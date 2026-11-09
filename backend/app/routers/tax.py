"""Tax Center API: GST calculator, input tax credit, reports and income-tax estimates.

No endpoint here calls a model or an external service. GST arithmetic comes from
``app.services.gst``, reporting from ``app.services.gst_reports`` and income tax from
``app.services.income_tax``, which reads slabs and caps from the stored rule sets.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GstCatalogueChange, HSNSACClassification, IncomeTaxEstimate, ITCEntry, Product, User
from ..schemas import (
    GstCatalogueDecisionIn,
    GstCatalogueSettingsIn,
    GstCatalogueUpdateIn,
    HSNClassificationIn,
    IncomeTaxCalculateIn,
    IncomeTaxCompareIn,
    IncomeTaxEstimateSaveIn,
    ITCEntryIn,
    TaxApprovalIn,
    TaxCalculatorIn,
)
from ..security import get_current_owner
from ..services.audit import log_audit
from ..services.business_context import active_business
from ..services.finance import q2
from ..services.gst import (
    GSTValidationError,
    ensure_default_gst_rates,
    normalize_rate,
    state_options,
)
from ..services.gst_reports import (
    ITC_STATUSES,
    calculate_gst,
    create_itc_entry,
    gst_report,
    hsn_options,
    hsn_to_dict,
    invoice_has_verified_hsn,
    itc_summary,
    net_gst,
    validate_hsn_code,
)
from ..services.gst_catalogue import (
    approval_mode,
    catalogue_rows,
    change_to_dict,
    decide_change,
    export_catalogue_workbook,
    history as catalogue_history,
    pending_changes,
    product_to_dict,
    request_change,
    set_approval_mode,
)
from ..services.income_tax import (
    DISCLAIMER,
    TaxValidationError,
    compute_comparison,
    compute_income_tax,
    financial_years,
    rules_payload,
    seed_tax_rules,
)

router = APIRouter(tags=["Tax"])


def _fail(exc: Exception, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def _jsonable(value: Any) -> Any:
    """JSON columns cannot hold Decimal, so stored snapshots keep exact values as strings."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _current_financial_year() -> str:
    today = date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _empty_inputs() -> dict:
    return {
        "salary": {
            "gross_salary": "0",
            "basic_salary": "0",
            "hra_received": "0",
            "rent_paid": "0",
            "professional_tax": "0",
            "employer_nps": "0",
            "metro_city": False,
        },
        "business": {
            "net_profit": "0",
            "presumptive": "none",
            "gross_receipts": "0",
            "digital_receipts_pct": "0",
        },
        "other_income": "0",
        "capital_gains": {
            "equity_stcg": "0",
            "equity_ltcg": "0",
            "other_ltcg": "0",
            "other_stcg": "0",
        },
        "deductions": {
            "80C": "0",
            "80CCD1B": "0",
            "80D": "0",
            "80TTA": "0",
            "80TTB": "0",
            "24B": "0",
            "80G": "0",
            "80E": "0",
            "other": "0",
        },
    }


# ------------------------------------------------------------------ GST


@router.get("/tax/gst/options")
def gst_options(user: User = Depends(get_current_owner), db: Session = Depends(get_db)):
    rates = ensure_default_gst_rates(db, user)
    profile = active_business(db, user)
    return {
        "states": state_options(),
        "supplier_state": {
            "name": profile.state if profile else None,
            "code": profile.state_code if profile else None,
        },
        "gst_rates": [
            {"rate": q2(row.rate), "label": row.label, "active": row.is_active}
            for row in sorted(rates, key=lambda row: row.sort_order)
        ],
        "hsn": [hsn_to_dict(row) for row in hsn_options(db, user)],
        "hsn_coverage": invoice_has_verified_hsn(db, user),
        "note": (
            "Rates come from your own GST settings. Every HSN/SAC code and rate must be confirmed "
            "against the notification that applies to the goods or service before you rely on it."
        ),
    }


@router.post("/tax/gst/calculate")
def gst_calculator(
    payload: TaxCalculatorIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    profile = active_business(db, user)
    supplier_code = payload.supplier_state_code or (profile.state_code if profile else None)
    place_code = payload.place_of_supply_state_code
    try:
        for rate in {line.gst_rate for line in payload.lines}:
            normalize_rate(rate)
        return calculate_gst(
            [line.model_dump() for line in payload.lines],
            supplier_state_code=supplier_code,
            place_of_supply_state_code=place_code,
            other_charges=payload.other_charges,
            round_to_rupee=payload.round_to_rupee,
        )
    except GSTValidationError as exc:
        raise _fail(exc) from exc


@router.get("/tax/gst/report")
def gst_invoice_report(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    try:
        return gst_report(db, user, date_from=date_from, date_to=date_to)
    except GSTValidationError as exc:
        raise _fail(exc) from exc


@router.get("/tax/gst/net")
def gst_net_position(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    try:
        return net_gst(db, user, date_from=date_from, date_to=date_to)
    except GSTValidationError as exc:
        raise _fail(exc) from exc


@router.get("/tax/gst/itc")
def list_itc(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    try:
        return itc_summary(db, user, date_from=date_from, date_to=date_to)
    except GSTValidationError as exc:
        raise _fail(exc) from exc


@router.post("/tax/gst/itc", status_code=201)
def add_itc(
    payload: ITCEntryIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    try:
        entry = create_itc_entry(db, user, payload, user)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="itc.created",
        entity_type="itc_entry",
        entity_id=entry.id,
        detail={
            "invoice_number": entry.invoice_number,
            "taxable_value": str(entry.taxable_value),
            "eligible_amount": str(entry.eligible_amount),
        },
    )
    db.commit()
    return {
        "id": entry.id,
        "supplier_name": entry.supplier_name,
        "invoice_number": entry.invoice_number,
        "eligible_amount": q2(entry.eligible_amount),
        "status": entry.status,
    }


@router.patch("/tax/gst/itc/{entry_id}")
def update_itc_status(
    entry_id: int,
    status: str = Query(...),
    eligible_amount: Decimal | None = Query(default=None, ge=0),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if status not in ITC_STATUSES:
        raise HTTPException(status_code=400, detail="ITC status must be eligible, claimed or blocked.")
    entry = (
        db.query(ITCEntry)
        .filter(ITCEntry.id == entry_id, ITCEntry.user_id == user.id)
        .one_or_none()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Input-credit entry not found.")
    tax = q2(entry.cgst_amount + entry.sgst_amount + entry.igst_amount)
    if eligible_amount is not None:
        if eligible_amount > tax:
            raise HTTPException(
                status_code=400, detail="Eligible credit cannot exceed the GST on the bill."
            )
        entry.eligible_amount = q2(eligible_amount)
    if status == "blocked":
        entry.eligible_amount = Decimal("0.00")
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="itc.status_changed",
        entity_type="itc_entry",
        entity_id=entry.id,
        detail={"status": status, "eligible_amount": str(entry.eligible_amount)},
    )
    entry.status = status
    db.commit()
    return {"id": entry.id, "status": entry.status, "eligible_amount": q2(entry.eligible_amount)}


@router.delete("/tax/gst/itc/{entry_id}", status_code=204)
def delete_itc(
    entry_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    entry = (
        db.query(ITCEntry)
        .filter(ITCEntry.id == entry_id, ITCEntry.user_id == user.id)
        .one_or_none()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Input-credit entry not found.")
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="itc.deleted",
        entity_type="itc_entry",
        entity_id=entry.id,
        detail={"invoice_number": entry.invoice_number},
    )
    db.delete(entry)
    db.commit()
    return None


@router.get("/tax/gst/hsn")
def list_hsn(user: User = Depends(get_current_owner), db: Session = Depends(get_db)):
    return {
        "items": [hsn_to_dict(row) for row in hsn_options(db, user)],
        "coverage": invoice_has_verified_hsn(db, user),
        "note": (
            "A classification is only a stored reference. Mark it verified once you have checked the "
            "code and rate against the GST rate notification for that goods or service."
        ),
    }


@router.post("/tax/gst/hsn", status_code=201)
def create_hsn(
    payload: HSNClassificationIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    try:
        code = validate_hsn_code(payload.code, payload.kind)
        rate = normalize_rate(payload.gst_rate)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    existing = (
        db.query(HSNSACClassification)
        .filter(HSNSACClassification.user_id == user.id, HSNSACClassification.code == code)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"HSN/SAC {code} is already stored. Update that entry instead."
        )
    row = HSNSACClassification(
        user_id=user.id,
        code=code,
        description=payload.description.strip(),
        kind=payload.kind,
        gst_rate=rate,
        verified=payload.verified,
        note=(payload.note or "").strip() or None,
        created_by_user_id=user.id,
    )
    db.add(row)
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="hsn.created",
        entity_type="hsn_classification",
        entity_id=code,
        detail={"gst_rate": str(rate), "verified": payload.verified},
    )
    db.commit()
    return hsn_to_dict(row)


@router.put("/tax/gst/hsn/{hsn_id}")
def update_hsn(
    hsn_id: int,
    payload: HSNClassificationIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    row = (
        db.query(HSNSACClassification)
        .filter(HSNSACClassification.id == hsn_id, HSNSACClassification.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="HSN/SAC classification not found.")
    try:
        code = validate_hsn_code(payload.code, payload.kind)
        rate = normalize_rate(payload.gst_rate)
    except GSTValidationError as exc:
        raise _fail(exc) from exc
    clash = (
        db.query(HSNSACClassification)
        .filter(
            HSNSACClassification.user_id == user.id,
            HSNSACClassification.code == code,
            HSNSACClassification.id != row.id,
        )
        .one_or_none()
    )
    if clash is not None:
        raise HTTPException(status_code=409, detail=f"HSN/SAC {code} is already stored.")
    row.code = code
    row.description = payload.description.strip()
    row.kind = payload.kind
    row.gst_rate = rate
    row.verified = payload.verified
    row.note = (payload.note or "").strip() or None
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="hsn.updated",
        entity_type="hsn_classification",
        entity_id=row.id,
        detail={"code": code, "gst_rate": str(rate), "verified": payload.verified},
    )
    db.commit()
    return hsn_to_dict(row)


@router.delete("/tax/gst/hsn/{hsn_id}", status_code=204)
def delete_hsn(
    hsn_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    row = (
        db.query(HSNSACClassification)
        .filter(HSNSACClassification.id == hsn_id, HSNSACClassification.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="HSN/SAC classification not found.")
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="hsn.deleted",
        entity_type="hsn_classification",
        entity_id=row.code,
        detail={"code": row.code},
    )
    db.delete(row)
    db.commit()
    return None


# --------------------------------------------------------- GST catalogue


@router.get("/tax/gst/catalogue")
def gst_catalogue(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=300, ge=1, le=1000),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    items = catalogue_rows(db, user.id, search=q, limit=limit)
    pending = pending_changes(db, user.id)
    return {
        "items": items,
        "count": len(items),
        "approval_mode": approval_mode(db, user),
        "pending_changes": pending,
        "pending_count": len(pending),
        "note": (
            "Each catalogue item carries its own GST rate and HSN/SAC. Changes apply to new "
            "invoices only; issued invoices keep the tax snapshot they were issued with."
        ),
    }


@router.patch("/tax/gst/catalogue/{product_id}")
def update_gst_catalogue_item(
    product_id: int,
    payload: GstCatalogueUpdateIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == user.id)
        .one_or_none()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Catalogue item not found.")
    change = request_change(
        db,
        product=product,
        actor=user,
        role="owner",
        gst_rate=payload.gst_rate,
        hsn_sac=payload.hsn_sac,
        item_type=payload.item_type,
        hsn_verified=payload.hsn_verified,
        effective_from=payload.effective_from,
        reason=payload.reason,
    )
    return {
        "item": product_to_dict(db, product),
        "change": change_to_dict(db, change),
        "message": "GST catalogue updated. New invoices will use the new rate.",
    }


@router.get("/tax/gst/catalogue/history")
def gst_catalogue_history(
    product_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return {
        "items": catalogue_history(db, user.id, product_id=product_id, limit=limit),
        "pending": pending_changes(db, user.id),
    }


@router.post("/tax/gst/catalogue/changes/{change_id}/decision")
def decide_gst_catalogue_change(
    change_id: int,
    payload: GstCatalogueDecisionIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    change = (
        db.query(GstCatalogueChange)
        .filter(
            GstCatalogueChange.id == change_id,
            GstCatalogueChange.owner_user_id == user.id,
        )
        .one_or_none()
    )
    if change is None:
        raise HTTPException(status_code=404, detail="Catalogue change not found.")
    change = decide_change(
        db, change=change, owner=user, approve=payload.approve, note=payload.note
    )
    return {
        "change": change_to_dict(db, change),
        "item": product_to_dict(db, change.product),
        "message": "Catalogue change approved." if payload.approve else "Catalogue change rejected.",
    }


@router.put("/tax/gst/catalogue/settings")
def update_gst_catalogue_settings(
    payload: GstCatalogueSettingsIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return set_approval_mode(db, user, payload.approval_mode)


@router.get("/tax/gst/catalogue/export")
def export_gst_catalogue(
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    content = export_catalogue_workbook(db, user)
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="gst.catalogue.exported",
        entity_type="gst_catalogue",
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


# ------------------------------------------------------------------ income tax


@router.get("/tax/income/rules")
def income_tax_rules(
    financial_year: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if not financial_years(db):
        seed_tax_rules(db)
    try:
        payload = rules_payload(db, financial_year)
    except TaxValidationError as exc:
        raise _fail(exc) from exc
    payload["current_financial_year"] = _current_financial_year()
    payload["today"] = date.today().isoformat()
    return payload


@router.post("/tax/income/calculate")
def income_tax_calculate(
    payload: IncomeTaxCalculateIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    try:
        return compute_income_tax(
            db,
            financial_year=payload.financial_year,
            regime=payload.regime,
            inputs=payload.inputs.to_engine(),
        )
    except TaxValidationError as exc:
        raise _fail(exc) from exc


@router.post("/tax/income/compare")
def income_tax_compare(
    payload: IncomeTaxCompareIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    try:
        return compute_comparison(
            db, financial_year=payload.financial_year, inputs=payload.inputs.to_engine()
        )
    except TaxValidationError as exc:
        raise _fail(exc) from exc


def _estimate_payload(row: IncomeTaxEstimate) -> dict:
    return {
        "id": row.id,
        "financial_year": row.financial_year,
        "regime": row.regime,
        "rule_version": row.rule_version,
        "status": row.status,
        "approved_by_name": row.approved_by_name,
        "membership_number": row.membership_number,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "approval_note": row.approval_note,
        "created_at": row.created_at.isoformat(),
        "result": row.result,
        "inputs": row.inputs,
    }


@router.get("/tax/income/estimates")
def list_estimates(
    user: User = Depends(get_current_owner), db: Session = Depends(get_db)
):
    rows = (
        db.query(IncomeTaxEstimate)
        .filter(IncomeTaxEstimate.user_id == user.id)
        .order_by(IncomeTaxEstimate.created_at.desc(), IncomeTaxEstimate.id.desc())
        .limit(50)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "financial_year": row.financial_year,
                "regime": row.regime,
                "rule_version": row.rule_version,
                "status": row.status,
                "total_liability": (row.result or {}).get("tax", {}).get("total_liability"),
                "total_income": (row.result or {}).get("total_income"),
                "approved_by_name": row.approved_by_name,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "count": len(rows),
        "disclaimer": DISCLAIMER,
    }


@router.get("/tax/income/estimates/{estimate_id}")
def get_estimate(
    estimate_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    row = (
        db.query(IncomeTaxEstimate)
        .filter(IncomeTaxEstimate.id == estimate_id, IncomeTaxEstimate.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Tax estimate not found.")
    return _estimate_payload(row)


@router.post("/tax/income/estimates", status_code=201)
def save_estimate(
    payload: IncomeTaxEstimateSaveIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    engine_inputs = payload.inputs.to_engine()
    try:
        if payload.regime:
            result = compute_income_tax(
                db,
                financial_year=payload.financial_year,
                regime=payload.regime,
                inputs=engine_inputs,
            )
        else:
            comparison = compute_comparison(
                db, financial_year=payload.financial_year, inputs=engine_inputs
            )
            result = comparison["regimes"][comparison["recommended_regime"]]
            result["comparison"] = {
                "recommended_regime": comparison["recommended_regime"],
                "savings": comparison["savings"],
            }
    except TaxValidationError as exc:
        raise _fail(exc) from exc
    row = IncomeTaxEstimate(
        user_id=user.id,
        financial_year=result["financial_year"],
        regime=result["regime"],
        rule_set_id=result["rule_set_id"],
        rule_version=result["rule_version"],
        inputs=_jsonable(engine_inputs),
        result=_jsonable(result),
        status="draft",
        created_by_user_id=user.id,
    )
    db.add(row)
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="tax_estimate.saved",
        entity_type="income_tax_estimate",
        entity_id=row.id,
        detail={"financial_year": row.financial_year, "regime": row.regime},
    )
    db.commit()
    return _estimate_payload(row)


@router.post("/tax/income/estimates/{estimate_id}/approve")
def approve_estimate(
    estimate_id: int,
    payload: TaxApprovalIn,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    row = (
        db.query(IncomeTaxEstimate)
        .filter(IncomeTaxEstimate.id == estimate_id, IncomeTaxEstimate.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Tax estimate not found.")
    if row.status == "approved":
        raise HTTPException(
            status_code=409,
            detail="This estimate is already approved. Reopen it before changing the sign-off.",
        )
    row.status = "approved"
    row.approved_by_name = payload.approved_by_name.strip()
    row.membership_number = payload.membership_number.strip()
    row.approval_note = (payload.approval_note or "").strip() or None
    row.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="tax_estimate.approved",
        entity_type="income_tax_estimate",
        entity_id=row.id,
        detail={
            "approved_by_name": row.approved_by_name,
            "membership_number": row.membership_number,
            "rule_version": row.rule_version,
        },
    )
    db.commit()
    return _estimate_payload(row)


@router.post("/tax/income/estimates/{estimate_id}/reopen")
def reopen_estimate(
    estimate_id: int,
    user: User = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    row = (
        db.query(IncomeTaxEstimate)
        .filter(IncomeTaxEstimate.id == estimate_id, IncomeTaxEstimate.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Tax estimate not found.")
    if row.status != "approved":
        raise HTTPException(status_code=409, detail="Only an approved estimate can be reopened.")
    log_audit(
        db,
        user_id=user.id,
        actor="owner",
        action="tax_estimate.reopened",
        entity_type="income_tax_estimate",
        entity_id=row.id,
        detail={"previous_approver": row.approved_by_name},
    )
    row.status = "draft"
    row.approved_by_name = None
    row.membership_number = None
    row.approved_at = None
    row.approval_note = None
    db.commit()
    return _estimate_payload(row)


# ------------------------------------------------------------------ overview


@router.get("/tax/overview")
def tax_overview(
    user: User = Depends(get_current_owner), db: Session = Depends(get_db)
):
    if not financial_years(db):
        seed_tax_rules(db)
    years = financial_years(db)
    fy = _current_financial_year()
    if fy not in years and years:
        fy = years[0]
    today = date.today()
    quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    gst = net_gst(db, user, date_from=quarter_start, date_to=today)
    estimates = (
        db.query(IncomeTaxEstimate)
        .filter(IncomeTaxEstimate.user_id == user.id, IncomeTaxEstimate.financial_year == fy)
        .order_by(IncomeTaxEstimate.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        "financial_year": fy,
        "financial_years": years,
        "gst": gst,
        "income_tax": {
            "estimate_count": len(estimates),
            "latest": [
                {
                    "id": row.id,
                    "regime": row.regime,
                    "status": row.status,
                    "rule_version": row.rule_version,
                    "total_liability": (row.result or {}).get("tax", {}).get("total_liability"),
                    "approved_by_name": row.approved_by_name,
                }
                for row in estimates
            ],
        },
        "empty_inputs": _empty_inputs(),
        "disclaimer": DISCLAIMER,
    }
