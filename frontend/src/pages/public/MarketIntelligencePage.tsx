import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Clock3,
  Database,
  LineChart,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import {
  DisclaimerBox,
  Eyebrow,
  GradientText,
  Pill,
  Reveal,
  Section,
} from "../../components/public/PublicUI";
import { NiftyRecommendations } from "../../components/NiftyRecommendations";
import { useAuth } from "../../context/AuthContext";

const PRINCIPLES = [
  {
    icon: BarChart3,
    title: "All 50 constituents screened",
    copy: "The list is refreshed from NSE's published NIFTY 50 constituent file, then every stock is analysed on the same documented rules — not a hand-picked watchlist.",
  },
  {
    icon: Clock3,
    title: "Timestamps and sources kept",
    copy: "Every card states the market price, when that price was observed, its provider and whether the data is delayed or stale.",
  },
  {
    icon: Database,
    title: "Missing data stays missing",
    copy: "A stock without a verified price or enough history is placed in an insufficient-data bucket. No target, upside or confidence is invented.",
  },
  {
    icon: ShieldCheck,
    title: "No buy ratings",
    copy: "Upside alone never produces a “Strong Buy”. Targets and confidence are model estimates, clearly separated from observed prices.",
  },
];

export function MarketIntelligencePage() {
  const { user } = useAuth();

  return (
    <div className="pb-16">
      <Section className="pt-14 sm:pt-20">
        <Reveal>
          <div className="flex flex-wrap items-center gap-2">
            <Eyebrow icon={LineChart}>Market intelligence</Eyebrow>
            <Pill tone="amber">
              <ShieldAlert className="h-3 w-3" aria-hidden /> Informational only
            </Pill>
          </div>
          <h1 className="mt-5 max-w-3xl text-balance text-[34px] font-semibold leading-[1.05] tracking-tight text-white sm:text-[46px]">
            NIFTY 50 recommendations, <GradientText>with the reasoning attached.</GradientText>
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-[15px]">
            Every NSE NIFTY 50 constituent is screened in one pass using a documented technical model.
            Stocks that clear the positive-upside threshold are shown with a target, horizon, confidence
            and the indicators behind them. The rest are listed separately instead of being presented as
            buys.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Pill tone="emerald">50 of 50 screened</Pill>
            <Pill tone="slate">Delayed data labelled</Pill>
            <Pill tone="slate">Formula-based upside</Pill>
            <Pill tone="slate">Risks on every card</Pill>
          </div>
        </Reveal>
      </Section>

      <Section className="mt-10 sm:mt-14">
        <Reveal delay={80}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {PRINCIPLES.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-white/[0.08] bg-white/[0.035] p-4"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.06] text-brand-200">
                  <item.icon className="h-4 w-4" aria-hidden />
                </span>
                <p className="mt-3 text-xs font-semibold text-white">{item.title}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{item.copy}</p>
              </div>
            ))}
          </div>
        </Reveal>
      </Section>

      <Section className="mt-10 sm:mt-12">
        <div className="rounded-3xl border border-white/10 bg-white p-3 text-ink-900 shadow-[0_40px_120px_-60px_rgba(0,0,0,0.9)] sm:p-6">
          <NiftyRecommendations />
        </div>
        <p className="mt-4 text-[10.5px] leading-relaxed text-slate-500">
          Prices and history are supplied by a keyless market-data source and may be delayed. The
          recommendation model uses price history only; no licensed fundamental feed is configured, so
          fundamentals are marked unavailable rather than estimated.{" "}
          <a href="#methodology" className="font-semibold text-brand-300 hover:text-brand-200">
            Read the methodology
          </a>
          .
        </p>
      </Section>

      <Section className="mt-10 sm:mt-12">
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <Reveal>
            <div className="h-full rounded-2xl border border-white/[0.08] bg-white/[0.035] p-6 sm:p-7">
              <h2 className="text-lg font-semibold tracking-tight text-white">
                What this screen is — and is not
              </h2>
              <ul className="mt-4 space-y-2.5 text-[12.5px] leading-relaxed text-slate-400">
                <li>
                  <strong className="font-semibold text-slate-200">Observed facts:</strong> the latest
                  reported price, its timestamp and the provider that supplied it.
                </li>
                <li>
                  <strong className="font-semibold text-slate-200">Model estimates:</strong> the target
                  price, expected upside and technical confidence, produced by stated formulas.
                </li>
                <li>
                  <strong className="font-semibold text-slate-200">Not included:</strong> licensed analyst
                  ratings, broker research or fundamental forecasts. FINOVEXA does not fabricate them.
                </li>
              </ul>
              <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
                Use the horizon, minimum-upside, confidence and search controls to inspect every stock's
                reasoning. A qualifying signal means the model's estimated target is above the current
                price by the chosen threshold — nothing more.
              </p>
            </div>
          </Reveal>
          <Reveal delay={80}>
            <div className="space-y-3">
              <DisclaimerBox title="Not investment advice">
                Recommendations are informational only. Model estimates can be wrong, market data can be
                delayed, and historical performance does not guarantee future results. Nothing on this page
                is a solicitation to buy or sell a security.
              </DisclaimerBox>
              <div className="rounded-2xl border border-white/[0.08] bg-white/[0.035] p-5">
                <p className="text-xs font-semibold text-white">
                  {user ? "Continue in your workspace" : "Explore beyond the screen"}
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                  {user
                    ? "Open Market Intelligence in your dashboard for charts, news and the full research workspace."
                    : "Create a free demo account to see the business workspace, or keep browsing the market screen."}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link
                    to={user ? "/markets" : "/register"}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-3.5 py-2 text-xs font-semibold text-white transition hover:brightness-110"
                  >
                    {user ? "Open dashboard" : "Create demo account"}
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                  <Link
                    to="/features"
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/15 px-3.5 py-2 text-xs font-semibold text-slate-200 transition hover:bg-white/5"
                  >
                    Platform features
                  </Link>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </Section>
    </div>
  );
}
