"""Search Decision Gate: LLM-based decision on whether to invoke search/tools."""

from __future__ import annotations

import re
from typing import Any, Callable


class SearchDecisionGate:
    _LLM_TRUST_THRESHOLD = 0.75

    def __init__(
        self,
        llm_json_inferer: Callable[[str], str],
        memory_getter: Callable[[str], str],
    ) -> None:
        self._llm_json_inferer = llm_json_inferer
        self._memory_getter = memory_getter

    def analyze_search_need(self, analysis: dict[str, Any], session_id: str) -> dict[str, Any]:
        try:
            return self._decide_with_llm(analysis, session_id)
        except Exception as error:
            return self._decide_rule_based(analysis, str(error))

    def _decide_with_llm(self, analysis: dict[str, Any], session_id: str) -> dict[str, Any]:
        intent = analysis.get("intent", "research")
        normalized_prompt = analysis.get("normalized_prompt", "")
        intent_tier = analysis.get("intent_tier", "direct")

        tier_to_search_likelihood: dict[str, float] = {
            "trivial": 0.0,
            "direct": 0.2,
            "research": 0.8,
            "analytical": 0.7,
        }
        baseline_need = tier_to_search_likelihood.get(intent_tier, 0.5)

        schema = (
            'Return valid JSON: {"need_search": bool, "reason": "...", "confidence": 0.0}'
            ' need_search: does this query require live/recent/external data?'
            ' confidence: 0.0-1.0, how confident in this decision'
            ' reason: brief explanation (1 line)'
        )

        memory_context = self._memory_getter(session_id)
        response = self._llm_json_inferer(
            f"{schema}\n\nContext: intent={intent} tier={intent_tier} baseline_search_likelihood={baseline_need}\n\n"
            f"Recent memory:\n{memory_context or '- none'}\n\n"
            f"User query: {normalized_prompt}"
        )

        payload = self._extract_json_payload(response)
        need_search = bool(payload.get("need_search", baseline_need > 0.5))
        confidence = float(payload.get("confidence", 0.5))
        reason = str(payload.get("reason", "")).strip() or (
            "Search needed based on query intent" if need_search else "Query answerable from training data"
        )

        return {
            **analysis,
            "need_search": need_search,
            "search_confidence": confidence,
            "search_reason": reason,
        }

    def _decide_rule_based(self, analysis: dict[str, Any], error_context: str = "") -> dict[str, Any]:
        intent = analysis.get("intent", "research")
        intent_tier = analysis.get("intent_tier", "direct")

        tier_rules = {
            "trivial": False,
            "direct": False,
            "research": True,
            "analytical": True,
        }
        need_search = tier_rules.get(intent_tier, True)

        intent_search_rules = {
            "market_price": True,
            "market_analysis": True,
            "trend_analysis": True,
            "simple_fact": False,
            "request": False,
            "question": False,
            "knowledge_lookup": True,
        }
        if intent in intent_search_rules:
            need_search = intent_search_rules[intent]

        return {
            **analysis,
            "need_search": need_search,
            "search_confidence": 0.4,
            "search_reason": f"Rule-based decision (error: {error_context[:50]})" if error_context else "Rule-based fallback",
        }

    @staticmethod
    def _extract_json_payload(raw: str) -> dict[str, Any]:
        candidates = [raw.strip()]
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1).strip())

        import json as json_module

        decoder = json_module.JSONDecoder()
        for candidate in candidates:
            for match in re.finditer(r"\{", candidate):
                try:
                    parsed, end_index = decoder.raw_decode(candidate[match.start() :])
                except json_module.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    trailing = candidate[match.start() + end_index :].strip()
                    if trailing and not trailing.startswith("```"):
                        continue
                    return parsed

        raise ValueError("No valid JSON object found in SearchDecisionGate LLM response.")
