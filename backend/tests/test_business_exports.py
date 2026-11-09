from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from openpyxl import load_workbook

from app.services.business_exports import SHEET_NAMES

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _login(client, path, email, password):
    response = client.post(path, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _senior(client):
    return _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")


def _junior(client):
    return _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")


def _client_user(client):
    return _login(client, "/api/auth/login", "demo@finovexa.ai", "Demo1234!")


def _dn_client(client, senior):
    rows = client.get("/api/accounting/senior/clients", headers=senior["headers"]).json()["items"]
    return next(row for row in rows if row["business_name"] == "DN Ventures Pvt. Ltd")


def _sunrise(client, senior):
    rows = client.get("/api/accounting/senior/clients", headers=senior["headers"]).json()["items"]
    return next(row for row in rows if row["business_name"] == "Sunrise Interiors")


def _catalog(client, senior, client_id):
    response = client.get(
        f"/api/accounting/clients/{client_id}/exports/catalog", headers=senior["headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def _period(catalog):
    return {"date_from": catalog["default_from"], "date_to": catalog["default_to"]}


def _preview(client, senior, client_id, catalog, categories=None):
    payload = _period(catalog)
    if categories is not None:
        payload["categories"] = categories
    response = client.post(
        f"/api/accounting/clients/{client_id}/exports/preview",
        headers=senior["headers"],
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_lists_categories_and_years(client):
    senior = _senior(client)
    dn = _dn_client(client, senior)
    catalog = _catalog(client, senior, dn["id"])

    assert [row["key"] for row in catalog["categories"]] == [
        "sales",
        "purchases",
        "receipts",
        "payments",
        "expenses",
        "journals",
        "credit_notes",
        "debit_notes",
        "inventory",
    ]
    assert catalog["financial_years"]
    assert catalog["counts"]["invoices"] > 0
    assert catalog["business"]["business_name"] == "DN Ventures Pvt. Ltd"


def test_preview_reconciles_and_reports_availability(client):
    senior = _senior(client)
    dn = _dn_client(client, senior)
    catalog = _catalog(client, senior, dn["id"])
    body = _preview(client, senior, dn["id"], catalog)

    assert body["tally"]["voucher_count"] > 0
    assert body["tally"]["balanced"] is True
    assert body["reconciliation"]["balanced"] is True
    assert body["tally"]["debit_total"] == body["tally"]["credit_total"]
    checks = {row["key"]: row["status"] for row in body["reconciliation"]["checks"]}
    assert checks["voucher_balance"] == "passed"
    assert checks["source_totals"] == "passed"
    assert checks["gst_match"] == "passed"
    assert checks["duplicate_references"] == "passed"

    availability = {row[0]: row[1] for row in body["availability"]}
    assert set(availability) == set(SHEET_NAMES) - {"Business Summary"}
    assert availability["Credit Notes"] == "Not recorded"
    assert availability["Debit Notes"] == "Not recorded"
    assert availability["Inventory Transactions"] == "Partial"
    assert availability["Stock Summary"] == "Current snapshot"
    assert "not been tested" in body["import_claim"].lower()
    assert body["issues"] is not None


def test_workbook_has_all_fourteen_sheets_and_downloads(client):
    senior = _senior(client)
    dn = _dn_client(client, senior)
    catalog = _catalog(client, senior, dn["id"])
    payload = _period(catalog)

    created = client.post(
        f"/api/accounting/clients/{dn['id']}/exports/workbook",
        headers=senior["headers"],
        json=payload,
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["export_kind"] == "workbook"
    assert record["download_url"].endswith(f"/exports/{record['id']}/download")
    assert record["file_sha256"]
    assert record["row_count"] > 0
    assert record["details"]["import_claim"]

    download = client.get(record["download_url"], headers=senior["headers"])
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == XLSX

    workbook = load_workbook(io.BytesIO(download.content))
    assert tuple(workbook.sheetnames) == SHEET_NAMES
    sales = workbook["Sales Register"]
    headers = [cell.value for cell in sales[1]]
    assert "Transaction Reference" in headers
    assert sales.max_row > 1
    summary = workbook["Business Summary"]
    values = {
        row[0].value: row[1].value
        for row in summary.iter_rows(min_row=1, max_row=30)
        if row[0].value
    }
    assert values["Business"] == "DN Ventures Pvt. Ltd"
    assert "Period from" in values


def test_workbook_keeps_sheets_when_categories_filtered(client):
    senior = _senior(client)
    dn = _dn_client(client, senior)
    catalog = _catalog(client, senior, dn["id"])
    payload = _period(catalog)
    payload["categories"] = ["sales"]

    created = client.post(
        f"/api/accounting/clients/{dn['id']}/exports/workbook",
        headers=senior["headers"],
        json=payload,
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["categories"] == ["sales"]

    download = client.get(record["download_url"], headers=senior["headers"])
    workbook = load_workbook(io.BytesIO(download.content))
    assert tuple(workbook.sheetnames) == SHEET_NAMES
    purchase = workbook["Purchase Register"]
    assert purchase["A2"].value == "No records available for this period."


def test_tally_excel_and_xml_exports(client):
    senior = _senior(client)
    dn = _dn_client(client, senior)
    catalog = _catalog(client, senior, dn["id"])
    payload = _period(catalog)

    excel = client.post(
        f"/api/accounting/clients/{dn['id']}/exports/tally",
        headers=senior["headers"],
        json={**payload, "file_format": "xlsx", "tally_version": "TallyPrime 4.1"},
    )
    assert excel.status_code == 201, excel.text
    excel_record = excel.json()
    assert excel_record["export_kind"] == "tally_excel"
    excel_file = client.get(excel_record["download_url"], headers=senior["headers"])
    assert excel_file.status_code == 200
    workbook = load_workbook(io.BytesIO(excel_file.content))
    for sheet in (
        "Instructions",
        "Summary",
        "Reconciliation",
        "Sales Vouchers",
        "Purchase Vouchers",
        "Voucher Entries",
        "Ledger Masters",
        "Validation",
    ):
        assert sheet in workbook.sheetnames
    reconciliations = workbook["Reconciliation"]
    assert reconciliations.max_row > 1

    xml_export = client.post(
        f"/api/accounting/clients/{dn['id']}/exports/tally",
        headers=senior["headers"],
        json={**payload, "file_format": "xml", "tally_version": "TallyPrime 4.1"},
    )
    assert xml_export.status_code == 201, xml_export.text
    xml_record = xml_export.json()
    assert xml_record["export_kind"] == "tally_xml"
    pack = client.get(xml_record["download_url"], headers=senior["headers"])
    assert pack.status_code == 200
    assert pack.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(pack.content)) as archive:
        names = set(archive.namelist())
        assert {"tally-master-import.xml", "tally-voucher-import.xml", "README.txt"} == names
        voucher_xml = archive.read("tally-voucher-import.xml")
        root = ElementTree.fromstring(voucher_xml)
        assert root.tag == "ENVELOPE"
        vouchers = root.findall(".//VOUCHER")
        assert len(vouchers) == xml_record["row_count"]
        assert xml_record["row_count"] == excel_record["row_count"]
        for voucher in vouchers[:5]:
            entries = voucher.findall("./ALLLEDGERENTRIES.LIST")
            assert entries
            debits = sum(float(e.findtext("AMOUNT") or 0) for e in entries)
            assert abs(debits) < 0.01


def test_history_and_audit_trail(client):
    senior = _senior(client)
    dn = _dn_client(client, senior)
    catalog = _catalog(client, senior, dn["id"])
    _preview(client, senior, dn["id"], catalog)
    created = client.post(
        f"/api/accounting/clients/{dn['id']}/exports/workbook",
        headers=senior["headers"],
        json=_period(catalog),
    )
    assert created.status_code == 201, created.text

    history = client.get(
        f"/api/accounting/clients/{dn['id']}/exports", headers=senior["headers"]
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["count"] >= 1
    assert body["items"][0]["id"] == created.json()["id"]
    assert body["items"][0]["created_by"]

    from app.database import SessionLocal
    from app.models import AuditEvent

    with SessionLocal() as session:
        actions = {
            row.action
            for row in session.query(AuditEvent)
            .filter(AuditEvent.action.like("accounting.business_export_%"))
            .all()
        }
    assert "accounting.business_export_created" in actions
    assert "accounting.business_export_previewed" in actions


def test_export_isolation(client):
    senior = _senior(client)
    junior = _junior(client)
    dn = _dn_client(client, senior)
    sunrise = _sunrise(client, senior)
    catalog = _catalog(client, senior, dn["id"])

    # An assigned junior accountant can read the export catalogue.
    junior_catalog = client.get(
        f"/api/accounting/clients/{dn['id']}/exports/catalog", headers=junior["headers"]
    )
    assert junior_catalog.status_code == 200, junior_catalog.text

    # A client user is never allowed into the export centre.
    customer = _client_user(client)
    denied = client.get(
        f"/api/accounting/clients/{dn['id']}/exports/catalog", headers=customer["headers"]
    )
    assert denied.status_code == 403

    # A record from another engagement cannot be downloaded through this client.
    created = client.post(
        f"/api/accounting/clients/{dn['id']}/exports/workbook",
        headers=senior["headers"],
        json=_period(catalog),
    )
    assert created.status_code == 201, created.text
    cross = client.get(
        f"/api/accounting/clients/{sunrise['id']}/exports/{created.json()['id']}/download",
        headers=senior["headers"],
    )
    assert cross.status_code == 404

    # A client without a linked Business Manager business is rejected, not emptied.
    unlinked = client.get(
        f"/api/accounting/clients/{sunrise['id']}/exports/catalog", headers=senior["headers"]
    )
    assert unlinked.status_code == 409
