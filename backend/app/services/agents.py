from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AIInsight, Expense, FinancialObligation, PayPalRefund, Product, User
from .finance import (
    invoice_aging_summary,
    outstanding_invoices,
    period_bounds,
    period_metrics,
    q2,
    revenue_expense_series,
)
from .forecasting import build_forecast


def _amount(value) -> float:
    return float(q2(value))


def _evidence_invoice(row) -> dict:
    return {
        "type": "invoice",
        "id": row["invoice"].id,
        "label": f"Invoice {row['invoice'].number} · {row['invoice'].customer.name}",
        "amount": _amount(row["outstanding"]),
        "date": row["invoice"].due_date.isoformat(),
    }


def generate_business_insights(db: Session, user: User, days: int = 90) -> list[AIInsight]:
    profile = user.profile
    today = date.today()
    start, end, prev_start, prev_end = period_bounds(days, today)
    current = period_metrics(db, profile.user_id, start, end)
    previous = period_metrics(db, profile.user_id, prev_start, prev_end)
    aging = invoice_aging_summary(db, profile.user_id, today)
    overdue = [row for row in outstanding_invoices(db, profile.user_id, today) if row["overdue_days"] > 0]
    overdue.sort(key=lambda r: r["outstanding"], reverse=True)
    insights: list[AIInsight] = []

    if overdue:
        top = overdue[:3]
        total = aging["overdue_total"]
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"Recover {profile.currency} {total:,.0f} from {len(overdue)} overdue invoices",
                finding=(
                    f"{len(overdue)} invoices are past due, with {profile.currency} {total:,.2f} outstanding. "
                    f"The largest is invoice {top[0]['invoice'].number} for {profile.currency} {top[0]['outstanding']:,.2f}, "
                    f"{top[0]['overdue_days']} days past due."
                ),
                evidence=[_evidence_invoice(row) for row in top],
                period_start=start,
                period_end=end,
                impact_amount=total,
                confidence="high",
                limitations="Outstanding amounts are verified from the ledger; collectibility is not guaranteed.",
                recommended_action="Review priority invoices and approve payment reminders for the top three.",
                mode="deterministic",
            )
        )

    # Expense category movements over the two 30-day windows inside the period.
    cat_current = dict(
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(
            Expense.user_id == profile.user_id,
            Expense.incurred_on >= end - timedelta(days=29),
            Expense.incurred_on <= end,
        )
        .group_by(Expense.category)
        .all()
    )
    cat_previous = dict(
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(
            Expense.user_id == profile.user_id,
            Expense.incurred_on >= end - timedelta(days=59),
            Expense.incurred_on <= end - timedelta(days=30),
        )
        .group_by(Expense.category)
        .all()
    )
    spikes = []
    for category, amount in cat_current.items():
        prior = q2(cat_previous.get(category, 0))
        delta = q2(q2(amount) - prior)
        if prior > 0 and delta > 0 and delta / prior >= Decimal("0.15") and delta >= Decimal("2000"):
            spikes.append((category, q2(amount), prior, delta))
    spikes.sort(key=lambda item: item[3], reverse=True)
    if spikes:
        category, amount, prior, delta = spikes[0]
        examples = (
            db.query(Expense)
            .filter(
                Expense.user_id == profile.user_id,
                Expense.category == category,
                Expense.incurred_on >= end - timedelta(days=29),
            )
            .order_by(Expense.amount.desc())
            .limit(3)
            .all()
        )
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"{category.title()} spend rose {float(delta / prior * 100):.0f}% in the last 30 days",
                finding=(
                    f"{category} expenses increased from {profile.currency} {prior:,.2f} to {profile.currency} {amount:,.2f} "
                    f"(+{profile.currency} {delta:,.2f}) versus the prior 30 days."
                ),
                evidence=[
                    {
                        "type": "expense",
                        "id": e.id,
                        "label": f"{e.vendor} · {e.incurred_on.isoformat()}",
                        "amount": _amount(e.amount),
                    }
                    for e in examples
                ],
                period_start=end - timedelta(days=29),
                period_end=end,
                impact_amount=delta,
                confidence="medium",
                limitations="Category-level comparison can be distorted by timing or one-off purchases.",
                recommended_action=f"Review the largest {category} vendors and confirm whether the increase is recurring.",
                mode="deterministic",
            )
        )

    revenue_change = q2(current["revenue"] - previous["revenue"])
    if previous["revenue"] > 0 and abs(revenue_change) / previous["revenue"] >= Decimal("0.10"):
        direction = "increased" if revenue_change > 0 else "declined"
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"Revenue {direction} {abs(float(revenue_change / previous['revenue'] * 100)):.0f}% versus the prior period",
                finding=(
                    f"Revenue moved from {profile.currency} {previous['revenue']:,.2f} to "
                    f"{profile.currency} {current['revenue']:,.2f} ({revenue_change:+,.2f}) for the selected period. "
                    "This is invoiced revenue, not cash received."
                ),
                evidence=[
                    {
                        "type": "metric",
                        "id": "revenue",
                        "label": f"Revenue {start.isoformat()} to {end.isoformat()}",
                        "amount": _amount(current["revenue"]),
                    }
                ],
                period_start=start,
                period_end=end,
                impact_amount=abs(revenue_change),
                confidence="medium",
                limitations="Invoice issue dates drive this metric; collection timing may differ materially.",
                recommended_action="Compare sales pipeline and collection activity before changing operating spend.",
                mode="deterministic",
            )
        )

    products = db.query(Product).filter(Product.user_id == profile.user_id).all()
    low_stock = [
        p
        for p in products
        if p.inventory is not None and p.inventory.quantity_on_hand <= p.reorder_level
    ]
    if low_stock:
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"{len(low_stock)} products are at or below reorder level",
                finding=(
                    "Inventory cover is low for: "
                    + ", ".join(
                        f"{p.name} ({p.inventory.quantity_on_hand} left, reorder at {p.reorder_level})"
                        for p in low_stock[:4]
                    )
                    + "."
                ),
                evidence=[
                    {
                        "type": "product",
                        "id": p.id,
                        "label": f"{p.sku} · {p.name}",
                        "amount": _amount(p.inventory.quantity_on_hand * p.unit_cost),
                    }
                    for p in low_stock[:4]
                ],
                period_start=start,
                period_end=end,
                impact_amount=None,
                confidence="high",
                limitations="Revenue impact is not calculable without a demand forecast and supplier lead times.",
                recommended_action="Confirm supplier lead times and raise a replenishment order for the fastest-moving SKUs.",
                mode="deterministic",
            )
        )

    forecast = build_forecast(db, profile, 30, "base", today)
    if forecast["minimum_balance"] < q2(profile.min_cash_reserve):
        gap = q2(q2(profile.min_cash_reserve) - forecast["minimum_balance"])
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"Projected cash may fall {profile.currency} {gap:,.0f} below reserve",
                finding=(
                    f"The 30-day base forecast reaches a low of {profile.currency} {forecast['minimum_balance']:,.2f} "
                    f"against a {profile.currency} {profile.min_cash_reserve:,.2f} reserve. "
                    f"Earliest reserve breach: {forecast['shortfall_date'] or 'none in horizon'}."
                ),
                evidence=(
                    [
                        {
                            "type": "obligation",
                            "id": obligation.id,
                            "label": obligation.name,
                            "amount": _amount(obligation.amount),
                            "date": obligation.due_date.isoformat(),
                        }
                        for obligation in db.query(FinancialObligation)
                        .filter(
                            FinancialObligation.user_id == profile.user_id,
                            FinancialObligation.status == "scheduled",
                            FinancialObligation.due_date <= today + timedelta(days=30),
                        )
                        .order_by(FinancialObligation.amount.desc())
                        .limit(3)
                        .all()
                    ]
                ),
                period_start=today,
                period_end=today + timedelta(days=30),
                impact_amount=gap,
                confidence="medium",
                limitations="Forecast uses probability-weighted receivables and historical average spend. It is not guaranteed.",
                recommended_action="Review collection follow-ups and defer discretionary spend before the shortfall date.",
                mode="deterministic",
            )
        )

    scored_products = [
        item
        for item in _product_margins(db, profile.user_id, start, end)
        if item["revenue"] > 0 and item["margin_pct"] is not None
    ]
    if scored_products:
        worst = min(scored_products, key=lambda item: item["margin_pct"])
        if worst["margin_pct"] < 25:
            insights.append(
                AIInsight(
                    user_id=profile.user_id,
                    agent="business_manager",
                    title=f"{worst['name']} margin is {worst['margin_pct']:.1f}%",
                    finding=(
                        f"{worst['name']} generated {profile.currency} {worst['revenue']:,.2f} revenue with "
                        f"{profile.currency} {worst['gross_profit']:,.2f} gross profit over the period."
                    ),
                    evidence=[
                        {
                            "type": "product",
                            "id": worst["id"],
                            "label": worst["sku"],
                            "amount": _amount(worst["gross_profit"]),
                        }
                    ],
                    period_start=start,
                    period_end=end,
                    impact_amount=worst["gross_profit"],
                    confidence="medium",
                    limitations="Unit costs are the costs recorded in your product catalog, not live supplier quotes.",
                    recommended_action="Review pricing or supplier cost for this product before promoting it further.",
                    mode="deterministic",
                )
            )

    from .paypal import paypal_payments, paypal_statistics

    paypal_stats = paypal_statistics(
        db,
        profile.user_id,
        datetime.combine(start, time.min),
        datetime.combine(end, time.max),
    )
    paypal_rows = paypal_payments(
        db,
        profile.user_id,
        start=datetime.combine(start, time.min),
        end=datetime.combine(end, time.max),
    )
    review_rows = [
        payment
        for payment in paypal_rows
        if payment.status == "confirmed"
        and payment.amount > 0
        and (payment.invoice_id is None or payment.reconciliation_status == "mismatch")
    ]
    if review_rows:
        total = q2(sum((row.amount for row in review_rows), Decimal("0.00")))
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"Reconcile {len(review_rows)} verified PayPal payments",
                finding=(
                    f"{len(review_rows)} verified PayPal captures worth {profile.currency} {total:,.2f} "
                    "are not matched to an invoice, or do not match the invoice amount or currency. "
                    "The invoices were not marked paid."
                ),
                evidence=[
                    {
                        "type": "payment",
                        "id": payment.id,
                        "label": f"PayPal {payment.provider_ref or payment.id} · {payment.reconciliation_status}",
                        "amount": _amount(payment.amount),
                        "date": (payment.received_at or payment.created_at).date().isoformat(),
                    }
                    for payment in review_rows[:5]
                ],
                period_start=start,
                period_end=end,
                impact_amount=total,
                confidence="high",
                limitations="The money is verified by PayPal; the correct invoice is an owner decision.",
                recommended_action=(
                    "Open Payment Center → Reconciliation, review the suggested invoices and confirm "
                    "a match. AI never marks an invoice paid on its own."
                ),
                mode="deterministic",
            )
        )
    if paypal_stats["pending_count"]:
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"{paypal_stats['pending_count']} PayPal captures are pending",
                finding=(
                    f"{paypal_stats['pending_count']} PayPal captures worth {profile.currency} "
                    f"{paypal_stats['pending_total']:,.2f} are pending. Pending captures never count as cash."
                ),
                evidence=[
                    {
                        "type": "payment",
                        "id": payment.id,
                        "label": f"PayPal pending · {payment.provider_ref or payment.id}",
                        "amount": _amount(payment.amount),
                    }
                    for payment in paypal_rows
                    if payment.status == "pending"
                ][:5],
                period_start=start,
                period_end=end,
                impact_amount=paypal_stats["pending_total"],
                confidence="medium",
                limitations="Provider settlement timing is outside your control.",
                recommended_action="Monitor the webhook event log and ask the customer to complete the payment if it stays pending.",
                mode="deterministic",
            )
        )
    if paypal_stats["failed_count"]:
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"{paypal_stats['failed_count']} PayPal captures failed",
                finding=(
                    f"{paypal_stats['failed_count']} PayPal capture attempts worth {profile.currency} "
                    f"{paypal_stats['failed_total']:,.2f} failed. No cash was recorded for them."
                ),
                evidence=[
                    {
                        "type": "payment",
                        "id": payment.id,
                        "label": f"PayPal failed · {payment.provider_ref or payment.id}",
                        "amount": _amount(payment.amount),
                    }
                    for payment in paypal_rows
                    if payment.status == "failed"
                ][:5],
                period_start=start,
                period_end=end,
                impact_amount=paypal_stats["failed_total"],
                confidence="high",
                limitations="A failed attempt may be retried by the customer; it is not proof of non-payment.",
                recommended_action="Share the invoice checkout link again or prepare a reminder for the customer.",
                mode="deterministic",
            )
        )

    refund_rows = (
        db.query(PayPalRefund)
        .filter(
            PayPalRefund.user_id == profile.user_id,
            PayPalRefund.created_at >= datetime.combine(start, time.min),
            PayPalRefund.created_at <= datetime.combine(end, time.max),
        )
        .order_by(PayPalRefund.created_at.desc())
        .all()
    )
    if refund_rows:
        refund_total = q2(sum((row.amount for row in refund_rows), Decimal("0.00")))
        insights.append(
            AIInsight(
                user_id=profile.user_id,
                agent="business_manager",
                title=f"{len(refund_rows)} PayPal refunds reduced received cash",
                finding=(
                    f"{len(refund_rows)} PayPal refunds worth {profile.currency} {refund_total:,.2f} "
                    "were recorded in this period. Refunds reduce net received cash but do not change "
                    "the original capture history."
                ),
                evidence=[
                    {
                        "type": "refund",
                        "id": refund.id,
                        "label": f"PayPal refund {refund.provider_refund_id or refund.id}",
                        "amount": _amount(refund.amount),
                        "date": refund.created_at.date().isoformat(),
                    }
                    for refund in refund_rows[:5]
                ],
                period_start=start,
                period_end=end,
                impact_amount=refund_total,
                confidence="high",
                limitations="A refund can be partial and may arrive after its webhook; both are reconciled here.",
                recommended_action=(
                    "Review the refund history in Payment Center and confirm the related invoice balance "
                    "still reflects the amount you expect. Refunds require explicit owner approval."
                ),
                mode="deterministic",
            )
        )

    # Refresh the business-manager insight set, preserving other agents' insights.
    db.query(AIInsight).filter(
        AIInsight.user_id == profile.user_id, AIInsight.agent == "business_manager"
    ).delete(synchronize_session=False)
    for insight in insights:
        db.add(insight)
    db.commit()
    for insight in insights:
        db.refresh(insight)
    return insights


def _product_margins(db: Session, user_id: int, start: date, end: date) -> list[dict]:
    from .finance import product_performance

    rows = product_performance(db, user_id, start, end)
    return [
        {
            "id": item["product_id"],
            "sku": item["sku"],
            "name": item["name"],
            "revenue": item["revenue"],
            "gross_profit": item["gross_profit"],
            "margin_pct": item["margin_pct"],
        }
        for item in rows
    ]


def monitoring_summary(db: Session, user: User) -> dict:
    profile = user.profile
    today = date.today()
    metrics = period_metrics(db, profile.user_id, today - timedelta(days=29), today)
    trend = revenue_expense_series(db, profile.user_id, today - timedelta(days=13), today)
    return {
        "revenue_30d": metrics["revenue"],
        "expenses_30d": metrics["expenses"],
        "net_profit_30d": metrics["net_profit"],
        "trend": trend,
        "checks": [
            "Invoice aging and collection risk",
            "Expense category movement",
            "Revenue trend vs prior period",
            "Inventory reorder levels",
            "Cash reserve coverage",
            "Product gross margin",
        ],
        "mode": "deterministic",
        "note": "Each insight is computed from ledger records. No figures are generated by a language model.",
    }
