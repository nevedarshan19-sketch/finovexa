import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, FileCheck2, Files, ShieldCheck, Upload, XCircle } from "lucide-react";
import { downloadFile, get, getErrorMessage, post } from "../../lib/api";
import type { AccountingClient, AccountingDocument } from "../../lib/accountingTypes";
import { DOCUMENT_CATEGORIES, fileToDataUrl, formatBytes, labelize } from "../../lib/accounting";
import { formatDate } from "../../lib/utils";
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

export function AccountantDocumentsPage() {
  const [documents, setDocuments] = useState<AccountingDocument[]>([]);
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [clientFilter, setClientFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [busy, setBusy] = useState(false);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadForm, setUploadForm] = useState({
    client_id: "",
    title: "",
    category: "purchase_bill",
    notes: "",
  });
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  const [reviewFor, setReviewFor] = useState<AccountingDocument | null>(null);
  const [reviewNote, setReviewNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (clientFilter) params.set("client_id", clientFilter);
      if (statusFilter) params.set("status", statusFilter);
      if (categoryFilter) params.set("category", categoryFilter);
      const suffix = params.toString();
      const data = await get<{ items: AccountingDocument[] }>(
        `/accounting/senior/documents${suffix ? `?${suffix}` : ""}`,
      );
      setDocuments(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [clientFilter, statusFilter, categoryFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    get<{ items: AccountingClient[] }>("/accounting/senior/clients")
      .then((data) => setClients(data.items))
      .catch(() => setClients([]));
  }, []);

  const clientName = useMemo(() => {
    const map = new Map(clients.map((client) => [client.id, client.business_name]));
    return (id: number) => map.get(id) || `Client #${id}`;
  }, [clients]);

  const upload = async () => {
    if (!uploadFile) return;
    setBusy(true);
    setActionError(null);
    try {
      const dataUrl = await fileToDataUrl(uploadFile);
      await post("/accounting/documents", {
        client_id: Number(uploadForm.client_id),
        filename: uploadFile.name,
        data_url: dataUrl,
        title: uploadForm.title || uploadFile.name,
        category: uploadForm.category,
        note: uploadForm.notes || null,
      });
      setUploadOpen(false);
      setUploadFile(null);
      setUploadForm({ client_id: uploadForm.client_id, title: "", category: "purchase_bill", notes: "" });
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const review = async (status: "verified" | "rejected") => {
    if (!reviewFor) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/senior/documents/${reviewFor.id}/review`, {
        status,
        note: reviewNote || null,
      });
      setReviewFor(null);
      setReviewNote("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const download = async (doc: AccountingDocument) => {
    try {
      await downloadFile(`/accounting/documents/${doc.id}/file`, doc.original_filename);
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  if (loading && documents.length === 0) return <PageSkeleton cards={4} />;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Secure vault"
        title="Client documents"
        description="Review client uploads before they are used in bookkeeping. Files are stored with a SHA-256 digest and role-based access."
        actions={
          <Button icon={Upload} onClick={() => setUploadOpen(true)}>
            Upload document
          </Button>
        }
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Documents" value={documents.length} icon={Files} tone="blue" />
        <StatCard
          label="Received"
          value={documents.filter((doc) => doc.status === "received").length}
          icon={FileCheck2}
          tone="amber"
        />
        <StatCard
          label="Verified"
          value={documents.filter((doc) => doc.status === "verified").length}
          icon={ShieldCheck}
          tone="green"
        />
        <StatCard
          label="Rejected"
          value={documents.filter((doc) => doc.status === "rejected").length}
          icon={XCircle}
          tone="red"
        />
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          title="Document register"
          description="Internal files stay hidden from the client portal until shared."
          icon={Files}
          actions={
            <>
              <Select
                aria-label="Document status"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="h-8 min-w-[130px] text-[11px]"
              >
                <option value="">All statuses</option>
                {["received", "verified", "rejected"].map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Document category"
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
                className="h-8 min-w-[150px] text-[11px]"
              >
                <option value="">All categories</option>
                {DOCUMENT_CATEGORIES.map((category) => (
                  <option key={category.key} value={category.key}>
                    {category.label}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Client"
                value={clientFilter}
                onChange={(event) => setClientFilter(event.target.value)}
                className="h-8 min-w-[170px] text-[11px]"
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
          ) : documents.length === 0 ? (
            <EmptyState
              title="No documents"
              description="Client uploads and accountant files appear here with their verification state."
              icon={Files}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[940px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head">Document</th>
                    <th className="table-head">Client</th>
                    <th className="table-head">Category</th>
                    <th className="table-head">Visibility</th>
                    <th className="table-head">Status</th>
                    <th className="table-head">Size</th>
                    <th className="table-head">Uploaded</th>
                    <th className="table-head"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {documents.map((doc) => (
                    <tr key={doc.id} className="row-hover">
                      <td className="table-cell">
                        <p className="text-[12px] font-semibold text-ink-900">{doc.title}</p>
                        <p className="text-[10px] text-slate-500">{doc.original_filename}</p>
                      </td>
                      <td className="table-cell text-[11px] text-slate-600">{clientName(doc.client_id)}</td>
                      <td className="table-cell text-[11px] text-slate-500">{labelize(doc.category)}</td>
                      <td className="table-cell">
                        <Badge tone={doc.visibility === "shared" ? "blue" : "slate"}>
                          {doc.visibility === "shared" ? "Shared" : "Internal"}
                        </Badge>
                      </td>
                      <td className="table-cell">
                        <StatusBadge status={doc.status} />
                      </td>
                      <td className="table-cell text-[11px] text-slate-500">{formatBytes(doc.size_bytes)}</td>
                      <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                        {formatDate(doc.created_at)}
                      </td>
                      <td className="table-cell">
                        <div className="flex items-center gap-1.5">
                          <Button size="sm" variant="ghost" icon={Download} onClick={() => void download(doc)}>
                            Open
                          </Button>
                          {doc.status !== "verified" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setReviewFor(doc);
                                setReviewNote(doc.note || "");
                              }}
                            >
                              Review
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

      <Modal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title="Upload a client document"
        description="Stored on the server under a random filename; the original name is retained for display."
        footer={
          <>
            <Button variant="outline" onClick={() => setUploadOpen(false)}>
              Cancel
            </Button>
            <Button
              icon={Upload}
              loading={busy}
              onClick={upload}
              disabled={!uploadForm.client_id || !uploadFile}
            >
              Upload
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Client" htmlFor="doc_client" required>
            <Select
              id="doc_client"
              value={uploadForm.client_id}
              onChange={(event) => setUploadForm({ ...uploadForm, client_id: event.target.value })}
            >
              <option value="">Select a client</option>
              {clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.business_name} · {client.code}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="File" htmlFor="doc_file" required hint="PDF, image, CSV or spreadsheet.">
            <input
              id="doc_file"
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
          <Field label="Title" htmlFor="doc_title">
            <Input
              id="doc_title"
              value={uploadForm.title}
              onChange={(event) => setUploadForm({ ...uploadForm, title: event.target.value })}
              placeholder="October purchase bills"
            />
          </Field>
          <Field label="Category" htmlFor="doc_category">
            <Select
              id="doc_category"
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
          <Field label="Internal note" htmlFor="doc_notes">
            <Textarea
              id="doc_notes"
              value={uploadForm.notes}
              onChange={(event) => setUploadForm({ ...uploadForm, notes: event.target.value })}
              placeholder="Why this file was uploaded."
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(reviewFor)}
        onClose={() => setReviewFor(null)}
        title="Review document"
        description={reviewFor ? `${reviewFor.title} · ${reviewFor.original_filename}` : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setReviewFor(null)}>
              Cancel
            </Button>
            <Button variant="outline" loading={busy} onClick={() => void review("rejected")}>
              Reject
            </Button>
            <Button icon={ShieldCheck} loading={busy} onClick={() => void review("verified")}>
              Verify
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-[12px] leading-relaxed text-slate-600">
            Verify only after the bill has been checked against the ledger. Rejected documents stay on
            file with your note so the client can replace them.
          </p>
          <Field label="Review note" htmlFor="doc_review_note">
            <Textarea
              id="doc_review_note"
              value={reviewNote}
              onChange={(event) => setReviewNote(event.target.value)}
              placeholder="What was checked, or why this file is rejected."
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
