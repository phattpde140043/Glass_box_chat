from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import parse_qs, unquote, urlparse

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


class LocationSemanticExtractor(Protocol):
    def extract_location(self, text: str) -> str | None: ...


SearchIntent = Literal["weather_live", "news_live", "market_live", "local_discovery", "travel_planning", "general_research"]

_COMMODITY_SUBJECT_HINTS: dict[str, tuple[str, ...]] = {
    "coffee": ("coffee", "cà phê", "ca phe", "cafe", "arabica", "robusta"),
    "pepper": ("pepper", "hồ tiêu", "ho tieu", "black pepper"),
    "commodity": ("commodity", "commodities", "nông sản", "nong san", "market"),
}

_OFFICIAL_COMMODITY_DOMAINS: dict[str, tuple[str, ...]] = {
    "coffee": ("ico.org", "fas.usda.gov", "fao.org", "worldbank.org"),
    "pepper": ("fao.org", "worldbank.org"),
    "commodity": ("worldbank.org", "fao.org", "usda.gov"),
}

_AGGREGATE_SOURCE_HINTS = (
    "news",
    "digest",
    "latest",
    "summary",
    "roundup",
    "analysis",
    "opinion",
    "blog",
)

_SOURCE_TIER_SCORES: dict[str, float] = {
    "official_statistics": 1.0,
    "intergovernmental_report": 0.88,
    "major_exchange": 0.78,
    "financial_media": 0.62,
    "general_news": 0.45,
    "other": 0.35,
}

_INTERGOV_DOMAINS = (
    "worldbank.org",
    "fao.org",
    "usda.gov",
    "oecd.org",
    "imf.org",
    "ec.europa.eu",
)

_MAJOR_EXCHANGE_DOMAINS = (
    "ice.com",
    "cmegroup.com",
    "lme.com",
)

_FINANCIAL_MEDIA_DOMAINS = (
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "marketwatch.com",
    "investing.com",
)


def _tokenize_text(text: str) -> set[str]:
    return {token for token in re.split(r"[^\wÀ-ỹ]+", text.lower()) if token}


def detect_commodity_subject(query: str) -> str:
    lowered = query.lower()
    for subject, hints in _COMMODITY_SUBJECT_HINTS.items():
        if any(hint in lowered for hint in hints):
            return subject
    return "commodity"


def is_official_commodity_source(document: SearchDocument, query: str) -> bool:
    subject = detect_commodity_subject(query)
    haystack = f"{document.url} {document.provider} {document.title}".lower()
    return any(domain in haystack for domain in _OFFICIAL_COMMODITY_DOMAINS.get(subject, ()))


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    netloc = (parsed.netloc or "").lower()
    if netloc.startswith("www."):
        return netloc[4:]
    return netloc


def classify_source_tier(document: SearchDocument, query: str) -> str:
    haystack = f"{document.provider} {document.title} {document.url}".lower()
    domain = _extract_domain(document.url)
    provider = (document.provider or "").lower()

    if is_official_commodity_source(document, query):
        return "official_statistics"
    if any(domain.endswith(suffix) for suffix in _INTERGOV_DOMAINS):
        return "intergovernmental_report"
    if any(domain.endswith(suffix) for suffix in _MAJOR_EXCHANGE_DOMAINS):
        return "major_exchange"
    if any(domain.endswith(suffix) for suffix in _FINANCIAL_MEDIA_DOMAINS):
        return "financial_media"
    if provider in ("newsapi", "serpapi") or any(token in haystack for token in ("news", "headline", "digest")):
        return "general_news"
    return "other"


def _published_recency_decay(published_at: str | None, freshness: str) -> float:
    if not published_at:
        freshness_map = {"live": 1.0, "latest": 0.95, "today": 0.97, "recent": 0.9}
        return freshness_map.get((freshness or "").lower(), 0.86)

    raw = published_at.strip()
    if not raw:
        return 0.86
    normalized = raw.replace("Z", "+00:00")
    try:
        published_dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            published_dt = datetime.fromisoformat(f"{raw}T00:00:00")
        except ValueError:
            return 0.86

    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=UTC)
    now = datetime.now(tz=UTC)
    age_days = max(0.0, (now - published_dt).total_seconds() / 86400.0)

    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.97
    if age_days <= 30:
        return 0.9
    if age_days <= 90:
        return 0.78
    if age_days <= 180:
        return 0.66
    return 0.55


def _source_group_key(document: SearchDocument) -> str:
    domain = _extract_domain(document.url)
    if domain:
        parts = domain.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return domain
    provider = (document.provider or "").strip().lower()
    return provider or "unknown"


def _title_signature(title: str) -> str:
    tokens = sorted(_tokenize_text(title))
    return " ".join(tokens[:8])


def _token_jaccard(a: str, b: str) -> float:
    a_tokens = _tokenize_text(a)
    b_tokens = _tokenize_text(b)
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    if union == 0:
        return 0.0
    return intersection / union


def score_document_relevance(document: SearchDocument, query: str) -> float:
    query_tokens = _tokenize_text(query)
    doc_tokens = _tokenize_text(f"{document.title} {document.snippet} {document.url} {document.provider}")
    overlap = len(query_tokens & doc_tokens)
    title_overlap = len(query_tokens & _tokenize_text(document.title))
    subject = detect_commodity_subject(query)
    subject_hits = sum(1 for hint in _COMMODITY_SUBJECT_HINTS.get(subject, ()) if hint in f"{document.title} {document.snippet}".lower())
    aggregate_penalty = 0.18 if any(token in f"{document.title} {document.provider} {document.url}".lower() for token in _AGGREGATE_SOURCE_HINTS) else 0.0
    tier = classify_source_tier(document, query)
    tier_score = _SOURCE_TIER_SCORES.get(tier, _SOURCE_TIER_SCORES["other"])
    official_bonus = 0.2 if tier == "official_statistics" else 0.0
    provider_bonus = 0.1 if document.provider == "commodity_refs" else 0.0
    freshness_bonus = 0.08 if document.freshness == "live" else 0.0
    recency_decay = _published_recency_decay(document.published_at, document.freshness)

    raw_score = (
        document.reliability * 0.55
        + tier_score * 0.6
        + overlap * 0.05
        + title_overlap * 0.08
        + subject_hits * 0.07
        + freshness_bonus
        + official_bonus
        + provider_bonus
        - aggregate_penalty
    )
    return round(max(0.0, min(2.5, raw_score * recency_decay)), 4)


def rank_documents_for_query(query: str, documents: list[SearchDocument], limit: int | None = None) -> list[SearchDocument]:
    ranked = sorted(
        documents,
        key=lambda document: (
            score_document_relevance(document, query),
            document.reliability,
            1 if document.freshness == "live" else 0,
        ),
        reverse=True,
    )

    selected: list[SearchDocument] = []
    source_counts: dict[str, int] = {}
    seen_signatures: set[str] = set()

    target = len(ranked) if limit is None else min(limit, len(ranked))
    while ranked and len(selected) < target:
        best_index = 0
        best_adjusted_score = -1.0
        for index, candidate in enumerate(ranked):
            base = score_document_relevance(candidate, query)
            source_group = _source_group_key(candidate)
            diversity_penalty = source_counts.get(source_group, 0) * 0.16
            signature = _title_signature(candidate.title)
            duplicate_penalty = 0.1 if signature in seen_signatures else 0.0
            near_duplicate_penalty = 0.0
            if selected:
                near_duplicate_penalty = max(
                    (_token_jaccard(candidate.title, picked.title) * 0.12 for picked in selected[-3:]),
                    default=0.0,
                )
            adjusted = base - diversity_penalty - duplicate_penalty - near_duplicate_penalty
            if adjusted > best_adjusted_score:
                best_adjusted_score = adjusted
                best_index = index

        chosen = ranked.pop(best_index)
        selected.append(chosen)
        source_group = _source_group_key(chosen)
        source_counts[source_group] = source_counts.get(source_group, 0) + 1
        seen_signatures.add(_title_signature(chosen.title))

    return selected


def is_commodity_query(query: str) -> bool:
    lowered = query.lower()
    return any(
        token in lowered
        for token in (
            "coffee",
            "cà phê",
            "ca phe",
            "cafe",
            "arabica",
            "robusta",
            "commodity",
            "nông sản",
            "nong san",
            "pepper",
            "hồ tiêu",
            "ho tieu",
        )
    )


def detect_search_intent(query: str) -> SearchIntent:
    lowered = query.lower()
    
    # Check high-priority intents FIRST to avoid false positives from location mentions
    if any(token in lowered for token in ("weather", "thời tiết", "thoi tiet", "forecast", "dự báo", "du bao", "nhiệt độ", "nhiet do")):
        return "weather_live"
    if any(token in lowered for token in ("news", "tin tức", "tin tuc", "headline", "mới nhất", "moi nhat")):
        return "news_live"
    if any(token in lowered for token in ("stock", "market", "crypto", "gia vang", "giá vàng", "gold price", "xau", "xauusd", "bitcoin", "btc", "ethereum", "eth", "tỷ giá", "ty gia", "exchange rate", "forex", "chứng khoán", "chung khoan", "coffee", "cà phê", "ca phe", "cafe", "arabica", "robusta", "commodity", "nông sản", "nong san", "pepper", "hồ tiêu", "ho tieu")):
        return "market_live"
    
    # Then check local_discovery and travel_planning
    if any(
        token in lowered
        for token in (
            "nhà hàng",
            "nha hang",
            "restaurant",
            "quán ăn",
            "quan an",
            "khách sạn",
            "khach san",
            "hotel",
            "resort",
            "homestay",
            "attraction",
            "địa điểm",
            "dia diem",
            "điểm đến",
            "diem den",
            "du lịch",
            "du lich",
            "travel",
            "lịch trình",
            "lich trinh",
            "itinerary",
            "things to do",
            "near me",
            "gần đây",
            "gan day",
            "food",
            "foods",
            "eat",
            "eating",
            "eating out",
            "dining",
            "dine",
            "breakfast",
            "lunch",
            "dinner",
            "brunch",
            "meal",
            "traditional food",
            "street food",
            "ăn uống",
            "an uong",
            "ăn gì",
            "an gi",
            "ăn gì ngon",
            "ăn ở đâu",
            "thứ ăn",
            "chu an",
            "món ăn",
            "mon an",
            "vacation",
        )
    ):
        if any(token in lowered for token in ("itinerary", "lịch trình", "lich trinh", "2 ngày", "3 ngày", "plan trip", "kế hoạch", "ke hoach")):
            return "travel_planning"
        return "local_discovery"
    
    return "general_research"


class ToolPolicy:
    """Select provider strategy by intent, mode, and provider health."""

    def __init__(self, mode: str = "hybrid") -> None:
        self._mode = mode.strip().lower() or "hybrid"
        self._cache_policy_by_intent = {
            "weather_live": 30,
            "news_live": 120,
            "market_live": 45,
            "local_discovery": 300,
            "travel_planning": 300,
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
        if self._mode == "demo":
            return True
        # In live/hybrid modes, mock fallback must be explicitly enabled.
        # This prevents returning fake example.local evidence in real user responses.
        return os.getenv("RESEARCH_ALLOW_MOCK_FALLBACK", "false").strip().lower() in ("1", "true", "yes", "on")

    def provider_candidates(self, intent: SearchIntent) -> list[str]:
        if self._mode == "demo":
            return ["mock"]
        if intent == "weather_live":
            return ["weather_open_meteo", "duckduckgo"]
        if intent == "news_live":
            return ["newsapi", "duckduckgo"]
        if intent == "market_live":
            return ["serpapi", "duckduckgo"]
        if intent in ("local_discovery", "travel_planning"):
            return ["serpapi", "osm_local", "duckduckgo", "newsapi"]
        return ["duckduckgo"]

    def speculative_enabled(self, intent: SearchIntent) -> bool:
        return self._mode in ("live", "hybrid") and intent in (
            "weather_live",
            "news_live",
            "market_live",
            "local_discovery",
            "travel_planning",
        )


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

        # Instant-answer API can be empty for local/place queries; fallback to HTML SERP parsing.
        if not documents:
            documents = self._search_html_sync(query, limit)

        return rank_documents_for_query(query, documents, limit=limit)

    def _search_html_sync(self, query: str, limit: int) -> list[SearchDocument]:
        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=self._timeout_seconds,
            headers={"User-Agent": "GlassBoxResearch/1.0"},
        )
        response.raise_for_status()
        return self._extract_html_results(query, response.text, limit)

    def _extract_html_results(self, query: str, html: str, limit: int) -> list[SearchDocument]:
        documents: list[SearchDocument] = []
        anchors = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for href, raw_title in anchors:
            title = re.sub(r"<[^>]+>", "", raw_title)
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue

            url = href.strip()
            if "duckduckgo.com/l/?" in url:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                uddg = qs.get("uddg", [""])[0]
                if uddg:
                    url = unquote(uddg)

            if not url.startswith("http"):
                continue

            documents.append(
                SearchDocument(
                    title=title[:180],
                    snippet=f"Search result for: {query}",
                    url=url,
                    freshness="live",
                    reliability=0.5,
                    provider=self.name,
                )
            )
            if len(documents) >= limit:
                break

        return documents

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
    _KNOWN_CITIES = ("da nang", "ha noi", "ho chi minh", "hue", "can tho")
    _LOCATION_TRAILING_HINTS = re.compile(
        r"\b(?:"
        r"ngay mai|ngày mai|hom nay|hôm nay|tomorrow|today|forecast|du bao|dự báo|"
        r"the nao|thế nào|ra sao|la gi|là gì|suitable|phu hop|phù hợp|picnic|"
        r"weather|thoi tiet|thời tiết|nhu the nao|như thế nào"
        r")\b",
        re.IGNORECASE,
    )

    def __init__(self, timeout_seconds: float = 3.0, semantic_extractor: LocationSemanticExtractor | None = None) -> None:
        self._timeout_seconds = timeout_seconds
        self._semantic_extractor = semantic_extractor or self._build_default_semantic_extractor()

    @staticmethod
    def _build_default_semantic_extractor() -> LocationSemanticExtractor | None:
        enabled = os.getenv("WEATHER_ENABLE_BERT_EXTRACTOR", "false").strip().lower() in ("1", "true", "yes", "on")
        if not enabled:
            return None
        model_name = os.getenv("WEATHER_BERT_MODEL", "dslim/bert-base-NER").strip() or "dslim/bert-base-NER"
        min_score = float(os.getenv("WEATHER_BERT_MIN_SCORE", "0.5"))
        return BERTSemanticEntityExtractor(model_name=model_name, min_score=min_score)

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

    @classmethod
    def _clean_location_candidate(cls, candidate: str) -> str | None:
        sanitized = re.sub(r"\s+", " ", candidate).strip(" ,?.!:;")
        sanitized = re.sub(r"^(?:o|ở|in|tai|tại|for)\s+", "", sanitized, flags=re.IGNORECASE)
        sanitized = cls._LOCATION_TRAILING_HINTS.split(sanitized, maxsplit=1)[0].strip(" ,?.!:;")
        sanitized = re.sub(r"[^0-9A-Za-zÀ-ỹ\s\-'.]", " ", sanitized)
        sanitized = re.sub(r"\s+", " ", sanitized).strip(" ,?.!:;")
        return sanitized[:60] if sanitized else None

    def _extract_location_semantically(self, query: str) -> str | None:
        if self._semantic_extractor is None:
            return None
        try:
            semantic_location = self._semantic_extractor.extract_location(query)
        except Exception:
            return None
        if not semantic_location:
            return None
        return self._clean_location_candidate(semantic_location.lower())

    def _extract_location(self, query: str) -> str | None:
        lowered = query.lower()
        for known_city in self._KNOWN_CITIES:
            if known_city in lowered:
                return known_city

        patterns = (
            r"(?:weather\s+forecast|forecast\s+weather)\s+(?:for|in|at)\s+(.+)",
            r"(?:weather|thoi tiet|thời tiết)\s+(?:o|ở|in|tai|tại|for|at)?\s*(.+)",
            r"(?:du bao|dự báo|forecast)\s+(?:weather|thoi tiet|thời tiết)\s+(?:o|ở|in|tai|tại|for|at)?\s*(.+)",
            r"(?:o|ở|in|tai|tại|for|at)\s+([0-9A-Za-zÀ-ỹ\s\-'.]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = self._clean_location_candidate(match.group(1))
            if candidate:
                return candidate

        # Semantic extraction is intentionally the last fallback because loading/using
        # token-classification models can be expensive on cold start.
        semantic = self._extract_location_semantically(query)
        if semantic:
            return semantic
        return None


class BERTSemanticEntityExtractor:
    """Optional semantic extractor using a local or remotely-resolved BERT token-classification model."""

    _LOCATION_LABEL_HINTS = ("LOC", "LOCATION", "GPE")

    def __init__(self, model_name: str, min_score: float = 0.5) -> None:
        self._model_name = model_name
        self._min_score = max(0.0, min(1.0, min_score))
        self._pipeline: object | None = None
        self._disabled = False

    def _get_pipeline(self):
        if self._disabled:
            return None
        if self._pipeline is not None:
            return self._pipeline
        try:
            from transformers import pipeline  # type: ignore

            self._pipeline = pipeline(
                "token-classification",
                model=self._model_name,
                tokenizer=self._model_name,
                aggregation_strategy="simple",
            )
            return self._pipeline
        except Exception:
            self._disabled = True
            self._pipeline = None
            return None

    @classmethod
    def _is_location_entity(cls, entity_group: str) -> bool:
        normalized = entity_group.upper().replace("-", "_")
        return any(hint in normalized for hint in cls._LOCATION_LABEL_HINTS)

    def extract_location(self, text: str) -> str | None:
        if not text.strip():
            return None
        token_classifier = self._get_pipeline()
        if token_classifier is None:
            return None

        entities = token_classifier(text)
        best_text: str | None = None
        best_score = -1.0

        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_group = str(entity.get("entity_group") or entity.get("entity") or "")
            if not self._is_location_entity(entity_group):
                continue
            score = float(entity.get("score") or 0.0)
            if score < self._min_score:
                continue
            candidate = str(entity.get("word") or "").strip()
            if not candidate:
                continue
            if score > best_score:
                best_score = score
                best_text = candidate

        return best_text


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
        intent = detect_search_intent(query)
        if not self._available:
            return SearchResultBatch(
                provider=self.name,
                documents=[],
                intent=intent,
                confidence=0.0,
                providers_tried=[self.name],
            )

        docs = await asyncio.to_thread(self._search_sync, query, limit)
        return SearchResultBatch(
            provider=self.name,
            documents=docs,
            intent=intent,
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
            documents: list[SearchDocument] = []

            # Local intent: prefer Google local pack style results when available.
            local_results = payload.get("local_results") or payload.get("local_map") or {}
            local_places = local_results.get("places") if isinstance(local_results, dict) else None
            if isinstance(local_places, list):
                for place in local_places[:limit]:
                    title = str(place.get("title") or place.get("name") or "").strip()
                    rating = str(place.get("rating") or "n/a").strip()
                    reviews = str(place.get("reviews") or place.get("reviews_original") or "").strip()
                    address = str(place.get("address") or place.get("snippet") or "").strip()
                    website = str(place.get("website") or place.get("link") or "").strip()
                    if not title:
                        continue
                    documents.append(
                        SearchDocument(
                            title=title[:100],
                            snippet=f"Rating {rating} | Reviews {reviews} | {address}"[:300],
                            url=(website or f"https://www.google.com/search?q={title.replace(' ', '+')}")[:500],
                            freshness="live",
                            published_at=None,
                            reliability=0.74,
                            provider=self.name,
                        )
                    )

            organic_results = payload.get("organic_results") or []
            if not organic_results and documents:
                return documents[:limit]
            if not organic_results and not documents:
                return []

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


class OpenStreetMapLocalProvider:
    """Local place provider using OpenStreetMap Nominatim (no API key)."""

    name = "osm_local"

    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        docs = await asyncio.to_thread(self._search_sync, query, limit)
        return SearchResultBatch(
            provider=self.name,
            documents=docs,
            intent="local_discovery",
            confidence=0.68 if docs else 0.0,
            providers_tried=[self.name],
        )

    @staticmethod
    def _extract_place_type(query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ("restaurant", "nhà hàng", "nha hang", "quán ăn", "quan an", "risotto", "food", "foods", "eat", "eating", "eating out", "dining", "dine", "breakfast", "lunch", "dinner", "brunch", "meal", "traditional food", "street food", "ăn uống", "an uong", "ăn gì", "an gi", "ăn gì ngon", "ăn ở đâu", "thứ ăn", "chu an", "món ăn", "mon an")):
            return "restaurant"
        if any(token in lowered for token in ("hotel", "khách sạn", "khach san", "resort", "homestay")):
            return "hotel"
        if any(token in lowered for token in ("attraction", "địa điểm", "dia diem", "travel", "du lịch", "du lich")):
            return "attraction"
        return "place"

    @staticmethod
    def _extract_location(query: str) -> str | None:
        lowered = query.lower()
        for city in ("milan", "milano", "hanoi", "ha noi", "da nang", "ho chi minh", "saigon", "nha trang", "da lat"):
            if city in lowered:
                return city

        match = re.search(r"\b(?:in|at|ở|tai|tại)\s+([A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s\-']{1,40})", query, flags=re.IGNORECASE)
        if match:
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,.!?;:")
            candidate = re.split(r"\b(with|for|and|or|which|that|good|best|review|reviews)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,.!?;:")
            if candidate:
                return candidate
        return None

    @classmethod
    def _query_candidates(cls, query: str) -> list[str]:
        place_type = cls._extract_place_type(query)
        location = cls._extract_location(query)
        candidates = [query.strip()]
        if location:
            candidates.extend(
                [
                    f"{place_type} in {location}",
                    f"{place_type} {location}",
                    location,
                ]
            )
        return [candidate for candidate in dict.fromkeys(candidates) if candidate]

    def _search_sync(self, query: str, limit: int) -> list[SearchDocument]:
        for candidate in self._query_candidates(query):
            try:
                response = httpx.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": candidate,
                        "format": "jsonv2",
                        "limit": max(1, min(limit, 10)),
                        "addressdetails": 1,
                    },
                    timeout=self._timeout_seconds,
                    headers={"User-Agent": "GlassBoxLocalDiscovery/1.0"},
                )
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue

            if not isinstance(payload, list) or not payload:
                continue

            docs: list[SearchDocument] = []
            for item in payload[: max(1, min(limit, 10))]:
                if not isinstance(item, dict):
                    continue
                display_name = str(item.get("display_name", "")).strip()
                name = str(item.get("name", "")).strip() or display_name.split(",", 1)[0].strip() or "Place"
                osm_type = str(item.get("type", "place")).strip() or "place"
                lat = str(item.get("lat", "")).strip()
                lon = str(item.get("lon", "")).strip()
                if not display_name:
                    continue

                osm_id = str(item.get("osm_id", "")).strip()
                osm_entity_type = str(item.get("osm_type", "node")).strip() or "node"
                details_url = f"https://www.openstreetmap.org/{osm_entity_type}/{osm_id}" if osm_id else "https://www.openstreetmap.org/"

                docs.append(
                    SearchDocument(
                        title=name[:180],
                        snippet=f"{osm_type}: {display_name}. Coordinates: {lat}, {lon}",
                        url=details_url,
                        freshness="live",
                        reliability=0.72,
                        provider=self.name,
                    )
                )

            if docs:
                return docs

        return []


class CommodityReferenceProvider:
    """Direct reference fetcher for commodity/coffee market pages without API keys."""

    name = "commodity_refs"

    def __init__(self, timeout_seconds: float = 4.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> SearchResultBatch:
        if not is_commodity_query(query):
            return SearchResultBatch(
                provider=self.name,
                documents=[],
                intent="market_live",
                confidence=0.0,
                providers_tried=[self.name],
            )

        docs = await asyncio.to_thread(self._search_sync, query, limit)
        return SearchResultBatch(
            provider=self.name,
            documents=docs[:limit],
            intent="market_live",
            confidence=0.76 if docs else 0.0,
            providers_tried=[self.name],
        )

    def _search_sync(self, query: str, limit: int) -> list[SearchDocument]:
        subject = self._detect_subject(query)
        references = self._reference_urls(subject)
        documents: list[SearchDocument] = []

        for title, url, reliability in references:
            doc = self._fetch_reference(subject, title, url, reliability)
            if doc is not None:
                documents.append(doc)
            if len(documents) >= limit:
                break

        return documents[:limit]

    @staticmethod
    def _detect_subject(query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ("coffee", "cà phê", "ca phe", "cafe", "arabica", "robusta")):
            return "coffee"
        if any(token in lowered for token in ("pepper", "hồ tiêu", "ho tieu")):
            return "pepper"
        return "commodity"

    @staticmethod
    def _reference_urls(subject: str) -> list[tuple[str, str, float]]:
        common_refs = [
            ("World Bank commodity markets", "https://www.worldbank.org/en/research/commodity-markets", 0.84),
            ("FAO food price index", "https://www.fao.org/worldfoodsituation/foodpricesindex/en/", 0.82),
        ]
        if subject == "coffee":
            return [
                ("ICO coffee organization", "https://www.ico.org/", 0.9),
                ("USDA coffee markets and trade", "https://www.fas.usda.gov/data/coffee-world-markets-and-trade", 0.88),
                *common_refs,
            ]
        if subject == "pepper":
            return [
                ("FAO commodities and trade", "https://www.fao.org/markets-and-trade/en/", 0.8),
                *common_refs,
            ]
        return common_refs

    def _fetch_reference(self, subject: str, title: str, url: str, reliability: float) -> SearchDocument | None:
        try:
            response = httpx.get(
                url,
                timeout=self._timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "GlassBoxResearch/1.0"},
            )
            response.raise_for_status()
        except Exception:
            return None

        html = response.text
        page_title = self._extract_title(html) or title
        meta_description = self._extract_meta_description(html)
        snippet = meta_description or self._extract_visible_text(html)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not snippet:
            snippet = f"Official {subject} market reference page."

        if subject == "coffee" and "coffee" not in snippet.lower() and "cà phê" not in snippet.lower():
            snippet = f"Official coffee market reference. {snippet}"
        elif subject == "pepper" and "pepper" not in snippet.lower() and "tiêu" not in snippet.lower():
            snippet = f"Official pepper market reference. {snippet}"
        elif subject == "commodity" and "commodity" not in snippet.lower():
            snippet = f"Official commodity market reference. {snippet}"

        return SearchDocument(
            title=page_title[:100],
            snippet=snippet[:300],
            url=str(response.url)[:500],
            freshness="live",
            reliability=reliability,
            provider=self.name,
        )

    @staticmethod
    def _extract_title(html: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group(1))).strip()

    @staticmethod
    def _extract_meta_description(html: str) -> str:
        match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        return re.sub(r"\s+", " ", match.group(1)).strip()

    @staticmethod
    def _extract_visible_text(html: str) -> str:
        stripped = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return stripped[:600]


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
            result.documents = rank_documents_for_query(query, result.documents, limit=limit)
            result.confidence = self._compute_confidence(result.documents, fallback_used=True, query=query)
            result.latency_ms = int((time.perf_counter() - started_at) * 1000)
            result.cache_ttl_seconds = cache_ttl_seconds
            return result

        provider_names = self._policy.provider_candidates(intent)
        if intent == "market_live" and is_commodity_query(query):
            provider_names = ["commodity_refs", "newsapi", *provider_names]
            provider_names = list(dict.fromkeys(provider_names))
        providers = [self._providers[name] for name in provider_names if name in self._providers]
        providers_tried: list[str] = []

        if self._policy.speculative_enabled(intent) and len(providers) >= 2:
            selected = await self._run_speculative(query, providers[:2], limit=limit, providers_tried=providers_tried)
            if selected is not None:
                selected.intent = intent
                selected.providers_tried = providers_tried
                selected.fallback_used = selected.provider == self._fallback.name
                selected.confidence = self._compute_confidence(selected.documents, fallback_used=selected.fallback_used, query=query)
                selected.latency_ms = int((time.perf_counter() - started_at) * 1000)
                selected.cache_ttl_seconds = cache_ttl_seconds
                return selected

        for provider in providers:
            candidate = await self._run_single_provider(query, provider, limit=limit, providers_tried=providers_tried)
            if candidate is not None and candidate.documents:
                candidate.intent = intent
                candidate.providers_tried = providers_tried
                candidate.fallback_used = False
                candidate.confidence = self._compute_confidence(candidate.documents, fallback_used=False, query=query)
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
            fallback_result.documents = rank_documents_for_query(query, fallback_result.documents, limit=limit)
            fallback_result.confidence = self._compute_confidence(fallback_result.documents, fallback_used=True, query=query)
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
            result.documents = rank_documents_for_query(query, result.documents, limit=limit)
            score = self._provider_rank(result.provider) + self._documents_quality(query, result.documents)
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
        if result.documents:
            result.documents = rank_documents_for_query(query, result.documents, limit=limit)
        return result

    def _provider_rank(self, provider_name: str) -> float:
        if provider_name == "commodity_refs":
            return 0.58
        if provider_name == "weather_open_meteo":
            return 0.6
        if provider_name == "serpapi":
            return 0.65
        if provider_name == "osm_local":
            return 0.62
        if provider_name == "duckduckgo":
            return 0.45
        if provider_name == "mock":
            return 0.1
        return 0.2

    def _documents_quality(self, query: str, documents: list[SearchDocument]) -> float:
        if not documents:
            return 0.0
        avg_reliability = sum(max(0.0, min(1.0, doc.reliability)) for doc in documents) / len(documents)
        source_bonus = min(len({doc.url for doc in documents}) * 0.05, 0.2)
        live_bonus = 0.1 if any(doc.freshness == "live" for doc in documents) else 0.0
        top_relevance = score_document_relevance(documents[0], query)
        official_bonus = 0.12 if is_commodity_query(query) and is_official_commodity_source(documents[0], query) else 0.0
        return avg_reliability + source_bonus + live_bonus + min(top_relevance * 0.15, 0.3) + official_bonus

    def _compute_confidence(self, documents: list[SearchDocument], fallback_used: bool, query: str = "") -> float:
        if not documents:
            return 0.0
        confidence = self._documents_quality(query, documents) if query else self._documents_quality("", documents)
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
