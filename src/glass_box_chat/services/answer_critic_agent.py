"""
Answer Critic Agent: Quality control gate for synthesized answers.

Role: Evaluates the synthesized answer before returning to user
      Detects hallucinations, missing evidence, weak reasoning
      Can trigger re-execution with different strategy if needed

Placement: BEFORE FinalResponseBuilder

This agent:
1. Analyzes synthesized output (text + sources)
2. Cross-checks claims against source evidence
3. Detects hallucinations and missing data
4. Returns quality verdict + suggestions for improvement
"""

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Any

from pydantic import BaseModel


class CriticVerdictType(str, Enum):
    """Quality verdict types."""
    PASS = "pass"  # Answer is good to return
    NEEDS_EVIDENCE = "needs_evidence"  # Missing supporting sources
    POTENTIAL_HALLUCINATION = "potential_hallucination"  # Claims not backed by sources
    WEAK_REASONING = "weak_reasoning"  # Logic gaps detected
    MISSING_CONTEXT = "missing_context"  # Should add more data
    CONTRADICTION = "contradiction"  # Internal inconsistencies


class CriticIssue(BaseModel):
    """Single issue found by critic."""
    type: CriticVerdictType
    severity: float  # 0.0-1.0: how serious?
    location: str  # Which part of answer (e.g., "paragraph 1", "conclusion")
    description: str  # Explanation
    suggestion: Optional[str] = None  # How to fix


class AnswerCriticResult(BaseModel):
    """Output from Answer Critic Agent."""
    is_safe: bool  # Safe to return to user?
    needs_revision: bool  # Should we try to improve?
    overall_quality: float  # 0.0-1.0: overall quality score
    issues: list[CriticIssue] = []  # List of detected issues
    confidence: float  # How confident in this verdict?
    revision_strategy: Optional[str] = None  # If needs_revision: "research_more" | "refine" | "rerun"


class AnswerCriticAgent:
    """
    Quality control gate for synthesized answers.
    
    Runs before FinalResponseBuilder to catch:
    - Hallucinations (claims not in sources)
    - Missing evidence (unsupported assertions)
    - Weak reasoning (logic gaps)
    - Contradictions (internal inconsistencies)
    """
    
    def __init__(self, call_model: Callable):
        """
        Args:
            call_model: Async function to call LLM
        """
        self._call_model = call_model
    
    async def critique_output(
        self,
        analysis: dict,  # From InputAnalyzer
        dag_outputs: dict,  # From Executor {node_id: result}
        synthesized: dict,  # From SynthesizerSkill {text, sources}
        session_id: Optional[str] = None,
    ) -> AnswerCriticResult:
        """
        Critique synthesized answer before returning.
        
        Args:
            analysis: Original input analysis
            dag_outputs: Execution results {task_id: output}
            synthesized: Synthesized output {text, sources, ...}
            session_id: Session context
        
        Returns:
            AnswerCriticResult with verdict, issues, suggestions
        """
        answer_text = synthesized.get("text", "")
        sources = synthesized.get("sources", [])
        
        user_prompt = self._build_critique_prompt(
            analysis.get("normalized_prompt", ""),
            answer_text,
            sources,
            dag_outputs,
        )
        
        # Combine system + user message into single prompt
        full_prompt = f"{self._system_prompt()}\n\n{user_prompt}"
        
        try:
            response_text = self._call_model(full_prompt)
            result = self._parse_json_response(response_text)
            
            # Parse issues
            issues = []
            for issue_data in result.get("issues", []):
                try:
                    issues.append(CriticIssue(
                        type=CriticVerdictType(issue_data.get("type", "weak_reasoning")),
                        severity=float(issue_data.get("severity", 0.3)),
                        location=issue_data.get("location", ""),
                        description=issue_data.get("description", ""),
                        suggestion=issue_data.get("suggestion"),
                    ))
                except Exception:
                    pass  # Skip malformed issues
            
            overall_quality = float(result.get("overall_quality", 0.5))
            
            # Determine if safe/needs_revision
            is_safe = len(issues) == 0 or overall_quality >= 0.6
            needs_revision = len(issues) > 0
            
            return AnswerCriticResult(
                is_safe=is_safe,
                needs_revision=needs_revision,
                overall_quality=overall_quality,
                issues=issues,
                confidence=float(result.get("confidence", 0.5)),
                revision_strategy=result.get("revision_strategy"),
            )
            
        except Exception as e:
            print(f"[AnswerCriticAgent] LLM call failed: {e}")
            return self._fallback_critique(answer_text, sources)
    
    def _system_prompt(self) -> str:
        """System instructions for Answer Critic."""
        return """You are an Answer Critic Agent responsible for quality control.

Your job is to evaluate synthesized answers for:
1. HALLUCINATIONS: Claims not supported by sources
2. MISSING EVIDENCE: Important claims need sources
3. WEAK REASONING: Logic gaps or unsupported jumps
4. CONTRADICTIONS: Internal inconsistencies
5. MISSING CONTEXT: Should add more data/sources

For each issue found:
- Identify the TYPE (hallucination | needs_evidence | weak_reasoning | contradiction | missing_context)
- Rate SEVERITY (0.0-1.0)
- Specify LOCATION in answer
- Suggest solution

Return JSON with:
- is_safe: bool (safe to return?)
- overall_quality: float 0.0-1.0
- issues: list of detected problems
- confidence: 0.0-1.0 (how sure are you?)
- revision_strategy: if issues found, "research_more" | "refine" | "rerun"

Be thorough but fair. Minor issues don't need revision."""
    
    def _build_critique_prompt(
        self,
        user_request: str,
        answer_text: str,
        sources: list[dict | str],
        dag_outputs: dict,
    ) -> str:
        """Build detailed prompt for critique reasoning."""
        
        sources_text = ""
        if sources:
            sources_text = "\n\nAvailable Sources:\n"
            for i, source in enumerate(sources[:5], 1):  # First 5 sources
                if isinstance(source, dict):
                    title = str(source.get("title", "Untitled"))
                    url = str(source.get("url", ""))
                    snippet = str(source.get("snippet", ""))[:200]
                else:
                    # Some flows provide plain URL strings instead of source objects.
                    title = "Source"
                    url = str(source)
                    snippet = ""
                sources_text += f"{i}. {title}\n   URL: {url}\n   Snippet: {snippet}\n"
        
        dag_outputs_text = ""
        if dag_outputs:
            dag_outputs_text = "\n\nExecution Outputs:\n"
            for task_id, output in list(dag_outputs.items())[:3]:
                if isinstance(output, dict):
                    output_str = str(output)[:300]
                else:
                    output_str = str(output)[:300]
                dag_outputs_text += f"- {task_id}: {output_str}\n"
        
        prompt = f"""Critique this synthesized answer:

USER REQUEST:
"{user_request}"

SYNTHESIZED ANSWER:
{answer_text}
{sources_text}
{dag_outputs_text}

Evaluate:
1. Are all claims supported by sources?
2. Any logical gaps or weak reasoning?
3. Missing important context?
4. Any hallucinations or made-up facts?
5. Internal consistency?

Return JSON following the schema."""
        
        return prompt
    
    def _build_response_schema(self) -> dict:
        """JSON schema for critic response."""
        return {
            "type": "object",
            "properties": {
                "is_safe": {
                    "type": "boolean",
                    "description": "Is answer safe to return?"
                },
                "overall_quality": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Overall quality score (0.0-1.0)"
                },
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "hallucination",
                                    "needs_evidence",
                                    "weak_reasoning",
                                    "contradiction",
                                    "missing_context"
                                ]
                            },
                            "severity": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0
                            },
                            "location": {
                                "type": "string",
                                "description": "Where in answer (e.g., 'paragraph 2')"
                            },
                            "description": {
                                "type": "string",
                                "description": "What's the issue?"
                            },
                            "suggestion": {
                                "type": ["string", "null"],
                                "description": "How to fix?"
                            }
                        },
                        "required": ["type", "severity", "location", "description"]
                    }
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "How confident in this critique?"
                },
                "revision_strategy": {
                    "type": ["string", "null"],
                    "enum": ["research_more", "refine", "rerun", None],
                    "description": "If issues found, how to improve?"
                }
            },
            "required": ["is_safe", "overall_quality", "issues", "confidence"]
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
    
    def _fallback_critique(self, answer_text: str, sources: list[dict | str]) -> AnswerCriticResult:
        """Fallback critique when LLM unavailable."""
        # Simple heuristics
        has_sources = len(sources) > 0
        answer_length = len(answer_text)
        is_confident = answer_length > 100 and has_sources
        
        issues = []
        if not has_sources:
            issues.append(CriticIssue(
                type=CriticVerdictType.NEEDS_EVIDENCE,
                severity=0.5,
                location="overall",
                description="No sources provided",
                suggestion="Add source references"
            ))
        
        return AnswerCriticResult(
            is_safe=is_confident,
            needs_revision=not is_confident,
            overall_quality=0.6 if is_confident else 0.4,
            issues=issues,
            confidence=0.3,  # Low confidence in heuristic
            revision_strategy="research_more" if not has_sources else None,
        )
