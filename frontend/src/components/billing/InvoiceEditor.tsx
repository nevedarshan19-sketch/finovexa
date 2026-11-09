import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Calculator,
  Eye,
  PackageSearch,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { getErrorMessage, post, put } from "../../lib/api";
import type {
  BillingCustomer,
  BillingProduct,
  BillingSettings,
  GSTCalculation,
  Invoice,
} from "../../lib/types";
import { formatDate, moneyExact } from "../../lib/utils";
import { useToast } from "../../context/ToastContext";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  EmptyState,
  Field,
  Input,
  Modal,
  Select,
  Textarea,
} from "../ui";
import { InvoiceDocument, printInvoiceDocument } from "../InvoiceDocument";

type PricingMode = "exclusive" | "inclusive";
type InvoiceStatus = "draft" | "issued";

interface DraftLine {
  key: string;
  productId: string;
  name: string;
  description: string;
  hsnSac: string;
  unit: string;
  itemType: "goods" | "services";
  quantity: string;
  unitPrice: string;
  discount: string;
  gstRate: string;
}

interface CustomerDraft {
  name: string;
  email: string;
  company: string;
  phone: string;
  gstin: string;
  address1: string;
  address2: string;
  city: string;
  state: string;
  stateCode: string;
  postalCode: string;
}

interface FormState {
  number: string;
  customerMode: "existing" | "new";
  customerId: string;
  newCustomer: CustomerDraft;
  issueDate: string;
  dueDate: string;
  pricingMode: PricingMode;
  posCode: string;
  lines: DraftLine[];
  otherCharges: string;
  roundToRupee: boolean;
  notes: string;
  terms: string;
  confirm: boolean;
  status: InvoiceStatus;
}

let lineCounter = 0;

function makeLine(overrides: Partial<DraftLine> = {}): DraftLine {
  lineCounter += 1;
  return {
    key: `line-${lineCounter}`,
    productId: "",
    name: "",
    description: "",
    hsnSac: "",
    unit: "pcs",
    itemType: "goods",
    quantity: "1",
    unitPrice: "",
    discount: "0",
    gstRate: "18",
    ...overrides,
  };
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

const EMPTY_CUSTOMER: CustomerDraft = {
  name: "",
  email: "",
  company: "",
  phone: "",
  gstin: "",
  address1: "",
  address2: "",
  city: "",
  state: "",
  stateCode: "",
  postalCode: "",
};

function formFromInvoice(invoice: Invoice | null, settings: BillingSettings): FormState {
  return {
    number: invoice?.number ?? "",
    customerMode: "existing",
    customerId: invoice ? String(invoice.customer.id) : "",
    newCustomer: EMPTY_CUSTOMER,
    issueDate: invoice?.issue_date ?? todayIso(),
    dueDate: invoice?.due_date ?? addDays(todayIso(), 30),
    pricingMode: invoice?.pricing_mode ?? "exclusive",
    posCode:
      invoice?.place_of_supply?.state_code ??
      (invoice ? "" : settings.business.state_code ?? ""),
    lines:
      invoice && invoice.items.length > 0
        ? invoice.items.map((item) =>
            makeLine({
              productId: item.product_id ? String(item.product_id) : "",
              name: item.name || item.description,
              description: item.description,
              hsnSac: item.hsn_sac ?? "",
              unit: item.unit ?? "pcs",
              itemType: item.item_type === "services" ? "services" : "goods",
              quantity: String(item.quantity),
              unitPrice: String(item.unit_price),
              discount: String(item.discount ?? 0),
              gstRate: String(item.gst_rate ?? 18),
            }),
          )
        : [makeLine()],
    otherCharges: String(invoice?.other_charges ?? 0),
    roundToRupee: invoice?.round_to_rupee ?? true,
    notes: invoice?.notes ?? "",
    terms: invoice?.terms ?? settings.business.invoice_terms ?? "",
    confirm: false,
    status: invoice?.base_status === "draft" ? "draft" : "issued",
  };
}

function toNumber(value: string, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function previewLine(line: DraftLine, mode: PricingMode) {
  const quantity = toNumber(line.quantity);
  const price = toNumber(line.unitPrice);
  const discount = toNumber(line.discount);
  const rate = toNumber(line.gstRate);
  const gross = quantity * price;
  const net = Math.max(gross - discount, 0);
  if (mode === "inclusive") {
    const taxable = net / (1 + rate / 100);
    return { taxable, gst: net - taxable, total: net, invalid: discount > gross };
  }
  const taxable = net;
  const gst = (taxable * rate) / 100;
  return { taxable, gst, total: taxable + gst, invalid: discount > gross };
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function InvoiceEditor({
  invoice,
  settings,
  customers,
  products,
  onCancel,
  onSaved,
}: {
  invoice: Invoice | null;
  settings: BillingSettings;
  customers: BillingCustomer[];
  products: BillingProduct[];
  onCancel: () => void;
  onSaved: (invoice: Invoice) => void;
}) {
  const { toast } = useToast();
  const [form, setForm] = useState<FormState>(() => formFromInvoice(invoice, settings));
  const [calc, setCalc] = useState<GSTCalculation | null>(null);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [saving, setSaving] = useState<InvoiceStatus | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [productQuery, setProductQuery] = useState("");
  const [showProductResults, setShowProductResults] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const requestId = useRef(0);
  const [phoneDraft, setPhoneDraft] = useState("");
  const [savedPhones, setSavedPhones] = useState<Record<number, string>>({});
  const [savingPhone, setSavingPhone] = useState(false);

  const activeRates = useMemo(
    () => settings.rates.filter((rate) => rate.is_active),
    [settings.rates],
  );

  const selectedCustomer = useMemo(
    () => customers.find((customer) => String(customer.id) === form.customerId) ?? null,
    [customers, form.customerId],
  );

  const selectedPhone = selectedCustomer
    ? savedPhones[selectedCustomer.id] ?? selectedCustomer.phone ?? ""
    : "";

  useEffect(() => {
    setPhoneDraft(selectedPhone);
  }, [selectedCustomer?.id, selectedPhone]);

  const saveCustomerPhone = async () => {
    if (!selectedCustomer) return;
    const value = phoneDraft.trim();
    if (value === selectedPhone.trim()) return;
    setSavingPhone(true);
    try {
      const result = await put<{ item: BillingCustomer }>(
        `/billing/customers/${selectedCustomer.id}`,
        {
          name: selectedCustomer.name,
          email: selectedCustomer.email,
          company: selectedCustomer.company,
          phone: value || null,
          gstin: selectedCustomer.gstin,
          billing_address_line1: selectedCustomer.billing_address_line1 ?? null,
          billing_address_line2: selectedCustomer.billing_address_line2 ?? null,
          city: selectedCustomer.city ?? null,
          state: selectedCustomer.state ?? null,
          state_code: selectedCustomer.state_code ?? null,
          postal_code: selectedCustomer.postal_code ?? null,
        },
      );
      setSavedPhones((current) => ({
        ...current,
        [selectedCustomer.id]: result.item.phone ?? "",
      }));
      setPhoneDraft(result.item.phone ?? "");
      toast({
        tone: "success",
        title: "Mobile saved",
        description: result.item.phone
          ? `${result.item.phone} will appear on this customer's invoices and can receive SMS reminders.`
          : "Mobile number removed from the customer record.",
      });
    } catch (err) {
      toast({
        tone: "error",
        title: "Could not save mobile",
        description: getErrorMessage(err),
      });
    } finally {
      setSavingPhone(false);
    }
  };

  const productMatches = useMemo(() => {
    const needle = productQuery.trim().toLowerCase();
    if (!needle) return products.slice(0, 6);
    return products
      .filter(
        (product) =>
          product.name.toLowerCase().includes(needle) ||
          product.sku.toLowerCase().includes(needle) ||
          (product.hsn_sac || "").toLowerCase().includes(needle),
      )
      .slice(0, 8);
  }, [productQuery, products]);

  const update = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }));

  const updateLine = (key: string, patch: Partial<DraftLine>) =>
    setForm((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    }));

  const addProduct = (product: BillingProduct) => {
    const line = makeLine({
      productId: String(product.id),
      name: product.name,
      description: product.description ?? "",
      hsnSac: product.hsn_sac ?? "",
      unit: product.unit || "pcs",
      itemType: product.item_type,
      quantity: "1",
      unitPrice: String(product.unit_price ?? 0),
      gstRate: String(product.default_gst_rate ?? 18),
    });
    setForm((current) => {
      const blankIndex = current.lines.findIndex(
        (candidate) =>
          !candidate.name.trim() &&
          !candidate.productId &&
          !candidate.hsnSac.trim() &&
          !toNumber(candidate.unitPrice) &&
          !toNumber(candidate.discount),
      );
      if (blankIndex === -1) {
        return { ...current, lines: [...current.lines, line] };
      }
      return {
        ...current,
        lines: current.lines.map((candidate, index) =>
          index === blankIndex ? line : candidate,
        ),
      };
    });
    setProductQuery("");
    setShowProductResults(false);
  };

  const payloadLines = form.lines
    .filter((line) => line.name.trim() && toNumber(line.quantity) > 0)
    .map((line) => ({
      product_id: line.productId ? Number(line.productId) : null,
      name: line.name.trim(),
      description: line.description.trim() || line.name.trim(),
      hsn_sac: line.hsnSac.trim() || null,
      unit: line.unit.trim() || "pcs",
      item_type: line.itemType,
      quantity: Number(line.quantity),
      unit_price: toNumber(line.unitPrice),
      discount: toNumber(line.discount),
      gst_rate: toNumber(line.gstRate),
    }));

  const customerPayload = () => ({
    name: form.newCustomer.name.trim(),
    email: form.newCustomer.email.trim(),
    company: form.newCustomer.company.trim() || null,
    phone: form.newCustomer.phone.trim() || null,
    gstin: form.newCustomer.gstin.trim() || null,
    billing_address_line1: form.newCustomer.address1.trim() || null,
    billing_address_line2: form.newCustomer.address2.trim() || null,
    city: form.newCustomer.city.trim() || null,
    state: form.newCustomer.state || null,
    state_code: form.newCustomer.stateCode || null,
    postal_code: form.newCustomer.postalCode.trim() || null,
  });

  const basePayload = () => ({
    ...(form.customerMode === "existing"
      ? { customer_id: Number(form.customerId) }
      : { customer: customerPayload(), save_customer: true }),
    number: form.number.trim() || null,
    issue_date: form.issueDate,
    due_date: form.dueDate,
    pricing_mode: form.pricingMode,
    place_of_supply_state_code: form.posCode || null,
    items: payloadLines,
    other_charges: toNumber(form.otherCharges),
    round_to_rupee: form.roundToRupee,
    confirm_supply_details: form.confirm,
    notes: form.notes.trim() || null,
    terms: form.terms.trim() || null,
  });

  useEffect(() => {
    if (payloadLines.length === 0 || !form.posCode) {
      setCalc(null);
      setCalcError(null);
      return;
    }
    const id = requestId.current + 1;
    requestId.current = id;
    const timer = window.setTimeout(async () => {
      setCalculating(true);
      try {
        const result = await post<GSTCalculation>("/billing/calculate", {
          pricing_mode: form.pricingMode,
          place_of_supply_state_code: form.posCode,
          items: payloadLines,
          other_charges: toNumber(form.otherCharges),
          round_to_rupee: form.roundToRupee,
        });
        if (requestId.current !== id) return;
        setCalc(result);
        setCalcError(null);
      } catch (err) {
        if (requestId.current !== id) return;
        setCalc(null);
        setCalcError(getErrorMessage(err));
      } finally {
        if (requestId.current === id) setCalculating(false);
      }
    }, 450);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    form.lines,
    form.posCode,
    form.pricingMode,
    form.otherCharges,
    form.roundToRupee,
  ]);

  const localTotals = useMemo(() => {
    let subtotal = 0;
    let taxable = 0;
    let gst = 0;
    let total = 0;
    let discount = 0;
    let invalid = false;
    for (const line of form.lines) {
      if (!line.name.trim()) continue;
      const result = previewLine(line, form.pricingMode);
      if (result.invalid) invalid = true;
      subtotal += toNumber(line.quantity) * toNumber(line.unitPrice);
      discount += toNumber(line.discount);
      taxable += result.taxable;
      gst += result.gst;
      total += result.total;
    }
    return {
      subtotal: round2(subtotal),
      discount: round2(discount),
      taxable: round2(taxable),
      gst: round2(gst),
      total: round2(total + toNumber(form.otherCharges)),
      invalid,
    };
  }, [form.lines, form.pricingMode, form.otherCharges]);

  const canSave =
    form.confirm &&
    payloadLines.length > 0 &&
    Boolean(form.posCode) &&
    Boolean(calc) &&
    !calcError &&
    !calculating &&
    (form.customerMode === "existing"
      ? Boolean(form.customerId)
      : Boolean(form.newCustomer.name.trim() && form.newCustomer.email.trim()));

  const save = async (status: InvoiceStatus) => {
    setFormError(null);
    if (!form.confirm) {
      setFormError(
        "Confirm that you verified the supplier state, place of supply and GST rate for every item.",
      );
      return;
    }
    if (form.customerMode === "new" && (!form.newCustomer.name.trim() || !form.newCustomer.email.trim())) {
      setFormError("Enter the customer name and email address.");
      return;
    }
    if (payloadLines.length === 0) {
      setFormError("Add at least one item with a name and a positive quantity.");
      return;
    }
    if (!calc) {
      setFormError(
        calcError ||
          "The backend has not verified the totals yet. Set a place of supply and wait for the calculation.",
      );
      return;
    }
    setSaving(status);
    try {
      const payload = { ...basePayload(), status };
      const result = invoice
        ? await put<Invoice>(`/billing/invoices/${invoice.id}`, payload)
        : await post<Invoice>("/billing/invoices", payload);
      toast({
        tone: "success",
        title: status === "draft" ? "Draft saved" : "Invoice issued",
        description: `${result.number} · ${moneyExact(result.total)} ${
          status === "draft" ? "saved as draft" : "saved with GST breakdown"
        }.`,
      });
      onSaved(result);
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setSaving(null);
    }
  };

  const buildPreview = (): Invoice | null => {
    if (!calc) return null;
    const customer = selectedCustomer
      ? {
          id: selectedCustomer.id,
          name: selectedCustomer.name,
          email: selectedCustomer.email,
          company: selectedCustomer.company,
          phone: selectedPhone || null,
          gstin: selectedCustomer.gstin,
          billing_address: selectedCustomer.billing_address,
          state: selectedCustomer.state ?? null,
          state_code: selectedCustomer.state_code ?? null,
        }
      : {
          id: 0,
          name: form.newCustomer.name,
          email: form.newCustomer.email,
          company: form.newCustomer.company || null,
          phone: form.newCustomer.phone || null,
          gstin: form.newCustomer.gstin || null,
          billing_address:
            [
              form.newCustomer.address1,
              form.newCustomer.address2,
              form.newCustomer.city,
              form.newCustomer.state,
              form.newCustomer.postalCode,
            ]
              .filter(Boolean)
              .join("\n") || null,
          state: form.newCustomer.state || null,
          state_code: form.newCustomer.stateCode || null,
        };
    return {
      id: invoice?.id ?? 0,
      number: form.number || "DRAFT",
      customer,
      issue_date: form.issueDate,
      due_date: form.dueDate,
      currency: settings.business.currency || "INR",
      status: "draft",
      base_status: "draft",
      subtotal: calc.totals.subtotal,
      tax: calc.totals.tax_amount,
      total: calc.totals.total_amount,
      paid: 0,
      outstanding: calc.totals.total_amount,
      aging_days: 0,
      aging_bucket: "current",
      notes: form.notes || null,
      items: calc.lines.map((line) => ({
        name: line.name,
        description: line.description ?? line.name,
        hsn_sac: line.hsn_sac ?? null,
        unit: line.unit,
        item_type: line.item_type,
        quantity: Number(line.quantity),
        unit_price: Number(line.unit_price),
        discount: Number(line.discount),
        line_total: line.gross_amount,
        taxable_value: line.taxable_value,
        gst_rate: Number(line.gst_rate),
        cgst_amount: line.cgst_amount,
        sgst_amount: line.sgst_amount,
        igst_amount: line.igst_amount,
        gst_amount: line.gst_amount,
        final_amount: line.final_amount,
        pricing_mode: line.pricing_mode,
        product_id: line.product_id ?? null,
      })),
      payments: [],
      created_by: null,
      pricing_mode: form.pricingMode,
      supply_type: calc.supply_type,
      supply_type_label: calc.supply_type_label,
      supplier: calc.supplier,
      place_of_supply: calc.place_of_supply,
      supply_verified: true,
      discount: calc.totals.discount,
      taxable_value: calc.totals.taxable_value,
      cgst: calc.totals.cgst_amount,
      sgst: calc.totals.sgst_amount,
      igst: calc.totals.igst_amount,
      other_charges: calc.totals.other_charges,
      rounding_adjustment: calc.totals.rounding_adjustment,
      round_to_rupee: calc.totals.round_to_rupee,
      terms: form.terms || null,
    };
  };

  const stateOptions = settings.states.map((state) => (
    <option key={state.code} value={state.code}>
      {state.code} — {state.name}
    </option>
  ));

  const isInterState =
    (calc?.supply_type ??
      (settings.business.state_code && form.posCode
        ? settings.business.state_code === form.posCode
          ? "intra_state"
          : "inter_state"
        : "intra_state")) === "inter_state";

  const totalsForSummary = calc
    ? {
        subtotal: calc.totals.subtotal,
        discount: calc.totals.discount,
        taxable: calc.totals.taxable_value,
        cgst: calc.totals.cgst_amount,
        sgst: calc.totals.sgst_amount,
        igst: calc.totals.igst_amount,
        other: calc.totals.other_charges,
        rounding: calc.totals.rounding_adjustment,
        total: calc.totals.total_amount,
      }
    : {
        subtotal: localTotals.subtotal,
        discount: localTotals.discount,
        taxable: localTotals.taxable,
        cgst: 0,
        sgst: 0,
        igst: 0,
        other: toNumber(form.otherCharges),
        rounding: 0,
        total: localTotals.total,
      };

  const previewInvoice = buildPreview();
  const currency = settings.business.currency || "INR";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <button
            type="button"
            onClick={onCancel}
            className="mb-2 inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to invoices
          </button>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">
            {invoice ? `Edit ${invoice.number}` : "New GST invoice"}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Amounts are recalculated by the backend with decimal precision. The preview on this
            page is indicative and is re-checked when you save.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            icon={Eye}
            onClick={() => setPreviewOpen(true)}
            disabled={!previewInvoice}
          >
            Preview A4
          </Button>
          <Button
            variant="outline"
            onClick={() => void save("draft")}
            loading={saving === "draft"}
            disabled={!canSave || saving !== null}
          >
            Save draft
          </Button>
          <Button
            onClick={() => void save("issued")}
            loading={saving === "issued"}
            disabled={!canSave || saving !== null}
          >
            Issue invoice
          </Button>
        </div>
      </div>

      {formError && (
        <Callout tone="red" title="Cannot save yet" icon={AlertTriangle}>
          {formError}
        </Callout>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Invoice details"
              description="The place of supply determines whether CGST + SGST or IGST applies."
            />
            <CardBody className="grid gap-4 sm:grid-cols-2">
              <Field label="Invoice number" hint="Leave blank to use the next available number.">
                <Input
                  value={form.number}
                  onChange={(event) => update({ number: event.target.value })}
                  placeholder="Auto-assigned"
                  maxLength={40}
                />
              </Field>
              <Field label="Place of supply" hint="Confirm the state where the supply is taxed.">
                <Select
                  value={form.posCode}
                  onChange={(event) => update({ posCode: event.target.value })}
                >
                  <option value="">Select a state…</option>
                  {stateOptions}
                </Select>
              </Field>
              <Field label="Invoice date">
                <Input
                  type="date"
                  value={form.issueDate}
                  onChange={(event) => {
                    const issueDate = event.target.value;
                    update({
                      issueDate,
                      dueDate: addDays(issueDate, 30),
                    });
                  }}
                />
              </Field>
              <Field label="Due date">
                <Input
                  type="date"
                  value={form.dueDate}
                  min={form.issueDate}
                  onChange={(event) => update({ dueDate: event.target.value })}
                />
              </Field>
              <Field label="Pricing" hint="Inclusive pricing extracts GST from the entered amount.">
                <Select
                  value={form.pricingMode}
                  onChange={(event) =>
                    update({ pricingMode: event.target.value as PricingMode })
                  }
                >
                  <option value="exclusive">Exclusive — GST added to line value</option>
                  <option value="inclusive">Inclusive — GST contained in line value</option>
                </Select>
              </Field>
              <div className="flex items-end">
                <Checkbox
                  label="Round the final invoice total to the nearest rupee."
                  checked={form.roundToRupee}
                  onChange={(checked) => update({ roundToRupee: checked })}
                />
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Customer"
              description="Choose an existing customer or enter billing details for this invoice."
              actions={
                <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[11px] font-semibold">
                  {(["existing", "new"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => update({ customerMode: mode })}
                      className={
                        form.customerMode === mode
                          ? "rounded-md bg-white px-2.5 py-1 text-ink-900 shadow-sm"
                          : "rounded-md px-2.5 py-1 text-slate-500"
                      }
                    >
                      {mode === "existing" ? "Existing" : "New"}
                    </button>
                  ))}
                </div>
              }
            />
            <CardBody className="space-y-4">
              {form.customerMode === "existing" ? (
                <>
                  <Field label="Customer">
                    <Select
                      value={form.customerId}
                      onChange={(event) => {
                        const customer = customers.find(
                          (row) => String(row.id) === event.target.value,
                        );
                        update({
                          customerId: event.target.value,
                          posCode: customer?.state_code || form.posCode,
                        });
                      }}
                    >
                      <option value="">Select a customer…</option>
                      {customers.map((customer) => (
                        <option key={customer.id} value={customer.id}>
                          {customer.name}
                          {customer.company ? ` · ${customer.company}` : ""}
                          {customer.state_code ? ` · ${customer.state_code}` : ""}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {selectedCustomer && (
                    <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-600">
                      <p className="font-semibold text-slate-800">{selectedCustomer.name}</p>
                      <p>{selectedCustomer.email}</p>
                      {selectedCustomer.billing_address && (
                        <p className="whitespace-pre-line">{selectedCustomer.billing_address}</p>
                      )}
                      <p>
                        GSTIN: {selectedCustomer.gstin || "not provided"} · State:{" "}
                        {selectedCustomer.state_code
                          ? `${selectedCustomer.state} (${selectedCustomer.state_code})`
                          : "not provided"}
                      </p>
                      <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-slate-200 pt-3">
                        <div className="min-w-[200px] flex-1">
                          <Field
                            label="Mobile"
                            hint="Used for SMS payment reminders and printed on the invoice."
                          >
                            <Input
                              type="tel"
                              inputMode="tel"
                              value={phoneDraft}
                              onChange={(event) => setPhoneDraft(event.target.value)}
                              placeholder="+91 98765 43210"
                              maxLength={20}
                            />
                          </Field>
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void saveCustomerPhone()}
                          loading={savingPhone}
                          disabled={savingPhone || phoneDraft.trim() === selectedPhone.trim()}
                        >
                          Save mobile
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Customer name" required>
                    <Input
                      value={form.newCustomer.name}
                      onChange={(event) =>
                        update({
                          newCustomer: { ...form.newCustomer, name: event.target.value },
                        })
                      }
                    />
                  </Field>
                  <Field label="Email" required>
                    <Input
                      type="email"
                      value={form.newCustomer.email}
                      onChange={(event) =>
                        update({
                          newCustomer: { ...form.newCustomer, email: event.target.value },
                        })
                      }
                    />
                  </Field>
                  <Field label="Company">
                    <Input
                      value={form.newCustomer.company}
                      onChange={(event) =>
                        update({
                          newCustomer: { ...form.newCustomer, company: event.target.value },
                        })
                      }
                    />
                  </Field>
                  <Field label="Phone">
                    <Input
                      value={form.newCustomer.phone}
                      onChange={(event) =>
                        update({
                          newCustomer: { ...form.newCustomer, phone: event.target.value },
                        })
                      }
                    />
                  </Field>
                  <Field label="Customer GSTIN" hint="Leave blank if the customer is unregistered.">
                    <Input
                      value={form.newCustomer.gstin}
                      onChange={(event) =>
                        update({
                          newCustomer: {
                            ...form.newCustomer,
                            gstin: event.target.value.toUpperCase(),
                          },
                        })
                      }
                      maxLength={15}
                    />
                  </Field>
                  <Field label="State">
                    <Select
                      value={form.newCustomer.stateCode}
                      onChange={(event) => {
                        const state = settings.states.find(
                          (row) => row.code === event.target.value,
                        );
                        update({
                          newCustomer: {
                            ...form.newCustomer,
                            stateCode: event.target.value,
                            state: state?.name ?? "",
                          },
                          posCode: event.target.value || form.posCode,
                        });
                      }}
                    >
                      <option value="">Select a state…</option>
                      {stateOptions}
                    </Select>
                  </Field>
                  <Field label="Address line 1">
                    <Input
                      value={form.newCustomer.address1}
                      onChange={(event) =>
                        update({
                          newCustomer: {
                            ...form.newCustomer,
                            address1: event.target.value,
                          },
                        })
                      }
                    />
                  </Field>
                  <Field label="Address line 2">
                    <Input
                      value={form.newCustomer.address2}
                      onChange={(event) =>
                        update({
                          newCustomer: {
                            ...form.newCustomer,
                            address2: event.target.value,
                          },
                        })
                      }
                    />
                  </Field>
                  <Field label="City">
                    <Input
                      value={form.newCustomer.city}
                      onChange={(event) =>
                        update({
                          newCustomer: { ...form.newCustomer, city: event.target.value },
                        })
                      }
                    />
                  </Field>
                  <Field label="PIN code">
                    <Input
                      value={form.newCustomer.postalCode}
                      onChange={(event) =>
                        update({
                          newCustomer: {
                            ...form.newCustomer,
                            postalCode: event.target.value,
                          },
                        })
                      }
                      maxLength={10}
                    />
                  </Field>
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Items and GST"
              description="Search the catalogue to prefill a line, or type a custom item. Changing a rate here does not alter the saved product default."
              actions={
                <Button
                  variant="outline"
                  size="sm"
                  icon={Plus}
                  onClick={() =>
                    setForm((current) => ({ ...current, lines: [...current.lines, makeLine()] }))
                  }
                >
                  Custom item
                </Button>
              }
            />
            <CardBody className="space-y-3">
              <div className="relative">
                <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2">
                  <PackageSearch className="h-4 w-4 text-slate-400" />
                  <input
                    value={productQuery}
                    onChange={(event) => {
                      setProductQuery(event.target.value);
                      setShowProductResults(true);
                    }}
                    onFocus={() => setShowProductResults(true)}
                    placeholder="Search product catalogue by name, SKU or HSN/SAC…"
                    className="h-5 w-full bg-transparent text-xs text-ink-900 outline-none placeholder:text-slate-400"
                  />
                </div>
                {showProductResults && (
                  <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-pop">
                    {productMatches.length === 0 ? (
                      <p className="px-3 py-3 text-[11px] text-slate-400">
                        No catalogue matches. Add a custom item instead.
                      </p>
                    ) : (
                      productMatches.map((product) => (
                        <button
                          key={product.id}
                          type="button"
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => addProduct(product)}
                          className="flex w-full items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 text-left last:border-0 hover:bg-slate-50"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-[12px] font-semibold text-ink-900">
                              {product.name}
                            </span>
                            <span className="block text-[10px] text-slate-400">
                              {product.sku} · HSN {product.hsn_sac || "—"} · GST{" "}
                              {product.default_gst_rate}%
                            </span>
                          </span>
                          <span className="shrink-0 text-[11px] font-semibold text-slate-600">
                            {moneyExact(product.unit_price, currency)}
                          </span>
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>

              {form.lines.length === 0 ? (
                <EmptyState
                  icon={PackageSearch}
                  title="No items yet"
                  description="Search the catalogue or add a custom item to build the invoice."
                />
              ) : (
                <div className="space-y-3">
                  {form.lines.map((line, index) => {
                    const preview = previewLine(line, form.pricingMode);
                    const rateOptions = activeRates.some(
                      (rate) => Number(rate.rate) === toNumber(line.gstRate),
                    )
                      ? activeRates
                      : [
                          ...activeRates,
                          {
                            id: -1,
                            rate: toNumber(line.gstRate),
                            label: `${line.gstRate}% (current line)`,
                            is_active: true,
                            is_custom: false,
                          },
                        ];
                    return (
                      <div
                        key={line.key}
                        className="rounded-xl border border-slate-200 bg-slate-50/40 p-3"
                      >
                        <div className="flex items-start gap-2">
                          <span className="mt-2 w-5 shrink-0 text-[11px] font-semibold text-slate-400">
                            {index + 1}.
                          </span>
                          <div className="min-w-0 flex-1 space-y-2">
                            <div className="flex items-start gap-2">
                              <Input
                                value={line.name}
                                onChange={(event) =>
                                  updateLine(line.key, { name: event.target.value })
                                }
                                placeholder="Item or service name"
                                className="h-9 flex-1 font-medium"
                              />
                              <button
                                type="button"
                                onClick={() =>
                                  setForm((current) => ({
                                    ...current,
                                    lines: current.lines.filter((row) => row.key !== line.key),
                                  }))
                                }
                                className="mt-0.5 rounded-lg border border-slate-200 p-2 text-slate-400 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600"
                                aria-label={`Remove line ${index + 1}`}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
                              <label className="col-span-2 block text-[10px] font-medium text-slate-500 sm:col-span-1">
                                HSN / SAC
                                <Input
                                  value={line.hsnSac}
                                  onChange={(event) =>
                                    updateLine(line.key, { hsnSac: event.target.value })
                                  }
                                  maxLength={12}
                                  className="mt-0.5 h-8 text-xs"
                                />
                              </label>
                              <label className="block text-[10px] font-medium text-slate-500">
                                Qty
                                <Input
                                  type="number"
                                  min="0.001"
                                  step="0.001"
                                  value={line.quantity}
                                  onChange={(event) =>
                                    updateLine(line.key, { quantity: event.target.value })
                                  }
                                  className="mt-0.5 h-8 text-xs"
                                />
                              </label>
                              <label className="block text-[10px] font-medium text-slate-500">
                                Unit
                                <Input
                                  value={line.unit}
                                  onChange={(event) =>
                                    updateLine(line.key, { unit: event.target.value })
                                  }
                                  maxLength={24}
                                  className="mt-0.5 h-8 text-xs"
                                />
                              </label>
                              <label className="block text-[10px] font-medium text-slate-500">
                                Unit price
                                <Input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={line.unitPrice}
                                  onChange={(event) =>
                                    updateLine(line.key, { unitPrice: event.target.value })
                                  }
                                  className="mt-0.5 h-8 text-xs"
                                />
                              </label>
                              <label className="block text-[10px] font-medium text-slate-500">
                                Discount
                                <Input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={line.discount}
                                  onChange={(event) =>
                                    updateLine(line.key, { discount: event.target.value })
                                  }
                                  className="mt-0.5 h-8 text-xs"
                                />
                              </label>
                              <label className="block text-[10px] font-medium text-slate-500">
                                GST rate
                                <Select
                                  value={line.gstRate}
                                  onChange={(event) =>
                                    updateLine(line.key, { gstRate: event.target.value })
                                  }
                                  className="mt-0.5 h-8 py-0 text-xs"
                                >
                                  {rateOptions.map((rate) => (
                                    <option key={`${rate.id}-${rate.rate}`} value={rate.rate}>
                                      {Number(rate.rate)}%{rate.is_custom ? " custom" : ""}
                                    </option>
                                  ))}
                                </Select>
                              </label>
                              <label className="block text-[10px] font-medium text-slate-500">
                                Type
                                <Select
                                  value={line.itemType}
                                  onChange={(event) =>
                                    updateLine(line.key, {
                                      itemType: event.target.value as "goods" | "services",
                                    })
                                  }
                                  className="mt-0.5 h-8 py-0 text-xs"
                                >
                                  <option value="goods">Goods</option>
                                  <option value="services">Service</option>
                                </Select>
                              </label>
                            </div>
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
                              <span>
                                Taxable{" "}
                                <strong className="text-slate-800">
                                  {moneyExact(preview.taxable, currency)}
                                </strong>
                              </span>
                              <span>
                                GST{" "}
                                <strong className="text-slate-800">
                                  {moneyExact(preview.gst, currency)}
                                </strong>
                              </span>
                              <span>
                                Line total{" "}
                                <strong className="text-slate-800">
                                  {moneyExact(preview.total, currency)}
                                </strong>
                              </span>
                              {line.productId && <Badge tone="slate">Catalogued</Badge>}
                              {preview.invalid && (
                                <span className="font-medium text-rose-600">
                                  Discount exceeds line value.
                                </span>
                              )}
                              <span className="text-[9px] uppercase tracking-wide text-slate-300">
                                live preview
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Other charges" hint="Freight, packaging or other non-taxable additions.">
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.otherCharges}
                    onChange={(event) => update({ otherCharges: event.target.value })}
                  />
                </Field>
                <div />
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Notes and terms" />
            <CardBody className="grid gap-4 sm:grid-cols-2">
              <Field label="Invoice notes">
                <Textarea
                  value={form.notes}
                  onChange={(event) => update({ notes: event.target.value })}
                  rows={3}
                  maxLength={2000}
                  placeholder="Visible on the invoice and PDF."
                />
              </Field>
              <Field label="Terms and conditions">
                <Textarea
                  value={form.terms}
                  onChange={(event) => update({ terms: event.target.value })}
                  rows={3}
                  maxLength={3000}
                  placeholder="Payment terms, declaration or dispute terms."
                />
              </Field>
            </CardBody>
          </Card>
        </div>

        <aside className="space-y-4 self-start xl:sticky xl:top-20">
          <Card>
            <CardHeader
              title="Invoice summary"
              actions={
                calc ? (
                  <Badge tone="green">Backend verified</Badge>
                ) : (
                  <Badge tone="amber">{calculating ? "Calculating…" : "Preview only"}</Badge>
                )
              }
            />
            <CardBody className="space-y-2 text-[12px]">
              <SummaryRow label="Subtotal" value={moneyExact(totalsForSummary.subtotal, currency)} />
              <SummaryRow
                label="Discounts"
                value={`-${moneyExact(totalsForSummary.discount, currency)}`}
              />
              <SummaryRow
                label="Taxable value"
                value={moneyExact(totalsForSummary.taxable, currency)}
              />
              {calc ? (
                isInterState ? (
                  <SummaryRow label="IGST" value={moneyExact(totalsForSummary.igst, currency)} />
                ) : (
                  <>
                    <SummaryRow label="CGST" value={moneyExact(totalsForSummary.cgst, currency)} />
                    <SummaryRow label="SGST" value={moneyExact(totalsForSummary.sgst, currency)} />
                  </>
                )
              ) : (
                <SummaryRow
                  label={form.posCode ? "GST (split pending)" : "GST (place of supply required)"}
                  value={moneyExact(localTotals.gst, currency)}
                />
              )}
              <SummaryRow
                label="Other charges"
                value={moneyExact(totalsForSummary.other, currency)}
              />
              <SummaryRow
                label="Rounding"
                value={moneyExact(totalsForSummary.rounding, currency)}
              />
              <div className="flex items-center justify-between border-t border-slate-200 pt-2 text-[14px] font-bold text-ink-900">
                <span>Total</span>
                <span>{moneyExact(totalsForSummary.total, currency)}</span>
              </div>
              {calc && (
                <p className="pt-1 text-[10px] leading-relaxed text-slate-400">
                  {calc.supply_type_label} · {calc.place_of_supply.state} (
                  {calc.place_of_supply.state_code})
                </p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Verification" />
            <CardBody className="space-y-3">
              {invoice?.supply_type === "unverified" && (
                <Callout tone="amber" title="GST classification not verified" icon={AlertTriangle}>
                  This invoice was saved before the supplier state and place of supply were
                  recorded. Choose the place of supply and save so a verified CGST/SGST or IGST
                  split is stored.
                </Callout>
              )}
              {!settings.ready && (
                <Callout tone="amber" title="Business GST state missing" icon={AlertTriangle}>
                  Set your business state under GST setup before issuing an invoice. The state
                  decides the CGST/SGST or IGST split.
                </Callout>
              )}
              {calcError && (
                <Callout tone="red" title="Backend calculation blocked" icon={AlertTriangle}>
                  {calcError}
                </Callout>
              )}
              {calc?.warnings.map((warning) => (
                <Callout key={warning} tone="amber" title="Please verify" icon={AlertTriangle}>
                  {warning}
                </Callout>
              ))}
              <Checkbox
                checked={form.confirm}
                onChange={(checked) => update({ confirm: checked })}
                label={
                  <span>
                    I verified the supplier state, place of supply and the GST rate and HSN/SAC
                    classification for every item. FINOVEXA does not guess legal tax treatment.
                  </span>
                }
              />
              <div className="flex items-center gap-1.5 rounded-lg bg-slate-50 px-2.5 py-2 text-[10px] text-slate-500">
                <Calculator className="h-3.5 w-3.5 shrink-0" />
                Saved invoices keep the tax values calculated at issue time.
              </div>
              <div className="flex items-center gap-1.5 rounded-lg bg-slate-50 px-2.5 py-2 text-[10px] text-slate-500">
                <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
                Totals must reconcile before the backend saves the invoice.
              </div>
            </CardBody>
          </Card>
        </aside>
      </div>

      {previewOpen && previewInvoice && (
        <Modal
          open
          onClose={() => setPreviewOpen(false)}
          title="Invoice preview"
          description="Preview only. The backend recalculates and validates every amount when you save."
          size="xl"
          footer={
            <>
              <Button variant="outline" onClick={() => setPreviewOpen(false)}>
                Close
              </Button>
              <Button
                variant="outline"
                icon={Eye}
                onClick={() => printInvoiceDocument("invoice-preview")}
              >
                Print preview
              </Button>
            </>
          }
        >
          <div className="rounded-xl bg-slate-100 p-2 sm:p-4">
            <InvoiceDocument
              invoice={previewInvoice}
              id="invoice-preview"
              logoUrl={settings.business.logo_data_url}
            />
          </div>
        </Modal>
      )}

      <p className="text-center text-[10px] text-slate-400">
        Invoice date {formatDate(form.issueDate)} · Due {formatDate(form.dueDate)} · Amounts in{" "}
        {currency}
      </p>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-800">{value}</span>
    </div>
  );
}
