import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BadgeCheck,
  Calculator,
  Check,
  CircleDollarSign,
  FileText,
  Info,
  Layers,
  ReceiptText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { get, getErrorMessage, post } from "../../lib/api";
import { useApi } from "../../hooks/useApi";
import type {
  AccountingPricingResponse,
  PricingAddon,
  QuotationEstimate,
  SoftwareTier,
} from "../../lib/pricingTypes";
import { money, number } from "../../lib/utils";import {
  DisclaimerBox,
  Eyebrow,
  GlassCard,
  GradientText,
  Pill,
  PublicCheckbox,
  PublicError,
  PublicField,
  PublicInput,
  PublicLoading,
  PublicSelect,
  PublicTextarea,
  Reveal,
  Section,
  SectionHeading,
} from "../../components/public/PublicUI";
import { cn } from "../../lib/utils";

type BillingMode = "monthly" | "annual";

interface CalculatorForm {
  business_name: string;
  contact_name: string;
  email: string;
  phone: string;
  annual_turnover: string;
  business_type: string;
  turnover_range: string;
  gst_status: string;
  monthly_transactions: string;
  bank_accounts: string;
  financial_year: string;
  services: string[];
  payroll_required: boolean;
  inventory_required: boolean;
  requirements: string;
  consent: boolean;
  website: string;
}

function currentFinancialYear(): string {
  const now = new Date();
  const year = now.getFullYear();
  const start = now.getMonth() + 1 >= 4 ? year : year - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

function rangeForTurnover(value: number): string {
  if (value < 2_000_000) return "Under INR 20 lakh";
  if (value < 10_000_000) return "INR 20 lakh - 1 crore";
  if (value < 50_000_000) return "INR 1 crore - 5 crore";
  if (value < 250_000_000) return "INR 5 crore - 25 crore";
  return "Above INR 25 crore";
}

const emptyForm: CalculatorForm = {
  business_name: "",
  contact_name: "",
  email: "",
  phone: "",
  annual_turnover: "",
  business_type: "Proprietorship",
  turnover_range: "Under INR 20 lakh",
  gst_status: "Registered - regular",
  monthly_transactions: "",
  bank_accounts: "1",
  financial_year: currentFinancialYear(),
  services: ["bookkeeping"],
  payroll_required: false,
  inventory_required: false,
  requirements: "",
  consent: false,
  website: "",
};

function AddonRow({ addon }: { addon: PricingAddon }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/[0.06] py-2.5 last:border-0">
      <div>
        <p className="text-[12px] font-semibold text-white">{addon.label}</p>
        <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{addon.description}</p>
      </div>
      <span className="shrink-0 text-[11px] font-semibold text-slate-300">
        {addon.priced ? money(addon.amount) : addon.cadence === "one_time" ? "Quoted" : "Included in quote"}
      </span>
    </div>
  );
}

function TierCard({ tier, mode, discount }: { tier: SoftwareTier; mode: BillingMode; discount: number }) {
  const price = mode === "monthly" ? tier.monthly_price : tier.annual_price;
  return (
    <GlassCard hover className="flex h-full flex-col p-5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-300">
            {tier.label}
          </p>
          <p className="mt-1 text-[11px] text-slate-500">
            Annual turnover {tier.turnover_max ? `up to ${money(tier.turnover_max)}` : "above ₹1 crore"}
          </p>
        </div>
        <Pill tone="blue">{mode === "monthly" ? "Monthly" : "Annual"}</Pill>
      </div>
      <div className="mt-4 flex items-end gap-1.5">
        <span className="text-[28px] font-semibold tracking-tight text-white">{money(price)}</span>
        <span className="pb-1 text-[11px] text-slate-500">/ {mode === "monthly" ? "month" : "year"}</span>
      </div>
      <p className="mt-1 min-h-[18px] text-[10.5px] text-slate-500">
        {mode === "annual"
          ? discount > 0
            ? `${money(tier.annual_effective_monthly)}/month effective · ${discount}% annual discount`
            : `Equivalent to ${money(tier.annual_effective_monthly)}/month · no annual discount currently configured`
          : "Billed monthly"}
      </p>
      <p className="mt-2.5 text-[11.5px] leading-relaxed text-slate-400">{tier.description}</p>
      <ul className="mt-3 space-y-1.5 text-[11px] text-slate-300">
        {tier.features.map((feature) => (
          <li key={feature} className="flex items-start gap-2">
            <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-300" aria-hidden />
            {feature}
          </li>
        ))}
      </ul>
      <div className="mt-auto pt-4">
        <Link
          to="/register"
          className="flex items-center justify-center gap-2 rounded-xl border border-white/15 px-3 py-2 text-[11px] font-semibold text-slate-200 transition hover:border-brand-400/40 hover:bg-white/5"
        >
          Choose plan <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      </div>
    </GlassCard>
  );
}

export function PricingPage() {
  const pricing = useApi<AccountingPricingResponse>("/accounting/public/pricing");
  const [mode, setMode] = useState<BillingMode>("monthly");
  const [form, setForm] = useState<CalculatorForm>(emptyForm);
  const [estimate, setEstimate] = useState<QuotationEstimate | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<{ reference: string; message: string } | null>(null);

  const rules = pricing.data?.accounting;
  const annualDiscount = pricing.data?.software.annual_discount_percent ?? 0;
  const turnoverValue = Number(form.annual_turnover);

  useEffect(() => {
    if (!Number.isFinite(turnoverValue) || turnoverValue <= 0) {
      setEstimate(null);
      setEstimateError(null);
      return;
    }
    let alive = true;
    setEstimateError(null);
    const timer = window.setTimeout(() => {
      get<QuotationEstimate>(
        `/accounting/public/quotation-estimate?annual_turnover=${encodeURIComponent(form.annual_turnover)}`,
        { auth: false },
      )
        .then((result) => {
          if (alive) setEstimate(result);
        })
        .catch((err: unknown) => {
          if (alive) setEstimateError(getErrorMessage(err));
        });
    }, 350);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [turnoverValue]);

  useEffect(() => {
    if (!Number.isFinite(turnoverValue) || turnoverValue <= 0) return;
    setForm((current) => ({
      ...current,
      turnover_range: rangeForTurnover(turnoverValue),
    }));
  }, [turnoverValue]);

  const groupedServices = useMemo(
    () => (rules?.services ?? []).filter((service) => service.key !== "itr_filing"),
    [rules],
  );

  const toggleService = (key: string) => {
    setForm((current) => ({
      ...current,
      services: current.services.includes(key)
        ? current.services.filter((item) => item !== key)
        : [...current.services, key],
    }));
  };

  const requestItr = () => {
    setForm((current) => ({
      ...current,
      services: current.services.includes("itr_filing")
        ? current.services
        : [...current.services, "itr_filing"],
      requirements: current.requirements || "ITR filing enquiry: which return applies will be confirmed before filing.",
    }));
    document.getElementById("accounting-quote")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const submit = async () => {
    setSubmitError(null);
    if (form.website.trim()) return; // honeypot
    if (!rules) return;
    if (!form.business_name.trim() || !form.contact_name.trim() || !form.email.trim()) {
      setSubmitError("Business name, contact name and email are required.");
      return;
    }
    if (!Number.isFinite(turnoverValue) || turnoverValue <= 0) {
      setSubmitError("Enter the annual turnover so the indicative benchmark can be calculated.");
      return;
    }
    if (form.services.length === 0) {
      setSubmitError("Select at least one accounting service.");
      return;
    }
    if (!form.consent) {
      setSubmitError("Please confirm consent to be contacted about this quotation.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await post<{
        reference: string;
        status: string;
        estimate: QuotationEstimate;
        message: string;
      }>(
        "/accounting/public/enquiries",
        {
          business_name: form.business_name.trim(),
          contact_name: form.contact_name.trim(),
          email: form.email.trim(),
          phone: form.phone.trim() || null,
          business_type: form.business_type,
          turnover_range: form.turnover_range,
          gst_status: form.gst_status,
          services: form.services,
          monthly_transactions: form.monthly_transactions
            ? Number(form.monthly_transactions)
            : null,
          requirements: form.requirements.trim() || null,
          annual_turnover: form.annual_turnover,
          bank_accounts: form.bank_accounts ? Number(form.bank_accounts) : null,
          payroll_required: form.payroll_required,
          inventory_required: form.inventory_required,
          financial_year: form.financial_year,
          consent: true,
          website: "",
        },
        { auth: false },
      );
      setEstimate(response.estimate);
      setSubmitted({ reference: response.reference, message: response.message });
    } catch (err) {
      setSubmitError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="pb-10">
      <Section className="pb-10 pt-14 sm:pt-20">
        <Reveal>
          <div className="mx-auto max-w-3xl text-center">
            <Eyebrow icon={CircleDollarSign}>Pricing &amp; quotations</Eyebrow>
            <h1 className="mt-5 text-balance text-[38px] font-semibold leading-[1.06] tracking-tight text-white sm:text-[50px]">
              Clear prices for software.{" "}
              <GradientText>Approved quotations for experts.</GradientText>
            </h1>
            <p className="mt-4 text-sm leading-relaxed text-slate-400 sm:text-[15px]">
              Business Manager subscription fees and professional accounting fees are separate.
              Accounting quotations start from an indicative benchmark and are only final after a
              senior accountant approves them.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <Pill tone="emerald">
                <ShieldCheck className="h-3 w-3" aria-hidden /> No auto-charges
              </Pill>
              <Pill tone="blue">
                <ReceiptText className="h-3 w-3" aria-hidden /> GST shown separately
              </Pill>
              <Pill tone="violet">
                <BadgeCheck className="h-3 w-3" aria-hidden /> Senior-approved quotations
              </Pill>
            </div>
          </div>
        </Reveal>
      </Section>

      <Section className="pb-14">
        {pricing.loading && !pricing.data && <PublicLoading cards={6} />}
        {pricing.error && !pricing.data && (
          <PublicError message={pricing.error} onRetry={pricing.reload} />
        )}
        {pricing.data && rules && (
          <>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <SectionHeading
                eyebrow="Business Manager software"
                title={<>Subscription plans by annual turnover</>}
                description="Published monthly prices. Annual billing uses the administrator's configured discount — it is never invented or applied automatically."
              />
              <div className="inline-flex rounded-xl border border-white/10 bg-white/[0.03] p-1">
                {(["monthly", "annual"] as BillingMode[]).map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setMode(option)}
                    aria-pressed={mode === option}
                    className={cn(
                      "rounded-lg px-3.5 py-1.5 text-[11px] font-semibold capitalize transition",
                      mode === option
                        ? "bg-white/10 text-white shadow-sm"
                        : "text-slate-400 hover:text-slate-200",
                    )}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {pricing.data.software.tiers.map((tier, index) => (
                <Reveal key={tier.key} delay={index * 40}>
                  <TierCard tier={tier} mode={mode} discount={annualDiscount} />
                </Reveal>
              ))}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Pill tone={annualDiscount > 0 ? "emerald" : "amber"}>
                <Info className="h-3 w-3" aria-hidden />
                {annualDiscount > 0
                  ? `${annualDiscount}% annual billing discount is configured by the administrator`
                  : "No annual billing discount is currently configured"}
              </Pill>
              <p className="text-[11px] text-slate-500">{pricing.data.software.note}</p>
            </div>

            <div className="mt-8 overflow-hidden rounded-2xl border border-white/[0.08]">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-[11.5px]">
                  <thead className="bg-white/[0.04] text-[10px] uppercase tracking-[0.14em] text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-semibold">Plan</th>
                      <th className="px-4 py-3 font-semibold">Turnover band</th>
                      <th className="px-4 py-3 text-right font-semibold">Monthly</th>
                      <th className="px-4 py-3 text-right font-semibold">Annual</th>
                      <th className="px-4 py-3 font-semibold">Notable capabilities</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pricing.data.software.tiers.map((tier) => (
                      <tr key={tier.key} className="border-t border-white/[0.06] text-slate-300">
                        <td className="px-4 py-3 font-semibold text-white">{tier.label}</td>
                        <td className="px-4 py-3 text-slate-400">
                          {tier.turnover_max
                            ? `${money(tier.turnover_min)} – ${money(tier.turnover_max)}`
                            : `Above ${money(tier.turnover_min)}`}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">{money(tier.monthly_price)}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{money(tier.annual_price)}</td>
                        <td className="px-4 py-3 text-slate-400">{tier.features[tier.features.length - 1]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <p className="mt-3 text-[10.5px] leading-relaxed text-slate-500">
              Software subscription prices exclude applicable taxes ({pricing.data.software.tax_rate_percent}% GST
              shown separately). {pricing.data.software.tax_note} Subscription checkout is not enabled in this
              build, so choosing a plan does not charge a card.
            </p>
          </>
        )}
      </Section>

      <Section id="accounting-quote" className="scroll-mt-24 pb-16">
        {pricing.data && rules && (
          <div className="grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
            <Reveal>
              <GlassCard className="p-5 sm:p-6">
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-500/15 text-brand-200">
                    <Calculator className="h-5 w-5" aria-hidden />
                  </span>
                  <div>
                    <h2 className="text-[21px] font-semibold tracking-tight text-white">
                      Accounting quotation calculator
                    </h2>
                    <p className="mt-1 text-[12px] leading-relaxed text-slate-400">
                      Tell us the scope. We show the {rules.benchmark_percent}% indicative benchmark only — a
                      senior accountant reviews the details and approves the final quotation.
                    </p>
                  </div>
                </div>

                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                  <PublicField label="Business name" htmlFor="quote-business" required>
                    <PublicInput
                      id="quote-business"
                      value={form.business_name}
                      onChange={(event) => setForm({ ...form, business_name: event.target.value })}
                      placeholder="e.g. Meridian Traders"
                    />
                  </PublicField>
                  <PublicField label="Contact name" htmlFor="quote-contact" required>
                    <PublicInput
                      id="quote-contact"
                      value={form.contact_name}
                      onChange={(event) => setForm({ ...form, contact_name: event.target.value })}
                    />
                  </PublicField>
                  <PublicField label="Email" htmlFor="quote-email" required>
                    <PublicInput
                      id="quote-email"
                      type="email"
                      value={form.email}
                      onChange={(event) => setForm({ ...form, email: event.target.value })}
                    />
                  </PublicField>
                  <PublicField label="Phone" htmlFor="quote-phone">
                    <PublicInput
                      id="quote-phone"
                      value={form.phone}
                      onChange={(event) => setForm({ ...form, phone: event.target.value })}
                    />
                  </PublicField>
                  <PublicField
                    label="Annual turnover (INR)"
                    htmlFor="quote-turnover"
                    hint={`Shows a ${rules.benchmark_percent}% indicative starting benchmark. Never a final fee.`}
                    required
                  >
                    <PublicInput
                      id="quote-turnover"
                      inputMode="numeric"
                      value={form.annual_turnover}
                      onChange={(event) =>
                        setForm({ ...form, annual_turnover: event.target.value.replace(/[^\d.]/g, "") })
                      }
                      placeholder="3500000"
                    />
                  </PublicField>
                  <PublicField label="Business type" htmlFor="quote-type" required>
                    <PublicSelect
                      id="quote-type"
                      value={form.business_type}
                      onChange={(event) => setForm({ ...form, business_type: event.target.value })}
                    >
                      {rules.business_types.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </PublicSelect>
                  </PublicField>
                  <PublicField label="Turnover range" htmlFor="quote-range" required>
                    <PublicSelect
                      id="quote-range"
                      value={form.turnover_range}
                      onChange={(event) => setForm({ ...form, turnover_range: event.target.value })}
                    >
                      {rules.turnover_ranges.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </PublicSelect>
                  </PublicField>
                  <PublicField label="GST registration" htmlFor="quote-gst" required>
                    <PublicSelect
                      id="quote-gst"
                      value={form.gst_status}
                      onChange={(event) => setForm({ ...form, gst_status: event.target.value })}
                    >
                      {rules.gst_statuses.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </PublicSelect>
                  </PublicField>
                  <PublicField label="Monthly transactions" htmlFor="quote-txns">
                    <PublicInput
                      id="quote-txns"
                      inputMode="numeric"
                      value={form.monthly_transactions}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          monthly_transactions: event.target.value.replace(/[^\d]/g, ""),
                        })
                      }
                      placeholder="180"
                    />
                  </PublicField>
                  <PublicField label="Bank accounts" htmlFor="quote-banks">
                    <PublicInput
                      id="quote-banks"
                      inputMode="numeric"
                      value={form.bank_accounts}
                      onChange={(event) =>
                        setForm({ ...form, bank_accounts: event.target.value.replace(/[^\d]/g, "") })
                      }
                    />
                  </PublicField>
                  <PublicField label="Financial year" htmlFor="quote-fy" required>
                    <PublicInput
                      id="quote-fy"
                      value={form.financial_year}
                      onChange={(event) => setForm({ ...form, financial_year: event.target.value })}
                      placeholder="2026-27"
                    />
                  </PublicField>
                </div>

                <div className="mt-4">
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-400">
                    Required accounting services <span className="text-brand-300">*</span>
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {groupedServices.map((service) => (
                      <PublicCheckbox
                        key={service.key}
                        checked={form.services.includes(service.key)}
                        onChange={() => toggleService(service.key)}
                        label={
                          <span>
                            <span className="font-medium text-slate-200">{service.name}</span>
                            <span className="block text-[10.5px] text-slate-500">{service.description}</span>
                          </span>
                        }
                      />
                    ))}
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-5">
                  <PublicCheckbox
                    checked={form.payroll_required}
                    onChange={(checked) => setForm({ ...form, payroll_required: checked })}
                    label="Payroll processing required"
                  />
                  <PublicCheckbox
                    checked={form.inventory_required}
                    onChange={(checked) => setForm({ ...form, inventory_required: checked })}
                    label="Inventory / stock accounting required"
                  />
                </div>

                <PublicField label="Anything else" htmlFor="quote-notes" className="mt-4">
                  <PublicTextarea
                    id="quote-notes"
                    value={form.requirements}
                    onChange={(event) => setForm({ ...form, requirements: event.target.value })}
                    placeholder="Branches, GSTINs, reporting deadlines, prior-year issues…"
                    className="min-h-[84px]"
                  />
                </PublicField>

                <input
                  type="text"
                  tabIndex={-1}
                  autoComplete="off"
                  aria-hidden
                  value={form.website}
                  onChange={(event) => setForm({ ...form, website: event.target.value })}
                  className="hidden"
                />

                <div className="mt-4">
                  <PublicCheckbox
                    checked={form.consent}
                    onChange={(checked) => setForm({ ...form, consent: checked })}
                    label="I consent to FINOVEXA contacting me about this quotation. Submitting a request does not create an engagement or charge any amount."
                  />
                </div>

                {submitError && (
                  <p className="mt-3 rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-[11.5px] text-rose-200">
                    {submitError}
                  </p>
                )}

                {submitted ? (
                  <div className="mt-4 rounded-xl border border-emerald-400/25 bg-emerald-500/10 px-4 py-3">
                    <p className="text-[12px] font-semibold text-emerald-200">
                      Request received · {submitted.reference}
                    </p>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-emerald-100/80">
                      {submitted.message}
                    </p>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => void submit()}
                    disabled={submitting || !pricing.data}
                    className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-2.5 text-[12px] font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {submitting ? "Submitting request…" : "Request a quotation"}
                    <ArrowRight className="h-4 w-4" aria-hidden />
                  </button>
                )}
              </GlassCard>
            </Reveal>

            <div className="space-y-4">
              <Reveal delay={80}>
                <GlassCard className="p-5">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-[13px] font-semibold text-white">Indicative benchmark</h3>
                    <Pill tone="amber">{rules.benchmark_percent}% of turnover</Pill>
                  </div>
                  <div className="mt-4 space-y-3">
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                        Indicative annual fee
                      </p>
                      <p className="mt-1 text-[28px] font-semibold tracking-tight text-white">
                        {estimate ? money(estimate.indicative_annual_fee) : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                        Monthly equivalent
                      </p>
                      <p className="mt-1 text-[16px] font-semibold text-slate-200">
                        {estimate ? money(estimate.indicative_monthly_equivalent) : "—"}
                      </p>
                    </div>
                    {estimate?.software_tier && (
                      <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-[11px] text-slate-400">
                        Business Manager software tier shown separately:{" "}
                        <span className="font-semibold text-slate-200">
                          {estimate.software_tier.label} · {money(estimate.software_tier.monthly_price)}/month
                        </span>
                      </div>
                    )}
                    {estimateError && <p className="text-[11px] text-rose-300">{estimateError}</p>}
                    <p className="rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-[10.5px] leading-relaxed text-amber-100/80">
                      {estimate?.note ?? rules.benchmark_note}
                    </p>
                  </div>
                </GlassCard>
              </Reveal>

              <Reveal delay={120}>
                <GlassCard className="p-5">
                  <h3 className="text-[13px] font-semibold text-white">Additional service charges</h3>
                  <p className="mt-1 text-[10.5px] leading-relaxed text-slate-500">
                    Charges the senior accountant can add to a quotation. Unpriced items are assessed during
                    review, never presented as a fixed public price.
                  </p>
                  <div className="mt-2">
                    {pricing.data.addons.map((addon) => (
                      <AddonRow key={addon.key} addon={addon} />
                    ))}
                  </div>
                </GlassCard>
              </Reveal>

              <Reveal delay={160}>
                <GlassCard className="p-5">
                  <h3 className="flex items-center gap-2 text-[13px] font-semibold text-white">
                    <Layers className="h-4 w-4 text-brand-300" aria-hidden /> What the quotation includes
                  </h3>
                  <ul className="mt-3 space-y-2 text-[11px] leading-relaxed text-slate-400">
                    <li>Indicative annual fee, monthly equivalent and selected services</li>
                    <li>Additional charges and any approved discount, stated separately</li>
                    <li>Final approved price, payment frequency and quotation validity</li>
                    <li>Terms and conditions, plus separate tax disclosure</li>
                  </ul>
                  <p className="mt-3 text-[10.5px] leading-relaxed text-slate-500">
                    Quotation validity: {rules.quote_validity_days} days unless the senior accountant sets another
                    period. Accepting a quotation records a decision only — no amount is charged.
                  </p>
                </GlassCard>
              </Reveal>
            </div>
          </div>
        )}
      </Section>

      <Section className="pb-16">
        <SectionHeading
          eyebrow="Income-tax returns"
          title={
            <>
              ITR filing, priced and <GradientText>kept separate</GradientText>
            </>
          }
          description="ITR filing is a separate paid service. It is never included automatically in a bookkeeping or GST package."
        />
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {(pricing.data?.itr.items ?? []).map((item, index) => (
            <Reveal key={item.key} delay={index * 50}>
              <GlassCard hover className="flex h-full flex-col p-5">
                <Pill tone="cyan">Return type</Pill>
                <h3 className="mt-3 text-[15px] font-semibold text-white">{item.label}</h3>
                <p className="mt-2 text-[24px] font-semibold tracking-tight text-white">
                  {money(item.price_min)}
                  {item.price_max ? ` – ${money(item.price_max)}` : ""}
                </p>
                <p className="mt-1 text-[10.5px] text-slate-500">
                  {item.price_max ? "Range, subject to written quotation" : "Fixed professional fee, ex-GST"}
                </p>
                <p className="mt-2 flex-1 text-[11px] leading-relaxed text-slate-400">{item.description}</p>
                <p className="mt-2 text-[10.5px] leading-relaxed text-slate-500">{item.price_note}</p>
                <button
                  type="button"
                  onClick={requestItr}
                  className="mt-4 inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/15 px-3 py-2 text-[11px] font-semibold text-slate-200 transition hover:border-cyan-400/40 hover:bg-white/5"
                >
                  Request ITR filing <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </button>
              </GlassCard>
            </Reveal>
          ))}
        </div>
        <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
          {pricing.data?.itr.note ??
            "Only appropriately qualified and authorised professionals perform regulated filing or certification work."}
        </p>
      </Section>

      <Section className="pb-16">
        <div className="grid gap-4 lg:grid-cols-3">
          {[
            {
              icon: FileText,
              title: "Separate fees",
              copy: "Business Manager subscriptions and professional accounting fees are never bundled into one undisclosed amount.",
            },
            {
              icon: ShieldCheck,
              title: "Senior approval",
              copy: "Every accounting quotation is reviewed and approved by a senior accountant before it can be sent to a customer.",
            },
            {
              icon: Info,
              title: "No invented discounts",
              copy: "Annual billing uses only the discount the administrator configures. No promotional or testimonial claims are published.",
            },
          ].map((item) => (
            <Reveal key={item.title}>
              <GlassCard className="h-full p-5">
                <item.icon className="h-4 w-4 text-brand-300" aria-hidden />
                <p className="mt-3 text-sm font-semibold text-white">{item.title}</p>
                <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-400">{item.copy}</p>
              </GlassCard>
            </Reveal>
          ))}
        </div>
      </Section>

      <Section className="pb-6">
        <Reveal>
          <GlassCard className="p-6 sm:p-8">
            <SectionHeading
              eyebrow="Business rules"
              title={
                <>
                  What is included, and what is <GradientText>not assumed</GradientText>
                </>
              }
            />
            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <div className="space-y-2.5">
                {[
                  "Software subscription and accounting fees are quoted and invoiced separately.",
                  "Accounting services are never advertised as free.",
                  "GST is disclosed separately; final prices exclude applicable taxes unless stated.",
                  "ITR filing requires a separate engagement and fee.",
                ].map((line) => (
                  <p key={line} className="flex items-start gap-2 text-[11.5px] leading-relaxed text-slate-400">
                    <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" aria-hidden />
                    {line}
                  </p>
                ))}
              </div>
              <div className="space-y-2.5">
                {[
                  "The 2% benchmark is indicative and never a final or automatically issued price.",
                  "Accepting a quotation does not trigger a payment; a separate secure process applies.",
                  "Additional work outside the approved scope is quoted before it starts.",
                  "Regulated filing or certification is performed only by appropriately qualified professionals.",
                ].map((line) => (
                  <p key={line} className="flex items-start gap-2 text-[11.5px] leading-relaxed text-slate-400">
                    <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" aria-hidden />
                    {line}
                  </p>
                ))}
              </div>
            </div>
            {pricing.data && (
              <DisclaimerBox className="mt-5" title="Indicative information">
                {pricing.data.disclosures.join(" ")}
              </DisclaimerBox>
            )}
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <a
                href="#accounting-quote"
                className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2.5 text-[12px] font-semibold text-white transition hover:brightness-110"
              >
                Request a quotation <ArrowRight className="h-4 w-4" aria-hidden />
              </a>
              <Link
                to="/accounting"
                className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-[12px] font-semibold text-slate-200 transition hover:bg-white/5"
              >
                <Sparkles className="h-4 w-4" aria-hidden /> Explore accounting services
              </Link>
              <span className="text-[10.5px] text-slate-500">
                Prices managed in-app · {rules ? `${number(rules.tax_rate_percent, 1)}% GST disclosed separately` : ""}
              </span>
            </div>
          </GlassCard>
        </Reveal>
      </Section>
    </div>
  );
}
