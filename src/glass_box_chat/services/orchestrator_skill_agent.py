from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from collections.abc import Callable
from typing import Any

from ..models.chat_models import TraceEvent
from ..utils.trace_payload_utils import build_trace_payload
from .executor import DAGExecutor
from .execution_gate import ExecutionGate
from .final_response_builder import FinalResponseBuilder
from .input_analyzer import InputAnalyzer
from .llm_backends import ClaudeLLMBackend, GeminiLLMBackend, LLMBackend
from .planner import AutoDAGPlanner, AnalysisResult
from .provider_factories import build_default_llm_backend, build_default_search_provider
from .runtime_metrics import RuntimeMetrics
from .runtime_resilience import NodeCache, ShortTermMemoryStore, classify_error
from .skill_registry_factory import RegistryFactory, build_default_skill_registry
from .result_formatting import (
    classify_source_niche,
    collect_source_details_from_results,
    collect_sources_from_results,
    extract_result_text,
)
from .search_providers import (
    SearchDocument,
    SearchProvider,
    SearchResultBatch,
)
from .semantic_router import EmbeddingService, SemanticRouter
from .skill_core import DAGNode, SkillContext, SkillMetadata, SkillRegistry, SkillResult
from .skills import PlanningSkill, ResearchSkill, SynthesizerSkill
from .tool_analyzer import ToolAnalyzer
from .trace_event_formatter import (
    build_analysis_detail,
    build_done_detail,
    build_execution_trace_entry,
    build_plan_detail,
    build_tool_call_detail,
    build_tool_phase_details,
    build_tool_result_detail,
)
from .trace_engine_protocol import TraceEngineProtocol
from .tools.tool_resolver import ToolResolver
from .search_decision_gate import SearchDecisionGate
from .meta_reasoning_agent import MetaReasoningAgent
from .answer_critic_agent import AnswerCriticAgent
from .parallel_execution_orchestrator import ParallelExecutionOrchestrator

__all__ = [
    "DAGExecutor",
    "DAGNode",
    "EmbeddingService",
    "NodeCache",
    "OrchestratorSkillAgent",
    "PlanningSkill",
    "ResearchSkill",
    "SearchDocument",
    "SearchProvider",
    "SearchResultBatch",
    "SemanticRouter",
    "ShortTermMemoryStore",
    "SkillContext",
    "SkillMetadata",
    "SkillRegistry",
    "SkillResult",
    "SynthesizerSkill",
]




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
        self._tool_resolver = ToolResolver()
        self._executor = executor or DAGExecutor(self._registry, tool_resolver=self._tool_resolver)
        self._analyzer = analyzer or InputAnalyzer(
            self._call_model,
            lambda sid: self._memory.snapshot(sid),
            self._STOPWORDS,
        )
        self._execution_gate = ExecutionGate(self._call_model)
        self._search_decision_gate = SearchDecisionGate(
            self._call_model,
            lambda sid: self._memory.snapshot(sid),
        )
        # Initialize Decision Intelligence Layer agents
        self._meta_reasoning_agent = MetaReasoningAgent(self._call_model)
        self._answer_critic_agent = AnswerCriticAgent(self._call_model)
        self._parallel_orchestrator = ParallelExecutionOrchestrator(self._call_model)
        
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

    async def run(self, prompt: str, session_id: str, session_label: str, message_id: str) -> list[TraceEvent]:
        return [event async for event in self.stream(prompt, session_id, session_label, message_id)]

    async def stream(self, prompt: str, session_id: str, session_label: str, message_id: str) -> AsyncIterator[TraceEvent]:
        if not self._router_initialized:
            await self._router.init()
            self._router_initialized = True

        # Phase 1: Input Analysis
        analysis = self._analyze_input(prompt, session_id)
        analysis = self._apply_search_decision_gate(analysis, session_id)
        analysis = self._apply_execution_gate(analysis)
        
        # Phase 2a: Decision Intelligence Layer - Meta-Reasoning (NEW)
        meta_reasoning = await self._apply_meta_reasoning(analysis, session_id)
        
        # Phase 2b: Decision Intelligence Layer - Parallel Execution (NEW)
        parallel_config = await self._apply_parallel_orchestration(meta_reasoning, analysis)
        
        # Phase 3: DAG Planning (with decision inputs)
        dag = await self._planner.build(analysis)
        
        # Convert to parallel DAG if needed (from parallel_config)
        if parallel_config.get("enable_parallel", False):
            dag = parallel_config.get("convert_to_parallel_dag", lambda d: d)(dag)
        
        self._apply_tool_hints(dag, analysis)
        dag_summary = "; ".join(
            f"{node.id}<-{node.depends_on or []}:{node.skill}[p={node.priority}]" for node in dag
        )
        self._metrics_service.mark_run_started(analysis["execution_mode"], len(dag))
        self._memory.remember(session_id, "chat_user", prompt)
        self._memory.remember(session_id, "user_prompt", prompt)
        self._memory.remember(session_id, "analysis", f"intent={analysis['intent']} keywords={analysis['keywords']}")
        self._memory.remember(session_id, "meta_reasoning", f"strategy={meta_reasoning.get('strategy', 'unknown')}")
        self._metrics_service.update_memory_entries(self._memory.size(session_id))

        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=build_analysis_detail(
                    intent=analysis["intent"],
                    sentiment=analysis["sentiment"],
                    keywords=analysis["keywords"],
                    execution_mode=analysis["execution_mode"],
                    normalized_prompt=analysis["normalized_prompt"],
                ),
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )
        
        # Emit Meta-Reasoning decision
        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=(
                    "Decision intelligence completed.\n"
                    f"Phase: decision_intelligence.\n"
                    f"Strategy: {meta_reasoning.get('strategy')}.\n"
                    f"Confidence: {meta_reasoning.get('confidence')}.\n"
                    f"Reason: {meta_reasoning.get('reason')}.\n"
                    f"Risk: {meta_reasoning.get('risk', {})}.\n"
                    f"Parallel enabled: {parallel_config.get('enable_parallel', False)}."
                ),
                agent="MetaReasoningAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )
        
        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=build_plan_detail(dag, dag_summary),
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )

        # Emit a first-class plan artifact so UI can display generated execution assets.
        yield TraceEvent(
            **build_trace_payload(
                event="artifact_created",
                detail="Execution plan artifact has been generated.",
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
                artifact={
                    "id": f"artifact-plan-{uuid.uuid4()}",
                    "type": "plan",
                    "title": "Execution Plan",
                    "status": "created",
                    "content": dag_summary,
                    "createdAt": time.strftime("%H:%M:%S"),
                },
                metadata={
                    "phase": "planning",
                    "nodeCount": len(dag),
                },
            )
        )

        for planned_node in dag:
            yield TraceEvent(
                **build_trace_payload(
                    event="node_start",
                    detail=(
                        f"Node {planned_node.id} is scheduled for skill '{planned_node.skill}' "
                        f"with dependencies: {', '.join(planned_node.depends_on) if planned_node.depends_on else 'none'}."
                    ),
                    agent="OrchestratorAgent",
                    branch=planned_node.branch,
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                    metadata={
                        "nodeId": planned_node.id,
                        "skill": planned_node.skill,
                        "deps": planned_node.depends_on,
                        "branch": planned_node.branch,
                        "phase": "scheduled",
                        "startedAtMs": int(time.time() * 1000),
                    },
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
                    event="subagent_start",
                    detail=f"Skill agent '{update.skill_name}' started execution for node {update.node.id}.",
                    agent="OrchestratorAgent",
                    branch=trace_entry["branch"],
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                    metadata=self._build_trace_metadata(trace_entry, phase="start"),
                )
            )

            yield TraceEvent(
                **build_trace_payload(
                    event="tool_call",
                    detail=build_tool_call_detail(trace_entry),
                    agent="OrchestratorAgent",
                    branch=trace_entry["branch"],
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                    metadata=self._build_trace_metadata(trace_entry, phase="call"),
                )
            )
            for phase_detail in build_tool_phase_details(trace_entry):
                yield TraceEvent(
                    **build_trace_payload(
                        event="thinking",
                        detail=phase_detail,
                        agent="OrchestratorAgent",
                        branch=trace_entry["branch"],
                        mode=analysis["execution_mode"],
                        session_id=session_id,
                        session_label=session_label,
                        message_id=message_id,
                        metadata=self._build_trace_metadata(trace_entry, phase="progress"),
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
                    message_id=message_id,
                    metadata=self._build_trace_metadata(trace_entry, phase="result"),
                )
            )

            yield TraceEvent(
                **build_trace_payload(
                    event="node_done",
                    detail=f"Node {update.node.id} finished with success={trace_entry.get('success') == 'true'}.",
                    agent="OrchestratorAgent",
                    branch=trace_entry["branch"],
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                    metadata=self._build_trace_metadata(trace_entry, phase="done"),
                )
            )

            yield TraceEvent(
                **build_trace_payload(
                    event="subagent_done",
                    detail=f"Skill agent '{update.skill_name}' completed node {update.node.id}.",
                    agent="OrchestratorAgent",
                    branch=trace_entry["branch"],
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                    metadata=self._build_trace_metadata(trace_entry, phase="subagent_done"),
                )
            )

            yield TraceEvent(
                **build_trace_payload(
                    event="artifact_updated",
                    detail=f"Evidence artifact updated from node {update.node.id}.",
                    agent="AnswerSkillAgent",
                    branch=trace_entry["branch"],
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                    artifact={
                        "id": f"artifact-evidence-{update.node.id}",
                        "type": "evidence",
                        "title": f"Evidence bundle ({update.node.id})",
                        "status": "updated",
                        "content": trace_entry.get("output", ""),
                        "createdAt": time.strftime("%H:%M:%S"),
                    },
                    metadata=self._build_trace_metadata(trace_entry, phase="artifact"),
                )
            )

        final_answer, final_payload = self._final_response_builder.build_payload_from_results(results, analysis)

        dual_niche_summary = (
            ((final_payload.get("reasoningQuality") or {}).get("dualNiche") or {}).get("summary")
            if isinstance(final_payload, dict)
            else None
        )
        if isinstance(dual_niche_summary, str) and dual_niche_summary.strip():
            yield TraceEvent(
                **build_trace_payload(
                    event="thinking",
                    detail=dual_niche_summary,
                    agent="OrchestratorAgent",
                    mode=analysis["execution_mode"],
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                    metadata={
                        "phase": "dual_niche_analysis",
                        "success": True,
                    },
                )
            )
        
        # Phase 5b: Quality Control - Answer Critic (NEW)
        synthesized = {
            "text": final_answer,
            "sources": collect_source_details_from_results(results),
        }
        critic_verdict = await self._apply_answer_critique(
            analysis,
            results,
            synthesized,
            session_id,
        )

        final_answer, final_payload = await self._augment_payload_with_quick_evidence(
            analysis,
            final_answer,
            final_payload,
            critic_verdict,
        )
        
        # Emit Critic verdict
        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=(
                    "Answer critic completed.\n"
                    "Phase: quality_control.\n"
                    f"Is safe: {critic_verdict.get('is_safe')}.\n"
                    f"Overall quality: {critic_verdict.get('overall_quality')}.\n"
                    f"Needs revision: {critic_verdict.get('needs_revision')}.\n"
                    f"Issues count: {len(critic_verdict.get('issues', []))}.\n"
                    f"Revision strategy: {critic_verdict.get('revision_strategy')}."
                ),
                agent="AnswerCriticAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )
        
        # Store final answer
        self._answer_cache[prompt] = final_answer
        self._answer_payload_cache[prompt] = final_payload
        self._memory.remember(session_id, "chat_assistant", final_answer)
        self._memory.remember(session_id, "final_answer", final_answer)
        self._memory.remember(session_id, "critic_verdict", f"quality={critic_verdict.get('overall_quality'):.2f} safe={critic_verdict.get('is_safe')}")
        self._record_execution_metrics(execution_trace)
        self._metrics_service.mark_completed()

        yield TraceEvent(
            **build_trace_payload(
                event="artifact_created",
                detail="Final response artifact has been created.",
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
                artifact={
                    "id": f"artifact-final-{uuid.uuid4()}",
                    "type": "final_response",
                    "title": "Final Response",
                    "status": "final",
                    "content": final_answer,
                    "createdAt": time.strftime("%H:%M:%S"),
                },
                metadata={
                    "phase": "finalize",
                    "success": True,
                    "sourceCount": len(final_payload.get("sources", [])) if isinstance(final_payload.get("sources", []), list) else 0,
                },
            )
        )

        yield TraceEvent(
            **build_trace_payload(
                event="done",
                detail=build_done_detail(
                    total_nodes=len(execution_trace),
                    successful_nodes=sum(1 for entry in execution_trace if entry.get("success") == "true"),
                    failed_nodes=sum(1 for entry in execution_trace if entry.get("success") != "true"),
                ),
                agent="OrchestratorAgent",
                mode=analysis["execution_mode"],
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
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
        return self._analyzer.analyze(prompt, session_id)

    def _apply_search_decision_gate(self, analysis: AnalysisResult, session_id: str) -> AnalysisResult:
        """Apply SearchDecisionGate: decide whether live/external data is needed."""
        return self._search_decision_gate.analyze_search_need(analysis, session_id)

    def _apply_execution_gate(self, analysis: AnalysisResult) -> AnalysisResult:
        return self._execution_gate.decide(analysis)

    async def _apply_meta_reasoning(self, analysis: dict, session_id: str) -> dict:
        """Apply MetaReasoningAgent: decide global execution strategy (direct / research_first / hybrid_parallel)."""
        result = await self._meta_reasoning_agent.analyze_strategy(
            analysis,
            session_memory=self._memory.snapshot(session_id),
            session_id=session_id,
        )
        return result.model_dump() if hasattr(result, 'model_dump') else result.dict()
    
    async def _apply_parallel_orchestration(
        self,
        meta_reasoning: dict,
        analysis: dict,
    ) -> dict:
        """Apply ParallelExecutionOrchestrator: decide whether to enable multi-path execution."""
        result = self._parallel_orchestrator.should_enable_parallel_execution(
            meta_reasoning,
            analysis,
            confidence_threshold=0.6,
        )
        return result.model_dump() if hasattr(result, 'model_dump') else result.dict()
    
    async def _apply_answer_critique(
        self,
        analysis: dict,
        dag_outputs: dict,
        synthesized: dict,
        session_id: str,
    ) -> dict:
        """Apply AnswerCriticAgent: quality-control gate (hallucination / evidence / contradiction checks)."""
        result = await self._answer_critic_agent.critique_output(
            analysis,
            dag_outputs,
            synthesized,
            session_id=session_id,
        )
        return result.model_dump() if hasattr(result, 'model_dump') else result.dict()

    def _record_execution_metrics(self, execution_trace: list[dict[str, str]]) -> None:
        self._metrics_service.record_execution_trace(execution_trace)

    @staticmethod
    def _build_trace_metadata(trace_entry: dict[str, str], phase: str) -> dict[str, object]:
        citations_raw = trace_entry.get("citations", "none")
        citations = [] if citations_raw in ("none", "", None) else [item for item in citations_raw.split(",") if item]
        return {
            "nodeId": trace_entry.get("node_id"),
            "skill": trace_entry.get("skill_name"),
            "deps": [] if trace_entry.get("depends_on") in (None, "-") else str(trace_entry["depends_on"]).split(","),
            "score": trace_entry.get("route_score"),
            "provider": trace_entry.get("provider"),
            "sourceCount": int(str(trace_entry.get("source_count", "0") or "0")),
            "citationCount": int(str(trace_entry.get("citation_count", "0") or "0")),
            "freshness": trace_entry.get("freshness"),
            "fallbackUsed": trace_entry.get("fallback_used") == "true",
            "cacheHit": trace_entry.get("cache_hit") == "true",
            "durationMs": int(str(trace_entry.get("duration_ms", "0") or "0")) if str(trace_entry.get("duration_ms", "0")).isdigit() else 0,
            "attempts": int(str(trace_entry.get("attempts", "0") or "0")) if str(trace_entry.get("attempts", "0")).isdigit() else 0,
            "success": trace_entry.get("success") == "true",
            "citations": citations,
            "branch": trace_entry.get("branch"),
            "phase": phase,
        }

    async def _augment_payload_with_quick_evidence(
        self,
        analysis: AnalysisResult,
        final_answer: str,
        final_payload: dict[str, Any],
        critic_verdict: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        quality = final_payload.get("reasoningQuality") if isinstance(final_payload, dict) else None
        coverage_ratio = float((quality or {}).get("coverageRatio", 1.0) or 1.0)

        dual_niche = (quality or {}).get("dualNiche") if isinstance(quality, dict) else None
        quant_sources = int((((dual_niche or {}).get("quantitative") or {}).get("sourceCount", 0) or 0))
        qual_sources = int((((dual_niche or {}).get("qualitative") or {}).get("sourceCount", 0) or 0))
        niche_balance = float((dual_niche or {}).get("niche_balance", 1.0) or 1.0)

        missing_niche: str | None = None
        if quant_sources == 0 and qual_sources > 0:
            missing_niche = "quantitative"
        elif qual_sources == 0 and quant_sources > 0:
            missing_niche = "qualitative"
        elif niche_balance < 0.65 and quant_sources != qual_sources:
            missing_niche = "quantitative" if quant_sources < qual_sources else "qualitative"

        needs_evidence_issue = False
        for issue in critic_verdict.get("issues", []) if isinstance(critic_verdict, dict) else []:
            issue_type = str(issue.get("type", "")).strip().lower() if isinstance(issue, dict) else ""
            if issue_type in {"needs_evidence", "potential_hallucination", "missing_context"}:
                needs_evidence_issue = True
                break

        if coverage_ratio >= 0.55 and not needs_evidence_issue and not missing_niche:
            return final_answer, final_payload

        query = str(analysis.get("normalized_prompt", "")).strip()
        if not query:
            return final_answer, final_payload

        search_batches: list[SearchResultBatch] = []
        try:
            if coverage_ratio < 0.55 or needs_evidence_issue:
                search_batches.append(await self._search_provider.search(query, limit=2))
            if missing_niche:
                niche_hint = (
                    "official data statistics metrics report"
                    if missing_niche == "quantitative"
                    else "expert analysis outlook sentiment commentary"
                )
                search_batches.append(await self._search_provider.search(f"{query} {niche_hint}", limit=3))
        except Exception:
            return final_answer, final_payload

        documents: list[SearchDocument] = []
        for batch in search_batches:
            documents.extend(batch.documents)
        if not documents:
            return final_answer, final_payload

        source_urls = final_payload.get("sources") if isinstance(final_payload.get("sources"), list) else []
        source_details = final_payload.get("sourceDetails") if isinstance(final_payload.get("sourceDetails"), list) else []
        evidence_ledger = final_payload.get("evidenceLedger") if isinstance(final_payload.get("evidenceLedger"), list) else []

        changed = False
        added_quant = 0
        added_qual = 0
        for doc in documents:
            doc_niche = classify_source_niche(doc.url, doc.snippet)
            if missing_niche and doc_niche != missing_niche:
                continue
            if doc.url not in source_urls:
                source_urls.append(doc.url)
                changed = True
            if not any(isinstance(item, dict) and item.get("url") == doc.url for item in source_details):
                source_details.append(
                    {
                        "title": doc.title,
                        "url": doc.url,
                        "freshness": doc.freshness,
                    }
                )
                changed = True
            if not any(isinstance(item, dict) and item.get("source") == doc.url for item in evidence_ledger):
                evidence_ledger.append(
                    {
                        "type": "quick_retrieval",
                        "claim": doc.snippet[:220],
                        "source": doc.url,
                        "evidence_item_id": f"quick_{abs(hash(doc.url))}",
                        "niche": doc_niche,
                    }
                )
                changed = True
                if doc_niche == "quantitative":
                    added_quant += 1
                elif doc_niche == "qualitative":
                    added_qual += 1

        if not changed:
            return final_answer, final_payload

        final_payload["sources"] = source_urls
        final_payload["sourceDetails"] = source_details
        final_payload["evidenceLedger"] = evidence_ledger

        if isinstance(quality, dict) and isinstance(quality.get("dualNiche"), dict):
            dual_niche_payload = quality["dualNiche"]
            quant_block = dual_niche_payload.get("quantitative") if isinstance(dual_niche_payload.get("quantitative"), dict) else {}
            qual_block = dual_niche_payload.get("qualitative") if isinstance(dual_niche_payload.get("qualitative"), dict) else {}

            quant_block["sourceCount"] = int(quant_block.get("sourceCount", 0) or 0) + added_quant
            quant_block["evidenceCount"] = int(quant_block.get("evidenceCount", 0) or 0) + added_quant
            qual_block["sourceCount"] = int(qual_block.get("sourceCount", 0) or 0) + added_qual
            qual_block["evidenceCount"] = int(qual_block.get("evidenceCount", 0) or 0) + added_qual

            total = max(int(quant_block["sourceCount"] + qual_block["sourceCount"]), 1)
            quant_ratio = float(quant_block["sourceCount"]) / float(total)
            dual_niche_payload["quantitative"] = quant_block
            dual_niche_payload["qualitative"] = qual_block
            dual_niche_payload["niche_balance"] = round(1.0 - abs(0.5 - quant_ratio), 2)

        final_payload["content"] = final_answer
        return final_answer, final_payload

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

            if "selected_tool" in node.input:
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
