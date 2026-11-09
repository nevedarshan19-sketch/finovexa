from __future__ import annotations

import hashlib
import math
import random
import statistics
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from ..models import utcnow
from .instruments import NIFTY50_STOCKS, nifty50_demo_specs

IST = timezone(timedelta(hours=5, minutes=30))
TICK_SECONDS = 5
SESSION_BARS = 75
BAR_MINUTES = 5
SPARK_POINTS = 24
BASE_INDEX_LEVEL = 25000.0

_CATALOGUE = {
    symbol: {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "exchange": "NSE",
        "currency": "INR",
        "instrument_key": instrument_key,
        "exchange_token": exchange_token,
    }
    for symbol, name, sector, instrument_key, exchange_token in NIFTY50_STOCKS
}

_SPECS = {
    spec["symbol"]: {
        "base": float(spec["base"]),
        "volatility": float(spec["volatility"]),
        "drift": float(spec["drift"]),
    }
    for spec in nifty50_demo_specs()
}

_SYMBOLS = tuple(_CATALOGUE)


def _bar_label(index: int) -> str:
    total = 9 * 60 + 15 + index * BAR_MINUTES
    return f"{total // 60:02d}:{total % 60:02d}"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=512)
def _bars_for(symbol: str, day: str) -> tuple[dict[str, Any], ...]:
    spec = _SPECS[symbol]
    base = spec["base"]
    daily_vol = max(0.004, spec["volatility"])
    digest = hashlib.sha256(f"{symbol}:{day}:sim-v1".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))

    name_factor = 0.8 + rng.random() * 0.8
    sigma = daily_vol / math.sqrt(SESSION_BARS) * name_factor
    daily_bias = (rng.random() - 0.5) * 0.012
    wave_amplitude = daily_vol * (0.35 + rng.random() * 0.5)
    phase = rng.random() * math.tau
    volume_base = int(260_000 + rng.random() * 2_600_000)

    bars: list[dict[str, Any]] = []
    previous_close = base
    for index in range(SESSION_BARS):
        progress = index / SESSION_BARS
        previous_progress = (index - 1) / SESSION_BARS
        wave = wave_amplitude * math.sin(progress * math.tau * 1.15 + phase)
        previous_wave = wave_amplitude * math.sin(previous_progress * math.tau * 1.15 + phase)
        ret = (
            daily_bias / SESSION_BARS
            + (wave - previous_wave)
            + sigma * rng.gauss(0.0, 1.0)
        )
        ret = _clamp(ret, -0.03, 0.03)
        close = round(previous_close * math.exp(ret), 2)

        open_price = round(previous_close, 2)
        wick = abs(rng.gauss(0.0, 1.0)) * max(0.00035, daily_vol * 0.3) + 0.0002
        high = max(open_price, close, round(max(open_price, close) * (1 + wick), 2))
        low = min(open_price, close, round(min(open_price, close) * (1 - wick), 2))

        volume_factor = 0.55 + rng.random() * 0.9
        if index < 6 or index > SESSION_BARS - 10:
            volume_factor *= 1.35
        volume = int(volume_base * volume_factor)

        bars.append(
            {
                "index": index,
                "time": _bar_label(index),
                "open": open_price,
                "high": round(high, 2),
                "low": round(low, 2),
                "close": close,
                "volume": volume,
            }
        )
        previous_close = close
    return tuple(bars)


def _sma(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    sample = values[-window:] if len(values) > window else values
    return sum(sample) / len(sample)


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) <= period:
        return 50.0
    deltas = [b - a for a, b in zip(closes[-period - 1 : -1], closes[-period:])]
    gains = sum(delta for delta in deltas if delta > 0) / period
    losses = sum(-delta for delta in deltas if delta < 0) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def _analyze(symbol: str, day: str, bar: int) -> dict[str, Any]:
    meta = _CATALOGUE[symbol]
    spec = _SPECS[symbol]
    bars = _bars_for(symbol, day)
    bar = _clamp(bar, 0, SESSION_BARS - 1)
    visible = list(bars[: bar + 1])
    closes = [item["close"] for item in visible]

    price = closes[-1]
    previous_close = spec["base"]
    change = round(price - previous_close, 2)
    change_pct = round(change / previous_close * 100, 2) if previous_close else 0.0

    day_high = max(item["high"] for item in visible)
    day_low = min(item["low"] for item in visible)
    open_price = visible[0]["open"]

    sma5 = _sma(closes, 5)
    sma20 = _sma(closes, 20)
    rsi = _rsi(closes)
    if len(closes) > 5:
        momentum_pct = (closes[-1] / closes[-6] - 1.0) * 100.0
    else:
        momentum_pct = change_pct

    returns = [b / a - 1.0 for a, b in zip(closes[-21:-1], closes[-20:]) if a]
    if len(returns) >= 3:
        volatility_pct = statistics.pstdev(returns) * math.sqrt(SESSION_BARS) * 100.0
    else:
        volatility_pct = spec["volatility"] * 100.0

    current_volume = visible[-1]["volume"]
    history = visible[max(0, bar - 20) : bar]
    average_volume = (
        sum(item["volume"] for item in history) / len(history) if history else current_volume
    )
    average_volume = max(1.0, average_volume)
    volume_ratio = current_volume / average_volume

    traded_volume = sum(item["volume"] for item in visible)
    vwap_numerator = sum(
        ((item["high"] + item["low"] + item["close"]) / 3.0) * item["volume"] for item in visible
    )
    vwap = vwap_numerator / traded_volume if traded_volume else price

    recent = visible[-12:]
    support = min(item["low"] for item in recent)
    resistance = max(item["high"] for item in recent)

    score = 50.0
    score += _clamp(change_pct * 6.0, -12.0, 12.0)
    score += 8.0 if price >= sma20 else -8.0
    score += 6.0 if sma5 >= sma20 else -6.0
    score += _clamp((rsi - 50.0) * 0.35, -8.0, 8.0)
    if volume_ratio >= 1.25:
        score += 4.0 if change_pct >= 0 else -4.0
    if rsi >= 80:
        score -= 4.0
    if rsi <= 20:
        score -= 4.0
    score = int(round(_clamp(score, 0.0, 100.0)))

    if price > sma20 and sma5 > sma20:
        trend = "up"
    elif price < sma20 and sma5 < sma20:
        trend = "down"
    else:
        trend = "sideways"

    bias = "bullish" if score >= 60 else "bearish" if score <= 40 else "neutral"
    if bias == "bullish":
        label = "Overbought momentum" if rsi >= 70 else "Bullish momentum"
    elif bias == "bearish":
        label = "Oversold pressure" if rsi <= 30 else "Bearish momentum"
    else:
        label = "Range-bound"

    observations = [
        "Above 20-bar average" if price >= sma20 else "Below 20-bar average",
        f"RSI {rsi:.1f} · overbought"
        if rsi >= 70
        else f"RSI {rsi:.1f} · oversold"
        if rsi <= 30
        else f"RSI {rsi:.1f} · neutral",
        f"Volume {volume_ratio:.2f}× 20-bar average"
        if volume_ratio >= 1.2
        else "Volume near average",
        f"{momentum_pct:+.2f}% over the last 5 bars",
    ]

    return {
        **meta,
        "price": price,
        "previous_close": previous_close,
        "open": open_price,
        "day_high": day_high,
        "day_low": day_low,
        "change": change,
        "change_pct": change_pct,
        "volume": current_volume,
        "average_volume": int(average_volume),
        "volume_ratio": round(volume_ratio, 2),
        "traded_volume": traded_volume,
        "vwap": round(vwap, 2),
        "sma5": round(sma5, 2),
        "sma20": round(sma20, 2),
        "rsi14": round(rsi, 1),
        "momentum_pct": round(momentum_pct, 2),
        "volatility_pct": round(volatility_pct, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "trend": trend,
        "bias": bias,
        "label": label,
        "score": score,
        "observations": observations,
        "spark": [item["close"] for item in visible[-SPARK_POINTS:]],
        "data_mode": "simulated",
        "disclosure": (
            "Simulated technical analysis over synthetic prices. "
            "Not a recommendation, forecast or live market observation."
        ),
    }


def _brief(stock: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": stock["symbol"],
        "name": stock["name"],
        "sector": stock["sector"],
        "price": stock["price"],
        "change_pct": stock["change_pct"],
        "volume_ratio": stock["volume_ratio"],
        "rsi14": stock["rsi14"],
        "score": stock["score"],
        "trend": stock["trend"],
        "label": stock["label"],
    }


def _sector_summary(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for stock in stocks:
        groups.setdefault(stock["sector"], []).append(stock)
    sectors = []
    for sector, members in groups.items():
        average = sum(item["change_pct"] for item in members) / len(members)
        leader = max(members, key=lambda item: item["change_pct"])
        laggard = min(members, key=lambda item: item["change_pct"])
        sectors.append(
            {
                "sector": sector,
                "count": len(members),
                "change_pct": round(average, 2),
                "advancers": sum(1 for item in members if item["change_pct"] > 0.05),
                "decliners": sum(1 for item in members if item["change_pct"] < -0.05),
                "unchanged": sum(1 for item in members if abs(item["change_pct"]) <= 0.05),
                "leader_symbol": leader["symbol"],
                "leader_change_pct": leader["change_pct"],
                "laggard_symbol": laggard["symbol"],
                "laggard_change_pct": laggard["change_pct"],
            }
        )
    return sorted(sectors, key=lambda item: item["change_pct"], reverse=True)


def _index_history(day: str, bar: int) -> list[dict[str, Any]]:
    start = max(0, bar - SPARK_POINTS + 1)
    points = []
    for index in range(start, bar + 1):
        changes = []
        for symbol in _SYMBOLS:
            bars = _bars_for(symbol, day)
            base = _SPECS[symbol]["base"]
            changes.append(bars[index]["close"] / base - 1.0)
        level = BASE_INDEX_LEVEL * (1.0 + sum(changes) / len(changes))
        points.append({"time": _bar_label(index), "level": round(level, 2)})
    return points


def _session(bar: int) -> dict[str, Any]:
    return {
        "mode": "accelerated_replay",
        "clock": _bar_label(bar),
        "bar": bar + 1,
        "total_bars": SESSION_BARS,
        "tick_seconds": TICK_SECONDS,
        "bar_minutes": BAR_MINUTES,
        "loop_seconds": SESSION_BARS * TICK_SECONDS,
        "real_hours_ist": "09:15–15:30 Mon–Fri (simulation ignores holidays)",
        "note": (
            "Synthetic session replay: one 5-minute bar every 5 seconds, looping every 6m15s. "
            "It does not follow the real NSE clock and is not exchange data."
        ),
    }


def build_market_snapshot(day: str, bar: int) -> dict[str, Any]:
    bar = int(_clamp(bar, 0, SESSION_BARS - 1))
    stocks = [_analyze(symbol, day, bar) for symbol in _SYMBOLS]
    advancers = sum(1 for item in stocks if item["change_pct"] > 0.05)
    decliners = sum(1 for item in stocks if item["change_pct"] < -0.05)
    unchanged = len(stocks) - advancers - decliners
    average_change = sum(item["change_pct"] for item in stocks) / len(stocks)
    median_change = statistics.median(item["change_pct"] for item in stocks)
    breadth_pct = advancers / len(stocks) * 100.0
    index_level = BASE_INDEX_LEVEL * (1.0 + average_change / 100.0)

    gainers = sorted(stocks, key=lambda item: item["change_pct"], reverse=True)
    most_active = sorted(stocks, key=lambda item: item["volume_ratio"], reverse=True)
    overbought = sorted(
        (item for item in stocks if item["rsi14"] >= 70),
        key=lambda item: item["rsi14"],
        reverse=True,
    )
    oversold = sorted(
        (item for item in stocks if item["rsi14"] <= 30),
        key=lambda item: item["rsi14"],
    )

    return {
        "data_mode": "simulated",
        "is_live_market_data": False,
        "verified_live": False,
        "source": "FINOVEXA Indian market simulator",
        "index": {
            "symbol": "SIMNIFTY50",
            "name": "NIFTY 50 · simulated equal-weight index",
            "level": round(index_level, 2),
            "change": round(index_level - BASE_INDEX_LEVEL, 2),
            "change_pct": round(average_change, 2),
            "base_level": BASE_INDEX_LEVEL,
            "history": _index_history(day, bar),
        },
        "summary": {
            "total": len(stocks),
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": unchanged,
            "breadth_pct": round(breadth_pct, 1),
            "average_change_pct": round(average_change, 2),
            "median_change_pct": round(median_change, 2),
            "mood": "Advancing"
            if breadth_pct >= 60
            else "Declining"
            if breadth_pct <= 40
            else "Mixed",
            "total_volume": sum(item["volume"] for item in stocks),
            "overbought": len(overbought),
            "oversold": len(oversold),
        },
        "sectors": _sector_summary(stocks),
        "stocks": stocks,
        "top_gainers": [_brief(item) for item in gainers[:5]],
        "top_losers": [_brief(item) for item in gainers[-5:][::-1]],
        "most_active": [_brief(item) for item in most_active[:5]],
        "overbought": [_brief(item) for item in overbought[:5]],
        "oversold": [_brief(item) for item in oversold[:5]],
        "session": _session(bar),
        "session_date": day,
        "notes": {
            "feed": (
                "SIMULATED — synthetic prices, volumes and indicators. This is not live market data; "
                "no NSE, BSE, Upstox or broker feed is used."
            ),
            "engine": (
                "Deterministic seeded random walk per stock and trading day, replayed at 5 seconds per "
                "5-minute bar. Same bar returns the same values; a new bar updates every 5 seconds."
            ),
            "analysis": (
                "RSI(14), moving averages, VWAP, momentum, volume ratio and support/resistance are computed "
                "from the synthetic session only. Scores are a transparent rules-based technical summary."
            ),
            "orders": (
                "This panel is read-only. Any simulated or live order must be created in the approval-gated "
                "trade desk and explicitly approved by the owner."
            ),
        },
        "disclosures": [
            "Simulated market data: prices, volume and analytics are generated locally and are not live market data.",
            "Not NSE/BSE, Upstox or any exchange feed; do not use for real trading decisions.",
            "Technical scores are model-generated commentary, not investment advice or a recommendation.",
            "No order, holding, cash or position changes from viewing this simulator.",
        ],
    }


def build_stock_snapshot(symbol: str, day: str, bar: int) -> dict[str, Any]:
    symbol = symbol.upper()
    if symbol not in _CATALOGUE:
        raise KeyError(symbol)
    bar = int(_clamp(bar, 0, SESSION_BARS - 1))
    stock = _analyze(symbol, day, bar)
    candles = [
        {
            "index": item["index"],
            "time": item["time"],
            "open": item["open"],
            "high": item["high"],
            "low": item["low"],
            "close": item["close"],
            "volume": item["volume"],
        }
        for item in _bars_for(symbol, day)[: bar + 1]
    ]
    return {
        **stock,
        "candles": candles,
        "session": _session(bar),
        "session_date": day,
        "notes": {
            "feed": "SIMULATED — synthetic prices and indicators, not live market data.",
            "engine": "Deterministic seeded random walk replayed at 5 seconds per 5-minute bar.",
            "analysis": "RSI(14), SMA(5/20), VWAP, momentum, volume ratio and 12-bar support/resistance.",
            "orders": "Read-only analysis. Orders require the approval-gated trade desk.",
        },
        "disclosures": [
            "Simulated market data generated locally; not NSE/BSE or Upstox data.",
            "Model-generated technical commentary, not investment advice.",
            "Viewing this analysis does not place an order.",
        ],
    }


def _current_bar() -> int:
    return int(time.time() // TICK_SECONDS) % SESSION_BARS


def _current_day() -> str:
    return datetime.now(IST).date().isoformat()


def market_simulation() -> dict[str, Any]:
    payload = build_market_snapshot(_current_day(), _current_bar())
    payload["as_of"] = utcnow()
    return payload


def stock_simulation(symbol: str) -> dict[str, Any]:
    payload = build_stock_snapshot(symbol, _current_day(), _current_bar())
    payload["as_of"] = utcnow()
    return payload
