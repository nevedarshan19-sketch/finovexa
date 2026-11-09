import { useEffect, useMemo, useState } from "react";
import {
  BadgeCheck,
  Calculator,
  FileCheck2,
  Info,
  Landmark,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
  Wallet,
} from "lucide-react";
import { getErrorMessage, post } from "../../lib/api";
import { useApi, type ApiState } from "../../hooks/useApi";
import { useToast } from "../../context/ToastContext";
import type {
  IncomeTaxComparison,
  IncomeTaxResult,
  IncomeTaxRules,
  TaxEstimateSummary,
  TaxRuleSet,
} from "../../lib/taxTypes";
import { formatDate, money, moneyExact, plainPct } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSkeleton,
  Select,
  StatCard,
  TableWrap,
  TBody,
  TD,
  Textarea,
  TH,
  THead,
  TR,
} from "../ui";

interface Draft {
  gross_salary: string;
  basic_salary: string;
  hra_received: string;
  rent_paid: string;
  professional_tax: string;
  employer_nps: string;
  metro_city: boolean;
  net_profit: string;
  presumptive: "none" | "44ad" | "44ada";
  gross_receipts: string;
  digital_receipts_pct: string;
  other_income: string;
  equity_stcg: string;
  equity_ltcg: string;
  other_ltcg: string;
  other_stcg: string;
  d80c: string;
  d80ccd1b: string;
  d80d: string;
  d80tta: string;
  d80ttb: string;
  d24b: string;
  d80g: string;
  d80e: string;
  dother: string;
}

const EMPTY: Draft = {
  gross_salary: "",
  basic_salary: "",
  hra_received: "",
  rent_paid: "",
  professional_tax: "",
  employer_nps: "",
  metro_city: false,
  net_profit: "",
  presumptive: "none",
  gross_receipts: "",
  digital_receipts_pct: "",
  other_income: "",
  equity_stcg: "",
  equity_ltcg: "",
  other_ltcg: "",
  other_stcg: "",
  d80c: "",
  d80ccd1b: "",
  d80d: "",
  d80tta: "",
  d80ttb: "",
  d24b: "",
  d80g: "",
  d80e: "",
  dother: "",
};

function num(value: string): string {
  return value.trim() === "" ? "0" : value;
}

function toPayload(draft: Draft) {
  return {
    salary: {
      gross_salary: num(draft.gross_salary),
      basic_salary: num(draft.basic_salary),
      hra_received: num(draft.hra_received),
      rent_paid: num(draft.rent_paid),
      professional_tax: num(draft.professional_tax),
      employer_nps: num(draft.employer_nps),
      metro_city: draft.metro_city,
    },
    business: {
      net_profit: num(draft.net_profit),
      presumptive: draft.presumptive,
      gross_receipts: num(draft.gross_receipts),
      digital_receipts_pct: num(draft.digital_receipts_pct),
    },
    other_income: num(draft.other_income),
    capital_gains: {
      equity_stcg: num(draft.equity_stcg),
      equity_ltcg: num(draft.equity_ltcg),
      other_ltcg: num(draft.other_ltcg),
      other_stcg: num(draft.other_stcg),
    },
    deductions: {
      "80C": num(draft.d80c),
      "80CCD1B": num(draft.d80ccd1b),
      "80D": num(draft.d80d),
      "80TTA": num(draft.d80tta),
      "80TTB": num(draft.d80ttb),
      "24B": num(draft.d24b),
      "80G": num(draft.d80g),
      "80E": num(draft.d80e),
      other: num(draft.dother),
    },
  };
}

function ruleFor(rules: IncomeTaxRules | null, regime: "new" | "old"): TaxRuleSet | null {
  return rules?.rule_sets.find((row) => row.regime === regime) ?? null;
}

export function IncomeTaxPanel({ currency = "INR" }: { currency?: string }) {
  const { toast } = useToast();
  const [financialYear, setFinancialYear] = useState("");
  const rules = useApi<IncomeTaxRules>(
    `/tax/income/rules${financialYear ? `?financial_year=${financialYear}` : ""}`,
  );
  const estimates = useApi<{ items: TaxEstimateSummary[] }>("/tax/income/estimates");
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [comparison, setComparison] = useState<IncomeTaxComparison | null>(null);
  const [result, setResult] = useState<IncomeTaxResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!financialYear && rules.data) setFinancialYear(rules.data.financial_year);
  }, [rules.data, financialYear]);

  const newRules = ruleFor(rules.data, "new");
  const oldRules = ruleFor(rules.data, "old");
  const activeYear = financialYear || rules.data?.financial_year || "";

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const calculate = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = await post<IncomeTaxComparison>("/tax/income/compare", {
        financial_year: activeYear,
        inputs: toPayload(draft),
      });
      setComparison(body);
      setResult(body.regimes[body.recommended_regime] ?? null);
    } catch (err: unknown) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!comparison) return;
    setSaving(true);
    try {
      await post("/tax/income/estimates", {
        financial_year: activeYear,
        inputs: toPayload(draft),
      });
      toast({ title: "Estimate saved as a draft", description: "An accountant must approve it before filing.", tone: "success" });
      estimates.reload();
    } catch (err: unknown) {
      toast({ title: "Could not save the estimate", description: getErrorMessage(err), tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setDraft(EMPTY);
    setComparison(null);
    setResult(null);
    setError(null);
  };

  const yearOptions = rules.data?.financial_years ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="flex flex-wrap items-end gap-3">
          <Field label="Financial year" className="w-40">
            <Select
              value={activeYear}
              onChange={(event) => {
                setFinancialYear(event.target.value);
                setComparison(null);
                setResult(null);
              }}
            >
              {yearOptions.map((year) => (
                <option key={year} value={year}>
                  FY {year}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex flex-wrap items-center gap-2 pb-1">
            {rules.data && (
              <>
                <Badge tone="blue">AY {rules.data.assessment_year}</Badge>
                {newRules && <Badge tone="violet">New regime · {newRules.version}</Badge>}
                {oldRules && <Badge tone="slate">Old regime · {oldRules.version}</Badge>}
              </>
            )}
            <Badge tone="green">Rules stored as configuration</Badge>
          </div>
          <div className="ml-auto flex gap-2">
            <Button size="sm" variant="ghost" icon={RotateCcw} onClick={reset}>
              Clear
            </Button>
            <Button icon={Calculator} loading={busy} onClick={() => void calculate()} disabled={!activeYear}>
              Compare both regimes
            </Button>
          </div>
        </CardBody>
      </Card>

      {rules.loading && !rules.data ? (
        <PageSkeleton cards={3} />
      ) : rules.error && !rules.data ? (
        <ErrorState message={rules.error} onRetry={rules.reload} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
          <div className="space-y-4">
            <Card>
              <CardHeader title="Salary income" description="HRA, standard deduction and professional tax come from the rule set" icon={Wallet} />
              <CardBody className="grid grid-cols-2 gap-3">
                <Field label="Gross salary" className="col-span-2">
                  <Input inputMode="decimal" aria-label="Gross salary" value={draft.gross_salary} onChange={(event) => set("gross_salary", event.target.value)} />
                </Field>
                <Field label="Basic salary">
                  <Input inputMode="decimal" aria-label="Basic salary" value={draft.basic_salary} onChange={(event) => set("basic_salary", event.target.value)} />
                </Field>
                <Field label="HRA received">
                  <Input inputMode="decimal" aria-label="HRA received" value={draft.hra_received} onChange={(event) => set("hra_received", event.target.value)} />
                </Field>
                <Field label="Rent paid">
                  <Input inputMode="decimal" aria-label="Rent paid" value={draft.rent_paid} onChange={(event) => set("rent_paid", event.target.value)} />
                </Field>
                <Field label="Professional tax">
                  <Input inputMode="decimal" aria-label="Professional tax" value={draft.professional_tax} onChange={(event) => set("professional_tax", event.target.value)} />
                </Field>
                <Field label="Employer NPS" className="col-span-2" hint="Claimed under 80CCD(2), capped as a share of basic">
                  <Input inputMode="decimal" aria-label="Employer NPS" value={draft.employer_nps} onChange={(event) => set("employer_nps", event.target.value)} />
                </Field>
                <div className="col-span-2">
                  <Checkbox checked={draft.metro_city} onChange={(checked) => set("metro_city", checked)} label="I live in a metro city (Delhi, Mumbai, Kolkata, Chennai)" />
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Business or professional income" description="Books net profit, or a presumptive section" icon={Landmark} />
              <CardBody className="grid grid-cols-2 gap-3">
                <Field label="Net profit from books" className="col-span-2">
                  <Input inputMode="decimal" aria-label="Net profit from books" value={draft.net_profit} onChange={(event) => set("net_profit", event.target.value)} />
                </Field>
                <Field label="Presumptive section">
                  <Select value={draft.presumptive} onChange={(event) => set("presumptive", event.target.value as Draft["presumptive"])}>
                    <option value="none">None</option>
                    <option value="44ad">44AD · business</option>
                    <option value="44ada">44ADA · professional</option>
                  </Select>
                </Field>
                <Field label="Gross receipts">
                  <Input inputMode="decimal" aria-label="Gross receipts" value={draft.gross_receipts} onChange={(event) => set("gross_receipts", event.target.value)} />
                </Field>
                {draft.presumptive === "44ad" && (
                  <Field label="Digital receipts %" className="col-span-2" hint="Digital receipts qualify for the lower presumptive rate">
                    <Input inputMode="decimal" aria-label="Digital receipts percentage" value={draft.digital_receipts_pct} onChange={(event) => set("digital_receipts_pct", event.target.value)} />
                  </Field>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Other income and capital gains" description="Gains taxed under 111A/112A use the stored rates" />
              <CardBody className="grid grid-cols-2 gap-3">
                <Field label="Other income" className="col-span-2" hint="Interest, rental or dividend income taxed at slab rates">
                  <Input inputMode="decimal" aria-label="Other income" value={draft.other_income} onChange={(event) => set("other_income", event.target.value)} />
                </Field>
                <Field label="Equity STCG (111A)">
                  <Input inputMode="decimal" aria-label="Equity STCG" value={draft.equity_stcg} onChange={(event) => set("equity_stcg", event.target.value)} />
                </Field>
                <Field label="Equity LTCG (112A)">
                  <Input inputMode="decimal" aria-label="Equity LTCG" value={draft.equity_ltcg} onChange={(event) => set("equity_ltcg", event.target.value)} />
                </Field>
                <Field label="Other LTCG">
                  <Input inputMode="decimal" aria-label="Other LTCG" value={draft.other_ltcg} onChange={(event) => set("other_ltcg", event.target.value)} />
                </Field>
                <Field label="Other STCG">
                  <Input inputMode="decimal" aria-label="Other STCG" value={draft.other_stcg} onChange={(event) => set("other_stcg", event.target.value)} />
                </Field>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Deductions" description={`Allowed only where the ${activeYear} rule set permits them`} />
              <CardBody className="grid grid-cols-2 gap-3">
                {(
                  [
                    ["d80c", "80C"],
                    ["d80ccd1b", "80CCD(1B)"],
                    ["d80d", "80D"],
                    ["d80tta", "80TTA"],
                    ["d80ttb", "80TTB"],
                    ["d24b", "24(b)"],
                    ["d80g", "80G"],
                    ["d80e", "80E"],
                    ["dother", "Other"],
                  ] as const
                ).map(([key, label]) => (
                  <Field key={key} label={label}>
                    <Input aria-label={`Deduction ${label}`} inputMode="decimal" value={draft[key]} onChange={(event) => set(key, event.target.value)} />
                  </Field>
                ))}
              </CardBody>
            </Card>

            {error && <Callout tone="red" title="Could not estimate">{error}</Callout>}
          </div>

          <div className="space-y-4">
            {!comparison ? (
              <Card>
                <CardHeader title="Estimate" description="Enter income on the left, then compare the two regimes" icon={Sparkles} />
                <CardBody>
                  <EmptyState
                    title="No estimate yet"
                    description="FINOVEXA uses plain arithmetic on stored slabs. No AI model decides the tax amount."
                  />
                </CardBody>
              </Card>
            ) : (
              <>
                <Card>
                  <CardBody className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                          FY {comparison.financial_year} · AY {comparison.assessment_year}
                        </p>
                        <p className="mt-1 text-sm text-slate-600">
                          {comparison.recommended_regime === "new" ? "New regime" : "Old regime"} gives the lower
                          estimate, saving {money(comparison.savings, currency)}.
                        </p>
                      </div>
                      <Button size="sm" variant="outline" icon={Save} loading={saving} onClick={() => void save()}>
                        Save as draft
                      </Button>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      {(["new", "old"] as const).map((regime) => {
                        const row = comparison.regimes[regime];
                        if (!row) return null;
                        const active = result?.regime === regime;
                        return (
                          <button
                            key={regime}
                            type="button"
                            onClick={() => setResult(row)}
                            className={`rounded-xl border p-4 text-left transition ${
                              active
                                ? "border-brand-300 bg-brand-50/60 ring-1 ring-brand-200"
                                : "border-slate-200 bg-white hover:border-slate-300"
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                                {row.regime_label}
                              </span>
                              {comparison.recommended_regime === regime && <Badge tone="green">recommended</Badge>}
                            </div>
                            <p className="mt-2 text-xl font-semibold tabular text-ink-900">
                              {moneyExact(row.tax.total_liability, currency)}
                            </p>
                            <p className="mt-1 text-[11px] text-slate-500">
                              Total income {money(row.total_income, currency)} · effective {plainPct(row.effective_rate_pct)}
                            </p>
                            <p className="mt-1 text-[11px] text-slate-400">Rule version {row.rule_version}</p>
                          </button>
                        );
                      })}
                    </div>
                  </CardBody>
                </Card>

                {result && <TaxBreakdown result={result} currency={currency} newRule={newRules} oldRule={oldRules} />}

                <Callout tone="violet" title="Estimate only" icon={Info}>
                  {comparison.disclaimer}
                </Callout>
              </>
            )}

            <EstimatesCard estimates={estimates} onChanged={estimates.reload} currency={currency} />
          </div>
        </div>
      )}
    </div>
  );
}

function TaxBreakdown({
  result,
  currency,
  newRule,
  oldRule,
}: {
  result: IncomeTaxResult;
  currency: string;
  newRule: TaxRuleSet | null;
  oldRule: TaxRuleSet | null;
}) {
  const ruleSet = result.regime === "new" ? newRule : oldRule;
  const notes = result.notes;

  return (
    <Card>
      <CardHeader
        title={`${result.regime_label} · FY ${result.financial_year}`}
        description={`Assessment year ${result.assessment_year} · rule version ${result.rule_version}`}
        icon={FileCheck2}
        actions={<Badge tone="slate">No AI used</Badge>}
      />
      <CardBody className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard label="Gross total income" value={money(result.income.gross_total_income, currency)} tone="blue" />
          <StatCard label="Total income" value={money(result.total_income, currency)} tone="violet" />
          <StatCard label="Estimated liability" value={moneyExact(result.tax.total_liability, currency)} tone="amber" />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2 text-sm">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Income</p>
            <Line label="Net salary" value={result.income.salary.net_salary} currency={currency} />
            <Line label={`Business (${result.income.business.basis})`} value={result.income.business.income} currency={currency} />
            <Line label="Other income" value={result.income.other_income} currency={currency} />
            <Line label="Capital gains" value={result.income.capital_gains.equity_stcg + result.income.capital_gains.equity_ltcg + result.income.capital_gains.other_ltcg + result.income.capital_gains.other_stcg} currency={currency} />
            <div className="flex justify-between border-t border-slate-200 pt-2 font-semibold text-ink-900">
              <span>Total income</span>
              <span className="tabular">{moneyExact(result.total_income, currency)}</span>
            </div>
            <div className="mt-3 space-y-1.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Deductions allowed</p>
              {result.deductions.items.length === 0 ? (
                <p className="text-xs text-slate-400">No deductions were claimed.</p>
              ) : (
                result.deductions.items.map((row) => (
                  <div key={row.section} className="flex items-start justify-between gap-3 text-xs">
                    <span className="text-slate-600">
                      {row.section} · {row.label}
                      {row.reason && <span className="block text-[10px] text-slate-400">{row.reason}</span>}
                    </span>
                    <span className="tabular font-medium text-ink-900">{moneyExact(row.allowed, currency)}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="space-y-2 text-sm">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Tax computation</p>
            <Line label="Taxable slab income" value={result.tax.slab_income} currency={currency} />
            <Line label="Slab tax" value={result.tax.slab_tax} currency={currency} />
            <Line label="87A rebate" value={-result.tax.rebate_87a} currency={currency} />
            <Line label="Rebate marginal relief" value={-result.tax.rebate_marginal_relief} currency={currency} />
            <Line label="Capital-gains tax" value={result.tax.capital_gains_tax} currency={currency} />
            <Line label={`Surcharge @ ${plainPct(result.tax.surcharge_rate)}`} value={result.tax.surcharge} currency={currency} />
            <Line label="Surcharge marginal relief" value={-result.tax.surcharge_marginal_relief} currency={currency} />
            <Line label={`Health & education cess @ ${plainPct(result.tax.cess_rate)}`} value={result.tax.cess} currency={currency} />
            <Line label="Rounding" value={result.tax.rounding_adjustment} currency={currency} />
            <div className="flex justify-between border-t border-slate-200 pt-2 font-semibold text-ink-900">
              <span>Estimated liability</span>
              <span className="tabular">{moneyExact(result.tax.total_liability, currency)}</span>
            </div>
          </div>
        </div>

        <TableWrap>
          <THead>
            <TR>
              <TH>Slab</TH>
              <TH className="text-right">Rate</TH>
              <TH className="text-right">Income in slab</TH>
              <TH className="text-right">Tax</TH>
            </TR>
          </THead>
          <TBody>
            {result.tax.slabs.map((row, index) => (
              <TR key={index}>
                <TD>
                  {money(row.from, currency)} {row.to === null ? "and above" : `– ${money(row.to, currency)}`}
                </TD>
                <TD className="text-right">{plainPct(row.rate)}</TD>
                <TD className="text-right tabular">{moneyExact(row.taxable, currency)}</TD>
                <TD className="text-right tabular">{moneyExact(row.tax, currency)}</TD>
              </TR>
            ))}
          </TBody>
        </TableWrap>

        {result.tax.capital_gains.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Capital gains</p>
            {result.tax.capital_gains.map((row) => (
              <div key={row.category} className="flex items-center justify-between text-xs text-slate-600">
                <span>
                  {row.label} · {plainPct(row.rate)} · exemption {moneyExact(row.exemption, currency)}
                </span>
                <span className="tabular font-medium text-ink-900">{moneyExact(row.tax, currency)}</span>
              </div>
            ))}
          </div>
        )}

        {notes.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-[11px] leading-relaxed text-slate-500">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}

        {ruleSet && (
          <p className="text-[11px] leading-relaxed text-slate-400">
            Source: {ruleSet.source_note ?? "Stored rule set"} · effective {formatDate(ruleSet.effective_from)} to{" "}
            {ruleSet.effective_to ? formatDate(ruleSet.effective_to) : "—"}
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function Line({ label, value, currency }: { label: string; value: number; currency: string }) {
  return (
    <div className="flex items-center justify-between text-slate-600">
      <span>{label}</span>
      <span className="tabular font-medium text-ink-900">{moneyExact(value, currency)}</span>
    </div>
  );
}

function EstimatesCard({
  estimates,
  onChanged,
  currency,
}: {
  estimates: ApiState<{ items: TaxEstimateSummary[] }>;
  onChanged: () => void;
  currency: string;
}) {
  const { toast } = useToast();
  const [approving, setApproving] = useState<TaxEstimateSummary | null>(null);
  const [name, setName] = useState("");
  const [membership, setMembership] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const open = (row: TaxEstimateSummary) => {
    setApproving(row);
    setName("");
    setMembership("");
    setNote("");
  };

  const approve = async () => {
    if (!approving) return;
    setBusy(true);
    try {
      await post(`/tax/income/estimates/${approving.id}/approve`, {
        approved_by_name: name,
        membership_number: membership,
        approval_note: note || null,
      });
      toast({ title: "Estimate approved", description: "The sign-off is recorded in the activity log.", tone: "success" });
      setApproving(null);
      onChanged();
    } catch (err: unknown) {
      toast({ title: "Could not record approval", description: getErrorMessage(err), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const reopen = async (row: TaxEstimateSummary) => {
    try {
      await post(`/tax/income/estimates/${row.id}/reopen`, {});
      toast({ title: "Estimate reopened", description: "The previous sign-off was cleared.", tone: "success" });
      onChanged();
    } catch (err: unknown) {
      toast({ title: "Could not reopen", description: getErrorMessage(err), tone: "error" });
    }
  };

  const rows = useMemo(() => estimates.data?.items ?? [], [estimates.data]);

  return (
    <Card>
      <CardHeader
        title="Saved estimates"
        description="Filing needs an accountant's sign-off on a saved estimate"
        icon={ShieldCheck}
      />
      <CardBody className="pt-3">
        {estimates.loading && !estimates.data ? (
          <p className="py-6 text-center text-sm text-slate-500">Loading estimates…</p>
        ) : rows.length === 0 ? (
          <EmptyState
            title="No saved estimates"
            description="Calculate both regimes, then save the one you want reviewed."
          />
        ) : (
          <TableWrap>
            <THead>
              <TR>
                <TH>Financial year</TH>
                <TH>Regime</TH>
                <TH className="text-right">Liability</TH>
                <TH>Rule</TH>
                <TH>Status</TH>
                <TH className="text-right">Action</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((row) => (
                <TR key={row.id}>
                  <TD>{row.financial_year}</TD>
                  <TD>{row.regime === "new" ? "New" : "Old"}</TD>
                  <TD className="text-right tabular">{moneyExact(row.total_liability, currency)}</TD>
                  <TD>{row.rule_version}</TD>
                  <TD>
                    <Badge tone={row.status === "approved" ? "green" : "amber"}>
                      {row.status === "approved" ? `approved · ${row.approved_by_name ?? ""}` : "draft"}
                    </Badge>
                  </TD>
                  <TD>
                    <div className="flex justify-end">
                      {row.status === "approved" ? (
                        <Button size="sm" variant="ghost" icon={RotateCcw} onClick={() => void reopen(row)}>
                          Reopen
                        </Button>
                      ) : (
                        <Button size="sm" variant="outline" icon={BadgeCheck} onClick={() => open(row)}>
                          Accountant approval
                        </Button>
                      )}
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </TableWrap>
        )}
      </CardBody>

      <Modal
        open={approving !== null}
        onClose={() => setApproving(null)}
        title="Record accountant approval"
        description="The sign-off is attached to this estimate and written to the activity log."
        footer={
          <>
            <Button variant="outline" onClick={() => setApproving(null)} disabled={busy}>
              Cancel
            </Button>
            <Button icon={BadgeCheck} loading={busy} onClick={() => void approve()} disabled={!name || !membership}>
              Record approval
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Accountant name" required>
            <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="CA R. Iyer" />
          </Field>
          <Field label="Membership number" required hint="ICAI membership number of the signatory">
            <Input value={membership} onChange={(event) => setMembership(event.target.value)} />
          </Field>
          <Field label="Note">
            <Textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
          </Field>
          <Callout tone="amber" title="Approval is a record, not a filing">
            FINOVEXA never files a return or pays tax. The accountant must still check the figures and file on the
            government portal.
          </Callout>
        </div>
      </Modal>
    </Card>
  );
}
