export type UserRole =
  | "owner"
  | "employee"
  | "developer"
  | "senior_accountant"
  | "junior_accountant"
  | "customer";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  owner_id: number | null;
  is_demo: boolean;
}

export interface AccountingContext {
  portal: "accountant" | "customer";
  role: "senior_accountant" | "junior_accountant" | "customer";
  display_name: string;
  client?: {
    id: number;
    code: string;
    business_name: string;
    status: string;
  } | null;
}

export interface BusinessSummary {
  business_name: string;
  currency: string;
  timezone: string;
}

export interface Profile {
  business_name: string;
  currency: string;
  timezone: string;
  reporting_period: "weekly" | "monthly" | "quarterly";
  min_cash_reserve: number;
  opening_cash_balance: number;
  opening_balance_date: string;
  risk_tolerance: "conservative" | "balanced" | "growth";
  research_interests: string[];
  reminder_tone: "friendly" | "professional" | "firm";
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
  profile: Profile | null;
  business: BusinessSummary | null;
}

export interface MeResponse {
  user: User;
  profile: Profile | null;
  business: BusinessSummary | null;
  accounting: AccountingContext | null;
  demo_mode: boolean;
}

export interface Customer {
  id: number;
  name: string;
  email: string;
  company: string | null;
  phone?: string | null;
  gstin?: string | null;
  billing_address?: string | null;
  state?: string | null;
  state_code?: string | null;
}

export interface Payment {
  id: number;
  invoice_id: number | null;
  invoice_number: string | null;
  customer_name: string | null;
  amount: number;
  currency: string;
  method: string;
  status: string;
  provider: string | null;
  provider_ref: string | null;
  sender_name: string | null;
  note: string | null;
  received_at: string | null;
  created_at: string;
  source:
    | "provider_verified"
    | "provider_simulated"
    | "employee_recorded"
    | "owner_recorded"
    | "ledger";
  recorded_by: string | null;
  recorded_by_role: "owner" | "employee" | null;
  reconciliation_status?: "matched" | "unmatched" | "mismatch" | "not_applicable" | string;
  reconciled_at?: string | null;
  refund_of_payment_id?: number | null;
  refunded_amount?: number;
  refundable_amount?: number;
  suggested_matches?: SuggestedMatch[];
}

export interface InvoiceItem {
  id?: number;
  description: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  name?: string;
  hsn_sac?: string | null;
  unit?: string;
  item_type?: string;
  discount?: number;
  taxable_value?: number;
  gst_rate?: number;
  cgst_amount?: number;
  sgst_amount?: number;
  igst_amount?: number;
  gst_amount?: number;
  final_amount?: number;
  pricing_mode?: string;
  product_id?: number | null;
}

export interface Invoice {
  id: number;
  number: string;
  customer: Customer;
  issue_date: string;
  due_date: string;
  currency: string;
  status: string;
  base_status: string;
  subtotal: number;
  tax: number;
  total: number;
  paid: number;
  outstanding: number;
  aging_days: number;
  aging_bucket: string;
  notes: string | null;
  items: InvoiceItem[];
  payments: Payment[];
  reminders?: InvoiceReminder[];
  created_by: { id: number; name: string; role: "owner" | "employee" } | null;
  pricing_mode?: "exclusive" | "inclusive";
  supply_type?: "intra_state" | "inter_state" | "unverified";
  supply_type_label?: string;
  supplier?: BillingSupplier | null;
  place_of_supply?: { state: string | null; state_code: string | null };
  supply_verified?: boolean;
  discount?: number;
  taxable_value?: number;
  cgst?: number;
  sgst?: number;
  igst?: number;
  other_charges?: number;
  rounding_adjustment?: number;
  round_to_rupee?: boolean;
  terms?: string | null;
  pdf_url?: string;
}

export interface InvoiceReminder {
  id: number;
  status: string;
  channel: string;
  stage?: ReminderStageKey | null;
  body: string;
  delivery_note: string | null;
  created_at: string;
}

export interface EmployeeEntry {
  id: number;
  entry_type: "invoice" | "sale" | "purchase";
  status: "submitted" | "void";
  reference: string;
  counterparty: string;
  counterparty_email: string | null;
  counterparty_phone: string | null;
  description: string;
  category: string | null;
  amount: number;
  currency: string;
  tax_rate: number;
  payment_method: string | null;
  entry_date: string;
  due_date: string | null;
  notes: string | null;
  invoice_id: number | null;
  invoice_number: string | null;
  invoice_status: string | null;
  invoice_total: number | null;
  invoice_paid: number;
  invoice_outstanding: number | null;
  amount_received: number | null;
  collection_status: string | null;
  payment_state: string | null;
  payment_status_label: string | null;
  overpaid_amount: number;
  payment_count: number;
  payment_method_label: string | null;
  payment_reference: string | null;
  payment_date: string | null;
  items: InvoiceItem[];
  expense_id: number | null;
  payment_id: number | null;
  payment: {
    id: number;
    amount: number;
    method: string;
    method_label: string;
    status: string;
    provider: string | null;
    provider_ref: string | null;
    received_at: string | null;
  } | null;
  employee: { id: number; name: string; email: string };
  editable: boolean;
  voidable: boolean;
  lock_reason: string | null;
  created_at: string;
  updated_at: string;
  voided_at: string | null;
}

export interface EmployeeEntrySummary {
  total_entries: number;
  submitted: number;
  voided: number;
  sales_total: number;
  purchases_total: number;
  invoice_count: number;
  sale_count: number;
  purchase_count: number;
  last_entry_at: string | null;
}

export interface EmployeeCollectionSummary {
  currency: string;
  outstanding_total: number;
  overdue_total: number;
  collected_this_month: number;
  collected_today: number;
  collected_today_count: number;
  overpaid_total: number;
  open_invoice_count: number;
  partially_paid_count: number;
  unpaid_count: number;
  paid_count: number;
  overpaid_count: number;
  collection_by_mode: { method: string; label: string; amount: number; count: number }[];
  collection_rate_pct: number | null;
}

export interface EmployeeOverview {
  employee: { id: number; name: string; email: string };
  business: BusinessSummary;
  entries: EmployeeEntry[];
  summary: EmployeeEntrySummary;
  collections: {
    summary: EmployeeCollectionSummary;
    currency_totals: EmployeeCollectionSummary[];
    as_of: string;
    timezone: string;
  };
  permissions: {
    can_generate_invoices: boolean;
    can_edit_entries: boolean;
    can_record_payments: boolean;
    can_edit_payments: boolean;
    can_reverse_payments: boolean;
    owner_dashboard: boolean;
    owner_api_access: boolean;
  };
  note: string;
  as_of: string;
}

export interface EmployeePaymentHistoryRow {
  id: number;
  amount: number;
  currency: string;
  method: string;
  method_label: string;
  reference: string | null;
  note: string | null;
  status: string;
  provider: string | null;
  received_at: string | null;
  created_at: string;
  recorded_by: { id: number; name: string; role: string } | null;
}

export interface EmployeeInvoicePaymentsResponse {
  id: number;
  number: string;
  payment_status_label: string;
  total: number;
  paid: number;
  amount_received: number;
  outstanding: number;
  overpaid_amount: number;
  payment_count: number;
  payment_history: EmployeePaymentHistoryRow[];
}

export interface EmployeeEntriesResponse {
  items: EmployeeEntry[];
  count: number;
  summary: EmployeeEntrySummary;
}

export interface TeamEmployee {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_demo: boolean;
  created_at: string;
  entry_count: number;
}

export interface TeamRoster {
  items: TeamEmployee[];
  count: number;
  login_path: string;
  note: string;
}

export interface TeamEntriesResponse {
  items: EmployeeEntry[];
  count: number;
  summary: EmployeeEntrySummary;
  note: string;
}

export interface ChangeMetric {
  value: number;
  previous: number;
  change_pct: number | null;
}

export interface AgingBucket {
  bucket: string;
  label: string;
  amount: number;
  count: number;
}

export interface Dashboard {
  as_of: string;
  period: { days: number; start: string; end: string };
  currency: string;
  data_mode: string;
  metrics: {
    revenue: ChangeMetric;
    cash_received: ChangeMetric;
    operating_expenses: ChangeMetric;
    gross_profit: ChangeMetric;
    net_profit: ChangeMetric;
    gross_margin_pct: number | null;
    net_margin_pct: number | null;
  };
  receivables: {
    buckets: AgingBucket[];
    total_outstanding: number;
    overdue_total: number;
    current_total: number;
    overdue_count: number;
    top_overdue: Invoice[];
  };
  cash: {
    recorded_balance: number;
    minimum_reserve: number;
    projected_30d: number;
    projected_30d_minimum: number;
    shortfall_date: string | null;
    investable_surplus: number;
    reserve_headroom: number;
    definition: string;
  };
  recovery: {
    recovered_in_period: number;
    awaiting_reconciliation: number;
    pending_amount: number;
    unmatched_confirmed_amount: number;
  };
  upcoming_obligations: Obligation[];
  inventory: InventoryProduct[];
  inventory_risk: { low_stock_count: number; total_inventory_value: number };
  alerts: Alert[];
  recent_payments: Payment[];
  employee_entries: EmployeeEntry[];
  employee_activity: EmployeeEntrySummary & { active_employees: number };
  insights: Insight[];
  ai_summary: { text: string; generated_by: string; mode: string; note: string };
  charts: {
    cash_trend: CashPoint[];
    revenue_expenses: SeriesPoint[];
  };
  paypal: PayPalStatistics & {
    configured: boolean;
    enabled: boolean;
    environment: string;
    mode: string;
    recent: Payment[];
  };
  data_quality: { has_paypal_live: boolean; paypal_mode?: string; note: string };
}

export interface Alert {
  severity: "high" | "medium" | "low" | string;
  title: string;
  detail: string;
  link: string;
}

export interface Obligation {
  id: number;
  name: string;
  category: string;
  amount: number;
  due_date: string;
  days_until?: number;
  recurring: boolean;
  status: string;
  notes?: string | null;
}

export interface InventoryProduct {
  product_id: number;
  name: string;
  sku: string;
  quantity_on_hand: number;
  reorder_level: number;
  inventory_value: number;
  low_stock: boolean;
}

export interface Evidence {
  type: string;
  id: number | string | null;
  label: string;
  amount?: number | string | null;
  date?: string;
  data_mode?: string;
}

export interface Insight {
  id: number;
  agent: string;
  title: string;
  finding: string;
  evidence: Evidence[];
  period_start: string | null;
  period_end: string | null;
  impact_amount: number | null;
  confidence: string;
  limitations: string | null;
  recommended_action: string | null;
  mode: string;
  created_at: string;
}

export interface SeriesPoint {
  date: string;
  revenue: number;
  expenses: number;
}

export interface ExpenseBreakdownPoint {
  category: string;
  amount: number;
  share_pct: number;
}

export interface CashPoint {
  date: string;
  inflow: number;
  outflow: number;
  balance: number;
}

export interface Analytics {
  period: { days: number; start: string; end: string };
  metrics: {
    revenue: ChangeMetric;
    cogs: ChangeMetric;
    gross_profit: ChangeMetric;
    operating_expenses: ChangeMetric;
    net_profit: ChangeMetric;
    gross_margin_pct: number | null;
    net_margin_pct: number | null;
    invoice_count: number;
  };
  series: SeriesPoint[];
  expense_breakdown: { category: string; amount: number; share_pct: number }[];
  products: ProductPerformance[];
  invoices: Invoice[];
  insights: Insight[];
  definitions: Record<string, string>;
}

export interface ProductPerformance {
  product_id: number;
  sku: string;
  name: string;
  units_sold: number;
  revenue: number;
  cogs: number;
  gross_profit: number;
  margin_pct: number;
  inventory_qty: number;
  reorder_level: number;
  inventory_value: number;
  low_stock: boolean;
}

export interface ForecastSeriesPoint {
  date: string;
  inflow: number;
  outflow: number;
  balance: number;
  is_forecast: boolean;
  below_reserve: boolean;
}

export interface Forecast {
  scenario: string;
  scenario_label: string;
  scenario_description: string;
  horizon_days: number;
  as_of: string;
  opening_balance: number;
  closing_balance: number;
  minimum_balance: number;
  minimum_balance_date: string;
  minimum_reserve: number;
  shortfall_date: string | null;
  investable_surplus: number;
  total_expected_inflow: number;
  total_expected_outflow: number;
  at_risk_receivables: number;
  receivables_beyond_horizon: number;
  series: ForecastSeriesPoint[];
  receivables: ExpectedReceivable[];
  outflows: ForecastOutflow[];
  assumptions: {
    method: string;
    collection_probabilities: Record<string, number>;
    probability_multiplier: number;
    overdue_delay_days_adjustment: number;
    daily_expense_basis: number;
    expense_multiplier: number;
    expense_history_days: number;
    minimum_reserve: number;
    data_quality: string;
    receivables_not_guaranteed: boolean;
    note: string;
  };
}

export interface ExpectedReceivable {
  invoice_id: number;
  invoice_number: string;
  customer: string;
  outstanding: number;
  expected_date: string;
  probability: number;
  expected_amount: number;
  bucket: string;
}

export interface ForecastOutflow {
  source: string;
  id: number;
  label: string;
  category: string;
  date: string;
  amount: number;
}

export interface CashflowOverview {
  forecast: Forecast;
  scenarios: {
    key: string;
    label: string;
    description: string;
    closing_balance: number;
    minimum_balance: number;
    minimum_balance_date: string;
    shortfall_date: string | null;
    investable_surplus: number;
    total_expected_inflow: number;
    total_expected_outflow: number;
  }[];
  sensitivity: {
    key: string;
    label: string;
    closing_balance: number;
    minimum_balance: number;
    shortfall_date: string | null;
    investable_surplus: number;
  }[];
  obligations: Obligation[];
  definitions: Record<string, string>;
  data_quality: string;
}

export interface SavedForecast {
  id: number;
  horizon_days: number;
  scenario: string;
  opening_balance: number;
  closing_balance: number;
  minimum_reserve: number;
  shortfall_date: string | null;
  created_at: string;
}

export interface Quote {
  symbol: string;
  name: string;
  asset_class: string;
  exchange: string;
  currency: string;
  unit: string;
  price: number | null;
  previous_close: number | null;
  change_pct: number | null;
  as_of: string | null;
  source: string | null;
  data_mode: string;
  freshness: string;
  is_stale: boolean;
  age_minutes: number | null;
  session_status: string | null;
  sector: string | null;
  note: string | null;
}

export interface MarketOverview {
  items: Quote[];
  groups: { metals: Quote[]; indices: Quote[]; equities: Quote[] };
  summary: {
    live_count: number;
    demo_count: number;
    stale_count: number;
    provider_errors: string[];
    upstox_configured: boolean;
    metals_configured: boolean;
    mode_note: string;
  };
  as_of: string;
}

export interface NewsArticle {
  id: number;
  title: string;
  source: string;
  url: string;
  published_at: string;
  summary: string;
  implications: string | null;
  risks: string | null;
  instruments: string[];
  data_mode: string;
  freshness: string;
  is_stale: boolean;
  age_minutes: number;
  fetched_at: string;
  analysis_note: string;
}

export interface NewsResponse {
  items: NewsArticle[];
  mode: string;
  provider_error: string | null;
  dedupe_note: string;
  provider_note: string;
}

export interface MarketHistory {
  symbol: string;
  currency: string;
  unit: string;
  data_mode: string;
  provider_error: string | null;
  source: string;
  candles: {
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number | null;
  }[];
}

export interface ResearchSignal {
  model_signal: string;
  score: number;
  rationale: string;
  risks: string;
  methodology: string;
  data_quality: string;
  is_model_generated: boolean;
  generated_at: string;
  disclosure: string;
}

export interface ResearchItem {
  symbol: string;
  name: string;
  exchange: string;
  sector: string | null;
  instrument_key: string | null;
  quote: Quote;
  signal: ResearchSignal | null;
  announcements: NewsArticle[];
  analyst_ratings: { items: unknown[]; note: string };
  cash_constraints: {
    recorded_cash: number;
    minimum_reserve: number;
    investable_headroom: number;
    surplus_note: string;
    illustrative_order_value: number;
    illustrative_quantity: number;
    sizing_rule: string;
  };
  data_quality_note: string;
}

export interface ResearchOverview {
  items: ResearchItem[];
  orders: BrokerOrder[];
  risk_profile: { tolerance: string; research_interests: string[]; currency: string };
  cash_context: {
    recorded_cash: number;
    minimum_reserve: number;
    investable_headroom: number;
    projected_minimum_30d: number;
    shortfall_date: string | null;
  };
  broker_status: {
    mode: string;
    upstox_configured: boolean;
    live_trading_enabled: boolean;
    live_trading_ready: boolean;
    static_ip_required: boolean;
    note: string;
  };
  disclosures: string[];
}

export interface StockToken {
  symbol: string;
  name: string;
  sector: string;
  exchange: string;
  instrument_key: string;
  exchange_token: string;
  seeded: boolean;
  research_coverage: boolean;
  signal_available: boolean;
}

export interface StockTokenCatalogue {
  index: string;
  total: number;
  covered: number;
  signals: number;
  items: StockToken[];
  note: string;
  coverage_note: string;
  provider_note: string;
}

export interface Nifty50Stock {
  symbol: string;
  name: string;
  sector: string;
  exchange: string;
  currency: string;
  instrument_key: string;
  exchange_token: string;
  instrument_id: number | null;
  quote: Quote | null;
  signal_available: boolean;
  tradable: boolean;
}

export interface Nifty50Desk {
  index: string;
  total: number;
  tradable: number;
  items: Nifty50Stock[];
  modes: { live: number; demo: number; stale: number; unavailable: number };
  provider: {
    upstox_configured: boolean;
    provider_errors: string[];
    note: string;
  };
  orders_note: string;
  as_of: string;
}

export type SimulatorTrend = "up" | "down" | "sideways";
export type SimulatorBias = "bullish" | "bearish" | "neutral";

export interface SimulatorStock {
  symbol: string;
  name: string;
  sector: string;
  exchange: string;
  currency: string;
  instrument_key: string;
  exchange_token: string;
  price: number;
  previous_close: number;
  open: number;
  day_high: number;
  day_low: number;
  change: number;
  change_pct: number;
  volume: number;
  average_volume: number;
  volume_ratio: number;
  traded_volume: number;
  vwap: number;
  sma5: number;
  sma20: number;
  rsi14: number;
  momentum_pct: number;
  volatility_pct: number;
  support: number;
  resistance: number;
  trend: SimulatorTrend;
  bias: SimulatorBias;
  label: string;
  score: number;
  observations: string[];
  spark: number[];
  data_mode: string;
  disclosure: string;
}

export interface SimulatorMover {
  symbol: string;
  name: string;
  sector: string;
  price: number;
  change_pct: number;
  volume_ratio: number;
  rsi14: number;
  score: number;
  trend: SimulatorTrend;
  label: string;
}

export interface SimulatorSector {
  sector: string;
  count: number;
  change_pct: number;
  advancers: number;
  decliners: number;
  unchanged: number;
  leader_symbol: string;
  leader_change_pct: number;
  laggard_symbol: string;
  laggard_change_pct: number;
}

export interface SimulatorSession {
  mode: string;
  clock: string;
  bar: number;
  total_bars: number;
  tick_seconds: number;
  bar_minutes: number;
  loop_seconds: number;
  real_hours_ist: string;
  note: string;
}

export interface SimulatorIndexPoint {
  time: string;
  level: number;
}

export interface MarketSimulator {
  data_mode: string;
  is_live_market_data: boolean;
  verified_live: boolean;
  source: string;
  index: {
    symbol: string;
    name: string;
    level: number;
    change: number;
    change_pct: number;
    base_level: number;
    history: SimulatorIndexPoint[];
  };
  summary: {
    total: number;
    advancers: number;
    decliners: number;
    unchanged: number;
    breadth_pct: number;
    average_change_pct: number;
    median_change_pct: number;
    mood: string;
    total_volume: number;
    overbought: number;
    oversold: number;
  };
  sectors: SimulatorSector[];
  stocks: SimulatorStock[];
  top_gainers: SimulatorMover[];
  top_losers: SimulatorMover[];
  most_active: SimulatorMover[];
  overbought: SimulatorMover[];
  oversold: SimulatorMover[];
  session: SimulatorSession;
  session_date: string;
  notes: Record<string, string>;
  disclosures: string[];
  as_of: string;
}

export interface SimulatorCandle {
  index: number;
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SimulatorDetail extends SimulatorStock {
  candles: SimulatorCandle[];
  session: SimulatorSession;
  session_date: string;
  notes: Record<string, string>;
  disclosures: string[];
  as_of: string;
}

export interface OptionLeg {
  ltp: number;
  previous_close: number | null;
  change_pct: number | null;
  oi: number | null;
  oi_change: number | null;
  volume: number | null;
  iv: number | null;
  delta: number | null;
  instrument_key: string | null;
  data_mode: string;
}

export interface OptionStrike {
  strike: number;
  is_atm: boolean;
  call: OptionLeg | null;
  put: OptionLeg | null;
}

export interface OptionExpiry {
  date: string;
  label: string;
  kind: string;
  days_to_expiry: number;
}

export interface OptionChain {
  underlying: {
    symbol: string;
    name: string;
    exchange: string;
    currency: string;
    spot: number | null;
    change_pct: number | null;
    as_of: string | null;
    data_mode: string;
    source: string | null;
  };
  expiries: OptionExpiry[];
  selected_expiry: string;
  requested_expiry: string | null;
  expiry_note: string | null;
  data_mode: string;
  verified_live: boolean;
  source: string;
  provider_error: string | null;
  as_of: string;
  underlying_key: string;
  lot_size: number;
  strikes: OptionStrike[];
  summary: {
    atm_strike: number;
    atm_iv: number | null;
    pcr_oi: number | null;
    max_pain: number | null;
    total_call_oi: number;
    total_put_oi: number;
    call_oi_change: number;
    put_oi_change: number;
    support: number | null;
    resistance: number | null;
    strike_step: number | null;
    strikes_used: number;
  };
  notes: Record<string, string>;
}

export interface Approval {
  id: number;
  action_type: string;
  title: string;
  reason: string;
  evidence: Evidence[];
  financial_impact: number | null;
  risk_level: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  status: string;
  expires_at: string;
  decided_at: string | null;
  executed_at: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  can_decide: boolean;
  order?: BrokerOrder | null;
}

export interface BrokerOrderOption {
  underlying: string;
  expiry: string;
  strike: number;
  option_type: "call" | "put";
  instrument_key: string | null;
  symbol: string;
  display_name: string;
  lot_size: number;
  chain_data_mode: string;
}

export interface BrokerOrder {
  id: number;
  approval_id: number;
  instrument_id: number;
  symbol: string | null;
  asset_class: string | null;
  side: string;
  quantity: number;
  lot_size: number;
  option: BrokerOrderOption | null;
  order_type: string;
  limit_price: number | null;
  order_value: number | null;
  quote_price: number | null;
  quote_data_mode: string | null;
  status: string;
  broker: string;
  simulated: boolean;
  execution_mode: "simulated" | "live";
  broker_order_id: string | null;
  broker_status: string | null;
  broker_status_message: string | null;
  order_tag: string | null;
  last_synced_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  type: string;
  id: string;
  label: string;
  source: string;
  data_mode: string;
  url?: string | null;
}

export interface ChatAnswer {
  answer: string;
  verified_facts: string[];
  estimates: string[];
  interpretations: string[];
  uncertainty: string[];
  citations: Citation[];
  followups: string[];
  mode: "llm" | "rules";
  provider_note: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: { text?: string } & Partial<ChatAnswer>;
  citations: Citation[];
  mode: string | null;
  created_at: string;
}

export interface ReminderDraft {
  subject: string;
  body: string;
  sms_body: string;
  channel: "email" | "sms";
  tone: string;
  generated_by: string;
  mode: string;
  facts: Record<string, unknown>;
  note: string;
  recipient: string;
  email: string;
  phone: string | null;
  email_ready: boolean;
  sms_ready: boolean;
  stage?: ReminderStageKey | null;
  stage_label?: string | null;
  stage_description?: string | null;
  current_stage?: ReminderStageKey | null;
}

export type ReminderStageKey =
  | "due_in_7"
  | "due_today"
  | "overdue_1_7"
  | "overdue_8_14"
  | "overdue_15_plus";

export type ReminderTone = "friendly" | "professional" | "firm";
export type ReminderSeverity = "low" | "medium" | "high" | "critical";

export interface ReminderStageLadderTile {
  key: ReminderStageKey;
  label: string;
  description: string;
  tone: ReminderTone;
  severity: ReminderSeverity;
  count: number;
  amount: number;
  reminded_count: number;
  unreminded_count: number;
}

export interface ReminderShareLinks {
  subject: string;
  text: string;
  whatsapp_url: string | null;
  mailto_url: string | null;
  sms_uri: string | null;
}

export interface ReminderScheduleItem {
  invoice: Invoice;
  outstanding: number;
  due_date: string;
  days_until_due: number;
  stage: ReminderStageKey;
  stage_label: string;
  stage_description: string;
  tone: ReminderTone;
  severity: ReminderSeverity;
  reminded: boolean;
  reminded_channels: string[];
  reminder_count: number;
  last_reminder_at: string | null;
  contact: {
    email: string | null;
    phone: string | null;
    email_ready: boolean;
    sms_ready: boolean;
  };
  share: ReminderShareLinks;
}

export interface ReminderSchedule {
  as_of: string;
  window_days: number;
  currency: string;
  summary: {
    actionable_count: number;
    actionable_amount: number;
    reminded_count: number;
    unreminded_count: number;
    not_due_count: number;
    not_due_amount: number;
    by_stage: ReminderStageLadderTile[];
  };
  items: ReminderScheduleItem[];
  note: string;
}

export interface RecoverySummary {
  period: { days: number; start: string; end: string };
  total_outstanding: number;
  overdue_total: number;
  current_total: number;
  recovered_in_period: number;
  confirmed_payments_total: number;
  awaiting_reconciliation: number;
  unmatched_confirmed: number;
  pending_payments: number;
  counts: { open_invoices: number; overdue_invoices: number };
  aging: AgingBucket[];
  priority_invoices: {
    invoice: Invoice;
    priority_score: number;
    reasons: string[];
  }[];
}

export interface SuggestedMatch {
  invoice: Invoice;
  match_reason: string;
  confidence?: string;
}

export interface UnmatchedPayment extends Payment {
  suggested_matches: SuggestedMatch[];
}

export interface DuplicateCheck {
  duplicate_invoices: {
    invoice_a: { id: number; number: string; total: number };
    invoice_b: { id: number; number: string; total: number };
    customer_id: number;
    customer_name: string;
    reason: string;
    confidence: string;
  }[];
  duplicate_payments: {
    payment_a: Payment;
    payment_b: Payment;
    reason: string;
    confidence: string;
  }[];
  checked_at: string;
}

export interface PayPalStatistics {
  currency: string | null;
  gross_received: number;
  verified_received: number;
  simulated_received: number;
  refunded_total: number;
  net_received: number;
  pending_total: number;
  failed_total: number;
  unmatched_confirmed: number;
  mismatch_total: number;
  successful_count: number;
  pending_count: number;
  failed_count: number;
  refund_count: number;
  transaction_count: number;
  note: string;
}

export interface PayPalSeriesPoint {
  date: string;
  received: number;
  refunded: number;
  net: number;
  count: number;
}

export interface PayPalOrderRecord {
  id: number;
  provider_order_id: string | null;
  invoice_id: number | null;
  invoice_number: string | null;
  customer_name: string | null;
  mode: string;
  intent: string;
  status: string;
  amount: number;
  currency: string;
  approve_url: string | null;
  capture_id: string | null;
  capture_status: string | null;
  payer_email: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface PayPalRefundRecord {
  id: number;
  payment_id: number | null;
  refund_payment_id: number | null;
  invoice_id: number | null;
  invoice_number: string | null;
  capture_id: string | null;
  provider_refund_id: string | null;
  request_id: string;
  amount: number;
  currency: string;
  status: string;
  reason: string | null;
  mode: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface PayPalEventRecord {
  id: number;
  event_id: string;
  event_type: string;
  outcome: string;
  verification: string | null;
  user_id: number | null;
  invoice_id: number | null;
  payment_id: number | null;
  details: Record<string, unknown>;
  processed_at: string;
}

export interface ReconciliationHistoryItem {
  id: number;
  payment_id: number;
  invoice_id: number | null;
  status: string;
  reason: string;
  amount_delta: number;
  actor: string;
  created_at: string;
}

export interface ReconciliationSummary {
  matched_count: number;
  matched_amount: number;
  unmatched_count: number;
  unmatched_amount: number;
  mismatch_count: number;
  mismatch_amount: number;
  duplicate_events: number;
  unmatched: UnmatchedPayment[];
  mismatches: UnmatchedPayment[];
  history: ReconciliationHistoryItem[];
  note: string;
}

export interface PaymentOverview {
  provider: {
    name: string;
    configured: boolean;
    enabled: boolean;
    environment: string;
    mode: string;
    mode_label: string;
    note: string;
    webhook_verification: string;
    webhook_configured: boolean;
    client_id_hint: string;
  };
  filters: {
    days: number;
    start: string;
    end: string;
    status: string | null;
    currency: string | null;
  };
  currencies: string[];
  open_invoices: Invoice[];
  payments: Payment[];
  orders: PayPalOrderRecord[];
  open_orders: PayPalOrderRecord[];
  refunds: PayPalRefundRecord[];
  events: PayPalEventRecord[];
  reconciliation: ReconciliationSummary;
  series: PayPalSeriesPoint[];
  statistics: PayPalStatistics;
  summary: {
    confirmed_received_period: number;
    pending_total: number;
    failed_total: number;
    refunded_total: number;
    net_received: number;
    unmatched_confirmed: number;
    mismatch_total: number;
    period_days: number;
    confirmed_note: string;
    pending_note: string;
  };
  webhook_endpoint: string;
}

export interface PayPalSettingsEnvironment {
  environment: "sandbox" | "live";
  label: string;
  credentials_present: boolean;
  client_id_hint: string;
  webhook_configured: boolean;
  base_url: string | null;
}

export interface PayPalSettings {
  provider: "paypal";
  environment: "sandbox" | "live";
  enabled: boolean;
  configured: boolean;
  mode: string;
  mode_label: string;
  active_client_id_hint: string;
  active_webhook_id_hint: string;
  webhook_configured: boolean;
  webhook_signature_verification: boolean;
  webhook_endpoint: string;
  environments: PayPalSettingsEnvironment[];
  updated_at: string | null;
  updated_by: string | null;
  security_note: string;
}

export interface PayPalConnectionCheck {
  connected: boolean;
  status: string;
  mode: string;
  environment: string;
  message: string;
  webhook_configured: boolean;
  details?: Record<string, unknown>;
}

export interface PayPalCaptureResponse {
  mode: string;
  duplicate?: boolean;
  mismatch?: boolean;
  payment: Payment;
  invoice: Invoice | null;
  message: string;
  provider_reference?: string;
}

export interface PayPalRefundResponse {
  mode: string;
  simulation: boolean;
  status: string;
  refund: PayPalRefundRecord;
  refund_payment: Payment | null;
  invoice: Invoice | null;
  refundable_remaining: number;
  message: string;
}

export interface Integration {
  provider: string;
  label: string;
  purpose: string;
  configured: boolean;
  mode: string;
  status: string;
  last_checked_at: string | null;
  setup: string;
  demo_behaviour: string;
  auth_url?: string;
  live_trading_enabled?: boolean;
  live_trading_ready?: boolean;
  static_ip_required?: boolean;
  static_ip_proxy_configured?: boolean;
}

export interface IntegrationsResponse {
  items: Integration[];
  data_modes: { mode: string; meaning: string }[];
  secrets_note: string;
}

export interface RuntimeSettings {
  environment: string;
  demo_mode: boolean;
  demo_reset_enabled: boolean;
  features: {
    llm: { configured: boolean; mode: string; model: string | null };
    paypal: {
      configured: boolean;
      enabled: boolean;
      environment: "sandbox" | "live";
      mode: string;
      webhook_configured: boolean;
      webhook_signature_verification: boolean;
    };
    upstox: {
      configured: boolean;
      live_trading_enabled: boolean;
      live_trading_ready: boolean;
      static_ip_required: boolean;
      static_ip_proxy_configured: boolean;
    };
    market_data: { metals_configured: boolean; news_configured: boolean };
    delivery: {
      email_configured: boolean;
      email_ready: boolean;
      sms_configured: boolean;
      sms_ready: boolean;
    };
  };
  security: {
    token_type: string;
    password_hashing: string;
    secrets_location: string;
    demo_warning: string;
  };
  timezone: string | null;
  currency: string | null;
}

export interface AuditEvent {
  id: number;
  actor: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface PayPalOrderResponse {
  id: string | null;
  local_order_id: number;
  provider_order_id: string | null;
  mode: string;
  status: string;
  approve_url: string | null;
  note: string;
  invoice_id: number;
  invoice_number: string | null;
  customer_name: string | null;
  amount: number;
  currency: string;
  capture_id: string | null;
  capture_status: string | null;
  demo_simulation_available: boolean;
  trust_note: string;
}

export interface DeveloperAccount {
  id: number;
  email: string;
  full_name: string;
  role: "owner" | "employee" | "senior_accountant" | "junior_accountant" | "customer";
  is_active: boolean;
  is_demo: boolean;
  owner_id: number | null;
  owner_email: string | null;
  business_name: string | null;
  created_at: string;
}

export interface DeveloperAccountsResponse {
  items: DeveloperAccount[];
  count: number;
  login_paths: Record<string, string>;
  note: string;
}

export interface DeveloperOverview {
  environment: string;
  developer: { name: string; email: string; account_management: string };
  counts: {
    owners: number;
    employees: number;
    accountants: number;
    customers: number;
    developers: number;
    active_accounts: number;
    inactive_accounts: number;
    auth_events_24h: number;
  };
  features: {
    llm: { configured: boolean; mode: string };
    paypal: { configured: boolean; mode: string };
    upstox: {
      configured: boolean;
      live_trading_enabled: boolean;
      live_trading_ready: boolean;
      static_ip_proxy_configured: boolean;
    };
    market_data: { metals_configured: boolean; news_configured: boolean };
    demo_seed_enabled: boolean;
    public_registration_open: boolean;
  };
  security: {
    password_hashing: string;
    session_type: string;
    secrets_location: string;
    scope: string;
  };
}

export interface DeveloperSecurityEvent {
  id: number;
  action: string;
  actor: string;
  entity_type: string | null;
  entity_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface DeveloperSecurityLog {
  items: DeveloperSecurityEvent[];
  count: number;
  note: string;
}

export interface GSTRate {
  id: number;
  rate: number;
  label: string;
  is_active: boolean;
  is_custom: boolean;
}

export interface BillingSupplier {
  name: string;
  gstin: string | null;
  address: string | null;
  state: string | null;
  state_code: string | null;
}

export interface BillingBusiness {
  business_name: string;
  legal_name: string | null;
  gstin: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  state_code: string | null;
  postal_code: string | null;
  business_phone: string | null;
  business_email: string | null;
  invoice_terms: string | null;
  logo_data_url: string | null;
  currency: string;
}

export interface BillingSettings {
  business: BillingBusiness;
  ready: boolean;
  states: { code: string; name: string }[];
  rates: GSTRate[];
  note: string;
}

export interface BillingCustomer {
  id: number;
  name: string;
  email: string;
  company: string | null;
  phone: string | null;
  gstin: string | null;
  billing_address: string | null;
  billing_address_line1?: string | null;
  billing_address_line2?: string | null;
  city?: string | null;
  state?: string | null;
  state_code?: string | null;
  postal_code?: string | null;
}

export interface BillingProduct {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  hsn_sac: string | null;
  item_type: "goods" | "services";
  unit: string;
  default_gst_rate: number;
  unit_price: number;
  unit_cost: number;
  reorder_level: number;
  quantity_on_hand: number;
  low_stock: boolean;
}

export interface GSTLineInput {
  product_id?: number | null;
  name: string;
  description?: string | null;
  hsn_sac?: string | null;
  unit: string;
  item_type: "goods" | "services";
  quantity: number | string;
  unit_price: number | string;
  discount: number | string;
  gst_rate: number | string;
}

export interface GSTCalculatedLine extends GSTLineInput {
  gross_amount: number;
  taxable_value: number;
  gst_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  final_amount: number;
  pricing_mode: string;
}

export interface GSTTotals {
  subtotal: number;
  discount: number;
  taxable_value: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  tax_amount: number;
  other_charges: number;
  rounding_adjustment: number;
  raw_total: number;
  total_amount: number;
  round_to_rupee: boolean;
  supply_type: "intra_state" | "inter_state";
}

export interface GSTCalculation {
  supplier: BillingSupplier;
  place_of_supply: { state: string | null; state_code: string | null };
  supply_type: "intra_state" | "inter_state";
  supply_type_label: string;
  pricing_mode: "exclusive" | "inclusive";
  lines: GSTCalculatedLine[];
  totals: GSTTotals;
  warnings: string[];
  note: string;
}

export interface BillingOverview {
  counts: { total: number; drafts: number; open: number; overdue: number };
  totals: {
    invoiced: number;
    outstanding: number;
    confirmed_received: number;
    gst_on_invoices: number;
  };
  recent: Invoice[];
  note: string;
}

export interface IndiaQuote {
  price: number | null;
  previous_close: number | null;
  change_pct: number | null;
  day_high: number | null;
  day_low: number | null;
  high_52w: number | null;
  low_52w: number | null;
  volume: number | null;
  currency: string;
  exchange: string;
  as_of: string | null;
  age_minutes: number | null;
  source: string;
  data_mode: string;
  freshness: string;
  is_stale: boolean;
  spark: number[];
  note: string;
}

export interface IndiaMarketRow {
  symbol: string;
  name: string;
  sector: string | null;
  exchange: string;
  currency: string;
  yahoo_symbol: string;
  instrument_key: string | null;
  quote: IndiaQuote | null;
}

export interface IndiaSession {
  state: "open" | "pre_open" | "closed" | string;
  label: string;
  ist_time: string;
  ist_date: string;
  regular_hours: string;
  note: string;
}

export interface IndiaMarketOverview {
  available: boolean;
  data_mode: string;
  source: string | null;
  provider: {
    name: string;
    configured: boolean;
    keyless: boolean;
    upstox_configured: boolean;
    delay_note: string;
    errors: string[];
    stale?: boolean;
  };
  session: IndiaSession;
  indices: IndiaMarketRow[];
  stocks: IndiaMarketRow[];
  coverage: { covered: number; requested: number };
  summary: {
    requested: number;
    covered: number;
    advancers: number;
    decliners: number;
    unchanged: number;
    breadth_pct: number | null;
    average_change_pct: number | null;
    median_change_pct: number | null;
    total_volume: number;
    mood: string | null;
  };
  fetched_at: string;
  cache_seconds: number;
  stale: boolean;
  stale_note?: string;
  notes: Record<string, string>;
  disclosures: string[];
}

export interface IndiaCandle {
  time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
}

export interface IndiaStockDetail {
  symbol: string;
  name: string;
  sector: string | null;
  exchange: string;
  currency: string;
  yahoo_symbol: string;
  instrument_key: string;
  quote: IndiaQuote;
  range: string;
  interval: string;
  candles: IndiaCandle[];
  spark: number[];
  indicators: {
    sma20: number | null;
    sma50: number | null;
    rsi14: number | null;
    high_52w: number | null;
    low_52w: number | null;
    position_52w_pct: number | null;
    samples: number;
  };
  provider: { name: string; delay_note: string; errors: string[] };
  session: IndiaSession;
  data_mode: string;
  source: string;
  fetched_at: string;
  stale: boolean;
  stale_note?: string;
  disclosures: string[];
}

export interface PortfolioHolding {
  symbol: string;
  name: string;
  sector: string | null;
  exchange: string;
  currency: string;
  quantity: number;
  average_cost: number;
  invested: number;
  price: number | null;
  value: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  change_pct: number | null;
  day_change: number | null;
  data_mode: string;
  price_source: string | null;
  price_as_of: string | null;
  is_stale: boolean;
  source: string;
  source_label: string;
  weight_pct: number | null;
}

export interface InvestmentPortfolio {
  holdings: PortfolioHolding[];
  totals: {
    holdings: number;
    priced: number;
    invested: number;
    current_value: number;
    pnl: number;
    pnl_pct: number | null;
    day_change: number;
    recorded_cash: number;
    cash_plus_investments: number;
    currency: string;
  };
  allocation: { sector: string; value: number; count: number; share_pct: number }[];
  data_mode: string;
  price_source: string | null;
  price_as_of: string | null;
  session: IndiaSession | null;
  provider: { name: string | null; delay_note: string | null; errors: string[] };
  sources: Record<string, number>;
  is_simulated: boolean;
  notes: Record<string, string>;
  disclosures: string[];
  generated_at: string;
}

export interface StockRecommendation {
  symbol: string;
  name: string;
  sector: string | null;
  score: number;
  model_signal: string;
  label: string;
  tone: "green" | "blue" | "slate" | "amber" | "red";
  reason: string;
  price: number | null;
  change_pct: number | null;
  data_mode: string;
  price_source: string | null;
  price_as_of: string | null;
  is_model_generated: boolean;
}

export interface RecommendationFeed {
  items: StockRecommendation[];
  summary: {
    ideas: number;
    strong: number;
    watch: number;
    caution: number;
    universe: number;
  };
  headline: string;
  signature: string;
  generated_at: string;
  data_mode: string;
  note: string;
  disclosure: string;
}
