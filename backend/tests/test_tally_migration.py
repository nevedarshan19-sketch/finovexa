from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import (
    AccountingHistoricalLedger,
    AccountingHistoricalVoucher,
    AccountingOpeningBalance,
    AccountingVoucher,
)
from app.services.tally_migration import parse_migration_file


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


def _data_url(content: str | bytes, mime: str = "text/csv") -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


SALES_CSV = """Voucher Type,Voucher No,Voucher Date,Party Name,Ledger Name,Debit,Credit,GST Rate,Narration
Sales,S-1001,2024-05-10,Ravi Traders,Ravi Traders,11800,0,18,Sale of goods
Sales,S-1001,2024-05-10,Ravi Traders,Sales Account,0,10000,18,Sale of goods
Sales,S-1001,2024-05-10,Ravi Traders,Output CGST,0,900,18,Sale of goods
Sales,S-1001,2024-05-10,Ravi Traders,Output SGST,0,900,18,Sale of goods
"""


def _migration_payload(client_id: int, **overrides) -> dict:
    body = {
        "client_id": client_id,
        "tally_version": "TallyPrime 4.1",
        "financial_year": "2024-25",
        "import_type": "sales",
        "file_format": "csv",
        "filename": "sales-2024-25.csv",
        "data_url": _data_url(SALES_CSV),
    }
    body.update(overrides)
    return body


def _upload(client, headers, payload):
    response = client.post("/api/accounting/tally-migration/batches", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _live_voucher_count(client_id: int) -> int:
    with SessionLocal() as db:
        return (
            db.query(AccountingVoucher)
            .filter(AccountingVoucher.client_id == client_id)
            .count()
        )


def test_catalog_preview_and_suggested_mapping(client, senior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    catalog = client.get(
        f"/api/accounting/tally-migration/catalog?client_id={meridian['id']}",
        headers=senior["headers"],
    )
    assert catalog.status_code == 200, catalog.text
    body = catalog.json()
    assert len(body["import_types"]) == 12
    formats = {row["key"] for row in body["formats"]}
    assert formats == {"xlsx", "xls", "csv", "xml", "json"}
    assert len(body["mapping_fields"]) >= 20

    preview = client.post(
        "/api/accounting/tally-migration/preview",
        json={
            "file_format": "csv",
            "filename": "sales.csv",
            "data_url": _data_url(SALES_CSV),
        },
        headers=senior["headers"],
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    mapping = data["suggested_mapping"]
    assert mapping["voucher_number"] == "Voucher No"
    assert mapping["voucher_date"] == "Voucher Date"
    assert mapping["ledger_name"] == "Ledger Name"
    assert mapping["debit"] == "Debit"
    assert len(data["sample"]) >= 1


def test_sales_import_approval_creates_history_without_touching_live_ledger(client, senior, junior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    live_before = _live_voucher_count(meridian["id"])

    batch = _upload(client, junior["headers"], _migration_payload(meridian["id"]))
    assert batch["status"] == "validated"
    assert batch["import_type"] == "sales"
    assert batch["row_count"] == 1
    assert batch["error_count"] == 0
    assert batch["warning_count"] == 1
    assert batch["duplicate_count"] == 0
    codes = {issue["code"] for issue in batch["validation"]["issues"]}
    assert "missing_ledger" in codes
    assert "unmatched_party" in codes

    submit = client.post(
        f"/api/accounting/tally-migration/batches/{batch['id']}/submit",
        headers=junior["headers"],
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "pending_approval"

    # A junior may not approve.
    denied = client.post(
        f"/api/accounting/tally-migration/batches/{batch['id']}/decision",
        json={"decision": "approve"},
        headers=junior["headers"],
    )
    assert denied.status_code == 403

    approved = client.post(
        f"/api/accounting/tally-migration/batches/{batch['id']}/decision",
        json={"decision": "approve", "note": "Checked against the client's Tally backup."},
        headers=senior["headers"],
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["batch"]["status"] == "imported"
    assert body["batch"]["imported_count"] == 1

    with SessionLocal() as db:
        vouchers = (
            db.query(AccountingHistoricalVoucher)
            .filter(AccountingHistoricalVoucher.client_id == meridian["id"])
            .all()
        )
        assert len(vouchers) == 1
        voucher = vouchers[0]
        assert voucher.number == "S-1001"
        assert voucher.voucher_type == "sale"
        assert voucher.total_debit == Decimal("11800.00")
        assert voucher.total_credit == Decimal("11800.00")
        assert voucher.taxable_value == Decimal("10000.00")
        assert voucher.cgst_amount == Decimal("900.00")
        assert voucher.sgst_amount == Decimal("900.00")
        assert len(voucher.lines) == 4
        ledgers = {
            row.name
            for row in db.query(AccountingHistoricalLedger)
            .filter(AccountingHistoricalLedger.client_id == meridian["id"])
            .all()
        }
        assert {"Ravi Traders", "Sales Account", "Output CGST", "Output SGST"} <= ledgers

    assert _live_voucher_count(meridian["id"]) == live_before

    reports = client.get(
        f"/api/accounting/tally-migration/reports?client_id={meridian['id']}&financial_year=2024-25",
        headers=senior["headers"],
    )
    assert reports.status_code == 200, reports.text
    bundle = reports.json()
    assert bundle["trial_balance"]["totals"]["closing_debit"] == bundle["trial_balance"]["totals"]["closing_credit"]
    assert bundle["profit_loss"]["revenue_total"] > 0
    assert bundle["gst"]["output"]["total_tax"] == 1800.0
    assert bundle["gst"]["output"]["cgst"] == 900.0
    assert bundle["gst"]["net_payable"] == 1800.0
    assert bundle["sales"]["gst"] == 1800.0
    assert bundle["profit_loss"]["revenue_total"] == 10000.0
    assert bundle["monthly"][0]["revenue"] == 10000.0
    assert bundle["live"]["vouchers"] == 0
    assert "not included" in bundle["live"]["label"]
    assert "no Tally connection" in bundle["source_note"]

    reimport = _upload(client, senior["headers"], _migration_payload(meridian["id"]))
    assert reimport["duplicate_count"] == 1
    blocked = client.post(
        f"/api/accounting/tally-migration/batches/{reimport['id']}/submit",
        headers=senior["headers"],
    )
    assert blocked.status_code == 409

    rolled = client.post(
        f"/api/accounting/tally-migration/batches/{batch['id']}/rollback",
        json={"note": "Demo reset after test."},
        headers=senior["headers"],
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["batch"]["status"] == "rolled_back"
    with SessionLocal() as db:
        assert (
            db.query(AccountingHistoricalVoucher)
            .filter(AccountingHistoricalVoucher.client_id == meridian["id"])
            .count()
            == 0
        )


def test_unbalanced_and_out_of_year_rows_block_submission(client, senior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    csv_text = """Voucher Type,Voucher No,Voucher Date,Party Name,Ledger Name,Debit,Credit
Sales,U-1,2024-06-01,Acme,Acme,100,0
Sales,U-1,2024-06-01,Acme,Sales,0,90
"""
    batch = _upload(
        client,
        senior["headers"],
        _migration_payload(meridian["id"], filename="unbalanced.csv", data_url=_data_url(csv_text)),
    )
    assert batch["error_count"] == 1
    assert any(issue["code"] == "unbalanced" for issue in batch["validation"]["issues"])
    submit = client.post(
        f"/api/accounting/tally-migration/batches/{batch['id']}/submit",
        headers=senior["headers"],
    )
    assert submit.status_code == 409
    assert "Correct the validation errors" in submit.text

    fy_csv = """Voucher Type,Voucher No,Voucher Date,Party Name,Ledger Name,Debit,Credit
Sales,FY-1,2023-06-01,Acme,Acme,100,0
Sales,FY-1,2023-06-01,Acme,Sales,0,100
"""
    fy_batch = _upload(
        client,
        senior["headers"],
        _migration_payload(meridian["id"], filename="wrong-fy.csv", data_url=_data_url(fy_csv)),
    )
    assert any(issue["code"] == "financial_year" for issue in fy_batch["validation"]["issues"])


OPENING_CSV = """Ledger Name,Ledger Group,Debit,Credit,Stock Item,Quantity,Rate
Cash-in-Hand,Cash-in-Hand,50000,0,,,
Sundry Debtors,Sundry Debtors,25000,0,,,
Closing Stock,Stock-in-Hand,15000,0,Fabric Roll,10,1500
Capital Account,Capital Account,0,90000,,,
"""


def test_opening_balance_import_and_double_count_guard(client, senior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    payload = _migration_payload(
        meridian["id"],
        import_type="opening_balances",
        opening_date="2024-04-01",
        filename="opening-2024-25.csv",
        data_url=_data_url(OPENING_CSV),
    )
    batch = _upload(client, senior["headers"], payload)
    assert batch["direction"] == "opening_balance"
    assert batch["error_count"] == 0, batch["validation"]

    submit = client.post(
        f"/api/accounting/tally-migration/batches/{batch['id']}/submit",
        headers=senior["headers"],
    )
    assert submit.status_code == 200, submit.text
    approved = client.post(
        f"/api/accounting/tally-migration/batches/{batch['id']}/decision",
        json={"decision": "approve"},
        headers=senior["headers"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["batch"]["status"] == "imported"

    with SessionLocal() as db:
        opening = (
            db.query(AccountingOpeningBalance)
            .filter(AccountingOpeningBalance.client_id == meridian["id"])
            .one()
        )
        assert opening.status == "approved"
        assert opening.total_debit == Decimal("90000.00")
        assert opening.total_credit == Decimal("90000.00")
        assert opening.stock_value == Decimal("15000.00")

    blocked = client.post(
        "/api/accounting/tally-migration/batches",
        json=_migration_payload(meridian["id"]),
        headers=senior["headers"],
    )
    assert blocked.status_code == 409
    assert "double count" in blocked.text

    second = client.post(
        "/api/accounting/tally-migration/batches",
        json=payload,
        headers=senior["headers"],
    )
    assert second.status_code == 409


def test_opening_must_balance(client, senior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    csv_text = """Ledger Name,Ledger Group,Debit,Credit
Cash-in-Hand,Cash-in-Hand,1000,0
Capital Account,Capital Account,0,900
"""
    batch = _upload(
        client,
        senior["headers"],
        _migration_payload(
            meridian["id"],
            import_type="opening_balances",
            opening_date="2024-04-01",
            filename="opening-bad.csv",
            data_url=_data_url(csv_text),
        ),
    )
    assert batch["error_count"] >= 1
    assert any(issue["code"] == "opening_unbalanced" for issue in batch["validation"]["issues"])


def test_client_isolation(client, senior, customer):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    batch = _upload(client, senior["headers"], _migration_payload(meridian["id"]))
    denied = client.get(
        f"/api/accounting/tally-migration/batches/{batch['id']}",
        headers=customer["headers"],
    )
    assert denied.status_code == 403
    denied_upload = client.post(
        "/api/accounting/tally-migration/batches",
        json=_migration_payload(meridian["id"]),
        headers=customer["headers"],
    )
    assert denied_upload.status_code == 403


def test_mapping_template_round_trip(client, senior, junior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    created = client.post(
        "/api/accounting/tally-migration/mappings",
        json={
            "name": "Meridian sales CSV",
            "client_id": meridian["id"],
            "file_format": "csv",
            "import_type": "sales",
            "mapping": {"voucher_number": "Voucher No", "voucher_date": "Voucher Date"},
        },
        headers=junior["headers"],
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["name"] == "Meridian sales CSV"

    listing = client.get(
        f"/api/accounting/tally-migration/mappings?client_id={meridian['id']}",
        headers=junior["headers"],
    )
    assert listing.status_code == 200
    assert any(row["id"] == template["id"] for row in listing.json()["items"])

    upload = _upload(
        client,
        junior["headers"],
        _migration_payload(meridian["id"], mapping_template_id=template["id"], filename="template.csv"),
    )
    assert upload["mapping"]["voucher_number"] == "Voucher No"

    patched = client.patch(
        f"/api/accounting/tally-migration/mappings/{template['id']}",
        json={"name": "Meridian sales CSV v2"},
        headers=junior["headers"],
    )
    assert patched.status_code == 200
    removed = client.delete(
        f"/api/accounting/tally-migration/mappings/{template['id']}",
        headers=junior["headers"],
    )
    assert removed.status_code == 200


XML_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <BODY>
    <DATA>
      <TALLYMESSAGE xmlns:UDF="TallyUDF">
        <VOUCHER VCHTYPE="Sales" ACTION="Create">
          <DATE>20240515</DATE>
          <VOUCHERNUMBER>S-2001</VOUCHERNUMBER>
          <PARTYLEDGERNAME>Ravi Traders</PARTYLEDGERNAME>
          <NARRATION>Sale of fabric</NARRATION>
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Ravi Traders</LEDGERNAME>
            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
            <AMOUNT>-11800</AMOUNT>
          </ALLLEDGERENTRIES.LIST>
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Sales Account</LEDGERNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <AMOUNT>10000</AMOUNT>
          </ALLLEDGERENTRIES.LIST>
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Output CGST</LEDGERNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <AMOUNT>900</AMOUNT>
          </ALLLEDGERENTRIES.LIST>
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Output SGST</LEDGERNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <AMOUNT>900</AMOUNT>
          </ALLLEDGERENTRIES.LIST>
        </VOUCHER>
      </TALLYMESSAGE>
    </DATA>
  </BODY>
</ENVELOPE>
"""


def test_xml_voucher_sign_conversion():
    rows, note = parse_migration_file(XML_SAMPLE.encode("utf-8"), "xml")
    assert note
    assert len(rows) == 4
    first = rows[0]
    assert first["voucher_number"] == "S-2001"
    assert first["voucher_date"] == "2024-05-15"
    assert Decimal(str(first["debit"])) == Decimal("11800")
    assert Decimal(str(rows[1]["credit"])) == Decimal("10000")


JSON_SAMPLE = json.dumps(
    {
        "vouchers": [
            {
                "voucher_type": "Sales",
                "voucher_number": "J-3001",
                "voucher_date": "2024-07-01",
                "party_name": "Ravi Traders",
                "ledger_name": "Ravi Traders",
                "debit": 2360,
                "credit": 0,
                "gst_rate": 18,
            },
            {
                "voucher_type": "Sales",
                "voucher_number": "J-3001",
                "voucher_date": "2024-07-01",
                "party_name": "Ravi Traders",
                "ledger_name": "Sales Account",
                "debit": 0,
                "credit": 2000,
                "gst_rate": 18,
            },
            {
                "voucher_type": "Sales",
                "voucher_number": "J-3001",
                "voucher_date": "2024-07-01",
                "party_name": "Ravi Traders",
                "ledger_name": "Output GST",
                "debit": 0,
                "credit": 360,
                "gst_rate": 18,
            },
        ]
    }
)


def test_json_voucher_rows():
    rows, note = parse_migration_file(JSON_SAMPLE.encode("utf-8"), "json")
    assert note
    assert len(rows) == 3
    assert rows[0]["VOUCHER_NUMBER"] == "J-3001"
    assert Decimal(str(rows[0]["DEBIT"])) == Decimal("2360")


def test_xlsx_voucher_import(client, senior):
    from openpyxl import Workbook

    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        ["Voucher Type", "Voucher No", "Voucher Date", "Party Name", "Ledger Name", "Debit", "Credit"]
    )
    sheet.append(["Sales", "X-1", "2024-08-01", "Ravi Traders", "Ravi Traders", 590, 0])
    sheet.append(["Sales", "X-1", "2024-08-01", "Ravi Traders", "Sales Account", 0, 500])
    sheet.append(["Sales", "X-1", "2024-08-01", "Ravi Traders", "Output GST", 0, 90])
    import io

    buffer = io.BytesIO()
    workbook.save(buffer)

    payload = _migration_payload(
        meridian["id"],
        file_format="xlsx",
        filename="sales.xlsx",
        data_url=_data_url(
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )
    batch = _upload(client, senior["headers"], payload)
    assert batch["row_count"] == 1
    assert batch["error_count"] == 0


def test_seeded_historical_reports_and_year_comparison(client, senior):
    clients = _clients(client, senior["headers"])
    sunrise = clients["Sunrise Interiors"]

    years = client.get(
        f"/api/accounting/tally-migration/years?client_id={sunrise['id']}",
        headers=senior["headers"],
    )
    assert years.status_code == 200
    assert {"2023-24", "2024-25"} <= set(years.json()["years"])

    bundle = client.get(
        f"/api/accounting/tally-migration/reports?client_id={sunrise['id']}&financial_year=2024-25",
        headers=senior["headers"],
    ).json()
    assert bundle["counts"]["vouchers"] == 7
    assert bundle["counts"]["opening_balance"] is True
    assert bundle["profit_loss"]["revenue_total"] == 210000.0
    assert bundle["profit_loss"]["expense_total"] == 120000.0
    assert bundle["profit_loss"]["net_profit"] == 90000.0
    assert bundle["trial_balance"]["totals"]["difference"] == 0.0
    assert bundle["balance_sheet"]["difference"] == 0.0
    assert bundle["monthly"]
    assert bundle["gst"]["net_payable"] > 0

    comparison = client.get(
        f"/api/accounting/tally-migration/reports/compare?client_id={sunrise['id']}&financial_year=2024-25",
        headers=senior["headers"],
    )
    assert comparison.status_code == 200, comparison.text
    rows = {row["financial_year"]: row for row in comparison.json()["years"]}
    assert rows["2024-25"]["revenue"] == 210000.0
    assert rows["2023-24"]["revenue"] == 160000.0
    assert rows["2024-25"]["net_profit"] == 90000.0
    assert rows["2023-24"]["net_profit"] == 120000.0

    ledger_report = client.get(
        f"/api/accounting/tally-migration/reports/ledger?client_id={sunrise['id']}&financial_year=2024-25&ledger=HDFC%20Bank%20-%20Current",
        headers=senior["headers"],
    )
    assert ledger_report.status_code == 200, ledger_report.text
    assert ledger_report.json()["closing"] == 220000.0
