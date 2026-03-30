from __future__ import annotations

import os

from ..search_providers import NewsAPIProvider
from .tool_gateway import BaseTool, ToolInput, ToolOutput


class NewsAPITool(BaseTool):
    """Live news search tool using NewsAPI.org."""
    
    def __init__(self, timeout_seconds: float = 4.0) -> None:
        super().__init__(
            name="news_api",
            description="Search for latest news articles using NewsAPI. Requires NEWSAPI_API_KEY environment variable.",
            timeout_seconds=timeout_seconds,
            max_retries=2,
        )
        api_key = os.getenv("NEWSAPI_API_KEY", "").strip()
        self._provider = NewsAPIProvider(api_key=api_key, timeout_seconds=timeout_seconds)
    
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Execute news search and return formatted result."""
        async def _search(inp: ToolInput) -> ToolOutput:
            batch = await self._provider.search(inp.query, limit=inp.limit)
            
            if not batch.documents:
                return ToolOutput(
                    success=False,
                    content="No news articles found. Verify NEWSAPI_API_KEY is set and valid.",
                    confidence=0.0,
                )
            
            content_lines = [f"News Results for: {inp.query}", ""]
            for idx, doc in enumerate(batch.documents, 1):
                published = f" (Published: {doc.published_at})" if doc.published_at else ""
                content_lines.append(
                    f"{idx}. {doc.title}\n"
                    f"   Source: {doc.provider}{published}\n"
                    f"   URL: {doc.url}\n"
                    f"   {doc.snippet}\n"
                )
            
            content = "\n".join(content_lines)
            
            return ToolOutput(
                success=True,
                content=content,
                source_url=batch.documents[0].url if batch.documents else None,
                data={
                    "articles": [
                        {
                            "title": doc.title,
                            "url": doc.url,
                            "snippet": doc.snippet,
                            "source": doc.provider,
                            "published_at": doc.published_at,
                            "reliability": doc.reliability,
                        }
                        for doc in batch.documents
                    ],
                },
                confidence=batch.confidence,
                metadata={
                    "provider": batch.provider,
                    "article_count": len(batch.documents),
                    "intent": batch.intent,
                    "fallback_used": batch.fallback_used,
                },
            )
        
        return await self.execute_with_retry(tool_input, _search)
