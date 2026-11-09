import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CreditCard,
  Download,
  IndianRupee,
  Info,
  Pencil,
  Percent,
  Plus,
  Printer,
  ReceiptText,
  RefreshCw,
  Search,
  ShieldCheck,
  Wallet,
  FileText,
  Boxes,
} from "lucide-react";
import { api, downloadFile, getErrorMessage, post, put } from "../lib/api";
import type {
  BillingBusiness,
  BillingCustomer,
  BillingOverview,
  BillingProduct,
  BillingSettings,
  GSTRate,
  Invoice,
  PaymentOverview,
} from "../lib/types";
import { formatDate, moneyExact, number as formatNumber, titleCase } from "../lib/utils";
import { useApi } from "../hooks/useApi";
import { useToast } from "../context/ToastContext";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
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
  Tabs,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Textarea,
} from "../components/ui";
import { StatusBadge } from "../components/DataMode";
import { InvoiceDocument, printInvoiceDocument } from "../components/InvoiceDocument";
import { InvoiceEditor } from "../components/billing/InvoiceEditor";
import { CheckoutModal } from "./PaymentsPage";

type Tab = "invoices" | "catalogue" | "setup";

const INVOICE_STATUSES = [
  { value: "all", label: "All invoices" },
  { value: "draft", label: "Drafts" },
  { value: "issued", label: "Issued" },
  { value: "partially_paid", label: "Partially paid" },
  { value: "paid", label: "Paid" },
  { value: "overdue", label: "Overdue" },
  { value: "outstanding", label: "Outstanding" },
  { value: "void", label: "Void" },
];

interface ProductForm {
  sku: string;
  name: string;
  description: string;
  hsn_sac: string;
  item_type: "goods" | "services";
  unit: string;
  default_gst_rate: string;
  unit_price: string;
  unit_cost: string;
  reorder_level: string;
}

const EMPTY_PRODUCT: ProductForm = {
  sku: "",
  name: "",
  description: "",
  hsn_sac: "",
  item_type: "goods",
  unit: "pcs",
  default_gst_rate: "18",
  unit_price: "0",
  unit_cost: "0",
  reorder_level: "0",
};

function productToForm(product: BillingProduct): ProductForm {
  return {
    sku: product.sku,
    name: product.name,
    description: product.description ?? "",
    hsn_sac: product.hsn_sac ?? "",
    item_type: product.item_type,
    unit: product.unit,
    default_gst_rate: String(product.default_gst_rate),
    unit_price: String(product.unit_price),
    unit_cost: String(product.unit_cost),
    reorder_level: String(product.reorder_level),
  };
}

function supplyBadge(supplyType: Invoice["supply_type"]): {
  label: string;
  tone: "blue" | "violet" | "amber";
  title: string;
} {
  if (supplyType === "inter_state") {
    return { label: "IGST", tone: "violet", title: "Inter-state supply (IGST)" };
  }
  if (supplyType === "intra_state") {
    return { label: "CGST + SGST", tone: "blue", title: "Intra-state supply (CGST + SGST)" };
  }
  return {
    label: "GST not split",
    tone: "amber",
    title: "Supplier state or place of supply was never verified, so CGST/SGST and IGST are not allocated.",
  };
}

function InvoiceRow({
  invoice,
  currency,
  onView,
  onEdit,
}: {
  invoice: Invoice;
  currency: string;
  onView: () => void;
  onEdit: () => void;
}) {
  const gst = invoice.tax ?? (invoice.cgst ?? 0) + (invoice.sgst ?? 0) + (invoice.igst ?? 0);
  const supply = supplyBadge(invoice.supply_type);
  return (
    <div className="flex flex-col gap-3 border-b border-slate-100 px-4 py-3 last:border-0 sm:flex-row sm:items-center sm:px-5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12px] font-semibold text-ink-900">{invoice.number}</span>
          <StatusBadge status={invoice.status} />
          {invoice.base_status === "draft" && <Badge tone="slate">Draft</Badge>}
          {invoice.supply_type && (
            <Badge tone={supply.tone} title={supply.title}>
              {supply.label}
            </Badge>
          )}
        </div>
        <button type="button" onClick={onView} className="mt-0.5 block max-w-full truncate text-left text-[12px] font-medium text-slate-700 hover:text-brand-700">
          {invoice.customer.name}
          {invoice.customer.company ? ` · ${invoice.customer.company}` : ""}
        </button>
        <p className="text-[10px] text-slate-400">
          Issued {formatDate(invoice.issue_date)} · Due {formatDate(invoice.due_date)} · GST{" "}
          {moneyExact(gst, currency)}
        </p>
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <div className="text-right">
          <p className="text-[13px] font-semibold text-ink-900">{moneyExact(invoice.total, currency)}</p>
          <p className="text-[10px] text-slate-400">
            {invoice.outstanding > 0 ? `${moneyExact(invoice.outstanding, currency)} outstanding` : "settled"}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="outline" size="sm" icon={FileText} onClick={onView}>
            View
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={Pencil}
            onClick={onEdit}
            disabled={invoice.base_status === "void"}
            aria-label={`Edit ${invoice.number}`}
          >
            Edit
          </Button>
        </div>
      </div>
    </div>
  );
}

function PaymentModal({
  invoice,
  currency,
  onClose,
  onDone,
}: {
  invoice: Invoice;
  currency: string;
  onClose: () => void;
  onDone: (invoice: Invoice) => void;
}) {
  const { toast } = useToast();
  const [amount, setAmount] = useState(String(invoice.outstanding));
  const [method, setMethod] = useState<"bank" | "upi" | "cash" | "card" | "other">("bank");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const response = await post<{ invoice: Invoice; message: string }>(
        `/invoices/${invoice.id}/payments`,
        {
          amount: Number(amount),
          method,
          reference: reference.trim() || null,
          note: note.trim() || null,
        },
      );
      toast({
        tone: "success",
        title: "Payment recorded",
        description: response.message,
      });
      onDone(response.invoice);
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
      title={`Record payment for ${invoice.number}`}
      description={`${invoice.customer.name} · ${moneyExact(invoice.outstanding, currency)} outstanding`}
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy} icon={CheckCircle2}>
            Record confirmed payment
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Callout tone="amber" title="Record only verified receipts" icon={AlertTriangle}>
          This entry is marked as confirmed from owner-provided evidence. Check the bank, UPI or
          cash receipt first. Recording a payment does not move money.
        </Callout>
        {error && (
          <Callout tone="red" title="Payment not recorded" icon={AlertTriangle}>
            {error}
          </Callout>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Amount">
            <Input
              type="number"
              min="0.01"
              step="0.01"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </Field>
          <Field label="Method">
            <Select value={method} onChange={(event) => setMethod(event.target.value as typeof method)}>
              <option value="bank">Bank transfer</option>
              <option value="upi">UPI</option>
              <option value="cash">Cash</option>
              <option value="card">Card</option>
              <option value="other">Other</option>
            </Select>
          </Field>
        </div>
        <Field label="Reference" hint="UTR, UPI reference or receipt number.">
          <Input value={reference} onChange={(event) => setReference(event.target.value)} maxLength={120} />
        </Field>
        <Field label="Note">
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            maxLength={500}
            placeholder="Evidence checked and recorded by the owner."
          />
        </Field>
      </div>
    </Modal>
  );
}

function ProductModal({
  product,
  rates,
  currency,
  onClose,
  onSaved,
}: {
  product: BillingProduct | null;
  rates: GSTRate[];
  currency: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const [form, setForm] = useState<ProductForm>(product ? productToForm(product) : EMPTY_PRODUCT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const activeRates = rates.filter((rate) => rate.is_active);
  const gstChanged =
    product !== null &&
    (form.default_gst_rate !== String(product.default_gst_rate) ||
      (form.hsn_sac ?? "") !== (product.hsn_sac ?? "") ||
      form.item_type !== product.item_type);

  const submit = async () => {
    setError(null);
    if (gstChanged && reason.trim().length < 3) {
      setError("Add a short reason for the GST rate, HSN/SAC or type change.");
      return;
    }
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        ...form,
        default_gst_rate: Number(form.default_gst_rate),
        unit_price: Number(form.unit_price),
        unit_cost: Number(form.unit_cost),
        reorder_level: Number(form.reorder_level),
      };
      if (product && gstChanged) payload.gst_change_reason = reason.trim();
      const response = product
        ? await put<{ item: BillingProduct }>(`/billing/products/${product.id}`, payload)
        : await post<{ item: BillingProduct }>("/billing/products", payload);
      toast({
        tone: "success",
        title: product ? "Product updated" : "Product added",
        description: `${response.item.name} · default GST ${response.item.default_gst_rate}%.`,
      });
      onSaved();
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
      title={product ? `Edit ${product.name}` : "Add product or service"}
      description="The default GST rate prefills new invoice lines. Changing a rate on an invoice never rewrites this default or an issued invoice."
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            {product ? "Save changes" : "Add to catalogue"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <Callout tone="red" title="Not saved" icon={AlertTriangle}>
            {error}
          </Callout>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="SKU" required>
            <Input
              value={form.sku}
              onChange={(event) => setForm({ ...form, sku: event.target.value })}
              maxLength={40}
            />
          </Field>
          <Field label="Name" required>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              maxLength={160}
            />
          </Field>
          <Field label="Type">
            <Select
              value={form.item_type}
              onChange={(event) =>
                setForm({ ...form, item_type: event.target.value as "goods" | "services" })
              }
            >
              <option value="goods">Goods</option>
              <option value="services">Service</option>
            </Select>
          </Field>
          <Field label="Unit">
            <Input
              value={form.unit}
              onChange={(event) => setForm({ ...form, unit: event.target.value })}
              maxLength={24}
            />
          </Field>
          <Field label="HSN / SAC" hint="Confirm classification with your tax adviser.">
            <Input
              value={form.hsn_sac}
              onChange={(event) => setForm({ ...form, hsn_sac: event.target.value })}
              maxLength={12}
            />
          </Field>
          <Field label="Default GST rate">
            <Select
              value={form.default_gst_rate}
              onChange={(event) => setForm({ ...form, default_gst_rate: event.target.value })}
            >
              {activeRates.map((rate) => (
                <option key={rate.id} value={rate.rate}>
                  {Number(rate.rate)}%{rate.is_custom ? " (custom)" : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={`Selling price (${currency})`}>
            <Input
              type="number"
              min="0"
              step="0.01"
              value={form.unit_price}
              onChange={(event) => setForm({ ...form, unit_price: event.target.value })}
            />
          </Field>
          <Field label={`Cost price (${currency})`}>
            <Input
              type="number"
              min="0"
              step="0.01"
              value={form.unit_cost}
              onChange={(event) => setForm({ ...form, unit_cost: event.target.value })}
            />
          </Field>
          {form.item_type === "goods" && (
            <Field label="Reorder level">
              <Input
                type="number"
                min="0"
                step="1"
                value={form.reorder_level}
                onChange={(event) => setForm({ ...form, reorder_level: event.target.value })}
              />
            </Field>
          )}
          <div className="sm:col-span-2">
            <Field label="Description">
              <Textarea
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                rows={2}
                maxLength={2000}
                placeholder="Shown on invoice lines when the item is selected."
              />
            </Field>
          </div>
          {gstChanged && (
            <div className="sm:col-span-2">
              <Callout tone="amber" title="This change is recorded in the GST catalogue history" icon={AlertTriangle}>
                Rate, HSN/SAC and item type edits are audited with an old and new value and never rewrite an
                issued invoice. Give the reason below.
              </Callout>
              <Field label="Reason for the change" required hint="Minimum 3 characters">
                <Input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={500}
                  placeholder="e.g. GST rate notification 12/2026 effective 1 Oct"
                />
              </Field>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

function GstSetupPanel({
  settings,
  onReload,
}: {
  settings: BillingSettings;
  onReload: () => void;
}) {
  const { toast } = useToast();
  const [form, setForm] = useState<BillingBusiness>(settings.business);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rate, setRate] = useState("");
  const [label, setLabel] = useState("");
  const [rateBusy, setRateBusy] = useState(false);
  const [rateError, setRateError] = useState<string | null>(null);

  useEffect(() => {
    setForm(settings.business);
  }, [settings.business]);

  const save = async () => {
    setError(null);
    setBusy(true);
    try {
      await put<BillingSettings>("/billing/settings", {
        business_name: form.business_name,
        legal_name: form.legal_name,
        gstin: form.gstin,
        address_line1: form.address_line1,
        address_line2: form.address_line2,
        city: form.city,
        state: form.state,
        state_code: form.state_code,
        postal_code: form.postal_code,
        business_phone: form.business_phone,
        business_email: form.business_email,
        invoice_terms: form.invoice_terms,
        logo_data_url: form.logo_data_url,
      });
      toast({ tone: "success", title: "GST settings saved" });
      onReload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const addRate = async () => {
    setRateError(null);
    setRateBusy(true);
    try {
      await post("/billing/gst-rates", {
        rate: Number(rate),
        label: label.trim() || null,
      });
      toast({
        tone: "success",
        title: "Custom rate added",
        description: "It becomes available on new invoice lines. Verify it applies to your supply.",
      });
      setRate("");
      setLabel("");
      onReload();
    } catch (err) {
      setRateError(getErrorMessage(err));
    } finally {
      setRateBusy(false);
    }
  };

  const onLogo = (file: File | undefined) => {
    if (!file) return;
    if (file.size > 200_000) {
      toast({
        tone: "error",
        title: "Logo is too large",
        description: "Use an image under 200 KB so it can be stored with the business profile.",
      });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setForm((current) => ({ ...current, logo_data_url: String(reader.result) }));
    reader.readAsDataURL(file);
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        <Card>
          <CardHeader
            title="Supplier details"
            description="These values appear on invoices and in the PDF. FINOVEXA never invents a GSTIN or registration status."
          />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            {error && (
              <div className="sm:col-span-2">
                <Callout tone="red" title="Settings not saved" icon={AlertTriangle}>
                  {error}
                </Callout>
              </div>
            )}
            <Field label="Business name" required>
              <Input
                value={form.business_name}
                onChange={(event) => setForm({ ...form, business_name: event.target.value })}
                maxLength={160}
              />
            </Field>
            <Field label="Legal name">
              <Input
                value={form.legal_name ?? ""}
                onChange={(event) => setForm({ ...form, legal_name: event.target.value })}
                maxLength={160}
                placeholder="As registered, if different"
              />
            </Field>
            <Field
              label="GSTIN"
              hint="Optional. Checksum is validated. Leave blank if you are not GST registered."
            >
              <Input
                value={form.gstin ?? ""}
                onChange={(event) =>
                  setForm({ ...form, gstin: event.target.value.toUpperCase() })
                }
                maxLength={15}
                placeholder="27ABCDE1234F1Z5"
              />
            </Field>
            <Field label="State" hint="Supplier state determines the CGST/SGST or IGST split.">
              <Select
                value={form.state_code ?? ""}
                onChange={(event) => {
                  const state = settings.states.find((row) => row.code === event.target.value);
                  setForm({
                    ...form,
                    state_code: event.target.value,
                    state: state?.name ?? "",
                  });
                }}
              >
                <option value="">Select a state…</option>
                {settings.states.map((state) => (
                  <option key={state.code} value={state.code}>
                    {state.code} — {state.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Address line 1">
              <Input
                value={form.address_line1 ?? ""}
                onChange={(event) => setForm({ ...form, address_line1: event.target.value })}
                maxLength={200}
              />
            </Field>
            <Field label="Address line 2">
              <Input
                value={form.address_line2 ?? ""}
                onChange={(event) => setForm({ ...form, address_line2: event.target.value })}
                maxLength={200}
              />
            </Field>
            <Field label="City">
              <Input
                value={form.city ?? ""}
                onChange={(event) => setForm({ ...form, city: event.target.value })}
                maxLength={80}
              />
            </Field>
            <Field label="PIN code">
              <Input
                value={form.postal_code ?? ""}
                onChange={(event) => setForm({ ...form, postal_code: event.target.value })}
                maxLength={10}
              />
            </Field>
            <Field label="Business phone">
              <Input
                value={form.business_phone ?? ""}
                onChange={(event) => setForm({ ...form, business_phone: event.target.value })}
                maxLength={40}
              />
            </Field>
            <Field label="Business email">
              <Input
                type="email"
                value={form.business_email ?? ""}
                onChange={(event) => setForm({ ...form, business_email: event.target.value })}
                maxLength={255}
              />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Default invoice terms">
                <Textarea
                  value={form.invoice_terms ?? ""}
                  onChange={(event) => setForm({ ...form, invoice_terms: event.target.value })}
                  rows={3}
                  maxLength={3000}
                />
              </Field>
            </div>
            <div className="sm:col-span-2">
              <Field label="Business logo" hint="Optional PNG/JPG under 200 KB. Stored as a data URL.">
                <div className="flex flex-wrap items-center gap-3">
                  {form.logo_data_url ? (
                    <img
                      src={form.logo_data_url}
                      alt="Business logo preview"
                      className="h-12 w-12 rounded border border-slate-200 object-contain"
                    />
                  ) : (
                    <span className="flex h-12 w-12 items-center justify-center rounded border border-dashed border-slate-300 text-[10px] text-slate-400">
                      No logo
                    </span>
                  )}
                  <input
                    type="file"
                    accept="image/png,image/jpeg"
                    onChange={(event) => onLogo(event.target.files?.[0])}
                    className="text-xs text-slate-500"
                  />
                  {form.logo_data_url && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setForm({ ...form, logo_data_url: null })}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              </Field>
            </div>
            <div className="sm:col-span-2 flex justify-end">
              <Button onClick={() => void save()} loading={busy} icon={ShieldCheck}>
                Save GST settings
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Configured GST rates"
            description="Only active rates can be used on a new invoice. Custom rates are an explicit owner action."
          />
          <CardBody className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {settings.rates.map((rate) => (
                <span
                  key={rate.id}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-[11px]"
                >
                  <Percent className="h-3 w-3 text-slate-400" />
                  <span className="font-semibold text-slate-800">{Number(rate.rate)}%</span>
                  <span className="text-slate-500">{rate.label}</span>
                  {rate.is_custom && <Badge tone="violet">Custom</Badge>}
                  {!rate.is_active && <Badge tone="slate">Inactive</Badge>}
                </span>
              ))}
            </div>
            {rateError && (
              <Callout tone="red" title="Rate not added" icon={AlertTriangle}>
                {rateError}
              </Callout>
            )}
            <div className="grid gap-3 sm:grid-cols-[120px_1fr_auto]">
              <Field label="Rate %">
                <Input
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  value={rate}
                  onChange={(event) => setRate(event.target.value)}
                  placeholder="6"
                />
              </Field>
              <Field label="Label">
                <Input
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="e.g. 6% — verified with adviser"
                  maxLength={60}
                />
              </Field>
              <div className="flex items-end">
                <Button
                  variant="outline"
                  icon={Plus}
                  onClick={() => void addRate()}
                  loading={rateBusy}
                  disabled={!rate}
                >
                  Add rate
                </Button>
              </div>
            </div>
          </CardBody>
        </Card>
      </div>

      <aside className="space-y-4">
        <Callout tone="blue" title="GST is configurable, not guessed" icon={Info}>
          The calculator supports exclusive and inclusive pricing, intra-state CGST/SGST and
          inter-state IGST. It does not decide the correct legal rate or HSN/SAC classification for
          your supply. Verify each rate with your tax adviser before issuing real tax invoices.
        </Callout>
        <Card>
          <CardHeader title="Readiness" />
          <CardBody className="space-y-2 text-[12px]">
            <ReadinessRow ok={Boolean(form.state_code)} label="Supplier state set" />
            <ReadinessRow ok={Boolean(form.gstin)} label="GSTIN saved (optional)" optional />
            <ReadinessRow ok={Boolean(form.address_line1)} label="Billing address" />
            <ReadinessRow ok={Boolean(form.invoice_terms)} label="Invoice terms" />
            <p className="pt-2 text-[10px] leading-relaxed text-slate-400">
              A tax invoice normally needs the supplier and customer GSTIN, a valid tax rate and a
              correct place of supply. If any detail is uncertain, confirm it before issuing.
            </p>
          </CardBody>
        </Card>
      </aside>
    </div>
  );
}

function ReadinessRow({
  ok,
  label,
  optional = false,
}: {
  ok: boolean;
  label: string;
  optional?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-slate-600">{label}</span>
      <Badge tone={ok ? "green" : optional ? "slate" : "amber"}>
        {ok ? "Ready" : optional ? "Optional" : "Missing"}
      </Badge>
    </div>
  );
}

export function GstBillingPage() {
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const lastDeepLink = useRef<string | null>(null);
  const [tab, setTab] = useState<Tab>("invoices");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [status, setStatus] = useState("all");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingInvoice, setEditingInvoice] = useState<Invoice | null>(null);
  const [viewInvoice, setViewInvoice] = useState<Invoice | null>(null);
  const [paymentInvoice, setPaymentInvoice] = useState<Invoice | null>(null);
  const [paypalInvoice, setPaypalInvoice] = useState<Invoice | null>(null);
  const [voidTarget, setVoidTarget] = useState<Invoice | null>(null);
  const [voidBusy, setVoidBusy] = useState(false);
  const [productModal, setProductModal] = useState<{ open: boolean; product: BillingProduct | null }>({
    open: false,
    product: null,
  });
  const [loadingInvoice, setLoadingInvoice] = useState<number | null>(null);

  const invoices = useApi<{ items: Invoice[]; count: number }>(
    `/billing/invoices?q=${encodeURIComponent(deferredSearch)}&status=${status}`,
  );
  const overview = useApi<BillingOverview>("/billing/overview");
  const settings = useApi<BillingSettings>("/billing/settings");
  const products = useApi<{ items: BillingProduct[] }>("/billing/products");
  const customers = useApi<{ items: BillingCustomer[] }>("/billing/customers");
  const payments = useApi<PaymentOverview>("/payments/overview?days=30");

  const currency = settings.data?.business.currency || "INR";
  const invoiceCount = invoices.data?.count ?? 0;
  const productCount = products.data?.items.length ?? 0;

  const reloadAll = () => {
    invoices.reload();
    overview.reload();
    payments.reload();
  };

  const openInvoice = async (invoice: Invoice) => {
    setLoadingInvoice(invoice.id);
    try {
      const detail = await api<Invoice>(`/billing/invoices/${invoice.id}`);
      setViewInvoice(detail);
    } catch (err) {
      toast({ tone: "error", title: "Could not open invoice", description: getErrorMessage(err) });
    } finally {
      setLoadingInvoice(null);
    }
  };

  const openEdit = async (invoice: Invoice) => {
    setLoadingInvoice(invoice.id);
    try {
      const detail = await api<Invoice>(`/billing/invoices/${invoice.id}`);
      setEditingInvoice(detail);
      setEditorOpen(true);
      setViewInvoice(null);
    } catch (err) {
      toast({ tone: "error", title: "Could not open invoice", description: getErrorMessage(err) });
    } finally {
      setLoadingInvoice(null);
    }
  };

  const startNew = () => {
    setEditingInvoice(null);
    setEditorOpen(true);
    setViewInvoice(null);
  };

  const downloadPdf = async (invoice: Invoice) => {
    try {
      await downloadFile(`/billing/invoices/${invoice.id}/pdf`, `${invoice.number}.pdf`);
      toast({ tone: "success", title: "PDF downloaded", description: `${invoice.number}.pdf` });
    } catch (err) {
      toast({ tone: "error", title: "PDF download failed", description: getErrorMessage(err) });
    }
  };

  const confirmVoid = async () => {
    if (!voidTarget) return;
    setVoidBusy(true);
    try {
      const result = await post<Invoice>(`/billing/invoices/${voidTarget.id}/void`, {
        confirm: true,
      });
      toast({
        tone: "success",
        title: "Invoice voided",
        description: `${result.number} is now marked void. The record is retained for audit.`,
      });
      setVoidTarget(null);
      setViewInvoice(result);
      reloadAll();
    } catch (err) {
      toast({ tone: "error", title: "Invoice not voided", description: getErrorMessage(err) });
    } finally {
      setVoidBusy(false);
    }
  };

  useEffect(() => {
    const signature = searchParams.toString();
    if (!signature || signature === lastDeepLink.current) return;
    const requestedTab = searchParams.get("tab") as Tab | null;
    const invoiceId = Number(searchParams.get("invoice") || 0);
    const productId = Number(searchParams.get("product") || 0);
    const openNewInvoice = searchParams.get("new") === "1";
    const openNewProduct = searchParams.get("newProduct") === "1";

    if (requestedTab === "invoices" || requestedTab === "catalogue" || requestedTab === "setup") {
      setTab(requestedTab);
    }

    const consume = () => {
      lastDeepLink.current = signature;
      const next = new URLSearchParams(searchParams);
      ["tab", "invoice", "product", "new", "newProduct"].forEach((key) => next.delete(key));
      setSearchParams(next, { replace: true });
    };

    if (openNewInvoice) {
      if (!settings.data) return;
      startNew();
      consume();
      return;
    }

    if (openNewProduct) {
      setProductModal({ open: true, product: null });
      consume();
      return;
    }

    if (productId) {
      if (!products.data) return;
      const product = products.data.items.find((item) => item.id === productId);
      if (product) {
        setProductModal({ open: true, product });
      } else {
        toast({
          tone: "error",
          title: "Product not found",
          description: "It may have been removed from the catalogue.",
        });
      }
      consume();
      return;
    }

    if (invoiceId) {
      let alive = true;
      void api<Invoice>(`/billing/invoices/${invoiceId}`)
        .then((detail) => {
          if (alive) setViewInvoice(detail);
        })
        .catch((err) => {
          if (alive) {
            toast({ tone: "error", title: "Could not open invoice", description: getErrorMessage(err) });
          }
        });
      consume();
      return () => {
        alive = false;
      };
    }

    if (requestedTab) consume();
  }, [searchParams, settings.data, products.data, setSearchParams, toast]);

  if (editorOpen && settings.data) {
    return (
      <InvoiceEditor
        key={editingInvoice ? `edit-${editingInvoice.id}` : "new"}
        invoice={editingInvoice}
        settings={settings.data}
        customers={customers.data?.items ?? []}
        products={products.data?.items ?? []}
        onCancel={() => setEditorOpen(false)}
        onSaved={(invoice) => {
          setEditorOpen(false);
          setViewInvoice(invoice);
          reloadAll();
          products.reload();
          customers.reload();
        }}
      />
    );
  }

  if (settings.loading || invoices.loading) {
    return <PageSkeleton cards={4} />;
  }

  if (settings.error) {
    return <ErrorState message={settings.error} onRetry={settings.reload} />;
  }

  const invoiceList = invoices.data?.items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="GST & Billing"
        title="GST invoices and billing"
        description="Create, issue, print and download GST invoices. The backend recalculates every line with decimal precision and stores the tax values at issue time."
        actions={
          <>
            <Button variant="outline" icon={RefreshCw} onClick={reloadAll}>
              Refresh
            </Button>
            <Button icon={Plus} onClick={startNew}>
              New invoice
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Invoiced"
          value={moneyExact(overview.data?.totals.invoiced ?? 0, currency)}
          icon={ReceiptText}
          tone="blue"
          sub={`${overview.data?.counts.total ?? 0} records including drafts`}
        />
        <StatCard
          label="Outstanding"
          value={moneyExact(overview.data?.totals.outstanding ?? 0, currency)}
          icon={Wallet}
          tone="amber"
          sub={`${overview.data?.counts.overdue ?? 0} overdue`}
        />
        <StatCard
          label="GST charged on invoices"
          value={moneyExact(overview.data?.totals.gst_on_invoices ?? 0, currency)}
          icon={IndianRupee}
          tone="violet"
          sub="Not a net GST payable calculation"
        />
        <StatCard
          label="Confirmed receipts"
          value={moneyExact(overview.data?.totals.confirmed_received ?? 0, currency)}
          icon={CheckCircle2}
          tone="green"
          sub="From verified payment records"
        />
      </div>

      <Tabs
        items={[
          { key: "invoices", label: "Invoices", count: invoiceCount },
          { key: "catalogue", label: "Product catalogue", count: productCount },
          { key: "setup", label: "GST setup" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "invoices" && (
        <Card>
          <CardHeader
            title="Invoice register"
            description={overview.data?.note}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                  <Input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search number or customer…"
                    className="h-8 w-[200px] pl-8 text-xs"
                  />
                </div>
                <Select
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                  className="h-8 w-[150px] py-0 text-xs"
                >
                  {INVOICE_STATUSES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </div>
            }
          />
          <CardBody className="p-0">
            {invoices.error ? (
              <div className="p-4">
                <ErrorState message={invoices.error} onRetry={invoices.reload} />
              </div>
            ) : invoiceList.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  icon={ReceiptText}
                  title="No invoices match"
                  description="Create a GST invoice or change the search and status filters."
                  action={
                    <Button icon={Plus} onClick={startNew}>
                      New invoice
                    </Button>
                  }
                />
              </div>
            ) : (
              invoiceList.map((invoice) => (
                <div key={invoice.id} className={loadingInvoice === invoice.id ? "opacity-60" : ""}>
                  <InvoiceRow
                    invoice={invoice}
                    currency={currency}
                    onView={() => void openInvoice(invoice)}
                    onEdit={() => void openEdit(invoice)}
                  />
                </div>
              ))
            )}
          </CardBody>
        </Card>
      )}

      {tab === "catalogue" && (
        <Card>
          <CardHeader
            title="Products and services"
            description="Default GST rate and HSN/SAC prefill invoice lines. Editing them never changes an issued invoice."
            actions={
              <Button
                icon={Plus}
                onClick={() => setProductModal({ open: true, product: null })}
              >
                Add item
              </Button>
            }
          />
          <CardBody className="p-0">
            {products.error ? (
              <div className="p-4">
                <ErrorState message={products.error} onRetry={products.reload} />
              </div>
            ) : productCount === 0 ? (
              <div className="p-4">
                <EmptyState
                  icon={Boxes}
                  title="Catalogue is empty"
                  description="Add products or services so invoice lines can prefill details and GST."
                />
              </div>
            ) : (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Item</TH>
                    <TH>Type</TH>
                    <TH>HSN / SAC</TH>
                    <TH className="text-right">Price</TH>
                    <TH className="text-right">Default GST</TH>
                    <TH className="text-right">Stock</TH>
                    <TH />
                  </TR>
                </THead>
                <TBody>
                  {products.data?.items.map((product) => (
                    <TR key={product.id}>
                      <TD>
                        <p className="font-medium text-ink-900">{product.name}</p>
                        <p className="text-[10px] text-slate-400">{product.sku}</p>
                      </TD>
                      <TD className="capitalize text-slate-600">{product.item_type}</TD>
                      <TD className="font-mono text-[11px] text-slate-600">
                        {product.hsn_sac || "—"}
                      </TD>
                      <TD className="text-right text-slate-700">
                        {moneyExact(product.unit_price, currency)}
                      </TD>
                      <TD className="text-right text-slate-700">{Number(product.default_gst_rate)}%</TD>
                      <TD className="text-right">
                        {product.item_type === "goods" ? (
                          <span className={product.low_stock ? "text-amber-600" : "text-slate-600"}>
                            {formatNumber(product.quantity_on_hand)}
                            {product.low_stock ? " · low" : ""}
                          </span>
                        ) : (
                          <span className="text-slate-400">n/a</span>
                        )}
                      </TD>
                      <TD className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={Pencil}
                          onClick={() => setProductModal({ open: true, product })}
                        >
                          Edit
                        </Button>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            )}
          </CardBody>
        </Card>
      )}

      {tab === "setup" && settings.data && (
        <GstSetupPanel
          settings={settings.data}
          onReload={() => {
            settings.reload();
            products.reload();
          }}
        />
      )}

      {viewInvoice && (
        <Modal
          open
          onClose={() => setViewInvoice(null)}
          title={`${viewInvoice.number} · ${viewInvoice.customer.name}`}
          description={`${titleCase(viewInvoice.status)} · ${moneyExact(viewInvoice.total, currency)} · ${
            supplyBadge(viewInvoice.supply_type).label
          }`}
          size="xl"
          footer={
            <>
              <Button variant="outline" onClick={() => setViewInvoice(null)}>
                Close
              </Button>
              <Button
                variant="outline"
                icon={Printer}
                onClick={() => printInvoiceDocument("invoice-document")}
              >
                Print
              </Button>
              <Button
                variant="outline"
                icon={Download}
                onClick={() => void downloadPdf(viewInvoice)}
              >
                Download PDF
              </Button>
              {viewInvoice.base_status !== "void" && viewInvoice.outstanding > 0 && (
                <Button
                  variant="outline"
                  icon={Wallet}
                  onClick={() => setPaymentInvoice(viewInvoice)}
                >
                  Record payment
                </Button>
              )}
              {viewInvoice.base_status !== "void" && viewInvoice.outstanding > 0 && (
                <Button
                  variant="outline"
                  icon={CreditCard}
                  onClick={() => setPaypalInvoice(viewInvoice)}
                  disabled={!payments.data?.provider}
                >
                  PayPal
                </Button>
              )}
              {viewInvoice.paid === 0 && viewInvoice.base_status !== "void" && (
                <Button
                  variant="outline"
                  icon={Ban}
                  onClick={() => setVoidTarget(viewInvoice)}
                >
                  Void
                </Button>
              )}
              {viewInvoice.base_status !== "void" && (
                <Button variant="outline" icon={Pencil} onClick={() => void openEdit(viewInvoice)}>
                  Edit
                </Button>
              )}
            </>
          }
        >
          <div className="rounded-xl bg-slate-100 p-2 sm:p-4">
            <InvoiceDocument
              invoice={viewInvoice}
              logoUrl={settings.data?.business.logo_data_url}
            />
          </div>
        </Modal>
      )}

      {paymentInvoice && (
        <PaymentModal
          invoice={paymentInvoice}
          currency={currency}
          onClose={() => setPaymentInvoice(null)}
          onDone={(invoice) => {
            setPaymentInvoice(null);
            setViewInvoice(invoice);
            reloadAll();
          }}
        />
      )}

      {paypalInvoice && payments.data?.provider && (
        <CheckoutModal
          invoice={paypalInvoice}
          provider={payments.data.provider}
          currency={currency}
          onClose={() => setPaypalInvoice(null)}
          onDone={() => {
            payments.reload();
            overview.reload();
            invoices.reload();
          }}
        />
      )}

      <ConfirmDialog
        open={Boolean(voidTarget)}
        onClose={() => setVoidTarget(null)}
        onConfirm={() => void confirmVoid()}
        title="Void this invoice?"
        description={
          voidTarget
            ? `${voidTarget.number} will be retained for audit but removed from outstanding balances. This cannot be undone.`
            : undefined
        }
        confirmLabel="Void invoice"
        tone="danger"
        loading={voidBusy}
        disabled={Boolean(voidTarget && voidTarget.paid > 0)}
      >
        {voidTarget && voidTarget.paid > 0 && (
          <Callout tone="red" title="Payments recorded" icon={AlertTriangle}>
            This invoice has confirmed payments. Reverse or refund those payments before voiding it.
          </Callout>
        )}
      </ConfirmDialog>

      {productModal.open && settings.data && (
        <ProductModal
          product={productModal.product}
          rates={settings.data.rates}
          currency={currency}
          onClose={() => setProductModal({ open: false, product: null })}
          onSaved={() => {
            setProductModal({ open: false, product: null });
            products.reload();
          }}
        />
      )}

      {!settings.data?.ready && tab === "invoices" && (
        <Callout tone="amber" title="Set your supplier state before invoicing" icon={AlertTriangle}>
          The GST split needs your business state. Open GST setup and save the supplier state and
          address first. FINOVEXA will not guess the place of supply.
        </Callout>
      )}
    </div>
  );
}
