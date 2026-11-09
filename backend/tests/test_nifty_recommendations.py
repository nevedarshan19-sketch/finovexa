from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import nifty_recommendations as rec


def _trend(start: float, end: float, points: int = 250) -> list[float]:
    step = (end - start) / (points - 1)
    return [round(start + step * index, 2) for index in range(points)]


def _quote(price: float) -> dict:
    return {
        "price": price,
        "previous_close": price,
        "change_pct": 0.5,
        "high_52w": price * 1.1,
        "low_52w": price * 0.8,
        "volume": 100_000,
        "currency": "INR",
        "exchange": "NSE",
        "as_of": "2026-11-06T15:30:00+05:30",
        "age_minutes": 10,
        "source": "Yahoo Finance (NSE)",
        "data_mode": "delayed",
        "freshness": "delayed",
        "is_stale": False,
        "note": "Delayed NSE quote from Yahoo Finance.",
    }


def test_upside_uses_the_documented_formula_and_no_buy_rating():
    item = {"symbol": "TEST", "name": "Test Ltd", "sector": "Testing"}
    closes = _trend(100, 160)
    card = rec.analyse_one(item, _quote(160), closes, "3m")

    assert card["classification"] in ("positive_upside", "no_positive_upside")
    expected = round((card["target_price"] - card["price"]) / card["price"] * 100, 2)
    assert card["upside_pct"] == expected
    assert card["signal_label"] in ("Positive upside signal", "No positive upside signal")
    assert "buy" not in card["signal_label"].lower()
    assert card["fundamentals"]["available"] is False
    assert card["fundamentals"]["used"] is False
    assert card["confidence"]["score"] <= 90
    assert card["indicators"]["used"]


def test_missing_history_is_insufficient_not_estimated():
    item = {"symbol": "TEST", "name": "Test Ltd", "sector": "Testing"}
    card = rec.analyse_one(item, _quote(100), [100, 101, 102], "3m")

    assert card["classification"] == "insufficient_data"
    assert card["target_price"] is None
    assert card["upside_pct"] is None
    assert card["confidence"] is None
    assert any("daily closes" in risk for risk in card["risks"])


def test_missing_price_is_insufficient():
    item = {"symbol": "TEST", "name": "Test Ltd", "sector": "Testing"}
    card = rec.analyse_one(item, None, _trend(100, 120), "3m")

    assert card["classification"] == "insufficient_data"
    assert card["price"] is None
    assert card["target_price"] is None


@pytest.fixture()
def stubbed_market(monkeypatch):
    """All 50 constituents priced, with alternating uptrends and downtrends."""
    rec.clear_cache()
    items = [
        {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "isin": key.split("|", 1)[1],
            "upstox": key,
            "yahoo": f"{symbol}.NS",
            "exchange_token": token,
        }
        for symbol, name, sector, key, token in rec.NIFTY50_STOCKS
    ]
    source = {
        "name": "Test constituents",
        "url": rec.NSE_CONSTITUENTS_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "fallback": False,
        "note": "Test fixture.",
        "errors": [],
        "count": len(items),
    }
    prices: dict[str, float] = {}
    history: dict[str, list[float]] = {}
    for index, item in enumerate(items):
        if index % 2 == 0:
            closes = _trend(100, 160)
        else:
            closes = _trend(160, 100)
        history[item["yahoo"]] = closes
        prices[item["symbol"]] = closes[-1]

    monkeypatch.setattr(rec, "_constituents", lambda: (items, source))
    monkeypatch.setattr(
        rec,
        "india_overview",
        lambda: {
            "stocks": [
                {"symbol": item["symbol"], "quote": _quote(prices[item["symbol"]])}
                for item in items
            ],
            "provider": {"name": "yahoo", "errors": [], "delay_note": "Delayed."},
            "source": "Yahoo Finance (NSE)",
            "data_mode": "delayed",
            "session": {"state": "closed"},
        },
    )
    monkeypatch.setattr(
        rec.yahoo_client,
        "spark",
        lambda symbols, range_="1d", interval="5m": {
            symbol: {"meta": {"regularMarketPrice": 100}, "spark": history[symbol]}
            for symbol in symbols
        },
    )
    yield items, prices
    rec.clear_cache()


def test_screen_covers_all_fifty_and_splits_buckets(stubbed_market):
    result = rec.screen(horizon="3m")
    counts = result["counts"]

    assert result["universe"]["size"] == 50
    assert counts["universe"] == 50
    assert counts["qualifying"] > 0
    assert counts["no_positive_upside"] > 0
    assert counts["qualifying"] + counts["no_positive_upside"] + counts["insufficient_data"] == 50
    assert result["matched"]["qualifying"] == counts["qualifying"]
    assert result["matched"]["no_positive_upside"] == counts["no_positive_upside"]
    assert result["matched"]["total"] == 50
    assert result["criteria"]["min_upside_pct"] == rec.settings.NIFTY_UPSIDE_THRESHOLD_PCT
    assert result["fundamentals"]["available"] is False
    assert "not investment advice" in result["disclaimer"]
    assert result["methodology"]["upside"].startswith("Upside % = ((Target Price")

    for card in result["qualifying"]:
        assert card["upside_pct"] >= result["criteria"]["min_upside_pct"]
        assert card["signal_label"] == "Positive upside signal"
        expected = round((card["target_price"] - card["price"]) / card["price"] * 100, 2)
        assert card["upside_pct"] == expected
    for card in result["no_positive_upside"]:
        assert card["upside_pct"] < result["criteria"]["min_upside_pct"]
        assert card["signal_label"] == "No positive upside signal"


def test_screen_threshold_sort_search_and_confidence_filters(stubbed_market):
    wide = rec.screen(min_upside=0)
    assert len(wide["qualifying"]) == wide["counts"]["qualifying"]
    assert all(card["upside_pct"] >= 0 for card in wide["qualifying"])

    upside_sorted = rec.screen()
    values = [card["upside_pct"] for card in upside_sorted["qualifying"]]
    assert values == sorted(values, reverse=True)

    by_name = rec.screen(sort="name")
    assert [card["name"] for card in by_name["qualifying"]] == sorted(
        card["name"] for card in by_name["qualifying"]
    )

    searched = rec.screen(query="reliance", min_upside=0)
    assert searched["matched"]["total"] == 1
    matches = searched["qualifying"] + searched["no_positive_upside"]
    assert [card["symbol"] for card in matches] == ["RELIANCE"]

    label = wide["qualifying"][0]["confidence"]["label"]
    filtered = rec.screen(min_upside=0, confidence=label)
    assert all(card["confidence"]["label"] == label for card in filtered["qualifying"])

    impossible = rec.screen(min_upside=50)
    assert impossible["counts"]["qualifying"] == 0
    assert len(impossible["no_positive_upside"]) == 50 - impossible["counts"]["insufficient_data"]

    with pytest.raises(ValueError):
        rec.screen(horizon="9m")
    with pytest.raises(ValueError):
        rec.screen(sort="rating")


def test_public_endpoint_returns_the_screen(client, stubbed_market):
    response = client.get("/api/market/nifty50/recommendations?horizon=3m&sort=upside")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["universe"]["size"] == 50
    assert payload["criteria"]["horizon"] == "3m"
    assert set(payload["counts"]) == {
        "universe",
        "qualifying",
        "no_positive_upside",
        "insufficient_data",
    }
    assert payload["disclaimer"].startswith("Recommendations are informational only")
    assert payload["data_quality"]["history_source"].startswith("Yahoo Finance")

    filtered = client.get(
        "/api/market/nifty50/recommendations?horizon=6m&q=tcs&min_upside=0&confidence=low"
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["filters"]["q"] == "tcs"
    assert body["criteria"]["horizon"] == "6m"
    assert body["filters"]["confidence"] == "low"

    bad = client.get("/api/market/nifty50/recommendations?horizon=2y")
    assert bad.status_code == 422
