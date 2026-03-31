from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..search_providers import OpenMeteoWeatherProvider
from .tool_gateway import BaseTool, ToolInput, ToolOutput

if TYPE_CHECKING:
    from ..search_providers import PolicyDrivenSearchProvider


class WeatherTool(BaseTool):
    """Weather adapter that routes through the shared provider orchestration.

    When a ``PolicyDrivenSearchProvider`` is injected at construction time the
    tool uses ``search_with_intent("weather_live")`` so it benefits from the
    same circuit-breaker, speculative-execution, and confidence-scoring logic
    as every other search path.  The chain is:
        weather_open_meteo → duckduckgo (per ToolPolicy)

    Three outcome tiers are produced:
    1. Structured success  – provider == ``weather_open_meteo``, returns
       fully-parsed numeric weather payload.
    2. Evidence-only degraded success – Open-Meteo failed, DuckDuckGo had
       documents; returns grounded evidence with ``mode=evidence_only``.
    3. Hard tool failure – no documents from any provider; returns
       ``success=False, error=insufficient_live_evidence``.

    In all cases ``metadata.tool_fully_orchestrated=True`` is set so that
    ``ResearchSkill`` skips the duplicate fallback search.

    If no search provider is injected the tool falls back to a direct
    ``OpenMeteoWeatherProvider`` call (standalone / test mode).
    """

    def __init__(
        self,
        timeout_seconds: float = 4.0,
        search_provider: PolicyDrivenSearchProvider | None = None,
    ) -> None:
        super().__init__(
            name="weather",
            description="Get current weather information for a location using Open-Meteo.",
            timeout_seconds=timeout_seconds,
            max_retries=1,
        )
        self._search_provider = search_provider
        # Standalone fallback used only when no orchestrated provider is wired.
        self._standalone_provider = OpenMeteoWeatherProvider(timeout_seconds=timeout_seconds)

    # ------------------------------------------------------------------
    # Schema helpers (unchanged from original)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Outcome builders
    # ------------------------------------------------------------------

    def _build_structured_success(self, batch: object, query: str) -> ToolOutput:
        """Outcome 1 – Open-Meteo returned parseable numeric data."""
        documents = list(getattr(batch, "documents", []))
        doc = documents[0]
        weather_schema = self._build_weather_schema(documents, query)
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
                "weather": weather_schema,
                "documents": [
                    {
                        "title": item.title,
                        "snippet": item.snippet,
                        "url": item.url,
                        "freshness": item.freshness,
                        "published_at": item.published_at,
                        "reliability": item.reliability,
                    }
                    for item in documents
                ],
                "title": doc.title,
                "snippet": doc.snippet,
                "url": doc.url,
                "published_at": doc.published_at,
                "freshness": doc.freshness,
            },
            confidence=getattr(batch, "confidence", 0.8),
            metadata={
                "provider": getattr(batch, "provider", "weather_open_meteo"),
                "intent": getattr(batch, "intent", "weather_live"),
                "published_at": doc.published_at,
                "weather_mode": mode,
                "source_count": len(documents),
                "fallback_used": False,
                "providers_tried": ",".join(getattr(batch, "providers_tried", []) or []),
                "tool_fully_orchestrated": True,
            },
        )

    def _build_degraded_success(self, batch: object, query: str) -> ToolOutput:
        """Outcome 2 – Open-Meteo failed; DuckDuckGo (or another provider)
        supplied web evidence.  Returns grounded documents without pretending
        to be structured numeric forecast."""
        documents = list(getattr(batch, "documents", []))
        doc = documents[0]
        weather_schema = {
            "type": "weather",
            "mode": "evidence_only",
            "query": query,
            "location": None,
            "current": None,
            "forecast": [],
        }
        content = (
            f"Weather evidence (web fallback)\n\n"
            f"Source: {doc.title}\n"
            f"Details: {doc.snippet}\n"
            f"URL: {doc.url}"
        )
        confidence = float(getattr(batch, "confidence", 0.3))
        return ToolOutput(
            success=True,
            content=content,
            source_url=doc.url,
            data={
                "weather": weather_schema,
                "documents": [
                    {
                        "title": item.title,
                        "snippet": item.snippet,
                        "url": item.url,
                        "freshness": item.freshness,
                        "published_at": item.published_at,
                        "reliability": item.reliability,
                    }
                    for item in documents
                ],
                "title": doc.title,
                "snippet": doc.snippet,
                "url": doc.url,
                "published_at": doc.published_at,
                "freshness": doc.freshness,
            },
            confidence=max(confidence, 0.1),
            metadata={
                "provider": getattr(batch, "provider", "duckduckgo"),
                "intent": getattr(batch, "intent", "weather_live"),
                "published_at": doc.published_at,
                "weather_mode": "evidence_only",
                "source_count": len(documents),
                "fallback_used": True,
                "providers_tried": ",".join(getattr(batch, "providers_tried", []) or []),
                "quality_tier": "web_fallback",
                "tool_fully_orchestrated": True,
            },
        )

    @staticmethod
    def _build_hard_failure(batch: object) -> ToolOutput:
        """Outcome 3 – every provider in the chain returned no documents."""
        providers_tried = ",".join(getattr(batch, "providers_tried", []) or [])
        return ToolOutput(
            success=False,
            content="No live weather data could be retrieved from any provider.",
            confidence=0.0,
            error="insufficient_live_evidence",
            metadata={
                "provider": "none",
                "source_count": 0,
                "providers_tried": providers_tried,
                "fallback_used": getattr(batch, "fallback_used", False),
                "tool_fully_orchestrated": True,
            },
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Execute weather lookup via orchestrated provider chain."""

        async def _get_weather(inp: ToolInput) -> ToolOutput:
            if self._search_provider is not None:
                # Orchestrated path: force weather_live intent so implicit
                # queries like "picnic tomorrow" still hit the right chain.
                batch = await self._search_provider.search_with_intent(
                    inp.query,
                    limit=max(1, inp.limit),
                    intent_override="weather_live",
                )
            else:
                # Standalone / test-mode path: direct Open-Meteo call.
                batch = await self._standalone_provider.search(inp.query, limit=max(1, inp.limit))

            if not batch.documents:
                return self._build_hard_failure(batch)

            # Distinguish structured (Open-Meteo) from degraded (web) success.
            provider = getattr(batch, "provider", "") or ""
            if provider == "weather_open_meteo":
                return self._build_structured_success(batch, inp.query)
            return self._build_degraded_success(batch, inp.query)

        return await self.execute_with_retry(tool_input, _get_weather)

