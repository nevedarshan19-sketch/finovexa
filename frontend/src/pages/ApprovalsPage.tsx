import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  Hash,
  LineChart,
  Mail,
  RefreshCw,
  ShieldCheck,
  ShieldX,
  Waves,
  XCircle,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, post } from "../lib/api";
import type { Approval, Evidence } from "../lib/types";
import { countdown, formatDateTime, moneyExact, number, timeAgo, titleCase } from "../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  HashChip,
  Modal,
  PageHeader,
  PageSkeleton,
  StatCard,
  Tabs,
  Textarea,
} from "../components/ui";
import { RiskBadge, StatusBadge } from "../components/DataMode";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";

interface ApprovalsResponse {
  items: Approval[];
  pending_count: number;
  note: string;
}

type StatusTab = "pending" | "executed" | "rejected" | "expired" | "failed" | "all";

const STATUS_TABS: { key: StatusTab; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "executed", label: "Executed" },
  { key: "rejected", label: "Rejected" },
  { key: "expired", label: "Expired" },
  { key: "failed", label: "Failed" },
  { key: "all", label: "All" },
];

const ACTION_META: Record<
  string,
  { label: string; icon: typeof Mail; approveLabel: string; note: string }
> = {
  "reminder.send": {
    label: "Payment reminder",
    icon: Mail,
    approveLabel: "Approve reminder dispatch",
    note: "Approval records a simulated email dispatch. No external email is sent in this build.",
  },
  "investment.order": {
    label: "Investment order",
    icon: LineChart,
    approveLabel: "Approve order",
    note: "Approval creates a broker order bound to this exact payload. Simulated unless this request explicitly says live.",
  },
  "cashflow.intervention": {
    label: "Cash-flow advisory",
    icon: Waves,
    approveLabel: "Acknowledge recommendation",
    note: "This acknowledgement changes no ledger balances and executes no external action.",
  },
};

const MONEY_KEY = /(amount|value|price|impact|balance|reserve|limit)/i;

function formatPayloadValue(key: string, value: unknown, currency: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    return MONEY_KEY.test(key) ? moneyExact(value, currency) : number(value);
  }
  const text = String(value);
  const numeric = Number(text);
  if (MONEY_KEY.test(key) && Number.isFinite(numeric) && text.trim() !== "") {
    return moneyExact(numeric, currency);
  }
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return formatDateTime(text);
  return text;
}

function EvidenceChips({ evidence, currency }: { evidence: Evidence[]; currency: string }) {
  if (!evidence.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {evidence.map((item, index) => (
        <span
          key={`${item.type}-${item.id}-${index}`}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] text-slate-600"
        >
          <span className="font-medium">{item.label}</span>
          {item.amount !== null && item.amount !== undefined && (
            <span className="font-mono text-slate-500">
              {formatPayloadValue("amount", item.amount, currency)}
            </span>
          )}
          {item.data_mode && <Badge tone="slate">{item.data_mode}</Badge>}
        </span>
      ))}
    </div>
  );
}

function PayloadGrid({ payload, currency }: { payload: Record<string, unknown>; currency: string }) {
  const entries = Object.entries(payload).filter(
    ([key]) => key !== "body" && key !== "recommendation",
  );
  return (
    <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0 rounded-lg border border-slate-100 bg-slate-50/60 px-2.5 py-1.5">
          <p className="text-[10px] uppercase tracking-wide text-slate-400">{titleCase(key)}</p>
          <p className="truncate text-[12px] font-medium text-slate-700" title={String(value ?? "—")}>
            {formatPayloadValue(key, value, currency)}
          </p>
        </div>
      ))}
    </div>
  );
}

function ResultBlock({ result, currency }: { result: Record<string, unknown>; currency: string }) {
  const note = typeof result.note === "string" ? result.note : null;
  const rest = Object.entries(result).filter(([key]) => key !== "note");
  return (
    <div className="space-y-2">
      {note && <Callout tone="green">{note}</Callout>}
      <div className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
        {rest.map(([key, value]) => (
          <div key={key} className="flex items-baseline justify-between gap-2 border-b border-slate-100 py-1 text-[11.5px]">
            <span className="text-slate-400">{titleCase(key)}</span>
            <span className="truncate font-medium text-slate-700">
              {formatPayloadValue(key, value, currency)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function isLiveApproval(approval: Approval): boolean {
  return approval.action_type === "investment.order" && approval.payload.execution_mode === "live";
}

function ApprovalCard({
  approval,
  currency,
  onOpen,
}: {
  approval: Approval;
  currency: string;
  onOpen: () => void;
}) {
  const meta = ACTION_META[approval.action_type] || {
    label: titleCase(approval.action_type),
    icon: ShieldCheck,
    approveLabel: "Review",
    note: "",
  };
  const Icon = meta.icon;
  const pending = approval.status === "pending";
  const live = isLiveApproval(approval);
  return (
    <Card hover className="overflow-hidden">
      <div className="flex flex-col gap-3 p-5 sm:flex-row sm:items-start">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={live ? "red" : "blue"}>{live ? "Live investment order" : meta.label}</Badge>
            {live && <Badge tone="red">Upstox · real money</Badge>}
            <StatusBadge status={approval.status} />
            <RiskBadge risk={approval.risk_level} />
            {pending && (
              <span className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-400">
                <Clock3 className="h-3 w-3" aria-hidden /> {countdown(approval.expires_at)}
              </span>
            )}
          </div>
          <h3 className="mt-2 text-[14px] font-semibold tracking-tight text-ink-900">{approval.title}</h3>
          <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-slate-500">{approval.reason}</p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {approval.financial_impact !== null && (
              <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
                {moneyExact(approval.financial_impact, currency)} at stake
              </span>
            )}
            <span className="text-[10px] text-slate-400">
              Requested {timeAgo(approval.created_at)} · Approval #{approval.id}
            </span>
          </div>
        </div>
        <Button
          variant={pending ? "primary" : "outline"}
          size="sm"
          onClick={onOpen}
          iconRight={ArrowRight}
          className="shrink-0 self-start"
        >
          {pending ? "Review & decide" : "View details"}
        </Button>
      </div>
      {pending && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 bg-slate-50/50 px-5 py-2.5 text-[10px] text-slate-400">
          <Hash className="h-3 w-3" aria-hidden />
          <span className="font-mono">{approval.payload_hash.slice(0, 16)}…</span>
          <span>· Exact payload bound by SHA-256 · Expires {formatDateTime(approval.expires_at)}</span>
        </div>
      )}
    </Card>
  );
}

function ReviewModal({
  approvalId,
  initial,
  onClose,
  onChanged,
}: {
  approvalId: number;
  initial: Approval;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { profile } = useAuth();
  const { toast } = useToast();
  const detail = useApi<Approval>(`/approvals/${approvalId}`);
  const approval = detail.data || initial;
  const [acknowledged, setAcknowledged] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [busy, setBusy] = useState<
    "approve" | "reject" | "fill" | "cancel" | "sync" | null
  >(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [orderConfirm, setOrderConfirm] = useState<"fill" | "cancel" | null>(null);
  const [liveConfirm, setLiveConfirm] = useState<"sync" | "cancel" | null>(null);
  const currency = profile?.currency || "INR";
  const meta = ACTION_META[approval.action_type];
  const pending = approval.status === "pending" && approval.can_decide;
  const order = approval.order;
  const live = isLiveApproval(approval);
  const orderIsLive = Boolean(order && !order.simulated);

  const refreshAll = () => {
    detail.reload();
    onChanged();
    window.dispatchEvent(new Event("finovexa:approvals-changed"));
  };

  const approve = async () => {
    setBusy("approve");
    setActionError(null);
    try {
      await post<Approval>(`/approvals/${approval.id}/approve`, {
        confirm: true,
        payload_hash: approval.payload_hash,
      });
      toast({
        tone: "success",
        title: live ? "Live order sent to Upstox" : "Approval executed",
        description: live
          ? "The order was submitted to Upstox with a unique tag. Refresh its status to confirm the broker state."
          : meta?.note || "The approved action was executed with duplicate protection.",
      });
      refreshAll();
    } catch (err) {
      setActionError(getErrorMessage(err));
      detail.reload();
      onChanged();
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    setBusy("reject");
    setActionError(null);
    try {
      await post<Approval>(`/approvals/${approval.id}/reject`, {
        reason: rejectReason.trim() || "Rejected by owner from the Approval Center.",
      });
      toast({ tone: "info", title: "Approval rejected", description: "No action was executed." });
      setRejecting(false);
      refreshAll();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const actOnOrder = async (kind: "fill" | "cancel") => {
    if (!order) return;
    setBusy(kind);
    setActionError(null);
    try {
      await post(`/orders/${order.id}/simulate-${kind}`, { confirm: true });
      toast({
        tone: "success",
        title: kind === "fill" ? "Simulated fill recorded" : "Simulation cancelled the order",
        description:
          kind === "fill"
            ? "Local simulator only — no exchange execution and no money moved."
            : "No live broker order exists.",
      });
      setOrderConfirm(null);
      refreshAll();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const actOnLiveOrder = async (kind: "sync" | "cancel") => {
    if (!order) return;
    setBusy(kind);
    setActionError(null);
    try {
      const result = await post<{ order: unknown; message: string }>(
        kind === "sync" ? `/orders/${order.id}/sync` : `/orders/${order.id}/cancel-request`,
        kind === "sync" ? undefined : { confirm: true },
      );
      toast({
        tone: "success",
        title: kind === "sync" ? "Status refreshed from Upstox" : "Cancellation sent to Upstox",
        description:
          result?.message ||
          (kind === "sync"
            ? "The latest broker status is shown below."
            : "The order may already be filled; refresh the status to confirm."),
      });
      setLiveConfirm(null);
      refreshAll();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Modal
        open
        onClose={onClose}
        title={approval.title}
        description={`Approval #${approval.id} · ${
          live ? "Live investment order" : meta?.label || titleCase(approval.action_type)
        }`}
        size="lg"
        footer={
          pending ? (
            <>
              <Button variant="outline" onClick={onClose} disabled={busy !== null}>
                Close
              </Button>
              <Button
                variant="ghost"
                onClick={() => setRejecting((value) => !value)}
                disabled={busy !== null}
                icon={ShieldX}
                className="text-rose-600 hover:bg-rose-50 hover:text-rose-700"
              >
                Reject
              </Button>
              <Button
                onClick={() => void approve()}
                loading={busy === "approve"}
                disabled={!acknowledged || busy !== null}
                icon={ClipboardCheck}
                variant={live ? "danger" : "primary"}
              >
                {live ? "Approve live order — send to Upstox" : meta?.approveLabel || "Approve"}
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
          )
        }
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={approval.status} />
            <RiskBadge risk={approval.risk_level} />
            {pending && (
              <Badge tone="amber" dot>
                {countdown(approval.expires_at)}
              </Badge>
            )}
            {!pending && approval.decided_at && (
              <span className="text-[11px] text-slate-400">
                Decided {formatDateTime(approval.decided_at)}
              </span>
            )}
          </div>

          <p className="text-[13px] leading-relaxed text-slate-600">{approval.reason}</p>

          {live ? (
            <Callout tone="red" title="Live order — real money moves">
              Approving this request places a <strong>real order on Upstox</strong> using your broker
              account. Nothing is simulated. The order is sent only after your explicit approval, is
              tagged for traceability, and must originate from a registered static IP. Check the
              instrument, side, quantity and price above before you approve.
            </Callout>
          ) : (
            meta?.note && (
              <Callout tone={approval.action_type === "cashflow.intervention" ? "blue" : "amber"}>
                {meta.note}
              </Callout>
            )
          )}

          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <Hash className="h-3.5 w-3.5 text-slate-400" aria-hidden />
            <span className="text-[11px] font-medium text-slate-500">Canonical payload hash</span>
            <HashChip hash={approval.payload_hash} />
            <CopyButton value={approval.payload_hash} label="Copy hash" />
          </div>

          {approval.financial_impact !== null && (
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-brand-500">Financial impact</p>
              <p className="text-lg font-semibold tracking-tight text-brand-900">
                {moneyExact(approval.financial_impact, currency)}
              </p>
            </div>
          )}

          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Exact action payload
            </h4>
            <PayloadGrid payload={approval.payload} currency={currency} />
            {typeof approval.payload.body === "string" && (
              <div className="mt-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Reminder body</p>
                <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-600">
                  {approval.payload.body}
                </p>
              </div>
            )}
            {typeof approval.payload.recommendation === "string" && (
              <div className="mt-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Recommendation</p>
                <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-600">
                  {approval.payload.recommendation}
                </p>
              </div>
            )}
            <details className="mt-2">
              <summary className="cursor-pointer text-[11px] font-medium text-slate-400 hover:text-slate-600">
                View raw JSON payload
              </summary>
              <pre className="mt-1.5 max-h-48 overflow-auto rounded-lg bg-navy-950 p-3 text-[10.5px] leading-relaxed text-slate-300">
                {JSON.stringify(approval.payload, null, 2)}
              </pre>
            </details>
          </div>

          {approval.evidence.length > 0 && (
            <div>
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Evidence
              </h4>
              <EvidenceChips evidence={approval.evidence} currency={currency} />
            </div>
          )}

          {approval.result && (
            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {approval.status === "executed" ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-hidden />
                ) : (
                  <XCircle className="h-3.5 w-3.5 text-rose-500" aria-hidden />
                )}
                Execution result
              </h4>
              <ResultBlock result={approval.result} currency={currency} />
            </div>
          )}

          {order && (
            <div
              className={`rounded-lg border p-3 ${
                orderIsLive
                  ? "border-rose-200 bg-rose-50/40"
                  : "border-violet-200 bg-violet-50/40"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p
                    className={`flex items-center gap-1.5 text-[12px] font-semibold ${
                      orderIsLive ? "text-rose-900" : "text-violet-900"
                    }`}
                  >
                    <LineChart className="h-3.5 w-3.5" aria-hidden />
                    {orderIsLive ? "Live Upstox order" : "Simulated broker order"} #{order.id}
                  </p>
                  <p
                    className={`mt-0.5 font-mono text-[10px] ${
                      orderIsLive ? "text-rose-700" : "text-violet-700"
                    }`}
                  >
                    {order.broker_order_id || `ORDER-${order.id}`} · {order.symbol} · {order.side} ·{" "}
                    {number(order.quantity)} × {order.order_type}
                    {order.lot_size > 1 ? ` · lot ${order.lot_size}` : ""}
                  </p>
                  {orderIsLive && (order.broker_status || order.broker_status_message) && (
                    <p className="mt-1 text-[10.5px] text-rose-700">
                      Broker status: {order.broker_status || "unknown"}
                      {order.broker_status_message ? ` · ${order.broker_status_message}` : ""}
                      {order.last_synced_at ? ` · synced ${timeAgo(order.last_synced_at)}` : ""}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  <StatusBadge status={order.status} />
                  <Badge tone={orderIsLive ? "red" : "violet"}>
                    {orderIsLive ? "LIVE" : "SIMULATED"}
                  </Badge>
                </div>
              </div>
              {orderIsLive ? (
                <div className="mt-2.5 flex flex-wrap gap-2 border-t border-rose-200/70 pt-2.5">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setLiveConfirm("sync")}
                    loading={busy === "sync"}
                    icon={RefreshCw}
                  >
                    Refresh broker status
                  </Button>
                  {["live_submitted", "live_open", "live_partially_filled"].includes(
                    order.status,
                  ) && (
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => setLiveConfirm("cancel")}
                      loading={busy === "cancel"}
                    >
                      Request Upstox cancellation
                    </Button>
                  )}
                </div>
              ) : (
                (order.status === "simulated_pending" || order.status === "cancel_requested") && (
                  <div className="mt-2.5 flex flex-wrap gap-2 border-t border-violet-200/70 pt-2.5">
                    <Button
                      size="sm"
                      variant="success"
                      onClick={() => setOrderConfirm("fill")}
                      loading={busy === "fill"}
                      disabled={order.status !== "simulated_pending"}
                    >
                      Record simulated fill
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setOrderConfirm("cancel")}
                      loading={busy === "cancel"}
                    >
                      Cancel in simulator
                    </Button>
                  </div>
                )
              )}
            </div>
          )}

          {pending && (
            <div className="space-y-3 rounded-lg border border-slate-200 p-3">
              <Checkbox
                checked={acknowledged}
                onChange={setAcknowledged}
                label={
                  <span>
                    I reviewed the exact payload above and understand this approval is bound to hash{" "}
                    <span className="font-mono text-[11px]">{approval.payload_hash.slice(0, 12)}…</span>.
                    Reusing or altering the details will be rejected.
                  </span>
                }
              />
              <p className="flex items-start gap-1.5 text-[10.5px] leading-relaxed text-slate-400">
                <CalendarClock className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                This request expires {formatDateTime(approval.expires_at)}. After expiry, an identical new
                request must be created. Execution is one-shot and duplicate protected.
              </p>
            </div>
          )}

          {rejecting && pending && (
            <div className="space-y-2 rounded-lg border border-rose-200 bg-rose-50/40 p-3">
              <Field label="Reason for rejection" htmlFor="reject-reason" hint="Recorded in the audit trail.">
                <Textarea
                  id="reject-reason"
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  maxLength={500}
                  className="min-h-[70px] bg-white"
                  placeholder="e.g. Customer already paid by bank transfer; verify reconciliation."
                />
              </Field>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setRejecting(false)}>
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => void reject()}
                  loading={busy === "reject"}
                  icon={ShieldX}
                >
                  Confirm rejection
                </Button>
              </div>
            </div>
          )}

          {actionError && (
            <Callout tone="red" title="Action not completed" icon={AlertTriangle}>
              {actionError}
            </Callout>
          )}
        </div>
      </Modal>

      <ConfirmDialog
        open={orderConfirm !== null}
        onClose={() => setOrderConfirm(null)}
        onConfirm={() => orderConfirm && void actOnOrder(orderConfirm)}
        title={orderConfirm === "fill" ? "Record a simulated fill?" : "Cancel the simulated order?"}
        description={
          orderConfirm === "fill"
            ? "This marks the local simulated order as filled. No live exchange order is sent and no money moves."
            : "This cancels the local simulated order. No live broker cancellation is sent."
        }
        confirmLabel={orderConfirm === "fill" ? "Record simulated fill" : "Cancel simulated order"}
        tone={orderConfirm === "fill" ? "success" : "danger"}
        loading={busy === "fill" || busy === "cancel"}
      />

      <ConfirmDialog
        open={liveConfirm !== null}
        onClose={() => setLiveConfirm(null)}
        onConfirm={() => liveConfirm && void actOnLiveOrder(liveConfirm)}
        title={
          liveConfirm === "sync"
            ? "Refresh status from Upstox?"
            : "Request cancellation on Upstox?"
        }
        description={
          liveConfirm === "sync"
            ? "Fetches the latest broker state for this order. No new order is placed."
            : "This sends a real cancellation request to Upstox. If the order is already filled, cancellation will fail; refresh the status to confirm."
        }
        confirmLabel={liveConfirm === "sync" ? "Refresh status" : "Send cancellation"}
        tone={liveConfirm === "cancel" ? "danger" : "default"}
        loading={busy === "sync" || busy === "cancel"}
      >
        {order && (
          <p className="text-xs leading-relaxed text-slate-600">
            Live order <strong>#{order.id}</strong> · {order.broker_order_id || "no Upstox id"} ·{" "}
            {order.symbol} · {order.side} · {number(order.quantity)} × {order.order_type}.
          </p>
        )}
      </ConfirmDialog>
    </>
  );
}

export function ApprovalsPage() {
  const { profile } = useAuth();
  const { toast } = useToast();
  const approvals = useApi<ApprovalsResponse>("/approvals?status=all&limit=100");
  const [tab, setTab] = useState<StatusTab>("pending");
  const [selected, setSelected] = useState<Approval | null>(null);
  const currency = profile?.currency || "INR";

  const items = approvals.data?.items || [];
  const counts = useMemo(() => {
    const result: Record<string, number> = { all: items.length };
    for (const item of items) result[item.status] = (result[item.status] || 0) + 1;
    return result;
  }, [items]);

  const visible = tab === "all" ? items : items.filter((item) => item.status === tab);
  const pending = items.filter((item) => item.status === "pending");
  const expiringSoon = pending.filter(
    (item) => new Date(item.expires_at).getTime() - Date.now() < 2 * 60 * 60 * 1000,
  ).length;
  const executed = counts.executed || 0;
  const rejected = counts.rejected || 0;
  const failed = counts.failed || 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Governance"
        title="Approval Center"
        description="Every consequential action waits here for an explicit human decision, bound to the exact payload hash and a hard expiry."
        actions={
          <Button
            variant="outline"
            size="sm"
            icon={RefreshCw}
            onClick={() => approvals.reload()}
            loading={approvals.loading}
          >
            Refresh queue
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Awaiting your decision"
          value={number(pending.length)}
          icon={ShieldCheck}
          tone="amber"
          sub={pending.length ? "No action executes without you" : "Queue is clear"}
        />
        <StatCard
          label="Expiring within 2 hours"
          value={number(expiringSoon)}
          icon={Clock3}
          tone={expiringSoon > 0 ? "red" : "slate"}
          sub="Expired requests are rejected automatically"
        />
        <StatCard
          label="Executed approvals"
          value={number(executed)}
          icon={CheckCircle2}
          tone="green"
          sub="One-shot, duplicate protected"
        />
        <StatCard
          label="Rejected / failed"
          value={number(rejected + failed)}
          icon={ShieldX}
          tone="slate"
          sub="Recorded with reasons in the audit log"
        />
      </div>

      <Callout tone="blue" title="Exact-order protection" icon={ShieldCheck}>
        Each request carries a canonical SHA-256 hash of its action and payload. Approving sends that hash back;
        the backend rejects modified details, expired requests and duplicate executions. Reminders are simulated
        dispatches. Investment orders stay in the local simulator unless the request is explicitly marked live,
        in which case approval places a real Upstox order.
      </Callout>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          items={STATUS_TABS.map((item) => ({ ...item, count: counts[item.key] || 0 }))}
          value={tab}
          onChange={setTab}
        />
        <p className="text-[10px] text-slate-400">{approvals.data?.note}</p>
      </div>

      {approvals.loading && !approvals.data ? (
        <PageSkeleton cards={3} />
      ) : approvals.error ? (
        <ErrorState message={approvals.error} onRetry={approvals.reload} />
      ) : visible.length === 0 ? (
        <Card>
          <EmptyState
            icon={tab === "pending" ? CheckCircle2 : ShieldCheck}
            title={
              tab === "pending"
                ? "No approvals are waiting"
                : `No ${tab === "all" ? "" : tab} approvals`
            }
            description={
              tab === "pending"
                ? "When FINOVEXA wants to send a reminder, place an order or record an advisory decision, it will appear here for your review."
                : "Approvals will appear here once they reach this state."
            }
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {visible.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              currency={currency}
              onOpen={() => setSelected(approval)}
            />
          ))}
        </div>
      )}

      <Card>
        <CardHeader title="How approvals work" icon={ShieldCheck} />
        <CardBody className="grid gap-4 pt-3 sm:grid-cols-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">1 · Review</p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-600">
              Inspect the evidence, financial impact and exact payload. Reminder bodies are editable before
              the approval is created.
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">2 · Decide</p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-600">
              Approve the exact hash or reject with a reason. Investment approvals expire after 30 minutes;
              reminders after 24 hours.
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">3 · Audit</p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-600">
              Creation, decision, execution and failures are all written to the activity log. Order values are
              re-checked against your reserve before submission.
            </p>
          </div>
        </CardBody>
      </Card>

      {selected && (
        <ReviewModal
          approvalId={selected.id}
          initial={selected}
          onClose={() => setSelected(null)}
          onChanged={() => {
            approvals.reload();
          }}
        />
      )}
    </div>
  );
}
