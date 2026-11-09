"""Deterministic Indian income-tax estimator.

Every slab, surcharge band, rebate limit, deduction cap and capital-gain rate is read from the
``tax_rule_sets`` tables. Nothing here calls an AI model: the numbers come from the stored rule
version and plain arithmetic, and the result carries that version back to the caller.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.orm import Session, selectinload

from ..models import (
    TaxCapitalGainsRule,
    TaxConstant,
    TaxDeductionCap,
    TaxRebateRule,
    TaxRuleSet,
    TaxSlab,
    TaxSurchargeBand,
)

ZERO = Decimal("0.00")
HUNDRED = Decimal("100")
FY_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")

REGIME_LABELS = {"new": "New regime", "old": "Old regime"}

# Chapter VI-A sections accepted by the estimator. Employer NPS (80CCD(2)) is computed from the
# salary block instead of being claimed by hand because its cap is a percentage of basic salary.
DEDUCTION_SECTIONS = ("80C", "80CCD1B", "80D", "80TTA", "80TTB", "24B", "80G", "80E", "other")

DISCLAIMER = (
    "Estimate only. Slabs, rebate, surcharge and deduction caps come from the stored rule "
    "version shown here and are applied with rounded arithmetic. FINOVEXA never decides a tax "
    "amount with AI and does not file returns. Confirm every figure with a chartered accountant "
    "before filing."
)


class TaxValidationError(ValueError):
    """Raised when an income-tax input cannot be calculated safely."""


# ------------------------------------------------------------------ helpers


def _d(value: object, label: str = "value") -> Decimal:
    if value is None or value == "":
        return ZERO
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TaxValidationError(f"{label} must be a number.") from exc
    if not dec.is_finite():
        raise TaxValidationError(f"{label} must be a finite number.")
    return dec


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_to(value: Decimal, multiple: Decimal) -> Decimal:
    if multiple <= 0:
        return _money(value)
    return (Decimal(value) / multiple).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * multiple


def financial_year_bounds(financial_year: str) -> tuple[date, date]:
    match = FY_PATTERN.match((financial_year or "").strip())
    if not match:
        raise TaxValidationError("Financial year must look like 2026-27.")
    start_year = int(match.group(1))
    end_year = int(match.group(2))
    if end_year != (start_year + 1) % 100:
        raise TaxValidationError("Financial year must span consecutive years, for example 2026-27.")
    if start_year < 2018 or start_year > 2100:
        raise TaxValidationError("Financial year is outside the supported range.")
    last_day = calendar.monthrange(start_year + 1, 3)[1]
    return date(start_year, 4, 1), date(start_year + 1, 3, last_day)


def assessment_year(financial_year: str) -> str:
    start, _ = financial_year_bounds(financial_year)
    return f"{start.year + 1}-{str(start.year + 2)[2:]}"


def _constant(rule_set: TaxRuleSet, code: str, default: str = "0") -> Decimal:
    for row in rule_set.constants:
        if row.code == code:
            return Decimal(row.value)
    return Decimal(default)


def _deduction_cap(rule_set: TaxRuleSet, code: str) -> TaxDeductionCap | None:
    for row in rule_set.deduction_caps:
        if row.code == code:
            return row
    return None


def _capital_gains_rule(rule_set: TaxRuleSet, category: str) -> TaxCapitalGainsRule | None:
    for row in rule_set.capital_gains_rules:
        if row.category == category:
            return row
    return None


def load_rule_sets(db: Session, financial_year: str) -> list[TaxRuleSet]:
    financial_year_bounds(financial_year)
    return (
        db.query(TaxRuleSet)
        .options(
            selectinload(TaxRuleSet.slabs),
            selectinload(TaxRuleSet.surcharge_bands),
            selectinload(TaxRuleSet.rebate),
            selectinload(TaxRuleSet.constants),
            selectinload(TaxRuleSet.deduction_caps),
            selectinload(TaxRuleSet.capital_gains_rules),
        )
        .filter(TaxRuleSet.financial_year == financial_year, TaxRuleSet.is_active.is_(True))
        .order_by(TaxRuleSet.regime.desc())
        .all()
    )


def financial_years(db: Session) -> list[str]:
    rows = (
        db.query(TaxRuleSet.financial_year)
        .filter(TaxRuleSet.is_active.is_(True))
        .distinct()
        .order_by(TaxRuleSet.financial_year.desc())
        .all()
    )
    return [row[0] for row in rows]


def _slab_tax(income: Decimal, slabs: list[TaxSlab]) -> tuple[Decimal, list[dict]]:
    remaining = Decimal(income)
    total = ZERO
    rows: list[dict] = []
    for slab in sorted(slabs, key=lambda row: row.lower_bound):
        lower = Decimal(slab.lower_bound)
        upper = Decimal(slab.upper_bound) if slab.upper_bound is not None else None
        if remaining <= 0:
            break
        if income <= lower:
            break
        taxable = min(remaining, (upper - lower) if upper is not None else remaining)
        taxable = max(taxable, ZERO)
        if taxable > 0:
            tax = _money(taxable * Decimal(slab.rate) / HUNDRED)
            total += tax
            rows.append(
                {
                    "from": _money(lower),
                    "to": _money(upper) if upper is not None else None,
                    "rate": _money(Decimal(slab.rate)),
                    "taxable": _money(taxable),
                    "tax": tax,
                }
            )
        remaining -= taxable if upper is not None else remaining
    return _money(total), rows


def _surcharge_rate(income: Decimal, bands: list[TaxSurchargeBand]) -> tuple[Decimal, Decimal]:
    """Return the applicable rate and the income threshold that starts that band."""
    applicable = Decimal("0")
    threshold = ZERO
    for band in sorted(bands, key=lambda row: row.income_above):
        if income > Decimal(band.income_above):
            applicable = Decimal(band.rate)
            threshold = Decimal(band.income_above)
    return applicable, threshold


# ------------------------------------------------------------------ calculation


def compute_income_tax(
    db: Session,
    *,
    financial_year: str,
    regime: str,
    inputs: dict,
) -> dict:
    if regime not in ("new", "old"):
        raise TaxValidationError("Regime must be new or old.")
    rule_sets = load_rule_sets(db, financial_year)
    rule_set = next((row for row in rule_sets if row.regime == regime), None)
    if rule_set is None:
        raise TaxValidationError(
            f"No {regime} regime rule set is stored for FY {financial_year}. "
            "Add the published slabs before estimating."
        )
    if not rule_set.slabs:
        raise TaxValidationError("The stored rule set has no slabs. No estimate can be produced.")

    salary_in = inputs.get("salary") or {}
    business_in = inputs.get("business") or {}
    cg_in = inputs.get("capital_gains") or {}
    deduction_in = inputs.get("deductions") or {}

    gross_salary = max(_d(salary_in.get("gross_salary"), "Gross salary"), ZERO)
    basic_salary = min(max(_d(salary_in.get("basic_salary"), "Basic salary"), ZERO), gross_salary)
    hra_received = max(_d(salary_in.get("hra_received"), "HRA received"), ZERO)
    rent_paid = max(_d(salary_in.get("rent_paid"), "Rent paid"), ZERO)
    professional_tax_input = max(_d(salary_in.get("professional_tax"), "Professional tax"), ZERO)
    employer_nps = max(_d(salary_in.get("employer_nps"), "Employer NPS contribution"), ZERO)
    metro = bool(salary_in.get("metro_city"))

    notes: list[str] = []

    standard_deduction = min(gross_salary, _constant(rule_set, "standard_deduction"))
    professional_cap = _constant(rule_set, "professional_tax_cap")
    professional_tax = min(professional_tax_input, professional_cap)

    hra_exemption = ZERO
    metro_pct = _constant(rule_set, "hra_metro_percent")
    non_metro_pct = _constant(rule_set, "hra_non_metro_percent")
    pct = metro_pct if metro else non_metro_pct
    if pct > 0 and basic_salary > 0 and hra_received > 0 and rent_paid > 0:
        hra_exemption = min(
            hra_received,
            max(rent_paid - basic_salary * Decimal("0.10"), ZERO),
            basic_salary * pct / HUNDRED,
        )
        hra_exemption = min(_money(hra_exemption), gross_salary)
    elif hra_received > 0 and pct == 0:
        notes.append("House rent allowance exemption is not available under the selected regime.")

    net_salary = max(gross_salary - hra_exemption - standard_deduction - professional_tax, ZERO)

    presumptive = (business_in.get("presumptive") or "none").lower()
    if presumptive not in ("none", "44ad", "44ada"):
        raise TaxValidationError("Presumptive taxation must be none, 44AD or 44ADA.")
    gross_receipts = max(_d(business_in.get("gross_receipts"), "Gross receipts"), ZERO)
    digital_pct = min(max(_d(business_in.get("digital_receipts_pct"), "Digital receipt share"), ZERO), HUNDRED)
    if presumptive == "44ad":
        if gross_receipts <= 0:
            raise TaxValidationError("44AD needs gross receipts greater than zero.")
        rate = (
            digital_pct * _constant(rule_set, "presumptive_44ad_digital_percent", "6")
            + (HUNDRED - digital_pct) * _constant(rule_set, "presumptive_44ad_percent", "8")
        ) / HUNDRED
        business_income = _money(gross_receipts * rate / HUNDRED)
        business_basis = "44AD presumptive"
    elif presumptive == "44ada":
        if gross_receipts <= 0:
            raise TaxValidationError("44ADA needs gross receipts greater than zero.")
        business_income = _money(
            gross_receipts * _constant(rule_set, "presumptive_44ada_percent", "50") / HUNDRED
        )
        business_basis = "44ADA presumptive"
    else:
        business_income = max(_d(business_in.get("net_profit"), "Business net profit"), ZERO)
        business_income = _money(business_income)
        business_basis = "Net profit from books"

    other_income = max(_d(inputs.get("other_income"), "Other income"), ZERO)

    equity_stcg = max(_d(cg_in.get("equity_stcg"), "Equity STCG"), ZERO)
    equity_ltcg = max(_d(cg_in.get("equity_ltcg"), "Equity LTCG"), ZERO)
    other_ltcg = max(_d(cg_in.get("other_ltcg"), "Other LTCG"), ZERO)
    other_stcg = max(_d(cg_in.get("other_stcg"), "Other STCG"), ZERO)

    gross_total_income = _money(
        net_salary + business_income + other_income + equity_stcg + equity_ltcg + other_ltcg + other_stcg
    )

    deduction_rows: list[dict] = []

    def apply_section(code: str, claimed: Decimal, label_fallback: str) -> Decimal:
        cap_row = _deduction_cap(rule_set, code)
        if cap_row is None:
            deduction_rows.append(
                {
                    "section": code,
                    "label": label_fallback,
                    "claimed": _money(claimed),
                    "allowed": ZERO,
                    "cap": None,
                    "reason": "No deduction cap is configured for this section.",
                }
            )
            return ZERO
        if not cap_row.allowed:
            deduction_rows.append(
                {
                    "section": code,
                    "label": cap_row.label,
                    "claimed": _money(claimed),
                    "allowed": ZERO,
                    "cap": None,
                    "reason": f"Not available under the {REGIME_LABELS[regime].lower()}.",
                }
            )
            return ZERO
        cap = Decimal(cap_row.cap_amount) if cap_row.cap_amount is not None else None
        allowed = claimed if cap is None else min(claimed, cap)
        deduction_rows.append(
            {
                "section": code,
                "label": cap_row.label,
                "claimed": _money(claimed),
                "allowed": _money(allowed),
                "cap": _money(cap) if cap is not None else None,
                "reason": cap_row.note,
            }
        )
        return _money(allowed)

    total_deductions = ZERO
    for code in DEDUCTION_SECTIONS:
        claimed = max(_d(deduction_in.get(code), f"Deduction {code}"), ZERO)
        if claimed <= 0:
            continue
        total_deductions += apply_section(code, claimed, f"Section {code}")

    nps_cap_row = _deduction_cap(rule_set, "80CCD2")
    employer_nps_allowed = ZERO
    if nps_cap_row is not None and nps_cap_row.allowed and employer_nps > 0:
        percent = (
            Decimal(nps_cap_row.percent_of_basic)
            if nps_cap_row.percent_of_basic is not None
            else ZERO
        )
        cap = basic_salary * percent / HUNDRED
        if nps_cap_row.cap_amount is not None:
            cap = min(cap, Decimal(nps_cap_row.cap_amount))
        employer_nps_allowed = _money(min(employer_nps, cap))
        deduction_rows.append(
            {
                "section": "80CCD2",
                "label": nps_cap_row.label,
                "claimed": _money(employer_nps),
                "allowed": employer_nps_allowed,
                "cap": _money(cap),
                "reason": nps_cap_row.note,
            }
        )
    elif employer_nps > 0:
        deduction_rows.append(
            {
                "section": "80CCD2",
                "label": "Employer NPS contribution",
                "claimed": _money(employer_nps),
                "allowed": ZERO,
                "cap": None,
                "reason": f"Not available under the {REGIME_LABELS[regime].lower()}.",
            }
        )

    total_deductions = _money(min(total_deductions + employer_nps_allowed, gross_total_income))
    total_income_raw = max(gross_total_income - total_deductions, ZERO)
    total_income = _round_to(total_income_raw, _constant(rule_set, "rounding_multiple", "10"))
    if total_income != total_income_raw:
        notes.append("Total income rounded to the nearest 10 for display (section 288A style rounding).")

    capital_gain_rows: list[dict] = []
    special_income = ZERO
    cg_tax = ZERO
    cg_specs = (
        ("equity_stcg_111a", equity_stcg),
        ("equity_ltcg_112a", equity_ltcg),
        ("other_ltcg", other_ltcg),
    )
    for category, amount in cg_specs:
        rule = _capital_gains_rule(rule_set, category)
        if amount <= 0:
            continue
        if rule is None:
            notes.append(f"No stored rate for {category}; the amount is taxed at slab rates.")
            continue
        exemption = Decimal(rule.exemption_limit or ZERO)
        taxable = max(amount - exemption, ZERO)
        tax = _money(taxable * Decimal(rule.rate) / HUNDRED)
        special_income += amount
        cg_tax += tax
        capital_gain_rows.append(
            {
                "category": category,
                "label": rule.label,
                "amount": _money(amount),
                "exemption": _money(exemption),
                "taxable": _money(taxable),
                "rate": _money(Decimal(rule.rate)),
                "tax": tax,
            }
        )

    slab_income = max(total_income - special_income, ZERO)
    slab_tax, slab_rows = _slab_tax(slab_income, rule_set.slabs)

    rebate = ZERO
    marginal_relief = ZERO
    rebate_rule = rule_set.rebate
    # 87A is tested and applied on slab-rate income; gains taxed under 111A/112A stay outside it.
    rebate_test_income = slab_income
    if rebate_rule is not None and rebate_test_income <= Decimal(rebate_rule.income_limit):
        rebate = min(slab_tax, Decimal(rebate_rule.max_rebate))
    if (
        rebate_rule is not None
        and rebate_rule.marginal_relief
        and rebate == ZERO
        and rebate_test_income > Decimal(rebate_rule.income_limit)
    ):
        excess = rebate_test_income - Decimal(rebate_rule.income_limit)
        if slab_tax > excess:
            marginal_relief = _money(slab_tax - excess)
            notes.append("Section 87A marginal relief limits tax to the income above the rebate limit.")

    slab_after_rebate = _money(slab_tax - rebate - marginal_relief)
    tax_before_surcharge = _money(slab_after_rebate + cg_tax)

    surcharge_rate, surcharge_threshold = _surcharge_rate(total_income, rule_set.surcharge_bands)
    cg_cap = _constant(rule_set, "capital_gains_surcharge_cap_percent", "15")
    surcharge = _money(
        slab_after_rebate * surcharge_rate / HUNDRED
        + cg_tax * min(surcharge_rate, cg_cap) / HUNDRED
    )
    surcharge_relief = ZERO
    if surcharge_rate > 0 and cg_tax == ZERO:
        tax_at_threshold, _ = _slab_tax(surcharge_threshold, rule_set.slabs)
        prior_rate, _ = _surcharge_rate(surcharge_threshold - Decimal("0.01"), rule_set.surcharge_bands)
        threshold_total = _money(
            tax_at_threshold + tax_at_threshold * prior_rate / HUNDRED + (total_income - surcharge_threshold)
        )
        if tax_before_surcharge + surcharge > threshold_total:
            surcharge_relief = _money(tax_before_surcharge + surcharge - threshold_total)
            surcharge = _money(surcharge - surcharge_relief)
            notes.append("Surcharge marginal relief applied at the band threshold.")

    cess_rate = _constant(rule_set, "cess_percent", "4")
    cess = _money((tax_before_surcharge + surcharge) * cess_rate / HUNDRED)
    liability_raw = _money(tax_before_surcharge + surcharge + cess)
    total_liability = _round_to(liability_raw, _constant(rule_set, "rounding_multiple", "10"))
    rounding = _money(total_liability - liability_raw)

    effective_rate = (
        (total_liability / total_income * HUNDRED).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total_income > 0
        else ZERO
    )

    return {
        "financial_year": financial_year,
        "assessment_year": rule_set.assessment_year,
        "regime": regime,
        "regime_label": REGIME_LABELS[regime],
        "rule_set_id": rule_set.id,
        "rule_version": rule_set.version,
        "rule_source_note": rule_set.source_note,
        "currency": "INR",
        "status": "estimate",
        "income": {
            "salary": {
                "gross_salary": _money(gross_salary),
                "basic_salary": _money(basic_salary),
                "hra_received": _money(hra_received),
                "hra_exemption": _money(hra_exemption),
                "standard_deduction": _money(standard_deduction),
                "professional_tax": _money(professional_tax),
                "net_salary": _money(net_salary),
            },
            "business": {
                "basis": business_basis,
                "net_profit": _money(_d(business_in.get("net_profit"), "Business net profit")),
                "gross_receipts": _money(gross_receipts),
                "income": _money(business_income),
            },
            "other_income": _money(other_income),
            "capital_gains": {
                "equity_stcg": _money(equity_stcg),
                "equity_ltcg": _money(equity_ltcg),
                "other_ltcg": _money(other_ltcg),
                "other_stcg": _money(other_stcg),
            },
            "gross_total_income": gross_total_income,
        },
        "deductions": {"items": deduction_rows, "total": total_deductions},
        "total_income": _money(total_income),
        "tax": {
            "slab_income": _money(slab_income),
            "slabs": slab_rows,
            "slab_tax": _money(slab_tax),
            "rebate_87a": _money(rebate),
            "rebate_marginal_relief": _money(marginal_relief),
            "capital_gains": capital_gain_rows,
            "capital_gains_tax": _money(cg_tax),
            "tax_before_surcharge": tax_before_surcharge,
            "surcharge_rate": _money(surcharge_rate),
            "surcharge": _money(surcharge),
            "surcharge_marginal_relief": _money(surcharge_relief),
            "cess_rate": _money(cess_rate),
            "cess": _money(cess),
            "total_liability": _money(total_liability),
            "rounding_adjustment": rounding,
        },
        "effective_rate_pct": effective_rate,
        "monthly_estimate": _money(total_liability / Decimal("12")),
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }


def compute_comparison(db: Session, *, financial_year: str, inputs: dict) -> dict:
    results = {}
    for regime in ("new", "old"):
        try:
            results[regime] = compute_income_tax(
                db, financial_year=financial_year, regime=regime, inputs=inputs
            )
        except TaxValidationError:
            continue
    if not results:
        raise TaxValidationError(
            f"No stored rule sets are available for FY {financial_year}. "
            "Seed or add the published rules before estimating."
        )
    recommended = min(
        results.items(),
        key=lambda item: (Decimal(str(item[1]["tax"]["total_liability"])), 0 if item[0] == "new" else 1),
    )[0]
    liability_values = {
        regime: Decimal(str(result["tax"]["total_liability"])) for regime, result in results.items()
    }
    ordered = sorted(liability_values.values())
    savings = ordered[-1] - ordered[0] if len(ordered) > 1 else ZERO
    return {
        "financial_year": financial_year,
        "assessment_year": assessment_year(financial_year),
        "regimes": results,
        "recommended_regime": recommended,
        "savings": _money(savings),
        "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------------ rule payload


def _rule_set_payload(rule_set: TaxRuleSet) -> dict:
    return {
        "id": rule_set.id,
        "financial_year": rule_set.financial_year,
        "assessment_year": rule_set.assessment_year,
        "regime": rule_set.regime,
        "regime_label": REGIME_LABELS.get(rule_set.regime, rule_set.regime),
        "version": rule_set.version,
        "status": rule_set.status,
        "effective_from": rule_set.effective_from.isoformat(),
        "effective_to": rule_set.effective_to.isoformat() if rule_set.effective_to else None,
        "source_note": rule_set.source_note,
        "slabs": [
            {
                "from": _money(Decimal(slab.lower_bound)),
                "to": _money(Decimal(slab.upper_bound)) if slab.upper_bound is not None else None,
                "rate": _money(Decimal(slab.rate)),
            }
            for slab in sorted(rule_set.slabs, key=lambda row: row.lower_bound)
        ],
        "surcharge_bands": [
            {"income_above": _money(Decimal(band.income_above)), "rate": _money(Decimal(band.rate))}
            for band in sorted(rule_set.surcharge_bands, key=lambda row: row.income_above)
        ],
        "rebate": (
            {
                "income_limit": _money(Decimal(rule_set.rebate.income_limit)),
                "max_rebate": _money(Decimal(rule_set.rebate.max_rebate)),
                "marginal_relief": rule_set.rebate.marginal_relief,
                "note": rule_set.rebate.note,
            }
            if rule_set.rebate
            else None
        ),
        "constants": [
            {"code": row.code, "value": _money(Decimal(row.value)), "description": row.description}
            for row in sorted(rule_set.constants, key=lambda row: row.code)
        ],
        "deductions": [
            {
                "code": row.code,
                "label": row.label,
                "cap_amount": _money(Decimal(row.cap_amount)) if row.cap_amount is not None else None,
                "percent_of_basic": (
                    _money(Decimal(row.percent_of_basic))
                    if row.percent_of_basic is not None
                    else None
                ),
                "allowed": row.allowed,
                "note": row.note,
            }
            for row in sorted(rule_set.deduction_caps, key=lambda row: row.code)
        ],
        "capital_gains": [
            {
                "category": row.category,
                "label": row.label,
                "rate": _money(Decimal(row.rate)),
                "exemption_limit": _money(Decimal(row.exemption_limit)),
                "note": row.note,
            }
            for row in sorted(rule_set.capital_gains_rules, key=lambda row: row.category)
        ],
    }


def rules_payload(db: Session, financial_year: str | None) -> dict:
    years = financial_years(db)
    if not years:
        raise TaxValidationError("No income-tax rule sets are stored.")
    selected = financial_year or years[0]
    financial_year_bounds(selected)
    rule_sets = load_rule_sets(db, selected)
    if not rule_sets:
        raise TaxValidationError(f"No rule sets are stored for FY {selected}.")
    return {
        "financial_years": years,
        "financial_year": selected,
        "assessment_year": rule_sets[0].assessment_year,
        "rule_sets": [_rule_set_payload(row) for row in rule_sets],
        "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------------ seeding

# Published rules held as data. Amounts are in rupees; rates are percentages.
_NEW_2526 = {
    "version": "FA2025",
    "slabs": [
        (0, 400000, 0),
        (400000, 800000, 5),
        (800000, 1200000, 10),
        (1200000, 1600000, 15),
        (1600000, 2000000, 20),
        (2000000, 2400000, 25),
        (2400000, None, 30),
    ],
    "surcharge": [(5000000, 10), (10000000, 15), (20000000, 25)],
    "rebate": (1200000, 60000, True, "Section 87A rebate up to the rebate limit, with marginal relief above it."),
    "constants": {
        "standard_deduction": (75000, "Standard deduction from salary"),
        "professional_tax_cap": (0, "Professional tax is not deductible in this regime"),
        "hra_metro_percent": (0, "HRA exemption is not available in this regime"),
        "hra_non_metro_percent": (0, "HRA exemption is not available in this regime"),
        "presumptive_44ad_percent": (8, "44AD presumptive rate on cash receipts"),
        "presumptive_44ad_digital_percent": (6, "44AD presumptive rate on digital receipts"),
        "presumptive_44ada_percent": (50, "44ADA presumptive rate for professionals"),
        "cess_percent": (4, "Health and education cess"),
        "rounding_multiple": (10, "Tax payable rounded to the nearest 10"),
        "capital_gains_surcharge_cap_percent": (15, "Surcharge ceiling on equity capital gains"),
    },
    "deductions": [
        ("80CCD2", "Employer NPS contribution (80CCD(2))", None, 14, True, "Allowed up to 14% of basic salary."),
        ("80C", "Section 80C investments", 150000, None, False, "Not available in the new regime."),
        ("80CCD1B", "Additional NPS (80CCD(1B))", 50000, None, False, "Not available in the new regime."),
        ("80D", "Health insurance premium (80D)", 100000, None, False, "Not available in the new regime."),
        ("80TTA", "Savings interest (80TTA)", 10000, None, False, "Not available in the new regime."),
        ("80TTB", "Interest for senior citizens (80TTB)", 50000, None, False, "Not available in the new regime."),
        ("24B", "Home loan interest (24(b))", 200000, None, False, "Not available in the new regime."),
        ("80G", "Donations (80G)", None, None, False, "Not available in the new regime."),
        ("80E", "Education loan interest (80E)", None, None, False, "Not available in the new regime."),
        ("other", "Other eligible deductions", None, None, False, "Not available in the new regime."),
    ],
}

_OLD_2526 = {
    "version": "FA2025",
    "slabs": [(0, 250000, 0), (250000, 500000, 5), (500000, 1000000, 20), (1000000, None, 30)],
    "surcharge": [(5000000, 10), (10000000, 15), (20000000, 25), (50000000, 37)],
    "rebate": (500000, 12500, False, "Section 87A rebate for total income up to the rebate limit."),
    "constants": {
        "standard_deduction": (50000, "Standard deduction from salary"),
        "professional_tax_cap": (2500, "Professional tax ceiling"),
        "hra_metro_percent": (50, "HRA exemption share of basic salary in metro cities"),
        "hra_non_metro_percent": (40, "HRA exemption share of basic salary elsewhere"),
        "presumptive_44ad_percent": (8, "44AD presumptive rate on cash receipts"),
        "presumptive_44ad_digital_percent": (6, "44AD presumptive rate on digital receipts"),
        "presumptive_44ada_percent": (50, "44ADA presumptive rate for professionals"),
        "cess_percent": (4, "Health and education cess"),
        "rounding_multiple": (10, "Tax payable rounded to the nearest 10"),
        "capital_gains_surcharge_cap_percent": (15, "Surcharge ceiling on equity capital gains"),
    },
    "deductions": [
        ("80C", "Section 80C investments", 150000, None, True, "Overall 80C/80CCC/80CCD(1) ceiling."),
        ("80CCD1B", "Additional NPS (80CCD(1B))", 50000, None, True, "Over and above the 80C ceiling."),
        ("80D", "Health insurance premium (80D)", 100000, None, True, "Self, family and parents combined."),
        ("80TTA", "Savings interest (80TTA)", 10000, None, True, "Non-senior individuals."),
        ("80TTB", "Interest for senior citizens (80TTB)", 50000, None, True, "Senior citizens only."),
        ("24B", "Home loan interest (24(b))", 200000, None, True, "Self-occupied property."),
        ("80G", "Donations (80G)", None, None, True, "Claim only the eligible amount after the 80G limits."),
        ("80E", "Education loan interest (80E)", None, None, True, "No monetary ceiling."),
        ("80CCD2", "Employer NPS contribution (80CCD(2))", None, 10, True, "Allowed up to 10% of basic salary."),
        ("other", "Other eligible deductions", None, None, True, "Enter only amounts you can support."),
    ],
}

_NEW_2425 = {
    **_NEW_2526,
    "version": "FA2024",
    "slabs": [
        (0, 300000, 0),
        (300000, 700000, 5),
        (700000, 1000000, 10),
        (1000000, 1200000, 15),
        (1200000, 1500000, 20),
        (1500000, None, 30),
    ],
    "rebate": (700000, 25000, True, "Section 87A rebate up to the rebate limit."),
}

_CAPITAL_GAINS = [
    ("equity_stcg_111a", "Listed equity STCG (section 111A)", 20, 0, "Rate in force from 23 July 2024."),
    ("equity_ltcg_112a", "Listed equity LTCG (section 112A)", 12.5, 125000, "Annual exemption before tax."),
    ("other_ltcg", "Other long-term capital gains", 12.5, 0, "Verify indexation eligibility for the asset."),
]

_FY_SPECS: dict[str, dict[str, dict]] = {
    "2024-25": {"new": _NEW_2425, "old": _OLD_2526},
    "2025-26": {"new": _NEW_2526, "old": _OLD_2526},
    "2026-27": {"new": _NEW_2526, "old": _OLD_2526},
}

_SOURCE_NOTE = (
    "Published Finance Act slabs stored as configuration for the stated financial year. "
    "Rates and caps must be reviewed against the current Act before filing."
)


def seed_tax_rules(db: Session) -> None:
    """Idempotently store every published rule set the estimator can use."""
    created = False
    for financial_year, regimes in _FY_SPECS.items():
        start, end = financial_year_bounds(financial_year)
        for regime, spec in regimes.items():
            existing = (
                db.query(TaxRuleSet)
                .filter(
                    TaxRuleSet.financial_year == financial_year,
                    TaxRuleSet.regime == regime,
                    TaxRuleSet.version == spec["version"],
                )
                .one_or_none()
            )
            if existing is not None:
                continue
            db.query(TaxRuleSet).filter(
                TaxRuleSet.financial_year == financial_year,
                TaxRuleSet.regime == regime,
                TaxRuleSet.is_active.is_(True),
            ).update({"is_active": False, "status": "superseded"}, synchronize_session=False)
            rule_set = TaxRuleSet(
                financial_year=financial_year,
                assessment_year=assessment_year(financial_year),
                regime=regime,
                version=spec["version"],
                effective_from=start,
                effective_to=end,
                status="published",
                source_note=_SOURCE_NOTE,
                is_active=True,
            )
            db.add(rule_set)
            db.flush()
            for index, (lower, upper, rate) in enumerate(spec["slabs"]):
                db.add(
                    TaxSlab(
                        rule_set_id=rule_set.id,
                        sequence=index,
                        lower_bound=Decimal(lower),
                        upper_bound=Decimal(upper) if upper is not None else None,
                        rate=Decimal(rate),
                    )
                )
            for index, (threshold, rate) in enumerate(spec["surcharge"]):
                db.add(
                    TaxSurchargeBand(
                        rule_set_id=rule_set.id,
                        sequence=index,
                        income_above=Decimal(threshold),
                        rate=Decimal(rate),
                    )
                )
            limit, max_rebate, marginal, note = spec["rebate"]
            db.add(
                TaxRebateRule(
                    rule_set_id=rule_set.id,
                    income_limit=Decimal(limit),
                    max_rebate=Decimal(max_rebate),
                    marginal_relief=marginal,
                    note=note,
                )
            )
            for code, (value, description) in spec["constants"].items():
                db.add(
                    TaxConstant(
                        rule_set_id=rule_set.id,
                        code=code,
                        value=Decimal(str(value)),
                        description=description,
                    )
                )
            for code, label, cap, percent, allowed, note in spec["deductions"]:
                db.add(
                    TaxDeductionCap(
                        rule_set_id=rule_set.id,
                        code=code,
                        label=label,
                        cap_amount=Decimal(cap) if cap is not None else None,
                        percent_of_basic=Decimal(str(percent)) if percent is not None else None,
                        allowed=allowed,
                        note=note,
                    )
                )
            for category, label, rate, exemption, note in _CAPITAL_GAINS:
                db.add(
                    TaxCapitalGainsRule(
                        rule_set_id=rule_set.id,
                        category=category,
                        label=label,
                        rate=Decimal(str(rate)),
                        exemption_limit=Decimal(exemption),
                        note=note,
                    )
                )
            created = True
    if created:
        db.commit()
