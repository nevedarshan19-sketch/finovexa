import type { AccountingService } from "./accountingTypes";

export interface SoftwareTier {
  id: number;
  key: string;
  label: string;
  turnover_min: number;
  turnover_max: number | null;
  monthly_price: number;
  annual_price: number;
  annual_effective_monthly: number;
  description: string;
  features: string[];
}

export interface SoftwarePricing {
  tiers: SoftwareTier[];
  annual_discount_percent: number;
  annual_discount_configured: boolean;
  billing_options: ("monthly" | "annual")[];
  tax_rate_percent: number;
  tax_note: string;
  note: string;
}

export interface ITRPrice {
  id: number;
  key: string;
  label: string;
  description: string;
  price_min: number;
  price_max: number | null;
  price_note: string | null;
}

export interface ITRPricing {
  items: ITRPrice[];
  note: string;
}

export interface PricingAddon {
  id: number;
  key: string;
  label: string;
  description: string;
  amount: number | null;
  cadence: "annual" | "one_time";
  is_active: boolean;
  priced: boolean;
}

export interface AccountingPricingRules {
  services: AccountingService[];
  business_types: string[];
  turnover_ranges: string[];
  gst_statuses: string[];
  benchmark_percent: number;
  benchmark_note: string;
  quote_validity_days: number;
  tax_rate_percent: number;
  tax_note: string;
  terms: string;
}

export interface AccountingPricingResponse {
  software: SoftwarePricing;
  itr: ITRPricing;
  addons: PricingAddon[];
  accounting: AccountingPricingRules;
  disclosures: string[];
}

export interface QuotationEstimate {
  annual_turnover: number | null;
  benchmark_percent: number;
  indicative_annual_fee: number | null;
  indicative_monthly_equivalent: number | null;
  software_tier: { key: string; label: string; monthly_price: number } | null;
  note: string;
  tax_rate_percent?: number;
  tax_note?: string;
  validity_days?: number;
}

/* ------------------------------------------------------------------ admin */

export interface PricingSettings {
  benchmark_percent: number;
  annual_discount_percent: number;
  quote_validity_days: number;
  tax_rate_percent: number;
  tax_note: string;
  terms: string;
  updated_at: string | null;
  updated_by_user_id: number | null;
}

export interface AdminSoftwareTier extends Omit<SoftwareTier, "annual_effective_monthly"> {
  is_active: boolean;
  sort_order: number;
}

export interface AdminITRPrice extends ITRPrice {
  is_active: boolean;
  sort_order: number;
}

export interface AdminPricingAddon extends Omit<PricingAddon, "priced"> {
  sort_order: number;
}

export interface PriceHistoryRow {
  id: number;
  entity_type: string;
  entity_key: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
  changed_by_user_id: number | null;
  changed_at: string | null;
  note: string | null;
}

export interface AdminPricingResponse {
  settings: PricingSettings;
  software_tiers: AdminSoftwareTier[];
  itr_prices: AdminITRPrice[];
  addons: AdminPricingAddon[];
  history: PriceHistoryRow[];
  note: string;
}
