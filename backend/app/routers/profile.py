from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, Product, User
from ..schemas import ProfileUpdateIn
from ..security import get_current_user
from ..services.audit import log_audit
from ..services.business_context import require_business
from ..services.finance import customer_to_dict, q2

router = APIRouter(tags=["Business profile and catalog"])


@router.get("/profile")
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = require_business(db, user)
    return {
        "business_name": profile.business_name,
        "currency": profile.currency,
        "timezone": profile.timezone,
        "reporting_period": profile.reporting_period,
        "min_cash_reserve": q2(profile.min_cash_reserve),
        "opening_cash_balance": q2(profile.opening_cash_balance),
        "opening_balance_date": profile.opening_balance_date,
        "risk_tolerance": profile.risk_tolerance,
        "research_interests": profile.research_interests,
        "reminder_tone": profile.reminder_tone,
    }


@router.put("/profile")
def update_profile(
    payload: ProfileUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = require_business(db, user)
    changes = payload.model_dump(exclude_unset=True)
    if "opening_balance_date" not in changes:
        pass
    for field, value in changes.items():
        if value is not None:
            setattr(profile, field, value)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="profile.updated",
        entity_type="business_profile",
        entity_id=profile.id,
        detail={"fields": sorted(changes.keys())},
    )
    db.commit()
    db.refresh(profile)
    return {
        "message": "Business profile updated.",
        "profile": {
            "business_name": profile.business_name,
            "currency": profile.currency,
            "timezone": profile.timezone,
            "reporting_period": profile.reporting_period,
            "min_cash_reserve": q2(profile.min_cash_reserve),
            "opening_cash_balance": q2(profile.opening_cash_balance),
            "opening_balance_date": profile.opening_balance_date,
            "risk_tolerance": profile.risk_tolerance,
            "research_interests": profile.research_interests,
            "reminder_tone": profile.reminder_tone,
        },
    }


@router.get("/customers")
def customers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Customer).filter(Customer.user_id == user.id).order_by(Customer.name).all()
    return {"items": [customer_to_dict(customer) for customer in rows]}


@router.get("/products")
def products(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Product).filter(Product.user_id == user.id).order_by(Product.name).all()
    return {
        "items": [
            {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "unit_price": q2(product.unit_price),
                "unit_cost": q2(product.unit_cost),
                "reorder_level": product.reorder_level,
                "quantity_on_hand": product.inventory.quantity_on_hand if product.inventory else 0,
                "low_stock": (product.inventory.quantity_on_hand if product.inventory else 0)
                <= product.reorder_level,
            }
            for product in rows
        ]
    }
