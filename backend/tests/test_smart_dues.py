from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from conftest import amount

from app.database import SessionLocal
from app.models import Invoice, Payment, ReconciliationRecord


def _employee_login(client, email="employee@finovexa.ai", password="Employee1234!"):
    response = client.post(
        "/api/auth/employee/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _invoice_payload(*, due_offset=10, received=None, method="upi", total=30000):
    today = date.today()
    payload = {
        "entry_type": "invoice",
        "counterparty": "ABC Traders",
        "counterparty_email": "accounts@abctraders.example",
        "description": "Consulting retainer",
        "items": [
            {"description": "Consulting retainer", "quantity": 1, "unit_price": total}
        ],
        "tax_rate": 0,
        "entry_date": (today - timedelta(days=5)).isoformat(),
        "due_date": (today + timedelta(days=due_offset)).isoformat(),
        "payment_method": method,
        "notes": "Stage 3 dues test",
    }
    if received is not None:
        payload["amount_received"] = received
    return payload


def _create_invoice(client, headers, **kwargs):
    response = client.post(
        "/api/employee/entries", json=_invoice_payload(**kwargs), headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["entry"]


def _dues(client, headers, **params):
    response = client.get("/api/employee/dues", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_employee_invoice_records_partial_payment_and_remaining_dues(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"], received=10000)

    assert amount(entry["invoice_total"]) == Decimal("30000.00")
    assert amount(entry["amount_received"]) == Decimal("10000.00")
    assert amount(entry["invoice_paid"]) == Decimal("10000.00")
    assert amount(entry["invoice_outstanding"]) == Decimal("20000.00")
    assert entry["payment_id"] is not None
    assert entry["payment_state"] == "partially_paid"

    history = client.get(
        f"/api/employee/invoices/{entry['invoice_id']}/payments",
        headers=employee["headers"],
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["payment_count"] == 1
    assert amount(body["payment_history"][0]["amount"]) == Decimal("10000.00")
    assert body["payment_history"][0]["method"] == "upi"

    dues = _dues(client, employee["headers"])
    row = next(item for item in dues["items"] if item["id"] == entry["invoice_id"])
    assert amount(row["outstanding"]) == Decimal("20000.00")
    assert row["collection_status"] in {"partially_paid", "due_soon"}
    assert amount(dues["summary"]["outstanding_total"]) >= Decimal("20000.00")


def test_multiple_instalments_update_outstanding_without_overwriting(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"], received=5000)
    invoice_id = entry["invoice_id"]

    first = client.post(
        f"/api/employee/invoices/{invoice_id}/payments",
        json={"amount": 7000, "method": "bank", "reference": "UTR-1"},
        headers=employee["headers"],
    )
    assert first.status_code == 201, first.text
    assert amount(first.json()["invoice"]["outstanding"]) == Decimal("18000.00")

    second = client.post(
        f"/api/employee/invoices/{invoice_id}/payments",
        json={"amount": 8000, "method": "cash", "reference": "CASH-2"},
        headers=employee["headers"],
    )
    assert second.status_code == 201, second.text
    assert amount(second.json()["invoice"]["outstanding"]) == Decimal("10000.00")

    history = client.get(
        f"/api/employee/invoices/{invoice_id}/payments", headers=employee["headers"]
    ).json()
    assert history["payment_count"] == 3
    assert [amount(p["amount"]) for p in history["payment_history"]] == [
        Decimal("5000.00"),
        Decimal("7000.00"),
        Decimal("8000.00"),
    ]
    assert amount(history["amount_received"]) == Decimal("20000.00")

    final = client.post(
        f"/api/employee/invoices/{invoice_id}/payments",
        json={"amount": 10000, "method": "upi"},
        headers=employee["headers"],
    )
    assert final.status_code == 201, final.text
    assert final.json()["invoice"]["collection_status"] == "paid"
    assert amount(final.json()["invoice"]["outstanding"]) == Decimal("0.00")

    again = client.post(
        f"/api/employee/invoices/{invoice_id}/payments",
        json={"amount": 1, "method": "upi"},
        headers=employee["headers"],
    )
    assert again.status_code == 409, again.text


def test_overpayment_is_recorded_as_flagged_customer_credit(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"], received=1000)

    response = client.post(
        f"/api/employee/invoices/{entry['invoice_id']}/payments",
        json={"amount": 50000, "method": "bank"},
        headers=employee["headers"],
    )
    assert response.status_code == 201, response.text
    invoice = response.json()["invoice"]
    assert invoice["payment_status_label"] == "OVERPAID"
    assert amount(invoice["overpaid_amount"]) == Decimal("21000.00")
    assert amount(invoice["outstanding"]) == Decimal("0.00")

    with SessionLocal() as db:
        row = db.get(Invoice, entry["invoice_id"])
        assert row is not None
        assert row.status == "paid"
        review = (
            db.query(ReconciliationRecord)
            .filter(
                ReconciliationRecord.invoice_id == row.id,
                ReconciliationRecord.status == "overpayment_review",
            )
            .one()
        )
        assert review.amount_delta == Decimal("21000.00")
        assert "customer credit" in (review.reason or "")

    again = client.post(
        f"/api/employee/invoices/{entry['invoice_id']}/payments",
        json={"amount": 10, "method": "cash"},
        headers=employee["headers"],
    )
    assert again.status_code == 409, again.text


def test_invoice_creation_records_overpayment_for_review(client, demo):
    employee = _employee_login(client)
    response = client.post(
        "/api/employee/entries",
        json=_invoice_payload(received=99999),
        headers=employee["headers"],
    )
    assert response.status_code == 201, response.text
    entry = response.json()["entry"]
    assert entry["payment_state"] == "overpaid"
    assert entry["payment_status_label"] == "OVERPAID"
    assert amount(entry["invoice_paid"]) == Decimal("99999.00")
    assert amount(entry["overpaid_amount"]) == Decimal("69999.00")
    assert amount(entry["invoice_outstanding"]) == Decimal("0.00")

    dues = _dues(client, employee["headers"])
    assert dues["summary"]["overpaid_count"] == 1
    assert amount(dues["summary"]["overpaid_total"]) == Decimal("69999.00")


def test_duplicate_idempotency_key_records_one_payment(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"])
    payload = {
        "amount": 4000,
        "method": "upi",
        "idempotency_key": "stage3-retry-001",
    }
    first = client.post(
        f"/api/employee/invoices/{entry['invoice_id']}/payments",
        json=payload,
        headers=employee["headers"],
    )
    assert first.status_code == 201, first.text
    retry = client.post(
        f"/api/employee/invoices/{entry['invoice_id']}/payments",
        json=payload,
        headers=employee["headers"],
    )
    assert retry.status_code == 201, retry.text

    with SessionLocal() as db:
        count = db.query(Payment).filter(Payment.invoice_id == entry["invoice_id"]).count()
        assert count == 1


def test_employee_cannot_collect_an_unassigned_owner_invoice(client, demo):
    employee = _employee_login(client)
    listing = client.get("/api/invoices?limit=100", headers=demo["headers"])
    assert listing.status_code == 200, listing.text
    owner_invoice = next(
        item for item in listing.json()["items"] if item["status"] not in {"paid", "void"}
    )
    denied = client.post(
        f"/api/employee/invoices/{owner_invoice['id']}/payments",
        json={"amount": 100, "method": "cash"},
        headers=employee["headers"],
    )
    assert denied.status_code == 404, denied.text
    history = client.get(
        f"/api/employee/invoices/{owner_invoice['id']}/payments",
        headers=employee["headers"],
    )
    assert history.status_code == 404


def test_assigned_owner_invoice_becomes_collectible(client, demo):
    employee = _employee_login(client)
    listing = client.get("/api/invoices?limit=100", headers=demo["headers"])
    owner_invoice = next(
        item for item in listing.json()["items"] if item["status"] not in {"paid", "void"}
    )
    with SessionLocal() as db:
        invoice = db.get(Invoice, owner_invoice["id"])
        invoice.assigned_employee_id = employee["user"]["id"]
        db.commit()

    dues = _dues(client, employee["headers"])
    assert any(item["id"] == owner_invoice["id"] for item in dues["items"])
    history = client.get(
        f"/api/employee/invoices/{owner_invoice['id']}/payments",
        headers=employee["headers"],
    )
    assert history.status_code == 200, history.text


def test_due_soon_and_overdue_filters(client, demo):
    employee = _employee_login(client)
    soon = _create_invoice(client, employee["headers"], due_offset=3)
    overdue = _create_invoice(client, employee["headers"], due_offset=-2)

    soon_dues = _dues(client, employee["headers"], status="due_soon")
    assert any(item["id"] == soon["invoice_id"] for item in soon_dues["items"])
    soon_row = next(item for item in soon_dues["items"] if item["id"] == soon["invoice_id"])
    assert soon_row["collection_status"] == "due_soon"

    overdue_dues = _dues(client, employee["headers"], status="overdue")
    assert any(item["id"] == overdue["invoice_id"] for item in overdue_dues["items"])
    assert all(item["collection_status"] == "overdue" for item in overdue_dues["items"])
    assert overdue_dues["summary"]["overdue_count"] >= 1
    assert amount(overdue_dues["summary"]["overdue_total"]) >= Decimal("30000.00")


def test_disputed_invoice_is_flagged_and_filtered(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"], due_offset=-2)
    with SessionLocal() as db:
        invoice = db.get(Invoice, entry["invoice_id"])
        invoice.disputed_at = invoice.created_at
        db.commit()

    dues = _dues(client, employee["headers"], status="disputed")
    assert [item["id"] for item in dues["items"]] == [entry["invoice_id"]]
    assert dues["items"][0]["collection_status"] == "disputed"
    assert dues["summary"]["disputed_count"] == 1


def test_employee_payment_reaches_owner_ledger(client, demo):
    employee = _employee_login(client)
    entry = _create_invoice(client, employee["headers"], received=12000)

    payments = client.get("/api/payments?status=confirmed", headers=demo["headers"])
    assert payments.status_code == 200, payments.text
    row = next(item for item in payments.json()["items"] if item["invoice_id"] == entry["invoice_id"])
    assert amount(row["amount"]) == Decimal("12000.00")
    assert row["created_by_user_id"] == employee["user"]["id"]

    audit = client.get(
        "/api/audit-log?action=employee.entry_recorded&limit=50",
        headers=demo["headers"],
    )
    assert audit.status_code == 200, audit.text
    assert any(item["action"] == "employee.entry_recorded" for item in audit.json()["items"])
