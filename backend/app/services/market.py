from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from ..config import settings
from ..models import MarketCandle, MarketInstrument, MarketQuote, NewsArticle, utcnow
from .finance import q2
from .integrations.metals import MetalsError, metals_client
from .integrations.news import NewsError, news_client
from .integrations.upstox import UpstoxError, upstox_client

QUOTE_STALE_MINUTES = max(settings.QUOTE_CACHE_MINUTES * 4, 60)
NEWS_STALE_HOURS = 48


def _freshness(data_mode: str, as_of: datetime, stale_minutes: int = QUOTE_STALE_MINUTES) -> tuple[str, bool, int]:
    now = utcnow()
    age_minutes = max(0, int((now - as_of.replace(tzinfo=None)).total_seconds() / 60))
    if data_mode == "demo":
        return "demo", False, age_minutes
    if data_mode == "sandbox":
        return "sandbox", False, age_minutes
    if age_minutes > stale_minutes:
        return "stale", True, age_minutes
    return "live", False, age_minutes


def _upsert_quote(
    db: Session,
    instrument: MarketInstrument,
    *,
    price: Decimal,
    previous_close: Decimal,
    as_of: datetime,
    source: str,
    data_mode: str,
    session_status: str | None = None,
) -> MarketQuote:
    change_pct = (
        (price - previous_close) / previous_close * 100 if previous_close and previous_close != 0 else Decimal("0")
    )
    quote = MarketQuote(
        instrument_id=instrument.id,
        price=price,
        previous_close=previous_close,
        change_pct=change_pct,
        as_of=as_of.replace(tzinfo=None) if as_of.tzinfo else as_of,
        source=source,
        data_mode=data_mode,
        session_status=session_status,
    )
    db.add(quote)
    db.flush()
    return quote


def _parse_provider_time(value: str | None) -> datetime:
    if not value:
        return utcnow()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return utcnow()


def quote_to_dict(instrument: MarketInstrument, quote: MarketQuote | None) -> dict:
    if quote is None:
        return {
            "symbol": instrument.symbol,
            "name": instrument.name,
            "asset_class": instrument.asset_class,
            "exchange": instrument.exchange,
            "currency": instrument.currency,
            "unit": instrument.unit,
            "price": None,
            "previous_close": None,
            "change_pct": None,
            "as_of": None,
            "source": None,
            "data_mode": "unavailable",
            "freshness": "unavailable",
            "is_stale": False,
            "age_minutes": None,
            "session_status": None,
            "sector": instrument.sector,
            "note": "No quote is available. Nothing is substituted.",
        }
    freshness, is_stale, age_minutes = _freshness(quote.data_mode, quote.as_of)
    return {
        "symbol": instrument.symbol,
        "name": instrument.name,
        "asset_class": instrument.asset_class,
        "exchange": instrument.exchange,
        "currency": instrument.currency,
        "unit": instrument.unit,
        "price": q2(quote.price) if instrument.currency == "INR" else quote.price,
        "previous_close": quote.previous_close,
        "change_pct": round(float(quote.change_pct), 2),
        "as_of": quote.as_of,
        "source": quote.source,
        "data_mode": quote.data_mode,
        "freshness": freshness,
        "is_stale": is_stale,
        "age_minutes": age_minutes,
        "session_status": quote.session_status,
        "sector": instrument.sector,
        "note": "Demo quote — not live market data."
        if quote.data_mode == "demo"
        else "Provider data older than expected; treat as stale."
        if is_stale
        else None,
    }


def latest_quote(db: Session, instrument_id: int) -> MarketQuote | None:
    return (
        db.query(MarketQuote)
        .filter(MarketQuote.instrument_id == instrument_id)
        .order_by(MarketQuote.as_of.desc(), MarketQuote.id.desc())
        .first()
    )


def _refresh_live(db: Session) -> tuple[list[str], dict[str, str]]:
    errors: list[str] = []
    modes: dict[str, str] = {}
    instruments = (
        db.query(MarketInstrument)
        .filter(MarketInstrument.asset_class != "option")
        .order_by(MarketInstrument.id)
        .all()
    )
    now = utcnow()

    if metals_client.configured:
        metals = [i for i in instruments if i.symbol in ("XAUUSD", "XAGUSD")]
        needs = any(
            (q := latest_quote(db, i.id)) is None
            or q.data_mode != "live"
            or (now - q.fetched_at).total_seconds() > settings.QUOTE_CACHE_MINUTES * 60
            for i in metals
        )
        if needs:
            try:
                payload = metals_client.fetch()
                for instrument, key in ((next((i for i in metals if i.symbol == "XAUUSD"), None), "gold"),
                                        (next((i for i in metals if i.symbol == "XAGUSD"), None), "silver")):
                    if instrument is None:
                        continue
                    entry = payload[key]
                    previous = latest_quote(db, instrument.id)
                    _upsert_quote(
                        db,
                        instrument,
                        price=entry["price"],
                        previous_close=previous.price if previous else entry["price"],
                        as_of=_parse_provider_time(str(entry["as_of"])),
                        source=entry["source"],
                        data_mode="live",
                        session_status="24h",
                    )
                    modes[instrument.symbol] = "live"
                db.commit()
            except MetalsError as exc:
                errors.append(f"Gold/silver: {exc}")
    else:
        modes["XAUUSD"] = "demo"
        modes["XAGUSD"] = "demo"

    if upstox_client.configured:
        targets: list[MarketInstrument] = []
        for instrument in [i for i in instruments if i.asset_class in ("index", "equity")]:
            if not instrument.external_key:
                continue
            latest = latest_quote(db, instrument.id)
            if latest and latest.data_mode == "live" and (now - latest.fetched_at).total_seconds() < settings.QUOTE_CACHE_MINUTES * 60:
                modes[instrument.symbol] = "live"
                continue
            targets.append(instrument)
        if targets:
            try:
                payloads = upstox_client.get_quotes([i.external_key for i in targets if i.external_key])
                for instrument in targets:
                    payload = payloads.get(instrument.external_key or "")
                    if payload is None:
                        errors.append(f"{instrument.symbol}: Upstox returned no quote in the batch response.")
                        continue
                    _upsert_quote(
                        db,
                        instrument,
                        price=Decimal(str(payload["price"])),
                        previous_close=Decimal(str(payload["previous_close"])),
                        as_of=_parse_provider_time(payload.get("as_of")),
                        source=payload["source"],
                        data_mode="live",
                        session_status=payload.get("session_status"),
                    )
                    modes[instrument.symbol] = "live"
                db.commit()
            except UpstoxError as exc:
                errors.append(f"Upstox quotes: {exc}")
                db.rollback()
    else:
        for instrument in [i for i in instruments if i.asset_class in ("index", "equity")]:
            modes[instrument.symbol] = "demo"

    return errors, modes


def refresh_live_quotes(db: Session) -> tuple[list[str], dict[str, str]]:
    return _refresh_live(db)


def market_overview(db: Session) -> dict:
    errors, _ = _refresh_live(db)
    instruments = (
        db.query(MarketInstrument)
        .filter(MarketInstrument.asset_class != "option")
        .order_by(MarketInstrument.asset_class, MarketInstrument.symbol)
        .all()
    )
    items = [quote_to_dict(instrument, latest_quote(db, instrument.id)) for instrument in instruments]
    live_count = sum(1 for item in items if item["freshness"] in ("live", "sandbox"))
    demo_count = sum(1 for item in items if item["data_mode"] == "demo")
    stale_count = sum(1 for item in items if item["is_stale"])
    return {
        "items": items,
        "groups": {
            "metals": [i for i in items if i["asset_class"] == "metal"],
            "indices": [i for i in items if i["asset_class"] == "index"],
            "equities": [i for i in items if i["asset_class"] == "equity"],
        },
        "summary": {
            "live_count": live_count,
            "demo_count": demo_count,
            "stale_count": stale_count,
            "provider_errors": errors,
            "upstox_configured": upstox_client.configured,
            "metals_configured": metals_client.configured,
            "mode_note": "Each quote carries its own source, timestamp and data mode. Demo prices are never presented as live.",
        },
        "as_of": utcnow(),
    }


def historical_series(db: Session, instrument: MarketInstrument, days: int = 90) -> dict:
    days = max(10, min(days, 365))
    from_date = date.today() - timedelta(days=days)
    provider_error = None
    data_mode = "demo"
    if upstox_client.configured and instrument.asset_class in ("index", "equity") and instrument.external_key:
        try:
            candles = upstox_client.get_historical(instrument.external_key, from_date, date.today())
            for candle in candles:
                trading_date = date.fromisoformat(candle["date"])
                existing = (
                    db.query(MarketCandle)
                    .filter(
                        MarketCandle.instrument_id == instrument.id,
                        MarketCandle.trading_date == trading_date,
                    )
                    .one_or_none()
                )
                values = {
                    "open": Decimal(str(candle["open"])),
                    "high": Decimal(str(candle["high"])),
                    "low": Decimal(str(candle["low"])),
                    "close": Decimal(str(candle["close"])),
                    "volume": candle.get("volume"),
                    "data_mode": "live",
                }
                if existing:
                    for key, value in values.items():
                        setattr(existing, key, value)
                else:
                    db.add(
                        MarketCandle(
                            instrument_id=instrument.id,
                            trading_date=trading_date,
                            **values,
                        )
                    )
            db.commit()
            data_mode = "live"
        except UpstoxError as exc:
            provider_error = str(exc)
            db.rollback()

    rows = (
        db.query(MarketCandle)
        .filter(MarketCandle.instrument_id == instrument.id, MarketCandle.trading_date >= from_date)
        .order_by(MarketCandle.trading_date.asc())
        .all()
    )
    if data_mode == "live":
        rows = [row for row in rows if row.data_mode == "live"] or rows
    return {
        "symbol": instrument.symbol,
        "currency": instrument.currency,
        "unit": instrument.unit,
        "data_mode": data_mode,
        "provider_error": provider_error,
        "source": "Upstox API" if data_mode == "live" else "FINOVEXA demo history",
        "candles": [
            {
                "date": row.trading_date.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ],
    }


def _normalize_title(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


def ensure_news(db: Session) -> tuple[str, str | None]:
    if not news_client.configured:
        return "demo", None
    latest_live = (
        db.query(NewsArticle)
        .filter(NewsArticle.data_mode == "live")
        .order_by(NewsArticle.fetched_at.desc())
        .first()
    )
    if latest_live and (utcnow() - latest_live.fetched_at).total_seconds() < settings.NEWS_CACHE_MINUTES * 60:
        return "live", None
    try:
        articles = news_client.fetch()
    except NewsError as exc:
        return ("live" if latest_live else "demo"), str(exc)
    existing_urls = {row[0] for row in db.query(NewsArticle.url).all()}
    recent_titles = {_normalize_title(row[0]) for row in db.query(NewsArticle.title).all()}
    for article in articles[:20]:
        if article["url"] in existing_urls or _normalize_title(article["title"]) in recent_titles:
            continue
        db.add(NewsArticle(**article))
        existing_urls.add(article["url"])
        recent_titles.add(_normalize_title(article["title"]))
    db.commit()
    return "live", None


def news_to_dict(article: NewsArticle) -> dict:
    freshness, is_stale, age_minutes = _freshness(
        article.data_mode,
        article.published_at,
        stale_minutes=NEWS_STALE_HOURS * 60,
    )
    return {
        "id": article.id,
        "title": article.title,
        "source": article.source,
        "url": article.url,
        "published_at": article.published_at,
        "summary": article.summary,
        "implications": article.implications,
        "risks": article.risks,
        "instruments": article.instruments,
        "data_mode": article.data_mode,
        "freshness": freshness,
        "is_stale": is_stale,
        "age_minutes": age_minutes,
        "fetched_at": article.fetched_at,
        "analysis_note": "Sample editorial notes for the demo."
        if article.data_mode == "demo"
        else "No AI implications were generated for this live article.",
    }


def news_list(db: Session, instrument: str | None = None, limit: int = 20) -> dict:
    mode, error = ensure_news(db)
    query = db.query(NewsArticle)
    if mode == "live":
        query = query.filter(NewsArticle.data_mode == "live")
    articles = query.order_by(NewsArticle.published_at.desc()).limit(60).all()
    if instrument:
        needle = instrument.upper()
        articles = [a for a in articles if needle in [i.upper() for i in a.instruments]]
    return {
        "items": [news_to_dict(article) for article in articles[: max(1, min(limit, 50))]],
        "mode": mode,
        "provider_error": error,
        "dedupe_note": "Articles are deduplicated by canonical URL and normalized headline.",
        "provider_note": "Live news requires NEWS_API_KEY."
        if not news_client.configured
        else "Live news from NewsAPI.",
    }
