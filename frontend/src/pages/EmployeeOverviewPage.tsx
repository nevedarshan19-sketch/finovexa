import { Link } from "react-router-dom";
import {
  ArrowRight,
  FilePlus2,
  ReceiptText,
  ShoppingBag,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import type { EmployeeOverview } from "../lib/types";
import { formatDate, formatDateTime, money } from "../lib/utils";
import { useAuth } from "../context/AuthContext";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorState,
  PageHeader,
  PageSkeleton,
  StatCard,
} from "../components/ui";
import { StatusBadge } from "../components/DataMode";

const TYPE_META = {
  invoice: { label: "Invoice", tone: "blue" as const, icon: ReceiptText },
  sale: { label: "Sale", tone: "green" as const, icon: TrendingUp },
  purchase: { label: "Purchase", tone: "amber" as const, icon: ShoppingBag },
};

export function EmployeeOverviewPage() {
  const { user, business } = useAuth();
  const { data, loading, error, reload } = useApi<EmployeeOverview>("/employee/overview");
  const currency = data?.business.currency || business?.currency || "INR";
  const firstName = user?.full_name.split(" ")[0] || "there";

  if (loading && !data) return <PageSkeleton cards={4} />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={`Employee workspace · ${firstName}`}
        title="Today's money entries"
        description={`Record invoices, paid sales and purchases for ${data.business.business_name}. The owner's ledger updates as soon as you submit.`}
        actions={
          <>
            <Link to="/employee/entries">
              <Button variant="outline" icon={FilePlus2}>
                New sale or purchase
              </Button>
            </Link>
            <Link to="/employee/invoices">
              <Button icon={ReceiptText}>Generate invoice</Button>
            </Link>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Sales submitted"
          value={money(data.summary.sales_total, currency)}
          icon={TrendingUp}
          changeLabel={`${data.summary.sale_count} paid · ${data.summary.invoice_count} invoices`}
          tone="green"
        />
        <StatCard
          label="Purchases logged"
          value={money(data.summary.purchases_total, currency)}
          icon={ShoppingBag}
          changeLabel={`${data.summary.purchase_count} purchase entries`}
          tone="amber"
        />
        <StatCard
          label="Entries submitted"
          value={String(data.summary.submitted)}
          icon={FilePlus2}
          changeLabel={`${data.summary.voided} voided`}
          tone="blue"
        />
        <StatCard
          label="Last entry"
          value={data.summary.last_entry_at ? formatDate(data.summary.last_entry_at) : "—"}
          icon={Wallet}
          changeLabel={data.summary.last_entry_at ? formatDateTime(data.summary.last_entry_at) : "Nothing recorded yet"}
          tone="violet"
        />
      </div>

      <Card>
        <CardHeader
          title="Customer collections"
          description={`Payments you recorded, calculated live in ${data.collections.timezone}. Outstanding and status refresh after every entry.`}
          icon={Wallet}
          actions={
            <Link
              to="/employee/invoices"
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700"
            >
              Open invoices <ArrowRight className="h-3 w-3" />
            </Link>
          }
        />
        <CardBody className="space-y-3 pt-3">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-emerald-700">
                Received today
              </p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums text-emerald-800">
                {money(data.collections.summary.collected_today, data.collections.summary.currency || currency)}
              </p>
              <p className="text-[10px] text-emerald-700/80">
                {data.collections.summary.collected_today_count} payment
                {data.collections.summary.collected_today_count === 1 ? "" : "s"} confirmed
              </p>
            </div>
            <div className="rounded-xl border border-amber-100 bg-amber-50/60 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-amber-700">
                Outstanding
              </p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums text-amber-800">
                {money(data.collections.summary.outstanding_total, data.collections.summary.currency || currency)}
              </p>
              <p className="text-[10px] text-amber-700/80">
                {data.collections.summary.open_invoice_count} open invoice
                {data.collections.summary.open_invoice_count === 1 ? "" : "s"}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Partially paid
              </p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums text-ink-900">
                {data.collections.summary.partially_paid_count}
              </p>
              <p className="text-[10px] text-slate-500">Balance still due from customers</p>
            </div>
            <div className="rounded-xl border border-rose-100 bg-rose-50/60 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-rose-700">Unpaid</p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums text-rose-800">
                {data.collections.summary.unpaid_count}
              </p>
              <p className="text-[10px] text-rose-700/80">No payment received yet</p>
            </div>
          </div>

          <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3">
            <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
              Collection by payment mode · this month
            </p>
            {data.collections.summary.collection_by_mode.length === 0 ? (
              <p className="mt-1.5 text-[11px] text-slate-500">
                No payments recorded this month yet.
              </p>
            ) : (
              <div className="mt-2 flex flex-wrap gap-2">
                {data.collections.summary.collection_by_mode.map((mode) => (
                  <span
                    key={mode.method}
                    className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600"
                  >
                    <span className="font-medium text-ink-900">{mode.label}</span>
                    <span className="tabular-nums">
                      {money(mode.amount, data.collections.summary.currency || currency)}
                    </span>
                    <span className="text-slate-400">· {mode.count}</span>
                  </span>
                ))}
              </div>
            )}
          </div>

          {data.collections.summary.overpaid_count > 0 && (
            <div className="rounded-xl border border-violet-100 bg-violet-50/60 p-3">
              <p className="text-[11px] font-semibold text-violet-800">
                {data.collections.summary.overpaid_count} overpaid invoice
                {data.collections.summary.overpaid_count === 1 ? "" : "s"} ·{" "}
                {money(
                  data.collections.summary.overpaid_total,
                  data.collections.summary.currency || currency,
                )}{" "}
                held as customer credit
              </p>
              <p className="mt-0.5 text-[10px] leading-relaxed text-violet-700">
                Only the owner can approve a refund or credit note for the excess.
              </p>
            </div>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-8">
          <CardHeader
            title="Your recent entries"
            description="Only entries you recorded are visible here."
            icon={Sparkles}
            actions={
              <Link to="/employee/entries" className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700">
                Open editor <ArrowRight className="h-3 w-3" />
              </Link>
            }
          />
          <CardBody className="space-y-2 pt-3">
            {data.entries.map((entry) => {
              const meta = TYPE_META[entry.entry_type];
              return (
                <div
                  key={entry.id}
                  className="flex flex-col gap-2 rounded-xl border border-slate-100 bg-slate-50/60 px-3 py-2.5 sm:flex-row sm:items-center"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-slate-500 shadow-sm">
                    <meta.icon className="h-4 w-4" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-mono text-[11px] font-semibold text-ink-900">{entry.reference}</span>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                      {entry.status === "void" && <Badge tone="red">VOID</Badge>}
                      {entry.payment_method && entry.payment_method !== "credit" && (
                        <span className="text-[10px] uppercase tracking-wide text-slate-400">
                          {entry.payment_method}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-[11px] text-slate-500">
                      {entry.counterparty} · {entry.description}
                    </p>
                  </div>
                  <div className="text-left sm:text-right">
                    <p className="text-xs font-semibold tabular-nums text-ink-900">
                      {money(entry.amount, entry.currency || currency)}
                    </p>
                    <p className="text-[10px] text-slate-400">{formatDateTime(entry.created_at)}</p>
                  </div>
                </div>
              );
            })}
            {data.entries.length === 0 && (
              <div className="py-8 text-center">
                <p className="text-xs text-slate-400">No entries yet. Start with a sale, purchase or invoice.</p>
                <Link to="/employee/entries" className="mt-2 inline-flex text-xs font-semibold text-brand-600">
                  Create the first entry
                </Link>
              </div>
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-4">
          <CardHeader title="Your access" description="Employee accounts are deliberately scoped." icon={Wallet} />
          <CardBody className="space-y-3 pt-3">
            <div className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3">
              <p className="text-xs font-semibold text-emerald-800">Allowed</p>
              <ul className="mt-1.5 space-y-1 text-[11px] text-emerald-700">
                <li>Generate customer invoices</li>
                <li>Record paid sales for your business</li>
                <li>Log purchases and vendor spend</li>
                <li>Record full or partial customer payments</li>
                <li>Edit or void your own unlocked entries</li>
              </ul>
            </div>
            <div className="rounded-xl border border-rose-100 bg-rose-50/60 p-3">
              <p className="text-xs font-semibold text-rose-800">Blocked</p>
              <ul className="mt-1.5 space-y-1 text-[11px] text-rose-700">
                <li>Owner dashboard and cash totals</li>
                <li>Editing or reversing recorded payments</li>
                <li>Other employees&apos; entries</li>
                <li>Other businesses&apos; records</li>
              </ul>
            </div>
            <p className="text-[10px] leading-relaxed text-slate-400">{data.note}</p>
            <div className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2">
              <span className="text-[11px] text-slate-500">Signed in as</span>
              <StatusBadge status="active" label="EMPLOYEE" />
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
