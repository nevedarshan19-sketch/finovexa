from __future__ import annotations

import hashlib
import math
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import MarketInstrument, MarketQuote, utcnow
from .integrations.upstox import UpstoxError, upstox_client
from .market import latest_quote, quote_to_dict

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"
NIFTY_LOT_SIZE = 75
RISK_FREE_RATE = 0.065
CONTRACT_CACHE_SECONDS = 600
CHAIN_CACHE_SECONDS = 60
MAX_STRIKE_WINDOW = 41

_contract_cache: dict[str, Any] = {"at": 0.0, "expiries": []}
_chain_cache: dict[str, tuple[float, dict]] = {}


def _today_ist() -> date:
    return datetime.now(IST).date()


def _last_tuesday(year: int, month: int) -> date:
    first_next = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    day = first_next - timedelta(days=1)
    while day.weekday() != 1:
        day -= timedelta(days=1)
    return day


def _demo_expiries(today: date) -> list[dict]:
    weekly_start = today + timedelta(days=1)
    while weekly_start.weekday() != 1:
        weekly_start += timedelta(days=1)
    weekly = [weekly_start + timedelta(days=7 * index) for index in range(4)]

    monthly: list[date] = []
    cursor = date(today.year, today.month, 1)
    while len(monthly) < 2:
        candidate = _last_tuesday(cursor.year, cursor.month)
        if candidate > today:
            monthly.append(candidate)
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)

    dates = sorted(set(weekly + monthly))[:6]
    out = []
    for expiry in dates:
        out.append(
            {
                "date": expiry.isoformat(),
                "label": expiry.strftime("%d %b %Y"),
                "kind": "monthly" if expiry == _last_tuesday(expiry.year, expiry.month) else "weekly",
                "days_to_expiry": max(0, (expiry - today).days),
            }
        )
    return out


def _label_expiry(expiry: date, today: date) -> dict:
    return {
        "date": expiry.isoformat(),
        "label": expiry.strftime("%d %b %Y"),
        "kind": "monthly" if expiry == _last_tuesday(expiry.year, expiry.month) else "weekly",
        "days_to_expiry": max(0, (expiry - today).days),
    }


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black_scholes(spot: float, strike: float, years: float, sigma: float, side: str) -> tuple[float, float]:
    if years <= 0:
        intrinsic = max(0.0, spot - strike) if side == "call" else max(0.0, strike - spot)
        delta = 1.0 if (side == "call" and spot > strike) else -1.0 if (side == "put" and spot < strike) else 0.0
        return intrinsic, delta
    sigma = max(sigma, 0.01)
    vol = sigma * math.sqrt(years)
    d1 = (math.log(spot / strike) + (RISK_FREE_RATE + 0.5 * sigma * sigma) * years) / vol
    d2 = d1 - vol
    if side == "call":
        price = spot * _norm_cdf(d1) - strike * math.exp(-RISK_FREE_RATE * years) * _norm_cdf(d2)
        return price, _norm_cdf(d1)
    price = strike * math.exp(-RISK_FREE_RATE * years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return price, _norm_cdf(d1) - 1.0


def _tick(value: float) -> float:
    return round(max(0.05, value) / 0.05) * 0.05


def _deterministic_seed(expiry: str, strike: float) -> int:
    digest = hashlib.sha256(f"{expiry}:{strike}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _demo_leg(
    spot: float,
    strike: float,
    years: float,
    side: str,
    expiry: str,
    atm_strike: float,
    step: int,
) -> dict:
    seed = _deterministic_seed(expiry, strike)
    distance = abs(strike - atm_strike)
    base_iv = 0.105 + min(0.10, (distance / max(spot, 1.0)) * 1.5)
    sigma = min(0.32, base_iv + ((seed >> 17) % 18) / 1000.0)
    raw_price, delta = _black_scholes(spot, strike, years, sigma, side)
    ltp = _tick(raw_price)
    change_pct = round(((seed % 1201) - 600) / 100.0, 2)
    previous = ltp / (1 + change_pct / 100) if change_pct > -99 else ltp
    previous = _tick(previous)

    oi_weight = 1.25 if (side == "call" and strike >= atm_strike) or (side == "put" and strike <= atm_strike) else 0.8
    round_bonus = 1.45 if strike % 500 == 0 else 1.1 if strike % 100 == 0 else 1.0
    oi = int(8500 + 95000 * math.exp(-distance / (step * 7.0)) * oi_weight * round_bonus * (0.72 + (seed % 47) / 100))
    oi = max(500, oi)
    oi_change = int(oi * (((seed >> 8) % 81) - 40) / 300.0)
    volume = int(oi * (0.12 + ((seed >> 24) % 28) / 100))

    return {
        "ltp": round(ltp, 2),
        "previous_close": round(previous, 2),
        "change_pct": change_pct,
        "oi": oi,
        "oi_change": oi_change,
        "volume": volume,
        "iv": round(sigma * 100, 2),
        "delta": round(delta, 3),
        "instrument_key": None,
        "data_mode": "demo",
    }


def _leg_from_provider(entry: dict | None) -> dict | None:
    if not isinstance(entry, dict):
        return None
    market = entry.get("market_data") or {}
    greeks = entry.get("option_greeks") or {}
    ltp = market.get("ltp")
    if ltp is None:
        return None
    close = market.get("close_price")
    change_pct = None
    if close:
        try:
            change_pct = round((float(ltp) - float(close)) / float(close) * 100, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            change_pct = None
    oi = market.get("oi") or 0
    prev_oi = market.get("prev_oi")
    oi_change = None
    if prev_oi is not None:
        try:
            oi_change = int(oi) - int(prev_oi)
        except (TypeError, ValueError):
            oi_change = None
    iv = greeks.get("iv")
    if iv is not None:
        try:
            iv = float(iv)
            if iv < 1.5:
                iv *= 100
            iv = round(iv, 2)
        except (TypeError, ValueError):
            iv = None
    delta = greeks.get("delta")
    try:
        delta = round(float(delta), 3) if delta is not None else None
    except (TypeError, ValueError):
        delta = None
    return {
        "ltp": round(float(ltp), 2),
        "previous_close": round(float(close), 2) if close is not None else None,
        "change_pct": change_pct,
        "oi": int(oi) if oi is not None else None,
        "oi_change": oi_change,
        "volume": int(market["volume"]) if market.get("volume") is not None else None,
        "iv": iv,
        "delta": delta,
        "instrument_key": entry.get("instrument_key"),
        "data_mode": "live",
    }


def _max_pain(rows: list[dict]) -> float | None:
    if not rows:
        return None
    strikes = [row["strike"] for row in rows]
    best_strike = None
    best_pain = None
    for candidate in strikes:
        pain = 0.0
        for row in rows:
            call_oi = (row.get("call") or {}).get("oi") or 0
            put_oi = (row.get("put") or {}).get("oi") or 0
            pain += call_oi * max(0.0, candidate - row["strike"])
            pain += put_oi * max(0.0, row["strike"] - candidate)
        if best_pain is None or pain < best_pain:
            best_pain = pain
            best_strike = candidate
    return best_strike


def _summarize(rows: list[dict], atm_strike: float) -> dict:
    total_call_oi = sum((row.get("call") or {}).get("oi") or 0 for row in rows)
    total_put_oi = sum((row.get("put") or {}).get("oi") or 0 for row in rows)
    call_change = sum((row.get("call") or {}).get("oi_change") or 0 for row in rows)
    put_change = sum((row.get("put") or {}).get("oi_change") or 0 for row in rows)
    support_row = max(rows, key=lambda row: (row.get("put") or {}).get("oi") or 0, default=None)
    resistance_row = max(rows, key=lambda row: (row.get("call") or {}).get("oi") or 0, default=None)
    atm_row = next((row for row in rows if row["strike"] == atm_strike), None)
    atm_ivs = [
        leg.get("iv")
        for leg in ((atm_row or {}).get("call"), (atm_row or {}).get("put"))
        if leg and leg.get("iv") is not None
    ]
    strike_values = sorted({row["strike"] for row in rows})
    steps = [b - a for a, b in zip(strike_values, strike_values[1:])]
    return {
        "atm_strike": atm_strike,
        "atm_iv": round(sum(atm_ivs) / len(atm_ivs), 2) if atm_ivs else None,
        "pcr_oi": round(total_put_oi / total_call_oi, 2) if total_call_oi else None,
        "max_pain": _max_pain(rows),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "call_oi_change": call_change,
        "put_oi_change": put_change,
        "support": support_row["strike"] if support_row else None,
        "resistance": resistance_row["strike"] if resistance_row else None,
        "strike_step": min(steps) if steps else None,
        "strikes_used": len(rows),
    }


def _strike_step(spot: float) -> int:
    return 50 if spot < 30000 else 100


def _window(rows: list[dict], atm_strike: float, count: int) -> list[dict]:
    count = max(5, min(count, MAX_STRIKE_WINDOW))
    if len(rows) <= count:
        return rows
    atm_index = min(range(len(rows)), key=lambda index: abs(rows[index]["strike"] - atm_strike))
    half = count // 2
    start = max(0, min(atm_index - half, len(rows) - count))
    return rows[start : start + count]


def _base_payload(
    *,
    quote_payload: dict,
    expiries: list[dict],
    selected_expiry: str,
    data_mode: str,
    source: str,
    provider_error: str | None,
    requested_expiry: str | None,
    expiry_note: str | None,
) -> dict:
    return {
        "underlying": {
            "symbol": "NIFTY50",
            "name": "Nifty 50",
            "exchange": "NSE",
            "currency": "INR",
            "spot": quote_payload["price"],
            "change_pct": quote_payload["change_pct"],
            "as_of": quote_payload["as_of"],
            "data_mode": quote_payload["data_mode"],
            "source": quote_payload["source"],
        },
        "expiries": expiries,
        "selected_expiry": selected_expiry,
        "requested_expiry": requested_expiry,
        "expiry_note": expiry_note,
        "data_mode": data_mode,
        "verified_live": data_mode == "live",
        "source": source,
        "provider_error": provider_error,
        "as_of": utcnow(),
        "underlying_key": NIFTY_INDEX_KEY,
    }


def _demo_chain(db: Session, quote_payload: dict, requested_expiry: str | None, strike_count: int) -> dict:
    today = _today_ist()
    expiries = _demo_expiries(today)
    chosen = next((item for item in expiries if item["date"] == requested_expiry), expiries[0])
    expiry_note = None
    if requested_expiry and requested_expiry != chosen["date"]:
        expiry_note = (
            f"Requested expiry {requested_expiry} is not in the available demo series; "
            f"showing {chosen['label']} instead."
        )

    spot = float(quote_payload["price"]) if quote_payload.get("price") else 25000.0
    if not quote_payload.get("price"):
        quote_payload = {
            **quote_payload,
            "price": spot,
            "data_mode": "demo",
            "source": "FINOVEXA demo reference spot",
        }
    step = _strike_step(spot)
    atm_strike = round(spot / step) * step
    years = max(chosen["days_to_expiry"], 1) / 365.0
    rows = []
    for offset in range(-20, 21):
        strike = atm_strike + offset * step
        rows.append(
            {
                "strike": float(strike),
                "is_atm": strike == atm_strike,
                "call": _demo_leg(spot, float(strike), years, "call", chosen["date"], float(atm_strike), step),
                "put": _demo_leg(spot, float(strike), years, "put", chosen["date"], float(atm_strike), step),
            }
        )

    payload = _base_payload(
        quote_payload=quote_payload,
        expiries=expiries,
        selected_expiry=chosen["date"],
        data_mode="demo",
        source="FINOVEXA demo options model",
        provider_error=None,
        requested_expiry=requested_expiry,
        expiry_note=expiry_note,
    )
    payload.update(
        {
            "lot_size": NIFTY_LOT_SIZE,
            "strikes": _window(rows, float(atm_strike), strike_count),
            "summary": _summarize(rows, float(atm_strike)),
            "notes": {
                "data_mode": "DEMO — simulated option prices, open interest and IV generated from the seeded NIFTY spot.",
                "pricing": "Demo values use Black-Scholes with a deterministic OI profile. They are not exchange quotes.",
                "metrics": "PCR, max pain, support and resistance are calculated from the simulated open interest.",
                "trading": (
                    "Buy and sell requests from this demo chain are simulated. Every option order requires "
                    "owner approval, and live execution is unavailable while the chain is DEMO."
                ),
                "advice": "Not investment advice. Derivatives carry substantial risk.",
            },
        }
    )
    return payload


def _live_expiries() -> list[date]:
    now = time.monotonic()
    cached = _contract_cache.get("expiries") or []
    if cached and now - float(_contract_cache.get("at") or 0) < CONTRACT_CACHE_SECONDS:
        return cached
    contracts = upstox_client.get_option_contracts(NIFTY_INDEX_KEY)
    dates = set()
    for contract in contracts:
        raw = contract.get("expiry") if isinstance(contract, dict) else None
        if not raw:
            continue
        try:
            dates.add(date.fromisoformat(str(raw)[:10]))
        except ValueError:
            continue
    if not dates:
        raise UpstoxError("Upstox returned no NIFTY option expiries.")
    ordered = sorted(dates)
    _contract_cache["expiries"] = ordered
    _contract_cache["at"] = now
    return ordered


def _live_chain(expiry: str, strike_count: int) -> dict:
    now = time.monotonic()
    cached = _chain_cache.get(expiry)
    if cached and now - cached[0] < CHAIN_CACHE_SECONDS:
        return cached[1]
    entries = upstox_client.get_option_chain(NIFTY_INDEX_KEY, expiry)
    if not entries:
        raise UpstoxError("Upstox returned an empty NIFTY option chain.")
    today = _today_ist()
    expiries = [_label_expiry(day, today) for day in _live_expiries()]
    rows = []
    spot = None
    for entry in entries:
        try:
            strike = float(entry.get("strike_price"))
        except (TypeError, ValueError):
            continue
        if spot is None:
            try:
                spot = float(entry.get("underlying_spot_price"))
            except (TypeError, ValueError):
                spot = None
        rows.append(
            {
                "strike": strike,
                "is_atm": False,
                "call": _leg_from_provider(entry.get("call_options")),
                "put": _leg_from_provider(entry.get("put_options")),
            }
        )
    if not rows:
        raise UpstoxError("Upstox option chain had no usable strikes.")
    rows.sort(key=lambda row: row["strike"])
    if not spot:
        raise UpstoxError("Upstox option chain did not include an underlying spot price.")
    step = min(
        (b["strike"] - a["strike"] for a, b in zip(rows, rows[1:]) if b["strike"] > a["strike"]),
        default=float(_strike_step(spot)),
    )
    atm_strike = round(spot / step) * step if step else spot
    for row in rows:
        row["is_atm"] = row["strike"] == atm_strike

    quote_payload = {
        "symbol": "NIFTY50",
        "name": "Nifty 50",
        "price": round(spot, 2),
        "change_pct": None,
        "as_of": utcnow(),
        "data_mode": "live",
        "source": "Upstox API",
        "currency": "INR",
    }
    choices = [item["date"] for item in expiries]
    selected = expiry if expiry in choices else expiries[0]["date"]
    payload = _base_payload(
        quote_payload=quote_payload,
        expiries=expiries,
        selected_expiry=selected,
        data_mode="live",
        source="Upstox API",
        provider_error=None,
        requested_expiry=expiry,
        expiry_note=None if expiry == selected else f"Requested expiry {expiry} is not available; showing {selected}.",
    )
    payload.update(
        {
            "lot_size": NIFTY_LOT_SIZE,
            "strikes": _window(rows, float(atm_strike), strike_count),
            "summary": _summarize(rows, float(atm_strike)),
            "notes": {
                "data_mode": "LIVE — option chain fetched from the configured Upstox account moments ago.",
                "pricing": "Prices, open interest and IV are provider values for the selected expiry.",
                "metrics": "PCR, max pain, support and resistance are calculated from provider open interest.",
                "trading": (
                    "Owner-approved live Upstox orders are available from this provider chain when live trading "
                    "is enabled. No order is placed without explicit approval."
                    if settings.upstox_live_ready
                    else "Buy and sell requests from this provider chain are simulated. "
                    "No live derivative order is placed."
                ),
                "advice": "Not investment advice. Derivatives carry substantial risk.",
            },
        }
    )
    _chain_cache[expiry] = (now, payload)
    return payload


_MONTHS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def option_contract_symbol(expiry: str, strike: float, option_type: str) -> str:
    day = date.fromisoformat(expiry)
    suffix = "CE" if option_type == "call" else "PE"
    return f"NIFTY{day.strftime('%y')}{_MONTHS[day.month - 1]}{int(round(strike))}{suffix}"


def option_contract_context(
    db: Session, expiry: str, strike: float, option_type: str
) -> dict:
    if option_type not in ("call", "put"):
        raise ValueError("Option type must be call or put.")
    chain = nifty_option_chain(db, expiry, MAX_STRIKE_WINDOW)
    if chain["selected_expiry"] != expiry:
        raise ValueError(
            f"Expiry {expiry} is not available; the current chain shows {chain['selected_expiry']}."
        )
    row = next(
        (item for item in chain["strikes"] if abs(float(item["strike"]) - float(strike)) < 0.001),
        None,
    )
    if row is None:
        raise ValueError("That strike is not in the current option chain window. Refresh and choose a listed strike.")
    leg = row.get(option_type)
    if not leg or leg.get("ltp") is None or float(leg["ltp"]) <= 0:
        raise ValueError(f"No {option_type} premium is available for strike {strike}.")

    symbol = option_contract_symbol(expiry, float(row["strike"]), option_type)
    pretty = "Call" if option_type == "call" else "Put"
    name = f"NIFTY {row['strike']:.0f} {pretty} · {expiry}"
    instrument = db.query(MarketInstrument).filter(MarketInstrument.symbol == symbol).one_or_none()
    if instrument is None:
        instrument = MarketInstrument(
            symbol=symbol,
            name=name,
            asset_class="option",
            exchange="NSE",
            currency="INR",
            unit="lot",
            external_key=leg.get("instrument_key"),
            sector=None,
        )
        db.add(instrument)
        db.flush()
    elif leg.get("instrument_key") and instrument.external_key != leg["instrument_key"]:
        instrument.external_key = leg["instrument_key"]

    ltp = Decimal(str(leg["ltp"]))
    previous = Decimal(str(leg.get("previous_close") or leg["ltp"]))
    quote = MarketQuote(
        instrument_id=instrument.id,
        price=ltp,
        previous_close=previous,
        change_pct=Decimal(str(leg.get("change_pct") or 0)),
        as_of=utcnow(),
        source=chain["source"],
        data_mode=leg.get("data_mode") or chain["data_mode"],
        session_status="option_chain",
    )
    db.add(quote)
    db.flush()
    return {
        "chain": chain,
        "row": row,
        "leg": leg,
        "instrument": instrument,
        "quote": quote,
        "lot_size": NIFTY_LOT_SIZE,
        "symbol": symbol,
        "display_name": name,
    }


def nifty_option_chain(db: Session, requested_expiry: str | None, strike_count: int) -> dict:
    instrument = db.query(MarketInstrument).filter(MarketInstrument.symbol == "NIFTY50").one_or_none()
    quote = latest_quote(db, instrument.id) if instrument else None
    quote_payload = (
        quote_to_dict(instrument, quote)
        if instrument
        else {
            "symbol": "NIFTY50",
            "name": "Nifty 50",
            "price": None,
            "change_pct": None,
            "as_of": None,
            "data_mode": "unavailable",
            "source": None,
            "currency": "INR",
        }
    )

    if requested_expiry:
        try:
            date.fromisoformat(requested_expiry)
        except ValueError as exc:
            raise ValueError("Expiry must be an ISO date (YYYY-MM-DD).") from exc

    if upstox_client.configured:
        try:
            expiries = _live_expiries()
            today = _today_ist()
            available = [day for day in expiries if day >= today] or expiries
            chosen = next((day for day in available if day.isoformat() == requested_expiry), available[0])
            return _live_chain(chosen.isoformat(), strike_count)
        except UpstoxError as exc:
            demo = _demo_chain(db, quote_payload, requested_expiry, strike_count)
            demo["provider_error"] = str(exc)
            demo["notes"]["data_mode"] = (
                "DEMO fallback — the Upstox option chain could not be verified. "
                "No live price is shown."
            )
            return demo

    return _demo_chain(db, quote_payload, requested_expiry, strike_count)
