import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpDown,
  ArrowUpRight,
  Flame,
  LineChart,
  Pause,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApi } from "../hooks/useApi";
import type {
  MarketSimulator,
  SimulatorDetail,
  SimulatorMover,
  SimulatorStock,
  SimulatorTrend,
} from "../lib/types";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  ProgressBar,
  Select,
  Skeleton,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "./ui";
import { DataModeBadge } from "./DataMode";
import { compactMoney, compactNumber, moneyExact, number, pct, titleCase } from "../lib/utils";

type TrendTone = "green" | "red" | "slate";
type SortKey = "change_pct" | "score" | "rsi14" | "volume_ratio" | "price" | "symbol";
type FilterKey = "all" | "bullish" | "bearish" | "overbought" | "oversold" | "volume";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All stocks" },
  { key: "bullish", label: "Bullish only" },
  { key: "bearish", label: "Bearish only" },
  { key: "overbought", label: "RSI ≥ 70" },
  { key: "oversold", label: "RSI ≤ 30" },
  { key: "volume", label: "Volume ≥ 1.2×" },
];

const SORTS: { key: SortKey; label: string }[] = [
  { key: "change_pct", label: "Change %" },
  { key: "score", label: "Technical score" },
  { key: "rsi14", label: "RSI (14)" },
  { key: "volume_ratio", label: "Volume ratio" },
  { key: "price", label: "Price" },
  { key: "symbol", label: "Symbol" },
];

function trendTone(trend: SimulatorTrend): TrendTone {
  return trend === "up" ? "green" : trend === "down" ? "red" : "slate";
}

function biasTone(bias: SimulatorStock["bias"]): "green" | "red" | "amber" {
  return bias === "bullish" ? "green" : bias === "bearish" ? "red" : "amber";
}

function scoreTone(score: number): "green" | "amber" | "red" {
  return score >= 60 ? "green" : score <= 40 ? "red" : "amber";
}

function rsiClass(rsi: number): string {
  if (rsi >= 70) return "text-rose-600";
  if (rsi <= 30) return "text-amber-600";
  return "text-slate-600";
}

function sectorTone(change: number): string {
  if (change >= 1) return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (change >= 0.2) return "border-emerald-100 bg-emerald-50/60 text-emerald-700";
  if (change <= -1) return "border-rose-200 bg-rose-50 text-rose-800";
  if (change <= -0.2) return "border-rose-100 bg-rose-50/60 text-rose-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function Sparkline({ values, className = "h-6 w-20" }: { values: number[]; className?: string }) {
  if (values.length < 2) {
    return <span className="text-[10px] text-slate-300">—</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map(
      (value, index) =>
        `${(index / (values.length - 1)) * 72},${20 - ((value - min) / range) * 18}`,
    )
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg
      viewBox="0 0 72 22"
      className={className}
      preserveAspectRatio="none"
      role="img"
      aria-label={`${up ? "Rising" : "Falling"} simulated price trend`}
    >
      <polyline
        points={points}
        fill="none"
        stroke={up ? "#059669" : "#e11d48"}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TrendBadge({ trend }: { trend: SimulatorTrend }) {
  const tone = trendTone(trend);
  const className =
    tone === "green" ? "text-emerald-600" : tone === "red" ? "text-rose-600" : "text-slate-500";
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-semibold ${className}`}>
      {trend === "up" ? (
        <ArrowUpRight className="h-3 w-3" />
      ) : trend === "down" ? (
        <ArrowDownRight className="h-3 w-3" />
      ) : null}
      {titleCase(trend)}
    </span>
  );
}

function MoverPanel({
  title,
  icon: Icon,
  items,
  kind,
  onSelect,
}: {
  title: string;
  icon: typeof TrendingUp;
  items: SimulatorMover[];
  kind: "change" | "active";
  onSelect: (symbol: string) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-100">
      <div className="flex items-center gap-1.5 border-b border-slate-100 px-3 py-2">
        <Icon className="h-3 w-3 text-slate-400" aria-hidden />
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{title}</p>
      </div>
      <div className="divide-y divide-slate-50">
        {items.map((item) => {
          const up = item.change_pct >= 0;
          return (
            <button
              key={item.symbol}
              type="button"
              onClick={() => onSelect(item.symbol)}
              className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left transition hover:bg-slate-50"
            >
              <span className="min-w-0">
                <span className="block text-[11px] font-semibold text-ink-900">{item.symbol}</span>
                <span className="block truncate text-[9px] text-slate-400">{item.name}</span>
              </span>
              <span className="shrink-0 text-right">
                <span
                  className={`block text-[11px] font-semibold tabular-nums ${
                    kind === "active"
                      ? "text-violet-600"
                      : up
                        ? "text-emerald-600"
                        : "text-rose-600"
                  }`}
                >
                  {kind === "active" ? `${number(item.volume_ratio, 2)}×` : pct(item.change_pct, 2)}
                </span>
                <span className="block text-[9px] text-slate-400">
                  {moneyExact(item.price, "INR")}
                </span>
              </span>
            </button>
          );
        })}
        {items.length === 0 && (
          <p className="px-3 py-3 text-[10px] text-slate-400">None in this simulated session.</p>
        )}
      </div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  valueClassName = "text-ink-900",
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-100 px-2.5 py-2">
      <p className="text-[9px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-0.5 text-[11px] font-semibold tabular-nums ${valueClassName}`}>{value}</p>
    </div>
  );
}

function PriceTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value?: number | string }[];
  label?: string | number;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-pop">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-xs font-semibold tabular-nums text-ink-900">
        {moneyExact(Number(payload[0]?.value ?? 0), "INR")}
      </p>
    </div>
  );
}

export function MarketSimulator() {
  const [paused, setPaused] = useState(false);
  const market = useApi<MarketSimulator>("/market/simulator", {
    pollMs: paused ? 0 : 5000,
  });
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sortKey, setSortKey] = useState<SortKey>("change_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useApi<SimulatorDetail>(selected ? `/market/simulator/${selected}` : null);

  const data = market.data;
  const stocks = useMemo(() => data?.stocks ?? [], [data]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return stocks.filter((stock) => {
      if (
        needle &&
        ![stock.symbol, stock.name, stock.sector, stock.instrument_key]
          .join(" ")
          .toLowerCase()
          .includes(needle)
      ) {
        return false;
      }
      if (filter === "bullish") return stock.bias === "bullish";
      if (filter === "bearish") return stock.bias === "bearish";
      if (filter === "overbought") return stock.rsi14 >= 70;
      if (filter === "oversold") return stock.rsi14 <= 30;
      if (filter === "volume") return stock.volume_ratio >= 1.2;
      return true;
    });
  }, [stocks, search, filter]);

  const sorted = useMemo(() => {
    const factor = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sortKey === "symbol") return a.symbol.localeCompare(b.symbol) * factor;
      return ((a[sortKey] as number) - (b[sortKey] as number)) * factor;
    });
  }, [filtered, sortKey, sortDir]);

  const goToTradeDesk = () => {
    setSelected(null);
    window.setTimeout(() => {
      document
        .getElementById("nifty50-trade-desk")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  };

  const detailReady =
    detail.data && detail.data.symbol === selected && !detail.loading ? detail.data : null;

  return (
    <Card>
      <CardHeader
        title="Indian market live simulator"
        description="An auto-refreshing simulated NSE session across all 50 NIFTY 50 stocks, with RSI, moving averages, VWAP, volume, support/resistance and a transparent technical score. Synthetic data only — not NSE/BSE or Upstox."
        icon={Activity}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <DataModeBadge mode="simulated" />
            <Badge tone="amber">NOT LIVE MARKET DATA</Badge>
            {data && (
              <Badge tone="slate">
                {paused ? "Paused" : `${data.session.tick_seconds}s auto-refresh`}
              </Badge>
            )}
            <Button
              variant="outline"
              size="sm"
              icon={paused ? Play : Pause}
              onClick={() => setPaused((value) => !value)}
            >
              {paused ? "Resume" : "Pause"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={RefreshCw}
              onClick={market.reload}
              loading={market.loading}
            >
              Refresh
            </Button>
          </div>
        }
      />

      {market.loading && !data ? (
        <CardBody className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-24 w-full" />
            ))}
          </div>
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </CardBody>
      ) : market.error && !data ? (
        <CardBody>
          <ErrorState message={market.error} onRetry={market.reload} />
        </CardBody>
      ) : data ? (
        <>
          <CardBody className="space-y-5 pt-4">
            <Callout tone="amber" title="Simulated feed — not live market data" icon={ShieldAlert}>
              Every price, volume, RSI value and score on this panel is generated locally by the
              FINOVEXA simulator. No exchange or broker feed is contacted, and nothing here is a
              recommendation. This feed is independent of the demo/provider quotes in the trade desk
              and is never used to price an order.
            </Callout>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Simulated NIFTY 50
                </p>
                <div className="mt-1 flex items-end justify-between gap-2">
                  <p className="text-xl font-semibold tracking-tight text-ink-900">
                    {number(data.index.level, 2)}
                  </p>
                  <Sparkline
                    values={data.index.history.map((point) => point.level)}
                    className="h-7 w-20"
                  />
                </div>
                <p
                  className={`mt-1 text-[11px] font-semibold ${
                    data.index.change_pct >= 0 ? "text-emerald-600" : "text-rose-600"
                  }`}
                >
                  {pct(data.index.change_pct, 2)} · equal-weight
                </p>
              </div>

              <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Market breadth
                </p>
                <div className="mt-1 flex items-baseline gap-2">
                  <p className="text-xl font-semibold tracking-tight text-emerald-600">
                    {data.summary.advancers}
                  </p>
                  <span className="text-xs text-slate-400">advancing</span>
                  <p className="ml-auto text-xl font-semibold tracking-tight text-rose-600">
                    {data.summary.decliners}
                  </p>
                  <span className="text-xs text-slate-400">declining</span>
                </div>
                <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="bg-emerald-500"
                    style={{ width: `${data.summary.breadth_pct}%` }}
                  />
                  <div
                    className="bg-rose-500"
                    style={{ width: `${100 - data.summary.breadth_pct}%` }}
                  />
                </div>
                <p className="mt-1.5 text-[10px] text-slate-400">
                  {number(data.summary.breadth_pct, 1)}% breadth · {data.summary.unchanged} unchanged
                </p>
              </div>

              <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Average move · {data.summary.total} stocks
                </p>
                <div className="mt-1 flex items-baseline gap-2">
                  <p
                    className={`text-xl font-semibold tracking-tight ${
                      data.summary.average_change_pct >= 0
                        ? "text-emerald-600"
                        : "text-rose-600"
                    }`}
                  >
                    {pct(data.summary.average_change_pct, 2)}
                  </p>
                  <Badge
                    tone={
                      data.summary.mood === "Advancing"
                        ? "green"
                        : data.summary.mood === "Declining"
                          ? "red"
                          : "amber"
                    }
                  >
                    {data.summary.mood}
                  </Badge>
                </div>
                <p className="mt-1.5 text-[10px] text-slate-400">
                  Median {pct(data.summary.median_change_pct, 2)} ·{" "}
                  {data.summary.overbought} overbought · {data.summary.oversold} oversold
                </p>
              </div>

              <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Session replay
                </p>
                <div className="mt-1 flex items-baseline justify-between gap-2">
                  <p className="text-xl font-semibold tracking-tight text-ink-900">
                    {data.session.clock}
                  </p>
                  <Badge tone="violet">bar {data.session.bar}/{data.session.total_bars}</Badge>
                </div>
                <p className="mt-1.5 text-[10px] text-slate-400">
                  {data.session.tick_seconds}s per {data.session.bar_minutes}-min bar · loops every{" "}
                  {Math.floor(data.session.loop_seconds / 60)}m
                  {String(data.session.loop_seconds % 60).padStart(2, "0")}s ·{" "}
                  {compactNumber(data.summary.total_volume)} shares traded
                </p>
              </div>
            </div>

            <div>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Sector performance
                </p>
                <span className="text-[10px] text-slate-400">
                  Average simulated move · advancers / decliners
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                {data.sectors.map((sector) => (
                  <div
                    key={sector.sector}
                    className={`rounded-lg border p-2.5 ${sectorTone(sector.change_pct)}`}
                  >
                    <p className="truncate text-[10px] font-semibold" title={sector.sector}>
                      {sector.sector}
                    </p>
                    <div className="mt-0.5 flex items-baseline justify-between gap-1">
                      <span className="text-sm font-semibold tabular-nums">
                        {pct(sector.change_pct, 2)}
                      </span>
                      <span className="text-[9px] opacity-70">
                        {sector.advancers}↑ {sector.decliners}↓
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-[9px] opacity-70">
                      {sector.leader_symbol} {pct(sector.leader_change_pct, 1)}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-3">
              <MoverPanel
                title="Top gainers"
                icon={TrendingUp}
                items={data.top_gainers}
                kind="change"
                onSelect={setSelected}
              />
              <MoverPanel
                title="Top losers"
                icon={TrendingDown}
                items={data.top_losers}
                kind="change"
                onSelect={setSelected}
              />
              <MoverPanel
                title="Most active"
                icon={Flame}
                items={data.most_active}
                kind="active"
                onSelect={setSelected}
              />
            </div>

            <div id="simulator-stocks" className="space-y-2.5">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    Analyse all stocks
                  </p>
                  <p className="text-[11px] text-slate-400">
                    {filtered.length} of {data.summary.total} stocks · sorted by{" "}
                    {SORTS.find((option) => option.key === sortKey)?.label.toLowerCase()} (
                    {sortDir === "asc" ? "ascending" : "descending"})
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative w-full max-w-[220px]">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                    <Input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Search symbol, name or sector"
                      aria-label="Search simulated stocks"
                      className="h-9 pl-8 text-xs"
                    />
                  </div>
                  <Select
                    value={filter}
                    onChange={(event) => setFilter(event.target.value as FilterKey)}
                    aria-label="Filter stocks"
                    className="h-9 w-auto text-xs"
                  >
                    {FILTERS.map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                  <Select
                    value={sortKey}
                    onChange={(event) => setSortKey(event.target.value as SortKey)}
                    aria-label="Sort stocks"
                    className="h-9 w-auto text-xs"
                  >
                    {SORTS.map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                  <Button
                    size="sm"
                    variant="outline"
                    icon={ArrowUpDown}
                    onClick={() => setSortDir((value) => (value === "asc" ? "desc" : "asc"))}
                    aria-label={`Sort ${sortDir === "asc" ? "descending" : "ascending"}`}
                  >
                    {sortDir === "asc" ? "Asc" : "Desc"}
                  </Button>
                </div>
              </div>

              {sorted.length === 0 ? (
                <EmptyState
                  title="No simulated stock matches"
                  description="Try another symbol, sector or filter. All 50 NIFTY 50 constituents are in the simulator."
                  icon={Search}
                />
              ) : (
                <div className="overflow-hidden rounded-lg border border-slate-100">
                  <div className="max-h-[620px] space-y-2 overflow-auto p-2 lg:hidden">
                    {sorted.map((stock) => {
                      const up = stock.change_pct >= 0;
                      return (
                        <div
                          key={stock.symbol}
                          className="rounded-lg border border-slate-100 bg-white p-3"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="text-sm font-semibold text-ink-900">{stock.symbol}</p>
                              <p className="truncate text-[10px] text-slate-400">{stock.name}</p>
                            </div>
                            <div className="shrink-0 text-right">
                              <p className="text-sm font-semibold text-ink-900">
                                {moneyExact(stock.price, stock.currency)}
                              </p>
                              <p
                                className={`text-[10px] font-semibold ${
                                  up ? "text-emerald-600" : "text-rose-600"
                                }`}
                              >
                                {pct(stock.change_pct, 2)}
                              </p>
                            </div>
                          </div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            <Badge tone="slate">{stock.sector}</Badge>
                            <Badge tone={biasTone(stock.bias)}>{stock.label}</Badge>
                            <span className={`text-[10px] font-semibold ${rsiClass(stock.rsi14)}`}>
                              RSI {number(stock.rsi14, 1)}
                            </span>
                            <span className="text-[10px] text-slate-400">
                              vol {number(stock.volume_ratio, 2)}×
                            </span>
                            <span className="text-[10px] text-slate-400">
                              score {stock.score}/100
                            </span>
                          </div>
                          <div className="mt-2 flex items-center justify-between gap-2">
                            <Sparkline values={stock.spark} className="h-7 w-24" />
                            <Button
                              size="sm"
                              variant="outline"
                              icon={LineChart}
                              onClick={() => setSelected(stock.symbol)}
                            >
                              Analyse
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="hidden lg:block">
                    <TableWrap>
                      <THead>
                        <TR className="bg-slate-50/90">
                          <TH className="sticky top-0 z-10 bg-slate-50">Stock</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50">Sector</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50 text-right">Price</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50 text-right">Change</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50">Trend</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50 text-right">RSI 14</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50 text-right">Vol</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50">Score</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50">24-bar</TH>
                          <TH className="sticky top-0 z-10 bg-slate-50 text-right" />
                        </TR>
                      </THead>
                      <TBody>
                        {sorted.map((stock) => {
                          const up = stock.change_pct >= 0;
                          return (
                            <TR key={stock.symbol}>
                              <TD>
                                <p className="font-semibold text-ink-900">{stock.symbol}</p>
                                <p className="text-[10px] text-slate-400">{stock.name}</p>
                              </TD>
                              <TD className="text-[10px] text-slate-500">{stock.sector}</TD>
                              <TD className="text-right font-semibold tabular-nums text-ink-900">
                                {moneyExact(stock.price, stock.currency)}
                              </TD>
                              <TD
                                className={`text-right text-[11px] font-semibold tabular-nums ${
                                  up ? "text-emerald-600" : "text-rose-600"
                                }`}
                              >
                                {pct(stock.change_pct, 2)}
                              </TD>
                              <TD>
                                <TrendBadge trend={stock.trend} />
                              </TD>
                              <TD
                                className={`text-right text-[11px] font-semibold tabular-nums ${rsiClass(
                                  stock.rsi14,
                                )}`}
                              >
                                {number(stock.rsi14, 1)}
                              </TD>
                              <TD className="text-right text-[11px] tabular-nums text-slate-600">
                                {number(stock.volume_ratio, 2)}×
                              </TD>
                              <TD>
                                <div className="flex items-center gap-1.5">
                                  <span className="w-6 text-right text-[10px] tabular-nums text-slate-500">
                                    {stock.score}
                                  </span>
                                  <ProgressBar
                                    value={stock.score}
                                    tone={scoreTone(stock.score)}
                                    className="w-14"
                                    label={`${stock.symbol} simulated technical score`}
                                  />
                                </div>
                              </TD>
                              <TD>
                                <Sparkline values={stock.spark} />
                              </TD>
                              <TD>
                                <div className="flex justify-end">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    icon={LineChart}
                                    onClick={() => setSelected(stock.symbol)}
                                  >
                                    Analyse
                                  </Button>
                                </div>
                              </TD>
                            </TR>
                          );
                        })}
                      </TBody>
                    </TableWrap>
                  </div>
                </div>
              )}
            </div>
          </CardBody>
          <CardFooter>
            <span>{data.notes.feed}</span>
            <span>{data.notes.orders}</span>
          </CardFooter>
        </>
      ) : null}

      <Modal
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected ? `${selected} · simulated analysis` : "Simulated analysis"}
        description="Synthetic intraday data for this simulated session. Read-only — not investment advice."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setSelected(null)}>
              Close
            </Button>
            <Button icon={LineChart} onClick={goToTradeDesk}>
              Go to trade desk
            </Button>
          </>
        }
      >
        {!detailReady ? (
          detail.error ? (
            <ErrorState message={detail.error} onRetry={detail.reload} />
          ) : (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-52 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50/70 p-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-ink-900">{detailReady.name}</p>
                <p className="text-[10px] text-slate-400">
                  {detailReady.sector} · {detailReady.instrument_key}
                </p>
              </div>
              <div className="text-right">
                <p className="text-lg font-semibold tracking-tight text-ink-900">
                  {moneyExact(detailReady.price, detailReady.currency)}
                </p>
                <p
                  className={`text-[11px] font-semibold ${
                    detailReady.change_pct >= 0 ? "text-emerald-600" : "text-rose-600"
                  }`}
                >
                  {pct(detailReady.change_pct, 2)} today
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={biasTone(detailReady.bias)}>{detailReady.label}</Badge>
              <Badge tone="violet">TECHNICAL SCORE {detailReady.score}/100</Badge>
              <DataModeBadge mode="simulated" />
              <Badge tone="slate">Read-only</Badge>
            </div>

            <div className="rounded-lg border border-slate-100 p-2">
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart
                  data={detailReady.candles.map((candle) => ({
                    time: candle.time,
                    price: candle.close,
                  }))}
                  margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                >
                  <defs>
                    <linearGradient id="simPriceFill" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="0%"
                        stopColor={detailReady.change_pct >= 0 ? "#0d9488" : "#e11d48"}
                        stopOpacity={0.25}
                      />
                      <stop
                        offset="100%"
                        stopColor={detailReady.change_pct >= 0 ? "#0d9488" : "#e11d48"}
                        stopOpacity={0.01}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#e8edf4" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10, fill: "#94a3b8" }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={26}
                  />
                  <YAxis
                    width={58}
                    domain={["auto", "auto"]}
                    tick={{ fontSize: 10, fill: "#94a3b8" }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(value: number) => compactMoney(value, "INR")}
                  />
                  <Tooltip content={<PriceTooltip />} />
                  <ReferenceLine
                    y={detailReady.previous_close}
                    stroke="#94a3b8"
                    strokeDasharray="4 4"
                    label={{
                      value: "Prev close",
                      position: "insideTopLeft",
                      fontSize: 9,
                      fill: "#64748b",
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="price"
                    stroke={detailReady.change_pct >= 0 ? "#0d9488" : "#e11d48"}
                    strokeWidth={2}
                    fill="url(#simPriceFill)"
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
              <p className="px-2 pb-1 text-[9px] text-slate-400">
                Simulated 5-minute closes · 09:15 to {detailReady.session.clock} IST equivalence ·
                replay clock, not the real NSE session.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <MiniStat label="Open" value={moneyExact(detailReady.open, "INR")} />
              <MiniStat
                label="Day range"
                value={`${moneyExact(detailReady.day_low, "INR")} – ${moneyExact(
                  detailReady.day_high,
                  "INR",
                )}`}
              />
              <MiniStat label="VWAP" value={moneyExact(detailReady.vwap, "INR")} />
              <MiniStat
                label="SMA 5 / 20"
                value={`${number(detailReady.sma5, 2)} / ${number(detailReady.sma20, 2)}`}
              />
              <MiniStat
                label="RSI (14)"
                value={number(detailReady.rsi14, 1)}
                valueClassName={rsiClass(detailReady.rsi14)}
              />
              <MiniStat
                label="5-bar momentum"
                value={pct(detailReady.momentum_pct, 2)}
                valueClassName={
                  detailReady.momentum_pct >= 0 ? "text-emerald-600" : "text-rose-600"
                }
              />
              <MiniStat
                label="Session volatility"
                value={`${number(detailReady.volatility_pct, 2)}%`}
              />
              <MiniStat
                label="Volume vs average"
                value={`${number(detailReady.volume_ratio, 2)}× (${compactNumber(
                  detailReady.volume,
                )})`}
              />
              <MiniStat
                label="Support / resistance"
                value={`${number(detailReady.support, 2)} / ${number(
                  detailReady.resistance,
                  2,
                )}`}
              />
            </div>

            <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
              <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                <span>Simulated technical score</span>
                <span>{detailReady.score}/100</span>
              </div>
              <ProgressBar
                value={detailReady.score}
                tone={scoreTone(detailReady.score)}
                className="mt-2"
                label={`${detailReady.symbol} simulated technical score`}
              />
              <ul className="mt-2.5 space-y-1">
                {detailReady.observations.map((observation) => (
                  <li
                    key={observation}
                    className="flex items-start gap-1.5 text-[11px] leading-relaxed text-slate-600"
                  >
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-slate-400" />
                    {observation}
                  </li>
                ))}
              </ul>
            </div>

            <Callout tone="amber" title="Simulated analysis, not advice" icon={ShieldAlert}>
              {detailReady.disclosure} No order is placed from this panel; trading stays in the
              approval-gated NIFTY 50 trade desk and requires owner approval.
            </Callout>

            <p className="text-[10px] leading-relaxed text-slate-400">
              {detailReady.notes.feed} {detailReady.notes.analysis}
            </p>
          </div>
        )}
      </Modal>
    </Card>
  );
}
