import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Database,
  Gauge,
  Lock,
  MessageSquare,
  RefreshCw,
  SendHorizontal,
  ShieldCheck,
  Sparkles,
  User,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, post } from "../lib/api";
import type { ChatAnswer, ChatMessage } from "../lib/types";
import { cn, formatDateTime, timeAgo } from "../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  ErrorState,
  PageHeader,
  Skeleton,
  Textarea,
} from "../components/ui";
import { AssistantAnswer } from "../components/ai/AssistantAnswer";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";

interface HistoryResponse {
  items: ChatMessage[];
}

interface ChatResponse {
  answer: ChatAnswer;
  agent_note: string;
}

interface ToolInfo {
  name: string;
  description: string;
  read_only: boolean;
}

interface ToolsResponse {
  items: ToolInfo[];
  policy: string;
}

const SUGGESTIONS = [
  "What is my recorded cash position and minimum reserve?",
  "Which overdue invoice should I prioritise, and why?",
  "Show my 30-day cash forecast and its main assumptions.",
  "Can I afford a ₹75,000 investment above my reserve?",
  "Summarise this month's revenue, expenses and margin.",
  "Which payments are unmatched or look duplicated?",
  "What market headlines are linked to my watchlist?",
  "What actions are waiting for my approval right now?",
];

export function AskPage() {
  const { profile } = useAuth();
  const { toast } = useToast();
  const history = useApi<HistoryResponse>("/ai/history?limit=40");
  const tools = useApi<ToolsResponse>("/ai/tools");
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.data, pending]);

  const send = async (value?: string) => {
    const text = (value ?? question).trim();
    if (text.length < 3 || sending) return;
    setSending(true);
    setError(null);
    setPending(text);
    setQuestion("");
    try {
      await post<ChatResponse>("/ai/chat", { question: text });
      history.reload();
    } catch (err) {
      setError(getErrorMessage(err));
      setQuestion(text);
      toast({ tone: "error", title: "The analyst could not answer", description: getErrorMessage(err) });
    } finally {
      setPending(null);
      setSending(false);
      window.setTimeout(() => inputRef.current?.focus(), 40);
    }
  };

  const messages = history.data?.items || [];
  const isEmpty = !history.loading && messages.length === 0 && !pending;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Central AI orchestrator"
        title="Ask FINOVEXA"
        description="Grounded answers over your own ledger, forecasts and labelled market data — with sources, estimates and uncertainty separated."
        actions={
          <Button
            variant="outline"
            size="sm"
            icon={RefreshCw}
            onClick={() => history.reload()}
            loading={history.loading}
          >
            Refresh thread
          </Button>
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="flex min-h-[620px] flex-col overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-violet-500 text-white">
                <Sparkles className="h-4 w-4" aria-hidden />
              </span>
              <div>
                <p className="text-[13px] font-semibold text-ink-900">FINOVEXA analyst</p>
                <p className="text-[10px] text-slate-400">
                  Read-only tools · Human approval required for any action
                </p>
              </div>
            </div>
            <Badge tone="green" dot>
              Grounded
            </Badge>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-5">
            {history.loading && messages.length === 0 ? (
              <div className="space-y-4">
                <Skeleton className="ml-auto h-16 w-2/3" />
                <Skeleton className="h-40 w-full" />
                <Skeleton className="ml-auto h-12 w-1/2" />
              </div>
            ) : history.error ? (
              <ErrorState message={history.error} onRetry={history.reload} />
            ) : isEmpty ? (
              <div className="mx-auto max-w-xl py-6 text-center">
                <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-violet-500 text-white shadow-lg shadow-brand-500/20">
                  <MessageSquare className="h-6 w-6" aria-hidden />
                </span>
                <h2 className="mt-4 text-lg font-semibold tracking-tight text-ink-900">
                  Ask a question about your business
                </h2>
                <p className="mx-auto mt-1.5 max-w-md text-[13px] leading-relaxed text-slate-500">
                  Answers are built from authorized backend tools. FINOVEXA will not invent a payment,
                  order fill, analyst rating or live price.
                </p>
                <div className="mt-5 grid gap-2 text-left sm:grid-cols-2">
                  {SUGGESTIONS.slice(0, 6).map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => void send(suggestion)}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left text-[12px] leading-relaxed text-slate-600 transition hover:border-brand-300 hover:text-brand-700"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-5">
                {messages.map((message) => {
                  const isUser = message.role === "user";
                  const answer = message.content as Partial<ChatAnswer>;
                  return (
                    <div
                      key={message.id}
                      className={cn("flex gap-3", isUser && "flex-row-reverse")}
                    >
                      <span
                        className={cn(
                          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                          isUser
                            ? "bg-navy-800 text-slate-200"
                            : "bg-gradient-to-br from-brand-500 to-violet-500 text-white",
                        )}
                      >
                        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                      </span>
                      <div className={cn("min-w-0 max-w-[92%]", isUser && "max-w-[80%]")}>
                        <div
                          className={cn(
                            "rounded-xl border px-4 py-3",
                            isUser
                              ? "border-navy-700 bg-navy-900 text-white"
                              : "border-slate-200 bg-white shadow-sm",
                          )}
                        >
                          {isUser ? (
                            <p className="whitespace-pre-wrap text-[13px] leading-relaxed">
                              {message.content.text}
                            </p>
                          ) : (
                            <AssistantAnswer
                              answer={answer}
                              onAsk={(value) => {
                                setQuestion(value);
                                inputRef.current?.focus();
                              }}
                            />
                          )}
                        </div>
                        <div
                          className={cn(
                            "mt-1 flex flex-wrap items-center gap-2 text-[10px] text-slate-400",
                            isUser && "justify-end",
                          )}
                        >
                          <span title={formatDateTime(message.created_at)}>{timeAgo(message.created_at)}</span>
                          {!isUser && message.mode && (
                            <Badge tone={message.mode === "llm" ? "violet" : "slate"}>
                              {message.mode === "llm" ? "LLM-assisted" : "Deterministic analyst"}
                            </Badge>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {pending && (
                  <>
                    <div className="flex flex-row-reverse gap-3">
                      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-navy-800 text-slate-200">
                        <User className="h-3.5 w-3.5" />
                      </span>
                      <div className="max-w-[80%] rounded-xl border border-navy-700 bg-navy-900 px-4 py-3 text-[13px] leading-relaxed text-white">
                        {pending}
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-violet-500 text-white">
                        <Bot className="h-3.5 w-3.5" />
                      </span>
                      <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500 shadow-sm">
                        <span className="flex gap-1">
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.2s]" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.1s]" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400" />
                        </span>
                        Calling authorized read-only tools…
                      </div>
                    </div>
                  </>
                )}

                {error && !pending && (
                  <Callout tone="red" title="Answer failed" icon={AlertTriangle}>
                    {error}
                  </Callout>
                )}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <div className="border-t border-slate-100 bg-slate-50/50 px-4 py-3 sm:px-5">
            <div className="flex items-end gap-2">
              <Textarea
                ref={inputRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send();
                  }
                }}
                placeholder="Ask about cash, receivables, forecasts, markets or approvals…"
                maxLength={1200}
                className="min-h-[52px] resize-none bg-white"
                aria-label="Your question"
                disabled={sending}
              />
              <Button
                onClick={() => void send()}
                loading={sending}
                disabled={question.trim().length < 3}
                icon={SendHorizontal}
                className="h-[52px] px-4"
              >
                Send
              </Button>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
              <span>Enter to send · Shift+Enter for a new line · Answers are not financial advice.</span>
              <span>{question.length}/1200</span>
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title="How this answer is built" icon={ShieldCheck} />
            <CardBody className="space-y-3 pt-3">
              <div className="flex gap-2.5">
                <Database className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden />
                <p className="text-[12px] leading-relaxed text-slate-600">
                  A central orchestrator calls <span className="font-semibold">read-only backend tools</span>{" "}
                  scoped to {profile?.business_name || "your business"}. Tool results are validated before use.
                </p>
              </div>
              <div className="flex gap-2.5">
                <Lock className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden />
                <p className="text-[12px] leading-relaxed text-slate-600">
                  The assistant cannot send reminders, capture payments, change approvals or place orders.
                </p>
              </div>
              <div className="flex gap-2.5">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden />
                <p className="text-[12px] leading-relaxed text-slate-600">
                  News articles and external content are treated as <span className="font-semibold">untrusted data</span>{" "}
                  — never as instructions.
                </p>
              </div>
              <Callout tone="slate">
                Forecasts are estimates. Demo market data is never presented as live.
              </Callout>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Authorized tools"
              description={tools.data?.policy}
              icon={Gauge}
            />
            <CardBody className="pt-3">
              {tools.loading ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <Skeleton key={index} className="h-4 w-full" />
                  ))}
                </div>
              ) : tools.error ? (
                <p className="text-xs text-slate-400">{tools.error}</p>
              ) : (
                <div className="space-y-1.5">
                  {(tools.data?.items || []).map((tool) => (
                    <details key={tool.name} className="group rounded-lg border border-slate-100 bg-slate-50/60">
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-[11.5px] font-medium text-slate-700 [&::-webkit-details-marker]:hidden">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                        <span className="flex-1 truncate font-mono">{tool.name}</span>
                        <Badge tone="green">read-only</Badge>
                      </summary>
                      <p className="border-t border-slate-100 px-2.5 py-2 text-[11px] leading-relaxed text-slate-500">
                        {tool.description}
                      </p>
                    </details>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>

          {!isEmpty && (
            <Card>
              <CardHeader title="Try a follow-up" icon={Sparkles} />
              <CardBody className="flex flex-wrap gap-1.5 pt-3">
                {SUGGESTIONS.slice(2).map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => setQuestion(suggestion)}
                    className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600 transition hover:border-brand-300 hover:text-brand-700"
                  >
                    {suggestion}
                  </button>
                ))}
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
