import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { getErrorMessage, post } from "../lib/api";
import { moneyExact } from "../lib/utils";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import { useApi } from "../hooks/useApi";
import type { RuntimeSettings } from "../lib/types";
import { Button, Callout, Checkbox, Field, Input, Modal, Select } from "./ui";
import { DataModeBadge } from "./DataMode";

export interface TradeSubject {
  kind: "stock" | "option";
  symbol: string;
  name: string;
  subtitle?: string;
  price: number | null;
  currency: string;
  dataMode: string;
  source?: string | null;
  option?: {
    expiry: string;
    strike: number;
    optionType: "call" | "put";
    lotSize: number;
    instrumentKey?: string | null;
  };
}

type Side = "buy" | "sell";

export function TradeTicketModal({
  subject,
  initialSide = "buy",
  headroom,
  open,
  onClose,
  onCreated,
}: {
  subject: TradeSubject | null;
  initialSide?: Side;
  headroom: number;
  open: boolean;
  onClose: () => void;
  onCreated?: () => void;
}) {
  const { toast } = useToast();
  const { profile } = useAuth();
  const navigate = useNavigate();
  const runtime = useApi<RuntimeSettings>("/settings/runtime");
  const [side, setSide] = useState<Side>(initialSide);
  const [executionMode, setExecutionMode] = useState<"simulated" | "live">("simulated");
  const [quantity, setQuantity] = useState("1");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const liveReady = Boolean(runtime.data?.features.upstox.live_trading_ready);
  const liveQuote = subject?.dataMode === "live";
  const inrProfile = profile?.currency === "INR";
  const canGoLive = liveReady && liveQuote && inrProfile;
  const isLive = executionMode === "live";

  useEffect(() => {
    if (!subject) return;
    setSide(initialSide);
    setExecutionMode("simulated");
    setQuantity("1");
    setOrderType("market");
    setLimitPrice(subject.price !== null ? String(subject.price) : "");
    setAcknowledged(false);
    setError(null);
  }, [subject, initialSide, open]);

  useEffect(() => {
    if (executionMode === "live" && !canGoLive) setExecutionMode("simulated");
  }, [executionMode, canGoLive]);

  const multiplier = subject?.kind === "option" ? subject.option?.lotSize ?? 1 : 1;
  const quantityNumber = Number(quantity);
  const referencePrice = orderType === "limit" ? Number(limitPrice) : subject?.price ?? 0;
  const orderValue =
    Number.isFinite(quantityNumber) && Number.isFinite(referencePrice)
      ? quantityNumber * referencePrice * multiplier
      : 0;
  const exceedsHeadroom = side === "buy" && (orderValue > headroom || headroom <= 0);
  const invalid =
    !Number.isFinite(quantityNumber) ||
    quantityNumber <= 0 ||
    quantityNumber > (subject?.kind === "option" ? 10000 : 100000) ||
    (orderType === "limit" && (!Number.isFinite(Number(limitPrice)) || Number(limitPrice) <= 0));

  const submit = async () => {
    if (!subject) return;
    setSubmitting(true);
    setError(null);
    try {
      const common = {
        side,
        order_type: orderType,
        limit_price: orderType === "limit" ? Number(limitPrice) : null,
        execution_mode: executionMode,
      };
      if (subject.kind === "option" && subject.option) {
        await post("/approvals/options", {
          ...common,
          expiry: subject.option.expiry,
          strike: subject.option.strike,
          option_type: subject.option.optionType,
          lots: Math.floor(quantityNumber),
        });
      } else {
        await post("/approvals/investments", {
          ...common,
          symbol: subject.symbol,
          quantity: Math.floor(quantityNumber),
        });
      }
      window.dispatchEvent(new CustomEvent("finovexa:approvals-changed"));
      toast({
        title: `${isLive ? "Live" : "Simulated"} ${side} request submitted`,
        description: isLive
          ? "Review the exact instrument, price and hash in the Approval Center. Approval sends a real order to Upstox."
          : "Review the exact instrument, price and hash in the Approval Center. No order exists yet.",
        tone: "success",
      });
      onCreated?.();
      onClose();
      navigate("/approvals");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const isOption = subject?.kind === "option";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        subject
          ? `${isLive ? "Live" : "Simulated"} ${side} · ${subject.symbol}`
          : "Order ticket"
      }
      description={
        isLive
          ? "A live order request for owner approval. Approval sends a real order to Upstox."
          : isOption
            ? "A simulated option order request for owner approval. No live derivative order is placed."
            : "A simulated stock order request for owner approval. No live broker order is placed."
      }
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            icon={ShieldCheck}
            variant={side === "sell" ? "danger" : "primary"}
            onClick={submit}
            loading={submitting}
            disabled={!acknowledged || invalid || exceedsHeadroom}
          >
            Request {isLive ? "live " : ""}{side} approval
          </Button>
        </>
      }
    >
      {subject && (
        <div className="space-y-4">
          {error && (
            <Callout tone="red" title="Order request failed">
              {error}
            </Callout>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50/70 p-3">
            <div>
              <p className="text-xs font-semibold text-ink-900">{subject.name}</p>
              <p className="text-[10px] text-slate-400">
                {subject.symbol}
                {subject.subtitle ? ` · ${subject.subtitle}` : ""}
                {isOption ? ` · ${multiplier} units per lot` : ""}
              </p>
              {subject.option?.instrumentKey && (
                <p className="font-mono text-[9px] text-slate-400">{subject.option.instrumentKey}</p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <DataModeBadge mode={subject.dataMode} />
              <span className="text-sm font-semibold text-ink-900">
                {subject.price !== null ? moneyExact(subject.price, subject.currency) : "—"}
              </span>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Side" hint={isLive ? "Live orders are real and cannot be undone." : "Both sides are paper orders; no live trade is placed."}>
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  variant={side === "buy" ? "success" : "outline"}
                  onClick={() => setSide("buy")}
                >
                  Buy
                </Button>
                <Button
                  type="button"
                  variant={side === "sell" ? "danger" : "outline"}
                  onClick={() => setSide("sell")}
                >
                  Sell
                </Button>
              </div>
            </Field>
            <Field
              label={isOption ? "Lots" : "Quantity"}
              htmlFor="trade-quantity"
              required
              hint={
                isOption
                  ? `1 lot = ${multiplier} units. Order value = premium × lots × ${multiplier}.`
                  : "Whole shares only."
              }
            >
              <Input
                id="trade-quantity"
                type="number"
                min="1"
                max={isOption ? "10000" : "100000"}
                step="1"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
            </Field>
          </div>

          <Field
            label="Execution mode"
            hint={
              !liveReady
                ? "Live trading is disabled or Upstox credentials are not configured on the server."
                : !inrProfile
                  ? "Live Upstox orders require a business profile whose currency is INR."
                  : !liveQuote
                    ? "Live orders require a live Upstox quote. This ticket is priced from demo or stale data."
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

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Order type">
              <Select
                value={orderType}
                onChange={(event) => setOrderType(event.target.value as "market" | "limit")}
              >
                <option value="market">Market (displayed price)</option>
                <option value="limit">Limit (fixed price)</option>
              </Select>
            </Field>
            {orderType === "limit" && (
              <Field label={isOption ? "Limit premium" : "Limit price"} htmlFor="trade-limit" required>
                <Input
                  id="trade-limit"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={limitPrice}
                  onChange={(event) => setLimitPrice(event.target.value)}
                />
              </Field>
            )}
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3 text-[11px]">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-500">Estimated order value</span>
              <span className="font-semibold text-ink-900">
                {moneyExact(orderValue, subject.currency)}
              </span>
            </div>
            {side === "buy" ? (
              <div className="mt-1 flex items-center justify-between gap-2">
                <span className="text-slate-500">Investable headroom above reserve</span>
                <span
                  className={`font-semibold ${
                    exceedsHeadroom ? "text-rose-600" : "text-emerald-700"
                  }`}
                >
                  {moneyExact(headroom, subject.currency)}
                </span>
              </div>
            ) : (
              <p className="mt-1 leading-relaxed text-slate-500">
                {isLive
                  ? "Upstox applies its own holdings and margin checks. No local holdings check is performed."
                  : "Simulated sells do not check holdings, margin or settlement. No position or short-sale accounting is carried out."}
              </p>
            )}
            {isOption && (
              <p className="mt-1.5 text-[10px] leading-relaxed text-slate-400">
                {isLive
                  ? "Premium is the live option chain LTP. The order is re-checked when you approve it."
                  : "Premium is the option chain LTP. This paper ticket is priced from the displayed chain and re-checked when you approve it."}
              </p>
            )}
          </div>

          {exceedsHeadroom && (
            <Callout tone="red" title="Order exceeds available headroom">
              Reduce size or choose a lower limit. Approval execution re-checks headroom and will
              reject an oversized buy.
            </Callout>
          )}

          <Callout
            tone={isLive ? "red" : "violet"}
            title={isLive ? "Live order notice" : "Simulation notice"}
            icon={ShieldAlert}
          >
            {isLive ? (
              <>
                After approval, a <strong>real order</strong> is sent to Upstox. Money, holdings or
                margin can change, and a market order can fill at a different price. Upstox requires
                order placement from a registered static IP.
              </>
            ) : (
              <>
                Even after approval, this build only creates a <strong>simulated</strong> order. No
                Upstox order is sent, no shares or contracts settle and no cash enters or leaves your
                ledger.
              </>
            )}
          </Callout>

          <Checkbox
            checked={acknowledged}
            onChange={setAcknowledged}
            label={
              isLive
                ? `I understand this is a real live ${side} order to Upstox, requires explicit approval, and is not investment advice.`
                : `I understand this is a simulated ${side} request requiring explicit approval, not investment advice.`
            }
          />
        </div>
      )}
    </Modal>
  );
}
