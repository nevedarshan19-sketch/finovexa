"""Deterministic accounting calculations.

No figure in this module is produced by a language model. The same functions
feed the API, the working papers and the tests, so an accountant can trace
every number back to stored vouchers.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal
from statistics import mean

from ..models import AccountingVoucher
from .finance import q2

ZERO = Decimal("0.00")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def financial_year_for(on: date | None = None) -> str:
    on = on or date.today()
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def financial_year_bounds(financial_year: str) -> tuple[date, date]:
    try:
        start_year = int(financial_year.split("-")[0])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Invalid financial year {financial_year!r}") from exc
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def month_bounds(period: str) -> tuple[date, date]:
    """period is YYYY-MM. Returns the first and last day of the month."""
    try:
        year, month = (int(part) for part in period.split("-"))
        start = date(year, month, 1)
    except (ValueError, TypeError) as exc:
        raise ValueError("Period must use the YYYY-MM format.") from exc
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def previous_period(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{year:04d}-{month:02d}"


def split_gst(taxable: Decimal, rate: Decimal, inter_state: bool) -> dict[str, Decimal]:
    tax = q2(taxable * rate / Decimal("100"))
    if inter_state:
        igst = tax
        cgst = sgst = ZERO
    else:
        cgst = q2(tax / 2)
        sgst = tax - cgst
        igst = ZERO
    return {
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total": q2(taxable + tax),
    }


def voucher_dedupe_hash(
    client_id: int,
    voucher_type: str,
    number: str,
    voucher_date: date,
    total: Decimal,
) -> str:
    raw = "|".join(
        [
            str(client_id),
            voucher_type.strip().lower(),
            number.strip().lower(),
            voucher_date.isoformat(),
            f"{q2(total):.2f}",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _voucher_period(voucher: AccountingVoucher) -> str:
    return f"{voucher.voucher_date.year:04d}-{voucher.voucher_date.month:02d}"


def _in_period(vouchers: list[AccountingVoucher], start: date, end: date) -> list[AccountingVoucher]:
    return [v for v in vouchers if start <= v.voucher_date <= end]


def gst_summary(vouchers: list[AccountingVoucher]) -> dict:
    sale = [v for v in vouchers if v.voucher_type == "sale"]
    purchase = [v for v in vouchers if v.voucher_type == "purchase"]

    def totals(rows: list[AccountingVoucher]) -> dict[str, Decimal]:
        return {
            "taxable": q2(sum((r.taxable_value for r in rows), ZERO)),
            "cgst": q2(sum((r.cgst_amount for r in rows), ZERO)),
            "sgst": q2(sum((r.sgst_amount for r in rows), ZERO)),
            "igst": q2(sum((r.igst_amount for r in rows), ZERO)),
            "total": q2(sum((r.total_amount for r in rows), ZERO)),
        }

    output = totals(sale)
    itc = totals(purchase)
    output_tax = q2(output["cgst"] + output["sgst"] + output["igst"])
    itc_tax = q2(itc["cgst"] + itc["sgst"] + itc["igst"])
    net = q2(output_tax - itc_tax)
    return {
        "output": output,
        "itc": itc,
        "output_tax": output_tax,
        "itc_tax": itc_tax,
        "net_payable": max(net, ZERO),
        "credit_carried_forward": max(-net, ZERO),
        "direction": "payable" if net > 0 else ("refund" if net < 0 else "nil"),
    }


def gstr1_working(vouchers: list[AccountingVoucher]) -> dict:
    sale = [v for v in vouchers if v.voucher_type == "sale"]
    b2b: dict[tuple, dict] = {}
    b2cs: dict[str, dict] = {}
    for voucher in sale:
        key = (voucher.party_name, voucher.party_gstin or "", str(voucher.gst_rate), voucher.inter_state)
        bucket = b2b if voucher.party_gstin else b2cs
        map_key = key if voucher.party_gstin else str(voucher.gst_rate)
        row = bucket.setdefault(
            map_key,
            {
                "party": voucher.party_name if voucher.party_gstin else "B2C aggregate",
                "gstin": voucher.party_gstin,
                "rate": float(voucher.gst_rate),
                "supply_type": "inter_state" if voucher.inter_state else "intra_state",
                "invoice_numbers": [],
                "taxable_value": ZERO,
                "cgst": ZERO,
                "sgst": ZERO,
                "igst": ZERO,
                "invoice_value": ZERO,
            },
        )
        row["invoice_numbers"].append(voucher.number)
        row["taxable_value"] = q2(row["taxable_value"] + voucher.taxable_value)
        row["cgst"] = q2(row["cgst"] + voucher.cgst_amount)
        row["sgst"] = q2(row["sgst"] + voucher.sgst_amount)
        row["igst"] = q2(row["igst"] + voucher.igst_amount)
        row["invoice_value"] = q2(row["invoice_value"] + voucher.total_amount)
    b2b_rows = list(b2b.values())
    b2cs_rows = list(b2cs.values())
    return {
        "b2b": b2b_rows,
        "b2cs": b2cs_rows,
        "total_taxable": q2(sum((r["taxable_value"] for r in b2b_rows + b2cs_rows), ZERO)),
        "total_invoices": len(sale),
    }


def gstr3b_working(vouchers: list[AccountingVoucher]) -> dict:
    summary = gst_summary(vouchers)
    purchase_unregistered = [
        v for v in vouchers if v.voucher_type == "purchase" and v.gst_rate > 0 and not v.party_gstin
    ]
    return {
        "outward": summary["output"],
        "itc": summary["itc"],
        "net_payable": summary["net_payable"],
        "credit_carried_forward": summary["credit_carried_forward"],
        "itc_at_risk": q2(
            sum((v.cgst_amount + v.sgst_amount + v.igst_amount for v in purchase_unregistered), ZERO)
        ),
    }


def gst_mismatches(vouchers: list[AccountingVoucher], period: str) -> list[dict]:
    flags: list[dict] = []
    numbers: dict[tuple[str, str], int] = {}
    for voucher in vouchers:
        if _voucher_period(voucher) != period:
            continue
        key = (voucher.voucher_type, voucher.number.strip().lower())
        numbers[key] = numbers.get(key, 0) + 1
        if voucher.voucher_type == "sale" and voucher.party_gstin and voucher.gst_rate == 0:
            flags.append(
                {
                    "voucher": voucher.number,
                    "severity": "medium",
                    "title": "Registered customer charged 0% GST",
                    "detail": "A B2B invoice has a GSTIN but no GST. Confirm the supply is exempt or nil-rated.",
                }
            )
        if (
            voucher.voucher_type == "purchase"
            and voucher.gst_rate > 0
            and not voucher.party_gstin
        ):
            flags.append(
                {
                    "voucher": voucher.number,
                    "severity": "high",
                    "title": "Input tax credit cannot be claimed",
                    "detail": "This purchase carries GST but has no supplier GSTIN recorded.",
                }
            )
        if voucher.party_gstin and not GSTIN_RE.match(voucher.party_gstin.upper()):
            flags.append(
                {
                    "voucher": voucher.number,
                    "severity": "high",
                    "title": "GSTIN format looks invalid",
                    "detail": f"Recorded GSTIN {voucher.party_gstin} does not match the 15-character format.",
                }
            )
    for (voucher_type, number), count in numbers.items():
        if count > 1:
            flags.append(
                {
                    "voucher": number,
                    "severity": "medium",
                    "title": "Voucher number used more than once",
                    "detail": f"{voucher_type.title()} voucher {number} appears {count} times in this period.",
                }
            )
    return flags


def gst_working(vouchers: list[AccountingVoucher], period: str) -> dict:
    start, end = month_bounds(period)
    rows = _in_period(vouchers, start, end)
    summary = gst_summary(rows)
    return {
        "period": period,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "voucher_count": len(rows),
        "summary": summary,
        "gstr1": gstr1_working(rows),
        "gstr3b": gstr3b_working(rows),
        "mismatches": gst_mismatches(vouchers, period),
        "filing_status": "working_paper_only",
        "filing_note": (
            "These are working papers generated from recorded vouchers. No return has been filed "
            "with GSTN. Filing requires an authorised GSP integration and the accountant's sign-off."
        ),
    }


def monthly_summary(
    vouchers: list[AccountingVoucher],
    period: str,
    receivables: Decimal = ZERO,
    overdue_receivables: Decimal = ZERO,
    overdue_count: int = 0,
) -> dict:
    start, end = month_bounds(period)
    prev_start, prev_end = month_bounds(previous_period(period))
    current_rows = _in_period(vouchers, start, end)
    previous_rows = _in_period(vouchers, prev_start, prev_end)

    def by_type(rows: list[AccountingVoucher], kind: str) -> Decimal:
        return q2(sum((r.taxable_value for r in rows if r.voucher_type == kind), ZERO))

    revenue = by_type(current_rows, "sale")
    expense = by_type(current_rows, "purchase")
    prev_revenue = by_type(previous_rows, "sale")
    prev_expense = by_type(previous_rows, "purchase")

    def change(current: Decimal, previous: Decimal) -> float | None:
        if previous <= 0:
            return None
        return round(float((current - previous) / previous * 100), 1)

    amounts = [abs(r.total_amount) for r in current_rows]
    average = mean(amounts) if amounts else ZERO
    unusual = [
        {
            "voucher": r.number,
            "type": r.voucher_type,
            "party": r.party_name,
            "amount": float(r.total_amount),
            "reason": "More than twice the period average",
        }
        for r in current_rows
        if average > 0 and abs(r.total_amount) > average * 2
    ]

    observations: list[str] = []
    if change(revenue, prev_revenue) is not None:
        direction = "increased" if revenue >= prev_revenue else "decreased"
        observations.append(
            f"Sales {direction} {abs(change(revenue, prev_revenue) or 0):.1f}% compared with {previous_period(period)}."
        )
    else:
        observations.append("No prior-period sales were recorded, so no month-on-month comparison is shown.")
    if change(expense, prev_expense) is not None:
        direction = "rose" if expense >= prev_expense else "fell"
        observations.append(
            f"Purchases {direction} {abs(change(expense, prev_expense) or 0):.1f}% compared with {previous_period(period)}."
        )
    if overdue_count:
        observations.append(
            f"{overdue_count} practice invoice(s) totalling INR {q2(overdue_receivables):,.2f} are overdue."
        )

    return {
        "period": period,
        "revenue": revenue,
        "expenses": expense,
        "gross_profit": q2(revenue - expense),
        "gst": gst_summary(current_rows),
        "previous_period": previous_period(period),
        "revenue_change_pct": change(revenue, prev_revenue),
        "expense_change_pct": change(expense, prev_expense),
        "receivables": q2(receivables),
        "overdue_receivables": q2(overdue_receivables),
        "overdue_invoice_count": overdue_count,
        "unusual_entries": unusual,
        "observations": observations,
        "voucher_count": len(current_rows),
        "generated_from": "recorded_vouchers",
    }
