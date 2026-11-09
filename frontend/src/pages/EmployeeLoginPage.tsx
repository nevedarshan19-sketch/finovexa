import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Eye,
  EyeOff,
  HandCoins,
  LockKeyhole,
  ReceiptText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { getErrorMessage } from "../lib/api";
import { Button, Callout, Field, Input } from "../components/ui";
import { BrandLogo } from "../components/BrandLogo";

export function EmployeeLoginPage() {
  const { employeeLogin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = () => {
    const state = location.state as { from?: string } | null;
    navigate(state?.from || "/employee", { replace: true });
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await employeeLogin(email.trim(), password);
      go();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-slate-50">
      <div className="relative hidden w-[50%] flex-col overflow-hidden bg-gradient-to-br from-[#062c2b] via-navy-950 to-navy-900 px-10 py-9 lg:flex xl:px-14">
        <div className="pointer-events-none absolute -right-24 -top-24 h-[380px] w-[380px] rounded-full bg-teal-400/15 blur-3xl" aria-hidden />
        <BrandLogo subtitle="Employee portal" subtitleClassName="text-teal-300/70" className="relative" />

        <div className="relative my-auto max-w-md py-10">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-teal-300/20 bg-teal-400/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-200">
            <ShieldCheck className="h-3 w-3" /> Scoped employee access
          </p>
          <h1 className="text-[36px] font-semibold leading-[1.14] tracking-tight text-white">
            Record the day&apos;s money.
            <br />
            <span className="bg-gradient-to-r from-teal-300 via-cyan-300 to-brand-300 bg-clip-text text-transparent">
              The owner sees it instantly.
            </span>
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-slate-400">
            Generate invoices, record paid sales and log purchases. Every entry is attributed to you and
            posted to the owner&apos;s ledger.
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {[
              { icon: ReceiptText, title: "Generate invoices", detail: "Line items, tax and due dates." },
              { icon: HandCoins, title: "Record sales", detail: "Cash, UPI, bank, card or PayPal." },
              { icon: Sparkles, title: "Log purchases", detail: "Vendor spend updates owner cash." },
              { icon: LockKeyhole, title: "No owner access", detail: "Dashboard and approvals stay private." },
            ].map((feature) => (
              <div key={feature.title} className="rounded-xl border border-white/[0.07] bg-white/[0.035] p-3.5">
                <feature.icon className="h-4 w-4 text-teal-300" aria-hidden />
                <p className="mt-2 text-[12px] font-semibold text-slate-100">{feature.title}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{feature.detail}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="relative text-[10px] tracking-wide text-slate-600">
          Employee accounts are created by the business owner. Sessions are tenant-scoped.
        </p>
      </div>

      <div className="flex w-full flex-col px-5 py-6 sm:px-8 lg:w-[50%] lg:px-12 xl:px-20">
        <div className="my-auto w-full max-w-md self-center py-10">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-teal-700">
            Employee sign-in
          </p>
          <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink-900">
            Open your work queue
          </h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
            Use the employee credentials provided by the business owner. Owner accounts cannot sign in here.
          </p>

          {error && (
            <Callout tone="red" title="Could not sign in" className="mt-5">
              {error}
            </Callout>
          )}

          <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
            <Field label="Work email" htmlFor="employee_email" required>
              <Input
                id="employee_email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@business.com"
                autoComplete="email"
                required
              />
            </Field>
            <Field label="Password" htmlFor="employee_password" required>
              <div className="relative">
                <Input
                  id="employee_password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Your employee password"
                  autoComplete="current-password"
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
            <Button type="submit" loading={submitting} iconRight={ArrowRight} className="w-full">
              Sign in to employee portal
            </Button>
          </form>

          <div className="mt-7 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-[10px] leading-relaxed text-slate-400">
            <span className="flex items-start gap-2">
              <LockKeyhole className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              This portal can only create and edit its own invoices and purchase/sale entries. It cannot call
              owner-only APIs, view business cash totals, or approve payments and orders.
            </span>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-slate-500">
            <Link to="/login" className="font-semibold text-brand-600 hover:text-brand-700">
              Owner sign-in
            </Link>
            <span className="text-slate-300">·</span>
            <Link to="/developer/login" className="font-semibold text-slate-500 hover:text-slate-700">
              Developer console
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
