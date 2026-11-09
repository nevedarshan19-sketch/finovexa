from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Invoice, Payment, ReconciliationRecord, User, utcnow
from .audit import log_audit
from .finance import payment_method_label, q2


def refresh_invoice_status(db: Session, invoice: Invoice) -> None:
    if invoice.status in ("draft", "void"):
        return
    paid = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
        .scalar()
    )
    if invoice.total_amount > 0 and paid >= invoice.total_amount:
        invoice.status = "paid"
    elif paid > 0:
        invoice.status = "partially_paid"
    elif invoice.status == "pending_payment":
        # Keep the checkout state until the order is captured, denied or cancelled.
        return
    else:
        invoice.status = "issued"


def record_payment(
    db: Session,
    *,
    user: User,
    invoice: Invoice | None,
    amount: Decimal,
    method: str,
    status: str = "confirmed",
    provider: str | None = "manual",
    provider_ref: str | None = None,
    idempotency_key: str | None = None,
    note: str | None = None,
    sender_name: str | None = None,
    received_at: datetime | None = None,
    actor: str | None = None,
    created_by_user_id: int | None = None,
    currency: str | None = None,
    reconciliation_status: str | None = None,
    allow_overpayment: bool = False,
    commit: bool = True,
) -> Payment:
    amount = q2(amount)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")
    if idempotency_key:
        existing = (
            db.query(Payment).filter(Payment.idempotency_key == idempotency_key).one_or_none()
        )
        if existing is not None:
            return existing
    if invoice is not None:
        if invoice.user_id != user.id:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        if invoice.status == "draft":
            raise HTTPException(
                status_code=409,
                detail="Issue the invoice before recording a payment against it.",
            )
        if invoice.status == "void":
            raise HTTPException(status_code=409, detail="Cannot record a payment against a void invoice.")
        if (
            status == "confirmed"
            and amount > invoice.outstanding_amount
            and not allow_overpayment
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Payment {amount} exceeds the outstanding balance "
                    f"{invoice.outstanding_amount} for invoice {invoice.number}."
                ),
            )
    resolved_currency = currency or (user.profile.currency if user.profile else "INR")
    if invoice is not None:
        resolved_currency = currency or invoice.currency
    if reconciliation_status is None:
        if invoice is not None:
            reconciliation_status = "matched"
        elif status == "confirmed":
            reconciliation_status = "unmatched"
        else:
            reconciliation_status = "not_applicable"
    payment = Payment(
        user_id=user.id,
        created_by_user_id=created_by_user_id,
        invoice_id=invoice.id if invoice else None,
        amount=amount,
        currency=resolved_currency,
        method=method,
        status=status,
        provider=provider,
        provider_ref=provider_ref,
        idempotency_key=idempotency_key,
        reconciliation_status=reconciliation_status,
        reconciled_at=utcnow() if reconciliation_status == "matched" else None,
        note=note,
        sender_name=sender_name,
        received_at=received_at or (utcnow() if status == "confirmed" else None),
    )
    db.add(payment)
    db.flush()
    if invoice is not None:
        refresh_invoice_status(db, invoice)
    log_audit(
        db,
        user_id=user.id,
        actor=actor or user.email,
        action=f"payment.{status}",
        entity_type="payment",
        entity_id=payment.id,
        detail={
            "invoice_id": invoice.id if invoice else None,
            "amount": str(amount),
            "method": method,
            "provider": provider or "manual",
            "created_by_user_id": created_by_user_id,
            "note": (note or "")[:200],
        },
    )
    if commit:
        db.commit()
        db.refresh(payment)
    return payment


def match_payment(
    db: Session, user: User, payment: Payment, invoice: Invoice, confirm: bool
) -> Payment:
    if payment.user_id != user.id or invoice.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment or invoice not found.")
    if payment.status != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="Only confirmed payments can be reconciled. This payment needs provider confirmation first.",
        )
    if not confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")
    if invoice.status == "draft":
        raise HTTPException(status_code=409, detail="Issue the invoice before matching payments to it.")
    if invoice.status == "void":
        raise HTTPException(status_code=409, detail="Cannot match a payment to a void invoice.")
    if payment.amount > invoice.outstanding_amount:
        raise HTTPException(
            status_code=409,
            detail=f"Payment amount exceeds the invoice outstanding balance ({invoice.outstanding_amount}).",
        )
    if payment.invoice_id is not None and payment.invoice_id != invoice.id:
        raise HTTPException(status_code=409, detail="Payment is already matched to another invoice.")
    previous_invoice_id = payment.invoice_id
    payment.invoice_id = invoice.id
    payment.reconciliation_status = "matched"
    payment.reconciled_at = utcnow()
    payment.note = ((payment.note or "") + " · Reconciled by owner").strip(" ·")
    db.add(
        ReconciliationRecord(
            user_id=user.id,
            payment_id=payment.id,
            invoice_id=invoice.id,
            status="matched",
            reason=f"Owner confirmed a match to invoice {invoice.number}.",
            amount_delta=q2(invoice.outstanding_amount - payment.amount),
            actor=user.email,
        )
    )
    refresh_invoice_status(db, invoice)
    if previous_invoice_id and previous_invoice_id != invoice.id:
        previous = db.get(Invoice, previous_invoice_id)
        if previous is not None:
            refresh_invoice_status(db, previous)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="payment.reconciled",
        entity_type="payment",
        entity_id=payment.id,
        detail={
            "invoice_id": invoice.id,
            "invoice_number": invoice.number,
            "amount": str(payment.amount),
        },
    )
    db.commit()
    db.refresh(payment)
    return payment


def confirmed_paid_total(db: Session, invoice: Invoice) -> Decimal:
    return q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
        .scalar()
    )


def flag_overpayment_review(
    db: Session,
    *,
    user_id: int,
    payment: Payment,
    invoice: Invoice | None,
    actor: str,
) -> Decimal:
    """Record the excess as customer credit pending an owner refund/credit decision."""
    if invoice is None or invoice.total_amount <= 0:
        return q2(0)
    paid = confirmed_paid_total(db, invoice)
    excess = q2(max(paid - invoice.total_amount, Decimal("0.00")))
    if excess <= 0:
        return q2(0)
    reason = (
        f"Overpayment of {excess} {invoice.currency} on invoice {invoice.number}. "
        "Held as customer credit until the owner approves a refund or credit note."
    )
    record = (
        db.query(ReconciliationRecord)
        .filter(
            ReconciliationRecord.payment_id == payment.id,
            ReconciliationRecord.status == "overpayment_review",
        )
        .one_or_none()
    )
    if record is None:
        db.add(
            ReconciliationRecord(
                user_id=user_id,
                payment_id=payment.id,
                invoice_id=invoice.id,
                status="overpayment_review",
                reason=reason,
                amount_delta=excess,
                actor=actor,
            )
        )
    else:
        record.amount_delta = excess
        record.reason = reason
    return excess


def find_duplicate_payment(
    db: Session, *, invoice_id: int, reference: str | None
) -> Payment | None:
    ref = (reference or "").strip()
    if not ref:
        return None
    return (
        db.query(Payment)
        .filter(
            Payment.invoice_id == invoice_id,
            Payment.status == "confirmed",
            func.lower(Payment.provider_ref) == ref.lower(),
        )
        .order_by(Payment.id.desc())
        .first()
    )


def update_payment(
    db: Session,
    user: User,
    payment: Payment,
    *,
    amount: Decimal | None = None,
    method: str | None = None,
    provider_ref: str | None = None,
    note: str | None = None,
    received_at: datetime | None = None,
) -> Payment:
    if payment.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="Only confirmed payments can be edited.",
        )
    if payment.provider in ("paypal", "paypal_demo"):
        raise HTTPException(
            status_code=409,
            detail="Provider-verified payments cannot be edited. Use the PayPal refund workflow.",
        )
    before = {
        "amount": str(q2(payment.amount)),
        "method": payment.method,
        "reference": payment.provider_ref,
        "received_at": payment.received_at.isoformat() if payment.received_at else None,
        "note": payment.note,
    }
    if amount is not None:
        amount = q2(amount)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")
        payment.amount = amount
    if method is not None:
        payment.method = method
    if provider_ref is not None:
        payment.provider_ref = provider_ref.strip() or None
    if note is not None:
        payment.note = note.strip() or None
    if received_at is not None:
        payment.received_at = received_at
    if payment.invoice is not None:
        refresh_invoice_status(db, payment.invoice)
        flag_overpayment_review(
            db,
            user_id=user.id,
            payment=payment,
            invoice=payment.invoice,
            actor=user.email,
        )
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="payment.edited",
        entity_type="payment",
        entity_id=payment.id,
        detail={
            "invoice_id": payment.invoice_id,
            "invoice_number": payment.invoice.number if payment.invoice else None,
            "before": before,
            "after": {
                "amount": str(q2(payment.amount)),
                "method": payment.method,
                "reference": payment.provider_ref,
                "received_at": payment.received_at.isoformat() if payment.received_at else None,
                "note": payment.note,
            },
        },
    )
    db.commit()
    db.refresh(payment)
    return payment


def reverse_payment(
    db: Session, user: User, payment: Payment, *, reason: str | None = None
) -> Payment:
    if payment.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="Only confirmed payments can be reversed.",
        )
    if payment.provider in ("paypal", "paypal_demo"):
        raise HTTPException(
            status_code=409,
            detail="Provider-verified payments must be refunded through PayPal, not reversed locally.",
        )
    invoice = payment.invoice
    payment.status = "reversed"
    payment.reconciliation_status = "reversed"
    payment.note = ((payment.note or "") + f" · Reversed by owner: {reason or 'recorded in error'}").strip(
        " ·"
    )
    db.add(
        ReconciliationRecord(
            user_id=user.id,
            payment_id=payment.id,
            invoice_id=payment.invoice_id,
            status="reversed",
            reason=reason or "Owner reversed a recorded payment.",
            amount_delta=q2(-payment.amount),
            actor=user.email,
        )
    )
    if invoice is not None:
        refresh_invoice_status(db, invoice)
    log_audit(        db,
        user_id=user.id,
        actor=user.email,
        action="payment.reversed",
        entity_type="payment",
        entity_id=payment.id,
        detail={
            "invoice_id": payment.invoice_id,
            "invoice_number": invoice.number if invoice else None,
            "amount": str(q2(payment.amount)),
            "method": payment.method,
            "method_label": payment_method_label(payment.method),
            "reason": reason,
            "outstanding_after": str(invoice.outstanding_amount) if invoice else None,
        },
    )
    db.commit()
    db.refresh(payment)
    return payment
