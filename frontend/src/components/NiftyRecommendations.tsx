import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  ChevronDown,
  Info,
  RefreshCw,
  Search,
  ShieldAlert,
  Target,
} from "lucide-react";
import type {
  NiftyConfidence,
  NiftyHorizon,
  NiftyRecommendationCard,
  NiftyRecommendationResponse,
  NiftySort,
} from "../lib/niftyTypes";
import { useApi } from "../hooks/useApi";
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
  Select,
  SkeletonCard,
} from "./ui";
import { DataModeBadge } from "./DataMode";
import { cn, formatDateTime, moneyExact, pct, timeAgo } from "../lib/utils";

const MIN_UPSIDE_OPTIONS = ["0", "3", "5", "8", "10", "15"];

function upsideTone(value: number | null) {
  if (value === null) return "text-slate-400";
  if (value >= 5) return "text-emerald-600";
  if (value > 0) return "text-brand-600";
  return "text-rose-600";
}

function confidenceTone(label: string) {
  if (label === "high") return "green" as const;
  if (label === "medium") return "blue" as const;
  return "amber" as const;
}

function IndicatorValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50/80 px-2.5 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-[11.5px] font-semibold text-ink-900">{value}</p>
    </div>
  );
}

function ReasoningPanel({ card }: { card: NiftyRecommendationCard }) {
  return (
    <details className="group mt-3 rounded-xl border border-slate-200 bg-slate-50/60">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2.5 text-[11.5px] font-semibold text-slate-700 [&::-webkit-details-marker]:hidden">
        Why this recommendation
        <ChevronDown className="h-3.5 w-3.5 text-slate-400 transition group-open:rotate-180" aria-hidden />
      </summary>
      <div className="space-y-3 border-t border-slate-200 px-3 py-3 text-[11px] leading-relaxed">
        <div>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Model reasons</p>
          <ul className="mt-1 space-y-1 text-slate-600">
            {card.reasons.map((reason) => (
              <li key={reason} className="flex gap-1.5">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-400" aria-hidden />
                {reason}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Main risks</p>
          <ul className="mt-1 space-y-1 text-amber-800">
            {card.risks.map((risk) => (
              <li key={risk} className="flex gap-1.5">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-amber-400" aria-hidden />
                {risk}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">
            Indicators used
          </p>
          <div className="mt-1.5 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            <IndicatorValue label="SMA 20" value={moneyExact(card.indicators.sma20 ?? null)} />
            <IndicatorValue label="SMA 50" value={moneyExact(card.indicators.sma50 ?? null)} />
            <IndicatorValue label="RSI 14" value={card.indicators.rsi14?.toFixed(1) ?? "—"} />
            <IndicatorValue label="Volatility" value={card.indicators.volatility_annual_pct ? `${card.indicators.volatility_annual_pct.toFixed(0)}%` : "—"} />
            <IndicatorValue label="1M momentum" value={pct(card.indicators.momentum_1m_pct ?? null)} />
            <IndicatorValue label="3M momentum" value={pct(card.indicators.momentum_3m_pct ?? null)} />
            <IndicatorValue label="52W high" value={moneyExact(card.indicators.high_52w ?? null)} />
            <IndicatorValue label="52W low" value={moneyExact(card.indicators.low_52w ?? null)} />
          </div>
          <p className="mt-1.5 text-[10px] text-slate-400">
            {card.indicators.closes} daily closes analysed · 52-week position{" "}
            {card.indicators.position_52w_pct !== null && card.indicators.position_52w_pct !== undefined
              ? `${card.indicators.position_52w_pct.toFixed(0)}%`
              : "—"}
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[10.5px] text-slate-500">
          <span className="font-semibold text-slate-700">Fundamentals:</span> {card.fundamentals.note}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-200 pt-2 text-[10px] text-slate-400">
          <span>Source: {card.price_source || "unavailable"}</span>
          <span>Price as of {card.price_as_of ? formatDateTime(card.price_as_of) : "not reported"}</span>
          <span>Analysed {card.analysis_at ? timeAgo(card.analysis_at) : "—"}</span>
          <span>Method {card.methodology_version}</span>
        </div>
      </div>
    </details>
  );
}

function RecommendationCard({ card }: { card: NiftyRecommendationCard }) {
  const confidence = card.confidence;
  return (
    <Card hover className="flex h-full flex-col p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-600">
              {card.symbol}
            </span>
            <DataModeBadge mode={card.data_mode || "unavailable"} showDot={false} />
            {card.is_stale && <Badge tone="amber">STALE</Badge>}
          </div>
          <p className="mt-1.5 truncate text-[13px] font-semibold text-ink-900">{card.name}</p>
          <p className="truncate text-[10.5px] text-slate-400">{card.sector}</p>
        </div>
        <Badge tone={confidence ? confidenceTone(confidence.label) : "slate"} dot>
          {confidence ? `${confidence.label_display} confidence` : "No confidence"}
        </Badge>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <div className="rounded-lg border border-slate-200 px-2.5 py-2">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Market price</p>
          <p className="mt-0.5 text-sm font-semibold text-ink-900">{moneyExact(card.price)}</p>
          <p className="mt-0.5 text-[9px] text-slate-400">
            {card.price_as_of ? timeAgo(card.price_as_of) : "no timestamp"}
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 px-2.5 py-2">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Target price</p>
          <p className="mt-0.5 text-sm font-semibold text-ink-900">{moneyExact(card.target_price)}</p>
          <p className="mt-0.5 text-[9px] text-slate-400">model estimate</p>
        </div>
        <div className="rounded-lg border border-slate-200 px-2.5 py-2">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Upside</p>
          <p className={cn("mt-0.5 inline-flex items-center gap-0.5 text-sm font-semibold", upsideTone(card.upside_pct))}>
            {card.upside_pct !== null && card.upside_pct >= 0 ? (
              <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <ArrowDownRight className="h-3.5 w-3.5" aria-hidden />
            )}
            {pct(card.upside_pct, 2)}
          </p>
          <p className="mt-0.5 text-[9px] text-slate-400">{card.horizon_label}</p>
        </div>
      </div>

      {confidence && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span>Technical confidence · {confidence.score}/100</span>
            <span className="capitalize">{confidence.label}</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div
              className={cn(
                "h-full rounded-full",
                confidence.label === "high"
                  ? "bg-emerald-500"
                  : confidence.label === "medium"
                    ? "bg-brand-500"
                    : "bg-amber-400",
              )}
              style={{ width: `${confidence.score}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-3 space-y-1 text-[10.5px] leading-relaxed text-slate-500">
        {card.reasons.slice(0, 2).map((reason) => (
          <p key={reason} className="flex gap-1.5">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-emerald-400" aria-hidden />
            {reason}
          </p>
        ))}
      </div>

      <ReasoningPanel card={card} />

      <p className="mt-auto pt-3 text-[9.5px] text-slate-400">
        {card.price_source || "Source unavailable"} · analysed {card.analysis_at ? timeAgo(card.analysis_at) : "—"}
      </p>
    </Card>
  );
}

function NoSignalRow({ card }: { card: NiftyRecommendationCard }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 py-2 first:border-t-0">
      <span className="w-24 shrink-0 font-mono text-[10.5px] font-semibold text-slate-600">{card.symbol}</span>
      <span className="min-w-0 flex-1 truncate text-[11.5px] text-slate-700">{card.name}</span>
      <span className="text-[11px] font-medium text-slate-500">{moneyExact(card.price)}</span>
      <span className={cn("w-16 text-right text-[11px] font-semibold", upsideTone(card.upside_pct))}>
        {pct(card.upside_pct, 2)}
      </span>
      <span className="w-20 text-right text-[10px] text-slate-400">
        {card.confidence ? `${card.confidence.label_display} · ${card.confidence.score}` : "—"}
      </span>
      <span className="w-24 text-right text-[9.5px] text-slate-400">
        {card.price_as_of ? timeAgo(card.price_as_of) : "no timestamp"}
      </span>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  hint,
  tone = "slate",
}: {
  label: string;
  value: string;
  hint: string;
  tone?: "green" | "slate" | "amber" | "brand";
}) {
  const toneClass = {
    green: "border-emerald-200 bg-emerald-50/60",
    slate: "border-slate-200 bg-slate-50/60",
    amber: "border-amber-200 bg-amber-50/60",
    brand: "border-brand-200 bg-brand-50/60",
  }[tone];
  return (
    <div className={cn("rounded-xl border px-3.5 py-3", toneClass)}>
      <p className="text-[9.5px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold tracking-tight text-ink-900">{value}</p>
      <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">{hint}</p>
    </div>
  );
}

export function NiftyRecommendations({ embedded = false }: { embedded?: boolean }) {
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [horizon, setHorizon] = useState<NiftyHorizon>("3m");
  const [sort, setSort] = useState<NiftySort>("upside");
  const [confidence, setConfidence] = useState<"" | NiftyConfidence>("");
  const [minUpside, setMinUpside] = useState("5");

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(queryInput.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [queryInput]);

  const path = useMemo(() => {
    const params = new URLSearchParams({ horizon, sort, min_upside: minUpside });
    if (query) params.set("q", query);
    if (confidence) params.set("confidence", confidence);
    return `/market/nifty50/recommendations?${params.toString()}`;
  }, [horizon, sort, minUpside, query, confidence]);

  const screen = useApi<NiftyRecommendationResponse>(path);
  const data = screen.data;

  if (screen.loading && !data) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {[0, 1, 2, 3].map((index) => (
          <SkeletonCard key={index} lines={4} />
        ))}
      </div>
    );
  }
  if (screen.error && !data) {
    return <ErrorState message={screen.error} onRetry={screen.reload} />;
  }
  if (!data) return null;

  return (
    <div className={cn("space-y-4", embedded && "pt-1")}>
      <Callout tone="amber" title="Recommendations are informational only" icon={ShieldAlert}>
        <p>{data.disclaimer}</p>
        <p className="mt-1 text-[10.5px]">
          Only {data.counts.qualifying} of {data.counts.universe} NIFTY 50 constituents currently clear the{" "}
          {data.criteria.min_upside_pct}% model-upside threshold. A qualifying signal is not a buy rating.
        </p>
      </Callout>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryTile
          label="Qualifying"
          value={`${data.counts.qualifying} of ${data.counts.universe}`}
          hint={`Model upside ≥ ${data.criteria.min_upside_pct}% · ${data.criteria.horizon_label}`}
          tone="green"
        />
        <SummaryTile
          label="No positive upside"
          value={String(data.counts.no_positive_upside)}
          hint="Analysed, but below the positive-upside threshold"
        />
        <SummaryTile
          label="Insufficient data"
          value={String(data.counts.insufficient_data)}
          hint="No verified price or enough history; never estimated"
          tone="amber"
        />
        <SummaryTile
          label="Universe analysed"
          value={`${data.universe.analysed}/${data.universe.size}`}
          hint={data.universe.constituents.fallback ? "Bundled NSE snapshot" : "NSE constituent file"}
          tone="brand"
        />
      </div>

      <Card>
        <CardBody className="grid gap-3 pt-4 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <label className="relative block">
            <span className="sr-only">Search company or ticker</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
            <Input
              value={queryInput}
              onChange={(event) => setQueryInput(event.target.value)}
              placeholder="Search company or ticker"
              className="pl-8"
            />
          </label>
          <label className="block">
            <span className="sr-only">Horizon</span>
            <Select value={horizon} onChange={(event) => setHorizon(event.target.value as NiftyHorizon)}>
              {data.criteria.horizons.map((item) => (
                <option key={item.key} value={item.key}>
                  Horizon · {item.label}
                </option>
              ))}
            </Select>
          </label>
          <label className="block">
            <span className="sr-only">Minimum upside</span>
            <Select value={minUpside} onChange={(event) => setMinUpside(event.target.value)}>
              {MIN_UPSIDE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  Min upside · {value}%
                </option>
              ))}
            </Select>
          </label>
          <label className="block">
            <span className="sr-only">Confidence</span>
            <Select
              value={confidence}
              onChange={(event) => setConfidence(event.target.value as "" | NiftyConfidence)}
            >
              <option value="">All confidence levels</option>
              <option value="high">High confidence</option>
              <option value="medium">Medium confidence</option>
              <option value="low">Low confidence</option>
            </Select>
          </label>
          <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-4">
            <Select
              value={sort}
              onChange={(event) => setSort(event.target.value as NiftySort)}
              className="max-w-[190px]"
            >
              <option value="upside">Sort · Estimated upside</option>
              <option value="confidence">Sort · Confidence</option>
              <option value="name">Sort · Company name</option>
            </Select>
            <Button variant="outline" size="sm" icon={RefreshCw} onClick={screen.reload} loading={screen.loading}>
              Refresh analysis
            </Button>
            <span className="text-[10px] text-slate-400">
              Analysed {formatDateTime(data.generated_at)} · {data.matched.total} of{" "}
              {data.counts.universe} shown
            </span>
          </div>
        </CardBody>
      </Card>

      <section aria-labelledby="nifty-qualifying">
        <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="nifty-qualifying" className="text-sm font-semibold text-ink-900">
              NIFTY 50 recommendations
            </h2>
            <p className="text-[11px] text-slate-400">
              Every constituent with model upside ≥ {data.criteria.min_upside_pct}% · {data.criteria.horizon_label}{" "}
              horizon
            </p>
          </div>
          <Badge tone="green">{data.matched.qualifying} qualifying</Badge>
        </div>
        {data.qualifying.length === 0 ? (
          <EmptyState
            title="No stock clears the current filter"
            description="No constituent meets this upside threshold and filter combination. Lower the minimum upside or clear the search to see more."
            icon={Target}
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setMinUpside("0");
                  setQueryInput("");
                  setConfidence("");
                }}
              >
                Reset upside filter
              </Button>
            }
          />
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {data.qualifying.map((card) => (
              <RecommendationCard key={card.symbol} card={card} />
            ))}
          </div>
        )}
      </section>

      <Card>
        <CardHeader
          title="No positive upside signal"
          description={`${data.counts.no_positive_upside} of ${data.counts.universe} constituents were analysed but do not clear the ${data.criteria.min_upside_pct}% threshold. They are listed here instead of being presented as buys.`}
          icon={AlertTriangle}
          actions={<Badge tone="slate">{data.matched.no_positive_upside} shown</Badge>}
        />
        <CardBody className="pt-2">
          {data.no_positive_upside.length === 0 ? (
            <p className="py-3 text-[11.5px] text-slate-400">
              Every analysed constituent meets the current threshold, or the filters exclude the rest.
            </p>
          ) : (
            <div>
              <div className="flex flex-wrap items-center gap-x-3 border-b border-slate-200 pb-2 text-[9px] font-semibold uppercase tracking-wide text-slate-400">
                <span className="w-24 shrink-0">Ticker</span>
                <span className="min-w-0 flex-1">Company</span>
                <span>Price</span>
                <span className="w-16 text-right">Upside</span>
                <span className="w-20 text-right">Confidence</span>
                <span className="w-24 text-right">Price as of</span>
              </div>
              {data.no_positive_upside.map((card) => (
                <NoSignalRow key={card.symbol} card={card} />
              ))}
            </div>
          )}
        </CardBody>
        <CardFooter>
          <span>Prices may be delayed; each row keeps its provider timestamp.</span>
          <span>{data.data_quality.quote_source || "Source unavailable"}</span>
        </CardFooter>
      </Card>

      {data.insufficient_data.length > 0 && (
        <Card>
          <CardHeader
            title="Insufficient data"
            description="These constituents could not be analysed. No price, target or confidence is invented for them."
            icon={Info}
          />
          <CardBody className="space-y-1.5 pt-2">
            {data.insufficient_data.map((card) => (
              <div key={card.symbol} className="rounded-lg bg-amber-50/60 px-3 py-2 text-[11px]">
                <span className="font-mono font-semibold text-slate-700">{card.symbol}</span>{" "}
                <span className="text-slate-600">{card.name}</span>
                <p className="mt-0.5 text-[10.5px] text-amber-800">{card.risks.join(" ")}</p>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      <div id="methodology" className="grid scroll-mt-24 gap-3 lg:grid-cols-3">
        <Card>
          <CardHeader title="Methodology" description={`Version ${data.methodology.version}`} icon={Info} />
          <CardBody className="space-y-2 pt-2 text-[10.5px] leading-relaxed text-slate-500">
            <p>
              <strong className="font-semibold text-slate-700">Target:</strong> {data.methodology.target}
            </p>
            <p>
              <strong className="font-semibold text-slate-700">Upside:</strong> {data.methodology.upside}
            </p>
            <p>
              <strong className="font-semibold text-slate-700">Confidence:</strong>{" "}
              {data.methodology.confidence}
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Facts vs estimates" description="What is observed and what is modelled." icon={Target} />
          <CardBody className="space-y-2 pt-2 text-[10.5px] leading-relaxed text-slate-500">
            <p>{data.methodology.inputs}</p>
            <p>{data.methodology.analyst_opinions}</p>
            <p className="rounded-lg bg-slate-50 px-2.5 py-2 text-[10px] text-slate-500">
              {data.fundamentals.note}
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Data provenance" description="Source, freshness and coverage." icon={AlertTriangle} />
          <CardBody className="space-y-1.5 pt-2 text-[10.5px] text-slate-500">
            <p>
              <span className="text-slate-400">Quotes:</span>{" "}
              {data.data_quality.quote_source || "unavailable"} · mode{" "}
              {data.data_quality.quote_mode || "unavailable"}
            </p>
            <p>
              <span className="text-slate-400">History:</span> {data.data_quality.history_source}
            </p>
            <p>
              <span className="text-slate-400">Constituents:</span> {data.universe.constituents.name}
              {data.universe.constituents.retrieved_at
                ? ` · ${formatDateTime(data.universe.constituents.retrieved_at)}`
                : " · bundled snapshot"}
            </p>
            <p>
              <span className="text-slate-400">Stale prices:</span> {data.data_quality.stale_prices}
            </p>
            {data.data_quality.errors.length > 0 && (
              <ul className="list-disc pl-4 text-[10px] text-amber-700">
                {data.data_quality.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            )}
            <p className="text-[10px]">{data.data_quality.note}</p>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
