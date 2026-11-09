import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Loader2, Package } from "lucide-react";
import { api } from "../lib/api";
import { cn, money } from "../lib/utils";
import { Input } from "./ui";

export interface StockItem {
  id: number;
  sku: string;
  name: string;
  unit: string;
  item_type?: string;
  hsn_sac?: string | null;
  gst_rate?: number;
  gst_verified?: boolean;
  unit_price: number;
  quantity_on_hand: number;
  low_stock: boolean;
}

interface StockItemComboboxProps {
  value: string;
  onValueChange: (value: string) => void;
  onPick: (item: StockItem) => void;
  onExactMatch?: (item: StockItem) => void;
  ariaLabel: string;
  placeholder?: string;
  disabled?: boolean;
  currency: string;
}

const DEBOUNCE_MS = 220;
const MIN_CHARS = 2;

export function StockItemCombobox({
  value,
  onValueChange,
  onPick,
  onExactMatch,
  ariaLabel,
  placeholder,
  disabled,
  currency,
}: StockItemComboboxProps) {
  const listId = useId();
  const [focused, setFocused] = useState(false);
  const [options, setOptions] = useState<StockItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const trimmed = value.trim();
  const exactMatchRef = useRef(onExactMatch);
  exactMatchRef.current = onExactMatch;

  useEffect(() => {
    if (!focused || trimmed.length < MIN_CHARS) {
      setOptions([]);
      setLoading(false);
      return;
    }
    let alive = true;
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      api<{ items: StockItem[] }>(
        `/employee/products?q=${encodeURIComponent(trimmed)}&limit=6`,
        { signal: controller.signal },
      )
        .then((data) => {
          if (!alive) return;
          setOptions(data.items);
          setActive(0);
          const exact = data.items.find(
            (item) => item.name.toLowerCase() === trimmed.toLowerCase(),
          );
          if (exact) exactMatchRef.current?.(exact);
        })
        .catch(() => {
          if (alive) setOptions([]);
        })
        .finally(() => {
          if (alive) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      alive = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [trimmed, focused]);

  const open = focused && !dismissed && trimmed.length >= MIN_CHARS && options.length > 0;

  useLayoutEffect(() => {
    if (!open) {
      setDropUp(false);
      return;
    }
    const node = wrapRef.current;
    if (!node) return;
    let scroller = node.parentElement;
    while (scroller) {
      const overflowY = window.getComputedStyle(scroller).overflowY;
      if (/(auto|scroll)/.test(overflowY) && scroller.scrollHeight > scroller.clientHeight) break;
      scroller = scroller.parentElement;
    }
    const limit = scroller ? scroller.getBoundingClientRect().bottom : window.innerHeight;
    setDropUp(limit - node.getBoundingClientRect().bottom < 240);
  }, [open, options]);

  const pick = (item: StockItem) => {
    onPick(item);
    setDismissed(true);
    setFocused(false);
  };

  return (
    <div ref={wrapRef} className="relative">
      <Input
        value={value}
        onChange={(event) => {
          onValueChange(event.target.value);
          setDismissed(false);
        }}
        onFocus={() => {
          setFocused(true);
          setDismissed(false);
        }}
        onBlur={() => setFocused(false)}
        onKeyDown={(event) => {
          if (!open) return;
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((index) => (index + 1) % options.length);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((index) => (index - 1 + options.length) % options.length);
          } else if (event.key === "Enter") {
            event.preventDefault();
            const item = options[active];
            if (item) pick(item);
          } else if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            setDismissed(true);
          }
        }}
        placeholder={placeholder}
        aria-label={ariaLabel}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        autoComplete="off"
        maxLength={255}
        disabled={disabled}
        className={loading ? "pr-8" : undefined}
      />
      {loading && (
        <Loader2
          className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-slate-400"
          aria-hidden
        />
      )}
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Stock items"
          className={cn(
            "absolute left-0 right-0 z-30 max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-pop",
            dropUp ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          {options.map((item, index) => (
            <li key={item.id} id={`${listId}-${index}`} role="option" aria-selected={index === active}>
              <button
                type="button"
                tabIndex={-1}
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(item);
                }}
                onMouseEnter={() => setActive(index)}
                className={cn(
                  "flex w-full items-center gap-2 px-2.5 py-2 text-left transition",
                  index === active ? "bg-brand-50" : "hover:bg-slate-50",
                )}
              >
                <Package className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12px] font-medium text-ink-900">
                    {item.name}
                  </span>
                  <span className="block truncate text-[10px] text-slate-400">
                    {item.sku} · {money(item.unit_price, currency)} / {item.unit}
                    {item.gst_rate != null ? ` · GST ${item.gst_rate}%` : ""}
                  </span>
                </span>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                    item.quantity_on_hand > 0
                      ? item.low_stock
                        ? "bg-amber-50 text-amber-700"
                        : "bg-emerald-50 text-emerald-700"
                      : "bg-rose-50 text-rose-700",
                  )}
                >
                  {item.quantity_on_hand > 0 ? `${item.quantity_on_hand} in stock` : "Out of stock"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
