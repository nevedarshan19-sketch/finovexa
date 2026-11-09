import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, IndianRupee, Plus, ReceiptIndianRupee } from "lucide-react";
import { get, getErrorMessage, post } from "../../lib/api";
import type { AccountingClient, ServiceInvoice } from "../../lib/accountingTypes";
import { PAYMENT_METHODS, labelize } from "../../lib/accounting";
import { formatDate, money } from "../../lib/utils";
import {
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

interface Receivables {
  invoiced: number;
  paid: number;
  outstanding: number;
  overdue: number;
  overdue_count: number;
  invoice_count: number;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

export function AccountantBillingPage() {
  const [invoices, setInvoices] = useState<ServiceInvoice[]>([]);
  const [totals, setTotals] = useState<Receivables | null>(null);
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [busy, setBusy] = useState(false);

  const [invoiceOpen, setInvoiceOpen] = useState(false);
  const [invoiceForm, setInvoiceForm] = useState({
    client_id: "",
    issue_date: today(),
    due_date: addDays(today(), 15),
    period_label: "",
    subtotal: "",
    tax_rate: "18",
    notes: "",
  });

  const [paymentFor, setPaymentFor] = useState<ServiceInvoice | null>(null);
  const [paymentForm, setPaymentForm] = useState({
    amount: "",
    method: "bank",
    reference: "",
    received_on: today(),
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (clientFilter) params.set("client_id", clientFilter);
      const suffix = params.toString();
      const data = await get<{ items: ServiceInvoice[]; totals: Receivables }>(
        `/accounting/senior/invoices${suffix ? `?${suffix}` : ""}`,
      );
      setInvoices(data.items);
      setTotals(data.totals);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [status, clientFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    get<{ items: AccountingClient[] }>("/accounting/senior/clients")
      .then((data) => setClients(data.items))
      .catch(() => setClients([]));
  }, []);

  const createInvoice = async () => {
    setBusy(true);
    setActionError(null);
    try {
      await post<ServiceInvoice>("/accounting/senior/invoices", {
        client_id: Number(invoiceForm.client_id),
        issue_date: invoiceForm.issue_date,
        due_date: invoiceForm.due_date,
        period_label: invoiceForm.period_label || null,
        subtotal: invoiceForm.subtotal,
        tax_rate: invoiceForm.tax_rate,
        notes: invoiceForm.notes || null,
      });
      setInvoiceOpen(false);
      setInvoiceForm({
        client_id: invoiceForm.client_id,
        issue_date: today(),
        due_date: addDays(today(), 15),
        period_label: "",
        subtotal: "",
        tax_rate: "18",
        notes: "",
      });
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const recordPayment = async () => {
    if (!paymentFor) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/senior/invoices/${paymentFor.id}/payments`, {
        amount: paymentForm.amount,
        method: paymentForm.method,
        reference: paymentForm.reference || null,
        received_on: paymentForm.received_on,
      });
      setPaymentFor(null);
      setPaymentForm({ amount: "", method: "bank", reference: "", received_on: today() });
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading && invoices.length === 0) return <PageSkeleton cards={4} />;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Practice fees"
        title="Billing and collections"
        description="Issue engagement invoices and record the payments received against them."
        actions={
          <Button icon={Plus} onClick={() => setInvoiceOpen(true)}>
            Issue invoice
          </Button>
        }
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      {totals && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Invoiced" value={money(totals.invoiced)} icon={ReceiptIndianRupee} tone="blue" sub={`${totals.invoice_count} invoices`} />
          <StatCard label="Collected" value={money(totals.paid)} icon={CheckCircle2} tone="green" />
          <StatCard label="Outstanding" value={money(totals.outstanding)} icon={IndianRupee} tone="amber" />
          <StatCard
            label="Overdue"
            value={money(totals.overdue)}
            icon={IndianRupee}
            tone="red"
            sub={`${totals.overdue_count} past due`}
          />
        </div>
      )}

      <Card className="overflow-hidden">
        <CardHeader
          title="Invoices"
          description="Fees billed to clients for the accounting engagement."
          icon={ReceiptIndianRupee}
          actions={
            <>
              <Select
                aria-label="Invoice status"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="h-8 min-w-[140px] text-[11px]"
              >
                <option value="">All statuses</option>
                {["issued", "part_paid", "paid", "void"].map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Client"
                value={clientFilter}
                onChange={(event) => setClientFilter(event.target.value)}
                className="h-8 min-w-[180px] text-[11px]"
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
          ) : invoices.length === 0 ? (
            <EmptyState title="No invoices" description="Issue a fee invoice for an onboarded client." icon={ReceiptIndianRupee} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head">Invoice</th>
                    <th className="table-head">Client</th>
                    <th className="table-head">Issued</th>
                    <th className="table-head">Due</th>
                    <th className="table-head">Total</th>
                    <th className="table-head">Paid</th>
                    <th className="table-head">Outstanding</th>
                    <th className="table-head">Status</th>
                    <th className="table-head"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {invoices.map((invoice) => (
                    <tr key={invoice.id} className="row-hover">
                      <td className="table-cell">
                        <p className="text-[12px] font-semibold text-ink-900">{invoice.number}</p>
                        <p className="text-[10px] text-slate-500">{invoice.period_label || "—"}</p>
                      </td>
                      <td className="table-cell text-[11px] text-slate-600">{invoice.client_name}</td>
                      <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">{formatDate(invoice.issue_date)}</td>
                      <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">{formatDate(invoice.due_date)}</td>
                      <td className="table-cell tabular text-[11px]">{money(invoice.total_amount)}</td>
                      <td className="table-cell tabular text-[11px]">{money(invoice.paid_amount)}</td>
                      <td className="table-cell tabular text-[11px] font-semibold">
                        {money(invoice.outstanding_amount)}
                      </td>
                      <td className="table-cell">
                        <StatusBadge status={invoice.is_overdue ? "overdue" : invoice.status} />
                      </td>
                      <td className="table-cell">
                        {invoice.outstanding_amount > 0 && invoice.status !== "void" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setPaymentFor(invoice);
                              setPaymentForm({
                                amount: String(invoice.outstanding_amount),
                                method: "bank",
                                reference: "",
                                received_on: today(),
                              });
                            }}
                          >
                            Record payment
                          </Button>
                        ) : (
                          <span className="text-[10px] text-slate-400">
                            {invoice.payments.length} payment{invoice.payments.length === 1 ? "" : "s"}
                          </span>
                        )}
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
        open={invoiceOpen}
        onClose={() => setInvoiceOpen(false)}
        title="Issue a fee invoice"
        description="GST is calculated on the subtotal at the selected rate."
        footer={
          <>
            <Button variant="outline" onClick={() => setInvoiceOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={createInvoice}
              disabled={!invoiceForm.client_id || !invoiceForm.subtotal}
            >
              Issue invoice
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Client" htmlFor="invoice_client" required>
            <Select
              id="invoice_client"
              value={invoiceForm.client_id}
              onChange={(event) => setInvoiceForm({ ...invoiceForm, client_id: event.target.value })}
            >
              <option value="">Select a client</option>
              {clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.business_name} · {client.code}
                </option>
              ))}
            </Select>
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Issue date" htmlFor="invoice_issue" required>
              <Input
                id="invoice_issue"
                type="date"
                value={invoiceForm.issue_date}
                onChange={(event) => setInvoiceForm({ ...invoiceForm, issue_date: event.target.value })}
              />
            </Field>
            <Field label="Due date" htmlFor="invoice_due" required>
              <Input
                id="invoice_due"
                type="date"
                value={invoiceForm.due_date}
                onChange={(event) => setInvoiceForm({ ...invoiceForm, due_date: event.target.value })}
              />
            </Field>
            <Field label="Fee subtotal (INR)" htmlFor="invoice_subtotal" required>
              <Input
                id="invoice_subtotal"
                type="number"
                min="1"
                step="0.01"
                value={invoiceForm.subtotal}
                onChange={(event) => setInvoiceForm({ ...invoiceForm, subtotal: event.target.value })}
              />
            </Field>
            <Field label="GST rate %" htmlFor="invoice_tax_rate">
              <Input
                id="invoice_tax_rate"
                type="number"
                min="0"
                max="28"
                step="0.01"
                value={invoiceForm.tax_rate}
                onChange={(event) => setInvoiceForm({ ...invoiceForm, tax_rate: event.target.value })}
              />
            </Field>
            <Field label="Period label" htmlFor="invoice_period">
              <Input
                id="invoice_period"
                value={invoiceForm.period_label}
                onChange={(event) => setInvoiceForm({ ...invoiceForm, period_label: event.target.value })}
                placeholder="October 2026"
              />
            </Field>
          </div>
          <Field label="Notes" htmlFor="invoice_notes">
            <Textarea
              id="invoice_notes"
              value={invoiceForm.notes}
              onChange={(event) => setInvoiceForm({ ...invoiceForm, notes: event.target.value })}
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(paymentFor)}
        onClose={() => setPaymentFor(null)}
        title="Record a payment"
        description={paymentFor ? `${paymentFor.number} · outstanding ${money(paymentFor.outstanding_amount)}` : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setPaymentFor(null)}>
              Cancel
            </Button>
            <Button loading={busy} onClick={recordPayment} disabled={!paymentForm.amount}>
              Record payment
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Amount (INR)" htmlFor="payment_amount" required>
            <Input
              id="payment_amount"
              type="number"
              min="0.01"
              step="0.01"
              value={paymentForm.amount}
              onChange={(event) => setPaymentForm({ ...paymentForm, amount: event.target.value })}
            />
          </Field>
          <Field label="Method" htmlFor="payment_method">
            <Select
              id="payment_method"
              value={paymentForm.method}
              onChange={(event) => setPaymentForm({ ...paymentForm, method: event.target.value })}
            >
              {PAYMENT_METHODS.map((value) => (
                <option key={value} value={value}>
                  {labelize(value)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Received on" htmlFor="payment_date" required>
            <Input
              id="payment_date"
              type="date"
              value={paymentForm.received_on}
              onChange={(event) => setPaymentForm({ ...paymentForm, received_on: event.target.value })}
            />
          </Field>
          <Field label="Reference" htmlFor="payment_reference" hint="Bank reference or receipt number.">
            <Input
              id="payment_reference"
              value={paymentForm.reference}
              onChange={(event) => setPaymentForm({ ...paymentForm, reference: event.target.value })}
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
