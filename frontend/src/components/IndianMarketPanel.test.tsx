import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { IndianMarketPanel } from "./IndianMarketPanel";

function quote(price: number, change: number) {
  return {
    price,
    previous_close: price - change,
    change_pct: (change / (price - change)) * 100,
    day_high: price + 4,
    day_low: price - 4,
    high_52w: price * 1.3,
    low_52w: price * 0.7,
    volume: 1_200_000,
    currency: "INR",
    exchange: "NSE",
    as_of: "2026-10-28T15:30:00+05:30",
    age_minutes: 20,
    source: "Yahoo Finance (NSE)",
    data_mode: "delayed",
    freshness: "delayed",
    is_stale: false,
    spark: [price - 6, price - 3, price - 1, price],
    note: "Delayed NSE quote from Yahoo Finance. Not tick-level exchange data.",
  };
}

const indices = [
  {
    symbol: "NIFTY50",
    name: "NIFTY 50",
    sector: null,
    exchange: "NSE",
    currency: "INR",
    yahoo_symbol: "^NSEI",
    instrument_key: null,
    quote: quote(22698.85, -50.9),
  },
  {
    symbol: "BANKNIFTY",
    name: "NIFTY Bank",
    sector: null,
    exchange: "NSE",
    currency: "INR",
    yahoo_symbol: "^NSEBANK",
    instrument_key: null,
    quote: quote(54267.4, 290.1),
  },
  {
    symbol: "SENSEX",
    name: "BSE SENSEX",
    sector: null,
    exchange: "NSE",
    currency: "INR",
    yahoo_symbol: "^BSESN",
    instrument_key: null,
    quote: quote(73246.03, -350.2),
  },
];

const stocks = [
  {
    symbol: "RELIANCE",
    name: "Reliance Industries",
    sector: "Oil Gas & Consumable Fuels",
    exchange: "NSE",
    currency: "INR",
    yahoo_symbol: "RELIANCE.NS",
    instrument_key: "NSE_EQ|INE002A01018",
    quote: quote(1158, -38.2),
  },
  {
    symbol: "TCS",
    name: "Tata Consultancy Services",
    sector: "Information Technology",
    exchange: "NSE",
    currency: "INR",
    yahoo_symbol: "TCS.NS",
    instrument_key: "NSE_EQ|INE467B01029",
    quote: quote(2460, 12.4),
  },
];

const overview = {
  available: true,
  data_mode: "delayed",
  source: "Yahoo Finance (NSE)",
  provider: {
    name: "yahoo",
    configured: true,
    keyless: true,
    upstox_configured: false,
    delay_note: "NSE quotes on Yahoo Finance are unofficial and typically delayed.",
    errors: [],
  },
  session: {
    state: "closed",
    label: "Closed today",
    ist_time: "19:20 IST",
    ist_date: "2026-10-28",
    regular_hours: "09:15–15:30 IST, Monday to Friday",
    note: "NSE trading holidays are not detected by this clock.",
  },
  indices,
  stocks,
  coverage: { covered: 2, requested: 2 },
  summary: {
    requested: 2,
    covered: 2,
    advancers: 1,
    decliners: 1,
    unchanged: 0,
    breadth_pct: 50,
    average_change_pct: 0.1,
    median_change_pct: 0.1,
    total_volume: 2_400_000,
    mood: "Mixed",
  },
  fetched_at: "2026-10-28T19:20:00+05:30",
  cache_seconds: 60,
  stale: false,
  notes: { prices: "Real NSE prices, delayed by the provider." },
  disclosures: ["Delayed market data: informational only."],
};

const detail = {
  symbol: "TCS",
  name: "Tata Consultancy Services",
  sector: "Information Technology",
  exchange: "NSE",
  currency: "INR",
  yahoo_symbol: "TCS.NS",
  instrument_key: "NSE_EQ|INE467B01029",
  quote: stocks[1].quote,
  range: "1d",
  interval: "5m",
  candles: [
    { time: "2026-10-28T09:15:00+05:30", open: 2450, high: 2465, low: 2445, close: 2455, volume: 1000 },
    { time: "2026-10-28T15:30:00+05:30", open: 2455, high: 2470, low: 2450, close: 2460, volume: 1200 },
  ],
  spark: [2455, 2460],
  indicators: {
    sma20: 2285.88,
    sma50: 2256.34,
    rsi14: 79.1,
    high_52w: 3350,
    low_52w: 1976.8,
    position_52w_pct: 35.2,
    samples: 248,
  },
  provider: { name: "yahoo", delay_note: "Delayed quotes.", errors: [] },
  session: overview.session,
  data_mode: "delayed",
  source: "Yahoo Finance (NSE)",
  fetched_at: "2026-10-28T19:20:00+05:30",
  stale: false,
  disclosures: ["Delayed market data: informational only."],
};

vi.mock("../hooks/useApi", () => ({
  useApi: (path: string | null) => {
    if (!path) return { data: null, loading: false, error: null, reload: () => {} };
    if (path.startsWith("/market/india/stocks/")) {
      return { data: detail, loading: false, error: null, reload: () => {} };
    }
    return { data: overview, loading: false, error: null, reload: () => {} };
  },
}));

describe("IndianMarketPanel", () => {
  it("labels real quotes as delayed and lists the NIFTY 50 rows", () => {
    render(<IndianMarketPanel />);
    expect(screen.getByText("NSE market · real data")).toBeInTheDocument();
    expect(screen.getByText("DELAYED")).toBeInTheDocument();
    expect(screen.getByText("NIFTY 50")).toBeInTheDocument();
    expect(screen.getByText("NIFTY Bank")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();
    expect(screen.getByText(/2 advancing|1 advancing/)).toBeInTheDocument();
    expect(screen.getByText(/Source: Yahoo Finance \(NSE\)/)).toBeInTheDocument();
    expect(screen.queryByText(/LIVE/)).not.toBeInTheDocument();
  });

  it("filters rows and opens the provider detail modal", () => {
    render(<IndianMarketPanel />);
    fireEvent.change(screen.getByLabelText("Search NIFTY 50 stocks"), {
      target: { value: "TCS" },
    });
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View" }));
    expect(screen.getByText("Tata Consultancy Services · TCS")).toBeInTheDocument();
    expect(screen.getByText("79.1")).toBeInTheDocument();
    expect(screen.getByText(/Read-only market detail/)).toBeInTheDocument();
  });
});
