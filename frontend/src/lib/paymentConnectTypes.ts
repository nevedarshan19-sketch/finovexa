export type PaymentProvider = "paypal" | "google_pay" | "bank_statement";
export type ReconciliationStatus =
  | "unverified"
  | "suggested"
  | "matched"
  | "rejected"
  | "not_applicable";

export interface PCConnectionCounts {
  transactions: number;
  matched: number;
  unmatched: number;
  duplicates: number;
  incoming_total: string;
  outgoing_total: string;
}

export interface PCConnection {
  id: number;
  provider: PaymentProvider;
  provider_label: string;
  label: string;
  environment: string;
  mode: string;
  status: string;
  merchant_id: string | null;
  account_hint: string | null;
  outlet_label: string | null;
  permissions: string[];
  consent_at: string | null;
  connected_at: string | null;
  disconnected_at: string | null;
  last_sync_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  note: string | null;
  counts: PCConnectionCounts;
}

export interface PCSyncRun {
  id: number;
  connection_id: number;
  provider: string;
  trigger: string;
  status: string;
  range_start: string | null;
  range_end: string | null;
  fetched: number;
  created: number;
  duplicates: number;
  skipped: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  actor: string | null;
  detail: Record<string, unknown>;
}

export interface PCTransaction {
  id: number;
  connection_id: number;
  client_id: number | null;
  provider: PaymentProvider;
  provider_label: string;
  environment: string;
  external_id: string;
  parent_external_id: string | null;
  direction: "incoming" | "outgoing";
  txn_type: string;
  amount: string;
  fee_amount: string;
  net_amount: string;
  currency: string;
  status: string;
  occurred_on: string | null;
  occurred_at: string | null;
  description: string | null;
  counterparty: string | null;
  reference: string | null;
  provider_reference: string | null;
  source: string;
  import_id: number | null;
  bank_transaction_id: number | null;
  dedupe_hash: string | null;
  duplicate_of_id: number | null;
  reconciliation_status: ReconciliationStatus;
  matched_invoice_id: number | null;
  matched_invoice_number: string | null;
  matched_payment_id: number | null;
  match_score: number | null;
  match_reason: string | null;
  reviewed_by_user_id: number | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  note: string | null;
  outlet_label: string | null;
  accounting_draft_id: number | null;
  accounting_voucher_id: number | null;
  created_at: string | null;
}

export interface PCTransactionList {
  items: PCTransaction[];
  total: number;
  limit: number;
  offset: number;
  summary: { incoming_total: string; outgoing_total: string; rows: number };
}

export interface PCCandidate {
  invoice_id: number;
  invoice_number: string;
  customer_name: string | null;
  outstanding_amount: string;
  issue_date: string | null;
  score: number;
  reason: string;
  existing_payment_id: number | null;
}

export interface PCEvent {
  id: number;
  transaction_id: number;
  action: string;
  actor: string | null;
  actor_user_id: number | null;
  invoice_id: number | null;
  payment_id: number | null;
  note: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export interface PCCapability {
  provider: PaymentProvider;
  label: string;
  history_access: string;
  history_api: string | null;
  requirements: string[];
  limitations: string[];
  costs: string;
}

export interface PCOverview {
  capabilities: PCCapability[];
  connections: PCConnection[];
  summary: {
    transactions: number;
    duplicates: number;
    incoming_total: string;
    outgoing_total: string;
    by_provider: {
      provider: PaymentProvider;
      provider_label: string;
      count: number;
      incoming_total: string;
      outgoing_total: string;
    }[];
  };
  reconciliation: {
    unverified: number;
    suggested: number;
    matched: number;
    rejected: number;
    not_applicable: number;
  };
  recent_syncs: PCSyncRun[];
  last_successful_sync: string | null;
  security_note: string;
}

export interface PCSyncResult extends PCSyncRun {}

export interface PCReconcileResponse {
  transaction: PCTransaction;
  candidates: PCCandidate[];
  result: Record<string, unknown>;
}

export interface PCBankRow {
  row: number;
  txn_date: string | null;
  description: string;
  reference: string | null;
  debit: string;
  credit: string;
  direction: string | null;
  confidence: number;
  issues: string[];
  valid: boolean;
  source: string;
  raw: Record<string, unknown>;
  corrected: boolean;
  duplicate: boolean;
}

export interface PCBankPreview {
  client_id: number;
  account_label: string | null;
  filename: string;
  format: string;
  warnings: string[];
  columns: Record<string, string>;
  rows: PCBankRow[];
  summary: {
    rows: number;
    valid: number;
    uncertain: number;
    duplicates: number;
    total_debit: string;
    total_credit: string;
  };
  note: string;
}

export interface PCBankImport {
  id: number;
  client_id: number;
  connection_id: number | null;
  filename: string;
  account_label: string | null;
  parsing_format: string;
  source_sha256: string;
  row_count: number;
  matched_count: number;
  uncertain_count: number;
  duplicate_count: number;
  status: string;
  note: string | null;
  created_at: string | null;
}

export interface PCBankImportResult {
  import_id: number;
  document_id: number;
  rows: number;
  uncertain: number;
  duplicates_skipped: number;
  warnings: string[];
  encrypted_original: boolean;
  status: string;
}

export interface PCGooglePayEligibility {
  provider: string;
  history_api: boolean;
  transaction_detail_api: boolean;
  tracking_supported: boolean;
  summary: string;
  requirements: string[];
  blocked: string[];
}

export interface PCInvoiceOption {
  id: number;
  number: string;
  customer_name: string | null;
  total: string | number;
  outstanding: string | number;
  issue_date: string | null;
  status: string;
}
