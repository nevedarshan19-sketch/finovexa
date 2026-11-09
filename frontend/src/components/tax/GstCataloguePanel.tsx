import { useEffect, useState } from "react";
import {
  Check,
  Clock,
  Download,
  History,
  Pencil,
  Percent,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { downloadFile, getErrorMessage, patch, post, put } from "../../lib/api";
import { useApi } from "../../hooks/useApi";
import { useToast } from "../../context/ToastContext";
import { formatDate, formatDateTime } from "../../lib/utils";
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
  Modal,
  Select,
  StatCard,
  TableWrap,
  TBody,
  TD,
  Textarea,
  TH,
  THead,
  TR,
} from "../ui";

export interface GstCatalogueItem {
  id: number;
  sku: string;
  name: string;
  hsn_sac: string | null;
  item_type: string;
  unit: string;
  gst_rate: number;
  gst_effective_from: string | null;
  gst_verified: boolean;
  gst_change_reason: string | null;
  gst_updated_by: { id: number; name: string } | null;
  gst_updated_at: string;
  pending_change: GstCatalogueChange | null;
}

export interface GstCatalogueChange {
  id: number;
  product_id: number;
  product_name: string | null;
  sku: string | null;
  old_gst_rate: number;
  new_gst_rate: number;
  old_hsn_sac: string | null;
  new_hsn_sac: string | null;
  old_item_type: string | null;
  new_item_type: string | null;
  old_hsn_verified: boolean | null;
  new_hsn_verified: boolean | null;
  effective_from: string | null;
  reason: string;
  status: string;
  requested_by: { id: number; name: string } | null;
  requested_by_role: string;
  decided_by: { id: number; name: string } | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

interface CatalogueResponse {
  items: GstCatalogueItem[];
  count: number;
  approval_mode: "direct" | "owner_approval";
  pending_changes: GstCatalogueChange[];
  pending_count: number;
  can_edit?: boolean;
  note?: string;
}

interface CatalogueHistoryResponse {
  items: GstCatalogueChange[];
  pending: GstCatalogueChange[];
}

interface GstCataloguePanelProps {
  endpoint: string;
  role: "owner" | "accountant";
  searchKey?: "q" | "search";
  canEdit?: boolean;
  exportPath?: string | null;
  permissionEndpoint?: string | null;
}

function rateLabel(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Number(value)}%`;
}

function changeStatusTone(status: string): "green" | "amber" | "red" | "slate" {
  if (status === "applied" || status === "approved") return "green";
  if (status === "pending_approval") return "amber";
  if (status === "rejected") return "red";
  return "slate";
}

function statusLabel(status: string): string {
  return status === "pending_approval" ? "pending approval" : status.replaceAll("_", " ");
}

export function GstCataloguePanel({
  endpoint,
  role,
  searchKey = "search",
  canEdit,
  exportPath,
  permissionEndpoint,
}: GstCataloguePanelProps) {
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<GstCatalogueItem | null>(null);
  const [deciding, setDeciding] = useState<{ change: GstCatalogueChange; approve: boolean } | null>(null);
  const [decisionNote, setDecisionNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState({
    gst_rate: "18",
    hsn_sac: "",
    item_type: "goods",
    hsn_verified: false,
    effective_from: "",
    reason: "",
  });

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const catalogue = useApi<CatalogueResponse>(
    `${endpoint}${query ? `?${searchKey}=${encodeURIComponent(query)}` : ""}`,
  );
  const history = useApi<CatalogueHistoryResponse>(`${endpoint}/history?limit=40`);

  const data = catalogue.data;
  const editable = canEdit ?? Boolean(data?.can_edit);
  const verifiedCount = data?.items.filter((item) => item.gst_verified).length ?? 0;
  const canDecide = role === "owner";

  const reload = () => {
    catalogue.reload();
    history.reload();
  };

  const openEdit = (item: GstCatalogueItem) => {
    setEditing(item);
    setFormError(null);
    setForm({
      gst_rate: String(item.gst_rate),
      hsn_sac: item.hsn_sac ?? "",
      item_type: item.item_type === "service" ? "services" : item.item_type || "goods",
      hsn_verified: item.gst_verified,
      effective_from: item.gst_effective_from ?? "",
      reason: "",
    });
  };

  const closeEdit = () => {
    if (busy) return;
    setEditing(null);
    setFormError(null);
  };

  const submitEdit = async () => {
    if (!editing) return;
    if (form.reason.trim().length < 3) {
      setFormError("Give a short reason for this GST change (at least 3 characters).");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const result = await patch<{ message: string }>(`${endpoint}/${editing.id}`, {
        gst_rate: Number(form.gst_rate),
        hsn_sac: form.hsn_sac.trim() || null,
        item_type: form.item_type,
        hsn_verified: form.hsn_verified,
        effective_from: form.effective_from || null,
        reason: form.reason.trim(),
      });
      toast({ title: "GST catalogue change saved", description: result.message, tone: "success" });
      setEditing(null);
      reload();
    } catch (err: unknown) {
      setFormError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitDecision = async () => {
    if (!deciding) return;
    setBusy(true);
    try {
      const result = await post<{ message: string }>(
        `/tax/gst/catalogue/changes/${deciding.change.id}/decision`,
        { approve: deciding.approve, note: decisionNote.trim() || null },
      );
      toast({ title: "Change reviewed", description: result.message, tone: "success" });
      setDeciding(null);
      setDecisionNote("");
      reload();
    } catch (err: unknown) {
      toast({ title: "Could not review the change", description: getErrorMessage(err), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const changeApprovalMode = async (mode: "direct" | "owner_approval") => {
    setBusy(true);
    try {
      await put("/tax/gst/catalogue/settings", { approval_mode: mode });
      toast({
        title: mode === "direct" ? "Direct changes enabled" : "Owner approval required",
        description:
          mode === "direct"
            ? "Accountants with catalogue access apply GST changes immediately."
            : "Accountant GST changes now wait for your approval.",
        tone: "success",
      });
      reload();
    } catch (err: unknown) {
      toast({ title: "Could not change the approval mode", description: getErrorMessage(err), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const togglePermission = async (enabled: boolean) => {
    if (!permissionEndpoint) return;
    setBusy(true);
    try {
      await put(permissionEndpoint, { enabled });
      toast({
        title: enabled ? "Catalogue editing enabled" : "Catalogue editing revoked",
        tone: "success",
      });
      reload();
    } catch (err: unknown) {
      toast({ title: "Could not update the permission", description: getErrorMessage(err), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!exportPath) return;
    try {
      await downloadFile(exportPath, "finovexa-gst-catalogue.xlsx");
    } catch (err: unknown) {
      toast({ title: "Export failed", description: getErrorMessage(err), tone: "error" });
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard
          label="Catalogue items"
          value={data?.count ?? 0}
          sub="each with its own GST rate"
          tone="blue"
          icon={Percent}
        />
        <StatCard
          label="Verified HSN / SAC"
          value={verifiedCount}
          sub="checked against a notification"
          tone="green"
          icon={ShieldCheck}
        />
        <StatCard
          label="Pending approvals"
          value={data?.pending_count ?? 0}
          sub="accountant proposals"
          tone={(data?.pending_count ?? 0) > 0 ? "amber" : "slate"}
          icon={Clock}
        />
      </div>

      <Callout tone="amber" title="Existing invoices never change">
        Each item keeps its own GST rate and HSN/SAC. A change applies to new invoice lines only —
        issued invoices keep the tax snapshot they were issued with, and every change is recorded
        with the old rate, new rate, person, time and reason.
      </Callout>

      {permissionEndpoint && data && (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-3">
            <div className="max-w-2xl">
              <p className="text-sm font-semibold text-ink-900">Accountant GST editing</p>
              <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">
                Allow this accountant to manage GST rates and HSN/SAC for the linked business.
                Without this permission they can only view the catalogue.
              </p>
            </div>
            <Checkbox
              checked={editable}
              disabled={busy}
              onChange={(checked) => void togglePermission(checked)}
              label={editable ? "Editing enabled" : "Editing not granted"}
            />
          </CardBody>
        </Card>
      )}

      {role === "owner" && data && (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-3">
            <div className="max-w-2xl">
              <p className="text-sm font-semibold text-ink-900">Accountant change control</p>
              <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">
                {data.approval_mode === "direct"
                  ? "Accountants with access apply changes directly. Every change is still audited."
                  : "Accountant changes wait for your approval before they affect new invoices."}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant={data.approval_mode === "direct" ? "primary" : "outline"}
                loading={busy}
                onClick={() => void changeApprovalMode("direct")}
              >
                Direct changes
              </Button>
              <Button
                size="sm"
                variant={data.approval_mode === "owner_approval" ? "primary" : "outline"}
                loading={busy}
                onClick={() => void changeApprovalMode("owner_approval")}
              >
                Owner approval
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      {data && data.pending_changes.length > 0 && (
        <Card>
          <CardHeader
            title="Pending GST changes"
            description="Proposed by an accountant and not yet in effect"
            icon={Clock}
          />
          <CardBody className="space-y-2 pt-3">
            {data.pending_changes.map((change) => (
              <div
                key={change.id}
                className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50/60 p-3"
              >
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold text-ink-900">
                    {change.product_name} <span className="text-slate-400">· {change.sku}</span>
                  </p>
                  <p className="mt-0.5 text-[11.5px] text-slate-600">
                    {rateLabel(change.old_gst_rate)} → {rateLabel(change.new_gst_rate)}
                    {change.new_hsn_sac ? ` · HSN/SAC ${change.new_hsn_sac}` : ""}
                    {change.effective_from ? ` · from ${formatDate(change.effective_from)}` : ""}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {change.reason} · {change.requested_by?.name ?? "Accountant"} ·{" "}
                    {formatDateTime(change.created_at)}
                  </p>
                </div>
                {canDecide && (
                  <div className="flex gap-1.5">
                    <Button
                      size="sm"
                      icon={Check}
                      onClick={() => {
                        setDeciding({ change, approve: true });
                        setDecisionNote("");
                      }}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      icon={X}
                      onClick={() => {
                        setDeciding({ change, approve: false });
                        setDecisionNote("");
                      }}
                    >
                      Reject
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="GST catalogue"
          description="Rate and HSN/SAC used when new invoice lines are added"
          icon={Percent}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search item, SKU or HSN"
                  aria-label="Search GST catalogue"
                  className="w-56 pl-8"
                />
              </div>
              {exportPath && editable && (
                <Button size="sm" variant="outline" icon={Download} onClick={() => void download()}>
                  Export Excel
                </Button>
              )}
            </div>
          }
        />
        <CardBody className="pt-3">
          {catalogue.loading && !data ? (
            <p className="py-8 text-center text-sm text-slate-500">Loading GST catalogue…</p>
          ) : catalogue.error && !data ? (
            <ErrorState message={catalogue.error} onRetry={catalogue.reload} />
          ) : data && data.items.length === 0 ? (
            <EmptyState
              title="No catalogue items"
              description="Add products or services in GST & Billing, then set their GST rate here."
            />
          ) : data ? (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Item</TH>
                  <TH>HSN / SAC</TH>
                  <TH>Type</TH>
                  <TH className="text-right">GST</TH>
                  <TH>Effective from</TH>
                  <TH>Updated</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {data.items.map((item) => (
                  <TR key={item.id}>
                    <TD>
                      <p className="font-semibold text-ink-900">{item.name}</p>
                      <p className="text-[10.5px] text-slate-400">{item.sku}</p>
                    </TD>
                    <TD>{item.hsn_sac || "—"}</TD>
                    <TD className="capitalize">{item.item_type === "service" ? "services" : item.item_type}</TD>
                    <TD className="text-right font-semibold tabular">{rateLabel(item.gst_rate)}</TD>
                    <TD className="whitespace-nowrap">
                      {item.gst_effective_from ? formatDate(item.gst_effective_from) : "—"}
                    </TD>
                    <TD>
                      <p className="text-[11px] text-slate-600">{item.gst_updated_by?.name ?? "—"}</p>
                      <p className="text-[10px] text-slate-400">{formatDateTime(item.gst_updated_at)}</p>
                      {item.gst_change_reason && (
                        <p className="max-w-[220px] truncate text-[10px] text-slate-400" title={item.gst_change_reason}>
                          {item.gst_change_reason}
                        </p>
                      )}
                    </TD>
                    <TD>
                      <div className="flex flex-col items-start gap-1">
                        <Badge tone={item.gst_verified ? "green" : "amber"}>
                          {item.gst_verified ? "HSN verified" : "HSN unverified"}
                        </Badge>
                        {item.pending_change && <Badge tone="amber">change pending</Badge>}
                      </div>
                    </TD>
                    <TD>
                      <div className="flex justify-end">
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={`Edit GST for ${item.name}`}
                          disabled={!editable}
                          onClick={() => openEdit(item)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          ) : null}
          {data && <p className="mt-4 text-[11px] leading-relaxed text-slate-400">{data.note}</p>}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Change history"
          description="Immutable record of every GST catalogue change"
          icon={History}
        />
        <CardBody className="pt-3">
          {history.loading && !history.data ? (
            <p className="py-6 text-center text-sm text-slate-500">Loading history…</p>
          ) : history.data && history.data.items.length === 0 ? (
            <p className="py-4 text-center text-[12px] text-slate-500">
              No GST catalogue changes recorded yet.
            </p>
          ) : history.data ? (
            <div className="space-y-2">
              {history.data.items.map((change) => (
                <div
                  key={change.id}
                  className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="text-[12px] font-semibold text-ink-900">
                      {change.product_name} <span className="text-slate-400">· {change.sku}</span>
                    </p>
                    <p className="text-[11px] text-slate-600">
                      {rateLabel(change.old_gst_rate)} → {rateLabel(change.new_gst_rate)}
                      {change.old_hsn_sac !== change.new_hsn_sac
                        ? ` · HSN/SAC ${change.old_hsn_sac || "—"} → ${change.new_hsn_sac || "—"}`
                        : ""}
                      {change.effective_from ? ` · effective ${formatDate(change.effective_from)}` : ""}
                    </p>
                    <p className="mt-0.5 text-[10.5px] text-slate-400">
                      {change.requested_by?.name ?? "—"} ({change.requested_by_role}) ·{" "}
                      {formatDateTime(change.created_at)} · {change.reason}
                      {change.decision_note ? ` · ${change.decision_note}` : ""}
                    </p>
                  </div>
                  <Badge tone={changeStatusTone(change.status)}>{statusLabel(change.status)}</Badge>
                </div>
              ))}
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Modal
        open={editing !== null}
        onClose={closeEdit}
        title={editing ? `GST settings · ${editing.name}` : "GST settings"}
        description="The new rate applies to invoice lines dated on or after the effective date. Issued invoices are never recalculated."
        footer={
          <>
            <Button variant="ghost" onClick={closeEdit} disabled={busy}>
              Cancel
            </Button>
            <Button icon={Pencil} loading={busy} onClick={() => void submitEdit()}>
              {role === "owner" ? "Save change" : "Propose change"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="GST rate %" required>
              <Input
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={form.gst_rate}
                onChange={(event) => setForm({ ...form, gst_rate: event.target.value })}
              />
            </Field>
            <Field label="HSN / SAC" hint="Goods use HSN, services use SAC">
              <Input
                value={form.hsn_sac}
                maxLength={12}
                onChange={(event) => setForm({ ...form, hsn_sac: event.target.value })}
              />
            </Field>
            <Field label="Type">
              <Select
                value={form.item_type}
                onChange={(event) => setForm({ ...form, item_type: event.target.value })}
              >
                <option value="goods">Goods</option>
                <option value="services">Services</option>
              </Select>
            </Field>
          </div>
          <Field label="Effective from" hint="Leave blank to apply from today">
            <Input
              type="date"
              value={form.effective_from}
              onChange={(event) => setForm({ ...form, effective_from: event.target.value })}
            />
          </Field>
          <Checkbox
            checked={form.hsn_verified}
            onChange={(checked) => setForm({ ...form, hsn_verified: checked })}
            label="I have verified this HSN/SAC and rate against the GST notification"
          />
          <Field label="Reason for change" required hint="Stored in the audit trail with old and new values">
            <Textarea
              rows={3}
              value={form.reason}
              maxLength={500}
              onChange={(event) => setForm({ ...form, reason: event.target.value })}
              placeholder="e.g. Rate correction after GST Council notification 12/2026"
            />
          </Field>
          {formError && (
            <Callout tone="red" title="Could not save the change">
              {formError}
            </Callout>
          )}
        </div>
      </Modal>

      <Modal
        open={deciding !== null}
        onClose={() => {
          if (!busy) setDeciding(null);
        }}
        title={deciding?.approve ? "Approve GST change" : "Reject GST change"}
        description={
          deciding
            ? `${deciding.change.product_name}: ${rateLabel(deciding.change.old_gst_rate)} → ${rateLabel(
                deciding.change.new_gst_rate,
              )}`
            : undefined
        }
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeciding(null)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant={deciding?.approve ? "primary" : "danger"}
              loading={busy}
              onClick={() => void submitDecision()}
            >
              {deciding?.approve ? "Approve change" : "Reject change"}
            </Button>
          </>
        }
      >
        <Field label="Note" hint="Optional context stored with the decision">
          <Textarea
            rows={3}
            value={decisionNote}
            maxLength={500}
            onChange={(event) => setDecisionNote(event.target.value)}
          />
        </Field>
      </Modal>
    </div>
  );
}
