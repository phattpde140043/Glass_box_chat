from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any, Callable

from .result_formatting import extract_result_text
from .runtime_resilience import CircuitBreaker, NodeCache, classify_error
from .schema_validation import validate_against_json_schema
from .skill_core import DAGNode, ExecutionUpdate, SkillAgent, SkillContext, SkillRegistry, SkillResult


class DAGExecutor:
    def __init__(
        self,
        registry: SkillRegistry,
        *,
        max_concurrency: int = 4,
        node_timeout_seconds: float = 12.0,
        retries: int = 2,
        cache: NodeCache | None = None,
        breaker_fail_threshold: int = 5,
        breaker_recovery_timeout_seconds: float = 15.0,
    ) -> None:
        self._registry = registry
        self._max_concurrency = max(1, max_concurrency)
        self._node_timeout_seconds = node_timeout_seconds
        self._retries = retries
        self._cache = cache or NodeCache()
        self._breaker_fail_threshold = breaker_fail_threshold
        self._breaker_recovery_timeout_seconds = breaker_recovery_timeout_seconds
        self._breakers: dict[str, CircuitBreaker] = {}
        self._tool_instances: dict[str, object] = {}

    async def execute(
        self,
        nodes: list[DAGNode],
        normalized_prompt: str,
        recent_memory_getter: Callable[[], str] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        results: dict[str, Any] = {}
        execution_trace: list[dict[str, str]] = []
        async for update in self.execute_stream(nodes, normalized_prompt, recent_memory_getter=recent_memory_getter):
            result = update.result
            results[update.node.id] = (
                result.data if result.success and result.data is not None else f"ERROR: {result.error or 'unknown error'}"
            )
            execution_trace.append(
                {
                    "node_id": update.node.id,
                    "skill_name": update.skill_name,
                    "branch": update.node.branch,
                    "depends_on": ",".join(update.node.depends_on) if update.node.depends_on else "-",
                    "route_score": str(update.node.input.get("route_score", "n/a")),
                    "success": "true" if result.success else "false",
                    "duration_ms": str((result.metadata or {}).get("duration_ms", "n/a")),
                    "cache_hit": "true" if (result.metadata or {}).get("cache_hit") else "false",
                    "attempts": str((result.metadata or {}).get("attempts", "n/a")),
                    "priority": str(update.node.priority),
                    "error_type": str((result.metadata or {}).get("error_type", "none")),
                    "output": extract_result_text(result.data if result.success else result.error)[:220],
                }
            )
        return results, execution_trace

    async def execute_stream(
        self,
        nodes: list[DAGNode],
        normalized_prompt: str,
        recent_memory_getter: Callable[[], str] | None = None,
    ) -> AsyncIterator[ExecutionUpdate]:
        results: dict[str, Any] = {}
        completed: set[str] = set()
        pending: dict[str, DAGNode] = {node.id: node for node in nodes}
        in_flight: dict[asyncio.Task[tuple[DAGNode, SkillResult, str]], DAGNode] = {}

        def current_memory() -> str:
            return recent_memory_getter() if recent_memory_getter is not None else ""

        while pending or in_flight:
            ready_nodes = sorted(
                [
                    node
                    for node in pending.values()
                    if all(dep in completed for dep in node.depends_on)
                ],
                key=lambda node: (-node.priority, len(node.depends_on), node.id),
            )

            while ready_nodes and len(in_flight) < self._max_concurrency:
                node = ready_nodes.pop(0)
                pending.pop(node.id, None)
                task = asyncio.create_task(
                    self._run_node_with_guard(
                        node,
                        results,
                        normalized_prompt,
                        current_memory(),
                    )
                )
                in_flight[task] = node

            if not in_flight:
                raise RuntimeError("Circular dependency detected in DAG.")

            done, _ = await asyncio.wait(in_flight.keys(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                in_flight.pop(task, None)
                node, result, skill_name = await task
                results[node.id] = result.data if result.success and result.data is not None else f"ERROR: {result.error or 'unknown error'}"
                completed.add(node.id)
                yield ExecutionUpdate(node=node, result=result, skill_name=skill_name)

    def get_breaker_states(self) -> dict[str, bool]:
        return {name: breaker.snapshot()["state"] == "open" for name, breaker in self._breakers.items()}

    def get_breaker_details(self) -> dict[str, dict[str, Any]]:
        return {name: breaker.snapshot() for name, breaker in self._breakers.items()}

    async def _run_node_with_guard(
        self,
        node: DAGNode,
        results: dict[str, Any],
        normalized_prompt: str,
        recent_memory: str,
    ) -> tuple[DAGNode, SkillResult, str]:
        skill = self._registry.get(node.skill)
        if skill is None:
            return node, SkillResult(success=False, error=f"Skill {node.skill} not found"), node.skill

        schema_error = self._validate_skill_input(skill, node.input)
        if schema_error is not None:
            return (
                node,
                SkillResult(
                    success=False,
                    error=schema_error,
                    metadata={"duration_ms": 0, "cache_hit": False, "attempts": 0, "error_type": "permanent"},
                ),
                node.skill,
            )

        dependency_outputs = {dep: results[dep] for dep in node.depends_on if dep in results}
        bypass_cache = str(node.input.get("cache_policy", "default")) == "bypass"
        cache_key = self._cache.build_key(node, normalized_prompt, dependency_outputs, recent_memory)
        cached = None if bypass_cache else self._cache.get(cache_key)
        if cached is not None:
            return (
                node,
                SkillResult(
                    success=True,
                    data=cached,
                    metadata={"duration_ms": 0, "cache_hit": True, "attempts": 0, "error_type": "none"},
                ),
                node.skill,
            )

        breaker = self._breakers.setdefault(
            node.skill,
            CircuitBreaker(
                fail_threshold=self._breaker_fail_threshold,
                recovery_timeout_seconds=self._breaker_recovery_timeout_seconds,
            ),
        )
        if not breaker.allow_request():
            return (
                node,
                SkillResult(
                    success=False,
                    error="circuit_open",
                    metadata={"duration_ms": 0, "cache_hit": False, "attempts": 0, "error_type": "system"},
                ),
                node.skill,
            )

        started_at = time.perf_counter()
        result = await self._run_with_retry(skill, node, dependency_outputs, normalized_prompt, recent_memory)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        metadata = {**(result.metadata or {}), "duration_ms": duration_ms, "cache_hit": False}
        result.metadata = metadata
        if result.success:
            breaker.record_success()
            if result.data is not None and not bypass_cache:
                self._cache.set(cache_key, result.data)
        else:
            breaker.record_failure()
        return node, result, node.skill

    @staticmethod
    def _validate_skill_input(skill: SkillAgent, input_data: dict[str, object]) -> str | None:
        schema = skill.metadata.input_schema
        if not schema:
            return None
        try:
            validate_against_json_schema(input_data, schema)
            return None
        except ValueError as err:
            return f"invalid_skill_input: {err}"

    async def _run_with_retry(
        self,
        skill: SkillAgent,
        node: DAGNode,
        dependency_outputs: dict[str, Any],
        normalized_prompt: str,
        recent_memory: str,
    ) -> SkillResult:
        last_result = SkillResult(success=False, error="unknown_error", metadata={"error_type": "system"})
        selected_tool = self._resolve_selected_tool(node.input.get("selected_tool"))
        for attempt in range(self._retries + 1):
            try:
                context = SkillContext(
                    input=node.input,
                    normalized_prompt=normalized_prompt,
                    dependency_outputs=dependency_outputs,
                    recent_memory=recent_memory,
                    selected_tool=selected_tool,
                )
                result = await asyncio.wait_for(skill.execute(context), timeout=self._node_timeout_seconds)
                error_text = result.error or ""
                error_type = classify_error(error_text) if not result.success and error_text else "transient"
                result.metadata = {
                    **(result.metadata or {}),
                    "attempts": attempt + 1,
                    "error_type": error_type if not result.success else "none",
                }
                if result.success:
                    return result
                last_result = result
                if error_type == "permanent":
                    return last_result
            except asyncio.TimeoutError:
                last_result = SkillResult(
                    success=False,
                    error="timeout",
                    metadata={"attempts": attempt + 1, "error_type": "transient"},
                )
            except Exception as err:
                error_type = classify_error(str(err))
                last_result = SkillResult(
                    success=False,
                    error=str(err),
                    metadata={"attempts": attempt + 1, "error_type": error_type},
                )
                if error_type == "permanent":
                    return last_result

            if attempt < self._retries and (last_result.metadata or {}).get("error_type") == "transient":
                await asyncio.sleep(0.5 * (2**attempt))
            else:
                break

        return last_result

    def _resolve_selected_tool(self, selected_tool: object | None) -> object | None:
        if selected_tool is None:
            return None

        # Already a tool-like object.
        if hasattr(selected_tool, "execute") and hasattr(selected_tool, "name"):
            return selected_tool

        if not isinstance(selected_tool, str):
            return None

        tool_name = selected_tool.strip().lower()
        if not tool_name:
            return None

        cached = self._tool_instances.get(tool_name)
        if cached is not None:
            return cached

        try:
            from .tools import CalculatorTool, FetchPageTool, FinanceTool, NewsAPITool, WeatherTool, WebSearchTool
        except Exception:
            return None

        factories = {
            "web_search": WebSearchTool,
            "weather": WeatherTool,
            "news_api": NewsAPITool,
            "fetch_page": FetchPageTool,
            "calculator": CalculatorTool,
            "finance": FinanceTool,
        }
        factory = factories.get(tool_name)
        if factory is None:
            return None

        instance = factory()
        self._tool_instances[tool_name] = instance
        return instance
