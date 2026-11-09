from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AuditEvent,
    Invoice,
    Payment,
    PaymentEvent,
    PayPalOrder,
    PayPalRefund,
    ProviderSetting,
    ReconciliationRecord,
    User,
    utcnow,
)
from .audit import log_audit
from .finance import (
    confirmed_paid_by_invoice,
    invoice_to_dict,
    payment_to_dict,
    q2,
)
from .integrations.paypal import mask_secret_hint, paypal_client
from .payments import refresh_invoice_status, record_payment

PAYPAL_PROVIDER = "paypal"
OPEN_ORDER_STATUSES = ("CREATED", "APPROVED", "PAYER_ACTION_REQUIRED", "SAVED")


# ------------------------------------------------------------------ provider settings


def load_paypal_runtime(db: Session) -> ProviderSetting:
    row = (
        db.query(ProviderSetting)
        .filter(ProviderSetting.provider == PAYPAL_PROVIDER)
        .one_or_none()
    )
    if row is None:
        row = ProviderSetting(
            provider=PAYPAL_PROVIDER,
            environment=settings.paypal_environment,
            enabled=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    paypal_client.configure_runtime(row.environment, row.enabled)
    return row


def paypal_setting_snapshot(db: Session) -> dict:
    row = load_paypal_runtime(db)
    environments = []
    for environment in ("sandbox", "live"):
        creds = settings.paypal_credentials(environment)
        environments.append(
            {
                "environment": environment,
                "label": "Sandbox" if environment == "sandbox" else "Production",
                "credentials_present": settings.paypal_environment_configured(environment),
                "client_id_hint": mask_secret_hint(creds["client_id"]),
                "webhook_configured": bool(creds["webhook_id"]),
                "base_url": creds["base_url"] if settings.paypal_environment_configured(environment) else None,
            }
        )
    return {
        "provider": "paypal",
        "environment": row.environment,
        "enabled": row.enabled,
        "configured": paypal_client.configured,
        "mode": paypal_client.mode,
        "mode_label": {
            "sandbox": "SANDBOX",
            "live": "LIVE",
            "simulated": "SIMULATED",
        }[paypal_client.mode],
        "active_client_id_hint": paypal_client.client_id_hint,
        "active_webhook_id_hint": paypal_client.webhook_id_hint,
        "webhook_configured": bool(paypal_client.webhook_id),
        "webhook_signature_verification": bool(paypal_client.configured and paypal_client.webhook_id),
        "webhook_endpoint": f"{settings.API_PREFIX}/paypal/webhook",
        "environments": environments,
        "updated_at": row.updated_at,
        "updated_by": row.updated_by.full_name if row.updated_by else None,
        "security_note": (
            "Client secrets, access tokens and the full webhook id stay in backend environment "
            "variables. This response only contains booleans and masked hints."
        ),
    }


def save_paypal_setting(
    db: Session, *, environment: str, enabled: bool, user: User
) -> dict:
    if environment not in ("sandbox", "live"):
        raise HTTPException(status_code=400, detail="Choose the sandbox or live environment.")
    if environment == "live" and enabled and not settings.paypal_environment_configured("live"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Live PayPal credentials are not present in the backend environment. "
                "Set PAYPAL_LIVE_CLIENT_ID, PAYPAL_LIVE_CLIENT_SECRET and PAYPAL_LIVE_WEBHOOK_ID first."
            ),
        )
    row = (
        db.query(ProviderSetting)
        .filter(ProviderSetting.provider == PAYPAL_PROVIDER)
        .one_or_none()
    )
    if row is None:
        row = ProviderSetting(provider=PAYPAL_PROVIDER)
        db.add(row)
    previous = row.environment
    row.environment = environment
    row.enabled = enabled
    row.updated_by_user_id = user.id
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="paypal.settings_updated",
        entity_type="integration",
        entity_id="paypal",
        detail={"previous_environment": previous, "environment": environment, "enabled": enabled},
    )
    db.commit()
    db.refresh(row)
    paypal_client.configure_runtime(row.environment, row.enabled)
    return paypal_setting_snapshot(db)


# ------------------------------------------------------------------ event log


def add_payment_event(
    db: Session,
    *,
    event_id: str,
    event_type: str,
    payload_hash: str,
    outcome: str,
    verification: str,
    user_id: int | None = None,
    invoice_id: int | None = None,
    payment_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> PaymentEvent:
    row = PaymentEvent(
        provider=PAYPAL_PROVIDER,
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        outcome=outcome,
        verification=verification,
        user_id=user_id,
        invoice_id=invoice_id,
        payment_id=payment_id,
        details=details or {},
        processed_at=utcnow(),
    )
    db.add(row)
    return row


def event_to_dict(row: PaymentEvent) -> dict:
    return {
        "id": row.id,
        "event_id": row.event_id,
        "event_type": row.event_type,
        "outcome": row.outcome,
        "verification": row.verification,
        "user_id": row.user_id,
        "invoice_id": row.invoice_id,
        "payment_id": row.payment_id,
        "details": row.details,
        "processed_at": row.processed_at,
    }


# ------------------------------------------------------------------ order records


def order_to_dict(order: PayPalOrder) -> dict:
    invoice = order.invoice
    return {
        "id": order.id,
        "provider_order_id": order.provider_order_id,
        "invoice_id": order.invoice_id,
        "invoice_number": invoice.number if invoice else None,
        "customer_name": invoice.customer.name if invoice else None,
        "mode": order.mode,
        "intent": order.intent,
        "status": order.status,
        "amount": q2(order.amount),
        "currency": order.currency,
        "approve_url": order.approve_url,
        "capture_id": order.capture_id,
        "capture_status": order.capture_status,
        "payer_email": order.payer_email,
        "note": order.note,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def refund_to_dict(refund: PayPalRefund) -> dict:
    return {
        "id": refund.id,
        "payment_id": refund.payment_id,
        "refund_payment_id": refund.refund_payment_id,
        "invoice_id": refund.invoice_id,
        "invoice_number": refund.invoice.number if refund.invoice else None,
        "capture_id": refund.capture_id,
        "provider_refund_id": refund.provider_refund_id,
        "request_id": refund.request_id,
        "amount": q2(refund.amount),
        "currency": refund.currency,
        "status": refund.status,
        "reason": refund.reason,
        "mode": refund.mode,
        "note": refund.note,
        "created_at": refund.created_at,
        "updated_at": refund.updated_at,
    }


def find_open_order(db: Session, user_id: int, invoice_id: int) -> PayPalOrder | None:
    return (
        db.query(PayPalOrder)
        .filter(
            PayPalOrder.user_id == user_id,
            PayPalOrder.invoice_id == invoice_id,
            PayPalOrder.status.in_(OPEN_ORDER_STATUSES),
        )
        .order_by(PayPalOrder.id.desc())
        .first()
    )


def mark_invoice_pending(db: Session, invoice: Invoice) -> None:
    if invoice.status in ("draft", "void", "paid", "partially_paid"):
        return
    invoice.status = "pending_payment"


def release_invoice_pending(db: Session, invoice: Invoice) -> None:
    if invoice.status != "pending_payment":
        return
    # Clear the checkout hold first: refresh_invoice_status keeps pending_payment
    # whenever nothing has been paid yet, so it cannot be used to release a hold.
    invoice.status = "issued"
    refresh_invoice_status(db, invoice)


# ------------------------------------------------------------------ capture / attempts


def record_capture(
    db: Session,
    *,
    user: User,
    invoice: Invoice | None,
    capture_id: str,
    amount: Decimal,
    currency: str,
    order: PayPalOrder | None,
    event_id: str | None,
    verification: str,
    note: str,
    reconciliation_status: str | None = None,
    commit: bool = True,
) -> Payment:
    payment = record_payment(
        db,
        user=user,
        invoice=invoice,
        amount=amount,
        method="paypal",
        status="confirmed",
        provider=PAYPAL_PROVIDER,
        provider_ref=capture_id,
        idempotency_key=f"paypal-capture-{capture_id}",
        note=note,
        currency=currency,
        reconciliation_status=reconciliation_status,
        actor="paypal-webhook" if event_id else user.email,
        commit=False,
    )
    if order is not None:
        order.capture_id = capture_id
        order.capture_status = "COMPLETED"
        order.status = "COMPLETED"
        if invoice is not None:
            order.invoice_id = invoice.id
    if payment.invoice_id is None:
        db.add(
            ReconciliationRecord(
                user_id=user.id,
                payment_id=payment.id,
                invoice_id=None,
                status=payment.reconciliation_status,
                reason=(
                    "Verified PayPal capture amount or currency does not match the invoice; "
                    "owner review required."
                    if payment.reconciliation_status == "mismatch"
                    else "Verified PayPal capture has no invoice reference; owner review required."
                ),
                amount_delta=amount,
                actor="paypal-webhook" if event_id else user.email,
            )
        )
    else:
        db.add(
            ReconciliationRecord(
                user_id=user.id,
                payment_id=payment.id,
                invoice_id=invoice.id,
                status="matched",
                reason=f"Verified PayPal capture matched to invoice {invoice.number}.",
                amount_delta=q2(invoice.total_amount - payment.amount),
                actor="paypal-webhook" if event_id else user.email,
            )
        )
    apply_deferred_refunds(db, user=user, capture_payment=payment, capture_id=capture_id)
    if commit:
        db.commit()
        db.refresh(payment)
    return payment


def record_attempt(
    db: Session,
    *,
    user: User,
    invoice: Invoice | None,
    capture_id: str,
    amount: Decimal,
    currency: str,
    status: str,
    note: str,
) -> Payment:
    """Record a pending/failed provider attempt. Attempts never change recorded cash."""
    existing = (
        db.query(Payment)
        .filter(Payment.provider == PAYPAL_PROVIDER, Payment.provider_ref == capture_id)
        .first()
    )
    if existing is not None:
        if existing.status == "confirmed":
            return existing
        existing.status = status
        existing.note = note
        db.flush()
        return existing
    return record_payment(
        db,
        user=user,
        invoice=invoice,
        amount=amount,
        method="paypal",
        status=status,
        provider=PAYPAL_PROVIDER,
        provider_ref=capture_id,
        idempotency_key=f"paypal-{status}-{capture_id}",
        note=note,
        currency=currency,
        reconciliation_status="not_applicable",
        actor="paypal-webhook",
        commit=False,
    )


# ------------------------------------------------------------------ refunds


def refunded_amount(db: Session, payment: Payment) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.refund_of_payment_id == payment.id,
            Payment.status == "confirmed",
        )
        .scalar()
    )
    return q2(abs(Decimal(str(total or 0))))


def refundable_amount(db: Session, payment: Payment) -> Decimal:
    if payment.status != "confirmed" or payment.amount <= 0:
        return q2(0)
    if payment.provider not in ("paypal", "paypal_demo"):
        return q2(0)
    return q2(max(payment.amount - refunded_amount(db, payment), Decimal("0.00")))


def record_refund(
    db: Session,
    *,
    user: User,
    original: Payment,
    refund_id: str,
    amount: Decimal,
    currency: str,
    status: str,
    reason: str,
    mode: str,
    note: str,
    commit: bool = True,
) -> Payment:
    amount = q2(abs(amount))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be greater than zero.")
    idempotency_key = f"paypal-refund-{refund_id}"
    existing = (
        db.query(Payment).filter(Payment.idempotency_key == idempotency_key).one_or_none()
    )
    if existing is not None:
        return existing
    invoice = original.invoice
    payment = Payment(
        user_id=user.id,
        invoice_id=original.invoice_id,
        refund_of_payment_id=original.id,
        amount=-amount,
        currency=currency or original.currency,
        method="paypal",
        status=status,
        provider="paypal_refund",
        provider_ref=refund_id,
        idempotency_key=idempotency_key,
        reconciliation_status="matched" if original.invoice_id else "unmatched",
        reconciled_at=utcnow() if original.invoice_id else None,
        note=note,
        received_at=utcnow(),
    )
    db.add(payment)
    db.flush()
    if invoice is not None:
        refresh_invoice_status(db, invoice)
    db.add(
        ReconciliationRecord(
            user_id=user.id,
            payment_id=payment.id,
            invoice_id=original.invoice_id,
            status="refund",
            reason=reason,
            amount_delta=-amount,
            actor=user.email,
        )
    )
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="paypal.refund_recorded",
        entity_type="payment",
        entity_id=payment.id,
        detail={
            "original_payment_id": original.id,
            "refund_id": refund_id,
            "amount": str(amount),
            "currency": currency,
            "mode": mode,
        },
    )
    if commit:
        db.commit()
        db.refresh(payment)
    return payment


def apply_deferred_refunds(
    db: Session, *, user: User, capture_payment: Payment, capture_id: str
) -> None:
    rows = (
        db.query(PayPalRefund)
        .filter(
            PayPalRefund.user_id == user.id,
            PayPalRefund.capture_id == capture_id,
            PayPalRefund.status == "deferred",
        )
        .all()
    )
    for row in rows:
        refund_payment = record_refund(
            db,
            user=user,
            original=capture_payment,
            refund_id=row.provider_refund_id or row.request_id,
            amount=row.amount,
            currency=row.currency,
            status="confirmed",
            reason=row.reason or "Deferred PayPal refund applied after capture.",
            mode=row.mode,
            note=row.note or "Deferred PayPal refund applied after the capture arrived.",
            commit=False,
        )
        row.status = "completed"
        row.payment_id = capture_payment.id
        row.refund_payment_id = refund_payment.id


# ------------------------------------------------------------------ statistics / reconciliation


def _paypal_filter():
    return or_(Payment.method == "paypal", Payment.provider.like("paypal%"))


def paypal_payment_query():
    """Public filter expression so routers can reuse the exact provider scope."""
    return _paypal_filter()


def paypal_payments(
    db: Session,
    user_id: int,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    status: str | None = None,
    currency: str | None = None,
) -> list[Payment]:
    query = db.query(Payment).filter(Payment.user_id == user_id, _paypal_filter())
    if start is not None:
        query = query.filter(func.coalesce(Payment.received_at, Payment.created_at) >= start)
    if end is not None:
        query = query.filter(func.coalesce(Payment.received_at, Payment.created_at) <= end)
    if status:
        query = query.filter(Payment.status == status)
    if currency:
        query = query.filter(Payment.currency == currency)
    return query.order_by(func.coalesce(Payment.received_at, Payment.created_at).desc()).all()


def paypal_statistics(
    db: Session,
    user_id: int,
    start: datetime,
    end: datetime,
    *,
    currency: str | None = None,
) -> dict:
    rows = paypal_payments(db, user_id, start=start, end=end, currency=currency)
    credits = [row for row in rows if row.status == "confirmed" and row.amount > 0]
    refunds = [row for row in rows if row.status == "confirmed" and row.amount < 0]
    pending = [row for row in rows if row.status == "pending"]
    failed = [row for row in rows if row.status == "failed"]
    gross_received = q2(sum((row.amount for row in credits), Decimal("0.00")))
    refunded = q2(abs(sum((row.amount for row in refunds), Decimal("0.00"))))
    verified = q2(
        sum((row.amount for row in credits if row.provider == "paypal"), Decimal("0.00"))
    )
    simulated = q2(
        sum((row.amount for row in credits if row.provider == "paypal_demo"), Decimal("0.00"))
    )
    unmatched_amount = q2(
        sum(
            (
                row.amount
                for row in credits
                if row.invoice_id is None and row.reconciliation_status != "mismatch"
            ),
            Decimal("0.00"),
        )
    )
    mismatch_amount = q2(
        sum((row.amount for row in credits if row.reconciliation_status == "mismatch"), Decimal("0.00"))
    )
    return {
        "currency": currency or (rows[0].currency if rows else None),
        "gross_received": gross_received,
        "verified_received": verified,
        "simulated_received": simulated,
        "refunded_total": refunded,
        "net_received": q2(gross_received - refunded),
        "pending_total": q2(sum((row.amount for row in pending), Decimal("0.00"))),
        "failed_total": q2(sum((row.amount for row in failed), Decimal("0.00"))),
        "unmatched_confirmed": unmatched_amount,
        "mismatch_total": mismatch_amount,
        "successful_count": len(credits),
        "pending_count": len(pending),
        "failed_count": len(failed),
        "refund_count": len(refunds),
        "transaction_count": len(rows),
        "note": (
            "Only confirmed captures count as received cash. Pending and failed attempts never "
            "increase cash, and refunds reduce it."
        ),
    }


def paypal_series(
    db: Session,
    user_id: int,
    start: date,
    end: date,
    *,
    currency: str | None = None,
) -> list[dict]:
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.max)
    rows = paypal_payments(db, user_id, start=start_dt, end=end_dt, currency=currency)
    buckets: dict[str, dict[str, Any]] = {}
    cursor = start
    while cursor <= end:
        buckets[cursor.isoformat()] = {
            "date": cursor.isoformat(),
            "received": Decimal("0.00"),
            "refunded": Decimal("0.00"),
            "net": Decimal("0.00"),
            "count": 0,
        }
        cursor += timedelta(days=1)
    for row in rows:
        if row.status != "confirmed":
            continue
        stamp = row.received_at or row.created_at
        key = stamp.date().isoformat()
        bucket = buckets.get(key)
        if bucket is None:
            continue
        bucket["count"] += 1
        if row.amount >= 0:
            bucket["received"] = q2(bucket["received"] + row.amount)
        else:
            bucket["refunded"] = q2(bucket["refunded"] + abs(row.amount))
        bucket["net"] = q2(bucket["net"] + row.amount)
    return list(buckets.values())


def _suggestions_for(db: Session, payment: Payment, paid_map: dict[int, Decimal]) -> list[dict]:
    currency = payment.currency
    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.user_id == payment.user_id,
            Invoice.currency == currency,
            Invoice.status.notin_(("draft", "void", "paid")),
        )
        .order_by(Invoice.due_date.asc())
        .limit(60)
        .all()
    )
    suggestions = []
    for invoice in invoices:
        paid = paid_map.get(invoice.id, Decimal("0.00"))
        outstanding = q2(invoice.total_amount - paid)
        if outstanding <= 0:
            continue
        confidence = None
        reason = None
        if q2(outstanding) == q2(payment.amount):
            confidence = "high"
            reason = "Exact amount match to the invoice outstanding balance."
        elif payment.sender_name and (
            payment.sender_name.lower() in invoice.customer.name.lower()
            or (
                invoice.customer.company
                and payment.sender_name.lower() in invoice.customer.company.lower()
            )
        ):
            confidence = "medium"
            reason = "Sender name matches the invoice customer."
        if reason:
            suggestions.append(
                {
                    "invoice": invoice_to_dict(
                        db, invoice, paid_map, include_items=False
                    ),
                    "match_reason": reason,
                    "confidence": confidence,
                }
            )
        if len(suggestions) >= 3:
            break
    return suggestions


def reconciliation_summary(db: Session, user: User, limit: int = 50) -> dict:
    paid_map = confirmed_paid_by_invoice(db, user.id)
    rows = (
        db.query(Payment)
        .filter(
            Payment.user_id == user.id,
            _paypal_filter(),
            Payment.status == "confirmed",
            Payment.amount > 0,
        )
        .order_by(func.coalesce(Payment.received_at, Payment.created_at).desc())
        .limit(200)
        .all()
    )
    unmatched, mismatched = [], []
    for payment in rows:
        if payment.reconciliation_status == "mismatch":
            mismatched.append(
                {
                    **payment_to_dict(payment),
                    "suggested_matches": _suggestions_for(db, payment, paid_map),
                }
            )
        elif payment.invoice_id is None:
            unmatched.append(
                {
                    **payment_to_dict(payment),
                    "suggested_matches": _suggestions_for(db, payment, paid_map),
                }
            )
    duplicate_events = (
        db.query(func.count(PaymentEvent.id))
        .filter(
            PaymentEvent.provider == PAYPAL_PROVIDER,
            PaymentEvent.user_id == user.id,
            PaymentEvent.outcome.like("duplicate%"),
        )
        .scalar()
    ) + (
        db.query(func.count(AuditEvent.id))
        .filter(
            AuditEvent.user_id == user.id,
            AuditEvent.action == "paypal.webhook_duplicate",
        )
        .scalar()
    )
    history = (
        db.query(ReconciliationRecord)
        .filter(ReconciliationRecord.user_id == user.id)
        .order_by(ReconciliationRecord.created_at.desc(), ReconciliationRecord.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "matched_count": sum(1 for row in rows if row.reconciliation_status == "matched"),
        "matched_amount": q2(
            sum(
                (row.amount for row in rows if row.reconciliation_status == "matched"),
                Decimal("0.00"),
            )
        ),
        "unmatched_count": len(unmatched),
        "unmatched_amount": q2(
            sum((Decimal(str(row["amount"])) for row in unmatched), Decimal("0.00"))
        ),
        "mismatch_count": len(mismatched),
        "mismatch_amount": q2(
            sum((Decimal(str(row["amount"])) for row in mismatched), Decimal("0.00"))
        ),
        "duplicate_events": int(duplicate_events or 0),
        "unmatched": unmatched[:limit],
        "mismatches": mismatched[:limit],
        "history": [
            {
                "id": row.id,
                "payment_id": row.payment_id,
                "invoice_id": row.invoice_id,
                "status": row.status,
                "reason": row.reason,
                "amount_delta": q2(row.amount_delta),
                "actor": row.actor,
                "created_at": row.created_at,
            }
            for row in history
        ],
        "note": (
            "Matching is deterministic: exact amount and currency first, then customer/sender name. "
            "Unmatched or mismatched captures never change an invoice until an owner confirms a match."
        ),
    }


def hash_payload(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
