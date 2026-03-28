from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolSuggestion:
    """Tool suggestion result for routing to specific tool."""
    tool_name: str
    confidence: float
    reason: str
    is_fallback: bool = False


class ToolAnalyzer:
    """Analyze user input to suggest appropriate tools for execution."""

    MARKET_HINTS = (
        "gia vang",
        "giá vàng",
        "gold price",
        "xau",
        "xauusd",
        "crypto price",
        "bitcoin price",
        "btc",
        "ethereum",
        "eth",
        "ty gia",
        "tỷ giá",
        "exchange rate",
        "forex",
    )
    
    @staticmethod
    def suggest_tool(query: str, context: str = "") -> ToolSuggestion:
        """Analyze query and suggest the best tool to handle it."""
        combined_text = f"{query} {context}".lower()
        
        # URL detection (highest priority)
        if query.startswith(("http://", "https://", "www.")):
            return ToolSuggestion(
                tool_name="fetch_page",
                confidence=0.90,
                reason=f"Direct URL provided: '{query[:60]}'",
            )
        
        # Weather
        if any(kw in combined_text for kw in ["weather", "thời tiết", "forecast", "nhiệt độ"]):
            return ToolSuggestion(tool_name="weather", confidence=0.88, reason="Weather query detected")

        # Market data (gold/crypto/fx)
        if any(kw in combined_text for kw in ToolAnalyzer.MARKET_HINTS):
            return ToolSuggestion(tool_name="finance", confidence=0.96, reason="Market price query detected")
        
        # News
        if any(kw in combined_text for kw in ["news", "tin tức", "headline", "mới nhất"]):
            return ToolSuggestion(tool_name="news_api", confidence=0.86, reason="News query detected")
        
        # Calculator
        calc_keywords = ["calculate", "tính", "math", "toán", "equation"]
        has_calc_keyword = any(kw in combined_text for kw in calc_keywords)
        has_url = "http://" in query or "https://" in query
        has_math_op = not has_url and any(op in query for op in ["+", "-", "*", "^", "%"])
        
        if has_math_op or has_calc_keyword:
            return ToolSuggestion(
                tool_name="calculator",
                confidence=0.95 if has_math_op else 0.82,
                reason="Math calculation detected"
            )
        
        # Fetch page
        if any(kw in combined_text for kw in ["fetch", "url", "website", "content from", "read"]):
            return ToolSuggestion(tool_name="fetch_page", confidence=0.83, reason="Page fetch requested")
        
        # Default
        return ToolSuggestion(
            tool_name="web_search",
            confidence=0.65,
            reason="General query",
            is_fallback=True,
        )
    
    @staticmethod
    def multi_suggest(query: str, top_k: int = 3) -> list[ToolSuggestion]:
        """Suggest multiple tools ranked by confidence."""
        primary = ToolAnalyzer.suggest_tool(query)
        suggestions = [primary]
        
        if primary.tool_name == "calculator":
            suggestions.append(ToolSuggestion(
                tool_name="web_search",
                confidence=0.40,
                reason="Additional context",
            ))
        elif primary.tool_name == "finance":
            suggestions.append(
                ToolSuggestion(
                    tool_name="news_api",
                    confidence=0.45,
                    reason="Optional market news context",
                )
            )
        
        return suggestions[:top_k]
