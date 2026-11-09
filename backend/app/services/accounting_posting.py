"""Draft review lifecycle and posting approved drafts to vouchers.

Phase 4 moves a draft through ``draft -> pending_review -> approved -> posted``
(or ``rejected``). Posting copies the accountant-approved lines verbatim into an
``AccountingVoucher`` plus ``AccountingVoucherLine`` rows; GST is never
recomputed. A source change after generation must be explicitly acknowledged by
the reviewer before approval or posting, and every transition is audited by the
router.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import (
    AccountingEntryDraft,
    AccountingVoucher,
    AccountingVoucherLine,
    User,
    utcnow,
)
from .accounting import voucher_to_dict
from .accounting_math import q2, voucher_dedupe_hash

ZERO = Decimal("0.00")

SOURCE_CHANGED_DETAIL = (
    "The business source changed after this draft was generated. The draft and any "
    "posted voucher were preserved. Review the source differences, then retry with "
    "acknowledge_source_change=true."
)


def _lines(draft: AccountingEntryDraft) -> list:
    return sorted(draft.lines, key=lambda row: row.line_no)


def _validate_balanced(draft: AccountingEntryDraft) -> None:
    lines = _lines(draft)
    if len(lines) < 2:
        raise HTTPException(
            status_code=422, detail="A double-entry draft needs at least two lines."
        )
    debit = q2(sum((line.debit for line in lines), ZERO))
    credit = q2(sum((line.credit for line in lines), ZERO))
    if debit != credit:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Debits ({debit}) and credits ({credit}) must match. "
                f"Difference: {q2(debit - credit)}."
            ),
        )
    if debit <= ZERO:
        raise HTTPException(
            status_code=422, detail="A draft must carry a positive amount before review."
        )
    for line in lines:
        has_debit = line.debit > ZERO
        has_credit = line.credit > ZERO
        if has_debit == has_credit:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Line {line.line_no} must have exactly one of debit or credit."
                ),
            )


def _source_changed(draft: AccountingEntryDraft, acknowledge: bool) -> bool:
    txn = draft.transaction
    if txn is None or draft.source_hash == txn.source_hash:
        return False
    if acknowledge:
        draft.source_hash = txn.source_hash
        return True
    raise HTTPException(status_code=409, detail=SOURCE_CHANGED_DETAIL)


def submit_draft(
    db: Session, draft: AccountingEntryDraft, user: User
) -> tuple[AccountingEntryDraft, dict]:
    if draft.status not in ("draft", "rejected"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Only draft or rejected drafts can be submitted; this one is "
                f"{draft.status}."
            ),
        )
    _validate_balanced(draft)
    previous = draft.status
    draft.status = "pending_review"
    draft.submitted_at = utcnow()
    draft.reviewed_at = None
    draft.reviewed_by_user_id = None
    draft.review_note = None
    db.flush()
    return draft, {
        "previous_status": previous,
        "number": draft.number,
        "total_debit": str(draft.total_debit),
        "total_credit": str(draft.total_credit),
    }


def approve_draft(
    db: Session,
    draft: AccountingEntryDraft,
    user: User,
    *,
    note: str | None = None,
    acknowledge_source_change: bool = False,
) -> tuple[AccountingEntryDraft, dict]:
    if draft.status != "pending_review":
        raise HTTPException(
            status_code=409,
            detail=f"Only drafts pending review can be approved; this one is {draft.status}.",
        )
    _validate_balanced(draft)
    acknowledged = _source_changed(draft, acknowledge_source_change)
    draft.status = "approved"
    draft.reviewed_at = utcnow()
    draft.reviewed_by_user_id = user.id
    draft.review_note = (note or "").strip() or None
    db.flush()
    return draft, {
        "number": draft.number,
        "self_approved": draft.prepared_by_user_id == user.id,
        "source_change_acknowledged": acknowledged,
        "note": draft.review_note,
        "total_debit": str(draft.total_debit),
        "total_credit": str(draft.total_credit),
    }


def reject_draft(
    db: Session,
    draft: AccountingEntryDraft,
    user: User,
    *,
    note: str | None,
    acknowledge_source_change: bool = False,
) -> tuple[AccountingEntryDraft, dict]:
    if draft.status != "pending_review":
        raise HTTPException(
            status_code=409,
            detail=f"Only drafts pending review can be rejected; this one is {draft.status}.",
        )
    reason = (note or "").strip()
    if not reason:
        raise HTTPException(
            status_code=422, detail="A rejection reason is required."
        )
    acknowledged = _source_changed(draft, acknowledge_source_change)
    draft.status = "rejected"
    draft.reviewed_at = utcnow()
    draft.reviewed_by_user_id = user.id
    draft.review_note = reason
    db.flush()
    return draft, {
        "number": draft.number,
        "note": reason,
        "source_change_acknowledged": acknowledged,
    }


def _is_tax_ledger(name: str) -> bool:
    return "gst" in name.lower()


def _tax_kind(name: str) -> str | None:
    lowered = name.lower()
    if "igst" in lowered:
        return "igst"
    if "cgst" in lowered:
        return "cgst"
    if "sgst" in lowered:
        return "sgst"
    return None


def _is_bank_ledger(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("bank", "cash", "paypal", "wallet"))


def derive_voucher_header(draft: AccountingEntryDraft) -> dict:
    """Derive the voucher header from the approved draft lines.

    Tax amounts come from the explicit CGST/SGST/IGST ledger lines. A ledger that
    looks like GST but cannot be classified is rejected rather than guessed.
    """
    lines = _lines(draft)
    _validate_balanced(draft)
    total = q2(draft.total_debit)
    tax = {"cgst": ZERO, "sgst": ZERO, "igst": ZERO}
    for line in lines:
        if not _is_tax_ledger(line.ledger_name):
            continue
        kind = _tax_kind(line.ledger_name)
        if kind is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Ledger '{line.ledger_name}' looks like a GST ledger but is not "
                    "marked CGST, SGST or IGST. Rename it before posting."
                ),
            )
        tax[kind] += line.debit if line.debit > ZERO else line.credit
    tax_total = q2(tax["cgst"] + tax["sgst"] + tax["igst"])

    non_tax_credit = [line for line in lines if line.credit > ZERO and not _is_tax_ledger(line.ledger_name)]
    non_tax_debit = [line for line in lines if line.debit > ZERO and not _is_tax_ledger(line.ledger_name)]
    bank_lines = [line for line in lines if _is_bank_ledger(line.ledger_name)]

    if draft.voucher_type == "sale":
        pool = non_tax_credit or [line for line in lines if line.credit > ZERO]
        primary = max(pool, key=lambda row: (row.credit, -row.line_no), default=lines[0])
    elif draft.voucher_type in ("expense", "purchase"):
        pool = non_tax_debit or [line for line in lines if line.debit > ZERO]
        primary = max(pool, key=lambda row: (row.debit, -row.line_no), default=lines[0])
    elif draft.voucher_type == "receipt":
        pool = [line for line in bank_lines if line.debit > ZERO] or [
            line for line in lines if line.debit > ZERO
        ]
        primary = max(pool, key=lambda row: row.debit, default=lines[0])
    elif draft.voucher_type == "payment":
        pool = [line for line in bank_lines if line.credit > ZERO] or [
            line for line in lines if line.credit > ZERO
        ]
        primary = max(pool, key=lambda row: row.credit, default=lines[0])
    else:
        pool = [line for line in lines if line.debit > ZERO] or lines
        primary = max(pool, key=lambda row: row.debit, default=lines[0])

    taxable_value = q2(total - tax_total)
    gst_rate = ZERO
    if tax_total > ZERO and taxable_value > ZERO:
        gst_rate = q2(tax_total * Decimal("100") / taxable_value)

    bank_ledger = None
    if bank_lines:
        bank_ledger = max(
            bank_lines, key=lambda row: (row.debit + row.credit, -row.line_no)
        ).ledger_name

    txn = draft.transaction
    category = getattr(txn, "category", None) if txn is not None else None
    description = draft.narration or f"Posted from draft {draft.number}"

    return {
        "voucher_type": draft.voucher_type,
        "number": draft.number,
        "voucher_date": draft.voucher_date,
        "party_name": draft.party_name,
        "party_gstin": draft.party_gstin,
        "ledger_name": primary.ledger_name,
        "bank_ledger": bank_ledger,
        "category": category,
        "description": description,
        "taxable_value": taxable_value,
        "gst_rate": gst_rate,
        "inter_state": tax["igst"] > ZERO,
        "cgst_amount": q2(tax["cgst"]),
        "sgst_amount": q2(tax["sgst"]),
        "igst_amount": q2(tax["igst"]),
        "total_amount": total,
    }


def voucher_for_draft(db: Session, draft_id: int) -> AccountingVoucher | None:
    return (
        db.query(AccountingVoucher)
        .filter(AccountingVoucher.entry_draft_id == draft_id)
        .one_or_none()
    )


def posted_voucher_payload(db: Session, voucher: AccountingVoucher) -> dict:
    payload = voucher_to_dict(voucher)
    lines = (
        db.query(AccountingVoucherLine)
        .filter(AccountingVoucherLine.voucher_id == voucher.id)
        .order_by(AccountingVoucherLine.line_no)
        .all()
    )
    payload["lines"] = [
        {
            "line_no": line.line_no,
            "ledger_name": line.ledger_name,
            "description": line.description,
            "debit": line.debit,
            "credit": line.credit,
        }
        for line in lines
    ]
    payload["source_transaction_id"] = voucher.source_transaction_id
    payload["entry_draft_id"] = voucher.entry_draft_id
    return payload


def post_draft(
    db: Session,
    draft: AccountingEntryDraft,
    user: User,
    *,
    acknowledge_source_change: bool = False,
) -> tuple[AccountingVoucher, dict]:
    if draft.status == "posted":
        existing = voucher_for_draft(db, draft.id)
        raise HTTPException(
            status_code=409,
            detail=(
                f"This draft is already posted as voucher {existing.number}."
                if existing is not None
                else "This draft is already posted."
            ),
        )
    if draft.status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Only approved drafts can be posted; this one is {draft.status}.",
        )
    _validate_balanced(draft)
    acknowledged = _source_changed(draft, acknowledge_source_change)
    header = derive_voucher_header(draft)
    dedupe = voucher_dedupe_hash(
        draft.client_id,
        header["voucher_type"],
        header["number"],
        header["voucher_date"],
        header["total_amount"],
    )
    duplicate = (
        db.query(AccountingVoucher)
        .filter(
            AccountingVoucher.client_id == draft.client_id,
            AccountingVoucher.dedupe_hash == dedupe,
        )
        .one_or_none()
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Voucher {duplicate.number} with the same date and amount already exists "
                "for this client."
            ),
        )

    voucher = AccountingVoucher(
        client_id=draft.client_id,
        voucher_type=header["voucher_type"],
        number=header["number"],
        voucher_date=header["voucher_date"],
        party_name=header["party_name"],
        party_gstin=header["party_gstin"],
        ledger_name=header["ledger_name"],
        bank_ledger=header["bank_ledger"],
        category=header["category"],
        description=header["description"],
        taxable_value=header["taxable_value"],
        gst_rate=header["gst_rate"],
        inter_state=header["inter_state"],
        cgst_amount=header["cgst_amount"],
        sgst_amount=header["sgst_amount"],
        igst_amount=header["igst_amount"],
        total_amount=header["total_amount"],
        source="integration",
        status="posted",
        dedupe_hash=dedupe,
        created_by_user_id=user.id,
        source_transaction_id=draft.transaction_id,
        entry_draft_id=draft.id,
        source_hash=draft.source_hash,
    )
    db.add(voucher)
    db.flush()
    for line in _lines(draft):
        db.add(
            AccountingVoucherLine(
                voucher_id=voucher.id,
                line_no=line.line_no,
                ledger_name=line.ledger_name,
                description=line.description,
                debit=q2(line.debit),
                credit=q2(line.credit),
            )
        )

    now = utcnow()
    draft.status = "posted"
    txn = draft.transaction
    if txn is not None:
        txn.status = "posted"
        txn.issue_reason = None
        txn.reviewed_at = now
        txn.reviewed_by_user_id = user.id
    db.flush()
    return voucher, {
        "number": draft.number,
        "voucher_id": voucher.id,
        "voucher_number": voucher.number,
        "voucher_type": voucher.voucher_type,
        "total_amount": str(voucher.total_amount),
        "taxable_value": str(voucher.taxable_value),
        "source_change_acknowledged": acknowledged,
    }
