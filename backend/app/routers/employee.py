from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EmployeeEntry, Product, User
from ..schemas import EmployeeEntryIn, EmployeeEntryUpdateIn, PaymentRecordIn
from ..security import get_current_employee, rate_limit
from ..services.dues import (
    business_today,
    dues_payload,
    get_collectible_invoice,
    payment_history_payload,
    record_employee_payment,
)
from ..services.employee_entries import (
    create_employee_entry,
    entry_to_dict,
    entry_totals,
    update_employee_entry,
    void_employee_entry,
)
from ..services.finance import invoice_to_dict, payment_to_dict, q2
from ..services.gst_catalogue import effective_gst_rate

router = APIRouter(prefix="/employee", tags=["Employee portal"])


def _owner_for(db: Session, employee: User) -> User:
    owner = db.get(User, employee.owner_id) if employee.owner_id else None
    if owner is None or not owner.is_active or owner.profile is None:
        raise HTTPException(
            status_code=403, detail="This employee account is not attached to an active business."
        )
    return owner


def _employee_payload(employee: User) -> dict:
    return {"id": employee.id, "name": employee.full_name, "email": employee.email}


def _business_payload(owner: User) -> dict:
    profile = owner.profile
    return {
        "business_name": profile.business_name,
        "currency": profile.currency,
        "timezone": profile.timezone,
    }


@router.get("/overview")
def employee_overview(
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    all_entries = (
        db.query(EmployeeEntry)
        .filter(EmployeeEntry.employee_id == employee.id)
        .order_by(EmployeeEntry.created_at.desc(), EmployeeEntry.id.desc())
        .all()
    )
    dues = dues_payload(db, owner=owner, employee=employee, limit=1)
    return {
        "employee": _employee_payload(employee),
        "business": _business_payload(owner),
        "entries": [entry_to_dict(db, entry) for entry in all_entries[:12]],
        "summary": entry_totals(all_entries),
        "collections": {
            "summary": dues["summary"],
            "currency_totals": dues["currency_totals"],
            "as_of": dues["as_of"],
            "timezone": dues["timezone"],
        },
        "permissions": {
            "can_generate_invoices": True,
            "can_edit_entries": True,
            "can_record_payments": True,
            "can_edit_payments": False,
            "can_reverse_payments": False,
            "owner_dashboard": False,
            "owner_api_access": False,
        },
        "note": (
            "You can see only the entries you recorded. Payment edits and reversals are "
            "reserved for the owner. The owner dashboard, cash totals, market data and "
            "approval center are not available to employee accounts."
        ),
        "as_of": date.today().isoformat(),
    }


@router.get("/products")
def employee_products(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=8, ge=1, le=50),
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    query = db.query(Product).filter(Product.user_id == owner.id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            or_(Product.name.ilike(needle), Product.sku.ilike(needle))
        )
    rows = query.order_by(Product.name.asc()).limit(limit).all()
    today = business_today(owner.profile)
    return {
        "items": [
            {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "unit": product.unit,
                "item_type": product.item_type,
                "hsn_sac": product.hsn_sac,
                "gst_rate": q2(effective_gst_rate(db, product, today)),
                "gst_verified": product.gst_verified,
                "unit_price": q2(product.unit_price),
                "quantity_on_hand": (
                    product.inventory.quantity_on_hand if product.inventory else 0
                ),
                "low_stock": (
                    (product.inventory.quantity_on_hand if product.inventory else 0)
                    <= product.reorder_level
                ),
            }
            for product in rows
        ],
        "count": len(rows),
    }


@router.get("/entries")
def list_employee_entries(
    entry_type: str = Query(default="all", pattern=r"^(all|invoice|sale|purchase)$"),
    status_filter: str = Query(default="all", alias="status", pattern=r"^(all|submitted|void)$"),
    limit: int = Query(default=100, ge=1, le=300),
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    query = db.query(EmployeeEntry).filter(EmployeeEntry.employee_id == employee.id)
    if entry_type != "all":
        query = query.filter(EmployeeEntry.entry_type == entry_type)
    if status_filter != "all":
        query = query.filter(EmployeeEntry.status == status_filter)
    entries = query.order_by(EmployeeEntry.created_at.desc(), EmployeeEntry.id.desc()).limit(limit).all()
    all_entries = (
        db.query(EmployeeEntry)
        .filter(EmployeeEntry.employee_id == employee.id)
        .order_by(EmployeeEntry.created_at.desc(), EmployeeEntry.id.desc())
        .all()
    )
    return {
        "items": [entry_to_dict(db, entry) for entry in entries],
        "count": len(entries),
        "summary": entry_totals(all_entries),
    }


@router.get("/entries/{entry_id}")
def get_employee_entry(
    entry_id: int,
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    entry = (
        db.query(EmployeeEntry)
        .filter(EmployeeEntry.id == entry_id, EmployeeEntry.employee_id == employee.id)
        .one_or_none()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return entry_to_dict(db, entry)


@router.post(
    "/entries",
    status_code=201,
    dependencies=[Depends(rate_limit("employee_entry", 60, 60))],
)
def create_entry(
    payload: EmployeeEntryIn,
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    entry = create_employee_entry(db, owner=owner, employee=employee, payload=payload)
    return {
        "entry": entry_to_dict(db, entry),
        "message": (
            "Entry submitted. The owner's ledger and dashboard update automatically."
            if entry.entry_type != "purchase"
            else "Purchase recorded. It is included in the owner's recorded expenses and cash immediately."
        ),
    }


@router.patch("/entries/{entry_id}")
def update_entry(
    entry_id: int,
    payload: EmployeeEntryUpdateIn,
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    entry = update_employee_entry(
        db, owner=owner, employee=employee, entry_id=entry_id, payload=payload
    )
    return {
        "entry": entry_to_dict(db, entry),
        "message": "Entry updated. The owner's ledger reflects the change.",
    }


@router.post("/entries/{entry_id}/void")
def void_entry(
    entry_id: int,
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    entry = void_employee_entry(db, owner=owner, employee=employee, entry_id=entry_id)
    return {
        "entry": entry_to_dict(db, entry),
        "message": (
            "Entry voided. The linked ledger record was reversed."
            if entry.entry_type == "purchase"
            else "Entry voided. The linked invoice is no longer collectible."
        ),
    }


@router.get("/dues")
def employee_dues(
    status_filter: str = Query(
        default="all",
        alias="status",
        pattern=r"^(all|unpaid|partially_paid|due_soon|overdue|paid|disputed)$",
    ),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=200, ge=1, le=500),
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    return dues_payload(
        db,
        owner=owner,
        employee=employee,
        status_filter=status_filter,
        query_text=q,
        limit=limit,
    )


@router.get("/invoices/{invoice_id}/payments")
def employee_invoice_payments(
    invoice_id: int,
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    invoice = get_collectible_invoice(
        db, owner_id=owner.id, employee_id=employee.id, invoice_id=invoice_id
    )
    return payment_history_payload(
        db, invoice=invoice, today=business_today(owner.profile)
    )


@router.post(
    "/invoices/{invoice_id}/payments",
    status_code=201,
    dependencies=[Depends(rate_limit("employee_payment", 60, 60))],
)
def record_invoice_payment(
    invoice_id: int,
    payload: PaymentRecordIn,
    employee: User = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    owner = _owner_for(db, employee)
    payment, invoice = record_employee_payment(
        db,
        owner=owner,
        employee=employee,
        invoice_id=invoice_id,
        payload=payload,
    )
    invoice_data = invoice_to_dict(db, invoice, include_items=False)
    return {
        "payment": payment_to_dict(payment),
        "invoice": invoice_data,
        "message": (
            f"Payment recorded. {invoice.number} is "
            f"{invoice_data['payment_status_label']} · "
            f"{invoice.outstanding_amount} {invoice.currency} remaining."
        ),
    }

