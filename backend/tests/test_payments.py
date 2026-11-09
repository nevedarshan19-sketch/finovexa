from __future__ import annotations

import json
from decimal import Decimal

from conftest import amount
from app.services.integrations.paypal import demo_signature


def test_payment_overview_separates_cash_from_pending(client, demo):
    response = client.get("/api/payments/overview?days=30", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["provider"]["configured"] is False
    assert body["provider"]["mode"] == "simulated"
    assert body["provider"]["mode_label"] == "SIMULATED"
    assert amount(body["summary"]["confirmed_received_period"]) == amount("68440.00")
    assert amount(body["summary"]["pending_total"]) == amount("30000.00")
    assert "Only confirmed provider captures" in body["summary"]["confirmed_note"]
    assert "never increase recorded cash" in body["summary"]["pending_note"]
    assert len(body["open_invoices"]) == 15
    assert body["webhook_endpoint"] == "/api/paypal/webhook"

    statuses = {payment["status"] for payment in body["payments"]}
    assert statuses == {"confirmed", "pending", "failed"}


def test_simulated_payment_is_labelled_and_idempotent(client, demo):
    invoice = next(
        item
        for item in client.get("/api/invoices?limit=100", headers=demo["headers"]).json()["items"]
        if item["number"] == "INV-1039"
    )
    payload = {"invoice_id": invoice["id"]}
    first = client.post("/api/paypal/simulate", json=payload, headers=demo["headers"])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mode"] == "simulated"
    assert body["simulation"] is True
    assert body["payment"]["status"] == "confirmed"
    assert body["payment"]["provider"] == "paypal_demo"
    assert body["invoice"]["status"] == "paid"
    assert "not proof of a real PayPal transaction" in body["message"]

    second = client.post("/api/paypal/simulate", json=payload, headers=demo["headers"])
    assert second.status_code == 200
    assert second.json()["payment"]["id"] == body["payment"]["id"]
    duplicates = client.get("/api/payments?status=confirmed", headers=demo["headers"]).json()["items"]
    matching = [p for p in duplicates if p["provider_ref"] == body["payment"]["provider_ref"]]
    assert len(matching) == 1


def test_capture_requires_configured_provider(client, demo):
    response = client.post("/api/paypal/orders/FAKE-ORDER/capture", headers=demo["headers"])
    assert response.status_code == 409
    assert "not configured" in response.json()["detail"]

    status = client.get("/api/paypal/orders/FAKE-ORDER", headers=demo["headers"])
    assert status.status_code == 200
    assert status.json()["status"] == "UNAVAILABLE"
    assert "Nothing is invented" in status.json()["note"]


def test_webhook_rejects_unsigned_events(client):
    payload = {"id": "EVT-UNSIGNED-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}
    response = client.post("/api/paypal/webhook", json=payload)
    assert response.status_code == 401
    assert "signature verification failed" in response.json()["detail"].lower()


def test_signed_webhook_confirms_once_and_rejects_duplicate(client, demo):
    event = {
        "id": "EVT-TEST-COMPLETE-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAPTURE-TEST-1",
            "amount": {"value": "51330.00", "currency_code": "INR"},
            "custom_id": "invoice:1",
        },
    }
    raw = json.dumps(event, separators=(",", ":")).encode("utf-8")
    signature = demo_signature(raw)

    first = client.post(
        "/api/paypal/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-FINOVEXA-Demo-Signature": signature,
        },
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["duplicate"] is False
    assert body["outcome"] == "payment_confirmed"
    assert body["verification"] == "demo_hmac"
    assert body["payment_id"]

    invoice = client.get("/api/invoices/1", headers=demo["headers"]).json()
    assert invoice["status"] == "paid"
    assert amount(invoice["outstanding"]) == 0

    duplicate = client.post(
        "/api/paypal/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-FINOVEXA-Demo-Signature": signature,
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert "already processed" in duplicate.json()["message"]

    payments = client.get("/api/payments", headers=demo["headers"]).json()["items"]
    capture_payments = [p for p in payments if p["provider_ref"] == "CAPTURE-TEST-1"]
    assert len(capture_payments) == 1


def test_webhook_notes_pending_and_unmapped_events_without_cash(client, demo):
    pending_event = {
        "id": "EVT-TEST-PENDING-1",
        "event_type": "PAYMENT.CAPTURE.PENDING",
        "resource": {
            "id": "CAPTURE-PENDING-1",
            "amount": {"value": "1000.00", "currency_code": "INR"},
            "custom_id": "invoice:1",
        },
    }
    raw = json.dumps(pending_event).encode("utf-8")
    response = client.post(
        "/api/paypal/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-FINOVEXA-Demo-Signature": demo_signature(raw),
        },
    )
    assert response.status_code == 200
    assert response.json()["outcome"].startswith("noted:")
    assert response.json()["payment_id"] is None

    unmapped_event = {
        "id": "EVT-TEST-UNMAPPED-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAPTURE-UNMAPPED-1",
            "amount": {"value": "1000.00", "currency_code": "INR"},
            "custom_id": "no-invoice-here",
        },
    }
    raw = json.dumps(unmapped_event).encode("utf-8")
    unmapped = client.post(
        "/api/paypal/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-FINOVEXA-Demo-Signature": demo_signature(raw),
        },
    )
    assert unmapped.status_code == 200
    assert unmapped.json()["outcome"].startswith("unmapped:")
    assert unmapped.json()["payment_id"] is None

    overview = client.get("/api/payments/overview", headers=demo["headers"]).json()
    assert amount(overview["summary"]["confirmed_received_period"]) == amount("68440.00")
    assert amount(overview["summary"]["pending_total"]) == amount("30000.00")


def test_match_unmatched_payment_requires_confirmation(client, demo):
    unmatched = client.get("/api/recovery/unmatched", headers=demo["headers"]).json()["items"]
    payment = next(item for item in unmatched if item["provider_ref"] == "NEFT-DEMO-88421")
    suggestion = payment["suggested_matches"][0]
    invoice_id = suggestion["invoice"]["id"]

    no_confirm = client.post(
        f"/api/payments/{payment['id']}/match",
        json={"invoice_id": invoice_id, "confirm": False},
        headers=demo["headers"],
    )
    assert no_confirm.status_code == 400

    matched = client.post(
        f"/api/payments/{payment['id']}/match",
        json={"invoice_id": invoice_id, "confirm": True},
        headers=demo["headers"],
    )
    assert matched.status_code == 200, matched.text
    assert matched.json()["payment"]["invoice_id"] == invoice_id
    assert matched.json()["invoice"]["status"] == "paid"
    assert amount(matched.json()["invoice"]["outstanding"]) == 0

    again = client.post(
        f"/api/payments/{payment['id']}/match",
        json={"invoice_id": invoice_id, "confirm": True},
        headers=demo["headers"],
    )
    assert again.status_code == 409
