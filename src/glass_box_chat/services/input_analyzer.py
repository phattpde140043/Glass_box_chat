from __future__ import annotations

import json
import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, field_validator

from .planner import AnalysisResult, needs_research_text


class AnalysisTaskModel(BaseModel):
    description: str = Field(min_length=1, max_length=600)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        trimmed = re.sub(r"\s+", " ", value).strip()
        if not trimmed:
            raise ValueError("description cannot be empty")
        return trimmed


class IntentCandidateModel(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tier: Literal["trivial", "direct", "research", "analytical"] = Field(default="direct")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return re.sub(r"\s+", "_", value.strip().lower())


class AnalysisEnvelopeModel(BaseModel):
    normalized_prompt: str = Field(min_length=1, max_length=4000)
    intent: str = Field(min_length=1, max_length=80)
    sentiment: Literal["positive", "neutral", "negative"]
    keywords: list[str] = Field(default_factory=list, max_length=6)
    sub_tasks: list[AnalysisTaskModel] = Field(min_length=1, max_length=4)
    execution_mode: Literal["parallel", "sequential"]
    time_window: str = Field(default="unspecified", min_length=1, max_length=40)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    intent_tier: Literal["trivial", "direct", "research", "analytical"] = Field(default="direct")
    intents: list[IntentCandidateModel] = Field(default_factory=list, max_length=3)

    @field_validator("normalized_prompt", "intent")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        trimmed = re.sub(r"\s+", " ", value).strip()
        if not trimmed:
            raise ValueError("field cannot be empty")
        return trimmed

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            cleaned = re.sub(r"\s+", " ", str(item)).strip().lower()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
            if len(normalized) >= 6:
                break
        return normalized


class AmbiguityDetector:
    """Detects when LLM intent classification carries two close-confidence hypotheses.

    Triggers multi-hypothesis execution in the planner (cheap + expensive paths run in
    parallel, then merged by FusionSkill). Only fires when:
      - Top-2 candidate confidence gap < _GAP_THRESHOLD
      - Top-1 confidence >= _MIN_TRIGGER_CONFIDENCE
      - Hard domain signals (market_price, weather) are absent (handled upstream)
    """

    _GAP_THRESHOLD: float = 0.20
    _MIN_TRIGGER_CONFIDENCE: float = 0.30

    @classmethod
    def is_ambiguous(cls, candidates: list[dict]) -> bool:
        """Return True when the top-2 intent candidates are too close to discriminate."""
        if len(candidates) < 2:
            return False
        top1 = float(candidates[0].get("confidence", 0.0))
        top2 = float(candidates[1].get("confidence", 0.0))
        return top1 >= cls._MIN_TRIGGER_CONFIDENCE and (top1 - top2) < cls._GAP_THRESHOLD


class InputAnalyzer:
    _LLM_INTENT_TRUST_THRESHOLD = 0.7

    _INTENT_TIER_MAP: dict[str, str] = {
        "market_price": "research",
        "market_analysis": "analytical",
        "trend_analysis": "analytical",
        "knowledge_lookup": "research",
        "information_retrieval": "research",
        "research": "research",
        "simple_fact": "direct",
        "question": "direct",
        "request": "direct",
    }

    _KNOWN_INTENTS = {
        "request",
        "question",
        "research",
        "knowledge_lookup",
        "information_retrieval",
        "market_price",
        "market_analysis",
        "trend_analysis",
        "simple_fact",
    }

    _MARKET_HINTS = (
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

    _MARKET_ANALYSIS_HINTS = (
        "nhận định",
        "nhan dinh",
        "phân tích",
        "phan tich",
        "tình hình",
        "tinh hinh",
        "xu hướng",
        "xu huong",
        "outlook",
        "trend",
        "assessment",
        "analyze",
        "analysis",
        "đánh giá",
        "danh gia",
    )

    _COMMODITY_HINTS = (
        "cà phê",
        "ca phe",
        "cafe",
        "coffee",
        "arabica",
        "robusta",
        "commodity",
        "nông sản",
        "nong san",
        "hồ tiêu",
        "ho tieu",
        "pepper price",
    )

    _TREND_TIME_HINTS = (
        "hôm nay",
        "hom nay",
        "today",
        "tuần",
        "tuan",
        "week",
        "tháng",
        "thang",
        "month",
        "months",
        "past",
        "last",
        "6 months",
        "six months",
        "quý",
        "quy",
        "quarter",
        "năm",
        "nam",
        "year",
        "gần đây",
        "gan day",
        "recent",
    )

    _LOOKUP_HINTS = (
        "thông tin",
        "thong tin",
        "tìm kiếm",
        "tim kiem",
        "tra cứu",
        "tra cuu",
        "information search",
        "lookup",
        "find information",
        "who is",
        "what is",
        "là gì",
        "la gi",
    )

    _SIMPLE_FACT_HINTS = (
        "what is",
        "who is",
        "population",
        "capital",
        "definition",
        "meaning",
        "là gì",
        "la gi",
        "dân số",
        "dan so",
        "thủ đô",
        "thu do",
    )

    _SIMPLE_FACT_ENTITIES = (
        "unesco",
        "vietnam",
        "việt nam",
        "hanoi",
        "ha noi",
    )

    def __init__(
        self,
        llm_json_inferer: Callable[[str], str],
        memory_getter: Callable[[str], str],
        stopwords: set[str],
    ) -> None:
        self._llm_json_inferer = llm_json_inferer
        self._memory_getter = memory_getter
        self._stopwords = stopwords

    @staticmethod
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

    def analyze(self, prompt: str, session_id: str) -> AnalysisResult:
        try:
            return self.analyze_with_llm(prompt, session_id)
        except Exception:
            return self.analyze_rule_based(prompt)

    def analyze_with_llm(self, prompt: str, session_id: str) -> AnalysisResult:
        schema = (
            'Return valid JSON only with this shape: '
            '{"normalized_prompt":"...","intent":"...","sentiment":"positive|neutral|negative",'
            '"keywords":["..."],"sub_tasks":[{"description":"..."}],'
            '"execution_mode":"parallel|sequential","time_window":"intraday|1w|1m|1q|1y|recent|unspecified",'
            '"confidence":0.0,"intent_tier":"trivial|direct|research|analytical",'
            '"intents":[{"name":"...","confidence":0.0,"tier":"direct"}]}'
            ' intent_tier: trivial=greeting/chitchat no tools needed,'
            ' direct=LLM answers from training data,'
            ' research=requires live data or external tool calls,'
            ' analytical=multi-step analysis with synthesis.'
            ' intents: top-K intent candidates sorted by confidence desc (max 3);'
            ' intent field must match intents[0].name.'
        )
        memory_context = self._memory_getter(session_id)
        response = self._llm_json_inferer(
            f"{schema}\n\nRecent short-term memory:\n{memory_context or '- none'}\n\nUser input: {prompt}"
        )
        payload = self._extract_json_payload(response)
        validated = AnalysisEnvelopeModel.model_validate(payload)
        analysis: AnalysisResult = {
            "original_prompt": prompt,
            "normalized_prompt": validated.normalized_prompt,
            "intent": validated.intent,
            "sentiment": validated.sentiment,
            "keywords": validated.keywords,
            "sub_tasks": [
                {"id": f"task-{index + 1}", "description": item.description}
                for index, item in enumerate(validated.sub_tasks)
            ],
            "execution_mode": validated.execution_mode,
            "time_window": self._infer_time_window(validated.time_window if validated.time_window != "unspecified" else validated.normalized_prompt),
            "confidence": float(validated.confidence),
            "intent_tier": validated.intent_tier,
            "intent_candidates": [c.model_dump() for c in validated.intents],
        }
        return self._resolve_intent(analysis)

    def analyze_rule_based(self, prompt: str) -> AnalysisResult:
        normalized = re.sub(r"\s+", " ", prompt).strip()
        lowered = normalized.lower()

        intent = "question" if "?" in normalized or lowered.startswith(("what", "why", "how", "tại sao", "làm sao")) else "request"
        if needs_research_text(normalized):
            intent = "research"

        sentiment = "neutral"
        if any(word in lowered for word in ("tệ", "bad", "lỗi", "khó chịu", "frustrated")):
            sentiment = "negative"
        elif any(word in lowered for word in ("tốt", "great", "hay", "good", "nice")):
            sentiment = "positive"

        tokens = [token for token in re.split(r"[^\wÀ-ỹ]+", lowered) if len(token) >= 3 and token not in self._stopwords]
        keywords = list(dict.fromkeys(tokens))[:6]

        clauses = [segment.strip() for segment in re.split(r"\.|,|;|\band\b|\bvà\b", normalized, flags=re.IGNORECASE) if segment.strip()]
        raw_sub_tasks = clauses[:4] if clauses else [normalized]
        sub_tasks = [{"id": f"task-{index + 1}", "description": description} for index, description in enumerate(raw_sub_tasks)]
        execution_mode = "parallel" if len(sub_tasks) > 1 else "sequential"

        analysis: AnalysisResult = {
            "original_prompt": prompt,
            "normalized_prompt": normalized,
            "intent": intent,
            "sentiment": sentiment,
            "keywords": keywords,
            "sub_tasks": sub_tasks,
            "execution_mode": execution_mode,
            "time_window": self._infer_time_window(normalized),
            "confidence": 0.35,
        }
        return self._resolve_intent(analysis)

    @classmethod
    def _canonicalize_intent(cls, value: str) -> str:
        return str(value).strip().lower().replace("-", "_").replace(" ", "_")

    @classmethod
    def _resolve_intent(cls, analysis: AnalysisResult) -> AnalysisResult:
        normalized_prompt = str(analysis.get("normalized_prompt", "")).strip()
        if not normalized_prompt:
            return analysis

        llm_confidence = float(analysis.get("confidence", 0.0) or 0.0)
        llm_intent = cls._canonicalize_intent(str(analysis.get("intent", "")))
        intent_tier = str(analysis.get("intent_tier") or "").strip().lower()

        def _ensure_tier(result: AnalysisResult, fallback_tier: str) -> AnalysisResult:
            final_intent = str(result.get("intent", "request"))
            inferred_tier = cls._INTENT_TIER_MAP.get(final_intent, fallback_tier)
            return {**result, "intent_tier": inferred_tier}

        if intent_tier == "trivial":
            return {**analysis, "intent": "request", "need_pipeline": False, "intent_tier": "trivial"}

        if cls._is_market_price_prompt(normalized_prompt):
            if llm_intent != "market_price":
                return _ensure_tier(
                    {**analysis, "intent": "market_price", "keywords": list(dict.fromkeys([*analysis.get("keywords", []), "market_price"]))[:6]},
                    "research",
                )
            return _ensure_tier({**analysis}, "research")

        intent_candidates = [c for c in (analysis.get("intent_candidates") or []) if isinstance(c, dict)]
        if AmbiguityDetector.is_ambiguous(intent_candidates) and llm_confidence < cls._LLM_INTENT_TRUST_THRESHOLD:
            primary = cls._canonicalize_intent(intent_candidates[0].get("name", llm_intent))
            if primary not in cls._KNOWN_INTENTS:
                primary = "research"
            return _ensure_tier(
                {**analysis, "intent": primary, "is_ambiguous": True, "intent_candidates": intent_candidates},
                "research",
            )

        if llm_confidence >= cls._LLM_INTENT_TRUST_THRESHOLD:
            if llm_intent in cls._KNOWN_INTENTS:
                return _ensure_tier({**analysis, "intent": llm_intent}, intent_tier or "direct")
            return _ensure_tier({**analysis, "intent": "research"}, "research")

        return _ensure_tier({**analysis, "intent": "research"}, "research")

    @classmethod
    def _is_market_price_prompt(cls, text: str) -> bool:
        return cls._contains_hint(text, cls._MARKET_HINTS)

    @classmethod
    def _infer_time_window(cls, text: str) -> str:
        lowered = text.lower()
        if any(token in lowered for token in ("6 months", "six months", "past six months", "last six months")):
            return "6m"
        if any(token in lowered for token in ("hôm nay", "hom nay", "today", "intraday")):
            return "intraday"
        if any(token in lowered for token in ("tuần", "tuan", "week", "weekly")):
            return "1w"
        if any(token in lowered for token in ("tháng", "thang", "month", "monthly")):
            return "1m"
        if any(token in lowered for token in ("months", "past", "last")):
            return "recent"
        if any(token in lowered for token in ("quý", "quy", "quarter")):
            return "1q"
        if any(token in lowered for token in ("năm", "nam", "year", "yearly")):
            return "1y"
        if any(token in lowered for token in ("gần đây", "gan day", "recent", "latest")):
            return "recent"
        return "unspecified"

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

        raise ValueError("No valid JSON object found in analyzer LLM response.")
