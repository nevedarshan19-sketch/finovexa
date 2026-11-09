from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MarketInstrument, User
from ..security import get_current_user
from ..services.business_context import active_business
from ..services.market import (
    historical_series,
    market_overview,
    news_list,
    quote_to_dict,
    latest_quote,
)
from ..services.instruments import nifty50_trade_desk, stock_token_catalogue
from ..services.investments import portfolio_overview, recommendation_feed
from ..services.india_market import overview as india_market_overview
from ..services.india_market import stock_detail as india_stock_detail
from ..services.integrations.yahoo_finance import YahooFinanceError
from ..services.market_simulator import market_simulation, stock_simulation
from ..services.options import nifty_option_chain
from ..services.research import research_overview

router = APIRouter(tags=["Market intelligence and research"])


def _instrument(db: Session, symbol: str) -> MarketInstrument:
    instrument = (
        db.query(MarketInstrument)
        .filter(MarketInstrument.symbol == symbol.upper())
        .one_or_none()
    )
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found.")
    return instrument


@router.get("/market/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return market_overview(db)


@router.get("/market/simulator")
def simulator(user: User = Depends(get_current_user)):
    return market_simulation()


@router.get("/market/simulator/{symbol}")
def simulator_stock(symbol: str, user: User = Depends(get_current_user)):
    try:
        return stock_simulation(symbol)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Stock is not in the simulated NIFTY 50 universe.",
        ) from exc


@router.get("/market/india/overview")
def india_overview(user: User = Depends(get_current_user)):
    return india_market_overview()


@router.get("/market/india/stocks/{symbol}")
def india_stock(
    symbol: str,
    range: str = Query(default="1d", pattern="^(1d|5d|1mo|3mo|1y)$"),
    user: User = Depends(get_current_user),
):
    try:
        return india_stock_detail(symbol, range)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Stock is not in the NIFTY 50 universe.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except YahooFinanceError as exc:
        status = 429 if exc.status_code == 429 else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/market/instruments/{symbol}")
def instrument_detail(
    symbol: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instrument = _instrument(db, symbol)
    return quote_to_dict(instrument, latest_quote(db, instrument.id))


@router.get("/market/instruments/{symbol}/history")
def instrument_history(
    symbol: str,
    days: int = Query(default=90, ge=10, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instrument = _instrument(db, symbol)
    return historical_series(db, instrument, days)


@router.get("/market/news")
def market_news(
    instrument: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return news_list(db, instrument, limit)


@router.get("/research")
def research(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if active_business(db, user) is None:
        raise HTTPException(status_code=409, detail="Complete your business profile first.")
    return research_overview(db, user)


@router.get("/research/portfolio")
def investment_portfolio(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if active_business(db, user) is None:
        raise HTTPException(status_code=409, detail="Complete your business profile first.")
    return portfolio_overview(db, user)


@router.get("/research/recommendations")
def stock_recommendations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return recommendation_feed(db)


@router.get("/research/stock-tokens")
def stock_tokens(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return stock_token_catalogue(db)


@router.get("/research/nifty50")
def nifty50(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return nifty50_trade_desk(db)


@router.get("/research/option-chain")
def option_chain(
    expiry: str | None = Query(default=None, max_length=10),
    strikes: int = Query(default=21, ge=5, le=41),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return nifty_option_chain(db, expiry, strikes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
