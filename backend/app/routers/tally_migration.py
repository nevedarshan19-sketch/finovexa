"""Tally Data Migration APIs.

Uploads are parsed and staged for review; only a senior accountant can approve a
batch, and approval writes to historical tables only. No route connects to or
writes into a Tally installation.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..accounting_catalog import (
    TALLY_MAPPING_FIELDS,
    TALLY_MIGRATION_IMPORT_LABELS,
    TALLY_MIGRATION_STATUSES,
    TALLY_VERSIONS,
    TALLY_VERSION_FORMATS,
)
from ..database import get_db
from ..models import (
    AccountingClient,
    AccountingHistoricalLedger,
    AccountingHistoricalVoucher,
    AccountingOpeningBalance,
    AccountingOpeningBalanceLine,
    AccountingTallyMappingTemplate,
    AccountingTallyMigration,
    User,
    utcnow,
)
from ..schemas import (
    TallyMappingTemplateIn,
    TallyMappingTemplateUpdateIn,
    TallyMigrationDecisionIn,
    TallyMigrationIn,
    TallyMigrationPreviewIn,
    TallyMigrationRevalidateIn,
    TallyOpeningBalanceIn,
)
from ..security import get_current_accountant, get_current_senior_accountant
from ..services.accounting import (
    decode_data_url,
    ensure_client_access,
    notify,
    save_document_file,
    staff_client_filter,
)
from ..services.audit import log_audit
from ..services.file_store import StoredFileMissing, build_download, local_path
from ..services.tally_history import (
    available_years,
    compare_years,
    ledger_history,
    ledger_names,
    report_bundle,
)
from ..services.tally_migration import (
    create_batch,
    decide_batch,
    error_report_csv,
    migration_to_dict,
    opening_to_dict,
    preview_migration_file,
    revalidate_batch,
    rollback_batch,
    submit_batch,
    template_to_dict,
)

router = APIRouter(prefix="/accounting/tally-migration", tags=["Tally migration"])

_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
    "xml": "application/xml",
    "json": "application/json",
}


def _audit(
    db: Session,
    user: User,
    action: str,
    *,
    client_id: int | None,
    entity: str,
    entity_id: int | None,
    detail: dict | None = None,
) -> None:
    payload = dict(detail or {})
    if client_id is not None:
        payload.setdefault("client_id", client_id)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action=action,
        entity_type=entity,
        entity_id=entity_id if entity_id is not None else client_id,
        detail=payload,
    )


def _visible_client_filter(db: Session, user: User):
    clause = staff_client_filter(db, user)
    if clause is None:
        return None
    return clause


def _batch_or_404(db: Session, batch_id: int) -> AccountingTallyMigration:
    batch = db.get(AccountingTallyMigration, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found.")
    return batch


def _check_signature(raw: bytes, file_format: str) -> None:
    head = raw[:8]
    if file_format == "xlsx" and not raw.startswith(b"PK"):
        raise HTTPException(status_code=422, detail="This file is not a valid .xlsx workbook.")
    if file_format == "xls" and not raw.startswith(b"\xd0\xcf\x11\xe0"):
        raise HTTPException(status_code=422, detail="This file is not a valid legacy .xls workbook.")
    if file_format == "xml" and not raw.lstrip().startswith(b"<"):
        raise HTTPException(status_code=422, detail="This file is not valid XML.")
    if file_format == "json" and head.lstrip()[:1] not in (b"{", b"["):
        raise HTTPException(status_code=422, detail="This file is not valid JSON.")


@router.get("/catalog")
def migration_catalog(user: User = Depends(get_current_accountant)):
    return {
        "versions": [
            {"key": version, "formats": list(TALLY_VERSION_FORMATS[version])}
            for version in TALLY_VERSIONS
        ],
        "formats": [
            {"key": "xlsx", "label": "Excel workbook (.xlsx)"},
            {"key": "xls", "label": "Legacy Excel (.xls)"},
            {"key": "csv", "label": "CSV (.csv)"},
            {"key": "xml", "label": "Tally XML (.xml)"},
            {"key": "json", "label": "JSON (.json, TallyPrime 3.0+)"},
        ],
        "import_types": [
            {"key": key, "label": label} for key, label in TALLY_MIGRATION_IMPORT_LABELS.items()
        ],
        "statuses": list(TALLY_MIGRATION_STATUSES),
        "mapping_fields": [dict(item) for item in TALLY_MAPPING_FIELDS],
        "notes": [
            "File-based migration only: FINOVEXA does not connect to Tally.",
            "JSON import is offered for TallyPrime 3.0 and later; older versions use XML, Excel or CSV.",
            "Imported history is stored separately from the live FINOVEXA ledger.",
            "Every approved batch keeps the original upload for the configured retention period.",
        ],
    }


@router.post("/preview")
def preview_upload(
    payload: TallyMigrationPreviewIn,
    user: User = Depends(get_current_accountant),
):
    raw, _ = decode_data_url(payload.data_url)
    _check_signature(raw, payload.file_format)
    return preview_migration_file(raw, payload.file_format)


@router.get("/mappings")
def list_mapping_templates(
    client_id: int | None = None,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingTallyMappingTemplate)
    if client_id is not None:
        ensure_client_access(db, user, client_id)
    rows = query.order_by(AccountingTallyMappingTemplate.created_at.desc()).limit(200).all()
    if user.role == "senior_accountant":
        visible = rows
    else:
        visible = [
            row
            for row in rows
            if row.is_shared or row.created_by_user_id == user.id or row.client_id == client_id
        ]
    return {"items": [template_to_dict(row) for row in visible]}


@router.post("/mappings", status_code=201)
def create_mapping_template(
    payload: TallyMappingTemplateIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    if payload.client_id is not None:
        ensure_client_access(db, user, payload.client_id)
    template = AccountingTallyMappingTemplate(
        name=payload.name.strip(),
        client_id=payload.client_id,
        file_format=payload.file_format,
        import_type=payload.import_type,
        mapping=payload.mapping,
        created_by_user_id=user.id,
        is_shared=payload.is_shared,
    )
    db.add(template)
    _audit(
        db,
        user,
        "accounting.tally_mapping_template_saved",
        client_id=payload.client_id,
        entity="accounting_tally_mapping_template",
        entity_id=None,
        detail={"name": template.name, "format": template.file_format, "import_type": template.import_type},
    )
    db.commit()
    db.refresh(template)
    return template_to_dict(template)


@router.patch("/mappings/{template_id}")
def update_mapping_template(
    template_id: int,
    payload: TallyMappingTemplateUpdateIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    template = db.get(AccountingTallyMappingTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Mapping template not found.")
    if template.client_id is not None:
        ensure_client_access(db, user, template.client_id)
    if user.role != "senior_accountant" and template.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only edit mapping templates you created.")
    if payload.name is not None:
        template.name = payload.name.strip()
    if payload.mapping is not None:
        template.mapping = payload.mapping
    if payload.is_shared is not None:
        template.is_shared = payload.is_shared
    _audit(
        db,
        user,
        "accounting.tally_mapping_template_updated",
        client_id=template.client_id,
        entity="accounting_tally_mapping_template",
        entity_id=template.id,
        detail={"name": template.name},
    )
    db.commit()
    db.refresh(template)
    return template_to_dict(template)


@router.delete("/mappings/{template_id}")
def delete_mapping_template(
    template_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    template = db.get(AccountingTallyMappingTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Mapping template not found.")
    if template.client_id is not None:
        ensure_client_access(db, user, template.client_id)
    if user.role != "senior_accountant" and template.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only delete mapping templates you created.")
    _audit(
        db,
        user,
        "accounting.tally_mapping_template_deleted",
        client_id=template.client_id,
        entity="accounting_tally_mapping_template",
        entity_id=template.id,
        detail={"name": template.name},
    )
    db.delete(template)
    db.commit()
    return {"deleted": True}


@router.post("/batches", status_code=201)
def upload_batch(
    payload: TallyMigrationIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, payload.client_id)
    raw, _ = decode_data_url(payload.data_url)
    if len(raw) > 2 * 1024 * 1024 and payload.file_format in ("csv", "xlsx", "xls"):
        # Allowed: the configured upload limit was already checked by decode_data_url.
        pass
    _check_signature(raw, payload.file_format)
    if payload.mapping_template_id is not None:
        template = db.get(AccountingTallyMappingTemplate, payload.mapping_template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Mapping template not found.")
        if template.client_id is not None and template.client_id != payload.client_id:
            raise HTTPException(status_code=403, detail="This mapping template belongs to another client.")
        if not payload.mapping:
            payload.mapping = template.mapping
    stored_name, file_sha256, file_size = save_document_file(db, raw, payload.file_format)
    batch = create_batch(
        db,
        user=user,
        client_id=payload.client_id,
        payload=payload,
        raw=raw,
        stored_name=stored_name,
        file_sha256=file_sha256,
        file_size=file_size,
    )
    _audit(
        db,
        user,
        "accounting.tally_migration_validated",
        client_id=payload.client_id,
        entity="accounting_tally_migration",
        entity_id=batch.id,
        detail={
            "import_type": batch.import_type,
            "format": batch.file_format,
            "financial_year": batch.financial_year,
            "records": batch.row_count,
            "valid": batch.valid_count,
            "warnings": batch.warning_count,
            "errors": batch.error_count,
            "duplicates": batch.duplicate_count,
        },
    )
    senior_id = client.senior_accountant_user_id
    if user.role == "junior_accountant" and senior_id:
        notify(
            db,
            senior_id,
            kind="tally_migration_ready",
            title="Tally import ready for review",
            body=(
                f"{user.full_name} uploaded {payload.filename} for {client.business_name} "
                f"({batch.financial_year}). Review the validation and approve the batch."
            ),
            client_id=client.id,
        )
    db.commit()
    db.refresh(batch)
    return migration_to_dict(db, batch, include_validation=True, include_rows=True, row_limit=200)


@router.get("/batches")
def list_batches(
    client_id: int | None = None,
    status: str | None = None,
    financial_year: str | None = None,
    import_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingTallyMigration)
    clause = _visible_client_filter(db, user)
    if client_id is not None:
        ensure_client_access(db, user, client_id)
        query = query.filter(AccountingTallyMigration.client_id == client_id)
    elif clause is not None:
        query = query.filter(
            AccountingTallyMigration.client_id.in_(
                db.query(AccountingClient.id).filter(clause)
            )
        )
    if status:
        query = query.filter(AccountingTallyMigration.status == status)
    if financial_year:
        query = query.filter(AccountingTallyMigration.financial_year == financial_year)
    if import_type:
        query = query.filter(AccountingTallyMigration.import_type == import_type)
    rows = query.order_by(AccountingTallyMigration.created_at.desc()).limit(limit).all()
    pending_query = db.query(AccountingTallyMigration.id).filter(
        AccountingTallyMigration.status == "pending_approval"
    )
    if clause is not None:
        pending_query = pending_query.filter(
            AccountingTallyMigration.client_id.in_(
                db.query(AccountingClient.id).filter(clause)
            )
        )
    return {
        "items": [migration_to_dict(db, row) for row in rows],
        "pending_approval_count": pending_query.count(),
    }


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: int,
    include_rows: bool = True,
    row_limit: int = Query(default=200, ge=0, le=2000),
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    batch = _batch_or_404(db, batch_id)
    ensure_client_access(db, user, batch.client_id)
    return migration_to_dict(
        db,
        batch,
        include_validation=True,
        include_rows=include_rows,
        row_limit=row_limit,
    )


@router.post("/batches/{batch_id}/revalidate")
def revalidate(
    batch_id: int,
    payload: TallyMigrationRevalidateIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    batch = _batch_or_404(db, batch_id)
    ensure_client_access(db, user, batch.client_id)
    if batch.prepared_by_user_id not in (None, user.id) and user.role != "senior_accountant":
        raise HTTPException(status_code=403, detail="Only the preparer or a senior can revalidate this batch.")
    if not batch.stored_name:
        raise HTTPException(status_code=404, detail="The original upload is unavailable.")
    mapping = payload.mapping
    if mapping is None and payload.mapping_template_id is not None:
        template = db.get(AccountingTallyMappingTemplate, payload.mapping_template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Mapping template not found.")
        mapping = template.mapping
        batch.mapping_template_id = template.id
    try:
        with local_path(db, batch.stored_name) as path:
            revalidate_batch(db, batch=batch, mapping=mapping, stored_path=path)
    except StoredFileMissing as exc:
        raise HTTPException(
            status_code=404, detail="The original upload is unavailable."
        ) from exc
    _audit(
        db,
        user,
        "accounting.tally_migration_revalidated",
        client_id=batch.client_id,
        entity="accounting_tally_migration",
        entity_id=batch.id,
        detail={"records": batch.row_count, "errors": batch.error_count, "warnings": batch.warning_count},
    )
    db.commit()
    db.refresh(batch)
    return migration_to_dict(db, batch, include_validation=True, include_rows=True, row_limit=200)


@router.post("/batches/{batch_id}/submit")
def submit(
    batch_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    batch = _batch_or_404(db, batch_id)
    client = ensure_client_access(db, user, batch.client_id)
    if batch.prepared_by_user_id not in (None, user.id) and user.role != "senior_accountant":
        raise HTTPException(status_code=403, detail="Only the preparer or a senior can submit this batch.")
    submit_batch(db, batch, user)
    _audit(
        db,
        user,
        "accounting.tally_migration_submitted",
        client_id=batch.client_id,
        entity="accounting_tally_migration",
        entity_id=batch.id,
        detail={"records": batch.row_count, "importable": batch.valid_count + batch.warning_count},
    )
    senior_id = client.senior_accountant_user_id
    if senior_id and senior_id != user.id:
        notify(
            db,
            senior_id,
            kind="tally_migration_pending",
            title="Tally import awaiting approval",
            body=f"{user.full_name} submitted {batch.filename} for {client.business_name}.",
            client_id=client.id,
        )
    db.commit()
    db.refresh(batch)
    return migration_to_dict(db, batch, include_validation=True)


@router.post("/batches/{batch_id}/decision")
def decision(
    batch_id: int,
    payload: TallyMigrationDecisionIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    batch = _batch_or_404(db, batch_id)
    client = ensure_client_access(db, user, batch.client_id)
    result = decide_batch(db, batch, user, payload.decision, payload.note)
    _audit(
        db,
        user,
        f"accounting.tally_migration_{batch.status}",
        client_id=batch.client_id,
        entity="accounting_tally_migration",
        entity_id=batch.id,
        detail={
            "decision": payload.decision,
            "note": payload.note,
            "imported": batch.imported_count,
            "self_approved": batch.prepared_by_user_id == user.id,
        },
    )
    notify(
        db,
        batch.prepared_by_user_id,
        kind=f"tally_migration_{batch.status}",
        title=f"Tally import {batch.status}",
        body=(
            f"{user.full_name} {payload.decision}d the import {batch.filename} for {client.business_name}."
            + (f" Note: {payload.note}" if payload.note else "")
        ),
        client_id=client.id,
    )
    db.commit()
    db.refresh(batch)
    return {
        "batch": migration_to_dict(db, batch, include_validation=True),
        "result": result,
    }


@router.post("/batches/{batch_id}/rollback")
def rollback(
    batch_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    batch = _batch_or_404(db, batch_id)
    ensure_client_access(db, user, batch.client_id)
    result = rollback_batch(db, batch, user)
    _audit(
        db,
        user,
        "accounting.tally_migration_rolled_back",
        client_id=batch.client_id,
        entity="accounting_tally_migration",
        entity_id=batch.id,
        detail=result,
    )
    db.commit()
    db.refresh(batch)
    return {"batch": migration_to_dict(db, batch), "result": result}


@router.get("/batches/{batch_id}/error-report")
def download_error_report(
    batch_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    batch = _batch_or_404(db, batch_id)
    ensure_client_access(db, user, batch.client_id)
    content = error_report_csv(batch)
    _audit(
        db,
        user,
        "accounting.tally_migration_error_report_downloaded",
        client_id=batch.client_id,
        entity="accounting_tally_migration",
        entity_id=batch.id,
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="tally-import-{batch.id}-error-report.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/batches/{batch_id}/source")
def download_source(
    batch_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    batch = _batch_or_404(db, batch_id)
    ensure_client_access(db, user, batch.client_id)
    if not batch.stored_name:
        raise HTTPException(status_code=404, detail="The original upload is unavailable.")
    _audit(
        db,
        user,
        "accounting.tally_migration_source_downloaded",
        client_id=batch.client_id,
        entity="accounting_tally_migration",
        entity_id=batch.id,
        detail={"filename": batch.filename, "sha256": batch.file_sha256},
    )
    db.commit()
    try:
        return build_download(
            db,
            batch.stored_name,
            filename=batch.filename,
            media_type=_MIME.get(batch.file_format, "application/octet-stream"),
        )
    except StoredFileMissing as exc:
        raise HTTPException(
            status_code=404, detail="The original upload is unavailable."
        ) from exc


@router.get("/opening-balances")
def list_opening_balances(
    client_id: int,
    financial_year: str | None = None,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    query = db.query(AccountingOpeningBalance).filter(
        AccountingOpeningBalance.client_id == client_id
    )
    if financial_year:
        query = query.filter(AccountingOpeningBalance.financial_year == financial_year)
    rows = query.order_by(AccountingOpeningBalance.financial_year.desc()).limit(20).all()
    return {"items": [opening_to_dict(row) for row in rows]}


@router.post("/opening-balances", status_code=201)
def create_opening_balance(
    payload: TallyOpeningBalanceIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    """Manual senior entry; file-based opening balances use an approved batch."""
    client = ensure_client_access(db, user, payload.client_id)
    vouchers_exist = (
        db.query(AccountingHistoricalVoucher.id)
        .filter(
            AccountingHistoricalVoucher.client_id == client.id,
            AccountingHistoricalVoucher.financial_year == payload.financial_year,
            AccountingHistoricalVoucher.status == "posted",
        )
        .first()
        is not None
    )
    if vouchers_exist:
        raise HTTPException(
            status_code=409,
            detail=(
                "Historical vouchers already exist for this year. Their opening balances are part of "
                "that history; entering separate opening balances would double count."
            ),
        )
    existing = (
        db.query(AccountingOpeningBalance)
        .filter(
            AccountingOpeningBalance.client_id == client.id,
            AccountingOpeningBalance.financial_year == payload.financial_year,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Opening balances already exist for this year; they were not overwritten.",
        )
    opening = AccountingOpeningBalance(
        client_id=client.id,
        financial_year=payload.financial_year,
        opening_date=payload.opening_date,
        status="approved",
        prepared_by_user_id=user.id,
        approved_by_user_id=user.id,
        approved_at=utcnow(),
        approval_note=payload.note,
        total_debit=sum((line.debit for line in payload.lines), 0),
        total_credit=sum((line.credit for line in payload.lines), 0),
        stock_value=sum(
            (line.debit for line in payload.lines if line.stock_item), 0
        ),
        details={"source": "senior_manual_entry", "note": payload.note},
    )
    db.add(opening)
    db.flush()
    for position, line in enumerate(payload.lines, start=1):
        db.add(
            AccountingOpeningBalanceLine(
                opening_id=opening.id,
                line_number=position,
                ledger_name=line.ledger_name,
                group_name=line.group_name,
                party_type=line.party_type,
                debit=line.debit,
                credit=line.credit,
                stock_item=line.stock_item,
                quantity=line.quantity,
                rate=line.rate,
                value=line.debit,
                narration=line.narration,
            )
        )
    _audit(
        db,
        user,
        "accounting.tally_opening_balance_approved",
        client_id=client.id,
        entity="accounting_opening_balance",
        entity_id=opening.id,
        detail={"financial_year": payload.financial_year, "lines": len(payload.lines)},
    )
    db.commit()
    db.refresh(opening)
    return opening_to_dict(opening)


@router.get("/years")
def years_and_ledgers(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    return {
        "years": available_years(db, client_id),
        "ledgers": ledger_names(db, client_id),
    }


@router.get("/reports")
def reports(
    client_id: int,
    financial_year: str | None = None,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    years = available_years(db, client_id)
    year = financial_year or (years[0] if years else None)
    if not year:
        raise HTTPException(
            status_code=404,
            detail="No imported history exists for this client yet. Complete an approved import first.",
        )
    return report_bundle(db, client, year)


@router.get("/reports/ledger")
def ledger_report(
    client_id: int,
    ledger: str = Query(min_length=1, max_length=180),
    financial_year: str | None = None,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    years = available_years(db, client_id)
    year = financial_year or (years[0] if years else None)
    if not year:
        raise HTTPException(status_code=404, detail="No imported history exists for this client yet.")
    return ledger_history(db, client_id, year, ledger)


@router.get("/reports/compare")
def compare(
    client_id: int,
    financial_year: str | None = None,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    years = available_years(db, client_id)
    year = financial_year or (years[0] if years else None)
    if not year:
        raise HTTPException(status_code=404, detail="No imported history exists for this client yet.")
    return {"financial_year": year, "years": compare_years(db, client_id, year)}
