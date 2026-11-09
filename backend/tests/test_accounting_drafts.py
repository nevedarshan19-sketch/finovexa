from __future__ import annotations

from decimal import Decimal

from app.database import SessionLocal
from app.models import (
    AccountingBusinessTransaction,
    AccountingEntryDraft,
    AccountingVoucher,
    AuditEvent,
    Invoice,
    Payment,
)


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


def _generate(client, headers, client_id, **body):
    response = client.post(
        f"/api/accounting/senior/clients/{client_id}/integration/drafts/generate",
        json=body or {"limit": 5},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _txn(db, client_id, **filters):
    query = db.query(AccountingBusinessTransaction).filter(
        AccountingBusinessTransaction.client_id == client_id
    )
    for key, value in filters.items():
        query = query.filter(getattr(AccountingBusinessTransaction, key) == value)
    return query.order_by(AccountingBusinessTransaction.id).first()


def _balanced(draft: dict) -> None:
    debit = sum((Decimal(str(line["debit"])) for line in draft["lines"]), Decimal("0"))
    credit = sum((Decimal(str(line["credit"])) for line in draft["lines"]), Decimal("0"))
    assert debit == credit
    assert Decimal(str(draft["total_debit"])) == debit
    assert Decimal(str(draft["total_credit"])) == credit
    assert Decimal(str(draft["difference"])) == Decimal("0")


def test_suggestions_cover_sale_receipt_refund_and_expense(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])

    db = SessionLocal()
    try:
        intra = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.source_type == "invoice",
                AccountingBusinessTransaction.cgst_amount > 0,
            )
            .first()
        )
        receipt = _txn(db, dn["id"], transaction_type="receipt")
        rent = _txn(db, dn["id"], transaction_type="expense")
        receipt_amount = receipt.total_amount
        receipt_party = receipt.party_name
        rent_amount = rent.total_amount
        intra_id = intra.id
        intra_party = intra.party_name
        intra_total = intra.total_amount
        receipt_id = receipt.id
        rent_id = rent.id
        payment_reference = (
            db.query(Payment)
            .filter(Payment.user_id == demo["user"]["id"], Payment.status == "confirmed")
            .order_by(Payment.id)
            .first()
        )
        refund = Payment(
            user_id=demo["user"]["id"],
            invoice_id=payment_reference.invoice_id,
            refund_of_payment_id=payment_reference.id,
            amount=-(payment_reference.amount / 2).quantize(Decimal("0.01")),
            currency=payment_reference.currency,
            method=payment_reference.method,
            status="confirmed",
            provider="manual",
            note="Refund for a returned unit.",
        )
        db.add(refund)
        db.commit()
        refund_id = refund.id
    finally:
        db.close()

    _sync(client, senior["headers"], dn["id"])
    db = SessionLocal()
    try:
        refund_txn_id = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.source_type == "payment",
                AccountingBusinessTransaction.source_id == refund_id,
            )
            .one()
            .id
        )
    finally:
        db.close()

    def suggestion(txn_id):
        response = client.get(
            f"/api/accounting/senior/clients/{dn['id']}/integration/transactions/{txn_id}/suggestion",
            headers=senior["headers"],
        )
        assert response.status_code == 200, response.text
        return response.json()

    sale = suggestion(intra_id)
    assert sale["voucher_type"] == "sale"
    assert sale["mapping"]["source"] == "client_defaults"
    assert sale["total_debit"] == sale["total_credit"]
    assert Decimal(str(sale["total_debit"])) == Decimal(str(intra_total))
    assert any(line["credit"] > 0 and "GST" in line["ledger_name"] for line in sale["lines"])
    assert any(line["debit"] > 0 and line["ledger_name"] == intra_party for line in sale["lines"])
    assert any(
        line["credit"] > 0 and line["ledger_name"] == "Sales - office furniture"
        for line in sale["lines"]
    )

    receipt_view = suggestion(receipt_id)
    assert receipt_view["voucher_type"] == "receipt"
    debit = [line for line in receipt_view["lines"] if line["debit"] > 0]
    credit = [line for line in receipt_view["lines"] if line["credit"] > 0]
    assert len(debit) == 1 and debit[0]["ledger_name"] == "ICICI Bank - Current"
    assert len(credit) == 1 and credit[0]["ledger_name"] == receipt_party
    assert Decimal(str(receipt_view["total_debit"])) == abs(Decimal(str(receipt_amount)))

    refund_view = suggestion(refund_txn_id)
    assert refund_view["voucher_type"] == "payment"
    debit = [line for line in refund_view["lines"] if line["debit"] > 0]
    credit = [line for line in refund_view["lines"] if line["credit"] > 0]
    assert debit and credit
    assert debit[0]["ledger_name"] == refund_view["party_name"]
    assert credit[0]["ledger_name"] == "ICICI Bank - Current"
    assert Decimal(str(refund_view["total_debit"])) > 0

    expense_view = suggestion(rent_id)
    assert expense_view["voucher_type"] == "expense"
    debit = [line for line in expense_view["lines"] if line["debit"] > 0]
    assert debit and debit[0]["ledger_name"]
    assert Decimal(str(expense_view["total_debit"])) == abs(Decimal(str(rent_amount)))
    assert expense_view["warnings"]


def test_generate_drafts_is_balanced_idempotent_and_posts_nothing(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])
    total_pending = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration",
        headers=senior["headers"],
    ).json()["counts"]["pending"]
    assert total_pending > 5

    db = SessionLocal()
    try:
        vouchers_before = db.query(AccountingVoucher).count()
    finally:
        db.close()

    first = _generate(client, senior["headers"], dn["id"], limit=5)
    assert first["generated"] == 5
    assert first["skipped"] == 0 and first["errors"] == 0
    assert first["integration"]["counts"]["drafted"] == 5
    assert first["integration"]["counts"]["pending"] == total_pending - 5
    numbers = {draft["number"] for draft in first["drafts"]}
    assert len(numbers) == 5
    for draft in first["drafts"]:
        _balanced(draft)
        assert draft["status"] == "draft"
        assert draft["source"]["status"] == "drafted"

    second = _generate(client, senior["headers"], dn["id"], limit=5)
    assert second["generated"] == 5
    assert not (numbers & {draft["number"] for draft in second["drafts"]})

    already = _generate(
        client,
        senior["headers"],
        dn["id"],
        transaction_ids=[first["drafts"][0]["transaction_id"]],
    )
    assert already["generated"] == 0
    assert already["skipped"] == 1
    assert "already exists" in already["skipped_details"][0]["reason"]

    listing = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts",
        headers=senior["headers"],
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 10
    _balanced(listing.json()["items"][0])

    db = SessionLocal()
    try:
        assert db.query(AccountingVoucher).count() == vouchers_before
        assert db.query(AccountingEntryDraft).count() == 10
        drafted = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.status == "drafted",
            )
            .count()
        )
        assert drafted == 10
        actions = {
            event.action
            for event in db.query(AuditEvent)
            .filter(AuditEvent.action.like("accounting.entry_draft%"))
            .all()
        }
    finally:
        db.close()
    assert "accounting.entry_draft_generated" in actions
    assert "accounting.entry_drafts_generated" in actions


def test_ledger_mapping_overrides_and_permissions(client, demo, other):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    junior = _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    sunrise = _clients(client, senior["headers"])["Sunrise Interiors"]
    _sync(client, senior["headers"], dn["id"])

    response = client.put(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings",
        json={
            "transaction_type": "expense",
            "category": "Logistics",
            "debit_ledger": "Freight - Reviewed",
            "credit_ledger": "Petty Cash",
            "notes": "Demo practice mapping.",
        },
        headers=senior["headers"],
    )
    assert response.status_code == 200, response.text
    mapping = response.json()
    assert mapping["is_active"] is True

    receipt_mapping = client.put(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings",
        json={"transaction_type": "receipt", "bank_ledger": "HDFC Bank - Current"},
        headers=senior["headers"],
    )
    assert receipt_mapping.status_code == 200, receipt_mapping.text

    db = SessionLocal()
    try:
        rent_ids = [
            row.id
            for row in db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == dn["id"],
                AccountingBusinessTransaction.transaction_type == "expense",
                AccountingBusinessTransaction.category == "Logistics",
            )
            .order_by(AccountingBusinessTransaction.id)
            .all()
        ]
        receipt_id = _txn(db, dn["id"], transaction_type="receipt").id
    finally:
        db.close()
    assert len(rent_ids) >= 2

    generated = _generate(
        client,
        senior["headers"],
        dn["id"],
        transaction_ids=[rent_ids[0], receipt_id],
    )
    assert generated["errors"] == 0
    by_type = {draft["voucher_type"]: draft for draft in generated["drafts"]}
    rent_draft = by_type["expense"]
    assert any(line["ledger_name"] == "Freight - Reviewed" and line["debit"] > 0 for line in rent_draft["lines"])
    assert any(line["ledger_name"] == "Petty Cash" and line["credit"] > 0 for line in rent_draft["lines"])
    receipt_draft = by_type["receipt"]
    assert any(line["ledger_name"] == "HDFC Bank - Current" and line["debit"] > 0 for line in receipt_draft["lines"])

    preview = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/transactions/{rent_ids[1]}/suggestion",
        headers=senior["headers"],
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["mapping"]["mapping_id"] == mapping["id"]

    mappings = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings",
        headers=senior["headers"],
    )
    assert mappings.status_code == 200, mappings.text
    body = mappings.json()
    assert len(body["items"]) == 2
    assert body["client_defaults"]["bank"] == "ICICI Bank - Current"
    assert client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings",
        headers=junior["headers"],
    ).status_code == 403

    assert client.put(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings",
        json={"transaction_type": "sale", "credit_ledger": "Sales"},
        headers=junior["headers"],
    ).status_code == 403
    assert client.put(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings",
        json={"transaction_type": "sale", "credit_ledger": "Sales"},
        headers=demo["headers"],
    ).status_code == 403
    assert client.put(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings",
        json={"transaction_type": "expense", "category": "Logistics"},
        headers=senior["headers"],
    ).status_code == 422

    removed = client.delete(
        f"/api/accounting/senior/clients/{dn['id']}/integration/ledger-mappings/{mapping['id']}",
        headers=senior["headers"],
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["is_active"] is False
    after = client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/transactions/{rent_ids[1]}/suggestion",
        headers=senior["headers"],
    )
    assert after.status_code == 200, after.text
    assert after.json()["mapping"]["mapping_id"] is None

    assert client.post(
        f"/api/accounting/senior/clients/{sunrise['id']}/integration/drafts/generate",
        json={"limit": 1},
        headers=senior["headers"],
    ).status_code == 409

    junior_generate = client.post(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/generate",
        json={"limit": 1},
        headers=junior["headers"],
    )
    assert junior_generate.status_code == 403


def test_draft_edit_validates_balance_and_permissions(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    junior = _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    sunrise = _clients(client, senior["headers"])["Sunrise Interiors"]
    _sync(client, senior["headers"], dn["id"])
    created = _generate(client, senior["headers"], dn["id"], limit=1)["drafts"][0]
    draft_id = created["id"]

    edited = client.patch(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft_id}",
        json={
            "narration": "Reviewed by senior accountant.",
            "lines": [
                {
                    "ledger_name": "Accounts Receivable - reviewed",
                    "description": "Reviewed debit",
                    "debit": "100.00",
                    "credit": "0",
                },
                {
                    "ledger_name": "Sales - reviewed",
                    "description": "Reviewed credit",
                    "debit": "0",
                    "credit": "100.00",
                },
            ],
        },
        headers=senior["headers"],
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["narration"] == "Reviewed by senior accountant."
    assert body["total_debit"] == 100
    assert body["total_credit"] == 100
    assert body["lines"][0]["ledger_name"] == "Accounts Receivable - reviewed"
    _balanced(body)

    unbalanced = client.patch(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft_id}",
        json={
            "lines": [
                {"ledger_name": "A", "debit": "100.00", "credit": "0"},
                {"ledger_name": "B", "debit": "0", "credit": "90.00"},
            ]
        },
        headers=senior["headers"],
    )
    assert unbalanced.status_code == 422
    assert "must match" in unbalanced.text

    both_sides = client.patch(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft_id}",
        json={"lines": [{"ledger_name": "A", "debit": "100.00", "credit": "1.00"}]},
        headers=senior["headers"],
    )
    assert both_sides.status_code == 422

    assert client.patch(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft_id}",
        json={"narration": "Junior edit"},
        headers=junior["headers"],
    ).status_code == 403
    assert client.get(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft_id}",
        headers=demo["headers"],
    ).status_code == 403
    assert client.get(
        f"/api/accounting/senior/clients/{sunrise['id']}/integration/drafts/{draft_id}",
        headers=senior["headers"],
    ).status_code == 404

    junior_list = client.get(
        f"/api/accounting/junior/clients/{dn['id']}/integration/drafts",
        headers=junior["headers"],
    )
    assert junior_list.status_code == 200, junior_list.text
    assert junior_list.json()["total"] == 1
    junior_detail = client.get(
        f"/api/accounting/junior/clients/{dn['id']}/integration/drafts/{draft_id}",
        headers=junior["headers"],
    )
    assert junior_detail.status_code == 200, junior_detail.text

    db = SessionLocal()
    try:
        draft = db.get(AccountingEntryDraft, draft_id)
        draft.status = "pending_review"
        db.commit()
    finally:
        db.close()
    assert client.patch(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft_id}",
        json={"narration": "Too late"},
        headers=senior["headers"],
    ).status_code == 409

    db = SessionLocal()
    try:
        actions = {
            event.action
            for event in db.query(AuditEvent)
            .filter(AuditEvent.entity_type == "accounting_entry_draft")
            .all()
        }
    finally:
        db.close()
    assert "accounting.entry_draft_generated" in actions
    assert "accounting.entry_draft_updated" in actions


def test_source_change_after_draft_flags_inbox_and_preserves_draft(client):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])
    created = _generate(client, senior["headers"], dn["id"], limit=1)["drafts"][0]
    draft_id = created["id"]
    txn_id = created["transaction_id"]

    db = SessionLocal()
    try:
        txn = db.get(AccountingBusinessTransaction, txn_id)
        invoice = db.get(Invoice, txn.source_id)
        assert invoice is not None
        invoice.notes = "Source updated after the draft was prepared."
        db.commit()
    finally:
        db.close()

    _sync(client, senior["headers"], dn["id"])

    db = SessionLocal()
    try:
        txn = db.get(AccountingBusinessTransaction, txn_id)
        assert txn.status == "needs_attention"
        assert "draft" in (txn.issue_reason or "").lower()
        assert db.get(AccountingEntryDraft, draft_id) is not None
    finally:
        db.close()

    blocked = _generate(client, senior["headers"], dn["id"], transaction_ids=[txn_id])
    assert blocked["generated"] == 0
    assert blocked["skipped"] == 1
    assert "needs_attention" in blocked["skipped_details"][0]["reason"]
