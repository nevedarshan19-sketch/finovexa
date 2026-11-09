from __future__ import annotations

from decimal import Decimal

from conftest import amount


def test_market_overview_labels_every_quote(client, demo):
    response = client.get("/api/market/overview", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    for item in body["items"]:
        assert item["data_mode"] == "demo"
        assert item["freshness"] == "demo"
        assert item["is_stale"] is False
        assert item["source"]
        assert item["as_of"]
        assert item["price"] is not None
        assert item["note"] == "Demo quote — not live market data."

    summary = body["summary"]
    assert summary["demo_count"] == len(body["items"])
    assert summary["live_count"] == 0
    assert summary["stale_count"] == 0
    assert set(body["groups"]) == {"metals", "indices", "equities"}
    assert len(body["groups"]["equities"]) == 50


def test_quote_detail_and_unknown_symbol(client, demo):
    detail = client.get("/api/market/instruments/TCS", headers=demo["headers"])
    assert detail.status_code == 200
    quote = detail.json()
    assert quote["symbol"] == "TCS"
    assert quote["asset_class"] == "equity"
    assert quote["data_mode"] == "demo"
    assert quote["currency"] == "INR"

    missing = client.get("/api/market/instruments/NOTREAL", headers=demo["headers"])
    assert missing.status_code == 404

    history = client.get("/api/market/instruments/TCS/history?days=30", headers=demo["headers"])
    assert history.status_code == 200
    series = history.json()
    assert series["symbol"] == "TCS"
    assert len(series["candles"]) > 10
    for candle in series["candles"]:
        assert amount(candle["high"]) >= amount(candle["low"])


def test_news_is_attributed_and_deduplicated(client, demo):
    response = client.get("/api/market/news?limit=20", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert body["mode"] == "demo"
    urls = [item["url"] for item in body["items"]]
    titles = [item["title"].strip().lower() for item in body["items"]]
    assert len(urls) == len(set(urls))
    assert len(titles) == len(set(titles))
    for article in body["items"]:
        assert article["source"]
        assert article["data_mode"] == "demo"
        assert article["is_stale"] is False
        assert article["analysis_note"] == "Sample editorial notes for the demo."

    filtered = client.get("/api/market/news?instrument=TCS", headers=demo["headers"]).json()
    assert filtered["items"]
    assert all("TCS" in article["instruments"] for article in filtered["items"])


def test_research_signals_are_model_generated_and_orders_simulated(client, demo):
    response = client.get("/api/research", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    for item in body["items"]:
        signal = item["signal"]
        assert signal is not None
        assert signal["is_model_generated"] is True
        assert "not an analyst rating or consensus" in signal["disclosure"]
        assert item["analyst_ratings"]["items"] == []
        assert "not fabricated" in item["analyst_ratings"]["note"]
        assert amount(item["cash_constraints"]["investable_headroom"]) >= 0
        assert item["quote"]["data_mode"] == "demo"

    assert body["broker_status"]["mode"] == "simulated"
    assert body["broker_status"]["live_trading_enabled"] is False
    for order in body["orders"]:
        assert order["simulated"] is True
        assert order["broker"] == "simulated"


def test_research_requires_profile(client):
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "no-profile@example.com",
            "password": "NoProfile123!",
            "full_name": "No Profile",
            "business_name": "No Profile Co",
            "currency": "INR",
        },
    )
    assert registered.status_code == 201
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    response = client.get("/api/research", headers=headers)
    assert response.status_code == 200


def test_nifty50_token_catalogue_is_complete_and_public(client, demo):
    response = client.get("/api/research/stock-tokens", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["index"] == "NIFTY 50"
    assert body["total"] == 50
    assert len(body["items"]) == 50
    symbols = [item["symbol"] for item in body["items"]]
    keys = [item["instrument_key"] for item in body["items"]]
    assert len(set(symbols)) == 50
    assert len(set(keys)) == 50
    assert all(key.startswith("NSE_EQ|") for key in keys)
    assert "HDFCBANK" in symbols
    assert next(item for item in body["items"] if item["symbol"] == "HDFCBANK")["instrument_key"] == "NSE_EQ|INE040A01034"
    assert body["covered"] == 50
    assert body["signals"] == 4
    assert all(item["seeded"] for item in body["items"])
    assert sum(1 for item in body["items"] if item["signal_available"]) == 4
    assert "not credentials" in body["note"]
    unauthorised = client.get("/api/research/stock-tokens")
    assert unauthorised.status_code == 401


def test_nifty50_trade_desk_lists_all_tradable_stocks(client, demo):
    response = client.get("/api/research/nifty50", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 50
    assert body["tradable"] == 50
    assert len(body["items"]) == 50
    assert body["provider"]["upstox_configured"] is False
    assert "demo" in body["provider"]["note"]
    assert body["modes"]["demo"] == 50
    assert "simulated" in body["orders_note"]
    for item in body["items"]:
        assert item["tradable"] is True
        assert item["instrument_id"] is not None
        assert item["quote"]["data_mode"] == "demo"
        assert item["quote"]["price"] is not None
        assert item["quote"]["price"] > 0
        assert item["instrument_key"].startswith("NSE_EQ|")
    assert sum(1 for item in body["items"] if item["signal_available"]) == 4
    unauthorised = client.get("/api/research/nifty50")
    assert unauthorised.status_code == 401


def test_nifty_option_chain_is_labelled_demo(client, demo):
    response = client.get("/api/research/option-chain", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["data_mode"] == "demo"
    assert body["verified_live"] is False
    assert body["underlying"]["symbol"] == "NIFTY50"
    assert body["underlying"]["spot"] is not None
    assert body["source"] == "FINOVEXA demo options model"
    assert body["expiries"]
    assert body["selected_expiry"] in [item["date"] for item in body["expiries"]]
    assert len(body["strikes"]) == 21
    strike_values = [row["strike"] for row in body["strikes"]]
    summary = body["summary"]
    assert summary["atm_strike"] in strike_values
    assert summary["max_pain"] is not None
    assert abs(summary["max_pain"] - summary["atm_strike"]) <= 15 * summary["strike_step"]
    assert summary["support"] is not None
    assert summary["resistance"] is not None
    assert summary["pcr_oi"] is not None and summary["pcr_oi"] > 0
    for row in body["strikes"]:
        for side in ("call", "put"):
            leg = row[side]
            assert leg["data_mode"] == "demo"
            assert leg["instrument_key"] is None
            assert leg["ltp"] > 0
            assert leg["iv"] > 0
            assert leg["oi"] > 0
    assert "demo chain are simulated" in body["notes"]["trading"]
    assert "live execution is unavailable" in body["notes"]["trading"]
    assert body["lot_size"] == 75
    assert "Not investment advice" in body["notes"]["advice"]
    unauthorised = client.get("/api/research/option-chain")
    assert unauthorised.status_code == 401


def test_nifty_option_chain_expiry_selection_and_window(client, demo):
    initial = client.get("/api/research/option-chain", headers=demo["headers"]).json()
    target = initial["expiries"][2]["date"]
    selected = client.get(
        f"/api/research/option-chain?expiry={target}&strikes=11",
        headers=demo["headers"],
    )
    assert selected.status_code == 200
    body = selected.json()
    assert body["selected_expiry"] == target
    assert len(body["strikes"]) == 11
    fallback = client.get(
        "/api/research/option-chain?expiry=2020-01-01",
        headers=demo["headers"],
    ).json()
    assert fallback["selected_expiry"] != "2020-01-01"
    assert fallback["expiry_note"]
    invalid = client.get(
        "/api/research/option-chain?expiry=not-a-date",
        headers=demo["headers"],
    )
    assert invalid.status_code == 400
