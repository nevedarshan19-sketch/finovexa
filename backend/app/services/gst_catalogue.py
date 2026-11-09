"""GST catalogue governance.

The product catalogue is the single source of truth for a line's GST rate and
HSN/SAC. Changes are effective-dated, audited and optionally require the owner
to approve an accountant's proposal. Issued invoices are untouched: every
``InvoiceItem`` keeps the rate and tax amounts that were stored when it was
issued.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import GstCatalogueChange, Product, User, utcnow
from .audit import log_audit
from .finance import q2
from .gst import GSTValidationError, validate_configured_rate

APPROVAL_MODES = {"direct", "owner_approval"}
APPLIED_STATUSES = ("applied", "approved")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _owner(db: Session, owner_id: int) -> User:
    owner = db.get(User, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Catalogue owner not found.")
    return owner


def approval_mode(db: Session, owner: User) -> str:
    profile = owner.profile
    mode = profile.gst_change_approval if profile else "direct"
    return mode if mode in APPROVAL_MODES else "direct"


def set_approval_mode(db: Session, owner: User, mode: str) -> dict:
    if mode not in APPROVAL_MODES:
        raise HTTPException(status_code=400, detail="Approval mode must be direct or owner_approval.")
    profile = owner.profile
    if profile is None:
        raise HTTPException(status_code=409, detail="The business profile is incomplete.")
    previous = profile.gst_change_approval
    profile.gst_change_approval = mode
    log_audit(
        db,
        user_id=owner.id,
        actor="owner",
        action="gst.catalogue.approval_mode_changed",
        entity_type="business_profile",
        entity_id=profile.id,
        detail={"previous": previous, "current": mode},
    )
    db.commit()
    return {"approval_mode": mode}


def _validated_rate(db: Session, owner: User, value: Decimal) -> Decimal:
    try:
        return q2(validate_configured_rate(db, owner, value))
    except GSTValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _person(db: Session, user_id: int | None) -> dict | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None:
        return None
    return {"id": user.id, "name": user.full_name, "role": user.role}


def change_to_dict(db: Session, change: GstCatalogueChange) -> dict:
    product = change.product
    return {
        "id": change.id,
        "product_id": change.product_id,
        "product_name": product.name if product else None,
        "sku": product.sku if product else None,
        "old_gst_rate": q2(change.old_gst_rate),
        "new_gst_rate": q2(change.new_gst_rate),
        "old_hsn_sac": change.old_hsn_sac,
        "new_hsn_sac": change.new_hsn_sac,
        "old_item_type": change.old_item_type,
        "new_item_type": change.new_item_type,
        "old_hsn_verified": change.old_hsn_verified,
        "new_hsn_verified": change.new_hsn_verified,
        "effective_from": change.effective_from.isoformat() if change.effective_from else None,
        "reason": change.reason,
        "status": change.status,
        "requested_by": _person(db, change.requested_by_user_id),
        "requested_by_role": change.requested_by_role,
        "decided_by": _person(db, change.decided_by_user_id),
        "decided_at": change.decided_at,
        "decision_note": change.decision_note,
        "created_at": change.created_at,
    }


def _pending(db: Session, product_id: int) -> GstCatalogueChange | None:
    return (
        db.query(GstCatalogueChange)
        .filter(
            GstCatalogueChange.product_id == product_id,
            GstCatalogueChange.status == "pending_approval",
        )
        .order_by(GstCatalogueChange.created_at.desc())
        .first()
    )


def product_to_dict(
    db: Session, product: Product, pending: GstCatalogueChange | None = None
) -> dict:
    if pending is None:
        pending = _pending(db, product.id)
    updated_by = _person(db, product.gst_updated_by_user_id)
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "hsn_sac": product.hsn_sac,
        "item_type": product.item_type,
        "unit": product.unit,
        "gst_rate": q2(product.default_gst_rate),
        "gst_effective_from": (
            product.gst_effective_from.isoformat() if product.gst_effective_from else None
        ),
        "gst_verified": product.gst_verified,
        "gst_change_reason": product.gst_change_reason,
        "gst_updated_by": updated_by,
        "gst_updated_at": product.updated_at,
        "unit_price": q2(product.unit_price),
        "unit_cost": q2(product.unit_cost),
        "quantity_on_hand": product.inventory.quantity_on_hand if product.inventory else 0,
        "low_stock": (product.inventory.quantity_on_hand if product.inventory else 0)
        <= product.reorder_level,
        "pending_change": change_to_dict(db, pending) if pending else None,
    }


def catalogue_rows(
    db: Session,
    owner_id: int,
    *,
    search: str | None = None,
    limit: int = 300,
) -> list[dict]:
    query = db.query(Product).filter(Product.user_id == owner_id)
    if search and search.strip():
        needle = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(needle),
                Product.sku.ilike(needle),
                Product.hsn_sac.ilike(needle),
            )
        )
    products = query.order_by(Product.name.asc()).limit(limit).all()
    pending = {
        row.product_id: row
        for row in db.query(GstCatalogueChange)
        .filter(
            GstCatalogueChange.owner_user_id == owner_id,
            GstCatalogueChange.status == "pending_approval",
        )
        .order_by(GstCatalogueChange.created_at.desc())
        .all()
    }
    return [product_to_dict(db, product, pending.get(product.id)) for product in products]


def pending_changes(db: Session, owner_id: int) -> list[dict]:
    rows = (
        db.query(GstCatalogueChange)
        .filter(
            GstCatalogueChange.owner_user_id == owner_id,
            GstCatalogueChange.status == "pending_approval",
        )
        .order_by(GstCatalogueChange.created_at.asc())
        .all()
    )
    return [change_to_dict(db, row) for row in rows]


def history(
    db: Session,
    owner_id: int,
    *,
    product_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    query = db.query(GstCatalogueChange).filter(GstCatalogueChange.owner_user_id == owner_id)
    if product_id is not None:
        query = query.filter(GstCatalogueChange.product_id == product_id)
    rows = query.order_by(GstCatalogueChange.created_at.desc()).limit(limit).all()
    return [change_to_dict(db, row) for row in rows]


def _apply_change(product: Product, change: GstCatalogueChange, actor_id: int | None) -> None:
    product.default_gst_rate = change.new_gst_rate
    if change.new_hsn_sac is not None or change.old_hsn_sac != change.new_hsn_sac:
        product.hsn_sac = change.new_hsn_sac
    if change.new_item_type:
        product.item_type = change.new_item_type
    if change.new_hsn_verified is not None:
        product.gst_verified = change.new_hsn_verified
    product.gst_effective_from = change.effective_from or date.today()
    product.gst_change_reason = change.reason
    product.gst_updated_by_user_id = actor_id


def request_change(
    db: Session,
    *,
    product: Product,
    actor: User,
    role: str,
    gst_rate: Decimal | None = None,
    hsn_sac: str | None = None,
    item_type: str | None = None,
    hsn_verified: bool | None = None,
    effective_from: date | None = None,
    reason: str,
) -> GstCatalogueChange:
    """Apply an owner edit, or queue an accountant proposal for owner approval."""
    owner = _owner(db, product.user_id)
    clean_reason = reason.strip()
    if len(clean_reason) < 3:
        raise HTTPException(status_code=400, detail="Give a reason for the GST catalogue change.")
    new_rate = (
        _validated_rate(db, owner, gst_rate)
        if gst_rate is not None
        else q2(product.default_gst_rate)
    )
    new_hsn = _clean(hsn_sac) if hsn_sac is not None else product.hsn_sac
    new_type = item_type if item_type is not None else product.item_type
    if new_type not in {"goods", "services", "service"}:
        raise HTTPException(status_code=400, detail="Item type must be goods or services.")
    new_verified = hsn_verified if hsn_verified is not None else product.gst_verified
    if hsn_sac is not None and _clean(hsn_sac) != product.hsn_sac and hsn_verified is None:
        # A new HSN/SAC starts unverified until an accountant checks the notification.
        new_verified = False
    if (
        new_rate == q2(product.default_gst_rate)
        and new_hsn == product.hsn_sac
        and new_type == product.item_type
        and new_verified == product.gst_verified
    ):
        raise HTTPException(status_code=400, detail="The catalogue item already has these GST details.")

    mode = approval_mode(db, owner)
    requires_approval = role != "owner" and mode == "owner_approval"
    change = GstCatalogueChange(
        business_id=product.business_id,
        product_id=product.id,
        owner_user_id=owner.id,
        old_gst_rate=q2(product.default_gst_rate),
        new_gst_rate=new_rate,
        old_hsn_sac=product.hsn_sac,
        new_hsn_sac=new_hsn,
        old_item_type=product.item_type,
        new_item_type=new_type,
        old_hsn_verified=product.gst_verified,
        new_hsn_verified=new_verified,
        effective_from=effective_from,
        reason=clean_reason,
        status="pending_approval" if requires_approval else "applied",
        requested_by_user_id=actor.id,
        requested_by_role=role,
        decided_by_user_id=None if requires_approval else actor.id,
        decided_at=None if requires_approval else utcnow(),
    )
    db.add(change)
    db.flush()
    if not requires_approval:
        _apply_change(product, change, actor.id)
    log_audit(
        db,
        user_id=owner.id,
        actor=actor.email,
        action="gst.catalogue.proposed" if requires_approval else "gst.catalogue.updated",
        entity_type="product",
        entity_id=product.id,
        detail={
            "change_id": change.id,
            "sku": product.sku,
            "old_gst_rate": str(change.old_gst_rate),
            "new_gst_rate": str(change.new_gst_rate),
            "old_hsn_sac": change.old_hsn_sac,
            "new_hsn_sac": change.new_hsn_sac,
            "reason": clean_reason,
            "approval_mode": mode,
            "requested_by_role": role,
        },
    )
    db.commit()
    db.refresh(change)
    return change


def decide_change(
    db: Session,
    *,
    change: GstCatalogueChange,
    owner: User,
    approve: bool,
    note: str | None = None,
) -> GstCatalogueChange:
    if change.owner_user_id != owner.id:
        raise HTTPException(status_code=404, detail="Catalogue change not found.")
    if change.status != "pending_approval":
        raise HTTPException(status_code=409, detail="This catalogue change is already decided.")
    if approve:
        _apply_change(change.product, change, owner.id)
        change.status = "approved"
    else:
        change.status = "rejected"
    change.decided_by_user_id = owner.id
    change.decided_at = utcnow()
    change.decision_note = _clean(note)
    log_audit(
        db,
        user_id=owner.id,
        actor="owner",
        action="gst.catalogue.approved" if approve else "gst.catalogue.rejected",
        entity_type="product",
        entity_id=change.product_id,
        detail={
            "change_id": change.id,
            "new_gst_rate": str(change.new_gst_rate),
            "new_hsn_sac": change.new_hsn_sac,
            "note": change.decision_note,
        },
    )
    db.commit()
    db.refresh(change)
    return change


def effective_gst_rate(db: Session, product: Product, on_date: date) -> Decimal:
    """Rate that applies to a new invoice dated ``on_date``.

    A future-dated change is already stored on the product; earlier invoices use
    the proposal's previous rate until the effective date arrives.
    """
    changes = (
        db.query(GstCatalogueChange)
        .filter(
            GstCatalogueChange.product_id == product.id,
            GstCatalogueChange.status.in_(APPLIED_STATUSES),
        )
        .all()
    )
    if not changes:
        return q2(product.default_gst_rate)
    dated = [row for row in changes if row.effective_from and row.effective_from <= on_date]
    if dated:
        latest = max(dated, key=lambda row: (row.effective_from, row.created_at, row.id))
        return q2(latest.new_gst_rate)
    future = [
        row
        for row in changes
        if row.effective_from and row.effective_from > on_date and row.old_gst_rate is not None
    ]
    if future:
        earliest = min(future, key=lambda row: (row.effective_from, row.created_at, row.id))
        return q2(earliest.old_gst_rate)
    return q2(product.default_gst_rate)


def export_catalogue_workbook(db: Session, owner: User) -> bytes:
    rows = catalogue_rows(db, owner.id, limit=5000)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "GST Catalogue"
    headers = [
        "SKU",
        "Product / Service",
        "Type",
        "HSN / SAC",
        "GST %",
        "Effective from",
        "HSN verified",
        "Last updated by",
        "Last updated",
        "Pending change",
        "Pending reason",
    ]
    sheet.append(headers)
    header_fill = PatternFill("solid", fgColor="1E3A8A")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        pending = row["pending_change"]
        sheet.append(
            [
                row["sku"],
                row["name"],
                "Service" if row["item_type"] in ("services", "service") else "Goods",
                row["hsn_sac"] or "",
                float(row["gst_rate"]),
                row["gst_effective_from"] or "",
                "Yes" if row["gst_verified"] else "No",
                (row["gst_updated_by"] or {}).get("name") or "—",
                row["gst_updated_at"].strftime("%Y-%m-%d %H:%M") if row["gst_updated_at"] else "",
                f"{pending['new_gst_rate']}% pending" if pending else "",
                pending["reason"] if pending else "",
            ]
        )
    sheet.freeze_panes = "A2"
    widths = [16, 34, 12, 14, 10, 14, 13, 22, 18, 18, 40]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    for cell in sheet["E"][1:]:
        cell.number_format = '0.00"%"'
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
