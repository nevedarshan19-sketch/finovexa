from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from conftest import amount


def _credit_customers(client, headers, **params):
    response = client.get("/api/credit/customers", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _credit_supplier(client, headers, name="Paper Supply Co.", **overrides):
    payload = {"name": name, "payment_terms_days": 15}
    payload.update(overrides)
    response = client.post("/api/credit/suppliers", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _employee_login(client):
    response = client.post(
        "/api/auth/employee/login",
        json={"email": "employee@finovexa.ai", "password": "Employee1234!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _purchase_entry(client, headers, counterparty, amount_value, entry_date, due_date=None):
    payload = {
        "entry_type": "purchase",
        "counterparty": counterparty,
        "description": "Stock restock",
        "amount": amount_value,
        "category": "Stock",
        "entry_date": entry_date.isoformat(),
    }
    if due_date is not None:
        payload["due_date"] = due_date.isoformat()
    response = client.post("/api/employee/entries", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["entry"]


def _pick_customer_with_balance(client, headers):
    items = _credit_customers(client, headers, page_size=200)["items"]
    candidates = [row for row in items if amount(row["outstanding"]) > 0]
    assert candidates, "seed data should include an outstanding customer"
    return max(candidates, key=lambda row: amount(row["outstanding"]))


def test_customer_credit_profile_and_summary(client, demo):
    headers = demo["headers"]
    customer = _pick_customer_with_balance(client, headers)
    outstanding = amount(customer["outstanding"])
    limit = outstanding + Decimal("5000.00")

    response = client.patch(
        f"/api/credit/customers/{customer['id']}/credit",
        json={"credit_limit": str(limit), "payment_terms_days": 15},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert amount(body["credit_limit"]) == limit
    assert amount(body["available_credit"]) == Decimal("5000.00")
    assert body["payment_terms_days"] == 15
    expected_utilization = (outstanding * 100 / limit).quantize(Decimal("0.01"))
    assert amount(body["utilization_pct"]) == expected_utilization
    assert body["risk_status"] in {"normal", "watch", "overdue", "critical", "over_limit"}

    missing_date = client.patch(
        f"/api/credit/customers/{customer['id']}/credit",
        json={"opening_balance": "1000.00"},
        headers=headers,
    )
    assert missing_date.status_code == 400

    summary = client.get("/api/credit/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    data = summary.json()
    assert amount(data["total_receivables"]) >= outstanding
    assert amount(data["available_customer_credit"]) >= Decimal("5000.00")
    assert amount(data["total_payables"]) >= Decimal("0.00")
    assert data["currency"] == "INR"


def test_customer_ledger_adjustment_and_void(client, demo):
    headers = demo["headers"]
    customer = _pick_customer_with_balance(client, headers)
    before = customer["outstanding"]

    created = client.post(
        f"/api/credit/customers/{customer['id']}/adjustments",
        json={
            "customer_id": customer["id"],
            "kind": "credit_note",
            "amount": "500.00",
            "issued_on": date.today().isoformat(),
            "reason": "Goodwill credit for a short delivery",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    adjustment = created.json()
    assert adjustment["kind"] == "credit_note"
    assert adjustment["number"].startswith("CN-")

    detail = client.get(f"/api/credit/customers/{customer['id']}", headers=headers).json()
    assert amount(detail["outstanding"]) == amount(before) - Decimal("500.00")

    ledger = client.get(
        f"/api/credit/customers/{customer['id']}/ledger", headers=headers
    ).json()
    credit_rows = [row for row in ledger["rows"] if row["reference"] == adjustment["number"]]
    assert len(credit_rows) == 1
    assert amount(credit_rows[0]["credit"]) == Decimal("500.00")
    assert amount(ledger["closing_balance"]) == amount(detail["outstanding"])

    duplicate = client.post(
        f"/api/credit/customers/{customer['id']}/adjustments",
        json={
            "customer_id": customer["id"],
            "kind": "credit_note",
            "number": adjustment["number"],
            "amount": "250.00",
            "issued_on": date.today().isoformat(),
            "reason": "Duplicate number should be rejected",
        },
        headers=headers,
    )
    assert duplicate.status_code == 409

    voided = client.post(
        f"/api/credit/adjustments/{adjustment['id']}/void",
        json={"reason": "Raised on the wrong customer"},
        headers=headers,
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"

    detail_after = client.get(f"/api/credit/customers/{customer['id']}", headers=headers).json()
    assert amount(detail_after["outstanding"]) == amount(before)
    ledger_after = client.get(
        f"/api/credit/customers/{customer['id']}/ledger", headers=headers
    ).json()
    assert all(row["reference"] != adjustment["number"] for row in ledger_after["rows"])


def test_supplier_payables_payments_and_matching(client, demo):
    headers = demo["headers"]
    employee = _employee_login(client)
    today = date.today()

    entry = _purchase_entry(
        client, employee, "Paper Supply Co.", "5000.00", today - timedelta(days=20)
    )
    assert entry["due_date"] is None

    supplier = _credit_supplier(client, headers)
    assert amount(supplier["payable"]) == Decimal("0.00")

    preview = client.post(
        "/api/credit/suppliers/match", json={"dry_run": True}, headers=headers
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert any(item["vendor"] == "Paper Supply Co." for item in preview_body["proposed"])
    assert preview_body["linked_rows"] == 0

    applied = client.post(
        "/api/credit/suppliers/match", json={"dry_run": False}, headers=headers
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["linked_rows"] >= 1

    detail = client.get(f"/api/credit/suppliers/{supplier['id']}", headers=headers).json()
    assert amount(detail["payable"]) == Decimal("5000.00")
    assert amount(detail["overdue"]) == Decimal("5000.00")
    assert detail["bills"][0]["vendor"] == "Paper Supply Co."
    bill_id = detail["bills"][0]["id"]

    later = _purchase_entry(
        client, employee, "paper supply co", "3000.00", today - timedelta(days=10)
    )
    assert later["due_date"] == (today - timedelta(days=10) + timedelta(days=15)).isoformat()
    assert later["expense_id"] is not None

    detail = client.get(f"/api/credit/suppliers/{supplier['id']}", headers=headers).json()
    assert amount(detail["payable"]) == Decimal("8000.00")
    assert amount(detail["overdue"]) == Decimal("5000.00")
    on_time_bill = next(row for row in detail["bills"] if row["id"] == later["expense_id"])
    assert on_time_bill["due_date"] == later["due_date"]

    partial = client.post(
        "/api/credit/supplier-payments",
        json={
            "supplier_id": supplier["id"],
            "expense_id": bill_id,
            "amount": "2000.00",
            "method": "neft",
            "reference": "NEFT-8842",
            "paid_on": today.isoformat(),
        },
        headers=headers,
    )
    assert partial.status_code == 201, partial.text
    payment = partial.json()

    detail = client.get(f"/api/credit/suppliers/{supplier['id']}", headers=headers).json()
    assert amount(detail["payable"]) == Decimal("6000.00")
    paid_bill = next(row for row in detail["bills"] if row["id"] == bill_id)
    assert paid_bill["payment_status"] == "partial"
    assert amount(paid_bill["outstanding"]) == Decimal("3000.00")

    overpay = client.post(
        "/api/credit/supplier-payments",
        json={
            "supplier_id": supplier["id"],
            "expense_id": bill_id,
            "amount": "4000.00",
            "method": "bank",
            "paid_on": today.isoformat(),
        },
        headers=headers,
    )
    assert overpay.status_code == 400

    voided = client.post(
        f"/api/credit/supplier-payments/{payment['id']}/void",
        json={"reason": "Bank transfer was reversed"},
        headers=headers,
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"

    detail = client.get(f"/api/credit/suppliers/{supplier['id']}", headers=headers).json()
    assert amount(detail["payable"]) == Decimal("8000.00")
    bill_after_void = next(row for row in detail["bills"] if row["id"] == bill_id)
    assert bill_after_void["payment_status"] == "unpaid"

    advance = client.post(
        "/api/credit/supplier-payments",
        json={
            "supplier_id": supplier["id"],
            "amount": "1000.00",
            "method": "upi",
            "paid_on": today.isoformat(),
            "note": "Advance for next month",
        },
        headers=headers,
    )
    assert advance.status_code == 201, advance.text
    assert advance.json()["expense_id"] is None

    detail = client.get(f"/api/credit/suppliers/{supplier['id']}", headers=headers).json()
    assert amount(detail["payable"]) == Decimal("7000.00")

    ledger = client.get(
        f"/api/credit/suppliers/{supplier['id']}/ledger", headers=headers
    ).json()
    assert amount(ledger["closing_balance"]) == Decimal("7000.00")
    assert any("advance" in row["description"].lower() for row in ledger["rows"])

    bills = client.get(
        "/api/credit/bills", headers=headers, params={"supplier_id": supplier["id"]}
    )
    assert bills.status_code == 200, bills.text
    assert bills.json()["total"] >= 2


def test_credit_alert_settings_evaluation_and_dismissal(client, demo):
    headers = demo["headers"]
    customer = _pick_customer_with_balance(client, headers)

    settings = client.get("/api/credit/alert-settings", headers=headers)
    assert settings.status_code == 200, settings.text
    body = settings.json()
    assert body["utilization_warn_pct"] == 80
    assert body["utilization_critical_pct"] == 100

    invalid = client.put(
        "/api/credit/alert-settings",
        json={
            "utilization_warn_pct": 110,
            "utilization_critical_pct": 100,
            "due_soon_days": 7,
            "overdue_escalation_days": 7,
            "supplier_due_soon_days": 7,
            "in_app_enabled": True,
            "email_enabled": False,
        },
        headers=headers,
    )
    assert invalid.status_code == 422

    updated = client.put(
        "/api/credit/alert-settings",
        json={
            "utilization_warn_pct": 70,
            "utilization_critical_pct": 90,
            "due_soon_days": 7,
            "overdue_escalation_days": 5,
            "supplier_due_soon_days": 7,
            "in_app_enabled": True,
            "email_enabled": False,
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["utilization_warn_pct"] == 70

    half_limit = max(amount(customer["outstanding"]) / 2, Decimal("1.00"))
    configured = client.patch(
        f"/api/credit/customers/{customer['id']}/credit",
        json={"credit_limit": str(half_limit.quantize(Decimal("0.01")))},
        headers=headers,
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["risk_status"] == "over_limit"

    first = client.post(
        "/api/credit/alerts/evaluate", json={"send_email": False}, headers=headers
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["created"] >= 1
    kinds = {item["kind"] for item in first_body["items"]}
    assert "utilization_critical" in kinds
    assert first_body["emails_sent"] == 0

    second = client.post(
        "/api/credit/alerts/evaluate", json={"send_email": False}, headers=headers
    )
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0
    assert second.json()["skipped"] >= 1

    open_alerts = client.get(
        "/api/credit/alerts", headers=headers, params={"status": "open"}
    )
    assert open_alerts.status_code == 200, open_alerts.text
    alerts = open_alerts.json()["items"]
    assert alerts
    dismissed = client.post(
        f"/api/credit/alerts/{alerts[0]['id']}/dismiss", headers=headers
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"

    remaining = client.get(
        "/api/credit/alerts", headers=headers, params={"status": "open"}
    ).json()["items"]
    assert all(row["id"] != alerts[0]["id"] for row in remaining)

    disabled = client.put(
        "/api/credit/alert-settings",
        json={
            "utilization_warn_pct": 70,
            "utilization_critical_pct": 90,
            "due_soon_days": 7,
            "overdue_escalation_days": 5,
            "supplier_due_soon_days": 7,
            "in_app_enabled": False,
            "email_enabled": False,
        },
        headers=headers,
    )
    assert disabled.status_code == 200, disabled.text
    paused = client.post(
        "/api/credit/alerts/evaluate", json={"send_email": False}, headers=headers
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["created"] == 0


def test_credit_reports_and_exports(client, demo):
    headers = demo["headers"]
    customer = _pick_customer_with_balance(client, headers)
    supplier = _credit_supplier(client, headers, name="Report Supplier")

    catalogue = client.get("/api/credit/reports", headers=headers)
    assert catalogue.status_code == 200, catalogue.text
    keys = {item["key"] for item in catalogue.json()["items"]}
    assert keys == {
        "customer_outstanding",
        "supplier_outstanding",
        "receivable_aging",
        "payable_aging",
        "credit_utilization",
        "overdue_payments",
        "customer_ledger",
        "supplier_ledger",
    }

    for report_key in (
        "customer_outstanding",
        "supplier_outstanding",
        "receivable_aging",
        "payable_aging",
        "credit_utilization",
        "overdue_payments",
    ):
        payload = client.get(f"/api/credit/reports/{report_key}", headers=headers)
        assert payload.status_code == 200, (report_key, payload.text)
        body = payload.json()
        assert body["key"] == report_key
        assert body["columns"]
        assert body["row_count"] == len(body["rows"])

    aging = client.get("/api/credit/reports/receivable_aging", headers=headers).json()
    assert {column["key"] for column in aging["columns"]} >= {"0-30", "31-60", "61-90", "90+"}

    customer_ledger = client.get(
        f"/api/credit/reports/customer_ledger",
        headers=headers,
        params={"customer_id": customer["id"]},
    )
    assert customer_ledger.status_code == 200, customer_ledger.text
    assert customer_ledger.json()["rows"]

    supplier_ledger = client.get(
        "/api/credit/reports/supplier_ledger",
        headers=headers,
        params={"supplier_id": supplier["id"]},
    )
    assert supplier_ledger.status_code == 200, supplier_ledger.text

    missing_entity = client.get("/api/credit/reports/customer_ledger", headers=headers)
    assert missing_entity.status_code == 400

    unknown = client.get("/api/credit/reports/not-a-report", headers=headers)
    assert unknown.status_code == 404

    xlsx = client.get(
        "/api/credit/reports/customer_outstanding/export",
        headers=headers,
        params={"format": "xlsx"},
    )
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.content[:2] == b"PK"
    assert "spreadsheetml" in xlsx.headers["content-type"]
    assert "attachment" in xlsx.headers["content-disposition"]

    from io import BytesIO

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(xlsx.content))
    sheet = workbook.active
    assert sheet.cell(row=1, column=1).value == "Customer Outstanding"
    headers_row = [cell.value for cell in sheet[5]]
    assert "Outstanding" in headers_row
    assert sheet.max_row >= 6

    pdf = client.get(
        "/api/credit/reports/payable_aging/export",
        headers=headers,
        params={"format": "pdf"},
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content[:4] == b"%PDF"

    bad_format = client.get(
        "/api/credit/reports/customer_outstanding/export",
        headers=headers,
        params={"format": "csv"},
    )
    assert bad_format.status_code == 422


def test_credit_isolation_and_role_guards(client, demo, other):
    owner_headers = demo["headers"]
    customer = _pick_customer_with_balance(client, owner_headers)
    supplier = _credit_supplier(client, owner_headers, name="Private Supplier")

    employee = _employee_login(client)
    for path in (
        "/api/credit/summary",
        "/api/credit/customers",
        "/api/credit/suppliers",
        "/api/credit/reports",
    ):
        assert client.get(path, headers=employee).status_code == 403, path

    other_headers = other["headers"]
    assert (
        client.get(f"/api/credit/customers/{customer['id']}", headers=other_headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/credit/suppliers/{supplier['id']}", headers=other_headers).status_code
        == 404
    )
    assert (
        client.get(
            "/api/credit/reports/customer_ledger",
            headers=other_headers,
            params={"customer_id": customer["id"]},
        ).status_code
        == 404
    )
    blocked_patch = client.patch(
        f"/api/credit/customers/{customer['id']}/credit",
        json={"credit_limit": "1.00"},
        headers=other_headers,
    )
    assert blocked_patch.status_code == 404

    own_summary = client.get("/api/credit/summary", headers=other_headers)
    assert own_summary.status_code == 200, own_summary.text
    assert amount(own_summary.json()["total_receivables"]) == Decimal("0.00")
    assert own_summary.json()["customers"] == 0
