import { cn } from "../lib/utils";

type BrandLogoProps = {
  subtitle?: string;
  subtitleClassName?: string;
  size?: "sm" | "md" | "lg";
  variant?: "dark" | "light";
  className?: string;
};

const MARK_SIZE = {
  sm: "h-9 w-9 rounded-xl",
  md: "h-10 w-10 rounded-xl",
  lg: "h-12 w-12 rounded-2xl",
};

export function BrandLogo({
  subtitle = "Business operations",
  subtitleClassName,
  size = "md",
  variant = "dark",
  className,
}: BrandLogoProps) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span
        className={cn(
          "relative shrink-0 overflow-hidden ring-1 shadow-lg",
          MARK_SIZE[size],
          variant === "dark"
            ? "ring-white/15 shadow-black/40"
            : "ring-slate-900/10 shadow-slate-900/10",
        )}
      >
        <img
          src="/branding/finovexa-mark.png"
          alt="FINOVEXA AI emblem"
          className="h-full w-full object-cover object-[38%_38%]"
        />
      </span>
      <div className="leading-tight">
        <p
          className={cn(
            "font-semibold tracking-tight",
            size === "lg" ? "text-[17px]" : "text-[15px]",
            variant === "dark" ? "text-white" : "text-ink-900",
          )}
        >
          FINOVEXA{" "}
          <span className={variant === "dark" ? "text-brand-300" : "text-brand-600"}>AI</span>
        </p>
        <p
          className={cn(
            "text-[10px] font-medium uppercase tracking-[0.16em]",
            subtitleClassName ?? (variant === "dark" ? "text-slate-500" : "text-slate-500"),
          )}
        >
          {subtitle}
        </p>
      </div>
    </div>
  );
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "relative shrink-0 overflow-hidden rounded-xl ring-1 ring-white/15 shadow-lg shadow-black/30",
        className,
      )}
    >
      <img
        src="/branding/finovexa-mark.png"
        alt="FINOVEXA AI emblem"
        className="h-full w-full object-cover object-[38%_38%]"
      />
    </span>
  );
}

export function BrandHero({ className }: { className?: string }) {
  return (
    <img
      src="/branding/finovexa-logo.png"
      alt="FINOVEXA AI — Smarter Business. Greater Tomorrow."
      className={cn("h-auto w-48 rounded-2xl ring-1 ring-white/10 shadow-2xl shadow-black/40", className)}
    />
  );
}
