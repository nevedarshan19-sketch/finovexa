"""Accounting practice helpers: serialisation, access control, imports and matching.

Calculations live in :mod:`app.services.accounting_math`; this module only moves
records around, enforces who may see what, and parses uploaded files.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AccountingBankImport,
    AccountingBankTransaction,
    AccountingClient,
    AccountingDocument,
    AccountingDocumentRequest,
    AccountingEnquiry,
    AccountingInvoice,
    AccountingMessage,
    AccountingNotification,
    AccountingQuotation,
    AccountingReport,
    AccountingTallyBatch,
    AccountingTask,
    AccountingTaskComment,
    AccountingVoucher,
    User,
    utcnow,
)
from .accounting_math import (
    GSTIN_RE,
    financial_year_for,
    month_bounds,
    q2,
    split_gst,
    voucher_dedupe_hash,
)
from .file_store import save_bytes

ZERO = Decimal("0.00")
ACCOUNTANT_ROLES = ("senior_accountant", "junior_accountant")
MAX_UPLOAD_BYTES = max(settings.ACCOUNTING_MAX_UPLOAD_MB, 1) * 1024 * 1024

VISIBILITY_INTERNAL = "internal"
VISIBILITY_SHARED = "shared"


# ---------------------------------------------------------------- references


def _next_number(db: Session, model: type, field: str, prefix: str) -> str:
    rows = db.query(getattr(model, field)).filter(getattr(model, field).like(f"{prefix}%")).all()
    highest = 0
    for (value,) in rows:
        match = re.search(r"(\d+)$", value or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:04d}"


def next_enquiry_reference(db: Session) -> str:
    return _next_number(db, AccountingEnquiry, "reference", f"ACC-ENQ-{date.today().year}-")


def next_quotation_number(db: Session) -> str:
    return _next_number(db, AccountingQuotation, "number", f"ACC-QT-{date.today().year}-")


def next_client_code(db: Session) -> str:
    return _next_number(db, AccountingClient, "code", f"ACC-{date.today().year}-")


def next_invoice_number(db: Session) -> str:
    return _next_number(db, AccountingInvoice, "number", f"ACC-INV-{date.today().year}-")


# ---------------------------------------------------------------- access


def client_for_customer(db: Session, user: User) -> AccountingClient | None:
    if user.role != "customer":
        return None
    return (
        db.query(AccountingClient)
        .filter(AccountingClient.customer_user_id == user.id)
        .one_or_none()
    )


def junior_has_client(db: Session, user: User, client: AccountingClient) -> bool:
    if client.assigned_junior_user_id == user.id:
        return True
    return (
        db.query(AccountingTask.id)
        .filter(
            AccountingTask.client_id == client.id,
            AccountingTask.assigned_to_user_id == user.id,
        )
        .first()
        is not None
    )


def ensure_client_access(db: Session, user: User, client_id: int) -> AccountingClient:
    client = db.get(AccountingClient, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client record not found.")
    if user.role == "senior_accountant":
        return client
    if user.role == "junior_accountant":
        if junior_has_client(db, user, client):
            return client
        raise HTTPException(status_code=403, detail="This client is not assigned to you.")
    if user.role == "customer":
        if client.customer_user_id == user.id:
            return client
        raise HTTPException(status_code=403, detail="You can only access your own account.")
    raise HTTPException(status_code=403, detail="Accounting access required.")


def staff_client_filter(db: Session, user: User):
    """A query for clients a staff member may read, or None for all seniors."""
    if user.role == "senior_accountant":
        return None
    task_clients = db.query(AccountingTask.client_id).filter(
        AccountingTask.assigned_to_user_id == user.id
    )
    return or_(
        AccountingClient.assigned_junior_user_id == user.id,
        AccountingClient.id.in_(task_clients),
    )


def task_for_staff(db: Session, user: User, task_id: int) -> AccountingTask:
    task = db.get(AccountingTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if user.role == "senior_accountant":
        return task
    if user.role == "junior_accountant" and task.assigned_to_user_id == user.id:
        return task
    raise HTTPException(status_code=403, detail="This task is not assigned to you.")


def document_for_reader(db: Session, user: User, document_id: int) -> AccountingDocument:
    document = db.get(AccountingDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if user.role in ACCOUNTANT_ROLES:
        ensure_client_access(db, user, document.client_id)
        return document
    if user.role == "customer":
        client = client_for_customer(db, user)
        if client is None or client.id != document.client_id:
            raise HTTPException(status_code=403, detail="You can only access your own documents.")
        if document.visibility != VISIBILITY_SHARED and document.uploaded_by_user_id != user.id:
            raise HTTPException(status_code=403, detail="This document is not shared with you.")
        return document
    raise HTTPException(status_code=403, detail="Document access required.")


# ---------------------------------------------------------------- serialisation


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def enquiry_to_dict(enquiry: AccountingEnquiry, *, internal: bool = False) -> dict:
    data = {
        "id": enquiry.id,
        "reference": enquiry.reference,
        "business_name": enquiry.business_name,
        "contact_name": enquiry.contact_name,
        "email": enquiry.email,
        "phone": enquiry.phone,
        "business_type": enquiry.business_type,
        "turnover_range": enquiry.turnover_range,
        "gst_status": enquiry.gst_status,
        "services": enquiry.services or [],
        "monthly_transactions": enquiry.monthly_transactions,
        "requirements": enquiry.requirements,
        "status": enquiry.status,
        "source": enquiry.source,
        "annual_turnover": enquiry.annual_turnover,
        "bank_accounts": enquiry.bank_accounts,
        "payroll_required": enquiry.payroll_required,
        "inventory_required": enquiry.inventory_required,
        "financial_year": enquiry.financial_year,
        "benchmark_annual": enquiry.benchmark_annual,
        "created_at": _iso(enquiry.created_at),
    }
    if internal:
        data["assigned_senior_user_id"] = enquiry.assigned_senior_user_id
        data["internal_notes"] = enquiry.internal_notes
        data["customer_user_id"] = enquiry.customer_user_id
    return data


def quotation_status(quotation: AccountingQuotation) -> str:
    if quotation.status == "sent" and quotation.valid_until and quotation.valid_until < date.today():
        return "expired"
    return quotation.status


def quotation_to_dict(quotation: AccountingQuotation, *, internal: bool = True) -> dict:
    data = {
        "id": quotation.id,
        "number": quotation.number,
        "enquiry_id": quotation.enquiry_id,
        "client_id": quotation.client_id,
        "currency": quotation.currency,
        "amount": quotation.amount,
        "billing_cadence": quotation.billing_cadence,
        "scope": quotation.scope or [],
        "terms": quotation.terms,
        "valid_until": _iso(quotation.valid_until),
        "status": quotation_status(quotation),
        "line_items": quotation.line_items or [],
        "annual_turnover": quotation.annual_turnover,
        "benchmark_annual": quotation.benchmark_annual,
        "subtotal_annual": quotation.subtotal_annual,
        "total_annual": quotation.total_annual,
        "monthly_equivalent": quotation.monthly_equivalent,
        "discount_type": quotation.discount_type,
        "discount_value": quotation.discount_value,
        "discount_amount": quotation.discount_amount,
        "payment_frequency": quotation.payment_frequency,
        "validity_days": quotation.validity_days,
        "tax_rate_percent": quotation.tax_rate_percent,
        "tax_note": quotation.tax_note,
        "approved_at": _iso(quotation.approved_at),
        "sent_at": _iso(quotation.sent_at),
        "rejected_at": _iso(quotation.rejected_at),
        "rejection_note": quotation.rejection_note,
        "accepted_at": _iso(quotation.accepted_at),
        "responded_at": _iso(quotation.responded_at),
        "response_note": quotation.response_note,
        "created_at": _iso(quotation.created_at),
    }
    if internal:
        data["prepared_by_user_id"] = quotation.prepared_by_user_id
        data["prepared_by_name"] = quotation.prepared_by.full_name if quotation.prepared_by else None
        data["approved_by_user_id"] = quotation.approved_by_user_id
        data["approved_by_name"] = quotation.approved_by.full_name if quotation.approved_by else None
        data["rejected_by_user_id"] = quotation.rejected_by_user_id
        data["rejected_by_name"] = quotation.rejected_by.full_name if quotation.rejected_by else None
        data["discount_note"] = quotation.discount_note
        if quotation.enquiry is not None:
            data["enquiry_reference"] = quotation.enquiry.reference
            data["enquiry"] = {
                "reference": quotation.enquiry.reference,
                "business_name": quotation.enquiry.business_name,
                "contact_name": quotation.enquiry.contact_name,
                "email": quotation.enquiry.email,
                "phone": quotation.enquiry.phone,
                "business_type": quotation.enquiry.business_type,
                "turnover_range": quotation.enquiry.turnover_range,
                "gst_status": quotation.enquiry.gst_status,
                "services": quotation.enquiry.services or [],
                "monthly_transactions": quotation.enquiry.monthly_transactions,
                "annual_turnover": quotation.enquiry.annual_turnover,
                "bank_accounts": quotation.enquiry.bank_accounts,
                "payroll_required": quotation.enquiry.payroll_required,
                "inventory_required": quotation.enquiry.inventory_required,
                "financial_year": quotation.enquiry.financial_year,
                "benchmark_annual": quotation.enquiry.benchmark_annual,
            }
        if quotation.client is not None:
            data["client_name"] = quotation.client.business_name
    return data


def client_to_dict(db: Session, client: AccountingClient, *, detail: bool = False) -> dict:
    data = {
        "id": client.id,
        "code": client.code,
        "business_name": client.business_name,
        "contact_name": client.contact_name,
        "email": client.email,
        "phone": client.phone,
        "business_type": client.business_type,
        "turnover_range": client.turnover_range,
        "gst_status": client.gst_status,
        "gstin": client.gstin,
        "pan_last4": client.pan_last4,
        "financial_year": client.financial_year,
        "service_package": client.service_package,
        "status": client.status,
        "customer_user_id": client.customer_user_id,
        "business_profile_id": client.business_profile_id,
        "linked_business": (
            {
                "id": client.business_profile.id,
                "business_name": client.business_profile.business_name,
                "gstin": client.business_profile.gstin,
                "city": client.business_profile.city,
                "state": client.business_profile.state,
            }
            if client.business_profile is not None
            else None
        ),
        "integration": {
            "status": client.integration_status,
            "enabled_at": _iso(client.integration_enabled_at),
            "last_synced_at": _iso(client.integration_last_synced_at),
            "settings": client.integration_settings or {},
        },
        "senior_accountant_user_id": client.senior_accountant_user_id,
        "assigned_junior_user_id": client.assigned_junior_user_id,
        "senior_name": client.senior_accountant.full_name if client.senior_accountant else None,
        "junior_name": client.assigned_junior.full_name if client.assigned_junior else None,
        "onboarded_at": _iso(client.onboarded_at),
        "notes": client.notes,
        "created_at": _iso(client.created_at),
    }
    if detail:
        open_tasks = (
            db.query(func.count(AccountingTask.id))
            .filter(
                AccountingTask.client_id == client.id,
                AccountingTask.status.in_(
                    ("unassigned", "assigned", "in_progress", "submitted", "changes_requested")
                ),
            )
            .scalar()
            or 0
        )
        documents = (
            db.query(func.count(AccountingDocument.id))
            .filter(AccountingDocument.client_id == client.id)
            .scalar()
            or 0
        )
        invoices = (
            db.query(AccountingInvoice).filter(AccountingInvoice.client_id == client.id).all()
        )
        outstanding = q2(sum((inv.outstanding_amount for inv in invoices), ZERO))
        overdue = q2(
            sum(
                (
                    inv.outstanding_amount
                    for inv in invoices
                    if inv.status != "void" and inv.due_date < date.today()
                ),
                ZERO,
            )
        )
        data["counts"] = {
            "open_tasks": open_tasks,
            "documents": documents,
            "invoices": len(invoices),
            "reports": db.query(func.count(AccountingReport.id))
            .filter(AccountingReport.client_id == client.id)
            .scalar()
            or 0,
        }
        data["billing"] = {
            "invoiced": q2(sum((inv.total_amount for inv in invoices), ZERO)),
            "paid": q2(sum((inv.paid_amount for inv in invoices), ZERO)),
            "outstanding": outstanding,
            "overdue": overdue,
        }
    return data


def task_to_dict(task: AccountingTask, *, comments: bool = False) -> dict:
    data = {
        "id": task.id,
        "client_id": task.client_id,
        "client_name": task.client.business_name if task.client else None,
        "client_code": task.client.code if task.client else None,
        "title": task.title,
        "description": task.description,
        "service_type": task.service_type,
        "status": task.status,
        "priority": task.priority,
        "due_date": _iso(task.due_date),
        "assigned_to_user_id": task.assigned_to_user_id,
        "assignee_name": task.assignee.full_name if task.assignee else None,
        "progress": task.progress,
        "submitted_at": _iso(task.submitted_at),
        "reviewed_at": _iso(task.reviewed_at),
        "review_notes": task.review_notes,
        "delivered_at": _iso(task.delivered_at),
        "is_overdue": bool(
            task.due_date
            and task.due_date < date.today()
            and task.status not in ("approved", "delivered", "cancelled")
        ),
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }
    if comments:
        data["comments"] = [
            {
                "id": comment.id,
                "author_label": comment.author_label,
                "body": comment.body,
                "created_at": _iso(comment.created_at),
            }
            for comment in task.comments
        ]
    return data


def document_to_dict(document: AccountingDocument, *, include_url: bool = True) -> dict:
    return {
        "id": document.id,
        "client_id": document.client_id,
        "category": document.category,
        "title": document.title,
        "original_filename": document.original_filename,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "visibility": document.visibility,
        "source": document.source,
        "status": document.status,
        "note": document.note,
        "verified_at": _iso(document.verified_at),
        "created_at": _iso(document.created_at),
        "download_url": f"/accounting/documents/{document.id}/file" if include_url else None,
    }


def document_request_to_dict(request: AccountingDocumentRequest) -> dict:
    return {
        "id": request.id,
        "client_id": request.client_id,
        "title": request.title,
        "description": request.description,
        "due_date": _iso(request.due_date),
        "status": request.status,
        "fulfilled_document_id": request.fulfilled_document_id,
        "fulfilled_at": _iso(request.fulfilled_at),
        "created_at": _iso(request.created_at),
    }


def report_to_dict(report: AccountingReport, *, include_payload: bool = True) -> dict:
    data = {
        "id": report.id,
        "client_id": report.client_id,
        "client_name": report.client.business_name if report.client else None,
        "report_type": report.report_type,
        "financial_year": report.financial_year,
        "period_label": report.period_label,
        "status": report.status,
        "version": report.version,
        "review_notes": report.review_notes,
        "approved_at": _iso(report.approved_at),
        "delivered_at": _iso(report.delivered_at),
        "created_at": _iso(report.created_at),
    }
    if include_payload:
        data["payload"] = report.payload or {}
    return data


def invoice_to_dict(invoice: AccountingInvoice) -> dict:
    return {
        "id": invoice.id,
        "client_id": invoice.client_id,
        "client_name": invoice.client.business_name if invoice.client else None,
        "number": invoice.number,
        "issue_date": _iso(invoice.issue_date),
        "due_date": _iso(invoice.due_date),
        "period_label": invoice.period_label,
        "subtotal": invoice.subtotal,
        "tax_amount": invoice.tax_amount,
        "total_amount": invoice.total_amount,
        "paid_amount": invoice.paid_amount,
        "outstanding_amount": invoice.outstanding_amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "notes": invoice.notes,
        "is_overdue": bool(invoice.status != "void" and invoice.outstanding_amount > 0 and invoice.due_date < date.today()),
        "payments": [
            {
                "id": payment.id,
                "amount": payment.amount,
                "method": payment.method,
                "reference": payment.reference,
                "received_on": _iso(payment.received_on),
            }
            for payment in sorted(invoice.payments, key=lambda p: (p.received_on, p.id))
        ],
        "created_at": _iso(invoice.created_at),
    }


def voucher_to_dict(voucher: AccountingVoucher) -> dict:
    return {
        "id": voucher.id,
        "client_id": voucher.client_id,
        "voucher_type": voucher.voucher_type,
        "number": voucher.number,
        "voucher_date": _iso(voucher.voucher_date),
        "party_name": voucher.party_name,
        "party_gstin": voucher.party_gstin,
        "ledger_name": voucher.ledger_name,
        "bank_ledger": voucher.bank_ledger,
        "category": voucher.category,
        "description": voucher.description,
        "taxable_value": voucher.taxable_value,
        "gst_rate": voucher.gst_rate,
        "inter_state": voucher.inter_state,
        "cgst_amount": voucher.cgst_amount,
        "sgst_amount": voucher.sgst_amount,
        "igst_amount": voucher.igst_amount,
        "total_amount": voucher.total_amount,
        "source": voucher.source,
        "status": voucher.status,
        "created_at": _iso(voucher.created_at),
    }


def bank_transaction_to_dict(txn: AccountingBankTransaction) -> dict:
    return {
        "id": txn.id,
        "import_id": txn.import_id,
        "txn_date": _iso(txn.txn_date),
        "description": txn.description,
        "reference": txn.reference,
        "debit": txn.debit,
        "credit": txn.credit,
        "status": txn.status,
        "matched_voucher_id": txn.matched_voucher_id,
        "match_score": txn.match_score,
        "match_note": txn.match_note,
    }


def bank_import_to_dict(record: AccountingBankImport, *, include_transactions: bool = True) -> dict:
    data = {
        "id": record.id,
        "client_id": record.client_id,
        "filename": record.filename,
        "row_count": record.row_count,
        "matched_count": record.matched_count,
        "status": record.status,
        "note": record.note,
        "created_at": _iso(record.created_at),
    }
    if include_transactions:
        data["transactions"] = [bank_transaction_to_dict(t) for t in record.transactions]
    return data


def message_to_dict(message: AccountingMessage) -> dict:
    return {
        "id": message.id,
        "client_id": message.client_id,
        "author_label": message.author_label,
        "author_role": message.author_role,
        "body": message.body,
        "created_at": _iso(message.created_at),
    }


def notification_to_dict(notification: AccountingNotification) -> dict:
    return {
        "id": notification.id,
        "client_id": notification.client_id,
        "kind": notification.kind,
        "title": notification.title,
        "body": notification.body,
        "read": notification.read_at is not None,
        "created_at": _iso(notification.created_at),
    }


def tally_batch_to_dict(batch: AccountingTallyBatch) -> dict:
    return {
        "id": batch.id,
        "client_id": batch.client_id,
        "direction": batch.direction,
        "filename": batch.filename,
        "format": batch.format,
        "row_count": batch.row_count,
        "valid_count": batch.valid_count,
        "duplicate_count": batch.duplicate_count,
        "error_count": batch.error_count,
        "status": batch.status,
        "details": batch.details or {},
        "created_at": _iso(batch.created_at),
    }


# ---------------------------------------------------------------- notifications & audit labels


def notify(
    db: Session,
    user_id: int | None,
    *,
    kind: str,
    title: str,
    body: str,
    client_id: int | None = None,
) -> AccountingNotification | None:
    if not user_id:
        return None
    notification = AccountingNotification(
        user_id=user_id,
        client_id=client_id,
        kind=kind,
        title=title,
        body=body,
    )
    db.add(notification)
    return notification


# ---------------------------------------------------------------- files


_MIME_BY_SUFFIX = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "txt": "text/plain",
}

_SUFFIX_BY_PREFIX = (
    ("data:application/pdf", "pdf"),
    ("data:image/png", "png"),
    ("data:image/jpeg", "jpg"),
    ("data:text/csv", "csv"),
    ("data:text/plain", "txt"),
    ("data:application/xml", "xml"),
    ("data:text/xml", "xml"),
    ("data:application/json", "json"),
    ("data:text/json", "json"),
    ("data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    ("data:application/vnd.ms-excel", "xls"),
    ("data:application/octet-stream", "bin"),
)


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """Return (content, suffix). Raises HTTPException for bad or oversized files."""
    if "," not in data_url:
        raise HTTPException(status_code=422, detail="The uploaded file is not a valid data URL.")
    header, encoded = data_url.split(",", 1)
    suffix = next((suffix for prefix, suffix in _SUFFIX_BY_PREFIX if header.startswith(prefix)), "bin")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="The uploaded file could not be decoded.") from exc
    if not raw:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Files must be smaller than {settings.ACCOUNTING_MAX_UPLOAD_MB} MB.",
        )
    return raw, suffix


def save_document_file(
    db: Session, raw: bytes, suffix: str, *, content_type: str = ""
) -> tuple[str, str, int]:
    return save_bytes(db, raw, suffix, content_type=content_type)


def content_type_for(suffix: str, declared: str | None = None) -> str:
    if declared and "/" in declared:
        return declared
    return _MIME_BY_SUFFIX.get(suffix.lower(), "application/octet-stream")


# ---------------------------------------------------------------- vouchers


class DuplicateVoucher(Exception):
    def __init__(self, voucher: AccountingVoucher) -> None:
        super().__init__(f"Voucher {voucher.number} already exists for this client.")
        self.voucher = voucher


def create_voucher(
    db: Session,
    *,
    client_id: int,
    voucher_type: str,
    number: str,
    voucher_date: date,
    party_name: str,
    party_gstin: str | None,
    ledger_name: str,
    category: str | None,
    description: str | None,
    taxable_value: Decimal,
    gst_rate: Decimal,
    inter_state: bool,
    created_by: User | None,
    source: str = "manual",
    bank_ledger: str | None = None,
) -> AccountingVoucher:
    amounts = split_gst(taxable_value, gst_rate, inter_state)
    dedupe = voucher_dedupe_hash(client_id, voucher_type, number, voucher_date, amounts["total"])
    existing = (
        db.query(AccountingVoucher)
        .filter(
            AccountingVoucher.client_id == client_id,
            AccountingVoucher.dedupe_hash == dedupe,
        )
        .one_or_none()
    )
    if existing is not None:
        raise DuplicateVoucher(existing)
    gstin = party_gstin.strip().upper() if party_gstin else None
    voucher = AccountingVoucher(
        client_id=client_id,
        voucher_type=voucher_type,
        number=number.strip(),
        voucher_date=voucher_date,
        party_name=party_name.strip(),
        party_gstin=gstin or None,
        ledger_name=ledger_name.strip(),
        bank_ledger=(bank_ledger or "").strip() or None,
        category=category,
        description=description,
        taxable_value=q2(taxable_value),
        gst_rate=Decimal(gst_rate),
        inter_state=inter_state,
        cgst_amount=amounts["cgst"],
        sgst_amount=amounts["sgst"],
        igst_amount=amounts["igst"],
        total_amount=amounts["total"],
        source=source,
        status="posted",
        dedupe_hash=dedupe,
        created_by_user_id=created_by.id if created_by else None,
    )
    db.add(voucher)
    db.flush()
    return voucher


# ---------------------------------------------------------------- tabular parsing


def _coerce_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        return q2(Decimal(str(value)))
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return q2(Decimal(cleaned))
    except InvalidOperation:
        return None


def _coerce_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:11].strip(), pattern).date()
        except ValueError:
            continue
    return None


def parse_csv_rows(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return [
        {(key or "").strip(): value for key, value in row.items() if key is not None}
        for row in reader
    ]


def parse_xlsx_rows(raw: bytes) -> list[dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise HTTPException(
            status_code=503,
            detail="Excel parsing is unavailable on this server. Upload a CSV file instead.",
        ) from exc
    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="This Excel file could not be read.") from exc
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    workbook.close()
    if not rows:
        return []
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    parsed: list[dict[str, Any]] = []
    for row in rows[1:]:
        if row is None or all(cell in (None, "") for cell in row):
            continue
        parsed.append({headers[i]: row[i] for i in range(min(len(headers), len(row)))})
    return parsed


def parse_tabular(raw: bytes, suffix: str) -> tuple[list[dict[str, Any]], str]:
    if suffix in ("xlsx", "xls"):
        return parse_xlsx_rows(raw), "xlsx"
    if suffix in ("csv", "txt", "bin"):
        return parse_csv_rows(raw), "csv"
    raise HTTPException(status_code=422, detail="Upload a CSV or Excel file for this import.")


_HEADER_ALIASES = {
    "date": ("date", "txn date", "transaction date", "value date", "voucher_date", "voucher date"),
    "description": ("description", "narration", "particulars", "details"),
    "reference": ("reference", "ref", "cheque no", "chq no", "utr"),
    "debit": ("debit", "withdrawal", "dr", "debit amount"),
    "credit": ("credit", "deposit", "cr", "credit amount"),
    "amount": ("amount", "value"),
}


def _match_header(row: dict[str, Any], field: str) -> str | None:
    lowered = {str(key).strip().lower(): key for key in row if key is not None}
    for alias in _HEADER_ALIASES.get(field, ()):
        if alias in lowered:
            return lowered[alias]
    return None


def normalise_bank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        date_key = _match_header(row, "date")
        description_key = _match_header(row, "description")
        reference_key = _match_header(row, "reference")
        debit_key = _match_header(row, "debit")
        credit_key = _match_header(row, "credit")
        amount_key = _match_header(row, "amount")
        txn_date = _coerce_date(row.get(date_key)) if date_key else None
        description = str(row.get(description_key) or "").strip() if description_key else ""
        if txn_date is None or not description:
            continue
        debit = _coerce_decimal(row.get(debit_key)) if debit_key else None
        credit = _coerce_decimal(row.get(credit_key)) if credit_key else None
        amount = _coerce_decimal(row.get(amount_key)) if amount_key else None
        if amount is not None and debit is None and credit is None:
            if amount >= 0:
                credit = amount
            else:
                debit = abs(amount)
        normalised.append(
            {
                "row": index,
                "txn_date": txn_date,
                "description": description[:255],
                "reference": (
                    str(row.get(reference_key)).strip()[:120]
                    if reference_key and row.get(reference_key) not in (None, "")
                    else None
                ),
                "debit": debit or ZERO,
                "credit": credit or ZERO,
            }
        )
    return normalised


def _name_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^A-Za-z0-9]+", value.upper()) if len(token) > 2}


def suggest_match(
    txn: dict[str, Any], vouchers: Iterable[AccountingVoucher]
) -> tuple[AccountingVoucher | None, int, str]:
    amount = txn["credit"] if txn["credit"] > 0 else txn["debit"]
    direction = "credit" if txn["credit"] > 0 else "debit"
    wanted = ("sale",) if direction == "credit" else ("purchase", "payment")
    best: AccountingVoucher | None = None
    best_score = 0
    description_tokens = _name_tokens(txn["description"]) | _name_tokens(txn.get("reference") or "")
    for voucher in vouchers:
        if voucher.voucher_type not in wanted:
            continue
        if abs(voucher.total_amount - amount) > Decimal("0.01"):
            continue
        score = 90
        if txn.get("reference") and txn["reference"].lower() in voucher.number.lower():
            score += 5
        if description_tokens & _name_tokens(voucher.party_name):
            score += 5
        if best is None or score > best_score:
            best, best_score = voucher, min(score, 100)
    if best is not None:
        return best, best_score, f"Amount matches {best.voucher_type} voucher {best.number}."
    return None, 40, "No recorded voucher matches this amount exactly."


def recompute_import_matches(db: Session, record: AccountingBankImport) -> None:
    vouchers = (
        db.query(AccountingVoucher).filter(AccountingVoucher.client_id == record.client_id).all()
    )
    matched = 0
    for txn in record.transactions:
        if txn.status == "matched":
            matched += 1
            continue
        voucher, score, note = suggest_match(
            {"credit": txn.credit, "debit": txn.debit, "description": txn.description, "reference": txn.reference},
            vouchers,
        )
        if txn.status != "confirmed":
            txn.status = "suggested" if voucher else "unmatched"
        txn.match_score = score
        txn.match_note = note
        txn.matched_voucher_id = voucher.id if (txn.status == "suggested" and voucher) else None
    record.matched_count = matched


# ---------------------------------------------------------------- tally


_TALLY_ALIASES = {
    "voucher_type": ("voucher_type", "voucher type", "type"),
    "number": ("number", "voucher_no", "voucher no", "voucher number"),
    "voucher_date": ("voucher_date", "voucher date", "date"),
    "party_name": ("party_name", "party name", "party", "ledger party"),
    "party_gstin": ("party_gstin", "gstin", "party gstin"),
    "ledger_name": ("ledger_name", "ledger name", "ledger"),
    "bank_ledger": ("bank_ledger", "bank ledger", "bank", "bank account", "payment account"),
    "category": ("category",),
    "description": ("description", "narration", "particulars"),
    "taxable_value": ("taxable_value", "taxable value", "amount", "value"),
    "gst_rate": ("gst_rate", "gst rate", "rate"),
    "inter_state": ("inter_state", "inter state", "igst"),
}

_VOUCHER_TYPES = ("sale", "purchase", "journal", "payment", "receipt", "expense")


def _pick(row: dict[str, Any], field: str) -> Any:
    lowered = {str(key).strip().lower(): key for key in row if key is not None}
    for alias in _TALLY_ALIASES.get(field, ()):
        if alias in lowered:
            return row[lowered[alias]]
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "igst", "inter")


def import_tally_rows(
    db: Session,
    *,
    client_id: int,
    rows: list[dict[str, Any]],
    actor: User | None,
    filename: str,
    fmt: str,
    stored_name: str | None = None,
) -> AccountingTallyBatch:
    batch = AccountingTallyBatch(
        client_id=client_id,
        direction="import",
        created_by_user_id=actor.id if actor else None,
        filename=filename[:255],
        format=fmt,
        stored_name=stored_name,
        row_count=len(rows),
        status="completed",
    )
    errors: list[dict[str, Any]] = []
    duplicates: list[str] = []
    valid = 0
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        voucher_type = str(_pick(row, "voucher_type") or "").strip().lower()
        number = str(_pick(row, "number") or "").strip()
        voucher_date = _coerce_date(_pick(row, "voucher_date"))
        party = str(_pick(row, "party_name") or "").strip()
        ledger = str(_pick(row, "ledger_name") or "").strip()
        taxable = _coerce_decimal(_pick(row, "taxable_value"))
        rate = _coerce_decimal(_pick(row, "gst_rate")) or ZERO
        problems: list[str] = []
        if voucher_type not in _VOUCHER_TYPES:
            problems.append(
                "Voucher type must be sale, purchase, journal, payment, receipt or expense."
            )
        if not number:
            problems.append("Voucher number is required.")
        if voucher_date is None:
            problems.append("A valid date is required.")
        if not party:
            problems.append("Party name is required.")
        if not ledger:
            problems.append("Ledger name is required.")
        if taxable is None or taxable <= 0:
            problems.append("Taxable value must be greater than zero.")
        if rate < 0 or rate > 28:
            problems.append("GST rate must be between 0 and 28.")
        if problems:
            if len(errors) < 50:
                errors.append({"row": index, "number": number or None, "problems": problems})
            continue
        try:
            create_voucher(
                db,
                client_id=client_id,
                voucher_type=voucher_type,
                number=number,
                voucher_date=voucher_date,
                party_name=party,
                party_gstin=_pick(row, "party_gstin"),
                ledger_name=ledger,
                bank_ledger=str(_pick(row, "bank_ledger") or "").strip() or None,
                category=str(_pick(row, "category") or "").strip() or None,
                description=str(_pick(row, "description") or "").strip() or None,
                taxable_value=taxable,
                gst_rate=rate,
                inter_state=_truthy(_pick(row, "inter_state")),
                created_by=actor,
                source="tally",
            )
            valid += 1
            seen.add(number)
        except DuplicateVoucher:
            duplicates.append(number)
    batch.valid_count = valid
    batch.duplicate_count = len(duplicates)
    batch.error_count = max(len(rows) - valid - len(duplicates), len(errors))
    batch.details = {
        "errors": errors,
        "duplicates": duplicates[:50],
        "note": (
            "Tally import validates and posts vouchers into the workspace ledger. "
            "No connection to a Tally installation is made."
        ),
        "imported_numbers": sorted(seen)[:100],
    }
    db.add(batch)
    return batch


TALLY_EXPORT_HEADERS = [
    "Voucher Date",
    "Voucher Type",
    "Voucher Number",
    "Party Ledger",
    "Party GSTIN",
    "Ledger",
    "Bank / Cash Ledger",
    "Category",
    "Taxable Value",
    "GST Rate",
    "CGST",
    "SGST",
    "IGST",
    "Total",
    "Narration",
    "Place of Supply",
]


def tally_export_csv(vouchers: list[AccountingVoucher]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TALLY_EXPORT_HEADERS)
    for voucher in sorted(vouchers, key=lambda v: (v.voucher_date, v.id)):
        writer.writerow(
            [
                voucher.voucher_date.isoformat(),
                voucher.voucher_type.title(),
                voucher.number,
                voucher.party_name,
                voucher.party_gstin or "",
                voucher.ledger_name,
                voucher.bank_ledger or "",
                voucher.category or "",
                f"{q2(voucher.taxable_value):.2f}",
                f"{Decimal(voucher.gst_rate):.2f}",
                f"{q2(voucher.cgst_amount):.2f}",
                f"{q2(voucher.sgst_amount):.2f}",
                f"{q2(voucher.igst_amount):.2f}",
                f"{q2(voucher.total_amount):.2f}",
                voucher.description or "",
                "Inter-state" if voucher.inter_state else "Intra-state",
            ]
        )
    return buffer.getvalue()


# ---------------------------------------------------------------- bill reader (deterministic)


_BILL_PATTERNS = {
    "gstin": re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b"),
    "invoice_number": re.compile(
        r"(?:invoice|bill|tax invoice)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Za-z0-9/\-]{2,30})",
        re.IGNORECASE,
    ),
    "date": re.compile(
        r"(?:invoice|bill|dated|date)\s*[:\-]?\s*(\d{1,2}[\-\/\s][A-Za-z0-9]{2,9}[\-\/\s]\d{2,4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    ),
    "taxable": re.compile(
        r"(?:taxable\s*(?:value|amount)|sub\s*total|net\s*amount)\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    "tax": re.compile(
        r"(?:igst|cgst\s*\+\s*sgst|gst|tax\s*amount)\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    "total": re.compile(
        r"(?:grand\s*total|total\s*(?:amount|invoice value)?)\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
}

_LEDGER_HINTS = {
    "furniture": "Purchases - furniture",
    "chair": "Purchases - furniture",
    "stationery": "Office expenses",
    "rent": "Rent expense",
    "electricity": "Utilities",
    "transport": "Freight and transport",
    "software": "Software subscriptions",
    "professional": "Professional fees",
    "salary": "Salaries",
    "material": "Purchases - stock",
    "stock": "Purchases - stock",
}


def _extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail="PDF text extraction is unavailable on this server.") from exc
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages[:5]]
    except Exception as exc:
        raise HTTPException(status_code=422, detail="This PDF could not be read.") from exc
    return "\n".join(pages).strip()


def read_bill(raw: bytes, suffix: str) -> dict[str, Any]:
    warnings: list[str] = []
    text = ""
    if suffix == "pdf":
        text = _extract_pdf_text(raw)
        if not text:
            warnings.append("The PDF has no machine-readable text. Enter the fields manually.")
    elif suffix in ("csv", "txt", "bin"):
        text = raw.decode("utf-8", errors="replace")
    else:
        warnings.append(
            "Images are not OCR-processed on this server. Enter the fields from the bill manually and verify them."
        )

    fields: dict[str, Any] = {
        "invoice_number": None,
        "invoice_date": None,
        "party_gstin": None,
        "taxable_value": None,
        "tax_amount": None,
        "total_amount": None,
        "gst_rate": None,
        "suggested_ledger": None,
        "confidence": {},
    }
    if text:
        gstin = _BILL_PATTERNS["gstin"].search(text.upper())
        if gstin:
            fields["party_gstin"] = gstin.group(1)
        number = _BILL_PATTERNS["invoice_number"].search(text)
        if number:
            fields["invoice_number"] = number.group(1).strip().rstrip(".")
        found_date = _BILL_PATTERNS["date"].search(text)
        if found_date:
            parsed = _coerce_date(found_date.group(1))
            if parsed:
                fields["invoice_date"] = parsed.isoformat()
        taxable = _BILL_PATTERNS["taxable"].search(text)
        if taxable:
            fields["taxable_value"] = float(_coerce_decimal(taxable.group(1)) or 0)
        tax = _BILL_PATTERNS["tax"].search(text)
        if tax:
            fields["tax_amount"] = float(_coerce_decimal(tax.group(1)) or 0)
        total = _BILL_PATTERNS["total"].search(text)
        if total:
            fields["total_amount"] = float(_coerce_decimal(total.group(1)) or 0)
        if fields["taxable_value"] and fields["tax_amount"]:
            rate = q2(Decimal(str(fields["tax_amount"])) / Decimal(str(fields["taxable_value"])) * 100)
            if rate in (Decimal("5.00"), Decimal("12.00"), Decimal("18.00"), Decimal("28.00")):
                fields["gst_rate"] = float(rate)
        lowered = text.lower()
        for hint, ledger in _LEDGER_HINTS.items():
            if hint in lowered:
                fields["suggested_ledger"] = ledger
                break

    fields["confidence"] = {
        key: ("high" if fields[key] not in (None, "") else "missing")
        for key in ("invoice_number", "invoice_date", "party_gstin", "taxable_value", "total_amount")
    }
    uncertain = [key for key, level in fields["confidence"].items() if level == "missing"]
    if uncertain:
        warnings.append(
            "Confirm these fields before saving: " + ", ".join(key.replace("_", " ") for key in uncertain) + "."
        )
    return {
        "fields": fields,
        "warnings": warnings,
        "saved": False,
        "requires_human_verification": True,
        "source_text_preview": text[:800] if text else "",
        "note": (
            "Extraction is rule-based and never writes to the ledger. Review the values, then post the "
            "voucher through the normal entry form."
        ),
    }


# ---------------------------------------------------------------- practice reporting helpers


def practice_receivables(db: Session, client_id: int | None = None) -> dict[str, Any]:
    query = db.query(AccountingInvoice).filter(AccountingInvoice.status != "void")
    if client_id is not None:
        query = query.filter(AccountingInvoice.client_id == client_id)
    invoices = query.all()
    today = date.today()
    overdue = [inv for inv in invoices if inv.outstanding_amount > 0 and inv.due_date < today]
    return {
        "invoiced": q2(sum((inv.total_amount for inv in invoices), ZERO)),
        "paid": q2(sum((inv.paid_amount for inv in invoices), ZERO)),
        "outstanding": q2(sum((inv.outstanding_amount for inv in invoices), ZERO)),
        "overdue": q2(sum((inv.outstanding_amount for inv in overdue), ZERO)),
        "overdue_count": len(overdue),
        "invoice_count": len(invoices),
    }


def client_vouchers(
    db: Session,
    client_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    voucher_type: str | None = None,
) -> list[AccountingVoucher]:
    query = db.query(AccountingVoucher).filter(AccountingVoucher.client_id == client_id)
    if from_date:
        query = query.filter(AccountingVoucher.voucher_date >= from_date)
    if to_date:
        query = query.filter(AccountingVoucher.voucher_date <= to_date)
    if voucher_type:
        query = query.filter(AccountingVoucher.voucher_type == voucher_type)
    return query.order_by(AccountingVoucher.voucher_date, AccountingVoucher.id).all()


def voucher_duplicate_count(db: Session, client_id: int, period: str) -> int:
    start, end = month_bounds(period)
    rows = (
        db.query(AccountingVoucher.number, func.count(AccountingVoucher.id))
        .filter(
            AccountingVoucher.client_id == client_id,
            AccountingVoucher.voucher_date >= start,
            AccountingVoucher.voucher_date <= end,
        )
        .group_by(AccountingVoucher.number)
        .having(func.count(AccountingVoucher.id) > 1)
        .all()
    )
    return len(rows)


def financial_year_period(today: date | None = None) -> str:
    return financial_year_for(today or date.today())


def days_until(value: date | None) -> int | None:
    if value is None:
        return None
    return (value - date.today()).days


def upcoming_deadlines(tasks: list[AccountingTask], days: int = 14) -> list[dict]:
    limit = date.today() + timedelta(days=days)
    rows = [
        task
        for task in tasks
        if task.due_date and task.due_date <= limit and task.status not in ("approved", "delivered", "cancelled")
    ]
    rows.sort(key=lambda task: (task.due_date or limit, task.priority != "urgent"))
    return [task_to_dict(task) for task in rows[:20]]


def validate_gstin(value: str | None) -> str | None:
    if not value:
        return None
    upper = value.strip().upper()
    if not GSTIN_RE.match(upper):
        raise HTTPException(status_code=422, detail="GSTIN does not match the 15-character Indian format.")
    return upper
