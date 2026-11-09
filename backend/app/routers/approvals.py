from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ApprovalRequest, BrokerOrder, Invoice, MarketInstrument, User, utcnow
from ..schemas import (
    ApproveIn,
    CashflowInterventionIn,
    ConfirmIn,
    InvestmentApprovalIn,
    OptionApprovalIn,
    RejectIn,
    ReminderApprovalIn,
)
from ..security import get_current_user, rate_limit
from ..services.business_context import require_business
from ..services.approvals import (
    LIVE_CANCELLABLE_STATUSES,
    apply_upstox_order_status,
    approval_to_dict,
    approve_request,
    create_approval,
    expire_stale_approvals,
    live_order_block_reason,
    order_to_dict,
    reject_request,
)
from ..services.audit import log_audit
from ..services.contacts import normalize_phone
from ..services.finance import q2
from ..services.integrations.upstox import UpstoxError, upstox_client
from ..services.investments import apply_simulated_fill
from ..services.market import latest_quote
from ..services.options import option_contract_context
from ..config import settings

router = APIRouter(tags=["Approvals and orders"])


@router.get("/approvals")
def list_approvals(
    status_filter: str = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expire_stale_approvals(db, user.id)
    query = db.query(ApprovalRequest).filter(ApprovalRequest.user_id == user.id)
    if status_filter != "all":
        query = query.filter(ApprovalRequest.status == status_filter)
    rows = query.order_by(ApprovalRequest.created_at.desc()).limit(limit).all()
    items = [approval_to_dict(row) for row in rows]
    return {
        "items": items,
        "pending_count": sum(1 for item in items if item["status"] == "pending"),
        "note": "Approvals expire. Every approval is bound to a canonical hash of the exact action details.",
    }


@router.get("/approvals/{approval_id}")
def approval_detail(
    approval_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    approval = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.id == approval_id, ApprovalRequest.user_id == user.id)
        .one_or_none()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    payload = approval_to_dict(approval)
    order = db.query(BrokerOrder).filter(BrokerOrder.approval_id == approval.id).one_or_none()
    payload["order"] = order_to_dict(order) if order else None
    return payload


@router.post(
    "/approvals/{approval_id}/approve",
    dependencies=[Depends(rate_limit("approval_execute", 20, 60))],
)
def approve(
    approval_id: int,
    payload: ApproveIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    approval = approve_request(
        db, user, approval_id, payload.payload_hash, payload.confirm, payload.note
    )
    result = approval_to_dict(approval)
    order = db.query(BrokerOrder).filter(BrokerOrder.approval_id == approval.id).one_or_none()
    result["order"] = order_to_dict(order) if order else None
    return result


@router.post("/approvals/{approval_id}/reject")
def reject(
    approval_id: int,
    payload: RejectIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    approval = reject_request(db, user, approval_id, payload.reason)
    return approval_to_dict(approval)


@router.post(
    "/approvals/reminders",
    status_code=201,
    dependencies=[Depends(rate_limit("approval_create", 20, 60))],
)
def create_reminder_approval(
    payload: ReminderApprovalIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == payload.invoice_id, Invoice.user_id == user.id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if invoice.outstanding_amount <= 0:
        raise HTTPException(status_code=409, detail="Invoice has no outstanding balance.")
    channel = payload.channel
    if channel == "email":
        recipient = invoice.customer.email
        if payload.recipient.strip().lower() != recipient.lower():
            raise HTTPException(
                status_code=400,
                detail="The recipient must match the invoice customer email on record.",
            )
        subject = (payload.subject or f"Payment reminder · {invoice.number}").strip()
    else:
        on_file = normalize_phone(invoice.customer_phone or invoice.customer.phone)
        if not on_file:
            raise HTTPException(
                status_code=409,
                detail="Add a mobile number to this invoice's customer before sending an SMS reminder.",
            )
        recipient = normalize_phone(payload.recipient)
        if recipient != on_file:
            raise HTTPException(
                status_code=400,
                detail="The recipient must match the customer mobile number on record.",
            )
        subject = None
    approval = create_approval(
        db,
        user,
        action_type="reminder.send",
        title=f"Send {channel.upper()} payment reminder to {invoice.customer.name}",
        reason=(
            f"Invoice {invoice.number} has {require_business(db, user).currency} {invoice.outstanding_amount:,.2f} "
            f"outstanding and is due {invoice.due_date.isoformat()}. "
            f"Requested delivery channel: {channel}."
        ),
        payload={
            "invoice_id": invoice.id,
            "invoice_number": invoice.number,
            "recipient": recipient,
            "channel": channel,
            "subject": subject,
            "body": payload.body.strip(),
            "stage": payload.stage,
            "due_date": invoice.due_date.isoformat(),
        },
        evidence=[
            {
                "type": "invoice",
                "id": invoice.id,
                "label": f"{invoice.number} · {invoice.customer.company}",
                "amount": q2(invoice.outstanding_amount),
                "due_date": invoice.due_date.isoformat(),
            }
        ],
        financial_impact=q2(invoice.outstanding_amount),
        risk_level="low",
    )
    return approval_to_dict(approval)


@router.post(
    "/approvals/investments",
    status_code=201,
    dependencies=[Depends(rate_limit("approval_create", 20, 60))],
)
def create_investment_approval(
    payload: InvestmentApprovalIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instrument = (
        db.query(MarketInstrument)
        .filter(MarketInstrument.symbol == payload.symbol.upper())
        .one_or_none()
    )
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found.")
    quote = latest_quote(db, instrument.id)
    if quote is None:
        raise HTTPException(
            status_code=409,
            detail="No quote is available. An order cannot be priced without market data.",
        )
    if payload.order_type == "limit" and payload.limit_price is None:
        raise HTTPException(status_code=400, detail="A limit order requires a limit price.")
    if payload.order_type == "market" and payload.limit_price is not None:
        raise HTTPException(status_code=400, detail="Remove the limit price for a market order.")
    reference_price = (
        payload.limit_price if payload.order_type == "limit" else q2(quote.price)
    )
    order_value = q2(Decimal(str(reference_price)) * payload.quantity)
    execution_mode = payload.execution_mode
    if execution_mode == "live":
        block = live_order_block_reason(user, quote)
        if block:
            raise HTTPException(status_code=409, detail=block)
        if not instrument.external_key:
            raise HTTPException(
                status_code=409,
                detail="This instrument has no Upstox instrument token, so a live order cannot be requested.",
            )
    live = execution_mode == "live"
    if live:
        reason = (
            "Owner-requested live order. Approving sends a real order to Upstox and can move real "
            "money and holdings. Upstox requires order placement from a registered static IP. "
            "No order is placed until you approve this exact payload."
        )
        if payload.side == "sell":
            reason += " Live sells are not checked against local holdings; Upstox applies its own validation."
    elif payload.side == "sell":
        reason = (
            "Owner-requested simulated sell. No holdings, margin or settlement are checked; "
            "this is a paper order and no live order will be placed."
        )
    else:
        reason = (
            "Owner-requested research order. This approval is for a simulated broker workflow only; "
            "no live order will be placed."
        )
    approval = create_approval(
        db,
        user,
        action_type="investment.order",
        title=(
            f"Review {'live' if live else 'simulated'} {payload.side} order · "
            f"{payload.quantity} × {instrument.symbol}"
        ),
        reason=reason,
        payload={
            "symbol": instrument.symbol,
            "exchange": instrument.exchange,
            "asset_class": instrument.asset_class,
            "side": payload.side,
            "quantity": payload.quantity,
            "lot_size": 1,
            "option": None,
            "order_type": payload.order_type,
            "limit_price": str(payload.limit_price) if payload.limit_price is not None else None,
            "quote_price": str(q2(quote.price)),
            "quote_as_of": quote.as_of.isoformat(),
            "quote_data_mode": quote.data_mode,
            "illustrative_order_value": str(order_value),
            "holdings_check": "not_performed" if payload.side == "sell" else "not_required_for_buy",
            "execution_mode": execution_mode,
            "simulated": not live,
        },
        evidence=[
            {
                "type": "market_quote",
                "id": instrument.symbol,
                "label": f"{instrument.symbol} · {quote.source}",
                "amount": q2(quote.price),
                "data_mode": quote.data_mode,
            }
        ],
        financial_impact=order_value,
        risk_level="high",
    )
    return approval_to_dict(approval)


@router.post(
    "/approvals/options",
    status_code=201,
    dependencies=[Depends(rate_limit("approval_create", 20, 60))],
)
def create_option_approval(
    payload: OptionApprovalIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.order_type == "limit" and payload.limit_price is None:
        raise HTTPException(status_code=400, detail="A limit order requires a limit price.")
    if payload.order_type == "market" and payload.limit_price is not None:
        raise HTTPException(status_code=400, detail="Remove the limit price for a market order.")
    try:
        context = option_contract_context(
            db, payload.expiry, float(payload.strike), payload.option_type
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    chain = context["chain"]
    leg = context["leg"]
    instrument = context["instrument"]
    quote = context["quote"]
    lot_size = context["lot_size"]
    reference_price = payload.limit_price if payload.order_type == "limit" else q2(quote.price)
    order_value = q2(Decimal(str(reference_price)) * payload.lots * lot_size)
    pretty = "Call" if payload.option_type == "call" else "Put"
    display = f"NIFTY {context['row']['strike']:.0f} {pretty} · {chain['selected_expiry']}"
    execution_mode = payload.execution_mode
    live = execution_mode == "live"
    if live:
        if chain["data_mode"] != "live":
            raise HTTPException(
                status_code=409,
                detail="Live option orders require a live Upstox option chain. Refresh and try again.",
            )
        block = live_order_block_reason(user, quote)
        if block:
            raise HTTPException(status_code=409, detail=block)
        if not leg.get("instrument_key"):
            raise HTTPException(
                status_code=409,
                detail="This option leg has no Upstox instrument token, so a live order cannot be requested.",
            )
    if live:
        reason = (
            "Owner-requested live derivative order. Approving sends a real order to Upstox and can "
            "move real money and margin. Upstox requires order placement from a registered static IP. "
            f"Premia are multiplied by {lot_size} units per lot. No order is placed until you approve "
            "this exact payload."
        )
        if payload.side == "sell":
            reason += " Live option sells are not checked against local holdings; Upstox applies margin validation."
    else:
        reason = (
            "Owner-requested option paper order priced from the displayed chain. Premia are multiplied by "
            f"{lot_size} units per lot. This is a simulated order only; no live derivative order is placed."
            + (
                " Simulated sells do not verify holdings, margin or settlement."
                if payload.side == "sell"
                else ""
            )
            + (
                f" Chain data mode: {chain['data_mode']}."
            )
        )
    approval = create_approval(
        db,
        user,
        action_type="investment.order",
        title=(
            f"Review {'live' if live else 'simulated'} {payload.side} option · {payload.lots} lot"
            f"{'s' if payload.lots != 1 else ''} {instrument.symbol}"
        ),
        reason=reason,
        payload={
            "symbol": instrument.symbol,
            "exchange": "NSE",
            "asset_class": "option",
            "side": payload.side,
            "quantity": payload.lots,
            "lot_size": lot_size,
            "order_type": payload.order_type,
            "limit_price": str(payload.limit_price) if payload.limit_price is not None else None,
            "quote_price": str(q2(quote.price)),
            "quote_as_of": quote.as_of.isoformat(),
            "quote_data_mode": quote.data_mode,
            "illustrative_order_value": str(order_value),
            "option": {
                "underlying": "NIFTY 50",
                "expiry": chain["selected_expiry"],
                "strike": float(context["row"]["strike"]),
                "option_type": payload.option_type,
                "instrument_key": leg.get("instrument_key"),
                "symbol": instrument.symbol,
                "display_name": display,
                "lot_size": lot_size,
                "chain_data_mode": chain["data_mode"],
            },
            "holdings_check": "not_performed" if payload.side == "sell" else "not_required_for_buy",
            "execution_mode": execution_mode,
            "simulated": not live,
        },
        evidence=[
            {
                "type": "option_quote",
                "id": instrument.symbol,
                "label": f"{display} · {chain['source']}",
                "amount": q2(quote.price),
                "data_mode": quote.data_mode,
            }
        ],
        financial_impact=order_value,
        risk_level="high",
    )
    return approval_to_dict(approval)


@router.post(
    "/approvals/cashflow",
    status_code=201,
    dependencies=[Depends(rate_limit("approval_create", 20, 60))],
)
def create_cashflow_approval(
    payload: CashflowInterventionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    approval = create_approval(
        db,
        user,
        action_type="cashflow.intervention",
        title=payload.title,
        reason=payload.recommendation,
        payload={
            "recommendation": payload.recommendation,
            "financial_impact": str(payload.financial_impact)
            if payload.financial_impact is not None
            else None,
            "no_external_effect": True,
        },
        evidence=[
            {
                "type": "advisory",
                "id": "owner-created",
                "label": "Owner-created cash-flow acknowledgement (advisory only)",
            }
        ],
        financial_impact=payload.financial_impact,
        risk_level="medium",
    )
    return approval_to_dict(approval)


@router.get("/orders")
def list_orders(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(BrokerOrder)
        .filter(BrokerOrder.user_id == user.id)
        .order_by(BrokerOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [order_to_dict(row) for row in rows],
        "broker_mode": "live" if settings.upstox_live_ready else "simulated",
        "live_trading_enabled": settings.UPSTOX_LIVE_TRADING_ENABLED,
        "upstox_configured": settings.upstox_configured,
        "static_ip_proxy_configured": bool(settings.UPSTOX_ORDER_PROXY_URL),
        "note": (
            "Live Upstox orders are available only for manually approved orders. "
            "Simulated orders remain available and are labelled."
            if settings.upstox_live_ready
            else "All orders in this build are simulated. Enable live trading and configure Upstox credentials to place live orders."
        ),
    }


def _order_for_user(db: Session, user: User, order_id: int) -> BrokerOrder:
    order = (
        db.query(BrokerOrder)
        .filter(BrokerOrder.id == order_id, BrokerOrder.user_id == user.id)
        .one_or_none()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


@router.post(
    "/orders/{order_id}/sync",
    dependencies=[Depends(rate_limit("order_sync", 60, 60))],
)
def sync_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = _order_for_user(db, user, order_id)
    if order.simulated:
        raise HTTPException(
            status_code=409,
            detail="Simulated orders have no broker to sync. Use the simulator actions instead.",
        )
    if not order.broker_order_id:
        raise HTTPException(status_code=409, detail="This live order has no Upstox order id.")
    try:
        details = upstox_client.get_order_details(order.broker_order_id)
    except UpstoxError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not refresh the Upstox order status: {exc}"
        ) from exc
    apply_upstox_order_status(order, details)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="order.live_status_synced",
        entity_type="order",
        entity_id=order.id,
        detail={
            "broker_order_id": order.broker_order_id,
            "broker_status": order.broker_status,
            "status": order.status,
        },
    )
    db.commit()
    db.refresh(order)
    return {
        "order": order_to_dict(order),
        "message": "Broker status refreshed from Upstox.",
    }


@router.post("/orders/{order_id}/cancel-request")
def request_cancellation(
    order_id: int,
    payload: ConfirmIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")
    order = _order_for_user(db, user, order_id)
    if order.simulated:
        if order.status not in ("simulated_pending", "cancel_requested"):
            raise HTTPException(
                status_code=409, detail=f"Order is {order.status} and cannot be cancelled."
            )
        order.status = "cancel_requested"
        log_audit(
            db,
            user_id=user.id,
            actor=user.email,
            action="order.cancel_requested",
            entity_type="order",
            entity_id=order.id,
            detail={"simulated": True, "broker_order_id": order.broker_order_id},
        )
        db.commit()
        db.refresh(order)
        return {
            "order": order_to_dict(order),
            "message": "Cancellation requested on the simulator. No live broker request was sent.",
        }

    if order.status not in LIVE_CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Order is {order.status} and cannot be cancelled."
        )
    if not order.broker_order_id:
        raise HTTPException(
            status_code=409, detail="This live order has no Upstox order id to cancel."
        )
    try:
        upstox_client.cancel_order(order.broker_order_id)
    except UpstoxError as exc:
        raise HTTPException(
            status_code=502, detail=f"Upstox cancellation failed: {exc}"
        ) from exc
    order.status = "live_cancel_requested"
    order.broker_status = "cancel requested"
    order.last_synced_at = utcnow()
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="order.live_cancel_requested",
        entity_type="order",
        entity_id=order.id,
        detail={"simulated": False, "broker_order_id": order.broker_order_id},
    )
    db.commit()
    db.refresh(order)
    return {
        "order": order_to_dict(order),
        "message": "Cancellation request sent to Upstox. Refresh the broker status to confirm.",
    }


@router.post("/orders/{order_id}/simulate-fill")
def simulate_fill(
    order_id: int,
    payload: ConfirmIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")
    order = _order_for_user(db, user, order_id)
    if not order.simulated:
        raise HTTPException(
            status_code=409,
            detail="This is a live order. Refresh it from Upstox instead of using the simulator.",
        )
    if order.status != "simulated_pending":
        raise HTTPException(
            status_code=409, detail=f"Order is {order.status}; a fill is not possible."
        )
    fill_price = order.limit_price
    if fill_price is None or order.order_type == "market":
        quote = latest_quote(db, order.instrument_id)
        if quote is not None and quote.price is not None:
            fill_price = quote.price
    order.status = "simulated_filled"
    portfolio_update = apply_simulated_fill(db, order, fill_price)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="order.simulated_filled",
        entity_type="order",
        entity_id=order.id,
        detail={
            "simulated": True,
            "symbol": order.instrument.symbol if order.instrument else None,
            "quantity": order.quantity,
            "fill_price": str(fill_price) if fill_price is not None else None,
            "portfolio_update": portfolio_update,
        },
    )
    db.commit()
    db.refresh(order)
    return {
        "order": order_to_dict(order),
        "portfolio_update": portfolio_update,
        "message": (
            "Simulated fill recorded in the practice portfolio. "
            "This is not a real execution and no money moved."
        ),
    }


@router.post("/orders/{order_id}/simulate-cancel")
def simulate_cancel(
    order_id: int,
    payload: ConfirmIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")
    order = _order_for_user(db, user, order_id)
    if not order.simulated:
        raise HTTPException(
            status_code=409,
            detail="This is a live order. Use cancel-request to send a cancellation to Upstox.",
        )
    if order.status not in ("simulated_pending", "cancel_requested"):
        raise HTTPException(
            status_code=409, detail=f"Order is {order.status}; it cannot be cancelled."
        )
    order.status = "simulated_cancelled"
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="order.simulated_cancelled",
        entity_type="order",
        entity_id=order.id,
        detail={"simulated": True},
    )
    db.commit()
    db.refresh(order)
    return {
        "order": order_to_dict(order),
        "message": "Simulation cancelled the order. No live broker order exists.",
    }
