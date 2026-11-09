import type { ReactNode } from "react";
import { Badge, Select } from "../ui";
import type { AccountingClient } from "../../lib/accountingTypes";
import { labelize, priorityTone, statusTone } from "../../lib/accounting";
import { cn } from "../../lib/utils";

export function StatusBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  return (
    <Badge tone={statusTone(status)} dot className={className}>
      {labelize(status)}
    </Badge>
  );
}

export function PriorityBadge({ priority }: { priority: string | null | undefined }) {
  if (!priority) return null;
  return <Badge tone={priorityTone(priority)}>{labelize(priority)}</Badge>;
}

export function ClientSelect({
  clients,
  value,
  onChange,
  placeholder = "Select a client",
  id,
  className,
  allowAll = false,
}: {
  clients: AccountingClient[];
  value: number | null;
  onChange: (clientId: number | null) => void;
  placeholder?: string;
  id?: string;
  className?: string;
  allowAll?: boolean;
}) {
  return (
    <Select
      id={id}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
      className={className}
    >
      {allowAll ? <option value="">All clients</option> : <option value="">{placeholder}</option>}
      {clients.map((client) => (
        <option key={client.id} value={client.id}>
          {client.business_name} · {client.code}
        </option>
      ))}
    </Select>
  );
}

export function InlineStat({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: ReactNode;
  tone?: "slate" | "blue" | "green" | "amber" | "red";
}) {
  const tones = {
    slate: "text-ink-900",
    blue: "text-brand-700",
    green: "text-emerald-700",
    amber: "text-amber-700",
    red: "text-rose-700",
  }[tone];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{label}</p>
      <p className={cn("mt-1 text-lg font-semibold tabular", tones)}>{value}</p>
    </div>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h2 className="text-[13px] font-semibold text-ink-900">{children}</h2>
      {action}
    </div>
  );
}
