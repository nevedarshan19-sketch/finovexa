from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import Customer, Invoice, Payment, User
from ..schemas import PaymentRecordIn
from ..services.audit import log_audit
from ..services.finance import (
    collection_status,
    invoice_to_dict,
    payment_method_label,
    q2,
)
from ..services.payments import (
    find_duplicate_payment,
    flag_overpayment_review,
    record_payment,
)

DUES_FILTERS = (
    "all",
    "unpaid",
    "partially_paid",
    "due_soon",
    "overdue",
    "paid",
    "disputed",
)


def business_timezone(profile) -> str:
    name = getattr(profile, "timezone", None) or "Asia/Kolkata"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return "Asia/Kolkata"
    return name


def business_today(profile) -> date:
    return datetime.now(ZoneInfo(business_timezone(profile))).date()


def _utc_day_start(profile, day: date) -> datetime:
    """Stored payment timestamps are naive UTC; compare against the business-day boundary."""
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(business_timezone(profile)))
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def _collectible_query(db: Session, owner_id: int, employee_id: int):
    """Invoices this employee may collect: their own or explicitly assigned."""
    return db.query(Invoice).filter(
        Invoice.user_id == owner_id,
        Invoice.status.notin_(("draft", "void")),
        or_(
            Invoice.created_by_user_id == employee_id,
            Invoice.assigned_employee_id == employee_id,
        ),
    )


def get_collectible_invoice(
    db: Session, *, owner_id: int, employee_id: int, invoice_id: int
) -> Invoice:
    invoice = (
        _collectible_query(db, owner_id, employee_id)
        .filter(Invoice.id == invoice_id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(
            status_code=404, detail="Invoice not found or not assigned to this employee."
        )
    return invoice


def _paid_map(db: Session, invoice_ids: list[int]) -> dict[int, Decimal]:
    if not invoice_ids:
        return {}
    rows = (
        db.query(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.invoice_id.in_(invoice_ids), Payment.status == "confirmed")
        .group_by(Payment.invoice_id)
        .all()
    )
    return {row[0]: q2(row[1]) for row in rows}


def _collected_range(
    db: Session, owner_id: int, employee_id: int, start: datetime
) -> list[tuple[str, str, Decimal, int]]:
    rows = (
        db.query(
            Payment.currency,
            Payment.method,
            func.coalesce(func.sum(Payment.amount), 0),
            func.count(Payment.id),
        )
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .filter(
            Invoice.user_id == owner_id,
            Invoice.status.notin_(("draft", "void")),
            or_(
                Invoice.created_by_user_id == employee_id,
                Invoice.assigned_employee_id == employee_id,
            ),
            Payment.status == "confirmed",
            func.coalesce(Payment.received_at, Payment.created_at) >= start,
        )
        .group_by(Payment.currency, Payment.method)
        .all()
    )
    return [(row[0] or "INR", row[1] or "other", q2(row[2]), int(row[3])) for row in rows]


def _mode_summary(rows: list[tuple[str, str, Decimal, int]], currency: str) -> list[dict]:
    summary: dict[str, dict] = {}
    for row_currency, method, amount, count in rows:
        if row_currency != currency:
            continue
        entry = summary.setdefault(
            method,
            {"method": method, "label": payment_method_label(method), "amount": q2(0), "count": 0},
        )
        entry["amount"] = q2(entry["amount"] + amount)
        entry["count"] += count
    return sorted(summary.values(), key=lambda row: (-row["amount"], row["label"]))


def _last_payment_at(db: Session, invoice_id: int) -> datetime | None:
    row = (
        db.query(Payment)
        .filter(Payment.invoice_id == invoice_id, Payment.status == "confirmed")
        .order_by(
            func.coalesce(Payment.received_at, Payment.created_at).desc(), Payment.id.desc()
        )
        .first()
    )
    if row is None:
        return None
    return row.received_at or row.created_at


def _empty_totals(currency: str) -> dict:
    return {
        "currency": currency,
        "outstanding_total": q2(0),
        "overdue_total": q2(0),
        "due_tomorrow_total": q2(0),
        "due_soon_total": q2(0),
        "collected_this_month": q2(0),
        "collected_today": q2(0),
        "collected_today_count": 0,
        "overpaid_total": q2(0),
        "open_invoice_count": 0,
        "overdue_count": 0,
        "due_tomorrow_count": 0,
        "due_soon_count": 0,
        "partially_paid_count": 0,
        "unpaid_count": 0,
        "paid_count": 0,
        "overpaid_count": 0,
        "disputed_count": 0,
        "collection_by_mode": [],
        "collection_rate_pct": None,
    }


def dues_payload(
    db: Session,
    *,
    owner: User,
    employee: User,
    status_filter: str = "all",
    query_text: str | None = None,
    due_soon_days: int = 7,
    limit: int = 200,
) -> dict:
    profile = owner.profile
    today = business_today(profile)
    timezone_name = business_timezone(profile)
    if status_filter not in DUES_FILTERS:
        raise HTTPException(status_code=422, detail=f"Unknown dues filter '{status_filter}'.")

    query = _collectible_query(db, owner.id, employee.id)
    if query_text and query_text.strip():
        needle = f"%{query_text.strip()}%"
        query = query.join(Customer, Invoice.customer_id == Customer.id).filter(
            or_(
                Invoice.number.ilike(needle),
                Invoice.customer_name.ilike(needle),
                Customer.name.ilike(needle),
            )
        )
    invoices = (
        query.order_by(Invoice.due_date.asc(), Invoice.id.asc()).limit(500).all()
    )
    paid_map = _paid_map(db, [invoice.id for invoice in invoices])
    month_start = _utc_day_start(profile, today.replace(day=1))
    today_start = _utc_day_start(profile, today)
    month_rows = _collected_range(db, owner.id, employee.id, month_start)
    today_rows = _collected_range(db, owner.id, employee.id, today_start)
    tomorrow = today + timedelta(days=1)

    totals: dict[str, dict] = {}
    primary_currency = (profile.currency if profile else None) or "INR"
    totals.setdefault(primary_currency, _empty_totals(primary_currency))
    items: list[dict] = []

    for invoice in invoices:
        paid = paid_map.get(invoice.id, Decimal("0.00"))
        data = invoice_to_dict(db, invoice, paid_map=paid_map, include_items=False, today=today)
        state = data["collection_status"]
        currency = invoice.currency or primary_currency
        bucket = totals.setdefault(currency, _empty_totals(currency))
        outstanding = q2(data["outstanding"])

        if invoice.total_amount > 0 and paid >= invoice.total_amount:
            bucket["paid_count"] += 1
        else:
            bucket["open_invoice_count"] += 1
            if paid <= 0:
                bucket["unpaid_count"] += 1
        if data["payment_state"] == "overpaid":
            bucket["overpaid_count"] += 1
            bucket["overpaid_total"] = q2(
                bucket["overpaid_total"] + q2(paid - invoice.total_amount)
            )
        if state == "overdue":
            bucket["overdue_count"] += 1
            bucket["overdue_total"] = q2(bucket["overdue_total"] + outstanding)
        if state == "disputed":
            bucket["disputed_count"] += 1
        if data["payment_state"] == "partially_paid" and outstanding > 0:
            bucket["partially_paid_count"] += 1
        if outstanding > 0:
            bucket["outstanding_total"] = q2(bucket["outstanding_total"] + outstanding)
            if invoice.due_date == tomorrow:
                bucket["due_tomorrow_count"] += 1
                bucket["due_tomorrow_total"] = q2(bucket["due_tomorrow_total"] + outstanding)
            if today <= invoice.due_date <= today + timedelta(days=due_soon_days):
                bucket["due_soon_count"] += 1
                bucket["due_soon_total"] = q2(bucket["due_soon_total"] + outstanding)

        if status_filter != "all" and state != status_filter:
            continue

        data["last_payment_at"] = _last_payment_at(db, invoice.id)
        data["payment_count"] = len(
            [payment for payment in invoice.payments if payment.status == "confirmed"]
        )
        items.append(data)

    for currency, bucket in totals.items():
        bucket["collected_this_month"] = q2(
            sum(
                (amount for row_currency, _, amount, _ in month_rows if row_currency == currency),
                Decimal("0.00"),
            )
        )
        bucket["collected_today"] = q2(
            sum(
                (amount for row_currency, _, amount, _ in today_rows if row_currency == currency),
                Decimal("0.00"),
            )
        )
        bucket["collected_today_count"] = sum(
            (count for row_currency, _, _, count in today_rows if row_currency == currency), 0
        )
        bucket["collection_by_mode"] = _mode_summary(month_rows, currency)
        denominator = bucket["collected_this_month"] + bucket["outstanding_total"]
        bucket["collection_rate_pct"] = (
            q2(bucket["collected_this_month"] / denominator * 100)
            if denominator > 0
            else None
        )

    currency_totals = sorted(totals.values(), key=lambda row: row["currency"])
    summary = next(
        (row for row in currency_totals if row["currency"] == primary_currency),
        currency_totals[0],
    )
    return {
        "employee": {"id": employee.id, "name": employee.full_name, "email": employee.email},
        "summary": summary,
        "currency_totals": currency_totals,
        "items": items[:limit],
        "count": min(len(items), limit),
        "filters": DUES_FILTERS,
        "status_filter": status_filter,
        "as_of": today.isoformat(),
        "timezone": timezone_name,
        "due_soon_days": due_soon_days,
        "note": (
            "Only invoices you created or the owner assigned to you are visible. "
            "Every instalment is a separate confirmed payment; previous payments are never overwritten."
        ),
    }


def payment_history_payload(db: Session, *, invoice: Invoice, today: date) -> dict:
    payments = sorted(
        (payment for payment in invoice.payments if payment.status == "confirmed"),
        key=lambda payment: (payment.received_at or payment.created_at, payment.id),
    )
    recorder_ids = {
        payment.created_by_user_id for payment in payments if payment.created_by_user_id
    }
    recorders = (
        {user.id: user for user in db.query(User).filter(User.id.in_(recorder_ids)).all()}
        if recorder_ids
        else {}
    )
    paid = sum((payment.amount for payment in payments), Decimal("0.00"))
    data = invoice_to_dict(db, invoice, include_items=False, today=today)
    data["payment_count"] = len(payments)
    data["last_payment_at"] = (
        (payments[-1].received_at or payments[-1].created_at) if payments else None
    )
    data["payment_history"] = [
        {
            "id": payment.id,
            "amount": q2(payment.amount),
            "currency": payment.currency,
            "method": payment.method,
            "method_label": payment_method_label(payment.method),
            "reference": payment.provider_ref,
            "note": payment.note,
            "status": payment.status,
            "provider": payment.provider,
            "received_at": payment.received_at,
            "created_at": payment.created_at,
            "recorded_by": (
                {
                    "id": recorders[payment.created_by_user_id].id,
                    "name": recorders[payment.created_by_user_id].full_name,
                    "role": recorders[payment.created_by_user_id].role,
                }
                if payment.created_by_user_id in recorders
                else None
            ),
        }
        for payment in payments
    ]
    data["amount_received"] = q2(paid)
    return data


def record_employee_payment(
    db: Session,
    *,
    owner: User,
    employee: User,
    invoice_id: int,
    payload: PaymentRecordIn,
) -> tuple[Payment, Invoice]:
    invoice = get_collectible_invoice(
        db, owner_id=owner.id, employee_id=employee.id, invoice_id=invoice_id
    )
    outstanding = invoice.outstanding_amount
    amount = q2(payload.amount)
    if outstanding <= 0:
        raise HTTPException(status_code=409, detail="Invoice has no outstanding balance.")
    if payload.currency and payload.currency.upper() != (invoice.currency or "INR").upper():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Payment currency {payload.currency.upper()} does not match the invoice "
                f"currency {invoice.currency}."
            ),
        )
    if payload.idempotency_key:
        already_recorded = (
            db.query(Payment)
            .filter(Payment.idempotency_key == payload.idempotency_key)
            .one_or_none()
        )
    else:
        already_recorded = None
    if already_recorded is None and payload.reference:
        duplicate = find_duplicate_payment(
            db, invoice_id=invoice.id, reference=payload.reference
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Payment reference {payload.reference} is already recorded for invoice "
                    f"{invoice.number}. Use a unique transaction reference."
                ),
            )

    note = payload.note or (
        f"Recorded by employee {employee.full_name} via "
        f"{payment_method_label(payload.method)}. "
        "Employee-recorded receipt, not provider-verified."
    )
    payment = record_payment(
        db,
        user=owner,
        invoice=invoice,
        amount=amount,
        method=payload.method,
        status="confirmed",
        provider="employee_recorded",
        provider_ref=payload.reference or f"EMP-{employee.id}",
        idempotency_key=payload.idempotency_key,
        note=note,
        received_at=payload.received_at,
        actor=employee.email,
        created_by_user_id=employee.id,
        allow_overpayment=True,
        commit=False,
    )
    excess = flag_overpayment_review(
        db,
        user_id=owner.id,
        payment=payment,
        invoice=invoice,
        actor=employee.email,
    )
    log_audit(
        db,
        user_id=owner.id,
        actor=employee.email,
        action="employee.invoice_payment_recorded",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={
            "invoice_number": invoice.number,
            "amount": str(amount),
            "currency": invoice.currency,
            "method": payload.method,
            "method_label": payment_method_label(payload.method),
            "reference": payload.reference,
            "employee_name": employee.full_name,
            "outstanding_after": str(invoice.outstanding_amount),
            "overpayment_amount": str(excess),
        },
    )
    db.commit()
    db.refresh(payment)
    db.refresh(invoice)
    return payment, invoice
