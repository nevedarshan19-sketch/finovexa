"""Configurable pricing rules and quotation totals.

Every public price lives in the database so an administrator can change it without a code
release. The accounting benchmark is deliberately indicative: a quotation only becomes
pricing once a senior accountant approves it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from ..models import ITRPrice, PriceHistory, PricingAddon, PricingSetting, SoftwareTier, User, utcnow
from .finance import q2

BENCHMARK_NOTE = (
    "Indicative only. The 2% benchmark is a starting point, not a final fee. A senior "
    "accountant reviews the scope, transaction volume and add-ons before approving a quotation."
)

DEFAULT_TERMS = (
    "1. This quotation covers the scope listed above for the stated financial year.\n"
    "2. Fees exclude GST and any government filing fees; taxes are shown separately on invoices.\n"
    "3. Books and documents are to be shared by the agreed monthly cut-off.\n"
    "4. Work outside the agreed scope is quoted separately before it is started.\n"
    "5. Quotation validity is stated above; acceptance after expiry requires a fresh review.\n"
    "6. Accepting this quotation does not charge any amount. A separate invoice and secure "
    "payment process apply.\n"
    "7. ITR filing is a separate paid service and is not included in bookkeeping packages."
)

SOFTWARE_TIER_SEED: tuple[dict, ...] = (
    {
        "key": "up_to_8_lakh",
        "label": "Up to ₹8 lakh",
        "turnover_min": Decimal("0"),
        "turnover_max": Decimal("800000"),
        "monthly_price": Decimal("300"),
        "description": "For very small businesses starting structured bookkeeping.",
        "features": ["Sales and purchase records", "GST-ready invoices", "Basic reports"],
        "sort_order": 1,
    },
    {
        "key": "8_to_15_lakh",
        "label": "Above ₹8–15 lakh",
        "turnover_min": Decimal("800000.01"),
        "turnover_max": Decimal("1500000"),
        "monthly_price": Decimal("500"),
        "description": "For growing proprietors and small partnerships.",
        "features": ["Everything in Up to ₹8 lakh", "Payment tracking", "Expense categories"],
        "sort_order": 2,
    },
    {
        "key": "15_to_30_lakh",
        "label": "Above ₹15–30 lakh",
        "turnover_min": Decimal("1500000.01"),
        "turnover_max": Decimal("3000000"),
        "monthly_price": Decimal("800"),
        "description": "For businesses with regular GST cycles and staff entries.",
        "features": ["Everything in ₹8–15 lakh", "Employee portal", "GST working papers"],
        "sort_order": 3,
    },
    {
        "key": "30_to_50_lakh",
        "label": "Above ₹30–50 lakh",
        "turnover_min": Decimal("3000000.01"),
        "turnover_max": Decimal("5000000"),
        "monthly_price": Decimal("1500"),
        "description": "For established businesses needing tighter controls.",
        "features": ["Everything in ₹15–30 lakh", "Approval workflows", "Cash-flow forecasting"],
        "sort_order": 4,
    },
    {
        "key": "50_lakh_to_1_crore",
        "label": "Above ₹50 lakh–₹1 crore",
        "turnover_min": Decimal("5000000.01"),
        "turnover_max": Decimal("10000000"),
        "monthly_price": Decimal("2500"),
        "description": "For businesses approaching the GST audit threshold.",
        "features": ["Everything in ₹30–50 lakh", "Audit trail", "Deadline tracking"],
        "sort_order": 5,
    },
    {
        "key": "above_1_crore",
        "label": "Above ₹1 crore",
        "turnover_min": Decimal("10000000.01"),
        "turnover_max": None,
        "monthly_price": Decimal("4000"),
        "description": "For larger businesses with multi-team operations.",
        "features": ["Everything in ₹50 lakh–₹1 crore", "Priority support", "Custom reporting"],
        "sort_order": 6,
    },
)

ITR_PRICE_SEED: tuple[dict, ...] = (
    {
        "key": "itr_1",
        "label": "Basic ITR-1",
        "description": "Salary, pension and simple interest income where ITR-1 applies.",
        "price_min": Decimal("999"),
        "price_max": None,
        "price_note": "Fixed price. Scope confirmed before filing.",
        "sort_order": 1,
    },
    {
        "key": "itr_2_itr_4",
        "label": "Standard ITR-2 / ITR-4",
        "description": "Capital gains, multiple properties or presumptive business income.",
        "price_min": Decimal("1999"),
        "price_max": None,
        "price_note": "Fixed price. Additional schedules may be quoted separately.",
        "sort_order": 2,
    },
    {
        "key": "itr_3",
        "label": "Business ITR-3",
        "description": "Business or professional income with books of account.",
        "price_min": Decimal("3999"),
        "price_max": None,
        "price_note": "Fixed price for a standard business return.",
        "sort_order": 3,
    },
    {
        "key": "complex_business_itr",
        "label": "Complex Business ITR",
        "description": "Multi-entity, audit-linked or complex capital-gain situations.",
        "price_min": Decimal("5000"),
        "price_max": Decimal("12000"),
        "price_note": "Subject to quotation. Final scope and fee are approved in writing.",
        "sort_order": 4,
    },
)

ADDON_SEED: tuple[dict, ...] = (
    {
        "key": "payroll_management",
        "label": "Payroll management",
        "description": "Monthly payroll register, deduction workings and payslip summaries.",
        "amount": None,
        "cadence": "annual",
        "sort_order": 1,
    },
    {
        "key": "inventory_accounting",
        "label": "Inventory accounting",
        "description": "Stock registers, movement reconciliation and valuation workings.",
        "amount": None,
        "cadence": "annual",
        "sort_order": 2,
    },
    {
        "key": "additional_bank_account",
        "label": "Additional bank account reconciliation",
        "description": "Per additional bank account beyond the first, if required.",
        "amount": None,
        "cadence": "annual",
        "sort_order": 3,
    },
    {
        "key": "prior_year_cleanup",
        "label": "Prior-year cleanup",
        "description": "One-time cleanup of opening balances and unreconciled ledgers.",
        "amount": None,
        "cadence": "one_time",
        "sort_order": 4,
    },
)

DEFAULT_SETTINGS = {
    "benchmark_percent": Decimal("2.00"),
    "annual_discount_percent": Decimal("0.00"),
    "quote_validity_days": 15,
    "tax_rate_percent": Decimal("18.00"),
    "tax_note": (
        "Prices exclude GST. Applicable taxes are shown separately on the invoice raised "
        "by the practice."
    ),
    "terms": DEFAULT_TERMS,
}


def get_pricing_settings(db: Session) -> PricingSetting:
    record = db.query(PricingSetting).filter(PricingSetting.key == "default").one_or_none()
    if record is None:
        record = PricingSetting(key="default", **DEFAULT_SETTINGS)
        db.add(record)
        db.flush()
    return record


def ensure_pricing_seed(db: Session) -> None:
    """Idempotently add the configured price catalogue and default rules."""
    get_pricing_settings(db)
    existing_tiers = {row[0] for row in db.query(SoftwareTier.key).all()}
    for seed in SOFTWARE_TIER_SEED:
        if seed["key"] not in existing_tiers:
            db.add(SoftwareTier(**seed))
    existing_itr = {row[0] for row in db.query(ITRPrice.key).all()}
    for seed in ITR_PRICE_SEED:
        if seed["key"] not in existing_itr:
            db.add(ITRPrice(**seed))
    existing_addons = {row[0] for row in db.query(PricingAddon.key).all()}
    for seed in ADDON_SEED:
        if seed["key"] not in existing_addons:
            db.add(PricingAddon(**seed))
    db.flush()


def _dimensionless(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value))


def money_round(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def tier_for_turnover(db: Session, turnover: Decimal | None) -> SoftwareTier | None:
    if turnover is None:
        return None
    amount = Decimal(turnover)
    tiers = (
        db.query(SoftwareTier)
        .filter(SoftwareTier.is_active.is_(True))
        .order_by(SoftwareTier.sort_order, SoftwareTier.turnover_min)
        .all()
    )
    for tier in tiers:
        if amount >= tier.turnover_min and (tier.turnover_max is None or amount <= tier.turnover_max):
            return tier
    return tiers[-1] if tiers and amount > (tiers[-1].turnover_min or 0) else None


def software_payload(db: Session) -> dict:
    settings_row = get_pricing_settings(db)
    discount = _dimensionless(settings_row.annual_discount_percent)
    tiers = (
        db.query(SoftwareTier)
        .filter(SoftwareTier.is_active.is_(True))
        .order_by(SoftwareTier.sort_order, SoftwareTier.turnover_min)
        .all()
    )
    items = []
    for tier in tiers:
        monthly = money_round(Decimal(tier.monthly_price))
        annual = money_round(monthly * 12 * (Decimal("1") - discount / Decimal("100")))
        items.append(
            {
                "id": tier.id,
                "key": tier.key,
                "label": tier.label,
                "turnover_min": float(tier.turnover_min),
                "turnover_max": float(tier.turnover_max) if tier.turnover_max is not None else None,
                "monthly_price": float(monthly),
                "annual_price": float(annual),
                "annual_effective_monthly": float(money_round(annual / Decimal("12"))),
                "description": tier.description,
                "features": tier.features or [],
            }
        )
    return {
        "tiers": items,
        "annual_discount_percent": float(discount),
        "annual_discount_configured": discount > 0,
        "billing_options": ["monthly", "annual"],
        "tax_rate_percent": float(settings_row.tax_rate_percent),
        "tax_note": settings_row.tax_note,
        "note": (
            "Business Manager subscription prices are separate from professional accounting "
            "fees. Subscription checkout is not enabled in this build; no plan auto-charges."
        ),
    }


def itr_payload(db: Session) -> dict:
    rows = (
        db.query(ITRPrice)
        .filter(ITRPrice.is_active.is_(True))
        .order_by(ITRPrice.sort_order, ITRPrice.id)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "key": row.key,
                "label": row.label,
                "description": row.description,
                "price_min": float(row.price_min),
                "price_max": float(row.price_max) if row.price_max is not None else None,
                "price_note": row.price_note,
            }
            for row in rows
        ],
        "note": (
            "ITR filing is a separate paid service. It is never included automatically with "
            "bookkeeping or GST packages. Complex returns are quoted and approved in writing."
        ),
    }


def addons_payload(db: Session, *, include_inactive: bool = False) -> list[dict]:
    query = db.query(PricingAddon)
    if not include_inactive:
        query = query.filter(PricingAddon.is_active.is_(True))
    rows = query.order_by(PricingAddon.sort_order, PricingAddon.id).all()
    return [
        {
            "id": row.id,
            "key": row.key,
            "label": row.label,
            "description": row.description,
            "amount": float(row.amount) if row.amount is not None else None,
            "cadence": row.cadence,
            "is_active": row.is_active,
            "priced": row.amount is not None,
        }
        for row in rows
    ]


def settings_payload(record: PricingSetting) -> dict:
    return {
        "benchmark_percent": float(record.benchmark_percent),
        "annual_discount_percent": float(record.annual_discount_percent),
        "quote_validity_days": record.quote_validity_days,
        "tax_rate_percent": float(record.tax_rate_percent),
        "tax_note": record.tax_note,
        "terms": record.terms,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "updated_by_user_id": record.updated_by_user_id,
    }


def benchmark_for(db: Session, annual_turnover: Decimal | None) -> Decimal | None:
    if annual_turnover is None:
        return None
    settings_row = get_pricing_settings(db)
    return money_round(
        Decimal(annual_turnover) * _dimensionless(settings_row.benchmark_percent) / Decimal("100")
    )


def estimate_payload(db: Session, annual_turnover: Decimal | None) -> dict:
    settings_row = get_pricing_settings(db)
    benchmark = benchmark_for(db, annual_turnover)
    tier = tier_for_turnover(db, annual_turnover)
    return {
        "annual_turnover": float(annual_turnover) if annual_turnover is not None else None,
        "benchmark_percent": float(settings_row.benchmark_percent),
        "indicative_annual_fee": float(benchmark) if benchmark is not None else None,
        "indicative_monthly_equivalent": (
            float(money_round(benchmark / Decimal("12"))) if benchmark is not None else None
        ),
        "software_tier": (
            {
                "key": tier.key,
                "label": tier.label,
                "monthly_price": float(tier.monthly_price),
            }
            if tier is not None
            else None
        ),
        "note": BENCHMARK_NOTE,
    }


def _line_dict(line: object) -> dict:
    if isinstance(line, dict):
        raw = line
    else:
        raw = line.model_dump() if hasattr(line, "model_dump") else dict(line)  # type: ignore[arg-type]
    amount = money_round(Decimal(str(raw.get("amount") or 0)))
    return {
        "kind": raw.get("kind") or "service",
        "key": raw.get("key"),
        "label": (raw.get("label") or "").strip(),
        "description": (raw.get("description") or "").strip() or None,
        "service": raw.get("service"),
        "amount": amount,
        "cadence": raw.get("cadence") or "annual",
    }


def normalise_lines(lines: list[object]) -> list[dict]:
    normalised: list[dict] = []
    for line in lines:
        row = _line_dict(line)
        if row["label"]:
            normalised.append(row)
    return normalised


def compute_totals(
    lines: list[dict],
    discount_type: str,
    discount_value: Decimal | int | float | str,
    payment_frequency: str,
) -> dict:
    subtotal = money_round(sum((Decimal(str(row["amount"])) for row in lines), Decimal("0")))
    value = _dimensionless(discount_value or 0)
    if discount_type == "percent":
        discount = money_round(subtotal * value / Decimal("100"))
    elif discount_type == "amount":
        discount = money_round(min(value, subtotal))
    else:
        discount = Decimal("0.00")
    total = money_round(max(subtotal - discount, Decimal("0")))
    periods = {"monthly": 12, "quarterly": 4, "annual": 1, "one_time": 1}.get(
        payment_frequency, 12
    )
    return {
        "subtotal_annual": subtotal,
        "discount_amount": discount,
        "total_annual": total,
        "monthly_equivalent": money_round(total / Decimal("12")),
        "amount_per_period": money_round(total / Decimal(periods)),
    }


def apply_quotation_pricing(
    quotation,
    *,
    lines: list[dict],
    discount_type: str,
    discount_value,
    payment_frequency: str,
    validity_days: int | None,
    settings_row: PricingSetting | None = None,
) -> None:
    totals = compute_totals(lines, discount_type, discount_value, payment_frequency)
    quotation.line_items = lines
    quotation.scope = [
        {"service": row.get("service") or "bookkeeping", "description": row["label"]}
        for row in lines
        if row.get("kind") == "service" and row.get("service")
    ]
    quotation.discount_type = discount_type
    quotation.discount_value = money_round(_dimensionless(discount_value or 0))
    quotation.discount_amount = totals["discount_amount"]
    quotation.subtotal_annual = totals["subtotal_annual"]
    quotation.total_annual = totals["total_annual"]
    quotation.monthly_equivalent = totals["monthly_equivalent"]
    quotation.amount = totals["amount_per_period"]
    quotation.payment_frequency = payment_frequency
    quotation.billing_cadence = payment_frequency
    if validity_days is not None:
        quotation.validity_days = validity_days
    if settings_row is not None:
        quotation.tax_rate_percent = settings_row.tax_rate_percent
        quotation.tax_note = settings_row.tax_note


def record_price_history(
    db: Session,
    *,
    entity_type: str,
    entity_key: str,
    field: str,
    old_value,
    new_value,
    user: User | None,
    note: str | None = None,
) -> None:
    db.add(
        PriceHistory(
            entity_type=entity_type,
            entity_key=entity_key,
            field=field,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            changed_by_user_id=user.id if user is not None else None,
            changed_at=utcnow(),
            note=note,
        )
    )


def admin_pricing_payload(db: Session) -> dict:
    tiers = db.query(SoftwareTier).order_by(SoftwareTier.sort_order, SoftwareTier.id).all()
    itr_rows = db.query(ITRPrice).order_by(ITRPrice.sort_order, ITRPrice.id).all()
    addons = (
        db.query(PricingAddon).order_by(PricingAddon.sort_order, PricingAddon.id).all()
    )
    return {
        "settings": settings_payload(get_pricing_settings(db)),
        "software_tiers": [
            {
                "id": row.id,
                "key": row.key,
                "label": row.label,
                "turnover_min": float(row.turnover_min),
                "turnover_max": float(row.turnover_max) if row.turnover_max is not None else None,
                "monthly_price": float(row.monthly_price),
                "annual_price": float(
                    money_round(
                        Decimal(row.monthly_price)
                        * 12
                        * (
                            Decimal("1")
                            - _dimensionless(get_pricing_settings(db).annual_discount_percent)
                            / Decimal("100")
                        )
                    )
                ),
                "description": row.description,
                "features": row.features or [],
                "is_active": row.is_active,
                "sort_order": row.sort_order,
            }
            for row in tiers
        ],
        "itr_prices": [
            {
                "id": row.id,
                "key": row.key,
                "label": row.label,
                "description": row.description,
                "price_min": float(row.price_min),
                "price_max": float(row.price_max) if row.price_max is not None else None,
                "price_note": row.price_note,
                "is_active": row.is_active,
                "sort_order": row.sort_order,
            }
            for row in itr_rows
        ],
        "addons": [
            {
                "id": row.id,
                "key": row.key,
                "label": row.label,
                "description": row.description,
                "amount": float(row.amount) if row.amount is not None else None,
                "cadence": row.cadence,
                "is_active": row.is_active,
                "sort_order": row.sort_order,
            }
            for row in addons
        ],
        "history": history_payload(db, limit=100),
        "note": (
            "Changes affect new quotations only. Existing approved or sent quotations keep "
            "the totals stored against them."
        ),
    }


def history_payload(db: Session, *, limit: int = 100) -> list[dict]:
    rows = (
        db.query(PriceHistory)
        .order_by(PriceHistory.changed_at.desc(), PriceHistory.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "entity_type": row.entity_type,
            "entity_key": row.entity_key,
            "field": row.field,
            "old_value": row.old_value,
            "new_value": row.new_value,
            "changed_by_user_id": row.changed_by_user_id,
            "changed_at": row.changed_at.isoformat() if row.changed_at else None,
            "note": row.note,
        }
        for row in rows
    ]
