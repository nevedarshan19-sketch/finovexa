import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  CalendarClock,
  ClipboardList,
  Landmark,
  LockKeyhole,
  Save,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  Waves,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, post } from "../lib/api";
import type { CashflowOverview, Forecast, SavedForecast } from "../lib/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
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
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  StatCard,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Tabs,
  Textarea,
} from "../components/ui";
import { DataModeBadge, StatusBadge } from "../components/DataMode";
import { ForecastChart, ReceivableForecast } from "../components/Charts";
import { formatDate, formatDateTime, money, moneyExact, plainPct } from "../lib/utils";

type Horizon = "7" | "30" | "90";
type ScenarioKey = "conservative" | "base" | "optimistic";

function DecisionModal({
  open,
  onClose,
  currency,
  gap,
  horizon,
}: {
  open: boolean;
  onClose: () => void;
  currency: string;
  gap: number;
  horizon: string;
}) {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [title, setTitle] = useState("Mitigation plan for projected cash shortfall");
  const [recommendation, setRecommendation] = useState(
    `Review collections and defer discretionary spend to protect the ${currency} reserve floor over the next ${horizon} days.`,
  );
  const [impact, setImpact] = useState(String(gap || 0));
  const [acknowledged, setAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await post("/approvals/cashflow", {
        title,
        recommendation,
        financial_impact: Number(impact) || 0,
      });
      window.dispatchEvent(new CustomEvent("finovexa:approvals-changed"));
      toast({
        title: "Mitigation decision recorded",
        description: "The advisory is waiting in the Approval Center. No money moved.",
        tone: "success",
      });
      onClose();
      navigate("/approvals");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Record a mitigation decision"
      description="Creates an advisory approval. It has no external effect and moves no money."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button icon={ShieldCheck} onClick={submit} loading={submitting} disabled={!acknowledged || !title || recommendation.length < 10}>
            Create advisory
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && <Callout tone="red" title="Could not create advisory">{error}</Callout>}
        <Field label="Decision title" htmlFor="decision-title" required>
          <Input id="decision-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} />
        </Field>
        <Field label="Recommendation" htmlFor="decision-body" required hint="Describe the cash action and its rationale.">
          <Textarea id="decision-body" value={recommendation} onChange={(event) => setRecommendation(event.target.value)} maxLength={2000} className="min-h-[120px]" />
        </Field>
        <Field label={`Expected financial impact (${currency})`} htmlFor="decision-impact" hint="Illustrative impact used for prioritization only.">
          <Input id="decision-impact" type="number" value={impact} onChange={(event) => setImpact(event.target.value)} />
        </Field>
        <Callout tone="blue" title="Human approval still applies">
          This creates a pending advisory request. Nothing leaves FINOVEXA, and no payment, reminder or order is
          triggered by approving it.
        </Callout>
        <Checkbox checked={acknowledged} onChange={setAcknowledged} label="I understand this is an advisory record, not a cash transfer." />
      </div>
    </Modal>
  );
}

export function CashflowPage() {
  const { profile } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [horizon, setHorizon] = useState<Horizon>("30");
  const [scenario, setScenario] = useState<ScenarioKey>("base");
  const [saving, setSaving] = useState(false);
  const [decisionOpen, setDecisionOpen] = useState(false);

  const overview = useApi<CashflowOverview>(`/cashflow/overview?horizon=${horizon}`);
  const selectedForecast = useApi<Forecast>(`/cashflow/forecast?horizon=${horizon}&scenario=${scenario}`);
  const saved = useApi<{ items: SavedForecast[] }>("/cashflow/forecasts?limit=6");
  const currency = profile?.currency || "INR";

  const refresh = () => {
    overview.reload();
    selectedForecast.reload();
    saved.reload();
  };

  const saveSnapshot = async () => {
    setSaving(true);
    try {
      await post(`/cashflow/forecasts?horizon=${horizon}&scenario=${scenario}`);
      toast({
        title: "Forecast snapshot saved",
        description: "The projection is stored for later comparison. It is not an actual bank balance.",
        tone: "success",
      });
      saved.reload();
    } catch (err) {
      toast({ title: "Could not save snapshot", description: getErrorMessage(err), tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  if (overview.loading && !overview.data) return <PageSkeleton cards={4} />;
  if (overview.error && !overview.data) return <ErrorState message={overview.error} onRetry={refresh} />;
  if (!overview.data) return null;

  const data = overview.data;
  const forecast = selectedForecast.data ?? data.forecast;
  const gap = Math.max(0, forecast.minimum_reserve - forecast.minimum_balance);
  const reserveCover = forecast.minimum_reserve > 0 ? (forecast.minimum_balance / forecast.minimum_reserve) * 100 : 100;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Cash flow intelligence"
        title="See the cash before it moves"
        description="Probability-weighted receivables, scheduled obligations and average operating spend. Projections are estimates, not guarantees."
        actions={
          <>
            <Tabs
              items={[
                { key: "7", label: "7 days" },
                { key: "30", label: "30 days" },
                { key: "90", label: "90 days" },
              ]}
              value={horizon}
              onChange={setHorizon}
            />
            <Button variant="outline" size="md" icon={Save} onClick={saveSnapshot} loading={saving}>
              Save snapshot
            </Button>
            <Button size="md" icon={Sparkles} onClick={() => navigate("/ask")}>
              Ask about cash
            </Button>
          </>
        }
      />

      {forecast.shortfall_date && (
        <Callout tone="red" title={`Reserve breach projected on ${formatDate(forecast.shortfall_date)}`} icon={AlertTriangle}>
          The {forecast.scenario_label.toLowerCase()} scenario reaches {money(forecast.minimum_balance, currency)} against
          a {money(forecast.minimum_reserve, currency)} floor — a gap of {money(gap, currency)}. Treat this as an early
          warning, not a certainty.
        </Callout>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Opening recorded cash"
          value={moneyExact(forecast.opening_balance, currency)}
          icon={Landmark}
          sub="owner-recorded + confirmed receipts"
          tone="blue"
        />
        <StatCard
          label={`Expected inflows · ${forecast.horizon_days}d`}
          value={money(forecast.total_expected_inflow, currency)}
          icon={ArrowDownToLine}
          sub="probability-weighted collections"
          tone="green"
        />
        <StatCard
          label={`Expected outflows · ${forecast.horizon_days}d`}
          value={money(forecast.total_expected_outflow, currency)}
          icon={ArrowUpFromLine}
          sub="obligations + average operating spend"
          tone="amber"
        />
        <StatCard
          label="Lowest projected balance"
          value={money(forecast.minimum_balance, currency)}
          icon={forecast.shortfall_date ? TrendingDown : ShieldCheck}
          sub={`on ${formatDate(forecast.minimum_balance_date)}`}
          tone={forecast.shortfall_date ? "red" : "violet"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-8">
          <CardHeader
            title={`${forecast.scenario_label} · ${forecast.horizon_days}-day projection`}
            description={forecast.scenario_description}
            icon={Waves}
            actions={
              <div className="flex items-center gap-2">
                <DataModeBadge mode="deterministic" showDot={false} />
                {selectedForecast.loading && <span className="text-[10px] text-slate-400">Updating…</span>}
              </div>
            }
          />
          <CardBody className="pt-3">
            {selectedForecast.error && (
              <Callout tone="amber" title="Scenario refresh failed" className="mb-3">
                {selectedForecast.error} Showing the last loaded projection.
              </Callout>
            )}
            <ForecastChart data={forecast.series} currency={currency} reserve={forecast.minimum_reserve} height={320} />
            <div className="mt-3 grid gap-3 rounded-xl border border-slate-100 bg-slate-50/70 p-3 sm:grid-cols-4">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Projected close</p>
                <p className="mt-0.5 text-sm font-semibold text-ink-900">{money(forecast.closing_balance, currency)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Reserve floor</p>
                <p className="mt-0.5 text-sm font-semibold text-ink-900">{money(forecast.minimum_reserve, currency)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Illustrative headroom</p>
                <p className="mt-0.5 text-sm font-semibold text-ink-900">{money(forecast.investable_surplus, currency)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Headroom vs reserve</p>
                <p className={`mt-0.5 text-sm font-semibold ${gap > 0 ? "text-rose-600" : "text-emerald-700"}`}>
                  {gap > 0 ? `-${money(gap, currency)}` : money(forecast.minimum_balance - forecast.minimum_reserve, currency)}
                </p>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-4 text-[10px] text-slate-400">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-brand-500" /> Projected balance</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-emerald-500" /> Expected inflow</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-rose-500" /> Expected outflow</span>
              <span className="ml-auto">Reserve coverage at low point: {plainPct(reserveCover)}</span>
            </div>
          </CardBody>
        </Card>

        <Card className="lg:col-span-4">
          <CardHeader title="Scenario comparison" description="Switch scenarios to inspect resilience." icon={ClipboardList} />
          <CardBody className="space-y-2 pt-3">
            {data.scenarios.map((row) => {
              const active = row.key === scenario;
              return (
                <button
                  key={row.key}
                  type="button"
                  onClick={() => setScenario(row.key as ScenarioKey)}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    active ? "border-brand-300 bg-brand-50/60 ring-1 ring-brand-200" : "border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50"
                  }`}
                  aria-pressed={active}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-ink-900">{row.label}</p>
                    {active ? <Badge tone="blue">Viewing</Badge> : <span className="text-[10px] text-slate-400">Select</span>}
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[10px] leading-relaxed text-slate-400">{row.description}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2 border-t border-slate-100 pt-2 text-[10px]">
                    <div>
                      <p className="text-slate-400">Lowest balance</p>
                      <p className={`font-semibold tabular-nums ${row.shortfall_date ? "text-rose-600" : "text-ink-900"}`}>
                        {money(row.minimum_balance, currency)}
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-400">Projected close</p>
                      <p className="font-semibold tabular-nums text-ink-900">{money(row.closing_balance, currency)}</p>
                    </div>
                  </div>
                  <div className="mt-1.5 flex items-center justify-between text-[9px]">
                    <span className="text-slate-400">{row.shortfall_date ? `Breach ${formatDate(row.shortfall_date)}` : "Reserve maintained"}</span>
                    <span className={row.shortfall_date ? "text-rose-500" : "text-emerald-600"}>
                      {row.shortfall_date ? `Gap ${money(Math.max(0, forecast.minimum_reserve - row.minimum_balance), currency)}` : "No breach"}
                    </span>
                  </div>
                </button>
              );
            })}
          </CardBody>
          <CardFooter>
            <span>Scenarios change collection probabilities and spend, never ledger records.</span>
          </CardFooter>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-7">
          <CardHeader
            title="Expected collections"
            description={`${forecast.receivables.length} receivables inside the ${forecast.horizon_days}-day horizon, weighted by aging-based probability.`}
            icon={ArrowDownToLine}
          />
          <CardBody className="pt-3">
            <ReceivableForecast items={forecast.receivables} currency={currency} />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2 text-[10px] text-amber-800">
              <span>At-risk receivables: {money(forecast.at_risk_receivables, currency)}</span>
              <span>Beyond horizon: {money(forecast.receivables_beyond_horizon, currency)}</span>
            </div>
          </CardBody>
          <CardFooter>
            <span>Receivables are not guaranteed cash. Overdue invoices are delayed, never accelerated.</span>
          </CardFooter>
        </Card>

        <Card className="lg:col-span-5">
          <CardHeader
            title="Scheduled outflows"
            description="Scheduled obligations inside the horizon plus average operating spend."
            icon={ArrowUpFromLine}
          />
          <CardBody className="pt-3">
            <div className="max-h-[330px] space-y-2 overflow-y-auto pr-1">
              {forecast.outflows.map((outflow, index) => (
                <div key={`${outflow.source}-${outflow.id}-${index}`} className="flex items-start justify-between gap-3 rounded-lg border border-slate-100 px-3 py-2">
                  <div className="flex min-w-0 items-start gap-2.5">
                    <span
                      className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                        outflow.source === "obligation" ? "bg-amber-400" : "bg-slate-300"
                      }`}
                    />
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-ink-900">{outflow.label}</p>
                      <p className="text-[10px] capitalize text-slate-400">
                        {outflow.source.replace("_", " ")} · {formatDate(outflow.date)}
                      </p>
                    </div>
                  </div>
                  <span className="shrink-0 text-xs font-semibold tabular-nums text-slate-700">
                    {money(outflow.amount, currency)}
                  </span>
                </div>
              ))}
              {forecast.outflows.length === 0 && (
                <EmptyState title="No scheduled outflows" description="No obligations or expense basis fall inside this horizon." />
              )}
            </div>
          </CardBody>
          <CardFooter>
            <span>Average daily expense basis: {money(forecast.assumptions.daily_expense_basis, currency)}</span>
            <span>{money(forecast.total_expected_outflow, currency)} total</span>
          </CardFooter>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-5">
          <CardHeader title="Sensitivity analysis" description="What changes when collections or spend move." icon={Waves} />
          <div className="mt-3">
            <TableWrap>
              <THead>
                <TR>
                  <TH>Stress</TH>
                  <TH className="text-right">Lowest</TH>
                  <TH className="text-right">Headroom</TH>
                  <TH>Reserve</TH>
                </TR>
              </THead>
              <TBody>
                {data.sensitivity.map((row) => (
                  <TR key={row.key}>
                    <TD>
                      <p className="text-xs font-medium text-ink-900">{row.label}</p>
                      {row.shortfall_date && <p className="text-[10px] text-rose-500">Breach {formatDate(row.shortfall_date)}</p>}
                    </TD>
                    <TD className="text-right font-medium tabular-nums">{money(row.minimum_balance, currency)}</TD>
                    <TD className="text-right tabular-nums">{money(row.investable_surplus, currency)}</TD>
                    <TD>
                      <StatusBadge status={row.shortfall_date ? "shortfall" : "active"} label={row.shortfall_date ? "At risk" : "OK"} />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          </div>
          <CardFooter>
            <span>Sensitivity is deterministic; it does not forecast market shocks.</span>
          </CardFooter>
        </Card>

        <Card className="lg:col-span-7">
          <CardHeader
            title="Model assumptions"
            description="Every projection discloses its method and caveats."
            icon={LockKeyhole}
            actions={<DataModeBadge mode="deterministic" showDot={false} />}
          />
          <CardBody className="space-y-3 pt-3">
            <p className="rounded-lg border border-slate-100 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-600">
              {forecast.assumptions.method}
            </p>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Collection probabilities</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {Object.entries(forecast.assumptions.collection_probabilities).map(([bucket, probability]) => (
                  <Badge key={bucket} tone="slate">
                    {bucket} · {plainPct(Number(probability) * 100, 0)}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {[
                ["Overdue delay adjustment", `${forecast.assumptions.overdue_delay_days_adjustment} days`],
                ["Expense basis", `${money(forecast.assumptions.daily_expense_basis, currency)} / day`],
                ["Expense history", `${forecast.assumptions.expense_history_days} days`],
                ["Minimum reserve", money(forecast.assumptions.minimum_reserve, currency)],
                ["Data quality", data.data_quality],
                ["Receivables guaranteed", forecast.assumptions.receivables_not_guaranteed ? "No" : "Check policy"],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-2.5 py-2 text-[10px]">
                  <span className="text-slate-400">{label}</span>
                  <span className="font-medium capitalize text-slate-700">{value}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] leading-relaxed text-slate-400">{forecast.assumptions.note}</p>
            <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
              <Button variant="outline" size="sm" icon={ClipboardList} onClick={() => setDecisionOpen(true)}>
                Record mitigation decision
              </Button>
              <span className="self-center text-[10px] text-slate-400">Advisory only · requires approval</span>
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Saved forecast snapshots"
          description="Point-in-time projections saved by the owner for later comparison."
          icon={CalendarClock}
          actions={
            <Button variant="outline" size="sm" icon={Save} onClick={saveSnapshot} loading={saving}>
              Save current
            </Button>
          }
        />
        <CardBody className="pt-3">
          {saved.loading && !saved.data ? (
            <p className="py-6 text-center text-xs text-slate-400">Loading snapshots…</p>
          ) : (saved.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="No snapshots yet"
              description="Save the current forecast to compare against future conditions."
              icon={CalendarClock}
            />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {saved.data?.items.map((snapshot) => (
                <div key={snapshot.id} className="rounded-xl border border-slate-100 bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Badge tone="violet">{snapshot.scenario}</Badge>
                    <span className="text-[10px] text-slate-400">{formatDateTime(snapshot.created_at)}</span>
                  </div>
                  <p className="mt-2 text-sm font-semibold text-ink-900">{money(snapshot.closing_balance, currency)}</p>
                  <p className="text-[10px] text-slate-400">
                    closes after {snapshot.horizon_days} days · reserve {money(snapshot.minimum_reserve, currency)}
                  </p>
                  {snapshot.shortfall_date ? (
                    <p className="mt-1 text-[10px] font-medium text-rose-500">Projected breach {formatDate(snapshot.shortfall_date)}</p>
                  ) : (
                    <p className="mt-1 text-[10px] text-emerald-600">No reserve breach projected</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardBody>
        <CardFooter>
          <span>Snapshots are projections, not actual balances. Saved {saved.data?.items.length ?? 0} records.</span>
        </CardFooter>
      </Card>

      <DecisionModal
        open={decisionOpen}
        onClose={() => setDecisionOpen(false)}
        currency={currency}
        gap={gap}
        horizon={horizon}
      />
    </div>
  );
}
