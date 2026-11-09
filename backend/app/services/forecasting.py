from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import BusinessProfile, Expense, FinancialObligation
from .finance import (
    aging_bucket,
    cash_balance,
    confirmed_paid_by_invoice,
    outstanding_invoices,
    q2,
)

SCENARIOS: dict[str, dict[str, Decimal | int | str]] = {
    "conservative": {
        "label": "Conservative",
        "probability_multiplier": Decimal("0.65"),
        "expense_multiplier": Decimal("1.15"),
        "delay_days": 7,
        "description": "Lower collection odds, higher expenses, and slower payment of overdue invoices.",
    },
    "base": {
        "label": "Base case",
        "probability_multiplier": Decimal("1.00"),
        "expense_multiplier": Decimal("1.00"),
        "delay_days": 0,
        "description": "Historical collection behaviour with current operating spend.",
    },
    "optimistic": {
        "label": "Optimistic",
        "probability_multiplier": Decimal("1.20"),
        "expense_multiplier": Decimal("0.95"),
        "delay_days": -3,
        "description": "Faster collections and slightly lower operating spend. Not a guarantee.",
    },
}

COLLECTION_PROBABILITY = {
    "current": Decimal("0.90"),
    "1-30": Decimal("0.70"),
    "31-60": Decimal("0.50"),
    "61-90": Decimal("0.35"),
    "90+": Decimal("0.25"),
}

BUCKET_DELAY_DAYS = {"1-30": 7, "31-60": 14, "61-90": 21, "90+": 30}


def _expense_basis(db: Session, user_id: int, today: date) -> tuple[Decimal, int]:
    lookback_days = 60
    start = today - timedelta(days=lookback_days - 1)
    total, days_with_data = (
        db.query(
            func.coalesce(func.sum(Expense.amount), 0),
            func.count(func.distinct(Expense.incurred_on)),
        )
        .filter(
            Expense.user_id == user_id,
            Expense.incurred_on >= start,
            Expense.incurred_on <= today,
        )
        .one()
    )
    return q2(q2(total) / Decimal(lookback_days)), int(days_with_data or 0)


def build_forecast(
    db: Session,
    profile: BusinessProfile,
    horizon_days: int = 30,
    scenario: str = "base",
    today: date | None = None,
) -> dict:
    today = today or date.today()
    horizon_days = max(7, min(int(horizon_days), 90))
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    config = SCENARIOS[scenario]
    prob_multiplier = Decimal(str(config["probability_multiplier"]))
    expense_multiplier = Decimal(str(config["expense_multiplier"]))
    delay_days = int(config["delay_days"])

    opening = cash_balance(db, profile, today)
    reserve = q2(profile.min_cash_reserve)
    cutoff = today + timedelta(days=horizon_days)

    paid_map = confirmed_paid_by_invoice(db, profile.user_id)
    receivables = []
    at_risk = Decimal("0.00")
    excluded_beyond_horizon = Decimal("0.00")
    for row in outstanding_invoices(db, profile.user_id, today):
        inv = row["invoice"]
        bucket = aging_bucket(inv.due_date, today)
        base_prob = COLLECTION_PROBABILITY[bucket]
        probability = min(Decimal("0.98"), max(Decimal("0.05"), base_prob * prob_multiplier))
        if row["overdue_days"] > 0:
            expected_date = today + timedelta(
                days=max(1, BUCKET_DELAY_DAYS.get(bucket, 21) + delay_days)
            )
        else:
            expected_date = inv.due_date
        expected_amount = q2(row["outstanding"] * probability)
        at_risk = q2(at_risk + (row["outstanding"] - expected_amount))
        if expected_date > cutoff:
            excluded_beyond_horizon = q2(excluded_beyond_horizon + row["outstanding"])
            continue
        if expected_date < today:
            expected_date = today
        receivables.append(
            {
                "invoice_id": inv.id,
                "invoice_number": inv.number,
                "customer": inv.customer.name,
                "outstanding": row["outstanding"],
                "expected_date": expected_date.isoformat(),
                "probability": float(probability),
                "expected_amount": expected_amount,
                "bucket": bucket,
            }
        )

    daily_expense, expense_days = _expense_basis(db, profile.user_id, today)
    daily_expense = q2(daily_expense * expense_multiplier)

    obligation_rows = (
        db.query(FinancialObligation)
        .filter(
            FinancialObligation.user_id == profile.user_id,
            FinancialObligation.status == "scheduled",
            FinancialObligation.due_date <= cutoff,
        )
        .order_by(FinancialObligation.due_date.asc())
        .all()
    )
    outflows = []
    for obligation in obligation_rows:
        due = obligation.due_date
        if due <= today:
            due = today + timedelta(days=1)
        outflows.append(
            {
                "source": "obligation",
                "id": obligation.id,
                "label": obligation.name,
                "category": obligation.category,
                "date": due.isoformat(),
                "amount": q2(obligation.amount),
            }
        )

    inflow_by_day: dict[date, Decimal] = {}
    for receivable in receivables:
        day = date.fromisoformat(receivable["expected_date"])
        inflow_by_day[day] = q2(inflow_by_day.get(day, Decimal("0.00")) + receivable["expected_amount"])
    outflow_by_day: dict[date, Decimal] = {}
    for outflow in outflows:
        day = date.fromisoformat(outflow["date"])
        outflow_by_day[day] = q2(outflow_by_day.get(day, Decimal("0.00")) + outflow["amount"])
    if daily_expense > 0:
        for offset in range(1, horizon_days + 1):
            day = today + timedelta(days=offset)
            outflow_by_day[day] = q2(outflow_by_day.get(day, Decimal("0.00")) + daily_expense)

    series = [
        {
            "date": today.isoformat(),
            "inflow": Decimal("0.00"),
            "outflow": Decimal("0.00"),
            "balance": opening,
            "is_forecast": False,
            "below_reserve": opening < reserve,
        }
    ]
    balance = opening
    minimum_balance = opening
    minimum_balance_date = today
    shortfall_date: date | None = None
    total_inflow = Decimal("0.00")
    total_outflow = Decimal("0.00")
    for offset in range(1, horizon_days + 1):
        day = today + timedelta(days=offset)
        inflow = inflow_by_day.get(day, Decimal("0.00"))
        outflow = outflow_by_day.get(day, Decimal("0.00"))
        balance = q2(balance + inflow - outflow)
        total_inflow = q2(total_inflow + inflow)
        total_outflow = q2(total_outflow + outflow)
        if balance < minimum_balance:
            minimum_balance = balance
            minimum_balance_date = day
        if balance < reserve and shortfall_date is None:
            shortfall_date = day
        series.append(
            {
                "date": day.isoformat(),
                "inflow": inflow,
                "outflow": outflow,
                "balance": balance,
                "is_forecast": True,
                "below_reserve": balance < reserve,
            }
        )

    investable_surplus = q2(max(Decimal("0.00"), minimum_balance - reserve))
    data_quality = "high" if expense_days >= 30 else "medium" if expense_days >= 7 else "low"
    assumptions = {
        "method": "Rules-based deterministic forecast using invoice aging probabilities, scheduled obligations and a 60-day average daily expense.",
        "collection_probabilities": {
            key: float(value) for key, value in COLLECTION_PROBABILITY.items()
        },
        "probability_multiplier": float(prob_multiplier),
        "overdue_delay_days_adjustment": delay_days,
        "daily_expense_basis": daily_expense,
        "expense_multiplier": float(expense_multiplier),
        "expense_history_days": expense_days,
        "minimum_reserve": reserve,
        "data_quality": data_quality,
        "receivables_not_guaranteed": True,
        "note": "Expected receivables are probability-weighted, never treated as guaranteed cash. Investable surplus is only the headroom above your reserve at the lowest projected point.",
    }
    return {
        "scenario": scenario,
        "scenario_label": config["label"],
        "scenario_description": config["description"],
        "horizon_days": horizon_days,
        "as_of": today.isoformat(),
        "opening_balance": opening,
        "closing_balance": balance,
        "minimum_balance": minimum_balance,
        "minimum_balance_date": minimum_balance_date.isoformat(),
        "minimum_reserve": reserve,
        "shortfall_date": shortfall_date.isoformat() if shortfall_date else None,
        "investable_surplus": investable_surplus,
        "total_expected_inflow": total_inflow,
        "total_expected_outflow": total_outflow,
        "at_risk_receivables": at_risk,
        "receivables_beyond_horizon": excluded_beyond_horizon,
        "series": series,
        "receivables": sorted(receivables, key=lambda r: r["expected_date"]),
        "outflows": sorted(outflows, key=lambda o: o["date"]),
        "assumptions": assumptions,
    }


def sensitivity_analysis(
    db: Session, profile: BusinessProfile, horizon_days: int = 30, today: date | None = None
) -> list[dict]:
    today = today or date.today()
    variants = [
        ("base", "Base case", None),
        ("conservative", "Slower collections / higher spend", None),
        ("optimistic", "Faster collections / lower spend", None),
    ]
    results = []
    for key, label, _ in variants:
        forecast = build_forecast(db, profile, horizon_days, key, today)
        results.append(
            {
                "key": key,
                "label": label,
                "closing_balance": forecast["closing_balance"],
                "minimum_balance": forecast["minimum_balance"],
                "shortfall_date": forecast["shortfall_date"],
                "investable_surplus": forecast["investable_surplus"],
            }
        )
    return results
