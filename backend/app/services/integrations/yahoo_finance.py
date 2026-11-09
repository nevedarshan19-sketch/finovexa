from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from ...config import settings

IST = timezone(timedelta(hours=5, minutes=30))
MAX_SYMBOLS_PER_CALL = 20
# A full browser UA is rejected by Yahoo's bot filter; a minimal one is accepted.
USER_AGENT = "Mozilla/5.0"


class YahooFinanceError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def iso_ist(epoch: Any) -> str | None:
    if not isinstance(epoch, (int, float)):
        return None
    return datetime.fromtimestamp(epoch, IST).isoformat()


class YahooFinanceClient:
    """Keyless NSE/BSE quote source.

    Yahoo's public endpoints are unofficial and typically delayed, so every
    consumer must label the numbers as delayed rather than exchange-grade.
    """

    @property
    def base_url(self) -> str:
        return settings.YAHOO_FINANCE_BASE_URL.rstrip("/")

    @property
    def base_urls(self) -> list[str]:
        primary = self.base_url
        secondary = (
            primary.replace("//query1.", "//query2.")
            if "//query1." in primary
            else primary
        )
        return [primary] if secondary == primary else [primary, secondary]

    @property
    def configured(self) -> bool:
        return bool(settings.YAHOO_FINANCE_BASE_URL)

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept": "application/json"}

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        if not self.configured:
            raise YahooFinanceError("The Yahoo Finance base URL is not configured.")
        last_error: YahooFinanceError | None = None
        for base in self.base_urls:
            try:
                response = httpx.get(
                    f"{base}{path}",
                    params=params,
                    headers=self._headers(),
                    timeout=15,
                )
            except httpx.TimeoutException:
                last_error = YahooFinanceError("Yahoo Finance did not answer in time.")
                continue
            except httpx.HTTPError:
                last_error = YahooFinanceError("Could not reach Yahoo Finance.")
                continue
            if response.status_code == 429:
                last_error = YahooFinanceError(
                    "Yahoo Finance rate limit reached. Try again in a minute.",
                    status_code=429,
                )
                continue
            if response.status_code >= 500:
                last_error = YahooFinanceError(
                    f"Yahoo Finance is unavailable ({response.status_code}).",
                    status_code=response.status_code,
                )
                continue
            if response.status_code >= 400:
                raise YahooFinanceError(
                    f"Yahoo Finance request failed ({response.status_code}).",
                    status_code=response.status_code,
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise YahooFinanceError(
                    "Yahoo Finance returned an unreadable response."
                ) from exc
            if not isinstance(body, dict):
                raise YahooFinanceError("Yahoo Finance returned an unexpected response.")
            return body
        raise last_error or YahooFinanceError("Yahoo Finance is unavailable.")

    @staticmethod
    def _parse_entry(symbol: str, entry: dict) -> dict | None:
        responses = entry.get("response") or []
        if not responses or not isinstance(responses[0], dict):
            return None
        response = responses[0]
        meta = response.get("meta") or {}
        if _number(meta.get("regularMarketPrice")) is None:
            return None
        quote_blocks = ((response.get("indicators") or {}).get("quote")) or []
        closes = (quote_blocks[0] or {}).get("close") if quote_blocks else []
        return {
            "symbol": symbol,
            "meta": meta,
            "spark": [value for value in (_number(item) for item in closes or []) if value is not None],
        }

    def spark(
        self, symbols: list[str], *, range_: str = "1d", interval: str = "5m"
    ) -> dict[str, dict]:
        unique = list(dict.fromkeys(symbol for symbol in symbols if symbol))
        if not unique:
            return {}
        quotes: dict[str, dict] = {}
        for start in range(0, len(unique), MAX_SYMBOLS_PER_CALL):
            chunk = unique[start : start + MAX_SYMBOLS_PER_CALL]
            body = self._get(
                "/v7/finance/spark",
                {
                    "symbols": ",".join(chunk),
                    "range": range_,
                    "interval": interval,
                },
            )
            block = body.get("spark") or {}
            error = block.get("error")
            if error:
                description = " ".join(str(error.get("description") or "").split())[:200]
                raise YahooFinanceError(
                    description or "Yahoo Finance rejected the quote request."
                )
            for entry in block.get("result") or []:
                if not isinstance(entry, dict):
                    continue
                symbol = str(entry.get("symbol") or "")
                parsed = self._parse_entry(symbol, entry)
                if parsed:
                    quotes[symbol.upper()] = parsed
        return quotes

    def chart(
        self, symbol: str, *, range_: str = "1d", interval: str = "5m"
    ) -> dict:
        body = self._get(
            f"/v8/finance/chart/{quote(symbol, safe='')}",
            {"range": range_, "interval": interval},
        )
        chart = body.get("chart") or {}
        error = chart.get("error")
        result = chart.get("result") or []
        if error or not result:
            description = " ".join(str((error or {}).get("description") or "").split())[:200]
            raise YahooFinanceError(
                description or f"No market series is available for {symbol}."
            )
        payload = result[0]
        meta = payload.get("meta") or {}
        timestamps = payload.get("timestamp") or []
        blocks = ((payload.get("indicators") or {}).get("quote")) or [{}]
        block = blocks[0] or {}
        opens = block.get("open") or []
        highs = block.get("high") or []
        lows = block.get("low") or []
        closes = block.get("close") or []
        volumes = block.get("volume") or []

        candles = []
        for index, epoch in enumerate(timestamps):
            close = _number(closes[index]) if index < len(closes) else None
            if close is None:
                continue
            candles.append(
                {
                    "time": iso_ist(epoch),
                    "open": _number(opens[index]) if index < len(opens) else None,
                    "high": _number(highs[index]) if index < len(highs) else None,
                    "low": _number(lows[index]) if index < len(lows) else None,
                    "close": close,
                    "volume": _number(volumes[index]) if index < len(volumes) else None,
                }
            )
        return {
            "symbol": symbol,
            "meta": meta,
            "candles": candles,
            "spark": [candle["close"] for candle in candles],
        }


yahoo_client = YahooFinanceClient()
