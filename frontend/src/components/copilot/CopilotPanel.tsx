import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Bot,
  CornerDownLeft,
  Loader2,
  SendHorizontal,
  ShieldCheck,
  Sparkles,
  User,
  X,
} from "lucide-react";
import { useApi } from "../../hooks/useApi";
import { getErrorMessage, post } from "../../lib/api";
import type { ChatAnswer, ChatMessage } from "../../lib/types";
import { cn, formatDateTime, timeAgo } from "../../lib/utils";
import { Badge, Callout, Skeleton } from "../ui";
import { AssistantAnswer } from "../ai/AssistantAnswer";
import { BrandMark } from "../BrandLogo";

interface HistoryResponse {
  items: ChatMessage[];
}

interface ChatResponse {
  answer: ChatAnswer;
  agent_note: string;
}

const COPILOT_QUESTIONS = [
  "How is my business performing?",
  "Which products need restocking?",
  "What payments are overdue?",
  "What are my biggest expenses?",
  "Generate a monthly business report.",
];

export function CopilotPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const history = useApi<HistoryResponse>(open ? "/ai/history?limit=24" : null);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 120);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(timer);
    };
  }, [open, onClose]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.data, pending, open]);

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
    } finally {
      setPending(null);
      setSending(false);
    }
  };

  if (!open) return null;
  const messages = history.data?.items || [];
  const isEmpty = !history.loading && messages.length === 0 && !pending;

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        aria-label="Close copilot"
        className="absolute inset-0 bg-navy-950/50 backdrop-blur-[2px] animate-fade-in"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="FINOVEXA AI copilot"
        className="absolute inset-y-0 right-0 flex w-full max-w-[420px] animate-slide-in-right flex-col border-l border-[color:var(--border)] bg-[var(--surface)] shadow-pop"
      >
        <header className="flex items-center gap-3 border-b border-[color:var(--border)] px-4 py-3.5">
          <BrandMark className="h-9 w-9" />
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 text-[13px] font-semibold text-ink-900">
              FINOVEXA Copilot
              <Sparkles className="h-3.5 w-3.5 text-brand-500" aria-hidden />
            </p>
            <p className="flex items-center gap-1 text-[10px] text-slate-400">
              <ShieldCheck className="h-3 w-3 text-emerald-500" aria-hidden />
              Read-only business tools · approval required for actions
            </p>
          </div>
          <Link
            to="/ask"
            onClick={onClose}
            className="hidden items-center gap-1 rounded-lg border border-[color:var(--border)] px-2 py-1 text-[10px] font-semibold text-slate-500 transition hover:text-brand-600 sm:inline-flex"
          >
            Full view <ArrowUpRight className="h-3 w-3" />
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-[var(--surface-2)] hover:text-[var(--text-1)]"
            aria-label="Close copilot"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {history.loading && messages.length === 0 ? (
            <div className="space-y-3">
              <Skeleton className="ml-auto h-12 w-2/3" />
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-16 w-5/6" />
            </div>
          ) : history.error ? (
            <Callout tone="red" title="Copilot unavailable">
              {history.error}
            </Callout>
          ) : isEmpty ? (
            <div className="space-y-4">
              <div className="rounded-2xl border border-[color:var(--border)] bg-[var(--surface-2)] p-4">
                <p className="text-[13px] font-semibold text-ink-900">Ask about your own records</p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">
                  Answers are built from authorized, read-only backend tools. FINOVEXA will never
                  invent a payment, price or order fill.
                </p>
              </div>
              <div className="space-y-1.5">
                {COPILOT_QUESTIONS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => void send(item)}
                    className="flex w-full items-center justify-between gap-2 rounded-xl border border-[color:var(--border)] bg-[var(--surface)] px-3 py-2.5 text-left text-[12px] text-slate-600 transition hover:border-brand-300 hover:text-brand-700"
                  >
                    {item}
                    <ArrowUpRight className="h-3.5 w-3.5 shrink-0 opacity-50" aria-hidden />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message) => {
                const isUser = message.role === "user";
                return (
                  <div key={message.id} className={cn("flex gap-2.5", isUser && "flex-row-reverse")}>
                    <span
                      className={cn(
                        "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                        isUser ? "bg-navy-800 text-slate-200" : "bg-brand-500/15 text-brand-600",
                      )}
                    >
                      {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                    </span>
                    <div className={cn("min-w-0 max-w-[88%]", isUser && "max-w-[80%]")}>
                      <div
                        className={cn(
                          "rounded-2xl border px-3.5 py-2.5",
                          isUser
                            ? "border-navy-700 bg-navy-900 text-[12.5px] leading-relaxed text-white"
                            : "border-[color:var(--border)] bg-[var(--surface)]",
                        )}
                      >
                        {isUser ? (
                          <p className="whitespace-pre-wrap">{String(message.content.text || "")}</p>
                        ) : (
                          <AssistantAnswer
                            answer={message.content as Partial<ChatAnswer>}
                            compact
                            onAsk={(value) => {
                              setQuestion(value);
                              inputRef.current?.focus();
                            }}
                          />
                        )}
                      </div>
                      <p className={cn("mt-1 text-[10px] text-slate-400", isUser && "text-right")}>
                        {timeAgo(message.created_at)}
                        {!isUser && message.mode ? ` · ${message.mode === "llm" ? "LLM-assisted" : "deterministic"}` : ""}
                      </p>
                    </div>
                  </div>
                );
              })}

              {pending && (
                <>
                  <div className="flex flex-row-reverse gap-2.5">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-navy-800 text-slate-200">
                      <User className="h-3.5 w-3.5" />
                    </span>
                    <div className="max-w-[80%] rounded-2xl border border-navy-700 bg-navy-900 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-white">
                      {pending}
                    </div>
                  </div>
                  <div className="flex gap-2.5">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-500/15 text-brand-600">
                      <Bot className="h-3.5 w-3.5" />
                    </span>
                    <div className="flex items-center gap-2 rounded-2xl border border-[color:var(--border)] bg-[var(--surface)] px-3.5 py-2.5 text-[11.5px] text-slate-500">
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-brand-500" aria-hidden />
                      Reading authorized ledger tools…
                    </div>
                  </div>
                </>
              )}

              {error && !pending && (
                <Callout tone="red" title="Answer failed">
                  {error}
                </Callout>
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <div className="border-t border-[color:var(--border)] bg-[var(--surface-2)]/60 px-3 py-3">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
              rows={2}
              maxLength={1200}
              placeholder="Ask about cash, dues, stock, margins…"
              aria-label="Ask the copilot"
              disabled={sending}
              className="input-base min-h-[46px] resize-none py-2 text-[12.5px]"
            />
            <button
              type="button"
              onClick={() => void send()}
              disabled={sending || question.trim().length < 3}
              className="flex h-[46px] w-[46px] shrink-0 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#1f6feb,#0ea5b7)] text-white shadow-[0_10px_22px_-14px_rgba(31,111,235,0.95)] transition hover:brightness-110 disabled:opacity-50"
              aria-label="Send question"
            >
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizontal className="h-4 w-4" />}
            </button>
          </div>
          <p className="mt-1.5 flex items-center gap-1 text-[10px] text-slate-400">
            <CornerDownLeft className="h-3 w-3" aria-hidden /> Enter to send · answers are not financial advice
          </p>
        </div>
      </aside>
    </div>
  );
}

export function CopilotLauncher({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group fixed bottom-[86px] right-4 z-30 flex items-center gap-2 rounded-full bg-[linear-gradient(135deg,#1f6feb,#0ea5b7)] px-4 py-3 text-[12px] font-semibold text-white shadow-[0_18px_36px_-16px_rgba(31,111,235,0.9)] transition hover:brightness-110 lg:bottom-6 lg:right-6"
      aria-label="Open FINOVEXA copilot"
    >
      <span className="relative flex h-5 w-5 items-center justify-center">
        <Sparkles className="h-4 w-4" aria-hidden />
      </span>
      <span className="hidden sm:inline">Ask Copilot</span>
      <span className="sm:hidden">AI</span>
    </button>
  );
}
