from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from .language_policy import build_response_language_instruction, normalize_language_name
from .planner import is_weather_text, needs_research_text
from .result_formatting import (
    AnalysisDataPointModel,
    AnalysisResultEnvelopeModel,
    EvidenceModel,
    ResearchResultEnvelopeModel,
    ResearchSourceModel,
    extract_result_text,
    format_dependency_outputs,
    format_sources_for_user,
    parse_analysis_result,
    parse_research_result,
)
from .runtime_resilience import classify_error
from .search_providers import SearchDocument, SearchProvider, SearchResultBatch, rank_documents_for_query
from .skill_core import SkillContext, SkillMetadata, SkillResult


class SupportsCallModel(Protocol):
    def _call_model(self, prompt: str) -> str: ...


class BaseLLMSkill:
    def __init__(self, model_source: SupportsCallModel | Callable[[str], str]) -> None:
        if callable(model_source):
            self._model_generate: Callable[[str], str] = model_source
        else:
            self._model_generate = model_source._call_model

    async def _generate(self, prompt: str) -> SkillResult:
        try:
            content = await asyncio.to_thread(self._model_generate, prompt)
            return SkillResult(success=True, data=content)
        except Exception as err:
            return SkillResult(success=False, error=str(err), metadata={"error_type": classify_error(str(err))})

    @staticmethod
    def _response_language(context: SkillContext) -> str:
        return normalize_language_name(context.response_language)

    def _with_language_policy(self, prompt: str, context: SkillContext) -> str:
        return (
            f"{build_response_language_instruction(self._response_language(context), explicit=context.explicit_response_language)}\n\n"
            f"{prompt}"
        )

    def _fallback_text(self, context: SkillContext, *, english: str, vietnamese: str | None = None) -> str:
        _ = context, vietnamese
        return english


class ResearchSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="research",
        description="Research current or external information using a search provider before answering.",
        examples=["today weather", "latest news", "current price", "information lookup", "research"],
        priority_weight=0.24,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def __init__(self, model_source: SupportsCallModel | Callable[[str], str], search_provider: SearchProvider) -> None:
        super().__init__(model_source)
        self._search_provider = search_provider

    _MOCK_HINTS = (
        "example.local",
        "mock-result",
        "demo",
        "simulation",
    )

    _SUBJECT_HINT_GROUPS = (
        ("cafe", "coffee", "arabica", "robusta"),
        ("pepper",),
        ("gold", "xau", "xauusd"),
        ("bitcoin", "btc", "ethereum", "eth", "crypto"),
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        return needs_research_text(str(input_data.get("description", "")))

    @classmethod
    def _is_mock_document(cls, document: SearchDocument) -> bool:
        haystack = f"{document.title} {document.snippet} {document.url} {document.provider}".lower()
        return document.provider == "mock" or any(token in haystack for token in cls._MOCK_HINTS)

    @classmethod
    def _extract_subject_hints(cls, task_description: str) -> tuple[str, ...]:
        lowered = task_description.lower()
        for hint_group in cls._SUBJECT_HINT_GROUPS:
            if any(token in lowered for token in hint_group):
                return hint_group
        return ()

    @classmethod
    def _filter_documents(cls, task_description: str, documents: list[SearchDocument]) -> tuple[list[SearchDocument], str | None]:
        non_mock_documents = [document for document in documents if not cls._is_mock_document(document)]
        if not non_mock_documents:
            return [], "mock_only"

        subject_hints = cls._extract_subject_hints(task_description)
        if not subject_hints:
            return rank_documents_for_query(task_description, non_mock_documents), None

        relevant_documents = [
            document
            for document in non_mock_documents
            if any(token in f"{document.title} {document.snippet} {document.url}".lower() for token in subject_hints)
        ]
        if relevant_documents:
            return rank_documents_for_query(task_description, relevant_documents), None
        return [], "insufficient_relevance"

    @staticmethod
    def _build_insufficient_evidence_result(
        reason: str,
        search_batch: SearchResultBatch,
        task_description: str,
        used_tool: str,
        raw_document_count: int,
    ) -> SkillResult:
        if reason == "mock_only":
            error = "insufficient_live_evidence"
            message = (
                "There is no reliable live evidence for this request. "
                "The system intentionally avoided using demo or mock sources."
            )
        else:
            error = "insufficient_relevant_evidence"
            message = (
                "The system collected results, but none of them were directly relevant enough to support the request."
            )

        return SkillResult(
            success=False,
            error=error,
            metadata={
                "provider": search_batch.provider,
                "source_count": 0,
                "retrieved_source_count": raw_document_count,
                "freshness": "n/a",
                "citation_count": 0,
                "citations": "none",
                "fallback_used": search_batch.fallback_used,
                "latency_ms": search_batch.latency_ms,
                "confidence": 0.0,
                "intent": search_batch.intent,
                "providers_tried": ",".join(search_batch.providers_tried or []),
                "cache_ttl_seconds": search_batch.cache_ttl_seconds,
                "used_tool": used_tool,
                "error_type": "permanent",
                "error_detail": f"{message} Task={task_description[:160]}",
            },
        )

    @staticmethod
    def _build_search_batch_from_tool_output(tool_name: str, tool_result: object) -> SearchResultBatch | None:
        data = getattr(tool_result, "data", {}) or {}
        confidence = float(getattr(tool_result, "confidence", 0.5) or 0.5)
        latency_ms = int(getattr(tool_result, "latency_ms", 0) or 0)
        source_url = str(getattr(tool_result, "source_url", "") or "")
        content = str(getattr(tool_result, "content", "") or "")

        documents: list[SearchDocument] = []

        for doc in data.get("documents", []):
            documents.append(
                SearchDocument(
                    title=str(doc.get("title", "Tool result")).strip()[:100],
                    snippet=str(doc.get("snippet", "")).strip()[:300],
                    url=str(doc.get("url", source_url)).strip()[:500],
                    freshness=str(doc.get("freshness", "live"))[:40],
                    published_at=doc.get("published_at"),
                    reliability=float(doc.get("reliability", 0.7) or 0.7),
                    provider=tool_name,
                )
            )

        for article in data.get("articles", []):
            documents.append(
                SearchDocument(
                    title=str(article.get("title", "Article")).strip()[:100],
                    snippet=str(article.get("snippet", "")).strip()[:300],
                    url=str(article.get("url", source_url)).strip()[:500],
                    freshness="live",
                    published_at=article.get("published_at"),
                    reliability=float(article.get("reliability", 0.75) or 0.75),
                    provider=str(article.get("source", tool_name)).strip()[:80],
                )
            )

        if not documents and data.get("title") and (data.get("snippet") or data.get("text")):
            snippet = str(data.get("snippet", data.get("text", ""))).strip()[:300]
            url = str(data.get("url", source_url)).strip()[:500]
            documents.append(
                SearchDocument(
                    title=str(data.get("title", "Tool result")).strip()[:100],
                    snippet=snippet,
                    url=url or "about:blank",
                    freshness=str(data.get("freshness", "live"))[:40],
                    published_at=data.get("published_at"),
                    reliability=0.72,
                    provider=tool_name,
                )
            )

        if not documents and data.get("expression") and data.get("result"):
            documents.append(
                SearchDocument(
                    title=f"Calculation: {str(data.get('expression', ''))[:80]}",
                    snippet=f"Result: {data.get('result')}",
                    url="tool://calculator",
                    freshness="live",
                    reliability=0.99,
                    provider=tool_name,
                )
            )

        market = data.get("market") if isinstance(data.get("market"), dict) else None
        if not documents and market is not None:
            symbol = str(market.get("symbol", "MARKET"))
            price = market.get("price")
            currency = str(market.get("currency", "USD"))
            ts = str(market.get("timestamp", "live"))
            source = str(market.get("source", tool_name))
            documents.append(
                SearchDocument(
                    title=f"{symbol} latest price",
                    snippet=f"{symbol} = {price} {currency} at {ts}",
                    url=str(getattr(tool_result, "source_url", "") or f"tool://{tool_name}"),
                    freshness="live",
                    published_at=ts,
                    reliability=0.92,
                    provider=source,
                )
            )

        if not documents and content:
            documents.append(
                SearchDocument(
                    title=f"Tool output from {tool_name}",
                    snippet=content[:300],
                    url=source_url or f"tool://{tool_name}",
                    freshness="live",
                    reliability=0.7,
                    provider=tool_name,
                )
            )

        if not documents:
            return None

        return SearchResultBatch(
            provider=tool_name,
            documents=documents,
            fallback_used=False,
            intent=f"tool_{tool_name}",
            confidence=confidence,
            latency_ms=latency_ms,
            providers_tried=[tool_name],
        )

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", "")).strip()
        started_at = time.perf_counter()
        selected_tool_name = str(getattr(context.selected_tool, "name", "") or "")
        strict_market_mode = selected_tool_name == "finance"

        # Try using selected tool if provided
        search_batch: SearchResultBatch | None = None
        _failed_tool_result: object | None = None  # capture for fully-orchestrated guard
        if context.selected_tool is not None:
            try:
                from .tools import ToolInput

                tool_input = ToolInput(query=task_description, limit=4)
                tool_result = await context.selected_tool.execute(tool_input)
                if tool_result.success:
                    search_batch = self._build_search_batch_from_tool_output(context.selected_tool.name, tool_result)
                elif strict_market_mode:
                    error_text = tool_result.error or "finance_data_unavailable"
                    return SkillResult(
                        success=False,
                        error=error_text,
                        metadata={
                            "provider": "finance",
                            "source_count": 0,
                            "freshness": "live",
                            "citation_count": 0,
                            "citations": "none",
                            "fallback_used": False,
                            "latency_ms": int((time.perf_counter() - started_at) * 1000),
                            "confidence": 0.0,
                            "intent": "market_price",
                            "providers_tried": "finance",
                            "cache_ttl_seconds": 0,
                            "used_tool": "finance",
                            "error_type": classify_error(error_text),
                        },
                    )
                else:
                    _failed_tool_result = tool_result
            except Exception:
                if strict_market_mode:
                    return SkillResult(
                        success=False,
                        error="finance_data_unavailable",
                        metadata={
                            "provider": "finance",
                            "source_count": 0,
                            "freshness": "live",
                            "citation_count": 0,
                            "citations": "none",
                            "fallback_used": False,
                            "latency_ms": int((time.perf_counter() - started_at) * 1000),
                            "confidence": 0.0,
                            "intent": "market_price",
                            "providers_tried": "finance",
                            "cache_ttl_seconds": 0,
                            "used_tool": "finance",
                            "error_type": "transient",
                        },
                    )

        # Fallback to search provider if tool didn't work or wasn't provided
        if search_batch is None:
            if strict_market_mode:
                return SkillResult(
                    success=False,
                    error="finance_data_unavailable",
                    metadata={
                        "provider": "finance",
                        "source_count": 0,
                        "freshness": "live",
                        "citation_count": 0,
                        "citations": "none",
                        "fallback_used": False,
                        "latency_ms": int((time.perf_counter() - started_at) * 1000),
                        "confidence": 0.0,
                        "intent": "market_price",
                        "providers_tried": "finance",
                        "cache_ttl_seconds": 0,
                        "used_tool": "finance",
                        "error_type": "transient",
                    },
                )
            # If the tool already ran its own full orchestration chain (e.g.
            # WeatherTool with an injected PolicyDrivenSearchProvider), do not
            # re-run the same provider chain here.  That would produce duplicate
            # trace entries and mix providers_tried from two separate runs.
            if _failed_tool_result is not None:
                _meta = getattr(_failed_tool_result, "metadata", {}) or {}
                if _meta.get("tool_fully_orchestrated"):
                    _error = str(getattr(_failed_tool_result, "error", "") or "tool_orchestration_failed")
                    return SkillResult(
                        success=False,
                        error=_error,
                        metadata={
                            **_meta,
                            "used_tool": selected_tool_name,
                            "latency_ms": int((time.perf_counter() - started_at) * 1000),
                            "error_type": classify_error(_error),
                        },
                    )
            search_batch = await self._search_provider.search(task_description, limit=4)

        raw_documents = list(search_batch.documents)
        documents, filter_reason = self._filter_documents(task_description, raw_documents)
        if filter_reason is not None:
            return self._build_insufficient_evidence_result(
                reason=filter_reason,
                search_batch=search_batch,
                task_description=task_description,
                used_tool=context.selected_tool.name if context.selected_tool is not None else "none",
                raw_document_count=len(raw_documents),
            )

        if not documents:
            return SkillResult(success=False, error="no_research_results", metadata={"error_type": "permanent"})

        evidence_text = "\n".join(
            f"- [{index + 1}] {document.title} | {document.freshness} | {document.url}\n  {document.snippet}"
            for index, document in enumerate(documents)
        )
        prompt = (
            "You are ResearchSkill. Answer only from the evidence below. "
            "If the evidence is weak or incomplete, say so explicitly.\n\n"
            f"Normalized prompt: {context.normalized_prompt}\n"
            f"Research task: {task_description}\n"
            f"Recent memory:\n{context.recent_memory or '- none'}\n"
            f"Evidence:\n{evidence_text}\n\n"
            "Requirement: write a short findings summary, state limits clearly, and do not invent any facts or sources beyond the evidence."
        )
        result = await self._generate(self._with_language_policy(prompt, context))
        if result.success:
            summary = extract_result_text(result.data).strip()
            sources = [
                ResearchSourceModel(
                    title=document.title,
                    snippet=document.snippet,
                    url=document.url,
                    freshness=document.freshness,
                    published_at=document.published_at,
                    reliability=document.reliability,
                    provider=document.provider,
                )
                for document in documents
            ]
            evidence = [
                EvidenceModel(
                    content=document.snippet,
                    source=document.url,
                    timestamp=document.published_at,
                    reliability=document.reliability,
                    provider=document.provider,
                )
                for document in documents
            ]
            result.data = ResearchResultEnvelopeModel(
                kind="research_result",
                summary=summary or self._fallback_text(
                    context,
                    english="There are no clear findings from the current evidence.",
                    vietnamese="Không có findings rõ ràng từ evidence hiện tại.",
                ),
                grounded=True,
                confidence=search_batch.confidence,
                citations=[source.url for source in sources],
                sources=sources,
                evidence=evidence,
            ).model_dump()
        metadata = {
            **(result.metadata or {}),
            "provider": search_batch.provider,
            "source_count": len(documents),
            "freshness": documents[0].freshness,
            "citation_count": len({document.url for document in documents}),
            "citations": ",".join(document.url for document in documents),
            "fallback_used": search_batch.fallback_used,
            "latency_ms": search_batch.latency_ms or int((time.perf_counter() - started_at) * 1000),
            "confidence": search_batch.confidence,
            "intent": search_batch.intent,
            "providers_tried": ",".join(search_batch.providers_tried or []),
            "cache_ttl_seconds": search_batch.cache_ttl_seconds,
            "used_tool": context.selected_tool.name if context.selected_tool is not None else "none",
        }
        result.metadata = metadata
        return result


class FinanceSkill:
    metadata = SkillMetadata(
        name="finance",
        description="Fetch structured live market data (gold/crypto) without research fallback.",
        examples=["gold price today", "gold price", "BTC price", "exchange rate"],
        priority_weight=0.28,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    _MARKET_HINTS = (
        "gold price",
        "xau",
        "xauusd",
        "crypto",
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "exchange rate",
        "forex",
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        tokens = {token for token in re.split(r"[^\w]+", text) if token}
        for hint in self._MARKET_HINTS:
            if " " in hint:
                if hint in text:
                    return True
                continue
            if hint in tokens:
                return True
        return False

    async def execute(self, context: SkillContext) -> SkillResult:
        from .tools import FinanceTool, ToolInput

        description = str(context.input.get("description", "")).strip()
        tool = context.selected_tool if getattr(context.selected_tool, "name", "") == "finance" else FinanceTool()

        try:
            tool_result = await tool.execute(ToolInput(query=description, limit=1))
        except Exception as err:
            graceful = (
                "Real-time market data is currently unavailable because the provider connection failed.\n\n"
                "You can try again in a few minutes or check:\n"
                "- https://www.kitco.com\n"
                "- https://www.sjc.com.vn"
            )
            return SkillResult(
                success=True,
                data={
                    "summary": graceful,
                    "content": graceful,
                    "market": {},
                    "source": None,
                },
                metadata={
                    "provider": "finance",
                    "source_count": 2,
                    "citation_count": 0,
                    "citations": "none",
                    "freshness": "live",
                    "fallback_used": True,
                    "confidence": 0.25,
                    "intent": "market_price",
                    "providers_tried": "finance",
                    "cache_ttl_seconds": 0,
                    "used_tool": "finance",
                    "error_type": "transient",
                    "error_detail": str(err),
                },
            )

        if not tool_result.success:
            error_text = tool_result.error or "finance_data_unavailable"
            provider = str((tool_result.metadata or {}).get("provider", "finance"))
            providers_tried = str((tool_result.metadata or {}).get("providers_tried", provider))
            source_hints = (tool_result.metadata or {}).get("source_hints")
            if not isinstance(source_hints, list) or not source_hints:
                source_hints = ["https://www.kitco.com", "https://www.sjc.com.vn"]
            source_count = int((tool_result.metadata or {}).get("source_count", 0) or 0)
            graceful = str(tool_result.content or "").strip() or "Real-time market data is currently unavailable. Please try again later."

            degraded_sources = [
                ResearchSourceModel(
                    title="Market data reference",
                    snippet="Fallback reference source while live providers are unavailable.",
                    url=url,
                    freshness="live",
                    reliability=0.55,
                    provider="finance_chain",
                )
                for url in source_hints
            ]
            degraded_payload = ResearchResultEnvelopeModel(
                kind="research_result",
                summary=graceful,
                grounded=True,
                confidence=max(float(tool_result.confidence or 0.0), 0.2),
                citations=[item.url for item in degraded_sources],
                sources=degraded_sources,
                evidence=[
                    EvidenceModel(
                        content=item.snippet,
                        source=item.url,
                        reliability=item.reliability,
                        provider=item.provider,
                    )
                    for item in degraded_sources
                ],
            ).model_dump()
            return SkillResult(
                success=True,
                data=degraded_payload,
                metadata={
                    "provider": provider,
                    "source_count": max(source_count, len(source_hints)),
                    "citation_count": len(source_hints),
                    "citations": ",".join(source_hints),
                    "freshness": "live",
                    "fallback_used": True,
                    "confidence": max(float(tool_result.confidence or 0.0), 0.2),
                    "intent": "market_price",
                    "used_tool": "finance",
                    "providers_tried": providers_tried,
                    "cache_ttl_seconds": 0,
                    "error_type": classify_error(error_text),
                    "error_detail": str((tool_result.metadata or {}).get("provider_errors", error_text)),
                },
            )

        tool_documents: list[dict[str, object]] = []
        if isinstance(tool_result.data, dict):
            docs_raw = tool_result.data.get("documents")
            if isinstance(docs_raw, list):
                tool_documents = [doc for doc in docs_raw if isinstance(doc, dict)]

        summary = tool_result.content.strip() or "Market price data is available."
        sources: list[ResearchSourceModel] = []
        for doc in tool_documents:
            url = str(doc.get("url", "")).strip()
            if not url:
                continue
            sources.append(
                ResearchSourceModel(
                    title=str(doc.get("title", "Market source")).strip()[:300],
                    snippet=str(doc.get("snippet", "Market data source")).strip()[:1200],
                    url=url,
                    freshness=str(doc.get("freshness", "live"))[:80],
                    published_at=str(doc.get("published_at", "")).strip() or None,
                    reliability=float(doc.get("reliability", 0.8) or 0.8),
                    provider=str(doc.get("provider", "finance"))[:80],
                )
            )

        if not sources and tool_result.source_url:
            sources.append(
                ResearchSourceModel(
                    title="Market source",
                    snippet="Market price provider.",
                    url=str(tool_result.source_url),
                    freshness="live",
                    reliability=0.8,
                    provider="finance",
                )
            )

        citations = [item.url for item in sources]
        confidence = float(tool_result.confidence or 0.0)
        if sources and confidence <= 0.0:
            confidence = 0.65

        payload = ResearchResultEnvelopeModel(
            kind="research_result",
            summary=summary,
            grounded=True,
            confidence=min(confidence, 1.0),
            citations=citations,
            sources=sources,
            evidence=[
                EvidenceModel(
                    content=item.snippet,
                    source=item.url,
                    timestamp=item.published_at,
                    reliability=item.reliability,
                    provider=item.provider,
                )
                for item in sources
            ],
        ).model_dump()

        return SkillResult(
            success=True,
            data=payload,
            metadata={
                "provider": str((tool_result.metadata or {}).get("provider", "finance")),
                "source_count": int((tool_result.metadata or {}).get("source_count", 1 if tool_result.source_url else 0) or 0),
                "citation_count": len(citations),
                "citations": ",".join(citations) if citations else "none",
                "freshness": "live",
                "fallback_used": bool((tool_result.metadata or {}).get("fallback_used", False)),
                "confidence": payload.get("confidence", float(tool_result.confidence or 0.9)),
                "intent": "market_price",
                "providers_tried": str((tool_result.metadata or {}).get("providers_tried", (tool_result.metadata or {}).get("provider", "finance"))),
                "cache_ttl_seconds": int((tool_result.metadata or {}).get("cache_ttl_seconds", 20) or 20),
                "used_tool": "finance",
                "error_type": "none",
                "error_detail": str((tool_result.metadata or {}).get("provider_errors", "none")),
            },
        )


class AnalysisSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="analysis",
        description="Analyze multi-source research evidence into trend, drivers, and risk-aware outlook.",
        examples=["phan tich xu huong", "market analysis", "trend outlook", "nhan dinh thi truong"],
        priority_weight=0.22,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    _ANALYSIS_HINTS = (
        "phân tích",
        "phan tich",
        "nhận định",
        "nhan dinh",
        "xu hướng",
        "xu huong",
        "outlook",
        "trend",
        "assessment",
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        return any(token in text for token in self._ANALYSIS_HINTS)

    @staticmethod
    def _derive_outlook(signals: list[str]) -> str:
        lowered = " ".join(signals).lower()
        if any(token in lowered for token in ("tang", "uptrend", "thieu cung", "tight supply", "support")):
            return "bullish"
        if any(token in lowered for token in ("giam", "downtrend", "du cung", "weak demand", "pressure")):
            return "bearish"
        return "neutral"

    @staticmethod
    def _ensure_structured_reasoning_text(
        summary: str,
        signals: list[str],
        limitations: list[str],
        evidence_urls: list[str],
    ) -> str:
        lowered = summary.lower()
        has_conclusion = "ket luan" in lowered
        has_reasoning = "lap luan" in lowered
        has_evidence = "dan chung" in lowered
        has_limits = "gioi han" in lowered

        if has_conclusion and has_reasoning and has_evidence and has_limits:
            return summary

        conclusion = summary.strip()[:500] or "Chua the ket luan chac chan do bo du lieu con han che."
        reasoning = "; ".join(signals[:4]) if signals else "Can them tin hieu doc lap de cung co lap luan."
        evidence = "; ".join(evidence_urls[:4]) if evidence_urls else "Chua co URL dan chung ro rang."
        limits = "; ".join(limitations[:3]) if limitations else "Do phu data con han che."
        return (
            f"Ket luan: {conclusion}\n"
            f"Lap luan: {reasoning}\n"
            f"Dan chung da dung: {evidence}\n"
            f"Gioi han/gia dinh: {limits}"
        )

    @staticmethod
    def _safe_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_first_numeric(cls, text: str) -> float | None:
        candidates = re.findall(r"\b(\d{1,6}(?:[.,]\d{1,4})?)\b", text)
        for candidate in candidates:
            number = cls._safe_float(candidate.replace(",", "."))
            if number is None:
                continue
            if 0.0 <= number <= 1_000_000.0:
                return number
        return None

    @classmethod
    def _normalize_data_points(
        cls,
        *,
        dependency_outputs: dict[str, object],
        research_payloads: list[ResearchResultEnvelopeModel],
        task_description: str,
    ) -> list[AnalysisDataPointModel]:
        points: list[AnalysisDataPointModel] = []

        # Prefer explicit structured market payload when available.
        for payload in dependency_outputs.values():
            if not isinstance(payload, dict):
                continue
            market = payload.get("market") if isinstance(payload.get("market"), dict) else None
            if market is None:
                continue
            price = cls._safe_float(market.get("price"))
            if price is None:
                continue
            points.append(
                AnalysisDataPointModel(
                    metric="price",
                    value=price,
                    unit=str(market.get("currency", "USD")),
                    subject=str(market.get("symbol", market.get("asset", "market"))),
                    timestamp=str(market.get("timestamp", "")) or None,
                    source=str(market.get("source", "tool://finance")),
                    reliability=0.9,
                )
            )

        # Fallback: extract coarse numeric signals from research snippets.
        if not points:
            for payload in research_payloads:
                for source in payload.sources:
                    numeric = cls._extract_first_numeric(f"{source.title} {source.snippet}")
                    if numeric is None:
                        continue
                    points.append(
                        AnalysisDataPointModel(
                            metric="observed_value",
                            value=numeric,
                            unit="n/a",
                            subject=task_description[:120] or "market",
                            timestamp=source.published_at,
                            source=source.url,
                            reliability=source.reliability,
                        )
                    )
                    if len(points) >= 12:
                        break
                if len(points) >= 12:
                    break

        # Deduplicate by (metric, subject, source, rounded value).
        dedup: list[AnalysisDataPointModel] = []
        seen: set[str] = set()
        for item in points:
            key = f"{item.metric}|{item.subject}|{item.source}|{round(item.value, 4)}"
            if key in seen:
                continue
            seen.add(key)
            dedup.append(item)
            if len(dedup) >= 12:
                break
        return dedup

    @staticmethod
    def _detect_data_conflicts(data_points: list[AnalysisDataPointModel]) -> int:
        buckets: dict[tuple[str, str], list[float]] = {}
        for point in data_points:
            key = (point.subject.lower(), point.metric.lower())
            buckets.setdefault(key, []).append(point.value)

        conflicts = 0
        for values in buckets.values():
            if len(values) < 2:
                continue
            low = min(values)
            high = max(values)
            baseline = max(abs(low), 1.0)
            spread_ratio = abs(high - low) / baseline
            if spread_ratio >= 0.06:
                conflicts += 1
        return conflicts

    @staticmethod
    def _rate_evidence_quality(*, avg_reliability: float, source_diversity: int, data_coverage: float, conflict_count: int) -> str:
        score = avg_reliability * 0.45 + min(source_diversity / 4.0, 1.0) * 0.25 + data_coverage * 0.2 - min(conflict_count * 0.12, 0.24)
        if score >= 0.72:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"

    @classmethod
    def _compute_confidence(
        cls,
        *,
        research_payloads: list[ResearchResultEnvelopeModel],
        data_points: list[AnalysisDataPointModel],
        conflict_count: int,
    ) -> tuple[float, float, str]:
        avg_research_conf = sum(payload.confidence for payload in research_payloads) / max(len(research_payloads), 1)
        data_coverage = min(len(data_points) / 6.0, 1.0)
        avg_reliability = (
            sum(point.reliability for point in data_points) / len(data_points)
            if data_points
            else 0.45
        )
        source_diversity = len({point.source for point in data_points})
        quality = cls._rate_evidence_quality(
            avg_reliability=avg_reliability,
            source_diversity=source_diversity,
            data_coverage=data_coverage,
            conflict_count=conflict_count,
        )

        confidence = (
            avg_research_conf * 0.5
            + avg_reliability * 0.2
            + min(source_diversity / 5.0, 1.0) * 0.15
            + data_coverage * 0.15
            - min(conflict_count * 0.1, 0.3)
        )
        return round(max(0.05, min(confidence, 0.98)), 2), round(data_coverage, 2), quality

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", "")).strip() or context.normalized_prompt
        research_payloads = [
            payload for payload in (parse_research_result(value) for value in context.dependency_outputs.values()) if payload is not None
        ]
        if not research_payloads:
            degraded_prompt = (
                "You are AnalysisSkill in degraded mode. There is no reliable live research evidence. "
                "Provide a short general assessment using baseline knowledge only, do not overclaim, "
                "and clearly state that independent verification is still needed.\n\n"
                f"Normalized prompt: {context.normalized_prompt}\n"
                f"Analysis task: {task_description}"
            )
            degraded = await self._generate(self._with_language_policy(degraded_prompt, context))
            if not degraded.success:
                return degraded

            degraded_summary = extract_result_text(degraded.data).strip() or self._fallback_text(
                context,
                english="There is not enough live evidence, so this is only a temporary general assessment.",
                vietnamese="There is not enough live evidence, so this is only a temporary general assessment.",
            )
            degraded_summary = self._fallback_text(
                context,
                english=(
                    "Disclaimer: there is not enough reliable live evidence, so the response below is based only on general knowledge. "
                    "Please verify it before using it for other purposes.\n\n"
                ),
                vietnamese=(
                    "Disclaimer: there is not enough reliable live evidence, so the response below is based only on general knowledge. "
                    "Please verify it before using it for other purposes.\n\n"
                ),
            ) + degraded_summary
            payload = AnalysisResultEnvelopeModel(
                kind="analysis_result",
                summary=degraded_summary,
                confidence=0.2,
                signals=["No live evidence available; using baseline prior knowledge"],
                assumptions=["Market condition may have changed since model knowledge cutoff"],
                limitations=["No validated external evidence was retrieved for this run"],
                outlook="neutral",
                data_points=[],
                data_coverage=0.0,
                conflict_count=0,
                evidence_quality="low",
            ).model_dump()
            return SkillResult(
                success=True,
                data=payload,
                metadata={
                    "provider": "analysis",
                    "source_count": 0,
                    "citation_count": 0,
                    "citations": "none",
                    "freshness": "n/a",
                    "fallback_used": True,
                    "confidence": 0.2,
                    "intent": "analysis_degraded",
                    "providers_tried": "none",
                    "cache_ttl_seconds": 0,
                    "used_tool": "none",
                    "data_points_count": 0,
                    "data_coverage": 0.0,
                    "conflict_count": 0,
                    "evidence_quality": "low",
                },
            )

        evidence_lines: list[str] = []
        for idx, payload in enumerate(research_payloads, start=1):
            evidence_lines.append(f"[{idx}] {payload.summary}")
            for source in payload.sources[:3]:
                evidence_lines.append(f"- {source.title} | {source.url} | {source.freshness}")
        evidence_block = "\n".join(evidence_lines)

        prompt = (
            "You are AnalysisSkill. Analyze the trend from the existing research evidence only. "
            "Do not add facts beyond the evidence. Keep the answer concise and logically structured.\n\n"
            f"Normalized prompt: {context.normalized_prompt}\n"
            f"Analysis task: {task_description}\n"
            f"Recent memory:\n{context.recent_memory or '- none'}\n"
            f"Evidence summary:\n{evidence_block}\n\n"
            "Return plain text with exactly four sections:\n"
            "1) Trend conclusion\n"
            "2) Main reasoning\n"
            "3) Evidence used (each point must include a source URL when available)\n"
            "4) Limits, assumptions, and confidence"
        )
        result = await self._generate(self._with_language_policy(prompt, context))
        if not result.success:
            return result

        summary = extract_result_text(result.data).strip() or "There is not enough information to reach a confident trend conclusion."
        signals: list[str] = []
        for payload in research_payloads:
            snippet = payload.summary.strip()
            if snippet and snippet not in signals:
                signals.append(snippet[:180])
            if len(signals) >= 4:
                break

        assumptions = [
            "Gia dinh du lieu nguon van phan anh dung boi canh hien tai.",
            "Khong co su kien dot bien ngoai evidence da thu thap.",
        ]
        limitations = [
            "Khong co du lieu giao dich vi mo day du theo thoi gian thuc.",
            "Mot so nguon co do tre cap nhat va pham vi khu vuc han che.",
        ]
        data_points = self._normalize_data_points(
            dependency_outputs=context.dependency_outputs,
            research_payloads=research_payloads,
            task_description=task_description,
        )
        conflict_count = self._detect_data_conflicts(data_points)
        confidence, data_coverage, evidence_quality = self._compute_confidence(
            research_payloads=research_payloads,
            data_points=data_points,
            conflict_count=conflict_count,
        )

        if conflict_count > 0:
            limitations = [
                f"Phat hien {conflict_count} nhom du lieu co chenh lech dang ke giua cac nguon.",
                *limitations,
            ]

        if data_points:
            limitations = [
                "Data points duoc trich xuat tu evidence va co the khac nhau theo cach bao cao cua tung nguon.",
                *limitations,
            ]

        if confidence < 0.45 or evidence_quality == "low":
            summary = (
                "Do tin cay cua bo evidence hien tai con han che, can them du lieu doc lap truoc khi dua ra nhan dinh manh.\n"
                f"Tom tat tam thoi: {summary}"
            )
            assumptions = [
                "Ket luan duoi day chi la nhan dinh tam thoi do do phu du lieu chua cao.",
                *assumptions,
            ]

        evidence_urls = []
        for payload in research_payloads:
            for source in payload.sources:
                if source.url not in evidence_urls:
                    evidence_urls.append(source.url)
                if len(evidence_urls) >= 6:
                    break
            if len(evidence_urls) >= 6:
                break
        summary = self._ensure_structured_reasoning_text(summary, signals, limitations, evidence_urls)

        payload = AnalysisResultEnvelopeModel(
            kind="analysis_result",
            summary=summary,
            confidence=confidence,
            signals=signals,
            assumptions=assumptions,
            limitations=limitations,
            outlook=self._derive_outlook(signals),
            data_points=data_points,
            data_coverage=data_coverage,
            conflict_count=conflict_count,
            evidence_quality=evidence_quality,
        ).model_dump()

        return SkillResult(
            success=True,
            data=payload,
            metadata={
                "provider": "analysis",
                "source_count": len(research_payloads),
                "citation_count": 0,
                "citations": "none",
                "freshness": "recent",
                "fallback_used": confidence < 0.45,
                "confidence": confidence,
                "intent": "analysis",
                "providers_tried": "dependency_outputs",
                "cache_ttl_seconds": 0,
                "used_tool": "none",
                "data_points_count": len(data_points),
                "data_coverage": data_coverage,
                "conflict_count": conflict_count,
                "evidence_quality": evidence_quality,
            },
        )


class GeneralAnswerSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="general_answer",
        description="General purpose question answering and explanation skill in English.",
        examples=["explain", "why", "how it works", "concept"],
        priority_weight=0.05,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        _ = input_data
        return True

    @staticmethod
    def _infer_conversation_mode(text: str) -> str:
        lowered = text.lower().strip()
        greeting_hints = (
            "hello",
            "hi",
            "hey",
        )
        request_hints = (
            "please",
            "can you",
            "could you",
        )

        if any(token in lowered for token in greeting_hints) and len(lowered.split()) <= 6:
            return "greeting"
        if "?" in text or any(token in lowered for token in request_hints):
            return "question_or_request"
        return "statement_or_context"

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", ""))
        conversation_mode = self._infer_conversation_mode(task_description or context.normalized_prompt)
        prompt = (
            "You are GeneralAnswerSkill. Reply briefly and naturally in English while following the current conversational context.\n"
            "Rules:\n"
            "- If this is a greeting: reply warmly, briefly, and do not repeat the user's wording verbatim.\n"
            "- If this is a statement or shared context: do not simply echo the user. Acknowledge the information, continue the conversation naturally, and when useful ask one follow-up question or offer the next helpful step.\n"
            "- If this is a question or request: answer directly and clearly without rambling.\n"
            "- Do not invent facts beyond the prompt or memory.\n"
            "- Avoid robotic openers such as 'You said that...' or copying the user's sentence back.\n\n"
            f"Conversation mode: {conversation_mode}\n"
            f"Normalized prompt: {context.normalized_prompt}\n"
            f"Recent memory:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}"
        )
        return await self._generate(self._with_language_policy(prompt, context))


class PlanningSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="planning",
        description="Create checklist and implementation plans with prioritized steps.",
        examples=["kế hoạch", "checklist", "plan", "lộ trình", "step by step"],
        priority_weight=0.15,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        return any(token in text for token in ("kế hoạch", "checklist", "plan", "lộ trình", "bước"))

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", ""))
        prompt = (
            "Bạn là PlanningSkill. Tạo checklist có thứ tự ưu tiên, rõ ràng, súc tích bằng ngôn ngữ phản hồi được yêu cầu.\n\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}"
        )
        return await self._generate(self._with_language_policy(prompt, context))


class CompareSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="compare",
        description="Compare two or more technologies, options, or approaches with trade-offs.",
        examples=["so sánh", "compare", "khác nhau", "ưu nhược điểm"],
        priority_weight=0.18,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        return any(token in text for token in ("compare", "difference", "trade-off", "pros and cons"))

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", ""))
        deps_text = format_dependency_outputs(context.dependency_outputs)
        prompt = (
            "You are CompareSkill. Compare the options clearly with explicit criteria and concise trade-offs.\n\n"
            f"Normalized prompt: {context.normalized_prompt}\n"
            f"Recent memory:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}\n"
            f"Dependency outputs:\n{deps_text or '- none'}"
        )
        return await self._generate(self._with_language_policy(prompt, context))


class CodeExampleSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="code_example",
        description="Generate minimal, correct code examples or snippets based on context.",
        examples=["code example", "snippet", "sample code", "minimal example"],
        priority_weight=0.16,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        return any(token in text for token in ("code", "snippet", "sample", "example"))

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", ""))
        deps_text = format_dependency_outputs(context.dependency_outputs)
        prompt = (
            "You are CodeExampleSkill. Create a short, correct, easy-to-understand code example. Add a brief explanation after the code only when needed.\n\n"
            f"Normalized prompt: {context.normalized_prompt}\n"
            f"Recent memory:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}\n"
            f"Dependency outputs:\n{deps_text or '- none'}"
        )
        return await self._generate(self._with_language_policy(prompt, context))


class SynthesizerSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="synthesizer",
        description="Merge outputs from previous tasks into one coherent final answer.",
        examples=["tổng hợp", "merge outputs", "final answer", "synthesis"],
        priority_weight=0.2,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    _LLM_EXTRACTION_TIMEOUT_SECONDS = 3.5
    _LLM_EXTRACTION_CB_THRESHOLD = 3
    _LLM_EXTRACTION_CB_COOLDOWN_SECONDS = 90.0
    _LLM_EXTRACTION_FAILURE_STREAK = 0
    _LLM_EXTRACTION_BLOCK_UNTIL = 0.0

    def can_handle(self, input_data: dict[str, object]) -> bool:
        _ = input_data
        return True

    @staticmethod
    def _is_insufficient_summary(text: str) -> bool:
        """
        Enhanced check for insufficient research summary.
        
        Detects:
        - Explicit insufficiency markers (not found, limited results, etc.)
        - Content too short (less than 15 words)
        - Low semantic density (too many filler words)
        - Outdated data (if markers present)
        
        Confidence penalty formula:
        - Base penalty: 0.25 (for 1 weak summary)
        - Per additional weak: +0.12
        - Max penalty: 0.65
        """
        if not text or not isinstance(text, str):
            return True
        
        lowered = text.lower()
        stripped = text.strip()
        
        # Check 1: Explicit insufficiency markers
        insufficiency_markers = (
            "khong du",
            "không đủ",
            "chua co du",
            "chưa có đủ",
            "insufficient",
            "not enough",
            "no enough data",
            "lacking data",
            "khong co du lieu",
            "không có dữ liệu",
            "khong tim thay",
            "không tìm thấy",
            "not found",
            "no results",
            "no results found",
            "limited results",
            "gioi han",
            "giới hạn",
            "tieu du",
            "tiếu đủ",
            "chi tinh",
            "chỉ tính",
            "briefly",
            "briefly cover",
        )
        
        if any(marker in lowered for marker in insufficiency_markers):
            return True
        
        # Check 2: Content too short (minimum 15 words)
        word_count = len(stripped.split())
        if word_count < 15:
            return True
        
        # Check 3: Semantic density - too many filler words (>40% filler)
        filler_words = {
            "the", "a", "an", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "could",
            "and", "or", "but", "at", "in", "on", "to",
            "for", "of", "with", "by", "from", "as",
            "la", "le", "de", "da", "va", "se",  # French
            "của", "và", "là", "được", "có", "trong", "ở", "tại",  # Vietnamese
        }
        
        words = stripped.lower().split()
        filler_count = sum(1 for w in words if w.strip('.,!?;:') in filler_words)
        filler_ratio = filler_count / max(word_count, 1)
        
        if filler_ratio > 0.5:  # More than 50% filler words
            return True
        
        # Check 4: Vague placeholder text patterns
        vague_patterns = [
            r"^(more|additional|further|other)\s+(information|details|data)",
            r"(coming soon|stay tuned|watch for|check back)",
            r"(not\s+(yet\s+)?available|unavailable|pending)",
            r"^(to\s+be\s+(determined|announced|confirmed))",
            r"(as\s+of|currently|presently)\s+(no\s+data|no\s+results|unknown)",
        ]
        
        for pattern in vague_patterns:
            if re.search(pattern, lowered):
                return True
        
        # Check 5: Extremely generic summary (< 8 unique meaningful words)
        meaningful_words = [w.strip('.,!?;:') for w in words 
                           if len(w) > 3 and w.strip('.,!?;:') not in filler_words]
        unique_meaningful = len(set(meaningful_words))
        
        if unique_meaningful < 8:
            return True
        
        # If it passes all checks, consider it sufficient
        return False

    _LOCAL_CANDIDATE_STOPWORDS = {
        "the",
        "this",
        "that",
        "best",
        "top",
        "tokyo",
        "milan",
        "hanoi",
        "danang",
        "da nang",
        "restaurant",
        "restaurants",
        "hotel",
        "hotels",
        "review",
        "reviews",
        "guide",
        "travel",
    }
    _GENERIC_CANDIDATE_PREFIXES = (
        "search",
        "best ",
        "top ",
        "guide",
        "review",
        "reviews",
        "article",
        "list of",
        "things to do",
    )

    @classmethod
    def _normalize_candidate_name(cls, raw: str) -> str:
        value = re.sub(r"\s+", " ", raw).strip(" \t\r\n,.;:!?\"'`()[]{}")
        value = re.sub(r"^[\-–—•*]+\s*", "", value)
        return value

    @classmethod
    def _looks_like_place_candidate(cls, raw: str) -> bool:
        candidate = cls._normalize_candidate_name(raw)
        if len(candidate) < 2 or len(candidate) > 80:
            return False
        lowered = candidate.lower()
        if lowered in cls._LOCAL_CANDIDATE_STOPWORDS:
            return False
        if any(lowered.startswith(prefix) for prefix in cls._GENERIC_CANDIDATE_PREFIXES):
            return False
        if lowered.isdigit():
            return False
        token_count = len(candidate.split())
        if token_count > 6:
            return False
        if token_count == 1 and candidate[:1].islower():
            return False
        return True

    @classmethod
    def _build_grounded_text_blocks(cls, local_payload: ResearchResultEnvelopeModel) -> list[str]:
        blocks: list[str] = []
        for idx, source in enumerate(local_payload.sources[:6], start=1):
            snippet = source.snippet.strip().replace("\n", " ")
            if len(snippet) > 420:
                snippet = snippet[:420].rstrip() + "..."
            if snippet:
                blocks.append(f"[{idx}] Snippet: {snippet}")

        for idx, evidence in enumerate(local_payload.evidence[:8], start=1):
            content = evidence.content.strip().replace("\n", " ")
            if len(content) > 240:
                content = content[:240].rstrip() + "..."
            if content:
                blocks.append(f"[E{idx}] Evidence: {content}")
        return blocks

    @classmethod
    def _find_best_evidence_span(cls, candidate: str, local_payload: ResearchResultEnvelopeModel) -> str:
        lowered_candidate = candidate.lower()
        best_span = ""
        best_score = -1

        for source in local_payload.sources:
            text = source.snippet.strip()
            if lowered_candidate not in text.lower():
                continue
            score = cls._mentions_in_text(candidate, text)
            if score > best_score:
                best_score = score
                best_span = text[:220]

        for evidence in local_payload.evidence:
            text = evidence.content.strip()
            if lowered_candidate not in text.lower():
                continue
            score = cls._mentions_in_text(candidate, text) + 1
            if score > best_score:
                best_score = score
                best_span = text[:220]

        return best_span

    @classmethod
    def _extract_candidates_from_text(cls, text: str) -> list[str]:
        candidates: list[str] = []

        for pattern in (r'"([^"\n]{2,80})"', r"'([^'\n]{2,80})'"):
            for match in re.finditer(pattern, text):
                candidate = cls._normalize_candidate_name(match.group(1))
                if cls._looks_like_place_candidate(candidate):
                    candidates.append(candidate)

        for match in re.finditer(r"\b([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,4})\b", text):
            candidate = cls._normalize_candidate_name(match.group(1))
            if cls._looks_like_place_candidate(candidate):
                candidates.append(candidate)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    @classmethod
    def _extract_fallback_places_from_local_search(cls, local_raw: object) -> list[str]:
        payload = parse_research_result(local_raw)
        if payload is None:
            return []

        candidates: list[str] = []
        for source in payload.sources:
            if cls._looks_like_place_candidate(source.title):
                candidates.append(cls._normalize_candidate_name(source.title))
            candidates.extend(cls._extract_candidates_from_text(source.snippet))

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
            if len(deduped) >= 8:
                break
        return deduped

    @classmethod
    def _extract_grounded_fallback_places(cls, local_payload: ResearchResultEnvelopeModel) -> list[str]:
        candidates: list[str] = []
        for block in cls._build_grounded_text_blocks(local_payload):
            _, _, content = block.partition(":")
            candidates.extend(cls._extract_candidates_from_text(content.strip()))

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
            if len(deduped) >= 8:
                break
        return deduped

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
        text = raw_text.strip()
        if not text:
            return None

        candidates = [text]
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidates.append(text[first_brace:last_brace + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None

    @classmethod
    def _mentions_in_text(cls, candidate: str, haystack: str) -> int:
        pattern = re.compile(rf"\b{re.escape(candidate.lower())}\b")
        return len(pattern.findall(haystack.lower()))

    @classmethod
    def _record_llm_extraction_success(cls) -> None:
        cls._LLM_EXTRACTION_FAILURE_STREAK = 0
        cls._LLM_EXTRACTION_BLOCK_UNTIL = 0.0

    @classmethod
    def _record_llm_extraction_failure(cls) -> None:
        cls._LLM_EXTRACTION_FAILURE_STREAK += 1
        if cls._LLM_EXTRACTION_FAILURE_STREAK >= cls._LLM_EXTRACTION_CB_THRESHOLD:
            cls._LLM_EXTRACTION_BLOCK_UNTIL = time.monotonic() + cls._LLM_EXTRACTION_CB_COOLDOWN_SECONDS

    async def _generate_with_timeout(self, prompt: str, timeout_seconds: float) -> SkillResult:
        try:
            return await asyncio.wait_for(self._generate(prompt), timeout=timeout_seconds)
        except TimeoutError:
            return SkillResult(
                success=False,
                error="llm_extraction_timeout",
                metadata={"error_type": "transient"},
            )

    @staticmethod
    def _extract_entities_list(parsed: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(parsed, dict):
            return []
        entities = parsed.get("entities")
        if not isinstance(entities, list):
            return []
        return [item for item in entities if isinstance(item, dict)]

    async def _extract_candidates_with_llm(
        self,
        local_payload: ResearchResultEnvelopeModel | None,
    ) -> tuple[list[str], bool, int, bool, str]:
        if local_payload is None or not local_payload.sources:
            return [], False, 0, False, "no_research_payload"

        if time.monotonic() < self._LLM_EXTRACTION_BLOCK_UNTIL:
            return [], False, 0, True, "circuit_open"

        source_chunks = self._build_grounded_text_blocks(local_payload)

        prompt = (
            "Extract candidate place entities from the provided text snippets.\n"
            "Rules:\n"
            "- Only extract entities explicitly mentioned in the snippets or evidence spans.\n"
            "- Do not invent new entities.\n"
            "- Prefer proper-noun, multi-word place names when available.\n"
            "- Ignore article titles and generic phrases like Search, Best restaurants, Top places, guide.\n"
            "- Return only specific real-world place names.\n"
            "Return STRICT JSON with this shape only:\n"
            "{\"entities\":[{\"name\":\"...\",\"type\":\"place\",\"confidence\":0.0,\"evidence\":\"exact text span\"}]}\n\n"
            f"Snippets:\n{chr(10).join(source_chunks)}"
        )

        attempts = 0
        extraction = await self._generate_with_timeout(prompt, self._LLM_EXTRACTION_TIMEOUT_SECONDS)
        attempts += 1
        if not extraction.success:
            self._record_llm_extraction_failure()
            return [], False, attempts, False, "initial_call_failed"

        raw_output = extract_result_text(extraction.data)
        parsed = self._extract_json_object(raw_output)
        entities = self._extract_entities_list(parsed)
        used_retry = False

        if not entities:
            used_retry = True
            retry_prompt = (
                "Reformat the previous extraction into STRICT JSON only.\n"
                "Do not add explanations, markdown, or extra keys.\n"
                "Required shape:\n"
                "{\"entities\":[{\"name\":\"...\",\"type\":\"place\",\"confidence\":0.0}]}\n"
                "If no valid entity exists, return {\"entities\":[]}.\n\n"
                f"Previous output:\n{raw_output}"
            )
            retry = await self._generate_with_timeout(retry_prompt, self._LLM_EXTRACTION_TIMEOUT_SECONDS)
            attempts += 1
            if retry.success:
                retry_raw = extract_result_text(retry.data)
                entities = self._extract_entities_list(self._extract_json_object(retry_raw))

        if not entities:
            self._record_llm_extraction_failure()
            return [], used_retry, attempts, False, "invalid_extraction_output"

        source_haystack = "\n".join(self._build_grounded_text_blocks(local_payload))
        scored: list[tuple[float, str]] = []

        for item in entities:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("name", "") or "")
            candidate = self._normalize_candidate_name(raw_name)
            if not self._looks_like_place_candidate(candidate):
                continue
            mention_count = self._mentions_in_text(candidate, source_haystack)
            if mention_count <= 0:
                continue

            raw_confidence = item.get("confidence", 0.0)
            try:
                llm_confidence = max(0.0, min(1.0, float(raw_confidence)))
            except Exception:
                llm_confidence = 0.0

            length_score = min(len(candidate) / 24.0, 1.0)
            token_bonus = 1.0 if len(candidate.split()) >= 2 else 0.6
            score = (
                mention_count * 0.5
                + length_score * 0.2
                + token_bonus * 0.2
                + llm_confidence * 0.1
            )
            scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        deduped: list[str] = []
        seen: set[str] = set()
        for _, candidate in scored:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
            if len(deduped) >= 8:
                break
        self._record_llm_extraction_success()
        return deduped, used_retry, attempts, False, "ok"

    @staticmethod
    def _count_independent_sources(research_payloads: list[ResearchResultEnvelopeModel]) -> int:
        domains: set[str] = set()
        for payload in research_payloads:
            for source in payload.sources:
                domain = urlparse(source.url).netloc.strip().lower()
                if domain:
                    domains.add(domain)
        return len(domains)

    async def execute(self, context: SkillContext) -> SkillResult:
        deps_text = format_dependency_outputs(context.dependency_outputs)
        synthesis_task = str(context.input.get("description", "")).strip().lower()
        local_or_travel_synthesis = any(
            token in synthesis_task
            for token in ("verified local place", "local place", "travel", "itinerary")
        )
        research_payloads = [
            payload for payload in (parse_research_result(value) for value in context.dependency_outputs.values()) if payload is not None
        ]
        analysis_payloads = [
            payload for payload in (parse_analysis_result(value) for value in context.dependency_outputs.values()) if payload is not None
        ]

        if local_or_travel_synthesis:
            return await self._synthesize_local_discovery(context, research_payloads, deps_text)

        if not context.dependency_outputs and not research_payloads and not analysis_payloads:
            # Fallback to pure knowledge answer when synthesis is invoked without evidence.
            fallback_prompt = (
                "You are SynthesizerSkill. No dependency output or tool evidence is available. "
                "Answer with concise, honest general knowledge in English. "
                "If anything is uncertain, state the limitation instead of overclaiming.\n\n"
                f"Normalized prompt: {context.normalized_prompt}\n"
                f"Task: {str(context.input.get('description', '')).strip() or context.normalized_prompt}"
            )
            fallback_result = await self._generate(self._with_language_policy(fallback_prompt, context))
            if fallback_result.success:
                fallback_result.metadata = {
                    **(fallback_result.metadata or {}),
                    "provider": "synthesizer",
                    "source_count": 0,
                    "citation_count": 0,
                    "citations": "none",
                    "freshness": "n/a",
                    "fallback_used": True,
                    "confidence": 0.55,
                    "intent": "knowledge_fallback",
                    "providers_tried": "none",
                    "cache_ttl_seconds": 0,
                    "used_tool": "none",
                }
            return fallback_result

        failed_steps = [
            key
            for key, value in context.dependency_outputs.items()
            if extract_result_text(value).strip().startswith("ERROR:")
        ]

        if context.dependency_outputs and not research_payloads and not analysis_payloads and failed_steps and len(failed_steps) == len(context.dependency_outputs):
            if is_weather_text(context.normalized_prompt):
                return SkillResult(
                    success=False,
                    error="insufficient_live_evidence",
                    metadata={
                        "provider": "synthesizer",
                        "source_count": 0,
                        "citation_count": 0,
                        "citations": "none",
                        "freshness": "n/a",
                        "fallback_used": False,
                        "confidence": 0.0,
                        "intent": "weather_hard_fail",
                        "providers_tried": "dependency_outputs",
                        "cache_ttl_seconds": 0,
                        "used_tool": "none",
                        "failed_steps": ",".join(failed_steps),
                        "error_type": "permanent",
                    },
                )

            degraded_prompt = (
                "You are SynthesizerSkill in degraded mode. All dependency outputs failed to provide valid live evidence. "
                "Answer briefly from basic information only, do not overclaim, and state that more verification is needed.\n\n"
                f"Normalized prompt: {context.normalized_prompt}\n"
                f"Task: {str(context.input.get('description', '')).strip() or context.normalized_prompt}"
            )
            degraded = await self._generate(self._with_language_policy(degraded_prompt, context))
            if not degraded.success:
                return degraded

            degraded_answer = extract_result_text(degraded.data).strip() or self._fallback_text(
                context,
                english="There is not enough live evidence. This is a temporary best-effort answer.",
                vietnamese="There is not enough live evidence. This is a temporary best-effort answer.",
            )
            degraded_answer = self._fallback_text(
                context,
                english=(
                    "Disclaimer: there is not enough reliable live evidence, so the answer below is based only on general information. "
                    "Please verify it before using it for other purposes.\n\n"
                ),
                vietnamese=(
                    "Disclaimer: there is not enough reliable live evidence, so the answer below is based only on general information. "
                    "Please verify it before using it for other purposes.\n\n"
                ),
            ) + degraded_answer
            return SkillResult(
                success=True,
                data=degraded_answer,
                metadata={
                    "provider": "synthesizer",
                    "source_count": 0,
                    "citation_count": 0,
                    "citations": "none",
                    "freshness": "n/a",
                    "fallback_used": True,
                    "confidence": 0.18,
                    "intent": "degraded_llm",
                    "providers_tried": "dependency_outputs",
                    "cache_ttl_seconds": 0,
                    "used_tool": "none",
                    "failed_steps": ",".join(failed_steps),
                },
            )

        evidence_block = "\n\n".join(
            [
                f"Research summary: {payload.summary}\nSources:\n{format_sources_for_user(payload.sources) or '- none'}"
                for payload in research_payloads
            ]
        )
        analysis_block = "\n\n".join(
            [
                "Analysis summary: "
                f"{payload.summary}\n"
                f"Signals: {'; '.join(payload.signals[:4]) if payload.signals else '- none'}\n"
                f"Limitations: {'; '.join(payload.limitations[:3]) if payload.limitations else '- none'}\n"
                f"Quality: {payload.evidence_quality}; Coverage: {payload.data_coverage}; Conflicts: {payload.conflict_count}"
                for payload in analysis_payloads
            ]
        )
        prompt = (
            "You are SynthesizerSkill. Merge the intermediate results into one coherent final answer in English. "
            "If research evidence exists, use only facts that are explicitly supported by cited evidence. "
            "Do not add new facts beyond the evidence. When sources conflict, state the conflict and the confidence level clearly. "
            "Keep or add a References section with source URLs, and include an Evidence used section where each point is tied to a source URL when possible.\n\n"
            f"Normalized prompt: {context.normalized_prompt}\n"
            f"Recent memory:\n{context.recent_memory or '- none'}\n"
            f"Dependency outputs:\n{deps_text or '- none'}\n"
            f"Research evidence:\n{evidence_block or '- none'}\n"
            f"Analysis evidence:\n{analysis_block or '- none'}"
        )
        result = await self._generate(self._with_language_policy(prompt, context))
        if not result.success:
            return result

        answer_text = extract_result_text(result.data).strip()
        if research_payloads:
            sources = [source for payload in research_payloads for source in payload.sources]
            source_block = format_sources_for_user(sources)
            if source_block and source_block not in answer_text:
                answer_text = f"{answer_text}\n\nReferences:\n{source_block}"
            unique_urls: list[str] = []
            for source in sources:
                if source.url not in unique_urls:
                    unique_urls.append(source.url)
            avg_confidence = sum(payload.confidence for payload in research_payloads) / max(len(research_payloads), 1)
            insufficient_count = sum(1 for payload in research_payloads if self._is_insufficient_summary(payload.summary))
            if insufficient_count > 0:
                insufficient_penalty = min(0.25 + insufficient_count * 0.12, 0.65)
                avg_confidence = max(0.15, avg_confidence - insufficient_penalty)
                answer_text = self._fallback_text(
                    context,
                    english=(
                        "Note: the current evidence is still missing direct support for some aspects, "
                        "so the confidence level was reduced to avoid overclaiming.\n\n"
                    ),
                    vietnamese=(
                        "Note: the current evidence is still missing direct support for some aspects, "
                        "so the confidence level was reduced to avoid overclaiming.\n\n"
                    ),
                ) + answer_text
            freshness = sources[0].freshness if sources else "n/a"
            result.metadata = {
                **(result.metadata or {}),
                "provider": "synthesizer",
                "source_count": len(unique_urls),
                "citation_count": len(unique_urls),
                "citations": ",".join(unique_urls) if unique_urls else "none",
                "freshness": freshness,
                "fallback_used": insufficient_count > 0,
                "confidence": round(float(avg_confidence), 2),
                "intent": "synthesis",
                "providers_tried": "dependency_outputs",
                "cache_ttl_seconds": 0,
                "used_tool": "none",
                "insufficient_research_count": insufficient_count,
            }
        elif analysis_payloads:
            avg_confidence = sum(payload.confidence for payload in analysis_payloads) / max(len(analysis_payloads), 1)
            max_conflicts = max((payload.conflict_count for payload in analysis_payloads), default=0)
            min_quality = "high"
            for payload in analysis_payloads:
                if payload.evidence_quality == "low":
                    min_quality = "low"
                    break
                if payload.evidence_quality == "medium":
                    min_quality = "medium"

            if max_conflicts > 0 or avg_confidence < 0.45:
                answer_text = (
                    "Disclaimer: the conclusions below are provisional because the evidence is still conflicting or has low reliability.\n\n"
                    f"{answer_text}"
                )

            result.metadata = {
                **(result.metadata or {}),
                "provider": "synthesizer",
                "source_count": len(analysis_payloads),
                "citation_count": 0,
                "citations": "none",
                "freshness": "recent",
                "fallback_used": max_conflicts > 0 or avg_confidence < 0.45,
                "confidence": round(float(avg_confidence), 2),
                "intent": "synthesis",
                "providers_tried": "analysis_outputs",
                "cache_ttl_seconds": 0,
                "used_tool": "none",
                "conflict_count": max_conflicts,
                "evidence_quality": min_quality,
            }
        else:
            result.metadata = {
                **(result.metadata or {}),
                "provider": "synthesizer",
                "source_count": 0,
                "citation_count": 0,
                "citations": "none",
                "freshness": "n/a",
                "fallback_used": False,
                "confidence": 0.6,
                "intent": "synthesis",
                "providers_tried": "none",
                "cache_ttl_seconds": 0,
                "used_tool": "none",
            }
        result.data = answer_text
        return result

    async def _synthesize_local_discovery(
        self,
        context: SkillContext,
        research_payloads: list[ResearchResultEnvelopeModel],
        deps_text: str,
    ) -> SkillResult:
        """Handle synthesis for local_discovery and travel_planning pipelines.

        Accepts evidence in any format: ResearchResultEnvelope, PlaceVerification
        plain dicts, ReviewConsensus plain dicts, or ERROR strings from failed nodes.
        Always produces a useful answer — never returns a hard failure to the user.
        """
        place_verify_raw = context.dependency_outputs.get("place-verify")
        candidate_extract_raw = context.dependency_outputs.get("candidate-extract")
        verified_places: list[dict[str, object]] = []
        if isinstance(place_verify_raw, dict):
            raw_verified_places = place_verify_raw.get("verified_places")
            if isinstance(raw_verified_places, list):
                verified_places = [item for item in raw_verified_places if isinstance(item, dict)]

        extracted_candidates: list[dict[str, object]] = []
        if isinstance(candidate_extract_raw, dict):
            raw_candidates = candidate_extract_raw.get("candidates")
            if isinstance(raw_candidates, list):
                extracted_candidates = [item for item in raw_candidates if isinstance(item, dict)]

        has_verified_places = bool(verified_places)
        has_structured_candidates = bool(extracted_candidates)
        local_payload = parse_research_result(context.dependency_outputs.get("local-search"))

        if has_structured_candidates:
            fallback_candidates = [
                str(item.get("name", "")).strip()
                for item in extracted_candidates
                if str(item.get("name", "")).strip()
            ][:8]
            llm_candidates: list[str] = []
            llm_retry_used = False
            llm_attempts = 0
            llm_skipped = True
            llm_skip_reason = "candidate_node_available"
        else:
            llm_candidates, llm_retry_used, llm_attempts, llm_skipped, llm_skip_reason = await self._extract_candidates_with_llm(local_payload)
            heuristic_candidates = self._extract_fallback_places_from_local_search(context.dependency_outputs.get("local-search"))
            fallback_candidates = []
            seen_candidates: set[str] = set()
            for candidate in llm_candidates + heuristic_candidates:
                key = candidate.lower()
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                fallback_candidates.append(candidate)
                if len(fallback_candidates) >= 8:
                    break

        # Collect useful content from all dependency outputs regardless of format.
        # PlaceVerificationSkill and ReviewConsensusSkill emit plain dicts with a
        # 'summary' key — extract_result_text handles these correctly.
        useful_parts: list[str] = []
        for key, val in context.dependency_outputs.items():
            text = extract_result_text(val).strip()
            if text and not text.startswith("ERROR:"):
                useful_parts.append(f"[{key}]\n{text}")

        has_evidence = bool(useful_parts) or bool(research_payloads) or bool(fallback_candidates)

        evidence_block = "\n\n".join(useful_parts) if useful_parts else ""
        research_block = "\n\n".join(
            f"Research sources:\n{format_sources_for_user(p.sources)}\nSummary: {p.summary}"
            for p in research_payloads
        ) if research_payloads else ""
        extracted_candidates_block = ""
        if extracted_candidates:
            extracted_candidates_block = "\n".join(
                f"- {item.get('name', 'unknown')} | type={item.get('type', 'place')} | "
                f"location={item.get('location', 'unspecified')} | confidence={item.get('confidence', 0.0)}"
                for item in extracted_candidates[:6]
            )
        fallback_candidates_block = ""
        if fallback_candidates and not has_verified_places:
            fallback_candidates_block = "\n".join(f"- {item}" for item in fallback_candidates)

        # Extract location from geo-intent if available in this synthesizer's dependency outputs.
        geo_raw_s = context.dependency_outputs.get("geo-intent")
        target_location_s = ""
        if isinstance(geo_raw_s, dict):
            geo_data_s = geo_raw_s.get("geo_intent", {})
            if isinstance(geo_data_s, dict):
                target_location_s = str(geo_data_s.get("location", "")).strip()
        location_rule = (
            f"- VỊ TRÍ BẮT BUỘC: Chỉ gợi ý địa điểm thực sự ở {target_location_s}. "
            "Nếu tên địa điểm hoặc mô tả gợi ý vị trí khác (thành phố/quốc gia khác), LOẠI BỎ ngay lập tức.\n"
        ) if target_location_s else ""

        if has_evidence:
            combined_evidence = "\n\n".join(filter(None, [evidence_block, research_block]))
            prompt = (
                "You are SynthesizerSkill. Turn the pipeline outputs into practical place recommendations for the user.\n"
                "Mandatory rules:\n"
                f"{location_rule}"
                "- Present at least 3 specific suggestions from the available data\n"
                "- Use a clear format: place name plus a short reason\n"
                "- If the evidence is incomplete, add a short confidence note\n"
                "- Never answer with 'cannot verify' or similar refusals\n\n"
                f"User request: {context.normalized_prompt}\n\n"
                f"Pipeline data:\n{combined_evidence or deps_text or '- none'}\n"
                f"Extracted structured candidates:\n{extracted_candidates_block or '- none'}\n"
                f"Fallback candidate list when place verification is empty:\n{fallback_candidates_block or '- none'}\n"
            )
            confidence_base = 0.55 if research_payloads else 0.42
        else:
            # All upstream nodes failed (e.g. SerpAPI key missing, no places found).
            # Still provide best-effort from LLM knowledge with explicit disclaimer.
            prompt = (
                "You are a helpful assistant. The live place-search pipeline has no verified data for this request.\n"
                "Provide best-effort suggestions from general knowledge with these constraints:\n"
                "- Give at least 3 to 5 specific suggestions with short reasons\n"
                "- Do not refuse or say there is no information\n"
                "- Keep the answer practical and concise in English\n\n"
                f"Request: {context.normalized_prompt}"
            )
            confidence_base = 0.30

        result = await self._generate(self._with_language_policy(prompt, context))
        if not result.success:
            return result

        answer = extract_result_text(result.data).strip()
        if not has_evidence:
            answer = self._fallback_text(
                context,
                english="Warning: the suggestions below are based on general knowledge and have not been verified against live sources.\n\n",
                vietnamese="Warning: the suggestions below are based on general knowledge and have not been verified against live sources.\n\n",
            ) + answer

        sources = [s for p in research_payloads for s in p.sources]
        unique_urls = list({s.url for s in sources})
        source_count = len(unique_urls) or len(useful_parts)
        independent_source_count = self._count_independent_sources(research_payloads)

        verification_status = "verified" if has_verified_places else "candidate_extracted" if has_structured_candidates else "unverified"
        needs_followup = not has_verified_places or independent_source_count < 2
        if has_verified_places:
            confidence_label = "high"
        elif has_structured_candidates and independent_source_count >= 1:
            confidence_label = "medium"
        elif independent_source_count >= 2:
            confidence_label = "medium"
        else:
            confidence_label = "low"

        if needs_followup and not answer.lower().startswith(("warning:", "disclaimer:", "note:")):
            answer = (
                "Warning: part of the suggestions below remains provisional because the place-verification layer is not yet complete. "
                "Please confirm opening hours and availability before deciding.\n\n"
                f"{answer}"
            )

        result.data = answer
        result.metadata = {
            **(result.metadata or {}),
            "provider": "synthesizer",
            "source_count": source_count,
            "citation_count": len(unique_urls),
            "citations": ",".join(unique_urls) if unique_urls else "none",
            "freshness": sources[0].freshness if sources else "n/a",
            "fallback_used": not bool(research_payloads),
            "confidence": round(min(0.85, confidence_base + min(source_count, 5) * 0.06), 2),
            "confidence_label": confidence_label,
            "verification_status": verification_status,
            "needs_followup": needs_followup,
            "independent_source_count": independent_source_count,
            "fallback_place_count": len(fallback_candidates),
            "structured_candidate_count": len(extracted_candidates),
            "llm_extraction_used": llm_attempts > 0,
            "llm_extraction_success": bool(llm_candidates),
            "llm_extraction_retried": llm_retry_used,
            "llm_extraction_attempts": llm_attempts,
            "llm_candidate_count": len(llm_candidates),
            "llm_extraction_skipped": llm_skipped,
            "llm_extraction_skip_reason": llm_skip_reason,
            "intent": "local_discovery",
            "providers_tried": "dependency_outputs" if has_evidence else "llm_knowledge",
            "cache_ttl_seconds": 0,
            "used_tool": "none",
        }
        return result


class FusionSkill(BaseLLMSkill):
    """Arbitration layer for multi-hypothesis execution.

    Reads path-a (cheap LLM direct) and path-b (research) dependency outputs
    and selects the stronger signal or blends both transparently.

    Decision logic:
      research_preferred  — research confidence >= 0.55 AND not insufficient AND has sources
      llm_direct_fallback — research failed/insufficient AND cheap text exists
      blend               — otherwise (partial evidence on both sides)
    """

    metadata = SkillMetadata(
        name="fusion",
        description="Arbitrate and fuse outputs from parallel cheap/expensive execution paths.",
        examples=["ambiguity resolution", "path fusion", "multi-hypothesis merge"],
        priority_weight=0.19,
        input_schema={
            "type": "object",
            "properties": {"description": {"type": "string", "minLength": 1}},
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    _RESEARCH_CONFIDENCE_GATE: float = 0.55
    _INSUFFICIENT_HINTS = (
        "khong du", "không đủ", "chua co du", "chưa có đủ",
        "insufficient", "no evidence", "mock",
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        _ = input_data
        return True

    @classmethod
    def _is_insufficient(cls, text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in cls._INSUFFICIENT_HINTS)

    async def execute(self, context: SkillContext) -> SkillResult:
        cheap_raw = context.dependency_outputs.get("path-a")
        research_raw = context.dependency_outputs.get("path-b")
        cheap_text = extract_result_text(cheap_raw).strip() if cheap_raw is not None else ""
        research_payload = parse_research_result(research_raw) if research_raw is not None else None

        has_strong_research = (
            research_payload is not None
            and research_payload.confidence >= self._RESEARCH_CONFIDENCE_GATE
            and not self._is_insufficient(research_payload.summary or "")
            and bool(research_payload.sources)
        )

        if has_strong_research and research_payload is not None:
            decision = "research_preferred"
            primary_text = research_payload.summary
            secondary_text = cheap_text
            sources = research_payload.sources
            confidence = research_payload.confidence
        elif cheap_text and (research_payload is None or self._is_insufficient(research_payload.summary or "")):
            decision = "llm_direct_fallback"
            primary_text = cheap_text
            secondary_text = ""
            sources = []
            confidence = 0.55
        else:
            decision = "blend"
            primary_text = cheap_text
            secondary_text = research_payload.summary if research_payload else ""
            sources = research_payload.sources if research_payload else []
            confidence = (research_payload.confidence if research_payload else 0.5) * 0.6 + 0.4 * 0.5

        blend_section = (
            f"\nBổ sung từ LLM direct:\n{secondary_text}"
            if decision == "research_preferred" and secondary_text
            else ""
        )
        prompt = (
            "You are FusionSkill. Create the final answer from two sources collected in parallel.\n"
            "Priority: if research evidence with concrete sources exists, use it as the primary foundation. "
            "If the direct LLM answer adds helpful context, integrate it without repeating points.\n"
            "Do not add any new facts beyond what is already available. Write naturally in English.\n\n"
            f"Original prompt: {context.normalized_prompt}\n"
            f"Recent memory:\n{context.recent_memory or '- none'}\n"
            f"Decision: {decision}\n"
            f"Primary source:\n{primary_text or '- none'}"
            f"{blend_section}"
        )
        result = await self._generate(self._with_language_policy(prompt, context))
        if not result.success:
            return result

        answer_text = extract_result_text(result.data).strip() or primary_text or self._fallback_text(
            context,
            english="There is not enough evidence to answer reliably.",
            vietnamese="Không đủ evidence để trả lời.",
        )
        if sources:
            source_block = format_sources_for_user(sources)
            if source_block and source_block not in answer_text:
                answer_text = f"{answer_text}\n\nReferences:\n{source_block}"
            unique_urls = list({s.url for s in sources})
        else:
            unique_urls = []

        result.data = answer_text
        result.metadata = {
            **(result.metadata or {}),
            "provider": "fusion",
            "decision": decision,
            "source_count": len(unique_urls),
            "citation_count": len(unique_urls),
            "citations": ",".join(unique_urls) if unique_urls else "none",
            "freshness": sources[0].freshness if sources else "n/a",
            "fallback_used": decision != "research_preferred",
            "confidence": round(float(confidence), 2),
            "intent": "fusion",
            "providers_tried": "path-a,path-b",
            "cache_ttl_seconds": 0,
            "used_tool": "none",
        }
        return result


class GeoIntentSkill:
    metadata = SkillMetadata(
        name="geo_intent",
        description="Extract geographic constraints (location, budget, companions, preferences) from local/travel queries.",
        examples=["nhà hàng ở Đà Nẵng", "khách sạn gần biển Nha Trang", "lịch trình 2 ngày Đà Lạt"],
        priority_weight=0.22,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    _LOCATION_PATTERNS = (
        r"(?:ở|o|at|in)\s+([A-Za-zÀ-ỹ\s]+)",
        r"(?:tại|tai)\s+([A-Za-zÀ-ỹ\s]+)",
        r"(?:gần|gan|near)\s+([A-Za-zÀ-ỹ\s]+)",
        # Handles travel context: "business trip to Tokyo", "travel to Paris", "going to Berlin"
        r"(?:trip|travel|journey|visit(?:ing)?|going)\s+to\s+([A-Za-zÀ-ỹ]+(?:\s[A-Za-zÀ-ỹ]+){0,2})",
    )

    _BUDGET_HINTS = (
        "rẻ",
        "bình dân",  # removed bare "re" — it substring-matches "restaurant"
        "binh dan",
        "cheap",
        "luxury",
        "cao cấp",
        "cao cap",
        "mid-range",
        "tầm trung",
        "tam trung",
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        return any(
            token in text
            for token in (
                "nhà hàng",
                "nha hang",
                "restaurant",
                "hotel",
                "khách sạn",
                "khach san",
                "du lịch",
                "du lich",
                "travel",
                "itinerary",
            )
        )

    def execute_sync(self, text: str) -> dict[str, object]:
        lowered = text.lower()
        location = ""
        for pattern in self._LOCATION_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                location = re.sub(r"\s+", " ", match.group(1)).strip(" .,")
                break

        budget = "unspecified"
        for hint in self._BUDGET_HINTS:
            if hint in lowered:
                budget = hint
                break

        interests = []
        for token in ("ẩm thực", "am thuc", "biển", "bien", "museum", "bảo tàng", "bao tang", "family", "couple"):
            if token in lowered and token not in interests:
                interests.append(token)

        days = "unspecified"
        day_match = re.search(r"(\d+)\s*(?:ngày|ngay|days?)", lowered)
        if day_match:
            days = f"{day_match.group(1)}d"

        summary = (
            f"Đã nhận diện yêu cầu địa điểm. Location={location or 'unspecified'}, "
            f"budget={budget}, duration={days}, interests={', '.join(interests) if interests else 'unspecified'}."
        )

        return {
            "summary": summary,
            "geo_intent": {
                "location": location,
                "budget": budget,
                "duration": days,
                "interests": interests,
            },
        }

    async def execute(self, context: SkillContext) -> SkillResult:
        description = str(context.input.get("description", "")).strip()
        return SkillResult(success=True, data=self.execute_sync(description), metadata={"intent": "local_discovery"})


class LocalDiscoverySkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="local_discovery",
        description="Discover local places (restaurants/hotels/attractions) with evidence-based shortlist.",
        examples=["best restaurants in Da Nang", "khách sạn gần biển Nha Trang", "địa điểm đi chơi ở Hà Nội"],
        priority_weight=0.3,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def __init__(self, model_source: SupportsCallModel | Callable[[str], str], search_provider: SearchProvider) -> None:
        super().__init__(model_source)
        self._search_provider = search_provider

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        return any(
            token in text
            for token in (
                "nhà hàng",
                "nha hang",
                "restaurant",
                "hotel",
                "khách sạn",
                "khach san",
                "resort",
                "du lịch",
                "travel",
                "địa điểm",
                "attraction",
            )
        )

    @staticmethod
    def _infer_place_type(text: str) -> str:
        lowered = text.lower()
        if any(t in lowered for t in ("restaurant", "nhà hàng", "nha hang", "quán ăn", "lunch", "dinner", "breakfast", "eat", "food", "dining", "ăn")):
            return "restaurant"
        if any(t in lowered for t in ("hotel", "khách sạn", "khach san", "resort", "homestay")):
            return "hotel"
        if any(t in lowered for t in ("attraction", "địa điểm", "dia diem", "things to do", "museum", "park")):
            return "tourist attraction"
        return "place"

    async def execute(self, context: SkillContext) -> SkillResult:
        query = str(context.input.get("description", "")).strip()
        started_at = time.perf_counter()

        # Read location from geo-intent (runs before local-search in the DAG).
        # Build a tightly location-scoped query so OSM / DDG return places in the right city.
        geo_raw = context.dependency_outputs.get("geo-intent")
        if isinstance(geo_raw, dict):
            geo_data = geo_raw.get("geo_intent", {})
            location = str(geo_data.get("location", "")).strip() if isinstance(geo_data, dict) else ""
            if location:
                place_type = self._infer_place_type(query)
                query = f"{place_type} in {location}"

        batch: SearchResultBatch | None = None
        if context.selected_tool is not None:
            try:
                from .tools import ToolInput

                tool_output = await context.selected_tool.execute(ToolInput(query=query, limit=6))
                if tool_output.success:
                    batch = ResearchSkill._build_search_batch_from_tool_output(context.selected_tool.name, tool_output)
            except Exception:
                batch = None

        if batch is None:
            batch = await self._search_provider.search(query, limit=6)

        if not batch.documents:
            return SkillResult(success=False, error="no_local_places_found", metadata={"error_type": "permanent"})

        ranked_docs = rank_documents_for_query(query, batch.documents, limit=6)
        sources = [
            ResearchSourceModel(
                title=doc.title,
                snippet=doc.snippet,
                url=doc.url,
                freshness=doc.freshness,
                published_at=doc.published_at,
                reliability=doc.reliability,
                provider=doc.provider,
            )
            for doc in ranked_docs
        ]

        shortlist_lines = [
            f"{idx + 1}. {doc.title} - {doc.snippet[:120]}"
            for idx, doc in enumerate(ranked_docs[:5])
        ]
        summary = "Top local options đã được tổng hợp:\n" + "\n".join(shortlist_lines)

        payload = ResearchResultEnvelopeModel(
            kind="research_result",
            summary=summary,
            grounded=True,
            confidence=batch.confidence,
            citations=[item.url for item in sources],
            sources=sources,
            evidence=[
                EvidenceModel(
                    content=item.snippet,
                    source=item.url,
                    timestamp=item.published_at,
                    reliability=item.reliability,
                    provider=item.provider,
                )
                for item in sources
            ],
        ).model_dump()

        return SkillResult(
            success=True,
            data=payload,
            metadata={
                "provider": batch.provider,
                "source_count": len(ranked_docs),
                "freshness": ranked_docs[0].freshness,
                "citation_count": len({doc.url for doc in ranked_docs}),
                "citations": ",".join(doc.url for doc in ranked_docs),
                "fallback_used": batch.fallback_used,
                "latency_ms": batch.latency_ms or int((time.perf_counter() - started_at) * 1000),
                "confidence": batch.confidence,
                "intent": "local_discovery",
                "providers_tried": ",".join(batch.providers_tried or []),
                "cache_ttl_seconds": batch.cache_ttl_seconds,
                "used_tool": context.selected_tool.name if context.selected_tool is not None else "none",
            },
        )


class PlaceVerificationSkill:
    metadata = SkillMetadata(
        name="place_verification",
        description="Verify and deduplicate place candidates, then produce a trusted shortlist.",
        examples=["verify local places", "deduplicate hotels", "cross-check attractions"],
        priority_weight=0.24,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        _ = input_data
        return True

    async def execute(self, context: SkillContext) -> SkillResult:
        local_raw = context.dependency_outputs.get("local-search")
        local_payload = parse_research_result(local_raw)
        if local_payload is None:
            text = extract_result_text(local_raw).strip()
            if not text or text.startswith("ERROR:"):
                return SkillResult(success=False, error="local_evidence_missing", metadata={"error_type": "permanent"})
            return SkillResult(success=False, error="local_evidence_missing", metadata={"error_type": "permanent"})

        # Read target location from geo-intent (available when geo-intent is in depends_on).
        geo_raw = context.dependency_outputs.get("geo-intent")
        target_location = ""
        if isinstance(geo_raw, dict):
            geo_data = geo_raw.get("geo_intent", {})
            if isinstance(geo_data, dict):
                target_location = str(geo_data.get("location", "")).strip().lower()

        seen_titles: set[str] = set()
        verified: list[dict[str, object]] = []
        for source in local_payload.sources:
            normalized_title = re.sub(r"\s+", " ", source.title.strip().lower())
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            # Location guard: drop places whose ADDRESS doesn't mention the target city.
            # Strip the place name from the snippet first to avoid false positives like
            # "Tokyo In April" restaurant in Vancouver matching a Tokyo query.
            # OSM snippet format: "osm_type: Place Name, address1, City, Country. Coordinates: ..."
            if target_location:
                snippet_lower = source.snippet.lower()
                colon_pos = snippet_lower.find(":")
                if colon_pos >= 0:
                    after_colon = snippet_lower[colon_pos + 1:]
                    comma_pos = after_colon.find(",")
                    address_part = after_colon[comma_pos + 1:] if comma_pos >= 0 else after_colon
                else:
                    address_part = snippet_lower
                if target_location not in address_part:
                    continue
            verified.append(
                {
                    "name": source.title,
                    "url": source.url,
                    "snippet": source.snippet,
                    "provider": source.provider or "unknown",
                    "freshness": source.freshness,
                    "reliability": source.reliability,
                }
            )
            if len(verified) >= 5:
                break

        if not verified:
            return SkillResult(success=False, error="no_local_places_found", metadata={"error_type": "permanent"})

        summary_lines = [f"{idx + 1}. {item['name']} ({item['provider']})" for idx, item in enumerate(verified)]
        summary = "Danh sách địa điểm đã xác thực:\n" + "\n".join(summary_lines) if summary_lines else "Không có địa điểm đủ điều kiện xác thực."

        return SkillResult(
            success=True,
            data={
                "summary": summary,
                "verified_places": verified,
            },
            metadata={
                "provider": "place_verification",
                "source_count": len(verified),
                "citation_count": len(verified),
                "confidence": round(min(0.92, 0.45 + len(verified) * 0.08), 2),
                "intent": "local_discovery",
                "used_tool": "none",
            },
        )


class ReviewConsensusSkill:
    metadata = SkillMetadata(
        name="review_consensus",
        description="Extract practical pros/cons consensus from local place snippets.",
        examples=["review consensus for restaurants", "hotel pros and cons"],
        priority_weight=0.21,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    _POSITIVE_HINTS = ("ngon", "sạch", "đẹp", "friendly", "good", "great", "view", "tiện", "clean", "excellent")
    _NEGATIVE_HINTS = ("đắt", "dong", "ồn", "noisy", "bad", "poor", "xa", "far", "chậm", "wait")

    def can_handle(self, input_data: dict[str, object]) -> bool:
        _ = input_data
        return True

    async def execute(self, context: SkillContext) -> SkillResult:
        local_payload = parse_research_result(context.dependency_outputs.get("local-search"))
        if local_payload is None or not local_payload.sources:
            return SkillResult(success=False, error="local_evidence_missing", metadata={"error_type": "permanent"})

        pros: list[str] = []
        cons: list[str] = []
        for source in local_payload.sources:
            snippet = source.snippet.lower()
            if any(token in snippet for token in self._POSITIVE_HINTS) and source.title not in pros:
                pros.append(source.title)
            if any(token in snippet for token in self._NEGATIVE_HINTS) and source.title not in cons:
                cons.append(source.title)

        pros_preview = ", ".join(pros[:4]) if pros else "chưa rõ"
        cons_preview = ", ".join(cons[:4]) if cons else "không thấy vấn đề nổi bật"
        summary = f"Consensus review: Ưu điểm nổi bật: {pros_preview}. Hạn chế thường gặp: {cons_preview}."

        return SkillResult(
            success=True,
            data={
                "summary": summary,
                "pros": pros[:6],
                "cons": cons[:6],
            },
            metadata={
                "provider": "review_consensus",
                "source_count": len(local_payload.sources),
                "confidence": round(min(0.85, 0.4 + len(local_payload.sources) * 0.06), 2),
                "intent": "local_discovery",
            },
        )


class CandidateExtractionSkill(SynthesizerSkill):
    metadata = SkillMetadata(
        name="candidate_extraction",
        description="Extract structured place candidates from local search evidence using guarded LLM parsing.",
        examples=["extract restaurant candidates", "parse place entities", "candidate extraction"],
        priority_weight=0.23,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        _ = input_data
        return True

    @staticmethod
    def _infer_candidate_type(description: str) -> str:
        return LocalDiscoverySkill._infer_place_type(description)

    @classmethod
    def _build_candidate_records(
        cls,
        candidate_names: list[str],
        local_payload: ResearchResultEnvelopeModel,
        description: str,
        location: str,
    ) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        candidate_type = cls._infer_candidate_type(description)

        for name in candidate_names:
            evidence_sources: list[str] = []
            mention_count = 0
            for source in local_payload.sources:
                haystack = f"{source.title}\n{source.snippet}"
                mentions_here = cls._mentions_in_text(name, haystack)
                if mentions_here <= 0:
                    continue
                mention_count += mentions_here
                if source.url not in evidence_sources:
                    evidence_sources.append(source.url)

            if mention_count <= 0:
                continue

            source_support = min(len(evidence_sources) / 3.0, 1.0)
            mention_support = min(mention_count / 3.0, 1.0)
            confidence = round(min(0.95, 0.45 + source_support * 0.3 + mention_support * 0.2), 2)
            evidence_span = cls._find_best_evidence_span(name, local_payload)
            records.append(
                {
                    "name": name,
                    "type": candidate_type,
                    "location": location or "unspecified",
                    "confidence": confidence,
                    "evidence_sources": evidence_sources[:4],
                    "evidence_span": evidence_span,
                    "mention_count": mention_count,
                }
            )

        return records[:6]

    async def execute(self, context: SkillContext) -> SkillResult:
        local_payload = parse_research_result(context.dependency_outputs.get("local-search"))
        if local_payload is None or not local_payload.sources:
            return SkillResult(success=False, error="local_evidence_missing", metadata={"error_type": "permanent"})

        geo_raw = context.dependency_outputs.get("geo-intent")
        target_location = ""
        if isinstance(geo_raw, dict):
            geo_data = geo_raw.get("geo_intent", {})
            if isinstance(geo_data, dict):
                target_location = str(geo_data.get("location", "") or "").strip()

        llm_candidates, llm_retry_used, llm_attempts, llm_skipped, llm_skip_reason = await self._extract_candidates_with_llm(local_payload)
        heuristic_candidates = self._extract_grounded_fallback_places(local_payload)

        ordered_names: list[str] = []
        seen: set[str] = set()
        for candidate in llm_candidates + heuristic_candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered_names.append(candidate)
            if len(ordered_names) >= 8:
                break

        candidate_records = self._build_candidate_records(
            ordered_names,
            local_payload,
            str(context.input.get("description", "") or context.normalized_prompt),
            target_location,
        )
        if not candidate_records:
            return SkillResult(success=False, error="no_candidate_entities", metadata={"error_type": "permanent"})

        summary_lines = [
            f"{idx + 1}. {item['name']} ({item['type']}, {item['location']}, confidence={item['confidence']})"
            for idx, item in enumerate(candidate_records)
        ]
        summary = "Extracted place candidates:\n" + "\n".join(summary_lines)

        return SkillResult(
            success=True,
            data={
                "summary": summary,
                "candidates": candidate_records,
                "candidate_count": len(candidate_records),
            },
            metadata={
                "provider": "candidate_extraction",
                "source_count": len(candidate_records),
                "candidate_count": len(candidate_records),
                "confidence": round(sum(float(item["confidence"]) for item in candidate_records) / max(len(candidate_records), 1), 2),
                "llm_extraction_used": llm_attempts > 0,
                "llm_extraction_success": bool(llm_candidates),
                "llm_extraction_retried": llm_retry_used,
                "llm_extraction_attempts": llm_attempts,
                "llm_candidate_count": len(llm_candidates),
                "llm_extraction_skipped": llm_skipped,
                "llm_extraction_skip_reason": llm_skip_reason,
                "intent": "local_discovery",
            },
        )


class ItineraryPlannerSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="itinerary_planner",
        description="Create a concise travel itinerary from verified local places and constraints.",
        examples=["lịch trình 2 ngày Đà Lạt", "2-day Hanoi itinerary"],
        priority_weight=0.25,
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["description"],
            "additionalProperties": True,
        },
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        return any(token in text for token in ("itinerary", "lịch trình", "lich trinh", "du lịch", "travel"))

    async def execute(self, context: SkillContext) -> SkillResult:
        prompt = str(context.input.get("description", "")).strip()
        geo_text = extract_result_text(context.dependency_outputs.get("geo-intent"))
        verified_payload = context.dependency_outputs.get("place-verify")
        verified_text = extract_result_text(verified_payload)
        candidate_payload = context.dependency_outputs.get("candidate-extract")

        verified_places: list[dict[str, object]] = []
        if isinstance(verified_payload, dict):
            raw_places = verified_payload.get("verified_places")
            if isinstance(raw_places, list):
                verified_places = [item for item in raw_places if isinstance(item, dict)]

        extracted_candidates: list[dict[str, object]] = []
        if isinstance(candidate_payload, dict):
            raw_candidates = candidate_payload.get("candidates")
            if isinstance(raw_candidates, list):
                extracted_candidates = [item for item in raw_candidates if isinstance(item, dict)]

        candidate_lines = [
            f"- {item.get('name', 'unknown')} ({item.get('type', 'place')}, {item.get('location', 'unspecified')})"
            for item in extracted_candidates[:6]
        ]
        candidate_text = "\n".join(candidate_lines)

        if (not verified_places or str(verified_text).strip().startswith("ERROR:")) and not extracted_candidates:
            return SkillResult(
                success=False,
                error="no_verified_places_for_itinerary",
                metadata={"error_type": "permanent", "intent": "travel_planning"},
            )

        llm_prompt = (
            "You are ItineraryPlannerSkill. Build a short, practical itinerary with morning, afternoon, and evening slots. "
            "Only use places that appear in the evidence, and do not invent new places.\n\n"
            f"User prompt: {prompt}\n"
            f"Geo constraints: {geo_text or '- none'}\n"
            f"Verified places:\n{verified_text or '- none'}\n"
            f"Candidate places:\n{candidate_text or '- none'}\n"
        )

        result = await self._generate(self._with_language_policy(llm_prompt, context))
        if not result.success:
            return result

        itinerary = extract_result_text(result.data).strip() or self._fallback_text(
            context,
            english="There is not enough evidence to build a detailed itinerary yet.",
            vietnamese="Chưa đủ dữ liệu để tạo lịch trình chi tiết.",
        )
        return SkillResult(
            success=True,
            data={
                "summary": itinerary,
                "itinerary": itinerary,
            },
            metadata={
                "provider": "itinerary_planner",
                "confidence": 0.72,
                "intent": "travel_planning",
                "verification_status": "verified" if verified_places else "candidate_extracted",
            },
        )
