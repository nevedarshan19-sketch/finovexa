import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  BadgeCheck,
  Building2,
  CheckCircle2,
  Inbox,
  Search,
  XCircle,
} from "lucide-react";
import { get, getErrorMessage, patch, post } from "../../lib/api";
import type {
  AccountantOption,
  AccountingClient,
  AccountingEnquiry,
  AccountingQuotation,
} from "../../lib/accountingTypes";
import type { AccountingServiceKey } from "../../lib/accountingTypes";
import { SERVICE_LABELS, cadenceLabel, labelize, serviceLabel, statusTone } from "../../lib/accounting";
import { formatDate, money, timeAgo } from "../../lib/utils";
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
  Textarea,
} from "../../components/ui";
import { StatusBadge } from "../../components/accounting/AccountingUI";

type EnquiryWithQuotes = AccountingEnquiry & { quotations: AccountingQuotation[] };

const STATUSES = ["new", "contacted", "quoted", "quote_accepted", "onboarded", "declined"];

function currentFinancialYear(): string {
  const today = new Date();
  const start = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

export function AccountantEnquiriesPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<EnquiryWithQuotes[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [decision, setDecision] = useState<{ quotation: AccountingQuotation; value: "accepted" | "declined" } | null>(null);
  const [decisionNote, setDecisionNote] = useState("");

  const [accountants, setAccountants] = useState<AccountantOption[]>([]);
  const [onboardFor, setOnboardFor] = useState<{ enquiry: EnquiryWithQuotes; quotation: AccountingQuotation | null } | null>(null);
  const [clientForm, setClientForm] = useState({
    financial_year: currentFinancialYear(),
    service_package: "",
    assigned_junior_user_id: "",
    gstin: "",
    pan_last4: "",
    portal_password: "",
    notes: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (search.trim()) params.set("search", search.trim());
      const query = params.toString();
      const data = await get<{ items: EnquiryWithQuotes[] }>(
        `/accounting/senior/enquiries${query ? `?${query}` : ""}`,
      );
      setItems(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [search, status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    get<{ items: AccountantOption[] }>("/accounting/senior/accountants")
      .then((data) => setAccountants(data.items.filter((row) => row.role === "junior_accountant")))
      .catch(() => setAccountants([]));
  }, []);

  const selected = items.find((row) => row.id === selectedId) || null;
  const juniors = useMemo(() => accountants, [accountants]);

  const updateStatus = async (enquiry: EnquiryWithQuotes, nextStatus: string, notes?: string) => {
    setActionError(null);
    try {
      const updated = await patch<AccountingEnquiry>(`/accounting/senior/enquiries/${enquiry.id}`, {
        status: nextStatus,
        internal_notes: notes ?? enquiry.internal_notes ?? undefined,
      });
      setItems((rows) => rows.map((row) => (row.id === updated.id ? { ...row, ...updated } : row)));
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const submitDecision = async () => {
    if (!decision) return;
    setBusy(true);
    setActionError(null);
    try {
      await post<AccountingQuotation>(`/accounting/senior/quotations/${decision.quotation.id}/decision`, {
        decision: decision.value,
        note: decisionNote || null,
      });
      setDecision(null);
      setDecisionNote("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openOnboard = (enquiry: EnquiryWithQuotes, quotation: AccountingQuotation | null) => {
    setClientForm({
      financial_year: currentFinancialYear(),
      service_package: enquiry.services.map((key) => SERVICE_LABELS[key]).join(", ").slice(0, 80),
      assigned_junior_user_id: "",
      gstin: "",
      pan_last4: "",
      portal_password: "",
      notes: "",
    });
    setActionError(null);
    setOnboardFor({ enquiry, quotation });
  };

  const submitOnboard = async () => {
    if (!onboardFor) return;
    const { enquiry, quotation } = onboardFor;
    setBusy(true);
    setActionError(null);
    try {
      const result = await post<{ client: AccountingClient }>("/accounting/senior/clients", {
        enquiry_id: enquiry.id,
        quotation_id: quotation?.id ?? null,
        business_name: enquiry.business_name,
        contact_name: enquiry.contact_name,
        email: enquiry.email,
        phone: enquiry.phone,
        business_type: enquiry.business_type,
        turnover_range: enquiry.turnover_range,
        gst_status: enquiry.gst_status,
        gstin: clientForm.gstin.trim() || null,
        pan_last4: clientForm.pan_last4.trim() || null,
        financial_year: clientForm.financial_year,
        service_package: clientForm.service_package,
        assigned_junior_user_id: clientForm.assigned_junior_user_id
          ? Number(clientForm.assigned_junior_user_id)
          : null,
        portal_password: clientForm.portal_password || null,
        notes: clientForm.notes || null,
      });
      setOnboardFor(null);
      navigate(`/accountant/clients/${result.client.id}`);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Practice pipeline"
        title="Enquiries and quotations"
        description="Review website enquiries, record the written quotation and onboard the client only after they accept."
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      <div className="grid gap-3 sm:grid-cols-[1fr_200px_auto]">
        <Field label="Search" htmlFor="enquiry_search">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              id="enquiry_search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Business, contact, email or reference"
              className="pl-9"
            />
          </div>
        </Field>
        <Field label="Status" htmlFor="enquiry_status">
          <Select id="enquiry_status" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {labelize(value)}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex items-end">
          <Button variant="outline" onClick={load} loading={loading}>
            Refresh
          </Button>
        </div>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading && items.length === 0 ? (
        <PageSkeleton cards={3} />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            title="No enquiries match"
            description="New enquiries from the Accounting Services page appear here."
            icon={Inbox}
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Card className="overflow-hidden">
            <CardHeader
              title={`${items.length} enquir${items.length === 1 ? "y" : "ies"}`}
              description="Select an enquiry to review the scope, quote and onboarding actions."
              icon={Inbox}
            />
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head">Enquiry</th>
                    <th className="table-head">Services</th>
                    <th className="table-head">Received</th>
                    <th className="table-head">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((enquiry) => (
                    <tr
                      key={enquiry.id}
                      onClick={() => setSelectedId(enquiry.id)}
                      className={
                        selectedId === enquiry.id
                          ? "cursor-pointer bg-brand-50/60"
                          : "row-hover cursor-pointer"
                      }
                    >
                      <td className="table-cell">
                        <p className="text-[13px] font-semibold text-ink-900">{enquiry.business_name}</p>
                        <p className="text-[11px] text-slate-500">
                          {enquiry.reference} · {enquiry.contact_name}
                        </p>
                      </td>
                      <td className="table-cell">
                        <div className="flex max-w-[240px] flex-wrap gap-1">
                          {enquiry.services.slice(0, 3).map((key) => (
                            <Badge key={key} tone="slate">
                              {serviceLabel(key)}
                            </Badge>
                          ))}
                          {enquiry.services.length > 3 && (
                            <Badge tone="slate">+{enquiry.services.length - 3}</Badge>
                          )}
                        </div>
                      </td>
                      <td className="table-cell whitespace-nowrap text-[12px] text-slate-500">
                        {timeAgo(enquiry.created_at)}
                      </td>
                      <td className="table-cell">
                        <StatusBadge status={enquiry.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card>
            {!selected ? (
              <EmptyState
                title="Select an enquiry"
                description="Open a row to see contact details, volume and quotation history."
                icon={Building2}
              />
            ) : (
              <>
                <CardHeader
                  title={selected.business_name}
                  description={`${selected.reference} · received ${formatDate(selected.created_at)}`}
                  actions={<StatusBadge status={selected.status} />}
                />
                <CardBody className="space-y-4 text-[12px]">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-slate-400">Contact</p>
                      <p className="font-medium text-ink-900">{selected.contact_name}</p>
                      <p className="break-all text-slate-500">{selected.email}</p>
                      {selected.phone && <p className="text-slate-500">{selected.phone}</p>}
                    </div>
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-slate-400">Business</p>
                      <p className="text-slate-600">{labelize(selected.business_type)}</p>
                      <p className="text-slate-600">{selected.turnover_range}</p>
                      <p className="text-slate-600">GST: {labelize(selected.gst_status)}</p>
                    </div>
                  </div>

                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-slate-400">Requested services</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {selected.services.map((key) => (
                        <Badge key={key} tone="blue">
                          {serviceLabel(key)}
                        </Badge>
                      ))}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-slate-400">Monthly transactions</p>
                      <p className="text-slate-600">{selected.monthly_transactions ?? "Not stated"}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-slate-400">Source</p>
                      <p className="text-slate-600">{labelize(selected.source)}</p>
                    </div>
                  </div>

                  {selected.requirements && (
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-slate-400">Requirements</p>
                      <p className="mt-1 whitespace-pre-wrap leading-relaxed text-slate-600">{selected.requirements}</p>
                    </div>
                  )}

                  <Field label="Pipeline status" htmlFor="enquiry_status_update">
                    <Select
                      id="enquiry_status_update"
                      value={selected.status}
                      onChange={(event) => void updateStatus(selected, event.target.value)}
                    >
                      {STATUSES.map((value) => (
                        <option key={value} value={value}>
                          {labelize(value)}
                        </option>
                      ))}
                    </Select>
                  </Field>

                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <p className="text-[10px] uppercase tracking-wide text-slate-400">Quotations</p>
                      <Link
                        to={`/accountant/quotations?enquiry=${selected.id}`}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-semibold text-slate-700 transition hover:border-brand-300 hover:text-brand-700"
                      >
                        Prepare quotation
                      </Link>
                    </div>
                    {selected.quotations.length === 0 ? (
                      <p className="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-[11px] text-slate-500">
                        No quotation yet. Draft, approve and send from the Quotations workspace. A senior
                        accountant must approve the final fee before the customer can see it.
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {selected.quotations.map((quotation) => (
                          <li key={quotation.id} className="rounded-lg border border-slate-200 p-2.5">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[12px] font-semibold text-ink-900">{quotation.number}</p>
                              <Badge tone={statusTone(quotation.status)}>{labelize(quotation.status)}</Badge>
                            </div>
                            <div className="mt-0.5 flex flex-wrap items-center justify-between gap-1 text-[11px] text-slate-500">
                              <span>
                                {money(quotation.total_annual)} annual ·{" "}
                                {money(quotation.amount)} {cadenceLabel(quotation.billing_cadence)}
                                {quotation.valid_until ? ` · valid to ${formatDate(quotation.valid_until)}` : ""}
                              </span>
                              <Link
                                to={`/accountant/quotations?quotation=${quotation.id}`}
                                className="font-semibold text-brand-600 hover:underline"
                              >
                                Open
                              </Link>
                            </div>
                            {quotation.scope.length > 0 && (
                              <p className="mt-1 text-[10px] text-slate-400">
                                {quotation.scope.map((row) => serviceLabel(row.service)).join(" · ")}
                              </p>
                            )}
                            {quotation.status === "sent" && (
                              <div className="mt-2 flex gap-1.5">
                                <Button
                                  size="sm"
                                  variant="success"
                                  icon={CheckCircle2}
                                  onClick={() => {
                                    setDecision({ quotation, value: "accepted" });
                                    setDecisionNote("");
                                  }}
                                >
                                  Record acceptance
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  icon={XCircle}
                                  onClick={() => {
                                    setDecision({ quotation, value: "declined" });
                                    setDecisionNote("");
                                  }}
                                >
                                  Record decline
                                </Button>
                              </div>
                            )}
                            {(quotation.status === "accepted" || selected.status === "quote_accepted") && (
                              <Button
                                size="sm"
                                className="mt-2"
                                icon={BadgeCheck}
                                onClick={() => openOnboard(selected, quotation)}
                              >
                                Onboard client
                              </Button>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {selected.status === "quote_accepted" && selected.quotations.length === 0 && (
                    <Button size="sm" icon={BadgeCheck} onClick={() => openOnboard(selected, null)}>
                      Onboard client
                    </Button>
                  )}
                </CardBody>
              </>
            )}
          </Card>
        </div>
      )}

      <Modal
        open={Boolean(decision)}
        onClose={() => setDecision(null)}
        title={decision?.value === "accepted" ? "Record customer acceptance" : "Record customer decline"}
        description={decision ? `${decision.quotation.number} · ${money(decision.quotation.amount)}` : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setDecision(null)}>
              Cancel
            </Button>
            <Button
              variant={decision?.value === "accepted" ? "success" : "danger"}
              loading={busy}
              onClick={submitDecision}
            >
              Record {decision?.value === "accepted" ? "acceptance" : "decline"}
            </Button>
          </>
        }
      >
        <Field label="Note" htmlFor="decision_note" hint="Recorded on the quotation and in the audit trail.">
          <Textarea
            id="decision_note"
            value={decisionNote}
            onChange={(event) => setDecisionNote(event.target.value)}
            placeholder="Where and how the customer responded"
          />
        </Field>
      </Modal>

      <Modal
        open={Boolean(onboardFor)}
        onClose={() => setOnboardFor(null)}
        title="Onboard client"
        description={onboardFor ? `${onboardFor.enquiry.business_name} · ${onboardFor.enquiry.reference}` : undefined}
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setOnboardFor(null)}>
              Cancel
            </Button>
            <Button icon={BadgeCheck} loading={busy} onClick={submitOnboard} disabled={!clientForm.service_package}>
              Create client record
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Callout tone="blue" title="Isolated from day one">
            The client record is linked to a customer login only for this email. Their documents, tasks and
            invoices are visible only to them and to the practice staff who work on them.
          </Callout>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Financial year" htmlFor="client_fy" required>
              <Input
                id="client_fy"
                value={clientForm.financial_year}
                onChange={(event) => setClientForm({ ...clientForm, financial_year: event.target.value })}
                placeholder="2026-27"
              />
            </Field>
            <Field label="Assigned junior accountant" htmlFor="client_junior">
              <Select
                id="client_junior"
                value={clientForm.assigned_junior_user_id}
                onChange={(event) => setClientForm({ ...clientForm, assigned_junior_user_id: event.target.value })}
              >
                <option value="">Assign later</option>
                {juniors.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name} · {person.open_tasks} open tasks
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Service package description" htmlFor="client_package" required>
            <Input
              id="client_package"
              value={clientForm.service_package}
              onChange={(event) => setClientForm({ ...clientForm, service_package: event.target.value })}
              placeholder="Bookkeeping + GST working papers"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="GSTIN" htmlFor="client_gstin" hint="Optional. Validated by the server when supplied.">
              <Input
                id="client_gstin"
                value={clientForm.gstin}
                onChange={(event) => setClientForm({ ...clientForm, gstin: event.target.value.toUpperCase() })}
                placeholder="27ABCDE1234F1Z5"
                maxLength={15}
              />
            </Field>
            <Field label="PAN last 4" htmlFor="client_pan" hint="Only the last four characters are stored.">
              <Input
                id="client_pan"
                value={clientForm.pan_last4}
                onChange={(event) => setClientForm({ ...clientForm, pan_last4: event.target.value.toUpperCase() })}
                placeholder="1234"
                maxLength={4}
              />
            </Field>
          </div>
          <Field
            label="Client portal password"
            htmlFor="client_portal_password"
            hint="Leave blank to skip creating a login. Minimum 10 characters if supplied."
          >
            <Input
              id="client_portal_password"
              type="password"
              value={clientForm.portal_password}
              onChange={(event) => setClientForm({ ...clientForm, portal_password: event.target.value })}
              autoComplete="new-password"
            />
          </Field>
          <Field label="Internal notes" htmlFor="client_notes">
            <Textarea
              id="client_notes"
              value={clientForm.notes}
              onChange={(event) => setClientForm({ ...clientForm, notes: event.target.value })}
              placeholder="Scope agreed, exclusions, contact preferences"
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
