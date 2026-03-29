"""
Meta-Reasoning Agent: Global execution strategy decision maker.

Role: Decides global execution strategy (direct | research_first | hybrid_parallel)
       based on intent analysis, NOT hardcoded rules.

Placement: AFTER InputAnalyzer, BEFORE Planner
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel


class ExecutionStrategy(str, Enum):
    DIRECT = "direct"
    RESEARCH_FIRST = "research_first"
    HYBRID_PARALLEL = "hybrid_parallel"


class RiskProfile(BaseModel):
    hallucination_risk: float
    missing_data_risk: float
    weak_reasoning_risk: float


class MetaReasoningResult(BaseModel):
    strategy: ExecutionStrategy
    confidence: float
    reason: str
    risk: RiskProfile
    suggested_tools: list[str]
    parallel_candidates: Optional[list[str]] = None


@dataclass
class MetaReasoningAgent:
    _call_model: Callable

    async def analyze_strategy(
        self,
        analysis: dict,
        session_memory: Optional[dict] = None,
        session_id: Optional[str] = None,
    ) -> MetaReasoningResult:
        prompt = self._build_strategy_prompt(analysis, session_memory)
        schema = self._build_response_schema()

        try:
            result = await self._call_model(
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                schema=schema,
            )

            return MetaReasoningResult(
                strategy=ExecutionStrategy(result.get("strategy", "hybrid_parallel")),
                confidence=float(result.get("confidence", 0.5)),
                reason=result.get("reason", ""),
                risk=RiskProfile(
                    hallucination_risk=float(result.get("risk", {}).get("hallucination", 0.5)),
                    missing_data_risk=float(result.get("risk", {}).get("missing_data", 0.5)),
                    weak_reasoning_risk=float(result.get("risk", {}).get("weak_reasoning", 0.3)),
                ),
                suggested_tools=result.get("suggested_tools", []),
                parallel_candidates=result.get("parallel_candidates", None),
            )
        except Exception:
            return self._fallback_strategy(analysis)

    def _system_prompt(self) -> str:
        return """You are a Meta-Reasoning Agent responsible for deciding the GLOBAL execution strategy.

Your job is to analyze the user's intent and determine:
1. Can we answer this with reasoning alone? (DIRECT)
2. Do we need to fetch external data first? (RESEARCH_FIRST)
3. Should we run both reasoning & research in parallel? (HYBRID_PARALLEL)

Consider:
- Intent complexity
- Timeliness requirements (market prices, news -> need research)
- Risk of hallucination (factual claims -> higher risk)
- Risk of missing context (may need research)
- Preparation for follow-up questions

Return JSON with:
- strategy: direct | research_first | hybrid_parallel
- confidence: 0.0-1.0
- reason: brief explanation
- risk: {hallucination, missing_data, weak_reasoning} scores
- suggested_tools: list of tools that might help
- parallel_candidates: if hybrid_parallel, which skills to run in parallel"""

    def _build_strategy_prompt(self, analysis: dict, session_memory: Optional[dict]) -> str:
        intent = analysis.get("intent", "unknown")
        confidence = analysis.get("confidence", 0.0)
        tier = analysis.get("intent_tier", "unknown")
        keywords = analysis.get("keywords", [])
        normalized_prompt = analysis.get("normalized_prompt", "")

        memory_context = ""
        if session_memory:
            memory_context = f"\n\nConversation history:\n{json.dumps(session_memory, indent=2)}"

        return f"""Analyze execution strategy for this request:

Intent: {intent}
Confidence: {confidence:.2f}
Tier: {tier}
Keywords: {', '.join(keywords)}
Request: \"{normalized_prompt}\"{memory_context}

Decide:
1. Can reasoning alone suffice?
2. Does this need real-time or external data?
3. What are the risks of each approach?

Return JSON following the schema."""

    def _build_response_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["direct", "research_first", "hybrid_parallel"],
                    "description": "Global execution strategy",
                },
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "reason": {"type": "string"},
                "risk": {
                    "type": "object",
                    "properties": {
                        "hallucination": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "missing_data": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "weak_reasoning": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["hallucination", "missing_data", "weak_reasoning"],
                },
                "suggested_tools": {"type": "array", "items": {"type": "string"}},
                "parallel_candidates": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
            },
            "required": ["strategy", "confidence", "reason", "risk", "suggested_tools"],
        }

    def _fallback_strategy(self, analysis: dict) -> MetaReasoningResult:
        tier = analysis.get("intent_tier", "research")

        if tier == "trivial":
            strategy = ExecutionStrategy.DIRECT
            hallucination = 0.1
            missing_data = 0.1
            weak_reasoning = 0.05
        elif tier == "lookup":
            strategy = ExecutionStrategy.RESEARCH_FIRST
            hallucination = 0.2
            missing_data = 0.3
            weak_reasoning = 0.1
        else:
            strategy = ExecutionStrategy.HYBRID_PARALLEL
            hallucination = 0.4
            missing_data = 0.5
            weak_reasoning = 0.3

        return MetaReasoningResult(
            strategy=strategy,
            confidence=0.4,
            reason=f"Fallback strategy based on intent tier: {tier}",
            risk=RiskProfile(
                hallucination_risk=hallucination,
                missing_data_risk=missing_data,
                weak_reasoning_risk=weak_reasoning,
            ),
            suggested_tools=["web_search"] if strategy != ExecutionStrategy.DIRECT else [],
            parallel_candidates=None,
        )
