from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Literal, Protocol, TypedDict

from pydantic import BaseModel, Field, field_validator

from .skill_core import DAGNode, RoutedSkill

TIME_SENSITIVE_HINTS = (
    "hôm nay",
    "today",
    "latest",
    "mới nhất",
    "weather",
    "thời tiết",
    "news",
    "tin tức",
    "price",
    "giá",
    "hiện tại",
    "current",
)

WEATHER_HINTS = (
    "weather",
    "thời tiết",
    "thoi tiet",
    "forecast",
    "dự báo",
    "du bao",
    "ngày mai",
    "ngay mai",
    "tomorrow",
)

MARKET_HINTS = (
    "gia vang",
    "giá vàng",
    "gold price",
    "xau",
    "xauusd",
    "crypto",
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "tỷ giá",
    "ty gia",
    "exchange rate",
    "forex",
)

RESEARCH_HINTS = (
    "nghiên cứu",
    "tra cứu",
    "tìm thông tin",
    "search",
    "research",
    *TIME_SENSITIVE_HINTS,
)

EXPLICIT_RESEARCH_HINTS = (
    "nghiên cứu",
    "tra cứu",
    "tìm thông tin",
    "search",
    "research",
)


class AnalysisResult(TypedDict):
    original_prompt: str
    normalized_prompt: str
    intent: str
    sentiment: str
    keywords: list[str]
    sub_tasks: list[dict[str, str]]
    execution_mode: str


class PlannerDependencyModel(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    depends_on: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("planner dependency id cannot be empty")
        return trimmed

    @field_validator("depends_on")
    @classmethod
    def normalize_depends_on(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            cleaned = str(item).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class PlannerDependenciesEnvelopeModel(BaseModel):
    dependencies: list[PlannerDependencyModel] = Field(default_factory=list, max_length=12)


class RouterProtocol(Protocol):
    async def route(self, task: dict[str, object]) -> RoutedSkill: ...


def is_time_sensitive_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in TIME_SENSITIVE_HINTS)


def needs_research_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in RESEARCH_HINTS)


def is_weather_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in WEATHER_HINTS)


def is_explicit_research_task(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in EXPLICIT_RESEARCH_HINTS)


def is_market_data_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in MARKET_HINTS)


class AutoDAGPlanner:
    def __init__(self, router: RouterProtocol, llm_json_inferer: Callable[[str], str]) -> None:
        self._router = router
        self._llm_json_inferer = llm_json_inferer

    async def build(self, analysis: AnalysisResult) -> list[DAGNode]:
        if analysis.get("intent") == "market_price" or is_market_data_text(analysis["normalized_prompt"]):
            normalized_prompt = analysis["normalized_prompt"]
            return [
                DAGNode(
                    id="task-1",
                    skill="finance",
                    input={
                        "id": "task-1",
                        "description": normalized_prompt,
                        "routed_skill": "finance",
                        "route_score": "intent_market_price",
                        "cache_policy": "bypass",
                        "selected_tool": "finance",
                        "selected_tool_confidence": "0.98",
                        "selected_tool_reason": "Market price intent detected",
                    },
                    depends_on=[],
                    branch="main",
                    priority=130,
                ),
                DAGNode(
                    id="synthesis",
                    skill="synthesizer",
                    input={"description": "Synthesize market data output"},
                    depends_on=["task-1"],
                    branch="main",
                    priority=-1,
                ),
            ]

        branches = ["A", "B", "C", "main"]
        nodes: list[DAGNode] = []
        planned_tasks = self._inject_research_tasks(analysis["sub_tasks"], analysis["normalized_prompt"])

        for index, task in enumerate(planned_tasks):
            routed = await self._router.route(task)
            routed_skill = routed.skill_name

            # Guardrail: regular task nodes should never execute synthesizer directly.
            if routed_skill == "synthesizer":
                description = str(task.get("description", ""))
                routed_skill = "research" if needs_research_text(description) else "general_answer"

            nodes.append(
                DAGNode(
                    id=task["id"],
                    skill=routed_skill,
                    input={
                        **task,
                        "routed_skill": routed_skill,
                        "route_score": "fallback" if routed.used_fallback else f"{routed.final_score:.3f}",
                        "cache_policy": "bypass" if routed_skill == "research" else "default",
                    },
                    depends_on=[],
                    branch=branches[min(index, len(branches) - 1)],
                    priority=self._estimate_priority(task["description"], routed),
                )
            )

            nodes = self._collapse_weather_research_nodes(nodes, analysis["normalized_prompt"])

        dependencies = await self._infer_dependencies(nodes, analysis["normalized_prompt"])
        dependencies = self._enforce_research_dependencies(dependencies, nodes, analysis["normalized_prompt"])
        for node in nodes:
            node.depends_on = dependencies.get(node.id, [])

        if self._detect_cycle(nodes):
            sequential = self._build_sequential_fallback(nodes)
            for node in nodes:
                node.depends_on = sequential.get(node.id, [])

        should_add_synthesis = len(nodes) > 1 or any(node.skill == "research" for node in nodes)
        if should_add_synthesis:
            nodes.append(
                DAGNode(
                    id="synthesis",
                    skill="synthesizer",
                    input={"description": "Synthesize all task outputs"},
                    depends_on=[node.id for node in nodes],
                    branch="main",
                    priority=-1,
                )
            )

        return nodes

    @staticmethod
    def _collapse_weather_research_nodes(nodes: list[DAGNode], normalized_prompt: str) -> list[DAGNode]:
        """For pure weather prompts, keep a single research node to avoid duplicate tool calls."""
        if not is_weather_text(normalized_prompt):
            return nodes

        non_synth_nodes = [node for node in nodes if node.skill != "synthesizer"]
        if len(non_synth_nodes) <= 1:
            return nodes
        if any(node.skill != "research" for node in non_synth_nodes):
            return nodes

        # Keep the highest-priority research node only.
        best = max(non_synth_nodes, key=lambda node: (node.priority, -len(node.depends_on), node.id))
        return [best]

    def _inject_research_tasks(
        self,
        sub_tasks: list[dict[str, str]],
        normalized_prompt: str,
    ) -> list[dict[str, str]]:
        normalized_tasks = [
            {"id": f"task-{index + 1}", "description": str(task["description"]).strip()}
            for index, task in enumerate(sub_tasks)
            if str(task.get("description", "")).strip()
        ]

        if not is_time_sensitive_text(normalized_prompt):
            return normalized_tasks

        if any(is_explicit_research_task(task["description"]) for task in normalized_tasks):
            return normalized_tasks

        injected = [{"id": "task-0", "description": f"Nghiên cứu thông tin mới nhất cho: {normalized_prompt}"}, *normalized_tasks]
        return [
            {"id": f"task-{index + 1}", "description": task["description"]}
            for index, task in enumerate(injected)
        ]

    async def _infer_dependencies(self, nodes: list[DAGNode], normalized_prompt: str) -> dict[str, list[str]]:
        try:
            inferred = await self._infer_dependencies_with_llm(nodes, normalized_prompt)
            normalized = self._normalize_dependencies(inferred, nodes)
            if self._looks_reasonable(normalized, nodes):
                return normalized
        except Exception:
            pass

        return self._infer_dependencies_rule(nodes)

    async def _infer_dependencies_with_llm(self, nodes: list[DAGNode], normalized_prompt: str) -> dict[str, list[str]]:
        tasks = "\n".join(f"{node.id}: {node.input.get('description', '')}" for node in nodes)
        prompt = (
            "You are a planning engine.\n"
            "Given a list of tasks, determine dependencies.\n"
            "Rules:\n"
            "- If a task needs information from another task, add that dependency\n"
            "- Independent tasks must have []\n"
            "- Never depend on a later task\n"
            "- Avoid cycles\n"
            "- Return valid JSON only\n"
            "- Use this exact shape only: {\"dependencies\":[{\"id\":\"task-1\",\"depends_on\":[]}] }\n"
            "- Every task id must appear exactly once in dependencies\n\n"
            f"Normalized prompt: {normalized_prompt}\n\n"
            f"Tasks:\n{tasks}\n\n"
            "Return JSON like:\n"
            '{"dependencies":[{"id":"task-1","depends_on":[]},{"id":"task-2","depends_on":["task-1"]}]}'
        )
        response = await asyncio.to_thread(self._llm_json_inferer, prompt)
        json_payload = self._extract_json_payload(response)
        parsed = PlannerDependenciesEnvelopeModel.model_validate(json_payload)
        dependency_map = {item.id: item.depends_on for item in parsed.dependencies}

        missing_ids = [node.id for node in nodes if node.id not in dependency_map]
        if missing_ids:
            raise ValueError(f"Planner LLM response omitted task ids: {missing_ids}")

        return dependency_map

    def _infer_dependencies_rule(self, nodes: list[DAGNode]) -> dict[str, list[str]]:
        deps: dict[str, list[str]] = {node.id: [] for node in nodes}
        compare_ids: list[str] = []

        for index, node in enumerate(nodes):
            description = str(node.input.get("description", "")).lower()
            previous_ids = [previous.id for previous in nodes[:index]]

            if any(keyword in description for keyword in ("so sánh", "compare", "khác nhau", "đánh giá")):
                deps[node.id] = previous_ids
                compare_ids.append(node.id)
                continue

            if any(keyword in description for keyword in ("ví dụ code", "code example", "mã", "snippet", "ví dụ")):
                deps[node.id] = compare_ids[:] if compare_ids else previous_ids[-1:]
                continue

            if any(keyword in description for keyword in ("tổng hợp", "synthesize", "kết luận")):
                deps[node.id] = previous_ids
                continue

            if node.skill == "synthesizer" and previous_ids:
                deps[node.id] = previous_ids

        return deps

    def _normalize_dependencies(self, raw: dict[str, list[str]], nodes: list[DAGNode]) -> dict[str, list[str]]:
        valid_ids = {node.id for node in nodes}
        normalized: dict[str, list[str]] = {node.id: [] for node in nodes}
        for node in nodes:
            for dep in raw.get(node.id, []):
                if dep in valid_ids and dep != node.id and dep not in normalized[node.id]:
                    normalized[node.id].append(dep)
        return normalized

    def _enforce_research_dependencies(
        self,
        dependencies: dict[str, list[str]],
        nodes: list[DAGNode],
        normalized_prompt: str,
    ) -> dict[str, list[str]]:
        if not is_time_sensitive_text(normalized_prompt):
            return dependencies

        research_ids = [node.id for node in nodes if node.skill == "research"]
        if not research_ids:
            return dependencies

        enforced = {node_id: list(dep_ids) for node_id, dep_ids in dependencies.items()}
        for node in nodes:
            if node.skill in {"research", "synthesizer"}:
                continue
            node_deps = enforced.setdefault(node.id, [])
            for research_id in research_ids:
                if research_id != node.id and research_id not in node_deps:
                    node_deps.insert(0, research_id)
        return enforced

    def _looks_reasonable(self, dependencies: dict[str, list[str]], nodes: list[DAGNode]) -> bool:
        if not dependencies:
            return False
        node_ids = [node.id for node in nodes]
        node_id_set = set(node_ids)
        node_position = {node_id: index for index, node_id in enumerate(node_ids)}

        if any(node.id not in dependencies for node in nodes):
            return False

        for node in nodes:
            dep_ids = dependencies.get(node.id, [])
            if len(dep_ids) != len(set(dep_ids)):
                return False
            for dep_id in dep_ids:
                if dep_id not in node_id_set or dep_id == node.id:
                    return False
                if node_position[dep_id] >= node_position[node.id]:
                    return False

        hydrated_nodes = [
            DAGNode(
                id=node.id,
                skill=node.skill,
                input=node.input,
                depends_on=list(dependencies.get(node.id, [])),
                branch=node.branch,
                priority=node.priority,
            )
            for node in nodes
        ]
        if self._detect_cycle(hydrated_nodes):
            return False

        compare_nodes = [node for node in nodes if node.skill == "compare"]
        for node in compare_nodes:
            if node_position[node.id] > 0 and not dependencies.get(node.id):
                return False

        synthesizer_nodes = [node for node in nodes if node.skill == "synthesizer"]
        for node in synthesizer_nodes:
            if node_position[node.id] > 0 and not dependencies.get(node.id):
                return False

        return True

    def _detect_cycle(self, nodes: list[DAGNode]) -> bool:
        node_map = {node.id: node for node in nodes}
        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(node_id: str) -> bool:
            if node_id in stack:
                return True
            if node_id in visited:
                return False

            visited.add(node_id)
            stack.add(node_id)
            node = node_map[node_id]
            for dep in node.depends_on:
                if dep in node_map and dfs(dep):
                    return True
            stack.remove(node_id)
            return False

        return any(dfs(node.id) for node in nodes)

    def _build_sequential_fallback(self, nodes: list[DAGNode]) -> dict[str, list[str]]:
        sequential: dict[str, list[str]] = {}
        previous_id: str | None = None
        for node in nodes:
            sequential[node.id] = [previous_id] if previous_id is not None else []
            previous_id = node.id
        return sequential

    @staticmethod
    def _extract_json_payload(raw: str) -> dict[str, Any]:
        candidates = [raw.strip()]
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1).strip())

        decoder = json.JSONDecoder()
        for candidate in candidates:
            for match in re.finditer(r"\{", candidate):
                try:
                    parsed, end_index = decoder.raw_decode(candidate[match.start() :])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    trailing = candidate[match.start() + end_index :].strip()
                    if trailing and not trailing.startswith("```"):
                        continue
                    return parsed

        raise ValueError("No valid JSON object found in planner LLM response.")

    @staticmethod
    def _extract_json_object(raw: str) -> str:
        return json.dumps(AutoDAGPlanner._extract_json_payload(raw), ensure_ascii=False)

    @staticmethod
    def _estimate_priority(description: str, routed: RoutedSkill) -> int:
        lowered = description.lower()
        bonus = 0
        if any(token in lowered for token in ("khẩn", "urgent", "quan trọng", "critical")):
            bonus += 40
        if any(token in lowered for token in ("tóm tắt", "summary", "nhanh")):
            bonus += 10
        return int(routed.final_score * 100) + bonus
