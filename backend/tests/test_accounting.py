from __future__ import annotations

import base64
from datetime import date, timedelta

import pytest


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


def _clients(client, headers):
    response = client.get("/api/accounting/senior/clients", headers=headers)
    assert response.status_code == 200, response.text
    return {row["business_name"]: row for row in response.json()["items"]}


def _data_url(text: str, mime: str = "text/csv") -> str:
    return f"data:{mime};base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_public_catalogue_and_enquiry(client):
    response = client.get("/api/accounting/public/services")
    assert response.status_code == 200
    body = response.json()
    assert len(body["services"]) == 8
    assert all("price" not in service for service in body["services"])
    assert "quoted" in body["process"][2].lower() or "quotation" in body["process"][2].lower()
    assert "GSTN" in body["filing_note"]

    payload = {
        "business_name": "Harbour Textiles",
        "contact_name": "Meera Joshi",
        "email": "meera@harbour.example.com",
        "business_type": "Partnership",
        "turnover_range": "INR 20 lakh - 1 crore",
        "gst_status": "Registered - regular",
        "services": ["bookkeeping", "gst_accounting"],
        "monthly_transactions": 180,
        "requirements": "Monthly books and GST working papers.",
        "consent": True,
    }
    response = client.post("/api/accounting/public/enquiries", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["reference"].startswith("ACC-ENQ-")
    assert body["status"] == "new"

    missing_consent = client.post(
        "/api/accounting/public/enquiries", json={**payload, "email": "second@harbour.example.com", "consent": False}
    )
    assert missing_consent.status_code == 422

    honeypot = client.post(
        "/api/accounting/public/enquiries",
        json={**payload, "email": "bot@harbour.example.com", "website": "http://spam.example"},
    )
    assert honeypot.status_code == 422


def test_role_boundaries(client, demo, senior, junior, customer):
    assert client.get("/api/accounting/senior/overview", headers=demo["headers"]).status_code == 403
    assert client.get("/api/accounting/senior/overview", headers=junior["headers"]).status_code == 403
    assert client.get("/api/accounting/senior/overview", headers=customer["headers"]).status_code == 403
    assert client.get("/api/accounting/senior/overview", headers=senior["headers"]).status_code == 200

    assert client.get("/api/accounting/junior/workspace", headers=senior["headers"]).status_code == 403
    assert client.get("/api/accounting/junior/workspace", headers=junior["headers"]).status_code == 200

    assert client.get("/api/accounting/customer/overview", headers=senior["headers"]).status_code == 403
    assert client.get("/api/accounting/customer/overview", headers=customer["headers"]).status_code == 200

    # Existing owner features still work alongside the new portal.
    assert client.get("/api/dashboard", headers=demo["headers"]).status_code == 200

    me = client.get("/api/auth/me", headers=senior["headers"]).json()
    assert me["accounting"]["portal"] == "accountant"
    assert me["user"]["role"] == "senior_accountant"

    me = client.get("/api/auth/me", headers=customer["headers"]).json()
    assert me["accounting"]["portal"] == "customer"
    assert me["accounting"]["client"]["business_name"] == "Meridian Traders"


def test_senior_overview_and_client_detail(client, senior):
    response = client.get("/api/accounting/senior/overview", headers=senior["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["clients"]["total"] == 3
    assert body["clients"]["active"] == 3
    assert body["enquiries"]["new"] >= 1
    assert body["tasks"]["submitted"] >= 1
    assert len(body["monthly_series"]) == 6
    assert body["workload"][0]["name"]
    assert body["recent_activity"]

    clients = _clients(client, senior["headers"])
    meridian = clients["Meridian Traders"]
    dn_ventures = clients["DN Ventures Pvt. Ltd"]
    assert dn_ventures["business_profile_id"]
    assert dn_ventures["linked_business"]["business_name"] == "DN Ventures Pvt. Ltd"
    detail = client.get(f"/api/accounting/senior/clients/{meridian['id']}", headers=senior["headers"])
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["client"]["pan_last4"] == "234A"
    assert "pan" not in {key for key in body["client"] if key != "pan_last4"}
    assert body["vouchers"]["sales"] >= 230000
    assert len(body["tasks"]) == 4
    assert body["invoices"][0]["paid_amount"] > 0


def test_quotation_and_onboarding_flow(client, senior, junior):
    enquiries = client.get("/api/accounting/senior/enquiries", headers=senior["headers"]).json()["items"]
    target = next(row for row in enquiries if row["status"] == "new")
    forbidden = client.post(
        "/api/accounting/senior/quotations",
        headers=junior["headers"],
        json={
            "enquiry_id": target["id"],
            "line_items": [{"label": "Bookkeeping", "service": "bookkeeping", "amount": "60000"}],
        },
    )
    assert forbidden.status_code == 403
    response = client.post(
        "/api/accounting/senior/quotations",
        headers=senior["headers"],
        json={
            "enquiry_id": target["id"],
            "annual_turnover": "3500000",
            "line_items": [
                {
                    "label": "Bookkeeping",
                    "service": "bookkeeping",
                    "description": "Monthly bookkeeping.",
                    "amount": "60000",
                },
                {
                    "label": "GST accounting",
                    "service": "gst_accounting",
                    "amount": "24000",
                },
            ],
            "payment_frequency": "monthly",
        },
    )
    assert response.status_code == 201, response.text
    quotation = response.json()
    assert quotation["number"].startswith("ACC-QT-")
    assert quotation["status"] == "draft"
    assert quotation["total_annual"] == 84000
    assert quotation["monthly_equivalent"] == 7000
    assert quotation["benchmark_annual"] == 70000

    refreshed = client.get("/api/accounting/senior/enquiries", headers=senior["headers"]).json()["items"]
    assert next(row for row in refreshed if row["id"] == target["id"])["status"] == "contacted"

    early_decision = client.post(
        f"/api/accounting/senior/quotations/{quotation['id']}/decision",
        headers=senior["headers"],
        json={"decision": "accepted", "note": "Should not work before sending."},
    )
    assert early_decision.status_code == 409

    approved = client.post(
        f"/api/accounting/senior/quotations/{quotation['id']}/approve",
        headers=senior["headers"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    sent = client.post(
        f"/api/accounting/senior/quotations/{quotation['id']}/send",
        headers=senior["headers"],
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    refreshed = client.get("/api/accounting/senior/enquiries", headers=senior["headers"]).json()["items"]
    assert next(row for row in refreshed if row["id"] == target["id"])["status"] == "quoted"

    decision = client.post(
        f"/api/accounting/senior/quotations/{quotation['id']}/decision",
        headers=senior["headers"],
        json={"decision": "accepted", "note": "Confirmed by email."},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "accepted"

    response = client.post(
        "/api/accounting/senior/clients",
        headers=senior["headers"],
        json={
            "enquiry_id": target["id"],
            "quotation_id": quotation["id"],
            "business_name": target["business_name"],
            "contact_name": target["contact_name"],
            "email": target["email"],
            "business_type": target["business_type"],
            "turnover_range": target["turnover_range"],
            "gst_status": target["gst_status"],
            "financial_year": "2026-27",
            "service_package": "Bookkeeping",
            "portal_password": "PortalPass123!",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["client"]["code"].startswith("ACC-")
    assert body["client"]["status"] == "onboarding"
    assert body["portal_access"] == "created"

    login = client.post(
        "/api/auth/customer/login",
        json={"email": target["email"], "password": "PortalPass123!"},
    )
    assert login.status_code == 200, login.text
    overview = client.get(
        "/api/accounting/customer/overview",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert overview.status_code == 200
    assert overview.json()["client"]["business_name"] == target["business_name"]

    duplicate = client.post(
        "/api/accounting/senior/clients",
        headers=senior["headers"],
        json={
            "business_name": "Duplicate Co",
            "contact_name": "Someone",
            "email": target["email"],
            "business_type": "LLP",
            "turnover_range": "INR 20 lakh - 1 crore",
            "gst_status": "Not registered",
            "financial_year": "2026-27",
            "service_package": "Bookkeeping",
        },
    )
    assert duplicate.status_code == 409


def test_junior_isolation_and_task_review(client, senior, junior):
    junior_clients = client.get("/api/accounting/junior/clients", headers=junior["headers"]).json()["items"]
    assert {row["business_name"] for row in junior_clients} == {
        "DN Ventures Pvt. Ltd",
        "Meridian Traders",
    }

    clients = _clients(client, senior["headers"])
    sunrise = clients["Sunrise Interiors"]
    forbidden = client.get(f"/api/accounting/junior/clients/{sunrise['id']}", headers=junior["headers"])
    assert forbidden.status_code == 403

    voucher = client.post(
        "/api/accounting/vouchers",
        headers=junior["headers"],
        json={
            "client_id": sunrise["id"],
            "voucher_type": "sale",
            "number": "SI-TEST-1",
            "voucher_date": date.today().isoformat(),
            "party_name": "Forbidden Party",
            "ledger_name": "Sales",
            "taxable_value": "1000.00",
            "gst_rate": "18.00",
        },
    )
    assert voucher.status_code == 403

    task = client.post(
        "/api/accounting/senior/tasks",
        headers=senior["headers"],
        json={
            "client_id": clients["Meridian Traders"]["id"],
            "title": "Trial balance review",
            "service_type": "bookkeeping",
            "priority": "high",
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
            "assigned_to_user_id": junior["user"]["id"],
        },
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    assert task.json()["status"] == "assigned"

    submitted = client.post(
        f"/api/accounting/junior/tasks/{task_id}/submit",
        headers=junior["headers"],
        json={"summary": "Trial balance checked against the ledger.", "progress": 100},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    changes = client.post(
        f"/api/accounting/senior/tasks/{task_id}/review",
        headers=senior["headers"],
        json={"decision": "changes_requested", "notes": "Attach the trial balance."},
    )
    assert changes.status_code == 200
    assert changes.json()["status"] == "changes_requested"

    client.post(
        f"/api/accounting/junior/tasks/{task_id}/submit",
        headers=junior["headers"],
        json={"summary": "Trial balance attached and cross-checked.", "progress": 100},
    )
    approved = client.post(
        f"/api/accounting/senior/tasks/{task_id}/review",
        headers=senior["headers"],
        json={"decision": "approve", "notes": "Approved after review."},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    again = client.post(
        f"/api/accounting/senior/tasks/{task_id}/review",
        headers=senior["headers"],
        json={"decision": "approve"},
    )
    assert again.status_code == 409

    notifications = client.get("/api/accounting/notifications", headers=junior["headers"]).json()
    assert notifications["unread_count"] >= 1


def test_document_permissions_and_isolation(client, senior, junior, customer):
    clients = _clients(client, senior["headers"])
    meridian = clients["Meridian Traders"]
    internal = client.post(
        "/api/accounting/documents",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "filename": "working-paper.csv",
            "title": "Internal working paper",
            "category": "other",
            "data_url": _data_url("ledger,total\ncash,1000\n"),
        },
    )
    assert internal.status_code == 201, internal.text
    internal_id = internal.json()["id"]
    assert internal.json()["visibility"] == "internal"

    blocked = client.get(
        f"/api/accounting/documents/{internal_id}/file", headers=customer["headers"]
    )
    assert blocked.status_code == 403

    upload = client.post(
        "/api/accounting/customer/documents",
        headers=customer["headers"],
        json={
            "client_id": meridian["id"],
            "filename": "purchase-bill.csv",
            "title": "Purchase bill",
            "category": "purchase_bill",
            "data_url": _data_url("bill,total\nb1,1200\n"),
        },
    )
    assert upload.status_code == 201, upload.text
    shared_id = upload.json()["id"]
    download = client.get(f"/api/accounting/documents/{shared_id}/file", headers=customer["headers"])
    assert download.status_code == 200
    assert download.content.startswith(b"bill,total")

    staff_view = client.get(f"/api/accounting/documents/{shared_id}/file", headers=senior["headers"])
    assert staff_view.status_code == 200

    # A second client must never reach the first client's document.
    created = client.post(
        "/api/accounting/senior/clients",
        headers=senior["headers"],
        json={
            "business_name": "Other Client",
            "contact_name": "Other Person",
            "email": "other@client.example.com",
            "business_type": "Proprietorship",
            "turnover_range": "INR 20 lakh - 1 crore",
            "gst_status": "Not registered",
            "financial_year": "2026-27",
            "service_package": "Bookkeeping",
            "portal_password": "OtherPass123!",
        },
    )
    assert created.status_code == 201, created.text
    other_login = client.post(
        "/api/auth/customer/login",
        json={"email": "other@client.example.com", "password": "OtherPass123!"},
    )
    assert other_login.status_code == 200
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    assert (
        client.get(f"/api/accounting/documents/{shared_id}/file", headers=other_headers).status_code
        == 403
    )
    overview = client.get("/api/accounting/customer/overview", headers=other_headers).json()
    assert overview["client"]["business_name"] == "Other Client"
    assert overview["documents"] == []

    wrong_client = client.post(
        "/api/accounting/customer/documents",
        headers=other_headers,
        json={
            "client_id": meridian["id"],
            "filename": "sneaky.csv",
            "data_url": _data_url("account,amount\nsneaky,1234.00\n"),
        },
    )
    assert wrong_client.status_code == 403


def test_gst_working_papers_and_reports(client, senior, junior, customer):
    clients = _clients(client, senior["headers"])
    meridian = clients["Meridian Traders"]
    period = f"{date.today():%Y-%m}"
    response = client.post(
        "/api/accounting/gst/prepare",
        headers=junior["headers"],
        json={"client_id": meridian["id"], "period": period},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filing_status"] == "working_paper_only"
    assert "GSTN" in body["filing_note"]
    assert float(body["summary"]["output_tax"]) == pytest.approx(26100.0)
    assert float(body["summary"]["itc_tax"]) == pytest.approx(2160.0)
    assert float(body["summary"]["net_payable"]) == pytest.approx(23940.0)
    assert body["gstr1"]["total_invoices"] == 2
    assert all(row["gstin"] for row in body["gstr1"]["b2b"])

    draft = client.post(
        "/api/accounting/reports",
        headers=junior["headers"],
        json={"client_id": meridian["id"], "report_type": "gstr1", "financial_year": "2026-27", "period": period},
    )
    assert draft.status_code == 201, draft.text
    report = draft.json()
    assert report["status"] == "draft"
    assert report["payload"]["filing_status"] == "working_paper_only"

    hidden = client.get(f"/api/accounting/customer/documents", headers=customer["headers"])
    assert hidden.status_code == 200

    approved = client.post(
        f"/api/accounting/senior/reports/{report['id']}/review",
        headers=senior["headers"],
        json={"decision": "approve", "notes": "Working paper verified against the register."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    delivered = client.post(
        f"/api/accounting/senior/reports/{report['id']}/deliver",
        headers=senior["headers"],
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "delivered"

    overview = client.get("/api/accounting/customer/overview", headers=customer["headers"]).json()
    assert any(row["id"] == report["id"] for row in overview["reports"])

    monthly = client.post(
        "/api/accounting/reports",
        headers=junior["headers"],
        json={"client_id": meridian["id"], "report_type": "monthly_summary", "financial_year": "2026-27", "period": period},
    )
    assert monthly.status_code == 201
    payload = monthly.json()["payload"]
    assert payload["generated_from"] == "recorded_vouchers"
    assert float(payload["revenue"]) == pytest.approx(145000.0)
    assert payload["observations"]


def test_bank_reconciliation_and_tally(client, senior, junior):
    clients = _clients(client, senior["headers"])
    meridian = clients["Meridian Traders"]
    month = date.today().replace(day=1)
    csv_text = (
        "Date,Description,Reference,Debit,Credit\n"
        f"{month.isoformat()},NEFT CR VERTEX INTERIORS,NEFT-1,,118000.00\n"
        f"{(month + timedelta(days=1)).isoformat()},UPI DR ERGO WHOLESALE,UPI-2,14160.00,\n"
        f"{(month + timedelta(days=2)).isoformat()},IMPS CR UNKNOWN PARTY,IMPS-3,,50000.00\n"
    )
    response = client.post(
        "/api/accounting/bank/import",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "filename": "statement.csv",
            "data_url": _data_url(csv_text),
        },
    )
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["row_count"] == 3
    scores = [txn["match_score"] for txn in record["transactions"]]
    assert scores[0] == 95
    assert scores[1] == 95
    assert scores[2] == 40

    first = record["transactions"][0]
    confirmed = client.post(
        f"/api/accounting/bank/transactions/{first['id']}/match",
        headers=junior["headers"],
        json={"voucher_id": first["matched_voucher_id"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "matched"

    tally_csv = (
        "Voucher Type,Voucher Number,Date,Party Name,GSTIN,Ledger,Taxable Value,GST Rate,IGST\n"
        f"Sale,TAL-1,{(month + timedelta(days=3)).isoformat()},Tally Customer,27AAECM1234A1Z5,Sales,10000,18,no\n"
        f"Purchase,TAL-2,{(month + timedelta(days=4)).isoformat()},Tally Supplier,27AABCE2222D1Z7,Purchases,4000,18,no\n"
        f"Sale,TAL-1,{(month + timedelta(days=3)).isoformat()},Tally Customer,27AAECM1234A1Z5,Sales,10000,18,no\n"
        "Sale,,not-a-date,,,Sales,abc,50,no\n"
    )
    imported = client.post(
        "/api/accounting/tally/import",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "filename": "tally.csv",
            "data_url": _data_url(tally_csv),
        },
    )
    assert imported.status_code == 201, imported.text
    batch = imported.json()
    assert batch["row_count"] == 4
    assert batch["valid_count"] == 2
    assert batch["duplicate_count"] == 1
    assert batch["error_count"] == 1
    assert batch["details"]["errors"][0]["row"] == 5

    export = client.post(
        "/api/accounting/tally/export",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "from_date": month.isoformat(),
            "to_date": (month + timedelta(days=10)).isoformat(),
            "voucher_type": "all",
        },
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("text/csv")
    assert "Voucher Number" in export.text
    assert "TAL-1" in export.text


def test_bill_reader_and_voucher_dedupe(client, junior):
    junior_clients = client.get("/api/accounting/junior/clients", headers=junior["headers"]).json()["items"]
    meridian = junior_clients[0]

    bill = (
        "Tax Invoice No: HB-2291\n"
        "Invoice Date: 12-10-2026\n"
        "GSTIN: 27AAECM1234A1Z5\n"
        "Party: Ergo Wholesale\n"
        "Taxable Value: 1000.00\n"
        "IGST: 180.00\n"
        "Grand Total: 1180.00\n"
        "Narration: office stationery purchase\n"
    )
    response = client.post(
        "/api/accounting/bills/extract",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "filename": "bill.csv",
            "data_url": _data_url(bill),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"] is False
    assert body["requires_human_verification"] is True
    assert body["fields"]["invoice_number"] == "HB-2291"
    assert body["fields"]["party_gstin"] == "27AAECM1234A1Z5"
    assert body["fields"]["invoice_date"] == "2026-10-12"
    assert body["fields"]["gst_rate"] == 18.0
    assert body["fields"]["suggested_ledger"] == "Office expenses"

    voucher = {
        "client_id": meridian["id"],
        "voucher_type": "purchase",
        "number": "HB-2291",
        "voucher_date": "2026-10-12",
        "party_name": "Ergo Wholesale",
        "party_gstin": "27AAECM1234A1Z5",
        "ledger_name": "Office expenses",
        "taxable_value": "1000.00",
        "gst_rate": "18.00",
    }
    first = client.post("/api/accounting/vouchers", headers=junior["headers"], json=voucher)
    assert first.status_code == 201, first.text
    assert float(first.json()["cgst_amount"]) == 90.0
    assert float(first.json()["sgst_amount"]) == 90.0
    assert float(first.json()["total_amount"]) == 1180.0

    duplicate = client.post("/api/accounting/vouchers", headers=junior["headers"], json=voucher)
    assert duplicate.status_code == 409

    bulk = client.post(
        "/api/accounting/vouchers/bulk",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "rows": [
                {**voucher, "number": "HB-2292", "voucher_date": "2026-10-13", "inter_state": True},
                {**voucher, "number": "HB-2292", "voucher_date": "2026-10-13", "inter_state": True},
            ],
        },
    )
    assert bulk.status_code == 201, bulk.text
    body = bulk.json()
    assert len(body["created"]) == 1
    assert body["duplicate_numbers"] == ["HB-2292"]
    assert float(body["created"][0]["igst_amount"]) == 180.0


def test_invoice_payments_and_customer_portal(client, senior, customer):
    clients = _clients(client, senior["headers"])
    meridian = clients["Meridian Traders"]
    created = client.post(
        "/api/accounting/senior/invoices",
        headers=senior["headers"],
        json={
            "client_id": meridian["id"],
            "issue_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=15)).isoformat(),
            "period_label": "Retainer",
            "subtotal": "10000.00",
            "tax_rate": "18.00",
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()
    assert float(invoice["total_amount"]) == 11800.0

    partial = client.post(
        f"/api/accounting/senior/invoices/{invoice['id']}/payments",
        headers=senior["headers"],
        json={"amount": "5000.00", "method": "bank", "received_on": date.today().isoformat()},
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["status"] == "part_paid"
    assert float(partial.json()["outstanding_amount"]) == 6800.0

    over = client.post(
        f"/api/accounting/senior/invoices/{invoice['id']}/payments",
        headers=senior["headers"],
        json={"amount": "99999.00", "method": "bank", "received_on": date.today().isoformat()},
    )
    assert over.status_code == 422

    overview = client.get("/api/accounting/customer/overview", headers=customer["headers"]).json()
    assert overview["counts"]["outstanding_invoices"] >= 1
    assert any(row["id"] == invoice["id"] for row in overview["invoices"])
    assert overview["messages"]

    message = client.post(
        "/api/accounting/customer/messages",
        headers=customer["headers"],
        json={"body": "Please confirm the GST working paper status."},
    )
    assert message.status_code == 201, message.text
    assert message.json()["author_role"] == "customer"

    staff_messages = client.get(
        f"/api/accounting/messages?client_id={meridian['id']}", headers=senior["headers"]
    )
    assert staff_messages.status_code == 200
    assert any(row["body"].startswith("Please confirm") for row in staff_messages.json()["items"])

    request = client.post(
        "/api/accounting/document-requests",
        headers=senior["headers"],
        json={"client_id": meridian["id"], "title": "Bank statement", "description": "PDF or CSV"},
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]

    fulfilled = client.post(
        "/api/accounting/customer/documents",
        headers=customer["headers"],
        json={
            "client_id": meridian["id"],
            "filename": "bank.csv",
            "category": "bank_statement",
            "request_id": request_id,
            "data_url": _data_url("date,description,debit,credit\n2026-10-01,Opening,,0\n"),
        },
    )
    assert fulfilled.status_code == 201, fulfilled.text
    requests = client.get(
        "/api/accounting/customer/document-requests", headers=customer["headers"]
    ).json()["items"]
    assert next(row for row in requests if row["id"] == request_id)["status"] == "fulfilled"


def test_audit_trail_records_accounting_actions(client, senior):
    clients = _clients(client, senior["headers"])
    meridian = clients["Meridian Traders"]
    client.post(
        "/api/accounting/senior/tasks",
        headers=senior["headers"],
        json={
            "client_id": meridian["id"],
            "title": "Audit trail check",
            "service_type": "bookkeeping",
        },
    )
    response = client.get(
        f"/api/accounting/senior/audit?client_id={meridian['id']}", headers=senior["headers"]
    )
    assert response.status_code == 200
    actions = [row["action"] for row in response.json()["items"]]
    assert "accounting.task_created" in actions
