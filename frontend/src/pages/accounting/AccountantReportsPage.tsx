import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, FileCheck2, FileText, Send, ShieldAlert } from "lucide-react";
import { get, getErrorMessage, post } from "../../lib/api";
import type { AccountingClient, AccountingReport } from "../../lib/accountingTypes";
import { labelize } from "../../lib/accounting";
import { formatDate, formatDateTime, money } from "../../lib/utils";
import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageHeader,
  PageSkeleton,
  Select,
  StatCard,
  Textarea,
} from "../../components/ui";
import { StatusBadge } from "../../components/accounting/AccountingUI";

interface MonthlyPayload {
  revenue?: number;
  expenses?: number;
  gross_profit?: number;
  receivables?: number;
  overdue_receivables?: number;
  overdue_invoice_count?: number;
  observations?: string[];
  unusual_entries?: { voucher: string; type: string; party: string; amount: number; reason: string }[];
  gst?: { total?: number };
  voucher_count?: number;
}

interface GstPayload {
  period?: string;
  summary?: {
    output_tax?: number;
    itc_tax?: number;
    net_payable?: number;
    credit_carried_forward?: number;
    direction?: string;
  };
  gstr1?: { total_taxable?: number; total_invoices?: number; b2b?: unknown[]; b2cs?: unknown[] };
  gstr3b?: { net_payable?: number; credit_carried_forward?: number; itc_at_risk?: number };
  mismatches?: { voucher: string; severity: string; title: string; detail: string }[];
  filing_status?: string;
  filing_note?: string;
}

interface FinancialsPayload {
  revenue?: number;
  expenses?: number;
  gross_profit?: number;
  voucher_count?: number;
  basis?: string;
  note?: string;
}

function MonthlyView({ payload }: { payload: MonthlyPayload }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Revenue" value={money(payload.revenue ?? 0)} tone="blue" />
        <StatCard label="Purchases" value={money(payload.expenses ?? 0)} tone="amber" />
        <StatCard label="Gross profit" value={money(payload.gross_profit ?? 0)} tone="green" />
        <StatCard label="GST on period" value={money(payload.gst?.total ?? 0)} tone="violet" />
      </div>
      {payload.observations && payload.observations.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Draft commentary
          </p>
          <ul className="space-y-1.5">
            {payload.observations.map((line) => (
              <li key={line} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12px] text-slate-700">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
      {payload.unusual_entries && payload.unusual_entries.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Unusual entries
          </p>
          <div className="overflow-x-auto rounded-lg border border-amber-200">
            <table className="w-full min-w-[520px] border-collapse">
              <thead className="bg-amber-50">
                <tr>
                  <th className="table-head">Voucher</th>
                  <th className="table-head">Party</th>
                  <th className="table-head">Amount</th>
                  <th className="table-head">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {payload.unusual_entries.map((row) => (
                  <tr key={`${row.voucher}-${row.party}`}>
                    <td className="table-cell text-[11px]">{row.voucher}</td>
                    <td className="table-cell text-[11px]">{row.party}</td>
                    <td className="table-cell tabular text-[11px]">{money(row.amount)}</td>
                    <td className="table-cell text-[11px] text-slate-600">{row.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="text-[11px] text-slate-500">
        Practice receivables {money(payload.receivables ?? 0)} · overdue{" "}
        {money(payload.overdue_receivables ?? 0)} across {payload.overdue_invoice_count ?? 0} invoice(s) ·{" "}
        {payload.voucher_count ?? 0} vouchers in the period.
      </p>
    </div>
  );
}

function GstView({ payload, reportType }: { payload: GstPayload; reportType: string }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Output tax" value={money(payload.summary?.output_tax ?? 0)} tone="amber" />
        <StatCard label="Input credit" value={money(payload.summary?.itc_tax ?? 0)} tone="green" />
        <StatCard label="Net payable" value={money(payload.summary?.net_payable ?? 0)} tone="red" />
        <StatCard
          label="Carry forward"
          value={money(payload.summary?.credit_carried_forward ?? 0)}
          tone="violet"
        />
      </div>
      {reportType === "gstr1" && payload.gstr1 && (
        <p className="text-[12px] text-slate-600">
          {payload.gstr1.total_invoices ?? 0} invoice(s) · taxable value{" "}
          {money(payload.gstr1.total_taxable ?? 0)} · B2B {(payload.gstr1.b2b ?? []).length} · B2C small{" "}
          {(payload.gstr1.b2cs ?? []).length}
        </p>
      )}
      {payload.mismatches && payload.mismatches.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Mismatches to review
          </p>
          <ul className="space-y-1.5">
            {payload.mismatches.map((row) => (
              <li key={`${row.voucher}-${row.title}`} className="rounded-lg border border-rose-200 bg-rose-50/60 px-3 py-2 text-[12px] text-rose-900">
                <span className="font-semibold">{row.title}</span> · {row.voucher} · {row.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Callout tone="amber" icon={ShieldAlert} title="Working paper only">
        {payload.filing_note ||
          "This is a computed GSTR working paper. It is not an official filing and has not been submitted to the GST portal."}
      </Callout>
    </div>
  );
}

function FinancialsView({ payload }: { payload: FinancialsPayload }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Revenue" value={money(payload.revenue ?? 0)} tone="blue" />
        <StatCard label="Expenses" value={money(payload.expenses ?? 0)} tone="amber" />
        <StatCard label="Gross profit" value={money(payload.gross_profit ?? 0)} tone="green" />
      </div>
      <p className="text-[11px] text-slate-500">
        {payload.voucher_count ?? 0} vouchers · basis {labelize(payload.basis || "recorded_vouchers")}
      </p>
      {payload.note && (
        <Callout tone="amber" icon={ShieldAlert} title="Management draft">
          {payload.note}
        </Callout>
      )}
    </div>
  );
}

export function AccountantReportsPage() {
  const [reports, setReports] = useState<AccountingReport[]>([]);
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [busy, setBusy] = useState(false);

  const [detail, setDetail] = useState<AccountingReport | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reviewNote, setReviewNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (clientFilter) params.set("client_id", clientFilter);
      const suffix = params.toString();
      const data = await get<{ items: AccountingReport[] }>(
        `/accounting/senior/reports${suffix ? `?${suffix}` : ""}`,
      );
      setReports(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [status, clientFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    get<{ items: AccountingClient[] }>("/accounting/senior/clients")
      .then((data) => setClients(data.items))
      .catch(() => setClients([]));
  }, []);

  const openDetail = async (report: AccountingReport) => {
    setDetailLoading(true);
    setActionError(null);
    setReviewNote(report.review_notes || "");
    try {
      const full = await get<AccountingReport>(`/accounting/reports/${report.id}`);
      setDetail(full);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setDetailLoading(false);
    }
  };

  const review = async (decision: "approve" | "changes_requested") => {
    if (!detail) return;
    setBusy(true);
    setActionError(null);
    try {
      await post<AccountingReport>(`/accounting/senior/reports/${detail.id}/review`, {
        decision,
        notes: reviewNote || null,
      });
      setDetail(await get<AccountingReport>(`/accounting/reports/${detail.id}`));
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const deliver = async () => {
    if (!detail) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/senior/reports/${detail.id}/deliver`);
      setDetail(await get<AccountingReport>(`/accounting/reports/${detail.id}`));
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading && reports.length === 0) return <PageSkeleton cards={4} />;

  const payload = (detail?.payload || {}) as Record<string, unknown>;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Senior review"
        title="Reports and working papers"
        description="Approve or send back draft working papers before they are delivered to the client portal."
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Awaiting review" value={reports.filter((r) => r.status === "draft").length} icon={FileText} tone="amber" />
        <StatCard label="Changes requested" value={reports.filter((r) => r.status === "changes_requested").length} icon={FileCheck2} tone="red" />
        <StatCard label="Approved" value={reports.filter((r) => r.status === "approved").length} icon={CheckCircle2} tone="green" />
        <StatCard label="Delivered" value={reports.filter((r) => r.status === "delivered").length} icon={Send} tone="blue" />
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          title="Report register"
          description="Drafts are generated from recorded vouchers — never from invented data."
          icon={FileText}
          actions={
            <>
              <Select
                aria-label="Report status"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="h-8 min-w-[150px] text-[11px]"
              >
                <option value="">All statuses</option>
                {["draft", "changes_requested", "approved", "delivered"].map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Client"
                value={clientFilter}
                onChange={(event) => setClientFilter(event.target.value)}
                className="h-8 min-w-[180px] text-[11px]"
              >
                <option value="">All clients</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.business_name}
                  </option>
                ))}
              </Select>
            </>
          }
        />
        <CardBody className="pt-0">
          {error ? (
            <ErrorState message={error} onRetry={load} />
          ) : reports.length === 0 ? (
            <EmptyState
              title="No reports yet"
              description="Prepare a working paper from the workbench for a client engagement."
              icon={FileText}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head">Report</th>
                    <th className="table-head">Client</th>
                    <th className="table-head">FY</th>
                    <th className="table-head">Period</th>
                    <th className="table-head">Version</th>
                    <th className="table-head">Status</th>
                    <th className="table-head">Created</th>
                    <th className="table-head"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {reports.map((report) => (
                    <tr key={report.id} className="row-hover">
                      <td className="table-cell">
                        <p className="text-[12px] font-semibold text-ink-900">{labelize(report.report_type)}</p>
                        <p className="text-[10px] text-slate-500">#{report.id}</p>
                      </td>
                      <td className="table-cell text-[11px] text-slate-600">{report.client_name}</td>
                      <td className="table-cell text-[11px] text-slate-500">{report.financial_year}</td>
                      <td className="table-cell text-[11px] text-slate-500">{report.period_label}</td>
                      <td className="table-cell text-[11px] text-slate-500">v{report.version}</td>
                      <td className="table-cell">
                        <StatusBadge status={report.status} />
                      </td>
                      <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                        {formatDate(report.created_at)}
                      </td>
                      <td className="table-cell">
                        <Button size="sm" variant="outline" onClick={() => void openDetail(report)}>
                          Review
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>

      <Modal
        open={Boolean(detail) || detailLoading}
        onClose={() => setDetail(null)}
        title={detail ? `${labelize(detail.report_type)} · ${detail.period_label}` : "Loading report"}
        description={detail ? `${detail.client_name} · FY ${detail.financial_year} · ${labelize(detail.status)}` : undefined}
        size="lg"
        footer={
          detail ? (
            <>
              <Button variant="outline" onClick={() => setDetail(null)}>
                Close
              </Button>
              {detail.status === "approved" ? (
                <Button icon={Send} loading={busy} onClick={deliver}>
                  Deliver to client
                </Button>
              ) : detail.status !== "delivered" ? (
                <>
                  <Button
                    variant="outline"
                    loading={busy}
                    onClick={() => void review("changes_requested")}
                  >
                    Request changes
                  </Button>
                  <Button icon={CheckCircle2} loading={busy} onClick={() => void review("approve")}>
                    Approve
                  </Button>
                </>
              ) : null}
            </>
          ) : undefined
        }
      >
        {detail ? (
          <div className="space-y-4">
            {detail.status === "delivered" && (
              <Callout tone="green" icon={CheckCircle2} title="Delivered">
                Delivered {formatDateTime(detail.delivered_at)}. This working paper is visible in the client portal.
              </Callout>
            )}
            {detail.review_notes && (
              <Callout tone="amber" title="Previous review note">
                {detail.review_notes}
              </Callout>
            )}

            {detail.report_type === "monthly_summary" && <MonthlyView payload={payload as MonthlyPayload} />}
            {(detail.report_type === "gstr1" || detail.report_type === "gstr3b") && (
              <GstView payload={payload as GstPayload} reportType={detail.report_type} />
            )}
            {detail.report_type === "financials" && <FinancialsView payload={payload as FinancialsPayload} />}

            {detail.status !== "delivered" && (
              <Field
                label="Review note"
                htmlFor="report_review_note"
                hint="Sent to the preparer when changes are requested; stored with the report when approved."
              >
                <Textarea
                  id="report_review_note"
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                  placeholder="What needs attention before this is delivered?"
                />
              </Field>
            )}

            <details className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <summary className="cursor-pointer text-[11px] font-semibold text-slate-600">
                Full working paper data
              </summary>
              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-[10px] leading-relaxed text-slate-600">
                {JSON.stringify(detail.payload, null, 2)}
              </pre>
            </details>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="h-24 animate-pulse rounded-lg bg-slate-100" />
            <div className="h-24 animate-pulse rounded-lg bg-slate-100" />
          </div>
        )}
      </Modal>
    </div>
  );
}
