"""Historical Tally reports.

Every figure is computed from approved imported history (historical vouchers,
ledger masters and approved opening balances). The live FINOVEXA ledger is shown
only as a separately labelled comparison count; the two are never mixed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    AccountingClient,
    AccountingHistoricalLedger,
    AccountingHistoricalVoucher,
    AccountingHistoricalVoucherLine,
    AccountingOpeningBalance,
    AccountingTallyMigration,
    AccountingVoucher,
)
from .accounting_math import financial_year_bounds
from .finance import q2

ZERO = Decimal("0.00")

REVENUE_GROUPS = {
    "sales accounts",
    "sales",
    "direct incomes",
    "indirect incomes",
    "income",
    "revenue",
    "other income",
}
EXPENSE_GROUPS = {
    "purchase accounts",
    "purchase",
    "direct expenses",
    "indirect expenses",
    "expenses",
    "cost of goods sold",
    "cost of sales",
}
ASSET_GROUPS = {
    "cash-in-hand",
    "cash in hand",
    "bank accounts",
    "sundry debtors",
    "stock-in-hand",
    "fixed assets",
    "current assets",
    "loans & advances (asset)",
    "investments",
    "deposits (asset)",
    "miscellaneous expenses (asset)",
}
LIABILITY_GROUPS = {
    "capital account",
    "reserves & surplus",
    "loans (liability)",
    "sundry creditors",
    "duties & taxes",
    "current liabilities",
    "provisions",
    "bank od accounts",
    "secured loans",
    "unsecured loans",
}


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    return float(q2(Decimal(str(value))))


def _group(value: str | None) -> str:
    return (value or "").strip().lower()


def _infer_group(name: str) -> str:
    lowered = name.lower()
    if "sales" in lowered or "revenue" in lowered:
        return "Sales Accounts"
    if "purchase" in lowered:
        return "Purchase Accounts"
    if any(word in lowered for word in ("salary", "rent", "electric", "telephone", "office", "travel")):
        return "Indirect Expenses"
    if any(word in lowered for word in ("bank", "cash")):
        return "Bank Accounts"
    if any(word in lowered for word in ("gst", "cgst", "sgst", "igst", "tds")):
        return "Duties & Taxes"
    if any(word in lowered for word in ("debtor", "receivable")):
        return "Sundry Debtors"
    if any(word in lowered for word in ("creditor", "payable")):
        return "Sundry Creditors"
    return "Suspense Account"


def available_years(db: Session, client_id: int) -> list[str]:
    years: set[str] = set()
    for (value,) in (
        db.query(AccountingHistoricalVoucher.financial_year)
        .filter(AccountingHistoricalVoucher.client_id == client_id)
        .distinct()
        .all()
    ):
        if value:
            years.add(str(value))
    for (value,) in (
        db.query(AccountingOpeningBalance.financial_year)
        .filter(AccountingOpeningBalance.client_id == client_id)
        .distinct()
        .all()
    ):
        if value:
            years.add(str(value))
    for (value,) in (
        db.query(AccountingHistoricalLedger.financial_year)
        .filter(AccountingHistoricalLedger.client_id == client_id)
        .distinct()
        .all()
    ):
        if value:
            years.add(str(value))
    return sorted(years, reverse=True)


def _history_data(db: Session, client_id: int, financial_year: str) -> dict[str, Any]:
    vouchers = (
        db.query(AccountingHistoricalVoucher)
        .filter(
            AccountingHistoricalVoucher.client_id == client_id,
            AccountingHistoricalVoucher.financial_year == financial_year,
            AccountingHistoricalVoucher.status == "posted",
        )
        .order_by(AccountingHistoricalVoucher.voucher_date, AccountingHistoricalVoucher.id)
        .all()
    )
    voucher_ids = [voucher.id for voucher in vouchers]
    lines = (
        db.query(AccountingHistoricalVoucherLine)
        .filter(AccountingHistoricalVoucherLine.voucher_id.in_(voucher_ids))
        .all()
        if voucher_ids
        else []
    )
    ledgers = (
        db.query(AccountingHistoricalLedger)
        .filter(
            AccountingHistoricalLedger.client_id == client_id,
            AccountingHistoricalLedger.financial_year == financial_year,
        )
        .all()
    )
    opening = (
        db.query(AccountingOpeningBalance)
        .filter(
            AccountingOpeningBalance.client_id == client_id,
            AccountingOpeningBalance.financial_year == financial_year,
            AccountingOpeningBalance.status == "approved",
        )
        .first()
    )
    return {
        "vouchers": vouchers,
        "lines": lines,
        "ledgers": ledgers,
        "opening": opening,
    }


def _trial_balance(data: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}

    def bucket(name: str, group: str | None) -> dict[str, Any]:
        key = name.strip().lower()
        resolved = (group or "").strip()
        if not resolved or resolved.lower() == "suspense account":
            # Auto-created ledgers have no group in the source; infer one so the
            # trial balance, P&L and balance sheet stay meaningful.
            resolved = _infer_group(name)
        if key not in buckets:
            buckets[key] = {
                "ledger": name.strip(),
                "group": resolved,
                "opening_debit": ZERO,
                "opening_credit": ZERO,
                "debit": ZERO,
                "credit": ZERO,
            }
        elif resolved and buckets[key]["group"] == "Suspense Account":
            buckets[key]["group"] = resolved
        return buckets[key]

    for ledger in data["ledgers"]:
        entry = bucket(ledger.name, ledger.group_name)
        entry["opening_debit"] += Decimal(str(ledger.opening_debit or 0))
        entry["opening_credit"] += Decimal(str(ledger.opening_credit or 0))

    opening = data["opening"]
    if opening is not None:
        # An approved opening balance is authoritative; ledger master openings
        # for the same year are ignored to prevent double counting.
        for entry in buckets.values():
            entry["opening_debit"] = ZERO
            entry["opening_credit"] = ZERO
        for line in opening.lines:
            group = "Stock-in-Hand" if line.stock_item else line.group_name
            entry = bucket(line.ledger_name, group)
            entry["opening_debit"] += Decimal(str(line.debit or 0))
            entry["opening_credit"] += Decimal(str(line.credit or 0))

    vouchers_by_id = {voucher.id: voucher for voucher in data["vouchers"]}
    for line in data["lines"]:
        voucher = vouchers_by_id.get(line.voucher_id)
        group = line.ledger_group
        if not group and voucher and voucher.party_name and line.ledger_name == voucher.party_name:
            group = "Sundry Debtors" if voucher.voucher_type in ("sale", "credit_note") else "Sundry Creditors"
        entry = bucket(line.ledger_name, group)
        entry["debit"] += Decimal(str(line.debit or 0))
        entry["credit"] += Decimal(str(line.credit or 0))

    rows: list[dict[str, Any]] = []
    total_opening_debit = ZERO
    total_opening_credit = ZERO
    total_debit = ZERO
    total_credit = ZERO
    total_closing_debit = ZERO
    total_closing_credit = ZERO
    for entry in sorted(buckets.values(), key=lambda item: (item["group"], item["ledger"])):
        if not any(
            entry[key] for key in ("opening_debit", "opening_credit", "debit", "credit")
        ):
            continue
        closing = (
            entry["opening_debit"]
            - entry["opening_credit"]
            + entry["debit"]
            - entry["credit"]
        )
        closing_debit = closing if closing > 0 else ZERO
        closing_credit = -closing if closing < 0 else ZERO
        total_opening_debit += entry["opening_debit"]
        total_opening_credit += entry["opening_credit"]
        total_debit += entry["debit"]
        total_credit += entry["credit"]
        total_closing_debit += closing_debit
        total_closing_credit += closing_credit
        entry.update(
            {
                "closing_debit": closing_debit,
                "closing_credit": closing_credit,
                "closing": closing,
            }
        )
        rows.append(entry)

    def serialise(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "ledger": entry["ledger"],
            "group": entry["group"],
            "opening_debit": _num(entry["opening_debit"]),
            "opening_credit": _num(entry["opening_credit"]),
            "debit": _num(entry["debit"]),
            "credit": _num(entry["credit"]),
            "closing_debit": _num(entry["closing_debit"]),
            "closing_credit": _num(entry["closing_credit"]),
        }

    return {
        "rows": [serialise(entry) for entry in rows],
        "totals": {
            "opening_debit": _num(total_opening_debit),
            "opening_credit": _num(total_opening_credit),
            "debit": _num(total_debit),
            "credit": _num(total_credit),
            "closing_debit": _num(total_closing_debit),
            "closing_credit": _num(total_closing_credit),
            "difference": _num(total_closing_debit - total_closing_credit),
        },
    }


def _profit_loss(trial: dict[str, Any]) -> dict[str, Any]:
    revenue: list[dict[str, Any]] = []
    expenses: list[dict[str, Any]] = []
    for row in trial["rows"]:
        group = _group(row["group"])
        movement = row["debit"] - row["credit"]
        if group in REVENUE_GROUPS:
            amount = -movement
            if amount:
                revenue.append({"ledger": row["ledger"], "group": row["group"], "amount": amount})
        elif group in EXPENSE_GROUPS:
            if movement:
                expenses.append({"ledger": row["ledger"], "group": row["group"], "amount": movement})
    revenue_total = q2(sum((Decimal(str(item["amount"])) for item in revenue), ZERO))
    expense_total = q2(sum((Decimal(str(item["amount"])) for item in expenses), ZERO))
    return {
        "revenue": revenue,
        "expenses": expenses,
        "revenue_total": _num(revenue_total),
        "expense_total": _num(expense_total),
        "net_profit": _num(revenue_total - expense_total),
        "note": "Computed from imported vouchers only. Opening balances are not treated as income or expense.",
    }


def _balance_sheet(trial: dict[str, Any], profit_loss: dict[str, Any]) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    liabilities: list[dict[str, Any]] = []
    unclassified: list[str] = []
    for row in trial["rows"]:
        group = _group(row["group"])
        net = row["closing_debit"] - row["closing_credit"]
        if group in ASSET_GROUPS:
            if net:
                assets.append({"ledger": row["ledger"], "group": row["group"], "amount": net})
        elif group in LIABILITY_GROUPS:
            if net:
                liabilities.append({"ledger": row["ledger"], "group": row["group"], "amount": -net})
        elif group in REVENUE_GROUPS or group in EXPENSE_GROUPS:
            continue
        elif net > 0:
            assets.append({"ledger": row["ledger"], "group": "Unclassified", "amount": net})
            unclassified.append(row["ledger"])
        elif net < 0:
            liabilities.append({"ledger": row["ledger"], "group": "Unclassified", "amount": -net})
            unclassified.append(row["ledger"])
    profit = Decimal(str(profit_loss["net_profit"]))
    if profit:
        liabilities.append({"ledger": "Profit for the year", "group": "Reserves & Surplus", "amount": _num(profit)})
    asset_total = q2(sum((Decimal(str(item["amount"])) for item in assets), ZERO))
    liability_total = q2(sum((Decimal(str(item["amount"])) for item in liabilities), ZERO))
    return {
        "assets": assets,
        "liabilities": liabilities,
        "asset_total": _num(asset_total),
        "liability_total": _num(liability_total),
        "difference": _num(asset_total - liability_total),
        "unclassified_ledgers": unclassified[:50],
        "note": (
            "Prepared from imported history and approved opening balances. Stock values come from "
            "opening-balance lines tagged with a stock item."
        ),
    }


def _voucher_amount(voucher: AccountingHistoricalVoucher) -> Decimal:
    return q2(Decimal(str(voucher.total_debit or 0)))


def _monthly_amount(voucher: AccountingHistoricalVoucher) -> Decimal:
    taxable = q2(Decimal(str(voucher.taxable_value or 0)))
    return taxable if taxable else _voucher_amount(voucher)


def _voucher_history(vouchers: list[AccountingHistoricalVoucher], voucher_type: str) -> dict[str, Any]:
    rows = [v for v in vouchers if v.voucher_type == voucher_type]
    months: dict[str, dict[str, Any]] = {}
    total = ZERO
    gst = ZERO
    taxable = ZERO
    for voucher in rows:
        amount = _voucher_amount(voucher)
        total += amount
        taxable += Decimal(str(voucher.taxable_value or 0))
        gst += (
            Decimal(str(voucher.cgst_amount or 0))
            + Decimal(str(voucher.sgst_amount or 0))
            + Decimal(str(voucher.igst_amount or 0))
        )
        month = voucher.voucher_date.strftime("%Y-%m")
        entry = months.setdefault(month, {"month": month, "count": 0, "amount": ZERO, "taxable": ZERO, "gst": ZERO})
        entry["count"] += 1
        entry["amount"] += amount
        entry["taxable"] += Decimal(str(voucher.taxable_value or 0))
        entry["gst"] += (
            Decimal(str(voucher.cgst_amount or 0))
            + Decimal(str(voucher.sgst_amount or 0))
            + Decimal(str(voucher.igst_amount or 0))
        )
    return {
        "count": len(rows),
        "total": _num(total),
        "taxable": _num(taxable),
        "gst": _num(gst),
        "months": [
            {
                "month": entry["month"],
                "count": entry["count"],
                "amount": _num(entry["amount"]),
                "taxable": _num(entry["taxable"]),
                "gst": _num(entry["gst"]),
            }
            for entry in sorted(months.values(), key=lambda item: item["month"])
        ],
        "vouchers": [
            {
                "id": voucher.id,
                "number": voucher.number,
                "date": voucher.voucher_date.isoformat(),
                "party": voucher.party_name,
                "amount": _num(voucher.total_debit),
                "taxable": _num(voucher.taxable_value),
                "gst_rate": _num(voucher.gst_rate),
            }
            for voucher in rows[:200]
        ],
    }


def _monthly_summary(vouchers: list[AccountingHistoricalVoucher]) -> list[dict[str, Any]]:
    months: dict[str, dict[str, Any]] = {}
    for voucher in vouchers:
        month = voucher.voucher_date.strftime("%Y-%m")
        entry = months.setdefault(
            month,
            {"month": month, "revenue": ZERO, "purchases": ZERO, "expenses": ZERO},
        )
        amount = _monthly_amount(voucher)
        if voucher.voucher_type == "sale":
            entry["revenue"] += amount
        elif voucher.voucher_type == "credit_note":
            entry["revenue"] -= amount
        elif voucher.voucher_type == "purchase":
            entry["purchases"] += amount
        elif voucher.voucher_type == "debit_note":
            entry["purchases"] -= amount
        elif voucher.voucher_type == "expense":
            entry["expenses"] += amount
    result: list[dict[str, Any]] = []
    for month in sorted(months.values(), key=lambda item: item["month"]):
        month["profit"] = month["revenue"] - month["purchases"] - month["expenses"]
        result.append({key: (_num(value) if isinstance(value, Decimal) else value) for key, value in month.items()})
    return result


def _gst_summary(vouchers: list[AccountingHistoricalVoucher]) -> dict[str, Any]:
    def block(types: tuple[str, ...]) -> dict[str, Any]:
        rows = [voucher for voucher in vouchers if voucher.voucher_type in types]
        taxable = sum((Decimal(str(v.taxable_value or 0)) for v in rows), ZERO)
        cgst = sum((Decimal(str(v.cgst_amount or 0)) for v in rows), ZERO)
        sgst = sum((Decimal(str(v.sgst_amount or 0)) for v in rows), ZERO)
        igst = sum((Decimal(str(v.igst_amount or 0)) for v in rows), ZERO)
        return {
            "count": len(rows),
            "taxable": _num(taxable),
            "cgst": _num(cgst),
            "sgst": _num(sgst),
            "igst": _num(igst),
            "total_tax": _num(cgst + sgst + igst),
        }

    output = block(("sale",))
    credit_notes = block(("credit_note",))
    input_tax = block(("purchase",))
    debit_notes = block(("debit_note",))
    net_output = output["total_tax"] - credit_notes["total_tax"]
    net_input = input_tax["total_tax"] - debit_notes["total_tax"]
    return {
        "output": output,
        "credit_notes": credit_notes,
        "input": input_tax,
        "debit_notes": debit_notes,
        "net_output_tax": _num(net_output),
        "net_input_tax": _num(net_input),
        "net_payable": _num(net_output - net_input),
        "note": "Working summary only. GSTR-1/GSTR-3B filing remains a separate reviewed process.",
    }


def _outstanding(trial: dict[str, Any]) -> dict[str, Any]:
    customers = []
    suppliers = []
    for row in trial["rows"]:
        group = _group(row["group"])
        if group in ("sundry debtors", "debtors") or "debtor" in group:
            if row["closing_debit"]:
                customers.append({"party": row["ledger"], "amount": row["closing_debit"]})
        elif group in ("sundry creditors", "creditors") or "creditor" in group:
            if row["closing_credit"]:
                suppliers.append({"party": row["ledger"], "amount": row["closing_credit"]})
    return {
        "customers": sorted(customers, key=lambda item: -item["amount"]),
        "suppliers": sorted(suppliers, key=lambda item: -item["amount"]),
        "customer_total": _num(sum((Decimal(str(item["amount"])) for item in customers), ZERO)),
        "supplier_total": _num(sum((Decimal(str(item["amount"])) for item in suppliers), ZERO)),
    }


def ledger_history(
    db: Session, client_id: int, financial_year: str, ledger_name: str
) -> dict[str, Any]:
    data = _history_data(db, client_id, financial_year)
    name = ledger_name.strip().lower()
    opening_debit = ZERO
    opening_credit = ZERO
    opening = data["opening"]
    if opening is not None:
        for line in opening.lines:
            if line.ledger_name.strip().lower() == name:
                opening_debit += Decimal(str(line.debit or 0))
                opening_credit += Decimal(str(line.credit or 0))
    else:
        for ledger in data["ledgers"]:
            if ledger.name.strip().lower() == name:
                opening_debit += Decimal(str(ledger.opening_debit or 0))
                opening_credit += Decimal(str(ledger.opening_credit or 0))
    vouchers_by_id = {voucher.id: voucher for voucher in data["vouchers"]}
    entries = []
    balance = opening_debit - opening_credit
    for line in sorted(
        (
            line
            for line in data["lines"]
            if line.ledger_name.strip().lower() == name
            and line.voucher_id in vouchers_by_id
        ),
        key=lambda line: (vouchers_by_id[line.voucher_id].voucher_date, line.voucher_id, line.line_number),
    ):
        voucher = vouchers_by_id[line.voucher_id]
        balance += Decimal(str(line.debit or 0)) - Decimal(str(line.credit or 0))
        entries.append(
            {
                "date": voucher.voucher_date.isoformat(),
                "voucher_type": voucher.voucher_type,
                "number": voucher.number,
                "narration": voucher.narration or line.narration,
                "party": voucher.party_name,
                "debit": _num(line.debit),
                "credit": _num(line.credit),
                "balance": _num(balance),
                "balance_type": "Dr" if balance >= 0 else "Cr",
            }
        )
    return {
        "ledger": ledger_name,
        "financial_year": financial_year,
        "opening_debit": _num(opening_debit),
        "opening_credit": _num(opening_credit),
        "closing": _num(balance),
        "closing_type": "Dr" if balance >= 0 else "Cr",
        "entries": entries,
    }


def _live_summary(db: Session, client_id: int, financial_year: str) -> dict[str, Any]:
    start, end = financial_year_bounds(financial_year)
    rows = (
        db.query(AccountingVoucher)
        .filter(
            AccountingVoucher.client_id == client_id,
            AccountingVoucher.voucher_date >= start,
            AccountingVoucher.voucher_date <= end,
        )
        .all()
    )
    return {
        "vouchers": len(rows),
        "total": _num(sum((Decimal(str(v.total_amount or 0)) for v in rows), ZERO)),
        "label": "Newly recorded FINOVEXA transactions (not included in imported history)",
    }


def report_bundle(
    db: Session,
    client: AccountingClient,
    financial_year: str,
    *,
    include_comparison: bool = True,
) -> dict[str, Any]:
    data = _history_data(db, client.id, financial_year)
    trial = _trial_balance(data)
    profit_loss = _profit_loss(trial)
    balance_sheet = _balance_sheet(trial, profit_loss)
    vouchers = data["vouchers"]
    batches = (
        db.query(AccountingTallyMigration)
        .filter(
            AccountingTallyMigration.client_id == client.id,
            AccountingTallyMigration.financial_year == financial_year,
            AccountingTallyMigration.status.in_(("imported", "partially_imported")),
        )
        .count()
    )
    result = {
        "client_id": client.id,
        "client_name": client.business_name,
        "financial_year": financial_year,
        "available_years": available_years(db, client.id),
        "source": "imported_history",
        "source_note": (
            "All figures below come from approved Tally historical imports stored separately from the "
            "live FINOVEXA ledger. File-based migration only — no Tally connection is used."
        ),
        "counts": {
            "vouchers": len(vouchers),
            "ledger_lines": len(data["lines"]),
            "ledgers": len(data["ledgers"]),
            "approved_batches": batches,
            "opening_balance": data["opening"] is not None,
        },
        "live": _live_summary(db, client.id, financial_year),
        "trial_balance": trial,
        "profit_loss": profit_loss,
        "balance_sheet": balance_sheet,
        "sales": _voucher_history(vouchers, "sale"),
        "purchases": _voucher_history(vouchers, "purchase"),
        "expenses": _voucher_history(vouchers, "expense"),
        "credit_notes": _voucher_history(vouchers, "credit_note"),
        "debit_notes": _voucher_history(vouchers, "debit_note"),
        "outstanding": _outstanding(trial),
        "gst": _gst_summary(vouchers),
        "monthly": _monthly_summary(vouchers),
        "generated_at": date.today().isoformat(),
    }
    if include_comparison:
        result["comparison"] = compare_years(
            db,
            client.id,
            financial_year,
            include_current=False,
        )
    return result


def compare_years(
    db: Session,
    client_id: int,
    financial_year: str,
    *,
    include_current: bool = True,
) -> list[dict[str, Any]]:
    years = available_years(db, client_id)
    if financial_year not in years:
        years.insert(0, financial_year)
    if include_current and financial_year not in years:
        years.insert(0, financial_year)
    result: list[dict[str, Any]] = []
    for year in sorted(set(years), reverse=True):
        data = _history_data(db, client_id, year)
        trial = _trial_balance(data)
        profit_loss = _profit_loss(trial)
        balance_sheet = _balance_sheet(trial, profit_loss)
        result.append(
            {
                "financial_year": year,
                "vouchers": len(data["vouchers"]),
                "revenue": profit_loss["revenue_total"],
                "expenses": profit_loss["expense_total"],
                "net_profit": profit_loss["net_profit"],
                "sales": _voucher_history(data["vouchers"], "sale")["total"],
                "purchases": _voucher_history(data["vouchers"], "purchase")["total"],
                "assets": balance_sheet["asset_total"],
                "liabilities": balance_sheet["liability_total"],
                "gst": _gst_summary(data["vouchers"])["net_payable"],
            }
        )
    return result


def ledger_names(db: Session, client_id: int, financial_year: str | None = None) -> list[str]:
    query = db.query(AccountingHistoricalLedger.name).filter(
        AccountingHistoricalLedger.client_id == client_id
    )
    if financial_year:
        query = query.filter(AccountingHistoricalLedger.financial_year == financial_year)
    names = {str(row[0]).strip() for row in query.all() if row[0]}
    for line in (
        db.query(AccountingHistoricalVoucherLine.ledger_name)
        .join(
            AccountingHistoricalVoucher,
            AccountingHistoricalVoucher.id == AccountingHistoricalVoucherLine.voucher_id,
        )
        .filter(AccountingHistoricalVoucher.client_id == client_id)
        .distinct()
        .all()
    ):
        if line[0]:
            names.add(str(line[0]).strip())
    return sorted(names, key=str.lower)
