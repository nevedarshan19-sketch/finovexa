from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Invoice, Payment, PaymentEvent, PayPalOrder, PayPalRefund, User, utcnow
from ..schemas import PayPalOrderIn, PayPalRefundIn, PayPalSettingsIn, SimulatePayPalIn
from ..security import get_current_owner, get_current_user, rate_limit
from ..services.audit import log_audit
from ..services.finance import invoice_to_dict, payment_to_dict, q2
from ..services.integrations.paypal import PayPalError, paypal_client, verify_demo_signature
from ..services.paypal import (
    OPEN_ORDER_STATUSES,
    add_payment_event,
    event_to_dict,
    find_open_order,
    hash_payload,
    mark_invoice_pending,
    order_to_dict,
    paypal_payment_query,
    paypal_payments,
    paypal_series,
    paypal_setting_snapshot,
    paypal_statistics,
    reconciliation_summary,
    record_attempt,
    record_capture,
    record_refund,
    refund_to_dict,
    refundable_amount,
    release_invoice_pending,
    save_paypal_setting,
)
from ..services.payments import refresh_invoice_status

router = APIRouter(tags=["Payments"])
public_router = APIRouter(tags=["Payments"])

REFUND_EVENTS = ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED")
FAILED_EVENTS = (
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.DECLINED",
    "PAYMENT.CAPTURE.FAILED",
)


def _owned_invoice(db: Session, user: User, invoice_id: int) -> Invoice:
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.user_id == user.id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice


def _find_order(db: Session, user: User, identifier: str) -> PayPalOrder | None:
    order = (
        db.query(PayPalOrder)
        .filter(
            PayPalOrder.user_id == user.id,
            PayPalOrder.provider_order_id == identifier,
        )
        .one_or_none()
    )
    if order is None and identifier.isdigit():
        order = (
            db.query(PayPalOrder)
            .filter(PayPalOrder.user_id == user.id, PayPalOrder.id == int(identifier))
            .one_or_none()
        )
    return order


def _invoice_id_from_custom_id(custom_id: str | None) -> int | None:
    match = re.search(r"invoice:(\d+)", str(custom_id or ""))
    return int(match.group(1)) if match else None


def _capture_id_from_links(resource: dict) -> str | None:
    for link in resource.get("links") or []:
        href = str(link.get("href") or "")
        match = re.search(r"/captures/([A-Za-z0-9_-]+)", href)
        if match:
            return match.group(1)
    return None


def _provider_block() -> dict:
    configured = paypal_client.configured
    mode = paypal_client.mode
    return {
        "name": "PayPal",
        "configured": configured,
        "enabled": paypal_client.enabled,
        "environment": paypal_client.environment,
        "mode": mode,
        "mode_label": {
            "sandbox": "SANDBOX",
            "live": "LIVE",
            "simulated": "SIMULATED",
        }[mode],
        "note": (
            "Sandbox credentials are configured. A sandbox checkout still moves no real money."
            if mode == "sandbox"
            else "Live PayPal credentials are configured. Real captures move real money."
            if mode == "live"
            else "PayPal is not configured. The simulated workflow records labelled demo payments only."
        ),
        "webhook_verification": (
            "PayPal signature verification API"
            if configured and paypal_client.webhook_id
            else "Demo HMAC signature (X-FINOVEXA-Demo-Signature). Unsigned events are rejected."
        ),
        "webhook_configured": bool(paypal_client.webhook_id),
        "client_id_hint": paypal_client.client_id_hint,
    }


def _order_payload(order: PayPalOrder, *, note: str | None = None) -> dict:
    data = order_to_dict(order)
    data["id"] = order.provider_order_id
    data["local_order_id"] = order.id
    data["note"] = note or order.note or ""
    data["demo_simulation_available"] = not paypal_client.configured
    data["trust_note"] = (
        "A client-side browser success message is not proof of payment. Cash updates only from a "
        "verified capture or webhook."
    )
    return data


@router.get("/payments/overview")
def payments_overview(
    days: int = Query(default=30, ge=7, le=365),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    status: str | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    if start or end:
        range_end = end or today
        range_start = start or (range_end - timedelta(days=days - 1))
        if range_start > range_end:
            raise HTTPException(status_code=400, detail="Start date must be before the end date.")
    else:
        range_end = today
        range_start = today - timedelta(days=days)
    start_dt = datetime.combine(range_start, time.min)
    end_dt = datetime.combine(range_end, time.max)

    stats = paypal_statistics(db, user.id, start_dt, end_dt, currency=currency)
    rows = paypal_payments(
        db,
        user.id,
        start=start_dt,
        end=end_dt,
        status=status,
        currency=currency,
    )
    invoice_rows = (
        db.query(Invoice)
        .filter(Invoice.user_id == user.id, Invoice.status.notin_(("void", "draft")))
        .order_by(Invoice.due_date.asc())
        .all()
    )
    open_invoices = [
        invoice_to_dict(db, invoice, today=today)
        for invoice in invoice_rows
        if invoice.outstanding_amount > 0
    ]
    orders = (
        db.query(PayPalOrder)
        .filter(PayPalOrder.user_id == user.id)
        .order_by(PayPalOrder.created_at.desc(), PayPalOrder.id.desc())
        .limit(40)
        .all()
    )
    refunds = (
        db.query(PayPalRefund)
        .filter(PayPalRefund.user_id == user.id)
        .order_by(PayPalRefund.created_at.desc(), PayPalRefund.id.desc())
        .limit(40)
        .all()
    )
    events = (
        db.query(PaymentEvent)
        .filter(
            PaymentEvent.provider == "paypal",
            or_(
                PaymentEvent.user_id == user.id,
                PaymentEvent.invoice_id.in_(
                    db.query(Invoice.id).filter(Invoice.user_id == user.id)
                ),
            ),
        )
        .order_by(PaymentEvent.processed_at.desc(), PaymentEvent.id.desc())
        .limit(40)
        .all()
    )
    currencies = {
        row.currency
        for row in db.query(Payment.currency)
        .filter(Payment.user_id == user.id, paypal_payment_query())
        .distinct()
        .all()
        if row.currency
    }
    currencies.add(user.profile.currency if user.profile else "INR")
    active_orders = [order for order in orders if order.status in OPEN_ORDER_STATUSES]
    provider = _provider_block()
    return {
        "provider": provider,
        "filters": {
            "days": (range_end - range_start).days + 1,
            "start": range_start.isoformat(),
            "end": range_end.isoformat(),
            "status": status,
            "currency": currency,
        },
        "currencies": sorted(currencies),
        "open_invoices": open_invoices,
        "payments": [payment_to_dict(payment) for payment in rows[:100]],
        "orders": [order_to_dict(order) for order in orders],
        "open_orders": [order_to_dict(order) for order in active_orders],
        "refunds": [refund_to_dict(refund) for refund in refunds],
        "events": [event_to_dict(event) for event in events],
        "reconciliation": reconciliation_summary(db, user, limit=25),
        "series": paypal_series(db, user.id, range_start, range_end, currency=currency),
        "statistics": stats,
        "summary": {
            "confirmed_received_period": stats["gross_received"],
            "pending_total": stats["pending_total"],
            "failed_total": stats["failed_total"],
            "refunded_total": stats["refunded_total"],
            "net_received": stats["net_received"],
            "unmatched_confirmed": stats["unmatched_confirmed"],
            "mismatch_total": stats["mismatch_total"],
            "period_days": (range_end - range_start).days + 1,
            "confirmed_note": "Only confirmed provider captures count as received cash.",
            "pending_note": "Pending or failed payments never increase recorded cash.",
        },
        "webhook_endpoint": f"{settings.API_PREFIX}/paypal/webhook",
    }


# ------------------------------------------------------------------ settings


@router.get("/paypal/settings")
def paypal_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return paypal_setting_snapshot(db)


@router.put("/paypal/settings")
def update_paypal_settings(
    payload: PayPalSettingsIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if payload.environment == "live" and payload.enabled and not payload.confirm_live:
        raise HTTPException(
            status_code=400,
            detail="Switching to live PayPal requires explicit confirmation (confirm_live=true).",
        )
    return save_paypal_setting(
        db, environment=payload.environment, enabled=payload.enabled, user=user
    )


@router.post(
    "/paypal/settings/test",
    dependencies=[Depends(rate_limit("paypal_settings_test", 10, 60))],
)
def test_paypal_connection(
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    snapshot = paypal_setting_snapshot(db)
    if not paypal_client.configured:
        return {
            "connected": False,
            "status": "simulated",
            "mode": paypal_client.mode,
            "environment": paypal_client.environment,
            "message": "No credentials are configured for this environment. Simulation remains available.",
            "webhook_configured": snapshot["webhook_configured"],
        }
    try:
        result = paypal_client.check_connection()
    except PayPalError as exc:
        log_audit(
            db,
            user_id=user.id,
            actor=user.email,
            action="paypal.connection_tested",
            entity_type="integration",
            entity_id="paypal",
            detail={"status": "error", "environment": paypal_client.environment},
        )
        db.commit()
        return {
            "connected": False,
            "status": "error",
            "mode": paypal_client.mode,
            "environment": paypal_client.environment,
            "message": str(exc),
            "webhook_configured": snapshot["webhook_configured"],
        }
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="paypal.connection_tested",
        entity_type="integration",
        entity_id="paypal",
        detail={"status": "ok", "environment": paypal_client.environment},
    )
    db.commit()
    return {
        "connected": True,
        "status": "ok",
        "mode": paypal_client.mode,
        "environment": paypal_client.environment,
        "message": "PayPal credentials accepted.",
        "webhook_configured": snapshot["webhook_configured"],
        "details": result,
    }


# ------------------------------------------------------------------ orders


@router.post(
    "/paypal/orders",
    dependencies=[Depends(rate_limit("paypal_order", 20, 60))],
)
def create_paypal_order(
    payload: PayPalOrderIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    invoice = _owned_invoice(db, user, payload.invoice_id)
    if invoice.status == "draft":
        raise HTTPException(status_code=409, detail="Issue the invoice before creating a PayPal order.")
    if invoice.status == "void":
        raise HTTPException(status_code=409, detail="Cannot create a checkout for a void invoice.")
    if invoice.outstanding_amount <= 0:
        raise HTTPException(status_code=409, detail="Invoice has no outstanding balance.")

    amount = q2(invoice.outstanding_amount)
    existing = find_open_order(db, user.id, invoice.id)
    if existing is not None:
        fresh = existing.created_at >= utcnow() - timedelta(hours=3)
        if fresh and q2(existing.amount) == amount and existing.currency == invoice.currency:
            mark_invoice_pending(db, invoice)
            db.commit()
            return _order_payload(existing, note="Reusing the existing open checkout for this invoice.")

    try:
        result = paypal_client.create_order(
            invoice_id=invoice.id,
            invoice_number=invoice.number,
            amount=amount,
            currency=invoice.currency,
            return_url=f"{settings.FRONTEND_URL}/payments?paypal=return&invoice_id={invoice.id}",
            cancel_url=f"{settings.FRONTEND_URL}/payments?paypal=cancel&invoice_id={invoice.id}",
            description=f"Invoice {invoice.number}",
            request_id=f"finovexa-order-{invoice.id}-{amount}-{invoice.currency}",
        )
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if existing is not None:
        existing.status = "SUPERSEDED"

    order = PayPalOrder(
        user_id=user.id,
        created_by_user_id=user.id,
        invoice_id=invoice.id,
        provider_order_id=result.get("id"),
        mode=result.get("mode") or paypal_client.mode,
        intent="CAPTURE",
        status=result.get("status") or "CREATED",
        amount=amount,
        currency=invoice.currency,
        approve_url=result.get("approve_url"),
        note=result.get("note"),
    )
    db.add(order)
    mark_invoice_pending(db, invoice)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="paypal.order_created",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={
            "paypal_order_id": result.get("id"),
            "local_order_id": order.id,
            "mode": result.get("mode"),
            "amount": str(amount),
            "currency": invoice.currency,
        },
    )
    db.commit()
    db.refresh(order)
    return _order_payload(order)


@router.get("/paypal/orders")
def list_paypal_orders(
    invoice_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PayPalOrder).filter(PayPalOrder.user_id == user.id)
    if invoice_id is not None:
        query = query.filter(PayPalOrder.invoice_id == invoice_id)
    if status:
        query = query.filter(PayPalOrder.status == status)
    rows = (
        query.order_by(PayPalOrder.created_at.desc(), PayPalOrder.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [order_to_dict(row) for row in rows], "count": len(rows)}


@router.get("/paypal/orders/{order_id}")
def paypal_order_status(
    order_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = _find_order(db, user, order_id)
    if order is None and not paypal_client.configured:
        return {
            "mode": "simulated",
            "order_id": order_id,
            "status": "UNAVAILABLE",
            "note": "No PayPal provider is configured, so no remote order status exists. Nothing is invented.",
        }
    if order is not None and not paypal_client.configured:
        return {
            "mode": order.mode,
            "order_id": order.provider_order_id,
            "status": order.status,
            "local": order_to_dict(order),
            "note": "Recorded locally. No remote PayPal status exists while PayPal is unconfigured.",
        }
    try:
        remote = paypal_client.get_order(order_id)
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if order is not None:
        order.status = remote.get("status") or order.status
        if remote.get("capture_id"):
            order.capture_id = remote["capture_id"]
            order.capture_status = remote.get("capture_status")
        db.commit()
        db.refresh(order)
    return {
        "mode": paypal_client.mode,
        "local": order_to_dict(order) if order is not None else None,
        **remote,
    }


@router.post("/paypal/orders/{order_id}/cancel")
def cancel_paypal_order(
    order_id: str,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    order = _find_order(db, user, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="PayPal order not found.")
    if order.status == "COMPLETED" or order.capture_id:
        raise HTTPException(
            status_code=409, detail="This order is already captured and cannot be cancelled."
        )
    order.status = "CANCELLED"
    order.note = ((order.note or "") + " · Cancelled by owner").strip(" ·")
    if order.invoice is not None:
        release_invoice_pending(db, order.invoice)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="paypal.order_cancelled",
        entity_type="paypal_order",
        entity_id=order.id,
        detail={"provider_order_id": order.provider_order_id},
    )
    db.commit()
    return {
        "message": "Checkout cancelled locally. Any PayPal-hosted approval page will expire on its own.",
        "order": order_to_dict(order),
    }


@router.post(
    "/paypal/orders/{order_id}/capture",
    dependencies=[Depends(rate_limit("paypal_capture", 20, 60))],
)
def capture_paypal_order(
    order_id: str,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if not paypal_client.configured:
        raise HTTPException(
            status_code=409,
            detail="PayPal is not configured. Use the labelled simulated payment action instead.",
        )
    order = _find_order(db, user, order_id)
    try:
        result = paypal_client.capture_order(order_id)
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    capture_id = result.get("capture_id")
    if not capture_id:
        raise HTTPException(
            status_code=409,
            detail="PayPal did not return a capture reference. No cash was recorded.",
        )
    if result.get("capture_status") != "COMPLETED" or result.get("status") not in (
        "COMPLETED",
        "APPROVED",
    ):
        if order is not None:
            order.capture_id = capture_id
            order.capture_status = result.get("capture_status")
            order.status = result.get("status") or order.status
            db.commit()
        raise HTTPException(
            status_code=409,
            detail=(
                f"PayPal capture is {result.get('status') or 'unknown'} / "
                f"{result.get('capture_status') or 'unknown'}. No cash was recorded."
            ),
        )

    existing = (
        db.query(Payment)
        .filter(Payment.provider == "paypal", Payment.provider_ref == capture_id)
        .one_or_none()
    )
    if existing is not None:
        if order is not None:
            order.capture_id = capture_id
            order.capture_status = "COMPLETED"
            order.status = "COMPLETED"
            db.commit()
        return {
            "mode": paypal_client.mode,
            "duplicate": True,
            "payment": payment_to_dict(existing),
            "invoice": invoice_to_dict(db, existing.invoice) if existing.invoice else None,
            "message": "This capture was already recorded. No duplicate payment was created.",
            "provider_reference": capture_id,
        }

    invoice_id = _invoice_id_from_custom_id(result.get("custom_id"))
    if invoice_id is None and order is not None:
        invoice_id = order.invoice_id
    invoice = (
        db.query(Invoice).filter(Invoice.id == invoice_id).one_or_none()
        if invoice_id is not None
        else None
    )
    owner = db.get(User, invoice.user_id) if invoice is not None else (
        db.get(User, order.user_id) if order is not None else None
    )
    if owner is None or owner.id != user.id:
        raise HTTPException(
            status_code=409,
            detail="Capture is not linked to one of your invoices. Payment requires manual reconciliation.",
        )
    amount = Decimal(str(result.get("amount") or "0"))
    currency = str(result.get("currency") or (invoice.currency if invoice else ""))
    mismatch_reason = None
    if invoice is not None:
        if currency and currency != invoice.currency:
            mismatch_reason = f"Currency {currency} does not match invoice {invoice.currency}."
        elif amount > invoice.outstanding_amount:
            mismatch_reason = (
                f"Captured {amount} exceeds the outstanding balance {invoice.outstanding_amount}."
            )
    if mismatch_reason:
        payment = record_capture(
            db,
            user=owner,
            invoice=None,
            capture_id=capture_id,
            amount=amount,
            currency=currency or owner.profile.currency,
            order=order,
            event_id=None,
            verification="capture_api",
            note=f"PayPal capture {capture_id} needs review: {mismatch_reason}",
            reconciliation_status="mismatch",
            commit=False,
        )
        if invoice is not None and order is not None:
            order.note = mismatch_reason
        db.commit()
        db.refresh(payment)
        return {
            "mode": paypal_client.mode,
            "duplicate": False,
            "mismatch": True,
            "payment": payment_to_dict(payment),
            "invoice": invoice_to_dict(db, invoice) if invoice is not None else None,
            "message": (
                "PayPal captured the money, but it does not match the invoice. It was recorded as "
                "unmatched for owner reconciliation; the invoice was not marked paid."
            ),
            "provider_reference": capture_id,
        }

    try:
        payment = record_capture(
            db,
            user=owner,
            invoice=invoice,
            capture_id=capture_id,
            amount=amount,
            currency=currency or owner.profile.currency,
            order=order,
            event_id=None,
            verification="capture_api",
            note=f"Verified PayPal capture {capture_id} (order {order_id}).",
            commit=False,
        )
    except HTTPException as exc:
        log_audit(
            db,
            user_id=user.id,
            actor=user.email,
            action="paypal.capture_rejected",
            entity_type="invoice",
            entity_id=invoice.id if invoice else None,
            detail={"reason": str(exc.detail), "capture_id": capture_id},
        )
        db.commit()
        raise
    db.commit()
    db.refresh(payment)
    return {
        "mode": paypal_client.mode,
        "duplicate": False,
        "payment": payment_to_dict(payment),
        "invoice": invoice_to_dict(db, invoice) if invoice else None,
        "message": "Verified PayPal capture recorded as confirmed cash.",
        "provider_reference": capture_id,
    }


@router.post(
    "/paypal/simulate",
    dependencies=[Depends(rate_limit("paypal_simulate", 20, 60))],
)
def simulate_paypal_payment(
    payload: SimulatePayPalIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if paypal_client.configured:
        raise HTTPException(
            status_code=409,
            detail="PayPal is configured. Use the sandbox checkout instead of a simulated capture.",
        )
    invoice = _owned_invoice(db, user, payload.invoice_id)
    if invoice.outstanding_amount <= 0:
        existing = (
            db.query(Payment)
            .filter(
                Payment.user_id == user.id,
                Payment.invoice_id == invoice.id,
                Payment.provider == "paypal_demo",
                Payment.status == "confirmed",
            )
            .order_by(Payment.id.desc())
            .first()
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="Invoice has no outstanding balance.")
        return {
            "mode": "simulated",
            "simulation": True,
            "payment": payment_to_dict(existing),
            "invoice": invoice_to_dict(db, invoice),
            "message": "SIMULATED payment was already recorded for this invoice. Idempotent replay; no real payment occurred.",
            "cash_effect_note": "Because this is the demo ledger, the confirmed simulated payment is included in recorded cash.",
        }
    amount = q2(payload.amount or invoice.outstanding_amount)
    payment = record_payment_simulated(db, user=user, invoice=invoice, amount=amount)
    order = (
        db.query(PayPalOrder)
        .filter(
            PayPalOrder.user_id == user.id,
            PayPalOrder.invoice_id == invoice.id,
            PayPalOrder.mode == "simulated",
            PayPalOrder.capture_id == payment.provider_ref,
        )
        .one_or_none()
    )
    if order is None:
        order = PayPalOrder(
            user_id=user.id,
            created_by_user_id=user.id,
            invoice_id=invoice.id,
            provider_order_id=None,
            mode="simulated",
            status="COMPLETED",
            amount=amount,
            currency=invoice.currency,
            capture_id=payment.provider_ref,
            capture_status="COMPLETED",
            note="Simulated PayPal capture. No PayPal API call was made.",
        )
        db.add(order)
    db.commit()
    return {
        "mode": "simulated",
        "simulation": True,
        "payment": payment_to_dict(payment),
        "invoice": invoice_to_dict(db, invoice),
        "order": order_to_dict(order),
        "message": "SIMULATED PayPal payment recorded. This is not proof of a real PayPal transaction.",
        "cash_effect_note": "Because this is the demo ledger, the confirmed simulated payment is included in recorded cash.",
    }


def record_payment_simulated(db: Session, *, user: User, invoice: Invoice, amount: Decimal):
    from ..services.payments import record_payment

    return record_payment(
        db,
        user=user,
        invoice=invoice,
        amount=amount,
        method="paypal",
        status="confirmed",
        provider="paypal_demo",
        provider_ref=f"SIM-{invoice.number}-{amount}",
        idempotency_key=f"paypal-simulated-{invoice.id}-{amount}",
        note="Simulated PayPal payment. No PayPal API was called and no real money moved.",
        actor=user.email,
    )


# ------------------------------------------------------------------ refunds


@router.post(
    "/paypal/payments/{payment_id}/refund",
    dependencies=[Depends(rate_limit("paypal_refund", 10, 60))],
)
def refund_paypal_payment(
    payment_id: int,
    payload: PayPalRefundIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id, Payment.user_id == user.id)
        .one_or_none()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.provider not in ("paypal", "paypal_demo"):
        raise HTTPException(status_code=409, detail="Only PayPal captures can be refunded here.")
    if payment.status != "confirmed" or payment.amount <= 0:
        raise HTTPException(status_code=409, detail="Only confirmed incoming captures can be refunded.")
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Explicit owner confirmation is required before a refund is requested.",
        )
    available = refundable_amount(db, payment)
    amount = q2(payload.amount or available)
    if available <= 0:
        raise HTTPException(status_code=409, detail="This capture has already been fully refunded.")
    if amount > available:
        raise HTTPException(
            status_code=409,
            detail=f"Refund amount exceeds the refundable balance ({available}).",
        )

    mode = paypal_client.mode
    external_refund_id: str | None = None
    status = "completed"
    if paypal_client.configured:
        if not payment.provider_ref:
            raise HTTPException(
                status_code=409, detail="The capture reference is missing, so PayPal cannot be refunded."
            )
        request_id = f"finovexa-refund-{payment.id}-{uuid.uuid4().hex[:16]}"
        try:
            result = paypal_client.create_refund(
                capture_id=payment.provider_ref,
                amount=amount,
                currency=payment.currency,
                request_id=request_id,
                note=payload.reason,
            )
        except PayPalError as exc:
            log_audit(
                db,
                user_id=user.id,
                actor=user.email,
                action="paypal.refund_rejected",
                entity_type="payment",
                entity_id=payment.id,
                detail={"reason": str(exc), "amount": str(amount)},
            )
            db.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        external_refund_id = result.get("refund_id")
        refund_status = str(result.get("status") or "").upper()
        if not external_refund_id:
            raise HTTPException(
                status_code=502, detail="PayPal did not return a refund reference. No refund was recorded."
            )
        if refund_status in ("FAILED", "CANCELLED", "DENIED"):
            raise HTTPException(
                status_code=502, detail=f"PayPal refund status is {refund_status}. No refund was recorded."
            )
        status = "completed" if refund_status in ("COMPLETED", "SUCCESS") else "pending"
    else:
        external_refund_id = f"SIM-REFUND-{payment.id}-{uuid.uuid4().hex[:10]}"

    refund_row = PayPalRefund(
        user_id=user.id,
        created_by_user_id=user.id,
        payment_id=payment.id,
        invoice_id=payment.invoice_id,
        capture_id=payment.provider_ref,
        provider_refund_id=external_refund_id,
        request_id=f"refund-req-{payment.id}-{uuid.uuid4().hex[:16]}",
        amount=amount,
        currency=payment.currency,
        status="completed" if status == "completed" else "pending",
        reason=payload.reason,
        mode=mode,
        note=(
            "Simulated PayPal refund. No PayPal API was called and no money moved."
            if not paypal_client.configured
            else f"PayPal refund {external_refund_id} ({status})."
        ),
    )
    db.add(refund_row)
    db.flush()

    refund_payment = None
    if status == "completed":
        refund_payment = record_refund(
            db,
            user=user,
            original=payment,
            refund_id=external_refund_id,
            amount=amount,
            currency=payment.currency,
            status="confirmed",
            reason=payload.reason,
            mode=mode,
            note=refund_row.note or "",
            commit=False,
        )
        refund_row.refund_payment_id = refund_payment.id
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="paypal.refund_requested",
        entity_type="payment",
        entity_id=payment.id,
        detail={
            "refund_id": external_refund_id,
            "amount": str(amount),
            "currency": payment.currency,
            "status": status,
            "mode": mode,
        },
    )
    db.commit()
    db.refresh(refund_row)
    if refund_payment is not None:
        db.refresh(refund_payment)
    return {
        "mode": mode,
        "simulation": not paypal_client.configured,
        "status": status,
        "refund": refund_to_dict(refund_row),
        "refund_payment": payment_to_dict(refund_payment) if refund_payment else None,
        "invoice": invoice_to_dict(db, payment.invoice) if payment.invoice else None,
        "refundable_remaining": q2(max(available - amount, Decimal("0.00"))),
        "message": (
            "SIMULATED refund recorded in the demo ledger. No PayPal API was called."
            if not paypal_client.configured
            else "PayPal accepted the refund request."
            if status == "completed"
            else "PayPal accepted the refund request as pending. Cash changes when it completes."
        ),
    }


@router.get("/paypal/refunds")
def list_paypal_refunds(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PayPalRefund).filter(PayPalRefund.user_id == user.id)
    if status:
        query = query.filter(PayPalRefund.status == status)
    rows = (
        query.order_by(PayPalRefund.created_at.desc(), PayPalRefund.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [refund_to_dict(row) for row in rows], "count": len(rows)}


@router.get("/paypal/events")
def list_paypal_events(
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned_invoices = db.query(Invoice.id).filter(Invoice.user_id == user.id)
    query = db.query(PaymentEvent).filter(
        PaymentEvent.provider == "paypal",
        or_(
            PaymentEvent.user_id == user.id,
            PaymentEvent.invoice_id.in_(owned_invoices),
        ),
    )
    if event_type:
        query = query.filter(PaymentEvent.event_type == event_type)
    rows = (
        query.order_by(PaymentEvent.processed_at.desc(), PaymentEvent.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [event_to_dict(row) for row in rows], "count": len(rows)}


@router.get("/paypal/reconciliation")
def paypal_reconciliation(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return reconciliation_summary(db, user)


# ------------------------------------------------------------------ webhook


@public_router.post("/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        event = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid webhook JSON body.")
    headers = {key.lower(): value for key, value in request.headers.items()}

    if paypal_client.configured and paypal_client.webhook_id:
        verified = paypal_client.verify_webhook(headers, event)
        verification_mode = "paypal_signature_api"
    else:
        verified = verify_demo_signature(raw, headers.get("x-finovexa-demo-signature"))
        verification_mode = "demo_hmac"

    if not verified:
        raise HTTPException(
            status_code=401,
            detail="Webhook signature verification failed. The event was not processed.",
        )

    event_id = str(event.get("id") or "").strip()
    if not event_id:
        raise HTTPException(status_code=400, detail="Webhook event id is missing.")
    existing = (
        db.query(PaymentEvent)
        .filter(PaymentEvent.provider == "paypal", PaymentEvent.event_id == event_id)
        .one_or_none()
    )
    if existing is not None:
        log_audit(
            db,
            user_id=existing.user_id,
            actor="paypal-webhook",
            action="paypal.webhook_duplicate",
            entity_type="payment_event",
            entity_id=event_id,
            detail={"event_type": existing.event_type, "outcome": existing.outcome},
        )
        db.commit()
        return {
            "received": True,
            "duplicate": True,
            "event_id": event_id,
            "outcome": existing.outcome,
            "message": "This event was already processed. No duplicate payment was recorded.",
        }

    event_type = str(event.get("event_type") or "unknown")
    resource = event.get("resource") or {}
    capture_id = str(resource.get("id") or "")
    amount = Decimal(str((resource.get("amount") or {}).get("value") or "0"))
    currency = str((resource.get("amount") or {}).get("currency_code") or "")
    custom_id = resource.get("custom_id")
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    provider_order_id = related.get("order_id") or related.get("order")
    order = None
    if provider_order_id:
        order = (
            db.query(PayPalOrder)
            .filter(PayPalOrder.provider_order_id == str(provider_order_id))
            .one_or_none()
        )

    outcome = "ignored: unsupported event type"
    payment_id = None
    invoice_id = None
    owner_id = None
    details: dict = {
        "resource_id": capture_id or None,
        "amount": str(amount) if amount else None,
        "currency": currency or None,
        "provider_order_id": provider_order_id,
    }

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        invoice_id = _invoice_id_from_custom_id(custom_id)
        if invoice_id is None and order is not None:
            invoice_id = order.invoice_id
        invoice = (
            db.query(Invoice).filter(Invoice.id == invoice_id).one_or_none()
            if invoice_id is not None
            else None
        )
        owner = db.get(User, invoice.user_id) if invoice is not None else (
            db.get(User, order.user_id) if order is not None else None
        )
        owner_id = owner.id if owner is not None else None
        if not capture_id or amount <= 0:
            outcome = "rejected: capture id or amount missing"
        elif owner is None:
            outcome = "unmapped: no business owner for this capture"
        else:
            already = (
                db.query(Payment)
                .filter(Payment.provider == "paypal", Payment.provider_ref == capture_id)
                .one_or_none()
            )
            if already is not None:
                outcome = "duplicate: capture already recorded"
                payment_id = already.id
                invoice_id = already.invoice_id
            else:
                mismatch_reason = None
                if invoice is not None:
                    if currency and currency != invoice.currency:
                        mismatch_reason = (
                            f"currency {currency} does not match invoice {invoice.currency}"
                        )
                    elif order is not None and q2(amount) != q2(order.amount):
                        mismatch_reason = (
                            f"captured {amount} does not match the checkout amount {order.amount}"
                        )
                    elif amount > invoice.outstanding_amount:
                        mismatch_reason = (
                            f"captured {amount} exceeds outstanding {invoice.outstanding_amount}"
                        )
                try:
                    payment = record_capture(
                        db,
                        user=owner,
                        invoice=None if mismatch_reason else invoice,
                        capture_id=capture_id,
                        amount=amount,
                        currency=currency or owner.profile.currency,
                        order=order,
                        event_id=event_id,
                        verification=verification_mode,
                        note=(
                            f"PayPal webhook {event_id} · needs review: {mismatch_reason}"
                            if mismatch_reason
                            else f"PayPal webhook {event_id} · verified {verification_mode}."
                        ),
                        reconciliation_status="mismatch" if mismatch_reason else None,
                        commit=False,
                    )
                    payment_id = payment.id
                    invoice_id = payment.invoice_id
                    outcome = (
                        f"mismatch: {mismatch_reason}; recorded for owner review"
                        if mismatch_reason
                        else "payment_confirmed"
                    )
                    if invoice is not None and mismatch_reason:
                        invoice_id = invoice.id
                except HTTPException as exc:
                    outcome = f"rejected: {exc.detail}"
    elif event_type == "PAYMENT.CAPTURE.PENDING":
        invoice_id = _invoice_id_from_custom_id(custom_id)
        if invoice_id is None and order is not None:
            invoice_id = order.invoice_id
        invoice = (
            db.query(Invoice).filter(Invoice.id == invoice_id).one_or_none()
            if invoice_id is not None
            else None
        )
        owner = db.get(User, invoice.user_id) if invoice is not None else (
            db.get(User, order.user_id) if order is not None else None
        )
        if order is None or owner is None or not capture_id:
            outcome = "noted: pending capture is not linked to a stored checkout; no cash changed"
        else:
            payment = record_attempt(
                db,
                user=owner,
                invoice=invoice,
                capture_id=capture_id,
                amount=amount,
                currency=currency or owner.profile.currency,
                status="pending",
                note=f"PayPal webhook {event_id}: capture pending. No cash was recorded.",
            )
            payment_id = payment.id
            owner_id = owner.id
            invoice_id = invoice.id if invoice else None
            order.status = "PENDING"
            order.capture_id = capture_id
            order.capture_status = "PENDING"
            outcome = "pending_recorded: no cash changed"
    elif event_type in FAILED_EVENTS:
        invoice_id = _invoice_id_from_custom_id(custom_id)
        if invoice_id is None and order is not None:
            invoice_id = order.invoice_id
        invoice = (
            db.query(Invoice).filter(Invoice.id == invoice_id).one_or_none()
            if invoice_id is not None
            else None
        )
        owner = db.get(User, invoice.user_id) if invoice is not None else (
            db.get(User, order.user_id) if order is not None else None
        )
        if order is None or owner is None or not capture_id:
            outcome = f"noted: {event_type.lower()} is not linked to a stored checkout; no cash changed"
        else:
            payment = record_attempt(
                db,
                user=owner,
                invoice=invoice,
                capture_id=capture_id,
                amount=amount,
                currency=currency or owner.profile.currency,
                status="failed",
                note=f"PayPal webhook {event_id}: capture {event_type.split('.')[-1].lower()}. No cash was recorded.",
            )
            payment_id = payment.id
            owner_id = owner.id
            invoice_id = invoice.id if invoice else None
            order.status = event_type.split(".")[-1]
            order.capture_id = capture_id
            order.capture_status = event_type.split(".")[-1]
            if invoice is not None:
                release_invoice_pending(db, invoice)
            outcome = "failed_recorded: no cash changed"
    elif event_type in REFUND_EVENTS:
        refund_id = str(resource.get("id") or "")
        capture_for_refund = _capture_id_from_links(resource) or capture_id
        original = (
            db.query(Payment)
            .filter(Payment.provider == "paypal", Payment.provider_ref == capture_for_refund)
            .one_or_none()
            if capture_for_refund
            else None
        )
        if not refund_id or amount <= 0:
            outcome = "rejected: refund id or amount missing"
        elif original is not None:
            owner = db.get(User, original.user_id)
            if owner is None:
                outcome = "unmapped: refund owner missing"
            elif currency and currency != original.currency:
                outcome = f"rejected: refund currency {currency} does not match capture {original.currency}"
            else:
                duplicate_refund = (
                    db.query(PayPalRefund)
                    .filter(PayPalRefund.provider_refund_id == refund_id)
                    .one_or_none()
                )
                if duplicate_refund is not None:
                    outcome = "duplicate: refund already recorded"
                    payment_id = duplicate_refund.refund_payment_id
                else:
                    refund_payment = record_refund(
                        db,
                        user=owner,
                        original=original,
                        refund_id=refund_id,
                        amount=amount,
                        currency=currency or original.currency,
                        status="confirmed",
                        reason=f"PayPal webhook {event_id}",
                        mode=paypal_client.mode,
                        note=f"PayPal refund {refund_id} confirmed by webhook {event_id}.",
                        commit=False,
                    )
                    row = PayPalRefund(
                        user_id=owner.id,
                        payment_id=original.id,
                        invoice_id=original.invoice_id,
                        refund_payment_id=refund_payment.id,
                        capture_id=capture_for_refund,
                        provider_refund_id=refund_id,
                        request_id=f"webhook-refund-{refund_id}",
                        amount=q2(amount),
                        currency=currency or original.currency,
                        status="completed",
                        reason=f"PayPal webhook {event_id}",
                        mode=paypal_client.mode,
                        note=f"Confirmed by webhook {event_id}.",
                    )
                    db.add(row)
                    owner_id = owner.id
                    payment_id = refund_payment.id
                    invoice_id = original.invoice_id
                    outcome = "refund_recorded: cash reduced"
        elif order is not None:
            owner = db.get(User, order.user_id)
            if owner is None:
                outcome = "unmapped: refund owner missing"
            else:
                deferred = (
                    db.query(PayPalRefund)
                    .filter(PayPalRefund.provider_refund_id == refund_id)
                    .one_or_none()
                )
                if deferred is None:
                    db.add(
                        PayPalRefund(
                            user_id=owner.id,
                            payment_id=None,
                            invoice_id=order.invoice_id,
                            capture_id=capture_for_refund,
                            provider_refund_id=refund_id,
                            request_id=f"webhook-refund-{refund_id}",
                            amount=q2(amount),
                            currency=currency or order.currency,
                            status="deferred",
                            reason=f"PayPal webhook {event_id}",
                            mode=paypal_client.mode,
                            note="Refund arrived before the capture. It will be applied when the capture is recorded.",
                        )
                    )
                owner_id = owner.id
                invoice_id = order.invoice_id
                outcome = "deferred: refund arrived before capture; applied after capture"
        else:
            outcome = "unmapped: refund is not linked to a recorded capture"

    add_payment_event(
        db,
        event_id=event_id,
        event_type=event_type,
        payload_hash=hash_payload(raw),
        outcome=outcome,
        verification=verification_mode,
        user_id=owner_id,
        invoice_id=invoice_id,
        payment_id=payment_id,
        details=details,
    )
    log_audit(
        db,
        user_id=owner_id,
        actor="paypal-webhook",
        action="paypal.webhook_processed",
        entity_type="payment_event",
        entity_id=event_id,
        detail={
            "event_type": event_type,
            "outcome": outcome,
            "verification": verification_mode,
            "payment_id": payment_id,
            "invoice_id": invoice_id,
        },
    )
    db.commit()
    return {
        "received": True,
        "duplicate": False,
        "event_id": event_id,
        "event_type": event_type,
        "outcome": outcome,
        "payment_id": payment_id,
        "invoice_id": invoice_id,
        "verification": verification_mode,
    }
