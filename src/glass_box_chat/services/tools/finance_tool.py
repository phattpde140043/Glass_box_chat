from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
import time
from typing import Any

import httpx

from .tool_gateway import BaseTool, ToolInput, ToolOutput


@dataclass
class FinanceQuote:
    asset: str
    symbol: str
    price: float
    currency: str
    timestamp: str
    source: str
    raw_url: str


class FinanceTool(BaseTool):
    """Live market data tool for gold and selected assets."""

    def __init__(self, timeout_seconds: float = 4.0) -> None:
        super().__init__(
            name="finance",
            description="Get real-time market prices (gold/crypto/fx).",
            timeout_seconds=timeout_seconds,
            max_retries=0,
        )
        self._timeout_seconds = timeout_seconds
        self._goldapi_key = os.getenv("GOLDAPI_API_KEY", "").strip()
        self._cache_ttl_seconds = int(os.getenv("FINANCE_CACHE_TTL_SECONDS", "300"))
        self._cache: dict[str, tuple[float, FinanceQuote]] = {}

    @staticmethod
    def _compute_confidence(*, is_live: bool, source_count: int, multi_provider: bool, degraded: bool) -> float:
        score = 0.0
        if is_live:
            score += 0.4
        score += min(max(source_count, 0) * 0.2, 0.4)
        if multi_provider:
            score += 0.2
        if degraded:
            score = min(score, 0.45)
        return max(0.05, min(score, 1.0))

    @staticmethod
    def _normalize_query(query: str) -> str:
        return re.sub(r"\s+", " ", query).strip().lower()

    @staticmethod
    def _is_gold_query(normalized_query: str) -> bool:
        gold_hints = (
            "gold",
            "xau",
            "gia vang",
            "giá vàng",
            "vàng",
            "vang",
            "sjc",
            "nhan 24k",
            "24k",
        )
        return any(hint in normalized_query for hint in gold_hints)

    @staticmethod
    def _is_crypto_query(normalized_query: str) -> bool:
        crypto_hints = ("btc", "bitcoin", "eth", "ethereum", "crypto", "coin")
        return any(hint in normalized_query for hint in crypto_hints)

    @staticmethod
    def _select_crypto_id(normalized_query: str) -> tuple[str, str]:
        if any(token in normalized_query for token in ("ethereum", "eth")):
            return "ethereum", "ETH"
        return "bitcoin", "BTC"

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        async def _execute(inp: ToolInput) -> ToolOutput:
            normalized = self._normalize_query(inp.query)
            cache_key = self._cache_key(normalized)

            cached_quote = self._get_cached(cache_key)
            if cached_quote is not None:
                cached_confidence = self._compute_confidence(
                    is_live=False,
                    source_count=1,
                    multi_provider=False,
                    degraded=True,
                )
                return self._build_success_output(
                    quote=cached_quote,
                    source_quotes=[cached_quote],
                    providers_tried=["cache"],
                    confidence=cached_confidence,
                    fallback_used=True,
                    metadata_extra={"cache_hit": True, "cache_ttl_seconds": self._cache_ttl_seconds},
                )

            if self._is_gold_query(normalized):
                quotes, providers_tried, errors = await self._get_gold_quotes()
            elif self._is_crypto_query(normalized):
                quote = await self._get_crypto_quote(normalized)
                quotes = [quote] if quote is not None else []
                providers_tried = ["coingecko"]
                errors = [] if quote is not None else ["coingecko: no_data"]
            else:
                return ToolOutput(
                    success=False,
                    content="FinanceTool only supports market price requests (gold/crypto) in this version.",
                    error="unsupported_market_asset",
                    confidence=0.0,
                    metadata={
                        "source": "finance",
                        "intent": "market_price",
                        "providers_tried": "none",
                        "source_count": 0,
                        "fallback_used": False,
                    },
                )

            if not quotes:
                cached_stale = self._get_cached(cache_key, allow_stale=True)
                if cached_stale is not None:
                    stale_confidence = self._compute_confidence(
                        is_live=False,
                        source_count=1,
                        multi_provider=False,
                        degraded=True,
                    )
                    return self._build_success_output(
                        quote=cached_stale,
                        source_quotes=[cached_stale],
                        providers_tried=[*providers_tried, "cache_stale"],
                        confidence=stale_confidence,
                        fallback_used=True,
                        metadata_extra={
                            "cache_hit": True,
                            "cache_stale": True,
                            "cache_ttl_seconds": self._cache_ttl_seconds,
                            "provider_errors": " | ".join(errors) if errors else "none",
                        },
                    )

                source_hint_urls = ["https://www.kitco.com", "https://www.sjc.com.vn"]
                providers_text = ", ".join(providers_tried) if providers_tried else "none"
                degraded_confidence = self._compute_confidence(
                    is_live=False,
                    source_count=len(source_hint_urls),
                    multi_provider=len(providers_tried) > 1,
                    degraded=True,
                )
                return ToolOutput(
                    success=False,
                    content=(
                        "Unable to fetch real-time market price right now.\n\n"
                        "Please try again later or verify from:\n"
                        f"- {source_hint_urls[0]}\n"
                        f"- {source_hint_urls[1]}"
                    ),
                    error="finance_data_unavailable",
                    confidence=degraded_confidence,
                    metadata={
                        "source": "finance",
                        "provider": "finance_chain",
                        "intent": "market_price",
                        "providers_tried": providers_text,
                        "provider_errors": " | ".join(errors) if errors else "unknown",
                        "source_count": len(source_hint_urls),
                        "fallback_used": True,
                        "source_hints": source_hint_urls,
                    },
                    data={
                        "source_hints": source_hint_urls,
                        "documents": [
                            {
                                "title": "Kitco Gold Reference",
                                "snippet": "Reference source for gold market data.",
                                "url": "https://www.kitco.com",
                                "freshness": "live",
                                "published_at": datetime.now(tz=UTC).isoformat(),
                                "reliability": 0.75,
                                "provider": "kitco",
                            },
                            {
                                "title": "SJC Gold Reference",
                                "snippet": "Reference source for Vietnam gold pricing.",
                                "url": "https://www.sjc.com.vn",
                                "freshness": "live",
                                "published_at": datetime.now(tz=UTC).isoformat(),
                                "reliability": 0.7,
                                "provider": "sjc",
                            },
                        ],
                    },
                )

            final_quote, aggregated_confidence = self._aggregate_quotes(quotes)
            self._cache[cache_key] = (time.time(), final_quote)

            computed_confidence = self._compute_confidence(
                is_live=True,
                source_count=len(quotes),
                multi_provider=len({quote.source for quote in quotes}) > 1,
                degraded=False,
            )

            return self._build_success_output(
                quote=final_quote,
                source_quotes=quotes,
                providers_tried=providers_tried,
                confidence=max(aggregated_confidence, computed_confidence),
                fallback_used=False,
                metadata_extra={
                    "cache_hit": False,
                    "cache_ttl_seconds": self._cache_ttl_seconds,
                    "provider_errors": " | ".join(errors) if errors else "none",
                    "provider_count": len(quotes),
                },
            )

        return await self.execute_with_retry(tool_input, _execute)

    @staticmethod
    def _cache_key(normalized_query: str) -> str:
        if any(token in normalized_query for token in ("ethereum", "eth")):
            return "crypto:ethusd"
        if any(token in normalized_query for token in ("bitcoin", "btc")):
            return "crypto:btcusd"
        return "gold:xauusd"

    def _get_cached(self, cache_key: str, allow_stale: bool = False) -> FinanceQuote | None:
        entry = self._cache.get(cache_key)
        if entry is None:
            return None
        saved_at, quote = entry
        age = time.time() - saved_at
        if age <= self._cache_ttl_seconds:
            return quote
        if allow_stale and age <= self._cache_ttl_seconds * 4:
            return quote
        return None

    async def _get_gold_quotes(self) -> tuple[list[FinanceQuote], list[str], list[str]]:
        providers_tried: list[str] = []
        errors: list[str] = []
        quotes: list[FinanceQuote] = []

        provider_calls = [
            ("goldapi", self._get_gold_quote_via_goldapi),
            ("stooq", self._get_gold_quote_via_stooq),
            ("duckduckgo", self._get_gold_quote_via_duckduckgo),
        ]

        for provider_name, provider_call in provider_calls:
            providers_tried.append(provider_name)
            try:
                quote = await provider_call()
                if quote is not None:
                    quotes.append(quote)
                    # Keep latency bounded: stop the chain after the first valid quote.
                    # execute_with_retry applies a single-attempt timeout budget, so
                    # continuing to slower providers can cancel an otherwise successful run.
                    break
                else:
                    errors.append(f"{provider_name}: no_data")
            except Exception as err:
                errors.append(f"{provider_name}: {err}")

        return quotes, providers_tried, errors

    async def _get_gold_quote_via_goldapi(self) -> FinanceQuote | None:
        if not self._goldapi_key:
            return None

        url = "https://www.goldapi.io/api/XAU/USD"
        headers = {"x-access-token": self._goldapi_key, "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()

            price_raw = payload.get("price")
            if price_raw is None:
                return None
            price = float(price_raw)
            timestamp = str(payload.get("timestamp", ""))
            if timestamp.isdigit():
                dt = datetime.fromtimestamp(int(timestamp), tz=UTC)
                timestamp = dt.isoformat()
            if not timestamp:
                timestamp = datetime.now(tz=UTC).isoformat()

            return FinanceQuote(
                asset="gold",
                symbol="XAUUSD",
                price=price,
                currency="USD",
                timestamp=timestamp,
                source="goldapi",
                raw_url=url,
            )
        except Exception:
            return None

    async def _get_gold_quote_via_stooq(self) -> FinanceQuote | None:
        url = "https://stooq.com/q/l/?s=xauusd&i=d"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
                csv_text = response.text.strip()

            lines = [line for line in csv_text.splitlines() if line.strip()]
            if not lines:
                return None

            # Stooq may return either:
            # 1) header + data row, or
            # 2) a single data row without header.
            candidate_row = lines[-1]
            fields = [field.strip() for field in candidate_row.split(",")]
            if len(fields) < 7:
                return None

            # If we accidentally parsed a header row, abort.
            if fields[0].lower() == "symbol":
                return None

            symbol = fields[0] or "XAUUSD"
            date_part = fields[1]
            time_part = fields[2]
            close_part = fields[6]
            if close_part in {"N/D", "", "-"}:
                return None

            price = float(close_part)
            timestamp = f"{date_part}T{time_part}Z" if date_part and time_part else datetime.now(tz=UTC).isoformat()

            return FinanceQuote(
                asset="gold",
                symbol=symbol,
                price=price,
                currency="USD",
                timestamp=timestamp,
                source="stooq",
                raw_url=url,
            )
        except Exception:
            return None

    async def _get_gold_quote_via_duckduckgo(self) -> FinanceQuote | None:
        url = "https://api.duckduckgo.com/"
        params = {
            "q": "XAU USD gold price",
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url, params=params, headers={"User-Agent": "GlassBoxFinance/1.0"})
                response.raise_for_status()
                payload = response.json()

            candidates: list[str] = []
            abstract = str(payload.get("AbstractText", "")).strip()
            if abstract:
                candidates.append(abstract)
            for topic in payload.get("RelatedTopics", [])[:5]:
                if isinstance(topic, dict):
                    text = str(topic.get("Text", "")).strip()
                    if text:
                        candidates.append(text)

            if not candidates:
                return None

            price = self._extract_price_from_text(" ".join(candidates))
            if price is None:
                return None

            return FinanceQuote(
                asset="gold",
                symbol="XAUUSD",
                price=price,
                currency="USD",
                timestamp=datetime.now(tz=UTC).isoformat(),
                source="duckduckgo",
                raw_url="https://duckduckgo.com/?q=XAU+USD+gold+price",
            )
        except Exception:
            return None

    @staticmethod
    def _extract_price_from_text(text: str) -> float | None:
        candidates = re.findall(r"\b(\d{3,5}(?:[.,]\d{1,2})?)\b", text)
        for candidate in candidates:
            normalized = candidate.replace(",", ".")
            try:
                value = float(normalized)
            except ValueError:
                continue
            if 800.0 <= value <= 6000.0:
                return value
        return None

    @staticmethod
    def _aggregate_quotes(quotes: list[FinanceQuote]) -> tuple[FinanceQuote, float]:
        if len(quotes) == 1:
            return quotes[0], 0.87

        prices = sorted(q.price for q in quotes)
        median = prices[len(prices) // 2]
        tolerance = max(15.0, median * 0.01)
        filtered = [q for q in quotes if abs(q.price - median) <= tolerance]
        if not filtered:
            filtered = [quotes[0]]

        avg_price = sum(q.price for q in filtered) / len(filtered)
        base_quote = filtered[0]
        confidence = min(0.97, 0.72 + 0.1 * len(filtered))
        aggregated = FinanceQuote(
            asset=base_quote.asset,
            symbol=base_quote.symbol,
            price=avg_price,
            currency=base_quote.currency,
            timestamp=max(q.timestamp for q in filtered),
            source=",".join(dict.fromkeys(q.source for q in filtered)),
            raw_url=base_quote.raw_url,
        )
        return aggregated, confidence

    def _build_success_output(
        self,
        *,
        quote: FinanceQuote,
        source_quotes: list[FinanceQuote],
        providers_tried: list[str],
        confidence: float,
        fallback_used: bool,
        metadata_extra: dict[str, Any] | None = None,
    ) -> ToolOutput:
        content = (
            "Market Price\n\n"
            f"Asset: {quote.asset}\n"
            f"Symbol: {quote.symbol}\n"
            f"Price: {quote.price:.2f} {quote.currency}\n"
            f"Timestamp: {quote.timestamp}\n"
            f"Source: {quote.source}"
        )

        metadata = {
            "provider": quote.source,
            "intent": "market_price",
            "asset": quote.asset,
            "symbol": quote.symbol,
            "fallback_used": fallback_used,
            "providers_tried": ",".join(providers_tried) if providers_tried else "none",
            "source_count": max(1, len(source_quotes)),
            "freshness": "live",
        }
        if metadata_extra:
            metadata.update(metadata_extra)

        return ToolOutput(
            success=True,
            content=content,
            source_url=quote.raw_url,
            data={
                "market": {
                    "type": "market_price",
                    "asset": quote.asset,
                    "symbol": quote.symbol,
                    "price": quote.price,
                    "currency": quote.currency,
                    "timestamp": quote.timestamp,
                    "source": quote.source,
                },
                "documents": [
                    {
                        "title": f"{src.symbol} price from {src.source}",
                        "snippet": f"{src.symbol} = {src.price:.2f} {src.currency} at {src.timestamp}",
                        "url": src.raw_url,
                        "freshness": "live",
                        "published_at": src.timestamp,
                        "reliability": 0.92,
                        "provider": src.source,
                    }
                    for src in source_quotes
                ],
                "summary": content,
            },
            confidence=confidence,
            metadata=metadata,
        )

    async def _get_crypto_quote(self, normalized_query: str) -> FinanceQuote | None:
        coin_id, symbol = self._select_crypto_id(normalized_query)
        url = "https://api.coingecko.com/api/v3/simple/price"
        params: dict[str, Any] = {
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_last_updated_at": "true",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()

            coin_payload = payload.get(coin_id) or {}
            price_raw = coin_payload.get("usd")
            if price_raw is None:
                return None
            price = float(price_raw)
            last_updated = coin_payload.get("last_updated_at")
            if isinstance(last_updated, int):
                timestamp = datetime.fromtimestamp(last_updated, tz=UTC).isoformat()
            else:
                timestamp = datetime.now(tz=UTC).isoformat()

            return FinanceQuote(
                asset="crypto",
                symbol=symbol,
                price=price,
                currency="USD",
                timestamp=timestamp,
                source="coingecko",
                raw_url=f"{url}?ids={coin_id}&vs_currencies=usd",
            )
        except Exception:
            return None
