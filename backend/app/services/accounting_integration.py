"""Business Manager to accounting integration.

Phase 1 covers the explicit engagement link and the read-only status surface.
Phase 2 copies the business's own sales, receipts, refunds and expenses into a
review inbox keyed by source record, so repeated syncs cannot duplicate rows and
source edits are detected without overwriting accounting work. Nothing here
posts a voucher or changes a business ledger.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..models import (
    AccountingBusinessTransaction,
    AccountingBusinessTransactionLine,
    AccountingClient,
    AccountingEntryDraft,
    AccountingIntegrationRun,
    BusinessProfile,
    Expense,
    Invoice,
    Payment,
    User,
    utcnow,
)
from .accounting_math import financial_year_for, q2

INTEGRATION_SOURCES = ("invoice", "payment", "expense", "refund")
DEFAULT_INTEGRATION_SETTINGS = {
    "sync_sources": list(INTEGRATION_SOURCES),
    "include_voided": False,
    "draft_mode": "manual",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def business_option(db: Session, profile: BusinessProfile) -> dict:
    linked = (
        db.query(AccountingClient)
        .filter(AccountingClient.business_profile_id == profile.id)
        .order_by(AccountingClient.id)
        .first()
    )
    return {
        "business_profile_id": profile.id,
        "business_name": profile.business_name,
        "legal_name": profile.legal_name,
        "gstin": profile.gstin,
        "city": profile.city,
        "state": profile.state,
        "owner_user_id": profile.user_id,
        "linked_client_id": linked.id if linked else None,
        "linked_client_name": linked.business_name if linked else None,
    }


def list_business_options(db: Session) -> list[dict]:
    profiles = (
        db.query(BusinessProfile).order_by(BusinessProfile.business_name).limit(300).all()
    )
    return [business_option(db, profile) for profile in profiles]


def link_business(
    db: Session, client: AccountingClient, business_profile_id: int
) -> AccountingClient:
    profile = db.get(BusinessProfile, business_profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Business profile not found.")

    other = (
        db.query(AccountingClient)
        .filter(
            AccountingClient.business_profile_id == profile.id,
            AccountingClient.id != client.id,
        )
        .first()
    )
    if other is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This business is already linked to {other.business_name}. "
                "Unlink it there before linking it here."
            ),
        )
    if client.business_profile_id not in (None, profile.id):
        raise HTTPException(
            status_code=409,
            detail="This engagement is already linked to another business. Unlink it first.",
        )

    client.business_profile_id = profile.id
    client.integration_status = "linked"
    client.integration_enabled_at = client.integration_enabled_at or utcnow()
    if not client.integration_settings:
        client.integration_settings = dict(DEFAULT_INTEGRATION_SETTINGS)
    db.flush()
    return client


def unlink_business(db: Session, client: AccountingClient) -> int | None:
    """Remove the link without touching synced transactions, drafts or vouchers."""
    previous = client.business_profile_id
    if previous is None and client.integration_status == "not_linked":
        raise HTTPException(status_code=409, detail="No business is linked to this engagement.")
    client.business_profile_id = None
    client.integration_status = "not_linked"
    client.integration_enabled_at = None
    client.integration_last_synced_at = None
    db.flush()
    return previous


def _status_counts(db: Session, client_id: int) -> dict[str, int]:
    rows = (
        db.query(
            AccountingBusinessTransaction.status,
            func.count(AccountingBusinessTransaction.id),
        )
        .filter(AccountingBusinessTransaction.client_id == client_id)
        .group_by(AccountingBusinessTransaction.status)
        .all()
    )
    counts = {"pending": 0, "drafted": 0, "needs_attention": 0, "ignored": 0, "posted": 0}
    for status, total in rows:
        counts[status] = total
    counts["total"] = sum(counts.values())
    return counts


def _draft_counts(db: Session, client_id: int) -> dict[str, int]:
    rows = (
        db.query(AccountingEntryDraft.status, func.count(AccountingEntryDraft.id))
        .filter(AccountingEntryDraft.client_id == client_id)
        .group_by(AccountingEntryDraft.status)
        .all()
    )
    counts = {
        "draft": 0,
        "pending_review": 0,
        "approved": 0,
        "rejected": 0,
        "posted": 0,
    }
    for status, total in rows:
        counts[status] = total
    counts["total"] = sum(counts.values())
    return counts


def last_run(db: Session, client_id: int) -> dict | None:
    run = (
        db.query(AccountingIntegrationRun)
        .filter(AccountingIntegrationRun.client_id == client_id)
        .order_by(AccountingIntegrationRun.created_at.desc())
        .first()
    )
    if run is None:
        return None
    return {
        "id": run.id,
        "run_type": run.run_type,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "discovered": run.discovered,
        "created": run.created_count,
        "updated": run.updated_count,
        "skipped": run.skipped_count,
        "errors": run.error_count,
    }


def integration_summary(
    db: Session, client: AccountingClient, *, owner_view: bool = False
) -> dict:
    profile = client.business_profile
    payload = {
        "client_id": client.id,
        "linked": client.business_profile_id is not None,
        "status": client.integration_status,
        "enabled_at": _iso(client.integration_enabled_at),
        "last_synced_at": _iso(client.integration_last_synced_at),
        "business": (
            {
                "id": profile.id,
                "business_name": profile.business_name,
                "gstin": profile.gstin,
                "city": profile.city,
                "state": profile.state,
            }
            if profile is not None
            else None
        ),
        "counts": _status_counts(db, client.id),
        "drafts": _draft_counts(db, client.id),
        "last_run": last_run(db, client.id),
    }
    if not owner_view:
        payload["settings"] = client.integration_settings or {}
    return payload


def transaction_to_dict(row: AccountingBusinessTransaction) -> dict:
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_ref": row.source_ref,
        "transaction_type": row.transaction_type,
        "transaction_date": row.transaction_date.isoformat(),
        "financial_year": row.financial_year,
        "party_name": row.party_name,
        "party_gstin": row.party_gstin,
        "narration": row.narration,
        "category": row.category,
        "currency": row.currency,
        "taxable_value": row.taxable_value,
        "gst_rate": row.gst_rate,
        "cgst_amount": row.cgst_amount,
        "sgst_amount": row.sgst_amount,
        "igst_amount": row.igst_amount,
        "total_amount": row.total_amount,
        "source_status": row.source_status,
        "status": row.status,
        "issue_reason": row.issue_reason,
        "synced_at": _iso(row.synced_at),
        "lines": [
            {
                "line_no": line.line_no,
                "description": line.description,
                "hsn_sac": line.hsn_sac,
                "quantity": line.quantity,
                "unit": line.unit,
                "taxable_value": line.taxable_value,
                "gst_rate": line.gst_rate,
                "total_amount": line.total_amount,
                "suggested_ledger": line.suggested_ledger,
            }
            for line in row.lines
        ],
    }


# ---------------------------------------------------------------- inbox sync


ZERO = Decimal("0.00")
PROTECTED_DRAFT_STATUSES = ("draft", "pending_review", "approved", "posted")


def _decimal(value) -> Decimal:
    if value in (None, ""):
        return ZERO
    return q2(Decimal(str(value)))


def _canonical(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _source_hash(payload: dict) -> str:
    encoded = json.dumps(
        _canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _invoice_lines(invoice: Invoice) -> list[dict]:
    lines = []
    for index, item in enumerate(invoice.items, start=1):
        taxable = _decimal(item.taxable_value or item.line_total)
        gst = _decimal(item.gst_amount)
        lines.append(
            {
                "line_no": index,
                "description": item.name or item.description or invoice.number,
                "hsn_sac": item.hsn_sac,
                "item_type": item.item_type,
                "quantity": _decimal(item.quantity),
                "unit": item.unit,
                "rate": _decimal(item.unit_price),
                "taxable_value": taxable,
                "gst_rate": _decimal(item.gst_rate),
                "cgst_amount": _decimal(item.cgst_amount),
                "sgst_amount": _decimal(item.sgst_amount),
                "igst_amount": _decimal(item.igst_amount),
                "total_amount": _decimal(item.final_amount or (taxable + gst)),
                "suggested_ledger": None,
            }
        )
    return lines


def _invoice_record(invoice: Invoice, *, include_voided: bool) -> dict:
    customer = invoice.customer
    party_name = invoice.customer_name or (customer.name if customer else None) or "Unnamed customer"
    party_gstin = invoice.customer_gstin or (customer.gstin if customer else None)
    lines = _invoice_lines(invoice)
    taxable = _decimal(invoice.taxable_amount)
    if taxable == ZERO:
        taxable = q2(sum((line["taxable_value"] for line in lines), ZERO)) or _decimal(
            invoice.subtotal_amount
        )
    total = _decimal(invoice.total_amount)
    status = invoice.status or "issued"
    skip_reason: str | None = None
    issue_reason: str | None = None
    bookable = True
    if status == "draft":
        bookable = False
        skip_reason = "Draft invoices are excluded until they are issued."
    elif status == "void":
        bookable = False
        issue_reason = (
            "This invoice was voided. Do not post it; review the source before booking."
        )
        if not include_voided:
            skip_reason = "Voided invoices are excluded by the integration settings."
    elif total <= ZERO:
        bookable = False
        issue_reason = "The invoice total is zero. Review the source before booking."
    bookable_payload = {
        "kind": "invoice",
        "number": invoice.number,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "currency": invoice.currency,
        "party_name": party_name,
        "party_gstin": party_gstin,
        "notes": invoice.notes,
        "taxable_value": taxable,
        "cgst_amount": _decimal(invoice.cgst_amount),
        "sgst_amount": _decimal(invoice.sgst_amount),
        "igst_amount": _decimal(invoice.igst_amount),
        "total_amount": total,
        "lines": [
            {key: value for key, value in line.items() if key != "suggested_ledger"}
            for line in lines
        ],
    }
    snapshot = {
        **bookable_payload,
        "status": status,
        "supply_type": invoice.supply_type,
        "supply_verified": invoice.supply_verified,
        "place_of_supply_state": invoice.place_of_supply_state,
        "payment_terms": invoice.terms,
    }
    return {
        "source_type": "invoice",
        "source_id": invoice.id,
        "source_ref": invoice.number,
        "transaction_date": invoice.issue_date,
        "transaction_type": "sale",
        "category": "Sales",
        "party_name": party_name,
        "party_gstin": party_gstin,
        "narration": invoice.notes or f"Sales invoice {invoice.number}",
        "currency": invoice.currency or "INR",
        "taxable_value": taxable,
        "gst_rate": ZERO,
        "cgst_amount": _decimal(invoice.cgst_amount),
        "sgst_amount": _decimal(invoice.sgst_amount),
        "igst_amount": _decimal(invoice.igst_amount),
        "total_amount": total,
        "source_status": status,
        "source_updated_at": invoice.updated_at,
        "bookable": bookable,
        "skip_reason": skip_reason,
        "issue_reason": issue_reason,
        "hash": _source_hash(bookable_payload),
        "snapshot": snapshot,
        "lines": lines,
    }


def _payment_record(payment: Payment) -> dict:
    invoice = payment.invoice
    is_refund = payment.refund_of_payment_id is not None
    party_name = (
        payment.sender_name
        or (invoice.customer_name if invoice else None)
        or (invoice.customer.name if invoice is not None and invoice.customer else None)
        or ("Customer refund" if is_refund else "Customer")
    )
    party_gstin = invoice.customer_gstin if invoice is not None else None
    status = payment.status or "pending"
    bookable = status == "confirmed" and _decimal(payment.amount) != ZERO
    issue_reason: str | None = None
    skip_reason: str | None = None
    if status != "confirmed":
        skip_reason = "Only confirmed payments are synced."
        issue_reason = (
            f"This payment is not confirmed (status: {status}). Review before booking."
        )
    elif _decimal(payment.amount) == ZERO:
        issue_reason = "The payment amount is zero. Review the source before booking."
    received = payment.received_at or payment.created_at
    reference = (payment.provider_ref or f"PMT-{payment.id}")[:60]
    bookable_payload = {
        "kind": "refund" if is_refund else "payment",
        "invoice_id": payment.invoice_id,
        "refund_of_payment_id": payment.refund_of_payment_id,
        "amount": _decimal(payment.amount),
        "currency": payment.currency,
        "method": payment.method,
        "provider": payment.provider,
        "provider_ref": payment.provider_ref,
        "sender_name": payment.sender_name,
        "note": payment.note,
        "received_at": received,
    }
    snapshot = {
        **bookable_payload,
        "status": status,
        "reconciliation_status": payment.reconciliation_status,
    }
    return {
        "source_type": "payment",
        "source_id": payment.id,
        "source_ref": reference,
        "transaction_date": received.date() if received else date.today(),
        "transaction_type": "refund" if is_refund else "receipt",
        "category": "Refunds" if is_refund else "Receipts",
        "party_name": party_name,
        "party_gstin": party_gstin,
        "narration": payment.note
        or (
            f"Refund against invoice {invoice.number}"
            if is_refund and invoice is not None
            else (
                f"Payment received for invoice {invoice.number}"
                if invoice is not None
                else "Payment received"
            )
        ),
        "currency": payment.currency or "INR",
        "taxable_value": ZERO,
        "gst_rate": ZERO,
        "cgst_amount": ZERO,
        "sgst_amount": ZERO,
        "igst_amount": ZERO,
        "total_amount": _decimal(payment.amount),
        "source_status": status,
        "source_updated_at": received,
        "bookable": bookable,
        "skip_reason": skip_reason,
        "issue_reason": issue_reason,
        "hash": _source_hash(bookable_payload),
        "snapshot": snapshot,
        "lines": [],
    }


def _expense_record(expense: Expense) -> dict:
    amount = _decimal(expense.amount)
    bookable = amount > ZERO
    issue_reason = None if bookable else "The expense amount is zero. Review the source."
    bookable_payload = {
        "kind": "expense",
        "category": expense.category,
        "vendor": expense.vendor,
        "amount": amount,
        "incurred_on": expense.incurred_on,
        "note": expense.note,
    }
    snapshot = {**bookable_payload}
    return {
        "source_type": "expense",
        "source_id": expense.id,
        "source_ref": f"EXP-{expense.id}",
        "transaction_date": expense.incurred_on,
        "transaction_type": "expense",
        "category": expense.category,
        "party_name": expense.vendor or "Unnamed vendor",
        "party_gstin": None,
        "narration": expense.note or f"{expense.category} expense",
        "currency": "INR",
        "taxable_value": amount,
        "gst_rate": ZERO,
        "cgst_amount": ZERO,
        "sgst_amount": ZERO,
        "igst_amount": ZERO,
        "total_amount": amount,
        "source_status": "active",
        "source_updated_at": expense.created_at,
        "bookable": bookable,
        "skip_reason": None,
        "issue_reason": issue_reason,
        "hash": _source_hash(bookable_payload),
        "snapshot": snapshot,
        "lines": [],
    }


def _source_records(db: Session, owner_id: int, *, include_voided: bool):
    invoices = (
        db.query(Invoice)
        .filter(Invoice.user_id == owner_id)
        .order_by(Invoice.issue_date, Invoice.id)
        .all()
    )
    for invoice in invoices:
        yield _invoice_record(invoice, include_voided=include_voided)
    payments = (
        db.query(Payment)
        .filter(Payment.user_id == owner_id)
        .order_by(Payment.received_at, Payment.id)
        .all()
    )
    for payment in payments:
        yield _payment_record(payment)
    expenses = (
        db.query(Expense)
        .filter(Expense.user_id == owner_id)
        .order_by(Expense.incurred_on, Expense.id)
        .all()
    )
    for expense in expenses:
        yield _expense_record(expense)


def _replace_lines(db: Session, transaction_id: int, lines: list[dict]) -> None:
    db.query(AccountingBusinessTransactionLine).filter(
        AccountingBusinessTransactionLine.transaction_id == transaction_id
    ).delete(synchronize_session=False)
    for line in lines:
        db.add(
            AccountingBusinessTransactionLine(
                transaction_id=transaction_id,
                line_no=line["line_no"],
                description=line["description"],
                hsn_sac=line["hsn_sac"],
                item_type=line["item_type"],
                quantity=line["quantity"],
                unit=line["unit"],
                rate=line["rate"],
                taxable_value=line["taxable_value"],
                gst_rate=line["gst_rate"],
                cgst_amount=line["cgst_amount"],
                sgst_amount=line["sgst_amount"],
                igst_amount=line["igst_amount"],
                total_amount=line["total_amount"],
                suggested_ledger=line["suggested_ledger"],
            )
        )


def _copy_record(row: AccountingBusinessTransaction, record: dict) -> None:
    row.transaction_date = record["transaction_date"]
    row.financial_year = financial_year_for(record["transaction_date"])
    row.transaction_type = record["transaction_type"]
    row.category = record["category"]
    row.party_name = record["party_name"]
    row.party_gstin = record["party_gstin"]
    row.narration = record["narration"]
    row.currency = record["currency"]
    row.taxable_value = record["taxable_value"]
    row.gst_rate = record["gst_rate"]
    row.cgst_amount = record["cgst_amount"]
    row.sgst_amount = record["sgst_amount"]
    row.igst_amount = record["igst_amount"]
    row.total_amount = record["total_amount"]
    row.source_ref = record["source_ref"][:60]
    row.source_status = record["source_status"]
    row.source_hash = record["hash"]
    row.source_updated_at = record["source_updated_at"]
    row.snapshot = record["snapshot"]


def _apply_record(
    db: Session,
    client: AccountingClient,
    record: dict,
    *,
    now: datetime,
) -> tuple[str, str | None]:
    existing = (
        db.query(AccountingBusinessTransaction)
        .filter(
            AccountingBusinessTransaction.client_id == client.id,
            AccountingBusinessTransaction.source_type == record["source_type"],
            AccountingBusinessTransaction.source_id == record["source_id"],
        )
        .one_or_none()
    )
    if existing is None:
        if record["skip_reason"]:
            return "skipped", record["skip_reason"]
        row = AccountingBusinessTransaction(
            client_id=client.id,
            business_profile_id=client.business_profile_id,
            source_type=record["source_type"],
            source_id=record["source_id"],
            source_ref=record["source_ref"][:60],
            transaction_date=record["transaction_date"],
            financial_year=financial_year_for(record["transaction_date"]),
            transaction_type=record["transaction_type"],
            category=record["category"],
            party_name=record["party_name"],
            party_gstin=record["party_gstin"],
            narration=record["narration"],
            currency=record["currency"],
            taxable_value=record["taxable_value"],
            gst_rate=record["gst_rate"],
            cgst_amount=record["cgst_amount"],
            sgst_amount=record["sgst_amount"],
            igst_amount=record["igst_amount"],
            total_amount=record["total_amount"],
            source_status=record["source_status"],
            source_hash=record["hash"],
            source_updated_at=record["source_updated_at"],
            snapshot=record["snapshot"],
            status="pending" if record["bookable"] else "needs_attention",
            issue_reason=record["issue_reason"],
            synced_at=now,
        )
        db.add(row)
        db.flush()
        _replace_lines(db, row.id, record["lines"])
        return "created", None

    existing.source_status = record["source_status"]
    existing.synced_at = now
    if existing.source_hash == record["hash"]:
        if not record["bookable"] and existing.status in ("pending", "drafted", "needs_attention"):
            if existing.status != "needs_attention":
                existing.status = "needs_attention"
                existing.issue_reason = record["issue_reason"]
        return "skipped", None

    protected = existing.status in PROTECTED_DRAFT_STATUSES or (
        db.query(AccountingEntryDraft.id)
        .filter(AccountingEntryDraft.transaction_id == existing.id)
        .first()
        is not None
    )
    was_ignored = existing.status == "ignored"
    _copy_record(existing, record)
    _replace_lines(db, existing.id, record["lines"])
    if protected:
        existing.status = "needs_attention"
        existing.issue_reason = (
            "The source changed after an accounting draft was created. "
            "The draft and any posted voucher were not overwritten."
        )
    elif was_ignored:
        existing.issue_reason = (
            "The source changed after this transaction was ignored. Review before restoring it."
        )
    elif record["bookable"]:
        existing.status = "pending"
        existing.issue_reason = None
    else:
        existing.status = "needs_attention"
        existing.issue_reason = record["issue_reason"]
    return "updated", None


def sync_business_transactions(
    db: Session, client: AccountingClient, user: User
) -> AccountingIntegrationRun:
    if client.business_profile_id is None or client.integration_status != "linked":
        raise HTTPException(
            status_code=409,
            detail="Link this engagement to a business before syncing transactions.",
        )
    profile = client.business_profile
    if profile is None:
        raise HTTPException(status_code=409, detail="The linked business profile no longer exists.")

    settings = client.integration_settings or {}
    include_voided = bool(settings.get("include_voided"))
    now = utcnow()
    run = AccountingIntegrationRun(
        client_id=client.id,
        business_profile_id=profile.id,
        run_type="manual_sync",
        status="running",
        started_at=now,
        triggered_by_user_id=user.id,
        details={},
    )
    db.add(run)
    db.flush()

    discovered = created = updated = skipped = errors = 0
    sources: dict[str, int] = {}
    skipped_reasons: dict[str, int] = {}
    error_items: list[dict] = []
    for record in _source_records(db, profile.user_id, include_voided=include_voided):
        discovered += 1
        sources[record["source_type"]] = sources.get(record["source_type"], 0) + 1
        try:
            with db.begin_nested():
                outcome, reason = _apply_record(db, client, record, now=now)
        except Exception as exc:  # noqa: BLE001 - one bad source must not abort the run
            errors += 1
            if len(error_items) < 20:
                error_items.append(
                    {
                        "source_type": record["source_type"],
                        "source_id": record["source_id"],
                        "error": type(exc).__name__,
                    }
                )
            continue
        if outcome == "created":
            created += 1
        elif outcome == "updated":
            updated += 1
        else:
            skipped += 1
            if reason:
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1

    run.discovered = discovered
    run.created_count = created
    run.updated_count = updated
    run.skipped_count = skipped
    run.error_count = errors
    run.status = "completed" if errors == 0 else "partial"
    run.finished_at = utcnow()
    run.details = {
        "sources": sources,
        "skipped_reasons": skipped_reasons,
        "errors": error_items,
    }
    client.integration_last_synced_at = run.finished_at
    db.flush()
    return run


def run_to_dict(run: AccountingIntegrationRun) -> dict:
    return {
        "id": run.id,
        "run_type": run.run_type,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "discovered": run.discovered,
        "created": run.created_count,
        "updated": run.updated_count,
        "skipped": run.skipped_count,
        "errors": run.error_count,
        "details": run.details or {},
    }


def list_client_transactions(
    db: Session,
    client_id: int,
    *,
    status: str | None = None,
    source_type: str | None = None,
    transaction_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    query = db.query(AccountingBusinessTransaction).filter(
        AccountingBusinessTransaction.client_id == client_id
    )
    if status:
        query = query.filter(AccountingBusinessTransaction.status == status)
    if source_type:
        query = query.filter(AccountingBusinessTransaction.source_type == source_type)
    if transaction_type:
        query = query.filter(AccountingBusinessTransaction.transaction_type == transaction_type)
    if date_from:
        query = query.filter(AccountingBusinessTransaction.transaction_date >= date_from)
    if date_to:
        query = query.filter(AccountingBusinessTransaction.transaction_date <= date_to)
    total = query.count()
    rows = (
        query.options(selectinload(AccountingBusinessTransaction.lines))
        .order_by(
            AccountingBusinessTransaction.transaction_date.desc(),
            AccountingBusinessTransaction.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": [transaction_to_dict(row) for row in rows], "total": total}


def owner_client(db: Session, user: User) -> AccountingClient | None:
    """The engagement linked to this owner's own business, if any."""
    profile = (
        db.query(BusinessProfile).filter(BusinessProfile.user_id == user.id).one_or_none()
    )
    if profile is not None:
        client = (
            db.query(AccountingClient)
            .filter(AccountingClient.business_profile_id == profile.id)
            .order_by(AccountingClient.id)
            .first()
        )
        if client is not None:
            return client
    return (
        db.query(AccountingClient)
        .filter(AccountingClient.customer_user_id == user.id)
        .order_by(AccountingClient.id)
        .first()
    )
