import { useCallback, useEffect, useMemo, useState } from "react";
import { FileClock, History, Search, ShieldCheck } from "lucide-react";
import { get, getErrorMessage } from "../../lib/api";
import type { AccountingClient, AuditRow } from "../../lib/accountingTypes";
import { labelize } from "../../lib/accounting";
import { formatDateTime } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  PageSkeleton,
  Select,
  StatCard,
} from "../../components/ui";

function actionTone(action: string): "blue" | "green" | "amber" | "red" | "slate" | "violet" {
  if (action.includes("approved") || action.includes("delivered") || action.includes("verified")) return "green";
  if (action.includes("rejected") || action.includes("changes_requested") || action.includes("declined")) return "red";
  if (action.includes("review") || action.includes("submitted")) return "amber";
  if (action.includes("document")) return "violet";
  if (action.includes("report")) return "blue";
  return "slate";
}

export function AccountantAuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clientFilter, setClientFilter] = useState("");
  const [limit, setLimit] = useState("150");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (clientFilter) params.set("client_id", clientFilter);
      params.set("limit", limit);
      const data = await get<{ items: AuditRow[] }>(`/accounting/senior/audit?${params.toString()}`);
      setRows(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [clientFilter, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    get<{ items: AccountingClient[] }>("/accounting/senior/clients")
      .then((data) => setClients(data.items))
      .catch(() => setClients([]));
  }, []);

  const clientName = useMemo(() => {
    const map = new Map(clients.map((client) => [client.id, client.business_name]));
    return (detail: Record<string, unknown>, entityType: string | null, entityId: string | null) => {
      const id = num(detail.client_id) ?? (entityType === "accounting_client" ? num(entityId) : null);
      if (id === null) return "—";
      return map.get(id) || `Client #${id}`;
    };
  }, [clients]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => {
      const haystack = [row.actor, row.action, row.entity_type, row.entity_id, JSON.stringify(row.detail)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [rows, search]);

  const counts = useMemo(
    () => ({
      total: filtered.length,
      approvals: filtered.filter((row) => /approved|delivered|verified/.test(row.action)).length,
      reviews: filtered.filter((row) => /review|changes_requested|submitted/.test(row.action)).length,
      documents: filtered.filter((row) => row.action.includes("document")).length,
    }),
    [filtered],
  );

  if (loading && rows.length === 0) return <PageSkeleton cards={4} />;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Accountability"
        title="Audit trail"
        description="Every accounting action is recorded with the actor, entity and timestamp. This log is append-only and visible to senior accountants only."
      />

      <Callout tone="blue" icon={ShieldCheck} title="What is recorded">
        Enquiries, quotations, onboarding, task assignment and review, document verification, report
        approval and delivery, invoices, payments and Tally imports. Passwords and full client financial
        records are never written to this log.
      </Callout>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Events shown" value={counts.total} icon={History} tone="blue" />
        <StatCard label="Approvals" value={counts.approvals} icon={ShieldCheck} tone="green" />
        <StatCard label="Reviews" value={counts.reviews} icon={FileClock} tone="amber" />
        <StatCard label="Documents" value={counts.documents} icon={FileClock} tone="violet" />
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          title="Accounting events"
          description="Filter by client or search the actor, action and detail fields."
          icon={FileClock}
          actions={
            <>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
                <Input
                  aria-label="Search audit events"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search events"
                  className="h-8 w-[190px] pl-8 text-[11px]"
                />
              </div>
              <Select
                aria-label="Client"
                value={clientFilter}
                onChange={(event) => setClientFilter(event.target.value)}
                className="h-8 min-w-[170px] text-[11px]"
              >
                <option value="">All clients</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.business_name}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Event limit"
                value={limit}
                onChange={(event) => setLimit(event.target.value)}
                className="h-8 min-w-[110px] text-[11px]"
              >
                {["50", "100", "150", "300"].map((value) => (
                  <option key={value} value={value}>
                    Last {value}
                  </option>
                ))}
              </Select>
              <Button size="sm" variant="outline" onClick={() => void load()}>
                Refresh
              </Button>
            </>
          }
        />
        <CardBody className="pt-0">
          {error ? (
            <ErrorState message={error} onRetry={load} />
          ) : filtered.length === 0 ? (
            <EmptyState
              title="No events match"
              description="Adjust the client filter or search term to see recorded accounting activity."
              icon={History}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head">When</th>
                    <th className="table-head">Actor</th>
                    <th className="table-head">Action</th>
                    <th className="table-head">Client</th>
                    <th className="table-head">Entity</th>
                    <th className="table-head"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filtered.map((row) => (
                    <tr key={row.id} className="row-hover align-top">
                      <td className="table-cell whitespace-nowrap text-[11px] text-slate-500">
                        {formatDateTime(row.created_at)}
                      </td>
                      <td className="table-cell text-[11px] font-medium text-slate-700">{row.actor}</td>
                      <td className="table-cell">
                        <Badge tone={actionTone(row.action)}>{labelize(row.action.replace(/^accounting\./, ""))}</Badge>
                      </td>
                      <td className="table-cell text-[11px] text-slate-600">
                        {clientName(row.detail, row.entity_type, row.entity_id)}
                      </td>
                      <td className="table-cell text-[11px] text-slate-500">
                        {row.entity_type ? `${labelize(row.entity_type)}${row.entity_id ? ` #${row.entity_id}` : ""}` : "—"}
                      </td>
                      <td className="table-cell">
                        {Object.keys(row.detail || {}).length > 0 && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                          >
                            {expanded === row.id ? "Hide" : "Detail"}
                          </Button>
                        )}
                        {expanded === row.id && (
                          <pre className="mt-2 max-w-[320px] whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50 p-2 text-[10px] leading-relaxed text-slate-600">
                            {JSON.stringify(row.detail, null, 2)}
                          </pre>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}
