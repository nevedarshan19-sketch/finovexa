from __future__ import annotations

import csv
import io
import math
import statistics
import threading
import time
from datetime import datetime

import httpx

from ..config import settings
from .india_market import IST, overview as india_overview
from .instruments import NIFTY50_STOCKS
from .integrations.yahoo_finance import (
    YahooFinanceError,
    iso_ist,
    yahoo_client,
)

ANALYSIS_VERSION = "nifty50-technical-v1"
NSE_CONSTITUENTS_URL = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
CONSTITUENT_TTL_SECONDS = 24 * 60 * 60
MIN_HISTORY_SESSIONS = 50

HORIZONS: dict[str, dict] = {
    "1m": {"label": "1 month", "sessions": 21, "scale": 0.35},
    "3m": {"label": "3 months", "sessions": 63, "scale": 1.0},
    "6m": {"label": "6 months", "sessions": 126, "scale": 1.6},
}
DEFAULT_HORIZON = "3m"

_CONFIDENCE_LABELS = ((70, "high", "High"), (50, "medium", "Medium"), (0, "low", "Low"))

_CACHE: dict[str, tuple[float, dict]] = {}
_CONSTITUENTS: tuple[float, list[dict], dict] | None = None
_LOCK = threading.Lock()
# Serialises cold builds so a burst of public requests cannot stampede the providers.
_BUILD_LOCK = threading.Lock()


def clear_cache() -> None:
    global _CONSTITUENTS
    with _LOCK:
        _CACHE.clear()
        _CONSTITUENTS = None


def _bundled_constituents() -> list[dict]:
    return [
        {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "isin": instrument_key.split("|", 1)[1] if "|" in instrument_key else None,
            "upstox": instrument_key,
            "yahoo": f"{symbol}.NS",
            "exchange_token": exchange_token,
        }
        for symbol, name, sector, instrument_key, exchange_token in NIFTY50_STOCKS
    ]


def _parse_nse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    bundled = {item["symbol"]: item for item in _bundled_constituents()}
    items: list[dict] = []
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        series = (row.get("Series") or "EQ").strip().upper()
        if not symbol or series != "EQ":
            continue
        isin = (row.get("ISIN Code") or "").strip() or None
        known = bundled.get(symbol)
        items.append(
            {
                "symbol": symbol,
                "name": (row.get("Company Name") or symbol).strip(),
                "sector": (row.get("Industry") or (known or {}).get("sector") or "Unclassified").strip(),
                "isin": isin or (known or {}).get("isin"),
                "upstox": (known or {}).get("upstox") or (f"NSE_EQ|{isin}" if isin else None),
                "yahoo": (known or {}).get("yahoo") or f"{symbol}.NS",
                "exchange_token": (known or {}).get("exchange_token"),
            }
        )
    symbols = [item["symbol"] for item in items]
    if not 45 <= len(symbols) <= 60 or len(set(symbols)) != len(symbols):
        raise ValueError("The constituent file did not contain a plausible NIFTY 50 list.")
    return items


def _constituents() -> tuple[list[dict], dict]:
    global _CONSTITUENTS
    now = time.time()
    with _LOCK:
        cached = _CONSTITUENTS
    if cached and now - cached[0] < CONSTITUENT_TTL_SECONDS:
        return cached[1], cached[2]

    source: dict = {
        "name": "NSE NIFTY 50 constituents (official file)",
        "url": NSE_CONSTITUENTS_URL,
        "retrieved_at": None,
        "fallback": False,
        "note": "Constituents are refreshed from NSE daily and fall back to a bundled snapshot when NSE cannot be reached.",
        "errors": [],
    }
    items: list[dict] | None = None
    if settings.NIFTY_CONSTITUENT_REFRESH and settings.ENV != "test":
        try:
            response = httpx.get(
                NSE_CONSTITUENTS_URL,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"},
                timeout=6,
            )
            response.raise_for_status()
            items = _parse_nse_csv(response.text)
            source["retrieved_at"] = datetime.now(IST).isoformat()
        except Exception as exc:  # network and parsing problems both fall back
            source["errors"].append(f"NSE constituents: {exc}")
    if items is None:
        items = _bundled_constituents()
        source["fallback"] = True
        source["name"] = "Bundled NSE NIFTY 50 snapshot"
        source["retrieved_at"] = None
    source["count"] = len(items)
    with _LOCK:
        _CONSTITUENTS = (now, items, source)
    return items, source


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    deltas = [b - a for a, b in zip(closes[-period - 1 : -1], closes[-period:])]
    gains = sum(delta for delta in deltas if delta > 0) / period
    losses = sum(-delta for delta in deltas if delta < 0) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def _daily_volatility(closes: list[float], window: int = 63) -> float | None:
    sample = closes[-(window + 1) :]
    if len(sample) < 10:
        return None
    returns = [b / a - 1.0 for a, b in zip(sample, sample[1:]) if a > 0]
    if len(returns) < 10:
        return None
    return statistics.pstdev(returns) * math.sqrt(252) * 100


def _minimal_quote(entry: dict) -> dict | None:
    meta = entry.get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    price = float(price)
    previous = float(meta.get("previousClose") or meta.get("chartPreviousClose") or price)
    return {
        "price": _round(price),
        "previous_close": _round(previous),
        "change_pct": _round(((price - previous) / previous * 100) if previous else 0.0),
        "high_52w": _round(meta.get("fiftyTwoWeekHigh")),
        "low_52w": _round(meta.get("fiftyTwoWeekLow")),
        "volume": meta.get("regularMarketVolume"),
        "currency": meta.get("currency") or "INR",
        "exchange": "NSE",
        "as_of": iso_ist(meta.get("regularMarketTime")),
        "age_minutes": None,
        "source": "Yahoo Finance (NSE)",
        "data_mode": "delayed",
        "freshness": "delayed",
        "is_stale": False,
        "note": "Delayed NSE quote from Yahoo Finance.",
    }


def _quote_map(items: list[dict], errors: list[str]) -> tuple[dict[str, dict], dict]:
    payload = india_overview()
    provider = payload.get("provider") or {}
    errors.extend(provider.get("errors") or [])
    quotes = {
        row["symbol"]: row["quote"]
        for row in payload.get("stocks", [])
        if row.get("quote") and row["quote"].get("price") is not None
    }
    missing = [item for item in items if item["symbol"] not in quotes]
    if missing:
        try:
            dataset = yahoo_client.spark([item["yahoo"] for item in missing])
        except YahooFinanceError as exc:
            errors.append(f"Yahoo Finance: {exc}")
        else:
            for item in missing:
                entry = dataset.get(item["yahoo"]) or dataset.get(item["yahoo"].upper())
                quote = _minimal_quote(entry) if entry else None
                if quote:
                    quotes[item["symbol"]] = quote
    provenance = {
        "quote_provider": provider.get("name") or ("upstox" if settings.upstox_configured else "yahoo"),
        "quote_source": payload.get("source"),
        "quote_mode": payload.get("data_mode"),
        "delay_note": provider.get("delay_note"),
        "session": payload.get("session"),
    }
    return quotes, provenance


def _history(items: list[dict], errors: list[str]) -> dict[str, list[float]]:
    try:
        dataset = yahoo_client.spark(
            [item["yahoo"] for item in items], range_="1y", interval="1d"
        )
    except YahooFinanceError as exc:
        errors.append(f"Yahoo Finance daily closes: {exc}")
        return {}
    series: dict[str, list[float]] = {}
    for item in items:
        entry = dataset.get(item["yahoo"]) or dataset.get(item["yahoo"].upper())
        closes = [float(value) for value in (entry or {}).get("spark", []) if value]
        if closes:
            series[item["symbol"]] = closes
    return series


def _confidence_label(score: int) -> tuple[str, str]:
    for threshold, key, label in _CONFIDENCE_LABELS:
        if score >= threshold:
            return key, label
    return "low", "Low"


def _insufficient(item: dict, quote: dict | None, close_count: int, horizon: str) -> dict:
    reasons: list[str] = []
    if quote is None or quote.get("price") is None:
        reasons.append("No verified price is available from the configured provider.")
    if close_count < MIN_HISTORY_SESSIONS:
        reasons.append(
            f"Only {close_count} daily closes were available; at least {MIN_HISTORY_SESSIONS} are required."
        )
    return {
        "symbol": item["symbol"],
        "name": item["name"],
        "sector": item["sector"],
        "classification": "insufficient_data",
        "signal_label": "Insufficient data",
        "price": quote.get("price") if quote else None,
        "price_as_of": quote.get("as_of") if quote else None,
        "price_source": quote.get("source") if quote else None,
        "price_note": quote.get("note") if quote else None,
        "data_mode": quote.get("data_mode") if quote else "unavailable",
        "freshness": quote.get("freshness") if quote else "unavailable",
        "is_stale": bool(quote.get("is_stale")) if quote else False,
        "target_price": None,
        "upside_pct": None,
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon]["label"],
        "confidence": None,
        "indicators": {"available": False, "closes": close_count},
        "fundamentals": {
            "available": False,
            "used": False,
            "note": "No licensed fundamental feed is configured. Fundamentals are not estimated.",
        },
        "reasons": ["The model cannot produce a target without a price and enough daily history."],
        "risks": reasons,
        "analysis_at": None,
        "methodology_version": ANALYSIS_VERSION,
    }


def analyse_one(
    item: dict, quote: dict | None, closes: list[float], horizon: str
) -> dict:
    """Build one card from a provider quote and daily closes. Pure and deterministic."""
    if quote is None or quote.get("price") is None or len(closes) < MIN_HISTORY_SESSIONS:
        return _insufficient(item, quote, len(closes), horizon)

    price = float(quote["price"])
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    rsi = _rsi(closes)
    momentum_3m = (price / closes[-64] - 1.0) * 100 if len(closes) >= 64 and closes[-64] else None
    momentum_1m = (price / closes[-22] - 1.0) * 100 if len(closes) >= 22 and closes[-22] else None
    volatility = _daily_volatility(closes)
    high_52w = quote.get("high_52w") or max(closes)
    low_52w = quote.get("low_52w") or min(closes)
    position_52w = (
        (price - low_52w) / (high_52w - low_52w) * 100 if high_52w > low_52w else None
    )

    trend_gap = (price / sma50 - 1.0) if sma50 else 0.0
    raw = 0.55 * trend_gap + 0.35 * ((momentum_3m or 0.0) / 100.0)
    raw = _clamp(raw, -0.12, 0.15)
    vol_drag = _clamp(((volatility or 25.0) - 18.0) / 100.0, 0.0, 0.25)
    scale = HORIZONS[horizon]["scale"]
    expected_move = _clamp(raw * scale - 0.25 * vol_drag * scale, -0.20, 0.30)
    target = round(price * (1.0 + expected_move), 2)
    upside = round(((target - price) / price) * 100, 2) if price else None

    score = 50
    score += 10 if trend_gap > 0 else -10
    score += 10 if (momentum_3m or 0) > 0 else -10
    score += 8 if rsi is not None and 45 <= rsi <= 65 else -6 if rsi is not None and rsi > 75 else 0
    score += 5 if len(closes) >= 200 else -5
    score -= int(min(20, max(0.0, (volatility or 0.0) - 25.0) * 0.8))
    if position_52w is not None and position_52w < 15:
        score -= 8
    score = int(_clamp(score, 5, 90))
    confidence_key, confidence_label = _confidence_label(score)

    reasons: list[str] = []
    if sma50 is not None:
        gap = (price / sma50 - 1.0) * 100
        direction = "above" if gap >= 0 else "below"
        reasons.append(f"Price is {abs(gap):.1f}% {direction} its 50-day average.")
    if momentum_3m is not None:
        direction = "gained" if momentum_3m >= 0 else "lost"
        reasons.append(f"The stock has {direction} {abs(momentum_3m):.1f}% over roughly three months.")
    if rsi is not None:
        zone = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
        reasons.append(f"14-day RSI is {rsi:.1f} ({zone}).")
    if position_52w is not None:
        reasons.append(f"Price sits at the {position_52w:.0f}th percentile of its 52-week range.")

    risks: list[str] = []
    if rsi is not None and rsi > 70:
        risks.append("RSI above 70 flags a stretched, overbought move that can reverse.")
    if sma50 is not None and price < sma50:
        risks.append("Price is below its 50-day average, so the short-term trend is weak.")
    if volatility is not None and volatility > 30:
        risks.append(f"Annualised volatility is high ({volatility:.0f}%), widening the error band.")
    if position_52w is not None and position_52w < 20:
        risks.append("Price is near its 52-week low, which can reflect unresolved fundamental stress.")
    if momentum_3m is not None and momentum_3m < 0:
        risks.append("Three-month momentum is negative.")
    risks.append(
        "Target and confidence come from price history only; company fundamentals, news and analyst views are not included."
    )

    return {
        "symbol": item["symbol"],
        "name": item["name"],
        "sector": item["sector"],
        "classification": "positive_upside" if (upside or 0) >= settings.NIFTY_UPSIDE_THRESHOLD_PCT else "no_positive_upside",
        "signal_label": "Positive upside signal",
        "price": _round(price),
        "price_as_of": quote.get("as_of"),
        "price_source": quote.get("source"),
        "price_note": quote.get("note"),
        "data_mode": quote.get("data_mode"),
        "freshness": quote.get("freshness"),
        "is_stale": bool(quote.get("is_stale")),
        "target_price": target,
        "upside_pct": upside,
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon]["label"],
        "confidence": {
            "score": score,
            "label": confidence_key,
            "label_display": confidence_label,
            "explanation": (
                "Technical confidence combines trend agreement, three-month momentum, the RSI band, "
                "history depth and volatility. It is not a probability of profit."
            ),
        },
        "indicators": {
            "available": True,
            "closes": len(closes),
            "sma20": _round(sma20),
            "sma50": _round(sma50),
            "rsi14": _round(rsi, 1),
            "momentum_1m_pct": _round(momentum_1m),
            "momentum_3m_pct": _round(momentum_3m),
            "volatility_annual_pct": _round(volatility),
            "high_52w": _round(high_52w),
            "low_52w": _round(low_52w),
            "position_52w_pct": _round(position_52w, 1),
            "used": [
                "Latest provider price",
                "Daily closes (1 year)",
                "SMA 20",
                "SMA 50",
                "RSI 14",
                "1-month and 3-month momentum",
                "Annualised volatility",
                "52-week range position",
            ],
        },
        "fundamentals": {
            "available": False,
            "used": False,
            "note": (
                "No licensed fundamental data feed is configured, so earnings, valuation and balance-sheet "
                "inputs are not used and not estimated."
            ),
        },
        "reasons": reasons,
        "risks": risks,
        "analysis_at": None,
        "methodology_version": ANALYSIS_VERSION,
    }


def _build(horizon: str) -> dict:
    errors: list[str] = []
    items, constituent_source = _constituents()
    quotes, quote_provenance = _quote_map(items, errors)
    series = _history(items, errors)
    now = datetime.now(IST)
    cards = []
    for item in items:
        card = analyse_one(item, quotes.get(item["symbol"]), series.get(item["symbol"], []), horizon)
        card["analysis_at"] = now.isoformat()
        cards.append(card)
    return {
        "items": items,
        "cards": cards,
        "constituent_source": constituent_source,
        "quote_provenance": quote_provenance,
        "errors": errors,
        "generated_at": now,
    }


def _analyse(horizon: str) -> dict:
    with _LOCK:
        cached = _CACHE.get(horizon)
    if cached and time.time() - cached[0] < settings.NIFTY_RECOMMENDATION_CACHE_SECONDS:
        return cached[1]
    with _BUILD_LOCK:
        with _LOCK:
            cached = _CACHE.get(horizon)
        if cached and time.time() - cached[0] < settings.NIFTY_RECOMMENDATION_CACHE_SECONDS:
            return cached[1]
        built = _build(horizon)
        with _LOCK:
            _CACHE[horizon] = (time.time(), built)
        return built


def _matches(card: dict, query: str) -> bool:
    if not query:
        return True
    needle = query.strip().lower()
    return needle in card["symbol"].lower() or needle in card["name"].lower()


def screen(
    *,
    horizon: str = DEFAULT_HORIZON,
    min_upside: float | None = None,
    confidence: str | None = None,
    query: str | None = None,
    sort: str = "upside",
) -> dict:
    if horizon not in HORIZONS:
        raise ValueError("Horizon must be one of 1m, 3m or 6m.")
    if sort not in ("upside", "confidence", "name"):
        raise ValueError("Sort must be upside, confidence or name.")
    if confidence not in (None, "low", "medium", "high"):
        raise ValueError("Confidence filter must be low, medium or high.")
    threshold = settings.NIFTY_UPSIDE_THRESHOLD_PCT if min_upside is None else float(min_upside)

    built = _analyse(horizon)
    cards = []
    for cached_card in built["cards"]:
        card = dict(cached_card)
        if card["upside_pct"] is None:
            card["classification"] = "insufficient_data"
            card["signal_label"] = "Insufficient data"
        elif card["upside_pct"] >= threshold:
            card["classification"] = "positive_upside"
            card["signal_label"] = "Positive upside signal"
        else:
            card["classification"] = "no_positive_upside"
            card["signal_label"] = "No positive upside signal"
        cards.append(card)

    counts = {
        "universe": len(cards),
        "qualifying": sum(1 for card in cards if card["classification"] == "positive_upside"),
        "no_positive_upside": sum(
            1 for card in cards if card["classification"] == "no_positive_upside"
        ),
        "insufficient_data": sum(
            1 for card in cards if card["classification"] == "insufficient_data"
        ),
    }

    def visible(card: dict) -> bool:
        if not _matches(card, query or ""):
            return False
        if confidence and (card["confidence"] or {}).get("label") != confidence:
            return False
        return True

    def order(card: dict) -> tuple:
        if sort == "name":
            return (card["name"].lower(),)
        if sort == "confidence":
            return (-((card["confidence"] or {}).get("score") or 0), card["symbol"])
        return (-(card["upside_pct"] if card["upside_pct"] is not None else -10_000), card["symbol"])

    buckets = {
        key: sorted(
            [card for card in cards if card["classification"] == key and visible(card)],
            key=order,
        )
        for key in ("positive_upside", "no_positive_upside", "insufficient_data")
    }

    stale = sum(1 for card in buckets["positive_upside"] if card["is_stale"])
    now = built["generated_at"]
    return {
        "available": counts["qualifying"] + counts["no_positive_upside"] > 0,
        "universe": {
            "name": "NSE NIFTY 50",
            "size": counts["universe"],
            "analysed": counts["universe"] - counts["insufficient_data"],
            "constituents": built["constituent_source"],
        },
        "criteria": {
            "horizon": horizon,
            "horizon_label": HORIZONS[horizon]["label"],
            "min_upside_pct": threshold,
            "horizons": [
                {"key": key, "label": value["label"], "sessions": value["sessions"]}
                for key, value in HORIZONS.items()
            ],
            "classification_note": (
                "A stock qualifies only when the model's estimated upside is at or above the threshold. "
                "Qualifying is a model screen, not a buy rating; no 'Strong Buy' label is issued."
            ),
        },
        "counts": counts,
        "matched": {
            "qualifying": len(buckets["positive_upside"]),
            "no_positive_upside": len(buckets["no_positive_upside"]),
            "insufficient_data": len(buckets["insufficient_data"]),
            "total": sum(len(value) for value in buckets.values()),
        },
        "filters": {
            "q": query or "",
            "sort": sort,
            "confidence": confidence,
        },
        "qualifying": buckets["positive_upside"],
        "no_positive_upside": buckets["no_positive_upside"],
        "insufficient_data": buckets["insufficient_data"],
        "methodology": {
            "version": ANALYSIS_VERSION,
            "target": (
                "Target = current price × (1 + expected move). Expected move = 0.55 × gap between price "
                "and SMA50 + 0.35 × three-month price momentum, damped by annualised volatility and scaled "
                "to the selected horizon. It is clamped to a conservative range."
            ),
            "upside": "Upside % = ((Target Price − Current Price) / Current Price) × 100.",
            "confidence": (
                "Confidence is a 5–90 technical score from trend agreement, momentum, RSI, history depth "
                "and volatility. It is not a probability and not an analyst rating."
            ),
            "inputs": (
                "A provider quote plus one year of daily closes. Prices, timestamps, SMAs, RSI and the "
                "52-week range are historical facts; target, upside and confidence are model estimates."
            ),
            "fundamentals": (
                "No licensed fundamental feed is configured. Fundamentals are marked unavailable and are "
                "never synthesised."
            ),
            "analyst_opinions": (
                "No third-party analyst ratings are reproduced or invented. Nothing here is an analyst opinion."
            ),
        },
        "data_quality": {
            "quote_source": built["quote_provenance"].get("quote_source"),
            "quote_provider": built["quote_provenance"].get("quote_provider"),
            "quote_mode": built["quote_provenance"].get("quote_mode"),
            "delay_note": built["quote_provenance"].get("delay_note"),
            "history_source": "Yahoo Finance (NSE) daily closes",
            "session": built["quote_provenance"].get("session"),
            "stale_prices": stale,
            "errors": built["errors"],
            "note": (
                "Quotes may be delayed or stale and are labelled per card. When history or price is "
                "unavailable the stock moves to the insufficient-data bucket instead of being estimated."
            ),
        },
        "fundamentals": {
            "available": False,
            "note": (
                "Fundamental analysis is not available in this deployment because no licensed fundamental "
                "data provider is configured. Cards state this explicitly."
            ),
        },
        "disclaimer": (
            "Recommendations are informational only and are not investment advice. Targets, upside and "
            "confidence are model estimates built from price history and can be wrong. FINOVEXA does not "
            "execute trades from this screen and does not guarantee returns."
        ),
        "generated_at": now,
        "cache_seconds": settings.NIFTY_RECOMMENDATION_CACHE_SECONDS,
    }
