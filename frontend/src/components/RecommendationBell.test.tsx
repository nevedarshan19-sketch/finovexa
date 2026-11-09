import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../context/ToastContext";
import type { RecommendationFeed } from "../lib/types";
import { RecommendationBell } from "./RecommendationBell";

const state = vi.hoisted(() => ({ feed: null as unknown }));

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: state.feed,
    loading: false,
    error: null,
    reload: () => {},
  }),
}));

const feed: RecommendationFeed = {
  items: [
    {
      symbol: "TCS",
      name: "Tata Consultancy Services",
      sector: "Information Technology",
      score: 78,
      model_signal: "positive",
      label: "Strong setup",
      tone: "green",
      reason: "Up 0.80% today and the model trend is positive. Model score 78/100.",
      price: 4120,
      change_pct: 0.8,
      data_mode: "delayed",
      price_source: "Yahoo Finance (NSE)",
      price_as_of: "2026-10-28T15:30:00+05:30",
      is_model_generated: true,
    },
    {
      symbol: "INFY",
      name: "Infosys",
      sector: "Information Technology",
      score: 52,
      model_signal: "neutral",
      label: "Neutral",
      tone: "slate",
      reason: "Little change today and the model sees no clear direction. Model score 52/100.",
      price: 1890,
      change_pct: 0.05,
      data_mode: "delayed",
      price_source: "Yahoo Finance (NSE)",
      price_as_of: "2026-10-28T15:30:00+05:30",
      is_model_generated: true,
    },
  ],
  summary: { ideas: 2, strong: 1, watch: 0, caution: 0, universe: 4 },
  headline: "Tata Consultancy Services stands out in today's model review",
  signature: "abc123",
  generated_at: "2026-10-28T19:20:00+05:30",
  data_mode: "delayed",
  note: "Model-generated ideas from price momentum and data-quality checks. Not investment advice, an analyst rating or an instruction to buy.",
  disclosure: "FINOVEXA never places an order from this feed.",
};

function renderBell() {
  return render(
    <ToastProvider>
      <RecommendationBell />
    </ToastProvider>,
  );
}

describe("RecommendationBell", () => {
  beforeEach(() => {
    state.feed = feed;
    window.localStorage.clear();
  });

  it("shows plain-language model ideas and never presents them as advice", () => {
    renderBell();
    expect(screen.getByText("Quick stock ideas")).toBeInTheDocument();
    expect(screen.getAllByText(/stands out in today's model review/).length).toBeGreaterThan(0);
    expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument();
    expect(screen.getByText("Strong setup")).toBeInTheDocument();
    expect(screen.getByText("Neutral")).toBeInTheDocument();
    expect(screen.getByText(/Model-generated · not investment advice/)).toBeInTheDocument();
    expect(screen.getByText(/Click any idea to see its chart/)).toBeInTheDocument();
  });

  it("opens the matching stock in the market panel when an idea is clicked", () => {
    const seen: string[] = [];
    const listener = (event: Event) => seen.push((event as CustomEvent<string>).detail);
    window.addEventListener("finovexa:open-symbol", listener);
    renderBell();
    fireEvent.click(screen.getByText("Tata Consultancy Services"));
    window.removeEventListener("finovexa:open-symbol", listener);
    expect(seen).toEqual(["TCS"]);
  });
});
