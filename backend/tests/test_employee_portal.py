from __future__ import annotations

from decimal import Decimal

from conftest import amount

from app.database import SessionLocal
from app.models import Expense


def _employee_login(client, email="employee@finovexa.ai", password="Employee1234!"):
    response = client.post(
        "/api/auth/employee/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["role"] == "employee"
    assert body["profile"] is None
    assert body["business"]["business_name"]
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _dashboard(client, headers):
    response = client.get("/api/dashboard?days=30", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _create_entry(client, headers, **overrides):
    payload = {
        "entry_type": "purchase",
        "counterparty": "Paper Supply Co.",
        "description": "A4 paper restock",
        "amount": 5000,
        "category": "Office supplies",
        "entry_date": "2026-10-24",
        "notes": "Employee recorded",
    }
    payload.update(overrides)
    response = client.post("/api/employee/entries", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["entry"]


def test_owner_and_employee_portals_are_separate(client, demo):
    employee = _employee_login(client)
    owner_headers = demo["headers"]

    assert client.get("/api/dashboard", headers=employee["headers"]).status_code == 403
    assert client.get("/api/invoices", headers=employee["headers"]).status_code == 403
    assert client.get("/api/payments/overview", headers=employee["headers"]).status_code == 403
    assert client.get("/api/team/employees", headers=employee["headers"]).status_code == 403
    assert client.get("/api/employee/overview", headers=owner_headers).status_code == 403

    employee_as_owner = client.post(
        "/api/auth/login",
        json={"email": "employee@finovexa.ai", "password": "Employee1234!"},
    )
    assert employee_as_owner.status_code == 403

    owner_as_employee = client.post(
        "/api/auth/employee/login",
        json={"email": "demo@finovexa.ai", "password": "Demo1234!"},
    )
    assert owner_as_employee.status_code == 403

    overview = client.get("/api/employee/overview", headers=employee["headers"])
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["permissions"]["owner_dashboard"] is False
    assert body["permissions"]["owner_api_access"] is False
    assert body["business"]["business_name"] == "DN Ventures Pvt. Ltd"


def test_employee_purchase_changes_cash_and_expenses(client, demo):
    employee = _employee_login(client)
    before = _dashboard(client, demo["headers"])

    entry = _create_entry(client, employee["headers"])
    assert entry["entry_type"] == "purchase"
    assert entry["reference"].startswith("PUR-")
    assert entry["expense_id"] is not None

    after = _dashboard(client, demo["headers"])
    assert amount(after["metrics"]["operating_expenses"]["value"]) - amount(
        before["metrics"]["operating_expenses"]["value"]
    ) == Decimal("5000.00")
    assert amount(after["cash"]["recorded_balance"]) == amount(
        before["cash"]["recorded_balance"]
    ) - Decimal("5000.00")
    assert after["employee_activity"]["active_employees"] == 1
    assert after["employee_entries"][0]["reference"] == entry["reference"]
    assert after["employee_entries"][0]["employee"]["name"] == "Riya Sharma"

    team_feed = client.get("/api/team/entries?entry_type=purchase", headers=demo["headers"])
    assert team_feed.status_code == 200, team_feed.text
    assert team_feed.json()["items"][0]["reference"] == entry["reference"]

    edited = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={"amount": 7000, "description": "A4 paper and folders"},
        headers=employee["headers"],
    )
    assert edited.status_code == 200, edited.text
    assert amount(edited.json()["entry"]["amount"]) == Decimal("7000.00")
    edited_dashboard = _dashboard(client, demo["headers"])
    assert amount(edited_dashboard["cash"]["recorded_balance"]) == amount(
        before["cash"]["recorded_balance"]
    ) - Decimal("7000.00")

    voided = client.post(
        f"/api/employee/entries/{entry['id']}/void", headers=employee["headers"]
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["entry"]["status"] == "void"
    restored = _dashboard(client, demo["headers"])
    assert amount(restored["cash"]["recorded_balance"]) == amount(before["cash"]["recorded_balance"])


def test_employee_cash_sale_updates_cash_and_invoice(client, demo):
    employee = _employee_login(client)
    before = _dashboard(client, demo["headers"])

    entry = _create_entry(
        client,
        employee["headers"],
        entry_type="sale",
        counterparty="Alpha Design Studio",
        description="Workspace fit-out",
        amount=1000,
        tax_rate=18,
        payment_method="cash",
        category=None,
        notes=None,
    )
    assert amount(entry["amount"]) == Decimal("1180.00")
    assert entry["invoice_id"] is not None
    assert entry["payment_id"] is not None
    assert entry["editable"] is False

    invoices = client.get("/api/invoices?limit=100", headers=demo["headers"]).json()["items"]
    created = next(item for item in invoices if item["id"] == entry["invoice_id"])
    assert created["status"] == "paid"
    assert created["created_by"]["name"] == "Riya Sharma"
    assert created["created_by"]["role"] == "employee"

    after = _dashboard(client, demo["headers"])
    assert amount(after["cash"]["recorded_balance"]) == amount(
        before["cash"]["recorded_balance"]
    ) + Decimal("1180.00")
    newest = after["recent_payments"][0]
    assert newest["source"] == "employee_recorded"
    assert newest["recorded_by"] == "Riya Sharma"
    assert newest["recorded_by_role"] == "employee"

    locked_edit = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={"amount": 2000},
        headers=employee["headers"],
    )
    assert locked_edit.status_code == 409
    locked_void = client.post(
        f"/api/employee/entries/{entry['id']}/void", headers=employee["headers"]
    )
    assert locked_void.status_code == 409

    credit_sale = client.post(
        "/api/employee/entries",
        json={
            "entry_type": "sale",
            "counterparty": "Alpha Design Studio",
            "description": "Credit sale attempt",
            "amount": 500,
            "payment_method": "credit",
            "entry_date": "2026-10-24",
            "tax_rate": 0,
        },
        headers=employee["headers"],
    )
    assert credit_sale.status_code == 400


def test_employee_paypal_sale_appears_in_payment_center(client, demo):
    employee = _employee_login(client)
    entry = _create_entry(
        client,
        employee["headers"],
        entry_type="sale",
        counterparty="Beta Workspaces",
        description="Consulting sprint",
        amount=4000,
        tax_rate=0,
        payment_method="paypal",
        category=None,
    )
    overview = client.get("/api/payments/overview", headers=demo["headers"])
    assert overview.status_code == 200, overview.text
    payment = next(
        item for item in overview.json()["payments"] if item["id"] == entry["payment_id"]
    )
    assert payment["method"] == "paypal"
    assert payment["status"] == "confirmed"
    assert payment["provider"] == "employee_recorded"
    assert payment["source"] == "employee_recorded"
    assert payment["recorded_by"] == "Riya Sharma"
    assert "no paypal api capture" in payment["note"].lower()


def test_employee_invoice_generation_and_unpaid_edit(client, demo):
    employee = _employee_login(client)
    entry = _create_entry(
        client,
        employee["headers"],
        entry_type="invoice",
        counterparty="Gamma Interiors",
        counterparty_email="billing@gamma.example.com",
        description="Design retainer",
        amount=200,
        tax_rate=18,
        payment_method="credit",
        items=[
            {"description": "Design retainer", "quantity": 2, "unit_price": 100},
        ],
        category=None,
    )
    assert entry["entry_type"] == "invoice"
    assert amount(entry["amount"]) == Decimal("236.00")
    assert entry["editable"] is True

    owner_invoices = client.get("/api/invoices?limit=100", headers=demo["headers"]).json()["items"]
    invoice = next(item for item in owner_invoices if item["id"] == entry["invoice_id"])
    assert amount(invoice["outstanding"]) == Decimal("236.00")
    assert invoice["status"] != "paid"

    edited = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={"amount": 300, "description": "Design retainer revised"},
        headers=employee["headers"],
    )
    assert edited.status_code == 200, edited.text
    updated = edited.json()["entry"]
    assert amount(updated["amount"]) == Decimal("354.00")
    assert amount(updated["invoice_outstanding"]) == Decimal("354.00")

    line_edit = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={
            "tax_rate": 18,
            "items": [{"description": "Design retainer", "quantity": 3, "unit_price": 150}],
        },
        headers=employee["headers"],
    )
    assert line_edit.status_code == 200, line_edit.text
    line_entry = line_edit.json()["entry"]
    assert amount(line_entry["amount"]) == Decimal("531.00")
    assert amount(line_entry["invoice_outstanding"]) == Decimal("531.00")
    assert len(line_entry["items"]) == 1
    assert line_entry["items"][0]["description"] == "Design retainer"
    assert amount(line_entry["items"][0]["quantity"]) == Decimal("3.00")
    assert amount(line_entry["items"][0]["line_total"]) == Decimal("450.00")

    voided = client.post(
        f"/api/employee/entries/{entry['id']}/void", headers=employee["headers"]
    )
    assert voided.status_code == 200, voided.text
    invoice_after = client.get(
        f"/api/invoices/{entry['invoice_id']}", headers=demo["headers"]
    ).json()
    assert invoice_after["base_status"] == "void"
    assert amount(invoice_after["outstanding"]) == Decimal("0.00")


def test_employee_purchase_with_items_computes_total(client, demo):
    employee = _employee_login(client)
    before = _dashboard(client, demo["headers"])

    entry = _create_entry(
        client,
        employee["headers"],
        amount=None,
        items=[
            {"description": "A4 paper ream", "quantity": 12, "unit_price": 250},
            {"description": "Folders", "quantity": 5, "unit_price": 80},
        ],
    )
    assert entry["entry_type"] == "purchase"
    assert amount(entry["amount"]) == Decimal("3400.00")
    assert len(entry["items"]) == 2
    assert amount(entry["items"][0]["quantity"]) == Decimal("12.00")
    assert amount(entry["items"][0]["line_total"]) == Decimal("3000.00")
    assert amount(entry["items"][1]["line_total"]) == Decimal("400.00")

    after = _dashboard(client, demo["headers"])
    assert amount(after["metrics"]["operating_expenses"]["value"]) - amount(
        before["metrics"]["operating_expenses"]["value"]
    ) == Decimal("3400.00")
    assert amount(after["cash"]["recorded_balance"]) == amount(
        before["cash"]["recorded_balance"]
    ) - Decimal("3400.00")

    edited = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={"items": [{"description": "A4 paper ream", "quantity": 13, "unit_price": 250}]},
        headers=employee["headers"],
    )
    assert edited.status_code == 200, edited.text
    updated = edited.json()["entry"]
    assert amount(updated["amount"]) == Decimal("3250.00")
    assert len(updated["items"]) == 1
    assert amount(updated["items"][0]["quantity"]) == Decimal("13.00")

    with SessionLocal() as db:
        record = db.get(Expense, updated["expense_id"])
        assert record is not None
        assert "Items:" in (record.note or "")
        assert "A4 paper ream × 13" in (record.note or "")
        assert amount(record.amount) == Decimal("3250.00")


def test_employee_sale_with_multiple_items_creates_line_invoice(client, demo):
    employee = _employee_login(client)
    entry = _create_entry(
        client,
        employee["headers"],
        entry_type="sale",
        counterparty="Alpha Design Studio",
        description="Chairs and desks",
        amount=None,
        tax_rate=0,
        payment_method="upi",
        category=None,
        items=[
            {"description": "Office chairs", "quantity": 4, "unit_price": 1500},
            {"description": "Standing desks", "quantity": 2, "unit_price": 4000},
            {"description": "Cable trays", "quantity": 3, "unit_price": 250},
        ],
    )
    assert amount(entry["amount"]) == Decimal("14750.00")
    assert len(entry["items"]) == 3
    assert amount(entry["items"][1]["line_total"]) == Decimal("8000.00")

    invoice = client.get(
        f"/api/billing/invoices/{entry['invoice_id']}", headers=demo["headers"]
    ).json()
    assert len(invoice["items"]) == 3
    assert amount(invoice["total"]) == Decimal("14750.00")
    assert amount(invoice["paid"]) == Decimal("14750.00")


def test_employee_searches_the_owner_stock_catalogue(client, demo):
    employee = _employee_login(client)

    response = client.get(
        "/api/employee/products?q=chair&limit=5", headers=employee["headers"]
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items, "the demo catalogue should match a partial item name"
    chair = items[0]
    assert chair["name"] == "Ergo Pro Task Chair"
    assert chair["sku"] == "CH-ERG"
    assert amount(chair["unit_price"]) == Decimal("18500.00")
    assert chair["quantity_on_hand"] == 34
    assert chair["unit"] == "pcs"
    assert "unit_cost" not in chair

    sku_search = client.get(
        "/api/employee/products?q=CH-ER", headers=employee["headers"]
    ).json()["items"]
    assert [item["sku"] for item in sku_search] == ["CH-ERG"]

    assert client.get("/api/employee/products", headers=demo["headers"]).status_code == 403


def test_employee_customer_contact_details_persist_for_owner(client, demo):
    employee = _employee_login(client)
    entry = _create_entry(
        client,
        employee["headers"],
        entry_type="invoice",
        counterparty="Delta Traders",
        counterparty_email="accounts@delta.example.com",
        counterparty_phone="98765 43210",
        description="Office chairs",
        amount=1000,
        tax_rate=0,
        payment_method="credit",
        category=None,
    )
    assert entry["counterparty_email"] == "accounts@delta.example.com"
    assert entry["counterparty_phone"] == "+919876543210"

    customers = client.get(
        "/api/billing/customers?q=Delta", headers=demo["headers"]
    ).json()["items"]
    customer = next(item for item in customers if item["name"] == "Delta Traders")
    assert customer["email"] == "accounts@delta.example.com"
    assert customer["phone"] == "+919876543210"

    invoice = client.get(
        f"/api/billing/invoices/{entry['invoice_id']}", headers=demo["headers"]
    ).json()
    assert invoice["customer"]["name"] == "Delta Traders"
    assert invoice["customer"]["phone"] == "+919876543210"
    assert amount(invoice["outstanding"]) == Decimal("1000.00")

    fetched = client.get(
        f"/api/employee/entries/{entry['id']}", headers=employee["headers"]
    ).json()
    assert fetched["counterparty_email"] == "accounts@delta.example.com"
    assert fetched["counterparty_phone"] == "+919876543210"

    updated = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={
            "counterparty_email": "payables@delta.example.com",
            "counterparty_phone": "9123456780",
        },
        headers=employee["headers"],
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["entry"]
    assert body["counterparty_email"] == "payables@delta.example.com"
    assert body["counterparty_phone"] == "+919123456780"

    customer_after = next(
        item
        for item in client.get(
            "/api/billing/customers?q=Delta", headers=demo["headers"]
        ).json()["items"]
        if item["id"] == customer["id"]
    )
    assert customer_after["email"] == "payables@delta.example.com"
    assert customer_after["phone"] == "+919123456780"

    invoice_after = client.get(
        f"/api/billing/invoices/{entry['invoice_id']}", headers=demo["headers"]
    ).json()
    assert invoice_after["customer"]["phone"] == "+919123456780"


def test_employee_contact_details_update_an_existing_owner_customer(client, demo):
    created = client.post(
        "/api/billing/customers",
        json={
            "name": "Epsilon Retail",
            "email": "old@epsilon.example.com",
            "phone": "9000000000",
            "state": "Karnataka",
            "state_code": "29",
        },
        headers=demo["headers"],
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["item"]["id"]

    employee = _employee_login(client)
    entry = _create_entry(
        client,
        employee["headers"],
        entry_type="invoice",
        counterparty="Epsilon Retail",
        counterparty_email="new@epsilon.example.com",
        counterparty_phone="9123456781",
        description="Store fixtures",
        amount=500,
        tax_rate=0,
        payment_method="credit",
        category=None,
    )
    assert entry["counterparty_email"] == "new@epsilon.example.com"

    customer = next(
        item
        for item in client.get(
            "/api/billing/customers?q=Epsilon", headers=demo["headers"]
        ).json()["items"]
        if item["id"] == customer_id
    )
    assert customer["email"] == "new@epsilon.example.com"
    assert customer["phone"] == "+919123456781"

    invoice = client.get(
        f"/api/billing/invoices/{entry['invoice_id']}", headers=demo["headers"]
    ).json()
    assert invoice["customer"]["id"] == customer_id
    assert invoice["customer"]["state_code"] == "29"
    assert invoice["place_of_supply"]["state_code"] == "29"


def test_owner_creates_and_deactivates_employee(client, demo):
    created = client.post(
        "/api/team/employees",
        json={
            "email": "new.employee@finovexa.ai",
            "password": "Employee5678!",
            "full_name": "Kabir Shah",
        },
        headers=demo["headers"],
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["employee"]["id"]

    roster = client.get("/api/team/employees", headers=demo["headers"]).json()
    assert any(item["id"] == employee_id for item in roster["items"])
    assert "demo_credentials" not in roster

    new_employee = _employee_login(
        client, "new.employee@finovexa.ai", "Employee5678!"
    )
    assert client.get("/api/dashboard", headers=new_employee["headers"]).status_code == 403

    deactivated = client.patch(
        f"/api/team/employees/{employee_id}",
        json={"is_active": False},
        headers=demo["headers"],
    )
    assert deactivated.status_code == 200, deactivated.text
    blocked = client.post(
        "/api/auth/employee/login",
        json={"email": "new.employee@finovexa.ai", "password": "Employee5678!"},
    )
    assert blocked.status_code == 401


def test_employee_entries_are_scoped_to_the_owning_business(client, demo, other):
    employee = _employee_login(client)
    entry = _create_entry(client, employee["headers"])

    other_employee_response = client.post(
        "/api/team/employees",
        json={
            "email": "second.employee@second-business.example.com",
            "password": "Second5678!",
            "full_name": "Second Employee",
        },
        headers=other["headers"],
    )
    assert other_employee_response.status_code == 201, other_employee_response.text
    other_employee = _employee_login(
        client, "second.employee@second-business.example.com", "Second5678!"
    )
    assert (
        client.get(f"/api/employee/entries/{entry['id']}", headers=other_employee["headers"]).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/employee/entries/{entry['id']}",
            json={"notes": "cross-tenant"},
            headers=other_employee["headers"],
        ).status_code
        == 404
    )
    other_entries = client.get("/api/employee/entries", headers=other_employee["headers"]).json()
    assert other_entries["count"] == 0
    assert (
        client.get("/api/employee/overview", headers=other_employee["headers"]).json()["business"][
            "business_name"
        ]
        == "Second Business"
    )


def _catalogue(client, headers):
    response = client.get("/api/billing/products?limit=100", headers=headers)
    assert response.status_code == 200, response.text
    return {item["sku"]: item for item in response.json()["items"]}


def _on_hand(client, headers, sku):
    return _catalogue(client, headers)[sku]["quantity_on_hand"]


def test_employee_purchase_adds_matching_catalogue_stock(client, demo):
    employee = _employee_login(client)
    chair = _catalogue(client, demo["headers"])["CH-ERG"]
    footrest = _catalogue(client, demo["headers"])["FR-ERG"]

    entry = _create_entry(
        client,
        employee["headers"],
        counterparty="Ergo Wholesale",
        description="Chair and footrest restock",
        items=[
            {"description": "Ergo Pro Task Chair", "quantity": 2, "unit_price": 11900},
            {
                "description": footrest["name"],
                "quantity": 5,
                "unit_price": 1650,
                "product_id": footrest["id"],
            },
        ],
    )
    assert [item["product_id"] for item in entry["items"]] == [chair["id"], footrest["id"]]

    catalogue = _catalogue(client, demo["headers"])
    assert catalogue["CH-ERG"]["quantity_on_hand"] == 36
    assert catalogue["FR-ERG"]["quantity_on_hand"] == 31


def test_employee_sale_and_invoice_reduce_catalogue_stock(client, demo):
    employee = _employee_login(client)
    chair = _catalogue(client, demo["headers"])["CH-ERG"]

    sale = _create_entry(
        client,
        employee["headers"],
        entry_type="sale",
        counterparty="Acme Interiors",
        description="Chair sale",
        payment_method="upi",
        items=[
            {
                "description": chair["name"],
                "quantity": 3,
                "unit_price": 18500,
                "product_id": chair["id"],
            }
        ],
    )
    assert sale["items"][0]["product_id"] == chair["id"]
    assert _on_hand(client, demo["headers"], "CH-ERG") == 31

    _create_entry(
        client,
        employee["headers"],
        entry_type="invoice",
        counterparty="Beta Offices",
        description="Chair invoice",
        payment_method="credit",
        items=[
            {
                "description": chair["name"],
                "quantity": 2,
                "unit_price": 18500,
                "product_id": chair["id"],
            }
        ],
    )
    assert _on_hand(client, demo["headers"], "CH-ERG") == 29


def test_employee_purchase_edit_and_void_keep_stock_in_step(client, demo):
    employee = _employee_login(client)
    chair = _catalogue(client, demo["headers"])["CH-ERG"]
    desk = _catalogue(client, demo["headers"])["DK-LFT"]

    entry = _create_entry(
        client,
        employee["headers"],
        items=[{"description": chair["name"], "quantity": 4, "unit_price": 11900}],
    )
    assert _on_hand(client, demo["headers"], "CH-ERG") == 38

    edited = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={
            "items": [
                {
                    "description": chair["name"],
                    "quantity": 1,
                    "unit_price": 11900,
                    "product_id": chair["id"],
                },
                {
                    "description": desk["name"],
                    "quantity": 2,
                    "unit_price": 22500,
                    "product_id": desk["id"],
                },
            ]
        },
        headers=employee["headers"],
    )
    assert edited.status_code == 200, edited.text
    assert _on_hand(client, demo["headers"], "CH-ERG") == 35
    assert _on_hand(client, demo["headers"], "DK-LFT") == 14

    voided = client.post(
        f"/api/employee/entries/{entry['id']}/void", headers=employee["headers"]
    )
    assert voided.status_code == 200, voided.text
    assert _on_hand(client, demo["headers"], "CH-ERG") == 34
    assert _on_hand(client, demo["headers"], "DK-LFT") == 12


def test_employee_invoice_edit_and_void_keep_stock_in_step(client, demo):
    employee = _employee_login(client)
    chair = _catalogue(client, demo["headers"])["CH-ERG"]

    entry = _create_entry(
        client,
        employee["headers"],
        entry_type="invoice",
        counterparty="Gamma Furnishings",
        description="Chair invoice",
        payment_method="credit",
        items=[
            {
                "description": chair["name"],
                "quantity": 3,
                "unit_price": 18500,
                "product_id": chair["id"],
            }
        ],
    )
    assert _on_hand(client, demo["headers"], "CH-ERG") == 31

    edited = client.patch(
        f"/api/employee/entries/{entry['id']}",
        json={
            "items": [
                {
                    "description": chair["name"],
                    "quantity": 1,
                    "unit_price": 18500,
                    "product_id": chair["id"],
                }
            ]
        },
        headers=employee["headers"],
    )
    assert edited.status_code == 200, edited.text
    assert _on_hand(client, demo["headers"], "CH-ERG") == 33

    voided = client.post(
        f"/api/employee/entries/{entry['id']}/void", headers=employee["headers"]
    )
    assert voided.status_code == 200, voided.text
    assert _on_hand(client, demo["headers"], "CH-ERG") == 34


def test_employee_entries_without_a_catalogue_match_leave_stock_alone(client, demo):
    employee = _employee_login(client)
    before = {
        sku: item["quantity_on_hand"]
        for sku, item in _catalogue(client, demo["headers"]).items()
    }

    entry = _create_entry(
        client,
        employee["headers"],
        counterparty="Landlord",
        description="Monthly office rent",
        category="Rent",
        items=[{"description": "Monthly office rent", "quantity": 1, "unit_price": 45000}],
    )
    assert entry["items"][0]["product_id"] is None

    after = {
        sku: item["quantity_on_hand"]
        for sku, item in _catalogue(client, demo["headers"]).items()
    }
    assert after == before


def test_employee_stock_quantity_must_be_whole_units(client, demo):
    employee = _employee_login(client)
    chair = _catalogue(client, demo["headers"])["CH-ERG"]

    response = client.post(
        "/api/employee/entries",
        json={
            "entry_type": "purchase",
            "counterparty": "Ergo Wholesale",
            "description": "Half chair",
            "category": "Purchases",
            "entry_date": "2026-10-24",
            "items": [
                {
                    "description": chair["name"],
                    "quantity": 1.5,
                    "unit_price": 11900,
                    "product_id": chair["id"],
                }
            ],
        },
        headers=employee["headers"],
    )
    assert response.status_code == 400, response.text
    assert "whole units" in response.json()["detail"]
    assert _on_hand(client, demo["headers"], "CH-ERG") == 34
