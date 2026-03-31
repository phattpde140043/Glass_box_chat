"""
Structured Synthesis Output Models: Pydantic models for deterministic synthesizer output.

Design: Instead of freeform text from LLM, use structured schema + post-rendering
This prevents hallucinations and format inconsistencies.

Components:
1. SynthesisPoint - Single claim with source attribution
2. StructuredSynthesis - Complete structured answer
3. SynthesisRenderer - Convert structured to markdown/plain text
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SynthesisPointType(str, Enum):
    """Type of synthesis point."""
    MAIN_CLAIM = "main_claim"              # Primary answer
    SUPPORTING_FACT = "supporting_fact"    # Fact that supports main claim
    CAVEAT = "caveat"                      # Limitation or exception
    CONFLICT_NOTE = "conflict_note"        # When sources disagree
    DEFINITION = "definition"              # Explanatory definition


class SynthesisPoint(BaseModel):
    """Single point in synthesis with source attribution."""
    
    type: SynthesisPointType                   # Type of point
    claim: str                                 # The actual claim/fact
    confidence: float = Field(ge=0.0, le=1.0) # 0.0-1.0 confidence
    sources: list[str]                        # URLs backing this claim
    explanation: Optional[str] = None         # Why we selected these sources
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "type": "main_claim",
                    "claim": "The iPhone 15 was released in September 2023",
                    "confidence": 0.98,
                    "sources": ["https://apple.com/newsroom", "https://techcrunch.com"],
                    "explanation": "Multiple authoritative sources confirm this date"
                }
            ]
        }


class StructuredSynthesis(BaseModel):
    """Complete structured answer before rendering."""
    
    title: Optional[str] = None              # Optional title/summary
    main_claim: SynthesisPoint               # Primary answer point
    supporting_points: list[SynthesisPoint] = []  # Evidence/details
    caveats: list[SynthesisPoint] = []      # Limitations
    conflict_notes: list[SynthesisPoint] = [] # Conflicts between sources
    all_sources: list[str]                  # Deduplicated source URLs
    quality_metrics: dict[str, float] = {}  # {confidence, coverage, freshness_score}
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "title": "iPhone 15 Release Timeline",
                    "main_claim": {
                        "type": "main_claim",
                        "claim": "The iPhone 15 was released in September 2023",
                        "confidence": 0.98,
                        "sources": ["https://apple.com"],
                    },
                    "supporting_points": [
                        {
                            "type": "supporting_fact",
                            "claim": "Apple announced it on September 12, 2023",
                            "confidence": 0.97,
                            "sources": ["https://apple.com", "https://techcrunch.com"],
                        }
                    ],
                    "caveats": [
                        {
                            "type": "caveat",
                            "claim": "Exact release time varies by region",
                            "confidence": 0.95,
                            "sources": ["https://apple.com"],
                        }
                    ],
                    "conflict_notes": [],
                    "all_sources": ["https://apple.com"],
                    "quality_metrics": {
                        "overall_confidence": 0.97,
                        "coverage": 0.85,
                        "freshness": 0.72
                    }
                }
            ]
        }


class SynthesisSchema(BaseModel):
    """Schema for constraining LLM output when generating synthesis."""
    
    main_answer: str = Field(description="The main answer (150-500 chars)")
    key_points: list[str] = Field(
        description="3-5 supporting bullet points",
        min_items=0,
        max_items=5
    )
    sources_used: dict[str, list[str]] = Field(
        description="Map of point -> list of source URLs used",
        examples=[{
            "The iPhone 15 was released in September 2023": [
                "https://apple.com/newsroom",
                "https://techcrunch.com/article"
            ]
        }]
    )
    caveats: list[str] = Field(
        description="Any limitations or assumptions",
        min_items=0,
        max_items=3
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall confidence (0.0-1.0)"
    )
    
    class Config:
        json_schema_extra = {
            "description": "Constrained schema for LLM synthesis output"
        }


# Helper model for mapping sources to claims
class SourceAttribution(BaseModel):
    """Maps a claim to supporting sources."""
    
    claim: str                          # The claim text
    sources: list[str]                  # URLs supporting this claim
    confidence: float = Field(ge=0.0, le=1.0)  # 0.0-1.0


@dataclass
class SynthesisContext:
    """Context passed to renderer."""
    
    answer_text: str                    # Main answer from LLM
    research_sources: list[dict]        # All research sources
    analysis_results: list[dict] = None # Any analysis results
    conflict_notes: list[str] = None    # Detected conflicts
    confidence_score: float = 0.5       # Overall confidence
    include_sources_section: bool = True  # Add "Sources" at end?


class SynthesisRenderer:
    """Convert structured synthesis to readable formats."""
    
    @staticmethod
    def render_markdown(synthesis: StructuredSynthesis) -> str:
        """Render structured synthesis as markdown."""
        
        lines: list[str] = []
        
        # Title
        if synthesis.title:
            lines.append(f"## {synthesis.title}\n")
        
        # Main claim
        main = synthesis.main_claim
        lines.append(f"{main.claim}\n")
        
        # Supporting points
        if synthesis.supporting_points:
            lines.append("### Key Points")
            for point in synthesis.supporting_points:
                if point.sources:
                    urls_str = " | ".join([f"[source]({url})" for url in point.sources[:2]])
                    lines.append(f"- {point.claim} ({urls_str})")
                else:
                    lines.append(f"- {point.claim}")
            lines.append("")
        
        # Caveats
        if synthesis.caveats:
            lines.append("### Important Notes")
            for caveat in synthesis.caveats:
                lines.append(f"- {caveat.claim}")
            lines.append("")
        
        # Conflicts
        if synthesis.conflict_notes:
            lines.append("### Conflicts in Sources")
            for conflict in synthesis.conflict_notes:
                lines.append(f"- {conflict.claim}")
            lines.append("")
        
        # Sources
        if synthesis.all_sources:
            lines.append("### Sources")
            for url in synthesis.all_sources:
                lines.append(f"- {url}")
        
        return "\n".join(lines)
    
    @staticmethod
    def render_plain_text(synthesis: StructuredSynthesis) -> str:
        """Render structured synthesis as plain text."""
        
        lines: list[str] = []
        
        if synthesis.title:
            lines.append(synthesis.title)
            lines.append("=" * len(synthesis.title))
            lines.append("")
        
        lines.append(synthesis.main_claim.claim)
        lines.append("")
        
        if synthesis.supporting_points:
            lines.append("Key Points:")
            for point in synthesis.supporting_points:
                confidence_str = f" (confidence: {point.confidence:.0%})" if point.confidence else ""
                lines.append(f"• {point.claim}{confidence_str}")
            lines.append("")
        
        if synthesis.caveats:
            lines.append("Important Notes:")
            for caveat in synthesis.caveats:
                lines.append(f"• {caveat.claim}")
            lines.append("")
        
        if synthesis.conflict_notes:
            lines.append("Conflicts in Sources:")
            for conflict in synthesis.conflict_notes:
                lines.append(f"• {conflict.claim}")
            lines.append("")
        
        if synthesis.all_sources:
            lines.append("Sources:")
            for i, url in enumerate(synthesis.all_sources, 1):
                lines.append(f"{i}. {url}")
        
        return "\n".join(lines)
    
    @staticmethod
    def render_with_metadata(
        synthesis: StructuredSynthesis,
        format_type: str = "markdown"
    ) -> dict:
        """Render with metadata."""
        
        if format_type == "markdown":
            rendered = SynthesisRenderer.render_markdown(synthesis)
        elif format_type == "plain_text":
            rendered = SynthesisRenderer.render_plain_text(synthesis)
        else:
            rendered = str(synthesis.main_claim.claim)
        
        return {
            "text": rendered,
            "sources": synthesis.all_sources,
            "confidence": synthesis.quality_metrics.get("overall_confidence", 0.5),
            "is_synthesis": True,
            "has_caveats": len(synthesis.caveats) > 0,
            "has_conflicts": len(synthesis.conflict_notes) > 0,
        }


# Example builder function
def build_structured_synthesis(
    main_answer: str,
    supporting_points: list[tuple[str, list[str]]] = None,  # (claim, [urls])
    caveats: list[str] = None,
    sources: list[str] = None,
    confidence: float = 0.7,
    title: Optional[str] = None,
) -> StructuredSynthesis:
    """Helper to build StructuredSynthesis."""
    
    main_point = SynthesisPoint(
        type=SynthesisPointType.MAIN_CLAIM,
        claim=main_answer,
        confidence=confidence,
        sources=sources or [],
    )
    
    supporting = []
    if supporting_points:
        for claim, urls in supporting_points:
            supporting.append(
                SynthesisPoint(
                    type=SynthesisPointType.SUPPORTING_FACT,
                    claim=claim,
                    confidence=0.9,
                    sources=urls,
                )
            )
    
    caveat_points = []
    if caveats:
        for caveat in caveats:
            caveat_points.append(
                SynthesisPoint(
                    type=SynthesisPointType.CAVEAT,
                    claim=caveat,
                    confidence=0.8,
                    sources=[],
                )
            )
    
    all_sources = list(set(sources or []))
    for _, urls in (supporting_points or []):
        all_sources.extend(urls)
    all_sources = list(set(all_sources))
    
    return StructuredSynthesis(
        title=title,
        main_claim=main_point,
        supporting_points=supporting,
        caveats=caveat_points,
        conflict_notes=[],
        all_sources=all_sources,
        quality_metrics={
            "overall_confidence": confidence,
            "coverage": 0.8,
            "freshness": 0.7,
        }
    )
