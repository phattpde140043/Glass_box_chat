from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from .planner import AnalysisResult, is_lookup_text, is_market_analysis_text, is_market_data_text, is_weather_text


class ExecutionDecisionModel(BaseModel):
    tier: Literal["trivial", "lookup", "market_realtime", "analysis", "complex_task"]
    need_pipeline: bool
    need_tools: bool
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=240)


class ExecutionGate:
    _TRUST_THRESHOLD = 0.7

    _TRIVIAL_HINTS = (
        "xin chao",
        "xin chào",
        "chao",
        "chào",
        "hello",
        "hi",
        "hey",
        "yo",
        "good morning",
        "good afternoon",
        "good evening",
    )

    _ANALYSIS_HINTS = (
        "phan tich",
        "phân tích",
        "nhan dinh",
        "nhận định",
        "xu huong",
        "xu hướng",
        "analysis",
        "analyze",
        "trend",
        "outlook",
    )

    _OUTDOOR_ACTIVITY_HINTS = (
        "picnic",
        "dã ngoại",
        "da ngoai",
        "camping",
        "cắm trại",
        "cam trai",
        "walk",
        "hiking",
        "ngoài trời",
        "ngoai troi",
        "outdoor",
    )

    _TIME_PLAN_HINTS = (
        "ngày mai",
        "ngay mai",
        "tomorrow",
        "cuối tuần",
        "cuoi tuan",
        "this weekend",
        "weekend",
        "mai",
    )

    def __init__(self, llm_json_inferer: Callable[[str], str]) -> None:
        self._llm_json_inferer = llm_json_inferer

    @staticmethod
    def _fold_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return without_marks.replace("đ", "d").replace("Đ", "D").lower()

    @staticmethod
    def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
        lowered = ExecutionGate._fold_text(text)
        tokens = {token for token in re.split(r"[^\wÀ-ỹ]+", lowered) if token}
        for hint in hints:
            normalized_hint = ExecutionGate._fold_text(hint)
            if " " in normalized_hint:
                if normalized_hint in lowered:
                    return True
                continue
            if normalized_hint in tokens:
                return True
        return False

    def decide(self, analysis: AnalysisResult) -> AnalysisResult:
        rule_decision = self._decide_rule_based(analysis)

        try:
            llm_decision = self._decide_with_llm(analysis)
        except Exception:
            llm_decision = None

        decision = rule_decision
        if llm_decision is not None and llm_decision.confidence >= self._TRUST_THRESHOLD:
            decision = llm_decision

        return {
            **analysis,
            "intent": self._override_intent(analysis, decision),
            "intent_tier": decision.tier,
            "need_pipeline": decision.need_pipeline,
            "need_tools": decision.need_tools,
            "decision_confidence": float(decision.confidence),
            "decision_reason": decision.reason,
        }

    @staticmethod
    def _override_intent(analysis: AnalysisResult, decision: ExecutionDecisionModel) -> str:
        original_intent = str(analysis.get("intent", "request")).strip().lower() or "request"
        if decision.reason in {"implicit_weather_suitability", "lookup_or_research_detected", "market_realtime_detected"}:
            return "research"
        if decision.tier == "analysis":
            return "trend_analysis" if original_intent == "request" else original_intent
        return original_intent

    def _decide_rule_based(self, analysis: AnalysisResult) -> ExecutionDecisionModel:
        prompt = str(analysis.get("normalized_prompt", "")).strip()
        lowered = prompt.lower()
        intent = str(analysis.get("intent", "")).strip().lower()
        sub_tasks = analysis.get("sub_tasks", [])

        if self._is_implicit_weather_suitability_prompt(prompt):
            return ExecutionDecisionModel(
                tier="lookup",
                need_pipeline=True,
                need_tools=True,
                confidence=0.88,
                reason="implicit_weather_suitability",
            )

        if self._is_trivial_prompt(prompt):
            return ExecutionDecisionModel(
                tier="trivial",
                need_pipeline=False,
                need_tools=False,
                confidence=0.95,
                reason="trivial_small_talk",
            )

        if intent in {"market_price"} or is_market_data_text(lowered):
            return ExecutionDecisionModel(
                tier="market_realtime",
                need_pipeline=True,
                need_tools=True,
                confidence=0.9,
                reason="market_realtime_detected",
            )

        if intent in {"knowledge_lookup", "information_retrieval", "research"} or is_lookup_text(lowered) or is_weather_text(lowered):
            return ExecutionDecisionModel(
                tier="lookup",
                need_pipeline=True,
                need_tools=True,
                confidence=0.85,
                reason="lookup_or_research_detected",
            )

        if intent in {"market_analysis", "trend_analysis"} or is_market_analysis_text(lowered) or self._contains_hint(lowered, self._ANALYSIS_HINTS):
            return ExecutionDecisionModel(
                tier="analysis",
                need_pipeline=True,
                need_tools=True,
                confidence=0.84,
                reason="analysis_detected",
            )

        if len(sub_tasks) >= 2:
            return ExecutionDecisionModel(
                tier="complex_task",
                need_pipeline=True,
                need_tools=False,
                confidence=0.7,
                reason="multiple_subtasks",
            )

        return ExecutionDecisionModel(
            tier="lookup" if intent == "simple_fact" else "trivial",
            need_pipeline=False,
            need_tools=False,
            confidence=0.68,
            reason="default_direct_answer",
        )

    def _decide_with_llm(self, analysis: AnalysisResult) -> ExecutionDecisionModel:
        prompt = str(analysis.get("normalized_prompt", "")).strip()
        intent = str(analysis.get("intent", "")).strip()
        schema = (
            "Return strict JSON only with shape: "
            '{"tier":"trivial|lookup|market_realtime|analysis|complex_task",'
            '"need_pipeline":true,"need_tools":false,"confidence":0.0,"reason":"..."}'
        )
        llm_prompt = (
            f"{schema}\n\n"
            "Task: Decide if this user input needs a complex execution pipeline/tool search, or direct answer.\n"
            "Guidelines:\n"
            "- greeting/small-talk/social pleasantries => trivial, no pipeline, no tools\n"
            "- simple factual question answerable from model memory => trivial or lookup, no pipeline\n"
            "- explicit realtime data/weather/market/news lookup => need tools + pipeline\n"
            "- outdoor plans (picnic/camping/outdoor activity) with time/location often imply weather lookup even if weather is not mentioned explicitly\n"
            "- analysis/trend request with evidence needs => analysis + tools + pipeline\n\n"
            f"Current intent: {intent}\n"
            f"User prompt: {prompt}"
        )
        raw = self._llm_json_inferer(llm_prompt)
        payload = self._extract_json_payload(raw)
        return ExecutionDecisionModel.model_validate(payload)

    def _is_trivial_prompt(self, prompt: str) -> bool:
        lowered = re.sub(r"\s+", " ", prompt.lower()).strip()
        if not lowered:
            return True
        if self._is_implicit_weather_suitability_prompt(prompt):
            return False
        if is_market_data_text(lowered) or is_market_analysis_text(lowered):
            return False
        if is_lookup_text(lowered) or is_weather_text(lowered):
            return False
        if self._contains_hint(lowered, self._ANALYSIS_HINTS):
            return False

        words = [token for token in re.split(r"[^\wÀ-ỹ]+", lowered) if token]
        if len(words) <= 3 and self._contains_hint(lowered, self._TRIVIAL_HINTS):
            return True
        return False

    def _is_implicit_weather_suitability_prompt(self, prompt: str) -> bool:
        lowered = re.sub(r"\s+", " ", self._fold_text(prompt)).strip()
        if not lowered:
            return False

        has_outdoor_activity = self._contains_hint(lowered, self._OUTDOOR_ACTIVITY_HINTS)
        has_time_hint = self._contains_hint(lowered, self._TIME_PLAN_HINTS)
        has_location_signal = self._has_location_signal(prompt)
        return has_outdoor_activity and has_time_hint and has_location_signal

    @staticmethod
    def _has_location_signal(prompt: str) -> bool:
        lowered = ExecutionGate._fold_text(prompt)
        if re.search(r"\b(?:tai|o|in|at)\b", lowered):
            return True
        title_case_location = re.search(r"\b(?:in|at|tại|ở)\s+[A-ZÀ-Ỹ][\wÀ-ỹ-]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ-]*)*", prompt)
        if title_case_location is not None:
            return True
        trailing_location = re.search(r"[A-ZÀ-Ỹ][\wÀ-ỹ-]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ-]*)*$", prompt.strip())
        if trailing_location is not None and len(trailing_location.group(0).split()) <= 4:
            return True
        return title_case_location is not None

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

        raise ValueError("No valid JSON object found in execution gate response.")
