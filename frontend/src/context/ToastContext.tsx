import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "../lib/utils";

export type ToastTone = "success" | "error" | "info" | "warning";

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface ToastContextValue {
  toast: (input: { title: string; description?: string; tone?: ToastTone }) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_STYLES: Record<ToastTone, { icon: typeof Info; ring: string; iconClass: string }> = {
  success: {
    icon: CheckCircle2,
    ring: "border-emerald-200",
    iconClass: "text-emerald-500",
  },
  error: { icon: XCircle, ring: "border-rose-200", iconClass: "text-rose-500" },
  info: { icon: Info, ring: "border-brand-200", iconClass: "text-brand-500" },
  warning: { icon: AlertTriangle, ring: "border-amber-200", iconClass: "text-amber-500" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef<Map<number, number>>(new Map());
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const toast = useCallback(
    (input: { title: string; description?: string; tone?: ToastTone }) => {
      const id = ++counter.current;
      const item: ToastItem = {
        id,
        title: input.title,
        description: input.description,
        tone: input.tone || "info",
      };
      setItems((current) => [...current.slice(-3), item]);
      const timer = window.setTimeout(() => dismiss(id), 5200);
      timers.current.set(id, timer);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {items.map((item) => {
          const tone = TONE_STYLES[item.tone];
          const Icon = tone.icon;
          return (
            <div
              key={item.id}
              className={cn(
                "pointer-events-auto flex animate-slide-in-right items-start gap-3 rounded-xl border bg-white p-4 shadow-pop",
                tone.ring,
              )}
              role="status"
            >
              <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", tone.iconClass)} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink-900">{item.title}</p>
                {item.description && (
                  <p className="mt-0.5 text-[13px] leading-snug text-slate-500">
                    {item.description}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(item.id)}
                className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                aria-label="Dismiss notification"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
