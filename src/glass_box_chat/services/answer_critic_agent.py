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

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel


class CriticVerdictType(str, Enum):
    """Quality verdict types."""

    PASS = "pass"
    NEEDS_EVIDENCE = "needs_evidence"
    POTENTIAL_HALLUCINATION = "potential_hallucination"
    WEAK_REASONING = "weak_reasoning"
    MISSING_CONTEXT = "missing_context"
    CONTRADICTION = "contradiction"


class CriticIssue(BaseModel):
    """Single issue found by critic."""

    type: CriticVerdictType
    severity: float
    location: str
    description: str
    suggestion: Optional[str] = None


class AnswerCriticResult(BaseModel):
    """Output from Answer Critic Agent."""

    is_safe: bool
    needs_revision: bool
    overall_quality: float
    issues: list[CriticIssue] = []
    confidence: float
    revision_strategy: Optional[str] = None


@dataclass
class AnswerCriticAgent:
    """Quality control gate for synthesized answers."""

    _call_model: Callable

    async def critique_output(
        self,
        analysis: dict,
        dag_outputs: dict,
        synthesized: dict,
        session_id: Optional[str] = None,
    ) -> AnswerCriticResult:
        answer_text = synthesized.get("text", "")
        sources = synthesized.get("sources", [])

        prompt = self._build_critique_prompt(
            analysis.get("normalized_prompt", ""),
            answer_text,
            sources,
            dag_outputs,
        )
        schema = self._build_response_schema()

        try:
            result = await self._call_model(
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                schema=schema,
            )

            issues: list[CriticIssue] = []
            for issue_data in result.get("issues", []):
                try:
                    issues.append(
                        CriticIssue(
                            type=CriticVerdictType(issue_data.get("type", "weak_reasoning")),
                            severity=float(issue_data.get("severity", 0.3)),
                            location=issue_data.get("location", ""),
                            description=issue_data.get("description", ""),
                            suggestion=issue_data.get("suggestion"),
                        )
                    )
                except Exception:
                    pass

            overall_quality = float(result.get("overall_quality", 0.5))
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
        except Exception:
            return self._fallback_critique(answer_text, sources)

    def _system_prompt(self) -> str:
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
        sources: list[dict],
        dag_outputs: dict,
    ) -> str:
        sources_text = ""
        if sources:
            sources_text = "\n\nAvailable Sources:\n"
            for index, source in enumerate(sources[:5], start=1):
                title = source.get("title", "Untitled")
                url = source.get("url", "")
                snippet = source.get("snippet", "")[:200]
                sources_text += f"{index}. {title}\n   URL: {url}\n   Snippet: {snippet}\n"

        dag_outputs_text = ""
        if dag_outputs:
            dag_outputs_text = "\n\nExecution Outputs:\n"
            for task_id, output in list(dag_outputs.items())[:3]:
                output_str = str(output)[:300]
                dag_outputs_text += f"- {task_id}: {output_str}\n"

        return f"""Critique this synthesized answer:

USER REQUEST:
\"{user_request}\"

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

    def _build_response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "is_safe": {"type": "boolean", "description": "Is answer safe to return?"},
                "overall_quality": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Overall quality score (0.0-1.0)",
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
                                    "missing_context",
                                ],
                            },
                            "severity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "location": {"type": "string", "description": "Where in answer (e.g., 'paragraph 2')"},
                            "description": {"type": "string", "description": "What's the issue?"},
                            "suggestion": {"type": ["string", "null"], "description": "How to fix?"},
                        },
                        "required": ["type", "severity", "location", "description"],
                    },
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "How confident in this critique?",
                },
                "revision_strategy": {
                    "type": ["string", "null"],
                    "enum": ["research_more", "refine", "rerun", None],
                    "description": "If issues found, how to improve?",
                },
            },
            "required": ["is_safe", "overall_quality", "issues", "confidence"],
        }

    def _fallback_critique(self, answer_text: str, sources: list[dict]) -> AnswerCriticResult:
        has_sources = len(sources) > 0
        answer_length = len(answer_text)
        is_confident = answer_length > 100 and has_sources

        issues: list[CriticIssue] = []
        if not has_sources:
            issues.append(
                CriticIssue(
                    type=CriticVerdictType.NEEDS_EVIDENCE,
                    severity=0.5,
                    location="overall",
                    description="No sources provided",
                    suggestion="Add source references",
                )
            )

        return AnswerCriticResult(
            is_safe=is_confident,
            needs_revision=not is_confident,
            overall_quality=0.6 if is_confident else 0.4,
            issues=issues,
            confidence=0.3,
            revision_strategy="research_more" if not has_sources else None,
        )
