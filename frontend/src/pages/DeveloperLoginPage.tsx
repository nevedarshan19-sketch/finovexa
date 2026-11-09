import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Code2,
  Eye,
  EyeOff,
  KeyRound,
  LockKeyhole,
  ServerCog,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { getErrorMessage } from "../lib/api";
import { Button, Callout, Field, Input } from "../components/ui";
import { BrandLogo } from "../components/BrandLogo";

export function DeveloperLoginPage() {
  const { developerLogin } = useAuth();
  const navigate = useNavigate();
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
      await developerLogin(email.trim(), password);
      navigate("/developer", { replace: true });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-slate-950">
      <div className="relative hidden w-[52%] flex-col overflow-hidden bg-gradient-to-br from-slate-950 via-[#0b1220] to-[#1c1917] px-10 py-9 lg:flex xl:px-14">
        <div className="pointer-events-none absolute -right-24 -top-24 h-[380px] w-[380px] rounded-full bg-amber-500/10 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-28 left-8 h-[320px] w-[320px] rounded-full bg-cyan-500/10 blur-3xl" aria-hidden />

        <BrandLogo subtitle="Developer console" subtitleClassName="text-amber-300/80" className="relative" />

        <div className="relative my-auto max-w-lg py-10">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-amber-300/20 bg-amber-400/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-200">
            <Code2 className="h-3 w-3" /> Maintainer access
          </p>
          <h1 className="text-[36px] font-semibold leading-[1.14] tracking-tight text-white">
            Operate the platform.
            <br />
            <span className="bg-gradient-to-r from-amber-300 via-orange-300 to-cyan-300 bg-clip-text text-transparent">
              Without touching owner money.
            </span>
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-slate-400">
            Create and maintain owner and employee accounts, review authentication events and verify
            integration readiness. Owner ledgers, approvals and payments stay outside this console.
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {[
              { icon: Users, title: "Account control", detail: "Create, disable and reset owner/employee access." },
              { icon: ShieldCheck, title: "Security events", detail: "Auth and account changes, no ledger data." },
              { icon: ServerCog, title: "System readiness", detail: "LLM, PayPal, Upstox and market-data flags." },
              { icon: LockKeyhole, title: "Least privilege", detail: "No owner dashboard or employee work queue." },
            ].map((feature) => (
              <div key={feature.title} className="rounded-xl border border-white/[0.07] bg-white/[0.035] p-3.5">
                <feature.icon className="h-4 w-4 text-amber-300" aria-hidden />
                <p className="mt-2 text-[12px] font-semibold text-slate-100">{feature.title}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{feature.detail}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="relative text-[10px] tracking-wide text-slate-600">
          Developer accounts are provisioned from backend environment variables. No demo login.
        </p>
      </div>

      <div className="flex w-full flex-col bg-slate-50 px-5 py-6 sm:px-8 lg:w-[48%] lg:px-12 xl:px-20">
        <div className="my-auto w-full max-w-md self-center py-10">
          <BrandLogo
            variant="light"
            subtitle="Developer console"
            subtitleClassName="text-amber-700"
            className="mb-6 lg:hidden"
          />

          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-700">
            Developer sign-in
          </p>
          <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink-900">
            Authenticate as a maintainer
          </h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
            This portal is separate from owner and employee sign-in. Use the developer credentials
            provisioned on the server.
          </p>

          {error && (
            <Callout tone="red" title="Could not sign in" className="mt-5">
              {error}
            </Callout>
          )}

          <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
            <Field label="Developer email" htmlFor="developer_email" required>
              <Input
                id="developer_email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="developer@your-domain.com"
                autoComplete="email"
                required
              />
            </Field>
            <Field label="Password" htmlFor="developer_password" required>
              <div className="relative">
                <Input
                  id="developer_password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Developer password"
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
              Sign in to developer console
            </Button>
          </form>

          <div className="mt-7 flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-2.5 text-[10px] leading-relaxed text-amber-900">
            <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              Developer credentials are never stored in the frontend. Failed sign-ins are rate limited,
              and every developer action is written to the audit trail.
            </span>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-slate-500">
            <Link to="/login" className="font-semibold text-brand-600 hover:text-brand-700">
              Owner sign-in
            </Link>
            <span className="text-slate-300">·</span>
            <Link to="/employee/login" className="font-semibold text-teal-700 hover:text-teal-800">
              Employee portal
            </Link>
          </div>

          <p className="mt-8 text-center text-[10px] text-slate-400">
            FINOVEXA AI · maintainer surface
          </p>
        </div>
      </div>
    </div>
  );
}
