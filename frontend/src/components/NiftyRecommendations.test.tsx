import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  NiftyRecommendationCard,
  NiftyRecommendationResponse,
} from "../lib/niftyTypes";
import { NiftyRecommendations } from "./NiftyRecommendations";

const state = vi.hoisted(() => ({ payload: null as unknown }));

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: state.payload,
    loading: false,
    error: null,
    reload: () => {},
  }),
}));

const card: NiftyRecommendationCard = {
  symbol: "TCS",
  name: "Tata Consultancy Services",
  sector: "Information Technology",
  classification: "positive_upside",
  signal_label: "Positive upside signal",
  price: 4000,
  price_as_of: "2026-11-06T15:30:00+05:30",
  price_source: "Yahoo Finance (NSE)",
  price_note: "Delayed NSE quote from Yahoo Finance.",
  data_mode: "delayed",
  freshness: "delayed",
  is_stale: false,
  target_price: 4280,
  upside_pct: 7,
  horizon: "3m",
  horizon_label: "3 months",
  confidence: {
    score: 72,
    label: "high",
    label_display: "High",
    explanation: "Technical confidence is not a probability of profit.",
  },
  indicators: {
    available: true,
    closes: 250,
    sma20: 3950,
    sma50: 3880,
    rsi14: 61,
    momentum_1m_pct: 2.4,
    momentum_3m_pct: 6.1,
    volatility_annual_pct: 22,
    high_52w: 4400,
    low_52w: 3200,
    position_52w_pct: 66.7,
    used: ["Latest provider price", "SMA 50"],
  },
  fundamentals: {
    available: false,
    used: false,
    note: "No licensed fundamental data feed is configured.",
  },
  reasons: ["Price is 3.1% above its 50-day average.", "14-day RSI is 61.0 (neutral)."],
  risks: ["Target and confidence come from price history only."],
  analysis_at: "2026-11-06T18:00:00+05:30",
  methodology_version: "nifty50-technical-v1",
};

function response(overrides: Partial<NiftyRecommendationResponse> = {}): NiftyRecommendationResponse {
  return {
    available: true,
    universe: {
      name: "NSE NIFTY 50",
      size: 50,
      analysed: 49,
      constituents: {
        name: "Bundled NSE NIFTY 50 snapshot",
        url: "https://www.nseindia.com",
        retrieved_at: null,
        fallback: true,
        note: "Bundled snapshot.",
        errors: [],
        count: 50,
      },
    },
    criteria: {
      horizon: "3m",
      horizon_label: "3 months",
      min_upside_pct: 5,
      horizons: [
        { key: "1m", label: "1 month", sessions: 21 },
        { key: "3m", label: "3 months", sessions: 63 },
        { key: "6m", label: "6 months", sessions: 126 },
      ],
      classification_note: "Qualifying is a model screen, not a buy rating.",
    },
    counts: { universe: 50, qualifying: 1, no_positive_upside: 48, insufficient_data: 1 },
    matched: { qualifying: 1, no_positive_upside: 48, insufficient_data: 1, total: 50 },
    filters: { q: "", sort: "upside", confidence: null },
    qualifying: [card],
    no_positive_upside: [{ ...card, symbol: "ITC", name: "ITC Limited", upside_pct: -2.1, target_price: 3916 }],
    insufficient_data: [
      {
        ...card,
        symbol: "NEWCO",
        name: "Newly Listed Co",
        classification: "insufficient_data",
        signal_label: "Insufficient data",
        target_price: null,
        upside_pct: null,
        confidence: null,
        indicators: { available: false, closes: 12 },
        risks: ["Only 12 daily closes were available; at least 50 are required."],
      },
    ],
    methodology: {
      version: "nifty50-technical-v1",
      target: "Target = current price × (1 + expected move).",
      upside: "Upside % = ((Target Price − Current Price) / Current Price) × 100.",
      confidence: "Technical score, not a probability.",
      inputs: "A provider quote plus one year of daily closes.",
      fundamentals: "No licensed fundamental feed is configured.",
      analyst_opinions: "No analyst ratings are reproduced.",
    },
    data_quality: {
      quote_source: "Yahoo Finance (NSE)",
      quote_provider: "yahoo",
      quote_mode: "delayed",
      delay_note: "Quotes may be delayed.",
      history_source: "Yahoo Finance (NSE) daily closes",
      session: { state: "closed", label: "Market closed" },
      stale_prices: 0,
      errors: [],
      note: "Missing data moves a stock to the insufficient-data bucket.",
    },
    fundamentals: { available: false, note: "No licensed fundamental feed is configured." },
    disclaimer:
      "Recommendations are informational only and are not investment advice. Targets, upside and confidence are model estimates.",
    generated_at: "2026-11-06T18:00:00+05:30",
    cache_seconds: 600,
    ...overrides,
  };
}

describe("NiftyRecommendations", () => {
  beforeEach(() => {
    state.payload = response();
  });

  it("separates qualifying stocks from no-signal and insufficient-data stocks", () => {
    render(<NiftyRecommendations />);

    expect(screen.getAllByText(/Recommendations are informational only/).length).toBeGreaterThan(0);
    expect(screen.getByText("1 of 50")).toBeInTheDocument();
    expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument();
    expect(screen.getByText("ITC Limited")).toBeInTheDocument();
    expect(screen.getByText("NEWCO")).toBeInTheDocument();
    expect(screen.getByText(/Only 12 daily closes were available/)).toBeInTheDocument();
    expect(screen.getAllByText("No positive upside signal").length).toBeGreaterThan(0);
  });

  it("shows targets, upside and the reasoning behind a recommendation", () => {
    render(<NiftyRecommendations />);

    expect(screen.getByText("Target price")).toBeInTheDocument();
    expect(screen.getByText("+7.00%")).toBeInTheDocument();
    expect(screen.getByText("Why this recommendation")).toBeInTheDocument();
    expect(screen.getAllByText(/Price is 3.1% above its 50-day average/).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/No licensed fundamental data feed is configured/).length,
    ).toBeGreaterThan(0);
  });

  it("never labels a qualifying signal as a buy rating", () => {
    render(<NiftyRecommendations />);

    expect(screen.queryByText(/Strong Buy/i)).not.toBeInTheDocument();
    expect(screen.getByText(/A qualifying signal is not a buy rating/)).toBeInTheDocument();
  });
});
