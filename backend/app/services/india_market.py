from __future__ import annotations

import copy
import statistics
import threading
import time
from datetime import date, datetime, timedelta

from ..config import settings
from .instruments import NIFTY50_STOCKS
from .integrations.upstox import UpstoxError, upstox_client
from .integrations.yahoo_finance import (
    IST,
    YahooFinanceError,
    iso_ist,
    yahoo_client,
)

YAHOO_SOURCE = "Yahoo Finance (NSE)"
UPSTOX_SOURCE = "Upstox API"
YAHOO_DELAY_NOTE = (
    "NSE quotes on Yahoo Finance are unofficial and typically delayed, not tick-level. "
    "Every row keeps its own provider timestamp."
)
STALE_AFTER_MINUTES = 4 * 24 * 60
SPARK_POINTS = 24
RANGES: dict[str, tuple[str, str]] = {
    "1d": ("1d", "5m"),
    "5d": ("5d", "15m"),
    "1mo": ("1mo", "1d"),
    "3mo": ("3mo", "1d"),
    "1y": ("1y", "1d"),
}

INDICES: tuple[dict[str, str], ...] = (
    {"symbol": "NIFTY50", "name": "NIFTY 50", "yahoo": "^NSEI", "upstox": "NSE_INDEX|Nifty 50"},
    {"symbol": "BANKNIFTY", "name": "NIFTY Bank", "yahoo": "^NSEBANK", "upstox": "NSE_INDEX|Nifty Bank"},
    {"symbol": "SENSEX", "name": "BSE SENSEX", "yahoo": "^BSESN", "upstox": "BSE_INDEX|SENSEX"},
)

STOCKS: tuple[dict[str, str], ...] = tuple(
    {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "upstox": instrument_key,
        "yahoo": f"{symbol}.NS",
    }
    for symbol, name, sector, instrument_key, _ in NIFTY50_STOCKS
)
STOCK_BY_SYMBOL = {stock["symbol"]: stock for stock in STOCKS}

_CACHE: dict[str, tuple[float, dict]] = {}
_LAST_GOOD: dict[str, dict] = {}
_LOCK = threading.Lock()


def _cache_get(key: str) -> dict | None:
    with _LOCK:
        entry = _CACHE.get(key)
    if not entry:
        return None
    stored_at, payload = entry
    if time.time() - stored_at > payload.get("_ttl", 60):
        with _LOCK:
            _CACHE.pop(key, None)
        return None
    return {k: v for k, v in payload.items() if k != "_ttl"}


def _cache_put(key: str, payload: dict, ttl: int) -> dict:
    with _LOCK:
        _CACHE[key] = (time.time(), {**payload, "_ttl": ttl})
    return payload


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
        _LAST_GOOD.clear()


def _remember(key: str, payload: dict) -> None:
    with _LOCK:
        _LAST_GOOD[key] = copy.deepcopy(payload)


def _last_good(key: str) -> dict | None:
    with _LOCK:
        payload = _LAST_GOOD.get(key)
    return copy.deepcopy(payload) if payload else None


def _mark_stale(payload: dict, errors: list[str]) -> dict:
    payload["data_mode"] = "stale"
    payload["provider"] = {**payload.get("provider", {}), "errors": errors, "stale": True}
    payload["stale"] = True
    payload["stale_note"] = (
        "The market provider is unreachable. Showing the last successfully fetched snapshot; "
        "prices may be older than they appear. Nothing is refreshed or invented."
    )
    return payload


def _provider() -> str:
    return "upstox" if settings.upstox_configured else "yahoo"


def _source(provider: str) -> str:
    return UPSTOX_SOURCE if provider == "upstox" else YAHOO_SOURCE


def _session(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    minute = now.hour * 60 + now.minute
    weekday = now.weekday() < 5
    if weekday and 9 * 60 + 15 <= minute < 15 * 60 + 30:
        state, label = "open", "Market open"
    elif weekday and 9 * 60 <= minute < 9 * 60 + 15:
        state, label = "pre_open", "Pre-open"
    elif weekday and minute >= 15 * 60 + 30:
        state, label = "closed", "Closed today"
    else:
        state, label = "closed", "Closed"
    return {
        "state": state,
        "label": label,
        "ist_time": now.strftime("%H:%M IST"),
        "ist_date": now.date().isoformat(),
        "regular_hours": "09:15–15:30 IST, Monday to Friday",
        "note": "NSE trading holidays are not detected by this clock.",
    }


def _age_minutes(as_of: str | None) -> int | None:
    if not as_of:
        return None
    try:
        parsed = datetime.fromisoformat(as_of)
    except ValueError:
        return None
    now = datetime.now(IST)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return max(0, int((now - parsed.astimezone(IST)).total_seconds() // 60))


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _yahoo_quote(meta: dict, spark: list[float]) -> dict | None:
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    price = float(price)
    previous = meta.get("previousClose") or meta.get("chartPreviousClose") or price
    previous = float(previous)
    change_pct = meta.get("regularMarketChangePercent")
    if change_pct is None:
        change_pct = ((price - previous) / previous * 100) if previous else 0.0
    as_of = iso_ist(meta.get("regularMarketTime"))
    age = _age_minutes(as_of)
    is_stale = age is not None and age > STALE_AFTER_MINUTES
    return {
        "price": _round(price),
        "previous_close": _round(previous),
        "change_pct": _round(change_pct),
        "day_high": _round(meta.get("regularMarketDayHigh")),
        "day_low": _round(meta.get("regularMarketDayLow")),
        "high_52w": _round(meta.get("fiftyTwoWeekHigh")),
        "low_52w": _round(meta.get("fiftyTwoWeekLow")),
        "volume": meta.get("regularMarketVolume"),
        "currency": meta.get("currency") or "INR",
        "exchange": meta.get("fullExchangeName") or "NSE",
        "as_of": as_of,
        "age_minutes": age,
        "source": YAHOO_SOURCE,
        "data_mode": "delayed",
        "freshness": "stale" if is_stale else "delayed",
        "is_stale": is_stale,
        "spark": [_round(value) for value in spark[-SPARK_POINTS:]],
        "note": (
            "Last known delayed price; the feed looks stale."
            if is_stale
            else "Delayed NSE quote from Yahoo Finance. Not tick-level exchange data."
        ),
    }


def _upstox_quote(payload: dict) -> dict:
    price = float(payload["price"])
    previous = float(payload.get("previous_close") or price)
    return {
        "price": _round(price),
        "previous_close": _round(previous),
        "change_pct": _round(payload.get("change_pct")),
        "day_high": None,
        "day_low": None,
        "high_52w": None,
        "low_52w": None,
        "volume": payload.get("volume"),
        "currency": "INR",
        "exchange": "NSE",
        "as_of": iso_ist(payload.get("as_of")) if isinstance(payload.get("as_of"), (int, float)) else payload.get("as_of"),
        "age_minutes": 0,
        "source": UPSTOX_SOURCE,
        "data_mode": "live",
        "freshness": "live",
        "is_stale": False,
        "spark": [],
        "note": "Live NSE quote from Upstox.",
    }


def _fetch_quotes(targets: list[dict[str, str]]) -> tuple[dict[str, dict], list[str], str]:
    errors: list[str] = []
    provider = _provider()
    if provider == "upstox":
        try:
            payloads = upstox_client.get_quotes([target["upstox"] for target in targets])
            quotes = {
                target["symbol"]: _upstox_quote(payloads[target["upstox"]])
                for target in targets
                if target["upstox"] in payloads
            }
            if quotes:
                return quotes, errors, "upstox"
            errors.append("Upstox returned no quotes.")
        except (UpstoxError, KeyError) as exc:
            errors.append(f"Upstox: {exc}")
    try:
        payload = yahoo_client.spark([target["yahoo"] for target in targets])
    except YahooFinanceError as exc:
        errors.append(f"Yahoo Finance: {exc}")
        return {}, errors, "yahoo"
    by_yahoo = {target["yahoo"]: target for target in targets}
    quotes: dict[str, dict] = {}
    for yahoo_symbol, entry in payload.items():
        target = by_yahoo.get(yahoo_symbol) or by_yahoo.get(yahoo_symbol.upper())
        if target is None:
            continue
        quote = _yahoo_quote(entry["meta"], entry["spark"])
        if quote:
            quotes[target["symbol"]] = quote
    return quotes, errors, "yahoo"


def _targets() -> list[dict[str, str]]:
    indices = [
        {"symbol": item["symbol"], "yahoo": item["yahoo"], "upstox": item["upstox"]}
        for item in INDICES
    ]
    stocks = [
        {"symbol": item["symbol"], "yahoo": item["yahoo"], "upstox": item["upstox"]}
        for item in STOCKS
    ]
    return indices + stocks


def _row(base: dict[str, str], quote: dict | None) -> dict:
    return {
        "symbol": base["symbol"],
        "name": base["name"],
        "sector": base.get("sector"),
        "exchange": "NSE",
        "currency": "INR",
        "yahoo_symbol": base["yahoo"],
        "instrument_key": base["upstox"] if base["upstox"].startswith("NSE_EQ|") else None,
        "quote": quote,
    }


def _summary(stocks: list[dict]) -> dict:
    priced = [item["quote"] for item in stocks if item.get("quote") and item["quote"]["price"] is not None]
    changes = [quote["change_pct"] for quote in priced if quote.get("change_pct") is not None]
    advancers = sum(1 for change in changes if change > 0.05)
    decliners = sum(1 for change in changes if change < -0.05)
    unchanged = len(changes) - advancers - decliners
    return {
        "requested": len(stocks),
        "covered": len(priced),
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "breadth_pct": round(advancers / len(changes) * 100, 1) if changes else None,
        "average_change_pct": round(sum(changes) / len(changes), 2) if changes else None,
        "median_change_pct": round(statistics.median(changes), 2) if changes else None,
        "total_volume": sum(int(quote.get("volume") or 0) for quote in priced),
        "mood": "Advancing"
        if changes and advancers / len(changes) >= 0.6
        else "Declining"
        if changes and decliners / len(changes) >= 0.6
        else "Mixed"
        if changes
        else None,
    }


def overview(force: bool = False) -> dict:
    if not force:
        cached = _cache_get("overview")
        if cached:
            return cached
    quotes, errors, provider = _fetch_quotes(_targets())
    indices = [_row(item, quotes.get(item["symbol"])) for item in INDICES]
    stocks = [_row(item, quotes.get(item["symbol"])) for item in STOCKS]
    covered = sum(1 for item in stocks if item["quote"])
    if not covered:
        fallback = _last_good("overview")
        if fallback:
            return _mark_stale(fallback, errors)
    data_mode = (
        "live"
        if provider == "upstox" and covered
        else "delayed"
        if covered
        else "unavailable"
    )
    payload = {
        "available": covered > 0,
        "data_mode": data_mode,
        "source": _source(provider) if covered else None,
        "provider": {
            "name": provider,
            "configured": True,
            "keyless": provider == "yahoo",
            "upstox_configured": settings.upstox_configured,
            "delay_note": YAHOO_DELAY_NOTE if provider == "yahoo" else "Live quotes from Upstox.",
            "errors": errors,
        },
        "session": _session(),
        "indices": indices,
        "stocks": stocks,
        "coverage": {"covered": covered, "requested": len(STOCKS)},
        "summary": _summary(stocks),
        "fetched_at": datetime.now(IST),
        "cache_seconds": settings.INDIA_MARKET_CACHE_SECONDS,
        "notes": {
            "prices": (
                "Real NSE prices, delayed by the provider. They are not the FINOVEXA simulator and "
                "must not be shown as live tick data."
            ),
            "session": "The clock uses IST regular hours only; exchange holidays are not detected.",
            "orders": (
                "This panel is read-only. Orders go through the approval-gated trade desk with its own quote "
                "provenance."
            ),
        },
        "disclosures": [
            "Delayed market data: informational only, not exchange-grade or suitable for automated trading.",
            "Not investment advice. No signal, rating or target price is derived from this feed.",
            "No order, holding, cash or position changes from viewing this panel.",
        ],
    }
    ttl = 15 if not covered else max(15, settings.INDIA_MARKET_CACHE_SECONDS)
    payload["stale"] = False
    if covered:
        _remember("overview", payload)
    return _cache_put("overview", payload, ttl)


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(sum(values[-window:]) / window, 2)


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    deltas = [b - a for a, b in zip(closes[-period - 1 : -1], closes[-period:])]
    gains = sum(delta for delta in deltas if delta > 0) / period
    losses = sum(-delta for delta in deltas if delta < 0) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return round(100.0 - 100.0 / (1.0 + rs), 1)


def _indicators(closes: list[float], price: float, quote: dict) -> dict:
    high = quote.get("high_52w") or (max(closes) if closes else None)
    low = quote.get("low_52w") or (min(closes) if closes else None)
    position = None
    if high is not None and low is not None and high > low:
        position = round((price - low) / (high - low) * 100, 1)
    return {
        "sma20": _sma(closes, 20),
        "sma50": _sma(closes, 50),
        "rsi14": _rsi(closes),
        "high_52w": high,
        "low_52w": low,
        "position_52w_pct": position,
        "samples": len(closes),
    }


def _daily_closes(provider: str, meta: dict[str, str]) -> tuple[list[float], str | None]:
    try:
        if provider == "upstox":
            candles = upstox_client.get_historical(
                meta["upstox"], date.today() - timedelta(days=365), date.today()
            )
        else:
            chart = yahoo_client.chart(meta["yahoo"], range_="1y", interval="1d")
            candles = chart["candles"]
        return [float(candle["close"]) for candle in candles if candle.get("close")], None
    except (UpstoxError, YahooFinanceError) as exc:
        return [], str(exc)


def _intraday(provider: str, meta: dict[str, str], range_: str) -> tuple[list[dict], list[float], dict | None, str | None]:
    range_value, interval = RANGES[range_]
    try:
        if provider == "upstox":
            candles = upstox_client.get_historical(
                meta["upstox"],
                date.today() - timedelta(days=30 if range_ in ("1mo", "3mo", "1y") else 7),
                date.today(),
            )
            payload = upstox_client.get_quote(meta["upstox"])
            return (
                [{"time": candle["date"], "close": candle["close"], "volume": candle.get("volume")} for candle in candles],
                [float(candle["close"]) for candle in candles if candle.get("close")],
                _upstox_quote(payload),
                None,
            )
        chart = yahoo_client.chart(meta["yahoo"], range_=range_value, interval=interval)
        meta_payload = chart["meta"]
        quote = _yahoo_quote(meta_payload, chart["spark"])
        return chart["candles"], chart["spark"], quote, None
    except (UpstoxError, YahooFinanceError) as exc:
        return [], [], None, str(exc)


def stock_detail(symbol: str, range_: str = "1d") -> dict:
    symbol = symbol.upper()
    meta = STOCK_BY_SYMBOL.get(symbol)
    if meta is None:
        raise KeyError(symbol)
    if range_ not in RANGES:
        raise ValueError("Range must be one of 1d, 5d, 1mo, 3mo or 1y.")
    cache_key = f"stock:{symbol}:{range_}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    provider = _provider()
    errors: list[str] = []
    candles, spark, quote, intraday_error = _intraday(provider, meta, range_)
    if intraday_error:
        errors.append(intraday_error)
    if quote is None and provider == "upstox":
        # Upstox failed for this symbol; fall back to the keyless delayed feed.
        provider = "yahoo"
        candles, spark, quote, intraday_error = _intraday(provider, meta, range_)
        if intraday_error:
            errors.append(intraday_error)
    if quote is None:
        try:
            dataset = yahoo_client.spark([meta["yahoo"]])
            entry = dataset.get(meta["yahoo"])
            quote = _yahoo_quote(entry["meta"], entry["spark"]) if entry else None
            provider = "yahoo"
        except YahooFinanceError as exc:
            errors.append(f"Yahoo Finance: {exc}")
    if quote is None:
        fallback = _last_good(cache_key)
        if fallback:
            return _mark_stale(fallback, errors)
        reason = "; ".join(errors) or "No market data is available for this stock right now."
        raise YahooFinanceError(f"{reason} Nothing is substituted.")

    closes, daily_error = _daily_closes(provider, meta)
    if daily_error:
        errors.append(daily_error)
    indicators = _indicators(closes, float(quote["price"]), quote)
    if quote.get("high_52w") is None:
        quote["high_52w"] = indicators["high_52w"]
        quote["low_52w"] = indicators["low_52w"]

    if range_ in ("1mo", "3mo", "1y") and candles:
        keep = {"1mo": 31, "3mo": 92, "1y": 366}[range_]
        cutoff = datetime.now(IST).date() - timedelta(days=keep)
        filtered = []
        for candle in candles:
            try:
                candle_date = date.fromisoformat(str(candle["time"])[:10])
            except ValueError:
                continue
            if candle_date >= cutoff:
                filtered.append(candle)
        candles = filtered or candles

    payload = {
        "symbol": symbol,
        "name": meta["name"],
        "sector": meta["sector"],
        "exchange": "NSE",
        "currency": "INR",
        "yahoo_symbol": meta["yahoo"],
        "instrument_key": meta["upstox"],
        "quote": quote,
        "range": range_,
        "interval": RANGES[range_][1],
        "candles": candles,
        "spark": [round(float(value), 2) for value in spark[-SPARK_POINTS:]],
        "indicators": indicators,
        "provider": {
            "name": provider,
            "delay_note": YAHOO_DELAY_NOTE if provider == "yahoo" else "Live quotes from Upstox.",
            "errors": errors,
        },
        "session": _session(),
        "data_mode": quote["data_mode"],
        "source": quote["source"],
        "fetched_at": datetime.now(IST),
        "disclosures": [
            "Delayed market data: informational only, not exchange-grade or suitable for automated trading.",
            "Technical indicators are arithmetic summaries of the provider's candles, not recommendations.",
            "Viewing this detail does not place an order or change cash, holdings or positions.",
        ],
    }
    ttl = 60 if range_ == "1d" else 300
    payload["stale"] = False
    _remember(cache_key, payload)
    return _cache_put(cache_key, payload, ttl)


def provider_status() -> dict:
    return {
        "active": _provider(),
        "upstox_configured": settings.upstox_configured,
        "yahoo_configured": yahoo_client.configured,
        "source": _source(_provider()),
    }
