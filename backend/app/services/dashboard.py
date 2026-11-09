from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    AIInsight,
    BusinessProfile,
    EmployeeEntry,
    Expense,
    Invoice,
    Payment,
    Product,
    User,
)
from .finance import (
    cash_balance,
    cash_trend,
    confirmed_paid_by_invoice,
    expense_breakdown,
    invoice_aging_summary,
    invoice_to_dict,
    obligations_upcoming,
    outstanding_invoices,
    payment_to_dict,
    money_text,
    pct_change,
    period_bounds,
    period_metrics,
    priority_alerts,
    product_performance,
    q2,
    revenue_expense_series,
)
from .employee_entries import entry_to_dict, entry_totals
from .forecasting import build_forecast
from .integrations.paypal import paypal_client
from .paypal import paypal_payments, paypal_statistics


def _change_block(current: Decimal, previous: Decimal) -> dict:
    return {"value": current, "previous": previous, "change_pct": pct_change(current, previous)}


def insight_to_dict(insight: AIInsight) -> dict:
    return {
        "id": insight.id,
        "agent": insight.agent,
        "title": insight.title,
        "finding": insight.finding,
        "evidence": insight.evidence,
        "period_start": insight.period_start.isoformat() if insight.period_start else None,
        "period_end": insight.period_end.isoformat() if insight.period_end else None,
        "impact_amount": q2(insight.impact_amount) if insight.impact_amount is not None else None,
        "confidence": insight.confidence,
        "limitations": insight.limitations,
        "recommended_action": insight.recommended_action,
        "mode": getattr(insight, "mode", "deterministic"),
        "created_at": insight.created_at,
    }


def build_ai_summary(
    profile: BusinessProfile,
    metrics: dict,
    prev_metrics: dict,
    receivables: dict,
    cash: Decimal,
    projected: Decimal,
    top_alert: str | None,
    days: int,
) -> dict:
    reserve = q2(profile.min_cash_reserve)
    reserve_state = "above" if cash >= reserve else "below"
    revenue_delta = pct_change(metrics["revenue"], prev_metrics["revenue"])
    trend = (
        "up" if revenue_delta and revenue_delta > 0 else "down" if revenue_delta and revenue_delta < 0 else "flat"
    )
    parts = [
        f"Recorded cash is {money_text(cash)} ({reserve_state} your {money_text(reserve)} reserve).",
        f"Revenue for the last {days} days is {money_text(metrics['revenue'])}, {trend} versus the prior period.",
        f"{receivables['overdue_count']} invoices worth {money_text(receivables['overdue_total'])} are overdue.",
        f"The 30-day base projection closes at {money_text(projected)}.",
    ]
    if top_alert:
        parts.append(f"Priority: {top_alert}.")
    return {
        "text": " ".join(parts),
        "generated_by": "deterministic",
        "mode": "rule_based",
        "note": "Generated from verified records without an LLM. Figures are computed by the finance engine.",
    }


def _recovery_snapshot(db: Session, user_id: int, start: date, end: date) -> dict:
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.max)
    recovered = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.user_id == user_id,
            Payment.status == "confirmed",
            Payment.invoice_id.isnot(None),
            func.coalesce(Payment.received_at, Payment.created_at) >= start_dt,
            func.coalesce(Payment.received_at, Payment.created_at) <= end_dt,
        )
        .scalar()
    )
    pending = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.user_id == user_id, Payment.status == "pending")
        .scalar()
    )
    unmatched_confirmed = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.user_id == user_id,
            Payment.status == "confirmed",
            Payment.invoice_id.is_(None),
        )
        .scalar()
    )
    return {
        "recovered_in_period": recovered,
        "awaiting_reconciliation": q2(pending + unmatched_confirmed),
        "pending_amount": pending,
        "unmatched_confirmed_amount": unmatched_confirmed,
    }


def dashboard_snapshot(db: Session, user: User, days: int = 30) -> dict:
    profile = user.profile
    if profile is None:
        raise ValueError("Business profile is missing")
    today = date.today()
    start, end, prev_start, prev_end = period_bounds(days, today)
    metrics = period_metrics(db, profile.user_id, start, end)
    prev_metrics = period_metrics(db, profile.user_id, prev_start, prev_end)

    paid_map = confirmed_paid_by_invoice(db, profile.user_id)
    receivables = invoice_aging_summary(db, profile.user_id, today)
    overdue_rows = [r for r in outstanding_invoices(db, profile.user_id, today) if r["overdue_days"] > 0]
    receivables.update(
        {
            "overdue_count": len(overdue_rows),
            "total_outstanding": receivables["total_outstanding"],
        }
    )

    cash = cash_balance(db, profile, today)
    forecast = build_forecast(db, profile, 30, "base", today)

    period_start_dt = datetime.combine(start, time.min)
    period_end_dt = datetime.combine(end, time.max)
    paypal_stats = paypal_statistics(db, profile.user_id, period_start_dt, period_end_dt)
    paypal_recent = paypal_payments(
        db, profile.user_id, start=period_start_dt, end=period_end_dt
    )[:5]

    recent_payments = (
        db.query(Payment)
        .filter(Payment.user_id == profile.user_id, Payment.status.in_(("confirmed", "pending")))
        .order_by(func.coalesce(Payment.received_at, Payment.created_at).desc())
        .limit(6)
        .all()
    )

    all_employee_entries = (
        db.query(EmployeeEntry)
        .filter(EmployeeEntry.owner_id == profile.user_id)
        .order_by(EmployeeEntry.created_at.desc(), EmployeeEntry.id.desc())
        .all()
    )
    employee_count = (
        db.query(func.count(User.id))
        .filter(
            User.owner_id == profile.user_id,
            User.role == "employee",
            User.is_active.is_(True),
        )
        .scalar()
    )

    products = db.query(Product).filter(Product.user_id == profile.user_id).all()
    inventory = [
        {
            "product_id": p.id,
            "name": p.name,
            "sku": p.sku,
            "quantity_on_hand": p.inventory.quantity_on_hand if p.inventory else 0,
            "reorder_level": p.reorder_level,
            "inventory_value": q2((p.inventory.quantity_on_hand if p.inventory else 0) * p.unit_cost),
            "low_stock": (p.inventory.quantity_on_hand if p.inventory else 0) <= p.reorder_level,
        }
        for p in products
    ]

    insights = (
        db.query(AIInsight)
        .filter(AIInsight.user_id == profile.user_id)
        .order_by(AIInsight.created_at.desc(), AIInsight.id.desc())
        .limit(4)
        .all()
    )

    snapshot_for_alerts = {
        "cash": {"recorded_balance": cash, "projected_30d": forecast["closing_balance"]},
        "receivables": receivables,
        "inventory": inventory,
        "upcoming_obligations": obligations_upcoming(db, profile.user_id, 30, today),
    }
    alerts = priority_alerts(db, profile, snapshot_for_alerts, today)

    top_alert = alerts[0]["title"] if alerts else None
    ai_summary = build_ai_summary(
        profile, metrics, prev_metrics, receivables, cash, forecast["closing_balance"], top_alert, days
    )

    receivable_items = [
        invoice_to_dict(db, row["invoice"], paid_map, include_items=False, today=today)
        for row in overdue_rows[:5]
    ]

    company_mode = "demo" if user.is_demo else "manual_records"
    return {
        "as_of": today.isoformat(),
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "currency": profile.currency,
        "data_mode": company_mode,
        "metrics": {
            "revenue": _change_block(metrics["revenue"], prev_metrics["revenue"]),
            "cash_received": _change_block(metrics["cash_received"], prev_metrics["cash_received"]),
            "operating_expenses": _change_block(metrics["expenses"], prev_metrics["expenses"]),
            "gross_profit": _change_block(metrics["gross_profit"], prev_metrics["gross_profit"]),
            "net_profit": _change_block(metrics["net_profit"], prev_metrics["net_profit"]),
            "gross_margin_pct": metrics["gross_margin_pct"],
            "net_margin_pct": metrics["net_margin_pct"],
        },
        "receivables": {
            **receivables,
            "overdue_count": len(overdue_rows),
            "top_overdue": receivable_items,
        },
        "cash": {
            "recorded_balance": cash,
            "minimum_reserve": q2(profile.min_cash_reserve),
            "projected_30d": forecast["closing_balance"],
            "projected_30d_minimum": forecast["minimum_balance"],
            "shortfall_date": forecast["shortfall_date"],
            "investable_surplus": forecast["investable_surplus"],
            "reserve_headroom": q2(cash - profile.min_cash_reserve),
            "definition": "Opening owner-recorded balance + confirmed payments − recorded expenses − paid obligations. Projected uses the 30-day base forecast and is not actual cash.",
        },
        "recovery": _recovery_snapshot(db, profile.user_id, start, end),
        "paypal": {
            "configured": paypal_client.configured,
            "enabled": paypal_client.enabled,
            "environment": paypal_client.environment,
            "mode": paypal_client.mode,
            **paypal_stats,
            "recent": [payment_to_dict(payment) for payment in paypal_recent],
            "note": (
                "Verified PayPal totals come from stored captures and signed webhooks only. "
                "Browser redirects are never treated as payment proof."
            ),
        },
        "upcoming_obligations": snapshot_for_alerts["upcoming_obligations"],
        "inventory": inventory,
        "inventory_risk": {
            "low_stock_count": sum(1 for i in inventory if i["low_stock"]),
            "total_inventory_value": q2(sum((i["inventory_value"] for i in inventory), Decimal("0.00"))),
        },
        "alerts": alerts,
        "recent_payments": [payment_to_dict(p) for p in recent_payments],
        "employee_entries": [
            entry_to_dict(db, entry) for entry in all_employee_entries[:8]
        ],
        "employee_activity": {
            **entry_totals(all_employee_entries),
            "active_employees": int(employee_count or 0),
        },
        "insights": [insight_to_dict(i) for i in insights],
        "ai_summary": ai_summary,
        "charts": {
            "cash_trend": cash_trend(db, profile, 30, today),
            "revenue_expenses": revenue_expense_series(db, profile.user_id, start, end),
        },
        "data_quality": {
            "has_paypal_live": paypal_client.configured,
            "paypal_mode": paypal_client.mode,
            "note": "All records shown are from your business ledger. Seeded demo records are labelled in Settings.",
        },
    }


def analytics_snapshot(db: Session, user: User, days: int = 90) -> dict:
    profile = user.profile
    today = date.today()
    start, end, prev_start, prev_end = period_bounds(days, today)
    metrics = period_metrics(db, profile.user_id, start, end)
    prev = period_metrics(db, profile.user_id, prev_start, prev_end)
    paid_map = confirmed_paid_by_invoice(db, profile.user_id)
    recent_invoices = (
        db.query(Invoice)
        .filter(
            Invoice.user_id == profile.user_id,
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
            Invoice.status.notin_(("draft", "void")),
        )
        .order_by(Invoice.issue_date.desc())
        .limit(20)
        .all()
    )
    return {
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "metrics": {
            "revenue": _change_block(metrics["revenue"], prev["revenue"]),
            "cogs": _change_block(metrics["cogs"], prev["cogs"]),
            "gross_profit": _change_block(metrics["gross_profit"], prev["gross_profit"]),
            "operating_expenses": _change_block(metrics["expenses"], prev["expenses"]),
            "net_profit": _change_block(metrics["net_profit"], prev["net_profit"]),
            "gross_margin_pct": metrics["gross_margin_pct"],
            "net_margin_pct": metrics["net_margin_pct"],
            "invoice_count": metrics["invoice_count"],
        },
        "series": revenue_expense_series(db, profile.user_id, start, end),
        "expense_breakdown": expense_breakdown(db, profile.user_id, start, end),
        "products": product_performance(db, profile.user_id, start, end),
        "invoices": [
            invoice_to_dict(db, inv, paid_map, include_items=False, today=today)
            for inv in recent_invoices
        ],
        "insights": [
            insight_to_dict(i)
            for i in db.query(AIInsight)
            .filter(AIInsight.user_id == profile.user_id)
            .order_by(AIInsight.created_at.desc())
            .limit(6)
            .all()
        ],
        "definitions": {
            "revenue": "Sum of issued invoice totals in the period (accrual, not cash received).",
            "cogs": "Cost of goods sold from product unit cost × quantities on issued invoices.",
            "gross_profit": "Revenue − COGS.",
            "net_profit": "Gross profit − recorded operating expenses.",
            "cash_received": "Confirmed payments received in the period, not equal to revenue.",
        },
    }
