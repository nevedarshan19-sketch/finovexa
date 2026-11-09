import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type Numeric = number | string | null | undefined;

function toNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function money(
  value: Numeric,
  currency = "INR",
  options: Intl.NumberFormatOptions = {},
): string {
  const parsed = toNumber(value);
  if (parsed === null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
    ...options,
  }).format(parsed);
}

export function moneyExact(value: Numeric, currency = "INR"): string {
  return money(value, currency, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function compactMoney(value: Numeric, currency = "INR"): string {
  const parsed = toNumber(value);
  if (parsed === null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(parsed);
}

export function number(value: Numeric, digits = 0): string {
  const parsed = toNumber(value);
  if (parsed === null) return "—";
  return new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(parsed);
}

export function compactNumber(value: Numeric, digits = 1): string {
  const parsed = toNumber(value);
  if (parsed === null) return "—";
  return new Intl.NumberFormat("en-IN", {
    notation: "compact",
    maximumFractionDigits: digits,
  }).format(parsed);
}

export function pct(value: Numeric, digits = 1): string {
  const parsed = toNumber(value);
  if (parsed === null) return "—";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(digits)}%`;
}

export function plainPct(value: Numeric, digits = 1): string {
  const parsed = toNumber(value);
  if (parsed === null) return "—";
  return `${parsed.toFixed(digits)}%`;
}

function parseDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T00:00:00`);
  const normalized = value.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatDateShort(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short" }).format(date);
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function timeAgo(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(date);
}

export function countdown(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  const diff = date.getTime() - Date.now();
  if (diff <= 0) return "expired";
  const minutes = Math.round(diff / 60000);
  if (minutes < 60) return `${minutes}m left`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m left`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h left`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : plural || `${singular}s`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
