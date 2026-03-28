from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from collections.abc import Callable
from typing import Any

from ..models.chat_models import TraceEvent
from ..utils.trace_payload_utils import build_trace_payload
from .executor import DAGExecutor
from .final_response_builder import FinalResponseBuilder
from .input_analyzer import InputAnalyzer
from .llm_backends import ClaudeLLMBackend, GeminiLLMBackend, LLMBackend
from .planner import AutoDAGPlanner, AnalysisResult, needs_research_text
from .provider_factories import build_default_llm_backend, build_default_search_provider
from .runtime_metrics import RuntimeMetrics
from .runtime_resilience import NodeCache, ShortTermMemoryStore, classify_error
from .skill_registry_factory import RegistryFactory, build_default_skill_registry
from .result_formatting import (
    collect_source_details_from_results,
    collect_sources_from_results,
    extract_result_text,
    render_result_for_user,
)
from .search_providers import (
    DuckDuckGoSearchProvider,
    FallbackSearchProvider,
    MockSearchProvider,
    SearchDocument,
    SearchProvider,
    SearchResultBatch,
)
from .semantic_router import EmbeddingService, SemanticRouter
from .skill_core import DAGNode, RoutedSkill, SkillContext, SkillMetadata, SkillRegistry, SkillResult
from .tool_analyzer import ToolAnalyzer
from .trace_event_formatter import build_execution_trace_entry, build_tool_call_detail, build_tool_result_detail
from .skills import PlanningSkill, ResearchSkill, SynthesizerSkill
from .trace_engine_protocol import TraceEngineProtocol




class OrchestratorSkillAgent(TraceEngineProtocol):
    _STOPWORDS = {
        "la",
        "là",
        "va",
        "và",
        "the",
        "for",
        "with",
        "that",
        "this",
        "cua",
        "của",
        "toi",
        "tôi",
        "ban",
        "bạn",
        "please",
    }

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        llm_backend: LLMBackend | None = None,
        search_provider: SearchProvider | None = None,
        registry: SkillRegistry | None = None,
        embedding_service: EmbeddingService | None = None,
        router: SemanticRouter | None = None,
        planner: AutoDAGPlanner | None = None,
        executor: DAGExecutor | None = None,
        analyzer: InputAnalyzer | None = None,
        registry_factory: RegistryFactory | None = None,
        final_response_builder: FinalResponseBuilder | None = None,
        llm_backend_builder: Callable[[str], LLMBackend] | None = None,
        search_provider_builder: Callable[[], SearchProvider] | None = None,
    ) -> None:
        self._llm_backend_builder = llm_backend_builder or self._build_default_llm_backend
        self._search_provider_builder = search_provider_builder or self._build_default_search_provider
        self.model = model
        self._llm_backend = llm_backend or self._llm_backend_builder(model)
        self._llm_provider = getattr(self._llm_backend, "provider", "custom")
        self._answer_cache: dict[str, str] = {}
        self._answer_payload_cache: dict[str, dict[str, Any]] = {}
        self._memory = ShortTermMemoryStore()
        self._search_provider = search_provider or self._search_provider_builder()
        self._registry_factory = registry_factory or build_default_skill_registry

        self._registry = registry or self._registry_factory(self._call_model, self._search_provider)

        self._embedding_service = embedding_service or EmbeddingService()
        self._router = router or SemanticRouter(self._registry, self._embedding_service)
        self._planner = planner or AutoDAGPlanner(self._router, self._call_model)
        self._executor = executor or DAGExecutor(self._registry)
        self._analyzer = analyzer or InputAnalyzer(
            self._call_model,
            lambda sid: self._memory.snapshot(sid),
            self._STOPWORDS,
        )
        self._final_response_builder = final_response_builder or FinalResponseBuilder()
        self._router_initialized = False
        self._metrics_service = RuntimeMetrics(self._llm_provider)
        self._metrics = self._metrics_service.state

    @staticmethod
    def _build_default_search_provider() -> SearchProvider:
        return build_default_search_provider()

    def _build_default_registry(self, search_provider: SearchProvider) -> SkillRegistry:
        # Backward-compatible wrapper kept for tests/extensions that call this method directly.
        return self._registry_factory(self._call_model, search_provider)

    @staticmethod
    def _build_default_llm_backend(model: str) -> LLMBackend:
        backend = build_default_llm_backend(
            model=model,
            claude_backend_factory=ClaudeLLMBackend,
            gemini_backend_factory=GeminiLLMBackend,
        )
        if not hasattr(backend, "generate"):
            raise TypeError("Default LLM backend factory must return object with generate().")
        return backend

    async def run(self, prompt: str, session_id: str, session_label: str) -> list[TraceEvent]:
        return [event async for event in self.stream(prompt, session_id, session_label)]

    async def stream(self, prompt: str, session_id: str, session_label: str) -> AsyncIterator[TraceEvent]:
        if not self._router_initialized:
            await self._router.init()
            self._router_initialized = True

        analysis = self._analyze_input(prompt, session_id)
        dag = await self._planner.build(analysis)
        self._apply_tool_hints(dag, analysis)
        dag_summary = "; ".join(
            f"{node.id}<-{node.depends_on or []}:{node.skill}[p={node.priority}]" for node in dag
        )
        self._metrics_service.mark_run_started(analysis["execution_mode"], len(dag))
        self._memory.remember(session_id, "user_prompt", prompt)
        self._memory.remember(session_id, "analysis", f"intent={analysis['intent']} keywords={analysis['keywords']}")
        self._metrics_service.update_memory_entries(self._memory.size(session_id))

        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=(
                    "Refining input + semantic analysis complete. "
                    f"intent={analysis['intent']}, sentiment={analysis['sentiment']}, keywords={analysis['keywords']}"
                ),
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
            )
        )
        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=f"Auto DAG planned with {len(dag)} nodes. {dag_summary}",
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
            )
        )

        results: dict[str, Any] = {}
        execution_trace: list[dict[str, str]] = []
        async for update in self._executor.execute_stream(
            dag,
            analysis["normalized_prompt"],
            recent_memory_getter=lambda: self._memory.snapshot(session_id),
        ):
            result = update.result
            results[update.node.id] = (
                result.data if result.success and result.data is not None else f"ERROR: {result.error or 'unknown error'}"
            )
            result_preview = extract_result_text(result.data if result.success else result.error)
            trace_entry = build_execution_trace_entry(update, result, result_preview)
            execution_trace.append(trace_entry)
            self._memory.remember(
                session_id,
                f"node:{update.node.id}",
                f"skill={update.skill_name} result={trace_entry['output']}",
            )
            self._metrics_service.update_memory_entries(self._memory.size(session_id))

            yield TraceEvent(
                **build_trace_payload(
                    event="tool_call",
                    detail=build_tool_call_detail(trace_entry),
                    agent="OrchestratorAgent",
                    branch=trace_entry["branch"],
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                )
            )
            yield TraceEvent(
                **build_trace_payload(
                    event="tool_result",
                    detail=build_tool_result_detail(trace_entry),
                    agent="AnswerSkillAgent",
                    branch=trace_entry["branch"],
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                )
            )

        final_answer, final_payload = self._get_final_response_builder().build_payload_from_results(results, analysis)
        self._answer_cache[prompt] = final_answer
        self._answer_payload_cache[prompt] = final_payload
        self._memory.remember(session_id, "final_answer", final_answer)
        self._record_execution_metrics(execution_trace)
        self._metrics_service.mark_completed()

        yield TraceEvent(
            **build_trace_payload(
                event="done",
                detail="DAG execution and aggregation completed.",
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
            )
        )

    def get_metrics(self) -> dict[str, Any]:
        return self._metrics_service.snapshot_with_breakers(
            self._executor.get_breaker_states(),
            self._executor.get_breaker_details(),
        )

    def get_claude_tools(self) -> list[dict[str, Any]]:
        return self._registry.get_claude_tools()

    def build_final_answer(self, prompt: str) -> str:
        if prompt in self._answer_cache:
            return self._answer_cache[prompt]
        return self._call_model(prompt)

    def build_final_payload(self, prompt: str) -> dict[str, Any]:
        if prompt in self._answer_payload_cache:
            return dict(self._answer_payload_cache[prompt])
        return {
            "type": "assistant_message",
            "content": self.build_final_answer(prompt),
        }

    def _analyze_input(self, prompt: str, session_id: str) -> AnalysisResult:
        return self._get_analyzer().analyze(prompt, session_id)

    def _analyze_input_llm(self, prompt: str, session_id: str) -> AnalysisResult:
        return self._get_analyzer().analyze_with_llm(prompt, session_id)

    def _analyze_input_rule_based(self, prompt: str) -> AnalysisResult:
        return self._get_analyzer().analyze_rule_based(prompt)

    def _get_analyzer(self) -> InputAnalyzer:
        analyzer = getattr(self, "_analyzer", None)
        if analyzer is None:
            analyzer = InputAnalyzer(
                self._call_model,
                lambda sid: self._memory.snapshot(sid),
                self._STOPWORDS,
            )
            self._analyzer = analyzer
        return analyzer

    def _get_final_response_builder(self) -> FinalResponseBuilder:
        builder = getattr(self, "_final_response_builder", None)
        if builder is None:
            builder = FinalResponseBuilder()
            self._final_response_builder = builder
        return builder

    def _select_final_answer(self, results: dict[str, Any], analysis: AnalysisResult) -> str:
        return self._get_final_response_builder().select_final_answer(results, analysis)

    def _record_execution_metrics(self, execution_trace: list[dict[str, str]]) -> None:
        self._metrics_service.record_execution_trace(execution_trace)

    @staticmethod
    def _apply_tool_hints(dag: list[DAGNode], analysis: AnalysisResult) -> None:
        """Attach selected tool hints to research nodes before execution."""
        for node in dag:
            if node.skill == "finance":
                node.input["selected_tool"] = "finance"
                node.input["selected_tool_confidence"] = "0.98"
                node.input["selected_tool_reason"] = "Finance skill requires finance tool"
                continue

            if node.skill != "research":
                continue

            description = str(node.input.get("description", "")).strip() or analysis["normalized_prompt"]
            suggestion = ToolAnalyzer.suggest_tool(description, analysis["normalized_prompt"])
            node.input["selected_tool"] = suggestion.tool_name
            node.input["selected_tool_confidence"] = f"{suggestion.confidence:.2f}"
            node.input["selected_tool_reason"] = suggestion.reason

    @staticmethod
    def _collect_sources_from_results(results: dict[str, Any]) -> list[str]:
        return collect_sources_from_results(results)

    @staticmethod
    def _collect_source_details_from_results(results: dict[str, Any]) -> list[dict[str, str]]:
        return collect_source_details_from_results(results)

    def _call_model(self, prompt: str) -> str:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._llm_backend.generate(self.model, prompt)
                return self._extract_response_text(response)
            except Exception as err:  # pragma: no cover
                last_error = err
                if classify_error(str(err)) != "transient" or attempt == 2:
                    break
                time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"{self._llm_provider} API error: {last_error}")

    @staticmethod
    def _extract_response_text(response: object) -> str:
        if hasattr(response, "text"):
            text = getattr(response, "text")
            return text.strip() if isinstance(text, str) and text.strip() else "(empty response)"
        return str(response) if response else "(empty response)"
