import { Badge } from "../ui";
import { type CreditAging, type CreditReportColumn } from "../../lib/creditTypes";
import { formatDate, moneyExact, plainPct, titleCase } from "../../lib/utils";

const RISK: Record<string, { tone: "green" | "amber" | "red" | "violet" | "slate" | "blue"; label: string; hint: string }> = {
  normal: { tone: "green", label: "Normal", hint: "Within the credit limit and no overdue amount." },
  watch: { tone: "amber", label: "Watch", hint: "Utilisation has crossed the warning threshold." },
  critical: { tone: "red", label: "Critical", hint: "Utilisation has crossed the critical threshold." },
  over_limit: { tone: "red", label: "Over limit", hint: "Outstanding is above the approved credit limit." },
  overdue: { tone: "amber", label: "Overdue", hint: "The customer has past-due invoices." },
  on_hold: { tone: "violet", label: "On hold", hint: "New credit sales are on hold for this customer." },
  not_configured: { tone: "slate", label: "No limit", hint: "No credit limit is configured." },
};

export function RiskBadge({ status }: { status: string | null | undefined }) {
  const spec = RISK[status || "not_configured"] || {
    tone: "slate" as const,
    label: titleCase(status || "Unknown"),
    hint: "",
  };
  return (
    <Badge tone={spec.tone} dot title={spec.hint}>
      {spec.label}
    </Badge>
  );
}

const SUPPLIER_STATUS: Record<string, "green" | "amber" | "slate"> = {
  active: "green",
  on_hold: "amber",
  inactive: "slate",
};

export function SupplierStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={SUPPLIER_STATUS[status] || "slate"} dot>
      {titleCase(status)}
    </Badge>
  );
}

const BILL_STATUS: Record<string, "green" | "amber" | "red" | "slate"> = {
  paid: "green",
  partial: "amber",
  unpaid: "red",
  void: "slate",
};

export function BillStatusBadge({ status }: { status: string }) {
  return <Badge tone={BILL_STATUS[status] || "slate"}>{titleCase(status)}</Badge>;
}

export function AgingRow({ aging }: { aging: CreditAging }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {(["0-30", "31-60", "61-90", "90+"] as const).map((bucket, index) => (
        <div key={bucket} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{bucket} days</p>
          <p
            className={
              "mt-1 tabular text-sm font-semibold " +
              (index === 3 && Number(aging[bucket]) > 0 ? "text-rose-600" : "text-ink-900")
            }
          >
            {moneyExact(aging[bucket])}
          </p>
        </div>
      ))}
    </div>
  );
}

export function ReportCell({
  column,
  value,
}: {
  column: CreditReportColumn;
  value: string | number | boolean | null | undefined;
}) {
  if (value === null || value === undefined || value === "") return <span className="text-slate-400">—</span>;
  if (column.kind === "money") return <span className="tabular">{moneyExact(Number(value))}</span>;
  if (column.kind === "percent") return <span className="tabular">{plainPct(Number(value))}</span>;
  if (column.kind === "date") return <span className="whitespace-nowrap">{formatDate(String(value))}</span>;
  return <span className="break-words">{String(value)}</span>;
}
