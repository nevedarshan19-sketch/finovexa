import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  Download,
  Eye,
  FileSpreadsheet,
  History,
  Package,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Upload,
  XCircle,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { ApiError, downloadFile, get, getErrorMessage, patch, post } from "../../lib/api";
import type {
  AccountingClient,
  TallyExportBatch,
  TallyExportCatalog,
  TallyExportFormat,
  TallyExportList,
  TallyExportTypeKey,
  TallyImportStatus,
  TallyStockItem,
  TallyValidationCheck,
  TallyValidationIssue,
  TallyValidationReport,
} from "../../lib/accountingTypes";
import { formatBytes, labelize, tallyExportFormatLabel } from "../../lib/accounting";
import { formatDate, formatDateTime, money } from "../../lib/utils";
import {
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
  Select,
  StatCard,
  Tabs,
  Textarea,
} from "../../components/ui";
import { StatusBadge } from "../../components/accounting/AccountingUI";

type TabKey = "export" | "approvals" | "history" | "stock" | "guide";

const ALL_TYPES: TallyExportTypeKey[] = [
  "sales",
  "purchase",
  "payment",
  "receipt",
  "expense",
  "ledger_masters",
  "stock_masters",
];

const IMPORT_STATUSES: { key: TallyImportStatus; label: string }[] = [
  { key: "not_imported", label: "Not imported" },
  { key: "imported", label: "Imported in Tally" },
  { key: "partially_imported", label: "Partially imported" },
  { key: "failed", label: "Import failed" },
];

function monthStart(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
}

function monthEnd(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().slice(0, 10);
}

function detailMessage(error: unknown): string | null {
  if (error instanceof ApiError && error.payload && typeof error.payload === "object") {
    const detail = (error.payload as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
    if (typeof detail === "string") return detail;
  }
  return null;
}

function validationFrom(error: unknown): TallyValidationReport | null {
  if (error instanceof ApiError && error.payload && typeof error.payload === "object") {
    const detail = (error.payload as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "validation" in detail) {
      return (detail as { validation: TallyValidationReport }).validation;
    }
  }
  return null;
}

function CheckRow({ check }: { check: TallyValidationCheck }) {
  const passed = check.status === "passed";
  return (
    <li className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
      {passed ? (
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" aria-hidden />
      ) : (
        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-500" aria-hidden />
      )}
      <div className="min-w-0">
        <p className="text-[12px] font-semibold text-ink-900">{check.label}</p>
        <p className="text-[11px] leading-relaxed text-slate-500">{check.detail}</p>
      </div>
      <span
        className={`ml-auto shrink-0 text-[10px] font-semibold uppercase tracking-wide ${
          passed ? "text-emerald-600" : "text-rose-600"
        }`}
      >
        {passed ? "Passed" : "Failed"}
      </span>
    </li>
  );
}

function IssueList({
  title,
  tone,
  issues,
}: {
  title: string;
  tone: "error" | "warning";
  issues: TallyValidationIssue[];
}) {
  if (issues.length === 0) return null;
  const styles =
    tone === "error"
      ? "border-rose-200 bg-rose-50/50 text-rose-900"
      : "border-amber-200 bg-amber-50/50 text-amber-900";
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        {title} · {issues.length}
      </p>
      <ul className="space-y-1.5">
        {issues.map((issue, index) => (
          <li key={`${issue.code}-${index}`} className={`rounded-lg border px-3 py-2 text-[12px] ${styles}`}>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded bg-white/70 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
                {issue.code}
              </span>
              {issue.voucher_number && (
                <span className="text-[10px] font-medium opacity-80">
                  {issue.voucher_type ? `${labelize(issue.voucher_type)} ` : ""}
                  {issue.voucher_number}
                  {issue.voucher_date ? ` · ${formatDate(issue.voucher_date)}` : ""}
                </span>
              )}
            </div>
            <p className="mt-1 leading-relaxed">{issue.message}</p>
            {(issue.expected || issue.stored) && (
              <p className="mt-0.5 text-[11px] opacity-80">
                {issue.stored ? `Recorded: ${issue.stored}` : ""}
                {issue.expected ? ` · Expected: ${issue.expected}` : ""}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ValidationPanel({ report }: { report: TallyValidationReport }) {
  const [showWarnings, setShowWarnings] = useState(false);
  return (
    <div className="space-y-4">
      <Callout
        tone={report.ok ? "green" : "red"}
        icon={report.ok ? CheckCircle2 : AlertTriangle}
        title={report.ok ? "Validation passed" : "Validation failed — fix the errors before export"}
      >
        {report.ok
          ? "The recorded vouchers and masters balance. A senior accountant must still approve the batch before it can be downloaded."
          : `${report.error_count} error(s) must be corrected in the source vouchers or masters. The export is blocked and no accounting figure was changed.`}
      </Callout>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Vouchers" value={report.summary.voucher_count} tone="blue" />
        <StatCard label="Double entries" value={report.summary.entry_count} tone="violet" />
        <StatCard label="Debit total" value={money(report.summary.debit_total)} tone="amber" />
        <StatCard
          label={report.summary.balanced ? "Credit total · balanced" : "Credit total · mismatch"}
          value={money(report.summary.credit_total)}
          tone={report.summary.balanced ? "green" : "red"}
        />
      </div>

      <p className="text-[11px] text-slate-500">
        {report.summary.ledger_count} ledger master(s) · {report.summary.stock_item_count} stock item(s) · period{" "}
        {report.period.from ? formatDate(report.period.from) : "start"} to{" "}
        {report.period.to ? formatDate(report.period.to) : "today"} · checked {formatDateTime(report.checked_at)}
      </p>

      {report.summary.by_type.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[640px] border-collapse">
            <thead className="bg-slate-50">
              <tr>
                <th className="table-head">Data type</th>
                <th className="table-head">Vouchers</th>
                <th className="table-head">Taxable value</th>
                <th className="table-head">CGST</th>
                <th className="table-head">SGST</th>
                <th className="table-head">IGST</th>
                <th className="table-head">Debit</th>
                <th className="table-head">Credit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {report.summary.by_type.map((row) => (
                <tr key={row.export_type}>
                  <td className="table-cell text-[12px] font-semibold text-ink-900">{row.label}</td>
                  <td className="table-cell tabular text-[11px]">{row.voucher_count}</td>
                  <td className="table-cell tabular text-[11px]">{money(row.taxable_value)}</td>
                  <td className="table-cell tabular text-[11px]">{money(row.cgst)}</td>
                  <td className="table-cell tabular text-[11px]">{money(row.sgst)}</td>
                  <td className="table-cell tabular text-[11px]">{money(row.igst)}</td>
                  <td className="table-cell tabular text-[11px]">{money(row.debit_total)}</td>
                  <td className="table-cell tabular text-[11px]">{money(row.credit_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          Validation checks
        </p>
        <ul className="space-y-1.5">
          {report.checks.map((check) => (
            <CheckRow key={check.key} check={check} />
          ))}
        </ul>
      </div>

      <IssueList title="Errors blocking export" tone="error" issues={report.errors} />

      {report.warnings.length > 0 && (
        <div>
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Warnings · {report.warnings.length}
            </p>
            <button
              type="button"
              onClick={() => setShowWarnings((value) => !value)}
              className="text-[11px] font-semibold text-brand-600 hover:underline"
            >
              {showWarnings ? "Hide warnings" : "Show warnings"}
            </button>
          </div>
          {showWarnings && (
            <div className="mt-1.5">
              <IssueList title="Review before importing" tone="warning" issues={report.warnings} />
            </div>
          )}
        </div>
      )}

      <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500">
        {report.note}
      </p>
    </div>
  );
}

interface StockForm {
  name: string;
  sku: string;
  unit: string;
  hsn_sac: string;
  gst_rate: string;
  opening_qty: string;
  opening_rate: string;
}

const emptyStockForm: StockForm = {
  name: "",
  sku: "",
  unit: "Nos",
  hsn_sac: "",
  gst_rate: "18",
  opening_qty: "0",
  opening_rate: "0",
};

export function TallyIntegrationPage() {
  const { user, isSeniorAccountant } = useAuth();
  const requestedClientId = Number(new URLSearchParams(window.location.search).get("clientId"));
  const [tab, setTab] = useState<TabKey>("export");

  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [clientId, setClientId] = useState<number | null>(
    Number.isFinite(requestedClientId) && requestedClientId > 0 ? requestedClientId : null,
  );
  const [loadingClients, setLoadingClients] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [catalog, setCatalog] = useState<TallyExportCatalog | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [types, setTypes] = useState<TallyExportTypeKey[]>(ALL_TYPES);
  const [range, setRange] = useState({ from: monthStart(), to: monthEnd() });
  const [format, setFormat] = useState<TallyExportFormat>("xlsx");
  const [tallyVersion, setTallyVersion] = useState("TallyPrime 4.1");
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState<TallyValidationReport | null>(null);
  const [validating, setValidating] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [preparedMessage, setPreparedMessage] = useState<string | null>(null);

  const [history, setHistory] = useState<TallyExportBatch[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyStatus, setHistoryStatus] = useState("");
  const [historyClient, setHistoryClient] = useState<number | null>(null);

  const [pending, setPending] = useState<TallyExportBatch[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [approvalsLoading, setApprovalsLoading] = useState(false);

  const [detail, setDetail] = useState<TallyExportBatch | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [approval, setApproval] = useState<TallyExportBatch | null>(null);
  const [decisionNote, setDecisionNote] = useState("");
  const [deciding, setDeciding] = useState(false);

  const [importTarget, setImportTarget] = useState<TallyExportBatch | null>(null);
  const [importForm, setImportForm] = useState<{ status: TallyImportStatus; note: string }>({
    status: "imported",
    note: "",
  });
  const [savingImport, setSavingImport] = useState(false);

  const [stockClientId, setStockClientId] = useState<number | null>(null);
  const [stockItems, setStockItems] = useState<TallyStockItem[]>([]);
  const [stockLoading, setStockLoading] = useState(false);
  const [stockEditing, setStockEditing] = useState<TallyStockItem | "new" | null>(null);
  const [stockForm, setStockForm] = useState<StockForm>(emptyStockForm);
  const [savingStock, setSavingStock] = useState(false);
  const [stockError, setStockError] = useState<string | null>(null);

  const loadClients = useCallback(async () => {
    setLoadingClients(true);
    setPageError(null);
    try {
      const path = isSeniorAccountant ? "/accounting/senior/clients" : "/accounting/junior/clients";
      const data = await get<{ items: AccountingClient[] }>(path);
      setClients(data.items);
      setClientId((current) =>
        current && data.items.some((row) => row.id === current) ? current : data.items[0]?.id ?? null,
      );
      setStockClientId((current) =>
        current && data.items.some((row) => row.id === current) ? current : data.items[0]?.id ?? null,
      );
    } catch (err) {
      setPageError(getErrorMessage(err));
    } finally {
      setLoadingClients(false);
    }
  }, [isSeniorAccountant]);

  useEffect(() => {
    void loadClients();
  }, [loadClients]);

  const loadCatalog = useCallback(async (id: number) => {
    setCatalogLoading(true);
    try {
      setCatalog(await get<TallyExportCatalog>(`/accounting/tally/catalog?client_id=${id}`));
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  useEffect(() => {
    setValidation(null);
    setPreparedMessage(null);
    if (clientId) void loadCatalog(clientId);
  }, [clientId, loadCatalog]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (historyStatus) params.set("status", historyStatus);
      if (historyClient) params.set("client_id", String(historyClient));
      const data = await get<TallyExportList>(`/accounting/tally/exports?${params.toString()}`);
      setHistory(data.items);
      setPendingCount(data.pending_approval_count);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setHistoryLoading(false);
    }
  }, [historyStatus, historyClient]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const loadPending = useCallback(async () => {
    if (!isSeniorAccountant) return;
    setApprovalsLoading(true);
    try {
      const data = await get<TallyExportList>("/accounting/tally/exports?status=pending_approval&limit=200");
      setPending(data.items);
      setPendingCount(data.pending_approval_count);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setApprovalsLoading(false);
    }
  }, [isSeniorAccountant]);

  useEffect(() => {
    if (tab === "approvals") void loadPending();
  }, [tab, loadPending]);

  const loadStock = useCallback(async () => {
    if (!stockClientId) return;
    setStockLoading(true);
    try {
      const data = await get<{ items: TallyStockItem[] }>(
        `/accounting/tally/stock-items?client_id=${stockClientId}`,
      );
      setStockItems(data.items);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setStockLoading(false);
    }
  }, [stockClientId]);

  useEffect(() => {
    if (tab === "stock") void loadStock();
  }, [tab, loadStock]);

  const requestPayload = useMemo(
    () => ({
      client_id: clientId,
      export_types: types,
      from_date: range.from || null,
      to_date: range.to || null,
      file_format: format,
      tally_version: tallyVersion,
      note: note || null,
    }),
    [clientId, types, range, format, tallyVersion, note],
  );

  const canSubmit = Boolean(clientId) && types.length > 0 && !validating && !preparing;

  const toggleType = (key: TallyExportTypeKey) => {
    setValidation(null);
    setPreparedMessage(null);
    setTypes((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  };

  const validate = async () => {
    if (!canSubmit) return;
    setValidating(true);
    setActionError(null);
    setPreparedMessage(null);
    try {
      setValidation(
        await post<TallyValidationReport>("/accounting/tally/exports/validate", requestPayload),
      );
    } catch (err) {
      setValidation(validationFrom(err));
      setActionError(detailMessage(err) || getErrorMessage(err));
    } finally {
      setValidating(false);
    }
  };

  const prepare = async () => {
    if (!canSubmit) return;
    setPreparing(true);
    setActionError(null);
    setPreparedMessage(null);
    try {
      const batch = await post<TallyExportBatch>("/accounting/tally/exports", requestPayload);
      setValidation(batch.validation || null);
      setPreparedMessage(
        isSeniorAccountant
          ? `Batch #${batch.id} is ${labelize(batch.status)}. Approve it in the approval queue before it can be downloaded.`
          : `Batch #${batch.id} was sent to a senior accountant for approval. It cannot be downloaded until approved.`,
      );
      await loadHistory();
      if (tab === "approvals") await loadPending();
    } catch (err) {
      setValidation(validationFrom(err));
      setActionError(detailMessage(err) || getErrorMessage(err));
    } finally {
      setPreparing(false);
    }
  };

  const openDetail = async (batch: TallyExportBatch) => {
    setDetailLoading(true);
    setActionError(null);
    try {
      setDetail(await get<TallyExportBatch>(`/accounting/tally/exports/${batch.id}`));
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setDetailLoading(false);
    }
  };

  const openApproval = async (batch: TallyExportBatch) => {
    setActionError(null);
    setDecisionNote("");
    try {
      setApproval(await get<TallyExportBatch>(`/accounting/tally/exports/${batch.id}`));
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const decide = async (decision: "approve" | "reject") => {
    if (!approval) return;
    setDeciding(true);
    setActionError(null);
    try {
      await post<TallyExportBatch>(`/accounting/tally/exports/${approval.id}/decision`, {
        decision,
        note: decisionNote || null,
      });
      setApproval(null);
      setDecisionNote("");
      await Promise.all([loadPending(), loadHistory()]);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setDeciding(false);
    }
  };

  const download = async (batch: TallyExportBatch) => {
    setActionError(null);
    try {
      await downloadFile(`/accounting/tally/exports/${batch.id}/download`, batch.filename);
      await loadHistory();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const openImport = (batch: TallyExportBatch) => {
    setActionError(null);
    setImportForm({
      status: batch.import_status === "not_imported" ? "imported" : batch.import_status,
      note: batch.import_note || "",
    });
    setImportTarget(batch);
  };

  const saveImport = async () => {
    if (!importTarget) return;
    setSavingImport(true);
    setActionError(null);
    try {
      await post<TallyExportBatch>(`/accounting/tally/exports/${importTarget.id}/import-status`, {
        import_status: importForm.status,
        note: importForm.note || null,
      });
      setImportTarget(null);
      await loadHistory();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setSavingImport(false);
    }
  };

  const openStock = (item: TallyStockItem | "new") => {
    setStockError(null);
    setStockEditing(item);
    if (item === "new") {
      setStockForm(emptyStockForm);
    } else {
      setStockForm({
        name: item.name,
        sku: item.sku,
        unit: item.unit,
        hsn_sac: item.hsn_sac || "",
        gst_rate: String(item.gst_rate),
        opening_qty: String(item.opening_qty),
        opening_rate: String(item.opening_rate),
      });
    }
  };

  const saveStock = async () => {
    if (!stockEditing || !stockClientId) return;
    setSavingStock(true);
    setStockError(null);
    try {
      if (stockEditing === "new") {
        await post("/accounting/tally/stock-items", {
          client_id: stockClientId,
          name: stockForm.name.trim(),
          sku: stockForm.sku.trim(),
          unit: stockForm.unit.trim() || "Nos",
          hsn_sac: stockForm.hsn_sac.trim() || null,
          gst_rate: Number(stockForm.gst_rate || 0),
          opening_qty: Number(stockForm.opening_qty || 0),
          opening_rate: Number(stockForm.opening_rate || 0),
        });
      } else {
        await patch(`/accounting/tally/stock-items/${stockEditing.id}`, {
          name: stockForm.name.trim(),
          unit: stockForm.unit.trim() || "Nos",
          hsn_sac: stockForm.hsn_sac.trim() || null,
          gst_rate: Number(stockForm.gst_rate || 0),
          opening_qty: Number(stockForm.opening_qty || 0),
          opening_rate: Number(stockForm.opening_rate || 0),
        });
      }
      setStockEditing(null);
      await loadStock();
      if (stockClientId && clientId === stockClientId) void loadCatalog(stockClientId);
    } catch (err) {
      setStockError(getErrorMessage(err));
    } finally {
      setSavingStock(false);
    }
  };

  const deactivateStock = async (item: TallyStockItem) => {
    setActionError(null);
    try {
      await patch(`/accounting/tally/stock-items/${item.id}`, { is_active: false });
      await loadStock();
      if (stockClientId && clientId === stockClientId) void loadCatalog(stockClientId);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  if (loadingClients && clients.length === 0) return <PageSkeleton cards={4} />;
  if (pageError && clients.length === 0) return <ErrorState message={pageError} onRetry={loadClients} />;

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "export", label: "Export centre" },
    ...(isSeniorAccountant
      ? [{ key: "approvals" as TabKey, label: "Approval queue", count: pendingCount }]
      : []),
    { key: "history", label: "Export history", count: history.length },
    { key: "stock", label: "Stock masters" },
    { key: "guide", label: "Tally import guide" },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Tally integration"
        title="Tally export centre"
        description="Build validated Excel/CSV export batches from recorded vouchers, route them through senior approval, and track what was imported into TallyPrime."
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Awaiting approval" value={pendingCount} icon={ClipboardCheck} tone="amber" />
        <StatCard
          label="Approved batches"
          value={history.filter((row) => row.status === "approved").length}
          icon={ShieldCheck}
          tone="green"
        />
        <StatCard
          label="Records exported"
          value={history
            .filter((row) => row.status === "approved")
            .reduce((sum, row) => sum + row.row_count, 0)}
          icon={FileSpreadsheet}
          tone="blue"
        />
        <StatCard
          label="Tally imports recorded"
          value={history.filter((row) => row.import_status === "imported").length}
          icon={Upload}
          tone="violet"
        />
      </div>

      <Tabs items={tabs} value={tab} onChange={setTab} />

      {tab === "export" && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
          <Card className="h-fit">
            <CardHeader
              title="Prepare an export"
              description="Figures are copied exactly as recorded. Validation reports problems; it never edits them."
              icon={FileSpreadsheet}
            />
            <CardBody className="space-y-3">
              <Field label="Client" htmlFor="tally_client" required>
                <Select
                  id="tally_client"
                  value={clientId ?? ""}
                  onChange={(event) => setClientId(event.target.value ? Number(event.target.value) : null)}
                >
                  <option value="">Select a client</option>
                  {clients.map((client) => (
                    <option key={client.id} value={client.id}>
                      {client.business_name} · {client.code}
                    </option>
                  ))}
                </Select>
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="From date" htmlFor="tally_from">
                  <Input
                    id="tally_from"
                    type="date"
                    value={range.from}
                    onChange={(event) => {
                      setValidation(null);
                      setPreparedMessage(null);
                      setRange({ ...range, from: event.target.value });
                    }}
                  />
                </Field>
                <Field label="To date" htmlFor="tally_to">
                  <Input
                    id="tally_to"
                    type="date"
                    value={range.to}
                    onChange={(event) => {
                      setValidation(null);
                      setPreparedMessage(null);
                      setRange({ ...range, to: event.target.value });
                    }}
                  />
                </Field>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="File format" htmlFor="tally_format">
                  <Select
                    id="tally_format"
                    value={format}
                    onChange={(event) => {
                      setValidation(null);
                      setPreparedMessage(null);
                      setFormat(event.target.value as TallyExportFormat);
                    }}
                  >
                    {(catalog?.formats || [
                      { key: "xlsx", label: "Excel workbook (.xlsx)" },
                      { key: "csv_zip", label: "CSV bundle + Tally XML (.zip)" },
                      { key: "xml", label: "Tally XML (.xml)" },
                      { key: "json", label: "Structured JSON (.json, TallyPrime 3.0+)" },
                    ]).map((option) => (
                      <option
                        key={option.key}
                        value={option.key}
                        disabled={
                          option.key === "json" &&
                          !(catalog?.tally_versions.find((item) => item.key === tallyVersion)?.formats ?? []).includes("json")
                        }
                      >
                        {option.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Tally version" htmlFor="tally_version">
                  <Select
                    id="tally_version"
                    value={tallyVersion}
                    onChange={(event) => {
                      setValidation(null);
                      setPreparedMessage(null);
                      setTallyVersion(event.target.value);
                      if (event.target.value === "TallyPrime 2.0" || event.target.value === "Tally ERP 9") {
                        setFormat((current) => (current === "json" ? "xml" : current));
                      }
                    }}
                  >
                    {(catalog?.tally_versions || [
                      { key: "TallyPrime 5.0", formats: [] },
                      { key: "TallyPrime 4.1", formats: [] },
                      { key: "TallyPrime 3.0", formats: [] },
                      { key: "TallyPrime 2.0", formats: [] },
                      { key: "Tally ERP 9", formats: [] },
                    ]).map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.key}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>

              <div>
                <p className="field-label">Data types</p>
                <div className="space-y-2">
                  {ALL_TYPES.map((key) => {
                    const meta = catalog?.types.find((item) => item.key === key);
                    const detail =
                      meta?.kind === "masters"
                        ? key === "stock_masters"
                          ? `${meta.record_count ?? 0} stock item(s)`
                          : "Ledger masters built from recorded vouchers"
                        : `${meta?.record_count ?? 0} voucher(s) in all periods`;
                    return (
                      <label
                        key={key}
                        className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 transition ${
                          types.includes(key)
                            ? "border-brand-300 bg-brand-50/40"
                            : "border-slate-200 bg-white hover:border-slate-300"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={types.includes(key)}
                          onChange={() => toggleType(key)}
                          className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-brand-500"
                        />
                        <span className="min-w-0">
                          <span className="block text-[12px] font-semibold text-ink-900">
                            {meta?.label || labelize(key)}
                          </span>
                          <span className="block text-[10px] text-slate-500">{detail}</span>
                        </span>
                      </label>
                    );
                  })}
                </div>
                {catalogLoading && <p className="mt-1 text-[10px] text-slate-400">Loading counts…</p>}
              </div>

              <Field
                label="Batch note"
                htmlFor="tally_note"
                hint="Stored with the batch for the senior reviewer."
              >
                <Textarea
                  id="tally_note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  className="min-h-[60px]"
                  placeholder="Anything the reviewer should know?"
                />
              </Field>

              <Callout tone="slate" icon={ShieldCheck} title="Approval required">
                {isSeniorAccountant
                  ? "Batches stay locked until you approve them. Self-approval is flagged in the audit trail."
                  : "A senior accountant must approve every batch before any file can be downloaded."}
              </Callout>

              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" loading={validating} onClick={validate} disabled={!canSubmit}>
                  Validate
                </Button>
                <Button loading={preparing} onClick={prepare} disabled={!canSubmit}>
                  Prepare batch
                </Button>
              </div>
              {types.length === 0 && (
                <p className="text-[11px] font-medium text-rose-600">Choose at least one data type.</p>
              )}
            </CardBody>
          </Card>

          <div className="space-y-4">
            {preparedMessage && (
              <Callout tone="green" icon={CheckCircle2} title="Batch prepared">
                {preparedMessage}
              </Callout>
            )}
            <Card>
              <CardHeader
                title="Validation report"
                description="Mandatory fields, ledger mappings, debit-credit balance, GST split, duplicates and party details."
                icon={ClipboardCheck}
                actions={
                  <Button
                    size="sm"
                    variant="outline"
                    icon={RefreshCw}
                    loading={validating}
                    onClick={validate}
                    disabled={!canSubmit}
                  >
                    Run validation
                  </Button>
                }
              />
              <CardBody className="pt-0">
                {validation ? (
                  <ValidationPanel report={validation} />
                ) : (
                  <EmptyState
                    title="No validation run yet"
                    description="Select a client, period and data types, then validate to see every check before preparing the batch."
                    icon={ClipboardCheck}
                  />
                )}
              </CardBody>
            </Card>
          </div>
        </div>
      )}

      {tab === "approvals" && isSeniorAccountant && (
        <Card>
          <CardHeader
            title="Approval queue"
            description="Junior-prepared batches wait here. Review the validation report before approving."
            icon={ClipboardCheck}
            actions={
              <Button size="sm" variant="outline" icon={RefreshCw} loading={approvalsLoading} onClick={loadPending}>
                Refresh
              </Button>
            }
          />
          <CardBody className="pt-0">
            {pending.length === 0 ? (
              <EmptyState
                title="Queue is clear"
                description="No export batches are waiting for senior review."
                icon={ClipboardCheck}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head">Batch</th>
                      <th className="table-head">Client</th>
                      <th className="table-head">Period</th>
                      <th className="table-head">Records</th>
                      <th className="table-head">Prepared by</th>
                      <th className="table-head">Prepared</th>
                      <th className="table-head"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {pending.map((batch) => (
                      <tr key={batch.id} className="row-hover">
                        <td className="table-cell">
                          <p className="text-[12px] font-semibold text-ink-900">
                            #{batch.id} · {batch.filename}
                          </p>
                          <p className="text-[10px] text-slate-500">{batch.type_labels.join(" · ")}</p>
                        </td>
                        <td className="table-cell text-[11px] text-slate-600">{batch.client_name}</td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                          {batch.period_from ? formatDate(batch.period_from) : "Start"} –{" "}
                          {batch.period_to ? formatDate(batch.period_to) : "Today"}
                        </td>
                        <td className="table-cell text-[11px] text-slate-500">
                          {batch.voucher_count} vouchers · {batch.row_count} rows
                        </td>
                        <td className="table-cell text-[11px] text-slate-600">{batch.prepared_by || "—"}</td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                          {formatDate(batch.created_at)}
                        </td>
                        <td className="table-cell">
                          <Button size="sm" variant="outline" icon={Eye} onClick={() => void openApproval(batch)}>
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
      )}

      {tab === "history" && (
        <Card>
          <CardHeader
            title="Export history"
            description="Every batch, who prepared and approved it, its validation result and the recorded Tally import outcome."
            icon={History}
            actions={
              <>
                <Select
                  aria-label="History status"
                  value={historyStatus}
                  onChange={(event) => setHistoryStatus(event.target.value)}
                  className="h-8 min-w-[150px] text-[11px]"
                >
                  <option value="">All statuses</option>
                  {["pending_approval", "approved", "rejected"].map((status) => (
                    <option key={status} value={status}>
                      {labelize(status)}
                    </option>
                  ))}
                </Select>
                <Select
                  aria-label="History client"
                  value={historyClient ?? ""}
                  onChange={(event) =>
                    setHistoryClient(event.target.value ? Number(event.target.value) : null)
                  }
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
            {historyLoading && history.length === 0 ? (
              <div className="space-y-2">
                <div className="h-16 animate-pulse rounded-lg bg-slate-100" />
                <div className="h-16 animate-pulse rounded-lg bg-slate-100" />
              </div>
            ) : history.length === 0 ? (
              <EmptyState
                title="No export batches yet"
                description="Prepare a batch in the export centre. It will appear here with its approval and import status."
                icon={History}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1080px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head">Batch</th>
                      <th className="table-head">Client</th>
                      <th className="table-head">Period</th>
                      <th className="table-head">Format</th>
                      <th className="table-head">Records</th>
                      <th className="table-head">Prepared by</th>
                      <th className="table-head">Approved by</th>
                      <th className="table-head">Export date</th>
                      <th className="table-head">Status</th>
                      <th className="table-head">Import</th>
                      <th className="table-head">Errors</th>
                      <th className="table-head"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {history.map((batch) => (
                      <tr key={batch.id} className="row-hover">
                        <td className="table-cell">
                          <p className="text-[12px] font-semibold text-ink-900">#{batch.id}</p>
                          <p className="max-w-[220px] truncate text-[10px] text-slate-500">{batch.filename}</p>
                        </td>
                        <td className="table-cell text-[11px] text-slate-600">{batch.client_name}</td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                          {batch.period_from ? formatDate(batch.period_from) : "Start"} –{" "}
                          {batch.period_to ? formatDate(batch.period_to) : "Today"}
                        </td>
                        <td className="table-cell text-[11px] text-slate-500">
                          {tallyExportFormatLabel(batch.file_format)}
                          <span className="block text-[10px] text-slate-400">{formatBytes(batch.file_size)}</span>
                        </td>
                        <td className="table-cell text-[11px] text-slate-500">
                          {batch.voucher_count} vouchers
                          <span className="block text-[10px] text-slate-400">
                            {batch.row_count} rows · {batch.master_count} masters
                          </span>
                        </td>
                        <td className="table-cell text-[11px] text-slate-600">{batch.prepared_by || "—"}</td>
                        <td className="table-cell text-[11px] text-slate-600">
                          {batch.approved_by || "—"}
                          {batch.details?.self_approved === true && (
                            <span className="block text-[10px] text-amber-600">Self-approved</span>
                          )}
                        </td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                          {formatDate(batch.created_at)}
                        </td>
                        <td className="table-cell">
                          <StatusBadge status={batch.status} />
                        </td>
                        <td className="table-cell">
                          <StatusBadge status={batch.import_status} />
                        </td>
                        <td className="table-cell text-[11px]">
                          <span className={batch.error_count > 0 ? "font-semibold text-rose-600" : "text-slate-500"}>
                            {batch.error_count}
                          </span>
                          <span className="text-slate-400"> / </span>
                          <span className="text-amber-600">{batch.warning_count}</span>
                        </td>
                        <td className="table-cell">
                          <div className="flex flex-wrap gap-1">
                            <Button size="sm" variant="ghost" icon={Eye} onClick={() => void openDetail(batch)}>
                              View
                            </Button>
                            {batch.status === "approved" && (
                              <>
                                <Button size="sm" variant="outline" icon={Download} onClick={() => void download(batch)}>
                                  Download
                                </Button>
                                <Button size="sm" variant="ghost" icon={Upload} onClick={() => openImport(batch)}>
                                  Import
                                </Button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {tab === "stock" && (
        <Card>
          <CardHeader
            title="Stock item masters"
            description="Opening quantities and GST rates for the Tally stock master export. Rates must be business-verified — they are never guessed."
            icon={Package}
            actions={
              <>
                <Select
                  aria-label="Stock client"
                  value={stockClientId ?? ""}
                  onChange={(event) =>
                    setStockClientId(event.target.value ? Number(event.target.value) : null)
                  }
                  className="h-8 min-w-[180px] text-[11px]"
                >
                  <option value="">Select a client</option>
                  {clients.map((client) => (
                    <option key={client.id} value={client.id}>
                      {client.business_name}
                    </option>
                  ))}
                </Select>
                <Button size="sm" icon={Plus} disabled={!stockClientId} onClick={() => openStock("new")}>
                  Add item
                </Button>
              </>
            }
          />
          <CardBody className="pt-0">
            {!stockClientId ? (
              <EmptyState title="Select a client" description="Stock masters are maintained per client." icon={Package} />
            ) : stockLoading && stockItems.length === 0 ? (
              <div className="h-24 animate-pulse rounded-lg bg-slate-100" />
            ) : stockItems.length === 0 ? (
              <EmptyState
                title="No stock items"
                description="Add the items this client trades in; they are included when Stock item masters is selected for export."
                icon={Package}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head">SKU</th>
                      <th className="table-head">Item</th>
                      <th className="table-head">Unit</th>
                      <th className="table-head">HSN/SAC</th>
                      <th className="table-head">GST rate</th>
                      <th className="table-head">Opening qty</th>
                      <th className="table-head">Opening rate</th>
                      <th className="table-head">Opening value</th>
                      <th className="table-head"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {stockItems.map((item) => (
                      <tr key={item.id} className="row-hover">
                        <td className="table-cell text-[11px] font-semibold text-ink-900">{item.sku}</td>
                        <td className="table-cell text-[12px] text-slate-700">{item.name}</td>
                        <td className="table-cell text-[11px] text-slate-500">{item.unit}</td>
                        <td className="table-cell text-[11px] text-slate-500">
                          {item.hsn_sac || <span className="text-amber-600">Not set</span>}
                        </td>
                        <td className="table-cell tabular text-[11px] text-slate-500">{item.gst_rate}%</td>
                        <td className="table-cell tabular text-[11px] text-slate-500">{item.opening_qty}</td>
                        <td className="table-cell tabular text-[11px] text-slate-500">{money(item.opening_rate)}</td>
                        <td className="table-cell tabular text-[11px] text-slate-600">{money(item.opening_value)}</td>
                        <td className="table-cell">
                          <div className="flex gap-1">
                            <Button size="sm" variant="ghost" icon={Pencil} onClick={() => openStock(item)}>
                              Edit
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => void deactivateStock(item)}>
                              Deactivate
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {tab === "guide" && (
        <div className="space-y-4">
          <Callout tone="amber" icon={AlertTriangle} title="Not a live Tally connection">
            FINOVEXA does not update Tally by itself. It generates validated Excel/CSV/XML files that you import into
            TallyPrime yourself. No voucher is posted to Tally automatically, and no claim of a two-way sync is made.
          </Callout>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Import into TallyPrime" icon={BookOpen} />
              <CardBody className="pt-0">
                <ol className="list-decimal space-y-3 pl-5 text-[12px] leading-relaxed text-slate-600">
                  <li>
                    <span className="font-semibold text-ink-900">Get the batch approved.</span> A senior accountant
                    approves it, then download the .xlsx workbook or the .zip bundle from Export history.
                  </li>
                  <li>
                    <span className="font-semibold text-ink-900">Import masters first.</span> In TallyPrime open the
                    target company and use Gateway of Tally → Import Data → Masters. Choose{" "}
                    <code className="rounded bg-slate-100 px-1">tally-master-import.xml</code> from the zip and import
                    All Masters. This creates the party, sales, purchase, expense, bank and tax ledgers plus stock items.
                  </li>
                  <li>
                    <span className="font-semibold text-ink-900">Import vouchers next.</span> Use Import Data →
                    Vouchers with <code className="rounded bg-slate-100 px-1">tally-voucher-import.xml</code>. Import
                    sales, purchases, payments and receipts before reconciling the period.
                  </li>
                  <li>
                    <span className="font-semibold text-ink-900">Excel / CSV route.</span> The workbook has one
                    worksheet per data type and a Voucher Entries sheet with debit/credit lines. Map these columns in
                    Tally's Excel import, or use the CSV bundle where each file carries the same columns.
                  </li>
                  <li>
                    <span className="font-semibold text-ink-900">Reconcile before posting.</span> Compare the Summary
                    and Validation sheets with the batch totals. Debit and credit must match, and every failed check
                    must be cleared.
                  </li>
                  <li>
                    <span className="font-semibold text-ink-900">Record the outcome.</span> Back in Export history,
                    use Import to record imported / partially imported / failed with a note, so the practice has an
                    audit record of what reached Tally.
                  </li>
                </ol>
              </CardBody>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader title="Mapping notes" icon={FileSpreadsheet} />
                <CardBody className="space-y-2 pt-0 text-[12px] leading-relaxed text-slate-600">
                  <p>
                    <span className="font-semibold text-ink-900">Ledger groups:</span> parties go to Sundry Debtors or
                    Sundry Creditors, sales and purchases to their trading groups, expenses to Indirect Expenses, and
                    GST to Duties &amp; Taxes.
                  </p>
                  <p>
                    <span className="font-semibold text-ink-900">Payment account:</span> payment, receipt and expense
                    vouchers use the recorded bank/cash ledger. If none was recorded, the export warns and falls back
                    to the voucher ledger or Cash — check these before importing.
                  </p>
                  <p>
                    <span className="font-semibold text-ink-900">GST:</span> output and input tax are split into CGST,
                    SGST and IGST exactly as recorded. The export does not recalculate or alter GST amounts.
                  </p>
                  <p>
                    <span className="font-semibold text-ink-900">Stock items:</span> set each item's GST rate and HSN
                    in Tally from the Stock Item Masters sheet. FINOVEXA exports what is on file and never invents a
                    classification.
                  </p>
                </CardBody>
              </Card>

              <Callout tone="blue" icon={ShieldCheck} title="Security and audit">
                Downloads are limited to the accountants assigned to the client, blocked until senior approval, served
                with no-store headers, and every validation, approval, download and import-status change is written to
                the practice audit trail.
              </Callout>
            </div>
          </div>
        </div>
      )}

      <Modal
        open={Boolean(detail) || detailLoading}
        onClose={() => setDetail(null)}
        title={detail ? `Batch #${detail.id} · ${detail.filename}` : "Loading batch"}
        description={
          detail
            ? `${detail.client_name} · ${detail.type_labels.join(", ")} · ${tallyExportFormatLabel(detail.file_format)}`
            : undefined
        }
        size="xl"
        footer={
          detail ? (
            <>
              <Button variant="outline" onClick={() => setDetail(null)}>
                Close
              </Button>
              {detail.status === "approved" && (
                <>
                  <Button variant="outline" icon={Upload} onClick={() => openImport(detail)}>
                    Record import
                  </Button>
                  <Button icon={Download} onClick={() => void download(detail)}>
                    Download
                  </Button>
                </>
              )}
            </>
          ) : undefined
        }
      >
        {detail ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Batch status" value={labelize(detail.status)} tone="blue" />
              <StatCard label="Prepared by" value={detail.prepared_by || "—"} tone="slate" />
              <StatCard label="Approved by" value={detail.approved_by || "—"} tone="green" />
              <StatCard label="Tally import" value={labelize(detail.import_status)} tone="violet" />
            </div>

            <p className="text-[11px] text-slate-500">
              {detail.voucher_count} vouchers · {detail.row_count} rows · {detail.master_count} masters ·{" "}
              {formatBytes(detail.file_size)}
              {detail.tally_version ? ` · ${detail.tally_version}` : ""}
              {detail.file_sha256 ? ` · SHA-256 ${detail.file_sha256.slice(0, 16)}…` : ""}
            </p>

            {detail.approval_note && (
              <Callout tone={detail.status === "rejected" ? "red" : "amber"} title="Review note">
                {detail.approval_note}
              </Callout>
            )}
            {detail.import_note && (
              <Callout tone="slate" title="Import note">
                {detail.import_note}
              </Callout>
            )}

            {detail.validation && detail.validation.checks ? (
              <ValidationPanel report={detail.validation} />
            ) : (
              <p className="text-[12px] text-slate-500">No validation snapshot is stored for this batch.</p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            <div className="h-24 animate-pulse rounded-lg bg-slate-100" />
            <div className="h-24 animate-pulse rounded-lg bg-slate-100" />
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(approval)}
        onClose={() => setApproval(null)}
        title={approval ? `Review batch #${approval.id}` : "Review batch"}
        description={
          approval
            ? `${approval.client_name} · prepared by ${approval.prepared_by || "—"} · ${approval.voucher_count} vouchers`
            : undefined
        }
        size="xl"
        footer={
          approval ? (
            <>
              <Button variant="outline" onClick={() => setApproval(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                loading={deciding}
                disabled={!decisionNote.trim()}
                onClick={() => void decide("reject")}
              >
                Reject batch
              </Button>
              <Button
                icon={CheckCircle2}
                loading={deciding}
                onClick={() => void decide("approve")}
                disabled={approval.validation ? !approval.validation.ok : false}
              >
                Approve export
              </Button>
            </>
          ) : undefined
        }
      >
        {approval ? (
          <div className="space-y-4">
            {approval.prepared_by_user_id === user?.id && (
              <Callout tone="amber" title="Prepared by you">
                Approving your own batch is allowed, but it is flagged as self-approved in the audit trail.
              </Callout>
            )}
            {approval.validation && approval.validation.checks ? (
              <ValidationPanel report={approval.validation} />
            ) : (
              <p className="text-[12px] text-slate-500">No validation snapshot is available.</p>
            )}
            <Field
              label="Decision note"
              htmlFor="tally_decision_note"
              hint="Required when rejecting; stored with the batch either way."
            >
              <Textarea
                id="tally_decision_note"
                value={decisionNote}
                onChange={(event) => setDecisionNote(event.target.value)}
                placeholder="What should the preparer know?"
              />
            </Field>
          </div>
        ) : (
          <div className="h-24 animate-pulse rounded-lg bg-slate-100" />
        )}
      </Modal>

      <Modal
        open={Boolean(importTarget)}
        onClose={() => setImportTarget(null)}
        title="Record Tally import result"
        description={
          importTarget
            ? `${importTarget.filename} · approved by ${importTarget.approved_by || "—"}`
            : undefined
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setImportTarget(null)}>
              Cancel
            </Button>
            <Button loading={savingImport} onClick={saveImport}>
              Save status
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Callout tone="amber" icon={AlertTriangle} title="Record what Tally actually did">
            This records the result of your manual TallyPrime import. It does not send anything to Tally.
          </Callout>
          <Field label="Import status" htmlFor="tally_import_status" required>
            <Select
              id="tally_import_status"
              value={importForm.status}
              onChange={(event) =>
                setImportForm({ ...importForm, status: event.target.value as TallyImportStatus })
              }
            >
              {IMPORT_STATUSES.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Import note / error report" htmlFor="tally_import_note">
            <Textarea
              id="tally_import_note"
              value={importForm.note}
              onChange={(event) => setImportForm({ ...importForm, note: event.target.value })}
              placeholder="Rows rejected by Tally, mismatches, or anything the reviewer should see."
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(stockEditing)}
        onClose={() => setStockEditing(null)}
        title={stockEditing === "new" ? "Add stock item" : "Edit stock item"}
        description="Item masters feed the Tally stock master export."
        footer={
          <>
            <Button variant="outline" onClick={() => setStockEditing(null)}>
              Cancel
            </Button>
            <Button
              loading={savingStock}
              onClick={saveStock}
              disabled={stockForm.name.trim().length < 2 || (stockEditing === "new" && !stockForm.sku.trim())}
            >
              {stockEditing === "new" ? "Add item" : "Save changes"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {stockError && (
            <Callout tone="red" title="Could not save the stock item">
              {stockError}
            </Callout>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Item name" htmlFor="stock_name" required>
              <Input
                id="stock_name"
                value={stockForm.name}
                onChange={(event) => setStockForm({ ...stockForm, name: event.target.value })}
                placeholder="Ergo Chair"
              />
            </Field>
            <Field label="SKU" htmlFor="stock_sku" required>
              <Input
                id="stock_sku"
                value={stockForm.sku}
                onChange={(event) => setStockForm({ ...stockForm, sku: event.target.value.toUpperCase() })}
                disabled={stockEditing !== "new"}
                placeholder="FP-EC-02"
              />
            </Field>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Unit" htmlFor="stock_unit">
              <Input
                id="stock_unit"
                value={stockForm.unit}
                onChange={(event) => setStockForm({ ...stockForm, unit: event.target.value })}
              />
            </Field>
            <Field label="HSN / SAC" htmlFor="stock_hsn">
              <Input
                id="stock_hsn"
                value={stockForm.hsn_sac}
                maxLength={12}
                onChange={(event) => setStockForm({ ...stockForm, hsn_sac: event.target.value })}
                placeholder="9403"
              />
            </Field>
            <Field label="GST rate %" htmlFor="stock_gst">
              <Input
                id="stock_gst"
                type="number"
                min="0"
                max="28"
                step="0.01"
                value={stockForm.gst_rate}
                onChange={(event) => setStockForm({ ...stockForm, gst_rate: event.target.value })}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Opening quantity" htmlFor="stock_qty">
              <Input
                id="stock_qty"
                type="number"
                min="0"
                step="0.001"
                value={stockForm.opening_qty}
                onChange={(event) => setStockForm({ ...stockForm, opening_qty: event.target.value })}
              />
            </Field>
            <Field label="Opening rate" htmlFor="stock_rate">
              <Input
                id="stock_rate"
                type="number"
                min="0"
                step="0.01"
                value={stockForm.opening_rate}
                onChange={(event) => setStockForm({ ...stockForm, opening_rate: event.target.value })}
              />
            </Field>
          </div>
          <p className="text-[11px] leading-relaxed text-slate-500">
            GST rates and HSN codes must be business-verified. FINOVEXA exports exactly what is entered here and never
            fills them in automatically.
          </p>
        </div>
      </Modal>
    </div>
  );
}