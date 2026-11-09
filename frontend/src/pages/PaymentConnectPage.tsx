import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  BadgeCheck,
  CheckCircle2,
  CircleDollarSign,
  Database,
  FileSpreadsheet,
  History,
  KeyRound,
  Link2,
  Loader2,
  PlugZap,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Upload,
  Wallet,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { get, getErrorMessage, post } from "../lib/api";
import { fileToDataUrl, formatBytes, labelize } from "../lib/accounting";
import type { AccountingClient } from "../lib/accountingTypes";
import type {
  PCBankImport,
  PCBankImportResult,
  PCBankPreview,
  PCBankRow,
  PCCandidate,
  PCConnection,
  PCEvent,
  PCGooglePayEligibility,
  PCInvoiceOption,
  PCOverview,
  PCReconcileResponse,
  PCSyncResult,
  PCTransaction,
  PCTransactionList,
} from "../lib/paymentConnectTypes";
import { formatDate, formatDateTime, money, moneyExact } from "../lib/utils";
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
  TableWrap,
  Tabs,
  TBody,
  TD,
  THead,
  TH,
  TR,
  Textarea,
} from "../components/ui";

type Mode = "owner" | "accountant";
type TabKey = "overview" | "transactions" | "statements" | "google-pay";
type BadgeTone = "slate" | "blue" | "green" | "amber" | "red" | "violet" | "cyan" | "navy";
type BankField = "txn_date" | "description" | "reference" | "debit" | "credit";
type BankCorrection = Partial<Record<BankField, string>>;

interface Filters {
  date_from: string;
  date_to: string;
  provider: string;
  direction: string;
  status: string;
  reconciliation_status: string;
  search: string;
  amount_min: string;
  amount_max: string;
  include_duplicates: boolean;
}

const EMPTY_FILTERS: Filters = {
  date_from: "",
  date_to: "",
  provider: "",
  direction: "",
  status: "",
  reconciliation_status: "",
  search: "",
  amount_min: "",
  amount_max: "",
  include_duplicates: false,
};

const PROVIDERS = [
  { value: "paypal", label: "PayPal" },
  { value: "google_pay", label: "Google Pay" },
  { value: "bank_statement", label: "Bank statement" },
];

const TXN_STATUSES = ["completed", "pending", "failed", "refunded", "reversed", "chargeback", "unknown"];
const RECON_STATUSES = ["unverified", "suggested", "matched", "rejected", "not_applicable"];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgo(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return value.toISOString().slice(0, 10);
}

function providerTone(provider: string): BadgeTone {
  if (provider === "paypal") return "blue";
  if (provider === "google_pay") return "violet";
  return "slate";
}

function reconciliationTone(status: string): BadgeTone {
  if (status === "matched") return "green";
  if (status === "suggested") return "amber";
  if (status === "rejected") return "red";
  if (status === "not_applicable") return "slate";
  return "cyan";
}

function connectionTone(status: string): BadgeTone {
  if (status === "connected") return "green";
  if (status === "error") return "red";
  if (status === "disconnected") return "slate";
  return "amber";
}

function isRefund(txn: PCTransaction): boolean {
  return txn.amount.startsWith("-") || ["refund", "chargeback", "reversal"].includes(txn.txn_type);
}

function signedMoney(txn: PCTransaction): string {
  const amount = moneyExact(txn.amount, txn.currency);
  if (txn.direction === "outgoing" || txn.amount.startsWith("-")) {
    return amount.startsWith("-") ? amount : `-${amount}`;
  }
  return `+${amount}`;
}

function syncRange(days: number) {
  return { start_date: daysAgo(days), end_date: today() };
}

export function PaymentConnectPage({ mode }: { mode: Mode }) {
  const accountant = mode === "accountant";
  const base = accountant ? "/accounting/payment-connect" : "/payment-connect";
  const { isSeniorAccountant } = useAuth();
  const canManageConnections = !accountant || isSeniorAccountant;
  const [params] = useSearchParams();

  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [clientId, setClientId] = useState<number | null>(() => {
    const value = Number(params.get("clientId"));
    return Number.isFinite(value) && value > 0 ? value : null;
  });
  const [loadingClients, setLoadingClients] = useState(accountant);
  const [overview, setOverview] = useState<PCOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");
  const [refreshing, setRefreshing] = useState(false);

  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<Filters>(EMPTY_FILTERS);
  const [txnData, setTxnData] = useState<PCTransactionList | null>(null);
  const [txnLoading, setTxnLoading] = useState(false);

  const [reviewTxn, setReviewTxn] = useState<PCTransaction | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewCandidates, setReviewCandidates] = useState<PCCandidate[]>([]);
  const [reviewEvents, setReviewEvents] = useState<PCEvent[]>([]);
  const [reviewInvoices, setReviewInvoices] = useState<PCInvoiceOption[]>([]);
  const [reviewInvoiceId, setReviewInvoiceId] = useState<number | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);

  const [connectOpen, setConnectOpen] = useState(false);
  const [connectForm, setConnectForm] = useState({
    provider: "paypal" as "paypal" | "google_pay",
    environment: "sandbox",
    label: "",
    merchant_id: "",
    outlet_label: "",
    note: "",
    consent: false,
  });
  const [connectBusy, setConnectBusy] = useState(false);

  const [syncTarget, setSyncTarget] = useState<PCConnection | null>(null);
  const [syncForm, setSyncForm] = useState(syncRange(30));
  const [syncBusy, setSyncBusy] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<PCConnection | null>(null);
  const [disconnectBusy, setDisconnectBusy] = useState(false);

  const [bankFile, setBankFile] = useState<File | null>(null);
  const [bankInputKey, setBankInputKey] = useState(0);
  const [bankAccountLabel, setBankAccountLabel] = useState("");
  const [bankPreview, setBankPreview] = useState<PCBankPreview | null>(null);
  const [bankRows, setBankRows] = useState<PCBankRow[]>([]);
  const [bankCorrections, setBankCorrections] = useState<Record<number, BankCorrection>>({});
  const [bankBusy, setBankBusy] = useState(false);
  const [bankImports, setBankImports] = useState<PCBankImport[]>([]);

  const [gpEligibility, setGpEligibility] = useState<PCGooglePayEligibility | null>(null);
  const [gpLookupError, setGpLookupError] = useState<string | null>(null);
  const [gpLookupBusy, setGpLookupBusy] = useState(false);
  const [gpTrack, setGpTrack] = useState({
    merchant_id: "",
    google_transaction_id: "",
    amount: "",
    currency: "INR",
    occurred_on: today(),
    status: "unknown",
    description: "",
    upi_reference: "",
    outlet_label: "",
  });
  const [gpTrackBusy, setGpTrackBusy] = useState(false);

  const scopeQuery = useCallback(
    (extra: Record<string, string | number | boolean | undefined | null> = {}) => {
      const query = new URLSearchParams();
      if (accountant && clientId) query.set("client_id", String(clientId));
      for (const [key, value] of Object.entries(extra)) {
        if (value === undefined || value === null || value === "" || value === false) continue;
        query.set(key, String(value));
      }
      return query.toString();
    },
    [accountant, clientId],
  );

  const loadClients = useCallback(async () => {
    if (!accountant) return;
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
  }, [accountant, isSeniorAccountant]);

  useEffect(() => {
    void loadClients();
  }, [loadClients]);

  const loadOverview = useCallback(async () => {
    if (accountant && !clientId) {
      setOverview(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const query = scopeQuery();
      setOverview(await get<PCOverview>(`${base}/overview${query ? `?${query}` : ""}`));
    } catch (err) {
      setError(getErrorMessage(err));
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, [accountant, base, clientId, scopeQuery]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const loadTransactions = useCallback(
    async (override?: Filters) => {
      if (accountant && !clientId) return;
      const active = override ?? appliedFilters;
      setTxnLoading(true);
      try {
        const query = scopeQuery({
          date_from: active.date_from,
          date_to: active.date_to,
          provider: active.provider,
          direction: active.direction,
          status: active.status,
          reconciliation_status: active.reconciliation_status,
          search: active.search,
          amount_min: active.amount_min,
          amount_max: active.amount_max,
          include_duplicates: active.include_duplicates ? "true" : undefined,
          limit: 250,
        });
        setTxnData(await get<PCTransactionList>(`${base}/transactions?${query}`));
      } catch (err) {
        setActionError(getErrorMessage(err));
      } finally {
        setTxnLoading(false);
      }
    },
    [accountant, appliedFilters, base, clientId, scopeQuery],
  );

  useEffect(() => {
    if (tab === "transactions") void loadTransactions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, clientId, base]);

  const loadBankImports = useCallback(async () => {
    if (!accountant || !clientId) return;
    try {
      const data = await get<{ items: PCBankImport[] }>(
        `${base}/bank-statements?client_id=${clientId}`,
      );
      setBankImports(data.items);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [accountant, base, clientId]);

  useEffect(() => {
    if (tab === "statements") void loadBankImports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, clientId]);

  const loadGooglePay = useCallback(async () => {
    if (accountant && !clientId) return;
    try {
      const query = scopeQuery();
      setGpEligibility(
        await get<PCGooglePayEligibility>(`${base}/google-pay/eligibility${query ? `?${query}` : ""}`),
      );
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [accountant, base, clientId, scopeQuery]);

  useEffect(() => {
    if (tab === "google-pay") void loadGooglePay();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, clientId]);

  useEffect(() => {
    if (tab !== "google-pay") return;
    const connection = overview?.connections.find((row) => row.provider === "google_pay");
    if (connection?.merchant_id) {
      setGpTrack((current) =>
        current.merchant_id ? current : { ...current, merchant_id: connection.merchant_id ?? "" },
      );
    }
  }, [overview, tab]);

  const tabs = useMemo(() => {
    const items: { key: TabKey; label: string; count?: number }[] = [
      { key: "overview", label: "Connections" },
      {
        key: "transactions",
        label: "Transactions",
        count: overview?.summary.transactions,
      },
    ];
    if (accountant) {
      items.push({ key: "statements", label: "Bank statements", count: bankImports.length });
    }
    items.push({ key: "google-pay", label: "Google Pay" });
    return items;
  }, [accountant, bankImports.length, overview?.summary.transactions]);

  const reviewInvoice = useMemo(() => {
    if (!reviewTxn) return null;
    return isRefund(reviewTxn) ? null : reviewInvoiceId;
  }, [reviewInvoiceId, reviewTxn]);

  const openReview = async (txn: PCTransaction) => {
    setReviewTxn(txn);
    setReviewOpen(true);
    setReviewCandidates([]);
    setReviewEvents([]);
    setReviewInvoices([]);
    setReviewInvoiceId(txn.matched_invoice_id ?? null);
    setReviewNote("");
    setReviewBusy(true);
    setActionError(null);
    try {
      const query = scopeQuery();
      const [candidates, events] = await Promise.all([
        get<{ items: PCCandidate[] }>(
          `${base}/transactions/${txn.id}/candidates${query ? `?${query}` : ""}`,
        ),
        get<{ items: PCEvent[] }>(`${base}/transactions/${txn.id}/events${query ? `?${query}` : ""}`),
      ]);
      setReviewCandidates(candidates.items);
      setReviewEvents(events.items);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
    try {
      setReviewInvoices(await loadInvoiceOptions());
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setReviewBusy(false);
    }
  };

  const loadInvoiceOptions = async (): Promise<PCInvoiceOption[]> => {
    if (accountant) {
      if (!clientId) return [];
      const role = isSeniorAccountant ? "senior" : "junior";
      const data = await get<{
        items: {
          source_type: string;
          source_id: number;
          reference: string;
          party_name: string | null;
          total_amount: string | number;
          date: string;
          source_status: string;
        }[];
      }>(
        `/accounting/${role}/clients/${clientId}/business/transactions?transaction_type=sale&limit=200`,
      );
      return data.items
        .filter(
          (row) =>
            row.source_type === "invoice" &&
            !["draft", "void", "paid"].includes((row.source_status || "").toLowerCase()),
        )
        .map((row) => ({
          id: row.source_id,
          number: row.reference,
          customer_name: row.party_name,
          total: row.total_amount,
          outstanding: "",
          issue_date: row.date,
          status: row.source_status,
        }));
    }
    const data = await get<{
      items: {
        id: number;
        number: string;
        customer?: { name?: string | null };
        total: string | number;
        outstanding: string | number;
        issue_date: string;
        status: string;
      }[];
    }>("/invoices?status=outstanding&limit=300");
    return data.items.map((row) => ({
      id: row.id,
      number: row.number,
      customer_name: row.customer?.name ?? null,
      total: row.total,
      outstanding: row.outstanding,
      issue_date: row.issue_date,
      status: row.status,
    }));
  };

  const refreshAfterAction = async () => {
    await loadOverview();
    if (tab === "transactions") await loadTransactions();
    if (tab === "statements") await loadBankImports();
  };

  const submitReconcile = async (action: "approve" | "reject" | "not_applicable" | "reset" | "suggest") => {
    if (!reviewTxn) return;
    setReviewBusy(true);
    setActionError(null);
    try {
      const body: Record<string, unknown> = { action };
      if (accountant) body.client_id = clientId;
      if (reviewNote.trim()) body.note = reviewNote.trim();
      if (action === "approve" && !isRefund(reviewTxn)) body.invoice_id = reviewInvoice;
      const result = await post<PCReconcileResponse>(
        `${base}/transactions/${reviewTxn.id}/reconcile`,
        body,
      );
      setNotice(
        action === "approve"
          ? `Payment approved${result.transaction.accounting_draft_id ? ` · accounting draft #${result.transaction.accounting_draft_id} created` : ""}.`
          : action === "reject"
            ? "Transaction rejected and kept in the audit trail."
            : action === "not_applicable"
              ? "Transaction marked as not applicable to an invoice."
              : action === "reset"
                ? "Review state cleared. The transaction is back in the queue."
                : "Match suggestions refreshed. Nothing was approved.",
      );
      setReviewOpen(false);
      setReviewTxn(null);
      await refreshAfterAction();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setReviewBusy(false);
    }
  };

  const openConnect = () => {
    setActionError(null);
    setConnectOpen(true);
  };

  const submitConnection = async () => {
    if (!connectForm.consent) return;
    setConnectBusy(true);
    setActionError(null);
    try {
      const body: Record<string, unknown> = {
        provider: connectForm.provider,
        label: connectForm.label || undefined,
        outlet_label: connectForm.outlet_label || undefined,
        merchant_id: connectForm.provider === "google_pay" ? connectForm.merchant_id : undefined,
        note: connectForm.note || undefined,
        consent: connectForm.consent,
      };
      if (connectForm.provider === "paypal") body.environment = connectForm.environment;
      if (accountant) body.client_id = clientId;
      await post<PCConnection>(`${base}/connections`, body);
      setConnectOpen(false);
      setConnectForm({
        provider: "paypal",
        environment: "sandbox",
        label: "",
        merchant_id: "",
        outlet_label: "",
        note: "",
        consent: false,
      });
      setNotice("Provider connection saved. Credentials stay in the backend environment.");
      await loadOverview();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setConnectBusy(false);
    }
  };

  const submitSync = async () => {
    if (!syncTarget) return;
    setSyncBusy(true);
    setActionError(null);
    try {
      const query = scopeQuery();
      const body: Record<string, unknown> = {
        start_date: syncForm.start_date,
        end_date: syncForm.end_date,
        trigger: "manual",
      };
      if (accountant) body.client_id = clientId;
      const result = await post<PCSyncResult>(
        `${base}/connections/${syncTarget.id}/sync${query ? `?${query}` : ""}`,
        body,
      );
      setSyncTarget(null);
      setNotice(
        result.status === "failed"
          ? `Sync failed: ${result.error || "the provider rejected the request."}`
          : `Sync complete: ${result.fetched} fetched, ${result.created} new, ${result.duplicates} duplicates skipped.`,
      );
      await refreshAfterAction();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setSyncBusy(false);
    }
  };

  const submitDisconnect = async () => {
    if (!disconnectTarget) return;
    setDisconnectBusy(true);
    setActionError(null);
    try {
      const query = scopeQuery();
      await post<PCConnection>(
        `${base}/connections/${disconnectTarget.id}/disconnect${query ? `?${query}` : ""}`,
      );
      setDisconnectTarget(null);
      setNotice("Connection disconnected. Imported transactions remain in the audit trail.");
      await loadOverview();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setDisconnectBusy(false);
    }
  };

  const previewStatement = async () => {
    if (!accountant || !clientId || !bankFile) return;
    setBankBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(bankFile);
      const preview = await post<PCBankPreview>(`${base}/bank-statements/preview`, {
        client_id: clientId,
        filename: bankFile.name,
        data_url: dataUrl,
        account_label: bankAccountLabel || null,
      });
      setBankPreview(preview);
      setBankRows(preview.rows);
      setBankCorrections({});
    } catch (err) {
      setActionError(getErrorMessage(err));
      setBankPreview(null);
      setBankRows([]);
    } finally {
      setBankBusy(false);
    }
  };

  const updateBankRow = (rowNumber: number, field: BankField, value: string) => {
    setBankRows((rows) =>
      rows.map((row) => (row.row === rowNumber ? { ...row, [field]: value } : row)),
    );
    setBankCorrections((current) => ({
      ...current,
      [rowNumber]: { ...current[rowNumber], [field]: value },
    }));
  };

  const importStatement = async () => {
    if (!accountant || !clientId || !bankFile) return;
    setBankBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(bankFile);
      const corrections = Object.entries(bankCorrections).map(([row, values]) => {
        const corrected: Record<string, string | number> = { row: Number(row) };
        for (const [key, value] of Object.entries(values)) {
          if (value !== undefined && value !== "") corrected[key] = value;
        }
        return corrected;
      });
      const result = await post<PCBankImportResult>(`${base}/bank-statements/import`, {
        client_id: clientId,
        filename: bankFile.name,
        data_url: dataUrl,
        account_label: bankAccountLabel || null,
        corrections,
      });
      setNotice(
        `Statement imported: ${result.rows} rows, ${result.uncertain} need review, ${result.duplicates_skipped} duplicates skipped. The original is encrypted at rest.`,
      );
      setBankPreview(null);
      setBankRows([]);
      setBankCorrections({});
      setBankFile(null);
      setBankInputKey((value) => value + 1);
      await Promise.all([loadBankImports(), loadOverview(), loadTransactions()]);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBankBusy(false);
    }
  };

  const lookupGooglePay = async () => {
    setGpLookupBusy(true);
    setGpLookupError(null);
    try {
      const query = scopeQuery();
      await post(`${base}/google-pay/lookup${query ? `?${query}` : ""}`);
      setGpLookupError("Unexpected response: no public Google Pay history API is configured.");
    } catch (err) {
      setGpLookupError(getErrorMessage(err));
    } finally {
      setGpLookupBusy(false);
    }
  };

  const trackGooglePay = async () => {
    setGpTrackBusy(true);
    setActionError(null);
    try {
      const body: Record<string, unknown> = {
        merchant_id: gpTrack.merchant_id,
        google_transaction_id: gpTrack.google_transaction_id,
        amount: gpTrack.amount,
        currency: gpTrack.currency || "INR",
        occurred_on: gpTrack.occurred_on,
        status: gpTrack.status,
        description: gpTrack.description || undefined,
        upi_reference: gpTrack.upi_reference || undefined,
        outlet_label: gpTrack.outlet_label || undefined,
      };
      if (accountant) body.client_id = clientId;
      await post<PCTransaction>(`${base}/google-pay/track`, body);
      setNotice(
        "Google Pay merchant reference recorded. It is marked as not verified through Google and needs review.",
      );
      setGpTrack((current) => ({
        ...current,
        google_transaction_id: "",
        amount: "",
        description: "",
        upi_reference: "",
      }));
      await Promise.all([loadOverview(), loadTransactions()]);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setGpTrackBusy(false);
    }
  };

  const connectedCount = overview?.connections.filter((row) => row.status === "connected").length ?? 0;
  const pendingReview =
    (overview?.reconciliation.unverified ?? 0) + (overview?.reconciliation.suggested ?? 0);
  const gpConnection = overview?.connections.find((row) => row.provider === "google_pay");

  if (accountant && loadingClients) {
    return <PageSkeleton cards={4} />;
  }

  if (accountant && clients.length === 0) {
    return (
      <div className="space-y-5">
        <PageHeader
          title="Payment Connect"
          description="Reconcile authorised provider transactions and imported statements for your assigned clients."
        />
        <EmptyState
          icon={Wallet}
          title="No clients assigned"
          description="A senior accountant must assign client engagements before payments can be reconciled."
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Payment Connect"
        description={
          accountant
            ? "Reconcile authorised PayPal transactions, merchant references and imported bank statements against client invoices. Nothing is approved automatically."
            : "Bring authorised PayPal history, eligible Google Pay merchant references and imported statements into one reconciliation queue. Every approval is explicit."
        }
        actions={
          <>
            <Button
              variant="outline"
              icon={RefreshCw}
              loading={refreshing}
              onClick={async () => {
                setRefreshing(true);
                await loadOverview();
                if (tab === "transactions") await loadTransactions();
                if (tab === "statements") await loadBankImports();
                if (tab === "google-pay") await loadGooglePay();
                setRefreshing(false);
              }}
            >
              Refresh
            </Button>
            {canManageConnections && (
              <Button icon={PlugZap} onClick={openConnect}>
                Connect provider
              </Button>
            )}
          </>
        }
      />

      {accountant && (
        <Card>
          <CardBody className="flex flex-wrap items-end gap-4 py-4">
            <Field label="Client business" className="min-w-[260px] flex-1" htmlFor="pc-client">
              <Select
                id="pc-client"
                value={clientId ?? ""}
                onChange={(event) => {
                  setClientId(Number(event.target.value) || null);
                  setTxnData(null);
                  setBankPreview(null);
                  setBankRows([]);
                  setBankCorrections({});
                  setNotice(null);
                }}
              >
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.business_name} · {client.code}
                  </option>
                ))}
              </Select>
            </Field>
            <p className="pb-2 text-[11px] leading-relaxed text-slate-500">
              Only assigned businesses are visible. Owner-wide and client-specific connections are
              reconciled separately.
            </p>
          </CardBody>
        </Card>
      )}

      {notice && (
        <Callout tone="green" title="Done">
          {notice}
        </Callout>
      )}
      {actionError && (
        <Callout tone="red" title="Action failed">
          {actionError}
        </Callout>
      )}

      <Tabs items={tabs} value={tab} onChange={setTab} />

      {tab === "overview" && (
        <div className="space-y-5">
          {error && <ErrorState message={error} onRetry={loadOverview} />}
          {loading && <PageSkeleton cards={4} />}
          {!loading && overview && (
            <>
              <Callout tone="slate" icon={ShieldCheck} title="Credential boundary">
                {overview.security_note} Connection consent is recorded, every sync is logged, and
                disconnecting never deletes the imported audit trail.
              </Callout>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div className="card p-5">
                  <p className="text-[12px] font-medium text-slate-500">Imported transactions</p>
                  <p className="mt-2 text-[22px] font-semibold text-ink-900">
                    {overview.summary.transactions}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    {overview.summary.duplicates} duplicate rows blocked
                  </p>
                </div>
                <div className="card p-5">
                  <p className="text-[12px] font-medium text-slate-500">Incoming total</p>
                  <p className="mt-2 text-[22px] font-semibold text-emerald-700">
                    {money(overview.summary.incoming_total)}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    Outgoing {money(overview.summary.outgoing_total)}
                  </p>
                </div>
                <div className="card p-5">
                  <p className="text-[12px] font-medium text-slate-500">Matched to invoices</p>
                  <p className="mt-2 text-[22px] font-semibold text-ink-900">
                    {overview.reconciliation.matched}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    {overview.reconciliation.rejected} rejected ·{" "}
                    {overview.reconciliation.not_applicable} not applicable
                  </p>
                </div>
                <div className="card p-5">
                  <p className="text-[12px] font-medium text-slate-500">Needs review</p>
                  <p className="mt-2 text-[22px] font-semibold text-amber-700">{pendingReview}</p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    {overview.reconciliation.unverified} unverified ·{" "}
                    {overview.reconciliation.suggested} suggested
                  </p>
                </div>
              </div>

              <section className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-semibold text-ink-900">Connected providers</h2>
                    <p className="text-xs text-slate-500">
                      {connectedCount} active · last successful sync{" "}
                      {overview.last_successful_sync
                        ? formatDateTime(overview.last_successful_sync)
                        : "not yet"}
                    </p>
                  </div>
                  {canManageConnections && (
                    <Button size="sm" variant="outline" icon={PlugZap} onClick={openConnect}>
                      Add connection
                    </Button>
                  )}
                  {!canManageConnections && (
                    <Badge tone="slate">Senior accountant manages connections</Badge>
                  )}
                </div>

                {overview.connections.length === 0 ? (
                  <Card>
                    <EmptyState
                      icon={Link2}
                      title="No provider connections yet"
                      description="Connect PayPal with backend credentials or register a Google Pay merchant ID. Bank statements are imported per client by an accountant."
                      action={
                        canManageConnections ? (
                          <Button icon={PlugZap} onClick={openConnect}>
                            Connect a provider
                          </Button>
                        ) : undefined
                      }
                    />
                  </Card>
                ) : (
                  <div className="grid gap-4 xl:grid-cols-2">
                    {overview.connections.map((connection) => (
                      <Card key={connection.id}>
                        <CardBody className="space-y-4">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-ink-900">
                                {connection.label}
                              </p>
                              <p className="text-[11px] text-slate-500">
                                {connection.provider_label} · {labelize(connection.environment)} ·{" "}
                                {labelize(connection.mode)}
                              </p>
                            </div>
                            <Badge tone={connectionTone(connection.status)} dot>
                              {labelize(connection.status)}
                            </Badge>
                          </div>

                          <div className="grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-3 text-[11px] sm:grid-cols-4">
                            <div>
                              <p className="text-slate-400">Transactions</p>
                              <p className="font-semibold text-ink-900">
                                {connection.counts.transactions}
                              </p>
                            </div>
                            <div>
                              <p className="text-slate-400">Matched</p>
                              <p className="font-semibold text-emerald-700">
                                {connection.counts.matched}
                              </p>
                            </div>
                            <div>
                              <p className="text-slate-400">To review</p>
                              <p className="font-semibold text-amber-700">
                                {connection.counts.unmatched}
                              </p>
                            </div>
                            <div>
                              <p className="text-slate-400">Duplicates</p>
                              <p className="font-semibold text-slate-700">
                                {connection.counts.duplicates}
                              </p>
                            </div>
                          </div>

                          <div className="grid gap-1 text-[11px] text-slate-500">
                            <p>
                              Incoming {money(connection.counts.incoming_total)} · Outgoing{" "}
                              {money(connection.counts.outgoing_total)}
                            </p>
                            <p>
                              Last sync{" "}
                              {connection.last_sync_at
                                ? formatDateTime(connection.last_sync_at)
                                : "never"}{" "}
                              · Last success{" "}
                              {connection.last_success_at
                                ? formatDateTime(connection.last_success_at)
                                : "never"}
                            </p>
                            <p>
                              Account{" "}
                              {connection.merchant_id
                                ? `merchant ${connection.merchant_id.slice(0, 6)}…`
                                : connection.account_hint || "backend credential"}
                              {connection.outlet_label ? ` · ${connection.outlet_label}` : ""}
                            </p>
                            <p>
                              Permissions{" "}
                              {connection.permissions.length
                                ? connection.permissions.join(", ")
                                : "none granted"}
                            </p>
                          </div>

                          {connection.last_error && (
                            <Callout tone="red" icon={ShieldAlert} title="Last provider error">
                              {connection.last_error}
                            </Callout>
                          )}

                          <div className="flex flex-wrap gap-2">
                            {canManageConnections && connection.provider === "paypal" && (
                              <Button
                                size="sm"
                                icon={RefreshCw}
                                onClick={() => {
                                  setSyncTarget(connection);
                                  setSyncForm(syncRange(30));
                                }}
                              >
                                Sync history
                              </Button>
                            )}
                            {canManageConnections && connection.status === "connected" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => setDisconnectTarget(connection)}
                              >
                                Disconnect
                              </Button>
                            )}
                          </div>
                        </CardBody>
                      </Card>
                    ))}
                  </div>
                )}
              </section>

              <div className="grid gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader
                    title="Reconciliation queue"
                    description="Nothing is approved automatically. Suggested matches need an explicit decision."
                    icon={CircleDollarSign}
                  />
                  <CardBody className="space-y-2">
                    {[
                      { label: "Unverified", value: overview.reconciliation.unverified, tone: "cyan" as BadgeTone },
                      { label: "Suggested", value: overview.reconciliation.suggested, tone: "amber" as BadgeTone },
                      { label: "Matched", value: overview.reconciliation.matched, tone: "green" as BadgeTone },
                      { label: "Rejected", value: overview.reconciliation.rejected, tone: "red" as BadgeTone },
                      {
                        label: "Not applicable",
                        value: overview.reconciliation.not_applicable,
                        tone: "slate" as BadgeTone,
                      },
                    ].map((row) => (
                      <div
                        key={row.label}
                        className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2"
                      >
                        <Badge tone={row.tone} dot>
                          {row.label}
                        </Badge>
                        <span className="text-sm font-semibold text-ink-900">{row.value}</span>
                      </div>
                    ))}
                    <Button
                      variant="outline"
                      className="mt-1 w-full"
                      onClick={() => setTab("transactions")}
                    >
                      Open transaction queue
                    </Button>
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader
                    title="Provider capabilities"
                    description="What each provider officially supports in this deployment."
                    icon={Database}
                  />
                  <CardBody className="space-y-3">
                    {overview.capabilities.map((capability) => (
                      <div key={capability.provider} className="rounded-xl border border-slate-200 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-ink-900">{capability.label}</p>
                          <Badge tone={providerTone(capability.provider)}>
                            {labelize(capability.history_access)}
                          </Badge>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500">
                          {capability.history_api || "No public transaction-history API."}
                        </p>
                        <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[11px] text-slate-500">
                          {capability.limitations.slice(0, 3).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </CardBody>
                </Card>
              </div>

              <Card>
                <CardHeader
                  title="Recent sync activity"
                  description="Each sync run is recorded with its window, counts and errors."
                  icon={History}
                />
                <CardBody className="pt-3">
                  {overview.recent_syncs.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      No sync runs yet. Connect PayPal and sync a date window to begin.
                    </p>
                  ) : (
                    <TableWrap>
                      <THead>
                        <TR>
                          <TH>Started</TH>
                          <TH>Provider</TH>
                          <TH>Window</TH>
                          <TH>Status</TH>
                          <TH>Fetched</TH>
                          <TH>New</TH>
                          <TH>Duplicates</TH>
                          <TH>Error</TH>
                        </TR>
                      </THead>
                      <TBody>
                        {overview.recent_syncs.map((run) => (
                          <TR key={run.id}>
                            <TD>{formatDateTime(run.started_at)}</TD>
                            <TD>{labelize(run.provider)}</TD>
                            <TD>
                              {formatDate(run.range_start)} → {formatDate(run.range_end)}
                            </TD>
                            <TD>
                              <Badge
                                tone={
                                  run.status === "completed"
                                    ? "green"
                                    : run.status === "failed"
                                      ? "red"
                                      : "amber"
                                }
                                dot
                              >
                                {labelize(run.status)}
                              </Badge>
                            </TD>
                            <TD>{run.fetched}</TD>
                            <TD>{run.created}</TD>
                            <TD>{run.duplicates}</TD>
                            <TD className="max-w-[260px]">
                              <span className="block truncate" title={run.error || ""}>
                                {run.error || "—"}
                              </span>
                            </TD>
                          </TR>
                        ))}
                      </TBody>
                    </TableWrap>
                  )}
                </CardBody>
              </Card>
            </>
          )}
        </div>
      )}

      {tab === "transactions" && (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Filters"
              description="Filter the unified history by provider, direction, status and reconciliation state."
              icon={Search}
            />
            <CardBody className="grid gap-3 pt-3 sm:grid-cols-2 xl:grid-cols-4">
              <Field label="From" htmlFor="pc-from">
                <Input
                  id="pc-from"
                  type="date"
                  value={filters.date_from}
                  onChange={(event) => setFilters({ ...filters, date_from: event.target.value })}
                />
              </Field>
              <Field label="To" htmlFor="pc-to">
                <Input
                  id="pc-to"
                  type="date"
                  value={filters.date_to}
                  onChange={(event) => setFilters({ ...filters, date_to: event.target.value })}
                />
              </Field>
              <Field label="Provider" htmlFor="pc-provider">
                <Select
                  id="pc-provider"
                  value={filters.provider}
                  onChange={(event) => setFilters({ ...filters, provider: event.target.value })}
                >
                  <option value="">All providers</option>
                  {PROVIDERS.map((provider) => (
                    <option key={provider.value} value={provider.value}>
                      {provider.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Direction" htmlFor="pc-direction">
                <Select
                  id="pc-direction"
                  value={filters.direction}
                  onChange={(event) => setFilters({ ...filters, direction: event.target.value })}
                >
                  <option value="">Both</option>
                  <option value="incoming">Incoming</option>
                  <option value="outgoing">Outgoing</option>
                </Select>
              </Field>
              <Field label="Provider status" htmlFor="pc-status">
                <Select
                  id="pc-status"
                  value={filters.status}
                  onChange={(event) => setFilters({ ...filters, status: event.target.value })}
                >
                  <option value="">Any status</option>
                  {TXN_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {labelize(status)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Reconciliation" htmlFor="pc-recon">
                <Select
                  id="pc-recon"
                  value={filters.reconciliation_status}
                  onChange={(event) =>
                    setFilters({ ...filters, reconciliation_status: event.target.value })
                  }
                >
                  <option value="">Any state</option>
                  {RECON_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {labelize(status)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Amount from" htmlFor="pc-amount-min">
                <Input
                  id="pc-amount-min"
                  type="number"
                  min="0"
                  step="0.01"
                  value={filters.amount_min}
                  onChange={(event) => setFilters({ ...filters, amount_min: event.target.value })}
                />
              </Field>
              <Field label="Amount to" htmlFor="pc-amount-max">
                <Input
                  id="pc-amount-max"
                  type="number"
                  min="0"
                  step="0.01"
                  value={filters.amount_max}
                  onChange={(event) => setFilters({ ...filters, amount_max: event.target.value })}
                />
              </Field>
              <Field label="Search" className="sm:col-span-2" htmlFor="pc-search">
                <Input
                  id="pc-search"
                  placeholder="Description, counterparty, reference or provider ID"
                  value={filters.search}
                  onChange={(event) => setFilters({ ...filters, search: event.target.value })}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      setAppliedFilters(filters);
                      void loadTransactions(filters);
                    }
                  }}
                />
              </Field>
              <div className="flex flex-wrap items-end gap-3">
                <label className="flex items-center gap-2 pb-2 text-[11px] font-medium text-slate-600">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 rounded border-slate-300"
                    checked={filters.include_duplicates}
                    onChange={(event) =>
                      setFilters({ ...filters, include_duplicates: event.target.checked })
                    }
                  />
                  Show blocked duplicates
                </label>
                <Button
                  size="sm"
                  icon={Search}
                  loading={txnLoading}
                  onClick={() => {
                    setAppliedFilters(filters);
                    void loadTransactions(filters);
                  }}
                >
                  Apply
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setFilters(EMPTY_FILTERS);
                    setAppliedFilters(EMPTY_FILTERS);
                    void loadTransactions(EMPTY_FILTERS);
                  }}
                >
                  Clear
                </Button>
              </div>
            </CardBody>
          </Card>

          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <Badge tone="slate">{txnData?.total ?? overview?.summary.transactions ?? 0} rows</Badge>
            <Badge tone="green">
              Incoming {money(txnData?.summary.incoming_total ?? overview?.summary.incoming_total ?? 0)}
            </Badge>
            <Badge tone="red">
              Outgoing {money(txnData?.summary.outgoing_total ?? overview?.summary.outgoing_total ?? 0)}
            </Badge>
            <span>Provider references are preserved exactly as supplied.</span>
          </div>

          <Card>
            <CardBody className="pt-4">
              {txnLoading && !txnData ? (
                <div className="flex items-center gap-2 py-12 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading transactions…
                </div>
              ) : !txnData || txnData.items.length === 0 ? (
                <EmptyState
                  icon={Wallet}
                  title="No transactions in this view"
                  description="Sync a connected PayPal account, track a Google Pay merchant reference or import a bank statement."
                />
              ) : (
                <TableWrap>
                  <THead>
                    <TR>
                      <TH>Date</TH>
                      <TH>Provider</TH>
                      <TH>Description / reference</TH>
                      <TH>Direction</TH>
                      <TH>Amount</TH>
                      <TH>Status</TH>
                      <TH>Matched invoice</TH>
                      <TH>Reconciliation</TH>
                      <TH />
                    </TR>
                  </THead>
                  <TBody>
                    {txnData.items.map((txn) => (
                      <TR key={txn.id}>
                        <TD className="whitespace-nowrap">{formatDate(txn.occurred_on)}</TD>
                        <TD>
                          <div className="flex flex-col gap-0.5">
                            <Badge tone={providerTone(txn.provider)}>{txn.provider_label}</Badge>
                            <span className="text-[10px] text-slate-400">
                              {labelize(txn.environment)}
                            </span>
                          </div>
                        </TD>
                        <TD className="max-w-[280px]">
                          <p className="truncate font-medium text-ink-900" title={txn.description || ""}>
                            {txn.description || "—"}
                          </p>
                          <p className="truncate text-[10px] text-slate-400" title={txn.reference || ""}>
                            {txn.reference || txn.external_id}
                          </p>
                          {txn.duplicate_of_id && (
                            <Badge tone="red" className="mt-1">
                              Duplicate — blocked
                            </Badge>
                          )}
                        </TD>
                        <TD>
                          <span className="inline-flex items-center gap-1 text-[11px] font-medium">
                            {txn.direction === "incoming" ? (
                              <ArrowDownToLine className="h-3 w-3 text-emerald-600" />
                            ) : (
                              <ArrowUpFromLine className="h-3 w-3 text-rose-600" />
                            )}
                            {labelize(txn.direction)}
                          </span>
                        </TD>
                        <TD
                          className={
                            txn.direction === "incoming"
                              ? "whitespace-nowrap font-semibold text-emerald-700"
                              : "whitespace-nowrap font-semibold text-rose-700"
                          }
                        >
                          {signedMoney(txn)}
                          <span className="ml-1 text-[10px] font-normal text-slate-400">
                            {txn.currency}
                          </span>
                        </TD>
                        <TD>
                          <Badge
                            tone={
                              txn.status === "completed"
                                ? "green"
                                : ["failed", "reversed", "chargeback"].includes(txn.status)
                                  ? "red"
                                  : "amber"
                            }
                          >
                            {labelize(txn.status)}
                          </Badge>
                        </TD>
                        <TD>
                          {txn.matched_invoice_number ? (
                            <span className="font-medium text-ink-900">
                              {txn.matched_invoice_number}
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                          {txn.accounting_draft_id && (
                            <Badge tone="blue" className="ml-1">
                              Draft #{txn.accounting_draft_id}
                            </Badge>
                          )}
                        </TD>
                        <TD>
                          <Badge
                            tone={reconciliationTone(txn.reconciliation_status)}
                            title={txn.match_reason || ""}
                          >
                            {labelize(txn.reconciliation_status)}
                          </Badge>
                          {txn.match_score !== null && txn.match_score > 0 && (
                            <span className="ml-1 text-[10px] text-slate-400">
                              score {txn.match_score}
                            </span>
                          )}
                        </TD>
                        <TD>
                          <Button size="sm" variant="outline" onClick={() => void openReview(txn)}>
                            Review
                          </Button>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </TableWrap>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {tab === "statements" && accountant && (
        <div className="space-y-4">
          <Callout tone="amber" icon={ShieldAlert} title="Imported rows stay unverified">
            CSV, Excel and machine-readable PDF statements are parsed without OCR. Scanned images are
            rejected. Correct uncertain rows before importing; the original file is encrypted at rest
            and every row is still reviewed before an invoice match is approved.
          </Callout>

          <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
            <Card>
              <CardHeader
                title="Upload a bank statement"
                description="Select the business and upload one statement at a time."
                icon={Upload}
              />
              <CardBody className="space-y-3 pt-3">
                <Field label="Account label" htmlFor="pc-bank-label" hint="Optional, for example HDFC current account.">
                  <Input
                    id="pc-bank-label"
                    value={bankAccountLabel}
                    onChange={(event) => setBankAccountLabel(event.target.value)}
                    placeholder="HDFC current account"
                  />
                </Field>
                <Field
                  label="Statement file"
                  htmlFor="pc-bank-file"
                  hint="CSV, XLSX, XLS, TXT or a PDF with machine-readable text. Maximum size follows the backend upload limit."
                >
                  <Input
                    key={bankInputKey}
                    id="pc-bank-file"
                    type="file"
                    accept=".csv,.xlsx,.xls,.txt,.pdf"
                    onChange={(event) => {
                      const file = event.target.files?.[0] ?? null;
                      setBankFile(file);
                      setBankPreview(null);
                      setBankRows([]);
                      setBankCorrections({});
                    }}
                  />
                </Field>
                {bankFile && (
                  <p className="text-[11px] text-slate-500">
                    {bankFile.name} · {formatBytes(bankFile.size)}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    icon={FileSpreadsheet}
                    loading={bankBusy && !bankPreview}
                    disabled={!bankFile}
                    onClick={() => void previewStatement()}
                  >
                    Preview rows
                  </Button>
                  {bankPreview && (
                    <Button
                      variant="outline"
                      icon={CheckCircle2}
                      loading={bankBusy}
                      onClick={() => void importStatement()}
                    >
                      Import statement
                    </Button>
                  )}
                </div>
                <p className="text-[11px] leading-relaxed text-slate-400">
                  Importing never overwrites earlier statements. The same file and identical rows are
                  detected and skipped.
                </p>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Import history"
                description="Encrypted originals and row counts for this client."
                icon={History}
              />
              <CardBody className="pt-3">
                {bankImports.length === 0 ? (
                  <p className="py-6 text-center text-xs text-slate-500">
                    No statements imported for this client yet.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {bankImports.map((record) => (
                      <div key={record.id} className="rounded-lg border border-slate-200 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="truncate text-xs font-semibold text-ink-900" title={record.filename}>
                            {record.filename}
                          </p>
                          <Badge tone={record.uncertain_count ? "amber" : "green"}>
                            {record.uncertain_count} to review
                          </Badge>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500">
                          {record.account_label || "No account label"} · {record.row_count} rows ·{" "}
                          {record.duplicate_count} duplicates skipped
                        </p>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          {labelize(record.parsing_format)} · imported {formatDateTime(record.created_at)} ·{" "}
                          SHA-256 {record.source_sha256.slice(0, 12)}…
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>
          </div>

          {bankPreview && (
            <Card>
              <CardHeader
                title={`Preview · ${bankPreview.filename}`}
                description={`${bankPreview.summary.rows} rows · ${bankPreview.summary.valid} valid · ${bankPreview.summary.uncertain} uncertain · ${bankPreview.summary.duplicates} duplicates`}
                icon={FileSpreadsheet}
                actions={
                  <Badge tone={bankPreview.summary.uncertain ? "amber" : "green"} dot>
                    {bankPreview.summary.uncertain ? "Review required" : "Ready to import"}
                  </Badge>
                }
              />
              <CardBody className="space-y-3 pt-3">
                {bankPreview.warnings.length > 0 && (
                  <Callout tone="amber" title="Parser warnings">
                    <ul className="list-disc space-y-0.5 pl-4">
                      {bankPreview.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </Callout>
                )}
                <p className="text-[11px] text-slate-500">{bankPreview.note}</p>
                <TableWrap>
                  <THead>
                    <TR>
                      <TH>Row</TH>
                      <TH>Date</TH>
                      <TH>Description</TH>
                      <TH>Reference</TH>
                      <TH>Debit</TH>
                      <TH>Credit</TH>
                      <TH>Confidence</TH>
                      <TH>Checks</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {bankRows.map((row) => {
                      const debit = Number(row.debit) || 0;
                      const credit = Number(row.credit) || 0;
                      const compensated = debit > 0 || credit > 0;
                      return (
                        <TR key={row.row}>
                          <TD className="text-slate-400">{row.row}</TD>
                          <TD>
                            <Input
                              type="date"
                              className="min-w-[130px]"
                              value={row.txn_date ?? ""}
                              onChange={(event) =>
                                updateBankRow(row.row, "txn_date", event.target.value)
                              }
                            />
                          </TD>
                          <TD>
                            <Input
                              className="min-w-[200px]"
                              value={row.description}
                              onChange={(event) =>
                                updateBankRow(row.row, "description", event.target.value)
                              }
                            />
                          </TD>
                          <TD>
                            <Input
                              className="min-w-[140px]"
                              value={row.reference ?? ""}
                              onChange={(event) =>
                                updateBankRow(row.row, "reference", event.target.value)
                              }
                            />
                          </TD>
                          <TD>
                            <Input
                              type="number"
                              min="0"
                              step="0.01"
                              className="min-w-[110px]"
                              value={row.debit}
                              onChange={(event) => updateBankRow(row.row, "debit", event.target.value)}
                            />
                          </TD>
                          <TD>
                            <Input
                              type="number"
                              min="0"
                              step="0.01"
                              className="min-w-[110px]"
                              value={row.credit}
                              onChange={(event) => updateBankRow(row.row, "credit", event.target.value)}
                            />
                          </TD>
                          <TD>
                            <Badge tone={row.confidence >= 100 ? "green" : row.confidence >= 50 ? "amber" : "red"}>
                              {row.confidence}%
                            </Badge>
                            {row.duplicate && (
                              <Badge tone="red" className="ml-1">
                                Duplicate
                              </Badge>
                            )}
                          </TD>
                          <TD className="max-w-[240px]">
                            {!compensated && (
                              <p className="text-[10px] font-medium text-rose-600">
                                Enter a debit or credit.
                              </p>
                            )}
                            {row.issues.length === 0 && compensated ? (
                              <p className="text-[10px] text-slate-400">No parser issues.</p>
                            ) : (
                              row.issues.map((issue) => (
                                <p key={issue} className="text-[10px] text-amber-700">
                                  {issue}
                                </p>
                              ))
                            )}
                          </TD>
                        </TR>
                      );
                    })}
                  </TBody>
                </TableWrap>
                {Object.keys(bankCorrections).length > 0 && (
                  <p className="text-[11px] text-slate-500">
                    {Object.keys(bankCorrections).length} row(s) corrected. Corrections mark the row as
                    reviewed but do not replace the encrypted original.
                  </p>
                )}
              </CardBody>
            </Card>
          )}
        </div>
      )}

      {tab === "google-pay" && (
        <div className="space-y-4">
          <Callout tone="amber" icon={Smartphone} title="Limited by Google's official APIs">
            {gpEligibility?.summary ||
              "Google Pay does not expose a public API that lists or downloads every consumer Google Pay transaction. Only merchant references you enter can be tracked."}
          </Callout>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader
                title="Official eligibility check"
                description="This deployment never asks for Google passwords, UPI PINs, OTPs or card credentials."
                icon={KeyRound}
              />
              <CardBody className="space-y-3 pt-3">
                {gpEligibility ? (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg border border-slate-200 p-3">
                        <p className="text-[11px] text-slate-500">History API</p>
                        <p className="mt-1 text-xs font-semibold text-rose-700">
                          {gpEligibility.history_api ? "Available" : "Not available"}
                        </p>
                      </div>
                      <div className="rounded-lg border border-slate-200 p-3">
                        <p className="text-[11px] text-slate-500">Transaction detail API</p>
                        <p className="mt-1 text-xs font-semibold text-rose-700">
                          {gpEligibility.transaction_detail_api ? "Available" : "Not available"}
                        </p>
                      </div>
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                        Requirements
                      </p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-slate-600">
                        {gpEligibility.requirements.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                        Not supported
                      </p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-slate-600">
                        {gpEligibility.blocked.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                    <Button variant="outline" icon={Search} loading={gpLookupBusy} onClick={() => void lookupGooglePay()}>
                      Try official lookup
                    </Button>
                    {gpLookupError && (
                      <Callout tone="slate" icon={ShieldAlert} title="Lookup response">
                        {gpLookupError}
                      </Callout>
                    )}
                  </>
                ) : (
                  <div className="flex items-center gap-2 py-6 text-xs text-slate-500">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking eligibility…
                  </div>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Track a merchant reference"
                description="For businesses with an official Google Pay merchant flow. Records are marked as not verified through Google."
                icon={Smartphone}
              />
              <CardBody className="space-y-3 pt-3">
                {gpConnection && (
                  <p className="text-[11px] text-slate-500">
                    Connected merchant {gpConnection.merchant_id || gpConnection.account_hint} ·{" "}
                    {gpConnection.counts.transactions} tracked records
                  </p>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Google Pay merchant ID" required htmlFor="gp-merchant">
                    <Input
                      id="gp-merchant"
                      value={gpTrack.merchant_id}
                      onChange={(event) =>
                        setGpTrack({ ...gpTrack, merchant_id: event.target.value })
                      }
                      placeholder="Merchant ID from Google Pay"
                    />
                  </Field>
                  <Field label="Merchant transaction ID" required htmlFor="gp-txn">
                    <Input
                      id="gp-txn"
                      value={gpTrack.google_transaction_id}
                      onChange={(event) =>
                        setGpTrack({ ...gpTrack, google_transaction_id: event.target.value })
                      }
                      placeholder="Official merchant reference"
                    />
                  </Field>
                  <Field label="Amount" required htmlFor="gp-amount">
                    <Input
                      id="gp-amount"
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={gpTrack.amount}
                      onChange={(event) => setGpTrack({ ...gpTrack, amount: event.target.value })}
                    />
                  </Field>
                  <Field label="Currency" htmlFor="gp-currency">
                    <Input
                      id="gp-currency"
                      maxLength={3}
                      value={gpTrack.currency}
                      onChange={(event) =>
                        setGpTrack({ ...gpTrack, currency: event.target.value.toUpperCase() })
                      }
                    />
                  </Field>
                  <Field label="Received on" required htmlFor="gp-date">
                    <Input
                      id="gp-date"
                      type="date"
                      value={gpTrack.occurred_on}
                      onChange={(event) =>
                        setGpTrack({ ...gpTrack, occurred_on: event.target.value })
                      }
                    />
                  </Field>
                  <Field label="Status" htmlFor="gp-status">
                    <Select
                      id="gp-status"
                      value={gpTrack.status}
                      onChange={(event) => setGpTrack({ ...gpTrack, status: event.target.value })}
                    >
                      {["unknown", "completed", "pending", "failed", "refunded"].map((status) => (
                        <option key={status} value={status}>
                          {labelize(status)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="UPI reference" htmlFor="gp-upi">
                    <Input
                      id="gp-upi"
                      value={gpTrack.upi_reference}
                      onChange={(event) =>
                        setGpTrack({ ...gpTrack, upi_reference: event.target.value })
                      }
                      placeholder="If officially available"
                    />
                  </Field>
                  <Field label="Outlet" htmlFor="gp-outlet">
                    <Input
                      id="gp-outlet"
                      value={gpTrack.outlet_label}
                      onChange={(event) =>
                        setGpTrack({ ...gpTrack, outlet_label: event.target.value })
                      }
                    />
                  </Field>
                </div>
                <Field label="Description" htmlFor="gp-description">
                  <Textarea
                    id="gp-description"
                    rows={2}
                    value={gpTrack.description}
                    onChange={(event) =>
                      setGpTrack({ ...gpTrack, description: event.target.value })
                    }
                    placeholder="What does this merchant reference represent?"
                  />
                </Field>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    icon={BadgeCheck}
                    loading={gpTrackBusy}
                    disabled={
                      !gpTrack.merchant_id.trim() ||
                      !gpTrack.google_transaction_id.trim() ||
                      !gpTrack.amount
                    }
                    onClick={() => void trackGooglePay()}
                  >
                    Record merchant reference
                  </Button>
                  <span className="text-[11px] text-slate-400">
                    Duplicate references are returned instead of creating a second transaction.
                  </span>
                </div>
              </CardBody>
            </Card>
          </div>
        </div>
      )}

      <Modal
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        title="Connect a payment provider"
        description="Credentials are never entered in the browser. PayPal reads server-side environment secrets; Google Pay records only a merchant ID."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setConnectOpen(false)} disabled={connectBusy}>
              Cancel
            </Button>
            <Button
              icon={PlugZap}
              loading={connectBusy}
              disabled={!connectForm.consent}
              onClick={() => void submitConnection()}
            >
              Save connection
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {actionError && (
            <Callout tone="red" title="Could not save the connection">
              {actionError}
            </Callout>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Provider" htmlFor="pc-connect-provider">
              <Select
                id="pc-connect-provider"
                value={connectForm.provider}
                onChange={(event) =>
                  setConnectForm({
                    ...connectForm,
                    provider: event.target.value as "paypal" | "google_pay",
                  })
                }
              >
                <option value="paypal">PayPal Transaction Search</option>
                <option value="google_pay">Google Pay merchant records</option>
              </Select>
            </Field>
            {connectForm.provider === "paypal" ? (
              <Field
                label="Environment"
                htmlFor="pc-connect-env"
                hint="The backend must hold credentials for this environment."
              >
                <Select
                  id="pc-connect-env"
                  value={connectForm.environment}
                  onChange={(event) =>
                    setConnectForm({ ...connectForm, environment: event.target.value })
                  }
                >
                  <option value="sandbox">Sandbox</option>
                  <option value="live">Live</option>
                </Select>
              </Field>
            ) : (
              <Field
                label="Google Pay merchant ID"
                required
                htmlFor="pc-connect-merchant"
                hint="No Google password, UPI PIN or OTP is requested."
              >
                <Input
                  id="pc-connect-merchant"
                  value={connectForm.merchant_id}
                  onChange={(event) =>
                    setConnectForm({ ...connectForm, merchant_id: event.target.value })
                  }
                  placeholder="Official merchant ID"
                />
              </Field>
            )}
            <Field label="Label" htmlFor="pc-connect-label" hint="Optional name shown in this workspace.">
              <Input
                id="pc-connect-label"
                value={connectForm.label}
                onChange={(event) => setConnectForm({ ...connectForm, label: event.target.value })}
                placeholder={connectForm.provider === "paypal" ? "PayPal Sandbox" : "Google Pay"}
              />
            </Field>
            <Field label="Outlet" htmlFor="pc-connect-outlet" hint="Optional business outlet or store.">
              <Input
                id="pc-connect-outlet"
                value={connectForm.outlet_label}
                onChange={(event) =>
                  setConnectForm({ ...connectForm, outlet_label: event.target.value })
                }
              />
            </Field>
          </div>

          <Field label="Note" htmlFor="pc-connect-note">
            <Textarea
              id="pc-connect-note"
              rows={2}
              value={connectForm.note}
              onChange={(event) => setConnectForm({ ...connectForm, note: event.target.value })}
              placeholder="Who authorised this connection and for which account?"
            />
          </Field>

          {accountant && (
            <Callout tone="slate" title="Client scope">
              This connection belongs to the selected client engagement only. A second business must
              never reuse another merchant's credentials.
            </Callout>
          )}
          {connectForm.provider === "paypal" && (
            <Callout tone="blue" title="PayPal eligibility">
              PayPal Transaction Search reads only the merchant that owns the backend credentials.
              Searching another merchant's history requires PayPal partner-network approval. Each
              sync window is limited to 31 days.
            </Callout>
          )}

          <label className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-[12px] text-slate-600">
            <input
              type="checkbox"
              className="mt-0.5 h-3.5 w-3.5 rounded border-slate-300"
              checked={connectForm.consent}
              onChange={(event) =>
                setConnectForm({ ...connectForm, consent: event.target.checked })
              }
            />
            <span>
              I confirm this business is authorised to connect the selected provider account, and I
              consent to read its official transaction history. I understand that no banking
              password, UPI PIN or OTP will ever be requested.
            </span>
          </label>
        </div>
      </Modal>

      <Modal
        open={Boolean(syncTarget)}
        onClose={() => setSyncTarget(null)}
        title="Sync PayPal history"
        description="Official Transaction Search. Windows over 31 days are split automatically."
        size="md"
        footer={
          <>
            <Button variant="outline" onClick={() => setSyncTarget(null)} disabled={syncBusy}>
              Cancel
            </Button>
            <Button
              icon={RefreshCw}
              loading={syncBusy}
              disabled={!syncForm.start_date || !syncForm.end_date}
              onClick={() => void submitSync()}
            >
              Run sync
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {actionError && (
            <Callout tone="red" title="Sync failed">
              {actionError}
            </Callout>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Start date" required htmlFor="pc-sync-start">
              <Input
                id="pc-sync-start"
                type="date"
                value={syncForm.start_date}
                onChange={(event) => setSyncForm({ ...syncForm, start_date: event.target.value })}
              />
            </Field>
            <Field label="End date" required htmlFor="pc-sync-end">
              <Input
                id="pc-sync-end"
                type="date"
                value={syncForm.end_date}
                onChange={(event) => setSyncForm({ ...syncForm, end_date: event.target.value })}
              />
            </Field>
          </div>
          <div className="flex flex-wrap gap-2">
            {[7, 30, 90].map((days) => (
              <Button
                key={days}
                size="sm"
                variant="outline"
                onClick={() => setSyncForm(syncRange(days))}
              >
                Last {days} days
              </Button>
            ))}
          </div>
          <Callout tone="slate" icon={ShieldAlert} title="Repeated syncs are safe">
            Provider transaction IDs are unique per connection. Re-running the same window returns
            duplicates instead of creating second financial records.
          </Callout>
        </div>
      </Modal>

      <Modal
        open={reviewOpen && Boolean(reviewTxn)}
        onClose={() => {
          setReviewOpen(false);
          setReviewTxn(null);
        }}
        title={reviewTxn ? `${reviewTxn.provider_label} · ${signedMoney(reviewTxn)}` : "Transaction"}
        description={
          reviewTxn
            ? `${formatDate(reviewTxn.occurred_on)} · ${labelize(reviewTxn.status)} · ${labelize(reviewTxn.reconciliation_status)}`
            : undefined
        }
        size="xl"
        footer={
          reviewTxn ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                disabled={reviewBusy}
                onClick={() => void submitReconcile("suggest")}
              >
                Suggest match
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={reviewBusy}
                onClick={() => void submitReconcile("reject")}
              >
                Reject
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={reviewBusy}
                onClick={() => void submitReconcile("not_applicable")}
              >
                Mark not applicable
              </Button>
              {(reviewTxn.reconciliation_status === "rejected" ||
                reviewTxn.reconciliation_status === "not_applicable" ||
                reviewTxn.reconciliation_status === "matched") && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={reviewBusy}
                  onClick={() => void submitReconcile("reset")}
                >
                  Reset review
                </Button>
              )}
              <Button
                icon={CheckCircle2}
                loading={reviewBusy}
                disabled={
                  (!canManageConnections && accountant) ||
                  reviewTxn.status !== "completed" ||
                  (!isRefund(reviewTxn) && !reviewInvoice)
                }
                title={
                  accountant && !isSeniorAccountant
                    ? "A senior accountant must approve matches."
                    : reviewTxn.status !== "completed"
                      ? "Only completed provider transactions can be approved."
                      : !isRefund(reviewTxn) && !reviewInvoice
                        ? "Select the invoice this payment settles."
                        : undefined
                }
                onClick={() => void submitReconcile("approve")}
              >
                Approve & record
              </Button>
            </>
          ) : undefined
        }
      >
        {reviewTxn && (
          <div className="space-y-4">
            {actionError && (
              <Callout tone="red" title="Review action failed">
                {actionError}
              </Callout>
            )}
            {reviewTxn.duplicate_of_id && (
              <Callout tone="red" icon={ShieldAlert} title="Duplicate blocked">
                This row duplicates transaction #{reviewTxn.duplicate_of_id} and cannot be approved.
              </Callout>
            )}
            {isRefund(reviewTxn) && (
              <Callout tone="amber" icon={ArrowUpFromLine} title="Refund or reversal">
                Approving records a negative payment against the original transaction when it can be
                found, restores the invoice balance, and never creates a second customer receipt.
              </Callout>
            )}
            {reviewTxn.direction === "outgoing" && !isRefund(reviewTxn) && (
              <Callout tone="slate" icon={ArrowUpFromLine} title="Outgoing payment">
                Outgoing provider payments cannot be matched to a customer invoice. Reject or mark
                them not applicable after review.
              </Callout>
            )}
            {accountant && !isSeniorAccountant && (
              <Callout tone="slate" icon={ShieldCheck} title="Junior review scope">
                You can suggest, reject or mark transactions. A senior accountant must approve the
                final invoice match.
              </Callout>
            )}

            <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-[11px] sm:grid-cols-2">
              <div>
                <p className="text-slate-400">Provider ID</p>
                <p className="break-all font-medium text-ink-900">{reviewTxn.external_id}</p>
              </div>
              <div>
                <p className="text-slate-400">Reference</p>
                <p className="break-all font-medium text-ink-900">{reviewTxn.reference || "—"}</p>
              </div>
              <div>
                <p className="text-slate-400">Counterparty</p>
                <p className="font-medium text-ink-900">{reviewTxn.counterparty || "—"}</p>
              </div>
              <div>
                <p className="text-slate-400">Type / direction</p>
                <p className="font-medium text-ink-900">
                  {labelize(reviewTxn.txn_type)} · {labelize(reviewTxn.direction)}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Fee / net</p>
                <p className="font-medium text-ink-900">
                  {moneyExact(reviewTxn.fee_amount, reviewTxn.currency)} ·{" "}
                  {moneyExact(reviewTxn.net_amount, reviewTxn.currency)}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Outlet</p>
                <p className="font-medium text-ink-900">{reviewTxn.outlet_label || "—"}</p>
              </div>
              <div className="sm:col-span-2">
                <p className="text-slate-400">Description</p>
                <p className="font-medium text-ink-900">{reviewTxn.description || "—"}</p>
              </div>
            </div>

            {!isRefund(reviewTxn) && reviewTxn.direction === "incoming" && (
              <section className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Suggested invoices
                  </h3>
                  <span className="text-[11px] text-slate-400">
                    Suggestions never approve themselves.
                  </span>
                </div>
                {reviewCandidates.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-slate-300 p-3 text-[11px] text-slate-500">
                    No automatic candidates for this transaction. Choose an open invoice manually.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {reviewCandidates.map((candidate) => (
                      <button
                        key={candidate.invoice_id}
                        type="button"
                        onClick={() => setReviewInvoiceId(candidate.invoice_id)}
                        className={`w-full rounded-lg border p-3 text-left transition ${
                          reviewInvoiceId === candidate.invoice_id
                            ? "border-brand-400 bg-brand-50/60"
                            : "border-slate-200 hover:border-slate-300"
                        }`}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-ink-900">
                            {candidate.invoice_number} · {candidate.customer_name || "Customer"}
                          </p>
                          <div className="flex items-center gap-1">
                            <Badge tone={candidate.score >= 60 ? "green" : "amber"}>
                              score {candidate.score}
                            </Badge>
                            {candidate.existing_payment_id && (
                              <Badge tone="blue">Payment #{candidate.existing_payment_id}</Badge>
                            )}
                          </div>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500">
                          Outstanding {money(candidate.outstanding_amount)} · issued{" "}
                          {formatDate(candidate.issue_date)}
                        </p>
                        <p className="mt-0.5 text-[11px] text-slate-400">{candidate.reason}</p>
                      </button>
                    ))}
                  </div>
                )}
                <Field label="Invoice to settle" required htmlFor="pc-review-invoice">
                  <Select
                    id="pc-review-invoice"
                    value={reviewInvoiceId ?? ""}
                    onChange={(event) =>
                      setReviewInvoiceId(Number(event.target.value) || null)
                    }
                  >
                    <option value="">Select an invoice…</option>
                    {reviewInvoices.map((invoice) => (
                      <option key={invoice.id} value={invoice.id}>
                        {invoice.number} · {invoice.customer_name || "Customer"} ·{" "}
                        {invoice.outstanding !== ""
                          ? `outstanding ${money(invoice.outstanding)}`
                          : `total ${money(invoice.total)}`}
                      </option>
                    ))}
                  </Select>
                </Field>
                {reviewInvoices.length === 0 && (
                  <p className="text-[11px] text-amber-700">
                    No open invoices were returned. Issue an invoice or import the statement after
                    the business ledger is linked.
                  </p>
                )}
              </section>
            )}

            <Field label="Review note" htmlFor="pc-review-note" hint="Included in the audit trail.">
              <Textarea
                id="pc-review-note"
                rows={2}
                value={reviewNote}
                onChange={(event) => setReviewNote(event.target.value)}
                placeholder="Why is this match correct, or why was it rejected?"
              />
            </Field>

            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Reconciliation history
              </h3>
              {reviewEvents.length === 0 ? (
                <p className="text-[11px] text-slate-400">No review events recorded yet.</p>
              ) : (
                <div className="space-y-2">
                  {reviewEvents.map((event) => (
                    <div key={event.id} className="flex items-start gap-2 rounded-lg border border-slate-100 p-2">
                      <History className="mt-0.5 h-3.5 w-3.5 text-slate-400" />
                      <div className="min-w-0 text-[11px]">
                        <p className="font-medium text-ink-900">
                          {labelize(event.action)}
                          {event.actor ? ` · ${event.actor}` : ""}
                        </p>
                        {event.note && <p className="text-slate-500">{event.note}</p>}
                        <p className="text-[10px] text-slate-400">
                          {formatDateTime(event.created_at)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={Boolean(disconnectTarget)}
        onClose={() => setDisconnectTarget(null)}
        onConfirm={() => void submitDisconnect()}
        title="Disconnect this provider?"
        description={
          disconnectTarget
            ? `${disconnectTarget.label} will stop syncing. Imported transactions and the audit trail are kept.`
            : undefined
        }
        confirmLabel="Disconnect"
        tone="danger"
        loading={disconnectBusy}
      />
    </div>
  );
}
