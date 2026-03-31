from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, NotRequired, Protocol, TypedDict

from pydantic import BaseModel, Field, field_validator

from .skill_core import DAGNode, RoutedSkill

TIME_SENSITIVE_HINTS = (
    "today",
    "latest",
    "weather",
    "news",
    "price",
    "current",
)

WEATHER_HINTS = (
    "weather",
    "forecast",
    "rain",
    "snow",
    "temperature",
    "humidity",
)

# Time-only words — NOT standalone weather signals; only amplify when a core weather term is also present.
_WEATHER_TIME_WORDS = ("tomorrow",)

MARKET_HINTS = (
    "gold price",
    "xau",
    "xauusd",
    "crypto",
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "exchange rate",
    "forex",
)

MARKET_ANALYSIS_HINTS = (
    "outlook",
    "trend",
    "assessment",
    "analyze",
    "analysis",
)

GENERIC_ANALYSIS_HINTS = (
    "trend",
    "outlook",
    "assessment",
    "analyze",
    "analysis",
    "impact",
)

COMMODITY_HINTS = (
    "cafe",
    "coffee",
    "arabica",
    "robusta",
    "commodity",
    "pepper",
)

RESEARCH_HINTS = (
    "search",
    "research",
    *TIME_SENSITIVE_HINTS,
)

LOOKUP_HINTS = (
    "information search",
    "lookup",
    "find information",
    "who is",
    "what is",
)

LOCAL_DISCOVERY_HINTS = (
    "restaurant",
    "restaurants",
    "hotel",
    "hotels",
    "resort",
    "resorts",
    "homestay",
    "homestays",
    "attraction",
    "attractions",
    "things to do",
    "near me",
    "food",
    "foods",
    "eat",
    "eating",
    "eating out",
    "dining",
    "dine",
    "breakfast",
    "lunch",
    "dinner",
    "brunch",
    "meal",
    "meals",
    "cuisine",
    "traditional food",
    "street food",
    "vacation",
)

TRAVEL_PLAN_HINTS = (
    "travel plan",
    "itinerary",
    "2 day",
    "3 day",
)

SIMPLE_FACT_HINTS = (
    "what is",
    "who is",
    "population",
    "capital",
    "definition",
    "meaning",
)

EXPLICIT_RESEARCH_HINTS = (
    "search",
    "research",
)

GREETING_HINTS = (
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
)


class AnalysisResult(TypedDict):
    original_prompt: str
    normalized_prompt: str
    intent: str
    sentiment: str
    keywords: list[str]
    sub_tasks: list[dict[str, str]]
    execution_mode: str
    time_window: str
    confidence: float
    intent_tier: NotRequired[str]
    need_pipeline: NotRequired[bool]
    need_tools: NotRequired[bool]
    decision_confidence: NotRequired[float]
    decision_reason: NotRequired[str]
    intent_candidates: NotRequired[list[dict]]
    is_ambiguous: NotRequired[bool]
    detected_input_language: NotRequired[str]
    response_language: NotRequired[str]
    explicit_response_language: NotRequired[bool]
    language_confidence: NotRequired[float]


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
    # Require at least one genuine weather vocabulary term.
    # Time words alone ("tomorrow", "ngày mai") must not trigger weather routing
    # because they appear in unrelated queries ("find food in Milan tomorrow").
    return any(token in lowered for token in WEATHER_HINTS)


def is_explicit_research_task(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in EXPLICIT_RESEARCH_HINTS)


def is_greeting_text(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", text.lower()).strip()
    if not lowered:
        return False
    if is_market_data_text(lowered) or is_market_analysis_text(lowered):
        return False
    if is_lookup_text(lowered) or needs_research_text(lowered) or is_weather_text(lowered):
        return False
    if any(token in lowered for token in GENERIC_ANALYSIS_HINTS):
        return False

    words = [token for token in re.split(r"[^\wÀ-ỹ]+", lowered) if token]
    if len(words) > 6:
        return False
    return _contains_hint(lowered, GREETING_HINTS)


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    tokens = {token for token in re.split(r"[^\wÀ-ỹ]+", lowered) if token}
    for hint in hints:
        normalized_hint = hint.lower()
        if " " in normalized_hint:
            if normalized_hint in lowered:
                return True
            continue
        if normalized_hint in tokens:
            return True
    return False


def is_market_data_text(text: str) -> bool:
    return _contains_hint(text, MARKET_HINTS)


def is_lookup_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in LOOKUP_HINTS)


def is_local_discovery_text(text: str) -> bool:
    lowered = text.lower()
    return _contains_hint(lowered, LOCAL_DISCOVERY_HINTS)


def is_travel_plan_text(text: str) -> bool:
    lowered = text.lower()
    return _contains_hint(lowered, TRAVEL_PLAN_HINTS)


def is_simple_fact_text(text: str) -> bool:
    lowered = text.lower().strip()
    if is_market_data_text(lowered) or is_market_analysis_text(lowered):
        return False
    if any(token in lowered for token in ("today", "latest", "hôm nay", "mới nhất", "real-time", "realtime")):
        return False
    return any(token in lowered for token in SIMPLE_FACT_HINTS) and len(lowered.split()) <= 14


def is_market_analysis_text(text: str) -> bool:
    lowered = text.lower()
    has_analysis_signal = _contains_hint(lowered, MARKET_ANALYSIS_HINTS)
    has_subject_signal = _contains_hint(lowered, (*COMMODITY_HINTS, *MARKET_HINTS))
    has_time_signal = any(token in lowered for token in ("tháng", "thang", "month", "tuần", "tuan", "week", "quý", "quy", "recent", "gần đây", "gan day"))
    return has_analysis_signal and (has_subject_signal or has_time_signal)


def is_trend_analysis_text(text: str) -> bool:
    lowered = text.lower()
    has_analysis_signal = _contains_hint(lowered, MARKET_ANALYSIS_HINTS)
    has_time_signal = any(token in lowered for token in ("tháng", "thang", "month", "tuần", "tuan", "week", "quý", "quy", "recent", "gần đây", "gan day", "quarter", "year"))
    has_subject_signal = _contains_hint(lowered, (*COMMODITY_HINTS, *MARKET_HINTS))
    return has_analysis_signal and (has_time_signal or has_subject_signal)


def infer_time_window(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("hôm nay", "hom nay", "today", "intraday")):
        return "intraday"
    if any(token in lowered for token in ("tuần", "tuan", "week", "weekly")):
        return "1w"
    if any(token in lowered for token in ("tháng", "thang", "month", "monthly")):
        return "1m"
    if any(token in lowered for token in ("quý", "quy", "quarter")):
        return "1q"
    if any(token in lowered for token in ("năm", "nam", "year", "yearly")):
        return "1y"
    if any(token in lowered for token in ("gần đây", "gan day", "recent", "latest")):
        return "recent"
    return "unspecified"


def infer_market_subject(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("cà phê", "ca phe", "cafe", "coffee", "arabica", "robusta")):
        return "thị trường cà phê thế giới"
    if any(token in lowered for token in ("hồ tiêu", "ho tieu", "pepper")):
        return "thị trường hồ tiêu thế giới"
    if any(token in lowered for token in ("gia vang", "giá vàng", "gold", "xau", "xauusd")):
        return "thị trường vàng"
    if any(token in lowered for token in ("bitcoin", "btc", "ethereum", "eth", "crypto")):
        return "thị trường crypto"
    return "thị trường mục tiêu"


class AutoDAGPlanner:
    def __init__(self, router: RouterProtocol, llm_json_inferer: Callable[[str], str]) -> None:
        self._router = router
        self._llm_json_inferer = llm_json_inferer

    async def build(self, analysis: AnalysisResult) -> list[DAGNode]:
        normalized_prompt = analysis["normalized_prompt"]

        if analysis.get("need_pipeline") is False:
            return [
                DAGNode(
                    id="task-1",
                    skill="general_answer",
                    input={
                        "id": "task-1",
                        "description": normalized_prompt,
                        "routed_skill": "general_answer",
                        "route_score": "execution_gate_direct",
                        "cache_policy": "default",
                    },
                    depends_on=[],
                    branch="main",
                    priority=94,
                )
            ]

        if is_greeting_text(normalized_prompt):
            return [
                DAGNode(
                    id="task-1",
                    skill="general_answer",
                    input={
                        "id": "task-1",
                        "description": normalized_prompt,
                        "routed_skill": "general_answer",
                        "route_score": "intent_greeting_direct",
                        "cache_policy": "default",
                    },
                    depends_on=[],
                    branch="main",
                    priority=92,
                )
            ]

        # Multi-hypothesis execution: fires when InputAnalyzer detected two close-confidence
        # intent candidates (gap < 0.20). Cheap path (A) runs in parallel with expensive
        # research path (B); FusionSkill arbitrates the outputs.
        if analysis.get("is_ambiguous"):
            return [
                DAGNode(
                    id="path-a",
                    skill="general_answer",
                    input={
                        "id": "path-a",
                        "description": normalized_prompt,
                        "routed_skill": "general_answer",
                        "route_score": "multi_path_cheap",
                        "cache_policy": "default",
                        "path_role": "cheap",
                    },
                    depends_on=[],
                    branch="A",
                    priority=102,
                ),
                DAGNode(
                    id="path-b",
                    skill="research",
                    input={
                        "id": "path-b",
                        "description": normalized_prompt,
                        "routed_skill": "research",
                        "route_score": "multi_path_research",
                        "cache_policy": "bypass",
                        "path_role": "expensive",
                    },
                    depends_on=[],
                    branch="B",
                    priority=98,
                ),
                DAGNode(
                    id="fusion",
                    skill="fusion",
                    input={
                        "id": "fusion",
                        "description": f"Ambiguity fusion: {normalized_prompt}",
                        "routed_skill": "fusion",
                        "route_score": "multi_path_fusion",
                        "cache_policy": "default",
                    },
                    depends_on=["path-a", "path-b"],
                    branch="main",
                    priority=-1,
                ),
            ]

        # Deterministic weather branch: keep full prompt context (location + time + suitability)
        # in one research step to avoid fragmented subtasks that can lose entity grounding.
        if is_weather_text(normalized_prompt) or analysis.get("decision_reason") == "implicit_weather_suitability":
            return [
                DAGNode(
                    id="task-1",
                    skill="research",
                    input={
                        "id": "task-1",
                        "description": normalized_prompt,
                        "routed_skill": "research",
                        "route_score": "intent_weather_lookup",
                        "cache_policy": "bypass",
                        "selected_tool": "weather",
                        "selected_tool_confidence": "0.95",
                        "selected_tool_reason": "Weather query should preserve full context and use weather provider first",
                    },
                    depends_on=[],
                    branch="main",
                    priority=122,
                ),
                DAGNode(
                    id="synthesis",
                    skill="synthesizer",
                    input={"description": "Synthesize weather findings and suitability recommendation"},
                    depends_on=["task-1"],
                    branch="main",
                    priority=-1,
                ),
            ]

        if analysis.get("intent") in {"market_analysis", "trend_analysis"} or is_market_analysis_text(analysis["normalized_prompt"]) or is_trend_analysis_text(analysis["normalized_prompt"]):
            subject = infer_market_subject(normalized_prompt)
            time_window = str(analysis.get("time_window") or infer_time_window(normalized_prompt))
            return [
                DAGNode(
                    id="task-1",
                    skill="research",
                    input={
                        "id": "task-1",
                        "description": (
                            f"Thu thập chuoi du lieu gia, bien dong gan day va toc do thay doi cua {subject} "
                            f"trong khung thoi gian {time_window}. Prompt goc: {normalized_prompt}"
                        ),
                        "routed_skill": "research",
                        "route_score": "intent_trend_analysis_data",
                        "cache_policy": "bypass",
                        "selected_tool": "",
                        "selected_tool_reason": "Use policy-driven research for trend analysis data",
                    },
                    depends_on=[],
                    branch="A",
                    priority=125,
                ),
                DAGNode(
                    id="task-2",
                    skill="research",
                    input={
                        "id": "task-2",
                        "description": (
                            f"Thu thap boi canh cung-cau, ton kho, thoi tiet, logistics, ty gia va chinh sach "
                            f"dang anh huong toi {subject} trong khung {time_window}. Prompt goc: {normalized_prompt}"
                        ),
                        "routed_skill": "research",
                        "route_score": "intent_trend_analysis_context",
                        "cache_policy": "bypass",
                        "selected_tool": "",
                        "selected_tool_reason": "Use policy-driven research for trend analysis context",
                    },
                    depends_on=[],
                    branch="B",
                    priority=118,
                ),
                DAGNode(
                    id="analysis",
                    skill="analysis",
                    input={
                        "id": "analysis",
                        "description": (
                            f"Phan tich xu huong cua {subject} trong khung {time_window}: "
                            "tong hop tin hieu, danh gia xung dot, neu gia dinh va gioi han evidence. "
                            f"Prompt goc: {normalized_prompt}"
                        ),
                        "routed_skill": "analysis",
                        "route_score": "intent_trend_analysis_reasoning",
                        "cache_policy": "default",
                    },
                    depends_on=["task-1", "task-2"],
                    branch="main",
                    priority=108,
                ),
                DAGNode(
                    id="synthesis",
                    skill="synthesizer",
                    input={"description": "Synthesize trend analysis findings"},
                    depends_on=["task-1", "task-2", "analysis"],
                    branch="main",
                    priority=-1,
                ),
            ]

        if analysis.get("intent") == "market_price" or is_market_data_text(analysis["normalized_prompt"]):
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

        if analysis.get("intent") == "local_discovery" or is_local_discovery_text(analysis["normalized_prompt"]):
            return [
                DAGNode(
                    id="geo-intent",
                    skill="geo_intent",
                    input={
                        "id": "geo-intent",
                        "description": normalized_prompt,
                        "routed_skill": "geo_intent",
                        "route_score": "intent_local_geo_parse",
                        "cache_policy": "default",
                    },
                    depends_on=[],
                    branch="main",
                    priority=120,
                ),
                DAGNode(
                    id="local-search",
                    skill="local_discovery",
                    input={
                        "id": "local-search",
                        "description": normalized_prompt,
                        "routed_skill": "local_discovery",
                        "route_score": "intent_local_discovery",
                        "cache_policy": "bypass",
                        "selected_tool": "local_search",
                        "selected_tool_confidence": "0.92",
                        "selected_tool_reason": "Local discovery intent should use place-aware search",
                    },
                    depends_on=["geo-intent"],
                    branch="A",
                    priority=118,
                ),
                DAGNode(
                    id="place-verify",
                    skill="place_verification",
                    input={
                        "id": "place-verify",
                        "description": "Verify and deduplicate local results",
                        "routed_skill": "place_verification",
                        "route_score": "intent_local_verify",
                        "cache_policy": "default",
                    },
                    depends_on=["geo-intent", "local-search"],
                    branch="main",
                    priority=110,
                ),
                DAGNode(
                    id="review-consensus",
                    skill="review_consensus",
                    input={
                        "id": "review-consensus",
                        "description": "Extract pros/cons consensus from review evidence",
                        "routed_skill": "review_consensus",
                        "route_score": "intent_local_consensus",
                        "cache_policy": "default",
                    },
                    depends_on=["local-search"],
                    branch="B",
                    priority=104,
                ),
                DAGNode(
                    id="candidate-extract",
                    skill="candidate_extraction",
                    input={
                        "id": "candidate-extract",
                        "description": "Extract structured place candidates from local evidence",
                        "routed_skill": "candidate_extraction",
                        "route_score": "intent_local_candidate_extract",
                        "cache_policy": "default",
                    },
                    depends_on=["local-search", "review-consensus"],
                    branch="main",
                    priority=102,
                ),
                DAGNode(
                    id="synthesis",
                    skill="synthesizer",
                    input={"description": "Synthesize structured local place recommendations"},
                    depends_on=["geo-intent", "place-verify", "candidate-extract", "review-consensus"],
                    branch="main",
                    priority=-1,
                ),
            ]

        if analysis.get("intent") == "travel_planning" or is_travel_plan_text(analysis["normalized_prompt"]):
            return [
                DAGNode(
                    id="geo-intent",
                    skill="geo_intent",
                    input={
                        "id": "geo-intent",
                        "description": normalized_prompt,
                        "routed_skill": "geo_intent",
                        "route_score": "intent_travel_geo_parse",
                        "cache_policy": "default",
                    },
                    depends_on=[],
                    branch="main",
                    priority=122,
                ),
                DAGNode(
                    id="local-search",
                    skill="local_discovery",
                    input={
                        "id": "local-search",
                        "description": normalized_prompt,
                        "routed_skill": "local_discovery",
                        "route_score": "intent_travel_local_discovery",
                        "cache_policy": "bypass",
                        "selected_tool": "local_search",
                        "selected_tool_confidence": "0.9",
                        "selected_tool_reason": "Travel planning needs strong local evidence",
                    },
                    depends_on=["geo-intent"],
                    branch="A",
                    priority=118,
                ),
                DAGNode(
                    id="place-verify",
                    skill="place_verification",
                    input={
                        "id": "place-verify",
                        "description": "Verify and score local travel options",
                        "routed_skill": "place_verification",
                        "route_score": "intent_travel_verify",
                        "cache_policy": "default",
                    },
                    depends_on=["local-search"],
                    branch="main",
                    priority=112,
                ),
                DAGNode(
                    id="candidate-extract",
                    skill="candidate_extraction",
                    input={
                        "id": "candidate-extract",
                        "description": "Extract structured travel place candidates from local evidence",
                        "routed_skill": "candidate_extraction",
                        "route_score": "intent_travel_candidate_extract",
                        "cache_policy": "default",
                    },
                    depends_on=["local-search"],
                    branch="main",
                    priority=108,
                ),
                DAGNode(
                    id="itinerary",
                    skill="itinerary_planner",
                    input={
                        "id": "itinerary",
                        "description": normalized_prompt,
                        "routed_skill": "itinerary_planner",
                        "route_score": "intent_travel_itinerary",
                        "cache_policy": "default",
                    },
                    depends_on=["place-verify", "candidate-extract"],
                    branch="main",
                    priority=106,
                ),
                DAGNode(
                    id="synthesis",
                    skill="synthesizer",
                    input={"description": "Synthesize final travel itinerary recommendation"},
                    depends_on=["itinerary", "candidate-extract"],
                    branch="main",
                    priority=-1,
                ),
            ]

        if analysis.get("intent") == "simple_fact" or is_simple_fact_text(analysis["normalized_prompt"]):
            return [
                DAGNode(
                    id="task-1",
                    skill="general_answer",
                    input={
                        "id": "task-1",
                        "description": normalized_prompt,
                        "routed_skill": "general_answer",
                        "route_score": "intent_simple_fact",
                        "cache_policy": "default",
                    },
                    depends_on=[],
                    branch="main",
                    priority=90,
                )
            ]

        if analysis.get("intent") in {"knowledge_lookup", "information_retrieval"} or is_lookup_text(analysis["normalized_prompt"]):
            return [
                DAGNode(
                    id="task-1",
                    skill="research",
                    input={
                        "id": "task-1",
                        "description": normalized_prompt,
                        "routed_skill": "research",
                        "route_score": "intent_knowledge_lookup",
                        "cache_policy": "bypass",
                        "selected_tool": "web_search",
                        "selected_tool_confidence": "0.75",
                        "selected_tool_reason": "Lookup query should gather external evidence",
                    },
                    depends_on=[],
                    branch="main",
                    priority=95,
                ),
                DAGNode(
                    id="synthesis",
                    skill="synthesizer",
                    input={"description": "Synthesize lookup findings"},
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

            # Guardrail: internal pipeline skills require dependency outputs and should not be
            # directly selected for user-facing tasks.
            if routed_skill in {"place_verification", "review_consensus", "candidate_extraction", "itinerary_planner", "geo_intent", "fusion"}:
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

        if self._should_inject_analysis_layer(analysis, nodes):
            upstream_ids = [node.id for node in nodes]
            nodes.append(
                DAGNode(
                    id="analysis",
                    skill="analysis",
                    input={
                        "id": "analysis",
                        "description": (
                            "Phan tich tong hop cac ket qua nghien cuu, xac dinh tin hieu chinh, "
                            "neu gia dinh, rui ro va gioi han du lieu."
                        ),
                        "routed_skill": "analysis",
                        "route_score": "injected_reasoning_layer",
                        "cache_policy": "default",
                    },
                    depends_on=upstream_ids,
                    branch="main",
                    priority=8,
                )
            )

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
    def _should_inject_analysis_layer(analysis: AnalysisResult, nodes: list[DAGNode]) -> bool:
        if any(node.skill == "analysis" for node in nodes):
            return False
        if not any(node.skill == "research" for node in nodes):
            return False

        intent = str(analysis.get("intent", "")).strip().lower()
        prompt = str(analysis.get("normalized_prompt", "")).lower()
        if is_weather_text(prompt):
            return False
        has_analysis_hint = any(token in prompt for token in GENERIC_ANALYSIS_HINTS)
        has_commodity_hint = _contains_hint(prompt, COMMODITY_HINTS)
        has_time_hint = any(token in prompt for token in ("month", "months", "past", "last", "week", "quarter", "year", "six months", "6 months"))

        if intent in {"trend_analysis", "market_analysis"}:
            return True

        if intent in {"knowledge_lookup", "information_retrieval", "research"} and has_analysis_hint:
            return True

        # Noisy/unknown intent from LLM: infer by prompt semantics.
        if has_analysis_hint and has_commodity_hint and has_time_hint:
            return True

        # For multi-branch research, enable reasoning layer even without explicit keyword.
        research_count = sum(1 for node in nodes if node.skill == "research")
        if intent in {"knowledge_lookup", "research"} and research_count >= 2 and analysis.get("execution_mode") == "parallel":
            return True

        return False

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
    def _estimate_priority(description: str, routed: RoutedSkill) -> int:
        lowered = description.lower()
        bonus = 0
        if any(token in lowered for token in ("khẩn", "urgent", "quan trọng", "critical")):
            bonus += 40
        if any(token in lowered for token in ("tóm tắt", "summary", "nhanh")):
            bonus += 10
        return int(routed.final_score * 100) + bonus
