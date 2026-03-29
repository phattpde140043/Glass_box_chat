from __future__ import annotations

import json
import re
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
