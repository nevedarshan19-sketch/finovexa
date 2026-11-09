import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronRight,
  CircleAlert,
  Globe2,
  LineChart,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApi } from "../hooks/useApi";
import type {
  IndiaCandle,
  IndiaMarketOverview,
  IndiaMarketRow,
  IndiaStockDetail,
} from "../lib/types";
import { cn } from "../lib/utils";
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
import { compactNumber, moneyExact, number, pct } from "../lib/utils";

type SortKey = "change_pct" | "price" | "volume" | "symbol" | "range_52w";
type Direction = "up" | "down";
type Breadth = "all" | "gainers" | "losers";

const RANGES: { value: string; label: string; hint: string }[] = [
  { value: "1d", label: "1D · 5m", hint: "today intraday" },
  { value: "5d", label: "5D · 15m", hint: "this week" },
  { value: "1mo", label: "1M · daily", hint: "one month" },
  { value: "3mo", label: "3M · daily", hint: "three months" },
  { value: "1y", label: "1Y · daily", hint: "one year" },
];

function marketTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  }).format(date)} IST`;
}

function position52w(quote: IndiaMarketRow["quote"]): number | null {
  if (!quote || quote.high_52w === null || quote.low_52w === null || quote.price === null) return null;
  const span = quote.high_52w - quote.low_52w;
  if (span <= 0) return null;
  return Math.max(0, Math.min(100, ((quote.price - quote.low_52w) / span) * 100));
}

function Sparkline({ values, tone }: { values: number[]; tone: "green" | "red" | "slate" }) {
  if (values.length < 2) return <span className="text-[10px] text-slate-300">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map(
      (value, index) =>
        `${(index / (values.length - 1)) * 72},${20 - ((value - min) / range) * 18}`,
    )
    .join(" ");
  const stroke = tone === "green" ? "#059669" : tone === "red" ? "#e11d48" : "#94a3b8";
  return (
    <svg viewBox="0 0 72 20" className="h-5 w-[72px]" role="img" aria-label="Intraday sparkline">
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function changeTone(change: number | null | undefined): "green" | "red" | "slate" {
  if (change === null || change === undefined) return "slate";
  return change > 0 ? "green" : change < 0 ? "red" : "slate";
}

function IndexTile({ row }: { row: IndiaMarketRow }) {
  const quote = row.quote;
  const tone = changeTone(quote?.change_pct);
  const up = (quote?.change_pct ?? 0) >= 0;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{row.symbol}</p>
          <p className="text-[11px] font-medium text-slate-500">{row.name}</p>
        </div>
        <Sparkline values={quote?.spark ?? []} tone={tone} />
      </div>
      <p className="mt-2 text-lg font-semibold tracking-tight text-ink-900">
        {quote ? number(quote.price, 2) : "Unavailable"}
      </p>
      <div className="mt-1 flex items-center justify-between gap-2">
        {quote?.change_pct !== null && quote?.change_pct !== undefined ? (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 text-[11px] font-semibold",
              up ? "text-emerald-600" : "text-rose-600",
            )}
          >
            {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {pct(quote.change_pct, 2)}
          </span>
        ) : (
          <span className="text-[11px] text-slate-400">No verified value</span>
        )}
        <span className="text-[9px] text-slate-400">{marketTime(quote?.as_of)}</span>
      </div>
    </div>
  );
}

function DetailChart({ candles }: { candles: IndiaCandle[] }) {
  const data = candles.map((candle) => ({
    time: candle.time,
    close: candle.close,
  }));
  if (data.length < 2) {
    return (
      <div className="flex h-52 items-center justify-center rounded-lg border border-dashed border-slate-200 text-xs text-slate-400">
        No chart series is available for this range.
      </div>
    );
  }
  const label = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("en-IN", {
      day: "2-digit",
      month: "short",
      timeZone: "Asia/Kolkata",
    }).format(date);
  };
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="india-quote-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2563eb" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#2563eb" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="time" tickFormatter={label} tick={{ fontSize: 10, fill: "#94a3b8" }} minTickGap={28} />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            width={52}
            tickFormatter={(value: number) => number(value, 0)}
          />
          <Tooltip
            formatter={(value: number) => [number(value, 2), "Close"]}
            labelFormatter={(value: string) => marketTime(value)}
            contentStyle={{ fontSize: 11, borderRadius: 8 }}
          />
          <Area type="monotone" dataKey="close" stroke="#2563eb" strokeWidth={1.6} fill="url(#india-quote-fill)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function DetailModal({ symbol, onClose }: { symbol: string | null; onClose: () => void }) {
  const [range, setRange] = useState("1d");
  const detail = useApi<IndiaStockDetail>(
    symbol ? `/market/india/stocks/${symbol}?range=${range}` : null,
  );

  useEffect(() => {
    setRange("1d");
  }, [symbol]);

  const data = detail.data;
  const quote = data?.quote;
  const up = (quote?.change_pct ?? 0) >= 0;

  return (
    <Modal
      open={Boolean(symbol)}
      onClose={onClose}
      title={data ? `${data.name} · ${data.symbol}` : `Loading ${symbol ?? ""}`}
      description={
        data
          ? `${data.exchange} · ${data.sector || "sector not classified"} · ${data.source}`
          : "Fetching the provider's chart for this stock."
      }
      size="lg"
      footer={
        <>
          <span className="mr-auto text-[10px] leading-relaxed text-slate-400">
            Read-only market detail. Orders are created only in the approval-gated NIFTY 50 trade desk.
          </span>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </>
      }
    >
      {detail.loading && !data && (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      )}
      {detail.error && !data && <ErrorState message={detail.error} onRetry={detail.reload} />}
      {data && quote && (
        <div className="space-y-4">
          {data.stale && (
            <Callout tone="amber" title="Showing the last successful snapshot" icon={CircleAlert}>
              {data.stale_note || "The provider is unreachable. Prices may be older than they appear."}
            </Callout>
          )}
          <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50/70 p-3">
            <div>
              <p className="text-xl font-semibold text-ink-900">{moneyExact(quote.price, "INR")}</p>
              <p
                className={cn(
                  "mt-0.5 inline-flex items-center gap-0.5 text-[11px] font-semibold",
                  up ? "text-emerald-600" : "text-rose-600",
                )}
              >
                {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                {pct(quote.change_pct, 2)} vs previous close {number(quote.previous_close, 2)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <DataModeBadge mode={quote.data_mode} />
              <Badge tone="slate">{marketTime(quote.as_of)}</Badge>
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {RANGES.map((item) => (
              <button
                key={item.value}
                type="button"
                title={item.hint}
                onClick={() => setRange(item.value)}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-[11px] font-semibold transition",
                  range === item.value
                    ? "border-brand-300 bg-brand-50 text-brand-700"
                    : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50",
                )}
              >
                {item.label}
              </button>
            ))}
            <span className="ml-auto self-center text-[10px] text-slate-400">
              {data.candles.length} candles · interval {data.interval}
            </span>
          </div>

          <DetailChart candles={data.candles} />

          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-100 bg-white p-2.5">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">SMA 20 / 50</p>
              <p className="mt-0.5 text-xs font-semibold text-ink-900">
                {number(data.indicators.sma20, 2)} / {number(data.indicators.sma50, 2)}
              </p>
            </div>
            <div className="rounded-lg border border-slate-100 bg-white p-2.5">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">RSI (14)</p>
              <p className="mt-0.5 text-xs font-semibold text-ink-900">{number(data.indicators.rsi14, 1)}</p>
            </div>
            <div className="rounded-lg border border-slate-100 bg-white p-2.5">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">52-week range</p>
              <p className="mt-0.5 text-xs font-semibold text-ink-900">
                {number(data.indicators.low_52w, 2)} – {number(data.indicators.high_52w, 2)}
              </p>
            </div>
          </div>
          {data.indicators.position_52w_pct !== null && (
            <div>
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>Position in 52-week range</span>
                <span>{number(data.indicators.position_52w_pct, 1)}%</span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-brand-500"
                  style={{ width: `${Math.max(0, Math.min(100, data.indicators.position_52w_pct))}%` }}
                />
              </div>
            </div>
          )}

          <div className="grid gap-2 text-[11px] text-slate-500 sm:grid-cols-2">
            <p>
              <span className="font-semibold text-slate-600">Day range:</span>{" "}
              {number(quote.day_low, 2)} – {number(quote.day_high, 2)}
            </p>
            <p>
              <span className="font-semibold text-slate-600">Volume:</span> {compactNumber(quote.volume)}
            </p>
            <p>
              <span className="font-semibold text-slate-600">Instrument key:</span>{" "}
              <span className="font-mono text-[10px]">{data.instrument_key}</span>
            </p>
            <p>
              <span className="font-semibold text-slate-600">Fetched:</span> {marketTime(data.fetched_at)}
            </p>
          </div>

          {data.provider.errors.length > 0 && (
            <Callout tone="amber" title="Partial provider response" icon={CircleAlert}>
              {data.provider.errors.join(" · ")}
            </Callout>
          )}
          <p className="text-[10px] leading-relaxed text-slate-400">{data.provider.delay_note}</p>
          <div className="space-y-1">
            {data.disclosures.map((line) => (
              <p key={line} className="flex items-start gap-1.5 text-[10px] leading-relaxed text-slate-400">
                <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" />
                {line}
              </p>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}

export function IndianMarketPanel() {
  const overview = useApi<IndiaMarketOverview>("/market/india/overview", { pollMs: 60000 });
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("change_pct");
  const [direction, setDirection] = useState<Direction>("down");
  const [breadth, setBreadth] = useState<Breadth>("all");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const handler = (event: Event) => {
      const symbol = (event as CustomEvent<string>).detail;
      if (symbol) setSelected(symbol);
    };
    window.addEventListener("finovexa:open-symbol", handler);
    return () => window.removeEventListener("finovexa:open-symbol", handler);
  }, []);

  const data = overview.data;

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLowerCase();
    let items = data.stocks.filter((item) => {
      if (breadth === "gainers" && (item.quote?.change_pct ?? 0) <= 0.05) return false;
      if (breadth === "losers" && (item.quote?.change_pct ?? 0) >= -0.05) return false;
      if (!needle) return true;
      return (
        item.symbol.toLowerCase().includes(needle) ||
        item.name.toLowerCase().includes(needle) ||
        (item.sector || "").toLowerCase().includes(needle)
      );
    });
    const factor = direction === "down" ? -1 : 1;
    items = [...items].sort((a, b) => {
      if (sort === "symbol") return a.symbol.localeCompare(b.symbol) * factor;
      if (sort === "range_52w") {
        return ((position52w(a.quote) ?? -1) - (position52w(b.quote) ?? -1)) * factor;
      }
      if (sort === "volume") {
        return ((a.quote?.volume ?? -1) - (b.quote?.volume ?? -1)) * factor;
      }
      if (sort === "price") {
        return ((a.quote?.price ?? -1) - (b.quote?.price ?? -1)) * factor;
      }
      return ((a.quote?.change_pct ?? -999) - (b.quote?.change_pct ?? -999)) * factor;
    });
    return items;
  }, [data, query, sort, direction, breadth]);

  return (
    <div id="real-india-market" className="scroll-mt-24">
    <Card>
      <CardHeader
        title="NSE market · real data"
        description="Delayed NSE/BSE prices for the NIFTY 50 and headline indices, fetched live from a market data provider. This is not the simulator."
        icon={Globe2}
        actions={
          <>
            {data && <DataModeBadge mode={data.data_mode} />}
            {data?.session && (
              <Badge tone={data.session.state === "open" ? "green" : data.session.state === "pre_open" ? "amber" : "slate"}>
                {data.session.label} · {data.session.ist_time}
              </Badge>
            )}
            <Button variant="outline" size="sm" icon={RefreshCw} onClick={overview.reload} loading={overview.loading}>
              Refresh
            </Button>
          </>
        }
      />
      <CardBody className="space-y-4 pt-3">
        {overview.loading && !data && (
          <div className="grid gap-3 sm:grid-cols-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {overview.error && !data && <ErrorState message={overview.error} onRetry={overview.reload} />}

        {data && data.stale && (
          <Callout tone="amber" title="Provider unreachable — showing the last snapshot" icon={CircleAlert}>
            {data.stale_note}
          </Callout>
        )}

        {data && !data.available && !data.stale && (
          <Callout tone="amber" title="No real market data right now" icon={CircleAlert}>
            The provider returned no quotes, so nothing is displayed instead of inventing prices.
            {data.provider.errors.length > 0 && (
              <span className="mt-1 block text-[11px]">{data.provider.errors.join(" · ")}</span>
            )}
          </Callout>
        )}

        {data && data.available && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              {data.indices.map((row) => (
                <IndexTile key={row.symbol} row={row} />
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-500">
              <span className="font-semibold text-slate-600">Breadth</span>
              <span className="text-emerald-700">{data.summary.advancers} advancing</span>
              <span className="text-rose-600">{data.summary.decliners} declining</span>
              <span>{data.summary.unchanged} unchanged</span>
              <span className="text-slate-300">|</span>
              <span>
                Avg move {data.summary.average_change_pct === null ? "—" : pct(data.summary.average_change_pct, 2)}
              </span>
              <span className="text-slate-300">|</span>
              <span>Volume {compactNumber(data.summary.total_volume)}</span>
              <span className="text-slate-300">|</span>
              <span>Coverage {data.coverage.covered}/{data.coverage.requested}</span>
              <span className="ml-auto text-[10px] text-slate-400">Session: {data.session.regular_hours}</span>
            </div>

            {data.provider.errors.length > 0 && (
              <Callout tone="amber" title="Some provider calls failed" icon={CircleAlert}>
                {data.provider.errors.join(" · ")}
              </Callout>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[200px] flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search symbol, company or sector"
                  className="pl-8"
                  aria-label="Search NIFTY 50 stocks"
                />
              </div>
              <div className="flex overflow-hidden rounded-md border border-slate-200">
                {(
                  [
                    ["all", "All"],
                    ["gainers", "Gainers"],
                    ["losers", "Losers"],
                  ] as [Breadth, string][]
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setBreadth(value)}
                    className={cn(
                      "px-2.5 py-1.5 text-[11px] font-semibold transition",
                      breadth === value ? "bg-brand-50 text-brand-700" : "bg-white text-slate-500 hover:bg-slate-50",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <Select
                value={sort}
                onChange={(event) => setSort(event.target.value as SortKey)}
                className="w-auto"
                aria-label="Sort stocks"
              >
                <option value="change_pct">Sort: change %</option>
                <option value="price">Sort: price</option>
                <option value="volume">Sort: volume</option>
                <option value="range_52w">Sort: 52-week position</option>
                <option value="symbol">Sort: symbol</option>
              </Select>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDirection((value) => (value === "down" ? "up" : "down"))}
                title={direction === "down" ? "Descending" : "Ascending"}
              >
                {direction === "down" ? "↓ Desc" : "↑ Asc"}
              </Button>
            </div>

            {rows.length === 0 ? (
              <EmptyState
                title="No stocks match"
                description="Try a different search term or breadth filter."
                icon={Search}
              />
            ) : (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Stock</TH>
                    <TH className="text-right">Price</TH>
                    <TH className="text-right">Change</TH>
                    <TH className="text-right">Day range</TH>
                    <TH className="text-right">52-week</TH>
                    <TH className="text-right">Volume</TH>
                    <TH>Trend</TH>
                    <TH className="text-right">Detail</TH>
                  </TR>
                </THead>
                <TBody>
                  {rows.map((row) => {
                    const quote = row.quote;
                    const tone = changeTone(quote?.change_pct);
                    const position = position52w(quote);
                    return (
                      <TR key={row.symbol}>
                        <TD>
                          <p className="font-semibold text-ink-900">{row.symbol}</p>
                          <p className="max-w-[220px] truncate text-[10px] text-slate-400">
                            {row.name} · {row.sector || "sector not classified"}
                          </p>
                        </TD>
                        <TD className="text-right tabular-nums">
                          {quote ? moneyExact(quote.price, "INR") : "Unavailable"}
                        </TD>
                        <TD
                          className={cn(
                            "text-right font-semibold tabular-nums",
                            tone === "green" ? "text-emerald-600" : tone === "red" ? "text-rose-600" : "text-slate-400",
                          )}
                        >
                          {quote?.change_pct === null || quote?.change_pct === undefined
                            ? "—"
                            : pct(quote.change_pct, 2)}
                        </TD>
                        <TD className="text-right text-[10px] tabular-nums text-slate-500">
                          {quote ? `${number(quote.day_low, 2)} – ${number(quote.day_high, 2)}` : "—"}
                        </TD>
                        <TD className="min-w-[110px] text-right">
                          {position === null ? (
                            <span className="text-[10px] text-slate-400">—</span>
                          ) : (
                            <div className="ml-auto w-[100px]">
                              <div className="flex items-center justify-between text-[9px] text-slate-400">
                                <span>{number(quote?.low_52w, 0)}</span>
                                <span>{number(quote?.high_52w, 0)}</span>
                              </div>
                              <div className="mt-0.5 h-1 w-full overflow-hidden rounded-full bg-slate-100">
                                <div
                                  className="h-full rounded-full bg-brand-500"
                                  style={{ width: `${Math.max(2, position)}%` }}
                                />
                              </div>
                            </div>
                          )}
                        </TD>
                        <TD className="text-right text-[10px] tabular-nums text-slate-500">
                          {compactNumber(quote?.volume)}
                        </TD>
                        <TD>
                          <Sparkline values={quote?.spark ?? []} tone={tone} />
                        </TD>
                        <TD className="text-right">
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={ChevronRight}
                            onClick={() => setSelected(row.symbol)}
                            disabled={!quote}
                          >
                            View
                          </Button>
                        </TD>
                      </TR>
                    );
                  })}
                </TBody>
              </TableWrap>
            )}
          </>
        )}
      </CardBody>
      <CardFooter>
        <span className="flex flex-wrap items-center gap-1.5">
          <LineChart className="h-3 w-3" />
          {data?.provider.delay_note ||
            "Real provider quotes, delayed. The simulator below is synthetic and stays labelled SIMULATED."}
        </span>
        <span>{data?.source ? `Source: ${data.source}` : "Source: none"}</span>
      </CardFooter>

      <DetailModal symbol={selected} onClose={() => setSelected(null)} />

      {data && data.available && (
        <div className="sr-only" aria-live="polite">
          {data.summary.mood ? `Market breadth: ${data.summary.mood}.` : ""}
        </div>
      )}
    </Card>
    </div>
  );
}
