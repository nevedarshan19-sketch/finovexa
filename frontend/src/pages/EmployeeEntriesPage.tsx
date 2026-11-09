import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  Banknote,
  FilePlus2,
  Lock,
  Minus,
  Pencil,
  Plus,
  RefreshCw,
  ShoppingBag,
  Trash2,
  TrendingUp,
  Undo2,
  Wallet,
} from "lucide-react";
import { StockItemCombobox, type StockItem } from "../components/StockItemCombobox";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, patch, post } from "../lib/api";
import type { EmployeeEntry, EmployeeEntriesResponse } from "../lib/types";
import { formatDate, formatDateTime, money } from "../lib/utils";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
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

type EntryTab = "all" | "sale" | "purchase";
type EntryKind = "sale" | "purchase";
type SaleMethod = "cash" | "upi" | "bank" | "card" | "paypal" | "other";

const SALE_METHODS: { value: SaleMethod; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "upi", label: "UPI" },
  { value: "bank", label: "Bank transfer" },
  { value: "card", label: "Card" },
  { value: "paypal", label: "PayPal (recorded manually)" },
  { value: "other", label: "Other" },
];

const TYPE_META = {
  invoice: { label: "Invoice", tone: "blue" as const },
  sale: { label: "Sale", tone: "green" as const },
  purchase: { label: "Purchase", tone: "amber" as const },
};

interface EntryLineDraft {
  key: number;
  description: string;
  quantity: string;
  unit_price: string;
  product_id: number | null;
  gst_rate: number | null;
}

interface EntryDraft {
  entryType: EntryKind;
  counterparty: string;
  counterpartyEmail: string;
  counterpartyPhone: string;
  lines: EntryLineDraft[];
  category: string;
  paymentMethod: SaleMethod;
  entryDate: string;
  notes: string;
}

let entryLineKey = 1;

function nextEntryLineKey(): number {
  entryLineKey += 1;
  return entryLineKey;
}

function localToday(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function newEntryLine(): EntryLineDraft {
  return {
    key: nextEntryLineKey(),
    description: "",
    quantity: "1",
    unit_price: "",
    product_id: null,
    gst_rate: null,
  };
}

function blankDraft(entryType: EntryKind = "sale"): EntryDraft {
  return {
    entryType,
    counterparty: "",
    counterpartyEmail: "",
    counterpartyPhone: "",
    lines: [newEntryLine()],
    category: "",
    paymentMethod: "cash",
    entryDate: localToday(),
    notes: "",
  };
}

function draftFromEntry(entry: EmployeeEntry): EntryDraft {
  return {
    entryType: entry.entry_type === "purchase" ? "purchase" : "sale",
    counterparty: entry.counterparty,
    counterpartyEmail: entry.counterparty_email ?? "",
    counterpartyPhone: entry.counterparty_phone ?? "",
    lines:
      entry.items.length > 0
        ? entry.items.map((item) => ({
            key: nextEntryLineKey(),
            description: item.description,
            quantity: String(item.quantity),
            unit_price: String(item.unit_price),
            product_id: item.product_id ?? null,
            gst_rate: item.gst_rate ?? null,
          }))
        : [
            {
              key: nextEntryLineKey(),
              description: entry.description,
              quantity: "1",
              unit_price: String(entry.amount),
              product_id: null,
              gst_rate: null,
            },
          ],
    category: entry.category || "",
    paymentMethod: (entry.payment_method as SaleMethod) || "cash",
    entryDate: entry.entry_date,
    notes: entry.notes || "",
  };
}

function draftLines(draft: EntryDraft): EntryLineDraft[] {
  return draft.lines.filter(
    (line) =>
      line.description.trim().length > 0 &&
      Number(line.quantity) > 0 &&
      Number(line.unit_price) >= 0,
  );
}

function lineTotal(line: EntryLineDraft): number {
  const quantity = Number(line.quantity);
  const price = Number(line.unit_price);
  if (!Number.isFinite(quantity) || !Number.isFinite(price)) return 0;
  return Math.max(0, quantity) * Math.max(0, price);
}

function draftTotal(draft: EntryDraft): number {
  return draftLines(draft).reduce((total, line) => total + lineTotal(line), 0);
}

function lineGst(line: EntryLineDraft): number {
  return (lineTotal(line) * (line.gst_rate ?? 0)) / 100;
}

function draftGst(draft: EntryDraft): number {
  if (draft.entryType === "purchase") return 0;
  return draftLines(draft).reduce((total, line) => total + lineGst(line), 0);
}

function draftDescription(draft: EntryDraft): string {
  const first = draftLines(draft)[0]?.description.trim() ?? "";
  if (first.length >= 2) return first.slice(0, 255);
  const fallback =
    draft.entryType === "purchase"
      ? `Purchase from ${draft.counterparty.trim()}`
      : `Sale to ${draft.counterparty.trim()}`;
  return fallback.slice(0, 255);
}

export function EmployeeEntriesPage() {
  const { business } = useAuth();
  const { toast } = useToast();
  const entriesApi = useApi<EmployeeEntriesResponse>(
    "/employee/entries?entry_type=all&status=all",
    { pollMs: 20000 },
  );
  const [tab, setTab] = useState<EntryTab>("all");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EmployeeEntry | null>(null);
  const [draft, setDraft] = useState<EntryDraft>(blankDraft());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [voidTarget, setVoidTarget] = useState<EmployeeEntry | null>(null);
  const [voiding, setVoiding] = useState(false);

  const currency = business?.currency || "INR";
  const allEntries = entriesApi.data?.items ?? [];
  const entries = useMemo(
    () => allEntries.filter((entry) => entry.entry_type !== "invoice"),
    [allEntries],
  );
  const visible = useMemo(
    () =>
      tab === "all" ? entries : entries.filter((entry) => entry.entry_type === tab),
    [entries, tab],
  );
  const sales = entries.filter((entry) => entry.entry_type === "sale" && entry.status !== "void");
  const purchases = entries.filter(
    (entry) => entry.entry_type === "purchase" && entry.status !== "void",
  );
  const salesTotal = sales.reduce((total, entry) => total + entry.amount, 0);
  const purchasesTotal = purchases.reduce((total, entry) => total + entry.amount, 0);
  const openReceivables = allEntries
    .filter((entry) => entry.entry_type === "invoice" && entry.status !== "void")
    .reduce((total, entry) => total + (entry.invoice_outstanding || 0), 0);

  const locked = editing ? !editing.editable : false;

  const openCreate = (entryType: EntryKind) => {
    setEditing(null);
    setDraft(blankDraft(entryType));
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

  const patchLine = (key: number, patch: Partial<EntryLineDraft>) =>
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    }));

  const pickStockItem = (key: number, item: StockItem) =>
    patchLine(key, {
      description: item.name,
      unit_price: String(item.unit_price),
      product_id: item.id,
      gst_rate: item.gst_rate ?? null,
    });

  const fillPriceFromStock = (key: number, item: StockItem) =>
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
    const usableLines = draftLines(draft);
    if (!editing || editing.editable) {
      if (usableLines.length === 0) {
        setFormError("Add at least one item with a description, quantity and unit price.");
        return;
      }
      if (draftTotal(draft) <= 0) {
        setFormError("The bill total must be greater than zero.");
        return;
      }
    }
    const items = usableLines.map((line) => ({
      description: line.description.trim(),
      quantity: Number(line.quantity),
      unit_price: Number(line.unit_price),
      product_id: line.product_id,
      gst_rate: line.gst_rate,
    }));
    setSaving(true);
    try {
      if (editing) {
        const payload: Record<string, unknown> = { notes: draft.notes };
        if (editing.editable) {
          payload.counterparty = draft.counterparty.trim();
          payload.description = draftDescription(draft);
          payload.items = items;
          payload.entry_date = draft.entryDate;
          if (draft.entryType === "purchase") {
            payload.category = draft.category.trim() || "Purchases";
          } else {
            payload.payment_method = draft.paymentMethod;
            if (draft.counterpartyEmail.trim()) {
              payload.counterparty_email = draft.counterpartyEmail.trim();
            }
            payload.counterparty_phone = draft.counterpartyPhone.trim() || null;
          }
        }
        const result = await patch<{ entry: EmployeeEntry; message: string }>(
          `/employee/entries/${editing.id}`,
          payload,
        );
        toast({ title: "Entry updated", description: result.message, tone: "success" });
      } else {
        const payload: Record<string, unknown> = {
          entry_type: draft.entryType,
          counterparty: draft.counterparty.trim(),
          description: draftDescription(draft),
          items,
          entry_date: draft.entryDate,
          notes: draft.notes.trim() || null,
          tax_rate: 0,
        };
        if (draft.entryType === "purchase") {
          payload.category = draft.category.trim() || "Purchases";
        } else {
          payload.payment_method = draft.paymentMethod;
          if (draft.counterpartyEmail.trim()) {
            payload.counterparty_email = draft.counterpartyEmail.trim();
          }
          if (draft.counterpartyPhone.trim()) {
            payload.counterparty_phone = draft.counterpartyPhone.trim();
          }
        }
        const result = await post<{ entry: EmployeeEntry; message: string }>(
          "/employee/entries",
          payload,
        );
        toast({ title: "Entry submitted", description: result.message, tone: "success" });
      }
      setEditorOpen(false);
      setEditing(null);
      entriesApi.reload();
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
      toast({ title: "Entry voided", description: result.message, tone: "success" });
      setVoidTarget(null);
      entriesApi.reload();
    } catch (err) {
      toast({ title: "Could not void entry", description: getErrorMessage(err), tone: "error" });
    } finally {
      setVoiding(false);
    }
  };

  if (entriesApi.loading && !entriesApi.data) return <PageSkeleton cards={4} />;
  if (entriesApi.error && !entriesApi.data) {
    return <ErrorState message={entriesApi.error} onRetry={entriesApi.reload} />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Employee workspace · entries"
        title="Sales & purchase entries"
        description="Record money that already moved. Sale receipts and purchase costs post to the owner's ledger immediately."
        actions={
          <>
            <Button
              variant="outline"
              icon={RefreshCw}
              onClick={entriesApi.reload}
              loading={entriesApi.loading}
            >
              Refresh
            </Button>
            <Button variant="secondary" icon={ShoppingBag} onClick={() => openCreate("purchase")}>
              Log purchase
            </Button>
            <Button icon={TrendingUp} onClick={() => openCreate("sale")}>
              Record sale
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Paid sales recorded"
          value={money(salesTotal, currency)}
          icon={TrendingUp}
          changeLabel={`${sales.length} sale entries`}
          tone="green"
        />
        <StatCard
          label="Purchases logged"
          value={money(purchasesTotal, currency)}
          icon={ShoppingBag}
          changeLabel={`${purchases.length} purchase entries`}
          tone="amber"
        />
        <StatCard
          label="Open receivables"
          value={money(openReceivables, currency)}
          icon={Wallet}
          changeLabel="From invoices you generated"
          tone="blue"
        />
        <StatCard
          label="Voided entries"
          value={String(entries.filter((entry) => entry.status === "void").length)}
          icon={Undo2}
          changeLabel="Reversed from the owner ledger"
          tone="slate"
        />
      </div>

      <Callout tone="amber" title="Attribution and trust">
        Every entry is stamped with your name. Cash and PayPal receipts you record are posted as
        employee-recorded, not provider-verified. Entries with confirmed cash can only be edited by the
        owner after a payment reversal.
      </Callout>

      <Card>
        <CardHeader
          title="Your entry history"
          description="Only the sale and purchase entries you created are shown here."
          icon={FilePlus2}
          actions={
            <Tabs<EntryTab>
              items={[
                { key: "all", label: "All", count: entries.length },
                { key: "sale", label: "Sales", count: sales.length },
                { key: "purchase", label: "Purchases", count: purchases.length },
              ]}
              value={tab}
              onChange={setTab}
              size="sm"
            />
          }
        />
        <div className="mt-3">
          {visible.length === 0 ? (
            <EmptyState
              icon={Banknote}
              title={entries.length ? "No entries in this view" : "No sale or purchase entries yet"}
              description={
                entries.length
                  ? "Switch tabs to see the rest of your entries."
                  : "Record a paid sale or a purchase to update the owner's ledger."
              }
              action={
                <Button size="sm" icon={TrendingUp} onClick={() => openCreate("sale")}>
                  Record the first sale
                </Button>
              }
            />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Reference</TH>
                  <TH>Counterparty</TH>
                  <TH>Method</TH>
                  <TH>Date</TH>
                  <TH className="text-right">Amount</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {visible.map((entry) => {
                  const meta = TYPE_META[entry.entry_type];
                  return (
                    <TR key={entry.id}>
                      <TD>
                        <span className="font-mono text-[11.5px] font-semibold text-ink-900">
                          {entry.reference}
                        </span>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          {formatDateTime(entry.created_at)}
                        </p>
                      </TD>
                      <TD>
                        <p className="text-[12px] font-medium text-ink-900">{entry.counterparty}</p>
                        <p className="max-w-[260px] truncate text-[10px] text-slate-400">
                          {entry.description}
                        </p>
                        {entry.items.length > 0 && (
                          <p className="text-[10px] text-slate-400">
                            {entry.items.length} item{entry.items.length === 1 ? "" : "s"} ·{" "}
                            {entry.items.reduce((total, item) => total + item.quantity, 0)} qty
                          </p>
                        )}
                      </TD>
                      <TD>
                        {entry.entry_type === "sale" && entry.payment_method ? (
                          <Badge tone={entry.payment_method === "paypal" ? "violet" : "slate"}>
                            {entry.payment_method === "paypal"
                              ? "PayPal · unverified"
                              : entry.payment_method.toUpperCase()}
                          </Badge>
                        ) : (
                          <span className="text-[11px] text-slate-400">{entry.category || "Purchases"}</span>
                        )}
                      </TD>
                      <TD>
                        <span className="text-[11px] text-slate-500">{formatDate(entry.entry_date)}</span>
                      </TD>
                      <TD className="text-right">
                        <span className="text-[12px] font-semibold tabular-nums text-ink-900">
                          {money(entry.amount, entry.currency || currency)}
                        </span>
                      </TD>
                      <TD>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge tone={meta.tone}>{meta.label}</Badge>
                          {entry.status === "void" && <Badge tone="red">VOID</Badge>}
                          {entry.status !== "void" && !entry.editable && (
                            <Badge tone="amber" dot title={entry.lock_reason || undefined}>
                              Locked
                            </Badge>
                          )}
                        </div>
                        {entry.status !== "void" && !entry.editable && entry.lock_reason && (
                          <p className="mt-1 max-w-[220px] text-[10px] leading-relaxed text-amber-700">
                            {entry.lock_reason}
                          </p>
                        )}
                      </TD>
                      <TD className="text-right">
                        <div className="inline-flex items-center gap-1.5">
                          {entry.status !== "void" && (
                            <Button
                              variant="outline"
                              size="sm"
                              icon={entry.editable ? Pencil : Lock}
                              onClick={() => openEdit(entry)}
                              title={entry.lock_reason || "Edit entry"}
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
                  );
                })}
              </TBody>
            </TableWrap>
          )}
        </div>
      </Card>

      <p className="text-right text-[10px] text-slate-400">
        Need to bill a customer without payment?{" "}
        <Link to="/employee/invoices" className="font-semibold text-brand-600 hover:text-brand-700">
          Generate an invoice
        </Link>
      </p>

      <Modal
        open={editorOpen}
        onClose={closeEditor}
        title={editing ? `Edit ${editing.reference}` : draft.entryType === "purchase" ? "Log a purchase" : "Record a paid sale"}
        description={
          locked
            ? "Confirmed cash is attached to this entry. Only notes can be changed."
            : draft.entryType === "purchase"
              ? "Add every item on the bill with its quantity and unit price. The total reduces recorded cash and increases operating expenses."
              : "Add every item on the bill with its quantity and unit price. The total creates a paid invoice in the owner's ledger."
        }
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={closeEditor} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" form="entry-form" loading={saving}>
              {editing ? "Save changes" : draft.entryType === "purchase" ? "Log purchase" : "Submit sale"}
            </Button>
          </>
        }
      >
        <form id="entry-form" className="space-y-4" onSubmit={save}>
          {!editing && (
            <Tabs<EntryKind>
              items={[
                { key: "sale", label: "Paid sale" },
                { key: "purchase", label: "Purchase" },
              ]}
              value={draft.entryType}
              onChange={(entryType) =>
                setDraft((current) => ({
                  ...current,
                  entryType,
                  category:
                    entryType === "purchase" && !current.category
                      ? "Purchases"
                      : current.category,
                }))
              }
            />
          )}

          {locked && (
            <Callout tone="amber" title="Financial fields locked" icon={Lock}>
              {editing?.lock_reason} You can still update the note for the owner.
            </Callout>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={draft.entryType === "purchase" ? "Vendor" : "Customer"} htmlFor="entry-counterparty" required>
              <Input
                id="entry-counterparty"
                value={draft.counterparty}
                onChange={(event) => setDraft({ ...draft, counterparty: event.target.value })}
                placeholder={draft.entryType === "purchase" ? "Vendor name" : "Customer name"}
                minLength={2}
                required
                disabled={locked}
              />
            </Field>
            {draft.entryType === "sale" && (
              <Field label="Customer email" htmlFor="entry-email" hint="Optional. Used for the invoice record.">
                <Input
                  id="entry-email"
                  type="email"
                  value={draft.counterpartyEmail}
                  onChange={(event) => setDraft({ ...draft, counterpartyEmail: event.target.value })}
                  placeholder="customer@example.com"
                  disabled={locked}
                />
              </Field>
            )}
            {draft.entryType === "sale" && (
              <Field label="Customer mobile" htmlFor="entry-phone" hint="Optional. Used for SMS payment reminders.">
                <Input
                  id="entry-phone"
                  type="tel"
                  value={draft.counterpartyPhone}
                  onChange={(event) => setDraft({ ...draft, counterpartyPhone: event.target.value })}
                  placeholder="98765 43210"
                  disabled={locked}
                />
              </Field>
            )}
            {draft.entryType === "purchase" && (
              <Field label="Category" htmlFor="entry-category" hint="Example: Inventory, Rent, Marketing.">
                <Input
                  id="entry-category"
                  value={draft.category}
                  onChange={(event) => setDraft({ ...draft, category: event.target.value })}
                  placeholder="Purchases"
                  disabled={locked}
                />
              </Field>
            )}
          </div>

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-[12px] font-semibold text-ink-900">
                  {draft.entryType === "purchase" ? "Items purchased" : "Items sold"}
                </p>
                <p className="text-[10.5px] text-slate-500">
                  One bill can hold several items. Start typing an item name to pick it from stock —
                  the price fills in automatically and its catalogue quantity is updated: purchases
                  add stock, sales reduce it.
                </p>
              </div>
              {!locked && (
                <Button
                  variant="outline"
                  size="sm"
                  icon={Plus}
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      lines: [...current.lines, newEntryLine()],
                    }))
                  }
                >
                  Add item
                </Button>
              )}
            </div>
            <div className="space-y-2">
              {draft.lines.map((line, index) => (
                <div
                  key={line.key}
                  className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50/60 p-2.5 sm:grid-cols-[minmax(0,1fr)_150px_130px_120px_36px]"
                >
                  <StockItemCombobox
                    value={line.description}
                    onValueChange={(description) =>
                      patchLine(line.key, { description, product_id: null, gst_rate: null })
                    }
                    onPick={(item) => pickStockItem(line.key, item)}
                    onExactMatch={(item) => fillPriceFromStock(line.key, item)}
                    placeholder={
                      draft.entryType === "purchase"
                        ? "Item bought — type to search stock"
                        : "Item sold — type to search stock"
                    }
                    ariaLabel={`Item ${index + 1} description`}
                    disabled={locked}
                    currency={currency}
                  />
                  <div className="flex items-center gap-1">
                    <Button
                      variant="outline"
                      size="icon"
                      icon={Minus}
                      aria-label={`Decrease quantity for item ${index + 1}`}
                      onClick={() =>
                        setDraft((current) => ({
                          ...current,
                          lines: current.lines.map((item) =>
                            item.key === line.key
                              ? {
                                  ...item,
                                  quantity: String(
                                    Math.max(1, Math.round((Number(item.quantity) || 1) - 1)),
                                  ),
                                }
                              : item,
                          ),
                        }))
                      }
                      disabled={locked || (Number(line.quantity) || 1) <= 1}
                    />
                    <Input
                      type="number"
                      min="1"
                      step="1"
                      value={line.quantity}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          lines: current.lines.map((item) =>
                            item.key === line.key
                              ? { ...item, quantity: event.target.value }
                              : item,
                          ),
                        }))
                      }
                      placeholder="Qty"
                      aria-label={`Item ${index + 1} quantity`}
                      className="text-center"
                      disabled={locked}
                    />
                    <Button
                      variant="outline"
                      size="icon"
                      icon={Plus}
                      aria-label={`Increase quantity for item ${index + 1}`}
                      onClick={() =>
                        setDraft((current) => ({
                          ...current,
                          lines: current.lines.map((item) =>
                            item.key === line.key
                              ? {
                                  ...item,
                                  quantity: String(
                                    Math.min(100000, Math.round((Number(item.quantity) || 0) + 1)),
                                  ),
                                }
                              : item,
                          ),
                        }))
                      }
                      disabled={locked}
                    />
                  </div>
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.unit_price}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        lines: current.lines.map((item) =>
                          item.key === line.key
                            ? { ...item, unit_price: event.target.value }
                            : item,
                        ),
                      }))
                    }
                    placeholder="Unit price"
                    aria-label={`Item ${index + 1} unit price`}
                    disabled={locked}
                  />
                  <div className="flex flex-col items-end justify-center px-2 text-right text-[12px] font-semibold tabular-nums text-ink-900">
                    <span>{money(lineTotal(line), currency)}</span>
                    {draft.entryType === "sale" && line.gst_rate != null && (
                      <span className="text-[10px] font-normal text-slate-400">
                        GST {line.gst_rate}%
                      </span>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    icon={Trash2}
                    aria-label={`Remove item ${index + 1}`}
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
            <div className="mt-2 flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2">
              <span className="text-[11px] text-slate-500">
                {draftLines(draft).length} item{draftLines(draft).length === 1 ? "" : "s"} on this bill
                {draft.entryType === "sale" && draftGst(draft) > 0
                  ? ` · GST ${money(draftGst(draft), currency)} from catalogue rates`
                  : ""}
              </span>
              <span className="text-[13px] font-semibold text-ink-900">
                {draft.entryType === "purchase" ? "Amount paid" : "Amount collected"}:{" "}
                <span className="tabular-nums">
                  {money(draftTotal(draft) + draftGst(draft), currency)}
                </span>
              </span>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Entry date" htmlFor="entry-date" required>
              <Input
                id="entry-date"
                type="date"
                value={draft.entryDate}
                onChange={(event) => setDraft({ ...draft, entryDate: event.target.value })}
                max={localToday()}
                required
                disabled={locked}
              />
            </Field>
            {draft.entryType === "sale" ? (
              <Field label="Received via" htmlFor="entry-method" required>
                <Select
                  id="entry-method"
                  value={draft.paymentMethod}
                  onChange={(event) =>
                    setDraft({ ...draft, paymentMethod: event.target.value as SaleMethod })
                  }
                  disabled={locked}
                >
                  {SALE_METHODS.map((method) => (
                    <option key={method.value} value={method.value}>
                      {method.label}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : (
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <p className="text-[10px] uppercase tracking-wide text-slate-400">Cash effect</p>
                <p className="mt-0.5 text-[11px] font-medium text-slate-600">
                  Reduces recorded cash immediately
                </p>
              </div>
            )}
          </div>

          {draft.entryType === "sale" && draft.paymentMethod === "paypal" && (
            <Callout tone="violet" title="PayPal recorded manually">
              This will appear in the owner&apos;s Payment Center as employee-recorded, not provider-verified.
              No PayPal API or webhook confirms it.
            </Callout>
          )}

          <Field label="Notes" htmlFor="entry-notes" hint="Optional context for the owner.">
            <Textarea
              id="entry-notes"
              value={draft.notes}
              onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
              placeholder="Reference number, delivery note or anything the owner should know."
            />
          </Field>

          {formError && (
            <Callout tone="red" title="Entry not saved">
              {formError}
            </Callout>
          )}
        </form>
      </Modal>

      <ConfirmDialog
        open={voidTarget !== null}
        onClose={() => setVoidTarget(null)}
        onConfirm={() => void confirmVoid()}
        title="Void this entry?"
        description={
          voidTarget
            ? `${voidTarget.reference} · ${voidTarget.counterparty} · ${money(
                voidTarget.amount,
                voidTarget.currency || currency,
              )}. Voiding reverses the linked ledger record and cannot be undone from the employee portal.`
            : undefined
        }
        confirmLabel="Void entry"
        tone="danger"
        loading={voiding}
      />
    </div>
  );
}
