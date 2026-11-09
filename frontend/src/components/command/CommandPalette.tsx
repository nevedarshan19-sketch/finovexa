import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Boxes,
  CreditCard,
  FileText,
  HandCoins,
  Loader2,
  Plus,
  ReceiptText,
  Search,
  Settings2,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { ALL_PAGES } from "../../lib/navigation";
import { api } from "../../lib/api";
import type { BillingProduct, Invoice } from "../../lib/types";
import { cn, money } from "../../lib/utils";

interface Entry {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: LucideIcon;
  to?: string;
  badge?: string;
  run?: () => void;
}

interface InvoicesResponse {
  items: Invoice[];
}
interface ProductsResponse {
  items: BillingProduct[];
}

export function CommandPalette({
  open,
  onClose,
  onOpenCopilot,
}: {
  open: boolean;
  onClose: () => void;
  onOpenCopilot: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [products, setProducts] = useState<BillingProduct[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const actions = useMemo<Entry[]>(
    () => [
      {
        id: "action-new-invoice",
        label: "Create a new invoice",
        hint: "Opens the GST invoice editor",
        group: "Actions",
        icon: Plus,
        to: "/billing?new=1",
      },
      {
        id: "action-new-product",
        label: "Add inventory item",
        hint: "Products, services, stock and GST defaults",
        group: "Actions",
        icon: Boxes,
        to: "/billing?tab=catalogue&newProduct=1",
      },
      {
        id: "action-recovery",
        label: "Chase overdue invoices",
        hint: "Reminder ladder by deadline",
        group: "Actions",
        icon: HandCoins,
        to: "/recovery",
      },
      {
        id: "action-payments",
        label: "Open the payment center",
        hint: "PayPal captures and reconciliation",
        group: "Actions",
        icon: CreditCard,
        to: "/payments",
      },
      {
        id: "action-analytics",
        label: "Review business analytics",
        hint: "Revenue, expenses and margins",
        group: "Actions",
        icon: BarChart3,
        to: "/analytics",
      },
      {
        id: "action-settings",
        label: "Open settings and integrations",
        hint: "Profile, GST and providers",
        group: "Actions",
        icon: Settings2,
        to: "/settings",
      },
      {
        id: "action-copilot",
        label: "Ask the FINOVEXA copilot",
        hint: "Grounded answer from your records",
        group: "Actions",
        icon: Sparkles,
        run: onOpenCopilot,
      },
    ],
    [onOpenCopilot],
  );

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    setInvoices([]);
    setProducts([]);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 40);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const needle = query.trim();
    if (needle.length < 2) {
      setInvoices([]);
      setProducts([]);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const [invoiceResult, productResult] = await Promise.all([
          api<InvoicesResponse>(`/billing/invoices?q=${encodeURIComponent(needle)}&limit=4`, {
            signal: controller.signal,
          }),
          api<ProductsResponse>(`/billing/products?q=${encodeURIComponent(needle)}&limit=4`, {
            signal: controller.signal,
          }),
        ]);
        setInvoices(invoiceResult.items);
        setProducts(productResult.items);
      } catch {
        // A failed entity lookup should not break navigation through the palette.
      } finally {
        setSearching(false);
      }
    }, 220);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      setSearching(false);
    };
  }, [query, open]);

  const entries = useMemo<Entry[]>(() => {
    const needle = query.trim().toLowerCase();
    const pages: Entry[] = ALL_PAGES.map((page) => ({
      id: `page-${page.to}`,
      label: page.label,
      hint: page.hint,
      group: page.group === "Command" ? "Navigate" : page.group,
      icon: page.icon,
      to: page.to,
    }));
    const matches = (entry: Entry) =>
      !needle ||
      entry.label.toLowerCase().includes(needle) ||
      (entry.hint || "").toLowerCase().includes(needle) ||
      entry.group.toLowerCase().includes(needle);

    const base = [...actions.filter(matches), ...pages.filter(matches)];

    const invoiceEntries: Entry[] = invoices.map((invoice) => ({
      id: `invoice-${invoice.id}`,
      label: `${invoice.number} · ${invoice.customer?.name || "Customer"}`,
      hint: `${invoice.status} · ${money(invoice.total, invoice.currency || "INR")}`,
      group: "Invoices",
      icon: FileText,
      to: `/billing?invoice=${invoice.id}`,
      badge: "Invoice",
    }));
    const productEntries: Entry[] = products.map((product) => ({
      id: `product-${product.id}`,
      label: product.name,
      hint: `${product.sku} · ${Number(product.quantity_on_hand ?? 0)} in stock`,
      group: "Products",
      icon: ReceiptText,
      to: `/billing?tab=catalogue&product=${product.id}`,
      badge: "Product",
    }));

    return [...base, ...invoiceEntries, ...productEntries];
  }, [actions, invoices, products, query]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  if (!open) return null;

  const go = (entry: Entry) => {
    onClose();
    if (entry.run) {
      entry.run();
      return;
    }
    if (entry.to) navigate(entry.to);
  };

  let lastGroup = "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-navy-950/60 px-4 pt-[10vh] backdrop-blur-sm animate-fade-in"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-[color:var(--border)] bg-[var(--surface)] shadow-pop animate-slide-up"
      >
        <div className="flex items-center gap-2.5 border-b border-[color:var(--border)] px-4">
          <Search className="h-4 w-4 text-slate-400" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActive((index) => Math.min(index + 1, entries.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive((index) => Math.max(index - 1, 0));
              } else if (event.key === "Enter" && entries[active]) {
                go(entries[active]);
              }
            }}
            placeholder="Search modules, invoices, products or actions…"
            className="h-14 flex-1 bg-transparent text-sm text-ink-900 outline-none placeholder:text-slate-400"
            aria-label="Search workspace"
            role="combobox"
            aria-expanded="true"
            aria-controls="command-results"
            aria-activedescendant={entries[active]?.id}
          />
          {searching && <Loader2 className="h-4 w-4 animate-spin text-brand-500" aria-hidden />}
          <span className="kbd">ESC</span>
        </div>

        <div id="command-results" role="listbox" className="max-h-[380px] overflow-y-auto p-2">
          {entries.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <p className="text-sm font-medium text-ink-900">No matches for “{query}”.</p>
              <p className="mt-1 text-xs text-slate-400">
                Try an invoice number, a product name, or “invoice”, “payment”, “analytics”.
              </p>
            </div>
          ) : (
            entries.map((entry, index) => {
              const showGroup = entry.group !== lastGroup;
              lastGroup = entry.group;
              return (
                <div key={entry.id}>
                  {showGroup && (
                    <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                      {entry.group}
                    </p>
                  )}
                  <button
                    id={entry.id}
                    type="button"
                    role="option"
                    aria-selected={index === active}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => go(entry)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition",
                      index === active
                        ? "bg-brand-500/10 text-ink-900 ring-1 ring-inset ring-brand-400/25"
                        : "text-slate-600 hover:bg-[var(--surface-2)]",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                        index === active
                          ? "bg-brand-500 text-white shadow-sm"
                          : "bg-[var(--surface-3)] text-slate-500",
                      )}
                    >
                      <entry.icon className="h-4 w-4" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold">{entry.label}</span>
                      {entry.hint && (
                        <span className="block truncate text-[10.5px] text-slate-400">{entry.hint}</span>
                      )}
                    </span>
                    {entry.badge && (
                      <span className="shrink-0 rounded-full border border-[color:var(--border)] px-2 py-0.5 text-[10px] font-medium text-slate-400">
                        {entry.badge}
                      </span>
                    )}
                    <ArrowRight
                      className={cn(
                        "h-3.5 w-3.5 shrink-0 transition",
                        index === active ? "text-brand-500 opacity-100" : "opacity-0",
                      )}
                      aria-hidden
                    />
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[color:var(--border)] bg-[var(--surface-2)]/60 px-4 py-2 text-[10px] text-slate-400">
          <span className="flex items-center gap-2">
            <span className="kbd">↑</span>
            <span className="kbd">↓</span> navigate
            <span className="kbd">↵</span> open
          </span>
          <span className="flex items-center gap-1.5">
            <Sparkles className="h-3 w-3" /> Live results from your ledger
          </span>
        </div>
      </div>
    </div>
  );
}
