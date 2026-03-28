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


class AnalysisEnvelopeModel(BaseModel):
    normalized_prompt: str = Field(min_length=1, max_length=4000)
    intent: str = Field(min_length=1, max_length=80)
    sentiment: Literal["positive", "neutral", "negative"]
    keywords: list[str] = Field(default_factory=list, max_length=6)
    sub_tasks: list[AnalysisTaskModel] = Field(min_length=1, max_length=4)
    execution_mode: Literal["parallel", "sequential"]

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


class InputAnalyzer:
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

    def __init__(
        self,
        llm_json_inferer: Callable[[str], str],
        memory_getter: Callable[[str], str],
        stopwords: set[str],
    ) -> None:
        self._llm_json_inferer = llm_json_inferer
        self._memory_getter = memory_getter
        self._stopwords = stopwords

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
            '"execution_mode":"parallel|sequential"}'
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
        }
        return self._normalize_market_analysis(analysis)

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
        }
        return self._normalize_market_analysis(analysis)

    @classmethod
    def _is_market_price_prompt(cls, text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in cls._MARKET_HINTS)

    @classmethod
    def _normalize_market_analysis(cls, analysis: AnalysisResult) -> AnalysisResult:
        normalized_prompt = str(analysis.get("normalized_prompt", "")).strip()
        if not normalized_prompt or not cls._is_market_price_prompt(normalized_prompt):
            return analysis

        keywords = list(dict.fromkeys([*analysis.get("keywords", []), "market_price"]))[:6]
        return {
            **analysis,
            "intent": "market_price",
            "keywords": keywords,
            "sub_tasks": [{"id": "task-1", "description": normalized_prompt}],
            "execution_mode": "sequential",
        }

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
