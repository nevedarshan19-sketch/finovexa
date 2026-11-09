from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from conftest import amount, approval_by_title
from app.database import SessionLocal
from app.models import ApprovalRequest, utcnow


def test_pending_approvals_are_hash_bound_and_expire_aware(client, demo):
    response = client.get("/api/approvals?status=pending", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] == 3
    assert {item["action_type"] for item in body["items"]} == {
        "reminder.send",
        "investment.order",
        "cashflow.intervention",
    }
    for item in body["items"]:
        assert len(item["payload_hash"]) == 64
        assert item["can_decide"] is True
        assert item["risk_level"] in ("low", "medium", "high")
        assert item["expires_at"]


def test_changed_payload_hash_is_rejected(client, demo):
    approval = approval_by_title(client, demo["headers"], "Send payment reminder")
    response = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": "0" * 64},
        headers=demo["headers"],
    )
    assert response.status_code == 409
    assert "details changed" in response.json()["detail"]

    still_pending = client.get(
        f"/api/approvals/{approval['id']}", headers=demo["headers"]
    ).json()
    assert still_pending["status"] == "pending"


def test_reminder_approval_executes_simulated_dispatch_once(client, demo):
    approval = approval_by_title(client, demo["headers"], "Send payment reminder")
    first = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert first.status_code == 200, first.text
    executed = first.json()
    assert executed["status"] == "executed"
    assert executed["result"]["dispatch"] == "simulated"
    assert "Nothing was sent externally" in executed["result"]["note"]
    assert executed["decided_at"]

    second = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert second.status_code == 409
    assert "cannot be executed again" in second.json()["detail"]

    audit = client.get(
        "/api/audit-log?action=reminder.simulated_dispatch", headers=demo["headers"]
    ).json()["items"]
    assert any(item["entity_id"] == str(approval["payload"]["invoice_id"]) for item in audit)


def test_sms_reminder_requires_customer_mobile_and_simulates_dispatch(client, demo):
    invoice = next(
        item
        for item in client.get("/api/invoices?limit=100", headers=demo["headers"]).json()["items"]
        if amount(item["outstanding"]) > 0 and item["customer"].get("phone")
    )
    body = "FINOVEXA: invoice due soon. Please share a payment date."
    wrong_number = client.post(
        "/api/approvals/reminders",
        json={
            "invoice_id": invoice["id"],
            "body": body,
            "channel": "sms",
            "recipient": "+919999999999",
        },
        headers=demo["headers"],
    )
    assert wrong_number.status_code == 400
    assert "mobile number" in wrong_number.json()["detail"]

    too_long = client.post(
        "/api/approvals/reminders",
        json={
            "invoice_id": invoice["id"],
            "body": "x" * 321,
            "channel": "sms",
            "recipient": invoice["customer"]["phone"],
        },
        headers=demo["headers"],
    )
    assert too_long.status_code == 422

    created = client.post(
        "/api/approvals/reminders",
        json={
            "invoice_id": invoice["id"],
            "body": body,
            "channel": "sms",
            "recipient": invoice["customer"]["phone"],
        },
        headers=demo["headers"],
    )
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["payload"]["channel"] == "sms"
    assert approval["payload"]["recipient"].startswith("+91")
    assert len(approval["payload"]["recipient"]) == 13

    approved = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert approved.status_code == 200, approved.text
    result = approved.json()["result"]
    assert result["dispatch"] == "simulated"
    assert result["channel"] == "sms"
    assert "Nothing was sent externally" in result["note"]

    detail = client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()
    reminder = next(row for row in detail["reminders"] if row["id"] == result["reminder_id"])
    assert reminder["channel"] == "sms"
    assert reminder["status"] == "simulated_sent"


def test_investment_approval_creates_simulated_order_and_forbids_double_execution(client, demo):
    approval = approval_by_title(client, demo["headers"], "Review simulated buy order")
    response = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "executed"
    assert body["result"]["broker"] == "simulated"
    assert body["result"]["status"] == "simulated_pending"
    assert body["result"]["note"].startswith("Simulated broker order only")

    orders = client.get("/api/orders", headers=demo["headers"]).json()
    assert orders["broker_mode"] == "simulated"
    order = next(item for item in orders["items"] if item["approval_id"] == approval["id"])
    assert order["simulated"] is True
    assert order["status"] == "simulated_pending"

    rejected_again = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert rejected_again.status_code == 409

    filled = client.post(
        f"/api/orders/{order['id']}/simulate-fill",
        json={"confirm": True},
        headers=demo["headers"],
    )
    assert filled.status_code == 200
    assert filled.json()["order"]["status"] == "simulated_filled"
    assert "no money moved" in filled.json()["message"]

    refill = client.post(
        f"/api/orders/{order['id']}/simulate-fill",
        json={"confirm": True},
        headers=demo["headers"],
    )
    assert refill.status_code == 409


def test_order_cancel_flow(client, demo):
    approval = approval_by_title(client, demo["headers"], "Review simulated buy order")
    client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    order = next(
        item
        for item in client.get("/api/orders", headers=demo["headers"]).json()["items"]
        if item["approval_id"] == approval["id"]
    )

    no_confirm = client.post(
        f"/api/orders/{order['id']}/simulate-cancel",
        json={"confirm": False},
        headers=demo["headers"],
    )
    assert no_confirm.status_code == 400

    cancelled = client.post(
        f"/api/orders/{order['id']}/simulate-cancel",
        json={"confirm": True},
        headers=demo["headers"],
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["order"]["status"] == "simulated_cancelled"
    assert "No live broker order exists" in cancelled.json()["message"]

    fill_after_cancel = client.post(
        f"/api/orders/{order['id']}/simulate-fill",
        json={"confirm": True},
        headers=demo["headers"],
    )
    assert fill_after_cancel.status_code == 409


def test_reject_requires_pending_and_records_reason(client, demo):
    created = client.post(
        "/api/approvals/cashflow",
        json={
            "title": "Hold marketing spend this month",
            "recommendation": "Pause non-essential marketing until the overdue invoices clear.",
            "financial_impact": "25000.00",
        },
        headers=demo["headers"],
    )
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["status"] == "pending"

    rejected = client.post(
        f"/api/approvals/{approval['id']}/reject",
        json={"reason": "Campaign already booked."},
        headers=demo["headers"],
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["result"]["reason"] == "Campaign already booked."

    approve_after = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert approve_after.status_code == 409


def test_expired_approval_cannot_execute(client, demo):
    created = client.post(
        "/api/approvals/cashflow",
        json={
            "title": "Advisory that will expire",
            "recommendation": "This request is used to verify expiry handling.",
        },
        headers=demo["headers"],
    ).json()

    with SessionLocal() as db:
        row = db.get(ApprovalRequest, created["id"])
        row.expires_at = utcnow() - timedelta(minutes=5)
        db.commit()

    detail = client.get(f"/api/approvals/{created['id']}", headers=demo["headers"]).json()
    assert detail["status"] == "expired"
    assert detail["can_decide"] is False

    response = client.post(
        f"/api/approvals/{created['id']}/approve",
        json={"confirm": True, "payload_hash": created["payload_hash"]},
        headers=demo["headers"],
    )
    assert response.status_code == 409


def test_investment_headroom_is_rechecked_at_execution(client, demo):
    research = client.get("/api/research", headers=demo["headers"]).json()
    headroom = amount(research["cash_context"]["investable_headroom"])
    assert headroom > 0
    equity = next(item for item in research["items"] if item["symbol"] == "RELIANCE")
    price = amount(equity["quote"]["price"])
    quantity = int(headroom // price) + 2

    created = client.post(
        "/api/approvals/investments",
        json={"symbol": "RELIANCE", "side": "buy", "quantity": quantity, "order_type": "market"},
        headers=demo["headers"],
    )
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["action_type"] == "investment.order"
    assert amount(approval["financial_impact"]) > headroom

    executed = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert executed.status_code == 409
    assert "exceeds investable headroom" in executed.json()["detail"]

    detail = client.get(f"/api/approvals/{approval['id']}", headers=demo["headers"]).json()
    assert detail["status"] == "failed"
    assert "headroom" in detail["result"]["error"]


def test_simulated_sell_is_supported_without_holdings_check(client, demo):
    research = client.get("/api/research", headers=demo["headers"]).json()
    headroom = amount(research["cash_context"]["investable_headroom"])

    created = client.post(
        "/api/approvals/investments",
        json={"symbol": "RELIANCE", "side": "sell", "quantity": 1000, "order_type": "market"},
        headers=demo["headers"],
    )
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["title"].startswith("Review simulated sell order")
    assert approval["payload"]["side"] == "sell"
    assert approval["payload"]["holdings_check"] == "not_performed"
    assert amount(approval["financial_impact"]) > headroom

    executed = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["order"]["side"] == "sell"
    assert body["order"]["simulated"] is True
    assert "do not verify holdings" in body["result"]["note"]
    assert body["result"]["order_value"] is not None


def test_option_orders_are_simulated_and_lot_priced(client, demo):
    chain = client.get("/api/research/option-chain?strikes=21", headers=demo["headers"]).json()
    atm = next(row for row in chain["strikes"] if row["is_atm"])
    call = atm["call"]
    assert call["ltp"] > 0

    created = client.post(
        "/api/approvals/options",
        json={
            "expiry": chain["selected_expiry"],
            "strike": atm["strike"],
            "option_type": "call",
            "side": "buy",
            "lots": 1,
            "order_type": "market",
        },
        headers=demo["headers"],
    )
    assert created.status_code == 201, created.text
    approval = created.json()
    assert approval["action_type"] == "investment.order"
    assert approval["title"].startswith("Review simulated buy option")
    assert approval["payload"]["asset_class"] == "option"
    assert approval["payload"]["lot_size"] == 75
    assert approval["payload"]["option"]["strike"] == atm["strike"]
    assert approval["payload"]["option"]["option_type"] == "call"
    assert amount(approval["financial_impact"]) == amount(call["ltp"]) * 75

    executed = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"confirm": True, "payload_hash": approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()
    order = body["order"]
    assert order["asset_class"] == "option"
    assert order["side"] == "buy"
    assert order["lot_size"] == 75
    assert order["option"]["expiry"] == chain["selected_expiry"]
    assert order["option"]["chain_data_mode"] == "demo"
    assert amount(order["order_value"]) == amount(call["ltp"]) * 75
    assert body["result"]["simulated"] is True
    assert "no margin" in body["result"]["note"]

    overview = client.get("/api/market/overview", headers=demo["headers"]).json()
    assert all(item["asset_class"] != "option" for item in overview["items"])

    put_row = next(row for row in chain["strikes"] if row["is_atm"])
    sell = client.post(
        "/api/approvals/options",
        json={
            "expiry": chain["selected_expiry"],
            "strike": put_row["strike"],
            "option_type": "put",
            "side": "sell",
            "lots": 2,
            "order_type": "market",
        },
        headers=demo["headers"],
    )
    assert sell.status_code == 201, sell.text
    sell_approval = sell.json()
    sell_executed = client.post(
        f"/api/approvals/{sell_approval['id']}/approve",
        json={"confirm": True, "payload_hash": sell_approval["payload_hash"]},
        headers=demo["headers"],
    )
    assert sell_executed.status_code == 200, sell_executed.text
    sell_order = sell_executed.json()["order"]
    assert sell_order["side"] == "sell"
    assert sell_order["option"]["option_type"] == "put"
    assert "do not verify holdings" in sell_executed.json()["result"]["note"]


def test_option_order_validation(client, demo):
    chain = client.get("/api/research/option-chain", headers=demo["headers"]).json()
    base = {
        "expiry": chain["selected_expiry"],
        "strike": chain["strikes"][0]["strike"],
        "option_type": "call",
        "side": "buy",
        "lots": 1,
        "order_type": "market",
    }
    bad_strike = client.post(
        "/api/approvals/options",
        json={**base, "strike": 1},
        headers=demo["headers"],
    )
    assert bad_strike.status_code == 400
    assert "strike" in bad_strike.json()["detail"].lower()

    bad_expiry = client.post(
        "/api/approvals/options",
        json={**base, "expiry": "2020-01-01"},
        headers=demo["headers"],
    )
    assert bad_expiry.status_code == 400

    limit_without_price = client.post(
        "/api/approvals/options",
        json={**base, "order_type": "limit"},
        headers=demo["headers"],
    )
    assert limit_without_price.status_code == 400

    market_with_price = client.post(
        "/api/approvals/options",
        json={**base, "limit_price": "100"},
        headers=demo["headers"],
    )
    assert market_with_price.status_code == 400

    invalid_type = client.post(
        "/api/approvals/options",
        json={**base, "option_type": "straddle"},
        headers=demo["headers"],
    )
    assert invalid_type.status_code == 422


def test_approval_creation_validates_recipient_and_order_fields(client, demo):
    invoice = next(
        item
        for item in client.get("/api/invoices?limit=100", headers=demo["headers"]).json()["items"]
        if amount(item["outstanding"]) > 0
    )
    wrong_recipient = client.post(
        "/api/approvals/reminders",
        json={
            "invoice_id": invoice["id"],
            "body": "A reminder body long enough to pass validation.",
            "channel": "email",
            "recipient": "someone-else@example.com",
        },
        headers=demo["headers"],
    )
    assert wrong_recipient.status_code == 400

    limit_without_price = client.post(
        "/api/approvals/investments",
        json={"symbol": "TCS", "side": "buy", "quantity": 1, "order_type": "limit"},
        headers=demo["headers"],
    )
    assert limit_without_price.status_code == 400

    market_with_price = client.post(
        "/api/approvals/investments",
        json={
            "symbol": "TCS",
            "side": "buy",
            "quantity": 1,
            "order_type": "market",
            "limit_price": "3000",
        },
        headers=demo["headers"],
    )
    assert market_with_price.status_code == 400

    unknown_symbol = client.post(
        "/api/approvals/investments",
        json={"symbol": "NOTREAL", "side": "buy", "quantity": 1, "order_type": "market"},
        headers=demo["headers"],
    )
    assert unknown_symbol.status_code == 404
