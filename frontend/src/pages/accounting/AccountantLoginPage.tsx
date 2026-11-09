import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Calculator,
  Eye,
  EyeOff,
  FileCheck2,
  LockKeyhole,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { getErrorMessage } from "../../lib/api";
import { Button, Callout, Field, Input } from "../../components/ui";
import { BrandLogo } from "../../components/BrandLogo";

export function AccountantLoginPage() {
  const { accountantLogin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await accountantLogin(email.trim(), password);
      const state = location.state as { from?: string } | null;
      navigate(state?.from?.startsWith("/accountant") ? state.from : "/accountant", { replace: true });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-slate-50">
      <div className="relative hidden w-[50%] flex-col overflow-hidden bg-gradient-to-br from-[#052221] via-navy-950 to-navy-900 px-10 py-9 lg:flex xl:px-14">
        <div className="pointer-events-none absolute -right-24 -top-24 h-[380px] w-[380px] rounded-full bg-teal-400/15 blur-3xl" aria-hidden />
        <BrandLogo subtitle="Accounting practice" subtitleClassName="text-teal-300/70" className="relative" />

        <div className="relative my-auto max-w-md py-10">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-teal-300/20 bg-teal-400/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-200">
            <ShieldCheck className="h-3 w-3" /> Staff-only access
          </p>
          <h1 className="text-[36px] font-semibold leading-[1.14] tracking-tight text-white">
            Run the practice.
            <br />
            <span className="bg-gradient-to-r from-teal-300 via-cyan-300 to-brand-300 bg-clip-text text-transparent">
              Review before anything ships.
            </span>
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-slate-400">
            Senior accountants manage clients, quotations and reviews. Junior accountants work only on
            the clients and tasks assigned to them. Nothing is filed with a tax authority from here.
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {[
              { icon: UsersRound, title: "Client register", detail: "Isolated per business." },
              { icon: Calculator, title: "Accounting work", detail: "Vouchers, bank, GST workings." },
              { icon: FileCheck2, title: "Senior review", detail: "Approve or request changes." },
              { icon: LockKeyhole, title: "Role boundaries", detail: "Juniors cannot approve work." },
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
          Accountant accounts are provisioned by the practice owner. Every action is attributed and audited.
        </p>
      </div>

      <div className="flex w-full flex-col px-5 py-6 sm:px-8 lg:w-[50%] lg:px-12 xl:px-20">
        <div className="my-auto w-full max-w-md self-center py-10">
          <BrandLogo
            variant="light"
            subtitle="Accounting practice"
            subtitleClassName="text-teal-700"
            className="mb-6 lg:hidden"
          />

          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-teal-700">
            Accountant sign-in
          </p>
          <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink-900">
            Open the practice workspace
          </h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
            Use the staff credentials issued by the practice. Owner, employee and client accounts cannot
            sign in here.
          </p>

          {error && (
            <Callout tone="red" title="Could not sign in" className="mt-5">
              {error}
            </Callout>
          )}

          <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
            <Field label="Work email" htmlFor="accountant_email" required>
              <Input
                id="accountant_email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@practice.com"
                autoComplete="email"
                required
              />
            </Field>
            <Field label="Password" htmlFor="accountant_password" required>
              <div className="relative">
                <Input
                  id="accountant_password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Your practice password"
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
              Sign in to the practice
            </Button>
          </form>

          <div className="mt-7 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-[10px] leading-relaxed text-slate-400">
            <span className="flex items-start gap-2">
              <LockKeyhole className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              Senior and junior accountants see different data. Clients are isolated per business, and
              report approval stays with senior staff.
            </span>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-slate-500">
            <Link to="/client/login" className="font-semibold text-teal-700 hover:text-teal-800">
              Client portal
            </Link>
            <span className="text-slate-300">·</span>
            <Link to="/login" className="font-semibold text-brand-600 hover:text-brand-700">
              Owner sign-in
            </Link>
            <span className="text-slate-300">·</span>
            <Link to="/accounting" className="font-semibold text-slate-500 hover:text-slate-700">
              Accounting services
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
