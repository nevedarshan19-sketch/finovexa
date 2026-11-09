import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  FileSpreadsheet,
  FileText,
  FlaskConical,
  Landmark,
  Plus,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { get, getErrorMessage, post } from "../../lib/api";
import type {
  AccountingClient,
  AccountingReport,
  AccountingVoucher,
  BankImport,
  BillExtract,
  GstWorking,
  TallyBatch,
  VoucherListResponse,
} from "../../lib/accountingTypes";
import type { AccountingServiceKey } from "../../lib/accountingTypes";
import {
  PAYMENT_METHODS,
  VOUCHER_TYPES,
  downloadText,
  fileToDataUrl,
  formatBytes,
  labelize,
  parseCsv,
  readTextFile,
  statusTone,
} from "../../lib/accounting";
import { formatDate, formatDateTime, money, moneyExact } from "../../lib/utils";
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
  Modal,
  PageHeader,
  PageSkeleton,
  Select,
  Tabs,
  Textarea,
} from "../../components/ui";
import { StatusBadge } from "../../components/accounting/AccountingUI";

type WorkTab = "vouchers" | "bill" | "bank" | "gst" | "tally" | "reports";

const REPORT_TYPES = [
  { key: "monthly_summary", label: "Monthly summary" },
  { key: "gstr1", label: "GSTR-1 working" },
  { key: "gstr3b", label: "GSTR-3B working" },
  { key: "financials", label: "Draft financials" },
];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

function currentFinancialYear(): string {
  const now = new Date();
  const start = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

function monthStart(): string {
  return `${currentMonth()}-01`;
}

function monthEnd(): string {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return end.toISOString().slice(0, 10);
}

const emptyVoucher = {
  voucher_type: "sale" as "sale" | "purchase" | "journal" | "payment",
  number: "",
  voucher_date: today(),
  party_name: "",
  party_gstin: "",
  ledger_name: "",
  category: "",
  description: "",
  taxable_value: "",
  gst_rate: "18",
  inter_state: false,
};

export function AccountantWorkPage() {
  const { isSeniorAccountant } = useAuth();
  const [params] = useSearchParams();
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [clientId, setClientId] = useState<number | null>(() => {
    const value = Number(params.get("clientId"));
    return Number.isFinite(value) && value > 0 ? value : null;
  });
  const [tab, setTab] = useState<WorkTab>("vouchers");
  const [loadingClients, setLoadingClients] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [voucherList, setVoucherList] = useState<VoucherListResponse | null>(null);
  const [voucherFilters, setVoucherFilters] = useState({ from: monthStart(), to: monthEnd(), type: "" });
  const [voucher, setVoucher] = useState(emptyVoucher);

  const [billFile, setBillFile] = useState<File | null>(null);
  const [bill, setBill] = useState<BillExtract | null>(null);
  const [billForm, setBillForm] = useState({
    voucher_type: "purchase" as "sale" | "purchase",
    number: "",
    voucher_date: today(),
    party_name: "",
    ledger_name: "",
    taxable_value: "",
    gst_rate: "18",
    inter_state: false,
  });

  const [bankImports, setBankImports] = useState<BankImport[]>([]);
  const [activeImportId, setActiveImportId] = useState<number | null>(null);
  const [bankFile, setBankFile] = useState<File | null>(null);

  const [gstPeriod, setGstPeriod] = useState(currentMonth());
  const [gst, setGst] = useState<GstWorking | null>(null);

  const [tallyFile, setTallyFile] = useState<File | null>(null);
  const [tallyBatches, setTallyBatches] = useState<TallyBatch[]>([]);
  const [tallyRange, setTallyRange] = useState({
    from_date: monthStart(),
    to_date: monthEnd(),
    voucher_type: "all",
  });

  const [reports, setReports] = useState<AccountingReport[]>([]);
  const [reportDetail, setReportDetail] = useState<AccountingReport | null>(null);
  const [reportForm, setReportForm] = useState({
    report_type: "monthly_summary",
    financial_year: currentFinancialYear(),
    period: currentMonth(),
  });
  const [reportReviewNote, setReportReviewNote] = useState("");

  const loadClients = useCallback(async () => {
    setLoadingClients(true);
    setError(null);
    try {
      const path = isSeniorAccountant ? "/accounting/senior/clients" : "/accounting/junior/clients";
      const data = await get<{ items: AccountingClient[] }>(path);
      setClients(data.items);
      setClientId((current) => current ?? data.items[0]?.id ?? null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoadingClients(false);
    }
  }, [isSeniorAccountant]);

  useEffect(() => {
    void loadClients();
  }, [loadClients]);

  const loadVouchers = useCallback(async () => {
    if (!clientId) return;
    try {
      const query = new URLSearchParams({ client_id: String(clientId) });
      if (voucherFilters.from) query.set("from_date", voucherFilters.from);
      if (voucherFilters.to) query.set("to_date", voucherFilters.to);
      if (voucherFilters.type) query.set("voucher_type", voucherFilters.type);
      setVoucherList(await get<VoucherListResponse>(`/accounting/vouchers?${query.toString()}`));
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [clientId, voucherFilters]);

  const loadBankImports = useCallback(async () => {
    if (!clientId) return;
    try {
      const data = await get<{ items: BankImport[] }>(`/accounting/bank/imports?client_id=${clientId}`);
      setBankImports(data.items);
      setActiveImportId((current) => current ?? data.items[0]?.id ?? null);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [clientId]);

  const loadTallyBatches = useCallback(async () => {
    if (!clientId) return;
    try {
      const data = await get<{ items: TallyBatch[] }>(`/accounting/tally/batches?client_id=${clientId}`);
      setTallyBatches(data.items);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [clientId]);

  const loadReports = useCallback(async () => {
    if (!clientId || !isSeniorAccountant) return;
    try {
      const data = await get<{ items: AccountingReport[] }>(
        `/accounting/senior/reports?client_id=${clientId}`,
      );
      setReports(data.items);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [clientId, isSeniorAccountant]);

  useEffect(() => {
    if (!clientId) return;
    setBill(null);
    setBillFile(null);
    setGst(null);
    setVoucherList(null);
    setBankImports([]);
    setActiveImportId(null);
    setTallyBatches([]);
    setReports([]);
    void loadVouchers();
    void loadBankImports();
    void loadTallyBatches();
    void loadReports();
  }, [clientId, loadVouchers, loadBankImports, loadTallyBatches, loadReports]);

  const client = clients.find((row) => row.id === clientId) || null;
  const activeImport = bankImports.find((row) => row.id === activeImportId) || null;

  const postVoucher = async () => {
    if (!clientId) return;
    setBusy(true);
    setActionError(null);
    try {
      await post<AccountingVoucher>("/accounting/vouchers", {
        client_id: clientId,
        voucher_type: voucher.voucher_type,
        number: voucher.number,
        voucher_date: voucher.voucher_date,
        party_name: voucher.party_name,
        party_gstin: voucher.party_gstin || null,
        ledger_name: voucher.ledger_name,
        category: voucher.category || null,
        description: voucher.description || null,
        taxable_value: voucher.taxable_value,
        gst_rate: voucher.gst_rate,
        inter_state: voucher.inter_state,
      });
      setVoucher({ ...emptyVoucher, voucher_date: today() });
      await loadVouchers();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const importVoucherCsv = async (file: File) => {
    if (!clientId) return;
    setBusy(true);
    setActionError(null);
    try {
      const text = await readTextFile(file);
      const rows = parseCsv(text).map((row) => ({
        voucher_type: (row.voucher_type || "sale").toLowerCase(),
        number: row.number || row.voucher_number || "",
        voucher_date: row.voucher_date || row.date || "",
        party_name: row.party_name || "",
        party_gstin: row.party_gstin || null,
        ledger_name: row.ledger_name || "",
        category: row.category || null,
        description: row.description || null,
        taxable_value: row.taxable_value || row.amount || "0",
        gst_rate: row.gst_rate || "0",
        inter_state: ["true", "1", "yes", "y"].includes((row.inter_state || "").toLowerCase()),
      }));
      if (rows.length === 0) {
        throw new Error("No data rows were found. Use the template header row.");
      }
      const result = await post<{ created: AccountingVoucher[]; duplicate_numbers: string[]; errors: unknown[] }>(
        "/accounting/vouchers/bulk",
        { client_id: clientId, rows },
      );
      setActionError(
        `Imported ${result.created.length} voucher${result.created.length === 1 ? "" : "s"}. ` +
          `${result.duplicate_numbers.length} duplicate${result.duplicate_numbers.length === 1 ? "" : "s"}, ` +
          `${result.errors.length} row error${result.errors.length === 1 ? "" : "s"}.`,
      );
      await loadVouchers();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const extractBill = async () => {
    if (!clientId || !billFile) return;
    setBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(billFile);
      const result = await post<BillExtract>("/accounting/bills/extract", {
        client_id: clientId,
        filename: billFile.name,
        data_url: dataUrl,
      });
      setBill(result);
      setBillForm({
        voucher_type: "purchase",
        number: result.fields.invoice_number || "",
        voucher_date: result.fields.invoice_date || today(),
        party_name: "",
        ledger_name: result.fields.suggested_ledger || "",
        taxable_value: result.fields.taxable_value != null ? String(result.fields.taxable_value) : "",
        gst_rate: result.fields.gst_rate != null ? String(result.fields.gst_rate) : "18",
        inter_state: Boolean(result.fields.party_gstin),
      });
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const saveBillVoucher = async () => {
    if (!clientId || !bill) return;
    setBusy(true);
    setActionError(null);
    try {
      await post<AccountingVoucher>("/accounting/vouchers", {
        client_id: clientId,
        voucher_type: billForm.voucher_type,
        number: billForm.number,
        voucher_date: billForm.voucher_date,
        party_name: billForm.party_name,
        party_gstin: bill.fields.party_gstin || null,
        ledger_name: billForm.ledger_name,
        taxable_value: billForm.taxable_value,
        gst_rate: billForm.gst_rate,
        inter_state: billForm.inter_state,
      });
      setBill(null);
      setBillFile(null);
      await loadVouchers();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const importBank = async () => {
    if (!clientId || !bankFile) return;
    setBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(bankFile);
      const record = await post<BankImport>("/accounting/bank/import", {
        client_id: clientId,
        filename: bankFile.name,
        data_url: dataUrl,
      });
      setBankFile(null);
      await loadBankImports();
      setActiveImportId(record.id);
      await loadVouchers();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const confirmMatch = async (transactionId: number, voucherId: number | null) => {
    setActionError(null);
    try {
      await post(`/accounting/bank/transactions/${transactionId}/match`, {
        voucher_id: voucherId,
        note: voucherId ? "Confirmed by accountant." : "Match cleared by the accountant.",
      });
      await loadBankImports();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const prepareGst = async () => {
    if (!clientId) return;
    setBusy(true);
    setActionError(null);
    try {
      setGst(await post<GstWorking>("/accounting/gst/prepare", { client_id: clientId, period: gstPeriod }));
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const importTally = async () => {
    if (!clientId || !tallyFile) return;
    setBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(tallyFile);
      const batch = await post<TallyBatch>("/accounting/tally/import", {
        client_id: clientId,
        filename: tallyFile.name,
        data_url: dataUrl,
      });
      setTallyFile(null);
      await loadTallyBatches();
      await loadVouchers();
      setActionError(
        `Tally import ${batch.filename}: ${batch.valid_count} valid, ${batch.duplicate_count} duplicates, ${batch.error_count} errors.`,
      );
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const exportTally = async () => {
    if (!clientId) return;
    setBusy(true);
    setActionError(null);
    try {
      const csv = await post<string>("/accounting/tally/export", {
        client_id: clientId,
        from_date: tallyRange.from_date,
        to_date: tallyRange.to_date,
        voucher_type: tallyRange.voucher_type,
      });
      downloadText(`tally-export-${tallyRange.from_date}.csv`, csv, "text/csv;charset=utf-8");
      await loadTallyBatches();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const createReport = async () => {
    if (!clientId) return;
    setBusy(true);
    setActionError(null);
    try {
      const report = await post<AccountingReport>("/accounting/reports", {
        client_id: clientId,
        report_type: reportForm.report_type,
        financial_year: reportForm.financial_year,
        period: reportForm.period,
      });
      setReportDetail(report);
      if (isSeniorAccountant) {
        await loadReports();
      } else {
        setReports((rows) => [report, ...rows.filter((row) => row.id !== report.id)]);
      }
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openReport = async (report: AccountingReport) => {
    setActionError(null);
    setReportReviewNote(report.review_notes || "");
    try {
      setReportDetail(await get<AccountingReport>(`/accounting/reports/${report.id}`));
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const reviewReport = async (decision: "approve" | "changes_requested") => {
    if (!reportDetail) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await post<AccountingReport>(
        `/accounting/senior/reports/${reportDetail.id}/review`,
        { decision, notes: reportReviewNote || null },
      );
      setReportDetail(await get<AccountingReport>(`/accounting/reports/${updated.id}`));
      await loadReports();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const deliverReport = async () => {
    if (!reportDetail) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/senior/reports/${reportDetail.id}/deliver`);
      setReportDetail(await get<AccountingReport>(`/accounting/reports/${reportDetail.id}`));
      await loadReports();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const tabs: { key: WorkTab; label: string }[] = [
    { key: "vouchers", label: "Vouchers" },
    { key: "bill", label: "Bill reader" },
    { key: "bank", label: "Bank reconciliation" },
    { key: "gst", label: "GST working" },
    { key: "tally", label: "Tally" },
    { key: "reports", label: "Reports" },
  ];

  const reportPayload = useMemo<Record<string, unknown> | null>(() => {
    if (!reportDetail?.payload) return null;
    return reportDetail.payload as Record<string, unknown>;
  }, [reportDetail]);

  if (loadingClients) return <PageSkeleton cards={3} />;
  if (error) return <ErrorState message={error} onRetry={loadClients} />;
  if (clients.length === 0)
    return (
      <Card>
        <EmptyState
          title="No clients available"
          description="A senior accountant must assign a client before accounting work can start."
          icon={FlaskConical}
        />
      </Card>
    );

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Accounting workbench"
        title={client ? `${client.business_name} · ${client.code}` : "Workbench"}
        description="Post vouchers, extract bills, reconcile the bank, prepare GST workings and build reports for senior review."
        actions={
          <Select
            aria-label="Select client"
            value={clientId ?? ""}
            onChange={(event) => setClientId(Number(event.target.value))}
            className="min-w-[240px]"
          >
            {clients.map((row) => (
              <option key={row.id} value={row.id}>
                {row.business_name} · {row.code}
              </option>
            ))}
          </Select>
        }
      />

      {actionError && (
        <Callout tone="blue" title="Workbench message">
          {actionError}
        </Callout>
      )}

      <Tabs items={tabs} value={tab} onChange={setTab} />

      {tab === "vouchers" && (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_1fr]">
            <Card>
              <CardHeader title="Post a voucher" description="Sales, purchases, journals and payments." icon={Plus} />
              <CardBody className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Type" htmlFor="voucher_type">
                    <Select
                      id="voucher_type"
                      value={voucher.voucher_type}
                      onChange={(event) =>
                        setVoucher({ ...voucher, voucher_type: event.target.value as typeof voucher.voucher_type })
                      }
                    >
                      {VOUCHER_TYPES.map((value) => (
                        <option key={value} value={value}>
                          {labelize(value)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Number" htmlFor="voucher_number" required>
                    <Input
                      id="voucher_number"
                      value={voucher.number}
                      onChange={(event) => setVoucher({ ...voucher, number: event.target.value })}
                      placeholder="INV-1042"
                    />
                  </Field>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Date" htmlFor="voucher_date" required>
                    <Input
                      id="voucher_date"
                      type="date"
                      value={voucher.voucher_date}
                      onChange={(event) => setVoucher({ ...voucher, voucher_date: event.target.value })}
                    />
                  </Field>
                  <Field label="GST rate %" htmlFor="voucher_gst_rate">
                    <Input
                      id="voucher_gst_rate"
                      type="number"
                      min="0"
                      max="28"
                      step="0.01"
                      value={voucher.gst_rate}
                      onChange={(event) => setVoucher({ ...voucher, gst_rate: event.target.value })}
                    />
                  </Field>
                </div>
                <Field label="Party" htmlFor="voucher_party" required>
                  <Input
                    id="voucher_party"
                    value={voucher.party_name}
                    onChange={(event) => setVoucher({ ...voucher, party_name: event.target.value })}
                    placeholder="Customer or vendor"
                  />
                </Field>
                <Field label="Party GSTIN" htmlFor="voucher_party_gstin">
                  <Input
                    id="voucher_party_gstin"
                    value={voucher.party_gstin}
                    onChange={(event) => setVoucher({ ...voucher, party_gstin: event.target.value.toUpperCase() })}
                    maxLength={15}
                  />
                </Field>
                <Field label="Ledger" htmlFor="voucher_ledger" required>
                  <Input
                    id="voucher_ledger"
                    value={voucher.ledger_name}
                    onChange={(event) => setVoucher({ ...voucher, ledger_name: event.target.value })}
                    placeholder="Sales / Office expenses"
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Taxable value" htmlFor="voucher_value" required>
                    <Input
                      id="voucher_value"
                      type="number"
                      min="0"
                      step="0.01"
                      value={voucher.taxable_value}
                      onChange={(event) => setVoucher({ ...voucher, taxable_value: event.target.value })}
                    />
                  </Field>
                  <Field label="Category" htmlFor="voucher_category">
                    <Input
                      id="voucher_category"
                      value={voucher.category}
                      onChange={(event) => setVoucher({ ...voucher, category: event.target.value })}
                    />
                  </Field>
                </div>
                <label className="flex items-center gap-2 text-[12px] text-slate-600">
                  <input
                    type="checkbox"
                    checked={voucher.inter_state}
                    onChange={(event) => setVoucher({ ...voucher, inter_state: event.target.checked })}
                    className="h-4 w-4 rounded border-slate-300 accent-brand-500"
                  />
                  Inter-state supply (IGST)
                </label>
                <Field label="Description" htmlFor="voucher_description">
                  <Textarea
                    id="voucher_description"
                    value={voucher.description}
                    onChange={(event) => setVoucher({ ...voucher, description: event.target.value })}
                    className="min-h-[60px]"
                  />
                </Field>
                <Button
                  loading={busy}
                  onClick={postVoucher}
                  disabled={
                    !voucher.number ||
                    !voucher.party_name ||
                    !voucher.ledger_name ||
                    !voucher.taxable_value
                  }
                  className="w-full"
                >
                  Post voucher
                </Button>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Voucher register"
                description="Recorded vouchers for this client. Duplicate numbers with the same date and amount are rejected."
                icon={FileSpreadsheet}
                actions={
                  <>
                    <Button size="sm" variant="outline" onClick={() => void loadVouchers()} icon={RefreshCw}>
                      Refresh
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        downloadText(
                          "voucher-import-template.csv",
                          "voucher_type,number,voucher_date,party_name,party_gstin,ledger_name,category,description,taxable_value,gst_rate,inter_state\nsale,INV-1001,2026-04-01,Acme Traders,27ABCDE1234F1Z5,Sales,,Goods sold,10000,18,false\n",
                        )
                      }
                    >
                      Template
                    </Button>
                    <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-slate-600 hover:border-slate-300">
                      <Upload className="h-3.5 w-3.5" />
                      Import CSV
                      <input
                        type="file"
                        accept=".csv,text/csv"
                        className="hidden"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) void importVoucherCsv(file);
                          event.target.value = "";
                        }}
                      />
                    </label>
                  </>
                }
              />
              <CardBody className="space-y-3">
                <div className="grid gap-2 sm:grid-cols-4">
                  <Field label="From" htmlFor="voucher_from">
                    <Input
                      id="voucher_from"
                      type="date"
                      value={voucherFilters.from}
                      onChange={(event) => setVoucherFilters({ ...voucherFilters, from: event.target.value })}
                    />
                  </Field>
                  <Field label="To" htmlFor="voucher_to">
                    <Input
                      id="voucher_to"
                      type="date"
                      value={voucherFilters.to}
                      onChange={(event) => setVoucherFilters({ ...voucherFilters, to: event.target.value })}
                    />
                  </Field>
                  <Field label="Type" htmlFor="voucher_type_filter">
                    <Select
                      id="voucher_type_filter"
                      value={voucherFilters.type}
                      onChange={(event) => setVoucherFilters({ ...voucherFilters, type: event.target.value })}
                    >
                      <option value="">All</option>
                      {VOUCHER_TYPES.map((value) => (
                        <option key={value} value={value}>
                          {labelize(value)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <div className="flex items-end">
                    <Button variant="outline" className="w-full" onClick={() => void loadVouchers()}>
                      Apply
                    </Button>
                  </div>
                </div>

                {voucherList && (
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {[
                      { label: "Sales", value: money(voucherList.totals.sales) },
                      { label: "Purchases", value: money(voucherList.totals.purchases) },
                      { label: "Output GST", value: money(voucherList.totals.gst_output) },
                      { label: "Input GST", value: money(voucherList.totals.gst_input) },
                    ].map((item) => (
                      <div key={item.label} className="rounded-lg border border-slate-200 px-3 py-2">
                        <p className="text-[10px] uppercase tracking-wide text-slate-400">{item.label}</p>
                        <p className="mt-0.5 text-[13px] font-semibold tabular text-ink-900">{item.value}</p>
                      </div>
                    ))}
                  </div>
                )}

                {!voucherList ? (
                  <p className="text-[11px] text-slate-500">Loading vouchers…</p>
                ) : voucherList.items.length === 0 ? (
                  <EmptyState title="No vouchers in this range" description="Post a voucher or import a CSV." icon={FileSpreadsheet} />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] border-collapse">
                      <thead>
                        <tr>
                          <th className="table-head">Voucher</th>
                          <th className="table-head">Party</th>
                          <th className="table-head">Ledger</th>
                          <th className="table-head">Taxable</th>
                          <th className="table-head">GST</th>
                          <th className="table-head">Total</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {voucherList.items.map((row) => (
                          <tr key={row.id} className="row-hover">
                            <td className="table-cell">
                              <p className="text-[12px] font-semibold text-ink-900">{row.number}</p>
                              <p className="text-[10px] text-slate-500">
                                {labelize(row.voucher_type)} · {formatDate(row.voucher_date)}
                              </p>
                            </td>
                            <td className="table-cell text-[11px] text-slate-600">{row.party_name}</td>
                            <td className="table-cell text-[11px] text-slate-600">{row.ledger_name}</td>
                            <td className="table-cell tabular text-[11px]">{money(row.taxable_value)}</td>
                            <td className="table-cell tabular text-[11px]">
                              {money(row.cgst_amount + row.sgst_amount + row.igst_amount)}
                            </td>
                            <td className="table-cell tabular text-[11px] font-semibold">{money(row.total_amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardBody>
            </Card>
          </div>
        </div>
      )}

      {tab === "bill" && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_1fr]">
          <Card>
            <CardHeader
              title="Bill reader"
              description="Rule-based extraction from PDF text or CSV rows. Images are not OCR'd."
              icon={ScanLine}
            />
            <CardBody className="space-y-3">
              <Field label="Bill file" htmlFor="bill_file">
                <input
                  id="bill_file"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.csv"
                  onChange={(event) => setBillFile(event.target.files?.[0] || null)}
                  className="block w-full text-xs text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-brand-700"
                />
              </Field>
              {billFile && <p className="text-[10px] text-slate-400">{billFile.name} · {formatBytes(billFile.size)}</p>}
              <Button icon={ScanLine} loading={busy} onClick={extractBill} disabled={!billFile} className="w-full">
                Extract fields
              </Button>
              <Callout tone="amber" title="Human verification required">
                Nothing is saved automatically. Review every field, correct it, then post the voucher yourself.
              </Callout>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Extracted fields"
              description={bill ? `${bill.filename} · ${bill.note}` : "Upload a bill to extract candidate fields."}
              icon={FileText}
            />
            <CardBody>
              {!bill ? (
                <EmptyState title="No bill loaded" description="Upload a PDF or CSV bill to read its fields." icon={ScanLine} />
              ) : (
                <div className="space-y-4">
                  {bill.warnings.length > 0 && (
                    <Callout tone="amber" title="Check these before saving">
                      <ul className="list-disc pl-4">
                        {bill.warnings.map((warning) => (
                          <li key={warning}>{warning}</li>
                        ))}
                      </ul>
                    </Callout>
                  )}
                  {bill.source_text_preview && (
                    <div className="max-h-32 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2 font-mono text-[10px] leading-relaxed text-slate-500">
                      {bill.source_text_preview}
                    </div>
                  )}
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Voucher type" htmlFor="bill_voucher_type">
                      <Select
                        id="bill_voucher_type"
                        value={billForm.voucher_type}
                        onChange={(event) =>
                          setBillForm({ ...billForm, voucher_type: event.target.value as typeof billForm.voucher_type })
                        }
                      >
                        <option value="purchase">Purchase</option>
                        <option value="sale">Sale</option>
                      </Select>
                    </Field>
                    <Field label="Voucher number" htmlFor="bill_number" required>
                      <Input
                        id="bill_number"
                        value={billForm.number}
                        onChange={(event) => setBillForm({ ...billForm, number: event.target.value })}
                      />
                    </Field>
                    <Field label="Date" htmlFor="bill_date" required>
                      <Input
                        id="bill_date"
                        type="date"
                        value={billForm.voucher_date}
                        onChange={(event) => setBillForm({ ...billForm, voucher_date: event.target.value })}
                      />
                    </Field>
                    <Field label="Party name" htmlFor="bill_party" required>
                      <Input
                        id="bill_party"
                        value={billForm.party_name}
                        onChange={(event) => setBillForm({ ...billForm, party_name: event.target.value })}
                        placeholder="Vendor or customer"
                      />
                    </Field>
                    <Field label="Party GSTIN" htmlFor="bill_gstin">
                      <Input id="bill_gstin" value={bill.fields.party_gstin || ""} readOnly />
                    </Field>
                    <Field label="Ledger" htmlFor="bill_ledger" required>
                      <Input
                        id="bill_ledger"
                        value={billForm.ledger_name}
                        onChange={(event) => setBillForm({ ...billForm, ledger_name: event.target.value })}
                      />
                    </Field>
                    <Field label="Taxable value" htmlFor="bill_value" required>
                      <Input
                        id="bill_value"
                        type="number"
                        min="0"
                        step="0.01"
                        value={billForm.taxable_value}
                        onChange={(event) => setBillForm({ ...billForm, taxable_value: event.target.value })}
                      />
                    </Field>
                    <Field label="GST rate %" htmlFor="bill_rate">
                      <Input
                        id="bill_rate"
                        type="number"
                        min="0"
                        max="28"
                        step="0.01"
                        value={billForm.gst_rate}
                        onChange={(event) => setBillForm({ ...billForm, gst_rate: event.target.value })}
                      />
                    </Field>
                  </div>
                  <label className="flex items-center gap-2 text-[12px] text-slate-600">
                    <input
                      type="checkbox"
                      checked={billForm.inter_state}
                      onChange={(event) => setBillForm({ ...billForm, inter_state: event.target.checked })}
                      className="h-4 w-4 rounded border-slate-300 accent-brand-500"
                    />
                    Inter-state supply (IGST)
                  </label>
                  <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2">
                    <span className="text-[11px] text-slate-500">
                      Candidate total: {money(bill.fields.total_amount)} · confidence{" "}
                      {bill.fields.confidence?.total_amount || "low"}
                    </span>
                    <Button
                      icon={ShieldCheck}
                      loading={busy}
                      onClick={saveBillVoucher}
                      disabled={!billForm.number || !billForm.party_name || !billForm.ledger_name || !billForm.taxable_value}
                    >
                      Save verified voucher
                    </Button>
                  </div>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {tab === "bank" && (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Import a bank statement"
              description="CSV or Excel with date, description and debit or credit columns. Matches remain suggestions until you confirm them."
              icon={Landmark}
            />
            <CardBody className="flex flex-wrap items-end gap-3">
              <Field label="Statement file" htmlFor="bank_file" className="min-w-[260px] flex-1">
                <input
                  id="bank_file"
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={(event) => setBankFile(event.target.files?.[0] || null)}
                  className="block w-full text-xs text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-brand-700"
                />
              </Field>
              <Button icon={Upload} loading={busy} onClick={importBank} disabled={!bankFile}>
                Import statement
              </Button>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Reconciliation"
              description="Confirm a suggested voucher match, or clear it. Nothing is reconciled automatically."
              icon={Landmark}
              actions={
                <Select
                  aria-label="Statement import"
                  value={activeImportId ?? ""}
                  onChange={(event) => setActiveImportId(event.target.value ? Number(event.target.value) : null)}
                  className="min-w-[220px]"
                >
                  {bankImports.length === 0 && <option value="">No imports</option>}
                  {bankImports.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.filename} · {formatDate(row.created_at)}
                    </option>
                  ))}
                </Select>
              }
            />
            <CardBody>
              {!activeImport ? (
                <EmptyState title="No statement imported" description="Upload a bank statement to start reconciliation." icon={Landmark} />
              ) : (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
                    <Badge tone="slate">{activeImport.row_count} rows</Badge>
                    <Badge tone="green">{activeImport.matched_count} confirmed</Badge>
                    <StatusBadge status={activeImport.status} />
                    <span>{activeImport.note}</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[860px] border-collapse">
                      <thead>
                        <tr>
                          <th className="table-head">Date</th>
                          <th className="table-head">Description</th>
                          <th className="table-head">Debit</th>
                          <th className="table-head">Credit</th>
                          <th className="table-head">Status</th>
                          <th className="table-head">Confirm match</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {activeImport.transactions.map((txn) => (
                          <tr key={txn.id} className="row-hover">
                            <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">{formatDate(txn.txn_date)}</td>
                            <td className="table-cell max-w-[280px]">
                              <p className="truncate text-[11px] font-medium text-slate-700">{txn.description}</p>
                              {txn.match_note && <p className="text-[10px] text-slate-400">{txn.match_note}</p>}
                            </td>
                            <td className="table-cell tabular text-[11px]">{txn.debit ? money(txn.debit) : "—"}</td>
                            <td className="table-cell tabular text-[11px]">{txn.credit ? money(txn.credit) : "—"}</td>
                            <td className="table-cell">
                              <div className="flex items-center gap-1.5">
                                <StatusBadge status={txn.status} />
                                {txn.match_score != null && txn.status === "suggested" && (
                                  <span className="text-[10px] text-slate-400">{txn.match_score}%</span>
                                )}
                              </div>
                            </td>
                            <td className="table-cell">
                              <div className="flex items-center gap-1.5">
                                <Select
                                  aria-label={`Match transaction ${txn.id}`}
                                  value={txn.matched_voucher_id ?? ""}
                                  onChange={(event) =>
                                    void confirmMatch(txn.id, event.target.value ? Number(event.target.value) : null)
                                  }
                                  className="h-8 min-w-[150px] text-[11px]"
                                >
                                  <option value="">Not matched</option>
                                  {(voucherList?.items || []).map((row) => (
                                    <option key={row.id} value={row.id}>
                                      {row.number} · {money(row.total_amount)}
                                    </option>
                                  ))}
                                </Select>
                                {txn.status === "matched" && (
                                  <Button size="sm" variant="ghost" onClick={() => void confirmMatch(txn.id, null)}>
                                    Clear
                                  </Button>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {tab === "gst" && (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="GST working papers"
              description="Computed from posted vouchers. These are working papers for review, not a filed return."
              icon={FileText}
            />
            <CardBody className="flex flex-wrap items-end gap-3">
              <Field label="GST period" htmlFor="gst_period" className="w-48">
                <Input id="gst_period" type="month" value={gstPeriod} onChange={(event) => setGstPeriod(event.target.value)} />
              </Field>
              <Button loading={busy} onClick={prepareGst}>
                Prepare working
              </Button>
              {gst && (
                <span className="text-[11px] text-slate-500">
                  {gst.voucher_count} vouchers · {formatDate(gst.period_start)} to {formatDate(gst.period_end)}
                </span>
              )}
            </CardBody>
          </Card>

          {!gst ? (
            <Card>
              <EmptyState title="No working prepared" description="Choose a period and prepare the GST working paper." icon={FileText} />
            </Card>
          ) : (
            <>
              <Callout tone="amber" title="Working paper only">
                {gst.filing_note}
              </Callout>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  { label: "Output tax", value: money(gst.summary.output_tax), tone: "text-ink-900" },
                  { label: "Input tax credit", value: money(gst.summary.itc_tax), tone: "text-emerald-700" },
                  { label: "Net payable", value: money(gst.summary.net_payable), tone: "text-amber-700" },
                  { label: "Carried forward", value: money(gst.summary.credit_carried_forward), tone: "text-brand-700" },
                ].map((item) => (
                  <Card key={item.label}>
                    <CardBody>
                      <p className="text-[10px] uppercase tracking-wide text-slate-400">{item.label}</p>
                      <p className={`mt-1 text-xl font-semibold tabular ${item.tone}`}>{item.value}</p>
                    </CardBody>
                  </Card>
                ))}
              </div>

              <Card>
                <CardHeader title="GSTR-1 summary" description="Outward supplies grouped by party and rate." icon={ArrowUpFromLine} />
                <CardBody className="pt-0">
                  {gst.gstr1.b2b.length === 0 && gst.gstr1.b2cs.length === 0 ? (
                    <EmptyState title="No outward supplies" description="No sales vouchers were recorded in this period." />
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[720px] border-collapse">
                        <thead>
                          <tr>
                            <th className="table-head">Party</th>
                            <th className="table-head">GSTIN</th>
                            <th className="table-head">Rate</th>
                            <th className="table-head">Taxable</th>
                            <th className="table-head">Tax</th>
                            <th className="table-head">Invoice value</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {[...gst.gstr1.b2b, ...gst.gstr1.b2cs].map((row, index) => (
                            <tr key={`${row.party}-${row.rate}-${index}`} className="row-hover">
                              <td className="table-cell text-[11px] font-medium text-slate-700">{row.party}</td>
                              <td className="table-cell font-mono text-[10px] text-slate-500">{row.gstin || "B2C"}</td>
                              <td className="table-cell text-[11px]">{row.rate}%</td>
                              <td className="table-cell tabular text-[11px]">{money(row.taxable_value)}</td>
                              <td className="table-cell tabular text-[11px]">{money(row.cgst + row.sgst + row.igst)}</td>
                              <td className="table-cell tabular text-[11px]">{money(row.invoice_value)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardBody>
              </Card>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader title="GSTR-3B working" description="Outward tax, ITC and net position." icon={ArrowDownToLine} />
                  <CardBody className="space-y-2 text-[12px]">
                    <div className="flex justify-between"><span className="text-slate-500">Outward taxable</span><span className="tabular">{money(gst.gstr3b.outward.taxable)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-500">Outward tax</span><span className="tabular">{money(gst.gstr3b.outward.total)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-500">ITC taxable</span><span className="tabular">{money(gst.gstr3b.itc.taxable)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-500">ITC available</span><span className="tabular">{money(gst.gstr3b.itc.total)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-500">ITC at risk</span><span className="tabular text-amber-700">{money(gst.gstr3b.itc_at_risk)}</span></div>
                    <div className="flex justify-between border-t border-slate-100 pt-2 font-semibold"><span>Net payable</span><span className="tabular">{money(gst.gstr3b.net_payable)}</span></div>
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader title="Mismatch flags" description="Items an accountant should check before relying on this working." icon={AlertTriangle} />
                  <CardBody className="pt-0">
                    {gst.mismatches.length === 0 ? (
                      <p className="text-[11px] text-slate-500">No mismatch flags for this period.</p>
                    ) : (
                      <ul className="space-y-2">
                        {gst.mismatches.map((row, index) => (
                          <li key={`${row.voucher}-${index}`} className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[11px] font-semibold text-amber-900">{row.title}</p>
                              <Badge tone={statusTone(row.severity)}>{labelize(row.severity)}</Badge>
                            </div>
                            <p className="mt-0.5 text-[11px] text-amber-800">{row.voucher} · {row.detail}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardBody>
                </Card>
              </div>
            </>
          )}
        </div>
      )}

      {tab === "tally" && (
        <div className="space-y-4">
          <Callout tone="blue" title="No live Tally connection">
            Imports and exports are file-based. Nothing is synchronised with a Tally installation.
          </Callout>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Import Tally vouchers" description="CSV or Excel rows are validated for missing fields and duplicates." icon={ArrowDownToLine} />
              <CardBody className="space-y-3">
                <Field label="Tally file" htmlFor="tally_file">
                  <input
                    id="tally_file"
                    type="file"
                    accept=".csv,.xlsx,.xls"
                    onChange={(event) => setTallyFile(event.target.files?.[0] || null)}
                    className="block w-full text-xs text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-brand-700"
                  />
                </Field>
                <Button icon={Upload} loading={busy} onClick={importTally} disabled={!tallyFile}>
                  Import and validate
                </Button>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Export voucher file" description="Produces a Tally-compatible CSV for the selected dates." icon={ArrowUpFromLine} />
              <CardBody className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <Field label="From" htmlFor="tally_from">
                    <Input
                      id="tally_from"
                      type="date"
                      value={tallyRange.from_date}
                      onChange={(event) => setTallyRange({ ...tallyRange, from_date: event.target.value })}
                    />
                  </Field>
                  <Field label="To" htmlFor="tally_to">
                    <Input
                      id="tally_to"
                      type="date"
                      value={tallyRange.to_date}
                      onChange={(event) => setTallyRange({ ...tallyRange, to_date: event.target.value })}
                    />
                  </Field>
                </div>
                <Field label="Voucher type" htmlFor="tally_type">
                  <Select
                    id="tally_type"
                    value={tallyRange.voucher_type}
                    onChange={(event) => setTallyRange({ ...tallyRange, voucher_type: event.target.value })}
                  >
                    <option value="all">All vouchers</option>
                    {VOUCHER_TYPES.map((value) => (
                      <option key={value} value={value}>
                        {labelize(value)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button icon={ArrowUpFromLine} loading={busy} onClick={exportTally}>
                  Download CSV
                </Button>
              </CardBody>
            </Card>
          </div>

          <Card>
            <CardHeader title="Import and export history" description="Recent file exchanges for this client." icon={FileSpreadsheet} />
            <CardBody className="pt-0">
              {tallyBatches.length === 0 ? (
                <EmptyState title="No Tally files yet" description="Imports and exports will be listed here." icon={FileSpreadsheet} />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[680px] border-collapse">
                    <thead>
                      <tr>
                        <th className="table-head">File</th>
                        <th className="table-head">Direction</th>
                        <th className="table-head">Rows</th>
                        <th className="table-head">Valid</th>
                        <th className="table-head">Duplicates</th>
                        <th className="table-head">Created</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {tallyBatches.map((batch) => (
                        <tr key={batch.id} className="row-hover">
                          <td className="table-cell text-[11px] font-medium text-slate-700">{batch.filename}</td>
                          <td className="table-cell"><Badge tone={batch.direction === "import" ? "blue" : "green"}>{labelize(batch.direction)}</Badge></td>
                          <td className="table-cell tabular text-[11px]">{batch.row_count}</td>
                          <td className="table-cell tabular text-[11px]">{batch.valid_count}</td>
                          <td className="table-cell tabular text-[11px]">{batch.duplicate_count}</td>
                          <td className="table-cell whitespace-nowrap text-[10px] text-slate-500">{formatDateTime(batch.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {tab === "reports" && (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Prepare a report"
              description="Reports are built from recorded vouchers, then reviewed by a senior accountant before delivery."
              icon={FileText}
            />
            <CardBody className="flex flex-wrap items-end gap-3">
              <Field label="Report type" htmlFor="report_type" className="min-w-[180px]">
                <Select
                  id="report_type"
                  value={reportForm.report_type}
                  onChange={(event) => setReportForm({ ...reportForm, report_type: event.target.value })}
                >
                  {REPORT_TYPES.map((row) => (
                    <option key={row.key} value={row.key}>
                      {row.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Financial year" htmlFor="report_fy" className="w-36">
                <Input
                  id="report_fy"
                  value={reportForm.financial_year}
                  onChange={(event) => setReportForm({ ...reportForm, financial_year: event.target.value })}
                />
              </Field>
              <Field
                label={reportForm.report_type === "financials" ? "Period label" : "Month"}
                htmlFor="report_period"
                className="w-44"
              >
                <Input
                  id="report_period"
                  type={reportForm.report_type === "financials" ? "text" : "month"}
                  value={reportForm.period}
                  onChange={(event) => setReportForm({ ...reportForm, period: event.target.value })}
                />
              </Field>
              <Button loading={busy} onClick={createReport}>
                Build draft
              </Button>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Reports"
              description={
                isSeniorAccountant
                  ? "Drafts from the team, awaiting your review or ready to deliver."
                  : "Drafts you create are sent to a senior accountant for review."
              }
              icon={FileText}
              actions={
                isSeniorAccountant ? (
                  <Button size="sm" variant="outline" icon={RefreshCw} onClick={() => void loadReports()}>
                    Refresh
                  </Button>
                ) : undefined
              }
            />
            <CardBody className="pt-0">
              {reports.length === 0 ? (
                <EmptyState title="No reports yet" description="Build a draft report for this client." icon={FileText} />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] border-collapse">
                    <thead>
                      <tr>
                        <th className="table-head">Report</th>
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
                          <td className="table-cell text-[12px] font-semibold text-ink-900">{labelize(report.report_type)}</td>
                          <td className="table-cell text-[11px] text-slate-600">{report.period_label}</td>
                          <td className="table-cell text-[11px]">v{report.version}</td>
                          <td className="table-cell"><StatusBadge status={report.status} /></td>
                          <td className="table-cell whitespace-nowrap text-[10px] text-slate-500">{formatDate(report.created_at)}</td>
                          <td className="table-cell">
                            <Button size="sm" variant="ghost" onClick={() => void openReport(report)}>
                              Open
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
        </div>
      )}

      <Modal
        open={Boolean(reportDetail)}
        onClose={() => setReportDetail(null)}
        title={reportDetail ? `${labelize(reportDetail.report_type)} · ${reportDetail.period_label}` : "Report"}
        description={reportDetail ? `FY ${reportDetail.financial_year} · version ${reportDetail.version}` : undefined}
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setReportDetail(null)}>
              Close
            </Button>
            {isSeniorAccountant &&
              reportDetail &&
              ["draft", "changes_requested"].includes(reportDetail.status) && (
                <>
                  <Button
                    variant="danger"
                    loading={busy}
                    onClick={() => void reviewReport("changes_requested")}
                  >
                    Request changes
                  </Button>
                  <Button variant="success" loading={busy} onClick={() => void reviewReport("approve")}>
                    Approve
                  </Button>
                </>
              )}
            {isSeniorAccountant && reportDetail?.status === "approved" && (
              <Button loading={busy} onClick={() => void deliverReport()}>
                Deliver to client
              </Button>
            )}
          </>
        }
      >
        {reportDetail && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={reportDetail.status} />
              {reportDetail.approved_at && (
                <span className="text-[10px] text-slate-400">Approved {formatDateTime(reportDetail.approved_at)}</span>
              )}
            </div>
            {reportPayload ? (
              <div className="space-y-3">
                {typeof reportPayload.note === "string" && (
                  <Callout tone="amber" title="Basis of preparation">
                    {reportPayload.note}
                  </Callout>
                )}
                {typeof reportPayload.filing_note === "string" && (
                  <Callout tone="amber" title="Filing boundary">
                    {reportPayload.filing_note}
                  </Callout>
                )}
                <div className="grid gap-2 sm:grid-cols-3">
                  {["revenue", "expenses", "gross_profit"].map((key) =>
                    typeof reportPayload[key] === "number" ? (
                      <div key={key} className="rounded-lg border border-slate-200 px-3 py-2">
                        <p className="text-[10px] uppercase tracking-wide text-slate-400">{labelize(key)}</p>
                        <p className="mt-1 text-lg font-semibold tabular text-ink-900">
                          {moneyExact(reportPayload[key] as number)}
                        </p>
                      </div>
                    ) : null,
                  )}
                </div>
                <div>
                  <p className="mb-1 text-[10px] uppercase tracking-wide text-slate-400">Report payload</p>
                  <pre className="max-h-72 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-[10px] leading-relaxed text-slate-600">
                    {JSON.stringify(reportPayload, null, 2)}
                  </pre>
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-slate-500">The payload was not returned for this report.</p>
            )}
            {isSeniorAccountant && ["draft", "changes_requested"].includes(reportDetail.status) && (
              <Field label="Review notes" htmlFor="report_review_note">
                <Textarea
                  id="report_review_note"
                  value={reportReviewNote}
                  onChange={(event) => setReportReviewNote(event.target.value)}
                  placeholder="What was checked, or what must change"
                />
              </Field>
            )}
            {reportDetail.review_notes && (
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                Review note: {reportDetail.review_notes}
              </p>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
