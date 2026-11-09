from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.services.finance import q2
from app.services.gst import GSTValidationError
from app.services.income_tax import (
    TaxValidationError,
    assessment_year,
    compute_comparison,
    compute_income_tax,
    financial_year_bounds,
    seed_tax_rules,
)
from conftest import amount


@pytest.fixture(autouse=True)
def rules(client):
    """The client fixture recreates every table, so the published rules are re-seeded per test."""
    with SessionLocal() as db:
        seed_tax_rules(db)
    yield


def salary_inputs(**salary) -> dict:
    base = {
        "gross_salary": "0",
        "basic_salary": "0",
        "hra_received": "0",
        "rent_paid": "0",
        "professional_tax": "0",
        "employer_nps": "0",
        "metro_city": False,
    }
    base.update(salary)
    return {"salary": base}


def liability(result: dict) -> Decimal:
    return amount(result["tax"]["total_liability"])


# ---------------------------------------------------------------- financial year


def test_financial_year_bounds_and_assessment_year():
    start, end = financial_year_bounds("2026-27")
    assert start == date(2026, 4, 1)
    assert end == date(2027, 3, 31)
    assert assessment_year("2026-27") == "2027-28"
    # A leap-year March must still end on the 31st.
    _start, leap_end = financial_year_bounds("2027-28")
    assert leap_end == date(2028, 3, 31)


@pytest.mark.parametrize("value", ["2026", "2026-28", "2026/27", "abcd-ef", ""])
def test_financial_year_rejects_bad_input(value):
    with pytest.raises(TaxValidationError):
        financial_year_bounds(value)


# ---------------------------------------------------------------- new regime


def test_new_regime_rebate_makes_twelve_lakh_income_tax_free():
    # New regime, FY 2025-26 onwards: standard deduction 75,000, so 12,75,000 gross is 12,00,000.
    with SessionLocal() as db:
        result = compute_income_tax(
            db, financial_year="2025-26", regime="new", inputs=salary_inputs(gross_salary="1275000")
        )
    assert amount(result["total_income"]) == Decimal("1200000.00")
    assert amount(result["tax"]["slab_tax"]) == Decimal("60000.00")
    assert amount(result["tax"]["rebate_87a"]) == Decimal("60000.00")
    assert liability(result) == Decimal("0.00")
    assert result["rule_version"] == "FA2025"
    assert result["assessment_year"] == "2026-27"


def test_new_regime_marginal_relief_caps_tax_just_above_the_rebate_limit():
    # Total income 12,10,000: slab tax 61,500 but the excess over 12,00,000 is only 10,000.
    with SessionLocal() as db:
        result = compute_income_tax(
            db, financial_year="2025-26", regime="new", inputs=salary_inputs(gross_salary="1285000")
        )
    assert amount(result["total_income"]) == Decimal("1210000.00")
    assert amount(result["tax"]["slab_tax"]) == Decimal("61500.00")
    assert amount(result["tax"]["rebate_marginal_relief"]) == Decimal("51500.00")
    assert amount(result["tax"]["tax_before_surcharge"]) == Decimal("10000.00")
    assert liability(result) == Decimal("10400.00")  # 10,000 + 4% cess


def test_new_regime_slabs_above_the_rebate_limit():
    # Total income 20,00,000: 4-8L @5% = 20,000; 8-12L @10% = 40,000; 12-16L @15% = 60,000;
    # 16-20L @20% = 80,000 -> 2,00,000 slab tax, plus 4% cess.
    with SessionLocal() as db:
        result = compute_income_tax(
            db, financial_year="2025-26", regime="new", inputs=salary_inputs(gross_salary="2075000")
        )
    assert amount(result["total_income"]) == Decimal("2000000.00")
    assert amount(result["tax"]["slab_tax"]) == Decimal("200000.00")
    assert amount(result["tax"]["cess"]) == Decimal("8000.00")
    assert liability(result) == Decimal("208000.00")
    assert [row["rate"] for row in result["tax"]["slabs"]] == [
        Decimal("0.00"),
        Decimal("5.00"),
        Decimal("10.00"),
        Decimal("15.00"),
        Decimal("20.00"),
    ]


def test_new_regime_ignores_chapter_via_a_deductions():
    inputs = salary_inputs(gross_salary="1275000")
    inputs["deductions"] = {"80C": "150000", "80D": "25000"}
    with SessionLocal() as db:
        result = compute_income_tax(db, financial_year="2025-26", regime="new", inputs=inputs)
    assert amount(result["deductions"]["total"]) == Decimal("0.00")
    rows = {row["section"]: row for row in result["deductions"]["items"]}
    assert rows["80C"]["allowed"] == Decimal("0.00")
    assert "Not available" in rows["80C"]["reason"]


# ---------------------------------------------------------------- old regime


def test_old_regime_hra_deductions_and_cess():
    # Gross 15,00,000, basic 6,00,000, HRA 3,00,000, rent 3,60,000 in a metro city.
    # HRA exemption = min(3,00,000, 3,60,000 - 60,000, 50% of 6,00,000) = 3,00,000.
    # Net salary = 15,00,000 - 3,00,000 - 50,000 (standard deduction) = 11,50,000.
    # Deductions 80C 1,50,000 + 80D 25,000 = 1,75,000 -> total income 9,75,000.
    # Slab tax = 12,500 + 95,000 = 1,07,500; cess 4,300 -> 1,11,800.
    inputs = salary_inputs(
        gross_salary="1500000",
        basic_salary="600000",
        hra_received="300000",
        rent_paid="360000",
        metro_city=True,
    )
    inputs["deductions"] = {"80C": "150000", "80D": "25000"}
    with SessionLocal() as db:
        result = compute_income_tax(db, financial_year="2025-26", regime="old", inputs=inputs)
    assert amount(result["income"]["salary"]["hra_exemption"]) == Decimal("300000.00")
    assert amount(result["total_income"]) == Decimal("975000.00")
    assert amount(result["tax"]["slab_tax"]) == Decimal("107500.00")
    assert amount(result["tax"]["cess"]) == Decimal("4300.00")
    assert liability(result) == Decimal("111800.00")


def test_old_regime_non_metro_hra_uses_forty_percent():
    inputs = salary_inputs(
        gross_salary="1200000",
        basic_salary="600000",
        hra_received="300000",
        rent_paid="600000",
        metro_city=False,
    )
    with SessionLocal() as db:
        result = compute_income_tax(db, financial_year="2025-26", regime="old", inputs=inputs)
    # min(HRA 3,00,000, rent less 10% basic 5,40,000, 40% basic 2,40,000) = 2,40,000.
    assert amount(result["income"]["salary"]["hra_exemption"]) == Decimal("240000.00")


def test_old_regime_rebate_applies_up_to_five_lakh():
    # Gross 5,50,000 -> net salary 5,00,000 -> slab tax 12,500 -> 87A rebate wipes it out.
    with SessionLocal() as db:
        result = compute_income_tax(
            db, financial_year="2025-26", regime="old", inputs=salary_inputs(gross_salary="550000")
        )
    assert amount(result["total_income"]) == Decimal("500000.00")
    assert amount(result["tax"]["rebate_87a"]) == Decimal("12500.00")
    assert liability(result) == Decimal("0.00")


# ---------------------------------------------------------------- surcharge and cess


def test_surcharge_band_and_marginal_relief_at_five_crore():
    # Old regime, total income 5,00,50,000 crosses the 37% band. Without relief the jump at
    # 5 crore would make the tax larger than the extra income, so relief is applied.
    with SessionLocal() as db:
        result = compute_income_tax(
            db,
            financial_year="2025-26",
            regime="old",
            inputs=salary_inputs(gross_salary="50100000"),
        )
    assert amount(result["tax"]["surcharge_rate"]) == Decimal("37.00")
    assert amount(result["tax"]["surcharge_marginal_relief"]) > Decimal("0.00")
    assert amount(result["total_income"]) == Decimal("50050000.00")
    assert liability(result) == Decimal("19308250.00")


def test_new_regime_higher_surcharge_band_has_no_cliff():
    with SessionLocal() as db:
        result = compute_income_tax(
            db,
            financial_year="2025-26",
            regime="new",
            inputs=salary_inputs(gross_salary="10500000"),
        )
    assert amount(result["total_income"]) == Decimal("10425000.00")
    assert amount(result["tax"]["surcharge_rate"]) == Decimal("15.00")
    assert amount(result["tax"]["surcharge"]) == Decimal("406125.00")
    assert liability(result) == Decimal("3238170.00")


# ---------------------------------------------------------------- capital gains


def test_equity_ltcg_uses_stored_exemption_and_rate():
    # 112A: 12.5% above 1,25,000. Slab income 11,25,000 is below the rebate limit, so the
    # rebate removes slab tax while the 9,375 capital-gains tax survives, plus 4% cess.
    inputs = salary_inputs(gross_salary="1200000")
    inputs["capital_gains"] = {"equity_ltcg": "200000"}
    with SessionLocal() as db:
        result = compute_income_tax(db, financial_year="2025-26", regime="new", inputs=inputs)
    row = result["tax"]["capital_gains"][0]
    assert row["category"] == "equity_ltcg_112a"
    assert row["exemption"] == Decimal("125000.00")
    assert row["taxable"] == Decimal("75000.00")
    assert amount(result["tax"]["capital_gains_tax"]) == Decimal("9375.00")
    assert liability(result) == Decimal("9750.00")


def test_equity_stcg_is_taxed_at_twenty_percent():
    inputs = {"capital_gains": {"equity_stcg": "100000"}}
    with SessionLocal() as db:
        result = compute_income_tax(db, financial_year="2025-26", regime="new", inputs=inputs)
    assert amount(result["tax"]["capital_gains_tax"]) == Decimal("20000.00")
    assert liability(result) == Decimal("20800.00")


# ---------------------------------------------------------------- presumptive business


def test_section_44ad_splits_digital_and_cash_receipts():
    with SessionLocal() as db:
        result = compute_income_tax(
            db,
            financial_year="2025-26",
            regime="old",
            inputs={
                "business": {
                    "presumptive": "44ad",
                    "gross_receipts": "2000000",
                    "digital_receipts_pct": "50",
                }
            },
        )
    # 50% digital at 6% + 50% cash at 8% = 7% of 20,00,000 = 1,40,000.
    assert amount(result["income"]["business"]["income"]) == Decimal("140000.00")
    assert liability(result) == Decimal("0.00")


def test_section_44ada_uses_half_of_gross_receipts():
    with SessionLocal() as db:
        result = compute_income_tax(
            db,
            financial_year="2025-26",
            regime="old",
            inputs={"business": {"presumptive": "44ada", "gross_receipts": "1600000"}},
        )
    assert amount(result["income"]["business"]["income"]) == Decimal("800000.00")


def test_presumptive_without_receipts_is_rejected():
    with SessionLocal() as db:
        with pytest.raises(TaxValidationError):
            compute_income_tax(
                db,
                financial_year="2025-26",
                regime="new",
                inputs={"business": {"presumptive": "44ad", "gross_receipts": "0"}},
            )


# ---------------------------------------------------------------- comparison


def test_comparison_recommends_the_lower_regime_and_reports_savings():
    with SessionLocal() as db:
        result = compute_comparison(
            db, financial_year="2025-26", inputs=salary_inputs(gross_salary="1500000")
        )
    assert result["recommended_regime"] == "new"
    new_tax = amount(result["regimes"]["new"]["tax"]["total_liability"])
    old_tax = amount(result["regimes"]["old"]["tax"]["total_liability"])
    assert amount(result["savings"]) == old_tax - new_tax
    assert new_tax == Decimal("97500.00")
    assert old_tax == Decimal("257400.00")


# ---------------------------------------------------------------- API


def test_tax_rules_api_exposes_versions_and_years(client, demo):
    response = client.get("/api/tax/income/rules", headers=demo["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert "2025-26" in body["financial_years"]
    assert body["financial_year"] in body["financial_years"]
    versions = {row["regime"]: row["version"] for row in body["rule_sets"]}
    assert versions == {"new": "FA2025", "old": "FA2025"}
    assert body["rule_sets"][0]["assessment_year"] == "2027-28"
    assert "Chartered accountant" in body["disclaimer"] or "chartered accountant" in body["disclaimer"]


def test_tax_calculator_switches_between_intra_and_inter_state(client, demo):
    intra = client.post(
        "/api/tax/gst/calculate",
        headers=demo["headers"],
        json={
            "place_of_supply_state_code": "27",
            "lines": [{"quantity": "10", "unit_price": "100", "gst_rate": "18"}],
        },
    )
    assert intra.status_code == 200, intra.text
    body = intra.json()
    assert body["supply_type"] == "intra_state"
    assert amount(body["totals"]["cgst_amount"]) == Decimal("90.00")
    assert amount(body["totals"]["sgst_amount"]) == Decimal("90.00")
    assert amount(body["totals"]["igst_amount"]) == Decimal("0.00")
    assert amount(body["totals"]["total_amount"]) == Decimal("1180.00")

    inter = client.post(
        "/api/tax/gst/calculate",
        headers=demo["headers"],
        json={
            "place_of_supply_state_code": "29",
            "lines": [{"quantity": "10", "unit_price": "100", "gst_rate": "18"}],
        },
    )
    assert inter.status_code == 200, inter.text
    body = inter.json()
    assert body["supply_type"] == "inter_state"
    assert amount(body["totals"]["igst_amount"]) == Decimal("180.00")
    assert amount(body["totals"]["cgst_amount"]) == Decimal("0.00")


def test_tax_calculator_handles_inclusive_pricing(client, demo):
    response = client.post(
        "/api/tax/gst/calculate",
        headers=demo["headers"],
        json={
            "place_of_supply_state_code": "27",
            "lines": [
                {"quantity": "1", "unit_price": "1180", "gst_rate": "18", "pricing_mode": "inclusive"}
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert amount(body["totals"]["taxable_value"]) == Decimal("1000.00")
    assert amount(body["totals"]["tax_amount"]) == Decimal("180.00")


def test_tax_calculator_requires_a_place_of_supply(client, demo):
    response = client.post(
        "/api/tax/gst/calculate",
        headers=demo["headers"],
        json={"lines": [{"quantity": "1", "unit_price": "100", "gst_rate": "18"}]},
    )
    assert response.status_code == 400, response.text


def _itc_payload(**overrides) -> dict:
    payload = {
        "supplier_name": "Verma Traders",
        "supplier_gstin": None,
        "invoice_number": "VT/2026/014",
        "invoice_date": (date.today() - timedelta(days=10)).isoformat(),
        "taxable_value": "10000",
        "gst_rate": "18",
        "cgst_amount": "900",
        "sgst_amount": "900",
        "igst_amount": "0",
        "status": "eligible",
    }
    payload.update(overrides)
    return payload


def test_itc_entries_feed_the_net_gst_position(client, demo):
    created = client.post("/api/tax/gst/itc", headers=demo["headers"], json=_itc_payload())
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    assert amount(created.json()["eligible_amount"]) == Decimal("1800.00")

    summary = client.get("/api/tax/gst/itc", headers=demo["headers"])
    assert summary.status_code == 200, summary.text
    assert amount(summary.json()["available_itc"]) == Decimal("1800.00")

    net = client.get("/api/tax/gst/net", headers=demo["headers"])
    assert net.status_code == 200, net.text
    body = net.json()
    assert amount(body["input_tax_credit"]["available"]) == Decimal("1800.00")
    assert body["net_gst"]["direction"] in ("payable", "refundable", "nil")

    blocked = client.patch(
        f"/api/tax/gst/itc/{entry_id}?status=blocked", headers=demo["headers"]
    )
    assert blocked.status_code == 200, blocked.text
    assert amount(blocked.json()["eligible_amount"]) == Decimal("0.00")
    after = client.get("/api/tax/gst/itc", headers=demo["headers"]).json()
    assert amount(after["available_itc"]) == Decimal("0.00")

    deleted = client.delete(f"/api/tax/gst/itc/{entry_id}", headers=demo["headers"])
    assert deleted.status_code == 204, deleted.text


def test_itc_ledger_keeps_bills_older_than_the_report_window(client, demo):
    old = _itc_payload(
        invoice_number="VT/2024/001",
        invoice_date=(date.today() - timedelta(days=900)).isoformat(),
    )
    created = client.post("/api/tax/gst/itc", headers=demo["headers"], json=old)
    assert created.status_code == 201, created.text

    ledger = client.get("/api/tax/gst/itc", headers=demo["headers"])
    assert ledger.status_code == 200, ledger.text
    assert [row["invoice_number"] for row in ledger.json()["entries"]] == ["VT/2024/001"]
    assert amount(ledger.json()["available_itc"]) == Decimal("1800.00")

    ranged = client.get(
        "/api/tax/gst/itc?date_from=2020-01-01&date_to=" + date.today().isoformat(),
        headers=demo["headers"],
    )
    assert ranged.status_code == 200, ranged.text


def test_itc_rejects_mismatched_tax_and_mixed_supply(client, demo):
    bad_tax = client.post(
        "/api/tax/gst/itc", headers=demo["headers"], json=_itc_payload(cgst_amount="100", sgst_amount="100")
    )
    assert bad_tax.status_code == 400, bad_tax.text

    mixed = client.post(
        "/api/tax/gst/itc",
        headers=demo["headers"],
        json=_itc_payload(igst_amount="500", cgst_amount="500", sgst_amount="500"),
    )
    assert mixed.status_code == 400, mixed.text


def test_itc_rejects_claims_above_the_bill(client, demo):
    response = client.post(
        "/api/tax/gst/itc",
        headers=demo["headers"],
        json=_itc_payload(eligible_amount="5000"),
    )
    assert response.status_code == 400, response.text


def test_hsn_classifications_are_crud_and_validated(client, demo):
    created = client.post(
        "/api/tax/gst/hsn",
        headers=demo["headers"],
        json={
            "code": "940330",
            "description": "Wooden office furniture",
            "kind": "goods",
            "gst_rate": "18",
            "verified": True,
        },
    )
    assert created.status_code == 201, created.text
    hsn_id = created.json()["id"]

    duplicate = client.post(
        "/api/tax/gst/hsn",
        headers=demo["headers"],
        json={"code": "940330", "description": "Again", "kind": "goods", "gst_rate": "18"},
    )
    assert duplicate.status_code == 409, duplicate.text

    bad_sac = client.post(
        "/api/tax/gst/hsn",
        headers=demo["headers"],
        json={"code": "12345", "description": "Short SAC", "kind": "services", "gst_rate": "18"},
    )
    assert bad_sac.status_code == 400, bad_sac.text

    updated = client.put(
        f"/api/tax/gst/hsn/{hsn_id}",
        headers=demo["headers"],
        json={
            "code": "940330",
            "description": "Wooden office furniture",
            "kind": "goods",
            "gst_rate": "12",
            "verified": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert amount(updated.json()["gst_rate"]) == Decimal("12.00")

    listed = client.get("/api/tax/gst/hsn", headers=demo["headers"])
    assert listed.status_code == 200
    assert [row["code"] for row in listed.json()["items"]] == ["940330"]

    removed = client.delete(f"/api/tax/gst/hsn/{hsn_id}", headers=demo["headers"])
    assert removed.status_code == 204


def test_gst_report_lists_invoices_with_rate_and_hsn_breakdown(client, demo):
    report = client.get(
        "/api/tax/gst/report",
        params={
            "date_from": (date.today() - timedelta(days=700)).isoformat(),
            "date_to": date.today().isoformat(),
        },
        headers=demo["headers"],
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["totals"]["invoice_count"] == len(body["invoices"])
    assert amount(body["totals"]["tax_amount"]) == sum(
        (amount(row["tax_amount"]) for row in body["invoices"]), Decimal("0.00")
    )
    assert set(body) >= {"period", "invoices", "totals", "by_rate", "by_hsn", "note"}


def test_gst_report_rejects_reversed_period(client, demo):
    response = client.get(
        "/api/tax/gst/report", params={"date_from": "2026-05-01", "date_to": "2026-04-01"}, headers=demo["headers"]
    )
    assert response.status_code == 400


def test_income_estimate_needs_accountant_approval_before_filing(client, demo):
    payload = {
        "financial_year": "2025-26",
        "regime": "new",
        "inputs": {"salary": {"gross_salary": "1275000"}},
    }
    saved = client.post("/api/tax/income/estimates", headers=demo["headers"], json=payload)
    assert saved.status_code == 201, saved.text
    body = saved.json()
    estimate_id = body["id"]
    assert body["status"] == "draft"
    assert amount(body["result"]["tax"]["total_liability"]) == Decimal("0.00")

    early = client.post(
        f"/api/tax/income/estimates/{estimate_id}/approve",
        headers=demo["headers"],
        json={"approved_by_name": "CA R. Iyer", "membership_number": ""},
    )
    assert early.status_code == 422, early.text

    approved = client.post(
        f"/api/tax/income/estimates/{estimate_id}/approve",
        headers=demo["headers"],
        json={
            "approved_by_name": "CA R. Iyer",
            "membership_number": "123456",
            "approval_note": "Checked against the return worksheet.",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by_name"] == "CA R. Iyer"
    assert approved.json()["rule_version"] == "FA2025"

    again = client.post(
        f"/api/tax/income/estimates/{estimate_id}/approve",
        headers=demo["headers"],
        json={"approved_by_name": "CA R. Iyer", "membership_number": "123456"},
    )
    assert again.status_code == 409

    reopened = client.post(
        f"/api/tax/income/estimates/{estimate_id}/reopen", headers=demo["headers"]
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "draft"
    assert reopened.json()["approved_by_name"] is None


def test_saved_estimate_without_a_regime_stores_the_recommended_one(client, demo):
    saved = client.post(
        "/api/tax/income/estimates",
        headers=demo["headers"],
        json={"financial_year": "2025-26", "inputs": {"salary": {"gross_salary": "1500000"}}},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["regime"] == "new"
    assert body["result"]["comparison"]["recommended_regime"] == "new"

    listed = client.get("/api/tax/income/estimates", headers=demo["headers"])
    assert listed.status_code == 200
    assert any(row["id"] == body["id"] for row in listed.json()["items"])


def test_income_tax_calculation_rejects_unknown_financial_year(client, demo):
    response = client.post(
        "/api/tax/income/calculate",
        headers=demo["headers"],
        json={"financial_year": "2019-20", "regime": "new", "inputs": {"salary": {"gross_salary": "1000000"}}},
    )
    assert response.status_code == 400, response.text


def test_tax_overview_returns_current_year_and_quarter_gst(client, demo):
    response = client.get("/api/tax/overview", headers=demo["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["financial_year"] in body["financial_years"]
    assert "net_gst" in body["gst"]
    assert "total_liability" in body["disclaimer"] or isinstance(body["disclaimer"], str)
    assert "salary" in body["empty_inputs"]


def test_tax_routes_are_owner_only(client, developer, other):
    assert client.get("/api/tax/overview", headers=developer["headers"]).status_code == 403
    # A second owner sees only their own rows.
    response = client.get("/api/tax/income/estimates", headers=other["headers"])
    assert response.status_code == 200
    assert response.json()["items"] == []
