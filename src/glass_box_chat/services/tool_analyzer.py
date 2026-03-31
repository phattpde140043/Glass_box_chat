from __future__ import annotations

from dataclasses import dataclass
import re


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
        "gold price",
        "xau",
        "xauusd",
        "crypto price",
        "bitcoin price",
        "btc",
        "ethereum",
        "eth",
        "exchange rate",
        "forex",
    )

    LOCAL_DISCOVERY_HINTS = (
        "restaurant",
        "restaurants",
        "hotel",
        "hotels",
        "resort",
        "resorts",
        "homestay",
        "homestays",
        "travel",
        "trip",
        "beach",
        "attraction",
        "attractions",
        "things to do",
        "near me",
    )

    @staticmethod
    def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
        lowered = text.lower()
        tokens = {token for token in re.split(r"[^\w]+", lowered) if token}
        for hint in hints:
            normalized_hint = hint.lower()
            if " " in normalized_hint:
                if normalized_hint in lowered:
                    return True
                continue
            if normalized_hint in tokens:
                return True
        return False
    
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
        if any(kw in combined_text for kw in ["weather", "forecast", "temperature"]):
            return ToolSuggestion(tool_name="weather", confidence=0.88, reason="Weather query detected")

        # Market data (gold/crypto/fx)
        if ToolAnalyzer._contains_hint(combined_text, ToolAnalyzer.MARKET_HINTS):
            return ToolSuggestion(tool_name="finance", confidence=0.96, reason="Market price query detected")
        
        # News
        if any(kw in combined_text for kw in ["news", "headline", "latest"]):
            return ToolSuggestion(tool_name="news_api", confidence=0.86, reason="News query detected")

        # Local/travel discovery
        if ToolAnalyzer._contains_hint(combined_text, ToolAnalyzer.LOCAL_DISCOVERY_HINTS):
            return ToolSuggestion(
                tool_name="local_search",
                confidence=0.9,
                reason="Local discovery query detected",
            )
        
        # Calculator
        calc_keywords = ["calculate", "math", "equation"]
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
        elif primary.tool_name == "local_search":
            suggestions.append(
                ToolSuggestion(
                    tool_name="web_search",
                    confidence=0.4,
                    reason="Additional supporting links",
                )
            )
        
        return suggestions[:top_k]
