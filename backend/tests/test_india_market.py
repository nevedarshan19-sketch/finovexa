from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import india_market
from app.services.integrations.yahoo_finance import YahooFinanceError, yahoo_client

IST = timezone(timedelta(hours=5, minutes=30))


def _timestamp() -> int:
    return int(datetime.now(IST).timestamp())


def _fake_spark(symbols: list[str]) -> dict[str, dict]:
    quotes: dict[str, dict] = {}
    for index, symbol in enumerate(symbols):
        price = 100.0 + index
        quotes[symbol] = {
            "meta": {
                "symbol": symbol,
                "currency": "INR",
                "fullExchangeName": "NSE",
                "regularMarketPrice": price,
                "previousClose": price - 1.5,
                "regularMarketChangePercent": round((1.5 / (price - 1.5)) * 100, 2),
                "regularMarketDayHigh": price + 2,
                "regularMarketDayLow": price - 2,
                "fiftyTwoWeekHigh": price * 1.4,
                "fiftyTwoWeekLow": price * 0.7,
                "regularMarketVolume": 1_000_000 + index,
                "regularMarketTime": _timestamp(),
            },
            "spark": [round(price - 0.5 + step * 0.1, 2) for step in range(10)],
        }
    return quotes


def _fake_chart(symbol: str, *, range_: str, interval: str) -> dict:
    points = 30 if range_ in ("1d", "5d") else 260
    candles = []
    for index in range(points):
        close = 1000.0 + index
        candles.append(
            {
                "time": (datetime.now(IST) - timedelta(days=points - index)).isoformat(),
                "open": close - 2,
                "high": close + 3,
                "low": close - 4,
                "close": close,
                "volume": 500_000 + index,
            }
        )
    return {
        "symbol": symbol,
        "meta": {
            "regularMarketPrice": candles[-1]["close"],
            "previousClose": candles[-2]["close"],
            "regularMarketChangePercent": 0.3,
            "regularMarketDayHigh": candles[-1]["high"],
            "regularMarketDayLow": candles[-1]["low"],
            "fiftyTwoWeekHigh": candles[-1]["close"] * 1.1,
            "fiftyTwoWeekLow": candles[0]["close"],
            "regularMarketVolume": 1_234_567,
            "regularMarketTime": _timestamp(),
            "currency": "INR",
            "fullExchangeName": "NSE",
        },
        "candles": candles,
        "spark": [candle["close"] for candle in candles],
    }


@pytest.fixture(autouse=True)
def reset_cache():
    india_market.clear_cache()
    yield
    india_market.clear_cache()


@pytest.fixture()
def market(monkeypatch):
    monkeypatch.setattr(
        yahoo_client,
        "spark",
        lambda symbols, range_="1d", interval="5m": _fake_spark(symbols),
    )
    monkeypatch.setattr(
        yahoo_client,
        "chart",
        lambda symbol, range_="1d", interval="5m": _fake_chart(
            symbol, range_=range_, interval=interval
        ),
    )
    return india_market


def test_india_overview_is_delayed_and_complete(client, demo, market):
    response = client.get("/api/market/india/overview", headers=demo["headers"])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["available"] is True
    assert body["data_mode"] == "delayed"
    assert body["source"] == "Yahoo Finance (NSE)"
    assert body["provider"]["name"] == "yahoo"
    assert body["provider"]["keyless"] is True
    assert body["provider"]["errors"] == []
    assert body["stale"] is False

    assert [item["symbol"] for item in body["indices"]] == ["NIFTY50", "BANKNIFTY", "SENSEX"]
    assert len(body["stocks"]) == 50
    assert body["coverage"] == {"covered": 50, "requested": 50}
    for item in body["stocks"]:
        quote = item["quote"]
        assert quote is not None
        assert quote["data_mode"] == "delayed"
        assert quote["source"] == "Yahoo Finance (NSE)"
        assert quote["price"] > 0
        assert quote["as_of"]
        assert len(quote["spark"]) == 10
        assert quote["freshness"] == "delayed"
        assert quote["is_stale"] is False
        assert "delayed" in quote["note"].lower()

    summary = body["summary"]
    assert summary["covered"] == 50
    assert summary["advancers"] + summary["decliners"] + summary["unchanged"] == 50
    assert summary["total_volume"] > 0

    assert body["session"]["state"] in {"open", "pre_open", "closed"}
    assert "IST" in body["session"]["ist_time"]
    assert any("not investment advice" in line.lower() for line in body["disclosures"])
    assert "simulator" in body["notes"]["prices"].lower()

    unauthorised = client.get("/api/market/india/overview")
    assert unauthorised.status_code == 401


def test_india_stock_detail_has_real_candles_and_indicators(client, demo, market):
    response = client.get("/api/market/india/stocks/TCS?range=1d", headers=demo["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "TCS"
    assert body["instrument_key"].startswith("NSE_EQ|")
    assert body["data_mode"] == "delayed"
    assert body["source"] == "Yahoo Finance (NSE)"
    assert body["range"] == "1d"
    assert body["interval"] == "5m"
    assert len(body["candles"]) == 30
    assert body["indicators"]["sma20"] is not None
    assert body["indicators"]["sma50"] is not None
    assert 0 <= body["indicators"]["rsi14"] <= 100
    assert body["quote"]["price"] == body["candles"][-1]["close"]

    month = client.get("/api/market/india/stocks/INFY?range=3mo", headers=demo["headers"])
    assert month.status_code == 200
    assert month.json()["interval"] == "1d"

    missing = client.get("/api/market/india/stocks/NOTREAL", headers=demo["headers"])
    assert missing.status_code == 404

    bad_range = client.get("/api/market/india/stocks/TCS?range=10y", headers=demo["headers"])
    assert bad_range.status_code == 422

    unauthorised = client.get("/api/market/india/stocks/TCS")
    assert unauthorised.status_code == 401


def test_provider_failure_is_reported_without_inventing_prices(client, demo, monkeypatch):
    def fail(symbols, range_="1d", interval="5m"):
        raise YahooFinanceError("Yahoo Finance rate limit reached.", status_code=429)

    def fail_chart(symbol, range_="1d", interval="5m"):
        raise YahooFinanceError("Yahoo Finance rate limit reached.", status_code=429)

    monkeypatch.setattr(yahoo_client, "spark", fail)
    monkeypatch.setattr(yahoo_client, "chart", fail_chart)
    response = client.get("/api/market/india/overview", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["data_mode"] == "unavailable"
    assert body["source"] is None
    assert body["provider"]["errors"]
    assert all(item["quote"] is None for item in body["stocks"])
    assert all(item["quote"] is None for item in body["indices"])
    assert body["summary"]["covered"] == 0

    detail = client.get("/api/market/india/stocks/TCS", headers=demo["headers"])
    assert detail.status_code == 503
    detail_body = detail.json()
    assert "rate limit" in detail_body["detail"].lower()
    assert "Nothing is substituted" in detail_body["detail"]


def test_last_good_snapshot_is_served_and_marked_stale(client, demo, market, monkeypatch):
    first = client.get("/api/market/india/overview", headers=demo["headers"])
    assert first.status_code == 200
    assert first.json()["stale"] is False

    india_market._CACHE.clear()

    def fail(symbols, range_="1d", interval="5m"):
        raise YahooFinanceError("Could not reach Yahoo Finance.")

    monkeypatch.setattr(yahoo_client, "spark", fail)
    second = client.get("/api/market/india/overview", headers=demo["headers"])
    assert second.status_code == 200
    body = second.json()
    assert body["stale"] is True
    assert body["data_mode"] == "stale"
    assert body["provider"]["stale"] is True
    assert "last successfully fetched snapshot" in body["stale_note"]
    assert len(body["stocks"]) == 50
    assert body["provider"]["errors"]
