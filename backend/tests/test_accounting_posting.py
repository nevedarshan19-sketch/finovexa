from __future__ import annotations

from decimal import Decimal

from app.database import SessionLocal
from app.models import (
    AccountingBusinessTransaction,
    AccountingEntryDraft,
    AccountingVoucher,
    AccountingVoucherLine,
    AuditEvent,
    Invoice,
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
        json=body or {"limit": 200},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _action(client, headers, client_id, draft_id, action, body=None):
    return client.post(
        f"/api/accounting/senior/clients/{client_id}/integration/drafts/{draft_id}/{action}",
        json=body or {},
        headers=headers,
    )


def _get(client, headers, client_id, draft_id):
    response = client.get(
        f"/api/accounting/senior/clients/{client_id}/integration/drafts/{draft_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _audit_actions(db):
    return {event.action for event in db.query(AuditEvent).all()}


def test_sale_draft_submit_approve_post_creates_balanced_voucher(client):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    junior = _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])
    generated = _generate(client, senior["headers"], dn["id"])
    draft = next(row for row in generated["drafts"] if row["voucher_type"] == "sale")
    draft_id = draft["id"]
    txn_id = draft["transaction_id"]
    draft_detail = _get(client, senior["headers"], dn["id"], draft_id)
    draft_lines = [(line["ledger_name"], Decimal(str(line["debit"])), Decimal(str(line["credit"]))) for line in draft_detail["lines"]]

    db = SessionLocal()
    try:
        invoice_count = db.query(Invoice).count()
        voucher_count = db.query(AccountingVoucher).filter(AccountingVoucher.client_id == dn["id"]).count()
    finally:
        db.close()

    submitted = _action(client, senior["headers"], dn["id"], draft_id, "submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_review"
    assert submitted.json()["submitted_at"] is not None

    approved = _action(
        client, senior["headers"], dn["id"], draft_id, "approve", {"note": "Checked against invoice."}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["review_note"] == "Checked against invoice."
    assert approved.json()["reviewed_by_user_id"] == senior["user"]["id"]

    posted = _action(client, senior["headers"], dn["id"], draft_id, "post")
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["status"] == "posted"
    assert body["source"]["status"] == "posted"
    voucher = body["voucher"]
    assert voucher["voucher_type"] == "sale"
    assert voucher["number"] == draft["number"]
    assert voucher["voucher_date"] == draft["voucher_date"]
    assert voucher["party_name"] == draft["party_name"]
    assert voucher["source"] == "integration"
    assert voucher["status"] == "posted"
    assert voucher["entry_draft_id"] == draft_id
    assert voucher["source_transaction_id"] == txn_id
    total = Decimal(str(draft["total_debit"]))
    assert Decimal(str(voucher["total_amount"])) == total
    assert (
        Decimal(str(voucher["taxable_value"]))
        + Decimal(str(voucher["cgst_amount"]))
        + Decimal(str(voucher["sgst_amount"]))
        + Decimal(str(voucher["igst_amount"]))
        == total
    )
    assert [
        (line["ledger_name"], Decimal(str(line["debit"])), Decimal(str(line["credit"])))
        for line in voucher["lines"]
    ] == draft_lines

    db = SessionLocal()
    try:
        txn = db.get(AccountingBusinessTransaction, txn_id)
        assert txn.status == "posted"
        assert db.query(AccountingVoucher).filter(AccountingVoucher.client_id == dn["id"]).count() == voucher_count + 1
        voucher_row = db.get(AccountingVoucher, voucher["id"])
        assert voucher_row.entry_draft_id == draft_id
        assert db.query(AccountingVoucherLine).filter(AccountingVoucherLine.voucher_id == voucher["id"]).count() == len(draft_lines)
        assert db.query(Invoice).count() == invoice_count
        actions = _audit_actions(db)
    finally:
        db.close()
    assert "accounting.entry_draft_submitted" in actions
    assert "accounting.entry_draft_approved" in actions
    assert "accounting.entry_draft_posted" in actions

    junior_view = client.get(
        f"/api/accounting/junior/clients/{dn['id']}/integration/drafts/{draft_id}",
        headers=junior["headers"],
    )
    assert junior_view.status_code == 200, junior_view.text
    assert junior_view.json()["status"] == "posted"
    assert junior_view.json()["voucher"]["id"] == voucher["id"]

    assert _action(client, senior["headers"], dn["id"], draft_id, "approve").status_code == 409
    assert _action(client, senior["headers"], dn["id"], draft_id, "post").status_code == 409
    assert _action(client, senior["headers"], dn["id"], draft_id, "submit").status_code == 409


def test_reject_requires_reason_and_editing_reopens_draft(client):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])
    created = _generate(client, senior["headers"], dn["id"], limit=1)["drafts"][0]
    draft_id = created["id"]

    assert _action(client, senior["headers"], dn["id"], draft_id, "post").status_code == 409
    assert _action(client, senior["headers"], dn["id"], draft_id, "approve").status_code == 409
    assert _action(client, senior["headers"], dn["id"], draft_id, "reject", {"note": "x"}).status_code == 409

    submitted = _action(client, senior["headers"], dn["id"], draft_id, "submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_review"

    missing_reason = _action(client, senior["headers"], dn["id"], draft_id, "reject", {})
    assert missing_reason.status_code == 422
    assert "reason" in missing_reason.text.lower()

    rejected = _action(
        client, senior["headers"], dn["id"], draft_id, "reject", {"note": "Wrong ledger used."}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["review_note"] == "Wrong ledger used."
    assert _action(client, senior["headers"], dn["id"], draft_id, "reject", {"note": "again"}).status_code == 409

    edited = client.patch(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft_id}",
        json={"narration": "Corrected after rejection."},
        headers=senior["headers"],
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "draft"
    assert edited.json()["review_note"] is None
    assert edited.json()["reviewed_at"] is None

    assert _action(client, senior["headers"], dn["id"], draft_id, "submit").status_code == 200
    approved = _action(client, senior["headers"], dn["id"], draft_id, "approve")
    assert approved.status_code == 200, approved.text
    assert _action(client, senior["headers"], dn["id"], draft_id, "reject", {"note": "late"}).status_code == 409
    assert _action(client, senior["headers"], dn["id"], draft_id, "post").status_code == 200


def test_source_changes_require_explicit_acknowledgement(client):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])
    generated = _generate(client, senior["headers"], dn["id"])
    sales = [row for row in generated["drafts"] if row["voucher_type"] == "sale"][:2]
    assert len(sales) == 2
    first, second = sales

    assert _action(client, senior["headers"], dn["id"], first["id"], "submit").status_code == 200
    assert _action(client, senior["headers"], dn["id"], first["id"], "approve").status_code == 200
    assert _action(client, senior["headers"], dn["id"], second["id"], "submit").status_code == 200

    db = SessionLocal()
    try:
        txn = db.get(AccountingBusinessTransaction, first["transaction_id"])
        invoice = db.get(Invoice, txn.source_id)
        invoice.notes = "Invoice corrected after approval."
        db.commit()
    finally:
        db.close()
    _sync(client, senior["headers"], dn["id"])

    blocked = _action(client, senior["headers"], dn["id"], first["id"], "post")
    assert blocked.status_code == 409
    assert "acknowledge_source_change" in blocked.text

    posted = _action(
        client, senior["headers"], dn["id"], first["id"], "post", {"acknowledge_source_change": True}
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted"

    db = SessionLocal()
    try:
        event = (
            db.query(AuditEvent)
            .filter(AuditEvent.action == "accounting.entry_draft_posted")
            .order_by(AuditEvent.id.desc())
            .first()
        )
        assert event.detail["source_change_acknowledged"] is True
        txn = db.get(AccountingBusinessTransaction, second["transaction_id"])
        invoice = db.get(Invoice, txn.source_id)
        invoice.notes = "Second invoice corrected before approval."
        db.commit()
    finally:
        db.close()
    _sync(client, senior["headers"], dn["id"])

    unacknowledged = _action(client, senior["headers"], dn["id"], second["id"], "approve")
    assert unacknowledged.status_code == 409
    acknowledged = _action(
        client,
        senior["headers"],
        dn["id"],
        second["id"],
        "approve",
        {"note": "Reviewed the corrected source.", "acknowledge_source_change": True},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "approved"

    posted_second = _action(client, senior["headers"], dn["id"], second["id"], "post")
    assert posted_second.status_code == 200, posted_second.text
    assert posted_second.json()["status"] == "posted"


def test_posting_rejects_unclassified_gst_ledger_and_posts_classified_tax(client):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    _sync(client, senior["headers"], dn["id"])
    generated = _generate(client, senior["headers"], dn["id"])
    expenses = [row for row in generated["drafts"] if row["voucher_type"] == "expense"][:2]
    assert len(expenses) == 2
    bad, good = expenses

    def set_lines(draft, tax_ledger):
        response = client.patch(
            f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft['id']}",
            json={
                "party_name": "Stationery Mart",
                "lines": [
                    {"ledger_name": "Office supplies", "debit": "900.00", "credit": "0"},
                    {"ledger_name": tax_ledger, "debit": "100.00", "credit": "0"},
                    {"ledger_name": "Stationery Mart", "debit": "0", "credit": "1000.00"},
                ],
            },
            headers=senior["headers"],
        )
        assert response.status_code == 200, response.text

    set_lines(bad, "Input GST")
    assert _action(client, senior["headers"], dn["id"], bad["id"], "submit").status_code == 200
    assert _action(client, senior["headers"], dn["id"], bad["id"], "approve").status_code == 200
    rejected = _action(client, senior["headers"], dn["id"], bad["id"], "post")
    assert rejected.status_code == 422
    assert "CGST" in rejected.text and "GST" in rejected.text

    db = SessionLocal()
    try:
        assert (
            db.query(AccountingVoucher).filter(AccountingVoucher.entry_draft_id == bad["id"]).count()
            == 0
        )
    finally:
        db.close()

    set_lines(good, "Input GST - CGST")
    assert _action(client, senior["headers"], dn["id"], good["id"], "submit").status_code == 200
    assert _action(client, senior["headers"], dn["id"], good["id"], "approve").status_code == 200
    posted = _action(client, senior["headers"], dn["id"], good["id"], "post")
    assert posted.status_code == 200, posted.text
    voucher = posted.json()["voucher"]
    assert Decimal(str(voucher["taxable_value"])) == Decimal("900.00")
    assert Decimal(str(voucher["cgst_amount"])) == Decimal("100.00")
    assert Decimal(str(voucher["sgst_amount"])) == Decimal("0.00")
    assert Decimal(str(voucher["igst_amount"])) == Decimal("0.00")
    assert Decimal(str(voucher["gst_rate"])) == Decimal("11.11")
    assert Decimal(str(voucher["total_amount"])) == Decimal("1000.00")
    assert voucher["ledger_name"] == "Office supplies"


def test_review_and_posting_permissions_and_isolation(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    junior = _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    sunrise = _clients(client, senior["headers"])["Sunrise Interiors"]
    _sync(client, senior["headers"], dn["id"])
    created = _generate(client, senior["headers"], dn["id"], limit=1)["drafts"][0]
    draft_id = created["id"]

    for action in ("submit", "approve", "reject", "post"):
        assert _action(client, junior["headers"], dn["id"], draft_id, action).status_code == 403
        assert _action(client, demo["headers"], dn["id"], draft_id, action).status_code == 403
        assert _action(client, senior["headers"], sunrise["id"], draft_id, action).status_code == 404

    assert client.get(
        f"/api/accounting/junior/clients/{dn['id']}/integration/drafts/{draft_id}",
        headers=junior["headers"],
    ).status_code == 200
    assert client.get(
        f"/api/accounting/junior/clients/{sunrise['id']}/integration/drafts/{draft_id}",
        headers=junior["headers"],
    ).status_code == 403

    assert _action(client, senior["headers"], dn["id"], draft_id, "submit").status_code == 200
    assert _action(client, senior["headers"], dn["id"], draft_id, "approve").status_code == 200
    assert _action(client, senior["headers"], dn["id"], draft_id, "post").status_code == 200

    db = SessionLocal()
    try:
        draft = db.get(AccountingEntryDraft, draft_id)
        assert draft.status == "posted"
        assert db.query(AccountingVoucher).filter(AccountingVoucher.entry_draft_id == draft_id).count() == 1
    finally:
        db.close()
