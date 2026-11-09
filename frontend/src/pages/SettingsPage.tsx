import { useEffect, useState } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  Building2,
  CheckCircle2,
  CreditCard,
  DatabaseZap,
  ExternalLink,
  Globe2,
  KeyRound,
  Landmark,
  LineChart,
  Lock,
  Mail,
  MessageSquare,
  PlugZap,
  RefreshCw,
  RotateCcw,
  Save,
  Server,
  Settings2,
  ShieldCheck,
  Sparkles,
  Unplug,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, post, put } from "../lib/api";
import type {
  Integration,
  IntegrationsResponse,
  PayPalConnectionCheck,
  PayPalSettings,
  Profile,
  RuntimeSettings,
} from "../lib/types";
import { formatDateTime, titleCase } from "../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Checkbox,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Skeleton,
} from "../components/ui";
import { DataModeBadge, DataModeLegend, StatusBadge } from "../components/DataMode";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

interface FormState {
  business_name: string;
  currency: string;
  timezone: string;
  reporting_period: Profile["reporting_period"];
  min_cash_reserve: string;
  opening_cash_balance: string;
  risk_tolerance: Profile["risk_tolerance"];
  reminder_tone: Profile["reminder_tone"];
  research_interests: string;
}

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD"];
const TIMEZONES = [
  "Asia/Kolkata",
  "UTC",
  "Asia/Dubai",
  "Asia/Singapore",
  "Europe/London",
  "America/New_York",
];

function toForm(profile: Profile): FormState {
  return {
    business_name: profile.business_name,
    currency: profile.currency,
    timezone: profile.timezone,
    reporting_period: profile.reporting_period,
    min_cash_reserve: String(profile.min_cash_reserve),
    opening_cash_balance: String(profile.opening_cash_balance),
    risk_tolerance: profile.risk_tolerance,
    reminder_tone: profile.reminder_tone,
    research_interests: (profile.research_interests || []).join(", "),
  };
}

function ProviderIcon({ provider }: { provider: string }) {
  const icons: Record<string, typeof PlugZap> = {
    paypal: CreditCard,
    upstox: LineChart,
    metals: Landmark,
    news: DatabaseZap,
    email: Mail,
    sms: MessageSquare,
    llm: BrainCircuit,
  };
  const Icon = icons[provider] || PlugZap;
  return <Icon className="h-4 w-4" aria-hidden />;
}

function IntegrationCard({
  item,
  checking,
  onCheck,
}: {
  item: Integration;
  checking: boolean;
  onCheck: () => void;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
            <ProviderIcon provider={item.provider} />
          </span>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-ink-900">{item.label}</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{item.purpose}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <DataModeBadge mode={item.mode} />
          <StatusBadge status={item.status} />
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-100 bg-slate-50/70 px-2.5 py-1.5">
          <p className="text-[10px] uppercase tracking-wide text-slate-400">Setup</p>
          <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-600">{item.setup}</p>
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50/70 px-2.5 py-1.5">
          <p className="text-[10px] uppercase tracking-wide text-slate-400">In this build</p>
          <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-600">{item.demo_behaviour}</p>
        </div>
      </div>

      {item.provider === "upstox" && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Badge tone={item.live_trading_ready ? "amber" : "slate"} dot>
            {item.live_trading_ready
              ? "Live orders enabled"
              : item.live_trading_enabled
                ? "Live flag on · not ready"
                : "Live trading disabled"}
          </Badge>
          <span className="text-[10px] text-slate-400">
            {item.live_trading_ready
              ? item.static_ip_proxy_configured
                ? "Real Upstox orders only after owner approval, routed via the static-IP proxy."
                : "Real Upstox orders only after owner approval. No static-IP order proxy is configured."
              : "Orders are simulated unless live trading is fully configured and selected on the ticket."}
          </span>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2.5">
        <p className="text-[10px] text-slate-400">
          {item.last_checked_at ? `Last checked ${formatDateTime(item.last_checked_at)}` : "Not checked yet"}
        </p>
        <div className="flex items-center gap-1.5">
          {item.auth_url && (
            <a
              href={item.auth_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10.5px] font-medium text-slate-600 transition hover:border-brand-300 hover:text-brand-700"
            >
              Authorize at provider <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          )}
          <Button
            variant="outline"
            size="sm"
            icon={RefreshCw}
            onClick={onCheck}
            loading={checking}
            disabled={checking}
          >
            Check connection
          </Button>
        </div>
      </div>
    </div>
  );
}

function FeatureTile({
  label,
  value,
  detail,
  configured,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  configured: boolean;
  icon: typeof Server;
}) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-100 text-slate-500">
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </span>
        <Badge tone={configured ? "green" : "slate"} dot={configured}>
          {configured ? "Configured" : "Not configured"}
        </Badge>
      </div>
      <p className="mt-2 text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="text-[12.5px] font-semibold text-ink-900">{value}</p>
      <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">{detail}</p>
    </div>
  );
}

function DemoResetModal({
  open,
  onClose,
  onReset,
}: {
  open: boolean;
  onClose: () => void;
  onReset: () => Promise<void>;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setConfirmation("");
      setAcknowledged(false);
      setError(null);
    }
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reset the demo workspace?"
      description="Restores seeded invoices, payments, orders, approvals and audit history for the demo account."
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="danger"
            icon={RotateCcw}
            loading={busy}
            disabled={confirmation !== "RESET DEMO" || !acknowledged || busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onReset();
                onClose();
              } catch (err) {
                setError(getErrorMessage(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            Reset demo data
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Callout tone="amber" title="This only works for the demo account" icon={AlertTriangle}>
          Live business records are never wiped. The backend refuses this action for non-demo accounts and
          when demo reset is disabled on the deployment.
        </Callout>
        <Field
          label='Type "RESET DEMO" to confirm'
          htmlFor="reset-confirm"
          hint="The seeded starting state will replace current demo records. This cannot be undone."
        >
          <Input
            id="reset-confirm"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder="RESET DEMO"
            autoComplete="off"
          />
        </Field>
        <Checkbox
          checked={acknowledged}
          onChange={setAcknowledged}
          label="I understand that demo invoices, payments, approvals, orders and audit events will be restored."
        />
        {error && <p className="text-[11px] font-medium text-rose-600">{error}</p>}
      </div>
    </Modal>
  );
}

function PayPalPanel({ onChanged }: { onChanged: () => void }) {
  const { toast } = useToast();
  const settings = useApi<PayPalSettings>("/paypal/settings");
  const [environment, setEnvironment] = useState<"sandbox" | "live">("sandbox");
  const [enabled, setEnabled] = useState(true);
  const [confirmLive, setConfirmLive] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data = settings.data;

  useEffect(() => {
    if (!data) return;
    setEnvironment(data.environment);
    setEnabled(data.enabled);
    setConfirmLive(false);
  }, [data]);

  const save = async () => {
    if (environment === "live" && enabled && !confirmLive) {
      setError("Tick the production confirmation before enabling live PayPal.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await put<PayPalSettings>("/paypal/settings", {
        environment,
        enabled,
        confirm_live: environment === "live" && enabled ? confirmLive : false,
      });
      toast({
        tone: "success",
        title: "PayPal settings saved",
        description: result.configured
          ? `Checkout mode is now ${result.mode_label}. Secrets stay in the backend environment.`
          : `${titleCase(environment)} selected. No credentials are present, so simulation stays available.`,
      });
      settings.reload();
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setError(null);
    try {
      const result = await post<PayPalConnectionCheck>("/paypal/settings/test");
      toast({
        tone: result.connected ? "success" : result.status === "simulated" ? "info" : "error",
        title: result.connected ? "PayPal connected" : "PayPal not connected",
        description: result.message,
      });
      settings.reload();
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setTesting(false);
    }
  };

  const selected = data?.environments.find((item) => item.environment === environment);

  return (
    <Card>
      <CardHeader
        title="PayPal"
        description="Sandbox first. Production requires its own credentials and an explicit confirmation."
        icon={CreditCard}
        actions={data ? <DataModeBadge mode={data.mode} /> : undefined}
      />
      <CardBody className="space-y-3 pt-4">
        {settings.loading && !data ? (
          <Skeleton className="h-40 w-full" />
        ) : settings.error ? (
          <ErrorState message={settings.error} onRetry={settings.reload} />
        ) : data ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label="Environment"
                htmlFor="paypal-environment"
                hint="Credential pairs are separate. Switching environments never copies secrets."
              >
                <Select
                  id="paypal-environment"
                  value={environment}
                  onChange={(event) => {
                    setEnvironment(event.target.value as "sandbox" | "live");
                    setConfirmLive(false);
                  }}
                >
                  <option value="sandbox">Sandbox</option>
                  <option value="live">Production</option>
                </Select>
              </Field>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-600">
                <p className="flex items-center justify-between gap-2">
                  <span>Credentials</span>
                  <span className={selected?.credentials_present ? "text-emerald-600" : "text-amber-600"}>
                    {selected?.credentials_present ? "Present in backend env" : "Not configured"}
                  </span>
                </p>
                <p className="mt-1 flex items-center justify-between gap-2">
                  <span>Client ID</span>
                  <span className="font-mono text-[10px]">{selected?.client_id_hint || "—"}</span>
                </p>
                <p className="mt-1 flex items-center justify-between gap-2">
                  <span>Webhook ID</span>
                  <span className={selected?.webhook_configured ? "text-emerald-600" : "text-amber-600"}>
                    {selected?.webhook_configured ? "Configured" : "Not configured"}
                  </span>
                </p>
                <p className="mt-1 flex items-center justify-between gap-2">
                  <span>API host</span>
                  <span className="truncate font-mono text-[10px]">{selected?.base_url || "—"}</span>
                </p>
              </div>
            </div>

            <Checkbox
              checked={enabled}
              onChange={setEnabled}
              label="Enable PayPal checkout for this workspace"
            />

            {environment === "live" && enabled && (
              <Checkbox
                checked={confirmLive}
                onChange={setConfirmLive}
                label={
                  <span>
                    I understand production PayPal moves <strong>real money</strong>. Credentials must already be
                    set in the backend environment and webhooks must be configured before enabling.
                  </span>
                }
              />
            )}

            {environment === "live" && !selected?.credentials_present && (
              <Callout tone="amber" title="Production credentials missing" icon={AlertTriangle}>
                Set <code className="font-mono text-[10px]">PAYPAL_LIVE_CLIENT_ID</code>,{" "}
                <code className="font-mono text-[10px]">PAYPAL_LIVE_CLIENT_SECRET</code> and{" "}
                <code className="font-mono text-[10px]">PAYPAL_LIVE_WEBHOOK_ID</code> in the backend, then restart
                the API. The app never activates production on its own.
              </Callout>
            )}

            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-navy-950 px-3 py-2">
              <code className="min-w-0 flex-1 break-all font-mono text-[10.5px] text-slate-300">
                {data.webhook_endpoint}
              </code>
              <CopyButton value={data.webhook_endpoint} label="Copy" />
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              {data.environments.map((item) => (
                <div
                  key={item.environment}
                  className={`rounded-lg border px-3 py-2 text-[11px] ${
                    item.environment === data.environment
                      ? "border-brand-200 bg-brand-50/40"
                      : "border-slate-100 bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-slate-700">{item.label}</span>
                    <Badge tone={item.credentials_present ? "green" : "slate"}>
                      {item.credentials_present ? "Ready" : "Not configured"}
                    </Badge>
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-slate-500">
                    {item.client_id_hint || "no client id"}
                  </p>
                  <p className="mt-0.5 text-[10px] text-slate-400">
                    Webhook {item.webhook_configured ? "configured" : "missing"}
                    {item.environment === data.environment ? " · active selection" : ""}
                  </p>
                </div>
              ))}
            </div>

            <Callout tone="blue" title="Secrets never reach the browser" icon={ShieldCheck}>
              {data.security_note} Only masked hints, booleans and the environment selection are returned here.
              Access tokens are cached server-side and never logged.
            </Callout>

            {error && <p className="text-[11px] font-medium text-rose-600">{error}</p>}
          </>
        ) : null}
      </CardBody>
      <CardFooter className="flex-wrap gap-2">
        <span className="flex items-center gap-1.5 text-[10px] text-slate-400">
          <Globe2 className="h-3 w-3" aria-hidden />
          {data?.updated_by ? `Last changed by ${data.updated_by}` : "Managed by the business owner"}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            icon={RefreshCw}
            onClick={() => void test()}
            loading={testing}
            disabled={saving || testing}
          >
            Test connection
          </Button>
          <Button size="sm" icon={Save} onClick={() => void save()} loading={saving} disabled={saving}>
            Save PayPal settings
          </Button>
        </div>
      </CardFooter>
    </Card>
  );
}

export function SettingsPage() {
  const { user, profile, demoMode, setProfile, refresh } = useAuth();
  const { toast } = useToast();
  const integrations = useApi<IntegrationsResponse>("/integrations");
  const runtime = useApi<RuntimeSettings>("/settings/runtime");
  const [form, setForm] = useState<FormState | null>(profile ? toForm(profile) : null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [resetOpen, setResetOpen] = useState(false);

  useEffect(() => {
    if (profile) setForm(toForm(profile));
  }, [profile]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => (current ? { ...current, [key]: value } : current));
  };

  const saveProfile = async () => {
    if (!form) return;
    if (form.business_name.trim().length < 2) {
      setFormError("Business name must be at least 2 characters.");
      return;
    }
    const reserve = Number(form.min_cash_reserve);
    const opening = Number(form.opening_cash_balance);
    if (!Number.isFinite(reserve) || reserve < 0) {
      setFormError("Minimum cash reserve must be a non-negative number.");
      return;
    }
    if (!Number.isFinite(opening) || opening < 0) {
      setFormError("Opening cash balance must be a non-negative number.");
      return;
    }
    const interests = form.research_interests
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (interests.length > 10) {
      setFormError("List at most 10 research interests.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const result = await put<{ message: string; profile: Profile }>("/profile", {
        business_name: form.business_name.trim(),
        currency: form.currency,
        timezone: form.timezone,
        reporting_period: form.reporting_period,
        min_cash_reserve: reserve,
        opening_cash_balance: opening,
        risk_tolerance: form.risk_tolerance,
        reminder_tone: form.reminder_tone,
        research_interests: interests,
      });
      setProfile(result.profile);
      setForm(toForm(result.profile));
      toast({ tone: "success", title: "Profile saved", description: result.message });
      window.dispatchEvent(new Event("finovexa:approvals-changed"));
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const checkConnection = async (provider: string) => {
    setChecking((current) => ({ ...current, [provider]: true }));
    try {
      const result = await post<{ status: string; message: string; mode: string }>(
        "/integrations/check",
        { provider },
      );
      toast({
        tone: result.status === "error" ? "error" : result.status === "demo" ? "info" : "success",
        title: `${titleCase(provider)} check · ${result.status}`,
        description: result.message,
      });
      integrations.reload();
      runtime.reload();
    } catch (err) {
      toast({ tone: "error", title: "Connection check failed", description: getErrorMessage(err) });
    } finally {
      setChecking((current) => ({ ...current, [provider]: false }));
    }
  };

  const resetDemo = async () => {
    const result = await post<{ message: string }>("/demo/reset", { confirm: "RESET DEMO" });
    toast({
      tone: "success",
      title: "Demo workspace restored",
      description: result.message,
    });
    await refresh();
    integrations.reload();
    runtime.reload();
    window.dispatchEvent(new Event("finovexa:approvals-changed"));
  };

  const runtimeData = runtime.data;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Workspace"
        title="Settings & Integrations"
        description="Business profile, reserve policy, provider connections, runtime capabilities and demo controls. Credentials live only in backend environment variables."
        actions={<Badge tone="slate" dot>{runtimeData?.environment || "local"}</Badge>}
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Business profile"
              description="These values drive your reserve policy, forecasts, reminder tone and research defaults."
              icon={Building2}
            />
            <CardBody className="pt-4">
              {!form ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <Skeleton key={index} className="h-10 w-full" />
                  ))}
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Business name" htmlFor="business-name" required className="sm:col-span-2">
                    <Input
                      id="business-name"
                      value={form.business_name}
                      onChange={(event) => update("business_name", event.target.value)}
                      maxLength={160}
                    />
                  </Field>
                  <Field label="Currency" htmlFor="currency" hint="ISO 4217 code used for every amount.">
                    <Select
                      id="currency"
                      value={form.currency}
                      onChange={(event) => update("currency", event.target.value)}
                    >
                      {CURRENCIES.map((currency) => (
                        <option key={currency} value={currency}>
                          {currency}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Timezone" htmlFor="timezone">
                    <Select
                      id="timezone"
                      value={form.timezone}
                      onChange={(event) => update("timezone", event.target.value)}
                    >
                      {TIMEZONES.map((timezone) => (
                        <option key={timezone} value={timezone}>
                          {timezone}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Reporting period" htmlFor="reporting">
                    <Select
                      id="reporting"
                      value={form.reporting_period}
                      onChange={(event) =>
                        update("reporting_period", event.target.value as Profile["reporting_period"])
                      }
                    >
                      <option value="weekly">Weekly</option>
                      <option value="monthly">Monthly</option>
                      <option value="quarterly">Quarterly</option>
                    </Select>
                  </Field>
                  <Field label="Risk tolerance" htmlFor="risk">
                    <Select
                      id="risk"
                      value={form.risk_tolerance}
                      onChange={(event) =>
                        update("risk_tolerance", event.target.value as Profile["risk_tolerance"])
                      }
                    >
                      <option value="conservative">Conservative</option>
                      <option value="balanced">Balanced</option>
                      <option value="growth">Growth</option>
                    </Select>
                  </Field>
                  <Field
                    label="Minimum cash reserve"
                    htmlFor="reserve"
                    hint="The forecast and investment headroom never plan below this floor."
                  >
                    <Input
                      id="reserve"
                      type="number"
                      min={0}
                      step="1000"
                      value={form.min_cash_reserve}
                      onChange={(event) => update("min_cash_reserve", event.target.value)}
                    />
                  </Field>
                  <Field
                    label="Opening cash balance"
                    htmlFor="opening"
                    hint={`Opening balance date: ${profile?.opening_balance_date || "—"}. Changing this recomputes recorded cash; it does not create a payment.`}
                  >
                    <Input
                      id="opening"
                      type="number"
                      min={0}
                      step="1000"
                      value={form.opening_cash_balance}
                      onChange={(event) => update("opening_cash_balance", event.target.value)}
                    />
                  </Field>
                  <Field label="Reminder tone" htmlFor="reminder-tone" hint="Default tone for drafted reminders.">
                    <Select
                      id="reminder-tone"
                      value={form.reminder_tone}
                      onChange={(event) =>
                        update("reminder_tone", event.target.value as Profile["reminder_tone"])
                      }
                    >
                      <option value="friendly">Friendly</option>
                      <option value="professional">Professional</option>
                      <option value="firm">Firm</option>
                    </Select>
                  </Field>
                  <Field
                    label="Research interests"
                    htmlFor="interests"
                    hint="Comma-separated, up to 10. Used to rank research ideas — not to auto-trade."
                  >
                    <Input
                      id="interests"
                      value={form.research_interests}
                      onChange={(event) => update("research_interests", event.target.value)}
                      placeholder="Large-cap IT, Gold, Index ETFs"
                    />
                  </Field>
                </div>
              )}
              {formError && (
                <Callout tone="red" title="Check these fields" className="mt-4" icon={AlertTriangle}>
                  {formError}
                </Callout>
              )}
            </CardBody>
            <CardFooter className="justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => profile && setForm(toForm(profile))}
                disabled={saving || !form}
              >
                Discard changes
              </Button>
              <Button icon={Save} onClick={() => void saveProfile()} loading={saving} disabled={!form}>
                Save profile
              </Button>
            </CardFooter>
          </Card>

          <PayPalPanel onChanged={() => runtime.reload()} />

          <Card>
            <CardHeader
              title="Integrations"
              description={integrations.data?.secrets_note}
              icon={PlugZap}
              actions={
                <Button
                  variant="outline"
                  size="sm"
                  icon={RefreshCw}
                  onClick={() => {
                    integrations.reload();
                    runtime.reload();
                  }}
                  loading={integrations.loading}
                >
                  Refresh
                </Button>
              }
            />
            <CardBody className="space-y-3 pt-4">
              {integrations.loading && !integrations.data ? (
                <div className="space-y-3">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <Skeleton key={index} className="h-28 w-full" />
                  ))}
                </div>
              ) : integrations.error ? (
                <ErrorState message={integrations.error} onRetry={integrations.reload} />
              ) : integrations.data?.items.length ? (
                integrations.data.items.map((item) => (
                  <IntegrationCard
                    key={item.provider}
                    item={item}
                    checking={Boolean(checking[item.provider])}
                    onCheck={() => void checkConnection(item.provider)}
                  />
                ))
              ) : (
                <EmptyState title="No integrations configured" icon={Unplug} />
              )}
            </CardBody>
            <CardFooter>
              <span className="flex items-center gap-1.5">
                <Lock className="h-3 w-3" aria-hidden /> Secret values are never sent to this page.
              </span>
              <Badge tone="blue">Backend environment only</Badge>
            </CardFooter>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Runtime capabilities" icon={Server} />
            <CardBody className="space-y-2.5 pt-3">
              {runtime.loading && !runtimeData ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <Skeleton key={index} className="h-20 w-full" />
                  ))}
                </div>
              ) : runtime.error ? (
                <ErrorState message={runtime.error} onRetry={runtime.reload} />
              ) : runtimeData ? (
                <>
                  <FeatureTile
                    label="AI provider"
                    value={runtimeData.features.llm.mode === "llm" ? "LLM-assisted" : "Deterministic rules"}
                    detail={
                      runtimeData.features.llm.configured
                        ? `Model: ${runtimeData.features.llm.model || "configured"}`
                        : "Same read-only tools, no external model key."
                    }
                    configured={runtimeData.features.llm.configured}
                    icon={BrainCircuit}
                  />
                  <FeatureTile
                    label="PayPal"
                    value={runtimeData.features.paypal.mode}
                    detail={
                      runtimeData.features.paypal.webhook_signature_verification
                        ? "Webhooks verified with PayPal signature API."
                        : "Demo HMAC verification; unsigned events rejected."
                    }
                    configured={runtimeData.features.paypal.configured}
                    icon={CreditCard}
                  />
                  <FeatureTile
                    label="Upstox"
                    value={
                      runtimeData.features.upstox.live_trading_ready
                        ? "Live orders"
                        : runtimeData.features.upstox.configured
                          ? "Quotes only"
                          : "Demo quotes"
                    }
                    detail={
                      !runtimeData.features.upstox.live_trading_enabled
                        ? "Live trading disabled. All orders are simulated."
                        : !runtimeData.features.upstox.configured
                          ? "Live flag is on but no Upstox token is configured. Orders stay simulated."
                          : runtimeData.features.upstox.static_ip_proxy_configured
                            ? "Live Upstox orders enabled, gated by owner approval and routed through the static-IP proxy."
                            : "Live Upstox orders enabled and gated by owner approval. No static-IP order proxy is configured, so Upstox may reject orders from this host."
                    }
                    configured={runtimeData.features.upstox.configured}
                    icon={LineChart}
                  />
                  <FeatureTile
                    label="Market data"
                    value={
                      runtimeData.features.market_data.metals_configured ||
                      runtimeData.features.market_data.news_configured
                        ? "Partially live"
                        : "Demo dataset"
                    }
                    detail={`Metals: ${
                      runtimeData.features.market_data.metals_configured ? "configured" : "demo"
                    } · News: ${runtimeData.features.market_data.news_configured ? "configured" : "demo"}`}
                    configured={
                      runtimeData.features.market_data.metals_configured ||
                      runtimeData.features.market_data.news_configured
                    }
                    icon={DatabaseZap}
                  />
                </>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Security posture" icon={ShieldCheck} />
            <CardBody className="space-y-2.5 pt-3">
              {runtimeData ? (
                <>
                  <div className="flex items-start gap-2.5">
                    <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden />
                    <div>
                      <p className="text-[11.5px] font-semibold text-slate-700">{runtimeData.security.token_type}</p>
                      <p className="text-[10.5px] leading-relaxed text-slate-500">
                        Session tokens are scoped to your account. Every endpoint enforces ownership.
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <Lock className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden />
                    <div>
                      <p className="text-[11.5px] font-semibold text-slate-700">
                        {runtimeData.security.password_hashing}
                      </p>
                      <p className="text-[10.5px] leading-relaxed text-slate-500">
                        Passwords are hashed with a per-user salt.
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <Server className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden />
                    <div>
                      <p className="text-[11.5px] font-semibold text-slate-700">Secrets location</p>
                      <p className="text-[10.5px] leading-relaxed text-slate-500">
                        {runtimeData.security.secrets_location}
                      </p>
                    </div>
                  </div>
                  <Callout tone="amber" icon={AlertTriangle}>
                    {runtimeData.security.demo_warning}
                  </Callout>
                </>
              ) : (
                <Skeleton className="h-32 w-full" />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Account" icon={Settings2} />
            <CardBody className="space-y-2 pt-3 text-[11.5px]">
              <div className="flex justify-between gap-2">
                <span className="text-slate-400">Signed in as</span>
                <span className="truncate font-medium text-slate-700">{user?.email}</span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-slate-400">Account type</span>
                <Badge tone={demoMode ? "violet" : "green"}>{demoMode ? "Demo workspace" : "Live account"}</Badge>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-slate-400">Currency</span>
                <span className="font-medium text-slate-700">
                  {runtimeData?.currency || profile?.currency}
                </span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-slate-400">Timezone</span>
                <span className="font-medium text-slate-700">
                  {runtimeData?.timezone || profile?.timezone}
                </span>
              </div>
              <p className="border-t border-slate-100 pt-2 text-[10px] leading-relaxed text-slate-400">
                Use the profile menu in the top bar to sign out. This build has no password reset flow.
              </p>
            </CardBody>
          </Card>

          {integrations.data?.data_modes?.length ? (
            <Card>
              <CardHeader title="Data mode labels" icon={Sparkles} />
              <CardBody className="pt-3">
                <DataModeLegend modes={integrations.data.data_modes} />
              </CardBody>
            </Card>
          ) : null}

          {demoMode && (
            <Card className="border-amber-200">
              <CardHeader
                title="Demo workspace"
                description="Restore seeded records between demos. Only the demo account can do this."
                icon={RotateCcw}
              />
              <CardBody className="pt-3">
                <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
                  <p className="text-[11px] leading-relaxed text-amber-900">
                    Reset clears demo mutations — simulated payments, approvals, orders and audit entries — and
                    restores the original dataset. It never touches another business.
                  </p>
                </div>
                <Button
                  variant="outline"
                  icon={RotateCcw}
                  className="mt-3 w-full border-rose-200 text-rose-600 hover:bg-rose-50"
                  onClick={() => setResetOpen(true)}
                  disabled={runtimeData ? !runtimeData.demo_reset_enabled : true}
                >
                  Reset demo data
                </Button>
                {runtimeData && !runtimeData.demo_reset_enabled && (
                  <p className="mt-1.5 text-center text-[10px] text-slate-400">
                    Demo reset is disabled on this deployment.
                  </p>
                )}
              </CardBody>
            </Card>
          )}
        </div>
      </div>

      <DemoResetModal open={resetOpen} onClose={() => setResetOpen(false)} onReset={resetDemo} />
    </div>
  );
}
