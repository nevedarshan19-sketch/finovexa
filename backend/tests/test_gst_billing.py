from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Invoice, InvoiceItem, User
from app.services.gst import (
    GSTValidationError,
    LineInput,
    invoice_totals,
    line_calculation,
    resolve_supply_type,
)
from conftest import amount


def line(
    quantity: str = "1",
    unit_price: str = "1000",
    discount: str = "0",
    rate: str = "18",
    mode: str = "exclusive",
) -> LineInput:
    return LineInput(
        quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        discount=Decimal(discount),
        gst_rate=Decimal(rate),
        pricing_mode=mode,
    )


# ---------------------------------------------------------------- calculation engine


@pytest.mark.parametrize(
    ("rate", "gst"),
    [("0", "0.00"), ("5", "50.00"), ("12", "120.00"), ("18", "180.00"), ("28", "280.00")],
)
def test_single_item_each_configured_rate(rate: str, gst: str):
    calc = line_calculation(line(rate=rate), "intra_state")
    assert calc["taxable_value"] == Decimal("1000.00")
    assert calc["gst_amount"] == Decimal(gst)
    assert calc["cgst_amount"] + calc["sgst_amount"] == calc["gst_amount"]
    assert calc["final_amount"] == Decimal("1000.00") + Decimal(gst)


def test_example_two_units_at_eighteen_percent():
    totals = invoice_totals([line(quantity="2")], supply_type="intra_state")
    assert totals["taxable_value"] == Decimal("2000.00")
    assert totals["cgst_amount"] == Decimal("180.00")
    assert totals["sgst_amount"] == Decimal("180.00")
    assert totals["igst_amount"] == Decimal("0.00")
    assert totals["total_amount"] == Decimal("2360.00")


def test_multi_rate_invoice_uses_each_line_rate():
    totals = invoice_totals(
        [line(unit_price="1000", rate="18"), line(unit_price="1000", rate="5")],
        supply_type="intra_state",
        round_to_rupee=False,
    )
    assert totals["tax_amount"] == Decimal("230.00")
    assert totals["cgst_amount"] == Decimal("115.00")
    assert totals["sgst_amount"] == Decimal("115.00")
    assert totals["total_amount"] == Decimal("2230.00")


def test_inclusive_pricing_backs_out_tax():
    calc = line_calculation(line(unit_price="1180", rate="18", mode="inclusive"), "intra_state")
    assert calc["taxable_value"] == Decimal("1000.00")
    assert calc["gst_amount"] == Decimal("180.00")
    assert calc["final_amount"] == Decimal("1180.00")


def test_discount_applies_before_tax():
    totals = invoice_totals(
        [line(quantity="2", discount="200")], supply_type="intra_state", round_to_rupee=False
    )
    assert totals["subtotal"] == Decimal("2000.00")
    assert totals["discount"] == Decimal("200.00")
    assert totals["taxable_value"] == Decimal("1800.00")
    assert totals["tax_amount"] == Decimal("324.00")
    assert totals["total_amount"] == Decimal("2124.00")


def test_inter_state_uses_igst_only():
    totals = invoice_totals([line()], supply_type="inter_state", round_to_rupee=False)
    assert totals["igst_amount"] == Decimal("180.00")
    assert totals["cgst_amount"] == Decimal("0.00")
    assert totals["sgst_amount"] == Decimal("0.00")


def test_rounding_adjustment_reconciles_to_whole_rupee():
    totals = invoice_totals(
        [line(unit_price="999.99")], supply_type="intra_state", round_to_rupee=True
    )
    assert totals["raw_total"] == Decimal("1179.99")
    assert totals["total_amount"] == Decimal("1180.00")
    assert totals["rounding_adjustment"] == Decimal("0.01")
    assert (
        totals["taxable_value"] + totals["tax_amount"] + totals["rounding_adjustment"]
        == totals["total_amount"]
    )


@pytest.mark.parametrize(
    "candidate",
    [
        line(quantity="0"),
        line(unit_price="-1"),
        line(discount="1500"),
        line(rate="101"),
        line(rate="-1"),
    ],
)
def test_invalid_lines_are_rejected(candidate: LineInput):
    with pytest.raises(GSTValidationError):
        line_calculation(candidate, "intra_state")


def test_supply_type_requires_verified_states():
    assert resolve_supply_type("27", "27") == "intra_state"
    assert resolve_supply_type("27", "29") == "inter_state"
    with pytest.raises(GSTValidationError):
        resolve_supply_type("", "27")
    with pytest.raises(GSTValidationError):
        resolve_supply_type("27", "")


# ---------------------------------------------------------------- API helpers


def _configure_supplier(client, headers, state="Maharashtra", code="27"):
    response = client.put(
        "/api/billing/settings",
        headers=headers,
        json={"state": state, "state_code": code, "city": "Mumbai"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["ready"] is True


def _customer(client, headers, state="Maharashtra", code="27", email="gst.buyer@example.com"):
    response = client.post(
        "/api/billing/customers",
        headers=headers,
        json={
            "name": "GST Buyer",
            "email": email,
            "billing_address_line1": "12 Buyer Street",
            "city": "Mumbai" if code == "27" else "Bengaluru",
            "state": state,
            "state_code": code,
        },
    )
    if response.status_code == 409:
        items = client.get("/api/billing/customers", headers=headers).json()["items"]
        return next(item for item in items if item["email"] == email)
    assert response.status_code == 201, response.text
    return response.json()["item"]


def _invoice_payload(customer_id, code="27", rate="18", discount="0", confirm=True):
    return {
        "customer_id": customer_id,
        "issue_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=15)).isoformat(),
        "pricing_mode": "exclusive",
        "place_of_supply_state_code": code,
        "place_of_supply_state": "Maharashtra" if code == "27" else "Karnataka",
        "round_to_rupee": False,
        "confirm_supply_details": confirm,
        "items": [
            {
                "name": "Ergonomic chair",
                "hsn_sac": "9401",
                "quantity": "2",
                "unit_price": "1000",
                "discount": discount,
                "gst_rate": rate,
            }
        ],
    }


# ---------------------------------------------------------------- billing API


def test_calculate_create_and_pdf_round_trip(client, demo):
    _configure_supplier(client, demo["headers"])
    customer = _customer(client, demo["headers"])

    calc = client.post(
        "/api/billing/calculate", headers=demo["headers"], json=_invoice_payload(customer["id"])
    )
    assert calc.status_code == 200, calc.text
    body = calc.json()
    assert body["supply_type"] == "intra_state"
    assert amount(body["totals"]["taxable_value"]) == amount("2000")
    assert amount(body["totals"]["cgst_amount"]) == amount("180")
    assert amount(body["totals"]["sgst_amount"]) == amount("180")
    assert amount(body["totals"]["total_amount"]) == amount("2360")

    created = client.post(
        "/api/billing/invoices", headers=demo["headers"], json=_invoice_payload(customer["id"])
    )
    assert created.status_code == 201, created.text
    invoice = created.json()
    assert invoice["supply_type"] == "intra_state"
    assert invoice["supply_verified"] is True
    assert amount(invoice["total"]) == amount("2360")
    assert amount(invoice["outstanding"]) == amount("2360")
    assert invoice["items"][0]["gst_rate"] == 18

    pdf = client.get(f"/api/billing/invoices/{invoice['id']}/pdf", headers=demo["headers"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]


def test_inter_state_invoice_uses_igst(client, demo):
    _configure_supplier(client, demo["headers"])
    customer = _customer(
        client, demo["headers"], state="Karnataka", code="29", email="karnataka.buyer@example.com"
    )
    created = client.post(
        "/api/billing/invoices",
        headers=demo["headers"],
        json=_invoice_payload(customer["id"], code="29"),
    )
    assert created.status_code == 201, created.text
    invoice = created.json()
    assert invoice["supply_type"] == "inter_state"
    assert amount(invoice["igst"]) == amount("360")
    assert amount(invoice["cgst"]) == 0
    assert amount(invoice["sgst"]) == 0


def test_manual_rate_change_does_not_touch_issued_invoice(client, demo):
    _configure_supplier(client, demo["headers"])
    customer = _customer(client, demo["headers"])
    first = client.post(
        "/api/billing/invoices", headers=demo["headers"], json=_invoice_payload(customer["id"])
    ).json()
    second = client.post(
        "/api/billing/invoices",
        headers=demo["headers"],
        json=_invoice_payload(customer["id"], rate="12"),
    ).json()
    assert amount(second["tax"]) == amount("240")
    stored = client.get(f"/api/billing/invoices/{first['id']}", headers=demo["headers"]).json()
    assert stored["items"][0]["gst_rate"] == 18
    assert amount(stored["total"]) == amount("2360")


def test_invalid_requests_are_blocked(client, demo):
    _configure_supplier(client, demo["headers"])
    customer = _customer(client, demo["headers"])

    missing_confirmation = client.post(
        "/api/billing/invoices",
        headers=demo["headers"],
        json=_invoice_payload(customer["id"], confirm=False),
    )
    assert missing_confirmation.status_code == 400

    unconfigured_rate = client.post(
        "/api/billing/calculate",
        headers=demo["headers"],
        json=_invoice_payload(customer["id"], rate="17"),
    )
    assert unconfigured_rate.status_code == 400
    assert "configured rate list" in unconfigured_rate.json()["detail"]

    excessive_discount = client.post(
        "/api/billing/calculate",
        headers=demo["headers"],
        json=_invoice_payload(customer["id"], discount="3000"),
    )
    assert excessive_discount.status_code == 400
    assert "discount" in excessive_discount.json()["detail"].lower()

    no_place = _invoice_payload(customer["id"])
    no_place.pop("place_of_supply_state_code")
    no_place.pop("place_of_supply_state")
    response = client.post("/api/billing/calculate", headers=demo["headers"], json=no_place)
    assert response.status_code == 400
    assert "place of supply" in response.json()["detail"].lower()


def test_payments_update_outstanding_balance(client, demo):
    _configure_supplier(client, demo["headers"])
    customer = _customer(client, demo["headers"])
    invoice = client.post(
        "/api/billing/invoices", headers=demo["headers"], json=_invoice_payload(customer["id"])
    ).json()

    partial = client.post(
        f"/api/invoices/{invoice['id']}/payments",
        headers=demo["headers"],
        json={"amount": "1000", "method": "bank", "reference": "UTR-GST-1"},
    )
    assert partial.status_code == 200, partial.text
    assert amount(partial.json()["invoice"]["outstanding"]) == amount("1360")
    assert partial.json()["payment"]["status"] == "confirmed"

    rest = client.post(
        f"/api/invoices/{invoice['id']}/payments",
        headers=demo["headers"],
        json={"amount": "1360", "method": "upi", "reference": "UPI-GST-2"},
    )
    assert rest.status_code == 200, rest.text
    assert amount(rest.json()["invoice"]["outstanding"]) == amount("0")
    assert rest.json()["invoice"]["status"] == "paid"


def test_billing_invoices_are_tenant_scoped(client, demo, other):
    _configure_supplier(client, demo["headers"])
    customer = _customer(client, demo["headers"])
    invoice = client.post(
        "/api/billing/invoices", headers=demo["headers"], json=_invoice_payload(customer["id"])
    ).json()

    response = client.get(f"/api/billing/invoices/{invoice['id']}", headers=other["headers"])
    assert response.status_code == 404
    pdf = client.get(f"/api/billing/invoices/{invoice['id']}/pdf", headers=other["headers"])
    assert pdf.status_code == 404


def test_legacy_invoice_without_states_is_unverified_then_can_be_verified(client, demo):
    _configure_supplier(client, demo["headers"])
    customer = _customer(client, demo["headers"])

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "demo@finovexa.ai")).scalar_one()
        legacy = Invoice(
            user_id=user.id,
            created_by_user_id=user.id,
            customer_id=customer["id"],
            number="INV-LEGACY-1",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=10),
            currency="INR",
            status="issued",
            subtotal_amount=Decimal("1000.00"),
            taxable_amount=Decimal("1000.00"),
            tax_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            round_to_rupee=False,
        )
        db.add(legacy)
        db.flush()
        db.add(
            InvoiceItem(
                invoice_id=legacy.id,
                name="Legacy line",
                description="Legacy line",
                quantity=Decimal("1"),
                unit_price=Decimal("1000.00"),
                line_total=Decimal("1000.00"),
                taxable_value=Decimal("1000.00"),
                gst_rate=Decimal("18.00"),
                gst_amount=Decimal("180.00"),
                final_amount=Decimal("1180.00"),
            )
        )
        db.commit()
        legacy_id = legacy.id

    fetched = client.get(f"/api/billing/invoices/{legacy_id}", headers=demo["headers"]).json()
    assert fetched["supply_type"] == "unverified"
    assert fetched["supply_type_label"] == "GST classification not verified"
    assert amount(fetched["tax"]) == amount("180")
    assert amount(fetched["cgst"]) == 0
    assert amount(fetched["sgst"]) == 0
    assert amount(fetched["igst"]) == 0
    assert amount(fetched["total"]) == amount("1180")

    verified = client.put(
        f"/api/billing/invoices/{legacy_id}",
        headers=demo["headers"],
        json={
            **_invoice_payload(customer["id"]),
            "number": "INV-LEGACY-1",
            "items": [
                {
                    "name": "Legacy line",
                    "quantity": "1",
                    "unit_price": "1000",
                    "discount": "0",
                    "gst_rate": "18",
                }
            ],
        },
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["supply_type"] == "intra_state"
    assert body["supply_verified"] is True
    assert amount(body["cgst"]) == amount("90")
    assert amount(body["sgst"]) == amount("90")
    assert amount(body["total"]) == amount("1180")


def test_customer_mobile_is_normalized_and_snapshotted_on_invoice(client, demo):
    _configure_supplier(client, demo["headers"])
    created = client.post(
        "/api/billing/customers",
        headers=demo["headers"],
        json={
            "name": "Mobile Buyer",
            "email": "mobile.buyer@example.com",
            "phone": "098200 12345",
            "billing_address_line1": "5 Buyer Lane",
            "city": "Mumbai",
            "state": "Maharashtra",
            "state_code": "27",
        },
    )
    assert created.status_code == 201, created.text
    customer = created.json()["item"]
    assert customer["phone"] == "+919820012345"

    invoice = client.post(
        "/api/billing/invoices",
        headers=demo["headers"],
        json=_invoice_payload(customer["id"]),
    )
    assert invoice.status_code == 201, invoice.text
    invoice_body = invoice.json()
    assert invoice_body["customer"]["phone"] == "+919820012345"

    updated = client.put(
        f"/api/billing/customers/{customer['id']}",
        headers=demo["headers"],
        json={
            "name": "Mobile Buyer",
            "email": "mobile.buyer@example.com",
            "phone": "+91 98200 99999",
            "billing_address_line1": "5 Buyer Lane",
            "city": "Mumbai",
            "state": "Maharashtra",
            "state_code": "27",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["item"]["phone"] == "+919820099999"

    snapshot = client.get(
        f"/api/billing/invoices/{invoice_body['id']}", headers=demo["headers"]
    ).json()
    assert snapshot["customer"]["phone"] == "+919820012345"

    refreshed = client.put(
        f"/api/billing/invoices/{invoice_body['id']}",
        headers=demo["headers"],
        json={**_invoice_payload(customer["id"]), "number": invoice_body["number"]},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["customer"]["phone"] == "+919820099999"
