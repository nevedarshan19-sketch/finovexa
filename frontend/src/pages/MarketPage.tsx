import { useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Building2,
  Coins,
  ExternalLink,
  Globe2,
  Info,
  LineChart,
  Newspaper,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import type { MarketHistory, MarketOverview, NewsResponse, Quote } from "../lib/types";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Checkbox,
  EmptyState,
  ErrorState,
  PageHeader,
  PageSkeleton,
  Tabs,
} from "../components/ui";
import { DataModeBadge, DataModeLegend } from "../components/DataMode";
import { NiftyRecommendations } from "../components/NiftyRecommendations";
import { PriceAreaChart } from "../components/Charts";
import {
  formatDate,
  formatDateTime,
  moneyExact,
  number,
  pct,
  plainPct,
  timeAgo,
  titleCase,
} from "../lib/utils";

type GroupFilter = "all" | "metals" | "indices" | "equities";

function groupIcon(assetClass: string) {
  if (assetClass === "metal") return Coins;
  if (assetClass === "index") return BarChart3;
  return Building2;
}

function quoteValue(quote: Quote): string {
  if (quote.price === null) return "Unavailable";
  if (quote.asset_class === "equity" || quote.asset_class === "metal") {
    return moneyExact(quote.price, quote.currency);
  }
  return number(quote.price, 2);
}

function QuoteCard({ quote, active, onSelect }: { quote: Quote; active: boolean; onSelect: () => void }) {
  const Icon = groupIcon(quote.asset_class);
  const positive = (quote.change_pct ?? 0) >= 0;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group flex w-full flex-col rounded-xl border p-3.5 text-left transition ${
        active
          ? "border-brand-300 bg-brand-50/40 ring-1 ring-brand-200"
          : "border-slate-200 bg-white hover:border-slate-300 hover:shadow-card"
      }`}
      aria-pressed={active}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500 group-hover:bg-white">
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </span>
        <DataModeBadge mode={quote.data_mode} showDot={false} />
      </div>
      <p className="mt-2.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{quote.symbol}</p>
      <p className="truncate text-xs font-medium text-ink-900">{quote.name}</p>
      <p className="mt-2 text-lg font-semibold tracking-tight text-ink-900">
        {quoteValue(quote)}
        {quote.price !== null && quote.asset_class !== "equity" && quote.asset_class !== "metal" && (
          <span className="ml-1 text-[10px] font-normal text-slate-400">{quote.unit}</span>
        )}
      </p>
      <div className="mt-1 flex items-center justify-between gap-2">
        {quote.change_pct !== null ? (
          <span className={`inline-flex items-center gap-0.5 text-[11px] font-semibold ${positive ? "text-emerald-600" : "text-rose-600"}`}>
            {positive ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {pct(quote.change_pct, 2)}
          </span>
        ) : (
          <span className="text-[11px] text-slate-400">No change data</span>
        )}
        <span className="text-[9px] text-slate-400">{quote.is_stale ? "STALE" : quote.freshness}</span>
      </div>
      <p className="mt-1.5 truncate border-t border-slate-100 pt-1.5 text-[9px] text-slate-400">
        {quote.source || "No verified source"} · {quote.as_of ? timeAgo(quote.as_of) : "no timestamp"}
      </p>
    </button>
  );
}

export function MarketPage() {
  const overview = useApi<MarketOverview>("/market/overview");
  const news = useApi<NewsResponse>("/market/news?limit=20");
  const [view, setView] = useState<"overview" | "nifty50">("overview");
  const [filter, setFilter] = useState<GroupFilter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [historyDays, setHistoryDays] = useState("90");
  const [relatedOnly, setRelatedOnly] = useState(false);

  const data = overview.data;
  const activeSymbol = selected ?? data?.items[0]?.symbol ?? null;
  const history = useApi<MarketHistory>(
    activeSymbol ? `/market/instruments/${activeSymbol}/history?days=${historyDays}` : null,
  );

  const activeQuote = useMemo(
    () => data?.items.find((quote) => quote.symbol === activeSymbol) ?? null,
    [data, activeSymbol],
  );

  const visibleQuotes = useMemo(() => {
    if (!data) return [];
    if (filter === "all") return data.items;
    return data.groups[filter];
  }, [data, filter]);

  const visibleNews = useMemo(() => {
    const items = news.data?.items ?? [];
    if (!relatedOnly || !activeSymbol) return items;
    return items.filter((article) => article.instruments.includes(activeSymbol));
  }, [news.data, relatedOnly, activeSymbol]);

  const refresh = () => {
    overview.reload();
    news.reload();
    history.reload();
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Market intelligence"
        title="Context for the cash you deploy"
        description="Screen every NIFTY 50 constituent with stated reasoning, or inspect gold, silver, Indian indices and large-cap quotes. Nothing here is investment advice."
        actions={
          view === "overview" ? (
            <>
              <div className="hidden items-center gap-1.5 sm:flex">
                <DataModeBadge mode="live" showDot={false} />
                <DataModeBadge mode="demo" showDot={false} />
                <DataModeBadge mode="stale" showDot={false} />
              </div>
              <Button variant="outline" size="md" icon={RefreshCw} onClick={refresh} loading={overview.loading}>
                Refresh quotes
              </Button>
            </>
          ) : undefined
        }
      />

      <Tabs
        items={[
          { key: "overview", label: "Market overview" },
          { key: "nifty50", label: "NIFTY 50 recommendations", count: 50 },
        ]}
        value={view}
        onChange={setView}
      />

      {view === "nifty50" ? (
        <NiftyRecommendations embedded />
      ) : overview.loading && !data ? (
        <PageSkeleton cards={4} />
      ) : overview.error && !data ? (
        <ErrorState message={overview.error} onRetry={refresh} />
      ) : !data ? null : (
        <>
      <Callout tone={data.summary.provider_errors.length ? "amber" : "blue"} title="Provider status" icon={Info}>
        <p>{data.summary.mode_note}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px]">
          <Badge tone={data.summary.upstox_configured ? "green" : "slate"}>
            Upstox {data.summary.upstox_configured ? "configured" : "demo mode"}
          </Badge>
          <Badge tone={data.summary.metals_configured ? "green" : "slate"}>
            Metals {data.summary.metals_configured ? "live feed" : "demo feed"}
          </Badge>
          <Badge tone="blue">{data.summary.live_count} live</Badge>
          <Badge tone="slate">{data.summary.demo_count} demo</Badge>
          {data.summary.stale_count > 0 && <Badge tone="amber">{data.summary.stale_count} stale</Badge>}
        </div>
        {data.summary.provider_errors.length > 0 && (
          <ul className="mt-1.5 list-disc pl-4 text-[10px]">
            {data.summary.provider_errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}
      </Callout>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          items={[
            { key: "all", label: "All markets", count: data.items.length },
            { key: "metals", label: "Metals", count: data.groups.metals.length },
            { key: "indices", label: "India indices", count: data.groups.indices.length },
            { key: "equities", label: "Equities", count: data.groups.equities.length },
          ]}
          value={filter}
          onChange={setFilter}
        />
        <p className="text-[10px] text-slate-400">
          Quotes as of {formatDateTime(data.as_of)} · click a card to chart it
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {visibleQuotes.map((quote) => (
          <QuoteCard
            key={quote.symbol}
            quote={quote}
            active={quote.symbol === activeSymbol}
            onSelect={() => setSelected(quote.symbol)}
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-8">
          <CardHeader
            title={
              activeQuote ? (
                <span className="flex flex-wrap items-center gap-2">
                  {activeQuote.name} <span className="text-xs font-normal text-slate-400">{activeQuote.symbol}</span>
                  <DataModeBadge mode={activeQuote.data_mode} />
                  {activeQuote.is_stale && <Badge tone="amber">STALE</Badge>}
                </span>
              ) : (
                "Price history"
              )
            }
            description={
              activeQuote
                ? `${activeQuote.exchange} · ${activeQuote.currency} · ${activeQuote.unit}${activeQuote.sector ? ` · ${activeQuote.sector}` : ""}`
                : "Select an instrument"
            }
            icon={LineChart}
            actions={
              <Tabs
                size="sm"
                items={[
                  { key: "30", label: "30D" },
                  { key: "90", label: "90D" },
                  { key: "180", label: "180D" },
                ]}
                value={historyDays}
                onChange={setHistoryDays}
              />
            }
          />
          <CardBody className="pt-3">
            {history.error && (
              <Callout tone="red" title="History unavailable" className="mb-3">
                {history.error}
              </Callout>
            )}
            {history.data?.provider_error && (
              <Callout tone="amber" title="Live provider issue · showing labelled fallback" className="mb-3">
                {history.data.provider_error}
              </Callout>
            )}
            {history.loading && !history.data ? (
              <div className="h-[280px] animate-pulse rounded-xl bg-slate-100" />
            ) : history.data && history.data.candles.length > 0 ? (
              <PriceAreaChart
                data={history.data.candles.map((candle) => ({ date: candle.date, close: candle.close }))}
                currency={history.data.currency}
              />
            ) : (
              <EmptyState
                title="No price history"
                description="No verified historical series exists for this instrument. FINOVEXA will not invent one."
                icon={LineChart}
              />
            )}
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
              <span>
                Source: {history.data?.source || activeQuote?.source || "unavailable"} · mode{" "}
                {history.data?.data_mode || activeQuote?.data_mode || "unavailable"}
              </span>
              <span>Chart shows close prices only; it is not a forecast.</span>
            </div>
          </CardBody>
        </Card>

        <Card className="lg:col-span-4">
          <CardHeader title="Instrument detail" description="Source, freshness and session context." icon={Globe2} />
          <CardBody className="space-y-3 pt-3">
            {activeQuote ? (
              <>
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <p className="text-2xl font-semibold tracking-tight text-ink-900">{quoteValue(activeQuote)}</p>
                    <p className="text-[10px] text-slate-400">
                      Previous close{" "}
                      {activeQuote.previous_close !== null ? quoteValue({ ...activeQuote, price: activeQuote.previous_close }) : "—"}
                    </p>
                  </div>
                  {activeQuote.change_pct !== null && (
                    <span
                      className={`rounded-lg px-2 py-1 text-xs font-semibold ${
                        activeQuote.change_pct >= 0 ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
                      }`}
                    >
                      {pct(activeQuote.change_pct, 2)}
                    </span>
                  )}
                </div>
                <div className="space-y-1.5 rounded-lg border border-slate-100 bg-slate-50/70 p-3 text-[11px]">
                  {[
                    ["Data mode", activeQuote.data_mode.toUpperCase()],
                    ["Freshness", activeQuote.freshness],
                    ["Age", activeQuote.age_minutes !== null ? `${activeQuote.age_minutes} min` : "unknown"],
                    ["Source", activeQuote.source || "not available"],
                    ["As of", activeQuote.as_of ? formatDateTime(activeQuote.as_of) : "not available"],
                    ["Session", activeQuote.session_status || "not reported"],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between gap-2">
                      <span className="text-slate-400">{label}</span>
                      <span className="max-w-[65%] truncate text-right font-medium capitalize text-slate-700">{value}</span>
                    </div>
                  ))}
                </div>
                {activeQuote.is_stale && (
                  <Callout tone="amber" title="This quote is stale">
                    Last verified update is older than the freshness window. Treat the price as historical context.
                  </Callout>
                )}
                {activeQuote.note && <p className="text-[10px] leading-relaxed text-slate-400">{activeQuote.note}</p>}
                <div className="flex flex-wrap gap-1.5">
                  <Badge tone="slate">{titleCase(activeQuote.asset_class)}</Badge>
                  <Badge tone="slate">{activeQuote.exchange}</Badge>
                  {activeQuote.sector && <Badge tone="slate">{activeQuote.sector}</Badge>}
                </div>
              </>
            ) : (
              <EmptyState title="No instrument selected" description="Choose a quote card to see detail." />
            )}
          </CardBody>
          <CardFooter>
            <span>{data.items.length} instruments tracked</span>
            <span>{data.summary.stale_count} stale</span>
          </CardFooter>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Market news & announcements"
          description={news.data?.dedupe_note || "Articles are deduplicated and attributed to their source."}
          icon={Newspaper}
          actions={
            <div className="flex flex-wrap items-center gap-3">
              <Checkbox
                checked={relatedOnly}
                onChange={setRelatedOnly}
                label={<span className="text-[11px]">Only {activeSymbol || "selected"}</span>}
                disabled={!activeSymbol}
              />
              <Button variant="outline" size="sm" icon={RefreshCw} onClick={() => news.reload()} loading={news.loading}>
                Refresh
              </Button>
            </div>
          }
        />
        <CardBody className="pt-3">
          <Callout tone="violet" title="External content is untrusted data" icon={ShieldAlert} className="mb-3">
            Headlines and article text are never treated as instructions. FINOVEXA does not execute actions from news,
            and no analyst rating is fabricated when a licensed source is unavailable.
          </Callout>
          {news.error && <Callout tone="red">{news.error}</Callout>}
          {news.data?.provider_error && (
            <Callout tone="amber" title="News provider unavailable" className="mb-3">
              {news.data.provider_error} Showing labelled demo articles instead.
            </Callout>
          )}
          {news.loading && !news.data ? (
            <div className="h-40 animate-pulse rounded-xl bg-slate-100" />
          ) : visibleNews.length === 0 ? (
            <EmptyState
              title="No articles for this instrument"
              description="No verified coverage is stored for this filter. FINOVEXA does not invent headlines."
              icon={Newspaper}
              action={
                relatedOnly ? (
                  <Button variant="outline" size="sm" onClick={() => setRelatedOnly(false)}>
                    Show all market news
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {visibleNews.map((article) => (
                <article key={article.id} className="flex h-full flex-col rounded-xl border border-slate-100 p-4 transition hover:border-slate-200">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <DataModeBadge mode={article.data_mode} showDot={false} />
                    <Badge tone="slate">{article.source}</Badge>
                    <span className="ml-auto text-[10px] text-slate-400">{timeAgo(article.published_at)}</span>
                  </div>
                  <h3 className="mt-2 text-[13px] font-semibold leading-snug text-ink-900">{article.title}</h3>
                  <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-slate-500">{article.summary}</p>
                  {article.implications && (
                    <p className="mt-2 rounded-lg bg-brand-50/60 px-2.5 py-1.5 text-[10px] leading-relaxed text-brand-900">
                      <span className="font-semibold">Context:</span> {article.implications}
                    </p>
                  )}
                  {article.risks && (
                    <p className="mt-1 text-[10px] leading-relaxed text-amber-700">
                      <span className="font-semibold">Risks:</span> {article.risks}
                    </p>
                  )}
                  <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-2.5">
                    {article.instruments.map((symbol) => (
                      <button
                        key={symbol}
                        type="button"
                        onClick={() => setSelected(symbol)}
                        className="rounded border border-slate-200 px-1.5 py-0.5 text-[9px] font-medium text-slate-500 hover:border-brand-300 hover:text-brand-600"
                      >
                        {symbol}
                      </button>
                    ))}
                    {article.url && (
                      <a
                        href={article.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ml-auto inline-flex items-center gap-1 text-[10px] font-semibold text-brand-600 hover:text-brand-700"
                      >
                        Source <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                  <p className="mt-2 border-t border-slate-100 pt-1.5 text-[9px] text-slate-400">
                    {article.analysis_note}
                  </p>
                </article>
              ))}
            </div>
          )}
        </CardBody>
        <CardFooter>
          <span>{news.data?.provider_note || "Source attribution and verification notes are shown per article."}</span>
          <span>{visibleNews.length} articles</span>
        </CardFooter>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Data modes" description="Every market value carries a verification label." icon={ShieldCheck} />
          <CardBody className="pt-3">
            <DataModeLegend
              modes={[
                { mode: "live", meaning: "Fetched from a configured provider within the freshness window." },
                { mode: "demo", meaning: "Seeded sample values for the demo workspace." },
                { mode: "stale", meaning: "Last verified value is older than the freshness window." },
                { mode: "unavailable", meaning: "Provider failed and no fallback exists. No price is fabricated." },
              ]}
            />
          </CardBody>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="How to read this page" icon={Info} />
          <CardBody className="grid gap-3 pt-3 text-[11px] leading-relaxed text-slate-500 sm:grid-cols-2">
            <p>
              <strong className="font-semibold text-slate-700">Prices are context, not signals.</strong> FINOVEXA shows
              market prices to inform research conversations. It does not recommend buying or selling.
            </p>
            <p>
              <strong className="font-semibold text-slate-700">Freshness matters.</strong> A DEMO or STALE quote is
              never presented as live. Provider failures fall back to labelled demo data or report unavailable.
            </p>
            <p>
              <strong className="font-semibold text-slate-700">News is untrusted input.</strong> Articles are
              summarized for context. They cannot issue instructions to the assistant or trigger actions.
            </p>
            <p>
              <strong className="font-semibold text-slate-700">No analyst ratings.</strong> FINOVEXA does not
              reproduce third-party analyst ratings unless a licensed feed is configured.
            </p>
          </CardBody>
          <CardFooter>
            <span>Last market refresh {formatDate(data.as_of)} · {plainPct(data.summary.live_count / Math.max(1, data.items.length) * 100, 0)} verified live</span>
            <span>Demo workspace data is labelled</span>
          </CardFooter>
        </Card>
      </div>
        </>
      )}
    </div>
  );
}
