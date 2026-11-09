import { useState } from "react";
import { Calculator, FileSpreadsheet, Info, Landmark, Percent, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useApi } from "../hooks/useApi";
import type { TaxGstOptions, TaxOverview } from "../lib/taxTypes";
import { money } from "../lib/utils";
import { Badge, Button, Callout, Card, CardBody, ErrorState, PageHeader, PageSkeleton, StatCard, Tabs } from "../components/ui";
import { GstCalculator } from "../components/tax/GstCalculator";
import { GstCataloguePanel } from "../components/tax/GstCataloguePanel";
import { GstReports } from "../components/tax/GstReports";
import { HsnPanel } from "../components/tax/HsnPanel";
import { IncomeTaxPanel } from "../components/tax/IncomeTaxPanel";
import { ItcPanel } from "../components/tax/ItcPanel";

type Module = "gst" | "income";
type GstView = "calculator" | "reports" | "itc" | "hsn" | "catalogue";

export function TaxCenterPage() {
  const { profile } = useAuth();
  const currency = profile?.currency || "INR";
  const overview = useApi<TaxOverview>("/tax/overview");
  const options = useApi<TaxGstOptions>("/tax/gst/options");
  const [module, setModule] = useState<Module>("gst");
  const [gstView, setGstView] = useState<GstView>("calculator");

  const net = overview.data?.gst;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Compliance"
        title="Tax Center"
        description="Indian GST and income-tax calculations from stored rule sets. Every figure is plain arithmetic — no AI model decides a tax amount."
        actions={
          <>
            <Badge tone="green" dot>
              Deterministic engine
            </Badge>
            <Badge tone="slate">No paid API</Badge>
          </>
        }
      />

      {overview.loading && !overview.data ? (
        <PageSkeleton cards={3} />
      ) : overview.error && !overview.data ? (
        <ErrorState message={overview.error} onRetry={overview.reload} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Output GST this quarter"
              value={money(net?.output_gst.tax_amount ?? 0, currency)}
              sub={`${net?.output_gst.invoice_count ?? 0} invoices`}
              tone="violet"
              icon={Percent}
            />
            <StatCard
              label="Available input credit"
              value={money(net?.input_tax_credit.available ?? 0, currency)}
              tone="green"
              icon={FileSpreadsheet}
            />
            <StatCard
              label={`Net GST ${net?.net_gst.direction ?? ""}`}
              value={money(net?.net_gst.amount ?? 0, currency)}
              tone={net?.net_gst.direction === "refundable" ? "green" : "amber"}
              icon={Calculator}
            />
            <StatCard
              label={`Income tax · FY ${overview.data?.financial_year ?? "—"}`}
              value={overview.data?.income_tax.estimate_count ?? 0}
              sub="saved estimates"
              tone="blue"
              icon={Landmark}
            />
          </div>

          <Tabs
            items={[
              { key: "gst", label: "GST" },
              { key: "income", label: "Income Tax" },
            ]}
            value={module}
            onChange={setModule}
          />

          {module === "gst" ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Tabs
                  size="sm"
                  items={[
                    { key: "calculator", label: "Calculator" },
                    { key: "reports", label: "Reports" },
                    { key: "catalogue", label: "GST Catalogue" },
                    { key: "itc", label: "Input credit" },
                    { key: "hsn", label: "HSN / SAC" },
                  ]}
                  value={gstView}
                  onChange={setGstView}
                />
                <p className="text-[11px] text-slate-400">
                  CGST and SGST apply within a state; IGST applies across states.
                </p>
              </div>

              {options.loading && !options.data ? (
                <PageSkeleton cards={2} />
              ) : options.error && !options.data ? (
                <ErrorState message={options.error} onRetry={options.reload} />
              ) : options.data ? (
                gstView === "calculator" ? (
                  <GstCalculator options={options.data} currency={currency} />
                ) : gstView === "reports" ? (
                  <GstReports currency={currency} />
                ) : gstView === "catalogue" ? (
                  <GstCataloguePanel
                    endpoint="/tax/gst/catalogue"
                    role="owner"
                    searchKey="q"
                    canEdit
                    exportPath="/tax/gst/catalogue/export"
                  />
                ) : gstView === "itc" ? (
                  <ItcPanel currency={currency} />
                ) : (
                  <HsnPanel options={options.data} onChanged={options.reload} />
                )
              ) : null}
            </div>
          ) : (
            <IncomeTaxPanel currency={currency} />
          )}

          <Card>
            <CardBody className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-3xl">
                <p className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                  <ShieldCheck className="h-4 w-4 text-brand-600" aria-hidden />
                  Estimates requiring professional verification
                </p>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">
                  GST figures come from your own invoices and purchase bills. Income-tax figures come from the stored
                  rule version shown on each estimate, and an accountant must approve an estimate before any filing.
                  FINOVEXA does not file returns, pay tax or determine an amount with AI.
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                icon={Info}
                onClick={() => {
                  overview.reload();
                  options.reload();
                }}
              >
                Refresh
              </Button>
            </CardBody>
          </Card>

          {net && net.warnings.length > 0 && (
            <Callout tone="amber" title="Data still to verify">
              <ul className="list-disc space-y-1 pl-4">
                {net.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Callout>
          )}
        </>
      )}
    </div>
  );
}
