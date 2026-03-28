from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from .runtime_resilience import CircuitBreaker


@dataclass
class SearchDocument:
    title: str
    snippet: str
    url: str
    freshness: str
    published_at: str | None = None
    reliability: float = 0.55
    provider: str = "unknown"


@dataclass
class SearchResultBatch:
    provider: str
    documents: list[SearchDocument]
    fallback_used: bool = False
    intent: str = "general_research"
    confidence: float = 0.5
    latency_ms: int = 0
    providers_tried: list[str] | None = None
    cache_ttl_seconds: int = 0


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch: ...


SearchIntent = Literal["weather_live", "news_live", "market_live", "general_research"]


def detect_search_intent(query: str) -> SearchIntent:
    lowered = query.lower()
    if any(token in lowered for token in ("weather", "thời tiết", "thoi tiet", "forecast", "nhiệt độ", "nhiet do")):
        return "weather_live"
    if any(token in lowered for token in ("news", "tin tức", "tin tuc", "headline", "mới nhất", "moi nhat")):
        return "news_live"
    if any(token in lowered for token in ("stock", "market", "crypto", "gia vang", "chứng khoán", "chung khoan")):
        return "market_live"
    return "general_research"


class ToolPolicy:
    """Select provider strategy by intent, mode, and provider health."""

    def __init__(self, mode: str = "hybrid") -> None:
        self._mode = mode.strip().lower() or "hybrid"
        self._cache_policy_by_intent = {
            "weather_live": 30,
            "news_live": 120,
            "market_live": 45,
            "general_research": 600,
        }

    @property
    def mode(self) -> str:
        return self._mode

    def cache_ttl_seconds(self, intent: SearchIntent) -> int:
        return self._cache_policy_by_intent.get(intent, 180)

    def should_use_mock_only(self) -> bool:
        return self._mode == "demo"

    def allow_mock_fallback(self) -> bool:
        if self._mode == "live":
            return os.getenv("RESEARCH_ALLOW_MOCK_FALLBACK", "false").strip().lower() in ("1", "true", "yes", "on")
        return True

    def provider_candidates(self, intent: SearchIntent) -> list[str]:
        if self._mode == "demo":
            return ["mock"]
        if intent == "weather_live":
            return ["weather_open_meteo", "duckduckgo"]
        if intent == "news_live":
            return ["newsapi", "duckduckgo"]
        if intent == "market_live":
            return ["serpapi", "duckduckgo"]
        return ["duckduckgo"]

    def speculative_enabled(self, intent: SearchIntent) -> bool:
        return self._mode in ("live", "hybrid") and intent in ("weather_live", "news_live", "market_live")


class MockSearchProvider:
    name = "mock"

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        lowered = query.lower()
        if "đà nẵng" in lowered and any(token in lowered for token in ("weather", "thời tiết", "hôm nay", "today")):
            docs = [
                SearchDocument(
                    title="Da Nang weather snapshot",
                    snippet="Điều kiện thời tiết tham khảo cho Đà Nẵng: trời ấm, có thể nắng xen mây, cần kiểm tra nguồn thời tiết chính thức để có số liệu mới nhất.",
                    url="https://weather.example.local/da-nang",
                    freshness="today",
                    reliability=0.35,
                    provider=self.name,
                ),
                SearchDocument(
                    title="Regional forecast advisory",
                    snippet="Khu vực miền Trung có biến động thời tiết trong ngày, nên ưu tiên theo dõi dự báo ngắn hạn trước khi ra quyết định di chuyển.",
                    url="https://forecast.example.local/central-vietnam",
                    freshness="today",
                    reliability=0.32,
                    provider=self.name,
                ),
            ]
        elif any(token in lowered for token in ("news", "tin tức", "latest", "mới nhất")):
            docs = [
                SearchDocument(
                    title="Latest topic summary",
                    snippet="Có nhiều cập nhật gần đây từ các nguồn tổng hợp. Cần đối chiếu nhiều nguồn trước khi kết luận.",
                    url="https://news.example.local/latest",
                    freshness="latest",
                    reliability=0.3,
                    provider=self.name,
                ),
                SearchDocument(
                    title="Secondary source digest",
                    snippet="Nguồn thứ cấp cung cấp tóm tắt ngắn, nhưng cần nguồn gốc ban đầu để xác nhận dữ liệu.",
                    url="https://digest.example.local/summary",
                    freshness="latest",
                    reliability=0.28,
                    provider=self.name,
                ),
            ]
        else:
            docs = [
                SearchDocument(
                    title="Research summary",
                    snippet=f"Kết quả nghiên cứu mô phỏng cho truy vấn: {query}",
                    url="https://research.example.local/mock-result",
                    freshness="recent",
                    reliability=0.25,
                    provider=self.name,
                ),
                SearchDocument(
                    title="Supporting source",
                    snippet="Nguồn hỗ trợ cung cấp bối cảnh và vài dữ kiện kiểm chứng ở mức demo.",
                    url="https://research.example.local/supporting-source",
                    freshness="recent",
                    reliability=0.25,
                    provider=self.name,
                ),
            ]

        return SearchResultBatch(provider=self.name, documents=docs[:limit])


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        documents = await asyncio.to_thread(self._search_sync, query, limit)
        return SearchResultBatch(provider=self.name, documents=documents[:limit])

    def _search_sync(self, query: str, limit: int) -> list[SearchDocument]:
        response = httpx.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_redirect": "1",
                "no_html": "1",
                "skip_disambig": "1",
            },
            timeout=self._timeout_seconds,
            headers={"User-Agent": "GlassBoxResearch/1.0"},
        )
        response.raise_for_status()
        payload = response.json()

        documents: list[SearchDocument] = []
        abstract_text = str(payload.get("AbstractText", "")).strip()
        abstract_url = str(payload.get("AbstractURL", "")).strip()
        heading = str(payload.get("Heading", "")).strip() or "DuckDuckGo summary"
        if abstract_text and abstract_url:
            documents.append(
                SearchDocument(
                    title=heading,
                    snippet=abstract_text,
                    url=abstract_url,
                    freshness="live",
                    reliability=0.6,
                    provider=self.name,
                )
            )

        for topic in payload.get("RelatedTopics", []):
            self._append_related_topic_documents(topic, documents, limit)
            if len(documents) >= limit:
                break

        return documents[:limit]

    def _append_related_topic_documents(self, topic: object, documents: list[SearchDocument], limit: int) -> None:
        if len(documents) >= limit or not isinstance(topic, dict):
            return

        nested_topics = topic.get("Topics")
        if isinstance(nested_topics, list):
            for nested_topic in nested_topics:
                self._append_related_topic_documents(nested_topic, documents, limit)
                if len(documents) >= limit:
                    return
            return

        text = str(topic.get("Text", "")).strip()
        first_url = str(topic.get("FirstURL", "")).strip()
        if not text or not first_url:
            return

        title = text.split(" - ", 1)[0].strip() or "DuckDuckGo related topic"
        documents.append(
            SearchDocument(
                title=title,
                snippet=text,
                url=first_url,
                freshness="live",
                reliability=0.52,
                provider=self.name,
            )
        )


class OpenMeteoWeatherProvider:
    """Live weather provider using Open-Meteo endpoints (no API key)."""

    name = "weather_open_meteo"

    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        docs = await asyncio.to_thread(self._search_sync, query, limit)
        return SearchResultBatch(
            provider=self.name,
            documents=docs,
            intent="weather_live",
            confidence=0.86 if docs else 0.0,
            providers_tried=[self.name],
        )

    @staticmethod
    def _detect_weather_mode(query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ("ngày mai", "ngay mai", "tomorrow", "mai", "t2", "t3", "t4", "t5", "t6", "t7", "cn")):
            return "tomorrow"
        if any(token in lowered for token in ("forecast", "dự báo", "du bao", "3 ngày", "5 ngày", "7 ngày", "this week", "tuần")):
            return "forecast"
        return "current"

    @staticmethod
    def _weather_code_label(weather_code: object) -> str:
        try:
            code = int(weather_code)
        except Exception:
            return "unknown"
        code_map = {
            0: "clear",
            1: "mainly clear",
            2: "partly cloudy",
            3: "overcast",
            45: "fog",
            48: "rime fog",
            51: "light drizzle",
            53: "drizzle",
            55: "dense drizzle",
            61: "slight rain",
            63: "rain",
            65: "heavy rain",
            71: "slight snow",
            73: "snow",
            75: "heavy snow",
            80: "rain showers",
            81: "rain showers",
            82: "violent rain showers",
            95: "thunderstorm",
        }
        return code_map.get(code, f"weather_code={code}")

    def _search_sync(self, query: str, limit: int) -> list[SearchDocument]:
        location = self._extract_location(query) or "Da Nang"
        mode = self._detect_weather_mode(query)
        geo = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=self._timeout_seconds,
            headers={"User-Agent": "GlassBoxResearch/1.0"},
        )
        geo.raise_for_status()
        geo_payload = geo.json()
        geo_results = geo_payload.get("results") or []
        if not geo_results:
            return []

        first = geo_results[0]
        latitude = first.get("latitude")
        longitude = first.get("longitude")
        if latitude is None or longitude is None:
            return []

        forecast = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": "true",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                "forecast_days": 7,
                "timezone": "auto",
            },
            timeout=self._timeout_seconds,
            headers={"User-Agent": "GlassBoxResearch/1.0"},
        )
        forecast.raise_for_status()
        payload = forecast.json()
        current_weather = payload.get("current_weather") or {}
        daily = payload.get("daily") or {}

        location_name = str(first.get("name", location))
        docs: list[SearchDocument] = []

        if mode in ("tomorrow", "forecast") and daily:
            dates = list(daily.get("time") or [])
            max_temps = list(daily.get("temperature_2m_max") or [])
            min_temps = list(daily.get("temperature_2m_min") or [])
            rain_probs = list(daily.get("precipitation_probability_max") or [])
            weather_codes = list(daily.get("weathercode") or [])

            if dates:
                start_index = 1 if mode == "tomorrow" and len(dates) > 1 else 0
                end_index = min(len(dates), start_index + (1 if mode == "tomorrow" else 3))
                for idx in range(start_index, end_index):
                    day_label = str(dates[idx])
                    temp_min = min_temps[idx] if idx < len(min_temps) else "n/a"
                    temp_max = max_temps[idx] if idx < len(max_temps) else "n/a"
                    rain_prob = rain_probs[idx] if idx < len(rain_probs) else "n/a"
                    weather_code = weather_codes[idx] if idx < len(weather_codes) else "n/a"
                    summary = (
                        f"{location_name} forecast {day_label}: temp_min={temp_min}C, temp_max={temp_max}C, "
                        f"rain_probability_max={rain_prob}%, weather={self._weather_code_label(weather_code)}."
                    )
                    docs.append(
                        SearchDocument(
                            title=f"Weather forecast for {location_name} on {day_label}",
                            snippet=summary,
                            url="https://open-meteo.com/",
                            freshness="live",
                            published_at=day_label,
                            reliability=0.9,
                            provider=self.name,
                        )
                    )

        if mode == "current" and current_weather:
            temperature = current_weather.get("temperature")
            windspeed = current_weather.get("windspeed")
            weather_code = current_weather.get("weathercode")
            observed_at = str(current_weather.get("time", ""))
            summary = (
                f"{location_name}: temperature={temperature}C, wind={windspeed}km/h, "
                f"weather={self._weather_code_label(weather_code)}, observed_at={observed_at}."
            )
            docs.append(
                SearchDocument(
                    title=f"Live weather snapshot for {location_name}",
                    snippet=summary,
                    url="https://open-meteo.com/",
                    freshness="live",
                    published_at=observed_at or None,
                    reliability=0.88,
                    provider=self.name,
                )
            )

        # Fallback: if requested forecast but no daily data, still return current snapshot.
        if not docs and current_weather:
            temperature = current_weather.get("temperature")
            windspeed = current_weather.get("windspeed")
            weather_code = current_weather.get("weathercode")
            observed_at = str(current_weather.get("time", ""))
            summary = (
                f"{location_name}: current temperature={temperature}C, wind={windspeed}km/h, "
                f"weather={self._weather_code_label(weather_code)}, observed_at={observed_at}."
            )
            docs.append(
                SearchDocument(
                    title=f"Current weather for {location_name} (forecast unavailable)",
                    snippet=summary,
                    url="https://open-meteo.com/",
                    freshness="live",
                    published_at=observed_at or None,
                    reliability=0.82,
                    provider=self.name,
                )
            )

        return docs[:max(1, limit)]

    def _extract_location(self, query: str) -> str | None:
        lowered = query.lower()
        for known_city in ("da nang", "ha noi", "ho chi minh", "hue", "can tho"):
            if known_city in lowered:
                return known_city
        # Attempt simple phrase extraction: "weather in <location>"
        match = re.search(r"(?:weather|thoi tiet|thời tiết)\s+(?:in|tai|tại)?\s*([a-zA-Z\s]+)", lowered)
        if not match:
            return None
        candidate = re.sub(r"\s+", " ", match.group(1)).strip()
        return candidate[:60] if candidate else None


class NewsAPIProvider:
    """Live news provider using NewsAPI.org (requires API key)."""

    name = "newsapi"

    def __init__(self, api_key: str = "", timeout_seconds: float = 3.0) -> None:
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._available = bool(self._api_key)

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        if not self._available:
            return SearchResultBatch(
                provider=self.name,
                documents=[],
                intent="news_live",
                confidence=0.0,
                providers_tried=[self.name],
            )

        docs = await asyncio.to_thread(self._search_sync, query, limit)
        return SearchResultBatch(
            provider=self.name,
            documents=docs,
            intent="news_live",
            confidence=0.72 if docs else 0.0,
            providers_tried=[self.name],
        )

    def _search_sync(self, query: str, limit: int) -> list[SearchDocument]:
        try:
            response = httpx.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "pageSize": limit,
                    "apiKey": self._api_key,
                },
                timeout=self._timeout_seconds,
                headers={"User-Agent": "GlassBoxResearch/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
            articles = payload.get("articles") or []
            if not articles:
                return []

            documents: list[SearchDocument] = []
            for article in articles[:limit]:
                title = str(article.get("title", "")).strip()
                description = str(article.get("description", "")).strip()
                url = str(article.get("url", "")).strip()
                published_at = str(article.get("publishedAt", "")).strip()
                source_name = str(article.get("source", {}).get("name", "news")).strip()

                if not title or not url:
                    continue

                snippet = description or title[:200]
                documents.append(
                    SearchDocument(
                        title=title[:100],
                        snippet=snippet[:300],
                        url=url[:500],
                        freshness="live",
                        published_at=published_at,
                        reliability=0.75,
                        provider=source_name or self.name,
                    )
                )

            return documents[:limit]
        except Exception:
            return []


class SerpAPIProvider:
    """Live search provider using SerpAPI (requires API key, premium feature)."""

    name = "serpapi"

    def __init__(self, api_key: str = "", timeout_seconds: float = 3.0) -> None:
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._available = bool(self._api_key)

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        if not self._available:
            return SearchResultBatch(
                provider=self.name,
                documents=[],
                intent="general_research",
                confidence=0.0,
                providers_tried=[self.name],
            )

        docs = await asyncio.to_thread(self._search_sync, query, limit)
        return SearchResultBatch(
            provider=self.name,
            documents=docs,
            intent="general_research",
            confidence=0.68 if docs else 0.0,
            providers_tried=[self.name],
        )

    def _search_sync(self, query: str, limit: int) -> list[SearchDocument]:
        try:
            response = httpx.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": self._api_key,
                    "num": limit,
                },
                timeout=self._timeout_seconds,
                headers={"User-Agent": "GlassBoxResearch/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
            organic_results = payload.get("organic_results") or []
            if not organic_results:
                return []

            documents: list[SearchDocument] = []
            for result in organic_results[:limit]:
                title = str(result.get("title", "")).strip()
                snippet = str(result.get("snippet", "")).strip()
                url = str(result.get("link", "")).strip()

                if not title or not url:
                    continue

                documents.append(
                    SearchDocument(
                        title=title[:100],
                        snippet=snippet[:300],
                        url=url[:500],
                        freshness="live",
                        published_at=None,
                        reliability=0.70,
                        provider=self.name,
                    )
                )

            return documents[:limit]
        except Exception:
            return []


class PolicyDrivenSearchProvider:
    """Policy + health-aware provider orchestration with optional speculative execution."""

    name = "policy"

    def __init__(
        self,
        providers: dict[str, SearchProvider],
        policy: ToolPolicy,
        fallback: SearchProvider,
        provider_timeout_seconds: float = 4.0,
    ) -> None:
        self._providers = providers
        self._policy = policy
        self._fallback = fallback
        self._provider_timeout_seconds = provider_timeout_seconds
        self._breaker_by_provider: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(fail_threshold=3, recovery_timeout_seconds=20.0, half_open_max_calls=1)
            for name in providers
        }
        self._breaker_by_provider[fallback.name] = CircuitBreaker(
            fail_threshold=5,
            recovery_timeout_seconds=8.0,
            half_open_max_calls=1,
        )

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        intent = detect_search_intent(query)
        started_at = time.perf_counter()
        cache_ttl_seconds = self._policy.cache_ttl_seconds(intent)

        if self._policy.should_use_mock_only():
            result = await self._fallback.search(query, limit=limit)
            result.intent = intent
            result.fallback_used = True
            result.providers_tried = [self._fallback.name]
            result.confidence = self._compute_confidence(result.documents, fallback_used=True)
            result.latency_ms = int((time.perf_counter() - started_at) * 1000)
            result.cache_ttl_seconds = cache_ttl_seconds
            return result

        provider_names = self._policy.provider_candidates(intent)
        providers = [self._providers[name] for name in provider_names if name in self._providers]
        providers_tried: list[str] = []

        if self._policy.speculative_enabled(intent) and len(providers) >= 2:
            selected = await self._run_speculative(query, providers[:2], limit=limit, providers_tried=providers_tried)
            if selected is not None:
                selected.intent = intent
                selected.providers_tried = providers_tried
                selected.fallback_used = selected.provider == self._fallback.name
                selected.confidence = self._compute_confidence(selected.documents, fallback_used=selected.fallback_used)
                selected.latency_ms = int((time.perf_counter() - started_at) * 1000)
                selected.cache_ttl_seconds = cache_ttl_seconds
                return selected

        for provider in providers:
            candidate = await self._run_single_provider(query, provider, limit=limit, providers_tried=providers_tried)
            if candidate is not None and candidate.documents:
                candidate.intent = intent
                candidate.providers_tried = providers_tried
                candidate.fallback_used = False
                candidate.confidence = self._compute_confidence(candidate.documents, fallback_used=False)
                candidate.latency_ms = int((time.perf_counter() - started_at) * 1000)
                candidate.cache_ttl_seconds = cache_ttl_seconds
                return candidate

        if self._policy.allow_mock_fallback():
            fallback_result = await self._run_single_provider(query, self._fallback, limit=limit, providers_tried=providers_tried)
            if fallback_result is None:
                fallback_result = SearchResultBatch(provider=self._fallback.name, documents=[])
            fallback_result.intent = intent
            fallback_result.fallback_used = True
            fallback_result.providers_tried = providers_tried
            fallback_result.confidence = self._compute_confidence(fallback_result.documents, fallback_used=True)
            fallback_result.latency_ms = int((time.perf_counter() - started_at) * 1000)
            fallback_result.cache_ttl_seconds = cache_ttl_seconds
            return fallback_result

        return SearchResultBatch(
            provider="none",
            documents=[],
            fallback_used=False,
            intent=intent,
            confidence=0.0,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            providers_tried=providers_tried,
            cache_ttl_seconds=cache_ttl_seconds,
        )

    async def _run_speculative(
        self,
        query: str,
        providers: list[SearchProvider],
        limit: int,
        providers_tried: list[str],
    ) -> SearchResultBatch | None:
        tasks = [self._run_single_provider(query, provider, limit=limit, providers_tried=providers_tried) for provider in providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        best: SearchResultBatch | None = None
        best_score = -1.0
        for result in results:
            if isinstance(result, Exception) or result is None or not result.documents:
                continue
            score = self._provider_rank(result.provider) + self._documents_quality(result.documents)
            if score > best_score:
                best = result
                best_score = score
        return best

    async def _run_single_provider(
        self,
        query: str,
        provider: SearchProvider,
        limit: int,
        providers_tried: list[str],
    ) -> SearchResultBatch | None:
        providers_tried.append(provider.name)
        breaker = self._breaker_by_provider.get(provider.name)
        if breaker is not None and not breaker.allow_request():
            return None

        try:
            result = await asyncio.wait_for(provider.search(query, limit=limit), timeout=self._provider_timeout_seconds)
        except Exception:
            if breaker is not None:
                breaker.record_failure()
            return None

        if breaker is not None:
            breaker.record_success()
        return result

    def _provider_rank(self, provider_name: str) -> float:
        if provider_name == "weather_open_meteo":
            return 0.6
        if provider_name == "duckduckgo":
            return 0.45
        if provider_name == "mock":
            return 0.1
        return 0.2

    def _documents_quality(self, documents: list[SearchDocument]) -> float:
        if not documents:
            return 0.0
        avg_reliability = sum(max(0.0, min(1.0, doc.reliability)) for doc in documents) / len(documents)
        source_bonus = min(len({doc.url for doc in documents}) * 0.05, 0.2)
        live_bonus = 0.1 if any(doc.freshness == "live" for doc in documents) else 0.0
        return avg_reliability + source_bonus + live_bonus

    def _compute_confidence(self, documents: list[SearchDocument], fallback_used: bool) -> float:
        if not documents:
            return 0.0
        confidence = self._documents_quality(documents)
        if fallback_used:
            confidence *= 0.5
        return round(max(0.0, min(1.0, confidence)), 2)


class FallbackSearchProvider:
    name = "fallback"

    def __init__(self, primary: SearchProvider, fallback: SearchProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        try:
            primary_result = await self._primary.search(query, limit=limit)
            if primary_result.documents:
                return primary_result
        except Exception:
            pass

        fallback_result = await self._fallback.search(query, limit=limit)
        return SearchResultBatch(
            provider=fallback_result.provider,
            documents=fallback_result.documents,
            fallback_used=True,
        )
