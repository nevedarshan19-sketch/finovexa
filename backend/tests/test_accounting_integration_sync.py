from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import (
    AccountingBusinessTransaction,
    AccountingEntryDraft,
    AccountingVoucher,
    AuditEvent,
    BusinessProfile,
    Expense,
    Invoice,
    Payment,
)
from app.services.accounting_math import financial_year_for


def _login(client, path, email, password):
    response = client.post(path, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _clients(client, headers):
    response = client.get("/api/accounting/senior/clients", headers=headers)
    assert response.status_code == 200, response.text
    return {row["business_name"]: row for row in response.json()["items"]}


def _sync(client, headers, client_id):
    response = client.post(
        f"/api/accounting/senior/clients/{client_id}/integration/sync",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _expected_counts(owner_id: int) -> dict:
    db = SessionLocal()
    try:
        invoices = db.query(Invoice).filter(Invoice.user_id == owner_id).all()
        payments = db.query(Payment).filter(Payment.user_id == owner_id).all()
        expenses = db.query(Expense).filter(Expense.user_id == owner_id).all()
    finally:
        db.close()
    bookable_invoices = [
        row for row in invoices if (row.status or "issued") not in ("draft", "void")
    ]
    bookable_payments = [row for row in payments if row.status == "confirmed"]
    bookable_expenses = [row for row in expenses if row.amount > 0]
    return {
        "discovered": len(invoices) + len(payments) + len(expenses),
        "created": len(bookable_invoices) + len(bookable_payments) + len(bookable_expenses),
        "invoices": len(bookable_invoices),
        "payments": len(bookable_payments),
        "expenses": len(bookable_expenses),
    }


def test_sync_builds_inbox_once_and_preserves_sources(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    detail = client.get(
        f"/api/accounting/senior/clients/{dn['id']}", headers=senior["headers"]
    ).json()
    owner_id = demo["user"]["id"]
    profile_id = detail["integration"]["business"]["id"]
    assert profile_id == detail["client"]["business_profile_id"]

    db = SessionLocal()
    try:
        assert db.get(BusinessProfile, profile_id).user_id == owner_id
        invoice_rows = {
            row.id: row
            for row in db.query(Invoice)
            .options(selectinload(Invoice.items))
            .filter(Invoice.user_id == owner_id)
            .all()
        }
        invoice_count = len(invoice_rows)
        voucher_count = db.query(AccountingVoucher).count()
    finally:
        db.close()
    expected = _expected_counts(owner_id)
    assert invoice_count > 0 and expected["created"] > 0

    first = _sync(client, senior["headers"], dn["id"])
    run = first["run"]
    assert run["status"] == "completed"
    assert run["errors"] == 0
    assert run["discovered"] == expected["discovered"]
    assert run["created"] == expected["created"]
    assert run["skipped"] == expected["discovered"] - expected["created"]
    summary = first["integration"]
    assert summary["counts"]["total"] == expected["created"]
    assert summary["counts"]["pending"] == expected["created"]
    assert summary["counts"]["needs_attention"] == 0
    assert summary["last_synced_at"] is not None
    assert summary["last_run"]["id"] == run["id"]

    db = SessionLocal()
    try:
        assert db.query(Invoice).filter(Invoice.user_id == owner_id).count() == invoice_count
        assert db.query(AccountingVoucher).count() == voucher_count
        inbox = (
            db.query(AccountingBusinessTransaction)
            .filter(AccountingBusinessTransaction.client_id == dn["id"])
            .all()
        )
        assert len(inbox) == expected["created"]
        by_source = {}
        for row in inbox:
            by_source[row.source_type] = by_source.get(row.source_type, 0) + 1
            assert row.financial_year == financial_year_for(row.transaction_date)
            assert row.status == "pending"
        assert by_source == {
            "invoice": expected["invoices"],
            "payment": expected["payments"],
            "expense": expected["expenses"],
        }
        sample = next(row for row in inbox if row.source_type == "invoice")
        source = invoice_rows[sample.source_id]
        assert sample.source_ref == source.number
        assert sample.transaction_date == source.issue_date
        assert len(sample.lines) == len(source.items)
        assert sample.total_amount == source.total_amount
        second_actions = {
            event.action
            for event in db.query(AuditEvent)
            .filter(AuditEvent.entity_type == "accounting_integration_run")
            .all()
        }
    finally:
        db.close()
    assert "accounting.integration_synced" in second_actions

    second = _sync(client, senior["headers"], dn["id"])
    assert second["run"]["created"] == 0
    assert second["run"]["updated"] == 0
    assert second["run"]["skipped"] == expected["discovered"]
    assert second["integration"]["counts"]["total"] == expected["created"]

    runs = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/runs",
        headers=senior["headers"],
    )
    assert runs.status_code == 200, runs.text
    assert [row["id"] for row in runs.json()["items"][:2]] == [
        second["run"]["id"],
        first["run"]["id"],
    ]

    inbox_page = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/transactions",
        params={"source_type": "invoice", "limit": 5},
        headers=senior["headers"],
    )
    assert inbox_page.status_code == 200, inbox_page.text
    body = inbox_page.json()
    assert body["total"] == expected["invoices"]
    assert len(body["items"]) == 5
    assert all(item["source_type"] == "invoice" for item in body["items"])


def test_source_change_after_draft_is_flagged_not_overwritten(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])

    db = SessionLocal()
    try:
        txn = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.source_type == "invoice",
            )
            .order_by(AccountingBusinessTransaction.id)
            .first()
        )
        draft = AccountingEntryDraft(
            client_id=dn["id"],
            transaction_id=txn.id,
            voucher_type="sales",
            number="JE-TXN-0001",
            voucher_date=txn.transaction_date,
            financial_year=txn.financial_year,
            party_name=txn.party_name,
            narration="Draft prepared before the source changed.",
            total_debit=txn.total_amount,
            total_credit=txn.total_amount,
            difference=0,
            status="draft",
            source_hash=txn.source_hash,
        )
        db.add(draft)
        invoice = db.get(Invoice, txn.source_id)
        invoice.notes = "Customer asked to add a delivery note."
        voucher_count = db.query(AccountingVoucher).count()
        db.commit()
        txn_id = txn.id
        draft_id = draft.id
    finally:
        db.close()

    result = _sync(client, senior["headers"], dn["id"])
    assert result["run"]["updated"] == 1
    assert result["integration"]["counts"]["needs_attention"] == 1
    assert result["integration"]["counts"]["pending"] == result["integration"]["counts"]["total"] - 1

    db = SessionLocal()
    try:
        txn = db.get(AccountingBusinessTransaction, txn_id)
        assert txn.status == "needs_attention"
        assert "draft" in (txn.issue_reason or "").lower()
        assert txn.snapshot["notes"] == "Customer asked to add a delivery note."
        assert db.get(AccountingEntryDraft, draft_id) is not None
        assert db.query(AccountingVoucher).count() == voucher_count
    finally:
        db.close()

    filtered = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/transactions",
        params={"status": "needs_attention"},
        headers=senior["headers"],
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["issue_reason"]


def test_voided_invoice_and_refund_are_synced_with_correct_semantics(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])

    db = SessionLocal()
    try:
        issued = (
            db.query(Invoice)
            .filter(Invoice.user_id == demo["user"]["id"], Invoice.status == "issued")
            .order_by(Invoice.id)
            .first()
        )
        issued.status = "void"
        payment = (
            db.query(Payment)
            .filter(
                Payment.user_id == demo["user"]["id"],
                Payment.status == "confirmed",
                Payment.refund_of_payment_id.is_(None),
            )
            .order_by(Payment.id)
            .first()
        )
        refund_amount = (payment.amount / 2).quantize(Decimal("0.01"))
        refund = Payment(
            user_id=demo["user"]["id"],
            invoice_id=payment.invoice_id,
            refund_of_payment_id=payment.id,
            amount=-refund_amount,
            currency=payment.currency,
            method=payment.method,
            status="confirmed",
            provider="manual",
            note="Partial refund for a damaged unit.",
        )
        db.add(refund)
        db.commit()
        void_invoice_id = issued.id
        refund_id = refund.id
        payment_amount = payment.amount
    finally:
        db.close()

    result = _sync(client, senior["headers"], dn["id"])
    assert result["run"]["status"] == "completed"
    assert result["run"]["created"] == 1
    assert result["integration"]["counts"]["needs_attention"] == 1

    db = SessionLocal()
    try:
        voided = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.source_type == "invoice",
                AccountingBusinessTransaction.source_id == void_invoice_id,
            )
            .one()
        )
        assert voided.source_status == "void"
        assert voided.status == "needs_attention"
        assert "void" in (voided.issue_reason or "").lower()

        refund_row = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.source_type == "payment",
                AccountingBusinessTransaction.source_id == refund_id,
            )
            .one()
        )
        assert refund_row.transaction_type == "refund"
        assert refund_row.total_amount < 0
        assert refund_row.total_amount == -(payment_amount / 2).quantize(Decimal("0.01"))
        assert refund_row.status == "pending"
    finally:
        db.close()


def test_sync_rbac_and_owner_read_only(client, demo, other):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    junior = _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")
    clients = _clients(client, senior["headers"])
    dn = clients["DN Ventures Pvt. Ltd"]
    sunrise = clients["Sunrise Interiors"]

    assert client.post(
        f"/api/accounting/senior/clients/{dn['id']}/integration/sync",
        headers=junior["headers"],
    ).status_code == 403
    assert client.post(
        f"/api/accounting/senior/clients/{sunrise['id']}/integration/sync",
        headers=senior["headers"],
    ).status_code == 409
    assert client.post(
        "/api/accounting/senior/clients/999999/integration/sync",
        headers=senior["headers"],
    ).status_code == 404
    assert client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/transactions",
        headers=demo["headers"],
    ).status_code == 403

    result = _sync(client, senior["headers"], dn["id"])
    total = result["integration"]["counts"]["total"]
    expected = _expected_counts(demo["user"]["id"])
    assert total == expected["created"]

    junior_summary = client.get(
        f"/api/accounting/junior/clients/{dn['id']}/integration",
        headers=junior["headers"],
    )
    assert junior_summary.status_code == 200, junior_summary.text
    assert junior_summary.json()["counts"]["total"] == total
    junior_inbox = client.get(
        f"/api/accounting/junior/clients/{dn['id']}/integration/transactions",
        headers=junior["headers"],
    )
    assert junior_inbox.status_code == 200, junior_inbox.text
    assert junior_inbox.json()["total"] == total
    assert client.get(
        f"/api/accounting/junior/clients/{sunrise['id']}/integration",
        headers=junior["headers"],
    ).status_code == 403
    assert client.get(
        f"/api/accounting/junior/clients/{sunrise['id']}/integration/transactions",
        headers=junior["headers"],
    ).status_code == 403

    owner_status = client.get("/api/integration/accounting", headers=demo["headers"])
    assert owner_status.status_code == 200, owner_status.text
    assert owner_status.json()["linked"] is True
    assert owner_status.json()["counts"]["total"] == total
    assert "settings" not in owner_status.json()
    owner_inbox = client.get(
        "/api/integration/accounting/transactions",
        params={"source_type": "expense"},
        headers=demo["headers"],
    )
    assert owner_inbox.status_code == 200, owner_inbox.text
    assert owner_inbox.json()["total"] == expected["expenses"]

    other_status = client.get("/api/integration/accounting", headers=other["headers"])
    assert other_status.status_code == 200, other_status.text
    assert other_status.json()["linked"] is False
    other_inbox = client.get("/api/integration/accounting/transactions", headers=other["headers"])
    assert other_inbox.json()["total"] == 0


def test_repeat_sync_keeps_original_dates_and_financial_years(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])

    db = SessionLocal()
    try:
        before = {
            (row.source_type, row.source_id): (row.transaction_date, row.financial_year, row.total_amount)
            for row in db.query(AccountingBusinessTransaction)
            .filter(AccountingBusinessTransaction.client_id == dn["id"])
            .all()
        }
        # A backdated expense in a prior financial year must keep its own FY.
        expense = Expense(
            user_id=demo["user"]["id"],
            category="Professional fees",
            vendor="Prior Year Advisors",
            amount=4500,
            incurred_on=date(2024, 5, 12),
            note="Filed after the deadline.",
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id
    finally:
        db.close()

    result = _sync(client, senior["headers"], dn["id"])
    assert result["run"]["created"] == 1

    db = SessionLocal()
    try:
        kept = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.source_type == "expense",
                AccountingBusinessTransaction.source_id == expense_id,
            )
            .one()
        )
        assert kept.transaction_date == date(2024, 5, 12)
        assert kept.financial_year == "2024-25"
        for row in db.query(AccountingBusinessTransaction).filter(
            AccountingBusinessTransaction.client_id == dn["id"]
        ):
            if row.source_type == "expense" and row.source_id == expense_id:
                continue
            assert before[(row.source_type, row.source_id)] == (
                row.transaction_date,
                row.financial_year,
                row.total_amount,
            )
    finally:
        db.close()
