"""File-based Tally historical data migration.

This module reads TallyPrime exports (Excel, CSV, XML, JSON) and stages them for
review. Nothing is posted into the live FINOVEXA ledger: approved batches are
written to dedicated historical tables, so imported history and newly recorded
transactions stay distinguishable. No connection to a Tally installation is made.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..accounting_catalog import (
    TALLY_MAPPING_FIELDS,
    TALLY_MIGRATION_IMPORT_LABELS,
    TALLY_RECORD_TYPES,
    TALLY_VERSION_FORMATS,
)
from ..config import settings
from ..models import (
    AccountingClient,
    AccountingHistoricalLedger,
    AccountingHistoricalVoucher,
    AccountingHistoricalVoucherLine,
    AccountingOpeningBalance,
    AccountingOpeningBalanceLine,
    AccountingStockItem,
    AccountingTallyMappingTemplate,
    AccountingTallyMigration,
    AccountingTallyMigrationRow,
    AccountingVoucher,
    User,
    utcnow,
)
from .accounting_math import financial_year_bounds
from .finance import q2

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
MAX_IMPORT_RECORDS = 20_000


# ---------------------------------------------------------------- parsing


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return q2(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return None
    raw = str(value).strip()
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    raw = re.sub(r"(?i)\b(rs\.?|inr|₹)", "", raw)
    raw = raw.replace(",", "").replace(" ", "")
    raw = re.sub(r"(?i)(dr|cr)$", "", raw)
    if raw in ("", "-", "+"):
        return None
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return q2(-parsed if negative else parsed)


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%m-%y",
    "%d/%m/%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y%m%d",
    "%d.%m.%Y",
)


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Excel serial date; 25569 is 1970-01-01 in Excel's 1900 system.
        if 20000 <= float(value) <= 80000:
            try:
                return date(1899, 12, 30) + timedelta(days=int(float(value)))
            except ValueError:
                return None
        if 19000101 <= int(value) <= 22001231:
            value = str(int(value))
    raw = str(value).strip()
    if not raw:
        return None
    # Tally XML sometimes appends a time component.
    raw = raw.split("T")[0].split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", raw) else raw
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].upper()


def _xml_text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _xml_child(node: ET.Element, *names: str) -> ET.Element | None:
    wanted = {name.upper() for name in names}
    for child in node:
        if _localname(child.tag) in wanted:
            return child
    return None


def _xml_children(node: ET.Element, *names: str) -> list[ET.Element]:
    wanted = {name.upper() for name in names}
    return [child for child in node if _localname(child.tag) in wanted]


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_csv_rows(raw: bytes) -> list[dict[str, Any]]:
    text = _decode_text(raw)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows: list[dict[str, Any]] = []
    for row in reader:
        if row is None:
            continue
        cleaned = {
            (str(key).strip() if key is not None else ""): value
            for key, value in row.items()
            if key is not None and not str(key).strip().lower().startswith("unnamed")
        }
        if cleaned and any(value not in (None, "") for value in cleaned.values()):
            rows.append(cleaned)
    return rows


def parse_xlsx_rows(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise HTTPException(
            status_code=503, detail="Excel parsing is unavailable on this server."
        ) from exc
    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="This Excel file could not be read.") from exc
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    workbook.close()
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]] if rows else []
    if not headers or not any(headers):
        raise HTTPException(status_code=422, detail="The first Excel row must contain column names.")
    parsed: list[dict[str, Any]] = []
    for row in rows[1:]:
        if row is None or all(cell in (None, "") for cell in row):
            continue
        parsed.append(
            {headers[index]: row[index] for index in range(min(len(headers), len(row)))}
        )
    return parsed, sheet.title


def parse_xls_rows(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise HTTPException(
            status_code=503,
            detail="Legacy .xls reading is unavailable. Save the file as .xlsx or .csv.",
        ) from exc
    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="This legacy Excel file could not be read.") from exc
    sheet = book.sheet_by_index(0)
    if sheet.nrows == 0:
        return [], sheet.name
    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    parsed: list[dict[str, Any]] = []
    for row_index in range(1, sheet.nrows):
        values: list[Any] = []
        for col in range(sheet.ncols):
            cell = sheet.cell(row_index, col)
            if cell.ctype == xlrd.XL_CELL_DATE:
                values.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
            else:
                values.append(cell.value)
        if all(value in (None, "") for value in values):
            continue
        parsed.append({headers[i]: values[i] for i in range(min(len(headers), len(values)))})
    return parsed, sheet.name


def _tally_sign_amount(amount: Decimal | None, deemed_positive: bool | None) -> tuple[Decimal, Decimal]:
    """Convert Tally's signed ledger amount to (debit, credit)."""
    if amount is None:
        return ZERO, ZERO
    if deemed_positive is True:
        return abs(amount), ZERO
    if deemed_positive is False:
        return ZERO, abs(amount)
    # Tally's convention: negative amounts are debits, positive are credits.
    if amount < 0:
        return abs(amount), ZERO
    return ZERO, amount


def parse_xml_rows(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise HTTPException(
            status_code=422, detail=f"This XML file is not well-formed: {exc}"
        ) from exc
    rows: list[dict[str, Any]] = []
    vouchers = 0
    masters = 0

    def walk(node: ET.Element) -> None:
        nonlocal vouchers, masters
        name = _localname(node.tag)
        if name == "VOUCHER":
            vouchers += 1
            raw_date = _xml_text(_xml_child(node, "DATE", "EFFECTIVEDATE"))
            normalised_date = _date(raw_date)
            header = {
                "record_type": "voucher",
                "voucher_type": _xml_text(_xml_child(node, "VOUCHERTYPENAME", "VCHTYPE"))
                or node.attrib.get("VCHTYPE", ""),
                "voucher_number": _xml_text(_xml_child(node, "VOUCHERNUMBER")),
                "voucher_date": normalised_date.isoformat() if normalised_date else raw_date,
                "party_name": _xml_text(_xml_child(node, "PARTYLEDGERNAME")),
                "party_gstin": _xml_text(_xml_child(node, "PARTYGSTIN")),
                "narration": _xml_text(_xml_child(node, "NARRATION")),
                "reference": _xml_text(_xml_child(node, "REFERENCE", "REFERENCEDATE")),
                "original_type": node.attrib.get("VCHTYPE", ""),
                "financial_year": _xml_text(_xml_child(node, "FINANCIALYEAR")),
            }
            entries = _xml_children(
                node, "ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST", "LEDGERENTRIES"
            )
            inventory = _xml_children(
                node, "ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST"
            )
            stock_info: dict[str, Any] = {}
            if inventory:
                first = inventory[0]
                stock_info = {
                    "stock_item": _xml_text(_xml_child(first, "STOCKITEMNAME")),
                    "quantity": _xml_text(_xml_child(first, "ACTUALQTY", "BILLEDQTY")),
                    "rate": _xml_text(_xml_child(first, "RATE")),
                    "unit": _xml_text(_xml_child(first, "UNIT")),
                    "hsn_sac": _xml_text(_xml_child(first, "HSNCODE")),
                }
            if not entries:
                rows.append({**header, **stock_info, "_xml_note": "Voucher has no ledger entries."})
            for entry in entries:
                ledger = _xml_text(_xml_child(entry, "LEDGERNAME"))
                amount = _decimal(_xml_text(_xml_child(entry, "AMOUNT")))
                deemed_raw = _xml_text(_xml_child(entry, "ISDEEMEDPOSITIVE"))
                deemed = None
                if deemed_raw:
                    deemed = deemed_raw.lower() in ("yes", "true", "1")
                debit, credit = _tally_sign_amount(amount, deemed)
                rows.append(
                    {
                        **header,
                        "ledger_name": ledger,
                        "ledger_group": _xml_text(_xml_child(entry, "LEDGERGROUP")),
                        "debit": debit,
                        "credit": credit,
                        **stock_info,
                    }
                )
            return
        if name == "LEDGER":
            masters += 1
            opening = _decimal(_xml_text(_xml_child(node, "OPENINGBALANCE")))
            debit, credit = _tally_sign_amount(opening, False if (opening or 0) > 0 else True)
            rows.append(
                {
                    "record_type": "ledger",
                    "ledger_name": node.attrib.get("NAME", ""),
                    "ledger_group": _xml_text(_xml_child(node, "PARENT")),
                    "party_gstin": _xml_text(_xml_child(node, "PARTYGSTIN", "GSTIN")),
                    "opening_balance": opening,
                    "opening_debit": debit,
                    "opening_credit": credit,
                    "financial_year": _xml_text(_xml_child(node, "FINANCIALYEAR")),
                }
            )
            return
        if name in ("GROUP", "STOCKGROUP"):
            masters += 1
            rows.append(
                {
                    "record_type": "group",
                    "ledger_group": node.attrib.get("NAME", ""),
                    "parent_group": _xml_text(_xml_child(node, "PARENT")),
                }
            )
            return
        if name in ("STOCKITEM", "ITEM"):
            masters += 1
            gst_node = _xml_child(node, "GSTAPPLICABLE", "GSTRATE")
            rows.append(
                {
                    "record_type": "stock",
                    "stock_item": node.attrib.get("NAME", ""),
                    "sku": node.attrib.get("NAME", ""),
                    "unit": _xml_text(_xml_child(node, "BASEUNITS", "UNIT")),
                    "hsn_sac": _xml_text(_xml_child(node, "HSNCODE", "HSN")),
                    "gst_rate": (gst_node.attrib.get("RATE") if gst_node is not None else "")
                    or _xml_text(gst_node),
                    "quantity": _xml_text(_xml_child(node, "OPENINGBALANCE")),
                    "rate": _xml_text(_xml_child(node, "OPENINGRATE")),
                }
            )
            return
        for child in node:
            walk(child)

    walk(root)
    if not rows:
        raise HTTPException(
            status_code=422,
            detail=(
                "No Tally vouchers or masters were found in this XML. Export from TallyPrime "
                "Gateway of Tally → Export → Data (XML) and try again."
            ),
        )
    return rows, f"{vouchers} voucher(s), {masters} master(s)"


def _flatten_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "#text" in value and len(value) <= 2:
            return value["#text"]
        return {str(key).upper(): _flatten_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_flatten_json_value(item) for item in value]
    return value


def _json_rows_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    item = _flatten_json_value(item)
    for wrapper in ("VOUCHER", "LEDGER", "GROUP", "STOCKITEM", "ITEM"):
        if wrapper in item and isinstance(item[wrapper], dict):
            inner = item[wrapper]
            if wrapper == "VOUCHER":
                return _json_voucher_rows(inner)
            entry = inner
            entry.setdefault("RECORD_TYPE", wrapper.lower() if wrapper != "STOCKITEM" else "stock")
            return [entry]
    voucher_keys = {
        "VOUCHERTYPENAME",
        "VOUCHERTYPE",
        "VCHTYPE",
        "VOUCHERNUMBER",
        "VOUCHER_TYPE",
        "VOUCHER_NUMBER",
        "DATE",
        "VOUCHER_DATE",
        "PARTYLEDGERNAME",
        "PARTY_NAME",
    }
    line_keys = {"LEDGERNAME", "LEDGER_NAME", "DEBIT", "CREDIT"}
    if voucher_keys & set(item):
        # A flat JSON row that already carries its own ledger line is imported as-is.
        if line_keys & set(item):
            return [item]
        return _json_voucher_rows(item)
    return [item]


def _json_voucher_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    header = {
        "record_type": "voucher",
        "voucher_type": item.get("VOUCHERTYPENAME") or item.get("VCHTYPE") or item.get("VOUCHER_TYPE") or "",
        "voucher_number": item.get("VOUCHERNUMBER") or item.get("VOUCHER_NUMBER") or "",
        "voucher_date": item.get("DATE") or item.get("VOUCHER_DATE") or "",
        "party_name": item.get("PARTYLEDGERNAME") or item.get("PARTY_NAME") or "",
        "party_gstin": item.get("PARTYGSTIN") or item.get("PARTY_GSTIN") or "",
        "narration": item.get("NARRATION") or item.get("NARRATION_TEXT") or "",
        "reference": item.get("REFERENCE") or item.get("VOUCHER_REFERENCE") or "",
        "financial_year": item.get("FINANCIALYEAR") or "",
    }
    entries: Any = (
        item.get("ALLLEDGERENTRIES.LIST")
        or item.get("LEDGERENTRIES.LIST")
        or item.get("LEDGER_ENTRIES")
        or item.get("entries")
        or item.get("lines")
    )
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        entries = []
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry = _flatten_json_value(entry)
        amount = _decimal(entry.get("AMOUNT") or entry.get("amount"))
        deemed_raw = entry.get("ISDEEMEDPOSITIVE") or entry.get("is_deemed_positive")
        deemed = None
        if deemed_raw not in (None, ""):
            deemed = str(deemed_raw).strip().lower() in ("yes", "true", "1")
        debit, credit = _tally_sign_amount(amount, deemed)
        rows.append(
            {
                **header,
                "ledger_name": entry.get("LEDGERNAME") or entry.get("ledger_name") or entry.get("ledger") or "",
                "ledger_group": entry.get("LEDGERGROUP") or entry.get("ledger_group") or "",
                "debit": debit,
                "credit": credit,
            }
        )
    if not rows:
        rows.append(header)
    return rows


def parse_json_rows(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    try:
        payload = json.loads(_decode_text(raw))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"This JSON file could not be parsed: {exc}") from exc

    items: list[Any]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("rows", "records", "data", "vouchers", "items"):
            value = payload.get(key) or payload.get(key.upper())
            if isinstance(value, list):
                items = value
                break
        else:
            envelope = payload.get("ENVELOPE") or payload.get("envelope")
            if isinstance(envelope, dict):
                body = envelope.get("BODY") or envelope.get("body") or envelope
                data = body.get("DATA") or body.get("data") or body if isinstance(body, dict) else envelope
                messages = data.get("TALLYMESSAGE") or data.get("tallymessage") if isinstance(data, dict) else None
                if isinstance(messages, dict):
                    messages = [messages]
                items = messages if isinstance(messages, list) else [payload]
            else:
                items = [payload]
    else:
        raise HTTPException(status_code=422, detail="This JSON file has an unsupported structure.")

    rows: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            rows.extend(_json_rows_from_item(item))
    if not rows:
        raise HTTPException(status_code=422, detail="This JSON file contains no importable records.")
    return rows, f"{len(items)} JSON record(s)"


def parse_migration_file(raw: bytes, file_format: str) -> tuple[list[dict[str, Any]], str]:
    fmt = (file_format or "").strip().lower()
    if fmt == "csv":
        return parse_csv_rows(raw), "CSV"
    if fmt == "xlsx":
        rows, sheet = parse_xlsx_rows(raw)
        return rows, f"Sheet “{sheet}”"
    if fmt == "xls":
        rows, sheet = parse_xls_rows(raw)
        return rows, f"Legacy sheet “{sheet}”"
    if fmt == "xml":
        return parse_xml_rows(raw)
    if fmt == "json":
        return parse_json_rows(raw)
    raise HTTPException(status_code=422, detail="Upload an XLSX, XLS, CSV, XML or JSON Tally export.")


def headers_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in rows[:20]:
        for key in row:
            if key not in seen and not str(key).startswith("_"):
                seen.append(key)
    return seen


_ALIAS_LOOKUP: dict[str, str] = {}
for _field in TALLY_MAPPING_FIELDS:
    for _alias in _field["aliases"]:  # type: ignore[union-attr]
        _ALIAS_LOOKUP.setdefault(str(_alias).strip().lower(), str(_field["key"]))


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for header in headers:
        target = _ALIAS_LOOKUP.get(_header_key(header))
        if not target or target in mapping or header in used:
            continue
        mapping[target] = header
        used.add(header)
    return mapping


def preview_migration_file(raw: bytes, file_format: str) -> dict[str, Any]:
    rows, note = parse_migration_file(raw, file_format)
    headers = headers_from_rows(rows)
    sample = [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in rows[:10]
    ]
    return {
        "file_format": file_format,
        "row_count": len(rows),
        "headers": headers,
        "sample": sample,
        "suggested_mapping": suggest_mapping(headers),
        "note": note,
        "supported_versions": {
            version: list(formats) for version, formats in TALLY_VERSION_FORMATS.items()
        },
        "mapping_fields": [dict(item) for item in TALLY_MAPPING_FIELDS],
        "limits": {
            "max_records": MAX_IMPORT_RECORDS,
            "max_upload_mb": settings.ACCOUNTING_MAX_UPLOAD_MB,
        },
    }


# ---------------------------------------------------------------- mapping & normalisation


def _header_key(value: Any) -> str:
    return re.sub(r"[\s_]+", " ", str(value).strip().lower()).strip()


def _cell(row: dict[str, Any], field_name: str, mapping: dict[str, str]) -> Any:
    column = mapping.get(field_name)
    lowered = {_header_key(key): key for key in row}
    if column:
        if column in row:
            return row[column]
        key = lowered.get(_header_key(column))
        if key is not None:
            return row[key]
    if field_name in row:
        return row[field_name]
    key = lowered.get(_header_key(field_name))
    return row[key] if key is not None else None


def _norm_voucher_type(value: Any) -> str:
    raw = _text(value).lower()
    raw = re.sub(r"\bvoucher\b|\bvch\b", "", raw).strip(" -_")
    aliases = {
        "sales": "sale",
        "sale": "sale",
        "tax invoice": "sale",
        "invoice": "sale",
        "purchase": "purchase",
        "purchase order": "purchase",
        "bill": "purchase",
        "payment": "payment",
        "payments": "payment",
        "receipt": "receipt",
        "receipts": "receipt",
        "journal": "journal",
        "jv": "journal",
        "credit note": "credit_note",
        "creditnote": "credit_note",
        "cr note": "credit_note",
        "debit note": "debit_note",
        "debitnote": "debit_note",
        "dr note": "debit_note",
        "contra": "contra",
        "expense": "expense",
        "expenses": "expense",
    }
    return aliases.get(raw, raw)


_PARTY_GROUPS = {
    "sundry debtors": "customer",
    "sundry creditors": "supplier",
    "debtors": "customer",
    "creditors": "supplier",
    "customer": "customer",
    "supplier": "supplier",
}

_GST_RATES = {
    Decimal("0"),
    Decimal("0.25"),
    Decimal("3"),
    Decimal("5"),
    Decimal("12"),
    Decimal("18"),
    Decimal("28"),
}

_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


@dataclass
class MigrationConfig:
    import_type: str
    financial_year: str
    period_from: date | None
    period_to: date | None
    opening_date: date | None
    file_format: str
    filename: str
    tally_version: str


@dataclass
class Record:
    row_number: int
    record_type: str
    source: dict[str, Any]
    data: dict[str, Any] = field(default_factory=dict)
    lines: list[dict[str, Any]] = field(default_factory=list)
    problems: list[dict[str, str]] = field(default_factory=list)
    row_numbers: list[int] = field(default_factory=list)

    def problem(self, code: str, message: str, severity: str = "error") -> None:
        self.problems.append({"code": code, "severity": severity, "message": message})


def _party_type(name: str | None, group: str | None) -> str:
    if group and group.strip().lower() in _PARTY_GROUPS:
        return _PARTY_GROUPS[group.strip().lower()]
    lowered = (name or "").lower()
    if any(word in lowered for word in ("customer", "debtor")):
        return "customer"
    if any(word in lowered for word in ("supplier", "creditor", "vendor")):
        return "supplier"
    return "other"


def _base_record(row_number: int, record_type: str, source: dict[str, Any]) -> Record:
    return Record(
        row_number=row_number,
        record_type=record_type,
        source={str(key): _json_safe(value) for key, value in source.items()},
        row_numbers=[row_number],
    )


def _record_type_for(row: dict[str, Any], import_type: str, mapping: dict[str, str]) -> str:
    if import_type in TALLY_RECORD_TYPES and import_type != "complete":
        return TALLY_RECORD_TYPES[import_type]
    explicit = _text(_cell(row, "record_type", mapping)).lower().replace(" ", "_")
    aliases = {
        "ledger": "ledger",
        "ledgermaster": "ledger",
        "ledger_master": "ledger",
        "ledger_masters": "ledger",
        "group": "group",
        "groups": "group",
        "stock": "stock",
        "stock_item": "stock",
        "stockitem": "stock",
        "stock_master": "stock",
        "stock_masters": "stock",
        "balance": "balance",
        "opening": "opening",
        "opening_balance": "opening",
        "opening_balances": "opening",
        "voucher": "voucher",
    }
    return aliases.get(explicit, TALLY_RECORD_TYPES.get(import_type, "voucher"))


def _opening_sides(row: dict[str, Any], mapping: dict[str, str]) -> tuple[Decimal, Decimal]:
    direct_debit = _decimal(_cell(row, "opening_debit", mapping))
    direct_credit = _decimal(_cell(row, "opening_credit", mapping))
    if direct_debit is not None or direct_credit is not None:
        return abs(direct_debit or ZERO), abs(direct_credit or ZERO)
    debit = _decimal(_cell(row, "debit", mapping))
    credit = _decimal(_cell(row, "credit", mapping))
    if debit is not None or credit is not None:
        return abs(debit or ZERO), abs(credit or ZERO)
    opening = _decimal(_cell(row, "opening_balance", mapping))
    if opening is None:
        return ZERO, ZERO
    dr_cr = _text(_cell(row, "dr_cr", mapping)).lower()
    if dr_cr.startswith("d"):
        return abs(opening), ZERO
    if dr_cr.startswith("c"):
        return ZERO, abs(opening)
    # Tally's signed convention: a negative opening is a debit, positive a credit.
    return (abs(opening), ZERO) if opening < 0 else (ZERO, opening)


def normalise_records(
    rows: list[dict[str, Any]],
    mapping: dict[str, str],
    config: MigrationConfig,
) -> list[Record]:
    """Turn raw rows into voucher/master/opening records without touching the DB."""
    if len(rows) > MAX_IMPORT_RECORDS:
        raise HTTPException(
            status_code=422,
            detail=f"This file has {len(rows):,} rows; the limit is {MAX_IMPORT_RECORDS:,}. Split it by financial year.",
        )
    records: list[Record] = []
    voucher_groups: dict[tuple[str, str, str], Record] = {}
    for index, row in enumerate(rows, start=2):
        record_type = _record_type_for(row, config.import_type, mapping)
        if record_type == "voucher":
            record = _voucher_from_row(index, row, mapping, config)
            if record is None:
                continue
            key = (
                str(record.data.get("voucher_type") or ""),
                str(record.data.get("number") or f"__row{index}").strip().lower(),
                str(record.data.get("voucher_date") or ""),
            )
            existing = voucher_groups.get(key)
            if existing is None:
                voucher_groups[key] = record
                records.append(record)
            else:
                existing.lines.extend(record.lines)
                existing.row_numbers.extend(record.row_numbers)
                existing.problems.extend(record.problems)
                for field_name in ("taxable_value", "cgst", "sgst", "igst"):
                    existing.data[field_name] = q2(
                        Decimal(str(existing.data.get(field_name) or "0"))
                        + Decimal(str(record.data.get(field_name) or "0"))
                    )
            continue
        if record_type == "ledger":
            record = _base_record(index, "ledger", row)
            opening_debit, opening_credit = _opening_sides(row, mapping)
            record.data = {
                "name": _text(_cell(row, "ledger_name", mapping) or _cell(row, "party_name", mapping)),
                "group_name": _text(_cell(row, "ledger_group", mapping)) or "Suspense Account",
                "parent_group": _text(_cell(row, "parent_group", mapping)) or None,
                "gstin": _text(_cell(row, "party_gstin", mapping)).upper() or None,
                "opening_debit": str(opening_debit),
                "opening_credit": str(opening_credit),
                "opening_date": config.opening_date.isoformat() if config.opening_date else None,
                "financial_year": config.financial_year,
            }
            if not record.data["name"]:
                record.problem("missing_ledger_name", "Ledger master has no ledger name.")
            record.data["party_type"] = _party_type(
                str(record.data["name"]), str(record.data["group_name"])
            )
            records.append(record)
            continue
        if record_type == "balance":
            record = _base_record(index, "balance", row)
            opening_debit, opening_credit = _opening_sides(row, mapping)
            record.data = {
                "name": _text(_cell(row, "ledger_name", mapping) or _cell(row, "party_name", mapping)),
                "group_name": _text(_cell(row, "ledger_group", mapping)) or "Suspense Account",
                "gstin": _text(_cell(row, "party_gstin", mapping)).upper() or None,
                "opening_debit": str(opening_debit),
                "opening_credit": str(opening_credit),
                "opening_date": (
                    config.opening_date.isoformat()
                    if config.opening_date
                    else financial_year_bounds(config.financial_year)[0].isoformat()
                ),
                "financial_year": config.financial_year,
            }
            if not record.data["name"]:
                record.problem("missing_ledger_name", "Historical balance has no ledger name.")
            if opening_debit > 0 and opening_credit > 0:
                record.problem("both_debit_credit", "A balance line cannot have both debit and credit.")
            record.data["party_type"] = _party_type(
                str(record.data["name"]), str(record.data["group_name"])
            )
            records.append(record)
            continue
        if record_type == "group":
            record = _base_record(index, "group", row)
            record.data = {
                "name": _text(_cell(row, "ledger_group", mapping) or _cell(row, "party_name", mapping)),
                "parent_group": _text(_cell(row, "parent_group", mapping)) or None,
            }
            if not record.data["name"]:
                record.problem("missing_group_name", "Group row has no group name.")
            records.append(record)
            continue
        if record_type == "stock":
            record = _base_record(index, "stock", row)
            name = _text(_cell(row, "stock_item", mapping) or _cell(row, "party_name", mapping))
            sku = _text(_cell(row, "sku", mapping)) or re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").upper()
            rate = _decimal(_cell(row, "gst_rate", mapping)) or ZERO
            record.data = {
                "name": name,
                "sku": sku[:60],
                "unit": _text(_cell(row, "unit", mapping)) or "Nos",
                "hsn_sac": _text(_cell(row, "hsn_sac", mapping)) or None,
                "gst_rate": str(rate),
                "quantity": str(_decimal(_cell(row, "quantity", mapping)) or ZERO),
                "rate": str(_decimal(_cell(row, "rate", mapping)) or ZERO),
            }
            if not name:
                record.problem("missing_stock_name", "Stock item row has no item name.")
            if rate < 0 or rate > 28:
                record.problem("invalid_gst", "GST rate must be between 0 and 28.", "warning")
            records.append(record)
            continue
        if record_type == "opening":
            record = _base_record(index, "opening", row)
            debit = _decimal(_cell(row, "debit", mapping))
            credit = _decimal(_cell(row, "credit", mapping))
            opening = _decimal(_cell(row, "opening_balance", mapping))
            dr_cr = _text(_cell(row, "dr_cr", mapping)).lower()
            if opening is not None and debit is None and credit is None:
                if dr_cr.startswith("c") or opening > 0:
                    credit, debit = abs(opening), ZERO
                elif dr_cr.startswith("d") or opening < 0:
                    debit, credit = abs(opening), ZERO
            record.data = {
                "ledger_name": _text(_cell(row, "ledger_name", mapping) or _cell(row, "party_name", mapping)),
                "group_name": _text(_cell(row, "ledger_group", mapping)) or None,
                "party_type": _party_type(
                    _text(_cell(row, "ledger_name", mapping) or _cell(row, "party_name", mapping)),
                    _text(_cell(row, "ledger_group", mapping)),
                ),
                "debit": str(abs(debit or ZERO)),
                "credit": str(abs(credit or ZERO)),
                "stock_item": _text(_cell(row, "stock_item", mapping)) or None,
                "quantity": _text(_decimal(_cell(row, "quantity", mapping))) or None,
                "rate": _text(_decimal(_cell(row, "rate", mapping))) or None,
                "narration": _text(_cell(row, "narration", mapping)) or None,
            }
            if not record.data["ledger_name"]:
                record.problem("missing_ledger_name", "Opening balance line has no ledger name.")
            if (debit or ZERO) > 0 and (credit or ZERO) > 0:
                record.problem("both_debit_credit", "An opening line cannot have both debit and credit.")
            if not (debit or ZERO) and not (credit or ZERO):
                record.problem("missing_amount", "An opening line needs a debit or credit amount.")
            records.append(record)
            continue
    for record in voucher_groups.values():
        _infer_gst_from_lines(record)
    return records


def _infer_gst_from_lines(record: Record) -> None:
    """Tally exports often book CGST/SGST as separate ledger lines.

    When no GST amount columns were mapped, read the tax lines so the GST
    summary reflects what the source file actually contains.
    """
    fields = ("cgst", "sgst", "igst")
    if any(Decimal(str(record.data.get(field) or "0")) != 0 for field in fields):
        return
    totals = {field: ZERO for field in fields}
    for line in record.lines:
        name = str(line.get("ledger_name") or "").lower()
        field = next((field for field in fields if field in name), None)
        if field is None:
            continue
        totals[field] += abs(Decimal(str(line.get("debit") or "0"))) + abs(
            Decimal(str(line.get("credit") or "0"))
        )
    if not any(totals.values()):
        return
    for field, value in totals.items():
        record.data[field] = str(q2(value))
    if Decimal(str(record.data.get("taxable_value") or "0")) == 0:
        voucher_type = str(record.data.get("voucher_type") or "")
        side = "credit" if voucher_type in ("sale", "credit_note", "receipt") else "debit"
        base = sum(
            (
                abs(Decimal(str(line.get(side) or "0")))
                for line in record.lines
                if not line.get("is_party")
                and not any(field in str(line.get("ledger_name") or "").lower() for field in fields)
            ),
            ZERO,
        )
        if base:
            record.data["taxable_value"] = str(q2(base))
    record.data["inter_state"] = Decimal(str(record.data.get("igst") or "0")) > 0


def _voucher_from_row(
    index: int,
    row: dict[str, Any],
    mapping: dict[str, str],
    config: MigrationConfig,
) -> Record | None:
    if all(value in (None, "") for value in row.values()):
        return None
    record = _base_record(index, "voucher", row)
    voucher_type = _norm_voucher_type(_cell(row, "voucher_type", mapping))
    if not voucher_type:
        voucher_type = {
            "sales": "sale",
            "purchase": "purchase",
            "payment": "payment",
            "receipt": "receipt",
            "journal": "journal",
        }.get(config.import_type, "")
    number = _text(_cell(row, "voucher_number", mapping))
    raw_date = _cell(row, "voucher_date", mapping)
    voucher_date = _date(raw_date)
    party = _text(_cell(row, "party_name", mapping))
    ledger = _text(_cell(row, "ledger_name", mapping))
    group = _text(_cell(row, "ledger_group", mapping))
    narration = _text(_cell(row, "narration", mapping))
    reference = _text(_cell(row, "reference", mapping))
    gstin = _text(_cell(row, "party_gstin", mapping)).upper()
    taxable = _decimal(_cell(row, "taxable_value", mapping))
    rate = _decimal(_cell(row, "gst_rate", mapping)) or ZERO
    cgst = _decimal(_cell(row, "cgst", mapping)) or ZERO
    sgst = _decimal(_cell(row, "sgst", mapping)) or ZERO
    igst = _decimal(_cell(row, "igst", mapping)) or ZERO
    debit = _decimal(_cell(row, "debit", mapping))
    credit = _decimal(_cell(row, "credit", mapping))
    amount = _decimal(_cell(row, "amount", mapping))
    dr_cr = _text(_cell(row, "dr_cr", mapping)).lower()
    stock_item = _text(_cell(row, "stock_item", mapping)) or None
    quantity = _decimal(_cell(row, "quantity", mapping))
    unit = _text(_cell(row, "unit", mapping)) or None
    hsn = _text(_cell(row, "hsn_sac", mapping)) or None

    if amount is not None and debit is None and credit is None:
        if dr_cr.startswith("c") or (not dr_cr and amount < 0):
            credit, debit = abs(amount), ZERO
        else:
            debit, credit = abs(amount), ZERO
    if debit is not None or credit is not None:
        line_ledger = ledger or party or (f"Unmapped ledger (row {index})" if not party else party)
        line_debit = abs(debit or ZERO)
        line_credit = abs(credit or ZERO)
        record.lines.append(
            {
                "ledger_name": line_ledger,
                "ledger_group": group or None,
                "debit": str(line_debit),
                "credit": str(line_credit),
                "gst_rate": str(rate),
                "stock_item": stock_item,
                "quantity": str(quantity) if quantity is not None else None,
                "unit": unit,
                "hsn_sac": hsn,
                "narration": narration or None,
                "is_party": bool(party and line_ledger.strip().lower() == party.strip().lower()),
            }
        )
    elif taxable is not None and party:
        # Voucher-level export: synthesise a balanced two-line entry.
        total = q2(taxable + cgst + sgst + igst)
        if total <= 0 and rate > 0:
            total = q2(taxable + q2(taxable * rate / Decimal("100")))
        contra = ledger or {
            "sale": "Sales Accounts",
            "purchase": "Purchase Accounts",
            "payment": "Bank Account",
            "receipt": "Bank Account",
            "expense": "Expenses",
        }.get(voucher_type, "Suspense Account")
        if voucher_type in ("purchase", "expense"):
            first = {"ledger_name": contra, "debit": str(total), "credit": "0"}
            second = {"ledger_name": party, "debit": "0", "credit": str(total)}
        elif voucher_type == "receipt":
            first = {"ledger_name": contra, "debit": str(total), "credit": "0"}
            second = {"ledger_name": party, "debit": "0", "credit": str(total)}
        elif voucher_type == "journal":
            first = {"ledger_name": contra, "debit": str(total), "credit": "0"}
            second = {"ledger_name": party, "debit": "0", "credit": str(total)}
            record.problem(
                "incomplete_journal",
                "A journal row was balanced against the party ledger; confirm the counter-ledger.",
                "warning",
            )
        else:
            first = {"ledger_name": party, "debit": str(total), "credit": "0"}
            second = {"ledger_name": contra, "debit": "0", "credit": str(total)}
        for position, line in enumerate((first, second), start=1):
            record.lines.append(
                {
                    **line,
                    "ledger_group": group or None,
                    "gst_rate": str(rate),
                    "stock_item": stock_item if position == 2 else None,
                    "quantity": str(quantity) if quantity is not None and position == 2 else None,
                    "unit": unit,
                    "hsn_sac": hsn,
                    "narration": narration or None,
                    "is_party": line["ledger_name"] == party,
                }
            )

    if taxable is None and record.lines:
        total = sum(
            (Decimal(line["debit"]) for line in record.lines if not line["is_party"]), ZERO
        )
        taxable = q2(total - cgst - sgst - igst) if total else ZERO

    record.data = {
        "voucher_type": voucher_type,
        "number": number,
        "voucher_date": voucher_date.isoformat() if voucher_date else _text(raw_date)[:20],
        "party_name": party or None,
        "party_gstin": gstin or None,
        "narration": narration or None,
        "reference": reference or None,
        "original_type": _text(_cell(row, "voucher_type", mapping)) or None,
        "taxable_value": str(taxable or ZERO),
        "gst_rate": str(rate),
        "cgst": str(cgst),
        "sgst": str(sgst),
        "igst": str(igst),
        "inter_state": bool(igst > 0),
        "financial_year": config.financial_year,
    }
    return record


# ---------------------------------------------------------------- validation


def _existing_ledger_names(db: Session, client_id: int) -> set[str]:
    names = {
        str(row[0]).strip().lower()
        for row in db.query(AccountingHistoricalLedger.name)
        .filter(AccountingHistoricalLedger.client_id == client_id)
        .all()
        if row[0]
    }
    names.update(
        str(row[0]).strip().lower()
        for row in db.query(AccountingVoucher.ledger_name)
        .filter(AccountingVoucher.client_id == client_id)
        .all()
        if row[0]
    )
    return names


def _existing_fingerprints(db: Session, client_id: int) -> set[str]:
    return {
        str(row[0])
        for row in db.query(AccountingHistoricalVoucher.fingerprint)
        .filter(AccountingHistoricalVoucher.client_id == client_id)
        .all()
    }


def _live_voucher_keys(db: Session, client_id: int) -> set[tuple[str, str, str]]:
    return {
        (str(vtype).lower(), str(number).strip().lower(), voucher_date.isoformat())
        for vtype, number, voucher_date in db.query(
            AccountingVoucher.voucher_type,
            AccountingVoucher.number,
            AccountingVoucher.voucher_date,
        )
        .filter(AccountingVoucher.client_id == client_id)
        .all()
    }


def voucher_fingerprint(
    client_id: int, voucher_type: str, number: str, voucher_date: date, total: Decimal
) -> str:
    raw = "|".join(
        [
            str(client_id),
            voucher_type.strip().lower(),
            number.strip().lower(),
            voucher_date.isoformat(),
            f"{q2(total):.2f}",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_records(
    db: Session,
    *,
    client_id: int,
    records: list[Record],
    config: MigrationConfig,
) -> dict[str, Any]:
    known_ledgers = _existing_ledger_names(db, client_id)
    master_names = {
        str(record.data.get("name") or "").strip().lower()
        for record in records
        if record.record_type in ("ledger", "balance")
    }
    known_ledgers.update(name for name in master_names if name)
    existing_fingerprints = _existing_fingerprints(db, client_id)
    live_keys = _live_voucher_keys(db, client_id)
    fy_start, fy_end = financial_year_bounds(config.financial_year)
    seen_fingerprints: set[str] = set()
    seen_ledgers: set[str] = set()
    batch_errors: list[dict[str, Any]] = []
    missing_ledgers: set[str] = set()
    unmatched_parties: set[str] = set()
    total_debit = ZERO
    total_credit = ZERO
    opening_debit = ZERO
    opening_credit = ZERO
    stock_value = ZERO

    statuses: dict[int, str] = {}
    for record in records:
        if record.record_type == "voucher":
            voucher_date = _date(record.data.get("voucher_date"))
            number = str(record.data.get("number") or "").strip()
            voucher_type = str(record.data.get("voucher_type") or "")
            if not voucher_type or voucher_type not in (
                "sale",
                "purchase",
                "payment",
                "receipt",
                "journal",
                "credit_note",
                "debit_note",
                "contra",
                "expense",
            ):
                record.problem(
                    "invalid_voucher_type",
                    "Voucher type is missing or not one of sale, purchase, payment, receipt, journal, credit note, debit note, contra or expense.",
                )
            if not number:
                record.problem("missing_voucher_number", "Voucher number is required.")
            if voucher_date is None:
                record.problem("invalid_date", "Voucher date is missing or not recognised.")
            elif not (fy_start <= voucher_date <= fy_end):
                record.problem(
                    "financial_year",
                    f"Voucher date {voucher_date.isoformat()} is outside financial year {config.financial_year} ({fy_start.isoformat()} to {fy_end.isoformat()}).",
                )
            elif config.period_from and config.period_to:
                if not (config.period_from <= voucher_date <= config.period_to):
                    record.problem(
                        "outside_period",
                        f"Voucher date {voucher_date.isoformat()} is outside the selected period.",
                    )
            if not record.lines:
                record.problem("incomplete_record", "Voucher has no ledger lines.")
            debit = sum((Decimal(line["debit"]) for line in record.lines), ZERO)
            credit = sum((Decimal(line["credit"]) for line in record.lines), ZERO)
            record.data["total_debit"] = str(q2(debit))
            record.data["total_credit"] = str(q2(credit))
            if record.lines and abs(debit - credit) > CENT:
                record.problem(
                    "unbalanced",
                    f"Debit {q2(debit)} does not equal credit {q2(credit)} (difference {q2(debit - credit)}).",
                )
            if debit < 0 or credit < 0:
                record.problem("negative_amount", "Amounts cannot be negative after mapping.")
            gst_rate = Decimal(str(record.data.get("gst_rate") or "0"))
            if gst_rate < 0 or gst_rate > 28:
                record.problem("invalid_gst", "GST rate must be between 0 and 28.")
            elif gst_rate and gst_rate not in _GST_RATES:
                record.problem(
                    "non_standard_gst",
                    f"GST rate {gst_rate}% is not a standard Indian GST rate; confirm it before posting.",
                    "warning",
                )
            gstin = str(record.data.get("party_gstin") or "")
            if gstin and not _GSTIN_RE.match(gstin):
                record.problem(
                    "invalid_gstin",
                    f"Party GSTIN {gstin!r} is not a valid Indian GSTIN.",
                    "warning",
                )
            party = str(record.data.get("party_name") or "").strip()
            if party and party.lower() not in known_ledgers:
                unmatched_parties.add(party)
                record.problem(
                    "unmatched_party",
                    f"Party “{party}” is not present in the ledger masters; a ledger will be created in suspense.",
                    "warning",
                )
            for line in record.lines:
                name = str(line.get("ledger_name") or "").strip()
                if not name:
                    record.problem("missing_ledger", "A voucher line has no ledger name.")
                    continue
                if name.lower() not in known_ledgers:
                    missing_ledgers.add(name)
                    record.problem(
                        "missing_ledger",
                        f"Ledger “{name}” is not in the ledger masters; it will be created under Suspense Account.",
                        "warning",
                    )
            if not record.problems or all(item["severity"] == "warning" for item in record.problems):
                if voucher_date and number:
                    fingerprint = voucher_fingerprint(
                        client_id, voucher_type, number, voucher_date, q2(debit)
                    )
                    record.data["fingerprint"] = fingerprint
                    if fingerprint in seen_fingerprints or fingerprint in existing_fingerprints:
                        record.problem(
                            "duplicate_voucher",
                            "A voucher with the same type, number, date and total already exists; it will be skipped.",
                            "duplicate",
                        )
                    elif (voucher_type, number.lower(), voucher_date.isoformat()) in live_keys:
                        record.problem(
                            "duplicate_live_voucher",
                            "A matching voucher exists in the live FINOVEXA ledger. Imported history stays separate, but check for double counting.",
                            "warning",
                        )
                    seen_fingerprints.add(fingerprint)
            total_debit += debit
            total_credit += credit
        elif record.record_type in ("ledger", "balance"):
            name = str(record.data.get("name") or "").strip()
            if name and name.lower() in seen_ledgers:
                record.problem(
                    "duplicate_ledger",
                    f"Ledger “{name}” appears more than once in this file; the later row will be skipped.",
                    "duplicate",
                )
            seen_ledgers.add(name.lower())
            opening_debit += Decimal(str(record.data.get("opening_debit") or "0"))
            opening_credit += Decimal(str(record.data.get("opening_credit") or "0"))
        elif record.record_type == "opening":
            debit = Decimal(str(record.data.get("debit") or "0"))
            credit = Decimal(str(record.data.get("credit") or "0"))
            opening_debit += debit
            opening_credit += credit
            if record.data.get("stock_item"):
                stock_value += debit
            if (record.data.get("rate") and record.data.get("quantity") and not debit):
                record.problem(
                    "stock_value_missing",
                    "Stock opening has quantity and rate but no value; enter the opening value in the debit column.",
                    "warning",
                )
        elif record.record_type == "stock":
            rate = Decimal(str(record.data.get("gst_rate") or "0"))
            if rate and rate not in _GST_RATES:
                record.problem(
                    "non_standard_gst",
                    f"GST rate {rate}% is not a standard Indian GST rate.",
                    "warning",
                )

        severities = {item["severity"] for item in record.problems}
        if "error" in severities:
            statuses[record.row_number] = "error"
        elif "duplicate" in severities:
            statuses[record.row_number] = "duplicate"
        elif "warning" in severities:
            statuses[record.row_number] = "warning"
        else:
            statuses[record.row_number] = "valid"

    if config.import_type == "opening_balances":
        if abs(opening_debit - opening_credit) > CENT:
            batch_errors.append(
                {
                    "code": "opening_unbalanced",
                    "message": f"Opening debit {q2(opening_debit)} does not equal credit {q2(opening_credit)}.",
                }
            )
        if opening_debit == 0 and opening_credit == 0:
            batch_errors.append(
                {"code": "opening_empty", "message": "No opening balance lines were detected."}
            )
        if stock_value < 0:
            batch_errors.append(
                {"code": "stock_invalid", "message": "Opening stock value cannot be negative."}
            )

    if config.import_type in ("complete",) or TALLY_RECORD_TYPES.get(config.import_type) == "voucher":
        if records and not any(record.record_type == "voucher" for record in records):
            batch_errors.append(
                {"code": "no_vouchers", "message": "No voucher rows were detected in this file."}
            )

    counts = {
        "detected": len(records),
        "valid": sum(1 for value in statuses.values() if value == "valid"),
        "warnings": sum(1 for value in statuses.values() if value == "warning"),
        "errors": sum(1 for value in statuses.values() if value == "error"),
        "duplicates": sum(1 for value in statuses.values() if value == "duplicate"),
    }
    if batch_errors:
        counts["errors"] = max(counts["errors"], 1)

    issues: list[dict[str, Any]] = []
    for record in records:
        for problem in record.problems:
            if len(issues) >= 500:
                break
            issues.append(
                {
                    "row": record.row_number,
                    "record_type": record.record_type,
                    "code": problem["code"],
                    "severity": problem["severity"],
                    "message": problem["message"],
                    "voucher_type": record.data.get("voucher_type"),
                    "voucher_number": record.data.get("number"),
                    "voucher_date": record.data.get("voucher_date"),
                }
            )
    for problem in batch_errors:
        issues.insert(
            0,
            {
                "row": 0,
                "record_type": "batch",
                "code": problem["code"],
                "severity": "error",
                "message": problem["message"],
            },
        )

    def check(code: str, label: str, failed: int, detail: str) -> dict[str, Any]:
        return {
            "code": code,
            "label": label,
            "status": "passed" if failed == 0 else "failed",
            "detail": detail,
            "count": failed,
        }

    checks = [
        check(
            "duplicates",
            "Duplicate vouchers",
            counts["duplicates"],
            "No duplicate vouchers detected."
            if counts["duplicates"] == 0
            else f"{counts['duplicates']} duplicate record(s) will be skipped, not overwritten.",
        ),
        check(
            "missing_ledgers",
            "Missing ledgers",
            len(missing_ledgers),
            "Every voucher line matches a known ledger."
            if not missing_ledgers
            else f"{len(missing_ledgers)} ledger(s) are missing and will be created under Suspense Account: "
            + ", ".join(sorted(missing_ledgers)[:6])
            + ("…" if len(missing_ledgers) > 6 else ""),
        ),
        check(
            "invalid_dates",
            "Invalid dates",
            sum(1 for record in records if any(p["code"] == "invalid_date" for p in record.problems)),
            "Every record has a recognised date.",
        ),
        check(
            "missing_numbers",
            "Missing voucher numbers",
            sum(1 for record in records if any(p["code"] == "missing_voucher_number" for p in record.problems)),
            "Every voucher has a number.",
        ),
        check(
            "debit_credit",
            "Debit and credit totals",
            sum(1 for record in records if any(p["code"] == "unbalanced" for p in record.problems)),
            f"Mapped debit {q2(total_debit)} and credit {q2(total_credit)} across voucher lines.",
        ),
        check(
            "financial_year",
            "Financial year consistency",
            sum(1 for record in records if any(p["code"] == "financial_year" for p in record.problems)),
            f"All dates fall in {config.financial_year}." if config.financial_year else "",
        ),
        check(
            "unmatched_parties",
            "Unmatched parties",
            len(unmatched_parties),
            "Every party matches a ledger master." if not unmatched_parties else f"{len(unmatched_parties)} party name(s) are not in the ledger masters.",
        ),
        check(
            "gst",
            "GST values",
            sum(
                1
                for record in records
                if any(p["code"] in ("invalid_gst", "non_standard_gst", "invalid_gstin") for p in record.problems)
            ),
            "GST rates and GSTINs look valid.",
        ),
        check(
            "completeness",
            "Incomplete records",
            sum(
                1
                for record in records
                if any(p["code"] in ("incomplete_record", "missing_ledger", "missing_ledger_name") for p in record.problems)
            ),
            "Every record has the fields needed to post it.",
        ),
    ]
    if config.import_type == "opening_balances":
        checks.append(
            check(
                "opening_balance",
                "Opening debit equals credit",
                len(batch_errors),
                f"Opening debit {q2(opening_debit)} and credit {q2(opening_credit)}."
                if not batch_errors
                else "Opening balances must balance before they can be submitted.",
            )
        )

    ok = counts["errors"] == 0 and not batch_errors
    return {
        "ok": ok,
        "counts": counts,
        "checks": checks,
        "issues": issues,
        "batch_errors": batch_errors,
        "missing_ledgers": sorted(missing_ledgers)[:200],
        "unmatched_parties": sorted(unmatched_parties)[:200],
        "totals": {
            "debit": str(q2(total_debit)),
            "credit": str(q2(total_credit)),
            "difference": str(q2(total_debit - total_credit)),
            "opening_debit": str(q2(opening_debit)),
            "opening_credit": str(q2(opening_credit)),
            "stock_value": str(q2(stock_value)),
        },
        "statuses": statuses,
        "note": (
            "Validation never changes a financial value. Duplicates are skipped, missing ledgers are "
            "created under Suspense Account for review, and errors must be corrected in the source file. "
            "Imported history is stored separately from the live FINOVEXA ledger."
        ),
    }


# ---------------------------------------------------------------- persistence


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def store_batch_rows(
    db: Session,
    batch: AccountingTallyMigration,
    records: list[Record],
    validation: dict[str, Any],
) -> None:
    statuses = validation["statuses"]
    for record in records:
        problems = [
            {"code": item["code"], "severity": item["severity"], "message": item["message"]}
            for item in record.problems
        ]
        db.add(
            AccountingTallyMigrationRow(
                migration_id=batch.id,
                row_number=record.row_number,
                record_type=record.record_type,
                status=statuses.get(record.row_number, "valid"),
                fingerprint=record.data.get("fingerprint"),
                problems=problems,
                raw=_json_safe(record.source),
                mapped=_json_safe({**record.data, "lines": record.lines}),
            )
        )


def apply_validation(batch: AccountingTallyMigration, validation: dict[str, Any]) -> None:
    counts = validation["counts"]
    batch.row_count = counts["detected"]
    batch.valid_count = counts["valid"]
    batch.warning_count = counts["warnings"]
    batch.error_count = counts["errors"]
    batch.duplicate_count = counts["duplicates"]
    batch.validation = _json_safe(validation)


def create_batch(
    db: Session,
    *,
    user: User,
    client_id: int,
    payload: Any,
    raw: bytes,
    stored_name: str,
    file_sha256: str,
    file_size: int,
) -> AccountingTallyMigration:
    config = MigrationConfig(
        import_type=payload.import_type,
        financial_year=payload.financial_year,
        period_from=payload.period_from,
        period_to=payload.period_to,
        opening_date=payload.opening_date,
        file_format=payload.file_format,
        filename=payload.filename,
        tally_version=payload.tally_version,
    )
    _guard_double_counting(db, client_id, config)
    rows, parse_note = parse_migration_file(raw, payload.file_format)
    if not rows:
        raise HTTPException(status_code=422, detail="The uploaded file has no data rows.")
    mapping = dict(payload.mapping or {})
    if not mapping:
        mapping = suggest_mapping(headers_from_rows(rows))
    if not mapping:
        raise HTTPException(
            status_code=422,
            detail="No columns could be matched. Map the file columns to FINOVEXA fields and try again.",
        )
    records = normalise_records(rows, mapping, config)
    if not records:
        raise HTTPException(status_code=422, detail="No importable records were detected in this file.")
    validation = validate_records(db, client_id=client_id, records=records, config=config)
    batch = AccountingTallyMigration(
        client_id=client_id,
        direction="opening_balance" if config.import_type == "opening_balances" else "import",
        tally_version=config.tally_version,
        financial_year=config.financial_year,
        period_from=config.period_from,
        period_to=config.period_to,
        opening_date=config.opening_date,
        import_type=config.import_type,
        file_format=config.file_format,
        filename=payload.filename[:255],
        stored_name=stored_name,
        file_sha256=file_sha256,
        file_size=file_size,
        mapping=mapping,
        mapping_template_id=payload.mapping_template_id,
        details={
            "parse_note": parse_note,
            "note": payload.note,
            "file_rows": len(rows),
            "import_type_label": TALLY_MIGRATION_IMPORT_LABELS.get(config.import_type),
            "live_ledger_untouched": True,
        },
        status="validated",
        prepared_by_user_id=user.id,
        retained_until=date.today() + timedelta(days=settings.ACCOUNTING_TALLY_RETENTION_DAYS),
    )
    apply_validation(batch, validation)
    db.add(batch)
    db.flush()
    store_batch_rows(db, batch, records, validation)
    return batch


def revalidate_batch(
    db: Session,
    *,
    batch: AccountingTallyMigration,
    mapping: dict[str, str] | None,
    stored_path: str,
) -> dict[str, Any]:
    if batch.status in ("imported", "partially_imported", "approved", "rolled_back"):
        raise HTTPException(
            status_code=409,
            detail="This batch has already been posted or rolled back and cannot be revalidated.",
        )
    with open(stored_path, "rb") as handle:
        raw = handle.read()
    rows, parse_note = parse_migration_file(raw, batch.file_format)
    if mapping:
        batch.mapping = mapping
    if not batch.mapping:
        raise HTTPException(status_code=422, detail="Map the file columns before validating.")
    config = _config_from_batch(batch)
    _guard_double_counting(db, batch.client_id, config)
    records = normalise_records(rows, batch.mapping, config)
    validation = validate_records(db, client_id=batch.client_id, records=records, config=config)
    for row in list(batch.rows):
        db.delete(row)
    db.flush()
    store_batch_rows(db, batch, records, validation)
    apply_validation(batch, validation)
    batch.status = "validated"
    batch.submitted_at = None
    batch.details = {**(batch.details or {}), "parse_note": parse_note}
    return validation


def _config_from_batch(batch: AccountingTallyMigration) -> MigrationConfig:
    return MigrationConfig(
        import_type=batch.import_type,
        financial_year=batch.financial_year,
        period_from=batch.period_from,
        period_to=batch.period_to,
        opening_date=batch.opening_date,
        file_format=batch.file_format,
        filename=batch.filename,
        tally_version=batch.tally_version,
    )


def _guard_double_counting(
    db: Session, client_id: int, config: MigrationConfig
) -> None:
    """Prevent importing both full history and its opening balances for one year."""
    vouchers_exist = (
        db.query(AccountingHistoricalVoucher.id)
        .filter(
            AccountingHistoricalVoucher.client_id == client_id,
            AccountingHistoricalVoucher.financial_year == config.financial_year,
            AccountingHistoricalVoucher.status == "posted",
        )
        .first()
        is not None
    )
    approved_opening = (
        db.query(AccountingOpeningBalance.id)
        .filter(
            AccountingOpeningBalance.client_id == client_id,
            AccountingOpeningBalance.financial_year == config.financial_year,
            AccountingOpeningBalance.status == "approved",
        )
        .first()
        is not None
    )
    if config.import_type == "opening_balances" and vouchers_exist:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Historical vouchers for {config.financial_year} are already imported. "
                "Their opening balances are part of that history; importing both would double count."
            ),
        )
    if config.import_type == "opening_balances" and approved_opening:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Approved opening balances for {config.financial_year} already exist. "
                "They were not overwritten; reverse the existing batch first if it was wrong."
            ),
        )
    if config.import_type in ("complete", "sales", "purchase", "payment", "receipt", "journal", "debit_credit_notes", "historical_balances") and approved_opening:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Approved opening balances for {config.financial_year} already exist. "
                "Importing full historical transactions as well would double count the year."
            ),
        )


def submit_batch(db: Session, batch: AccountingTallyMigration, user: User) -> None:
    if batch.status != "validated":
        raise HTTPException(status_code=409, detail=f"This batch is {batch.status}; only a validated batch can be submitted.")
    validation = batch.validation or {}
    if batch.error_count > 0 or not validation.get("ok", False):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Correct the validation errors before submitting this batch. No value was changed.",
                "validation": validation,
            },
        )
    importable = batch.valid_count + batch.warning_count
    if importable == 0:
        raise HTTPException(
            status_code=409,
            detail="There are no new records to import: every record is a duplicate or an error.",
        )
    batch.status = "pending_approval"
    batch.submitted_at = utcnow()
    batch.details = {**(batch.details or {}), "submitted_by": user.full_name}


def decide_batch(
    db: Session, batch: AccountingTallyMigration, user: User, decision: str, note: str | None
) -> dict[str, Any]:
    if batch.status != "pending_approval":
        raise HTTPException(
            status_code=409, detail=f"This batch is {batch.status}; only a pending batch can be reviewed."
        )
    if decision == "reject":
        batch.status = "rejected"
        batch.approval_note = note
        batch.approved_by_user_id = user.id
        batch.approved_at = utcnow()
        batch.details = {**(batch.details or {}), "rejected_by": user.full_name}
        return {"imported": 0, "status": batch.status}
    if batch.prepared_by_user_id == user.id:
        batch.details = {**(batch.details or {}), "self_approved": True}
    batch.approval_note = note
    result = post_batch(db, batch, user)
    batch.status = "imported" if result["failed"] == 0 else "partially_imported"
    if result["imported"] == 0:
        batch.status = "failed"
        batch.details = {
            **(batch.details or {}),
            "failure": "No record could be posted. The batch was not applied.",
        }
    batch.approved_by_user_id = user.id
    batch.approved_at = utcnow()
    batch.imported_count = result["imported"]
    return result


def post_batch(db: Session, batch: AccountingTallyMigration, approver: User) -> dict[str, Any]:
    rows = list(batch.rows)
    posts = [row for row in rows if row.status in ("valid", "warning")]
    imported = 0
    skipped = 0
    failed = 0
    created_ledgers: set[str] = set()
    known_ledgers = _existing_ledger_names(db, batch.client_id)
    if batch.import_type == "opening_balances":
        imported = _post_opening_balance(db, batch, posts, approver)
        skipped = len(rows) - imported
        return {
            "imported": imported,
            "skipped": skipped,
            "failed": 0,
            "ledgers_created": 0,
            "note": "Opening balances were recorded as approved. They are not posted as vouchers.",
        }

    for row in posts:
        mapped = row.mapped or {}
        kind = row.record_type
        if kind == "voucher":
            data = mapped
            fingerprint = str(data.get("fingerprint") or "")
            if fingerprint and db.query(AccountingHistoricalVoucher.id).filter(
                AccountingHistoricalVoucher.client_id == batch.client_id,
                AccountingHistoricalVoucher.fingerprint == fingerprint,
            ).first():
                row.status = "duplicate"
                skipped += 1
                continue
            voucher_date = _date(data.get("voucher_date"))
            if voucher_date is None:
                failed += 1
                continue
            lines = data.get("lines") or []
            if not lines:
                failed += 1
                continue
            for line in lines:
                name = str(line.get("ledger_name") or "").strip()
                if not name:
                    continue
                if name.lower() not in known_ledgers:
                    ledger = AccountingHistoricalLedger(
                        client_id=batch.client_id,
                        migration_id=batch.id,
                        name=name[:180],
                        group_name=(line.get("ledger_group") or "Suspense Account")[:120],
                        party_type=_party_type(name, line.get("ledger_group")),
                        financial_year=batch.financial_year,
                        source_row=row.row_number,
                    )
                    db.add(ledger)
                    known_ledgers.add(name.lower())
                    created_ledgers.add(name)
            party = data.get("party_name")
            if party and str(party).lower() not in known_ledgers:
                db.add(
                    AccountingHistoricalLedger(
                        client_id=batch.client_id,
                        migration_id=batch.id,
                        name=str(party)[:180],
                        group_name="Sundry Debtors"
                        if data.get("voucher_type") in ("sale", "credit_note")
                        else "Sundry Creditors",
                        party_type="customer"
                        if data.get("voucher_type") in ("sale", "credit_note")
                        else "supplier",
                        financial_year=batch.financial_year,
                        source_row=row.row_number,
                    )
                )
                known_ledgers.add(str(party).lower())
                created_ledgers.add(str(party))
            voucher = AccountingHistoricalVoucher(
                client_id=batch.client_id,
                migration_id=batch.id,
                voucher_type=str(data.get("voucher_type") or "journal")[:24],
                number=str(data.get("number") or "")[:80],
                voucher_date=voucher_date,
                financial_year=batch.financial_year,
                party_name=(str(party)[:180] if party else None),
                party_gstin=(str(data.get("party_gstin"))[:15] if data.get("party_gstin") else None),
                narration=str(data.get("narration") or "")[:4000] or None,
                reference=str(data.get("reference") or "")[:120] or None,
                original_type=str(data.get("original_type") or "")[:60] or None,
                taxable_value=Decimal(str(data.get("taxable_value") or "0")),
                gst_rate=Decimal(str(data.get("gst_rate") or "0")),
                cgst_amount=Decimal(str(data.get("cgst") or "0")),
                sgst_amount=Decimal(str(data.get("sgst") or "0")),
                igst_amount=Decimal(str(data.get("igst") or "0")),
                total_debit=Decimal(str(data.get("total_debit") or "0")),
                total_credit=Decimal(str(data.get("total_credit") or "0")),
                inter_state=bool(data.get("inter_state")),
                source_format=batch.file_format,
                source_filename=batch.filename,
                source_row=row.row_number,
                fingerprint=fingerprint,
            )
            db.add(voucher)
            db.flush()
            for position, line in enumerate(lines, start=1):
                db.add(
                    AccountingHistoricalVoucherLine(
                        voucher_id=voucher.id,
                        line_number=position,
                        ledger_name=str(line.get("ledger_name") or "")[:180],
                        ledger_group=(str(line.get("ledger_group"))[:120] if line.get("ledger_group") else None),
                        debit=Decimal(str(line.get("debit") or "0")),
                        credit=Decimal(str(line.get("credit") or "0")),
                        gst_rate=Decimal(str(line.get("gst_rate") or "0")),
                        stock_item=(str(line.get("stock_item"))[:180] if line.get("stock_item") else None),
                        quantity=(Decimal(str(line["quantity"])) if line.get("quantity") else None),
                        unit=(str(line.get("unit"))[:16] if line.get("unit") else None),
                        hsn_sac=(str(line.get("hsn_sac"))[:12] if line.get("hsn_sac") else None),
                        narration=(str(line.get("narration"))[:4000] if line.get("narration") else None),
                        is_party=bool(line.get("is_party")),
                    )
                )
            row.historical_voucher_id = voucher.id
            imported += 1
        elif kind in ("ledger", "balance"):
            name = str(mapped.get("name") or "").strip()
            if not name:
                failed += 1
                continue
            existing = (
                db.query(AccountingHistoricalLedger)
                .filter(
                    AccountingHistoricalLedger.client_id == batch.client_id,
                    AccountingHistoricalLedger.name == name,
                    AccountingHistoricalLedger.financial_year == batch.financial_year,
                )
                .first()
            )
            if existing:
                if (
                    Decimal(str(existing.opening_debit or 0)) == 0
                    and Decimal(str(existing.opening_credit or 0)) == 0
                    and (Decimal(str(mapped.get("opening_debit") or 0)) or Decimal(str(mapped.get("opening_credit") or 0)))
                ):
                    existing.opening_debit = Decimal(str(mapped.get("opening_debit") or "0"))
                    existing.opening_credit = Decimal(str(mapped.get("opening_credit") or "0"))
                    imported += 1
                else:
                    row.status = "duplicate"
                    skipped += 1
                continue
            db.add(
                AccountingHistoricalLedger(
                    client_id=batch.client_id,
                    migration_id=batch.id,
                    name=name[:180],
                    group_name=(str(mapped.get("group_name") or "Suspense Account"))[:120],
                    parent_group=(str(mapped.get("parent_group"))[:120] if mapped.get("parent_group") else None),
                    gstin=(str(mapped.get("gstin"))[:15] if mapped.get("gstin") else None),
                    party_type=str(mapped.get("party_type") or "other")[:16],
                    opening_debit=Decimal(str(mapped.get("opening_debit") or "0")),
                    opening_credit=Decimal(str(mapped.get("opening_credit") or "0")),
                    opening_date=_date(mapped.get("opening_date")),
                    financial_year=batch.financial_year,
                    source_row=row.row_number,
                )
            )
            imported += 1
        elif kind == "stock":
            name = str(mapped.get("name") or "").strip()
            sku = str(mapped.get("sku") or "").strip()
            if not name or not sku:
                failed += 1
                continue
            exists = (
                db.query(AccountingStockItem)
                .filter(AccountingStockItem.client_id == batch.client_id, AccountingStockItem.sku == sku)
                .first()
            )
            if exists:
                row.status = "duplicate"
                skipped += 1
                continue
            db.add(
                AccountingStockItem(
                    client_id=batch.client_id,
                    name=name[:180],
                    sku=sku[:60],
                    unit=(str(mapped.get("unit") or "Nos"))[:16],
                    hsn_sac=(str(mapped.get("hsn_sac"))[:12] if mapped.get("hsn_sac") else None),
                    gst_rate=Decimal(str(mapped.get("gst_rate") or "0")),
                    opening_qty=Decimal("0"),
                    opening_rate=Decimal("0"),
                    created_by_user_id=approver.id,
                )
            )
            imported += 1
        elif kind == "group":
            imported += 1
        else:
            failed += 1
    return {
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "ledgers_created": len(created_ledgers),
        "note": (
            "Approved rows were written to historical tables only. The live FINOVEXA ledger was not changed; "
            "this remains a file-based migration with no Tally connection."
        ),
    }


def _post_opening_balance(
    db: Session,
    batch: AccountingTallyMigration,
    rows: list[AccountingTallyMigrationRow],
    approver: User,
) -> int:
    existing = (
        db.query(AccountingOpeningBalance)
        .filter(
            AccountingOpeningBalance.client_id == batch.client_id,
            AccountingOpeningBalance.financial_year == batch.financial_year,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Opening balances already exist for this financial year; they were not overwritten.",
        )
    lines = [row.mapped or {} for row in rows]
    if not lines:
        raise HTTPException(status_code=409, detail="No opening balance lines are available to approve.")
    debit = sum((Decimal(str(line.get("debit") or "0")) for line in lines), ZERO)
    credit = sum((Decimal(str(line.get("credit") or "0")) for line in lines), ZERO)
    if abs(debit - credit) > CENT:
        raise HTTPException(
            status_code=409,
            detail=f"Opening balances do not balance: debit {q2(debit)} vs credit {q2(credit)}.",
        )
    stock_value = sum(
        (Decimal(str(line.get("debit") or "0")) for line in lines if line.get("stock_item")), ZERO
    )
    opening = AccountingOpeningBalance(
        client_id=batch.client_id,
        financial_year=batch.financial_year,
        opening_date=batch.opening_date or financial_year_bounds(batch.financial_year)[0],
        migration_id=batch.id,
        status="approved",
        prepared_by_user_id=batch.prepared_by_user_id,
        approved_by_user_id=approver.id,
        approved_at=utcnow(),
        approval_note=batch.approval_note,
        total_debit=q2(debit),
        total_credit=q2(credit),
        stock_value=q2(stock_value),
        details={
            "source": "tally_file_import",
            "inventory_total": str(q2(stock_value)),
            "note": "Opening balances recorded from an approved Tally migration batch.",
        },
    )
    db.add(opening)
    db.flush()
    known = _existing_ledger_names(db, batch.client_id)
    for position, line in enumerate(lines, start=1):
        name = str(line.get("ledger_name") or "").strip()
        if not name:
            continue
        db.add(
            AccountingOpeningBalanceLine(
                opening_id=opening.id,
                line_number=position,
                ledger_name=name[:180],
                group_name=(str(line.get("group_name"))[:120] if line.get("group_name") else None),
                party_type=str(line.get("party_type") or "other")[:16],
                debit=Decimal(str(line.get("debit") or "0")),
                credit=Decimal(str(line.get("credit") or "0")),
                stock_item=(str(line.get("stock_item"))[:180] if line.get("stock_item") else None),
                quantity=(Decimal(str(line["quantity"])) if line.get("quantity") else None),
                rate=(Decimal(str(line["rate"])) if line.get("rate") else None),
                value=Decimal(str(line.get("debit") or "0")),
                narration=(str(line.get("narration"))[:500] if line.get("narration") else None),
            )
        )
        if name.lower() not in known:
            db.add(
                AccountingHistoricalLedger(
                    client_id=batch.client_id,
                    migration_id=batch.id,
                    name=name[:180],
                    group_name=(str(line.get("group_name") or "Suspense Account"))[:120],
                    party_type=str(line.get("party_type") or "other")[:16],
                    financial_year=batch.financial_year,
                    opening_debit=Decimal(str(line.get("debit") or "0")),
                    opening_credit=Decimal(str(line.get("credit") or "0")),
                    opening_date=opening.opening_date,
                )
            )
            known.add(name.lower())
    return len(lines)


def rollback_batch(db: Session, batch: AccountingTallyMigration, user: User) -> dict[str, Any]:
    if batch.status not in ("imported", "partially_imported", "approved", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"This batch is {batch.status}; only a posted batch can be rolled back.",
        )
    vouchers = list(
        db.query(AccountingHistoricalVoucher)
        .filter(AccountingHistoricalVoucher.migration_id == batch.id)
        .all()
    )
    for voucher in vouchers:
        db.delete(voucher)
    if batch.direction == "opening_balance":
        openings = (
            db.query(AccountingOpeningBalance)
            .filter(AccountingOpeningBalance.migration_id == batch.id)
            .all()
        )
        for opening in openings:
            db.delete(opening)
    ledgers = (
        db.query(AccountingHistoricalLedger)
        .filter(AccountingHistoricalLedger.migration_id == batch.id)
        .all()
    )
    removed_ledgers = 0
    for ledger in ledgers:
        still_used = (
            db.query(AccountingHistoricalVoucherLine.id)
            .join(
                AccountingHistoricalVoucher,
                AccountingHistoricalVoucher.id == AccountingHistoricalVoucherLine.voucher_id,
            )
            .filter(
                AccountingHistoricalVoucher.client_id == batch.client_id,
                AccountingHistoricalVoucher.id != None,  # noqa: E711
                AccountingHistoricalVoucherLine.ledger_name == ledger.name,
            )
            .first()
        )
        if not still_used:
            db.delete(ledger)
            removed_ledgers += 1
    for row in list(batch.rows):
        row.historical_voucher_id = None
    batch.status = "rolled_back"
    batch.rolled_back_at = utcnow()
    batch.rolled_back_by_user_id = user.id
    batch.imported_count = 0
    batch.details = {
        **(batch.details or {}),
        "rollback": {
            "vouchers_removed": len(vouchers),
            "ledgers_removed": removed_ledgers,
            "by": user.full_name,
        },
    }
    return {
        "vouchers_removed": len(vouchers),
        "ledgers_removed": removed_ledgers,
        "status": batch.status,
    }


# ---------------------------------------------------------------- serialisation


def template_to_dict(template: AccountingTallyMappingTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "client_id": template.client_id,
        "file_format": template.file_format,
        "import_type": template.import_type,
        "mapping": template.mapping or {},
        "is_shared": template.is_shared,
        "created_at": template.created_at.isoformat() if template.created_at else None,
    }


def opening_to_dict(opening: AccountingOpeningBalance) -> dict[str, Any]:
    return {
        "id": opening.id,
        "client_id": opening.client_id,
        "financial_year": opening.financial_year,
        "opening_date": opening.opening_date.isoformat() if opening.opening_date else None,
        "status": opening.status,
        "total_debit": float(opening.total_debit or 0),
        "total_credit": float(opening.total_credit or 0),
        "stock_value": float(opening.stock_value or 0),
        "approved_at": opening.approved_at.isoformat() if opening.approved_at else None,
        "approved_by_user_id": opening.approved_by_user_id,
        "details": opening.details or {},
        "lines": [
            {
                "id": line.id,
                "ledger_name": line.ledger_name,
                "group_name": line.group_name,
                "party_type": line.party_type,
                "debit": float(line.debit or 0),
                "credit": float(line.credit or 0),
                "stock_item": line.stock_item,
                "quantity": float(line.quantity) if line.quantity is not None else None,
                "rate": float(line.rate) if line.rate is not None else None,
                "value": float(line.value or 0),
            }
            for line in opening.lines
        ],
        "created_at": opening.created_at.isoformat() if opening.created_at else None,
    }


def migration_to_dict(
    db: Session,
    batch: AccountingTallyMigration,
    *,
    include_validation: bool = False,
    include_rows: bool = False,
    row_limit: int = 100,
) -> dict[str, Any]:
    client = db.get(AccountingClient, batch.client_id)
    prepared = db.get(User, batch.prepared_by_user_id) if batch.prepared_by_user_id else None
    approved = db.get(User, batch.approved_by_user_id) if batch.approved_by_user_id else None
    rolled = db.get(User, batch.rolled_back_by_user_id) if batch.rolled_back_by_user_id else None
    result = {
        "id": batch.id,
        "client_id": batch.client_id,
        "client_name": client.business_name if client else None,
        "direction": batch.direction,
        "tally_version": batch.tally_version,
        "financial_year": batch.financial_year,
        "period_from": batch.period_from.isoformat() if batch.period_from else None,
        "period_to": batch.period_to.isoformat() if batch.period_to else None,
        "opening_date": batch.opening_date.isoformat() if batch.opening_date else None,
        "import_type": batch.import_type,
        "import_type_label": TALLY_MIGRATION_IMPORT_LABELS.get(batch.import_type),
        "file_format": batch.file_format,
        "filename": batch.filename,
        "file_size": batch.file_size,
        "file_sha256": batch.file_sha256,
        "row_count": batch.row_count,
        "valid_count": batch.valid_count,
        "warning_count": batch.warning_count,
        "error_count": batch.error_count,
        "duplicate_count": batch.duplicate_count,
        "imported_count": batch.imported_count,
        "status": batch.status,
        "prepared_by": prepared.full_name if prepared else None,
        "approved_by": approved.full_name if approved else None,
        "approved_at": batch.approved_at.isoformat() if batch.approved_at else None,
        "approval_note": batch.approval_note,
        "rolled_back_at": batch.rolled_back_at.isoformat() if batch.rolled_back_at else None,
        "rolled_back_by": rolled.full_name if rolled else None,
        "mapping": batch.mapping or {},
        "mapping_template_id": batch.mapping_template_id,
        "details": batch.details or {},
        "retained_until": batch.retained_until.isoformat() if batch.retained_until else None,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }
    if include_validation:
        result["validation"] = batch.validation or {}
    if include_rows:
        result["rows"] = [
            {
                "id": row.id,
                "row_number": row.row_number,
                "record_type": row.record_type,
                "status": row.status,
                "problems": row.problems or [],
                "mapped": row.mapped or {},
            }
            for row in batch.rows[:row_limit]
        ]
    return result


def error_report_csv(batch: AccountingTallyMigration) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Import batch",
            "Client ID",
            "Financial year",
            "Source file",
            "Row",
            "Record type",
            "Status",
            "Severity",
            "Code",
            "Message",
            "Voucher type",
            "Voucher number",
            "Voucher date",
        ]
    )
    for row in batch.rows:
        if row.status in ("valid",):
            continue
        mapped = row.mapped or {}
        if row.problems:
            for problem in row.problems:
                writer.writerow(
                    [
                        batch.id,
                        batch.client_id,
                        batch.financial_year,
                        batch.filename,
                        row.row_number,
                        row.record_type,
                        row.status,
                        problem.get("severity"),
                        problem.get("code"),
                        problem.get("message"),
                        mapped.get("voucher_type") or "",
                        mapped.get("number") or mapped.get("name") or "",
                        mapped.get("voucher_date") or "",
                    ]
                )
        else:
            writer.writerow(
                [
                    batch.id,
                    batch.client_id,
                    batch.financial_year,
                    batch.filename,
                    row.row_number,
                    row.record_type,
                    row.status,
                    "",
                    "",
                    "Skipped duplicate",
                    mapped.get("voucher_type") or "",
                    mapped.get("number") or mapped.get("name") or "",
                    mapped.get("voucher_date") or "",
                ]
            )
    return buffer.getvalue()
