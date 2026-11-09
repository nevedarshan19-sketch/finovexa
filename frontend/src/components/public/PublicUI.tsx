import {
  useEffect,
  useRef,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { AlertTriangle, ChevronDown, RefreshCw, Sparkles } from "lucide-react";
import { cn } from "../../lib/utils";

export function GradientText({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "bg-gradient-to-r from-brand-300 via-cyan-300 to-violet-300 bg-clip-text text-transparent",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={cn(
        "transition-[opacity,transform] duration-700 ease-out",
        visible ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Section({
  id,
  className,
  children,
}: {
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={cn("relative mx-auto w-full max-w-7xl px-5 sm:px-8", className)}>
      {children}
    </section>
  );
}

export function Eyebrow({ children, icon: Icon = Sparkles }: { children: ReactNode; icon?: typeof Sparkles }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-200">
      <Icon className="h-3 w-3" aria-hidden />
      {children}
    </span>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  align = "left",
  className,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  align?: "left" | "center";
  className?: string;
}) {
  return (
    <div className={cn("max-w-2xl", align === "center" && "mx-auto text-center", className)}>
      {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
      <h2 className="mt-4 text-balance text-[26px] font-semibold leading-tight tracking-tight text-white sm:text-[34px]">
        {title}
      </h2>
      {description && (
        <p className="mt-3 text-sm leading-relaxed text-slate-400 sm:text-[15px]">{description}</p>
      )}
    </div>
  );
}

export function GlassCard({
  children,
  className,
  hover = false,
  id,
}: {
  children: ReactNode;
  className?: string;
  hover?: boolean;
  id?: string;
}) {
  return (
    <div
      id={id}
      className={cn(
        "relative rounded-2xl border border-white/[0.08] bg-[linear-gradient(155deg,rgba(255,255,255,0.055),rgba(255,255,255,0.018))] shadow-[0_24px_60px_-40px_rgba(0,0,0,0.9)] backdrop-blur-xl",
        hover &&
          "transition duration-300 hover:-translate-y-0.5 hover:border-brand-400/30 hover:shadow-[0_30px_80px_-38px_rgba(36,120,240,0.55)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

const ToneStyles = {
  blue: "border-brand-400/25 bg-brand-500/10 text-brand-200",
  cyan: "border-cyan-400/25 bg-cyan-500/10 text-cyan-200",
  violet: "border-violet-400/25 bg-violet-500/10 text-violet-200",
  emerald: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200",
  amber: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  slate: "border-white/10 bg-white/[0.05] text-slate-300",
} as const;

export function Pill({
  children,
  tone = "slate",
  className,
  title,
}: {
  children: ReactNode;
  tone?: keyof typeof ToneStyles;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[10.5px] font-semibold",
        ToneStyles[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* --------------------------------------------------------------------- Forms */

const inputBase =
  "w-full rounded-xl border border-white/10 bg-white/[0.045] px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500 shadow-inner shadow-black/20 transition focus:border-brand-400/60 focus:bg-white/[0.06] focus:outline-none focus:ring-2 focus:ring-brand-500/25 disabled:cursor-not-allowed disabled:opacity-60";

export function PublicField({
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
      <label htmlFor={htmlFor} className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-400">
        {label}
        {required && <span className="ml-0.5 text-brand-300">*</span>}
      </label>
      {children}
      {hint && !error && <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">{hint}</p>}
      {error && <p className="mt-1.5 text-[11px] font-medium text-rose-300">{error}</p>}
    </div>
  );
}

export function PublicInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(inputBase, className)} {...props} />;
}

export function PublicSelect({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select
        className={cn(inputBase, "appearance-none pr-9 [&>option]:bg-[#0b1526]", className)}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500"
        aria-hidden
      />
    </div>
  );
}

export function PublicTextarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(inputBase, "min-h-[120px] resize-y", className)} {...props} />;
}

export function PublicCheckbox({
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
    <label
      className={cn(
        "flex cursor-pointer items-start gap-2.5 text-[12px] leading-relaxed text-slate-400",
        disabled && "cursor-not-allowed opacity-60",
        className,
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
        className="mt-0.5 h-4 w-4 shrink-0 rounded border-white/20 bg-white/5 accent-brand-500"
      />
      <span>{label}</span>
    </label>
  );
}

/* ------------------------------------------------------------------- States */

export function DarkSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-xl bg-[linear-gradient(90deg,rgba(255,255,255,0.05),rgba(255,255,255,0.09),rgba(255,255,255,0.05))]",
        className,
      )}
      aria-hidden
    />
  );
}

export function PublicLoading({ cards = 3 }: { cards?: number }) {
  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-16 sm:px-8" aria-busy="true" aria-label="Loading">
      <DarkSkeleton className="h-3 w-28" />
      <DarkSkeleton className="mt-4 h-9 w-80 max-w-full" />
      <DarkSkeleton className="mt-3 h-3.5 w-full max-w-xl" />
      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: cards }).map((_, index) => (
          <DarkSkeleton key={index} className="h-56" />
        ))}
      </div>
    </div>
  );
}

export function PublicError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <GlassCard className="mx-auto max-w-xl px-6 py-10 text-center">
      <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-rose-500/10 text-rose-300">
        <AlertTriangle className="h-5 w-5" aria-hidden />
      </span>
      <p className="mt-3 text-sm font-semibold text-white">We could not load this page</p>
      <p className="mt-1 text-xs leading-relaxed text-slate-400">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-white/30 hover:bg-white/5"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Try again
        </button>
      )}
    </GlassCard>
  );
}

export function DisclaimerBox({
  title = "Important",
  children,
  className,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-amber-400/20 bg-amber-400/[0.06] px-4 py-3 text-[11.5px] leading-relaxed text-amber-100/90",
        className,
      )}
    >
      <p className="font-semibold text-amber-200">{title}</p>
      <div className="mt-1 text-amber-100/80">{children}</div>
    </div>
  );
}
