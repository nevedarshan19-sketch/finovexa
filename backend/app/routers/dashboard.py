from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, rate_limit
from ..services.agents import generate_business_insights, monitoring_summary
from ..services.audit import log_audit
from ..services.business_context import active_business
from ..services.dashboard import analytics_snapshot, dashboard_snapshot
from ..services.finance import q2

router = APIRouter(tags=["Dashboard and analytics"])


@router.get("/dashboard")
def dashboard(
    days: int = Query(default=30, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return dashboard_snapshot(db, user, days)


@router.get("/analytics")
def analytics(
    days: int = Query(default=90, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return analytics_snapshot(db, user, days)


@router.get("/agents/business-manager/monitor")
def business_manager_monitor(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return monitoring_summary(db, user)


@router.post(
    "/agents/business-manager/analyze",
    dependencies=[Depends(rate_limit("business_analysis", 6, 60))],
)
def analyze_business(
    days: int = Query(default=90, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if active_business(db, user) is None:
        raise HTTPException(status_code=409, detail="Complete your business profile first.")
    insights = generate_business_insights(db, user, days)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="agent.business_manager_run",
        entity_type="insight_batch",
        detail={"days": days, "insight_count": len(insights)},
    )
    db.commit()
    return {
        "mode": "deterministic",
        "note": (
            "Insights are computed from ledger records by the FINOVEXA analysis engine. "
            "No figures are invented by an LLM; expected impacts are labelled estimates."
        ),
        "insights": [
            {
                "id": insight.id,
                "agent": insight.agent,
                "title": insight.title,
                "finding": insight.finding,
                "evidence": insight.evidence,
                "impact_amount": q2(insight.impact_amount)
                if insight.impact_amount is not None
                else None,
                "confidence": insight.confidence,
                "limitations": insight.limitations,
                "recommended_action": insight.recommended_action,
                "mode": insight.mode,
                "created_at": insight.created_at,
            }
            for insight in insights
        ],
    }
