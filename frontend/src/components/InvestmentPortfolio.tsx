import { useEffect } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  BriefcaseBusiness,
  Info,
  RefreshCw,
  Wallet,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import type { InvestmentPortfolio as PortfolioPayload } from "../lib/types";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  EmptyState,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "./ui";
import { DataModeBadge } from "./DataMode";
import { formatDateTime, money, moneyExact, plainPct } from "../lib/utils";

const ALLOCATION_TONES = [
  "bg-brand-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-violet-500",
  "bg-sky-500",
  "bg-rose-500",
  "bg-slate-400",
];

function signed(value: number | null | undefined, currency: string): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${moneyExact(Math.abs(value), currency)}`;
}

function pnlTone(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-slate-400";
  if (value > 0) return "text-emerald-600";
  if (value < 0) return "text-rose-600";
  return "text-slate-500";
}

export function InvestmentPortfolio() {
  const portfolio = useApi<PortfolioPayload>("/research/portfolio", { pollMs: 60000 });

  useEffect(() => {
    const reload = () => portfolio.reload();
    window.addEventListener("finovexa:portfolio-changed", reload);
    return () => window.removeEventListener("finovexa:portfolio-changed", reload);
  }, [portfolio.reload]);

  const data = portfolio.data;
  const currency = data?.totals.currency || "INR";
  const up = (data?.totals.pnl ?? 0) >= 0;

  return (
    <Card>
      <CardHeader
        title="Your investment portfolio"
        description="A separate practice portfolio, valued with the latest NSE prices. It is not your business cash."
        icon={BriefcaseBusiness}
        actions={
          <>
            <DataModeBadge mode={data?.data_mode} />
            {data?.is_simulated && <Badge tone="violet">SIMULATED HOLDINGS</Badge>}
            <Button
              variant="outline"
              size="sm"
              icon={RefreshCw}
              onClick={portfolio.reload}
              loading={portfolio.loading}
            >
              Refresh
            </Button>
          </>
        }
      />

      <CardBody className="space-y-4 pt-4">
        {portfolio.error && !data && (
          <Callout tone="red" title="Portfolio values are unavailable">
            {portfolio.error} No price has been invented to fill the gap.
          </Callout>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
              <div className="rounded-xl border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Worth today
                </p>
                <p className="mt-1 text-lg font-semibold tabular-nums text-ink-900">
                  {money(data.totals.current_value, currency)}
                </p>
                <p className="text-[10px] text-slate-400">
                  {data.totals.priced} of {data.totals.holdings} holdings priced
                </p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  You paid
                </p>
                <p className="mt-1 text-lg font-semibold tabular-nums text-ink-900">
                  {money(data.totals.invested, currency)}
                </p>
                <p className="text-[10px] text-slate-400">average buy value</p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Profit / loss
                </p>
                <p className={`mt-1 text-lg font-semibold tabular-nums ${up ? "text-emerald-600" : "text-rose-600"}`}>
                  {signed(data.totals.pnl, currency)}
                </p>
                <p className={`text-[10px] ${up ? "text-emerald-600" : "text-rose-600"}`}>
                  {data.totals.pnl_pct !== null ? `${up ? "+" : ""}${plainPct(data.totals.pnl_pct, 2)} overall` : "Not priced"}
                </p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Move today
                </p>
                <p className={`mt-1 flex items-center gap-1 text-lg font-semibold tabular-nums ${pnlTone(data.totals.day_change)}`}>
                  {data.totals.day_change >= 0 ? (
                    <ArrowUpRight className="h-4 w-4" />
                  ) : (
                    <ArrowDownRight className="h-4 w-4" />
                  )}
                  {signed(data.totals.day_change, currency)}
                </p>
                <p className="text-[10px] text-slate-400">since the previous close</p>
              </div>
            </div>

            <div className="flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
              <span>
                <strong className="text-slate-600">In plain words:</strong> at today&apos;s delayed prices,
                these {data.totals.holdings} holdings would be worth{" "}
                {money(data.totals.current_value, currency)}
                {data.totals.holdings > 0 && data.totals.pnl_pct !== null
                  ? ` — ${up ? "a gain" : "a loss"} of ${plainPct(Math.abs(data.totals.pnl_pct), 2)} on what you paid.`
                  : "."}{" "}
                Your recorded business cash of {money(data.totals.recorded_cash, currency)} is kept separate.
              </span>
            </div>

            {data.allocation.length > 0 && (
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <p className="text-[11px] font-semibold text-slate-600">Spread across sectors</p>
                  <span className="flex items-center gap-1 text-[10px] text-slate-400">
                    <Wallet className="h-3 w-3" />
                    cash + investments {money(data.totals.cash_plus_investments, currency)}
                  </span>
                </div>
                <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                  {data.allocation.map((item, index) => (
                    <div
                      key={item.sector}
                      className={ALLOCATION_TONES[index % ALLOCATION_TONES.length]}
                      style={{ width: `${item.share_pct}%` }}
                      title={`${item.sector}: ${item.share_pct}%`}
                    />
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {data.allocation.map((item, index) => (
                    <span
                      key={item.sector}
                      className="inline-flex items-center gap-1.5 rounded-full border border-slate-100 bg-white px-2 py-0.5 text-[10px] text-slate-500"
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${ALLOCATION_TONES[index % ALLOCATION_TONES.length]}`}
                      />
                      {item.sector} · {plainPct(item.share_pct, 1)}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {data.holdings.length === 0 ? (
              <EmptyState
                title="No holdings yet"
                description="Approve and fill a simulated order in the trade desk, or reset the demo, and the practice portfolio will show it here."
                icon={BriefcaseBusiness}
              />
            ) : (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Stock</TH>
                    <TH className="text-right">Qty</TH>
                    <TH className="hidden text-right sm:table-cell">Avg. cost</TH>
                    <TH className="text-right">Price now</TH>
                    <TH className="text-right">Worth now</TH>
                    <TH className="text-right">Profit / loss</TH>
                    <TH className="hidden text-right xl:table-cell">Today</TH>
                  </TR>
                </THead>
                <TBody>
                  {data.holdings.map((holding) => (
                    <TR key={holding.symbol}>
                      <TD>
                        <p className="font-semibold text-ink-900">{holding.name}</p>
                        <p className="flex items-center gap-1.5 text-[10px] text-slate-400">
                          {holding.symbol} · {holding.sector || "No sector"}
                          <Badge tone={holding.source === "demo_seed" ? "slate" : "violet"}>
                            {holding.source === "demo_seed" ? "DEMO" : "SIM"}
                          </Badge>
                        </p>
                      </TD>
                      <TD className="text-right tabular-nums">{holding.quantity}</TD>
                      <TD className="hidden text-right tabular-nums text-slate-500 sm:table-cell">
                        {moneyExact(holding.average_cost, currency)}
                      </TD>
                      <TD className="text-right tabular-nums">
                        {holding.price !== null ? (
                          <>
                            <p className="font-medium text-ink-900">
                              {moneyExact(holding.price, currency)}
                            </p>
                            <p className="text-[9px] text-slate-400">
                              {holding.is_stale ? "stale" : "delayed"}
                            </p>
                          </>
                        ) : (
                          <span className="text-slate-400">Unavailable</span>
                        )}
                      </TD>
                      <TD className="text-right tabular-nums font-medium text-ink-900">
                        {holding.value !== null ? moneyExact(holding.value, currency) : "—"}
                      </TD>
                      <TD className={`text-right tabular-nums font-semibold ${pnlTone(holding.pnl)}`}>
                        <p>{signed(holding.pnl, currency)}</p>
                        {holding.pnl_pct !== null && (
                          <p className="text-[9px] font-medium">
                            {holding.pnl_pct >= 0 ? "+" : ""}
                            {plainPct(holding.pnl_pct, 2)}
                          </p>
                        )}
                      </TD>
                      <TD className={`hidden text-right tabular-nums xl:table-cell ${pnlTone(holding.day_change)}`}>
                        {holding.change_pct !== null ? (
                          <>
                            <p>{signed(holding.day_change, currency)}</p>
                            <p className="text-[9px]">
                              {holding.change_pct >= 0 ? "+" : ""}
                              {plainPct(holding.change_pct, 2)}
                            </p>
                          </>
                        ) : (
                          "—"
                        )}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            )}

            {data.provider.errors.length > 0 && (
              <Callout tone="amber" title="Some prices could not be refreshed">
                {data.provider.errors.join(" ")} Existing values are shown with their own freshness label.
              </Callout>
            )}
          </>
        )}
      </CardBody>

      <CardFooter>
        <span>
          Prices {data?.price_source || "unavailable"} · {formatDateTime(data?.price_as_of)}
        </span>
        <span>Simulated fills update this portfolio only · no real money moves</span>
      </CardFooter>
    </Card>
  );
}
