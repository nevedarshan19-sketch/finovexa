import { Moon, Sun } from "lucide-react";
import { useTheme } from "../../context/ThemeContext";
import { cn } from "../../lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      aria-pressed={dark}
      title={dark ? "Light theme" : "Dark theme"}
      className={cn(
        "relative flex h-9 w-9 items-center justify-center overflow-hidden rounded-lg border border-[color:var(--border)] bg-[var(--surface)] text-[var(--text-3)] transition hover:border-[color:var(--border-strong)] hover:text-[var(--text-1)]",
        className,
      )}
    >
      <Sun
        className={cn(
          "absolute h-4 w-4 transition-all duration-300",
          dark ? "translate-y-0 rotate-0 opacity-100" : "-translate-y-5 rotate-90 opacity-0",
        )}
        aria-hidden
      />
      <Moon
        className={cn(
          "absolute h-4 w-4 transition-all duration-300",
          dark ? "translate-y-5 -rotate-90 opacity-0" : "translate-y-0 rotate-0 opacity-100",
        )}
        aria-hidden
      />
    </button>
  );
}

export function ThemeMenuRow() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-xs text-slate-600">
      <span className="flex items-center gap-2">
        {theme === "dark" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
        Appearance
      </span>
      <span className="inline-flex overflow-hidden rounded-md border border-[color:var(--border)] p-0.5">
        {(["light", "dark"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => setTheme(mode)}
            aria-pressed={theme === mode}
            className={cn(
              "rounded px-2 py-0.5 text-[10px] font-semibold capitalize transition",
              theme === mode
                ? "bg-[var(--accent)] text-white"
                : "text-[var(--text-3)] hover:text-[var(--text-1)]",
            )}
          >
            {mode}
          </button>
        ))}
      </span>
    </div>
  );
}
