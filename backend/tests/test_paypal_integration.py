from __future__ import annotations

import json
import re
from decimal import Decimal

import pytest

from conftest import amount
from app.config import settings
from app.services.integrations.paypal import paypal_client

SANDBOX_CLIENT_ID = "sandbox-client-id-ABCD"
SANDBOX_SECRET = "sandbox-secret-value-1234"


class FakePayPalResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class FakePayPalAPI:
    """In-memory stand-in for the PayPal REST API. No network call leaves the process."""

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.capture_seq = 0
        self.refund_seq = 0
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url))
        if url.endswith("/v1/oauth2/token"):
            return FakePayPalResponse(
                200, {"access_token": "fake-access-token", "expires_in": 3600}
            )
        if url.endswith("/v2/checkout/orders"):
            unit = (kwargs.get("json") or {})["purchase_units"][0]
            order_id = f"ORDER-SANDBOX-{len(self.orders) + 1}"
            self.orders[order_id] = {
                "custom_id": unit.get("custom_id"),
                "amount": unit["amount"],
                "status": "CREATED",
            }
            return FakePayPalResponse(
                201,
                {
                    "id": order_id,
                    "status": "CREATED",
                    "links": [
                        {
                            "rel": "approve",
                            "href": (
                                "https://www.sandbox.paypal.com/checkoutnow?token="
                                f"{order_id}"
                            ),
                        }
                    ],
                },
            )
        match = re.search(r"/v2/checkout/orders/([^/]+)/capture$", url)
        if match:
            order_id = match.group(1)
            order = self.orders[order_id]
            if order.get("capture"):
                # PayPal replays the original capture for a repeated capture call.
                return FakePayPalResponse(201, order["capture"])
            self.capture_seq += 1
            capture_id = f"CAPTURE-SANDBOX-{self.capture_seq}"
            order["status"] = "COMPLETED"
            order["capture"] = {
                "id": order_id,
                "status": "COMPLETED",
                "payer": {"email_address": "sandbox-buyer@example.com"},
                "purchase_units": [
                    {
                        "custom_id": order["custom_id"],
                        "amount": order["amount"],
                        "payments": {
                            "captures": [
                                {
                                    "id": capture_id,
                                    "status": "COMPLETED",
                                    "amount": order["amount"],
                                }
                            ]
                        },
                    }
                ],
            }
            return FakePayPalResponse(201, order["capture"])
        match = re.search(r"/v2/payments/captures/([^/]+)/refund$", url)
        if match:
            self.refund_seq += 1
            body = kwargs.get("json") or {}
            return FakePayPalResponse(
                201,
                {
                    "id": f"REFUND-SANDBOX-{self.refund_seq}",
                    "status": "COMPLETED",
                    "amount": body["amount"],
                },
            )
        if url.endswith("/v1/notifications/verify-webhook-signature"):
            return FakePayPalResponse(200, {"verification_status": "SUCCESS"})
        raise AssertionError(f"Unexpected PayPal call: {url}")

    def get(self, url: str, **kwargs):
        raise AssertionError(f"Unexpected PayPal GET: {url}")


@pytest.fixture()
def paypal_api(monkeypatch):
    fake = FakePayPalAPI()
    monkeypatch.setattr(settings, "PAYPAL_SANDBOX_CLIENT_ID", SANDBOX_CLIENT_ID, raising=False)
    monkeypatch.setattr(settings, "PAYPAL_SANDBOX_CLIENT_SECRET", SANDBOX_SECRET, raising=False)
    monkeypatch.setattr(settings, "PAYPAL_SANDBOX_WEBHOOK_ID", "WH-SANDBOX-ID", raising=False)
    import app.services.integrations.paypal as paypal_module

    monkeypatch.setattr(paypal_module.httpx, "post", fake.post)
    monkeypatch.setattr(paypal_module.httpx, "get", fake.get)
    paypal_client.configure_runtime("sandbox", True)
    paypal_client._token = None
    paypal_client._token_key = None
    yield fake
    paypal_client._token = None
    paypal_client._token_key = None
    paypal_client.configure_runtime(None, None)


def _invoice(client, headers, number: str = "INV-1056") -> dict:
    items = client.get("/api/invoices?limit=100", headers=headers).json()["items"]
    return next(item for item in items if item["number"] == number)


def _employee_headers(client) -> dict:
    response = client.post(
        "/api/auth/employee/login",
        json={"email": "employee@finovexa.ai", "password": "Employee1234!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _post_webhook(client, event: dict, *, signature: str | None = None):
    raw = json.dumps(event, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-FINOVEXA-Demo-Signature"] = signature
    else:
        headers.update(
            {
                "PayPal-Transmission-Id": "transmission-1",
                "PayPal-Transmission-Sig": "signature-1",
                "PayPal-Transmission-Time": "2026-11-01T00:00:00Z",
                "PayPal-Cert-Url": "https://api.paypal.com/cert.pem",
                "PayPal-Auth-Algo": "SHA256withRSA",
            }
        )
    return client.post("/api/paypal/webhook", content=raw, headers=headers)


def test_settings_mask_secrets_and_protect_live_mode(client, demo, paypal_api):
    response = client.get("/api/paypal/settings", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "sandbox"
    assert body["configured"] is True
    assert body["mode"] == "sandbox"
    assert body["webhook_signature_verification"] is True
    assert body["active_client_id_hint"].endswith("ABCD")
    assert body["webhook_endpoint"] == "/api/paypal/webhook"
    assert SANDBOX_SECRET not in response.text
    assert "fake-access-token" not in response.text

    test = client.post("/api/paypal/settings/test", headers=demo["headers"])
    assert test.status_code == 200, test.text
    assert test.json()["connected"] is True
    assert test.json()["environment"] == "sandbox"
    assert SANDBOX_SECRET not in test.text

    no_confirm = client.put(
        "/api/paypal/settings",
        json={"environment": "live", "enabled": True, "confirm_live": False},
        headers=demo["headers"],
    )
    assert no_confirm.status_code == 400
    live = client.put(
        "/api/paypal/settings",
        json={"environment": "live", "enabled": True, "confirm_live": True},
        headers=demo["headers"],
    )
    assert live.status_code == 409
    assert "PAYPAL_LIVE_CLIENT_ID" in live.json()["detail"]

    still_sandbox = client.get("/api/paypal/settings", headers=demo["headers"]).json()
    assert still_sandbox["environment"] == "sandbox"


def test_sandbox_checkout_marks_invoice_pending_and_capture_is_verified_once(
    client, demo, paypal_api
):
    invoice = _invoice(client, demo["headers"])
    original_status = invoice["status"]
    assert original_status != "paid"

    created = client.post(
        "/api/paypal/orders",
        json={"invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert created.status_code == 200, created.text
    order = created.json()
    assert order["status"] == "CREATED"
    assert order["mode"] == "sandbox"
    assert order["amount"] == invoice["outstanding"]
    assert order["approve_url"].startswith("https://www.sandbox.paypal.com/")

    pending = client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()
    assert pending["status"] == "pending_payment"

    reused = client.post(
        "/api/paypal/orders",
        json={"invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert reused.status_code == 200
    assert reused.json()["local_order_id"] == order["local_order_id"]

    captured = client.post(
        f"/api/paypal/orders/{order['id']}/capture", headers=demo["headers"]
    )
    assert captured.status_code == 200, captured.text
    capture_body = captured.json()
    assert capture_body["duplicate"] is False
    assert capture_body["payment"]["status"] == "confirmed"
    assert capture_body["payment"]["provider"] == "paypal"
    assert capture_body["payment"]["reconciliation_status"] == "matched"
    assert capture_body["invoice"]["status"] == "paid"

    repeat = client.post(
        f"/api/paypal/orders/{order['id']}/capture", headers=demo["headers"]
    )
    assert repeat.status_code == 200
    assert repeat.json()["duplicate"] is True
    assert repeat.json()["payment"]["id"] == capture_body["payment"]["id"]

    payments = client.get("/api/payments?status=confirmed", headers=demo["headers"]).json()[
        "items"
    ]
    matches = [
        item
        for item in payments
        if item["provider_ref"] == capture_body["provider_reference"]
    ]
    assert len(matches) == 1

    reconciliation = client.get("/api/paypal/reconciliation", headers=demo["headers"]).json()
    history = [row for row in reconciliation["history"] if row["payment_id"] == capture_body["payment"]["id"]]
    assert history and history[0]["status"] == "matched"

    orders = client.get("/api/paypal/orders", headers=demo["headers"]).json()["items"]
    stored = next(item for item in orders if item["provider_order_id"] == order["id"])
    assert stored["status"] == "COMPLETED"
    assert stored["capture_id"] == capture_body["provider_reference"]


def test_cancelling_checkout_releases_pending_invoice(client, demo, paypal_api):
    invoice = _invoice(client, demo["headers"], "INV-1054")
    created = client.post(
        "/api/paypal/orders",
        json={"invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert created.status_code == 200, created.text
    assert (
        client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()["status"]
        == "pending_payment"
    )
    cancelled = client.post(
        f"/api/paypal/orders/{created.json()['id']}/cancel", headers=demo["headers"]
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["order"]["status"] == "CANCELLED"
    released = client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()
    assert released["status"] != "pending_payment"
    assert amount(released["outstanding"]) == amount(invoice["outstanding"])


def test_refund_requires_confirmation_and_reduces_recorded_cash(client, demo, paypal_api):
    invoice = _invoice(client, demo["headers"], "INV-1057")
    created = client.post(
        "/api/paypal/orders",
        json={"invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert created.status_code == 200, created.text
    captured = client.post(
        f"/api/paypal/orders/{created.json()['id']}/capture", headers=demo["headers"]
    )
    payment = captured.json()["payment"]
    assert captured.json()["invoice"]["status"] == "paid"

    overview_before = client.get("/api/payments/overview", headers=demo["headers"]).json()
    unconfirmed = client.post(
        f"/api/paypal/payments/{payment['id']}/refund",
        json={"reason": "Customer return", "confirm": False},
        headers=demo["headers"],
    )
    assert unconfirmed.status_code == 400

    refunded = client.post(
        f"/api/paypal/payments/{payment['id']}/refund",
        json={"reason": "Customer return", "confirm": True},
        headers=demo["headers"],
    )
    assert refunded.status_code == 200, refunded.text
    body = refunded.json()
    assert body["mode"] == "sandbox"
    assert body["simulation"] is False
    assert body["status"] == "completed"
    assert body["refund"]["provider_refund_id"].startswith("REFUND-SANDBOX-")
    assert amount(body["refund_payment"]["amount"]) == -amount(payment["amount"])
    assert body["refund_payment"]["provider"] == "paypal_refund"
    invoice_after = body["invoice"]
    assert invoice_after["status"] != "paid"
    assert amount(invoice_after["outstanding"]) == amount(invoice["outstanding"])

    again = client.post(
        f"/api/paypal/payments/{payment['id']}/refund",
        json={"reason": "Duplicate attempt", "confirm": True},
        headers=demo["headers"],
    )
    assert again.status_code == 409

    refunds = client.get("/api/paypal/refunds", headers=demo["headers"]).json()["items"]
    assert len([row for row in refunds if row["payment_id"] == payment["id"]]) == 1

    overview_after = client.get("/api/payments/overview", headers=demo["headers"]).json()
    assert amount(overview_after["statistics"]["refunded_total"]) == amount(
        overview_before["statistics"]["refunded_total"]
    ) + amount(payment["amount"])
    assert amount(overview_after["statistics"]["net_received"]) == amount(
        overview_before["statistics"]["net_received"]
    ) - amount(payment["amount"])


def test_mismatched_webhook_never_marks_invoice_paid(client, demo, paypal_api):
    event = {
        "id": "EVT-MISMATCH-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAPTURE-MISMATCH-1",
            "amount": {"value": "999999.00", "currency_code": "INR"},
            "custom_id": "invoice:1",
        },
    }
    response = _post_webhook(client, event)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert body["outcome"].startswith("mismatch:")
    assert body["verification"] == "paypal_signature_api"
    assert body["payment_id"]

    invoice = client.get("/api/invoices/1", headers=demo["headers"]).json()
    assert invoice["status"] != "paid"
    assert amount(invoice["outstanding"]) == amount(invoice["total"])

    reconciliation = client.get("/api/paypal/reconciliation", headers=demo["headers"]).json()
    assert reconciliation["mismatch_count"] == 1
    assert reconciliation["mismatches"][0]["reconciliation_status"] == "mismatch"

    # The same event delivered twice must not create a second capture.
    duplicate = _post_webhook(client, event)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    payments = client.get("/api/payments", headers=demo["headers"]).json()["items"]
    assert len([p for p in payments if p["provider_ref"] == "CAPTURE-MISMATCH-1"]) == 1


def test_refund_webhook_is_idempotent_and_reverts_invoice(client, demo, paypal_api):
    invoice = _invoice(client, demo["headers"], "INV-1053")
    created = client.post(
        "/api/paypal/orders",
        json={"invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert created.status_code == 200, created.text
    captured = client.post(
        f"/api/paypal/orders/{created.json()['id']}/capture", headers=demo["headers"]
    )
    capture_id = captured.json()["provider_reference"]
    assert captured.json()["invoice"]["status"] == "paid"

    refund_event = {
        "id": "EVT-REFUND-1",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {
            "id": "REFUND-WEBHOOK-1",
            "amount": {"value": captured.json()["payment"]["amount"], "currency_code": "INR"},
            "links": [
                {
                    "rel": "up",
                    "href": f"https://api-m.sandbox.paypal.com/v2/payments/captures/{capture_id}",
                }
            ],
        },
    }
    response = _post_webhook(client, refund_event)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "refund_recorded: cash reduced"
    assert (
        client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()["status"]
        != "paid"
    )

    replay = _post_webhook(client, {**refund_event, "id": "EVT-REFUND-1-REPLAY"})
    assert replay.status_code == 200
    assert replay.json()["outcome"].startswith("duplicate:")

    refunds = client.get("/api/paypal/refunds", headers=demo["headers"]).json()["items"]
    stored = [row for row in refunds if row["provider_refund_id"] == "REFUND-WEBHOOK-1"]
    assert len(stored) == 1


def test_failed_webhook_records_attempt_without_cash_and_releases_invoice(
    client, demo, paypal_api
):
    invoice = _invoice(client, demo["headers"], "INV-1051")
    created = client.post(
        "/api/paypal/orders",
        json={"invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert created.status_code == 200, created.text
    order_id = created.json()["id"]

    failed_event = {
        "id": "EVT-FAILED-1",
        "event_type": "PAYMENT.CAPTURE.DENIED",
        "resource": {
            "id": "CAPTURE-FAILED-1",
            "amount": {"value": created.json()["amount"], "currency_code": "INR"},
            "custom_id": f"invoice:{invoice['id']}",
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }
    response = _post_webhook(client, failed_event)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "failed_recorded: no cash changed"

    payments = client.get("/api/payments", headers=demo["headers"]).json()["items"]
    failed = next(p for p in payments if p["provider_ref"] == "CAPTURE-FAILED-1")
    assert failed["status"] == "failed"

    released = client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()
    assert released["status"] != "pending_payment"
    assert amount(released["paid"]) == 0


def test_paypal_records_are_scoped_to_the_owning_business(client, demo, other, paypal_api):
    event = {
        "id": "EVT-SCOPE-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAPTURE-SCOPE-1",
            "amount": {"value": "1000.00", "currency_code": "INR"},
            "custom_id": "invoice:1",
        },
    }
    assert _post_webhook(client, event).status_code == 200

    demo_events = client.get("/api/paypal/events", headers=demo["headers"]).json()
    assert any(row["event_id"] == "EVT-SCOPE-1" for row in demo_events["items"])

    other_events = client.get("/api/paypal/events", headers=other["headers"]).json()
    assert other_events["items"] == []
    other_overview = client.get("/api/payments/overview", headers=other["headers"]).json()
    assert other_overview["events"] == []

    employee_headers = _employee_headers(client)
    assert client.get("/api/paypal/events", headers=employee_headers).status_code == 403
    assert client.get("/api/payments/overview", headers=employee_headers).status_code == 403

    forbidden = client.put(
        "/api/paypal/settings",
        json={"environment": "sandbox", "enabled": False},
        headers=employee_headers,
    )
    assert forbidden.status_code == 403

    cross_tenant_order = client.post(
        "/api/paypal/orders",
        json={"invoice_id": 1},
        headers=other["headers"],
    )
    assert cross_tenant_order.status_code == 404


def test_overview_filters_and_statistics_shape(client, demo):
    response = client.get(
        "/api/payments/overview?days=7&status=confirmed&currency=INR",
        headers=demo["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["filters"]["status"] == "confirmed"
    assert body["filters"]["currency"] == "INR"
    # The overview window is inclusive of both ends, so "7 days" spans 8 dates.
    assert body["filters"]["days"] == 8
    assert len(body["series"]) == 8
    assert "INR" in body["currencies"]
    assert all(payment["status"] == "confirmed" for payment in body["payments"])
    assert all(payment["currency"] == "INR" for payment in body["payments"])
    for key in (
        "gross_received",
        "verified_received",
        "refunded_total",
        "net_received",
        "pending_total",
        "failed_total",
        "unmatched_confirmed",
        "mismatch_total",
        "successful_count",
        "transaction_count",
    ):
        assert key in body["statistics"]
    assert body["provider"]["webhook_verification"]
