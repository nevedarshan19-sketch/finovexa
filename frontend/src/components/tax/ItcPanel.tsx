import { useState } from "react";
import { Ban, CheckCircle2, Plus, ReceiptText, Trash2 } from "lucide-react";
import { api, getErrorMessage, post } from "../../lib/api";
import { useApi } from "../../hooks/useApi";
import { useToast } from "../../context/ToastContext";
import type { ItcSummary } from "../../lib/taxTypes";
import { formatDate, money, moneyExact } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
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

const STATUS_TONES: Record<string, "green" | "blue" | "red"> = {
  eligible: "green",
  claimed: "blue",
  blocked: "red",
};

interface ItcForm {
  supplier_name: string;
  supplier_gstin: string;
  invoice_number: string;
  invoice_date: string;
  taxable_value: string;
  gst_rate: string;
  cgst_amount: string;
  sgst_amount: string;
  igst_amount: string;
  status: "eligible" | "claimed" | "blocked";
  note: string;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function blankForm(): ItcForm {
  return {
    supplier_name: "",
    supplier_gstin: "",
    invoice_number: "",
    invoice_date: todayIso(),
    taxable_value: "",
    gst_rate: "18",
    cgst_amount: "",
    sgst_amount: "",
    igst_amount: "",
    status: "eligible",
    note: "",
  };
}

export function ItcPanel({ currency = "INR" }: { currency?: string }) {
  const { toast } = useToast();
  const [form, setForm] = useState<ItcForm>(blankForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);
  const summary = useApi<ItcSummary>("/tax/gst/itc");

  const set = <K extends keyof ItcForm>(key: K, value: ItcForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const autoSplit = () => {
    const taxable = Number(form.taxable_value || 0);
    const rate = Number(form.gst_rate || 0);
    const total = Math.round(((taxable * rate) / 100) * 100) / 100;
    const half = Math.round((total / 2) * 100) / 100;
    setForm((current) => ({
      ...current,
      cgst_amount: String(half),
      sgst_amount: String(total - half),
      igst_amount: "0",
    }));
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await post("/tax/gst/itc", {
        supplier_name: form.supplier_name,
        supplier_gstin: form.supplier_gstin || null,
        invoice_number: form.invoice_number,
        invoice_date: form.invoice_date,
        taxable_value: form.taxable_value || "0",
        gst_rate: form.gst_rate,
        cgst_amount: form.cgst_amount || "0",
        sgst_amount: form.sgst_amount || "0",
        igst_amount: form.igst_amount || "0",
        status: form.status,
        note: form.note || null,
      });
      toast({ title: "Input credit recorded", tone: "success" });
      setForm(blankForm());
      summary.reload();
    } catch (err: unknown) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const changeStatus = async (id: number, status: string) => {
    try {
      await api(`/tax/gst/itc/${id}?status=${status}`, { method: "PATCH" });
      toast({ title: `Entry marked ${status}`, tone: "success" });
      summary.reload();
    } catch (err: unknown) {
      toast({ title: "Could not update the entry", description: getErrorMessage(err), tone: "error" });
    }
  };

  const remove = async (id: number) => {
    try {
      await api(`/tax/gst/itc/${id}`, { method: "DELETE" });
      toast({ title: "Input-credit entry deleted", tone: "success" });
      summary.reload();
    } catch (err: unknown) {
      toast({ title: "Could not delete the entry", description: getErrorMessage(err), tone: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  return (
    <div className="space-y-4">
      {summary.data && (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard label="Available input credit" value={money(summary.data.available_itc, currency)} tone="green" icon={CheckCircle2} />
          <StatCard
            label="Eligible entries"
            value={summary.data.by_status.find((row) => row.status === "eligible")?.count ?? 0}
            tone="blue"
            icon={ReceiptText}
          />
          <StatCard
            label="Blocked credit"
            value={money(summary.data.by_status.find((row) => row.status === "blocked")?.eligible_amount ?? 0, currency)}
            tone="red"
            icon={Ban}
          />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Record a purchase bill" description="Credit is only counted once the invoice supports it" icon={Plus} />
          <CardBody className="space-y-3">
            <Field label="Supplier name" required>
              <Input value={form.supplier_name} onChange={(event) => set("supplier_name", event.target.value)} />
            </Field>
            <Field label="Supplier GSTIN" hint="Optional, but validated when entered">
              <Input
                value={form.supplier_gstin}
                onChange={(event) => set("supplier_gstin", event.target.value.toUpperCase())}
                placeholder="27ABCDE1234F1Z5"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Invoice number" required>
                <Input value={form.invoice_number} onChange={(event) => set("invoice_number", event.target.value)} />
              </Field>
              <Field label="Invoice date" required>
                <Input type="date" value={form.invoice_date} max={todayIso()} onChange={(event) => set("invoice_date", event.target.value)} />
              </Field>
              <Field label="Taxable value">
                <Input inputMode="decimal" value={form.taxable_value} onChange={(event) => set("taxable_value", event.target.value)} />
              </Field>
              <Field label="GST rate">
                <Select value={form.gst_rate} onChange={(event) => set("gst_rate", event.target.value)}>
                  {["0", "5", "12", "18", "28"].map((rate) => (
                    <option key={rate} value={rate}>
                      {rate}%
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Button size="sm" variant="outline" onClick={autoSplit}>
              Split GST across CGST and SGST
            </Button>
            <div className="grid grid-cols-3 gap-2">
              <Field label="CGST">
                <Input inputMode="decimal" value={form.cgst_amount} onChange={(event) => set("cgst_amount", event.target.value)} />
              </Field>
              <Field label="SGST">
                <Input inputMode="decimal" value={form.sgst_amount} onChange={(event) => set("sgst_amount", event.target.value)} />
              </Field>
              <Field label="IGST">
                <Input inputMode="decimal" value={form.igst_amount} onChange={(event) => set("igst_amount", event.target.value)} />
              </Field>
            </div>
            <Field label="Status">
              <Select value={form.status} onChange={(event) => set("status", event.target.value as ItcForm["status"])}>
                <option value="eligible">Eligible</option>
                <option value="claimed">Claimed</option>
                <option value="blocked">Blocked</option>
              </Select>
            </Field>
            <Field label="Note">
              <Textarea rows={2} value={form.note} onChange={(event) => set("note", event.target.value)} />
            </Field>
            {error && <Callout tone="red" title="Could not save">{error}</Callout>}
            <Button icon={Plus} loading={busy} onClick={() => void submit()}>
              Add input credit
            </Button>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Input-credit ledger" description="Every purchase bill you have recorded" />
          <CardBody className="pt-3">
            {summary.loading && !summary.data ? (
              <p className="py-8 text-center text-sm text-slate-500">Loading input credit…</p>
            ) : summary.error && !summary.data ? (
              <ErrorState message={summary.error} onRetry={summary.reload} />
            ) : summary.data && summary.data.entries.length === 0 ? (
              <EmptyState
                title="No purchase bills yet"
                description="Record a supplier invoice to track the input tax credit you can set off."
              />
            ) : summary.data ? (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Supplier</TH>
                    <TH>Invoice</TH>
                    <TH className="text-right">Taxable</TH>
                    <TH className="text-right">GST</TH>
                    <TH className="text-right">Eligible</TH>
                    <TH>Status</TH>
                    <TH className="text-right">Actions</TH>
                  </TR>
                </THead>
                <TBody>
                  {summary.data.entries.map((entry) => (
                    <TR key={entry.id}>
                      <TD>
                        <p className="font-semibold text-ink-900">{entry.supplier_name}</p>
                        {entry.supplier_gstin && (
                          <p className="text-[11px] text-slate-400">{entry.supplier_gstin}</p>
                        )}
                      </TD>
                      <TD>
                        <p>{entry.invoice_number}</p>
                        <p className="text-[11px] text-slate-400">{formatDate(entry.invoice_date)}</p>
                      </TD>
                      <TD className="text-right tabular">{moneyExact(entry.taxable_value, currency)}</TD>
                      <TD className="text-right tabular">
                        {moneyExact(entry.cgst_amount + entry.sgst_amount + entry.igst_amount, currency)}
                      </TD>
                      <TD className="text-right tabular font-semibold">{moneyExact(entry.eligible_amount, currency)}</TD>
                      <TD>
                        <Badge tone={STATUS_TONES[entry.status] ?? "slate"}>{entry.status}</Badge>
                      </TD>
                      <TD>
                        <div className="flex justify-end gap-1">
                          {entry.status !== "claimed" && (
                            <Button size="sm" variant="ghost" onClick={() => void changeStatus(entry.id, "claimed")}>
                              Claim
                            </Button>
                          )}
                          {entry.status !== "blocked" && (
                            <Button size="sm" variant="ghost" onClick={() => void changeStatus(entry.id, "blocked")}>
                              Block
                            </Button>
                          )}
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Delete entry ${entry.invoice_number}`}
                            onClick={() => setPendingDelete(entry.id)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            ) : null}
            {summary.data && (
              <p className="mt-4 text-[11px] leading-relaxed text-slate-400">{summary.data.note}</p>
            )}
          </CardBody>
        </Card>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this input-credit entry?"
        description="The credit will stop counting towards your net GST position. This cannot be undone."
        confirmLabel="Delete entry"
        tone="danger"
        onClose={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete !== null) void remove(pendingDelete);
        }}
      />
    </div>
  );
}
