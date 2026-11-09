from __future__ import annotations

import io
from datetime import date, timedelta
from decimal import Decimal

from pypdf import PdfReader

from conftest import amount

from app.database import SessionLocal
from app.models import Invoice, Payment


def _employee_login(client, email="employee@finovexa.ai", password="Employee1234!"):
    response = client.post(
        "/api/auth/employee/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _invoice_payload(*, total=10000, received=None, method="upi", reference=None):
    today = date.today()
    payload = {
        "entry_type": "invoice",
        "counterparty": "Payment Test Traders",
        "description": "Payment received test",
        "items": [{"description": "Consulting", "quantity": 1, "unit_price": total}],
        "tax_rate": 0,
        "entry_date": today.isoformat(),
        "due_date": (today + timedelta(days=15)).isoformat(),
        "payment_method": method,
    }
    if received is not None:
        payload["amount_received"] = received
    if reference:
        payload["payment_reference"] = reference
        payload["payment_date"] = today.isoformat()
    return payload


def _create_invoice(client, headers, **kwargs):
    response = client.post("/api/employee/entries", json=_invoice_payload(**kwargs), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["entry"]


def _pay(client, headers, invoice_id, **payload):
    response = client.post(
        f"/api/employee/invoices/{invoice_id}/payments", json=payload, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_payment_status_and_outstanding_are_calculated_on_backend(client, demo):
    employee = _employee_login(client)

    partial = _create_invoice(client, employee["headers"], total=10000, received=4000)
    assert partial["payment_status_label"] == "PARTIALLY PAID"
    assert amount(partial["invoice_outstanding"]) == Decimal("6000.00")

    paid = _create_invoice(client, employee["headers"], total=10000, received=10000)
    assert paid["payment_status_label"] == "PAID"
    assert amount(paid["invoice_outstanding"]) == Decimal("0.00")

    unpaid = _create_invoice(client, employee["headers"], total=10000)
    assert unpaid["payment_status_label"] == "UNPAID"
    assert amount(unpaid["invoice_outstanding"]) == Decimal("10000.00")

    paise = _create_invoice(client, employee["headers"], total=10000.10, received=4000.05)
    assert amount(paise["invoice_outstanding"]) == Decimal("6000.05")
    final = _pay(client, employee["headers"], paise["invoice_id"], amount=6000.05, method="bank")
    assert final["invoice"]["payment_status_label"] == "PAID"
    assert amount(final["invoice"]["paid"]) == Decimal("10000.10")
    assert amount(final["invoice"]["outstanding"]) == Decimal("0.00")


def test_cheque_payment_mode_is_accepted_and_labelled(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"])

    response = _pay(
        client,
        employee["headers"],
        entry["invoice_id"],
        amount=2500,
        method="cheque",
        reference="CHQ-1001",
    )
    assert response["payment"]["method"] == "cheque"
    assert response["payment"]["method_label"] == "Cheque"

    history = client.get(
        f"/api/employee/invoices/{entry['invoice_id']}/payments", headers=employee["headers"]
    ).json()
    assert history["payment_history"][0]["method_label"] == "Cheque"
    assert amount(history["payment_history"][0]["amount"]) == Decimal("2500.00")


def test_duplicate_reference_and_currency_mismatch_are_rejected(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"])

    _pay(
        client,
        employee["headers"],
        entry["invoice_id"],
        amount=1000,
        method="upi",
        reference="UTR-DUP-1",
    )
    duplicate = client.post(
        f"/api/employee/invoices/{entry['invoice_id']}/payments",
        json={"amount": 2000, "method": "bank", "reference": "utr-dup-1"},
        headers=employee["headers"],
    )
    assert duplicate.status_code == 409, duplicate.text

    mismatch = client.post(
        f"/api/employee/invoices/{entry['invoice_id']}/payments",
        json={"amount": 1000, "method": "cash", "currency": "USD"},
        headers=employee["headers"],
    )
    assert mismatch.status_code == 400, mismatch.text
    assert "does not match" in mismatch.json()["detail"]

    for bad_amount in (0, -50):
        bad = client.post(
            f"/api/employee/invoices/{entry['invoice_id']}/payments",
            json={"amount": bad_amount, "method": "cash"},
            headers=employee["headers"],
        )
        assert bad.status_code == 422, bad.text


def test_employee_cannot_edit_or_reverse_recorded_payments(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"], received=4000)
    payment_id = entry["payment_id"]

    edit = client.patch(
        f"/api/payments/{payment_id}",
        json={"amount": 5000},
        headers=employee["headers"],
    )
    assert edit.status_code == 403, edit.text
    reverse = client.post(
        f"/api/payments/{payment_id}/reverse",
        json={"reason": "employee attempt"},
        headers=employee["headers"],
    )
    assert reverse.status_code == 403, reverse.text

    with SessionLocal() as db:
        payment = db.get(Payment, payment_id)
        assert payment is not None
        assert payment.status == "confirmed"
        assert payment.amount == Decimal("4000.00")


def test_owner_can_edit_and_reverse_with_audit_trail(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"], received=4000, method="upi", reference="UPI-77")
    payment_id = entry["payment_id"]

    edit = client.patch(
        f"/api/payments/{payment_id}",
        json={"amount": 4500, "method": "cheque", "reference": "CHQ-77", "note": "Corrected slip"},
        headers=demo["headers"],
    )
    assert edit.status_code == 200, edit.text
    body = edit.json()
    assert body["payment"]["method"] == "cheque"
    assert amount(body["payment"]["amount"]) == Decimal("4500.00")
    assert amount(body["invoice"]["outstanding"]) == Decimal("5500.00")
    assert body["invoice"]["payment_status_label"] == "PARTIALLY PAID"

    audit = client.get(
        "/api/audit-log?action=payment.edited&limit=20", headers=demo["headers"]
    )
    assert audit.status_code == 200, audit.text
    assert any(item["action"] == "payment.edited" for item in audit.json()["items"])

    reverse = client.post(
        f"/api/payments/{payment_id}/reverse",
        json={"reason": "Customer did not pay"},
        headers=demo["headers"],
    )
    assert reverse.status_code == 200, reverse.text
    reversed_body = reverse.json()
    assert reversed_body["payment"]["status"] == "reversed"
    assert amount(reversed_body["invoice"]["outstanding"]) == Decimal("10000.00")
    assert reversed_body["invoice"]["payment_status_label"] == "UNPAID"

    audit = client.get(
        "/api/audit-log?action=payment.reversed&limit=20", headers=demo["headers"]
    )
    assert any(item["action"] == "payment.reversed" for item in audit.json()["items"])

    history = client.get(
        f"/api/employee/invoices/{entry['invoice_id']}/payments", headers=employee["headers"]
    ).json()
    assert history["payment_count"] == 0
    assert amount(history["amount_received"]) == Decimal("0.00")

    dues = client.get("/api/employee/dues", headers=employee["headers"]).json()
    row = next(item for item in dues["items"] if item["id"] == entry["invoice_id"])
    assert amount(row["outstanding"]) == Decimal("10000.00")
    assert row["payment_status_label"] == "UNPAID"


def test_employee_dashboard_collection_metrics(client, demo):
    employee = _employee_login(client)
    upi = _create_invoice(client, employee["headers"], received=4000, method="upi")
    _create_invoice(client, employee["headers"], received=10000, method="cash")
    _create_invoice(client, employee["headers"])
    _pay(client, employee["headers"], upi["invoice_id"], amount=1000, method="bank")

    dues = client.get("/api/employee/dues", headers=employee["headers"]).json()
    summary = dues["summary"]
    assert amount(summary["collected_today"]) == Decimal("15000.00")
    assert summary["collected_today_count"] == 3
    assert summary["partially_paid_count"] == 1
    assert summary["unpaid_count"] == 1
    assert summary["paid_count"] == 1
    modes = {row["method"]: row for row in summary["collection_by_mode"]}
    assert amount(modes["upi"]["amount"]) == Decimal("4000.00")
    assert amount(modes["cash"]["amount"]) == Decimal("10000.00")
    assert amount(modes["bank"]["amount"]) == Decimal("1000.00")
    assert modes["bank"]["label"] == "Bank transfer"

    overview = client.get("/api/employee/overview", headers=employee["headers"]).json()
    assert amount(overview["collections"]["summary"]["collected_today"]) == Decimal("15000.00")
    assert overview["permissions"]["can_record_payments"] is True
    assert overview["permissions"]["can_edit_payments"] is False
    assert overview["permissions"]["can_reverse_payments"] is False


def test_invoice_pdf_shows_payment_summary(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(
        client, employee["headers"], received=4000, method="cheque", reference="CHQ-PDF-1"
    )

    response = client.get(
        f"/api/billing/invoices/{entry['invoice_id']}/pdf", headers=demo["headers"]
    )
    assert response.status_code == 200, response.text
    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "PAYMENT RECEIVED" in text
    assert "Total invoice amount" in text
    assert "Amount received" in text
    assert "Remaining balance" in text
    assert "PARTIALLY PAID" in text
    assert "Cheque" in text
    assert "CHQ-PDF-1" in text

    with SessionLocal() as db:
        invoice = db.get(Invoice, entry["invoice_id"])
        assert invoice is not None
        assert invoice.status == "partially_paid"
