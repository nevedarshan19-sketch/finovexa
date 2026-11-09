import type { AccountingServiceKey } from "./accountingTypes";

export type AccountingTone = "slate" | "blue" | "green" | "amber" | "red" | "violet" | "cyan";

export const SERVICE_LABELS: Record<AccountingServiceKey, string> = {
  bookkeeping: "Bookkeeping",
  gst_accounting: "GST accounting & returns",
  itr_filing: "ITR filing assistance",
  bank_reconciliation: "Bank reconciliation",
  sales_purchase: "Sales & purchase accounting",
  payroll: "Payroll management",
  financial_statements: "Financial statements",
  tally_support: "Tally support",
};

const TONE_BY_STATUS: Record<string, AccountingTone> = {
  new: "amber",
  contacted: "blue",
  quoted: "violet",
  quote_accepted: "green",
  onboarded: "green",
  declined: "red",
  onboarding: "cyan",
  active: "green",
  paused: "amber",
  archived: "slate",
  unassigned: "amber",
  assigned: "blue",
  in_progress: "blue",
  submitted: "violet",
  changes_requested: "red",
  approved: "green",
  delivered: "green",
  cancelled: "slate",
  draft: "slate",
  sent: "blue",
  accepted: "green",
  expired: "red",
  received: "slate",
  verified: "green",
  rejected: "red",
  pending: "amber",
  fulfilled: "green",
  issued: "blue",
  part_paid: "amber",
  paid: "green",
  void: "slate",
  unmatched: "slate",
  suggested: "amber",
  matched: "green",
  completed: "green",
  imported: "blue",
  reconciled: "green",
};

export function statusTone(status: string | null | undefined): AccountingTone {
  return TONE_BY_STATUS[(status || "").toLowerCase()] ?? "slate";
}

export function priorityTone(priority: string): AccountingTone {
  if (priority === "urgent") return "red";
  if (priority === "high") return "amber";
  if (priority === "low") return "slate";
  return "blue";
}

export function labelize(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replace(/[._-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function serviceLabel(key: string): string {
  return SERVICE_LABELS[key as AccountingServiceKey] || labelize(key);
}

export function tallyExportFormatLabel(format: string): string {
  return (
    {
      xlsx: "Excel",
      csv_zip: "CSV + XML",
      xml: "Tally XML",
      json: "JSON",
    }[format] || labelize(format)
  );
}

export function cadenceLabel(cadence: string): string {
  return (
    {
      monthly: "per month",
      quarterly: "per quarter",
      annual: "per year",
      one_time: "one time",
    }[cadence] || cadence
  );
}

export function formatMonth(period: string | null | undefined): string {
  if (!period || !/^\d{4}-\d{2}$/.test(period)) return period || "—";
  const [year, month] = period.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric" }).format(
    new Date(year, month - 1, 1),
  );
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}

export function downloadText(filename: string, text: string, mime = "text/csv;charset=utf-8"): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsText(file);
  });
}

function normaliseHeader(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** Minimal RFC-4180 CSV parser for accountant-entered voucher imports. */
export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim() !== "")) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  row.push(cell);
  if (row.some((value) => value.trim() !== "")) rows.push(row);
  if (rows.length < 2) return [];
  const headers = rows[0].map(normaliseHeader);
  return rows.slice(1).map((values) => {
    const record: Record<string, string> = {};
    headers.forEach((header, index) => {
      record[header] = (values[index] ?? "").trim();
    });
    return record;
  });
}

export const DOCUMENT_CATEGORIES = [
  { key: "purchase_bill", label: "Purchase bill" },
  { key: "sale_bill", label: "Sale bill" },
  { key: "bank_statement", label: "Bank statement" },
  { key: "gst_return", label: "GST return" },
  { key: "challan", label: "Challan" },
  { key: "payroll", label: "Payroll" },
  { key: "other", label: "Other" },
];

export const TASK_STATUSES = [
  "unassigned",
  "assigned",
  "in_progress",
  "submitted",
  "changes_requested",
  "approved",
  "delivered",
  "cancelled",
];

export const VOUCHER_TYPES = ["sale", "purchase", "journal", "payment", "receipt", "expense"] as const;

export const PAYMENT_METHODS = ["bank", "upi", "cash", "card", "cheque", "other"] as const;
