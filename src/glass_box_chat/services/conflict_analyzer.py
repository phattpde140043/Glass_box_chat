"""
Conflict Analyzer: Detects semantic conflicts between research sources.

Role: Identifies when multiple sources provide contradictory information
       and categorizes conflict type (direct contradiction, nuance difference, etc.)

Placement: BEFORE Synthesizer to provide conflict-aware synthesis

Benefits:
- Transparent conflict handling (not silent picks)
- User sees reasoning why sources conflict
- Higher trust through explainability
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel


class ConflictType(str, Enum):
    """Types of conflicts between sources."""
    DIRECT_CONTRADICTION = "direct_contradiction"  # "A won" vs "B won"
    NUANCE_DIFFERENCE = "nuance_difference"         # Both true but different angles
    MISSING_DATA = "missing_data"                   # One has data, other doesn't
    OUTDATED_VS_FRESH = "outdated_vs_fresh"        # Same metric, different timestamps


class ConflictSeverity(str, Enum):
    """How serious is the conflict?"""
    CRITICAL = "critical"              # Cannot both be true (e.g., opposite outcomes)
    HIGH = "high"                      # Significantly different claims
    MEDIUM = "medium"                  # Noteworthy differences
    LOW = "low"                        # Minor variations or different scopes


class SourceClaimsModel(BaseModel):
    """Extracted claims from a single source."""
    url: str                           # Source URL
    title: str                         # Source title
    main_claim: str                    # Primary claim/statement
    subject: str                       # What is being claimed about?
    confidence: float                  # How confident is this claim (0.0-1.0)
    published_at: Optional[str] = None # Publication date


class ConflictFinding(BaseModel):
    """A detected conflict between 2+ sources."""
    type: ConflictType                 # Type of conflict
    severity: ConflictSeverity         # How serious?
    sources: list[str]                 # URLs of conflicting sources
    claim_a: str                       # First claim
    claim_b: str                       # Second claim (or alternate claim)
    explanation: str                   # Why do they conflict?
    resolution_hint: Optional[str] = None  # Suggested way to resolve conflict
    requires_user_attention: bool      # Should synthesizer flag this?


class ConflictAnalysisResult(BaseModel):
    """Output from ConflictAnalyzer."""
    has_conflicts: bool                       # Any conflicts found?
    conflicts: list[ConflictFinding] = []    # List of conflicts
    conflict_count: int = 0                  # Total count
    critical_conflicts: int = 0              # Count of critical severity
    affected_sources: list[str] = []         # URLs with conflicts
    synthesis_guidance: str = ""             # Advice for Synthesizer


class ConflictAnalyzer:
    """
    Detects semantic conflicts between research sources.
    
    Usage:
        analyzer = ConflictAnalyzer(call_model=llm_service.call_unstructured)
        result = await analyzer.analyze_sources(sources=[...])
        
        if result.has_conflicts:
            # Add conflict block to synthesizer prompt
            prompt = f"{base_prompt}\n\nConflicts:\n{result.conflicts}"
    """
    
    def __init__(self, call_model: Optional[Callable] = None):
        """
        Args:
            call_model: Optional LLM function for semantic conflict detection
                       If None, uses heuristic-only analysis
        """
        self._call_model = call_model
    
    async def analyze_sources(
        self,
        sources: list[dict],  # List of source dicts {url, title, snippet}
        query: str = "",      # Original query for context
    ) -> ConflictAnalysisResult:
        """
        Analyze sources for conflicts.
        
        Args:
            sources: List of source dicts with {url, title, snippet}
            query: Original user query for context
        
        Returns:
            ConflictAnalysisResult with conflicts found
        """
        
        if len(sources) < 2:
            return ConflictAnalysisResult(
                has_conflicts=False,
                conflicts=[],
                conflict_count=0,
                critical_conflicts=0,
            )
        
        # Step 1: Extract claims from each source
        claims = []
        for source in sources:
            claim = self._extract_claim_from_source(source, query)
            if claim:
                claims.append(claim)
        
        if len(claims) < 2:
            return ConflictAnalysisResult(has_conflicts=False)
        
        # Step 2: Pairwise comparison of claims
        conflicts: list[ConflictFinding] = []
        
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                conflict = await self._detect_conflict_between(
                    claims[i],
                    claims[j],
                    query=query
                )
                if conflict:
                    conflicts.append(conflict)
        
        # Step 3: Deduplicate & rank conflicts
        conflicts = self._deduplicate_conflicts(conflicts)
        conflicts.sort(key=lambda c: self._severity_score(c.severity), reverse=True)
        
        # Step 4: Build result
        critical_count = sum(
            1 for c in conflicts 
            if c.severity == ConflictSeverity.CRITICAL
        )
        
        affected_urls = set()
        for conflict in conflicts:
            affected_urls.update(conflict.sources)
        
        synthesis_guidance = self._build_synthesis_guidance(conflicts)
        
        return ConflictAnalysisResult(
            has_conflicts=len(conflicts) > 0,
            conflicts=conflicts,
            conflict_count=len(conflicts),
            critical_conflicts=critical_count,
            affected_sources=list(affected_urls),
            synthesis_guidance=synthesis_guidance,
        )
    
    @staticmethod
    def _extract_claim_from_source(source: dict, query: str) -> Optional[SourceClaimsModel]:
        """Extract main claim from a source."""
        
        title = str(source.get("title", "")).strip()
        snippet = str(source.get("snippet", "")).strip()
        url = str(source.get("url", "")).strip()
        published_at = source.get("published_at")
        reliability = float(source.get("reliability", 0.7))
        
        if not snippet:
            return None
        
        # Extract subject (usually from query or title)
        subject = query.strip() if query else title[:60]
        
        # Use snippet as main claim
        main_claim = snippet[:250]
        
        return SourceClaimsModel(
            url=url,
            title=title,
            main_claim=main_claim,
            subject=subject,
            confidence=reliability,
            published_at=str(published_at) if published_at else None,
        )
    
    async def _detect_conflict_between(
        self,
        claim_a: SourceClaimsModel,
        claim_b: SourceClaimsModel,
        query: str = "",
    ) -> Optional[ConflictFinding]:
        """Detect if two claims conflict."""
        
        # Heuristic check first (fast path)
        heuristic_conflict = self._heuristic_detect_conflict(claim_a, claim_b)
        if heuristic_conflict:
            return heuristic_conflict
        
        # LLM-based semantic check (if available and no heuristic conflict)
        if self._call_model:
            llm_conflict = await self._llm_detect_conflict(
                claim_a, claim_b, query
            )
            if llm_conflict:
                return llm_conflict
        
        # No conflict detected
        return None
    
    @staticmethod
    def _heuristic_detect_conflict(
        claim_a: SourceClaimsModel,
        claim_b: SourceClaimsModel,
    ) -> Optional[ConflictFinding]:
        """Fast heuristic-based conflict detection."""
        
        # Different subjects → no conflict
        if claim_a.subject.lower() != claim_b.subject.lower():
            return None
        
        text_a = claim_a.main_claim.lower()
        text_b = claim_b.main_claim.lower()
        
        # Direct contradiction patterns
        contradiction_words = [
            ("won", "lost"),
            ("up", "down"),
            ("increase", "decrease"),
            ("rises", "falls"),
            ("tanged", "giam"),  # Vietnamese
            ("tăng", "giảm"),
            ("yes", "no"),
            ("true", "false"),
            ("possible", "impossible"),
            ("likely", "unlikely"),
        ]
        
        for word_a, word_b in contradiction_words:
            has_a = word_a in text_a
            has_b = word_b in text_b
            has_opposite_a = word_b in text_a
            has_opposite_b = word_a in text_b
            
            if (has_a and has_b) or (has_opposite_a and has_opposite_b):
                return ConflictFinding(
                    type=ConflictType.DIRECT_CONTRADICTION,
                    severity=ConflictSeverity.CRITICAL,
                    sources=[claim_a.url, claim_b.url],
                    claim_a=claim_a.main_claim[:150],
                    claim_b=claim_b.main_claim[:150],
                    explanation=f"One says '{word_a}', other says '{word_b}' for same subject",
                    resolution_hint=f"Check publication dates or credibility; verify which is current.",
                    requires_user_attention=True,
                )
        
        # High-value disagreement (numbers that differ significantly)
        numbers_a = ConflictAnalyzer._extract_numeric_claims(text_a)
        numbers_b = ConflictAnalyzer._extract_numeric_claims(text_b)
        
        if numbers_a and numbers_b:
            for num_a in numbers_a:
                for num_b in numbers_b:
                    spread_ratio = abs(num_a - num_b) / max(abs(num_a), 1.0)
                    if spread_ratio > 0.15:  # More than 15% difference
                        return ConflictFinding(
                            type=ConflictType.DIRECT_CONTRADICTION,
                            severity=ConflictSeverity.HIGH,
                            sources=[claim_a.url, claim_b.url],
                            claim_a=claim_a.main_claim[:150],
                            claim_b=claim_b.main_claim[:150],
                            explanation=f"Numeric values differ significantly: {num_a} vs {num_b}",
                            resolution_hint="Check unit/scale differences or recency of data",
                            requires_user_attention=True,
                        )
        
        # Outdated vs fresh (if dates available)
        date_a = claim_a.published_at or ""
        date_b = claim_b.published_at or ""
        
        if date_a and date_b and date_a != date_b:
            # One is older → might explain differences
            return ConflictFinding(
                type=ConflictType.OUTDATED_VS_FRESH,
                severity=ConflictSeverity.MEDIUM,
                sources=[claim_a.url, claim_b.url],
                claim_a=claim_a.main_claim[:150],
                claim_b=claim_b.main_claim[:150],
                explanation=f"Different publication dates: {date_a} vs {date_b}",
                resolution_hint="Prefer more recent source if data is time-sensitive",
                requires_user_attention=False,
            )
        
        return None
    
    async def _llm_detect_conflict(
        self,
        claim_a: SourceClaimsModel,
        claim_b: SourceClaimsModel,
        query: str = "",
    ) -> Optional[ConflictFinding]:
        """Use LLM for semantic conflict detection."""
        
        if not self._call_model:
            return None
        
        prompt = f"""Determine if these two claims about "{claim_a.subject}" conflict:

Source 1: {claim_a.title}
Claim A: {claim_a.main_claim}

Source 2: {claim_b.title}
Claim B: {claim_b.main_claim}

Respond with JSON:
{{
  "is_conflict": boolean,
  "conflict_type": "direct_contradiction" | "nuance_difference" | "missing_data" | "outdated_vs_fresh" | "none",
  "severity": "critical" | "high" | "medium" | "low",
  "explanation": "Why do they conflict (or why not)?",
  "resolution_hint": "How to resolve if needed?"
}}

Be precise. Only return "is_conflict": true if they actually contradict."""
        
        try:
            response = await self._call_model(prompt)
            conflict_data = self._parse_conflict_response(response)
            
            if conflict_data and conflict_data.get("is_conflict"):
                return ConflictFinding(
                    type=ConflictType(conflict_data.get("conflict_type", "direct_contradiction")),
                    severity=ConflictSeverity(conflict_data.get("severity", "medium")),
                    sources=[claim_a.url, claim_b.url],
                    claim_a=claim_a.main_claim[:150],
                    claim_b=claim_b.main_claim[:150],
                    explanation=conflict_data.get("explanation", "Conflict detected"),
                    resolution_hint=conflict_data.get("resolution_hint"),
                    requires_user_attention=conflict_data.get("severity") in ("critical", "high"),
                )
        except Exception:
            pass  # Fall back to heuristic result
        
        return None
    
    @staticmethod
    def _extract_numeric_claims(text: str) -> list[float]:
        """Extract numeric values from text."""
        numbers = []
        
        # Find percentages
        for match in re.finditer(r'(\d+(?:[.,]\d+)?)\s*%', text):
            try:
                num = float(match.group(1).replace(',', '.'))
                numbers.append(num)
            except ValueError:
                pass
        
        # Find currency values
        for match in re.finditer(r'[\$€£]\s*(\d+(?:[.,]\d+)?)', text):
            try:
                num = float(match.group(1).replace(',', '.'))
                numbers.append(num)
            except ValueError:
                pass
        
        # Find plain numbers (1-6 digits)
        for match in re.finditer(r'\b(\d{1,6}(?:[.,]\d{1,2})?)\b', text):
            try:
                num = float(match.group(1).replace(',', '.'))
                if 0 <= num <= 1_000_000:  # Reasonable range
                    numbers.append(num)
            except ValueError:
                pass
        
        return numbers
    
    @staticmethod
    def _parse_conflict_response(response: str) -> dict:
        """Parse JSON from LLM response."""
        import json
        
        # Extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
        if json_match:
            json_text = json_match.group(1).strip()
        else:
            # Try to find JSON object directly
            json_match = re.search(r'\{[\s\S]*\}', response)
            json_text = json_match.group(0) if json_match else response
        
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            return {}
    
    @staticmethod
    def _deduplicate_conflicts(conflicts: list[ConflictFinding]) -> list[ConflictFinding]:
        """Remove duplicate conflicts."""
        seen: set[frozenset[str]] = set()
        deduped: list[ConflictFinding] = []
        
        for conflict in conflicts:
            key = frozenset(conflict.sources)
            if key not in seen:
                seen.add(key)
                deduped.append(conflict)
        
        return deduped
    
    @staticmethod
    def _severity_score(severity: ConflictSeverity) -> int:
        """Score severity for sorting."""
        scores = {
            ConflictSeverity.CRITICAL: 4,
            ConflictSeverity.HIGH: 3,
            ConflictSeverity.MEDIUM: 2,
            ConflictSeverity.LOW: 1,
        }
        return scores.get(severity, 0)
    
    @staticmethod
    def _build_synthesis_guidance(conflicts: list[ConflictFinding]) -> str:
        """Build guidance for Synthesizer on handling conflicts."""
        
        if not conflicts:
            return ""
        
        critical = [c for c in conflicts if c.severity == ConflictSeverity.CRITICAL]
        
        if critical:
            urls = [url for c in critical for url in c.sources]
            return (
                f"Critical conflicts detected between sources. "
                f"MUST explicitly address these contradictions in synthesis:\n"
                f"{chr(10).join(f'- {c.explanation}' for c in critical[:2])}"
            )
        
        high_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.HIGH]
        if high_conflicts:
            return (
                f"Noteworthy conflicts detected. Explain these differences in answer:\n"
                f"{chr(10).join(f'- {c.explanation}' for c in high_conflicts[:2])}"
            )
        
        return ""
