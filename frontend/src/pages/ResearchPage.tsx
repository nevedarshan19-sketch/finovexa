import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowDownRight,
  ArrowUpRight,
  Ban,
  BellRing,
  BriefcaseBusiness,
  CheckCircle2,
  CircleDollarSign,
  ExternalLink,
  LineChart,
  LockKeyhole,
  Newspaper,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { useApi } from "../hooks/useApi";
import { getErrorMessage, post } from "../lib/api";
import type { BrokerOrder, ResearchItem, ResearchOverview, RuntimeSettings } from "../lib/types";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  PageSkeleton,
  ProgressBar,
  Select,
  StatCard,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui";
import { DataModeBadge, StatusBadge } from "../components/DataMode";
import { OptionChainPanel } from "../components/OptionChainPanel";
import { NiftyTradeDesk } from "../components/NiftyTradeDesk";
import { MarketSimulator } from "../components/MarketSimulator";
import { RecommendationBell } from "../components/RecommendationBell";
import { InvestmentPortfolio } from "../components/InvestmentPortfolio";
import { IndianMarketPanel } from "../components/IndianMarketPanel";
import {
  formatDate,
  formatDateTime,
  money,
  moneyExact,
  number,
  plainPct,
  titleCase,
} from "../lib/utils";

function signalTone(signal: string): "green" | "amber" | "red" | "slate" {
  if (signal === "positive") return "green";
  if (signal === "caution") return "red";
  if (signal === "neutral") return "amber";
  return "slate";
}

function OrderModal({
  item,
  headroom,
  currency,
  open,
  onClose,
  onCreated,
}: {
  item: ResearchItem | null;
  headroom: number;
  currency: string;
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { toast } = useToast();
  const { profile } = useAuth();
  const navigate = useNavigate();
  const runtime = useApi<RuntimeSettings>("/settings/runtime");
  const [quantity, setQuantity] = useState("1");
  const [executionMode, setExecutionMode] = useState<"simulated" | "live">("simulated");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const liveReady = Boolean(runtime.data?.features.upstox.live_trading_ready);
  const inrProfile = profile?.currency === "INR";
  const canGoLive = liveReady && inrProfile && item?.quote.data_mode === "live";
  const isLive = executionMode === "live";

  useEffect(() => {
    if (item) {
      setQuantity(String(Math.max(1, item.cash_constraints.illustrative_quantity)));
      setExecutionMode("simulated");
      setOrderType("market");
      setLimitPrice(item.quote.price !== null ? String(item.quote.price) : "");
      setAcknowledged(false);
      setError(null);
    }
  }, [item]);

  useEffect(() => {
    if (executionMode === "live" && !canGoLive) setExecutionMode("simulated");
  }, [executionMode, canGoLive]);

  const quantityNumber = Number(quantity);
  const referencePrice = orderType === "limit" ? Number(limitPrice) : item?.quote.price ?? 0;
  const orderValue = Number.isFinite(quantityNumber) && Number.isFinite(referencePrice)
    ? quantityNumber * referencePrice
    : 0;
  const exceedsHeadroom = orderValue > headroom || headroom <= 0;
  const invalid =
    !Number.isFinite(quantityNumber) ||
    quantityNumber <= 0 ||
    quantityNumber > 100000 ||
    (orderType === "limit" && (!Number.isFinite(Number(limitPrice)) || Number(limitPrice) <= 0));

  const submit = async () => {
    if (!item) return;
    setSubmitting(true);
    setError(null);
    try {
      await post("/approvals/investments", {
        symbol: item.symbol,
        side: "buy",
        quantity: Math.floor(quantityNumber),
        order_type: orderType,
        limit_price: orderType === "limit" ? Number(limitPrice) : null,
        execution_mode: executionMode,
      });
      window.dispatchEvent(new CustomEvent("finovexa:approvals-changed"));
      toast({
        title: `${isLive ? "Live" : "Simulated"} order submitted for approval`,
        description: isLive
          ? "Approval sends a real order to Upstox. Review the exact quote, quantity and hash first."
          : "Review the exact quote, quantity and hash in the Approval Center. No order exists yet.",
        tone: "success",
      });
      onCreated();
      onClose();
      navigate("/approvals");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={item ? `${isLive ? "Live" : "Simulated"} buy · ${item.symbol}` : "Order ticket"}
      description={
        isLive
          ? "A live order request for owner approval. Approval sends a real order to Upstox."
          : "A request for owner approval. This is a simulated order and no money moves."
      }
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            icon={ShieldCheck}
            onClick={submit}
            loading={submitting}
            disabled={!acknowledged || invalid || exceedsHeadroom}
          >
            Request {isLive ? "live " : ""}approval
          </Button>
        </>
      }
    >
      {item && (
        <div className="space-y-4">
          {error && <Callout tone="red" title="Order request failed">{error}</Callout>}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50/70 p-3">
            <div>
              <p className="text-xs font-semibold text-ink-900">{item.name} · {item.exchange}</p>
              <p className="text-[10px] text-slate-400">{item.sector || "No sector"} · {item.signal ? titleCase(item.signal.model_signal) : "No signal"}</p>
            </div>
            <div className="flex items-center gap-2">
              <DataModeBadge mode={item.quote.data_mode} />
              <span className="text-sm font-semibold text-ink-900">
                {item.quote.price !== null ? moneyExact(item.quote.price, item.quote.currency) : "—"}
              </span>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Side">
              <Input value="Buy" readOnly className="bg-slate-50 text-slate-500" />
            </Field>
            <Field label="Quantity" htmlFor="order-quantity" required hint={`Illustrative size: ${item.cash_constraints.illustrative_quantity} shares (10% of headroom).`}>
              <Input
                id="order-quantity"
                type="number"
                min="1"
                max="100000"
                step="1"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Order type">
              <Select value={orderType} onChange={(event) => setOrderType(event.target.value as "market" | "limit")}>
                <option value="market">Market (quote at execution)</option>
                <option value="limit">Limit (fixed price cap)</option>
              </Select>
            </Field>
            {orderType === "limit" && (
              <Field label="Limit price" htmlFor="order-limit" required>
                <Input
                  id="order-limit"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={limitPrice}
                  onChange={(event) => setLimitPrice(event.target.value)}
                />
              </Field>
            )}
          </div>
          <Field
            label="Execution mode"
            hint={
              !liveReady
                ? "Live trading is disabled or Upstox credentials are not configured on the server."
                : !inrProfile
                  ? "Live Upstox orders require a business profile whose currency is INR."
                  : item.quote.data_mode !== "live"
                    ? "Live orders require a live Upstox quote. This signal is priced from demo or stale data."
                    : "Live orders are sent to Upstox after your approval and require a registered static IP."
            }
          >
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant={!isLive ? "primary" : "outline"}
                onClick={() => setExecutionMode("simulated")}
              >
                Simulated
              </Button>
              <Button
                type="button"
                variant={isLive ? "danger" : "outline"}
                onClick={() => setExecutionMode("live")}
                disabled={!canGoLive}
              >
                Live · Upstox
              </Button>
            </div>
          </Field>
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3 text-[11px]">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-500">Estimated order value</span>
              <span className="font-semibold text-ink-900">{moneyExact(orderValue, currency)}</span>
            </div>
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="text-slate-500">Investable headroom above reserve</span>
              <span className={`font-semibold ${exceedsHeadroom ? "text-rose-600" : "text-emerald-700"}`}>
                {moneyExact(headroom, currency)}
              </span>
            </div>
            <p className="mt-1.5 text-[10px] leading-relaxed text-slate-400">{item.cash_constraints.surplus_note}</p>
          </div>
          {exceedsHeadroom && (
            <Callout tone="red" title="Order exceeds available headroom">
              Reduce quantity or choose a lower limit. Approval execution re-checks headroom and will reject an
              oversized order.
            </Callout>
          )}
          <Callout
            tone={isLive ? "red" : "violet"}
            title={isLive ? "Live order notice" : "Simulation notice"}
            icon={ShieldAlert}
          >
            {isLive ? (
              <>
                After approval, a <strong>real order</strong> is sent to Upstox. Money, holdings or margin can
                change, and a market order can fill at a different price. Upstox requires order placement from a
                registered static IP.
              </>
            ) : (
              <>
                Even after approval, this build only creates a <strong>simulated</strong> broker order. No Upstox
                order is sent, no shares settle and no cash enters or leaves your ledger.
              </>
            )}
          </Callout>
          <Checkbox
            checked={acknowledged}
            onChange={setAcknowledged}
            label={
              isLive
                ? "I understand this is a real live buy order to Upstox, requires explicit approval, and is not investment advice."
                : "I understand this is a simulated, model-informed order request requiring explicit approval, not investment advice."
            }
          />
        </div>
      )}
    </Modal>
  );
}

export function ResearchPage() {
  const { toast } = useToast();
  const research = useApi<ResearchOverview>("/research");
  const [orderItem, setOrderItem] = useState<ResearchItem | null>(null);
  const [pendingAction, setPendingAction] = useState<{ order: BrokerOrder; action: "fill" | "cancel" } | null>(null);
  const [acting, setActing] = useState(false);

  const currency = research.data?.risk_profile.currency || "INR";
  const signals = useMemo(() => research.data?.items ?? [], [research.data]);
  const orders = research.data?.orders ?? [];
  const headroom = research.data?.cash_context.investable_headroom ?? 0;

  const runOrderAction = async () => {
    if (!pendingAction) return;
    setActing(true);
    try {
      const { order, action } = pendingAction;
      if (order.simulated) {
        const endpoint = action === "fill" ? "simulate-fill" : "simulate-cancel";
        await post(`/orders/${order.id}/${endpoint}`, { confirm: true });
        if (action === "fill") {
          window.dispatchEvent(new CustomEvent("finovexa:portfolio-changed"));
        }
        toast({
          title: action === "fill" ? "Simulated fill recorded" : "Simulation cancelled",
          description:
            action === "fill"
              ? "Your practice portfolio now reflects this fill. No real execution occurred."
              : "No real execution occurred. The status change is audited.",
          tone: "success",
        });
      } else {
        await post(`/orders/${order.id}/cancel-request`, { confirm: true });
        toast({
          title: "Upstox cancellation requested",
          description: "Refresh the order to confirm the broker status.",
          tone: "success",
        });
      }
      setPendingAction(null);
      research.reload();
    } catch (err) {
      toast({ title: "Action failed", description: getErrorMessage(err), tone: "error" });
    } finally {
      setActing(false);
    }
  };

  const syncOrder = async (order: BrokerOrder) => {
    setActing(true);
    try {
      const result = await post<{ order: BrokerOrder }>(`/orders/${order.id}/sync`);
      toast({
        title: "Broker status refreshed",
        description: `Upstox reports: ${result.order.broker_status || result.order.status}.`,
        tone: "success",
      });
      research.reload();
    } catch (err) {
      toast({ title: "Could not refresh order", description: getErrorMessage(err), tone: "error" });
    } finally {
      setActing(false);
    }
  };

  if (research.loading && !research.data) return <PageSkeleton cards={4} />;
  if (research.error && !research.data) return <ErrorState message={research.error} onRetry={research.reload} />;
  if (!research.data) return null;

  const data = research.data;
  const liveCancel = Boolean(pendingAction && !pendingAction.order.simulated);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Investment research"
        title="Your money, in plain view"
        description="See today's NSE prices, a few simple stock ideas, and what your practice portfolio is worth. Every price says how fresh it is, and nothing is bought or sold without your approval."
        actions={
          <>
            <DataModeBadge mode={data.broker_status.mode} />
            <Button variant="outline" size="md" icon={RefreshCw} onClick={research.reload} loading={research.loading}>
              Refresh research
            </Button>
          </>
        }
      />

      <div className="grid gap-2.5 sm:grid-cols-3">
        {[
          {
            icon: LineChart,
            title: "1 · Market today",
            text: "Real NSE prices, delayed by a few minutes. Tap any stock to see its chart.",
            href: "#real-india-market",
          },
          {
            icon: BellRing,
            title: "2 · Ideas to review",
            text: "Three simple ideas with a one-line reason. A prompt, not a buy instruction.",
            href: "#quick-ideas",
          },
          {
            icon: BriefcaseBusiness,
            title: "3 · Your portfolio",
            text: "What your practice holdings are worth now, kept apart from business cash.",
            href: "#investment-portfolio",
          },
        ].map((step) => (
          <a
            key={step.title}
            href={step.href}
            className="group rounded-xl border border-slate-100 bg-white p-3 transition hover:border-brand-200 hover:bg-brand-50/30"
          >
            <p className="flex items-center gap-1.5 text-xs font-semibold text-ink-900">
              <step.icon className="h-3.5 w-3.5 text-brand-600" />
              {step.title}
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{step.text}</p>
          </a>
        ))}
      </div>

      <Callout tone="violet" title="This is research, not investment advice" icon={ShieldAlert}>
        Ideas come from a transparent rules-based model using price momentum and data-quality checks. They are{" "}
        <strong>not</strong> analyst ratings or suitability advice, and FINOVEXA never places a trade automatically.{" "}
        {data.broker_status.note}
      </Callout>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Business cash" value={moneyExact(data.cash_context.recorded_cash, currency)} icon={Wallet} sub="money in your ledger" tone="blue" />
        <StatCard label="Cash you protect" value={money(data.cash_context.minimum_reserve, currency)} icon={LockKeyhole} sub="reserve you keep untouched" tone="slate" />
        <StatCard
          label="You could invest up to"
          value={money(data.cash_context.investable_headroom, currency)}
          icon={CircleDollarSign}
          sub="projected spare cash above your reserve"
          tone={headroom > 0 ? "green" : "red"}
        />
        <StatCard
          label="Broker mode"
          value={titleCase(data.broker_status.mode)}
          icon={LineChart}
          sub={data.broker_status.live_trading_ready ? "live orders need your approval" : "practice mode, no real orders"}
          tone="violet"
        />
      </div>

      <div id="quick-ideas" className="scroll-mt-24">
        <RecommendationBell />
      </div>

      <div id="investment-portfolio" className="scroll-mt-24">
        <InvestmentPortfolio />
      </div>

      <IndianMarketPanel />

      <MarketSimulator />

      <OptionChainPanel
        headroom={headroom}
        currency={currency}
        onOrderCreated={research.reload}
      />

      <div className="flex flex-wrap items-end justify-between gap-2 pt-1">
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-ink-900">Ideas in detail</h2>
          <p className="text-xs text-slate-500">
            The {signals.length} stocks the model follows, with the score, risks and disclosures behind each idea.
          </p>
        </div>
        <Badge tone="violet">{signals.length} stocks</Badge>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {signals.map((item) => {
          const signal = item.signal;
          const tone = signal ? signalTone(signal.model_signal) : "slate";
          const priceUp = (item.quote.change_pct ?? 0) >= 0;
          return (
            <Card key={item.symbol} className="flex h-full flex-col">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 p-4">
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 text-xs font-bold text-slate-600">
                    {item.symbol.slice(0, 2)}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-ink-900">{item.name}</p>
                    <p className="text-[10px] text-slate-400">
                      {item.symbol} · {item.exchange} · {item.sector || "No sector"}
                    </p>
                    {item.instrument_key && (
                      <p className="font-mono text-[9px] text-slate-400">{item.instrument_key}</p>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold text-ink-900">
                    {item.quote.price !== null ? moneyExact(item.quote.price, item.quote.currency) : "Unavailable"}
                  </p>
                  {item.quote.change_pct !== null && (
                    <p className={`inline-flex items-center gap-0.5 text-[11px] font-semibold ${priceUp ? "text-emerald-600" : "text-rose-600"}`}>
                      {priceUp ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                      {plainPct(Math.abs(item.quote.change_pct), 2)}
                    </p>
                  )}
                </div>
              </div>
              <CardBody className="flex flex-1 flex-col space-y-3 pt-4">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={tone}>{signal ? titleCase(signal.model_signal) : "No signal"}</Badge>
                  <Badge tone="violet">MODEL-GENERATED</Badge>
                  <DataModeBadge mode={item.quote.data_mode} />
                  {signal && <span className="text-[10px] text-slate-400">score {signal.score}/100</span>}
                </div>
                {signal && (
                  <>
                    <ProgressBar value={signal.score} tone={tone === "slate" ? "blue" : tone} label="Model score" />
                    <p className="text-[12px] leading-relaxed text-slate-600">{signal.rationale}</p>
                    <div className="grid gap-2 rounded-lg border border-slate-100 bg-slate-50/70 p-2.5 text-[10px] text-slate-500">
                      <p><span className="font-semibold text-slate-600">Illustrative size:</span> {item.cash_constraints.illustrative_quantity} shares ≈ {money(item.cash_constraints.illustrative_order_value, currency)} · {item.cash_constraints.sizing_rule}</p>
                      <p><span className="font-semibold text-slate-600">Data quality:</span> {item.data_quality_note}</p>
                    </div>
                    <details className="text-[11px] text-slate-500">
                      <summary className="cursor-pointer font-medium text-slate-500 hover:text-slate-700">Methodology, risks and disclosure</summary>
                      <div className="mt-1.5 space-y-1.5 leading-relaxed">
                        <p><span className="font-semibold text-slate-600">Method:</span> {signal.methodology}</p>
                        <p><span className="font-semibold text-slate-600">Risks:</span> {signal.risks}</p>
                        <p className="text-[10px] text-slate-400">{signal.disclosure}</p>
                      </div>
                    </details>
                  </>
                )}
                {item.announcements.length > 0 && (
                  <div>
                    <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                      Related announcements
                    </p>
                    <div className="space-y-1">
                      {item.announcements.slice(0, 2).map((article) => (
                        <a
                          key={article.id}
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-start gap-1.5 rounded-md px-1 py-0.5 text-[10px] text-slate-500 hover:bg-slate-50 hover:text-brand-600"
                        >
                          <Newspaper className="mt-0.5 h-3 w-3 shrink-0" />
                          <span className="line-clamp-1">{article.title}</span>
                          <ExternalLink className="ml-auto mt-0.5 h-2.5 w-2.5 shrink-0" />
                        </a>
                      ))}
                    </div>
                  </div>
                )}
                <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
                  <p className="text-[9px] text-slate-400">
                    Generated {formatDateTime(signal?.generated_at)} · analyst ratings unavailable
                  </p>
                  <Button size="sm" icon={TrendingUp} onClick={() => setOrderItem(item)} disabled={item.quote.price === null}>
                    Trade
                  </Button>
                </div>
              </CardBody>
            </Card>
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-7">
          <CardHeader
            title="Your orders"
            description={
              data.broker_status.live_trading_ready
                ? "Practice and live Upstox orders. An order exists only after you approve it."
                : "Practice orders. Nothing is sent to a broker until you approve it."
            }
            icon={LineChart}
            actions={<Badge tone="violet" dot>{orders.length} orders</Badge>}
          />
          <div className="mt-3">
            {orders.length === 0 ? (
              <EmptyState
                title="No orders yet"
                description="Create a simulated or live buy or sell request from the NIFTY 50 trade desk or option chain, then approve it to produce an order."
                icon={LineChart}
              />
            ) : (
              <TableWrap>
                <THead>
                  <TR>
                    <TH>Order</TH>
                    <TH>Symbol</TH>
                    <TH className="text-right">Qty</TH>
                    <TH>Status</TH>
                    <TH>Created</TH>
                    <TH className="text-right">Actions</TH>
                  </TR>
                </THead>
                <TBody>
                  {orders.map((order) => (
                    <TR key={order.id}>
                      <TD>
                        <p className="font-semibold text-ink-900">#{order.id}</p>
                        <p className="font-mono text-[9px] text-slate-400">{order.broker_order_id || "—"}</p>
                      </TD>
                      <TD>
                        <p className="font-medium text-ink-900">
                          {order.option?.display_name || order.symbol || "—"}
                        </p>
                        <p className="flex flex-wrap items-center gap-1.5 text-[10px] uppercase text-slate-400">
                          <Badge tone={order.simulated ? "violet" : "red"}>
                            {order.simulated ? "SIM" : "LIVE"}
                          </Badge>
                          <span>
                            {order.side} · {order.asset_class === "option" ? "option" : order.order_type}
                            {order.order_value != null
                              ? ` · ${moneyExact(order.order_value, currency)}`
                              : ""}
                          </span>
                        </p>
                      </TD>
                      <TD className="text-right tabular-nums">
                        {number(order.quantity)}
                        {order.lot_size > 1 && (
                          <span className="ml-1 text-[9px] text-slate-400">lots</span>
                        )}
                      </TD>
                      <TD>
                        <StatusBadge status={order.status} />
                        {order.broker_status_message && (
                          <p className="mt-1 max-w-[180px] truncate text-[9px] text-slate-400" title={order.broker_status_message}>
                            {order.broker_status_message}
                          </p>
                        )}
                      </TD>
                      <TD className="text-[10px] text-slate-400">{formatDateTime(order.created_at)}</TD>
                      <TD>
                        <div className="flex justify-end gap-1">
                          {order.simulated ? (
                            <>
                              {order.status === "simulated_pending" && (
                                <Button size="sm" variant="success" icon={Play} onClick={() => setPendingAction({ order, action: "fill" })}>
                                  Fill
                                </Button>
                              )}
                              {(order.status === "simulated_pending" || order.status === "cancel_requested") && (
                                <Button size="sm" variant="ghost" icon={Ban} onClick={() => setPendingAction({ order, action: "cancel" })}>
                                  Cancel
                                </Button>
                              )}
                            </>
                          ) : (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                icon={RefreshCw}
                                onClick={() => void syncOrder(order)}
                                loading={acting}
                              >
                                Sync
                              </Button>
                              {["live_submitted", "live_open", "live_partially_filled"].includes(order.status) && (
                                <Button size="sm" variant="ghost" icon={Ban} onClick={() => setPendingAction({ order, action: "cancel" })}>
                                  Cancel
                                </Button>
                              )}
                            </>
                          )}
                        </div>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
            )}
          </div>
          <CardFooter>
            <span>
              {data.broker_status.live_trading_ready
                ? "Live orders are real Upstox orders. Simulated fills update the practice portfolio only."
                : "Simulated fills update the practice portfolio only. No cash moves and no broker is called."}
            </span>
            <span>Broker: {data.broker_status.mode}</span>
          </CardFooter>
        </Card>

        <div className="space-y-4 lg:col-span-5">
          <Card>
            <CardHeader title="Cash constraint" description="Sizing discipline before any order." icon={Wallet} />
            <CardBody className="space-y-2.5 pt-3">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-slate-500">Recorded cash</span>
                <span className="font-semibold text-ink-900">{money(data.cash_context.recorded_cash, currency)}</span>
              </div>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-slate-500">Minimum reserve</span>
                <span className="font-semibold text-ink-900">{money(data.cash_context.minimum_reserve, currency)}</span>
              </div>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-slate-500">Projected minimum · 30d</span>
                <span className="font-semibold text-ink-900">{money(data.cash_context.projected_minimum_30d, currency)}</span>
              </div>
              <div className="flex items-center justify-between gap-2 rounded-lg bg-emerald-50 px-2.5 py-2 text-xs">
                <span className="text-emerald-700">Investable headroom</span>
                <span className="font-semibold text-emerald-800">{money(data.cash_context.investable_headroom, currency)}</span>
              </div>
              {data.cash_context.shortfall_date && (
                <Callout tone="red" title="Reserve breach projected">
                  The 30-day base forecast dips below reserve on {formatDate(data.cash_context.shortfall_date)}.
                  Investing is not advisable without mitigation.
                </Callout>
              )}
              <p className="text-[10px] leading-relaxed text-slate-400">
                Headroom is the lowest projected balance above reserve, not spare cash. The server re-checks it when an
                approved order executes.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Ratings & disclosures" icon={ShieldCheck} />
            <CardBody className="space-y-2.5 pt-3">
              <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-2.5 text-[10px] leading-relaxed text-slate-500">
                <p className="font-semibold text-slate-600">Analyst ratings</p>
                <p className="mt-0.5">{data.items[0]?.analyst_ratings.note || "No third-party ratings provider is connected. Ratings are not fabricated."}</p>
              </div>
              {data.disclosures.map((disclosure) => (
                <p key={disclosure} className="flex items-start gap-1.5 text-[10px] leading-relaxed text-slate-500">
                  <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" />
                  {disclosure}
                </p>
              ))}
              <div className="flex flex-wrap gap-1.5 border-t border-slate-100 pt-2">
                <Badge tone="slate">Risk profile: {titleCase(data.risk_profile.tolerance)}</Badge>
                {data.risk_profile.research_interests.map((symbol) => (
                  <Badge key={symbol} tone="blue">{symbol}</Badge>
                ))}
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Broker connection" icon={LockKeyhole} />
            <CardBody className="space-y-2 pt-3 text-[11px] text-slate-500">
              <div className="flex items-center justify-between">
                <span>Mode</span>
                <DataModeBadge mode={data.broker_status.mode} />
              </div>
              <div className="flex items-center justify-between">
                <span>Upstox credentials</span>
                <Badge tone={data.broker_status.upstox_configured ? "green" : "slate"}>
                  {data.broker_status.upstox_configured ? "Configured" : "Not configured"}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span>Live trading</span>
                <Badge tone={data.broker_status.live_trading_enabled ? "amber" : "slate"}>
                  {data.broker_status.live_trading_enabled ? "Enabled" : "Disabled"}
                </Badge>
              </div>
              <p className="pt-1 text-[10px] leading-relaxed text-slate-400">
                Credentials stay on the backend. Upstox OAuth and live orders are not exposed to the browser.
              </p>
            </CardBody>
          </Card>
        </div>
      </div>

      <div id="nifty50-trade-desk" className="scroll-mt-24">
        <NiftyTradeDesk
          headroom={headroom}
          currency={currency}
          onOrderCreated={research.reload}
        />
      </div>

      <Callout tone="blue" title="Why signals are labelled model-generated" icon={Sparkles}>
        FINOVEXA distinguishes its own transparent model output from licensed analyst research. No analyst ratings,
        target prices or consensus figures are shown unless a real provider is connected. Signals use demo price
        history in this workspace and cannot be construed as advice.
      </Callout>

      <OrderModal
        item={orderItem}
        headroom={headroom}
        currency={currency}
        open={Boolean(orderItem)}
        onClose={() => setOrderItem(null)}
        onCreated={research.reload}
      />

      <ConfirmDialog
        open={Boolean(pendingAction)}
        onClose={() => setPendingAction(null)}
        onConfirm={runOrderAction}
        loading={acting}
        title={
          liveCancel
            ? "Request live cancellation on Upstox?"
            : pendingAction?.action === "fill"
              ? "Record a simulated fill?"
              : "Cancel the simulated order?"
        }
        description={
          liveCancel
            ? "This sends a cancellation request to Upstox. The order may already be filled; refresh the status afterwards to confirm."
            : "This changes the local simulation and updates the practice portfolio. No live order, settlement or cash movement occurs."
        }
        confirmLabel={
          liveCancel
            ? "Request Upstox cancellation"
            : pendingAction?.action === "fill"
              ? "Simulate fill"
              : "Simulate cancel"
        }
        tone={pendingAction?.action === "fill" && !liveCancel ? "success" : "danger"}
      >
        {pendingAction && (
          <p className="text-xs leading-relaxed text-slate-600">
            Order <strong>#{pendingAction.order.id}</strong> · {pendingAction.order.quantity} ×{" "}
            {pendingAction.order.symbol || "instrument"} · {titleCase(pendingAction.order.order_type)}. Broker:{" "}
            {pendingAction.order.simulated ? "simulated" : `Upstox (${pendingAction.order.broker_order_id || "no id"})`}.
          </p>
        )}
      </ConfirmDialog>
    </div>
  );
}
