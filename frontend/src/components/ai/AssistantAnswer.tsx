import { AlertTriangle, ArrowUpRight, ExternalLink, Gauge, Lightbulb, ShieldCheck } from "lucide-react";
import type { ChatAnswer, Citation } from "../../lib/types";
import { cn } from "../../lib/utils";
import { Badge } from "../ui";

function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={index}>{part.slice(2, -2)}</strong>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

export function RichText({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/).filter((block) => block.trim());
  return (
    <div className="space-y-2.5 text-[13.5px] leading-relaxed text-slate-700">
      {blocks.map((block, index) => {
        const lines = block
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        const listLike = lines.length > 0 && lines.every((line) => /^([-•*]|\d+\.)\s+/.test(line));
        if (listLike) {
          return (
            <ul key={index} className="list-disc space-y-1 pl-5">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  <Inline text={line.replace(/^([-•*]|\d+\.)\s+/, "")} />
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={index} className="whitespace-pre-line">
            <Inline text={block} />
          </p>
        );
      })}
    </div>
  );
}

function AnswerSection({
  title,
  items,
  tone,
  icon: Icon,
}: {
  title: string;
  items: string[];
  tone: "green" | "amber" | "blue" | "slate";
  icon: typeof Gauge;
}) {
  if (!items.length) return null;
  const tones = {
    green: "border-emerald-200 bg-emerald-50/50 text-emerald-900",
    amber: "border-amber-200 bg-amber-50/50 text-amber-900",
    blue: "border-brand-200 bg-brand-50/50 text-brand-900",
    slate: "border-slate-200 bg-slate-50 text-slate-700",
  }[tone];
  const iconTone = {
    green: "text-emerald-600",
    amber: "text-amber-600",
    blue: "text-brand-600",
    slate: "text-slate-500",
  }[tone];
  return (
    <div className={cn("rounded-lg border px-3 py-2.5", tones)}>
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide">
        <Icon className={cn("h-3.5 w-3.5", iconTone)} aria-hidden />
        {title}
      </p>
      <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12.5px] leading-relaxed">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function CitationChip({ citation }: { citation: Citation }) {
  const content = (
    <>
      <span className="font-medium">{citation.label}</span>
      <span className="text-slate-400">· {citation.source}</span>
      {citation.data_mode && <Badge tone="slate">{citation.data_mode}</Badge>}
      {citation.url && <ExternalLink className="h-3 w-3" aria-hidden />}
    </>
  );
  if (citation.url) {
    return (
      <a
        href={citation.url}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex flex-wrap items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:border-brand-300 hover:text-brand-700"
      >
        {content}
      </a>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600">
      {content}
    </span>
  );
}

export function AssistantAnswer({
  answer,
  onAsk,
  compact = false,
}: {
  answer: Partial<ChatAnswer>;
  onAsk: (question: string) => void;
  compact?: boolean;
}) {
  return (
    <div className={cn("space-y-3", compact && "space-y-2.5")}>
      <RichText text={answer.answer || "No answer text was returned."} />
      <div className="grid gap-2">
        <AnswerSection title="Verified ledger facts" items={answer.verified_facts || []} tone="green" icon={ShieldCheck} />
        <AnswerSection title="Estimates" items={answer.estimates || []} tone="amber" icon={Gauge} />
        {!compact && (
          <AnswerSection title="Interpretations" items={answer.interpretations || []} tone="blue" icon={Lightbulb} />
        )}
        <AnswerSection title="Uncertainty and limits" items={answer.uncertainty || []} tone="slate" icon={AlertTriangle} />
      </div>
      {Boolean(answer.citations?.length) && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Sources from authorized tools
          </p>
          <div className="flex flex-wrap gap-1.5">
            {answer.citations!.map((citation, index) => (
              <CitationChip key={`${citation.type}-${citation.id}-${index}`} citation={citation} />
            ))}
          </div>
        </div>
      )}
      {Boolean(answer.followups?.length) && (
        <div className="flex flex-wrap gap-1.5 border-t border-slate-100 pt-2.5">
          {answer.followups!.map((followup) => (
            <button
              key={followup}
              type="button"
              onClick={() => onAsk(followup)}
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 transition hover:border-brand-300 hover:text-brand-700"
            >
              {followup}
              <ArrowUpRight className="h-3 w-3" aria-hidden />
            </button>
          ))}
        </div>
      )}
      {answer.provider_note && (
        <p className="text-[11px] leading-relaxed text-slate-400">{answer.provider_note}</p>
      )}
    </div>
  );
}
