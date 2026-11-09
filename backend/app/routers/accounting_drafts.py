"""Accountant-facing draft voucher generation, review and posting routes.

Seniors generate and edit drafts, submit them for review, approve or reject them
and post approved drafts. Juniors can read drafts, review state and mappings for
their assigned clients only. Posting requires an approved draft and copies the
approved lines into a posted voucher without recomputing GST.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import DraftDecisionIn, DraftGenerateIn, EntryDraftUpdateIn, LedgerMappingIn
from ..security import get_current_junior_accountant, get_current_senior_accountant
from ..services.accounting import ensure_client_access
from ..services.accounting_drafts import (
    build_suggestion,
    client_or_404,
    deactivate_mapping,
    draft_to_dict,
    generate_drafts,
    get_draft,
    list_drafts,
    list_mappings,
    source_transaction_for,
    update_draft,
    upsert_mapping,
)
from ..services.accounting_integration import integration_summary
from ..services.accounting_posting import (
    approve_draft,
    post_draft,
    posted_voucher_payload,
    reject_draft,
    submit_draft,
    voucher_for_draft,
)
from ..services.audit import log_audit

router = APIRouter(prefix="/accounting", tags=["Accounting drafts"])


def _audit(db: Session, user: User, action: str, *, client_id: int, entity: str, entity_id, detail: dict) -> None:
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action=action,
        entity_type=entity,
        entity_id=entity_id,
        detail={"client_id": client_id, **detail},
    )


def _draft_response(db: Session, client_id: int, draft_id: int) -> dict:
    draft = get_draft(db, client_id, draft_id)
    payload = draft_to_dict(draft)
    voucher = voucher_for_draft(db, draft.id)
    if voucher is not None:
        payload["voucher"] = posted_voucher_payload(db, voucher)
    return payload


# ------------------------------------------------------------------ senior


@router.post("/senior/clients/{client_id}/integration/drafts/generate")
def generate_client_drafts(
    client_id: int,
    payload: DraftGenerateIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    result = generate_drafts(
        db,
        client,
        user,
        transaction_ids=payload.transaction_ids,
        limit=payload.limit,
    )
    for draft in result["drafts"]:
        _audit(
            db,
            user,
            "accounting.entry_draft_generated",
            client_id=client.id,
            entity="accounting_entry_draft",
            entity_id=draft["id"],
            detail={
                "transaction_id": draft["transaction_id"],
                "number": draft["number"],
                "voucher_type": draft["voucher_type"],
                "total_debit": str(draft["total_debit"]),
                "total_credit": str(draft["total_credit"]),
            },
        )
    _audit(
        db,
        user,
        "accounting.entry_drafts_generated",
        client_id=client.id,
        entity="accounting_client",
        entity_id=client.id,
        detail={
            "generated": result["generated"],
            "skipped": result["skipped"],
            "errors": result["errors"],
            "limit": payload.limit,
        },
    )
    db.commit()
    result["integration"] = integration_summary(db, client)
    return result


@router.get("/senior/clients/{client_id}/integration/drafts")
def list_client_drafts(
    client_id: int,
    status: str | None = None,
    voucher_type: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    return list_drafts(
        db,
        client.id,
        status=status,
        voucher_type=voucher_type,
        limit=limit,
        offset=offset,
    )


@router.get("/senior/clients/{client_id}/integration/drafts/{draft_id}")
def get_client_draft(
    client_id: int,
    draft_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    return _draft_response(db, client.id, draft_id)


@router.patch("/senior/clients/{client_id}/integration/drafts/{draft_id}")
def edit_client_draft(
    client_id: int,
    draft_id: int,
    payload: EntryDraftUpdateIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    draft = get_draft(db, client.id, draft_id)
    updated, audit_detail = update_draft(db, draft, payload, user)
    _audit(
        db,
        user,
        "accounting.entry_draft_updated",
        client_id=client.id,
        entity="accounting_entry_draft",
        entity_id=updated.id,
        detail=audit_detail,
    )
    db.commit()
    return draft_to_dict(get_draft(db, client.id, updated.id))


@router.post("/senior/clients/{client_id}/integration/drafts/{draft_id}/submit")
def submit_client_draft(
    client_id: int,
    draft_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    draft = get_draft(db, client.id, draft_id)
    submitted, detail = submit_draft(db, draft, user)
    _audit(
        db,
        user,
        "accounting.entry_draft_submitted",
        client_id=client.id,
        entity="accounting_entry_draft",
        entity_id=submitted.id,
        detail=detail,
    )
    db.commit()
    return _draft_response(db, client.id, submitted.id)


@router.post("/senior/clients/{client_id}/integration/drafts/{draft_id}/approve")
def approve_client_draft(
    client_id: int,
    draft_id: int,
    payload: DraftDecisionIn | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    draft = get_draft(db, client.id, draft_id)
    approved, detail = approve_draft(
        db,
        draft,
        user,
        note=payload.note if payload else None,
        acknowledge_source_change=bool(payload and payload.acknowledge_source_change),
    )
    _audit(
        db,
        user,
        "accounting.entry_draft_approved",
        client_id=client.id,
        entity="accounting_entry_draft",
        entity_id=approved.id,
        detail=detail,
    )
    db.commit()
    return _draft_response(db, client.id, approved.id)


@router.post("/senior/clients/{client_id}/integration/drafts/{draft_id}/reject")
def reject_client_draft(
    client_id: int,
    draft_id: int,
    payload: DraftDecisionIn | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    draft = get_draft(db, client.id, draft_id)
    rejected, detail = reject_draft(
        db,
        draft,
        user,
        note=payload.note if payload else None,
        acknowledge_source_change=bool(payload and payload.acknowledge_source_change),
    )
    _audit(
        db,
        user,
        "accounting.entry_draft_rejected",
        client_id=client.id,
        entity="accounting_entry_draft",
        entity_id=rejected.id,
        detail=detail,
    )
    db.commit()
    return _draft_response(db, client.id, rejected.id)


@router.post("/senior/clients/{client_id}/integration/drafts/{draft_id}/post")
def post_client_draft(
    client_id: int,
    draft_id: int,
    payload: DraftDecisionIn | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    draft = get_draft(db, client.id, draft_id)
    voucher, detail = post_draft(
        db,
        draft,
        user,
        acknowledge_source_change=bool(payload and payload.acknowledge_source_change),
    )
    _audit(
        db,
        user,
        "accounting.entry_draft_posted",
        client_id=client.id,
        entity="accounting_voucher",
        entity_id=voucher.id,
        detail={"draft_id": draft.id, **detail},
    )
    db.commit()
    return _draft_response(db, client.id, draft.id)


@router.get("/senior/clients/{client_id}/integration/transactions/{transaction_id}/suggestion")
def preview_transaction_suggestion(
    client_id: int,
    transaction_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    txn = source_transaction_for(db, client.id, transaction_id)
    return build_suggestion(db, client, txn)


@router.get("/senior/clients/{client_id}/integration/ledger-mappings")
def get_ledger_mappings(
    client_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    return list_mappings(db, client.id)


@router.put("/senior/clients/{client_id}/integration/ledger-mappings")
def save_ledger_mapping(
    client_id: int,
    payload: LedgerMappingIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    mapping = upsert_mapping(db, client, payload, user)
    _audit(
        db,
        user,
        "accounting.ledger_mapping_saved",
        client_id=client.id,
        entity="accounting_ledger_mapping",
        entity_id=mapping.id,
        detail={
            "transaction_type": mapping.transaction_type,
            "category": mapping.category,
            "debit_ledger": mapping.debit_ledger,
            "credit_ledger": mapping.credit_ledger,
            "tax_ledger": mapping.tax_ledger,
            "bank_ledger": mapping.bank_ledger,
        },
    )
    db.commit()
    return {
        "id": mapping.id,
        "transaction_type": mapping.transaction_type,
        "category": mapping.category,
        "debit_ledger": mapping.debit_ledger,
        "credit_ledger": mapping.credit_ledger,
        "tax_ledger": mapping.tax_ledger,
        "bank_ledger": mapping.bank_ledger,
        "notes": mapping.notes,
        "is_active": mapping.is_active,
    }


@router.delete("/senior/clients/{client_id}/integration/ledger-mappings/{mapping_id}")
def remove_ledger_mapping(
    client_id: int,
    mapping_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = client_or_404(db, client_id)
    mapping = deactivate_mapping(db, client, mapping_id, user)
    _audit(
        db,
        user,
        "accounting.ledger_mapping_removed",
        client_id=client.id,
        entity="accounting_ledger_mapping",
        entity_id=mapping.id,
        detail={"transaction_type": mapping.transaction_type, "category": mapping.category},
    )
    db.commit()
    return {"id": mapping.id, "is_active": mapping.is_active}


# ------------------------------------------------------------------ junior (read-only)


@router.get("/junior/clients/{client_id}/integration/drafts")
def list_junior_client_drafts(
    client_id: int,
    status: str | None = None,
    voucher_type: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    return list_drafts(
        db,
        client.id,
        status=status,
        voucher_type=voucher_type,
        limit=limit,
        offset=offset,
    )


@router.get("/junior/clients/{client_id}/integration/drafts/{draft_id}")
def get_junior_client_draft(
    client_id: int,
    draft_id: int,
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    return _draft_response(db, client.id, draft_id)


@router.get("/junior/clients/{client_id}/integration/ledger-mappings")
def get_junior_ledger_mappings(
    client_id: int,
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    return list_mappings(db, client.id)
