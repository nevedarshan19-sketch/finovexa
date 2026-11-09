from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Customer, Invoice, InvoiceItem, Payment, Product, User
from ..schemas import (
    InvoiceCreateIn,
    MatchPaymentIn,
    PaymentRecordIn,
    PaymentReverseIn,
    PaymentUpdateIn,
    ReminderDraftIn,
)
from ..security import get_current_owner, get_current_user, rate_limit
from ..services.audit import log_audit
from ..services.business_context import require_business
from ..services.finance import (
    confirmed_paid_by_invoice,
    invoice_to_dict,
    payment_to_dict,
    q2,
)
from ..services.gst_catalogue import effective_gst_rate
from ..services.payments import record_payment, reverse_payment, update_payment
from ..services.recovery import (
    REMINDER_STAGE_MAP,
    reminder_draft,
    reminder_schedule,
    reminder_stage_for_due_date,
)

router = APIRouter(tags=["Invoices and recovery"])


@router.get("/invoices")
def list_invoices(
    q: str | None = Query(default=None, max_length=100),
    status_filter: str = Query(default="all", alias="status"),
    limit: int = Query(default=100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Invoice).join(Customer).filter(Invoice.user_id == user.id)
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Invoice.number.ilike(needle),
                Customer.name.ilike(needle),
                Customer.company.ilike(needle),
            )
        )
    invoices = query.order_by(Invoice.issue_date.desc(), Invoice.id.desc()).limit(limit).all()
    paid_map = confirmed_paid_by_invoice(db, user.id)
    items = [invoice_to_dict(db, invoice, paid_map) for invoice in invoices]
    if status_filter == "overdue":
        items = [item for item in items if item["status"] == "overdue"]
    elif status_filter == "outstanding":
        items = [item for item in items if item["outstanding"] > 0 and item["status"] != "void"]
    elif status_filter in ("issued", "paid", "partially_paid"):
        items = [item for item in items if item["status"] == status_filter]
    return {"items": items, "count": len(items)}


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.user_id == user.id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    payload = invoice_to_dict(db, invoice)
    payload["reminders"] = [
        {
            "id": reminder.id,
            "status": reminder.status,
            "channel": reminder.channel,
            "stage": reminder.stage,
            "body": reminder.body,
            "delivery_note": reminder.delivery_note,
            "created_at": reminder.created_at,
        }
        for reminder in invoice.reminders
    ]
    return payload


@router.post("/invoices", status_code=201)
def create_invoice(
    payload: InvoiceCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.due_date < payload.issue_date:
        raise HTTPException(status_code=400, detail="Due date cannot be before the issue date.")
    customer = (
        db.query(Customer)
        .filter(Customer.id == payload.customer_id, Customer.user_id == user.id)
        .one_or_none()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    existing = (
        db.query(Invoice)
        .filter(Invoice.user_id == user.id, Invoice.number == payload.number)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Invoice number already exists.")
    profile = require_business(db, user)
    product_ids = [item.product_id for item in payload.items if item.product_id]
    owned_products = {
        product.id: product
        for product in db.query(Product)
        .filter(Product.user_id == user.id, Product.id.in_(product_ids))
        .all()
    } if product_ids else {}
    invoice = Invoice(
        user_id=user.id,
        created_by_user_id=user.id,
        customer_id=customer.id,
        number=payload.number.strip(),
        issue_date=payload.issue_date,
        due_date=payload.due_date,
        currency=profile.currency,
        status="issued",
        notes=payload.notes,
        pricing_mode="exclusive",
        supplier_name=profile.legal_name or profile.business_name,
        supplier_gstin=profile.gstin,
        supplier_state=profile.state,
        supplier_state_code=profile.state_code,
        customer_name=customer.name,
        customer_gstin=customer.gstin,
        customer_state=customer.state,
        customer_state_code=customer.state_code,
        place_of_supply_state=customer.state,
        place_of_supply_state_code=customer.state_code,
        supply_verified=False,
    )
    db.add(invoice)
    db.flush()
    supplier_code = profile.state_code
    place_code = customer.state_code
    if supplier_code and place_code:
        supply_type = "intra_state" if supplier_code == place_code else "inter_state"
    else:
        supply_type = "unverified"
    invoice.supply_type = supply_type
    rate = q2(payload.tax_rate)
    subtotal = q2(0)
    tax_total = q2(0)
    cgst = q2(0)
    sgst = q2(0)
    igst = q2(0)
    for item in payload.items:
        if item.product_id and item.product_id not in owned_products:
            raise HTTPException(status_code=404, detail="Product not found for this business.")
        product = owned_products.get(item.product_id) if item.product_id else None
        line_rate = (
            q2(effective_gst_rate(db, product, payload.issue_date))
            if product is not None
            else q2(item.gst_rate) if item.gst_rate is not None else rate
        )
        line_total = q2(item.quantity * item.unit_price)
        subtotal = q2(subtotal + line_total)
        line_gst = q2(line_total * line_rate / Decimal("100"))
        tax_total = q2(tax_total + line_gst)
        if supply_type == "intra_state":
            line_cgst = q2(line_gst / 2)
            line_sgst = q2(line_gst - line_cgst)
            line_igst = q2(0)
        elif supply_type == "inter_state":
            line_cgst = q2(0)
            line_sgst = q2(0)
            line_igst = line_gst
        else:
            line_cgst = q2(0)
            line_sgst = q2(0)
            line_igst = q2(0)
        cgst = q2(cgst + line_cgst)
        sgst = q2(sgst + line_sgst)
        igst = q2(igst + line_igst)
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                product_id=item.product_id,
                name=item.description,
                description=item.description,
                hsn_sac=product.hsn_sac if product else None,
                unit=product.unit if product else "pcs",
                item_type=product.item_type if product else "goods",
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=q2(0),
                line_total=line_total,
                taxable_value=line_total,
                gst_rate=line_rate,
                cgst_amount=line_cgst,
                sgst_amount=line_sgst,
                igst_amount=line_igst,
                gst_amount=line_gst,
                final_amount=q2(line_total + line_gst),
                pricing_mode="exclusive",
            )
        )
    invoice.subtotal_amount = subtotal
    invoice.discount_amount = q2(0)
    invoice.taxable_amount = subtotal
    invoice.tax_amount = tax_total
    invoice.cgst_amount = cgst
    invoice.sgst_amount = sgst
    invoice.igst_amount = igst
    invoice.other_charges = q2(0)
    invoice.rounding_adjustment = q2(0)
    invoice.round_to_rupee = False
    invoice.total_amount = q2(subtotal + invoice.tax_amount)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="invoice.created",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={"number": invoice.number, "total": str(invoice.total_amount)},
    )
    db.commit()
    db.refresh(invoice)
    return invoice_to_dict(db, invoice)


@router.post(
    "/invoices/{invoice_id}/payments",
    dependencies=[Depends(rate_limit("record_payment", 30, 60))],
)
def add_payment(
    invoice_id: int,
    payload: PaymentRecordIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.user_id == user.id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    payment = record_payment(
        db,
        user=user,
        invoice=invoice,
        amount=payload.amount,
        method=payload.method,
        status="confirmed",
        provider="owner_recorded",
        provider_ref=payload.reference,
        note=payload.note or "Payment recorded by owner from verified statement.",
        received_at=payload.received_at,
    )
    db.refresh(invoice)
    return {
        "payment": payment_to_dict(payment),
        "invoice": invoice_to_dict(db, invoice),
        "message": "Payment recorded as confirmed from owner-provided evidence.",
    }


@router.get("/recovery/summary")
def recovery_summary_route(
    days: int = Query(default=30, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from ..services.recovery import recovery_summary

    return recovery_summary(db, require_business(db, user), days)


@router.get("/recovery/duplicates")
def duplicate_checks_route(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    from ..services.recovery import duplicate_checks

    return duplicate_checks(db, user.id)


@router.get("/recovery/priorities")
def priority_route(
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from ..services.finance import invoice_to_dict
    from ..services.recovery import priority_rows

    rows = priority_rows(db, user.id)[:limit]
    return {
        "items": [
            {
                "invoice": invoice_to_dict(db, row["invoice"], include_items=False),
                "priority_score": row["priority_score"],
                "reasons": row["reasons"],
            }
            for row in rows
        ]
    }


@router.get("/recovery/unmatched")
def unmatched_route(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..services.recovery import unmatched_payments

    return {"items": unmatched_payments(db, user.id)}


@router.get("/recovery/reminder-schedule")
def reminder_schedule_route(
    window_days: int = Query(default=7, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return reminder_schedule(db, require_business(db, user), window_days)


@router.post(
    "/recovery/reminder-draft/{invoice_id}",
    dependencies=[Depends(rate_limit("reminder_draft", 20, 60))],
)
def draft_reminder(
    invoice_id: int,
    payload: ReminderDraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.user_id == user.id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if invoice.outstanding_amount <= 0:
        raise HTTPException(status_code=409, detail="Invoice has no outstanding balance.")
    paid = confirmed_paid_by_invoice(db, user.id).get(invoice.id)
    stage = REMINDER_STAGE_MAP.get(payload.stage) if payload.stage else None
    profile = require_business(db, user)
    tone = payload.tone or (stage["tone"] if stage else None) or profile.reminder_tone
    draft = reminder_draft(invoice, profile, tone, paid)
    current = reminder_stage_for_due_date(invoice.due_date)
    phone = invoice.customer_phone or invoice.customer.phone
    draft["channel"] = payload.channel
    draft["recipient"] = (
        invoice.customer.email if payload.channel == "email" else (phone or "")
    )
    draft["email"] = invoice.customer.email
    draft["phone"] = phone
    draft["email_ready"] = settings.email_ready
    draft["sms_ready"] = settings.sms_ready
    draft["stage"] = payload.stage
    draft["stage_label"] = stage["label"] if stage else None
    draft["stage_description"] = stage["description"] if stage else None
    draft["current_stage"] = current["key"] if current else None
    if payload.instructions:
        draft["note"] = (
            "Drafted from ledger records. The optional custom instruction was not sent to an AI provider; "
            "review and edit the text before requesting approval."
        )
    return draft


@router.get("/payments")
def list_payments(
    status_filter: str = Query(default="all", alias="status"),
    unmatched: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Payment).filter(Payment.user_id == user.id)
    if status_filter != "all":
        query = query.filter(Payment.status == status_filter)
    if unmatched:
        query = query.filter(Payment.invoice_id.is_(None))
    payments = query.order_by(
        func.coalesce(Payment.received_at, Payment.created_at).desc()
    ).limit(100).all()
    return {
        "items": [payment_to_dict(payment) for payment in payments],
        "count": len(payments),
    }


@router.post("/payments/{payment_id}/match")
def match_payment_route(
    payment_id: int,
    payload: MatchPaymentIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from ..services.payments import match_payment

    payment = (
        db.query(Payment).filter(Payment.id == payment_id, Payment.user_id == user.id).one_or_none()
    )
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == payload.invoice_id, Invoice.user_id == user.id)
        .one_or_none()
    )
    if payment is None or invoice is None:
        raise HTTPException(status_code=404, detail="Payment or invoice not found.")
    updated = match_payment(db, user, payment, invoice, payload.confirm)
    return {
        "payment": payment_to_dict(updated),
        "invoice": invoice_to_dict(db, invoice),
        "message": "Payment reconciled to the invoice.",
    }


def _owned_payment(db: Session, user: User, payment_id: int) -> Payment:
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id, Payment.user_id == user.id)
        .one_or_none()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return payment


@router.patch("/payments/{payment_id}")
def edit_payment_route(
    payment_id: int,
    payload: PaymentUpdateIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    payment = _owned_payment(db, user, payment_id)
    updated = update_payment(
        db,
        user,
        payment,
        amount=payload.amount,
        method=payload.method,
        provider_ref=payload.reference,
        note=payload.note,
        received_at=payload.received_at,
    )
    invoice = updated.invoice
    return {
        "payment": payment_to_dict(updated),
        "invoice": invoice_to_dict(db, invoice) if invoice is not None else None,
        "message": "Payment updated. Invoice dues and payment status were recalculated.",
    }


@router.post("/payments/{payment_id}/reverse")
def reverse_payment_route(
    payment_id: int,
    payload: PaymentReverseIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    payment = _owned_payment(db, user, payment_id)
    reversed_payment = reverse_payment(db, user, payment, reason=payload.reason)
    invoice = reversed_payment.invoice
    return {
        "payment": payment_to_dict(reversed_payment),
        "invoice": invoice_to_dict(db, invoice) if invoice is not None else None,
        "message": (
            "Payment reversed and the invoice dues were restored. "
            "The original record is kept for the audit trail."
        ),
    }
