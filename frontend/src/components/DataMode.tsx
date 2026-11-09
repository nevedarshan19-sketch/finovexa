import { Badge } from "./ui";
import { titleCase } from "../lib/utils";

const MODES: Record<
  string,
  {
    label: string;
    tone: "green" | "blue" | "violet" | "slate" | "amber" | "red" | "cyan";
    meaning: string;
  }
> = {
  live: {
    label: "LIVE",
    tone: "green",
    meaning: "Fetched from a configured external provider moments ago.",
  },
  delayed: {
    label: "DELAYED",
    tone: "amber",
    meaning: "Real provider data that the source publishes with a delay. Not exchange-grade.",
  },
  sandbox: {
    label: "SANDBOX",
    tone: "blue",
    meaning: "Provider sandbox environment. No real money moves.",
  },
  simulated: {
    label: "SIMULATED",
    tone: "violet",
    meaning: "Produced by the local simulator. No external system was contacted.",
  },
  demo: {
    label: "DEMO",
    tone: "slate",
    meaning: "Seeded demonstration record, not a live observation.",
  },
  stale: {
    label: "STALE",
    tone: "amber",
    meaning: "Last known value is older than the freshness window.",
  },
  unavailable: {
    label: "UNAVAILABLE",
    tone: "red",
    meaning: "No verified value exists. Nothing is invented.",
  },
  deterministic: {
    label: "DETERMINISTIC",
    tone: "cyan",
    meaning: "Computed from ledger records with the rules engine.",
  },
};

export function DataModeBadge({
  mode,
  showDot = true,
  label,
}: {
  mode?: string | null;
  showDot?: boolean;
  label?: string;
}) {
  const key = (mode || "unavailable").toLowerCase();
  const spec = MODES[key];
  if (!spec) {
    return (
      <Badge tone="slate" dot={showDot} title={`Unknown data mode: ${mode}`}>
        {label || (mode ? mode.toUpperCase() : "UNKNOWN")}
      </Badge>
    );
  }
  return (
    <Badge tone={spec.tone} dot={showDot} title={spec.meaning}>
      {label || spec.label}
    </Badge>
  );
}

export function DataModeLegend({ modes }: { modes: { mode: string; meaning: string }[] }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {modes.map((item) => (
        <div key={item.mode} className="flex items-start gap-2.5 rounded-lg border border-slate-100 bg-slate-50/60 p-2.5">
          <DataModeBadge mode={item.mode} showDot={false} />
          <p className="text-[11px] leading-relaxed text-slate-500">{item.meaning}</p>
        </div>
      ))}
    </div>
  );
}

type Tone = "slate" | "blue" | "green" | "amber" | "red" | "violet" | "cyan";

const STATUS_TONES: Record<string, Tone> = {
  paid: "green",
  confirmed: "green",
  executed: "green",
  approved: "green",
  active: "green",
  connected: "green",
  simulated_filled: "green",
  live: "green",
  live_filled: "green",
  live_open: "blue",
  live_submitted: "blue",
  live_partially_filled: "amber",
  live_cancel_requested: "amber",
  live_cancelled: "slate",
  live_rejected: "red",
  issued: "blue",
  scheduled: "blue",
  pending: "amber",
  partially_paid: "amber",
  cancel_requested: "amber",
  scheduled_past_due: "amber",
  attention: "amber",
  sandbox: "blue",
  demo: "violet",
  simulated: "violet",
  simulated_pending: "violet",
  degraded: "amber",
  stale: "amber",
  overdue: "red",
  rejected: "red",
  expired: "red",
  failed: "red",
  denied: "red",
  shortfall: "red",
  unavailable: "red",
  not_configured: "slate",
  disabled: "amber",
  configured: "green",
  void: "slate",
  simulated_cancelled: "slate",
  cancelled: "slate",
  paid_partially: "amber",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const tone = STATUS_TONES[status] || "slate";
  return (
    <Badge tone={tone} dot={false}>
      {label || titleCase(status)}
    </Badge>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  const tone: Tone =
    confidence === "high" ? "green" : confidence === "medium" ? "amber" : "slate";
  return <Badge tone={tone}>{titleCase(confidence)} confidence</Badge>;
}

export function RiskBadge({ risk }: { risk: string }) {
  const tone: Tone =
    risk === "high" ? "red" : risk === "medium" ? "amber" : risk === "low" ? "green" : "slate";
  return <Badge tone={tone}>{titleCase(risk)} risk</Badge>;
}
