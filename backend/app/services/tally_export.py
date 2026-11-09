"""TallyPrime Excel/CSV export builder.

Every figure here comes from stored accounting vouchers. Validation reports
problems; it never rewrites a recorded amount. The generated files are for
import into TallyPrime by the accountant — there is no live Tally connection.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..accounting_catalog import (
    TALLY_EXPORT_LABELS,
    TALLY_EXPORT_TYPES,
    TALLY_VERSIONS,
    TALLY_VERSION_FORMATS,
)
from ..models import AccountingClient, AccountingStockItem, AccountingVoucher, utcnow
from .accounting_math import GSTIN_RE, q2, split_gst
from .accounting import save_document_file

ZERO = Decimal("0.00")

VOUCHER_TYPE_BY_EXPORT: dict[str, str] = {
    "sales": "sale",
    "purchase": "purchase",
    "payment": "payment",
    "receipt": "receipt",
    "expense": "expense",
}
TALLY_VOUCHER_TYPE: dict[str, str] = {
    "sale": "Sales",
    "purchase": "Purchase",
    "payment": "Payment",
    "receipt": "Receipt",
    "expense": "Payment",
}
VOUCHER_SHEET_NAMES: dict[str, str] = {
    "sales": "Sales Vouchers",
    "purchase": "Purchase Vouchers",
    "payment": "Payment Vouchers",
    "receipt": "Receipt Vouchers",
    "expense": "Expense Entries",
}
COMMON_GST_RATES = (Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28"))

GROUP_DEBTORS = "Sundry Debtors"
GROUP_CREDITORS = "Sundry Creditors"
GROUP_BANK = "Bank Accounts"
GROUP_CASH = "Cash-in-Hand"
GROUP_SALES = "Sales Accounts"
GROUP_PURCHASE = "Purchase Accounts"
GROUP_EXPENSES = "Indirect Expenses"
GROUP_DUTIES = "Duties & Taxes"

BANK_LEDGER_HINTS = ("bank", "hdfc", "icici", "sbi", "axis", "kotak", "current account")


def _money(value: Decimal) -> str:
    return f"{q2(value):.2f}"


def _date_text(value: date) -> str:
    return value.isoformat()


def _normalise_number(number: str) -> str:
    return (number or "").strip().lower()


def is_cash_ledger(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return "cash" in lowered and not any(hint in lowered for hint in BANK_LEDGER_HINTS)


def ledger_group(ledger: str) -> str:
    if is_cash_ledger(ledger):
        return GROUP_CASH
    return GROUP_BANK


@dataclass
class EntryLine:
    ledger: str
    group: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    is_party: bool = False
    is_tax: bool = False


@dataclass
class VoucherBlock:
    voucher: AccountingVoucher
    tally_type: str
    entries: list[EntryLine] = field(default_factory=list)
    debit_total: Decimal = ZERO
    credit_total: Decimal = ZERO

    @property
    def balanced(self) -> bool:
        return self.debit_total == self.credit_total


@dataclass
class LedgerMaster:
    name: str
    group: str
    gstin: str | None = None
    registration: str = "Unregistered"
    opening: Decimal = ZERO
    source: str = "voucher"

    @property
    def dr_cr(self) -> str:
        if self.opening > 0:
            return "Dr"
        if self.opening < 0:
            return "Cr"
        return "-"


@dataclass
class ExportData:
    vouchers: list[AccountingVoucher]
    stock_items: list[AccountingStockItem]
    blocks: list[VoucherBlock]
    ledgers: list[LedgerMaster]
    voucher_all: list[AccountingVoucher]


# ---------------------------------------------------------------- collection


def _voucher_query(db: Session, client_id: int):
    return db.query(AccountingVoucher).filter(
        AccountingVoucher.client_id == client_id,
        AccountingVoucher.status == "posted",
    )


def _party_group(voucher_type: str) -> str:
    return GROUP_DEBTORS if voucher_type in ("sale", "receipt") else GROUP_CREDITORS


def _fallback_bank(voucher: AccountingVoucher) -> str:
    if voucher.bank_ledger:
        return voucher.bank_ledger
    if voucher.voucher_type in ("payment", "receipt") and voucher.ledger_name:
        return voucher.ledger_name
    return "Cash"


def build_block(voucher: AccountingVoucher) -> VoucherBlock:
    """Build the double-entry lines exactly from the stored voucher amounts."""
    block = VoucherBlock(
        voucher=voucher,
        tally_type=TALLY_VOUCHER_TYPE.get(voucher.voucher_type, "Journal"),
    )
    taxable = q2(voucher.taxable_value)
    cgst = q2(voucher.cgst_amount)
    sgst = q2(voucher.sgst_amount)
    igst = q2(voucher.igst_amount)
    total = q2(voucher.total_amount)
    output = voucher.voucher_type == "sale"

    if voucher.voucher_type == "sale":
        block.entries.append(
            EntryLine(voucher.party_name, GROUP_DEBTORS, debit=total, is_party=True)
        )
        block.entries.append(EntryLine(voucher.ledger_name, GROUP_SALES, credit=taxable))
    elif voucher.voucher_type == "purchase":
        block.entries.append(EntryLine(voucher.ledger_name, GROUP_PURCHASE, debit=taxable))
        block.entries.append(
            EntryLine(voucher.party_name, GROUP_CREDITORS, credit=total, is_party=True)
        )
    elif voucher.voucher_type == "payment":
        block.entries.append(
            EntryLine(voucher.party_name, GROUP_CREDITORS, debit=total, is_party=True)
        )
        bank = _fallback_bank(voucher)
        block.entries.append(EntryLine(bank, ledger_group(bank), credit=total))
    elif voucher.voucher_type == "receipt":
        bank = _fallback_bank(voucher)
        block.entries.append(EntryLine(bank, ledger_group(bank), debit=total))
        block.entries.append(
            EntryLine(voucher.party_name, GROUP_DEBTORS, credit=total, is_party=True)
        )
    elif voucher.voucher_type == "expense":
        block.entries.append(EntryLine(voucher.ledger_name, GROUP_EXPENSES, debit=taxable))
        bank = _fallback_bank(voucher)
        block.entries.append(EntryLine(bank, ledger_group(bank), credit=total))
    else:  # journal is not part of the export catalogue; keep a balanced fallback
        block.entries.append(EntryLine(voucher.ledger_name, GROUP_EXPENSES, debit=taxable))
        block.entries.append(EntryLine(voucher.party_name, GROUP_CREDITORS, credit=total))

    if cgst or sgst or igst:
        prefix = "Output" if output else "Input"
        for label, amount in (("CGST", cgst), ("SGST", sgst), ("IGST", igst)):
            if amount:
                block.entries.append(
                    EntryLine(f"{prefix} {label}", GROUP_DUTIES, credit=amount if output else ZERO,
                              debit=ZERO if output else amount, is_tax=True)
                )

    block.debit_total = q2(sum((line.debit for line in block.entries), ZERO))
    block.credit_total = q2(sum((line.credit for line in block.entries), ZERO))
    return block


def collect_export_data(
    db: Session,
    client: AccountingClient,
    export_types: list[str],
    from_date: date | None,
    to_date: date | None,
) -> ExportData:
    selected_types = [VOUCHER_TYPE_BY_EXPORT[t] for t in export_types if t in VOUCHER_TYPE_BY_EXPORT]
    vouchers: list[AccountingVoucher] = []
    if selected_types:
        query = _voucher_query(db, client.id).filter(
            AccountingVoucher.voucher_type.in_(selected_types)
        )
        if from_date:
            query = query.filter(AccountingVoucher.voucher_date >= from_date)
        if to_date:
            query = query.filter(AccountingVoucher.voucher_date <= to_date)
        vouchers = query.order_by(
            AccountingVoucher.voucher_date, AccountingVoucher.number, AccountingVoucher.id
        ).all()

    stock_items: list[AccountingStockItem] = []
    if "stock_masters" in export_types:
        stock_items = (
            db.query(AccountingStockItem)
            .filter(AccountingStockItem.client_id == client.id, AccountingStockItem.is_active.is_(True))
            .order_by(AccountingStockItem.name)
            .all()
        )

    voucher_all = _voucher_query(db, client.id).all()
    blocks = [build_block(v) for v in vouchers]
    ledgers = build_ledger_masters(blocks, stock_items)
    return ExportData(
        vouchers=vouchers,
        stock_items=stock_items,
        blocks=blocks,
        ledgers=ledgers,
        voucher_all=voucher_all,
    )


def build_ledger_masters(
    blocks: list[VoucherBlock], stock_items: list[AccountingStockItem]
) -> list[LedgerMaster]:
    masters: dict[str, LedgerMaster] = {}

    def add(name: str, group: str, *, gstin: str | None = None, source: str = "voucher") -> None:
        key = (name or "").strip()
        if not key:
            return
        existing = masters.get(key)
        if existing is None:
            masters[key] = LedgerMaster(
                name=key,
                group=group,
                gstin=gstin,
                registration="Regular" if gstin else ("Unregistered"),
                source=source,
            )
        elif gstin and not existing.gstin:
            existing.gstin = gstin
            existing.registration = "Regular"

    for block in blocks:
        voucher = block.voucher
        for line in block.entries:
            add(line.ledger, line.group, gstin=voucher.party_gstin if line.is_party else None)
    if stock_items:
        add("Stock-in-Hand", "Stock-in-Hand", source="stock")
    add("Round Off", "Indirect Expenses", source="standard")
    return sorted(masters.values(), key=lambda m: (m.group, m.name.lower()))


# ---------------------------------------------------------------- validation


def _problem(
    severity: str,
    code: str,
    message: str,
    *,
    voucher: AccountingVoucher | None = None,
    field_name: str | None = None,
    expected: Any | None = None,
    stored: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if voucher is not None:
        payload["voucher_type"] = voucher.voucher_type
        payload["voucher_number"] = voucher.number
        payload["voucher_date"] = _date_text(voucher.voucher_date)
    if field_name:
        payload["field"] = field_name
    if expected is not None:
        payload["expected"] = str(expected)
    if stored is not None:
        payload["stored"] = str(stored)
    return payload


def validate_export(
    data: ExportData,
    export_types: list[str],
    client: AccountingClient,
    from_date: date | None,
    to_date: date | None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    selected_types = [VOUCHER_TYPE_BY_EXPORT[t] for t in export_types if t in VOUCHER_TYPE_BY_EXPORT]

    # 1. Mandatory fields
    missing_fields = 0
    for block in data.blocks:
        voucher = block.voucher
        problems: list[str] = []
        if not (voucher.number or "").strip():
            problems.append("voucher number")
        if not (voucher.party_name or "").strip():
            problems.append("party name")
        if not (voucher.ledger_name or "").strip():
            problems.append("ledger name")
        if voucher.total_amount is None or q2(voucher.total_amount) <= 0:
            problems.append("total amount")
        if not voucher.voucher_date:
            problems.append("voucher date")
        if problems:
            missing_fields += 1
            errors.append(
                _problem(
                    "error",
                    "MISSING_MANDATORY_FIELD",
                    f"Voucher is missing: {', '.join(problems)}.",
                    voucher=voucher,
                    field_name=problems[0],
                )
            )
    checks.append(
        {
            "key": "mandatory_fields",
            "label": "Mandatory voucher fields are complete",
            "status": "failed" if missing_fields else "passed",
            "detail": (
                f"{missing_fields} voucher(s) have missing mandatory fields."
                if missing_fields
                else f"All {len(data.blocks)} exported voucher(s) have a number, date, party, ledger and amount."
            ),
        }
    )

    # 2. Ledger mapping
    unmapped = [
        block.voucher
        for block in data.blocks
        if any(not (line.ledger or "").strip() or not (line.group or "").strip() for line in block.entries)
    ]
    for voucher in unmapped:
        errors.append(
            _problem(
                "error",
                "LEDGER_MAPPING_MISSING",
                "A transaction line has no ledger, so Tally cannot map this entry.",
                voucher=voucher,
                field_name="ledger_name",
            )
        )
    checks.append(
        {
            "key": "ledger_mapping",
            "label": "Every line maps to a Tally ledger and group",
            "status": "failed" if unmapped else "passed",
            "detail": (
                f"{len(unmapped)} voucher(s) contain an unmapped line."
                if unmapped
                else f"{sum(len(b.entries) for b in data.blocks)} ledger lines mapped to Tally groups."
            ),
        }
    )

    # 3. Debit / credit balance
    unbalanced = [block for block in data.blocks if not block.balanced]
    for block in unbalanced:
        errors.append(
            _problem(
                "error",
                "VOUCHER_UNBALANCED",
                "Debit and credit totals do not match for this voucher.",
                voucher=block.voucher,
                expected=_money(block.debit_total),
                stored=_money(block.credit_total),
            )
        )
    total_debit = q2(sum((b.debit_total for b in data.blocks), ZERO))
    total_credit = q2(sum((b.credit_total for b in data.blocks), ZERO))
    if total_debit != total_credit:
        errors.append(
            _problem(
                "error",
                "LEDGER_UNBALANCED",
                "Total debits and credits differ across the export batch.",
                expected=_money(total_debit),
                stored=_money(total_credit),
            )
        )
    checks.append(
        {
            "key": "debit_credit",
            "label": "Debit and credit totals match",
            "status": "failed" if unbalanced or total_debit != total_credit else "passed",
            "detail": f"Debit {_money(total_debit)} · Credit {_money(total_credit)}.",
        }
    )

    # 4. GST recomputation (never rewritten)
    gst_errors = 0
    for block in data.blocks:
        voucher = block.voucher
        if voucher.voucher_type in ("payment", "receipt", "journal"):
            carried = q2(voucher.cgst_amount + voucher.sgst_amount + voucher.igst_amount)
            if carried:
                warnings.append(
                    _problem(
                        "warning",
                        "GST_ON_SETTLEMENT",
                        "A payment/receipt voucher carries GST amounts. Tally settles these against the bill; GST is not re-booked.",
                        voucher=voucher,
                    )
                )
            continue
        expected = split_gst(
            q2(voucher.taxable_value), Decimal(voucher.gst_rate or 0), bool(voucher.inter_state)
        )
        if (
            expected["cgst"] != q2(voucher.cgst_amount)
            or expected["sgst"] != q2(voucher.sgst_amount)
            or expected["igst"] != q2(voucher.igst_amount)
        ):
            gst_errors += 1
            errors.append(
                _problem(
                    "error",
                    "GST_SPLIT_MISMATCH",
                    "Stored GST does not match the tax computed from the taxable value and rate. Correct the voucher; the export will not adjust it.",
                    voucher=voucher,
                    field_name="gst",
                    expected=f"CGST {_money(expected['cgst'])} / SGST {_money(expected['sgst'])} / IGST {_money(expected['igst'])}",
                    stored=f"CGST {_money(voucher.cgst_amount)} / SGST {_money(voucher.sgst_amount)} / IGST {_money(voucher.igst_amount)}",
                )
            )
        if expected["total"] != q2(voucher.total_amount):
            gst_errors += 1
            errors.append(
                _problem(
                    "error",
                    "VOUCHER_TOTAL_MISMATCH",
                    "Voucher total does not equal taxable value plus GST. The stored amount is reported, not modified.",
                    voucher=voucher,
                    field_name="total_amount",
                    expected=_money(expected["total"]),
                    stored=_money(voucher.total_amount),
                )
            )
        rate = Decimal(voucher.gst_rate or 0)
        if rate not in COMMON_GST_RATES:
            warnings.append(
                _problem(
                    "warning",
                    "UNUSUAL_GST_RATE",
                    f"GST rate {rate}% is not a standard slab. Confirm the rate before importing.",
                    voucher=voucher,
                    field_name="gst_rate",
                )
            )
    checks.append(
        {
            "key": "gst",
            "label": "GST split and voucher totals reconcile",
            "status": "failed" if gst_errors else "passed",
            "detail": (
                f"{gst_errors} GST or total mismatch(es) found."
                if gst_errors
                else "Stored CGST, SGST, IGST and totals match the recorded taxable value and rate."
            ),
        }
    )

    # 5. Duplicate voucher numbers
    seen: dict[tuple[str, str], int] = {}
    duplicates = 0
    for block in data.blocks:
        key = (block.voucher.voucher_type, _normalise_number(block.voucher.number))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 2:
            duplicates += 1
            errors.append(
                _problem(
                    "error",
                    "DUPLICATE_VOUCHER_NUMBER",
                    f"{block.voucher.voucher_type.title()} voucher number is used more than once in this export.",
                    voucher=block.voucher,
                    field_name="number",
                )
            )
    # Same number outside the selected period is a warning, not a silent change.
    external_numbers: dict[tuple[str, str], list[AccountingVoucher]] = {}
    exported_ids = {b.voucher.id for b in data.blocks}
    for voucher in data.voucher_all:
        if voucher.id in exported_ids:
            continue
        key = (voucher.voucher_type, _normalise_number(voucher.number))
        external_numbers.setdefault(key, []).append(voucher)
    for block in data.blocks:
        key = (block.voucher.voucher_type, _normalise_number(block.voucher.number))
        other = external_numbers.get(key)
        if other:
            warnings.append(
                _problem(
                    "warning",
                    "NUMBER_EXISTS_OUTSIDE_PERIOD",
                    "The same voucher number exists outside the exported period. Check for accidental re-use.",
                    voucher=block.voucher,
                    field_name="number",
                    stored=other[0].voucher_date.isoformat(),
                )
            )
    checks.append(
        {
            "key": "duplicates",
            "label": "No duplicate voucher numbers",
            "status": "failed" if duplicates else "passed",
            "detail": (
                f"{duplicates} duplicate number(s) detected."
                if duplicates
                else "Every voucher number is unique within its voucher type for this export."
            ),
        }
    )

    # 6. Party details
    party_errors = 0
    for block in data.blocks:
        voucher = block.voucher
        gstin = (voucher.party_gstin or "").strip().upper()
        if gstin and not GSTIN_RE.match(gstin):
            party_errors += 1
            errors.append(
                _problem(
                    "error",
                    "INVALID_PARTY_GSTIN",
                    f"Party GSTIN {gstin} is not a valid 15-character GSTIN. Correct it on the voucher.",
                    voucher=voucher,
                    field_name="party_gstin",
                )
            )
        elif not gstin and voucher.voucher_type in ("sale", "purchase"):
            warnings.append(
                _problem(
                    "warning",
                    "PARTY_GSTIN_MISSING",
                    "No party GSTIN is recorded. The voucher will import as an unregistered/B2C party.",
                    voucher=voucher,
                    field_name="party_gstin",
                )
            )
        if voucher.voucher_type in ("payment", "receipt", "expense") and not voucher.bank_ledger:
            warnings.append(
                _problem(
                    "warning",
                    "PAYMENT_ACCOUNT_NOT_SET",
                    f"No bank/cash ledger is set on this voucher; the export uses '{_fallback_bank(voucher)}'.",
                    voucher=voucher,
                    field_name="bank_ledger",
                )
            )
        if voucher.voucher_type == "purchase" and Decimal(voucher.gst_rate or 0) > 0 and not gstin:
            warnings.append(
                _problem(
                    "warning",
                    "ITC_PARTY_GSTIN_MISSING",
                    "Purchase carries GST without a supplier GSTIN, so input tax credit is at risk.",
                    voucher=voucher,
                    field_name="party_gstin",
                )
            )
    checks.append(
        {
            "key": "party_details",
            "label": "Party details are importable",
            "status": "failed" if party_errors else "passed",
            "detail": (
                f"{party_errors} invalid party GSTIN(s) found."
                if party_errors
                else "Party names are present and any recorded GSTIN matches the standard format."
            ),
        }
    )

    # 7. Stock item masters
    stock_errors = 0
    if "stock_masters" in export_types:
        for item in data.stock_items:
            problems: list[str] = []
            if not (item.name or "").strip():
                problems.append("item name")
            if not (item.sku or "").strip():
                problems.append("SKU")
            if not (item.unit or "").strip():
                problems.append("unit")
            if problems:
                stock_errors += 1
                errors.append(
                    {
                        "severity": "error",
                        "code": "STOCK_ITEM_INCOMPLETE",
                        "message": f"Stock item is missing: {', '.join(problems)}.",
                        "field": problems[0],
                        "stored": item.sku or item.name or "unnamed",
                    }
                )
            if not (item.hsn_sac or "").strip():
                warnings.append(
                    {
                        "severity": "warning",
                        "code": "STOCK_ITEM_HSN_MISSING",
                        "message": f"Stock item {item.name or item.sku} has no HSN/SAC code.",
                        "field": "hsn_sac",
                        "stored": item.sku or item.name,
                    }
                )
        checks.append(
            {
                "key": "stock_items",
                "label": "Stock item masters are complete",
                "status": "failed" if stock_errors else "passed",
                "detail": (
                    f"{stock_errors} incomplete stock item(s)."
                    if stock_errors
                    else f"{len(data.stock_items)} stock item master(s) checked for name, SKU and unit."
                ),
            }
        )

    # 8. Empty selections
    by_type: dict[str, list[VoucherBlock]] = {vtype: [] for vtype in VOUCHER_TYPE_BY_EXPORT.values()}
    for block in data.blocks:
        by_type.setdefault(block.voucher.voucher_type, []).append(block)
    for export_type, voucher_type in VOUCHER_TYPE_BY_EXPORT.items():
        if export_type in export_types and not by_type.get(voucher_type):
            warnings.append(
                {
                    "severity": "warning",
                    "code": "NO_RECORDS",
                    "message": f"No {TALLY_EXPORT_LABELS[export_type].lower()} found in the selected period.",
                }
            )

    summary_by_type: list[dict[str, Any]] = []
    for export_type in TALLY_EXPORT_TYPES:
        if export_type not in export_types:
            continue
        voucher_type = VOUCHER_TYPE_BY_EXPORT.get(export_type)
        rows = by_type.get(voucher_type, []) if voucher_type else []
        summary_by_type.append(
            {
                "export_type": export_type,
                "label": TALLY_EXPORT_LABELS[export_type],
                "voucher_count": len(rows),
                "taxable_value": _money(sum((b.voucher.taxable_value for b in rows), ZERO)),
                "cgst": _money(sum((b.voucher.cgst_amount for b in rows), ZERO)),
                "sgst": _money(sum((b.voucher.sgst_amount for b in rows), ZERO)),
                "igst": _money(sum((b.voucher.igst_amount for b in rows), ZERO)),
                "total": _money(sum((b.voucher.total_amount for b in rows), ZERO)),
                "debit_total": _money(sum((b.debit_total for b in rows), ZERO)),
                "credit_total": _money(sum((b.credit_total for b in rows), ZERO)),
            }
        )

    summary = {
        "voucher_count": len(data.blocks),
        "entry_count": sum(len(b.entries) for b in data.blocks),
        "ledger_count": len(data.ledgers),
        "stock_item_count": len(data.stock_items),
        "debit_total": _money(total_debit),
        "credit_total": _money(total_credit),
        "balanced": total_debit == total_credit,
        "by_type": summary_by_type,
    }
    return {
        "ok": not errors,
        "client_id": client.id,
        "client_name": client.business_name,
        "client_gstin": client.gstin,
        "export_types": list(export_types),
        "period": {
            "from": from_date.isoformat() if from_date else None,
            "to": to_date.isoformat() if to_date else None,
        },
        "summary": summary,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "checked_at": utcnow().isoformat(timespec="seconds"),
        "note": (
            "Validation reads the recorded vouchers only. No amount is adjusted or corrected "
            "during export; every mismatch is listed above for the accountant to fix at source."
        ),
        "selected_types": selected_types,
    }


# ---------------------------------------------------------------- rows


VOUCHER_COLUMNS = [
    "Voucher Date",
    "Voucher Type",
    "Voucher Number",
    "Reference",
    "Party",
    "Party GSTIN",
    "Place of Supply",
    "Ledger",
    "Bank / Cash Ledger",
    "Category",
    "Taxable Value",
    "GST Rate",
    "CGST",
    "SGST",
    "IGST",
    "Total",
    "Debit Ledger",
    "Debit Total",
    "Credit Ledgers",
    "Credit Total",
    "Balanced",
    "Narration",
]

ENTRY_COLUMNS = [
    "Voucher Date",
    "Voucher Type",
    "Voucher Number",
    "Party",
    "Party GSTIN",
    "Ledger",
    "Ledger Group",
    "Debit",
    "Credit",
    "Narration",
]

LEDGER_COLUMNS = ["Ledger Name", "Parent Group", "Opening Balance", "Dr/Cr", "GSTIN", "Registration", "Source"]
STOCK_COLUMNS = [
    "Item Name",
    "SKU",
    "Unit",
    "HSN/SAC",
    "GST Rate",
    "Opening Quantity",
    "Opening Rate",
    "Opening Value",
]
VALIDATION_COLUMNS = ["Severity", "Code", "Voucher Type", "Voucher Number", "Field", "Message", "Expected", "Stored"]


def _credit_ledgers(block: VoucherBlock) -> str:
    return " / ".join(line.ledger for line in block.entries if line.credit)
def _debit_ledgers(block: VoucherBlock) -> str:
    return " / ".join(line.ledger for line in block.entries if line.debit)


def voucher_rows(blocks: list[VoucherBlock]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for block in sorted(blocks, key=lambda b: (b.voucher.voucher_date, b.voucher.number)):
        voucher = block.voucher
        rows.append(
            [
                _date_text(voucher.voucher_date),
                TALLY_VOUCHER_TYPE.get(voucher.voucher_type, voucher.voucher_type.title()),
                voucher.number,
                voucher.number,
                voucher.party_name,
                (voucher.party_gstin or "").upper(),
                "Inter-state" if voucher.inter_state else "Intra-state",
                voucher.ledger_name,
                voucher.bank_ledger or "",
                voucher.category or "",
                float(q2(voucher.taxable_value)),
                float(Decimal(voucher.gst_rate or 0)),
                float(q2(voucher.cgst_amount)),
                float(q2(voucher.sgst_amount)),
                float(q2(voucher.igst_amount)),
                float(q2(voucher.total_amount)),
                _debit_ledgers(block),
                float(block.debit_total),
                _credit_ledgers(block),
                float(block.credit_total),
                "Yes" if block.balanced else "No",
                voucher.description or "",
            ]
        )
    return rows


def entry_rows(blocks: list[VoucherBlock]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for block in sorted(blocks, key=lambda b: (b.voucher.voucher_date, b.voucher.number)):
        voucher = block.voucher
        for line in block.entries:
            rows.append(
                [
                    _date_text(voucher.voucher_date),
                    TALLY_VOUCHER_TYPE.get(voucher.voucher_type, voucher.voucher_type.title()),
                    voucher.number,
                    voucher.party_name,
                    (voucher.party_gstin or "").upper(),
                    line.ledger,
                    line.group,
                    float(q2(line.debit)),
                    float(q2(line.credit)),
                    voucher.description or "",
                ]
            )
    return rows


def ledger_rows(ledgers: list[LedgerMaster]) -> list[list[Any]]:
    return [
        [
            master.name,
            master.group,
            float(q2(master.opening)),
            master.dr_cr,
            master.gstin or "",
            master.registration,
            master.source,
        ]
        for master in ledgers
    ]


def stock_rows(items: list[AccountingStockItem]) -> list[list[Any]]:
    return [
        [
            item.name,
            item.sku,
            item.unit,
            item.hsn_sac or "",
            float(Decimal(item.gst_rate or 0)),
            float(Decimal(item.opening_qty or 0)),
            float(Decimal(item.opening_rate or 0)),
            float(q2(Decimal(item.opening_qty or 0) * Decimal(item.opening_rate or 0))),
        ]
        for item in items
    ]


def validation_rows(report: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for entry in report.get("errors", []) + report.get("warnings", []):
        rows.append(
            [
                entry.get("severity", ""),
                entry.get("code", ""),
                entry.get("voucher_type", ""),
                entry.get("voucher_number", ""),
                entry.get("field", ""),
                entry.get("message", ""),
                entry.get("expected", ""),
                entry.get("stored", ""),
            ]
        )
    return rows


# ---------------------------------------------------------------- Tally XML


def _xml_money(value: Decimal) -> str:
    return f"{q2(value):.2f}"


def _tally_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _envelope(company: str, report_name: str, body: str) -> str:
    return (
        "<ENVELOPE>\n"
        "  <HEADER>\n"
        "    <TALLYREQUEST>Import Data</TALLYREQUEST>\n"
        "  </HEADER>\n"
        "  <BODY>\n"
        "    <IMPORTDATA>\n"
        "      <REQUESTDESC>\n"
        f"        <REPORTNAME>{escape(report_name)}</REPORTNAME>\n"
        "        <STATICVARIABLES>\n"
        f"          <SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>\n"
        "        </STATICVARIABLES>\n"
        "      </REQUESTDESC>\n"
        "      <REQUESTDATA>\n"
        f"{body}"
        "      </REQUESTDATA>\n"
        "    </IMPORTDATA>\n"
        "  </BODY>\n"
        "</ENVELOPE>\n"
    )


def master_xml(data: ExportData, client: AccountingClient) -> str:
    parts: list[str] = []
    for master in data.ledgers:
        gstin = master.gstin or ""
        parts.append(
            "        <TALLYMESSAGE xmlns:UDF=\"TallyUDF\">\n"
            f"          <LEDGER NAME={quoteattr(master.name)} ACTION=\"Create\">\n"
            f"            <NAME>{escape(master.name)}</NAME>\n"
            f"            <PARENT>{escape(master.group)}</PARENT>\n"
            "            <ISBILLWISEON>Yes</ISBILLWISEON>\n"
            f"            <GSTREGISTRATIONTYPE>{escape(master.registration)}</GSTREGISTRATIONTYPE>\n"
            + (f"            <PARTYGSTIN>{escape(gstin)}</PARTYGSTIN>\n" if gstin else "")
            + "          </LEDGER>\n"
            "        </TALLYMESSAGE>\n"
        )
    for item in data.stock_items:
        opening = f"{Decimal(item.opening_qty or 0):.3f} {item.unit}"
        parts.append(
            "        <TALLYMESSAGE xmlns:UDF=\"TallyUDF\">\n"
            f"          <STOCKITEM NAME={quoteattr(item.name)} ACTION=\"Create\">\n"
            f"            <NAME>{escape(item.name)}</NAME>\n"
            f"            <BASEUNITS>{escape(item.unit)}</BASEUNITS>\n"
            + (f"            <HSNCODE>{escape(item.hsn_sac or '')}</HSNCODE>\n" if item.hsn_sac else "")
            + f"            <OPENINGBALANCE>{escape(opening)}</OPENINGBALANCE>\n"
            f"            <OPENINGRATE>{Decimal(item.opening_rate or 0):.2f}</OPENINGRATE>\n"
            f"            <OPENINGVALUE>{_xml_money(Decimal(item.opening_qty or 0) * Decimal(item.opening_rate or 0))}</OPENINGVALUE>\n"
            "          </STOCKITEM>\n"
            "        </TALLYMESSAGE>\n"
        )
    return _envelope(client.business_name, "All Masters", "".join(parts))


def voucher_xml(data: ExportData, client: AccountingClient) -> str:
    parts: list[str] = []
    for block in sorted(data.blocks, key=lambda b: (b.voucher.voucher_date, b.voucher.number)):
        voucher = block.voucher
        lines: list[str] = []
        for line in block.entries:
            debit = line.debit > 0
            amount = line.debit if debit else line.credit
            signed = -amount if debit else amount
            lines.append(
                "            <ALLLEDGERENTRIES.LIST>\n"
                f"              <LEDGERNAME>{escape(line.ledger)}</LEDGERNAME>\n"
                f"              <ISDEEMEDPOSITIVE>{'Yes' if debit else 'No'}</ISDEEMEDPOSITIVE>\n"
                f"              <AMOUNT>{_xml_money(signed)}</AMOUNT>\n"
                "            </ALLLEDGERENTRIES.LIST>\n"
            )
        gstin = (voucher.party_gstin or "").upper()
        parts.append(
            "        <TALLYMESSAGE xmlns:UDF=\"TallyUDF\">\n"
            f"          <VOUCHER VCHTYPE={quoteattr(block.tally_type)} ACTION=\"Create\" OBJVIEW=\"Invoice Voucher View\">\n"
            f"            <DATE>{_tally_date(voucher.voucher_date)}</DATE>\n"
            f"            <EFFECTIVEDATE>{_tally_date(voucher.voucher_date)}</EFFECTIVEDATE>\n"
            f"            <VOUCHERTYPENAME>{escape(block.tally_type)}</VOUCHERTYPENAME>\n"
            f"            <VOUCHERNUMBER>{escape(voucher.number)}</VOUCHERNUMBER>\n"
            f"            <REFERENCE>{escape(voucher.number)}</REFERENCE>\n"
            f"            <PARTYLEDGERNAME>{escape(voucher.party_name)}</PARTYLEDGERNAME>\n"
            + (f"            <PARTYGSTIN>{escape(gstin)}</PARTYGSTIN>\n" if gstin else "")
            + f"            <NARRATION>{escape(voucher.description or '')}</NARRATION>\n"
            + "".join(lines)
            + "          </VOUCHER>\n"
            "        </TALLYMESSAGE>\n"
        )
    return _envelope(client.business_name, "Vouchers", "".join(parts))


# ---------------------------------------------------------------- file builders


def _summary_pairs(data: ExportData, report: dict[str, Any], client: AccountingClient) -> list[tuple[str, Any]]:
    period = report["period"]
    pairs: list[tuple[str, Any]] = [
        ("Client", client.business_name),
        ("Client GSTIN", client.gstin or "Not recorded"),
        ("Period from", period["from"] or "Opening"),
        ("Period to", period["to"] or "Latest"),
        ("Generated at (UTC)", report["checked_at"]),
        ("Vouchers exported", report["summary"]["voucher_count"]),
        ("Ledger entries", report["summary"]["entry_count"]),
        ("Ledger masters", report["summary"]["ledger_count"]),
        ("Stock item masters", report["summary"]["stock_item_count"]),
        ("Total debit", report["summary"]["debit_total"]),
        ("Total credit", report["summary"]["credit_total"]),
        ("Debit equals credit", "Yes" if report["summary"]["balanced"] else "No"),
        ("Errors", report["error_count"]),
        ("Warnings", report["warning_count"]),
    ]
    for item in report["summary"]["by_type"]:
        pairs.append(
            (
                f"{item['label']} — vouchers / taxable / total",
                f"{item['voucher_count']} / {item['taxable_value']} / {item['total']}",
            )
        )
    return pairs


def _instructions(report: dict[str, Any], client: AccountingClient) -> list[tuple[str, str]]:
    return [
        ("What this file is", "A TallyPrime import pack generated from the vouchers recorded in FINOVEXA. It is a file export only — nothing is written to Tally automatically."),
        ("Company", f"Open {client.business_name} in TallyPrime. The XML files target this company name; rename the company or edit SVCURRENTCOMPANY to match."),
        ("Step 1 — back up", "Take a TallyPrime backup (Gateway of Tally → Backup) before importing masters or vouchers."),
        ("Step 2 — import masters", "Gateway of Tally → Import Data → Masters. Choose tally-master-import.xml. Review every ledger group and GST registration type in Tally."),
        ("Step 3 — verify ledgers", "Match the ledger names in the Ledger Masters sheet to your existing Tally ledgers. Tally creates new ledgers when the name differs; merge duplicates manually. Set each stock item's GST rate and HSN from the Stock Item Masters sheet — the XML import does not set GST rates."),
        ("Step 4 — import vouchers", "Gateway of Tally → Import Data → Vouchers. Choose tally-voucher-import.xml. Import period by period and reconcile the voucher count against the Summary sheet."),
        ("Step 5 — GST checks", "Open a sample sales and purchase voucher. Confirm the party GSTIN, place of supply and tax ledgers. Tally may ask you to set the party state before GST is applied."),
        ("Step 6 — reconcile", "Compare the Tally sales/purchase registers with the Summary sheet totals. Investigate any difference before posting to the books."),
        ("Step 7 — record the result", "Return to the Tally Integration page and set the import status (imported / partially imported / failed) with a note so the audit trail is complete."),
        ("CSV fallback", "If XML import is not suitable, use the per-type CSV files. They contain the same voucher and ledger detail and can be mapped with Tally's CSV import or a template."),
        ("No silent changes", f"This pack contains errors: {report['error_count']} and warnings: {report['warning_count']}. Amounts were not adjusted during export; resolve errors at source before importing."),
        ("No live connection", "FINOVEXA does not connect to, read from or post into a Tally installation. Import is a manual step performed by the accountant."),
    ]


def build_xlsx(data: ExportData, report: dict[str, Any], client: AccountingClient) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(color="FFFFFF", bold=True)
    title_font = Font(bold=True, size=13)

    def style_header(sheet, columns: list[str]) -> None:
        sheet.append(columns)
        for cell in sheet[sheet.max_row]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center")

    def autosize(sheet) -> None:
        for index, column in enumerate(sheet.columns, start=1):
            width = max((len(str(cell.value)) if cell.value is not None else 0) for cell in column)
            sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 12), 55)
        sheet.freeze_panes = "A2"

    instructions = workbook.active
    instructions.title = "Instructions"
    instructions["A1"] = "TallyPrime import instructions"
    instructions["A1"].font = title_font
    row = 3
    for label, text in _instructions(report, client):
        instructions.cell(row=row, column=1, value=label).font = Font(bold=True)
        instructions.cell(row=row, column=2, value=text).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    instructions.column_dimensions["A"].width = 30
    instructions.column_dimensions["B"].width = 110

    summary = workbook.create_sheet("Summary")
    summary["A1"] = "Export summary"
    summary["A1"].font = title_font
    summary.append([])
    style_header(summary, ["Item", "Value"])
    for label, value in _summary_pairs(data, report, client):
        summary.append([label, value])
    autosize(summary)

    for export_type in report["export_types"]:
        voucher_type = VOUCHER_TYPE_BY_EXPORT.get(export_type)
        if not voucher_type:
            continue
        sheet = workbook.create_sheet(VOUCHER_SHEET_NAMES[export_type])
        blocks = [b for b in data.blocks if b.voucher.voucher_type == voucher_type]
        style_header(sheet, VOUCHER_COLUMNS)
        for row_values in voucher_rows(blocks):
            sheet.append(row_values)
        autosize(sheet)

    entries = workbook.create_sheet("Voucher Entries")
    style_header(entries, ENTRY_COLUMNS)
    for row_values in entry_rows(data.blocks):
        entries.append(row_values)
    for row_cells in entries.iter_rows(min_row=2, min_col=8, max_col=9):
        for cell in row_cells:
            cell.number_format = "#,##0.00"
    autosize(entries)

    if "ledger_masters" in report["export_types"]:
        sheet = workbook.create_sheet("Ledger Masters")
        style_header(sheet, LEDGER_COLUMNS)
        for row_values in ledger_rows(data.ledgers):
            sheet.append(row_values)
        autosize(sheet)

    if "stock_masters" in report["export_types"]:
        sheet = workbook.create_sheet("Stock Item Masters")
        style_header(sheet, STOCK_COLUMNS)
        for row_values in stock_rows(data.stock_items):
            sheet.append(row_values)
        autosize(sheet)

    validation = workbook.create_sheet("Validation")
    style_header(validation, VALIDATION_COLUMNS)
    rows = validation_rows(report)
    if rows:
        for row_values in rows:
            validation.append(row_values)
    else:
        validation.append(["info", "NO_ISSUES", "", "", "", "No errors or warnings were found.", "", ""])
    autosize(validation)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _csv_text(columns: list[str], rows: list[list[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()


def build_csv_zip(data: ExportData, report: dict[str, Any], client: AccountingClient) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for export_type in report["export_types"]:
            voucher_type = VOUCHER_TYPE_BY_EXPORT.get(export_type)
            if not voucher_type:
                continue
            blocks = [b for b in data.blocks if b.voucher.voucher_type == voucher_type]
            archive.writestr(
                f"{export_type}-vouchers.csv",
                _csv_text(VOUCHER_COLUMNS, voucher_rows(blocks)),
            )
        archive.writestr("voucher-entries.csv", _csv_text(ENTRY_COLUMNS, entry_rows(data.blocks)))
        if "ledger_masters" in report["export_types"]:
            archive.writestr("ledger-masters.csv", _csv_text(LEDGER_COLUMNS, ledger_rows(data.ledgers)))
        if "stock_masters" in report["export_types"]:
            archive.writestr("stock-item-masters.csv", _csv_text(STOCK_COLUMNS, stock_rows(data.stock_items)))
        archive.writestr("validation-report.csv", _csv_text(VALIDATION_COLUMNS, validation_rows(report)))
        archive.writestr("tally-master-import.xml", master_xml(data, client))
        archive.writestr("tally-voucher-import.xml", voucher_xml(data, client))
        readme = ["TallyPrime import pack", ""]
        for label, text in _instructions(report, client):
            readme.append(f"{label}: {text}")
        archive.writestr("README.txt", "\n".join(readme) + "\n")
    return buffer.getvalue()


def _envelope_body(xml_text: str) -> str:
    start = xml_text.find("<REQUESTDATA>")
    end = xml_text.find("</REQUESTDATA>")
    if start == -1 or end == -1:
        return xml_text
    return xml_text[start + len("<REQUESTDATA>") : end]


def build_xml_export(data: ExportData, report: dict[str, Any], client: AccountingClient) -> bytes:
    """One Tally import envelope containing both masters and vouchers."""
    parts: list[str] = []
    if data.ledgers or data.stock_items:
        parts.append(_envelope_body(master_xml(data, client)))
    if data.blocks:
        parts.append(_envelope_body(voucher_xml(data, client)))
    report_name = "All Masters and Vouchers" if data.blocks else "All Masters"
    return _envelope(client.business_name, report_name, "".join(parts)).encode("utf-8")


def build_json_export(data: ExportData, report: dict[str, Any], client: AccountingClient) -> bytes:
    payload = {
        "company": client.business_name,
        "gstin": client.gstin,
        "generated_at": utcnow().isoformat(),
        "export_types": list(report["export_types"]),
        "currency": "INR",
        "source_note": "Exported from FINOVEXA. Amounts are decimal strings; import manually into Tally.",
        "masters": {
            "ledgers": [
                {
                    "name": master.name,
                    "group": master.group,
                    "gstin": master.gstin,
                    "registration": master.registration,
                    "opening": _money(master.opening),
                    "dr_cr": master.dr_cr,
                }
                for master in data.ledgers
            ],
            "stock_items": [
                {
                    "name": item.name,
                    "sku": item.sku,
                    "unit": item.unit,
                    "hsn_sac": item.hsn_sac,
                    "gst_rate": _money(Decimal(item.gst_rate or 0)),
                    "opening_qty": _money(Decimal(item.opening_qty or 0)),
                    "opening_rate": _money(Decimal(item.opening_rate or 0)),
                }
                for item in data.stock_items
            ],
        },
        "vouchers": [
            {
                "voucher_type": block.tally_type,
                "number": block.voucher.number,
                "date": block.voucher.voucher_date.isoformat(),
                "party_name": block.voucher.party_name,
                "party_gstin": block.voucher.party_gstin,
                "ledger_name": block.voucher.ledger_name,
                "bank_ledger": block.voucher.bank_ledger,
                "narration": block.voucher.description,
                "taxable_value": _money(Decimal(block.voucher.taxable_value or 0)),
                "gst_rate": _money(Decimal(block.voucher.gst_rate or 0)),
                "cgst": _money(Decimal(block.voucher.cgst_amount or 0)),
                "sgst": _money(Decimal(block.voucher.sgst_amount or 0)),
                "igst": _money(Decimal(block.voucher.igst_amount or 0)),
                "total": _money(Decimal(block.voucher.total_amount or 0)),
                "debit_total": _money(block.debit_total),
                "credit_total": _money(block.credit_total),
                "entries": [
                    {
                        "ledger_name": entry.ledger,
                        "ledger_group": entry.group,
                        "debit": _money(entry.debit),
                        "credit": _money(entry.credit),
                        "is_party": entry.is_party,
                        "is_tax": entry.is_tax,
                    }
                    for entry in block.entries
                ],
            }
            for block in data.blocks
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def build_export_file(
    data: ExportData,
    report: dict[str, Any],
    client: AccountingClient,
    file_format: str,
) -> tuple[bytes, str]:
    if file_format == "csv_zip":
        return build_csv_zip(data, report, client), "zip"
    if file_format == "xml":
        return build_xml_export(data, report, client), "xml"
    if file_format == "json":
        return build_json_export(data, report, client), "json"
    return build_xlsx(data, report, client), "xlsx"


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "client").lower()).strip("-")
    return cleaned[:40] or "client"


def export_filename(
    client: AccountingClient,
    from_date: date | None,
    to_date: date | None,
    file_format: str,
    batch_id: int | None = None,
) -> str:
    start = from_date.isoformat() if from_date else "opening"
    end = to_date.isoformat() if to_date else "latest"
    suffix = {"csv_zip": "zip", "xml": "xml", "json": "json"}.get(file_format, "xlsx")
    ident = f"-{batch_id}" if batch_id else ""
    return f"tally-export-{slugify(client.business_name)}-{start}-to-{end}{ident}.{suffix}"


# ---------------------------------------------------------------- catalog & serialisation


def export_catalog(db: Session, client: AccountingClient) -> dict[str, Any]:
    counts = {voucher_type: 0 for voucher_type in VOUCHER_TYPE_BY_EXPORT.values()}
    for voucher_type, count in (
        db.query(AccountingVoucher.voucher_type, func.count(AccountingVoucher.id))
        .filter(AccountingVoucher.client_id == client.id, AccountingVoucher.status == "posted")
        .group_by(AccountingVoucher.voucher_type)
        .all()
    ):
        counts[voucher_type] = int(count)
    stock_items = (
        db.query(AccountingStockItem)
        .filter(AccountingStockItem.client_id == client.id, AccountingStockItem.is_active.is_(True))
        .count()
    )
    return {
        "client_id": client.id,
        "client_name": client.business_name,
        "client_gstin": client.gstin,
        "types": [
            {
                "key": export_type,
                "label": TALLY_EXPORT_LABELS[export_type],
                "record_count": (
                    counts.get(VOUCHER_TYPE_BY_EXPORT[export_type], 0)
                    if export_type in VOUCHER_TYPE_BY_EXPORT
                    else (stock_items if export_type == "stock_masters" else None)
                ),
                "kind": "vouchers" if export_type in VOUCHER_TYPE_BY_EXPORT else "masters",
            }
            for export_type in TALLY_EXPORT_TYPES
        ],
        "stock_item_count": stock_items,
        "formats": [
            {"key": "xlsx", "label": "Excel workbook (.xlsx)"},
            {"key": "csv_zip", "label": "CSV bundle + Tally XML (.zip)"},
            {"key": "xml", "label": "Tally XML (.xml)"},
            {"key": "json", "label": "Structured JSON (.json, TallyPrime 3.0+)"},
        ],
        "tally_versions": [
            {"key": version, "formats": list(TALLY_VERSION_FORMATS[version])}
            for version in TALLY_VERSIONS
        ],
        "import_statuses": [
            {"key": "not_imported", "label": "Not imported"},
            {"key": "imported", "label": "Imported in Tally"},
            {"key": "partially_imported", "label": "Partially imported"},
            {"key": "failed", "label": "Import failed"},
        ],
        "note": (
            "Files are generated for manual import into TallyPrime. FINOVEXA does not connect to Tally."
        ),
    }


def stock_item_to_dict(item: AccountingStockItem) -> dict[str, Any]:
    opening_value = q2(Decimal(item.opening_qty or 0) * Decimal(item.opening_rate or 0))
    return {
        "id": item.id,
        "client_id": item.client_id,
        "name": item.name,
        "sku": item.sku,
        "unit": item.unit,
        "hsn_sac": item.hsn_sac,
        "gst_rate": item.gst_rate,
        "opening_qty": item.opening_qty,
        "opening_rate": item.opening_rate,
        "opening_value": opening_value,
        "is_active": item.is_active,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def prepare_export(
    db: Session,
    *,
    client: AccountingClient,
    export_types: list[str],
    from_date: date | None,
    to_date: date | None,
    file_format: str,
    prepared_by_id: int,
    tally_version: str = "TallyPrime 4.1",
) -> tuple[dict[str, Any], ExportData, Any]:
    """Validate, generate and store the file. Returns (report, data, stored_file)."""
    from ..models import AccountingTallyExport

    data = collect_export_data(db, client, export_types, from_date, to_date)
    report = validate_export(data, export_types, client, from_date, to_date)
    if not report["ok"]:
        return report, data, None

    raw, suffix = build_export_file(data, report, client, file_format)
    stored_name, sha256, size = save_document_file(db, raw, suffix)
    filename = export_filename(client, from_date, to_date, file_format)
    record = AccountingTallyExport(
        client_id=client.id,
        export_types=list(export_types),
        file_format=file_format,
        period_from=from_date,
        period_to=to_date,
        filename=filename,
        stored_name=stored_name,
        file_sha256=sha256,
        file_size=size,
        row_count=report["summary"]["voucher_count"] + report["summary"]["ledger_count"] + report["summary"]["stock_item_count"],
        voucher_count=report["summary"]["voucher_count"],
        master_count=report["summary"]["ledger_count"] + report["summary"]["stock_item_count"],
        error_count=report["error_count"],
        warning_count=report["warning_count"],
        status="pending_approval",
        prepared_by_user_id=prepared_by_id,
        validation=report,
        details={
            "entry_count": report["summary"]["entry_count"],
            "debit_total": report["summary"]["debit_total"],
            "credit_total": report["summary"]["credit_total"],
            "balanced": report["summary"]["balanced"],
            "by_type": report["summary"]["by_type"],
            "sha256": sha256,
            "file_size": size,
            "tally_version": tally_version,
            "note": report["note"],
        },
    )
    db.add(record)
    db.flush()
    record.filename = export_filename(client, from_date, to_date, file_format, record.id)
    db.flush()
    return report, data, record


def export_to_dict(
    record: Any,
    *,
    include_validation: bool = False,
    prepared_by: str | None = None,
    approved_by: str | None = None,
    client_name: str | None = None,
) -> dict[str, Any]:
    data = {
        "id": record.id,
        "client_id": record.client_id,
        "client_name": client_name,
        "export_types": record.export_types or [],
        "type_labels": [TALLY_EXPORT_LABELS.get(t, t) for t in (record.export_types or [])],
        "file_format": record.file_format,
        "tally_version": (record.details or {}).get("tally_version"),
        "period_from": record.period_from.isoformat() if record.period_from else None,
        "period_to": record.period_to.isoformat() if record.period_to else None,
        "filename": record.filename,
        "file_sha256": record.file_sha256,
        "file_size": record.file_size,
        "row_count": record.row_count,
        "voucher_count": record.voucher_count,
        "master_count": record.master_count,
        "error_count": record.error_count,
        "warning_count": record.warning_count,
        "status": record.status,
        "prepared_by_user_id": record.prepared_by_user_id,
        "prepared_by": prepared_by,
        "approved_by_user_id": record.approved_by_user_id,
        "approved_by": approved_by,
        "approved_at": record.approved_at.isoformat() if record.approved_at else None,
        "approval_note": record.approval_note,
        "import_status": record.import_status,
        "import_note": record.import_note,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "details": record.details or {},
        "download_url": f"/api/accounting/tally/exports/{record.id}/download"
        if record.status == "approved" and record.stored_name
        else None,
    }
    if include_validation:
        data["validation"] = record.validation or {}
    return data


def mime_for_format(file_format: str) -> str:
    return {
        "csv_zip": "application/zip",
        "xml": "application/xml",
        "json": "application/json",
    }.get(
        file_format,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


__all__ = [
    "VOUCHER_TYPE_BY_EXPORT",
    "TALLY_VOUCHER_TYPE",
    "build_block",
    "build_export_file",
    "build_json_export",
    "build_ledger_masters",
    "build_xml_export",
    "collect_export_data",
    "export_catalog",
    "export_filename",
    "export_to_dict",
    "master_xml",
    "mime_for_format",
    "prepare_export",
    "slugify",
    "stock_item_to_dict",
    "validate_export",
    "voucher_xml",
]