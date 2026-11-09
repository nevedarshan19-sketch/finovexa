from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AccountingBankImport,
    AccountingClient,
    PaymentReconciliationEvent,
    PaymentSyncRun,
    PaymentTransaction,
    User,
)
from ..schemas import (
    BankStatementImportIn,
    BankStatementPreviewIn,
    GooglePayTrackIn,
    PaymentConnectionIn,
    PaymentReconcileIn,
    PaymentSyncIn,
)
from ..security import (
    get_current_accountant,
    get_current_owner,
    rate_limit,
)
from ..services.accounting import decode_data_url, ensure_client_access
from ..services.payment_connect import (
    approve_transaction,
    build_overview,
    connect_provider,
    connection_to_dict,
    disconnect_connection,
    event_to_dict,
    get_connection_or_404,
    google_pay_eligibility,
    google_pay_lookup,
    import_statement,
    list_transactions,
    mark_not_applicable,
    match_candidates,
    preview_statement,
    reject_transaction,
    reset_transaction,
    resolve_client_owner,
    suggest_match,
    sync_paypal,
    sync_run_to_dict,
    track_google_pay_transaction,
    transaction_to_dict,
)

router = APIRouter(prefix="/payment-connect", tags=["Payment Connect"])
accounting_router = APIRouter(
    prefix="/accounting/payment-connect", tags=["Payment Connect (accounting)"]
)


def _owner_transaction(db: Session, user: User, transaction_id: int) -> PaymentTransaction:
    txn = db.get(PaymentTransaction, transaction_id)
    if txn is None or txn.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment transaction not found.")
    return txn


def _accounting_scope(
    db: Session, user: User, client_id: int
) -> tuple[AccountingClient, User]:
    client = ensure_client_access(db, user, client_id)
    owner = resolve_client_owner(db, client)
    return client, owner


def _client_transaction(
    db: Session, client: AccountingClient, owner: User, transaction_id: int
) -> PaymentTransaction:
    txn = db.get(PaymentTransaction, transaction_id)
    if (
        txn is None
        or txn.user_id != owner.id
        or txn.client_id != client.id
    ):
        raise HTTPException(status_code=404, detail="Payment transaction not found.")
    return txn


def _bank_import_item(record: AccountingBankImport) -> dict:
    return {
        "id": record.id,
        "client_id": record.client_id,
        "connection_id": record.connection_id,
        "filename": record.filename,
        "account_label": record.account_label,
        "parsing_format": record.parsing_format,
        "source_sha256": record.source_sha256,
        "row_count": record.row_count,
        "matched_count": record.matched_count,
        "uncertain_count": record.uncertain_count,
        "duplicate_count": record.duplicate_count,
        "status": record.status,
        "note": record.note,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _window(payload: PaymentSyncIn) -> tuple[date, date]:
    today = date.today()
    end = payload.end_date or today
    if payload.start_date:
        start = payload.start_date
    else:
        start = end - timedelta(days=payload.days - 1)
    if start > end:
        raise HTTPException(status_code=422, detail="The start date must be before the end date.")
    return start, end


def _reconcile(
    db: Session,
    txn: PaymentTransaction,
    payload: PaymentReconcileIn,
    user: User,
) -> dict:
    if payload.action == "approve":
        result = approve_transaction(
            db, txn, actor=user, invoice_id=payload.invoice_id, note=payload.note
        )
    elif payload.action == "reject":
        result = reject_transaction(db, txn, actor=user, note=payload.note)
    elif payload.action == "not_applicable":
        result = mark_not_applicable(db, txn, actor=user, note=payload.note)
    elif payload.action == "reset":
        result = reset_transaction(db, txn, actor=user, note=payload.note)
    else:
        suggest_match(db, txn)
        result = transaction_to_dict(txn)
    db.commit()
    db.refresh(txn)
    return {
        "transaction": transaction_to_dict(txn),
        "candidates": match_candidates(db, txn),
        "result": result,
    }


# ------------------------------------------------------------------ owner


@router.get("/overview")
def owner_overview(
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return build_overview(db, user_id=user.id, client_id=None)


@router.get("/transactions")
def owner_transactions(
    date_from: date | None = None,
    date_to: date | None = None,
    provider: str | None = None,
    direction: str | None = Query(default=None, pattern="^(incoming|outgoing)$"),
    status: str | None = None,
    reconciliation_status: str | None = None,
    outlet_label: str | None = None,
    search: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    include_duplicates: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return list_transactions(
        db,
        user_id=user.id,
        client_id=None,
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        direction=direction,
        status=status,
        reconciliation_status=reconciliation_status,
        outlet_label=outlet_label,
        search=search,
        amount_min=amount_min,
        amount_max=amount_max,
        include_duplicates=include_duplicates,
        limit=limit,
        offset=offset,
    )


@router.get("/transactions/{transaction_id}/events")
def owner_transaction_events(
    transaction_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    txn = _owner_transaction(db, user, transaction_id)
    rows = (
        db.query(PaymentReconciliationEvent)
        .filter(PaymentReconciliationEvent.transaction_id == txn.id)
        .order_by(PaymentReconciliationEvent.created_at.desc())
        .all()
    )
    return {"items": [event_to_dict(row) for row in rows]}


@router.get("/transactions/{transaction_id}/candidates")
def owner_transaction_candidates(
    transaction_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    txn = _owner_transaction(db, user, transaction_id)
    return {"items": match_candidates(db, txn)}


@router.post("/transactions/{transaction_id}/reconcile")
def owner_reconcile_transaction(
    transaction_id: int,
    payload: PaymentReconcileIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if payload.client_id is not None:
        raise HTTPException(
            status_code=422, detail="Owner reconciliation is business-wide; omit client_id."
        )
    txn = _owner_transaction(db, user, transaction_id)
    return _reconcile(db, txn, payload, user)


@router.post("/connections", status_code=201, dependencies=[Depends(rate_limit("payment_connect", 10, 60))])
def owner_create_connection(
    payload: PaymentConnectionIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if payload.client_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Owner connections are business-wide. An accountant manages client-specific connections.",
        )
    if payload.provider == "bank_statement":
        raise HTTPException(
            status_code=422,
            detail="Bank statements are imported by an accountant inside a client engagement.",
        )
    connection = connect_provider(
        db,
        owner=user,
        actor=user,
        provider=payload.provider,
        client=None,
        environment=payload.environment,
        label=payload.label,
        outlet_label=payload.outlet_label,
        merchant_id=payload.merchant_id,
        consent=payload.consent,
        note=payload.note,
    )
    db.commit()
    db.refresh(connection)
    return connection_to_dict(db, connection)


@router.post("/connections/{connection_id}/disconnect")
def owner_disconnect(
    connection_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    connection = get_connection_or_404(
        db, connection_id, user_id=user.id, client_id=None
    )
    disconnect_connection(db, connection, actor=user)
    db.commit()
    db.refresh(connection)
    return connection_to_dict(db, connection)


@router.post(
    "/connections/{connection_id}/sync",
    dependencies=[Depends(rate_limit("payment_connect_sync", 6, 60))],
)
def owner_sync(
    connection_id: int,
    payload: PaymentSyncIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if payload.client_id is not None:
        raise HTTPException(status_code=422, detail="Owner sync is business-wide; omit client_id.")
    connection = get_connection_or_404(
        db, connection_id, user_id=user.id, client_id=None
    )
    if connection.provider != "paypal":
        raise HTTPException(
            status_code=422,
            detail="This connection has no automatic sync. Import a statement or track a merchant reference.",
        )
    start, end = _window(payload)
    run = sync_paypal(
        db, connection, actor=user, start_date=start, end_date=end, trigger=payload.trigger
    )
    return sync_run_to_dict(run)


@router.get("/connections/{connection_id}/runs")
def owner_sync_runs(
    connection_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    connection = get_connection_or_404(
        db, connection_id, user_id=user.id, client_id=None
    )
    rows = (
        db.query(PaymentSyncRun)
        .filter(PaymentSyncRun.connection_id == connection.id)
        .order_by(PaymentSyncRun.started_at.desc())
        .limit(20)
        .all()
    )
    return {"items": [sync_run_to_dict(row) for row in rows]}


@router.get("/google-pay/eligibility")
def owner_google_pay_eligibility(user: User = Depends(get_current_owner)):
    return google_pay_eligibility()


@router.post("/google-pay/lookup")
def owner_google_pay_lookup(user: User = Depends(get_current_owner)):
    google_pay_lookup()


@router.post("/google-pay/track", status_code=201)
def owner_google_pay_track(
    payload: GooglePayTrackIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if payload.client_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Owner tracking is business-wide. An accountant tracks client-specific references.",
        )
    txn = track_google_pay_transaction(
        db,
        owner=user,
        actor=user,
        client=None,
        merchant_id=payload.merchant_id,
        google_transaction_id=payload.google_transaction_id,
        amount=payload.amount,
        currency=payload.currency,
        occurred_on=payload.occurred_on,
        status=payload.status,
        description=payload.description,
        upi_reference=payload.upi_reference,
        outlet_label=payload.outlet_label,
    )
    db.commit()
    db.refresh(txn)
    return transaction_to_dict(txn)


# ------------------------------------------------------------------ accountant


def _require_senior(user: User) -> None:
    if user.role != "senior_accountant":
        raise HTTPException(
            status_code=403,
            detail="A senior accountant must manage provider connections and approvals.",
        )


@accounting_router.get("/overview")
def accounting_overview(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, client_id)
    return build_overview(db, user_id=owner.id, client_id=client.id)


@accounting_router.get("/transactions")
def accounting_transactions(
    client_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    provider: str | None = None,
    direction: str | None = Query(default=None, pattern="^(incoming|outgoing)$"),
    status: str | None = None,
    reconciliation_status: str | None = None,
    outlet_label: str | None = None,
    search: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    include_duplicates: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, client_id)
    return list_transactions(
        db,
        user_id=owner.id,
        client_id=client.id,
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        direction=direction,
        status=status,
        reconciliation_status=reconciliation_status,
        outlet_label=outlet_label,
        search=search,
        amount_min=amount_min,
        amount_max=amount_max,
        include_duplicates=include_duplicates,
        limit=limit,
        offset=offset,
    )


@accounting_router.get("/transactions/{transaction_id}/events")
def accounting_transaction_events(
    transaction_id: int,
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, client_id)
    txn = _client_transaction(db, client, owner, transaction_id)
    rows = (
        db.query(PaymentReconciliationEvent)
        .filter(PaymentReconciliationEvent.transaction_id == txn.id)
        .order_by(PaymentReconciliationEvent.created_at.desc())
        .all()
    )
    return {"items": [event_to_dict(row) for row in rows]}


@accounting_router.get("/transactions/{transaction_id}/candidates")
def accounting_transaction_candidates(
    transaction_id: int,
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, client_id)
    txn = _client_transaction(db, client, owner, transaction_id)
    return {"items": match_candidates(db, txn)}


@accounting_router.post("/transactions/{transaction_id}/reconcile")
def accounting_reconcile_transaction(
    transaction_id: int,
    payload: PaymentReconcileIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client_id = payload.client_id or 0
    if not client_id:
        raise HTTPException(status_code=422, detail="client_id is required.")
    client, owner = _accounting_scope(db, user, client_id)
    txn = _client_transaction(db, client, owner, transaction_id)
    if payload.action == "approve":
        _require_senior(user)
    return _reconcile(db, txn, payload, user)


@accounting_router.post(
    "/connections",
    status_code=201,
    dependencies=[Depends(rate_limit("payment_connect", 10, 60))],
)
def accounting_create_connection(
    payload: PaymentConnectionIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    _require_senior(user)
    if payload.client_id is None:
        raise HTTPException(status_code=422, detail="client_id is required.")
    if payload.provider == "bank_statement":
        raise HTTPException(
            status_code=422,
            detail="Bank statements are imported directly and do not need a separate connection.",
        )
    client, owner = _accounting_scope(db, user, payload.client_id)
    connection = connect_provider(
        db,
        owner=owner,
        actor=user,
        provider=payload.provider,
        client=client,
        environment=payload.environment,
        label=payload.label,
        outlet_label=payload.outlet_label,
        merchant_id=payload.merchant_id,
        consent=payload.consent,
        note=payload.note,
    )
    db.commit()
    db.refresh(connection)
    return connection_to_dict(db, connection)


@accounting_router.post("/connections/{connection_id}/disconnect")
def accounting_disconnect(
    connection_id: int,
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    _require_senior(user)
    client, owner = _accounting_scope(db, user, client_id)
    connection = get_connection_or_404(
        db, connection_id, user_id=owner.id, client_id=client.id
    )
    disconnect_connection(db, connection, actor=user)
    db.commit()
    db.refresh(connection)
    return connection_to_dict(db, connection)


@accounting_router.post(
    "/connections/{connection_id}/sync",
    dependencies=[Depends(rate_limit("payment_connect_sync", 6, 60))],
)
def accounting_sync(
    connection_id: int,
    payload: PaymentSyncIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    _require_senior(user)
    client_id = payload.client_id or 0
    if not client_id:
        raise HTTPException(status_code=422, detail="client_id is required.")
    client, owner = _accounting_scope(db, user, client_id)
    connection = get_connection_or_404(
        db, connection_id, user_id=owner.id, client_id=client.id
    )
    if connection.provider != "paypal":
        raise HTTPException(
            status_code=422,
            detail="This connection has no automatic sync. Import a statement or track a merchant reference.",
        )
    start, end = _window(payload)
    run = sync_paypal(
        db, connection, actor=user, start_date=start, end_date=end, trigger=payload.trigger
    )
    return sync_run_to_dict(run)


@accounting_router.get("/connections/{connection_id}/runs")
def accounting_sync_runs(
    connection_id: int,
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, client_id)
    connection = get_connection_or_404(
        db, connection_id, user_id=owner.id, client_id=client.id
    )
    rows = (
        db.query(PaymentSyncRun)
        .filter(PaymentSyncRun.connection_id == connection.id)
        .order_by(PaymentSyncRun.started_at.desc())
        .limit(20)
        .all()
    )
    return {"items": [sync_run_to_dict(row) for row in rows]}


@accounting_router.post(
    "/bank-statements/preview",
    dependencies=[Depends(rate_limit("payment_connect_statement", 20, 300))],
)
def accounting_statement_preview(
    payload: BankStatementPreviewIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, payload.client_id)
    raw, suffix = decode_data_url(payload.data_url)
    result = preview_statement(
        db,
        owner_id=owner.id,
        client_id=client.id,
        raw=raw,
        suffix=suffix,
        filename=payload.filename,
    )
    result["client_id"] = client.id
    result["account_label"] = payload.account_label
    return result


@accounting_router.post(
    "/bank-statements/import",
    status_code=201,
    dependencies=[Depends(rate_limit("payment_connect_statement", 20, 300))],
)
def accounting_statement_import(
    payload: BankStatementImportIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, payload.client_id)
    raw, suffix = decode_data_url(payload.data_url)
    result = import_statement(
        db,
        owner=owner,
        client=client,
        actor=user,
        raw=raw,
        suffix=suffix,
        filename=payload.filename,
        account_label=payload.account_label,
        corrections=[item.model_dump() for item in payload.corrections],
    )
    db.commit()
    return result


@accounting_router.get("/bank-statements")
def accounting_statement_imports(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client, owner = _accounting_scope(db, user, client_id)
    rows = (
        db.query(AccountingBankImport)
        .filter(AccountingBankImport.client_id == client.id)
        .order_by(AccountingBankImport.created_at.desc())
        .limit(30)
        .all()
    )
    return {"items": [_bank_import_item(row) for row in rows]}


@accounting_router.get("/google-pay/eligibility")
def accounting_google_pay_eligibility(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    _accounting_scope(db, user, client_id)
    return google_pay_eligibility()


@accounting_router.post("/google-pay/lookup")
def accounting_google_pay_lookup(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    _accounting_scope(db, user, client_id)
    google_pay_lookup()


@accounting_router.post("/google-pay/track", status_code=201)
def accounting_google_pay_track(
    payload: GooglePayTrackIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    _require_senior(user)
    client_id = payload.client_id or 0
    if not client_id:
        raise HTTPException(status_code=422, detail="client_id is required.")
    client, owner = _accounting_scope(db, user, client_id)
    txn = track_google_pay_transaction(
        db,
        owner=owner,
        actor=user,
        client=client,
        merchant_id=payload.merchant_id,
        google_transaction_id=payload.google_transaction_id,
        amount=payload.amount,
        currency=payload.currency,
        occurred_on=payload.occurred_on,
        status=payload.status,
        description=payload.description,
        upi_reference=payload.upi_reference,
        outlet_label=payload.outlet_label,
    )
    db.commit()
    db.refresh(txn)
    return transaction_to_dict(txn)
