from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import BusinessProfile, Invoice, InvoiceReminder, Payment
from .contacts import normalize_phone
from .finance import (
    confirmed_paid_by_invoice,
    invoice_aging_summary,
    invoice_to_dict,
    outstanding_invoices,
    payment_to_dict,
    q2,
)


def priority_rows(db: Session, user_id: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = outstanding_invoices(db, user_id, today)
    if not rows:
        return []
    max_outstanding = max(row["outstanding"] for row in rows) or Decimal("1.00")
    result = []
    for row in rows:
        amount_weight = float(row["outstanding"] / max_outstanding) * 60
        age_weight = min(row["overdue_days"], 90) / 90 * 40
        score = round(amount_weight + age_weight, 1)
        reasons = []
        if row["overdue_days"] > 0:
            reasons.append(f"{row['overdue_days']} days overdue")
        else:
            reasons.append("not yet due")
        if row["outstanding"] >= Decimal("100000"):
            reasons.append("high value")
        if row["invoice"].status == "partially_paid":
            reasons.append("partially paid")
        result.append(
            {
                "invoice": row["invoice"],
                "outstanding": row["outstanding"],
                "overdue_days": row["overdue_days"],
                "bucket": row["bucket"],
                "priority_score": score,
                "reasons": reasons,
                "display_status": row["display_status"],
            }
        )
    result.sort(key=lambda item: (item["priority_score"], item["outstanding"]), reverse=True)
    return result


def recovery_summary(db: Session, profile: BusinessProfile, days: int = 30) -> dict:
    today = date.today()
    start = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(today, time.max)
    aging = invoice_aging_summary(db, profile.user_id, today)

    recovered = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.user_id == profile.user_id,
            Payment.status == "confirmed",
            Payment.invoice_id.isnot(None),
            func.coalesce(Payment.received_at, Payment.created_at) >= start_dt,
            func.coalesce(Payment.received_at, Payment.created_at) <= end_dt,
        )
        .scalar()
    )
    confirmed_total = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.user_id == profile.user_id, Payment.status == "confirmed")
        .scalar()
    )
    pending = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.user_id == profile.user_id, Payment.status == "pending")
        .scalar()
    )
    unmatched = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.user_id == profile.user_id,
            Payment.status == "confirmed",
            Payment.invoice_id.is_(None),
        )
        .scalar()
    )
    priorities = priority_rows(db, profile.user_id, today)
    return {
        "period": {"days": days, "start": start.isoformat(), "end": today.isoformat()},
        "total_outstanding": aging["total_outstanding"],
        "overdue_total": aging["overdue_total"],
        "current_total": aging["current_total"],
        "recovered_in_period": recovered,
        "confirmed_payments_total": confirmed_total,
        "awaiting_reconciliation": q2(pending + unmatched),
        "unmatched_confirmed": unmatched,
        "pending_payments": pending,
        "aging": aging["buckets"],
        "priority_invoices": [
            {
                "invoice": invoice_to_dict(db, row["invoice"], include_items=False, today=today),
                "priority_score": row["priority_score"],
                "reasons": row["reasons"],
            }
            for row in priorities[:6]
        ],
        "counts": {
            "open_invoices": sum(1 for b in aging["buckets"] for _ in range(b["count"])),
            "overdue_invoices": sum(
                b["count"] for b in aging["buckets"] if b["bucket"] not in ("current",)
            ),
        },
    }


def duplicate_checks(db: Session, user_id: int) -> dict:
    invoices = (
        db.query(Invoice)
        .filter(Invoice.user_id == user_id, Invoice.status.notin_(("draft", "void")))
        .order_by(Invoice.issue_date.asc())
        .all()
    )
    duplicate_invoices = []
    for i, first in enumerate(invoices):
        for second in invoices[i + 1 :]:
            if first.customer_id != second.customer_id:
                continue
            if first.total_amount != second.total_amount:
                continue
            if abs((second.issue_date - first.issue_date).days) > 7:
                continue
            duplicate_invoices.append(
                {
                    "invoice_a": {"id": first.id, "number": first.number, "total": q2(first.total_amount)},
                    "invoice_b": {"id": second.id, "number": second.number, "total": q2(second.total_amount)},
                    "customer_id": first.customer_id,
                    "customer_name": first.customer.name,
                    "reason": "Same customer and identical total issued within 7 days.",
                    "confidence": "possible",
                }
            )

    payments = (
        db.query(Payment).filter(Payment.user_id == user_id, Payment.status == "confirmed").all()
    )
    duplicate_payments = []
    seen_refs: dict[str, Payment] = {}
    for payment in payments:
        if payment.provider_ref:
            if payment.provider_ref in seen_refs:
                duplicate_payments.append(
                    {
                        "payment_a": payment_to_dict(seen_refs[payment.provider_ref]),
                        "payment_b": payment_to_dict(payment),
                        "reason": "The same provider reference appears on two payments.",
                        "confidence": "high",
                    }
                )
            else:
                seen_refs[payment.provider_ref] = payment
    for i, first in enumerate(payments):
        for second in payments[i + 1 :]:
            if first.id == second.id:
                continue
            if (
                first.invoice_id is not None
                and first.invoice_id == second.invoice_id
                and first.amount == second.amount
                and first.received_at
                and second.received_at
                and abs((first.received_at - second.received_at).days) <= 1
            ):
                duplicate_payments.append(
                    {
                        "payment_a": payment_to_dict(first),
                        "payment_b": payment_to_dict(second),
                        "reason": "Two confirmed payments match the same invoice, amount and day.",
                        "confidence": "possible",
                    }
                )
    return {
        "duplicate_invoices": duplicate_invoices,
        "duplicate_payments": duplicate_payments,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


def unmatched_payments(db: Session, user_id: int) -> list[dict]:
    payments = (
        db.query(Payment)
        .filter(
            Payment.user_id == user_id,
            Payment.invoice_id.is_(None),
            Payment.status.in_(("confirmed", "pending")),
        )
        .order_by(Payment.created_at.desc())
        .all()
    )
    paid_map = confirmed_paid_by_invoice(db, user_id)
    open_rows = outstanding_invoices(db, user_id)
    suggestions = []
    for payment in payments:
        matches = []
        for row in open_rows:
            inv = row["invoice"]
            difference = abs(row["outstanding"] - payment.amount)
            exact = difference == 0
            close = difference <= max(Decimal("100.00"), payment.amount * Decimal("0.02"))
            name_hint = payment.sender_name and payment.sender_name.lower() in inv.customer.name.lower()
            if exact or close or name_hint:
                matches.append(
                    {
                        "invoice": invoice_to_dict(db, inv, paid_map, include_items=False),
                        "match_reason": "Exact amount"
                        if exact
                        else "Amount within 2%"
                        if close
                        else "Sender name resembles customer",
                        "confidence": "high" if exact else "medium",
                    }
                )
        matches.sort(key=lambda m: 0 if m["confidence"] == "high" else 1)
        suggestions.append({**payment_to_dict(payment), "suggested_matches": matches[:3]})
    return suggestions


def reminder_draft(
    invoice: Invoice,
    profile: BusinessProfile,
    tone: str = "professional",
    paid_amount: Decimal | None = None,
) -> dict:
    paid = paid_amount or Decimal("0.00")
    outstanding = q2(max(invoice.total_amount - paid, Decimal("0.00")))
    overdue_days = max(0, (date.today() - invoice.due_date).days)
    greeting = f"Hi {invoice.customer.name.split()[0]}," if invoice.customer.name else "Hello,"
    if tone == "friendly":
        opener = (
            f"I hope you're doing well. This is a friendly reminder about invoice {invoice.number} "
            f"for {profile.currency} {outstanding:,.2f}, which was due on {invoice.due_date:%d %b %Y}."
        )
        closer = "If payment is already on its way, please ignore this note. Otherwise, I'd be grateful if you could share an expected date."
    elif tone == "firm":
        opener = (
            f"Invoice {invoice.number} for {profile.currency} {outstanding:,.2f} remains unpaid. "
            f"It became due on {invoice.due_date:%d %b %Y}, {overdue_days} day(s) ago, and now requires immediate attention."
        )
        closer = "Please confirm the payment date within two business days so we can avoid further follow-up."
    else:
        opener = (
            f"I'm writing regarding invoice {invoice.number} for {profile.currency} {outstanding:,.2f}, "
            f"issued on {invoice.issue_date:%d %b %Y} and due on {invoice.due_date:%d %b %Y}."
        )
        closer = "Could you please confirm when payment will be arranged? Let me know if you need a copy of the invoice or any supporting details."
    subject_age = f" ({overdue_days} days overdue)" if overdue_days else ""
    subject = f"Payment reminder: Invoice {invoice.number}{subject_age}"
    body = (
        f"{greeting}\n\n{opener}\n\n"
        f"Outstanding balance: {profile.currency} {outstanding:,.2f}\n"
        f"Due date: {invoice.due_date:%d %b %Y}\n\n"
        f"{closer}\n\n"
        f"Thank you,\n{profile.business_name}"
    )
    sms_body = (
        f"{profile.business_name}: Invoice {invoice.number} for {profile.currency} "
        f"{outstanding:,.2f} is due {invoice.due_date:%d %b %Y}. "
        "Please share a payment date. Reply STOP to opt out."
    )[:320]
    return {
        "subject": subject,
        "body": body,
        "sms_body": sms_body,
        "tone": tone,
        "generated_by": "template",
        "mode": "deterministic",
        "facts": {
            "invoice_id": invoice.id,
            "invoice_number": invoice.number,
            "outstanding": outstanding,
            "due_date": invoice.due_date.isoformat(),
            "overdue_days": overdue_days,
        },
        "note": "Drafted from your ledger. Nothing is sent until you approve it.",
    }


REMINDER_STAGES: tuple[dict[str, str], ...] = (
    {
        "key": "due_in_7",
        "label": "Due within 7 days",
        "description": "Heads-up before the deadline, while the invoice is still on time.",
        "tone": "friendly",
        "severity": "low",
    },
    {
        "key": "due_today",
        "label": "Due today",
        "description": "The deadline is today. Confirm the payment is scheduled.",
        "tone": "professional",
        "severity": "medium",
    },
    {
        "key": "overdue_1_7",
        "label": "1-7 days late",
        "description": "First chase after the deadline passed.",
        "tone": "professional",
        "severity": "high",
    },
    {
        "key": "overdue_8_14",
        "label": "8-14 days late",
        "description": "Second chase. Ask for a firm payment date.",
        "tone": "firm",
        "severity": "high",
    },
    {
        "key": "overdue_15_plus",
        "label": "15+ days late",
        "description": "Final reminder before the owner escalates the account.",
        "tone": "firm",
        "severity": "critical",
    },
)
REMINDER_STAGE_KEYS: tuple[str, ...] = tuple(stage["key"] for stage in REMINDER_STAGES)
REMINDER_STAGE_MAP = {stage["key"]: stage for stage in REMINDER_STAGES}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
DISPATCHED_REMINDER_STATUSES = ("sent", "simulated_sent")


def reminder_stage_for_due_date(
    due_date: date, today: date | None = None, window_days: int = 7
) -> dict | None:
    """Map a deadline to a reminder stage. Returns None when the deadline is too far away."""
    today = today or date.today()
    days_until_due = (due_date - today).days
    if days_until_due > window_days:
        return None
    if days_until_due >= 1:
        key = "due_in_7"
    elif days_until_due == 0:
        key = "due_today"
    elif days_until_due >= -7:
        key = "overdue_1_7"
    elif days_until_due >= -14:
        key = "overdue_8_14"
    else:
        key = "overdue_15_plus"
    return {**REMINDER_STAGE_MAP[key], "days_until_due": days_until_due}


def _share_text(
    invoice: Invoice, profile: BusinessProfile, outstanding: Decimal, days_until_due: int
) -> str:
    first_name = invoice.customer.name.split()[0] if invoice.customer.name else ""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    if days_until_due > 0:
        timing = f"is due in {days_until_due} day(s) on {invoice.due_date:%d %b %Y}"
    elif days_until_due == 0:
        timing = f"is due today, {invoice.due_date:%d %b %Y}"
    else:
        timing = (
            f"was due on {invoice.due_date:%d %b %Y} and is "
            f"{abs(days_until_due)} day(s) overdue"
        )
    lines = [
        greeting,
        "",
        f"This is a payment reminder from {profile.business_name}: invoice {invoice.number} for "
        f"{profile.currency} {outstanding:,.2f} {timing}.",
        "Please share a payment date, or reply if you need the invoice sent again.",
    ]
    if profile.business_phone:
        lines.append(f"Questions? Call {profile.business_phone}.")
    lines.extend(["", "Thank you,", profile.business_name])
    return "\n".join(lines)


def _share_links(invoice: Invoice, subject: str, text: str) -> dict:
    email = (invoice.customer.email or "").strip()
    raw_phone = invoice.customer_phone or invoice.customer.phone
    try:
        phone = normalize_phone(raw_phone)
    except Exception:  # invalid numbers must not break the schedule
        phone = None
    encoded_text = quote(text, safe="")
    whatsapp = f"https://wa.me/{phone.lstrip('+')}?text={encoded_text}" if phone else None
    mailto = f"mailto:{email}?subject={quote(subject, safe='')}&body={encoded_text}" if email else None
    sms_uri = f"sms:{phone}?&body={encoded_text}" if phone else None
    return {"whatsapp_url": whatsapp, "mailto_url": mailto, "sms_uri": sms_uri}


def reminder_schedule(
    db: Session, profile: BusinessProfile, window_days: int = 7, today: date | None = None
) -> dict:
    """Deadline-driven reminder queue. Nothing is dispatched from here."""
    today = today or date.today()
    rows = outstanding_invoices(db, profile.user_id, today)
    invoice_ids = [row["invoice"].id for row in rows]
    reminders: dict[int, list[InvoiceReminder]] = defaultdict(list)
    if invoice_ids:
        for reminder in (
            db.query(InvoiceReminder)
            .filter(InvoiceReminder.invoice_id.in_(invoice_ids))
            .order_by(InvoiceReminder.created_at.asc())
            .all()
        ):
            reminders[reminder.invoice_id].append(reminder)

    items: list[dict] = []
    not_due_count = 0
    not_due_amount = Decimal("0.00")
    for row in rows:
        invoice = row["invoice"]
        stage = reminder_stage_for_due_date(invoice.due_date, today, window_days)
        if stage is None:
            not_due_count += 1
            not_due_amount += row["outstanding"]
            continue
        history = reminders.get(invoice.id, [])
        stage_hits = [
            reminder
            for reminder in history
            if reminder.stage == stage["key"]
            and reminder.status in DISPATCHED_REMINDER_STATUSES
        ]
        dispatched = [
            reminder
            for reminder in history
            if reminder.status in DISPATCHED_REMINDER_STATUSES
        ]
        last_reminder_at = max(
            (reminder.created_at for reminder in dispatched), default=None
        )
        outstanding = q2(row["outstanding"])
        subject = f"Payment reminder: Invoice {invoice.number}"
        text = _share_text(invoice, profile, outstanding, stage["days_until_due"])
        email = (invoice.customer.email or "").strip() or None
        phone = invoice.customer_phone or invoice.customer.phone or None
        items.append(
            {
                "invoice": invoice_to_dict(db, invoice, include_items=False, today=today),
                "outstanding": outstanding,
                "due_date": invoice.due_date.isoformat(),
                "days_until_due": stage["days_until_due"],
                "stage": stage["key"],
                "stage_label": stage["label"],
                "stage_description": stage["description"],
                "tone": stage["tone"],
                "severity": stage["severity"],
                "reminded": bool(stage_hits),
                "reminded_channels": sorted({reminder.channel for reminder in stage_hits}),
                "reminder_count": len(dispatched),
                "last_reminder_at": last_reminder_at,
                "contact": {
                    "email": email,
                    "phone": phone,
                    "email_ready": settings.email_ready,
                    "sms_ready": settings.sms_ready,
                },
                "share": {
                    "subject": subject,
                    "text": text,
                    **_share_links(invoice, subject, text),
                },
            }
        )

    items.sort(
        key=lambda item: (
            SEVERITY_RANK.get(item["severity"], 9),
            item["days_until_due"],
            -float(item["outstanding"]),
        )
    )

    by_stage = []
    for stage in REMINDER_STAGES:
        stage_items = [item for item in items if item["stage"] == stage["key"]]
        by_stage.append(
            {
                **stage,
                "count": len(stage_items),
                "amount": q2(sum((item["outstanding"] for item in stage_items), Decimal("0.00"))),
                "reminded_count": sum(1 for item in stage_items if item["reminded"]),
                "unreminded_count": sum(1 for item in stage_items if not item["reminded"]),
            }
        )

    actionable_amount = q2(
        sum((item["outstanding"] for item in items), Decimal("0.00"))
    )
    return {
        "as_of": today.isoformat(),
        "window_days": window_days,
        "currency": profile.currency,
        "summary": {
            "actionable_count": len(items),
            "actionable_amount": actionable_amount,
            "reminded_count": sum(1 for item in items if item["reminded"]),
            "unreminded_count": sum(1 for item in items if not item["reminded"]),
            "not_due_count": not_due_count,
            "not_due_amount": q2(not_due_amount),
            "by_stage": by_stage,
        },
        "items": items,
        "note": (
            "Stages are derived from the invoice due date only. Nothing is sent automatically: "
            "email or SMS dispatch needs owner approval, and share links open your own mail, "
            "SMS or WhatsApp app with the message pre-filled."
        ),
    }
