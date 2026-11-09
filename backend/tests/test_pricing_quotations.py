from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import AccountingQuotation, AuditEvent, Payment


def _login(client, path, email, password):
    response = client.post(path, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


@pytest.fixture()
def senior(client):
    return _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")


@pytest.fixture()
def junior(client):
    return _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")


@pytest.fixture()
def customer(client):
    return _login(client, "/api/auth/customer/login", "client@finovexa.ai", "Client1234!")


@pytest.fixture()
def developer(client):
    return _login(client, "/api/auth/developer/login", "developer@finovexa.ai", "Developer1234!")


def _new_enquiry(client, headers):
    items = client.get("/api/accounting/senior/enquiries", headers=headers).json()["items"]
    return next(row for row in items if row["status"] == "new")


def _tiers(client):
    body = client.get("/api/accounting/public/pricing").json()
    return {row["key"]: row for row in body["software"]["tiers"]}


def test_public_pricing_uses_exact_configured_prices(client):
    response = client.get("/api/accounting/public/pricing")
    assert response.status_code == 200, response.text
    body = response.json()

    tiers = {row["key"]: row for row in body["software"]["tiers"]}
    assert tiers["up_to_8_lakh"]["monthly_price"] == 300
    assert tiers["8_to_15_lakh"]["monthly_price"] == 500
    assert tiers["15_to_30_lakh"]["monthly_price"] == 800
    assert tiers["30_to_50_lakh"]["monthly_price"] == 1500
    assert tiers["50_lakh_to_1_crore"]["monthly_price"] == 2500
    assert tiers["above_1_crore"]["monthly_price"] == 4000
    # No discount is invented or applied by default.
    assert body["software"]["annual_discount_percent"] == 0
    assert tiers["above_1_crore"]["annual_price"] == 48000
    assert tiers["above_1_crore"]["annual_effective_monthly"] == 4000

    itr = {row["key"]: row for row in body["itr"]["items"]}
    assert itr["itr_1"]["price_min"] == 999
    assert itr["itr_2_itr_4"]["price_min"] == 1999
    assert itr["itr_3"]["price_min"] == 3999
    assert itr["complex_business_itr"]["price_min"] == 5000
    assert itr["complex_business_itr"]["price_max"] == 12000

    # Add-ons without an approved amount are never shown as a fixed public price.
    assert body["addons"]
    assert all(row["amount"] is None for row in body["addons"])
    assert body["accounting"]["benchmark_percent"] == 2
    disclosures = " ".join(body["disclosures"]).lower()
    assert "separate" in disclosures
    assert "senior accountant" in disclosures
    assert "does not charge" in disclosures


def test_estimate_is_indicative_only_and_tiered(client):
    response = client.get(
        "/api/accounting/public/quotation-estimate", params={"annual_turnover": "3500000"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["indicative_annual_fee"] == 70000
    assert body["indicative_monthly_equivalent"] == 5833.33
    assert body["software_tier"]["key"] == "30_to_50_lakh"
    assert "not a final fee" in body["note"]
    assert body["validity_days"] == 15

    boundary = client.get(
        "/api/accounting/public/quotation-estimate", params={"annual_turnover": "800000"}
    ).json()
    assert boundary["software_tier"]["key"] == "up_to_8_lakh"
    above = client.get(
        "/api/accounting/public/quotation-estimate", params={"annual_turnover": "800001"}
    ).json()
    assert above["software_tier"]["key"] == "8_to_15_lakh"


def test_quotation_totals_discount_and_payment_frequency(client, senior, junior):
    enquiry = _new_enquiry(client, senior["headers"])
    created = client.post(
        "/api/accounting/senior/quotations",
        headers=senior["headers"],
        json={
            "enquiry_id": enquiry["id"],
            "annual_turnover": "3500000",
            "line_items": [
                {"label": "Bookkeeping", "service": "bookkeeping", "amount": "100000"},
                {"label": "Payroll management", "kind": "addon", "amount": "50000"},
            ],
            "discount_type": "percent",
            "discount_value": "10",
            "payment_frequency": "quarterly",
        },
    )
    assert created.status_code == 201, created.text
    quotation = created.json()
    assert quotation["subtotal_annual"] == 150000
    assert quotation["discount_amount"] == 15000
    assert quotation["total_annual"] == 135000
    assert quotation["monthly_equivalent"] == 11250
    assert quotation["amount"] == 33750  # per quarter
    assert quotation["benchmark_annual"] == 70000
    assert quotation["tax_rate_percent"] == 18

    updated = client.patch(
        f"/api/accounting/senior/quotations/{quotation['id']}",
        headers=senior["headers"],
        json={
            "discount_type": "amount",
            "discount_value": "20000",
            "payment_frequency": "annual",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["total_annual"] == 130000
    assert body["amount"] == 130000
    assert body["monthly_equivalent"] == 10833.33

    for method, path in (
        ("patch", f"/api/accounting/senior/quotations/{quotation['id']}"),
        ("post", f"/api/accounting/senior/quotations/{quotation['id']}/approve"),
    ):
        response = getattr(client, method)(path, headers=junior["headers"], json={})
        assert response.status_code == 403, response.text


def test_full_lifecycle_sends_pdf_and_customer_accepts_without_charging(client, senior, customer):
    overview = client.get("/api/accounting/customer/overview", headers=customer["headers"])
    assert overview.status_code == 200, overview.text
    client_id = overview.json()["client"]["id"]
    created = client.post(
        "/api/accounting/senior/quotations",
        headers=senior["headers"],
        json={
            "client_id": client_id,
            "annual_turnover": "20000000",
            "line_items": [
                {"label": "Bookkeeping", "service": "bookkeeping", "amount": "72000"},
                {"label": "GST accounting", "service": "gst_accounting", "amount": "48000"},
            ],
            "payment_frequency": "monthly",
        },
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["status"] == "draft"
    early_pdf = client.get(
        f"/api/accounting/customer/quotations/{draft['id']}/pdf", headers=customer["headers"]
    )
    assert early_pdf.status_code == 409

    approved = client.post(
        f"/api/accounting/senior/quotations/{draft['id']}/approve", headers=senior["headers"]
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    edit_after_approval = client.patch(
        f"/api/accounting/senior/quotations/{draft['id']}",
        headers=senior["headers"],
        json={"discount_type": "percent", "discount_value": "5"},
    )
    assert edit_after_approval.status_code == 200, edit_after_approval.text
    # Editing an approved quote invalidates the approval and returns it to draft.
    assert edit_after_approval.json()["status"] == "draft"
    assert edit_after_approval.json()["approved_at"] is None

    assert (
        client.post(
            f"/api/accounting/senior/quotations/{draft['id']}/approve",
            headers=senior["headers"],
        ).status_code
        == 200
    )
    sent = client.post(
        f"/api/accounting/senior/quotations/{draft['id']}/send", headers=senior["headers"]
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert sent.json()["sent_at"]

    listing = client.get("/api/accounting/customer/quotations", headers=customer["headers"])
    assert listing.status_code == 200, listing.text
    assert all(row["status"] in ("sent", "accepted", "declined") for row in listing.json()["items"])
    assert any(
        row["number"] == draft["number"] and row["status"] == "sent"
        for row in listing.json()["items"]
    )

    pdf = client.get(
        f"/api/accounting/customer/quotations/{draft['id']}/pdf", headers=customer["headers"]
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    staff_pdf = client.get(
        f"/api/accounting/senior/quotations/{draft['id']}/pdf", headers=senior["headers"]
    )
    assert staff_pdf.status_code == 200
    assert staff_pdf.content.startswith(b"%PDF")

    with SessionLocal() as db:
        payments_before = db.query(Payment).count()
    decision = client.post(
        f"/api/accounting/customer/quotations/{draft['id']}/decision",
        headers=customer["headers"],
        json={"decision": "accepted", "note": "Approved for the current financial year."},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "accepted"
    with SessionLocal() as db:
        assert db.query(Payment).count() == payments_before
        assert (
            db.query(AuditEvent)
            .filter(AuditEvent.action == "accounting.quotation_accepted")
            .count()
            >= 1
        )

    duplicate = client.post(
        f"/api/accounting/customer/quotations/{draft['id']}/decision",
        headers=customer["headers"],
        json={"decision": "declined"},
    )
    assert duplicate.status_code == 409


def test_customer_request_stays_invisible_until_senior_sends(client, senior, customer):
    requested = client.post(
        "/api/accounting/customer/quotation-requests",
        headers=customer["headers"],
        json={
            "business_name": "Meridian Traders",
            "contact_name": "Darshan Neve",
            "email": "client@finovexa.ai",
            "business_type": "Private Limited",
            "turnover_range": "INR 1 crore - 5 crore",
            "gst_status": "Registered - regular",
            "services": ["bookkeeping", "gst_accounting"],
            "monthly_transactions": 200,
            "annual_turnover": "20000000",
            "bank_accounts": 2,
            "payroll_required": True,
            "inventory_required": False,
            "financial_year": "2026-27",
            "requirements": "Additional GST branch reconciliation.",
            "consent": True,
        },
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["estimate"]["indicative_annual_fee"] == 400000
    assert requested.json()["estimate"]["indicative_monthly_equivalent"] == 33333.33

    requests = client.get(
        "/api/accounting/customer/quotation-requests", headers=customer["headers"]
    ).json()["items"]
    enquiry = next(row for row in requests if row["reference"] == requested.json()["reference"])
    assert enquiry["status"] == "new"
    assert enquiry["benchmark_annual"] == 400000

    created = client.post(
        "/api/accounting/senior/quotations",
        headers=senior["headers"],
        json={
            "enquiry_id": enquiry["id"],
            "line_items": [{"label": "GST branch reconciliation", "amount": "48000"}],
            "payment_frequency": "monthly",
        },
    )
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]

    visible = client.get("/api/accounting/customer/quotations", headers=customer["headers"]).json()
    assert draft_id not in {row["id"] for row in visible["items"]}
    hidden_pdf = client.get(
        f"/api/accounting/customer/quotations/{draft_id}/pdf", headers=customer["headers"]
    )
    # A draft addressed to this customer must not be downloadable before approval and sending.
    assert hidden_pdf.status_code == 409

    other = client.post(
        "/api/auth/register",
        json={
            "email": "stranger@example.com",
            "password": "Stranger1234!",
            "full_name": "Stranger",
            "business_name": "Stranger Co",
            "currency": "INR",
        },
    )
    assert other.status_code == 201
    stranger = {
        "headers": {"Authorization": f"Bearer {other.json()['access_token']}"}
    }
    forbidden = client.get(
        f"/api/accounting/customer/quotations/{draft_id}/pdf", headers=stranger["headers"]
    )
    assert forbidden.status_code in (403, 401)


def test_expired_quotation_is_read_only_for_customer(client, senior, customer):
    listing = client.get("/api/accounting/customer/quotations", headers=customer["headers"])
    assert listing.status_code == 200
    target = next(row for row in listing.json()["items"] if row["status"] == "sent")
    with SessionLocal() as db:
        quotation = db.get(AccountingQuotation, target["id"])
        quotation.valid_until = date.today() - timedelta(days=1)
        db.commit()

    refreshed = client.get("/api/accounting/customer/quotations", headers=customer["headers"])
    statuses = {row["id"]: row["status"] for row in refreshed.json()["items"]}
    assert statuses[target["id"]] == "expired"

    decision = client.post(
        f"/api/accounting/customer/quotations/{target['id']}/decision",
        headers=customer["headers"],
        json={"decision": "accepted"},
    )
    assert decision.status_code == 409
    assert "expired" in decision.json()["detail"].lower()


def test_reject_requires_note_and_blocks_sending(client, senior):
    workspace = client.get(
        "/api/accounting/senior/quotation-workspace", headers=senior["headers"]
    ).json()
    draft = next(row for row in workspace["quotations"] if row["status"] == "draft")
    missing_note = client.post(
        f"/api/accounting/senior/quotations/{draft['id']}/reject",
        headers=senior["headers"],
        json={"note": ""},
    )
    assert missing_note.status_code == 422
    rejected = client.post(
        f"/api/accounting/senior/quotations/{draft['id']}/reject",
        headers=senior["headers"],
        json={"note": "Turnover evidence was not provided."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejection_note"]
    send = client.post(
        f"/api/accounting/senior/quotations/{draft['id']}/send", headers=senior["headers"]
    )
    assert send.status_code == 409


def test_developer_manages_prices_with_history_and_public_effect(client, developer, senior):
    forbidden = client.get("/api/developer/pricing", headers=senior["headers"])
    assert forbidden.status_code in (401, 403)

    config = client.get("/api/developer/pricing", headers=developer["headers"])
    assert config.status_code == 200, config.text
    tiers = {row["key"]: row for row in config.json()["software_tiers"]}
    itr = {row["key"]: row for row in config.json()["itr_prices"]}

    updated_tier = client.put(
        f"/api/developer/pricing/software/{tiers['up_to_8_lakh']['id']}",
        headers=developer["headers"],
        json={"monthly_price": "350"},
    )
    assert updated_tier.status_code == 200, updated_tier.text

    updated_rules = client.put(
        "/api/developer/pricing/rules",
        headers=developer["headers"],
        json={"annual_discount_percent": "10", "benchmark_percent": "2.5"},
    )
    assert updated_rules.status_code == 200, updated_rules.text
    assert updated_rules.json()["settings"]["annual_discount_percent"] == 10

    updated_itr = client.put(
        f"/api/developer/pricing/itr/{itr['itr_1']['id']}",
        headers=developer["headers"],
        json={"price_min": "1099"},
    )
    assert updated_itr.status_code == 200, updated_itr.text

    addon = client.post(
        "/api/developer/pricing/addons",
        headers=developer["headers"],
        json={
            "key": "bookkeeping_cleanup",
            "label": "Bookkeeping cleanup",
            "description": "One-time cleanup of an unreconciled ledger.",
            "amount": "5000",
            "cadence": "one_time",
        },
    )
    assert addon.status_code == 201, addon.text
    patched = client.patch(
        f"/api/developer/pricing/addons/{addon.json()['addon']['id']}",
        headers=developer["headers"],
        json={"amount": "6500", "is_active": False},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["addon"]["amount"] == 6500
    assert patched.json()["addon"]["is_active"] is False

    public = client.get("/api/accounting/public/pricing").json()
    public_tiers = {row["key"]: row for row in public["software"]["tiers"]}
    assert public_tiers["up_to_8_lakh"]["monthly_price"] == 350
    assert public_tiers["up_to_8_lakh"]["annual_price"] == 3780
    assert public_tiers["up_to_8_lakh"]["annual_effective_monthly"] == 315
    public_itr = {row["key"]: row for row in public["itr"]["items"]}
    assert public_itr["itr_1"]["price_min"] == 1099
    assert all(row["key"] != "bookkeeping_cleanup" for row in public["addons"])

    estimate = client.get(
        "/api/accounting/public/quotation-estimate", params={"annual_turnover": "3500000"}
    ).json()
    assert estimate["indicative_annual_fee"] == 87500

    history = client.get(
        "/api/developer/pricing/history", headers=developer["headers"]
    ).json()["items"]
    pairs = {(row["entity_key"], row["field"], row["new_value"]) for row in history}
    assert ("up_to_8_lakh", "monthly_price", "350") in pairs
    assert ("default", "annual_discount_percent", "10") in pairs
    assert ("itr_1", "price_min", "1099") in pairs
    assert ("bookkeeping_cleanup", "amount", "6500") in pairs

    with SessionLocal() as db:
        actions = {
            row[0]
            for row in db.query(AuditEvent.action)
            .filter(AuditEvent.action.like("developer.%"))
            .all()
            if "pric" in row[0]
        }
    assert "developer.software_price_updated" in actions
    assert "developer.itr_price_updated" in actions
    assert "developer.pricing_rules_updated" in actions
