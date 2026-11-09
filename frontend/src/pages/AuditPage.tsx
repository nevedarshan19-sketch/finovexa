import { useMemo, useState } from "react";
import {
  Activity,
  CalendarRange,
  Filter,
  RefreshCw,
  ScrollText,
  Search,
  ShieldCheck,
  User,
  X,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import type { AuditEvent } from "../lib/types";
import { formatDateTime, number, timeAgo, titleCase } from "../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
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
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui";

interface AuditResponse {
  items: AuditEvent[];
  count: number;
  protection_note: string;
}

interface ActionsResponse {
  items: { action: string; entity_type: string | null }[];
}

function actionTone(action: string): "blue" | "green" | "amber" | "violet" | "slate" | "red" | "cyan" {
  if (action.startsWith("approval")) return "amber";
  if (action.startsWith("order")) return "violet";
  if (action.startsWith("paypal")) return "blue";
  if (action.startsWith("reminder")) return "green";
  if (action.startsWith("integration")) return "cyan";
  if (action.includes("failed") || action.includes("rejected")) return "red";
  return "slate";
}

function nextDay(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  date.setDate(date.getDate() + 1);
  return date.toISOString().slice(0, 10);
}

function EventDetailModal({ event, onClose }: { event: AuditEvent; onClose: () => void }) {
  return (
    <Modal
      open
      onClose={onClose}
      title={<span className="font-mono text-sm">{event.action}</span>}
      description={`Event #${event.id} · ${formatDateTime(event.created_at)}`}
      size="md"
      footer={
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Actor</p>
            <p className="mt-0.5 text-[12px] font-medium text-slate-700">{event.actor}</p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Entity</p>
            <p className="mt-0.5 text-[12px] font-medium text-slate-700">
              {event.entity_type ? `${titleCase(event.entity_type)} · ${event.entity_id || "—"}` : "—"}
            </p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Action</p>
            <p className="mt-0.5 font-mono text-[11px] text-slate-700">{event.action}</p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Recorded</p>
            <p className="mt-0.5 text-[12px] font-medium text-slate-700">{formatDateTime(event.created_at)}</p>
          </div>
        </div>
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Structured detail
          </p>
          <pre className="max-h-80 overflow-auto rounded-lg bg-navy-950 p-3 text-[11px] leading-relaxed text-slate-300">
            {JSON.stringify(event.detail, null, 2)}
          </pre>
        </div>
        <Callout tone="green" icon={ShieldCheck}>
          Audit details never include credentials, tokens, passwords or card data. Entries are scoped to your
          business only.
        </Callout>
      </div>
    </Modal>
  );
}

export function AuditPage() {
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [selected, setSelected] = useState<AuditEvent | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (action) params.set("action", action);
    if (entityType) params.set("entity_type", entityType);
    if (start) params.set("start", start);
    if (end) params.set("end", nextDay(end));
    return `/audit-log?${params.toString()}`;
  }, [action, entityType, start, end]);

  const events = useApi<AuditResponse>(query);
  const actions = useApi<ActionsResponse>("/audit-log/actions");

  const entityTypes = useMemo(() => {
    const values = new Set<string>();
    for (const item of actions.data?.items || []) {
      if (item.entity_type) values.add(item.entity_type);
    }
    return Array.from(values).sort();
  }, [actions.data?.items]);

  const actionNames = useMemo(
    () => Array.from(new Set((actions.data?.items || []).map((item) => item.action))).sort(),
    [actions.data?.items],
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const rows = events.data?.items || [];
    if (!needle) return rows;
    return rows.filter((event) =>
      [event.actor, event.action, event.entity_type || "", event.entity_id || "", JSON.stringify(event.detail)]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [events.data?.items, search]);

  const summary = useMemo(() => {
    const rows = events.data?.items || [];
    const uniqueActions = new Set(rows.map((row) => row.action));
    const actors = new Set(rows.map((row) => row.actor));
    return {
      total: rows.length,
      uniqueActions: uniqueActions.size,
      actors: actors.size,
      latest: rows[0]?.created_at || null,
    };
  }, [events.data?.items]);

  const filtersActive = Boolean(action || entityType || start || end || search);

  const clearFilters = () => {
    setSearch("");
    setAction("");
    setEntityType("");
    setStart("");
    setEnd("");
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Governance"
        title="Activity & Audit Log"
        description="A scoped, append-only record of approvals, payments, simulated orders, integrations and profile changes."
        actions={
          <Button
            variant="outline"
            size="sm"
            icon={RefreshCw}
            onClick={() => {
              events.reload();
              actions.reload();
            }}
            loading={events.loading}
          >
            Refresh log
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Events in view"
          value={number(summary.total)}
          icon={ScrollText}
          tone="blue"
          sub="Most recent 200 matching events"
        />
        <StatCard
          label="Distinct actions"
          value={number(summary.uniqueActions)}
          icon={Activity}
          tone="violet"
          sub="Every consequential step is recorded"
        />
        <StatCard
          label="Actors"
          value={number(summary.actors)}
          icon={User}
          tone="slate"
          sub="Owner, system and webhook processes"
        />
        <StatCard
          label="Latest event"
          value={summary.latest ? timeAgo(summary.latest) : "—"}
          icon={CalendarRange}
          tone="green"
          sub={summary.latest ? formatDateTime(summary.latest) : "No events yet"}
        />
      </div>

      <Callout tone="blue" title="Audit guarantees" icon={ShieldCheck}>
        {events.data?.protection_note ||
          "Audit details never include credentials, tokens, passwords or card data."}{" "}
        Approval creation, decisions, executions, webhook outcomes and integration checks all land here.
      </Callout>

      <Card>
        <CardHeader
          title="Filter the trail"
          description="Server-side action and date filters; free-text search spans actor, entity and structured detail."
          icon={Filter}
        />
        <CardBody className="grid gap-3 pt-4 sm:grid-cols-2 xl:grid-cols-5">
          <Field label="Search" htmlFor="audit-search" className="sm:col-span-2 xl:col-span-1">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <Input
                id="audit-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Actor, entity, detail…"
                className="pl-8"
              />
            </div>
          </Field>
          <Field label="Action" htmlFor="audit-action">
            <Select
              id="audit-action"
              value={action}
              onChange={(event) => setAction(event.target.value)}
            >
              <option value="">All actions</option>
              {(actionNames || []).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Entity type" htmlFor="audit-entity">
            <Select
              id="audit-entity"
              value={entityType}
              onChange={(event) => setEntityType(event.target.value)}
            >
              <option value="">All entities</option>
              {entityTypes.map((item) => (
                <option key={item} value={item}>
                  {titleCase(item)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="From" htmlFor="audit-start">
            <Input
              id="audit-start"
              type="date"
              value={start}
              max={end || undefined}
              onChange={(event) => setStart(event.target.value)}
            />
          </Field>
          <div className="flex items-end gap-2">
            <Field label="To" htmlFor="audit-end" className="flex-1">
              <Input
                id="audit-end"
                type="date"
                value={end}
                min={start || undefined}
                onChange={(event) => setEnd(event.target.value)}
              />
            </Field>
            {filtersActive && (
              <Button variant="ghost" size="sm" icon={X} onClick={clearFilters} className="mb-0.5">
                Clear
              </Button>
            )}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Event history"
          description={
            events.data
              ? `${number(events.data.count)} events returned${search ? ` · ${visible.length} match “${search}”` : ""}`
              : "Loading the audit trail…"
          }
          actions={
            <Badge tone="slate">
              <ScrollText className="h-3 w-3" aria-hidden /> Append-only
            </Badge>
          }
        />
        <div className="mt-3">
          {events.loading && !events.data ? (
            <PageSkeleton cards={2} />
          ) : events.error ? (
            <ErrorState message={events.error} onRetry={events.reload} />
          ) : visible.length === 0 ? (
            <EmptyState
              icon={ScrollText}
              title={filtersActive ? "No events match these filters" : "No audit events yet"}
              description={
                filtersActive
                  ? "Try a broader action, entity or date range."
                  : "Actions you take in FINOVEXA will be recorded here."
              }
              action={
                filtersActive ? (
                  <Button variant="outline" size="sm" onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Actor</TH>
                  <TH>Action</TH>
                  <TH>Entity</TH>
                  <TH>Detail</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {visible.map((event) => (
                  <TR key={event.id}>
                    <TD>
                      <p className="text-[11.5px] font-medium text-slate-700">
                        {formatDateTime(event.created_at)}
                      </p>
                      <p className="text-[10px] text-slate-400">{timeAgo(event.created_at)}</p>
                    </TD>
                    <TD>
                      <span className="text-[11.5px] text-slate-600">{event.actor}</span>
                    </TD>
                    <TD>
                      <Badge tone={actionTone(event.action)}>{event.action}</Badge>
                    </TD>
                    <TD>
                      <p className="text-[11px] text-slate-600">
                        {event.entity_type ? titleCase(event.entity_type) : "—"}
                      </p>
                      <p className="font-mono text-[10px] text-slate-400">{event.entity_id || ""}</p>
                    </TD>
                    <TD className="max-w-[280px]">
                      <p className="truncate font-mono text-[10.5px] text-slate-500">
                        {Object.entries(event.detail || {})
                          .slice(0, 3)
                          .map(([key, value]) => {
                            const text =
                              value !== null && typeof value === "object"
                                ? JSON.stringify(value)
                                : String(value ?? "—");
                            return `${key}: ${text.slice(0, 40)}`;
                          })
                          .join(" · ") || "—"}
                      </p>
                    </TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => setSelected(event)}>
                        Inspect
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </div>
      </Card>

      {selected && <EventDetailModal event={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
