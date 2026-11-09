"""Read-only Business Manager view of the accounting integration.

Owners cannot link, sync, edit or approve anything from these routes. They can
only see whether their own business is linked and the source transactions that
were copied into their own engagement's inbox.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user
from ..services.accounting_integration import (
    integration_summary,
    list_client_transactions,
    owner_client,
)

router = APIRouter(prefix="/integration", tags=["Business integration"])

EMPTY_COUNTS = {"total": 0, "pending": 0, "drafted": 0, "needs_attention": 0, "ignored": 0}
EMPTY_DRAFTS = {
    "total": 0,
    "draft": 0,
    "pending_review": 0,
    "approved": 0,
    "rejected": 0,
    "posted": 0,
}


def _require_owner(user: User) -> User:
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Business owner access required.")
    return user


@router.get("/accounting")
def accounting_integration_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_owner(user)
    client = owner_client(db, user)
    if client is None or client.business_profile_id is None:
        return {
            "linked": False,
            "status": "not_linked",
            "business": None,
            "enabled_at": None,
            "last_synced_at": None,
            "counts": EMPTY_COUNTS,
            "drafts": EMPTY_DRAFTS,
            "last_run": None,
            "note": (
                "No accounting engagement is linked to this business. "
                "Your accountant controls the link."
            ),
        }
    payload = integration_summary(db, client, owner_view=True)
    payload["note"] = (
        "Read-only status. Your accountant reviews and approves every accounting entry."
    )
    return payload


@router.get("/accounting/transactions")
def accounting_integration_transactions(
    status: str | None = None,
    source_type: str | None = None,
    transaction_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_owner(user)
    client = owner_client(db, user)
    if client is None or client.business_profile_id is None:
        return {"items": [], "total": 0, "linked": False}

    payload = list_client_transactions(
        db,
        client.id,
        status=status,
        source_type=source_type,
        transaction_type=transaction_type,
        limit=limit,
        offset=offset,
    )
    payload["linked"] = True
    return payload
