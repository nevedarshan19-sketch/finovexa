import { useState } from "react";
import { FileSpreadsheet, Info, RefreshCw, Scale } from "lucide-react";
import { useApi } from "../../hooks/useApi";
import type { GstReport, NetGst } from "../../lib/taxTypes";
import { formatDate, money, moneyExact, plainPct } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageSkeleton,
  StatCard,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../ui";

function isoDaysAgo(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return value.toISOString().slice(0, 10);
}

const SUPPLY_LABELS: Record<string, string> = {
  intra_state: "Intra-state",
  inter_state: "Inter-state",
  unverified: "Unverified",
};

export function GstReports({ currency = "INR" }: { currency?: string }) {
  const [from, setFrom] = useState(isoDaysAgo(90));
  const [to, setTo] = useState(new Date().toISOString().slice(0, 10));
  const query = `date_from=${from}&date_to=${to}`;
  const report = useApi<GstReport>(`/tax/gst/report?${query}`);
  const net = useApi<NetGst>(`/tax/gst/net?${query}`);

  const reload = () => {
    report.reload();
    net.reload();
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="flex flex-wrap items-end gap-3">
          <Field label="From" className="w-40">
            <Input type="date" value={from} max={to} onChange={(event) => setFrom(event.target.value)} />
          </Field>
          <Field label="To" className="w-40">
            <Input type="date" value={to} min={from} onChange={(event) => setTo(event.target.value)} />
          </Field>
          <Button size="sm" icon={RefreshCw} variant="outline" onClick={reload}>
            Refresh
          </Button>
          <p className="ml-auto max-w-md text-[11px] leading-relaxed text-slate-400">
            Only issued invoices count; voids are excluded. Keep the period under two financial years.
          </p>
        </CardBody>
      </Card>

      {report.loading && !report.data ? (
        <PageSkeleton cards={3} />
      ) : report.error && !report.data ? (
        <ErrorState message={report.error} onRetry={report.reload} />
      ) : report.data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Taxable value" value={money(report.data.totals.taxable_value, currency)} tone="blue" icon={FileSpreadsheet} />
            <StatCard label="Output GST" value={money(report.data.totals.tax_amount, currency)} tone="violet" icon={Scale} />
            <StatCard label="Invoices" value={report.data.totals.invoice_count} tone="slate" />
            <StatCard
              label={net.data ? `Net GST ${net.data.net_gst.direction}` : "Net GST"}
              value={net.data ? money(net.data.net_gst.amount, currency) : "—"}
              tone={net.data?.net_gst.direction === "refundable" ? "green" : "amber"}
              sub={net.data ? `After ${money(net.data.input_tax_credit.available, currency)} input credit` : undefined}
            />
          </div>

          {report.data.warnings.length > 0 && (
            <Callout tone="amber" title="Before you file" icon={Info}>
              <ul className="list-disc space-y-1 pl-4">
                {report.data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Callout>
          )}

          <Card>
            <CardHeader title="Invoice-wise GST" description={`${report.data.period.from} to ${report.data.period.to}`} />
            <CardBody className="pt-3">
              {report.data.invoices.length === 0 ? (
                <EmptyState
                  title="No invoices in this period"
                  description="Issue an invoice in GST & Billing, or choose a wider date range."
                />
              ) : (
                <TableWrap>
                  <THead>
                    <TR>
                      <TH>Invoice</TH>
                      <TH>Issued</TH>
                      <TH>Customer</TH>
                      <TH>Supply</TH>
                      <TH className="text-right">Taxable</TH>
                      <TH className="text-right">CGST</TH>
                      <TH className="text-right">SGST</TH>
                      <TH className="text-right">IGST</TH>
                      <TH className="text-right">Total</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {report.data.invoices.map((invoice) => (
                      <TR key={invoice.id}>
                        <TD>
                          <span className="font-semibold text-ink-900">{invoice.number}</span>
                          {invoice.items_without_hsn > 0 && (
                            <Badge tone="amber" className="ml-2">
                              {invoice.items_without_hsn} without HSN
                            </Badge>
                          )}
                        </TD>
                        <TD>{formatDate(invoice.issue_date)}</TD>
                        <TD>{invoice.customer_name ?? "—"}</TD>
                        <TD>
                          <span className="flex flex-wrap items-center gap-1">
                            {SUPPLY_LABELS[invoice.supply_type] ?? invoice.supply_type}
                            {!invoice.supply_verified && <Badge tone="amber">verify</Badge>}
                          </span>
                        </TD>
                        <TD className="text-right tabular">{moneyExact(invoice.taxable_value, currency)}</TD>
                        <TD className="text-right tabular">{moneyExact(invoice.cgst_amount, currency)}</TD>
                        <TD className="text-right tabular">{moneyExact(invoice.sgst_amount, currency)}</TD>
                        <TD className="text-right tabular">{moneyExact(invoice.igst_amount, currency)}</TD>
                        <TD className="text-right tabular font-semibold">{moneyExact(invoice.total_amount, currency)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </TableWrap>
              )}
            </CardBody>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="By GST rate" description="Tax charged per slab in this period" />
              <CardBody className="pt-3">
                {report.data.by_rate.length === 0 ? (
                  <EmptyState title="No rated lines" description="Invoice lines in this period will appear here." />
                ) : (
                  <TableWrap>
                    <THead>
                      <TR>
                        <TH>Rate</TH>
                        <TH className="text-right">Taxable</TH>
                        <TH className="text-right">Tax</TH>
                        <TH className="text-right">Invoices</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {report.data.by_rate.map((row) => (
                        <TR key={row.gst_rate}>
                          <TD>{plainPct(row.gst_rate)}</TD>
                          <TD className="text-right tabular">{moneyExact(row.taxable_value, currency)}</TD>
                          <TD className="text-right tabular">{moneyExact(row.tax_amount, currency)}</TD>
                          <TD className="text-right">{row.invoice_count}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </TableWrap>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="By HSN / SAC" description="GSTR-1 style summary, grouped by code and rate" />
              <CardBody className="pt-3">
                {report.data.by_hsn.length === 0 ? (
                  <EmptyState title="No HSN codes" description="Add the verified HSN/SAC code to each invoice line." />
                ) : (
                  <TableWrap>
                    <THead>
                      <TR>
                        <TH>Code</TH>
                        <TH className="text-right">Rate</TH>
                        <TH className="text-right">Quantity</TH>
                        <TH className="text-right">Taxable</TH>
                        <TH className="text-right">Tax</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {report.data.by_hsn.map((row, index) => (
                        <TR key={`${row.hsn_sac ?? "none"}-${row.gst_rate}-${index}`}>
                          <TD>{row.hsn_sac ?? <Badge tone="amber">missing</Badge>}</TD>
                          <TD className="text-right">{plainPct(row.gst_rate)}</TD>
                          <TD className="text-right tabular">{row.quantity}</TD>
                          <TD className="text-right tabular">{moneyExact(row.taxable_value, currency)}</TD>
                          <TD className="text-right tabular">{moneyExact(row.tax_amount, currency)}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </TableWrap>
                )}
              </CardBody>
            </Card>
          </div>

          <Callout tone="slate" title="Estimate, not a return" icon={Info}>
            {net.data?.note ?? report.data.note}
          </Callout>
        </>
      ) : null}
    </div>
  );
}
