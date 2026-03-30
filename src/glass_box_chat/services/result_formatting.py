from __future__ import annotations

import json
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


class ResearchSourceModel(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    snippet: str = Field(min_length=1, max_length=1200)
    url: str = Field(min_length=1, max_length=500)
    freshness: str = Field(min_length=1, max_length=80)
    published_at: str | None = Field(default=None, max_length=100)
    reliability: float = Field(default=0.55, ge=0.0, le=1.0)
    provider: str | None = Field(default=None, max_length=80)


class EvidenceModel(BaseModel):
    content: str = Field(min_length=1, max_length=1200)
    source: str = Field(min_length=1, max_length=500)
    timestamp: str | None = Field(default=None, max_length=100)
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    provider: str | None = Field(default=None, max_length=80)
    evidence_item_id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=50)


class ResearchResultEnvelopeModel(BaseModel):
    kind: Literal["research_result"]
    summary: str = Field(min_length=1, max_length=4000)
    grounded: bool = True
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    citations: list[str] = Field(default_factory=list, max_length=8)
    sources: list[ResearchSourceModel] = Field(default_factory=list, min_length=1, max_length=8)
    evidence: list[EvidenceModel] = Field(default_factory=list, max_length=12)


class AnalysisResultEnvelopeModel(BaseModel):
    kind: Literal["analysis_result"]
    summary: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    outlook: str = Field(default="neutral", min_length=1, max_length=120)
    data_points: list["AnalysisDataPointModel"] = Field(default_factory=list, max_length=20)
    data_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    conflict_count: int = Field(default=0, ge=0)
    evidence_quality: str = Field(default="low", min_length=1, max_length=40)


class AnalysisDataPointModel(BaseModel):
    metric: str = Field(min_length=1, max_length=80)
    value: float
    unit: str = Field(default="n/a", min_length=1, max_length=30)
    subject: str = Field(default="market", min_length=1, max_length=120)
    timestamp: str | None = Field(default=None, max_length=100)
    source: str = Field(min_length=1, max_length=500)
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=50)
    reliability: float = Field(default=0.6, ge=0.0, le=1.0)


def parse_research_result(data: object) -> ResearchResultEnvelopeModel | None:
    if not isinstance(data, dict) or data.get("kind") != "research_result":
        return None
    try:
        return ResearchResultEnvelopeModel.model_validate(data)
    except ValidationError:
        return None


def parse_analysis_result(data: object) -> AnalysisResultEnvelopeModel | None:
    if not isinstance(data, dict) or data.get("kind") != "analysis_result":
        return None
    try:
        return AnalysisResultEnvelopeModel.model_validate(data)
    except ValidationError:
        return None


def extract_result_text(data: dict[str, Any] | str | None) -> str:
    research_payload = parse_research_result(data)
    if research_payload is not None:
        return research_payload.summary
    analysis_payload = parse_analysis_result(data)
    if analysis_payload is not None:
        return analysis_payload.summary
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for field_name in ("summary", "answer", "content", "text"):
            field_value = data.get(field_name)
            if isinstance(field_value, str) and field_value.strip():
                return field_value.strip()
        return json.dumps(data, ensure_ascii=False)
    if data is None:
        return ""
    return str(data)


def format_sources_for_user(sources: list[ResearchSourceModel]) -> str:
    unique_lines: list[str] = []
    seen_urls: set[str] = set()
    for source in sources:
        if source.url in seen_urls:
            continue
        seen_urls.add(source.url)
        unique_lines.append(f"- {source.title}: {source.url} ({source.freshness})")
    return "\n".join(unique_lines)


def render_result_for_user(data: dict[str, Any] | str | None) -> str:
    research_payload = parse_research_result(data)
    if research_payload is None:
        analysis_payload = parse_analysis_result(data)
        if analysis_payload is None:
            return extract_result_text(data)
        details: list[str] = [analysis_payload.summary]
        if analysis_payload.data_points:
            points_preview = "; ".join(
                f"{point.subject} {point.metric}={point.value:g} {point.unit}" for point in analysis_payload.data_points[:3]
            )
            details.append("Data points: " + points_preview)
        if analysis_payload.signals:
            details.append("Tin hieu chinh: " + "; ".join(analysis_payload.signals[:4]))
        if analysis_payload.data_points:
            evidence_urls: list[str] = []
            for point in analysis_payload.data_points:
                if point.source not in evidence_urls:
                    evidence_urls.append(point.source)
                if len(evidence_urls) >= 3:
                    break
            if evidence_urls:
                details.append("Dan chung chinh: " + "; ".join(evidence_urls))
        if analysis_payload.limitations:
            details.append("Gioi han phan tich: " + "; ".join(analysis_payload.limitations[:3]))
        return "\n\n".join(details)

    source_block = format_sources_for_user(research_payload.sources)
    if not source_block:
        return research_payload.summary
    return f"{research_payload.summary}\n\nNguon tham khao:\n{source_block}"


def sanitize_text_for_plain_ui(text: str) -> str:
    sanitized = text.replace("\r\n", "\n")

    # Convert markdown links to plain text while preserving URL.
    sanitized = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1: \2", sanitized)

    # Remove markdown emphasis / inline code that the UI does not render.
    sanitized = sanitized.replace("**", "")
    sanitized = sanitized.replace("__", "")
    sanitized = sanitized.replace("`", "")

    # Remove duplicated source footer because frontend renders sources/sourceDetails separately.
    sanitized = re.split(r"\n\s*(?:Ngu[oồ]n tham kh[aả]o|Nguon tham khao)\s*:\s*\n", sanitized, maxsplit=1)[0]
    sanitized = re.sub(
        r"(?:\n|^)\s*(?:Ngu[oồ]n tham kh[aả]o|Nguon tham khao)\s*:\s*$",
        "",
        sanitized,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Normalize excessive blank lines after stripping markdown.
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    return sanitized.strip()


def format_dependency_outputs(dependency_outputs: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in dependency_outputs.items():
        research_payload = parse_research_result(value)
        if research_payload is not None:
            lines.append(f"- {key}: {research_payload.summary}")
            source_block = format_sources_for_user(research_payload.sources)
            if source_block:
                lines.append(f"  Sources:\n{source_block}")
            continue
        analysis_payload = parse_analysis_result(value)
        if analysis_payload is not None:
            lines.append(f"- {key}: {analysis_payload.summary}")
            if analysis_payload.data_points:
                lines.append(
                    "  DataPoints: "
                    + "; ".join(
                        f"{point.subject}:{point.metric}={point.value:g}{point.unit}" for point in analysis_payload.data_points[:3]
                    )
                )
            if analysis_payload.signals:
                lines.append(f"  Signals: {'; '.join(analysis_payload.signals[:4])}")
            continue
        lines.append(f"- {key}: {extract_result_text(value) or '- empty'}")
    return "\n".join(lines)


def collect_sources_from_results(results: dict[str, Any]) -> list[str]:
    ordered_sources: list[str] = []
    seen: set[str] = set()
    for value in results.values():
        research_payload = parse_research_result(value)
        if research_payload is None:
            continue
        for source in research_payload.sources:
            if source.url in seen:
                continue
            seen.add(source.url)
            ordered_sources.append(source.url)
    return ordered_sources


def collect_source_details_from_results(results: dict[str, Any]) -> list[dict[str, str]]:
    ordered_details: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in results.values():
        research_payload = parse_research_result(value)
        if research_payload is None:
            continue
        for source in research_payload.sources:
            if source.url in seen:
                continue
            seen.add(source.url)
            ordered_details.append(
                {
                    "title": source.title,
                    "url": source.url,
                    "freshness": source.freshness,
                }
            )
    return ordered_details


def collect_reasoning_evidence_from_results(results: dict[str, Any]) -> list[dict[str, str]]:
    ledger: list[dict[str, str]] = []
    seen: set[str] = set()

    for value in results.values():
        research_payload = parse_research_result(value)
        if research_payload is not None:
            for item in research_payload.evidence[:6]:
                key = f"research|{item.source}|{item.content[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                ledger.append(
                    {
                        "type": "research_evidence",
                        "claim": item.content[:280],
                        "source": item.source,
                        "evidence_item_id": item.evidence_item_id,
                    }
                )
                if len(ledger) >= 12:
                    return ledger

        analysis_payload = parse_analysis_result(value)
        if analysis_payload is not None:
            for point in analysis_payload.data_points[:8]:
                key = f"analysis|{point.source}|{point.subject}|{point.metric}|{round(point.value, 4)}"
                if key in seen:
                    continue
                seen.add(key)
                ledger.append(
                    {
                        "type": "analysis_datapoint",
                        "claim": f"{point.subject} {point.metric}={point.value:g} {point.unit}",
                        "source": point.source,
                        "claim_id": point.claim_id,
                        "evidence_item_id": f"datapoint_{point.claim_id}_{point.source.replace('://', '_')[:30]}",
                    }
                )
                if len(ledger) >= 12:
                    return ledger

    return ledger


def _tokenize_for_match(text: str) -> set[str]:
    return {token for token in re.split(r"[^\wÀ-ỹ]+", text.lower()) if len(token) >= 3}


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in re.findall(r"https?://[^\s)]+", text):
        candidate = match.strip().rstrip(".,;:!?)\"]'")
        if candidate and candidate not in urls:
            urls.append(candidate)
    return urls


def _extract_claim_candidates(answer: str) -> list[str]:
    lines = [line.strip(" -•\t") for line in answer.splitlines() if line.strip()]
    claims: list[str] = []
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("nguon tham khao") or lowered.startswith("dan chung da su dung"):
            continue
        if "http://" in lowered or "https://" in lowered:
            continue
        if len(line) < 20:
            continue
        claims.append(line)
    return claims[:10]


def compute_claim_evidence_coverage(answer: str, evidence_ledger: list[dict[str, str]]) -> dict[str, Any]:
    claims = _extract_claim_candidates(answer)
    ledger_sources = {
        str(item.get("source", "")).strip()
        for item in evidence_ledger
        if str(item.get("source", "")).strip()
    }
    if not claims:
        return {
            "claimCount": 0,
            "coveredClaimCount": 0,
            "coverageRatio": 1.0,
            "uncoveredClaims": [],
            "sourceAnchoredClaimCount": 0,
        }

    ledger_tokens: list[set[str]] = []
    for item in evidence_ledger:
        claim = str(item.get("claim", ""))
        source = str(item.get("source", ""))
        ledger_tokens.append(_tokenize_for_match(f"{claim} {source}"))

    covered = 0
    source_anchored = 0
    uncovered_claims: list[str] = []
    for claim in claims:
        claim_tokens = _tokenize_for_match(claim)
        if not claim_tokens:
            continue

        claim_urls = _extract_urls(claim)
        if claim_urls and any(url in ledger_sources for url in claim_urls):
            covered += 1
            source_anchored += 1
            continue

        matched = False
        for tokens in ledger_tokens:
            overlap = claim_tokens.intersection(tokens)
            if len(overlap) >= 2:
                matched = True
                break
        if matched:
            covered += 1
        else:
            uncovered_claims.append(claim)

    ratio = covered / max(len(claims), 1)
    return {
        "claimCount": len(claims),
        "coveredClaimCount": covered,
        "coverageRatio": round(ratio, 2),
        "uncoveredClaims": uncovered_claims[:4],
        "sourceAnchoredClaimCount": source_anchored,
    }


def compute_reasoning_conflict_score(results: dict[str, Any]) -> dict[str, Any]:
    max_conflict = 0
    quality_flags: list[str] = []
    low_quality_count = 0

    for value in results.values():
        analysis_payload = parse_analysis_result(value)
        if analysis_payload is None:
            continue

        max_conflict = max(max_conflict, int(analysis_payload.conflict_count))
        if analysis_payload.evidence_quality:
            quality_flags.append(analysis_payload.evidence_quality)
        if analysis_payload.evidence_quality == "low":
            low_quality_count += 1

    if max_conflict == 0 and low_quality_count == 0:
        return {
            "conflictScore": 0.0,
            "maxConflictCount": 0,
            "lowQualityAnalysisCount": 0,
        }

    conflict_component = min(max_conflict / 3.0, 1.0)
    quality_component = min(low_quality_count / 2.0, 1.0)
    conflict_score = round(min(conflict_component * 0.7 + quality_component * 0.3, 1.0), 2)
    return {
        "conflictScore": conflict_score,
        "maxConflictCount": max_conflict,
        "lowQualityAnalysisCount": low_quality_count,
        "qualityFlags": quality_flags[:6],
    }


def extract_claims_with_ids(answer: str) -> list[dict[str, str]]:
    """
    Extract claims from answer text with unique IDs for claim-to-evidence traceability.
    Returns list of {claim_id, text}.
    """
    claims_text = _extract_claim_candidates(answer)
    result: list[dict[str, str]] = []
    for idx, claim_text in enumerate(claims_text):
        claim_hash = str(hash(claim_text) & 0x7FFFFFFF)
        claim_id = f"claim_{idx}_{claim_hash}"
        result.append(
            {
                "claim_id": claim_id,
                "text": claim_text,
            }
        )
    return result


def create_claim_evidence_mapping(results: dict[str, Any], answer: str) -> dict[str, list[str]]:
    """
    Build exact claim-to-evidence mapping using UUID IDs.
    Maps claim_id → [evidence_item_id, ...] based on source URL matching and subject/metric matching.
    """
    mapping: dict[str, list[str]] = {}

    # Extract all data points and evidence items with their IDs
    analysis_data_points: list[tuple[str, AnalysisDataPointModel]] = []
    evidence_items_by_source: dict[str, list[tuple[str, EvidenceModel]]] = {}

    for value in results.values():
        analysis_payload = parse_analysis_result(value)
        if analysis_payload is not None:
            for point in analysis_payload.data_points:
                analysis_data_points.append((point.source, point))

        research_payload = parse_research_result(value)
        if research_payload is not None:
            for item in research_payload.evidence:
                if item.source not in evidence_items_by_source:
                    evidence_items_by_source[item.source] = []
                evidence_items_by_source[item.source].append((item.source, item))

    # Extract answer claims with unique IDs
    answer_claims = extract_claims_with_ids(answer)

    # Match each claim to evidence items
    for claim_info in answer_claims:
        claim_id = claim_info["claim_id"]
        claim_text = claim_info["text"]
        claim_tokens = _tokenize_for_match(claim_text)
        claim_urls = _extract_urls(claim_text)

        matched_evidence_ids: list[str] = []

        # Try direct URL match first
        for url in claim_urls:
            if url in evidence_items_by_source:
                for _, evidence in evidence_items_by_source[url]:
                    if evidence.evidence_item_id not in matched_evidence_ids:
                        matched_evidence_ids.append(evidence.evidence_item_id)

        # Try token-based matching if no direct URL match
        if not matched_evidence_ids and claim_tokens:
            for source, evidence_list in evidence_items_by_source.items():
                for _, evidence in evidence_list:
                    evidence_tokens = _tokenize_for_match(f"{evidence.content} {evidence.source}")
                    overlap = claim_tokens.intersection(evidence_tokens)
                    if len(overlap) >= 2:
                        if evidence.evidence_item_id not in matched_evidence_ids:
                            matched_evidence_ids.append(evidence.evidence_item_id)

        # Match with analysis data points
        for source, data_point in analysis_data_points:
            point_tokens = _tokenize_for_match(f"{data_point.subject} {data_point.metric}")
            if claim_tokens and point_tokens:
                overlap = claim_tokens.intersection(point_tokens)
                if len(overlap) >= 1:
                    synth_evidence_id = f"datapoint_{data_point.claim_id}_{data_point.source.replace('://', '_')[:30]}"
                    if synth_evidence_id not in matched_evidence_ids:
                        matched_evidence_ids.append(synth_evidence_id)

        if matched_evidence_ids:
            mapping[claim_id] = matched_evidence_ids

    return mapping


def detect_source_contradictions(results: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Detect contradictions between source pairs reporting the same metric.
    Compare data points with same (metric, subject) and detect value differences > threshold.
    Returns list of contradictions: [{metric, subject, source1, value1, source2, value2, percent_diff, confidence}, ...]
    """
    contradictions: list[dict[str, Any]] = []
    
    # Group data points by (metric, subject) tuple
    metric_groups: dict[tuple[str, str], list[AnalysisDataPointModel]] = {}
    
    for value in results.values():
        analysis_payload = parse_analysis_result(value)
        if analysis_payload is None or not analysis_payload.data_points:
            continue
        
        for point in analysis_payload.data_points:
            key = (point.metric.lower().strip(), point.subject.lower().strip())
            if key not in metric_groups:
                metric_groups[key] = []
            metric_groups[key].append(point)
    
    # Check each metric group for contradictions
    for (metric, subject), points in metric_groups.items():
        if len(points) < 2:
            continue  # Need at least 2 sources to detect contradiction
        
        # Compare each pair of sources
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                p1, p2 = points[i], points[j]
                
                # Skip if from same source
                if p1.source == p2.source:
                    continue
                
                # Calculate percentage difference
                if p1.value == 0 and p2.value == 0:
                    percent_diff = 0.0
                elif p1.value == 0 or p2.value == 0:
                    percent_diff = 100.0  # Max difference
                else:
                    percent_diff = abs(p1.value - p2.value) / max(abs(p1.value), abs(p2.value)) * 100
                
                # Flag as contradiction if difference > 15%
                if percent_diff > 15.0:
                    # Confidence is weighted by reliability of both sources
                    avg_reliability = (p1.reliability + p2.reliability) / 2
                    confidence = percent_diff / 100.0 * avg_reliability  # Cap by reliability
                    
                    contradictions.append({
                        "metric": metric,
                        "subject": subject,
                        "source_1": p1.source,
                        "value_1": round(p1.value, 4),
                        "source_2": p2.source,
                        "value_2": round(p2.value, 4),
                        "percent_diff": round(percent_diff, 1),
                        "confidence": round(min(confidence, 1.0), 2),
                        "unit": p1.unit,
                    })
    
    return contradictions[:10]  # Return top 10 most significant


def compute_pairwise_conflict_matrix(contradictions: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """
    Build NxN conflict matrix showing contradiction scores between source pairs.
    Returns dict[source_url, dict[source_url, conflict_score (0.0-1.0)]].
    Symmetric: matrix[A][B] == matrix[B][A]
    """
    matrix: dict[str, dict[str, float]] = {}
    
    for contradiction in contradictions:
        s1 = contradiction["source_1"]
        s2 = contradiction["source_2"]
        confidence = contradiction["confidence"]
        
        # Initialize sources in matrix if not present
        if s1 not in matrix:
            matrix[s1] = {}
        if s2 not in matrix:
            matrix[s2] = {}
        
        # Update symmetric entries (use max confidence if multiple contradictions)
        if s2 not in matrix[s1]:
            matrix[s1][s2] = confidence
        else:
            matrix[s1][s2] = max(matrix[s1][s2], confidence)
        
        if s1 not in matrix[s2]:
            matrix[s2][s1] = confidence
        else:
            matrix[s2][s1] = max(matrix[s2][s1], confidence)
    
    return matrix


def summarize_contradictions(contradictions: list[dict[str, Any]]) -> str:
    """
    Generate human-readable summary of source contradictions.
    Returns formatted string or empty string if no contradictions.
    """
    if not contradictions:
        return ""
    
    lines = ["Cac dau hieu xung dot giua nguon:"]
    for idx, contra in enumerate(contradictions[:4], start=1):
        metric = contra["metric"]
        subject = contra["subject"]
        val1 = contra["value_1"]
        val2 = contra["value_2"]
        unit = contra["unit"]
        diff = contra["percent_diff"]
        src1 = contra["source_1"].split("/")[-1] if "/" in contra["source_1"] else contra["source_1"][:30]
        src2 = contra["source_2"].split("/")[-1] if "/" in contra["source_2"] else contra["source_2"][:30]
        
        lines.append(
            f"- [{idx}] {subject} {metric}: "
            f"Nguon 1 = {val1}{unit} vs Nguon 2 = {val2}{unit} (chenh +{diff}%)"
        )
    
    if len(contradictions) > 4:
        lines.append(f"... va {len(contradictions) - 4} dau hieu xung dot khac")
    
    return "\n".join(lines)


# ============================================================================
# PHASE 8: DUAL-NICHE ADAPTIVE RETRIEVAL
# ============================================================================

def classify_source_niche(source_url: str, evidence_content: str, metric: str = "") -> Literal["quantitative", "qualitative"]:
    """
    Classify a source into quantitative or qualitative niche based on URL, content, and metric.
    
    Quantitative indicators: financial data, numbers, statistics, metrics, time-series
    Qualitative indicators: analysis, opinion, sentiment, narrative, insights
    """
    source_lower = source_url.lower()
    content_lower = evidence_content.lower()
    metric_lower = metric.lower()
    
    # Strong quantitative indicators
    quant_keywords = [
        "bloomberg", "reuters", "cnbc", "ft.com",  # Financial sources
        "stock", "nasdaq", "price", "dividend", "earnings",  # Financial metrics
        "gdp", "inflation", "unemployment", "yield",  # Economic metrics
        "revenue", "profit", "margin", "asset", "liability",  # Accounting
        "metric", "data", "number", "percent", "%", "billion", "million",  # Numerical
        "quarterly", "annual", "report", "statement", "analysis",  # Financial reports
    ]
    
    # Strong qualitative indicators
    qual_keywords = [
        "opinion", "analysis", "insight", "expert", "commentary",  # Opinion/analysis
        "forecast", "outlook", "sentiment", "trend", "pattern",  # Subjective assessment
        "interview", "roundtable", "perspective", "view", "stance",  # Expert opinion
        "risk", "opportunity", "concern", "positive", "negative",  # Sentiment
        "believe", "think", "expect", "may", "could", "likely",  # Speculative language
    ]
    
    # Count indicators
    quant_score = sum(1 for kw in quant_keywords if kw in source_lower or kw in content_lower)
    qual_score = sum(1 for kw in qual_keywords if kw in source_lower or kw in content_lower)
    
    # URL domain-based classification (higher priority)
    if any(domain in source_lower for domain in ["sec.gov", "treasury.gov", "bls.gov", "fred.stlouisfed.org"]):
        return "quantitative"
    if any(domain in source_lower for domain in ["seeking", "investor", "zacks", "morningstar"]):
        return "qualitative"
    
    # Metric-based classification
    if metric_lower and any(m in metric_lower for m in ["price", "volume", "growth", "margin", "ratio"]):
        return "quantitative"
    if metric_lower and any(m in metric_lower for m in ["sentiment", "outlook", "risk", "opportunity"]):
        return "qualitative"
    
    # Score-based decision
    if quant_score > qual_score:
        return "quantitative"
    elif qual_score > quant_score:
        return "qualitative"
    else:
        # Default: if URL contains "analysis" lean qualitative, else quantitative
        return "qualitative" if "analysis" in source_lower else "quantitative"


def categorize_evidence_by_niche(
    evidence_ledger: list[dict[str, str]], results: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """
    Separate evidence into quantitative and qualitative niches.
    Returns: {"quantitative": [...], "qualitative": [...]}
    """
    categorized: dict[str, list[dict[str, Any]]] = {
        "quantitative": [],
        "qualitative": [],
    }
    
    # Build a map of source -> metric for classification
    source_metrics: dict[str, list[str]] = {}
    for value in results.values():
        analysis_payload = parse_analysis_result(value)
        if analysis_payload is not None:
            for point in analysis_payload.data_points:
                if point.source not in source_metrics:
                    source_metrics[point.source] = []
                source_metrics[point.source].append(point.metric)
    
    # Classify each evidence item
    for item in evidence_ledger:
        source = str(item.get("source", ""))
        content = str(item.get("claim", ""))
        metric = source_metrics.get(source, [""])[0] if source in source_metrics else ""
        
        niche = classify_source_niche(source, content, metric)
        item_with_niche = {**item, "niche": niche}
        categorized[niche].append(item_with_niche)
    
    return categorized


def compute_niche_coverage(
    answer: str, evidence_by_niche: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """
    Compute coverage metrics broken down by niche.
    Returns: {
        "quantitative": {"claimCount": ..., "coveredCount": ...},
        "qualitative": {"claimCount": ..., "coveredCount": ...},
        "niche_balance": 0.0-1.0,  # How balanced are the niches (0=all one niche, 1=perfectly balanced)
    }
    """
    claims = _extract_claim_candidates(answer)
    
    quant_evidence = evidence_by_niche.get("quantitative", [])
    qual_evidence = evidence_by_niche.get("qualitative", [])
    
    # All evidence as one ledger for standard coverage computation
    all_evidence = quant_evidence + qual_evidence
    coverage = compute_claim_evidence_coverage(answer, [
        {k: v for k, v in item.items() if k != "niche"}
        for item in all_evidence
    ])
    
    # Estimate niche contribution by source count
    quant_sources = len(set(item.get("source") for item in quant_evidence))
    qual_sources = len(set(item.get("source") for item in qual_evidence))
    total_sources = quant_sources + qual_sources
    
    if total_sources == 0:
        niche_balance = 0.5
    else:
        quant_ratio = quant_sources / total_sources
        qual_ratio = qual_sources / total_sources
        # Balance = 1 - |0.5 - ratio| (perfectly balanced if both 0.5, worst if 0 or 1)
        niche_balance = 1.0 - abs(0.5 - quant_ratio)
    
    return {
        "quantitative": {
            "sourceCount": quant_sources,
            "evidenceCount": len(quant_evidence),
        },
        "qualitative": {
            "sourceCount": qual_sources,
            "evidenceCount": len(qual_evidence),
        },
        "niche_balance": round(niche_balance, 2),
        "total_coverage": coverage,
    }


def compute_adaptive_weights(
    answer: str, niche_counts: dict[str, int]
) -> dict[str, float]:
    """
    Compute adaptive weights for merging quantitative and qualitative results.
    Based on query type inference from answer/question keywords.
    
    Returns: {"quantitative": 0.0-1.0, "qualitative": 0.0-1.0}  (sum=1.0)
    """
    answer_lower = answer.lower()
    
    # Query type indicators
    quant_keywords = ["price", "number", "percent", "growth", "ratio", "metric", "data", "statistics"]
    qual_keywords = ["outlook", "sentiment", "opinion", "trend", "strategy", "risk", "opportunity"]
    
    quant_score = sum(1 for kw in quant_keywords if kw in answer_lower)
    qual_score = sum(1 for kw in qual_keywords if kw in answer_lower)
    
    total = quant_score + qual_score
    if total == 0:
        # No strong indicators: balance based on available evidence
        quant_count = niche_counts.get("quantitative", 0)
        qual_count = niche_counts.get("qualitative", 0)
        if quant_count + qual_count == 0:
            return {"quantitative": 0.5, "qualitative": 0.5}
        total_count = quant_count + qual_count
        return {
            "quantitative": round(quant_count / total_count, 2),
            "qualitative": round(qual_count / total_count, 2),
        }
    
    quant_weight = quant_score / total
    qual_weight = qual_score / total
    
    return {
        "quantitative": round(quant_weight, 2),
        "qualitative": round(qual_weight, 2),
    }


def merge_niche_results(
    quant_score: float,
    qual_score: float,
    weights: dict[str, float],
) -> float:
    """
    Weighted merge of quantitative and qualitative coverage scores.
    Returns merged score in [0, 1] range.
    
    Formula: merged = quant_score × weights["quantitative"] + qual_score × weights["qualitative"]
    """
    quant_weight = weights.get("quantitative", 0.5)
    qual_weight = weights.get("qualitative", 0.5)
    
    merged = quant_score * quant_weight + qual_score * qual_weight
    return round(min(merged, 1.0), 2)


def generate_niche_summary(niche_coverage: dict[str, Any]) -> str:
    """
    Generate a summary of dual-niche coverage breakdown.
    Returns formatted string for inclusion in response.
    """
    quant = niche_coverage["quantitative"]
    qual = niche_coverage["qualitative"]
    balance = niche_coverage["niche_balance"]

    balance_label = "balanced" if balance > 0.7 else "biased" if balance > 0.4 else "highly biased"
    
    lines = [
        f"Dual-niche analysis: {quant['sourceCount']} quantitative sources + {qual['sourceCount']} analytical sources",
        f"Data balance: {int(balance * 100)}% ({balance_label})",
    ]
    
    return " | ".join(lines)


def compute_claim_niche_breakdown(
    claim_mapping: dict[str, list[str]],
    evidence_by_niche: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """
    Compute niche coverage at claim level using claim->evidence mapping.
    Returns per-claim niche assignment and summary counts.
    """
    evidence_to_niche: dict[str, str] = {}
    for niche in ("quantitative", "qualitative"):
        for item in evidence_by_niche.get(niche, []):
            evidence_id = str(item.get("evidence_item_id", "")).strip()
            if evidence_id:
                evidence_to_niche[evidence_id] = niche

    claim_niche_map: dict[str, dict[str, Any]] = {}
    quant_claims = 0
    qual_claims = 0
    mixed_claims = 0

    for claim_id, evidence_ids in claim_mapping.items():
        quant_hits = 0
        qual_hits = 0
        for evidence_id in evidence_ids:
            niche = evidence_to_niche.get(evidence_id)
            if niche == "quantitative":
                quant_hits += 1
            elif niche == "qualitative":
                qual_hits += 1

        if quant_hits > 0 and qual_hits > 0:
            dominant = "mixed"
            mixed_claims += 1
        elif quant_hits > 0:
            dominant = "quantitative"
            quant_claims += 1
        elif qual_hits > 0:
            dominant = "qualitative"
            qual_claims += 1
        else:
            dominant = "unknown"

        claim_niche_map[claim_id] = {
            "quantitativeEvidenceCount": quant_hits,
            "qualitativeEvidenceCount": qual_hits,
            "dominantNiche": dominant,
        }

    total_claims = max(len(claim_mapping), 1)
    mixed_ratio = round(mixed_claims / total_claims, 2)
    return {
        "claimNicheMap": claim_niche_map,
        "quantitativeClaimCount": quant_claims,
        "qualitativeClaimCount": qual_claims,
        "mixedClaimCount": mixed_claims,
        "mixedClaimRatio": mixed_ratio,
    }


def detect_cross_niche_contradictions(
    contradictions: list[dict[str, Any]],
    evidence_by_niche: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """
    Detect contradictions where two conflicting sources belong to different niches.
    """
    source_to_niche: dict[str, str] = {}
    for niche in ("quantitative", "qualitative"):
        for item in evidence_by_niche.get(niche, []):
            source = str(item.get("source", "")).strip()
            if source and source not in source_to_niche:
                source_to_niche[source] = niche

    cross: list[dict[str, Any]] = []
    for contradiction in contradictions:
        source_1 = str(contradiction.get("source_1", ""))
        source_2 = str(contradiction.get("source_2", ""))
        niche_1 = source_to_niche.get(source_1, "unknown")
        niche_2 = source_to_niche.get(source_2, "unknown")
        if niche_1 == "unknown" or niche_2 == "unknown":
            continue
        if niche_1 == niche_2:
            continue

        cross.append(
            {
                **contradiction,
                "niche_1": niche_1,
                "niche_2": niche_2,
                "crossNiche": True,
            }
        )

    return cross[:8]
