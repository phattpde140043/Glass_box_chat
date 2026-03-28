from __future__ import annotations

import asyncio

from ..search_providers import DuckDuckGoSearchProvider
from .tool_gateway import BaseTool, ToolInput, ToolOutput


class WebSearchTool(BaseTool):
    """Live web search tool using DuckDuckGo."""
    
    def __init__(self, timeout_seconds: float = 4.0) -> None:
        super().__init__(
            name="web_search",
            description="Search the web for current information using DuckDuckGo.",
            timeout_seconds=timeout_seconds,
            max_retries=2,
        )
        self._provider = DuckDuckGoSearchProvider(timeout_seconds=timeout_seconds)
    
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Execute web search and return formatted result."""
        async def _search(inp: ToolInput) -> ToolOutput:
            batch = await self._provider.search(inp.query, limit=inp.limit)
            
            if not batch.documents:
                return ToolOutput(
                    success=False,
                    content="No results found.",
                    confidence=0.0,
                )
            
            content_lines = [f"Web Search Results for: {inp.query}", ""]
            for idx, doc in enumerate(batch.documents, 1):
                content_lines.append(
                    f"{idx}. {doc.title}\n"
                    f"   URL: {doc.url}\n"
                    f"   {doc.snippet}\n"
                )
            
            content = "\n".join(content_lines)
            
            return ToolOutput(
                success=True,
                content=content,
                source_url=batch.documents[0].url if batch.documents else None,
                data={
                    "documents": [
                        {
                            "title": doc.title,
                            "url": doc.url,
                            "snippet": doc.snippet,
                            "freshness": doc.freshness,
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
        
        return await self.execute_with_retry(tool_input, _search)
