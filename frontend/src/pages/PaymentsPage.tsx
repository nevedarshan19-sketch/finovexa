import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Clock3,
  CreditCard,
  ExternalLink,
  Globe2,
  Info,
  Landmark,
  ListChecks,
  Lock,
  ReceiptText,
  RefreshCw,
  Search,
  ShieldCheck,
  ShieldAlert,
  Undo2,
  Wallet,
  Webhook,
  XCircle,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, post } from "../lib/api";
import type {
  Invoice,
  Payment,
  PaymentOverview,
  PayPalCaptureResponse,
  PayPalEventRecord,
  PayPalOrderRecord,
  PayPalOrderResponse,
  PayPalRefundRecord,
  PayPalRefundResponse,
} from "../lib/types";
import { formatDate, formatDateTime, moneyExact, number, titleCase } from "../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  CardFooter,
  Checkbox,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  Select,
  StatCard,
  TableWrap,
  Tabs,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui";
import { DataModeBadge, StatusBadge } from "../components/DataMode";
import { PayPalFlowChart } from "../components/Charts";
import { PageLink } from "../components/layout/AppShell";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

type PaymentTab = "all" | "confirmed" | "pending" | "failed";
type RangeKey = "today" | "7d" | "30d" | "90d" | "custom";

const RANGE_OPTIONS: { key: RangeKey; label: string; days?: number }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 days", days: 7 },
  { key: "30d", label: "30 days", days: 30 },
  { key: "90d", label: "90 days", days: 90 },
  { key: "custom", label: "Custom" },
];

const OPEN_ORDER_STATUSES = new Set([
  "CREATED",
  "SAVED",
  "APPROVED",
  "PAYER_ACTION_REQUIRED",
  "PENDING",
]);

function reconciliationTone(status?: string): "green" | "amber" | "red" | "slate" {
  if (status === "matched") return "green";
  if (status === "mismatch") return "red";
  if (status === "unmatched") return "amber";
  return "slate";
}

function InvoiceRow({
  invoice,
  currency,
  configured,
  onOpen,
}: {
  invoice: Invoice;
  currency: string;
  configured: boolean;
  onOpen: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 border-b border-slate-100 px-5 py-3 last:border-0 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12px] font-semibold text-ink-900">{invoice.number}</span>
          <StatusBadge status={invoice.status} />
          {invoice.created_by && (
            <Badge tone={invoice.created_by.role === "employee" ? "amber" : "slate"}>
              {invoice.created_by.role === "employee"
                ? `Employee: ${invoice.created_by.name}`
                : `Owner: ${invoice.created_by.name}`}
            </Badge>
          )}
          {invoice.aging_days > 0 && invoice.status !== "paid" && (
            <span className="text-[10px] text-slate-400">{invoice.aging_days} days aged</span>
          )}
        </div>
        <p className="mt-0.5 truncate text-[12px] text-slate-600">
          {invoice.customer.name}
          {invoice.customer.company ? ` · ${invoice.customer.company}` : ""}
        </p>
        <p className="text-[10px] text-slate-400">
          Due {formatDate(invoice.due_date)} · {invoice.customer.email}
        </p>
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <div className="text-right">
          <p className="text-[13px] font-semibold text-ink-900">
            {moneyExact(invoice.outstanding, invoice.currency || currency)}
          </p>
          <p className="text-[10px] text-slate-400">outstanding</p>
        </div>
        <Button
          variant={configured ? "primary" : "outline"}
          size="sm"
          icon={configured ? CreditCard : Wallet}
          onClick={onOpen}
        >
          {configured ? "PayPal checkout" : "Simulate payment"}
        </Button>
      </div>
    </div>
  );
}

export function CheckoutModal({
  invoice,
  provider,
  currency,
  onClose,
  onDone,
}: {
  invoice: Invoice;
  provider: PaymentOverview["provider"];
  currency: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [acknowledged, setAcknowledged] = useState(false);
  const [order, setOrder] = useState<PayPalOrderResponse | null>(null);
  const [result, setResult] = useState<PayPalCaptureResponse | null>(null);
  const [busy, setBusy] = useState<"create" | "simulate" | "capture" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const configured = provider.configured;

  const createOrder = async () => {
    setBusy("create");
    setError(null);
    try {
      const created = await post<PayPalOrderResponse>("/paypal/orders", { invoice_id: invoice.id });
      setOrder(created);
      toast({
        tone: "info",
        title: "Checkout order created",
        description:
          created.mode === "simulated"
            ? "No PayPal API was called. Use the labelled simulation instead."
            : "Open the approval link, complete the sandbox checkout, then return to verify capture.",
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const simulate = async () => {
    setBusy("simulate");
    setError(null);
    try {
      const response = await post<PayPalCaptureResponse>("/paypal/simulate", {
        invoice_id: invoice.id,
      });
      setResult(response);
      toast({
        tone: "success",
        title: "Simulated PayPal payment recorded",
        description: "Labelled demo only — no PayPal API was called and no real money moved.",
      });
      onDone();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const capture = async () => {
    if (!order?.id) return;
    setBusy("capture");
    setError(null);
    try {
      const response = await post<PayPalCaptureResponse>(`/paypal/orders/${order.id}/capture`);
      setResult(response);
      toast({
        tone: response.mismatch ? "info" : "success",
        title: response.mismatch ? "Captured but needs reconciliation" : "Verified capture recorded",
        description: response.message,
      });
      onDone();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const cancelOrder = async () => {
    if (!order?.id) return;
    setBusy("cancel");
    setError(null);
    try {
      const response = await post<{ message: string; order: PayPalOrderResponse }>(
        `/paypal/orders/${order.id}/cancel`,
      );
      setOrder(response.order);
      toast({ tone: "info", title: "Checkout cancelled", description: response.message });
      onDone();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={configured ? "PayPal sandbox checkout" : "Simulated PayPal payment"}
      description={`${invoice.number} · ${invoice.customer.name} · ${moneyExact(
        invoice.outstanding,
        invoice.currency || currency,
      )} outstanding`}
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy !== null}>
            {result ? "Done" : "Cancel"}
          </Button>
          {!configured && !result && (
            <Button
              onClick={() => void simulate()}
              loading={busy === "simulate"}
              disabled={!acknowledged || busy !== null}
              icon={Wallet}
            >
              Record simulated payment
            </Button>
          )}
          {configured && !result && !order && (
            <Button onClick={() => void createOrder()} loading={busy === "create"} icon={CreditCard}>
              Create PayPal order
            </Button>
          )}
          {configured && order?.id && !result && (
            <>
              {OPEN_ORDER_STATUSES.has(order.status) && (
                <Button
                  variant="ghost"
                  onClick={() => void cancelOrder()}
                  loading={busy === "cancel"}
                  disabled={busy !== null}
                >
                  Cancel checkout
                </Button>
              )}
              <Button
                onClick={() => void capture()}
                loading={busy === "capture"}
                disabled={!acknowledged || busy !== null}
                icon={ShieldCheck}
              >
                Verify &amp; capture
              </Button>
            </>
          )}
        </>
      }
    >
      <div className="space-y-4">
        {!configured ? (
          <Callout tone="amber" title="Simulation only — this is not PayPal" icon={AlertTriangle}>
            PayPal credentials are not configured. This action writes a clearly labelled demo payment to your
            local ledger. It does not call PayPal and moves no real money. It is not proof of payment.
          </Callout>
        ) : (
          <Callout tone="blue" title={`PayPal ${provider.mode_label} mode`} icon={ShieldCheck}>
            {provider.note} A browser success page alone is not proof of payment; cash changes only after the
            backend verifies a captured order or a signed webhook.
          </Callout>
        )}

        <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-[11px] text-slate-400">Invoice</p>
              <p className="font-mono text-[13px] font-semibold text-ink-900">{invoice.number}</p>
            </div>
            <div className="text-right">
              <p className="text-[11px] text-slate-400">Outstanding</p>
              <p className="text-[15px] font-semibold text-ink-900">
                {moneyExact(invoice.outstanding, invoice.currency || currency)}
              </p>
            </div>
          </div>
          <div className="mt-2 grid gap-1 text-[11px] text-slate-500 sm:grid-cols-2">
            <span>Customer: {invoice.customer.name}</span>
            <span>Due: {formatDate(invoice.due_date)}</span>
            <span className="truncate">Email: {invoice.customer.email}</span>
            <span>Status: {titleCase(invoice.status)}</span>
          </div>
        </div>

        {configured && order && (
          <div className="space-y-2 rounded-xl border border-brand-200 bg-brand-50/40 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-[11px] text-brand-600">PayPal order</p>
                <p className="font-mono text-[12px] font-semibold text-brand-900">
                  {order.id || "No remote order created"}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <DataModeBadge mode={order.mode} />
                {order.status && <Badge tone="blue">{order.status}</Badge>}
              </div>
            </div>
            <p className="text-[11px] leading-relaxed text-brand-800">{order.note}</p>
            {order.approve_url ? (
              <a
                href={order.approve_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-500 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-brand-600"
              >
                Open PayPal approval <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            ) : (
              <p className="text-[11px] font-medium text-amber-700">
                No PayPal approval URL was returned. Do not treat this as paid.
              </p>
            )}
            <p className="text-[10px] text-brand-700/70">
              Complete the sandbox approval in the PayPal tab, then return here and select “Verify &amp;
              capture”. The backend calls PayPal and re-checks the capture before recording cash.
            </p>
          </div>
        )}

        {result && (
          <Callout
            tone={result.mismatch ? "amber" : "green"}
            title={result.mismatch ? "Captured but not matched to the invoice" : "Recorded by the backend"}
            icon={result.mismatch ? AlertTriangle : CheckCircle2}
          >
            <p>{result.message}</p>
            <p className="mt-1 text-[11px] opacity-80">
              {result.mismatch
                ? "The capture was stored as unmatched for owner reconciliation. The invoice was not marked paid."
                : configured
                  ? "This entry came from a server-verified PayPal capture."
                  : "This entry is a simulated demo payment and is labelled as such in the ledger."}
            </p>
          </Callout>
        )}

        {!result && (
          <Checkbox
            checked={acknowledged}
            onChange={setAcknowledged}
            label={
              configured ? (
                <span>
                  I completed the PayPal sandbox approval for this order. I understand cash is recorded only if
                  the server-side capture verification succeeds.
                </span>
              ) : (
                <span>
                  I understand this action writes a <strong>simulated</strong> payment, calls no PayPal API, and
                  does not prove that any customer paid.
                </span>
              )
            }
          />
        )}

        {!configured && (
          <p className="flex items-start gap-1.5 text-[10px] leading-relaxed text-slate-400">
            <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
            To test real PayPal sandbox flows, set backend credentials and a webhook ID. Keys never reach the
            browser.
          </p>
        )}

        {error && (
          <Callout tone="red" title="Payment not recorded" icon={AlertTriangle}>
            {error}
          </Callout>
        )}
      </div>
    </Modal>
  );
}

function RefundModal({
  payment,
  currency,
  onClose,
  onDone,
}: {
  payment: Payment;
  currency: string;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const refundable = payment.refundable_amount ?? payment.amount;
  const [amount, setAmount] = useState(String(refundable));
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setError("Enter a refund amount greater than zero.");
      return;
    }
    if (value > refundable) {
      setError(`The refundable balance is ${moneyExact(refundable, payment.currency || currency)}.`);
      return;
    }
    if (reason.trim().length < 3) {
      setError("Add a short reason for the refund.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await post<PayPalRefundResponse>(
        `/paypal/payments/${payment.id}/refund`,
        { amount: value, reason: reason.trim(), confirm: true },
      );
      onDone(response.message);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Refund a verified PayPal capture"
      description={`${payment.invoice_number || "Unmatched capture"} · ${moneyExact(
        refundable,
        payment.currency || currency,
      )} refundable`}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="danger"
            icon={Undo2}
            loading={busy}
            onClick={() => void submit()}
            disabled={!confirmed || busy}
          >
            Submit refund
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Callout tone="amber" title="Owner-initiated refund" icon={AlertTriangle}>
          The backend calls PayPal and records the refund only after PayPal accepts it. AI agents cannot
          initiate refunds. Duplicate refunds are rejected.
        </Callout>
        <Field
          label="Refund amount"
          htmlFor="refund-amount"
          hint={`Maximum ${moneyExact(refundable, payment.currency || currency)}. Partial refunds are supported.`}
        >
          <Input
            id="refund-amount"
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </Field>
        <Field label="Reason" htmlFor="refund-reason" required>
          <Input
            id="refund-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Customer return, duplicate charge…"
            maxLength={500}
          />
        </Field>
        <div className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-500">
          <p>
            Capture: <span className="font-mono">{payment.provider_ref || "—"}</span>
          </p>
          <p>
            Received: {payment.received_at ? formatDateTime(payment.received_at) : "—"} ·{" "}
            {payment.provider === "paypal_demo" ? "Simulated capture" : "Verified PayPal capture"}
          </p>
        </div>
        <Checkbox
          checked={confirmed}
          onChange={setConfirmed}
          label="I confirm this refund is authorised for this business. Refunds move money and cannot be undone from here."
        />
        {error && <p className="text-[11px] font-medium text-rose-600">{error}</p>}
      </div>
    </Modal>
  );
}

function RefundHistory({ rows, currency }: { rows: PayPalRefundRecord[]; currency: string }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={Undo2}
        title="No refunds recorded"
        description="Refunds initiated from a verified capture appear here with their PayPal refund reference."
      />
    );
  }
  return (
    <TableWrap>
      <THead>
        <TR>
          <TH>Refund</TH>
          <TH>Invoice</TH>
          <TH>Capture</TH>
          <TH>Status</TH>
          <TH>Created</TH>
          <TH className="text-right">Amount</TH>
        </TR>
      </THead>
      <TBody>
        {rows.map((refund) => (
          <TR key={refund.id}>
            <TD>
              <p className="font-mono text-[11px] font-semibold text-ink-900">
                {refund.provider_refund_id || `REF-${refund.id}`}
              </p>
              <p className="max-w-[220px] truncate text-[10px] text-slate-400">{refund.reason || "—"}</p>
            </TD>
            <TD>
              <span className="font-mono text-[11px] text-slate-600">{refund.invoice_number || "—"}</span>
            </TD>
            <TD>
              <span className="font-mono text-[10px] text-slate-500">{refund.capture_id || "—"}</span>
            </TD>
            <TD>
              <Badge tone={refund.status === "completed" ? "green" : refund.status === "failed" ? "red" : "amber"}>
                {titleCase(refund.status)}
              </Badge>
            </TD>
            <TD>
              <span className="text-[11px] text-slate-500">{formatDateTime(refund.created_at)}</span>
            </TD>
            <TD className="text-right">
              <span className="text-[12px] font-semibold text-rose-600">
                −{moneyExact(refund.amount, refund.currency || currency)}
              </span>
            </TD>
          </TR>
        ))}
      </TBody>
    </TableWrap>
  );
}

function OrderHistory({
  rows,
  currency,
  onCancel,
  busyId,
}: {
  rows: PayPalOrderRecord[];
  currency: string;
  onCancel: (order: PayPalOrderRecord) => void;
  busyId: number | null;
}) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={CreditCard}
        title="No PayPal checkouts yet"
        description="Create a checkout from an outstanding invoice. Every order is stored with its provider reference."
      />
    );
  }
  return (
    <TableWrap>
      <THead>
        <TR>
          <TH>Order</TH>
          <TH>Invoice</TH>
          <TH>Status</TH>
          <TH>Capture</TH>
          <TH>Created</TH>
          <TH className="text-right">Amount</TH>
          <TH />
        </TR>
      </THead>
      <TBody>
        {rows.map((order) => (
          <TR key={order.id}>
            <TD>
              <p className="font-mono text-[11px] font-semibold text-ink-900">
                {order.provider_order_id || `LOCAL-${order.id}`}
              </p>
              <p className="text-[10px] text-slate-400">{order.customer_name || "—"}</p>
            </TD>
            <TD>
              <span className="font-mono text-[11px] text-slate-600">{order.invoice_number || "—"}</span>
            </TD>
            <TD>
              <Badge
                tone={
                  order.status === "COMPLETED"
                    ? "green"
                    : OPEN_ORDER_STATUSES.has(order.status)
                      ? "amber"
                      : "slate"
                }
              >
                {order.status}
              </Badge>
            </TD>
            <TD>
              <span className="font-mono text-[10px] text-slate-500">{order.capture_id || "—"}</span>
            </TD>
            <TD>
              <span className="text-[11px] text-slate-500">{formatDateTime(order.created_at)}</span>
            </TD>
            <TD className="text-right">
              <span className="text-[12px] font-semibold text-ink-900">
                {moneyExact(order.amount, order.currency || currency)}
              </span>
            </TD>
            <TD className="text-right">
              {OPEN_ORDER_STATUSES.has(order.status) && order.provider_order_id && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onCancel(order)}
                  loading={busyId === order.id}
                >
                  Cancel
                </Button>
              )}
            </TD>
          </TR>
        ))}
      </TBody>
    </TableWrap>
  );
}

function EventLog({ rows }: { rows: PayPalEventRecord[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={Webhook}
        title="No webhook events yet"
        description="Signed PayPal events appear here with their verification mode, outcome and deduplication result."
      />
    );
  }
  return (
    <div className="divide-y divide-slate-100">
      {rows.map((event) => (
        <div key={event.id} className="flex flex-start flex-wrap items-start gap-2 px-5 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-[11px] font-semibold text-ink-900">{event.event_type}</span>
              <Badge tone={event.verification === "paypal_signature_api" ? "green" : "amber"}>
                {event.verification === "paypal_signature_api" ? "Signature API" : "Demo HMAC"}
              </Badge>
              {event.outcome.startsWith("duplicate") && <Badge tone="slate">Duplicate</Badge>}
            </div>
            <p className="mt-0.5 break-all font-mono text-[10px] text-slate-400">{event.event_id}</p>
            <p className="mt-0.5 text-[11px] text-slate-600">{event.outcome}</p>
          </div>
          <span className="text-[10px] text-slate-400">{formatDateTime(event.processed_at)}</span>
        </div>
      ))}
    </div>
  );
}

export function PaymentsPage() {
  const { profile } = useAuth();
  const { toast } = useToast();
  const [range, setRange] = useState<RangeKey>("30d");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [tab, setTab] = useState<PaymentTab>("all");
  const [currencyFilter, setCurrencyFilter] = useState(profile?.currency || "INR");
  const [invoiceQuery, setInvoiceQuery] = useState("");
  const [paymentQuery, setPaymentQuery] = useState("");
  const [checkout, setCheckout] = useState<Invoice | null>(null);
  const [refundTarget, setRefundTarget] = useState<Payment | null>(null);
  const [cancellingOrder, setCancellingOrder] = useState<number | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (range === "today") {
      const today = new Date().toISOString().slice(0, 10);
      params.set("start", today);
      params.set("end", today);
    } else if (range === "custom" && customStart && customEnd) {
      params.set("start", customStart);
      params.set("end", customEnd);
    } else {
      const option = RANGE_OPTIONS.find((item) => item.key === range);
      params.set("days", String(option?.days ?? 30));
    }
    if (tab !== "all") params.set("status", tab);
    if (currencyFilter) params.set("currency", currencyFilter);
    return `/payments/overview?${params.toString()}`;
  }, [range, customStart, customEnd, tab, currencyFilter]);

  const overview = useApi<PaymentOverview>(query);
  const data = overview.data;
  const provider = data?.provider;
  const currency = currencyFilter || profile?.currency || "INR";

  useEffect(() => {
    if (!data || !currencyFilter) return;
    if (data.currencies.length && !data.currencies.includes(currencyFilter)) {
      setCurrencyFilter(data.currencies.includes(profile?.currency || "INR") ? (profile?.currency as string) : data.currencies[0]);
    }
  }, [data, currencyFilter, profile?.currency]);

  // Returning from the PayPal approval page: reopen the checkout so the owner verifies the capture.
  useEffect(() => {
    if (!data) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("paypal") !== "return") return;
    const invoiceId = Number(params.get("invoice_id"));
    const invoice = data.open_invoices.find((item) => item.id === invoiceId);
    if (invoice) setCheckout(invoice);
    const url = new URL(window.location.href);
    url.searchParams.delete("paypal");
    url.searchParams.delete("invoice_id");
    window.history.replaceState({}, "", url.toString());
  }, [data]);

  const openInvoices = useMemo(() => {
    const needle = invoiceQuery.trim().toLowerCase();
    const rows = data?.open_invoices || [];
    if (!needle) return rows;
    return rows.filter((invoice) =>
      [invoice.number, invoice.customer.name, invoice.customer.company || ""]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [data?.open_invoices, invoiceQuery]);

  const payments = useMemo(() => {
    const needle = paymentQuery.trim().toLowerCase();
    return (data?.payments || []).filter((payment) => {
      const statusMatch = tab === "all" || payment.status === tab;
      const queryMatch =
        !needle ||
        [payment.invoice_number, payment.customer_name, payment.provider_ref, payment.note]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(needle);
      return statusMatch && queryMatch;
    });
  }, [data?.payments, tab, paymentQuery]);

  const openOrders = useMemo(
    () => (data?.orders || []).filter((order) => OPEN_ORDER_STATUSES.has(order.status)),
    [data?.orders],
  );

  const refresh = () => {
    overview.reload();
    window.dispatchEvent(new Event("finovexa:approvals-changed"));
  };

  const cancelOrder = async (order: PayPalOrderRecord) => {
    setCancellingOrder(order.id);
    try {
      const response = await post<{ message: string }>(
        `/paypal/orders/${order.provider_order_id || order.id}/cancel`,
      );
      toast({ tone: "info", title: "Checkout cancelled", description: response.message });
      refresh();
    } catch (err) {
      toast({ tone: "error", title: "Could not cancel", description: getErrorMessage(err) });
    } finally {
      setCancellingOrder(null);
    }
  };

  const stats = data?.statistics;
  const reconciliation = data?.reconciliation;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Collections"
        title="Payment Center"
        description="Create PayPal checkouts, verify captures, issue owner-authorised refunds and reconcile every verified transaction."
        actions={
          <Button
            variant="outline"
            size="sm"
            icon={RefreshCw}
            onClick={refresh}
            loading={overview.loading}
          >
            Refresh ledger
          </Button>
        }
      />

      {overview.loading && !data ? (
        <PageSkeleton cards={4} />
      ) : overview.error ? (
        <ErrorState message={overview.error} onRetry={overview.reload} />
      ) : data && provider && stats && reconciliation ? (
        <>
          <Card>
            <CardBody className="flex flex-wrap items-end gap-3 pt-4">
              <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 p-1">
                {RANGE_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setRange(option.key)}
                    className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                      range === option.key
                        ? "bg-brand-500 text-white"
                        : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Status
                </label>
                <Select
                  value={tab}
                  onChange={(event) => setTab(event.target.value as PaymentTab)}
                  className="h-8 w-32 text-xs"
                  aria-label="Filter by payment status"
                >
                  <option value="all">All</option>
                  <option value="confirmed">Confirmed</option>
                  <option value="pending">Pending</option>
                  <option value="failed">Failed</option>
                </Select>
                <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Currency
                </label>
                <Select
                  value={currencyFilter}
                  onChange={(event) => setCurrencyFilter(event.target.value)}
                  className="h-8 w-24 text-xs"
                  aria-label="Filter by currency"
                >
                  {data.currencies.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </Select>
              </div>
              {range === "custom" && (
                <div className="flex flex-wrap items-center gap-2">
                  <CalendarDays className="h-3.5 w-3.5 text-slate-400" aria-hidden />
                  <Input
                    type="date"
                    value={customStart}
                    onChange={(event) => setCustomStart(event.target.value)}
                    className="h-8 w-36 text-xs"
                    aria-label="Custom range start"
                  />
                  <span className="text-[11px] text-slate-400">to</span>
                  <Input
                    type="date"
                    value={customEnd}
                    onChange={(event) => setCustomEnd(event.target.value)}
                    className="h-8 w-36 text-xs"
                    aria-label="Custom range end"
                  />
                </div>
              )}
              <span className="ml-auto text-[10px] text-slate-400">
                {formatDate(data.filters.start)} → {formatDate(data.filters.end)} ·{" "}
                {data.filters.currency || "all currencies"}
              </span>
            </CardBody>
          </Card>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Net verified PayPal"
              value={moneyExact(stats.net_received, currency)}
              icon={CheckCircle2}
              tone="green"
              sub={`${moneyExact(stats.gross_received, currency)} received · ${moneyExact(
                stats.refunded_total,
                currency,
              )} refunded`}
            />
            <StatCard
              label="Pending captures"
              value={moneyExact(stats.pending_total, currency)}
              icon={Clock3}
              tone="amber"
              sub={`${number(stats.pending_count)} pending · never counted as cash`}
            />
            <StatCard
              label="Failed attempts"
              value={moneyExact(stats.failed_total, currency)}
              icon={XCircle}
              tone="red"
              sub={`${number(stats.failed_count)} failed checkouts or denied captures`}
            />
            <StatCard
              label="Needs reconciliation"
              value={moneyExact(stats.unmatched_confirmed + stats.mismatch_total, currency)}
              icon={ShieldAlert}
              tone="violet"
              sub={`${number(reconciliation.unmatched_count)} unmatched · ${number(
                reconciliation.mismatch_count,
              )} mismatched`}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
            <Card>
              <CardHeader
                title="Payments over time"
                description="Verified captures, refunds and net movement from the ledger — never projected data."
                icon={Landmark}
                actions={<DataModeBadge mode={provider.mode} />}
              />
              <CardBody className="pt-3">
                <PayPalFlowChart data={data.series} currency={currency} />
                <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm bg-emerald-300" aria-hidden /> Received
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm bg-rose-300" aria-hidden /> Refunded
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm bg-brand-500" aria-hidden /> Net
                  </span>
                  <span className="ml-auto">
                    {number(stats.successful_count)} successful · {number(stats.refund_count)} refunds ·{" "}
                    {number(stats.transaction_count)} transactions
                  </span>
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Provider status"
                icon={ShieldCheck}
                actions={<Badge tone={provider.configured ? "green" : "slate"} dot>{provider.mode_label}</Badge>}
              />
              <CardBody className="space-y-2.5 pt-3">
                <p className="text-[11.5px] leading-relaxed text-slate-600">{provider.note}</p>
                <div className="rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-600">
                  <p className="flex items-center justify-between gap-2">
                    Environment <span className="font-semibold">{titleCase(provider.environment)}</span>
                  </p>
                  <p className="mt-1 flex items-center justify-between gap-2">
                    Webhook ID
                    <span className={provider.webhook_configured ? "text-emerald-600" : "text-amber-600"}>
                      {provider.webhook_configured ? "Configured" : "Not configured"}
                    </span>
                  </p>
                  <p className="mt-1 flex items-center justify-between gap-2">
                    Client ID
                    <span className="font-mono text-[10px]">{provider.client_id_hint || "—"}</span>
                  </p>
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-navy-950 px-3 py-2">
                  <code className="min-w-0 flex-1 break-all font-mono text-[10px] text-slate-300">
                    {data.webhook_endpoint}
                  </code>
                  <CopyButton value={data.webhook_endpoint} label="Copy" />
                </div>
                <p className="text-[10.5px] leading-relaxed text-slate-500">{provider.webhook_verification}</p>
                <Callout tone="amber" icon={ShieldAlert}>
                  A browser success page is not proof of payment. Cash changes only after server-side capture
                  verification or a verified, deduplicated webhook.
                </Callout>
              </CardBody>
              <CardFooter>
                <span>{number(reconciliation.duplicate_events)} duplicate events blocked</span>
                <PageLink to="/settings">PayPal settings</PageLink>
              </CardFooter>
            </Card>
          </div>

          <Card>
            <CardHeader
              title="Outstanding invoices"
              description="Collect through PayPal sandbox, or record a clearly labelled simulated payment when PayPal is not configured."
              icon={ReceiptText}
              actions={
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                  <Input
                    value={invoiceQuery}
                    onChange={(event) => setInvoiceQuery(event.target.value)}
                    placeholder="Search invoices…"
                    className="h-8 w-48 pl-8 text-xs"
                    aria-label="Search open invoices"
                  />
                </div>
              }
            />
            <div className="mt-3">
              {openInvoices.length === 0 ? (
                <EmptyState
                  icon={ReceiptText}
                  title={data.open_invoices.length ? "No matching invoices" : "No outstanding invoices"}
                  description={
                    data.open_invoices.length
                      ? "Try a different invoice number or customer."
                      : "Every invoice is settled. New outstanding invoices appear here."
                  }
                />
              ) : (
                <div>
                  {openInvoices.map((invoice) => (
                    <InvoiceRow
                      key={invoice.id}
                      invoice={invoice}
                      currency={currency}
                      configured={provider.configured}
                      onOpen={() => setCheckout(invoice)}
                    />
                  ))}
                </div>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="PayPal transactions"
              description="Provider records including pending and failed attempts. Only confirmed captures affect cash; refunds reduce it."
              icon={Landmark}
              actions={
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                  <Input
                    value={paymentQuery}
                    onChange={(event) => setPaymentQuery(event.target.value)}
                    placeholder="Search payments…"
                    className="h-8 w-48 pl-8 text-xs"
                    aria-label="Search payments"
                  />
                </div>
              }
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 px-5">
              <Tabs<PaymentTab>
                items={[
                  { key: "all", label: "All", count: stats.transaction_count },
                  { key: "confirmed", label: "Confirmed", count: stats.successful_count },
                  { key: "pending", label: "Pending", count: stats.pending_count },
                  { key: "failed", label: "Failed", count: stats.failed_count },
                ]}
                value={tab}
                onChange={setTab}
                size="sm"
              />
              <p className="text-[10px] text-slate-400">
                Confirmed in view:{" "}
                {moneyExact(
                  payments
                    .filter((payment) => payment.status === "confirmed" && payment.amount > 0)
                    .reduce((total, payment) => total + payment.amount, 0),
                  currency,
                )}
              </p>
            </div>
            <div className="mt-2">
              {payments.length === 0 ? (
                <EmptyState
                  icon={Landmark}
                  title="No payments in this view"
                  description="Provider payments and recorded captures appear here once they exist."
                />
              ) : (
                <TableWrap>
                  <THead>
                    <TR>
                      <TH>Payment</TH>
                      <TH>Invoice</TH>
                      <TH>Status</TH>
                      <TH>Reconciliation</TH>
                      <TH>Received</TH>
                      <TH className="text-right">Amount</TH>
                      <TH />
                    </TR>
                  </THead>
                  <TBody>
                    {payments.map((payment) => {
                      const refundable = payment.refundable_amount ?? payment.amount;
                      const canRefund =
                        payment.status === "confirmed" &&
                        payment.amount > 0 &&
                        ["paypal", "paypal_demo"].includes(payment.provider || "") &&
                        refundable > 0;
                      return (
                        <TR key={payment.id}>
                          <TD>
                            <p className="text-[12px] font-medium text-ink-900">
                              {payment.customer_name || payment.sender_name || "Unknown payer"}
                            </p>
                            <p className="font-mono text-[10px] text-slate-400">
                              {payment.provider_ref || `PAY-${payment.id}`}
                            </p>
                            {payment.provider === "paypal_demo" && (
                              <Badge tone="violet">Simulated</Badge>
                            )}
                            {payment.provider === "paypal_refund" && (
                              <Badge tone="red">Refund</Badge>
                            )}
                          </TD>
                          <TD>
                            <span className="font-mono text-[11.5px] text-slate-600">
                              {payment.invoice_number || "—"}
                            </span>
                            <p className="text-[10px] text-slate-400">{titleCase(payment.method)}</p>
                          </TD>
                          <TD>
                            <StatusBadge status={payment.status} />
                          </TD>
                          <TD>
                            {payment.reconciliation_status ? (
                              <Badge tone={reconciliationTone(payment.reconciliation_status)}>
                                {titleCase(payment.reconciliation_status.replace(/_/g, " "))}
                              </Badge>
                            ) : (
                              <span className="text-[10px] text-slate-400">—</span>
                            )}
                          </TD>
                          <TD>
                            <span className="text-[11px] text-slate-500">
                              {payment.received_at ? formatDateTime(payment.received_at) : "Not received"}
                            </span>
                          </TD>
                          <TD className="text-right">
                            <span
                              className={`text-[12px] font-semibold ${
                                payment.amount < 0 ? "text-rose-600" : "text-ink-900"
                              }`}
                            >
                              {moneyExact(payment.amount, payment.currency || currency)}
                            </span>
                          </TD>
                          <TD className="text-right">
                            {canRefund && (
                              <Button
                                variant="outline"
                                size="sm"
                                icon={Undo2}
                                onClick={() => setRefundTarget(payment)}
                              >
                                Refund
                              </Button>
                            )}
                          </TD>
                        </TR>
                      );
                    })}
                  </TBody>
                </TableWrap>
              )}
            </div>
            <CardFooter>
              <span className="flex items-center gap-1.5">
                <Lock className="h-3 w-3" aria-hidden /> No raw card data is stored. PayPal handles payment
                instruments.
              </span>
              <PageLink to="/recovery">Match unmatched payments</PageLink>
            </CardFooter>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader
                title="Checkout orders"
                description="Every PayPal order is stored locally with its provider reference and capture status."
                icon={CreditCard}
                actions={
                  openOrders.length ? (
                    <Badge tone="amber" dot>
                      {openOrders.length} open
                    </Badge>
                  ) : undefined
                }
              />
              <div className="mt-3">
                <OrderHistory
                  rows={data.orders}
                  currency={currency}
                  onCancel={(order) => void cancelOrder(order)}
                  busyId={cancellingOrder}
                />
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Refund history"
                description="Refunds reduce recorded cash and keep the original capture history intact."
                icon={Undo2}
                actions={<Badge tone={data.refunds.length ? "red" : "slate"}>{data.refunds.length}</Badge>}
              />
              <div className="mt-3">
                <RefundHistory rows={data.refunds} currency={currency} />
              </div>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader
                title="Payment reconciliation"
                description="Deterministic matching from verified records. AI may explain but never edits verified payments."
                icon={ListChecks}
                actions={
                  <Badge tone={reconciliation.mismatch_count ? "red" : reconciliation.unmatched_count ? "amber" : "green"} dot>
                    {reconciliation.matched_count} matched
                  </Badge>
                }
              />
              <CardBody className="space-y-3 pt-3">
                <div className="grid grid-cols-3 gap-2">
                  <div className="rounded-lg border border-emerald-100 bg-emerald-50/60 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-emerald-600">Matched</p>
                    <p className="text-[13px] font-semibold text-emerald-800">
                      {moneyExact(reconciliation.matched_amount, currency)}
                    </p>
                    <p className="text-[10px] text-emerald-700/70">{reconciliation.matched_count} captures</p>
                  </div>
                  <div className="rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-amber-600">Unmatched</p>
                    <p className="text-[13px] font-semibold text-amber-800">
                      {moneyExact(reconciliation.unmatched_amount, currency)}
                    </p>
                    <p className="text-[10px] text-amber-700/70">{reconciliation.unmatched_count} captures</p>
                  </div>
                  <div className="rounded-lg border border-rose-100 bg-rose-50/60 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-rose-600">Mismatch</p>
                    <p className="text-[13px] font-semibold text-rose-800">
                      {moneyExact(reconciliation.mismatch_amount, currency)}
                    </p>
                    <p className="text-[10px] text-rose-700/70">{reconciliation.mismatch_count} captures</p>
                  </div>
                </div>
                {reconciliation.history.length === 0 ? (
                  <p className="py-2 text-center text-[11px] text-slate-400">
                    No reconciliation history yet.
                  </p>
                ) : (
                  <div className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
                    {reconciliation.history.slice(0, 12).map((row) => (
                      <div
                        key={row.id}
                        className="flex items-start justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="flex flex-wrap items-center gap-1.5 text-[11px] font-semibold text-slate-700">
                            <Badge tone={reconciliationTone(row.status)}>{titleCase(row.status)}</Badge>
                            {row.invoice_id ? `Invoice #${row.invoice_id}` : "No invoice"}
                          </p>
                          <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">{row.reason}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-[11px] font-semibold text-slate-700">
                            {moneyExact(row.amount_delta, currency)}
                          </p>
                          <p className="text-[10px] text-slate-400">{formatDateTime(row.created_at)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-[10px] leading-relaxed text-slate-400">{reconciliation.note}</p>
              </CardBody>
              <CardFooter>
                <span>Owner confirmation is required before cash is matched.</span>
                <PageLink to="/recovery">Open Money Recovery</PageLink>
              </CardFooter>
            </Card>

            <Card>
              <CardHeader
                title="Webhook event log"
                description="Verified events are deduplicated by provider event ID. Invalid signatures are rejected before processing."
                icon={Webhook}
                actions={<Badge tone="blue">{data.events.length}</Badge>}
              />
              <div className="mt-3 max-h-[420px] overflow-y-auto">
                <EventLog rows={data.events} />
              </div>
              <CardFooter>
                <span>Repeated or delayed events never create duplicate payments.</span>
                <PageLink to="/audit">Audit trail</PageLink>
              </CardFooter>
            </Card>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Callout tone="blue" title="What happens on capture" icon={Info}>
              The backend calls PayPal, checks the capture status, amount, currency and invoice reference, then
              records a confirmed payment with a unique capture ID. Repeated captures and events are rejected as
              duplicates.
            </Callout>
            <Callout tone="slate" title="Refunds & reconciliation" icon={ArrowRight}>
              Refunds require explicit owner confirmation and are recorded as negative payments. Unmatched or
              mismatched captures stay outside invoice balances until you confirm a match in Money Recovery.
            </Callout>
          </div>
        </>
      ) : null}

      {checkout && provider && (
        <CheckoutModal
          invoice={checkout}
          provider={provider}
          currency={currency}
          onClose={() => setCheckout(null)}
          onDone={refresh}
        />
      )}

      {refundTarget && (
        <RefundModal
          payment={refundTarget}
          currency={currency}
          onClose={() => setRefundTarget(null)}
          onDone={(message) => {
            setRefundTarget(null);
            toast({ tone: "success", title: "Refund recorded", description: message });
            refresh();
          }}
        />
      )}
    </div>
  );
}
