from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CashForecast, FinancialObligation, User
from ..security import get_current_user, rate_limit
from ..services.audit import log_audit
from ..services.business_context import require_business
from ..services.finance import q2
from ..services.forecasting import SCENARIOS, build_forecast, sensitivity_analysis

router = APIRouter(prefix="/cashflow", tags=["Cash flow"])


def _profile(db: Session, user: User):
    return require_business(db, user)


@router.get("/forecast")
def forecast(
    horizon: int = Query(default=30, ge=7, le=90),
    scenario: str = Query(default="base"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail="Unknown scenario.")
    return build_forecast(db, _profile(db, user), horizon, scenario)


@router.get("/overview")
def overview(
    horizon: int = Query(default=30, ge=7, le=90),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _profile(db, user)
    base = build_forecast(db, profile, horizon, "base")
    scenarios = [
        {
            "key": key,
            "label": SCENARIOS[key]["label"],
            "description": SCENARIOS[key]["description"],
            **{
                field: build_forecast(db, profile, horizon, key)[field]
                for field in (
                    "closing_balance",
                    "minimum_balance",
                    "minimum_balance_date",
                    "shortfall_date",
                    "investable_surplus",
                    "total_expected_inflow",
                    "total_expected_outflow",
                )
            },
        }
        for key in ("conservative", "base", "optimistic")
    ]
    obligations = (
        db.query(FinancialObligation)
        .filter(FinancialObligation.user_id == user.id)
        .order_by(FinancialObligation.due_date.asc())
        .limit(60)
        .all()
    )
    today = date.today()
    return {
        "forecast": base,
        "scenarios": scenarios,
        "sensitivity": sensitivity_analysis(db, profile, horizon),
        "obligations": [
            {
                "id": row.id,
                "name": row.name,
                "category": row.category,
                "amount": q2(row.amount),
                "due_date": row.due_date,
                "status": row.status
                if row.status != "scheduled" or row.due_date >= today
                else "scheduled_past_due",
                "recurring": row.recurring,
                "notes": row.notes,
            }
            for row in obligations
        ],
        "definitions": {
            "projected_balance": "Recorded opening cash + probability-weighted expected inflows - scheduled outflows and average operating expenses.",
            "minimum_reserve": "Owner-defined floor below which projected cash should not fall.",
            "investable_surplus": "Only the lowest projected balance above the reserve. Not guaranteed cash and not automatically available to invest.",
            "shortfall": "First projected day the balance falls below the minimum reserve.",
            "receivables_note": "Expected receivables are probability-weighted. Overdue invoices are delayed, never treated as guaranteed.",
        },
        "data_quality": base["assumptions"]["data_quality"],
    }


@router.get("/forecasts")
def saved_forecasts(
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CashForecast)
        .filter(CashForecast.user_id == user.id)
        .order_by(CashForecast.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "horizon_days": row.horizon_days,
                "scenario": row.scenario,
                "opening_balance": q2(row.opening_balance),
                "closing_balance": q2(row.closing_balance),
                "minimum_reserve": q2(row.minimum_reserve),
                "shortfall_date": row.shortfall_date,
                "assumptions": row.assumptions,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.post(
    "/forecasts",
    status_code=201,
    dependencies=[Depends(rate_limit("forecast_snapshot", 12, 60))],
)
def save_forecast_snapshot(
    horizon: int = Query(default=30, ge=7, le=90),
    scenario: str = Query(default="base"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail="Unknown scenario.")
    result = build_forecast(db, _profile(db, user), horizon, scenario)
    row = CashForecast(
        user_id=user.id,
        horizon_days=horizon,
        scenario=scenario,
        opening_balance=result["opening_balance"],
        closing_balance=result["closing_balance"],
        minimum_reserve=result["minimum_reserve"],
        shortfall_date=date.fromisoformat(result["shortfall_date"])
        if result["shortfall_date"]
        else None,
        series=result["series"],
        assumptions=result["assumptions"],
    )
    db.add(row)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="cashflow.forecast_saved",
        entity_type="cash_forecast",
        entity_id=None,
        detail={"horizon_days": horizon, "scenario": scenario},
    )
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "message": "Forecast snapshot saved. It is a projection, not a bank balance.",
        "forecast": result,
    }
