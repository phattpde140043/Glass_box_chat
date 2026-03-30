from __future__ import annotations

from ..search_providers import DuckDuckGoSearchProvider, SearchResultBatch, SerpAPIProvider
from .tool_gateway import BaseTool, ToolInput, ToolOutput


class LocalSearchTool(BaseTool):
    """Local place search tool for restaurants/hotels/attractions.

    Uses SerpAPI when available for richer local results and falls back to
    DuckDuckGo for broad web coverage.
    """

    def __init__(self, timeout_seconds: float = 4.0) -> None:
        super().__init__(
            name="local_search",
            description="Search local places (restaurant/hotel/attraction) with location-aware hints.",
            timeout_seconds=timeout_seconds,
            max_retries=2,
        )
        self._serp_provider = SerpAPIProvider(timeout_seconds=timeout_seconds)
        self._fallback_provider = DuckDuckGoSearchProvider(timeout_seconds=timeout_seconds)

    @staticmethod
    def _expand_query(query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ("restaurant", "nhà hàng", "nha hang", "quán ăn", "quan an")):
            return f"{query} best places reviews map"
        if any(token in lowered for token in ("hotel", "khách sạn", "khach san", "resort", "homestay")):
            return f"{query} booking reviews location"
        if any(token in lowered for token in ("du lịch", "du lich", "travel", "địa điểm", "dia diem", "attraction")):
            return f"{query} things to do guide"
        if any(token in lowered for token in ("food", "foods", "eat", "eating", "eating out", "dining", "dine", "breakfast", "lunch", "dinner", "brunch", "meal", "traditional", "street food", "ăn uống", "an uong", "ăn gì", "an gi", "ăn gì ngon", "ăn ở đâu", "thứ ăn", "chu an", "món ăn", "mon an")):
            return f"{query} restaurant best places reviews"
        return query

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        async def _search(inp: ToolInput) -> ToolOutput:
            query = self._expand_query(inp.query)
            batch = await self._serp_provider.search(query, limit=inp.limit)
            if not batch.documents:
                batch = await self._fallback_provider.search(query, limit=inp.limit)

            if not batch.documents:
                return ToolOutput(success=False, content="No local results found.", confidence=0.0)

            return self._to_output(inp.query, batch)

        return await self.execute_with_retry(tool_input, _search)

    def _to_output(self, original_query: str, batch: SearchResultBatch) -> ToolOutput:
        lines = [f"Local results for: {original_query}", ""]
        for idx, doc in enumerate(batch.documents, 1):
            lines.append(
                f"{idx}. {doc.title}\n"
                f"   URL: {doc.url}\n"
                f"   {doc.snippet}\n"
            )

        return ToolOutput(
            success=True,
            content="\n".join(lines),
            source_url=batch.documents[0].url,
            data={
                "documents": [
                    {
                        "title": doc.title,
                        "url": doc.url,
                        "snippet": doc.snippet,
                        "freshness": doc.freshness,
                        "provider": doc.provider,
                        "reliability": doc.reliability,
                    }
                    for doc in batch.documents
                ],
            },
            confidence=batch.confidence,
            metadata={
                "provider": batch.provider,
                "source_count": len(batch.documents),
                "intent": batch.intent,
                "fallback_used": batch.fallback_used,
            },
        )
