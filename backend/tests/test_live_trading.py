from __future__ import annotations

from decimal import Decimal

import pytest

from conftest import amount
from app.config import settings
from app.database import SessionLocal
from app.models import BrokerOrder, MarketInstrument, MarketQuote, User, utcnow
from app.services.approvals import create_approval
from app.services.integrations.upstox import UpstoxError, upstox_client


def make_quote_live(symbol: str = "RELIANCE") -> dict:
    with SessionLocal() as db:
        instrument = (
            db.query(MarketInstrument).filter(MarketInstrument.symbol == symbol).one()
        )
        quote = (
            db.query(MarketQuote)
            .filter(MarketQuote.instrument_id == instrument.id)
            .order_by(MarketQuote.as_of.desc(), MarketQuote.id.desc())
            .first()
        )
        assert quote is not None
        quote.data_mode = "live"
        quote.source = "Upstox API"
        db.commit()
        return {"external_key": instrument.external_key, "price": quote.price}


@pytest.fixture()
def live_enabled(monkeypatch):
    monkeypatch.setattr(settings, "UPSTOX_LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "UPSTOX_ACCESS_TOKEN", "test-upstox-token")
    return settings


@pytest.fixture()
def broker_mocks(monkeypatch):
    calls: dict[str, object] = {"placed": [], "cancelled": [], "synced": []}

    def fake_order_book():
        calls["order_book_calls"] = int(calls.get("order_book_calls", 0)) + 1
        return []

    def fake_place(payload):
        calls["placed"].append(payload)
        return {"order_id": "UPSTOX-TEST-1"}

    def fake_details(order_id):
        calls["synced"].append(order_id)
        return {
            "order_id": order_id,
            "status": "open",
            "status_message": "Order received",
        }

    def fake_cancel(order_id):
        calls["cancelled"].append(order_id)
        return {"order_id": order_id}

    monkeypatch.setattr(upstox_client, "get_order_book", fake_order_book)
    monkeypatch.setattr(upstox_client, "place_order", fake_place)
    monkeypatch.setattr(upstox_client, "get_order_details", fake_details)
    monkeypatch.setattr(upstox_client, "cancel_order", fake_cancel)
    return calls


def create_order_approval(client, demo, **overrides):
    body = {
        "symbol": "RELIANCE",
        "side": "buy",
        "quantity": 1,
        "order_type": "market",
    }
    body.update(overrides)
    return client.post("/api/approvals/investments", json=body, headers=demo["headers"])


def approve(client, demo, approval):
    return client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )


def test_live_orders_are_rejected_when_disabled(client, demo):
    response = create_order_approval(client, demo, execution_mode="live")
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]


def test_live_orders_require_a_live_quote(client, demo, live_enabled):
    response = create_order_approval(client, demo, execution_mode="live")
    assert response.status_code == 409
    assert "live Upstox quote" in response.json()["detail"]


def test_live_order_submits_to_upstox_and_returns_broker_status(
    client, demo, live_enabled, broker_mocks
):
    quote = make_quote_live()
    created = create_order_approval(client, demo, execution_mode="live")
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["title"].startswith("Review live buy order")
    assert approval["payload"]["execution_mode"] == "live"
    assert approval["payload"]["simulated"] is False

    executed = approve(client, demo, approval)
    assert executed.status_code == 200, executed.text
    body = executed.json()
    order = body["order"]
    assert body["result"]["broker"] == "upstox"
    assert body["result"]["simulated"] is False
    assert body["result"]["execution_mode"] == "live"
    assert order["simulated"] is False
    assert order["broker"] == "upstox"
    assert order["broker_order_id"] == "UPSTOX-TEST-1"
    assert order["status"] == "live_open"
    assert order["broker_status"] == "open"
    assert order["execution_mode"] == "live"

    assert len(broker_mocks["placed"]) == 1
    submitted = broker_mocks["placed"][0]
    assert submitted["quantity"] == 1
    assert submitted["product"] == "D"
    assert submitted["validity"] == "DAY"
    assert submitted["price"] == 0.0
    assert submitted["order_type"] == "MARKET"
    assert submitted["transaction_type"] == "BUY"
    assert submitted["instrument_token"] == quote["external_key"]
    assert submitted["tag"].startswith(f"BP-{approval['id']}-")
    assert submitted["market_protection"] == -1

    orders = client.get("/api/orders", headers=demo["headers"]).json()
    assert orders["broker_mode"] == "live"
    assert orders["live_trading_enabled"] is True
    assert orders["upstox_configured"] is True

    audit = client.get(
        "/api/audit-log?action=order.live_submitted", headers=demo["headers"]
    ).json()["items"]
    assert any(item["entity_id"] == str(order["id"]) for item in audit)


def test_live_order_status_can_be_synced_and_cancelled(
    client, demo, live_enabled, broker_mocks, monkeypatch
):
    make_quote_live()
    created = create_order_approval(client, demo, execution_mode="live").json()
    order = approve(client, demo, created).json()["order"]

    monkeypatch.setattr(
        upstox_client,
        "get_order_details",
        lambda order_id: {
            "order_id": order_id,
            "status": "complete",
            "status_message": "Order completed",
        },
    )
    synced = client.post(f"/api/orders/{order['id']}/sync", headers=demo["headers"])
    assert synced.status_code == 200, synced.text
    synced_order = synced.json()["order"]
    assert synced_order["status"] == "live_filled"
    assert synced_order["broker_status"] == "complete"
    assert synced_order["last_synced_at"] is not None

    cancelled = client.post(
        f"/api/orders/{order['id']}/cancel-request",
        json={"confirm": True},
        headers=demo["headers"],
    )
    assert cancelled.status_code == 409
    assert "cannot be cancelled" in cancelled.json()["detail"]

    monkeypatch.setattr(
        upstox_client,
        "get_order_details",
        lambda order_id: {
            "order_id": order_id,
            "status": "open",
            "status_message": "Order received",
        },
    )
    second = approve(
        client,
        demo,
        create_order_approval(client, demo, execution_mode="live").json(),
    ).json()["order"]
    cancel_response = client.post(
        f"/api/orders/{second['id']}/cancel-request",
        json={"confirm": True},
        headers=demo["headers"],
    )
    assert cancel_response.status_code == 200, cancel_response.text
    assert cancel_response.json()["order"]["status"] == "live_cancel_requested"
    assert broker_mocks["cancelled"] == ["UPSTOX-TEST-1"]

    simulator = client.post(
        f"/api/orders/{second['id']}/simulate-fill",
        json={"confirm": True},
        headers=demo["headers"],
    )
    assert simulator.status_code == 409
    assert "live order" in simulator.json()["detail"]


def test_upstox_failure_marks_approval_failed_without_order(
    client, demo, live_enabled, monkeypatch
):
    make_quote_live()
    monkeypatch.setattr(upstox_client, "get_order_book", lambda: [])
    monkeypatch.setattr(
        upstox_client,
        "place_order",
        lambda payload: (_ for _ in ()).throw(UpstoxError("Insufficient funds.")),
    )

    approval = create_order_approval(client, demo, execution_mode="live").json()
    response = approve(client, demo, approval)
    assert response.status_code == 502
    assert "Upstox rejected the live order" in response.json()["detail"]

    detail = client.get(
        f"/api/approvals/{approval['id']}", headers=demo["headers"]
    ).json()
    assert detail["status"] == "failed"
    assert detail["order"] is None
    with SessionLocal() as db:
        assert (
            db.query(BrokerOrder)
            .filter(BrokerOrder.approval_id == approval["id"])
            .one_or_none()
            is None
        )


def test_simulated_remains_the_default_even_when_live_is_enabled(
    client, demo, live_enabled, broker_mocks
):
    make_quote_live()
    created = create_order_approval(client, demo)
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["payload"]["execution_mode"] == "simulated"
    assert approval["payload"]["simulated"] is True
    assert approval["title"].startswith("Review simulated buy order")

    body = approve(client, demo, approval).json()
    assert body["result"]["simulated"] is True
    assert body["order"]["simulated"] is True
    assert body["order"]["broker"] == "simulated"
    assert broker_mocks["placed"] == []


def test_live_option_requires_a_live_chain(client, demo, live_enabled):
    chain = client.get("/api/research/option-chain?strikes=21", headers=demo["headers"]).json()
    atm = next(row for row in chain["strikes"] if row["is_atm"])
    response = client.post(
        "/api/approvals/options",
        json={
            "expiry": chain["selected_expiry"],
            "strike": atm["strike"],
            "option_type": "call",
            "side": "buy",
            "lots": 1,
            "order_type": "market",
            "execution_mode": "live",
        },
        headers=demo["headers"],
    )
    assert response.status_code == 409
    assert "live Upstox option chain" in response.json()["detail"]


def test_live_option_order_uses_lot_quantity_and_instrument_token(
    client, demo, live_enabled, broker_mocks
):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "demo@finovexa.ai").one()
        instrument = MarketInstrument(
            symbol="NIFTY-TEST-CALL",
            name="NIFTY Test Call",
            asset_class="option",
            exchange="NSE",
            currency="INR",
            unit="lot",
            external_key="NSE_FO|TEST-TOKEN",
        )
        db.add(instrument)
        db.flush()
        db.add(
            MarketQuote(
                instrument_id=instrument.id,
                price=Decimal("100"),
                previous_close=Decimal("100"),
                change_pct=Decimal("0"),
                as_of=utcnow(),
                source="Upstox API",
                data_mode="live",
            )
        )
        db.flush()
        payload = {
            "symbol": instrument.symbol,
            "exchange": "NSE",
            "asset_class": "option",
            "side": "buy",
            "quantity": 2,
            "lot_size": 75,
            "order_type": "market",
            "limit_price": None,
            "quote_price": "100",
            "quote_as_of": utcnow().isoformat(),
            "quote_data_mode": "live",
            "illustrative_order_value": "15000.00",
            "option": {
                "underlying": "NIFTY 50",
                "expiry": "2026-10-29",
                "strike": 25000.0,
                "option_type": "call",
                "instrument_key": "NSE_FO|TEST-TOKEN",
                "symbol": instrument.symbol,
                "display_name": "NIFTY 25000 Call · 2026-10-29",
                "lot_size": 75,
                "chain_data_mode": "live",
            },
            "holdings_check": "not_required_for_buy",
            "execution_mode": "live",
            "simulated": False,
        }
        approval = create_approval(
            db,
            user,
            action_type="investment.order",
            title="Review live buy option · 2 lots NIFTY-TEST-CALL",
            reason="Owner-requested live derivative order for execution testing.",
            payload=payload,
            financial_impact=Decimal("15000.00"),
            risk_level="high",
        )
        approval_id = approval.id
        approval_hash = approval.payload_hash

    executed = approve(client, demo, {"id": approval_id, "payload_hash": approval_hash})
    assert executed.status_code == 200, executed.text
    body = executed.json()
    order = body["order"]
    assert order["asset_class"] == "option"
    assert order["simulated"] is False
    assert order["broker"] == "upstox"
    assert order["lot_size"] == 75
    assert broker_mocks["placed"][0]["quantity"] == 2 * 75
    assert broker_mocks["placed"][0]["instrument_token"] == "NSE_FO|TEST-TOKEN"
    assert amount(order["order_value"]) == Decimal("15000.00")
