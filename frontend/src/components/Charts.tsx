import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  CashPoint,
  ExpectedReceivable,
  ExpenseBreakdownPoint,
  ForecastSeriesPoint,
  PayPalSeriesPoint,
  SeriesPoint,
} from "../lib/types";
import { compactMoney, formatDateShort, moneyExact, titleCase } from "../lib/utils";
import { useTheme } from "../context/ThemeContext";
import { ProgressBar } from "./ui";

function useChartPalette() {
  const { theme } = useTheme();
  const dark = theme === "dark";
  return {
    dark,
    grid: dark ? "rgba(148,163,184,0.16)" : "#e8eef7",
    axis: dark ? "#8496ad" : "#94a3b8",
    brand: dark ? "#4d94ff" : "#2478f0",
    brandSoft: dark ? "#7ab3ff" : "#4a94ff",
    teal: dark ? "#2dd4bf" : "#0d9488",
    positive: dark ? "#34d399" : "#6ee7b7",
    expense: dark ? "#fb7185" : "#fda4af",
    violet: dark ? "#a78bfa" : "#7c3aed",
    warning: dark ? "#fbbf24" : "#f59e0b",
  };
}

interface TooltipPayloadItem {
  name?: string;
  dataKey?: string | number;
  value?: number | string;
  color?: string;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string | number;
  currency: string;
  labels?: Record<string, string>;
}

function ChartTooltip({ active, payload, label, currency, labels }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-xl border border-[color:var(--tooltip-border)] bg-[var(--tooltip-bg)] px-3 py-2.5 shadow-pop">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        {typeof label === "string" ? formatDateShort(label) : label}
      </p>
      <div className="mt-1.5 space-y-1">
        {payload.map((item) => (
          <div key={String(item.dataKey)} className="flex items-center justify-between gap-5 text-xs">
            <span className="flex items-center gap-1.5 text-slate-500">
              <span
                className="h-2 w-2 rounded-sm"
                style={{ backgroundColor: item.color || "#2478f0" }}
                aria-hidden
              />
              {labels?.[String(item.dataKey)] || titleCase(String(item.name || item.dataKey || ""))}
            </span>
            <span className="font-semibold tabular-nums text-ink-900">
              {moneyExact(Number(item.value || 0), currency)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RevenueExpenseChart({
  data,
  currency,
  height = 270,
}: {
  data: SeriesPoint[];
  currency: string;
  height?: number;
}) {
  const palette = useChartPalette();
  const axisProps = {
    tick: { fontSize: 10, fill: palette.axis },
    axisLine: false,
    tickLine: false,
  } as const;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={palette.brand} stopOpacity={0.28} />
            <stop offset="100%" stopColor={palette.brand} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          {...axisProps}
          tickFormatter={(value: string) => formatDateShort(value)}
          minTickGap={38}
        />
        <YAxis
          {...axisProps}
          width={64}
          tickFormatter={(value: number) => compactMoney(value, currency)}
        />
        <Tooltip
          content={<ChartTooltip currency={currency} />}
          cursor={{ stroke: palette.axis, strokeDasharray: "4 4" }}
        />
        <Bar dataKey="expenses" name="Expenses" fill={palette.expense} radius={[3, 3, 0, 0]} maxBarSize={11} />
        <Area
          type="monotone"
          dataKey="revenue"
          name="Revenue"
          stroke={palette.brand}
          strokeWidth={2.2}
          fill="url(#revenueFill)"
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function CashTrendChart({
  data,
  currency,
  height = 260,
}: {
  data: CashPoint[];
  currency: string;
  height?: number;
}) {
  const palette = useChartPalette();
  const axisProps = {
    tick: { fontSize: 10, fill: palette.axis },
    axisLine: false,
    tickLine: false,
  } as const;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="balanceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={palette.teal} stopOpacity={0.24} />
            <stop offset="100%" stopColor={palette.teal} stopOpacity={0.01} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          {...axisProps}
          tickFormatter={(value: string) => formatDateShort(value)}
          minTickGap={32}
        />
        <YAxis
          {...axisProps}
          width={64}
          tickFormatter={(value: number) => compactMoney(value, currency)}
        />
        <Tooltip content={<ChartTooltip currency={currency} />} />
        <Bar dataKey="inflow" name="Inflow" fill={palette.positive} radius={[3, 3, 0, 0]} maxBarSize={13} />
        <Bar dataKey="outflow" name="Outflow" fill={palette.expense} radius={[3, 3, 0, 0]} maxBarSize={13} />
        <Line
          type="monotone"
          dataKey="balance"
          name="Balance"
          stroke={palette.teal}
          strokeWidth={2.4}
          dot={false}
          activeDot={{ r: 4 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function ForecastChart({
  data,
  currency,
  reserve,
  height = 300,
}: {
  data: ForecastSeriesPoint[];
  currency: string;
  reserve: number;
  height?: number;
}) {
  const shortfall = data.some((point) => point.below_reserve);
  const palette = useChartPalette();
  const axisProps = {
    tick: { fontSize: 10, fill: palette.axis },
    axisLine: false,
    tickLine: false,
  } as const;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="forecastFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={palette.brand} stopOpacity={0.28} />
            <stop offset="100%" stopColor={palette.brand} stopOpacity={0.01} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          {...axisProps}
          tickFormatter={(value: string) => formatDateShort(value)}
          minTickGap={36}
        />
        <YAxis
          {...axisProps}
          width={66}
          tickFormatter={(value: number) => compactMoney(value, currency)}
        />
        <Tooltip content={<ChartTooltip currency={currency} />} />
        <ReferenceLine
          y={reserve}
          stroke={shortfall ? "#e11d48" : "#f59e0b"}
          strokeDasharray="5 4"
          strokeWidth={1.5}
          label={{
            value: "Reserve floor",
            position: "insideTopLeft",
            fontSize: 10,
            fill: shortfall ? "#be123c" : "#b45309",
          }}
        />
        <Area
          type="monotone"
          dataKey="balance"
          name="Projected balance"
          stroke={palette.brand}
          strokeWidth={2.2}
          fill="url(#forecastFill)"
        />
        <Line
          type="monotone"
          dataKey="inflow"
          name="Expected inflow"
          stroke={palette.teal}
          strokeWidth={1.4}
          dot={false}
          strokeDasharray="4 4"
        />
        <Line
          type="monotone"
          dataKey="outflow"
          name="Expected outflow"
          stroke={palette.expense}
          strokeWidth={1.4}
          dot={false}
          strokeDasharray="4 4"
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export const DONUT_COLORS = ["#2478f0", "#0d9488", "#7c3aed", "#f59e0b", "#ec4899", "#06b6d4", "#84cc16", "#64748b"];

export function ExpenseBreakdownChart({
  data,
  currency,
  height = 240,
}: {
  data: ExpenseBreakdownPoint[];
  currency: string;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey="amount"
          nameKey="category"
          innerRadius={62}
          outerRadius={92}
          paddingAngle={2}
          stroke="none"
        >
          {data.map((entry, index) => (
            <Cell key={entry.category} fill={DONUT_COLORS[index % DONUT_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            borderRadius: 12,
            border: "1px solid var(--tooltip-border)",
            background: "var(--tooltip-bg)",
            color: "var(--text-1)",
            fontSize: 12,
            boxShadow: "var(--shadow-pop)",
          }}
          formatter={(value: number, name: string) => [moneyExact(value, currency), titleCase(name)]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function AgingBars({
  data,
  currency,
  compact = false,
}: {
  data: { bucket: string; label: string; amount: number; count: number }[];
  currency: string;
  compact?: boolean;
}) {
  const max = Math.max(1, ...data.map((item) => item.amount));
  return (
    <div className={compact ? "space-y-2.5" : "space-y-3"}>
      {data.map((item, index) => {
        const overdue = index >= 2;
        return (
          <div key={item.bucket}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="font-medium text-slate-600">
                {item.label}
                <span className="ml-1.5 text-[10px] font-normal text-slate-400">
                  {item.count} {item.count === 1 ? "invoice" : "invoices"}
                </span>
              </span>
              <span className="font-semibold tabular-nums text-ink-900">
                {compactMoney(item.amount, currency)}
              </span>
            </div>
            <ProgressBar
              value={(item.amount / max) * 100}
              tone={overdue ? (index >= 4 ? "red" : "amber") : "blue"}
              className="mt-1.5"
              label={item.label}
            />
          </div>
        );
      })}
    </div>
  );
}

export function PayPalFlowChart({
  data,
  currency,
  height = 240,
}: {
  data: PayPalSeriesPoint[];
  currency: string;
  height?: number;
}) {
  const palette = useChartPalette();
  const axisProps = {
    tick: { fontSize: 10, fill: palette.axis },
    axisLine: false,
    tickLine: false,
  } as const;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          {...axisProps}
          tickFormatter={(value: string) => formatDateShort(value)}
          minTickGap={32}
        />
        <YAxis
          {...axisProps}
          width={64}
          tickFormatter={(value: number) => compactMoney(value, currency)}
        />
        <Tooltip content={<ChartTooltip currency={currency} />} />
        <Bar dataKey="received" name="Received" fill={palette.positive} radius={[3, 3, 0, 0]} maxBarSize={13} />
        <Bar dataKey="refunded" name="Refunded" fill={palette.expense} radius={[3, 3, 0, 0]} maxBarSize={13} />
        <Line
          type="monotone"
          dataKey="net"
          name="Net"
          stroke={palette.brand}
          strokeWidth={2.2}
          dot={false}
          activeDot={{ r: 4 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function PriceAreaChart({
  data,
  currency,
  height = 280,
}: {
  data: { date: string; close: number }[];
  currency: string;
  height?: number;
}) {
  const first = data[0]?.close ?? 0;
  const last = data[data.length - 1]?.close ?? 0;
  const up = last >= first;
  const palette = useChartPalette();
  const stroke = up ? palette.teal : palette.expense;
  const axisProps = {
    tick: { fontSize: 10, fill: palette.axis },
    axisLine: false,
    tickLine: false,
  } as const;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.26} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0.01} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={palette.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          {...axisProps}
          tickFormatter={(value: string) => formatDateShort(value)}
          minTickGap={38}
        />
        <YAxis
          {...axisProps}
          width={60}
          domain={["auto", "auto"]}
          tickFormatter={(value: number) => compactMoney(value, currency)}
        />
        <Tooltip content={<ChartTooltip currency={currency} labels={{ close: "Close" }} />} />
        <Area
          type="monotone"
          dataKey="close"
          name="Close"
          stroke={stroke}
          strokeWidth={2}
          fill="url(#priceFill)"
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function ReceivableForecast({ items, currency }: { items: ExpectedReceivable[]; currency: string }) {
  if (!items.length) {
    return <p className="px-1 py-6 text-center text-xs text-slate-400">No receivables fall inside this horizon.</p>;
  }
  return (
    <div className="space-y-2">
      {items.slice(0, 8).map((item) => (
        <div
          key={item.invoice_id}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-slate-100 bg-white px-3 py-2"
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold text-ink-900">
              {item.invoice_number} · {item.customer}
            </p>
            <p className="text-[10px] text-slate-400">
              Expected {formatDateShort(item.expected_date)} · {item.bucket}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs font-semibold tabular-nums text-ink-900">
              {compactMoney(item.expected_amount, currency)}
            </p>
            <p className="text-[10px] text-slate-400">{Math.round(item.probability * 100)}% weighted</p>
          </div>
        </div>
      ))}
    </div>
  );
}
