"""Professional accounting services API.

Three audiences share these routes:

* a public visitor (services catalogue and enquiry form),
* practice staff (senior and junior accountants, with different permissions),
* an onboarded client (their own records only).

Every route applies its own role guard. There is no shared "all accounting data"
dependency, because a single guard would be the easiest place to leak a client.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..accounting_catalog import (
    ACCOUNTING_SERVICES,
    BUSINESS_TYPES,
    GST_STATUSES,
    SERVICE_LABELS,
    TURNOVER_RANGES,
)
from ..config import settings
from ..database import get_db
from ..models import (
    AccountingBankImport,
    AccountingBankTransaction,
    AccountingClient,
    AccountingDataExport,
    AccountingDocument,
    AccountingDocumentRequest,
    AccountingEnquiry,
    AccountingIntegrationRun,
    AccountingInvoice,
    AccountingInvoicePayment,
    AccountingMessage,
    AccountingNotification,
    AccountingQuotation,
    AccountingReport,
    AccountingStockItem,
    AccountingTallyBatch,
    AccountingTallyExport,
    AccountingTask,
    AccountingTaskComment,
    AccountingVoucher,
    AuditEvent,
    GstCatalogueChange,
    Product,
    User,
    utcnow,
)
from ..schemas import (
    AccountingClientIn,
    AccountingClientUpdateIn,
    AccountingDocumentIn,
    AccountingEnquiryIn,
    AccountingEnquiryStatusIn,
    AccountingFileIn,
    AccountingQuotationIn,
    AccountingReportIn,
    AccountingTaskIn,
    AccountingTaskUpdateIn,
    AccountingVoucherIn,
    BankFileIn,
    BankMatchIn,
    BankRowsIn,
    BillExtractIn,
    BusinessExportIn,
    BusinessIntegrationLinkIn,
    BusinessTallyExportIn,
    ClientAssignmentIn,
    DocumentRequestIn,
    DocumentReviewIn,
    GstCataloguePermissionIn,
    GstCatalogueUpdateIn,
    GSTPrepareIn,
    PortalMessageIn,
    QuotationDecisionIn,
    QuotationDraftIn,
    QuotationRejectIn,
    QuotationUpdateIn,
    ReportReviewIn,
    ServiceInvoiceIn,
    ServicePaymentIn,
    StockItemIn,
    StockItemUpdateIn,
    TallyDecisionIn,
    TallyExportBatchIn,
    TallyExportIn,
    TallyImportIn,
    TallyImportStatusIn,
    TaskCommentIn,
    TaskReviewIn,
    TaskSubmitIn,
    VoucherBulkIn,
)
from ..security import (
    ACCOUNTANT_ROLES,
    get_current_accountant,
    get_current_customer,
    get_current_junior_accountant,
    get_current_senior_accountant,
    get_current_user,
    hash_password,
    rate_limit,
)
from ..services.accounting import (
    DuplicateVoucher,    bank_import_to_dict,
    bank_transaction_to_dict,
    client_for_customer,
    client_to_dict,
    client_vouchers,
    content_type_for,
    create_voucher,
    days_until,
    decode_data_url,
    document_for_reader,
    document_request_to_dict,
    document_to_dict,
    enquiry_to_dict,
    ensure_client_access,
    financial_year_period,
    import_tally_rows,
    invoice_to_dict,
    junior_has_client,
    message_to_dict,
    next_client_code,
    next_enquiry_reference,
    next_invoice_number,
    next_quotation_number,
    normalise_bank_rows,
    notification_to_dict,
    notify,
    parse_tabular,
    practice_receivables,
    quotation_status,
    quotation_to_dict,
    recompute_import_matches,
    report_to_dict,
    read_bill,
    save_document_file,
    staff_client_filter,
    tally_batch_to_dict,
    tally_export_csv,
    task_for_staff,
    task_to_dict,
    upcoming_deadlines,
    validate_gstin,
    voucher_to_dict,
)
from ..services.accounting_business_view import business_summary, business_transactions
from ..services.business_exports import (
    build_dataset,
    create_tally_export,
    create_workbook,
    export_catalog as export_catalog_for_client,
    export_to_dict as business_export_to_dict,
    preview as export_preview,
)
from ..services.file_store import StoredFileMissing, build_download
from ..services.accounting_integration import (
    integration_summary,
    link_business,
    list_business_options,
    list_client_transactions,
    run_to_dict,
    sync_business_transactions,
    unlink_business,
)
from ..services.accounting_math import (
    financial_year_bounds,
    gst_working,
    month_bounds,
    monthly_summary,
    q2,
)
from ..services.audit import log_audit
from ..services.gst_catalogue import (
    approval_mode as catalogue_approval_mode,
    catalogue_rows,
    change_to_dict as catalogue_change_to_dict,
    export_catalogue_workbook,
    history as catalogue_history,
    pending_changes as catalogue_pending_changes,
    product_to_dict as catalogue_product_to_dict,
    request_change as request_catalogue_change,
)
from ..services.pricing import (
    BENCHMARK_NOTE,
    addons_payload,
    apply_quotation_pricing,
    benchmark_for,
    estimate_payload,
    get_pricing_settings,
    itr_payload,
    normalise_lines,
    settings_payload,
    software_payload,
)
from ..services.quotation_pdf import build_quotation_pdf
from ..services.tally_export import (
    collect_export_data,
    export_catalog,
    export_to_dict,
    mime_for_format,
    prepare_export,
    stock_item_to_dict,
    validate_export,
)

router = APIRouter(prefix="/accounting")
public_router = APIRouter(prefix="/public", tags=["Accounting services"])

OPEN_TASK_STATUSES = ("unassigned", "assigned", "in_progress", "submitted", "changes_requested")
ZERO = Decimal("0.00")


# ---------------------------------------------------------------- helpers


def _quotation_for_customer(db: Session, user: User, quotation_id: int) -> AccountingQuotation:
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    enquiry = quotation.enquiry
    client = client_for_customer(db, user)
    addressed_by_email = enquiry is not None and enquiry.email.lower() == user.email.lower()
    addressed_by_client = client is not None and quotation.client_id == client.id
    if not (addressed_by_email or addressed_by_client):
        raise HTTPException(status_code=403, detail="This quotation is not addressed to your account.")
    return quotation


def _require_customer_client(db: Session, user: User) -> AccountingClient:
    client = client_for_customer(db, user)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail="No accounting engagement is linked to your account yet.",
        )
    return client


def _assignee(db: Session, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    person = db.get(User, user_id)
    if person is None or not person.is_active or person.role not in ACCOUNTANT_ROLES:
        raise HTTPException(status_code=422, detail="Select an active accountant for assignment.")
    return person


def get_current_accountant_or_customer(user: User = Depends(get_current_user)) -> User:
    if user.role not in ACCOUNTANT_ROLES and user.role != "customer":
        raise HTTPException(status_code=403, detail="Document access required.")
    return user


def _client_or_404(db: Session, client_id: int) -> AccountingClient:
    client = db.get(AccountingClient, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client record not found.")
    return client


def _audit(
    db: Session,
    user: User | None,
    action: str,
    *,
    client_id: int | None = None,
    entity: str = "accounting_client",
    entity_id: int | str | None = None,
    detail: dict | None = None,
) -> None:
    payload = dict(detail or {})
    if client_id is not None:
        payload.setdefault("client_id", client_id)
    log_audit(
        db,
        user_id=user.id if user else None,
        actor=user.email if user else "public",
        action=action,
        entity_type=entity,
        entity_id=entity_id if entity_id is not None else client_id,
        detail=payload,
    )


def _serialize_notifications(db: Session, user: User, client_id: int | None = None) -> dict:
    query = db.query(AccountingNotification).filter(AccountingNotification.user_id == user.id)
    if client_id is not None:
        query = query.filter(AccountingNotification.client_id == client_id)
    rows = query.order_by(AccountingNotification.created_at.desc()).limit(50).all()
    unread = (
        db.query(func.count(AccountingNotification.id))
        .filter(
            AccountingNotification.user_id == user.id,
            AccountingNotification.read_at.is_(None),
        )
        .scalar()
        or 0
    )
    return {"items": [notification_to_dict(row) for row in rows], "unread_count": unread}


def _save_upload(
    db: Session,
    payload: AccountingFileIn,
    *,
    title: str | None,
    category: str,
    source: str,
) -> dict:
    raw, suffix = decode_data_url(payload.data_url)
    content_type = content_type_for(suffix)
    stored_name, sha256, size = save_document_file(db, raw, suffix, content_type=content_type)
    return {
        "raw": raw,
        "suffix": suffix,
        "stored_name": stored_name,
        "sha256": sha256,
        "size": size,
        "content_type": content_type,
        "title": title or payload.filename,
        "category": category,
        "source": source,
    }


# ---------------------------------------------------------------- public catalogue


@public_router.get("/services")
def public_services():
    return {
        "services": ACCOUNTING_SERVICES,
        "business_types": BUSINESS_TYPES,
        "turnover_ranges": TURNOVER_RANGES,
        "gst_statuses": GST_STATUSES,
        "process": [
            "Submit an enquiry with your business details.",
            "A senior accountant reviews the scope and volumes.",
            "You receive a customised written quotation.",
            "On acceptance, the engagement is onboarded and assigned.",
            "Work is prepared by an accountant and reviewed before delivery.",
        ],
        "assurances": [
            "No price is published online. Every engagement is quoted after review.",
            "Returns are prepared as working papers; filing happens only through an authorised channel.",
            "Client data is isolated per business and access is limited by role.",
        ],
        "filing_note": (
            "We prepare GST working papers and reports for accountant review. We do not claim to "
            "file returns with GSTN unless an authorised filing integration is connected and used."
        ),
    }


@public_router.get("/pricing")
def public_pricing_catalogue(db: Session = Depends(get_db)):
    settings_row = get_pricing_settings(db)
    return {
        "software": software_payload(db),
        "itr": itr_payload(db),
        "addons": addons_payload(db),
        "accounting": {
            "services": ACCOUNTING_SERVICES,
            "business_types": list(BUSINESS_TYPES),
            "turnover_ranges": list(TURNOVER_RANGES),
            "gst_statuses": list(GST_STATUSES),
            "benchmark_percent": float(settings_row.benchmark_percent),
            "benchmark_note": BENCHMARK_NOTE,
            "quote_validity_days": settings_row.quote_validity_days,
            "tax_rate_percent": float(settings_row.tax_rate_percent),
            "tax_note": settings_row.tax_note,
            "terms": settings_row.terms,
        },
        "disclosures": [
            "Business Manager subscription fees and professional accounting fees are separate.",
            "Accounting quotations are indicative until a senior accountant approves them.",
            "ITR filing is a separate paid service and is not included in bookkeeping packages.",
            "Accepting a quotation does not charge any amount; a separately configured secure payment process applies.",
            "Only appropriately qualified and authorised professionals perform regulated filing or certification work.",
        ],
    }


@public_router.get("/quotation-estimate")
def public_quotation_estimate(
    annual_turnover: Decimal = Query(ge=0, le=Decimal("1000000000000")),
    db: Session = Depends(get_db),
):
    settings_row = get_pricing_settings(db)
    return {
        **estimate_payload(db, annual_turnover),
        "tax_rate_percent": float(settings_row.tax_rate_percent),
        "tax_note": settings_row.tax_note,
        "validity_days": settings_row.quote_validity_days,
    }


@public_router.post(
    "/enquiries",
    status_code=201,
    dependencies=[Depends(rate_limit("accounting_enquiry", 5, 60))],
)
def create_enquiry(payload: AccountingEnquiryIn, db: Session = Depends(get_db)):
    reference = next_enquiry_reference(db)
    benchmark = benchmark_for(db, payload.annual_turnover)
    enquiry = AccountingEnquiry(
        reference=reference,
        business_name=payload.business_name.strip(),
        contact_name=payload.contact_name.strip(),
        email=payload.email.lower(),
        phone=payload.phone,
        business_type=payload.business_type,
        turnover_range=payload.turnover_range,
        gst_status=payload.gst_status,
        services=list(dict.fromkeys(payload.services)),
        monthly_transactions=payload.monthly_transactions,
        requirements=payload.requirements,
        annual_turnover=payload.annual_turnover,
        bank_accounts=payload.bank_accounts,
        payroll_required=payload.payroll_required,
        inventory_required=payload.inventory_required,
        financial_year=payload.financial_year,
        benchmark_annual=benchmark,
        status="new",
        source="website",
    )
    db.add(enquiry)
    db.flush()
    _audit(
        db,
        None,
        "accounting.enquiry_received",
        entity="accounting_enquiry",
        entity_id=enquiry.id,
        detail={
            "reference": reference,
            "services": enquiry.services,
            "benchmark_annual": float(benchmark) if benchmark is not None else None,
        },
    )
    db.commit()
    return {
        "reference": reference,
        "status": enquiry.status,
        "estimate": estimate_payload(db, payload.annual_turnover),
        "message": (
            "Enquiry received. A senior accountant will review the scope and send a customised "
            "quotation. No engagement or fee is confirmed until you accept an approved written "
            "quotation, and accepting it does not charge any amount."
        ),
    }


# ---------------------------------------------------------------- senior dashboard


@router.get("/senior/overview")
def senior_overview(
    client_id: int | None = None,
    financial_year: str | None = None,
    status: str | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    today = date.today()
    fy = financial_year or financial_year_period(today)
    clients = db.query(AccountingClient).all()
    tasks_query = db.query(AccountingTask)
    if client_id is not None:
        tasks_query = tasks_query.filter(AccountingTask.client_id == client_id)
    if status:
        tasks_query = tasks_query.filter(AccountingTask.status == status)
    tasks = tasks_query.all()
    counts = Counter(task.status for task in tasks)
    overdue = [
        task
        for task in tasks
        if task.due_date and task.due_date < today and task.status not in ("approved", "delivered", "cancelled")
    ]
    enquiries_new = (
        db.query(func.count(AccountingEnquiry.id))
        .filter(AccountingEnquiry.status.in_(("new", "contacted")))
        .scalar()
        or 0
    )
    pending_quotations = (
        db.query(func.count(AccountingQuotation.id))
        .filter(AccountingQuotation.status == "sent")
        .scalar()
        or 0
    )

    juniors = (
        db.query(User)
        .filter(User.role == "junior_accountant", User.is_active.is_(True))
        .order_by(User.full_name)
        .all()
    )
    workload_rows = []
    for junior in juniors:
        open_tasks = (
            db.query(func.count(AccountingTask.id))
            .filter(
                AccountingTask.assigned_to_user_id == junior.id,
                AccountingTask.status.in_(OPEN_TASK_STATUSES),
            )
            .scalar()
            or 0
        )
        clients_count = (
            db.query(func.count(AccountingClient.id))
            .filter(AccountingClient.assigned_junior_user_id == junior.id)
            .scalar()
            or 0
        )
        workload_rows.append(
            {
                "user_id": junior.id,
                "name": junior.full_name,
                "open_tasks": open_tasks,
                "clients": clients_count,
                "submitted": (
                    db.query(func.count(AccountingTask.id))
                    .filter(
                        AccountingTask.assigned_to_user_id == junior.id,
                        AccountingTask.status == "submitted",
                    )
                    .scalar()
                    or 0
                ),
            }
        )

    vouchers = db.query(AccountingVoucher).all()
    if client_id is not None:
        vouchers = [v for v in vouchers if v.client_id == client_id]
    months: list[str] = []
    cursor = today.replace(day=1)
    for _ in range(6):
        months.append(f"{cursor:%Y-%m}")
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
    series = []
    for period in months:
        start, end = month_bounds(period)
        rows = [v for v in vouchers if start <= v.voucher_date <= end]
        series.append(
            {
                "period": period,
                "sales": q2(sum((v.taxable_value for v in rows if v.voucher_type == "sale"), ZERO)),
                "purchases": q2(sum((v.taxable_value for v in rows if v.voucher_type == "purchase"), ZERO)),
            }
        )

    recent_events = (
        db.query(AuditEvent)
        .filter(AuditEvent.action.like("accounting.%"))
        .order_by(AuditEvent.created_at.desc())
        .limit(12)
        .all()
    )

    return {
        "financial_year": fy,
        "filters": {"client_id": client_id, "status": status},
        "clients": {
            "total": len(clients),
            "active": sum(1 for c in clients if c.status == "active"),
            "onboarding": sum(1 for c in clients if c.status == "onboarding"),
            "unassigned_junior": sum(1 for c in clients if not c.assigned_junior_user_id),
        },
        "enquiries": {
            "new": enquiries_new,
            "total": db.query(func.count(AccountingEnquiry.id)).scalar() or 0,
            "pending_quotations": pending_quotations,
        },
        "tasks": {
            "total": len(tasks),
            "unassigned": counts.get("unassigned", 0),
            "assigned": counts.get("assigned", 0),
            "in_progress": counts.get("in_progress", 0),
            "submitted": counts.get("submitted", 0),
            "changes_requested": counts.get("changes_requested", 0),
            "approved": counts.get("approved", 0),
            "delivered": counts.get("delivered", 0),
            "overdue": len(overdue),
        },
        "awaiting_review": counts.get("submitted", 0),
        "work_in_progress": counts.get("in_progress", 0) + counts.get("assigned", 0),
        "upcoming_deadlines": upcoming_deadlines(tasks),
        "overdue_tasks": [task_to_dict(task) for task in overdue[:10]],
        "workload": workload_rows,
        "billing": practice_receivables(db, client_id),
        "performance": {
            "completed_this_fy": sum(
                1
                for task in tasks
                if task.status in ("approved", "delivered")
                and (task.reviewed_at or task.updated_at).date()
                >= financial_year_bounds(fy)[0]
            ),
            "on_time": sum(
                1
                for task in tasks
                if task.status in ("approved", "delivered")
                and task.due_date
                and (task.reviewed_at or task.updated_at).date() <= task.due_date
            ),
        },
        "monthly_series": series,
        "recent_activity": [
            {
                "id": event.id,
                "action": event.action,
                "actor": event.actor,
                "detail": event.detail,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in recent_events
        ],
    }


# ---------------------------------------------------------------- enquiries & quotations


@router.get("/senior/enquiries")
def list_enquiries(
    status: str | None = None,
    search: str | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingEnquiry)
    if status:
        query = query.filter(AccountingEnquiry.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            AccountingEnquiry.business_name.ilike(pattern)
            | AccountingEnquiry.contact_name.ilike(pattern)
            | AccountingEnquiry.email.ilike(pattern)
            | AccountingEnquiry.reference.ilike(pattern)
        )
    enquiries = query.order_by(AccountingEnquiry.created_at.desc()).limit(200).all()
    quotations = db.query(AccountingQuotation).all()
    by_enquiry: dict[int, list[dict]] = {}
    for quotation in quotations:
        if quotation.enquiry_id:
            by_enquiry.setdefault(quotation.enquiry_id, []).append(quotation_to_dict(quotation))
    return {
        "items": [
            {**enquiry_to_dict(enquiry, internal=True), "quotations": by_enquiry.get(enquiry.id, [])}
            for enquiry in enquiries
        ],
        "statuses": ["new", "contacted", "quoted", "quote_accepted", "onboarded", "declined"],
    }


@router.patch("/senior/enquiries/{enquiry_id}")
def update_enquiry(
    enquiry_id: int,
    payload: AccountingEnquiryStatusIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    enquiry = db.get(AccountingEnquiry, enquiry_id)
    if enquiry is None:
        raise HTTPException(status_code=404, detail="Enquiry not found.")
    enquiry.status = payload.status
    if payload.internal_notes is not None:
        enquiry.internal_notes = payload.internal_notes
    enquiry.assigned_senior_user_id = enquiry.assigned_senior_user_id or user.id
    _audit(db, user, "accounting.enquiry_updated", entity="accounting_enquiry", entity_id=enquiry.id, detail={"status": payload.status})
    db.commit()
    return enquiry_to_dict(enquiry, internal=True)


def _create_quotation_record(
    db: Session,
    user: User,
    payload: QuotationDraftIn,
    *,
    source: str = "workspace",
) -> AccountingQuotation:
    enquiry = db.get(AccountingEnquiry, payload.enquiry_id) if payload.enquiry_id else None
    if payload.enquiry_id and enquiry is None:
        raise HTTPException(status_code=404, detail="Enquiry not found.")
    client = db.get(AccountingClient, payload.client_id) if payload.client_id else None
    if payload.client_id and client is None:
        raise HTTPException(status_code=404, detail="Client record not found.")
    if enquiry is None and client is None:
        raise HTTPException(
            status_code=422,
            detail="A quotation must be linked to an enquiry or an existing client.",
        )
    lines = normalise_lines(payload.line_items)
    if not lines:
        raise HTTPException(status_code=422, detail="Add at least one service or charge line.")
    settings_row = get_pricing_settings(db)
    annual_turnover = payload.annual_turnover
    if annual_turnover is None and enquiry is not None:
        annual_turnover = enquiry.annual_turnover
    validity_days = payload.validity_days or settings_row.quote_validity_days
    quotation = AccountingQuotation(
        number=next_quotation_number(db),
        enquiry_id=enquiry.id if enquiry is not None else None,
        client_id=client.id if client is not None else None,
        prepared_by_user_id=user.id,
        currency="INR",
        amount=Decimal("0.00"),
        billing_cadence=payload.payment_frequency,
        scope=[],
        terms=payload.terms or settings_row.terms,
        valid_until=date.today() + timedelta(days=validity_days),
        status="draft",
        annual_turnover=annual_turnover,
        benchmark_annual=benchmark_for(db, annual_turnover),
        validity_days=validity_days,
        tax_rate_percent=settings_row.tax_rate_percent,
        tax_note=settings_row.tax_note,
    )
    apply_quotation_pricing(
        quotation,
        lines=lines,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        payment_frequency=payload.payment_frequency,
        validity_days=validity_days,
        settings_row=settings_row,
    )
    db.add(quotation)
    db.flush()
    if enquiry is not None:
        enquiry.assigned_senior_user_id = enquiry.assigned_senior_user_id or user.id
        if enquiry.status == "new":
            enquiry.status = "contacted"
    _audit(
        db,
        user,
        "accounting.quotation_drafted",
        entity="accounting_quotation",
        entity_id=quotation.id,
        detail={
            "source": source,
            "enquiry_id": quotation.enquiry_id,
            "client_id": quotation.client_id,
            "total_annual": float(quotation.total_annual),
        },
    )
    return quotation


@router.post("/senior/quotations", status_code=201)
def create_quotation_workspace(
    payload: QuotationDraftIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = _create_quotation_record(db, user, payload, source="quotation_workspace")
    db.commit()
    db.refresh(quotation)
    return quotation_to_dict(quotation)


@router.post("/senior/enquiries/{enquiry_id}/quotations", status_code=201)
def create_quotation(
    enquiry_id: int,
    payload: AccountingQuotationIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    """Legacy single-amount quotation entry.

    The record is created as a draft: a second, explicit approval action is required before
    it can be sent, so every final price carries a senior accountant's approval.
    """
    enquiry = db.get(AccountingEnquiry, enquiry_id)
    if enquiry is None:
        raise HTTPException(status_code=404, detail="Enquiry not found.")
    unknown = [row.service for row in payload.scope if row.service not in SERVICE_LABELS]
    if unknown:
        raise HTTPException(status_code=422, detail="The quotation includes an unknown service.")
    lines = []
    for index, row in enumerate(payload.scope):
        lines.append(
            {
                "kind": "service",
                "key": row.service,
                "label": SERVICE_LABELS[row.service],
                "description": row.description,
                "service": row.service,
                "amount": payload.amount if index == 0 else "0",
                "cadence": "annual",
            }
        )
    draft = QuotationDraftIn(
        enquiry_id=enquiry.id,
        line_items=lines,
        payment_frequency=payload.billing_cadence,
        terms=payload.terms,
        validity_days=None,
    )
    quotation = _create_quotation_record(db, user, draft, source="enquiry_page")
    validity_days = max((payload.valid_until - date.today()).days, 1) if payload.valid_until else None
    if validity_days is not None:
        quotation.valid_until = payload.valid_until
        quotation.validity_days = validity_days
    db.commit()
    db.refresh(quotation)
    return quotation_to_dict(quotation)


@router.get("/senior/quotations")
def list_quotations(
    status: str | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingQuotation)
    if status:
        query = query.filter(AccountingQuotation.status == status)
    rows = query.order_by(AccountingQuotation.created_at.desc()).limit(200).all()
    return {"items": [quotation_to_dict(row) for row in rows]}


@router.post("/senior/quotations/{quotation_id}/decision")
def record_quotation_decision(
    quotation_id: int,
    payload: QuotationDecisionIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    if quotation_status(quotation) != "sent":
        raise HTTPException(
            status_code=409,
            detail="Only a sent quotation can have a customer decision recorded.",
        )
    quotation.status = payload.decision
    quotation.responded_at = utcnow()
    quotation.response_note = payload.note
    if payload.decision == "accepted":
        quotation.accepted_at = utcnow()
    if quotation.enquiry is not None:
        quotation.enquiry.status = "quote_accepted" if payload.decision == "accepted" else "declined"
    _audit(
        db,
        user,
        f"accounting.quotation_{payload.decision}",
        entity="accounting_quotation",
        entity_id=quotation.id,
        detail={"note": payload.note, "recorded_by_staff": True},
    )
    db.commit()
    return quotation_to_dict(quotation)


@router.get("/senior/quotation-workspace")
def quotation_workspace(
    status: str | None = None,
    search: str | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    enquiries_query = db.query(AccountingEnquiry)
    if search:
        pattern = f"%{search.strip()}%"
        enquiries_query = enquiries_query.filter(
            AccountingEnquiry.business_name.ilike(pattern)
            | AccountingEnquiry.contact_name.ilike(pattern)
            | AccountingEnquiry.email.ilike(pattern)
            | AccountingEnquiry.reference.ilike(pattern)
        )
    enquiries = enquiries_query.order_by(AccountingEnquiry.created_at.desc()).limit(200).all()
    quotations_query = db.query(AccountingQuotation)
    if search:
        pattern = f"%{search.strip()}%"
        quotations_query = quotations_query.filter(
            AccountingQuotation.number.ilike(pattern)
            | AccountingQuotation.enquiry.has(AccountingEnquiry.business_name.ilike(pattern))
        )
    all_quotations = (
        quotations_query.order_by(AccountingQuotation.created_at.desc()).limit(300).all()
    )
    quotations = [
        row for row in all_quotations if not status or quotation_status(row) == status
    ]

    by_enquiry: dict[int, list[dict]] = {}
    for quotation in all_quotations:
        if quotation.enquiry_id:
            by_enquiry.setdefault(quotation.enquiry_id, []).append(quotation_to_dict(quotation))

    counts = Counter(quotation_status(row) for row in all_quotations)
    pending_statuses = ("draft", "approved", "sent")
    accepted_rows = [row for row in all_quotations if quotation_status(row) == "accepted"]
    return {
        "counts": {
            "new_requests": sum(1 for row in enquiries if row.status in ("new", "contacted")),
            "draft": counts.get("draft", 0),
            "approved": counts.get("approved", 0),
            "sent": counts.get("sent", 0),
            "accepted": counts.get("accepted", 0),
            "declined": counts.get("declined", 0),
            "rejected": counts.get("rejected", 0),
            "expired": counts.get("expired", 0),
            "total": len(quotations),
        },
        "pipeline": {
            "pending_value": float(
                sum(
                    (
                        Decimal(row.total_annual)
                        for row in all_quotations
                        if quotation_status(row) in pending_statuses
                    ),
                    Decimal("0"),
                )
            ),
            "accepted_value": float(
                sum((Decimal(row.total_annual) for row in accepted_rows), Decimal("0"))
            ),
        },
        "requests": [
            {
                **enquiry_to_dict(enquiry, internal=True),
                "estimate": estimate_payload(db, enquiry.annual_turnover),
                "quotations": by_enquiry.get(enquiry.id, []),
            }
            for enquiry in enquiries
        ],
        "quotations": [
            quotation_to_dict(row)
            for row in quotations
            if not status or quotation_status(row) == status
        ],
        "catalogue": {
            "services": ACCOUNTING_SERVICES,
            "addons": addons_payload(db),
            "business_types": list(BUSINESS_TYPES),
            "gst_statuses": list(GST_STATUSES),
            "turnover_ranges": list(TURNOVER_RANGES),
            "benchmark_note": BENCHMARK_NOTE,
        },
        "settings": settings_payload(get_pricing_settings(db)),
        "statuses": [
            "draft",
            "approved",
            "sent",
            "accepted",
            "declined",
            "rejected",
            "expired",
        ],
    }


@router.get("/senior/quotations/{quotation_id}")
def get_quotation(
    quotation_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    return quotation_to_dict(quotation)


@router.patch("/senior/quotations/{quotation_id}")
def update_quotation(
    quotation_id: int,
    payload: QuotationUpdateIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    if quotation.status in ("sent", "accepted", "declined"):
        raise HTTPException(
            status_code=409,
            detail="A sent or decided quotation cannot be edited. Create a revision instead.",
        )
    if quotation.status == "rejected":
        raise HTTPException(status_code=409, detail="A rejected quotation cannot be edited.")
    settings_row = get_pricing_settings(db)
    lines = normalise_lines(payload.line_items) if payload.line_items is not None else list(
        quotation.line_items or []
    )
    if not lines:
        raise HTTPException(status_code=422, detail="Add at least one service or charge line.")
    annual_turnover = (
        payload.annual_turnover if payload.annual_turnover is not None else quotation.annual_turnover
    )
    discount_type = payload.discount_type or quotation.discount_type
    discount_value = (
        payload.discount_value if payload.discount_value is not None else quotation.discount_value
    )
    payment_frequency = payload.payment_frequency or quotation.payment_frequency
    validity_days = payload.validity_days or quotation.validity_days
    quotation.annual_turnover = annual_turnover
    quotation.benchmark_annual = benchmark_for(db, annual_turnover)
    quotation.discount_note = (
        payload.discount_note if payload.discount_note is not None else quotation.discount_note
    )
    if payload.terms is not None:
        quotation.terms = payload.terms
    apply_quotation_pricing(
        quotation,
        lines=lines,
        discount_type=discount_type,
        discount_value=discount_value,
        payment_frequency=payment_frequency,
        validity_days=validity_days,
        settings_row=settings_row,
    )
    if quotation.validity_days:
        quotation.valid_until = date.today() + timedelta(days=quotation.validity_days)
    if quotation.status == "approved":
        quotation.status = "draft"
        quotation.approved_at = None
        quotation.approved_by_user_id = None
    _audit(
        db,
        user,
        "accounting.quotation_updated",
        entity="accounting_quotation",
        entity_id=quotation.id,
        detail={"total_annual": float(quotation.total_annual)},
    )
    db.commit()
    db.refresh(quotation)
    return quotation_to_dict(quotation)


@router.post("/senior/quotations/{quotation_id}/approve")
def approve_quotation(
    quotation_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    if quotation.status == "approved":
        return quotation_to_dict(quotation)
    if quotation.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only a draft quotation can be approved.",
        )
    if Decimal(quotation.total_annual) <= 0:
        raise HTTPException(
            status_code=422,
            detail="Set the service or charge amounts before approving the quotation.",
        )
    quotation.status = "approved"
    quotation.approved_at = utcnow()
    quotation.approved_by_user_id = user.id
    _audit(
        db,
        user,
        "accounting.quotation_approved",
        entity="accounting_quotation",
        entity_id=quotation.id,
        detail={"total_annual": float(quotation.total_annual), "number": quotation.number},
    )
    db.commit()
    db.refresh(quotation)
    return quotation_to_dict(quotation)


@router.post("/senior/quotations/{quotation_id}/reject")
def reject_quotation(
    quotation_id: int,
    payload: QuotationRejectIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    if quotation.status in ("sent", "accepted", "declined", "rejected"):
        raise HTTPException(status_code=409, detail="This quotation can no longer be rejected.")
    quotation.status = "rejected"
    quotation.rejected_at = utcnow()
    quotation.rejected_by_user_id = user.id
    quotation.rejection_note = payload.note
    _audit(
        db,
        user,
        "accounting.quotation_rejected",
        entity="accounting_quotation",
        entity_id=quotation.id,
        detail={"note": payload.note, "number": quotation.number},
    )
    db.commit()
    db.refresh(quotation)
    return quotation_to_dict(quotation)


@router.post("/senior/quotations/{quotation_id}/send")
def send_quotation(
    quotation_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    if quotation.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="A quotation must be approved by a senior accountant before it is sent.",
        )
    quotation.status = "sent"
    quotation.sent_at = utcnow()
    if quotation.enquiry is not None:
        quotation.enquiry.status = "quoted"
    _audit(
        db,
        user,
        "accounting.quotation_sent",
        entity="accounting_quotation",
        entity_id=quotation.id,
        detail={"number": quotation.number, "total_annual": float(quotation.total_annual)},
    )
    db.commit()
    db.refresh(quotation)
    return quotation_to_dict(quotation)


@router.get("/senior/quotations/{quotation_id}/pdf")
def download_quotation_pdf(
    quotation_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    quotation = db.get(AccountingQuotation, quotation_id)
    if quotation is None:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    content = build_quotation_pdf(
        quotation,
        approved_by_name=quotation.approved_by.full_name if quotation.approved_by else None,
        prepared_by_name=quotation.prepared_by.full_name if quotation.prepared_by else None,
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{quotation.number}.pdf"'},
    )


# ---------------------------------------------------------------- accountants & clients


@router.get("/senior/accountants")
def list_accountants(
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    staff = (
        db.query(User)
        .filter(User.role.in_(ACCOUNTANT_ROLES), User.is_active.is_(True))
        .order_by(User.role, User.full_name)
        .all()
    )
    rows = []
    for person in staff:
        rows.append(
            {
                "id": person.id,
                "name": person.full_name,
                "email": person.email,
                "role": person.role,
                "open_tasks": db.query(func.count(AccountingTask.id))
                .filter(
                    AccountingTask.assigned_to_user_id == person.id,
                    AccountingTask.status.in_(OPEN_TASK_STATUSES),
                )
                .scalar()
                or 0,
                "clients": db.query(func.count(AccountingClient.id))
                .filter(AccountingClient.assigned_junior_user_id == person.id)
                .scalar()
                or 0,
            }
        )
    return {"items": rows}


@router.get("/senior/clients")
def list_clients(
    search: str | None = None,
    status: str | None = None,
    financial_year: str | None = None,
    assigned_junior_user_id: int | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingClient)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            AccountingClient.business_name.ilike(pattern)
            | AccountingClient.code.ilike(pattern)
            | AccountingClient.email.ilike(pattern)
            | AccountingClient.contact_name.ilike(pattern)
        )
    if status:
        query = query.filter(AccountingClient.status == status)
    if financial_year:
        query = query.filter(AccountingClient.financial_year == financial_year)
    if assigned_junior_user_id is not None:
        query = query.filter(AccountingClient.assigned_junior_user_id == assigned_junior_user_id)
    clients = query.order_by(AccountingClient.business_name).limit(300).all()
    return {"items": [client_to_dict(db, client) for client in clients]}


@router.post("/senior/clients", status_code=201)
def onboard_client(
    payload: AccountingClientIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    email = payload.email.lower()
    existing_user = db.query(User).filter(User.email == email).one_or_none()
    if existing_user is not None and existing_user.role != "customer":
        raise HTTPException(
            status_code=409,
            detail="This email belongs to another account type and cannot be used as a client login.",
        )
    if existing_user is not None:
        already = (
            db.query(AccountingClient)
            .filter(AccountingClient.customer_user_id == existing_user.id)
            .one_or_none()
        )
        if already is not None:
            raise HTTPException(status_code=409, detail="This customer is already linked to a client record.")

    junior = _assignee(db, payload.assigned_junior_user_id)
    if junior is not None and junior.role != "junior_accountant":
        raise HTTPException(status_code=422, detail="Client assignment must target a junior accountant.")

    customer_user_id: int | None = existing_user.id if existing_user else None
    portal_access = "linked" if existing_user else "not_created"
    if existing_user is None and payload.portal_password:
        created = User(
            email=email,
            password_hash=hash_password(payload.portal_password),
            full_name=payload.contact_name,
            role="customer",
            is_demo=False,
            is_active=True,
        )
        db.add(created)
        db.flush()
        customer_user_id = created.id
        portal_access = "created"

    client = AccountingClient(
        code=next_client_code(db),
        business_name=payload.business_name.strip(),
        contact_name=payload.contact_name.strip(),
        email=email,
        phone=payload.phone,
        business_type=payload.business_type,
        turnover_range=payload.turnover_range,
        gst_status=payload.gst_status,
        gstin=validate_gstin(payload.gstin),
        pan_last4=payload.pan_last4,
        financial_year=payload.financial_year,
        service_package=payload.service_package,
        status="onboarding",
        customer_user_id=customer_user_id,
        senior_accountant_user_id=user.id,
        assigned_junior_user_id=junior.id if junior else None,
        onboarded_at=utcnow(),
        notes=payload.notes,
    )
    db.add(client)
    db.flush()

    if payload.enquiry_id:
        enquiry = db.get(AccountingEnquiry, payload.enquiry_id)
        if enquiry is not None:
            enquiry.status = "onboarded"
            enquiry.assigned_senior_user_id = user.id
    if payload.quotation_id:
        quotation = db.get(AccountingQuotation, payload.quotation_id)
        if quotation is not None:
            quotation.client_id = client.id
            quotation.status = "accepted"
            quotation.accepted_at = quotation.accepted_at or utcnow()

    if customer_user_id:
        notify(
            db,
            customer_user_id,
            kind="welcome",
            title="Accounting engagement created",
            body=f"{client.business_name} is now onboarded. Upload documents and track work from your portal.",
            client_id=client.id,
        )
    if junior is not None:
        notify(
            db,
            junior.id,
            kind="client_assigned",
            title="Client assigned",
            body=f"{client.business_name} was assigned to you.",
            client_id=client.id,
        )
    _audit(db, user, "accounting.client_created", client_id=client.id, detail={"code": client.code, "portal_access": portal_access})
    db.commit()
    db.refresh(client)
    return {
        "client": client_to_dict(db, client, detail=True),
        "portal_access": portal_access,
        "portal_note": (
            "A customer login was created for this email."
            if portal_access == "created"
            else (
                "The existing customer login can now see this engagement."
                if portal_access == "linked"
                else "No portal login was created. Provide a portal password to create one."
            )
        ),
    }


@router.get("/senior/clients/{client_id}")
def get_client(
    client_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    tasks = (
        db.query(AccountingTask)
        .filter(AccountingTask.client_id == client.id)
        .order_by(AccountingTask.created_at.desc())
        .all()
    )
    documents = (
        db.query(AccountingDocument)
        .filter(AccountingDocument.client_id == client.id)
        .order_by(AccountingDocument.created_at.desc())
        .all()
    )
    reports = (
        db.query(AccountingReport)
        .filter(AccountingReport.client_id == client.id)
        .order_by(AccountingReport.created_at.desc())
        .all()
    )
    invoices = (
        db.query(AccountingInvoice)
        .filter(AccountingInvoice.client_id == client.id)
        .order_by(AccountingInvoice.issue_date.desc())
        .all()
    )
    vouchers = client_vouchers(db, client.id)
    return {
        "client": client_to_dict(db, client, detail=True),
        "tasks": [task_to_dict(task, comments=True) for task in tasks],
        "documents": [document_to_dict(doc) for doc in documents],
        "document_requests": [
            document_request_to_dict(row)
            for row in db.query(AccountingDocumentRequest)
            .filter(AccountingDocumentRequest.client_id == client.id)
            .order_by(AccountingDocumentRequest.created_at.desc())
        ],
        "reports": [report_to_dict(row) for row in reports],
        "invoices": [invoice_to_dict(row) for row in invoices],
        "vouchers": {
            "count": len(vouchers),
            "sales": q2(sum((v.taxable_value for v in vouchers if v.voucher_type == "sale"), ZERO)),
            "purchases": q2(sum((v.taxable_value for v in vouchers if v.voucher_type == "purchase"), ZERO)),
            "recent": [voucher_to_dict(v) for v in vouchers[-10:]][::-1],
        },
        "messages": [
            message_to_dict(row)
            for row in db.query(AccountingMessage)
            .filter(AccountingMessage.client_id == client.id)
            .order_by(AccountingMessage.created_at)
        ],
        "integration": integration_summary(db, client),
    }


@router.patch("/senior/clients/{client_id}")
def update_client(
    client_id: int,
    payload: AccountingClientUpdateIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    data = payload.model_dump(exclude_unset=True)
    if "gstin" in data:
        data["gstin"] = validate_gstin(data["gstin"])
    if "pan_last4" in data and data["pan_last4"]:
        data["pan_last4"] = data["pan_last4"].upper()
    for field, value in data.items():
        setattr(client, field, value)
    _audit(db, user, "accounting.client_updated", client_id=client.id, detail={"fields": sorted(data.keys())})
    db.commit()
    return client_to_dict(db, client, detail=True)


@router.post("/senior/clients/{client_id}/assign")
def assign_client(
    client_id: int,
    payload: ClientAssignmentIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    junior = _assignee(db, payload.junior_user_id)
    if junior is not None and junior.role != "junior_accountant":
        raise HTTPException(status_code=422, detail="Clients can only be assigned to junior accountants.")
    client.assigned_junior_user_id = junior.id if junior else None
    if junior is not None:
        notify(
            db,
            junior.id,
            kind="client_assigned",
            title="Client assigned",
            body=f"{client.business_name} is now assigned to you.",
            client_id=client.id,
        )
    _audit(db, user, "accounting.client_assigned", client_id=client.id, detail={"junior_user_id": junior.id if junior else None})
    db.commit()
    return client_to_dict(db, client, detail=True)


# ---------------------------------------------------------------- business integration


@router.get("/senior/business-options")
def list_business_link_options(
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    return {"items": list_business_options(db)}


@router.get("/senior/clients/{client_id}/integration")
def get_client_integration(
    client_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    return integration_summary(db, client)


@router.post("/senior/clients/{client_id}/integration/link")
def link_client_business(
    client_id: int,
    payload: BusinessIntegrationLinkIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    previous = client.business_profile_id
    link_business(db, client, payload.business_profile_id)
    _audit(
        db,
        user,
        "accounting.integration_linked",
        client_id=client.id,
        entity="accounting_client",
        detail={
            "business_profile_id": client.business_profile_id,
            "previous_business_profile_id": previous,
        },
    )
    db.commit()
    return integration_summary(db, client)


@router.post("/senior/clients/{client_id}/integration/unlink")
def unlink_client_business(
    client_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    previous = unlink_business(db, client)
    _audit(
        db,
        user,
        "accounting.integration_unlinked",
        client_id=client.id,
        entity="accounting_client",
        detail={"business_profile_id": previous},
    )
    db.commit()
    return integration_summary(db, client)


@router.post("/senior/clients/{client_id}/integration/sync")
def sync_client_integration(
    client_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    run = sync_business_transactions(db, client, user)
    _audit(
        db,
        user,
        "accounting.integration_synced",
        client_id=client.id,
        entity="accounting_integration_run",
        entity_id=run.id,
        detail={
            "business_profile_id": client.business_profile_id,
            "discovered": run.discovered,
            "created": run.created_count,
            "updated": run.updated_count,
            "skipped": run.skipped_count,
            "errors": run.error_count,
            "status": run.status,
        },
    )
    db.commit()
    return {"integration": integration_summary(db, client), "run": run_to_dict(run)}


@router.get("/senior/clients/{client_id}/integration/transactions")
def list_client_integration_transactions(
    client_id: int,
    status: str | None = None,
    source_type: str | None = None,
    transaction_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    return list_client_transactions(
        db,
        client.id,
        status=status,
        source_type=source_type,
        transaction_type=transaction_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/senior/clients/{client_id}/integration/runs")
def list_client_integration_runs(
    client_id: int,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, client_id)
    rows = (
        db.query(AccountingIntegrationRun)
        .filter(AccountingIntegrationRun.client_id == client.id)
        .order_by(AccountingIntegrationRun.created_at.desc(), AccountingIntegrationRun.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [run_to_dict(row) for row in rows]}


@router.get("/junior/clients/{client_id}/integration")
def get_junior_client_integration(
    client_id: int,
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    return integration_summary(db, client)


@router.get("/junior/clients/{client_id}/integration/transactions")
def list_junior_client_integration_transactions(
    client_id: int,
    status: str | None = None,
    source_type: str | None = None,
    transaction_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    return list_client_transactions(
        db,
        client.id,
        status=status,
        source_type=source_type,
        transaction_type=transaction_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------- business records workspace


def _business_summary_for(db: Session, user: User, client_id: int, days: int) -> dict:
    client = ensure_client_access(db, user, client_id)
    return business_summary(db, client, days=days)


def _business_transactions_for(
    db: Session,
    user: User,
    client_id: int,
    *,
    transaction_type: str | None,
    search: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> dict:
    client = ensure_client_access(db, user, client_id)
    return business_transactions(
        db,
        client,
        transaction_type=transaction_type,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/senior/clients/{client_id}/business/summary")
def senior_business_summary(
    client_id: int,
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    return _business_summary_for(db, user, client_id, days)


@router.get("/junior/clients/{client_id}/business/summary")
def junior_business_summary(
    client_id: int,
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    return _business_summary_for(db, user, client_id, days)


@router.get("/senior/clients/{client_id}/business/transactions")
def senior_business_transactions(
    client_id: int,
    transaction_type: Literal["sale", "receipt", "refund", "expense"] | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    return _business_transactions_for(
        db,
        user,
        client_id,
        transaction_type=transaction_type,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/junior/clients/{client_id}/business/transactions")
def junior_business_transactions(
    client_id: int,
    transaction_type: Literal["sale", "receipt", "refund", "expense"] | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    return _business_transactions_for(
        db,
        user,
        client_id,
        transaction_type=transaction_type,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


# ------------------------------------------------------ GST catalogue management


def _catalogue_owner_for(db: Session, client: AccountingClient) -> User:
    profile = client.business_profile
    if client.business_profile_id is None or profile is None:
        raise HTTPException(
            status_code=409,
            detail="No Business Manager business is linked to this engagement.",
        )
    owner_id = profile.user_id or profile.owner_id
    owner = db.get(User, owner_id) if owner_id else None
    if owner is None:
        raise HTTPException(status_code=409, detail="The linked business owner was not found.")
    return owner


def _catalogue_payload(db: Session, client: AccountingClient, search: str | None) -> dict:
    owner = _catalogue_owner_for(db, client)
    items = catalogue_rows(db, owner.id, search=search)
    pending = catalogue_pending_changes(db, owner.id)
    return {
        "linked": True,
        "client_id": client.id,
        "business": {
            "business_name": owner.profile.business_name if owner.profile else client.business_name,
            "gstin": owner.profile.gstin if owner.profile else client.gstin,
            "currency": owner.profile.currency if owner.profile else "INR",
        },
        "items": items,
        "count": len(items),
        "approval_mode": catalogue_approval_mode(db, owner),
        "pending_changes": pending,
        "pending_count": len(pending),
        "can_edit": client.gst_catalogue_access,
        "note": (
            "GST rates are effective-dated. Saving a change only affects new invoices; "
            "issued invoices keep their original line-level tax snapshot."
        ),
    }


@router.get("/senior/clients/{client_id}/gst-catalogue")
def senior_gst_catalogue(
    client_id: int,
    search: str | None = Query(default=None, max_length=100),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    return _catalogue_payload(db, client, search)


@router.get("/junior/clients/{client_id}/gst-catalogue")
def junior_gst_catalogue(
    client_id: int,
    search: str | None = Query(default=None, max_length=100),
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    payload = _catalogue_payload(db, client, search)
    payload["can_edit"] = False
    return payload


@router.patch("/senior/clients/{client_id}/gst-catalogue/{product_id}")
def senior_update_gst_catalogue(
    client_id: int,
    product_id: int,
    payload: GstCatalogueUpdateIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    if not client.gst_catalogue_access:
        raise HTTPException(
            status_code=403,
            detail="GST catalogue editing is not granted for this client by the business owner.",
        )
    owner = _catalogue_owner_for(db, client)
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == owner.id)
        .one_or_none()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Catalogue item not found.")
    change = request_catalogue_change(
        db,
        product=product,
        actor=user,
        role="accountant",
        gst_rate=payload.gst_rate,
        hsn_sac=payload.hsn_sac,
        item_type=payload.item_type,
        hsn_verified=payload.hsn_verified,
        effective_from=payload.effective_from,
        reason=payload.reason,
    )
    return {
        "item": catalogue_product_to_dict(db, product),
        "change": catalogue_change_to_dict(db, change),
        "message": (
            "Change proposed. The business owner must approve it before it applies."
            if change.status == "pending_approval"
            else "GST catalogue updated. New invoices will use the new rate."
        ),
    }


@router.put("/senior/clients/{client_id}/gst-catalogue/permission")
def senior_gst_catalogue_permission(
    client_id: int,
    payload: GstCataloguePermissionIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    previous = client.gst_catalogue_access
    client.gst_catalogue_access = payload.enabled
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="accounting.gst_catalogue_permission",
        entity_type="accounting_client",
        entity_id=client.id,
        detail={"previous": previous, "enabled": payload.enabled},
    )
    db.commit()
    return {
        "client_id": client.id,
        "gst_catalogue_access": payload.enabled,
        "message": "GST catalogue editing enabled." if payload.enabled else "GST catalogue editing revoked.",
    }


@router.get("/senior/clients/{client_id}/gst-catalogue/history")
def senior_gst_catalogue_history(
    client_id: int,
    product_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    owner = _catalogue_owner_for(db, client)
    return {
        "items": catalogue_history(db, owner.id, product_id=product_id, limit=limit),
        "pending": catalogue_pending_changes(db, owner.id),
    }


@router.get("/senior/clients/{client_id}/gst-catalogue/export")
def senior_gst_catalogue_export(
    client_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    if not client.gst_catalogue_access:
        raise HTTPException(
            status_code=403,
            detail="GST catalogue export is not granted for this client by the business owner.",
        )
    owner = _catalogue_owner_for(db, client)
    content = export_catalogue_workbook(db, owner)
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="accounting.gst_catalogue_exported",
        entity_type="accounting_client",
        entity_id=client.id,
        detail={"format": "xlsx"},
    )
    db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="finovexa-gst-catalogue.xlsx"'
        },
    )


# ---------------------------------------------------------- business data exports

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _export_client(db: Session, user: User, client_id: int) -> AccountingClient:
    client = ensure_client_access(db, user, client_id)
    if client.business_profile_id is None:
        raise HTTPException(
            status_code=409,
            detail="No Business Manager business is linked to this engagement.",
        )
    return client


def _export_record_for(db: Session, client_id: int, export_id: int) -> AccountingDataExport:
    record = (
        db.query(AccountingDataExport)
        .filter(
            AccountingDataExport.id == export_id,
            AccountingDataExport.client_id == client_id,
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Export record not found.")
    return record


@router.get("/clients/{client_id}/exports/catalog")
def business_export_catalog(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = _export_client(db, user, client_id)
    return export_catalog_for_client(db, client)


@router.post("/clients/{client_id}/exports/preview")
def business_export_preview(
    client_id: int,
    payload: BusinessExportIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = _export_client(db, user, client_id)
    data = build_dataset(
        db,
        client,
        categories=payload.categories,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    result = export_preview(data)
    _audit(
        db,
        user,
        "accounting.business_export_previewed",
        client_id=client.id,
        entity="accounting_data_export",
        detail={
            "categories": payload.categories,
            "date_from": payload.date_from.isoformat() if payload.date_from else None,
            "date_to": payload.date_to.isoformat() if payload.date_to else None,
            "vouchers": result["tally"]["voucher_count"],
            "issue_counts": result["issue_counts"],
        },
    )
    db.commit()
    return result


@router.post("/clients/{client_id}/exports/workbook", status_code=201)
def business_export_workbook(
    client_id: int,
    payload: BusinessExportIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = _export_client(db, user, client_id)
    data = build_dataset(
        db,
        client,
        categories=payload.categories,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    record = create_workbook(db, data, created_by_id=user.id)
    _audit(
        db,
        user,
        "accounting.business_export_created",
        client_id=client.id,
        entity="accounting_data_export",
        entity_id=record.id,
        detail={
            "export_kind": record.export_kind,
            "filename": record.filename,
            "sha256": record.file_sha256,
            "categories": record.categories,
            "row_count": record.row_count,
            "warning_count": record.warning_count,
            "error_count": record.error_count,
        },
    )
    db.commit()
    db.refresh(record)
    return business_export_to_dict(db, record)


@router.post("/clients/{client_id}/exports/tally", status_code=201)
def business_export_tally(
    client_id: int,
    payload: BusinessTallyExportIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = _export_client(db, user, client_id)
    data = build_dataset(
        db,
        client,
        categories=payload.categories,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    record = create_tally_export(
        db,
        data,
        file_format=payload.file_format,
        tally_version=payload.tally_version,
        created_by_id=user.id,
    )
    _audit(
        db,
        user,
        "accounting.business_export_created",
        client_id=client.id,
        entity="accounting_data_export",
        entity_id=record.id,
        detail={
            "export_kind": record.export_kind,
            "file_format": payload.file_format,
            "tally_version": payload.tally_version,
            "filename": record.filename,
            "sha256": record.file_sha256,
            "categories": record.categories,
            "row_count": record.row_count,
        },
    )
    db.commit()
    db.refresh(record)
    return business_export_to_dict(db, record)


@router.get("/clients/{client_id}/exports")
def business_export_history(
    client_id: int,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = _export_client(db, user, client_id)
    records = (
        db.query(AccountingDataExport)
        .filter(AccountingDataExport.client_id == client.id)
        .order_by(AccountingDataExport.created_at.desc(), AccountingDataExport.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "client_id": client.id,
        "items": [business_export_to_dict(db, record) for record in records],
        "count": len(records),
    }


@router.get("/clients/{client_id}/exports/{export_id}/download")
def business_export_download(
    client_id: int,
    export_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    record = _export_record_for(db, client.id, export_id)
    if not record.stored_name:
        raise HTTPException(
            status_code=404, detail="The export file is unavailable. Generate it again."
        )
    media_type = (
        "application/zip" if record.export_kind == "tally_xml" else XLSX_MEDIA_TYPE
    )
    _audit(
        db,
        user,
        "accounting.business_export_downloaded",
        client_id=client.id,
        entity="accounting_data_export",
        entity_id=record.id,
        detail={"filename": record.filename, "sha256": record.file_sha256},
    )
    db.commit()
    try:
        return build_download(
            db, record.stored_name, filename=record.filename, media_type=media_type
        )
    except StoredFileMissing as exc:
        raise HTTPException(
            status_code=404, detail="The export file is unavailable. Generate it again."
        ) from exc


@router.get("/senior/tasks")
def list_tasks(
    status: str | None = None,
    client_id: int | None = None,
    assigned_to_user_id: int | None = None,
    overdue: bool | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingTask)
    if status:
        query = query.filter(AccountingTask.status == status)
    if client_id is not None:
        query = query.filter(AccountingTask.client_id == client_id)
    if assigned_to_user_id is not None:
        query = query.filter(AccountingTask.assigned_to_user_id == assigned_to_user_id)
    if overdue:
        query = query.filter(
            AccountingTask.due_date < date.today(),
            AccountingTask.status.notin_(("approved", "delivered", "cancelled")),
        )
    rows = query.order_by(AccountingTask.due_date.is_(None), AccountingTask.due_date).limit(300).all()
    return {"items": [task_to_dict(task) for task in rows]}


@router.post("/senior/tasks", status_code=201)
def create_task(
    payload: AccountingTaskIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, payload.client_id)
    assignee = _assignee(db, payload.assigned_to_user_id)
    task = AccountingTask(
        client_id=client.id,
        title=payload.title.strip(),
        description=payload.description,
        service_type=payload.service_type,
        status="assigned" if assignee else "unassigned",
        priority=payload.priority,
        due_date=payload.due_date,
        assigned_to_user_id=assignee.id if assignee else None,
        created_by_user_id=user.id,
        progress=0,
    )
    db.add(task)
    db.flush()
    if assignee:
        notify(
            db,
            assignee.id,
            kind="task_assigned",
            title="Task assigned",
            body=f"{task.title} for {client.business_name} was assigned to you.",
            client_id=client.id,
        )
    _audit(db, user, "accounting.task_created", client_id=client.id, entity="accounting_task", entity_id=task.id, detail={"title": task.title, "assigned_to": assignee.id if assignee else None})
    db.commit()
    db.refresh(task)
    return task_to_dict(task)


@router.patch("/senior/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: AccountingTaskUpdateIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    task = task_for_staff(db, user, task_id)
    data = payload.model_dump(exclude_unset=True)
    if "assigned_to_user_id" in data:
        assignee = _assignee(db, data["assigned_to_user_id"])
        data["assigned_to_user_id"] = assignee.id if assignee else None
        if assignee is not None and task.status == "unassigned":
            data["status"] = "assigned"
        if assignee is not None:
            notify(
                db,
                assignee.id,
                kind="task_assigned",
                title="Task assigned",
                body=f"{task.title} for {task.client.business_name} was assigned to you.",
                client_id=task.client_id,
            )
    for field, value in data.items():
        setattr(task, field, value)
    _audit(db, user, "accounting.task_updated", client_id=task.client_id, entity="accounting_task", entity_id=task.id, detail={"fields": sorted(data.keys())})
    db.commit()
    return task_to_dict(task, comments=True)


@router.post("/senior/tasks/{task_id}/review")
def review_task(
    task_id: int,
    payload: TaskReviewIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    task = task_for_staff(db, user, task_id)
    if task.status != "submitted":
        raise HTTPException(status_code=409, detail="Only tasks submitted for review can be reviewed.")
    task.reviewed_by_user_id = user.id
    task.reviewed_at = utcnow()
    task.review_notes = payload.notes
    if payload.decision == "approve":
        task.status = "approved"
        task.progress = 100
        task.delivered_at = utcnow()
        customer = task.client.customer_user_id if task.client else None
        notify(
            db,
            customer,
            kind="task_approved",
            title="Work approved",
            body=f"{task.title} for {task.client.business_name} was reviewed and approved.",
            client_id=task.client_id,
        )
    else:
        task.status = "changes_requested"
        notify(
            db,
            task.assigned_to_user_id,
            kind="changes_requested",
            title="Changes requested",
            body=f"{task.title} needs changes before approval.",
            client_id=task.client_id,
        )
    _audit(
        db,
        user,
        "accounting.task_approved" if payload.decision == "approve" else "accounting.task_changes_requested",
        client_id=task.client_id,
        entity="accounting_task",
        entity_id=task.id,
        detail={"notes": payload.notes},
    )
    db.commit()
    return task_to_dict(task, comments=True)


@router.get("/tasks/{task_id}/comments")
def list_task_comments(
    task_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    task = task_for_staff(db, user, task_id)
    return {"items": task_to_dict(task, comments=True)["comments"]}


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_task_comment(
    task_id: int,
    payload: TaskCommentIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    task = task_for_staff(db, user, task_id)
    comment = AccountingTaskComment(
        task_id=task.id,
        author_user_id=user.id,
        author_label=user.full_name,
        body=payload.body.strip(),
    )
    db.add(comment)
    db.flush()
    if user.role == "junior_accountant" and task.created_by_user_id:
        notify(
            db,
            task.created_by_user_id,
            kind="task_comment",
            title="New task comment",
            body=f"{user.full_name} commented on {task.title}.",
            client_id=task.client_id,
        )
    elif user.role == "senior_accountant" and task.assigned_to_user_id:
        notify(
            db,
            task.assigned_to_user_id,
            kind="task_comment",
            title="New task comment",
            body=f"{user.full_name} commented on {task.title}.",
            client_id=task.client_id,
        )
    _audit(db, user, "accounting.task_commented", client_id=task.client_id, entity="accounting_task", entity_id=task.id)
    db.commit()
    return {"id": comment.id, "author_label": comment.author_label, "body": comment.body, "created_at": comment.created_at.isoformat()}


# ---------------------------------------------------------------- junior workspace


@router.get("/junior/workspace")
def junior_workspace(
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    task_clients = db.query(AccountingTask.client_id).filter(
        AccountingTask.assigned_to_user_id == user.id
    )
    clients = (
        db.query(AccountingClient)
        .filter(
            AccountingClient.id.in_(task_clients)
            | (AccountingClient.assigned_junior_user_id == user.id)
        )
        .order_by(AccountingClient.business_name)
        .all()
    )
    tasks = (
        db.query(AccountingTask)
        .filter(AccountingTask.assigned_to_user_id == user.id)
        .order_by(AccountingTask.due_date.is_(None), AccountingTask.due_date)
        .all()
    )
    counts = Counter(task.status for task in tasks)
    today = date.today()
    return {
        "accountant": {"id": user.id, "name": user.full_name, "role": user.role},
        "clients": [client_to_dict(db, client) for client in clients],
        "tasks": [task_to_dict(task) for task in tasks],
        "counts": {
            "clients": len(clients),
            "open_tasks": sum(counts.get(status, 0) for status in OPEN_TASK_STATUSES),
            "in_progress": counts.get("in_progress", 0),
            "submitted": counts.get("submitted", 0),
            "changes_requested": counts.get("changes_requested", 0),
            "approved": counts.get("approved", 0),
            "overdue": sum(
                1
                for task in tasks
                if task.due_date
                and task.due_date < today
                and task.status not in ("approved", "delivered", "cancelled")
            ),
        },
        "upcoming_deadlines": upcoming_deadlines(tasks),
        "documents_pending": db.query(func.count(AccountingDocumentRequest.id))
        .filter(
            AccountingDocumentRequest.client_id.in_([client.id for client in clients] or [-1]),
            AccountingDocumentRequest.status == "pending",
        )
        .scalar()
        or 0,
        "notifications": _serialize_notifications(db, user),
    }


@router.get("/junior/clients")
def junior_clients(
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    condition = staff_client_filter(db, user)
    query = db.query(AccountingClient)
    if condition is not None:
        query = query.filter(condition)
    return {"items": [client_to_dict(db, client) for client in query.order_by(AccountingClient.business_name)]}


@router.get("/junior/clients/{client_id}")
def junior_client_detail(
    client_id: int,
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    tasks = (
        db.query(AccountingTask)
        .filter(AccountingTask.client_id == client.id)
        .order_by(AccountingTask.created_at.desc())
        .all()
    )
    documents = (
        db.query(AccountingDocument)
        .filter(AccountingDocument.client_id == client.id)
        .order_by(AccountingDocument.created_at.desc())
        .all()
    )
    return {
        "client": client_to_dict(db, client, detail=True),
        "tasks": [task_to_dict(task, comments=True) for task in tasks],
        "documents": [document_to_dict(doc) for doc in documents],
        "document_requests": [
            document_request_to_dict(row)
            for row in db.query(AccountingDocumentRequest)
            .filter(AccountingDocumentRequest.client_id == client.id)
            .order_by(AccountingDocumentRequest.created_at.desc())
        ],
        "vouchers": {
            "count": db.query(func.count(AccountingVoucher.id))
            .filter(AccountingVoucher.client_id == client.id)
            .scalar()
            or 0,
            "recent": [voucher_to_dict(v) for v in client_vouchers(db, client.id)[-8:]][::-1],
        },
        "messages": [
            message_to_dict(row)
            for row in db.query(AccountingMessage)
            .filter(AccountingMessage.client_id == client.id)
            .order_by(AccountingMessage.created_at)
        ],
    }


@router.get("/junior/tasks")
def junior_tasks(
    status: str | None = None,
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingTask).filter(AccountingTask.assigned_to_user_id == user.id)
    if status:
        query = query.filter(AccountingTask.status == status)
    rows = query.order_by(AccountingTask.due_date.is_(None), AccountingTask.due_date).all()
    return {"items": [task_to_dict(task) for task in rows]}


@router.post("/junior/tasks/{task_id}/submit")
def submit_task(
    task_id: int,
    payload: TaskSubmitIn,
    user: User = Depends(get_current_junior_accountant),
    db: Session = Depends(get_db),
):
    task = task_for_staff(db, user, task_id)
    if task.status == "approved":
        raise HTTPException(status_code=409, detail="This task is already approved.")
    task.status = "submitted"
    task.submitted_at = utcnow()
    task.progress = payload.progress
    comment = AccountingTaskComment(
        task_id=task.id,
        author_user_id=user.id,
        author_label=user.full_name,
        body=f"Submitted for review: {payload.summary.strip()}",
    )
    db.add(comment)
    seniors = (
        db.query(User)
        .filter(User.role == "senior_accountant", User.is_active.is_(True))
        .all()
    )
    for senior in seniors:
        notify(
            db,
            senior.id,
            kind="task_submitted",
            title="Task awaiting review",
            body=f"{user.full_name} submitted {task.title} for {task.client.business_name}.",
            client_id=task.client_id,
        )
    _audit(db, user, "accounting.task_submitted", client_id=task.client_id, entity="accounting_task", entity_id=task.id, detail={"progress": payload.progress})
    db.commit()
    return task_to_dict(task, comments=True)


# ---------------------------------------------------------------- vouchers


def _voucher_payload(
    db: Session,
    user: User,
    payload: AccountingVoucherIn,
    *,
    source: str = "manual",
) -> AccountingVoucher:
    if user.role not in ACCOUNTANT_ROLES:
        raise HTTPException(status_code=403, detail="Accounting access required.")
    ensure_client_access(db, user, payload.client_id)
    try:
        return create_voucher(
            db,
            client_id=payload.client_id,
            voucher_type=payload.voucher_type,
            number=payload.number,
            voucher_date=payload.voucher_date,
            party_name=payload.party_name,
            party_gstin=payload.party_gstin,
            ledger_name=payload.ledger_name,
            bank_ledger=payload.bank_ledger,
            category=payload.category,
            description=payload.description,
            taxable_value=payload.taxable_value,
            gst_rate=payload.gst_rate,
            inter_state=payload.inter_state,
            created_by=user,
            source=source,
        )
    except DuplicateVoucher as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Voucher {exc.voucher.number} with the same date and amount already exists.",
        ) from exc


@router.post("/vouchers", status_code=201)
def post_voucher(
    payload: AccountingVoucherIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    voucher = _voucher_payload(db, user, payload)
    _audit(db, user, "accounting.voucher_posted", client_id=payload.client_id, entity="accounting_voucher", entity_id=voucher.id, detail={"number": voucher.number, "type": voucher.voucher_type})
    db.commit()
    return voucher_to_dict(voucher)


@router.post("/vouchers/bulk", status_code=201)
def post_vouchers_bulk(
    payload: VoucherBulkIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    created: list[AccountingVoucher] = []
    duplicates: list[str] = []
    errors: list[dict] = []
    for index, row in enumerate(payload.rows, start=1):
        raw = {**row, "client_id": payload.client_id}
        try:
            parsed = AccountingVoucherIn.model_validate(raw)
        except Exception as exc:  # pydantic ValidationError
            errors.append({"row": index, "problems": [str(exc).splitlines()[0]]})
            continue
        try:
            created.append(_voucher_payload(db, user, parsed, source="bulk"))
        except HTTPException as exc:
            if exc.status_code == 409:
                duplicates.append(parsed.number)
            else:
                errors.append({"row": index, "problems": [str(exc.detail)]})
    _audit(db, user, "accounting.vouchers_bulk_posted", client_id=payload.client_id, detail={"created": len(created), "duplicates": len(duplicates), "errors": len(errors)})
    db.commit()
    return {
        "created": [voucher_to_dict(v) for v in created],
        "duplicate_numbers": duplicates,
        "errors": errors,
    }


@router.get("/vouchers")
def list_vouchers(
    client_id: int,
    from_date: date | None = None,
    to_date: date | None = None,
    voucher_type: str | None = None,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    rows = client_vouchers(db, client_id, from_date=from_date, to_date=to_date, voucher_type=voucher_type)
    return {
        "items": [voucher_to_dict(v) for v in rows],
        "totals": {
            "sales": q2(sum((v.taxable_value for v in rows if v.voucher_type == "sale"), ZERO)),
            "purchases": q2(sum((v.taxable_value for v in rows if v.voucher_type == "purchase"), ZERO)),
            "gst_output": q2(sum((v.cgst_amount + v.sgst_amount + v.igst_amount for v in rows if v.voucher_type == "sale"), ZERO)),
            "gst_input": q2(sum((v.cgst_amount + v.sgst_amount + v.igst_amount for v in rows if v.voucher_type == "purchase"), ZERO)),
        },
    }


# ---------------------------------------------------------------- automation (bill, bank, gst)


@router.post("/bills/extract")
def extract_bill(
    payload: BillExtractIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    raw, suffix = decode_data_url(payload.data_url)
    result = read_bill(raw, suffix)
    result["filename"] = payload.filename
    result["client_id"] = payload.client_id
    return result


@router.post("/bank/import", status_code=201)
def import_bank_statement(
    payload: BankFileIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    raw, suffix = decode_data_url(payload.data_url)
    rows, fmt = parse_tabular(raw, suffix)
    normalised = normalise_bank_rows(rows)
    if not normalised:
        raise HTTPException(
            status_code=422,
            detail="No usable rows were found. Include date, description and debit or credit columns.",
        )
    record = AccountingBankImport(
        client_id=payload.client_id,
        imported_by_user_id=user.id,
        filename=payload.filename[:255],
        row_count=len(normalised),
        status="imported",
        note=f"Parsed from {fmt.upper()} upload. Matches are suggestions until confirmed.",
    )
    db.add(record)
    db.flush()
    for row in normalised:
        db.add(
            AccountingBankTransaction(
                import_id=record.id,
                client_id=payload.client_id,
                txn_date=row["txn_date"],
                description=row["description"],
                reference=row["reference"],
                debit=row["debit"],
                credit=row["credit"],
                status="unmatched",
            )
        )
    db.flush()
    db.refresh(record)
    recompute_import_matches(db, record)
    _audit(db, user, "accounting.bank_imported", client_id=payload.client_id, entity="accounting_bank_import", entity_id=record.id, detail={"rows": record.row_count})
    db.commit()
    db.refresh(record)
    return bank_import_to_dict(record)


@router.post("/bank/import-rows", status_code=201)
def import_bank_rows(
    payload: BankRowsIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    normalised = normalise_bank_rows(payload.rows)
    if not normalised:
        raise HTTPException(status_code=422, detail="No usable rows were supplied.")
    record = AccountingBankImport(
        client_id=payload.client_id,
        imported_by_user_id=user.id,
        filename=payload.filename[:255],
        row_count=len(normalised),
        status="imported",
        note="Parsed from supplied rows. Matches are suggestions until confirmed.",
    )
    db.add(record)
    db.flush()
    for row in normalised:
        db.add(
            AccountingBankTransaction(
                import_id=record.id,
                client_id=payload.client_id,
                txn_date=row["txn_date"],
                description=row["description"],
                reference=row["reference"],
                debit=row["debit"],
                credit=row["credit"],
                status="unmatched",
            )
        )
    db.flush()
    db.refresh(record)
    recompute_import_matches(db, record)
    _audit(db, user, "accounting.bank_imported", client_id=payload.client_id, entity="accounting_bank_import", entity_id=record.id, detail={"rows": record.row_count})
    db.commit()
    db.refresh(record)
    return bank_import_to_dict(record)


@router.get("/bank/imports")
def list_bank_imports(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    rows = (
        db.query(AccountingBankImport)
        .filter(AccountingBankImport.client_id == client_id)
        .order_by(AccountingBankImport.created_at.desc())
        .limit(20)
        .all()
    )
    return {"items": [bank_import_to_dict(row) for row in rows]}


@router.post("/bank/transactions/{transaction_id}/match")
def confirm_bank_match(
    transaction_id: int,
    payload: BankMatchIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    txn = db.get(AccountingBankTransaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Bank transaction not found.")
    ensure_client_access(db, user, txn.client_id)
    if payload.voucher_id is not None:
        voucher = db.get(AccountingVoucher, payload.voucher_id)
        if voucher is None or voucher.client_id != txn.client_id:
            raise HTTPException(status_code=422, detail="Select a voucher that belongs to this client.")
        txn.matched_voucher_id = voucher.id
        txn.status = "matched"
        txn.match_score = 100
        txn.match_note = payload.note or f"Confirmed against voucher {voucher.number} by {user.full_name}."
    else:
        txn.matched_voucher_id = None
        txn.status = "unmatched"
        txn.match_note = payload.note or "Match cleared by the accountant."
    record = db.get(AccountingBankImport, txn.import_id)
    if record is not None:
        matched = sum(1 for row in record.transactions if row.status == "matched")
        record.matched_count = matched
        record.status = "reconciled" if matched == len(record.transactions) else "imported"
    _audit(db, user, "accounting.bank_match_confirmed", client_id=txn.client_id, entity="accounting_bank_transaction", entity_id=txn.id, detail={"voucher_id": txn.matched_voucher_id})
    db.commit()
    return bank_transaction_to_dict(txn)


@router.post("/gst/prepare")
def prepare_gst(
    payload: GSTPrepareIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    vouchers = client_vouchers(db, payload.client_id)
    return gst_working(vouchers, payload.period)


# ---------------------------------------------------------------- reports


def _build_report_payload(
    db: Session,
    client: AccountingClient,
    report_type: str,
    financial_year: str,
    period: str,
) -> dict:
    vouchers = client_vouchers(db, client.id)
    if report_type == "monthly_summary":
        receivables = practice_receivables(db, client.id)
        payload = monthly_summary(
            vouchers,
            period,
            receivables=receivables["outstanding"],
            overdue_receivables=receivables["overdue"],
            overdue_count=receivables["overdue_count"],
        )
        payload["client"] = {"business_name": client.business_name, "code": client.code, "gstin": client.gstin}
        return payload
    if report_type in ("gstr1", "gstr3b"):
        working = gst_working(vouchers, period)
        return {
            "period": period,
            "client": {"business_name": client.business_name, "code": client.code, "gstin": client.gstin},
            report_type: working[report_type],
            "summary": working["summary"],
            "mismatches": working["mismatches"],
            "filing_status": working["filing_status"],
            "filing_note": working["filing_note"],
        }
    if report_type == "financials":
        start, end = financial_year_bounds(financial_year)
        rows = [v for v in vouchers if start <= v.voucher_date <= end]
        revenue = q2(sum((v.taxable_value for v in rows if v.voucher_type == "sale"), ZERO))
        expenses = q2(sum((v.taxable_value for v in rows if v.voucher_type == "purchase"), ZERO))
        gst = gst_working(rows, period)["summary"] if rows else gst_working([], period)["summary"]
        return {
            "financial_year": financial_year,
            "period": period,
            "client": {"business_name": client.business_name, "code": client.code, "gstin": client.gstin},
            "revenue": revenue,
            "expenses": expenses,
            "gross_profit": q2(revenue - expenses),
            "gst": gst,
            "voucher_count": len(rows),
            "basis": "recorded_vouchers",
            "note": "Draft management accounts from the ledger. Not an audited financial statement.",
        }
    raise HTTPException(status_code=422, detail="Unknown report type.")


@router.post("/reports", status_code=201)
def create_report(
    payload: AccountingReportIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, payload.client_id)
    if payload.report_type != "financials":
        try:
            month_bounds(payload.period)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Period must use the YYYY-MM format.") from exc
    payload_data = _build_report_payload(db, client, payload.report_type, payload.financial_year, payload.period)
    report = AccountingReport(
        client_id=client.id,
        report_type=payload.report_type,
        financial_year=payload.financial_year,
        period_label=payload.period,
        payload=payload_data,
        status="draft",
        prepared_by_user_id=user.id,
    )
    db.add(report)
    db.flush()
    if client.senior_accountant_user_id and client.senior_accountant_user_id != user.id:
        notify(
            db,
            client.senior_accountant_user_id,
            kind="report_draft",
            title="Report draft ready",
            body=f"{payload.report_type.replace('_', ' ').title()} for {client.business_name} is ready for review.",
            client_id=client.id,
        )
    _audit(db, user, "accounting.report_drafted", client_id=client.id, entity="accounting_report", entity_id=report.id, detail={"type": report.report_type, "period": report.period_label})
    db.commit()
    return report_to_dict(report)


@router.get("/senior/reports")
def list_reports(
    status: str | None = None,
    client_id: int | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingReport)
    if status:
        query = query.filter(AccountingReport.status == status)
    if client_id is not None:
        query = query.filter(AccountingReport.client_id == client_id)
    rows = query.order_by(AccountingReport.created_at.desc()).limit(200).all()
    return {"items": [report_to_dict(row, include_payload=False) for row in rows]}


@router.get("/reports/{report_id}")
def get_report(
    report_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    report = db.get(AccountingReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    ensure_client_access(db, user, report.client_id)
    if user.role == "junior_accountant" and report.status not in ("draft", "changes_requested"):
        raise HTTPException(status_code=403, detail="Only your drafts are visible until a senior approves them.")
    return report_to_dict(report)


@router.post("/senior/reports/{report_id}/review")
def review_report(
    report_id: int,
    payload: ReportReviewIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    report = db.get(AccountingReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    if report.status == "delivered":
        raise HTTPException(status_code=409, detail="Delivered reports cannot be reviewed again.")
    report.reviewed_by_user_id = user.id
    report.review_notes = payload.notes
    if payload.decision == "approve":
        report.status = "approved"
        report.approved_at = utcnow()
        client = db.get(AccountingClient, report.client_id)
        notify(
            db,
            client.customer_user_id if client else None,
            kind="report_approved",
            title="Report approved",
            body=f"{report.report_type.replace('_', ' ').title()} for {report.period_label} is approved and ready.",
            client_id=report.client_id,
        )
    else:
        report.status = "changes_requested"
        notify(
            db,
            report.prepared_by_user_id,
            kind="changes_requested",
            title="Report changes requested",
            body=f"{report.report_type.replace('_', ' ').title()} needs changes before approval.",
            client_id=report.client_id,
        )
    _audit(db, user, "accounting.report_approved" if payload.decision == "approve" else "accounting.report_changes_requested", client_id=report.client_id, entity="accounting_report", entity_id=report.id, detail={"notes": payload.notes})
    db.commit()
    return report_to_dict(report)


@router.post("/senior/reports/{report_id}/deliver")
def deliver_report(
    report_id: int,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    report = db.get(AccountingReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    if report.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved reports can be delivered.")
    report.status = "delivered"
    report.delivered_at = utcnow()
    client = db.get(AccountingClient, report.client_id)
    notify(
        db,
        client.customer_user_id if client else None,
        kind="report_delivered",
        title="Report delivered",
        body=f"{report.report_type.replace('_', ' ').title()} for {report.period_label} is available in your portal.",
        client_id=report.client_id,
    )
    _audit(db, user, "accounting.report_delivered", client_id=report.client_id, entity="accounting_report", entity_id=report.id)
    db.commit()
    return report_to_dict(report)


# ---------------------------------------------------------------- documents


def _create_document(
    db: Session,
    client: AccountingClient,
    user: User,
    payload: AccountingDocumentIn,
    *,
    source: str,
    visibility: str,
) -> AccountingDocument:
    upload = _save_upload(db, payload, title=payload.title, category=payload.category, source=source)
    document = AccountingDocument(
        client_id=client.id,
        uploaded_by_user_id=user.id,
        category=payload.category,
        title=upload["title"][:200],
        original_filename=payload.filename[:255],
        stored_name=upload["stored_name"],
        content_type=upload["content_type"],
        size_bytes=upload["size"],
        sha256=upload["sha256"],
        visibility=visibility,
        source=source,
        status="received",
    )
    db.add(document)
    db.flush()
    if payload.request_id:
        request = db.get(AccountingDocumentRequest, payload.request_id)
        if request is not None and request.client_id == client.id and request.status == "pending":
            request.status = "fulfilled"
            request.fulfilled_document_id = document.id
            request.fulfilled_at = utcnow()
            if request.requested_by_user_id:
                notify(
                    db,
                    request.requested_by_user_id,
                    kind="document_received",
                    title="Requested document received",
                    body=f"{client.business_name} uploaded {payload.filename}.",
                    client_id=client.id,
                )
    if source == "customer" and client.senior_accountant_user_id:
        notify(
            db,
            client.senior_accountant_user_id,
            kind="document_uploaded",
            title="Client document uploaded",
            body=f"{client.business_name} uploaded {payload.filename}.",
            client_id=client.id,
        )
    _audit(db, user, "accounting.document_uploaded", client_id=client.id, entity="accounting_document", entity_id=document.id, detail={"filename": payload.filename, "visibility": visibility})
    return document


@router.post("/documents", status_code=201)
def upload_document(
    payload: AccountingDocumentIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, payload.client_id)
    document = _create_document(db, client, user, payload, source="accountant", visibility="internal")
    db.commit()
    return document_to_dict(document)


@router.get("/senior/documents")
def list_documents(
    client_id: int | None = None,
    status: str | None = None,
    category: str | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingDocument)
    if client_id is not None:
        query = query.filter(AccountingDocument.client_id == client_id)
    if status:
        query = query.filter(AccountingDocument.status == status)
    if category:
        query = query.filter(AccountingDocument.category == category)
    rows = query.order_by(AccountingDocument.created_at.desc()).limit(300).all()
    return {"items": [document_to_dict(row) for row in rows]}


@router.post("/senior/documents/{document_id}/review")
def review_document(
    document_id: int,
    payload: DocumentReviewIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    document = db.get(AccountingDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    document.status = payload.status
    document.verified_by_user_id = user.id
    document.verified_at = utcnow()
    document.note = payload.note
    _audit(db, user, f"accounting.document_{payload.status}", client_id=document.client_id, entity="accounting_document", entity_id=document.id, detail={"note": payload.note})
    db.commit()
    return document_to_dict(document)


@router.get("/documents/{document_id}/file")
def download_document(
    document_id: int,
    user: User = Depends(get_current_accountant_or_customer),
    db: Session = Depends(get_db),
):
    document = document_for_reader(db, user, document_id)
    try:
        return build_download(
            db,
            document.stored_name,
            filename=document.original_filename,
            media_type=document.content_type or "application/octet-stream",
        )
    except StoredFileMissing as exc:
        raise HTTPException(
            status_code=404, detail="The stored file is unavailable. Upload it again."
        ) from exc


@router.post("/document-requests", status_code=201)
def create_document_request(
    payload: DocumentRequestIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, payload.client_id)
    request = AccountingDocumentRequest(
        client_id=client.id,
        requested_by_user_id=user.id,
        title=payload.title.strip(),
        description=payload.description,
        due_date=payload.due_date,
        status="pending",
    )
    db.add(request)
    db.flush()
    notify(
        db,
        client.customer_user_id,
        kind="document_request",
        title="Document requested",
        body=f"{payload.title.strip()} is required for your accounting work.",
        client_id=client.id,
    )
    _audit(db, user, "accounting.document_requested", client_id=client.id, entity="accounting_document_request", entity_id=request.id, detail={"title": request.title})
    db.commit()
    return document_request_to_dict(request)


# ---------------------------------------------------------------- Tally


@router.post("/tally/import", status_code=201)
def tally_import(
    payload: TallyImportIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    raw, suffix = decode_data_url(payload.data_url)
    rows, fmt = parse_tabular(raw, suffix)
    if not rows:
        raise HTTPException(status_code=422, detail="The uploaded file has no data rows.")
    stored_name, _, _ = save_document_file(db, raw, suffix)
    batch = import_tally_rows(
        db,
        client_id=payload.client_id,
        rows=rows,
        actor=user,
        filename=payload.filename,
        fmt=fmt,
        stored_name=stored_name,
    )
    _audit(db, user, "accounting.tally_imported", client_id=payload.client_id, entity="accounting_tally_batch", entity_id=batch.id, detail={"rows": batch.row_count, "valid": batch.valid_count, "duplicates": batch.duplicate_count})
    db.commit()
    db.refresh(batch)
    return tally_batch_to_dict(batch)


@router.post("/tally/export")
def tally_export(
    payload: TallyExportIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    rows = client_vouchers(
        db,
        payload.client_id,
        from_date=payload.from_date,
        to_date=payload.to_date,
        voucher_type=None if payload.voucher_type == "all" else payload.voucher_type,
    )
    csv_text = tally_export_csv(rows)
    stored_name, _, _ = save_document_file(
        db, csv_text.encode("utf-8"), "csv", content_type="text/csv"
    )
    batch = AccountingTallyBatch(
        client_id=payload.client_id,
        direction="export",
        created_by_user_id=user.id,
        filename=f"tally-export-{payload.from_date.isoformat()}-{payload.to_date.isoformat()}.csv",
        format="csv",
        stored_name=stored_name,
        row_count=len(rows),
        valid_count=len(rows),
        status="completed",
        details={
            "from_date": payload.from_date.isoformat(),
            "to_date": payload.to_date.isoformat(),
            "voucher_type": payload.voucher_type,
            "note": "Export produces a Tally-compatible voucher file. No live Tally connection is used.",
        },
    )
    db.add(batch)
    _audit(db, user, "accounting.tally_exported", client_id=payload.client_id, entity="accounting_tally_batch", entity_id=batch.id, detail={"rows": len(rows)})
    db.commit()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="tally-export-{payload.from_date.isoformat()}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/tally/batches")
def tally_batches(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    rows = (
        db.query(AccountingTallyBatch)
        .filter(AccountingTallyBatch.client_id == client_id)
        .order_by(AccountingTallyBatch.created_at.desc())
        .limit(50)
        .all()
    )
    return {"items": [tally_batch_to_dict(row) for row in rows]}


def _export_record(db: Session, export_id: int) -> AccountingTallyExport:
    record = db.get(AccountingTallyExport, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Export batch not found.")
    return record


def _export_dict(db: Session, record: AccountingTallyExport, *, include_validation: bool = False) -> dict:
    client = db.get(AccountingClient, record.client_id)
    prepared = db.get(User, record.prepared_by_user_id) if record.prepared_by_user_id else None
    approved = db.get(User, record.approved_by_user_id) if record.approved_by_user_id else None
    return export_to_dict(
        record,
        include_validation=include_validation,
        prepared_by=prepared.full_name if prepared else None,
        approved_by=approved.full_name if approved else None,
        client_name=client.business_name if client else None,
    )


def _staff_visible_client_ids(db: Session, user: User) -> list[int]:
    return [row.id for row in db.query(AccountingClient.id).filter(staff_client_filter(db, user)).all()]


@router.get("/tally/catalog")
def tally_export_catalog(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    return export_catalog(db, client)


@router.post("/tally/exports/validate")
def tally_export_validate(
    payload: TallyExportBatchIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, payload.client_id)
    data = collect_export_data(db, client, payload.export_types, payload.from_date, payload.to_date)
    return validate_export(data, payload.export_types, client, payload.from_date, payload.to_date)


@router.post("/tally/exports", status_code=201)
def tally_export_create(
    payload: TallyExportBatchIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, payload.client_id)
    report, _, record = prepare_export(
        db,
        client=client,
        export_types=payload.export_types,
        from_date=payload.from_date,
        to_date=payload.to_date,
        file_format=payload.file_format,
        prepared_by_id=user.id,
        tally_version=payload.tally_version,
    )
    if record is None:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "The export was not prepared because validation found errors. "
                    "Correct the vouchers or masters and try again; no figure was changed."
                ),
                "validation": report,
            },
        )
    senior_id = client.senior_accountant_user_id
    if senior_id and senior_id != user.id:
        notify(
            db,
            senior_id,
            kind="tally_export_pending",
            title="Tally export awaiting your approval",
            body=(
                f"{user.full_name} prepared a {len(payload.export_types)}-type Tally export for "
                f"{client.business_name}. Review and approve it before it can be downloaded."
            ),
            client_id=client.id,
        )
    _audit(
        db,
        user,
        "accounting.tally_export_prepared",
        client_id=client.id,
        entity="accounting_tally_export",
        entity_id=record.id,
        detail={
            "types": payload.export_types,
            "format": payload.file_format,
            "vouchers": record.voucher_count,
            "errors": report["error_count"],
            "warnings": report["warning_count"],
        },
    )
    db.commit()
    db.refresh(record)
    return _export_dict(db, record, include_validation=True)


@router.get("/tally/exports")
def list_tally_exports(
    client_id: int | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingTallyExport)
    visible_ids: list[int] | None = None
    if client_id is not None:
        ensure_client_access(db, user, client_id)
        query = query.filter(AccountingTallyExport.client_id == client_id)
    elif user.role == "junior_accountant":
        visible_ids = _staff_visible_client_ids(db, user)
        query = query.filter(AccountingTallyExport.client_id.in_(visible_ids))
    if status:
        query = query.filter(AccountingTallyExport.status == status)
    rows = query.order_by(AccountingTallyExport.created_at.desc()).limit(limit).all()
    pending_query = db.query(func.count(AccountingTallyExport.id)).filter(
        AccountingTallyExport.status == "pending_approval"
    )
    if visible_ids is not None:
        pending_query = pending_query.filter(AccountingTallyExport.client_id.in_(visible_ids))
    pending = pending_query.scalar() or 0
    return {"items": [_export_dict(db, row) for row in rows], "pending_approval_count": int(pending)}


@router.get("/tally/exports/{export_id}")
def get_tally_export(
    export_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    record = _export_record(db, export_id)
    ensure_client_access(db, user, record.client_id)
    return _export_dict(db, record, include_validation=True)


@router.post("/tally/exports/{export_id}/decision")
def decide_tally_export(
    export_id: int,
    payload: TallyDecisionIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    record = _export_record(db, export_id)
    ensure_client_access(db, user, record.client_id)
    if record.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"This batch is {record.status}; only a pending batch can be reviewed.",
        )
    if record.prepared_by_user_id == user.id:
        # A senior may review their own batch, but the audit trail records it explicitly.
        record.details = {**(record.details or {}), "self_approved": payload.decision == "approve"}
    if payload.decision == "approve":
        record.status = "approved"
        record.approved_by_user_id = user.id
        record.approved_at = utcnow()
        record.approval_note = payload.note
    else:
        record.status = "rejected"
        record.approved_by_user_id = user.id
        record.approved_at = utcnow()
        record.approval_note = payload.note
    notify(
        db,
        record.prepared_by_user_id,
        kind=f"tally_export_{record.status}",
        title=f"Tally export {record.status}",
        body=(
            f"{user.full_name} {record.status} the Tally export {record.filename}."
            + (f" Note: {payload.note}" if payload.note else "")
        ),
        client_id=record.client_id,
    )
    _audit(
        db,
        user,
        f"accounting.tally_export_{record.status}",
        client_id=record.client_id,
        entity="accounting_tally_export",
        entity_id=record.id,
        detail={"note": payload.note, "self_approved": record.prepared_by_user_id == user.id},
    )
    db.commit()
    db.refresh(record)
    return _export_dict(db, record, include_validation=True)


@router.get("/tally/exports/{export_id}/download")
def download_tally_export(
    export_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    record = _export_record(db, export_id)
    ensure_client_access(db, user, record.client_id)
    if record.status != "approved":
        raise HTTPException(
            status_code=403,
            detail="A senior accountant must approve this batch before it can be downloaded.",
        )
    if not record.stored_name:
        raise HTTPException(status_code=404, detail="The export file is unavailable. Prepare it again.")
    _audit(
        db,
        user,
        "accounting.tally_export_downloaded",
        client_id=record.client_id,
        entity="accounting_tally_export",
        entity_id=record.id,
        detail={"filename": record.filename, "sha256": record.file_sha256},
    )
    db.commit()
    try:
        return build_download(
            db,
            record.stored_name,
            filename=record.filename,
            media_type=mime_for_format(record.file_format),
        )
    except StoredFileMissing as exc:
        raise HTTPException(
            status_code=404, detail="The export file is unavailable. Prepare it again."
        ) from exc


@router.post("/tally/exports/{export_id}/import-status")
def set_tally_import_status(
    export_id: int,
    payload: TallyImportStatusIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    record = _export_record(db, export_id)
    ensure_client_access(db, user, record.client_id)
    if record.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="Record the Tally import result only after the batch has been approved.",
        )
    record.import_status = payload.import_status
    record.import_note = payload.note
    if payload.import_status == "failed":
        notify(
            db,
            record.approved_by_user_id or record.prepared_by_user_id,
            kind="tally_import_failed",
            title="Tally import reported as failed",
            body=f"{user.full_name} recorded a failed Tally import for {record.filename}.",
            client_id=record.client_id,
        )
    _audit(
        db,
        user,
        "accounting.tally_import_status",
        client_id=record.client_id,
        entity="accounting_tally_export",
        entity_id=record.id,
        detail={"import_status": payload.import_status, "note": payload.note},
    )
    db.commit()
    db.refresh(record)
    return _export_dict(db, record)


# ---------------------------------------------------------------- Tally stock masters


@router.get("/tally/stock-items")
def list_stock_items(
    client_id: int,
    include_inactive: bool = False,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    query = db.query(AccountingStockItem).filter(AccountingStockItem.client_id == client_id)
    if not include_inactive:
        query = query.filter(AccountingStockItem.is_active.is_(True))
    rows = query.order_by(AccountingStockItem.name).all()
    return {"items": [stock_item_to_dict(row) for row in rows]}


@router.post("/tally/stock-items", status_code=201)
def create_stock_item(
    payload: StockItemIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, payload.client_id)
    sku = payload.sku.strip().upper()
    existing = (
        db.query(AccountingStockItem)
        .filter(
            AccountingStockItem.client_id == payload.client_id,
            func.upper(AccountingStockItem.sku) == sku,
        )
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Stock item SKU {sku} already exists for this client.")
    item = AccountingStockItem(
        client_id=payload.client_id,
        name=payload.name.strip(),
        sku=sku,
        unit=payload.unit.strip(),
        hsn_sac=(payload.hsn_sac or "").strip() or None,
        gst_rate=payload.gst_rate,
        opening_qty=payload.opening_qty,
        opening_rate=payload.opening_rate,
        created_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        user,
        "accounting.stock_item_created",
        client_id=item.client_id,
        entity="accounting_stock_item",
        entity_id=item.id,
        detail={"sku": sku, "name": item.name},
    )
    db.commit()
    db.refresh(item)
    return stock_item_to_dict(item)


@router.patch("/tally/stock-items/{item_id}")
def update_stock_item(
    item_id: int,
    payload: StockItemUpdateIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    item = db.get(AccountingStockItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Stock item not found.")
    ensure_client_access(db, user, item.client_id)
    changes = payload.model_dump(exclude_unset=True)
    for field_name, value in changes.items():
        if field_name in ("name", "unit") and isinstance(value, str):
            value = value.strip()
        if field_name == "hsn_sac" and isinstance(value, str):
            value = value.strip() or None
        setattr(item, field_name, value)
    _audit(
        db,
        user,
        "accounting.stock_item_updated",
        client_id=item.client_id,
        entity="accounting_stock_item",
        entity_id=item.id,
        detail={"fields": sorted(changes)},
    )
    db.commit()
    db.refresh(item)
    return stock_item_to_dict(item)


# ---------------------------------------------------------------- practice billing


@router.get("/senior/invoices")
def list_invoices(
    status: str | None = None,
    client_id: int | None = None,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    query = db.query(AccountingInvoice)
    if status:
        query = query.filter(AccountingInvoice.status == status)
    if client_id is not None:
        query = query.filter(AccountingInvoice.client_id == client_id)
    rows = query.order_by(AccountingInvoice.issue_date.desc()).limit(300).all()
    return {"items": [invoice_to_dict(row) for row in rows], "totals": practice_receivables(db, client_id)}


@router.post("/senior/invoices", status_code=201)
def create_invoice(
    payload: ServiceInvoiceIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    client = _client_or_404(db, payload.client_id)
    subtotal = q2(payload.subtotal)
    tax = q2(subtotal * payload.tax_rate / Decimal("100"))
    invoice = AccountingInvoice(
        client_id=client.id,
        number=next_invoice_number(db),
        issue_date=payload.issue_date,
        due_date=payload.due_date,
        period_label=payload.period_label,
        subtotal=subtotal,
        tax_amount=tax,
        total_amount=q2(subtotal + tax),
        status="issued",
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(invoice)
    db.flush()
    notify(
        db,
        client.customer_user_id,
        kind="invoice_issued",
        title="Invoice issued",
        body=f"Invoice {invoice.number} for INR {invoice.total_amount:,.2f} is available in your portal.",
        client_id=client.id,
    )
    _audit(db, user, "accounting.invoice_issued", client_id=client.id, entity="accounting_invoice", entity_id=invoice.id, detail={"number": invoice.number, "total": float(invoice.total_amount)})
    db.commit()
    return invoice_to_dict(invoice)


@router.post("/senior/invoices/{invoice_id}/payments", status_code=201)
def record_practice_payment(
    invoice_id: int,
    payload: ServicePaymentIn,
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    invoice = db.get(AccountingInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if invoice.status == "void":
        raise HTTPException(status_code=409, detail="Void invoices cannot receive payments.")
    amount = q2(payload.amount)
    if amount > invoice.outstanding_amount:
        raise HTTPException(
            status_code=422,
            detail=f"Payment exceeds the outstanding amount of INR {invoice.outstanding_amount:,.2f}.",
        )
    payment = AccountingInvoicePayment(
        invoice=invoice,
        amount=amount,
        method=payload.method,
        reference=payload.reference,
        received_on=payload.received_on,
        recorded_by_user_id=user.id,
    )
    db.add(payment)
    db.flush()
    invoice.status = "paid" if invoice.outstanding_amount <= 0 else "part_paid"
    _audit(db, user, "accounting.payment_recorded", client_id=invoice.client_id, entity="accounting_invoice", entity_id=invoice.id, detail={"amount": float(amount)})
    db.commit()
    db.refresh(invoice)
    return invoice_to_dict(invoice)


# ---------------------------------------------------------------- messages & notifications


@router.get("/messages")
def list_messages(
    client_id: int,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    ensure_client_access(db, user, client_id)
    rows = (
        db.query(AccountingMessage)
        .filter(AccountingMessage.client_id == client_id)
        .order_by(AccountingMessage.created_at)
        .all()
    )
    for row in rows:
        if row.author_role == "customer" and row.read_by_staff_at is None:
            row.read_by_staff_at = utcnow()
    db.commit()
    return {"items": [message_to_dict(row) for row in rows]}


@router.post("/messages", status_code=201)
def send_message(
    client_id: int,
    payload: PortalMessageIn,
    user: User = Depends(get_current_accountant),
    db: Session = Depends(get_db),
):
    client = ensure_client_access(db, user, client_id)
    message = AccountingMessage(
        client_id=client.id,
        author_user_id=user.id,
        author_label=user.full_name,
        author_role=user.role,
        body=payload.body.strip(),
        read_by_staff_at=utcnow(),
    )
    db.add(message)
    db.flush()
    notify(
        db,
        client.customer_user_id,
        kind="message",
        title="New message from your accountant",
        body=f"{user.full_name}: {payload.body.strip()[:160]}",
        client_id=client.id,
    )
    db.commit()
    return message_to_dict(message)


@router.get("/notifications")
def notifications(
    user: User = Depends(get_current_accountant_or_customer),
    db: Session = Depends(get_db),
):
    return _serialize_notifications(db, user)


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: int,
    user: User = Depends(get_current_accountant_or_customer),
    db: Session = Depends(get_db),
):
    row = db.get(AccountingNotification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    row.read_at = utcnow()
    db.commit()
    return notification_to_dict(row)


@router.post("/notifications/read-all")
def read_all_notifications(
    user: User = Depends(get_current_accountant_or_customer),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(AccountingNotification)
        .filter(
            AccountingNotification.user_id == user.id,
            AccountingNotification.read_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.read_at = utcnow()
    db.commit()
    return {"updated": len(rows)}


# ---------------------------------------------------------------- customer portal


@router.get("/customer/overview")
def customer_overview(
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    client = client_for_customer(db, user)
    if client is None:
        return {"linked": False, "message": "No accounting engagement is linked to your account yet."}
    tasks = (
        db.query(AccountingTask)
        .filter(
            AccountingTask.client_id == client.id,
            AccountingTask.status.notin_(("cancelled",)),
        )
        .order_by(AccountingTask.due_date.is_(None), AccountingTask.due_date)
        .all()
    )
    reports = (
        db.query(AccountingReport)
        .filter(
            AccountingReport.client_id == client.id,
            AccountingReport.status.in_(("approved", "delivered")),
        )
        .order_by(AccountingReport.created_at.desc())
        .limit(20)
        .all()
    )
    invoices = (
        db.query(AccountingInvoice)
        .filter(AccountingInvoice.client_id == client.id)
        .order_by(AccountingInvoice.issue_date.desc())
        .all()
    )
    requests = (
        db.query(AccountingDocumentRequest)
        .filter(AccountingDocumentRequest.client_id == client.id)
        .order_by(AccountingDocumentRequest.created_at.desc())
        .all()
    )
    documents = (
        db.query(AccountingDocument)
        .filter(
            AccountingDocument.client_id == client.id,
            (AccountingDocument.visibility == "shared")
            | (AccountingDocument.uploaded_by_user_id == user.id),
        )
        .order_by(AccountingDocument.created_at.desc())
        .all()
    )
    messages = (
        db.query(AccountingMessage)
        .filter(AccountingMessage.client_id == client.id)
        .order_by(AccountingMessage.created_at)
        .all()
    )
    for message in messages:
        if message.author_role != "customer" and message.read_by_customer_at is None:
            message.read_by_customer_at = utcnow()
    db.commit()
    today = date.today()
    return {
        "linked": True,
        "client": {
            "id": client.id,
            "code": client.code,
            "business_name": client.business_name,
            "contact_name": client.contact_name,
            "service_package": client.service_package,
            "status": client.status,
            "financial_year": client.financial_year,
            "gstin": client.gstin,
            "senior_name": client.senior_accountant.full_name if client.senior_accountant else None,
            "junior_name": client.assigned_junior.full_name if client.assigned_junior else None,
        },
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "service_type": task.service_type,
                "status": task.status,
                "priority": task.priority,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "progress": task.progress,
                "days_remaining": days_until(task.due_date),
                "delivered_at": task.delivered_at.isoformat() if task.delivered_at else None,
                "update_note": task.review_notes if task.status == "changes_requested" else None,
            }
            for task in tasks
        ],
        "counts": {
            "active_tasks": sum(
                1 for task in tasks if task.status in OPEN_TASK_STATUSES
            ),
            "awaiting_documents": sum(1 for row in requests if row.status == "pending"),
            "approved_reports": len(reports),
            "outstanding_invoices": sum(1 for inv in invoices if inv.outstanding_amount > 0),
            "overdue_tasks": sum(
                1
                for task in tasks
                if task.due_date and task.due_date < today and task.status not in ("approved", "delivered")
            ),
        },
        "document_requests": [document_request_to_dict(row) for row in requests if row.status == "pending"],
        "reports": [report_to_dict(row) for row in reports],
        "invoices": [invoice_to_dict(row) for row in invoices],
        "documents": [document_to_dict(row) for row in documents],
        "messages": [message_to_dict(row) for row in messages],
        "notifications": _serialize_notifications(db, user),
    }


@router.post("/customer/documents", status_code=201)
def customer_upload_document(
    payload: AccountingDocumentIn,
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    client = _require_customer_client(db, user)
    if payload.client_id != client.id:
        raise HTTPException(status_code=403, detail="You can only upload documents to your own account.")
    document = _create_document(db, client, user, payload, source="customer", visibility="shared")
    db.commit()
    return document_to_dict(document)


@router.get("/customer/documents")
def customer_documents(
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    client = _require_customer_client(db, user)
    rows = (
        db.query(AccountingDocument)
        .filter(
            AccountingDocument.client_id == client.id,
            (AccountingDocument.visibility == "shared")
            | (AccountingDocument.uploaded_by_user_id == user.id),
        )
        .order_by(AccountingDocument.created_at.desc())
        .all()
    )
    return {"items": [document_to_dict(row) for row in rows]}


@router.get("/customer/document-requests")
def customer_document_requests(
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    client = _require_customer_client(db, user)
    rows = (
        db.query(AccountingDocumentRequest)
        .filter(AccountingDocumentRequest.client_id == client.id)
        .order_by(AccountingDocumentRequest.created_at.desc())
        .all()
    )
    return {"items": [document_request_to_dict(row) for row in rows]}


@router.get("/customer/quotations")
def customer_quotations(
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    enquiries = db.query(AccountingEnquiry.id).filter(
        (AccountingEnquiry.email == user.email.lower())
        | (AccountingEnquiry.customer_user_id == user.id)
    )
    client = client_for_customer(db, user)
    addressed = AccountingQuotation.enquiry_id.in_(enquiries)
    if client is not None:
        addressed = addressed | (AccountingQuotation.client_id == client.id)
    rows = (
        db.query(AccountingQuotation)
        .filter(
            addressed,
            AccountingQuotation.status.in_(("sent", "accepted", "declined")),
        )
        .order_by(AccountingQuotation.created_at.desc())
        .all()
    )
    return {
        "items": [quotation_to_dict(row, internal=False) for row in rows],
        "note": (
            "Only quotations approved and sent by the practice appear here. Accepting a "
            "quotation records your decision; it does not charge any amount."
        ),
    }


@router.get("/customer/quotation-requests")
def customer_quotation_requests(
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(AccountingEnquiry)
        .filter(
            (AccountingEnquiry.email == user.email.lower())
            | (AccountingEnquiry.customer_user_id == user.id)
        )
        .order_by(AccountingEnquiry.created_at.desc())
        .all()
    )
    return {
        "items": [
            {
                **enquiry_to_dict(enquiry, internal=False),
                "estimate": estimate_payload(db, enquiry.annual_turnover),
            }
            for enquiry in rows
        ]
    }


@router.post(
    "/customer/quotation-requests",
    status_code=201,
    dependencies=[Depends(rate_limit("customer_quotation_request", 5, 300))],
)
def create_customer_quotation_request(
    payload: AccountingEnquiryIn,
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    client = client_for_customer(db, user)
    reference = next_enquiry_reference(db)
    benchmark = benchmark_for(db, payload.annual_turnover)
    enquiry = AccountingEnquiry(
        reference=reference,
        business_name=payload.business_name.strip(),
        contact_name=payload.contact_name.strip(),
        email=payload.email.lower(),
        phone=payload.phone,
        business_type=payload.business_type,
        turnover_range=payload.turnover_range,
        gst_status=payload.gst_status,
        services=list(dict.fromkeys(payload.services)),
        monthly_transactions=payload.monthly_transactions,
        requirements=payload.requirements,
        annual_turnover=payload.annual_turnover,
        bank_accounts=payload.bank_accounts,
        payroll_required=payload.payroll_required,
        inventory_required=payload.inventory_required,
        financial_year=payload.financial_year,
        benchmark_annual=benchmark,
        status="new",
        source="client_portal",
        customer_user_id=user.id,
    )
    db.add(enquiry)
    db.flush()
    _audit(
        db,
        user,
        "accounting.quotation_requested",
        entity="accounting_enquiry",
        entity_id=enquiry.id,
        detail={
            "reference": reference,
            "client_id": client.id if client is not None else None,
            "source": "client_portal",
        },
    )
    db.commit()
    return {
        "reference": reference,
        "status": enquiry.status,
        "estimate": estimate_payload(db, payload.annual_turnover),
        "message": (
            "Quotation request received. A senior accountant reviews the scope and sends an "
            "approved quotation to your portal. No amount is charged by requesting or "
            "accepting a quotation."
        ),
    }


@router.get("/customer/quotations/{quotation_id}/pdf")
def customer_quotation_pdf(
    quotation_id: int,
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    quotation = _quotation_for_customer(db, user, quotation_id)
    if quotation_status(quotation) not in ("sent", "accepted", "declined", "expired"):
        raise HTTPException(
            status_code=409,
            detail="This quotation has not been approved and sent yet.",
        )
    content = build_quotation_pdf(
        quotation,
        approved_by_name=quotation.approved_by.full_name if quotation.approved_by else None,
        prepared_by_name=quotation.prepared_by.full_name if quotation.prepared_by else None,
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{quotation.number}.pdf"'},
    )


@router.post("/customer/quotations/{quotation_id}/decision")
def customer_quotation_decision(
    quotation_id: int,
    payload: QuotationDecisionIn,
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    quotation = _quotation_for_customer(db, user, quotation_id)
    current_status = quotation_status(quotation)
    if current_status in ("accepted", "declined"):
        raise HTTPException(status_code=409, detail="This quotation already has a recorded decision.")
    if current_status == "expired":
        raise HTTPException(status_code=409, detail="This quotation has expired. Request a fresh quote.")
    if current_status != "sent":
        raise HTTPException(
            status_code=409,
            detail="This quotation is not open for a customer decision.",
        )
    quotation.status = payload.decision
    quotation.responded_at = utcnow()
    quotation.response_note = payload.note
    if payload.decision == "accepted":
        quotation.accepted_at = utcnow()
    if quotation.enquiry is not None:
        quotation.enquiry.status = "quote_accepted" if payload.decision == "accepted" else "declined"
    _audit(
        db,
        user,
        f"accounting.quotation_{payload.decision}",
        entity="accounting_quotation",
        entity_id=quotation.id,
        detail={"from": "customer_portal", "payment_triggered": False},
    )
    db.commit()
    return quotation_to_dict(quotation, internal=False)


@router.get("/customer/messages")
def customer_messages(
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    client = _require_customer_client(db, user)
    rows = (
        db.query(AccountingMessage)
        .filter(AccountingMessage.client_id == client.id)
        .order_by(AccountingMessage.created_at)
        .all()
    )
    for row in rows:
        if row.author_role != "customer" and row.read_by_customer_at is None:
            row.read_by_customer_at = utcnow()
    db.commit()
    return {"items": [message_to_dict(row) for row in rows]}


@router.post("/customer/messages", status_code=201)
def customer_send_message(
    payload: PortalMessageIn,
    user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    client = _require_customer_client(db, user)
    message = AccountingMessage(
        client_id=client.id,
        author_user_id=user.id,
        author_label=user.full_name,
        author_role="customer",
        body=payload.body.strip(),
        read_by_customer_at=utcnow(),
    )
    db.add(message)
    db.flush()
    notify(
        db,
        client.assigned_junior_user_id or client.senior_accountant_user_id,
        kind="message",
        title="New message from client",
        body=f"{client.business_name}: {payload.body.strip()[:160]}",
        client_id=client.id,
    )
    db.commit()
    return message_to_dict(message)


# ---------------------------------------------------------------- audit


@router.get("/senior/audit")
def accounting_audit(
    client_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    user: User = Depends(get_current_senior_accountant),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.action.like("accounting.%"))
        .order_by(AuditEvent.created_at.desc())
        .limit(1000)
        .all()
    )
    if client_id is not None:
        rows = [
            row
            for row in rows
            if str((row.detail or {}).get("client_id")) == str(client_id)
            or (row.entity_type == "accounting_client" and row.entity_id == str(client_id))
        ]
    return {
        "items": [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "detail": row.detail,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows[:limit]
        ]
    }


router.include_router(public_router)
