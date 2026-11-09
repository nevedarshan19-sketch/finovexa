from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    BusinessProfile,
    Customer,
    GSTRate,
    Invoice,
    InvoiceItem,
    InventoryItem,
    Payment,
    Product,
    User,
)
from ..schemas import (
    BillingCustomerIn,
    BillingProductIn,
    BillingProductUpdateIn,
    BillingSettingsIn,
    ConfirmIn,
    GSTCalculateIn,
    GSTInvoiceIn,
    GSTRateIn,
)
from ..security import get_current_user
from ..services.audit import log_audit
from ..services.contacts import normalize_phone
from ..services.finance import (
    customer_to_dict,
    invoice_display_status,
    invoice_to_dict,
    q2,
    supply_type_label,
)
from ..services.gst import (
    GSTValidationError,
    LineInput,
    ensure_default_gst_rates,
    invoice_totals,
    normalize_gstin,
    normalize_rate,
    normalize_state,
    resolve_supply_type,
    state_name,
    state_options,
    validate_configured_rate,
)
from ..services.gst_catalogue import request_change
from ..services.invoice_pdf import build_invoice_pdf

router = APIRouter(tags=["GST and billing"])


def _fail(exc: GSTValidationError, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _profile_address(profile: BusinessProfile) -> str | None:
    parts = [
        profile.address_line1,
        profile.address_line2,
        profile.city,
        profile.state,
        profile.postal_code,
    ]
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    return text or None


def _customer_address(customer: Customer) -> str | None:
    parts = [
        customer.billing_address_line1,
        customer.billing_address_line2,
        customer.city,
        customer.state,
        customer.postal_code,
    ]
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    return text or None


def _supplier_snapshot(profile: BusinessProfile) -> dict:
    try:
        state, code = normalize_state(profile.state, profile.state_code)
        gstin = normalize_gstin(profile.gstin)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    if not code:
        raise HTTPException(
            status_code=400,
            detail=(
                "Set your business GST state in GST settings before creating an invoice. "
                "The state determines the CGST/SGST or IGST split."
            ),
        )
    return {
        "name": _clean(profile.legal_name) or profile.business_name,
        "gstin": gstin,
        "address": _profile_address(profile),
        "state": state,
        "state_code": code,
    }


def _customer_snapshot(customer: Customer) -> dict:
    try:
        state, code = normalize_state(customer.state, customer.state_code)
        gstin = normalize_gstin(customer.gstin)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    return {
        "name": customer.name,
        "gstin": gstin,
        "phone": customer.phone,
        "address": _customer_address(customer),
        "state": state,
        "state_code": code,
    }


def _resolve_customer(db: Session, user: User, payload: GSTInvoiceIn) -> Customer:
    customer: Customer | None = None
    if payload.customer_id is not None:
        customer = (
            db.query(Customer)
            .filter(Customer.id == payload.customer_id, Customer.user_id == user.id)
            .one_or_none()
        )
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer not found.")
    if payload.customer is not None:
        data = payload.customer
        try:
            state, code = normalize_state(data.state, data.state_code)
            gstin = normalize_gstin(data.gstin)
        except GSTValidationError as exc:
            raise _fail(exc) from exc
        if customer is None and payload.save_customer:
            customer = (
                db.query(Customer)
                .filter(
                    Customer.user_id == user.id,
                    func.lower(Customer.email) == str(data.email).lower(),
                )
                .one_or_none()
            )
        if customer is None:
            customer = Customer(
                user_id=user.id,
                name=data.name.strip(),
                email=str(data.email).lower(),
                phone=normalize_phone(data.phone),
            )
            db.add(customer)
            db.flush()
        if payload.save_customer:
            customer.name = data.name.strip()
            customer.email = str(data.email).lower()
            customer.company = _clean(data.company)
            customer.phone = normalize_phone(data.phone)
            customer.gstin = gstin
            customer.billing_address_line1 = _clean(data.billing_address_line1)
            customer.billing_address_line2 = _clean(data.billing_address_line2)
            customer.city = _clean(data.city)
            customer.state = state
            customer.state_code = code
            customer.postal_code = _clean(data.postal_code)
            db.flush()
    if customer is None:
        raise HTTPException(
            status_code=400, detail="Choose an existing customer or enter customer billing details."
        )
    return customer


def _place_of_supply(payload: GSTInvoiceIn) -> tuple[str, str]:
    try:
        name, code = normalize_state(
            payload.place_of_supply_state, payload.place_of_supply_state_code
        )
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    if not code:
        raise HTTPException(
            status_code=400,
            detail=(
                "Place of supply is required. Confirm the customer's state and tick the verification "
                "step before saving the invoice."
            ),
        )
    return name or state_name(code) or "", code


def _require_confirmation(payload: GSTInvoiceIn) -> None:
    if not payload.confirm_supply_details:
        raise HTTPException(
            status_code=400,
            detail=(
                "Confirm that you verified the supplier state, place of supply and the GST rate for "
                "every item. FINOVEXA does not guess legal tax classification."
            ),
        )


def _prepare_lines(
    db: Session,
    user: User,
    payload: GSTInvoiceIn,
    supply_type: str,
    pricing_mode: str,
) -> tuple[list[LineInput], list[dict]]:
    product_ids = [item.product_id for item in payload.items if item.product_id]
    owned = {
        product.id: product
        for product in db.query(Product)
        .filter(Product.user_id == user.id, Product.id.in_(product_ids))
        .all()
    }
    calc_lines: list[LineInput] = []
    metadata: list[dict] = []
    for item in payload.items:
        if item.product_id and item.product_id not in owned:
            raise HTTPException(status_code=404, detail="Product not found for this business.")
        try:
            rate = validate_configured_rate(db, user, item.gst_rate)
        except GSTValidationError as exc:
            raise _fail(exc) from exc
        calc_lines.append(
            LineInput(
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount=item.discount,
                gst_rate=rate,
                pricing_mode=pricing_mode,
            )
        )
        metadata.append(
            {
                "product_id": item.product_id,
                "name": item.name.strip(),
                "description": _clean(item.description) or item.name.strip(),
                "hsn_sac": _clean(item.hsn_sac),
                "unit": _clean(item.unit) or "pcs",
                "item_type": item.item_type,
            }
        )
    return calc_lines, metadata


def _apply_items(
    db: Session,
    invoice: Invoice,
    metadata: list[dict],
    calculated: list[dict],
    pricing_mode: str,
) -> None:
    for item in list(invoice.items):
        db.delete(item)
    db.flush()
    for meta, calc in zip(metadata, calculated, strict=True):
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                product_id=meta["product_id"],
                name=meta["name"],
                description=meta["description"],
                hsn_sac=meta["hsn_sac"],
                unit=meta["unit"],
                item_type=meta["item_type"],
                quantity=calc["quantity"],
                unit_price=calc["unit_price"],
                discount_amount=calc["discount"],
                line_total=calc["gross_amount"],
                taxable_value=calc["taxable_value"],
                gst_rate=calc["gst_rate"],
                cgst_amount=calc["cgst_amount"],
                sgst_amount=calc["sgst_amount"],
                igst_amount=calc["igst_amount"],
                gst_amount=calc["gst_amount"],
                final_amount=calc["final_amount"],
                pricing_mode=pricing_mode,
            )
        )


def _set_totals(invoice: Invoice, totals: dict, pricing_mode: str, supply_type: str) -> None:
    invoice.pricing_mode = pricing_mode
    invoice.supply_type = supply_type
    invoice.subtotal_amount = totals["subtotal"]
    invoice.discount_amount = totals["discount"]
    invoice.taxable_amount = totals["taxable_value"]
    invoice.tax_amount = totals["tax_amount"]
    invoice.cgst_amount = totals["cgst_amount"]
    invoice.sgst_amount = totals["sgst_amount"]
    invoice.igst_amount = totals["igst_amount"]
    invoice.other_charges = totals["other_charges"]
    invoice.rounding_adjustment = totals["rounding_adjustment"]
    invoice.total_amount = totals["total_amount"]
    invoice.round_to_rupee = totals["round_to_rupee"]


def _next_number(db: Session, user_id: int) -> str:
    numbers = [row[0] for row in db.query(Invoice.number).filter(Invoice.user_id == user_id).all()]
    highest = 1000
    for number in numbers:
        match = re.search(r"(\d+)$", number or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"INV-{highest + 1}"


def _owned_invoice(db: Session, user: User, invoice_id: int) -> Invoice:
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.user_id == user.id)
        .one_or_none()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice


def _serialize_invoice(invoice: Invoice, db: Session) -> dict:
    payload = invoice_to_dict(db, invoice)
    payload["pdf_url"] = f"/billing/invoices/{invoice.id}/pdf"
    return payload


def _serialize_product(product: Product) -> dict:
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "hsn_sac": product.hsn_sac,
        "item_type": product.item_type,
        "unit": product.unit,
        "default_gst_rate": q2(product.default_gst_rate),
        "unit_price": q2(product.unit_price),
        "unit_cost": q2(product.unit_cost),
        "reorder_level": product.reorder_level,
        "quantity_on_hand": product.inventory.quantity_on_hand if product.inventory else 0,
        "low_stock": (product.inventory.quantity_on_hand if product.inventory else 0)
        <= product.reorder_level,
    }


def _serialize_rate(row: GSTRate) -> dict:
    return {
        "id": row.id,
        "rate": q2(row.rate),
        "label": row.label,
        "is_active": row.is_active,
        "is_custom": row.is_custom,
    }


@router.get("/billing/overview")
def billing_overview(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    invoices = (
        db.query(Invoice)
        .filter(Invoice.user_id == user.id, Invoice.status != "void")
        .order_by(Invoice.issue_date.desc(), Invoice.id.desc())
        .all()
    )
    paid_map = {
        invoice.id: q2(
            db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
            .scalar()
        )
        for invoice in invoices
    }
    outstanding = q2(
        sum(
            (
                max(invoice.total_amount - paid_map.get(invoice.id, Decimal("0.00")), Decimal("0.00"))
                for invoice in invoices
            ),
            Decimal("0.00"),
        )
    )
    issued_gst = q2(
        sum((invoice.tax_amount for invoice in invoices), Decimal("0.00"))
    )
    confirmed_received = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.user_id == user.id, Payment.status == "confirmed")
        .scalar()
    )
    overdue = sum(
        1
        for invoice in invoices
        if invoice_display_status(invoice, paid_map.get(invoice.id, Decimal("0.00")))
        == "overdue"
    )
    return {
        "counts": {
            "total": len(invoices),
            "drafts": sum(1 for invoice in invoices if invoice.status == "draft"),
            "open": sum(
                1
                for invoice in invoices
                if invoice.status != "draft"
                and invoice.total_amount > paid_map.get(invoice.id, Decimal("0.00"))
            ),
            "overdue": overdue,
        },
        "totals": {
            "invoiced": q2(sum((invoice.total_amount for invoice in invoices), Decimal("0.00"))),
            "outstanding": outstanding,
            "confirmed_received": confirmed_received,
            "gst_on_invoices": issued_gst,
        },
        "recent": [_serialize_invoice(invoice, db) for invoice in invoices[:6]],
        "note": (
            "GST on invoices is the tax charged on issued invoices, not a net GST payable calculation. "
            "Confirm your rates, HSN/SAC classification and place of supply before issuing a tax invoice."
        ),
    }


@router.get("/billing/settings")
def billing_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = user.profile
    ensure_default_gst_rates(db, user)
    db.commit()
    rates = (
        db.query(GSTRate)
        .filter(GSTRate.user_id == user.id)
        .order_by(GSTRate.sort_order, GSTRate.rate)
        .all()
    )
    return {
        "business": {
            "business_name": profile.business_name,
            "legal_name": profile.legal_name,
            "gstin": profile.gstin,
            "address_line1": profile.address_line1,
            "address_line2": profile.address_line2,
            "city": profile.city,
            "state": profile.state,
            "state_code": profile.state_code,
            "postal_code": profile.postal_code,
            "business_phone": profile.business_phone,
            "business_email": profile.business_email,
            "invoice_terms": profile.invoice_terms,
            "logo_data_url": profile.logo_data_url,
            "currency": profile.currency,
        },
        "ready": bool(profile.state_code),
        "states": state_options(),
        "rates": [_serialize_rate(row) for row in rates],
        "note": (
            "Rates and legal classification are configurable. This app does not decide the correct GST rate "
            "for your goods or services; verify it with your tax adviser before issuing real tax invoices."
        ),
    }


@router.put("/billing/settings")
def update_billing_settings(
    payload: BillingSettingsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = user.profile
    changes = payload.model_dump(exclude_unset=True)
    try:
        if "gstin" in changes:
            profile.gstin = normalize_gstin(changes["gstin"])
        if "state" in changes or "state_code" in changes:
            state, code = normalize_state(
                changes.get("state", profile.state),
                changes.get("state_code", profile.state_code),
            )
            profile.state = state
            profile.state_code = code
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    for field, value in changes.items():
        if field in ("gstin", "state", "state_code"):
            continue
        setattr(profile, field, _clean(value) if isinstance(value, str) else value)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.settings_updated",
        entity_type="business_profile",
        entity_id=profile.id,
        detail={"fields": sorted(changes.keys())},
    )
    db.commit()
    return billing_settings(user, db)


@router.get("/billing/gst-rates")
def list_gst_rates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rates = ensure_default_gst_rates(db, user)
    db.commit()
    return {
        "items": [_serialize_rate(row) for row in sorted(rates, key=lambda row: (row.sort_order, row.rate))],
        "note": "Only active rates can be used on a new invoice. Custom rates require an explicit owner action.",
    }


@router.post("/billing/gst-rates", status_code=201)
def add_gst_rate(
    payload: GSTRateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rate = normalize_rate(payload.rate)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    ensure_default_gst_rates(db, user)
    existing = (
        db.query(GSTRate).filter(GSTRate.user_id == user.id, GSTRate.rate == rate).one_or_none()
    )
    if existing is not None and existing.is_active:
        raise HTTPException(status_code=409, detail=f"{rate}% is already an active GST rate.")
    label = _clean(payload.label) or f"{rate}% (custom)"
    if existing is not None:
        existing.is_active = True
        existing.is_custom = True
        existing.label = label
        row = existing
    else:
        row = GSTRate(
            user_id=user.id,
            rate=rate,
            label=label,
            is_active=True,
            is_custom=True,
            sort_order=100 + int(rate),
        )
        db.add(row)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.gst_rate_added",
        entity_type="gst_rate",
        entity_id=rate,
        detail={"rate": str(rate), "label": label},
    )
    db.commit()
    db.refresh(row)
    return {"item": _serialize_rate(row), "message": "Custom GST rate added after owner confirmation."}


@router.get("/billing/products")
def list_billing_products(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Product).filter(Product.user_id == user.id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(needle),
                Product.sku.ilike(needle),
                Product.hsn_sac.ilike(needle),
            )
        )
    rows = query.order_by(Product.name.asc()).limit(limit).all()
    return {"items": [_serialize_product(row) for row in rows], "count": len(rows)}


@router.post("/billing/products", status_code=201)
def create_billing_product(
    payload: BillingProductIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rate = validate_configured_rate(db, user, payload.default_gst_rate)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    sku = payload.sku.strip()
    existing = (
        db.query(Product).filter(Product.user_id == user.id, Product.sku == sku).one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A product or service with this SKU already exists.")
    product = Product(
        user_id=user.id,
        sku=sku,
        name=payload.name.strip(),
        description=_clean(payload.description),
        hsn_sac=_clean(payload.hsn_sac),
        item_type=payload.item_type,
        unit=_clean(payload.unit) or "pcs",
        default_gst_rate=rate,
        unit_price=q2(payload.unit_price),
        unit_cost=q2(payload.unit_cost),
        reorder_level=payload.reorder_level,
    )
    db.add(product)
    db.flush()
    if payload.item_type == "goods":
        db.add(InventoryItem(product_id=product.id, quantity_on_hand=0))
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.product_created",
        entity_type="product",
        entity_id=product.id,
        detail={"sku": sku, "name": product.name, "gst_rate": str(rate)},
    )
    db.commit()
    db.refresh(product)
    return {"item": _serialize_product(product)}


@router.put("/billing/products/{product_id}")
def update_billing_product(
    product_id: int,
    payload: BillingProductUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == user.id)
        .one_or_none()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    changes = payload.model_dump(exclude_unset=True)
    reason = changes.pop("gst_change_reason", None)
    gst_fields = {"default_gst_rate", "hsn_sac", "item_type"}
    gst_updates: dict = {}
    for field in gst_fields:
        value = changes.get(field)
        if value is None:
            continue
        candidate = value.strip() if isinstance(value, str) else value
        current = getattr(product, field)
        if field == "default_gst_rate":
            if q2(candidate) != q2(current):
                gst_updates[field] = candidate
        elif candidate != current:
            gst_updates[field] = candidate
    if gst_updates and (reason is None or len(reason.strip()) < 3):
        raise HTTPException(
            status_code=400,
            detail="Give a reason for the GST catalogue change (rate, HSN/SAC or item type).",
        )
    for field in gst_fields:
        changes.pop(field, None)
    if changes.get("sku"):
        duplicate = (
            db.query(Product)
            .filter(
                Product.user_id == user.id,
                Product.sku == changes["sku"].strip(),
                Product.id != product.id,
            )
            .one_or_none()
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="A product with this SKU already exists.")
    for field, value in changes.items():
        if value is None:
            continue
        setattr(product, field, value.strip() if isinstance(value, str) else value)
    if changes:
        log_audit(
            db,
            user_id=user.id,
            actor=user.email,
            action="billing.product_updated",
            entity_type="product",
            entity_id=product.id,
            detail={"fields": sorted(changes.keys())},
        )
    if gst_updates:
        try:
            request_change(
                db,
                product=product,
                actor=user,
                role="owner",
                gst_rate=gst_updates.get("default_gst_rate"),
                hsn_sac=gst_updates.get("hsn_sac"),
                item_type=gst_updates.get("item_type"),
                reason=reason or "",
            )
        except GSTValidationError as exc:
            raise _fail(exc) from exc
    else:
        db.commit()
    db.refresh(product)
    return {"item": _serialize_product(product)}


@router.get("/billing/customers")
def list_billing_customers(
    q: str | None = Query(default=None, max_length=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Customer).filter(Customer.user_id == user.id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Customer.name.ilike(needle),
                Customer.company.ilike(needle),
                Customer.email.ilike(needle),
            )
        )
    rows = query.order_by(Customer.name.asc()).limit(200).all()
    return {"items": [customer_to_dict(row) for row in rows], "count": len(rows)}


@router.post("/billing/customers", status_code=201)
def create_billing_customer(
    payload: BillingCustomerIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(Customer)
        .filter(Customer.user_id == user.id, func.lower(Customer.email) == str(payload.email).lower())
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A customer with this email already exists.")
    try:
        state, code = normalize_state(payload.state, payload.state_code)
        gstin = normalize_gstin(payload.gstin)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    customer = Customer(
        user_id=user.id,
        name=payload.name.strip(),
        email=str(payload.email).lower(),
        company=_clean(payload.company),
        phone=normalize_phone(payload.phone),
        gstin=gstin,
        billing_address_line1=_clean(payload.billing_address_line1),
        billing_address_line2=_clean(payload.billing_address_line2),
        city=_clean(payload.city),
        state=state,
        state_code=code,
        postal_code=_clean(payload.postal_code),
    )
    db.add(customer)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.customer_created",
        entity_type="customer",
        entity_id=customer.id,
        detail={"name": customer.name},
    )
    db.commit()
    db.refresh(customer)
    return {"item": customer_to_dict(customer)}


@router.put("/billing/customers/{customer_id}")
def update_billing_customer(
    customer_id: int,
    payload: BillingCustomerIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.user_id == user.id)
        .one_or_none()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    duplicate = (
        db.query(Customer)
        .filter(
            Customer.user_id == user.id,
            func.lower(Customer.email) == str(payload.email).lower(),
            Customer.id != customer.id,
        )
        .one_or_none()
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="A customer with this email already exists.")
    try:
        state, code = normalize_state(payload.state, payload.state_code)
        gstin = normalize_gstin(payload.gstin)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    phone = normalize_phone(payload.phone)
    customer.name = payload.name.strip()
    customer.email = str(payload.email).lower()
    customer.company = _clean(payload.company)
    customer.phone = phone
    customer.gstin = gstin
    customer.billing_address_line1 = _clean(payload.billing_address_line1)
    customer.billing_address_line2 = _clean(payload.billing_address_line2)
    customer.city = _clean(payload.city)
    customer.state = state
    customer.state_code = code
    customer.postal_code = _clean(payload.postal_code)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.customer_updated",
        entity_type="customer",
        entity_id=customer.id,
        detail={"name": customer.name, "phone_set": bool(phone)},
    )
    db.commit()
    db.refresh(customer)
    return {"item": customer_to_dict(customer)}


@router.get("/billing/next-number")
def next_invoice_number(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"number": _next_number(db, user.id)}


@router.get("/billing/invoices")
def list_billing_invoices(
    q: str | None = Query(default=None, max_length=100),
    status_filter: str = Query(default="all", alias="status"),
    limit: int = Query(default=200, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Invoice).join(Customer).filter(Invoice.user_id == user.id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Invoice.number.ilike(needle),
                Invoice.customer_name.ilike(needle),
                Customer.name.ilike(needle),
                Customer.company.ilike(needle),
            )
        )
    invoices = query.order_by(Invoice.issue_date.desc(), Invoice.id.desc()).limit(limit).all()
    items = [_serialize_invoice(invoice, db) for invoice in invoices]
    if status_filter != "all":
        if status_filter == "outstanding":
            items = [item for item in items if item["outstanding"] > 0 and item["status"] != "void"]
        else:
            items = [item for item in items if item["status"] == status_filter]
    return {"items": items, "count": len(items)}


@router.get("/billing/invoices/{invoice_id}")
def get_billing_invoice(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = _owned_invoice(db, user, invoice_id)
    return _serialize_invoice(invoice, db)


@router.post("/billing/calculate")
def calculate_invoice(
    payload: GSTCalculateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    supplier = _supplier_snapshot(user.profile)
    try:
        pos_name, pos_code = normalize_state(
            payload.place_of_supply_state, payload.place_of_supply_state_code
        )
        if not pos_code:
            raise GSTValidationError(
                "Place of supply is required. Confirm the customer's state before calculating."
            )
        supply_type = resolve_supply_type(supplier["state_code"], pos_code)
        calc_lines, metadata = _prepare_lines(
            db, user, payload, supply_type, payload.pricing_mode
        )
        totals = invoice_totals(
            calc_lines,
            supply_type=supply_type,
            other_charges=payload.other_charges,
            round_to_rupee=payload.round_to_rupee,
        )
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    db.commit()
    warnings = []
    if any(not row["hsn_sac"] for row in metadata):
        warnings.append("One or more lines have no HSN/SAC. Confirm the classification before issuing.")
    if not supplier["gstin"]:
        warnings.append("No business GSTIN is saved. Leave it blank only if this is not a GST tax invoice.")
    return {
        "supplier": supplier,
        "place_of_supply": {"state": pos_name, "state_code": pos_code},
        "supply_type": supply_type,
        "supply_type_label": supply_type_label(supply_type),
        "pricing_mode": payload.pricing_mode,
        "lines": [
            {**meta, **calc}
            for meta, calc in zip(metadata, totals.pop("lines"), strict=True)
        ],
        "totals": totals,
        "warnings": warnings,
        "note": "Calculated by the backend with Decimal precision. Nothing was saved.",
    }


@router.post("/billing/invoices", status_code=201)
def create_billing_invoice(
    payload: GSTInvoiceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_confirmation(payload)
    supplier = _supplier_snapshot(user.profile)
    customer = _resolve_customer(db, user, payload)
    customer_snapshot = _customer_snapshot(customer)
    pos_name, pos_code = _place_of_supply(payload)
    try:
        supply_type = resolve_supply_type(supplier["state_code"], pos_code)
        calc_lines, metadata = _prepare_lines(
            db, user, payload, supply_type, payload.pricing_mode
        )
        totals = invoice_totals(
            calc_lines,
            supply_type=supply_type,
            other_charges=payload.other_charges,
            round_to_rupee=payload.round_to_rupee,
        )
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    number = _clean(payload.number) or _next_number(db, user.id)
    existing = (
        db.query(Invoice)
        .filter(Invoice.user_id == user.id, Invoice.number == number)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Invoice number already exists.")
    invoice = Invoice(
        user_id=user.id,
        created_by_user_id=user.id,
        customer_id=customer.id,
        number=number,
        issue_date=payload.issue_date,
        due_date=payload.due_date,
        currency=user.profile.currency,
        status=payload.status,
        notes=_clean(payload.notes),
        terms=_clean(payload.terms) or _clean(user.profile.invoice_terms),
        supply_verified=True,
        supplier_name=supplier["name"],
        supplier_gstin=supplier["gstin"],
        supplier_address=supplier["address"],
        supplier_state=supplier["state"],
        supplier_state_code=supplier["state_code"],
        customer_name=customer_snapshot["name"],
        customer_gstin=customer_snapshot["gstin"],
        customer_phone=customer_snapshot["phone"],
        customer_address=customer_snapshot["address"],
        customer_state=customer_snapshot["state"],
        customer_state_code=customer_snapshot["state_code"],
        place_of_supply_state=pos_name,
        place_of_supply_state_code=pos_code,
    )
    _set_totals(invoice, totals, payload.pricing_mode, supply_type)
    db.add(invoice)
    db.flush()
    _apply_items(db, invoice, metadata, totals["lines"], payload.pricing_mode)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action=f"billing.invoice_{payload.status}",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={
            "number": invoice.number,
            "total": str(invoice.total_amount),
            "taxable_value": str(invoice.taxable_amount),
            "cgst": str(invoice.cgst_amount),
            "sgst": str(invoice.sgst_amount),
            "igst": str(invoice.igst_amount),
            "supply_type": supply_type,
        },
    )
    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice, db)


@router.put("/billing/invoices/{invoice_id}")
def update_billing_invoice(
    invoice_id: int,
    payload: GSTInvoiceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = _owned_invoice(db, user, invoice_id)
    if invoice.status == "void":
        raise HTTPException(status_code=409, detail="A void invoice cannot be edited.")
    _require_confirmation(payload)
    supplier = _supplier_snapshot(user.profile)
    customer = _resolve_customer(db, user, payload)
    customer_snapshot = _customer_snapshot(customer)
    pos_name, pos_code = _place_of_supply(payload)
    try:
        supply_type = resolve_supply_type(supplier["state_code"], pos_code)
        calc_lines, metadata = _prepare_lines(
            db, user, payload, supply_type, payload.pricing_mode
        )
        totals = invoice_totals(
            calc_lines,
            supply_type=supply_type,
            other_charges=payload.other_charges,
            round_to_rupee=payload.round_to_rupee,
        )
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    paid = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
        .scalar()
    )
    if paid > 0 and totals["total_amount"] < paid:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The revised total {totals['total_amount']} is below the {paid} already recorded as paid. "
                "Refund or adjust the payment first."
            ),
        )
    number = _clean(payload.number) or invoice.number
    duplicate = (
        db.query(Invoice)
        .filter(
            Invoice.user_id == user.id,
            Invoice.number == number,
            Invoice.id != invoice.id,
        )
        .one_or_none()
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Invoice number already exists.")
    invoice.number = number
    invoice.customer_id = customer.id
    invoice.issue_date = payload.issue_date
    invoice.due_date = payload.due_date
    invoice.notes = _clean(payload.notes)
    invoice.terms = _clean(payload.terms) or _clean(user.profile.invoice_terms)
    invoice.supply_verified = True
    invoice.supplier_name = supplier["name"]
    invoice.supplier_gstin = supplier["gstin"]
    invoice.supplier_address = supplier["address"]
    invoice.supplier_state = supplier["state"]
    invoice.supplier_state_code = supplier["state_code"]
    invoice.customer_name = customer_snapshot["name"]
    invoice.customer_gstin = customer_snapshot["gstin"]
    invoice.customer_phone = customer_snapshot["phone"]
    invoice.customer_address = customer_snapshot["address"]
    invoice.customer_state = customer_snapshot["state"]
    invoice.customer_state_code = customer_snapshot["state_code"]
    invoice.place_of_supply_state = pos_name
    invoice.place_of_supply_state_code = pos_code
    if invoice.status in ("draft", "issued"):
        invoice.status = payload.status
    _set_totals(invoice, totals, payload.pricing_mode, supply_type)
    _apply_items(db, invoice, metadata, totals["lines"], payload.pricing_mode)
    db.flush()
    if invoice.status not in ("draft", "void"):
        from ..services.payments import refresh_invoice_status

        refresh_invoice_status(db, invoice)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.invoice_updated",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={
            "number": invoice.number,
            "total": str(invoice.total_amount),
            "status": invoice.status,
            "supply_type": supply_type,
        },
    )
    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice, db)


@router.post("/billing/invoices/{invoice_id}/void")
def void_billing_invoice(
    invoice_id: int,
    payload: ConfirmIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = _owned_invoice(db, user, invoice_id)
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")
    if invoice.status == "void":
        raise HTTPException(status_code=409, detail="Invoice is already void.")
    paid = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
        .scalar()
    )
    if paid > 0:
        raise HTTPException(
            status_code=409,
            detail="A void requires no confirmed payments. Refund or reverse the payments first.",
        )
    invoice.status = "void"
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.invoice_voided",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={"number": invoice.number},
    )
    db.commit()
    return _serialize_invoice(invoice, db)


@router.get("/billing/invoices/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoice = _owned_invoice(db, user, invoice_id)
    content = build_invoice_pdf(db, invoice, logo_data_url=user.profile.logo_data_url)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{invoice.number}.pdf")
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="billing.invoice_pdf_downloaded",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={"number": invoice.number},
    )
    db.commit()
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
