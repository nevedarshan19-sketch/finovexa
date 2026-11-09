from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent


def log_audit(
    db: Session,
    *,
    user_id: int | None,
    actor: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        user_id=user_id,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail or {},
    )
    db.add(event)
    return event


def audit_to_dict(event: AuditEvent) -> dict:
    return {
        "id": event.id,
        "actor": event.actor,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "detail": event.detail,
        "created_at": event.created_at,
    }
