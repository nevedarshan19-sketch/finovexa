"""Draft voucher generation with suggested ledgers.

Phase 3 turns eligible inbox rows into balanced double-entry drafts. Nothing in
this module posts a voucher: drafts stay editable until an accountant reviews and
approves them in a later step. Ledger names are suggestions drawn from the
client's own vouchers, explicit per-client mappings and documented defaults.
GST amounts are copied from the business source, never recomputed or guessed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from ..models import (
    AccountingBusinessTransaction,
    AccountingClient,
    AccountingEntryDraft,
    AccountingEntryDraftLine,
    AccountingLedgerMapping,
    AccountingVoucher,
    User,
    utcnow,
)
from ..schemas import EntryDraftUpdateIn, LedgerMappingIn
from .accounting_math import financial_year_for, q2

ZERO = Decimal("0.00")

MAPPING_TYPES = ("sale", "receipt", "refund", "expense")
DRAFT_TYPES = ("sale", "receipt", "payment", "expense", "journal")
INBOX_TO_VOUCHER = {
    "sale": "sale",
    "receipt": "receipt",
    "refund": "payment",
    "expense": "expense",
}
NUMBER_PREFIX = {
    "sale": "DR-S",
    "receipt": "DR-R",
    "payment": "DR-P",
    "expense": "DR-E",
    "journal": "DR-J",
}
EDITABLE_STATUSES = ("draft", "rejected")

EXPENSE_LEDGER_HINTS = {
    "rent": "Rent expense",
    "utilities": "Utilities",
    "utility": "Utilities",
    "salary": "Salaries",
    "salaries": "Salaries",
    "payroll": "Salaries",
    "marketing": "Marketing expenses",
    "advertising": "Marketing expenses",
    "software": "Software subscriptions",
    "subscription": "Software subscriptions",
    "professional": "Professional fees",
    "legal": "Professional fees",
    "travel": "Travel expenses",
    "logistics": "Freight and transport",
    "freight": "Freight and transport",
    "transport": "Freight and transport",
    "office supplies": "Office supplies",
    "equipment": "Equipment",
}


# ------------------------------------------------------------------ lookups


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _trim(value: str | None, limit: int = 120) -> str | None:
    cleaned = (value or "").strip()
    return cleaned[:limit] if cleaned else None


def client_or_404(db: Session, client_id: int) -> AccountingClient:
    client = db.get(AccountingClient, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client record not found.")
    return client


def _requires_business(client: AccountingClient) -> None:
    if client.business_profile_id is None or client.integration_status != "linked":
        raise HTTPException(
            status_code=409,
            detail="Link this engagement to a business before generating drafts.",
        )


# ------------------------------------------------------------------ client defaults


def _latest_voucher(
    db: Session, client_id: int, voucher_type: str | None = None, *, bank_only: bool = False
) -> AccountingVoucher | None:
    query = db.query(AccountingVoucher).filter(AccountingVoucher.client_id == client_id)
    if voucher_type:
        query = query.filter(AccountingVoucher.voucher_type == voucher_type)
    if bank_only:
        query = query.filter(AccountingVoucher.bank_ledger.isnot(None))
    return query.order_by(
        AccountingVoucher.voucher_date.desc(), AccountingVoucher.id.desc()
    ).first()


def client_ledger_defaults(db: Session, client_id: int) -> dict:
    """Suggest ledgers from the client's own recorded vouchers where possible."""
    sales = _latest_voucher(db, client_id, "sale")
    bank = _latest_voucher(db, client_id, bank_only=True)
    expense_rows = (
        db.query(AccountingVoucher)
        .filter(
            AccountingVoucher.client_id == client_id,
            AccountingVoucher.voucher_type == "expense",
        )
        .order_by(AccountingVoucher.voucher_date.desc(), AccountingVoucher.id.desc())
        .limit(100)
        .all()
    )
    expense_ledgers: dict[str, str] = {}
    for row in expense_rows:
        key = (row.category or "").strip().lower()
        if key and key not in expense_ledgers:
            expense_ledgers[key] = row.ledger_name
    return {
        "sales": sales.ledger_name if sales else "Sales",
        "bank": (bank.bank_ledger if bank and bank.bank_ledger else None),
        "expense_ledgers": expense_ledgers,
        "receivables": "Accounts Receivable",
        "payables": "Sundry Creditors",
    }


def _expense_ledger(category: str | None, defaults: dict) -> str:
    key = (category or "").strip().lower()
    if key and key in defaults["expense_ledgers"]:
        return defaults["expense_ledgers"][key]
    for hint, ledger in EXPENSE_LEDGER_HINTS.items():
        if hint in key:
            return ledger
    cleaned = (category or "").strip()
    if not cleaned:
        return "General expenses"
    if cleaned.lower().endswith(("expense", "expenses")):
        return cleaned[:120]
    return f"{cleaned} expense"[:120]


def _bank_ledger(txn: AccountingBusinessTransaction, mapping_bank: str | None, defaults: dict) -> str:
    if mapping_bank:
        return mapping_bank
    method = (txn.snapshot or {}).get("method") or ""
    if method == "cash":
        return "Cash"
    if method == "paypal":
        return "PayPal Clearing"
    return defaults["bank"] or "Bank"


def _party_ledger(txn: AccountingBusinessTransaction) -> str:
    name = (txn.party_name or "").strip()
    if name and name.lower() != "unnamed vendor":
        return name[:120]
    return "Sundry Creditors" if txn.transaction_type == "expense" else "Sundry Debtors"


# ------------------------------------------------------------------ mappings


def _mapping_query(db: Session, client_id: int, transaction_type: str, category: str):
    lowered = (category or "").strip().lower()
    return (
        db.query(AccountingLedgerMapping)
        .filter(
            AccountingLedgerMapping.client_id == client_id,
            AccountingLedgerMapping.transaction_type == transaction_type,
            AccountingLedgerMapping.is_active.is_(True),
        )
        .filter(
            or_(
                func.lower(AccountingLedgerMapping.category) == lowered,
                AccountingLedgerMapping.category == "",
            )
        )
        .order_by(func.length(AccountingLedgerMapping.category).desc())
        .first()
    )


def _mapping_fields(row: AccountingLedgerMapping | None) -> dict:
    if row is None:
        return {
            "debit_ledger": None,
            "credit_ledger": None,
            "tax_ledger": None,
            "bank_ledger": None,
        }
    return {
        "debit_ledger": row.debit_ledger or None,
        "credit_ledger": row.credit_ledger or None,
        "tax_ledger": row.tax_ledger,
        "bank_ledger": row.bank_ledger,
    }


def mapping_to_dict(row: AccountingLedgerMapping) -> dict:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "transaction_type": row.transaction_type,
        "category": row.category,
        "debit_ledger": row.debit_ledger or None,
        "credit_ledger": row.credit_ledger or None,
        "tax_ledger": row.tax_ledger,
        "bank_ledger": row.bank_ledger,
        "notes": row.notes,
        "is_active": row.is_active,
        "updated_at": _iso(row.updated_at),
    }


def list_mappings(db: Session, client_id: int) -> dict:
    rows = (
        db.query(AccountingLedgerMapping)
        .filter(AccountingLedgerMapping.client_id == client_id)
        .order_by(
            AccountingLedgerMapping.transaction_type,
            AccountingLedgerMapping.category,
            AccountingLedgerMapping.id,
        )
        .all()
    )
    return {
        "items": [mapping_to_dict(row) for row in rows],
        "client_defaults": client_ledger_defaults(db, client_id),
    }


def upsert_mapping(
    db: Session, client: AccountingClient, payload: LedgerMappingIn, user: User
) -> AccountingLedgerMapping:
    category = (payload.category or "").strip()
    row = (
        db.query(AccountingLedgerMapping)
        .filter(
            AccountingLedgerMapping.client_id == client.id,
            AccountingLedgerMapping.transaction_type == payload.transaction_type,
            AccountingLedgerMapping.category == category,
        )
        .one_or_none()
    )
    fields = {
        # debit_ledger and credit_ledger are non-nullable storage columns, so a
        # partial override (for example bank-only) stores an empty string.
        "debit_ledger": _trim(payload.debit_ledger) or "",
        "credit_ledger": _trim(payload.credit_ledger) or "",
        "tax_ledger": _trim(payload.tax_ledger),
        "bank_ledger": _trim(payload.bank_ledger),
    }
    if not any(fields.values()):
        raise HTTPException(
            status_code=422,
            detail="Set at least one suggested ledger (debit, credit, tax or bank).",
        )
    if row is None:
        row = AccountingLedgerMapping(
            client_id=client.id,
            transaction_type=payload.transaction_type,
            category=category,
            **fields,
            notes=_trim(payload.notes, 2000),
            created_by_user_id=user.id,
        )
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
        row.notes = _trim(payload.notes, 2000)
        row.is_active = True
    db.flush()
    return row


def deactivate_mapping(
    db: Session, client: AccountingClient, mapping_id: int, user: User
) -> AccountingLedgerMapping:
    row = (
        db.query(AccountingLedgerMapping)
        .filter(
            AccountingLedgerMapping.id == mapping_id,
            AccountingLedgerMapping.client_id == client.id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Ledger mapping not found.")
    row.is_active = False
    db.flush()
    return row


# ------------------------------------------------------------------ suggestions


def _line(ledger: str, debit: Decimal, credit: Decimal, description: str | None) -> dict:
    return {
        "ledger_name": ledger[:120],
        "description": (description or None),
        "debit": q2(abs(debit)),
        "credit": q2(abs(credit)),
    }


def _add_rounding(lines: list[dict]) -> Decimal:
    debit = sum((line["debit"] for line in lines), ZERO)
    credit = sum((line["credit"] for line in lines), ZERO)
    difference = q2(debit - credit)
    if difference == ZERO:
        return ZERO
    if difference > ZERO:
        lines.append(_line("Rounding adjustment", ZERO, difference, "Rounding difference"))
    else:
        lines.append(_line("Rounding adjustment", -difference, ZERO, "Rounding difference"))
    return difference


def _tax_lines(txn: AccountingBusinessTransaction, tax_ledger: str) -> list[dict]:
    base = (tax_ledger or "Output GST").strip()[:100]
    lines = []
    for label, amount in (
        ("CGST", txn.cgst_amount),
        ("SGST", txn.sgst_amount),
        ("IGST", txn.igst_amount),
    ):
        value = q2(amount or ZERO)
        if value > ZERO:
            lines.append(
                _line(
                    f"{base} - {label}",
                    ZERO,
                    value,
                    f"{label} on {txn.source_ref}",
                )
            )
    return lines


def build_suggestion(
    db: Session,
    client: AccountingClient,
    txn: AccountingBusinessTransaction,
    *,
    defaults: dict | None = None,
) -> dict:
    defaults = defaults or client_ledger_defaults(db, client.id)
    mapping = _mapping_query(db, client.id, txn.transaction_type, txn.category or "")
    fields = _mapping_fields(mapping)
    voucher_type = INBOX_TO_VOUCHER.get(txn.transaction_type)
    if voucher_type is None:
        raise HTTPException(
            status_code=422,
            detail=f"Transaction type {txn.transaction_type!r} cannot be drafted.",
        )
    total = q2(txn.total_amount or ZERO)
    if total == ZERO:
        raise HTTPException(
            status_code=422,
            detail=f"{txn.source_ref} has a zero amount and cannot be drafted.",
        )

    party = _party_ledger(txn)
    warnings: list[str] = []
    lines: list[dict] = []
    used: dict = {}
    if txn.transaction_type == "sale":
        used = {
            "debit_ledger": fields["debit_ledger"] or party,
            "credit_ledger": fields["credit_ledger"] or defaults["sales"],
            "tax_ledger": fields["tax_ledger"] or "Output GST",
            "bank_ledger": fields["bank_ledger"],
        }
        lines.append(
            _line(
                used["debit_ledger"],
                total,
                ZERO,
                txn.narration or f"Sales invoice {txn.source_ref}",
            )
        )
        taxable = q2(txn.taxable_value or ZERO)
        if taxable > ZERO:
            lines.append(
                _line(used["credit_ledger"], ZERO, taxable, f"Sales per {txn.source_ref}")
            )
        tax_lines = _tax_lines(txn, used["tax_ledger"])
        if taxable == ZERO and not tax_lines:
            lines.append(
                _line(used["credit_ledger"], ZERO, total, f"Sales per {txn.source_ref}")
            )
        lines.extend(tax_lines)
        if tax_lines:
            warnings.append(
                "GST ledgers are suggested from the source invoice. Confirm the output "
                "ledger names and tax amounts before approval."
            )
    elif txn.transaction_type == "receipt":
        bank = _bank_ledger(txn, fields["bank_ledger"] or defaults["bank"], defaults)
        used = {
            "debit_ledger": fields["debit_ledger"] or bank,
            "credit_ledger": fields["credit_ledger"] or party,
            "tax_ledger": fields["tax_ledger"],
            "bank_ledger": bank,
        }
        amount = abs(total)
        lines.append(
            _line(
                used["debit_ledger"],
                amount,
                ZERO,
                txn.narration or f"Receipt {txn.source_ref}",
            )
        )
        lines.append(
            _line(used["credit_ledger"], ZERO, amount, f"Receipt from {party}")
        )
        if used["debit_ledger"] == "Bank":
            warnings.append(
                "No bank ledger was found in this client's vouchers. Choose the bank or "
                "cash ledger used for this receipt."
            )
    elif txn.transaction_type == "refund":
        bank = _bank_ledger(txn, fields["bank_ledger"] or defaults["bank"], defaults)
        used = {
            "debit_ledger": fields["debit_ledger"] or party,
            "credit_ledger": fields["credit_ledger"] or bank,
            "tax_ledger": fields["tax_ledger"],
            "bank_ledger": bank,
        }
        amount = abs(total)
        lines.append(
            _line(used["debit_ledger"], amount, ZERO, f"Refund to {party}")
        )
        lines.append(
            _line(
                used["credit_ledger"],
                ZERO,
                amount,
                txn.narration or f"Refund {txn.source_ref}",
            )
        )
        if used["credit_ledger"] == "Bank":
            warnings.append(
                "No bank ledger was found in this client's vouchers. Choose the bank or "
                "cash ledger used for this refund."
            )
    else:
        expense_ledger = fields["debit_ledger"] or _expense_ledger(
            txn.category, defaults
        )
        payee = fields["credit_ledger"] or party
        used = {
            "debit_ledger": expense_ledger,
            "credit_ledger": payee,
            "tax_ledger": fields["tax_ledger"],
            "bank_ledger": fields["bank_ledger"],
        }
        amount = abs(total)
        lines.append(
            _line(
                used["debit_ledger"],
                amount,
                ZERO,
                txn.narration or f"{txn.category or 'Expense'} - {txn.source_ref}",
            )
        )
        lines.append(
            _line(used["credit_ledger"], ZERO, amount, f"Payable to {payee}")
        )
        if not fields["credit_ledger"]:
            warnings.append(
                "The credit ledger is the vendor's payable account. Confirm whether this "
                "expense was paid or remains payable."
            )

    rounding = _add_rounding(lines)
    if rounding != ZERO:
        warnings.append(
            "A rounding line was added so the draft balances against the source total."
        )
        if abs(rounding) > Decimal("1.00"):
            warnings.append(
                "The source total differs from its taxable and tax components by more "
                "than one rupee. Review the amounts before approval."
            )
    debit_total = q2(sum((line["debit"] for line in lines), ZERO))
    credit_total = q2(sum((line["credit"] for line in lines), ZERO))
    return {
        "transaction_id": txn.id,
        "source_type": txn.source_type,
        "source_ref": txn.source_ref,
        "transaction_type": txn.transaction_type,
        "voucher_type": voucher_type,
        "voucher_date": txn.transaction_date.isoformat(),
        "financial_year": txn.financial_year,
        "party_name": party,
        "party_gstin": txn.party_gstin,
        "narration": txn.narration,
        "lines": [
            {"line_no": index, **line} for index, line in enumerate(lines, start=1)
        ],
        "total_debit": debit_total,
        "total_credit": credit_total,
        "difference": q2(debit_total - credit_total),
        "mapping": {
            "mapping_id": mapping.id if mapping else None,
            "source": "override" if mapping else "client_defaults",
            "transaction_type": txn.transaction_type,
            "category": txn.category,
            **used,
        },
        "warnings": warnings,
    }


# ------------------------------------------------------------------ drafts


class _NumberAllocator:
    def __init__(self, db: Session, client_id: int) -> None:
        self.db = db
        self.client_id = client_id
        self.used: dict[str, set[str]] = {}

    def next(self, voucher_type: str, on: date) -> str:
        prefix = NUMBER_PREFIX.get(voucher_type, "DR-J")
        stem = f"{prefix}-{on:%Y%m}"
        if stem not in self.used:
            rows = (
                self.db.query(AccountingEntryDraft.number)
                .filter(
                    AccountingEntryDraft.client_id == self.client_id,
                    AccountingEntryDraft.number.like(f"{stem}-%"),
                )
                .all()
            )
            self.used[stem] = {row[0] for row in rows}
        seq = 1
        while f"{stem}-{seq:03d}" in self.used[stem]:
            seq += 1
        number = f"{stem}-{seq:03d}"
        self.used[stem].add(number)
        return number


def _create_draft(
    db: Session,
    client: AccountingClient,
    txn: AccountingBusinessTransaction,
    suggestion: dict,
    user: User,
    numbers: _NumberAllocator,
) -> AccountingEntryDraft:
    draft = AccountingEntryDraft(
        client_id=client.id,
        transaction_id=txn.id,
        voucher_type=suggestion["voucher_type"],
        number=numbers.next(suggestion["voucher_type"], txn.transaction_date),
        voucher_date=txn.transaction_date,
        financial_year=financial_year_for(txn.transaction_date),
        party_name=suggestion["party_name"],
        party_gstin=suggestion["party_gstin"],
        narration=suggestion["narration"],
        total_debit=suggestion["total_debit"],
        total_credit=suggestion["total_credit"],
        difference=suggestion["difference"],
        status="draft",
        source_hash=txn.source_hash,
        prepared_by_user_id=user.id,
    )
    db.add(draft)
    db.flush()
    for line in suggestion["lines"]:
        db.add(
            AccountingEntryDraftLine(
                draft_id=draft.id,
                line_no=line["line_no"],
                ledger_name=line["ledger_name"],
                description=line["description"],
                debit=line["debit"],
                credit=line["credit"],
            )
        )
    txn.status = "drafted"
    db.flush()
    return draft


def generate_drafts(
    db: Session,
    client: AccountingClient,
    user: User,
    *,
    transaction_ids: Iterable[int] | None = None,
    limit: int = 50,
) -> dict:
    _requires_business(client)
    query = db.query(AccountingBusinessTransaction).filter(
        AccountingBusinessTransaction.client_id == client.id,
    )
    ids = [int(value) for value in (transaction_ids or []) if value]
    if ids:
        query = query.filter(AccountingBusinessTransaction.id.in_(ids))
    else:
        query = query.filter(AccountingBusinessTransaction.status == "pending")
    candidates = (
        query.order_by(
            AccountingBusinessTransaction.transaction_date.asc(),
            AccountingBusinessTransaction.id.asc(),
        )
        .limit(limit)
        .all()
    )
    defaults = client_ledger_defaults(db, client.id)
    numbers = _NumberAllocator(db, client.id)
    generated: list[AccountingEntryDraft] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for txn in candidates:
        existing = (
            db.query(AccountingEntryDraft)
            .filter(AccountingEntryDraft.transaction_id == txn.id)
            .first()
        )
        if existing is not None:
            reason = f"A draft already exists ({existing.number})."
            if txn.status != "pending":
                reason = (
                    f"A draft already exists ({existing.number}) and the source is "
                    f"marked {txn.status}; review the draft and source before "
                    "regenerating."
                )
            skipped.append(
                {
                    "transaction_id": txn.id,
                    "source_ref": txn.source_ref,
                    "reason": reason,
                }
            )
            continue
        if txn.status != "pending":
            skipped.append(
                {
                    "transaction_id": txn.id,
                    "source_ref": txn.source_ref,
                    "reason": (
                        f"This transaction is marked {txn.status}; only pending rows "
                        "can be drafted."
                    ),
                }
            )
            continue
        try:
            with db.begin_nested():
                suggestion = build_suggestion(db, client, txn, defaults=defaults)
                draft = _create_draft(db, client, txn, suggestion, user, numbers)
        except HTTPException as exc:
            errors.append(
                {
                    "transaction_id": txn.id,
                    "source_ref": txn.source_ref,
                    "reason": exc.detail,
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the batch
            errors.append(
                {
                    "transaction_id": txn.id,
                    "source_ref": txn.source_ref,
                    "reason": f"{type(exc).__name__}: could not generate a draft.",
                }
            )
            continue
        generated.append(draft)
    db.flush()
    return {
        "generated": len(generated),
        "skipped": len(skipped),
        "errors": len(errors),
        "drafts": [draft_to_dict(row) for row in generated],
        "skipped_details": skipped,
        "error_details": errors,
        "eligible_remaining": db.query(AccountingBusinessTransaction)
        .filter(
            AccountingBusinessTransaction.client_id == client.id,
            AccountingBusinessTransaction.status == "pending",
        )
        .count(),
    }


def draft_to_dict(draft: AccountingEntryDraft, txn: AccountingBusinessTransaction | None = None) -> dict:
    txn = txn or draft.transaction
    return {
        "id": draft.id,
        "client_id": draft.client_id,
        "transaction_id": draft.transaction_id,
        "source": (
            {
                "source_type": txn.source_type,
                "source_ref": txn.source_ref,
                "transaction_type": txn.transaction_type,
                "transaction_date": txn.transaction_date.isoformat(),
                "party_name": txn.party_name,
                "total_amount": txn.total_amount,
                "status": txn.status,
            }
            if txn is not None
            else None
        ),
        "voucher_type": draft.voucher_type,
        "number": draft.number,
        "voucher_date": draft.voucher_date.isoformat(),
        "financial_year": draft.financial_year,
        "party_name": draft.party_name,
        "party_gstin": draft.party_gstin,
        "narration": draft.narration,
        "total_debit": draft.total_debit,
        "total_credit": draft.total_credit,
        "difference": draft.difference,
        "status": draft.status,
        "source_hash": draft.source_hash,
        "prepared_by_user_id": draft.prepared_by_user_id,
        "submitted_at": _iso(draft.submitted_at),
        "reviewed_at": _iso(draft.reviewed_at),
        "reviewed_by_user_id": draft.reviewed_by_user_id,
        "review_note": draft.review_note,
        "created_at": _iso(draft.created_at),
        "updated_at": _iso(draft.updated_at),
        "lines": [
            {
                "line_no": line.line_no,
                "ledger_name": line.ledger_name,
                "description": line.description,
                "debit": line.debit,
                "credit": line.credit,
            }
            for line in sorted(draft.lines, key=lambda row: row.line_no)
        ],
    }


def get_draft(db: Session, client_id: int, draft_id: int) -> AccountingEntryDraft:
    draft = (
        db.query(AccountingEntryDraft)
        .options(
            selectinload(AccountingEntryDraft.lines),
            selectinload(AccountingEntryDraft.transaction),
        )
        .filter(
            AccountingEntryDraft.id == draft_id,
            AccountingEntryDraft.client_id == client_id,
        )
        .one_or_none()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Entry draft not found.")
    return draft


def list_drafts(
    db: Session,
    client_id: int,
    *,
    status: str | None = None,
    voucher_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    query = db.query(AccountingEntryDraft).filter(
        AccountingEntryDraft.client_id == client_id
    )
    if status:
        query = query.filter(AccountingEntryDraft.status == status)
    if voucher_type:
        query = query.filter(AccountingEntryDraft.voucher_type == voucher_type)
    total = query.count()
    rows = (
        query.options(
            selectinload(AccountingEntryDraft.lines),
            selectinload(AccountingEntryDraft.transaction),
        )
        .order_by(
            AccountingEntryDraft.voucher_date.desc(),
            AccountingEntryDraft.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    voucher_ids = {}
    if rows:
        voucher_ids = dict(
            db.query(AccountingVoucher.entry_draft_id, AccountingVoucher.id)
            .filter(AccountingVoucher.entry_draft_id.in_([row.id for row in rows]))
            .all()
        )
    items = []
    for row in rows:
        payload = draft_to_dict(row)
        payload["voucher_id"] = voucher_ids.get(row.id)
        items.append(payload)
    return {"items": items, "total": total}


def update_draft(
    db: Session, draft: AccountingEntryDraft, payload: EntryDraftUpdateIn, user: User
) -> AccountingEntryDraft:
    if draft.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Only drafts that have not been submitted can be edited.",
        )
    previous = {
        "status": draft.status,
        "total_debit": str(draft.total_debit),
        "total_credit": str(draft.total_credit),
        "lines": len(draft.lines),
    }
    if draft.status == "rejected":
        draft.status = "draft"
        draft.reviewed_at = None
        draft.reviewed_by_user_id = None
        draft.review_note = None
    if payload.voucher_type is not None:
        if payload.voucher_type not in DRAFT_TYPES:
            raise HTTPException(status_code=422, detail="Unsupported voucher type.")
        draft.voucher_type = payload.voucher_type
    if payload.voucher_date is not None:
        draft.voucher_date = payload.voucher_date
        draft.financial_year = financial_year_for(payload.voucher_date)
    if payload.party_name is not None:
        draft.party_name = payload.party_name.strip()[:180]
    if payload.party_gstin is not None:
        draft.party_gstin = (payload.party_gstin or "").strip().upper() or None
    if payload.narration is not None:
        draft.narration = payload.narration.strip() or None

    if payload.lines is not None:
        lines = payload.lines
        if len(lines) < 2:
            raise HTTPException(
                status_code=422, detail="A double-entry draft needs at least two lines."
            )
        debit_total = q2(sum((line.debit for line in lines), ZERO))
        credit_total = q2(sum((line.credit for line in lines), ZERO))
        if debit_total != credit_total:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Debits ({debit_total}) and credits ({credit_total}) must match. "
                    f"Difference: {q2(debit_total - credit_total)}."
                ),
            )
        for line in list(draft.lines):
            db.expunge(line)
        db.query(AccountingEntryDraftLine).filter(
            AccountingEntryDraftLine.draft_id == draft.id
        ).delete(synchronize_session=False)
        db.flush()
        for index, line in enumerate(lines, start=1):
            db.add(
                AccountingEntryDraftLine(
                    draft_id=draft.id,
                    line_no=index,
                    ledger_name=line.ledger_name.strip()[:120],
                    description=(line.description or "").strip() or None,
                    debit=q2(line.debit),
                    credit=q2(line.credit),
                )
            )
        draft.total_debit = debit_total
        draft.total_credit = credit_total
        draft.difference = q2(debit_total - credit_total)
    db.flush()
    draft.updated_at = utcnow()
    db.flush()
    # The bulk line delete bypasses the identity map, so the loaded collection is stale.
    db.expire(draft, ["lines"])
    updated = get_draft(db, draft.client_id, draft.id)
    audit_detail = {
        "transaction_id": draft.transaction_id,
        "number": draft.number,
        "previous": previous,
        "total_debit": str(draft.total_debit),
        "total_credit": str(draft.total_credit),
        "lines": len(updated.lines),
    }
    return updated, audit_detail


def source_transaction_for(
    db: Session, client_id: int, transaction_id: int
) -> AccountingBusinessTransaction:
    txn = (
        db.query(AccountingBusinessTransaction)
        .filter(
            AccountingBusinessTransaction.id == transaction_id,
            AccountingBusinessTransaction.client_id == client_id,
        )
        .one_or_none()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Inbox transaction not found.")
    return txn
