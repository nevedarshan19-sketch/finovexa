import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Boxes,
  CreditCard,
  LineChart,
  ReceiptText,
  ShieldCheck,
  Sparkles,
  Target,
} from "lucide-react";
import {
  Eyebrow,
  GlassCard,
  GradientText,
  Pill,
  Reveal,
  Section,
  SectionHeading,
} from "../../components/public/PublicUI";
import { BrandLogo } from "../../components/BrandLogo";

const CAPABILITIES = [
  {
    icon: ReceiptText,
    title: "Accounting & invoices",
    copy: "GST-ready billing, customer records, payment capture and invoice PDFs on a shared ledger.",
  },
  {
    icon: CreditCard,
    title: "Payments",
    copy: "PayPal sandbox integration with server-verified status and invoice reconciliation.",
  },
  {
    icon: Boxes,
    title: "Inventory",
    copy: "Item-level stock movement and the working capital held in inventory.",
  },
  {
    icon: BarChart3,
    title: "Performance",
    copy: "Revenue, margins, receivables and cash-flow views derived from recorded data.",
  },
  {
    icon: Sparkles,
    title: "AI intelligence",
    copy: "Grounded business answers, drafted actions and approval-bound execution.",
  },
  {
    icon: LineChart,
    title: "Market intelligence",
    copy: "NIFTY 50 market data, technical signals and transparent, model-generated research.",
  },
];

const PRINCIPLES = [
  {
    title: "Real records, not theatre",
    copy: "Reports read from the ledger. When a comparison is not meaningful, the figure is omitted instead of invented.",
  },
  {
    title: "Owner authority",
    copy: "The owner approves anything that moves money, sends a message or changes public information.",
  },
  {
    title: "Honest labelling",
    copy: "Demo, sandbox and simulated features are labelled as such. Nothing pretends to be live when it is not.",
  },
  {
    title: "Private by default",
    copy: "Each business's records and documents stay inside that business. No other account can read them.",
  },
];

const ROADMAP = [
  {
    phase: "Available now",
    title: "Owner workspace and demo platform",
    copy: "Dashboard, GST billing, money recovery, cash-flow views, inventory, payments in sandbox and the approval center.",
    tone: "emerald" as const,
  },
  {
    phase: "Available now",
    title: "Market intelligence",
    copy: "NIFTY 50 market data, technical indicators and clearly labelled model-generated research with data provenance.",
    tone: "emerald" as const,
  },
  {
    phase: "Long-term vision",
    title: "Deeper operational intelligence",
    copy: "More connected workflows and explainable analysis across finance, operations and growth — always with human approval.",
    tone: "violet" as const,
  },
];

export function AboutPage() {
  return (
    <div className="pb-8">
      <Section className="pb-14 pt-14 sm:pt-20">
        <div className="grid items-center gap-10 lg:grid-cols-[1.15fr_0.85fr]">
          <Reveal>
            <Eyebrow icon={Target}>About FINOVEXA</Eyebrow>
            <h1 className="mt-5 text-balance text-[38px] font-semibold leading-[1.06] tracking-tight text-white sm:text-[50px]">
              One intelligent platform for the <GradientText>whole business</GradientText>
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-[15px]">
              FINOVEXA AI is a business operations platform. It brings accounting, payments,
              inventory, performance analysis and growth discovery together, so a business can run
              on one set of records instead of stitching together disconnected tools.
            </p>
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">
              The platform is designed for owner-led businesses that want clear numbers, controlled
              automation and market context for the cash they deploy.
            </p>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <Link
                to="/features"
                className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-2.5 text-xs font-semibold text-white transition hover:brightness-110"
              >
                Explore capabilities <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
              <Link
                to="/market-intelligence"
                className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-5 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
              >
                Market intelligence
              </Link>
            </div>
          </Reveal>
          <Reveal delay={120}>
            <GlassCard className="relative overflow-hidden p-7">
              <div
                className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand-500/20 blur-3xl"
                aria-hidden
              />
              <BrandLogo size="lg" subtitle="Business intelligence" />
              <p className="mt-5 text-sm font-medium leading-relaxed text-slate-200">
                Smarter Finance. Stronger Business.
              </p>
              <p className="mt-2 text-[12px] leading-relaxed text-slate-400">
                An AI-assisted operating layer for finance, operations and growth — with the owner in
                control of every consequential action.
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                <Pill tone="blue">
                  <ShieldCheck className="h-3 w-3" aria-hidden /> Human approval
                </Pill>
                <Pill tone="cyan">Traceable records</Pill>
                <Pill tone="violet">Market intelligence</Pill>
              </div>
            </GlassCard>
          </Reveal>
        </div>
      </Section>

      <Section className="pb-16">
        <Reveal>
          <SectionHeading
            eyebrow="What the platform does"
            title={
              <>
                Capabilities that share <GradientText>one source of truth</GradientText>
              </>
            }
            description="Every module below is built on the same business records, so numbers stay consistent wherever they appear."
          />
        </Reveal>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((capability, index) => (
            <Reveal key={capability.title} delay={index * 50}>
              <GlassCard hover className="h-full p-5">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.05] text-brand-200">
                  <capability.icon className="h-4 w-4" aria-hidden />
                </span>
                <p className="mt-3.5 text-sm font-semibold text-white">{capability.title}</p>
                <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-400">{capability.copy}</p>
              </GlassCard>
            </Reveal>
          ))}
        </div>
      </Section>

      <Section className="pb-16">
        <div className="grid gap-8 lg:grid-cols-[1fr_1.1fr]">
          <Reveal>
            <SectionHeading
              eyebrow="How we build"
              title={
                <>
                  Principles over <GradientText>promises</GradientText>
                </>
              }
              description="FINOVEXA avoids invented statistics, guaranteed returns and automation that acts without consent. These principles shape the product."
            />
          </Reveal>
          <Reveal delay={100}>
            <div className="grid gap-3 sm:grid-cols-2">
              {PRINCIPLES.map((principle) => (
                <div key={principle.title} className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <p className="text-xs font-semibold text-white">{principle.title}</p>
                  <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-400">{principle.copy}</p>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </Section>

      <Section className="pb-16">
        <Reveal>
          <GlassCard className="p-6 sm:p-8">
            <SectionHeading
              eyebrow="Direction"
              title="Where the platform is today"
              description="A clear line between what exists and what is planned — no fabricated milestones, customers or partnerships."
            />
            <div className="mt-6 space-y-3">
              {ROADMAP.map((item) => (
                <div
                  key={item.title}
                  className="flex flex-col gap-2 rounded-xl border border-white/[0.08] bg-white/[0.025] p-4 sm:flex-row sm:items-start sm:gap-5"
                >
                  <Pill tone={item.tone} className="w-fit shrink-0">
                    {item.phase}
                  </Pill>
                  <div>
                    <p className="text-sm font-semibold text-white">{item.title}</p>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-slate-400">{item.copy}</p>
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
        </Reveal>
      </Section>

      <Section className="pb-4">
        <Reveal>
          <GlassCard className="flex flex-col items-center gap-4 px-6 py-10 text-center">
            <BrandLogo subtitle="Business intelligence" />
            <h2 className="text-balance text-[24px] font-semibold tracking-tight text-white sm:text-[28px]">
              Build on records you can stand behind.
            </h2>
            <p className="max-w-xl text-sm leading-relaxed text-slate-400">
              Explore the platform with a demo workspace and see how accounting, payments and market
              context connect in one place.
            </p>
            <div className="flex flex-wrap justify-center gap-2.5">
              <Link
                to="/register"
                className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-5 py-2.5 text-xs font-semibold text-white transition hover:brightness-110"
              >
                Get Started <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
              <Link
                to="/contact"
                className="inline-flex items-center rounded-xl border border-white/15 px-5 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
              >
                Contact the team
              </Link>
            </div>
          </GlassCard>
        </Reveal>
      </Section>
    </div>
  );
}
