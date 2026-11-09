from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditEvent, User
from ..security import get_current_user
from ..services.audit import audit_to_dict

router = APIRouter(tags=["Activity and audit"])


@router.get("/audit-log")
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    action: str | None = Query(default=None, max_length=80),
    entity_type: str | None = Query(default=None, max_length=40),
    start: date | None = None,
    end: date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AuditEvent).filter(AuditEvent.user_id == user.id)
    if action:
        query = query.filter(AuditEvent.action.like(f"{action}%"))
    if entity_type:
        query = query.filter(AuditEvent.entity_type == entity_type)
    if start:
        query = query.filter(AuditEvent.created_at >= start)
    if end:
        query = query.filter(AuditEvent.created_at < end)
    rows = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit).all()
    return {
        "items": [audit_to_dict(row) for row in rows],
        "count": len(rows),
        "protection_note": "Audit details never include credentials, tokens, passwords or card data.",
    }


@router.get("/audit-log/actions")
def audit_actions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rows = (
        db.query(AuditEvent.action, AuditEvent.entity_type)
        .filter(AuditEvent.user_id == user.id)
        .distinct()
        .order_by(AuditEvent.action.asc())
        .all()
    )
    return {
        "items": [{"action": action, "entity_type": entity_type} for action, entity_type in rows]
    }
