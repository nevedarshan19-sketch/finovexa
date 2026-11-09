import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeftRight,
  BadgeCheck,
  BellRing,
  CalendarClock,
  CircleDollarSign,
  Download,
  FileSpreadsheet,
  Landmark,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Users,
  Wallet,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { downloadFile, getErrorMessage, post, put } from "../lib/api";
import type {
  CreditAlert,
  CreditAlertSettings,
  CreditCustomer,
  CreditPage,
  CreditReportCatalogueItem,
  CreditReportPayload,
  CreditSupplier,
  CreditSummary,
} from "../lib/creditTypes";
import { useToast } from "../context/ToastContext";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  ProgressBar,
  Select,
  StatCard,
  TBody,
  TD,
  TH,
  THead,
  TR,
  TableWrap,
  Tabs,
  Textarea,
} from "../components/ui";
import { BillStatusBadge, ReportCell, RiskBadge, SupplierStatusBadge } from "../components/credit/CreditUi";
import { formatDate, money, moneyExact, plainPct, titleCase } from "../lib/utils";

type TabKey = "customers" | "suppliers" | "alerts" | "reports";
type SortOrder = "asc" | "desc";

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

function supplierInitial() {
  return {
    name: "",
    gstin: "",
    email: "",
    phone: "",
    city: "",
    state: "",
    payment_terms_days: "30",
    credit_limit: "0",
    opening_balance: "0",
    opening_balance_date: "",
    status: "active",
    notes: "",
  };
}

function NewSupplierModal({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast();
  const [form, setForm] = useState(supplierInitial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const update = (key: keyof ReturnType<typeof supplierInitial>, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await post("/credit/suppliers", {
        name: form.name.trim(),
        gstin: form.gstin.trim() || null,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        city: form.city.trim() || null,
        state: form.state.trim() || null,
        payment_terms_days: Number(form.payment_terms_days) || 0,
        credit_limit: form.credit_limit || "0",
        opening_balance: form.opening_balance || "0",
        opening_balance_date: form.opening_balance_date || null,
        status: form.status,
        notes: form.notes.trim() || null,
      });
      toast({ title: "Supplier created", description: "The supplier master is ready for purchase bills.", tone: "success" });
      setForm(supplierInitial());
      onSaved();
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New supplier"
      description="Suppliers hold payment terms and payables. Historical expense text is never changed."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button icon={Plus} onClick={submit} loading={saving} disabled={form.name.trim().length < 2}>
            Create supplier
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {error && (
          <div className="sm:col-span-2">
            <Callout tone="red" title="Could not create the supplier">{error}</Callout>
          </div>
        )}
        <Field label="Supplier name" htmlFor="supplier-name" required className="sm:col-span-2">
          <Input id="supplier-name" value={form.name} onChange={(event) => update("name", event.target.value)} maxLength={160} />
        </Field>
        <Field label="GSTIN" htmlFor="supplier-gstin" hint="Used for matching when both records carry a GSTIN.">
          <Input id="supplier-gstin" value={form.gstin} onChange={(event) => update("gstin", event.target.value.toUpperCase())} maxLength={15} />
        </Field>
        <Field label="Payment terms (days)" htmlFor="supplier-terms">
          <Input id="supplier-terms" type="number" min={0} max={365} value={form.payment_terms_days} onChange={(event) => update("payment_terms_days", event.target.value)} />
        </Field>
        <Field label="Email" htmlFor="supplier-email">
          <Input id="supplier-email" type="email" value={form.email} onChange={(event) => update("email", event.target.value)} />
        </Field>
        <Field label="Phone" htmlFor="supplier-phone">
          <Input id="supplier-phone" value={form.phone} onChange={(event) => update("phone", event.target.value)} maxLength={40} />
        </Field>
        <Field label="City" htmlFor="supplier-city">
          <Input id="supplier-city" value={form.city} onChange={(event) => update("city", event.target.value)} />
        </Field>
        <Field label="State" htmlFor="supplier-state">
          <Input id="supplier-state" value={form.state} onChange={(event) => update("state", event.target.value)} />
        </Field>
        <Field label="Opening balance (INR)" htmlFor="supplier-opening" hint="Existing payable carried into FINOVEXA.">
          <Input id="supplier-opening" type="number" min={0} step="0.01" value={form.opening_balance} onChange={(event) => update("opening_balance", event.target.value)} />
        </Field>
        <Field label="Opening balance date" htmlFor="supplier-opening-date">
          <Input id="supplier-opening-date" type="date" value={form.opening_balance_date} onChange={(event) => update("opening_balance_date", event.target.value)} />
        </Field>
        <Field label="Status" htmlFor="supplier-status">
          <Select id="supplier-status" value={form.status} onChange={(event) => update("status", event.target.value)}>
            <option value="active">Active</option>
            <option value="on_hold">On hold</option>
            <option value="inactive">Inactive</option>
          </Select>
        </Field>
        <Field label="Notes" htmlFor="supplier-notes" className="sm:col-span-2">
          <Textarea id="supplier-notes" value={form.notes} onChange={(event) => update("notes", event.target.value)} maxLength={2000} />
        </Field>
      </div>
    </Modal>
  );
}

interface MatchResult {
  dry_run: boolean;
  proposed: { vendor: string; supplier_id: number; supplier_name: string; match: string }[];
  linked_rows: number;
  ambiguous: { vendor: string; candidates: { id: number; name: string; gstin: string | null }[] }[];
  unmatched: string[];
  supplier_count: number;
  note: string;
}

function MatchVendorsModal({ open, onClose, onApplied }: { open: boolean; onClose: () => void; onApplied: () => void }) {
  const { toast } = useToast();
  const [result, setResult] = useState<MatchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const data = await post<MatchResult>("/credit/suppliers/match", { dry_run: dryRun });
      setResult(data);
      if (!dryRun) {
        toast({
          title: "Historical bills linked",
          description: `${data.linked_rows} expense row(s) linked. Vendor text was not rewritten.`,
          tone: "success",
        });
        onApplied();
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    setResult(null);
    setError(null);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Match historical vendors"
      description="Only one-to-one name matches are linked. Ambiguous vendors stay in review and no vendor text changes."
      footer={
        <>
          <Button variant="outline" onClick={close} disabled={busy}>
            Close
          </Button>
          <Button icon={Search} variant="secondary" onClick={() => run(true)} loading={busy && !result}>
            Preview matches
          </Button>
          <Button
            icon={ArrowLeftRight}
            onClick={() => run(false)}
            loading={busy && Boolean(result)}
            disabled={!result || result.proposed.length === 0 || !result.dry_run}
          >
            Apply matches
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && <Callout tone="red" title="Matching failed">{error}</Callout>}
        {!result && (
          <Callout tone="blue" title="Nothing changes during preview">
            Preview lists the supplier links that would be created. Nothing is written until you apply.
          </Callout>
        )}
        {result && (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge tone="green" dot>{result.proposed.length} ready</Badge>
              <Badge tone="amber" dot>{result.ambiguous.length} ambiguous</Badge>
              <Badge tone="slate" dot>{result.unmatched.length} unmatched</Badge>
              <Badge tone={result.dry_run ? "blue" : "violet"}>{result.dry_run ? "PREVIEW" : `APPLIED · ${result.linked_rows} rows`}</Badge>
            </div>
            <div className="max-h-[320px] space-y-3 overflow-y-auto pr-1">
              {result.proposed.map((row) => (
                <div key={row.vendor} className="rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs">
                  <p className="font-semibold text-emerald-800">{row.vendor}</p>
                  <p className="text-emerald-700">→ {row.supplier_name} · {titleCase(row.match)}</p>
                </div>
              ))}
              {result.ambiguous.map((row) => (
                <div key={row.vendor} className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs">
                  <p className="font-semibold text-amber-800">{row.vendor}</p>
                  <p className="text-amber-700">
                    Multiple suppliers: {row.candidates.map((candidate) => candidate.name).join(", ")}
                  </p>
                </div>
              ))}
              {result.unmatched.map((vendor) => (
                <div key={vendor} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                  {vendor} · no supplier with this name
                </div>
              ))}
              {result.proposed.length + result.ambiguous.length + result.unmatched.length === 0 && (
                <p className="text-sm text-slate-500">No unlinked purchase bills were found.</p>
              )}
            </div>
            <p className="text-[11px] leading-relaxed text-slate-500">{result.note}</p>
          </>
        )}
      </div>
    </Modal>
  );
}

export function CreditControlPage() {
  const { toast } = useToast();
  const [tab, setTab] = useState<TabKey>("customers");
  const [customerQuery, setCustomerQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("all");
  const [customerSort, setCustomerSort] = useState("outstanding");
  const [customerOrder, setCustomerOrder] = useState<SortOrder>("desc");
  const [customerPage, setCustomerPage] = useState(1);
  const [supplierQuery, setSupplierQuery] = useState("");
  const [supplierStatus, setSupplierStatus] = useState("all");
  const [supplierPage, setSupplierPage] = useState(1);
  const [newSupplierOpen, setNewSupplierOpen] = useState(false);
  const [matchOpen, setMatchOpen] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [dismissing, setDismissing] = useState<number | null>(null);
  const [reportKey, setReportKey] = useState("customer_outstanding");
  const [reportCustomer, setReportCustomer] = useState("");
  const [reportSupplier, setReportSupplier] = useState("");
  const [reportFrom, setReportFrom] = useState("");
  const [reportTo, setReportTo] = useState("");
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [previewNonce, setPreviewNonce] = useState(0);

  const summary = useApi<CreditSummary>("/credit/summary");
  const customers = useApi<CreditPage<CreditCustomer>>(
    `/credit/customers${query({ q: customerQuery, risk: riskFilter, sort: customerSort, order: customerOrder, page: customerPage, page_size: 20 })}`,
  );
  const suppliers = useApi<CreditPage<CreditSupplier>>(
    `/credit/suppliers${query({ q: supplierQuery, status: supplierStatus, sort: "payable", order: "desc", page: supplierPage, page_size: 20 })}`,
  );
  const alerts = useApi<{ items: CreditAlert[] }>("/credit/alerts?status=open&limit=100");
  const settings = useApi<CreditAlertSettings>("/credit/alert-settings");
  const catalogue = useApi<{ items: CreditReportCatalogueItem[] }>("/credit/reports");
  const reportCustomers = useApi<CreditPage<CreditCustomer>>(tab === "reports" ? "/credit/customers?page_size=200&sort=name&order=asc" : null);
  const reportSuppliers = useApi<CreditPage<CreditSupplier>>(tab === "reports" ? "/credit/suppliers?page_size=200&sort=name&order=asc" : null);

  const activeReport = catalogue.data?.items.find((item) => item.key === reportKey) || null;
  const preview = useApi<CreditReportPayload>(
    previewKey
      ? `/credit/reports/${previewKey}${query({
          customer_id: activeRequires(previewKey, "customer_id") ? reportCustomer || null : null,
          supplier_id: activeRequires(previewKey, "supplier_id") ? reportSupplier || null : null,
          date_from: reportFrom || null,
          date_to: reportTo || null,
          _: previewNonce,
        })}`
      : null,
  );

  function activeRequires(key: string, field: "customer_id" | "supplier_id") {
    const item = catalogue.data?.items.find((entry) => entry.key === key);
    return item?.requires === field;
  }

  const reloadAll = () => {
    summary.reload();
    customers.reload();
    suppliers.reload();
    alerts.reload();
  };

  const refreshAlerts = async () => {
    setEvaluating(true);
    try {
      const result = await post<{ created: number; skipped: number; emails_sent: number }>("/credit/alerts/evaluate", { send_email: false });
      toast({
        title: result.created ? `${result.created} alert(s) raised` : "No new alerts",
        description: result.created
          ? "New credit events were recorded. Open the alerts tab to review them."
          : "Existing alerts already cover the current position.",
        tone: "success",
      });
      alerts.reload();
      summary.reload();
    } catch (err) {
      toast({ title: "Alert check failed", description: getErrorMessage(err), tone: "error" });
    } finally {
      setEvaluating(false);
    }
  };

  const dismiss = async (alertId: number) => {
    setDismissing(alertId);
    try {
      await post(`/credit/alerts/${alertId}/dismiss`, {});
      alerts.reload();
      summary.reload();
    } catch (err) {
      toast({ title: "Could not dismiss the alert", description: getErrorMessage(err), tone: "error" });
    } finally {
      setDismissing(null);
    }
  };

  const download = async (format: "xlsx" | "pdf") => {
    const params: Record<string, string> = { format };
    if (activeReport?.requires === "customer_id") params.customer_id = reportCustomer;
    if (activeReport?.requires === "supplier_id") params.supplier_id = reportSupplier;
    if (reportFrom) params.date_from = reportFrom;
    if (reportTo) params.date_to = reportTo;
    try {
      await downloadFile(
        `/credit/reports/${reportKey}/export?${new URLSearchParams(params).toString()}`,
        `finovexa-${reportKey.replace(/_/g, "-")}.${format}`,
      );
    } catch (err) {
      toast({ title: "Export failed", description: getErrorMessage(err), tone: "error" });
    }
  };

  const previewReport = () => {
    if (activeReport?.requires === "customer_id" && !reportCustomer) {
      toast({ title: "Select a customer", description: "The customer ledger statement needs one customer.", tone: "error" });
      return;
    }
    if (activeReport?.requires === "supplier_id" && !reportSupplier) {
      toast({ title: "Select a supplier", description: "The supplier ledger statement needs one supplier.", tone: "error" });
      return;
    }
    setPreviewKey(null);
    setPreviewNonce((value) => value + 1);
    window.setTimeout(() => setPreviewKey(reportKey), 0);
  };

  const tabs = useMemo(
    () => [
      { key: "customers" as const, label: "Customers", count: summary.data?.customers },
      { key: "suppliers" as const, label: "Suppliers", count: summary.data?.suppliers },
      { key: "alerts" as const, label: "Alerts", count: summary.data?.open_alerts },
      { key: "reports" as const, label: "Reports" },
    ],
    [summary.data],
  );

  if (summary.loading && !summary.data) {
    return (
      <div className="space-y-5">
        <PageSkeleton cards={5} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Credit control"
        title="Customer & supplier credit"
        description="Receivables, payables, credit limits, ageing and statements built from the existing invoice, payment and expense ledgers."
        actions={
          <>
            <Button variant="outline" icon={RefreshCw} onClick={refreshAlerts} loading={evaluating}>
              Run credit check
            </Button>
            <Button variant="secondary" icon={ArrowLeftRight} onClick={() => setMatchOpen(true)}>
              Match vendors
            </Button>
          </>
        }
      />

      {summary.error && <ErrorState message={summary.error} onRetry={summary.reload} />}

      {summary.data && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <StatCard label="Total receivables" value={money(summary.data.total_receivables, summary.data.currency)} icon={Wallet} tone="blue" sub={`${summary.data.customers} customers`} />
          <StatCard label="Total payables" value={money(summary.data.total_payables, summary.data.currency)} icon={Landmark} tone="violet" sub={`${summary.data.suppliers} suppliers`} />
          <StatCard label="Overdue receivables" value={money(summary.data.overdue_receivables, summary.data.currency)} icon={CalendarClock} tone="red" sub={`${summary.data.customers_over_limit} over limit`} />
          <StatCard label="Overdue payables" value={money(summary.data.overdue_payables, summary.data.currency)} icon={AlertTriangle} tone="amber" sub={`${summary.data.unmatched_bills} unmatched bill(s)`} />
          <StatCard label="Available customer credit" value={money(summary.data.available_customer_credit, summary.data.currency)} icon={BadgeCheck} tone="green" sub={`${summary.data.customers_on_hold} on hold`} />
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs items={tabs} value={tab} onChange={(key) => setTab(key)} />
        <p className="text-[11px] text-slate-400">
          As of {formatDate(summary.data?.as_of)} · figures are derived, never duplicated
        </p>
      </div>

      {tab === "customers" && (
        <Card>
          <CardHeader
            title="Customer credit book"
            description="Limit, utilisation and ageing per customer. Open a customer for the full ledger."
            icon={Users}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
                  <Input
                    value={customerQuery}
                    onChange={(event) => {
                      setCustomerQuery(event.target.value);
                      setCustomerPage(1);
                    }}
                    placeholder="Search customers"
                    className="h-9 w-[210px] pl-8 text-xs"
                    aria-label="Search customers"
                  />
                </div>
                <Select value={riskFilter} onChange={(event) => { setRiskFilter(event.target.value); setCustomerPage(1); }} className="h-9 w-[140px] text-xs" aria-label="Filter by risk">
                  <option value="all">All risk</option>
                  <option value="normal">Normal</option>
                  <option value="watch">Watch</option>
                  <option value="critical">Critical</option>
                  <option value="over_limit">Over limit</option>
                  <option value="overdue">Overdue</option>
                  <option value="on_hold">On hold</option>
                  <option value="not_configured">No limit</option>
                </Select>
                <Select
                  value={`${customerSort}:${customerOrder}`}
                  onChange={(event) => {
                    const [sort, order] = event.target.value.split(":");
                    setCustomerSort(sort);
                    setCustomerOrder(order as SortOrder);
                    setCustomerPage(1);
                  }}
                  className="h-9 w-[190px] text-xs"
                  aria-label="Sort customers"
                >
                  <option value="outstanding:desc">Outstanding · high to low</option>
                  <option value="overdue:desc">Overdue · high to low</option>
                  <option value="utilization_pct:desc">Utilisation · high to low</option>
                  <option value="credit_limit:desc">Credit limit · high to low</option>
                  <option value="name:asc">Name · A to Z</option>
                </Select>
              </div>
            }
          />
          <CardBody className="pt-4">
            {customers.error && <ErrorState message={customers.error} onRetry={customers.reload} />}
            {!customers.data?.items.length && !customers.loading && (
              <EmptyState title="No customers match" description="Adjust the search or risk filter to see more customers." />
            )}
            {customers.data && customers.data.items.length > 0 && (
              <>
                <TableWrap>
                  <THead>
                    <TR>
                      <TH>Customer</TH>
                      <TH>Credit limit</TH>
                      <TH>Outstanding</TH>
                      <TH>Overdue</TH>
                      <TH>Available</TH>
                      <TH className="min-w-[150px]">Utilisation</TH>
                      <TH>Risk</TH>
                      <TH />
                    </TR>
                  </THead>
                  <TBody>
                    {customers.data.items.map((row) => (
                      <TR key={row.id}>
                        <TD>
                          <Link to={`/credit/customers/${row.id}`} className="font-semibold text-ink-900 hover:text-brand-600">
                            {row.name}
                          </Link>
                          <p className="text-[11px] text-slate-400">{row.gstin || row.company || row.email || "No GSTIN"}</p>
                        </TD>
                        <TD className="tabular">{moneyExact(row.credit_limit)}</TD>
                        <TD className="tabular font-semibold">{moneyExact(row.outstanding)}</TD>
                        <TD className={"tabular " + (row.overdue > 0 ? "text-rose-600" : "text-slate-500")}>{moneyExact(row.overdue)}</TD>
                        <TD className="tabular">{moneyExact(row.available_credit)}</TD>
                        <TD>
                          <div className="flex items-center gap-2">
                            <ProgressBar
                              value={Math.min(Number(row.utilization_pct) || 0, 100)}
                              tone={row.risk_status === "over_limit" || row.risk_status === "critical" ? "red" : row.risk_status === "watch" ? "amber" : "blue"}
                              label={`${row.name} utilisation`}
                            />
                            <span className="w-12 shrink-0 text-right text-[11px] tabular text-slate-500">
                              {row.utilization_pct === null ? "—" : plainPct(Number(row.utilization_pct))}
                            </span>
                          </div>
                        </TD>
                        <TD><RiskBadge status={row.risk_status} /></TD>
                        <TD className="text-right">
                          <Link to={`/credit/customers/${row.id}`} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
                            View
                          </Link>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </TableWrap>
                <Pager
                  page={customers.data.page}
                  pages={customers.data.pages}
                  total={customers.data.total}
                  onChange={setCustomerPage}
                />
              </>
            )}
          </CardBody>
        </Card>
      )}

      {tab === "suppliers" && (
        <Card>
          <CardHeader
            title="Supplier payables"
            description="Bills stay as expenses; payouts are separate supplier payments with their own audit trail."
            icon={Landmark}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
                  <Input
                    value={supplierQuery}
                    onChange={(event) => {
                      setSupplierQuery(event.target.value);
                      setSupplierPage(1);
                    }}
                    placeholder="Search suppliers"
                    className="h-9 w-[210px] pl-8 text-xs"
                    aria-label="Search suppliers"
                  />
                </div>
                <Select value={supplierStatus} onChange={(event) => { setSupplierStatus(event.target.value); setSupplierPage(1); }} className="h-9 w-[140px] text-xs" aria-label="Filter suppliers by status">
                  <option value="all">All statuses</option>
                  <option value="active">Active</option>
                  <option value="on_hold">On hold</option>
                  <option value="inactive">Inactive</option>
                </Select>
                <Button size="sm" icon={Plus} onClick={() => setNewSupplierOpen(true)}>
                  New supplier
                </Button>
              </div>
            }
          />
          <CardBody className="pt-4">
            {suppliers.error && <ErrorState message={suppliers.error} onRetry={suppliers.reload} />}
            {!suppliers.data?.items.length && !suppliers.loading && (
              <EmptyState
                title="No suppliers yet"
                description="Create the supplier master, then match historical purchase vendors by name."
              />
            )}
            {suppliers.data && suppliers.data.items.length > 0 && (
              <>
                <TableWrap>
                  <THead>
                    <TR>
                      <TH>Supplier</TH>
                      <TH>Terms</TH>
                      <TH>Billed</TH>
                      <TH>Paid</TH>
                      <TH>Payable</TH>
                      <TH>Overdue</TH>
                      <TH>Status</TH>
                      <TH />
                    </TR>
                  </THead>
                  <TBody>
                    {suppliers.data.items.map((row) => (
                      <TR key={row.id}>
                        <TD>
                          <Link to={`/credit/suppliers/${row.id}`} className="font-semibold text-ink-900 hover:text-brand-600">
                            {row.name}
                          </Link>
                          <p className="text-[11px] text-slate-400">{row.gstin || row.city || row.email || "No GSTIN"}</p>
                        </TD>
                        <TD>{row.payment_terms_days} days</TD>
                        <TD className="tabular">{moneyExact(row.billed)}</TD>
                        <TD className="tabular">{moneyExact(row.paid)}</TD>
                        <TD className="tabular font-semibold">{moneyExact(row.payable)}</TD>
                        <TD className={"tabular " + (row.overdue > 0 ? "text-rose-600" : "text-slate-500")}>{moneyExact(row.overdue)}</TD>
                        <TD><SupplierStatusBadge status={row.status} /></TD>
                        <TD className="text-right">
                          <Link to={`/credit/suppliers/${row.id}`} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
                            View
                          </Link>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </TableWrap>
                <Pager page={suppliers.data.page} pages={suppliers.data.pages} total={suppliers.data.total} onChange={setSupplierPage} />
              </>
            )}
          </CardBody>
        </Card>
      )}

      {tab === "alerts" && (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Card>
            <CardHeader
              title="Open credit alerts"
              description="Raised from utilisation, due dates and overdue thresholds. Evaluated on demand; duplicates are suppressed."
              icon={ShieldAlert}
              actions={<Button size="sm" variant="outline" icon={RefreshCw} onClick={refreshAlerts} loading={evaluating}>Check now</Button>}
            />
            <CardBody className="pt-4">
              {alerts.error && <ErrorState message={alerts.error} onRetry={alerts.reload} />}
              {!alerts.data?.items.length && !alerts.loading && (
                <EmptyState title="No open alerts" description="Run a credit check to evaluate limits, due dates and overdues." icon={BellRing} />
              )}
              {alerts.data && alerts.data.items.length > 0 && (
                <div className="space-y-2">
                  {alerts.data.items.map((alert) => (
                    <div key={alert.id} className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={alert.kind.includes("critical") || alert.kind.includes("overdue") ? "red" : "amber"}>
                            {titleCase(alert.kind)}
                          </Badge>
                          <span className="text-[11px] tabular text-slate-400">{moneyExact(alert.amount)}</span>
                          {alert.due_on && <span className="text-[11px] text-slate-400">due {formatDate(alert.due_on)}</span>}
                        </div>
                        <p className="mt-1 text-sm font-semibold text-ink-900">{alert.title}</p>
                        <p className="text-xs leading-relaxed text-slate-500">{alert.body}</p>
                      </div>
                      <Button size="sm" variant="ghost" onClick={() => dismiss(alert.id)} loading={dismissing === alert.id}>
                        Dismiss
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
          <AlertSettingsCard settings={settings.data} loading={settings.loading} reloaded={() => { settings.reload(); summary.reload(); }} />
        </div>
      )}

      {tab === "reports" && (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Credit reports"
              description="Eight reports from the same verified numbers, with Excel and PDF exports."
              icon={FileSpreadsheet}
            />
            <CardBody className="space-y-4 pt-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="Report" htmlFor="report-key">
                  <Select id="report-key" value={reportKey} onChange={(event) => { setReportKey(event.target.value); setPreviewKey(null); }}>
                    {(catalogue.data?.items || []).map((item) => (
                      <option key={item.key} value={item.key}>{item.title}</option>
                    ))}
                  </Select>
                </Field>
                {activeReport?.requires === "customer_id" && (
                  <Field label="Customer" htmlFor="report-customer">
                    <Select id="report-customer" value={reportCustomer} onChange={(event) => setReportCustomer(event.target.value)}>
                      <option value="">Select a customer</option>
                      {(reportCustomers.data?.items || []).map((row) => (
                        <option key={row.id} value={row.id}>{row.name}</option>
                      ))}
                    </Select>
                  </Field>
                )}
                {activeReport?.requires === "supplier_id" && (
                  <Field label="Supplier" htmlFor="report-supplier">
                    <Select id="report-supplier" value={reportSupplier} onChange={(event) => setReportSupplier(event.target.value)}>
                      <option value="">Select a supplier</option>
                      {(reportSuppliers.data?.items || []).map((row) => (
                        <option key={row.id} value={row.id}>{row.name}</option>
                      ))}
                    </Select>
                  </Field>
                )}
                <Field label="From date" htmlFor="report-from">
                  <Input id="report-from" type="date" value={reportFrom} onChange={(event) => setReportFrom(event.target.value)} />
                </Field>
                <Field label="To date" htmlFor="report-to">
                  <Input id="report-to" type="date" value={reportTo} onChange={(event) => setReportTo(event.target.value)} />
                </Field>
              </div>
              {activeReport && <p className="text-xs leading-relaxed text-slate-500">{activeReport.description}</p>}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" icon={Search} onClick={previewReport}>Preview</Button>
                <Button size="sm" variant="outline" icon={FileSpreadsheet} onClick={() => download("xlsx")}>Excel</Button>
                <Button size="sm" variant="outline" icon={Download} onClick={() => download("pdf")}>PDF</Button>
              </div>
            </CardBody>
          </Card>

          {preview.error && <ErrorState message={preview.error} onRetry={preview.reload} />}
          {preview.data && (
            <Card>
              <CardHeader
                title={preview.data.title}
                description={`${preview.data.row_count} row(s) · as of ${formatDate(preview.data.as_of)}${preview.data.customer ? ` · ${preview.data.customer.name}` : preview.data.supplier ? ` · ${preview.data.supplier.name}` : ""}`}
              />
              <CardBody className="pt-4">
                <TableWrap>
                  <THead>
                    <TR>{preview.data.columns.map((column) => <TH key={column.key}>{column.label}</TH>)}</TR>
                  </THead>
                  <TBody>
                    {preview.data.rows.map((row, index) => (
                      <TR key={index}>
                        {preview.data!.columns.map((column) => (
                          <TD key={column.key}><ReportCell column={column} value={row[column.key]} /></TD>
                        ))}
                      </TR>
                    ))}
                    {preview.data.rows.length === 0 && (
                      <TR><TD>{<span className="text-slate-400">No rows for this selection.</span>}</TD></TR>
                    )}
                  </TBody>
                </TableWrap>
                {Object.keys(preview.data.totals).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
                    {Object.entries(preview.data.totals).map(([key, value]) => (
                      <span key={key}>
                        <span className="font-semibold text-slate-700">{titleCase(key)}:</span> {moneyExact(value)}
                      </span>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>
          )}
        </div>
      )}

      <NewSupplierModal
        open={newSupplierOpen}
        onClose={() => setNewSupplierOpen(false)}
        onSaved={() => { suppliers.reload(); summary.reload(); }}
      />
      <MatchVendorsModal
        open={matchOpen}
        onClose={() => setMatchOpen(false)}
        onApplied={() => { suppliers.reload(); summary.reload(); }}
      />
    </div>
  );
}

function AlertSettingsCard({
  settings,
  loading,
  reloaded,
}: {
  settings: CreditAlertSettings | null;
  loading: boolean;
  reloaded: () => void;
}) {
  const { toast } = useToast();
  const [draft, setDraft] = useState<CreditAlertSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = draft || settings;
  const update = (key: keyof CreditAlertSettings, next: number | boolean) =>
    setDraft((current) => ({ ...(current || settings || ({} as CreditAlertSettings)), [key]: next }) as CreditAlertSettings);

  const save = async () => {
    if (!value) return;
    setSaving(true);
    setError(null);
    try {
      await put("/credit/alert-settings", {
        utilization_warn_pct: Number(value.utilization_warn_pct),
        utilization_critical_pct: Number(value.utilization_critical_pct),
        due_soon_days: Number(value.due_soon_days),
        overdue_escalation_days: Number(value.overdue_escalation_days),
        supplier_due_soon_days: Number(value.supplier_due_soon_days),
        in_app_enabled: Boolean(value.in_app_enabled),
        email_enabled: Boolean(value.email_enabled),
      });
      toast({ title: "Alert settings saved", description: "Thresholds apply to the next credit check.", tone: "success" });
      setDraft(null);
      reloaded();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !value) return <Card><CardBody><PageSkeleton cards={2} /></CardBody></Card>;
  if (!value) return null;

  return (
    <Card>
      <CardHeader title="Alert settings" description="Owner-configured thresholds. Email uses the existing delivery setup and stays off by default." icon={BellRing} />
      <CardBody className="space-y-3 pt-4">
        {error && <Callout tone="red" title="Could not save">{error}</Callout>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Warning utilisation %" htmlFor="alert-warn">
            <Input id="alert-warn" type="number" min={1} max={99} value={value.utilization_warn_pct} onChange={(event) => update("utilization_warn_pct", Number(event.target.value))} />
          </Field>
          <Field label="Critical utilisation %" htmlFor="alert-critical">
            <Input id="alert-critical" type="number" min={2} max={100} value={value.utilization_critical_pct} onChange={(event) => update("utilization_critical_pct", Number(event.target.value))} />
          </Field>
          <Field label="Due soon (days)" htmlFor="alert-due">
            <Input id="alert-due" type="number" min={0} max={365} value={value.due_soon_days} onChange={(event) => update("due_soon_days", Number(event.target.value))} />
          </Field>
          <Field label="Escalate after (days)" htmlFor="alert-escalate">
            <Input id="alert-escalate" type="number" min={1} max={365} value={value.overdue_escalation_days} onChange={(event) => update("overdue_escalation_days", Number(event.target.value))} />
          </Field>
          <Field label="Supplier due soon (days)" htmlFor="alert-supplier">
            <Input id="alert-supplier" type="number" min={0} max={365} value={value.supplier_due_soon_days} onChange={(event) => update("supplier_due_soon_days", Number(event.target.value))} />
          </Field>
        </div>
        <Checkbox checked={Boolean(value.in_app_enabled)} onChange={(checked) => update("in_app_enabled", checked)} label="Create in-app alerts" />
        <Checkbox checked={Boolean(value.email_enabled)} onChange={(checked) => update("email_enabled", checked)} label="Also email the customer or supplier contact" />
        <Button size="sm" onClick={save} loading={saving}>Save thresholds</Button>
      </CardBody>
    </Card>
  );
}

function Pager({
  page,
  pages,
  total,
  onChange,
}: {
  page: number;
  pages: number;
  total: number;
  onChange: (page: number) => void;
}) {
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
      <span>{total} record(s) · page {page} of {Math.max(pages, 1)}</span>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => onChange(page - 1)} disabled={page <= 1}>Previous</Button>
        <Button size="sm" variant="outline" onClick={() => onChange(page + 1)} disabled={page >= pages}>Next</Button>
      </div>
    </div>
  );
}
