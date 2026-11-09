import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  Banknote,
  FilePlus2,
  KeyRound,
  Lock,
  RefreshCw,
  ShieldCheck,
  ShoppingBag,
  TrendingUp,
  UserPlus,
  Users,
  UserX,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, patch, post } from "../lib/api";
import type { EmployeeEntry, TeamEmployee, TeamEntriesResponse, TeamRoster } from "../lib/types";
import { formatDate, formatDateTime, money, pluralize } from "../lib/utils";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  StatCard,
  TableWrap,
  Tabs,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui";
import { StatusBadge } from "../components/DataMode";

type FeedTab = "all" | "sale" | "purchase" | "invoice";

const TYPE_META = {
  invoice: { label: "Invoice", tone: "blue" as const },
  sale: { label: "Sale", tone: "green" as const },
  purchase: { label: "Purchase", tone: "amber" as const },
};

export function TeamPage() {
  const { profile } = useAuth();
  const { toast } = useToast();
  const rosterApi = useApi<TeamRoster>("/team/employees", { pollMs: 30000 });
  const entriesApi = useApi<TeamEntriesResponse>("/team/entries?limit=100", { pollMs: 10000 });
  const [tab, setTab] = useState<FeedTab>("all");
  const [addOpen, setAddOpen] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [statusTarget, setStatusTarget] = useState<TeamEmployee | null>(null);
  const [updating, setUpdating] = useState(false);

  const currency = profile?.currency || "INR";
  const roster = rosterApi.data?.items ?? [];
  const summary = entriesApi.data?.summary;
  const entries = entriesApi.data?.items ?? [];
  const visible = useMemo(
    () => (tab === "all" ? entries : entries.filter((entry) => entry.entry_type === tab)),
    [entries, tab],
  );

  const openAdd = () => {
    setFullName("");
    setEmail("");
    setPassword("");
    setFormError(null);
    setAddOpen(true);
  };

  const createEmployee = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
      setFormError("Password must include at least one letter and one number.");
      return;
    }
    setCreating(true);
    try {
      const result = await post<{ message: string }>("/team/employees", {
        full_name: fullName.trim(),
        email: email.trim(),
        password,
      });
      toast({ title: "Employee account created", description: result.message, tone: "success" });
      setAddOpen(false);
      rosterApi.reload();
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  const confirmStatusChange = async () => {
    if (!statusTarget) return;
    setUpdating(true);
    try {
      await patch(`/team/employees/${statusTarget.id}`, {
        is_active: !statusTarget.is_active,
      });
      toast({
        title: statusTarget.is_active ? "Employee access paused" : "Employee access restored",
        description: `${statusTarget.full_name} ${
          statusTarget.is_active ? "can no longer sign in or use the portal." : "can sign in again."
        }`,
        tone: "success",
      });
      setStatusTarget(null);
      rosterApi.reload();
    } catch (err) {
      toast({ title: "Could not update access", description: getErrorMessage(err), tone: "error" });
    } finally {
      setUpdating(false);
    }
  };

  const refresh = () => {
    rosterApi.reload();
    entriesApi.reload();
  };

  if (rosterApi.loading && !rosterApi.data) return <PageSkeleton cards={4} />;
  if (rosterApi.error && !rosterApi.data) {
    return <ErrorState message={rosterApi.error} onRetry={rosterApi.reload} />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Owner workspace · team"
        title="Team & employee entries"
        description="Create employee logins and watch sale, purchase and invoice activity land in your ledger. Entries refresh automatically."
        actions={
          <>
            <Button variant="outline" icon={RefreshCw} onClick={refresh} loading={entriesApi.loading}>
              Refresh
            </Button>
            <Button icon={UserPlus} onClick={openAdd}>
              Add employee
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Active employees"
          value={String(roster.filter((employee) => employee.is_active).length)}
          icon={Users}
          changeLabel={`${roster.length} total accounts`}
          tone="blue"
        />
        <StatCard
          label="Employee entries"
          value={String(summary?.submitted ?? 0)}
          icon={FilePlus2}
          changeLabel={`${summary?.voided ?? 0} voided`}
          tone="violet"
        />
        <StatCard
          label="Employee sales & invoices"
          value={money(summary?.sales_total ?? 0, currency)}
          icon={TrendingUp}
          changeLabel={`${summary?.sale_count ?? 0} ${pluralize(summary?.sale_count ?? 0, "paid sale")} · ${summary?.invoice_count ?? 0} ${pluralize(summary?.invoice_count ?? 0, "invoice")}`}
          tone="green"
        />
        <StatCard
          label="Employee purchases"
          value={money(summary?.purchases_total ?? 0, currency)}
          icon={ShoppingBag}
          changeLabel={`${summary?.purchase_count ?? 0} ${pluralize(summary?.purchase_count ?? 0, "purchase entry", "purchase entries")}`}
          tone="amber"
        />
      </div>

      <Callout tone="amber" title="Employee-recorded money is not provider-verified" icon={ShieldCheck}>
        Cash and PayPal receipts entered by employees post as <strong>employee-recorded</strong>. PayPal
        entries receive no PayPal API capture or webhook confirmation. Review them in the Payment Center and
        reconcile against your actual bank or PayPal balance.
        <Link to="/payments" className="ml-1 font-semibold underline">
          Open Payment Center
        </Link>
      </Callout>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-5">
          <CardHeader
            title="Employee roster"
            description="Each employee signs in separately and only sees their own entries."
            icon={Users}
          />
          <CardBody className="space-y-2 pt-3">
            {roster.length === 0 ? (
              <EmptyState
                icon={Users}
                title="No employee accounts"
                description="Create a login so an employee can record invoices, sales and purchases for your business."
                action={
                  <Button size="sm" icon={UserPlus} onClick={openAdd}>
                    Add the first employee
                  </Button>
                }
              />
            ) : (
              roster.map((employee) => (
                <div
                  key={employee.id}
                  className="flex flex-col gap-2 rounded-xl border border-slate-100 bg-slate-50/60 px-3 py-2.5 sm:flex-row sm:items-center"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-teal-400 to-brand-600 text-[11px] font-bold text-white">
                    {employee.full_name
                      .split(" ")
                      .map((part) => part[0])
                      .slice(0, 2)
                      .join("")
                      .toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <p className="truncate text-xs font-semibold text-ink-900">{employee.full_name}</p>
                      {employee.is_demo && <Badge tone="slate">DEMO</Badge>}
                      <StatusBadge status={employee.is_active ? "active" : "void"} label={employee.is_active ? "Active" : "Paused"} />
                    </div>
                    <p className="truncate text-[10px] text-slate-400">{employee.email}</p>
                    <p className="text-[10px] text-slate-400">
                      {employee.entry_count} {employee.entry_count === 1 ? "entry" : "entries"} · joined{" "}
                      {formatDate(employee.created_at)}
                    </p>
                  </div>
                  <Button
                    variant={employee.is_active ? "ghost" : "outline"}
                    size="sm"
                    icon={employee.is_active ? UserX : BadgeCheck}
                    onClick={() => setStatusTarget(employee)}
                  >
                    {employee.is_active ? "Pause" : "Restore"}
                  </Button>
                </div>
              ))
            )}

            <div className="rounded-xl border border-slate-200 bg-white p-3">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold text-ink-900">
                <KeyRound className="h-3.5 w-3.5 text-brand-600" /> Employee sign-in
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                Share <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[10px]">/employee/login</code>{" "}
                and the employee&apos;s credentials separately. Employees cannot use the owner login.
              </p>
            </div>
            <p className="text-[10px] leading-relaxed text-slate-400">{rosterApi.data?.note}</p>
          </CardBody>
          <CardFooter>
            <span>Paused employees keep their history but lose access immediately.</span>
            <Link to="/audit" className="font-semibold text-brand-600 hover:text-brand-700">
              Activity log
            </Link>
          </CardFooter>
        </Card>

        <Card className="lg:col-span-7">
          <CardHeader
            title="Employee entry feed"
            description="The latest submissions from every employee, newest first."
            icon={Banknote}
            actions={
              <Tabs<FeedTab>
                items={[
                  { key: "all", label: "All", count: entries.length },
                  { key: "sale", label: "Sales" },
                  { key: "purchase", label: "Purchases" },
                  { key: "invoice", label: "Invoices" },
                ]}
                value={tab}
                onChange={setTab}
                size="sm"
              />
            }
          />
          <div className="mt-3">
            {entriesApi.loading && !entriesApi.data ? (
              <div className="px-5 py-10 text-center text-xs text-slate-400">Loading entries…</div>
            ) : visible.length === 0 ? (
              <EmptyState
                icon={Banknote}
                title={entries.length ? "No entries in this view" : "No employee entries yet"}
                description={
                  entries.length
                    ? "Switch tabs to see other entry types."
                    : "When an employee records a sale, purchase or invoice, it appears here within seconds."
                }
              />
            ) : (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Entry</TH>
                    <TH>Employee</TH>
                    <TH>Method</TH>
                    <TH className="text-right">Amount</TH>
                    <TH>Status</TH>
                    <TH>Submitted</TH>
                  </TR>
                </THead>
                <TBody>
                  {visible.map((entry: EmployeeEntry) => {
                    const meta = TYPE_META[entry.entry_type];
                    return (
                      <TR key={entry.id}>
                        <TD>
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-mono text-[11px] font-semibold text-ink-900">
                              {entry.reference}
                            </span>
                            <Badge tone={meta.tone}>{meta.label}</Badge>
                          </div>
                          <p className="mt-0.5 text-[11px] font-medium text-slate-700">
                            {entry.counterparty}
                          </p>
                          <p className="max-w-[240px] truncate text-[10px] text-slate-400">
                            {entry.description}
                          </p>
                        </TD>
                        <TD>
                          <p className="text-[11px] font-medium text-ink-900">{entry.employee.name}</p>
                          <p className="truncate text-[10px] text-slate-400">{entry.employee.email}</p>
                        </TD>
                        <TD>
                          {entry.payment_method ? (
                            <Badge tone={entry.payment_method === "paypal" ? "violet" : "slate"}>
                              {entry.payment_method === "paypal"
                                ? "PayPal · unverified"
                                : entry.payment_method.toUpperCase()}
                            </Badge>
                          ) : (
                            <span className="text-[10px] text-slate-400">{entry.category || "—"}</span>
                          )}
                        </TD>
                        <TD className="text-right">
                          <span className="text-[12px] font-semibold tabular-nums text-ink-900">
                            {money(entry.amount, entry.currency || currency)}
                          </span>
                          {entry.entry_type === "invoice" && (
                            <p className="text-[10px] text-slate-400">
                              {money(entry.invoice_outstanding || 0, entry.currency || currency)} open
                            </p>
                          )}
                        </TD>
                        <TD>
                          <div className="flex flex-wrap items-center gap-1.5">
                            <StatusBadge status={entry.status === "void" ? "void" : "submitted"} />
                            {entry.status !== "void" && !entry.editable && (
                              <Badge tone="amber" dot title={entry.lock_reason || undefined}>
                                Locked
                              </Badge>
                            )}
                          </div>
                        </TD>
                        <TD>
                          <span className="text-[11px] text-slate-500">
                            {formatDateTime(entry.created_at)}
                          </span>
                        </TD>
                      </TR>
                    );
                  })}
                </TBody>
              </TableWrap>
            )}
          </div>
          <CardFooter>
            <span className="flex items-center gap-1.5">
              <Lock className="h-3 w-3" aria-hidden /> Polling every 10 seconds — not instant push.
            </span>
            <Link to="/recovery" className="font-semibold text-brand-600 hover:text-brand-700">
              Review receivables
            </Link>
          </CardFooter>
        </Card>
      </div>

      <Modal
        open={addOpen}
        onClose={() => {
          if (!creating) setAddOpen(false);
        }}
        title="Add an employee"
        description="Creates a separate employee login linked to your business. The employee cannot see your dashboard."
        size="md"
        footer={
          <>
            <Button variant="outline" onClick={() => setAddOpen(false)} disabled={creating}>
              Cancel
            </Button>
            <Button type="submit" form="add-employee-form" loading={creating}>
              Create account
            </Button>
          </>
        }
      >
        <form id="add-employee-form" className="space-y-4" onSubmit={createEmployee}>
          <Field label="Full name" htmlFor="employee-name" required>
            <Input
              id="employee-name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder="Employee name"
              minLength={2}
              required
            />
          </Field>
          <Field label="Work email" htmlFor="employee-new-email" required>
            <Input
              id="employee-new-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="employee@business.com"
              autoComplete="off"
              required
            />
          </Field>
          <Field
            label="Temporary password"
            htmlFor="employee-password"
            hint="At least 8 characters with a letter and a number. Share it separately."
            required
          >
            <Input
              id="employee-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Create a temporary password"
              autoComplete="new-password"
              minLength={8}
              required
            />
          </Field>
          <Callout tone="blue" title="Scoped by design">
            The employee can generate invoices and record sales and purchases for your ledger. Owner
            dashboard routes and owner APIs reject employee sessions.
          </Callout>
          {formError && (
            <Callout tone="red" title="Could not create account">
              {formError}
            </Callout>
          )}
        </form>
      </Modal>

      <ConfirmDialog
        open={statusTarget !== null}
        onClose={() => setStatusTarget(null)}
        onConfirm={() => void confirmStatusChange()}
        title={statusTarget?.is_active ? "Pause employee access?" : "Restore employee access?"}
        description={
          statusTarget
            ? statusTarget.is_active
              ? `${statusTarget.full_name} will be signed out on their next request and cannot use the employee portal. Their past entries stay in your ledger.`
              : `${statusTarget.full_name} will be able to sign in to the employee portal again.`
            : undefined
        }
        confirmLabel={statusTarget?.is_active ? "Pause access" : "Restore access"}
        tone={statusTarget?.is_active ? "danger" : "success"}
        loading={updating}
      />
    </div>
  );
}
