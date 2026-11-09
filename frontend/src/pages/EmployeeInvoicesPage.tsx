import { useState, type FormEvent } from "react";
import {
  FilePlus2,
  History,
  Lock,
  Pencil,
  Plus,
  ReceiptText,
  RefreshCw,
  Trash2,
  Undo2,
  Wallet,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, patch, post } from "../lib/api";
import { StockItemCombobox, type StockItem } from "../components/StockItemCombobox";
import type {
  EmployeeEntry,
  EmployeeEntriesResponse,
  EmployeeInvoicePaymentsResponse,
} from "../lib/types";
import { formatDate, formatDateTime, money } from "../lib/utils";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  Badge,
  Button,
  Callout,
  Card,
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
  StatCard,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Textarea,
} from "../components/ui";

interface InvoiceLineDraft {
  key: number;
  description: string;
  quantity: string;
  unit_price: string;
  product_id: number | null;
  gst_rate: number | null;
}

interface InvoiceDraft {
  customer: string;
  customerEmail: string;
  customerPhone: string;
  issueDate: string;
  dueDate: string;
  taxRate: string;
  notes: string;
  paymentReceived: string;
  paymentMode: string;
  paymentDate: string;
  paymentReference: string;
  lines: InvoiceLineDraft[];
}

const PAYMENT_MODES = [
  { value: "cash", label: "Cash" },
  { value: "upi", label: "UPI" },
  { value: "bank", label: "Bank transfer" },
  { value: "card", label: "Card" },
  { value: "cheque", label: "Cheque" },
  { value: "other", label: "Other" },
];

let lineKey = 1;

function nextLineKey(): number {
  lineKey += 1;
  return lineKey;
}

function localDate(offsetDays = 0): string {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function newLine(): InvoiceLineDraft {
  return {
    key: nextLineKey(),
    description: "",
    quantity: "1",
    unit_price: "",
    product_id: null,
    gst_rate: null,
  };
}

function blankDraft(): InvoiceDraft {
  return {
    customer: "",
    customerEmail: "",
    customerPhone: "",
    issueDate: localDate(),
    dueDate: localDate(30),
    taxRate: "18",
    notes: "",
    paymentReceived: "",
    paymentMode: "upi",
    paymentDate: localDate(),
    paymentReference: "",
    lines: [newLine()],
  };
}

function draftFromEntry(entry: EmployeeEntry): InvoiceDraft {
  return {
    customer: entry.counterparty,
    customerEmail: entry.counterparty_email ?? "",
    customerPhone: entry.counterparty_phone ?? "",
    issueDate: entry.entry_date,
    dueDate: entry.due_date || localDate(30),
    taxRate: String(entry.tax_rate ?? 0),
    notes: entry.notes || "",
    paymentReceived: "",
    paymentMode: "upi",
    paymentDate: localDate(),
    paymentReference: "",
    lines:
      entry.items.length > 0
        ? entry.items.map((item) => ({
            key: nextLineKey(),
            description: item.description,
            quantity: String(item.quantity),
            unit_price: String(item.unit_price),
            product_id: item.product_id ?? null,
            gst_rate: item.gst_rate ?? null,
          }))
        : [
            {
              key: nextLineKey(),
              description: entry.description,
              quantity: "1",
              unit_price: String(entry.amount),
              product_id: null,
              gst_rate: null,
            },
          ],
  };
}

function paymentStatusFor(total: number, received: number): string {
  if (total > 0 && received > total) return "OVERPAID";
  if (total > 0 && received >= total) return "PAID";
  if (received > 0) return "PARTIALLY PAID";
  return "UNPAID";
}

function paymentTone(state: string | null | undefined): "green" | "amber" | "violet" | "slate" {
  if (state === "paid") return "green";
  if (state === "partially_paid") return "amber";
  if (state === "overpaid") return "violet";
  return "slate";
}

function draftSubtotal(draft: InvoiceDraft): number {
  return draft.lines.reduce((total, line) => {
    const quantity = Number(line.quantity);
    const price = Number(line.unit_price);
    if (!Number.isFinite(quantity) || !Number.isFinite(price)) return total;
    return total + Math.max(0, quantity) * Math.max(0, price);
  }, 0);
}

function lineGstRate(line: InvoiceLineDraft, defaultRate: number): number {
  if (line.gst_rate != null && Number.isFinite(line.gst_rate)) return line.gst_rate;
  return Number.isFinite(defaultRate) ? defaultRate : 0;
}

function draftTax(draft: InvoiceDraft): number {
  const defaultRate = Number(draft.taxRate);
  return draft.lines.reduce((total, line) => {
    const quantity = Number(line.quantity);
    const price = Number(line.unit_price);
    if (!Number.isFinite(quantity) || !Number.isFinite(price)) return total;
    const lineTotal = Math.max(0, quantity) * Math.max(0, price);
    return total + (lineTotal * lineGstRate(line, defaultRate)) / 100;
  }, 0);
}

export function EmployeeInvoicesPage() {
  const { business } = useAuth();
  const { toast } = useToast();
  const invoicesApi = useApi<EmployeeEntriesResponse>(
    "/employee/entries?entry_type=invoice&status=all",
    { pollMs: 20000 },
  );
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EmployeeEntry | null>(null);
  const [draft, setDraft] = useState<InvoiceDraft>(blankDraft());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [voidTarget, setVoidTarget] = useState<EmployeeEntry | null>(null);
  const [voiding, setVoiding] = useState(false);
  const [payTarget, setPayTarget] = useState<EmployeeEntry | null>(null);
  const [paySaving, setPaySaving] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const [payForm, setPayForm] = useState({
    amount: "",
    mode: "upi",
    date: localDate(),
    reference: "",
    note: "",
  });
  const [historyTarget, setHistoryTarget] = useState<EmployeeEntry | null>(null);
  const historyApi = useApi<EmployeeInvoicePaymentsResponse>(
    historyTarget?.invoice_id ? `/employee/invoices/${historyTarget.invoice_id}/payments` : null,
  );

  const currency = business?.currency || "INR";
  const entries = invoicesApi.data?.items ?? [];
  const live = entries.filter((entry) => entry.status !== "void");
  const invoicedTotal = live.reduce((total, entry) => total + (entry.invoice_total || 0), 0);
  const outstandingTotal = live.reduce(
    (total, entry) => total + (entry.invoice_outstanding || 0),
    0,
  );
  const paidTotal = live.reduce((total, entry) => total + entry.invoice_paid, 0);
  const overpaidTotal = live.reduce((total, entry) => total + (entry.overpaid_amount || 0), 0);
  const overpaidCount = live.filter((entry) => entry.payment_state === "overpaid").length;
  const unpaidCount = live.filter(
    (entry) => (entry.invoice_paid || 0) <= 0 && (entry.invoice_outstanding || 0) > 0,
  ).length;
  const partialCount = live.filter((entry) => entry.payment_state === "partially_paid").length;
  const locked = editing ? !editing.editable : false;
  const subtotal = draftSubtotal(draft);
  const taxRate = Number(draft.taxRate);
  const tax = draftTax(draft);
  const catalogueRatedLines = draft.lines.filter((line) => line.gst_rate != null).length;
  const total = subtotal + tax;
  const draftReceived = Math.max(0, Number(draft.paymentReceived) || 0);
  const draftOutstanding = Math.max(0, total - draftReceived);
  const draftOverpaid = Math.max(0, draftReceived - total);
  const draftPaymentStatus = paymentStatusFor(total, draftReceived);
  const draftPaymentState =
    draftOverpaid > 0
      ? "overpaid"
      : draftReceived > 0
        ? draftOutstanding > 0
          ? "partially_paid"
          : "paid"
        : "unpaid";
  const payReceived = Math.max(0, Number(payForm.amount) || 0);
  const payRemaining = payTarget
    ? Math.max(0, (payTarget.invoice_outstanding || 0) - payReceived)
    : 0;
  const payExcess = payTarget
    ? Math.max(0, payReceived - (payTarget.invoice_outstanding || 0))
    : 0;
  const payStatus = payTarget
    ? paymentStatusFor(
        payTarget.invoice_total || 0,
        (payTarget.invoice_paid || 0) + payReceived,
      )
    : "UNPAID";
  const payState =
    payStatus === "PAID"
      ? "paid"
      : payStatus === "OVERPAID"
        ? "overpaid"
        : payStatus === "PARTIALLY PAID"
          ? "partially_paid"
          : "unpaid";

  const openCreate = () => {
    setEditing(null);
    setDraft(blankDraft());
    setFormError(null);
    setEditorOpen(true);
  };

  const openEdit = (entry: EmployeeEntry) => {
    setEditing(entry);
    setDraft(draftFromEntry(entry));
    setFormError(null);
    setEditorOpen(true);
  };

  const closeEditor = () => {
    if (saving) return;
    setEditorOpen(false);
    setEditing(null);
  };

  const updateLine = (key: number, patchValue: Partial<InvoiceLineDraft>) => {
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) =>
        line.key === key ? { ...line, ...patchValue } : line,
      ),
    }));
  };

  const pickStockItem = (key: number, item: StockItem) =>
    updateLine(key, {
      description: item.name,
      unit_price: String(item.unit_price),
      product_id: item.id,
      gst_rate: item.gst_rate ?? null,
    });

  const linkStockItem = (key: number, item: StockItem) =>
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) =>
        line.key === key
          ? {
              ...line,
              product_id: item.id,
              gst_rate: item.gst_rate ?? line.gst_rate,
              unit_price: line.unit_price.trim() ? line.unit_price : String(item.unit_price),
            }
          : line,
      ),
    }));

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const usableLines = draft.lines.filter(
      (line) => line.description.trim() && Number(line.quantity) > 0 && Number(line.unit_price) >= 0,
    );
    if (editing && !locked && usableLines.length === 0) {
      setFormError("Add at least one line item with a description, quantity and unit price.");
      return;
    }
    if (draft.dueDate < draft.issueDate) {
      setFormError("Due date cannot be before the issue date.");
      return;
    }
    if (!editing && draftReceived > 0 && !draft.paymentDate) {
      setFormError("Choose the date the payment was received.");
      return;
    }
    if (!editing && draft.paymentReference.trim().length > 120) {
      setFormError("Transaction reference must be 120 characters or fewer.");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        const payload: Record<string, unknown> = { notes: draft.notes.trim() || null };
        if (editing.editable) {
          payload.counterparty = draft.customer.trim();
          payload.description =
            usableLines[0]?.description.trim().slice(0, 255) ||
            `Invoice for ${draft.customer.trim()}`.slice(0, 255);
          payload.entry_date = draft.issueDate;
          payload.due_date = draft.dueDate;
          payload.tax_rate = Number(draft.taxRate);
          payload.items = usableLines.map((line) => ({
            description: line.description.trim(),
            quantity: Number(line.quantity),
            unit_price: Number(line.unit_price),
            product_id: line.product_id,
            gst_rate: line.gst_rate,
          }));
          if (draft.customerEmail.trim()) payload.counterparty_email = draft.customerEmail.trim();
          payload.counterparty_phone = draft.customerPhone.trim() || null;
        }
        const result = await patch<{ entry: EmployeeEntry; message: string }>(
          `/employee/entries/${editing.id}`,
          payload,
        );
        toast({ title: "Invoice updated", description: result.message, tone: "success" });
      } else {
        const payload: Record<string, unknown> = {
          entry_type: "invoice",
          counterparty: draft.customer.trim(),
          description:
            usableLines[0]?.description.trim().slice(0, 255) ||
            `Invoice for ${draft.customer.trim()}`.slice(0, 255),
          payment_method: "credit",
          entry_date: draft.issueDate,
          due_date: draft.dueDate,
          tax_rate: Number(draft.taxRate),
          items: usableLines.map((line) => ({
            description: line.description.trim(),
            quantity: Number(line.quantity),
            unit_price: Number(line.unit_price),
            product_id: line.product_id,
            gst_rate: line.gst_rate,
          })),
          notes: draft.notes.trim() || null,
        };
        if (draftReceived > 0) {
          payload.amount_received = draftReceived;
          payload.payment_method = draft.paymentMode;
          payload.payment_date = draft.paymentDate;
          if (draft.paymentReference.trim()) {
            payload.payment_reference = draft.paymentReference.trim();
          }
        } else {
          payload.payment_method = "credit";
        }
        if (draft.customerEmail.trim()) payload.counterparty_email = draft.customerEmail.trim();
        if (draft.customerPhone.trim()) payload.counterparty_phone = draft.customerPhone.trim();
        const result = await post<{ entry: EmployeeEntry; message: string }>(
          "/employee/entries",
          payload,
        );
        toast({ title: "Invoice generated", description: result.message, tone: "success" });
      }
      setEditorOpen(false);
      setEditing(null);
      invoicesApi.reload();
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const confirmVoid = async () => {
    if (!voidTarget) return;
    setVoiding(true);
    try {
      const result = await post<{ entry: EmployeeEntry; message: string }>(
        `/employee/entries/${voidTarget.id}/void`,
      );
      toast({ title: "Invoice voided", description: result.message, tone: "success" });
      setVoidTarget(null);
      invoicesApi.reload();
    } catch (err) {
      toast({ title: "Could not void invoice", description: getErrorMessage(err), tone: "error" });
    } finally {
      setVoiding(false);
    }
  };

  const openPayment = (entry: EmployeeEntry) => {
    setPayTarget(entry);
    setPayError(null);
    setPayForm({
      amount: entry.invoice_outstanding ? String(entry.invoice_outstanding) : "",
      mode: "upi",
      date: localDate(),
      reference: "",
      note: "",
    });
  };

  const closePayment = () => {
    if (paySaving) return;
    setPayTarget(null);
    setPayError(null);
  };

  const submitPayment = async (event: FormEvent) => {
    event.preventDefault();
    if (!payTarget?.invoice_id) return;
    if (payReceived <= 0) {
      setPayError("Enter a payment amount greater than zero.");
      return;
    }
    if (!payForm.date) {
      setPayError("Choose the date the payment was received.");
      return;
    }
    setPaySaving(true);
    setPayError(null);
    try {
      const result = await post<{ message: string }>(
        `/employee/invoices/${payTarget.invoice_id}/payments`,
        {
          amount: payReceived,
          method: payForm.mode,
          reference: payForm.reference.trim() || undefined,
          note: payForm.note.trim() || undefined,
          received_at: new Date(`${payForm.date}T12:00:00`).toISOString(),
        },
      );
      toast({ title: "Payment recorded", description: result.message, tone: "success" });
      setPayTarget(null);
      invoicesApi.reload();
      if (historyTarget) historyApi.reload();
    } catch (err) {
      setPayError(getErrorMessage(err));
    } finally {
      setPaySaving(false);
    }
  };

  if (invoicesApi.loading && !invoicesApi.data) return <PageSkeleton cards={4} />;
  if (invoicesApi.error && !invoicesApi.data) {
    return <ErrorState message={invoicesApi.error} onRetry={invoicesApi.reload} />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Employee workspace · invoices"
        title="Invoice generation"
        description="Bill a customer with line items and tax. Issuing an invoice creates a receivable; cash updates only when payment is recorded."
        actions={
          <>
            <Button
              variant="outline"
              icon={RefreshCw}
              onClick={invoicesApi.reload}
              loading={invoicesApi.loading}
            >
              Refresh
            </Button>
            <Button icon={FilePlus2} onClick={openCreate}>
              Generate invoice
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Invoiced"
          value={money(invoicedTotal, currency)}
          icon={ReceiptText}
          changeLabel={`${live.length} open or settled invoices`}
          tone="blue"
        />
        <StatCard
          label="Payment received"
          value={money(paidTotal, currency)}
          icon={Wallet}
          changeLabel="Confirmed collections on open invoices"
          tone="green"
        />
        <StatCard
          label="Outstanding"
          value={money(outstandingTotal, currency)}
          icon={Wallet}
          changeLabel={`${unpaidCount} unpaid · ${partialCount} partially paid`}
          tone="amber"
        />
        <StatCard
          label="Overpaid"
          value={money(overpaidTotal, currency)}
          icon={Undo2}
          changeLabel={
            overpaidCount > 0
              ? `${overpaidCount} flagged for owner review`
              : "No customer credit pending"
          }
          tone={overpaidCount > 0 ? "violet" : "slate"}
        />
      </div>

      <Callout tone="blue" title="How invoice cash works">
        Record payments against an invoice with the Pay action. FINOVEXA recalculates the outstanding balance
        and payment status on the server after every entry, allows multiple partial payments, and locks
        financial edits once cash is attached. Overpayments are held as customer credit until the owner
        approves a refund or credit note.
      </Callout>

      <Card>
        <CardHeader
          title="Your invoices"
          description="Invoices you generated for this business. Confirmed payments lock financial edits."
          icon={ReceiptText}
        />
        <div className="mt-3">
          {entries.length === 0 ? (
            <EmptyState
              icon={ReceiptText}
              title="No invoices yet"
              description="Generate an invoice with itemised lines, tax and a due date for the owner's receivables."
              action={
                <Button size="sm" icon={FilePlus2} onClick={openCreate}>
                  Generate the first invoice
                </Button>
              }
            />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Invoice</TH>
                  <TH>Customer</TH>
                  <TH>Issued / due</TH>
                  <TH className="text-right">Total</TH>
                  <TH className="text-right">Outstanding</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {entries.map((entry) => (
                  <TR key={entry.id}>
                    <TD>
                      <span className="font-mono text-[11.5px] font-semibold text-ink-900">
                        {entry.invoice_number || entry.reference}
                      </span>
                      <p className="mt-0.5 text-[10px] text-slate-400">
                        {entry.items.length} line {entry.items.length === 1 ? "item" : "items"} ·{" "}
                        {formatDateTime(entry.created_at)}
                      </p>
                    </TD>
                    <TD>
                      <p className="text-[12px] font-medium text-ink-900">{entry.counterparty}</p>
                      {(entry.counterparty_email || entry.counterparty_phone) && (
                        <p className="max-w-[220px] truncate text-[10px] text-slate-500">
                          {[entry.counterparty_email, entry.counterparty_phone].filter(Boolean).join(" · ")}
                        </p>
                      )}
                      <p className="max-w-[220px] truncate text-[10px] text-slate-400">
                        {entry.description}
                      </p>
                    </TD>
                    <TD>
                      <p className="text-[11px] text-slate-600">{formatDate(entry.entry_date)}</p>
                      <p className="text-[10px] text-slate-400">
                        Due {entry.due_date ? formatDate(entry.due_date) : "—"}
                      </p>
                    </TD>
                    <TD className="text-right">
                      <span className="text-[12px] font-semibold tabular-nums text-ink-900">
                        {money(entry.invoice_total ?? entry.amount, entry.currency || currency)}
                      </span>
                      <p className="text-[10px] text-emerald-600">
                        {money(entry.invoice_paid, entry.currency || currency)} received
                      </p>
                    </TD>
                    <TD className="text-right">
                      <span className="text-[12px] font-semibold tabular-nums text-ink-900">
                        {entry.status === "void"
                          ? "—"
                          : money(entry.invoice_outstanding || 0, entry.currency || currency)}
                      </span>
                      {entry.status !== "void" && (entry.overpaid_amount || 0) > 0 && (
                        <p className="text-[10px] font-medium text-violet-600">
                          Overpaid {money(entry.overpaid_amount, entry.currency || currency)}
                        </p>
                      )}
                    </TD>
                    <TD>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {entry.status === "void" ? (
                          <Badge tone="slate">VOID</Badge>
                        ) : (
                          <Badge tone={paymentTone(entry.payment_state)}>
                            {entry.payment_status_label || "UNPAID"}
                          </Badge>
                        )}
                        {entry.status !== "void" && !entry.editable && (
                          <Badge tone="amber" dot title={entry.lock_reason || undefined}>
                            Locked
                          </Badge>
                        )}
                      </div>
                      {entry.status !== "void" && entry.payment_count > 0 && (
                        <p className="mt-1 max-w-[200px] truncate text-[10px] text-slate-500">
                          {[
                            entry.payment_method_label,
                            entry.payment_reference,
                            entry.payment_count > 1 ? `${entry.payment_count} payments` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      )}
                      {entry.status !== "void" && entry.lock_reason && (
                        <p className="mt-1 max-w-[200px] text-[10px] leading-relaxed text-amber-700">
                          {entry.lock_reason}
                        </p>
                      )}
                    </TD>
                    <TD className="text-right">
                      <div className="inline-flex flex-wrap items-center justify-end gap-1.5">
                        {entry.status !== "void" && (entry.invoice_outstanding || 0) > 0 && (
                          <Button
                            size="sm"
                            icon={Plus}
                            onClick={() => openPayment(entry)}
                            title="Record a customer payment"
                          >
                            Pay
                          </Button>
                        )}
                        {entry.status !== "void" && entry.payment_count > 0 && (
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={History}
                            onClick={() => setHistoryTarget(entry)}
                            title="View payment history"
                          >
                            History
                          </Button>
                        )}
                        {entry.status !== "void" && (
                          <Button
                            variant="outline"
                            size="sm"
                            icon={entry.editable ? Pencil : Lock}
                            onClick={() => openEdit(entry)}
                            title={entry.lock_reason || "Edit invoice"}
                          >
                            {entry.editable ? "Edit" : "Notes"}
                          </Button>
                        )}
                        {entry.status !== "void" && entry.voidable && (
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={Undo2}
                            onClick={() => setVoidTarget(entry)}
                          >
                            Void
                          </Button>
                        )}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </div>
      </Card>

      <Modal
        open={editorOpen}
        onClose={closeEditor}
        title={editing ? `Edit ${editing.invoice_number || editing.reference}` : "Generate invoice"}
        description={
          locked
            ? "Confirmed cash is attached to this invoice. Only the note can be changed."
            : "Line-item invoice for a customer. Tax is calculated on the subtotal."
        }
        size="xl"
        footer={
          <>
            <Button variant="outline" onClick={closeEditor} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" form="invoice-form" loading={saving}>
              {editing ? "Save invoice" : "Generate invoice"}
            </Button>
          </>
        }
      >
        <form id="invoice-form" className="space-y-4" onSubmit={save}>
          {locked && (
            <Callout tone="amber" title="Financial fields locked" icon={Lock}>
              {editing?.lock_reason} You can still update the note for the owner.
            </Callout>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Customer" htmlFor="invoice-customer" required>
              <Input
                id="invoice-customer"
                value={draft.customer}
                onChange={(event) => setDraft({ ...draft, customer: event.target.value })}
                placeholder="Customer or company name"
                minLength={2}
                required
                disabled={locked}
              />
            </Field>
            <Field label="Customer email" htmlFor="invoice-email" hint="Optional; used for the owner's reminders.">
              <Input
                id="invoice-email"
                type="email"
                value={draft.customerEmail}
                onChange={(event) => setDraft({ ...draft, customerEmail: event.target.value })}
                placeholder={editing ? "Leave blank to keep the current email" : "customer@example.com"}
                disabled={locked}
              />
            </Field>
            <Field label="Customer mobile" htmlFor="invoice-phone" hint="Optional; used for payment reminders by SMS.">
              <Input
                id="invoice-phone"
                type="tel"
                value={draft.customerPhone}
                onChange={(event) => setDraft({ ...draft, customerPhone: event.target.value })}
                placeholder="98765 43210"
                disabled={locked}
              />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Issue date" htmlFor="invoice-issue" required>
              <Input
                id="invoice-issue"
                type="date"
                value={draft.issueDate}
                onChange={(event) => setDraft({ ...draft, issueDate: event.target.value })}
                required
                disabled={locked}
              />
            </Field>
            <Field label="Due date" htmlFor="invoice-due" required>
              <Input
                id="invoice-due"
                type="date"
                value={draft.dueDate}
                min={draft.issueDate}
                onChange={(event) => setDraft({ ...draft, dueDate: event.target.value })}
                required
                disabled={locked}
              />
            </Field>
            <Field
              label="Default GST %"
              htmlFor="invoice-tax"
              hint="Applies to free-text lines. Catalogue items use their saved GST rate."
            >
              <Input
                id="invoice-tax"
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={draft.taxRate}
                onChange={(event) => setDraft({ ...draft, taxRate: event.target.value })}
                disabled={locked}
              />
            </Field>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <div>
                <p className="text-[12px] font-semibold text-ink-900">Line items</p>
                <p className="text-[10.5px] text-slate-500">
                  Type an item name to pick it from stock — the price and saved GST rate fill in, and
                  its catalogue quantity reduces when the invoice is issued.
                </p>
              </div>
              {!locked && (
                <Button
                  variant="outline"
                  size="sm"
                  icon={Plus}
                  onClick={() =>
                    setDraft((current) => ({ ...current, lines: [...current.lines, newLine()] }))
                  }
                >
                  Add line
                </Button>
              )}
            </div>
            <div className="space-y-2">
              {draft.lines.map((line, index) => (
                <div
                  key={line.key}
                  className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50/60 p-2.5 sm:grid-cols-[minmax(0,1fr)_90px_130px_120px_36px]"
                >
                  <StockItemCombobox
                    value={line.description}
                    onValueChange={(description) =>
                      updateLine(line.key, { description, product_id: null, gst_rate: null })
                    }
                    onPick={(item) => pickStockItem(line.key, item)}
                    onExactMatch={(item) => linkStockItem(line.key, item)}
                    placeholder={`Item ${index + 1} — type to search stock`}
                    ariaLabel={`Line ${index + 1} description`}
                    disabled={locked}
                    currency={currency}
                  />
                  <Input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={line.quantity}
                    onChange={(event) => updateLine(line.key, { quantity: event.target.value })}
                    placeholder="Qty"
                    aria-label={`Line ${index + 1} quantity`}
                    disabled={locked}
                  />
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.unit_price}
                    onChange={(event) => updateLine(line.key, { unit_price: event.target.value })}
                    placeholder="Unit price"
                    aria-label={`Line ${index + 1} unit price`}
                    disabled={locked}
                  />
                  <div className="flex flex-col items-end justify-center px-2 text-right text-[12px] font-semibold tabular-nums text-ink-900">
                    <span>
                      {money(
                        Math.max(0, Number(line.quantity) || 0) * Math.max(0, Number(line.unit_price) || 0),
                        currency,
                      )}
                    </span>
                    <span className="text-[10px] font-normal text-slate-400">
                      GST {lineGstRate(line, taxRate)}%
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    icon={Trash2}
                    aria-label={`Remove line ${index + 1}`}
                    onClick={() =>
                      setDraft((current) => ({
                        ...current,
                        lines:
                          current.lines.length > 1
                            ? current.lines.filter((item) => item.key !== line.key)
                            : current.lines,
                      }))
                    }
                    disabled={locked || draft.lines.length <= 1}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="ml-auto max-w-xs space-y-1 text-[12px]">
              <div className="flex justify-between text-slate-500">
                <span>Subtotal</span>
                <span className="font-semibold tabular-nums text-ink-900">{money(subtotal, currency)}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>
                  GST
                  {catalogueRatedLines > 0
                    ? ` (${catalogueRatedLines} catalogue line${catalogueRatedLines === 1 ? "" : "s"})`
                    : ` (${Number.isFinite(taxRate) ? taxRate : 0}%)`}
                </span>
                <span className="font-semibold tabular-nums text-ink-900">{money(tax, currency)}</span>
              </div>
              <div className="flex justify-between border-t border-slate-100 pt-1 text-[13px] font-semibold text-ink-900">
                <span>Invoice total</span>
                <span className="tabular-nums">{money(total, currency)}</span>
              </div>
            </div>
          </div>

          {!editing && (
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-[12px] font-semibold text-ink-900">Payment received</p>
                  <p className="text-[10.5px] text-slate-500">
                    Optional first instalment. Outstanding and payment status are calculated on the server.
                  </p>
                </div>
                <Badge tone={paymentTone(draftPaymentState)}>{draftPaymentStatus}</Badge>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <Field label="Total invoice amount" htmlFor="invoice-total-readonly">
                  <Input
                    id="invoice-total-readonly"
                    value={money(total, currency)}
                    readOnly
                    disabled
                    tabIndex={-1}
                  />
                </Field>
                <Field
                  label="Payment received"
                  htmlFor="invoice-payment-received"
                  hint="Leave blank when the customer has not paid yet."
                >
                  <Input
                    id="invoice-payment-received"
                    type="number"
                    min="0"
                    step="0.01"
                    value={draft.paymentReceived}
                    onChange={(event) =>
                      setDraft({ ...draft, paymentReceived: event.target.value })
                    }
                    placeholder="0.00"
                  />
                </Field>
                <Field label="Remaining balance" htmlFor="invoice-balance-readonly">
                  <Input
                    id="invoice-balance-readonly"
                    value={draftOverpaid > 0 ? money(0, currency) : money(draftOutstanding, currency)}
                    readOnly
                    disabled
                    tabIndex={-1}
                  />
                </Field>
                <Field label="Payment mode" htmlFor="invoice-payment-mode">
                  <Select
                    id="invoice-payment-mode"
                    value={draft.paymentMode}
                    onChange={(event) => setDraft({ ...draft, paymentMode: event.target.value })}
                    disabled={draftReceived <= 0}
                  >
                    {PAYMENT_MODES.map((mode) => (
                      <option key={mode.value} value={mode.value}>
                        {mode.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Payment date" htmlFor="invoice-payment-date">
                  <Input
                    id="invoice-payment-date"
                    type="date"
                    value={draft.paymentDate}
                    max={localDate()}
                    onChange={(event) => setDraft({ ...draft, paymentDate: event.target.value })}
                    disabled={draftReceived <= 0}
                  />
                </Field>
                <Field
                  label="Transaction reference"
                  htmlFor="invoice-payment-reference"
                  hint="Optional UPI, cheque or bank reference."
                >
                  <Input
                    id="invoice-payment-reference"
                    value={draft.paymentReference}
                    onChange={(event) =>
                      setDraft({ ...draft, paymentReference: event.target.value })
                    }
                    placeholder="UTR / cheque number"
                    maxLength={120}
                    disabled={draftReceived <= 0}
                  />
                </Field>
              </div>
              {draftOverpaid > 0 && (
                <div className="mt-3">
                  <Callout tone="amber" title="Customer credit pending">
                    This payment exceeds the invoice total by {money(draftOverpaid, currency)}. The invoice
                    will be marked OVERPAID and held as customer credit until the owner approves a refund or
                    credit note.
                  </Callout>
                </div>
              )}
            </div>
          )}

          <Field label="Notes" htmlFor="invoice-notes" hint="Visible to the owner on the invoice record.">
            <Textarea
              id="invoice-notes"
              value={draft.notes}
              onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
              placeholder="Payment terms, purchase order reference or delivery details."
            />
          </Field>

          {formError && (
            <Callout tone="red" title="Invoice not saved">
              {formError}
            </Callout>
          )}
        </form>
      </Modal>

      <Modal
        open={payTarget !== null}
        onClose={closePayment}
        title={
          payTarget
            ? `Record payment · ${payTarget.invoice_number || payTarget.reference}`
            : "Record payment"
        }
        description={
          payTarget
            ? `${payTarget.counterparty} · outstanding ${money(
                payTarget.invoice_outstanding || 0,
                payTarget.currency || currency,
              )}`
            : undefined
        }
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={closePayment} disabled={paySaving}>
              Cancel
            </Button>
            <Button type="submit" form="payment-form" loading={paySaving}>
              Record payment
            </Button>
          </>
        }
      >
        <form id="payment-form" className="space-y-4" onSubmit={submitPayment}>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Invoice total
              </p>
              <p className="mt-1 text-[15px] font-semibold tabular-nums text-ink-900">
                {money(payTarget?.invoice_total || 0, currency)}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Already received
              </p>
              <p className="mt-1 text-[15px] font-semibold tabular-nums text-emerald-600">
                {money(payTarget?.invoice_paid || 0, currency)}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Outstanding now
              </p>
              <p className="mt-1 text-[15px] font-semibold tabular-nums text-amber-600">
                {money(payTarget?.invoice_outstanding || 0, currency)}
              </p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Payment received" htmlFor="payment-amount" required>
              <Input
                id="payment-amount"
                type="number"
                min="0.01"
                step="0.01"
                value={payForm.amount}
                onChange={(event) => setPayForm({ ...payForm, amount: event.target.value })}
                placeholder="0.00"
                autoFocus
                required
              />
            </Field>
            <Field label="Payment mode" htmlFor="payment-mode" required>
              <Select
                id="payment-mode"
                value={payForm.mode}
                onChange={(event) => setPayForm({ ...payForm, mode: event.target.value })}
              >
                {PAYMENT_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Payment date" htmlFor="payment-date" required>
              <Input
                id="payment-date"
                type="date"
                value={payForm.date}
                max={localDate()}
                onChange={(event) => setPayForm({ ...payForm, date: event.target.value })}
                required
              />
            </Field>
            <Field
              label="Transaction reference"
              htmlFor="payment-reference"
              hint="Optional UPI, cheque or bank reference."
            >
              <Input
                id="payment-reference"
                value={payForm.reference}
                onChange={(event) => setPayForm({ ...payForm, reference: event.target.value })}
                placeholder="UTR / cheque number"
                maxLength={120}
              />
            </Field>
          </div>

          <Field
            label="Note"
            htmlFor="payment-note"
            hint="Optional; kept in the owner's audit trail."
          >
            <Textarea
              id="payment-note"
              value={payForm.note}
              onChange={(event) => setPayForm({ ...payForm, note: event.target.value })}
              placeholder="Collected at the counter, balance promised next week, etc."
              maxLength={500}
            />
          </Field>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-[12px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Remaining after this payment</span>
              <span className="font-semibold tabular-nums text-ink-900">
                {money(payExcess > 0 ? 0 : payRemaining, currency)}
              </span>
            </div>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-slate-500">Payment status</span>
              <Badge tone={paymentTone(payState)}>{payStatus}</Badge>
            </div>
          </div>

          {payExcess > 0 && (
            <Callout tone="amber" title="Amount exceeds the balance">
              This is {money(payExcess, currency)} more than the outstanding balance. It will still be
              recorded, the invoice will show OVERPAID, and the excess is flagged for the owner as customer
              credit or refund.
            </Callout>
          )}

          {payError && (
            <Callout tone="red" title="Payment not recorded">
              {payError}
            </Callout>
          )}
        </form>
      </Modal>

      <Modal
        open={historyTarget !== null}
        onClose={() => setHistoryTarget(null)}
        title={
          historyTarget
            ? `Payment history · ${historyTarget.invoice_number || historyTarget.reference}`
            : "Payment history"
        }
        description="Every payment recorded against this invoice, newest first."
        size="lg"
        footer={
          <Button variant="outline" onClick={() => setHistoryTarget(null)}>
            Close
          </Button>
        }
      >
        {historyApi.loading && !historyApi.data ? (
          <p className="py-6 text-center text-[12px] text-slate-500">Loading payments…</p>
        ) : historyApi.error ? (
          <Callout tone="red" title="Could not load payment history">
            {historyApi.error}
          </Callout>
        ) : historyApi.data ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                  Invoice total
                </p>
                <p className="mt-1 text-[14px] font-semibold tabular-nums text-ink-900">
                  {money(historyApi.data.total, historyApi.data.payment_history[0]?.currency || currency)}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                  Amount received
                </p>
                <p className="mt-1 text-[14px] font-semibold tabular-nums text-emerald-600">
                  {money(historyApi.data.amount_received, historyApi.data.payment_history[0]?.currency || currency)}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                  Outstanding
                </p>
                <p className="mt-1 text-[14px] font-semibold tabular-nums text-amber-600">
                  {money(historyApi.data.outstanding, historyApi.data.payment_history[0]?.currency || currency)}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                  Payment status
                </p>
                <p className="mt-1.5">
                  <Badge
                    tone={paymentTone(
                      historyApi.data.payment_status_label === "PAID"
                        ? "paid"
                        : historyApi.data.payment_status_label === "OVERPAID"
                          ? "overpaid"
                          : historyApi.data.payment_status_label === "PARTIALLY PAID"
                            ? "partially_paid"
                            : "unpaid",
                    )}
                  >
                    {historyApi.data.payment_status_label}
                  </Badge>
                </p>
              </div>
            </div>

            {historyApi.data.payment_history.length === 0 ? (
              <EmptyState
                icon={History}
                title="No payments recorded"
                description="Payments recorded against this invoice will appear here with their mode, reference and amount."
              />
            ) : (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Date</TH>
                    <TH>Mode</TH>
                    <TH>Reference</TH>
                    <TH>Recorded by</TH>
                    <TH className="text-right">Amount</TH>
                    <TH>Status</TH>
                  </TR>
                </THead>
                <TBody>
                  {historyApi.data.payment_history.map((payment) => (
                    <TR key={payment.id}>
                      <TD>
                        <span className="text-[11px] text-slate-600">
                          {formatDate(payment.received_at || payment.created_at)}
                        </span>
                      </TD>
                      <TD>
                        <span className="text-[11px] font-medium text-ink-900">
                          {payment.method_label || payment.method}
                        </span>
                      </TD>
                      <TD>
                        <span className="font-mono text-[10.5px] text-slate-500">
                          {payment.reference || "—"}
                        </span>
                      </TD>
                      <TD>
                        <span className="text-[11px] text-slate-600">
                          {payment.recorded_by?.name || "—"}
                        </span>
                      </TD>
                      <TD className="text-right">
                        <span className="text-[11.5px] font-semibold tabular-nums text-ink-900">
                          {money(payment.amount, payment.currency || currency)}
                        </span>
                      </TD>
                      <TD>
                        <Badge tone={payment.status === "reversed" ? "red" : "green"}>
                          {payment.status === "reversed" ? "REVERSED" : "CONFIRMED"}
                        </Badge>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            )}
          </div>
        ) : null}
      </Modal>

      <ConfirmDialog
        open={voidTarget !== null}
        onClose={() => setVoidTarget(null)}
        onConfirm={() => void confirmVoid()}
        title="Void this invoice?"
        description={
          voidTarget
            ? `${voidTarget.invoice_number || voidTarget.reference} · ${voidTarget.counterparty} · ${money(
                voidTarget.invoice_total ?? voidTarget.amount,
                voidTarget.currency || currency,
              )}. The owner will see it as void and it will no longer be collectible.`
            : undefined
        }
        confirmLabel="Void invoice"
        tone="danger"
        loading={voiding}
      />
    </div>
  );
}
