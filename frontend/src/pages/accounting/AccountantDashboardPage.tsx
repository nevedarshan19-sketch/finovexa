import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  FileSearch,
  Inbox,
  IndianRupee,
  TimerReset,
  TrendingUp,
  UsersRound,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "../../context/AuthContext";
import { get, getErrorMessage } from "../../lib/api";
import type {
  AccountingClient,
  AccountingTask,
  JuniorWorkspace,
  SeniorOverview,
} from "../../lib/accountingTypes";
import { TASK_STATUSES, formatMonth, labelize } from "../../lib/accounting";
import { compactMoney, formatDate, money, timeAgo } from "../../lib/utils";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  PageHeader,
  PageSkeleton,
  ProgressBar,
  Select,
  StatCard,
} from "../../components/ui";
import { PriorityBadge, StatusBadge } from "../../components/accounting/AccountingUI";

function financialYears(): string[] {
  const today = new Date();
  const start = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
  return [0, 1, 2].map((offset) => {
    const from = start - offset;
    return `${from}-${String((from + 1) % 100).padStart(2, "0")}`;
  });
}

function DeadlineRow({ task }: { task: AccountingTask }) {
  return (
    <li className="flex items-start justify-between gap-3 border-b border-slate-100 py-2.5 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-[13px] font-semibold text-ink-900">{task.title}</p>
        <p className="mt-0.5 truncate text-[11px] text-slate-500">
          {task.client_name || "Client"} · due {formatDate(task.due_date)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <PriorityBadge priority={task.priority} />
        <StatusBadge status={task.status} />
      </div>
    </li>
  );
}

function SeniorDashboard() {
  const [overview, setOverview] = useState<SeniorOverview | null>(null);
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [clientId, setClientId] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const [fy, setFy] = useState(financialYears()[0]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (clientId) params.set("client_id", String(clientId));
      if (status) params.set("status", status);
      if (fy) params.set("financial_year", fy);
      const query = params.toString();
      const data = await get<SeniorOverview>(`/accounting/senior/overview${query ? `?${query}` : ""}`);
      setOverview(data);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [clientId, status, fy]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    get<{ items: AccountingClient[] }>("/accounting/senior/clients")
      .then((data) => setClients(data.items))
      .catch(() => setClients([]));
  }, []);

  const chartData = useMemo(
    () =>
      (overview?.monthly_series || []).map((row) => ({
        label: formatMonth(row.period),
        Sales: row.sales,
        Purchases: row.purchases,
      })),
    [overview],
  );

  if (loading && !overview) return <PageSkeleton cards={4} />;
  if (error && !overview)
    return (
      <div className="space-y-4">
        <PageHeader eyebrow="Accounting practice" title="Senior accountant overview" />
        <ErrorState message={error} onRetry={load} />
      </div>
    );
  if (!overview) return null;

  const onTimeShare =
    overview.performance.completed_this_fy > 0
      ? Math.round((overview.performance.on_time / overview.performance.completed_this_fy) * 100)
      : null;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Accounting practice"
        title="Senior accountant overview"
        description={`Financial year ${overview.financial_year}. Review the practice pipeline, assign work and approve what reaches the client.`}
        actions={
          <Link to="/accountant/tasks?status=submitted">
            <Button icon={FileSearch}>Review queue ({overview.awaiting_review})</Button>
          </Link>
        }
      />

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Client" htmlFor="overview_client">
          <Select
            id="overview_client"
            value={clientId ?? ""}
            onChange={(event) => setClientId(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">All clients</option>
            {clients.map((client) => (
              <option key={client.id} value={client.id}>
                {client.business_name} · {client.code}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Task status" htmlFor="overview_status">
          <Select id="overview_status" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            {TASK_STATUSES.map((value) => (
              <option key={value} value={value}>
                {labelize(value)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Financial year" htmlFor="overview_fy">
          <Select id="overview_fy" value={fy} onChange={(event) => setFy(event.target.value)}>
            {financialYears().map((value) => (
              <option key={value} value={value}>
                FY {value}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex items-end">
          <Button variant="outline" className="w-full" onClick={load} loading={loading}>
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Active clients"
          value={overview.clients.active}
          icon={UsersRound}
          tone="blue"
          sub={`${overview.clients.total} total · ${overview.clients.onboarding} onboarding`}
          to="/accountant/clients"
        />
        <StatCard
          label="New enquiries"
          value={overview.enquiries.new}
          icon={Inbox}
          tone="amber"
          sub={`${overview.enquiries.pending_quotations} quotations awaiting response`}
          to="/accountant/enquiries"
        />
        <StatCard
          label="Awaiting senior review"
          value={overview.awaiting_review}
          icon={FileSearch}
          tone="violet"
          sub="Submitted by junior accountants"
          to="/accountant/tasks?status=submitted"
        />
        <StatCard
          label="Work in progress"
          value={overview.work_in_progress}
          icon={TimerReset}
          tone="blue"
          sub={`${overview.tasks.total} tasks in this view`}
          to="/accountant/tasks"
        />
        <StatCard
          label="Overdue tasks"
          value={overview.tasks.overdue}
          icon={AlertTriangle}
          tone="red"
          sub="Past due and not approved"
          to="/accountant/tasks?overdue=1"
        />
        <StatCard
          label="Outstanding fees"
          value={money(overview.billing.outstanding)}
          icon={IndianRupee}
          tone="amber"
          sub={`${money(overview.billing.overdue)} overdue · ${overview.billing.overdue_count} invoices`}
          to="/accountant/billing"
        />
        <StatCard
          label="Fees collected"
          value={money(overview.billing.paid)}
          icon={CheckCircle2}
          tone="green"
          sub={`${money(overview.billing.invoiced)} invoiced`}
          to="/accountant/billing"
        />
        <StatCard
          label="Completed this FY"
          value={overview.performance.completed_this_fy}
          icon={TrendingUp}
          tone="slate"
          sub={onTimeShare === null ? "No completions yet" : `${onTimeShare}% on or before due date`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Recorded sales and purchases"
            description="Taxable value from posted vouchers over the last six months."
            icon={TrendingUp}
          />
          <CardBody>
            {chartData.length === 0 ? (
              <EmptyState title="No vouchers yet" description="Post sales and purchase vouchers to see the practice ledger trend." />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} barGap={6}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e8eef7" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                    <YAxis
                      tick={{ fontSize: 11, fill: "#94a3b8" }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(value: number) => compactMoney(value)}
                    />
                    <Tooltip
                      formatter={(value: number, name: string) => [money(value), name]}
                      labelStyle={{ fontSize: 11, color: "#64748b" }}
                      contentStyle={{ borderRadius: 12, border: "1px solid #e2e8f0", fontSize: 12 }}
                    />
                    <Bar dataKey="Sales" fill="#2478f0" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="Purchases" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-brand-500" aria-hidden /> Sales
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-amber-500" aria-hidden /> Purchases
              </span>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Junior workload"
            description="Open tasks and assigned clients per junior accountant."
            icon={UsersRound}
          />
          <CardBody className="space-y-3">
            {overview.workload.length === 0 && (
              <p className="text-xs text-slate-500">No active junior accountants are configured.</p>
            )}
            {overview.workload.map((row) => (
              <div key={row.user_id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[13px] font-semibold text-ink-900">{row.name}</p>
                  <Badge tone={row.submitted > 0 ? "violet" : "slate"}>{row.submitted} submitted</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
                  <span>{row.open_tasks} open tasks</span>
                  <span>{row.clients} clients</span>
                </div>
                <ProgressBar
                  value={Math.min(100, row.open_tasks * 10)}
                  tone={row.open_tasks > 8 ? "amber" : "blue"}
                  className="mt-2"
                  label={`${row.name} workload`}
                />
              </div>
            ))}
            <Link to="/accountant/tasks" className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600">
              Open task board <ArrowRight className="h-3 w-3" />
            </Link>
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Upcoming deadlines"
            description="Nearest due dates across the current task filter."
            icon={CalendarClock}
            actions={
              <Link to="/accountant/tasks" className="text-[11px] font-semibold text-brand-600">
                All tasks
              </Link>
            }
          />
          <CardBody className="pt-0">
            {overview.upcoming_deadlines.length === 0 ? (
              <EmptyState title="Nothing due" description="No upcoming deadlines in this view." icon={CalendarClock} />
            ) : (
              <ul>
                {overview.upcoming_deadlines.map((task) => (
                  <DeadlineRow key={task.id} task={task} />
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Overdue work"
            description="Past the due date and not yet approved or delivered."
            icon={AlertTriangle}
            actions={
              <Link to="/accountant/tasks?overdue=1" className="text-[11px] font-semibold text-brand-600">
                Overdue queue
              </Link>
            }
          />
          <CardBody className="pt-0">
            {overview.overdue_tasks.length === 0 ? (
              <EmptyState title="Nothing overdue" description="Every open task is within its due date." icon={CheckCircle2} />
            ) : (
              <ul>
                {overview.overdue_tasks.map((task) => (
                  <DeadlineRow key={task.id} task={task} />
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Recent practice activity"
          description="Audited accounting events across all clients."
          icon={ClipboardList}
          actions={
            <Link to="/accountant/audit" className="text-[11px] font-semibold text-brand-600">
              Full audit trail
            </Link>
          }
        />
        <CardBody className="pt-0">
          {overview.recent_activity.length === 0 ? (
            <EmptyState title="No activity yet" description="Create a client, task or voucher to start the trail." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {overview.recent_activity.map((event) => (
                <li key={event.id} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="text-[12px] font-semibold text-ink-900">{labelize(event.action.replace(/^accounting\./, ""))}</p>
                    <p className="truncate text-[11px] text-slate-500">
                      {event.actor}
                      {typeof event.detail?.client_id === "number" ? ` · client #${event.detail.client_id}` : ""}
                    </p>
                  </div>
                  <span className="shrink-0 text-[10px] text-slate-400">{timeAgo(event.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function JuniorDashboard() {
  const [workspace, setWorkspace] = useState<JuniorWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setWorkspace(await get<JuniorWorkspace>("/accounting/junior/workspace"));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !workspace) return <PageSkeleton cards={4} />;
  if (error && !workspace)
    return (
      <div className="space-y-4">
        <PageHeader eyebrow="Accounting practice" title="My workspace" />
        <ErrorState message={error} onRetry={load} />
      </div>
    );
  if (!workspace) return null;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Accounting practice"
        title={`${workspace.accountant.name.split(" ")[0]}'s work queue`}
        description="Only the clients and tasks assigned to you appear here. Work you finish is submitted to a senior accountant for review."
        actions={
          <Link to="/accountant/work">
            <Button icon={ClipboardList}>Open workbench</Button>
          </Link>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="My clients" value={workspace.counts.clients} icon={UsersRound} tone="blue" to="/accountant/clients" />
        <StatCard
          label="Open tasks"
          value={workspace.counts.open_tasks}
          icon={ClipboardList}
          tone="violet"
          sub={`${workspace.counts.in_progress} in progress`}
          to="/accountant/tasks"
        />
        <StatCard
          label="Awaiting review"
          value={workspace.counts.submitted}
          icon={FileSearch}
          tone="blue"
          sub="With a senior accountant"
          to="/accountant/tasks"
        />
        <StatCard
          label="Changes requested"
          value={workspace.counts.changes_requested}
          icon={AlertTriangle}
          tone="red"
          sub={`${workspace.counts.overdue} overdue tasks`}
          to="/accountant/tasks"
        />
      </div>

      {workspace.documents_pending > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] text-amber-900">
          {workspace.documents_pending} client document request{workspace.documents_pending === 1 ? "" : "s"} still pending.
          Chase them from the client record.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Upcoming deadlines" description="Your nearest due dates." icon={CalendarClock} />
          <CardBody className="pt-0">
            {workspace.upcoming_deadlines.length === 0 ? (
              <EmptyState title="Nothing due" description="No upcoming deadlines right now." icon={CalendarClock} />
            ) : (
              <ul>
                {workspace.upcoming_deadlines.map((task) => (
                  <DeadlineRow key={task.id} task={task} />
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="My clients" description="Clients you are assigned to." icon={UsersRound} />
          <CardBody className="pt-0">
            {workspace.clients.length === 0 ? (
              <EmptyState title="No clients assigned" description="A senior accountant will assign client work to you." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {workspace.clients.map((client) => (
                  <li key={client.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <Link
                        to={`/accountant/clients/${client.id}`}
                        className="truncate text-[13px] font-semibold text-ink-900 hover:text-brand-700"
                      >
                        {client.business_name}
                      </Link>
                      <p className="text-[11px] text-slate-500">
                        {client.code} · {client.service_package}
                      </p>
                    </div>
                    <StatusBadge status={client.status} />
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="My tasks" description="Assigned accounting work, newest deadlines first." icon={ClipboardList} />
        <CardBody className="space-y-2">
          {workspace.tasks.length === 0 ? (
            <EmptyState title="No tasks yet" description="Tasks assigned to you will appear here." />
          ) : (
            workspace.tasks.slice(0, 12).map((task) => (
              <div key={task.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[13px] font-semibold text-ink-900">{task.title}</p>
                  <div className="flex items-center gap-1.5">
                    <PriorityBadge priority={task.priority} />
                    <StatusBadge status={task.status} />
                  </div>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">
                  {task.client_name} · due {formatDate(task.due_date)}
                  {task.is_overdue ? " · overdue" : ""}
                </p>
                <ProgressBar value={task.progress} className="mt-2" label={`${task.title} progress`} />
              </div>
            ))
          )}
          <Link to="/accountant/tasks" className="inline-flex items-center gap-1 pt-1 text-[11px] font-semibold text-brand-600">
            Open full task list <ArrowRight className="h-3 w-3" />
          </Link>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Notifications" description="Assignments, review decisions and document updates." icon={BellRing} />
        <CardBody className="pt-0">
          {workspace.notifications.items.length === 0 ? (
            <EmptyState title="No notifications" description="You are up to date." icon={BellRing} />
          ) : (
            <ul className="divide-y divide-slate-100">
              {workspace.notifications.items.slice(0, 8).map((item) => (
                <li key={item.id} className="py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[12px] font-semibold text-ink-900">{item.title}</p>
                    <span className="text-[10px] text-slate-400">{timeAgo(item.created_at)}</span>
                  </div>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{item.body}</p>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

export function AccountantDashboardPage() {
  const { isSeniorAccountant } = useAuth();
  return isSeniorAccountant ? <SeniorDashboard /> : <JuniorDashboard />;
}
