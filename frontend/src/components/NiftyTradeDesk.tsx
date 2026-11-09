import { useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  KeyRound,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import type { Nifty50Desk, Nifty50Stock } from "../lib/types";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CopyButton,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
  TBody,
  TD,
  TH,
  THead,
  TR,
  TableWrap,
} from "./ui";
import { DataModeBadge } from "./DataMode";
import { TradeTicketModal, type TradeSubject } from "./TradeTicketModal";
import { moneyExact, plainPct } from "../lib/utils";

export function NiftyTradeDesk({
  headroom,
  currency,
  onOrderCreated,
}: {
  headroom: number;
  currency: string;
  onOrderCreated?: () => void;
}) {
  const desk = useApi<Nifty50Desk>("/research/nifty50");
  const [search, setSearch] = useState("");
  const [trade, setTrade] = useState<{ subject: TradeSubject; side: "buy" | "sell" } | null>(
    null,
  );
  const items = useMemo(() => desk.data?.items ?? [], [desk.data]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) =>
      [item.symbol, item.name, item.sector, item.instrument_key]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [items, search]);

  const csv = useMemo(
    () => ["symbol,instrument_key", ...items.map((item) => `${item.symbol},${item.instrument_key}`)].join("\n"),
    [items],
  );

  const openTicket = (item: Nifty50Stock, side: "buy" | "sell") => {
    const quote = item.quote;
    setTrade({
      side,
      subject: {
        kind: "stock",
        symbol: item.symbol,
        name: item.name,
        subtitle: `${item.sector} · ${item.exchange}`,
        price: quote?.price ?? null,
        currency: quote?.currency || currency,
        dataMode: quote?.data_mode ?? "unavailable",
        source: quote?.source,
      },
    });
  };

  return (
    <Card>
      <CardHeader
        title="NIFTY 50 trade desk"
        description="Every NIFTY 50 constituent with its public Upstox instrument key. Buy and sell open an order ticket that requires owner approval; execution is simulated unless live Upstox trading is explicitly selected."
        icon={KeyRound}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            {desk.data && (
              <>
                <Badge tone="blue">{desk.data.total} stocks</Badge>
                <Badge tone={desk.data.modes.live > 0 ? "green" : "slate"}>
                  {desk.data.modes.live > 0
                    ? `${desk.data.modes.live} live`
                    : `${desk.data.modes.demo} demo`}
                </Badge>
                <CopyButton
                  value={csv}
                  label="Copy CSV"
                  ariaLabel="Copy all NIFTY 50 stock instrument keys as CSV"
                />
              </>
            )}
            <Button
              variant="outline"
              size="sm"
              icon={RefreshCw}
              onClick={desk.reload}
              loading={desk.loading}
            >
              Refresh
            </Button>
          </div>
        }
      />

      {desk.loading && !desk.data ? (
        <CardBody className="space-y-3">
          <Skeleton className="h-9 w-full" />
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </CardBody>
      ) : desk.error && !desk.data ? (
        <CardBody>
          <ErrorState message={desk.error} onRetry={desk.reload} />
        </CardBody>
      ) : desk.data ? (
        <>
          <CardBody className="space-y-3 pt-4">
            {!desk.data.provider.upstox_configured && (
              <Callout tone="amber" title="Live Upstox quotes are not configured" icon={ShieldAlert}>
                The backend has no Upstox access token, so every price below is clearly labelled{" "}
                <strong>DEMO</strong> and is not market data. Add <code>UPSTOX_ACCESS_TOKEN</code>{" "}
                to the backend environment to switch this desk to live Upstox quotes. Without a live
                quote, the trade ticket stays simulated and live execution is unavailable.
              </Callout>
            )}
            {desk.data.provider.provider_errors.length > 0 && (
              <Callout tone="amber" title="Upstox quote refresh reported an issue">
                {desk.data.provider.provider_errors[0]} Existing quotes keep their own data mode
                and timestamp; stale rows are marked.
              </Callout>
            )}

            <div className="relative max-w-sm">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search symbol, company, sector or token"
                aria-label="Search NIFTY 50 stocks"
                className="h-9 pl-8 text-xs"
              />
            </div>

            {filtered.length === 0 ? (
              <EmptyState
                title="No matching stock"
                description="Try a symbol such as HDFCBANK, a company name or part of an instrument key."
                icon={Search}
              />
            ) : (
              <div className="max-h-[620px] overflow-auto rounded-lg border border-slate-100">
                <div className="space-y-1.5 p-2 md:hidden">
                  {filtered.map((item) => {
                    const quote = item.quote;
                    const up = (quote?.change_pct ?? 0) >= 0;
                    return (
                      <div key={item.symbol} className="rounded-lg border border-slate-100 bg-white p-3">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <p className="text-sm font-semibold text-ink-900">{item.symbol}</p>
                            <p className="text-[10px] text-slate-400">{item.name}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-sm font-semibold text-ink-900">
                              {quote?.price != null
                                ? moneyExact(quote.price, quote.currency)
                                : "—"}
                            </p>
                            {quote?.change_pct != null && (
                              <p
                                className={`inline-flex items-center gap-0.5 text-[10px] font-semibold ${
                                  up ? "text-emerald-600" : "text-rose-600"
                                }`}
                              >
                                {up ? (
                                  <ArrowUpRight className="h-3 w-3" />
                                ) : (
                                  <ArrowDownRight className="h-3 w-3" />
                                )}
                                {plainPct(Math.abs(quote.change_pct), 2)}
                              </p>
                            )}
                          </div>
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <Badge tone="slate">{item.sector}</Badge>
                          <DataModeBadge mode={quote?.data_mode ?? "unavailable"} />
                          {item.signal_available && <Badge tone="violet">Model signal</Badge>}
                        </div>
                        <p className="mt-2 break-all font-mono text-[9px] text-slate-400">
                          {item.instrument_key}
                        </p>
                        <div className="mt-2 grid grid-cols-2 gap-2">
                          <Button
                            size="sm"
                            variant="success"
                            onClick={() => openTicket(item, "buy")}
                            disabled={!item.tradable}
                          >
                            Buy
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => openTicket(item, "sell")}
                            disabled={!item.tradable}
                          >
                            Sell
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="hidden md:block">
                  <TableWrap>
                    <THead>
                      <TR className="bg-slate-50/90">
                        <TH className="sticky top-0 z-10 bg-slate-50">Stock</TH>
                        <TH className="sticky top-0 z-10 bg-slate-50">Sector</TH>
                        <TH className="sticky top-0 z-10 bg-slate-50 text-right">Price</TH>
                        <TH className="sticky top-0 z-10 bg-slate-50 text-right">Change</TH>
                        <TH className="sticky top-0 z-10 bg-slate-50">Data</TH>
                        <TH className="sticky top-0 z-10 bg-slate-50">Research</TH>
                        <TH className="sticky top-0 z-10 bg-slate-50 text-right">Trade</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {filtered.map((item) => {
                        const quote = item.quote;
                        const up = (quote?.change_pct ?? 0) >= 0;
                        return (
                          <TR key={item.symbol}>
                            <TD>
                              <p className="font-semibold text-ink-900">{item.symbol}</p>
                              <p className="text-[10px] text-slate-400">{item.name}</p>
                              <p className="font-mono text-[9px] text-slate-400">{item.instrument_key}</p>
                            </TD>
                            <TD className="text-[11px] text-slate-500">{item.sector}</TD>
                            <TD className="text-right font-semibold tabular-nums text-ink-900">
                              {quote?.price != null
                                ? moneyExact(quote.price, quote.currency)
                                : "—"}
                            </TD>
                            <TD
                              className={`text-right text-[11px] font-semibold tabular-nums ${
                                quote?.change_pct == null
                                  ? "text-slate-400"
                                  : up
                                  ? "text-emerald-600"
                                  : "text-rose-600"
                              }`}
                            >
                              {quote?.change_pct != null
                                ? `${up ? "+" : "-"}${plainPct(Math.abs(quote.change_pct), 2)}`
                                : "—"}
                            </TD>
                            <TD>
                              <DataModeBadge mode={quote?.data_mode ?? "unavailable"} />
                            </TD>
                            <TD>
                              {item.signal_available ? (
                                <Badge tone="violet">Model signal</Badge>
                              ) : (
                                <span className="text-[10px] text-slate-400">Quote only</span>
                              )}
                            </TD>
                            <TD>
                              <div className="flex justify-end gap-1.5">
                                <Button
                                  size="sm"
                                  variant="success"
                                  onClick={() => openTicket(item, "buy")}
                                  disabled={!item.tradable}
                                >
                                  Buy
                                </Button>
                                <Button
                                  size="sm"
                                  variant="danger"
                                  onClick={() => openTicket(item, "sell")}
                                  disabled={!item.tradable}
                                >
                                  Sell
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

            <p className="text-[10px] text-slate-400">
              Showing {filtered.length} of {desk.data.total} constituents · {desk.data.tradable}{" "}
              priced · {desk.data.modes.demo} demo · {desk.data.modes.live} live ·{" "}
              {desk.data.modes.stale} stale.
            </p>
          </CardBody>
          <CardFooter>
            <span>{desk.data.provider.note}</span>
            <span>{desk.data.orders_note}</span>
          </CardFooter>
        </>
      ) : null}

      <TradeTicketModal
        subject={trade?.subject ?? null}
        initialSide={trade?.side ?? "buy"}
        headroom={headroom}
        open={Boolean(trade)}
        onClose={() => setTrade(null)}
        onCreated={onOrderCreated}
      />
    </Card>
  );
}
