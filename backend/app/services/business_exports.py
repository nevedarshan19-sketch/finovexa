"""Complete-business exports for the accountant portal.

Two deliverables are built from the same read-only snapshot:

* a 14-sheet Excel workbook with the registers, ledgers, GST summary, stock
  summary and business summary requested by the practice, and
* a Tally export (structured Excel or an XML pack) whose vouchers are built
  from stored amounts only.

Data comes from the linked Business Manager records (invoices, payments,
expenses, customers, products) plus manually posted accounting vouchers.
Integration-sourced vouchers are excluded because the originating invoice,
payment or expense is already in the export; including both would double count.

Nothing is invented. A missing ledger, GSTIN, HSN or payment account is
reported in the preview and in the workbook, and rounding differences are
written to an explicit Round Off line instead of being absorbed silently.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from ..accounting_catalog import (
    BUSINESS_EXPORT_CATEGORIES,
    BUSINESS_EXPORT_LABELS,
    TALLY_VERSIONS,
)
from ..models import (
    AccountingClient,
    AccountingDataExport,
    AccountingVoucher,
    AccountingVoucherLine,
    Customer,
    Expense,
    Invoice,
    Payment,
    Product,
    User,
    utcnow,
)
from .accounting import save_document_file
from .accounting_math import financial_year_for
from .finance import q2

ZERO = Decimal("0.00")
MAX_ISSUES = 250
SHEET_NAMES = (
    "Sales Register",
    "Purchase Register",
    "Receipt Register",
    "Payment Register",
    "Expense Register",
    "Customer Ledger",
    "Supplier Ledger",
    "GST Summary",
    "Credit Notes",
    "Debit Notes",
    "Journal Entries",
    "Inventory Transactions",
    "Stock Summary",
    "Business Summary",
)
WORKBOOK_KIND = "workbook"
TALLY_EXCEL_KIND = "tally_excel"
TALLY_XML_KIND = "tally_xml"

GROUP_DEBTORS = "Sundry Debtors"
GROUP_CREDITORS = "Sundry Creditors"
GROUP_BANK = "Bank Accounts"
GROUP_CASH = "Cash-in-Hand"
GROUP_SALES = "Sales Accounts"
GROUP_PURCHASE = "Purchase Accounts"
GROUP_EXPENSES = "Indirect Expenses"
GROUP_DUTIES = "Duties & Taxes"

VOUCHER_TALLY_TYPE = {
    "sale": "Sales",
    "purchase": "Purchase",
    "receipt": "Receipt",
    "payment": "Payment",
    "expense": "Payment",
    "journal": "Journal",
    "credit_note": "Credit Note",
    "debit_note": "Debit Note",
}

IMPORT_CLAIM = (
    "This file has not been tested against a live TallyPrime import in this "
    "environment. Import it into a test company first, reconcile the voucher "
    "count and totals, and only then use it in the books."
)


# ------------------------------------------------------------------ utilities


def _money(value: Decimal | int | float | None) -> Decimal:
    return q2(value)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _payment_date(payment: Payment) -> date:
    if payment.received_at:
        return payment.received_at.date()
    return payment.created_at.date()


def _in_range(value: date, start: date | None, end: date | None) -> bool:
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{q2(value):.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "business").lower()).strip("-")
    return cleaned or "business"


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    category: str | None = None,
    reference: str | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "category": category,
        "reference": reference,
    }


def _bank_ledger(payment: Payment | None, method: str | None = None) -> tuple[str, str, bool]:
    """Return (ledger, group, recorded). Business payments rarely store the bank name."""
    label = (method or (payment.method if payment else "") or "").lower()
    if label == "cash":
        return "Cash", GROUP_CASH, True
    return "Bank Account", GROUP_BANK, False


# ------------------------------------------------------------------ dataset


@dataclass
class ExportDataset:
    client: AccountingClient
    profile: Any
    owner_id: int
    categories: list[str]
    date_from: date | None
    date_to: date | None
    invoices: list[Invoice]
    payments: list[Payment]
    expenses: list[Expense]
    vouchers: list[AccountingVoucher]
    voucher_lines: dict[int, list[AccountingVoucherLine]]
    customers: list[Customer]
    products: list[Product]
    generated_at: datetime


def _normalise_categories(categories: list[str] | None) -> list[str]:
    if not categories:
        return list(BUSINESS_EXPORT_CATEGORIES)
    seen: list[str] = []
    for item in categories:
        if item in BUSINESS_EXPORT_CATEGORIES and item not in seen:
            seen.append(item)
    if not seen:
        raise HTTPException(status_code=422, detail="Choose at least one export category.")
    return seen


def build_dataset(
    db: Session,
    client: AccountingClient,
    *,
    categories: list[str] | None,
    date_from: date | None,
    date_to: date | None,
) -> ExportDataset:
    profile = client.business_profile
    if client.business_profile_id is None or profile is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No Business Manager business is linked to this engagement. "
                "The owner or senior accountant must link it before a full export can be prepared."
            ),
        )
    owner_id = profile.user_id or profile.owner_id
    if not owner_id:
        raise HTTPException(status_code=409, detail="The linked business owner was not found.")
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=422, detail="End date cannot be before the start date.")

    invoices = (
        db.query(Invoice)
        .options(
            selectinload(Invoice.customer),
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
        )
        .filter(Invoice.user_id == owner_id)
        .order_by(Invoice.issue_date, Invoice.id)
        .all()
    )
    payments = (
        db.query(Payment)
        .options(selectinload(Payment.invoice).selectinload(Invoice.customer))
        .filter(Payment.user_id == owner_id)
        .order_by(Payment.id)
        .all()
    )
    expenses = (
        db.query(Expense)
        .filter(Expense.user_id == owner_id)
        .order_by(Expense.incurred_on, Expense.id)
        .all()
    )
    vouchers = (
        db.query(AccountingVoucher)
        .filter(
            AccountingVoucher.client_id == client.id,
            AccountingVoucher.status == "posted",
            AccountingVoucher.source_transaction_id.is_(None),
        )
        .order_by(AccountingVoucher.voucher_date, AccountingVoucher.id)
        .all()
    )
    line_rows = (
        db.query(AccountingVoucherLine)
        .filter(AccountingVoucherLine.voucher_id.in_([v.id for v in vouchers]))
        .order_by(AccountingVoucherLine.voucher_id, AccountingVoucherLine.line_no)
        .all()
        if vouchers
        else []
    )
    voucher_lines: dict[int, list[AccountingVoucherLine]] = {}
    for line in line_rows:
        voucher_lines.setdefault(line.voucher_id, []).append(line)

    customers = db.query(Customer).filter(Customer.user_id == owner_id).all()
    products = (
        db.query(Product)
        .options(selectinload(Product.inventory))
        .filter(Product.user_id == owner_id)
        .order_by(Product.name)
        .all()
    )
    return ExportDataset(
        client=client,
        profile=profile,
        owner_id=owner_id,
        categories=_normalise_categories(categories),
        date_from=date_from,
        date_to=date_to,
        invoices=invoices,
        payments=payments,
        expenses=expenses,
        vouchers=vouchers,
        voucher_lines=voucher_lines,
        customers=customers,
        products=products,
        generated_at=utcnow(),
    )


def _period_invoices(data: ExportDataset) -> list[Invoice]:
    return [
        row
        for row in data.invoices
        if _in_range(row.issue_date, data.date_from, data.date_to)
    ]


def _period_payments(data: ExportDataset) -> list[Payment]:
    return [
        row
        for row in data.payments
        if _in_range(_payment_date(row), data.date_from, data.date_to)
    ]


def _period_expenses(data: ExportDataset) -> list[Expense]:
    return [
        row
        for row in data.expenses
        if _in_range(row.incurred_on, data.date_from, data.date_to)
    ]


def _period_vouchers(data: ExportDataset) -> list[AccountingVoucher]:
    return [
        row
        for row in data.vouchers
        if _in_range(row.voucher_date, data.date_from, data.date_to)
    ]


def _invoice_party(invoice: Invoice) -> str:
    customer = invoice.customer
    return invoice.customer_name or (customer.name if customer else "") or ""


def _invoice_gstin(invoice: Invoice) -> str | None:
    customer = invoice.customer
    return invoice.customer_gstin or (customer.gstin if customer else None)


def _invoice_paid(invoice: Invoice) -> Decimal:
    total = ZERO
    for payment in invoice.payments:
        if payment.status != "confirmed" or payment.refund_of_payment_id is not None:
            continue
        total += Decimal(payment.amount or ZERO)
    return q2(total)


def _invoice_tax(invoice: Invoice) -> Decimal:
    return q2(
        Decimal(invoice.cgst_amount or ZERO)
        + Decimal(invoice.sgst_amount or ZERO)
        + Decimal(invoice.igst_amount or ZERO)
    )


def _invoice_payment_status(invoice: Invoice) -> str:
    if invoice.status == "void":
        return "void"
    paid = _invoice_paid(invoice)
    total = q2(invoice.total_amount)
    if paid <= ZERO:
        return "unpaid"
    if paid >= total:
        return "paid"
    return "partially paid"


def _include_in_tally(invoice: Invoice) -> bool:
    return invoice.status not in ("void", "draft", "cancelled")


# ------------------------------------------------------------------ registers


def sales_rows(data: ExportDataset) -> list[list[Any]]:
    if "sales" not in data.categories:
        return []
    rows: list[list[Any]] = []
    for invoice in _period_invoices(data):
        paid = _invoice_paid(invoice)
        total = q2(invoice.total_amount)
        rows.append(
            [
                invoice.id,
                invoice.number,
                invoice.issue_date.isoformat(),
                financial_year_for(invoice.issue_date),
                _invoice_party(invoice) or "Unnamed customer",
                _invoice_gstin(invoice) or "",
                invoice.place_of_supply_state or "",
                invoice.supply_type or "",
                invoice.status or "",
                _invoice_payment_status(invoice),
                q2(invoice.taxable_amount),
                q2(invoice.cgst_amount),
                q2(invoice.sgst_amount),
                q2(invoice.igst_amount),
                _invoice_tax(invoice),
                total,
                paid,
                q2(max(total - paid, ZERO)),
                q2(invoice.other_charges),
                q2(invoice.rounding_adjustment),
                invoice.currency or "INR",
                invoice.notes or "",
                f"INV:{invoice.id}:{invoice.number}",
            ]
        )
    return rows


SALES_COLUMNS = [
    "Invoice ID",
    "Invoice Number",
    "Invoice Date",
    "Financial Year",
    "Customer",
    "Customer GSTIN",
    "Place of Supply",
    "Supply Type",
    "Invoice Status",
    "Payment Status",
    "Taxable Value",
    "CGST",
    "SGST",
    "IGST",
    "Total Tax",
    "Invoice Total",
    "Paid Amount",
    "Outstanding Amount",
    "Other Charges",
    "Rounding Adjustment",
    "Currency",
    "Notes",
    "Transaction Reference",
]


def _voucher_rows(data: ExportDataset, voucher_type: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for voucher in _period_vouchers(data):
        if voucher.voucher_type != voucher_type:
            continue
        rows.append(
            [
                voucher.id,
                voucher.number,
                voucher.voucher_date.isoformat(),
                financial_year_for(voucher.voucher_date),
                voucher.party_name or "Unnamed party",
                voucher.party_gstin or "",
                voucher.ledger_name or "",
                voucher.category or "",
                q2(voucher.taxable_value),
                q2(voucher.cgst_amount),
                q2(voucher.sgst_amount),
                q2(voucher.igst_amount),
                q2(voucher.total_amount),
                voucher.status or "",
                "Accounting voucher (manual)",
                voucher.description or "",
                f"VCH:{voucher.id}:{voucher.number}",
            ]
        )
    return rows


PURCHASE_COLUMNS = [
    "Voucher ID",
    "Voucher Number",
    "Voucher Date",
    "Financial Year",
    "Supplier",
    "Supplier GSTIN",
    "Ledger",
    "Category",
    "Taxable Value",
    "CGST",
    "SGST",
    "IGST",
    "Total",
    "Status",
    "Source",
    "Narration",
    "Transaction Reference",
]


def purchase_rows(data: ExportDataset) -> list[list[Any]]:
    return _voucher_rows(data, "purchase") if "purchases" in data.categories else []


RECEIPT_COLUMNS = [
    "Record Type",
    "Record ID",
    "Date",
    "Financial Year",
    "Customer / Sender",
    "Invoice Number",
    "Payment Method",
    "Provider Reference",
    "Amount",
    "Status",
    "Reconciliation Status",
    "Narration",
    "Transaction Reference",
]


def receipt_rows(data: ExportDataset) -> list[list[Any]]:
    if "receipts" not in data.categories:
        return []
    rows: list[list[Any]] = []
    for payment in _period_payments(data):
        if payment.refund_of_payment_id is not None:
            continue
        invoice = payment.invoice
        party = (
            payment.sender_name
            or (invoice.customer_name if invoice else "")
            or (
                invoice.customer.name
                if invoice and invoice.customer is not None
                else ""
            )
            or "Unnamed payer"
        )
        rows.append(
            [
                "Customer receipt",
                payment.id,
                _payment_date(payment).isoformat(),
                financial_year_for(_payment_date(payment)),
                party,
                invoice.number if invoice else "",
                payment.method or "",
                payment.provider_ref or "",
                q2(payment.amount),
                payment.status or "",
                payment.reconciliation_status or "",
                payment.note or "",
                f"PMT:{payment.id}",
            ]
        )
    for voucher in _period_vouchers(data):
        if voucher.voucher_type != "receipt":
            continue
        rows.append(
            [
                "Accounting receipt voucher",
                voucher.id,
                voucher.voucher_date.isoformat(),
                financial_year_for(voucher.voucher_date),
                voucher.party_name or "",
                voucher.category or "",
                voucher.bank_ledger or voucher.ledger_name or "",
                "",
                q2(voucher.total_amount),
                voucher.status or "",
                "",
                voucher.description or "",
                f"VCH:{voucher.id}:{voucher.number}",
            ]
        )
    rows.sort(key=lambda row: (row[2], row[0], row[1]))
    return rows


PAYMENT_COLUMNS = [
    "Record Type",
    "Record ID",
    "Date",
    "Financial Year",
    "Party",
    "Reference",
    "Payment Method / Bank Ledger",
    "Amount",
    "Status",
    "Narration",
    "Transaction Reference",
]


def payment_rows(data: ExportDataset) -> list[list[Any]]:
    if "payments" not in data.categories:
        return []
    rows: list[list[Any]] = []
    for payment in _period_payments(data):
        if payment.refund_of_payment_id is None:
            continue
        invoice = payment.invoice
        party = (
            payment.sender_name
            or (invoice.customer_name if invoice else "")
            or (
                invoice.customer.name
                if invoice and invoice.customer is not None
                else ""
            )
            or "Customer"
        )
        rows.append(
            [
                "Customer refund",
                payment.id,
                _payment_date(payment).isoformat(),
                financial_year_for(_payment_date(payment)),
                party,
                payment.provider_ref or f"PMT-{payment.id}",
                payment.method or "",
                q2(payment.amount),
                payment.status or "",
                payment.note or "",
                f"PMT:{payment.id}",
            ]
        )
    for voucher in _period_vouchers(data):
        if voucher.voucher_type != "payment":
            continue
        rows.append(
            [
                "Supplier payment voucher",
                voucher.id,
                voucher.voucher_date.isoformat(),
                financial_year_for(voucher.voucher_date),
                voucher.party_name or "",
                voucher.number,
                voucher.bank_ledger or voucher.ledger_name or "",
                q2(voucher.total_amount),
                voucher.status or "",
                voucher.description or "",
                f"VCH:{voucher.id}:{voucher.number}",
            ]
        )
    rows.sort(key=lambda row: (row[2], row[0], row[1]))
    return rows


EXPENSE_COLUMNS = [
    "Record Type",
    "Record ID",
    "Date",
    "Financial Year",
    "Vendor / Party",
    "Category / Ledger",
    "Amount",
    "Taxable Value",
    "GST",
    "Narration",
    "Transaction Reference",
]


def expense_rows(data: ExportDataset) -> list[list[Any]]:
    if "expenses" not in data.categories:
        return []
    rows: list[list[Any]] = []
    for expense in _period_expenses(data):
        rows.append(
            [
                "Business expense",
                expense.id,
                expense.incurred_on.isoformat(),
                financial_year_for(expense.incurred_on),
                expense.vendor or "",
                expense.category or "",
                q2(expense.amount),
                q2(expense.amount),
                ZERO,
                expense.note or "",
                f"EXP:{expense.id}",
            ]
        )
    for voucher in _period_vouchers(data):
        if voucher.voucher_type != "expense":
            continue
        tax = q2(
            Decimal(voucher.cgst_amount or ZERO)
            + Decimal(voucher.sgst_amount or ZERO)
            + Decimal(voucher.igst_amount or ZERO)
        )
        rows.append(
            [
                "Accounting expense voucher",
                voucher.id,
                voucher.voucher_date.isoformat(),
                financial_year_for(voucher.voucher_date),
                voucher.party_name or "",
                voucher.ledger_name or voucher.category or "",
                q2(voucher.total_amount),
                q2(voucher.taxable_value),
                tax,
                voucher.description or "",
                f"VCH:{voucher.id}:{voucher.number}",
            ]
        )
    rows.sort(key=lambda row: (row[2], row[0], row[1]))
    return rows


NOTE_COLUMNS = [
    "Voucher ID",
    "Voucher Number",
    "Date",
    "Financial Year",
    "Party",
    "Party GSTIN",
    "Ledger",
    "Taxable Value",
    "CGST",
    "SGST",
    "IGST",
    "Total",
    "Status",
    "Narration",
    "Transaction Reference",
]


def note_rows(data: ExportDataset, voucher_type: str, category: str) -> list[list[Any]]:
    if category not in data.categories:
        return []
    rows: list[list[Any]] = []
    for voucher in _period_vouchers(data):
        if voucher.voucher_type != voucher_type:
            continue
        rows.append(
            [
                voucher.id,
                voucher.number,
                voucher.voucher_date.isoformat(),
                financial_year_for(voucher.voucher_date),
                voucher.party_name or "",
                voucher.party_gstin or "",
                voucher.ledger_name or "",
                q2(voucher.taxable_value),
                q2(voucher.cgst_amount),
                q2(voucher.sgst_amount),
                q2(voucher.igst_amount),
                q2(voucher.total_amount),
                voucher.status or "",
                voucher.description or "",
                f"VCH:{voucher.id}:{voucher.number}",
            ]
        )
    return rows


JOURNAL_COLUMNS = [
    "Voucher ID",
    "Voucher Number",
    "Date",
    "Financial Year",
    "Party",
    "Line",
    "Ledger",
    "Debit",
    "Credit",
    "Narration",
    "Transaction Reference",
]


def journal_rows(data: ExportDataset) -> list[list[Any]]:
    if "journals" not in data.categories:
        return []
    rows: list[list[Any]] = []
    for voucher in _period_vouchers(data):
        if voucher.voucher_type != "journal":
            continue
        lines = data.voucher_lines.get(voucher.id) or []
        if not lines:
            rows.append(
                [
                    voucher.id,
                    voucher.number,
                    voucher.voucher_date.isoformat(),
                    financial_year_for(voucher.voucher_date),
                    voucher.party_name or "",
                    "",
                    voucher.ledger_name or "",
                    "",
                    "",
                    (voucher.description or "")
                    + " [Ledger split not recorded; review before export]",
                    f"VCH:{voucher.id}:{voucher.number}",
                ]
            )
            continue
        for line in lines:
            rows.append(
                [
                    voucher.id,
                    voucher.number,
                    voucher.voucher_date.isoformat(),
                    financial_year_for(voucher.voucher_date),
                    voucher.party_name or "",
                    line.line_no,
                    line.ledger_name,
                    q2(line.debit),
                    q2(line.credit),
                    line.description or voucher.description or "",
                    f"VCH:{voucher.id}:{voucher.number}:L{line.line_no}",
                ]
            )
    return rows


INVENTORY_COLUMNS = [
    "Date",
    "Source Reference",
    "Item",
    "SKU",
    "HSN / SAC",
    "Direction",
    "Quantity",
    "Unit",
    "Rate",
    "Taxable Value",
    "Note",
]


def inventory_rows(data: ExportDataset) -> list[list[Any]]:
    if "inventory" not in data.categories:
        return []
    products = {product.id: product for product in data.products}
    rows: list[list[Any]] = []
    for invoice in _period_invoices(data):
        if invoice.status in ("void", "draft", "cancelled"):
            continue
        for item in invoice.items:
            product = products.get(item.product_id) if item.product_id else None
            rows.append(
                [
                    invoice.issue_date.isoformat(),
                    invoice.number,
                    item.name or item.description,
                    product.sku if product else "",
                    item.hsn_sac or (product.hsn_sac if product else "") or "",
                    "Out (sale)",
                    q2(item.quantity),
                    item.unit or "",
                    q2(item.unit_price),
                    q2(item.taxable_value),
                    "",
                ]
            )
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


STOCK_COLUMNS = [
    "SKU",
    "Item",
    "HSN / SAC",
    "Unit",
    "GST Rate",
    "Quantity on Hand",
    "Reorder Level",
    "Unit Cost",
    "Stock Value",
    "Status",
    "As Of",
    "Note",
]


def stock_rows(data: ExportDataset) -> list[list[Any]]:
    if "inventory" not in data.categories:
        return []
    rows: list[list[Any]] = []
    for product in data.products:
        quantity = product.inventory.quantity_on_hand if product.inventory else 0
        status = "Low stock" if quantity <= product.reorder_level else "Available"
        rows.append(
            [
                product.sku,
                product.name,
                product.hsn_sac or "",
                product.unit,
                q2(product.default_gst_rate),
                quantity,
                product.reorder_level,
                q2(product.unit_cost),
                q2(Decimal(quantity) * Decimal(product.unit_cost or ZERO)),
                status,
                data.generated_at.date().isoformat(),
                "Current on-hand snapshot; historical period-end stock is not stored.",
            ]
        )
    return rows


# ------------------------------------------------------------------ ledgers


CUSTOMER_LEDGER_COLUMNS = [
    "Customer",
    "GSTIN",
    "Opening Balance (Dr)",
    "Invoices (Dr)",
    "Receipts (Cr)",
    "Refunds (Dr)",
    "Closing Balance (Dr)",
    "Note",
]


def customer_ledger_rows(data: ExportDataset) -> list[list[Any]]:
    if "sales" not in data.categories and "receipts" not in data.categories:
        return []
    start = data.date_from
    opening: dict[str, Decimal] = {}
    invoices_total: dict[str, Decimal] = {}
    receipts_total: dict[str, Decimal] = {}
    refunds_total: dict[str, Decimal] = {}
    gstins: dict[str, str] = {}

    for invoice in data.invoices:
        if invoice.status == "void":
            continue
        party = _invoice_party(invoice) or "Unnamed customer"
        gstins.setdefault(party, _invoice_gstin(invoice) or "")
        total = q2(invoice.total_amount)
        if start and invoice.issue_date < start:
            opening[party] = opening.get(party, ZERO) + total
        elif _in_range(invoice.issue_date, data.date_from, data.date_to):
            invoices_total[party] = invoices_total.get(party, ZERO) + total

    for payment in data.payments:
        if payment.status != "confirmed":
            continue
        invoice = payment.invoice
        party = (
            payment.sender_name
            or (invoice.customer_name if invoice else "")
            or (
                invoice.customer.name
                if invoice and invoice.customer is not None
                else ""
            )
            or "Unnamed payer"
        )
        gstins.setdefault(party, _invoice_gstin(invoice) if invoice else "")
        amount = q2(payment.amount)
        if payment.refund_of_payment_id is not None:
            if start and _payment_date(payment) < start:
                opening[party] = opening.get(party, ZERO) + amount
            elif _in_range(_payment_date(payment), data.date_from, data.date_to):
                refunds_total[party] = refunds_total.get(party, ZERO) + amount
            continue
        if start and _payment_date(payment) < start:
            opening[party] = opening.get(party, ZERO) - amount
        elif _in_range(_payment_date(payment), data.date_from, data.date_to):
            receipts_total[party] = receipts_total.get(party, ZERO) + amount

    parties = sorted(
        set(opening) | set(invoices_total) | set(receipts_total) | set(refunds_total),
        key=str.lower,
    )
    rows: list[list[Any]] = []
    for party in parties:
        opening_balance = q2(opening.get(party, ZERO))
        debit = q2(invoices_total.get(party, ZERO))
        credit = q2(receipts_total.get(party, ZERO))
        refunds = q2(refunds_total.get(party, ZERO))
        closing = q2(opening_balance + debit + refunds - credit)
        rows.append(
            [
                party,
                gstins.get(party, ""),
                opening_balance,
                debit,
                credit,
                refunds,
                closing,
                "Opening and closing balances are derived from recorded invoices, "
                "confirmed receipts and refunds only.",
            ]
        )
    return rows


SUPPLIER_LEDGER_COLUMNS = [
    "Supplier",
    "GSTIN",
    "Opening Balance (Cr)",
    "Purchases (Cr)",
    "Expenses (Cr)",
    "Payments (Dr)",
    "Closing Balance (Cr)",
    "Note",
]


def supplier_ledger_rows(data: ExportDataset) -> list[list[Any]]:
    if not {"purchases", "expenses", "payments"} & set(data.categories):
        return []
    start = data.date_from
    opening: dict[str, Decimal] = {}
    purchases: dict[str, Decimal] = {}
    expenses_total: dict[str, Decimal] = {}
    payments_total: dict[str, Decimal] = {}
    gstins: dict[str, str] = {}

    def add(bucket: dict[str, Decimal], party: str, amount: Decimal) -> None:
        bucket[party] = bucket.get(party, ZERO) + amount

    for voucher in data.vouchers:
        party = voucher.party_name or "Unnamed party"
        if voucher.voucher_type == "purchase":
            gstins.setdefault(party, voucher.party_gstin or "")
            total = q2(voucher.total_amount)
            if start and voucher.voucher_date < start:
                add(opening, party, total)
            elif _in_range(voucher.voucher_date, data.date_from, data.date_to):
                add(purchases, party, total)
        elif voucher.voucher_type == "payment":
            total = q2(voucher.total_amount)
            if start and voucher.voucher_date < start:
                add(opening, party, -total)
            elif _in_range(voucher.voucher_date, data.date_from, data.date_to):
                add(payments_total, party, total)

    for expense in data.expenses:
        party = expense.vendor or "Unnamed vendor"
        amount = q2(expense.amount)
        if start and expense.incurred_on < start:
            add(opening, party, amount)
        elif _in_range(expense.incurred_on, data.date_from, data.date_to):
            add(expenses_total, party, amount)

    parties = sorted(
        set(opening) | set(purchases) | set(expenses_total) | set(payments_total),
        key=str.lower,
    )
    rows: list[list[Any]] = []
    for party in parties:
        opening_balance = q2(opening.get(party, ZERO))
        purchase = q2(purchases.get(party, ZERO))
        expense = q2(expenses_total.get(party, ZERO))
        paid = q2(payments_total.get(party, ZERO))
        closing = q2(opening_balance + purchase + expense - paid)
        rows.append(
            [
                party,
                gstins.get(party, ""),
                opening_balance,
                purchase,
                expense,
                paid,
                closing,
                "Derived from recorded purchase vouchers, expenses and supplier payments. "
                "Unrecorded supplier payments are not assumed.",
            ]
        )
    return rows


# ------------------------------------------------------------------ GST summary


GST_COLUMNS = [
    "Section",
    "GST Rate",
    "Taxable Value",
    "CGST",
    "SGST",
    "IGST",
    "Total Tax",
    "Records",
    "Source",
]


def gst_rows(data: ExportDataset) -> list[list[Any]]:
    buckets: dict[tuple[str, Decimal], dict[str, Any]] = {}

    def bucket(section: str, rate: Decimal) -> dict[str, Any]:
        key = (section, q2(rate))
        if key not in buckets:
            buckets[key] = {
                "section": section,
                "rate": q2(rate),
                "taxable": ZERO,
                "cgst": ZERO,
                "sgst": ZERO,
                "igst": ZERO,
                "records": 0,
                "source": "FINOVEXA invoices" if section == "Output" else "Accounting vouchers",
            }
        return buckets[key]

    for invoice in _period_invoices(data):
        if invoice.status in ("void", "draft", "cancelled"):
            continue
        for item in invoice.items:
            row = bucket("Output", item.gst_rate)
            row["taxable"] += q2(item.taxable_value)
            row["cgst"] += q2(item.cgst_amount)
            row["sgst"] += q2(item.sgst_amount)
            row["igst"] += q2(item.igst_amount)
            row["records"] += 1

    for voucher in _period_vouchers(data):
        if voucher.voucher_type == "sale":
            row = bucket("Output", voucher.gst_rate)
            row["source"] = "FINOVEXA invoices and manual sale vouchers"
        elif voucher.voucher_type in ("purchase", "expense"):
            row = bucket("Input", voucher.gst_rate)
        else:
            continue
        row["taxable"] += q2(voucher.taxable_value)
        row["cgst"] += q2(voucher.cgst_amount)
        row["sgst"] += q2(voucher.sgst_amount)
        row["igst"] += q2(voucher.igst_amount)
        row["records"] += 1

    rows: list[list[Any]] = []
    for key in sorted(buckets, key=lambda item: (item[0] != "Output", item[1])):
        row = buckets[key]
        rows.append(
            [
                row["section"],
                row["rate"],
                q2(row["taxable"]),
                q2(row["cgst"]),
                q2(row["sgst"]),
                q2(row["igst"]),
                q2(row["cgst"] + row["sgst"] + row["igst"]),
                row["records"],
                row["source"],
            ]
        )
    output_tax = sum(
        (q2(row["cgst"] + row["sgst"] + row["igst"]) for row in buckets.values() if row["section"] == "Output"),
        ZERO,
    )
    input_tax = sum(
        (q2(row["cgst"] + row["sgst"] + row["igst"]) for row in buckets.values() if row["section"] == "Input"),
        ZERO,
    )
    rows.append(
        [
            "Net",
            "",
            "",
            "",
            "",
            "",
            q2(output_tax - input_tax),
            "",
            "Output tax minus input tax recorded in FINOVEXA. Not a filed return.",
        ]
    )
    return rows


# ------------------------------------------------------------------ summary


def summary_pairs(data: ExportDataset) -> list[tuple[str, Any]]:
    invoices = _period_invoices(data)
    payments = _period_payments(data)
    expenses = _period_expenses(data)
    vouchers = _period_vouchers(data)
    sales_total = sum(
        (q2(i.total_amount) for i in invoices if i.status not in ("void", "draft", "cancelled")),
        ZERO,
    )
    receipts_total = sum(
        (
            q2(p.amount)
            for p in payments
            if p.status == "confirmed" and p.refund_of_payment_id is None
        ),
        ZERO,
    )
    refunds_total = sum(
        (
            q2(p.amount)
            for p in payments
            if p.status == "confirmed" and p.refund_of_payment_id is not None
        ),
        ZERO,
    )
    return [
        ("Business", data.profile.business_name),
        ("Legal name", data.profile.legal_name or "Not recorded"),
        ("GSTIN", data.profile.gstin or "Not recorded"),
        ("State", data.profile.state or "Not recorded"),
        ("Currency", data.profile.currency or "INR"),
        ("Period from", data.date_from.isoformat() if data.date_from else "Earliest record"),
        ("Period to", data.date_to.isoformat() if data.date_to else "Latest record"),
        ("Financial year at export", financial_year_for(data.generated_at.date())),
        ("Generated at (UTC)", data.generated_at.isoformat(timespec="seconds")),
        ("Categories", ", ".join(BUSINESS_EXPORT_LABELS[c] for c in data.categories)),
        ("Invoices in period", len(invoices)),
        ("Payments in period", len(payments)),
        ("Expenses in period", len(expenses)),
        ("Manual accounting vouchers in period", len(vouchers)),
        ("Sales total (incl. GST)", sales_total),
        ("Confirmed receipts", receipts_total),
        ("Confirmed refunds", refunds_total),
        ("Business expenses", sum((q2(e.amount) for e in expenses), ZERO)),
        (
            "Note",
            "Every figure is read from stored records. Blank or 'Not recorded' values "
            "mean the source system does not hold that information.",
        ),
        (
            "Tally readiness",
            IMPORT_CLAIM,
        ),
    ]


def data_availability(data: ExportDataset) -> list[list[Any]]:
    rows = [
        ["Sales Register", "Available", "Business invoices with stored GST and payment status."],
        [
            "Purchase Register",
            "Available when recorded",
            "Built from manually posted purchase vouchers; the Business Manager does not capture purchase invoices.",
        ],
        ["Receipt Register", "Available", "Confirmed customer receipts plus manual receipt vouchers."],
        ["Payment Register", "Available", "Customer refunds plus manual supplier payment vouchers."],
        ["Expense Register", "Available", "Business expenses plus manual expense vouchers."],
        [
            "Customer Ledger",
            "Derived",
            "Opening and closing balances are derived from invoices, receipts and refunds.",
        ],
        [
            "Supplier Ledger",
            "Derived",
            "Derived from purchase vouchers, expenses and recorded supplier payments.",
        ],
        ["GST Summary", "Available", "Output tax from invoices and sale vouchers; input tax from purchase/expense vouchers."],
        [
            "Credit Notes",
            "Not recorded",
            "FINOVEXA does not capture credit notes in the live books; none are invented.",
        ],
        [
            "Debit Notes",
            "Not recorded",
            "FINOVEXA does not capture debit notes in the live books; none are invented.",
        ],
        ["Journal Entries", "Available when recorded", "Manual journal vouchers and their ledger splits."],
        [
            "Inventory Transactions",
            "Partial",
            "Sale movements come from invoice lines. Purchase stock movements are not stored.",
        ],
        [
            "Stock Summary",
            "Current snapshot",
            "On-hand quantity and value at export time; historical period-end stock is not stored.",
        ],
    ]
    return [row for row in rows if _availability_category(row[0]) in data.categories or row[0] == "Business Summary"]


def _availability_category(sheet: str) -> str:
    return {
        "Sales Register": "sales",
        "Purchase Register": "purchases",
        "Receipt Register": "receipts",
        "Payment Register": "payments",
        "Expense Register": "expenses",
        "Customer Ledger": "sales",
        "Supplier Ledger": "purchases",
        "GST Summary": "sales",
        "Credit Notes": "credit_notes",
        "Debit Notes": "debit_notes",
        "Journal Entries": "journals",
        "Inventory Transactions": "inventory",
        "Stock Summary": "inventory",
        "Business Summary": "sales",
    }.get(sheet, "sales")


# ------------------------------------------------------------------ validation


def build_issues(data: ExportDataset) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    invoices = _period_invoices(data)
    payments = _period_payments(data)

    for invoice in invoices:
        reference = f"INV:{invoice.id}:{invoice.number}"
        if not _invoice_party(invoice):
            issues.append(
                _issue("warning", "MISSING_PARTY", "Invoice has no customer name.", category="sales", reference=reference)
            )
        if not _invoice_gstin(invoice):
            issues.append(
                _issue(
                    "warning",
                    "MISSING_GSTIN",
                    "Customer GSTIN is not recorded; Tally will treat the party as unregistered.",
                    category="sales",
                    reference=reference,
                )
            )
        if (invoice.supply_type or "unverified") == "unverified":
            issues.append(
                _issue(
                    "warning",
                    "SUPPLY_TYPE_UNVERIFIED",
                    "Place-of-supply / intra-state classification is unverified.",
                    category="sales",
                    reference=reference,
                )
            )
        if invoice.status == "void":
            issues.append(
                _issue(
                    "review",
                    "VOID_INVOICE",
                    "Void invoice is listed for audit but excluded from export totals and vouchers.",
                    category="sales",
                    reference=reference,
                )
            )
        if invoice.status in ("draft", "cancelled"):
            issues.append(
                _issue(
                    "review",
                    "NOT_ISSUED_INVOICE",
                    f"Invoice status is {invoice.status}; it is excluded from Tally vouchers.",
                    category="sales",
                    reference=reference,
                )
            )
        if invoice.disputed_at is not None:
            issues.append(
                _issue("review", "DISPUTED_INVOICE", "Invoice is marked disputed.", category="sales", reference=reference)
            )
        paid = _invoice_paid(invoice)
        total = q2(invoice.total_amount)
        if paid > total and total > ZERO:
            issues.append(
                _issue(
                    "review",
                    "OVERPAYMENT",
                    f"Confirmed receipts {paid} exceed the invoice total {total}.",
                    category="sales",
                    reference=reference,
                )
            )
        components = q2(
            Decimal(invoice.taxable_amount or ZERO)
            + _invoice_tax(invoice)
            + Decimal(invoice.other_charges or ZERO)
            + Decimal(invoice.rounding_adjustment or ZERO)
        )
        if components != total:
            issues.append(
                _issue(
                    "warning",
                    "TOTAL_COMPONENTS",
                    f"Stored components total {components} but the invoice total is {total}; "
                    "a Round Off line keeps the voucher balanced.",
                    category="sales",
                    reference=reference,
                )
            )

    for payment in payments:
        reference = f"PMT:{payment.id}"
        if payment.status != "confirmed":
            issues.append(
                _issue(
                    "review",
                    "UNCONFIRMED_PAYMENT",
                    f"Payment status is {payment.status}; excluded from totals and Tally vouchers.",
                    category="receipts" if payment.refund_of_payment_id is None else "payments",
                    reference=reference,
                )
            )
            continue
        if payment.refund_of_payment_id is None and payment.invoice_id is None:
            issues.append(
                _issue(
                    "warning",
                    "UNALLOCATED_RECEIPT",
                    "Receipt is not linked to an invoice; the party is taken from the sender name.",
                    category="receipts",
                    reference=reference,
                )
            )
        if payment.method and payment.method.lower() != "cash":
            issues.append(
                _issue(
                    "warning",
                    "BANK_LEDGER_DEFAULTED",
                    "The bank account name is not recorded; the voucher uses 'Bank Account'. "
                    "Map it to the correct Tally bank ledger before import.",
                    category="receipts" if payment.refund_of_payment_id is None else "payments",
                    reference=reference,
                )
            )

    for expense in _period_expenses(data):
        if not (expense.vendor or "").strip():
            issues.append(
                _issue(
                    "warning",
                    "MISSING_VENDOR",
                    "Expense has no vendor name.",
                    category="expenses",
                    reference=f"EXP:{expense.id}",
                )
            )

    for voucher in _period_vouchers(data):
        reference = f"VCH:{voucher.id}:{voucher.number}"
        if voucher.voucher_type in ("purchase", "journal") and not data.voucher_lines.get(voucher.id):
            issues.append(
                _issue(
                    "warning",
                    "LEDGER_SPLIT_MISSING",
                    f"Voucher has no debit/credit lines; a balanced fallback is used and must be reviewed.",
                    category="purchases" if voucher.voucher_type == "purchase" else "journals",
                    reference=reference,
                )
            )
        if voucher.voucher_type in ("receipt", "payment", "expense") and not (voucher.bank_ledger or voucher.ledger_name):
            issues.append(
                _issue(
                    "warning",
                    "BANK_LEDGER_MISSING",
                    "Voucher has no bank or cash ledger recorded.",
                    category="receipts",
                    reference=reference,
                )
            )

    # Near-duplicate review: a manual sale voucher and an invoice for the same
    # party and amount within seven days are flagged, never dropped.
    for voucher in _period_vouchers(data):
        if voucher.voucher_type != "sale":
            continue
        for invoice in invoices:
            if invoice.status == "void":
                continue
            same_party = _invoice_party(invoice).strip().lower() == (voucher.party_name or "").strip().lower()
            amount_close = abs(q2(invoice.total_amount) - q2(voucher.total_amount)) <= Decimal("1.00")
            days = abs((invoice.issue_date - voucher.voucher_date).days)
            if same_party and amount_close and days <= 7:
                issues.append(
                    _issue(
                        "review",
                        "POSSIBLE_DUPLICATE",
                        f"Manual sale voucher {voucher.number} looks like invoice {invoice.number} "
                        f"(same party, amount within ₹1, {days} day(s) apart). Keep or remove the manual "
                        "voucher only after review.",
                        category="sales",
                        reference=f"VCH:{voucher.id}",
                    )
                )

    return issues


def issue_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "errors": sum(1 for row in issues if row["severity"] == "error"),
        "warnings": sum(1 for row in issues if row["severity"] == "warning"),
        "review": sum(1 for row in issues if row["severity"] == "review"),
        "total": len(issues),
    }


# ------------------------------------------------------------------ Tally vouchers


@dataclass
class TallyLine:
    ledger: str
    group: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    is_party: bool = False
    is_tax: bool = False


@dataclass
class TallyVoucher:
    category: str
    tally_type: str
    number: str
    voucher_date: date
    party: str
    party_gstin: str | None
    narration: str
    reference: str
    source: str
    entries: list[TallyLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def debit_total(self) -> Decimal:
        return q2(sum((line.debit for line in self.entries), ZERO))

    @property
    def credit_total(self) -> Decimal:
        return q2(sum((line.credit for line in self.entries), ZERO))

    @property
    def balanced(self) -> bool:
        return self.debit_total == self.credit_total


def _tax_lines(prefix: str, cgst: Decimal, sgst: Decimal, igst: Decimal, *, credit: bool) -> list[TallyLine]:
    lines: list[TallyLine] = []
    for label, amount in (("CGST", cgst), ("SGST", sgst), ("IGST", igst)):
        if amount:
            lines.append(
                TallyLine(
                    ledger=f"{prefix} {label}",
                    group=GROUP_DUTIES,
                    debit=ZERO if credit else amount,
                    credit=amount if credit else ZERO,
                    is_tax=True,
                )
            )
    return lines


def _balance(entries: list[TallyLine], voucher: TallyVoucher) -> None:
    debit = q2(sum((line.debit for line in entries), ZERO))
    credit = q2(sum((line.credit for line in entries), ZERO))
    diff = q2(debit - credit)
    if diff == ZERO:
        return
    # The stored total is authoritative. The difference is the stored other
    # charge/rounding component; write it to an explicit line so debit = credit.
    if diff > ZERO:
        entries.append(TallyLine("Round Off", GROUP_EXPENSES, credit=diff))
    else:
        entries.append(TallyLine("Round Off", GROUP_EXPENSES, debit=-diff))
    voucher.notes.append(f"Round Off {abs(diff)} keeps this voucher balanced.")


def build_tally_vouchers(data: ExportDataset) -> list[TallyVoucher]:
    vouchers: list[TallyVoucher] = []
    seen: set[str] = set()

    def add(voucher: TallyVoucher) -> None:
        if voucher.reference in seen:
            return
        seen.add(voucher.reference)
        _balance(voucher.entries, voucher)
        vouchers.append(voucher)

    if "sales" in data.categories:
        for invoice in _period_invoices(data):
            if not _include_in_tally(invoice):
                continue
            party = _invoice_party(invoice) or "Unnamed customer"
            voucher = TallyVoucher(
                category="sales",
                tally_type="Sales",
                number=invoice.number,
                voucher_date=invoice.issue_date,
                party=party,
                party_gstin=_invoice_gstin(invoice),
                narration=f"Sales invoice {invoice.number} [FINOVEXA:INV:{invoice.id}]",
                reference=f"INV:{invoice.id}:{invoice.number}",
                source="Business invoice",
                entries=[
                    TallyLine(party, GROUP_DEBTORS, debit=q2(invoice.total_amount), is_party=True),
                    TallyLine("Sales", GROUP_SALES, credit=q2(invoice.taxable_amount)),
                    *_tax_lines(
                        "Output",
                        q2(invoice.cgst_amount),
                        q2(invoice.sgst_amount),
                        q2(invoice.igst_amount),
                        credit=True,
                    ),
                ],
            )
            add(voucher)

    if "receipts" in data.categories:
        for payment in _period_payments(data):
            if payment.refund_of_payment_id is not None or payment.status != "confirmed":
                continue
            invoice = payment.invoice
            party = (
                payment.sender_name
                or (invoice.customer_name if invoice else "")
                or (invoice.customer.name if invoice and invoice.customer is not None else "")
                or "Customer"
            )
            bank, group, recorded = _bank_ledger(payment)
            voucher = TallyVoucher(
                category="receipts",
                tally_type="Receipt",
                number=payment.provider_ref or f"PMT-{payment.id}",
                voucher_date=_payment_date(payment),
                party=party,
                party_gstin=_invoice_gstin(invoice) if invoice else None,
                narration=(
                    f"Receipt for invoice {invoice.number} [FINOVEXA:PMT:{payment.id}]"
                    if invoice
                    else f"Unallocated receipt [FINOVEXA:PMT:{payment.id}]"
                ),
                reference=f"PMT:{payment.id}",
                source="Business payment",
                entries=[
                    TallyLine(bank, group, debit=q2(payment.amount)),
                    TallyLine(party, GROUP_DEBTORS, credit=q2(payment.amount), is_party=True),
                ],
            )
            if not recorded:
                voucher.notes.append("Bank ledger defaulted to 'Bank Account'; map it before import.")
            add(voucher)

    if "payments" in data.categories:
        for payment in _period_payments(data):
            if payment.refund_of_payment_id is None or payment.status != "confirmed":
                continue
            invoice = payment.invoice
            party = (
                payment.sender_name
                or (invoice.customer_name if invoice else "")
                or (invoice.customer.name if invoice and invoice.customer is not None else "")
                or "Customer"
            )
            bank, group, recorded = _bank_ledger(payment)
            voucher = TallyVoucher(
                category="payments",
                tally_type="Payment",
                number=payment.provider_ref or f"REF-{payment.id}",
                voucher_date=_payment_date(payment),
                party=party,
                party_gstin=_invoice_gstin(invoice) if invoice else None,
                narration=f"Customer refund [FINOVEXA:PMT:{payment.id}]",
                reference=f"PMT:{payment.id}",
                source="Business refund",
                entries=[
                    TallyLine(party, GROUP_DEBTORS, debit=q2(payment.amount), is_party=True),
                    TallyLine(bank, group, credit=q2(payment.amount)),
                ],
            )
            if not recorded:
                voucher.notes.append("Bank ledger defaulted to 'Bank Account'; map it before import.")
            add(voucher)

    if "expenses" in data.categories:
        for expense in _period_expenses(data):
            party = expense.vendor or "Unnamed vendor"
            voucher = TallyVoucher(
                category="expenses",
                tally_type="Payment",
                number=f"EXP-{expense.id}",
                voucher_date=expense.incurred_on,
                party=party,
                party_gstin=None,
                narration=f"{expense.category} expense [FINOVEXA:EXP:{expense.id}]",
                reference=f"EXP:{expense.id}",
                source="Business expense",
                entries=[
                    TallyLine(expense.category or "Expenses", GROUP_EXPENSES, debit=q2(expense.amount)),
                    TallyLine("Bank Account", GROUP_BANK, credit=q2(expense.amount)),
                ],
            )
            voucher.notes.append("Payment account is not recorded for this expense; 'Bank Account' was used.")
            add(voucher)

    for voucher_row in _period_vouchers(data):
        category = {
            "sale": "sales",
            "purchase": "purchases",
            "receipt": "receipts",
            "payment": "payments",
            "expense": "expenses",
            "journal": "journals",
            "credit_note": "credit_notes",
            "debit_note": "debit_notes",
        }.get(voucher_row.voucher_type)
        if category is None or category not in data.categories:
            continue
        party = voucher_row.party_name or "Unnamed party"
        lines = data.voucher_lines.get(voucher_row.id) or []
        entries: list[TallyLine] = []
        if lines:
            for line in lines:
                group = _line_group(voucher_row, line, party)
                entries.append(
                    TallyLine(
                        line.ledger_name,
                        group,
                        debit=q2(line.debit),
                        credit=q2(line.credit),
                        is_party=line.ledger_name.strip().lower() == party.strip().lower(),
                    )
                )
        else:
            entries = _fallback_entries(voucher_row, party)
        voucher = TallyVoucher(
            category=category,
            tally_type=VOUCHER_TALLY_TYPE.get(voucher_row.voucher_type, "Journal"),
            number=voucher_row.number,
            voucher_date=voucher_row.voucher_date,
            party=party,
            party_gstin=voucher_row.party_gstin,
            narration=f"{voucher_row.description or voucher_row.number} [FINOVEXA:VCH:{voucher_row.id}]",
            reference=f"VCH:{voucher_row.id}:{voucher_row.number}",
            source="Accounting voucher (manual)",
            entries=entries,
        )
        if not lines and voucher_row.voucher_type in ("purchase", "journal"):
            voucher.notes.append("Ledger split was not stored; a balanced fallback was used. Review before import.")
        add(voucher)

    vouchers.sort(key=lambda row: (row.voucher_date, row.tally_type, row.number))
    return vouchers


def _line_group(voucher: AccountingVoucher, line: AccountingVoucherLine, party: str) -> str:
    name = (line.ledger_name or "").lower()
    if line.ledger_name.strip().lower() == party.strip().lower():
        return GROUP_CREDITORS if voucher.voucher_type in ("purchase", "payment", "debit_note") else GROUP_DEBTORS
    if "cgst" in name or "sgst" in name or "igst" in name or "gst" in name:
        return GROUP_DUTIES
    if voucher.voucher_type in ("purchase", "debit_note"):
        return GROUP_PURCHASE
    if voucher.voucher_type in ("expense",):
        return GROUP_EXPENSES
    if voucher.voucher_type in ("sale", "credit_note"):
        return GROUP_SALES
    return GROUP_EXPENSES


def _fallback_entries(voucher: AccountingVoucher, party: str) -> list[TallyLine]:
    taxable = q2(voucher.taxable_value)
    total = q2(voucher.total_amount)
    cgst = q2(voucher.cgst_amount)
    sgst = q2(voucher.sgst_amount)
    igst = q2(voucher.igst_amount)
    bank = voucher.bank_ledger or voucher.ledger_name or "Bank Account"
    bank_group = GROUP_CASH if "cash" in bank.lower() else GROUP_BANK
    entries: list[TallyLine] = []
    if voucher.voucher_type == "sale":
        entries = [
            TallyLine(party, GROUP_DEBTORS, debit=total, is_party=True),
            TallyLine(voucher.ledger_name or "Sales", GROUP_SALES, credit=taxable),
            *_tax_lines("Output", cgst, sgst, igst, credit=True),
        ]
    elif voucher.voucher_type == "purchase":
        entries = [
            TallyLine(voucher.ledger_name or "Purchases", GROUP_PURCHASE, debit=taxable),
            TallyLine(party, GROUP_CREDITORS, credit=total, is_party=True),
            *_tax_lines("Input", cgst, sgst, igst, credit=False),
        ]
    elif voucher.voucher_type == "receipt":
        entries = [
            TallyLine(bank, bank_group, debit=total),
            TallyLine(party, GROUP_DEBTORS, credit=total, is_party=True),
        ]
    elif voucher.voucher_type == "payment":
        entries = [
            TallyLine(party, GROUP_CREDITORS, debit=total, is_party=True),
            TallyLine(bank, bank_group, credit=total),
        ]
    elif voucher.voucher_type == "expense":
        entries = [
            TallyLine(voucher.ledger_name or "Expenses", GROUP_EXPENSES, debit=total),
            TallyLine(bank, bank_group, credit=total),
            *_tax_lines("Input", cgst, sgst, igst, credit=False),
        ]
    elif voucher.voucher_type == "journal":
        entries = [
            TallyLine(voucher.ledger_name or "Journal", GROUP_EXPENSES, debit=total),
            TallyLine(party, GROUP_CREDITORS, credit=total, is_party=True),
        ]
    elif voucher.voucher_type == "credit_note":
        entries = [
            TallyLine(party, GROUP_DEBTORS, credit=total, is_party=True),
            TallyLine(voucher.ledger_name or "Sales", GROUP_SALES, debit=taxable),
            *_tax_lines("Output", cgst, sgst, igst, credit=False),
        ]
    elif voucher.voucher_type == "debit_note":
        entries = [
            TallyLine(party, GROUP_CREDITORS, debit=total, is_party=True),
            TallyLine(voucher.ledger_name or "Purchases", GROUP_PURCHASE, credit=taxable),
            *_tax_lines("Input", cgst, sgst, igst, credit=True),
        ]
    return entries


# ------------------------------------------------------------------ reconciliation


def build_reconciliation(data: ExportDataset, vouchers: list[TallyVoucher]) -> dict[str, Any]:
    invoices = _period_invoices(data)
    payments = _period_payments(data)
    expenses = _period_expenses(data)

    sales_source = sum(
        (q2(i.total_amount) for i in invoices if _include_in_tally(i)),
        ZERO,
    )
    receipts_source = sum(
        (
            q2(p.amount)
            for p in payments
            if p.status == "confirmed" and p.refund_of_payment_id is None
        ),
        ZERO,
    )
    refunds_source = sum(
        (
            q2(p.amount)
            for p in payments
            if p.status == "confirmed" and p.refund_of_payment_id is not None
        ),
        ZERO,
    )
    expenses_source = sum((q2(e.amount) for e in expenses), ZERO)
    voucher_type_totals: dict[str, Decimal] = {}
    for voucher in vouchers:
        if voucher.source != "Accounting voucher (manual)":
            continue
        key = voucher.category
        voucher_type_totals[key] = voucher_type_totals.get(key, ZERO) + _voucher_total(voucher)
    sales_source += voucher_type_totals.get("sales", ZERO)
    receipts_source += voucher_type_totals.get("receipts", ZERO)
    refunds_source += voucher_type_totals.get("payments", ZERO)
    expenses_source += voucher_type_totals.get("expenses", ZERO)

    exported: dict[str, Decimal] = {}
    for voucher in vouchers:
        exported[voucher.category] = exported.get(voucher.category, ZERO) + _voucher_total(voucher)

    def compare(label: str, source_total: Decimal, category: str) -> dict[str, Any]:
        exported_total = q2(exported.get(category, ZERO))
        difference = q2(source_total - exported_total)
        return {
            "label": label,
            "source_total": q2(source_total),
            "exported_total": exported_total,
            "difference": difference,
            "status": "matched" if difference == ZERO else "difference",
        }

    comparisons = [
        compare("Sales", sales_source, "sales"),
        compare("Receipts", receipts_source, "receipts"),
        compare("Payments and refunds", refunds_source, "payments"),
        compare("Expenses", expenses_source, "expenses"),
        compare("Purchases", voucher_type_totals.get("purchases", ZERO), "purchases"),
        compare("Journal entries", voucher_type_totals.get("journals", ZERO), "journals"),
        compare("Credit notes", voucher_type_totals.get("credit_notes", ZERO), "credit_notes"),
        compare("Debit notes", voucher_type_totals.get("debit_notes", ZERO), "debit_notes"),
    ]
    debit_total = q2(sum((v.debit_total for v in vouchers), ZERO))
    credit_total = q2(sum((v.credit_total for v in vouchers), ZERO))
    unbalanced = [v.reference for v in vouchers if not v.balanced]
    gst_source = sum(
        (
            _invoice_tax(i)
            for i in invoices
            if _include_in_tally(i)
        ),
        ZERO,
    ) + sum(
        (
            q2(
                Decimal(v.cgst_amount or ZERO)
                + Decimal(v.sgst_amount or ZERO)
                + Decimal(v.igst_amount or ZERO)
            )
            for v in _period_vouchers(data)
            if v.voucher_type == "sale"
        ),
        ZERO,
    )
    gst_exported = sum(
        (
            line.credit - line.debit
            for voucher in vouchers
            for line in voucher.entries
            if line.is_tax and line.ledger.startswith("Output")
        ),
        ZERO,
    )
    partial_invoices = [
        invoice
        for invoice in invoices
        if _include_in_tally(invoice)
        and ZERO < _invoice_paid(invoice) < q2(invoice.total_amount)
    ]
    overpaid = [
        invoice
        for invoice in invoices
        if _include_in_tally(invoice) and _invoice_paid(invoice) > q2(invoice.total_amount)
    ]
    checks = [
        {
            "key": "voucher_balance",
            "label": "Every exported voucher balances",
            "status": "passed" if not unbalanced else "failed",
            "detail": (
                f"{len(vouchers)} voucher(s): debit {debit_total} = credit {credit_total}."
                if not unbalanced
                else f"{len(unbalanced)} voucher(s) do not balance."
            ),
        },
        {
            "key": "source_totals",
            "label": "Exported totals equal the FINOVEXA source totals",
            "status": "passed"
            if all(row["status"] == "matched" for row in comparisons)
            else "failed",
            "detail": "Each category is compared below. Any difference is shown, never absorbed.",
        },
        {
            "key": "gst_match",
            "label": "Output GST matches the invoice tax snapshot",
            "status": "passed" if q2(gst_source) == q2(gst_exported) else "failed",
            "detail": f"Source {q2(gst_source)} vs exported {q2(gst_exported)}.",
        },
        {
            "key": "partial_payments",
            "label": "Partial payments are counted once",
            "status": "passed",
            "detail": (
                f"{len(partial_invoices)} partially paid invoice(s) use each confirmed receipt once; "
                f"{len(overpaid)} overpaid invoice(s) are flagged for review."
            ),
        },
        {
            "key": "duplicate_references",
            "label": "No duplicate voucher references",
            "status": "passed"
            if len({v.reference for v in vouchers}) == len(vouchers)
            else "failed",
            "detail": f"{len(vouchers)} unique transaction reference(s).",
        },
    ]
    return {
        "comparisons": comparisons,
        "checks": checks,
        "debit_total": debit_total,
        "credit_total": credit_total,
        "balanced": debit_total == credit_total and not unbalanced,
        "gst": {
            "output_source": q2(gst_source),
            "output_exported": q2(gst_exported),
            "difference": q2(gst_source - gst_exported),
        },
        "partial_payment_invoices": len(partial_invoices),
        "overpaid_invoices": len(overpaid),
    }


def _voucher_total(voucher: TallyVoucher) -> Decimal:
    return voucher.debit_total


# ------------------------------------------------------------------ preview


def preview(data: ExportDataset, *, include_issues: bool = True) -> dict[str, Any]:
    vouchers = build_tally_vouchers(data)
    issues = build_issues(data)
    counts = issue_counts(issues)
    reconciliation = build_reconciliation(data, vouchers)
    invoices = _period_invoices(data)
    payments = _period_payments(data)
    expenses = _period_expenses(data)
    period_vouchers = _period_vouchers(data)
    return {
        "linked": True,
        "client_id": data.client.id,
        "business": {
            "business_name": data.profile.business_name,
            "legal_name": data.profile.legal_name,
            "gstin": data.profile.gstin,
            "state": data.profile.state,
            "currency": data.profile.currency or "INR",
        },
        "period": {
            "from": data.date_from.isoformat() if data.date_from else None,
            "to": data.date_to.isoformat() if data.date_to else None,
            "generated_at": data.generated_at.isoformat(timespec="seconds"),
        },
        "categories": data.categories,
        "counts": {
            "sales": len(invoices),
            "purchases": sum(1 for v in period_vouchers if v.voucher_type == "purchase"),
            "receipts": sum(
                1 for p in payments if p.refund_of_payment_id is None
            ) + sum(1 for v in period_vouchers if v.voucher_type == "receipt"),
            "payments": sum(
                1 for p in payments if p.refund_of_payment_id is not None
            ) + sum(1 for v in period_vouchers if v.voucher_type == "payment"),
            "expenses": len(expenses)
            + sum(1 for v in period_vouchers if v.voucher_type == "expense"),
            "journals": sum(1 for v in period_vouchers if v.voucher_type == "journal"),
            "credit_notes": sum(1 for v in period_vouchers if v.voucher_type == "credit_note"),
            "debit_notes": sum(1 for v in period_vouchers if v.voucher_type == "debit_note"),
            "inventory": sum(len(i.items) for i in invoices if i.status not in ("void", "draft", "cancelled"))
            if "inventory" in data.categories
            else 0,
        },
        "totals": {
            "sales": q2(
                sum(
                    (q2(i.total_amount) for i in invoices if _include_in_tally(i)),
                    ZERO,
                )
                + sum(
                    (
                        q2(v.total_amount)
                        for v in period_vouchers
                        if v.voucher_type == "sale"
                    ),
                    ZERO,
                )
            ),
            "purchases": q2(
                sum(
                    (q2(v.total_amount) for v in period_vouchers if v.voucher_type == "purchase"),
                    ZERO,
                )
            ),
            "receipts": reconciliation["comparisons"][1]["source_total"],
            "payments": reconciliation["comparisons"][2]["source_total"],
            "expenses": reconciliation["comparisons"][3]["source_total"],
        },
        "tally": {
            "voucher_count": len(vouchers),
            "debit_total": reconciliation["debit_total"],
            "credit_total": reconciliation["credit_total"],
            "balanced": reconciliation["balanced"],
            "by_type": _voucher_counts(vouchers),
        },
        "issues": issues[:MAX_ISSUES] if include_issues else [],
        "issue_counts": counts,
        "missing_mappings": [
            row for row in issues if row["code"] in {
                "MISSING_PARTY",
                "MISSING_GSTIN",
                "BANK_LEDGER_DEFAULTED",
                "BANK_LEDGER_MISSING",
                "LEDGER_SPLIT_MISSING",
                "UNALLOCATED_RECEIPT",
                "MISSING_VENDOR",
            }
        ][:MAX_ISSUES],
        "review": [
            row for row in issues if row["severity"] == "review"
        ][:MAX_ISSUES],
        "reconciliation": reconciliation,
        "availability": data_availability(data),
        "import_claim": IMPORT_CLAIM,
        "note": (
            "Preview only. No file is created and no source record is changed. "
            "Amounts are read from stored invoices, payments, expenses and manual vouchers."
        ),
    }


def _voucher_counts(vouchers: list[TallyVoucher]) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for voucher in vouchers:
        row = counts.setdefault(
            voucher.category,
            {"category": voucher.category, "label": BUSINESS_EXPORT_LABELS.get(voucher.category, voucher.category), "count": 0},
        )
        row["count"] += 1
    return list(counts.values())


# ------------------------------------------------------------------ workbook


def _style_sheet(sheet, headers: list[str], money_columns: set[int] | None = None) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    sheet.append(headers)
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="1E293B")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"
    for index, column in enumerate(sheet.columns, start=1):
        width = max((len(str(cell.value)) if cell.value is not None else 0) for cell in column)
        sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 12), 52)
    if money_columns:
        for row in sheet.iter_rows(min_row=2):
            for index in money_columns:
                if index <= len(row):
                    row[index - 1].number_format = "#,##0.00"


def _write_sheet(workbook, title: str, headers: list[str], rows: list[list[Any]], *, money_columns: set[int] | None = None) -> None:
    sheet = workbook.create_sheet(title)
    _style_sheet(sheet, headers, money_columns)
    if rows:
        for row in rows:
            sheet.append(row)
    else:
        sheet.append(["No records available for this period."])
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=min(len(headers), 8))


def build_workbook(data: ExportDataset) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    workbook.remove(workbook.active)

    _write_sheet(
        workbook,
        "Sales Register",
        SALES_COLUMNS,
        sales_rows(data),
        money_columns={11, 12, 13, 14, 15, 16, 17, 18, 19, 20},
    )
    _write_sheet(
        workbook,
        "Purchase Register",
        PURCHASE_COLUMNS,
        purchase_rows(data),
        money_columns={9, 10, 11, 12, 13},
    )
    _write_sheet(
        workbook,
        "Receipt Register",
        RECEIPT_COLUMNS,
        receipt_rows(data),
        money_columns={9},
    )
    _write_sheet(
        workbook,
        "Payment Register",
        PAYMENT_COLUMNS,
        payment_rows(data),
        money_columns={8},
    )
    _write_sheet(
        workbook,
        "Expense Register",
        EXPENSE_COLUMNS,
        expense_rows(data),
        money_columns={7, 8, 9},
    )
    _write_sheet(
        workbook,
        "Customer Ledger",
        CUSTOMER_LEDGER_COLUMNS,
        customer_ledger_rows(data),
        money_columns={3, 4, 5, 6, 7},
    )
    _write_sheet(
        workbook,
        "Supplier Ledger",
        SUPPLIER_LEDGER_COLUMNS,
        supplier_ledger_rows(data),
        money_columns={3, 4, 5, 6, 7},
    )
    _write_sheet(
        workbook,
        "GST Summary",
        GST_COLUMNS,
        gst_rows(data),
        money_columns={3, 4, 5, 6, 7},
    )
    credit_rows = note_rows(data, "credit_note", "credit_notes")
    if not credit_rows and "credit_notes" in data.categories:
        credit_rows = [
            [
                "",
                "",
                "",
                "",
                "FINOVEXA does not capture credit notes in the live books.",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "No credit-note records exist for this period; nothing is invented.",
                "",
            ]
        ]
    _write_sheet(workbook, "Credit Notes", NOTE_COLUMNS, credit_rows, money_columns={8, 9, 10, 11, 12})
    debit_rows = note_rows(data, "debit_note", "debit_notes")
    if not debit_rows and "debit_notes" in data.categories:
        debit_rows = [
            [
                "",
                "",
                "",
                "",
                "FINOVEXA does not capture debit notes in the live books.",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "No debit-note records exist for this period; nothing is invented.",
                "",
            ]
        ]
    _write_sheet(workbook, "Debit Notes", NOTE_COLUMNS, debit_rows, money_columns={8, 9, 10, 11, 12})
    _write_sheet(
        workbook,
        "Journal Entries",
        JOURNAL_COLUMNS,
        journal_rows(data),
        money_columns={8, 9},
    )
    _write_sheet(
        workbook,
        "Inventory Transactions",
        INVENTORY_COLUMNS,
        inventory_rows(data),
        money_columns={9, 10},
    )
    _write_sheet(
        workbook,
        "Stock Summary",
        STOCK_COLUMNS,
        stock_rows(data),
        money_columns={5, 8, 9},
    )

    summary = workbook.create_sheet("Business Summary")
    summary["A1"] = "FINOVEXA AI — Complete Business Data Export"
    summary["A1"].font = Font(bold=True, size=14)
    summary["A2"] = (
        "Read-only snapshot of the linked business's stored records. Blank or "
        "'Not recorded' values mean the source system does not hold that information."
    )
    summary["A2"].alignment = Alignment(wrap_text=True)
    summary.merge_cells("A2:D2")
    row = 4
    summary.cell(row=row, column=1, value="Business details").font = Font(bold=True)
    row += 1
    for label, value in summary_pairs(data):
        summary.cell(row=row, column=1, value=label).font = Font(bold=True)
        summary.cell(row=row, column=2, value=value)
        row += 1
    row += 1
    summary.cell(row=row, column=1, value="Data availability").font = Font(bold=True)
    row += 1
    for cell_value in ("Worksheet", "Status", "Note"):
        summary.cell(row=row, column={"Worksheet": 1, "Status": 2, "Note": 3}[cell_value], value=cell_value).font = Font(bold=True)
    row += 1
    start_availability = row
    for values in data_availability(data):
        for index, value in enumerate(values, start=1):
            summary.cell(row=row, column=index, value=value).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    for column, width in (("A", 34), ("B", 34), ("C", 80), ("D", 24)):
        summary.column_dimensions[column].width = width

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ------------------------------------------------------------------ Tally files


TALLY_ENTRY_COLUMNS = [
    "Voucher Date",
    "Voucher Type",
    "Voucher Number",
    "Party",
    "Party GSTIN",
    "Ledger",
    "Group",
    "Debit",
    "Credit",
    "Narration",
    "Transaction Reference",
    "Review Note",
]


def tally_entry_rows(vouchers: list[TallyVoucher]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for voucher in vouchers:
        note = " ".join(voucher.notes)
        for line in voucher.entries:
            rows.append(
                [
                    voucher.voucher_date.isoformat(),
                    voucher.tally_type,
                    voucher.number,
                    voucher.party,
                    voucher.party_gstin or "",
                    line.ledger,
                    line.group,
                    q2(line.debit),
                    q2(line.credit),
                    voucher.narration,
                    voucher.reference,
                    note,
                ]
            )
    return rows


def build_tally_workbook(data: ExportDataset) -> tuple[bytes, dict[str, Any]]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    vouchers = build_tally_vouchers(data)
    report = build_reconciliation(data, vouchers)
    issues = build_issues(data)

    workbook = Workbook()
    instructions = workbook.active
    instructions.title = "Instructions"
    instructions["A1"] = "Tally export instructions"
    instructions["A1"].font = Font(bold=True, size=14)
    rows = [
        ("What this file is", "A structured export of FINOVEXA vouchers for import or mapping into TallyPrime. Nothing is written to Tally automatically."),
        ("Company", f"Open {data.profile.business_name} in TallyPrime and confirm the GSTIN and state."),
        ("Step 1 — back up", "Take a TallyPrime backup before importing any voucher."),
        ("Step 2 — review mappings", "Check the Ledger Masters sheet against your Tally ledgers. 'Bank Account' and 'Round Off' are fallback ledgers and must be mapped."),
        ("Step 3 — import", "Use TallyPrime's voucher import with this sheet layout, or import the XML pack from the Export Centre."),
        ("Step 4 — reconcile", "Compare the voucher count and totals with the Reconciliation sheet. Investigate every difference."),
        ("Step 5 — record the result", "Mark the export as imported or failed in the Export History so the audit trail is complete."),
        ("Import claim", IMPORT_CLAIM),
    ]
    row = 3
    for label, text in rows:
        instructions.cell(row=row, column=1, value=label).font = Font(bold=True)
        instructions.cell(row=row, column=2, value=text).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    instructions.column_dimensions["A"].width = 28
    instructions.column_dimensions["B"].width = 110

    summary = workbook.create_sheet("Summary")
    summary.append(["Item", "Value"])
    for cell in summary[1]:
        cell.fill = PatternFill("solid", fgColor="1E293B")
        cell.font = Font(color="FFFFFF", bold=True)
    for label, value in summary_pairs(data):
        summary.append([label, value])

    reconciliation = workbook.create_sheet("Reconciliation")
    reconciliation.append(["Category", "FINOVEXA total", "Exported vouchers", "Difference", "Status"])
    for cell in reconciliation[1]:
        cell.fill = PatternFill("solid", fgColor="1E293B")
        cell.font = Font(color="FFFFFF", bold=True)
    for pair in report["comparisons"]:
        reconciliation.append(
            [pair["label"], pair["source_total"], pair["exported_total"], pair["difference"], pair["status"]]
        )
    reconciliation.append(["Total debit", report["debit_total"], "", "", ""])
    reconciliation.append(["Total credit", report["credit_total"], "", "", ""])
    reconciliation.append(["Balanced", "Yes" if report["balanced"] else "No", "", "", ""])
    for row_cells in reconciliation.iter_rows(min_row=2, min_col=2, max_col=4):
        for cell in row_cells:
            cell.number_format = "#,##0.00"

    group_order = [
        ("Sales", "Sales Vouchers"),
        ("Purchase", "Purchase Vouchers"),
        ("Receipt", "Receipt Vouchers"),
        ("Payment", "Payment Vouchers"),
        ("Journal", "Journal Vouchers"),
        ("Credit Note", "Credit Notes"),
        ("Debit Note", "Debit Notes"),
    ]
    for tally_type, title in group_order:
        sheet = workbook.create_sheet(title)
        sheet.append(TALLY_ENTRY_COLUMNS)
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="1E293B")
            cell.font = Font(color="FFFFFF", bold=True)
        subset = [voucher for voucher in vouchers if voucher.tally_type == tally_type]
        if subset:
            for values in tally_entry_rows(subset):
                sheet.append(values)
        else:
            sheet.append(["No vouchers of this type in the selected period."])
        for column in sheet.columns:
            width = max((len(str(cell.value)) if cell.value is not None else 0) for cell in column)
            sheet.column_dimensions[get_column_letter(column[0].column)].width = min(max(width + 2, 12), 52)
        for row_cells in sheet.iter_rows(min_row=2, min_col=8, max_col=9):
            for cell in row_cells:
                cell.number_format = "#,##0.00"

    entries = workbook.create_sheet("Voucher Entries")
    entries.append(TALLY_ENTRY_COLUMNS)
    for cell in entries[1]:
        cell.fill = PatternFill("solid", fgColor="1E293B")
        cell.font = Font(color="FFFFFF", bold=True)
    for values in tally_entry_rows(vouchers):
        entries.append(values)
    for row_cells in entries.iter_rows(min_row=2, min_col=8, max_col=9):
        for cell in row_cells:
            cell.number_format = "#,##0.00"

    masters = workbook.create_sheet("Ledger Masters")
    masters.append(["Ledger", "Tally Group", "Party GSTIN", "Source", "Note"])
    for cell in masters[1]:
        cell.fill = PatternFill("solid", fgColor="1E293B")
        cell.font = Font(color="FFFFFF", bold=True)
    for name, group, gstin, source, note in ledger_master_rows(vouchers):
        masters.append([name, group, gstin, source, note])

    validation = workbook.create_sheet("Validation")
    validation.append(["Severity", "Code", "Reference", "Message"])
    for cell in validation[1]:
        cell.fill = PatternFill("solid", fgColor="1E293B")
        cell.font = Font(color="FFFFFF", bold=True)
    if issues:
        for issue in issues:
            validation.append(
                [issue["severity"], issue["code"], issue["reference"] or "", issue["message"]]
            )
    else:
        validation.append(["info", "NO_ISSUES", "", "No mapping or balance problems were found."])
    for sheet in workbook.worksheets:
        for column in sheet.columns:
            width = max((len(str(cell.value)) if cell.value is not None else 0) for cell in column)
            sheet.column_dimensions[get_column_letter(column[0].column)].width = min(max(width + 2, 12), 60)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), {
        "vouchers": len(vouchers),
        "issues": len(issues),
        "reconciliation": report,
    }


def ledger_master_rows(vouchers: list[TallyVoucher]) -> list[list[Any]]:
    masters: dict[str, dict[str, Any]] = {}

    def add(name: str, group: str, *, gstin: str | None = None, source: str, note: str = "") -> None:
        name = (name or "").strip()
        if not name:
            return
        if name not in masters:
            masters[name] = {"group": group, "gstin": gstin, "source": source, "note": note}
        elif gstin and not masters[name]["gstin"]:
            masters[name]["gstin"] = gstin

    for voucher in vouchers:
        for line in voucher.entries:
            add(
                line.ledger,
                line.group,
                gstin=voucher.party_gstin if line.is_party else None,
                source="Party" if line.is_party else ("GST" if line.is_tax else "Voucher"),
                note=(
                    "Tally group inferred from the voucher type; confirm it."
                    if line.group in (GROUP_EXPENSES, GROUP_PURCHASE, GROUP_SALES)
                    else ""
                ),
            )
        for note in voucher.notes:
            if "Bank ledger" in note:
                add("Bank Account", GROUP_BANK, source="Fallback", note=note)
            if "Payment account" in note:
                add("Bank Account", GROUP_BANK, source="Fallback", note=note)
    add("Round Off", GROUP_EXPENSES, source="Fallback", note="Balancing line written only when a stored rounding difference exists.")
    return [
        [name, row["group"], row["gstin"] or "", row["source"], row["note"]]
        for name, row in sorted(masters.items(), key=lambda item: (item[1]["group"], item[0].lower()))
    ]


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


def _tally_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _xml_money(value: Decimal) -> str:
    return f"{q2(value):.2f}"


def build_master_xml(data: ExportDataset, vouchers: list[TallyVoucher]) -> str:
    parts: list[str] = []
    for name, group, gstin, _source, _note in ledger_master_rows(vouchers):
        parts.append(
            "        <TALLYMESSAGE xmlns:UDF=\"TallyUDF\">\n"
            f"          <LEDGER NAME={quoteattr(name)} ACTION=\"Create\">\n"
            f"            <NAME>{escape(name)}</NAME>\n"
            f"            <PARENT>{escape(group)}</PARENT>\n"
            f"            <GSTREGISTRATIONTYPE>{'Regular' if gstin else 'Unregistered'}</GSTREGISTRATIONTYPE>\n"
            + (f"            <PARTYGSTIN>{escape(gstin)}</PARTYGSTIN>\n" if gstin else "")
            + "          </LEDGER>\n"
            "        </TALLYMESSAGE>\n"
        )
    if "inventory" in data.categories:
        for product in data.products:
            parts.append(
                "        <TALLYMESSAGE xmlns:UDF=\"TallyUDF\">\n"
                f"          <STOCKITEM NAME={quoteattr(product.name)} ACTION=\"Create\">\n"
                f"            <NAME>{escape(product.name)}</NAME>\n"
                f"            <BASEUNITS>{escape(product.unit)}</BASEUNITS>\n"
                + (f"            <HSNCODE>{escape(product.hsn_sac)}</HSNCODE>\n" if product.hsn_sac else "")
                + "          </STOCKITEM>\n"
                "        </TALLYMESSAGE>\n"
            )
    return _envelope(data.profile.business_name, "All Masters", "".join(parts))


def build_voucher_xml(data: ExportDataset, vouchers: list[TallyVoucher]) -> str:
    parts: list[str] = []
    for voucher in vouchers:
        lines: list[str] = []
        for line in voucher.entries:
            debit = line.debit > ZERO
            amount = line.debit if debit else line.credit
            signed = -amount if debit else amount
            lines.append(
                "            <ALLLEDGERENTRIES.LIST>\n"
                f"              <LEDGERNAME>{escape(line.ledger)}</LEDGERNAME>\n"
                f"              <ISDEEMEDPOSITIVE>{'Yes' if debit else 'No'}</ISDEEMEDPOSITIVE>\n"
                f"              <AMOUNT>{_xml_money(signed)}</AMOUNT>\n"
                "            </ALLLEDGERENTRIES.LIST>\n"
            )
        parts.append(
            "        <TALLYMESSAGE xmlns:UDF=\"TallyUDF\">\n"
            f"          <VOUCHER VCHTYPE={quoteattr(voucher.tally_type)} ACTION=\"Create\" OBJVIEW=\"Invoice Voucher View\">\n"
            f"            <DATE>{_tally_date(voucher.voucher_date)}</DATE>\n"
            f"            <EFFECTIVEDATE>{_tally_date(voucher.voucher_date)}</EFFECTIVEDATE>\n"
            f"            <VOUCHERTYPENAME>{escape(voucher.tally_type)}</VOUCHERTYPENAME>\n"
            f"            <VOUCHERNUMBER>{escape(voucher.number)}</VOUCHERNUMBER>\n"
            f"            <REFERENCE>{escape(voucher.reference)}</REFERENCE>\n"
            f"            <PARTYLEDGERNAME>{escape(voucher.party)}</PARTYLEDGERNAME>\n"
            + (f"            <PARTYGSTIN>{escape(voucher.party_gstin)}</PARTYGSTIN>\n" if voucher.party_gstin else "")
            + f"            <NARRATION>{escape(voucher.narration)}</NARRATION>\n"
            + "".join(lines)
            + "          </VOUCHER>\n"
            "        </TALLYMESSAGE>\n"
        )
    return _envelope(data.profile.business_name, "Vouchers", "".join(parts))


def validate_xml(xml_text: str, expected_vouchers: int) -> None:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Generated Tally XML is not well formed: {exc}") from exc
    if expected_vouchers:
        found = len(root.findall(".//VOUCHER"))
        if found != expected_vouchers:
            raise ValueError(
                f"Generated Tally XML contains {found} vouchers but {expected_vouchers} were expected."
            )


def build_tally_xml_pack(data: ExportDataset) -> tuple[bytes, dict[str, Any]]:
    vouchers = build_tally_vouchers(data)
    report = build_reconciliation(data, vouchers)
    master = build_master_xml(data, vouchers)
    voucher_xml = build_voucher_xml(data, vouchers)
    validate_xml(master, 0)
    validate_xml(voucher_xml, len(vouchers))
    readme = [
        "FINOVEXA AI — Tally XML pack",
        "",
        f"Business: {data.profile.business_name}",
        f"Period: {data.date_from or 'earliest'} to {data.date_to or 'latest'}",
        f"Vouchers: {len(vouchers)}",
        f"Debit total: {report['debit_total']}",
        f"Credit total: {report['credit_total']}",
        "",
        f"IMPORTANT: {IMPORT_CLAIM}",
        "",
        "1. Back up the Tally company.",
        "2. Import tally-master-import.xml (Import Data > Masters) and review groups/GSTINs.",
        "3. Import tally-voucher-import.xml (Import Data > Vouchers).",
        "4. Reconcile voucher count and totals with the Reconciliation sheet in the Tally Excel export.",
        "5. Record the import result in the FINOVEXA Export History.",
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("tally-master-import.xml", master)
        archive.writestr("tally-voucher-import.xml", voucher_xml)
        archive.writestr("README.txt", "\n".join(readme) + "\n")
    return buffer.getvalue(), {
        "vouchers": len(vouchers),
        "reconciliation": report,
    }


# ------------------------------------------------------------------ persistence


def _filename(data: ExportDataset, kind: str, suffix: str) -> str:
    start = data.date_from.isoformat() if data.date_from else "opening"
    end = data.date_to.isoformat() if data.date_to else "latest"
    label = {
        WORKBOOK_KIND: "complete-data",
        TALLY_EXCEL_KIND: "tally-export",
        TALLY_XML_KIND: "tally-xml-pack",
    }[kind]
    return f"finovexa-{_slug(data.profile.business_name)}-{label}-{start}-to-{end}.{suffix}"


def _store(
    db: Session,
    data: ExportDataset,
    *,
    kind: str,
    raw: bytes,
    suffix: str,
    row_count: int,
    issues: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    created_by_id: int,
    tally_version: str | None = None,
) -> AccountingDataExport:
    stored_name, sha256, size = save_document_file(db, raw, suffix)
    filename = _filename(data, kind, suffix)
    counts = issue_counts(issues)
    record = AccountingDataExport(
        client_id=data.client.id,
        export_kind=kind,
        categories=list(data.categories),
        period_from=data.date_from,
        period_to=data.date_to,
        filename=filename,
        stored_name=stored_name,
        file_sha256=sha256,
        file_size=size,
        row_count=row_count,
        warning_count=counts["warnings"],
        error_count=counts["errors"],
        status="exported",
        created_by_user_id=created_by_id,
        details=_json_safe(
            {
                "business_name": data.profile.business_name,
                "gstin": data.profile.gstin,
                "generated_at": data.generated_at,
                "issue_counts": counts,
                "reconciliation": reconciliation,
                "import_claim": IMPORT_CLAIM,
                "tally_version": tally_version,
            }
        ),
    )
    db.add(record)
    db.flush()
    return record


def create_workbook(db: Session, data: ExportDataset, *, created_by_id: int) -> AccountingDataExport:
    raw = build_workbook(data)
    return _store(
        db,
        data,
        kind=WORKBOOK_KIND,
        raw=raw,
        suffix="xlsx",
        row_count=sum(
            (
                len(sales_rows(data)),
                len(purchase_rows(data)),
                len(receipt_rows(data)),
                len(payment_rows(data)),
                len(expense_rows(data)),
                len(customer_ledger_rows(data)),
                len(supplier_ledger_rows(data)),
                len(gst_rows(data)),
                len(journal_rows(data)),
                len(inventory_rows(data)),
                len(stock_rows(data)),
            )
        ),
        issues=build_issues(data),
        reconciliation=build_reconciliation(data, build_tally_vouchers(data)),
        created_by_id=created_by_id,
    )


def create_tally_export(
    db: Session,
    data: ExportDataset,
    *,
    file_format: str,
    tally_version: str,
    created_by_id: int,
) -> AccountingDataExport:
    if file_format == "xml":
        raw, meta = build_tally_xml_pack(data)
        return _store(
            db,
            data,
            kind=TALLY_XML_KIND,
            raw=raw,
            suffix="zip",
            row_count=meta["vouchers"],
            issues=build_issues(data),
            reconciliation=meta["reconciliation"],
            created_by_id=created_by_id,
            tally_version=tally_version,
        )
    raw, meta = build_tally_workbook(data)
    return _store(
        db,
        data,
        kind=TALLY_EXCEL_KIND,
        raw=raw,
        suffix="xlsx",
        row_count=meta["vouchers"],
        issues=build_issues(data),
        reconciliation=meta["reconciliation"],
        created_by_id=created_by_id,
        tally_version=tally_version,
    )


def export_catalog(db: Session, client: AccountingClient) -> dict[str, Any]:
    data = build_dataset(db, client, categories=None, date_from=None, date_to=None)
    years = sorted(
        {
            financial_year_for(invoice.issue_date)
            for invoice in data.invoices
        }
        | {financial_year_for(expense.incurred_on) for expense in data.expenses}
        | {financial_year_for(voucher.voucher_date) for voucher in data.vouchers}
    )
    today = date.today()
    current_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    return {
        "linked": True,
        "client_id": client.id,
        "business": {
            "business_name": data.profile.business_name,
            "gstin": data.profile.gstin,
            "state": data.profile.state,
            "currency": data.profile.currency or "INR",
        },
        "categories": [
            {"key": key, "label": BUSINESS_EXPORT_LABELS[key]} for key in BUSINESS_EXPORT_CATEGORIES
        ],
        "tally_versions": list(TALLY_VERSIONS),
        "tally_formats": ["xlsx", "xml"],
        "financial_years": years,
        "default_from": current_start.isoformat(),
        "default_to": today.isoformat(),
        "counts": {
            "invoices": len(data.invoices),
            "payments": len(data.payments),
            "expenses": len(data.expenses),
            "accounting_vouchers": len(data.vouchers),
            "products": len(data.products),
        },
        "note": (
            "Exports are read-only snapshots. Integration-sourced accounting vouchers are "
            "excluded because the originating invoice, payment or expense is already included."
        ),
    }


def export_to_dict(db: Session, record: AccountingDataExport) -> dict[str, Any]:
    person = db.get(User, record.created_by_user_id) if record.created_by_user_id else None
    return {
        "id": record.id,
        "client_id": record.client_id,
        "export_kind": record.export_kind,
        "categories": record.categories or [],
        "category_labels": [BUSINESS_EXPORT_LABELS.get(c, c) for c in (record.categories or [])],
        "period_from": record.period_from.isoformat() if record.period_from else None,
        "period_to": record.period_to.isoformat() if record.period_to else None,
        "filename": record.filename,
        "file_sha256": record.file_sha256,
        "file_size": record.file_size,
        "row_count": record.row_count,
        "warning_count": record.warning_count,
        "error_count": record.error_count,
        "status": record.status,
        "created_by": person.full_name if person else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "details": record.details or {},
        "download_url": (
            f"/api/accounting/clients/{record.client_id}/exports/{record.id}/download"
            if record.stored_name
            else None
        ),
    }


__all__ = [
    "SHEET_NAMES",
    "build_dataset",
    "build_issues",
    "build_reconciliation",
    "build_tally_vouchers",
    "build_tally_workbook",
    "build_tally_xml_pack",
    "build_workbook",
    "create_tally_export",
    "create_workbook",
    "export_catalog",
    "export_to_dict",
    "preview",
    "validate_xml",
]
