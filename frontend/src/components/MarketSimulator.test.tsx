import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarketSimulator } from "./MarketSimulator";

vi.mock("../hooks/useApi", () => {
  const stock = {
    symbol: "RELIANCE",
    name: "Reliance Industries",
    sector: "Oil Gas & Consumable Fuels",
    exchange: "NSE",
    currency: "INR",
    instrument_key: "NSE_EQ|INE002A01018",
    exchange_token: "2885",
    price: 1502.5,
    previous_close: 1485,
    open: 1488,
    day_high: 1510,
    day_low: 1480,
    change: 17.5,
    change_pct: 1.18,
    volume: 900000,
    average_volume: 800000,
    volume_ratio: 1.13,
    traded_volume: 12000000,
    vwap: 1499.2,
    sma5: 1495.4,
    sma20: 1490.1,
    rsi14: 62.4,
    momentum_pct: 0.84,
    volatility_pct: 1.1,
    support: 1483.5,
    resistance: 1512.0,
    trend: "up",
    bias: "bullish",
    label: "Bullish momentum",
    score: 71,
    observations: [
      "Above 20-bar average",
      "RSI 62.4 · neutral",
      "Volume near average",
      "+0.84% over the last 5 bars",
    ],
    spark: [1488, 1492, 1495, 1502.5],
    data_mode: "simulated",
    disclosure:
      "Simulated technical analysis over synthetic prices. Not a recommendation, forecast or live market observation.",
  };
  const session = {
    mode: "accelerated_replay",
    clock: "10:40",
    bar: 18,
    total_bars: 75,
    tick_seconds: 5,
    bar_minutes: 5,
    loop_seconds: 375,
    real_hours_ist: "09:15–15:30 Mon–Fri (simulation ignores holidays)",
    note: "Synthetic session replay.",
  };
  const market = {
    data_mode: "simulated",
    is_live_market_data: false,
    verified_live: false,
    source: "FINOVEXA Indian market simulator",
    index: {
      symbol: "SIMNIFTY50",
      name: "NIFTY 50 · simulated equal-weight index",
      level: 25012.4,
      change: 12.4,
      change_pct: 0.05,
      base_level: 25000,
      history: [
        { time: "10:35", level: 24998 },
        { time: "10:40", level: 25012.4 },
      ],
    },
    summary: {
      total: 1,
      advancers: 1,
      decliners: 0,
      unchanged: 0,
      breadth_pct: 100,
      average_change_pct: 1.18,
      median_change_pct: 1.18,
      mood: "Advancing",
      total_volume: 900000,
      overbought: 0,
      oversold: 0,
    },
    sectors: [
      {
        sector: "Oil Gas & Consumable Fuels",
        count: 1,
        change_pct: 1.18,
        advancers: 1,
        decliners: 0,
        unchanged: 0,
        leader_symbol: "RELIANCE",
        leader_change_pct: 1.18,
        laggard_symbol: "RELIANCE",
        laggard_change_pct: 1.18,
      },
    ],
    stocks: [stock],
    top_gainers: [
      {
        symbol: "RELIANCE",
        name: "Reliance Industries",
        sector: "Oil Gas & Consumable Fuels",
        price: 1502.5,
        change_pct: 1.18,
        volume_ratio: 1.13,
        rsi14: 62.4,
        score: 71,
        trend: "up",
        label: "Bullish momentum",
      },
    ],
    top_losers: [],
    most_active: [],
    overbought: [],
    oversold: [],
    session,
    session_date: "2026-10-25",
    notes: {
      feed: "SIMULATED — synthetic prices, volumes and indicators. This is not live market data.",
      engine: "Deterministic seeded random walk.",
      analysis: "RSI(14), SMA(5/20), VWAP, momentum and volume ratio.",
      orders: "Read-only; orders require the approval-gated trade desk.",
    },
    disclosures: [
      "Simulated market data: prices, volume and analytics are generated locally and are not live market data.",
    ],
    as_of: "2026-10-25T05:00:00",
  };
  const detail = {
    ...stock,
    candles: [
      { index: 0, time: "09:15", open: 1488, high: 1492, low: 1486, close: 1490, volume: 12000 },
      { index: 1, time: "09:20", open: 1490, high: 1504, low: 1489, close: 1502.5, volume: 15000 },
    ],
    session,
    session_date: "2026-10-25",
    notes: market.notes,
    disclosures: market.disclosures,
    as_of: "2026-10-25T05:00:00",
  };
  return {
    useApi: (path: string | null) => {
      const reload = () => undefined;
      if (!path) return { data: null, loading: false, error: null, reload };
      if (path === "/market/simulator") {
        return { data: market, loading: false, error: null, reload };
      }
      return { data: detail, loading: false, error: null, reload };
    },
  };
});

describe("MarketSimulator", () => {
  it("labels the feed as simulated and opens a stock analysis", async () => {
    render(<MarketSimulator />);

    expect(
      screen.getByRole("heading", { name: "Indian market live simulator" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/not live market data/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("RELIANCE").length).toBeGreaterThan(0);
    expect(screen.getByText("Analyse all stocks")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Analyse" })[0]);

    expect(await screen.findByText("RELIANCE · simulated analysis")).toBeInTheDocument();
    expect(screen.getByText("Simulated analysis, not advice")).toBeInTheDocument();
    expect(screen.getByText(/TECHNICAL SCORE 71\/100/)).toBeInTheDocument();
  });

  it("supports search, filtering and pausing the feed", () => {
    render(<MarketSimulator />);

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search simulated stocks"), {
      target: { value: "TCS" },
    });
    expect(screen.getByText("No simulated stock matches")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search simulated stocks"), {
      target: { value: "Reliance" },
    });
    expect(screen.getAllByText("RELIANCE").length).toBeGreaterThan(0);
  });
});
