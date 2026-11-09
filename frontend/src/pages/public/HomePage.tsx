import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Boxes,
  Check,
  CreditCard,
  FileCheck2,
  FileSpreadsheet,
  Landmark,
  LineChart,
  LockKeyhole,
  ReceiptText,
  ScanLine,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Users,
  Wallet,
} from "lucide-react";
import { BrandLogo } from "../../components/BrandLogo";
import {
  Eyebrow,
  GlassCard,
  GradientText,
  Pill,
  Reveal,
  Section,
  SectionHeading,
} from "../../components/public/PublicUI";

const FEATURES = [
  {
    icon: ReceiptText,
    title: "Accounting & GST billing",
    detail:
      "Create tax invoices, record payments and keep a ledger that every report can trace back to.",
    to: "/features#finance",
  },
  {
    icon: CreditCard,
    title: "Payments & reconciliation",
    detail:
      "Connect PayPal in sandbox, match incoming payments and keep settlement status visible.",
    to: "/features#payments",
  },
  {
    icon: Boxes,
    title: "Inventory oversight",
    detail:
      "Track stock movement, low-stock items and the working capital tied up in inventory.",
    to: "/features#operations",
  },
  {
    icon: BarChart3,
    title: "Business performance",
    detail:
      "Revenue, margin, receivables and cash-flow views built from the records you already keep.",
    to: "/features#analytics",
  },
  {
    icon: Sparkles,
    title: "AI business intelligence",
    detail:
      "Ask plain-language questions and get grounded answers that cite your own ledger records.",
    to: "/features#intelligence",
  },
  {
    icon: LineChart,
    title: "NIFTY 50 intelligence",
    detail:
      "Every NIFTY 50 constituent screened with documented rules, source-stated prices and honest no-signal buckets.",
    to: "/features#market-intelligence",
  },
];

const CONTROL_POINTS = [
  "Every action that moves money or sends a message requires explicit owner approval.",
  "AI answers are grounded in your recorded data and separate facts from estimates.",
  "Approvals are hash-bound, audited and visible to the owner.",
  "Employee access is limited to the permissions the owner assigns.",
];

const ACCOUNTING_SERVICES = [
  { icon: BookOpen, name: "Bookkeeping", detail: "Sales, purchase and journal entries kept in double entry." },
  { icon: ReceiptText, name: "GST accounting", detail: "GSTR-1 and GSTR-3B working papers for review." },
  { icon: FileCheck2, name: "ITR filing assistance", detail: "Computation workings prepared for professional review." },
  { icon: Landmark, name: "Bank reconciliation", detail: "Import, suggested matches and unmatched items." },
  { icon: ShoppingCart, name: "Sales & purchase", detail: "Structured registers, GST split and ageing." },
  { icon: Users, name: "Payroll management", detail: "Monthly registers and deduction workings." },
  { icon: BarChart3, name: "Financial statements", detail: "Draft P&L, balance sheet and review notes." },
  { icon: FileSpreadsheet, name: "Tally support", detail: "Validated voucher import and ledger mapping." },
];

function DashboardPreview() {
  return (
    <div className="relative">
      <div
        className="pointer-events-none absolute -inset-6 rounded-[32px] bg-[radial-gradient(ellipse_at_60%_20%,rgba(36,120,240,0.28),transparent_65%)] blur-2xl"
        aria-hidden
      />
      <GlassCard className="relative overflow-hidden p-0">
        <div className="flex items-center gap-2 border-b border-white/[0.07] px-4 py-3">
          <span className="h-2 w-2 rounded-full bg-rose-400/70" aria-hidden />
          <span className="h-2 w-2 rounded-full bg-amber-300/70" aria-hidden />
          <span className="h-2 w-2 rounded-full bg-emerald-300/70" aria-hidden />
          <span className="ml-2 truncate text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
            FINOVEXA workspace · interface preview
          </span>
          <Pill tone="emerald" className="ml-auto">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" aria-hidden /> Sandbox
          </Pill>
        </div>

        <div className="grid grid-cols-[64px_1fr] sm:grid-cols-[86px_1fr]">
          <div className="space-y-2 border-r border-white/[0.06] bg-black/10 p-2.5">
            {[0, 1, 2, 3, 4].map((index) => (
              <div
                key={index}
                className={`flex items-center gap-2 rounded-lg px-1.5 py-1.5 ${
                  index === 0 ? "bg-brand-500/15" : ""
                }`}
              >
                <span
                  className={`h-6 w-6 shrink-0 rounded-md ${
                    index === 0 ? "bg-brand-400/40" : "bg-white/[0.07]"
                  }`}
                  aria-hidden
                />
                <span className="hidden h-1.5 w-7 rounded-full bg-white/10 sm:block" aria-hidden />
              </div>
            ))}
            <div className="mt-6 h-px bg-white/[0.06]" aria-hidden />
            <div className="flex items-center gap-2 rounded-lg px-1.5 py-1.5">
              <span className="h-6 w-6 rounded-md bg-white/[0.07]" aria-hidden />
              <span className="hidden h-1.5 w-6 rounded-full bg-white/10 sm:block" aria-hidden />
            </div>
          </div>

          <div className="p-3.5 sm:p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="h-2 w-24 rounded-full bg-white/15" aria-hidden />
                <div className="mt-1.5 h-1.5 w-36 rounded-full bg-white/[0.07]" aria-hidden />
              </div>
              <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1">
                <Sparkles className="h-3 w-3 text-brand-300" aria-hidden />
                <span className="text-[9px] font-semibold text-slate-300">AI briefing</span>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2">
              <div className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-2">
                <div className="h-1.5 w-10 rounded-full bg-white/10" aria-hidden />
                <div className="mt-2 h-3 w-14 rounded-full bg-brand-300/40" aria-hidden />
                <div className="mt-1 h-1.5 w-8 rounded-full bg-emerald-300/30" aria-hidden />
              </div>
              <div className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-2">
                <div className="h-1.5 w-10 rounded-full bg-white/10" aria-hidden />
                <div className="mt-2 h-3 w-12 rounded-full bg-cyan-300/40" aria-hidden />
                <div className="mt-1 h-1.5 w-8 rounded-full bg-white/10" aria-hidden />
              </div>
              <div className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-2">
                <div className="h-1.5 w-10 rounded-full bg-white/10" aria-hidden />
                <div className="mt-2 h-3 w-12 rounded-full bg-violet-300/40" aria-hidden />
                <div className="mt-1 h-1.5 w-8 rounded-full bg-white/10" aria-hidden />
              </div>
            </div>

            <div className="mt-3 rounded-xl border border-white/[0.08] bg-white/[0.025] p-3">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold text-slate-300">Cash-flow forecast</span>
                <Pill tone="slate">7 · 30 · 90 days</Pill>
              </div>
              <svg viewBox="0 0 320 92" className="mt-2 h-20 w-full" role="img" aria-label="Illustrative cash-flow chart shape">
                <defs>
                  <linearGradient id="hero-line" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#4d94ff" stopOpacity="0.45" />
                    <stop offset="100%" stopColor="#4d94ff" stopOpacity="0" />
                  </linearGradient>
                </defs>
                {[18, 42, 66].map((y) => (
                  <line key={y} x1="0" y1={y} x2="320" y2={y} stroke="rgba(148,163,184,0.12)" strokeWidth="1" />
                ))}
                <path
                  d="M0 70 C 26 66, 40 52, 62 55 S 104 72, 128 58 S 172 28, 196 36 S 238 58, 260 44 S 296 22, 320 26 L 320 92 L 0 92 Z"
                  fill="url(#hero-line)"
                />
                <path
                  d="M0 70 C 26 66, 40 52, 62 55 S 104 72, 128 58 S 172 28, 196 36 S 238 58, 260 44 S 296 22, 320 26"
                  fill="none"
                  stroke="#4d94ff"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] p-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-emerald-500/15 text-emerald-300">
                  <FileCheck2 className="h-3.5 w-3.5" aria-hidden />
                </span>
                <div className="min-w-0">
                  <div className="h-1.5 w-16 rounded-full bg-white/10" aria-hidden />
                  <div className="mt-1 h-1.5 w-10 rounded-full bg-white/[0.07]" aria-hidden />
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] p-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-amber-500/15 text-amber-300">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                </span>
                <div className="min-w-0">
                  <div className="h-1.5 w-20 rounded-full bg-white/10" aria-hidden />
                  <div className="mt-1 h-1.5 w-12 rounded-full bg-white/[0.07]" aria-hidden />
                </div>
              </div>
            </div>
          </div>
        </div>
      </GlassCard>
      <p className="mt-3 text-center text-[10px] text-slate-600">
        Interface preview only. A live workspace shows your own recorded figures.
      </p>
    </div>
  );
}

export function HomePage() {
  return (
    <div className="pb-8">
      <Section className="pb-14 pt-12 sm:pt-16 lg:pb-24 lg:pt-20">
        <div className="grid items-center gap-12 lg:grid-cols-[1.02fr_1fr] lg:gap-10">
          <Reveal>
            <Eyebrow>Intelligent business platform</Eyebrow>
            <h1 className="mt-5 text-balance text-[44px] font-semibold leading-[1.02] tracking-tight text-white sm:text-[58px] lg:text-[62px]">
              FINOVEXA <GradientText>AI</GradientText>
            </h1>
            <p className="mt-4 text-balance text-[24px] font-medium tracking-tight text-slate-200 sm:text-[30px]">
              Smarter Finance. <GradientText>Stronger Business.</GradientText>
            </p>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-slate-400 sm:text-[15px]">
              Automate accounting, manage payments, track inventory, understand your business
              performance and discover growth opportunities with intelligent business tools.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Link
                to="/features"
                className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb_0%,#2f86f6_55%,#0ea5b7_100%)] px-5 py-3 text-[13px] font-semibold text-white shadow-[0_18px_40px_-18px_rgba(36,120,240,0.95)] transition hover:brightness-110"
              >
                Explore FINOVEXA AI <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
              <Link
                to="/market-intelligence"
                className="inline-flex items-center gap-2 rounded-xl border border-white/15 bg-white/[0.04] px-5 py-3 text-[13px] font-semibold text-slate-200 transition hover:border-brand-300/40 hover:bg-white/[0.07] hover:text-white"
              >
                Explore Market Intelligence <LineChart className="h-4 w-4 text-brand-300" aria-hidden />
              </Link>
            </div>
            <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <LockKeyhole className="h-3.5 w-3.5 text-emerald-300" aria-hidden /> Owner-approved actions
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ScanLine className="h-3.5 w-3.5 text-cyan-300" aria-hidden /> Traceable records
              </span>
              <span className="inline-flex items-center gap-1.5">
                <CreditCard className="h-3.5 w-3.5 text-brand-300" aria-hidden /> PayPal Sandbox
              </span>
            </div>
          </Reveal>

          <Reveal delay={120}>
            <DashboardPreview />
          </Reveal>
        </div>
      </Section>

      <Section className="pb-16">
        <Reveal>
          <SectionHeading
            eyebrow="One workspace"
            title={
              <>
                Finance, operations and growth <GradientText>on one platform</GradientText>
              </>
            }
            description="Each module writes to the same ledger, so the numbers you see are the records you keep — not a separate reporting layer."
          />
        </Reveal>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature, index) => (
            <Reveal key={feature.title} delay={index * 60}>
              <Link to={feature.to} className="block h-full">
                <GlassCard hover className="flex h-full flex-col p-5">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-[linear-gradient(140deg,rgba(36,120,240,0.25),rgba(14,165,183,0.12))] text-brand-200">
                    <feature.icon className="h-4 w-4" aria-hidden />
                  </span>
                  <h3 className="mt-4 text-sm font-semibold text-white">{feature.title}</h3>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-400">{feature.detail}</p>
                  <span className="mt-4 inline-flex items-center gap-1 text-[11px] font-semibold text-brand-300">
                    Learn more <ArrowRight className="h-3 w-3" aria-hidden />
                  </span>
                </GlassCard>
              </Link>
            </Reveal>
          ))}
        </div>
      </Section>

      <Section id="accounting" className="pb-16 scroll-mt-20">
        <Reveal>
          <GlassCard className="overflow-hidden p-0">
            <div className="grid gap-0 lg:grid-cols-[0.92fr_1.08fr]">
              <div className="p-7 sm:p-10">
                <Eyebrow icon={ShieldCheck}>Professional accounting services</Eyebrow>
                <h2 className="mt-4 text-balance text-[28px] font-semibold leading-tight tracking-tight text-white sm:text-[34px]">
                  A managed practice for the books behind the dashboard.
                </h2>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">
                  Bookkeeping, GST working papers, ITR assistance, reconciliation, payroll and financial
                  statements — researched by a junior accountant, reviewed by a senior, and delivered
                  through a client portal. Every engagement is scoped and quoted after review.
                </p>
                <ul className="mt-5 space-y-2.5 text-[12.5px] text-slate-300">
                  {[
                    "Senior review before anything reaches you or a statutory channel.",
                    "Your business records are isolated from every other client.",
                    "AI drafts and suggests; an accountant confirms before saving.",
                  ].map((item) => (
                    <li key={item} className="flex items-start gap-2">
                      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
                        <Check className="h-2.5 w-2.5" aria-hidden />
                      </span>
                      {item}
                    </li>
                  ))}
                </ul>
                <div className="mt-6 flex flex-wrap gap-2.5">
                  <Link
                    to="/accounting"
                    className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2.5 text-xs font-semibold text-white transition hover:brightness-110"
                  >
                    Explore Services <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                  <Link
                    to="/accounting#enquiry"
                    className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
                  >
                    Request a Consultation
                  </Link>
                </div>
                <p className="mt-4 text-[10.5px] leading-relaxed text-slate-500">
                  No fixed fee is published online. Returns are prepared as working papers; filing needs an
                  authorised channel and professional sign-off.
                </p>
              </div>
              <div className="relative border-t border-white/[0.07] p-6 sm:p-8 lg:border-l lg:border-t-0">
                <div
                  className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_70%_10%,rgba(14,165,183,0.14),transparent_60%)]"
                  aria-hidden
                />
                <div className="relative grid gap-3 sm:grid-cols-2">
                  {ACCOUNTING_SERVICES.map((service) => (
                    <div
                      key={service.name}
                      className="rounded-xl border border-white/[0.08] bg-white/[0.035] p-3.5"
                    >
                      <service.icon className="h-4 w-4 text-cyan-300" aria-hidden />
                      <p className="mt-2 text-[12px] font-semibold text-white">{service.name}</p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{service.detail}</p>
                    </div>
                  ))}
                </div>
                <div className="relative mt-4 flex flex-wrap items-center gap-2 text-[10.5px] text-slate-500">
                  <Link to="/client/login" className="font-semibold text-slate-400 transition hover:text-white">
                    Client portal
                  </Link>
                  <span className="text-slate-700">·</span>
                  <Link
                    to="/accountant/login"
                    className="font-semibold text-slate-400 transition hover:text-white"
                  >
                    Accountant sign-in
                  </Link>
                </div>
              </div>
            </div>
          </GlassCard>
        </Reveal>
      </Section>

      <Section id="market-intelligence" className="pb-16 scroll-mt-20">
        <Reveal>
          <GlassCard className="overflow-hidden p-0">
            <div className="grid gap-0 lg:grid-cols-[1.15fr_1fr]">
              <div className="p-7 sm:p-10">
                <Eyebrow icon={LineChart}>Market intelligence</Eyebrow>
                <h2 className="mt-4 text-balance text-[28px] font-semibold leading-tight tracking-tight text-white sm:text-[34px]">
                  NIFTY 50 recommendations, shown with their reasoning.
                </h2>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">
                  All 50 NSE NIFTY 50 constituents are screened on the same documented rules. Stocks that
                  clear the positive-upside threshold appear with targets, horizons and confidence; the rest
                  are listed separately instead of being forced into a buy call.
                </p>
                <ul className="mt-5 space-y-2.5 text-[12.5px] text-slate-300">
                  {[
                    "Latest price, market-data timestamp and data source appear on every card.",
                    "Targets and upside are model estimates, never analyst facts or guaranteed returns.",
                    "Missing or stale data is labelled; nothing is back-filled with invented prices.",
                  ].map((item) => (
                    <li key={item} className="flex items-start gap-2">
                      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
                        <Check className="h-2.5 w-2.5" aria-hidden />
                      </span>
                      {item}
                    </li>
                  ))}
                </ul>
                <div className="mt-6 flex flex-wrap gap-2.5">
                  <Link
                    to="/market-intelligence"
                    className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2.5 text-xs font-semibold text-white transition hover:brightness-110"
                  >
                    Open Market Intelligence <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                  <Link
                    to="/market-intelligence#methodology"
                    className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
                  >
                    See the methodology
                  </Link>
                </div>
              </div>
              <div className="relative border-t border-white/[0.07] p-7 sm:p-10 lg:border-l lg:border-t-0">
                <div
                  className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_70%_20%,rgba(124,58,237,0.18),transparent_60%)]"
                  aria-hidden
                />
                <div className="relative space-y-3">
                  {[
                    { icon: LineChart, title: "Full 50-stock coverage", copy: "Screened in one pass, not a hand-picked watchlist." },
                    { icon: ScanLine, title: "Stated methodology", copy: "The target, horizon and confidence rules are documented." },
                    { icon: ShieldCheck, title: "No fabricated signals", copy: "Unavailable inputs are shown as unavailable, not guessed." },
                  ].map((item) => (
                    <div
                      key={item.title}
                      className="flex items-start gap-3 rounded-xl border border-white/[0.08] bg-white/[0.035] p-3.5"
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.06] text-brand-200">
                        <item.icon className="h-4 w-4" aria-hidden />
                      </span>
                      <div>
                        <p className="text-xs font-semibold text-white">{item.title}</p>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{item.copy}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="relative mt-5 rounded-xl border border-amber-400/20 bg-amber-400/[0.05] px-3.5 py-3 text-[10.5px] leading-relaxed text-amber-100/80">
                  Recommendations are informational only and are not investment advice. Model estimates can
                  be wrong and historical performance does not guarantee future results.
                </div>
              </div>
            </div>
          </GlassCard>
        </Reveal>
      </Section>

      <Section className="pb-16">
        <Reveal>
          <GlassCard className="px-6 py-10 sm:px-10">
            <div className="mx-auto max-w-3xl text-center">
              <h2 className="text-[26px] font-semibold tracking-tight text-white sm:text-[32px]">
                Trusted by Businesses
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-slate-400">
                Designed to help businesses manage finances, operations, payments and growth from one
                intelligent platform.
              </p>
            </div>
            <div className="mt-8 grid gap-4 sm:grid-cols-3">
              {[
                {
                  icon: ShieldCheck,
                  title: "Owner control",
                  copy: "The business owner decides what is public, what is private and what gets approved.",
                },
                {
                  icon: ScanLine,
                  title: "Traceable records",
                  copy: "Figures are drawn from the workspace ledger, with period and source stated.",
                },
                {
                  icon: LockKeyhole,
                  title: "Clear boundaries",
                  copy: "Simulated and sandbox features are labelled. Nothing claims to be live when it is not.",
                },
              ].map((item) => (
                <div key={item.title} className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
                  <item.icon className="h-4 w-4 text-brand-300" aria-hidden />
                  <p className="mt-2.5 text-xs font-semibold text-white">{item.title}</p>
                  <p className="mt-1 text-[11.5px] leading-relaxed text-slate-400">{item.copy}</p>
                </div>
              ))}
            </div>
          </GlassCard>
        </Reveal>
      </Section>

      <Section className="pb-16">
        <div className="grid items-center gap-8 lg:grid-cols-2">
          <Reveal>
            <SectionHeading
              eyebrow="Responsible by design"
              title={
                <>
                  AI suggests. <GradientText>You decide.</GradientText>
                </>
              }
              description="FINOVEXA is built around human approval. The assistant can draft, analyse and explain — it cannot move money, send external messages or act on its own."
            />
          </Reveal>
          <Reveal delay={100}>
            <div className="space-y-3">
              {CONTROL_POINTS.map((point) => (
                <div
                  key={point}
                  className="flex items-start gap-3 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3"
                >
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
                    <Check className="h-3 w-3" aria-hidden />
                  </span>
                  <p className="text-[12.5px] leading-relaxed text-slate-300">{point}</p>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </Section>

      <Section className="pb-4">
        <Reveal>
          <div className="relative overflow-hidden rounded-3xl border border-brand-400/20 bg-[linear-gradient(135deg,rgba(36,120,240,0.16),rgba(124,58,237,0.12)_55%,rgba(14,165,183,0.12))] px-6 py-10 text-center sm:px-12">
            <div
              className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[36rem] -translate-x-1/2 rounded-full bg-brand-500/20 blur-3xl"
              aria-hidden
            />
            <div className="relative">
              <BrandLogo size="lg" subtitle="Business intelligence" className="justify-center" />
              <h2 className="mt-5 text-balance text-[26px] font-semibold tracking-tight text-white sm:text-[32px]">
                Run your business with clarity and research your market with evidence.
              </h2>
              <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-slate-300">
                Start with the demo workspace, explore the platform, then open Market Intelligence to see
                the full NIFTY 50 screen with its data provenance.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-3">
                <Link
                  to="/register"
                  className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-[13px] font-semibold text-[#071120] shadow-lg shadow-black/30 transition hover:bg-slate-100"
                >
                  Get Started <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
                <Link
                  to="/market-intelligence"
                  className="inline-flex items-center gap-2 rounded-xl border border-white/20 bg-white/[0.06] px-5 py-3 text-[13px] font-semibold text-white transition hover:bg-white/[0.1]"
                >
                  Market Intelligence
                </Link>
              </div>
              <p className="mt-4 inline-flex items-center gap-1.5 text-[10.5px] text-slate-400">
                <Wallet className="h-3 w-3" aria-hidden /> Demo account, sandbox payments. No card
                details are stored or charged.
              </p>
            </div>
          </div>
        </Reveal>
      </Section>
    </div>
  );
}
