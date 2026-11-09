export interface TaxStateOption {
  code: string;
  name: string;
}

export interface HsnClassification {
  id: number;
  code: string;
  description: string;
  kind: "goods" | "services";
  gst_rate: number;
  verified: boolean;
  note: string | null;
}

export interface TaxGstOptions {
  states: TaxStateOption[];
  supplier_state: { name: string | null; code: string | null };
  gst_rates: { rate: number; label: string; active: boolean }[];
  hsn: HsnClassification[];
  hsn_coverage: { invoice_lines: number; lines_without_hsn: number; verified_codes: number };
  note: string;
}

export interface GstLineResult {
  quantity: number;
  unit_price: number;
  gross_amount: number;
  discount: number;
  taxable_value: number;
  gst_rate: number;
  gst_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  final_amount: number;
  pricing_mode: string;
}

export interface GstTotals {
  subtotal: number;
  discount: number;
  taxable_value: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  tax_amount: number;
  other_charges: number;
  rounding_adjustment: number;
  total_amount: number;
}

export interface GstCalculation {
  supply_type: "intra_state" | "inter_state";
  supplier_state: string | null;
  supplier_state_code: string | null;
  place_of_supply_state: string | null;
  place_of_supply_state_code: string | null;
  lines: GstLineResult[];
  totals: GstTotals;
  currency: string;
  status: string;
  note: string;
}

export interface GstReportInvoice {
  id: number;
  number: string;
  issue_date: string;
  status: string;
  pricing_mode: string;
  supply_type: string;
  supply_verified: boolean;
  customer_name: string | null;
  customer_gstin: string | null;
  place_of_supply_state: string | null;
  taxable_value: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  tax_amount: number;
  total_amount: number;
  hsn_codes: string[];
  items_without_hsn: number;
}

export interface GstRateSummary {
  gst_rate: number;
  taxable_value: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  tax_amount: number;
  invoice_count: number;
}

export interface GstHsnSummary {
  hsn_sac: string | null;
  gst_rate: number;
  quantity: number;
  taxable_value: number;
  tax_amount: number;
  line_count: number;
}

export interface GstReport {
  period: { from: string; to: string };
  invoices: GstReportInvoice[];
  totals: {
    invoice_count: number;
    taxable_value: number;
    cgst_amount: number;
    sgst_amount: number;
    igst_amount: number;
    tax_amount: number;
    total_amount: number;
  };
  by_rate: GstRateSummary[];
  by_hsn: GstHsnSummary[];
  warnings: string[];
  note: string;
}

export interface ItcEntry {
  id: number;
  supplier_name: string;
  supplier_gstin: string | null;
  invoice_number: string;
  invoice_date: string;
  taxable_value: number;
  gst_rate: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  eligible_amount: number;
  status: "eligible" | "claimed" | "blocked";
  note: string | null;
}

export interface ItcSummary {
  period: { from: string; to: string };
  entries: ItcEntry[];
  by_status: {
    status: string;
    count: number;
    cgst_amount: number;
    sgst_amount: number;
    igst_amount: number;
    eligible_amount: number;
  }[];
  available_itc: number;
  note: string;
}

export interface NetGst {
  period: { from: string; to: string };
  output_gst: GstReport["totals"];
  input_tax_credit: { available: number; by_status: ItcSummary["by_status"] };
  net_gst: {
    amount: number;
    direction: "payable" | "refundable" | "nil";
    payable: number;
    refundable: number;
  };
  warnings: string[];
  note: string;
}

export interface TaxSlabRow {
  from: number;
  to: number | null;
  rate: number;
  taxable: number;
  tax: number;
}

export interface TaxRuleSet {
  id: number;
  financial_year: string;
  assessment_year: string;
  regime: "new" | "old";
  regime_label: string;
  version: string;
  status: string;
  effective_from: string;
  effective_to: string | null;
  source_note: string | null;
  slabs: { from: number; to: number | null; rate: number }[];
  surcharge_bands: { income_above: number; rate: number }[];
  rebate: { income_limit: number; max_rebate: number; marginal_relief: boolean; note: string | null } | null;
  constants: { code: string; value: number; description: string | null }[];
  deductions: {
    code: string;
    label: string;
    cap_amount: number | null;
    percent_of_basic: number | null;
    allowed: boolean;
    note: string | null;
  }[];
  capital_gains: {
    category: string;
    label: string;
    rate: number;
    exemption_limit: number;
    note: string | null;
  }[];
}

export interface IncomeTaxRules {
  financial_years: string[];
  financial_year: string;
  assessment_year: string;
  rule_sets: TaxRuleSet[];
  disclaimer: string;
  current_financial_year: string;
  today: string;
}

export interface DeductionRow {
  section: string;
  label: string;
  claimed: number;
  allowed: number;
  cap: number | null;
  reason: string | null;
}

export interface IncomeTaxResult {
  financial_year: string;
  assessment_year: string;
  regime: "new" | "old";
  regime_label: string;
  rule_set_id: number;
  rule_version: string;
  rule_source_note: string | null;
  currency: string;
  status: string;
  income: {
    salary: {
      gross_salary: number;
      basic_salary: number;
      hra_received: number;
      hra_exemption: number;
      standard_deduction: number;
      professional_tax: number;
      net_salary: number;
    };
    business: {
      basis: string;
      net_profit: number;
      gross_receipts: number;
      income: number;
    };
    other_income: number;
    capital_gains: {
      equity_stcg: number;
      equity_ltcg: number;
      other_ltcg: number;
      other_stcg: number;
    };
    gross_total_income: number;
  };
  deductions: { items: DeductionRow[]; total: number };
  total_income: number;
  tax: {
    slab_income: number;
    slabs: TaxSlabRow[];
    slab_tax: number;
    rebate_87a: number;
    rebate_marginal_relief: number;
    capital_gains: {
      category: string;
      label: string;
      amount: number;
      exemption: number;
      taxable: number;
      rate: number;
      tax: number;
    }[];
    capital_gains_tax: number;
    tax_before_surcharge: number;
    surcharge_rate: number;
    surcharge: number;
    surcharge_marginal_relief: number;
    cess_rate: number;
    cess: number;
    total_liability: number;
    rounding_adjustment: number;
  };
  effective_rate_pct: number;
  monthly_estimate: number;
  notes: string[];
  disclaimer: string;
}

export interface IncomeTaxComparison {
  financial_year: string;
  assessment_year: string;
  regimes: Record<string, IncomeTaxResult>;
  recommended_regime: "new" | "old";
  savings: number;
  disclaimer: string;
}

export interface TaxEstimateSummary {
  id: number;
  financial_year: string;
  regime: "new" | "old";
  rule_version: string;
  status: "draft" | "approved";
  total_liability: number | string | null;
  total_income: number | string | null;
  approved_by_name: string | null;
  created_at: string;
}

export interface TaxEstimate extends TaxEstimateSummary {
  membership_number: string | null;
  approved_at: string | null;
  approval_note: string | null;
  inputs: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface TaxOverview {
  financial_year: string;
  financial_years: string[];
  gst: NetGst;
  income_tax: {
    estimate_count: number;
    latest: {
      id: number;
      regime: string;
      status: string;
      rule_version: string;
      total_liability: number | string | null;
      approved_by_name: string | null;
    }[];
  };
  empty_inputs: Record<string, unknown>;
  disclaimer: string;
}
