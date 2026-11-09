import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ClipboardList, MessageSquare, Plus, Search } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { get, getErrorMessage, patch, post } from "../../lib/api";
import type {
  AccountantOption,
  AccountingClient,
  AccountingTask,
} from "../../lib/accountingTypes";
import type { AccountingServiceKey } from "../../lib/accountingTypes";
import { SERVICE_LABELS, TASK_STATUSES, labelize } from "../../lib/accounting";
import { formatDate, formatDateTime } from "../../lib/utils";
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
  ProgressBar,
  Select,
  Textarea,
} from "../../components/ui";
import { PriorityBadge, StatusBadge } from "../../components/accounting/AccountingUI";

type TaskComment = { id: number; author_label: string; body: string; created_at: string };

export function AccountantTasksPage() {
  const { isSeniorAccountant } = useAuth();
  const [params] = useSearchParams();
  const [tasks, setTasks] = useState<AccountingTask[]>([]);
  const [clients, setClients] = useState<AccountingClient[]>([]);
  const [accountants, setAccountants] = useState<AccountantOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [status, setStatus] = useState(params.get("status") || "");
  const [clientId, setClientId] = useState(params.get("clientId") || "");
  const [overdue, setOverdue] = useState(params.get("overdue") === "1");
  const [assignee, setAssignee] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({
    client_id: params.get("clientId") || "",
    title: "",
    description: "",
    service_type: "bookkeeping" as AccountingServiceKey,
    priority: "normal",
    due_date: "",
    assigned_to_user_id: "",
  });

  const [reviewTask, setReviewTask] = useState<AccountingTask | null>(null);
  const [reviewDecision, setReviewDecision] = useState<"approve" | "changes_requested">("approve");
  const [reviewNotes, setReviewNotes] = useState("");
  const [submitTask, setSubmitTask] = useState<AccountingTask | null>(null);
  const [submitSummary, setSubmitSummary] = useState("");
  const [submitProgress, setSubmitProgress] = useState(100);

  const [commentsTask, setCommentsTask] = useState<AccountingTask | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [commentBody, setCommentBody] = useState("");
  const [commentsLoading, setCommentsLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = new URLSearchParams();
      if (status) query.set("status", status);
      if (isSeniorAccountant) {
        if (clientId) query.set("client_id", clientId);
        if (assignee) query.set("assigned_to_user_id", assignee);
        if (overdue) query.set("overdue", "true");
        const suffix = query.toString();
        const data = await get<{ items: AccountingTask[] }>(
          `/accounting/senior/tasks${suffix ? `?${suffix}` : ""}`,
        );
        setTasks(data.items);
      } else {
        const data = await get<{ items: AccountingTask[] }>(
          `/accounting/junior/tasks${status ? `?status=${status}` : ""}`,
        );
        setTasks(data.items);
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [isSeniorAccountant, status, clientId, assignee, overdue]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (isSeniorAccountant) {
      get<{ items: AccountingClient[] }>("/accounting/senior/clients")
        .then((data) => setClients(data.items))
        .catch(() => setClients([]));
      get<{ items: AccountantOption[] }>("/accounting/senior/accountants")
        .then((data) => setAccountants(data.items))
        .catch(() => setAccountants([]));
    } else {
      get<{ items: AccountingClient[] }>("/accounting/junior/clients")
        .then((data) => setClients(data.items))
        .catch(() => setClients([]));
    }
  }, [isSeniorAccountant]);

  const juniors = useMemo(
    () => accountants.filter((row) => row.role === "junior_accountant"),
    [accountants],
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return tasks;
    return tasks.filter(
      (task) =>
        task.title.toLowerCase().includes(needle) ||
        (task.client_name || "").toLowerCase().includes(needle) ||
        (task.assignee_name || "").toLowerCase().includes(needle),
    );
  }, [tasks, search]);

  const createTask = async () => {
    setBusy(true);
    setActionError(null);
    try {
      await post<AccountingTask>("/accounting/senior/tasks", {
        client_id: Number(form.client_id),
        title: form.title,
        description: form.description || null,
        service_type: form.service_type,
        priority: form.priority,
        due_date: form.due_date || null,
        assigned_to_user_id: form.assigned_to_user_id ? Number(form.assigned_to_user_id) : null,
      });
      setCreateOpen(false);
      setForm({ ...form, title: "", description: "", due_date: "", assigned_to_user_id: "" });
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitReview = async () => {
    if (!reviewTask) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/senior/tasks/${reviewTask.id}/review`, {
        decision: reviewDecision,
        notes: reviewNotes || null,
      });
      setReviewTask(null);
      setReviewNotes("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitForReview = async () => {
    if (!submitTask) return;
    setBusy(true);
    setActionError(null);
    try {
      await post(`/accounting/junior/tasks/${submitTask.id}/submit`, {
        summary: submitSummary,
        progress: submitProgress,
      });
      setSubmitTask(null);
      setSubmitSummary("");
      await load();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openComments = async (task: AccountingTask) => {
    setCommentsTask(task);
    setComments([]);
    setCommentBody("");
    setCommentsLoading(true);
    try {
      const data = await get<{ items: TaskComment[] }>(`/accounting/tasks/${task.id}/comments`);
      setComments(data.items);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setCommentsLoading(false);
    }
  };

  const addComment = async () => {
    if (!commentsTask || commentBody.trim().length < 2) return;
    setBusy(true);
    setActionError(null);
    try {
      const created = await post<TaskComment>(`/accounting/tasks/${commentsTask.id}/comments`, {
        body: commentBody.trim(),
      });
      setComments((rows) => [...rows, created]);
      setCommentBody("");
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reassign = async (task: AccountingTask, userId: string) => {
    setActionError(null);
    try {
      const updated = await patch<AccountingTask>(`/accounting/senior/tasks/${task.id}`, {
        assigned_to_user_id: userId ? Number(userId) : null,
      });
      setTasks((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Workflow"
        title={isSeniorAccountant ? "Tasks and senior review" : "My tasks"}
        description={
          isSeniorAccountant
            ? "Create work, assign it, then approve or send it back. Junior accountants cannot approve their own submissions."
            : "Prepare assigned work and submit it for senior review. Only a senior accountant can approve it."
        }
        actions={
          isSeniorAccountant ? (
            <Button icon={Plus} onClick={() => setCreateOpen(true)}>
              New task
            </Button>
          ) : undefined
        }
      />

      {actionError && (
        <Callout tone="red" title="That action did not complete">
          {actionError}
        </Callout>
      )}

      <div className={`grid gap-3 ${isSeniorAccountant ? "lg:grid-cols-5" : "sm:grid-cols-2"}`}>
        <Field label="Search" htmlFor="task_search" className={isSeniorAccountant ? "lg:col-span-2" : ""}>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              id="task_search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Task, client or assignee"
              className="pl-9"
            />
          </div>
        </Field>
        <Field label="Status" htmlFor="task_status_filter">
          <Select id="task_status_filter" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            {TASK_STATUSES.map((value) => (
              <option key={value} value={value}>
                {labelize(value)}
              </option>
            ))}
          </Select>
        </Field>
        {isSeniorAccountant && (
          <>
            <Field label="Client" htmlFor="task_client_filter">
              <Select
                id="task_client_filter"
                value={clientId}
                onChange={(event) => setClientId(event.target.value)}
              >
                <option value="">All clients</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.business_name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Assignee" htmlFor="task_assignee_filter">
              <Select id="task_assignee_filter" value={assignee} onChange={(event) => setAssignee(event.target.value)}>
                <option value="">Everyone</option>
                {accountants.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </Select>
            </Field>
            <label className="flex items-center gap-2 self-end pb-2 text-[12px] text-slate-600">
              <input
                type="checkbox"
                checked={overdue}
                onChange={(event) => setOverdue(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 accent-brand-500"
              />
              Overdue only
            </label>
          </>
        )}
      </div>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading && tasks.length === 0 ? (
        <PageSkeleton cards={3} />
      ) : visible.length === 0 ? (
        <Card>
          <EmptyState
            title="No tasks in this view"
            description={
              isSeniorAccountant
                ? "Adjust the filters or create a task for an onboarded client."
                : "Tasks assigned to you will appear here."
            }
            icon={ClipboardList}
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {visible.map((task) => (
            <Card key={task.id} hover>
              <div className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-[13px] font-semibold text-ink-900">{task.title}</p>
                      <PriorityBadge priority={task.priority} />
                      <StatusBadge status={task.status} />
                      {task.is_overdue && <Badge tone="red">Overdue</Badge>}
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {task.client_name} ({task.client_code}) ·{" "}
                      {SERVICE_LABELS[task.service_type] || labelize(task.service_type)} ·{" "}
                      {task.assignee_name || "Unassigned"} · due {formatDate(task.due_date)}
                    </p>
                    {task.description && (
                      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{task.description}</p>
                    )}
                    {task.review_notes && (
                      <p className="mt-1 rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-600">
                        Review note: {task.review_notes}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button size="sm" variant="ghost" icon={MessageSquare} onClick={() => void openComments(task)}>
                      Comments
                    </Button>
                    {isSeniorAccountant && task.status === "submitted" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setReviewTask(task);
                          setReviewDecision("approve");
                          setReviewNotes("");
                        }}
                      >
                        Review
                      </Button>
                    )}
                    {!isSeniorAccountant &&
                      ["assigned", "in_progress", "changes_requested"].includes(task.status) && (
                        <Button
                          size="sm"
                          onClick={() => {
                            setSubmitTask(task);
                            setSubmitSummary("");
                            setSubmitProgress(Math.max(50, task.progress));
                          }}
                        >
                          Submit for review
                        </Button>
                      )}
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <ProgressBar value={task.progress} className="max-w-xs flex-1" label={`${task.title} progress`} />
                  <span className="text-[10px] text-slate-400">{task.progress}%</span>
                  {isSeniorAccountant && (
                    <div className="ml-auto w-44">
                      <Select
                        aria-label={`Reassign ${task.title}`}
                        value={task.assigned_to_user_id ?? ""}
                        onChange={(event) => void reassign(task, event.target.value)}
                        className="h-8 text-[11px]"
                      >
                        <option value="">Unassigned</option>
                        {accountants.map((person) => (
                          <option key={person.id} value={person.id}>
                            {person.name}
                          </option>
                        ))}
                      </Select>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
        <Badge tone="slate" dot>
          {visible.length} task{visible.length === 1 ? "" : "s"}
        </Badge>
        <span>Junior accountants cannot approve tasks or final reports.</span>
      </div>

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create a task"
        description="Assign work to a client. Leaving the assignee blank keeps it in the unassigned queue."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button loading={busy} icon={Plus} onClick={createTask} disabled={!form.client_id || form.title.trim().length < 3}>
              Create task
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Client" htmlFor="new_task_client" required>
            <Select
              id="new_task_client"
              value={form.client_id}
              onChange={(event) => setForm({ ...form, client_id: event.target.value })}
            >
              <option value="">Select a client</option>
              {clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.business_name} · {client.code}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Title" htmlFor="new_task_title" required>
            <Input
              id="new_task_title"
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="October bookkeeping close"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Service type" htmlFor="new_task_service">
              <Select
                id="new_task_service"
                value={form.service_type}
                onChange={(event) => setForm({ ...form, service_type: event.target.value as AccountingServiceKey })}
              >
                {Object.entries(SERVICE_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Priority" htmlFor="new_task_priority">
              <Select
                id="new_task_priority"
                value={form.priority}
                onChange={(event) => setForm({ ...form, priority: event.target.value })}
              >
                {["low", "normal", "high", "urgent"].map((value) => (
                  <option key={value} value={value}>
                    {labelize(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Due date" htmlFor="new_task_due">
              <Input
                id="new_task_due"
                type="date"
                value={form.due_date}
                onChange={(event) => setForm({ ...form, due_date: event.target.value })}
              />
            </Field>
            <Field label="Assign to" htmlFor="new_task_assignee">
              <Select
                id="new_task_assignee"
                value={form.assigned_to_user_id}
                onChange={(event) => setForm({ ...form, assigned_to_user_id: event.target.value })}
              >
                <option value="">Leave unassigned</option>
                {juniors.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name} · {person.open_tasks} open tasks
                  </option>
                ))}
                {accountants
                  .filter((person) => person.role !== "junior_accountant")
                  .map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.name} (senior)
                    </option>
                  ))}
              </Select>
            </Field>
          </div>
          <Field label="Instructions" htmlFor="new_task_description">
            <Textarea
              id="new_task_description"
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              placeholder="What good looks like, documents to use, review expectations"
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(reviewTask)}
        onClose={() => setReviewTask(null)}
        title="Senior review"
        description={reviewTask ? `${reviewTask.title} · ${reviewTask.client_name}` : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setReviewTask(null)}>
              Cancel
            </Button>
            <Button
              variant={reviewDecision === "approve" ? "success" : "danger"}
              loading={busy}
              onClick={submitReview}
            >
              {reviewDecision === "approve" ? "Approve work" : "Request changes"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Decision" htmlFor="review_decision">
            <Select
              id="review_decision"
              value={reviewDecision}
              onChange={(event) => setReviewDecision(event.target.value as typeof reviewDecision)}
            >
              <option value="approve">Approve and deliver to client</option>
              <option value="changes_requested">Send back for changes</option>
            </Select>
          </Field>
          <Field label="Review notes" htmlFor="review_notes">
            <Textarea
              id="review_notes"
              value={reviewNotes}
              onChange={(event) => setReviewNotes(event.target.value)}
              placeholder="What was checked, or what must change"
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(submitTask)}
        onClose={() => setSubmitTask(null)}
        title="Submit for senior review"
        description={submitTask ? `${submitTask.title} · ${submitTask.client_name}` : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setSubmitTask(null)}>
              Cancel
            </Button>
            <Button loading={busy} onClick={submitForReview} disabled={submitSummary.trim().length < 5}>
              Submit
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="What was completed?" htmlFor="submit_summary" required>
            <Textarea
              id="submit_summary"
              value={submitSummary}
              onChange={(event) => setSubmitSummary(event.target.value)}
              placeholder="Ledger closed for October, bank reconciled, GST working paper prepared"
            />
          </Field>
          <Field label="Progress" htmlFor="submit_progress">
            <Input
              id="submit_progress"
              type="number"
              min={0}
              max={100}
              value={submitProgress}
              onChange={(event) => setSubmitProgress(Number(event.target.value))}
            />
          </Field>
          <p className="text-[10px] leading-relaxed text-slate-400">
            Submission sends the task to every active senior accountant. It does not approve or deliver anything.
          </p>
        </div>
      </Modal>

      <Modal
        open={Boolean(commentsTask)}
        onClose={() => setCommentsTask(null)}
        title="Task comments"
        description={commentsTask ? `${commentsTask.title} · ${commentsTask.client_name}` : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setCommentsTask(null)}>
              Close
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {commentsLoading ? (
            <p className="text-[11px] text-slate-500">Loading comments…</p>
          ) : comments.length === 0 ? (
            <p className="text-[11px] text-slate-500">No comments yet.</p>
          ) : (
            <ul className="max-h-72 space-y-2 overflow-y-auto">
              {comments.map((comment) => (
                <li key={comment.id} className="rounded-lg border border-slate-200 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] font-semibold text-ink-900">{comment.author_label}</p>
                    <span className="text-[10px] text-slate-400">{formatDateTime(comment.created_at)}</span>
                  </div>
                  <p className="mt-0.5 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-600">{comment.body}</p>
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-end gap-2">
            <Textarea
              value={commentBody}
              onChange={(event) => setCommentBody(event.target.value)}
              placeholder="Add a note for the other accountant"
              className="min-h-[70px]"
            />
            <Button loading={busy} onClick={addComment} disabled={commentBody.trim().length < 2}>
              Add
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
