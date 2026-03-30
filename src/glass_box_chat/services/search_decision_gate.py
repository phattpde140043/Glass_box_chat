"""Search Decision Gate: LLM-based decision on whether to invoke search/tools.

Replaces hardcoded heuristics (needs_research_text) with semantic understanding.

Pattern:
  1. InputAnalyzer determines INTENT (what user is asking about/intent tier)
  2. SearchDecisionGate determines SEARCH NEED (does this intent require external tools?)
  3. ExecutionGate determines EXECUTION TIER (how complex the execution is)

This separation allows:
  - LLM to understand nuance (e.g., "capital of france" vs "latest capital markets")
  - Safe fallback when search not needed (cheaper, faster)
  - Gradual upgrade path: rule-based → LLM-based → hybrid
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable


class SearchDecisionGate:
    """LLM-based decision: does this intent require search/tools?
    
    Unlike input_analyzer (which classifies intent), this gate decides:
    "Given this intent + prompt, do we need to fetch live/external data?"
    
    Example distinctions:
      - Intent: "simple_fact" + prompt "Define photosynthesis" → no search (training data)
      - Intent: "simple_fact" + prompt "What's the capital of Vietnam" → search if > tolerance confidence
      - Intent: "market_price" + prompt "Bitcoin price" → always search (realtime)
      - Intent: "trend_analysis" + prompt "Has coffee gone up recently" → search (historical)
    """

    _LLM_TRUST_THRESHOLD = 0.75

    def __init__(
        self,
        llm_json_inferer: Callable[[str], str],
        memory_getter: Callable[[str], str],
    ) -> None:
        self._llm_json_inferer = llm_json_inferer
        self._memory_getter = memory_getter

    def analyze_search_need(self, analysis: dict[str, Any], session_id: str) -> dict[str, Any]:
        """
        Determine if search/tools are needed for this intent + analysis.

        Input: analysis result from InputAnalyzer
        Output: analysis with added "need_search", "search_confidence", "search_reason"

        Returns updated analysis with:
          - need_search (bool): should we invoke search/tools?
          - search_confidence (float): confidence in this decision
          - search_reason (str): why search needed/not needed
        """
        try:
            return self._decide_with_llm(analysis, session_id)
        except Exception as e:
            # Fallback: use conservative rule-based decision
            return self._decide_rule_based(analysis, str(e))

    def _decide_with_llm(self, analysis: dict[str, Any], session_id: str) -> dict[str, Any]:
        """Query LLM to decide if search needed."""
        intent = analysis.get("intent", "research")
        normalized_prompt = analysis.get("normalized_prompt", "")
        intent_tier = analysis.get("intent_tier", "direct")

        # High-level tier decisions
        tier_to_search_likelihood: dict[str, float] = {
            "trivial": 0.0,  # Greetings never need search
            "direct": 0.2,   # Direct answers mostly from training data
            "research": 0.8,  # Research tier usually needs search
            "analytical": 0.7,  # Analytics might need live data
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
        reason = str(payload.get("reason", "")).strip() or ("Search needed based on query intent" if need_search else "Query answerable from training data")

        return {
            **analysis,
            "need_search": need_search,
            "search_confidence": confidence,
            "search_reason": reason,
        }

    def _decide_rule_based(self, analysis: dict[str, Any], error_context: str = "") -> dict[str, Any]:
        """Conservative rule-based fallback when LLM unavailable."""
        intent = analysis.get("intent", "research")
        intent_tier = analysis.get("intent_tier", "direct")

        # Tier-based rules
        tier_rules = {
            "trivial": False,  # Never search for greetings
            "direct": False,   # Direct answers from training
            "research": True,   # Research tier usually needs search
            "analytical": True,  # Analytics tier needs data
        }

        need_search = tier_rules.get(intent_tier, True)

        # Intent-based overrides
        intent_search_rules = {
            "market_price": True,       # Always search for realtime prices
            "market_analysis": True,    # Always search for analysis
            "trend_analysis": True,     # Always search for trends
            "local_discovery": True,    # Local place selection requires external/live sources
            "travel_planning": True,    # Travel plans require external context
            "simple_fact": False,       # Facts from training
            "request": False,           # Generic requests no search
            "question": False,          # General questions no search
            "knowledge_lookup": True,   # Lookup usually needs search
        }

        if intent in intent_search_rules:
            need_search = intent_search_rules[intent]

        return {
            **analysis,
            "need_search": need_search,
            "search_confidence": 0.4,  # Low confidence fallback
            "search_reason": f"Rule-based decision (error: {error_context[:50]})" if error_context else "Rule-based fallback",
        }

    @staticmethod
    def _extract_json_payload(raw: str) -> dict[str, Any]:
        """Extract JSON from LLM response."""
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
