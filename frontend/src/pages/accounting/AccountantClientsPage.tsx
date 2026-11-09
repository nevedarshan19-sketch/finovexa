import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Building2, Plus, Search, UsersRound } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { get, getErrorMessage, post } from "../../lib/api";
import type {
  AccountantOption,
  AccountingCatalogue,
  AccountingClient,
} from "../../lib/accountingTypes";
import { labelize } from "../../lib/accounting";
import { money } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  Select,
  Textarea,
} from "../../components/ui";
import { StatusBadge } from "../../components/accounting/AccountingUI";

const CLIENT_STATUSES = ["onboarding", "active", "paused", "archived"];

function currentFinancialYear(): string {
  const today = new Date();
  const start = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

interface ClientForm {
  business_name: string;
  contact_name: string;
  email: string;
  phone: string;
  business_type: string;
  turnover_range: string;
  gst_status: string;
  gstin: string;
  pan_last4: string;
  financial_year: string;
  service_package: string;
  assigned_junior_user_id: string;
  portal_password: string;
  notes: string;
}

const emptyForm = (): ClientForm => ({
  business_name: "",
  contact_name: "",
  email: "",
  phone: "",
  business_type: "Proprietorship",
  turnover_range: "Under INR 20 lakh",
  gst_status: "Registered - regular",
  gstin: "",
  pan_last4: "",
  financial_year: currentFinancialYear(),
  service_package: "",
  assigned_junior_user_id: "",
  portal_password: "",
  notes: "",
});

export function AccountantClientsPage() {
  const { isSeniorAccountant } = useAuth();
  const navigate = useNavigate();
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [juniors, setJuniors] = useState<AccountantOption[]>([]);
  const [catalogue, setCatalogue] = useState<AccountingCatalogue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [fy, setFy] = useState("");
  const [juniorId, setJuniorId] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<ClientForm>(emptyForm);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (isSeniorAccountant) {
        const params = new URLSearchParams();
        if (search.trim()) params.set("search", search.trim());
        if (status) params.set("status", status);
        if (fy.trim()) params.set("financial_year", fy.trim());
        if (juniorId) params.set("assigned_junior_user_id", juniorId);
        const query = params.toString();
        const data = await get<{ items: AccountingClient[] }>(
          `/accounting/senior/clients${query ? `?${query}` : ""}`,
        );
        setClients(data.items);
      } else {
        const data = await get<{ items: AccountingClient[] }>("/accounting/junior/clients");
        const needle = search.trim().toLowerCase();
        setClients(
          needle
            ? data.items.filter(
                (row) =>
                  row.business_name.toLowerCase().includes(needle) ||
                  row.code.toLowerCase().includes(needle) ||
                  row.email.toLowerCase().includes(needle),
              )
            : data.items,
        );
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [isSeniorAccountant, search, status, fy, juniorId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    get<AccountingCatalogue>("/accounting/public/services", { auth: false })
      .then(setCatalogue)
      .catch(() => setCatalogue(null));
    if (isSeniorAccountant) {
      get<{ items: AccountantOption[] }>("/accounting/senior/accountants")
        .then((data) => setJuniors(data.items.filter((row) => row.role === "junior_accountant")))
        .catch(() => setJuniors([]));
    }
  }, [isSeniorAccountant]);

  const submit = async () => {
    setBusy(true);
    setFormError(null);
    try {
      const result = await post<{ client: AccountingClient }>("/accounting/senior/clients", {
        business_name: form.business_name,
        contact_name: form.contact_name,
        email: form.email,
        phone: form.phone || null,
        business_type: form.business_type,
        turnover_range: form.turnover_range,
        gst_status: form.gst_status,
        gstin: form.gstin.trim() || null,
        pan_last4: form.pan_last4.trim() || null,
        financial_year: form.financial_year,
        service_package: form.service_package,
        assigned_junior_user_id: form.assigned_junior_user_id ? Number(form.assigned_junior_user_id) : null,
        portal_password: form.portal_password || null,
        notes: form.notes || null,
      });
      setCreateOpen(false);
      setForm(emptyForm());
      navigate(`/accountant/clients/${result.client.id}`);
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Practice register"
        title={isSeniorAccountant ? "Clients" : "My clients"}
        description={
          isSeniorAccountant
            ? "Every onboarded business, its package, assigned accountant and fee position."
            : "Clients you are assigned to work on. Other client records are not visible to you."
        }
        actions={
          isSeniorAccountant ? (
            <Button icon={Plus} onClick={() => setCreateOpen(true)}>
              Onboard client
            </Button>
          ) : undefined
        }
      />

      <div className={`grid gap-3 ${isSeniorAccountant ? "sm:grid-cols-4" : "sm:grid-cols-2"}`}>
        <Field label="Search" htmlFor="client_search">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              id="client_search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Business, code or email"
              className="pl-9"
            />
          </div>
        </Field>
        {isSeniorAccountant && (
          <>
            <Field label="Status" htmlFor="client_status">
              <Select id="client_status" value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="">All statuses</option>
                {CLIENT_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Financial year" htmlFor="client_fy_filter">
              <Input
                id="client_fy_filter"
                value={fy}
                onChange={(event) => setFy(event.target.value)}
                placeholder="e.g. 2026-27"
              />
            </Field>
            <Field label="Assigned to" htmlFor="client_junior_filter">
              <Select
                id="client_junior_filter"
                value={juniorId}
                onChange={(event) => setJuniorId(event.target.value)}
              >
                <option value="">All accountants</option>
                {juniors.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </Select>
            </Field>
          </>
        )}
      </div>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading && clients.length === 0 ? (
        <PageSkeleton cards={3} />
      ) : clients.length === 0 ? (
        <Card>
          <EmptyState
            title="No clients match"
            description={
              isSeniorAccountant
                ? "Accept an enquiry and onboard the business to create the client record."
                : "No client records are assigned to you yet."
            }
            icon={Building2}
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse">
              <thead>
                <tr>
                  <th className="table-head">Client</th>
                  <th className="table-head">Package</th>
                  {isSeniorAccountant && <th className="table-head">Assigned</th>}
                  <th className="table-head">Open tasks</th>
                  {isSeniorAccountant && <th className="table-head">Outstanding</th>}
                  <th className="table-head">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {clients.map((client) => (
                  <tr key={client.id} className="row-hover">
                    <td className="table-cell">
                      <Link
                        to={`/accountant/clients/${client.id}`}
                        className="text-[13px] font-semibold text-ink-900 hover:text-brand-700"
                      >
                        {client.business_name}
                      </Link>
                      {client.linked_business && (
                        <span className="ml-2 align-middle">
                          <Badge tone="blue">Linked</Badge>
                        </span>
                      )}
                      <p className="text-[11px] text-slate-500">
                        {client.code} · {client.email}
                      </p>
                    </td>
                    <td className="table-cell">
                      <p className="text-[12px] text-slate-600">{client.service_package}</p>
                      <p className="text-[10px] text-slate-400">FY {client.financial_year}</p>
                    </td>
                    {isSeniorAccountant && (
                      <td className="table-cell text-[12px] text-slate-600">
                        {client.junior_name || <span className="text-amber-600">Unassigned</span>}
                      </td>
                    )}
                    <td className="table-cell tabular text-[12px] text-slate-600">
                      {client.counts?.open_tasks ?? 0}
                    </td>
                    {isSeniorAccountant && (
                      <td className="table-cell tabular text-[12px]">
                        <span className={(client.billing?.outstanding ?? 0) > 0 ? "text-amber-700" : "text-slate-600"}>
                          {money(client.billing?.outstanding ?? 0)}
                        </span>
                      </td>
                    )}
                    <td className="table-cell">
                      <StatusBadge status={client.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <Badge tone="slate" dot>
          {clients.length} client{clients.length === 1 ? "" : "s"} in this view
        </Badge>
        <span className="inline-flex items-center gap-1">
          <UsersRound className="h-3 w-3" aria-hidden /> PAN is stored as last four characters only.
        </span>
      </div>

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Onboard a client"
        description="Create the engagement record without an enquiry. Email enquiries follow the quotation flow."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button loading={busy} onClick={submit} disabled={!form.business_name || !form.contact_name || !form.email || !form.service_package}>
              Create client
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {formError && (
            <Callout tone="red" title="Could not create the client">
              {formError}
            </Callout>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Business name" htmlFor="new_business_name" required>
              <Input
                id="new_business_name"
                value={form.business_name}
                onChange={(event) => setForm({ ...form, business_name: event.target.value })}
              />
            </Field>
            <Field label="Contact name" htmlFor="new_contact_name" required>
              <Input
                id="new_contact_name"
                value={form.contact_name}
                onChange={(event) => setForm({ ...form, contact_name: event.target.value })}
              />
            </Field>
            <Field label="Email" htmlFor="new_client_email" required>
              <Input
                id="new_client_email"
                type="email"
                value={form.email}
                onChange={(event) => setForm({ ...form, email: event.target.value })}
              />
            </Field>
            <Field label="Phone" htmlFor="new_client_phone">
              <Input
                id="new_client_phone"
                value={form.phone}
                onChange={(event) => setForm({ ...form, phone: event.target.value })}
              />
            </Field>
            <Field label="Business type" htmlFor="new_business_type">
              <Select
                id="new_business_type"
                value={form.business_type}
                onChange={(event) => setForm({ ...form, business_type: event.target.value })}
              >
                {(catalogue?.business_types || [form.business_type]).map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Annual turnover" htmlFor="new_turnover">
              <Select
                id="new_turnover"
                value={form.turnover_range}
                onChange={(event) => setForm({ ...form, turnover_range: event.target.value })}
              >
                {(catalogue?.turnover_ranges || [form.turnover_range]).map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="GST status" htmlFor="new_gst_status">
              <Select
                id="new_gst_status"
                value={form.gst_status}
                onChange={(event) => setForm({ ...form, gst_status: event.target.value })}
              >
                {(catalogue?.gst_statuses || [form.gst_status]).map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="GSTIN" htmlFor="new_gstin" hint="Optional; validated by the server.">
              <Input
                id="new_gstin"
                value={form.gstin}
                onChange={(event) => setForm({ ...form, gstin: event.target.value.toUpperCase() })}
                maxLength={15}
              />
            </Field>
            <Field label="PAN last 4" htmlFor="new_pan" hint="Only these four characters are stored.">
              <Input
                id="new_pan"
                value={form.pan_last4}
                onChange={(event) => setForm({ ...form, pan_last4: event.target.value.toUpperCase() })}
                maxLength={4}
              />
            </Field>
            <Field label="Financial year" htmlFor="new_fy" required>
              <Input
                id="new_fy"
                value={form.financial_year}
                onChange={(event) => setForm({ ...form, financial_year: event.target.value })}
                placeholder="2026-27"
              />
            </Field>
          </div>
          <Field label="Service package" htmlFor="new_package" required>
            <Input
              id="new_package"
              value={form.service_package}
              onChange={(event) => setForm({ ...form, service_package: event.target.value })}
              placeholder="Bookkeeping + GST working papers"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Assign junior accountant" htmlFor="new_junior">
              <Select
                id="new_junior"
                value={form.assigned_junior_user_id}
                onChange={(event) => setForm({ ...form, assigned_junior_user_id: event.target.value })}
              >
                <option value="">Assign later</option>
                {juniors.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name} · {person.open_tasks} open tasks
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Client portal password"
              htmlFor="new_portal_password"
              hint="Leave blank to skip the customer login. Minimum 10 characters."
            >
              <Input
                id="new_portal_password"
                type="password"
                autoComplete="new-password"
                value={form.portal_password}
                onChange={(event) => setForm({ ...form, portal_password: event.target.value })}
              />
            </Field>
          </div>
          <Field label="Internal notes" htmlFor="new_client_notes">
            <Textarea
              id="new_client_notes"
              value={form.notes}
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
