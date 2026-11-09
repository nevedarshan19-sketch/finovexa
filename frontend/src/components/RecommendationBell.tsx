import { useEffect, useRef } from "react";
import { ArrowDownRight, ArrowUpRight, BellRing, Info, RefreshCw, Sparkles } from "lucide-react";
import { useApi } from "../hooks/useApi";
import { useToast } from "../context/ToastContext";
import type { RecommendationFeed } from "../lib/types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Callout,
} from "./ui";
import { DataModeBadge } from "./DataMode";
import { formatDateTime, moneyExact, plainPct } from "../lib/utils";

const STORAGE_KEY = "finovexa.recommendation.signature";

function openInMarket(symbol: string) {
  document.getElementById("real-india-market")?.scrollIntoView({ behavior: "smooth", block: "start" });
  window.dispatchEvent(new CustomEvent("finovexa:open-symbol", { detail: symbol }));
}

export function RecommendationBell() {
  const feed = useApi<RecommendationFeed>("/research/recommendations", { pollMs: 60000 });
  const { toast } = useToast();
  const notified = useRef<string | null>(null);

  useEffect(() => {
    const data = feed.data;
    if (!data || notified.current === data.signature) return;
    notified.current = data.signature;
    const previous = window.localStorage.getItem(STORAGE_KEY);
    if (previous === data.signature) return;
    window.localStorage.setItem(STORAGE_KEY, data.signature);
    const tone = data.summary.caution > 0 ? "info" : "success";
    toast({
      title: data.headline,
      description: `${data.summary.ideas} model ideas · ${data.summary.strong} strong · ${data.summary.caution} caution. Not investment advice.`,
      tone,
    });
  }, [feed.data, toast]);

  const data = feed.data;

  return (
    <Card>
      <CardHeader
        title="Quick stock ideas"
        description="A short, plain-language read of the stocks the model follows. Refreshes hourly."
        icon={BellRing}
        actions={
          <>
            <DataModeBadge mode={data?.data_mode} />
            <Button
              variant="outline"
              size="sm"
              icon={RefreshCw}
              onClick={feed.reload}
              loading={feed.loading}
            >
              Refresh
            </Button>
          </>
        }
      />

      <CardBody className="space-y-3 pt-4">
        {feed.error && !data && (
          <Callout tone="red" title="Ideas are unavailable right now">
            {feed.error}
          </Callout>
        )}

        {data && (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="violet" dot>
                {data.headline}
              </Badge>
              <Badge tone="green">{data.summary.strong} strong</Badge>
              <Badge tone="blue">{data.summary.watch} to watch</Badge>
              <Badge tone="amber">{data.summary.caution} caution</Badge>
              <span className="text-[10px] text-slate-400">
                updated {formatDateTime(data.generated_at)}
              </span>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              {data.items.map((item) => {
                const up = (item.change_pct ?? 0) >= 0;
                return (
                  <button
                    key={item.symbol}
                    type="button"
                    onClick={() => openInMarket(item.symbol)}
                    className="group rounded-xl border border-slate-100 bg-white p-3 text-left transition hover:border-brand-200 hover:bg-brand-50/30"
                    title={`Open ${item.symbol} in the market panel`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-ink-900">{item.name}</p>
                        <p className="text-[10px] text-slate-400">
                          {item.symbol} · {item.sector || "No sector"} · score {item.score}/100
                        </p>
                      </div>
                      <Badge tone={item.tone}>{item.label}</Badge>
                    </div>
                    <p className="mt-1.5 text-[11px] leading-relaxed text-slate-600">{item.reason}</p>
                    <div className="mt-1.5 flex items-center justify-between gap-2">
                      <span className="text-[11px] font-semibold tabular-nums text-ink-900">
                        {item.price !== null ? moneyExact(item.price) : "Price unavailable"}
                      </span>
                      {item.change_pct !== null && (
                        <span
                          className={`inline-flex items-center gap-0.5 text-[10px] font-semibold ${up ? "text-emerald-600" : "text-rose-600"}`}
                        >
                          {up ? (
                            <ArrowUpRight className="h-3 w-3" />
                          ) : (
                            <ArrowDownRight className="h-3 w-3" />
                          )}
                          {plainPct(Math.abs(item.change_pct), 2)} today
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
              <span>
                <strong className="text-slate-600">How to read this:</strong> a score near 70 or more means
                price momentum looks strong; near 50 means no clear direction; below 40 means the model sees
                weakness. Click any idea to see its chart. This is research to review, not an instruction.
              </span>
            </div>
          </>
        )}
      </CardBody>

      <CardFooter>
        <span className="inline-flex items-center gap-1">
          <Sparkles className="h-3 w-3" />
          Model-generated · not investment advice
        </span>
        <span>{data?.note}</span>
      </CardFooter>
    </Card>
  );
}
