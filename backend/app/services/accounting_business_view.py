"""Read-only Business Manager records for an accountant's client workspace.

The accountant already receives source transactions through the integration
inbox. This module exposes the same business ledger directly, so the practice
can compare the owner's dashboard figures with the books and see which records
have been synced, drafted, reviewed or posted to Tally. Nothing here writes to
the business records or to the accounting books.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..models import (
    AccountingBusinessTransaction,
    AccountingClient,
    AccountingEntryDraft,
    AccountingTallyExport,
    AccountingVoucher,
    BusinessProfile,
    Expense,
    InventoryItem,
    Invoice,
    Payment,
    Product,
)
from .accounting_math import financial_year_for, q2
from .finance import (
    cash_balance,
    invoice_aging_summary,
    outstanding_invoices,
    period_bounds,
    period_metrics,
)

ZERO = Decimal("0.00")
TRANSACTION_TYPES = ("sale", "receipt", "refund", "expense")


def _business_payload(profile: BusinessProfile) -> dict:
    return {
        "id": profile.id,
        "business_name": profile.business_name,
        "legal_name": profile.legal_name,
        "gstin": profile.gstin,
        "city": profile.city,
        "state": profile.state,
        "currency": profile.currency,
    }


def _inventory_summary(db: Session, owner_id: int) -> dict:
    products = (
        db.query(Product)
        .options(selectinload(Product.inventory))
        .filter(Product.user_id == owner_id)
        .all()
    )
    total_value = ZERO
    low_stock = 0
    for product in products:
        quantity = product.inventory.quantity_on_hand if product.inventory else 0
        total_value += Decimal(quantity) * Decimal(product.unit_cost or ZERO)
        if quantity <= product.reorder_level:
            low_stock += 1
    return {
        "item_count": len(products),
        "total_value": q2(total_value),
        "low_stock_count": low_stock,
    }


def _source_counts(db: Session, owner_id: int) -> dict:
    invoice_count = (
        db.query(func.count(Invoice.id)).filter(Invoice.user_id == owner_id).scalar() or 0
    )
    payment_count = (
        db.query(func.count(Payment.id)).filter(Payment.user_id == owner_id).scalar() or 0
    )
    refund_count = (
        db.query(func.count(Payment.id))
        .filter(Payment.user_id == owner_id, Payment.refund_of_payment_id.isnot(None))
        .scalar()
        or 0
    )
    expense_count = (
        db.query(func.count(Expense.id)).filter(Expense.user_id == owner_id).scalar() or 0
    )
    return {
        "invoices": invoice_count,
        "payments": payment_count,
        "refunds": refund_count,
        "expenses": expense_count,
        "total": invoice_count + payment_count + expense_count,
    }


def _inbox_counts(db: Session, client_id: int) -> dict:
    rows = (
        db.query(AccountingBusinessTransaction.status, func.count(AccountingBusinessTransaction.id))
        .filter(AccountingBusinessTransaction.client_id == client_id)
        .group_by(AccountingBusinessTransaction.status)
        .all()
    )
    counts = {"pending": 0, "drafted": 0, "needs_attention": 0, "ignored": 0, "posted": 0}
    for status, total in rows:
        counts[status] = total
    counts["total"] = sum(counts.values())
    return counts


def _draft_counts(db: Session, client_id: int) -> dict:
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


def _tally_summary(db: Session, client_id: int) -> dict:
    voucher_count = (
        db.query(func.count(AccountingVoucher.id))
        .filter(AccountingVoucher.client_id == client_id)
        .scalar()
        or 0
    )
    integration_vouchers = (
        db.query(func.count(AccountingVoucher.id))
        .filter(
            AccountingVoucher.client_id == client_id,
            AccountingVoucher.source == "integration",
        )
        .scalar()
        or 0
    )
    export_count = (
        db.query(func.count(AccountingTallyExport.id))
        .filter(AccountingTallyExport.client_id == client_id)
        .scalar()
        or 0
    )
    latest_export = (
        db.query(AccountingTallyExport)
        .filter(AccountingTallyExport.client_id == client_id)
        .order_by(AccountingTallyExport.created_at.desc(), AccountingTallyExport.id.desc())
        .first()
    )
    return {
        "voucher_count": voucher_count,
        "integration_vouchers": integration_vouchers,
        "export_count": export_count,
        "last_export_at": latest_export.created_at.isoformat() if latest_export else None,
        "last_export_status": latest_export.status if latest_export else None,
        "note": (
            "Tally exports read posted accounting vouchers only. Integration entries appear "
            "after a senior accountant approves and posts the draft; unsynced or draft "
            "business records never reach Tally."
        ),
    }


def business_summary(db: Session, client: AccountingClient, *, days: int = 30) -> dict:
    profile = client.business_profile
    if client.business_profile_id is None or profile is None:
        return {
            "linked": False,
            "client_id": client.id,
            "business": None,
            "note": (
                "No Business Manager business is linked to this engagement. A senior "
                "accountant must link the business before its records can be reviewed."
            ),
        }

    owner_id = profile.user_id
    today = date.today()
    start, end, _, _ = period_bounds(days, today)
    metrics = period_metrics(db, owner_id, start, end)
    aging = invoice_aging_summary(db, owner_id, today)
    overdue_rows = [
        row for row in outstanding_invoices(db, owner_id, today) if row["overdue_days"] > 0
    ]
    cash = cash_balance(db, profile, today)

    return {
        "linked": True,
        "client_id": client.id,
        "business": _business_payload(profile),
        "as_of": today.isoformat(),
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "currency": profile.currency,
        "metrics": {
            "revenue": metrics["revenue"],
            "cash_received": metrics["cash_received"],
            "expenses": metrics["expenses"],
            "gross_profit": metrics["gross_profit"],
            "net_profit": metrics["net_profit"],
            "gross_margin_pct": metrics["gross_margin_pct"],
            "net_margin_pct": metrics["net_margin_pct"],
            "invoice_count": metrics["invoice_count"],
        },
        "receivables": {
            "total_outstanding": aging["total_outstanding"],
            "overdue_total": aging["overdue_total"],
            "current_total": aging["current_total"],
            "overdue_count": len(overdue_rows),
        },
        "cash": {
            "recorded_balance": cash,
            "minimum_reserve": q2(profile.min_cash_reserve),
        },
        "inventory": _inventory_summary(db, owner_id),
        "counts": _source_counts(db, owner_id),
        "integration": {
            "status": client.integration_status,
            "last_synced_at": (
                client.integration_last_synced_at.isoformat()
                if client.integration_last_synced_at
                else None
            ),
            "inbox": _inbox_counts(db, client.id),
            "drafts": _draft_counts(db, client.id),
        },
        "tally": _tally_summary(db, client.id),
        "note": (
            "Read-only view of the linked business ledger for accounting review. "
            "Business records are never edited from the accountant portal."
        ),
    }


def _invoice_row(invoice: Invoice) -> dict:
    customer = invoice.customer
    party_name = (
        invoice.customer_name
        or (customer.name if customer else None)
        or "Unnamed customer"
    )
    tax = q2(
        Decimal(invoice.cgst_amount or ZERO)
        + Decimal(invoice.sgst_amount or ZERO)
        + Decimal(invoice.igst_amount or ZERO)
    )
    return {
        "source_type": "invoice",
        "source_id": invoice.id,
        "transaction_type": "sale",
        "date": invoice.issue_date.isoformat(),
        "financial_year": financial_year_for(invoice.issue_date),
        "reference": invoice.number,
        "party_name": party_name,
        "party_gstin": invoice.customer_gstin or (customer.gstin if customer else None),
        "category": "Sales",
        "narration": invoice.notes or f"Sales invoice {invoice.number}",
        "currency": invoice.currency or "INR",
        "taxable_value": q2(invoice.taxable_amount),
        "tax_amount": tax,
        "total_amount": q2(invoice.total_amount),
        "source_status": invoice.status or "issued",
    }


def _payment_row(payment: Payment) -> dict:
    invoice = payment.invoice
    is_refund = payment.refund_of_payment_id is not None
    party_name = (
        payment.sender_name
        or (invoice.customer_name if invoice is not None else None)
        or (
            invoice.customer.name
            if invoice is not None and invoice.customer is not None
            else None
        )
        or ("Customer refund" if is_refund else "Customer")
    )
    received = payment.received_at or payment.created_at
    return {
        "source_type": "payment",
        "source_id": payment.id,
        "transaction_type": "refund" if is_refund else "receipt",
        "date": received.date().isoformat(),
        "financial_year": financial_year_for(received.date()),
        "reference": payment.provider_ref or f"PMT-{payment.id}",
        "party_name": party_name,
        "party_gstin": invoice.customer_gstin if invoice is not None else None,
        "category": "Refunds" if is_refund else "Receipts",
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
        "tax_amount": ZERO,
        "total_amount": q2(payment.amount),
        "source_status": payment.status or "pending",
    }


def _expense_row(expense: Expense) -> dict:
    return {
        "source_type": "expense",
        "source_id": expense.id,
        "transaction_type": "expense",
        "date": expense.incurred_on.isoformat(),
        "financial_year": financial_year_for(expense.incurred_on),
        "reference": f"EXP-{expense.id}",
        "party_name": expense.vendor or "Unnamed vendor",
        "party_gstin": None,
        "category": expense.category,
        "narration": expense.note or f"{expense.category} expense",
        "currency": "INR",
        "taxable_value": q2(expense.amount),
        "tax_amount": ZERO,
        "total_amount": q2(expense.amount),
        "source_status": "recorded",
    }


def _source_rows(db: Session, owner_id: int) -> list[dict]:
    rows: list[dict] = []
    invoices = (
        db.query(Invoice)
        .options(selectinload(Invoice.customer))
        .filter(Invoice.user_id == owner_id)
        .all()
    )
    rows.extend(_invoice_row(invoice) for invoice in invoices)
    payments = (
        db.query(Payment)
        .options(selectinload(Payment.invoice).selectinload(Invoice.customer))
        .filter(Payment.user_id == owner_id)
        .all()
    )
    rows.extend(_payment_row(payment) for payment in payments)
    expenses = db.query(Expense).filter(Expense.user_id == owner_id).all()
    rows.extend(_expense_row(expense) for expense in expenses)
    return rows


def _empty_summary() -> dict:
    return {
        key: {"count": 0, "total": ZERO}
        for key in TRANSACTION_TYPES
    }


def _summarise(rows: list[dict]) -> dict:
    summary = _empty_summary()
    for row in rows:
        bucket = summary[row["transaction_type"]]
        bucket["count"] += 1
        bucket["total"] = q2(bucket["total"] + Decimal(row["total_amount"]))
    summary["net_total"] = q2(sum((summary[key]["total"] for key in TRANSACTION_TYPES), ZERO))
    return summary


def _attach_accounting(db: Session, client_id: int, rows: list[dict]) -> None:
    if not rows:
        return
    source_ids: dict[str, set[int]] = {}
    for row in rows:
        source_ids.setdefault(row["source_type"], set()).add(row["source_id"])
    inbox_rows = (
        db.query(AccountingBusinessTransaction)
        .filter(
            AccountingBusinessTransaction.client_id == client_id,
            AccountingBusinessTransaction.source_type.in_(tuple(source_ids.keys())),
        )
        .all()
    )
    inbox_map = {
        (row.source_type, row.source_id): row
        for row in inbox_rows
        if row.source_id in source_ids.get(row.source_type, set())
    }
    transaction_ids = [row.id for row in inbox_map.values()]
    drafts: dict[int, AccountingEntryDraft] = {}
    vouchers: dict[int, AccountingVoucher] = {}
    if transaction_ids:
        drafts = {
            draft.transaction_id: draft
            for draft in db.query(AccountingEntryDraft)
            .filter(AccountingEntryDraft.transaction_id.in_(transaction_ids))
            .all()
        }
        vouchers = {
            voucher.source_transaction_id: voucher
            for voucher in db.query(AccountingVoucher)
            .filter(AccountingVoucher.source_transaction_id.in_(transaction_ids))
            .all()
        }
    for row in rows:
        inbox = inbox_map.get((row["source_type"], row["source_id"]))
        draft = drafts.get(inbox.id) if inbox else None
        voucher = vouchers.get(inbox.id) if inbox else None
        row["accounting"] = {
            "inbox_id": inbox.id if inbox else None,
            "inbox_status": inbox.status if inbox else "not_synced",
            "draft_id": draft.id if draft else None,
            "draft_number": draft.number if draft else None,
            "draft_status": draft.status if draft else None,
            "voucher_id": voucher.id if voucher else None,
            "voucher_number": voucher.number if voucher else None,
        }


def business_transactions(
    db: Session,
    client: AccountingClient,
    *,
    transaction_type: str | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    profile = client.business_profile
    if client.business_profile_id is None or profile is None:
        return {
            "linked": False,
            "business": None,
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "summary": _empty_summary(),
            "note": "No Business Manager business is linked to this engagement.",
        }

    rows = _source_rows(db, profile.user_id)
    if transaction_type:
        rows = [row for row in rows if row["transaction_type"] == transaction_type]
    if date_from:
        rows = [row for row in rows if row["date"] >= date_from.isoformat()]
    if date_to:
        rows = [row for row in rows if row["date"] <= date_to.isoformat()]
    if search:
        needle = search.strip().lower()
        rows = [
            row
            for row in rows
            if needle in row["reference"].lower()
            or needle in row["party_name"].lower()
            or needle in (row["category"] or "").lower()
            or needle in (row["narration"] or "").lower()
        ]

    rows.sort(key=lambda row: (row["date"], row["source_type"], row["source_id"]), reverse=True)
    total = len(rows)
    summary = _summarise(rows)
    page = rows[offset : offset + limit]
    _attach_accounting(db, client.id, page)

    return {
        "linked": True,
        "business": _business_payload(profile),
        "items": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": summary,
        "note": (
            "Live Business Manager records, read-only. The accounting status shows "
            "whether each record has been synced, drafted, reviewed or posted."
        ),
    }
