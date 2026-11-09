import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  BarChart3,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  Link2,
  Package,
  RefreshCw,
  Search,
  Wallet,
} from "lucide-react";
import { get, getErrorMessage, post } from "../../lib/api";
import type {
  BusinessInboxStatus,
  BusinessSummary,
  BusinessTransaction,
  BusinessTransactionList,
  BusinessTransactionType,
} from "../../lib/accountingTypes";
import { formatDate, formatDateTime, money } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Select,
  StatCard,
} from "../ui";

const PAGE_SIZE = 20;

const TYPE_TONES: Record<BusinessTransactionType, "blue" | "green" | "amber" | "red" | "slate" | "violet"> = {
  sale: "blue",
  receipt: "green",
  refund: "red",
  expense: "amber",
};

const TYPE_LABELS: Record<BusinessTransactionType, string> = {
  sale: "Sale",
  receipt: "Receipt",
  refund: "Refund",
  expense: "Expense",
};

const INBOX_LABELS: Record<BusinessInboxStatus, string> = {
  not_synced: "Not synced",
  pending: "In review inbox",
  drafted: "Draft created",
  needs_attention: "Needs attention",
  ignored: "Ignored",
  posted: "Posted to books",
};

function sourceTone(status: string): "green" | "amber" | "red" | "slate" {
  if (["confirmed", "paid", "issued"].includes(status)) return "green";
  if (["pending", "partial", "overdue"].includes(status)) return "amber";
  if (["void", "failed", "cancelled"].includes(status)) return "red";
  return "slate";
}

function AccountingState({ item }: { item: BusinessTransaction }) {
  const { accounting } = item;
  if (accounting.voucher_number) {
    return (
      <Badge tone="green" dot title="Included in Tally exports">
        Posted · {accounting.voucher_number}
      </Badge>
    );
  }
  if (accounting.draft_status) {
    return (
      <Badge tone="violet" dot>
        {accounting.draft_status.replace("_", " ")} · {accounting.draft_number}
      </Badge>
    );
  }
  const tone =
    accounting.inbox_status === "needs_attention"
      ? "red"
      : accounting.inbox_status === "not_synced" || accounting.inbox_status === "ignored"
        ? "slate"
        : "amber";
  return <Badge tone={tone}>{INBOX_LABELS[accounting.inbox_status]}</Badge>;
}

interface Filters {
  type: "" | BusinessTransactionType;
  search: string;
  from: string;
  to: string;
}

const EMPTY_FILTERS: Filters = { type: "", search: "", from: "", to: "" };

export function ClientBusinessPanel({
  clientId,
  isSeniorAccountant,
}: {
  clientId: number;
  isSeniorAccountant: boolean;
}) {
  const base = isSeniorAccountant ? "senior" : "junior";
  const [summary, setSummary] = useState<BusinessSummary | null>(null);
  const [history, setHistory] = useState<BusinessTransactionList | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);

  const loadSummary = useCallback(async () => {
    setError(null);
    try {
      setSummary(await get<BusinessSummary>(`/accounting/${base}/clients/${clientId}/business/summary`));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [base, clientId]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (applied.type) params.set("transaction_type", applied.type);
      if (applied.search.trim()) params.set("search", applied.search.trim());
      if (applied.from) params.set("date_from", applied.from);
      if (applied.to) params.set("date_to", applied.to);
      setHistory(
        await get<BusinessTransactionList>(
          `/accounting/${base}/clients/${clientId}/business/transactions?${params.toString()}`,
        ),
      );
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setHistoryLoading(false);
    }
  }, [applied, base, clientId, offset]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const applyFilters = () => {
    setOffset(0);
    setApplied(filters);
  };

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setOffset(0);
  };

  const syncNow = async () => {
    if (!isSeniorAccountant) return;
    setSyncing(true);
    setActionError(null);
    try {
      await post(`/accounting/senior/clients/${clientId}/integration/sync`);
      await Promise.all([loadSummary(), loadHistory()]);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardBody>
          <p className="text-[12px] text-slate-500">Loading the linked business records…</p>
        </CardBody>
      </Card>
    );
  }

  if (error || !summary) {
    return <ErrorState message={error ?? "The business records could not be loaded."} onRetry={loadSummary} />;
  }

  if (!summary.linked || !summary.business) {
    return (
      <Card>
        <CardBody>
          <EmptyState
            title="No Business Manager business linked"
            description={summary.note}
            icon={Link2}
          />
        </CardBody>
      </Card>
    );
  }

  const metrics = summary.metrics;
  const receivables = summary.receivables;
  const cash = summary.cash;
  const inventory = summary.inventory;
  const integration = summary.integration;
  const tally = summary.tally;
  const start = history && history.total > 0 ? history.offset + 1 : 0;
  const end = history ? Math.min(history.offset + history.items.length, history.total) : 0;
  const unavailable = "—";

  return (
    <div className="space-y-4">
      {actionError && (
        <Callout tone="red" title="The business records action did not complete">
          {actionError}
        </Callout>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard
          label={`Revenue · last ${summary.period?.days ?? 30} days`}
          value={metrics ? money(metrics.revenue) : unavailable}
          icon={BarChart3}
          tone="blue"
          sub={`${metrics?.invoice_count ?? 0} invoices`}
        />
        <StatCard
          label="Operating expenses"
          value={metrics ? money(metrics.expenses) : unavailable}
          icon={Wallet}
          tone="amber"
          sub={`Cash received ${metrics ? money(metrics.cash_received) : unavailable}`}
        />
        <StatCard
          label="Net profit"
          value={metrics ? money(metrics.net_profit) : unavailable}
          icon={BookOpen}
          tone={metrics && Number(metrics.net_profit) < 0 ? "red" : "green"}
          sub={metrics?.net_margin_pct != null ? `${metrics.net_margin_pct}% net margin` : "Margin unavailable"}
        />
        <StatCard
          label="Receivables outstanding"
          value={receivables ? money(receivables.total_outstanding) : unavailable}
          tone="violet"
          sub={
            receivables
              ? `${money(receivables.overdue_total)} overdue across ${receivables.overdue_count} invoices`
              : unavailable
          }
        />
        <StatCard
          label="Recorded cash"
          value={cash ? money(cash.recorded_balance) : unavailable}
          tone="green"
          sub={cash ? `Reserve ${money(cash.minimum_reserve)}` : unavailable}
        />
        <StatCard
          label="Inventory value"
          value={inventory ? money(inventory.total_value) : unavailable}
          icon={Package}
          tone="slate"
          sub={inventory ? `${inventory.low_stock_count} low-stock items` : unavailable}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title={summary.business.business_name}
            description="Owner dashboard figures are read-only here. Only approved entries become accounting vouchers."
            icon={Link2}
            actions={
              <Link
                to={`/accountant/tally?clientId=${clientId}`}
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600"
              >
                Tally exports <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            }
          />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Business GSTIN</p>
              <p className="font-mono text-[12px] text-slate-700">{summary.business.gstin || "Not recorded"}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Location</p>
              <p className="text-[12px] text-slate-700">
                {[summary.business.city, summary.business.state].filter(Boolean).join(", ") || "Not recorded"}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Integration status</p>
              <p className="text-[12px] text-slate-700">
                {integration?.status === "linked" ? "Linked" : integration?.status ?? "Not linked"}
                {integration?.last_synced_at ? ` · synced ${formatDateTime(integration.last_synced_at)}` : " · never synced"}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Source records</p>
              <p className="text-[12px] text-slate-700">
                {summary.counts
                  ? `${summary.counts.invoices} invoices · ${summary.counts.payments} payments · ${summary.counts.expenses} expenses`
                  : unavailable}
              </p>
            </div>
            <div className="sm:col-span-2 flex flex-wrap gap-1.5">
              <Badge tone="amber">{integration?.inbox.pending ?? 0} awaiting review</Badge>
              <Badge tone="violet">{integration?.drafts.draft ?? 0} drafts</Badge>
              <Badge tone="blue">{integration?.drafts.pending_review ?? 0} awaiting approval</Badge>
              <Badge tone="green">{integration?.inbox.posted ?? 0} posted</Badge>
              {(integration?.inbox.needs_attention ?? 0) > 0 && (
                <Badge tone="red">{integration?.inbox.needs_attention} need attention</Badge>
              )}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Tally reporting" icon={FileSpreadsheet} />
          <CardBody className="space-y-2 text-[12px]">
            <div className="flex justify-between">
              <span className="text-slate-500">Accounting vouchers</span>
              <span className="font-semibold tabular text-ink-900">{tally?.voucher_count ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">From business records</span>
              <span className="font-semibold tabular text-ink-900">{tally?.integration_vouchers ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Tally export batches</span>
              <span className="font-semibold tabular text-ink-900">{tally?.export_count ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Last export</span>
              <span className="text-slate-700">
                {tally?.last_export_at ? formatDateTime(tally.last_export_at) : "Never"}
              </span>
            </div>
            <p className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] leading-relaxed text-slate-500">
              {tally?.note}
            </p>
            <Link
              to={`/accountant/tally?clientId=${clientId}`}
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600"
            >
              Prepare a Tally export <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Transaction history"
          description="Every invoice, receipt, refund and expense recorded in the owner's Business Manager."
          icon={BookOpen}
          actions={
            isSeniorAccountant ? (
              <Button size="sm" variant="outline" icon={RefreshCw} loading={syncing} onClick={syncNow}>
                Sync business records
              </Button>
            ) : undefined
          }
        />
        <CardBody className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
            <Field label="Type" htmlFor="business_filter_type">
              <Select
                id="business_filter_type"
                value={filters.type}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    type: event.target.value as Filters["type"],
                  }))
                }
              >
                <option value="">All types</option>
                {(Object.keys(TYPE_LABELS) as BusinessTransactionType[]).map((key) => (
                  <option key={key} value={key}>
                    {TYPE_LABELS[key]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Search" htmlFor="business_filter_search">
              <Input
                id="business_filter_search"
                value={filters.search}
                onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
                placeholder="Party, reference or category"
              />
            </Field>
            <Field label="From" htmlFor="business_filter_from">
              <Input
                id="business_filter_from"
                type="date"
                value={filters.from}
                onChange={(event) => setFilters((current) => ({ ...current, from: event.target.value }))}
              />
            </Field>
            <Field label="To" htmlFor="business_filter_to">
              <Input
                id="business_filter_to"
                type="date"
                value={filters.to}
                onChange={(event) => setFilters((current) => ({ ...current, to: event.target.value }))}
              />
            </Field>
            <div className="flex items-end gap-2 lg:col-span-2">
              <Button icon={Search} onClick={applyFilters} className="flex-1">
                Apply
              </Button>
              <Button variant="outline" onClick={clearFilters} className="flex-1">
                Clear
              </Button>
            </div>
          </div>

          {history && (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {(Object.keys(TYPE_LABELS) as BusinessTransactionType[]).map((key) => (
                <div key={key} className="rounded-lg border border-slate-200 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">{TYPE_LABELS[key]}</p>
                  <p className="mt-0.5 text-[13px] font-semibold tabular text-ink-900">
                    {money(history.summary[key].total)}
                  </p>
                  <p className="text-[10px] text-slate-500">{history.summary[key].count} records</p>
                </div>
              ))}
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Net of receipts and refunds</p>
                <p className="mt-0.5 text-[13px] font-semibold tabular text-ink-900">{money(history.summary.net_total)}</p>
                <p className="text-[10px] text-slate-500">{history.total} matching records</p>
              </div>
            </div>
          )}

          {historyLoading && !history ? (
            <p className="text-[12px] text-slate-500">Loading transaction history…</p>
          ) : !history || history.items.length === 0 ? (
            <EmptyState
              title="No matching transactions"
              description="Adjust the filters, or sync the business records if the owner has entered new data."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head">Date</th>
                    <th className="table-head">Type</th>
                    <th className="table-head">Reference</th>
                    <th className="table-head">Party</th>
                    <th className="table-head">Taxable</th>
                    <th className="table-head">GST</th>
                    <th className="table-head">Total</th>
                    <th className="table-head">Source</th>
                    <th className="table-head">Accounting</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {history.items.map((item) => (
                    <tr key={`${item.source_type}-${item.source_id}`} className="row-hover">
                      <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                        {formatDate(item.date)}
                      </td>
                      <td className="table-cell">
                        <Badge tone={TYPE_TONES[item.transaction_type]}>{TYPE_LABELS[item.transaction_type]}</Badge>
                      </td>
                      <td className="table-cell">
                        <p className="text-[12px] font-semibold text-ink-900">{item.reference}</p>
                        <p className="text-[10px] text-slate-500">{item.category || "Uncategorised"}</p>
                      </td>
                      <td className="table-cell">
                        <p className="text-[12px] text-slate-700">{item.party_name}</p>
                        {item.party_gstin && (
                          <p className="font-mono text-[10px] text-slate-400">{item.party_gstin}</p>
                        )}
                      </td>
                      <td className="table-cell tabular text-[12px]">{money(item.taxable_value)}</td>
                      <td className="table-cell tabular text-[12px]">{money(item.tax_amount)}</td>
                      <td className="table-cell tabular text-[12px] font-semibold">{money(item.total_amount)}</td>
                      <td className="table-cell">
                        <Badge tone={sourceTone(item.source_status)}>{item.source_status}</Badge>
                      </td>
                      <td className="table-cell">
                        <AccountingState item={item} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {history && history.total > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <p className="text-[11px] text-slate-500">
                Showing {start}–{end} of {history.total} transactions
              </p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  icon={ChevronLeft}
                  disabled={history.offset === 0 || historyLoading}
                  onClick={() => setOffset((current) => Math.max(current - PAGE_SIZE, 0))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  iconRight={ChevronRight}
                  disabled={end >= history.total || historyLoading}
                  onClick={() => setOffset((current) => current + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}

          <p className="text-[11px] leading-relaxed text-slate-400">{history?.note}</p>
        </CardBody>
      </Card>
    </div>
  );
}
