"""Static catalogue for the professional accounting services practice.

Prices are deliberately absent: every engagement is quoted after a review of
the enquiry. Nothing here implies a service is already delivered.
"""

from __future__ import annotations

ACCOUNTING_SERVICES: list[dict] = [
    {
        "key": "bookkeeping",
        "name": "Bookkeeping",
        "description": "Day-to-day sales, purchase and journal entries kept in double entry with a monthly ledger review.",
        "includes": ["Sales and purchase vouchers", "Ledger and party reconciliation", "Monthly book-closing checklist"],
    },
    {
        "key": "gst_accounting",
        "name": "GST accounting and return preparation",
        "description": "GST-compliant books plus GSTR-1 and GSTR-3B working papers prepared for your review.",
        "includes": ["Output tax and input tax credit summary", "GSTR-1 and GSTR-3B working papers", "Mismatch flags for accountant review"],
    },
    {
        "key": "itr_filing",
        "name": "ITR filing assistance",
        "description": "Income-tax computation support for business owners, prepared for professional verification before filing.",
        "includes": ["Computation working papers", "Document checklist", "Accountant review before submission"],
    },
    {
        "key": "bank_reconciliation",
        "name": "Bank reconciliation",
        "description": "Bank statement import, suggested matches against your books and a clear list of unmatched items.",
        "includes": ["CSV/Excel statement import", "Suggested matches with confidence", "Duplicate and unmatched reports"],
    },
    {
        "key": "sales_purchase",
        "name": "Sales and purchase accounting",
        "description": "Structured sales and purchase registers with GST split, supplier checks and ageing.",
        "includes": ["Sales register", "Purchase register", "Receivable and payable ageing"],
    },
    {
        "key": "payroll",
        "name": "Payroll management",
        "description": "Payroll registers, salary summaries and statutory deduction workings maintained by the practice.",
        "includes": ["Monthly payroll register", "Deduction workings", "Payslip summary documents"],
    },
    {
        "key": "financial_statements",
        "name": "Financial statements",
        "description": "Draft profit-and-loss, balance sheet workings and notes prepared from your reconciled books.",
        "includes": ["Draft P&L", "Draft balance sheet", "Review notes and disclosures"],
    },
    {
        "key": "tally_support",
        "name": "Tally support",
        "description": "Tally-friendly CSV exports, voucher imports with validation and ledger mapping support.",
        "includes": ["Tally-ready voucher export", "Import validation and duplicate detection", "Ledger mapping"],
    },
]

SERVICE_KEYS: tuple[str, ...] = tuple(item["key"] for item in ACCOUNTING_SERVICES)
SERVICE_LABELS: dict[str, str] = {item["key"]: item["name"] for item in ACCOUNTING_SERVICES}

BUSINESS_TYPES: tuple[str, ...] = (
    "Proprietorship",
    "Partnership",
    "LLP",
    "Private Limited",
    "Public Limited",
    "HUF",
    "Trust / Society",
    "Freelancer",
    "Other",
)

TURNOVER_RANGES: tuple[str, ...] = (
    "Under INR 20 lakh",
    "INR 20 lakh - 1 crore",
    "INR 1 crore - 5 crore",
    "INR 5 crore - 25 crore",
    "Above INR 25 crore",
    "Not sure yet",
)

GST_STATUSES: tuple[str, ...] = (
    "Registered - regular",
    "Registered - composition",
    "Not registered",
    "Registration in progress",
)

TASK_SERVICE_TYPES: tuple[str, ...] = SERVICE_KEYS

REPORT_TYPES: tuple[str, ...] = ("monthly_summary", "gstr1", "gstr3b", "financials")

VOUCHER_TYPES: tuple[str, ...] = ("sale", "purchase", "journal", "payment", "receipt", "expense")

TALLY_EXPORT_TYPES: tuple[str, ...] = (
    "sales",
    "purchase",
    "payment",
    "receipt",
    "expense",
    "ledger_masters",
    "stock_masters",
)
TALLY_EXPORT_LABELS: dict[str, str] = {
    "sales": "Sales vouchers",
    "purchase": "Purchase vouchers",
    "payment": "Payment vouchers",
    "receipt": "Receipt vouchers",
    "expense": "Expense entries",
    "ledger_masters": "Ledger masters",
    "stock_masters": "Stock item masters",
}
TALLY_EXPORT_FORMATS: tuple[str, ...] = ("xlsx", "csv_zip", "xml", "json")

# Categories for the accountant's complete-business export workbook and the
# Tally Export Centre. These mirror the 14 worksheets in the product spec.
BUSINESS_EXPORT_CATEGORIES: tuple[str, ...] = (
    "sales",
    "purchases",
    "receipts",
    "payments",
    "expenses",
    "journals",
    "credit_notes",
    "debit_notes",
    "inventory",
)
BUSINESS_EXPORT_LABELS: dict[str, str] = {
    "sales": "Sales",
    "purchases": "Purchases",
    "receipts": "Receipts",
    "payments": "Payments and refunds",
    "expenses": "Expenses",
    "journals": "Journal entries",
    "credit_notes": "Credit notes",
    "debit_notes": "Debit notes",
    "inventory": "Inventory and stock",
}
TALLY_IMPORT_STATUSES: tuple[str, ...] = (
    "not_imported",
    "imported",
    "partially_imported",
    "failed",
)

# ---------------------------------------------------------------- Tally migration
# File-based migration only. FINOVEXA never connects to a Tally installation and
# never reads or writes a Tally company directly. Tally's own documentation governs
# the exact XML and master/voucher field names; this module models the commonly
# exported shapes and clearly reports anything it cannot map.

TALLY_VERSIONS: tuple[str, ...] = (
    "TallyPrime 5.0",
    "TallyPrime 4.1",
    "TallyPrime 3.0",
    "TallyPrime 2.0",
    "Tally ERP 9",
)

TALLY_VERSION_FORMATS: dict[str, tuple[str, ...]] = {
    # JSON import/export is offered on TallyPrime 3.0 and later only.
    "TallyPrime 5.0": ("xlsx", "xls", "csv", "xml", "json"),
    "TallyPrime 4.1": ("xlsx", "xls", "csv", "xml", "json"),
    "TallyPrime 3.0": ("xlsx", "xls", "csv", "xml", "json"),
    "TallyPrime 2.0": ("xlsx", "xls", "csv", "xml"),
    "Tally ERP 9": ("xlsx", "xls", "csv", "xml"),
}

TALLY_MIGRATION_FORMATS: tuple[str, ...] = ("xlsx", "xls", "csv", "xml", "json")

TALLY_MIGRATION_IMPORT_TYPES: tuple[str, ...] = (
    "ledger_masters",
    "groups",
    "stock_masters",
    "sales",
    "purchase",
    "payment",
    "receipt",
    "journal",
    "debit_credit_notes",
    "historical_balances",
    "complete",
    "opening_balances",
)

TALLY_MIGRATION_IMPORT_LABELS: dict[str, str] = {
    "ledger_masters": "Ledger masters",
    "groups": "Groups",
    "stock_masters": "Stock item masters",
    "sales": "Sales vouchers",
    "purchase": "Purchase vouchers",
    "payment": "Payment vouchers",
    "receipt": "Receipt vouchers",
    "journal": "Journal vouchers",
    "debit_credit_notes": "Debit notes and credit notes",
    "historical_balances": "Historical balances",
    "complete": "Complete historical transaction data",
    "opening_balances": "Opening balances",
}

TALLY_RECORD_TYPES: dict[str, str] = {
    "ledger_masters": "ledger",
    "groups": "group",
    "stock_masters": "stock",
    "historical_balances": "balance",
    "opening_balances": "opening",
    "sales": "voucher",
    "purchase": "voucher",
    "payment": "voucher",
    "receipt": "voucher",
    "journal": "voucher",
    "debit_credit_notes": "voucher",
    "complete": "voucher",
}

TALLY_MIGRATION_STATUSES: tuple[str, ...] = (
    "validated",
    "pending_approval",
    "approved",
    "rejected",
    "imported",
    "partially_imported",
    "failed",
    "rolled_back",
)

TALLY_MAPPING_FIELDS: tuple[dict[str, object], ...] = (
    {
        "key": "voucher_type",
        "label": "Voucher type",
        "group": "Voucher",
        "aliases": ("voucher type", "vch type", "vouchertype", "vouchertypename", "type", "vchtype"),
    },
    {
        "key": "voucher_number",
        "label": "Voucher number",
        "group": "Voucher",
        "aliases": ("voucher number", "voucher no", "voucher no.", "vouchernumber", "vch no", "vch no.", "number", "invoice no", "invoice number", "bill no"),
    },
    {
        "key": "voucher_date",
        "label": "Voucher date",
        "group": "Voucher",
        "aliases": ("voucher date", "voucherdate", "vch date", "date", "invoice date", "bill date"),
    },
    {
        "key": "party_name",
        "label": "Party name",
        "group": "Voucher",
        "aliases": ("party name", "party", "party ledger", "party ledger name", "partyledgername", "customer", "supplier", "customer name", "supplier name"),
    },
    {
        "key": "party_gstin",
        "label": "Party GSTIN",
        "group": "Voucher",
        "aliases": ("party gstin", "partygstin", "gstin", "gst no", "gst number", "party gst no", "party gstin/uin"),
    },
    {
        "key": "ledger_name",
        "label": "Ledger name",
        "group": "Line",
        "aliases": ("ledger name", "ledgername", "ledger", "account", "ledger account", "ledgeraccount"),
    },
    {
        "key": "ledger_group",
        "label": "Ledger group",
        "group": "Line",
        "aliases": ("ledger group", "ledgergroup", "group", "group name", "under", "parent group"),
    },
    {
        "key": "debit",
        "label": "Debit amount",
        "group": "Line",
        "aliases": ("debit", "debit amount", "dr", "dr amount"),
    },
    {
        "key": "credit",
        "label": "Credit amount",
        "group": "Line",
        "aliases": ("credit", "credit amount", "cr", "cr amount"),
    },
    {
        "key": "amount",
        "label": "Amount",
        "group": "Line",
        "aliases": ("amount", "value", "net amount"),
    },
    {
        "key": "dr_cr",
        "label": "Debit / credit indicator",
        "group": "Line",
        "aliases": ("dr/cr", "dr cr", "debit/credit", "dr-cr", "dc", "balance type", "opening type"),
    },
    {
        "key": "taxable_value",
        "label": "Taxable value",
        "group": "GST",
        "aliases": ("taxable value", "taxable", "taxable amount", "assessable value", "net amount"),
    },
    {
        "key": "gst_rate",
        "label": "GST rate",
        "group": "GST",
        "aliases": ("gst rate", "tax rate", "rate", "gst %", "gst percent"),
    },
    {
        "key": "cgst",
        "label": "CGST amount",
        "group": "GST",
        "aliases": ("cgst", "cgst amount", "central tax"),
    },
    {
        "key": "sgst",
        "label": "SGST amount",
        "group": "GST",
        "aliases": ("sgst", "sgst amount", "state tax"),
    },
    {
        "key": "igst",
        "label": "IGST amount",
        "group": "GST",
        "aliases": ("igst", "igst amount", "integrated tax"),
    },
    {
        "key": "narration",
        "label": "Narration",
        "group": "Voucher",
        "aliases": ("narration", "description", "particulars", "remarks", "notes"),
    },
    {
        "key": "reference",
        "label": "Invoice reference",
        "group": "Voucher",
        "aliases": ("invoice reference", "reference", "ref", "bill reference", "original invoice", "against reference"),
    },
    {
        "key": "stock_item",
        "label": "Stock item",
        "group": "Stock",
        "aliases": ("stock item", "item", "item name", "stock item name"),
    },
    {
        "key": "quantity",
        "label": "Quantity",
        "group": "Stock",
        "aliases": ("quantity", "qty", "qty.", "opening quantity"),
    },
    {
        "key": "unit",
        "label": "Unit",
        "group": "Stock",
        "aliases": ("unit", "uom", "units"),
    },
    {
        "key": "rate",
        "label": "Rate",
        "group": "Stock",
        "aliases": ("rate", "price", "unit price", "opening rate"),
    },
    {
        "key": "hsn_sac",
        "label": "HSN / SAC",
        "group": "Stock",
        "aliases": ("hsn", "hsn/sac", "hsn sac", "sac", "hsn code"),
    },
    {
        "key": "sku",
        "label": "SKU / item code",
        "group": "Stock",
        "aliases": ("sku", "item code", "stock code", "code", "part number"),
    },
    {
        "key": "opening_balance",
        "label": "Opening balance",
        "group": "Opening balance",
        "aliases": ("opening balance", "opening", "closing balance", "opening amount"),
    },
    {
        "key": "parent_group",
        "label": "Parent group",
        "group": "Group",
        "aliases": ("parent", "parent group", "under", "group under"),
    },
    {
        "key": "financial_year",
        "label": "Financial year",
        "group": "Voucher",
        "aliases": ("financial year", "financialyear", "fy", "year"),
    },
    {
        "key": "record_type",
        "label": "Record type",
        "group": "Voucher",
        "aliases": ("record type", "row type", "data type"),
    },
)

TALLY_MAPPING_FIELD_KEYS: tuple[str, ...] = tuple(
    str(field["key"]) for field in TALLY_MAPPING_FIELDS
)

QUOTATION_SCOPE_STATUSES: tuple[str, ...] = ("draft", "sent", "accepted", "declined", "expired")
