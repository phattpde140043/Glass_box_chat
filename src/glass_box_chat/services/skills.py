from __future__ import annotations

import asyncio
import time
from typing import Callable, Protocol

from .planner import needs_research_text
from .result_formatting import (
    EvidenceModel,
    ResearchResultEnvelopeModel,
    ResearchSourceModel,
    extract_result_text,
    format_dependency_outputs,
    format_sources_for_user,
    parse_research_result,
)
from .runtime_resilience import classify_error
from .search_providers import SearchDocument, SearchProvider, SearchResultBatch
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

    def can_handle(self, input_data: dict[str, object]) -> bool:
        return needs_research_text(str(input_data.get("description", "")))

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
        
        documents = search_batch.documents
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
        return any(token in text for token in self._MARKET_HINTS)

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

        market_data = {}
        tool_documents: list[dict[str, object]] = []
        if isinstance(tool_result.data, dict):
            market_raw = tool_result.data.get("market")
            if isinstance(market_raw, dict):
                market_data = market_raw
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

    async def execute(self, context: SkillContext) -> SkillResult:
        task_description = str(context.input.get("description", ""))
        prompt = (
            "Bạn là GeneralAnswerSkill. Trả lời ngắn gọn, đúng trọng tâm, bằng tiếng Việt.\n\n"
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

    async def execute(self, context: SkillContext) -> SkillResult:
        deps_text = format_dependency_outputs(context.dependency_outputs)
        research_payloads = [
            payload for payload in (parse_research_result(value) for value in context.dependency_outputs.values()) if payload is not None
        ]

        if not context.dependency_outputs and not research_payloads:
            # Fallback to pure knowledge answer when synthesis is invoked without evidence.
            fallback_prompt = (
                "Bạn là SynthesizerSkill. Không có kết quả phụ thuộc/evidence từ tool. "
                "Hãy trả lời bằng kiến thức tổng quát sẵn có, ngắn gọn, trung thực bằng tiếng Việt. "
                "Nếu có điểm không chắc chắn, nêu rõ giới hạn thay vì khẳng định tuyệt đối.\n\n"
                f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
                f"Task: {str(context.input.get('description', '')).strip() or context.normalized_prompt}"
            )
            return await self._generate(fallback_prompt)

        evidence_block = "\n\n".join(
            [
                f"Research summary: {payload.summary}\nSources:\n{format_sources_for_user(payload.sources) or '- none'}"
                for payload in research_payloads
            ]
        )
        prompt = (
            "Bạn là SynthesizerSkill. Hãy hợp nhất các kết quả trung gian thành 1 câu trả lời cuối cùng, "
            "mạch lạc, không lặp ý, bằng tiếng Việt. Nếu có dữ kiện từ research, chỉ dùng các dữ kiện có trong evidence đã dẫn nguồn. "
            "BẮT BUỘC: không được tự thêm fact ngoài evidence; khi có mâu thuẫn giữa các nguồn, phải nêu rõ xung đột và mức độ chắc chắn. "
            "BẮT BUỘC: giữ hoặc bổ sung phần Nguon tham khao với URL đã có.\n\n"
            f"Prompt chuẩn hóa: {context.normalized_prompt}\n"
            f"Memory gần đây:\n{context.recent_memory or '- none'}\n"
            f"Dependency outputs:\n{deps_text or '- none'}\n"
            f"Research evidence:\n{evidence_block or '- none'}"
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
        result.data = answer_text
        return result
