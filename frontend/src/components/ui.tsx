import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Check,
  Copy,
  Inbox,
  Loader2,
  RefreshCw,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn, pct } from "../lib/utils";

/* ------------------------------------------------------------------ Button */

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "success";
type ButtonSize = "sm" | "md" | "icon";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-[linear-gradient(135deg,#1f6feb_0%,#2f86f6_55%,#0ea5b7_100%)] text-white shadow-[0_10px_22px_-14px_rgba(31,111,235,0.95)] hover:brightness-[1.06] active:brightness-95 focus-visible:ring-brand-200 disabled:brightness-90 disabled:shadow-none",
  secondary:
    "bg-navy-900 text-white shadow-sm hover:bg-navy-800 focus-visible:ring-slate-300 disabled:bg-slate-400",
  outline:
    "border border-[color:var(--border-strong)] bg-[var(--surface)] text-[var(--text-2)] hover:border-[var(--text-3)] hover:bg-[var(--surface-2)] hover:text-[var(--text-1)] focus-visible:ring-slate-200 disabled:text-slate-400",
  ghost:
    "text-[var(--text-2)] hover:bg-[var(--surface-2)] hover:text-[var(--text-1)] focus-visible:ring-slate-200 disabled:text-slate-300",
  danger:
    "bg-rose-600 text-white shadow-sm hover:bg-rose-700 focus-visible:ring-rose-200 disabled:bg-rose-300",
  success:
    "bg-emerald-600 text-white shadow-sm hover:bg-emerald-700 focus-visible:ring-emerald-200 disabled:bg-emerald-300",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-lg px-2.5 text-xs",
  md: "h-9 gap-2 rounded-lg px-3.5 text-[13px]",
  icon: "h-9 w-9 justify-center rounded-lg",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: LucideIcon;
  iconRight?: LucideIcon;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon: Icon,
  iconRight: IconRight,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex select-none items-center justify-center font-semibold transition focus:outline-none focus-visible:ring-2 disabled:cursor-not-allowed",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : (
        Icon && <Icon className={cn(size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4")} aria-hidden />
      )}
      {children}
      {IconRight && !loading && (
        <IconRight className={cn(size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4")} aria-hidden />
      )}
    </button>
  );
}

/* ------------------------------------------------------------------- Badge */

type BadgeTone = "slate" | "blue" | "green" | "amber" | "red" | "violet" | "cyan" | "navy";

const BADGE_TONES: Record<BadgeTone, string> = {
  slate: "border-slate-200 bg-slate-50 text-slate-600",
  blue: "border-brand-200 bg-brand-50 text-brand-700",
  green: "border-emerald-200 bg-emerald-50 text-emerald-700",
  amber: "border-amber-200 bg-amber-50 text-amber-700",
  red: "border-rose-200 bg-rose-50 text-rose-700",
  violet: "border-violet-200 bg-violet-50 text-violet-700",
  cyan: "border-cyan-200 bg-cyan-50 text-cyan-700",
  navy: "border-navy-700 bg-navy-800 text-slate-100",
};

const DOT_TONES: Record<BadgeTone, string> = {
  slate: "bg-slate-400",
  blue: "bg-brand-500",
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-rose-500",
  violet: "bg-violet-500",
  cyan: "bg-cyan-500",
  navy: "bg-slate-300",
};

export function Badge({
  tone = "slate",
  dot = false,
  className,
  children,
  title,
}: {
  tone?: BadgeTone;
  dot?: boolean;
  className?: string;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-5",
        BADGE_TONES[tone],
        className,
      )}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", DOT_TONES[tone])} aria-hidden />}
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------- Card */

export function Card({
  className,
  children,
  hover = false,
}: {
  className?: string;
  children: ReactNode;
  hover?: boolean;
}) {
  return <div className={cn("card", hover && "card-hover", className)}>{children}</div>;
}

export function CardHeader({
  title,
  description,
  actions,
  icon: Icon,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3 px-5 pt-5", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {Icon && (
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            <Icon className="h-4 w-4" aria-hidden />
          </span>
        )}
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-tight text-ink-900">{title}</h2>
          {description && <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex min-w-0 max-w-full flex-wrap items-center justify-end gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("p-5", className)}>{children}</div>;
}

export function CardFooter({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-5 py-3 text-xs text-slate-500", className)}>
      {children}
    </div>
  );
}

/* ---------------------------------------------------------------- PageHeader */

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-brand-600">
            <span className="h-1 w-6 rounded-full bg-gradient-to-r from-brand-500 to-cyan-400" aria-hidden />
            {eyebrow}
          </p>
        )}
        <h1 className="text-balance text-[22px] font-semibold tracking-tight text-ink-900 sm:text-2xl">{title}</h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-500">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ----------------------------------------------------------------- StatCard */

export function AnimatedNumber({
  value,
  format,
  duration = 720,
  className,
}: {
  value: number;
  format: (value: number) => string;
  duration?: number;
  className?: string;
}) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);

  useEffect(() => {
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || !Number.isFinite(value)) {
      fromRef.current = value;
      setDisplay(value);
      return;
    }
    const from = fromRef.current;
    const start = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(from + (value - from) * eased);
      if (progress < 1) frame = requestAnimationFrame(step);
      else fromRef.current = value;
    });
    return () => {
      cancelAnimationFrame(frame);
      fromRef.current = value;
    };
  }, [value, duration]);

  return <span className={cn("tabular", className)}>{format(display)}</span>;
}

export function StatCard({
  label,
  value,
  icon: Icon,
  change,
  changeLabel,
  invert = false,
  sub,
  tone = "blue",
  className,
  to,
}: {
  label: string;
  value: ReactNode;
  icon?: LucideIcon;
  change?: number | null;
  changeLabel?: string;
  invert?: boolean;
  sub?: ReactNode;
  tone?: "blue" | "green" | "amber" | "violet" | "red" | "slate";
  className?: string;
  to?: string;
}) {
  const toneStyles = {
    blue: "bg-brand-50 text-brand-600",
    green: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    violet: "bg-violet-50 text-violet-600",
    red: "bg-rose-50 text-rose-600",
    slate: "bg-slate-100 text-slate-500",
  }[tone];
  const positive = change !== null && change !== undefined && (invert ? change < 0 : change >= 0);
  const showChange = change !== null && change !== undefined;
  const inner = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[12px] font-medium text-slate-500">{label}</p>
          <p className="mt-2 truncate text-[22px] font-semibold tracking-tight text-ink-900">{value}</p>
        </div>
        {Icon && (
          <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", toneStyles)}>
            <Icon className="h-4 w-4" aria-hidden />
          </span>
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1">
        {showChange && (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-semibold",
              positive ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
            )}
          >
            {change >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {pct(change)}
          </span>
        )}
        {(changeLabel || sub) && (
          <span className="text-[11px] text-slate-400">{changeLabel || sub}</span>
        )}
        {to && (
          <span className="ml-auto inline-flex items-center gap-0.5 text-[11px] font-semibold text-brand-600 opacity-0 transition-opacity group-hover:opacity-100">
            Details <ArrowUpRight className="h-3 w-3" />
          </span>
        )}
      </div>
    </>
  );
  if (to) {
    return (
      <Link to={to} className={cn("card card-hover group block p-5", className)}>
        {inner}
      </Link>
    );
  }
  return <div className={cn("card card-hover p-5", className)}>{inner}</div>;
}

/* ------------------------------------------------------------- Form controls */

export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="field-label" htmlFor={htmlFor}>
        {label}
        {required && <span className="ml-0.5 text-rose-500">*</span>}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{hint}</p>}
      {error && <p className="mt-1 text-[11px] font-medium text-rose-600">{error}</p>}
    </div>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("input-base", className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn("input-base appearance-none pr-8", className)} {...props}>
      {children}
    </select>
  );
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea ref={ref} className={cn("input-base min-h-[96px] resize-y", className)} {...props} />
    );
  },
);

export function Checkbox({
  label,
  checked,
  onChange,
  disabled,
  className,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label className={cn("flex cursor-pointer items-start gap-2.5 text-[13px] leading-relaxed text-slate-600", disabled && "cursor-not-allowed opacity-60", className)}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
        className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-500 accent-brand-500 focus:ring-brand-200"
      />
      <span>{label}</span>
    </label>
  );
}

/* -------------------------------------------------------------------- Modal */

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  const widths = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl", xl: "max-w-5xl" };
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-navy-950/60 p-4 backdrop-blur-[2px] sm:items-center"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn(
          "my-auto w-full animate-slide-up rounded-2xl border border-slate-200 bg-white shadow-pop",
          widths[size],
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold tracking-tight text-ink-900">
              {title}
            </h2>
            {description && <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[65vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex flex-wrap items-center justify-end gap-2 rounded-b-2xl border-t border-slate-100 bg-slate-50/60 px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  tone = "default",
  loading = false,
  children,
  disabled = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  tone?: "default" | "danger" | "success";
  loading?: boolean;
  children?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : tone === "success" ? "success" : "primary"}
            onClick={onConfirm}
            loading={loading}
            disabled={disabled}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Modal>
  );
}

/* ------------------------------------------------------------ States/Skeletons */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

export function SkeletonCard({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("card p-5", className)} aria-hidden>
      <Skeleton className="h-3.5 w-28" />
      <Skeleton className="mt-3 h-7 w-40" />
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className="mt-3 h-3 w-full" />
      ))}
    </div>
  );
}

export function PageSkeleton({ cards = 4 }: { cards?: number }) {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Loading page">
      <div className="space-y-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-8 w-72 max-w-full" />
        <Skeleton className="h-3.5 w-96 max-w-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: cards }).map((_, index) => (
          <SkeletonCard key={index} lines={1} />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card p-5 lg:col-span-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="mt-4 h-64 w-full" />
        </div>
        <SkeletonCard lines={6} />
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
  className,
}: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        <Icon className="h-6 w-6" aria-hidden />
      </span>
      <h3 className="mt-3 text-sm font-semibold text-ink-900">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-xs leading-relaxed text-slate-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card border-rose-200 bg-rose-50/40 px-5 py-8 text-center">
      <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-rose-100 text-rose-500">
        <AlertTriangle className="h-5 w-5" aria-hidden />
      </span>
      <p className="mt-3 text-sm font-semibold text-ink-900">We could not load this data</p>
      <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-slate-600">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" icon={RefreshCw} onClick={onRetry} className="mt-4">
          Try again
        </Button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- Callout */

export function Callout({
  tone = "blue",
  title,
  icon: Icon,
  children,
  className,
}: {
  tone?: "blue" | "amber" | "red" | "green" | "slate" | "violet";
  title?: string;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}) {
  const tones = {
    blue: "border-brand-200 bg-brand-50/60 text-brand-900",
    amber: "border-amber-200 bg-amber-50/60 text-amber-900",
    red: "border-rose-200 bg-rose-50/60 text-rose-900",
    green: "border-emerald-200 bg-emerald-50/60 text-emerald-900",
    slate: "border-slate-200 bg-slate-50 text-slate-700",
    violet: "border-violet-200 bg-violet-50/60 text-violet-900",
  }[tone];
  const iconTones = {
    blue: "text-brand-600",
    amber: "text-amber-600",
    red: "text-rose-600",
    green: "text-emerald-600",
    slate: "text-slate-500",
    violet: "text-violet-600",
  }[tone];
  const Fallback = tone === "red" || tone === "amber" ? AlertTriangle : Check;
  const IconComponent = Icon || Fallback;
  return (
    <div className={cn("flex items-start gap-3 rounded-xl border px-4 py-3", tones, className)}>
      <IconComponent className={cn("mt-0.5 h-4 w-4 shrink-0", iconTones)} aria-hidden />
      <div className="min-w-0 text-[13px] leading-relaxed">
        {title && <p className="mb-0.5 font-semibold">{title}</p>}
        {children}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- Tabs */

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  size = "md",
  className,
}: {
  items: { key: T; label: string; count?: number }[];
  value: T;
  onChange: (key: T) => void;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex max-w-full flex-wrap items-center gap-1 rounded-lg border border-slate-200 bg-slate-100/70 p-1",
        className,
      )}
      role="tablist"
    >
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={value === item.key}
          onClick={() => onChange(item.key)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md font-semibold transition",
            size === "sm" ? "px-2.5 py-1 text-[11px]" : "px-3 py-1.5 text-xs",
            value === item.key
              ? "bg-white text-ink-900 shadow-sm ring-1 ring-slate-200/70"
              : "text-slate-500 hover:text-slate-800",
          )}
        >
          {item.label}
          {typeof item.count === "number" && (
            <span
              className={cn(
                "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                value === item.key ? "bg-brand-50 text-brand-700" : "bg-slate-200/80 text-slate-500",
              )}
            >
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------- Progress/Copy */

export function ProgressBar({
  value,
  tone = "blue",
  className,
  label,
}: {
  value: number;
  tone?: "blue" | "green" | "amber" | "red" | "violet";
  className?: string;
  label?: string;
}) {
  const colors = {
    blue: "bg-brand-500",
    green: "bg-emerald-500",
    amber: "bg-amber-500",
    red: "bg-rose-500",
    violet: "bg-violet-500",
  }[tone];
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-slate-100", className)}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className={cn("h-full rounded-full transition-all duration-500", colors)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function CopyButton({
  value,
  label = "Copy",
  ariaLabel,
  className,
}: {
  value: string;
  label?: string;
  ariaLabel?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        } catch {
          setCopied(false);
        }
      }}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-500 transition hover:text-slate-800",
        className,
      )}
      aria-label={ariaLabel || `${label || "Copy"}: ${value}`}
    >
      {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : label}
    </button>
  );
}

export function HashChip({ hash }: { hash: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <button
      type="button"
      onClick={() => setExpanded((value) => !value)}
      className="max-w-full rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[10px] text-slate-500 transition hover:text-slate-800"
      title="Canonical SHA-256 approval hash"
    >
      <span className="break-all">{expanded ? hash : `${hash.slice(0, 12)}…${hash.slice(-8)}`}</span>
    </button>
  );
}

/* --------------------------------------------------------------------- Table */

export function TableWrap({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full min-w-[640px] border-collapse">{children}</table>
    </div>
  );
}
export function THead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
}
export function TH({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={cn("table-head", className)}>{children}</th>;
}
export function TBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-slate-100">{children}</tbody>;
}
export function TR({ children, className }: { children: ReactNode; className?: string }) {
  return <tr className={cn("row-hover", className)}>{children}</tr>;
}
export function TD({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cn("table-cell", className)}>{children}</td>;
}
