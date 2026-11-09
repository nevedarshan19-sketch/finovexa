from __future__ import annotations

import pytest

from app.services.market_simulator import (
    SESSION_BARS,
    build_market_snapshot,
    build_stock_snapshot,
)

DAY = "2026-10-24"


def test_market_snapshot_analyses_every_nifty50_stock():
    body = build_market_snapshot(DAY, 30)
    assert body["data_mode"] == "simulated"
    assert body["is_live_market_data"] is False
    assert body["verified_live"] is False
    assert body["source"] == "FINOVEXA Indian market simulator"
    assert body["index"]["symbol"] == "SIMNIFTY50"
    assert body["index"]["history"]
    assert len(body["stocks"]) == 50
    symbols = {stock["symbol"] for stock in body["stocks"]}
    assert len(symbols) == 50
    assert {"HDFCBANK", "RELIANCE", "TCS", "TATASTEEL"} <= symbols

    for stock in body["stocks"]:
        assert stock["data_mode"] == "simulated"
        assert stock["instrument_key"].startswith("NSE_EQ|")
        assert stock["price"] > 0
        assert stock["day_low"] <= stock["price"] <= stock["day_high"]
        assert stock["support"] <= stock["resistance"]
        assert 0 <= stock["rsi14"] <= 100
        assert 0 <= stock["score"] <= 100
        assert stock["trend"] in {"up", "down", "sideways"}
        assert stock["bias"] in {"bullish", "bearish", "neutral"}
        assert stock["spark"]
        assert len(stock["observations"]) == 4
        assert "Not a recommendation" in stock["disclosure"]

    summary = body["summary"]
    assert summary["total"] == 50
    assert summary["advancers"] + summary["decliners"] + summary["unchanged"] == 50
    assert sum(sector["count"] for sector in body["sectors"]) == 50
    assert len(body["top_gainers"]) == 5
    assert len(body["top_losers"]) == 5
    assert body["top_gainers"][0]["change_pct"] >= body["top_gainers"][-1]["change_pct"]
    assert body["top_losers"][0]["change_pct"] <= body["top_losers"][-1]["change_pct"]
    assert body["session"]["tick_seconds"] == 5
    assert body["session"]["total_bars"] == SESSION_BARS
    assert "not exchange data" in body["session"]["note"].lower()
    assert "SIMULATED" in body["notes"]["feed"]
    assert any("not live market data" in item for item in body["disclosures"])


def test_market_snapshot_is_deterministic_per_bar():
    first = build_market_snapshot(DAY, 12)
    second = build_market_snapshot(DAY, 12)
    assert first == second
    later = build_market_snapshot(DAY, 13)
    assert later["session"]["clock"] != first["session"]["clock"]
    assert later["stocks"][0]["price"] != first["stocks"][0]["price"]
    other_day = build_market_snapshot("2026-10-25", 12)
    assert other_day["stocks"] != first["stocks"]


def test_stock_snapshot_has_candles_and_rejects_unknown_symbol():
    detail = build_stock_snapshot("tcs", DAY, 25)
    assert detail["symbol"] == "TCS"
    assert detail["name"] == "Tata Consultancy Services"
    assert detail["data_mode"] == "simulated"
    assert 1 <= len(detail["candles"]) <= SESSION_BARS
    for candle in detail["candles"]:
        assert candle["high"] >= max(candle["open"], candle["close"])
        assert candle["low"] <= min(candle["open"], candle["close"])
    assert detail["candles"][-1]["time"] == detail["session"]["clock"]
    assert "not live market data" in detail["notes"]["feed"]
    with pytest.raises(KeyError):
        build_stock_snapshot("NOTREAL", DAY, 25)


def test_simulator_api_is_owner_authenticated_and_labelled_simulated(client, demo):
    response = client.get("/api/market/simulator", headers=demo["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_mode"] == "simulated"
    assert body["is_live_market_data"] is False
    assert body["as_of"]
    assert body["source"] == "FINOVEXA Indian market simulator"
    assert len(body["stocks"]) == 50
    assert body["session"]["mode"] == "accelerated_replay"
    assert "not live market data" in body["notes"]["feed"].lower()

    detail = client.get("/api/market/simulator/hdfcbank", headers=demo["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["symbol"] == "HDFCBANK"
    assert detail.json()["data_mode"] == "simulated"

    missing = client.get("/api/market/simulator/NOTREAL", headers=demo["headers"])
    assert missing.status_code == 404
    unauthorised = client.get("/api/market/simulator")
    assert unauthorised.status_code == 401
