"""Resolve and validate the business a request is allowed to work in."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import BusinessMembership, BusinessProfile, User
from ..tenancy import current_business_id, set_current_business

BUSINESS_HEADER = "X-Business-Id"
SCOPED_ROLES = ("owner", "employee")


def parse_business_header(raw: str | None) -> int | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid business selection.")
    if value <= 0:
        raise HTTPException(status_code=400, detail="Invalid business selection.")
    return value


def bind_business(db: Session, user: User, raw_header: str | None) -> BusinessProfile | None:
    """Bind the request to a business. Raises when access is not allowed."""
    set_current_business(None)
    if user.role not in SCOPED_ROLES:
        return None

    requested = parse_business_header(raw_header)
    owner_id = user.id if user.role == "owner" else user.owner_id
    if owner_id is None:
        set_current_business(-1)
        return None

    owned = db.query(BusinessProfile).filter(BusinessProfile.owner_id == owner_id)
    business: BusinessProfile | None = None

    if requested is not None:
        candidate = owned.filter(BusinessProfile.id == requested).one_or_none()
        if candidate is None:
            raise HTTPException(
                status_code=403, detail="You do not have access to this business."
            )
        business = candidate
    elif user.role == "employee":
        membership = (
            db.query(BusinessMembership)
            .filter(
                BusinessMembership.user_id == user.id,
                BusinessMembership.status == "active",
            )
            .order_by(BusinessMembership.id)
            .first()
        )
        if membership is not None:
            business = db.get(BusinessProfile, membership.business_id)
        if business is None or business.owner_id != owner_id:
            business = owned.order_by(BusinessProfile.id).first()
    else:
        business = (
            owned.filter(BusinessProfile.is_archived.is_(False))
            .order_by(BusinessProfile.id)
            .first()
            or owned.order_by(BusinessProfile.id).first()
        )

    if business is not None and user.role == "employee":
        membership = (
            db.query(BusinessMembership)
            .filter(
                BusinessMembership.business_id == business.id,
                BusinessMembership.user_id == user.id,
                BusinessMembership.status == "active",
            )
            .one_or_none()
        )
        if membership is None:
            raise HTTPException(
                status_code=403, detail="You do not have access to this business."
            )

    set_current_business(business.id if business is not None else -1)
    return business


def ensure_membership(
    db: Session, business_id: int, user_id: int, role: str
) -> BusinessMembership:
    row = (
        db.query(BusinessMembership)
        .filter(
            BusinessMembership.business_id == business_id,
            BusinessMembership.user_id == user_id,
        )
        .one_or_none()
    )
    if row is None:
        row = BusinessMembership(
            business_id=business_id, user_id=user_id, role=role, status="active"
        )
        db.add(row)
    else:
        row.role = role
        row.status = "active"
    return row


def primary_business(db: Session, owner_id: int) -> BusinessProfile | None:
    return (
        db.query(BusinessProfile)
        .filter(BusinessProfile.owner_id == owner_id)
        .order_by(BusinessProfile.id)
        .first()
    )


def require_business(db: Session, user: User) -> BusinessProfile:
    business = active_business(db, user)
    if business is None:
        raise HTTPException(
            status_code=404, detail="No active business. Create or select a business first."
        )
    return business


def active_business(db: Session, user: User) -> BusinessProfile | None:
    """The business currently in scope for this request."""
    business_id = current_business_id()
    if business_id is not None:
        if business_id <= 0:
            return None
        return db.get(BusinessProfile, business_id)
    owner_id = user.id if user.role == "owner" else user.owner_id
    if owner_id is None:
        return None
    return (
        db.query(BusinessProfile)
        .filter(BusinessProfile.owner_id == owner_id)
        .order_by(BusinessProfile.id)
        .first()
    )
