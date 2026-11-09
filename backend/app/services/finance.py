from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    BusinessProfile,
    Customer,
    Expense,
    FinancialObligation,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
)

CENT = Decimal("0.01")


def q2(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, float):
        value = Decimal(str(value))
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def supply_type_label(supply_type: str | None) -> str:
    if supply_type == "intra_state":
        return "Intra-state (CGST + SGST)"
    if supply_type == "inter_state":
        return "Inter-state (IGST)"
    return "GST classification not verified"


def pct_change(current: Decimal, previous: Decimal) -> float | None:
    # A percentage off a zero or negative base is not a meaningful comparison.
    if previous <= 0:
        return None
    return round(float((current - previous) / previous * 100), 1)


def money_text(value: Decimal | int | float | None, currency: str = "INR") -> str:
    amount = q2(value)
    sign = "-" if amount < 0 else ""
    whole, fraction = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{currency} {whole}.{fraction}"


def period_bounds(days: int, today: date | None = None) -> tuple[date, date, date, date]:
    today = today or date.today()
    days = max(1, min(days, 365))
    start = today - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return start, today, prev_start, prev_end


def confirmed_paid_by_invoice(db: Session, user_id: int) -> dict[int, Decimal]:
    rows = (
        db.query(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.user_id == user_id,
            Payment.status == "confirmed",
            Payment.invoice_id.isnot(None),
        )
        .group_by(Payment.invoice_id)
        .all()
    )
    return {invoice_id: q2(amount) for invoice_id, amount in rows}


def invoice_display_status(invoice: Invoice, paid: Decimal, today: date | None = None) -> str:
    today = today or date.today()
    if invoice.status == "void":
        return "void"
    if invoice.status == "draft":
        return "draft"
    if invoice.total_amount > 0 and paid >= invoice.total_amount:
        return "paid"
    if paid <= 0 and invoice.status == "pending_payment":
        return "pending_payment"
    if invoice.due_date < today:
        return "overdue"
    if paid > 0:
        return "partially_paid"
    return "issued"


DUE_SOON_DAYS = 7

COLLECTION_STATUSES = (
    "unpaid",
    "partially_paid",
    "due_soon",
    "overdue",
    "paid",
    "disputed",
    "draft",
    "void",
)


def collection_status(
    invoice: Invoice,
    paid: Decimal,
    today: date | None = None,
    due_soon_days: int = DUE_SOON_DAYS,
) -> str:
    """Actionable status for the dues ledger without rewriting the invoice state."""
    today = today or date.today()
    if invoice.status == "void":
        return "void"
    if invoice.status == "draft":
        return "draft"
    if invoice.total_amount > 0 and paid >= invoice.total_amount:
        return "paid"
    if invoice.disputed_at is not None:
        return "disputed"
    if invoice.due_date < today:
        return "overdue"
    if (invoice.due_date - today).days <= due_soon_days:
        return "due_soon"
    if paid > 0:
        return "partially_paid"
    return "unpaid"


def payment_state(invoice: Invoice, paid: Decimal) -> str:
    if invoice.status == "void":
        return "void"
    if invoice.total_amount > 0 and paid > invoice.total_amount:
        return "overpaid"
    if invoice.total_amount > 0 and paid >= invoice.total_amount:
        return "paid"
    if paid > 0:
        return "partially_paid"
    return "unpaid"


PAYMENT_STATUS_LABELS = {
    "paid": "PAID",
    "partially_paid": "PARTIALLY PAID",
    "unpaid": "UNPAID",
    "overpaid": "OVERPAID",
    "void": "VOID",
}


def payment_status_label(state: str | None) -> str:
    return PAYMENT_STATUS_LABELS.get(state or "", (state or "UNPAID").replace("_", " ").upper())


def overpaid_amount(invoice: Invoice, paid: Decimal) -> Decimal:
    if invoice.status == "void" or invoice.total_amount <= 0:
        return q2(0)
    return q2(max(paid - invoice.total_amount, Decimal("0.00")))


PAYMENT_METHOD_LABELS = {
    "cash": "Cash",
    "upi": "UPI",
    "bank": "Bank transfer",
    "bank_transfer": "Bank transfer",
    "card": "Card",
    "cheque": "Cheque",
    "paypal": "PayPal",
    "credit": "Credit",
    "manual": "Manual",
    "other": "Other",
}


def payment_method_label(method: str | None) -> str:
    return PAYMENT_METHOD_LABELS.get(method or "", (method or "Other").replace("_", " ").title())


def aging_bucket(due_date: date, today: date | None = None) -> str:
    today = today or date.today()
    overdue_days = (today - due_date).days
    if overdue_days <= 0:
        return "current"
    if overdue_days <= 30:
        return "1-30"
    if overdue_days <= 60:
        return "31-60"
    if overdue_days <= 90:
        return "61-90"
    return "90+"


def cash_balance(db: Session, profile: BusinessProfile, as_of: date | None = None) -> Decimal:
    """Recorded cash = owner opening balance + confirmed payments - recorded expenses - paid obligations."""
    as_of = as_of or date.today()
    if as_of < profile.opening_balance_date:
        return q2(profile.opening_cash_balance)
    as_of_end = datetime.combine(as_of, time.max)

    payments_in = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.user_id == profile.user_id,
            Payment.status == "confirmed",
            func.coalesce(Payment.received_at, Payment.created_at) <= as_of_end,
        )
        .scalar()
    )
    expenses_out = (
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.user_id == profile.user_id, Expense.incurred_on <= as_of)
        .scalar()
    )
    obligations_out = (
        db.query(func.coalesce(func.sum(FinancialObligation.amount), 0))
        .filter(
            FinancialObligation.user_id == profile.user_id,
            FinancialObligation.status == "paid",
            FinancialObligation.due_date <= as_of,
        )
        .scalar()
    )
    return q2(
        profile.opening_cash_balance + q2(payments_in) - q2(expenses_out) - q2(obligations_out)
    )


def _cogs_for_invoices(db: Session, user_id: int, invoice_ids: list[int]) -> Decimal:
    if not invoice_ids:
        return Decimal("0.00")
    rows = (
        db.query(InvoiceItem.quantity, Product.unit_cost)
        .join(Product, InvoiceItem.product_id == Product.id)
        .filter(InvoiceItem.invoice_id.in_(invoice_ids), Product.user_id == user_id)
        .all()
    )
    return q2(sum((q2(quantity * unit_cost) for quantity, unit_cost in rows), Decimal("0.00")))


def period_metrics(db: Session, user_id: int, start: date, end: date) -> dict:
    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.user_id == user_id,
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
            Invoice.status.notin_(("draft", "void")),
        )
        .all()
    )
    revenue = q2(sum((inv.total_amount for inv in invoices), Decimal("0.00")))
    cogs = _cogs_for_invoices(db, user_id, [inv.id for inv in invoices])
    gross_profit = q2(revenue - cogs)

    expenses_total = q2(
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(
            Expense.user_id == user_id,
            Expense.incurred_on >= start,
            Expense.incurred_on <= end,
        )
        .scalar()
    )
    net_profit = q2(gross_profit - expenses_total)

    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.max)
    cash_received = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.user_id == user_id,
            Payment.status == "confirmed",
            func.coalesce(Payment.received_at, Payment.created_at) >= start_dt,
            func.coalesce(Payment.received_at, Payment.created_at) <= end_dt,
        )
        .scalar()
    )
    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "expenses": expenses_total,
        "net_profit": net_profit,
        "cash_received": cash_received,
        "invoice_count": len(invoices),
        "gross_margin_pct": round(float(gross_profit / revenue * 100), 1) if revenue else None,
        "net_margin_pct": round(float(net_profit / revenue * 100), 1) if revenue else None,
    }


def outstanding_invoices(db: Session, user_id: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    paid_map = confirmed_paid_by_invoice(db, user_id)
    invoices = (
        db.query(Invoice)
        .filter(Invoice.user_id == user_id, Invoice.status.notin_(("draft", "void")))
        .order_by(Invoice.due_date.asc())
        .all()
    )
    result = []
    for inv in invoices:
        paid = paid_map.get(inv.id, Decimal("0.00"))
        outstanding = q2(max(inv.total_amount - paid, Decimal("0.00")))
        if outstanding <= 0:
            continue
        result.append(
            {
                "invoice": inv,
                "paid": paid,
                "outstanding": outstanding,
                "overdue_days": max(0, (today - inv.due_date).days),
                "bucket": aging_bucket(inv.due_date, today),
                "display_status": invoice_display_status(inv, paid, today),
            }
        )
    return result


def _customer_address_text(customer: Customer) -> str | None:
    parts = [
        customer.billing_address_line1,
        customer.billing_address_line2,
        customer.city,
        customer.state,
        customer.postal_code,
    ]
    text = ", ".join(part.strip() for part in parts if part and part.strip())
    return text or None


def invoice_to_dict(
    db: Session,
    invoice: Invoice,
    paid_map: dict[int, Decimal] | None = None,
    include_items: bool = True,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    paid = (paid_map or {}).get(invoice.id)
    if paid is None:
        paid = q2(
            db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
            .scalar()
        )
    outstanding = (
        Decimal("0.00")
        if invoice.status == "void"
        else q2(max(invoice.total_amount - paid, Decimal("0.00")))
    )
    state = payment_state(invoice, paid)
    return {
        "id": invoice.id,
        "number": invoice.number,
        "customer": {
            "id": invoice.customer.id,
            "name": invoice.customer_name or invoice.customer.name,
            "email": invoice.customer.email,
            "company": invoice.customer.company,
            "phone": invoice.customer_phone or invoice.customer.phone,
            "gstin": invoice.customer_gstin or invoice.customer.gstin,
            "billing_address": invoice.customer_address
            or _customer_address_text(invoice.customer),
            "state": invoice.customer_state or invoice.customer.state,
            "state_code": invoice.customer_state_code or invoice.customer.state_code,
        },
        "issue_date": invoice.issue_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "currency": invoice.currency,
        "status": invoice_display_status(invoice, paid, today),
        "collection_status": collection_status(invoice, paid, today),
        "payment_state": state,
        "payment_status": state,
        "payment_status_label": payment_status_label(state),
        "days_until_due": (invoice.due_date - today).days,
        "disputed": invoice.disputed_at is not None,
        "disputed_at": invoice.disputed_at,
        "reminder_paused": invoice.reminder_paused,
        "base_status": invoice.status,
        "pricing_mode": invoice.pricing_mode,
        "supply_type": invoice.supply_type,
        "supply_type_label": supply_type_label(invoice.supply_type),
        "supplier": {
            "name": invoice.supplier_name,
            "gstin": invoice.supplier_gstin,
            "address": invoice.supplier_address,
            "state": invoice.supplier_state,
            "state_code": invoice.supplier_state_code,
        },
        "place_of_supply": {
            "state": invoice.place_of_supply_state,
            "state_code": invoice.place_of_supply_state_code,
        },
        "supply_verified": invoice.supply_verified,
        "subtotal": q2(invoice.subtotal_amount),
        "discount": q2(invoice.discount_amount),
        "taxable_value": q2(invoice.taxable_amount),
        "tax": q2(invoice.tax_amount),
        "cgst": q2(invoice.cgst_amount),
        "sgst": q2(invoice.sgst_amount),
        "igst": q2(invoice.igst_amount),
        "other_charges": q2(invoice.other_charges),
        "rounding_adjustment": q2(invoice.rounding_adjustment),
        "round_to_rupee": invoice.round_to_rupee,
        "total": q2(invoice.total_amount),
        "paid": paid,
        "amount_received": paid,
        "outstanding": outstanding,
        "overpaid_amount": overpaid_amount(invoice, paid),
        "aging_days": max(0, (today - invoice.due_date).days),
        "aging_bucket": aging_bucket(invoice.due_date, today),
        "notes": invoice.notes,
        "terms": invoice.terms,
        "items": [
            {
                "id": item.id,
                "name": item.name or item.description,
                "description": item.description,
                "hsn_sac": item.hsn_sac,
                "unit": item.unit,
                "item_type": item.item_type,
                "quantity": item.quantity,
                "unit_price": q2(item.unit_price),
                "discount": q2(item.discount_amount),
                "line_total": q2(item.line_total),
                "taxable_value": q2(item.taxable_value or item.line_total),
                "gst_rate": item.gst_rate,
                "cgst_amount": q2(item.cgst_amount),
                "sgst_amount": q2(item.sgst_amount),
                "igst_amount": q2(item.igst_amount),
                "gst_amount": q2(item.gst_amount),
                "final_amount": q2(item.final_amount or item.line_total),
                "pricing_mode": item.pricing_mode,
                "product_id": item.product_id,
            }
            for item in (invoice.items if include_items else [])
        ],
        "payments": [
            {
                "id": p.id,
                "amount": q2(p.amount),
                "status": p.status,
                "method": p.method,
                "received_at": p.received_at,
                "provider": p.provider,
                "provider_ref": p.provider_ref,
                "note": p.note,
                "created_at": p.created_at,
                "created_by_user_id": p.created_by_user_id,
            }
            for p in invoice.payments
        ],
        "assigned_employee": {
            "id": invoice.assigned_employee.id,
            "name": invoice.assigned_employee.full_name,
            "email": invoice.assigned_employee.email,
        }
        if invoice.assigned_employee
        else None,
        "created_by": {
            "id": invoice.created_by.id,
            "name": invoice.created_by.full_name,
            "role": invoice.created_by.role,
        }
        if invoice.created_by
        else None,
    }


def payment_to_dict(payment: Payment) -> dict:
    recorder = payment.created_by
    source = "ledger"
    if payment.provider == "paypal":
        source = "provider_verified"
    elif payment.provider == "paypal_demo":
        source = "provider_simulated"
    elif recorder is not None and recorder.role == "employee":
        source = "employee_recorded"
    elif payment.provider in ("owner_recorded", "manual"):
        source = "owner_recorded"
    refunded = q2(
        abs(sum((refund.amount for refund in payment.refunds if refund.status == "confirmed"), Decimal("0.00")))
    )
    refundable = (
        q2(max(payment.amount - refunded, Decimal("0.00")))
        if payment.status == "confirmed" and payment.amount > 0 and payment.provider in ("paypal", "paypal_demo")
        else q2(0)
    )
    return {
        "id": payment.id,
        "invoice_id": payment.invoice_id,
        "invoice_number": payment.invoice.number if payment.invoice else None,
        "customer_name": payment.invoice.customer.name if payment.invoice else None,
        "amount": q2(payment.amount),
        "currency": payment.currency,
        "method": payment.method,
        "method_label": payment_method_label(payment.method),
        "status": payment.status,
        "provider": payment.provider,
        "provider_ref": payment.provider_ref,
        "sender_name": payment.sender_name,
        "reconciliation_status": payment.reconciliation_status,
        "reconciled_at": payment.reconciled_at,
        "refund_of_payment_id": payment.refund_of_payment_id,
        "refunded_amount": refunded,
        "refundable_amount": refundable,
        "note": payment.note,
        "received_at": payment.received_at,
        "created_at": payment.created_at,
        "source": source,
        "created_by_user_id": payment.created_by_user_id,
        "recorded_by": recorder.full_name if recorder else None,
        "recorded_by_role": recorder.role if recorder else None,
    }


def cash_trend(
    db: Session, profile: BusinessProfile, days: int, today: date | None = None
) -> list[dict]:
    today = today or date.today()
    days = max(1, min(days, 180))
    start = today - timedelta(days=days - 1)
    opening_on_start = cash_balance(db, profile, start - timedelta(days=1))

    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(today, time.max)
    payment_rows = (
        db.query(
            func.date(func.coalesce(Payment.received_at, Payment.created_at)).label("d"),
            func.sum(Payment.amount),
        )
        .filter(
            Payment.user_id == profile.user_id,
            Payment.status == "confirmed",
            func.coalesce(Payment.received_at, Payment.created_at) >= start_dt,
            func.coalesce(Payment.received_at, Payment.created_at) <= end_dt,
        )
        .group_by("d")
        .all()
    )
    expense_rows = (
        db.query(Expense.incurred_on, func.sum(Expense.amount))
        .filter(
            Expense.user_id == profile.user_id,
            Expense.incurred_on >= start,
            Expense.incurred_on <= today,
        )
        .group_by(Expense.incurred_on)
        .all()
    )
    inflow_by_day = {str(day): q2(amount) for day, amount in payment_rows}
    outflow_by_day = {str(day): q2(amount) for day, amount in expense_rows}

    balance = opening_on_start
    series = []
    cursor = start
    while cursor <= today:
        key = cursor.isoformat()
        inflow = inflow_by_day.get(key, Decimal("0.00"))
        outflow = outflow_by_day.get(key, Decimal("0.00"))
        balance = q2(balance + inflow - outflow)
        series.append(
            {
                "date": key,
                "inflow": inflow,
                "outflow": outflow,
                "balance": balance,
            }
        )
        cursor += timedelta(days=1)
    return series


def revenue_expense_series(
    db: Session, user_id: int, start: date, end: date
) -> list[dict]:
    invoice_rows = (
        db.query(Invoice.issue_date, func.sum(Invoice.total_amount))
        .filter(
            Invoice.user_id == user_id,
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
            Invoice.status.notin_(("draft", "void")),
        )
        .group_by(Invoice.issue_date)
        .all()
    )
    expense_rows = (
        db.query(Expense.incurred_on, func.sum(Expense.amount))
        .filter(
            Expense.user_id == user_id,
            Expense.incurred_on >= start,
            Expense.incurred_on <= end,
        )
        .group_by(Expense.incurred_on)
        .all()
    )
    revenue_by_day = {str(day): q2(amount) for day, amount in invoice_rows}
    expense_by_day = {str(day): q2(amount) for day, amount in expense_rows}
    series = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        series.append(
            {
                "date": key,
                "revenue": revenue_by_day.get(key, Decimal("0.00")),
                "expenses": expense_by_day.get(key, Decimal("0.00")),
            }
        )
        cursor += timedelta(days=1)
    return series


def expense_breakdown(db: Session, user_id: int, start: date, end: date) -> list[dict]:
    rows = (
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(
            Expense.user_id == user_id,
            Expense.incurred_on >= start,
            Expense.incurred_on <= end,
        )
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount).desc())
        .all()
    )
    total = sum((q2(amount) for _, amount in rows), Decimal("0.00"))
    return [
        {
            "category": category,
            "amount": q2(amount),
            "share_pct": round(float(q2(amount) / total * 100), 1) if total else 0.0,
        }
        for category, amount in rows
    ]


def product_performance(db: Session, user_id: int, start: date, end: date) -> list[dict]:
    products = db.query(Product).filter(Product.user_id == user_id).all()
    rows = (
        db.query(
            InvoiceItem.product_id,
            func.sum(InvoiceItem.quantity),
            func.sum(InvoiceItem.line_total),
        )
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .filter(
            Invoice.user_id == user_id,
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
            Invoice.status.notin_(("draft", "void")),
            InvoiceItem.product_id.isnot(None),
        )
        .group_by(InvoiceItem.product_id)
        .all()
    )
    sold = {
        product_id: (q2(quantity), q2(revenue)) for product_id, quantity, revenue in rows
    }
    result = []
    for product in products:
        quantity, revenue = sold.get(product.id, (Decimal("0"), Decimal("0.00")))
        cogs = q2(quantity * product.unit_cost)
        inventory_qty = product.inventory.quantity_on_hand if product.inventory else 0
        result.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "units_sold": quantity,
                "revenue": revenue,
                "cogs": cogs,
                "gross_profit": q2(revenue - cogs),
                "margin_pct": round(float((revenue - cogs) / revenue * 100), 1) if revenue else None,
                "inventory_qty": inventory_qty,
                "reorder_level": product.reorder_level,
                "inventory_value": q2(inventory_qty * product.unit_cost),
                "low_stock": inventory_qty <= product.reorder_level,
            }
        )
    result.sort(key=lambda item: item["revenue"], reverse=True)
    return result


def obligations_upcoming(
    db: Session, user_id: int, days: int = 30, today: date | None = None
) -> list[dict]:
    today = today or date.today()
    cutoff = today + timedelta(days=days)
    rows = (
        db.query(FinancialObligation)
        .filter(
            FinancialObligation.user_id == user_id,
            FinancialObligation.status == "scheduled",
            FinancialObligation.due_date >= today,
            FinancialObligation.due_date <= cutoff,
        )
        .order_by(FinancialObligation.due_date.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "category": row.category,
            "amount": q2(row.amount),
            "due_date": row.due_date.isoformat(),
            "days_until": (row.due_date - today).days,
            "recurring": row.recurring,
            "status": row.status,
        }
        for row in rows
    ]


def invoice_aging_summary(db: Session, user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    buckets = {
        "current": {"label": "Not yet due", "amount": Decimal("0.00"), "count": 0},
        "1-30": {"label": "1-30 days", "amount": Decimal("0.00"), "count": 0},
        "31-60": {"label": "31-60 days", "amount": Decimal("0.00"), "count": 0},
        "61-90": {"label": "61-90 days", "amount": Decimal("0.00"), "count": 0},
        "90+": {"label": "90+ days", "amount": Decimal("0.00"), "count": 0},
    }
    total = Decimal("0.00")
    overdue = Decimal("0.00")
    for row in outstanding_invoices(db, user_id, today):
        bucket = row["bucket"]
        buckets[bucket]["amount"] = q2(buckets[bucket]["amount"] + row["outstanding"])
        buckets[bucket]["count"] += 1
        total = q2(total + row["outstanding"])
        if row["overdue_days"] > 0:
            overdue = q2(overdue + row["outstanding"])
    return {
        "buckets": [
            {
                "bucket": key,
                "label": value["label"],
                "amount": value["amount"],
                "count": value["count"],
            }
            for key, value in buckets.items()
        ],
        "total_outstanding": total,
        "overdue_total": overdue,
        "current_total": q2(total - overdue),
    }


def priority_alerts(
    db: Session, profile: BusinessProfile, snapshot: dict, today: date | None = None
) -> list[dict]:
    today = today or date.today()
    alerts: list[dict] = []
    cash = snapshot["cash"]["recorded_balance"]
    reserve = q2(profile.min_cash_reserve)
    if cash < reserve:
        alerts.append(
            {
                "severity": "high",
                "title": "Cash is below your minimum reserve",
                "detail": f"Recorded cash is {money_text(cash)} against a reserve of {money_text(reserve)}.",
                "link": "/cash-flow",
            }
        )
    overdue = snapshot["receivables"]["overdue_total"]
    if overdue > 0:
        alerts.append(
            {
                "severity": "high" if snapshot["receivables"]["overdue_count"] >= 3 else "medium",
                "title": f"{snapshot['receivables']['overdue_count']} overdue invoices",
                "detail": f"{money_text(overdue)} is past due and needs collection follow-up.",
                "link": "/money-recovery",
            }
        )
    if snapshot["cash"]["projected_30d"] < reserve:
        alerts.append(
            {
                "severity": "medium",
                "title": "30-day projection dips below reserve",
                "detail": "Review the cash-flow assumptions and upcoming obligations.",
                "link": "/cash-flow",
            }
        )
    low_stock = [p for p in snapshot["inventory"] if p["low_stock"]]
    if low_stock:
        alerts.append(
            {
                "severity": "medium",
                "title": f"{len(low_stock)} products at or below reorder level",
                "detail": ", ".join(p["name"] for p in low_stock[:3]),
                "link": "/analytics",
            }
        )
    due_soon = snapshot["upcoming_obligations"][:1]
    if due_soon:
        ob = due_soon[0]
        alerts.append(
            {
                "severity": "medium" if ob["days_until"] <= 7 else "low",
                "title": f"{ob['name']} due in {ob['days_until']} days",
                "detail": f"{ob['amount']} scheduled for {ob['due_date']}.",
                "link": "/cash-flow",
            }
        )
    return alerts


def customer_to_dict(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "company": customer.company,
        "phone": customer.phone,
        "gstin": customer.gstin,
        "billing_address": _customer_address_text(customer),
        "billing_address_line1": customer.billing_address_line1,
        "billing_address_line2": customer.billing_address_line2,
        "city": customer.city,
        "state": customer.state,
        "state_code": customer.state_code,
        "postal_code": customer.postal_code,
    }
