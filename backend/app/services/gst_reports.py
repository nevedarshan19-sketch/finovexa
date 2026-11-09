"""GST calculation, input-tax-credit tracking and invoice-wise reporting.

The arithmetic itself lives in :mod:`app.services.gst`; this module adds the period filters,
aggregations and the net-payable view used by the Tax Center. Every figure is computed from
stored invoices and ITC rows, never estimated or produced by a model.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from ..models import HSNSACClassification, Invoice, InvoiceItem, ITCEntry, User
from .gst import (
    GSTValidationError,
    LineInput,
    invoice_totals,
    normalize_gstin,
    normalize_state,
    resolve_supply_type,
)
from .finance import q2

ZERO = Decimal("0.00")
ITC_STATUSES = ("eligible", "claimed", "blocked")
REPORT_NOTE = (
    "Reports are built from the invoices and input-credit rows stored in FINOVEXA. Filing needs the "
    "government portal figures for the same period and a professional review; this is not a filing."
)


def _d(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise GSTValidationError("Dates must be written as YYYY-MM-DD.") from exc


def period_bounds(
    date_from: date | str | None = None,
    date_to: date | str | None = None,
    *,
    default_days: int = 90,
    max_days: int | None = 800,
) -> tuple[date, date]:
    today = date.today()
    start = _d(date_from) or (today - timedelta(days=default_days))
    end = _d(date_to) or today
    if end < start:
        raise GSTValidationError("The period end date cannot be before the start date.")
    if max_days is not None and (end - start).days > max_days:
        raise GSTValidationError("Choose a period shorter than about two financial years.")
    return start, end


# ------------------------------------------------------------------ calculator


def calculate_gst(
    lines: list[dict],
    *,
    supplier_state_code: str | None,
    place_of_supply_state_code: str | None,
    other_charges: Decimal | str | int | float = "0",
    round_to_rupee: bool = True,
) -> dict:
    """Calculate a full GST quote without saving anything."""
    supplier_name, supplier_code = normalize_state(None, supplier_state_code)
    place_name, place_code = normalize_state(None, place_of_supply_state_code)
    if not supplier_code:
        raise GSTValidationError("Pick the supplier state to decide CGST/SGST versus IGST.")
    if not place_code:
        raise GSTValidationError("Pick the place of supply state before calculating GST.")
    supply_type = resolve_supply_type(supplier_code, place_code)
    parsed = [
        LineInput(
            quantity=line["quantity"],
            unit_price=line["unit_price"],
            discount=line.get("discount") or 0,
            gst_rate=line["gst_rate"],
            pricing_mode=line.get("pricing_mode") or "exclusive",
        )
        for line in lines
    ]
    totals = invoice_totals(
        parsed,
        supply_type=supply_type,
        other_charges=other_charges,
        round_to_rupee=round_to_rupee,
    )
    return {
        "supply_type": supply_type,
        "supplier_state": supplier_name,
        "supplier_state_code": supplier_code,
        "place_of_supply_state": place_name,
        "place_of_supply_state_code": place_code,
        "lines": totals["lines"],
        "totals": {
            "subtotal": totals["subtotal"],
            "discount": totals["discount"],
            "taxable_value": totals["taxable_value"],
            "cgst_amount": totals["cgst_amount"],
            "sgst_amount": totals["sgst_amount"],
            "igst_amount": totals["igst_amount"],
            "tax_amount": totals["tax_amount"],
            "other_charges": totals["other_charges"],
            "rounding_adjustment": totals["rounding_adjustment"],
            "total_amount": totals["total_amount"],
        },
        "currency": "INR",
        "status": "calculated",
        "note": (
            "Calculated only, nothing was saved. CGST and SGST apply within one state; IGST applies "
            "across states. Confirm the GST rate against the verified HSN/SAC classification."
        ),
    }


# ------------------------------------------------------------------ invoices


def _invoice_scope(db: Session, user: User):
    return db.query(Invoice).filter(Invoice.user_id == user.id, Invoice.status != "void")


def invoice_report_rows(db: Session, user: User, start: date, end: date) -> list[dict]:
    rows = (
        _invoice_scope(db, user)
        .options(selectinload(Invoice.items))
        .filter(Invoice.issue_date >= start, Invoice.issue_date <= end)
        .order_by(Invoice.issue_date.asc(), Invoice.id.asc())
        .all()
    )
    report: list[dict] = []
    for invoice in rows:
        report.append(
            {
                "id": invoice.id,
                "number": invoice.number,
                "issue_date": invoice.issue_date.isoformat(),
                "status": invoice.status,
                "pricing_mode": invoice.pricing_mode,
                "supply_type": invoice.supply_type,
                "supply_verified": invoice.supply_verified,
                "customer_name": invoice.customer_name,
                "customer_gstin": invoice.customer_gstin,
                "place_of_supply_state": invoice.place_of_supply_state,
                "place_of_supply_state_code": invoice.place_of_supply_state_code,
                "taxable_value": q2(invoice.taxable_amount),
                "cgst_amount": q2(invoice.cgst_amount),
                "sgst_amount": q2(invoice.sgst_amount),
                "igst_amount": q2(invoice.igst_amount),
                "tax_amount": q2(invoice.tax_amount),
                "total_amount": q2(invoice.total_amount),
                "hsn_codes": sorted({item.hsn_sac for item in invoice.items if item.hsn_sac}),
                "items_without_hsn": sum(1 for item in invoice.items if not item.hsn_sac),
            }
        )
    return report


def _rate_summary(db: Session, invoice_ids: list[int]) -> list[dict]:
    buckets: dict[Decimal, dict] = {}
    items = (
        db.query(InvoiceItem)
        .filter(InvoiceItem.invoice_id.in_(invoice_ids))
        .all()
        if invoice_ids
        else []
    )
    for item in items:
        rate = q2(item.gst_rate)
        bucket = buckets.setdefault(
            rate,
            {
                "gst_rate": rate,
                "taxable_value": ZERO,
                "cgst_amount": ZERO,
                "sgst_amount": ZERO,
                "igst_amount": ZERO,
                "tax_amount": ZERO,
                "invoice_ids": set(),
            },
        )
        bucket["taxable_value"] += item.taxable_value
        bucket["cgst_amount"] += item.cgst_amount
        bucket["sgst_amount"] += item.sgst_amount
        bucket["igst_amount"] += item.igst_amount
        bucket["tax_amount"] += item.gst_amount
        bucket["invoice_ids"].add(item.invoice_id)
    return [
        {
            "gst_rate": rate,
            "taxable_value": q2(bucket["taxable_value"]),
            "cgst_amount": q2(bucket["cgst_amount"]),
            "sgst_amount": q2(bucket["sgst_amount"]),
            "igst_amount": q2(bucket["igst_amount"]),
            "tax_amount": q2(bucket["tax_amount"]),
            "invoice_count": len(bucket["invoice_ids"]),
        }
        for rate, bucket in sorted(buckets.items())
    ]


def _hsn_summary(db: Session, invoice_ids: list[int]) -> list[dict]:
    if not invoice_ids:
        return []
    buckets: dict[tuple[str | None, Decimal], dict] = {}
    rows = db.query(InvoiceItem).filter(InvoiceItem.invoice_id.in_(invoice_ids)).all()
    for item in rows:
        key = (item.hsn_sac or None, q2(item.gst_rate))
        bucket = buckets.setdefault(
            key,
            {"quantity": Decimal("0"), "taxable_value": ZERO, "tax_amount": ZERO, "items": 0},
        )
        bucket["quantity"] += Decimal(item.quantity)
        bucket["taxable_value"] += item.taxable_value
        bucket["tax_amount"] += item.gst_amount
        bucket["items"] += 1
    return [
        {
            "hsn_sac": hsn,
            "gst_rate": rate,
            "quantity": bucket["quantity"],
            "taxable_value": q2(bucket["taxable_value"]),
            "tax_amount": q2(bucket["tax_amount"]),
            "line_count": bucket["items"],
        }
        for (hsn, rate), bucket in sorted(buckets.items(), key=lambda row: (row[0][0] or "~", row[0][1]))
    ]


def gst_report(db: Session, user: User, *, date_from=None, date_to=None) -> dict:
    start, end = period_bounds(date_from, date_to)
    rows = invoice_report_rows(db, user, start, end)
    invoice_ids = [row["id"] for row in rows]
    totals = {
        "invoice_count": len(rows),
        "taxable_value": q2(sum((row["taxable_value"] for row in rows), ZERO)),
        "cgst_amount": q2(sum((row["cgst_amount"] for row in rows), ZERO)),
        "sgst_amount": q2(sum((row["sgst_amount"] for row in rows), ZERO)),
        "igst_amount": q2(sum((row["igst_amount"] for row in rows), ZERO)),
        "tax_amount": q2(sum((row["tax_amount"] for row in rows), ZERO)),
        "total_amount": q2(sum((row["total_amount"] for row in rows), ZERO)),
    }
    unverified = sum(1 for row in rows if not row["supply_verified"])
    missing_hsn = sum(row["items_without_hsn"] for row in rows)
    warnings: list[str] = []
    if unverified:
        warnings.append(
            f"{unverified} invoice(s) in this period still carry an unverified supply type. "
            "Confirm the place of supply before filing."
        )
    if missing_hsn:
        warnings.append(
            f"{missing_hsn} invoice line(s) have no HSN/SAC code. Add the verified code to every line."
        )
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "invoices": rows,
        "totals": totals,
        "by_rate": _rate_summary(db, invoice_ids),
        "by_hsn": _hsn_summary(db, invoice_ids),
        "warnings": warnings,
        "note": REPORT_NOTE,
    }


# ------------------------------------------------------------------ ITC


def itc_rows(db: Session, user: User, *, start: date | None, end: date | None, status: str | None):
    query = db.query(ITCEntry).filter(ITCEntry.user_id == user.id)
    if start is not None:
        query = query.filter(ITCEntry.invoice_date >= start)
    if end is not None:
        query = query.filter(ITCEntry.invoice_date <= end)
    if status:
        if status not in ITC_STATUSES:
            raise GSTValidationError("ITC status must be eligible, claimed or blocked.")
        query = query.filter(ITCEntry.status == status)
    return query.order_by(ITCEntry.invoice_date.desc(), ITCEntry.id.desc()).all()


def itc_summary(db: Session, user: User, *, date_from=None, date_to=None) -> dict:
    if date_from is None and date_to is None:
        start, end = date(2000, 1, 1), date.today()
    else:
        start, end = period_bounds(date_from, date_to, max_days=None)
    rows = itc_rows(db, user, start=start, end=end, status=None)
    by_status: dict[str, dict] = {
        status: {"status": status, "count": 0, "cgst_amount": ZERO, "sgst_amount": ZERO, "igst_amount": ZERO, "eligible_amount": ZERO}
        for status in ITC_STATUSES
    }
    for row in rows:
        bucket = by_status[row.status]
        bucket["count"] += 1
        bucket["cgst_amount"] += row.cgst_amount
        bucket["sgst_amount"] += row.sgst_amount
        bucket["igst_amount"] += row.igst_amount
        bucket["eligible_amount"] += row.eligible_amount
    status_rows = []
    for bucket in by_status.values():
        status_rows.append(
            {
                "status": bucket["status"],
                "count": bucket["count"],
                "cgst_amount": q2(bucket["cgst_amount"]),
                "sgst_amount": q2(bucket["sgst_amount"]),
                "igst_amount": q2(bucket["igst_amount"]),
                "eligible_amount": q2(bucket["eligible_amount"]),
            }
        )
    available = q2(
        sum((row.eligible_amount for row in rows if row.status in ("eligible", "claimed")), ZERO)
    )
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "entries": [
            {
                "id": row.id,
                "supplier_name": row.supplier_name,
                "supplier_gstin": row.supplier_gstin,
                "invoice_number": row.invoice_number,
                "invoice_date": row.invoice_date.isoformat(),
                "taxable_value": q2(row.taxable_value),
                "gst_rate": q2(row.gst_rate),
                "cgst_amount": q2(row.cgst_amount),
                "sgst_amount": q2(row.sgst_amount),
                "igst_amount": q2(row.igst_amount),
                "eligible_amount": q2(row.eligible_amount),
                "status": row.status,
                "note": row.note,
            }
            for row in rows
        ],
        "by_status": status_rows,
        "available_itc": available,
        "note": (
            "Only claim credit you can support with a valid tax invoice and a supplier return that "
            "reports the same invoice. Blocked credit is excluded from the available total."
        ),
    }


def create_itc_entry(db: Session, user: User, payload, created_by: User) -> ITCEntry:
    gstin = normalize_gstin(payload.supplier_gstin)
    taxable = Decimal(str(payload.taxable_value))
    rate = Decimal(str(payload.gst_rate))
    if taxable < 0:
        raise GSTValidationError("Taxable value cannot be negative.")
    if rate < 0 or rate > 100:
        raise GSTValidationError("GST rate must be between 0 and 100 percent.")
    cgst = Decimal(str(payload.cgst_amount or 0))
    sgst = Decimal(str(payload.sgst_amount or 0))
    igst = Decimal(str(payload.igst_amount or 0))
    for label, value in (("CGST", cgst), ("SGST", sgst), ("IGST", igst)):
        if value < 0:
            raise GSTValidationError(f"{label} cannot be negative.")
    if igst > 0 and (cgst > 0 or sgst > 0):
        raise GSTValidationError("A purchase bill is either intra-state (CGST+SGST) or inter-state (IGST).")
    tax = cgst + sgst + igst
    expected = q2(taxable * rate / Decimal("100"))
    if tax > 0 and abs(q2(tax) - expected) > Decimal("1.00"):
        raise GSTValidationError(
            f"The GST amount {q2(tax)} does not match {rate}% of the taxable value ({expected}). "
            "Check the bill; do not guess the credit."
        )
    eligible = q2(payload.eligible_amount if payload.eligible_amount is not None else tax)
    if eligible < 0 or eligible > q2(tax):
        raise GSTValidationError("Eligible credit must be between zero and the GST on the bill.")
    if payload.status not in ITC_STATUSES:
        raise GSTValidationError("ITC status must be eligible, claimed or blocked.")
    if not payload.supplier_name.strip():
        raise GSTValidationError("Supplier name is required.")
    if not payload.invoice_number.strip():
        raise GSTValidationError("Purchase invoice number is required.")
    invoice_date = _d(payload.invoice_date)
    if invoice_date is None:
        raise GSTValidationError("Purchase invoice date is required.")
    if invoice_date > date.today():
        raise GSTValidationError("Purchase invoice date cannot be in the future.")
    entry = ITCEntry(
        user_id=user.id,
        supplier_name=payload.supplier_name.strip(),
        supplier_gstin=gstin,
        invoice_number=payload.invoice_number.strip(),
        invoice_date=invoice_date,
        taxable_value=q2(taxable),
        gst_rate=q2(rate),
        cgst_amount=q2(cgst),
        sgst_amount=q2(sgst),
        igst_amount=q2(igst),
        eligible_amount=eligible,
        status=payload.status,
        note=(payload.note or "").strip() or None,
        created_by_user_id=created_by.id,
    )
    db.add(entry)
    db.flush()
    return entry


def net_gst(db: Session, user: User, *, date_from=None, date_to=None) -> dict:
    start, end = period_bounds(date_from, date_to)
    report = gst_report(db, user, date_from=start, date_to=end)
    itc = itc_summary(db, user, date_from=start, date_to=end)
    output_tax = report["totals"]["tax_amount"]
    available = itc["available_itc"]
    net = q2(output_tax - available)
    return {
        "period": report["period"],
        "output_gst": report["totals"],
        "input_tax_credit": {
            "available": available,
            "by_status": itc["by_status"],
        },
        "net_gst": {
            "amount": abs(net),
            "direction": "payable" if net > 0 else ("refundable" if net < 0 else "nil"),
            "payable": net if net > 0 else ZERO,
            "refundable": q2(-net) if net < 0 else ZERO,
        },
        "warnings": report["warnings"],
        "note": (
            "An estimate of the net GST position for the period: output tax on issued invoices minus "
            "available input credit. It ignores opening credit balances, reverse charge and portal "
            "adjustments, so reconcile against GSTR-1, GSTR-2B and GSTR-3B before paying."
        ),
    }


# ------------------------------------------------------------------ HSN/SAC


def hsn_options(db: Session, user: User, kind: str | None = None) -> list[HSNSACClassification]:
    query = db.query(HSNSACClassification).filter(HSNSACClassification.user_id == user.id)
    if kind:
        if kind not in ("goods", "services"):
            raise GSTValidationError("HSN/SAC kind must be goods or services.")
        query = query.filter(HSNSACClassification.kind == kind)
    return query.order_by(HSNSACClassification.code.asc()).all()


def hsn_to_dict(row: HSNSACClassification) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "description": row.description,
        "kind": row.kind,
        "gst_rate": q2(row.gst_rate),
        "verified": row.verified,
        "note": row.note,
    }


def validate_hsn_code(code: str, kind: str) -> str:
    cleaned = (code or "").strip()
    if kind not in ("goods", "services"):
        raise GSTValidationError("HSN/SAC kind must be goods or services.")
    if kind == "goods":
        if not cleaned.isdigit():
            raise GSTValidationError("An HSN code for goods contains digits only.")
        if len(cleaned) not in (2, 4, 6, 8):
            raise GSTValidationError("An HSN code must be 2, 4, 6 or 8 digits.")
    else:
        if not cleaned.isdigit():
            raise GSTValidationError("An SAC code contains digits only.")
        if len(cleaned) != 6:
            raise GSTValidationError("An SAC code must be exactly 6 digits.")
    return cleaned


def invoice_has_verified_hsn(db: Session, user: User) -> dict:
    """Counts used by the dashboard to nudge owners towards verified classifications."""
    total = (
        db.query(func.count(InvoiceItem.id))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(Invoice.user_id == user.id, Invoice.status != "void")
        .scalar()
        or 0
    )
    missing = (
        db.query(func.count(InvoiceItem.id))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(
            Invoice.user_id == user.id,
            Invoice.status != "void",
            or_(InvoiceItem.hsn_sac.is_(None), InvoiceItem.hsn_sac == ""),
        )
        .scalar()
        or 0
    )
    verified_codes = {
        row.code
        for row in db.query(HSNSACClassification)
        .filter(HSNSACClassification.user_id == user.id, HSNSACClassification.verified.is_(True))
        .all()
    }
    return {"invoice_lines": int(total), "lines_without_hsn": int(missing), "verified_codes": len(verified_codes)}
