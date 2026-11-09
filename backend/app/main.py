from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine, ensure_schema_upgrades
from .routers import (
    accounting,
    accounting_drafts,
    ai,
    approvals,
    audit,
    auth,
    billing,
    business_integration,
    cashflow,
    credit,
    dashboard,
    developer,
    employee,
    invoices,
    market,
    market_public,
    payment_connect,
    payments,
    profile,
    public as public_router,
    settings as settings_router,
    tally_migration,
    tax,
    team,
)
from .security import get_current_developer, get_current_owner
from .services.business_migration import ensure_business_schema
from .seed import (
    ensure_global_market_data,
    provision_initial_accounts,
    seed_accounting_practice,
    seed_demo_user,
    seed_developer,
)
from .services.income_tax import seed_tax_rules
from .services.integrations.paypal import paypal_client
from .services.paypal import load_paypal_runtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("finovexa")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_upgrades(engine)
    ensure_business_schema(engine)
    demo_seed_enabled = settings.AUTO_SEED and settings.ENV != "production"
    if settings.AUTO_SEED and settings.ENV == "production":
        logger.warning("AUTO_SEED is enabled in production; demo data is skipped.")
    provisioned: dict[str, str] = {}
    with SessionLocal() as db:
        ensure_global_market_data(db)
        try:
            provisioned = provision_initial_accounts(db)
        except Exception:
            logger.exception("Initial account provisioning failed; existing accounts are unaffected.")
        if demo_seed_enabled:
            try:
                seed_demo_user(db)
            except Exception:
                logger.exception("Demo seed failed; the API will still start without demo data.")
            try:
                seed_accounting_practice(db)
            except Exception:
                logger.exception("Accounting practice seed failed; the API will still start.")
        if settings.developer_configured:
            try:
                seed_developer(db)
            except Exception:
                logger.exception("Developer account seed failed; the API will still start.")
        try:
            load_paypal_runtime(db)
        except Exception:
            logger.exception("PayPal runtime selection could not be loaded; defaults are in use.")
        try:
            seed_tax_rules(db)
        except Exception:
            logger.exception("Income-tax rule sets could not be seeded; tax estimates may be unavailable.")
    logger.info(
        "FINOVEXA API started · env=%s · demo_seed=%s · initial_accounts=%s · developer_console=%s · llm=%s · paypal=%s (%s) · upstox=%s",
        settings.ENV,
        "on" if demo_seed_enabled else "off",
        ",".join(
            f"{role}:{status}" for role, status in provisioned.items() if status != "not_configured"
        )
        or "none",
        "configured" if settings.developer_configured else "disabled",
        "configured" if settings.llm_configured else "deterministic-fallback",
        paypal_client.mode,
        paypal_client.environment,
        "configured" if settings.upstox_configured else "demo",
    )
    yield


app = FastAPI(
    title="FINOVEXA AI API",
    description=(
        "Autonomous business manager, money recovery, cash-flow forecasting, market intelligence "
        "and owner-controlled approvals for small businesses."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-FINOVEXA-Demo-Signature"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith(settings.API_PREFIX):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if settings.ENV == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred. No financial action was executed. Check server logs.",
        },
    )


app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(employee.router, prefix=settings.API_PREFIX)
app.include_router(payments.public_router, prefix=settings.API_PREFIX)
app.include_router(public_router.router, prefix=settings.API_PREFIX)
app.include_router(market_public.router, prefix=settings.API_PREFIX)
app.include_router(
    developer.router,
    prefix=settings.API_PREFIX,
    dependencies=[Depends(get_current_developer)],
)

# Every existing business route is owner-only. Employees use /api/employee only.
for module in (
    profile,
    dashboard,
    invoices,
    billing,
    cashflow,
    market,
    ai,
    approvals,
    business_integration,
    payments,
    audit,
    settings_router,
    team,
    tax,
    credit,
):
    app.include_router(
        module.router,
        prefix=settings.API_PREFIX,
        dependencies=[Depends(get_current_owner)],
    )

# The accounting practice spans several roles, so each route carries its own guard.
app.include_router(accounting.router, prefix=settings.API_PREFIX)
app.include_router(accounting_drafts.router, prefix=settings.API_PREFIX)
app.include_router(tally_migration.router, prefix=settings.API_PREFIX)
app.include_router(payment_connect.router, prefix=settings.API_PREFIX)
app.include_router(payment_connect.accounting_router, prefix=settings.API_PREFIX)


@app.get("/api/health", tags=["System"])
def health():
    return {
        "status": "ok",
        "service": "finovexa-api",
        "version": "1.0.0",
        "time": datetime.now(timezone.utc).isoformat(),
        "environment": settings.ENV,
        "modes": {
            "llm": "configured" if settings.llm_configured else "deterministic_fallback",
            "paypal": settings.paypal_mode,
            "upstox": "configured" if settings.upstox_configured else "demo",
            "live_trading_enabled": settings.UPSTOX_LIVE_TRADING_ENABLED,
            "developer_console": "configured" if settings.developer_configured else "disabled",
        },
        "note": "Credentials are never returned by this endpoint.",
    }


if (FRONTEND_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )


def _index_response() -> FileResponse:
    return FileResponse(
        FRONTEND_DIST / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/", include_in_schema=False)
def root():
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return _index_response()
    return {
        "name": "FINOVEXA AI API",
        "docs": "/api/docs",
        "health": "/api/health",
    }


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if not (FRONTEND_DIST / "index.html").is_file():
        raise HTTPException(status_code=404, detail="Not found")
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    target = (FRONTEND_DIST / full_path).resolve()
    dist_root = FRONTEND_DIST.resolve()
    if target != dist_root and dist_root not in target.parents:
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_file():
        if target == dist_root / "index.html":
            return _index_response()
        return FileResponse(target)
    if "." in Path(full_path).name:
        raise HTTPException(status_code=404, detail="Not found")
    return _index_response()
