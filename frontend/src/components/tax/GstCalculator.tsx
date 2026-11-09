import { useMemo, useState } from "react";
import { Calculator, Plus, Trash2 } from "lucide-react";
import { getErrorMessage, post } from "../../lib/api";
import type { GstCalculation, TaxGstOptions } from "../../lib/taxTypes";
import { moneyExact, plainPct } from "../../lib/utils";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  Select,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../ui";

interface CalcLine {
  key: number;
  quantity: string;
  unit_price: string;
  discount: string;
  gst_rate: string;
}

const FALLBACK_RATES = ["0", "5", "12", "18", "28"];

function newLine(key: number, rate: string): CalcLine {
  return { key, quantity: "1", unit_price: "", discount: "0", gst_rate: rate };
}

export function GstCalculator({
  options,
  currency = "INR",
}: {
  options: TaxGstOptions;
  currency?: string;
}) {
  const activeRates = options.gst_rates.filter((row) => row.active).map((row) => String(row.rate));
  const rateOptions = activeRates.length ? activeRates : FALLBACK_RATES;
  const defaultRate = rateOptions.includes("18") ? "18" : rateOptions[0];

  const [placeCode, setPlaceCode] = useState(options.supplier_state.code ?? "");
  const [pricingMode, setPricingMode] = useState<"exclusive" | "inclusive">("exclusive");
  const [otherCharges, setOtherCharges] = useState("0");
  const [roundToRupee, setRoundToRupee] = useState(true);
  const [lines, setLines] = useState<CalcLine[]>([newLine(1, defaultRate)]);
  const [result, setResult] = useState<GstCalculation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const supplierLabel = useMemo(() => {
    if (!options.supplier_state.code) return "Not set in GST settings";
    return `${options.supplier_state.name ?? "Your state"} (${options.supplier_state.code})`;
  }, [options.supplier_state]);

  const patchLine = (key: number, patch: Partial<CalcLine>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));

  const removeLine = (key: number) =>
    setLines((current) => (current.length === 1 ? current : current.filter((line) => line.key !== key)));

  const addLine = () =>
    setLines((current) => [...current, newLine(Math.max(...current.map((line) => line.key)) + 1, defaultRate)]);

  const calculate = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        supplier_state_code: options.supplier_state.code || undefined,
        place_of_supply_state_code: placeCode || undefined,
        other_charges: otherCharges || "0",
        round_to_rupee: roundToRupee,
        lines: lines.map((line) => ({
          quantity: line.quantity || "0",
          unit_price: line.unit_price || "0",
          discount: line.discount || "0",
          gst_rate: line.gst_rate,
          pricing_mode: pricingMode,
        })),
      };
      setResult(await post<GstCalculation>("/tax/gst/calculate", payload));
    } catch (err: unknown) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardHeader
          title="GST calculator"
          description="Inclusive or exclusive pricing, with the CGST/SGST or IGST split"
          icon={Calculator}
          actions={
            <Button size="sm" icon={Plus} variant="outline" onClick={addLine}>
              Add line
            </Button>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Supplier state" hint="From your GST settings">
              <Input value={supplierLabel} readOnly disabled />
            </Field>
            <Field label="Place of supply" hint="Decides intra-state or inter-state">
              <Select value={placeCode} onChange={(event) => setPlaceCode(event.target.value)}>
                <option value="">Select a state</option>
                {options.states.map((state) => (
                  <option key={state.code} value={state.code}>
                    {state.code} · {state.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Price basis">
              <Select
                value={pricingMode}
                onChange={(event) => setPricingMode(event.target.value as "exclusive" | "inclusive")}
              >
                <option value="exclusive">GST added on top</option>
                <option value="inclusive">GST already included</option>
              </Select>
            </Field>
            <Field label="Other charges" hint="Freight or packing, taxed at the line rates">
              <Input
                inputMode="decimal"
                value={otherCharges}
                onChange={(event) => setOtherCharges(event.target.value)}
              />
            </Field>
          </div>

          <div className="space-y-2">
            {lines.map((line, index) => (
              <div
                key={line.key}
                className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50/60 p-3 sm:grid-cols-[64px_minmax(0,1fr)_minmax(0,1fr)_72px_96px_36px] sm:items-end"
              >
                <Field label="Qty">
                  <Input
                    inputMode="decimal"
                    value={line.quantity}
                    onChange={(event) => patchLine(line.key, { quantity: event.target.value })}
                    aria-label={`Line ${index + 1} quantity`}
                  />
                </Field>
                <Field label="Unit price">
                  <Input
                    inputMode="decimal"
                    value={line.unit_price}
                    placeholder="0.00"
                    onChange={(event) => patchLine(line.key, { unit_price: event.target.value })}
                    aria-label={`Line ${index + 1} unit price`}
                  />
                </Field>
                <Field label="Discount">
                  <Input
                    inputMode="decimal"
                    value={line.discount}
                    onChange={(event) => patchLine(line.key, { discount: event.target.value })}
                    aria-label={`Line ${index + 1} discount`}
                  />
                </Field>
                <Field label="GST %">
                  <Select
                    value={line.gst_rate}
                    onChange={(event) => patchLine(line.key, { gst_rate: event.target.value })}
                    aria-label={`Line ${index + 1} GST rate`}
                  >
                    {rateOptions.map((rate) => (
                      <option key={rate} value={rate}>
                        {rate}%
                      </option>
                    ))}
                  </Select>
                </Field>
                <div className="pb-1 text-right sm:pb-2">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Line</p>
                  <p className="tabular text-sm font-semibold text-ink-900">
                    {moneyExact(
                      Math.max(
                        Number(line.quantity || 0) * Number(line.unit_price || 0) -
                          Number(line.discount || 0),
                        0,
                      ),
                      currency,
                    )}
                  </p>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => removeLine(line.key)}
                  disabled={lines.length === 1}
                  aria-label={`Remove line ${index + 1}`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>

          <label className="flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300"
              checked={roundToRupee}
              onChange={(event) => setRoundToRupee(event.target.checked)}
            />
            Round the invoice total to the nearest rupee
          </label>

          {error && <Callout tone="red" title="Could not calculate">{error}</Callout>}

          <div className="flex justify-end">
            <Button icon={Calculator} loading={busy} onClick={() => void calculate()}>
              Calculate GST
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Breakdown" description={result ? `${result.supplier_state} → ${result.place_of_supply_state}` : "Nothing calculated yet"} />
        <CardBody className="space-y-4">
          {!result ? (
            <div className="space-y-3 text-sm text-slate-500">
              <p>Enter the lines and calculate to see the taxable value, the CGST/SGST or IGST split and the invoice total.</p>
              <p className="text-xs text-slate-400">{options.note}</p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={result.supply_type === "intra_state" ? "blue" : "violet"}>
                  {result.supply_type === "intra_state" ? "Intra-state · CGST + SGST" : "Inter-state · IGST"}
                </Badge>
                <Badge tone="slate">Calculated only · not saved</Badge>
              </div>

              <dl className="space-y-2 text-sm">
                <Row label="Taxable value" value={moneyExact(result.totals.taxable_value, currency)} />
                <Row label="CGST" value={moneyExact(result.totals.cgst_amount, currency)} />
                <Row label="SGST" value={moneyExact(result.totals.sgst_amount, currency)} />
                <Row label="IGST" value={moneyExact(result.totals.igst_amount, currency)} />
                <Row label="Other charges" value={moneyExact(result.totals.other_charges, currency)} />
                <Row label="Rounding" value={moneyExact(result.totals.rounding_adjustment, currency)} />
                <div className="flex items-center justify-between border-t border-slate-200 pt-2 text-base font-semibold text-ink-900">
                  <dt>Invoice total</dt>
                  <dd className="tabular">{moneyExact(result.totals.total_amount, currency)}</dd>
                </div>
              </dl>

              <TableWrap>
                <THead>
                  <TR>
                    <TH>Line</TH>
                    <TH className="text-right">GST</TH>
                    <TH className="text-right">Tax</TH>
                    <TH className="text-right">Total</TH>
                  </TR>
                </THead>
                <TBody>
                  {result.lines.map((line, index) => (
                    <TR key={index}>
                      <TD>
                        {line.quantity} × {moneyExact(line.unit_price, currency)}
                        <span className="ml-1 text-[11px] text-slate-400">({line.pricing_mode})</span>
                      </TD>
                      <TD className="text-right">{plainPct(line.gst_rate)}</TD>
                      <TD className="text-right tabular">{moneyExact(line.gst_amount, currency)}</TD>
                      <TD className="text-right tabular">{moneyExact(line.final_amount, currency)}</TD>
                    </TR>
                  ))}
                </TBody>
              </TableWrap>
              <p className="text-xs leading-relaxed text-slate-500">{result.note}</p>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-slate-600">
      <dt>{label}</dt>
      <dd className="tabular font-medium text-ink-900">{value}</dd>
    </div>
  );
}
