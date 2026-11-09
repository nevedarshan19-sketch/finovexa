from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from sqlalchemy.orm import Session

from ..config import settings
from ..models import BrokerOrder, MarketInstrument, NewsArticle, ResearchSignal, User
from .finance import cash_balance, q2
from .forecasting import build_forecast
from .market import latest_quote, news_to_dict, quote_to_dict
from .approvals import order_to_dict


def _latest_signal(db: Session, instrument_id: int) -> ResearchSignal | None:
    return (
        db.query(ResearchSignal)
        .filter(ResearchSignal.instrument_id == instrument_id)
        .order_by(ResearchSignal.generated_at.desc(), ResearchSignal.id.desc())
        .first()
    )


def research_overview(db: Session, user: User) -> dict:
    profile = user.profile
    forecast = build_forecast(db, profile, 30, "base")
    cash = cash_balance(db, profile)
    headroom = q2(max(Decimal("0.00"), forecast["minimum_balance"] - profile.min_cash_reserve))
    equities = (
        db.query(MarketInstrument)
        .join(ResearchSignal, ResearchSignal.instrument_id == MarketInstrument.id)
        .filter(MarketInstrument.asset_class == "equity")
        .distinct()
        .order_by(MarketInstrument.symbol)
        .all()
    )
    equity_universe_count = (
        db.query(MarketInstrument)
        .filter(MarketInstrument.asset_class == "equity")
        .count()
    )
    recent_news = (
        db.query(NewsArticle).order_by(NewsArticle.published_at.desc()).limit(100).all()
    )
    items = []
    for instrument in equities:
        signal = _latest_signal(db, instrument.id)
        quote = latest_quote(db, instrument.id)
        quote_payload = quote_to_dict(instrument, quote)
        if signal is None:
            signal_payload = None
        else:
            quality = "demo" if quote_payload["data_mode"] == "demo" else "verified_quote"
            if quote_payload["is_stale"] or quote_payload["freshness"] == "unavailable":
                quality = "degraded"
            signal_payload = {
                "model_signal": signal.model_signal,
                "score": signal.score,
                "rationale": signal.rationale,
                "risks": signal.risks,
                "methodology": signal.methodology,
                "data_quality": quality,
                "is_model_generated": True,
                "generated_at": signal.generated_at,
                "disclosure": "This is a FINOVEXA model-generated research signal, not an analyst rating or consensus.",
            }
        price = Decimal(str(quote_payload["price"])) if quote_payload["price"] else None
        illustrative_qty = (
            int((headroom * Decimal("0.10") / price).to_integral_value(rounding=ROUND_DOWN))
            if price and headroom > 0
            else 0
        )
        announcements = [
            a for a in recent_news if instrument.symbol in (a.instruments or [])
        ][:3]
        items.append(
            {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "exchange": instrument.exchange,
                "sector": instrument.sector,
                "instrument_key": instrument.external_key,
                "quote": quote_payload,
                "signal": signal_payload,
                "announcements": [news_to_dict(a) for a in announcements],
                "analyst_ratings": {
                    "items": [],
                    "note": "No third-party analyst rating provider is connected. Ratings and consensus are not fabricated.",
                },
                "cash_constraints": {
                    "recorded_cash": cash,
                    "minimum_reserve": q2(profile.min_cash_reserve),
                    "investable_headroom": headroom,
                    "surplus_note": "Headroom is the lowest projected 30-day balance above your reserve. It is not guaranteed cash.",
                    "illustrative_order_value": q2(headroom * Decimal("0.10")),
                    "illustrative_quantity": illustrative_qty,
                    "sizing_rule": "Illustrative only: 10% of reserve headroom at the latest quote. Review before any order.",
                },
                "data_quality_note": "Demo quote and demo candles."
                if quote_payload["data_mode"] == "demo"
                else "Quote supplied by the configured market-data provider.",
            }
        )
    orders = (
        db.query(BrokerOrder)
        .filter(BrokerOrder.user_id == user.id)
        .order_by(BrokerOrder.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        "items": items,
        "orders": [order_to_dict(order) for order in orders],
        "risk_profile": {
            "tolerance": profile.risk_tolerance,
            "research_interests": profile.research_interests,
            "currency": profile.currency,
        },
        "cash_context": {
            "recorded_cash": cash,
            "minimum_reserve": q2(profile.min_cash_reserve),
            "investable_headroom": headroom,
            "projected_minimum_30d": forecast["minimum_balance"],
            "shortfall_date": forecast["shortfall_date"],
        },
        "universe": {
            "equity_instruments": equity_universe_count,
            "signal_covered": len(items),
            "note": (
                "Every NIFTY 50 constituent is available in the trade desk. Simulated requests are "
                "always available; live requests require live trading to be enabled and Upstox to be configured."
            ),
        },
        "broker_status": {
            "mode": "live" if settings.upstox_live_ready else "simulated",
            "upstox_configured": bool(settings.UPSTOX_ACCESS_TOKEN),
            "live_trading_enabled": settings.UPSTOX_LIVE_TRADING_ENABLED,
            "live_trading_ready": settings.upstox_live_ready,
            "static_ip_required": True,
            "note": (
                "Live Upstox order placement is enabled for manually approved orders only. "
                "No trade is ever placed automatically from a signal or AI output."
                if settings.upstox_live_ready
                else "Live trading is disabled or Upstox credentials are missing. Stock and option orders are simulated."
            ),
        },
        "disclosures": [
            "Signals are generated by a transparent rules-based model using price momentum and data-quality checks.",
            "A positive signal is not a recommendation, guarantee of returns, or evidence of suitability.",
            "Missing or stale data degrades the signal and must be reviewed before any action.",
            "Any order requires explicit owner approval of exact quantity, side, order type and price limit.",
            "Live Upstox orders are sent only after explicit owner approval and require a registered static IP.",
            "Simulated sells do not verify holdings, margin or settlement; live sells are validated by Upstox.",
            "Option orders require a live option chain for live execution. Derivatives carry substantial risk.",
        ],
    }
