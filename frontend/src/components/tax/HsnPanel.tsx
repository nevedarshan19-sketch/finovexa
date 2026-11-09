import { useState } from "react";
import { CheckCircle2, Pencil, Plus, ShieldAlert, Trash2 } from "lucide-react";
import { api, getErrorMessage, post, put } from "../../lib/api";
import { useApi } from "../../hooks/useApi";
import { useToast } from "../../context/ToastContext";
import type { HsnClassification, TaxGstOptions } from "../../lib/taxTypes";
import { plainPct } from "../../lib/utils";
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

interface HsnForm {
  code: string;
  description: string;
  kind: "goods" | "services";
  gst_rate: string;
  verified: boolean;
  note: string;
}

const blankForm: HsnForm = {
  code: "",
  description: "",
  kind: "goods",
  gst_rate: "18",
  verified: false,
  note: "",
};

export function HsnPanel({
  options,
  onChanged,
}: {
  options: TaxGstOptions;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const hsn = useApi<{ items: HsnClassification[]; coverage: TaxGstOptions["hsn_coverage"]; note: string }>(
    "/tax/gst/hsn",
  );
  const [form, setForm] = useState<HsnForm>(blankForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<HsnClassification | null>(null);

  const set = <K extends keyof HsnForm>(key: K, value: HsnForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const reset = () => {
    setForm(blankForm);
    setEditingId(null);
    setError(null);
  };

  const startEdit = (row: HsnClassification) => {
    setEditingId(row.id);
    setError(null);
    setForm({
      code: row.code,
      description: row.description,
      kind: row.kind,
      gst_rate: String(row.gst_rate),
      verified: row.verified,
      note: row.note ?? "",
    });
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    const payload = { ...form, note: form.note || null };
    try {
      if (editingId === null) {
        await post("/tax/gst/hsn", payload);
        toast({ title: `HSN/SAC ${form.code} stored`, tone: "success" });
      } else {
        await put(`/tax/gst/hsn/${editingId}`, payload);
        toast({ title: `HSN/SAC ${form.code} updated`, tone: "success" });
      }
      reset();
      hsn.reload();
      onChanged();
    } catch (err: unknown) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: HsnClassification) => {
    try {
      await api(`/tax/gst/hsn/${row.id}`, { method: "DELETE" });
      toast({ title: `HSN/SAC ${row.code} deleted`, tone: "success" });
      if (editingId === row.id) reset();
      hsn.reload();
      onChanged();
    } catch (err: unknown) {
      toast({ title: "Could not delete the code", description: getErrorMessage(err), tone: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const coverage = hsn.data?.coverage ?? options.hsn_coverage;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Stored classifications" value={hsn.data?.items.length ?? 0} tone="blue" icon={CheckCircle2} />
        <StatCard label="Verified codes" value={coverage.verified_codes} tone="green" icon={CheckCircle2} />
        <StatCard
          label="Invoice lines without HSN"
          value={coverage.lines_without_hsn}
          sub={`${coverage.invoice_lines} lines in total`}
          tone={coverage.lines_without_hsn > 0 ? "amber" : "slate"}
          icon={ShieldAlert}
        />
      </div>

      <Callout tone="amber" title="Classification is yours to confirm" icon={ShieldAlert}>
        FINOVEXA stores the code and rate you enter. It does not look them up or guess them. Mark a code
        verified only after checking the GST rate notification that applies to that goods or service.
      </Callout>

      <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
        <Card>
          <CardHeader
            title={editingId === null ? "Add a classification" : "Edit classification"}
            description="HSN for goods, SAC for services"
            icon={Plus}
            actions={
              editingId !== null ? (
                <Button size="sm" variant="ghost" onClick={reset}>
                  Cancel
                </Button>
              ) : undefined
            }
          />
          <CardBody className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label={form.kind === "goods" ? "HSN code" : "SAC code"} required>
                <Input
                  inputMode="numeric"
                  value={form.code}
                  maxLength={8}
                  onChange={(event) => set("code", event.target.value)}
                  placeholder={form.kind === "goods" ? "940330" : "998314"}
                />
              </Field>
              <Field label="Kind">
                <Select value={form.kind} onChange={(event) => set("kind", event.target.value as HsnForm["kind"])}>
                  <option value="goods">Goods (HSN)</option>
                  <option value="services">Services (SAC)</option>
                </Select>
              </Field>
            </div>
            <Field label="Description" required>
              <Input value={form.description} onChange={(event) => set("description", event.target.value)} />
            </Field>
            <Field label="GST rate" hint="Confirm against the notification before relying on it">
              <Select value={form.gst_rate} onChange={(event) => set("gst_rate", event.target.value)}>
                {["0", "5", "12", "18", "28"].map((rate) => (
                  <option key={rate} value={rate}>
                    {rate}%
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Note">
              <Textarea rows={2} value={form.note} onChange={(event) => set("note", event.target.value)} />
            </Field>
            <Checkbox
              checked={form.verified}
              onChange={(checked) => set("verified", checked)}
              label="I have verified this code and rate against the GST notification"
            />
            {error && <Callout tone="red" title="Could not save">{error}</Callout>}
            <Button icon={editingId === null ? Plus : Pencil} loading={busy} onClick={() => void submit()}>
              {editingId === null ? "Add classification" : "Save changes"}
            </Button>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Verified HSN / SAC list" description="Used as a reference when you invoice" />
          <CardBody className="pt-3">
            {hsn.loading && !hsn.data ? (
              <p className="py-8 text-center text-sm text-slate-500">Loading classifications…</p>
            ) : hsn.data && hsn.data.items.length === 0 ? (
              <EmptyState
                title="No classifications stored"
                description="Add the codes you actually sell, with the rate you have confirmed."
              />
            ) : hsn.data ? (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Code</TH>
                    <TH>Description</TH>
                    <TH>Kind</TH>
                    <TH className="text-right">Rate</TH>
                    <TH>Status</TH>
                    <TH className="text-right">Actions</TH>
                  </TR>
                </THead>
                <TBody>
                  {hsn.data.items.map((row) => (
                    <TR key={row.id}>
                      <TD className="font-semibold text-ink-900">{row.code}</TD>
                      <TD>{row.description}</TD>
                      <TD>{row.kind === "goods" ? "HSN" : "SAC"}</TD>
                      <TD className="text-right">{plainPct(row.gst_rate)}</TD>
                      <TD>
                        <Badge tone={row.verified ? "green" : "amber"}>{row.verified ? "verified" : "unverified"}</Badge>
                      </TD>
                      <TD>
                        <div className="flex justify-end gap-1">
                          <Button size="icon" variant="ghost" aria-label={`Edit ${row.code}`} onClick={() => startEdit(row)}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Delete ${row.code}`}
                            onClick={() => setPendingDelete(row)}
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
            {hsn.data && <p className="mt-4 text-[11px] leading-relaxed text-slate-400">{hsn.data.note}</p>}
          </CardBody>
        </Card>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete HSN/SAC ${pendingDelete?.code ?? ""}?`}
        description="Existing invoices keep the code they were issued with; only the reference entry is removed."
        confirmLabel="Delete code"
        tone="danger"
        onClose={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) void remove(pendingDelete);
        }}
      />
    </div>
  );
}
