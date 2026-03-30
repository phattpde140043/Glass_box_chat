"""
Meta-Reasoning Agent: Global execution strategy decision maker.

Role: Decides global execution strategy (direct | research_first | hybrid_parallel)
       based on intent analysis, NOT hardcoded rules.

Placement: AFTER InputAnalyzer, BEFORE Planner

This agent:
1. Analyzes input analysis results
2. Reasons about execution risk (hallucination, missing_data, weak_reasoning)
3. Decides optimal strategy with confidence
4. Returns strategy for Planner to build appropriate DAG
"""

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Callable, Optional

from pydantic import BaseModel


class ExecutionStrategy(str, Enum):
    """Global execution strategy types."""
    DIRECT = "direct"  # Use reasoning only, no external tools
    RESEARCH_FIRST = "research_first"  # fetch data first, then reason
    HYBRID_PARALLEL = "hybrid_parallel"  # run reasoning + research in parallel (FusionSkill)


class RiskProfile(BaseModel):
    """Risk assessment for different strategies."""
    hallucination_risk: float  # 0.0-1.0: likely to generate false info
    missing_data_risk: float  # 0.0-1.0: likely to lack needed data
    weak_reasoning_risk: float  # 0.0-1.0: reasoning may be insufficient


class MetaReasoningResult(BaseModel):
    """Output from Meta-Reasoning Agent."""
    strategy: ExecutionStrategy  # Chosen strategy
    confidence: float  # 0.0-1.0: how certain is this strategy?
    reason: str  # Natural language explanation
    risk: RiskProfile  # Risk assessment
    suggested_tools: list[str]  # Suggested tools to use (advisory)
    parallel_candidates: Optional[list[str]] = None  # If hybrid_parallel, which skills to run in parallel


class MetaReasoningAgent:
    """
    Global strategy decision-maker for execution pipeline.
    
    Replaces hardcoded rules with LLM-based reasoning about:
    - When to trust reasoning alone
    - When to fetch external data
    - When to run both in parallel (hybrid)
    """
    
    def __init__(self, call_model: Callable):
        """
        Args:
            call_model: Async function to call LLM
                       Signature: call_model(messages, schema) -> dict
        """
        self._call_model = call_model
    
    async def analyze_strategy(
        self,
        analysis: dict,  # From InputAnalyzer (intent, confidence, tier, keywords)
        session_memory: Optional[dict] = None,  # Session context
        session_id: Optional[str] = None,
    ) -> MetaReasoningResult:
        """
        Decide global execution strategy based on analysis.
        
        Args:
            analysis: From InputAnalyzer
                     {intent, confidence, intent_tier, keywords, normalized_prompt, ...}
            session_memory: Session-scoped context for follow-up questions
            session_id: Session ID for tracking
        
        Returns:
            MetaReasoningResult with strategy, confidence, risk, etc.
        """
        # Build LLM prompt for strategy reasoning
        user_prompt = self._build_strategy_prompt(analysis, session_memory)
        
        # Combine system + user message into single prompt
        full_prompt = f"{self._system_prompt()}\n\n{user_prompt}"
        
        try:
            response_text = self._call_model(full_prompt)
            result = self._parse_json_response(response_text)
            
            # Parse & validate result
            strategy_result = MetaReasoningResult(
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
            
            return strategy_result
            
        except Exception as e:
            # Fallback to conservative default (hybrid_parallel is safest)
            print(f"[MetaReasoningAgent] LLM call failed: {e}")
            return self._fallback_strategy(analysis)
    
    def _system_prompt(self) -> str:
        """System instructions for Meta-Reasoning Agent."""
        return """You are a Meta-Reasoning Agent responsible for deciding the GLOBAL execution strategy.

Your job is to analyze the user's intent and determine:
1. Can we answer this with reasoning alone? (DIRECT)
2. Do we need to fetch external data first? (RESEARCH_FIRST)
3. Should we run both reasoning & research in parallel? (HYBRID_PARALLEL)

Consider:
- Intent complexity
- Timeliness requirements (market prices, news → need research)
- Risk of hallucination (factual claims → higher risk)
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
        """Build detailed prompt for strategy reasoning."""
        intent = analysis.get("intent", "unknown")
        confidence = analysis.get("confidence", 0.0)
        tier = analysis.get("intent_tier", "unknown")
        keywords = analysis.get("keywords", [])
        normalized_prompt = analysis.get("normalized_prompt", "")
        
        memory_context = ""
        if session_memory:
            memory_context = f"\n\nConversation history:\n{json.dumps(session_memory, indent=2)}"
        
        prompt = f"""Analyze execution strategy for this request:

Intent: {intent}
Confidence: {confidence:.2f}
Tier: {tier}
Keywords: {', '.join(keywords)}
Request: "{normalized_prompt}"{memory_context}

Decide:
1. Can reasoning alone suffice?
2. Does this need real-time or external data?
3. What are the risks of each approach?

Return JSON following the schema."""
        
        return prompt
    
    def _build_response_schema(self) -> dict:
        """JSON schema for LLM response."""
        return {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["direct", "research_first", "hybrid_parallel"],
                    "description": "Global execution strategy"
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Confidence in this strategy (0.0-1.0)"
                },
                "reason": {
                    "type": "string",
                    "description": "Natural language explanation"
                },
                "risk": {
                    "type": "object",
                    "properties": {
                        "hallucination": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "missing_data": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "weak_reasoning": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["hallucination", "missing_data", "weak_reasoning"]
                },
                "suggested_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools to consider (web_search, finance, weather, etc.)"
                },
                "parallel_candidates": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "For hybrid_parallel: which skills to run in parallel"
                },
            },
            "required": ["strategy", "confidence", "reason", "risk", "suggested_tools"]
        }
    
    @staticmethod
    def _parse_json_response(response_text: str) -> dict:
        """Extract and parse JSON from LLM response."""

        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response_text)
        if json_match:
            json_text = json_match.group(1).strip()
        else:
            # Try to find JSON object directly
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            json_text = json_match.group(0) if json_match else response_text
        
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            return {}
    
    def _fallback_strategy(self, analysis: dict) -> MetaReasoningResult:
        """Fallback strategy when LLM unavailable."""
        tier = analysis.get("intent_tier", "research")
        
        # Conservative fallback rules
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
        else:  # research, complex
            strategy = ExecutionStrategy.HYBRID_PARALLEL
            hallucination = 0.4
            missing_data = 0.5
            weak_reasoning = 0.3
        
        return MetaReasoningResult(
            strategy=strategy,
            confidence=0.4,  # Low confidence in fallback
            reason=f"Fallback strategy based on intent tier: {tier}",
            risk=RiskProfile(
                hallucination_risk=hallucination,
                missing_data_risk=missing_data,
                weak_reasoning_risk=weak_reasoning,
            ),
            suggested_tools=["web_search"] if strategy != ExecutionStrategy.DIRECT else [],
            parallel_candidates=None,
        )
