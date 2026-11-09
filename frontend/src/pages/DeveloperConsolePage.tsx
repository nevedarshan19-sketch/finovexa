import { useMemo, useState, type FormEvent } from "react";
import {
  Activity,
  Ban,
  CheckCircle2,
  KeyRound,
  Plus,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  UserCog,
  Users,
  UserX,
} from "lucide-react";
import { useToast } from "../context/ToastContext";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, patch, post } from "../lib/api";
import type {
  DeveloperAccount,
  DeveloperAccountsResponse,
  DeveloperOverview,
  DeveloperSecurityLog,
} from "../lib/types";
import { formatDate, formatDateTime, initials } from "../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  Select,
  StatCard,
  TableWrap,
  Tabs,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui";
import { PricingAdmin } from "../components/developer/PricingAdmin";

type RoleFilter =
  | "all"
  | "owner"
  | "employee"
  | "senior_accountant"
  | "junior_accountant"
  | "customer";
type AccountRole = "owner" | "employee" | "senior_accountant" | "junior_accountant";

interface CreateForm {
  role: AccountRole;
  email: string;
  full_name: string;
  password: string;
  business_name: string;
  currency: string;
  owner_id: string;
}

const EMPTY_FORM: CreateForm = {
  role: "employee",
  email: "",
  full_name: "",
  password: "",
  business_name: "",
  currency: "INR",
  owner_id: "",
};

type Tone = "slate" | "blue" | "green" | "amber" | "red";

function detailSummary(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .filter(([key, value]) => key !== "password" && value !== null && value !== undefined)
    .slice(0, 3)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`)
    .join(" · ");
}

export function DeveloperConsolePage() {
  const { toast } = useToast();
  const overviewApi = useApi<DeveloperOverview>("/developer/overview", { pollMs: 30000 });
  const accountsApi = useApi<DeveloperAccountsResponse>("/developer/accounts", { pollMs: 20000 });
  const logApi = useApi<DeveloperSecurityLog>("/developer/security-log?limit=30", {
    pollMs: 30000,
  });

  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [view, setView] = useState<"accounts" | "pricing">("accounts");
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [showCreatePassword, setShowCreatePassword] = useState(false);
  const [loginTarget, setLoginTarget] = useState<DeveloperAccount | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [statusTarget, setStatusTarget] = useState<DeveloperAccount | null>(null);
  const [busy, setBusy] = useState(false);

  const overview = overviewApi.data;
  const accounts = accountsApi.data?.items ?? [];
  const owners = accounts.filter((account) => account.role === "owner" && account.is_active);
  const visible = useMemo(
    () => (roleFilter === "all" ? accounts : accounts.filter((account) => account.role === roleFilter)),
    [accounts, roleFilter],
  );
  const counts = overview?.counts;
  const features = overview?.features;

  const reload = () => {
    overviewApi.reload();
    accountsApi.reload();
    logApi.reload();
  };

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormError(null);
    setShowCreatePassword(false);
    setAddOpen(true);
  };

  const createAccount = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (form.password.length < 8 || !/[A-Za-z]/.test(form.password) || !/[0-9]/.test(form.password)) {
      setFormError("Use at least 8 characters, including a letter and a number.");
      return;
    }
    if (form.role === "owner" && !form.business_name.trim()) {
      setFormError("Business name is required for an owner account.");
      return;
    }
    if (form.role === "employee" && !form.owner_id) {
      setFormError("Select the owner this employee belongs to.");
      return;
    }
    setBusy(true);
    try {
      const result = await post<{ message: string }>("/developer/accounts", {
        role: form.role,
        email: form.email.trim(),
        password: form.password,
        full_name: form.full_name.trim(),
        ...(form.role === "owner"
          ? { business_name: form.business_name.trim(), currency: form.currency }
          : form.role === "employee"
            ? { owner_id: Number(form.owner_id) }
            : {}),
      });
      toast({ title: "Account created", description: result.message, tone: "success" });
      setAddOpen(false);
      reload();
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const updateLogin = async (event: FormEvent) => {
    event.preventDefault();
    if (!loginTarget) return;
    const email = loginEmail.trim().toLowerCase();
    const emailChanged = email !== loginTarget.email.toLowerCase();
    const passwordChanged = newPassword.length > 0;
    if (!emailChanged && !passwordChanged) {
      setFormError("Change the login email or set a new password.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setFormError("Enter a valid login email.");
      return;
    }
    if (passwordChanged) {
      if (newPassword.length < 8 || !/[A-Za-z]/.test(newPassword) || !/[0-9]/.test(newPassword)) {
        setFormError("Use at least 8 characters, including a letter and a number.");
        return;
      }
      if (newPassword !== confirmPassword) {
        setFormError("The two passwords do not match.");
        return;
      }
    }
    setBusy(true);
    setFormError(null);
    try {
      const result = await patch<{ message: string }>(`/developer/accounts/${loginTarget.id}`, {
        ...(emailChanged ? { email } : {}),
        ...(passwordChanged ? { password: newPassword } : {}),
      });
      toast({ title: "Login updated", description: result.message, tone: "success" });
      setLoginTarget(null);
      accountsApi.reload();
      logApi.reload();
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const changeStatus = async () => {
    if (!statusTarget) return;
    setBusy(true);
    try {
      const result = await patch<{ message: string }>(`/developer/accounts/${statusTarget.id}`, {
        is_active: !statusTarget.is_active,
      });
      toast({
        title: statusTarget.is_active ? "Account disabled" : "Account enabled",
        description: result.message,
        tone: "success",
      });
      setStatusTarget(null);
      reload();
    } catch (err) {
      toast({ title: "Could not update account", description: getErrorMessage(err), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  if (overviewApi.loading && !overview) return <PageSkeleton cards={5} />;
  if (overviewApi.error && !overview) {
    return <ErrorState message={overviewApi.error} onRetry={overviewApi.reload} />;
  }

  const readiness: { label: string; value: string; tone: Tone; note: string }[] = [
    {
      label: "Owner & employee login",
      value: "ID + password",
      tone: "green",
      note: "PBKDF2-SHA256, rate-limited sign-in",
    },
    {
      label: "Developer login",
      value: "Separate portal",
      tone: "green",
      note: "Environment-provisioned account",
    },
    {
      label: "Public owner registration",
      value: features?.public_registration_open ? "Open" : "Closed",
      tone: features?.public_registration_open ? "amber" : "green",
      note: "Anyone can create a new owner workspace",
    },
    {
      label: "Demo seed",
      value: features?.demo_seed_enabled ? "Enabled" : "Off",
      tone: features?.demo_seed_enabled ? "amber" : "slate",
      note: "Seeded demo accounts are separate from real owners",
    },
    {
      label: "LLM",
      value: features?.llm.configured ? "Configured" : "Deterministic fallback",
      tone: features?.llm.configured ? "green" : "slate",
      note: "No model key is exposed to the browser",
    },
    {
      label: "PayPal",
      value: features?.paypal.mode ?? "simulated",
      tone: features?.paypal.configured ? "green" : "amber",
      note: features?.paypal.configured ? "Credentials configured" : "Simulated checkout only",
    },
    {
      label: "Upstox",
      value: features?.upstox.live_trading_ready
        ? "Live orders ready"
        : features?.upstox.configured
          ? "Quotes only"
          : "Demo quotes",
      tone: features?.upstox.live_trading_ready ? "red" : features?.upstox.configured ? "amber" : "slate",
      note: features?.upstox.static_ip_proxy_configured
        ? "Static-IP proxy configured"
        : "Static-IP proxy not configured",
    },
    {
      label: "Market data",
      value:
        features?.market_data.metals_configured || features?.market_data.news_configured
          ? "Configured"
          : "Demo providers",
      tone:
        features?.market_data.metals_configured || features?.market_data.news_configured
          ? "green"
          : "slate",
      note: "Metals and news providers are independent",
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Maintainer surface"
        title="Developer console"
        description="Manage owner, employee, accountant and customer logins, verify integration readiness and review authentication events. Business ledgers and owner approvals are deliberately excluded."
        actions={
          view === "accounts" ? (
            <>
              <Button variant="outline" size="sm" icon={RefreshCw} onClick={reload}>
                Refresh
              </Button>
              <Button size="sm" icon={Plus} onClick={openCreate}>
                New account
              </Button>
            </>
          ) : undefined
        }
      />

      <Tabs
        items={[
          { key: "accounts", label: "Accounts & security" },
          { key: "pricing", label: "Pricing" },
        ]}
        value={view}
        onChange={setView}
      />

      {view === "pricing" ? (
        <PricingAdmin />
      ) : (
        <>
      <Callout tone="amber" title={`Scoped maintainer access · ${overview?.environment ?? "unknown"} environment`}>
        Developer accounts cannot open the owner dashboard, employee work queue, invoices, approvals,
        payments or market positions. Account passwords are never returned by any API or written to logs.
      </Callout>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        <StatCard label="Owners" value={counts?.owners ?? "—"} icon={Users} tone="blue" />
        <StatCard label="Employees" value={counts?.employees ?? "—"} icon={UserCog} tone="green" />
        <StatCard label="Accountants" value={counts?.accountants ?? "—"} icon={ShieldCheck} tone="violet" />
        <StatCard label="Customers" value={counts?.customers ?? "—"} icon={Users} tone="slate" />
        <StatCard label="Active accounts" value={counts?.active_accounts ?? "—"} icon={CheckCircle2} tone="green" />
        <StatCard label="Disabled" value={counts?.inactive_accounts ?? "—"} icon={UserX} tone="amber" />
      </div>

      <Card>
        <CardHeader
          title="System readiness"
          description="Booleans only. Secrets remain in backend environment variables."
          icon={ServerCog}
          actions={<Badge tone="slate">v1.0.0</Badge>}
        />
        <CardBody className="grid gap-3 md:grid-cols-2">
          {readiness.map((row) => (
            <div
              key={row.label}
              className="flex items-start justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2.5"
            >
              <div className="min-w-0">
                <p className="text-[12px] font-semibold text-ink-900">{row.label}</p>
                <p className="mt-0.5 text-[10px] text-slate-400">{row.note}</p>
              </div>
              <Badge tone={row.tone}>{row.value}</Badge>
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Accounts"
          description="Owner, employee, accountant and customer logins. Developer accounts are managed by deployment environment."
          icon={Users}
          actions={
            <Select
              aria-label="Filter accounts by role"
              value={roleFilter}
              onChange={(event) => setRoleFilter(event.target.value as RoleFilter)}
              className="h-8 w-44 text-xs"
            >
              <option value="all">All roles</option>
              <option value="owner">Owners</option>
              <option value="employee">Employees</option>
              <option value="senior_accountant">Senior accountants</option>
              <option value="junior_accountant">Junior accountants</option>
              <option value="customer">Customers</option>
            </Select>
          }
        />
        <CardBody className="p-0">
          {accountsApi.loading && accounts.length === 0 ? (
            <div className="p-5 text-sm text-slate-500">Loading accounts…</div>
          ) : accountsApi.error && accounts.length === 0 ? (
            <div className="p-5">
              <ErrorState message={accountsApi.error} onRetry={accountsApi.reload} />
            </div>
          ) : visible.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No accounts in this view"
              description="Create an owner, employee or accountant login to get started."
              action={
                <Button size="sm" icon={Plus} onClick={openCreate}>
                  New account
                </Button>
              }
            />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Account</TH>
                  <TH>Role</TH>
                  <TH>Business / owner</TH>
                  <TH>Status</TH>
                  <TH>Created</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {visible.map((account) => (
                  <TR key={account.id}>
                    <TD>
                      <div className="flex items-center gap-2.5">
                        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-600">
                          {initials(account.full_name)}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-[13px] font-semibold text-ink-900">
                            {account.full_name}
                          </p>
                          <p className="truncate text-[11px] text-slate-500">{account.email}</p>
                        </div>
                      </div>
                    </TD>
                    <TD>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge
                          tone={
                            account.role === "owner"
                              ? "blue"
                              : account.role === "employee"
                                ? "green"
                                : account.role === "customer"
                                  ? "slate"
                                  : "violet"
                          }
                        >
                          {account.role.replace(/_/g, " ")}
                        </Badge>
                        {account.is_demo && <Badge tone="slate">demo</Badge>}
                      </div>
                    </TD>
                    <TD>
                      <span className="text-[12px] text-slate-600">
                        {account.role === "owner"
                          ? account.business_name || "—"
                          : account.role === "employee"
                            ? account.owner_email || "—"
                            : account.role === "customer"
                              ? "Client portal"
                              : "Accounting practice"}
                      </span>
                    </TD>
                    <TD>
                      <Badge tone={account.is_active ? "green" : "red"} dot>
                        {account.is_active ? "active" : "disabled"}
                      </Badge>
                    </TD>
                    <TD>
                      <span className="text-[12px] text-slate-500">{formatDate(account.created_at)}</span>
                    </TD>
                    <TD>
                      <div className="flex justify-end gap-1.5">
                        <Button
                          variant="outline"
                          size="sm"
                          icon={UserCog}
                          onClick={() => {
                            setLoginTarget(account);
                            setLoginEmail(account.email);
                            setNewPassword("");
                            setConfirmPassword("");
                            setFormError(null);
                          }}
                        >
                          Edit login
                        </Button>
                        <Button
                          variant={account.is_active ? "ghost" : "outline"}
                          size="sm"
                          icon={account.is_active ? Ban : CheckCircle2}
                          onClick={() => setStatusTarget(account)}
                        >
                          {account.is_active ? "Disable" : "Enable"}
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Security log"
          description="Authentication, account and developer events. Financial records are excluded."
          icon={ShieldCheck}
          actions={<Badge tone="slate">{logApi.data?.count ?? 0} events</Badge>}
        />
        <CardBody className="p-0">
          {logApi.loading && !logApi.data ? (
            <div className="p-5 text-sm text-slate-500">Loading security events…</div>
          ) : logApi.error && !logApi.data ? (
            <div className="p-5">
              <ErrorState message={logApi.error} onRetry={logApi.reload} />
            </div>
          ) : (logApi.data?.items.length ?? 0) === 0 ? (
            <EmptyState icon={Activity} title="No security events yet" description="Sign-ins and account changes will appear here." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {logApi.data?.items.map((event) => (
                <li key={event.id} className="flex flex-wrap items-start gap-3 px-5 py-3">
                  <Badge
                    tone={
                      event.action.startsWith("auth.")
                        ? "blue"
                        : event.action.startsWith("developer.")
                          ? "amber"
                          : "slate"
                    }
                  >
                    {event.action}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-[12px] font-semibold text-ink-900">{event.actor}</p>
                    <p className="mt-0.5 text-[10px] text-slate-400">
                      {detailSummary(event.detail) || "No additional detail"}
                    </p>
                  </div>
                  <span className="text-[10px] text-slate-400">{formatDateTime(event.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
        </>
      )}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Create an account"
        description="Owner, employee and accountant logins can be created here. Customers are created by a senior accountant; developer access is environment-only."
        footer={
          <>
            <Button variant="outline" onClick={() => setAddOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" form="developer-create-account" loading={busy} icon={Plus}>
              Create account
            </Button>
          </>
        }
      >
        <form id="developer-create-account" className="space-y-4" onSubmit={createAccount} noValidate>
          {formError && (
            <Callout tone="red" title="Could not create account">
              {formError}
            </Callout>
          )}
          <Field label="Account type" htmlFor="account_role" required>
            <Select
              id="account_role"
              value={form.role}
              onChange={(event) =>
                setForm((current) => ({ ...current, role: event.target.value as AccountRole }))
              }
            >
              <option value="employee">Employee</option>
              <option value="owner">Business owner</option>
              <option value="senior_accountant">Senior accountant</option>
              <option value="junior_accountant">Junior accountant</option>
            </Select>
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name" htmlFor="account_name" required>
              <Input
                id="account_name"
                value={form.full_name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, full_name: event.target.value }))
                }
                placeholder="Riya Sharma"
                autoComplete="name"
                required
              />
            </Field>
            <Field label="Work email" htmlFor="account_email" required>
              <Input
                id="account_email"
                type="email"
                value={form.email}
                onChange={(event) =>
                  setForm((current) => ({ ...current, email: event.target.value }))
                }
                placeholder="name@business.com"
                autoComplete="email"
                required
              />
            </Field>
          </div>
          {form.role === "owner" ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Business name" htmlFor="business_name" required>
                <Input
                  id="business_name"
                  value={form.business_name}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, business_name: event.target.value }))
                  }
                  placeholder="DN Ventures Pvt. Ltd"
                  required
                />
              </Field>
              <Field label="Reporting currency" htmlFor="account_currency">
                <Select
                  id="account_currency"
                  value={form.currency}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, currency: event.target.value }))
                  }
                >
                  <option value="INR">INR · Indian rupee</option>
                  <option value="USD">USD · US dollar</option>
                  <option value="EUR">EUR · Euro</option>
                  <option value="GBP">GBP · Pound sterling</option>
                  <option value="AED">AED · UAE dirham</option>
                  <option value="SGD">SGD · Singapore dollar</option>
                </Select>
              </Field>
            </div>
          ) : form.role === "employee" ? (
            <Field label="Belongs to owner" htmlFor="account_owner" required>
              <Select
                id="account_owner"
                value={form.owner_id}
                onChange={(event) =>
                  setForm((current) => ({ ...current, owner_id: event.target.value }))
                }
                required
              >
                <option value="">Select an active owner</option>
                {owners.map((owner) => (
                  <option key={owner.id} value={owner.id}>
                    {owner.full_name} · {owner.business_name || owner.email}
                  </option>
                ))}
              </Select>
            </Field>
          ) : (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              Accountant logins sign in at <code>/accountant/login</code> and are scoped to the
              businesses their owner grants access to inside the app. No owner link is needed at
              creation.
            </p>
          )}
          <Field
            label="Initial password"
            htmlFor="account_password"
            required
            hint="At least 8 characters, including a letter and a number. Share it separately."
          >
            <div className="relative">
              <Input
                id="account_password"
                type={showCreatePassword ? "text" : "password"}
                value={form.password}
                onChange={(event) =>
                  setForm((current) => ({ ...current, password: event.target.value }))
                }
                placeholder="Set a strong password"
                autoComplete="new-password"
                className="pr-10"
                required
              />
              <button
                type="button"
                onClick={() => setShowCreatePassword((value) => !value)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600"
                aria-label={showCreatePassword ? "Hide password" : "Show password"}
              >
                {showCreatePassword ? "Hide" : "Show"}
              </button>
            </div>
          </Field>
        </form>
      </Modal>

      <Modal
        open={Boolean(loginTarget)}
        onClose={() => setLoginTarget(null)}
        title="Edit login"
        description={
          loginTarget
            ? `${loginTarget.full_name} · current login ${loginTarget.email}. Existing sessions remain valid until they expire.`
            : undefined
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setLoginTarget(null)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" form="developer-edit-login" loading={busy} icon={KeyRound}>
              Save login
            </Button>
          </>
        }
      >
        <form id="developer-edit-login" className="space-y-4" onSubmit={updateLogin} noValidate>
          {formError && (
            <Callout tone="red" title="Could not update login">
              {formError}
            </Callout>
          )}
          <Field
            label="Login email"
            htmlFor="login_email"
            required
            hint="This becomes the account's sign-in ID. It must be unique."
          >
            <Input
              id="login_email"
              type="email"
              value={loginEmail}
              onChange={(event) => setLoginEmail(event.target.value)}
              autoComplete="off"
              required
            />
          </Field>
          <div className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2.5">
            <p className="text-[11px] font-semibold text-ink-900">Set a new password</p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">
              Leave both password fields blank to keep the current password.
            </p>
            <div className="mt-3 space-y-3">
              <Field label="New password" htmlFor="reset_password">
                <Input
                  id="reset_password"
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  autoComplete="new-password"
                />
              </Field>
              <Field label="Confirm new password" htmlFor="reset_password_confirm">
                <Input
                  id="reset_password_confirm"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                />
              </Field>
            </div>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(statusTarget)}
        onClose={() => setStatusTarget(null)}
        onConfirm={changeStatus}
        title={statusTarget?.is_active ? "Disable this account?" : "Enable this account?"}
        description={
          statusTarget?.is_active
            ? statusTarget.role === "owner"
              ? "The owner and all of their employees will lose API access immediately. Historical records are retained."
              : "This employee will lose API access immediately. Historical entries are retained."
            : "The account will be able to sign in again with its existing password."
        }
        confirmLabel={statusTarget?.is_active ? "Disable account" : "Enable account"}
        tone={statusTarget?.is_active ? "danger" : "success"}
        loading={busy}
      />
    </div>
  );
}
