import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  BadgeCheck,
  Calculator,
  CheckCircle2,
  Download,
  FileText,
  Inbox,
  Plus,
  RefreshCw,
  Search,
  Send,
  Trash2,
  XCircle,
} from "lucide-react";
import { downloadFile, get, getErrorMessage, patch, post } from "../../lib/api";
import type {
  AccountingQuotation,
  AccountingServiceKey,
  PaymentFrequency,
  QuotationLine,
  QuotationStatus,
  QuotationWorkspace,
  QuotationWorkspaceRequest,
} from "../../lib/accountingTypes";
import type { PricingAddon } from "../../lib/pricingTypes";
import { labelize } from "../../lib/accounting";
import { formatDate, money, number } from "../../lib/utils";
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
  StatCard,
  Textarea,
} from "../../components/ui";
import { StatusBadge } from "../../components/accounting/AccountingUI";

type EditorStatus = QuotationStatus | "new";

interface EditorLine {
  rowKey: string;
  kind: "service" | "addon" | "custom";
  key: string | null;
  label: string;
  description: string;
  service: AccountingServiceKey | null;
  amount: string;
  cadence: "annual" | "one_time";
}

interface EditorState {
  id: number | null;
  number: string | null;
  status: EditorStatus;
  enquiryId: number | null;
  clientId: number | null;
  businessName: string;
  contactName: string;
  email: string;
  annualTurnover: string;
  lines: EditorLine[];
  discountType: "none" | "percent" | "amount";
  discountValue: string;
  discountNote: string;
  paymentFrequency: PaymentFrequency;
  validityDays: string;
  terms: string;
  approvedByName: string | null;
  sentAt: string | null;
}

const STATUS_FILTERS: (QuotationStatus | "")[] = [
  "",
  "draft",
  "approved",
  "sent",
  "accepted",
  "declined",
  "rejected",
  "expired",
];

function rowKey(): string {
  return Math.random().toString(36).slice(2, 10);
}

function amountOf(value: string | number | null | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function computePreview(editor: EditorState) {
  const subtotal = editor.lines.reduce((sum, line) => sum + amountOf(line.amount), 0);
  const value = amountOf(editor.discountValue);
  const discount =
    editor.discountType === "percent"
      ? (subtotal * value) / 100
      : editor.discountType === "amount"
        ? Math.min(value, subtotal)
        : 0;
  const total = Math.max(subtotal - discount, 0);
  const periods: Record<PaymentFrequency, number> = {
    monthly: 12,
    quarterly: 4,
    annual: 1,
    one_time: 1,
  };
  return {
    subtotal,
    discount,
    total,
    monthly: total / 12,
    perPeriod: total / periods[editor.paymentFrequency],
  };
}

function editorFromQuotation(quotation: AccountingQuotation): EditorState {
  return {
    id: quotation.id,
    number: quotation.number,
    status: quotation.status,
    enquiryId: quotation.enquiry_id,
    clientId: quotation.client_id,
    businessName: quotation.enquiry?.business_name || quotation.client_name || "Client",
    contactName: quotation.enquiry?.contact_name || "",
    email: quotation.enquiry?.email || "",
    annualTurnover: quotation.annual_turnover ? String(quotation.annual_turnover) : "",
    lines: (quotation.line_items ?? []).map((line: QuotationLine) => ({
      rowKey: rowKey(),
      kind: line.kind,
      key: line.key,
      label: line.label,
      description: line.description ?? "",
      service: line.service,
      amount: String(line.amount ?? "0"),
      cadence: line.cadence,
    })),
    discountType: quotation.discount_type,
    discountValue: String(quotation.discount_value ?? "0"),
    discountNote: quotation.discount_note ?? "",
    paymentFrequency: quotation.payment_frequency,
    validityDays: String(quotation.validity_days ?? ""),
    terms: quotation.terms ?? "",
    approvedByName: quotation.approved_by_name ?? null,
    sentAt: quotation.sent_at,
  };
}

function editorFromRequest(
  request: QuotationWorkspaceRequest,
  services: { key: string; name: string }[],
  defaultValidityDays = 15,
): EditorState {
  const labels = new Map(services.map((service) => [service.key, service.name]));
  const selected = request.services.filter((key) => key !== "itr_filing");
  const keys = selected.length ? selected : (["bookkeeping"] as AccountingServiceKey[]);
  return {
    id: null,
    number: null,
    status: "new",
    enquiryId: request.id,
    clientId: null,
    businessName: request.business_name,
    contactName: request.contact_name,
    email: request.email,
    annualTurnover: request.annual_turnover ? String(request.annual_turnover) : "",
    lines: keys.map((key) => ({
      rowKey: rowKey(),
      kind: "service" as const,
      key,
      label: labels.get(key) ?? labelize(key),
      description: "",
      service: key,
      amount: "0",
      cadence: "annual" as const,
    })),
    discountType: "none",
    discountValue: "0",
    discountNote: "",
    paymentFrequency: "monthly",
    validityDays: String(defaultValidityDays),
    terms: "",
    approvedByName: null,
    sentAt: null,
  };
}

export function AccountantQuotationsPage() {
  const [workspace, setWorkspace] = useState<QuotationWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<QuotationStatus | "">("");
  const [search, setSearch] = useState("");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectNote, setRejectNote] = useState("");
  const [addServiceKey, setAddServiceKey] = useState("");
  const [addAddonKey, setAddAddonKey] = useState("");
  const [searchParams] = useSearchParams();
  const openedFromQuery = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (search.trim()) params.set("search", search.trim());
      const query = params.toString();
      const data = await get<QuotationWorkspace>(
        `/accounting/senior/quotation-workspace${query ? `?${query}` : ""}`,
      );
      setWorkspace(data);
      setEditor((current) => {
        if (!current?.id) return current;
        const fresh = data.quotations.find((row) => row.id === current.id);
        return fresh ? editorFromQuotation(fresh) : current;
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [status, search]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!workspace || openedFromQuery.current) return;
    const quotationId = Number(searchParams.get("quotation"));
    const enquiryId = Number(searchParams.get("enquiry"));
    if (quotationId) {
      const found = workspace.quotations.find((row) => row.id === quotationId);
      if (found) {
        setEditor(editorFromQuotation(found));
        openedFromQuery.current = true;
      }
    } else if (enquiryId) {
      const request = workspace.requests.find((row) => row.id === enquiryId);
      if (request) {
        setEditor(
          editorFromRequest(
            request,
            workspace.catalogue.services,
            workspace.settings.quote_validity_days,
          ),
        );
        openedFromQuery.current = true;
      }
    }
  }, [workspace, searchParams]);

  const preview = editor ? computePreview(editor) : null;
  const readOnly =
    editor !== null && ["sent", "accepted", "declined", "rejected"].includes(editor.status);

  const requestRows = useMemo(() => {
    if (!workspace) return [];
    const needle = search.trim().toLowerCase();
    return workspace.requests
      .filter((row) => ["new", "contacted"].includes(row.status))
      .filter(
        (row) =>
          !needle ||
          row.business_name.toLowerCase().includes(needle) ||
          row.contact_name.toLowerCase().includes(needle) ||
          row.reference.toLowerCase().includes(needle),
      )
      .slice(0, 8);
  }, [workspace, search]);

  const setLine = (key: string, changes: Partial<EditorLine>) => {
    setEditor((current) =>
      current
        ? {
            ...current,
            lines: current.lines.map((line) =>
              line.rowKey === key ? { ...line, ...changes } : line,
            ),
          }
        : current,
    );
  };

  const addService = () => {
    if (!editor || !workspace || !addServiceKey) return;
    const service = workspace.catalogue.services.find((row) => row.key === addServiceKey);
    if (!service) return;
    setEditor({
      ...editor,
      lines: [
        ...editor.lines,
        {
          rowKey: rowKey(),
          kind: "service",
          key: service.key,
          label: service.name,
          description: "",
          service: service.key as AccountingServiceKey,
          amount: "0",
          cadence: "annual",
        },
      ],
    });
    setAddServiceKey("");
  };

  const addAddon = () => {
    if (!editor || !workspace || !addAddonKey) return;
    const addon: PricingAddon | undefined = workspace.catalogue.addons.find(
      (row) => row.key === addAddonKey,
    );
    if (!addon) return;
    setEditor({
      ...editor,
      lines: [
        ...editor.lines,
        {
          rowKey: rowKey(),
          kind: "addon",
          key: addon.key,
          label: addon.label,
          description: addon.description,
          service: null,
          amount: addon.amount !== null ? String(addon.amount) : "0",
          cadence: addon.cadence,
        },
      ],
    });
    setAddAddonKey("");
  };

  const addCustom = () => {
    if (!editor) return;
    setEditor({
      ...editor,
      lines: [
        ...editor.lines,
        {
          rowKey: rowKey(),
          kind: "custom",
          key: null,
          label: "",
          description: "",
          service: null,
          amount: "0",
          cadence: "annual",
        },
      ],
    });
  };

  const applyBenchmark = () => {
    if (!editor || !workspace) return;
    const benchmark = workspace.requests.find((row) => row.id === editor.enquiryId)?.estimate
      .indicative_annual_fee;
    if (!benchmark || editor.lines.length === 0) return;
    const perLine = Math.round((benchmark / editor.lines.length) * 100) / 100;
    setEditor({
      ...editor,
      lines: editor.lines.map((line, index) => ({
        ...line,
        amount: String(
          index === editor.lines.length - 1
            ? Math.round((benchmark - perLine * (editor.lines.length - 1)) * 100) / 100
            : perLine,
        ),
      })),
    });
    setNotice(
      `Benchmark of ${money(benchmark)} spread across ${editor.lines.length} line(s) as a starting point. Edit every amount before approval.`,
    );
  };

  const payloadLines = () =>
    (editor?.lines ?? []).map((line) => ({
      kind: line.kind,
      key: line.key,
      label: line.label.trim() || "Charge",
      description: line.description.trim() || null,
      service: line.service,
      amount: line.amount || "0",
      cadence: line.cadence,
    }));

  const payload = () => {
    if (!editor) return null;
    return {
      enquiry_id: editor.enquiryId,
      client_id: editor.clientId,
      annual_turnover: editor.annualTurnover || null,
      line_items: payloadLines(),
      discount_type: editor.discountType,
      discount_value: editor.discountValue || "0",
      discount_note: editor.discountNote.trim() || null,
      payment_frequency: editor.paymentFrequency,
      validity_days: editor.validityDays ? Number(editor.validityDays) : null,
      terms: editor.terms.trim() || null,
    };
  };

  const validate = (): string | null => {
    if (!editor) return "Open a quotation first.";
    if (!editor.lines.length) return "Add at least one service or charge.";
    if (editor.lines.some((line) => !line.label.trim())) return "Every line needs a label.";
    if (preview && preview.total <= 0) return "Set the amounts before saving or approving.";
    return null;
  };

  const createDraft = async (): Promise<AccountingQuotation | null> => {
    const body = payload();
    if (!body) return null;
    const created = await post<AccountingQuotation>("/accounting/senior/quotations", body);
    setEditor(editorFromQuotation(created));
    setNotice(`Draft ${created.number} created. It still needs senior approval before sending.`);
    await load();
    return created;
  };

  const saveDraft = async (): Promise<AccountingQuotation | null> => {
    if (!editor) return null;
    const validation = validate();
    if (validation) {
      setActionError(validation);
      return null;
    }
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!editor.id) return await createDraft();
      const updated = await patch<AccountingQuotation>(
        `/accounting/senior/quotations/${editor.id}`,
        payload(),
      );
      setEditor(editorFromQuotation(updated));
      setNotice(
        updated.status === "draft" && editor.status === "approved"
          ? "Changes saved. Approval was cleared, so the quotation is a draft again."
          : `Draft ${updated.number} saved.`,
      );
      await load();
      return updated;
    } catch (err) {
      setActionError(getErrorMessage(err));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    if (!editor) return;
    const validation = validate();
    if (validation) {
      setActionError(validation);
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      let targetId = editor.id;
      if (editor.status === "new" || (editor.id && editor.status === "approved")) {
        const saved = await saveDraft();
        if (!saved) return;
        targetId = saved.id;
      }
      if (!targetId) return;
      const approved = await post<AccountingQuotation>(
        `/accounting/senior/quotations/${targetId}/approve`,
      );
      setEditor(editorFromQuotation(approved));
      setNotice(`${approved.number} approved by a senior accountant. It can now be sent.`);
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    if (!editor?.id) return;
    setBusy(true);
    setActionError(null);
    try {
      const sent = await post<AccountingQuotation>(
        `/accounting/senior/quotations/${editor.id}/send`,
      );
      setEditor(editorFromQuotation(sent));
      setNotice(`${sent.number} sent to the customer portal.`);
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!editor?.id || rejectNote.trim().length < 3) return;
    setBusy(true);
    setActionError(null);
    try {
      const rejected = await post<AccountingQuotation>(
        `/accounting/senior/quotations/${editor.id}/reject`,
        { note: rejectNote.trim() },
      );
      setRejectOpen(false);
      setRejectNote("");
      setEditor(editorFromQuotation(rejected));
      setNotice(`${rejected.number} was rejected and cannot be sent.`);
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const recordDecision = async (decision: "accepted" | "declined") => {
    if (!editor?.id) return;
    setBusy(true);
    setActionError(null);
    try {
      const decided = await post<AccountingQuotation>(
        `/accounting/senior/quotations/${editor.id}/decision`,
        { decision, note: "Recorded by the practice after customer confirmation." },
      );
      setEditor(editorFromQuotation(decided));
      setNotice(`Customer ${decision} recorded. No payment has been charged.`);
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const downloadPdf = async () => {
    if (!editor?.id || !editor.number) return;
    try {
      await downloadFile(
        `/accounting/senior/quotations/${editor.id}/pdf`,
        `${editor.number}.pdf`,
      );
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  if (loading && !workspace) return <PageSkeleton cards={4} />;
  if (error && !workspace) {
    return <ErrorState message={error} onRetry={load} />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Senior accountant workspace"
        title="Quotation approvals"
        description="Review requests, price the scope, approve final fees, send quotations and track customer decisions. Junior accountants cannot approve or send quotations."
        actions={
          <Button variant="outline" icon={RefreshCw} onClick={() => void load()}>
            Refresh
          </Button>
        }
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}
      {notice && (
        <Callout tone="green" title="Updated">
          {notice}
        </Callout>
      )}

      {workspace && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="New requests"
            value={workspace.counts.new_requests}
            icon={Inbox}
            sub={`${workspace.counts.draft} draft · ${workspace.counts.approved} approved`}
            tone="blue"
          />
          <StatCard
            label="Pending value"
            value={money(workspace.pipeline.pending_value)}
            icon={FileText}
            sub="Draft, approved and sent quotations"
            tone="amber"
          />
          <StatCard
            label="Accepted value"
            value={money(workspace.pipeline.accepted_value)}
            icon={BadgeCheck}
            sub={`${workspace.counts.accepted} accepted`}
            tone="green"
          />
          <StatCard
            label="Awaiting customer"
            value={workspace.counts.sent}
            icon={Send}
            sub={`${workspace.counts.expired} expired · ${workspace.counts.rejected} rejected`}
            tone="violet"
          />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[390px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Quotation requests"
              description="New website and customer-portal requests start from the 2% benchmark."
              icon={Inbox}
            />
            <CardBody className="space-y-2 pt-3">
              {requestRows.length === 0 ? (
                <p className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-[11.5px] text-slate-500">
                  No open requests. New enquiries appear here.
                </p>
              ) : (
                requestRows.map((request) => (
                  <div key={request.id} className="rounded-xl border border-slate-200 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-[12.5px] font-semibold text-ink-900">
                          {request.business_name}
                        </p>
                        <p className="text-[10.5px] text-slate-500">
                          {request.reference} · {request.contact_name} · {labelize(request.status)}
                        </p>
                      </div>
                      <Badge tone={request.status === "new" ? "blue" : "amber"}>
                        {labelize(request.status)}
                      </Badge>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-1 text-[10.5px] text-slate-500">
                      <span>
                        Benchmark{" "}
                        <span className="font-semibold text-slate-700">
                          {money(request.estimate.indicative_annual_fee)}
                        </span>
                      </span>
                      <span className="text-right">
                        {request.bank_accounts ?? 0} bank a/c ·{" "}
                        {request.payroll_required ? "payroll" : "no payroll"}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <p className="text-[10px] text-slate-400">
                        {request.monthly_transactions ?? "—"} txns/month · FY{" "}
                        {request.financial_year ?? "—"}
                      </p>
                      <Button
                        size="sm"
                        icon={Calculator}
                        onClick={() =>
                          setEditor(
                            editorFromRequest(
                              request,
                              workspace?.catalogue.services ?? [],
                              workspace?.settings.quote_validity_days ?? 15,
                            ),
                          )
                        }
                      >
                        Draft quotation
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Quotations"
              description="Filter the pipeline and open a quotation to edit or approve it."
              icon={FileText}
            />
            <CardBody className="space-y-3 pt-3">
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                  <Input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Number or business"
                    className="pl-8 text-xs"
                    aria-label="Search quotations"
                  />
                </div>
                <Select
                  value={status}
                  onChange={(event) => setStatus(event.target.value as QuotationStatus | "")}
                  aria-label="Filter by status"
                  className="text-xs"
                >
                  {STATUS_FILTERS.map((value) => (
                    <option key={value || "all"} value={value}>
                      {value ? labelize(value) : "All statuses"}
                    </option>
                  ))}
                </Select>
              </div>
              {(!workspace || workspace.quotations.length === 0) && (
                <EmptyState
                  title="No quotations"
                  description="Create a draft from an open request to start the approval workflow."
                  icon={FileText}
                />
              )}
              <div className="max-h-[520px] space-y-2 overflow-y-auto pr-0.5">
                {workspace?.quotations.map((quotation) => (
                  <button
                    key={quotation.id}
                    type="button"
                    onClick={() => {
                      setActionError(null);
                      setNotice(null);
                      setEditor(editorFromQuotation(quotation));
                    }}
                    className={`w-full rounded-xl border p-3 text-left transition ${
                      editor?.id === quotation.id
                        ? "border-brand-300 bg-brand-50/60"
                        : "border-slate-200 hover:border-brand-200 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-[12px] font-semibold text-ink-900">
                          {quotation.number}
                        </p>
                        <p className="truncate text-[10.5px] text-slate-500">
                          {quotation.enquiry?.business_name || quotation.client_name || "Client"}
                        </p>
                      </div>
                      <StatusBadge status={quotation.status} />
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-1 text-[10.5px] text-slate-500">
                      <span>
                        {money(quotation.total_annual)} annual ·{" "}
                        {money(quotation.monthly_equivalent)}/mo
                      </span>
                      <span>Valid to {formatDate(quotation.valid_until)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </CardBody>
          </Card>
        </div>

        {!editor || !workspace ? (
          <Card>
            <CardBody>
              <EmptyState
                title="Select a quotation or request"
                description="Drafting, editing, approving, rejecting and sending all happen here. Every final price requires a senior accountant's approval."
                icon={Calculator}
              />
            </CardBody>
          </Card>
        ) : (
          <Card>
            <CardHeader
              icon={Calculator}
              title={
                <span className="flex flex-wrap items-center gap-2">
                  {editor.number ?? "New draft quotation"}
                  <StatusBadge status={editor.status === "new" ? "draft" : editor.status} />
                </span>
              }
              description={
                editor.status === "new"
                  ? "Unsaved draft. The benchmark is a starting point, not a final fee."
                  : `${editor.businessName} · ${editor.email}`
              }
              actions={
                <>
                  {editor.id && (
                    <Button size="sm" variant="outline" icon={Download} onClick={() => void downloadPdf()}>
                      PDF
                    </Button>
                  )}
                  {editor.status === "draft" && editor.id && (
                    <Button
                      size="sm"
                      variant="danger"
                      icon={XCircle}
                      onClick={() => setRejectOpen(true)}
                    >
                      Reject
                    </Button>
                  )}
                </>
              }
            />
            <CardBody className="space-y-4 pt-3">
              <div className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 sm:grid-cols-3">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Business</p>
                  <p className="text-[11.5px] font-semibold text-ink-900">{editor.businessName}</p>
                  <p className="text-[10.5px] text-slate-500">{editor.contactName}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Annual turnover</p>
                  <p className="text-[11.5px] font-semibold text-ink-900">
                    {editor.annualTurnover ? money(editor.annualTurnover) : "—"}
                  </p>
                  <p className="text-[10.5px] text-slate-500">
                    Benchmark{" "}
                    {money(
                      workspace.requests.find((row) => row.id === editor.enquiryId)?.estimate
                        .indicative_annual_fee,
                    )}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Approval</p>
                  <p className="text-[11.5px] font-semibold text-ink-900">
                    {editor.approvedByName ?? "Not approved"}
                  </p>
                  <p className="text-[10.5px] text-slate-500">
                    {editor.sentAt
                      ? `Sent ${formatDate(editor.sentAt)}`
                      : editor.approvedByName
                        ? "Approved — ready to send"
                        : "Sending requires approval"}
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Annual turnover (INR)" htmlFor="editor-turnover">
                  <Input
                    id="editor-turnover"
                    value={editor.annualTurnover}
                    disabled={readOnly}
                    onChange={(event) =>
                      setEditor({ ...editor, annualTurnover: event.target.value.replace(/[^\d.]/g, "") })
                    }
                  />
                </Field>
                <Field label="Payment frequency" htmlFor="editor-frequency">
                  <Select
                    id="editor-frequency"
                    value={editor.paymentFrequency}
                    disabled={readOnly}
                    onChange={(event) =>
                      setEditor({
                        ...editor,
                        paymentFrequency: event.target.value as PaymentFrequency,
                      })
                    }
                  >
                    <option value="monthly">Monthly</option>
                    <option value="quarterly">Quarterly</option>
                    <option value="annual">Annual</option>
                    <option value="one_time">One time</option>
                  </Select>
                </Field>
                <Field label="Validity (days)" htmlFor="editor-validity">
                  <Input
                    id="editor-validity"
                    inputMode="numeric"
                    value={editor.validityDays}
                    disabled={readOnly}
                    placeholder={String(workspace.settings.quote_validity_days)}
                    onChange={(event) =>
                      setEditor({ ...editor, validityDays: event.target.value.replace(/[^\d]/g, "") })
                    }
                  />
                </Field>
              </div>

              <div>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                    Scope and charges
                  </p>
                  {!readOnly && (
                    <div className="flex flex-wrap gap-1.5">
                      <Button size="sm" variant="ghost" icon={Calculator} onClick={applyBenchmark}>
                        Apply benchmark
                      </Button>
                      <Button size="sm" variant="ghost" icon={Plus} onClick={addCustom}>
                        Custom charge
                      </Button>
                    </div>
                  )}
                </div>
                <div className="overflow-x-auto rounded-xl border border-slate-200">
                  <table className="w-full min-w-[600px] text-left text-[11.5px]">
                    <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="px-3 py-2">Description</th>
                        <th className="px-3 py-2">Type</th>
                        <th className="px-3 py-2 text-right">Annual amount</th>
                        <th className="px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {editor.lines.map((line) => (
                        <tr key={line.rowKey} className="border-t border-slate-100">
                          <td className="px-3 py-2">
                            <Input
                              value={line.label}
                              disabled={readOnly}
                              onChange={(event) => setLine(line.rowKey, { label: event.target.value })}
                              placeholder="Service or charge"
                              className="text-xs"
                              aria-label="Line label"
                            />
                            <Input
                              value={line.description}
                              disabled={readOnly}
                              onChange={(event) =>
                                setLine(line.rowKey, { description: event.target.value })
                              }
                              placeholder="What is included (optional)"
                              className="mt-1 text-[11px]"
                              aria-label="Line description"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <Badge tone={line.kind === "service" ? "blue" : line.kind === "addon" ? "violet" : "slate"}>
                              {labelize(line.kind)}
                            </Badge>
                            <p className="mt-1 text-[10px] text-slate-400">
                              {line.cadence === "one_time" ? "One time" : "Annual"}
                            </p>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <Input
                              value={line.amount}
                              disabled={readOnly}
                              inputMode="decimal"
                              onChange={(event) =>
                                setLine(line.rowKey, {
                                  amount: event.target.value.replace(/[^\d.]/g, ""),
                                })
                              }
                              className="text-right text-xs"
                              aria-label="Annual amount"
                            />
                          </td>
                          <td className="px-3 py-2 text-right">
                            {!readOnly && (
                              <button
                                type="button"
                                onClick={() =>
                                  setEditor({
                                    ...editor,
                                    lines: editor.lines.filter((row) => row.rowKey !== line.rowKey),
                                  })
                                }
                                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                                aria-label={`Remove ${line.label || "line"}`}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!readOnly && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Select
                      value={addServiceKey}
                      onChange={(event) => setAddServiceKey(event.target.value)}
                      className="w-auto min-w-[190px] text-xs"
                      aria-label="Service to add"
                    >
                      <option value="">Add a service…</option>
                      {workspace.catalogue.services.map((service) => (
                        <option key={service.key} value={service.key}>
                          {service.name}
                        </option>
                      ))}
                    </Select>
                    <Button size="sm" variant="outline" icon={Plus} onClick={addService} disabled={!addServiceKey}>
                      Add service
                    </Button>
                    <Select
                      value={addAddonKey}
                      onChange={(event) => setAddAddonKey(event.target.value)}
                      className="w-auto min-w-[190px] text-xs"
                      aria-label="Add-on to add"
                    >
                      <option value="">Add an additional charge…</option>
                      {workspace.catalogue.addons.map((addon) => (
                        <option key={addon.key} value={addon.key}>
                          {addon.label}
                        </option>
                      ))}
                    </Select>
                    <Button size="sm" variant="outline" icon={Plus} onClick={addAddon} disabled={!addAddonKey}>
                      Add charge
                    </Button>
                  </div>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Discount type" htmlFor="editor-discount-type">
                  <Select
                    id="editor-discount-type"
                    value={editor.discountType}
                    disabled={readOnly}
                    onChange={(event) =>
                      setEditor({
                        ...editor,
                        discountType: event.target.value as EditorState["discountType"],
                      })
                    }
                  >
                    <option value="none">No discount</option>
                    <option value="percent">Approved percentage</option>
                    <option value="amount">Approved amount</option>
                  </Select>
                </Field>
                <Field
                  label={editor.discountType === "percent" ? "Discount %" : "Discount amount (INR)"}
                  htmlFor="editor-discount-value"
                  hint="Only an approved discount. Nothing is applied automatically."
                >
                  <Input
                    id="editor-discount-value"
                    inputMode="decimal"
                    value={editor.discountValue}
                    disabled={readOnly || editor.discountType === "none"}
                    onChange={(event) =>
                      setEditor({ ...editor, discountValue: event.target.value.replace(/[^\d.]/g, "") })
                    }
                  />
                </Field>
                <Field label="Payment schedule" htmlFor="editor-preview">
                  <div
                    id="editor-preview"
                    className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11.5px] text-slate-600"
                  >
                    {money(preview?.perPeriod)} per{" "}
                    {editor.paymentFrequency === "one_time" ? "invoice" : editor.paymentFrequency.replace("ly", "")}
                  </div>
                </Field>
              </div>

              <Field label="Discount / pricing note" htmlFor="editor-discount-note">
                <Input
                  id="editor-discount-note"
                  value={editor.discountNote}
                  disabled={readOnly}
                  onChange={(event) => setEditor({ ...editor, discountNote: event.target.value })}
                  placeholder="Why this discount is approved (optional)"
                />
              </Field>

              <Field label="Terms and conditions" htmlFor="editor-terms">
                <Textarea
                  id="editor-terms"
                  value={editor.terms}
                  disabled={readOnly}
                  onChange={(event) => setEditor({ ...editor, terms: event.target.value })}
                  placeholder={workspace.settings.terms}
                  className="min-h-[90px] text-xs"
                />
              </Field>

              <div className="grid gap-2 rounded-xl border border-brand-100 bg-brand-50/60 p-3 sm:grid-cols-4">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Subtotal</p>
                  <p className="text-[13px] font-semibold text-ink-900">{money(preview?.subtotal)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Discount</p>
                  <p className="text-[13px] font-semibold text-ink-900">{money(preview?.discount)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Final annual</p>
                  <p className="text-[13px] font-semibold text-brand-700">{money(preview?.total)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Monthly equivalent</p>
                  <p className="text-[13px] font-semibold text-ink-900">{money(preview?.monthly)}</p>
                </div>
              </div>
              <p className="text-[10.5px] leading-relaxed text-slate-500">
                Totals are recalculated on the server. {number(workspace.settings.tax_rate_percent, 1)}% GST is
                disclosed separately; this quotation is not a tax invoice. Accepting does not charge any amount.
              </p>

              <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
                {!readOnly && (
                  <>
                    <Button variant="outline" icon={FileText} loading={busy} onClick={() => void saveDraft()}>
                      {editor.id ? "Save changes" : "Save draft"}
                    </Button>
                    {editor.status !== "approved" && (
                      <Button icon={BadgeCheck} loading={busy} onClick={() => void approve()}>
                        Approve quotation
                      </Button>
                    )}
                    {editor.status === "approved" && (
                      <Button icon={Send} loading={busy} onClick={() => void send()}>
                        Send to customer
                      </Button>
                    )}
                  </>
                )}
                {editor.status === "sent" && (
                  <>
                    <Button
                      variant="success"
                      icon={CheckCircle2}
                      loading={busy}
                      onClick={() => void recordDecision("accepted")}
                    >
                      Record acceptance
                    </Button>
                    <Button
                      variant="outline"
                      icon={XCircle}
                      loading={busy}
                      onClick={() => void recordDecision("declined")}
                    >
                      Record decline
                    </Button>
                  </>
                )}
                {editor.status === "approved" && (
                  <Button size="sm" variant="danger" icon={XCircle} onClick={() => setRejectOpen(true)}>
                    Reject
                  </Button>
                )}
                <Link
                  to="/accountant/enquiries"
                  className="ml-auto self-center text-[11px] font-semibold text-brand-600 hover:underline"
                >
                  Open enquiry pipeline
                </Link>
              </div>
            </CardBody>
          </Card>
        )}
      </div>

      <Modal
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        title="Reject this quotation"
        description="A rejected quotation cannot be sent or edited. A note is required and recorded in the audit trail."
        footer={
          <>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              icon={XCircle}
              loading={busy}
              onClick={() => void reject()}
              disabled={rejectNote.trim().length < 3}
            >
              Reject quotation
            </Button>
          </>
        }
      >
        <Field label="Reason" htmlFor="reject-note" required>
          <Textarea
            id="reject-note"
            value={rejectNote}
            onChange={(event) => setRejectNote(event.target.value)}
            placeholder="e.g. Turnover evidence not provided; scope to be re-quoted."
          />
        </Field>
      </Modal>
    </div>
  );
}
