from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import AccountingStockItem, AccountingVoucher

ALL_TYPES = [
    "sales",
    "purchase",
    "payment",
    "receipt",
    "expense",
    "ledger_masters",
    "stock_masters",
]


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


def _payload(client_id: int, **overrides) -> dict:
    body = {
        "client_id": client_id,
        "export_types": list(ALL_TYPES),
        "file_format": "xlsx",
    }
    body.update(overrides)
    return body


def test_catalog_and_balanced_validation(client, senior, junior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]

    catalog = client.get(
        f"/api/accounting/tally/catalog?client_id={meridian['id']}", headers=junior["headers"]
    )
    assert catalog.status_code == 200, catalog.text
    body = catalog.json()
    assert len(body["types"]) == 7
    counts = {row["key"]: row["record_count"] for row in body["types"]}
    assert counts["sales"] == 3
    assert counts["purchase"] == 2
    assert counts["payment"] == 1
    assert counts["receipt"] == 1
    assert counts["expense"] == 1
    assert counts["stock_masters"] == 3
    assert body["stock_item_count"] == 3
    assert "not connect to Tally" in body["note"]

    validate = client.post(
        "/api/accounting/tally/exports/validate",
        headers=junior["headers"],
        json=_payload(meridian["id"]),
    )
    assert validate.status_code == 200, validate.text
    report = validate.json()
    assert report["ok"] is True, report["errors"]
    assert report["error_count"] == 0
    summary = report["summary"]
    assert summary["voucher_count"] == 8
    assert summary["entry_count"] == 25  # the inter-state sale carries one IGST line, not CGST+SGST
    assert summary["balanced"] is True
    assert summary["debit_total"] == summary["credit_total"] == "413320.00"
    by_type = {row["export_type"]: row for row in summary["by_type"]}
    assert by_type["sales"]["voucher_count"] == 3
    assert by_type["sales"]["total"] == "271400.00"
    assert by_type["purchase"]["total"] == "51920.00"
    assert by_type["receipt"]["total"] == "60000.00"
    assert by_type["payment"]["total"] == "12000.00"
    assert by_type["expense"]["total"] == "18000.00"
    assert {check["key"]: check["status"] for check in report["checks"]}["debit_credit"] == "passed"
    assert all(check["status"] == "passed" for check in report["checks"])


def test_prepare_requires_senior_approval_before_download(client, senior, junior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    created = client.post(
        "/api/accounting/tally/exports", headers=junior["headers"], json=_payload(meridian["id"])
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    assert batch["status"] == "pending_approval"
    assert batch["prepared_by"] == "Junior Accountant" or batch["prepared_by"]
    assert batch["approved_by"] is None
    assert batch["filename"].endswith(".xlsx")
    assert batch["download_url"] is None
    assert batch["validation"]["ok"] is True

    blocked = client.get(
        f"/api/accounting/tally/exports/{batch['id']}/download", headers=junior["headers"]
    )
    assert blocked.status_code == 403
    assert "approve" in blocked.json()["detail"].lower()

    junior_decision = client.post(
        f"/api/accounting/tally/exports/{batch['id']}/decision",
        headers=junior["headers"],
        json={"decision": "approve"},
    )
    assert junior_decision.status_code == 403

    missing_note = client.post(
        f"/api/accounting/tally/exports/{batch['id']}/decision",
        headers=senior["headers"],
        json={"decision": "reject"},
    )
    assert missing_note.status_code == 422

    approved = client.post(
        f"/api/accounting/tally/exports/{batch['id']}/decision",
        headers=senior["headers"],
        json={"decision": "approve", "note": "Checked against the sales register."},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "approved"
    assert approved_body["approved_at"]
    assert approved_body["import_status"] == "not_imported"
    assert approved_body["download_url"].endswith("/download")

    download = client.get(approved_body["download_url"], headers=junior["headers"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert download.content[:2] == b"PK"

    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(download.content), read_only=True)
    assert {
        "Instructions",
        "Summary",
        "Sales Vouchers",
        "Purchase Vouchers",
        "Payment Vouchers",
        "Receipt Vouchers",
        "Expense Entries",
        "Voucher Entries",
        "Ledger Masters",
        "Stock Item Masters",
        "Validation",
    } <= set(workbook.sheetnames)
    summary_rows = list(workbook["Summary"].iter_rows(values_only=True))
    flat = {str(row[0]): row[1] for row in summary_rows if row and row[0]}
    assert flat["Total debit"] == "413320.00"
    assert flat["Debit equals credit"] == "Yes"
    sales_rows = list(workbook["Sales Vouchers"].iter_rows(values_only=True))
    assert len(sales_rows) == 4  # header + three seeded sales
    workbook.close()

    imported = client.post(
        f"/api/accounting/tally/exports/{batch['id']}/import-status",
        headers=junior["headers"],
        json={"import_status": "imported", "note": "Imported into TallyPrime on 2026-11-02."},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["import_status"] == "imported"

    history = client.get(
        f"/api/accounting/tally/exports?client_id={meridian['id']}", headers=senior["headers"]
    )
    assert history.status_code == 200
    rows = history.json()["items"]
    assert rows[0]["id"] == batch["id"]
    assert rows[0]["approved_by"]
    assert rows[0]["import_status"] == "imported"

    audit = client.get(
        f"/api/accounting/senior/audit?client_id={meridian['id']}&limit=50", headers=senior["headers"]
    )
    actions = {row["action"] for row in audit.json()["items"]}
    assert "accounting.tally_export_prepared" in actions
    assert "accounting.tally_export_approved" in actions
    assert "accounting.tally_export_downloaded" in actions
    assert "accounting.tally_import_status" in actions


def test_csv_bundle_contains_vouchers_masters_and_tally_xml(client, senior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    created = client.post(
        "/api/accounting/tally/exports",
        headers=senior["headers"],
        json=_payload(meridian["id"], file_format="csv_zip"),
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    approved = client.post(
        f"/api/accounting/tally/exports/{batch['id']}/decision",
        headers=senior["headers"],
        json={"decision": "approve", "note": "Self-reviewed: demo practice data."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["details"]["self_approved"] is True

    download = client.get(
        f"/api/accounting/tally/exports/{batch['id']}/download", headers=senior["headers"]
    )
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = set(archive.namelist())
    assert {
        "sales-vouchers.csv",
        "purchase-vouchers.csv",
        "payment-vouchers.csv",
        "receipt-vouchers.csv",
        "expense-vouchers.csv",
        "voucher-entries.csv",
        "ledger-masters.csv",
        "stock-item-masters.csv",
        "validation-report.csv",
        "tally-voucher-import.xml",
        "tally-master-import.xml",
        "README.txt",
    } == names

    sales_csv = archive.read("sales-vouchers.csv").decode("utf-8")
    assert sales_csv.splitlines()[0].startswith("Voucher Date,Voucher Type,Voucher Number")
    assert len(sales_csv.splitlines()) == 4
    assert "Vertex Interiors" in sales_csv

    entries = archive.read("voucher-entries.csv").decode("utf-8").splitlines()
    assert entries[0].startswith("Voucher Date,Voucher Type,Voucher Number,Party,Party GSTIN,Ledger")
    total_debit = sum(
        Decimal(row.split(",")[7]) for row in entries[1:] if row.split(",")[7]
    )
    assert total_debit == Decimal("413320.00")

    masters = archive.read("ledger-masters.csv").decode("utf-8")
    assert "Sundry Debtors" in masters
    assert "Duties & Taxes" in masters
    stock = archive.read("stock-item-masters.csv").decode("utf-8")
    assert "LiftDesk Pro" in stock and "9403" in stock

    voucher_xml = archive.read("tally-voucher-import.xml").decode("utf-8")
    assert "<ENVELOPE>" in voucher_xml and "<TALLYMESSAGE" in voucher_xml
    assert "<VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>" in voucher_xml
    assert "<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>" in voucher_xml
    assert "<AMOUNT>-118000.00</AMOUNT>" in voucher_xml
    assert "Meridian Traders" in voucher_xml
    master_xml = archive.read("tally-master-import.xml").decode("utf-8")
    assert "<LEDGER NAME=\"Vertex Interiors\"" in master_xml
    assert "<STOCKITEM NAME=\"LiftDesk Pro\"" in master_xml
    readme = archive.read("README.txt").decode("utf-8")
    assert "does not connect to, read from or post into a Tally installation" in readme
    assert "manual step" in readme


def test_validation_reports_duplicates_bad_gstin_and_gst_mismatch(client, senior, junior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    month = date.today().replace(day=1)

    def voucher(**overrides):
        body = {
            "client_id": meridian["id"],
            "voucher_type": "sale",
            "number": "DUP-1",
            "voucher_date": (month + timedelta(days=1)).isoformat(),
            "party_name": "Duplicate Customer",
            "party_gstin": "27AABCV1111C1Z9",
            "ledger_name": "Sales - furniture",
            "taxable_value": "1000.00",
            "gst_rate": "18.00",
        }
        body.update(overrides)
        return body

    first = client.post("/api/accounting/vouchers", headers=junior["headers"], json=voucher())
    assert first.status_code == 201, first.text
    second = client.post(
        "/api/accounting/vouchers",
        headers=junior["headers"],
        json=voucher(voucher_date=(month + timedelta(days=2)).isoformat(), taxable_value="2000.00"),
    )
    assert second.status_code == 201, second.text
    bad_gstin = client.post(
        "/api/accounting/vouchers",
        headers=junior["headers"],
        json=voucher(number="BAD-GSTIN", voucher_date=(month + timedelta(days=3)).isoformat(),
                     party_gstin="INVALIDGSTIN"),
    )
    assert bad_gstin.status_code == 201, bad_gstin.text

    window = {
        "from_date": (month + timedelta(days=1)).isoformat(),
        "to_date": (month + timedelta(days=3)).isoformat(),
    }
    report = client.post(
        "/api/accounting/tally/exports/validate",
        headers=junior["headers"],
        json=_payload(meridian["id"], export_types=["sales"], **window),
    ).json()
    codes = {entry["code"] for entry in report["errors"]}
    assert "DUPLICATE_VOUCHER_NUMBER" in codes
    assert "INVALID_PARTY_GSTIN" in codes
    assert report["ok"] is False

    rejected = client.post(
        "/api/accounting/tally/exports",
        headers=junior["headers"],
        json=_payload(meridian["id"], export_types=["sales"], **window),
    )
    assert rejected.status_code == 422
    detail = rejected.json()["detail"]
    assert "no figure was changed" in detail["message"]
    assert detail["validation"]["error_count"] >= 2

    # Tamper directly with a stored GST split. Validation must report it and never rewrite it.
    with SessionLocal() as db:
        stored = (
            db.query(AccountingVoucher)
            .filter(AccountingVoucher.number == "DUP-1", AccountingVoucher.client_id == meridian["id"])
            .order_by(AccountingVoucher.voucher_date)
            .first()
        )
        stored.sgst_amount = Decimal("1.00")
        db.commit()
        stored_id = stored.id

    tampered = client.post(
        "/api/accounting/tally/exports/validate",
        headers=junior["headers"],
        json=_payload(meridian["id"], export_types=["sales"], **window),
    ).json()
    mismatch = [
        entry for entry in tampered["errors"] if entry["code"] == "GST_SPLIT_MISMATCH"
    ]
    assert mismatch and mismatch[0]["voucher_number"] == "DUP-1"
    assert mismatch[0]["stored"].startswith("CGST 90.00 / SGST 1.00 / IGST 0.00")

    with SessionLocal() as db:
        unchanged = db.get(AccountingVoucher, stored_id)
        assert unchanged.sgst_amount == Decimal("1.00")


def test_stock_masters_and_client_isolation(client, senior, junior, customer):
    clients = _clients(client, senior["headers"])
    meridian = clients["Meridian Traders"]
    sunrise = clients["Sunrise Interiors"]

    assert (
        client.get(
            f"/api/accounting/tally/catalog?client_id={sunrise['id']}", headers=junior["headers"]
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/accounting/tally/catalog?client_id={meridian['id']}", headers=customer["headers"]
        ).status_code
        == 403
    )

    created = client.post(
        "/api/accounting/tally/stock-items",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "name": "Meeting Table",
            "sku": "fp-mt-04",
            "unit": "Nos",
            "hsn_sac": "9403",
            "gst_rate": "18.00",
            "opening_qty": "8.000",
            "opening_rate": "9500.00",
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["sku"] == "FP-MT-04"
    assert Decimal(str(item["opening_value"])) == Decimal("76000.00")

    duplicate = client.post(
        "/api/accounting/tally/stock-items",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "name": "Another table",
            "sku": "FP-MT-04",
            "unit": "Nos",
        },
    )
    assert duplicate.status_code == 409

    updated = client.patch(
        f"/api/accounting/tally/stock-items/{item['id']}",
        headers=junior["headers"],
        json={"opening_qty": "0.000", "is_active": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_active"] is False

    listed = client.get(
        f"/api/accounting/tally/stock-items?client_id={meridian['id']}", headers=junior["headers"]
    ).json()["items"]
    assert item["id"] not in {row["id"] for row in listed}
    assert len(listed) == 3

    inactive = client.get(
        f"/api/accounting/tally/stock-items?client_id={meridian['id']}&include_inactive=true",
        headers=junior["headers"],
    ).json()["items"]
    assert item["id"] in {row["id"] for row in inactive}

    other_stock = client.get(
        f"/api/accounting/tally/stock-items?client_id={sunrise['id']}", headers=junior["headers"]
    )
    assert other_stock.status_code == 403
    assert (
        client.get(
            f"/api/accounting/tally/stock-items?client_id={meridian['id']}",
            headers=customer["headers"],
        ).status_code
        == 403
    )


def test_rejection_flow_and_import_status_guard(client, senior, junior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    created = client.post(
        "/api/accounting/tally/exports",
        headers=junior["headers"],
        json=_payload(meridian["id"], export_types=["sales", "ledger_masters"]),
    )
    assert created.status_code == 201, created.text
    batch = created.json()

    rejected = client.post(
        f"/api/accounting/tally/exports/{batch['id']}/decision",
        headers=senior["headers"],
        json={"decision": "reject", "note": "Ledger group for furniture sales needs confirmation."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["approval_note"].startswith("Ledger group")

    assert (
        client.get(
            f"/api/accounting/tally/exports/{batch['id']}/download", headers=junior["headers"]
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/accounting/tally/exports/{batch['id']}/import-status",
            headers=junior["headers"],
            json={"import_status": "imported"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/accounting/tally/exports/{batch['id']}/decision",
            headers=senior["headers"],
            json={"decision": "approve"},
        ).status_code
        == 409
    )

    # A rejected batch cannot be downloaded, and the next batch starts a new approval cycle.
    again = client.post(
        "/api/accounting/tally/exports",
        headers=junior["headers"],
        json=_payload(meridian["id"], export_types=["sales"]),
    )
    assert again.status_code == 201
    assert again.json()["id"] != batch["id"]
    assert again.json()["status"] == "pending_approval"

    history = client.get(
        f"/api/accounting/tally/exports?client_id={meridian['id']}", headers=senior["headers"]
    ).json()
    assert history["pending_approval_count"] == 1
    assert len(history["items"]) == 2


def test_linked_dn_ventures_business_exports(client, senior, junior):
    clients = _clients(client, senior["headers"])
    dn_ventures = clients["DN Ventures Pvt. Ltd"]
    assert dn_ventures["business_profile_id"]
    assert dn_ventures["linked_business"]["id"] == dn_ventures["business_profile_id"]

    catalog = client.get(
        f"/api/accounting/tally/catalog?client_id={dn_ventures['id']}", headers=junior["headers"]
    )
    assert catalog.status_code == 200, catalog.text
    counts = {row["key"]: row["record_count"] for row in catalog.json()["types"]}
    assert counts["sales"] == 2
    assert counts["purchase"] == 1
    assert counts["payment"] == 1
    assert counts["receipt"] == 1
    assert counts["expense"] == 1
    assert counts["stock_masters"] == 3

    report = client.post(
        "/api/accounting/tally/exports/validate",
        headers=junior["headers"],
        json=_payload(dn_ventures["id"]),
    ).json()
    assert report["ok"] is True, report["errors"]
    assert report["summary"]["voucher_count"] == 6
    assert report["summary"]["balanced"] is True
    assert report["summary"]["debit_total"] == report["summary"]["credit_total"]


def test_empty_period_is_a_warning_not_an_error(client, senior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    report = client.post(
        "/api/accounting/tally/exports/validate",
        headers=senior["headers"],
        json=_payload(
            meridian["id"],
            export_types=["sales"],
            from_date="2019-04-01",
            to_date="2019-04-30",
        ),
    ).json()
    assert report["ok"] is True
    assert report["summary"]["voucher_count"] == 0
    assert any(entry["code"] == "NO_RECORDS" for entry in report["warnings"])

    with SessionLocal() as db:
        assert (
            db.query(AccountingStockItem)
            .filter(AccountingStockItem.client_id == meridian["id"])
            .count()
            == 3
        )

def test_xml_and_json_exports_and_version_rules(client, senior):
    meridian = _clients(client, senior["headers"])["Meridian Traders"]

    catalog = client.get(
        f"/api/accounting/tally/catalog?client_id={meridian['id']}", headers=senior["headers"]
    ).json()
    formats = {row["key"] for row in catalog["formats"]}
    assert {"xlsx", "csv_zip", "xml", "json"} <= formats
    versions = {row["key"]: row["formats"] for row in catalog["tally_versions"]}
    assert "json" in versions["TallyPrime 4.1"]
    assert "json" not in versions["Tally ERP 9"]

    bad_version = client.post(
        "/api/accounting/tally/exports",
        headers=senior["headers"],
        json=_payload(meridian["id"], file_format="json", tally_version="Tally ERP 9"),
    )
    assert bad_version.status_code == 422

    for file_format, content_type, signature in (
        ("xml", "application/xml", b"<ENVELOPE"),
        ("json", "application/json", b"{"),
    ):
        created = client.post(
            "/api/accounting/tally/exports",
            headers=senior["headers"],
            json=_payload(
                meridian["id"],
                file_format=file_format,
                tally_version="TallyPrime 4.1",
            ),
        )
        assert created.status_code == 201, created.text
        batch = created.json()
        assert batch["filename"].endswith(f".{file_format}")
        assert batch["details"]["tally_version"] == "TallyPrime 4.1"
        approved = client.post(
            f"/api/accounting/tally/exports/{batch['id']}/decision",
            headers=senior["headers"],
            json={"decision": "approve", "note": "Version-specific export checked."},
        )
        assert approved.status_code == 200, approved.text
        download = client.get(approved.json()["download_url"], headers=senior["headers"])
        assert download.status_code == 200
        assert download.headers["content-type"].startswith(content_type)
        assert download.content.startswith(signature)

        if file_format == "xml":
            assert b"<VOUCHER" in download.content
            assert b"<LEDGER " in download.content
        else:
            payload = json.loads(download.content)
            assert payload["company"] == meridian["business_name"]
            assert len(payload["vouchers"]) == 8
            assert all(
                sum(Decimal(entry["debit"]) for entry in voucher["entries"])
                == sum(Decimal(entry["credit"]) for entry in voucher["entries"])
                for voucher in payload["vouchers"]
            )
