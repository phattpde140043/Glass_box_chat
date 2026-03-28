from __future__ import annotations

import re

from ..search_providers import OpenMeteoWeatherProvider
from .tool_gateway import BaseTool, ToolInput, ToolOutput


class WeatherTool(BaseTool):
    """Live weather tool using Open-Meteo (no API key required)."""
    
    def __init__(self, timeout_seconds: float = 4.0) -> None:
        super().__init__(
            name="weather",
            description="Get current weather information for a location using Open-Meteo.",
            timeout_seconds=timeout_seconds,
            max_retries=1,
        )
        self._provider = OpenMeteoWeatherProvider(timeout_seconds=timeout_seconds)

    @staticmethod
    def _extract_float(text: str, key: str) -> float | None:
        match = re.search(rf"{re.escape(key)}=([-+]?[0-9]*\.?[0-9]+)", text)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _extract_weather_label(snippet: str) -> str | None:
        match = re.search(r"weather=([^,.]+)", snippet)
        if not match:
            return None
        return match.group(1).strip()

    @staticmethod
    def _build_weather_schema(documents: list[object], query: str) -> dict[str, object]:
        docs = [doc for doc in documents if hasattr(doc, "title") and hasattr(doc, "snippet")]
        if not docs:
            return {
                "type": "weather",
                "mode": "unknown",
                "query": query,
                "location": None,
                "current": None,
                "forecast": [],
            }

        first = docs[0]
        first_title = str(getattr(first, "title", ""))
        mode = "forecast" if "forecast" in first_title.lower() else "current"

        location_match = re.search(r"for\s+(.+?)(?:\s+on\s+\d{4}-\d{2}-\d{2})?$", first_title, flags=re.IGNORECASE)
        location = location_match.group(1).strip() if location_match else None

        forecast_items: list[dict[str, object]] = []
        current_item: dict[str, object] | None = None

        for doc in docs:
            title = str(getattr(doc, "title", ""))
            snippet = str(getattr(doc, "snippet", ""))
            published_at = getattr(doc, "published_at", None)

            temp_min = WeatherTool._extract_float(snippet, "temp_min")
            temp_max = WeatherTool._extract_float(snippet, "temp_max")
            rain_prob = WeatherTool._extract_float(snippet, "rain_probability_max")
            temp = WeatherTool._extract_float(snippet, "temperature")
            wind = WeatherTool._extract_float(snippet, "wind")
            weather_label = WeatherTool._extract_weather_label(snippet)

            if "forecast" in title.lower():
                forecast_items.append(
                    {
                        "date": published_at,
                        "temp_min": temp_min,
                        "temp_max": temp_max,
                        "rain_probability_max": rain_prob,
                        "weather": weather_label,
                    }
                )
            else:
                current_item = {
                    "observed_at": published_at,
                    "temperature": temp,
                    "wind_kmh": wind,
                    "weather": weather_label,
                }

        if mode == "forecast" and not forecast_items:
            mode = "current"
        if mode == "current" and forecast_items:
            mode = "forecast"

        return {
            "type": "weather",
            "mode": mode,
            "query": query,
            "location": location,
            "current": current_item,
            "forecast": forecast_items,
        }
    
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Execute weather lookup and return formatted result."""
        async def _get_weather(inp: ToolInput) -> ToolOutput:
            # Ask provider for multiple docs to support forecast display.
            batch = await self._provider.search(inp.query, limit=max(1, inp.limit))
            
            if not batch.documents:
                return ToolOutput(
                    success=False,
                    content="Could not find weather data for the specified location.",
                    confidence=0.0,
                )
            
            doc = batch.documents[0]
            weather_schema = self._build_weather_schema(batch.documents, inp.query)
            mode = str(weather_schema.get("mode", "current"))
            content = (
                f"Weather Information\n\n"
                f"Location: {doc.title}\n"
                f"Details: {doc.snippet}\n"
                f"Mode: {mode}\n"
                f"Source: {doc.url}"
            )
            
            return ToolOutput(
                success=True,
                content=content,
                source_url=doc.url,
                data={
                    # Structured schema for deterministic downstream reasoning.
                    "weather": weather_schema,
                    # Backward-compatible document list for ResearchSkill conversion.
                    "documents": [
                        {
                            "title": item.title,
                            "snippet": item.snippet,
                            "url": item.url,
                            "freshness": item.freshness,
                            "published_at": item.published_at,
                            "reliability": item.reliability,
                        }
                        for item in batch.documents
                    ],
                    "title": doc.title,
                    "snippet": doc.snippet,
                    "url": doc.url,
                    "published_at": doc.published_at,
                    "freshness": doc.freshness,
                },
                confidence=batch.confidence,
                metadata={
                    "provider": batch.provider,
                    "intent": batch.intent,
                    "published_at": doc.published_at,
                    "weather_mode": mode,
                    "source_count": len(batch.documents),
                },
            )
        
        return await self.execute_with_retry(tool_input, _get_weather)
