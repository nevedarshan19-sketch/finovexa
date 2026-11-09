import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Boxes,
  Check,
  CreditCard,
  FileText,
  HandCoins,
  LineChart,
  LockKeyhole,
  ReceiptText,
  ShieldCheck,
  Sparkles,
  Users,
  Waves,
} from "lucide-react";
import {
  DisclaimerBox,
  Eyebrow,
  GlassCard,
  GradientText,
  Pill,
  Reveal,
  Section,
  SectionHeading,
} from "../../components/public/PublicUI";

const MODULES = [
  {
    id: "finance",
    icon: ReceiptText,
    eyebrow: "Accounting",
    title: "GST-ready billing that stays connected",
    detail:
      "Raise tax invoices, record payments and keep customer, tax and payment data linked. Every invoice can be exported as a PDF and every change is written to an audit trail.",
    points: [
      "Tax invoices with GST breakdowns and invoice numbering",
      "Customer ledger, payment recording and invoice PDFs",
      "Deadline-based reminder ladders for overdue dues",
      "Owner and employee entries reconciled in one place",
    ],
  },
  {
    id: "payments",
    icon: CreditCard,
    eyebrow: "Payments",
    title: "PayPal in sandbox, clearly labelled",
    detail:
      "Connect PayPal with sandbox credentials during development. Payment status is verified server-side, matched against invoices and never taken from a client-side success message.",
    points: [
      "Sandbox checkout and verified webhook handling",
      "Reconciliation against invoices and customer records",
      "No raw card details are stored anywhere in FINOVEXA",
      "Live mode stays off until explicitly enabled and configured",
    ],
    badge: "Sandbox",
  },
  {
    id: "operations",
    icon: Boxes,
    eyebrow: "Operations",
    title: "Inventory and working capital together",
    detail:
      "Track stock movement and low-stock positions, then see the capital tied up in inventory alongside receivables and cash.",
    points: [
      "Item-level stock tracking with movement history",
      "Low-stock visibility inside the business briefing",
      "Inventory value reflected in working-capital views",
      "Owner approvals for changes that affect the ledger",
    ],
  },
  {
    id: "analytics",
    icon: BarChart3,
    eyebrow: "Analytics",
    title: "Performance from your recorded data",
    detail:
      "Revenue, margins, receivables and cash-flow forecasts are calculated from invoices and payments already in the workspace. Percentages are omitted when the comparison base is not meaningful.",
    points: [
      "7, 30 and 90-day cash-flow views with reserve floors",
      "Revenue, margin and receivables trends",
      "Historical figures separated from estimates",
      "No projected returns or fabricated benchmarks",
    ],
  },
  {
    id: "intelligence",
    icon: Sparkles,
    eyebrow: "AI intelligence",
    title: "Grounded answers with a human in the loop",
    detail:
      "Ask business questions in plain language. The assistant retrieves your records, cites them and drafts actions — but never executes a side effect without explicit owner approval.",
    points: [
      "Answers grounded in the owner's ledger and records",
      "Facts, estimates and assumptions labelled separately",
      "Drafted reminders and interventions wait for approval",
      "External content treated as untrusted data, never instructions",
    ],
  },
  {
    id: "governance",
    icon: Users,
    eyebrow: "Governance",
    title: "Roles that are enforced by the server",
    detail:
      "Owner, employee and developer access is enforced in backend APIs and database queries, not only in the interface. Employees see only what the owner allocates.",
    points: [
      "Owner-only access to cash, approvals, payments and reports",
      "Employee permissions scoped to assigned workflows",
      "Developer role provisioned server-side, never self-registered",
      "Immutable audit trail for sensitive actions",
    ],
  },
];

const MARKET_POINTS = [
  "All 50 NIFTY 50 constituents analysed, not a hand-picked shortlist.",
  "Prices, targets and confidence come with data source, timestamp and freshness labels.",
  "Stocks without a positive upside signal stay visible in a separate list.",
  "Documented target-price and confidence rules that can be inspected for every stock.",
  "No fabricated prices, ratings or fundamentals. Missing data is stated, never invented.",
];

export function FeaturesPage() {
  return (
    <div className="pb-8">
      <Section className="pb-12 pt-14 sm:pt-20">
        <Reveal>
          <div className="max-w-3xl">
            <Eyebrow>Platform capabilities</Eyebrow>
            <h1 className="mt-5 text-balance text-[38px] font-semibold leading-[1.06] tracking-tight text-white sm:text-[50px]">
              Everything the business needs, <GradientText>connected by design</GradientText>
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-[15px]">
              FINOVEXA brings finance, operations, payments, intelligence and growth discovery into a
              single owner-controlled workspace. Each module is built on the same recorded data.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link
                to="/register"
                className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-2.5 text-xs font-semibold text-white transition hover:brightness-110"
              >
                Get Started <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
              <Link
                to="/pricing"
                className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-5 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
              >
                View pricing
              </Link>
            </div>
            <div className="mt-6 flex flex-wrap gap-2">
              {MODULES.map((module) => (
                <a
                  key={module.id}
                  href={`#${module.id}`}
                  className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] text-slate-400 transition hover:border-brand-400/30 hover:text-white"
                >
                  {module.eyebrow}
                </a>
              ))}
              <a
                href="#market-intelligence"
                className="rounded-full border border-violet-400/25 bg-violet-500/10 px-3 py-1 text-[11px] text-violet-200 transition hover:bg-violet-500/15"
              >
                Market Intelligence
              </a>
            </div>
          </div>
        </Reveal>
      </Section>

      <Section className="space-y-5 pb-16">
        {MODULES.map((module, index) => (
          <Reveal key={module.id} delay={index * 40}>
            <GlassCard id={module.id} className="scroll-mt-24 p-6 sm:p-8">
              <div className="grid gap-6 lg:grid-cols-[0.9fr_1.4fr] lg:gap-10">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-[linear-gradient(140deg,rgba(36,120,240,0.25),rgba(14,165,183,0.12))] text-brand-200">
                      <module.icon className="h-4 w-4" aria-hidden />
                    </span>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-300">
                      {module.eyebrow}
                    </p>
                    {module.badge && <Pill tone="emerald">{module.badge}</Pill>}
                  </div>
                  <h2 className="mt-4 text-[22px] font-semibold leading-tight tracking-tight text-white">
                    {module.title}
                  </h2>
                  <p className="mt-2.5 text-[12.5px] leading-relaxed text-slate-400">{module.detail}</p>
                </div>
                <ul className="grid gap-2.5 self-center sm:grid-cols-2">
                  {module.points.map((point) => (
                    <li
                      key={point}
                      className="flex items-start gap-2 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2.5 text-[11.5px] leading-relaxed text-slate-300"
                    >
                      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
                        <Check className="h-2.5 w-2.5" aria-hidden />
                      </span>
                      {point}
                    </li>
                  ))}
                </ul>
              </div>
            </GlassCard>
          </Reveal>
        ))}
      </Section>

      <Section id="market-intelligence" className="scroll-mt-24 pb-16">
        <Reveal>
          <GlassCard className="overflow-hidden p-0">
            <div className="grid lg:grid-cols-[1.2fr_1fr]">
              <div className="p-7 sm:p-10">
                <Eyebrow icon={LineChart}>Market Intelligence</Eyebrow>
                <h2 className="mt-4 text-balance text-[26px] font-semibold leading-tight tracking-tight text-white sm:text-[32px]">
                  NIFTY 50 recommendations with the working shown
                </h2>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">
                  Every NIFTY 50 constituent is analysed with a documented technical model. Qualifying
                  stocks appear as recommendation cards with target price, upside, horizon, confidence,
                  indicators, risks and data provenance. The rest remain visible without a signal.
                </p>
                <div className="mt-6 flex flex-wrap gap-2.5">
                  <Link
                    to="/market-intelligence"
                    className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2.5 text-xs font-semibold text-white transition hover:brightness-110"
                  >
                    Explore Market Intelligence <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                  <Link
                    to="/market-intelligence#methodology"
                    className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
                  >
                    Read the methodology
                  </Link>
                </div>
              </div>
              <div className="border-t border-white/[0.08] p-7 sm:p-10 lg:border-l lg:border-t-0">
                <ul className="space-y-3">
                  {MARKET_POINTS.map((point) => (
                    <li key={point} className="flex items-start gap-2.5 text-[12px] leading-relaxed text-slate-300">
                      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" aria-hidden />
                      {point}
                    </li>
                  ))}
                </ul>
                <DisclaimerBox className="mt-5" title="Informational only">
                  Recommendations are informational, not investment advice. Model estimates are
                  separated from historical data. Losses are possible.
                </DisclaimerBox>
              </div>
            </div>
          </GlassCard>
        </Reveal>
      </Section>

      <Section className="pb-16">
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            {
              icon: HandCoins,
              title: "Money recovery",
              copy: "Ranked overdue invoices and reminder drafts, sent only after approval.",
              to: "/features#finance",
            },
            {
              icon: Waves,
              title: "Cash-flow planning",
              copy: "Forecast views with reserve floors, built from recorded due dates.",
              to: "/features#analytics",
            },
            {
              icon: FileText,
              title: "Audit trail",
              copy: "Sensitive actions recorded with actor, time and entity details.",
              to: "/features#governance",
            },
          ].map((item) => (
            <Reveal key={item.title}>
              <Link to={item.to} className="block h-full">
                <GlassCard hover className="h-full p-5">
                  <item.icon className="h-4 w-4 text-brand-300" aria-hidden />
                  <p className="mt-3 text-sm font-semibold text-white">{item.title}</p>
                  <p className="mt-1 text-[11.5px] leading-relaxed text-slate-400">{item.copy}</p>
                </GlassCard>
              </Link>
            </Reveal>
          ))}
        </div>
      </Section>

      <Section className="pb-4">
        <GlassCard className="flex flex-col items-center gap-4 px-6 py-9 text-center">
          <LockKeyhole className="h-5 w-5 text-emerald-300" aria-hidden />
          <SectionHeading
            align="center"
            title="See it with your own data"
            description="Create a demo owner account, explore the workspace and review market intelligence in context."
          />
          <Link
            to="/register"
            className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-2.5 text-xs font-semibold text-white transition hover:brightness-110"
          >
            Get Started <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
        </GlassCard>
      </Section>
    </div>
  );
}
