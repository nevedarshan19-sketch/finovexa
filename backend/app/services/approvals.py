from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ApprovalRequest,
    BrokerOrder,
    BusinessProfile,
    Invoice,
    InvoiceReminder,
    MarketInstrument,
    MarketQuote,
    User,
    utcnow,
)
from .audit import log_audit
from .contacts import normalize_phone
from .delivery import DeliveryError, send_email, send_sms
from .finance import q2
from .forecasting import build_forecast
from .integrations.upstox import UpstoxError, upstox_client

ALLOWED_ACTIONS = {"reminder.send", "investment.order", "cashflow.intervention"}
EXPIRY_MINUTES = {"reminder.send": 24 * 60, "investment.order": 30, "cashflow.intervention": 72 * 60}
LIVE_CANCELLABLE_STATUSES = {
    "live_submitted",
    "live_open",
    "live_partially_filled",
}


def live_order_block_reason(user: User, quote: MarketQuote | None) -> str | None:
    if not settings.UPSTOX_LIVE_TRADING_ENABLED:
        return (
            "Live trading is disabled on this deployment. Set UPSTOX_LIVE_TRADING_ENABLED=true "
            "and configure an Upstox access token before requesting a live order."
        )
    if not settings.upstox_configured:
        return "Live trading needs a configured Upstox access token."
    if user.profile is None or user.profile.currency != "INR":
        return "Live Upstox orders require a business profile whose currency is INR."
    if quote is None or quote.data_mode != "live":
        return (
            "Live orders require a live Upstox quote. The current quote is demo or stale; "
            "refresh market data and try again."
        )
    return None


def live_instrument_key(instrument: MarketInstrument, payload: dict[str, Any]) -> str | None:
    if instrument.asset_class == "option":
        option = payload.get("option") or {}
        return option.get("instrument_key")
    return instrument.external_key


def map_upstox_status(raw: str | None) -> str:
    normalized = " ".join(str(raw or "").lower().replace("_", " ").split())
    if normalized.startswith("complete") or normalized in {"filled", "traded"}:
        return "live_filled"
    if "rejected" in normalized:
        return "live_rejected"
    if "cancel" in normalized:
        return "live_cancelled"
    if "partially" in normalized:
        return "live_partially_filled"
    if normalized in {
        "open",
        "pending",
        "trigger pending",
        "validation pending",
        "modified",
        "received",
        "put order req received",
    }:
        return "live_open"
    return "live_submitted"


def apply_upstox_order_status(order: BrokerOrder, details: dict) -> None:
    raw = str(details.get("status") or "").strip()
    message = (
        details.get("status_message")
        or details.get("status_message_raw")
        or details.get("message")
    )
    if message:
        order.broker_status_message = " ".join(str(message).split())[:500]
    order.last_synced_at = utcnow()
    if not raw:
        return
    order.broker_status = raw[:40]
    order.status = map_upstox_status(raw)
    if order.status == "live_rejected":
        order.rejection_reason = order.broker_status_message or "Upstox rejected the order."


def _find_upstox_order_by_tag(tag: str) -> dict | None:
    try:
        rows = upstox_client.get_order_book()
    except UpstoxError:
        return None
    return next((row for row in rows if row.get("tag") == tag), None)



def payload_hash(action_type: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"action_type": action_type, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_to_dict(approval: ApprovalRequest) -> dict:
    now = utcnow()
    effective_status = approval.status
    if approval.status == "pending" and approval.expires_at < now:
        effective_status = "expired"
    return {
        "id": approval.id,
        "action_type": approval.action_type,
        "title": approval.title,
        "reason": approval.reason,
        "evidence": approval.evidence,
        "financial_impact": q2(approval.financial_impact)
        if approval.financial_impact is not None
        else None,
        "risk_level": approval.risk_level,
        "payload": approval.payload,
        "payload_hash": approval.payload_hash,
        "status": effective_status,
        "expires_at": approval.expires_at,
        "decided_at": approval.decided_at,
        "executed_at": approval.executed_at,
        "result": approval.result,
        "created_at": approval.created_at,
        "can_decide": effective_status == "pending",
    }


def expire_stale_approvals(db: Session, user_id: int) -> int:
    stale = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.user_id == user_id,
            ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at < utcnow(),
        )
        .all()
    )
    for approval in stale:
        approval.status = "expired"
        log_audit(
            db,
            user_id=user_id,
            actor="system",
            action="approval.expired",
            entity_type="approval",
            entity_id=approval.id,
            detail={"action_type": approval.action_type, "title": approval.title},
        )
    if stale:
        db.commit()
    return len(stale)


def create_approval(
    db: Session,
    user: User,
    *,
    action_type: str,
    title: str,
    reason: str,
    payload: dict[str, Any],
    evidence: list[dict] | None = None,
    financial_impact: Decimal | None = None,
    risk_level: str = "medium",
) -> ApprovalRequest:
    if action_type not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail="Unsupported approval action.")
    expires_at = utcnow() + timedelta(minutes=EXPIRY_MINUTES[action_type])
    approval = ApprovalRequest(
        user_id=user.id,
        action_type=action_type,
        title=title,
        reason=reason,
        evidence=evidence or [],
        financial_impact=financial_impact,
        risk_level=risk_level,
        payload=payload,
        payload_hash=payload_hash(action_type, payload),
        expires_at=expires_at,
    )
    db.add(approval)
    db.flush()
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="approval.created",
        entity_type="approval",
        entity_id=approval.id,
        detail={"action_type": action_type, "title": title, "financial_impact": str(financial_impact or 0)},
    )
    db.commit()
    db.refresh(approval)
    return approval


def _execute_reminder(db: Session, user: User, approval: ApprovalRequest) -> dict:
    payload = approval.payload
    if approval.payload_hash != payload_hash(approval.action_type, approval.payload):
        raise HTTPException(
            status_code=409, detail="Action details no longer match the approved request."
        )
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == payload.get("invoice_id"), Invoice.user_id == user.id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(status_code=409, detail="Invoice is no longer available.")
    if invoice.outstanding_amount <= 0:
        raise HTTPException(status_code=409, detail="Invoice has no outstanding balance.")

    channel = str(payload.get("channel") or "email")
    recipient = str(payload.get("recipient") or "").strip()
    if channel == "email":
        if recipient.lower() != invoice.customer.email.lower():
            raise HTTPException(
                status_code=409, detail="The reminder recipient no longer matches the customer email."
            )
    elif channel == "sms":
        on_file = normalize_phone(invoice.customer_phone or invoice.customer.phone)
        if not on_file or normalize_phone(recipient) != on_file:
            raise HTTPException(
                status_code=409, detail="The reminder recipient no longer matches the customer mobile."
            )
    else:
        raise HTTPException(status_code=409, detail="Unsupported reminder channel.")

    body = str(payload["body"])
    stage = str(payload.get("stage") or "") or None
    try:
        if channel == "email":
            outcome = send_email(
                recipient=recipient,
                subject=str(payload.get("subject") or f"Payment reminder · {invoice.number}"),
                body=body,
            )
        else:
            outcome = send_sms(recipient=recipient, body=body)
    except DeliveryError as exc:
        reminder = InvoiceReminder(
            invoice_id=invoice.id,
            approval_id=approval.id,
            channel=channel,
            stage=stage,
            body=body,
            status="failed",
            delivery_note=str(exc)[:240],
        )
        db.add(reminder)
        db.flush()
        log_audit(
            db,
            user_id=user.id,
            actor=user.email,
            action="reminder.failed",
            entity_type="invoice",
            entity_id=invoice.id,
            detail={"approval_id": approval.id, "channel": channel, "stage": stage},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    reminder = InvoiceReminder(
        invoice_id=invoice.id,
        approval_id=approval.id,
        channel=channel,
        stage=stage,
        body=body,
        status=outcome.status,
        delivery_note=outcome.note,
    )
    db.add(reminder)
    db.flush()
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="reminder.sent" if outcome.status == "sent" else "reminder.simulated_dispatch",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={
            "approval_id": approval.id,
            "recipient": recipient,
            "channel": channel,
            "provider": outcome.provider,
        },
    )
    return {
        "dispatch": "sent" if outcome.status == "sent" else "simulated",
        "channel": channel,
        "recipient": recipient,
        "reminder_id": reminder.id,
        "provider": outcome.provider,
        "note": outcome.note,
    }


def _available_headroom(db: Session, profile: BusinessProfile) -> Decimal:
    forecast = build_forecast(db, profile, 30, "base")
    return q2(max(Decimal("0.00"), forecast["minimum_balance"] - profile.min_cash_reserve))


def _execute_live_order(
    db: Session,
    user: User,
    approval: ApprovalRequest,
    instrument: MarketInstrument,
    quote: MarketQuote,
    *,
    quantity: int,
    order_type: str,
    side: str,
    multiplier: int,
    limit_price: Decimal | None,
    order_value: Decimal,
) -> dict:
    block = live_order_block_reason(user, quote)
    if block:
        raise HTTPException(status_code=409, detail=block)
    instrument_key = live_instrument_key(instrument, approval.payload)
    if not instrument_key:
        raise HTTPException(
            status_code=409,
            detail="This instrument has no Upstox instrument token, so a live order cannot be placed.",
        )

    broker_quantity = quantity * multiplier
    order_tag = f"BP-{approval.id}-{approval.payload_hash[:10]}"
    live_payload = {
        "quantity": broker_quantity,
        "product": "D",
        "validity": "DAY",
        "price": float(q2(limit_price)) if order_type == "limit" and limit_price else 0.0,
        "instrument_token": instrument_key,
        "order_type": order_type.upper(),
        "transaction_type": side.upper(),
        "tag": order_tag,
        "is_amo": False,
    }
    if order_type == "market":
        live_payload["market_protection"] = -1

    matched = _find_upstox_order_by_tag(order_tag)
    details: dict | None = None
    if matched and matched.get("order_id"):
        broker_order_id = str(matched["order_id"])
        details = matched
    else:
        try:
            placed = upstox_client.place_order(live_payload)
        except UpstoxError as exc:
            if "did not answer in time" not in str(exc):
                raise HTTPException(
                    status_code=502, detail=f"Upstox rejected the live order: {exc}"
                ) from exc
            matched = _find_upstox_order_by_tag(order_tag)
            if not (matched and matched.get("order_id")):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            broker_order_id = str(matched["order_id"])
            details = matched
        else:
            broker_order_id = str(placed["order_id"])

    order = BrokerOrder(
        user_id=user.id,
        approval_id=approval.id,
        instrument_id=instrument.id,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        status="live_submitted",
        broker="upstox",
        simulated=False,
        broker_order_id=broker_order_id,
        broker_status="submitted",
        order_tag=order_tag,
    )
    db.add(order)
    db.flush()
    if details is None:
        try:
            details = upstox_client.get_order_details(broker_order_id)
        except UpstoxError:
            details = None
    if details:
        apply_upstox_order_status(order, details)

    note = (
        "Live order submitted to Upstox. Real money and holdings can change; "
        "refresh the broker status to confirm the fill."
    )
    if order_type == "market":
        note += " A market order can fill at a different price than the displayed quote."
    if side == "sell":
        note += " No local holdings check was performed; Upstox applies its own margin and holdings validation."
    if details is None:
        note += " The broker status could not be refreshed yet."
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="order.live_submitted",
        entity_type="order",
        entity_id=order.id,
        detail={
            "symbol": instrument.symbol,
            "side": side,
            "quantity": quantity,
            "broker_quantity": broker_quantity,
            "order_value": str(order_value),
            "approval_id": approval.id,
            "broker_order_id": broker_order_id,
            "order_tag": order_tag,
        },
    )
    return {
        "broker": "upstox",
        "execution_mode": "live",
        "order_id": order.id,
        "broker_order_id": order.broker_order_id,
        "order_value": order_value,
        "quote_price": q2(quote.price),
        "quote_mode": quote.data_mode,
        "status": order.status,
        "simulated": False,
        "lot_size": multiplier,
        "note": note,
    }


def _execute_investment_order(db: Session, user: User, approval: ApprovalRequest) -> dict:
    payload = approval.payload
    instrument = (
        db.query(MarketInstrument)
        .filter(MarketInstrument.symbol == payload.get("symbol"))
        .one_or_none()
    )
    if instrument is None:
        raise HTTPException(status_code=409, detail="Instrument is no longer available.")
    quote = (
        db.query(MarketQuote)
        .filter(MarketQuote.instrument_id == instrument.id)
        .order_by(MarketQuote.as_of.desc())
        .first()
    )
    if quote is None:
        raise HTTPException(status_code=409, detail="No valid quote available for this instrument.")

    quantity = int(payload["quantity"])
    order_type = payload["order_type"]
    side = payload.get("side")
    multiplier = max(1, int(payload.get("lot_size") or 1))
    limit_price = Decimal(str(payload["limit_price"])) if payload.get("limit_price") else None
    reference_price = limit_price if order_type == "limit" and limit_price else q2(quote.price)
    order_value = q2(reference_price * quantity * multiplier)
    execution_mode = payload.get("execution_mode", "simulated")

    if approval.payload_hash != payload_hash(approval.action_type, approval.payload):
        raise HTTPException(status_code=409, detail="Action details no longer match the approved request.")
    if side not in ("buy", "sell"):
        raise HTTPException(status_code=409, detail="Only buy and sell orders are supported.")
    if execution_mode not in ("simulated", "live"):
        raise HTTPException(status_code=409, detail="Unsupported execution mode.")

    existing = db.query(BrokerOrder).filter(BrokerOrder.approval_id == approval.id).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="This approval has already produced an order.")

    if side == "buy":
        headroom = _available_headroom(db, user.profile)
        if order_value > headroom:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Order value {order_value} exceeds investable headroom {headroom} above your reserve. "
                    "Reduce the order or improve projected cash first."
                ),
            )

    if execution_mode == "live":
        return _execute_live_order(
            db,
            user,
            approval,
            instrument,
            quote,
            quantity=quantity,
            order_type=order_type,
            side=side,
            multiplier=multiplier,
            limit_price=limit_price,
            order_value=order_value,
        )

    order = BrokerOrder(
        user_id=user.id,
        approval_id=approval.id,
        instrument_id=instrument.id,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        status="simulated_pending",
        broker="simulated",
        simulated=True,
        broker_order_id=f"SIM-{secrets.token_hex(4).upper()}",
    )
    db.add(order)
    db.flush()
    note = "Simulated broker order only. No live Upstox order was placed."
    if instrument.asset_class == "option":
        note += f" Option value uses {multiplier} units per lot; no margin or position accounting is performed."
    if side == "sell":
        note += " Simulated sells do not verify holdings or settlement."
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="order.simulated_submitted",
        entity_type="order",
        entity_id=order.id,
        detail={
            "symbol": instrument.symbol,
            "side": side,
            "quantity": quantity,
            "multiplier": multiplier,
            "order_value": str(order_value),
            "approval_id": approval.id,
        },
    )
    return {
        "broker": "simulated",
        "execution_mode": "simulated",
        "order_id": order.id,
        "broker_order_id": order.broker_order_id,
        "order_value": order_value,
        "quote_price": q2(quote.price),
        "quote_mode": quote.data_mode,
        "status": order.status,
        "simulated": True,
        "lot_size": multiplier,
        "note": note,
    }


def _execute_cashflow_intervention(db: Session, user: User, approval: ApprovalRequest) -> dict:
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="cashflow.intervention_acknowledged",
        entity_type="approval",
        entity_id=approval.id,
        detail={"recommendation": approval.payload.get("recommendation", "")[:300]},
    )
    return {
        "acknowledged": True,
        "note": "Advisory acknowledgement only. No payments, deferrals or ledger changes were executed.",
    }


def approve_request(
    db: Session,
    user: User,
    approval_id: int,
    expected_hash: str,
    confirm: bool,
    note: str | None = None,
) -> ApprovalRequest:
    approval = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.id == approval_id, ApprovalRequest.user_id == user.id)
        .one_or_none()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if approval.status == "pending" and approval.expires_at < utcnow():
        approval.status = "expired"
        db.commit()
    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"This approval is {approval.status} and cannot be executed again.",
        )
    if not confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")
    if expected_hash != approval.payload_hash:
        raise HTTPException(
            status_code=409,
            detail="The action details changed. Review the request and create a fresh approval.",
        )

    approval.decided_at = utcnow()
    try:
        if approval.action_type == "reminder.send":
            result = _execute_reminder(db, user, approval)
        elif approval.action_type == "investment.order":
            result = _execute_investment_order(db, user, approval)
        elif approval.action_type == "cashflow.intervention":
            result = _execute_cashflow_intervention(db, user, approval)
        else:
            raise HTTPException(status_code=400, detail="Unsupported approval action.")
    except HTTPException as exc:
        approval.status = "failed"
        approval.result = {"error": exc.detail}
        log_audit(
            db,
            user_id=user.id,
            actor=user.email,
            action="approval.failed",
            entity_type="approval",
            entity_id=approval.id,
            detail={"error": str(exc.detail), "note": note or ""},
        )
        db.commit()
        raise

    approval.status = "executed"
    approval.executed_at = utcnow()
    approval.result = result
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="approval.executed",
        entity_type="approval",
        entity_id=approval.id,
        detail={"action_type": approval.action_type, "result": result, "note": note or ""},
    )
    db.commit()
    db.refresh(approval)
    return approval


def reject_request(
    db: Session, user: User, approval_id: int, reason: str | None = None
) -> ApprovalRequest:
    approval = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.id == approval_id, ApprovalRequest.user_id == user.id)
        .one_or_none()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if approval.status == "pending" and approval.expires_at < utcnow():
        approval.status = "expired"
        db.commit()
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"This approval is {approval.status}.")
    approval.status = "rejected"
    approval.decided_at = utcnow()
    approval.result = {"reason": reason or "Rejected by owner"}
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="approval.rejected",
        entity_type="approval",
        entity_id=approval.id,
        detail={"reason": reason or "", "action_type": approval.action_type},
    )
    db.commit()
    db.refresh(approval)
    return approval


def order_to_dict(order: BrokerOrder) -> dict:
    payload = order.approval.payload if order.approval else {}
    order_value = payload.get("illustrative_order_value")
    quote_price = payload.get("quote_price")
    return {
        "id": order.id,
        "approval_id": order.approval_id,
        "instrument_id": order.instrument_id,
        "symbol": order.instrument.symbol if hasattr(order, "instrument") and order.instrument else None,
        "asset_class": order.instrument.asset_class if order.instrument else None,
        "side": order.side,
        "quantity": order.quantity,
        "lot_size": int(payload.get("lot_size") or 1),
        "option": payload.get("option"),
        "order_type": order.order_type,
        "limit_price": q2(order.limit_price) if order.limit_price is not None else None,
        "order_value": q2(Decimal(str(order_value))) if order_value is not None else None,
        "quote_price": q2(Decimal(str(quote_price))) if quote_price is not None else None,
        "quote_data_mode": payload.get("quote_data_mode"),
        "status": order.status,
        "broker": order.broker,
        "simulated": order.simulated,
        "execution_mode": "simulated" if order.simulated else "live",
        "broker_order_id": order.broker_order_id,
        "broker_status": order.broker_status,
        "broker_status_message": order.broker_status_message,
        "order_tag": order.order_tag,
        "last_synced_at": order.last_synced_at,
        "rejection_reason": order.rejection_reason,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }
