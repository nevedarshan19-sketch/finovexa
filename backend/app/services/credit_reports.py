"""Phase 1 credit reports with Excel and PDF output.

Every report is built from the same derived datasets used by the dashboard, so
the exported figures always match what the portal shows. Nothing is stored and
no historical row is modified.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import User
from . import credit
from .finance import q2

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"

_MONEY = "money"
_TEXT = "text"
_DATE = "date"
_INT = "int"
_PERCENT = "percent"


def _col(key: str, label: str, kind: str = _TEXT, width: int = 18) -> dict[str, Any]:
    return {"key": key, "label": label, "kind": kind, "width": width}


REPORTS: dict[str, dict[str, Any]] = {
    "customer_outstanding": {
        "title": "Customer Outstanding",
        "description": "Receivable balance, available credit and risk for every customer.",
        "columns": [
            _col("name", "Customer", width=28),
            _col("gstin", "GSTIN", width=18),
            _col("credit_limit", "Credit limit", _MONEY),
            _col("invoiced", "Invoiced", _MONEY),
            _col("paid", "Received", _MONEY),
            _col("outstanding", "Outstanding", _MONEY),
            _col("overdue", "Overdue", _MONEY),
            _col("available_credit", "Available credit", _MONEY),
            _col("utilization_pct", "Utilisation %", _PERCENT, 14),
            _col("risk_status", "Risk", 12),
        ],
        "totals": ("credit_limit", "invoiced", "paid", "outstanding", "overdue", "available_credit"),
    },
    "supplier_outstanding": {
        "title": "Supplier Outstanding",
        "description": "Payable balance and overdue amount for every supplier.",
        "columns": [
            _col("name", "Supplier", width=28),
            _col("gstin", "GSTIN", width=18),
            _col("payment_terms_days", "Terms (days)", _INT, 14),
            _col("billed", "Billed", _MONEY),
            _col("paid", "Paid", _MONEY),
            _col("payable", "Payable", _MONEY),
            _col("overdue", "Overdue", _MONEY),
            _col("status", "Status", 12),
        ],
        "totals": ("billed", "paid", "payable", "overdue"),
    },
    "receivable_aging": {
        "title": "Receivable Aging",
        "description": "Customer dues by age bucket (0-30, 31-60, 61-90, above 90 days).",
        "columns": [
            _col("name", "Customer", width=28),
            _col("gstin", "GSTIN", width=18),
            _col("0-30", "0-30 days", _MONEY),
            _col("31-60", "31-60 days", _MONEY),
            _col("61-90", "61-90 days", _MONEY),
            _col("90+", "Above 90 days", _MONEY),
            _col("total", "Total", _MONEY),
            _col("overdue", "Overdue", _MONEY),
        ],
        "totals": ("0-30", "31-60", "61-90", "90+", "total", "overdue"),
    },
    "payable_aging": {
        "title": "Payable Aging",
        "description": "Supplier dues by age bucket (0-30, 31-60, 61-90, above 90 days).",
        "columns": [
            _col("name", "Supplier", width=28),
            _col("gstin", "GSTIN", width=18),
            _col("0-30", "0-30 days", _MONEY),
            _col("31-60", "31-60 days", _MONEY),
            _col("61-90", "61-90 days", _MONEY),
            _col("90+", "Above 90 days", _MONEY),
            _col("total", "Total", _MONEY),
            _col("overdue", "Overdue", _MONEY),
        ],
        "totals": ("0-30", "31-60", "61-90", "90+", "total", "overdue"),
    },
    "credit_utilization": {
        "title": "Customer Credit Utilisation",
        "description": "Limit, usage and risk position for every customer.",
        "columns": [
            _col("name", "Customer", width=28),
            _col("gstin", "GSTIN", width=18),
            _col("credit_limit", "Credit limit", _MONEY),
            _col("outstanding", "Outstanding", _MONEY),
            _col("available_credit", "Available credit", _MONEY),
            _col("utilization_pct", "Utilisation %", _PERCENT, 14),
            _col("overdue", "Overdue", _MONEY),
            _col("risk_status", "Risk", 12),
            _col("credit_hold", "On hold", _TEXT, 10),
        ],
        "totals": ("credit_limit", "outstanding", "available_credit", "overdue"),
    },
    "overdue_payments": {
        "title": "Overdue Payments",
        "description": "Every past-due customer invoice and supplier bill.",
        "columns": [
            _col("party_type", "Party type", 14),
            _col("party", "Party", width=28),
            _col("reference", "Reference", width=20),
            _col("due_on", "Due on", _DATE, 14),
            _col("days_overdue", "Days overdue", _INT, 14),
            _col("bucket", "Bucket", 12),
            _col("amount", "Amount", _MONEY),
        ],
        "totals": ("amount",),
    },
    "customer_ledger": {
        "title": "Customer Ledger Statement",
        "description": "Statement of invoices, receipts, adjustments and running balance.",
        "columns": [
            _col("date", "Date", _DATE, 14),
            _col("type", "Type", 14),
            _col("reference", "Reference", width=20),
            _col("description", "Description", width=40),
            _col("debit", "Debit", _MONEY),
            _col("credit", "Credit", _MONEY),
            _col("balance", "Balance", _MONEY),
        ],
        "totals": ("debit", "credit"),
        "requires": "customer_id",
    },
    "supplier_ledger": {
        "title": "Supplier Ledger Statement",
        "description": "Statement of purchase bills, payments and running payable balance.",
        "columns": [
            _col("date", "Date", _DATE, 14),
            _col("type", "Type", 14),
            _col("reference", "Reference", width=20),
            _col("description", "Description", width=40),
            _col("debit", "Debit", _MONEY),
            _col("credit", "Credit", _MONEY),
            _col("balance", "Balance", _MONEY),
        ],
        "totals": ("debit", "credit"),
        "requires": "supplier_id",
    },
}


def report_catalogue() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "title": meta["title"],
            "description": meta["description"],
            "requires": meta.get("requires"),
        }
        for key, meta in REPORTS.items()
    ]


def _boolean_label(value: Any) -> str:
    return "Yes" if value else "No"


def _normalise_rows(meta: dict[str, Any], rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalised = []
    for row in rows:
        item = {}
        for column in meta["columns"]:
            value = row.get(column["key"])
            if column["kind"] == _MONEY:
                item[column["key"]] = credit.money(value)
            elif column["kind"] == _PERCENT:
                item[column["key"]] = q2(value) if value is not None else None
            elif column["kind"] == _INT:
                item[column["key"]] = int(value) if value is not None else None
            elif column["key"] == "credit_hold":
                item[column["key"]] = _boolean_label(value)
            else:
                item[column["key"]] = value
        normalised.append(item)
    return normalised


def report_payload(
    db: Session,
    user: User,
    key: str,
    *,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    meta = REPORTS.get(key)
    if meta is None:
        raise HTTPException(status_code=404, detail="Unknown credit report.")
    today = today or date.today()
    scope: dict[str, Any] = {}
    if meta.get("requires") == "customer_id":
        if customer_id is None:
            raise HTTPException(status_code=400, detail="Select a customer for this report.")
        ledger = credit.customer_ledger(
            db, user.id, customer_id, date_from=date_from, date_to=date_to
        )
        scope = {
            "customer": ledger["customer"],
            "opening_balance": ledger["opening_balance"],
            "closing_balance": ledger["closing_balance"],
        }
        rows = ledger["rows"]
    elif meta.get("requires") == "supplier_id":
        if supplier_id is None:
            raise HTTPException(status_code=400, detail="Select a supplier for this report.")
        ledger = credit.supplier_ledger(
            db, user.id, supplier_id, date_from=date_from, date_to=date_to
        )
        scope = {
            "supplier": ledger["supplier"],
            "opening_balance": ledger["opening_balance"],
            "closing_balance": ledger["closing_balance"],
        }
        rows = ledger["rows"]
    elif key == "customer_outstanding":
        rows = credit.customer_outstanding_rows(db, user.id, today=today)
    elif key == "supplier_outstanding":
        rows = credit.supplier_outstanding_rows(db, user.id, today=today)
    elif key == "receivable_aging":
        rows = credit.customer_aging(db, user.id, today=today)
    elif key == "payable_aging":
        rows = credit.supplier_aging(db, user.id, today=today)
    elif key == "credit_utilization":
        rows = credit.credit_utilization_rows(db, user.id, today=today)
    elif key == "overdue_payments":
        rows = credit.overdue_rows(db, user.id, today=today)
    else:  # pragma: no cover - catalogue and branch list are kept in sync
        raise HTTPException(status_code=404, detail="Unknown credit report.")

    normalised = _normalise_rows(meta, rows)
    totals = {
        column: q2(sum((row[column] or Decimal("0.00") for row in normalised), Decimal("0.00")))
        for column in meta.get("totals", ())
    }
    return {
        "key": key,
        "title": meta["title"],
        "description": meta["description"],
        "columns": meta["columns"],
        "rows": normalised,
        "totals": totals,
        "row_count": len(normalised),
        "date_from": date_from,
        "date_to": date_to,
        "as_of": today,
        "generated_at": credit.utcnow(),
        **scope,
    }


def export_filename(payload: dict[str, Any], extension: str) -> str:
    stem = payload["key"].replace("_", "-")
    today = payload["as_of"].isoformat()
    return f"finovexa-{stem}-{today}.{extension}"


def build_xlsx(payload: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = payload["title"][:31]
    columns = payload["columns"]
    width = len(columns)

    sheet.cell(row=1, column=1, value=payload["title"]).font = Font(size=14, bold=True)
    subtitle = payload["description"]
    if payload.get("customer"):
        subtitle = f"{subtitle} · {payload['customer']['name']}"
    elif payload.get("supplier"):
        subtitle = f"{subtitle} · {payload['supplier']['name']}"
    sheet.cell(row=2, column=1, value=subtitle).font = Font(size=10, italic=True)
    sheet.cell(
        row=3,
        column=1,
        value=(
            f"As of {payload['as_of'].isoformat()} · "
            f"{payload['row_count']} row(s) · amounts in INR"
        ),
    ).font = Font(size=10)

    header_row = 5
    fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(color="FFFFFF", bold=True)
    for index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=header_row, column=index, value=column["label"])
        cell.fill = fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(index)].width = column["width"]

    number_formats = {
        _MONEY: "#,##0.00",
        _PERCENT: '0.00"%"',
        _INT: "#,##0",
        _DATE: "yyyy-mm-dd",
    }
    for offset, row in enumerate(payload["rows"], start=header_row + 1):
        for index, column in enumerate(columns, start=1):
            value = row.get(column["key"])
            cell = sheet.cell(row=offset, column=index, value=value)
            if column["kind"] in number_formats:
                cell.number_format = number_formats[column["kind"]]

    if payload["totals"]:
        total_row = header_row + len(payload["rows"]) + 1
        for index, column in enumerate(columns, start=1):
            if column["key"] in payload["totals"]:
                value = payload["totals"][column["key"]]
            elif index == 1:
                value = "Total"
            else:
                value = None
            cell = sheet.cell(row=total_row, column=index, value=value)
            cell.font = Font(bold=True)
            if column["kind"] in number_formats:
                cell.number_format = number_formats[column["kind"]]

    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    sheet.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(width)}{header_row + max(len(payload['rows']), 1)}"
    )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _reportlab_story(payload: dict[str, Any]) -> list[Any]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CreditTitle", parent=styles["Title"], fontSize=15, spaceAfter=4
    )
    meta_style = ParagraphStyle(
        "CreditMeta", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#4B5563")
    )
    story: list[Any] = [Paragraph(payload["title"], title_style)]
    subtitle = payload["description"]
    if payload.get("customer"):
        subtitle = f"{subtitle} · {payload['customer']['name']}"
    elif payload.get("supplier"):
        subtitle = f"{subtitle} · {payload['supplier']['name']}"
    story.append(Paragraph(subtitle, meta_style))
    story.append(
        Paragraph(
            f"As of {payload['as_of'].isoformat()} · {payload['row_count']} row(s) · amounts in INR",
            meta_style,
        )
    )
    story.append(Spacer(1, 6))

    columns = payload["columns"]
    header = [column["label"] for column in columns]
    body: list[list[str]] = []
    for row in payload["rows"]:
        line = []
        for column in columns:
            value = row.get(column["key"])
            if value is None or value == "":
                line.append("")
            elif column["kind"] == _MONEY:
                line.append(f"{Decimal(value):,.2f}")
            elif column["kind"] == _PERCENT:
                line.append(f"{Decimal(value):.2f}%")
            elif column["kind"] == _INT:
                line.append(str(int(value)))
            elif column["kind"] == _DATE:
                line.append(value.isoformat() if hasattr(value, "isoformat") else str(value))
            else:
                line.append(str(value))
        body.append(line)
    if payload["totals"]:
        total_line = []
        for index, column in enumerate(columns):
            if column["key"] in payload["totals"]:
                total_line.append(f"{Decimal(payload['totals'][column['key']]):,.2f}")
            elif index == 0:
                total_line.append("Total")
            else:
                total_line.append("")
        body.append(total_line)
    if not body:
        body.append(["No records for this period."] + [""] * (len(columns) - 1))

    available = landscape(A4)[0] - 24 * mm
    weights = {"text": 2.2, "money": 1.2, "date": 1.1, "int": 0.9, "percent": 1.0}
    raw = [weights.get(column["kind"], 1.0) for column in columns]
    total_weight = sum(raw)
    col_widths = [available * (weight / total_weight) for weight in raw]

    table = Table([header] + body, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    numeric_columns = [
        index for index, column in enumerate(columns) if column["kind"] in {_MONEY, _PERCENT, _INT}
    ]
    for index in numeric_columns:
        style.append(("ALIGN", (index, 1), (index, -1), "RIGHT"))
    if payload["totals"]:
        style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E5E7EB")))
    table.setStyle(TableStyle(style))
    story.append(table)
    return story


def build_pdf(payload: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=payload["title"],
        author="FINOVEXA",
    )
    document.build(_reportlab_story(payload))
    return buffer.getvalue()
