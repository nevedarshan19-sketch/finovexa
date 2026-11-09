from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..config import settings
from ..models import IntegrationConfig, User, utcnow
from .audit import log_audit
from .delivery import (
    DeliveryError,
    check_email_connection,
    check_sms_connection,
)
from .integrations.metals import MetalsError, metals_client
from .integrations.news import NewsError, news_client
from .integrations.paypal import PayPalError, paypal_client
from .integrations.upstox import UpstoxError, upstox_client


def _mode_for(provider: str) -> str:
    if provider == "paypal":
        return paypal_client.mode
    if provider == "upstox":
        return "live" if upstox_client.configured else "demo"
    if provider == "email":
        return "live" if settings.email_ready else "simulated"
    if provider == "sms":
        return "live" if settings.sms_ready else "simulated"
    if provider in ("metals", "news", "llm"):
        configured = {
            "metals": metals_client.configured,
            "news": news_client.configured,
            "llm": settings.llm_configured,
        }[provider]
        return "live" if configured else "demo"
    return "demo"


def integration_overview(db: Session, user: User) -> dict:
    rows = db.query(IntegrationConfig).filter(IntegrationConfig.user_id == user.id).all()
    existing = {row.provider: row for row in rows}
    items = [
        {
            "provider": "paypal",
            "label": "PayPal",
            "purpose": "Sandbox checkout, capture, webhook-verified payment events.",
            "configured": paypal_client.configured,
            "mode": paypal_client.mode,
            "environment": paypal_client.environment,
            "webhook_configured": bool(paypal_client.webhook_id),
            "status": existing["paypal"].status if "paypal" in existing else ("configured" if paypal_client.configured else "demo"),
            "last_checked_at": existing["paypal"].last_checked_at if "paypal" in existing else None,
            "setup": (
                "Set PAYPAL_SANDBOX_CLIENT_ID / PAYPAL_SANDBOX_CLIENT_SECRET / "
                "PAYPAL_SANDBOX_WEBHOOK_ID (or the PAYPAL_LIVE_* pair) in backend/.env, then choose "
                "the environment in Settings."
            ),
            "demo_behaviour": "Simulated checkout and labelled simulated payment capture. No PayPal API call.",
        },
        {
            "provider": "upstox",
            "label": "Upstox",
            "purpose": "Authorized Indian equity quotes, historical candles, option chain and optional live order placement.",
            "configured": upstox_client.configured,
            "mode": "live" if upstox_client.configured else "demo",
            "status": existing["upstox"].status if "upstox" in existing else ("configured" if upstox_client.configured else "demo"),
            "last_checked_at": existing["upstox"].last_checked_at if "upstox" in existing else None,
            "setup": "Complete Upstox OAuth, then set UPSTOX_ACCESS_TOKEN in backend/.env. Secrets never reach the browser.",
            "auth_url": upstox_client.authorization_url(),
            "live_trading_enabled": settings.UPSTOX_LIVE_TRADING_ENABLED,
            "live_trading_ready": settings.upstox_live_ready,
            "static_ip_required": True,
            "static_ip_proxy_configured": bool(settings.UPSTOX_ORDER_PROXY_URL),
            "demo_behaviour": "Seeded demo quotes and candles. Orders are simulated unless live trading is enabled and explicitly selected at order approval.",
        },
        {
            "provider": "metals",
            "label": "Gold & silver data",
            "purpose": "Spot gold and silver prices in USD per troy ounce.",
            "configured": metals_client.configured,
            "mode": "live" if metals_client.configured else "demo",
            "status": existing["metals"].status if "metals" in existing else ("configured" if metals_client.configured else "demo"),
            "last_checked_at": existing["metals"].last_checked_at if "metals" in existing else None,
            "setup": "Set METALS_API_KEY (Metals.dev compatible) and optionally METALS_API_URL.",
            "demo_behaviour": "Seeded demo quotes labeled DEMO with source and timestamp.",
        },
        {
            "provider": "news",
            "label": "Market news",
            "purpose": "Source-attributed market headlines with deduplication.",
            "configured": news_client.configured,
            "mode": "live" if news_client.configured else "demo",
            "status": existing["news"].status if "news" in existing else ("configured" if news_client.configured else "demo"),
            "last_checked_at": existing["news"].last_checked_at if "news" in existing else None,
            "setup": "Set NEWS_API_KEY for NewsAPI.org access.",
            "demo_behaviour": "Seeded sample headlines from FINOVEXA Demo News. Clearly labeled, never treated as live.",
        },
        {
            "provider": "email",
            "label": "Email delivery",
            "purpose": "Approved payment-reminder emails to the invoice customer's email address.",
            "configured": settings.email_ready,
            "mode": "live" if settings.email_ready else "simulated",
            "status": (
                existing["email"].status
                if "email" in existing
                else ("configured" if settings.email_ready else "simulated")
            ),
            "last_checked_at": existing["email"].last_checked_at if "email" in existing else None,
            "setup": (
                "Set SMTP_HOST, SMTP_FROM_EMAIL and SMTP_USERNAME/SMTP_PASSWORD, then "
                "EMAIL_DELIVERY_ENABLED=true in backend/.env."
            ),
            "demo_behaviour": (
                "Approved email reminders are recorded as simulated_sent. No external email is sent "
                "until delivery is explicitly enabled and configured."
            ),
        },
        {
            "provider": "sms",
            "label": "SMS delivery",
            "purpose": "Approved payment-reminder SMS messages to the invoice customer's mobile number.",
            "configured": settings.sms_ready,
            "mode": "live" if settings.sms_ready else "simulated",
            "status": (
                existing["sms"].status
                if "sms" in existing
                else ("configured" if settings.sms_ready else "simulated")
            ),
            "last_checked_at": existing["sms"].last_checked_at if "sms" in existing else None,
            "setup": (
                "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER, then "
                "SMS_DELIVERY_ENABLED=true in backend/.env."
            ),
            "demo_behaviour": (
                "Approved SMS reminders are recorded as simulated_sent. No SMS is sent until "
                "delivery is explicitly enabled and configured."
            ),
        },
        {
            "provider": "llm",
            "label": "AI provider",
            "purpose": "Natural-language orchestration over deterministic tools.",
            "configured": settings.llm_configured,
            "mode": "llm" if settings.llm_configured else "rules",
            "status": existing["llm"].status if "llm" in existing else ("configured" if settings.llm_configured else "fallback"),
            "last_checked_at": existing["llm"].last_checked_at if "llm" in existing else None,
            "setup": "Set LLM_PROVIDER=openai, LLM_API_KEY, LLM_MODEL and optionally LLM_BASE_URL.",
            "demo_behaviour": "Rules-based analyst answers questions by calling the same authorized tools. Clearly labeled.",
        },
    ]
    return {
        "items": items,
        "data_modes": [
            {"mode": "LIVE", "meaning": "Fetched from a configured external provider just now."},
            {"mode": "SANDBOX", "meaning": "Real provider API in sandbox; no real money moves."},
            {"mode": "SIMULATED", "meaning": "Generated locally for workflow demonstration; no external effect."},
            {"mode": "STALE", "meaning": "Previously live data older than its freshness window."},
            {"mode": "DEMO", "meaning": "Seeded sample data. Never represented as live."},
            {"mode": "UNAVAILABLE", "meaning": "Provider or quote missing. No silent substitution."},
        ],
        "secrets_note": "All credentials stay in backend environment variables. This page never returns secret values.",
    }


def check_integration(db: Session, user: User, provider: str) -> dict:
    status = "ok"
    message = ""
    details: dict = {}
    try:
        if provider == "paypal":
            if not paypal_client.configured:
                status = "demo"
                message = (
                    f"PayPal {paypal_client.environment} credentials are not configured. "
                    "Simulated checkout remains available."
                )
            else:
                details = paypal_client.check_connection()
                message = f"PayPal {paypal_client.environment} credentials accepted."
        elif provider == "upstox":
            if not upstox_client.configured:
                status = "demo"
                message = "Upstox access token is not configured. Demo quotes are in use."
            else:
                profile = upstox_client.get_profile()
                details = {"user_id": str(profile.get("data", {}).get("user_id", ""))[:20]}
                message = "Upstox authorization accepted."
        elif provider == "metals":
            if not metals_client.configured:
                status = "demo"
                message = "Metals provider is not configured. Demo quotes are in use."
            else:
                metals_client.fetch()
                message = "Metals provider reachable."
        elif provider == "news":
            if not news_client.configured:
                status = "demo"
                message = "News provider is not configured. Demo headlines are in use."
            else:
                news_client.fetch()
                message = "News provider reachable."
        elif provider == "email":
            if not settings.email_configured:
                status = "simulated"
                message = "Email delivery is not configured. Approved reminders are simulated."
            elif not settings.EMAIL_DELIVERY_ENABLED:
                status = "disabled"
                message = (
                    "SMTP is configured but EMAIL_DELIVERY_ENABLED is false. "
                    "Approved reminders are simulated."
                )
            else:
                message = check_email_connection()
        elif provider == "sms":
            if not settings.sms_configured:
                status = "simulated"
                message = "SMS delivery is not configured. Approved reminders are simulated."
            elif not settings.SMS_DELIVERY_ENABLED:
                status = "disabled"
                message = (
                    "Twilio is configured but SMS_DELIVERY_ENABLED is false. "
                    "Approved reminders are simulated."
                )
            else:
                message = check_sms_connection()
        elif provider == "llm":
            configured = settings.llm_configured
            status = "ok" if configured else "fallback"
            message = (
                f"LLM provider {settings.LLM_PROVIDER} configured."
                if configured
                else "No LLM configured. Deterministic analyst mode is active."
            )
        else:
            raise ValueError("Unsupported provider")
    except (PayPalError, UpstoxError, MetalsError, NewsError, DeliveryError) as exc:
        status = "error"
        message = str(exc)

    row = (
        db.query(IntegrationConfig)
        .filter(IntegrationConfig.user_id == user.id, IntegrationConfig.provider == provider)
        .one_or_none()
    )
    if row is None:
        row = IntegrationConfig(user_id=user.id, provider=provider)
        db.add(row)
    row.mode = _mode_for(provider)
    row.status = status
    row.last_checked_at = utcnow()
    row.details = {**details, "message": message}
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="integration.checked",
        entity_type="integration",
        entity_id=provider,
        detail={"status": status, "mode": row.mode},
    )
    db.commit()
    return {
        "provider": provider,
        "status": status,
        "mode": row.mode,
        "message": message,
        "checked_at": row.last_checked_at,
        "details": details,
    }
