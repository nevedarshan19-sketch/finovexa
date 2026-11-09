import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileArchive,
  FileSpreadsheet,
  History,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { downloadFile, get, getErrorMessage, post } from "../../lib/api";
import { formatDateTime, money } from "../../lib/utils";
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
  Select,
  StatCard,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../ui";

interface ExportCategory {
  key: string;
  label: string;
}

interface ExportCatalog {
  business: { business_name: string; gstin: string | null; state: string | null; currency: string };
  categories: ExportCategory[];
  tally_versions: string[];
  tally_formats: string[];
  financial_years: string[];
  default_from: string;
  default_to: string;
  counts: Record<string, number>;
  note: string;
}

interface ReconciliationComparison {
  label: string;
  source_total: string;
  exported_total: string;
  difference: string;
  status: "matched" | "difference";
}

interface ReconciliationCheck {
  key: string;
  label: string;
  status: "passed" | "failed";
  detail: string;
}

interface ExportIssue {
  severity: "error" | "warning" | "review";
  code: string;
  message: string;
  category: string | null;
  reference: string | null;
}

interface ExportPreview {
  period: { from: string | null; to: string | null };
  counts: Record<string, number>;
  totals: Record<string, string>;
  tally: {
    voucher_count: number;
    debit_total: string;
    credit_total: string;
    balanced: boolean;
    by_type: { type: string; count: number }[];
  };
  issue_counts: { errors: number; warnings: number; review: number; total: number };
  missing_mappings: ExportIssue[];
  review: ExportIssue[];
  reconciliation: {
    comparisons: ReconciliationComparison[];
    checks: ReconciliationCheck[];
    debit_total: string;
    credit_total: string;
    balanced: boolean;
    gst: { output_source: string; output_exported: string; difference: string };
  };
  availability: string[][];
  import_claim: string;
}

interface ExportRecord {
  id: number;
  export_kind: string;
  category_labels: string[];
  period_from: string | null;
  period_to: string | null;
  filename: string;
  file_sha256: string | null;
  file_size: number;
  row_count: number;
  warning_count: number;
  error_count: number;
  status: string;
  created_by: string | null;
  created_at: string | null;
  details: Record<string, unknown>;
  download_url: string | null;
}

const KIND_LABELS: Record<string, string> = {
  workbook: "Complete data · 14-sheet Excel",
  tally_excel: "Tally export · Excel",
  tally_xml: "Tally export · XML pack",
};

function financialYearRange(fy: string): { from: string; to: string } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(fy);
  if (!match) return null;
  const start = Number(match[1]);
  return { from: `${start}-04-01`, to: `${start + 1}-03-31` };
}

function exportPath(clientId: number, suffix = ""): string {
  return `/accounting/clients/${clientId}/exports${suffix}`;
}

function relativeDownload(url: string): string {
  return url.replace(/^\/api/, "");
}

function bytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  if (size >= 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
}

export function ExportCentrePanel({ clientId }: { clientId: number }) {
  const [catalog, setCatalog] = useState<ExportCatalog | null>(null);
  const [history, setHistory] = useState<ExportRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [tallyFormat, setTallyFormat] = useState<"xlsx" | "xml">("xlsx");
  const [tallyVersion, setTallyVersion] = useState("TallyPrime 4.1");

  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [generating, setGenerating] = useState<"workbook" | "tally" | null>(null);
  const [created, setCreated] = useState<ExportRecord | null>(null);

  const loadHistory = useCallback(async () => {
    const data = await get<{ items: ExportRecord[] }>(exportPath(clientId));
    setHistory(data.items);
  }, [clientId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await get<ExportCatalog>(exportPath(clientId, "/catalog"));
      setCatalog(data);
      setFrom(data.default_from);
      setTo(data.default_to);
      setCategories(data.categories.map((row) => row.key));
      setTallyVersion(data.tally_versions[0] ?? "TallyPrime 4.1");
      await loadHistory();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [clientId, loadHistory]);

  useEffect(() => {
    void load();
  }, [load]);

  const payload = useMemo(
    () => ({ date_from: from || null, date_to: to || null, categories }),
    [from, to, categories],
  );

  const toggleCategory = (key: string, checked: boolean) => {
    setCategories((current) =>
      checked ? [...current, key] : current.filter((row) => row !== key),
    );
    setPreview(null);
  };

  const runPreview = async () => {
    setPreviewing(true);
    setActionError(null);
    try {
      setPreview(await post<ExportPreview>(exportPath(clientId, "/preview"), payload));
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setPreviewing(false);
    }
  };

  const generate = async (kind: "workbook" | "tally") => {
    setGenerating(kind);
    setActionError(null);
    try {
      const body =
        kind === "tally" ? { ...payload, file_format: tallyFormat, tally_version: tallyVersion } : payload;
      const record = await post<ExportRecord>(
        exportPath(clientId, kind === "tally" ? "/tally" : "/workbook"),
        body,
      );
      setCreated(record);
      await loadHistory();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setGenerating(null);
    }
  };

  const download = async (record: ExportRecord) => {
    if (!record.download_url) return;
    setActionError(null);
    try {
      await downloadFile(relativeDownload(record.download_url), record.filename);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  if (loading) {
    return (
      <Card>
        <CardBody>
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <RefreshCw className="h-4 w-4 animate-spin" /> Loading the export catalogue…
          </div>
        </CardBody>
      </Card>
    );
  }

  if (error || !catalog) {
    return <ErrorState message={error ?? "The export catalogue is unavailable."} onRetry={load} />;
  }

  const allSelected = categories.length === catalog.categories.length;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Export Centre"
          description={`Complete transaction history for ${catalog.business.business_name}${catalog.business.gstin ? ` · GSTIN ${catalog.business.gstin}` : ""}. Every file is built from stored records only; nothing is edited or posted.`}
        />
        <CardBody className="space-y-5">
          {actionError && (
            <Callout tone="red" title="That action did not complete">
              {actionError}
            </Callout>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Financial year" htmlFor="export_fy">
              <Select
                id="export_fy"
                value=""
                onChange={(event) => {
                  const range = financialYearRange(event.target.value);
                  if (range) {
                    setFrom(range.from);
                    setTo(range.to);
                    setPreview(null);
                  }
                }}
              >
                <option value="">Choose a year…</option>
                {catalog.financial_years.map((fy) => (
                  <option key={fy} value={fy}>
                    FY {fy}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="From" htmlFor="export_from">
              <Input
                id="export_from"
                type="date"
                value={from}
                onChange={(event) => {
                  setFrom(event.target.value);
                  setPreview(null);
                }}
              />
            </Field>
            <Field label="To" htmlFor="export_to">
              <Input
                id="export_to"
                type="date"
                value={to}
                onChange={(event) => {
                  setTo(event.target.value);
                  setPreview(null);
                }}
              />
            </Field>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[12px] font-semibold text-ink-900">Categories</p>
              <button
                type="button"
                className="text-[11px] font-semibold text-brand-600"
                onClick={() => {
                  setCategories(allSelected ? [] : catalog.categories.map((row) => row.key));
                  setPreview(null);
                }}
              >
                {allSelected ? "Clear all" : "Select all"}
              </button>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              {catalog.categories.map((row) => (
                <Checkbox
                  key={row.key}
                  label={row.label}
                  checked={categories.includes(row.key)}
                  onChange={(checked) => toggleCategory(row.key, checked)}
                />
              ))}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={runPreview} disabled={previewing || categories.length === 0}>
              <ShieldCheck className="h-4 w-4" />
              {previewing ? "Validating…" : "Preview and validate"}
            </Button>
            <Button onClick={() => void generate("workbook")} disabled={generating !== null || categories.length === 0}>
              <FileSpreadsheet className="h-4 w-4" />
              {generating === "workbook" ? "Building workbook…" : "Export complete data to Excel"}
            </Button>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
            <p className="text-[12px] font-semibold text-ink-900">Export for Tally</p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Generate a Tally-compatible workbook or an XML pack with masters, vouchers and a README.
              Import into a test company before using it in the books.
            </p>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <Field label="File format" htmlFor="tally_format">
                <Select
                  id="tally_format"
                  value={tallyFormat}
                  onChange={(event) => setTallyFormat(event.target.value as "xlsx" | "xml")}
                >
                  <option value="xlsx">Tally Excel workbook</option>
                  <option value="xml">Tally XML pack (.zip)</option>
                </Select>
              </Field>
              <Field label="Tally version" htmlFor="tally_version">
                <Select
                  id="tally_version"
                  value={tallyVersion}
                  onChange={(event) => setTallyVersion(event.target.value)}
                >
                  {catalog.tally_versions.map((version) => (
                    <option key={version} value={version}>
                      {version}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button variant="secondary" onClick={() => void generate("tally")} disabled={generating !== null || categories.length === 0}>
                <FileArchive className="h-4 w-4" />
                {generating === "tally" ? "Building export…" : "Export for Tally"}
              </Button>
            </div>
          </div>

          {created && (
            <Callout tone="green" title="Export ready">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-mono text-[11px]">{created.filename}</span>
                <Badge tone="green">{KIND_LABELS[created.export_kind] ?? created.export_kind}</Badge>
                <Button size="sm" variant="secondary" onClick={() => void download(created)}>
                  <Download className="h-3.5 w-3.5" /> Download
                </Button>
              </div>
              <p className="mt-1 text-[11px] text-slate-500">
                {created.row_count} row(s) · {created.warning_count} warning(s) · {created.error_count} error(s) · SHA-256{" "}
                {created.file_sha256?.slice(0, 12)}…
              </p>
            </Callout>
          )}
        </CardBody>
      </Card>

      {preview && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Tally vouchers" value={String(preview.tally.voucher_count)} sub="Unique transaction references" />
            <StatCard label="Debit total" value={money(preview.tally.debit_total)} sub="Sum of exported debits" />
            <StatCard label="Credit total" value={money(preview.tally.credit_total)} sub="Sum of exported credits" />
            <StatCard
              label="Balance"
              value={preview.tally.balanced ? "Balanced" : "Difference"}
              sub={preview.tally.balanced ? "Debit equals credit" : "Review the reconciliation below"}
            />
          </div>

          <Card>
            <CardHeader
              title="Validation and reconciliation"
              description="FINOVEXA totals are compared with the exported voucher totals. A difference is reported, never absorbed."
            />
            <CardBody className="space-y-4">
              <div className="space-y-2">
                {preview.reconciliation.checks.map((check) => (
                  <div key={check.key} className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-2">
                    {check.status === "passed" ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                    ) : (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
                    )}
                    <div className="min-w-0">
                      <p className="text-[12px] font-semibold text-ink-900">{check.label}</p>
                      <p className="text-[11px] text-slate-500">{check.detail}</p>
                    </div>
                    <Badge tone={check.status === "passed" ? "green" : "red"} className="ml-auto">
                      {check.status}
                    </Badge>
                  </div>
                ))}
              </div>

              <TableWrap>
                <THead>
                  <TR>
                    <TH>Category</TH>
                    <TH className="text-right">FINOVEXA total</TH>
                    <TH className="text-right">Exported total</TH>
                    <TH className="text-right">Difference</TH>
                    <TH>Status</TH>
                  </TR>
                </THead>
                <TBody>
                  {preview.reconciliation.comparisons.map((row) => (
                    <TR key={row.label}>
                      <TD>{row.label}</TD>
                      <TD className="text-right tabular">{money(row.source_total)}</TD>
                      <TD className="text-right tabular">{money(row.exported_total)}</TD>
                      <TD className="text-right tabular">{money(row.difference)}</TD>
                      <TD>
                        <Badge tone={row.status === "matched" ? "green" : "red"}>{row.status}</Badge>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 px-3 py-2">
                  <p className="text-[11px] font-semibold text-slate-500">Output GST</p>
                  <p className="text-[13px] text-ink-900">
                    Source {money(preview.reconciliation.gst.output_source)} · Exported{" "}
                    {money(preview.reconciliation.gst.output_exported)} · Difference{" "}
                    {money(preview.reconciliation.gst.difference)}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 px-3 py-2">
                  <p className="text-[11px] font-semibold text-slate-500">Records requiring review</p>
                  <p className="text-[13px] text-ink-900">
                    {preview.issue_counts.errors} error(s) · {preview.issue_counts.warnings} warning(s) ·{" "}
                    {preview.issue_counts.review} review item(s)
                  </p>
                </div>
              </div>
            </CardBody>
          </Card>

          {(preview.missing_mappings.length > 0 || preview.review.length > 0) && (
            <Card>
              <CardHeader
                title="Records that need attention"
                description="These rows are included where possible and flagged here. Nothing is skipped silently."
              />
              <CardBody className="space-y-2">
                {[...preview.missing_mappings, ...preview.review].slice(0, 40).map((issue, index) => (
                  <div key={`${issue.code}-${issue.reference ?? index}`} className="flex items-start gap-2 border-b border-slate-100 pb-2 last:border-0">
                    <Badge tone={issue.severity === "error" ? "red" : issue.severity === "warning" ? "amber" : "violet"}>
                      {issue.severity}
                    </Badge>
                    <div className="min-w-0">
                      <p className="text-[12px] text-ink-900">{issue.message}</p>
                      <p className="text-[10px] text-slate-500">
                        {issue.code}
                        {issue.reference ? ` · ${issue.reference}` : ""}
                      </p>
                    </div>
                  </div>
                ))}
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="Data availability in this export" description="A worksheet is never filled with invented figures." />
            <CardBody>
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Worksheet</TH>
                    <TH>Status</TH>
                    <TH>Note</TH>
                  </TR>
                </THead>
                <TBody>
                  {preview.availability.map((row) => (
                    <TR key={row[0]}>
                      <TD>{row[0]}</TD>
                      <TD>
                        <Badge tone={row[1] === "Available" ? "green" : row[1] === "Not recorded" ? "slate" : "amber"}>
                          {row[1]}
                        </Badge>
                      </TD>
                      <TD className="text-[11px] text-slate-500">{row[2]}</TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            </CardBody>
          </Card>

          <Callout tone="amber" title="Tally import status">
            {preview.import_claim}
          </Callout>
        </>
      )}

      <Card>
        <CardHeader
          title="Export history"
          description="Every generated file is recorded with a SHA-256 hash and an audit entry."
          actions={
            <Button size="sm" variant="ghost" onClick={() => void loadHistory()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </Button>
          }
        />
        <CardBody>
          {history.length === 0 ? (
            <EmptyState
              icon={History}
              title="No exports yet"
              description="Preview the export, then generate the complete Excel workbook or a Tally file."
            />
          ) : (
            <div className="space-y-2">
              {history.map((record) => (
                <div key={record.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-semibold text-ink-900">{record.filename}</p>
                    <p className="text-[11px] text-slate-500">
                      {KIND_LABELS[record.export_kind] ?? record.export_kind} · {record.row_count} row(s) ·{" "}
                      {bytes(record.file_size)}
                      {record.period_from ? ` · ${record.period_from} to ${record.period_to}` : ""}
                      {record.created_at ? ` · ${formatDateTime(record.created_at)}` : ""}
                      {record.created_by ? ` · ${record.created_by}` : ""}
                    </p>
                  </div>
                  {record.error_count > 0 && <Badge tone="red">{record.error_count} error(s)</Badge>}
                  {record.warning_count > 0 && <Badge tone="amber">{record.warning_count} warning(s)</Badge>}
                  <Button size="sm" variant="secondary" onClick={() => void download(record)} disabled={!record.download_url}>
                    <Download className="h-3.5 w-3.5" /> Download
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
