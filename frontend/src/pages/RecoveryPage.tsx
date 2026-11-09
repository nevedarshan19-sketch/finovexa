import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Banknote,
  BellRing,
  CalendarClock,
  CheckCircle2,
  CirclePlus,
  Copy,
  CopyCheck,
  FileStack,
  HandCoins,
  Mail,
  MessageSquare,
  RefreshCw,
  Search,
  Send,
  Share2,
  ShieldCheck,
  Sparkles,
  Split,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, post } from "../lib/api";
import type {
  DuplicateCheck,
  Invoice,
  ReminderDraft,
  ReminderSchedule,
  ReminderScheduleItem,
  ReminderStageKey,
  ReminderTone,
  RecoverySummary,
  UnmatchedPayment,
} from "../lib/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Checkbox,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  Select,
  Skeleton,
  StatCard,
  TableWrap,
  TBody,
  TD,
  Textarea,
  TH,
  THead,
  TR,
} from "../components/ui";
import { ConfidenceBadge, StatusBadge } from "../components/DataMode";
import { AgingBars } from "../components/Charts";
import { formatDate, formatDateTime, money, moneyExact, pluralize, timeAgo } from "../lib/utils";

const STAGE_TONE: Record<ReminderStageKey, ReminderTone> = {
  due_in_7: "friendly",
  due_today: "professional",
  overdue_1_7: "professional",
  overdue_8_14: "firm",
  overdue_15_plus: "firm",
};

const SEVERITY_BADGE: Record<string, "slate" | "blue" | "amber" | "red" | "violet"> = {
  low: "blue",
  medium: "violet",
  high: "amber",
  critical: "red",
};

function ReminderModal({
  invoice,
  currency,
  stage,
  onClose,
  onCreated,
}: {
  invoice: Invoice | null;
  currency: string;
  stage?: ReminderStageKey | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { toast } = useToast();
  const [tone, setTone] = useState<ReminderTone>("professional");
  const [channel, setChannel] = useState<"email" | "sms">("email");
  const [draft, setDraft] = useState<ReminderDraft | null>(null);
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const open = Boolean(invoice);

  useEffect(() => {
    if (invoice) setTone(stage ? STAGE_TONE[stage] : "professional");
  }, [invoice, stage]);

  useEffect(() => {
    if (!invoice) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setAcknowledged(false);
    setDraft(null);
    post<ReminderDraft>(`/recovery/reminder-draft/${invoice.id}`, {
      tone,
      channel,
      ...(stage ? { stage } : {}),
    })
      .then((result) => {
        if (!alive) return;
        setDraft(result);
        setBody(channel === "sms" ? result.sms_body : result.body);
      })
      .catch((err: unknown) => {
        if (alive) setError(getErrorMessage(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [invoice, tone, channel, stage]);

  const submit = async () => {
    if (!invoice || !draft) return;
    setSubmitting(true);
    setError(null);
    try {
      await post("/approvals/reminders", {
        invoice_id: invoice.id,
        body,
        channel,
        recipient: draft.recipient,
        ...(channel === "email" ? { subject: draft.subject } : {}),
        ...(stage ? { stage } : {}),
      });
      window.dispatchEvent(new CustomEvent("finovexa:approvals-changed"));
      toast({
        title: "Approval requested",
        description: "The reminder is now waiting in the Approval Center. Nothing has been sent.",
        tone: "success",
      });
      onCreated();
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Draft reminder · ${invoice?.number || ""}`}
      description="A ledger-grounded draft. Requesting approval does not send anything."
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            icon={Send}
            onClick={submit}
            loading={submitting}
            disabled={
              !draft ||
              !acknowledged ||
              body.trim().length < 20 ||
              (channel === "sms" && (!draft.phone || body.length > 320))
            }
          >
            Request approval
          </Button>
        </>
      }
    >
      {error && (
        <Callout tone="red" title="Could not draft reminder" className="mb-4">
          {error}
        </Callout>
      )}
      {loading ? (
        <div className="space-y-3" aria-busy="true">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : draft ? (
        <div className="space-y-4">
          {draft.stage_label && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
              <Badge tone={draft.current_stage && draft.current_stage !== draft.stage ? "amber" : "violet"}>
                Deadline stage · {draft.stage_label}
              </Badge>
              <span>{draft.stage_description}</span>
              {draft.current_stage && draft.current_stage !== draft.stage && (
                <span className="text-amber-700">
                  The invoice has since moved to {draft.current_stage}; re-open the ladder to use the current stage.
                </span>
              )}
            </div>
          )}
          <Field label="Send by" hint="The message is stored until the owner approves it in the Approval Center.">
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[11px] font-semibold">
              {(["email", "sms"] as const).map((option) => {
                const Icon = option === "email" ? Mail : MessageSquare;
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setChannel(option)}
                    className={
                      channel === option
                        ? "flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-ink-900 shadow-sm"
                        : "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-slate-500"
                    }
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    {option === "email" ? "Email" : "SMS"}
                  </button>
                );
              })}
            </div>
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label={channel === "email" ? "Recipient (customer email)" : "Recipient (customer mobile)"}
              hint={
                channel === "sms" && !draft.phone
                  ? "No mobile number is saved for this customer."
                  : "Must match the customer record."
              }
            >
              <Input
                value={draft.recipient}
                readOnly
                className="bg-slate-50 text-slate-500"
              />
            </Field>
            <Field label="Tone">
              <Select value={tone} onChange={(event) => setTone(event.target.value as typeof tone)}>
                <option value="friendly">Friendly</option>
                <option value="professional">Professional</option>
                <option value="firm">Firm</option>
              </Select>
            </Field>
          </div>
          {channel === "sms" && !draft.phone && (
            <Callout tone="amber" title="Add a mobile number first">
              This customer has no mobile number on record. Edit the customer in Billing (or when creating the
              invoice) and save a mobile number before drafting an SMS reminder.
            </Callout>
          )}
          {channel === "email" && (
            <Field label="Subject" hint="Binding to this approval; edit the body below if needed.">
              <Input value={draft.subject} readOnly className="bg-slate-50 text-slate-500" />
            </Field>
          )}
          <Field
            label={channel === "email" ? "Email body" : "SMS text"}
            hint={
              channel === "email"
                ? `${body.length} characters · minimum 20`
                : `${body.length} / 320 characters · minimum 20`
            }
          >
            <Textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              maxLength={channel === "sms" ? 320 : 4000}
              className={
                channel === "email"
                  ? "min-h-[220px] font-mono text-[12px] leading-relaxed"
                  : "min-h-[120px] text-[12px] leading-relaxed"
              }
            />
          </Field>
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-500">
            <p className="font-semibold text-slate-600">Draft provenance</p>
            <p className="mt-0.5">
              {draft.note} Generated by {draft.generated_by} · mode {draft.mode}. Outstanding{" "}
              {moneyExact(Number(draft.facts.outstanding || 0), currency)} ·{" "}
              {String(draft.facts.overdue_days || 0)} days overdue.
            </p>
          </div>
          <Callout tone="amber" title="Approval is required before dispatch">
            {channel === "email" ? (
              draft.email_ready ? (
                <>
                  Email delivery is configured. Once approved, the reminder is sent to the customer through
                  your SMTP provider and the result is recorded in the audit trail.
                </>
              ) : (
                <>
                  Approval executes a <strong>simulated email dispatch</strong> in this build. Email delivery
                  is not configured, so nothing leaves the system.
                </>
              )
            ) : draft.sms_ready ? (
              <>
                SMS delivery is configured. Once approved, the message is sent through Twilio to the recorded
                mobile number. Standard message charges may apply.
              </>
            ) : (
              <>
                Approval executes a <strong>simulated SMS dispatch</strong> in this build. SMS delivery is not
                configured, so no message leaves the system.
              </>
            )}
          </Callout>
          <Checkbox
            checked={acknowledged}
            onChange={setAcknowledged}
            label={`I reviewed the ${channel === "email" ? "recipient" : "mobile number"}, amount and wording. I understand this creates an approval request, not a ${channel === "email" ? "sent email" : "sent SMS"}.`}
          />
        </div>
      ) : null}
    </Modal>
  );
}

function ShareReminderModal({
  item,
  currency,
  onClose,
  onDraft,
}: {
  item: ReminderScheduleItem | null;
  currency: string;
  onClose: () => void;
  onDraft: () => void;
}) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  useEffect(() => setCopied(false), [item]);

  const copy = async () => {
    if (!item) return;
    try {
      await navigator.clipboard.writeText(item.share.text);
      setCopied(true);
      toast({
        title: "Reminder copied",
        description: "Paste it into your email, SMS or WhatsApp chat.",
        tone: "success",
      });
    } catch {
      toast({
        title: "Could not copy",
        description: "Select the message text and copy it manually.",
        tone: "error",
      });
    }
  };

  const links = item
    ? [
        { key: "whatsapp", label: "WhatsApp", href: item.share.whatsapp_url, icon: MessageSquare },
        { key: "email", label: "Email", href: item.share.mailto_url, icon: Mail },
        { key: "sms", label: "SMS", href: item.share.sms_uri, icon: Send },
      ].filter((link) => Boolean(link.href))
    : [];

  return (
    <Modal
      open={Boolean(item)}
      onClose={onClose}
      title={`Share reminder · ${item?.invoice.number || ""}`}
      description="Opens your own mail, SMS or WhatsApp app with the message pre-filled. FINOVEXA sends nothing from this screen."
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button icon={BellRing} onClick={onDraft}>
            Draft and request approval
          </Button>
        </>
      }
    >
      {item && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 bg-slate-50/70 p-3">
            <div>
              <p className="text-xs font-semibold text-ink-900">
                {item.invoice.customer.name} · {item.invoice.number}
              </p>
              <p className="text-[11px] text-slate-500">
                {item.days_until_due >= 0
                  ? `Due ${formatDate(item.due_date)}`
                  : `${Math.abs(item.days_until_due)} days overdue`}
                {" · "}
                {item.reminded && item.last_reminder_at
                  ? `reminded ${timeAgo(item.last_reminder_at)}`
                  : "not reminded for this stage"}
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Outstanding</p>
              <p className="text-sm font-semibold text-ink-900">
                {moneyExact(item.outstanding, currency)}
              </p>
            </div>
          </div>
          <Field
            label="Message"
            hint={`${item.share.text.length} characters · edit after pasting if needed`}
          >
            <Textarea
              value={item.share.text}
              readOnly
              className="min-h-[190px] font-mono text-[12px] leading-relaxed"
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              variant={copied ? "success" : "outline"}
              size="sm"
              icon={copied ? CopyCheck : Copy}
              onClick={copy}
            >
              {copied ? "Copied" : "Copy message"}
            </Button>
            {links.map((link) => {
              const Icon = link.icon;
              return (
                <a
                  key={link.key}
                  href={link.href || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden />
                  {link.label}
                </a>
              );
            })}
          </div>
          {(!item.contact.email || !item.contact.phone) && (
            <Callout tone="amber" title="Missing contact details">
              {[
                !item.contact.email ? "No email on record" : null,
                !item.contact.phone ? "no mobile on record" : null,
              ]
                .filter(Boolean)
                .join(" · ")}
              . Add them in Billing or on the customer record so every stage can reach the customer.
            </Callout>
          )}
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-500">
            <p className="font-semibold text-slate-600">How the deadline ladder works</p>
            <p className="mt-0.5">
              {item.stage_description} The stage is derived from the due date (
              {formatDate(item.due_date)}). Sharing never changes the ledger; only an approved email
              or SMS is recorded against the invoice.
            </p>
          </div>
        </div>
      )}
    </Modal>
  );
}

function RecordPaymentModal({
  invoice,
  currency,
  onClose,
  onDone,
}: {
  invoice: Invoice | null;
  currency: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("bank");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    if (invoice) {
      setAmount(String(invoice.outstanding));
      setMethod("bank");
      setReference("");
      setNote("");
      setError(null);
      setAcknowledged(false);
    }
  }, [invoice]);

  const submit = async () => {
    if (!invoice) return;
    setSubmitting(true);
    setError(null);
    try {
      await post(`/invoices/${invoice.id}/payments`, {
        amount,
        method,
        reference: reference || null,
        note: note || null,
      });
      toast({
        title: "Payment recorded",
        description: "Confirmed cash updated. The action is recorded in the audit trail.",
        tone: "success",
      });
      onDone();
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const numeric = Number(amount);
  const invalid = !Number.isFinite(numeric) || numeric <= 0 || numeric > (invoice?.outstanding || 0);

  return (
    <Modal
      open={Boolean(invoice)}
      onClose={onClose}
      title={`Record payment · ${invoice?.number || ""}`}
      description="Only record payments you have verified from a bank, UPI or provider statement."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button icon={Banknote} variant="success" onClick={submit} loading={submitting} disabled={invalid || !acknowledged}>
            Record confirmed payment
          </Button>
        </>
      }
    >
      {invoice && (
        <div className="space-y-4">
          {error && (
            <Callout tone="red" title="Payment not recorded">
              {error}
            </Callout>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 bg-slate-50/70 p-3">
            <div>
              <p className="text-xs font-semibold text-ink-900">{invoice.customer.name} · {invoice.number}</p>
              <p className="text-[11px] text-slate-500">Due {formatDate(invoice.due_date)} · {invoice.aging_days > 0 ? `${invoice.aging_days} days overdue` : "current"}</p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wide text-slate-400">Outstanding</p>
              <p className="text-sm font-semibold text-ink-900">{moneyExact(invoice.outstanding, currency)}</p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Amount received" hint={invalid && amount ? "Must be between 0 and the outstanding balance." : "Decimal amounts are accepted."}>
              <Input
                type="number"
                min="0.01"
                step="0.01"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
              />
            </Field>
            <Field label="Method">
              <Select value={method} onChange={(event) => setMethod(event.target.value)}>
                <option value="bank">Bank transfer</option>
                <option value="upi">UPI</option>
                <option value="cash">Cash</option>
                <option value="card">Card (via provider)</option>
                <option value="other">Other</option>
              </Select>
            </Field>
          </div>
          <Field label="Reference" hint="Bank UTR, UPI reference or statement line identifier.">
            <Input value={reference} onChange={(event) => setReference(event.target.value)} placeholder="e.g. NEFT-88421" maxLength={120} />
          </Field>
          <Field label="Note">
            <Input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Verified against bank statement" maxLength={500} />
          </Field>
          <Callout tone="amber" title="This immediately changes recorded cash">
            Owner-recorded payments are treated as confirmed and are audited. Do not use this action for pending or
            unverified provider notifications.
          </Callout>
          <Checkbox
            checked={acknowledged}
            onChange={setAcknowledged}
            label="I verified this receipt outside FINOVEXA and confirm the amount and reference are accurate."
          />
        </div>
      )}
    </Modal>
  );
}

function MatchModal({
  payment,
  currency,
  onClose,
  onDone,
}: {
  payment: UnmatchedPayment | null;
  currency: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [invoiceId, setInvoiceId] = useState<number | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (payment) {
      setInvoiceId(payment.suggested_matches[0]?.invoice.id ?? null);
      setAcknowledged(false);
      setError(null);
    }
  }, [payment]);

  const selected = payment?.suggested_matches.find((match) => match.invoice.id === invoiceId);

  const submit = async () => {
    if (!payment || !invoiceId) return;
    setSubmitting(true);
    setError(null);
    try {
      await post(`/payments/${payment.id}/match`, { invoice_id: invoiceId, confirm: true });
      toast({
        title: "Payment reconciled",
        description: "The invoice balance and recorded cash now reflect this verified receipt.",
        tone: "success",
      });
      onDone();
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={Boolean(payment)}
      onClose={onClose}
      title="Reconcile unmatched payment"
      description="Matching applies a confirmed receipt to the exact invoice you select."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button icon={Split} onClick={submit} loading={submitting} disabled={!invoiceId || !acknowledged}>
            Confirm match
          </Button>
        </>
      }
    >
      {payment && (
        <div className="space-y-4">
          {error && (
            <Callout tone="red" title="Could not reconcile">
              {error}
            </Callout>
          )}
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3">
            <p className="text-xs font-semibold text-ink-900">
              {moneyExact(payment.amount, currency)} received via {payment.method.toUpperCase()}
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              {payment.sender_name || "Unknown sender"} · {payment.provider_ref || "no reference"} ·{" "}
              {formatDateTime(payment.received_at || payment.created_at)}
            </p>
            <p className="mt-1 text-[10px] text-slate-400">{payment.note}</p>
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Suggested invoices
            </p>
            {payment.suggested_matches.length === 0 ? (
              <EmptyState title="No suggestions" description="There are no candidate invoices for this receipt." />
            ) : (
              <div className="space-y-2">
                {payment.suggested_matches.map((match) => (
                  <label
                    key={match.invoice.id}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition ${
                      invoiceId === match.invoice.id ? "border-brand-300 bg-brand-50/50" : "border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <input
                      type="radio"
                      name="match-invoice"
                      checked={invoiceId === match.invoice.id}
                      onChange={() => setInvoiceId(match.invoice.id)}
                      className="mt-1 h-4 w-4 accent-brand-500"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-1">
                        <p className="text-xs font-semibold text-ink-900">
                          {match.invoice.number} · {match.invoice.customer.name}
                        </p>
                        <p className="text-xs font-semibold tabular-nums text-ink-900">
                          {money(match.invoice.outstanding, currency)} open
                        </p>
                      </div>
                      <p className="text-[10px] text-slate-400">
                        Due {formatDate(match.invoice.due_date)} · {match.invoice.customer.company || match.invoice.customer.email}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge tone="blue">{match.match_reason}</Badge>
                        {match.confidence && <ConfidenceBadge confidence={match.confidence} />}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>
          {selected && Number(payment.amount) > Number(selected.invoice.outstanding) && (
            <Callout tone="red" title="Amount exceeds outstanding">
              The receipt is larger than the selected invoice balance. The backend will reject this match.
            </Callout>
          )}
          <Checkbox
            checked={acknowledged}
            onChange={setAcknowledged}
            label="I checked the sender reference and confirm this receipt belongs to the selected invoice."
          />
        </div>
      )}
    </Modal>
  );
}

export function RecoveryPage() {
  const { profile } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const summary = useApi<RecoverySummary>("/recovery/summary?days=30");
  const invoiceList = useApi<{ items: Invoice[] }>("/invoices?status=outstanding&limit=100");
  const duplicates = useApi<DuplicateCheck>("/recovery/duplicates");
  const unmatched = useApi<{ items: UnmatchedPayment[] }>("/recovery/unmatched");
  const schedule = useApi<ReminderSchedule>("/recovery/reminder-schedule?window_days=7");
  const currency = profile?.currency || "INR";

  const [reminderInvoice, setReminderInvoice] = useState<Invoice | null>(null);
  const [reminderStage, setReminderStage] = useState<ReminderStageKey | null>(null);
  const [shareItem, setShareItem] = useState<ReminderScheduleItem | null>(null);
  const [stageFilter, setStageFilter] = useState<ReminderStageKey | "all">("all");
  const [showAllLadder, setShowAllLadder] = useState(false);
  const [paymentInvoice, setPaymentInvoice] = useState<Invoice | null>(null);
  const [matchPayment, setMatchPayment] = useState<UnmatchedPayment | null>(null);
  const [query, setQuery] = useState("");
  const [scanning, setScanning] = useState(false);

  const reloadAll = () => {
    summary.reload();
    invoiceList.reload();
    duplicates.reload();
    unmatched.reload();
    schedule.reload();
  };

  const invoices = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = invoiceList.data?.items ?? [];
    if (!needle) return rows;
    return rows.filter(
      (invoice) =>
        invoice.number.toLowerCase().includes(needle) ||
        invoice.customer.name.toLowerCase().includes(needle) ||
        (invoice.customer.company || "").toLowerCase().includes(needle),
    );
  }, [invoiceList.data, query]);

  const scan = () => {
    setScanning(true);
    duplicates.reload();
    window.setTimeout(() => {
      setScanning(false);
      toast({ title: "Duplicate scan refreshed", description: "Checked invoices and confirmed payments for possible duplicates.", tone: "info" });
    }, 500);
  };

  const ladder = schedule.data;
  const ladderItems = useMemo(() => {
    const rows = ladder?.items ?? [];
    return stageFilter === "all" ? rows : rows.filter((row) => row.stage === stageFilter);
  }, [ladder, stageFilter]);
  const visibleLadder = showAllLadder ? ladderItems : ladderItems.slice(0, 6);

  if (summary.loading && !summary.data) return <PageSkeleton cards={4} />;
  if (summary.error && !summary.data) return <ErrorState message={summary.error} onRetry={reloadAll} />;
  if (!summary.data) return null;

  const data = summary.data;
  const unmatchedItems = unmatched.data?.items ?? [];
  const dupes = duplicates.data;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Money recovery"
        title="Collect what you are owed"
        description="Prioritized overdue invoices, verified reconciliation and reminder drafts. Sending always requires owner approval."
        actions={
          <>
            <Button variant="outline" size="md" icon={RefreshCw} onClick={reloadAll}>
              Refresh
            </Button>
            <Button size="md" icon={Sparkles} onClick={() => navigate("/ask")}>
              Ask about receivables
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total outstanding"
          value={money(data.total_outstanding, currency)}
          icon={FileStack}
          sub={`${data.counts.open_invoices} open invoices`}
          tone="blue"
        />
        <StatCard
          label="Overdue"
          value={money(data.overdue_total, currency)}
          icon={AlertTriangle}
          sub={`${data.counts.overdue_invoices} invoices need follow-up`}
          tone="red"
        />
        <StatCard
          label="Recovered · last 30 days"
          value={money(data.recovered_in_period, currency)}
          icon={HandCoins}
          sub="confirmed payments in period"
          tone="green"
        />
        <StatCard
          label="Awaiting reconciliation"
          value={money(data.awaiting_reconciliation, currency)}
          icon={Split}
          sub={`${money(data.pending_payments, currency)} pending provider`}
          tone="amber"
        />
      </div>

      <Card>
        <CardHeader
          title="Reminder ladder · by deadline"
          description="Every open invoice sits on a reminder step derived from its due date. Share the message yourself, or draft an email/SMS that still needs owner approval."
          icon={CalendarClock}
          actions={
            <Badge tone="violet">
              {ladder ? `${ladder.summary.unreminded_count} awaiting a reminder` : "loading"}
            </Badge>
          }
        />
        <CardBody className="space-y-3 pt-3">
          {schedule.loading && !ladder ? (
            <div className="space-y-2" aria-busy="true">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : ladder ? (
            <>
              <div className="grid gap-2 sm:grid-cols-5">
                {ladder.summary.by_stage.map((tile) => {
                  const active = stageFilter === tile.key;
                  return (
                    <button
                      key={tile.key}
                      type="button"
                      onClick={() => {
                        setStageFilter(active ? "all" : tile.key);
                        setShowAllLadder(false);
                      }}
                      className={`rounded-xl border p-2.5 text-left transition ${
                        active
                          ? "border-brand-300 bg-brand-50/70 shadow-sm"
                          : "border-slate-100 bg-white hover:border-slate-200"
                      }`}
                      aria-pressed={active}
                      title={tile.description}
                    >
                      <span className="block text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                        {tile.label}
                      </span>
                      <span className="mt-1 block text-lg font-semibold leading-5 text-ink-900">
                        {tile.count}
                      </span>
                      <span className="block text-[10px] text-slate-500">
                        {money(tile.amount, currency)}
                      </span>
                      <span className="mt-1 block text-[10px] text-slate-400">
                        {tile.reminded_count} of {tile.count} reminded
                      </span>
                    </button>
                  );
                })}
              </div>

              {stageFilter !== "all" && (
                <div className="flex items-center gap-2 text-[11px] text-slate-500">
                  <span>
                    Showing <strong className="text-slate-700">{ladderItems.length}</strong> in this stage.
                  </span>
                  <Button variant="ghost" size="sm" onClick={() => setStageFilter("all")}>
                    Show all stages
                  </Button>
                </div>
              )}

              {ladderItems.length === 0 ? (
                <EmptyState
                  icon={CheckCircle2}
                  title="Nothing due in this stage"
                  description="No open invoice needs a reminder at this deadline step right now."
                  className="py-8"
                />
              ) : (
                <div className="space-y-2">
                  {visibleLadder.map((row) => (
                    <div
                      key={row.invoice.id}
                      className="rounded-xl border border-slate-100 bg-white p-3 transition hover:border-slate-200 hover:shadow-card"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Badge tone={SEVERITY_BADGE[row.severity]}>{row.stage_label}</Badge>
                            {row.reminded ? (
                              <Badge tone="green" dot>
                                Reminded · {row.reminded_channels.join(" + ")}
                              </Badge>
                            ) : (
                              <Badge tone="slate">Not reminded yet</Badge>
                            )}
                            {!row.contact.email && !row.contact.phone && (
                              <Badge tone="amber">No contact details</Badge>
                            )}
                          </div>
                          <p className="mt-1.5 text-xs font-semibold text-ink-900">
                            {row.invoice.number} · {row.invoice.customer.name}
                          </p>
                          <p className="text-[10px] leading-relaxed text-slate-400">
                            {row.days_until_due > 0
                              ? `Due in ${row.days_until_due} day${row.days_until_due === 1 ? "" : "s"}`
                              : row.days_until_due === 0
                                ? "Due today"
                                : `${Math.abs(row.days_until_due)} days overdue`}
                            {" · "}
                            due {formatDate(row.due_date)}
                            {row.contact.email ? ` · ${row.contact.email}` : ""}
                            {row.contact.phone ? ` · ${row.contact.phone}` : ""}
                          </p>
                        </div>
                        <div className="flex flex-col items-end gap-1.5">
                          <span className="text-sm font-semibold text-ink-900">
                            {moneyExact(row.outstanding, currency)}
                          </span>
                          <div className="flex gap-1.5">
                            <Button
                              size="sm"
                              variant="outline"
                              icon={Share2}
                              onClick={() => setShareItem(row)}
                            >
                              Share
                            </Button>
                            <Button
                              size="sm"
                              icon={Send}
                              onClick={() => {
                                setReminderStage(row.stage);
                                setReminderInvoice(row.invoice);
                              }}
                            >
                              Draft
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {ladderItems.length > visibleLadder.length && (
                <Button variant="ghost" size="sm" onClick={() => setShowAllLadder(true)}>
                  Show all {ladderItems.length} invoices in this view
                </Button>
              )}
            </>
          ) : (
            <Callout tone="amber" title="Reminder ladder unavailable">
              The deadline schedule could not be loaded. Refresh to try again.
            </Callout>
          )}
        </CardBody>
        {ladder && (
          <CardFooter>
            <p className="text-[11px] leading-relaxed text-slate-500">
              {ladder.note} {ladder.summary.not_due_count} invoice
              {ladder.summary.not_due_count === 1 ? "" : "s"} worth{" "}
              {money(ladder.summary.not_due_amount, currency)} are due later than{" "}
              {ladder.window_days} days from now.
            </p>
          </CardFooter>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-7">
          <CardHeader
            title="Priority queue"
            description="Weighted by outstanding value and overdue age. This is a prioritization aid, not a credit assessment."
            icon={BellRing}
            actions={<Badge tone="blue">{data.priority_invoices.length} invoices</Badge>}
          />
          <CardBody className="space-y-2 pt-3">
            {data.priority_invoices.map((row, index) => (
              <div
                key={row.invoice.id}
                className="rounded-xl border border-slate-100 bg-white p-3 transition hover:border-slate-200 hover:shadow-card"
              >
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-500">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-ink-900">
                          {row.invoice.number} · {row.invoice.customer.name}
                        </p>
                        <p className="text-[10px] text-slate-400">
                          {row.invoice.customer.company || row.invoice.customer.email} · due {formatDate(row.invoice.due_date)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-semibold tabular-nums text-ink-900">
                          {money(row.invoice.outstanding, currency)}
                        </p>
                        <p className="text-[10px] text-slate-400">score {row.priority_score.toFixed(1)}</p>
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {row.reasons.map((reason) => (
                        <Badge key={reason} tone={reason.includes("overdue") ? "red" : reason.includes("high value") ? "amber" : "slate"}>
                          {reason}
                        </Badge>
                      ))}
                      <StatusBadge status={row.invoice.status} />
                    </div>
                    <div className="mt-2.5 flex flex-wrap gap-2">
                      <Button size="sm" variant="outline" icon={Send} onClick={() => setReminderInvoice(row.invoice)}>
                        Draft reminder
                      </Button>
                      <Button size="sm" variant="ghost" icon={Banknote} onClick={() => setPaymentInvoice(row.invoice)}>
                        Record payment
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
            {data.priority_invoices.length === 0 && (
              <EmptyState
                title="No open invoices"
                description="Everything is collected. New invoices will appear here once outstanding."
                icon={CheckCircle2}
              />
            )}
          </CardBody>
        </Card>

        <div className="space-y-4 lg:col-span-5">
          <Card>
            <CardHeader title="Aging profile" description="Outstanding balance by days past due." icon={FileStack} />
            <CardBody className="pt-4">
              <AgingBars data={data.aging} currency={currency} />
            </CardBody>
            <CardFooter>
              <span>Current: {money(data.current_total, currency)}</span>
              <span>Overdue: {money(data.overdue_total, currency)}</span>
            </CardFooter>
          </Card>

          <Card>
            <CardHeader title="Reconciliation snapshot" icon={ShieldCheck} />
            <CardBody className="space-y-2.5 pt-3">
              <div className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-[11px] text-slate-500">Unmatched confirmed receipts</span>
                <span className="text-xs font-semibold tabular-nums text-ink-900">
                  {money(data.unmatched_confirmed, currency)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-[11px] text-slate-500">Pending provider payments</span>
                <span className="text-xs font-semibold tabular-nums text-ink-900">
                  {money(data.pending_payments, currency)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-[11px] text-slate-500">Confirmed payments all-time</span>
                <span className="text-xs font-semibold tabular-nums text-ink-900">
                  {money(data.confirmed_payments_total, currency)}
                </span>
              </div>
              <p className="flex items-start gap-1.5 pt-1 text-[10px] leading-relaxed text-slate-400">
                <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0" />
                Pending payments never count as cash. Confirmed receipts require an invoice before they can reduce
                outstanding balances.
              </p>
            </CardBody>
            <CardFooter>
              <span>{unmatchedItems.length} unmatched receipts</span>
              <Button size="sm" variant="outline" icon={Split} onClick={() => setMatchPayment(unmatchedItems[0] || null)} disabled={unmatchedItems.length === 0}>
                Reconcile
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader
          title="Unmatched payments"
          description="Confirmed receipts sitting outside an invoice. Match only when the sender reference and amount align."
          icon={Split}
          actions={
            <Badge tone={unmatchedItems.length ? "amber" : "green"} dot>
              {unmatchedItems.length ? `${unmatchedItems.length} needs review` : "All reconciled"}
            </Badge>
          }
        />
        <CardBody className="pt-3">
          {unmatched.loading && !unmatched.data ? (
            <Skeleton className="h-24 w-full" />
          ) : unmatchedItems.length === 0 ? (
            <EmptyState
              title="No unmatched payments"
              description="Every confirmed receipt is currently linked to an invoice."
              icon={CopyCheck}
            />
          ) : (
            <div className="space-y-3">
              {unmatchedItems.map((payment) => (
                <div key={payment.id} className="rounded-xl border border-amber-200 bg-amber-50/30 p-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-ink-900">
                        {moneyExact(payment.amount, currency)} · {payment.sender_name || "Unknown sender"}
                      </p>
                      <p className="mt-0.5 text-[10px] text-slate-500">
                        {payment.provider || payment.method} · {payment.provider_ref || "No reference"} ·{" "}
                        {timeAgo(payment.received_at || payment.created_at)}
                      </p>
                      <p className="mt-1 text-[10px] text-slate-400">{payment.note}</p>
                      {payment.suggested_matches[0] && (
                        <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-500">
                          Suggested: <strong className="font-semibold text-slate-700">{payment.suggested_matches[0].invoice.number}</strong>
                          <Badge tone="blue">{payment.suggested_matches[0].match_reason}</Badge>
                          {payment.suggested_matches[0].confidence && (
                            <ConfidenceBadge confidence={payment.suggested_matches[0].confidence} />
                          )}
                        </p>
                      )}
                    </div>
                    <Button size="sm" icon={Split} onClick={() => setMatchPayment(payment)}>
                      Reconcile
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-7">
          <CardHeader
            title="Duplicate detection"
            description="Deterministic checks for same-customer invoices and repeated payments."
            icon={CopyCheck}
            actions={
              <Button variant="outline" size="sm" icon={RefreshCw} onClick={scan} loading={scanning}>
                Rescan
              </Button>
            }
          />
          <CardBody className="space-y-3 pt-3">
            {duplicates.error && <Callout tone="red">{duplicates.error}</Callout>}
            {!dupes ? (
              <Skeleton className="h-20 w-full" />
            ) : (
              <>
                <div>
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    Invoice pairs · {dupes.duplicate_invoices.length}
                  </p>
                  {dupes.duplicate_invoices.length === 0 ? (
                    <p className="rounded-lg bg-slate-50 px-3 py-2.5 text-[11px] text-slate-400">
                      No possible duplicate invoices detected.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {dupes.duplicate_invoices.map((pair, index) => (
                        <div key={index} className="rounded-lg border border-amber-200 bg-amber-50/40 p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-xs font-semibold text-ink-900">
                              {pair.invoice_a.number} ↔ {pair.invoice_b.number}
                            </p>
                            <div className="flex items-center gap-1.5">
                              <span className="text-[10px] text-slate-500">{money(pair.invoice_a.total, currency)} each</span>
                              <ConfidenceBadge confidence={pair.confidence} />
                            </div>
                          </div>
                          <p className="mt-1 text-[10px] text-slate-500">
                            {pair.customer_name} · {pair.reason}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    Payment pairs · {dupes.duplicate_payments.length}
                  </p>
                  {dupes.duplicate_payments.length === 0 ? (
                    <p className="rounded-lg bg-slate-50 px-3 py-2.5 text-[11px] text-slate-400">
                      No duplicate confirmed payments detected.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {dupes.duplicate_payments.map((pair, index) => (
                        <div key={index} className="rounded-lg border border-amber-200 bg-amber-50/40 p-3 text-[10px] text-slate-500">
                          Payments #{pair.payment_a.id} and #{pair.payment_b.id} · {pair.reason}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </CardBody>
          <CardFooter>
            <span>Flagged pairs require human review; nothing is merged automatically.</span>
            <span>Checked {dupes ? timeAgo(dupes.checked_at) : "—"}</span>
          </CardFooter>
        </Card>

        <Card className="lg:col-span-5">
          <CardHeader title="Recovery guardrails" icon={ShieldCheck} />
          <CardBody className="space-y-3 pt-3 text-[11px] leading-relaxed text-slate-500">
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
              Reminders are drafted from ledger records and require approval before dispatch.
            </div>
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
              Approvals are hash-bound to the exact recipient, invoice and message body.
            </div>
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
              Pending or failed provider payments never increase cash or reduce receivables.
            </div>
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
              Duplicate flags are advisory; no invoice is voided or merged automatically.
            </div>
            <p className="rounded-lg border border-slate-100 bg-slate-50/70 p-2.5 text-[10px]">
              Collection probability is not modelled here. The priority score combines relative outstanding value
              (60%) and overdue age up to 90 days (40%).
            </p>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Open invoice ledger"
          description={`${invoices.length} of ${invoiceList.data?.items.length ?? 0} outstanding invoices.`}
          icon={FileStack}
          actions={
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" aria-hidden />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search invoices"
                className="h-8 w-56 pl-8 text-xs"
                aria-label="Search outstanding invoices"
              />
            </div>
          }
        />
        <div className="mt-3">
          {invoiceList.loading && !invoiceList.data ? (
            <div className="p-5">
              <Skeleton className="h-32 w-full" />
            </div>
          ) : invoices.length === 0 ? (
            <EmptyState title="No invoices match" description="Try a different invoice number or customer name." icon={Search} />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Invoice</TH>
                  <TH>Customer</TH>
                  <TH>Due</TH>
                  <TH className="text-right">Outstanding</TH>
                  <TH>Aging</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {invoices.map((invoice) => (
                  <TR key={invoice.id}>
                    <TD>
                      <p className="font-semibold text-ink-900">{invoice.number}</p>
                      <p className="text-[10px] text-slate-400">Issued {formatDate(invoice.issue_date)}</p>
                    </TD>
                    <TD>
                      <p className="font-medium text-ink-900">{invoice.customer.name}</p>
                      <p className="text-[10px] text-slate-400">{invoice.customer.company || invoice.customer.email}</p>
                    </TD>
                    <TD>{formatDate(invoice.due_date)}</TD>
                    <TD className="text-right font-semibold tabular-nums">{money(invoice.outstanding, currency)}</TD>
                    <TD>
                      <span className={invoice.aging_days > 0 ? "font-medium text-rose-600" : "text-slate-500"}>
                        {invoice.aging_days > 0 ? `${invoice.aging_days}d overdue` : "Current"}
                      </span>
                    </TD>
                    <TD>
                      <StatusBadge status={invoice.status} />
                    </TD>
                    <TD>
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" icon={Send} onClick={() => setReminderInvoice(invoice)} title="Draft reminder">
                          Remind
                        </Button>
                        <Button size="sm" variant="ghost" icon={CirclePlus} onClick={() => setPaymentInvoice(invoice)} title="Record payment">
                          Pay
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </div>
        <CardFooter>
          <span>Invoice records are tenant-scoped and verifiable through the audit trail.</span>
          <span>{pluralize(invoiceList.data?.items.length ?? 0, "open invoice")}</span>
        </CardFooter>
      </Card>

      <ReminderModal
        invoice={reminderInvoice}
        currency={currency}
        stage={reminderStage}
        onClose={() => {
          setReminderInvoice(null);
          setReminderStage(null);
        }}
        onCreated={() => {
          reloadAll();
          navigate("/approvals");
        }}
      />
      <ShareReminderModal
        item={shareItem}
        currency={currency}
        onClose={() => setShareItem(null)}
        onDraft={() => {
          if (!shareItem) return;
          setReminderStage(shareItem.stage);
          setReminderInvoice(shareItem.invoice);
          setShareItem(null);
        }}
      />
      <RecordPaymentModal
        invoice={paymentInvoice}
        currency={currency}
        onClose={() => setPaymentInvoice(null)}
        onDone={reloadAll}
      />
      <MatchModal
        payment={matchPayment}
        currency={currency}
        onClose={() => setMatchPayment(null)}
        onDone={reloadAll}
      />
    </div>
  );
}
