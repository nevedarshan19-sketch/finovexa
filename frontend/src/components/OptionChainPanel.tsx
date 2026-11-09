import { useState } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, RefreshCw, ShieldAlert } from "lucide-react";
import { useApi } from "../hooks/useApi";
import type { OptionChain, OptionLeg, OptionStrike } from "../lib/types";
import { TradeTicketModal, type TradeSubject } from "./TradeTicketModal";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ErrorState,
  Select,
  Skeleton,
  TBody,
  TD,
  TH,
  THead,
  TR,
  TableWrap,
} from "./ui";
import { DataModeBadge } from "./DataMode";
import {
  compactNumber,
  formatDateTime,
  moneyExact,
  number,
  plainPct,
  titleCase,
} from "../lib/utils";

const STRIKE_WINDOWS = [11, 21, 31];

function signed(value: number | null): string {
  if (value === null) return "—";
  const formatted = compactNumber(Math.abs(value));
  if (value === 0) return "0";
  return `${value > 0 ? "+" : "-"}${formatted}`;
}

function changeClass(value: number | null): string {
  if (value === null || value === 0) return "text-slate-400";
  return value > 0 ? "text-emerald-600" : "text-rose-600";
}

function LegCells({
  leg,
  side,
  label,
  onTrade,
}: {
  leg: OptionLeg | null;
  side: "call" | "put";
  label: string;
  onTrade: (action: "buy" | "sell") => void;
}) {
  const actions = (
    <TD className="text-right">
      {leg ? (
        <div className="flex justify-end gap-1">
          <button
            type="button"
            aria-label={`Buy ${label}`}
            onClick={() => onTrade("buy")}
            className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-700 hover:bg-emerald-100"
          >
            Buy
          </button>
          <button
            type="button"
            aria-label={`Sell ${label}`}
            onClick={() => onTrade("sell")}
            className="rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-700 hover:bg-rose-100"
          >
            Sell
          </button>
        </div>
      ) : (
        "—"
      )}
    </TD>
  );
  const stats = (
    <>
      <TD className="text-right tabular-nums">{leg ? compactNumber(leg.oi) : "—"}</TD>
      <TD className={`text-right tabular-nums ${changeClass(leg?.oi_change ?? null)}`}>
        {leg ? signed(leg.oi_change) : "—"}
      </TD>
      <TD className="text-right tabular-nums">{leg ? compactNumber(leg.volume) : "—"}</TD>
      <TD className="text-right tabular-nums">{leg?.iv != null ? plainPct(leg.iv, 1) : "—"}</TD>
      <TD className="text-right font-semibold tabular-nums text-ink-900">
        {leg ? moneyExact(leg.ltp, "INR") : "—"}
      </TD>
    </>
  );
  if (side === "call") {
    return (
      <>
        {stats}
        {actions}
      </>
    );
  }
  return (
    <>
      {actions}
      <TD className="text-right font-semibold tabular-nums text-ink-900">
        {leg ? moneyExact(leg.ltp, "INR") : "—"}
      </TD>
      <TD className="text-right tabular-nums">{leg?.iv != null ? plainPct(leg.iv, 1) : "—"}</TD>
      <TD className="text-right tabular-nums">{leg ? compactNumber(leg.volume) : "—"}</TD>
      <TD className={`text-right tabular-nums ${changeClass(leg?.oi_change ?? null)}`}>
        {leg ? signed(leg.oi_change) : "—"}
      </TD>
      <TD className="text-right tabular-nums">{leg ? compactNumber(leg.oi) : "—"}</TD>
    </>
  );
}

export function OptionChainPanel({
  headroom,
  currency,
  onOrderCreated,
}: {
  headroom: number;
  currency: string;
  onOrderCreated?: () => void;
}) {
  const [expiry, setExpiry] = useState("");
  const [strikes, setStrikes] = useState(21);
  const [trade, setTrade] = useState<{ subject: TradeSubject; side: "buy" | "sell" } | null>(
    null,
  );
  const query = `/research/option-chain?strikes=${strikes}${
    expiry ? `&expiry=${encodeURIComponent(expiry)}` : ""
  }`;
  const chain = useApi<OptionChain>(query);
  const data = chain.data;

  const openTrade = (row: OptionStrike, optionType: "call" | "put", action: "buy" | "sell") => {
    if (!data) return;
    const leg = row[optionType];
    if (!leg) return;
    const label = `${Math.round(row.strike)} ${optionType === "call" ? "CE" : "PE"}`;
    const expiryLabel =
      data.expiries.find((item) => item.date === data.selected_expiry)?.label ||
      data.selected_expiry;
    setTrade({
      side: action,
      subject: {
        kind: "option",
        symbol: `NIFTY ${label}`,
        name: `${expiryLabel} · NIFTY ${Math.round(row.strike)} ${
          optionType === "call" ? "Call" : "Put"
        }`,
        subtitle: `Option chain · ${data.lot_size} units per lot`,
        price: leg.ltp,
        currency: data.underlying.currency || currency,
        dataMode: leg.data_mode,
        source: data.source,
        option: {
          expiry: data.selected_expiry,
          strike: row.strike,
          optionType,
          lotSize: data.lot_size,
          instrumentKey: leg.instrument_key,
        },
      },
    });
  };

  return (
    <Card>
      <CardHeader
        title="NIFTY option chain"
        description="Calls and puts by strike for the selected NIFTY expiry. Buy or sell any listed leg; every ticket needs owner approval and is simulated unless live Upstox execution is enabled."
        icon={Activity}
      />

      {chain.loading && !data ? (
        <CardBody className="space-y-3">
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
          <Skeleton className="h-64 w-full" />
        </CardBody>
      ) : chain.error && !data ? (
        <CardBody>
          <ErrorState message={chain.error} onRetry={chain.reload} />
        </CardBody>
      ) : data ? (
        <>
          <CardBody className="space-y-4 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <DataModeBadge mode={data.data_mode} />
              <Select
                aria-label="Option expiry"
                value={expiry || data.selected_expiry}
                onChange={(event) => setExpiry(event.target.value)}
                className="h-9 w-auto min-w-[176px] py-1 text-xs"
              >
                {data.expiries.map((item) => (
                  <option key={item.date} value={item.date}>
                    {item.label} · {titleCase(item.kind)} ({item.days_to_expiry}d)
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Number of strikes"
                value={strikes}
                onChange={(event) => setStrikes(Number(event.target.value))}
                className="h-9 w-auto py-1 text-xs"
              >
                {STRIKE_WINDOWS.map((count) => (
                  <option key={count} value={count}>
                    ±{(count - 1) / 2} strikes
                  </option>
                ))}
              </Select>
              <Button
                variant="outline"
                size="sm"
                icon={RefreshCw}
                onClick={chain.reload}
                loading={chain.loading}
              >
                Refresh
              </Button>
            </div>

            {data.provider_error && (
              <Callout tone="amber" title="Live option chain unavailable — demo fallback shown" icon={ShieldAlert}>
                {data.provider_error} The chain below is simulated and labelled DEMO. No live option price is shown.
              </Callout>
            )}
            {data.expiry_note && (
              <Callout tone="blue" title="Expiry unavailable">
                {data.expiry_note}
              </Callout>
            )}
            {chain.error && (
              <Callout tone="amber" title="Refresh failed — showing the last loaded chain">
                {chain.error} The rows below are the last successful response for{" "}
                {data.expiries.find((item) => item.date === data.selected_expiry)?.label || data.selected_expiry}.
                Retry before relying on this snapshot.
              </Callout>
            )}

            <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50/70 p-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  NIFTY 50 · {data.expiries.find((item) => item.date === data.selected_expiry)?.label || data.selected_expiry}
                </p>
                <div className="mt-1 flex flex-wrap items-baseline gap-2">
                  <span className="text-2xl font-semibold tracking-tight text-ink-900">
                    {moneyExact(data.underlying.spot, data.underlying.currency)}
                  </span>
                  {data.underlying.change_pct !== null && (
                    <span
                      className={`inline-flex items-center gap-0.5 text-xs font-semibold ${
                        data.underlying.change_pct >= 0 ? "text-emerald-600" : "text-rose-600"
                      }`}
                    >
                      {data.underlying.change_pct >= 0 ? (
                        <ArrowUpRight className="h-3 w-3" />
                      ) : (
                        <ArrowDownRight className="h-3 w-3" />
                      )}
                      {plainPct(Math.abs(data.underlying.change_pct), 2)}
                    </span>
                  )}
                  <Badge tone="slate">{data.underlying.data_mode.toUpperCase()} spot</Badge>
                </div>
                <p className="mt-1 text-[10px] text-slate-400">
                  {data.source} · {formatDateTime(data.as_of)}
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Badge tone="green">ATM {number(data.summary.atm_strike)}</Badge>
                <Badge tone="blue">Highest put OI {number(data.summary.support)}</Badge>
                <Badge tone="red">Highest call OI {number(data.summary.resistance)}</Badge>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <div className="rounded-lg border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">PCR (OI)</p>
                <p className="mt-1 text-lg font-semibold text-ink-900">{number(data.summary.pcr_oi, 2)}</p>
                <p className="mt-0.5 text-[10px] text-slate-400">
                  {data.summary.pcr_oi === null
                    ? "No open interest reported"
                    : data.summary.pcr_oi >= 1
                    ? "Put OI above call OI"
                    : "Call OI above put OI"}
                </p>
              </div>
              <div className="rounded-lg border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Max pain</p>
                <p className="mt-1 text-lg font-semibold text-ink-900">{number(data.summary.max_pain)}</p>
                <p className="mt-0.5 text-[10px] text-slate-400">from {data.summary.strikes_used} strikes</p>
              </div>
              <div className="rounded-lg border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">ATM IV</p>
                <p className="mt-1 text-lg font-semibold text-ink-900">
                  {data.summary.atm_iv !== null ? plainPct(data.summary.atm_iv, 1) : "—"}
                </p>
                <p className="mt-0.5 text-[10px] text-slate-400">call/put average at ATM</p>
              </div>
              <div className="rounded-lg border border-slate-100 bg-white p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Total OI</p>
                <p className="mt-1 text-lg font-semibold text-ink-900">
                  {compactNumber(data.summary.total_call_oi + data.summary.total_put_oi)}
                </p>
                <p className="mt-0.5 text-[10px] text-slate-400">
                  CE {compactNumber(data.summary.total_call_oi)} · PE {compactNumber(data.summary.total_put_oi)}
                </p>
              </div>
            </div>

            <div className="space-y-1.5 md:hidden">
              {data.strikes.map((row) => (
                <div
                  key={row.strike}
                  className={`rounded-lg border p-2.5 ${
                    row.is_atm ? "border-brand-200 bg-brand-50/70" : "border-slate-100 bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="w-[30%] text-left">
                      <p className="text-[9px] font-semibold uppercase tracking-wide text-emerald-600">Call</p>
                      <p className="text-xs font-semibold text-ink-900">{moneyExact(row.call?.ltp, "INR")}</p>
                      <p className="text-[9px] text-slate-400">
                        OI {compactNumber(row.call?.oi)} · IV {row.call?.iv != null ? plainPct(row.call.iv, 1) : "—"}
                      </p>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-semibold tabular-nums text-ink-900">{number(row.strike)}</p>
                      {row.is_atm ? (
                        <Badge tone="blue">ATM</Badge>
                      ) : (
                        <span className="text-[9px] text-slate-400">strike</span>
                      )}
                    </div>
                    <div className="w-[30%] text-right">
                      <p className="text-[9px] font-semibold uppercase tracking-wide text-rose-600">Put</p>
                      <p className="text-xs font-semibold text-ink-900">{moneyExact(row.put?.ltp, "INR")}</p>
                      <p className="text-[9px] text-slate-400">
                        OI {compactNumber(row.put?.oi)} · IV {row.put?.iv != null ? plainPct(row.put.iv, 1) : "—"}
                      </p>
                    </div>
                  </div>
                  <div className="mt-2 grid grid-cols-4 gap-1">
                    <button
                      type="button"
                      onClick={() => openTrade(row, "call", "buy")}
                      disabled={!row.call}
                      className="rounded border border-emerald-200 bg-emerald-50 px-1 py-1 text-[10px] font-semibold text-emerald-700 disabled:opacity-40"
                    >
                      Buy CE
                    </button>
                    <button
                      type="button"
                      onClick={() => openTrade(row, "call", "sell")}
                      disabled={!row.call}
                      className="rounded border border-rose-200 bg-rose-50 px-1 py-1 text-[10px] font-semibold text-rose-700 disabled:opacity-40"
                    >
                      Sell CE
                    </button>
                    <button
                      type="button"
                      onClick={() => openTrade(row, "put", "buy")}
                      disabled={!row.put}
                      className="rounded border border-emerald-200 bg-emerald-50 px-1 py-1 text-[10px] font-semibold text-emerald-700 disabled:opacity-40"
                    >
                      Buy PE
                    </button>
                    <button
                      type="button"
                      onClick={() => openTrade(row, "put", "sell")}
                      disabled={!row.put}
                      className="rounded border border-rose-200 bg-rose-50 px-1 py-1 text-[10px] font-semibold text-rose-700 disabled:opacity-40"
                    >
                      Sell PE
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="hidden md:block">
              <TableWrap className="rounded-lg border border-slate-100">
                <THead>
                  <TR className="bg-slate-50/80">
                    <th colSpan={6} className="table-head text-center text-emerald-700">
                      CALLS (CE)
                    </th>
                    <th className="table-head text-center">STRIKE</th>
                    <th colSpan={6} className="table-head text-center text-rose-700">
                      PUTS (PE)
                    </th>
                  </TR>
                  <TR className="bg-slate-50/80">
                    <TH className="text-right">OI</TH>
                    <TH className="text-right">Chg OI</TH>
                    <TH className="text-right">Volume</TH>
                    <TH className="text-right">IV</TH>
                    <TH className="text-right">LTP</TH>
                    <TH className="text-right">Trade</TH>
                    <TH className="text-center">Strike</TH>
                    <TH className="text-right">Trade</TH>
                    <TH className="text-right">LTP</TH>
                    <TH className="text-right">IV</TH>
                    <TH className="text-right">Volume</TH>
                    <TH className="text-right">Chg OI</TH>
                    <TH className="text-right">OI</TH>
                  </TR>
                </THead>
                <TBody>
                  {data.strikes.map((row) => (
                    <TR key={row.strike} className={row.is_atm ? "bg-brand-50/70" : undefined}>
                      <LegCells
                        leg={row.call}
                        side="call"
                        label={`${Math.round(row.strike)} CE`}
                        onTrade={(action) => openTrade(row, "call", action)}
                      />
                      <TD className="text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          <span className="font-semibold tabular-nums text-ink-900">{number(row.strike)}</span>
                          {row.is_atm && <Badge tone="blue">ATM</Badge>}
                        </div>
                      </TD>
                      <LegCells
                        leg={row.put}
                        side="put"
                        label={`${Math.round(row.strike)} PE`}
                        onTrade={(action) => openTrade(row, "put", action)}
                      />
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            </div>

            <p className="text-[10px] leading-relaxed text-slate-400">
              {data.notes.data_mode} {data.notes.pricing} {data.notes.metrics} Each lot is{" "}
              {data.lot_size} units; simulated sells do not verify holdings, margin or settlement,
              while live orders are validated by Upstox.
            </p>
          </CardBody>
          <CardFooter>
            <span className="flex items-center gap-1.5">
              <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />
              {data.notes.trading}
            </span>
            <span>{data.notes.advice}</span>
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
