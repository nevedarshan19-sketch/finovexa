import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Banknote,
  Boxes,
  CalendarClock,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Clock3,
  CreditCard,
  HandCoins,
  PackageOpen,
  Plus,
  ReceiptText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
  Wallet,
  Zap,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { post } from "../lib/api";
import type { Analytics, Approval, AuditEvent, Dashboard } from "../lib/types";
import {
  cn,
  formatDate,
  formatDateTime,
  money,
  moneyExact,
  number,
  plainPct,
  pluralize,
  timeAgo,
  titleCase,
} from "../lib/utils";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  AnimatedNumber,
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ErrorState,
  PageSkeleton,
  ProgressBar,
  StatCard,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui";
import { DataModeBadge, StatusBadge } from "../components/DataMode";
import { InsightCard } from "../components/InsightCard";
import {
  AgingBars,
  CashTrendChart,
  DONUT_COLORS,
  ExpenseBreakdownChart,
  RevenueExpenseChart,
} from "../components/Charts";

const RANGE_OPTIONS = [7, 30, 90];

const ALERT_LINK: Record<string, string> = {
  "/money-recovery": "/recovery",
  "/recovery": "/recovery",
  "/cash-flow": "/cash-flow",
  "/analytics": "/analytics",
  "/approvals": "/approvals",
  "/payments": "/payments",
};

const ALERT_STYLES: Record<string, string> = {
  high: "border-rose-200 bg-rose-50/60",
  medium: "border-amber-200 bg-amber-50/50",
  low: "border-brand-200 bg-brand-50/50",
};

const ACTION_ICON: { match: RegExp; icon: typeof ReceiptText; tone: string }[] = [
  { match: /invoice/i, icon: ReceiptText, tone: "bg-brand-500/10 text-brand-600" },
  { match: /paypal|payment|capture|refund/i, icon: Banknote, tone: "bg-emerald-500/10 text-emerald-600" },
  { match: /product|inventory|stock/i, icon: Boxes, tone: "bg-violet-500/10 text-violet-600" },
  { match: /purchase|obligation|expense/i, icon: PackageOpen, tone: "bg-amber-500/10 text-amber-600" },
  { match: /approval|decision/i, icon: ShieldCheck, tone: "bg-cyan-500/10 text-cyan-600" },
  { match: /auth|login|user|team|employee/i, icon: Users, tone: "bg-slate-500/10 text-slate-500" },
];

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function greetingLongDate(): string {
  return new Intl.DateTimeFormat("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date());
}

function riskTone(risk: string): "red" | "amber" | "slate" {
  if (risk === "high") return "red";
  if (risk === "medium") return "amber";
  return "slate";
}

function reconTone(status?: string): "green" | "amber" | "red" | "slate" {
  if (status === "matched") return "green";
  if (status === "unmatched") return "amber";
  if (status === "mismatch") return "red";
  return "slate";
}

function SectionHeading({
  icon: Icon,
  eyebrow,
  title,
  description,
  actions,
}: {
  icon: typeof ReceiptText;
  eyebrow: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-3)]">
          <Icon className="h-3.5 w-3.5 text-brand-500" aria-hidden />
          {eyebrow}
        </p>
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-[var(--text-1)]">{title}</h2>
        {description && <p className="mt-0.5 max-w-2xl text-xs text-[var(--text-3)]">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

function RangeSelector({ days, onChange }: { days: number; onChange: (days: number) => void }) {
  return (
    <div
      role="group"
      aria-label="Reporting range"
      className="inline-flex rounded-lg border border-[color:var(--border)] bg-[var(--surface)] p-0.5"
    >
      {RANGE_OPTIONS.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={days === option}
          className={cn(
            "rounded-md px-2.5 py-1 text-[11px] font-semibold transition",
            days === option
              ? "bg-brand-500 text-white shadow-sm"
              : "text-[var(--text-3)] hover:text-[var(--text-1)]",
          )}
        >
          {option}d
        </button>
      ))}
    </div>
  );
}

function ComparisonRow({
  label,
  current,
  previous,
  currency,
}: {
  label: string;
  current: number;
  previous: number;
  currency: string;
}) {
  const max = Math.max(current, previous, 1);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="font-medium text-[var(--text-2)]">{label}</span>
        <span className="tabular text-[var(--text-3)]">
          <strong className="font-semibold text-[var(--text-1)]">{money(current, currency)}</strong>
          {" vs "}
          {money(previous, currency)}
        </span>
      </div>
      <div className="mt-1 flex gap-1">
        <span
          className="h-1.5 rounded-full bg-brand-500"
          style={{ width: `${Math.max(2, (current / max) * 100)}%` }}
          aria-hidden
        />
        <span
          className="h-1.5 rounded-full bg-[var(--text-3)]/30"
          style={{ width: `${Math.max(2, (previous / max) * 100)}%` }}
          aria-hidden
        />
      </div>
      <p className="mt-1 text-[10px] text-[var(--text-3)]">Current vs prior period</p>
    </div>
  );
}

export function OverviewPage() {
  const { user, profile, demoMode } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [analyzing, setAnalyzing] = useState(false);

  const dashboard = useApi<Dashboard>(`/dashboard?days=${days}`, { pollMs: 15000 });
  const analytics = useApi<Analytics>(`/analytics?days=${days}`);
  const approvals = useApi<{ items: Approval[]; pending_count: number }>(
    "/approvals?status=pending&limit=5",
  );
  const activity = useApi<{ items: AuditEvent[]; count: number }>("/audit-log?limit=8");

  const data = dashboard.data;
  const currency = data?.currency || profile?.currency || "INR";
  const firstName = user?.full_name.split(" ")[0] || "there";

  const inventoryRows = useMemo(() => {
    if (!data) return [];
    const performance = new Map(
      (analytics.data?.products || []).map((item) => [item.product_id, item]),
    );
    return data.inventory
      .map((item) => {
        const stats = performance.get(item.product_id);
        return {
          ...item,
          units_sold: stats?.units_sold ?? 0,
          margin_pct: stats?.margin_pct ?? null,
        };
      })
      .sort((a, b) => {
        const aOut = a.quantity_on_hand <= 0 ? 0 : a.low_stock ? 1 : 2;
        const bOut = b.quantity_on_hand <= 0 ? 0 : b.low_stock ? 1 : 2;
        if (aOut !== bOut) return aOut - bOut;
        return b.units_sold - a.units_sold;
      });
  }, [data, analytics.data]);

  const inventoryStats = useMemo(() => {
    if (!data) {
      return { units: 0, low: 0, out: 0, fast: 0, valuation: 0 };
    }
    return {
      units: data.inventory.reduce((sum, item) => sum + item.quantity_on_hand, 0),
      low: data.inventory.filter((item) => item.low_stock).length,
      out: data.inventory.filter((item) => item.quantity_on_hand <= 0).length,
      fast: inventoryRows.filter((item) => item.units_sold > 0).length,
      valuation: data.inventory_risk.total_inventory_value,
    };
  }, [data, inventoryRows]);

  const pendingApprovals = approvals.data?.items || [];
  const pendingCount = approvals.data?.pending_count ?? 0;
  const lowStock = useMemo(() => data?.inventory.filter((item) => item.low_stock) ?? [], [data]);
  const topInsights = useMemo(() => data?.insights.slice(0, 4) ?? [], [data]);
  const recentActivity = activity.data?.items || [];

  const runAnalysis = async () => {
    setAnalyzing(true);
    try {
      const result = await post<{ insights: unknown[] }>("/agents/business-manager/analyze?days=90");
      toast({
        title: "Analysis complete",
        description: `${result.insights.length} evidence-backed ${pluralize(result.insights.length, "insight")} refreshed.`,
        tone: "success",
      });
      dashboard.reload();
    } catch (err) {
      toast({
        title: "Analysis failed",
        description: err instanceof Error ? err.message : "The analysis engine could not run.",
        tone: "error",
      });
    } finally {
      setAnalyzing(false);
    }
  };

  if (dashboard.loading && !data) return <PageSkeleton cards={4} />;
  if (dashboard.error && !data) return <ErrorState message={dashboard.error} onRetry={dashboard.reload} />;
  if (!data) return null;

  const suggestions = [
    ...data.alerts.slice(0, 2).map((alert) => ({
      key: `alert-${alert.title}`,
      label: alert.title,
      to: ALERT_LINK[alert.link] || "/",
    })),
    pendingCount > 0
      ? {
          key: "approvals",
          label: `Review ${pendingCount} pending ${pluralize(pendingCount, "approval")}`,
          to: "/approvals",
        }
      : null,
    lowStock.length > 0
      ? {
          key: "restock",
          label: `Restock ${lowStock.length} low-stock ${pluralize(lowStock.length, "SKU")}`,
          to: "/billing?tab=catalogue",
        }
      : null,
    topInsights[0]?.recommended_action
      ? {
          key: "insight",
          label: topInsights[0].recommended_action,
          to: "/analytics",
        }
      : null,
  ].filter(Boolean) as { key: string; label: string; to: string }[];

  return (
    <div className="space-y-6">
      {/* A · Welcome ------------------------------------------------------- */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-3)]">
            <span className="h-1 w-6 rounded-full bg-gradient-to-r from-brand-500 to-cyan-400" />
            {greeting()}, {firstName}
          </p>
          <h1 className="mt-1.5 text-[24px] font-semibold tracking-tight text-[var(--text-1)] sm:text-[28px]">
            Business command center
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-[var(--text-3)]">
            <span className="font-medium text-[var(--text-2)]">{profile?.business_name || "Your business"}</span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1">
              <CalendarDays className="h-3.5 w-3.5" aria-hidden />
              {greetingLongDate()}
            </span>
            <span aria-hidden>·</span>
            <span>Records through {formatDate(data.as_of)}</span>
            {demoMode && <DataModeBadge mode="demo" />}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <RangeSelector days={days} onChange={setDays} />
          <Button
            variant="outline"
            size="sm"
            icon={RefreshCw}
            onClick={() => {
              dashboard.reload();
              analytics.reload();
              approvals.reload();
              activity.reload();
            }}
            loading={dashboard.loading}
          >
            Refresh
          </Button>
          <Button
            size="sm"
            icon={Sparkles}
            onClick={() => window.dispatchEvent(new Event("finovexa:open-copilot"))}
          >
            Ask Copilot
          </Button>
          <details className="relative">
            <summary className="inline-flex h-8 cursor-pointer list-none items-center gap-1.5 rounded-lg border border-[color:var(--border-strong)] bg-[var(--surface)] px-2.5 text-xs font-semibold text-[var(--text-2)] transition hover:border-[var(--text-3)] hover:text-[var(--text-1)] [&::-webkit-details-marker]:hidden">
              Quick actions <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </summary>
            <div className="absolute right-0 z-20 mt-2 w-56 overflow-hidden rounded-xl border border-[color:var(--border)] bg-[var(--surface)] p-1.5 shadow-pop">
              {[
                { label: "Create invoice", icon: ReceiptText, to: "/billing?new=1" },
                { label: "Add inventory item", icon: Boxes, to: "/billing?tab=catalogue&newProduct=1" },
                { label: "Open payment center", icon: CreditCard, to: "/payments" },
                { label: "Chase overdue dues", icon: HandCoins, to: "/recovery" },
                { label: "Open analytics", icon: TrendingUp, to: "/analytics" },
              ].map((action) => (
                <button
                  key={action.label}
                  type="button"
                  onClick={() => navigate(action.to)}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-2)] transition hover:bg-[var(--surface-2)] hover:text-[var(--text-1)]"
                >
                  <action.icon className="h-3.5 w-3.5" aria-hidden />
                  {action.label}
                </button>
              ))}
            </div>
          </details>
        </div>
      </div>

      {/* B · AI business briefing ------------------------------------------ */}
      <section
        aria-label="FINOVEXA AI business briefing"
        className="relative overflow-hidden rounded-2xl border border-white/10 bg-[radial-gradient(1200px_420px_at_10%_-20%,rgba(77,148,255,0.32),transparent_60%),radial-gradient(900px_400px_at_100%_0%,rgba(45,212,191,0.18),transparent_55%),linear-gradient(140deg,#060e1b_0%,#0a1930_45%,#0c2240_100%)] p-5 text-white shadow-pop sm:p-6"
      >
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-brand-500/25 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-32 left-1/4 h-64 w-64 rounded-full bg-teal-400/10 blur-3xl" aria-hidden />

        <div className="relative flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/15 bg-white/10 shadow-lg">
              <Sparkles className="h-4 w-4 text-brand-200" aria-hidden />
            </span>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-brand-200">
                FINOVEXA AI · Business briefing
              </p>
              <p className="mt-0.5 text-[10px] text-slate-400">
                {data.ai_summary.generated_by === "deterministic"
                  ? "Rules engine over your ledger · no LLM narrative"
                  : `${titleCase(data.ai_summary.generated_by)} narrative over deterministic figures`}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-emerald-300/25 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">
              {data.ai_summary.generated_by === "deterministic" ? "DETERMINISTIC" : "AI-ASSISTED"}
            </span>
            <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-0.5 text-[10px] font-medium text-slate-300">
              {formatDate(data.period.start)} – {formatDate(data.period.end)}
            </span>
          </div>
        </div>

        <p className="relative mt-4 max-w-4xl text-[14.5px] leading-relaxed text-slate-200">
          {data.ai_summary.text}
        </p>

        <div className="relative mt-4 grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-white/10 bg-white/[0.05] px-3.5 py-2.5">
            <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              <Wallet className="h-3 w-3 text-brand-300" /> Verified cash
            </p>
            <p className="mt-1 text-[15px] font-semibold tabular-nums">{moneyExact(data.cash.recorded_balance, currency)}</p>
            <p className="text-[10px] text-slate-500">
              reserve {money(data.cash.minimum_reserve, currency)}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.05] px-3.5 py-2.5">
            <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              <HandCoins className="h-3 w-3 text-amber-300" /> Overdue dues
            </p>
            <p className="mt-1 text-[15px] font-semibold tabular-nums">{money(data.receivables.overdue_total, currency)}</p>
            <p className="text-[10px] text-slate-500">
              {data.receivables.overdue_count} {pluralize(data.receivables.overdue_count, "invoice")}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.05] px-3.5 py-2.5">
            <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              <ShieldCheck className="h-3 w-3 text-cyan-300" /> Pending approvals
            </p>
            <p className="mt-1 text-[15px] font-semibold tabular-nums">
              {approvals.loading && !approvals.data ? "…" : pendingCount}
            </p>
            <p className="text-[10px] text-slate-500">human decision required</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.05] px-3.5 py-2.5">
            <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              <PackageOpen className="h-3 w-3 text-violet-300" /> Inventory warnings
            </p>
            <p className="mt-1 text-[15px] font-semibold tabular-nums">{inventoryStats.low}</p>
            <p className="text-[10px] text-slate-500">
              {inventoryStats.out} out of stock · {lowStock.length} low
            </p>
          </div>
        </div>

        <div className="relative mt-4 grid gap-3 lg:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3.5">
            <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              <Zap className="h-3 w-3 text-brand-300" /> Key observations
            </p>
            <ul className="mt-2 space-y-1.5 text-[11.5px] leading-relaxed text-slate-300">
              {topInsights.slice(0, 3).map((insight) => (
                <li key={insight.id} className="flex gap-1.5">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-300" aria-hidden />
                  <span className="line-clamp-2">{insight.title}</span>
                </li>
              ))}
              {topInsights.length === 0 && <li className="text-slate-500">No observations yet.</li>}
            </ul>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3.5">
            <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              <PackageOpen className="h-3 w-3 text-violet-300" /> Inventory warnings
            </p>
            <ul className="mt-2 space-y-1.5 text-[11.5px] leading-relaxed text-slate-300">
              {lowStock.slice(0, 3).map((item) => (
                <li key={item.product_id} className="flex items-center justify-between gap-2">
                  <span className="truncate">{item.name}</span>
                  <span className="shrink-0 text-[10px] font-semibold text-amber-300">
                    {number(item.quantity_on_hand)} left
                  </span>
                </li>
              ))}
              {lowStock.length === 0 && (
                <li className="flex items-center gap-1.5 text-slate-500">
                  <CheckCircle2 className="h-3 w-3 text-emerald-400" /> All SKUs above reorder level.
                </li>
              )}
            </ul>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3.5">
            <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              <ShieldCheck className="h-3 w-3 text-cyan-300" /> Pending tasks
            </p>
            <ul className="mt-2 space-y-1.5 text-[11.5px] leading-relaxed text-slate-300">
              {pendingApprovals.slice(0, 3).map((approval) => (
                <li key={approval.id} className="truncate">
                  {approval.title}
                </li>
              ))}
              {pendingApprovals.length === 0 && (
                <li className="flex items-center gap-1.5 text-slate-500">
                  <CheckCircle2 className="h-3 w-3 text-emerald-400" /> Nothing is waiting on you.
                </li>
              )}
            </ul>
          </div>
        </div>

        {suggestions.length > 0 && (
          <div className="relative mt-4 flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Suggested actions
            </span>
            {suggestions.map((item) => (
              <Link
                key={item.key}
                to={item.to}
                className="inline-flex items-center gap-1 rounded-full border border-white/15 bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-slate-200 transition hover:border-white/30 hover:bg-white/10 hover:text-white"
              >
                {item.label}
                <ArrowUpRight className="h-3 w-3" aria-hidden />
              </Link>
            ))}
          </div>
        )}

        <p className="relative mt-4 border-t border-white/[0.08] pt-3 text-[10px] leading-relaxed text-slate-500">
          {data.ai_summary.note} Ledger figures are computed deterministically; the narrative only
          summarises them and never invents a payment, price or order fill.
        </p>
      </section>

      {/* C · KPI cards ---------------------------------------------------- */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label={`Revenue · last ${days} days`}
          value={<AnimatedNumber value={data.metrics.revenue.value} format={(value) => money(value, currency)} />}
          icon={TrendingUp}
          change={data.metrics.revenue.change_pct}
          changeLabel="vs prior period"
          tone="blue"
          to="/analytics"
        />
        <StatCard
          label="Cash received"
          value={<AnimatedNumber value={data.metrics.cash_received.value} format={(value) => money(value, currency)} />}
          icon={Banknote}
          change={data.metrics.cash_received.change_pct}
          changeLabel="confirmed payments only"
          tone="green"
          to="/cash-flow"
        />
        <StatCard
          label="Operating expenses"
          value={<AnimatedNumber value={data.metrics.operating_expenses.value} format={(value) => money(value, currency)} />}
          icon={ReceiptText}
          change={data.metrics.operating_expenses.change_pct}
          changeLabel="vs prior period"
          invert
          tone="amber"
          to="/analytics"
        />
        <StatCard
          label="Net profit"
          value={<AnimatedNumber value={data.metrics.net_profit.value} format={(value) => money(value, currency)} />}
          icon={ShieldCheck}
          change={data.metrics.net_profit.change_pct}
          changeLabel={
            data.metrics.net_margin_pct === null
              ? "no revenue in period"
              : `${plainPct(data.metrics.net_margin_pct)} net margin`
          }
          tone="violet"
          to="/analytics"
        />
      </div>

      {/* D · Business analytics ------------------------------------------- */}
      <section className="space-y-4">
        <SectionHeading
          icon={TrendingUp}
          eyebrow="Business analytics"
          title="Performance over time"
          description="Revenue, cash movement, expense mix and a like-for-like comparison with the prior period."
          actions={
            <div className="flex items-center gap-2">
              <RangeSelector days={days} onChange={setDays} />
              <Link
                to="/analytics"
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700"
              >
                Full analytics <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          }
        />

        <div className="grid gap-4 xl:grid-cols-12">
          <Card className="xl:col-span-7">
            <CardHeader
              title="Revenue vs expenses"
              description={`Daily ledger movements over the last ${days} days.`}
              icon={TrendingUp}
            />
            <CardBody className="pt-3">
              {analytics.loading && !analytics.data ? (
                <div className="h-[270px] animate-pulse rounded-xl bg-[var(--surface-2)]" />
              ) : analytics.error ? (
                <ErrorState message={analytics.error} onRetry={analytics.reload} />
              ) : (
                <RevenueExpenseChart data={analytics.data?.series || data.charts.revenue_expenses} currency={currency} />
              )}
            </CardBody>
          </Card>

          <Card className="xl:col-span-5">
            <CardHeader
              title="Cash position"
              description="Recorded balance with daily inflow and outflow."
              icon={Wallet}
              actions={
                <Link to="/cash-flow" className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700">
                  Forecast <ArrowRight className="h-3 w-3" />
                </Link>
              }
            />
            <CardBody className="pt-3">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-[var(--text-3)]">Recorded cash</p>
                  <p className="text-xl font-semibold tracking-tight text-[var(--text-1)]">
                    {moneyExact(data.cash.recorded_balance, currency)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] uppercase tracking-wide text-[var(--text-3)]">Reserve headroom</p>
                  <p className="text-sm font-semibold text-emerald-600">{money(data.cash.reserve_headroom, currency)}</p>
                </div>
              </div>
              <CashTrendChart data={data.charts.cash_trend} currency={currency} height={228} />
              {data.cash.shortfall_date && (
                <Callout tone="red" title="Reserve breach projected" className="mt-2">
                  Projected cash falls below the minimum reserve on {formatDate(data.cash.shortfall_date)}.
                </Callout>
              )}
            </CardBody>
          </Card>

          <Card className="xl:col-span-4">
            <CardHeader title="Expense breakdown" description="Share of operating spend." icon={CreditCard} />
            <CardBody className="pt-2">
              {(analytics.data?.expense_breakdown.length ?? 0) === 0 ? (
                <p className="py-10 text-center text-xs text-[var(--text-3)]">
                  No expenses recorded in this period.
                </p>
              ) : (
                <>
                  <ExpenseBreakdownChart data={analytics.data?.expense_breakdown || []} currency={currency} height={190} />
                  <div className="mt-2 space-y-1.5">
                    {(analytics.data?.expense_breakdown || []).slice(0, 5).map((item, index) => (
                      <div key={item.category} className="flex items-center justify-between gap-2 text-[11px]">
                        <span className="flex min-w-0 items-center gap-1.5 text-[var(--text-2)]">
                          <span
                            className="h-2 w-2 shrink-0 rounded-sm"
                            style={{ backgroundColor: DONUT_COLORS[index % DONUT_COLORS.length] }}
                            aria-hidden
                          />
                          <span className="truncate">{titleCase(item.category)}</span>
                        </span>
                        <span className="shrink-0 tabular text-[var(--text-3)]">
                          {money(item.amount, currency)} · {item.share_pct.toFixed(0)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </CardBody>
          </Card>

          <Card className="xl:col-span-4">
            <CardHeader
              title="Period comparison"
              description={`Last ${days} days vs the prior ${days} days.`}
              icon={CalendarClock}
            />
            <CardBody className="space-y-3.5 pt-4">
              <ComparisonRow
                label="Revenue"
                current={analytics.data?.metrics.revenue.value ?? data.metrics.revenue.value}
                previous={analytics.data?.metrics.revenue.previous ?? data.metrics.revenue.previous}
                currency={currency}
              />
              <ComparisonRow
                label="Operating expenses"
                current={analytics.data?.metrics.operating_expenses.value ?? data.metrics.operating_expenses.value}
                previous={analytics.data?.metrics.operating_expenses.previous ?? data.metrics.operating_expenses.previous}
                currency={currency}
              />
              <ComparisonRow
                label="Net profit"
                current={analytics.data?.metrics.net_profit.value ?? data.metrics.net_profit.value}
                previous={analytics.data?.metrics.net_profit.previous ?? data.metrics.net_profit.previous}
                currency={currency}
              />
              <div className="flex items-center justify-between rounded-lg bg-[var(--surface-2)] px-3 py-2 text-[11px]">
                <span className="text-[var(--text-3)]">Invoices issued</span>
                <span className="font-semibold text-[var(--text-1)]">
                  {number(analytics.data?.metrics.invoice_count ?? 0)}
                </span>
              </div>
            </CardBody>
          </Card>

          <Card className="xl:col-span-4">
            <CardHeader
              title="Receivables aging"
              description={`${money(data.receivables.total_outstanding, currency)} outstanding.`}
              icon={HandCoins}
              actions={
                <Link to="/recovery" className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700">
                  Recovery <ArrowRight className="h-3 w-3" />
                </Link>
              }
            />
            <CardBody className="space-y-3 pt-4">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-rose-200/70 bg-rose-50/60 p-2.5">
                  <p className="text-[10px] font-medium uppercase tracking-wide text-rose-500">Overdue</p>
                  <p className="mt-0.5 text-base font-semibold tracking-tight text-rose-700">
                    {money(data.receivables.overdue_total, currency)}
                  </p>
                  <p className="text-[10px] text-rose-500">
                    {data.receivables.overdue_count} {pluralize(data.receivables.overdue_count, "invoice")}
                  </p>
                </div>
                <div className="rounded-xl border border-[color:var(--border)] bg-[var(--surface-2)] p-2.5">
                  <p className="text-[10px] font-medium uppercase tracking-wide text-[var(--text-3)]">Not yet due</p>
                  <p className="mt-0.5 text-base font-semibold tracking-tight text-[var(--text-1)]">
                    {money(data.receivables.current_total, currency)}
                  </p>
                  <p className="text-[10px] text-[var(--text-3)]">current bucket</p>
                </div>
              </div>
              <AgingBars data={data.receivables.buckets} currency={currency} compact />
            </CardBody>
          </Card>
        </div>
      </section>

      {/* E · Inventory intelligence --------------------------------------- */}
      <section className="space-y-4">
        <SectionHeading
          icon={Boxes}
          eyebrow="Inventory intelligence"
          title="Stock health and sell-through"
          description="Live quantities from your product catalogue, paired with units sold in the selected period."
          actions={
            <Link
              to="/billing?tab=catalogue"
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700"
            >
              Open catalogue <ArrowRight className="h-3 w-3" />
            </Link>
          }
        />

        <Card>
          <CardBody className="pt-5">
            <div className="grid gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
              {[
                { label: "Products", value: number(data.inventory.length), tone: "text-[var(--text-1)]" },
                { label: "Units on hand", value: number(inventoryStats.units), tone: "text-[var(--text-1)]" },
                { label: "Low stock", value: number(inventoryStats.low), tone: "text-amber-600" },
                { label: "Out of stock", value: number(inventoryStats.out), tone: "text-rose-600" },
                { label: "Fast-moving", value: number(inventoryStats.fast), tone: "text-emerald-600" },
                {
                  label: "Stock value",
                  value: money(inventoryStats.valuation, currency),
                  tone: "text-[var(--text-1)]",
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className="rounded-xl border border-[color:var(--border)] bg-[var(--surface-2)]/70 px-3 py-2.5"
                >
                  <p className="text-[10px] font-medium uppercase tracking-wide text-[var(--text-3)]">
                    {item.label}
                  </p>
                  <p className={cn("mt-1 text-[15px] font-semibold tabular-nums", item.tone)}>{item.value}</p>
                </div>
              ))}
            </div>

            <div className="mt-4 space-y-1.5">
              {inventoryRows.slice(0, 6).map((item) => {
                const ratio = item.reorder_level > 0 ? item.quantity_on_hand / item.reorder_level : 1;
                const tone = item.quantity_on_hand <= 0 ? "red" : item.low_stock ? "amber" : "blue";
                return (
                  <div
                    key={item.product_id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-[color:var(--border)] px-3 py-2.5 transition hover:border-[var(--border-strong)]"
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2.5">
                      <span
                        className={cn(
                          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                          item.quantity_on_hand <= 0
                            ? "bg-rose-500/10 text-rose-500"
                            : item.low_stock
                              ? "bg-amber-500/10 text-amber-500"
                              : "bg-brand-500/10 text-brand-600",
                        )}
                      >
                        <Boxes className="h-4 w-4" aria-hidden />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-[var(--text-1)]">{item.name}</p>
                        <p className="text-[10px] text-[var(--text-3)]">
                          {item.sku}
                          {item.units_sold > 0 ? ` · ${number(item.units_sold)} sold` : " · no sales this period"}
                          {item.margin_pct !== null ? ` · ${item.margin_pct.toFixed(0)}% margin` : ""}
                        </p>
                      </div>
                    </div>
                    <div className="w-full max-w-[200px]">
                      <div className="flex items-baseline justify-between gap-2 text-[10px]">
                        <span className={cn("font-semibold", item.low_stock ? "text-amber-600" : "text-[var(--text-2)]")}>
                          {number(item.quantity_on_hand)} on hand
                        </span>
                        <span className="text-[var(--text-3)]">reorder {number(item.reorder_level)}</span>
                      </div>
                      <ProgressBar
                        value={Math.min(100, ratio * 100)}
                        tone={item.quantity_on_hand <= 0 ? "red" : item.low_stock ? "amber" : "blue"}
                        className="mt-1"
                        label={`${item.name} stock level`}
                      />
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-semibold tabular-nums text-[var(--text-1)]">
                        {money(item.inventory_value, currency)}
                      </p>
                      <p className="text-[10px] text-[var(--text-3)]">at cost</p>
                    </div>
                    <Link
                      to={`/billing?tab=catalogue&product=${item.product_id}`}
                      className="inline-flex items-center gap-1 rounded-lg border border-[color:var(--border-strong)] px-2 py-1 text-[10px] font-semibold text-[var(--text-2)] transition hover:border-brand-300 hover:text-brand-600"
                    >
                      Restock <ArrowUpRight className="h-3 w-3" />
                    </Link>
                  </div>
                );
              })}
              {inventoryRows.length === 0 && (
                <div className="rounded-xl border border-dashed border-[color:var(--border-strong)] px-4 py-8 text-center">
                  <p className="text-xs font-medium text-[var(--text-2)]">The catalogue is empty.</p>
                  <p className="mt-1 text-[11px] text-[var(--text-3)]">
                    Add products to track stock, low-stock warnings and valuation.
                  </p>
                  <Link
                    to="/billing?tab=catalogue&newProduct=1"
                    className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600"
                  >
                    <Plus className="h-3 w-3" /> Add your first item
                  </Link>
                </div>
              )}
            </div>
            <p className="mt-3 text-[10px] text-[var(--text-3)]">
              “Restock” opens the catalogue editor for that item. FINOVEXA never places a live purchase
              order on its own; stock changes are recorded by you.
            </p>
          </CardBody>
        </Card>
      </section>

      {/* F · PayPal payment center ---------------------------------------- */}
      <section className="space-y-4">
        <SectionHeading
          icon={CreditCard}
          eyebrow="Payments"
          title="PayPal payment center"
          description="Only verified captures count as received cash. Pending, failed and refunded amounts stay separate."
          actions={
            <Link
              to="/payments"
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700"
            >
              Open payment center <ArrowRight className="h-3 w-3" />
            </Link>
          }
        />

        <div className="grid gap-4 xl:grid-cols-12">
          <Card className="xl:col-span-7">
            <CardHeader
              title="Reconciliation snapshot"
              description={`${data.paypal.transaction_count} transactions · ${data.paypal.mode === "live" ? "live PayPal" : "simulated sandbox"}`}
              icon={Wallet}
              actions={
                <Badge tone={data.paypal.environment === "live" ? "green" : "amber"}>
                  {data.paypal.environment?.toUpperCase() || "SANDBOX"}
                </Badge>
              }
            />
            <CardBody className="pt-3">
              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                {[
                  {
                    label: "Verified received",
                    value: moneyExact(data.paypal.net_received, currency),
                    hint: `${data.paypal.successful_count} confirmed ${pluralize(data.paypal.successful_count, "capture")}`,
                    tone: "text-emerald-600",
                  },
                  {
                    label: "Pending captures",
                    value: moneyExact(data.paypal.pending_total, currency),
                    hint: `${data.paypal.pending_count} awaiting · never counted as cash`,
                    tone: "text-amber-600",
                  },
                  {
                    label: "Failed",
                    value: moneyExact(data.paypal.failed_total, currency),
                    hint: `${data.paypal.failed_count} failed attempts`,
                    tone: "text-rose-600",
                  },
                  {
                    label: "Refunded",
                    value: moneyExact(data.paypal.refunded_total, currency),
                    hint: `${data.paypal.refund_count} ${pluralize(data.paypal.refund_count, "refund")}`,
                    tone: "text-[var(--text-1)]",
                  },
                  {
                    label: "Needs reconciliation",
                    value: moneyExact(data.paypal.unmatched_confirmed + data.paypal.mismatch_total, currency),
                    hint: "unmatched or amount mismatch",
                    tone: "text-amber-600",
                  },
                  {
                    label: "Reconciliation",
                    value:
                      data.paypal.unmatched_confirmed + data.paypal.mismatch_total > 0
                        ? "Action needed"
                        : "Up to date",
                    hint: "confirm matches in the payment center",
                    tone:
                      data.paypal.unmatched_confirmed + data.paypal.mismatch_total > 0
                        ? "text-amber-600"
                        : "text-emerald-600",
                  },
                ].map((tile) => (
                  <div
                    key={tile.label}
                    className="rounded-xl border border-[color:var(--border)] bg-[var(--surface-2)]/60 px-3 py-2.5"
                  >
                    <p className="text-[10px] font-medium uppercase tracking-wide text-[var(--text-3)]">
                      {tile.label}
                    </p>
                    <p className={cn("mt-1 text-[15px] font-semibold tabular-nums", tile.tone)}>{tile.value}</p>
                    <p className="text-[10px] text-[var(--text-3)]">{tile.hint}</p>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[10px] leading-relaxed text-[var(--text-3)]">{data.paypal.note}</p>
            </CardBody>
          </Card>

          <Card className="xl:col-span-5">
            <CardHeader title="Recent transactions" description="Webhook-verified provider events and recorded payments." icon={Banknote} />
            <CardBody className="pt-3">
              <div className="space-y-1">
                {data.paypal.recent.slice(0, 6).map((payment) => (
                  <div
                    key={payment.id}
                    className="flex items-center justify-between gap-3 rounded-lg px-2 py-2 transition hover:bg-[var(--surface-2)]"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-xs font-semibold text-[var(--text-1)]">
                        {payment.invoice_number ? `${payment.invoice_number} · ` : ""}
                        {payment.customer_name || payment.sender_name || titleCase(payment.method)}
                      </p>
                      <p className="flex flex-wrap items-center gap-1.5 text-[10px] text-[var(--text-3)]">
                        <span>{formatDateTime(payment.received_at || payment.created_at)}</span>
                        {payment.reconciliation_status && payment.reconciliation_status !== "not_applicable" && (
                          <Badge tone={reconTone(payment.reconciliation_status)}>
                            {titleCase(payment.reconciliation_status)}
                          </Badge>
                        )}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-xs font-semibold tabular-nums text-[var(--text-1)]">
                        {money(payment.amount, payment.currency || currency)}
                      </p>
                      <StatusBadge status={payment.status} />
                    </div>
                  </div>
                ))}
                {data.paypal.recent.length === 0 && (
                  <p className="py-8 text-center text-xs text-[var(--text-3)]">
                    No PayPal activity yet. Create a payment request from an invoice in the payment center.
                  </p>
                )}
              </div>
            </CardBody>
            <CardFooter>
              <span>{money(data.recovery.awaiting_reconciliation, currency)} awaiting reconciliation</span>
              <Link to="/payments" className="font-semibold text-brand-600 hover:text-brand-700">
                Reconcile
              </Link>
            </CardFooter>
          </Card>
        </div>
      </section>

      {/* G · AI action center --------------------------------------------- */}
      <section className="space-y-4">
        <SectionHeading
          icon={ShieldCheck}
          eyebrow="AI action center"
          title="Decisions, alerts and recommendations"
          description="Nothing consequential executes without an owner decision. AI can recommend; only you can approve."
          actions={
            <Link
              to="/approvals"
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700"
            >
              Approval center <ArrowRight className="h-3 w-3" />
            </Link>
          }
        />

        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <CardHeader
              title="Pending approvals"
              description={pendingCount ? `${pendingCount} awaiting your decision.` : "Everything is reviewed."}
              icon={ShieldCheck}
              actions={<Badge tone={pendingCount ? "amber" : "green"}>{pendingCount}</Badge>}
            />
            <CardBody className="space-y-2 pt-3">
              {pendingApprovals.length === 0 ? (
                <p className="flex items-center gap-2 rounded-lg bg-emerald-500/5 px-3 py-4 text-[11px] text-emerald-700">
                  <CheckCircle2 className="h-3.5 w-3.5" /> No actions are waiting for approval.
                </p>
              ) : (
                pendingApprovals.map((approval) => (
                  <Link
                    key={approval.id}
                    to="/approvals"
                    className="block rounded-xl border border-[color:var(--border)] px-3 py-2.5 transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-2)]"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--text-1)]">
                        {approval.title}
                      </p>
                      <Badge tone={riskTone(approval.risk_level)}>{approval.risk_level}</Badge>
                    </div>
                    <p className="mt-0.5 text-[10px] text-[var(--text-3)]">
                      {titleCase(approval.action_type)}
                      {approval.financial_impact
                        ? ` · ${money(approval.financial_impact, currency)}`
                        : ""} · {timeAgo(approval.created_at)}
                    </p>
                  </Link>
                ))
              )}
            </CardBody>
            <CardFooter>
              <span>Approvals are hash-bound and expire.</span>
              <Link to="/approvals" className="font-semibold text-brand-600 hover:text-brand-700">
                Review
              </Link>
            </CardFooter>
          </Card>

          <Card>
            <CardHeader
              title="Operational alerts"
              description="Computed from ledger thresholds."
              icon={AlertTriangle}
              actions={<Badge tone={data.alerts.length ? "amber" : "slate"}>{data.alerts.length}</Badge>}
            />
            <CardBody className="space-y-2 pt-3">
              {data.alerts.length === 0 ? (
                <p className="flex items-center gap-2 rounded-lg bg-emerald-500/5 px-3 py-4 text-[11px] text-emerald-700">
                  <CheckCircle2 className="h-3.5 w-3.5" /> No threshold alerts in this period.
                </p>
              ) : (
                data.alerts.slice(0, 3).map((alert) => (
                  <Link
                    key={alert.title}
                    to={ALERT_LINK[alert.link] || "/"}
                    className={cn(
                      "block rounded-xl border px-3 py-2.5 transition hover:shadow-card",
                      ALERT_STYLES[alert.severity] || ALERT_STYLES.low,
                    )}
                  >
                    <p className="text-xs font-semibold text-[var(--text-1)]">{alert.title}</p>
                    <p className="mt-0.5 line-clamp-2 text-[10.5px] leading-relaxed text-[var(--text-2)]">
                      {alert.detail}
                    </p>
                    <span className="mt-1 inline-flex items-center gap-1 text-[10px] font-semibold text-[var(--text-2)]">
                      Review <ArrowUpRight className="h-3 w-3" />
                    </span>
                  </Link>
                ))
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Recommended actions"
              description="Suggestions from deterministic insights."
              icon={Sparkles}
              actions={
                <Button variant="ghost" size="sm" icon={RefreshCw} loading={analyzing} onClick={runAnalysis}>
                  Run
                </Button>
              }
            />
            <CardBody className="space-y-2 pt-3">
              {topInsights.filter((insight) => insight.recommended_action).length === 0 ? (
                <p className="rounded-lg bg-[var(--surface-2)] px-3 py-4 text-[11px] text-[var(--text-3)]">
                  Run the analysis engine to generate recommendations with evidence and limitations.
                </p>
              ) : (
                topInsights
                  .filter((insight) => insight.recommended_action)
                  .slice(0, 3)
                  .map((insight) => (
                    <div key={insight.id} className="rounded-xl border border-[color:var(--border)] px-3 py-2.5">
                      <p className="text-xs font-semibold text-[var(--text-1)]">{insight.title}</p>
                      <p className="mt-0.5 line-clamp-3 text-[10.5px] leading-relaxed text-[var(--text-2)]">
                        {insight.recommended_action}
                      </p>
                      <p className="mt-1 text-[10px] text-[var(--text-3)]">
                        Confidence {insight.confidence} · {titleCase(insight.mode)}
                      </p>
                    </div>
                  ))
              )}
            </CardBody>
            <CardFooter>
              <span>Actions always need owner approval.</span>
              <Link to="/ask" className="font-semibold text-brand-600 hover:text-brand-700">
                Ask why
              </Link>
            </CardFooter>
          </Card>
        </div>
      </section>

      {/* H · Recent activity ---------------------------------------------- */}
      <section className="space-y-4">
        <SectionHeading
          icon={Clock3}
          eyebrow="Recent activity"
          title="What changed in your ledger"
          description="Invoices, payments, stock updates, purchases and account events from the audit trail."
          actions={
            <Link
              to="/audit"
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700"
            >
              View full log <ArrowRight className="h-3 w-3" />
            </Link>
          }
        />

        <div className="grid gap-4 xl:grid-cols-12">
          <Card className="xl:col-span-7">
            <CardBody className="pt-4">
              {activity.loading && !activity.data ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <div key={index} className="h-12 animate-pulse rounded-lg bg-[var(--surface-2)]" />
                  ))}
                </div>
              ) : recentActivity.length === 0 ? (
                <p className="py-10 text-center text-xs text-[var(--text-3)]">
                  No activity recorded yet. Actions you take will appear here with a timestamp.
                </p>
              ) : (
                <ol className="relative space-y-1">
                  {recentActivity.map((event, index) => {
                    const style =
                      ACTION_ICON.find((entry) => entry.match.test(event.action)) || ACTION_ICON[ACTION_ICON.length - 1];
                    const Icon = style.icon;
                    return (
                      <li key={event.id} className="flex gap-3 rounded-lg px-1 py-2 transition hover:bg-[var(--surface-2)]">
                        <div className="relative flex flex-col items-center">
                          <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", style.tone)}>
                            <Icon className="h-3.5 w-3.5" aria-hidden />
                          </span>
                          {index < recentActivity.length - 1 && (
                            <span className="mt-1 w-px flex-1 bg-[var(--border)]" aria-hidden />
                          )}
                        </div>
                        <div className="min-w-0 flex-1 pb-1">
                          <p className="truncate text-xs font-semibold text-[var(--text-1)]">
                            {titleCase(event.action.replace(/\./g, " "))}
                          </p>
                          <p className="truncate text-[10.5px] text-[var(--text-3)]">
                            {event.actor}
                            {event.entity_type ? ` · ${titleCase(event.entity_type)}` : ""}
                            {event.entity_id ? ` #${event.entity_id}` : ""}
                          </p>
                        </div>
                        <span className="shrink-0 text-[10px] text-[var(--text-3)]" title={formatDateTime(event.created_at)}>
                          {timeAgo(event.created_at)}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              )}
            </CardBody>
          </Card>

          <Card className="xl:col-span-5">
            <CardHeader title="Data quality" description="What is verified, simulated or awaiting validation." icon={ShieldCheck} />
            <CardBody className="space-y-3 pt-3">
              <div className="flex items-start justify-between gap-3 rounded-lg border border-[color:var(--border)] bg-[var(--surface-2)]/70 p-3">
                <div>
                  <p className="text-xs font-semibold text-[var(--text-1)]">PayPal</p>
                  <p className="mt-0.5 text-[11px] text-[var(--text-2)]">{data.data_quality.note}</p>
                </div>
                <StatusBadge
                  status={data.data_quality.has_paypal_live ? "configured" : "simulated"}
                  label={data.data_quality.has_paypal_live ? "LIVE KEYS" : "SIMULATED"}
                />
              </div>
              <div className="flex items-start justify-between gap-3 rounded-lg border border-[color:var(--border)] bg-[var(--surface-2)]/70 p-3">
                <div>
                  <p className="text-xs font-semibold text-[var(--text-1)]">Business records</p>
                  <p className="mt-0.5 text-[11px] text-[var(--text-2)]">
                    Revenue and receivables are computed from invoices; cash only moves on confirmed payments.
                  </p>
                </div>
                <DataModeBadge mode={data.data_mode} />
              </div>
              <div className="flex items-start justify-between gap-3 rounded-lg border border-[color:var(--border)] bg-[var(--surface-2)]/70 p-3">
                <div>
                  <p className="text-xs font-semibold text-[var(--text-1)]">AI analysis</p>
                  <p className="mt-0.5 text-[11px] text-[var(--text-2)]">{data.ai_summary.note}</p>
                </div>
                <StatusBadge status="active" label="RULE-BASED" />
              </div>
            </CardBody>
          </Card>
        </div>
      </section>

      {/* Team activity ----------------------------------------------------- */}
      <Card>
        <CardHeader
          title="Employee activity"
          description="Invoices, paid sales and purchases submitted from the employee portal. Refreshes every 15 seconds."
          icon={Users}
          actions={
            <Link to="/team" className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700">
              Open team <ArrowRight className="h-3 w-3" />
            </Link>
          }
        />
        <CardBody className="pt-3">
          <div className="grid gap-4 lg:grid-cols-[230px_minmax(0,1fr)]">
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-1">
              {[
                { label: "Active employees", value: String(data.employee_activity.active_employees) },
                { label: "Entries submitted", value: String(data.employee_activity.submitted) },
                {
                  label: "Employee sales + invoices",
                  value: money(data.employee_activity.sales_total, currency),
                },
                { label: "Employee purchases", value: money(data.employee_activity.purchases_total, currency) },
              ].map((item) => (
                <div
                  key={item.label}
                  className="rounded-lg border border-[color:var(--border)] bg-[var(--surface-2)]/70 px-3 py-2"
                >
                  <p className="text-[10px] uppercase tracking-wide text-[var(--text-3)]">{item.label}</p>
                  <p className="mt-0.5 text-[13px] font-semibold tabular-nums text-[var(--text-1)]">{item.value}</p>
                </div>
              ))}
            </div>
            <div className="space-y-1.5">
              {data.employee_entries.slice(0, 4).map((entry) => {
                const tone =
                  entry.entry_type === "sale" ? "green" : entry.entry_type === "purchase" ? "amber" : "blue";
                const label =
                  entry.entry_type === "sale" ? "Sale" : entry.entry_type === "purchase" ? "Purchase" : "Invoice";
                return (
                  <div
                    key={entry.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-[color:var(--border)] px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge tone={tone}>{label}</Badge>
                        <span className="font-mono text-[10px] text-[var(--text-3)]">{entry.reference}</span>
                        {entry.status === "void" && <Badge tone="red">VOID</Badge>}
                      </div>
                      <p className="mt-0.5 truncate text-[11px] font-medium text-[var(--text-2)]">
                        {entry.counterparty} · {entry.description}
                      </p>
                      <p className="text-[10px] text-[var(--text-3)]">
                        {entry.employee.name} · {formatDateTime(entry.created_at)}
                      </p>
                    </div>
                    <span className="shrink-0 text-xs font-semibold tabular-nums text-[var(--text-1)]">
                      {money(entry.amount, entry.currency || currency)}
                    </span>
                  </div>
                );
              })}
              {data.employee_entries.length === 0 && (
                <p className="flex h-full min-h-[120px] items-center justify-center rounded-lg border border-dashed border-[color:var(--border-strong)] px-4 text-center text-xs text-[var(--text-3)]">
                  No employee entries yet. Add a team member and share the employee portal link.
                </p>
              )}
            </div>
          </div>
        </CardBody>
        <CardFooter>
          <span>Employee-recorded cash and PayPal receipts are unverified until reconciled.</span>
          <Link to="/payments" className="font-semibold text-brand-600 hover:text-brand-700">
            Payment Center
          </Link>
        </CardFooter>
      </Card>

      {/* Insights ---------------------------------------------------------- */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-[var(--text-1)]">Business Manager insights</h2>
          <p className="mt-0.5 text-xs text-[var(--text-3)]">
            Deterministic findings with evidence, estimated impact, confidence and limitations.
          </p>
        </div>
        <Button variant="outline" size="sm" icon={RefreshCw} loading={analyzing} onClick={runAnalysis}>
          Run analysis
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {topInsights.map((insight) => (
          <InsightCard key={insight.id} insight={insight} currency={currency} />
        ))}
        {topInsights.length === 0 && (
          <Card className="md:col-span-2">
            <CardBody>
              <p className="text-center text-xs text-[var(--text-3)]">
                No insights yet. Run the analysis engine to review the business.
              </p>
            </CardBody>
          </Card>
        )}
      </div>

      {/* Obligations ------------------------------------------------------- */}
      <Card>
        <CardHeader
          title="Upcoming obligations"
          description="Scheduled outflows inside the forecast window."
          icon={CalendarClock}
        />
        <div className="mt-3">
          <TableWrap>
            <THead>
              <TR>
                <TH>Obligation</TH>
                <TH>Due</TH>
                <TH className="text-right">Amount</TH>
                <TH>Status</TH>
              </TR>
            </THead>
            <TBody>
              {data.upcoming_obligations.map((obligation) => (
                <TR key={obligation.id}>
                  <TD>
                    <p className="font-medium text-ink-900">{obligation.name}</p>
                    <p className="text-[10px] capitalize text-slate-400">{obligation.category}</p>
                  </TD>
                  <TD>
                    <p>{formatDate(obligation.due_date)}</p>
                    <p className="text-[10px] text-slate-400">
                      {obligation.days_until !== undefined ? `in ${obligation.days_until} days` : ""}
                    </p>
                  </TD>
                  <TD className="text-right font-semibold tabular-nums">
                    {money(obligation.amount, currency)}
                  </TD>
                  <TD>
                    <StatusBadge status={obligation.status} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </TableWrap>
        </div>
        <CardFooter>
          <span>Scheduled obligations are owner-maintained and are not paid automatically.</span>
          <Link to="/cash-flow" className="font-semibold text-brand-600 hover:text-brand-700">
            Open forecast
          </Link>
        </CardFooter>
      </Card>
    </div>
  );
}
