from __future__ import annotations

import os
from collections.abc import Callable

from .search_providers import (
    CommodityReferenceProvider,
    DuckDuckGoSearchProvider,
    FallbackSearchProvider,
    MockSearchProvider,
    NewsAPIProvider,
    OpenStreetMapLocalProvider,
    OpenMeteoWeatherProvider,
    PolicyDrivenSearchProvider,
    SerpAPIProvider,
    SearchProvider,
    ToolPolicy,
)


def build_default_search_provider() -> SearchProvider:
    mode = os.getenv("RESEARCH_MODE", "hybrid").strip().lower() or "hybrid"
    timeout_seconds = float(os.getenv("SEARCH_HTTP_TIMEOUT_SECONDS", "3.0"))
    provider_timeout_seconds = float(os.getenv("SEARCH_PROVIDER_TIMEOUT_SECONDS", "4.0"))

    duck_provider = DuckDuckGoSearchProvider(timeout_seconds=timeout_seconds)
    weather_provider = OpenMeteoWeatherProvider(timeout_seconds=timeout_seconds)
    newsapi_key = os.getenv("NEWSAPI_API_KEY", "").strip()
    serpapi_key = os.getenv("SERPAPI_API_KEY", "").strip()
    news_provider = NewsAPIProvider(api_key=newsapi_key, timeout_seconds=timeout_seconds)
    serp_provider = SerpAPIProvider(api_key=serpapi_key, timeout_seconds=timeout_seconds)
    commodity_provider = CommodityReferenceProvider(timeout_seconds=timeout_seconds)
    osm_local_provider = OpenStreetMapLocalProvider(timeout_seconds=timeout_seconds)
    mock_provider = MockSearchProvider()

    if mode == "legacy":
        return FallbackSearchProvider(duck_provider, mock_provider)

    policy = ToolPolicy(mode=mode)
    providers_dict: dict[str, SearchProvider] = {
        weather_provider.name: weather_provider,
        duck_provider.name: duck_provider,
        news_provider.name: news_provider,
        serp_provider.name: serp_provider,
        commodity_provider.name: commodity_provider,
        osm_local_provider.name: osm_local_provider,
    }
    return PolicyDrivenSearchProvider(
        providers=providers_dict,
        policy=policy,
        fallback=mock_provider,
        provider_timeout_seconds=provider_timeout_seconds,
    )


def build_default_llm_backend(
    model: str,
    claude_backend_factory: Callable[..., object],
    gemini_backend_factory: Callable[..., object],
) -> object:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "claude" if model.lower().startswith("claude-") else "gemini"

    if provider == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")
        return claude_backend_factory(api_key=api_key)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    return gemini_backend_factory(api_key=api_key)
