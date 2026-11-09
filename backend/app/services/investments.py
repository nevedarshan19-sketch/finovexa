from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import (
    BrokerOrder,
    MarketInstrument,
    PortfolioHolding,
    ResearchSignal,
    User,
    utcnow,
)
from .finance import cash_balance, q2
from .india_market import IST, overview as india_overview
from .market import latest_quote, quote_to_dict

SOURCE_LABELS = {
    "demo_seed": "Demo holding",
    "simulated_fill": "Simulated trade",
}

LABELS = (
    (65, "Strong setup", "green", "the model trend is positive"),
    (55, "Worth a look", "blue", "the model trend is mildly positive"),
    (45, "Neutral", "slate", "the model sees no clear direction"),
    (35, "Weak", "amber", "the model flags weakening momentum"),
    (0, "High risk", "red", "the model flags high risk"),
)


def _market_quotes() -> tuple[dict[str, dict], dict]:
    payload = india_overview()
    quotes = {
        row["symbol"]: row["quote"]
        for row in payload.get("stocks", [])
        if row.get("quote") and row["quote"].get("price") is not None
    }
    return quotes, payload


def _quote_for(instrument: MarketInstrument, market: dict[str, dict], db: Session) -> dict | None:
    quote = market.get(instrument.symbol)
    if quote:
        return {
            "price": quote["price"],
            "change_pct": quote.get("change_pct"),
            "as_of": quote.get("as_of"),
            "source": quote.get("source"),
            "data_mode": quote.get("data_mode"),
            "is_stale": quote.get("is_stale", False),
        }
    stored = latest_quote(db, instrument.id)
    if stored is None:
        return None
    payload = quote_to_dict(instrument, stored)
    if payload.get("price") is None:
        return None
    return {
        "price": payload["price"],
        "change_pct": payload.get("change_pct"),
        "as_of": payload.get("as_of"),
        "source": payload.get("source"),
        "data_mode": payload.get("data_mode"),
        "is_stale": payload.get("is_stale", False),
    }


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


def _portfolio_mode(modes: set[str], priced: int, rows: int) -> str:
    if rows == 0 or priced == 0:
        return "unavailable"
    if "delayed" in modes:
        return "delayed"
    if "live" in modes:
        return "live"
    if modes <= {"demo"}:
        return "demo"
    return "unavailable"


def portfolio_overview(db: Session, user: User) -> dict:
    market, feed = _market_quotes()
    holdings = (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.user_id == user.id)
        .all()
    )
    rows: list[dict] = []
    total_invested = Decimal("0.00")
    total_value = Decimal("0.00")
    total_day = Decimal("0.00")
    priced = 0
    modes: set[str] = set()
    sources = {"demo_seed": 0, "simulated_fill": 0}

    for holding in holdings:
        instrument = holding.instrument
        quote = _quote_for(instrument, market, db)
        quantity = holding.quantity
        invested = q2(holding.average_cost * quantity)
        price = _dec(quote["price"]) if quote else None
        value = q2(price * quantity) if price is not None else None
        pnl = q2(value - invested) if value is not None else None
        pnl_pct = (
            round(float(pnl / invested * 100), 2) if pnl is not None and invested else None
        )
        change_pct = quote.get("change_pct") if quote else None
        day_change = None
        if value is not None and change_pct is not None:
            rate = _dec(change_pct)
            if rate > -100:
                day_change = q2(value * rate / (100 + rate))
                total_day += day_change
        if price is not None:
            priced += 1
            total_value += value
            total_invested += invested
            if quote.get("data_mode"):
                modes.add(quote["data_mode"])
        sources[holding.source] = sources.get(holding.source, 0) + 1
        rows.append(
            {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "sector": instrument.sector,
                "exchange": instrument.exchange,
                "currency": instrument.currency,
                "quantity": quantity,
                "average_cost": q2(holding.average_cost),
                "invested": invested,
                "price": round(float(price), 2) if price is not None else None,
                "value": value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "change_pct": change_pct,
                "day_change": day_change,
                "data_mode": quote.get("data_mode") if quote else "unavailable",
                "price_source": quote.get("source") if quote else None,
                "price_as_of": quote.get("as_of") if quote else None,
                "is_stale": bool(quote.get("is_stale")) if quote else False,
                "source": holding.source,
                "source_label": SOURCE_LABELS.get(holding.source, "Holding"),
            }
        )

    rows.sort(key=lambda row: (row["value"] is None, -(row["value"] or Decimal("0"))))
    total_pnl = q2(total_value - total_invested)
    total_pnl_pct = (
        round(float(total_pnl / total_invested * 100), 2) if total_invested else None
    )
    for row in rows:
        row["weight_pct"] = (
            round(float(row["value"] / total_value * 100), 1)
            if row["value"] is not None and total_value
            else None
        )

    groups: dict[str, dict] = {}
    for row in rows:
        if row["value"] is None:
            continue
        key = row["sector"] or "Other"
        group = groups.setdefault(key, {"sector": key, "value": Decimal("0.00"), "count": 0})
        group["value"] += row["value"]
        group["count"] += 1
    allocation = [
        {
            "sector": group["sector"],
            "value": q2(group["value"]),
            "count": group["count"],
            "share_pct": round(float(group["value"] / total_value * 100), 1),
        }
        for group in groups.values()
    ]
    allocation.sort(key=lambda item: item["value"], reverse=True)

    cash = cash_balance(db, user.profile)
    return {
        "holdings": rows,
        "totals": {
            "holdings": len(rows),
            "priced": priced,
            "invested": q2(total_invested),
            "current_value": q2(total_value),
            "pnl": total_pnl,
            "pnl_pct": total_pnl_pct,
            "day_change": q2(total_day),
            "recorded_cash": cash,
            "cash_plus_investments": q2(cash + total_value),
            "currency": user.profile.currency if user.profile else "INR",
        },
        "allocation": allocation,
        "data_mode": _portfolio_mode(modes, priced, len(rows)),
        "price_source": feed.get("source"),
        "price_as_of": feed.get("fetched_at"),
        "session": feed.get("session"),
        "provider": {
            "name": feed.get("provider", {}).get("name"),
            "delay_note": feed.get("provider", {}).get("delay_note"),
            "errors": feed.get("provider", {}).get("errors", []),
        },
        "sources": sources,
        "is_simulated": True,
        "notes": {
            "valuation": (
                "Values use provider-delayed NSE prices. They are an estimate, not an execution "
                "price, settlement amount or broker statement."
            ),
            "ownership": (
                "Holdings are demo or simulated fills recorded by FINOVEXA. No broking account is "
                "connected and live broker holdings are not mirrored."
            ),
            "pnl": "Profit and loss ignores brokerage, taxes, dividends and corporate actions.",
        },
        "disclosures": [
            "This is a practice portfolio, not a real demat or broker account.",
            "Prices are delayed by the data provider and may differ from the exchange.",
            "Simulated fills update this portfolio only; no money, shares or settlement move.",
            "P&L excludes charges, taxes, dividends and corporate actions.",
        ],
        "generated_at": datetime.now(IST),
    }


def apply_simulated_fill(db: Session, order: BrokerOrder, price: Decimal | None) -> dict | None:
    instrument = order.instrument
    if instrument is None or instrument.asset_class != "equity":
        return None
    if price is None or price <= 0:
        return {
            "action": "skipped",
            "symbol": instrument.symbol,
            "reason": "No usable price was available, so the practice portfolio was not updated.",
        }
    holding = (
        db.query(PortfolioHolding)
        .filter(
            PortfolioHolding.user_id == order.user_id,
            PortfolioHolding.instrument_id == order.instrument_id,
        )
        .one_or_none()
    )
    quantity = int(order.quantity)
    if order.side.lower() == "buy":
        if holding is None:
            holding = PortfolioHolding(
                user_id=order.user_id,
                instrument_id=order.instrument_id,
                quantity=quantity,
                average_cost=q2(price),
                source="simulated_fill",
            )
            db.add(holding)
        else:
            total = holding.quantity + quantity
            holding.average_cost = q2(
                (holding.average_cost * holding.quantity + price * quantity) / total
            )
            holding.quantity = total
            holding.source = "simulated_fill"
        holding.last_trade_at = utcnow()
        return {
            "action": "bought",
            "symbol": instrument.symbol,
            "quantity": quantity,
            "price": q2(price),
        }
    if holding is None:
        return {
            "action": "skipped",
            "symbol": instrument.symbol,
            "reason": "No practice holding exists for this stock, so the simulated sell changed nothing.",
        }
    sold = min(quantity, holding.quantity)
    holding.quantity -= sold
    holding.last_trade_at = utcnow()
    if holding.quantity == 0:
        db.delete(holding)
    return {
        "action": "sold",
        "symbol": instrument.symbol,
        "quantity": sold,
        "price": q2(price),
        "remaining": max(0, holding.quantity),
        "capped": sold < quantity,
    }


def recommendation_feed(db: Session) -> dict:
    market, feed = _market_quotes()
    instruments = (
        db.query(MarketInstrument)
        .filter(MarketInstrument.asset_class == "equity")
        .all()
    )
    latest: dict[int, ResearchSignal] = {}
    signals = (
        db.query(ResearchSignal)
        .order_by(ResearchSignal.generated_at.desc(), ResearchSignal.id.desc())
        .all()
    )
    for signal in signals:
        latest.setdefault(signal.instrument_id, signal)

    items = []
    for instrument in instruments:
        signal = latest.get(instrument.id)
        if signal is None:
            continue
        quote = _quote_for(instrument, market, db)
        label, tone, trend = next(
            (name, tone, phrase)
            for threshold, name, tone, phrase in LABELS
            if signal.score >= threshold
        )
        change_pct = quote.get("change_pct") if quote else None
        if quote is None:
            move = "The latest price is unavailable right now"
        elif change_pct is None:
            move = "Today's move is unavailable"
        elif change_pct > 0.15:
            move = f"Up {change_pct:.2f}% today"
        elif change_pct < -0.15:
            move = f"Down {abs(change_pct):.2f}% today"
        else:
            move = "Little change today"
        items.append(
            {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "sector": instrument.sector,
                "score": signal.score,
                "model_signal": signal.model_signal,
                "label": label,
                "tone": tone,
                "reason": f"{move} and {trend}. Model score {signal.score}/100.",
                "price": quote.get("price") if quote else None,
                "change_pct": change_pct,
                "data_mode": quote.get("data_mode") if quote else "unavailable",
                "price_source": quote.get("source") if quote else None,
                "price_as_of": quote.get("as_of") if quote else None,
                "is_model_generated": True,
            }
        )

    items.sort(key=lambda item: (-item["score"], item["symbol"]))
    top = items[:4]
    strong = sum(1 for item in items if item["tone"] == "green")
    watch = sum(1 for item in items if item["tone"] == "blue")
    caution = sum(1 for item in items if item["tone"] in ("amber", "red"))
    now = datetime.now(IST)
    signature = hashlib.sha256(
        f"{now.date().isoformat()}:{now.hour}:"
        f"{[(item['symbol'], item['score'], item['label'], item['data_mode']) for item in top]}".encode()
    ).hexdigest()[:16]
    return {
        "items": top,
        "summary": {
            "ideas": len(items),
            "strong": strong,
            "watch": watch,
            "caution": caution,
            "universe": len(items),
        },
        "headline": (
            f"{top[0]['name']} stands out in today's model review"
            if top and top[0]["score"] >= 65
            else f"{len(top)} stocks to review today"
            if top
            else "No model ideas right now"
        ),
        "signature": signature,
        "generated_at": now,
        "data_mode": _portfolio_mode(
            {item["data_mode"] for item in top} - {"unavailable"}, len(top), len(top)
        ),
        "note": (
            "Model-generated ideas from price momentum and data-quality checks. "
            "Not investment advice, an analyst rating or an instruction to buy."
        ),
        "disclosure": (
            "These are research prompts for the owner to review. FINOVEXA never places an order "
            "from this feed; any order needs explicit owner approval."
        ),
    }
