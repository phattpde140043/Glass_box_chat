from __future__ import annotations

import json
import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, field_validator

from .language_policy import DEFAULT_RESPONSE_LANGUAGE, normalize_language_name
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
    detected_input_language: str = Field(default=DEFAULT_RESPONSE_LANGUAGE, min_length=1, max_length=80)
    response_language: str = Field(default=DEFAULT_RESPONSE_LANGUAGE, min_length=1, max_length=80)
    explicit_response_language: bool = False
    language_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

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

    # Maps resolved intent to pipeline tier for rule-inferred paths.
    _INTENT_TIER_MAP: dict[str, str] = {
        "market_price": "research",
        "market_analysis": "analytical",
        "trend_analysis": "analytical",
        "knowledge_lookup": "research",
        "information_retrieval": "research",
        "local_discovery": "research",
        "travel_planning": "analytical",
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
        "local_discovery",
        "travel_planning",
        "simple_fact",
    }

    _MARKET_HINTS = (
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

    _MARKET_ANALYSIS_HINTS = (
        "outlook",
        "trend",
        "assessment",
        "analyze",
        "analysis",
    )

    _COMMODITY_HINTS = (
        "cafe",
        "coffee",
        "arabica",
        "robusta",
        "commodity",
        "pepper price",
    )

    _TREND_TIME_HINTS = (
        "today",
        "week",
        "month",
        "months",
        "past",
        "last",
        "6 months",
        "six months",
        "quarter",
        "year",
        "recent",
    )

    _LOOKUP_HINTS = (
        "information search",
        "lookup",
        "find information",
        "who is",
        "what is",
    )

    _LOCAL_DISCOVERY_HINTS = (
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
        "beach",
    )

    _TRAVEL_PLAN_HINTS = (
        "travel plan",
        "itinerary",
        "2 day",
        "3 day",
        "trip plan",
    )

    _SIMPLE_FACT_HINTS = (
        "what is",
        "who is",
        "population",
        "capital",
        "definition",
        "meaning",
    )

    _SIMPLE_FACT_ENTITIES = (
        "unesco",
        "vietnam",
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
        tokens = {token for token in re.split(r"[^\w]+", lowered) if token}
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
            '"intents":[{"name":"...","confidence":0.0,"tier":"direct"}],'
            '"detected_input_language":"english","response_language":"english",'
            '"explicit_response_language":false,"language_confidence":0.0}'
            ' intent_tier: trivial=greeting/chitchat no tools needed,'
            ' direct=LLM answers from training data,'
            ' research=requires live data or external tool calls,'
            ' analytical=multi-step analysis with synthesis.'
            ' intents: top-K intent candidates sorted by confidence desc (max 3);'
            ' intent field must match intents[0].name.'
            ' detected_input_language: language of the user message.'
            ' normalized_prompt: MUST be rewritten into clear English while preserving meaning, entities, time windows, and constraints from the user message.'
            ' response_language: MUST always be english.'
            ' explicit_response_language: MUST always be false because this runtime is English-only.'
            ' If the source message is unclear, still produce the best English normalization and set response_language to english.'
            ' Prefer intent labels from this set when applicable: '
            'request|question|research|knowledge_lookup|information_retrieval|market_price|market_analysis|trend_analysis|simple_fact|local_discovery|travel_planning.'
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
            "detected_input_language": normalize_language_name(validated.detected_input_language),
            "response_language": DEFAULT_RESPONSE_LANGUAGE,
            "explicit_response_language": False,
            "language_confidence": float(validated.language_confidence),
        }
        return self._resolve_intent(analysis)

    def analyze_rule_based(self, prompt: str) -> AnalysisResult:
        normalized = re.sub(r"\s+", " ", prompt).strip()
        lowered = normalized.lower()

        intent = "question" if "?" in normalized or lowered.startswith(("what", "why", "how")) else "request"
        if needs_research_text(normalized):
            intent = "research"

        sentiment = "neutral"
        if any(word in lowered for word in ("bad", "error", "frustrated", "annoyed")):
            sentiment = "negative"
        elif any(word in lowered for word in ("great", "good", "nice", "helpful")):
            sentiment = "positive"

        tokens = [token for token in re.split(r"[^\w]+", lowered) if len(token) >= 3 and token not in self._stopwords]
        keywords = list(dict.fromkeys(tokens))[:6]

        clauses = [segment.strip() for segment in re.split(r"\.|,|;|\band\b", normalized, flags=re.IGNORECASE) if segment.strip()]
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
            "detected_input_language": DEFAULT_RESPONSE_LANGUAGE,
            "response_language": DEFAULT_RESPONSE_LANGUAGE,
            "explicit_response_language": False,
            "language_confidence": 0.0,
        }
        return self._resolve_intent(analysis)

    @classmethod
    def _canonicalize_intent(cls, value: str) -> str:
        return str(value).strip().lower().replace("-", "_").replace(" ", "_")

    # --- DEPRECATED: _apply_special_intent() no longer used ---
    # LLM-first pattern: rules validate, not classify. No need for special intent injection.

    @classmethod
    def _resolve_intent(cls, analysis: AnalysisResult) -> AnalysisResult:
        """
        LLM-first validator pattern.
        
        Rules NEVER override LLM intent. Instead:
        1. Hard guardrails (market_price) VALIDATE unambiguous signals only
        2. High-confidence LLM (>=0.7) is TRUSTED as-is
        3. Ambiguity detection preserves multi-hypothesis for planner
        4. Low-confidence LLM falls back to research tier (safe default)
        
        Note: SearchDecisionGate (in orchestrator) will later decide if search/tools needed.
        """
        normalized_prompt = str(analysis.get("normalized_prompt", "")).strip()
        if not normalized_prompt:
            return analysis

        llm_confidence = float(analysis.get("confidence", 0.0) or 0.0)
        llm_intent = cls._canonicalize_intent(str(analysis.get("intent", "")))
        intent_tier = str(analysis.get("intent_tier") or "").strip().lower()

        def _ensure_tier(result: AnalysisResult, fallback_tier: str) -> AnalysisResult:
            """Propagate or infer intent_tier.
            
            If intent was changed from original LLM response, tier must be recalculated.
            """
            # Always infer tier from current intent to handle intent changes properly
            final_intent = str(result.get("intent", "request"))
            inferred_tier = cls._INTENT_TIER_MAP.get(final_intent, fallback_tier)
            return {**result, "intent_tier": inferred_tier}

        # Stage 1: TRIVIAL TIER FAST-PATH
        # Greetings/chitchat → skip pipeline entirely
        if intent_tier == "trivial":
            return {**analysis, "intent": "request", "need_pipeline": False, "intent_tier": "trivial"}

        # Stage 2: HARD GUARDRAIL
        # Market-price signals (XAU/USD, BTC, giá vàng) — always deterministic
        # This validates the signal, never overrides LLM
        if cls._is_market_price_prompt(normalized_prompt):
            if llm_intent != "market_price":
                # Hard signal detected but LLM missed → force correct intent
                return _ensure_tier(
                    {**analysis, "intent": "market_price", "keywords": list(dict.fromkeys([*analysis.get("keywords", []), "market_price"]))[:6]},
                    "research",
                )
            return _ensure_tier({**analysis}, "research")

        if cls._is_local_discovery_prompt(normalized_prompt):
            if llm_intent != "local_discovery":
                return _ensure_tier(
                    {
                        **analysis,
                        "intent": "local_discovery",
                        "keywords": list(dict.fromkeys([*analysis.get("keywords", []), "local_discovery"]))[:6],
                    },
                    "research",
                )
            return _ensure_tier({**analysis}, "research")

        if cls._is_travel_planning_prompt(normalized_prompt):
            if llm_intent != "travel_planning":
                return _ensure_tier(
                    {
                        **analysis,
                        "intent": "travel_planning",
                        "keywords": list(dict.fromkeys([*analysis.get("keywords", []), "travel_planning"]))[:6],
                    },
                    "analytical",
                )
            return _ensure_tier({**analysis}, "analytical")

        # Stage 3: AMBIGUITY DETECTION
        # Preserve multi-hypothesis when top-2 candidates too close
        # Let planner (with FusionSkill) handle multiple paths
        intent_candidates = [c for c in (analysis.get("intent_candidates") or []) if isinstance(c, dict)]
        if AmbiguityDetector.is_ambiguous(intent_candidates) and llm_confidence < cls._LLM_INTENT_TRUST_THRESHOLD:
            primary = cls._canonicalize_intent(intent_candidates[0].get("name", llm_intent))
            if primary not in cls._KNOWN_INTENTS:
                primary = "research"
            return _ensure_tier(
                {**analysis, "intent": primary, "is_ambiguous": True, "intent_candidates": intent_candidates},
                "research",
            )

        # Stage 4: LLM TRUST THRESHOLD
        # High confidence LLM classification → use as-is
        if llm_confidence >= cls._LLM_INTENT_TRUST_THRESHOLD:
            if llm_intent in cls._KNOWN_INTENTS:
                return _ensure_tier({**analysis, "intent": llm_intent}, intent_tier or "direct")
            # Unknown intent → research (conservative)
            return _ensure_tier({**analysis, "intent": "research"}, "research")

        # Stage 5: LOW CONFIDENCE FALLBACK
        # LLM uncertain → safe research tier
        # SearchDecisionGate will later decide if actual search/tools needed
        return _ensure_tier({**analysis, "intent": "research"}, "research")

    @classmethod
    def _is_market_price_prompt(cls, text: str) -> bool:
        """Hard guardrail: detect market price signals (XAU/USD, BTC, giá vàng, forex)."""
        return cls._contains_hint(text, cls._MARKET_HINTS)

    @classmethod
    def _is_local_discovery_prompt(cls, text: str) -> bool:
        return cls._contains_hint(text, cls._LOCAL_DISCOVERY_HINTS)

    @classmethod
    def _is_travel_planning_prompt(cls, text: str) -> bool:
        return cls._contains_hint(text, cls._TRAVEL_PLAN_HINTS)

    @classmethod
    def _infer_time_window(cls, text: str) -> str:
        """Infer time window from text for financial analysis queries."""
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
