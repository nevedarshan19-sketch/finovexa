from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models import MarketInstrument, User
from app.services import investments


def _quote(price: float, change: float = 0.8) -> dict:
    return {
        "price": price,
        "change_pct": change,
        "as_of": "2026-10-28T15:20:00+05:30",
        "source": "Yahoo Finance (NSE)",
        "data_mode": "delayed",
        "is_stale": False,
    }


@pytest.fixture()
def market(monkeypatch):
    prices = {
        "RELIANCE": 1158.0,
        "TCS": 2460.0,
        "HDFCBANK": 685.3,
        "INFY": 1123.15,
        "ITC": 259.5,
        "SUNPHARMA": 1757.5,
    }
    payload = {
        "source": "Yahoo Finance (NSE)",
        "provider": {
            "name": "yahoo",
            "delay_note": "Delayed NSE quotes.",
            "errors": [],
        },
        "session": {"state": "closed", "label": "Closed"},
        "stocks": [
            {"symbol": symbol, "quote": _quote(price)} for symbol, price in prices.items()
        ],
        "fetched_at": "2026-10-28T19:30:00+05:30",
    }
    monkeypatch.setattr(investments, "india_overview", lambda: payload)
    return prices


def test_portfolio_values_demo_holdings_with_delayed_prices(client, demo, market):
    response = client.get("/api/research/portfolio", headers=demo["headers"])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["data_mode"] == "delayed"
    assert body["is_simulated"] is True
    assert body["totals"]["holdings"] == 6
    assert body["totals"]["priced"] == 6
    assert body["price_source"] == "Yahoo Finance (NSE)"

    symbols = {row["symbol"] for row in body["holdings"]}
    assert {"RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC", "SUNPHARMA"} <= symbols

    reliance = next(row for row in body["holdings"] if row["symbol"] == "RELIANCE")
    assert reliance["quantity"] == 12
    assert reliance["average_cost"] == 1204
    assert reliance["price"] == 1158
    assert reliance["value"] == pytest.approx(13896)
    assert reliance["pnl"] == pytest.approx(-552)
    assert reliance["data_mode"] == "delayed"
    assert reliance["source"] == "demo_seed"

    invested = sum(row["invested"] for row in body["holdings"])
    current = sum(row["value"] for row in body["holdings"])
    assert body["totals"]["invested"] == pytest.approx(invested)
    assert body["totals"]["current_value"] == pytest.approx(current)
    assert body["totals"]["pnl"] == pytest.approx(current - invested)
    assert 99 <= sum(item["share_pct"] for item in body["allocation"]) <= 101
    assert any("practice portfolio" in line for line in body["disclosures"])


def test_portfolio_requires_authentication(client):
    assert client.get("/api/research/portfolio").status_code == 401


def test_simulated_fill_updates_only_the_practice_portfolio(client, demo, market):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "demo@finovexa.ai").one()
        instrument = db.query(MarketInstrument).filter(MarketInstrument.symbol == "TCS").one()
        buy = SimpleNamespace(
            user_id=user.id,
            instrument_id=instrument.id,
            instrument=instrument,
            side="buy",
            quantity=3,
        )
        bought = investments.apply_simulated_fill(db, buy, 4000)
        db.commit()
        assert bought["action"] == "bought"
        assert bought["quantity"] == 3

        sell = SimpleNamespace(
            user_id=user.id,
            instrument_id=instrument.id,
            instrument=instrument,
            side="sell",
            quantity=4,
        )
        sold = investments.apply_simulated_fill(db, sell, 4100)
        db.commit()
        assert sold["action"] == "sold"
        assert sold["capped"] is False
        assert sold["remaining"] == 5

        no_holding = SimpleNamespace(
            user_id=user.id,
            instrument_id=None,
            instrument=SimpleNamespace(symbol="BEL", asset_class="equity", id=None),
            side="sell",
            quantity=1,
        )
        skipped = investments.apply_simulated_fill(db, no_holding, 380)
        assert skipped["action"] == "skipped"


def test_recommendations_are_plain_model_ideas_not_advice(client, demo, market):
    first = client.get("/api/research/recommendations", headers=demo["headers"])
    assert first.status_code == 200, first.text
    body = first.json()

    assert 1 <= len(body["items"]) <= 4
    assert body["data_mode"] == "delayed"
    assert "not investment advice" in body["note"].lower()
    assert "never places an order" in body["disclosure"].lower()

    allowed = {"Strong setup", "Worth a look", "Neutral", "Weak", "High risk"}
    for item in body["items"]:
        assert item["label"] in allowed
        assert item["is_model_generated"] is True
        assert "/100" in item["reason"]
        assert item["symbol"] in {"RELIANCE", "TCS", "HDFCBANK", "INFY"}

    scores = [item["score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)

    second = client.get("/api/research/recommendations", headers=demo["headers"]).json()
    assert second["signature"] == body["signature"]


def test_recommendations_require_authentication(client):
    assert client.get("/api/research/recommendations").status_code == 401
