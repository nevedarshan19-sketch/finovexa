import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Boxes,
  CircleDollarSign,
  HandCoins,
  PackageOpen,
  RefreshCw,
  Search,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { post } from "../lib/api";
import type { Analytics } from "../lib/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  PageSkeleton,
  ProgressBar,
  Select,
  StatCard,
  TableWrap,
  Tabs,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui";
import { StatusBadge, ConfidenceBadge } from "../components/DataMode";
import { DONUT_COLORS, ExpenseBreakdownChart, RevenueExpenseChart } from "../components/Charts";
import { InsightCard } from "../components/InsightCard";
import { formatDate, money, number, plainPct, pluralize, titleCase } from "../lib/utils";

type Period = "30" | "60" | "90";

function marginTone(margin: number): "green" | "amber" | "red" {
  if (margin >= 35) return "green";
  if (margin >= 20) return "amber";
  return "red";
}

export function AnalyticsPage() {
  const { profile } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [period, setPeriod] = useState<Period>("90");
  const { data, loading, error, reload } = useApi<Analytics>(`/analytics?days=${period}`);
  const [running, setRunning] = useState(false);
  const [invoiceQuery, setInvoiceQuery] = useState("");
  const [invoiceStatus, setInvoiceStatus] = useState("all");

  const currency = profile?.currency || "INR";
  const filteredInvoices = useMemo(() => {
    if (!data) return [];
    const needle = invoiceQuery.trim().toLowerCase();
    return data.invoices.filter((invoice) => {
      const matchesQuery =
        !needle ||
        invoice.number.toLowerCase().includes(needle) ||
        invoice.customer.name.toLowerCase().includes(needle) ||
        (invoice.customer.company || "").toLowerCase().includes(needle);
      const matchesStatus = invoiceStatus === "all" || invoice.status === invoiceStatus;
      return matchesQuery && matchesStatus;
    });
  }, [data, invoiceQuery, invoiceStatus]);

  const runAnalysis = async () => {
    setRunning(true);
    try {
      const result = await post<{ insights: unknown[] }>(`/agents/business-manager/analyze?days=${period}`);
      toast({
        title: "Insights refreshed",
        description: `${result.insights.length} deterministic findings generated from the ledger.`,
        tone: "success",
      });
      reload();
    } catch (err) {
      toast({
        title: "Analysis failed",
        description: err instanceof Error ? err.message : "The analysis engine could not run.",
        tone: "error",
      });
    } finally {
      setRunning(false);
    }
  };

  if (loading && !data) return <PageSkeleton cards={4} />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const totalExpenses = data.expense_breakdown.reduce((sum, item) => sum + item.amount, 0);
  const lowStockCount = data.products.filter((product) => product.low_stock).length;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Business analytics"
        title="Revenue, margin and operating efficiency"
        description={`Accrual-based performance for ${formatDate(data.period.start)} – ${formatDate(data.period.end)}. Revenue is invoiced value; cash is tracked separately.`}
        actions={
          <>
            <Tabs
              items={[
                { key: "30", label: "30D" },
                { key: "60", label: "60D" },
                { key: "90", label: "90D" },
              ]}
              value={period}
              onChange={setPeriod}
            />
            <Button variant="outline" size="md" icon={RefreshCw} onClick={reload} loading={loading}>
              Refresh
            </Button>
            <Button size="md" icon={Sparkles} loading={running} onClick={runAnalysis}>
              Re-run insights
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label={`Revenue · ${data.period.days} days`}
          value={money(data.metrics.revenue.value, currency)}
          icon={TrendingUp}
          change={data.metrics.revenue.change_pct}
          changeLabel="vs previous period"
          tone="blue"
        />
        <StatCard
          label="Gross profit"
          value={money(data.metrics.gross_profit.value, currency)}
          icon={CircleDollarSign}
          change={data.metrics.gross_profit.change_pct}
          changeLabel={
            data.metrics.gross_margin_pct === null
              ? "no revenue in period"
              : `${plainPct(data.metrics.gross_margin_pct)} gross margin`
          }
          tone="green"
        />
        <StatCard
          label="Operating expenses"
          value={money(data.metrics.operating_expenses.value, currency)}
          icon={Wallet}
          change={data.metrics.operating_expenses.change_pct}
          changeLabel="positive change is higher spend"
          invert
          tone="amber"
        />
        <StatCard
          label="Net profit"
          value={money(data.metrics.net_profit.value, currency)}
          icon={BarChart3}
          change={data.metrics.net_profit.change_pct}
          changeLabel={
            data.metrics.net_margin_pct === null
              ? "no revenue in period"
              : `${plainPct(data.metrics.net_margin_pct)} net margin`
          }
          tone="violet"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-8">
          <CardHeader
            title="Revenue vs expenses"
            description={`${data.metrics.invoice_count} invoices issued in the period. Expenses are recorded by incurred date.`}
            icon={BarChart3}
          />
          <CardBody className="pt-3">
            <RevenueExpenseChart data={data.series} currency={currency} height={300} />
            <div className="mt-2 flex flex-wrap items-center gap-4 text-[10px] text-slate-400">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-brand-500" /> Invoiced revenue
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-rose-300" /> Operating expenses
              </span>
              <span className="ml-auto">Both series are accrual records, not bank movements.</span>
            </div>
          </CardBody>
        </Card>

        <Card className="lg:col-span-4">
          <CardHeader
            title="Expense mix"
            description={`${data.expense_breakdown.length} categories totaling ${money(totalExpenses, currency)}.`}
            icon={Wallet}
          />
          <CardBody className="pt-2">
            <div className="relative">
              <ExpenseBreakdownChart data={data.expense_breakdown} currency={currency} />
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <p className="text-[9px] uppercase tracking-wide text-slate-400">Total</p>
                <p className="text-base font-semibold tracking-tight text-ink-900">{money(totalExpenses, currency)}</p>
              </div>
            </div>
            <div className="mt-2 space-y-1.5">
              {data.expense_breakdown.slice(0, 6).map((item, index) => (
                <div key={item.category} className="flex items-center gap-2 text-[11px]">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: DONUT_COLORS[index % DONUT_COLORS.length] }}
                  />
                  <span className="capitalize text-slate-500">{item.category}</span>
                  <span className="ml-auto font-medium text-slate-700">{money(item.amount, currency)}</span>
                  <span className="w-10 text-right text-slate-400">{plainPct(item.share_pct, 0)}</span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>

      {data.insights.length > 0 && (
        <div>
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-base font-semibold tracking-tight text-ink-900">Findings from the analysis engine</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Each finding links to ledger evidence and states its own limitations.
              </p>
            </div>
            <Badge tone="slate">{data.insights.length} active</Badge>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {data.insights.map((insight) => (
              <InsightCard key={insight.id} insight={insight} currency={currency} />
            ))}
          </div>
        </div>
      )}

      <Card>
        <CardHeader
          title="Product performance"
          description={`Revenue, cost of goods and margin by SKU. ${lowStockCount} of ${data.products.length} products need replenishment.`}
          icon={Boxes}
          actions={
            <Badge tone={lowStockCount > 0 ? "amber" : "green"} dot>
              {lowStockCount > 0 ? `${lowStockCount} low stock` : "Stock healthy"}
            </Badge>
          }
        />
        <div className="mt-3">
          <TableWrap>
            <THead>
              <TR>
                <TH>Product</TH>
                <TH className="text-right">Units sold</TH>
                <TH className="text-right">Revenue</TH>
                <TH className="text-right">Gross profit</TH>
                <TH>Margin</TH>
                <TH className="text-right">On hand</TH>
              </TR>
            </THead>
            <TBody>
              {data.products.map((product) => (
                <TR key={product.product_id}>
                  <TD>
                    <p className="font-medium text-ink-900">{product.name}</p>
                    <p className="text-[10px] text-slate-400">{product.sku}</p>
                  </TD>
                  <TD className="text-right tabular-nums">{number(product.units_sold)}</TD>
                  <TD className="text-right tabular-nums">{money(product.revenue, currency)}</TD>
                  <TD className="text-right font-medium tabular-nums">{money(product.gross_profit, currency)}</TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <ProgressBar
                        value={product.margin_pct}
                        tone={marginTone(product.margin_pct)}
                        className="w-16"
                        label={`${product.name} margin`}
                      />
                      <span className="text-[11px] font-semibold tabular-nums text-slate-600">
                        {plainPct(product.margin_pct)}
                      </span>
                    </div>
                  </TD>
                  <TD className="text-right">
                    <span className="tabular-nums">{number(product.inventory_qty)}</span>
                    {product.low_stock && (
                      <Badge tone="amber" className="ml-2">
                        Reorder
                      </Badge>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </TableWrap>
        </div>
        <CardFooter>
          <span>Unit costs come from your product catalog, not live supplier quotes.</span>
          <span className="flex items-center gap-1">
            <PackageOpen className="h-3 w-3" /> {data.products.filter((p) => p.low_stock).length} replenishment flags
          </span>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader
          title="Invoice register"
          description="Every invoice contributing to revenue and receivables in this workspace."
          icon={CircleDollarSign}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" aria-hidden />
                <Input
                  value={invoiceQuery}
                  onChange={(event) => setInvoiceQuery(event.target.value)}
                  placeholder="Search invoice or customer"
                  className="h-8 w-52 pl-8 text-xs"
                  aria-label="Search invoices"
                />
              </div>
              <Select
                value={invoiceStatus}
                onChange={(event) => setInvoiceStatus(event.target.value)}
                className="h-8 w-36 py-1 text-xs"
                aria-label="Filter invoice status"
              >
                <option value="all">All statuses</option>
                <option value="overdue">Overdue</option>
                <option value="partially_paid">Partially paid</option>
                <option value="issued">Issued</option>
                <option value="paid">Paid</option>
              </Select>
            </div>
          }
        />
        <div className="mt-3">
          {filteredInvoices.length === 0 ? (
            <EmptyState
              title="No invoices match"
              description="Adjust the search text or status filter to see invoices."
              icon={Search}
            />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Invoice</TH>
                  <TH>Customer</TH>
                  <TH>Due</TH>
                  <TH className="text-right">Total</TH>
                  <TH className="text-right">Outstanding</TH>
                  <TH>Status</TH>
                  <TH>Aging</TH>
                </TR>
              </THead>
              <TBody>
                {filteredInvoices.map((invoice) => (
                  <TR key={invoice.id}>
                    <TD>
                      <Link to="/recovery" className="font-semibold text-ink-900 hover:text-brand-600">
                        {invoice.number}
                      </Link>
                      <p className="text-[10px] text-slate-400">{formatDate(invoice.issue_date)}</p>
                    </TD>
                    <TD>
                      <p className="font-medium text-ink-900">{invoice.customer.name}</p>
                      <p className="text-[10px] text-slate-400">{invoice.customer.company || invoice.customer.email}</p>
                    </TD>
                    <TD>{formatDate(invoice.due_date)}</TD>
                    <TD className="text-right tabular-nums">{money(invoice.total, currency)}</TD>
                    <TD className="text-right font-medium tabular-nums">{money(invoice.outstanding, currency)}</TD>
                    <TD>
                      <StatusBadge status={invoice.status} />
                    </TD>
                    <TD>
                      <span className={invoice.aging_days > 0 ? "text-rose-600" : "text-slate-500"}>
                        {invoice.aging_days > 0 ? `${invoice.aging_days}d overdue` : "Current"}
                      </span>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </div>
        <CardFooter>
          <span>{filteredInvoices.length} of {data.invoices.length} invoices shown</span>
          <button
            type="button"
            onClick={() => navigate("/recovery")}
            className="flex items-center gap-1 font-semibold text-brand-600 hover:text-brand-700"
          >
            <HandCoins /> Recovery workspace
          </button>
        </CardFooter>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Metric definitions" description="How FINOVEXA computes the numbers on this page." icon={BarChart3} />
          <CardBody className="grid gap-3 pt-3 sm:grid-cols-2">
            {Object.entries(data.definitions).map(([key, definition]) => (
              <div key={key} className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
                <p className="text-[11px] font-semibold text-ink-900">{titleCase(key)}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{definition}</p>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Confidence notes" icon={Sparkles} />
          <CardBody className="space-y-2.5 pt-3 text-[11px] leading-relaxed text-slate-500">
            <p>
              Revenue is recognised from invoice issue dates. Cash received is tracked separately from confirmed
              payments and may lag revenue significantly.
            </p>
            <p>
              Gross profit uses product cost at time of sale. Overhead allocation and taxes are excluded from gross
              margin.
            </p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <ConfidenceBadge confidence="high" />
              <Badge tone="slate">{pluralize(data.products.length, "SKU")} analyzed</Badge>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
