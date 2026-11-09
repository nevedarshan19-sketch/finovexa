"""Customer and supplier credit management.

Balances, utilisation, ageing and statements are derived from the existing
invoices, payments and expenses. Nothing stores a second ledger: the only new
money record is ``supplier_payments`` for money paid out to a supplier.

All arithmetic uses Decimal and ``q2`` rounding. Historical invoice, payment
and expense rows are never rewritten.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import (
    Customer,
    CustomerAdjustment,
    CreditAlert,
    CreditAlertSettings,
    Expense,
    Invoice,
    Payment,
    Supplier,
    SupplierPayment,
    User,
    utcnow,
)
from .audit import log_audit
from .delivery import DeliveryError, send_email
from .finance import q2
from .gst import GSTValidationError, normalize_gstin

ZERO = Decimal("0.00")
AGE_BUCKETS = ("0-30", "31-60", "61-90", "90+")
ADJUSTMENT_KINDS = ("credit_note", "debit_note", "write_off")
SUPPLIER_STATUSES = ("active", "on_hold", "inactive")
ALERT_KINDS = (
    "utilization_warn",
    "utilization_critical",
    "invoice_due_soon",
    "invoice_overdue",
    "overdue_escalation",
    "payment_received",
    "supplier_due_soon",
    "supplier_overdue",
)
DEFAULT_SETTINGS = {
    "utilization_warn_pct": 80,
    "utilization_critical_pct": 100,
    "due_soon_days": 7,
    "overdue_escalation_days": 7,
    "supplier_due_soon_days": 7,
    "in_app_enabled": True,
    "email_enabled": False,
}


def money(value: Any) -> Decimal:
    return q2(value or ZERO)


def normalize_name(value: str | None) -> str:
    """Lowercase letters and digits only, used as the supplier matching key."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _age_bucket(due_on: date, today: date) -> str:
    days = (today - due_on).days
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def _empty_buckets() -> dict[str, Decimal]:
    return {bucket: ZERO for bucket in AGE_BUCKETS}


def _payment_date(payment: Payment) -> date:
    return (payment.received_at or payment.created_at).date()


# ---------------------------------------------------------------------------
# Alert settings
# ---------------------------------------------------------------------------


def settings_row(db: Session, user_id: int) -> CreditAlertSettings | None:
    return (
        db.query(CreditAlertSettings)
        .filter(CreditAlertSettings.user_id == user_id)
        .one_or_none()
    )


def settings_values(db: Session, user_id: int) -> dict[str, Any]:
    row = settings_row(db, user_id)
    if row is None:
        return dict(DEFAULT_SETTINGS)
    return {
        "utilization_warn_pct": row.utilization_warn_pct,
        "utilization_critical_pct": row.utilization_critical_pct,
        "due_soon_days": row.due_soon_days,
        "overdue_escalation_days": row.overdue_escalation_days,
        "supplier_due_soon_days": row.supplier_due_soon_days,
        "in_app_enabled": row.in_app_enabled,
        "email_enabled": row.email_enabled,
        "updated_by_user_id": row.updated_by_user_id,
        "updated_at": row.updated_at,
    }


def update_settings(db: Session, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    row = settings_row(db, user.id)
    if row is None:
        row = CreditAlertSettings(user_id=user.id)
        db.add(row)
    for key in DEFAULT_SETTINGS:
        if key in payload and payload[key] is not None:
            setattr(row, key, payload[key])
    row.updated_by_user_id = user.id
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.alert_settings_updated",
        entity_type="credit_alert_settings",
        entity_id=row.id,
        detail={key: payload[key] for key in DEFAULT_SETTINGS if key in payload},
    )
    db.commit()
    db.refresh(row)
    return settings_values(db, user.id)


# ---------------------------------------------------------------------------
# Derived customer positions
# ---------------------------------------------------------------------------


@dataclass
class CustomerPosition:
    customer: Customer
    opening: Decimal = ZERO
    invoiced: Decimal = ZERO
    paid: Decimal = ZERO
    credits: Decimal = ZERO
    debits: Decimal = ZERO
    advances: Decimal = ZERO
    outstanding: Decimal = ZERO
    overdue: Decimal = ZERO
    aging: dict[str, Decimal] = field(default_factory=_empty_buckets)
    invoice_count: int = 0
    invoice_residuals: dict[int, Decimal] = field(default_factory=dict)


def _customer_positions(
    db: Session, user_id: int, *, today: date | None = None
) -> dict[int, CustomerPosition]:
    today = today or date.today()
    customers = db.query(Customer).filter(Customer.user_id == user_id).all()
    positions = {
        customer.id: CustomerPosition(customer=customer, opening=money(customer.opening_balance))
        for customer in customers
    }
    invoices = (
        db.query(Invoice)
        .filter(Invoice.user_id == user_id, Invoice.status != "void")
        .all()
    )
    payments = (
        db.query(Payment)
        .filter(Payment.user_id == user_id, Payment.status == "confirmed")
        .all()
    )
    adjustments = (
        db.query(CustomerAdjustment)
        .filter(CustomerAdjustment.user_id == user_id, CustomerAdjustment.status != "void")
        .all()
    )

    payments_by_invoice: dict[int, Decimal] = defaultdict(lambda: ZERO)
    advance_payments: list[Payment] = []
    for payment in payments:
        if payment.invoice_id is not None:
            payments_by_invoice[payment.invoice_id] += money(payment.amount)
        elif payment.refund_of_payment_id is None:
            advance_payments.append(payment)

    invoice_adjustments: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for adjustment in adjustments:
        amount = money(adjustment.amount)
        if adjustment.kind in ("credit_note", "write_off"):
            signed = -amount
            positions[adjustment.customer_id].credits += amount
        else:
            signed = amount
            positions[adjustment.customer_id].debits += amount
        if adjustment.invoice_id is not None:
            invoice_adjustments[adjustment.invoice_id] += signed

    for invoice in invoices:
        position = positions.get(invoice.customer_id)
        if position is None:
            continue
        total = money(invoice.total_amount)
        paid = payments_by_invoice.get(invoice.id, ZERO)
        residual = total - paid + invoice_adjustments.get(invoice.id, ZERO)
        position.invoiced += total
        position.paid += paid
        position.invoice_count += 1
        if residual > ZERO:
            position.invoice_residuals[invoice.id] = residual
            position.outstanding += residual
            if invoice.due_date < today:
                position.overdue += residual
            position.aging[_age_bucket(invoice.due_date, today)] += residual
        elif residual < ZERO:
            position.advances += -residual

    # Advances are payments without an invoice. Attribute them only when the
    # sender name matches exactly one customer; never guess otherwise.
    by_name: dict[str, list[Customer]] = defaultdict(list)
    for customer in customers:
        by_name[normalize_name(customer.name)].append(customer)
    for payment in advance_payments:
        key = normalize_name(payment.sender_name)
        candidates = by_name.get(key, []) if key else []
        if len(candidates) != 1:
            continue
        position = positions[candidates[0].id]
        position.advances += money(payment.amount)
        position.paid += money(payment.amount)

    for position in positions.values():
        position.outstanding = money(
            position.opening
            + position.invoiced
            + position.debits
            - position.credits
            - position.paid
        )
        position.invoiced = money(position.invoiced)
        position.paid = money(position.paid)
        position.credits = money(position.credits)
        position.debits = money(position.debits)
        position.advances = money(position.advances)
        position.overdue = money(position.overdue)
        position.aging = {bucket: money(value) for bucket, value in position.aging.items()}
    return positions


def _risk_status(
    position: CustomerPosition, settings: dict[str, Any], today: date
) -> tuple[str, Decimal | None]:
    if position.customer.credit_hold:
        return "on_hold", None
    limit = money(position.customer.credit_limit)
    if limit <= ZERO:
        return "not_configured", None
    utilisation = q2(max(position.outstanding, ZERO) * 100 / limit)
    if position.outstanding > limit:
        return "over_limit", utilisation
    if utilisation >= Decimal(settings["utilization_critical_pct"]):
        return "critical", utilisation
    if utilisation >= Decimal(settings["utilization_warn_pct"]):
        return "watch", utilisation
    if position.overdue > ZERO:
        return "overdue", utilisation
    return "normal", utilisation


def customer_to_dict(
    position: CustomerPosition, settings: dict[str, Any], today: date
) -> dict[str, Any]:
    customer = position.customer
    risk, utilisation = _risk_status(position, settings, today)
    limit = money(customer.credit_limit)
    available = q2(max(limit - max(position.outstanding, ZERO), ZERO)) if limit > ZERO else ZERO
    return {
        "id": customer.id,
        "name": customer.name,
        "company": customer.company,
        "email": customer.email,
        "phone": customer.phone,
        "gstin": customer.gstin,
        "credit_limit": limit,
        "payment_terms_days": customer.payment_terms_days,
        "credit_hold": customer.credit_hold,
        "opening_balance": money(customer.opening_balance),
        "opening_balance_date": customer.opening_balance_date,
        "notes": customer.notes,
        "outstanding": position.outstanding,
        "available_credit": available,
        "utilization_pct": utilisation,
        "risk_status": risk,
        "overdue": position.overdue,
        "invoiced": position.invoiced,
        "paid": position.paid,
        "credits": position.credits,
        "debits": position.debits,
        "advance_credit": position.advances,
        "invoice_count": position.invoice_count,
        "aging": position.aging,
    }


def customer_directory(
    db: Session,
    user_id: int,
    *,
    q: str | None = None,
    risk: str | None = None,
    sort: str = "name",
    order: str = "asc",
    page: int = 1,
    page_size: int = 25,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    settings = settings_values(db, user_id)
    positions = _customer_positions(db, user_id, today=today)
    rows = [customer_to_dict(row, settings, today) for row in positions.values()]
    if q and q.strip():
        needle = q.strip().lower()
        rows = [
            row
            for row in rows
            if needle
            in " ".join(
                str(row[key] or "")
                for key in ("name", "company", "email", "phone", "gstin")
            ).lower()
        ]
    if risk and risk != "all":
        rows = [row for row in rows if row["risk_status"] == risk]
    if sort in {"name", "outstanding", "overdue", "utilization_pct", "credit_limit"}:
        rows.sort(
            key=lambda row: (row[sort] is None, row[sort]) if sort != "name" else row[sort].lower(),
            reverse=order == "desc",
        )
    else:
        rows.sort(key=lambda row: row["name"].lower(), reverse=order == "desc")
    total = len(rows)
    start = max(page - 1, 0) * page_size
    return {
        "items": rows[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max((total + page_size - 1) // page_size, 1),
    }


def customer_detail(
    db: Session, user_id: int, customer_id: int, *, today: date | None = None
) -> dict[str, Any]:
    today = today or date.today()
    positions = _customer_positions(db, user_id, today=today)
    position = positions.get(customer_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    settings = settings_values(db, user_id)
    data = customer_to_dict(position, settings, today)
    data["invoices"] = [
        {
            "id": invoice.id,
            "number": invoice.number,
            "issue_date": invoice.issue_date,
            "due_date": invoice.due_date,
            "status": invoice.status,
            "total": money(invoice.total_amount),
            "outstanding": position.invoice_residuals.get(invoice.id, ZERO),
            "bucket": _age_bucket(invoice.due_date, today)
            if invoice.id in position.invoice_residuals
            else None,
        }
        for invoice in db.query(Invoice)
        .filter(Invoice.user_id == user_id, Invoice.customer_id == customer_id)
        .order_by(Invoice.issue_date.desc(), Invoice.id.desc())
        .limit(200)
        .all()
    ]
    data["adjustments"] = [
        adjustment_to_dict(row)
        for row in db.query(CustomerAdjustment)
        .filter(
            CustomerAdjustment.user_id == user_id,
            CustomerAdjustment.customer_id == customer_id,
        )
        .order_by(CustomerAdjustment.issued_on.desc(), CustomerAdjustment.id.desc())
        .limit(200)
        .all()
    ]
    return data


def update_customer_credit(
    db: Session, user: User, customer_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.user_id == user.id)
        .one_or_none()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    if payload.get("credit_limit") is not None:
        customer.credit_limit = money(payload["credit_limit"])
    if payload.get("payment_terms_days") is not None:
        customer.payment_terms_days = int(payload["payment_terms_days"])
    if payload.get("credit_hold") is not None:
        customer.credit_hold = bool(payload["credit_hold"])
    if payload.get("opening_balance") is not None:
        customer.opening_balance = money(payload["opening_balance"])
    if payload.get("opening_balance_date") is not None:
        customer.opening_balance_date = payload["opening_balance_date"]
    if "notes" in payload:
        customer.notes = _clean(payload.get("notes"))
    if money(customer.opening_balance) > ZERO and customer.opening_balance_date is None:
        raise HTTPException(
            status_code=400,
            detail="Set an opening balance date when an opening balance is recorded.",
        )
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.customer_settings_updated",
        entity_type="customer",
        entity_id=customer.id,
        detail={key: payload[key] for key in payload if key != "notes"},
    )
    db.commit()
    return customer_detail(db, user.id, customer.id)


# ---------------------------------------------------------------------------
# Customer ledger and adjustments
# ---------------------------------------------------------------------------


def customer_ledger(
    db: Session,
    user_id: int,
    customer_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.user_id == user_id)
        .one_or_none()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    entries: list[dict[str, Any]] = []
    opening = money(customer.opening_balance)
    opening_date = customer.opening_balance_date or date(1900, 1, 1)
    if opening > ZERO:
        entries.append(
            {
                "date": opening_date,
                "sort": (0, 0, 0),
                "type": "opening",
                "reference": "Opening balance",
                "description": "Opening receivable",
                "debit": opening,
                "credit": ZERO,
            }
        )
    invoices = (
        db.query(Invoice)
        .filter(Invoice.user_id == user_id, Invoice.customer_id == customer_id)
        .all()
    )
    invoice_ids = {invoice.id for invoice in invoices}
    for invoice in invoices:
        if invoice.status == "void":
            continue
        entries.append(
            {
                "date": invoice.issue_date,
                "sort": (1, invoice.issue_date.toordinal(), invoice.id),
                "type": "invoice",
                "reference": invoice.number,
                "description": f"Sales invoice · due {invoice.due_date.isoformat()}",
                "debit": money(invoice.total_amount),
                "credit": ZERO,
            }
        )
    for payment in (
        db.query(Payment)
        .filter(Payment.user_id == user_id, Payment.status == "confirmed")
        .all()
    ):
        if payment.invoice_id is not None and payment.invoice_id not in invoice_ids:
            continue
        if payment.invoice_id is None:
            if normalize_name(payment.sender_name) != normalize_name(customer.name):
                continue
        value = money(payment.amount)
        is_refund = payment.refund_of_payment_id is not None
        entries.append(
            {
                "date": _payment_date(payment),
                "sort": (2, _payment_date(payment).toordinal(), payment.id),
                "type": "refund" if is_refund else "payment",
                "reference": payment.provider_ref or f"PMT-{payment.id}",
                "description": (
                    f"Refund · {payment.method}"
                    if is_refund
                    else f"Payment received · {payment.method}"
                ),
                "debit": -value if value < ZERO else ZERO,
                "credit": value if value >= ZERO else ZERO,
            }
        )
    for adjustment in (
        db.query(CustomerAdjustment)
        .filter(
            CustomerAdjustment.user_id == user_id,
            CustomerAdjustment.customer_id == customer_id,
            CustomerAdjustment.status != "void",
        )
        .all()
    ):
        value = money(adjustment.amount)
        entries.append(
            {
                "date": adjustment.issued_on,
                "sort": (3, adjustment.issued_on.toordinal(), adjustment.id),
                "type": adjustment.kind,
                "reference": adjustment.number,
                "description": adjustment.reason,
                "debit": value if adjustment.kind == "debit_note" else ZERO,
                "credit": ZERO if adjustment.kind == "debit_note" else value,
            }
        )
    entries.sort(key=lambda row: (row["date"], row["sort"]))
    running = ZERO
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if date_from and entry["date"] < date_from:
            continue
        if date_to and entry["date"] > date_to:
            continue
        running += entry["debit"] - entry["credit"]
        rows.append(
            {
                "date": entry["date"],
                "type": entry["type"],
                "reference": entry["reference"],
                "description": entry["description"],
                "debit": money(entry["debit"]),
                "credit": money(entry["credit"]),
                "balance": money(running),
            }
        )
    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "gstin": customer.gstin,
            "phone": customer.phone,
            "email": customer.email,
            "credit_limit": money(customer.credit_limit),
            "payment_terms_days": customer.payment_terms_days,
        },
        "date_from": date_from,
        "date_to": date_to,
        "opening_balance": opening,
        "closing_balance": money(running),
        "rows": rows,
    }


def adjustment_to_dict(row: CustomerAdjustment) -> dict[str, Any]:
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "invoice_id": row.invoice_id,
        "kind": row.kind,
        "number": row.number,
        "amount": money(row.amount),
        "issued_on": row.issued_on,
        "reason": row.reason,
        "status": row.status,
        "created_at": row.created_at,
    }


def _next_adjustment_number(db: Session, user_id: int, kind: str, issued_on: date) -> str:
    prefix = {"credit_note": "CN", "debit_note": "DN", "write_off": "WO"}[kind]
    base = f"{prefix}-{issued_on.strftime('%Y%m')}-"
    numbers = (
        db.query(CustomerAdjustment.number)
        .filter(
            CustomerAdjustment.user_id == user_id,
            CustomerAdjustment.number.like(f"{base}%"),
        )
        .all()
    )
    sequence = 0
    for (number,) in numbers:
        try:
            sequence = max(sequence, int(str(number).rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{base}{sequence + 1:04d}"


def create_adjustment(
    db: Session, user: User, customer_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.user_id == user.id)
        .one_or_none()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    kind = payload["kind"]
    if kind not in ADJUSTMENT_KINDS:
        raise HTTPException(status_code=400, detail="Unknown adjustment type.")
    invoice_id = payload.get("invoice_id")
    if invoice_id is not None:
        invoice = (
            db.query(Invoice)
            .filter(
                Invoice.id == invoice_id,
                Invoice.user_id == user.id,
                Invoice.customer_id == customer_id,
            )
            .one_or_none()
        )
        if invoice is None:
            raise HTTPException(status_code=404, detail="Invoice not found for this customer.")
    number = _clean(payload.get("number")) or _next_adjustment_number(
        db, user.id, kind, payload["issued_on"]
    )
    duplicate = (
        db.query(CustomerAdjustment)
        .filter(CustomerAdjustment.user_id == user.id, CustomerAdjustment.number == number)
        .one_or_none()
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="This adjustment number already exists.")
    adjustment = CustomerAdjustment(
        user_id=user.id,
        customer_id=customer_id,
        invoice_id=invoice_id,
        kind=kind,
        number=number,
        amount=money(payload["amount"]),
        issued_on=payload["issued_on"],
        reason=payload["reason"].strip(),
        status="open",
        created_by_user_id=user.id,
    )
    db.add(adjustment)
    db.flush()
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action=f"credit.adjustment_{kind}",
        entity_type="customer_adjustment",
        entity_id=adjustment.id,
        detail={
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "number": number,
            "amount": str(adjustment.amount),
        },
    )
    db.commit()
    db.refresh(adjustment)
    return adjustment_to_dict(adjustment)


def void_adjustment(
    db: Session, user: User, adjustment_id: int, reason: str
) -> dict[str, Any]:
    adjustment = (
        db.query(CustomerAdjustment)
        .filter(
            CustomerAdjustment.id == adjustment_id,
            CustomerAdjustment.user_id == user.id,
        )
        .one_or_none()
    )
    if adjustment is None:
        raise HTTPException(status_code=404, detail="Adjustment not found.")
    if adjustment.status == "void":
        raise HTTPException(status_code=409, detail="This adjustment is already void.")
    adjustment.status = "void"
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.adjustment_voided",
        entity_type="customer_adjustment",
        entity_id=adjustment.id,
        detail={"number": adjustment.number, "reason": reason},
    )
    db.commit()
    db.refresh(adjustment)
    return adjustment_to_dict(adjustment)


# ---------------------------------------------------------------------------
# Suppliers and payables
# ---------------------------------------------------------------------------


@dataclass
class SupplierPosition:
    supplier: Supplier
    opening: Decimal = ZERO
    billed: Decimal = ZERO
    paid: Decimal = ZERO
    payable: Decimal = ZERO
    overdue: Decimal = ZERO
    aging: dict[str, Decimal] = field(default_factory=_empty_buckets)
    bill_count: int = 0
    bill_residuals: dict[int, Decimal] = field(default_factory=dict)


def _supplier_positions(
    db: Session, user_id: int, *, today: date | None = None
) -> dict[int, SupplierPosition]:
    today = today or date.today()
    suppliers = db.query(Supplier).filter(Supplier.user_id == user_id).all()
    positions = {
        supplier.id: SupplierPosition(
            supplier=supplier, opening=money(supplier.opening_balance)
        )
        for supplier in suppliers
    }
    bills = (
        db.query(Expense)
        .filter(
            Expense.user_id == user_id,
            Expense.supplier_id.isnot(None),
            Expense.payment_status != "void",
        )
        .all()
    )
    payments = (
        db.query(SupplierPayment)
        .filter(
            SupplierPayment.user_id == user_id,
            SupplierPayment.status == "confirmed",
        )
        .all()
    )
    paid_by_bill: dict[int, Decimal] = defaultdict(lambda: ZERO)
    advances: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for payment in payments:
        position = positions.get(payment.supplier_id)
        if position is None:
            continue
        value = money(payment.amount)
        position.paid += value
        if payment.expense_id is None:
            advances[payment.supplier_id] += value
        else:
            paid_by_bill[payment.expense_id] += value

    for bill in bills:
        position = positions.get(bill.supplier_id)
        if position is None:
            continue
        total = money(bill.amount)
        paid = paid_by_bill.get(bill.id, ZERO)
        residual = total - paid
        position.billed += total
        position.bill_count += 1
        if residual > ZERO:
            position.bill_residuals[bill.id] = residual
            position.payable += residual
            due_on = bill.due_date or bill.incurred_on
            if due_on < today:
                position.overdue += residual
            position.aging[_age_bucket(due_on, today)] += residual
        elif residual < ZERO:
            positions[bill.supplier_id].payable -= -residual

    for position in positions.values():
        position.payable = money(
            position.opening + position.billed - position.paid
        )
        position.billed = money(position.billed)
        position.paid = money(position.paid)
        position.overdue = money(position.overdue)
        position.aging = {bucket: money(value) for bucket, value in position.aging.items()}
    return positions


def supplier_to_dict(position: SupplierPosition) -> dict[str, Any]:
    supplier = position.supplier
    return {
        "id": supplier.id,
        "name": supplier.name,
        "gstin": supplier.gstin,
        "email": supplier.email,
        "phone": supplier.phone,
        "city": supplier.city,
        "state": supplier.state,
        "payment_terms_days": supplier.payment_terms_days,
        "credit_limit": money(supplier.credit_limit),
        "opening_balance": money(supplier.opening_balance),
        "opening_balance_date": supplier.opening_balance_date,
        "status": supplier.status,
        "notes": supplier.notes,
        "billed": position.billed,
        "paid": position.paid,
        "payable": position.payable,
        "overdue": position.overdue,
        "advance_paid": money(max(-position.payable, ZERO)),
        "bill_count": position.bill_count,
        "aging": position.aging,
    }


def supplier_directory(
    db: Session,
    user_id: int,
    *,
    q: str | None = None,
    status: str | None = None,
    sort: str = "name",
    order: str = "asc",
    page: int = 1,
    page_size: int = 25,
    today: date | None = None,
) -> dict[str, Any]:
    positions = _supplier_positions(db, user_id, today=today)
    rows = [supplier_to_dict(position) for position in positions.values()]
    if q and q.strip():
        needle = q.strip().lower()
        rows = [
            row
            for row in rows
            if needle
            in " ".join(
                str(row[key] or "") for key in ("name", "gstin", "email", "phone")
            ).lower()
        ]
    if status and status != "all":
        rows = [row for row in rows if row["status"] == status]
    if sort in {"name", "payable", "overdue", "billed", "paid"}:
        rows.sort(
            key=lambda row: row[sort].lower() if sort == "name" else row[sort],
            reverse=order == "desc",
        )
    total = len(rows)
    start = max(page - 1, 0) * page_size
    return {
        "items": rows[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max((total + page_size - 1) // page_size, 1),
    }


def supplier_detail(
    db: Session, user_id: int, supplier_id: int, *, today: date | None = None
) -> dict[str, Any]:
    positions = _supplier_positions(db, user_id, today=today)
    position = positions.get(supplier_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    data = supplier_to_dict(position)
    data["bills"] = [
        {
            "id": bill.id,
            "bill_number": bill.bill_number,
            "vendor": bill.vendor,
            "category": bill.category,
            "incurred_on": bill.incurred_on,
            "due_date": bill.due_date,
            "amount": money(bill.amount),
            "outstanding": position.bill_residuals.get(bill.id, ZERO),
            "payment_status": bill.payment_status,
            "bucket": _age_bucket(bill.due_date or bill.incurred_on, today or date.today())
            if bill.id in position.bill_residuals
            else None,
        }
        for bill in db.query(Expense)
        .filter(Expense.user_id == user_id, Expense.supplier_id == supplier_id)
        .order_by(Expense.incurred_on.desc(), Expense.id.desc())
        .limit(500)
        .all()
    ]
    data["payments"] = [
        supplier_payment_to_dict(row)
        for row in db.query(SupplierPayment)
        .filter(
            SupplierPayment.user_id == user_id,
            SupplierPayment.supplier_id == supplier_id,
        )
        .order_by(SupplierPayment.paid_on.desc(), SupplierPayment.id.desc())
        .limit(500)
        .all()
    ]
    return data


def create_supplier(db: Session, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    name = payload["name"].strip()
    normalized = normalize_name(name)
    if not normalized:
        raise HTTPException(status_code=400, detail="Enter a valid supplier name.")
    try:
        gstin = normalize_gstin(payload.get("gstin"))
    except GSTValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    duplicate_query = db.query(Supplier).filter(
        Supplier.user_id == user.id, Supplier.normalized_name == normalized
    )
    if gstin:
        duplicate_query = duplicate_query.filter(Supplier.gstin == gstin)
    if duplicate_query.one_or_none() is not None:
        raise HTTPException(status_code=409, detail="This supplier already exists.")
    if payload.get("opening_balance_date") is None and money(payload.get("opening_balance")) > ZERO:
        raise HTTPException(
            status_code=400,
            detail="Set an opening balance date when an opening balance is recorded.",
        )
    supplier = Supplier(
        user_id=user.id,
        name=name,
        normalized_name=normalized,
        gstin=gstin,
        email=str(payload["email"]).lower() if payload.get("email") else None,
        phone=_clean(payload.get("phone")),
        address_line1=_clean(payload.get("address_line1")),
        address_line2=_clean(payload.get("address_line2")),
        city=_clean(payload.get("city")),
        state=_clean(payload.get("state")),
        state_code=_clean(payload.get("state_code")),
        postal_code=_clean(payload.get("postal_code")),
        payment_terms_days=payload.get("payment_terms_days", 30),
        credit_limit=money(payload.get("credit_limit")),
        opening_balance=money(payload.get("opening_balance")),
        opening_balance_date=payload.get("opening_balance_date"),
        status=payload.get("status", "active"),
        notes=_clean(payload.get("notes")),
    )
    db.add(supplier)
    db.flush()
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.supplier_created",
        entity_type="supplier",
        entity_id=supplier.id,
        detail={"name": supplier.name, "gstin": supplier.gstin},
    )
    db.commit()
    db.refresh(supplier)
    return supplier_detail(db, user.id, supplier.id)


def update_supplier(
    db: Session, user: User, supplier_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.user_id == user.id)
        .one_or_none()
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    if payload.get("name") is not None:
        name = payload["name"].strip()
        normalized = normalize_name(name)
        if not normalized:
            raise HTTPException(status_code=400, detail="Enter a valid supplier name.")
        duplicate_query = db.query(Supplier).filter(
            Supplier.user_id == user.id,
            Supplier.normalized_name == normalized,
            Supplier.id != supplier.id,
        )
        gstin = supplier.gstin
        if gstin:
            duplicate_query = duplicate_query.filter(Supplier.gstin == gstin)
        if duplicate_query.one_or_none() is not None:
            raise HTTPException(status_code=409, detail="This supplier already exists.")
        supplier.name = name
        supplier.normalized_name = normalized
    if "gstin" in payload:
        try:
            supplier.gstin = normalize_gstin(payload.get("gstin"))
        except GSTValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for key in (
        "phone",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "state_code",
        "postal_code",
        "notes",
    ):
        if key in payload:
            setattr(supplier, key, _clean(payload.get(key)))
    if "email" in payload:
        supplier.email = str(payload["email"]).lower() if payload["email"] else None
    if payload.get("payment_terms_days") is not None:
        supplier.payment_terms_days = int(payload["payment_terms_days"])
    if payload.get("credit_limit") is not None:
        supplier.credit_limit = money(payload["credit_limit"])
    if payload.get("opening_balance") is not None:
        supplier.opening_balance = money(payload["opening_balance"])
    if payload.get("opening_balance_date") is not None:
        supplier.opening_balance_date = payload["opening_balance_date"]
    if payload.get("status") is not None:
        if payload["status"] not in SUPPLIER_STATUSES:
            raise HTTPException(status_code=400, detail="Unknown supplier status.")
        supplier.status = payload["status"]
    if money(supplier.opening_balance) > ZERO and supplier.opening_balance_date is None:
        raise HTTPException(
            status_code=400,
            detail="Set an opening balance date when an opening balance is recorded.",
        )
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.supplier_updated",
        entity_type="supplier",
        entity_id=supplier.id,
        detail={key: payload[key] for key in payload if key != "notes"},
    )
    db.commit()
    return supplier_detail(db, user.id, supplier.id)


def supplier_payment_to_dict(row: SupplierPayment) -> dict[str, Any]:
    return {
        "id": row.id,
        "supplier_id": row.supplier_id,
        "expense_id": row.expense_id,
        "amount": money(row.amount),
        "method": row.method,
        "reference": row.reference,
        "paid_on": row.paid_on,
        "status": row.status,
        "note": row.note,
        "voided_at": row.voided_at,
        "void_reason": row.void_reason,
        "created_at": row.created_at,
    }


def _bill_outstanding(db: Session, bill: Expense) -> Decimal:
    paid = q2(
        db.query(func.coalesce(func.sum(SupplierPayment.amount), 0))
        .filter(
            SupplierPayment.expense_id == bill.id,
            SupplierPayment.status == "confirmed",
        )
        .scalar()
    )
    return money(money(bill.amount) - paid)


def _refresh_bill_status(db: Session, bill: Expense) -> None:
    paid = q2(
        db.query(func.coalesce(func.sum(SupplierPayment.amount), 0))
        .filter(
            SupplierPayment.expense_id == bill.id,
            SupplierPayment.status == "confirmed",
        )
        .scalar()
    )
    total = money(bill.amount)
    if paid <= ZERO:
        bill.payment_status = "unpaid"
    elif paid >= total:
        bill.payment_status = "paid"
    else:
        bill.payment_status = "partial"


def create_supplier_payment(
    db: Session, user: User, payload: dict[str, Any]
) -> dict[str, Any]:
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == payload["supplier_id"], Supplier.user_id == user.id)
        .one_or_none()
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    if supplier.status == "inactive":
        raise HTTPException(status_code=409, detail="This supplier is inactive.")
    amount = money(payload["amount"])
    if amount <= ZERO:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")
    bill: Expense | None = None
    if payload.get("expense_id") is not None:
        bill = (
            db.query(Expense)
            .filter(
                Expense.id == payload["expense_id"],
                Expense.user_id == user.id,
                Expense.supplier_id == supplier.id,
            )
            .one_or_none()
        )
        if bill is None:
            raise HTTPException(status_code=404, detail="Purchase bill not found for this supplier.")
        outstanding = _bill_outstanding(db, bill)
        if amount > outstanding:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Payment exceeds the outstanding amount of this bill. "
                    "Record the excess as an advance payment instead."
                ),
            )
    payment = SupplierPayment(
        user_id=user.id,
        supplier_id=supplier.id,
        expense_id=bill.id if bill is not None else None,
        amount=amount,
        method=payload["method"],
        reference=_clean(payload.get("reference")),
        paid_on=payload["paid_on"],
        status="confirmed",
        note=_clean(payload.get("note")),
        created_by_user_id=user.id,
    )
    db.add(payment)
    db.flush()
    if bill is not None:
        _refresh_bill_status(db, bill)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.supplier_payment_recorded",
        entity_type="supplier_payment",
        entity_id=payment.id,
        detail={
            "supplier_id": supplier.id,
            "expense_id": payment.expense_id,
            "amount": str(payment.amount),
            "method": payment.method,
            "advance": payment.expense_id is None,
        },
    )
    db.commit()
    db.refresh(payment)
    return supplier_payment_to_dict(payment)


def void_supplier_payment(
    db: Session, user: User, payment_id: int, reason: str
) -> dict[str, Any]:
    payment = (
        db.query(SupplierPayment)
        .filter(SupplierPayment.id == payment_id, SupplierPayment.user_id == user.id)
        .one_or_none()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Supplier payment not found.")
    if payment.status == "void":
        raise HTTPException(status_code=409, detail="This payment is already void.")
    payment.status = "void"
    payment.voided_at = utcnow()
    payment.void_reason = reason
    db.flush()
    if payment.expense_id is not None:
        bill = db.get(Expense, payment.expense_id)
        if bill is not None:
            _refresh_bill_status(db, bill)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.supplier_payment_voided",
        entity_type="supplier_payment",
        entity_id=payment.id,
        detail={"amount": str(payment.amount), "reason": reason},
    )
    db.commit()
    db.refresh(payment)
    return supplier_payment_to_dict(payment)


def supplier_ledger(
    db: Session,
    user_id: int,
    supplier_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.user_id == user_id)
        .one_or_none()
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    entries: list[dict[str, Any]] = []
    opening = money(supplier.opening_balance)
    if opening > ZERO:
        entries.append(
            {
                "date": supplier.opening_balance_date or date(1900, 1, 1),
                "type": "opening",
                "reference": "Opening balance",
                "description": "Opening payable",
                "debit": ZERO,
                "credit": opening,
            }
        )
    bills = (
        db.query(Expense)
        .filter(Expense.user_id == user_id, Expense.supplier_id == supplier_id)
        .all()
    )
    for bill in bills:
        if bill.payment_status == "void":
            continue
        entries.append(
            {
                "date": bill.incurred_on,
                "type": "bill",
                "reference": bill.bill_number or f"BILL-{bill.id}",
                "description": bill.category,
                "debit": ZERO,
                "credit": money(bill.amount),
            }
        )
    for payment in (
        db.query(SupplierPayment)
        .filter(
            SupplierPayment.user_id == user_id,
            SupplierPayment.supplier_id == supplier_id,
            SupplierPayment.status == "confirmed",
        )
        .all()
    ):
        value = money(payment.amount)
        entries.append(
            {
                "date": payment.paid_on,
                "type": "payment",
                "reference": payment.reference or f"SP-{payment.id}",
                "description": (
                    f"Supplier payment · {payment.method}"
                    + (" · advance" if payment.expense_id is None else "")
                ),
                "debit": value,
                "credit": ZERO,
            }
        )
    entries.sort(key=lambda row: row["date"])
    running = ZERO
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if date_from and entry["date"] < date_from:
            continue
        if date_to and entry["date"] > date_to:
            continue
        running += entry["credit"] - entry["debit"]
        rows.append(
            {
                "date": entry["date"],
                "type": entry["type"],
                "reference": entry["reference"],
                "description": entry["description"],
                "debit": money(entry["debit"]),
                "credit": money(entry["credit"]),
                "balance": money(running),
            }
        )
    return {
        "supplier": {
            "id": supplier.id,
            "name": supplier.name,
            "gstin": supplier.gstin,
            "phone": supplier.phone,
            "email": supplier.email,
            "payment_terms_days": supplier.payment_terms_days,
            "status": supplier.status,
        },
        "date_from": date_from,
        "date_to": date_to,
        "opening_balance": opening,
        "closing_balance": money(running),
        "rows": rows,
    }


def list_bills(
    db: Session,
    user_id: int,
    *,
    supplier_id: int | None = None,
    unmatched: bool = False,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    query = db.query(Expense).filter(Expense.user_id == user_id)
    if supplier_id is not None:
        query = query.filter(Expense.supplier_id == supplier_id)
    if unmatched:
        query = query.filter(Expense.supplier_id.is_(None))
    bills = query.order_by(Expense.incurred_on.desc(), Expense.id.desc()).all()
    rows = []
    for bill in bills:
        outstanding = _bill_outstanding(db, bill) if bill.supplier_id else money(bill.amount)
        if status and status != "all" and bill.payment_status != status:
            continue
        rows.append(
            {
                "id": bill.id,
                "supplier_id": bill.supplier_id,
                "vendor": bill.vendor,
                "category": bill.category,
                "bill_number": bill.bill_number,
                "incurred_on": bill.incurred_on,
                "due_date": bill.due_date,
                "amount": money(bill.amount),
                "outstanding": outstanding,
                "payment_status": bill.payment_status,
                "bucket": _age_bucket(bill.due_date or bill.incurred_on, date.today()),
            }
        )
    total = len(rows)
    start = max(page - 1, 0) * page_size
    return {
        "items": rows[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max((total + page_size - 1) // page_size, 1),
    }


def match_suppliers(
    db: Session, user: User, *, dry_run: bool = True
) -> dict[str, Any]:
    """Link historical expense vendors to the supplier master.

    Only an unambiguous one-to-one name match is linked. Vendor text on the
    expense is never changed. GSTIN is used when both records carry one; the
    legacy expense rows do not store a GSTIN, so name matching is the fallback.
    """
    suppliers = db.query(Supplier).filter(Supplier.user_id == user.id).all()
    by_name: dict[str, list[Supplier]] = defaultdict(list)
    by_gstin: dict[str, list[Supplier]] = defaultdict(list)
    for supplier in suppliers:
        by_name[supplier.normalized_name].append(supplier)
        if supplier.gstin:
            by_gstin[supplier.gstin].append(supplier)
    vendor_rows = (
        db.query(Expense.vendor)
        .filter(Expense.user_id == user.id, Expense.supplier_id.is_(None))
        .distinct()
        .all()
    )
    proposals: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for (vendor,) in vendor_rows:
        normalized = normalize_name(vendor)
        candidates = by_name.get(normalized, []) if normalized else []
        if len(candidates) == 1:
            proposals.append(
                {
                    "vendor": vendor,
                    "supplier_id": candidates[0].id,
                    "supplier_name": candidates[0].name,
                    "match": "normalized_name",
                }
            )
        elif len(candidates) > 1:
            ambiguous.append(
                {
                    "vendor": vendor,
                    "candidates": [
                        {"id": row.id, "name": row.name, "gstin": row.gstin}
                        for row in candidates
                    ],
                }
            )
        else:
            unmatched.append(vendor)
    linked = 0
    if not dry_run and proposals:
        for proposal in proposals:
            vendor = proposal["vendor"]
            ids = [
                row.id
                for row in db.query(Expense.id)
                .filter(
                    Expense.user_id == user.id,
                    Expense.supplier_id.is_(None),
                    func.lower(func.trim(Expense.vendor)) == vendor.strip().lower(),
                )
                .all()
            ]
            if not ids:
                continue
            db.query(Expense).filter(Expense.id.in_(ids)).update(
                {Expense.supplier_id: proposal["supplier_id"]}, synchronize_session=False
            )
            linked += len(ids)
            log_audit(
                db,
                user_id=user.id,
                actor=user.email,
                action="credit.supplier_link_created",
                entity_type="supplier",
                entity_id=proposal["supplier_id"],
                detail={
                    "vendor": vendor,
                    "expense_count": len(ids),
                    "match": proposal["match"],
                    "historical_text_unchanged": True,
                },
            )
        db.commit()
    return {
        "dry_run": dry_run,
        "proposed": proposals,
        "linked_rows": linked,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "supplier_count": len(suppliers),
        "note": (
            "Vendor text on historical expenses is never rewritten. "
            "Only one-to-one name matches are linked; ambiguous vendors stay in review."
        ),
    }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def alert_to_dict(row: CreditAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "customer_id": row.customer_id,
        "supplier_id": row.supplier_id,
        "invoice_id": row.invoice_id,
        "expense_id": row.expense_id,
        "amount": money(row.amount),
        "due_on": row.due_on,
        "status": row.status,
        "title": row.title,
        "body": row.body,
        "email_sent_at": row.email_sent_at,
        "dismissed_at": row.dismissed_at,
        "created_at": row.created_at,
    }


def _alert_candidates(
    db: Session, user_id: int, today: date, settings: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    positions = _customer_positions(db, user_id, today=today)
    for position in positions.values():
        customer = position.customer
        limit = money(customer.credit_limit)
        if limit > ZERO and position.outstanding > ZERO:
            utilisation = q2(position.outstanding * 100 / limit)
            if utilisation >= Decimal(settings["utilization_critical_pct"]):
                candidates.append(
                    {
                        "kind": "utilization_critical",
                        "customer_id": customer.id,
                        "amount": position.outstanding,
                        "title": f"{customer.name} is over the credit limit",
                        "body": (
                            f"Outstanding {position.outstanding} against a limit of {limit} "
                            f"({utilisation}% utilised)."
                        ),
                        "dedupe_key": f"utilization_critical:{customer.id}:{today:%Y-%m}",
                    }
                )
            elif utilisation >= Decimal(settings["utilization_warn_pct"]):
                candidates.append(
                    {
                        "kind": "utilization_warn",
                        "customer_id": customer.id,
                        "amount": position.outstanding,
                        "title": f"{customer.name} is nearing the credit limit",
                        "body": (
                            f"Outstanding {position.outstanding} against a limit of {limit} "
                            f"({utilisation}% utilised)."
                        ),
                        "dedupe_key": f"utilization_warn:{customer.id}:{today:%Y-%m}",
                    }
                )
        for invoice in (
            db.query(Invoice)
            .filter(
                Invoice.user_id == user_id,
                Invoice.customer_id == customer.id,
                Invoice.status != "void",
            )
            .all()
        ):
            residual = position.invoice_residuals.get(invoice.id, ZERO)
            if residual <= ZERO:
                continue
            days_overdue = (today - invoice.due_date).days
            if invoice.due_date >= today and days_overdue >= -int(settings["due_soon_days"]):
                candidates.append(
                    {
                        "kind": "invoice_due_soon",
                        "customer_id": customer.id,
                        "invoice_id": invoice.id,
                        "amount": residual,
                        "due_on": invoice.due_date,
                        "title": f"Invoice {invoice.number} is due soon",
                        "body": (
                            f"{residual} is due on {invoice.due_date.isoformat()} "
                            f"for {customer.name}."
                        ),
                        "dedupe_key": f"invoice_due_soon:{invoice.id}:{invoice.due_date.isoformat()}",
                    }
                )
            elif days_overdue > 0:
                candidates.append(
                    {
                        "kind": "invoice_overdue",
                        "customer_id": customer.id,
                        "invoice_id": invoice.id,
                        "amount": residual,
                        "due_on": invoice.due_date,
                        "title": f"Invoice {invoice.number} is overdue",
                        "body": (
                            f"{residual} is {days_overdue} day(s) overdue for {customer.name}."
                        ),
                        "dedupe_key": f"invoice_overdue:{invoice.id}:{invoice.due_date.isoformat()}",
                    }
                )
                if days_overdue >= int(settings["overdue_escalation_days"]):
                    candidates.append(
                        {
                            "kind": "overdue_escalation",
                            "customer_id": customer.id,
                            "invoice_id": invoice.id,
                            "amount": residual,
                            "due_on": invoice.due_date,
                            "title": f"Escalate collection for {invoice.number}",
                            "body": (
                                f"{residual} is {days_overdue} day(s) overdue. "
                                "Escalation threshold reached."
                            ),
                            "dedupe_key": (
                                f"overdue_escalation:{invoice.id}:"
                                f"{invoice.due_date.isoformat()}"
                            ),
                        }
                    )
    supplier_positions = _supplier_positions(db, user_id, today=today)
    for position in supplier_positions.values():
        supplier = position.supplier
        for bill in (
            db.query(Expense)
            .filter(
                Expense.user_id == user_id,
                Expense.supplier_id == supplier.id,
                Expense.payment_status != "void",
            )
            .all()
        ):
            residual = position.bill_residuals.get(bill.id, ZERO)
            if residual <= ZERO:
                continue
            due_on = bill.due_date or bill.incurred_on
            days_overdue = (today - due_on).days
            reference = bill.bill_number or f"BILL-{bill.id}"
            if due_on >= today and days_overdue >= -int(settings["supplier_due_soon_days"]):
                candidates.append(
                    {
                        "kind": "supplier_due_soon",
                        "supplier_id": supplier.id,
                        "expense_id": bill.id,
                        "amount": residual,
                        "due_on": due_on,
                        "title": f"Supplier bill {reference} is due soon",
                        "body": f"{residual} is payable to {supplier.name} on {due_on.isoformat()}.",
                        "dedupe_key": f"supplier_due_soon:{bill.id}:{due_on.isoformat()}",
                    }
                )
            elif days_overdue > 0:
                candidates.append(
                    {
                        "kind": "supplier_overdue",
                        "supplier_id": supplier.id,
                        "expense_id": bill.id,
                        "amount": residual,
                        "due_on": due_on,
                        "title": f"Supplier bill {reference} is overdue",
                        "body": f"{residual} is {days_overdue} day(s) overdue to {supplier.name}.",
                        "dedupe_key": f"supplier_overdue:{bill.id}:{due_on.isoformat()}",
                    }
                )
    since = datetime.combine(today - timedelta(days=7), datetime.min.time())
    recent_payments = (
        db.query(Payment)
        .filter(
            Payment.user_id == user_id,
            Payment.status == "confirmed",
            Payment.refund_of_payment_id.is_(None),
            Payment.invoice_id.isnot(None),
        )
        .all()
    )
    invoice_map = {
        invoice.id: invoice
        for invoice in db.query(Invoice)
        .filter(Invoice.user_id == user_id, Invoice.status != "void")
        .all()
    }
    for payment in recent_payments:
        paid_at = payment.received_at or payment.created_at
        if paid_at < since:
            continue
        invoice = invoice_map.get(payment.invoice_id)
        if invoice is None:
            continue
        candidates.append(
            {
                "kind": "payment_received",
                "customer_id": invoice.customer_id,
                "invoice_id": invoice.id,
                "amount": money(payment.amount),
                "title": f"Payment received for {invoice.number}",
                "body": f"{money(payment.amount)} received via {payment.method}.",
                "dedupe_key": f"payment_received:{payment.id}",
            }
        )
    return candidates


def evaluate_alerts(
    db: Session, user: User, *, send_emails: bool = False, today: date | None = None
) -> dict[str, Any]:
    today = today or date.today()
    settings = settings_values(db, user.id)
    if not settings["in_app_enabled"]:
        return {
            "created": 0,
            "skipped": 0,
            "emails_sent": 0,
            "items": [],
            "message": "In-app alerts are disabled in credit alert settings.",
        }
    candidates = _alert_candidates(db, user.id, today, settings)
    existing = {
        row.dedupe_key
        for row in db.query(CreditAlert.dedupe_key)
        .filter(CreditAlert.user_id == user.id)
        .all()
    }
    created: list[CreditAlert] = []
    skipped = 0
    allow_email = bool(send_emails and settings["email_enabled"])
    for candidate in candidates:
        if candidate["dedupe_key"] in existing:
            skipped += 1
            continue
        alert = CreditAlert(
            user_id=user.id,
            kind=candidate["kind"],
            customer_id=candidate.get("customer_id"),
            supplier_id=candidate.get("supplier_id"),
            invoice_id=candidate.get("invoice_id"),
            expense_id=candidate.get("expense_id"),
            amount=money(candidate.get("amount")),
            due_on=candidate.get("due_on"),
            status="open",
            dedupe_key=candidate["dedupe_key"],
            title=candidate["title"],
            body=candidate["body"],
        )
        db.add(alert)
        db.flush()
        existing.add(candidate["dedupe_key"])
        if allow_email:
            recipient = None
            if alert.customer_id:
                customer = db.get(Customer, alert.customer_id)
                recipient = customer.email if customer else None
            elif alert.supplier_id:
                supplier = db.get(Supplier, alert.supplier_id)
                recipient = supplier.email if supplier else None
            if recipient:
                try:
                    send_email(recipient=recipient, subject=alert.title, body=alert.body)
                except DeliveryError:
                    pass
                else:
                    alert.status = "sent"
                    alert.email_sent_at = utcnow()
        created.append(alert)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.alerts_evaluated",
        entity_type="credit_alert",
        entity_id=None,
        detail={
            "created": len(created),
            "skipped": skipped,
            "emails": allow_email,
        },
    )
    db.commit()
    return {
        "created": len(created),
        "skipped": skipped,
        "emails_sent": sum(1 for row in created if row.email_sent_at is not None),
        "items": [alert_to_dict(row) for row in created],
    }


def list_alerts(
    db: Session, user_id: int, *, status: str | None = None, limit: int = 100
) -> dict[str, Any]:
    query = db.query(CreditAlert).filter(CreditAlert.user_id == user_id)
    if status and status != "all":
        query = query.filter(CreditAlert.status == status)
    rows = query.order_by(CreditAlert.created_at.desc(), CreditAlert.id.desc()).limit(limit).all()
    return {"items": [alert_to_dict(row) for row in rows]}


def dismiss_alert(db: Session, user: User, alert_id: int) -> dict[str, Any]:
    alert = (
        db.query(CreditAlert)
        .filter(CreditAlert.id == alert_id, CreditAlert.user_id == user.id)
        .one_or_none()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if alert.status == "dismissed":
        return alert_to_dict(alert)
    alert.status = "dismissed"
    alert.dismissed_at = utcnow()
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="credit.alert_dismissed",
        entity_type="credit_alert",
        entity_id=alert.id,
        detail={"kind": alert.kind},
    )
    db.commit()
    db.refresh(alert)
    return alert_to_dict(alert)


# ---------------------------------------------------------------------------
# Dashboard summary and report datasets
# ---------------------------------------------------------------------------


def summary(db: Session, user_id: int, *, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    customer_positions = _customer_positions(db, user_id, today=today)
    supplier_positions = _supplier_positions(db, user_id, today=today)
    settings = settings_values(db, user_id)
    receivables = ZERO
    advances = ZERO
    available_credit = ZERO
    overdue_receivables = ZERO
    on_hold = 0
    over_limit = 0
    for position in customer_positions.values():
        if position.outstanding > ZERO:
            receivables += position.outstanding
        else:
            advances += -position.outstanding
        overdue_receivables += position.overdue
        limit = money(position.customer.credit_limit)
        if limit > ZERO:
            available_credit += max(limit - max(position.outstanding, ZERO), ZERO)
            if position.outstanding > limit:
                over_limit += 1
        if position.customer.credit_hold:
            on_hold += 1
    payables = ZERO
    overdue_payables = ZERO
    supplier_advances = ZERO
    for position in supplier_positions.values():
        if position.payable > ZERO:
            payables += position.payable
        else:
            supplier_advances += -position.payable
        overdue_payables += position.overdue
    open_alerts = (
        db.query(func.count(CreditAlert.id))
        .filter(CreditAlert.user_id == user_id, CreditAlert.status == "open")
        .scalar()
        or 0
    )
    unmatched_bills = (
        db.query(func.count(Expense.id))
        .filter(Expense.user_id == user_id, Expense.supplier_id.is_(None))
        .scalar()
        or 0
    )
    return {
        "as_of": today,
        "currency": "INR",
        "total_receivables": money(receivables),
        "total_payables": money(payables),
        "overdue_receivables": money(overdue_receivables),
        "overdue_payables": money(overdue_payables),
        "available_customer_credit": money(available_credit),
        "customer_advances": money(advances),
        "supplier_advances": money(supplier_advances),
        "customers_on_hold": on_hold,
        "customers_over_limit": over_limit,
        "customers": len(customer_positions),
        "suppliers": len(supplier_positions),
        "unmatched_bills": unmatched_bills,
        "open_alerts": open_alerts,
        "alert_settings": settings,
    }


def customer_aging(
    db: Session, user_id: int, *, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    positions = _customer_positions(db, user_id, today=today)
    rows = []
    for position in positions.values():
        if position.outstanding <= ZERO and all(value == ZERO for value in position.aging.values()):
            continue
        rows.append(
            {
                "id": position.customer.id,
                "name": position.customer.name,
                "gstin": position.customer.gstin,
                **{bucket: position.aging[bucket] for bucket in AGE_BUCKETS},
                "total": money(sum(position.aging.values(), ZERO)),
                "overdue": position.overdue,
                "balance": position.outstanding,
            }
        )
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


def supplier_aging(
    db: Session, user_id: int, *, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    positions = _supplier_positions(db, user_id, today=today)
    rows = []
    for position in positions.values():
        if position.payable <= ZERO and all(value == ZERO for value in position.aging.values()):
            continue
        rows.append(
            {
                "id": position.supplier.id,
                "name": position.supplier.name,
                "gstin": position.supplier.gstin,
                **{bucket: position.aging[bucket] for bucket in AGE_BUCKETS},
                "total": money(sum(position.aging.values(), ZERO)),
                "overdue": position.overdue,
                "balance": position.payable,
            }
        )
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


def customer_outstanding_rows(
    db: Session, user_id: int, *, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    positions = _customer_positions(db, user_id, today=today)
    settings = settings_values(db, user_id)
    rows = [
        customer_to_dict(position, settings, today)
        for position in positions.values()
        if position.outstanding > ZERO or position.overdue > ZERO
    ]
    rows.sort(key=lambda row: row["outstanding"], reverse=True)
    return rows


def supplier_outstanding_rows(
    db: Session, user_id: int, *, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    positions = _supplier_positions(db, user_id, today=today)
    rows = [
        supplier_to_dict(position)
        for position in positions.values()
        if position.payable > ZERO or position.overdue > ZERO
    ]
    rows.sort(key=lambda row: row["payable"], reverse=True)
    return rows


def overdue_rows(
    db: Session, user_id: int, *, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    rows: list[dict[str, Any]] = []
    customer_positions = _customer_positions(db, user_id, today=today)
    for position in customer_positions.values():
        for invoice in (
            db.query(Invoice)
            .filter(
                Invoice.user_id == user_id,
                Invoice.customer_id == position.customer.id,
                Invoice.status != "void",
                Invoice.due_date < today,
            )
            .all()
        ):
            residual = position.invoice_residuals.get(invoice.id, ZERO)
            if residual <= ZERO:
                continue
            rows.append(
                {
                    "party_type": "customer",
                    "party": position.customer.name,
                    "reference": invoice.number,
                    "due_on": invoice.due_date,
                    "days_overdue": (today - invoice.due_date).days,
                    "amount": residual,
                    "bucket": _age_bucket(invoice.due_date, today),
                }
            )
    supplier_positions = _supplier_positions(db, user_id, today=today)
    for position in supplier_positions.values():
        for bill in (
            db.query(Expense)
            .filter(
                Expense.user_id == user_id,
                Expense.supplier_id == position.supplier.id,
                Expense.payment_status != "void",
            )
            .all()
        ):
            residual = position.bill_residuals.get(bill.id, ZERO)
            if residual <= ZERO:
                continue
            due_on = bill.due_date or bill.incurred_on
            if due_on >= today:
                continue
            rows.append(
                {
                    "party_type": "supplier",
                    "party": position.supplier.name,
                    "reference": bill.bill_number or f"BILL-{bill.id}",
                    "due_on": due_on,
                    "days_overdue": (today - due_on).days,
                    "amount": residual,
                    "bucket": _age_bucket(due_on, today),
                }
            )
    rows.sort(key=lambda row: row["days_overdue"], reverse=True)
    return rows


def credit_utilization_rows(
    db: Session, user_id: int, *, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    positions = _customer_positions(db, user_id, today=today)
    settings = settings_values(db, user_id)
    rows = []
    for position in positions.values():
        data = customer_to_dict(position, settings, today)
        rows.append(
            {
                "id": data["id"],
                "name": data["name"],
                "gstin": data["gstin"],
                "credit_limit": data["credit_limit"],
                "outstanding": data["outstanding"],
                "available_credit": data["available_credit"],
                "utilization_pct": data["utilization_pct"],
                "risk_status": data["risk_status"],
                "credit_hold": data["credit_hold"],
                "overdue": data["overdue"],
            }
        )
    rows.sort(
        key=lambda row: (row["utilization_pct"] is None, -(row["utilization_pct"] or ZERO))
    )
    return rows
