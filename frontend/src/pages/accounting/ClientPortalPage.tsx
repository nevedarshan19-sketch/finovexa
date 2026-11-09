import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Bell,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Files,
  IndianRupee,
  MessageSquare,
  Plus,
  Send,
  Upload,
} from "lucide-react";
import { downloadFile, get, getErrorMessage, post } from "../../lib/api";
import type {
  AccountingCatalogue,
  AccountingDocument,
  AccountingMessage,
  AccountingNotification,
  AccountingQuotation,
  AccountingReport,
  AccountingServiceKey,
  CustomerOverview,
  CustomerQuotationRequest,
} from "../../lib/accountingTypes";
import { DOCUMENT_CATEGORIES, fileToDataUrl, formatBytes, labelize, serviceLabel } from "../../lib/accounting";
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
  Modal,
  PageHeader,
  PageSkeleton,
  ProgressBar,
  Select,
  StatCard,
  Tabs,
  Textarea,
} from "../../components/ui";
import { PriorityBadge, StatusBadge } from "../../components/accounting/AccountingUI";

type TabKey = "overview" | "documents" | "reports" | "invoices" | "quotations" | "messages";

interface RequestForm {
  business_name: string;
  contact_name: string;
  email: string;
  phone: string;
  business_type: string;
  turnover_range: string;
  gst_status: string;
  services: AccountingServiceKey[];
  monthly_transactions: string;
  annual_turnover: string;
  bank_accounts: string;
  payroll_required: boolean;
  inventory_required: boolean;
  financial_year: string;
  requirements: string;
  consent: boolean;
}

const EMPTY_REQUEST: RequestForm = {
  business_name: "",
  contact_name: "",
  email: "",
  phone: "",
  business_type: "",
  turnover_range: "",
  gst_status: "",
  services: [],
  monthly_transactions: "",
  annual_turnover: "",
  bank_accounts: "",
  payroll_required: false,
  inventory_required: false,
  financial_year: "",
  requirements: "",
  consent: false,
};

function currentFinancialYear(): string {
  const today = new Date();
  const start = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

export function ClientPortalPage() {
  const [overview, setOverview] = useState<CustomerOverview | null>(null);
  const [quotations, setQuotations] = useState<AccountingQuotation[]>([]);
  const [quotationRequests, setQuotationRequests] = useState<CustomerQuotationRequest[]>([]);
  const [catalogue, setCatalogue] = useState<AccountingCatalogue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");
  const [busy, setBusy] = useState(false);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadRequestId, setUploadRequestId] = useState<number | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadForm, setUploadForm] = useState({ title: "", category: "purchase_bill" });

  const [messageBody, setMessageBody] = useState("");

  const [quotationFor, setQuotationFor] = useState<AccountingQuotation | null>(null);
  const [quotationDecision, setQuotationDecision] = useState<"accepted" | "declined">("accepted");
  const [quotationNote, setQuotationNote] = useState("");

  const [requestOpen, setRequestOpen] = useState(false);
  const [requestForm, setRequestForm] = useState<RequestForm>(EMPTY_REQUEST);
  const [requestFieldErrors, setRequestFieldErrors] = useState<Record<string, string>>({});
  const [requestResult, setRequestResult] = useState<{ reference: string; message: string } | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [overviewData, quotationData, requestData, catalogueData] = await Promise.all([
        get<CustomerOverview>("/accounting/customer/overview"),
        get<{ items: AccountingQuotation[] }>("/accounting/customer/quotations").catch(() => ({ items: [] })),
        get<{ items: CustomerQuotationRequest[] }>("/accounting/customer/quotation-requests").catch(() => ({
          items: [],
        })),
        get<AccountingCatalogue>("/accounting/public/services").catch(() => null),
      ]);
      setOverview(overviewData);
      setQuotations(quotationData.items);
      setQuotationRequests(requestData.items);
      setCatalogue(catalogueData);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const markRead = async (notification: AccountingNotification) => {
    try {
      await post(`/accounting/notifications/${notification.id}/read`);
      setOverview((current) =>
        current?.notifications
          ? {
              ...current,
              notifications: {
                ...current.notifications,
                items: current.notifications.items.map((item) =>
                  item.id === notification.id ? { ...item, read: true } : item,
                ),
                unread_count: Math.max(0, current.notifications.unread_count - 1),
              },
            }
          : current,
      );
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const markAllRead = async () => {
    try {
      await post("/accounting/notifications/read-all");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const upload = async () => {
    if (!uploadFile || !overview?.client) return;
    setBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(uploadFile);
      await post("/accounting/customer/documents", {
        client_id: overview.client.id,
        filename: uploadFile.name,
        data_url: dataUrl,
        title: uploadForm.title || uploadFile.name,
        category: uploadForm.category,
        request_id: uploadRequestId,
      });
      setUploadOpen(false);
      setUploadFile(null);
      setUploadRequestId(null);
      setUploadForm({ title: "", category: "purchase_bill" });
      await load();
      setTab("documents");
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const sendMessage = async () => {
    if (!messageBody.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      await post<AccountingMessage>("/accounting/customer/messages", { body: messageBody.trim() });
      setMessageBody("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const decideQuotation = async () => {
    if (!quotationFor) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/customer/quotations/${quotationFor.id}/decision`, {
        decision: quotationDecision,
        note: quotationNote || null,
      });
      setQuotationFor(null);
      setQuotationNote("");
      await load();
      setTab("quotations");
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const download = async (document: AccountingDocument) => {
    try {
      await downloadFile(`/accounting/documents/${document.id}/file`, document.original_filename);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const downloadQuotation = async (quotation: AccountingQuotation) => {
    try {
      await downloadFile(
        `/accounting/customer/quotations/${quotation.id}/pdf`,
        `${quotation.number}.pdf`,
      );
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const openRequest = () => {
    const client = overview?.client;
    setRequestForm({
      ...EMPTY_REQUEST,
      business_name: client?.business_name || "",
      contact_name: client?.contact_name || "",
      financial_year: currentFinancialYear(),
      business_type: catalogue?.business_types[0] || "",
      turnover_range: catalogue?.turnover_ranges[0] || "",
      gst_status: catalogue?.gst_statuses[0] || "",
    });
    setRequestFieldErrors({});
    setRequestResult(null);
    setActionError(null);
    setRequestOpen(true);
  };

  const submitRequest = async (event: FormEvent) => {
    event.preventDefault();
    const errors: Record<string, string> = {};
    if (requestForm.business_name.trim().length < 2) errors.business_name = "Enter the business name.";
    if (requestForm.contact_name.trim().length < 2) errors.contact_name = "Enter a contact name.";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(requestForm.email.trim()))
      errors.email = "Enter a valid email address.";
    if (!requestForm.business_type) errors.business_type = "Select a business type.";
    if (!requestForm.turnover_range) errors.turnover_range = "Select a turnover range.";
    if (!requestForm.gst_status) errors.gst_status = "Select the GST status.";
    if (requestForm.services.length === 0) errors.services = "Select at least one service.";
    if (!requestForm.consent) errors.consent = "Please confirm we may contact you about this request.";
    setRequestFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setBusy(true);
    setActionError(null);
    try {
      const result = await post<{ reference: string; message: string }>(
        "/accounting/customer/quotation-requests",
        {
          business_name: requestForm.business_name.trim(),
          contact_name: requestForm.contact_name.trim(),
          email: requestForm.email.trim(),
          phone: requestForm.phone.trim() || null,
          business_type: requestForm.business_type,
          turnover_range: requestForm.turnover_range,
          gst_status: requestForm.gst_status,
          services: requestForm.services,
          monthly_transactions: requestForm.monthly_transactions
            ? Number(requestForm.monthly_transactions)
            : null,
          annual_turnover: requestForm.annual_turnover || null,
          bank_accounts: requestForm.bank_accounts ? Number(requestForm.bank_accounts) : null,
          payroll_required: requestForm.payroll_required,
          inventory_required: requestForm.inventory_required,
          financial_year: requestForm.financial_year || null,
          requirements: requestForm.requirements.trim() || null,
          consent: true,
          website: null,
        },
      );
      setRequestResult(result);
      setRequestOpen(false);
      setTab("quotations");
      await load(true);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <PageSkeleton cards={4} />;
  if (error) {
    return (
      <Card>
        <CardBody>
          <ErrorState message={error} onRetry={load} />
        </CardBody>
      </Card>
    );
  }
  if (!overview || !overview.linked || !overview.client) {
    return (
      <Card>
        <CardBody>
          <EmptyState
            title="No engagement linked yet"
            description={overview?.message || "No accounting engagement is linked to this account."}
            icon={FileText}
            action={
              <Button onClick={() => (window.location.href = "/accounting")}>Explore accounting services</Button>
            }
          />
        </CardBody>
      </Card>
    );
  }

  const client = overview.client;
  const tasks = overview.tasks || [];
  const counts = overview.counts;
  const documents = overview.documents || [];
  const requests = overview.document_requests || [];
  const reports = overview.reports || [];
  const invoices = overview.invoices || [];
  const messages = overview.messages || [];
  const notifications = overview.notifications;
  const unread = notifications?.unread_count || 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={`${client.code} · ${labelize(client.status)}`}
        title={client.business_name}
        description={`${client.service_package} engagement · FY ${client.financial_year}${
          client.gstin ? ` · GSTIN ${client.gstin}` : ""
        }. You can only see your own engagement.`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" icon={Plus} onClick={openRequest}>
              Request a quotation
            </Button>
            <Button icon={Upload} onClick={() => setUploadOpen(true)}>
              Upload document
            </Button>
          </div>
        }
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      {requestResult && (
        <Callout
          tone="green"
          title={`Quotation request received — ${requestResult.reference}`}
        >
          {requestResult.message}
        </Callout>
      )}

      {requests.length > 0 && (
        <Callout tone="amber" icon={Clock} title={`${requests.length} document request(s) pending`}>
          Your accountant has asked for more information. Upload the documents from the list below so work
          can continue.
        </Callout>
      )}

      {counts && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <StatCard label="Active tasks" value={counts.active_tasks} icon={Clock} tone="blue" />
          <StatCard label="Awaiting your documents" value={counts.awaiting_documents} icon={Upload} tone="amber" />
          <StatCard label="Approved reports" value={counts.approved_reports} icon={CheckCircle2} tone="green" />
          <StatCard label="Outstanding invoices" value={counts.outstanding_invoices} icon={IndianRupee} tone="red" />
          <StatCard label="Overdue tasks" value={counts.overdue_tasks} icon={Bell} tone="violet" />
        </div>
      )}

      <Tabs<TabKey>
        value={tab}
        onChange={setTab}
        items={[
          { key: "overview", label: "Overview" },
          { key: "documents", label: "Documents", count: documents.length },
          { key: "reports", label: "Reports", count: reports.length },
          { key: "invoices", label: "Invoices", count: invoices.length },
          { key: "quotations", label: "Quotations", count: quotations.length },
          { key: "messages", label: "Messages", count: messages.length },
        ]}
      />

      {tab === "overview" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <Card>
              <CardHeader
                title="Engagement status"
                description={`Prepared with ${client.contact_name}; reviewed by ${client.senior_name || "the senior accountant"}.`}
                icon={FileText}
              />
              <CardBody className="space-y-3 pt-0">
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Senior accountant</p>
                    <p className="mt-1 text-[12px] font-medium text-ink-900">{client.senior_name || "Being assigned"}</p>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Preparing accountant</p>
                    <p className="mt-1 text-[12px] font-medium text-ink-900">{client.junior_name || "Being assigned"}</p>
                  </div>
                </div>
                {tasks.length === 0 ? (
                  <EmptyState title="No tasks yet" description="Work items appear here once your engagement starts." icon={Clock} />
                ) : (
                  <div className="space-y-2">
                    {tasks.map((task) => (
                      <div key={task.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-[12px] font-semibold text-ink-900">{task.title}</p>
                            <p className="text-[10px] text-slate-500">
                              {serviceLabel(task.service_type)} · due {formatDate(task.due_date)}
                              {!["approved", "delivered", "cancelled"].includes(task.status) &&
                              task.days_remaining !== null
                                ? task.days_remaining < 0
                                  ? ` · ${Math.abs(task.days_remaining)} day(s) overdue`
                                  : ` · ${task.days_remaining} day(s) left`
                                : ""}
                            </p>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <PriorityBadge priority={task.priority} />
                            <StatusBadge status={task.status} />
                          </div>
                        </div>
                        <div className="mt-2">
                          <ProgressBar value={task.progress} tone={task.progress >= 100 ? "green" : "blue"} label={`${task.title} progress`} />
                        </div>
                        {task.update_note && (
                          <p className="mt-1.5 text-[10px] text-amber-700">Review note: {task.update_note}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>

            {requests.length > 0 && (
              <Card>
                <CardHeader title="Documents requested" description="Upload these to keep your work on schedule." icon={Upload} />
                <CardBody className="space-y-2 pt-0">
                  {requests.map((request) => (
                    <div key={request.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2">
                      <div className="min-w-0">
                        <p className="text-[12px] font-semibold text-amber-900">{request.title}</p>
                        <p className="text-[10px] text-amber-700">
                          {request.description || "Requested by your accountant"} · due {formatDate(request.due_date)}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        icon={Upload}
                        onClick={() => {
                          setUploadRequestId(request.id);
                          setUploadForm({ title: request.title, category: "other" });
                          setUploadOpen(true);
                        }}
                      >
                        Upload
                      </Button>
                    </div>
                  ))}
                </CardBody>
              </Card>
            )}
          </div>

          <Card>
            <CardHeader
              title="Notifications"
              description={unread ? `${unread} unread` : "All caught up"}
              icon={Bell}
              actions={
                unread > 0 ? (
                  <Button size="sm" variant="ghost" onClick={() => void markAllRead()}>
                    Mark all read
                  </Button>
                ) : undefined
              }
            />
            <CardBody className="pt-0">
              {!notifications || notifications.items.length === 0 ? (
                <EmptyState title="No notifications" description="Updates about documents, approvals and deadlines appear here." icon={Bell} />
              ) : (
                <div className="space-y-2">
                  {notifications.items.slice(0, 12).map((notification) => (
                    <button
                      key={notification.id}
                      type="button"
                      onClick={() => !notification.read && void markRead(notification)}
                      className={`block w-full rounded-lg border px-3 py-2 text-left transition ${
                        notification.read
                          ? "border-slate-200 bg-white"
                          : "border-brand-200 bg-brand-50/60 hover:bg-brand-50"
                      }`}
                    >
                      <p className="text-[11px] font-semibold text-ink-900">{notification.title}</p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-slate-600">{notification.body}</p>
                      <p className="mt-1 text-[10px] text-slate-400">{formatDateTime(notification.created_at)}</p>
                    </button>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {tab === "documents" && (
        <Card>
          <CardHeader
            title="Your documents"
            description="Shared files and the documents you uploaded. Internal working files stay with the practice."
            icon={Files}
            actions={
              <Button size="sm" icon={Upload} onClick={() => setUploadOpen(true)}>
                Upload
              </Button>
            }
          />
          <CardBody className="pt-0">
            {documents.length === 0 ? (
              <EmptyState title="No documents" description="Upload bills, bank statements or GST documents here." icon={Files} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head">Document</th>
                      <th className="table-head">Category</th>
                      <th className="table-head">Status</th>
                      <th className="table-head">Size</th>
                      <th className="table-head">Uploaded</th>
                      <th className="table-head"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {documents.map((document) => (
                      <tr key={document.id} className="row-hover">
                        <td className="table-cell">
                          <p className="text-[12px] font-semibold text-ink-900">{document.title}</p>
                          <p className="text-[10px] text-slate-500">{document.original_filename}</p>
                        </td>
                        <td className="table-cell text-[11px] text-slate-500">{labelize(document.category)}</td>
                        <td className="table-cell">
                          <StatusBadge status={document.status} />
                        </td>
                        <td className="table-cell text-[11px] text-slate-500">{formatBytes(document.size_bytes)}</td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">{formatDate(document.created_at)}</td>
                        <td className="table-cell">
                          <Button size="sm" variant="ghost" icon={Download} onClick={() => void download(document)}>
                            Download
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

      {tab === "reports" && (
        <div className="space-y-3">
          <Callout tone="blue" icon={FileText} title="Approved and delivered reports">
            Only reports approved by the senior accountant appear here. GST workings are internal documents
            unless your engagement includes a filing service.
          </Callout>
          {reports.length === 0 ? (
            <Card>
              <CardBody>
                <EmptyState title="No approved reports" description="Reports appear once your accountant approves and delivers them." icon={FileText} />
              </CardBody>
            </Card>
          ) : (
            reports.map((report) => <ReportCard key={report.id} report={report} />)
          )}
        </div>
      )}

      {tab === "invoices" && (
        <Card>
          <CardHeader
            title="Invoices and payments"
            description="Fees billed for your accounting engagement. Payments are recorded by the practice."
            icon={IndianRupee}
          />
          <CardBody className="pt-0">
            {invoices.length === 0 ? (
              <EmptyState title="No invoices" description="Fee invoices for your engagement will appear here." icon={IndianRupee} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head">Invoice</th>
                      <th className="table-head">Issued</th>
                      <th className="table-head">Due</th>
                      <th className="table-head">Total</th>
                      <th className="table-head">Paid</th>
                      <th className="table-head">Outstanding</th>
                      <th className="table-head">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {invoices.map((invoice) => (
                      <tr key={invoice.id} className="row-hover">
                        <td className="table-cell">
                          <p className="text-[12px] font-semibold text-ink-900">{invoice.number}</p>
                          <p className="text-[10px] text-slate-500">{invoice.period_label || "—"}</p>
                        </td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">{formatDate(invoice.issue_date)}</td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">{formatDate(invoice.due_date)}</td>
                        <td className="table-cell tabular text-[11px]">{money(invoice.total_amount)}</td>
                        <td className="table-cell tabular text-[11px]">{money(invoice.paid_amount)}</td>
                        <td className="table-cell tabular text-[11px] font-semibold">{money(invoice.outstanding_amount)}</td>
                        <td className="table-cell">
                          <StatusBadge status={invoice.is_overdue ? "overdue" : invoice.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-3 text-[10px] text-slate-400">
              Online payment is not enabled on this portal. Settle fees through the agreed practice channel;
              your accountant records the receipt.
            </p>
          </CardBody>
        </Card>
      )}

      {tab === "quotations" && (
        <div className="space-y-4">
          <Callout tone="blue" icon={FileText} title="Approved quotations only">
            A quotation appears here only after a senior accountant approves it and the practice sends it.
            Accounting fees are quoted separately from the software subscription, and ITR filing is a
            separate paid service.
          </Callout>

          <Card>
            <CardHeader
              title="Your quotations"
              description="Review the scope, download the PDF and record your decision."
              icon={FileText}
              actions={
                <Button size="sm" variant="outline" icon={Plus} onClick={openRequest}>
                  Request a quotation
                </Button>
              }
            />
            <CardBody className="space-y-3 pt-0">
              {quotations.length === 0 ? (
                <EmptyState
                  title="No quotations yet"
                  description="Request a quotation and your senior accountant will prepare it after reviewing the scope."
                  icon={FileText}
                  action={
                    <Button size="sm" icon={Plus} onClick={openRequest}>
                      Request a quotation
                    </Button>
                  }
                />
              ) : (
                quotations.map((quotation) => (
                  <div key={quotation.id} className="rounded-xl border border-slate-200 p-3.5">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="text-[12px] font-semibold text-ink-900">{quotation.number}</p>
                        <p className="text-[11px] text-slate-500">
                          Valid until {formatDate(quotation.valid_until)}
                          {quotation.approved_by_name ? ` · approved by ${quotation.approved_by_name}` : ""}
                        </p>
                      </div>
                      <StatusBadge status={quotation.status} />
                    </div>

                    {quotation.line_items.length > 0 ? (
                      <ul className="mt-2 space-y-1">
                        {quotation.line_items.map((line, index) => (
                          <li
                            key={`${quotation.id}-${line.key ?? "custom"}-${index}`}
                            className="flex flex-wrap items-baseline justify-between gap-1 text-[11px] text-slate-600"
                          >
                            <span>
                              <span className="font-medium text-ink-900">{line.label}</span>
                              {line.description ? ` — ${line.description}` : ""}
                            </span>
                            <span className="tabular font-medium text-slate-700">
                              {money(line.amount)}
                              {line.cadence === "one_time" ? " one time" : " / year"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      quotation.scope.length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {quotation.scope.map((line) => (
                            <li key={`${quotation.id}-${line.service}`} className="text-[11px] text-slate-600">
                              <span className="font-medium text-ink-900">{serviceLabel(line.service)}</span> —{" "}
                              {line.description}
                            </li>
                          ))}
                        </ul>
                      )
                    )}

                    <div className="mt-2 grid gap-2 rounded-lg bg-slate-50 px-2.5 py-2 text-[11px] sm:grid-cols-3">
                      <div>
                        <p className="text-[10px] uppercase tracking-wide text-slate-400">Annual total</p>
                        <p className="font-semibold text-ink-900">{money(quotation.total_annual)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase tracking-wide text-slate-400">Monthly equivalent</p>
                        <p className="font-semibold text-ink-900">{money(quotation.monthly_equivalent)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase tracking-wide text-slate-400">Payment frequency</p>
                        <p className="font-semibold text-ink-900">
                          {labelize(quotation.payment_frequency || quotation.billing_cadence)}
                        </p>
                      </div>
                    </div>
                    {Number(quotation.discount_amount) > 0 && (
                      <p className="mt-1 text-[10px] text-emerald-700">
                        An approved discount of {money(quotation.discount_amount)} is included
                        {quotation.discount_note ? ` — ${quotation.discount_note}` : ""}.
                      </p>
                    )}
                    {quotation.terms && <p className="mt-2 text-[10px] text-slate-500">{quotation.terms}</p>}
                    {quotation.response_note && (
                      <p className="mt-2 text-[10px] text-slate-500">Your note: {quotation.response_note}</p>
                    )}

                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        icon={Download}
                        onClick={() => void downloadQuotation(quotation)}
                      >
                        Download PDF
                      </Button>
                      {quotation.status === "sent" && (
                        <>
                          <Button
                            size="sm"
                            icon={CheckCircle2}
                            onClick={() => {
                              setQuotationFor(quotation);
                              setQuotationDecision("accepted");
                              setQuotationNote("");
                            }}
                          >
                            Accept quotation
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setQuotationFor(quotation);
                              setQuotationDecision("declined");
                              setQuotationNote("");
                            }}
                          >
                            Decline
                          </Button>
                        </>
                      )}
                      {quotation.status === "expired" && (
                        <span className="self-center text-[10.5px] text-amber-700">
                          This quotation has expired. Request a fresh quotation to continue.
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
              <p className="text-[10px] leading-relaxed text-slate-400">
                Accepting a quotation records your decision only. No payment is collected here — a separate
                secure payment process is arranged with your accountant. Nothing is filed automatically.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Your quotation requests"
              description="Requests stay open until the practice sends an approved quotation."
              icon={Clock}
            />
            <CardBody className="space-y-2 pt-0">
              {quotationRequests.length === 0 ? (
                <p className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-[11.5px] text-slate-500">
                  No quotation requests submitted yet.
                </p>
              ) : (
                quotationRequests.map((request) => (
                  <div key={request.id} className="rounded-lg border border-slate-200 px-3 py-2.5">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-[12px] font-semibold text-ink-900">
                          {request.business_name}
                        </p>
                        <p className="text-[10.5px] text-slate-500">
                          {request.reference} · submitted {formatDate(request.created_at)}
                        </p>
                      </div>
                      <StatusBadge status={request.status} />
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-1 text-[10.5px] text-slate-500">
                      <span>
                        Indicative benchmark {money(request.estimate.indicative_annual_fee)} per year ·
                        not a final fee
                      </span>
                      <span>{request.services.map((key) => serviceLabel(key)).join(" · ")}</span>
                    </div>
                  </div>
                ))
              )}
              <p className="text-[10px] leading-relaxed text-slate-400">
                The 2% turnover benchmark is indicative only. A senior accountant reviews the scope and
                approves the final fee before a quotation is sent.
              </p>
            </CardBody>
          </Card>
        </div>
      )}

      {tab === "messages" && (
        <Card>
          <CardHeader
            title="Messages"
            description="Conversations with your accounting team. Messages are retained with the engagement."
            icon={MessageSquare}
          />
          <CardBody className="pt-0">
            <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
              {messages.length === 0 ? (
                <p className="py-6 text-center text-[12px] text-slate-400">No messages yet.</p>
              ) : (
                messages.map((message) => (
                  <div
                    key={message.id}
                    className={`max-w-[85%] rounded-xl border px-3 py-2 ${
                      message.author_role === "customer"
                        ? "ml-auto border-brand-200 bg-brand-50"
                        : "border-slate-200 bg-slate-50"
                    }`}
                  >
                    <p className="text-[10px] font-semibold text-slate-500">
                      {message.author_label} · {formatDateTime(message.created_at)}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-700">{message.body}</p>
                  </div>
                ))
              )}
            </div>
            <div className="mt-3 flex items-start gap-2 border-t border-slate-100 pt-3">
              <Textarea
                value={messageBody}
                onChange={(event) => setMessageBody(event.target.value)}
                placeholder="Write a message to your accountant"
                className="min-h-[64px] flex-1"
                aria-label="Message to your accountant"
              />
              <Button icon={Send} loading={busy} onClick={() => void sendMessage()} disabled={!messageBody.trim()}>
                Send
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      <Modal
        open={uploadOpen}
        onClose={() => {
          setUploadOpen(false);
          setUploadRequestId(null);
        }}
        title="Upload a document"
        description={
          uploadRequestId
            ? "This upload fulfils your accountant's request."
            : "Shared with your accounting team only."
        }
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => {
                setUploadOpen(false);
                setUploadRequestId(null);
              }}
            >
              Cancel
            </Button>
            <Button icon={Upload} loading={busy} onClick={upload} disabled={!uploadFile}>
              Upload
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="File" htmlFor="client_doc_file" required hint="PDF, image, CSV or spreadsheet.">
            <input
              id="client_doc_file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.webp,.csv,.xls,.xlsx"
              onChange={(event) => {
                const file = event.target.files?.[0] || null;
                setUploadFile(file);
                if (file && !uploadForm.title) {
                  setUploadForm((form) => ({ ...form, title: file.name }));
                }
              }}
              className="block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-slate-700"
            />
          </Field>
          <Field label="Title" htmlFor="client_doc_title">
            <Input
              id="client_doc_title"
              value={uploadForm.title}
              onChange={(event) => setUploadForm({ ...uploadForm, title: event.target.value })}
              placeholder="October bank statement"
            />
          </Field>
          <Field label="Category" htmlFor="client_doc_category">
            <Select
              id="client_doc_category"
              value={uploadForm.category}
              onChange={(event) => setUploadForm({ ...uploadForm, category: event.target.value })}
            >
              {DOCUMENT_CATEGORIES.map((category) => (
                <option key={category.key} value={category.key}>
                  {category.label}
                </option>
              ))}
            </Select>
          </Field>
          <p className="text-[10px] leading-relaxed text-slate-400">
            Files are stored under a random name with a SHA-256 digest. Only your engagement team can access
            them.
          </p>
        </div>
      </Modal>

      <Modal
        open={requestOpen}
        onClose={() => setRequestOpen(false)}
        title="Request a quotation"
        description="A senior accountant reviews the scope and sends an approved quotation to this portal."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setRequestOpen(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              form="quotation-request-form"
              icon={Send}
              loading={busy}
              disabled={requestForm.services.length === 0 || !requestForm.consent}
            >
              Submit request
            </Button>
          </>
        }
      >
        <form id="quotation-request-form" onSubmit={(event) => void submitRequest(event)} className="space-y-4">
          <Callout tone="amber" title="No price is finalised here">
            The 2% turnover benchmark is indicative only. Your senior accountant reviews the scope and
            approves the final fee. Accounting fees are separate from any software subscription, and ITR
            filing is not included unless you select it.
          </Callout>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Business name" htmlFor="request_business" required error={requestFieldErrors.business_name}>
              <Input
                id="request_business"
                value={requestForm.business_name}
                onChange={(event) => setRequestForm({ ...requestForm, business_name: event.target.value })}
              />
            </Field>
            <Field label="Contact name" htmlFor="request_contact" required error={requestFieldErrors.contact_name}>
              <Input
                id="request_contact"
                value={requestForm.contact_name}
                onChange={(event) => setRequestForm({ ...requestForm, contact_name: event.target.value })}
              />
            </Field>
            <Field label="Email" htmlFor="request_email" required error={requestFieldErrors.email}>
              <Input
                id="request_email"
                type="email"
                value={requestForm.email}
                onChange={(event) => setRequestForm({ ...requestForm, email: event.target.value })}
              />
            </Field>
            <Field label="Phone" htmlFor="request_phone" hint="Optional.">
              <Input
                id="request_phone"
                value={requestForm.phone}
                onChange={(event) => setRequestForm({ ...requestForm, phone: event.target.value })}
              />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Business type" htmlFor="request_business_type" required error={requestFieldErrors.business_type}>
              <Select
                id="request_business_type"
                value={requestForm.business_type}
                onChange={(event) => setRequestForm({ ...requestForm, business_type: event.target.value })}
              >
                {(catalogue?.business_types ?? []).map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Turnover range" htmlFor="request_turnover_range" required error={requestFieldErrors.turnover_range}>
              <Select
                id="request_turnover_range"
                value={requestForm.turnover_range}
                onChange={(event) => setRequestForm({ ...requestForm, turnover_range: event.target.value })}
              >
                {(catalogue?.turnover_ranges ?? []).map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="GST status" htmlFor="request_gst" required error={requestFieldErrors.gst_status}>
              <Select
                id="request_gst"
                value={requestForm.gst_status}
                onChange={(event) => setRequestForm({ ...requestForm, gst_status: event.target.value })}
              >
                {(catalogue?.gst_statuses ?? []).map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <Field
              label="Annual turnover (INR)"
              htmlFor="request_annual_turnover"
              hint="Benchmark only."
            >
              <Input
                id="request_annual_turnover"
                inputMode="decimal"
                value={requestForm.annual_turnover}
                onChange={(event) =>
                  setRequestForm({
                    ...requestForm,
                    annual_turnover: event.target.value.replace(/[^\d.]/g, ""),
                  })
                }
                placeholder="3500000"
              />
            </Field>
            <Field label="Transactions / month" htmlFor="request_transactions">
              <Input
                id="request_transactions"
                inputMode="numeric"
                value={requestForm.monthly_transactions}
                onChange={(event) =>
                  setRequestForm({
                    ...requestForm,
                    monthly_transactions: event.target.value.replace(/[^\d]/g, ""),
                  })
                }
              />
            </Field>
            <Field label="Bank accounts" htmlFor="request_banks">
              <Input
                id="request_banks"
                inputMode="numeric"
                value={requestForm.bank_accounts}
                onChange={(event) =>
                  setRequestForm({
                    ...requestForm,
                    bank_accounts: event.target.value.replace(/[^\d]/g, ""),
                  })
                }
              />
            </Field>
            <Field label="Financial year" htmlFor="request_fy">
              <Input
                id="request_fy"
                value={requestForm.financial_year}
                onChange={(event) => setRequestForm({ ...requestForm, financial_year: event.target.value })}
                placeholder="2026-27"
              />
            </Field>
          </div>

          <div>
            <p className="field-label">
              Services required <span className="text-rose-500">*</span>
            </p>
            <div className="mt-1 grid gap-2 sm:grid-cols-2">
              {(catalogue?.services ?? []).map((service) => {
                const checked = requestForm.services.includes(service.key);
                return (
                  <label
                    key={service.key}
                    className={`flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 transition ${
                      checked ? "border-brand-300 bg-brand-50/70" : "border-slate-200 hover:border-slate-300"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setRequestForm({
                          ...requestForm,
                          services: checked
                            ? requestForm.services.filter((key) => key !== service.key)
                            : [...requestForm.services, service.key],
                        })
                      }
                      className="mt-0.5 h-3.5 w-3.5 accent-brand-600"
                    />
                    <span>
                      <span className="block text-[11.5px] font-medium text-ink-900">{service.name}</span>
                      <span className="block text-[10px] text-slate-500">{service.description}</span>
                    </span>
                  </label>
                );
              })}
            </div>
            {requestFieldErrors.services && (
              <p className="mt-1 text-[11px] font-medium text-rose-600">{requestFieldErrors.services}</p>
            )}
          </div>

          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-[12px] text-slate-600">
              <input
                type="checkbox"
                checked={requestForm.payroll_required}
                onChange={(event) =>
                  setRequestForm({ ...requestForm, payroll_required: event.target.checked })
                }
                className="h-4 w-4 accent-brand-600"
              />
              Payroll required
            </label>
            <label className="flex items-center gap-2 text-[12px] text-slate-600">
              <input
                type="checkbox"
                checked={requestForm.inventory_required}
                onChange={(event) =>
                  setRequestForm({ ...requestForm, inventory_required: event.target.checked })
                }
                className="h-4 w-4 accent-brand-600"
              />
              Inventory accounting required
            </label>
          </div>

          <Field label="Anything else we should know?" htmlFor="request_requirements">
            <Textarea
              id="request_requirements"
              value={requestForm.requirements}
              onChange={(event) => setRequestForm({ ...requestForm, requirements: event.target.value })}
              placeholder="Current books, deadlines, software in use, specific scope"
            />
          </Field>

          <label className="flex items-start gap-2 text-[11.5px] leading-relaxed text-slate-600">
            <input
              type="checkbox"
              checked={requestForm.consent}
              onChange={(event) => setRequestForm({ ...requestForm, consent: event.target.checked })}
              className="mt-0.5 h-4 w-4 accent-brand-600"
            />
            I confirm the details are accurate and the practice may contact me about this request.
          </label>
          {requestFieldErrors.consent && (
            <p className="text-[11px] font-medium text-rose-600">{requestFieldErrors.consent}</p>
          )}
        </form>
      </Modal>

      <Modal
        open={Boolean(quotationFor)}
        onClose={() => setQuotationFor(null)}
        title={quotationDecision === "accepted" ? "Accept quotation" : "Decline quotation"}
        description={
          quotationFor
            ? `${quotationFor.number} · ${money(quotationFor.total_annual)} per year`
            : undefined
        }
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setQuotationFor(null)}>
              Cancel
            </Button>
            <Button
              loading={busy}
              variant={quotationDecision === "accepted" ? "primary" : "danger"}
              onClick={() => void decideQuotation()}
            >
              {quotationDecision === "accepted" ? "Accept quotation" : "Decline quotation"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-[12px] leading-relaxed text-slate-600">
            {quotationDecision === "accepted"
              ? "Accepting confirms the scope and the approved fee. It does not charge any amount — your accountant will arrange a separate secure payment process and onboarding."
              : "Declining records your decision. You can message your accountant to discuss a different scope."}
          </p>
          <Field label="Note (optional)" htmlFor="quotation_note">
            <Textarea
              id="quotation_note"
              value={quotationNote}
              onChange={(event) => setQuotationNote(event.target.value)}
              placeholder="Any context for your accountant."
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}

function ReportCard({ report }: { report: AccountingReport }) {
  const payload = (report.payload || {}) as Record<string, unknown>;
  const observations = Array.isArray(payload.observations) ? (payload.observations as string[]) : [];
  return (
    <Card>
      <CardHeader
        title={`${labelize(report.report_type)} · ${report.period_label}`}
        description={`Financial year ${report.financial_year} · version ${report.version}`}
        icon={FileText}
        actions={<StatusBadge status={report.status} />}
      />
      <CardBody className="space-y-2 pt-0">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
          <Badge tone="green">Approved {formatDate(report.approved_at)}</Badge>
          {report.delivered_at && <Badge tone="blue">Delivered {formatDate(report.delivered_at)}</Badge>}
        </div>
        {report.report_type === "monthly_summary" && (
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-200 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Revenue</p>
              <p className="mt-0.5 text-[13px] font-semibold text-ink-900">{money(Number(payload.revenue) || 0)}</p>
            </div>
            <div className="rounded-lg border border-slate-200 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Purchases</p>
              <p className="mt-0.5 text-[13px] font-semibold text-ink-900">{money(Number(payload.expenses) || 0)}</p>
            </div>
            <div className="rounded-lg border border-slate-200 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Gross profit</p>
              <p className="mt-0.5 text-[13px] font-semibold text-emerald-700">{money(Number(payload.gross_profit) || 0)}</p>
            </div>
          </div>
        )}
        {(report.report_type === "gstr1" || report.report_type === "gstr3b") && (
          <p className="text-[11px] text-slate-500">
            {(payload.filing_status as string) || "Working paper"} — this is an internal working paper, not an
            official filing.
          </p>
        )}
        {report.report_type === "financials" && (
          <p className="text-[11px] text-slate-500">
            {String(payload.note || "Draft management accounts from recorded vouchers.")}
          </p>
        )}
        {observations.length > 0 && (
          <ul className="space-y-1">
            {observations.map((line) => (
              <li key={line} className="rounded-lg bg-slate-50 px-3 py-1.5 text-[11px] text-slate-600">
                {line}
              </li>
            ))}
          </ul>
        )}
        <details className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
          <summary className="cursor-pointer text-[10px] font-semibold text-slate-500">Report data</summary>
          <pre className="mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[10px] leading-relaxed text-slate-600">
            {JSON.stringify(report.payload, null, 2)}
          </pre>
        </details>
      </CardBody>
    </Card>
  );
}
