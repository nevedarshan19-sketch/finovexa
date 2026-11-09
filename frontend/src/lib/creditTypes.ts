export interface CreditPage<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface CreditAging {
  "0-30": number;
  "31-60": number;
  "61-90": number;
  "90+": number;
}

export interface CreditSummary {
  as_of: string;
  currency: string;
  total_receivables: number;
  total_payables: number;
  overdue_receivables: number;
  overdue_payables: number;
  available_customer_credit: number;
  customer_advances: number;
  supplier_advances: number;
  customers_on_hold: number;
  customers_over_limit: number;
  customers: number;
  suppliers: number;
  unmatched_bills: number;
  open_alerts: number;
  alert_settings: CreditAlertSettings;
}

export interface CreditAlertSettings {
  utilization_warn_pct: number;
  utilization_critical_pct: number;
  due_soon_days: number;
  overdue_escalation_days: number;
  supplier_due_soon_days: number;
  in_app_enabled: boolean;
  email_enabled: boolean;
  updated_at?: string | null;
}

export interface CreditCustomer {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  gstin: string | null;
  credit_limit: number;
  payment_terms_days: number;
  credit_hold: boolean;
  opening_balance: number;
  opening_balance_date: string | null;
  notes: string | null;
  outstanding: number;
  available_credit: number;
  utilization_pct: number | null;
  risk_status: string;
  overdue: number;
  invoiced: number;
  paid: number;
  credits: number;
  debits: number;
  advance_credit: number;
  invoice_count: number;
  aging: CreditAging;
}

export interface CreditInvoiceRow {
  id: number;
  number: string;
  issue_date: string;
  due_date: string;
  status: string;
  total: number;
  outstanding: number;
  bucket: string | null;
}

export interface CreditAdjustment {
  id: number;
  customer_id: number;
  invoice_id: number | null;
  kind: string;
  number: string;
  amount: number;
  issued_on: string;
  reason: string;
  status: string;
  created_at: string;
}

export interface CreditCustomerDetail extends CreditCustomer {
  invoices: CreditInvoiceRow[];
  adjustments: CreditAdjustment[];
}

export interface CreditLedgerRow {
  date: string;
  type: string;
  reference: string;
  description: string;
  debit: number;
  credit: number;
  balance: number;
}

export interface CreditLedger {
  customer?: { id: number; name: string; gstin: string | null };
  supplier?: { id: number; name: string; gstin: string | null };
  date_from: string | null;
  date_to: string | null;
  opening_balance: number;
  closing_balance: number;
  rows: CreditLedgerRow[];
}

export interface CreditSupplier {
  id: number;
  name: string;
  gstin: string | null;
  email: string | null;
  phone: string | null;
  city: string | null;
  state: string | null;
  payment_terms_days: number;
  credit_limit: number;
  opening_balance: number;
  opening_balance_date: string | null;
  status: string;
  notes: string | null;
  billed: number;
  paid: number;
  payable: number;
  overdue: number;
  advance_paid: number;
  bill_count: number;
  aging: CreditAging;
}

export interface CreditBillRow {
  id: number;
  supplier_id: number | null;
  vendor: string;
  category: string | null;
  bill_number: string | null;
  incurred_on: string;
  due_date: string | null;
  amount: number;
  outstanding: number;
  payment_status: string;
  bucket: string | null;
}

export interface CreditSupplierPayment {
  id: number;
  supplier_id: number;
  expense_id: number | null;
  amount: number;
  method: string;
  reference: string | null;
  paid_on: string;
  status: string;
  note: string | null;
  created_by_user_id: number | null;
  voided_at: string | null;
  void_reason: string | null;
}

export interface CreditSupplierDetail extends CreditSupplier {
  bills: CreditBillRow[];
  payments: CreditSupplierPayment[];
}

export interface CreditAlert {
  id: number;
  kind: string;
  customer_id: number | null;
  supplier_id: number | null;
  invoice_id: number | null;
  expense_id: number | null;
  amount: number;
  due_on: string | null;
  status: string;
  title: string;
  body: string;
  email_sent_at: string | null;
  dismissed_at: string | null;
  created_at: string;
}

export interface CreditReportColumn {
  key: string;
  label: string;
  kind: "text" | "money" | "date" | "int" | "percent";
  width: number;
}

export interface CreditReportCatalogueItem {
  key: string;
  title: string;
  description: string;
  requires: "customer_id" | "supplier_id" | null;
}

export interface CreditReportPayload {
  key: string;
  title: string;
  description: string;
  columns: CreditReportColumn[];
  rows: Record<string, string | number | boolean | null>[];
  totals: Record<string, number>;
  row_count: number;
  date_from: string | null;
  date_to: string | null;
  as_of: string;
  generated_at: string;
  customer?: { id: number; name: string; gstin: string | null };
  supplier?: { id: number; name: string; gstin: string | null };
}
