import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  ClipboardCheck,
  FileCheck2,
  FileSpreadsheet,
  Landmark,
  LockKeyhole,
  ReceiptText,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Users,
} from "lucide-react";
import { useApi } from "../../hooks/useApi";
import { getErrorMessage, post } from "../../lib/api";
import type { AccountingServiceKey, AccountingCatalogue } from "../../lib/accountingTypes";
import { cn } from "../../lib/utils";
import {
  DisclaimerBox,
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
  Eyebrow,
} from "../../components/public/PublicUI";

const SERVICE_ICONS: Record<AccountingServiceKey, typeof BookOpen> = {
  bookkeeping: BookOpen,
  gst_accounting: ReceiptText,
  itr_filing: FileCheck2,
  bank_reconciliation: Landmark,
  sales_purchase: ShoppingCart,
  payroll: Users,
  financial_statements: BarChart3,
  tally_support: FileSpreadsheet,
};

interface EnquiryForm {
  business_name: string;
  contact_name: string;
  email: string;
  phone: string;
  business_type: string;
  turnover_range: string;
  gst_status: string;
  services: AccountingServiceKey[];
  monthly_transactions: string;
  requirements: string;
  consent: boolean;
  website: string;
}

const EMPTY_FORM: EnquiryForm = {
  business_name: "",
  contact_name: "",
  email: "",
  phone: "",
  business_type: "",
  turnover_range: "",
  gst_status: "",
  services: [],
  monthly_transactions: "",
  requirements: "",
  consent: false,
  website: "",
};

export function AccountingServicesPage() {
  const catalogue = useApi<AccountingCatalogue>("/accounting/public/services");
  const [form, setForm] = useState<EnquiryForm>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [reference, setReference] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const data = catalogue.data;

  useEffect(() => {
    if (!data) return;
    setForm((current) => ({
      ...current,
      business_type: current.business_type || data.business_types[0] || "",
      turnover_range: current.turnover_range || data.turnover_ranges[0] || "",
      gst_status: current.gst_status || data.gst_statuses[0] || "",
    }));
  }, [data]);

  const serviceOptions = useMemo(() => data?.services || [], [data]);

  const update = <K extends keyof EnquiryForm>(key: K, value: EnquiryForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setFieldErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const toggleService = (key: AccountingServiceKey) => {
    update(
      "services",
      form.services.includes(key)
        ? form.services.filter((value) => value !== key)
        : [...form.services, key],
    );
  };

  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (form.business_name.trim().length < 2) errors.business_name = "Enter the registered or trading name.";
    if (form.contact_name.trim().length < 2) errors.contact_name = "Enter the person we should contact.";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim())) errors.email = "Enter a valid email address.";
    if (!form.business_type) errors.business_type = "Select a business type.";
    if (!form.turnover_range) errors.turnover_range = "Select an annual turnover range.";
    if (!form.gst_status) errors.gst_status = "Select the GST registration status.";
    if (form.services.length === 0) errors.services = "Select at least one service.";
    if (!form.consent) errors.consent = "Please confirm we may contact you about this enquiry.";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!validate()) return;
    setSubmitting(true);
    try {
      const transactions = form.monthly_transactions.trim();
      const result = await post<{ reference: string; message: string }>(
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
          monthly_transactions: transactions === "" ? null : Number(transactions),
          requirements: form.requirements.trim() || null,
          consent: form.consent,
          website: form.website || null,
        },
        { auth: false },
      );
      setReference(result.reference);
      setSuccessMessage(result.message);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (catalogue.loading && !data) {
    return <PublicLoading cards={6} />;
  }
  if (catalogue.error && !data) {
    return (
      <div className="py-16">
        <PublicError message={catalogue.error} onRetry={catalogue.reload} />
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="pb-10">
      <Section className="pb-12 pt-14 sm:pt-20">
        <div className="grid items-start gap-10 lg:grid-cols-[1.1fr_0.9fr]">
          <Reveal>
            <Eyebrow icon={ShieldCheck}>Professional accounting services</Eyebrow>
            <h1 className="mt-5 text-balance text-[40px] font-semibold leading-[1.06] tracking-tight text-white sm:text-[52px]">
              Accountants prepare. <GradientText>Seniors review.</GradientText> You stay in control.
            </h1>
            <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-400">
              A managed accounting practice connected to your FINOVEXA workspace. Enquiries are reviewed
              by a senior accountant, scoped properly and quoted in writing — never sold from a price
              card. AI helps with extraction and reconciliation; an accountant confirms every entry.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <a
                href="#services"
                className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-3 text-[13px] font-semibold text-white shadow-[0_18px_40px_-18px_rgba(36,120,240,0.95)] transition hover:brightness-110"
              >
                Explore Services <ArrowRight className="h-4 w-4" aria-hidden />
              </a>
              <a
                href="#enquiry"
                className="inline-flex items-center gap-2 rounded-xl border border-white/15 bg-white/[0.04] px-5 py-3 text-[13px] font-semibold text-slate-200 transition hover:border-brand-300/40 hover:bg-white/[0.07] hover:text-white"
              >
                Request a Consultation
              </a>
            </div>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <Pill tone="emerald">
                <Check className="h-3 w-3" aria-hidden /> Senior-reviewed work
              </Pill>
              <Pill tone="cyan">
                <LockKeyhole className="h-3 w-3" aria-hidden /> Business-level isolation
              </Pill>
              <Pill tone="amber">
                <FileCheck2 className="h-3 w-3" aria-hidden /> No published prices
              </Pill>
            </div>
          </Reveal>

          <Reveal delay={120}>
            <GlassCard className="p-6">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                How an engagement starts
              </p>
              <ol className="mt-4 space-y-3">
                {data.process.map((step, index) => (
                  <li key={step} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-brand-400/25 bg-brand-500/10 text-[10px] font-bold text-brand-200">
                      {index + 1}
                    </span>
                    <p className="text-[12.5px] leading-relaxed text-slate-300">{step}</p>
                  </li>
                ))}
              </ol>
              <div className="mt-5 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3.5 py-3 text-[11px] leading-relaxed text-slate-400">
                <span className="font-semibold text-slate-200">What we never do:</span> we do not promise
                completion before scoping, publish a fixed fee online, or file a return without an
                authorised channel and the accountant&apos;s sign-off.
              </div>
            </GlassCard>
          </Reveal>
        </div>
      </Section>

      <Section id="services" className="pb-16 scroll-mt-24">
        <Reveal>
          <SectionHeading
            eyebrow="Services"
            title={
              <>
                Eight services, <GradientText>one practice workflow</GradientText>
              </>
            }
            description="Each service is quoted after a senior accountant reviews your volumes, registrations and current books. The scope of every engagement is written into the quotation."
          />
        </Reveal>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {serviceOptions.map((service, index) => {
            const Icon = SERVICE_ICONS[service.key] || BookOpen;
            return (
              <Reveal key={service.key} delay={index * 40}>
                <GlassCard className="flex h-full flex-col p-5">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-[linear-gradient(140deg,rgba(36,120,240,0.25),rgba(14,165,183,0.12))] text-brand-200">
                    <Icon className="h-4 w-4" aria-hidden />
                  </span>
                  <h3 className="mt-4 text-[13.5px] font-semibold leading-snug text-white">{service.name}</h3>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-slate-400">{service.description}</p>
                  <ul className="mt-3 space-y-1.5">
                    {service.includes.map((item) => (
                      <li key={item} className="flex items-start gap-1.5 text-[11px] text-slate-400">
                        <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-300" aria-hidden />
                        {item}
                      </li>
                    ))}
                  </ul>
                  <a
                    href="#enquiry"
                    className="mt-4 inline-flex items-center gap-1 text-[11px] font-semibold text-brand-300 hover:text-brand-200"
                  >
                    Enquire about this service <ArrowRight className="h-3 w-3" aria-hidden />
                  </a>
                </GlassCard>
              </Reveal>
            );
          })}
        </div>
        <Reveal>
          <div className="mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-[11.5px] text-slate-400">
            <ClipboardCheck className="h-4 w-4 text-cyan-300" aria-hidden />
            <span>
              Need several services? Select them in the enquiry form — the quotation will list each scope
              line separately so nothing is hidden inside a bundle.
            </span>
          </div>
        </Reveal>
      </Section>

      <Section id="enquiry" className="pb-16 scroll-mt-24">
        <div className="grid gap-6 lg:grid-cols-[1.35fr_0.65fr]">
          <Reveal>
            <GlassCard className="p-6 sm:p-8">
              <SectionHeading
                eyebrow="Request a consultation"
                title="Tell us what needs doing"
                description="The senior accountant reviews the scope and prepares a customised quotation. No engagement, fee or completion date is confirmed until you accept that written quotation."
              />

              {reference ? (
                <div className="mt-6">
                  <div className="rounded-xl border border-emerald-400/25 bg-emerald-500/10 px-4 py-4">
                    <p className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
                      <Check className="h-4 w-4" aria-hidden /> Enquiry received — {reference}
                    </p>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-emerald-100/80">
                      {successMessage}
                    </p>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        setForm(EMPTY_FORM);
                        setReference(null);
                        setSuccessMessage(null);
                      }}
                      className="rounded-xl border border-white/15 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
                    >
                      Submit another enquiry
                    </button>
                    <Link
                      to="/client/login"
                      className="rounded-xl border border-white/15 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
                    >
                      Client portal sign-in
                    </Link>
                  </div>
                </div>
              ) : (
                <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
                  <input
                    type="text"
                    value={form.website}
                    onChange={(event) => update("website", event.target.value)}
                    className="hidden"
                    tabIndex={-1}
                    autoComplete="off"
                    aria-hidden
                  />
                  <div className="grid gap-4 sm:grid-cols-2">
                    <PublicField
                      label="Business name"
                      htmlFor="enq_business"
                      required
                      error={fieldErrors.business_name}
                    >
                      <PublicInput
                        id="enq_business"
                        value={form.business_name}
                        onChange={(event) => update("business_name", event.target.value)}
                        placeholder="Meridian Traders"
                        autoComplete="organization"
                      />
                    </PublicField>
                    <PublicField label="Contact name" htmlFor="enq_name" required error={fieldErrors.contact_name}>
                      <PublicInput
                        id="enq_name"
                        value={form.contact_name}
                        onChange={(event) => update("contact_name", event.target.value)}
                        placeholder="Full name"
                        autoComplete="name"
                      />
                    </PublicField>
                    <PublicField label="Email" htmlFor="enq_email" required error={fieldErrors.email}>
                      <PublicInput
                        id="enq_email"
                        type="email"
                        value={form.email}
                        onChange={(event) => update("email", event.target.value)}
                        placeholder="you@business.com"
                        autoComplete="email"
                      />
                    </PublicField>
                    <PublicField label="Phone" htmlFor="enq_phone" hint="Optional, for scheduling the review call.">
                      <PublicInput
                        id="enq_phone"
                        value={form.phone}
                        onChange={(event) => update("phone", event.target.value)}
                        placeholder="+91…"
                        autoComplete="tel"
                      />
                    </PublicField>
                    <PublicField label="Business type" htmlFor="enq_type" required error={fieldErrors.business_type}>
                      <PublicSelect
                        id="enq_type"
                        value={form.business_type}
                        onChange={(event) => update("business_type", event.target.value)}
                      >
                        {data.business_types.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </PublicSelect>
                    </PublicField>
                    <PublicField
                      label="Annual turnover"
                      htmlFor="enq_turnover"
                      required
                      error={fieldErrors.turnover_range}
                    >
                      <PublicSelect
                        id="enq_turnover"
                        value={form.turnover_range}
                        onChange={(event) => update("turnover_range", event.target.value)}
                      >
                        {data.turnover_ranges.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </PublicSelect>
                    </PublicField>
                    <PublicField
                      label="GST registration"
                      htmlFor="enq_gst"
                      required
                      error={fieldErrors.gst_status}
                    >
                      <PublicSelect
                        id="enq_gst"
                        value={form.gst_status}
                        onChange={(event) => update("gst_status", event.target.value)}
                      >
                        {data.gst_statuses.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </PublicSelect>
                    </PublicField>
                    <PublicField label="Monthly transactions" htmlFor="enq_txns" hint="Approximate count is enough.">
                      <PublicInput
                        id="enq_txns"
                        type="number"
                        min={0}
                        max={1000000}
                        value={form.monthly_transactions}
                        onChange={(event) => update("monthly_transactions", event.target.value)}
                        placeholder="e.g. 120"
                      />
                    </PublicField>
                  </div>

                  <PublicField label="Required services" required error={fieldErrors.services}>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {serviceOptions.map((service) => {
                        const checked = form.services.includes(service.key);
                        return (
                          <button
                            key={service.key}
                            type="button"
                            onClick={() => toggleService(service.key)}
                            className={cn(
                              "flex items-center justify-between gap-2 rounded-xl border px-3 py-2.5 text-left text-[12px] transition",
                              checked
                                ? "border-brand-400/50 bg-brand-500/15 text-white"
                                : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20",
                            )}
                            aria-pressed={checked}
                          >
                            {service.name}
                            <span
                              className={cn(
                                "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                                checked
                                  ? "border-brand-300 bg-brand-400 text-[#04101f]"
                                  : "border-white/20",
                              )}
                              aria-hidden
                            >
                              {checked && <Check className="h-2.5 w-2.5" />}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </PublicField>

                  <PublicField
                    label="Additional requirements"
                    htmlFor="enq_requirements"
                    hint="Current software, backlog, registrations, deadlines or anything the reviewer should know."
                  >
                    <PublicTextarea
                      id="enq_requirements"
                      value={form.requirements}
                      onChange={(event) => update("requirements", event.target.value)}
                      placeholder="We maintain books in Tally, have a GST backlog from September and need monthly MIS…"
                    />
                  </PublicField>

                  <PublicCheckbox
                    checked={form.consent}
                    onChange={(checked) => update("consent", checked)}
                    label={
                      <>
                        I confirm the details are accurate and agree that a senior accountant may contact
                        me about this enquiry. I understand this is not a confirmed engagement or fee.
                      </>
                    }
                  />
                  {fieldErrors.consent && (
                    <p className="text-[11px] font-medium text-rose-300">{fieldErrors.consent}</p>
                  )}

                  {error && (
                    <p className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
                      {error}
                    </p>
                  )}

                  <button
                    type="submit"
                    disabled={submitting}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-3 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {submitting ? "Sending enquiry…" : "Request a consultation"}
                    {!submitting && <ArrowRight className="h-4 w-4" aria-hidden />}
                  </button>
                  <p className="text-center text-[10px] text-slate-500">
                    Enquiries are rate limited and stored only for the practice review. No password or
                    payment-card details are requested here.
                  </p>
                </form>
              )}
            </GlassCard>
          </Reveal>

          <div className="space-y-4">
            <Reveal delay={80}>
              <GlassCard className="p-5">
                <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  <Sparkles className="h-3.5 w-3.5 text-brand-300" aria-hidden /> What happens next
                </p>
                <ul className="mt-3 space-y-2.5">
                  {data.assurances.map((item) => (
                    <li key={item} className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-400">
                      <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" aria-hidden />
                      {item}
                    </li>
                  ))}
                </ul>
              </GlassCard>
            </Reveal>
            <Reveal delay={140}>
              <DisclaimerBox title="Filing boundary">{data.filing_note}</DisclaimerBox>
            </Reveal>
            <Reveal delay={180}>
              <GlassCard className="p-5">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Already a client?
                </p>
                <p className="mt-2 text-[12px] leading-relaxed text-slate-400">
                  Track work, upload documents, review approved reports and see invoices in the client
                  portal.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link
                    to="/client/login"
                    className="rounded-lg border border-white/15 px-3 py-2 text-[11.5px] font-semibold text-slate-200 transition hover:bg-white/5"
                  >
                    Client portal
                  </Link>
                  <Link
                    to="/accountant/login"
                    className="rounded-lg border border-white/15 px-3 py-2 text-[11.5px] font-semibold text-slate-200 transition hover:bg-white/5"
                  >
                    Accountant sign-in
                  </Link>
                </div>
              </GlassCard>
            </Reveal>
            <Reveal delay={220}>
              <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] px-4 py-3 text-[10.5px] leading-relaxed text-slate-500">
                FINOVEXA AI is a software platform. Accounting services are delivered by the practice team
                through this workspace. Statutory filings and tax positions require the engagement of a
                qualified professional and, where applicable, an authorised filing channel.
              </div>
            </Reveal>
          </div>
        </div>
      </Section>
    </div>
  );
}
