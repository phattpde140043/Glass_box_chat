from __future__ import annotations

import asyncio
import re
import time
from typing import Callable, Protocol

from .planner import needs_research_text
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


class ResearchSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="research",
        description="Research current or external information using a search provider before answering.",
        examples=["thời tiết hôm nay", "latest news", "giá hiện tại", "tra cứu", "research"],
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
        "mô phỏng",
        "mo phong",
    )

    _SUBJECT_HINT_GROUPS = (
        ("cà phê", "ca phe", "cafe", "coffee", "arabica", "robusta"),
        ("hồ tiêu", "ho tieu", "pepper"),
        ("gia vang", "giá vàng", "gold", "xau", "xauusd"),
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
                "Khong co du lieu live dang tin cay cho yeu cau nay. "
                "He thong da tranh dung source demo/mock de dua ra nhan dinh."
            )
        else:
            error = "insufficient_relevant_evidence"
            message = (
                "Da thu thu thap thong tin nhung chua co du lieu lien quan truc tiep den chu de can phan tich."
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
            "Bạn là ResearchSkill. Chỉ được trả lời dựa trên evidence bên dưới. "
            "Nếu evidence không đủ chắc chắn, phải nói rõ giới hạn. Ưu tiên tiếng Việt.\n\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Task nghiên cứu: {task_description}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Evidence:\n{evidence_text}\n\n"
            "Yêu cầu: viết một đoạn tóm tắt findings ngắn gọn, nêu rõ giới hạn nếu có, không bịa thêm nguồn hay dữ kiện ngoài evidence."
        )
        result = await self._generate(prompt)
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
                summary=summary or "Không có findings rõ ràng từ evidence hiện tại.",
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
        examples=["giá vàng hôm nay", "gold price", "BTC price", "tỷ giá"],
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
        "gia vang",
        "giá vàng",
        "gold price",
        "xau",
        "xauusd",
        "crypto",
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "tỷ giá",
        "ty gia",
        "exchange rate",
        "forex",
    )

    def can_handle(self, input_data: dict[str, object]) -> bool:
        text = str(input_data.get("description", "")).lower()
        tokens = {token for token in re.split(r"[^\wÀ-ỹ]+", text) if token}
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
                "Hien tai khong the lay gia thi truong real-time do loi ket noi provider.\n\n"
                "Ban co the thu lai sau it phut hoac tham khao:\n"
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
            graceful = str(tool_result.content or "").strip() or (
                "Hien tai khong the lay gia thi truong real-time. Vui long thu lai sau."
            )

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
                "Ban la AnalysisSkill o che do degraded. Khong co evidence live dang tin cay tu research. "
                "Hay dua ra nhan dinh tong quat ngan gon dua tren kien thuc co ban, KHONG khang dinh tuyet doi, "
                "va neu ro can xac minh them truoc khi su dung trong quyet dinh quan trong.\n\n"
                f"Prompt chuan hoa: {context.normalized_prompt}\n"
                f"Task phan tich: {task_description}"
            )
            degraded = await self._generate(degraded_prompt)
            if not degraded.success:
                return degraded

            degraded_summary = extract_result_text(degraded.data).strip() or "Khong du evidence live; day la nhan dinh tong quat tam thoi."
            degraded_summary = (
                "Luu y: khong du du lieu dang tin cay tu nguon live, phan hoi duoi day chi dua tren thong tin co ban. "
                "Ban can xac minh lai truoc khi su dung cho muc dich khac.\n\n"
                f"{degraded_summary}"
            )
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
            "Ban la AnalysisSkill. Nhiem vu: phan tich xu huong dua tren research evidence da co, "
            "khong bo sung fact moi ngoai evidence. Viet bang tieng Viet, ngan gon nhung ro logic.\n\n"
            f"Prompt chuan hoa: {context.normalized_prompt}\n"
            f"Task phan tich: {task_description}\n"
            f"Memory gan day:\n{context.recent_memory or '- none'}\n"
            f"Evidence tong hop:\n{evidence_block}\n\n"
            "Tra ve DUNG format 4 muc trong van ban thuong:\n"
            "1) Ket luan xu huong\n"
            "2) Lap luan chinh\n"
            "3) Dan chung da dung (moi y gan voi nguon URL cu the)\n"
            "4) Gioi han/gia dinh va muc do chac chan"
        )
        result = await self._generate(prompt)
        if not result.success:
            return result

        summary = extract_result_text(result.data).strip() or "Khong du thong tin de ket luan xu huong mot cach chac chan."
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
        description="General purpose question answering and explanation skill in Vietnamese.",
        examples=["giải thích", "tại sao", "how it works", "khái niệm"],
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
            "xin chao",
            "xin chào",
            "chao",
            "chào",
            "hello",
            "hi",
            "hey",
        )
        request_hints = (
            "giup",
            "giúp",
            "hay",
            "hãy",
            "co the",
            "có thể",
            "please",
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
            "Bạn là GeneralAnswerSkill. Trả lời ngắn gọn, tự nhiên, bằng tiếng Việt, theo đúng ngữ cảnh hội thoại.\n"
            "Quy tắc:\n"
            "- Nếu đây là greeting: trả lời thân thiện, ngắn, không lặp lại nguyên văn câu user.\n"
            "- Nếu đây là statement/context người dùng đang chia sẻ: không được chỉ echo lại câu user. Hãy phản hồi tự nhiên bằng cách ghi nhận thông tin, thể hiện tiếp nối hội thoại, và khi phù hợp thì hỏi 1 câu follow-up hữu ích hoặc gợi ý hỗ trợ liên quan.\n"
            "- Nếu đây là question/request: trả lời trực tiếp, rõ ý, tránh lan man.\n"
            "- Không bịa dữ kiện bên ngoài prompt/memory.\n"
            "- Tránh mở đầu máy móc như 'Bạn nói rằng...' hoặc chép lại nguyên câu user.\n\n"
            f"Conversation mode: {conversation_mode}\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}"
        )
        return await self._generate(prompt)


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
            "Bạn là PlanningSkill. Tạo checklist có thứ tự ưu tiên, rõ ràng, súc tích bằng tiếng Việt.\n\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}"
        )
        return await self._generate(prompt)


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
        return any(token in text for token in ("so sánh", "compare", "khác nhau", "ưu nhược"))

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", ""))
        deps_text = format_dependency_outputs(context.dependency_outputs)
        prompt = (
            "Bạn là CompareSkill. So sánh rõ ràng, có tiêu chí, ngắn gọn bằng tiếng Việt.\n\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}\n"
            f"Dependency outputs:\n{deps_text or '- none'}"
        )
        return await self._generate(prompt)


class CodeExampleSkill(BaseLLMSkill):
    metadata = SkillMetadata(
        name="code_example",
        description="Generate minimal, correct code examples or snippets based on context.",
        examples=["ví dụ code", "code example", "snippet", "mã mẫu"],
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
        return any(token in text for token in ("ví dụ code", "code", "snippet", "mã"))

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", ""))
        deps_text = format_dependency_outputs(context.dependency_outputs)
        prompt = (
            "Bạn là CodeExampleSkill. Tạo ví dụ code ngắn, đúng cú pháp, dễ hiểu. Nếu cần, giải thích ngắn sau code.\n\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Task: {task_description}\n"
            f"Dependency outputs:\n{deps_text or '- none'}"
        )
        return await self._generate(prompt)


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

    def can_handle(self, input_data: dict[str, object]) -> bool:
        _ = input_data
        return True

    @staticmethod
    def _is_insufficient_summary(text: str) -> bool:
        lowered = text.lower()
        insufficiency_hints = (
            "khong du",
            "không đủ",
            "chua co du",
            "chưa có đủ",
            "insufficient",
            "not enough data",
            "no enough data",
            "khong co du lieu",
            "không có dữ liệu",
            "gioi han",
            "giới hạn",
        )
        return any(token in lowered for token in insufficiency_hints)

    async def execute(self, context: SkillContext) -> SkillResult:
        deps_text = format_dependency_outputs(context.dependency_outputs)
        synthesis_task = str(context.input.get("description", "")).strip().lower()
        local_or_travel_synthesis = any(
            token in synthesis_task
            for token in ("verified local place", "local place", "travel", "itinerary", "địa điểm", "du lịch", "lich trinh")
        )
        research_payloads = [
            payload for payload in (parse_research_result(value) for value in context.dependency_outputs.values()) if payload is not None
        ]
        analysis_payloads = [
            payload for payload in (parse_analysis_result(value) for value in context.dependency_outputs.values()) if payload is not None
        ]

        if local_or_travel_synthesis and not research_payloads:
            return SkillResult(success=False, error="no_dependency_evidence", metadata={"error_type": "permanent"})

        if not context.dependency_outputs and not research_payloads and not analysis_payloads:
            # Fallback to pure knowledge answer when synthesis is invoked without evidence.
            fallback_prompt = (
                "Bạn là SynthesizerSkill. Không có kết quả phụ thuộc/evidence từ tool. "
                "Hãy trả lời bằng kiến thức tổng quát sẵn có, ngắn gọn, trung thực bằng tiếng Việt. "
                "Nếu có điểm không chắc chắn, nêu rõ giới hạn thay vì khẳng định tuyệt đối.\n\n"
                f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
                f"Task: {str(context.input.get('description', '')).strip() or context.normalized_prompt}"
            )
            fallback_result = await self._generate(fallback_prompt)
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
            degraded_prompt = (
                "Ban la SynthesizerSkill trong che do degraded. Toan bo dependency outputs khong thu duoc evidence live hop le. "
                "Hay tra loi ngan gon dua tren thong tin co ban, khong khang dinh tuyet doi, va neu ro can xac minh them.\n\n"
                f"Prompt chuan hoa: {context.normalized_prompt}\n"
                f"Task: {str(context.input.get('description', '')).strip() or context.normalized_prompt}"
            )
            degraded = await self._generate(degraded_prompt)
            if not degraded.success:
                return degraded

            degraded_answer = extract_result_text(degraded.data).strip() or "Khong du evidence live; day la cau tra loi tam thoi."
            degraded_answer = (
                "Tuyen bo trach nhiem: khong du du lieu dang tin cay tu cac nguon live, cau tra loi duoi day chi dua tren thong tin co ban. "
                "Ban can xac minh lai truoc khi su dung cho cac muc dich khac.\n\n"
                f"{degraded_answer}"
            )
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
            "Bạn là SynthesizerSkill. Hãy hợp nhất các kết quả trung gian thành 1 câu trả lời cuối cùng, "
            "mạch lạc, không lặp ý, bằng tiếng Việt. Nếu có dữ kiện từ research, chỉ dùng các dữ kiện có trong evidence đã dẫn nguồn. "
            "BẮT BUỘC: không được tự thêm fact ngoài evidence; khi có mâu thuẫn giữa các nguồn, phải nêu rõ xung đột và mức độ chắc chắn. "
            "BẮT BUỘC: giữ hoặc bổ sung phần Nguon tham khao với URL đã có. "
            "BẮT BUỘC: có mục 'Dan chung da su dung' và mỗi ý phải kèm URL nguồn tương ứng.\n\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Dependency outputs:\n{deps_text or '- none'}\n"
            f"Research evidence:\n{evidence_block or '- none'}\n"
            f"Analysis evidence:\n{analysis_block or '- none'}"
        )
        result = await self._generate(prompt)
        if not result.success:
            return result

        answer_text = extract_result_text(result.data).strip()
        if research_payloads:
            sources = [source for payload in research_payloads for source in payload.sources]
            source_block = format_sources_for_user(sources)
            if source_block and source_block not in answer_text:
                answer_text = f"{answer_text}\n\nNguon tham khao:\n{source_block}"
            unique_urls: list[str] = []
            for source in sources:
                if source.url not in unique_urls:
                    unique_urls.append(source.url)
            avg_confidence = sum(payload.confidence for payload in research_payloads) / max(len(research_payloads), 1)
            insufficient_count = sum(1 for payload in research_payloads if self._is_insufficient_summary(payload.summary))
            if insufficient_count > 0:
                insufficient_penalty = min(0.25 + insufficient_count * 0.12, 0.65)
                avg_confidence = max(0.15, avg_confidence - insufficient_penalty)
                answer_text = (
                    "Luu y: bo evidence hien tai con thieu du lieu truc tiep cho mot so khia canh, "
                    "vi vay muc do chac chan da duoc giam de tranh ket luan qua muc.\n\n"
                    f"{answer_text}"
                )
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
                    "Luu y: cac ket luan duoi day co tinh chat tam thoi do evidence con xung dot hoac do tin cay chua cao.\n\n"
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
            "Bạn là FusionSkill. Nhiệm vụ: tạo câu trả lời cuối cùng từ 2 nguồn đã thu thập song song.\n"
            "Ưu tiên: nếu có evidence từ research (có nguồn cụ thể) → dùng làm nền tảng chính. "
            "Nếu LLM direct answer bổ sung context hữu ích → tích hợp không lặp ý.\n"
            "Không được thêm fact mới ngoài những gì đã có. Viết tự nhiên bằng tiếng Việt.\n\n"
            f"Prompt gốc: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Decision: {decision}\n"
            f"Nguồn chính:\n{primary_text or '- none'}"
            f"{blend_section}"
        )
        result = await self._generate(prompt)
        if not result.success:
            return result

        answer_text = extract_result_text(result.data).strip() or primary_text or "Không đủ evidence để trả lời."
        if sources:
            source_block = format_sources_for_user(sources)
            if source_block and source_block not in answer_text:
                answer_text = f"{answer_text}\n\nNguồn tham khảo:\n{source_block}"
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
    )

    _BUDGET_HINTS = (
        "rẻ",
        "re",
        "bình dân",
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

    async def execute(self, context: SkillContext) -> SkillResult:
        query = str(context.input.get("description", "")).strip()
        started_at = time.perf_counter()

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

        seen_titles: set[str] = set()
        verified: list[dict[str, object]] = []
        for source in local_payload.sources:
            normalized_title = re.sub(r"\s+", " ", source.title.strip().lower())
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
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

        verified_places: list[dict[str, object]] = []
        if isinstance(verified_payload, dict):
            raw_places = verified_payload.get("verified_places")
            if isinstance(raw_places, list):
                verified_places = [item for item in raw_places if isinstance(item, dict)]

        if not verified_places or str(verified_text).strip().startswith("ERROR:"):
            return SkillResult(
                success=False,
                error="no_verified_places_for_itinerary",
                metadata={"error_type": "permanent", "intent": "travel_planning"},
            )

        llm_prompt = (
            "Bạn là ItineraryPlannerSkill. Tạo lịch trình ngắn gọn, thực dụng, theo khung giờ sáng/chiều/tối. "
            "Chỉ dùng địa điểm có trong evidence, không bịa thêm địa điểm mới. Ưu tiên tiếng Việt.\n\n"
            f"Prompt người dùng: {prompt}\n"
            f"Geo constraints: {geo_text or '- none'}\n"
            f"Verified places:\n{verified_text or '- none'}\n"
        )

        result = await self._generate(llm_prompt)
        if not result.success:
            return result

        itinerary = extract_result_text(result.data).strip() or "Chưa đủ dữ liệu để tạo lịch trình chi tiết."
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
            },
        )
