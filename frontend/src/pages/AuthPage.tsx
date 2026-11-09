import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  BadgeCheck,
  Eye,
  EyeOff,
  HandCoins,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  Waves,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { getErrorMessage } from "../lib/api";
import { Button, Callout, Field, Input, Select } from "../components/ui";
import { BrandHero, BrandLogo } from "../components/BrandLogo";

const FEATURES = [
  {
    icon: HandCoins,
    title: "Recover cash faster",
    detail: "Ranked overdue invoices, reminder drafts and reconciliation in one queue.",
  },
  {
    icon: Waves,
    title: "See cash before it moves",
    detail: "7, 30 and 90-day forecasts with reserve floors and scenario comparisons.",
  },
  {
    icon: Sparkles,
    title: "Ask grounded questions",
    detail: "Answers cite your ledger records and separate facts from estimates.",
  },
  {
    icon: ShieldCheck,
    title: "Approve every side effect",
    detail: "Reminders, orders and interventions are hash-bound and human-approved.",
  },
];

function BrandMark() {
  return <BrandLogo subtitle="Business operations" />;
}

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const afterAuth = () => {
    const state = location.state as { from?: string } | null;
    const target = state?.from?.startsWith("/employee") ? "/" : state?.from;
    navigate(target || "/", { replace: true });
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email.trim(), password);
      } else {
        if (password.length < 8 || !/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
          throw new Error("Use at least 8 characters, including a letter and a number.");
        }
        await register({
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          business_name: businessName.trim(),
          currency,
        });
      }
      afterAuth();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-slate-50">
      <div className="relative hidden w-[52%] flex-col overflow-hidden bg-gradient-to-br from-navy-950 via-navy-900 to-[#0d1f3c] px-10 py-9 lg:flex xl:px-14">
        <div
          className="pointer-events-none absolute -right-28 -top-28 h-[420px] w-[420px] rounded-full bg-brand-500/15 blur-3xl"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute -bottom-24 left-10 h-[340px] w-[340px] rounded-full bg-teal-500/10 blur-3xl"
          aria-hidden
        />
        <div className="relative">
          <BrandHero className="w-44" />
        </div>

        <div className="relative my-auto max-w-lg py-10">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-200">
            <Sparkles className="h-3 w-3" /> Autonomous business manager
          </p>
          <h1 className="text-balance text-[38px] font-semibold leading-[1.12] tracking-tight text-white xl:text-[44px]">
            Run the business.
            <br />
            <span className="bg-gradient-to-r from-brand-300 via-cyan-300 to-teal-300 bg-clip-text text-transparent">
              Let FINOVEXA handle the money.
            </span>
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-slate-400">
            One operating system for receivables, cash forecasts, market context and approvals — every
            number traceable, every action authorized by you.
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {FEATURES.map((feature) => (
              <div
                key={feature.title}
                className="rounded-xl border border-white/[0.07] bg-white/[0.035] p-3.5 transition hover:border-white/[0.14] hover:bg-white/[0.05]"
              >
                <feature.icon className="h-4 w-4 text-brand-300" aria-hidden />
                <p className="mt-2 text-[12px] font-semibold text-slate-100">{feature.title}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{feature.detail}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-xl border border-white/[0.08] bg-navy-950/60 p-4 backdrop-blur">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Seeded demo snapshot
              </p>
              <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-0.5 text-[9px] font-semibold text-slate-400">
                DEMO
              </span>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-3">
              {[
                { label: "Recorded cash", value: "₹4.09L", tone: "text-white" },
                { label: "Overdue", value: "₹7.82L", tone: "text-amber-300" },
                { label: "Awaiting approval", value: "3", tone: "text-brand-300" },
              ].map((metric) => (
                <div key={metric.label}>
                  <p className={`text-lg font-semibold tracking-tight ${metric.tone}`}>{metric.value}</p>
                  <p className="mt-0.5 text-[9px] uppercase tracking-wide text-slate-500">{metric.label}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 flex items-center gap-1.5 text-[9px] text-slate-500">
              <BadgeCheck className="h-3 w-3" /> Illustration of seeded demo records. Not live data.
            </p>
          </div>
        </div>

        <p className="relative text-[10px] tracking-wide text-slate-600">
          Owner-approved orders · Live only when enabled · Demo values always labelled
        </p>
      </div>

      <div className="flex w-full flex-col px-5 py-6 sm:px-8 lg:w-[48%] lg:px-12 xl:px-20">
        <div className="flex items-center justify-between lg:hidden">
          <div className="rounded-xl bg-navy-950 px-3 py-2">
            <BrandMark />
          </div>
        </div>

        <div className="my-auto w-full max-w-md self-center py-10">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-brand-600">
            {mode === "login" ? "Welcome back" : "Create your workspace"}
          </p>
          <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink-900">
            {mode === "login" ? "Sign in to FINOVEXA" : "Start running on evidence"}
          </h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
            {mode === "login"
              ? "Your business data is isolated to your account and never shared across tenants."
              : "Set up your business profile. You can refine reserves and risk preferences later."}
          </p>

          {error && (
            <Callout tone="red" title="Could not continue" className="mt-5">
              {error}
            </Callout>
          )}

          <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
            {mode === "register" && (
              <>
                <Field label="Your name" htmlFor="full_name" required>
                  <Input
                    id="full_name"
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    placeholder="Darshan Yogesh Neve"
                    autoComplete="name"
                    minLength={2}
                    required
                  />
                </Field>
                <Field label="Business name" htmlFor="business_name" required>
                  <Input
                    id="business_name"
                    value={businessName}
                    onChange={(event) => setBusinessName(event.target.value)}
                    placeholder="DN Ventures Pvt. Ltd"
                    autoComplete="organization"
                    minLength={2}
                    required
                  />
                </Field>
              </>
            )}

            <Field label="Work email" htmlFor="email" required>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@business.com"
                autoComplete="email"
                required
              />
            </Field>

            <Field
              label="Password"
              htmlFor="password"
              required
              hint={mode === "register" ? "At least 8 characters, with a letter and a number." : undefined}
            >
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={mode === "register" ? "Create a strong password" : "Your password"}
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  className="pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </Field>

            {mode === "register" && (
              <Field label="Reporting currency" htmlFor="currency">
                <Select
                  id="currency"
                  value={currency}
                  onChange={(event) => setCurrency(event.target.value)}
                >
                  <option value="INR">INR · Indian rupee</option>
                  <option value="USD">USD · US dollar</option>
                  <option value="EUR">EUR · Euro</option>
                  <option value="GBP">GBP · Pound sterling</option>
                  <option value="AED">AED · UAE dirham</option>
                  <option value="SGD">SGD · Singapore dollar</option>
                </Select>
              </Field>
            )}

            <Button type="submit" loading={submitting} iconRight={ArrowRight} className="mt-1 w-full">
              {mode === "login" ? "Sign in securely" : "Create workspace"}
            </Button>
          </form>

          {mode === "login" && (
            <div className="mt-5 space-y-2">
              <Link
                to="/accountant/login"
                className="flex items-center justify-between rounded-lg border border-brand-100 bg-brand-50/60 px-3 py-2.5 text-[11px] text-brand-800 transition hover:border-brand-200"
              >
                <span className="font-semibold">Accountant portal</span>
                <span className="inline-flex items-center gap-1">
                  Sign in <ArrowRight className="h-3 w-3" />
                </span>
              </Link>
              <Link
                to="/client/login"
                className="flex items-center justify-between rounded-lg border border-cyan-100 bg-cyan-50/60 px-3 py-2.5 text-[11px] text-cyan-900 transition hover:border-cyan-200"
              >
                <span className="font-semibold">Accounting client portal</span>
                <span className="inline-flex items-center gap-1">
                  Sign in <ArrowRight className="h-3 w-3" />
                </span>
              </Link>
              <Link
                to="/employee/login"
                className="flex items-center justify-between rounded-lg border border-teal-100 bg-teal-50/60 px-3 py-2.5 text-[11px] text-teal-800 transition hover:border-teal-200"
              >
                <span className="font-semibold">Employee portal</span>
                <span className="inline-flex items-center gap-1">
                  Sign in <ArrowRight className="h-3 w-3" />
                </span>
              </Link>
              <Link
                to="/developer/login"
                className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-[11px] text-slate-600 transition hover:border-slate-300"
              >
                <span className="font-semibold">Developer console</span>
                <span className="inline-flex items-center gap-1">
                  Sign in <ArrowRight className="h-3 w-3" />
                </span>
              </Link>
            </div>
          )}

          <p className="mt-6 text-center text-xs text-slate-500">
            {mode === "login" ? (
              <>
                New to FINOVEXA?{" "}
                <Link to="/register" className="font-semibold text-brand-600 hover:text-brand-700">
                  Create an account
                </Link>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <Link to="/login" className="font-semibold text-brand-600 hover:text-brand-700">
                  Sign in
                </Link>
              </>
            )}
          </p>

          <p className="mt-3 text-center text-[11px] text-slate-500">
            <Link to="/accounting" className="font-semibold text-brand-600 hover:text-brand-700">
              Accounting services
            </Link>
            <span className="px-1.5 text-slate-300">·</span>
            <Link to="/market-intelligence" className="font-semibold text-brand-600 hover:text-brand-700">
              Market intelligence
            </Link>
          </p>

          <div className="mt-7 flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-[10px] leading-relaxed text-slate-400">
            <LockKeyhole className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              JWT sessions, PBKDF2-hashed passwords and tenant-scoped queries. This build never handles raw
              card data and places live orders only when explicitly enabled for the deployment.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
