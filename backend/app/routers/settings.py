from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas import DemoResetIn, IntegrationCheckIn
from ..security import get_current_user, rate_limit
from ..seed import reset_demo
from ..services.audit import log_audit
from ..services.business_context import active_business
from ..services.integrations.paypal import paypal_client
from ..services.integrations_status import check_integration, integration_overview

router = APIRouter(tags=["Settings and integrations"])


@router.get("/integrations")
def integrations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return integration_overview(db, user)


@router.post(
    "/integrations/check",
    dependencies=[Depends(rate_limit("integration_check", 15, 60))],
)
def integration_check(
    payload: IntegrationCheckIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return check_integration(db, user, payload.provider)


@router.get("/settings/runtime")
def runtime_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    business = active_business(db, user)
    return {
        "environment": settings.ENV,
        "demo_mode": user.is_demo,
        "demo_reset_enabled": settings.DEMO_RESET_ENABLED,
        "features": {
            "llm": {
                "configured": settings.llm_configured,
                "mode": "llm" if settings.llm_configured else "deterministic_fallback",
                "model": settings.LLM_MODEL if settings.llm_configured else None,
            },
            "paypal": {
                "configured": paypal_client.configured,
                "enabled": paypal_client.enabled,
                "environment": paypal_client.environment,
                "mode": paypal_client.mode,
                "webhook_configured": bool(paypal_client.webhook_id),
                "webhook_signature_verification": paypal_client.configured
                and bool(paypal_client.webhook_id),
            },
            "upstox": {
                "configured": settings.upstox_configured,
                "live_trading_enabled": settings.UPSTOX_LIVE_TRADING_ENABLED,
                "live_trading_ready": settings.upstox_live_ready,
                "static_ip_required": True,
                "static_ip_proxy_configured": bool(settings.UPSTOX_ORDER_PROXY_URL),
            },
            "market_data": {
                "metals_configured": bool(settings.METALS_API_KEY),
                "news_configured": bool(settings.NEWS_API_KEY),
            },
            "delivery": {
                "email_configured": settings.email_configured,
                "email_ready": settings.email_ready,
                "sms_configured": settings.sms_configured,
                "sms_ready": settings.sms_ready,
            },
        },
        "security": {
            "token_type": "JWT bearer",
            "password_hashing": "PBKDF2-SHA256",
            "secrets_location": "Backend environment only. The browser receives booleans, never keys.",
            "demo_warning": "Demo credentials and seeded data are for local evaluation only.",
        },
        "timezone": business.timezone if business else None,
        "currency": business.currency if business else None,
    }


@router.post(
    "/demo/reset",
    dependencies=[Depends(rate_limit("demo_reset", 3, 300))],
)
def demo_reset(
    payload: DemoResetIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not settings.DEMO_RESET_ENABLED:
        raise HTTPException(status_code=403, detail="Demo reset is disabled on this deployment.")
    if not user.is_demo:
        raise HTTPException(
            status_code=403,
            detail="Demo reset is restricted to the seeded demo account. Live business records are never wiped.",
        )
    if payload.confirm != "RESET DEMO":
        raise HTTPException(
            status_code=400,
            detail='Type "RESET DEMO" to confirm. All demo ledger records will be restored.',
        )
    reset_user = reset_demo(db)
    log_audit(
        db,
        user_id=reset_user.id,
        actor=reset_user.email,
        action="demo.reset",
        entity_type="user",
        entity_id=reset_user.id,
        detail={"note": "Demo business records restored to the seeded starting state."},
    )
    db.commit()
    return {
        "message": "Demo data restored to its initial seeded state.",
        "demo_email": settings.DEMO_EMAIL,
        "note": "Sign in again if your token is still valid; the account is unchanged.",
    }
