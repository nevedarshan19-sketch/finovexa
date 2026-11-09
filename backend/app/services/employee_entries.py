from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import (
    Customer,
    EmployeeEntry,
    Expense,
    InventoryItem,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
    Supplier,
    User,
    utcnow,
)
from ..schemas import EmployeeEntryIn, EmployeeEntryUpdateIn
from ..services.audit import log_audit
from ..services.contacts import normalize_phone
from ..services.credit import normalize_name
from ..services.finance import (
    collection_status,
    payment_method_label,
    payment_state,
    payment_status_label,
    q2,
)
from ..services.gst_catalogue import effective_gst_rate
from ..services.payments import flag_overpayment_review, record_payment

PLACEHOLDER_EMAIL_DOMAIN = "@employee-entry.local"


@dataclass
class EntryLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    product_id: int | None
    gst_rate: Decimal | None = None
    hsn_sac: str | None = None
    item_type: str = "goods"
    unit: str = "pcs"


def _confirmed_payments(db: Session, entry: EmployeeEntry) -> list[Payment]:
    if entry.invoice_id is None:
        return []
    return (
        db.query(Payment)
        .filter(Payment.invoice_id == entry.invoice_id, Payment.status == "confirmed")
        .all()
    )


def _next_reference(db: Session, owner_id: int, prefix: str, entry_date: date) -> str:
    stem = f"{prefix}-{entry_date:%Y%m%d}"
    used = {
        row[0]
        for row in db.query(EmployeeEntry.reference)
        .filter(EmployeeEntry.owner_id == owner_id, EmployeeEntry.reference.like(f"{stem}-%"))
        .all()
    }
    seq = 1
    while f"{stem}-{seq:03d}" in used:
        seq += 1
    return f"{stem}-{seq:03d}"


def _next_invoice_number(db: Session, owner_id: int, issue_date: date) -> str:
    stem = f"INV-{issue_date:%Y%m%d}"
    existing = {
        row[0]
        for row in db.query(Invoice.number)
        .filter(Invoice.user_id == owner_id, Invoice.number.like(f"{stem}-%"))
        .all()
    }
    seq = 1
    while f"{stem}-{seq:03d}" in existing:
        seq += 1
    return f"{stem}-{seq:03d}"


def _ensure_customer(
    db: Session, owner: User, name: str, email: str | None, phone: str | None = None
) -> Customer:
    clean_name = name.strip()
    clean_email = email.strip().lower() if email else None
    clean_phone = normalize_phone(phone)
    existing = (
        db.query(Customer)
        .filter(Customer.user_id == owner.id, func.lower(Customer.name) == clean_name.lower())
        .order_by(Customer.id.asc())
        .first()
    )
    digest = hashlib.sha256(clean_name.lower().encode("utf-8")).hexdigest()[:10]
    fallback_email = f"customer-{digest}{PLACEHOLDER_EMAIL_DOMAIN}"
    if existing is not None:
        if clean_email and existing.email != clean_email:
            existing.email = clean_email
        if clean_phone and existing.phone != clean_phone:
            existing.phone = clean_phone
        db.flush()
        return existing
    customer = Customer(
        user_id=owner.id,
        name=clean_name,
        email=clean_email or fallback_email,
        company=None,
        phone=clean_phone,
    )
    db.add(customer)
    db.flush()
    return customer


def _match_supplier(db: Session, owner: User, name: str) -> Supplier | None:
    """Link a purchase to an existing supplier only when the name is unambiguous."""
    normalized = normalize_name(name)
    if not normalized:
        return None
    matches = (
        db.query(Supplier)
        .filter(Supplier.user_id == owner.id, Supplier.normalized_name == normalized)
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def _customer_email(customer: Customer | None) -> str | None:
    if customer is None or customer.email.endswith(PLACEHOLDER_EMAIL_DOMAIN):
        return None
    return customer.email


def _apply_customer_snapshot(invoice: Invoice, customer: Customer) -> None:
    invoice.customer_id = customer.id
    invoice.customer_name = customer.name
    invoice.customer_gstin = customer.gstin
    invoice.customer_phone = customer.phone
    invoice.customer_address = " · ".join(
        part
        for part in (
            customer.billing_address_line1,
            customer.billing_address_line2,
            customer.city,
            customer.postal_code,
        )
        if part
    ) or None
    invoice.customer_state = customer.state
    invoice.customer_state_code = customer.state_code
    invoice.place_of_supply_state = customer.state
    invoice.place_of_supply_state_code = customer.state_code


def _resolve_product(
    db: Session, owner_id: int, product_id: int | None, description: str
) -> Product | None:
    if product_id is not None:
        product = (
            db.query(Product)
            .filter(Product.id == product_id, Product.user_id == owner_id)
            .one_or_none()
        )
        if product is not None:
            return product
    name = description.strip()
    if not name:
        return None
    return (
        db.query(Product)
        .filter(
            Product.user_id == owner_id,
            or_(func.lower(Product.name) == name.lower(), func.lower(Product.sku) == name.lower()),
        )
        .order_by(Product.id.asc())
        .first()
    )


def _stock_units(product: Product, quantity: Decimal) -> int:
    units = q2(quantity)
    if units != units.to_integral_value():
        raise HTTPException(
            status_code=400,
            detail=(
                f"{product.name} is tracked in whole units. "
                "Round its quantity to a whole number."
            ),
        )
    return int(units)


def _row_product_id(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _apply_stock(db: Session, owner_id: int, rows: list[dict], sign: int) -> list[dict]:
    """Move catalogue stock for the entry lines; +1 buys in, -1 sells out.

    Lines that do not map to a catalogue product are ignored so free-text
    expenses such as rent or marketing keep working.
    """
    totals: dict[int, tuple[Product, int]] = {}
    for row in rows:
        product = _resolve_product(
            db,
            owner_id,
            _row_product_id(row.get("product_id")),
            str(row.get("description", "")),
        )
        if product is None:
            continue
        units = _stock_units(product, Decimal(str(row.get("quantity", "0"))))
        _, running = totals.get(product.id, (product, 0))
        totals[product.id] = (product, running + sign * units)
    changes = []
    for product, delta in totals.values():
        if delta == 0:
            continue
        inventory = product.inventory
        if inventory is None:
            inventory = InventoryItem(product_id=product.id, quantity_on_hand=0)
            db.add(inventory)
            product.inventory = inventory
        before = inventory.quantity_on_hand or 0
        inventory.quantity_on_hand = before + delta
        changes.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "delta": delta,
                "quantity_on_hand": inventory.quantity_on_hand,
            }
        )
    db.flush()
    return changes


def _line_gst_rate(
    db: Session, product: Product | None, item, fallback: Decimal, on_date: date
) -> Decimal:
    if product is not None:
        return q2(effective_gst_rate(db, product, on_date))
    if getattr(item, "gst_rate", None) is not None:
        return q2(item.gst_rate)
    return q2(fallback)


def _build_lines(
    db: Session,
    owner: User,
    payload: EmployeeEntryIn,
    amount: Decimal | None,
    on_date: date,
) -> list[EntryLine]:
    if payload.items:
        lines = []
        for item in payload.items:
            product = _resolve_product(db, owner.id, item.product_id, item.description)
            lines.append(
                EntryLine(
                    description=item.description.strip(),
                    quantity=q2(item.quantity),
                    unit_price=q2(item.unit_price),
                    line_total=q2(item.quantity * item.unit_price),
                    product_id=product.id if product else None,
                    gst_rate=_line_gst_rate(db, product, item, payload.tax_rate, on_date),
                    hsn_sac=product.hsn_sac if product else None,
                    item_type=product.item_type if product else "goods",
                    unit=product.unit if product else "pcs",
                )
            )
        return lines
    if amount is None:
        raise HTTPException(status_code=400, detail="Provide an amount or at least one line item.")
    description = payload.description.strip()
    product = _resolve_product(db, owner.id, None, description)
    base = q2(amount)
    return [
        EntryLine(
            description=description,
            quantity=Decimal("1"),
            unit_price=base,
            line_total=base,
            product_id=product.id if product else None,
            gst_rate=_line_gst_rate(db, product, None, payload.tax_rate, on_date),
            hsn_sac=product.hsn_sac if product else None,
            item_type=product.item_type if product else "goods",
            unit=product.unit if product else "pcs",
        )
    ]


def _stored_line_rows(db: Session, owner_id: int, items) -> list[dict]:
    rows = []
    for item in items:
        product = _resolve_product(db, owner_id, item.product_id, item.description)
        rows.append(
            {
                "description": item.description.strip(),
                "quantity": str(q2(item.quantity)),
                "unit_price": str(q2(item.unit_price)),
                "line_total": str(q2(item.quantity * item.unit_price)),
                "product_id": product.id if product else None,
            }
        )
    return rows


def _invoice_stock_rows(items) -> list[dict]:
    return [
        {
            "description": item.description,
            "quantity": str(item.quantity),
            "product_id": item.product_id,
        }
        for item in items
    ]


def _line_stock_rows(lines: list[EntryLine]) -> list[dict]:
    return [
        {"description": line.description, "quantity": str(line.quantity), "product_id": line.product_id}
        for line in lines
    ]


def _line_rows_total(rows: list[dict[str, str]]) -> Decimal:
    return q2(sum((Decimal(row["line_total"]) for row in rows), Decimal("0.00")))


def _line_rows_summary(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    parts = [
        f"{row['description']} × {Decimal(row['quantity']):g} @ {Decimal(row['unit_price']):g}"
        for row in rows[:8]
    ]
    if len(rows) > 8:
        parts.append(f"+{len(rows) - 8} more")
    return "Items: " + "; ".join(parts)


def _stored_items(entry: EmployeeEntry) -> list[dict]:
    items = []
    for index, row in enumerate(entry.line_items or []):
        quantity = Decimal(str(row.get("quantity", "1")))
        unit_price = Decimal(str(row.get("unit_price", "0")))
        line_total = Decimal(str(row.get("line_total", quantity * unit_price)))
        items.append(
            {
                "id": index + 1,
                "description": str(row.get("description", "")),
                "quantity": q2(quantity),
                "unit_price": q2(unit_price),
                "line_total": q2(line_total),
                "product_id": _row_product_id(row.get("product_id")),
                "hsn_sac": row.get("hsn_sac"),
                "gst_rate": q2(Decimal(str(row.get("gst_rate", "0")))),
                "taxable_value": q2(line_total),
                "cgst_amount": q2(0),
                "sgst_amount": q2(0),
                "igst_amount": q2(0),
                "gst_amount": q2(0),
                "final_amount": q2(line_total),
            }
        )
    return items


def _gst_components(amount: Decimal, rate: Decimal, supply_type: str) -> dict:
    gst = q2(amount * rate / Decimal("100"))
    if supply_type == "intra_state":
        cgst = q2(gst / 2)
        sgst = q2(gst - cgst)
        igst = q2(0)
    elif supply_type == "inter_state":
        cgst = q2(0)
        sgst = q2(0)
        igst = gst
    else:
        cgst = q2(0)
        sgst = q2(0)
        igst = q2(0)
    return {
        "gst": gst,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "final": q2(amount + gst),
    }


def _supply_type(owner: User, customer: Customer) -> str:
    supplier_code = owner.profile.state_code if owner.profile else None
    place_code = customer.state_code
    if supplier_code and place_code:
        return "intra_state" if supplier_code == place_code else "inter_state"
    return "unverified"


def _write_invoice_items(
    db: Session,
    invoice: Invoice,
    lines: list[EntryLine],
    tax_rate: Decimal,
) -> dict:
    for item in list(invoice.items):
        db.delete(item)
    db.flush()
    subtotal = q2(0)
    gst_total = q2(0)
    cgst_total = q2(0)
    sgst_total = q2(0)
    igst_total = q2(0)
    for line in lines:
        subtotal = q2(subtotal + line.line_total)
        rate = q2(line.gst_rate) if line.gst_rate is not None else q2(tax_rate)
        components = _gst_components(line.line_total, rate, invoice.supply_type)
        gst_total = q2(gst_total + components["gst"])
        cgst_total = q2(cgst_total + components["cgst"])
        sgst_total = q2(sgst_total + components["sgst"])
        igst_total = q2(igst_total + components["igst"])
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                product_id=line.product_id,
                name=line.description,
                description=line.description,
                hsn_sac=line.hsn_sac,
                unit=line.unit,
                item_type=line.item_type,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_amount=q2(0),
                line_total=line.line_total,
                taxable_value=line.line_total,
                gst_rate=rate,
                cgst_amount=components["cgst"],
                sgst_amount=components["sgst"],
                igst_amount=components["igst"],
                gst_amount=components["gst"],
                final_amount=components["final"],
                pricing_mode="exclusive",
            )
        )
    return {
        "subtotal": subtotal,
        "discount": q2(0),
        "taxable_value": subtotal,
        "cgst": cgst_total,
        "sgst": sgst_total,
        "igst": igst_total,
        "tax": gst_total,
    }


def entry_to_dict(db: Session, entry: EmployeeEntry) -> dict:
    invoice = entry.invoice
    if invoice is not None:
        items = [
            {
                "id": item.id,
                "description": item.description,
                "quantity": q2(item.quantity),
                "unit_price": q2(item.unit_price),
                "line_total": q2(item.line_total),
                "product_id": item.product_id,
                "hsn_sac": item.hsn_sac,
                "gst_rate": q2(item.gst_rate),
                "taxable_value": q2(item.taxable_value),
                "cgst_amount": q2(item.cgst_amount),
                "sgst_amount": q2(item.sgst_amount),
                "igst_amount": q2(item.igst_amount),
                "gst_amount": q2(item.gst_amount),
                "final_amount": q2(item.final_amount),
            }
            for item in db.query(InvoiceItem)
            .filter(InvoiceItem.invoice_id == invoice.id)
            .order_by(InvoiceItem.id.asc())
            .all()
        ]
    else:
        items = _stored_items(entry)
    confirmed_payments = _confirmed_payments(db, entry)
    latest_payment = (
        max(confirmed_payments, key=lambda row: (row.received_at or row.created_at, row.id))
        if confirmed_payments
        else None
    )
    paid = sum((payment.amount for payment in confirmed_payments), Decimal("0.00"))
    outstanding = (
        Decimal("0.00")
        if invoice is not None and invoice.status == "void"
        else q2(max(invoice.total_amount - paid, Decimal("0.00")))
        if invoice is not None
        else None
    )
    locked = entry.status != "void" and bool(confirmed_payments)
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "status": entry.status,
        "reference": entry.reference,
        "counterparty": entry.counterparty,
        "counterparty_email": _customer_email(invoice.customer) if invoice else None,
        "counterparty_phone": (
            invoice.customer_phone or (invoice.customer.phone if invoice.customer else None)
        )
        if invoice
        else None,
        "description": entry.description,
        "category": entry.category,
        "amount": q2(entry.amount),
        "currency": entry.currency,
        "tax_rate": q2(entry.tax_rate),
        "payment_method": entry.payment_method,
        "entry_date": entry.entry_date.isoformat(),
        "due_date": entry.due_date.isoformat() if entry.due_date else None,
        "notes": entry.notes,
        "invoice_id": entry.invoice_id,
        "invoice_number": invoice.number if invoice else None,
        "invoice_status": invoice.status if invoice else None,
        "invoice_total": q2(invoice.total_amount) if invoice else None,
        "invoice_paid": q2(paid),
        "invoice_outstanding": outstanding,
        "amount_received": (
            q2(paid) if invoice is not None else entry.amount_received
        ),
        "collection_status": collection_status(invoice, paid) if invoice else None,
        "payment_state": payment_state(invoice, paid) if invoice else None,
        "payment_status_label": payment_status_label(payment_state(invoice, paid))
        if invoice
        else None,
        "overpaid_amount": (
            q2(max(paid - invoice.total_amount, Decimal("0.00"))) if invoice else q2(0)
        ),
        "payment_count": len(confirmed_payments) if invoice else 0,
        "payment_method_label": payment_method_label(
            latest_payment.method if latest_payment else entry.payment_method
        ),
        "payment_reference": (
            latest_payment.provider_ref if latest_payment else None
        ),
        "payment_date": (
            (latest_payment.received_at or latest_payment.created_at).date().isoformat()
            if latest_payment
            else None
        ),
        "assigned_employee_id": invoice.assigned_employee_id if invoice else None,
        "expense_id": entry.expense_id,
        "items": items,
        "payment_id": entry.payment_id,
        "payment": {
            "id": entry.payment.id,
            "amount": q2(entry.payment.amount),
            "method": entry.payment.method,
            "method_label": payment_method_label(entry.payment.method),
            "status": entry.payment.status,
            "provider": entry.payment.provider,
            "provider_ref": entry.payment.provider_ref,
            "received_at": entry.payment.received_at,
        }
        if entry.payment
        else None,
        "employee": {
            "id": entry.employee.id,
            "name": entry.employee.full_name,
            "email": entry.employee.email,
        },
        "editable": entry.status != "void" and not locked,
        "voidable": entry.status != "void" and not locked,
        "lock_reason": (
            "Confirmed cash is attached to this entry. Ask the owner to reverse the payment."
            if locked
            else None
        ),
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "voided_at": entry.voided_at,
    }


def entry_totals(entries: list[EmployeeEntry]) -> dict:
    submitted = [entry for entry in entries if entry.status != "void"]
    sales = [entry for entry in submitted if entry.entry_type in ("invoice", "sale")]
    purchases = [entry for entry in submitted if entry.entry_type == "purchase"]
    return {
        "total_entries": len(entries),
        "submitted": len(submitted),
        "voided": len([entry for entry in entries if entry.status == "void"]),
        "sales_total": q2(sum((entry.amount for entry in sales), Decimal("0.00"))),
        "purchases_total": q2(sum((entry.amount for entry in purchases), Decimal("0.00"))),
        "invoice_count": len([entry for entry in sales if entry.entry_type == "invoice"]),
        "sale_count": len([entry for entry in sales if entry.entry_type == "sale"]),
        "purchase_count": len(purchases),
        "last_entry_at": entries[0].created_at if entries else None,
    }


def create_employee_entry(
    db: Session,
    *,
    owner: User,
    employee: User,
    payload: EmployeeEntryIn,
) -> EmployeeEntry:
    if owner.profile is None:
        raise HTTPException(status_code=409, detail="The business profile is incomplete.")
    currency = owner.profile.currency
    entry = EmployeeEntry(
        owner_id=owner.id,
        employee_id=employee.id,
        entry_type=payload.entry_type,
        status="submitted",
        reference="pending",
        counterparty=payload.counterparty.strip(),
        description=payload.description.strip(),
        category=payload.category.strip() if payload.category else None,
        amount=q2(0),
        currency=currency,
        tax_rate=q2(payload.tax_rate),
        payment_method=payload.payment_method,
        entry_date=payload.entry_date,
        due_date=payload.due_date,
        notes=payload.notes,
    )
    stock_changes: list[dict] = []

    if payload.entry_type == "purchase":
        line_rows = _stored_line_rows(db, owner.id, payload.items)
        amount = (
            _line_rows_total(line_rows)
            if line_rows
            else q2(payload.amount or Decimal("0"))
        )
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Purchase amount must be greater than zero.")
        entry.reference = _next_reference(db, owner.id, "PUR", payload.entry_date)
        entry.amount = amount
        entry.line_items = line_rows
        entry.tax_rate = q2(0)
        supplier = _match_supplier(db, owner, entry.counterparty)
        due_date = payload.due_date
        if due_date is None and supplier is not None and supplier.payment_terms_days:
            due_date = payload.entry_date + timedelta(days=supplier.payment_terms_days)
        entry.due_date = due_date
        stock_changes = _apply_stock(db, owner.id, line_rows, 1)
        expense = Expense(
            user_id=owner.id,
            created_by_user_id=employee.id,
            supplier_id=supplier.id if supplier is not None else None,
            category=entry.category or "Purchases",
            vendor=entry.counterparty,
            amount=amount,
            incurred_on=payload.entry_date,
            due_date=due_date,
            payment_status="unpaid",
            note=" · ".join(
                part
                for part in (
                    entry.description,
                    _line_rows_summary(line_rows),
                    entry.notes or "",
                )
                if part
            ),
        )
        db.add(expense)
        db.flush()
        entry.expense_id = expense.id
    else:
        method = payload.payment_method or ("credit" if payload.entry_type == "invoice" else None)
        if payload.entry_type == "invoice":
            received = q2(payload.amount_received or Decimal("0"))
            method = payload.payment_method if received > 0 else "credit"
        if method is None:
            raise HTTPException(status_code=400, detail="Choose how the sale was paid.")
        if payload.entry_type == "sale" and method == "credit":
            raise HTTPException(
                status_code=400,
                detail="A paid sale needs a payment method. Use an invoice for credit sales.",
            )
        due_date = payload.due_date or (
            payload.entry_date + timedelta(days=30 if payload.entry_type == "invoice" else 14)
        )
        if due_date < payload.entry_date:
            raise HTTPException(status_code=400, detail="Due date cannot be before the entry date.")
        customer = _ensure_customer(
            db,
            owner,
            entry.counterparty,
            str(payload.counterparty_email) if payload.counterparty_email else None,
            payload.counterparty_phone,
        )
        lines = _build_lines(db, owner, payload, payload.amount, payload.entry_date)
        supply_type = _supply_type(owner, customer)
        invoice = Invoice(
            user_id=owner.id,
            created_by_user_id=employee.id,
            number=_next_invoice_number(db, owner.id, payload.entry_date),
            issue_date=payload.entry_date,
            due_date=due_date,
            currency=currency,
            status="issued",
            notes=payload.notes,
            pricing_mode="exclusive",
            supply_type=supply_type,
            supplier_name=owner.profile.legal_name or owner.profile.business_name,
            supplier_gstin=owner.profile.gstin,
            supplier_state=owner.profile.state,
            supplier_state_code=owner.profile.state_code,
            supply_verified=False,
            round_to_rupee=False,
        )
        _apply_customer_snapshot(invoice, customer)
        db.add(invoice)
        db.flush()
        totals = _write_invoice_items(db, invoice, lines, q2(payload.tax_rate))
        stock_changes = _apply_stock(db, owner.id, _line_stock_rows(lines), -1)
        invoice.subtotal_amount = totals["subtotal"]
        invoice.discount_amount = totals["discount"]
        invoice.taxable_amount = totals["taxable_value"]
        invoice.tax_amount = totals["tax"]
        invoice.cgst_amount = totals["cgst"]
        invoice.sgst_amount = totals["sgst"]
        invoice.igst_amount = totals["igst"]
        invoice.total_amount = q2(totals["taxable_value"] + totals["tax"])
        total = invoice.total_amount
        entry.reference = invoice.number
        entry.invoice_id = invoice.id
        entry.amount = total
        entry.due_date = due_date
        entry.payment_method = method
        payment_amount = total
        if payload.entry_type == "invoice":
            payment_amount = q2(payload.amount_received or Decimal("0"))
            entry.amount_received = payment_amount
        if method != "credit":
            note = (
                f"Recorded by employee {employee.full_name} via "
                f"{payment_method_label(method)}. "
                "Employee-recorded receipt, not provider-verified."
            )
            if method == "paypal":
                note = (
                    f"Employee-recorded PayPal receipt by {employee.full_name}. "
                    "No PayPal API capture or webhook verified this payment."
                )
            payment = record_payment(
                db,
                user=owner,
                invoice=invoice,
                amount=payment_amount,
                method=method,
                status="confirmed",
                provider="employee_recorded",
                provider_ref=payload.payment_reference or f"EMP-{employee.id}",
                note=note,
                received_at=(
                    datetime.combine(payload.payment_date, time(12, 0))
                    if payload.payment_date
                    else None
                ),
                actor=employee.email,
                created_by_user_id=employee.id,
                allow_overpayment=True,
                commit=False,
            )
            flag_overpayment_review(
                db,
                user_id=owner.id,
                payment=payment,
                invoice=invoice,
                actor=employee.email,
            )
            entry.payment_id = payment.id

    db.add(entry)
    db.flush()
    log_audit(
        db,
        user_id=owner.id,
        actor=employee.email,
        action="employee.entry_recorded",
        entity_type="employee_entry",
        entity_id=entry.id,
        detail={
            "entry_type": entry.entry_type,
            "reference": entry.reference,
            "amount": str(entry.amount),
            "employee_name": employee.full_name,
            "payment_method": entry.payment_method,
            "stock_changes": stock_changes,
        },
    )
    db.commit()
    db.refresh(entry)
    return entry


def update_employee_entry(
    db: Session,
    *,
    owner: User,
    employee: User,
    entry_id: int,
    payload: EmployeeEntryUpdateIn,
) -> EmployeeEntry:
    entry = (
        db.query(EmployeeEntry)
        .filter(
            EmployeeEntry.id == entry_id,
            EmployeeEntry.owner_id == owner.id,
            EmployeeEntry.employee_id == employee.id,
        )
        .one_or_none()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found.")
    if entry.status == "void":
        raise HTTPException(status_code=409, detail="Voided entries cannot be edited.")
    if owner.profile is None:
        raise HTTPException(status_code=409, detail="The business profile is incomplete.")

    confirmed = _confirmed_payments(db, entry)
    fields = payload.model_dump(exclude_unset=True)
    stock_changes: list[dict] = []

    if entry.entry_type in ("invoice", "sale") and confirmed:
        disallowed = set(fields) - {"notes"}
        if disallowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Confirmed cash is attached to this entry. Only notes can be edited; "
                    "ask the owner to reverse the payment for financial changes."
                ),
            )
        entry.notes = payload.notes
        log_audit(
            db,
            user_id=owner.id,
            actor=employee.email,
            action="employee.entry_edited",
            entity_type="employee_entry",
            entity_id=entry.id,
            detail={"reference": entry.reference, "fields": sorted(fields)},
        )
        db.commit()
        db.refresh(entry)
        return entry

    if entry.entry_type == "purchase":
        expense = entry.expense
        if payload.counterparty is not None:
            entry.counterparty = payload.counterparty.strip()
            if expense:
                expense.vendor = entry.counterparty
                if expense.supplier_id is None:
                    supplier = _match_supplier(db, owner, entry.counterparty)
                    if supplier is not None:
                        expense.supplier_id = supplier.id
        if payload.description is not None:
            entry.description = payload.description.strip()
        if payload.category is not None:
            entry.category = payload.category.strip() or "Purchases"
            if expense:
                expense.category = entry.category
        if payload.items is not None:
            new_rows = _stored_line_rows(db, owner.id, payload.items)
            stock_changes.extend(_apply_stock(db, owner.id, entry.line_items or [], -1))
            stock_changes.extend(_apply_stock(db, owner.id, new_rows, 1))
            entry.line_items = new_rows
            entry.amount = _line_rows_total(new_rows)
            if expense:
                expense.amount = entry.amount
        elif payload.amount is not None:
            stock_changes.extend(_apply_stock(db, owner.id, entry.line_items or [], -1))
            entry.amount = q2(payload.amount)
            entry.line_items = []
            if expense:
                expense.amount = entry.amount
        if entry.amount <= 0:
            raise HTTPException(status_code=400, detail="Purchase amount must be greater than zero.")
        if payload.entry_date is not None:
            entry.entry_date = payload.entry_date
            if expense:
                expense.incurred_on = payload.entry_date
        if payload.due_date is not None:
            entry.due_date = payload.due_date
            if expense:
                expense.due_date = payload.due_date
        if payload.payment_method is not None:
            entry.payment_method = payload.payment_method
        if payload.notes is not None:
            entry.notes = payload.notes
        if expense:
            expense.note = " · ".join(
                part
                for part in (
                    entry.description,
                    _line_rows_summary(entry.line_items),
                    entry.notes or "",
                )
                if part
            )
    else:
        invoice = entry.invoice
        if invoice is None:
            raise HTTPException(status_code=409, detail="The linked invoice is missing.")
        customer_name = payload.counterparty.strip() if payload.counterparty else entry.counterparty
        customer_email = (
            str(payload.counterparty_email)
            if payload.counterparty_email
            else _customer_email(invoice.customer)
        )
        customer = _ensure_customer(
            db,
            owner,
            customer_name,
            customer_email,
            payload.counterparty_phone if "counterparty_phone" in fields else None,
        )
        if "counterparty_phone" in fields and not (payload.counterparty_phone or "").strip():
            customer.phone = None
        _apply_customer_snapshot(invoice, customer)
        invoice.supply_type = _supply_type(owner, customer)
        entry.counterparty = customer_name

        issue_date = payload.entry_date or invoice.issue_date
        due_date = payload.due_date or invoice.due_date
        if due_date < issue_date:
            raise HTTPException(status_code=400, detail="Due date cannot be before the issue date.")
        invoice.issue_date = issue_date
        invoice.due_date = due_date
        entry.entry_date = issue_date
        entry.due_date = due_date

        tax_rate = q2(payload.tax_rate) if payload.tax_rate is not None else q2(entry.tax_rate)
        entry.tax_rate = tax_rate
        lines: list[EntryLine] | None = None
        if payload.items:
            lines = []
            for item in payload.items:
                product = _resolve_product(db, owner.id, item.product_id, item.description)
                lines.append(
                    EntryLine(
                        description=item.description.strip(),
                        quantity=q2(item.quantity),
                        unit_price=q2(item.unit_price),
                        line_total=q2(item.quantity * item.unit_price),
                        product_id=product.id if product else None,
                        gst_rate=_line_gst_rate(db, product, item, tax_rate, issue_date),
                        hsn_sac=product.hsn_sac if product else None,
                        item_type=product.item_type if product else "goods",
                        unit=product.unit if product else "pcs",
                    )
                )
        elif payload.amount is not None or payload.description is not None:
            base_amount = q2(payload.amount) if payload.amount is not None else q2(invoice.subtotal_amount)
            description = (
                payload.description.strip() if payload.description else entry.description
            )
            product = _resolve_product(db, owner.id, None, description)
            lines = [
                EntryLine(
                    description=description,
                    quantity=Decimal("1"),
                    unit_price=base_amount,
                    line_total=base_amount,
                    product_id=product.id if product else None,
                    gst_rate=_line_gst_rate(db, product, None, tax_rate, issue_date),
                    hsn_sac=product.hsn_sac if product else None,
                    item_type=product.item_type if product else "goods",
                    unit=product.unit if product else "pcs",
                )
            ]
        if lines is not None:
            old_items = (
                db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).all()
            )
            stock_changes.extend(_apply_stock(db, owner.id, _invoice_stock_rows(old_items), 1))
            totals = _write_invoice_items(db, invoice, lines, tax_rate)
            stock_changes.extend(_apply_stock(db, owner.id, _line_stock_rows(lines), -1))
            invoice.subtotal_amount = totals["subtotal"]
            invoice.discount_amount = totals["discount"]
            invoice.taxable_amount = totals["taxable_value"]
            invoice.tax_amount = totals["tax"]
            invoice.cgst_amount = totals["cgst"]
            invoice.sgst_amount = totals["sgst"]
            invoice.igst_amount = totals["igst"]
            invoice.total_amount = q2(totals["taxable_value"] + totals["tax"])
            entry.amount = invoice.total_amount
        if payload.description is not None:
            entry.description = payload.description.strip()
        if payload.notes is not None:
            entry.notes = payload.notes
            invoice.notes = payload.notes

        if entry.entry_type == "invoice":
            entry.payment_method = "credit"
        elif payload.payment_method is not None and payload.payment_method != entry.payment_method:
            if payload.payment_method == "credit":
                raise HTTPException(
                    status_code=400,
                    detail="A paid sale needs a payment method. Use an invoice for credit sales.",
                )
            if invoice.outstanding_amount <= 0:
                raise HTTPException(
                    status_code=409, detail="Invoice has no outstanding balance."
                )
            method = payload.payment_method
            note = (
                f"Recorded by employee {employee.full_name} via "
                f"{PAYMENT_LABELS.get(method, method)}. "
                "Employee-recorded receipt, not provider-verified."
            )
            payment = record_payment(
                db,
                user=owner,
                invoice=invoice,
                amount=invoice.outstanding_amount,
                method=method,
                status="confirmed",
                provider="employee_recorded",
                provider_ref=f"EMP-{employee.id}",
                note=note,
                actor=employee.email,
                created_by_user_id=employee.id,
                commit=False,
            )
            entry.payment_id = payment.id
            entry.payment_method = method
        entry.reference = invoice.number

    log_audit(
        db,
        user_id=owner.id,
        actor=employee.email,
        action="employee.entry_edited",
        entity_type="employee_entry",
        entity_id=entry.id,
        detail={
            "reference": entry.reference,
            "fields": sorted(fields),
            "amount": str(entry.amount),
            "stock_changes": stock_changes,
        },
    )
    db.commit()
    db.refresh(entry)
    return entry


def void_employee_entry(
    db: Session, *, owner: User, employee: User, entry_id: int
) -> EmployeeEntry:
    entry = (
        db.query(EmployeeEntry)
        .filter(
            EmployeeEntry.id == entry_id,
            EmployeeEntry.owner_id == owner.id,
            EmployeeEntry.employee_id == employee.id,
        )
        .one_or_none()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found.")
    if entry.status == "void":
        return entry
    if _confirmed_payments(db, entry):
        raise HTTPException(
            status_code=409,
            detail=(
                "Confirmed cash is attached to this entry. Ask the owner to reverse the payment "
                "before voiding."
            ),
        )
    if entry.entry_type == "purchase":
        stock_changes = _apply_stock(db, owner.id, entry.line_items or [], -1)
    else:
        invoice_items = (
            db.query(InvoiceItem).filter(InvoiceItem.invoice_id == entry.invoice_id).all()
            if entry.invoice_id is not None
            else []
        )
        stock_changes = _apply_stock(db, owner.id, _invoice_stock_rows(invoice_items), 1)
    if entry.expense is not None:
        db.delete(entry.expense)
        entry.expense_id = None
    if entry.invoice is not None:
        entry.invoice.status = "void"
    entry.status = "void"
    entry.voided_at = utcnow()
    entry.notes = ((entry.notes or "") + " · Voided by employee").strip(" ·")
    log_audit(
        db,
        user_id=owner.id,
        actor=employee.email,
        action="employee.entry_voided",
        entity_type="employee_entry",
        entity_id=entry.id,
        detail={
            "reference": entry.reference,
            "entry_type": entry.entry_type,
            "amount": str(entry.amount),
            "employee_name": employee.full_name,
            "stock_changes": stock_changes,
        },
    )
    db.commit()
    db.refresh(entry)
    return entry
