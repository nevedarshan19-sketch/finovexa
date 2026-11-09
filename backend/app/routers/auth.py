from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AccountingClient, User
from ..schemas import (
    AuthOut,
    BusinessSummaryOut,
    LoginIn,
    ProfileOut,
    RegisterIn,
    UserOut,
)
from ..security import (
    ACCOUNTANT_ROLES,
    create_access_token,
    get_current_user,
    hash_password,
    rate_limit,
    verify_password,
)
from ..seed import create_user, ensure_global_market_data
from ..services.audit import log_audit
from ..services.business_context import BUSINESS_HEADER, active_business, bind_business

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _business_summary(business) -> BusinessSummaryOut | None:
    if business is None:
        return None
    return BusinessSummaryOut(
        business_name=business.business_name,
        currency=business.currency,
        timezone=business.timezone,
    )


def _auth_response(db: Session, user: User) -> AuthOut:
    token, expires_in = create_access_token(user.id, user.email)
    business = active_business(db, user) if user.role in ("owner", "employee") else None
    return AuthOut(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
        profile=ProfileOut.model_validate(business)
        if user.role == "owner" and business is not None
        else None,
        business=_business_summary(business),
    )


@router.post(
    "/register",
    response_model=AuthOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", 5, 60))],
)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email.lower()).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    ensure_global_market_data(db)
    user = create_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        business_name=payload.business_name,
        currency=payload.currency,
    )
    bind_business(db, user, None)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="auth.registered",
        entity_type="user",
        entity_id=user.id,
        detail={"business_name": payload.business_name},
    )
    db.commit()
    db.refresh(user)
    return _auth_response(db, user)


@router.post(
    "/login",
    response_model=AuthOut,
    dependencies=[Depends(rate_limit("login", 10, 60))],
)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    if user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee accounts sign in through the employee portal.",
        )
    bind_business(db, user, None)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        detail={"is_demo": user.is_demo, "role": user.role},
    )
    db.commit()
    return _auth_response(db, user)


@router.post(
    "/employee/login",
    response_model=AuthOut,
    dependencies=[Depends(rate_limit("employee_login", 10, 60))],
)
def employee_login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    if user.role != "employee":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner accounts sign in through the owner portal.",
        )
    owner = db.get(User, user.owner_id) if user.owner_id else None
    if owner is None or not owner.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This employee account is not attached to an active business.",
        )
    business = bind_business(db, user, None)
    if business is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This employee account is not attached to an active business.",
        )
    log_audit(
        db,
        user_id=owner.id,
        actor=user.email,
        action="auth.employee_login",
        entity_type="user",
        entity_id=user.id,
        detail={"employee_name": user.full_name, "owner_id": owner.id},
    )
    db.commit()
    return _auth_response(db, user)


@router.post(
    "/developer/login",
    response_model=AuthOut,
    dependencies=[Depends(rate_limit("developer_login", 10, 60))],
)
def developer_login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    if user.role != "developer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Developer accounts sign in through the developer console.",
        )
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="auth.developer_login",
        entity_type="user",
        entity_id=user.id,
        detail={"role": user.role},
    )
    db.commit()
    return _auth_response(db, user)


def _accounting_context(db: Session, user: User) -> dict | None:
    if user.role in ACCOUNTANT_ROLES:
        return {
            "portal": "accountant",
            "role": user.role,
            "display_name": user.full_name,
        }
    if user.role == "customer":
        client = (
            db.query(AccountingClient)
            .filter(AccountingClient.customer_user_id == user.id)
            .one_or_none()
        )
        return {
            "portal": "customer",
            "role": user.role,
            "display_name": user.full_name,
            "client": (
                {
                    "id": client.id,
                    "code": client.code,
                    "business_name": client.business_name,
                    "status": client.status,
                }
                if client is not None
                else None
            ),
        }
    return None


@router.post(
    "/accountant/login",
    response_model=AuthOut,
    dependencies=[Depends(rate_limit("accountant_login", 10, 60))],
)
def accountant_login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    if user.role not in ACCOUNTANT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accountant accounts sign in through the accountant portal.",
        )
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="auth.accountant_login",
        entity_type="user",
        entity_id=user.id,
        detail={"role": user.role, "is_demo": user.is_demo},
    )
    db.commit()
    return _auth_response(db, user)


@router.post(
    "/customer/login",
    response_model=AuthOut,
    dependencies=[Depends(rate_limit("customer_login", 10, 60))],
)
def customer_login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    if user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client accounts sign in through the client portal.",
        )
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="auth.customer_login",
        entity_type="user",
        entity_id=user.id,
        detail={"role": user.role, "is_demo": user.is_demo},
    )
    db.commit()
    return _auth_response(db, user)


@router.get("/me")
def me(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    business = None
    if user.role in ("owner", "employee"):
        business = bind_business(db, user, request.headers.get(BUSINESS_HEADER))
    return {
        "user": UserOut.model_validate(user),
        "profile": ProfileOut.model_validate(business)
        if user.role == "owner" and business is not None
        else None,
        "business": _business_summary(business),
        "accounting": _accounting_context(db, user),
        "demo_mode": user.is_demo,
    }


@router.post("/logout")
def logout(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="auth.logout",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    return {
        "message": "Signed out. Discard the access token on the client.",
        "note": "Tokens are stateless JWTs; the client must remove the token. Rotate SECRET_KEY to revoke all sessions.",
    }
