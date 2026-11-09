from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ContactMessage, utcnow
from ..schemas import ContactMessageIn
from ..security import rate_limit
from ..services.audit import log_audit

router = APIRouter(prefix="/public", tags=["Public site"])


def _new_contact_reference(db: Session) -> str:
    for _ in range(10):
        candidate = f"CNT-{secrets.token_hex(3).upper()}"
        if db.query(ContactMessage).filter(ContactMessage.reference == candidate).one_or_none() is None:
            return candidate
    return f"CNT-{secrets.token_hex(5).upper()}"


@router.post(
    "/contact",
    status_code=201,
    dependencies=[Depends(rate_limit("public_contact", 6, 600))],
)
def submit_contact(payload: ContactMessageIn, db: Session = Depends(get_db)):
    message = ContactMessage(
        reference=_new_contact_reference(db),
        name=payload.name.strip(),
        email=str(payload.email).lower().strip(),
        organisation=(payload.organisation or "").strip() or None,
        phone=(payload.phone or "").strip() or None,
        category=payload.category,
        subject=payload.subject.strip(),
        message=payload.message.strip(),
        consent_at=utcnow(),
        status="new",
    )
    db.add(message)
    log_audit(
        db,
        user_id=None,
        actor="public visitor",
        action="public.contact_received",
        entity_type="contact_message",
        entity_id=message.reference,
        detail={"category": message.category},
    )
    db.commit()
    return {
        "reference": message.reference,
        "message": "Your message has been recorded. The platform team can review it from the developer console.",
        "note": "No automatic email is sent. Contact details are published only when configured.",
    }
