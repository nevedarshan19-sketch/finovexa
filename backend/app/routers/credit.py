"""Credit Control API: customer and supplier credit, payables, alerts, reports.

Routes are owner-only. All figures come from the shared credit service, so the
dashboard, statements and exports cannot disagree with one another.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import (
    AdjustmentVoidIn,
    CreditAlertEvaluateIn,
    CreditAlertSettingsIn,
    CustomerAdjustmentIn,
    CustomerCreditIn,
    SupplierIn,
    SupplierMatchIn,
    SupplierPatchIn,
    SupplierPaymentIn,
    SupplierPaymentVoidIn,
)
from ..security import get_current_owner
from ..services import credit, credit_reports
from ..services.file_store import content_disposition

router = APIRouter(prefix="/credit", tags=["Credit control"])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/summary")
def credit_summary(
    user: User = Depends(get_current_owner), db: Session = Depends(get_db)
):
    return credit.summary(db, user.id)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


@router.get("/customers")
def list_customers(
    q: str | None = None,
    risk: str | None = None,
    sort: str = "name",
    order: str = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.customer_directory(
        db, user.id, q=q, risk=risk, sort=sort, order=order, page=page, page_size=page_size
    )


@router.get("/customers/{customer_id}")
def customer_detail(
    customer_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.customer_detail(db, user.id, customer_id)


@router.patch("/customers/{customer_id}/credit")
def update_customer_credit(
    customer_id: int,
    payload: CustomerCreditIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.update_customer_credit(
        db, user, customer_id, payload.model_dump(exclude_unset=True)
    )


@router.get("/customers/{customer_id}/ledger")
def customer_ledger(
    customer_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.customer_ledger(
        db, user.id, customer_id, date_from=date_from, date_to=date_to
    )


@router.post("/customers/{customer_id}/adjustments", status_code=201)
def create_adjustment(
    customer_id: int,
    payload: CustomerAdjustmentIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if payload.customer_id != customer_id:
        raise HTTPException(status_code=400, detail="Customer does not match the request path.")
    return credit.create_adjustment(
        db, user, customer_id, payload.model_dump(exclude={"customer_id"})
    )


@router.post("/adjustments/{adjustment_id}/void")
def void_adjustment(
    adjustment_id: int,
    payload: AdjustmentVoidIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.void_adjustment(db, user, adjustment_id, payload.reason)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


@router.get("/suppliers")
def list_suppliers(
    q: str | None = None,
    status: str | None = None,
    sort: str = "name",
    order: str = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.supplier_directory(
        db, user.id, q=q, status=status, sort=sort, order=order, page=page, page_size=page_size
    )


@router.post("/suppliers", status_code=201)
def create_supplier(
    payload: SupplierIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.create_supplier(db, user, payload.model_dump())


@router.get("/suppliers/{supplier_id}")
def supplier_detail(
    supplier_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.supplier_detail(db, user.id, supplier_id)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(
    supplier_id: int,
    payload: SupplierPatchIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.update_supplier(
        db, user, supplier_id, payload.model_dump(exclude_unset=True)
    )


@router.get("/suppliers/{supplier_id}/ledger")
def supplier_ledger(
    supplier_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.supplier_ledger(
        db, user.id, supplier_id, date_from=date_from, date_to=date_to
    )


@router.post("/suppliers/match")
def match_suppliers(
    payload: SupplierMatchIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.match_suppliers(db, user, dry_run=payload.dry_run)


# ---------------------------------------------------------------------------
# Purchase bills and supplier payments
# ---------------------------------------------------------------------------


@router.get("/bills")
def list_bills(
    supplier_id: int | None = None,
    unmatched: bool = False,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.list_bills(
        db,
        user.id,
        supplier_id=supplier_id,
        unmatched=unmatched,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post("/supplier-payments", status_code=201)
def create_supplier_payment(
    payload: SupplierPaymentIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.create_supplier_payment(db, user, payload.model_dump())


@router.post("/supplier-payments/{payment_id}/void")
def void_supplier_payment(
    payment_id: int,
    payload: SupplierPaymentVoidIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.void_supplier_payment(db, user, payment_id, payload.reason)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@router.get("/alert-settings")
def alert_settings(
    user: User = Depends(get_current_owner), db: Session = Depends(get_db)
):
    return credit.settings_values(db, user.id)


@router.put("/alert-settings")
def update_alert_settings(
    payload: CreditAlertSettingsIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.update_settings(db, user, payload.model_dump())


@router.get("/alerts")
def list_alerts(
    status: str = "open",
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.list_alerts(db, user.id, status=status, limit=limit)


@router.post("/alerts/evaluate")
def evaluate_alerts(
    payload: CreditAlertEvaluateIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.evaluate_alerts(db, user, send_emails=payload.send_email)


@router.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(
    alert_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit.dismiss_alert(db, user, alert_id)


# ---------------------------------------------------------------------------
# Reports and exports
# ---------------------------------------------------------------------------


@router.get("/reports")
def list_reports(user: User = Depends(get_current_owner)):
    return {"items": credit_reports.report_catalogue()}


@router.get("/reports/{report_key}")
def credit_report(
    report_key: str,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return credit_reports.report_payload(
        db,
        user,
        report_key,
        customer_id=customer_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/reports/{report_key}/export")
def export_credit_report(
    report_key: str,
    format: str = Query(default="xlsx", pattern="^(xlsx|pdf)$"),
    customer_id: int | None = None,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    payload = credit_reports.report_payload(
        db,
        user,
        report_key,
        customer_id=customer_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )
    filename = credit_reports.export_filename(payload, format)
    if format == "pdf":
        raw = credit_reports.build_pdf(payload)
        media_type = credit_reports.PDF_MEDIA_TYPE
    else:
        raw = credit_reports.build_xlsx(payload)
        media_type = credit_reports.XLSX_MEDIA_TYPE
    return Response(
        content=raw,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": content_disposition(filename),
        },
    )
