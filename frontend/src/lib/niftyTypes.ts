export type NiftyHorizon = "1m" | "3m" | "6m";
export type NiftySort = "upside" | "confidence" | "name";
export type NiftyConfidence = "low" | "medium" | "high";
export type NiftyClassification = "positive_upside" | "no_positive_upside" | "insufficient_data";

export interface NiftyConfidenceDetail {
  score: number;
  label: NiftyConfidence;
  label_display: string;
  explanation: string;
}

export interface NiftyIndicators {
  available: boolean;
  closes: number;
  sma20?: number | null;
  sma50?: number | null;
  rsi14?: number | null;
  momentum_1m_pct?: number | null;
  momentum_3m_pct?: number | null;
  volatility_annual_pct?: number | null;
  high_52w?: number | null;
  low_52w?: number | null;
  position_52w_pct?: number | null;
  used?: string[];
}

export interface NiftyRecommendationCard {
  symbol: string;
  name: string;
  sector: string;
  classification: NiftyClassification;
  signal_label: string;
  price: number | null;
  price_as_of: string | null;
  price_source: string | null;
  price_note?: string | null;
  data_mode: string | null;
  freshness: string | null;
  is_stale: boolean;
  target_price: number | null;
  upside_pct: number | null;
  horizon: NiftyHorizon;
  horizon_label: string;
  confidence: NiftyConfidenceDetail | null;
  indicators: NiftyIndicators;
  fundamentals: { available: boolean; used: boolean; note: string };
  reasons: string[];
  risks: string[];
  analysis_at: string | null;
  methodology_version: string;
}

export interface NiftyRecommendationResponse {
  available: boolean;
  universe: {
    name: string;
    size: number;
    analysed: number;
    constituents: {
      name: string;
      url: string;
      retrieved_at: string | null;
      fallback: boolean;
      note: string;
      errors: string[];
      count: number;
    };
  };
  criteria: {
    horizon: NiftyHorizon;
    horizon_label: string;
    min_upside_pct: number;
    horizons: { key: NiftyHorizon; label: string; sessions: number }[];
    classification_note: string;
  };
  counts: {
    universe: number;
    qualifying: number;
    no_positive_upside: number;
    insufficient_data: number;
  };
  matched: {
    qualifying: number;
    no_positive_upside: number;
    insufficient_data: number;
    total: number;
  };
  filters: { q: string; sort: NiftySort; confidence: NiftyConfidence | null };
  qualifying: NiftyRecommendationCard[];
  no_positive_upside: NiftyRecommendationCard[];
  insufficient_data: NiftyRecommendationCard[];
  methodology: Record<string, string>;
  data_quality: {
    quote_source: string | null;
    quote_provider: string | null;
    quote_mode: string | null;
    delay_note: string | null;
    history_source: string;
    session: { state?: string; label?: string; ist_time?: string } | null;
    stale_prices: number;
    errors: string[];
    note: string;
  };
  fundamentals: { available: boolean; note: string };
  disclaimer: string;
  generated_at: string;
  cache_seconds: number;
}
