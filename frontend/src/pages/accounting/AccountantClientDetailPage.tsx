import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Building2,
  Download,
  FileStack,
  FileUp,
  Link2,
  MessageSquareText,
  Plus,
  Send,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { downloadFile, get, getErrorMessage, patch, post } from "../../lib/api";
import type {
  AccountantOption,
  AccountingClient,
  AccountingDocument,
  AccountingMessage,
  ClientDetailResponse,
} from "../../lib/accountingTypes";
import { DOCUMENT_CATEGORIES, SERVICE_LABELS, fileToDataUrl, formatBytes, labelize } from "../../lib/accounting";
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
  Tabs,
  Textarea,
} from "../../components/ui";
import { StatusBadge } from "../../components/accounting/AccountingUI";
import { ClientBusinessPanel } from "../../components/accounting/ClientBusinessPanel";
import { ExportCentrePanel } from "../../components/accounting/ExportCentrePanel";
import { GstCataloguePanel } from "../../components/tax/GstCataloguePanel";

type TabKey =
  | "overview"
  | "business"
  | "gst_catalogue"
  | "export_centre"
  | "tasks"
  | "documents"
  | "billing"
  | "messages";

export function AccountantClientDetailPage() {
  const { clientId } = useParams<{ clientId: string }>();
  const { isSeniorAccountant } = useAuth();
  const id = Number(clientId);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [detail, setDetail] = useState<ClientDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");
  const [juniors, setJuniors] = useState<AccountantOption[]>([]);
  const [busy, setBusy] = useState(false);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadCategory, setUploadCategory] = useState("purchase_bill");
  const [requestOpen, setRequestOpen] = useState(false);
  const [requestForm, setRequestForm] = useState({ title: "", description: "", due_date: "" });
  const [reviewDoc, setReviewDoc] = useState<{ document: AccountingDocument; status: "verified" | "rejected" } | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    setLoading(true);
    setError(null);
    try {
      const path = isSeniorAccountant
        ? `/accounting/senior/clients/${id}`
        : `/accounting/junior/clients/${id}`;
      setDetail(await get<ClientDetailResponse>(path));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id, isSeniorAccountant]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!isSeniorAccountant) return;
    get<{ items: AccountantOption[] }>("/accounting/senior/accountants")
      .then((data) => setJuniors(data.items.filter((row) => row.role === "junior_accountant")))
      .catch(() => setJuniors([]));
  }, [isSeniorAccountant]);

  const client: AccountingClient | undefined = detail?.client;

  const assignJunior = async (juniorUserId: number | null) => {
    if (!client) return;
    setActionError(null);
    try {
      await post(`/accounting/senior/clients/${client.id}/assign`, { junior_user_id: juniorUserId });
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const changeStatus = async (status: string) => {
    if (!client) return;
    setActionError(null);
    try {
      await patch(`/accounting/senior/clients/${client.id}`, { status });
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const upload = async () => {
    if (!client || !uploadFile) return;
    setBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(uploadFile);
      await post("/accounting/documents", {
        client_id: client.id,
        filename: uploadFile.name,
        data_url: dataUrl,
        title: uploadTitle.trim() || uploadFile.name,
        category: uploadCategory,
      });
      setUploadOpen(false);
      setUploadFile(null);
      setUploadTitle("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const requestDocument = async () => {
    if (!client) return;
    setBusy(true);
    setActionError(null);
    try {
      await post("/accounting/document-requests", {
        client_id: client.id,
        title: requestForm.title,
        description: requestForm.description || null,
        due_date: requestForm.due_date || null,
      });
      setRequestOpen(false);
      setRequestForm({ title: "", description: "", due_date: "" });
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitReview = async () => {
    if (!reviewDoc) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/senior/documents/${reviewDoc.document.id}/review`, {
        status: reviewDoc.status,
        note: reviewNote || null,
      });
      setReviewDoc(null);
      setReviewNote("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const sendMessage = async () => {
    if (!client || message.trim().length < 2) return;
    setBusy(true);
    setActionError(null);
    try {
      await post<AccountingMessage>(`/accounting/messages?client_id=${client.id}`, { body: message.trim() });
      setMessage("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading && !detail) return <PageSkeleton cards={4} />;
  if (error && !detail)
    return (
      <div className="space-y-4">
        <Link to="/accountant/clients" className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to clients
        </Link>
        <ErrorState message={error} onRetry={load} />
      </div>
    );
  if (!detail || !client) return null;

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "overview", label: "Overview" },
    { key: "business", label: "Business data" },
    { key: "gst_catalogue", label: "GST Catalogue" },
    { key: "export_centre", label: "Export Centre" },
    { key: "tasks", label: "Tasks", count: detail.tasks.length },
    { key: "documents", label: "Documents", count: detail.documents.length },
    ...(isSeniorAccountant
      ? [{ key: "billing" as TabKey, label: "Billing", count: detail.invoices?.length ?? 0 }]
      : []),
    { key: "messages", label: "Messages", count: detail.messages.length },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/accountant/clients" className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600">
          <ArrowLeft className="h-3.5 w-3.5" /> Clients
        </Link>
        <Link
          to={`/accountant/work?clientId=${client.id}`}
          className="text-xs font-semibold text-brand-600 hover:text-brand-700"
        >
          Open workbench for this client →
        </Link>
      </div>

      <PageHeader
        eyebrow={`${client.code} · FY ${client.financial_year}`}
        title={client.business_name}
        description={`${client.contact_name} · ${client.email}${client.phone ? ` · ${client.phone}` : ""}`}
        actions={<StatusBadge status={client.status} />}
      />

      {client.linked_business && (
        <Callout tone="blue" title="Linked to Business Manager" icon={Link2}>
          This engagement is linked to {client.linked_business.business_name}
          {client.linked_business.city ? ` (${client.linked_business.city})` : ""}. Business
          records are copied into a review inbox only when the practice runs a sync, and
          only approved entries are posted to the books or included in Tally exports.
        </Callout>
      )}

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      {isSeniorAccountant && (
        <Card>
          <CardBody className="grid gap-3 sm:grid-cols-3">
            <Field label="Assigned junior accountant" htmlFor="assign_junior">
              <Select
                id="assign_junior"
                value={client.assigned_junior_user_id ?? ""}
                onChange={(event) => void assignJunior(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">Unassigned</option>
                {juniors.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name} · {person.open_tasks} open tasks
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Engagement status" htmlFor="client_status_change">
              <Select
                id="client_status_change"
                value={client.status}
                onChange={(event) => void changeStatus(event.target.value)}
              >
                {["onboarding", "active", "paused", "archived"].map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex items-end gap-2">
              <Button variant="outline" icon={FileUp} className="flex-1" onClick={() => setUploadOpen(true)}>
                Upload document
              </Button>
              <Button variant="outline" icon={Plus} className="flex-1" onClick={() => setRequestOpen(true)}>
                Request document
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      {!isSeniorAccountant && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" icon={FileUp} onClick={() => setUploadOpen(true)}>
            Upload document
          </Button>
          <Button variant="outline" icon={Plus} onClick={() => setRequestOpen(true)}>
            Request document
          </Button>
        </div>
      )}

      <Tabs items={tabs} value={tab} onChange={setTab} />

      {tab === "overview" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader title="Client record" description="Secure identifiers and engagement details." icon={Building2} />
            <CardBody className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Business type</p>
                <p className="text-[13px] text-slate-700">{labelize(client.business_type)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Annual turnover</p>
                <p className="text-[13px] text-slate-700">{client.turnover_range}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">GST status</p>
                <p className="text-[13px] text-slate-700">{labelize(client.gst_status)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">GSTIN</p>
                <p className="font-mono text-[12px] text-slate-700">{client.gstin || "Not recorded"}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">PAN</p>
                <p className="font-mono text-[12px] text-slate-700">••••{client.pan_last4 || "····"}</p>
                <p className="text-[10px] text-slate-400">Only the last four characters are stored.</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Service package</p>
                <p className="text-[13px] text-slate-700">{client.service_package}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Senior accountant</p>
                <p className="text-[13px] text-slate-700">{client.senior_name || "—"}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Junior accountant</p>
                <p className="text-[13px] text-slate-700">{client.junior_name || "Unassigned"}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Onboarded</p>
                <p className="text-[13px] text-slate-700">{formatDate(client.onboarded_at)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Client portal</p>
                <p className="text-[13px] text-slate-700">
                  {client.customer_user_id ? "Login linked" : "No login created"}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Business Manager link</p>
                <p className="text-[13px] text-slate-700">
                  {client.linked_business ? client.linked_business.business_name : "Not linked"}
                </p>
                {client.linked_business && (
                  <p className="text-[10px] text-slate-400">Records are not auto-synced.</p>
                )}
              </div>
              {client.notes && (
                <div className="sm:col-span-2">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Internal notes</p>
                  <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-slate-600">{client.notes}</p>
                </div>
              )}
            </CardBody>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader title="Work and records" icon={FileStack} />
              <CardBody className="grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-slate-200 p-3">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Open tasks</p>
                  <p className="mt-1 text-xl font-semibold tabular text-ink-900">{client.counts?.open_tasks ?? 0}</p>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Documents</p>
                  <p className="mt-1 text-xl font-semibold tabular text-ink-900">{client.counts?.documents ?? 0}</p>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Vouchers</p>
                  <p className="mt-1 text-xl font-semibold tabular text-ink-900">{detail.vouchers.count}</p>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">Reports</p>
                  <p className="mt-1 text-xl font-semibold tabular text-ink-900">{client.counts?.reports ?? 0}</p>
                </div>
              </CardBody>
            </Card>

            {isSeniorAccountant && client.billing && (
              <Card>
                <CardHeader title="Fee position" icon={UsersRound} />
                <CardBody className="space-y-2 text-[12px]">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Invoiced</span>
                    <span className="font-semibold tabular text-ink-900">{money(client.billing.invoiced)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Paid</span>
                    <span className="font-semibold tabular text-emerald-700">{money(client.billing.paid)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Outstanding</span>
                    <span className="font-semibold tabular text-amber-700">{money(client.billing.outstanding)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Overdue</span>
                    <span className="font-semibold tabular text-rose-700">{money(client.billing.overdue)}</span>
                  </div>
                </CardBody>
              </Card>
            )}

            <Card>
              <CardHeader title="Recent vouchers" icon={FileStack} />
              <CardBody className="pt-0">
                {detail.vouchers.recent.length === 0 ? (
                  <p className="text-[11px] text-slate-500">No vouchers posted for this client yet.</p>
                ) : (
                  <ul className="divide-y divide-slate-100">
                    {detail.vouchers.recent.slice(0, 6).map((voucher) => (
                      <li key={voucher.id} className="flex items-center justify-between gap-2 py-2">
                        <div className="min-w-0">
                          <p className="truncate text-[12px] font-semibold text-ink-900">{voucher.number}</p>
                          <p className="truncate text-[10px] text-slate-500">
                            {labelize(voucher.voucher_type)} · {voucher.party_name}
                          </p>
                        </div>
                        <span className="shrink-0 text-[11px] font-semibold tabular text-slate-700">
                          {money(voucher.taxable_value)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>
          </div>
        </div>
      )}

      {tab === "business" && (
        <ClientBusinessPanel clientId={client.id} isSeniorAccountant={isSeniorAccountant} />
      )}

      {tab === "gst_catalogue" && (
        <GstCataloguePanel
          endpoint={
            isSeniorAccountant
              ? `/accounting/senior/clients/${client.id}/gst-catalogue`
              : `/accounting/junior/clients/${client.id}/gst-catalogue`
          }
          role="accountant"
          canEdit={isSeniorAccountant ? undefined : false}
          exportPath={
            isSeniorAccountant
              ? `/accounting/senior/clients/${client.id}/gst-catalogue/export`
              : null
          }
          permissionEndpoint={
            isSeniorAccountant
              ? `/accounting/senior/clients/${client.id}/gst-catalogue/permission`
              : null
          }
        />
      )}

      {tab === "export_centre" && <ExportCentrePanel clientId={client.id} />}

      {tab === "tasks" && (
        <Card>
          <CardHeader
            title="Tasks for this client"
            description="Work moves through assignment, preparation, senior review and delivery."
            actions={
              <Link to={`/accountant/tasks?clientId=${client.id}`} className="text-[11px] font-semibold text-brand-600">
                Manage tasks
              </Link>
            }
          />
          <CardBody className="pt-0">
            {detail.tasks.length === 0 ? (
              <EmptyState title="No tasks yet" description="Create a task for this client from the task board." />
            ) : (
              <div className="space-y-2">
                {detail.tasks.map((task) => (
                  <div key={task.id} className="rounded-lg border border-slate-200 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-[13px] font-semibold text-ink-900">{task.title}</p>
                      <div className="flex items-center gap-1.5">
                        <StatusBadge status={task.status} />
                      </div>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {SERVICE_LABELS[task.service_type] || labelize(task.service_type)} ·{" "}
                      {task.assignee_name || "Unassigned"} · due{" "}
                      {formatDate(task.due_date)}
                      {task.is_overdue ? " · overdue" : ""}
                    </p>
                    <ProgressBar value={task.progress} className="mt-2" label={`${task.title} progress`} />
                    {task.review_notes && task.status === "changes_requested" && (
                      <p className="mt-2 rounded-md bg-rose-50 px-2 py-1.5 text-[11px] text-rose-700">
                        Changes requested: {task.review_notes}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {tab === "documents" && (
        <Card>
          <CardHeader
            title="Documents"
            description="Files are stored with a random name and checksum; access is scoped to this engagement."
            actions={
              <>
                <Button size="sm" variant="outline" icon={FileUp} onClick={() => setUploadOpen(true)}>
                  Upload
                </Button>
                <Button size="sm" variant="outline" icon={Plus} onClick={() => setRequestOpen(true)}>
                  Request
                </Button>
              </>
            }
          />
          <CardBody className="pt-0">
            {detail.document_requests.length > 0 && (
              <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2">
                <p className="text-[11px] font-semibold text-amber-900">Pending document requests</p>
                <ul className="mt-1 space-y-1">
                  {detail.document_requests.map((request) => (
                    <li key={request.id} className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-amber-800">
                      <span>
                        {request.title}
                        {request.due_date ? ` · due ${formatDate(request.due_date)}` : ""}
                      </span>
                      <StatusBadge status={request.status} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {detail.documents.length === 0 ? (
              <EmptyState title="No documents" description="Upload client records or request them from the client." icon={FileStack} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head">Document</th>
                      <th className="table-head">Category</th>
                      <th className="table-head">Uploaded</th>
                      <th className="table-head">Status</th>
                      <th className="table-head">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {detail.documents.map((document) => (
                      <tr key={document.id} className="row-hover">
                        <td className="table-cell">
                          <p className="text-[12px] font-semibold text-ink-900">{document.title}</p>
                          <p className="text-[10px] text-slate-500">
                            {document.original_filename} · {formatBytes(document.size_bytes)} ·{" "}
                            {document.visibility === "shared" ? "shared with client" : "internal"}
                          </p>
                        </td>
                        <td className="table-cell text-[11px] text-slate-600">{labelize(document.category)}</td>
                        <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                          {formatDateTime(document.created_at)}
                        </td>
                        <td className="table-cell">
                          <StatusBadge status={document.status} />
                        </td>
                        <td className="table-cell">
                          <div className="flex flex-wrap gap-1">
                            {document.download_url && (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon={Download}
                                onClick={() => void downloadFile(document.download_url!, document.original_filename)}
                              >
                                Download
                              </Button>
                            )}
                            {isSeniorAccountant && document.status !== "verified" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon={ShieldCheck}
                                onClick={() => {
                                  setReviewDoc({ document, status: "verified" });
                                  setReviewNote("");
                                }}
                              >
                                Verify
                              </Button>
                            )}
                            {isSeniorAccountant && document.status !== "rejected" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                  setReviewDoc({ document, status: "rejected" });
                                  setReviewNote("");
                                }}
                              >
                                Reject
                              </Button>
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

      {tab === "billing" && isSeniorAccountant && (
        <Card>
          <CardHeader
            title="Practice invoices"
            description="Fees billed to this client and payments recorded against them."
            actions={
              <Link to="/accountant/billing" className="text-[11px] font-semibold text-brand-600">
                Billing desk
              </Link>
            }
          />
          <CardBody className="pt-0">
            {!detail.invoices || detail.invoices.length === 0 ? (
              <EmptyState title="No invoices" description="Issue a fee invoice from the practice billing desk." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head">Invoice</th>
                      <th className="table-head">Issued</th>
                      <th className="table-head">Total</th>
                      <th className="table-head">Paid</th>
                      <th className="table-head">Outstanding</th>
                      <th className="table-head">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {detail.invoices.map((invoice) => (
                      <tr key={invoice.id} className="row-hover">
                        <td className="table-cell text-[12px] font-semibold text-ink-900">{invoice.number}</td>
                        <td className="table-cell text-[11px] text-slate-500">{formatDate(invoice.issue_date)}</td>
                        <td className="table-cell tabular text-[12px]">{money(invoice.total_amount)}</td>
                        <td className="table-cell tabular text-[12px]">{money(invoice.paid_amount)}</td>
                        <td className="table-cell tabular text-[12px]">{money(invoice.outstanding_amount)}</td>
                        <td className="table-cell">
                          <StatusBadge status={invoice.is_overdue ? "overdue" : invoice.status} />
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

      {tab === "messages" && (
        <Card>
          <CardHeader
            title="Conversation with the client"
            description="Messages are visible to the client in their portal and to the practice team."
            icon={MessageSquareText}
          />
          <CardBody>
            <div className="max-h-80 space-y-2 overflow-y-auto rounded-lg border border-slate-100 bg-slate-50/60 p-3">
              {detail.messages.length === 0 ? (
                <p className="text-[11px] text-slate-500">No messages yet.</p>
              ) : (
                detail.messages.map((item) => (
                  <div
                    key={item.id}
                    className={
                      item.author_role === "customer"
                        ? "ml-6 rounded-lg rounded-br-none border border-teal-200 bg-teal-50 px-3 py-2"
                        : "mr-6 rounded-lg rounded-bl-none border border-slate-200 bg-white px-3 py-2"
                    }
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[11px] font-semibold text-ink-900">{item.author_label}</p>
                      <span className="text-[10px] text-slate-400">{formatDateTime(item.created_at)}</span>
                    </div>
                    <p className="mt-0.5 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-600">{item.body}</p>
                  </div>
                ))
              )}
            </div>
            <div className="mt-3 flex items-end gap-2">
              <div className="flex-1">
                <Textarea
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="Write to the client. Do not include passwords or full PAN/card numbers."
                  className="min-h-[70px]"
                />
              </div>
              <Button icon={Send} loading={busy} onClick={sendMessage} disabled={message.trim().length < 2}>
                Send
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      <Modal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title="Upload a document"
        description="PDF, PNG, JPEG, CSV or Excel. Files stay scoped to this client."
        footer={
          <>
            <Button variant="outline" onClick={() => setUploadOpen(false)}>
              Cancel
            </Button>
            <Button icon={FileUp} loading={busy} onClick={upload} disabled={!uploadFile}>
              Upload
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="File" htmlFor="client_document_file" required>
            <input
              ref={fileInputRef}
              id="client_document_file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.csv,.xlsx,.xls"
              onChange={(event) => {
                const file = event.target.files?.[0] || null;
                setUploadFile(file);
                if (file && !uploadTitle) setUploadTitle(file.name.replace(/\.[^.]+$/, ""));
              }}
              className="block w-full text-xs text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-brand-700"
            />
          </Field>
          <Field label="Title" htmlFor="client_document_title">
            <Input
              id="client_document_title"
              value={uploadTitle}
              onChange={(event) => setUploadTitle(event.target.value)}
            />
          </Field>
          <Field label="Category" htmlFor="client_document_category">
            <Select
              id="client_document_category"
              value={uploadCategory}
              onChange={(event) => setUploadCategory(event.target.value)}
            >
              {DOCUMENT_CATEGORIES.map((category) => (
                <option key={category.key} value={category.key}>
                  {category.label}
                </option>
              ))}
            </Select>
          </Field>
          <p className="text-[10px] leading-relaxed text-slate-400">
            The file is stored under a random name with a SHA-256 checksum. Internal files are never exposed
            to the client portal.
          </p>
        </div>
      </Modal>

      <Modal
        open={requestOpen}
        onClose={() => setRequestOpen(false)}
        title="Request a document"
        description="The client sees this in their portal and gets a notification."
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setRequestOpen(false)}>
              Cancel
            </Button>
            <Button loading={busy} onClick={requestDocument} disabled={requestForm.title.trim().length < 3}>
              Send request
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="What do you need?" htmlFor="request_title" required>
            <Input
              id="request_title"
              value={requestForm.title}
              onChange={(event) => setRequestForm({ ...requestForm, title: event.target.value })}
              placeholder="Bank statement for October"
            />
          </Field>
          <Field label="Due date" htmlFor="request_due">
            <Input
              id="request_due"
              type="date"
              value={requestForm.due_date}
              onChange={(event) => setRequestForm({ ...requestForm, due_date: event.target.value })}
            />
          </Field>
          <Field label="Details" htmlFor="request_description">
            <Textarea
              id="request_description"
              value={requestForm.description}
              onChange={(event) => setRequestForm({ ...requestForm, description: event.target.value })}
              placeholder="Which account, which period, preferred format"
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(reviewDoc)}
        onClose={() => setReviewDoc(null)}
        title={reviewDoc?.status === "verified" ? "Verify document" : "Reject document"}
        description={reviewDoc ? reviewDoc.document.title : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setReviewDoc(null)}>
              Cancel
            </Button>
            <Button
              variant={reviewDoc?.status === "verified" ? "success" : "danger"}
              loading={busy}
              onClick={submitReview}
            >
              {reviewDoc?.status === "verified" ? "Mark verified" : "Reject"}
            </Button>
          </>
        }
      >
        <Field label="Review note" htmlFor="document_review_note">
          <Textarea
            id="document_review_note"
            value={reviewNote}
            onChange={(event) => setReviewNote(event.target.value)}
            placeholder="What was checked, or why it was rejected"
          />
        </Field>
      </Modal>

      <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
        <Badge tone="slate" dot>
          Access scoped to {client.code}
        </Badge>
        <span>Every upload, review and message is written to the accounting audit trail.</span>
      </div>
    </div>
  );
}
