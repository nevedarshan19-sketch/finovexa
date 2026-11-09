import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeftRight,
  ArrowRight,
  BadgeCheck,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileText,
  History,
  Layers,
  LineChart,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  Upload,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import {
  api,
  downloadFile,
  get,
  getErrorMessage,
  post,
} from "../../lib/api";
import type {
  AccountingClient,
  TallyComparisonRow,
  TallyHistoricalReport,
  TallyLedgerHistory,
  TallyMappingTemplate,
  TallyMigrationBatch,
  TallyMigrationBatchList,
  TallyMigrationCatalog,
  TallyMigrationFormat,
  TallyMigrationPreview,
  TallyMigrationValidation,
  TallyOpeningBalance,
} from "../../lib/accountingTypes";
import { fileToDataUrl, formatBytes, labelize } from "../../lib/accounting";
import { formatDate, formatDateTime, money } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
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
} from "../../components/ui";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

type TabKey = "import" | "reports" | "opening" | "approvals" | "history" | "mappings";

const FORMAT_LABELS: Record<TallyMigrationFormat, string> = {
  xlsx: "Excel (.xlsx)",
  xls: "Legacy Excel (.xls)",
  csv: "CSV (.csv)",
  xml: "Tally XML (.xml)",
  json: "JSON (TallyPrime 3.0+)",
};

const STATUS_TONE: Record<
  string,
  "slate" | "blue" | "green" | "amber" | "red" | "violet" | "cyan"
> = {
  validated: "blue",
  pending_approval: "amber",
  approved: "violet",
  rejected: "red",
  imported: "green",
  partially_imported: "amber",
  failed: "red",
  rolled_back: "slate",
};

const RECORD_STATUS_TONE: Record<string, "slate" | "blue" | "green" | "amber" | "red"> = {
  valid: "green",
  warning: "amber",
  error: "red",
  duplicate: "slate",
};

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function currentFinancialYear(): string {
  const now = new Date();
  const year = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return `${year}-${String((year + 1) % 100).padStart(2, "0")}`;
}

function financialYearStart(financialYear: string): string {
  return `${financialYear.slice(0, 4)}-04-01`;
}

function formatFromFilename(name: string): TallyMigrationFormat | null {
  const extension = name.split(".").pop()?.toLowerCase();
  if (extension === "xlsx" || extension === "xls" || extension === "csv" || extension === "xml" || extension === "json") {
    return extension;
  }
  return null;
}

const MIGRATION_FORMAT_LABELS: Record<string, string> = {
  xlsx: "Excel (.xlsx)",
  xls: "Excel (.xls)",
  csv: "CSV",
  xml: "Tally XML",
  json: "JSON",
};

function migrationFormatLabel(format: string): string {
  return MIGRATION_FORMAT_LABELS[format] || labelize(format);
}

function issueTone(severity: string): "red" | "amber" | "slate" {
  if (severity === "error") return "red";
  if (severity === "warning") return "amber";
  return "slate";
}

function useClients() {
  const { isSeniorAccountant } = useAuth();
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [clientId, setClientId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const path = isSeniorAccountant ? "/accounting/senior/clients" : "/accounting/junior/clients";
    get<{ items: AccountingClient[] }>(path)
      .then((data) => {
        if (cancelled) return;
        setClients(data.items);
        setClientId((current) => current ?? data.items[0]?.id ?? null);
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [isSeniorAccountant]);

  return { clients, clientId, setClientId, loading, error };
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={STATUS_TONE[status] || "slate"} dot>
      {labelize(status)}
    </Badge>
  );
}

function ClientSelect({
  clients,
  value,
  onChange,
  id,
}: {
  clients: AccountingClient[];
  value: number | null;
  onChange: (value: number) => void;
  id: string;
}) {
  return (
    <Field label="Client / business" htmlFor={id} required>
      <Select
        id={id}
        value={value ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {clients.length === 0 && <option value="">No clients available</option>}
        {clients.map((client) => (
          <option key={client.id} value={client.id}>
            {client.business_name}
          </option>
        ))}
      </Select>
    </Field>
  );
}

function ValidationSummary({ validation }: { validation: TallyMigrationValidation }) {
  const [showAllIssues, setShowAllIssues] = useState(false);
  const allIssues = validation.issues ?? [];
  const checks = validation.checks ?? [];
  const totals: Partial<NonNullable<TallyMigrationValidation["totals"]>> = validation.totals ?? {};
  const missingLedgers = validation.missing_ledgers ?? [];
  const unmatchedParties = validation.unmatched_parties ?? [];
  const issues = showAllIssues ? allIssues : allIssues.slice(0, 12);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label="Detected" value={validation.counts.detected} tone="slate" />
        <StatCard label="Valid" value={validation.counts.valid} tone="green" />
        <StatCard label="Warnings" value={validation.counts.warnings} tone="amber" />
        <StatCard label="Errors" value={validation.counts.errors} tone="red" />
        <StatCard label="Duplicates" value={validation.counts.duplicates} tone="violet" />
      </div>

      {checks.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {checks.map((check) => (
            <div
              key={check.code}
              className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-[12px] ${
                check.status === "passed"
                  ? "border-emerald-100 bg-emerald-50/50 text-emerald-900"
                  : "border-rose-100 bg-rose-50/50 text-rose-900"
              }`}
            >
              {check.status === "passed" ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              )}
              <div className="min-w-0">
                <p className="font-semibold">{check.label}</p>
                <p className="text-[11px] opacity-80">{check.detail}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {Object.keys(totals).length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Mapped debit</p>
            <p className="text-sm font-semibold text-ink-900">{money(totals.debit)}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Mapped credit</p>
            <p className="text-sm font-semibold text-ink-900">{money(totals.credit)}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Difference</p>
            <p className="text-sm font-semibold text-ink-900">{money(totals.difference)}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Opening Dr / Cr</p>
            <p className="text-sm font-semibold text-ink-900">
              {money(totals.opening_debit)} / {money(totals.opening_credit)}
            </p>
          </div>
        </div>
      )}

      {(missingLedgers.length > 0 || unmatchedParties.length > 0) && (
        <div className="grid gap-3 sm:grid-cols-2">
          {missingLedgers.length > 0 && (
            <Callout tone="amber" title={`${missingLedgers.length} missing ledger(s)`}>
              These will be created under Suspense Account for review:{" "}
              {missingLedgers.slice(0, 10).join(", ")}
              {missingLedgers.length > 10 ? "…" : ""}
            </Callout>
          )}
          {unmatchedParties.length > 0 && (
            <Callout tone="amber" title={`${unmatchedParties.length} unmatched party name(s)`}>
              {unmatchedParties.slice(0, 10).join(", ")}
              {unmatchedParties.length > 10 ? "…" : ""}
            </Callout>
          )}
        </div>
      )}

      {allIssues.length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-[12px] font-semibold text-slate-700">
              Issues ({allIssues.length})
            </p>
            {allIssues.length > 12 && (
              <Button size="sm" variant="ghost" onClick={() => setShowAllIssues((value) => !value)}>
                {showAllIssues ? "Show fewer" : "Show all"}
              </Button>
            )}
          </div>
          <div className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {issues.map((issue, index) => (
              <div
                key={`${issue.code}-${issue.row}-${index}`}
                className={`rounded-lg border px-3 py-2 text-[12px] ${
                  issueTone(issue.severity) === "red"
                    ? "border-rose-100 bg-rose-50/50"
                    : issueTone(issue.severity) === "amber"
                      ? "border-amber-100 bg-amber-50/50"
                      : "border-slate-200 bg-slate-50"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={issue.severity === "error" ? "red" : issue.severity === "warning" ? "amber" : "slate"}>
                    {labelize(issue.severity)}
                  </Badge>
                  <span className="font-semibold text-slate-700">
                    {issue.row > 0 ? `Row ${issue.row}` : "Batch"}
                  </span>
                  <span className="text-slate-400">{labelize(issue.code)}</span>
                  {issue.voucher_number && (
                    <span className="text-slate-400">· {issue.voucher_number}</span>
                  )}
                </div>
                <p className="mt-1 text-slate-600">{issue.message}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <Callout tone="slate" title="Values are never altered">
        {validation.note ||
          "Imported values are posted exactly as supplied. Nothing is silently discarded, altered or overwritten."}
      </Callout>
    </div>
  );
}

function BatchDetailBody({ batch }: { batch: TallyMigrationBatch }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Status" value={labelize(batch.status)} tone="blue" />
        <StatCard label="Rows imported" value={batch.imported_count} tone="green" />
        <StatCard label="Financial year" value={batch.financial_year} tone="violet" />
        <StatCard label="Format" value={migrationFormatLabel(batch.file_format)} tone="slate" />
      </div>

      <p className="text-[11px] leading-relaxed text-slate-500">
        {batch.client_name} · {batch.import_type_label || labelize(batch.import_type)} · {batch.tally_version || "Version not recorded"} ·{" "}
        {batch.row_count} row(s) · {batch.valid_count} valid · {batch.warning_count} warning ·{" "}
        {batch.error_count} error · {batch.duplicate_count} duplicate · {formatBytes(batch.file_size)}
        {batch.file_sha256 ? ` · SHA-256 ${batch.file_sha256.slice(0, 16)}…` : ""}
      </p>

      <p className="text-[11px] text-slate-500">
        Prepared by {batch.prepared_by || "—"} · approved by {batch.approved_by || "Not approved"} ·{" "}
        created {formatDateTime(batch.created_at)}
        {batch.retained_until ? ` · original retained until ${formatDate(batch.retained_until)}` : ""}
      </p>

      {batch.approval_note && (
        <Callout tone={batch.status === "rejected" ? "red" : "slate"} title="Review note">
          {batch.approval_note}
        </Callout>
      )}

      {batch.validation ? (
        <ValidationSummary validation={batch.validation} />
      ) : (
        <Callout tone="slate">No validation snapshot is stored for this batch.</Callout>
      )}

      {batch.rows && batch.rows.length > 0 && (
        <div>
          <p className="mb-2 text-[12px] font-semibold text-slate-700">
            Mapped rows (first {batch.rows.length})
          </p>
          <TableWrap>
            <THead>
              <TR>
                <TH>Row</TH>
                <TH>Type</TH>
                <TH>Status</TH>
                <TH>Problems</TH>
              </TR>
            </THead>
            <TBody>
              {batch.rows.slice(0, 100).map((row) => (
                <TR key={row.id}>
                  <TD>{row.row_number}</TD>
                  <TD>{labelize(row.record_type)}</TD>
                  <TD>
                    <Badge tone={RECORD_STATUS_TONE[row.status] || "slate"}>{labelize(row.status)}</Badge>
                  </TD>
                  <TD>
                    {row.problems.length === 0 ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <span className="text-slate-600">{row.problems[0].message}</span>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </TableWrap>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- import tab */

function ImportTab({
  clients,
  clientId,
  onClientChange,
  catalog,
  templates,
  onTemplateSaved,
  onGoToApprovals,
  onGoToOpening,
}: {
  clients: AccountingClient[];
  clientId: number | null;
  onClientChange: (value: number) => void;
  catalog: TallyMigrationCatalog | null;
  templates: TallyMappingTemplate[];
  onTemplateSaved: () => void;
  onGoToApprovals: () => void;
  onGoToOpening: () => void;
}) {
  const { isSeniorAccountant } = useAuth();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dataUrl, setDataUrl] = useState<string>("");
  const [format, setFormat] = useState<TallyMigrationFormat>("xlsx");
  const [tallyVersion, setTallyVersion] = useState("TallyPrime 4.1");
  const [financialYear, setFinancialYear] = useState(currentFinancialYear());
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [openingDate, setOpeningDate] = useState(financialYearStart(currentFinancialYear()));
  const [importType, setImportType] = useState("complete");
  const [note, setNote] = useState("");
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [preview, setPreview] = useState<TallyMigrationPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [previewing, setPreviewing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [batch, setBatch] = useState<TallyMigrationBatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState("");
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  const versionFormats = useMemo(() => {
    const version = catalog?.versions.find((item) => item.key === tallyVersion);
    return version?.formats || ["xlsx", "xls", "csv", "xml", "json"];
  }, [catalog, tallyVersion]);

  useEffect(() => {
    if (versionFormats.length > 0 && !versionFormats.includes(format)) {
      setFormat(versionFormats[0] as TallyMigrationFormat);
    }
  }, [format, versionFormats]);

  const mappingFields = preview?.mapping_fields || catalog?.mapping_fields || [];

  const pickFile = async (selected: File | null) => {
    setError(null);
    setPreview(null);
    setBatch(null);
    setSavedNotice(null);
    setFile(selected);
    setDataUrl("");
    if (!selected) return;
    if (selected.size > MAX_UPLOAD_BYTES) {
      setError(`Files are limited to ${formatBytes(MAX_UPLOAD_BYTES)}. Split the export and try again.`);
      return;
    }
    const detected = formatFromFilename(selected.name);
    if (!detected) {
      setError("Choose a .xlsx, .xls, .csv, .xml or .json Tally export.");
      return;
    }
    setFormat(detected);
    try {
      const url = await fileToDataUrl(selected);
      setDataUrl(url);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const runPreview = async () => {
    if (!file || !dataUrl) return;
    setPreviewing(true);
    setError(null);
    setBatch(null);
    try {
      const result = await post<TallyMigrationPreview>("/accounting/tally-migration/preview", {
        file_format: format,
        filename: file.name,
        data_url: dataUrl,
      });
      setPreview(result);
      setMapping(result.suggested_mapping || {});
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setPreviewing(false);
    }
  };

  const applyTemplate = (id: number | null) => {
    setTemplateId(id);
    if (id === null) return;
    const template = templates.find((item) => item.id === id);
    if (template) {
      setMapping(template.mapping);
      setFormat(template.file_format);
      setImportType(template.import_type);
    }
  };

  const createBatch = async () => {
    if (!file || !dataUrl || !clientId) return;
    setCreating(true);
    setError(null);
    setSavedNotice(null);
    try {
      const cleaned = Object.fromEntries(
        Object.entries(mapping).filter(([, column]) => column.trim().length > 0),
      );
      const result = await post<TallyMigrationBatch>("/accounting/tally-migration/batches", {
        client_id: clientId,
        tally_version: tallyVersion,
        financial_year: financialYear,
        period_from: periodFrom || null,
        period_to: periodTo || null,
        opening_date: importType === "opening_balances" ? openingDate : null,
        import_type: importType,
        file_format: format,
        filename: file.name,
        data_url: dataUrl,
        mapping: Object.keys(cleaned).length > 0 ? cleaned : null,
        mapping_template_id: templateId,
        note: note || null,
      });
      setBatch(result);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  const submitBatch = async () => {
    if (!batch) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await post<TallyMigrationBatch>(
        `/accounting/tally-migration/batches/${batch.id}/submit`,
      );
      setBatch(result);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const saveTemplate = async () => {
    if (!templateName.trim() || Object.keys(mapping).length === 0) return;
    setSavingTemplate(true);
    setError(null);
    try {
      await post<TallyMappingTemplate>("/accounting/tally-migration/mappings", {
        name: templateName.trim(),
        client_id: clientId,
        file_format: format,
        import_type: importType,
        mapping,
        is_shared: true,
      });
      setTemplateName("");
      setSavedNotice("Mapping template saved for this client and format.");
      onTemplateSaved();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSavingTemplate(false);
    }
  };

  const downloadErrorReport = async (id: number) => {
    try {
      await downloadFile(
        `/accounting/tally-migration/batches/${id}/error-report`,
        `tally-import-${id}-error-report.csv`,
      );
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const mappedCount = Object.values(mapping).filter((value) => value.trim()).length;
  const canSubmit = Boolean(clientId && file && dataUrl && financialYear);
  const validation = batch?.validation;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
      <Card>
        <CardHeader
          title="Import Tally historical data"
          description="Upload an Excel, CSV, XML or JSON export. Nothing is posted until a senior accountant approves it."
        />
        <CardBody className="space-y-3">
          <ClientSelect clients={clients} value={clientId} onChange={onClientChange} id="migration_client" />

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Tally version" htmlFor="migration_version">
              <Select
                id="migration_version"
                value={tallyVersion}
                onChange={(event) => setTallyVersion(event.target.value)}
              >
                {(catalog?.versions || [
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
            <Field label="Financial year" htmlFor="migration_fy" hint="April to March, e.g. 2024-25.">
              <Input
                id="migration_fy"
                value={financialYear}
                onChange={(event) => setFinancialYear(event.target.value)}
                placeholder="2024-25"
              />
            </Field>
          </div>

          <Field label="Import type" htmlFor="migration_type">
            <Select
              id="migration_type"
              value={importType}
              onChange={(event) => setImportType(event.target.value)}
            >
              {(catalog?.import_types || [{ key: "complete", label: "Complete historical data" }]).map(
                (option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ),
              )}
            </Select>
          </Field>

          {importType === "opening_balances" && (
            <div className="space-y-2 rounded-lg border border-violet-200 bg-violet-50/50 px-3 py-2">
              <Field label="Opening date" htmlFor="migration_opening_date">
                <Input
                  id="migration_opening_date"
                  type="date"
                  value={openingDate}
                  onChange={(event) => setOpeningDate(event.target.value)}
                />
              </Field>
              <p className="text-[11px] leading-relaxed text-violet-900">
                Opening balances must balance (debit = credit). They cannot be imported for a year that
                already has posted history, and a second opening balance is blocked to prevent double
                counting.{" "}
                <button
                  type="button"
                  className="font-semibold underline"
                  onClick={onGoToOpening}
                >
                  Enter manually instead
                </button>
                .
              </p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Period from" htmlFor="migration_from">
              <Input
                id="migration_from"
                type="date"
                value={periodFrom}
                onChange={(event) => setPeriodFrom(event.target.value)}
              />
            </Field>
            <Field label="Period to" htmlFor="migration_to">
              <Input
                id="migration_to"
                type="date"
                value={periodTo}
                onChange={(event) => setPeriodTo(event.target.value)}
              />
            </Field>
          </div>

          <Field
            label="Source file"
            htmlFor="migration_file"
            hint="Up to 10 MB. The original file is kept for the configured retention period."
          >
            <div className="space-y-2">
              <input
                id="migration_file"
                ref={fileRef}
                type="file"
                accept=".xlsx,.xls,.csv,.xml,.json"
                className="hidden"
                onChange={(event) => void pickFile(event.target.files?.[0] || null)}
              />
              <Button
                variant="outline"
                icon={UploadCloud}
                className="w-full"
                onClick={() => fileRef.current?.click()}
              >
                {file ? "Choose another file" : "Choose Tally export"}
              </Button>
              {file && (
                <p className="truncate text-[11px] text-slate-500">
                  {file.name} · {formatBytes(file.size)}
                </p>
              )}
            </div>
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="File format" htmlFor="migration_format">
              <Select
                id="migration_format"
                value={format}
                onChange={(event) => setFormat(event.target.value as TallyMigrationFormat)}
              >
                {(catalog?.formats || []).map((option) => (
                  <option
                    key={option.key}
                    value={option.key}
                    disabled={!versionFormats.includes(option.key)}
                  >
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Mapping template" htmlFor="migration_template">
              <Select
                id="migration_template"
                value={templateId ?? ""}
                onChange={(event) => applyTemplate(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">No template</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name} ({migrationFormatLabel(template.file_format)})
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field label="Note for the reviewer" htmlFor="migration_note">
            <Textarea
              id="migration_note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Optional context about the export or the client's books."
              rows={2}
            />
          </Field>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              icon={ArrowLeftRight}
              onClick={() => void runPreview()}
              loading={previewing}
              disabled={!file || !dataUrl}
            >
              Parse & preview
            </Button>
            <Button
              icon={ShieldCheck}
              onClick={() => void createBatch()}
              loading={creating}
              disabled={!canSubmit}
            >
              Validate & stage
            </Button>
          </div>

          {error && <Callout tone="red" title="Import could not continue">{error}</Callout>}
          {savedNotice && <Callout tone="green">{savedNotice}</Callout>}
        </CardBody>
      </Card>

      <div className="space-y-4">
        {!preview && !batch && (
          <Card>
            <CardBody>
              <EmptyState
                icon={UploadCloud}
                title="Start with a source file"
                description="Choose a Tally export, parse it to confirm the columns, then map them. Validation reports duplicates, missing ledgers, invalid dates and unbalanced entries without changing any value."
              />
            </CardBody>
          </Card>
        )}

        {preview && !batch && (
          <Card>
            <CardHeader
              title="Column mapping"
              description={`${preview.row_count} row(s) detected. ${mappedCount} of ${mappingFields.length} fields mapped.`}
              actions={<Badge tone="blue">{migrationFormatLabel(preview.file_format)}</Badge>}
            />
            <CardBody className="space-y-4">
              {preview.note && <Callout tone="slate">{preview.note}</Callout>}
              <div>
                <p className="mb-2 text-[12px] font-semibold text-slate-700">File headers</p>
                <div className="flex flex-wrap gap-1.5">
                  {preview.headers.map((header) => (
                    <span
                      key={header}
                      className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
                    >
                      {header}
                    </span>
                  ))}
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                {mappingFields.map((field) => (
                  <label key={field.key} className="flex items-center gap-2 text-[12px]">
                    <span className="w-36 shrink-0 text-slate-600" title={field.group}>
                      {field.label}
                    </span>
                    <Select
                      value={mapping[field.key] || ""}
                      onChange={(event) =>
                        setMapping((current) => ({ ...current, [field.key]: event.target.value }))
                      }
                      className="text-[12px]"
                    >
                      <option value="">Not mapped</option>
                      {preview.headers.map((header) => (
                        <option key={header} value={header}>
                          {header}
                        </option>
                      ))}
                    </Select>
                  </label>
                ))}
              </div>

              <div className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <Field label="Save this mapping as a template" htmlFor="migration_template_name" className="min-w-[220px] flex-1">
                  <Input
                    id="migration_template_name"
                    value={templateName}
                    onChange={(event) => setTemplateName(event.target.value)}
                    placeholder="e.g. TallyPrime sales export"
                  />
                </Field>
                <Button
                  variant="outline"
                  icon={Save}
                  onClick={() => void saveTemplate()}
                  loading={savingTemplate}
                  disabled={!templateName.trim() || mappedCount === 0}
                >
                  Save template
                </Button>
              </div>
            </CardBody>
          </Card>
        )}

        {batch && validation && (
          <Card>
            <CardHeader
              title={`Batch #${batch.id} · ${batch.filename}`}
              description={
                validation.ok
                  ? "Validation passed. Submit the batch for senior approval."
                  : "Validation found errors. Correct the source file and upload it again; nothing has been posted."
              }
              actions={<StatusBadge status={batch.status} />}
            />
            <CardBody className="space-y-4">
              <ValidationSummary validation={validation} />

              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  icon={Download}
                  onClick={() => void downloadErrorReport(batch.id)}
                >
                  Download error report
                </Button>
                {batch.status === "validated" && validation.ok && (
                  <Button
                    icon={ClipboardCheck}
                    onClick={() => void submitBatch()}
                    loading={submitting}
                  >
                    Submit for approval
                  </Button>
                )}
                {batch.status === "pending_approval" && (
                  <Button variant="outline" icon={ArrowRight} onClick={onGoToApprovals}>
                    {isSeniorAccountant ? "Review in approvals" : "Awaiting senior approval"}
                  </Button>
                )}
              </div>

              {batch.status === "pending_approval" && (
                <Callout tone="amber" title="Nothing has been posted yet">
                  A senior accountant must approve this batch. Approval writes to the historical ledger
                  only; the live FINOVEXA ledger is untouched. Every batch can be rolled back later.
                </Callout>
              )}
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- reports tab */

function ReportsTab({ clients, clientId, onClientChange }: { clients: AccountingClient[]; clientId: number | null; onClientChange: (value: number) => void }) {
  const [years, setYears] = useState<string[]>([]);
  const [ledgerNames, setLedgerNames] = useState<string[]>([]);
  const [year, setYear] = useState("");
  const [report, setReport] = useState<TallyHistoricalReport | null>(null);
  const [comparison, setComparison] = useState<TallyComparisonRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ledger, setLedger] = useState("");
  const [ledgerReport, setLedgerReport] = useState<TallyLedgerHistory | null>(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  const loadYears = useCallback(async () => {
    if (!clientId) return;
    setError(null);
    try {
      const data = await get<{ years: string[]; ledgers: string[] }>(
        `/accounting/tally-migration/years?client_id=${clientId}`,
      );
      setYears(data.years);
      setLedgerNames(data.ledgers);
      setYear((current) => (data.years.includes(current) ? current : data.years[0] || ""));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }, [clientId]);

  useEffect(() => {
    void loadYears();
  }, [loadYears]);

  const loadReport = useCallback(async () => {
    if (!clientId || !year) return;
    setLoading(true);
    setError(null);
    setLedgerReport(null);
    try {
      const [bundle, compare] = await Promise.all([
        get<TallyHistoricalReport>(
          `/accounting/tally-migration/reports?client_id=${clientId}&financial_year=${year}`,
        ),
        get<{ years: TallyComparisonRow[] }>(
          `/accounting/tally-migration/reports/compare?client_id=${clientId}&financial_year=${year}`,
        ),
      ]);
      setReport(bundle);
      setComparison(compare.years);
    } catch (err) {
      setReport(null);
      setComparison([]);
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [clientId, year]);

  useEffect(() => {
    if (year) void loadReport();
  }, [year, loadReport]);

  const openLedger = async () => {
    if (!clientId || !year || !ledger) return;
    setLedgerLoading(true);
    setError(null);
    try {
      setLedgerReport(
        await get<TallyLedgerHistory>(
          `/accounting/tally-migration/reports/ledger?client_id=${clientId}&financial_year=${year}&ledger=${encodeURIComponent(ledger)}`,
        ),
      );
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLedgerLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="grid gap-3 sm:grid-cols-3">
          <ClientSelect clients={clients} value={clientId} onChange={onClientChange} id="report_client" />
          <Field label="Financial year" htmlFor="report_year">
            <Select id="report_year" value={year} onChange={(event) => setYear(event.target.value)}>
              {years.length === 0 && <option value="">No imported years</option>}
              {years.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex items-end">
            <Button variant="outline" icon={RotateCcw} onClick={() => void loadReport()} disabled={!year}>
              Refresh reports
            </Button>
          </div>
        </CardBody>
      </Card>

      {error && <Callout tone="red" title="Reports unavailable">{error}</Callout>}

      {loading && <PageSkeleton cards={4} />}

      {!loading && !report && !error && (
        <Card>
          <CardBody>
            <EmptyState
              icon={LineChart}
              title="No imported history yet"
              description="Approve a Tally import for this client to unlock prior-year profit and loss, balance sheet, trial balance, GST and year comparison."
            />
          </CardBody>
        </Card>
      )}

      {report && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Imported vouchers" value={report.counts.vouchers} tone="blue" icon={BookOpen} />
            <StatCard label="Revenue" value={money(report.profit_loss.revenue_total)} tone="green" icon={LineChart} />
            <StatCard label="Expenses" value={money(report.profit_loss.expense_total)} tone="amber" icon={FileText} />
            <StatCard label="Net profit" value={money(report.profit_loss.net_profit)} tone="violet" icon={BadgeCheck} />
          </div>

          <Callout tone="blue" title={`Imported history · ${report.financial_year}`}>
            {report.source_note}
          </Callout>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Profit & loss" description={report.profit_loss.note} />
              <CardBody className="space-y-4">
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Revenue</p>
                  {report.profit_loss.revenue.length === 0 && <p className="text-[12px] text-slate-400">None</p>}
                  {report.profit_loss.revenue.map((row) => (
                    <div key={`${row.ledger}-${row.amount}`} className="flex justify-between border-b border-slate-100 py-1 text-[12px]">
                      <span className="text-slate-600">{row.ledger}</span>
                      <span className="font-medium text-ink-900">{money(row.amount)}</span>
                    </div>
                  ))}
                  <div className="mt-1 flex justify-between text-[13px] font-semibold">
                    <span>Revenue total</span>
                    <span>{money(report.profit_loss.revenue_total)}</span>
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Expenses</p>
                  {report.profit_loss.expenses.length === 0 && <p className="text-[12px] text-slate-400">None</p>}
                  {report.profit_loss.expenses.map((row) => (
                    <div key={`${row.ledger}-${row.amount}`} className="flex justify-between border-b border-slate-100 py-1 text-[12px]">
                      <span className="text-slate-600">{row.ledger}</span>
                      <span className="font-medium text-ink-900">{money(row.amount)}</span>
                    </div>
                  ))}
                  <div className="mt-1 flex justify-between text-[13px] font-semibold">
                    <span>Expense total</span>
                    <span>{money(report.profit_loss.expense_total)}</span>
                  </div>
                </div>
                <div className="flex justify-between rounded-lg bg-slate-50 px-3 py-2 text-[13px] font-semibold">
                  <span>Net profit</span>
                  <span className={report.profit_loss.net_profit >= 0 ? "text-emerald-700" : "text-rose-700"}>
                    {money(report.profit_loss.net_profit)}
                  </span>
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Balance sheet" description={report.balance_sheet.note} />
              <CardBody className="space-y-4">
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Assets</p>
                  {report.balance_sheet.assets.map((row) => (
                    <div key={`${row.ledger}-${row.amount}`} className="flex justify-between border-b border-slate-100 py-1 text-[12px]">
                      <span className="text-slate-600">{row.ledger}</span>
                      <span className="font-medium text-ink-900">{money(row.amount)}</span>
                    </div>
                  ))}
                  <div className="mt-1 flex justify-between text-[13px] font-semibold">
                    <span>Assets total</span>
                    <span>{money(report.balance_sheet.asset_total)}</span>
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Liabilities & equity</p>
                  {report.balance_sheet.liabilities.map((row) => (
                    <div key={`${row.ledger}-${row.amount}`} className="flex justify-between border-b border-slate-100 py-1 text-[12px]">
                      <span className="text-slate-600">{row.ledger}</span>
                      <span className="font-medium text-ink-900">{money(row.amount)}</span>
                    </div>
                  ))}
                  <div className="mt-1 flex justify-between text-[13px] font-semibold">
                    <span>Liabilities total</span>
                    <span>{money(report.balance_sheet.liability_total)}</span>
                  </div>
                </div>
                <div
                  className={`flex justify-between rounded-lg px-3 py-2 text-[13px] font-semibold ${
                    report.balance_sheet.difference === 0
                      ? "bg-emerald-50 text-emerald-800"
                      : "bg-rose-50 text-rose-800"
                  }`}
                >
                  <span>Difference</span>
                  <span>{money(report.balance_sheet.difference)}</span>
                </div>
                {report.balance_sheet.unclassified_ledgers.length > 0 && (
                  <p className="text-[11px] text-slate-500">
                    Unclassified ledgers: {report.balance_sheet.unclassified_ledgers.join(", ")}
                  </p>
                )}
              </CardBody>
            </Card>
          </div>

          <Card>
            <CardHeader
              title="Trial balance"
              description={`Difference ${money(report.trial_balance.totals.difference)} · opening balances are included where approved.`}
            />
            <CardBody>
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Ledger</TH>
                    <TH>Group</TH>
                    <TH>Opening Dr</TH>
                    <TH>Opening Cr</TH>
                    <TH>Debit</TH>
                    <TH>Credit</TH>
                    <TH>Closing Dr</TH>
                    <TH>Closing Cr</TH>
                  </TR>
                </THead>
                <TBody>
                  {report.trial_balance.rows.map((row) => (
                    <TR key={row.ledger}>
                      <TD className="font-medium text-ink-900">{row.ledger}</TD>
                      <TD className="text-slate-500">{row.group}</TD>
                      <TD>{money(row.opening_debit)}</TD>
                      <TD>{money(row.opening_credit)}</TD>
                      <TD>{money(row.debit)}</TD>
                      <TD>{money(row.credit)}</TD>
                      <TD>{money(row.closing_debit)}</TD>
                      <TD>{money(row.closing_credit)}</TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            </CardBody>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Customer & supplier outstanding"
                description="Derived from closing balances of debtor and creditor groups."
              />
              <CardBody className="grid gap-4 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    Customers ({money(report.outstanding.customer_total)})
                  </p>
                  {report.outstanding.customers.length === 0 && <p className="text-[12px] text-slate-400">None</p>}
                  {report.outstanding.customers.map((row) => (
                    <div key={row.party} className="flex justify-between border-b border-slate-100 py-1 text-[12px]">
                      <span className="text-slate-600">{row.party}</span>
                      <span className="font-medium text-ink-900">{money(row.amount)}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    Suppliers ({money(report.outstanding.supplier_total)})
                  </p>
                  {report.outstanding.suppliers.length === 0 && <p className="text-[12px] text-slate-400">None</p>}
                  {report.outstanding.suppliers.map((row) => (
                    <div key={row.party} className="flex justify-between border-b border-slate-100 py-1 text-[12px]">
                      <span className="text-slate-600">{row.party}</span>
                      <span className="font-medium text-ink-900">{money(row.amount)}</span>
                    </div>
                  ))}
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="GST summary" description={report.gst.note} />
              <CardBody className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Output tax</p>
                  <p className="text-sm font-semibold">{money(report.gst.output.total_tax)}</p>
                  <p className="text-[10px] text-slate-400">
                    CGST {money(report.gst.output.cgst)} · SGST {money(report.gst.output.sgst)} · IGST{" "}
                    {money(report.gst.output.igst)}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Input tax</p>
                  <p className="text-sm font-semibold">{money(report.gst.input.total_tax)}</p>
                  <p className="text-[10px] text-slate-400">
                    CGST {money(report.gst.input.cgst)} · SGST {money(report.gst.input.sgst)} · IGST{" "}
                    {money(report.gst.input.igst)}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Credit notes</p>
                  <p className="text-sm font-semibold">{money(report.gst.credit_notes.total_tax)}</p>
                </div>
                <div className="rounded-lg border border-slate-200 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Debit notes</p>
                  <p className="text-sm font-semibold">{money(report.gst.debit_notes.total_tax)}</p>
                </div>
                <div className="sm:col-span-2 flex justify-between rounded-lg bg-brand-50 px-3 py-2 text-[13px] font-semibold text-brand-900">
                  <span>Net GST payable</span>
                  <span>{money(report.gst.net_payable)}</span>
                </div>
              </CardBody>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Monthly revenue & expenses" description={`Sales ${report.sales.count} · Purchases ${report.purchases.count} · Expenses ${report.expenses.count}`} />
              <CardBody>
                {report.monthly.length === 0 ? (
                  <p className="text-[12px] text-slate-400">No vouchers in this year.</p>
                ) : (
                  <TableWrap>
                    <THead>
                      <TR>
                        <TH>Month</TH>
                        <TH>Revenue</TH>
                        <TH>Purchases</TH>
                        <TH>Expenses</TH>
                        <TH>Profit</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {report.monthly.map((row) => (
                        <TR key={row.month}>
                          <TD>{row.month}</TD>
                          <TD>{money(row.revenue)}</TD>
                          <TD>{money(row.purchases)}</TD>
                          <TD>{money(row.expenses)}</TD>
                          <TD>{money(row.profit)}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </TableWrap>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Financial year comparison" description="Imported history across multiple years." />
              <CardBody>
                {comparison.length === 0 ? (
                  <p className="text-[12px] text-slate-400">No comparison data.</p>
                ) : (
                  <TableWrap>
                    <THead>
                      <TR>
                        <TH>Year</TH>
                        <TH>Vouchers</TH>
                        <TH>Revenue</TH>
                        <TH>Expenses</TH>
                        <TH>Net profit</TH>
                        <TH>GST</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {comparison.map((row) => (
                        <TR key={row.financial_year}>
                          <TD className="font-medium text-ink-900">{row.financial_year}</TD>
                          <TD>{row.vouchers}</TD>
                          <TD>{money(row.revenue)}</TD>
                          <TD>{money(row.expenses)}</TD>
                          <TD>{money(row.net_profit)}</TD>
                          <TD>{money(row.gst)}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </TableWrap>
                )}
              </CardBody>
            </Card>
          </div>

          <Card>
            <CardHeader
              title="Ledger-wise history"
              description="Drill into a ledger to see the imported vouchers that moved it."
            />
            <CardBody className="space-y-3">
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Ledger" htmlFor="report_ledger" className="min-w-[220px] flex-1">
                  <Select id="report_ledger" value={ledger} onChange={(event) => setLedger(event.target.value)}>
                    <option value="">Choose a ledger</option>
                    {ledgerNames.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button variant="outline" icon={BookOpen} onClick={() => void openLedger()} loading={ledgerLoading} disabled={!ledger}>
                  Open ledger
                </Button>
              </div>

              {ledgerReport && (
                <>
                  <p className="text-[12px] text-slate-500">
                    Opening {money(ledgerReport.opening_debit)} Dr / {money(ledgerReport.opening_credit)} Cr · Closing{" "}
                    <span className="font-semibold text-ink-900">
                      {money(ledgerReport.closing)} {ledgerReport.closing_type}
                    </span>
                  </p>
                  <TableWrap>
                    <THead>
                      <TR>
                        <TH>Date</TH>
                        <TH>Type</TH>
                        <TH>Number</TH>
                        <TH>Party</TH>
                        <TH>Debit</TH>
                        <TH>Credit</TH>
                        <TH>Balance</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {ledgerReport.entries.map((entry, index) => (
                        <TR key={`${entry.number}-${entry.date}-${index}`}>
                          <TD>{formatDate(entry.date)}</TD>
                          <TD>{labelize(entry.voucher_type)}</TD>
                          <TD>{entry.number}</TD>
                          <TD>{entry.party || "—"}</TD>
                          <TD>{money(entry.debit)}</TD>
                          <TD>{money(entry.credit)}</TD>
                          <TD>
                            {money(entry.balance)} {entry.balance_type}
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </TableWrap>
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Live FINOVEXA activity" description="Kept separate from imported history." />
            <CardBody className="flex flex-wrap items-center gap-6">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Newly recorded vouchers</p>
                <p className="text-lg font-semibold text-ink-900">{report.live.vouchers}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Live total</p>
                <p className="text-lg font-semibold text-ink-900">{money(report.live.total)}</p>
              </div>
              <Badge tone="slate">{report.live.label}</Badge>
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- opening tab */

type OpeningLineDraft = {
  ledger_name: string;
  group_name: string;
  party_type: string;
  debit: string;
  credit: string;
  stock_item: string;
  quantity: string;
  rate: string;
};

const emptyOpeningLine = (): OpeningLineDraft => ({
  ledger_name: "",
  group_name: "",
  party_type: "other",
  debit: "",
  credit: "",
  stock_item: "",
  quantity: "",
  rate: "",
});

function OpeningTab({ clients, clientId, onClientChange }: { clients: AccountingClient[]; clientId: number | null; onClientChange: (value: number) => void }) {
  const { isSeniorAccountant } = useAuth();
  const [openings, setOpenings] = useState<TallyOpeningBalance[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [financialYear, setFinancialYear] = useState(currentFinancialYear());
  const [openingDate, setOpeningDate] = useState(financialYearStart(currentFinancialYear()));
  const [lines, setLines] = useState<OpeningLineDraft[]>([emptyOpeningLine(), emptyOpeningLine()]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<TallyOpeningBalance | null>(null);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await get<{ items: TallyOpeningBalance[] }>(
        `/accounting/tally-migration/opening-balances?client_id=${clientId}`,
      );
      setOpenings(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    void load();
  }, [load]);

  const updateLine = (index: number, patchValue: Partial<OpeningLineDraft>) => {
    setLines((current) =>
      current.map((line, position) => (position === index ? { ...line, ...patchValue } : line)),
    );
  };

  const debitTotal = lines.reduce((sum, line) => sum + (Number(line.debit) || 0), 0);
  const creditTotal = lines.reduce((sum, line) => sum + (Number(line.credit) || 0), 0);
  const difference = Math.round((debitTotal - creditTotal) * 100) / 100;
  const lineProblem =
    lines.some(
      (line) =>
        !line.ledger_name.trim() ||
        (Number(line.debit) > 0) === (Number(line.credit) > 0),
    ) || lines.length === 0;

  const submit = async () => {
    if (!clientId) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await post<TallyOpeningBalance>("/accounting/tally-migration/opening-balances", {
        client_id: clientId,
        financial_year: financialYear,
        opening_date: openingDate,
        note: note || null,
        lines: lines.map((line) => ({
          ledger_name: line.ledger_name.trim(),
          group_name: line.group_name.trim() || null,
          party_type: line.party_type,
          debit: Number(line.debit) || 0,
          credit: Number(line.credit) || 0,
          stock_item: line.stock_item.trim() || null,
          quantity: line.quantity ? Number(line.quantity) : null,
          rate: line.rate ? Number(line.rate) : null,
        })),
      });
      setNotice("Opening balances recorded and approved. They are excluded from profit and loss.");
      setLines([emptyOpeningLine(), emptyOpeningLine()]);
      setNote("");
      await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="grid gap-3 sm:grid-cols-3">
          <ClientSelect clients={clients} value={clientId} onChange={onClientChange} id="opening_client" />
          <Field label="Financial year" htmlFor="opening_fy">
            <Input
              id="opening_fy"
              value={financialYear}
              onChange={(event) => {
                setFinancialYear(event.target.value);
                setOpeningDate(financialYearStart(event.target.value));
              }}
              placeholder="2025-26"
            />
          </Field>
          <Field label="Opening date" htmlFor="opening_date">
            <Input
              id="opening_date"
              type="date"
              value={openingDate}
              onChange={(event) => setOpeningDate(event.target.value)}
            />
          </Field>
        </CardBody>
      </Card>

      {error && <Callout tone="red" title="Opening balances could not be saved">{error}</Callout>}
      {notice && <Callout tone="green">{notice}</Callout>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,380px)]">
        <Card>
          <CardHeader
            title="Existing opening balances"
            description="Approved openings are authoritative for reports. A second opening for the same year is blocked."
          />
          <CardBody>
            {loading ? (
              <PageSkeleton cards={2} />
            ) : openings.length === 0 ? (
              <EmptyState
                icon={Layers}
                title="No opening balances recorded"
                description="Upload an opening-balance file through the import wizard or enter them manually as a senior accountant."
              />
            ) : (
              <div className="space-y-2">
                {openings.map((opening) => (
                  <button
                    key={opening.id}
                    type="button"
                    onClick={() => setDetail(opening)}
                    className="flex w-full flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 text-left transition hover:border-brand-300 hover:bg-brand-50/30"
                  >
                    <div>
                      <p className="text-[13px] font-semibold text-ink-900">
                        {opening.financial_year} · {formatDate(opening.opening_date)}
                      </p>
                      <p className="text-[11px] text-slate-500">
                        {opening.lines.length} line(s) · approved {opening.approved_at ? formatDateTime(opening.approved_at) : "—"}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-[12px] font-semibold text-ink-900">
                        Dr {money(opening.total_debit)} / Cr {money(opening.total_credit)}
                      </p>
                      <p className="text-[11px] text-slate-500">Stock {money(opening.stock_value)}</p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Manual opening balance entry"
            description={
              isSeniorAccountant
                ? "Senior-only entry. Each line needs exactly one of debit or credit; totals must balance."
                : "Only a senior accountant can record opening balances."
            }
          />
          <CardBody className="space-y-3">
            {!isSeniorAccountant && (
              <Callout tone="slate" title="Senior approval required">
                You can prepare and upload an opening-balance file, but posting requires a senior accountant.
              </Callout>
            )}

            <div className="space-y-2">
              {lines.map((line, index) => (
                <div key={index} className="space-y-1.5 rounded-lg border border-slate-200 px-2 py-2">
                  <div className="flex items-center gap-2">
                    <Input
                      value={line.ledger_name}
                      onChange={(event) => updateLine(index, { ledger_name: event.target.value })}
                      placeholder="Ledger name"
                      aria-label={`Ledger name line ${index + 1}`}
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={Trash2}
                      aria-label={`Remove line ${index + 1}`}
                      onClick={() => setLines((current) => current.filter((_, position) => position !== index))}
                      disabled={lines.length <= 1}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    <Input
                      value={line.group_name}
                      onChange={(event) => updateLine(index, { group_name: event.target.value })}
                      placeholder="Group (optional)"
                    />
                    <Select
                      value={line.party_type}
                      onChange={(event) => updateLine(index, { party_type: event.target.value })}
                    >
                      <option value="other">Other</option>
                      <option value="customer">Customer</option>
                      <option value="supplier">Supplier</option>
                    </Select>
                    <Input
                      value={line.debit}
                      onChange={(event) => updateLine(index, { debit: event.target.value, credit: "" })}
                      placeholder="Debit"
                      inputMode="decimal"
                    />
                    <Input
                      value={line.credit}
                      onChange={(event) => updateLine(index, { credit: event.target.value, debit: "" })}
                      placeholder="Credit"
                      inputMode="decimal"
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-1.5">
                    <Input
                      value={line.stock_item}
                      onChange={(event) => updateLine(index, { stock_item: event.target.value })}
                      placeholder="Stock item"
                    />
                    <Input
                      value={line.quantity}
                      onChange={(event) => updateLine(index, { quantity: event.target.value })}
                      placeholder="Qty"
                      inputMode="decimal"
                    />
                    <Input
                      value={line.rate}
                      onChange={(event) => updateLine(index, { rate: event.target.value })}
                      placeholder="Rate"
                      inputMode="decimal"
                    />
                  </div>
                </div>
              ))}
            </div>

            <Button variant="outline" icon={Upload} onClick={() => setLines((current) => [...current, emptyOpeningLine()])}>
              Add line
            </Button>

            <div className="rounded-lg bg-slate-50 px-3 py-2 text-[12px]">
              <div className="flex justify-between">
                <span>Debit total</span>
                <span className="font-semibold">{money(debitTotal)}</span>
              </div>
              <div className="flex justify-between">
                <span>Credit total</span>
                <span className="font-semibold">{money(creditTotal)}</span>
              </div>
              <div className={`mt-1 flex justify-between font-semibold ${difference === 0 ? "text-emerald-700" : "text-rose-700"}`}>
                <span>Difference</span>
                <span>{money(difference)}</span>
              </div>
            </div>

            <Field label="Note" htmlFor="opening_note">
              <Textarea
                id="opening_note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={2}
                placeholder="Source of the opening balances"
              />
            </Field>

            <Button
              icon={ShieldCheck}
              onClick={() => void submit()}
              loading={saving}
              disabled={!isSeniorAccountant || !clientId || lineProblem || difference !== 0}
            >
              Approve opening balances
            </Button>
          </CardBody>
        </Card>
      </div>

      <Modal
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title={detail ? `Opening balances · ${detail.financial_year}` : "Opening balances"}
        description={detail ? `${formatDate(detail.opening_date)} · approved ${detail.approved_at ? formatDateTime(detail.approved_at) : "—"}` : undefined}
        size="lg"
      >
        {detail && (
          <TableWrap>
            <THead>
              <TR>
                <TH>Ledger</TH>
                <TH>Group</TH>
                <TH>Party</TH>
                <TH>Debit</TH>
                <TH>Credit</TH>
                <TH>Stock</TH>
              </TR>
            </THead>
            <TBody>
              {detail.lines.map((line) => (
                <TR key={line.id}>
                  <TD className="font-medium text-ink-900">{line.ledger_name}</TD>
                  <TD>{line.group_name || "—"}</TD>
                  <TD>{labelize(line.party_type)}</TD>
                  <TD>{money(line.debit)}</TD>
                  <TD>{money(line.credit)}</TD>
                  <TD>{line.stock_item ? `${line.stock_item} · ${line.quantity ?? 0} @ ${line.rate ?? 0}` : "—"}</TD>
                </TR>
              ))}
            </TBody>
          </TableWrap>
        )}
      </Modal>
    </div>
  );
}

/* ------------------------------------------------------------- approvals tab */

function ApprovalsTab({ clients }: { clients: AccountingClient[] }) {
  const [pending, setPending] = useState<TallyMigrationBatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<TallyMigrationBatch | null>(null);
  const [note, setNote] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await get<TallyMigrationBatchList>(
        "/accounting/tally-migration/batches?status=pending_approval",
      );
      setPending(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openReview = async (batch: TallyMigrationBatch) => {
    setError(null);
    setNote("");
    try {
      setReview(
        await get<TallyMigrationBatch>(`/accounting/tally-migration/batches/${batch.id}`),
      );
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const decide = async (decision: "approve" | "reject") => {
    if (!review) return;
    setDeciding(true);
    setError(null);
    try {
      const response = await post<{ batch: TallyMigrationBatch; result: Record<string, unknown> }>(
        `/accounting/tally-migration/batches/${review.id}/decision`,
        { decision, note: note || null },
      );
      setResult(
        `${decision === "approve" ? "Approved" : "Rejected"} batch #${response.batch.id} (${labelize(response.batch.status)}). ${
          typeof response.result.imported === "number" ? `${response.result.imported} record(s) imported.` : ""
        }`,
      );
      setReview(null);
      setNote("");
      await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setDeciding(false);
    }
  };

  const clientName = (batch: TallyMigrationBatch) =>
    batch.client_name || clients.find((client) => client.id === batch.client_id)?.business_name || "—";

  return (
    <div className="space-y-4">
      {error && <Callout tone="red" title="Approval queue unavailable">{error}</Callout>}
      {result && <Callout tone="green">{result}</Callout>}

      <Card>
        <CardHeader
          title="Pending import approvals"
          description="Only a senior accountant can approve an import. Approval writes to historical tables, never to the live FINOVEXA ledger."
          actions={
            <Button variant="outline" size="sm" icon={RotateCcw} onClick={() => void load()} loading={loading}>
              Refresh
            </Button>
          }
        />
        <CardBody>
          {loading ? (
            <PageSkeleton cards={2} />
          ) : pending.length === 0 ? (
            <EmptyState
              icon={BadgeCheck}
              title="Nothing awaiting approval"
              description="Validated imports appear here after a junior or senior submits them."
            />
          ) : (
            <div className="space-y-2">
              {pending.map((batch) => (
                <div
                  key={batch.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-ink-900">
                      {clientName(batch)} · {batch.filename}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {batch.financial_year} · {batch.import_type_label || labelize(batch.import_type)} ·{" "}
                      {batch.row_count} row(s) · {batch.valid_count} valid · {batch.warning_count} warning ·{" "}
                      {batch.duplicate_count} duplicate · prepared by {batch.prepared_by || "—"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={batch.status} />
                    <Button size="sm" variant="outline" onClick={() => void openReview(batch)}>
                      Review
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <Modal
        open={Boolean(review)}
        onClose={() => setReview(null)}
        title={review ? `Review batch #${review.id} · ${review.filename}` : "Review batch"}
        description={review ? `${clientName(review)} · ${review.financial_year}` : undefined}
        size="xl"
        footer={
          review ? (
            <>
              <Button variant="outline" onClick={() => setReview(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                loading={deciding}
                disabled={!note.trim()}
                onClick={() => void decide("reject")}
              >
                Reject
              </Button>
              <Button
                variant="success"
                icon={BadgeCheck}
                loading={deciding}
                onClick={() => void decide("approve")}
              >
                Approve & post history
              </Button>
            </>
          ) : undefined
        }
      >
        {review && (
          <div className="space-y-4">
            <BatchDetailBody batch={review} />
            <Callout tone="slate" title="Before approving">
              Duplicate rows are skipped automatically and never overwrite existing vouchers. A rejection
              needs a reason; an approved batch can be rolled back by a senior accountant.
            </Callout>
            <Field label="Decision note" htmlFor="decision_note" hint="Required to reject.">
              <Textarea
                id="decision_note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                placeholder="Explain the decision for the audit trail"
              />
            </Field>
          </div>
        )}
      </Modal>
    </div>
  );
}

/* --------------------------------------------------------------- history tab */

function HistoryTab({ clients }: { clients: AccountingClient[] }) {
  const { isSeniorAccountant } = useAuth();
  const [items, setItems] = useState<TallyMigrationBatch[]>([]);
  const [status, setStatus] = useState("");
  const [year, setYear] = useState("");
  const [clientFilter, setClientFilter] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<TallyMigrationBatch | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<TallyMigrationBatch | null>(null);
  const [rollingBack, setRollingBack] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (clientFilter) params.set("client_id", String(clientFilter));
      if (status) params.set("status", status);
      if (year.trim()) params.set("financial_year", year.trim());
      const data = await get<TallyMigrationBatchList>(
        `/accounting/tally-migration/batches?${params.toString()}`,
      );
      setItems(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [clientFilter, status, year]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (batch: TallyMigrationBatch) => {
    setError(null);
    try {
      setDetail(
        await get<TallyMigrationBatch>(`/accounting/tally-migration/batches/${batch.id}`),
      );
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const download = async (path: string, name: string) => {
    try {
      await downloadFile(path, name);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const rollback = async () => {
    if (!rollbackTarget) return;
    setRollingBack(true);
    setError(null);
    try {
      const response = await post<{ batch: TallyMigrationBatch; result: Record<string, unknown> }>(
        `/accounting/tally-migration/batches/${rollbackTarget.id}/rollback`,
      );
      setNotice(
        `Batch #${response.batch.id} rolled back. Imported vouchers and ledgers from that batch were removed; other history is untouched.`,
      );
      setRollbackTarget(null);
      if (detail?.id === response.batch.id) setDetail(null);
      await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setRollingBack(false);
    }
  };

  const clientName = (batch: TallyMigrationBatch) =>
    batch.client_name || clients.find((client) => client.id === batch.client_id)?.business_name || "—";

  return (
    <div className="space-y-4">
      {error && <Callout tone="red" title="History unavailable">{error}</Callout>}
      {notice && <Callout tone="green">{notice}</Callout>}

      <Card>
        <CardHeader title="Import, approval and export history" description="Every upload, validation, approval, download and rollback is retained in the audit trail." />
        <CardBody className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-4">
            <Field label="Client" htmlFor="history_client">
              <Select
                id="history_client"
                value={clientFilter ?? ""}
                onChange={(event) => setClientFilter(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">All visible clients</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.business_name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Status" htmlFor="history_status">
              <Select id="history_status" value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="">All statuses</option>
                {["validated", "pending_approval", "imported", "partially_imported", "failed", "rejected", "rolled_back"].map(
                  (option) => (
                    <option key={option} value={option}>
                      {labelize(option)}
                    </option>
                  ),
                )}
              </Select>
            </Field>
            <Field label="Financial year" htmlFor="history_year">
              <Input
                id="history_year"
                value={year}
                onChange={(event) => setYear(event.target.value)}
                placeholder="2024-25"
              />
            </Field>
            <div className="flex items-end">
              <Button variant="outline" icon={RotateCcw} onClick={() => void load()} loading={loading}>
                Apply filters
              </Button>
            </div>
          </div>

          {loading ? (
            <PageSkeleton cards={2} />
          ) : items.length === 0 ? (
            <EmptyState icon={History} title="No import batches yet" description="Upload a Tally export to create the first batch." />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Batch</TH>
                  <TH>Client</TH>
                  <TH>Year</TH>
                  <TH>Rows</TH>
                  <TH>Status</TH>
                  <TH>Prepared / approved</TH>
                  <TH>Actions</TH>
                </TR>
              </THead>
              <TBody>
                {items.map((batch) => (
                  <TR key={batch.id}>
                    <TD>
                      <button type="button" className="text-left font-medium text-brand-700 hover:underline" onClick={() => void openDetail(batch)}>
                        #{batch.id} · {batch.filename}
                      </button>
                      <p className="text-[10px] text-slate-400">
                        {batch.import_type_label || labelize(batch.import_type)} ·{" "}
                        {migrationFormatLabel(batch.file_format)} ·{" "}
                        {formatDateTime(batch.created_at)}
                      </p>
                    </TD>
                    <TD>{clientName(batch)}</TD>
                    <TD>{batch.financial_year}</TD>
                    <TD>
                      {batch.row_count}
                      {batch.imported_count > 0 ? (
                        <span className="block text-[10px] text-emerald-600">{batch.imported_count} imported</span>
                      ) : null}
                    </TD>
                    <TD>
                      <StatusBadge status={batch.status} />
                    </TD>
                    <TD className="text-[11px] text-slate-500">
                      {batch.prepared_by || "—"}
                      <span className="block">→ {batch.approved_by || "—"}</span>
                    </TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        <Button size="sm" variant="ghost" icon={Download} onClick={() => void download(`/accounting/tally-migration/batches/${batch.id}/error-report`, `tally-import-${batch.id}-error-report.csv`)}>
                          Error report
                        </Button>
                        <Button size="sm" variant="ghost" icon={FileText} onClick={() => void download(`/accounting/tally-migration/batches/${batch.id}/source`, batch.filename)}>
                          Source
                        </Button>
                        {isSeniorAccountant && ["imported", "partially_imported", "failed"].includes(batch.status) && (
                          <Button size="sm" variant="ghost" icon={RotateCcw} onClick={() => setRollbackTarget(batch)}>
                            Roll back
                          </Button>
                        )}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </CardBody>
      </Card>

      <Modal
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title={detail ? `Batch #${detail.id} · ${detail.filename}` : "Batch"}
        size="xl"
      >
        {detail && <BatchDetailBody batch={detail} />}
      </Modal>

      <ConfirmDialog
        open={Boolean(rollbackTarget)}
        onClose={() => setRollbackTarget(null)}
        onConfirm={() => void rollback()}
        title={`Roll back batch #${rollbackTarget?.id ?? ""}?`}
        description="Only vouchers, ledgers and opening balances created by this batch are removed. Other imported history and every live FINOVEXA transaction stay untouched."
        confirmLabel="Roll back batch"
        tone="danger"
        loading={rollingBack}
      />
    </div>
  );
}

/* -------------------------------------------------------------- mappings tab */

function MappingsTab({
  clients,
  catalog,
  templates,
  onChanged,
}: {
  clients: AccountingClient[];
  catalog: TallyMigrationCatalog | null;
  templates: TallyMappingTemplate[];
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [clientScope, setClientScope] = useState<number | null>(null);
  const [format, setFormat] = useState<TallyMigrationFormat>("csv");
  const [importType, setImportType] = useState("complete");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TallyMappingTemplate | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fields = catalog?.mapping_fields || [];

  const create = async () => {
    setSaving(true);
    setError(null);
    try {
      await post<TallyMappingTemplate>("/accounting/tally-migration/mappings", {
        name: name.trim(),
        client_id: clientScope,
        file_format: format,
        import_type: importType,
        mapping,
        is_shared: true,
      });
      setOpen(false);
      setName("");
      setMapping({});
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setError(null);
    try {
      await api(`/accounting/tally-migration/mappings/${deleteTarget.id}`, { method: "DELETE" });
      setDeleteTarget(null);
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  const mappedCount = Object.values(mapping).filter((value) => value.trim()).length;

  return (
    <div className="space-y-4">
      {error && <Callout tone="red" title="Mapping template error">{error}</Callout>}

      <Card>
        <CardHeader
          title="Reusable mapping templates"
          description="Save a column mapping once per client and format; reuse it for every future import."
          actions={
            <Button icon={Save} onClick={() => setOpen(true)}>
              New template
            </Button>
          }
        />
        <CardBody>
          {templates.length === 0 ? (
            <EmptyState
              icon={Layers}
              title="No mapping templates yet"
              description="Parse an import, map the columns and save the mapping — or create a template here."
            />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Scope</TH>
                  <TH>Format</TH>
                  <TH>Import type</TH>
                  <TH>Fields</TH>
                  <TH>Created</TH>
                  <TH>Actions</TH>
                </TR>
              </THead>
              <TBody>
                {templates.map((template) => (
                  <TR key={template.id}>
                    <TD className="font-medium text-ink-900">{template.name}</TD>
                    <TD>
                      {template.client_id
                        ? clients.find((client) => client.id === template.client_id)?.business_name || `Client #${template.client_id}`
                        : "All clients"}
                    </TD>
                    <TD>{migrationFormatLabel(template.file_format)}</TD>
                    <TD>{labelize(template.import_type)}</TD>
                    <TD>{Object.keys(template.mapping).length}</TD>
                    <TD>{formatDate(template.created_at)}</TD>
                    <TD>
                      <Button size="sm" variant="ghost" icon={Trash2} onClick={() => setDeleteTarget(template)}>
                        Delete
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </CardBody>
      </Card>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="New mapping template"
        description="Map FINOVEXA fields to the exact column names used in the Tally export."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button icon={Save} loading={saving} onClick={() => void create()} disabled={name.trim().length < 2 || mappedCount === 0}>
              Save template
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Template name" htmlFor="template_name" required>
              <Input id="template_name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Meridian sales export" />
            </Field>
            <Field label="Client scope" htmlFor="template_client">
              <Select
                id="template_client"
                value={clientScope ?? ""}
                onChange={(event) => setClientScope(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">All clients</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.business_name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Format" htmlFor="template_format">
              <Select id="template_format" value={format} onChange={(event) => setFormat(event.target.value as TallyMigrationFormat)}>
                {(catalog?.formats || []).map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Import type" htmlFor="template_type">
              <Select id="template_type" value={importType} onChange={(event) => setImportType(event.target.value)}>
                {(catalog?.import_types || []).map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <p className="text-[11px] text-slate-500">
            Enter the source column heading for each field you want to map. Leave a field blank to skip it.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {fields.map((field) => (
              <label key={field.key} className="flex items-center gap-2 text-[12px]">
                <span className="w-32 shrink-0 text-slate-600">{field.label}</span>
                <Input
                  value={mapping[field.key] || ""}
                  onChange={(event) =>
                    setMapping((current) => ({ ...current, [field.key]: event.target.value }))
                  }
                  placeholder={field.aliases[0] || "Column name"}
                />
              </label>
            ))}
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void remove()}
        title="Delete mapping template?"
        description={deleteTarget ? `“${deleteTarget.name}” will be removed. Existing imports are not affected.` : undefined}
        confirmLabel="Delete template"
        tone="danger"
        loading={deleting}
      />
    </div>
  );
}

/* --------------------------------------------------------------------- page */

export function TallyMigrationPage() {
  const { isSeniorAccountant } = useAuth();
  const { clients, clientId, setClientId, loading: clientsLoading, error: clientsError } = useClients();
  const [tab, setTab] = useState<TabKey>("import");
  const [catalog, setCatalog] = useState<TallyMigrationCatalog | null>(null);
  const [templates, setTemplates] = useState<TallyMappingTemplate[]>([]);
  const [pageError, setPageError] = useState<string | null>(null);

  useEffect(() => {
    get<TallyMigrationCatalog>("/accounting/tally-migration/catalog")
      .then(setCatalog)
      .catch((err) => setPageError(getErrorMessage(err)));
  }, []);

  const loadTemplates = useCallback(async () => {
    try {
      const data = await get<{ items: TallyMappingTemplate[] }>(
        "/accounting/tally-migration/mappings",
      );
      setTemplates(data.items);
    } catch (err) {
      setPageError(getErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  const tabs = useMemo(
    () =>
      [
        { key: "import" as TabKey, label: "Import wizard", count: undefined },
        { key: "reports" as TabKey, label: "Historical reports" },
        { key: "opening" as TabKey, label: "Opening balances" },
        ...(isSeniorAccountant
          ? [{ key: "approvals" as TabKey, label: "Approvals" }]
          : []),
        { key: "history" as TabKey, label: "History" },
        { key: "mappings" as TabKey, label: "Mapping templates", count: templates.length },
      ],
    [isSeniorAccountant, templates.length],
  );

  if (clientsLoading) return <PageSkeleton cards={4} />;
  if (clientsError) return <ErrorState message={clientsError} onRetry={() => window.location.reload()} />;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Accounting practice"
        title="Tally Data Migration"
        description="Import historical Tally data by file, validate it without altering values, approve it as a senior, and review prior-year reports. FINOVEXA never connects to a Tally installation."
        actions={
          <Badge tone="violet" dot>
            File-based migration only
          </Badge>
        }
      />

      {pageError && <Callout tone="red" title="Migration workspace error">{pageError}</Callout>}

      <Tabs
        items={tabs}
        value={tab}
        onChange={setTab}
        className="rounded-xl border border-slate-200 bg-white px-2 py-1.5"
      />

      {tab === "import" && (
        <ImportTab
          clients={clients}
          clientId={clientId}
          onClientChange={setClientId}
          catalog={catalog}
          templates={templates}
          onTemplateSaved={() => void loadTemplates()}
          onGoToApprovals={() => setTab(isSeniorAccountant ? "approvals" : "history")}
          onGoToOpening={() => setTab("opening")}
        />
      )}
      {tab === "reports" && <ReportsTab clients={clients} clientId={clientId} onClientChange={setClientId} />}
      {tab === "opening" && <OpeningTab clients={clients} clientId={clientId} onClientChange={setClientId} />}
      {tab === "approvals" && isSeniorAccountant && <ApprovalsTab clients={clients} />}
      {tab === "history" && <HistoryTab clients={clients} />}
      {tab === "mappings" && (
        <MappingsTab clients={clients} catalog={catalog} templates={templates} onChanged={() => void loadTemplates()} />
      )}
    </div>
  );
}
