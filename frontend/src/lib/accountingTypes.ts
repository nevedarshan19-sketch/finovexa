export type AccountingServiceKey =
  | "bookkeeping"
  | "gst_accounting"
  | "itr_filing"
  | "bank_reconciliation"
  | "sales_purchase"
  | "payroll"
  | "financial_statements"
  | "tally_support";

export interface AccountingService {
  key: AccountingServiceKey;
  name: string;
  description: string;
  includes: string[];
}

export interface AccountingCatalogue {
  services: AccountingService[];
  business_types: string[];
  turnover_ranges: string[];
  gst_statuses: string[];
  process: string[];
  assurances: string[];
  filing_note: string;
}

export interface AccountingEnquiry {
  id: number;
  reference: string;
  business_name: string;
  contact_name: string;
  email: string;
  phone: string | null;
  business_type: string;
  turnover_range: string;
  gst_status: string;
  services: AccountingServiceKey[];
  monthly_transactions: number | null;
  requirements: string | null;
  status: "new" | "contacted" | "quoted" | "quote_accepted" | "onboarded" | "declined";
  source: string;
  created_at: string;
  assigned_senior_user_id?: number | null;
  internal_notes?: string | null;
  annual_turnover: number | string | null;
  bank_accounts: number | null;
  payroll_required: boolean;
  inventory_required: boolean;
  financial_year: string | null;
  benchmark_annual: number | string | null;
}

export interface QuotationScope {
  service: AccountingServiceKey;
  description: string;
}

export type QuotationStatus =
  | "draft"
  | "approved"
  | "sent"
  | "accepted"
  | "declined"
  | "rejected"
  | "expired";

export type PaymentFrequency = "monthly" | "quarterly" | "annual" | "one_time";

export interface QuotationLine {
  kind: "service" | "addon" | "custom";
  key: string | null;
  label: string;
  description: string | null;
  service: AccountingServiceKey | null;
  amount: number | string;
  cadence: "annual" | "one_time";
}

export interface AccountingQuotation {
  id: number;
  number: string;
  enquiry_id: number | null;
  client_id: number | null;
  currency: string;
  amount: string | number;
  billing_cadence: PaymentFrequency;
  scope: QuotationScope[];
  terms: string | null;
  valid_until: string | null;
  status: QuotationStatus;
  accepted_at: string | null;
  responded_at: string | null;
  response_note: string | null;
  created_at: string;
  prepared_by_user_id?: number;
  enquiry_reference?: string;
  enquiry?: {
    reference: string;
    business_name: string;
    contact_name: string;
    email: string;
    phone: string | null;
    business_type: string;
    turnover_range: string;
    gst_status: string;
    services: string[];
    monthly_transactions: number | null;
    annual_turnover: number | string | null;
    bank_accounts: number | null;
    payroll_required: boolean;
    inventory_required: boolean;
    financial_year: string | null;
    benchmark_annual: number | string | null;
  } | null;
  client_name?: string | null;
  line_items: QuotationLine[];
  annual_turnover: number | string | null;
  benchmark_annual: number | string | null;
  subtotal_annual: number | string;
  total_annual: number | string;
  monthly_equivalent: number | string;
  discount_type: "none" | "percent" | "amount";
  discount_value: number | string;
  discount_amount: number | string;
  payment_frequency: PaymentFrequency;
  validity_days: number | null;
  tax_rate_percent: number | string;
  tax_note: string | null;
  approved_at: string | null;
  sent_at: string | null;
  rejected_at: string | null;
  rejection_note: string | null;
  prepared_by_name?: string | null;
  approved_by_name?: string | null;
  rejected_by_name?: string | null;
  discount_note?: string | null;
}

export interface QuotationWorkspaceRequest extends AccountingEnquiry {
  estimate: import("./pricingTypes").QuotationEstimate;
  quotations: AccountingQuotation[];
}

export interface CustomerQuotationRequest extends AccountingEnquiry {
  estimate: import("./pricingTypes").QuotationEstimate;
}

export interface QuotationWorkspace {
  counts: {
    new_requests: number;
    draft: number;
    approved: number;
    sent: number;
    accepted: number;
    declined: number;
    rejected: number;
    expired: number;
    total: number;
  };
  pipeline: { pending_value: number; accepted_value: number };
  requests: QuotationWorkspaceRequest[];
  quotations: AccountingQuotation[];
  catalogue: {
    services: AccountingService[];
    addons: import("./pricingTypes").PricingAddon[];
    business_types: string[];
    gst_statuses: string[];
    turnover_ranges: string[];
    benchmark_note: string;
  };
  settings: import("./pricingTypes").PricingSettings;
  statuses: QuotationStatus[];
}

export interface AccountingClient {
  id: number;
  code: string;
  business_name: string;
  contact_name: string;
  email: string;
  phone: string | null;
  business_type: string;
  turnover_range: string;
  gst_status: string;
  gstin: string | null;
  pan_last4: string | null;
  financial_year: string;
  service_package: string;
  status: "onboarding" | "active" | "paused" | "archived";
  customer_user_id: number | null;
  business_profile_id: number | null;
  linked_business: {
    id: number;
    business_name: string;
    gstin: string | null;
    city: string | null;
    state: string | null;
  } | null;
  senior_accountant_user_id: number | null;
  assigned_junior_user_id: number | null;
  senior_name: string | null;
  junior_name: string | null;
  onboarded_at: string | null;
  notes: string | null;
  created_at: string;
  counts?: {
    open_tasks: number;
    documents: number;
    invoices: number;
    reports: number;
  };
  billing?: {
    invoiced: number;
    paid: number;
    outstanding: number;
    overdue: number;
  };
}

export type AccountingTaskStatus =
  | "unassigned"
  | "assigned"
  | "in_progress"
  | "submitted"
  | "changes_requested"
  | "approved"
  | "delivered"
  | "cancelled";

export interface AccountingTask {
  id: number;
  client_id: number;
  client_name: string | null;
  client_code: string | null;
  title: string;
  description: string | null;
  service_type: AccountingServiceKey;
  status: AccountingTaskStatus;
  priority: "low" | "normal" | "high" | "urgent";
  due_date: string | null;
  assigned_to_user_id: number | null;
  assignee_name: string | null;
  progress: number;
  submitted_at: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  delivered_at: string | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
  comments?: {
    id: number;
    author_label: string;
    body: string;
    created_at: string;
  }[];
}

export interface AccountingDocument {
  id: number;
  client_id: number;
  category: string;
  title: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  visibility: "internal" | "shared";
  source: string;
  status: "received" | "verified" | "rejected";
  note: string | null;
  verified_at: string | null;
  created_at: string;
  download_url: string | null;
}

export interface AccountingDocumentRequest {
  id: number;
  client_id: number;
  title: string;
  description: string | null;
  due_date: string | null;
  status: "pending" | "fulfilled" | "cancelled";
  fulfilled_document_id: number | null;
  fulfilled_at: string | null;
  created_at: string;
}

export interface AccountingReport {
  id: number;
  client_id: number;
  client_name: string | null;
  report_type: "monthly_summary" | "gstr1" | "gstr3b" | "financials";
  financial_year: string;
  period_label: string;
  status: "draft" | "changes_requested" | "approved" | "delivered";
  version: number;
  review_notes: string | null;
  approved_at: string | null;
  delivered_at: string | null;
  created_at: string;
  payload?: Record<string, unknown>;
}

export interface ServiceInvoicePayment {
  id: number;
  amount: number;
  method: string;
  reference: string | null;
  received_on: string;
}

export interface ServiceInvoice {
  id: number;
  client_id: number;
  client_name: string | null;
  number: string;
  issue_date: string;
  due_date: string;
  period_label: string | null;
  subtotal: number;
  tax_amount: number;
  total_amount: number;
  paid_amount: number;
  outstanding_amount: number;
  currency: string;
  status: "issued" | "part_paid" | "paid" | "void";
  notes: string | null;
  is_overdue: boolean;
  payments: ServiceInvoicePayment[];
  created_at: string;
}

export type VoucherType = "sale" | "purchase" | "journal" | "payment" | "receipt" | "expense";

export interface AccountingVoucher {
  id: number;
  client_id: number;
  voucher_type: VoucherType;
  number: string;
  voucher_date: string;
  party_name: string;
  party_gstin: string | null;
  ledger_name: string;
  bank_ledger: string | null;
  category: string | null;
  description: string | null;
  taxable_value: number;
  gst_rate: number;
  inter_state: boolean;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_amount: number;
  source: string;
  status: string;
  created_at: string;
}

export interface VoucherListResponse {
  items: AccountingVoucher[];
  totals: {
    sales: number;
    purchases: number;
    gst_output: number;
    gst_input: number;
  };
}

export interface BankTransaction {
  id: number;
  import_id: number;
  txn_date: string | null;
  description: string;
  reference: string | null;
  debit: number;
  credit: number;
  status: "unmatched" | "suggested" | "matched";
  matched_voucher_id: number | null;
  match_score: number | null;
  match_note: string | null;
}

export interface BankImport {
  id: number;
  client_id: number;
  filename: string;
  row_count: number;
  matched_count: number;
  status: string;
  note: string | null;
  created_at: string;
  transactions: BankTransaction[];
}

export interface TallyBatch {
  id: number;
  client_id: number;
  direction: "import" | "export";
  filename: string;
  format: string;
  row_count: number;
  valid_count: number;
  duplicate_count: number;
  error_count: number;
  status: string;
  details: Record<string, unknown>;
  created_at: string;
}

export type TallyExportTypeKey =
  | "sales"
  | "purchase"
  | "payment"
  | "receipt"
  | "expense"
  | "ledger_masters"
  | "stock_masters";

export type TallyExportStatus = "draft" | "pending_approval" | "approved" | "rejected";

export type TallyImportStatus = "not_imported" | "imported" | "partially_imported" | "failed";

export interface TallyValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  voucher_type?: string;
  voucher_number?: string;
  voucher_date?: string;
  field?: string;
  expected?: string;
  stored?: string;
}

export interface TallyValidationCheck {
  key: string;
  label: string;
  status: "passed" | "failed";
  detail: string;
}

export interface TallyTypeSummary {
  export_type: TallyExportTypeKey;
  label: string;
  voucher_count: number;
  taxable_value: string;
  cgst: string;
  sgst: string;
  igst: string;
  total: string;
  debit_total: string;
  credit_total: string;
}

export interface TallyValidationReport {
  ok: boolean;
  client_id: number;
  client_name: string;
  client_gstin: string | null;
  export_types: TallyExportTypeKey[];
  period: { from: string | null; to: string | null };
  summary: {
    voucher_count: number;
    entry_count: number;
    ledger_count: number;
    stock_item_count: number;
    debit_total: string;
    credit_total: string;
    balanced: boolean;
    by_type: TallyTypeSummary[];
  };
  checks: TallyValidationCheck[];
  errors: TallyValidationIssue[];
  warnings: TallyValidationIssue[];
  error_count: number;
  warning_count: number;
  checked_at: string;
  note: string;
}

export type TallyExportFormat = "xlsx" | "csv_zip" | "xml" | "json";

export interface TallyExportBatch {
  id: number;
  client_id: number;
  client_name: string | null;
  export_types: TallyExportTypeKey[];
  type_labels: string[];
  file_format: TallyExportFormat;
  tally_version: string | null;
  period_from: string | null;
  period_to: string | null;
  filename: string;
  file_sha256: string | null;
  file_size: number;
  row_count: number;
  voucher_count: number;
  master_count: number;
  error_count: number;
  warning_count: number;
  status: TallyExportStatus;
  prepared_by_user_id: number | null;
  prepared_by: string | null;
  approved_by_user_id: number | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_note: string | null;
  import_status: TallyImportStatus;
  import_note: string | null;
  created_at: string | null;
  details: Record<string, unknown>;
  download_url: string | null;
  validation?: TallyValidationReport;
}

export interface TallyExportList {
  items: TallyExportBatch[];
  pending_approval_count: number;
}

export interface TallyExportCatalog {
  client_id: number;
  client_name: string;
  client_gstin: string | null;
  types: {
    key: TallyExportTypeKey;
    label: string;
    record_count: number | null;
    kind: "vouchers" | "masters";
  }[];
  stock_item_count: number;
  formats: { key: TallyExportFormat; label: string }[];
  tally_versions: { key: string; formats: string[] }[];
  import_statuses: { key: TallyImportStatus; label: string }[];
  note: string;
}

export interface TallyStockItem {
  id: number;
  client_id: number;
  name: string;
  sku: string;
  unit: string;
  hsn_sac: string | null;
  gst_rate: number;
  opening_qty: number;
  opening_rate: number;
  opening_value: number;
  is_active: boolean;
  created_at: string | null;
}

export type TallyMigrationFormat = "xlsx" | "xls" | "csv" | "xml" | "json";
export type TallyMigrationStatus =
  | "validated"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "imported"
  | "partially_imported"
  | "failed"
  | "rolled_back";

export interface TallyMigrationCatalog {
  versions: { key: string; formats: string[] }[];
  formats: { key: TallyMigrationFormat; label: string }[];
  import_types: { key: string; label: string }[];
  statuses: TallyMigrationStatus[];
  mapping_fields: { key: string; label: string; group: string; aliases: string[] }[];
  notes: string[];
}

export interface TallyMigrationPreview {
  file_format: TallyMigrationFormat;
  row_count: number;
  headers: string[];
  sample: Record<string, unknown>[];
  suggested_mapping: Record<string, string>;
  note: string | null;
  supported_versions: Record<string, string[]>;
  mapping_fields: { key: string; label: string; group: string; aliases: string[] }[];
  limits: { max_records: number; max_upload_mb: number };
}

export interface TallyMigrationCheck {
  code: string;
  label: string;
  status: "passed" | "failed";
  detail: string;
  count: number;
}

export interface TallyMigrationIssue {
  row: number;
  record_type: string;
  code: string;
  severity: "error" | "warning" | "duplicate";
  message: string;
  voucher_type?: string | null;
  voucher_number?: string | null;
  voucher_date?: string | null;
}

export interface TallyMigrationValidation {
  ok: boolean;
  counts: {
    detected: number;
    valid: number;
    warnings: number;
    errors: number;
    duplicates: number;
  };
  checks?: TallyMigrationCheck[];
  issues?: TallyMigrationIssue[];
  batch_errors?: { code: string; message: string }[];
  missing_ledgers?: string[];
  unmatched_parties?: string[];
  totals?: {
    debit: string;
    credit: string;
    difference: string;
    opening_debit: string;
    opening_credit: string;
    stock_value: string;
  };
  statuses?: Record<string, string>;
  note?: string;
}

export interface TallyMigrationRow {
  id: number;
  row_number: number;
  record_type: string;
  status: string;
  problems: { code: string; message: string; severity: string }[];
  mapped: Record<string, unknown>;
}

export interface TallyMigrationBatch {
  id: number;
  client_id: number;
  client_name: string | null;
  direction: string;
  tally_version: string | null;
  financial_year: string;
  period_from: string | null;
  period_to: string | null;
  opening_date: string | null;
  import_type: string;
  import_type_label: string | null;
  file_format: TallyMigrationFormat;
  filename: string;
  file_size: number;
  file_sha256: string | null;
  row_count: number;
  valid_count: number;
  warning_count: number;
  error_count: number;
  duplicate_count: number;
  imported_count: number;
  status: TallyMigrationStatus;
  prepared_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_note: string | null;
  rolled_back_at: string | null;
  rolled_back_by: string | null;
  mapping: Record<string, string>;
  mapping_template_id: number | null;
  details: Record<string, unknown>;
  retained_until: string | null;
  created_at: string | null;
  updated_at: string | null;
  validation?: TallyMigrationValidation;
  rows?: TallyMigrationRow[];
}

export interface TallyMigrationBatchList {
  items: TallyMigrationBatch[];
  pending_approval_count: number;
}

export interface TallyMappingTemplate {
  id: number;
  name: string;
  client_id: number | null;
  file_format: TallyMigrationFormat;
  import_type: string;
  mapping: Record<string, string>;
  is_shared: boolean;
  created_at: string | null;
}

export interface TallyOpeningBalanceLine {
  id: number;
  ledger_name: string;
  group_name: string | null;
  party_type: string;
  debit: number;
  credit: number;
  stock_item: string | null;
  quantity: number | null;
  rate: number | null;
  value: number;
}

export interface TallyOpeningBalance {
  id: number;
  client_id: number;
  financial_year: string;
  opening_date: string | null;
  status: string;
  total_debit: number;
  total_credit: number;
  stock_value: number;
  approved_at: string | null;
  approved_by_user_id: number | null;
  details: Record<string, unknown>;
  lines: TallyOpeningBalanceLine[];
  created_at: string | null;
}

export interface TallyReportAmountRow {
  ledger: string;
  group: string;
  amount: number;
}

export interface TallyTrialRow {
  ledger: string;
  group: string;
  opening_debit: number;
  opening_credit: number;
  debit: number;
  credit: number;
  closing_debit: number;
  closing_credit: number;
}

export interface TallyTrialBalance {
  rows: TallyTrialRow[];
  totals: {
    opening_debit: number;
    opening_credit: number;
    debit: number;
    credit: number;
    closing_debit: number;
    closing_credit: number;
    difference: number;
  };
}

export interface TallyVoucherSummary {
  count: number;
  total: number;
  taxable: number;
  gst: number;
  months: { month: string; count: number; amount: number; taxable: number; gst: number }[];
}

export interface TallyGstBlock {
  count: number;
  taxable: number;
  cgst: number;
  sgst: number;
  igst: number;
  total_tax: number;
}

export interface TallyHistoricalReport {
  client_id: number;
  client_name: string;
  financial_year: string;
  available_years: string[];
  source: string;
  source_note: string;
  counts: {
    vouchers: number;
    ledger_lines: number;
    ledgers: number;
    approved_batches: number;
    opening_balance: boolean;
  };
  live: { vouchers: number; total: number; label: string };
  trial_balance: TallyTrialBalance;
  profit_loss: {
    revenue: TallyReportAmountRow[];
    expenses: TallyReportAmountRow[];
    revenue_total: number;
    expense_total: number;
    net_profit: number;
    note: string;
  };
  balance_sheet: {
    assets: TallyReportAmountRow[];
    liabilities: TallyReportAmountRow[];
    asset_total: number;
    liability_total: number;
    difference: number;
    unclassified_ledgers: string[];
    note: string;
  };
  sales: TallyVoucherSummary;
  purchases: TallyVoucherSummary;
  expenses: TallyVoucherSummary;
  credit_notes: TallyVoucherSummary;
  debit_notes: TallyVoucherSummary;
  outstanding: {
    customers: { party: string; amount: number }[];
    suppliers: { party: string; amount: number }[];
    customer_total: number;
    supplier_total: number;
  };
  gst: {
    output: TallyGstBlock;
    credit_notes: TallyGstBlock;
    input: TallyGstBlock;
    debit_notes: TallyGstBlock;
    net_output_tax: number;
    net_input_tax: number;
    net_payable: number;
    note: string;
  };
  monthly: { month: string; revenue: number; purchases: number; expenses: number; profit: number }[];
  generated_at: string;
  comparison?: TallyComparisonRow[];
}

export interface TallyComparisonRow {
  financial_year: string;
  vouchers: number;
  revenue: number;
  expenses: number;
  net_profit: number;
  sales: number;
  purchases: number;
  assets: number;
  liabilities: number;
  gst: number;
}

export interface TallyLedgerHistory {
  ledger: string;
  financial_year: string;
  opening_debit: number;
  opening_credit: number;
  closing: number;
  closing_type: string;
  entries: {
    date: string;
    voucher_type: string;
    number: string;
    narration: string | null;
    party: string | null;
    debit: number;
    credit: number;
    balance: number;
    balance_type: string;
  }[];
}

export interface AccountingMessage {
  id: number;
  client_id: number;
  author_label: string;
  author_role: string;
  body: string;
  created_at: string;
}
export interface AccountingNotification {
  id: number;
  client_id: number | null;
  kind: string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
}

export interface NotificationList {
  items: AccountingNotification[];
  unread_count: number;
}

export interface AccountantOption {
  id: number;
  name: string;
  email: string;
  role: string;
  open_tasks: number;
  clients: number;
}

export interface SeniorOverview {
  financial_year: string;
  filters: { client_id: number | null; status: string | null };
  clients: { total: number; active: number; onboarding: number; unassigned_junior: number };
  enquiries: { new: number; total: number; pending_quotations: number };
  tasks: {
    total: number;
    unassigned: number;
    assigned: number;
    in_progress: number;
    submitted: number;
    changes_requested: number;
    approved: number;
    delivered: number;
    overdue: number;
  };
  awaiting_review: number;
  work_in_progress: number;
  upcoming_deadlines: AccountingTask[];
  overdue_tasks: AccountingTask[];
  workload: { user_id: number; name: string; open_tasks: number; clients: number; submitted: number }[];
  billing: {
    invoiced: number;
    paid: number;
    outstanding: number;
    overdue: number;
    overdue_count: number;
    invoice_count: number;
  };
  performance: { completed_this_fy: number; on_time: number };
  monthly_series: { period: string; sales: number; purchases: number }[];
  recent_activity: {
    id: number;
    action: string;
    actor: string;
    detail: Record<string, unknown>;
    created_at: string | null;
  }[];
}

export interface JuniorWorkspace {
  accountant: { id: number; name: string; role: string };
  clients: AccountingClient[];
  tasks: AccountingTask[];
  counts: {
    clients: number;
    open_tasks: number;
    in_progress: number;
    submitted: number;
    changes_requested: number;
    approved: number;
    overdue: number;
  };
  upcoming_deadlines: AccountingTask[];
  documents_pending: number;
  notifications: NotificationList;
}

export interface ClientDetailResponse {
  client: AccountingClient;
  tasks: AccountingTask[];
  documents: AccountingDocument[];
  document_requests: AccountingDocumentRequest[];
  reports?: AccountingReport[];
  invoices?: ServiceInvoice[];
  vouchers: {
    count: number;
    sales?: number;
    purchases?: number;
    recent: AccountingVoucher[];
  };
  messages: AccountingMessage[];
}

export type BusinessTransactionType = "sale" | "receipt" | "refund" | "expense";

export type BusinessInboxStatus =
  | "not_synced"
  | "pending"
  | "drafted"
  | "needs_attention"
  | "ignored"
  | "posted";

export interface BusinessSummary {
  linked: boolean;
  client_id: number;
  business: {
    id: number;
    business_name: string;
    legal_name: string | null;
    gstin: string | null;
    city: string | null;
    state: string | null;
    currency: string;
  } | null;
  as_of?: string;
  period?: { days: number; start: string; end: string };
  currency?: string;
  metrics?: {
    revenue: number | string;
    cash_received: number | string;
    expenses: number | string;
    gross_profit: number | string;
    net_profit: number | string;
    gross_margin_pct: number | null;
    net_margin_pct: number | null;
    invoice_count: number;
  };
  receivables?: {
    total_outstanding: number | string;
    overdue_total: number | string;
    current_total: number | string;
    overdue_count: number;
  };
  cash?: { recorded_balance: number | string; minimum_reserve: number | string };
  inventory?: { item_count: number; total_value: number | string; low_stock_count: number };
  counts?: { invoices: number; payments: number; refunds: number; expenses: number; total: number };
  integration?: {
    status: string;
    last_synced_at: string | null;
    inbox: Record<"pending" | "drafted" | "needs_attention" | "ignored" | "posted" | "total", number>;
    drafts: Record<"draft" | "pending_review" | "approved" | "rejected" | "posted" | "total", number>;
  };
  tally?: {
    voucher_count: number;
    integration_vouchers: number;
    export_count: number;
    last_export_at: string | null;
    last_export_status: string | null;
    note: string;
  };
  note: string;
}

export interface BusinessTransaction {
  source_type: "invoice" | "payment" | "expense";
  source_id: number;
  transaction_type: BusinessTransactionType;
  date: string;
  financial_year: string;
  reference: string;
  party_name: string;
  party_gstin: string | null;
  category: string | null;
  narration: string | null;
  currency: string;
  taxable_value: number | string;
  tax_amount: number | string;
  total_amount: number | string;
  source_status: string;
  accounting: {
    inbox_id: number | null;
    inbox_status: BusinessInboxStatus;
    draft_id: number | null;
    draft_number: string | null;
    draft_status: "draft" | "pending_review" | "approved" | "rejected" | "posted" | null;
    voucher_id: number | null;
    voucher_number: string | null;
  };
}

export interface BusinessTransactionList {
  linked: boolean;
  business: BusinessSummary["business"];
  items: BusinessTransaction[];
  total: number;
  limit: number;
  offset: number;
  summary: Record<BusinessTransactionType, { count: number; total: number | string }> & {
    net_total: number | string;
  };
  note: string;
}

export interface GstSummary {
  output: { taxable: number; cgst: number; sgst: number; igst: number; total: number };
  itc: { taxable: number; cgst: number; sgst: number; igst: number; total: number };
  output_tax: number;
  itc_tax: number;
  net_payable: number;
  credit_carried_forward: number;
  direction: "payable" | "refund" | "nil";
}

export interface Gstr1Row {
  party: string;
  gstin: string | null;
  rate: number;
  supply_type: string;
  invoice_numbers: string[];
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  invoice_value: number;
}

export interface GstWorking {
  period: string;
  period_start: string;
  period_end: string;
  voucher_count: number;
  summary: GstSummary;
  gstr1: {
    b2b: Gstr1Row[];
    b2cs: Gstr1Row[];
    total_taxable: number;
    total_invoices: number;
  };
  gstr3b: {
    outward: GstSummary["output"];
    itc: GstSummary["itc"];
    net_payable: number;
    credit_carried_forward: number;
    itc_at_risk: number;
  };
  mismatches: { voucher: string; severity: string; title: string; detail: string }[];
  filing_status: string;
  filing_note: string;
}

export interface BillExtract {
  filename: string;
  client_id: number;
  fields: {
    invoice_number: string | null;
    invoice_date: string | null;
    party_gstin: string | null;
    taxable_value: number | null;
    tax_amount: number | null;
    total_amount: number | null;
    gst_rate: number | null;
    suggested_ledger: string | null;
    confidence: Record<string, string>;
  };
  warnings: string[];
  saved: boolean;
  requires_human_verification: boolean;
  source_text_preview: string;
  note: string;
}

export interface CustomerOverview {
  linked: boolean;
  message?: string;
  client?: {
    id: number;
    code: string;
    business_name: string;
    contact_name: string;
    service_package: string;
    status: string;
    financial_year: string;
    gstin: string | null;
    senior_name: string | null;
    junior_name: string | null;
  };
  tasks?: {
    id: number;
    title: string;
    service_type: AccountingServiceKey;
    status: AccountingTaskStatus;
    priority: string;
    due_date: string | null;
    progress: number;
    days_remaining: number | null;
    delivered_at: string | null;
    update_note: string | null;
  }[];
  counts?: {
    active_tasks: number;
    awaiting_documents: number;
    approved_reports: number;
    outstanding_invoices: number;
    overdue_tasks: number;
  };
  document_requests?: AccountingDocumentRequest[];
  reports?: AccountingReport[];
  invoices?: ServiceInvoice[];
  documents?: AccountingDocument[];
  messages?: AccountingMessage[];
  notifications?: NotificationList;
}

export interface AuditRow {
  id: number;
  actor: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}
