import { ChevronRight, CircleDollarSign, FileWarning, Lightbulb } from "lucide-react";
import type { Insight } from "../lib/types";
import { formatDate, money } from "../lib/utils";
import { Badge, Card } from "./ui";
import { ConfidenceBadge } from "./DataMode";

export function InsightCard({ insight, currency }: { insight: Insight; currency: string }) {
  const evidence = Array.isArray(insight.evidence) ? insight.evidence : [];
  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <div className="h-1 w-full bg-gradient-to-r from-brand-500 via-brand-400 to-cyan-400" aria-hidden />
      <div className="flex flex-1 flex-col p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="blue" dot>
            {insight.agent === "business_manager" ? "Business Manager" : insight.agent}
          </Badge>
          <ConfidenceBadge confidence={insight.confidence} />
          <Badge tone="slate">{insight.mode === "deterministic" ? "Rules engine" : insight.mode}</Badge>
        </div>
        <h3 className="mt-3 text-[15px] font-semibold leading-snug tracking-tight text-ink-900">
          {insight.title}
        </h3>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">{insight.finding}</p>

        {insight.impact_amount ? (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2">
            <CircleDollarSign className="h-4 w-4 text-slate-400" aria-hidden />
            <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
              Estimated impact
            </span>
            <span className="ml-auto text-sm font-semibold text-ink-900">
              {money(insight.impact_amount, currency)}
            </span>
          </div>
        ) : null}

        {evidence.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {evidence.slice(0, 4).map((item, index) => (
              <span
                key={`${item.type}-${item.id}-${index}`}
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] text-slate-500"
              >
                <FileWarning className="h-3 w-3 text-slate-400" aria-hidden />
                {item.label}
                {item.amount !== undefined && item.amount !== null && (
                  <span className="font-semibold text-slate-600">
                    · {money(Number(item.amount), currency)}
                  </span>
                )}
              </span>
            ))}
          </div>
        )}

        {insight.recommended_action && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-brand-100 bg-brand-50/60 px-3 py-2">
            <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-600" aria-hidden />
            <p className="text-[11px] leading-relaxed text-brand-900">{insight.recommended_action}</p>
          </div>
        )}

        {insight.limitations && (
          <details className="group mt-3 text-[11px] text-slate-500">
            <summary className="flex cursor-pointer list-none items-center gap-1 font-medium text-slate-400 hover:text-slate-600">
              <ChevronRight className="h-3 w-3 transition group-open:rotate-90" aria-hidden />
              Limitations
            </summary>
            <p className="mt-1.5 leading-relaxed">{insight.limitations}</p>
          </details>
        )}

        <p className="mt-auto pt-3 text-[10px] text-slate-400">
          Computed {formatDate(insight.created_at)}
          {insight.period_start && insight.period_end
            ? ` · evidence period ${formatDate(insight.period_start)} – ${formatDate(insight.period_end)}`
            : ""}
        </p>
      </div>
    </Card>
  );
}
