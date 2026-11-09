from __future__ import annotations

import base64
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AccountingBankImport,
    AccountingDocument,
    Invoice,
    Payment,
    PaymentConnection,
    PaymentSyncRun,
    PaymentTransaction,
)
from app.services.integrations.paypal import paypal_client
from app.services.payment_connect import _fernet

SANDBOX_CLIENT_ID = "payment-connect-client-id-ABCD"
SANDBOX_SECRET = "payment-connect-secret-1234"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakePayPalHistory:
    """In-memory Reporting API stand-in. No network call leaves the process."""

    def __init__(self) -> None:
        self.transactions: list[dict] = []
        self.fail_status: int | None = None
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url))
        if url.endswith("/v1/oauth2/token"):
            return FakeResponse(200, {"access_token": "fake-history-token", "expires_in": 3600})
        raise AssertionError(f"Unexpected PayPal POST: {url}")

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url))
        if not url.endswith("/v1/reporting/transactions"):
            raise AssertionError(f"Unexpected PayPal GET: {url}")
        if self.fail_status is not None:
            return FakeResponse(
                self.fail_status,
                {"message": "denied", "details": [{"issue": "PERMISSION_DENIED"}]},
            )
        params = kwargs.get("params") or {}
        page = int(params.get("page") or 1)
        details = self.transactions if page == 1 else []
        return FakeResponse(
            200,
            {"transaction_details": details, "total_pages": 1, "page": page},
        )


@pytest.fixture()
def paypal_history(monkeypatch):
    fake = FakePayPalHistory()
    monkeypatch.setattr(settings, "PAYPAL_SANDBOX_CLIENT_ID", SANDBOX_CLIENT_ID, raising=False)
    monkeypatch.setattr(settings, "PAYPAL_SANDBOX_CLIENT_SECRET", SANDBOX_SECRET, raising=False)
    import app.services.integrations.paypal as paypal_module

    monkeypatch.setattr(paypal_module.httpx, "post", fake.post)
    monkeypatch.setattr(paypal_module.httpx, "get", fake.get)
    paypal_client._token = None
    paypal_client._token_key = None
    yield fake
    paypal_client._token = None
    paypal_client._token_key = None


def _login(client, path: str, email: str, password: str) -> dict:
    response = client.post(path, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _senior(client) -> dict:
    return _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")


def _junior(client) -> dict:
    return _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")


def _clients(client, headers: dict) -> dict:
    response = client.get("/api/accounting/senior/clients", headers=headers)
    assert response.status_code == 200, response.text
    return {row["business_name"]: row for row in response.json()["items"]}


def _invoice(client, headers: dict, number: str) -> dict:
    response = client.get("/api/invoices?limit=100", headers=headers)
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["number"] == number)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _paypal_item(
    transaction_id: str,
    amount: Decimal,
    *,
    event_code: str = "T0000",
    status: str = "S",
    occurred_on: date,
    invoice_reference: str | None = None,
    payer: str | None = None,
    fee: Decimal = Decimal("0.00"),
    parent: str | None = None,
) -> dict:
    info = {
        "transaction_id": transaction_id,
        "transaction_amount": {
            "value": f"{_money(amount):.2f}",
            "currency_code": "INR",
        },
        "fee_amount": {"value": f"{_money(fee):.2f}", "currency_code": "INR"},
        "transaction_event_code": event_code,
        "transaction_status": status,
        "transaction_initiation_date": f"{occurred_on.isoformat()}T10:00:00Z",
        "transaction_subject": f"Demo transaction {transaction_id}",
    }
    if invoice_reference:
        info["invoice_id"] = invoice_reference
    if parent:
        info["paypal_reference_id"] = parent
    item = {"transaction_info": info}
    if payer:
        item["payer_info"] = {"payer_name": {"alternate_full_name": payer}}
    return item


def _connect_owner_paypal(client, demo, **overrides) -> dict:
    payload = {
        "provider": "paypal",
        "environment": "sandbox",
        "label": "PayPal sandbox",
        "consent": True,
    }
    payload.update(overrides)
    response = client.post("/api/payment-connect/connections", json=payload, headers=demo["headers"])
    assert response.status_code == 201, response.text
    return response.json()


def _sync_owner(client, demo, connection_id: int, *, start: date, end: date) -> dict:
    response = client.post(
        f"/api/payment-connect/connections/{connection_id}/sync",
        json={"start_date": start.isoformat(), "end_date": end.isoformat()},
        headers=demo["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _owner_transactions(client, demo, **params) -> list[dict]:
    response = client.get("/api/payment-connect/transactions", params=params, headers=demo["headers"])
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _connect_client_paypal(client, senior, client_id: int) -> dict:
    response = client.post(
        "/api/accounting/payment-connect/connections",
        json={
            "provider": "paypal",
            "client_id": client_id,
            "environment": "sandbox",
            "label": "Client PayPal",
            "consent": True,
        },
        headers=senior["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _sync_client(client, senior, client_id: int, connection_id: int, *, start: date, end: date) -> dict:
    response = client.post(
        f"/api/accounting/payment-connect/connections/{connection_id}/sync",
        json={"client_id": client_id, "start_date": start.isoformat(), "end_date": end.isoformat()},
        headers=senior["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _client_transactions(client, senior, client_id: int, **params) -> list[dict]:
    response = client.get(
        "/api/accounting/payment-connect/transactions",
        params={"client_id": client_id, **params},
        headers=senior["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _data_url(raw: bytes, suffix: str = "csv") -> str:
    return f"data:text/csv;base64,{base64.b64encode(raw).decode('ascii')}"


def _csv_bytes(rows: list[str]) -> bytes:
    header = "Date,Description,Reference,Debit,Credit\n"
    return (header + "\n".join(rows) + "\n").encode("utf-8")


def _pdf_bytes(lines: list[str], *, blank: bool = False) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    if not blank:
        pdf.setFont("Helvetica", 10)
        y = 780
        for line in lines:
            pdf.drawString(40, y, line)
            y -= 16
    pdf.save()
    return buffer.getvalue()


def test_paypal_connection_requires_consent_and_server_credentials(client, demo):
    no_consent = client.post(
        "/api/payment-connect/connections",
        json={"provider": "paypal", "environment": "sandbox"},
        headers=demo["headers"],
    )
    assert no_consent.status_code == 422
    assert "consent" in no_consent.json()["detail"].lower()

    missing_credentials = client.post(
        "/api/payment-connect/connections",
        json={"provider": "paypal", "environment": "sandbox", "consent": True},
        headers=demo["headers"],
    )
    assert missing_credentials.status_code == 409
    assert "credentials" in missing_credentials.json()["detail"].lower()


def test_paypal_sync_imports_history_once_with_duplicate_protection(
    client, demo, paypal_history
):
    invoice = _invoice(client, demo["headers"], "INV-1057")
    amount = _money(invoice["outstanding"])
    occurred = date.fromisoformat(invoice["issue_date"])
    paypal_history.transactions = [
        _paypal_item(
            "PAYPAL-SYNC-1001",
            amount,
            occurred_on=occurred,
            invoice_reference=invoice["number"],
            payer="Delta Build Co.",
            fee=Decimal("12.00"),
        )
    ]
    connection = _connect_owner_paypal(client, demo)
    assert connection["status"] == "connected"
    assert connection["provider"] == "paypal"

    start, end = occurred - timedelta(days=5), occurred + timedelta(days=1)
    first = _sync_owner(client, demo, connection["id"], start=start, end=end)
    assert first["status"] == "success"
    assert first["fetched"] == 1
    assert first["created"] == 1
    assert first["duplicates"] == 0

    second = _sync_owner(client, demo, connection["id"], start=start, end=end)
    assert second["created"] == 0
    assert second["duplicates"] == 1

    rows = _owner_transactions(client, demo, provider="paypal")
    assert len(rows) == 1
    row = rows[0]
    assert row["external_id"] == "PAYPAL-SYNC-1001"
    assert row["direction"] == "incoming"
    assert _money(row["amount"]) == amount
    assert _money(row["fee_amount"]) == Decimal("12.00")
    assert _money(row["net_amount"]) == amount - Decimal("12.00")
    assert row["occurred_on"] == invoice["issue_date"]

    overview = client.get("/api/payment-connect/overview", headers=demo["headers"]).json()
    assert overview["summary"]["transactions"] == 1
    assert overview["summary"]["duplicates"] == 0
    assert summary_for(overview["summary"]["by_provider"], "paypal")["count"] == 1
    assert {row["id"] for row in overview["recent_syncs"]} == {first["id"], second["id"]}
    assert overview["last_successful_sync"] is not None

    runs = client.get(
        f"/api/payment-connect/connections/{connection['id']}/runs",
        headers=demo["headers"],
    )
    assert runs.status_code == 200
    assert len(runs.json()["items"]) == 2


def summary_for(rows: list[dict], provider: str) -> dict:
    return next(row for row in rows if row["provider"] == provider)


def test_paypal_pending_and_failed_transactions_cannot_be_approved(client, demo, paypal_history):
    occurred = date.today() - timedelta(days=2)
    paypal_history.transactions = [
        _paypal_item("PAYPAL-PENDING-1", Decimal("500.00"), status="P", occurred_on=occurred),
        _paypal_item("PAYPAL-FAILED-1", Decimal("700.00"), status="D", occurred_on=occurred),
    ]
    connection = _connect_owner_paypal(client, demo)
    run = _sync_owner(
        client, demo, connection["id"], start=occurred, end=date.today()
    )
    assert run["created"] == 2

    rows = _owner_transactions(client, demo, provider="paypal")
    by_external = {row["external_id"]: row for row in rows}
    assert by_external["PAYPAL-PENDING-1"]["status"] == "pending"
    assert by_external["PAYPAL-FAILED-1"]["status"] == "failed"
    assert by_external["PAYPAL-PENDING-1"]["reconciliation_status"] == "unverified"

    for external in ("PAYPAL-PENDING-1", "PAYPAL-FAILED-1"):
        response = client.post(
            f"/api/payment-connect/transactions/{by_external[external]['id']}/reconcile",
            json={"action": "approve"},
            headers=demo["headers"],
        )
        assert response.status_code == 409
        assert "completed" in response.json()["detail"].lower()


def test_paypal_refund_creates_negative_payment_and_restores_invoice(client, demo, paypal_history):
    invoice = _invoice(client, demo["headers"], "INV-1057")
    amount = _money(invoice["outstanding"])
    occurred = date.fromisoformat(invoice["issue_date"])
    paypal_history.transactions = [
        _paypal_item(
            "PAYPAL-PARENT-2001",
            amount,
            occurred_on=occurred,
            invoice_reference=invoice["number"],
            payer="Delta Build Co.",
        ),
        _paypal_item(
            "PAYPAL-REFUND-2002",
            amount,
            event_code="T1107",
            occurred_on=occurred + timedelta(days=1),
            parent="PAYPAL-PARENT-2001",
        ),
    ]
    connection = _connect_owner_paypal(client, demo)
    _sync_owner(
        client,
        demo,
        connection["id"],
        start=occurred - timedelta(days=1),
        end=occurred + timedelta(days=3),
    )
    rows = {row["external_id"]: row for row in _owner_transactions(client, demo)}
    parent, refund = rows["PAYPAL-PARENT-2001"], rows["PAYPAL-REFUND-2002"]
    assert refund["txn_type"] == "refund"
    assert refund["direction"] == "outgoing"

    approved = client.post(
        f"/api/payment-connect/transactions/{parent['id']}/reconcile",
        json={"action": "approve", "invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["transaction"]["reconciliation_status"] == "matched"

    refunded = client.post(
        f"/api/payment-connect/transactions/{refund['id']}/reconcile",
        json={"action": "approve", "invoice_id": invoice["id"]},
        headers=demo["headers"],
    )
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["transaction"]["reconciliation_status"] == "matched"

    db = SessionLocal()
    try:
        refund_payment = (
            db.query(Payment).filter(Payment.provider_ref == "PAYPAL-REFUND-2002").one()
        )
        assert refund_payment.amount == -amount
        assert refund_payment.refund_of_payment_id is not None
        stored_invoice = db.get(Invoice, invoice["id"])
        assert stored_invoice.outstanding_amount == amount
    finally:
        db.close()


def test_accountant_approval_matches_invoice_and_creates_accounting_draft(
    client, demo, paypal_history
):
    senior = _senior(client)
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    invoice = _invoice(client, demo["headers"], "INV-1057")
    amount = _money(invoice["outstanding"])
    occurred = date.fromisoformat(invoice["issue_date"])
    paypal_history.transactions = [
        _paypal_item(
            "PAYPAL-CLIENT-3001",
            amount,
            occurred_on=occurred,
            invoice_reference=invoice["number"],
            payer="Delta Build Co.",
        )
    ]
    connection = _connect_client_paypal(client, senior, dn["id"])
    assert connection["provider"] == "paypal"
    assert connection["status"] == "connected"

    run = _sync_client(
        client,
        senior,
        dn["id"],
        connection["id"],
        start=occurred - timedelta(days=2),
        end=occurred + timedelta(days=2),
    )
    assert run["created"] == 1

    rows = _client_transactions(client, senior, dn["id"], provider="paypal")
    assert len(rows) == 1
    txn = rows[0]
    assert txn["reconciliation_status"] == "suggested"
    assert txn["matched_invoice_id"] == invoice["id"]
    assert txn["match_score"] >= 60

    candidates = client.get(
        f"/api/accounting/payment-connect/transactions/{txn['id']}/candidates",
        params={"client_id": dn["id"]},
        headers=senior["headers"],
    )
    assert candidates.status_code == 200
    assert candidates.json()["items"][0]["invoice_id"] == invoice["id"]

    approved = client.post(
        f"/api/accounting/payment-connect/transactions/{txn['id']}/reconcile",
        json={"client_id": dn["id"], "action": "approve", "invoice_id": invoice["id"]},
        headers=senior["headers"],
    )
    assert approved.status_code == 200, approved.text
    result = approved.json()["transaction"]
    assert result["reconciliation_status"] == "matched"
    assert result["matched_payment_id"] is not None
    assert result["accounting_draft_id"] is not None

    events = client.get(
        f"/api/accounting/payment-connect/transactions/{txn['id']}/events",
        params={"client_id": dn["id"]},
        headers=senior["headers"],
    )
    assert events.status_code == 200
    assert events.json()["items"][0]["action"] == "approved"

    updated = _invoice(client, demo["headers"], "INV-1057")
    assert _money(updated["outstanding"]) == Decimal("0.00")


def test_partial_payment_is_only_a_suggestion_and_is_approved_explicitly(
    client, demo, paypal_history
):
    senior = _senior(client)
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    invoice = _invoice(client, demo["headers"], "INV-1056")
    outstanding = _money(invoice["outstanding"])
    partial = (outstanding / 2).quantize(Decimal("0.01"))
    occurred = date.fromisoformat(invoice["issue_date"])
    paypal_history.transactions = [
        _paypal_item(
            "PAYPAL-PARTIAL-4001",
            partial,
            occurred_on=occurred,
            payer="Delta Build Co.",
        )
    ]
    connection = _connect_client_paypal(client, senior, dn["id"])
    _sync_client(
        client,
        senior,
        dn["id"],
        connection["id"],
        start=occurred - timedelta(days=1),
        end=occurred + timedelta(days=1),
    )
    txn = _client_transactions(client, senior, dn["id"], provider="paypal")[0]
    assert txn["reconciliation_status"] == "unverified"
    assert txn["match_score"] < 60
    assert "partial" in (txn["match_reason"] or "").lower()

    approved = client.post(
        f"/api/accounting/payment-connect/transactions/{txn['id']}/reconcile",
        json={"client_id": dn["id"], "action": "approve", "invoice_id": invoice["id"]},
        headers=senior["headers"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["transaction"]["reconciliation_status"] == "matched"

    updated = _invoice(client, demo["headers"], "INV-1056")
    assert _money(updated["outstanding"]) == outstanding - partial


def test_cross_business_and_scope_are_blocked(client, demo, other, paypal_history):
    invoice = _invoice(client, demo["headers"], "INV-1057")
    amount = _money(invoice["outstanding"])
    occurred = date.fromisoformat(invoice["issue_date"])
    paypal_history.transactions = [
        _paypal_item(
            "PAYPAL-ISOLATION-5001",
            amount,
            occurred_on=occurred,
            invoice_reference=invoice["number"],
        )
    ]
    connection = _connect_owner_paypal(client, demo)
    _sync_owner(
        client,
        demo,
        connection["id"],
        start=occurred - timedelta(days=1),
        end=occurred + timedelta(days=1),
    )
    txn = _owner_transactions(client, demo, provider="paypal")[0]

    other_rows = client.get(
        "/api/payment-connect/transactions", headers=other["headers"]
    )
    assert other_rows.status_code == 200
    assert other_rows.json()["items"] == []

    denied = client.post(
        f"/api/payment-connect/transactions/{txn['id']}/reconcile",
        json={"action": "approve", "invoice_id": invoice["id"]},
        headers=other["headers"],
    )
    assert denied.status_code == 404

    # A second business must not inherit the deployment's single PayPal credential set.
    second_connection = client.post(
        "/api/payment-connect/connections",
        json={"provider": "paypal", "environment": "sandbox", "consent": True},
        headers=other["headers"],
    )
    assert second_connection.status_code == 409
    assert "another business" in second_connection.json()["detail"].lower()

    senior = _senior(client)
    clients = _clients(client, senior["headers"])
    dn = clients["DN Ventures Pvt. Ltd"]
    sunrise = clients["Sunrise Interiors"]

    junior = _junior(client)
    unattached = client.get(
        "/api/accounting/payment-connect/overview",
        params={"client_id": sunrise["id"]},
        headers=junior["headers"],
    )
    assert unattached.status_code == 403

    junior_sync = client.post(
        f"/api/accounting/payment-connect/connections/{connection['id']}/sync",
        json={"client_id": dn["id"], "start_date": occurred.isoformat(), "end_date": occurred.isoformat()},
        headers=junior["headers"],
    )
    assert junior_sync.status_code == 403

    tracked = client.post(
        "/api/accounting/payment-connect/google-pay/track",
        json={
            "client_id": dn["id"],
            "merchant_id": "GPAY-MERCHANT-5200",
            "google_transaction_id": "GPAY-TXN-5200",
            "amount": "999.00",
            "occurred_on": date.today().isoformat(),
            "status": "completed",
        },
        headers=senior["headers"],
    )
    assert tracked.status_code == 201, tracked.text
    junior_approve = client.post(
        f"/api/accounting/payment-connect/transactions/{tracked.json()['id']}/reconcile",
        json={"client_id": dn["id"], "action": "approve", "invoice_id": invoice["id"]},
        headers=junior["headers"],
    )
    assert junior_approve.status_code == 403

    junior_connect = client.post(
        "/api/accounting/payment-connect/connections",
        json={"provider": "google_pay", "client_id": dn["id"], "merchant_id": "X-1", "consent": True},
        headers=junior["headers"],
    )
    assert junior_connect.status_code == 403

    no_profile = client.post(
        "/api/accounting/payment-connect/connections",
        json={
            "provider": "google_pay",
            "client_id": sunrise["id"],
            "merchant_id": "MERCHANT-123",
            "consent": True,
        },
        headers=senior["headers"],
    )
    assert no_profile.status_code == 409
    assert "business profile" in no_profile.json()["detail"].lower()

    wrong_client = client.get(
        f"/api/accounting/payment-connect/transactions/{txn['id']}/events",
        params={"client_id": sunrise["id"]},
        headers=senior["headers"],
    )
    assert wrong_client.status_code == 409


def test_paypal_sync_failure_is_recorded_without_duplicates(client, demo, paypal_history):
    occurred = date.today() - timedelta(days=1)
    connection = _connect_owner_paypal(client, demo)
    paypal_history.transactions = [
        _paypal_item("PAYPAL-OK-6001", Decimal("100.00"), occurred_on=occurred)
    ]
    _sync_owner(client, demo, connection["id"], start=occurred, end=date.today())

    paypal_history.fail_status = 403
    response = client.post(
        f"/api/payment-connect/connections/{connection['id']}/sync",
        json={"start_date": occurred.isoformat(), "end_date": date.today().isoformat()},
        headers=demo["headers"],
    )
    assert response.status_code == 502
    assert "partner-network approval" in response.json()["detail"]

    db = SessionLocal()
    try:
        stored = db.get(PaymentConnection, connection["id"])
        assert stored.status == "error"
        assert stored.last_error is not None
        last_run = (
            db.query(PaymentSyncRun)
            .filter(PaymentSyncRun.connection_id == connection["id"])
            .order_by(PaymentSyncRun.id.desc())
            .first()
        )
        assert last_run.status == "failed"
        assert db.query(PaymentTransaction).count() == 1
    finally:
        db.close()


def test_google_pay_is_eligibility_only_and_manual_tracking_is_unverified(client, demo):
    eligibility = client.get("/api/payment-connect/google-pay/eligibility", headers=demo["headers"])
    assert eligibility.status_code == 200
    body = eligibility.json()
    assert body["history_api"] is False
    assert body["tracking_supported"] is True
    assert "does not expose a public API" in body["summary"]

    lookup = client.post("/api/payment-connect/google-pay/lookup", headers=demo["headers"])
    assert lookup.status_code == 409
    assert "not configured" in lookup.json()["detail"].lower()

    payload = {
        "merchant_id": "GPAY-MERCHANT-9001",
        "google_transaction_id": "GPAY-TXN-9001",
        "amount": "1500.00",
        "currency": "INR",
        "occurred_on": date.today().isoformat(),
        "status": "completed",
        "description": "Counter sale",
        "upi_reference": "UPI-REF-9001",
    }
    tracked = client.post(
        "/api/payment-connect/google-pay/track", json=payload, headers=demo["headers"]
    )
    assert tracked.status_code == 201, tracked.text
    txn = tracked.json()
    assert txn["provider"] == "google_pay"
    assert txn["source"] == "manual"
    assert txn["reconciliation_status"] == "unverified"
    assert "not verified" in (txn["note"] or "").lower()

    repeated = client.post(
        "/api/payment-connect/google-pay/track", json=payload, headers=demo["headers"]
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == txn["id"]

    db = SessionLocal()
    try:
        stored = db.get(PaymentTransaction, txn["id"])
        assert stored.raw["verification"] == "manual_entry_not_provider_verified"
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.provider == "google_pay"
        ).count() == 1
    finally:
        db.close()


def test_bank_statement_csv_preview_import_and_duplicate_upload(client, demo):
    senior = _senior(client)
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    first_csv = _csv_bytes(
        [
            "01/10/2026,NEFT RECEIVED FROM DELTA BUILD,UTR-778801,0,25000.00",
            "03/10/2026,VENDOR PAYMENT,CHQ-445522,4500.00,0",
        ]
    )
    preview = client.post(
        "/api/accounting/payment-connect/bank-statements/preview",
        json={
            "client_id": dn["id"],
            "filename": "october.csv",
            "data_url": _data_url(first_csv),
            "account_label": "HDFC Current",
        },
        headers=senior["headers"],
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["summary"]["rows"] == 2
    assert preview_body["summary"]["valid"] == 2
    assert preview_body["summary"]["duplicates"] == 0
    assert preview_body["summary"]["uncertain"] == 0
    assert len(preview_body["rows"]) == 2

    imported = client.post(
        "/api/accounting/payment-connect/bank-statements/import",
        json={
            "client_id": dn["id"],
            "filename": "october.csv",
            "data_url": _data_url(first_csv),
            "account_label": "HDFC Current",
        },
        headers=senior["headers"],
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["rows"] == 2
    assert body["duplicates_skipped"] == 0
    assert body["encrypted_original"] is True

    db = SessionLocal()
    try:
        document = db.get(AccountingDocument, body["document_id"])
        assert document.stored_name.endswith(".fernet")
        record = db.get(AccountingBankImport, body["import_id"])
        assert record.row_count == 2
        assert record.source_sha256 is not None
        with open(f"{settings.ACCOUNTING_UPLOAD_DIR}/{document.stored_name}", "rb") as handle:
            stored_bytes = handle.read()
        assert first_csv not in stored_bytes
        assert _fernet().decrypt(stored_bytes) == first_csv
        connection = db.get(PaymentConnection, record.connection_id)
        assert connection.provider == "bank_statement"
    finally:
        db.close()

    repeated = client.post(
        "/api/accounting/payment-connect/bank-statements/import",
        json={
            "client_id": dn["id"],
            "filename": "october.csv",
            "data_url": _data_url(first_csv),
        },
        headers=senior["headers"],
    )
    assert repeated.status_code == 409
    assert "already imported" in repeated.json()["detail"].lower()

    second_csv = _csv_bytes(
        [
            "01/10/2026,NEFT RECEIVED FROM DELTA BUILD,UTR-778801,0,25000.00",
            "03/10/2026,VENDOR PAYMENT,CHQ-445522,4500.00,0",
            "05/10/2026,BANK CHARGES,CHG-991,250.00,0",
        ]
    )
    partial_duplicate = client.post(
        "/api/accounting/payment-connect/bank-statements/import",
        json={
            "client_id": dn["id"],
            "filename": "october-revised.csv",
            "data_url": _data_url(second_csv),
        },
        headers=senior["headers"],
    )
    assert partial_duplicate.status_code == 201, partial_duplicate.text
    assert partial_duplicate.json()["rows"] == 1
    assert partial_duplicate.json()["duplicates_skipped"] == 2

    rows = _client_transactions(client, senior, dn["id"], provider="bank_statement")
    assert len(rows) == 3
    incoming = [row for row in rows if row["direction"] == "incoming"]
    assert len(incoming) == 1
    assert _money(incoming[0]["amount"]) == Decimal("25000.00")
    assert incoming[0]["source"] == "statement"

    imports = client.get(
        "/api/accounting/payment-connect/bank-statements",
        params={"client_id": dn["id"]},
        headers=senior["headers"],
    )
    assert imports.status_code == 200
    assert len(imports.json()["items"]) == 2

    owner_bank = client.post(
        "/api/payment-connect/connections",
        json={"provider": "bank_statement", "consent": True},
        headers=demo["headers"],
    )
    assert owner_bank.status_code == 422


def test_pdf_statement_rows_are_marked_uncertain_and_scans_are_rejected(client, demo):
    senior = _senior(client)
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    pdf = _pdf_bytes(
        [
            "BANK STATEMENT - OCTOBER",
            "01/10/2026 NEFT RECEIVED FROM DELTA 4500.00 Cr",
            "02/10/2026 CHEQUE PAID TO VENDOR 1250.00 Dr",
        ]
    )
    preview = client.post(
        "/api/accounting/payment-connect/bank-statements/preview",
        json={
            "client_id": dn["id"],
            "filename": "october.pdf",
            "data_url": f"data:application/pdf;base64,{base64.b64encode(pdf).decode('ascii')}",
        },
        headers=senior["headers"],
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["summary"]["rows"] == 2
    assert body["summary"]["uncertain"] == 2
    for row in body["rows"]:
        assert row["confidence"] < 100
        assert any("pdf" in issue.lower() for issue in row["issues"])

    imported = client.post(
        "/api/accounting/payment-connect/bank-statements/import",
        json={
            "client_id": dn["id"],
            "filename": "october.pdf",
            "data_url": f"data:application/pdf;base64,{base64.b64encode(pdf).decode('ascii')}",
        },
        headers=senior["headers"],
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["rows"] == 2
    assert imported.json()["uncertain"] == 2

    scanned = _pdf_bytes([], blank=True)
    scan_preview = client.post(
        "/api/accounting/payment-connect/bank-statements/preview",
        json={
            "client_id": dn["id"],
            "filename": "scan.pdf",
            "data_url": f"data:application/pdf;base64,{base64.b64encode(scanned).decode('ascii')}",
        },
        headers=senior["headers"],
    )
    assert scan_preview.status_code == 200
    scan_body = scan_preview.json()
    assert scan_body["summary"]["rows"] == 0
    assert any("ocr is not used" in warning.lower() for warning in scan_body["warnings"])


def test_reconciliation_rejects_unknown_invoice_and_owner_scope(client, demo, paypal_history):
    invoice = _invoice(client, demo["headers"], "INV-1057")
    amount = _money(invoice["outstanding"])
    occurred = date.fromisoformat(invoice["issue_date"])
    paypal_history.transactions = [
        _paypal_item("PAYPAL-SCOPE-7001", amount, occurred_on=occurred)
    ]
    connection = _connect_owner_paypal(client, demo)
    _sync_owner(
        client, demo, connection["id"], start=occurred, end=occurred + timedelta(days=1)
    )
    txn = _owner_transactions(client, demo, provider="paypal")[0]

    wrong_invoice = client.post(
        f"/api/payment-connect/transactions/{txn['id']}/reconcile",
        json={"action": "approve", "invoice_id": 999_999},
        headers=demo["headers"],
    )
    assert wrong_invoice.status_code == 422

    client_scope = client.post(
        f"/api/payment-connect/transactions/{txn['id']}/reconcile",
        json={"action": "reject", "client_id": 123, "note": "Not ours"},
        headers=demo["headers"],
    )
    assert client_scope.status_code == 422

    rejected = client.post(
        f"/api/payment-connect/transactions/{txn['id']}/reconcile",
        json={"action": "reject", "note": "Not ours"},
        headers=demo["headers"],
    )
    assert rejected.status_code == 200
    assert rejected.json()["transaction"]["reconciliation_status"] == "rejected"

    reset = client.post(
        f"/api/payment-connect/transactions/{txn['id']}/reconcile",
        json={"action": "reset"},
        headers=demo["headers"],
    )
    assert reset.status_code == 200
    assert reset.json()["transaction"]["reconciliation_status"] in (
        "suggested",
        "unverified",
    )
    assert reset.json()["transaction"]["matched_payment_id"] is None


def test_google_pay_eligibility_is_honest_for_accountants(client, demo):
    senior = _senior(client)
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    eligibility = client.get(
        "/api/accounting/payment-connect/google-pay/eligibility",
        params={"client_id": dn["id"]},
        headers=senior["headers"],
    )
    assert eligibility.status_code == 200
    assert eligibility.json()["history_api"] is False

    lookup = client.post(
        "/api/accounting/payment-connect/google-pay/lookup",
        params={"client_id": dn["id"]},
        headers=senior["headers"],
    )
    assert lookup.status_code == 409

    tracked = client.post(
        "/api/accounting/payment-connect/google-pay/track",
        json={
            "client_id": dn["id"],
            "merchant_id": "GPAY-MERCHANT-9100",
            "google_transaction_id": "GPAY-TXN-9100",
            "amount": "825.50",
            "occurred_on": date.today().isoformat(),
            "status": "unknown",
        },
        headers=senior["headers"],
    )
    assert tracked.status_code == 201, tracked.text
    assert tracked.json()["client_id"] == dn["id"]
    assert tracked.json()["reconciliation_status"] == "unverified"
