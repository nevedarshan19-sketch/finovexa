from __future__ import annotations

import base64
import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AccountingBankImport,
    AccountingBankTransaction,
    AccountingBusinessTransaction,
    AccountingClient,
    AccountingDocument,
    AccountingEntryDraft,
    Invoice,
    Payment,
    PaymentConnection,
    PaymentReconciliationEvent,
    PaymentSyncRun,
    PaymentTransaction,
    ReconciliationRecord,
    User,
    utcnow,
)
from .accounting import (
    _coerce_date,
    _coerce_decimal,
    _extract_pdf_text,
    decode_data_url,
    parse_tabular,
)
from .accounting_drafts import generate_drafts
from .accounting_integration import sync_business_transactions
from .audit import log_audit
from .file_store import save_bytes
from .integrations import paypal as paypal_module
from .payments import record_payment, refresh_invoice_status

ZERO = Decimal("0.00")
MAX_SYNC_DAYS = 366
PAYPAL_MAX_WINDOW_DAYS = 31
PAYPAL_MAX_PAGES = 40
PAYPAL_PAGE_SIZE = 500

PROVIDER_LABELS = {
    "paypal": "PayPal",
    "google_pay": "Google Pay (merchant records)",
    "bank_statement": "Bank statement import",
}

CAPABILITIES = [
    {
        "provider": "paypal",
        "label": "PayPal",
        "history_access": "official",
        "history_api": "GET /v1/reporting/transactions (Transaction Search)",
        "requirements": [
            "Backend PayPal credentials for the selected environment",
            "The reporting transaction-search scope granted to the application",
            "An eligible merchant account",
        ],
        "limitations": [
            "Only the merchant that owns the backend credentials is searched.",
            "Access to another merchant's history requires PayPal partner-network approval.",
            "Each search window is limited to 31 days and paginated results are capped.",
            "PayPal account pages are never scraped.",
        ],
        "costs": "PayPal API usage is governed by the existing PayPal agreement; no extra key is requested here.",
    },
    {
        "provider": "google_pay",
        "label": "Google Pay",
        "history_access": "unsupported",
        "history_api": None,
        "requirements": [
            "An official Google Pay merchant integration with its own merchant ID",
        ],
        "limitations": [
            "Google Pay does not provide a public API that lists or downloads every consumer Google Pay transaction.",
            "FINOVEXA does not request Google passwords, UPI PINs, OTPs or other payment credentials.",
            "The Google Pay app and notifications are never scraped.",
            "This deployment can only track merchant transaction IDs that you enter, clearly marked as unverified.",
        ],
        "costs": "No Google API is called, so there is no API cost.",
    },
    {
        "provider": "bank_statement",
        "label": "Bank statement fallback",
        "history_access": "import",
        "history_api": None,
        "requirements": [
            "A CSV or Excel statement, or a PDF that contains machine-readable text",
            "Accountant review of every uncertain row",
        ],
        "limitations": [
            "Images and scanned PDFs are not OCR-processed; rows must be entered or exported as CSV.",
            "Parsed rows are unverified until an accountant reviews them.",
            "Original files are stored encrypted at rest.",
        ],
        "costs": "No third-party API cost.",
    },
]


# ------------------------------------------------------------------ helpers


def _q2(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(value).quantize(Decimal("0.01"))


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.replace("_", " ").title())


def resolve_client_owner(db: Session, client: AccountingClient) -> User:
    """The business owner whose invoice ledger a connected client shares."""
    profile = client.business_profile
    if client.business_profile_id is None or profile is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Link this engagement to a business profile before connecting a payment "
                "provider. A payment connection must belong to the business that owns it."
            ),
        )
    owner = db.get(User, profile.user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status_code=409, detail="The linked business owner is unavailable.")
    return owner


def get_connection_or_404(
    db: Session, connection_id: int, *, user_id: int, client_id: int | None
) -> PaymentConnection:
    connection = db.get(PaymentConnection, connection_id)
    if connection is None or connection.user_id != user_id:
        raise HTTPException(status_code=404, detail="Payment connection not found.")
    if client_id is not None and connection.client_id != client_id:
        raise HTTPException(status_code=404, detail="Payment connection not found for this client.")
    return connection


# ------------------------------------------------------------------ serializers


def connection_to_dict(db: Session, connection: PaymentConnection) -> dict:
    base = db.query(PaymentTransaction).filter(
        PaymentTransaction.connection_id == connection.id,
        PaymentTransaction.duplicate_of_id.is_(None),
    )
    count = base.count()
    incoming = (
        db.query(func.coalesce(func.sum(PaymentTransaction.amount), 0))
        .filter(
            PaymentTransaction.connection_id == connection.id,
            PaymentTransaction.duplicate_of_id.is_(None),
            PaymentTransaction.direction == "incoming",
        )
        .scalar()
    )
    outgoing = (
        db.query(func.coalesce(func.sum(PaymentTransaction.amount), 0))
        .filter(
            PaymentTransaction.connection_id == connection.id,
            PaymentTransaction.duplicate_of_id.is_(None),
            PaymentTransaction.direction == "outgoing",
        )
        .scalar()
    )
    matched = base.filter(PaymentTransaction.reconciliation_status == "matched").count()
    unmatched = base.filter(
        PaymentTransaction.reconciliation_status.in_(("unverified", "suggested"))
    ).count()
    duplicates = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.connection_id == connection.id,
            PaymentTransaction.duplicate_of_id.isnot(None),
        )
        .count()
    )
    return {
        "id": connection.id,
        "provider": connection.provider,
        "provider_label": _provider_label(connection.provider),
        "label": connection.label,
        "environment": connection.environment,
        "mode": connection.mode,
        "status": connection.status,
        "merchant_id": connection.merchant_id,
        "account_hint": connection.account_hint,
        "outlet_label": connection.outlet_label,
        "permissions": connection.permissions or [],
        "consent_at": _iso(connection.consent_at),
        "connected_at": _iso(connection.connected_at),
        "disconnected_at": _iso(connection.disconnected_at),
        "last_sync_at": _iso(connection.last_sync_at),
        "last_success_at": _iso(connection.last_success_at),
        "last_error": connection.last_error,
        "last_error_at": _iso(connection.last_error_at),
        "note": connection.note,
        "counts": {
            "transactions": count,
            "matched": matched,
            "unmatched": unmatched,
            "duplicates": duplicates,
            "incoming_total": str(_q2(incoming)),
            "outgoing_total": str(_q2(outgoing)),
        },
    }


def sync_run_to_dict(run: PaymentSyncRun) -> dict:
    return {
        "id": run.id,
        "connection_id": run.connection_id,
        "provider": run.provider,
        "trigger": run.trigger,
        "status": run.status,
        "range_start": _iso(run.range_start),
        "range_end": _iso(run.range_end),
        "fetched": run.fetched,
        "created": run.created_count,
        "duplicates": run.duplicate_count,
        "skipped": run.skipped_count,
        "error": run.error,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "actor": run.actor,
        "detail": run.detail or {},
    }


def event_to_dict(event: PaymentReconciliationEvent) -> dict:
    return {
        "id": event.id,
        "transaction_id": event.transaction_id,
        "action": event.action,
        "actor": event.actor,
        "actor_user_id": event.actor_user_id,
        "invoice_id": event.invoice_id,
        "payment_id": event.payment_id,
        "note": event.note,
        "detail": event.detail or {},
        "created_at": _iso(event.created_at),
    }


def transaction_to_dict(txn: PaymentTransaction) -> dict:
    invoice = txn.invoice
    return {
        "id": txn.id,
        "connection_id": txn.connection_id,
        "client_id": txn.client_id,
        "provider": txn.provider,
        "provider_label": _provider_label(txn.provider),
        "environment": txn.environment,
        "external_id": txn.external_id,
        "parent_external_id": txn.parent_external_id,
        "direction": txn.direction,
        "txn_type": txn.txn_type,
        "amount": str(_q2(txn.amount)),
        "fee_amount": str(_q2(txn.fee_amount)),
        "net_amount": str(_q2(txn.net_amount)),
        "currency": txn.currency,
        "status": txn.status,
        "occurred_on": _iso(txn.occurred_on),
        "occurred_at": _iso(txn.occurred_at),
        "description": txn.description,
        "counterparty": txn.counterparty,
        "reference": txn.reference,
        "provider_reference": txn.provider_reference,
        "source": txn.source,
        "import_id": txn.import_id,
        "bank_transaction_id": txn.bank_transaction_id,
        "dedupe_hash": txn.dedupe_hash,
        "duplicate_of_id": txn.duplicate_of_id,
        "reconciliation_status": txn.reconciliation_status,
        "matched_invoice_id": txn.matched_invoice_id,
        "matched_invoice_number": invoice.number if invoice else None,
        "matched_payment_id": txn.matched_payment_id,
        "match_score": txn.match_score,
        "match_reason": txn.match_reason,
        "reviewed_by_user_id": txn.reviewed_by_user_id,
        "reviewed_by": txn.reviewed_by.full_name if txn.reviewed_by else None,
        "reviewed_at": _iso(txn.reviewed_at),
        "note": txn.note,
        "outlet_label": txn.outlet_label,
        "accounting_draft_id": txn.accounting_draft_id,
        "accounting_voucher_id": txn.accounting_voucher_id,
        "created_at": _iso(txn.created_at),
    }


# ------------------------------------------------------------------ connections


def _find_connection(
    db: Session, *, user_id: int, client_id: int | None, provider: str, environment: str
) -> PaymentConnection | None:
    query = db.query(PaymentConnection).filter(
        PaymentConnection.user_id == user_id,
        PaymentConnection.provider == provider,
        PaymentConnection.environment == environment,
    )
    if client_id is None:
        query = query.filter(PaymentConnection.client_id.is_(None))
    else:
        query = query.filter(PaymentConnection.client_id == client_id)
    return query.one_or_none()


def _assert_single_provider_account(
    db: Session, *, user_id: int, client_id: int | None, provider: str, environment: str
) -> None:
    query = db.query(PaymentConnection).filter(
        PaymentConnection.provider == provider,
        PaymentConnection.environment == environment,
    ).execution_options(tenancy_bypass=True)
    if provider != "paypal":
        query = query.filter(PaymentConnection.user_id == user_id)
        if client_id is None:
            query = query.filter(PaymentConnection.client_id.isnot(None))
        else:
            query = query.filter(
                or_(
                    PaymentConnection.client_id.is_(None),
                    PaymentConnection.client_id != client_id,
                )
            )
    # PayPal history is read with the single credential set held by this deployment.
    # It can power exactly one business/account, so the check is deployment-wide: a
    # second business must never inherit the first merchant's credentials.
    other = query.first()
    if other is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "One backend credential set can only be linked to one business/account per "
                "environment. The same provider is already connected for another business. "
                "Separate merchant credentials would need their own deployment configuration."
            ),
        )


def connect_provider(
    db: Session,
    *,
    owner: User,
    actor: User,
    provider: str,
    client: AccountingClient | None,
    environment: str | None,
    label: str | None,
    outlet_label: str | None,
    merchant_id: str | None,
    consent: bool,
    note: str | None,
) -> PaymentConnection:
    if not consent:
        raise HTTPException(
            status_code=422,
            detail="Explicit consent is required before a provider connection is created.",
        )
    if provider not in ("paypal", "google_pay", "bank_statement"):
        raise HTTPException(status_code=422, detail="Choose PayPal, Google Pay or bank statements.")
    client_id = client.id if client else None
    if provider == "paypal":
        environment = environment if environment in ("sandbox", "live") else settings.paypal_environment
        if not settings.paypal_environment_configured(environment):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"PayPal {environment} credentials are not present in the backend "
                    "environment. Add them as server secrets, then reconnect. Credentials "
                    "are never entered or stored in the browser."
                ),
            )
        paypal = paypal_module.PayPalClient()
        paypal.configure_runtime(environment, True)
        status = "connected"
        last_error = None
        permissions = ["transaction_search:read"]
        try:
            probe_end = datetime.now(timezone.utc)
            paypal.search_transactions(
                start_date=probe_end - timedelta(days=1),
                end_date=probe_end,
                page_size=1,
            )
        except paypal_module.PayPalError as exc:
            status = "error"
            last_error = str(exc)
            permissions = []
        except Exception as exc:  # noqa: BLE001 - surface a safe connection error
            status = "error"
            last_error = f"Could not verify PayPal access: {type(exc).__name__}."
            permissions = []
        environment_label = environment
        mode = environment
        default_label = f"PayPal {environment.title()}"
        account_hint = paypal.client_id_hint
    elif provider == "google_pay":
        if not (merchant_id or "").strip():
            raise HTTPException(
                status_code=422,
                detail="A Google Pay merchant ID is required. No Google credentials are requested.",
            )
        environment = "manual"
        mode = "manual"
        status = "connected"
        last_error = None
        permissions = []
        environment_label = "manual"
        default_label = "Google Pay merchant records"
        account_hint = f"merchant {merchant_id[:6]}…" if len(merchant_id or "") > 6 else "merchant"
    else:
        environment = "manual"
        mode = "manual"
        status = "connected"
        last_error = None
        permissions = []
        environment_label = "manual"
        default_label = "Bank statements"
        account_hint = "statement uploads"

    existing = _find_connection(
        db,
        user_id=owner.id,
        client_id=client_id,
        provider=provider,
        environment=environment_label,
    )
    if existing is None:
        _assert_single_provider_account(
            db,
            user_id=owner.id,
            client_id=client_id,
            provider=provider,
            environment=environment_label,
        )
        connection = PaymentConnection(
            user_id=owner.id,
            client_id=client_id,
            created_by_user_id=actor.id,
            provider=provider,
            label=(label or default_label)[:120],
            environment=environment_label,
            mode=mode,
            status=status,
            merchant_id=(merchant_id or None),
            account_hint=account_hint,
            outlet_label=(outlet_label or None),
            permissions=permissions,
            consent_at=utcnow(),
            connected_at=utcnow() if status == "connected" else None,
            last_error=last_error,
            last_error_at=utcnow() if last_error else None,
            note=note,
        )
        db.add(connection)
    else:
        connection = existing
        connection.label = (label or connection.label)[:120]
        connection.outlet_label = outlet_label or connection.outlet_label
        connection.merchant_id = merchant_id or connection.merchant_id
        connection.permissions = permissions
        connection.consent_at = utcnow()
        connection.status = status
        connection.last_error = last_error
        connection.last_error_at = utcnow() if last_error else None
        connection.disconnected_at = None
        if status == "connected":
            connection.connected_at = connection.connected_at or utcnow()
        if note:
            connection.note = note
    db.flush()
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.connection_saved",
        entity_type="payment_connection",
        entity_id=connection.id,
        detail={
            "provider": provider,
            "environment": environment_label,
            "client_id": client_id,
            "status": status,
            "consent": True,
        },
    )
    return connection


def disconnect_connection(
    db: Session, connection: PaymentConnection, *, actor: User, note: str | None = None
) -> PaymentConnection:
    connection.status = "disconnected"
    connection.disconnected_at = utcnow()
    connection.last_error = "Connection revoked by the owner or accountant."
    connection.last_error_at = utcnow()
    connection.note = note or connection.note
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.connection_revoked",
        entity_type="payment_connection",
        entity_id=connection.id,
        detail={"provider": connection.provider, "client_id": connection.client_id},
    )
    db.flush()
    return connection


def list_connections(
    db: Session, *, user_id: int, client_id: int | None
) -> list[PaymentConnection]:
    query = db.query(PaymentConnection).filter(PaymentConnection.user_id == user_id)
    if client_id is None:
        # Owner view: everything owned by the business, including client-linked imports.
        pass
    else:
        query = query.filter(PaymentConnection.client_id == client_id)
    return query.order_by(PaymentConnection.created_at.desc()).all()


# ------------------------------------------------------------------ PayPal normalisation

_PAYPAL_EVENT_TYPES = {
    "T0000": "payment",
    "T0001": "payment",
    "T0107": "fee",
    "T1106": "reversal",
    "T1107": "refund",
    "T1201": "chargeback",
    "T2000": "transfer",
}

_PAYPAL_STATUS = {
    "S": "completed",
    "P": "pending",
    "D": "failed",
    "V": "reversed",
    "COMPLETED": "completed",
    "PENDING": "pending",
    "DENIED": "failed",
    "FAILED": "failed",
    "REFUNDED": "refunded",
    "REVERSED": "reversed",
}


def _parse_paypal_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def normalise_paypal_transaction(item: dict[str, Any]) -> dict[str, Any] | None:
    info = item.get("transaction_info") or {}
    external_id = str(info.get("transaction_id") or "").strip()
    if not external_id:
        return None
    amount_data = info.get("transaction_amount") or {}
    amount = _coerce_decimal(amount_data.get("value"))
    if amount is None:
        return None
    fee = _coerce_decimal((info.get("fee_amount") or {}).get("value")) or ZERO
    currency = str(amount_data.get("currency_code") or "INR")[:3]
    event_code = str(info.get("transaction_event_code") or "").strip().upper()
    txn_type = _PAYPAL_EVENT_TYPES.get(event_code, "other")
    if txn_type == "refund" and amount > 0:
        amount = -amount
    direction = "outgoing" if amount < 0 else "incoming"
    status_code = str(info.get("transaction_status") or "").strip().upper()
    status = _PAYPAL_STATUS.get(status_code, "unknown")
    payer = item.get("payer_info") or {}
    payer_name = payer.get("payer_name") or {}
    counterparty = (
        payer_name.get("alternate_full_name")
        or " ".join(
            part for part in (payer_name.get("given_name"), payer_name.get("surname")) if part
        ).strip()
        or payer.get("email_address")
        or None
    )
    occurred_at = _parse_paypal_datetime(info.get("transaction_initiation_date"))
    reference = (
        info.get("invoice_id")
        or info.get("custom_field")
        or info.get("bank_reference_id")
        or info.get("payment_tracking_id")
    )
    description = (
        info.get("transaction_subject")
        or info.get("transaction_note")
        or f"{_provider_label('paypal')} {event_code or 'transaction'}"
    )
    return {
        "external_id": external_id[:160],
        "parent_external_id": (info.get("paypal_reference_id") or None),
        "direction": direction,
        "txn_type": txn_type,
        "amount": _q2(abs(amount)),
        "fee_amount": _q2(abs(fee)),
        "net_amount": _q2(abs(amount) - abs(fee)),
        "currency": currency,
        "status": status,
        "occurred_on": occurred_at.date() if occurred_at else None,
        "occurred_at": occurred_at,
        "description": (str(description) or "")[:1000] or None,
        "counterparty": (str(counterparty) if counterparty else None),
        "reference": (str(reference)[:160] if reference else None),
        "provider_reference": external_id[:200],
        "raw": item,
    }


# ------------------------------------------------------------------ matching


def _name_tokens(value: str | None) -> set[str]:
    return {token for token in re.split(r"[^A-Za-z0-9]+", (value or "").upper()) if len(token) > 2}


def match_candidates(
    db: Session, txn: PaymentTransaction, *, limit: int = 10
) -> list[dict]:
    if (
        txn.direction != "incoming"
        or txn.txn_type != "payment"
        or txn.amount <= 0
        or txn.status != "completed"
    ):
        return []
    existing = (
        db.query(Payment)
        .filter(
            Payment.user_id == txn.user_id,
            Payment.provider_ref == txn.external_id,
        )
        .one_or_none()
    )
    candidates: list[dict] = []
    if existing is not None and existing.invoice_id is not None:
        invoice = db.get(Invoice, existing.invoice_id)
        if invoice is not None:
            candidates.append(
                {
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.number,
                    "customer_name": invoice.customer_name
                    or (invoice.customer.name if invoice.customer else None),
                    "outstanding_amount": str(_q2(invoice.outstanding_amount)),
                    "issue_date": _iso(invoice.issue_date),
                    "score": 100,
                    "reason": "This provider transaction is already recorded against the invoice.",
                    "existing_payment_id": existing.id,
                }
            )
    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.user_id == txn.user_id,
            Invoice.status.notin_(("draft", "void", "paid")),
        )
        .order_by(Invoice.issue_date.desc(), Invoice.id.desc())
        .limit(200)
        .all()
    )
    text = f"{txn.description or ''} {txn.reference or ''} {txn.counterparty or ''}".upper()
    text_tokens = _name_tokens(text)
    seen_invoices = {row["invoice_id"] for row in candidates}
    for invoice in invoices:
        if invoice.id in seen_invoices:
            continue
        outstanding = _q2(invoice.outstanding_amount)
        if outstanding <= 0:
            continue
        score = 0
        reasons: list[str] = []
        if abs(txn.amount - outstanding) <= Decimal("0.01"):
            score += 60
            reasons.append(f"Amount matches the outstanding balance {outstanding}.")
        elif txn.amount < outstanding:
            score += 35
            reasons.append(
                f"Partial payment against outstanding balance {outstanding}."
            )
        else:
            continue
        if invoice.number and invoice.number.upper() in text:
            score += 20
            reasons.append(f"Invoice number {invoice.number} appears in the reference.")
        customer_tokens = _name_tokens(
            invoice.customer_name
            or (invoice.customer.name if invoice.customer is not None else None)
        )
        if customer_tokens and customer_tokens & text_tokens:
            score += 10
            reasons.append("Customer name appears in the description.")
        if txn.occurred_on is not None:
            delta = abs((txn.occurred_on - invoice.issue_date).days)
            if delta <= 7:
                score += 10
                reasons.append("Transaction date is within a week of the invoice date.")
            elif delta <= 30:
                score += 5
        if score < 35:
            continue
        candidates.append(
            {
                "invoice_id": invoice.id,
                "invoice_number": invoice.number,
                "customer_name": invoice.customer_name
                or (invoice.customer.name if invoice.customer else None),
                "outstanding_amount": str(outstanding),
                "issue_date": _iso(invoice.issue_date),
                "score": min(score, 99),
                "reason": " ".join(reasons),
                "existing_payment_id": None,
            }
        )
    candidates.sort(key=lambda row: (-row["score"], row["invoice_id"]))
    return candidates[:limit]


def suggest_match(db: Session, txn: PaymentTransaction) -> None:
    if txn.reconciliation_status in ("matched", "rejected", "not_applicable"):
        return
    candidates = match_candidates(db, txn, limit=1)
    if not candidates:
        txn.reconciliation_status = "unverified"
        txn.matched_invoice_id = None
        txn.match_score = None
        txn.match_reason = "No invoice candidate matched this transaction."
        return
    best = candidates[0]
    if best["score"] >= 60:
        txn.reconciliation_status = "suggested"
        txn.matched_invoice_id = best["invoice_id"]
        txn.match_score = best["score"]
        txn.match_reason = best["reason"]
    else:
        txn.reconciliation_status = "unverified"
        txn.matched_invoice_id = None
        txn.match_score = best["score"]
        txn.match_reason = f"Possible partial match with {best['invoice_number']}; review manually."


# ------------------------------------------------------------------ PayPal sync


def _record_event(
    db: Session,
    txn: PaymentTransaction,
    *,
    action: str,
    actor: User,
    note: str | None,
    invoice_id: int | None = None,
    payment_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        PaymentReconciliationEvent(
            transaction_id=txn.id,
            action=action,
            actor=actor.email,
            actor_user_id=actor.id,
            invoice_id=invoice_id,
            payment_id=payment_id,
            note=note,
            detail=detail or {},
        )
    )


def sync_paypal(
    db: Session,
    connection: PaymentConnection,
    *,
    actor: User,
    start_date: date,
    end_date: date,
    trigger: str = "manual",
) -> PaymentSyncRun:
    if connection.provider != "paypal":
        raise HTTPException(status_code=422, detail="This connection is not a PayPal connection.")
    if connection.status == "disconnected":
        raise HTTPException(
            status_code=409,
            detail="This connection was revoked. Reconnect with explicit consent before syncing.",
        )
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="The end date must be on or after the start date.")
    span = (end_date - start_date).days + 1
    if span > MAX_SYNC_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Sync at most {MAX_SYNC_DAYS} days at a time.",
        )
    run = PaymentSyncRun(
        connection_id=connection.id,
        provider=connection.provider,
        trigger=trigger,
        status="running",
        range_start=datetime.combine(start_date, time.min),
        range_end=datetime.combine(end_date, time.max),
        actor=actor.email,
        started_at=utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    money = paypal_module.PayPalClient()
    money.configure_runtime(connection.environment, True)
    if not money.configured:
        run.status = "failed"
        run.error = (
            "PayPal credentials for this connection's environment are not configured on the server."
        )
        run.finished_at = utcnow()
        connection.status = "error"
        connection.last_error = run.error
        connection.last_error_at = utcnow()
        connection.last_sync_at = utcnow()
        db.commit()
        raise HTTPException(status_code=409, detail=run.error)

    fetched = created = duplicates = skipped = 0
    warnings: list[str] = []
    new_rows: list[PaymentTransaction] = []
    existing_ids = {
        value
        for (value,) in db.query(PaymentTransaction.external_id).filter(
            PaymentTransaction.connection_id == connection.id
        )
    }
    existing_hashes = {
        value
        for (value,) in db.query(PaymentTransaction.dedupe_hash).filter(
            PaymentTransaction.connection_id == connection.id,
            PaymentTransaction.dedupe_hash.isnot(None),
        )
    }
    seen: set[str] = set()

    window_start = start_date
    try:
        while window_start <= end_date:
            window_end = min(end_date, window_start + timedelta(days=PAYPAL_MAX_WINDOW_DAYS - 1))
            page = 1
            while page <= PAYPAL_MAX_PAGES:
                payload = money.search_transactions(
                    start_date=datetime.combine(window_start, time.min).replace(
                        tzinfo=timezone.utc
                    ),
                    end_date=datetime.combine(window_end, time.max).replace(tzinfo=timezone.utc),
                    page=page,
                    page_size=PAYPAL_PAGE_SIZE,
                )
                details = payload.get("transaction_details") or []
                fetched += len(details)
                for item in details:
                    parsed = normalise_paypal_transaction(item)
                    if parsed is None:
                        skipped += 1
                        continue
                    external = parsed["external_id"]
                    dedupe = _sha(
                        f"{connection.provider}|{connection.environment}|{external}"
                    )
                    if external in seen or external in existing_ids or dedupe in existing_hashes:
                        duplicates += 1
                        continue
                    seen.add(external)
                    existing_ids.add(external)
                    existing_hashes.add(dedupe)
                    txn = PaymentTransaction(
                        connection_id=connection.id,
                        user_id=connection.user_id,
                        client_id=connection.client_id,
                        provider=connection.provider,
                        environment=connection.environment,
                        external_id=external,
                        parent_external_id=parsed["parent_external_id"],
                        direction=parsed["direction"],
                        txn_type=parsed["txn_type"],
                        amount=parsed["amount"],
                        fee_amount=parsed["fee_amount"],
                        net_amount=parsed["net_amount"],
                        currency=parsed["currency"],
                        status=parsed["status"],
                        occurred_on=parsed["occurred_on"],
                        occurred_at=parsed["occurred_at"],
                        description=parsed["description"],
                        counterparty=parsed["counterparty"],
                        reference=parsed["reference"],
                        provider_reference=parsed["provider_reference"],
                        source="api",
                        raw=parsed["raw"],
                        dedupe_hash=dedupe,
                        reconciliation_status="unverified",
                        outlet_label=connection.outlet_label,
                    )
                    db.add(txn)
                    new_rows.append(txn)
                    created += 1
                total_pages = int(payload.get("total_pages") or 1)
                if page >= total_pages or not details:
                    break
                page += 1
            else:
                warnings.append(
                    f"Stopped after {PAYPAL_MAX_PAGES} pages for "
                    f"{window_start.isoformat()} to {window_end.isoformat()}; "
                    "the next sync will continue with duplicate protection."
                )
            window_start = window_end + timedelta(days=1)
        db.flush()
        for txn in new_rows:
            suggest_match(db, txn)
        now = utcnow()
        run.fetched = fetched
        run.created_count = created
        run.duplicate_count = duplicates
        run.skipped_count = skipped
        run.status = "success" if not warnings else "partial"
        run.finished_at = now
        run.detail = {
            "warnings": warnings,
            "windows": span,
            "duplicate_prevention": "unique provider transaction ID per connection",
        }
        connection.status = "connected"
        connection.last_sync_at = now
        connection.last_success_at = now
        connection.last_error = None
        connection.last_error_at = None
        log_audit(
            db,
            user_id=actor.id,
            actor=actor.email,
            action="payment_connect.paypal_sync_completed",
            entity_type="payment_connection",
            entity_id=connection.id,
            detail={
                "client_id": connection.client_id,
                "fetched": fetched,
                "created": created,
                "duplicates": duplicates,
                "skipped": skipped,
                "range_start": start_date.isoformat(),
                "range_end": end_date.isoformat(),
            },
        )
        db.commit()
        db.refresh(run)
        return run
    except paypal_module.PayPalError as exc:
        db.rollback()
        stored = db.get(PaymentSyncRun, run.id)
        if stored is not None:
            stored.status = "failed"
            stored.fetched = fetched
            stored.created_count = created
            stored.duplicate_count = duplicates
            stored.skipped_count = skipped
            stored.error = str(exc)
            stored.finished_at = utcnow()
            stored.detail = {"warnings": warnings}
        connection = db.get(PaymentConnection, connection.id)
        if connection is not None:
            connection.status = "error"
            connection.last_sync_at = utcnow()
            connection.last_error = str(exc)
            connection.last_error_at = utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - keep the run auditable
        db.rollback()
        stored = db.get(PaymentSyncRun, run.id)
        if stored is not None:
            stored.status = "failed"
            stored.error = f"{type(exc).__name__}: sync stopped before completion."
            stored.finished_at = utcnow()
        connection = db.get(PaymentConnection, connection.id)
        if connection is not None:
            connection.status = "error"
            connection.last_sync_at = utcnow()
            connection.last_error = "Sync stopped unexpectedly. Review the server log."
            connection.last_error_at = utcnow()
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="The PayPal sync stopped unexpectedly. No duplicate transactions were created.",
        ) from exc


# ------------------------------------------------------------------ reconciliation


def _link_accounting_draft(
    db: Session, txn: PaymentTransaction, payment: Payment, *, actor: User
) -> str | None:
    if txn.client_id is None:
        return None
    client = db.get(AccountingClient, txn.client_id)
    if client is None or client.business_profile_id is None:
        return None
    if client.integration_status != "linked":
        return None
    try:
        sync_business_transactions(db, client, actor)
        business_txn = (
            db.query(AccountingBusinessTransaction)
            .filter(
                AccountingBusinessTransaction.client_id == client.id,
                AccountingBusinessTransaction.source_type == "payment",
                AccountingBusinessTransaction.source_id == payment.id,
            )
            .one_or_none()
        )
        if business_txn is None or business_txn.status != "pending":
            return None
        generate_drafts(db, client, actor, transaction_ids=[business_txn.id], limit=1)
        draft = (
            db.query(AccountingEntryDraft)
            .filter(AccountingEntryDraft.transaction_id == business_txn.id)
            .one_or_none()
        )
        if draft is None:
            return None
        txn.accounting_draft_id = draft.id
        return draft.number
    except HTTPException as exc:
        txn.note = (
            (txn.note + " " if txn.note else "")
            + f"Accounting draft was not created automatically: {exc.detail}"
        )
        return None
    except Exception:  # noqa: BLE001 - approval must not fail because drafting failed
        txn.note = (
            (txn.note + " " if txn.note else "")
            + "Accounting draft was not created automatically. Use the accounting workspace."
        )
        return None


def _approve_refund(
    db: Session,
    txn: PaymentTransaction,
    *,
    actor: User,
    owner: User,
    note: str | None,
) -> dict:
    original: Payment | None = None
    if txn.parent_external_id:
        original = (
            db.query(Payment)
            .filter(
                Payment.user_id == owner.id,
                Payment.provider_ref == txn.parent_external_id,
            )
            .one_or_none()
        )
        if original is None:
            parent_txn = (
                db.query(PaymentTransaction)
                .filter(
                    PaymentTransaction.connection_id == txn.connection_id,
                    PaymentTransaction.external_id == txn.parent_external_id,
                )
                .one_or_none()
            )
            if parent_txn is not None and parent_txn.matched_payment_id:
                original = db.get(Payment, parent_txn.matched_payment_id)
    if original is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "The original payment for this refund is not recorded. Approve the original "
                "payment first, or reject the refund and reconcile it manually."
            ),
        )
    idempotency_key = f"payconnect-refund-{txn.provider}-{txn.external_id}"
    refund = db.query(Payment).filter(Payment.idempotency_key == idempotency_key).one_or_none()
    amount = _q2(abs(txn.amount))
    if refund is None:
        refund = Payment(
            user_id=owner.id,
            created_by_user_id=actor.id,
            invoice_id=original.invoice_id,
            refund_of_payment_id=original.id,
            amount=-amount,
            currency=txn.currency,
            method=txn.provider,
            status="confirmed",
            provider=f"{txn.provider}_refund",
            provider_ref=txn.external_id,
            idempotency_key=idempotency_key,
            reconciliation_status="matched" if original.invoice_id else "unmatched",
            reconciled_at=utcnow() if original.invoice_id else None,
            note=note or txn.description,
            received_at=txn.occurred_at or utcnow(),
        )
        db.add(refund)
        db.flush()
        if original.invoice_id:
            invoice = db.get(Invoice, original.invoice_id)
            if invoice is not None:
                refresh_invoice_status(db, invoice)
        db.add(
            ReconciliationRecord(
                user_id=owner.id,
                payment_id=refund.id,
                invoice_id=original.invoice_id,
                status="refund",
                reason="Refund imported through Payment Connect.",
                amount_delta=-amount,
                actor=actor.email,
            )
        )
    txn.matched_payment_id = refund.id
    txn.matched_invoice_id = original.invoice_id
    txn.reconciliation_status = "matched"
    txn.match_score = 100
    txn.match_reason = f"Refund linked to original payment {original.provider_ref or original.id}."
    txn.reviewed_by_user_id = actor.id
    txn.reviewed_at = utcnow()
    txn.note = note or txn.note
    _record_event(
        db,
        txn,
        action="refund_approved",
        actor=actor,
        note=note,
        invoice_id=original.invoice_id,
        payment_id=refund.id,
        detail={"original_payment_id": original.id},
    )
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.refund_approved",
        entity_type="payment_transaction",
        entity_id=txn.id,
        detail={
            "provider": txn.provider,
            "original_payment_id": original.id,
            "refund_payment_id": refund.id,
            "amount": str(amount),
            "client_id": txn.client_id,
        },
    )
    return transaction_to_dict(txn)


def approve_transaction(
    db: Session,
    txn: PaymentTransaction,
    *,
    actor: User,
    invoice_id: int | None,
    note: str | None,
) -> dict:
    if txn.duplicate_of_id is not None:
        raise HTTPException(
            status_code=409,
            detail="This transaction is marked as a duplicate and cannot be approved.",
        )
    if txn.reconciliation_status == "matched" and txn.matched_payment_id is not None:
        return transaction_to_dict(txn)
    if txn.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Only completed provider transactions can be approved (current state: "
                f"{txn.status})."
            ),
        )
    owner = db.get(User, txn.user_id)
    if owner is None:
        raise HTTPException(status_code=409, detail="The owning business account is unavailable.")
    if txn.txn_type in ("refund", "chargeback", "reversal") or txn.amount < 0:
        return _approve_refund(db, txn, actor=actor, owner=owner, note=note)
    if txn.direction != "incoming":
        raise HTTPException(
            status_code=409,
            detail="Outgoing transactions cannot be matched to a customer invoice.",
        )
    if invoice_id is None:
        raise HTTPException(
            status_code=422,
            detail="Select the invoice that this payment settles before approving.",
        )
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.user_id != owner.id:
        raise HTTPException(
            status_code=422, detail="Select an invoice that belongs to this business."
        )
    if invoice.status in ("draft", "void"):
        raise HTTPException(
            status_code=409, detail="Issue the invoice before recording a payment against it."
        )
    if _q2(txn.amount) > _q2(invoice.outstanding_amount) + Decimal("0.01"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Payment {_q2(txn.amount)} is more than the invoice's outstanding balance "
                f"{_q2(invoice.outstanding_amount)}. Resolve the difference first."
            ),
        )
    existing_payment = (
        db.query(Payment)
        .filter(Payment.user_id == owner.id, Payment.provider_ref == txn.external_id)
        .one_or_none()
    )
    if existing_payment is not None:
        if existing_payment.invoice_id != invoice.id:
            raise HTTPException(
                status_code=409,
                detail="This provider transaction is already recorded against another invoice.",
            )
        payment = existing_payment
    else:
        payment = record_payment(
            db,
            user=owner,
            invoice=invoice,
            amount=_q2(txn.amount),
            method=txn.provider,
            status="confirmed",
            provider=txn.provider,
            provider_ref=txn.external_id,
            idempotency_key=f"payconnect-{txn.provider}-{txn.external_id}",
            note=note or f"Approved from {_provider_label(txn.provider)} transaction {txn.external_id}.",
            sender_name=txn.counterparty,
            received_at=txn.occurred_at or utcnow(),
            actor=actor.email,
            created_by_user_id=actor.id,
            currency=txn.currency,
            reconciliation_status="matched",
            commit=False,
        )
    txn.matched_invoice_id = invoice.id
    txn.matched_payment_id = payment.id
    txn.reconciliation_status = "matched"
    txn.match_score = 100
    txn.match_reason = note or "Approved by an accountant against the selected invoice."
    txn.reviewed_by_user_id = actor.id
    txn.reviewed_at = utcnow()
    txn.note = note or txn.note
    draft_number = _link_accounting_draft(db, txn, payment, actor=actor)
    _record_event(
        db,
        txn,
        action="approved",
        actor=actor,
        note=note,
        invoice_id=invoice.id,
        payment_id=payment.id,
        detail={"draft_number": draft_number},
    )
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.payment_approved",
        entity_type="payment_transaction",
        entity_id=txn.id,
        detail={
            "provider": txn.provider,
            "invoice_id": invoice.id,
            "payment_id": payment.id,
            "amount": str(_q2(txn.amount)),
            "client_id": txn.client_id,
            "accounting_draft_id": txn.accounting_draft_id,
        },
    )
    return transaction_to_dict(txn)


def reject_transaction(
    db: Session, txn: PaymentTransaction, *, actor: User, note: str | None
) -> dict:
    if txn.reconciliation_status == "matched" or txn.matched_payment_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This transaction is already approved and linked to a payment. Use the "
                "payment workflow to reverse it; rejecting here would hide a recorded payment."
            ),
        )
    txn.reconciliation_status = "rejected"
    txn.matched_invoice_id = None
    txn.match_reason = note or "Rejected during accountant review."
    txn.reviewed_by_user_id = actor.id
    txn.reviewed_at = utcnow()
    txn.note = note or txn.note
    _record_event(db, txn, action="rejected", actor=actor, note=note)
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.payment_rejected",
        entity_type="payment_transaction",
        entity_id=txn.id,
        detail={"provider": txn.provider, "client_id": txn.client_id},
    )
    return transaction_to_dict(txn)


def mark_not_applicable(
    db: Session, txn: PaymentTransaction, *, actor: User, note: str | None
) -> dict:
    if txn.matched_payment_id is not None:
        raise HTTPException(
            status_code=409,
            detail="A linked payment already exists. Reverse it through the payment workflow.",
        )
    txn.reconciliation_status = "not_applicable"
    txn.matched_invoice_id = None
    txn.match_reason = note or "Reviewed and marked not applicable to a customer invoice."
    txn.reviewed_by_user_id = actor.id
    txn.reviewed_at = utcnow()
    txn.note = note or txn.note
    _record_event(db, txn, action="not_applicable", actor=actor, note=note)
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.marked_not_applicable",
        entity_type="payment_transaction",
        entity_id=txn.id,
        detail={"provider": txn.provider, "client_id": txn.client_id},
    )
    return transaction_to_dict(txn)


def reset_transaction(
    db: Session, txn: PaymentTransaction, *, actor: User, note: str | None
) -> dict:
    if txn.matched_payment_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Reset is unavailable after a payment is linked. Use the payment workflow.",
        )
    txn.reconciliation_status = "unverified"
    txn.matched_invoice_id = None
    txn.match_score = None
    txn.match_reason = note or "Review reset by an accountant."
    txn.reviewed_by_user_id = None
    txn.reviewed_at = None
    txn.note = note or txn.note
    _record_event(db, txn, action="reset", actor=actor, note=note)
    suggest_match(db, txn)
    return transaction_to_dict(txn)


# ------------------------------------------------------------------ history


def list_transactions(
    db: Session,
    *,
    user_id: int,
    client_id: int | None,
    date_from: date | None = None,
    date_to: date | None = None,
    provider: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    reconciliation_status: str | None = None,
    outlet_label: str | None = None,
    search: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    include_duplicates: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    query = db.query(PaymentTransaction).filter(PaymentTransaction.user_id == user_id)
    if client_id is not None:
        query = query.filter(PaymentTransaction.client_id == client_id)
    if not include_duplicates:
        query = query.filter(PaymentTransaction.duplicate_of_id.is_(None))
    if date_from:
        query = query.filter(PaymentTransaction.occurred_on >= date_from)
    if date_to:
        query = query.filter(PaymentTransaction.occurred_on <= date_to)
    if provider:
        query = query.filter(PaymentTransaction.provider == provider)
    if direction:
        query = query.filter(PaymentTransaction.direction == direction)
    if status:
        query = query.filter(PaymentTransaction.status == status)
    if reconciliation_status:
        query = query.filter(
            PaymentTransaction.reconciliation_status == reconciliation_status
        )
    if outlet_label:
        query = query.filter(PaymentTransaction.outlet_label == outlet_label)
    if amount_min is not None:
        query = query.filter(PaymentTransaction.amount >= amount_min)
    if amount_max is not None:
        query = query.filter(PaymentTransaction.amount <= amount_max)
    if search:
        needle = f"%{search.strip()}%"
        query = query.filter(
            or_(
                PaymentTransaction.description.ilike(needle),
                PaymentTransaction.counterparty.ilike(needle),
                PaymentTransaction.reference.ilike(needle),
                PaymentTransaction.external_id.ilike(needle),
            )
        )
    total = query.count()
    rows = (
        query.order_by(PaymentTransaction.occurred_on.desc(), PaymentTransaction.id.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
        .all()
    )
    incoming = sum((row.amount for row in rows if row.direction == "incoming"), ZERO)
    outgoing = sum((row.amount for row in rows if row.direction == "outgoing"), ZERO)
    return {
        "items": [transaction_to_dict(row) for row in rows],
        "total": total,
        "limit": min(max(limit, 1), 500),
        "offset": max(offset, 0),
        "summary": {
            "incoming_total": str(_q2(incoming)),
            "outgoing_total": str(_q2(outgoing)),
            "rows": len(rows),
        },
    }


def build_overview(db: Session, *, user_id: int, client_id: int | None) -> dict:
    connections = list_connections(db, user_id=user_id, client_id=client_id)
    base = db.query(PaymentTransaction).filter(
        PaymentTransaction.user_id == user_id,
        PaymentTransaction.duplicate_of_id.is_(None),
    )
    if client_id is not None:
        base = base.filter(PaymentTransaction.client_id == client_id)
    total = base.count()
    reconciliation: dict[str, int] = {}
    for status, count in (
        db.query(PaymentTransaction.reconciliation_status, func.count())
        .filter(
            PaymentTransaction.user_id == user_id,
            PaymentTransaction.duplicate_of_id.is_(None),
            *(
                [PaymentTransaction.client_id == client_id]
                if client_id is not None
                else []
            ),
        )
        .group_by(PaymentTransaction.reconciliation_status)
        .all()
    ):
        reconciliation[status] = count
    by_provider = []
    for provider, count, incoming, outgoing in (
        db.query(
            PaymentTransaction.provider,
            func.count(),
            func.coalesce(
                func.sum(
                    case(
                        (PaymentTransaction.direction == "incoming", PaymentTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (PaymentTransaction.direction == "outgoing", PaymentTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(
            PaymentTransaction.user_id == user_id,
            PaymentTransaction.duplicate_of_id.is_(None),
            *(
                [PaymentTransaction.client_id == client_id]
                if client_id is not None
                else []
            ),
        )
        .group_by(PaymentTransaction.provider)
        .all()
    ):
        by_provider.append(
            {
                "provider": provider,
                "provider_label": _provider_label(provider),
                "count": count,
                "incoming_total": str(_q2(incoming)),
                "outgoing_total": str(_q2(outgoing)),
            }
        )
    duplicates = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.user_id == user_id,
            PaymentTransaction.duplicate_of_id.isnot(None),
            *(
                [PaymentTransaction.client_id == client_id]
                if client_id is not None
                else []
            ),
        )
        .count()
    )
    recent_runs = (
        db.query(PaymentSyncRun)
        .join(PaymentConnection, PaymentConnection.id == PaymentSyncRun.connection_id)
        .filter(PaymentConnection.user_id == user_id)
        .filter(
            *(
                [PaymentConnection.client_id == client_id]
                if client_id is not None
                else []
            )
        )
        .order_by(PaymentSyncRun.started_at.desc())
        .limit(8)
        .all()
    )
    incoming_total, outgoing_total = (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (PaymentTransaction.direction == "incoming", PaymentTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (PaymentTransaction.direction == "outgoing", PaymentTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(
            PaymentTransaction.user_id == user_id,
            PaymentTransaction.duplicate_of_id.is_(None),
            *(
                [PaymentTransaction.client_id == client_id]
                if client_id is not None
                else []
            ),
        )
        .one()
    )
    last_success = max(
        (connection.last_success_at for connection in connections if connection.last_success_at),
        default=None,
    )
    return {
        "capabilities": CAPABILITIES,
        "connections": [connection_to_dict(db, row) for row in connections],
        "summary": {
            "transactions": total,
            "duplicates": duplicates,
            "incoming_total": str(_q2(incoming_total)),
            "outgoing_total": str(_q2(outgoing_total)),
            "by_provider": by_provider,
        },
        "reconciliation": {
            "unverified": reconciliation.get("unverified", 0),
            "suggested": reconciliation.get("suggested", 0),
            "matched": reconciliation.get("matched", 0),
            "rejected": reconciliation.get("rejected", 0),
            "not_applicable": reconciliation.get("not_applicable", 0),
        },
        "recent_syncs": [sync_run_to_dict(row) for row in recent_runs],
        "last_successful_sync": _iso(last_success),
        "security_note": (
            "Provider credentials remain in backend environment variables. This view only "
            "contains connection state, masked hints and imported transactions."
        ),
    }


# ------------------------------------------------------------------ bank statements

_ENCRYPTED_SUFFIX = ".fernet"

_HEADER_ALIASES = {
    "date": (
        "date",
        "txn date",
        "transaction date",
        "value date",
        "posting date",
        "post date",
    ),
    "description": (
        "description",
        "narration",
        "particulars",
        "details",
        "transaction remarks",
        "remarks",
        "transaction description",
    ),
    "reference": (
        "reference",
        "ref",
        "ref no",
        "reference no",
        "cheque no",
        "cheque no.",
        "chq no",
        "chq/ref no",
        "chq/ref no.",
        "utr",
        "transaction reference",
    ),
    "debit": (
        "debit",
        "withdrawal",
        "withdrawal amt",
        "withdrawal amount",
        "withdrawal amount (dr)",
        "dr",
        "debit amount",
        "paid out",
    ),
    "credit": (
        "credit",
        "deposit",
        "deposit amt",
        "deposit amount",
        "deposit amount (cr)",
        "cr",
        "credit amount",
        "paid in",
    ),
    "amount": ("amount", "transaction amount", "value"),
    "direction": ("type", "dr/cr", "cr/dr", "transaction type", "debit/credit"),
    "balance": ("balance", "closing balance", "running balance"),
}


def _normalise_header(value: Any) -> str:
    text = re.sub(r"[\s_]+", " ", str(value or "").strip().lower())
    return text.strip(" :")


def _header_key(row: dict[str, Any], field: str) -> str | None:
    lowered = {_normalise_header(key): key for key in row if key is not None}
    for alias in _HEADER_ALIASES[field]:
        if alias in lowered:
            return lowered[alias]
    return None


def _row_hash(
    txn_date: date, description: str, reference: str | None, debit: Decimal, credit: Decimal
) -> str:
    return _sha(
        "|".join(
            (
                txn_date.isoformat(),
                description.strip().lower(),
                (reference or "").strip().lower(),
                f"{debit:.2f}",
                f"{credit:.2f}",
            )
        )
    )


def _direction_from_text(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in ("DR", "D", "DEBIT", "WITHDRAWAL", "PAID OUT"):
        return "debit"
    if text in ("CR", "C", "CREDIT", "DEPOSIT", "PAID IN"):
        return "credit"
    return None


def _statement_row(
    *,
    index: int,
    raw: dict[str, Any],
    txn_date: date | None,
    description: str,
    reference: str | None,
    debit: Decimal | None,
    credit: Decimal | None,
    direction_text: str | None = None,
    confidence: int = 100,
    issues: list[str] | None = None,
    source: str = "tabular",
) -> dict:
    issues = list(issues or [])
    debit_value = _q2(debit) if debit is not None else ZERO
    credit_value = _q2(credit) if credit is not None else ZERO
    direction = None
    if debit_value > 0 and credit_value == 0:
        direction = "debit"
    elif credit_value > 0 and debit_value == 0:
        direction = "credit"
    elif debit_value > 0 and credit_value > 0:
        direction = _direction_from_text(direction_text)
        if direction is None:
            issues.append("Both debit and credit are present; keep only one amount.")
            confidence = min(confidence, 40)
        else:
            if direction == "debit":
                credit_value = ZERO
            else:
                debit_value = ZERO
    elif direction_text:
        direction = _direction_from_text(direction_text)
        if direction is None:
            issues.append("The Dr/Cr indicator could not be read.")
    if txn_date is None:
        issues.append("The transaction date could not be read.")
        confidence = 0
    if not description:
        issues.append("The description is missing.")
        confidence = 0
    if debit_value == 0 and credit_value == 0:
        issues.append("No debit or credit amount could be read.")
        confidence = 0
    if direction is None and (debit_value or credit_value):
        issues.append("Debit/credit direction is unclear; choose the direction manually.")
        confidence = min(confidence, 25)
    valid = bool(txn_date and description and (debit_value or credit_value) and direction)
    return {
        "row": index,
        "txn_date": txn_date.isoformat() if txn_date else None,
        "description": description[:255],
        "reference": (reference or None),
        "debit": str(_q2(debit_value)),
        "credit": str(_q2(credit_value)),
        "direction": direction,
        "confidence": confidence,
        "issues": issues,
        "valid": valid,
        "source": source,
        "raw": {str(key): _json_safe(value) for key, value in raw.items()},
        "corrected": False,
        "duplicate": False,
    }


def _parse_tabular_statement(rows: list[dict[str, Any]], fmt: str) -> dict:
    warnings: list[str] = []
    if not rows:
        return {"rows": [], "warnings": ["The file contains no data rows."], "columns": {}}
    date_key = _header_key(rows[0], "date")
    description_key = _header_key(rows[0], "description")
    if date_key is None or description_key is None:
        return {
            "rows": [],
            "warnings": [
                "Date and description columns could not be detected. Rename the headers or "
                "export the statement as CSV."
            ],
            "columns": {},
        }
    reference_key = _header_key(rows[0], "reference")
    debit_key = _header_key(rows[0], "debit")
    credit_key = _header_key(rows[0], "credit")
    amount_key = _header_key(rows[0], "amount")
    direction_key = _header_key(rows[0], "direction")
    if debit_key is None and credit_key is None and amount_key is None:
        return {
            "rows": [],
            "warnings": [
                "Debit, credit or amount columns could not be detected. Export the statement "
                "with separate debit/credit columns."
            ],
            "columns": {},
        }
    parsed: list[dict] = []
    for index, row in enumerate(rows, start=2):
        txn_date = _coerce_date(row.get(date_key))
        description = str(row.get(description_key) or "").strip()
        reference = (
            str(row.get(reference_key)).strip()
            if reference_key and row.get(reference_key) not in (None, "")
            else None
        )
        debit = _coerce_decimal(row.get(debit_key)) if debit_key else None
        credit = _coerce_decimal(row.get(credit_key)) if credit_key else None
        direction_text = str(row.get(direction_key) or "") if direction_key else None
        amount = _coerce_decimal(row.get(amount_key)) if amount_key else None
        confidence = 100
        issues: list[str] = []
        if amount is not None and debit is None and credit is None:
            explicit = _direction_from_text(direction_text)
            if explicit == "debit":
                debit = abs(amount)
            elif explicit == "credit":
                credit = abs(amount)
            elif amount < 0:
                debit = abs(amount)
                direction_text = direction_text or "DR"
                issues.append("Debit direction was inferred from a negative amount.")
                confidence = 85
            else:
                credit = amount
                direction_text = direction_text or "CR"
                issues.append("Credit direction was inferred from a positive amount.")
                confidence = 85
        elif amount is not None and (debit is not None or credit is not None):
            issues.append("Both an amount and a debit/credit column were present; use one.")
            confidence = 70
        parsed.append(
            _statement_row(
                index=index,
                raw=row,
                txn_date=txn_date,
                description=description,
                reference=reference,
                debit=debit,
                credit=credit,
                direction_text=direction_text,
                confidence=confidence,
                issues=issues,
                source=fmt,
            )
        )
    if not parsed:
        warnings.append("No usable rows were found after skipping blank rows.")
    return {
        "rows": parsed,
        "warnings": warnings,
        "columns": {
            "date": date_key,
            "description": description_key,
            "reference": reference_key,
            "debit": debit_key,
            "credit": credit_key,
            "amount": amount_key,
            "direction": direction_key,
        },
    }


_PDF_DATE = re.compile(
    r"^\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{2,4})\s+"
)
_PDF_AMOUNT = re.compile(r"([\d,]+\.\d{2})\s*(Cr|Dr|CR|DR)?\s*$")


def _parse_pdf_statement(raw: bytes) -> dict:
    text = _extract_pdf_text(raw)
    warnings: list[str] = []
    if not text:
        return {
            "rows": [],
            "warnings": [
                "This PDF has no machine-readable text. It may be a scan; OCR is not used. "
                "Upload a CSV/Excel export instead."
            ],
            "columns": {},
        }
    parsed: list[dict] = []
    for line_index, line in enumerate(text.splitlines(), start=1):
        match = _PDF_DATE.match(line)
        if not match:
            continue
        remainder = line[match.end() :].strip()
        amount_match = _PDF_AMOUNT.search(remainder)
        if not amount_match:
            continue
        txn_date = _coerce_date(match.group(1))
        amount = _coerce_decimal(amount_match.group(1))
        if amount is None:
            continue
        marker = (amount_match.group(2) or "").upper()
        description = remainder[: amount_match.start()].strip()
        debit = credit = None
        direction_text = marker or None
        confidence = 25
        issues = ["Parsed from PDF text; verify the debit/credit direction and amounts."]
        if marker == "DR":
            debit = abs(amount)
            confidence = 65
        elif marker == "CR":
            credit = abs(amount)
            confidence = 65
        else:
            # Without an explicit Dr/Cr marker the column direction is unknown.
            issues.append("No Dr/Cr marker was found for this PDF line.")
        parsed.append(
            _statement_row(
                index=line_index,
                raw={"line": line},
                txn_date=txn_date,
                description=description,
                reference=None,
                debit=debit,
                credit=credit,
                direction_text=direction_text,
                confidence=confidence,
                issues=issues,
                source="pdf",
            )
        )
    if not parsed:
        warnings.append(
            "No transaction lines could be read from this PDF. OCR is not used; upload a "
            "CSV/Excel export or enter the rows manually."
        )
    return {"rows": parsed, "warnings": warnings, "columns": {}}


def parse_statement(raw: bytes, suffix: str) -> dict:
    if suffix == "pdf":
        return _parse_pdf_statement(raw)
    if suffix in ("xlsx", "xls"):
        rows, fmt = parse_tabular(raw, suffix)
        return _parse_tabular_statement(rows, fmt)
    if suffix in ("csv", "txt", "bin"):
        rows, fmt = parse_tabular(raw, suffix)
        return _parse_tabular_statement(rows, fmt)
    raise HTTPException(
        status_code=422,
        detail="Upload a CSV, Excel or text-based PDF bank statement.",
    )


def preview_statement(
    db: Session,
    *,
    owner_id: int,
    client_id: int,
    raw: bytes,
    suffix: str,
    filename: str,
) -> dict:
    parsed = parse_statement(raw, suffix)
    hashes = [
        _row_hash(
            _coerce_date(row["txn_date"]) or date.today(),
            row["description"],
            row["reference"],
            Decimal(row["debit"]),
            Decimal(row["credit"]),
        )
        for row in parsed["rows"]
        if row["txn_date"] is not None
    ]
    existing_hashes = {
        value
        for (value,) in db.query(PaymentTransaction.dedupe_hash)
        .filter(
            PaymentTransaction.user_id == owner_id,
            PaymentTransaction.client_id == client_id,
            PaymentTransaction.dedupe_hash.in_(hashes),
        )
        .all()
    } if hashes else set()
    seen: set[str] = set()
    duplicates = 0
    uncertain = 0
    for row in parsed["rows"]:
        if row["txn_date"] is not None:
            row_hash = _row_hash(
                _coerce_date(row["txn_date"]) or date.today(),
                row["description"],
                row["reference"],
                Decimal(row["debit"]),
                Decimal(row["credit"]),
            )
            if row_hash in existing_hashes or row_hash in seen:
                row["duplicate"] = True
                duplicates += 1
            seen.add(row_hash)
        if row["confidence"] < 100:
            uncertain += 1
    return {
        "filename": filename,
        "format": suffix,
        "warnings": parsed["warnings"],
        "columns": parsed["columns"],
        "rows": parsed["rows"],
        "summary": {
            "rows": len(parsed["rows"]),
            "valid": sum(1 for row in parsed["rows"] if row["valid"]),
            "uncertain": uncertain,
            "duplicates": duplicates,
            "total_debit": str(
                sum((Decimal(row["debit"]) for row in parsed["rows"]), ZERO)
            ),
            "total_credit": str(
                sum((Decimal(row["credit"]) for row in parsed["rows"]), ZERO)
            ),
        },
        "note": (
            "Preview only. Nothing is imported yet. Rows with a confidence below 100 and "
            "the direction of every PDF-derived amount must be reviewed."
        ),
    }


def _fernet():
    from cryptography.fernet import Fernet

    key = (settings.PAYMENT_DOCUMENT_KEY or "").strip()
    if key:
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=503,
                detail="PAYMENT_DOCUMENT_KEY is not a valid url-safe base64 Fernet key.",
            ) from exc
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(derived)


def _save_encrypted(db: Session, raw: bytes, suffix: str) -> tuple[str, str, int]:
    token = _fernet().encrypt(raw)
    return save_bytes(
        db,
        token,
        f"{suffix}{_ENCRYPTED_SUFFIX}",
        content_type="application/octet-stream",
    )


def _bank_connection(
    db: Session, *, owner: User, client: AccountingClient, actor: User
) -> PaymentConnection:
    connection = (
        db.query(PaymentConnection)
        .filter(
            PaymentConnection.user_id == owner.id,
            PaymentConnection.client_id == client.id,
            PaymentConnection.provider == "bank_statement",
        )
        .one_or_none()
    )
    if connection is None:
        connection = PaymentConnection(
            user_id=owner.id,
            client_id=client.id,
            created_by_user_id=actor.id,
            provider="bank_statement",
            label="Bank statements",
            environment="manual",
            mode="manual",
            status="connected",
            account_hint="statement uploads",
            permissions=["statement_import"],
            consent_at=utcnow(),
            connected_at=utcnow(),
        )
        db.add(connection)
        db.flush()
    return connection


def _apply_corrections(rows: list[dict], corrections: Iterable[dict]) -> list[dict]:
    by_row = {row["row"]: row for row in rows}
    for correction in corrections:
        row = by_row.get(int(correction.get("row") or 0))
        if row is None:
            continue
        if correction.get("txn_date"):
            parsed_date = _coerce_date(correction["txn_date"])
            if parsed_date is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Row {row['row']}: the corrected date could not be read.",
                )
            row["txn_date"] = parsed_date.isoformat()
        if correction.get("description") is not None:
            row["description"] = str(correction["description"]).strip()[:255]
        if correction.get("reference") is not None:
            row["reference"] = str(correction["reference"]).strip() or None
        debit = correction.get("debit")
        credit = correction.get("credit")
        if debit is not None:
            row["debit"] = str(_q2(_coerce_decimal(debit) or ZERO))
        if credit is not None:
            row["credit"] = str(_q2(_coerce_decimal(credit) or ZERO))
        debit_value = Decimal(row["debit"])
        credit_value = Decimal(row["credit"])
        if debit_value > 0 and credit_value == 0:
            row["direction"] = "debit"
        elif credit_value > 0 and debit_value == 0:
            row["direction"] = "credit"
        row["corrected"] = True
        row["confidence"] = 100
        row["issues"] = [
            issue for issue in row["issues"] if "manually" not in issue.lower()
        ]
        row["valid"] = bool(
            row["txn_date"]
            and row["description"]
            and (debit_value or credit_value)
            and row["direction"]
        )
    return rows


def import_statement(
    db: Session,
    *,
    owner: User,
    client: AccountingClient,
    actor: User,
    raw: bytes,
    suffix: str,
    filename: str,
    account_label: str | None,
    corrections: list[dict],
) -> dict:
    parsed = parse_statement(raw, suffix)
    rows = _apply_corrections(parsed["rows"], corrections)
    invalid = [row["row"] for row in rows if not row["valid"]]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                "Correct or remove these statement rows before importing: "
                + ", ".join(str(value) for value in invalid[:20])
                + ("…" if len(invalid) > 20 else "")
            ),
        )
    usable = [row for row in rows if not row["duplicate"]]
    if not usable:
        raise HTTPException(status_code=422, detail="No usable statement rows were found.")
    sha256 = hashlib.sha256(raw).hexdigest()
    prior = (
        db.query(AccountingBankImport)
        .filter(
            AccountingBankImport.client_id == client.id,
            AccountingBankImport.source_sha256 == sha256,
        )
        .order_by(AccountingBankImport.id.desc())
        .first()
    )
    if prior is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This exact statement was already imported on "
                f"{prior.created_at.date().isoformat()} (import #{prior.id}). Repeated uploads "
                "are blocked to prevent duplicate financial transactions."
            ),
        )

    seen_hashes: set[str] = set()
    prepared: list[dict] = []
    duplicate_rows = 0
    for row in usable:
        row_hash = _row_hash(
            _coerce_date(row["txn_date"]) or date.today(),
            row["description"],
            row["reference"],
            Decimal(row["debit"]),
            Decimal(row["credit"]),
        )
        if row_hash in seen_hashes or row["duplicate"]:
            duplicate_rows += 1
            continue
        seen_hashes.add(row_hash)
        row["hash"] = row_hash
        prepared.append(row)

    existing_hashes = {
        value
        for (value,) in db.query(PaymentTransaction.dedupe_hash)
        .filter(
            PaymentTransaction.user_id == owner.id,
            PaymentTransaction.client_id == client.id,
            PaymentTransaction.dedupe_hash.in_([row["hash"] for row in prepared]),
        )
        .all()
        if value
    } if prepared else set()
    if existing_hashes:
        remaining = []
        for row in prepared:
            if row["hash"] in existing_hashes:
                duplicate_rows += 1
            else:
                remaining.append(row)
        prepared = remaining
    if not prepared:
        raise HTTPException(
            status_code=409,
            detail=(
                "Every row in this statement already exists for this client. The upload was "
                "blocked to prevent duplicate financial transactions."
            ),
        )

    connection = _bank_connection(db, owner=owner, client=client, actor=actor)
    stored_name, saved_hash, size = _save_encrypted(db, raw, suffix)
    document = AccountingDocument(
        client_id=client.id,
        uploaded_by_user_id=actor.id,
        category="bank_statement",
        title=f"Bank statement · {filename}"[:200],
        original_filename=filename[:255],
        stored_name=stored_name,
        content_type="application/octet-stream",
        size_bytes=size,
        sha256=saved_hash,
        visibility="internal",
        source="payment_connect",
        status="received",
        note="Original statement stored encrypted at rest. Parsed rows require review.",
    )
    db.add(document)
    uncertain = sum(1 for row in prepared if row["confidence"] < 100)
    record = AccountingBankImport(
        client_id=client.id,
        connection_id=connection.id,
        imported_by_user_id=actor.id,
        filename=filename[:255],
        account_label=(account_label or "")[:160] or None,
        parsing_format=suffix,
        source_sha256=sha256,
        row_count=len(prepared),
        uncertain_count=uncertain,
        duplicate_count=duplicate_rows,
        status="imported",
        note=(
            "Imported through Payment Connect. Parsed rows are unverified until an accountant "
            "confirms them."
        ),
    )
    db.add(record)
    db.flush()
    created: list[PaymentTransaction] = []
    for row in prepared:
        txn_date = _coerce_date(row["txn_date"]) or date.today()
        debit = Decimal(row["debit"])
        credit = Decimal(row["credit"])
        direction = "credit" if credit > 0 else "debit"
        amount = credit if credit > 0 else debit
        bank_row = AccountingBankTransaction(
            import_id=record.id,
            client_id=client.id,
            txn_date=txn_date,
            description=row["description"],
            reference=row["reference"],
            debit=debit,
            credit=credit,
            direction=direction,
            raw=row["raw"],
            confidence=row["confidence"],
            issues=row["issues"],
            corrected=row["corrected"],
            source_hash=row["hash"],
            status="unmatched",
        )
        db.add(bank_row)
        db.flush()
        txn = PaymentTransaction(
            connection_id=connection.id,
            user_id=owner.id,
            client_id=client.id,
            provider="bank_statement",
            environment="manual",
            external_id=f"stmt-{row['hash']}",
            direction="incoming" if direction == "credit" else "outgoing",
            txn_type="payment" if direction == "credit" else "other",
            amount=_q2(amount),
            fee_amount=ZERO,
            net_amount=_q2(amount),
            currency="INR",
            status="completed",
            occurred_on=txn_date,
            occurred_at=datetime.combine(txn_date, time.min),
            description=row["description"],
            counterparty=None,
            reference=row["reference"],
            provider_reference=f"import-{record.id}",
            source="statement",
            import_id=record.id,
            bank_transaction_id=bank_row.id,
            raw=row["raw"],
            dedupe_hash=row["hash"],
            reconciliation_status="unverified",
            note=(
                "Statement row. Review the debit/credit direction before matching."
                if row["confidence"] < 100
                else None
            ),
            outlet_label=connection.outlet_label,
        )
        db.add(txn)
        created.append(txn)
    db.flush()
    for txn in created:
        suggest_match(db, txn)
    record.matched_count = 0
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.statement_imported",
        entity_type="accounting_bank_import",
        entity_id=record.id,
        detail={
            "client_id": client.id,
            "rows": len(prepared),
            "uncertain": uncertain,
            "duplicates_skipped": duplicate_rows,
            "format": suffix,
            "encrypted_original": True,
        },
    )
    return {
        "import_id": record.id,
        "document_id": document.id,
        "rows": len(prepared),
        "uncertain": uncertain,
        "duplicates_skipped": duplicate_rows,
        "warnings": parsed["warnings"],
        "encrypted_original": True,
        "status": record.status,
    }


# ------------------------------------------------------------------ Google Pay


def google_pay_eligibility() -> dict:
    return {
        "provider": "google_pay",
        "history_api": False,
        "transaction_detail_api": False,
        "tracking_supported": True,
        "summary": (
            "Google Pay does not expose a public API that lists or downloads every consumer "
            "Google Pay transaction. This module can only track merchant transaction IDs that "
            "you enter, and it marks them as not verified through Google."
        ),
        "requirements": [
            "A Google Pay merchant ID for the business",
            "The merchant transaction reference from an official merchant flow",
        ],
        "blocked": [
            "No Google Pay merchant integration credentials are configured in this deployment.",
            "FINOVEXA never requests Google passwords, UPI PINs, OTPs or card credentials.",
            "The Google Pay application and notifications are never scraped.",
        ],
    }


def google_pay_lookup() -> None:
    raise HTTPException(
        status_code=409,
        detail=(
            "An official Google Pay transaction-history or lookup API is not configured. "
            "Google does not provide a public API for downloading every consumer Google Pay "
            "transaction, and credential-based or scraped access is prohibited. Track the "
            "merchant reference in Payment Connect or import a bank statement instead."
        ),
    )


def track_google_pay_transaction(
    db: Session,
    *,
    owner: User,
    actor: User,
    client: AccountingClient | None,
    merchant_id: str,
    google_transaction_id: str,
    amount: Decimal,
    currency: str,
    occurred_on: date,
    status: str,
    description: str | None,
    upi_reference: str | None,
    outlet_label: str | None,
) -> PaymentTransaction:
    merchant_id = merchant_id.strip()
    google_transaction_id = google_transaction_id.strip()
    if not merchant_id or not google_transaction_id:
        raise HTTPException(
            status_code=422,
            detail="A merchant ID and merchant transaction reference are required.",
        )
    if amount <= 0:
        raise HTTPException(status_code=422, detail="The amount must be greater than zero.")
    if status not in ("completed", "pending", "failed", "refunded", "unknown"):
        raise HTTPException(status_code=422, detail="Choose a supported transaction status.")
    connection = _find_connection(
        db,
        user_id=owner.id,
        client_id=client.id if client else None,
        provider="google_pay",
        environment="manual",
    )
    if connection is None:
        connection = connect_provider(
            db,
            owner=owner,
            actor=actor,
            provider="google_pay",
            client=client,
            environment="manual",
            label="Google Pay merchant records",
            outlet_label=outlet_label,
            merchant_id=merchant_id,
            consent=True,
            note="Merchant references are entered manually and are not verified through Google.",
        )
    else:
        connection.merchant_id = merchant_id
    external_id = f"gpay:{merchant_id}:{google_transaction_id}"[:160]
    existing = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.connection_id == connection.id,
            PaymentTransaction.external_id == external_id,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing
    txn = PaymentTransaction(
        connection_id=connection.id,
        user_id=owner.id,
        client_id=client.id if client else None,
        provider="google_pay",
        environment="manual",
        external_id=external_id,
        direction="incoming",
        txn_type="payment",
        amount=_q2(amount),
        fee_amount=ZERO,
        net_amount=_q2(amount),
        currency=(currency or "INR")[:3].upper(),
        status=status,
        occurred_on=occurred_on,
        occurred_at=datetime.combine(occurred_on, time.min),
        description=(description or "Google Pay merchant transaction")[:1000],
        counterparty=None,
        reference=(upi_reference or google_transaction_id)[:160],
        provider_reference=google_transaction_id[:200],
        source="manual",
        raw={
            "merchant_id": merchant_id,
            "google_transaction_id": google_transaction_id,
            "upi_reference": upi_reference,
            "verification": "manual_entry_not_provider_verified",
        },
        dedupe_hash=_sha(f"google_pay|{merchant_id}|{google_transaction_id}"),
        reconciliation_status="unverified",
        note=(
            "Entered from a merchant reference. This is not verified through a Google API and "
            "must be reviewed before reconciliation."
        ),
        outlet_label=outlet_label or connection.outlet_label,
    )
    db.add(txn)
    db.flush()
    suggest_match(db, txn)
    log_audit(
        db,
        user_id=actor.id,
        actor=actor.email,
        action="payment_connect.google_pay_tracked",
        entity_type="payment_transaction",
        entity_id=txn.id,
        detail={
            "client_id": client.id if client else None,
            "merchant_id": merchant_id[:60],
            "verification": "manual",
        },
    )
    return txn
