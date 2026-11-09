import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InvestmentPortfolio as PortfolioPayload } from "../lib/types";
import { InvestmentPortfolio } from "./InvestmentPortfolio";

const state = vi.hoisted(() => ({ payload: null as unknown }));

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: state.payload,
    loading: false,
    error: null,
    reload: () => {},
  }),
}));

const payload: PortfolioPayload = {
  holdings: [
    {
      symbol: "RELIANCE",
      name: "Reliance Industries",
      sector: "Oil Gas & Consumable Fuels",
      exchange: "NSE",
      currency: "INR",
      quantity: 12,
      average_cost: 1380,
      invested: 16560,
      price: 1485,
      value: 17820,
      pnl: 1260,
      pnl_pct: 7.61,
      change_pct: 0.8,
      day_change: 141.43,
      data_mode: "delayed",
      price_source: "Yahoo Finance (NSE)",
      price_as_of: "2026-10-28T15:30:00+05:30",
      is_stale: false,
      source: "demo_seed",
      source_label: "Demo holding",
      weight_pct: 41.9,
    },
    {
      symbol: "TCS",
      name: "Tata Consultancy Services",
      sector: "Information Technology",
      exchange: "NSE",
      currency: "INR",
      quantity: 6,
      average_cost: 3950,
      invested: 23700,
      price: 4120,
      value: 24720,
      pnl: 1020,
      pnl_pct: 4.3,
      change_pct: 0.5,
      day_change: 123,
      data_mode: "delayed",
      price_source: "Yahoo Finance (NSE)",
      price_as_of: "2026-10-28T15:30:00+05:30",
      is_stale: false,
      source: "simulated_fill",
      source_label: "Simulated trade",
      weight_pct: 58.1,
    },
  ],
  totals: {
    holdings: 2,
    priced: 2,
    invested: 40260,
    current_value: 42540,
    pnl: 2280,
    pnl_pct: 5.66,
    day_change: 264.43,
    recorded_cash: 900000,
    cash_plus_investments: 942540,
    currency: "INR",
  },
  allocation: [
    { sector: "Information Technology", value: 24720, count: 1, share_pct: 58.1 },
    { sector: "Oil Gas & Consumable Fuels", value: 17820, count: 1, share_pct: 41.9 },
  ],
  data_mode: "delayed",
  price_source: "Yahoo Finance (NSE)",
  price_as_of: "2026-10-28T19:20:00+05:30",
  session: { state: "closed", label: "Closed", ist_time: "19:20", ist_date: "2026-10-28", regular_hours: "09:15–15:30", note: "Closed" },
  provider: { name: "yahoo", delay_note: "Delayed NSE quotes.", errors: [] },
  sources: { demo_seed: 1, simulated_fill: 1 },
  is_simulated: true,
  notes: { valuation: "Delayed prices." },
  disclosures: ["This is a practice portfolio, not a real demat or broker account."],
  generated_at: "2026-10-28T19:20:00+05:30",
};

describe("InvestmentPortfolio", () => {
  beforeEach(() => {
    state.payload = payload;
  });

  it("shows totals, holdings and the simulated label without claiming real ownership", () => {
    render(<InvestmentPortfolio />);
    expect(screen.getByText("Your investment portfolio")).toBeInTheDocument();
    expect(screen.getByText("SIMULATED HOLDINGS")).toBeInTheDocument();
    expect(screen.getByText("DELAYED")).toBeInTheDocument();
    expect(screen.getByText("Reliance Industries")).toBeInTheDocument();
    expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument();
    expect(screen.getByText("₹42,540")).toBeInTheDocument();
    expect(screen.getByText("₹40,260")).toBeInTheDocument();
    expect(screen.getByText("₹1,380.00")).toBeInTheDocument();
    expect(screen.getByText("₹17,820.00")).toBeInTheDocument();
    expect(screen.getByText("+₹1,260.00")).toBeInTheDocument();
    expect(screen.getByText("+5.66% overall")).toBeInTheDocument();
    expect(screen.getByText(/kept separate/i)).toBeInTheDocument();
    expect(screen.getByText(/Simulated fills update this portfolio only/i)).toBeInTheDocument();
  });

  it("shows an empty state instead of inventing holdings", () => {
    state.payload = {
      ...payload,
      holdings: [],
      allocation: [],
      totals: { ...payload.totals, holdings: 0, priced: 0, invested: 0, current_value: 0, pnl: 0, pnl_pct: null, day_change: 0 },
    };
    render(<InvestmentPortfolio />);
    expect(screen.getByText("No holdings yet")).toBeInTheDocument();
  });
});
