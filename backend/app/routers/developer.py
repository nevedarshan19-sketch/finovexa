from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import (
    AuditEvent,
    BusinessProfile,
    ContactMessage,
    ITRPrice,
    PricingAddon,
    SoftwareTier,
    User,
    utcnow,
)
from ..schemas import (
    DeveloperAccountCreateIn,
    DeveloperAccountUpdateIn,
    ITRPriceUpdateIn,
    PricingAddonIn,
    PricingAddonUpdateIn,
    PricingRulesIn,
    SoftwareTierUpdateIn,
)
from ..security import get_current_developer, hash_password, rate_limit
from ..seed import create_user
from ..services.audit import log_audit
from ..services.business_context import ensure_membership, primary_business
from ..services.pricing import (
    admin_pricing_payload,
    get_pricing_settings,
    history_payload,
    record_price_history,
)

router = APIRouter(prefix="/developer", tags=["Developer console"])

ACCOUNT_ROLES = (
    "owner",
    "employee",
    "senior_accountant",
    "junior_accountant",
    "customer",
)

LOGIN_PATHS = {
    "owner": "/login",
    "employee": "/employee/login",
    "senior_accountant": "/accountant/login",
    "junior_accountant": "/accountant/login",
    "customer": "/client/login",
}


def _account_payload(
    account: User,
    *,
    owner_email: str | None = None,
    business_name: str | None = None,
) -> dict:
    return {
        "id": account.id,
        "email": account.email,
        "full_name": account.full_name,
        "role": account.role,
        "is_active": account.is_active,
        "is_demo": account.is_demo,
        "owner_id": account.owner_id,
        "owner_email": owner_email,
        "business_name": business_name,
        "created_at": account.created_at.isoformat(),
    }


def _account_payloads(db: Session, accounts: list[User]) -> list[dict]:
    owner_ids = {account.owner_id for account in accounts if account.owner_id}
    owners = {
        owner.id: owner
        for owner in db.query(User).filter(User.id.in_(owner_ids)).all()
    } if owner_ids else {}
    profiles = {
        profile.user_id: profile
        for profile in db.query(BusinessProfile)
        .filter(BusinessProfile.user_id.in_({account.id for account in accounts}))
        .all()
    }
    return [
        _account_payload(
            account,
            owner_email=owners[account.owner_id].email if account.owner_id in owners else None,
            business_name=(
                profiles[account.id].business_name if account.id in profiles else None
            ),
        )
        for account in accounts
    ]


@router.get("/overview")
def developer_overview(
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    role_counts = dict(
        db.query(User.role, func.count(User.id)).group_by(User.role).all()
    )
    accountant_count = int(role_counts.get("senior_accountant", 0)) + int(
        role_counts.get("junior_accountant", 0)
    )
    active_accounts = (
        db.query(func.count(User.id))
        .filter(User.role.in_(ACCOUNT_ROLES), User.is_active.is_(True))
        .scalar()
    )
    inactive_accounts = (
        db.query(func.count(User.id))
        .filter(User.role.in_(ACCOUNT_ROLES), User.is_active.is_(False))
        .scalar()
    )
    auth_events_24h = (
        db.query(func.count(AuditEvent.id))
        .filter(
            AuditEvent.action.like("auth.%"),
            AuditEvent.created_at >= utcnow() - timedelta(hours=24),
        )
        .scalar()
    )
    return {
        "environment": settings.ENV,
        "developer": {
            "name": developer.full_name,
            "email": developer.email,
            "account_management": "owner, employee, accountant and customer logins",
        },
        "counts": {
            "owners": int(role_counts.get("owner", 0)),
            "employees": int(role_counts.get("employee", 0)),
            "accountants": accountant_count,
            "customers": int(role_counts.get("customer", 0)),
            "developers": int(role_counts.get("developer", 0)),
            "active_accounts": int(active_accounts or 0),
            "inactive_accounts": int(inactive_accounts or 0),
            "auth_events_24h": int(auth_events_24h or 0),
        },
        "features": {
            "llm": {
                "configured": settings.llm_configured,
                "mode": "llm" if settings.llm_configured else "deterministic_fallback",
            },
            "paypal": {"configured": settings.paypal_configured, "mode": settings.paypal_mode},
            "upstox": {
                "configured": settings.upstox_configured,
                "live_trading_enabled": settings.UPSTOX_LIVE_TRADING_ENABLED,
                "live_trading_ready": settings.upstox_live_ready,
                "static_ip_proxy_configured": bool(settings.UPSTOX_ORDER_PROXY_URL),
            },
            "market_data": {
                "metals_configured": bool(settings.METALS_API_KEY),
                "news_configured": bool(settings.NEWS_API_KEY),
            },
            "demo_seed_enabled": settings.AUTO_SEED,
            "public_registration_open": True,
        },
        "security": {
            "password_hashing": "PBKDF2-SHA256",
            "session_type": "JWT bearer",
            "secrets_location": "Backend environment only. This console never receives keys.",
            "scope": (
                "Developer accounts manage owner, employee, accountant and customer logins "
                "and inspect auth events. They cannot read owner ledgers, approvals, payments "
                "or market positions."
            ),
        },
    }


@router.get("/accounts")
def list_accounts(
    role: str = Query(
        default="all",
        pattern=r"^(all|owner|employee|senior_accountant|junior_accountant|customer)$",
    ),
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    query = db.query(User).filter(User.role.in_(ACCOUNT_ROLES))
    if role != "all":
        query = query.filter(User.role == role)
    accounts = query.order_by(User.role.asc(), User.created_at.desc(), User.id.desc()).all()
    return {
        "items": _account_payloads(db, accounts),
        "count": len(accounts),
        "login_paths": LOGIN_PATHS,
        "note": (
            "Owner, employee, accountant and customer logins appear here. "
            "Developer accounts are managed by environment."
        ),
    }


@router.post(
    "/accounts",
    status_code=201,
    dependencies=[Depends(rate_limit("developer_account_create", 20, 60))],
)
def create_account(
    payload: DeveloperAccountCreateIn,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    email = payload.email.lower().strip()
    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    if payload.role == "owner":
        account = create_user(
            db,
            email=email,
            password=payload.password,
            full_name=payload.full_name.strip(),
            business_name=(payload.business_name or "").strip(),
            currency=payload.currency,
        )
        account.is_demo = False
    elif payload.role == "employee":
        owner = db.get(User, payload.owner_id)
        if owner is None or owner.role != "owner":
            raise HTTPException(status_code=404, detail="Owner account not found.")
        if not owner.is_active:
            raise HTTPException(status_code=409, detail="That owner account is inactive.")
        account = User(
            email=email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name.strip(),
            role="employee",
            owner_id=owner.id,
            is_demo=False,
            is_active=True,
        )
        db.add(account)
    else:
        account = User(
            email=email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name.strip(),
            role=payload.role,
            is_demo=False,
            is_active=True,
        )
        db.add(account)
    db.flush()
    if account.role == "employee" and account.owner_id is not None:
        business = primary_business(db, account.owner_id)
        if business is not None:
            ensure_membership(db, business.id, account.id, "employee")
    log_audit(
        db,
        user_id=developer.id,
        actor=developer.email,
        action="developer.account_created",
        entity_type="user",
        entity_id=account.id,
        detail={
            "email": account.email,
            "role": account.role,
            "owner_id": account.owner_id,
            "business_name": payload.business_name if payload.role == "owner" else None,
        },
    )
    db.commit()
    db.refresh(account)
    return {
        "account": _account_payloads(db, [account])[0],
        "login_path": LOGIN_PATHS[account.role],
        "message": "Account created. Share the credentials separately and never in source control.",
    }


@router.patch("/accounts/{account_id}")
def update_account(
    account_id: int,
    payload: DeveloperAccountUpdateIn,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    account = (
        db.query(User)
        .filter(User.id == account_id, User.role.in_(ACCOUNT_ROLES))
        .one_or_none()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Managed login account not found.")

    changed: list[str] = []
    previous_email = account.email
    if payload.full_name is not None:
        account.full_name = payload.full_name.strip()
        changed.append("full_name")
    if payload.email is not None:
        email = str(payload.email).lower().strip()
        conflict = (
            db.query(User)
            .filter(func.lower(User.email) == email, User.id != account.id)
            .one_or_none()
        )
        if conflict is not None:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        account.email = email
        changed.append("email")
    if payload.is_active is not None:
        account.is_active = payload.is_active
        changed.append("is_active")
    if payload.password is not None:
        account.password_hash = hash_password(payload.password)
        changed.append("password_reset")

    log_audit(
        db,
        user_id=developer.id,
        actor=developer.email,
        action="developer.account_updated",
        entity_type="user",
        entity_id=account.id,
        detail={
            "email": account.email,
            "previous_email": previous_email if previous_email != account.email else None,
            "role": account.role,
            "changed": changed,
            "is_active": account.is_active,
        },
    )
    db.commit()
    db.refresh(account)
    return {
        "account": _account_payloads(db, [account])[0],
        "message": "Account updated. Password values are never stored in audit records.",
    }


@router.get("/security-log")
def security_log(
    limit: int = Query(default=50, ge=1, le=200),
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    events = (
        db.query(AuditEvent)
        .filter(
            or_(
                AuditEvent.action.like("auth.%"),
                AuditEvent.action.like("developer.%"),
                AuditEvent.action.like("team.%"),
            )
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": event.id,
                "action": event.action,
                "actor": event.actor,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "detail": event.detail,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
        "count": len(events),
        "note": "Authentication, account and developer actions only. Ledger records are not exposed here.",
    }


@router.get("/pricing")
def pricing_configuration(
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    return admin_pricing_payload(db)


def _price_changes(
    db: Session,
    developer: User,
    *,
    entity_type: str,
    entity_key: str,
    changes: list[tuple[str, object, object]],
    note: str | None,
) -> None:
    for field, old, new in changes:
        if str(old) == str(new):
            continue
        record_price_history(
            db,
            entity_type=entity_type,
            entity_key=entity_key,
            field=field,
            old_value=old,
            new_value=new,
            user=developer,
            note=note,
        )


@router.put("/pricing/rules")
def update_pricing_rules(
    payload: PricingRulesIn,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    rules = get_pricing_settings(db)
    changes: list[tuple[str, object, object]] = []
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        current = getattr(rules, field)
        if current != value:
            changes.append((field, current, value))
            setattr(rules, field, value)
    rules.updated_by_user_id = developer.id
    _price_changes(
        db,
        developer,
        entity_type="pricing_rules",
        entity_key="default",
        changes=changes,
        note="Accounting quotation rules updated",
    )
    log_audit(
        db,
        user_id=developer.id,
        actor=developer.email,
        action="developer.pricing_rules_updated",
        entity_type="pricing_setting",
        entity_id=rules.id,
        detail={"fields": [field for field, _, _ in changes]},
    )
    db.commit()
    db.refresh(rules)
    return {
        "settings": admin_pricing_payload(db)["settings"],
        "message": "Pricing rules updated. New quotations use the new rules.",
    }


@router.put("/pricing/software/{tier_id}")
def update_software_tier(
    tier_id: int,
    payload: SoftwareTierUpdateIn,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    tier = db.get(SoftwareTier, tier_id)
    if tier is None:
        raise HTTPException(status_code=404, detail="Software tier not found.")
    changes: list[tuple[str, object, object]] = []
    for field, value in payload.model_dump(exclude_unset=True).items():
        current = getattr(tier, field)
        if current != value:
            changes.append((field, current, value))
            setattr(tier, field, value)
    _price_changes(
        db,
        developer,
        entity_type="software_tier",
        entity_key=tier.key,
        changes=changes,
        note="Business Manager subscription price updated",
    )
    log_audit(
        db,
        user_id=developer.id,
        actor=developer.email,
        action="developer.software_price_updated",
        entity_type="software_tier",
        entity_id=tier.id,
        detail={"key": tier.key, "fields": [field for field, _, _ in changes]},
    )
    db.commit()
    db.refresh(tier)
    return {
        "tier": {
            "id": tier.id,
            "key": tier.key,
            "label": tier.label,
            "monthly_price": float(tier.monthly_price),
            "is_active": tier.is_active,
        },
        "message": "Subscription price updated.",
    }


@router.put("/pricing/itr/{price_id}")
def update_itr_price(
    price_id: int,
    payload: ITRPriceUpdateIn,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    row = db.get(ITRPrice, price_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ITR price not found.")
    changes: list[tuple[str, object, object]] = []
    for field, value in payload.model_dump(exclude_unset=True).items():
        current = getattr(row, field)
        if current != value:
            changes.append((field, current, value))
            setattr(row, field, value)
    _price_changes(
        db,
        developer,
        entity_type="itr_price",
        entity_key=row.key,
        changes=changes,
        note="ITR filing price updated",
    )
    log_audit(
        db,
        user_id=developer.id,
        actor=developer.email,
        action="developer.itr_price_updated",
        entity_type="itr_price",
        entity_id=row.id,
        detail={"key": row.key, "fields": [field for field, _, _ in changes]},
    )
    db.commit()
    db.refresh(row)
    return {
        "itr_price": {
            "id": row.id,
            "key": row.key,
            "label": row.label,
            "price_min": float(row.price_min),
            "price_max": float(row.price_max) if row.price_max is not None else None,
            "is_active": row.is_active,
        },
        "message": "ITR price updated.",
    }


@router.post("/pricing/addons", status_code=201)
def create_pricing_addon(
    payload: PricingAddonIn,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    if db.query(PricingAddon).filter(PricingAddon.key == payload.key).first() is not None:
        raise HTTPException(status_code=409, detail="An add-on with this key already exists.")
    addon = PricingAddon(**payload.model_dump())
    db.add(addon)
    db.flush()
    record_price_history(
        db,
        entity_type="pricing_addon",
        entity_key=addon.key,
        field="amount",
        old_value=None,
        new_value=addon.amount,
        user=developer,
        note="Additional service charge created",
    )
    log_audit(
        db,
        user_id=developer.id,
        actor=developer.email,
        action="developer.pricing_addon_created",
        entity_type="pricing_addon",
        entity_id=addon.id,
        detail={"key": addon.key},
    )
    db.commit()
    return {
        "addon": {
            "id": addon.id,
            "key": addon.key,
            "label": addon.label,
            "amount": float(addon.amount) if addon.amount is not None else None,
            "cadence": addon.cadence,
            "is_active": addon.is_active,
        },
        "message": "Add-on created.",
    }


@router.patch("/pricing/addons/{addon_id}")
def update_pricing_addon(
    addon_id: int,
    payload: PricingAddonUpdateIn,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    addon = db.get(PricingAddon, addon_id)
    if addon is None:
        raise HTTPException(status_code=404, detail="Add-on not found.")
    changes: list[tuple[str, object, object]] = []
    for field, value in payload.model_dump(exclude_unset=True).items():
        current = getattr(addon, field)
        if current != value:
            changes.append((field, current, value))
            setattr(addon, field, value)
    _price_changes(
        db,
        developer,
        entity_type="pricing_addon",
        entity_key=addon.key,
        changes=changes,
        note="Additional service charge updated",
    )
    log_audit(
        db,
        user_id=developer.id,
        actor=developer.email,
        action="developer.pricing_addon_updated",
        entity_type="pricing_addon",
        entity_id=addon.id,
        detail={"key": addon.key, "fields": [field for field, _, _ in changes]},
    )
    db.commit()
    db.refresh(addon)
    return {
        "addon": {
            "id": addon.id,
            "key": addon.key,
            "label": addon.label,
            "amount": float(addon.amount) if addon.amount is not None else None,
            "cadence": addon.cadence,
            "is_active": addon.is_active,
        },
        "message": "Add-on updated.",
    }


@router.get("/pricing/history")
def pricing_history(
    limit: int = Query(default=100, ge=1, le=300),
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    return {"items": history_payload(db, limit=limit)}


@router.get("/contact-messages")
def contact_messages(
    limit: int = Query(default=50, ge=1, le=200),
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ContactMessage)
        .order_by(ContactMessage.created_at.desc(), ContactMessage.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "reference": row.reference,
                "name": row.name,
                "email": row.email,
                "organisation": row.organisation,
                "phone": row.phone,
                "category": row.category,
                "subject": row.subject,
                "message": row.message,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "count": len(rows),
        "note": "Public contact messages. No automatic email is sent, and no secrets are requested.",
    }
