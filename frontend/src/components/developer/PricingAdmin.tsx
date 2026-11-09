import { useEffect, useState } from "react";
import { BadgeIndianRupee, History, Percent, Plus, RefreshCw, Save } from "lucide-react";
import { useApi } from "../../hooks/useApi";
import { getErrorMessage, patch, post, put } from "../../lib/api";
import type {
  AdminITRPrice,
  AdminPricingAddon,
  AdminPricingResponse,
  AdminSoftwareTier,
} from "../../lib/pricingTypes";
import { formatDateTime, money } from "../../lib/utils";
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
  PageSkeleton,
  Select,
  TableWrap,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Textarea,
} from "../ui";

interface RulesForm {
  benchmark_percent: string;
  annual_discount_percent: string;
  quote_validity_days: string;
  tax_rate_percent: string;
  tax_note: string;
  terms: string;
}

const EMPTY_RULES: RulesForm = {
  benchmark_percent: "",
  annual_discount_percent: "",
  quote_validity_days: "",
  tax_rate_percent: "",
  tax_note: "",
  terms: "",
};

function numberValue(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function PricingAdmin() {
  const api = useApi<AdminPricingResponse>("/developer/pricing");
  const [rules, setRules] = useState<RulesForm>(EMPTY_RULES);
  const [tiers, setTiers] = useState<AdminSoftwareTier[]>([]);
  const [itrPrices, setItrPrices] = useState<AdminITRPrice[]>([]);
  const [addons, setAddons] = useState<AdminPricingAddon[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [addonOpen, setAddonOpen] = useState(false);
  const [addonForm, setAddonForm] = useState({
    key: "",
    label: "",
    description: "",
    amount: "",
    cadence: "annual" as "annual" | "one_time",
    is_active: true,
  });
  const [addonError, setAddonError] = useState<string | null>(null);

  const data = api.data;

  useEffect(() => {
    if (!data) return;
    setRules({
      benchmark_percent: String(data.settings.benchmark_percent),
      annual_discount_percent: String(data.settings.annual_discount_percent),
      quote_validity_days: String(data.settings.quote_validity_days),
      tax_rate_percent: String(data.settings.tax_rate_percent),
      tax_note: data.settings.tax_note,
      terms: data.settings.terms,
    });
    setTiers(data.software_tiers);
    setItrPrices(data.itr_prices);
    setAddons(data.addons);
  }, [data]);

  if (api.loading && !data) return <PageSkeleton cards={4} />;
  if (api.error && !data) return <ErrorState message={api.error} onRetry={api.reload} />;
  if (!data) return null;

  const discount = numberValue(rules.annual_discount_percent);
  const tierAnnual = (monthly: number) => monthly * 12 * (1 - discount / 100);

  const run = async (key: string, task: () => Promise<unknown>, message: string) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await task();
      setNotice(message);
      api.reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const saveRules = () =>
    run(
      "rules",
      () =>
        put("/developer/pricing/rules", {
          benchmark_percent: numberValue(rules.benchmark_percent),
          annual_discount_percent: numberValue(rules.annual_discount_percent),
          quote_validity_days: Number(rules.quote_validity_days) || 1,
          tax_rate_percent: numberValue(rules.tax_rate_percent),
          tax_note: rules.tax_note,
          terms: rules.terms,
        }),
      "Pricing rules saved. New quotations and the public pricing page use these values.",
    );

  const saveTier = (tier: AdminSoftwareTier) =>
    run(
      `tier-${tier.id}`,
      () =>
        put(`/developer/pricing/software/${tier.id}`, {
          label: tier.label,
          turnover_min: tier.turnover_min,
          turnover_max: tier.turnover_max,
          monthly_price: tier.monthly_price,
          description: tier.description,
          is_active: tier.is_active,
        }),
      `${tier.label} updated.`,
    );

  const saveItr = (row: AdminITRPrice) =>
    run(
      `itr-${row.id}`,
      () =>
        put(`/developer/pricing/itr/${row.id}`, {
          label: row.label,
          description: row.description,
          price_min: row.price_min,
          price_max: row.price_max,
          is_active: row.is_active,
        }),
      `${row.label} updated.`,
    );

  const saveAddon = (addon: AdminPricingAddon) =>
    run(
      `addon-${addon.id}`,
      () =>
        patch(`/developer/pricing/addons/${addon.id}`, {
          label: addon.label,
          description: addon.description,
          amount: addon.amount,
          cadence: addon.cadence,
          is_active: addon.is_active,
        }),
      `${addon.label} updated.`,
    );

  const createAddon = async () => {
    setAddonError(null);
    if (!/^[a-z0-9_]{2,40}$/.test(addonForm.key)) {
      setAddonError("Use lowercase letters, numbers and underscores for the key.");
      return;
    }
    if (addonForm.label.trim().length < 2) {
      setAddonError("Give the additional charge a label.");
      return;
    }
    setBusy("addon-create");
    try {
      await post("/developer/pricing/addons", {
        key: addonForm.key,
        label: addonForm.label.trim(),
        description: addonForm.description.trim(),
        amount: addonForm.amount ? addonForm.amount : null,
        cadence: addonForm.cadence,
        is_active: addonForm.is_active,
      });
      setAddonOpen(false);
      setAddonForm({
        key: "",
        label: "",
        description: "",
        amount: "",
        cadence: "annual",
        is_active: true,
      });
      setNotice("Additional charge created.");
      api.reload();
    } catch (err) {
      setAddonError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <Callout tone="amber" title="Every price is configurable">
        These values drive the public pricing page, the accounting quotation benchmark and the senior
        accountant workspace. Saving a change writes a price-history entry and a developer audit event.
        Annual billing never applies a discount unless one is configured here.
      </Callout>

      {error && (
        <Callout tone="red" title="That change did not save">
          {error}
        </Callout>
      )}
      {notice && (
        <Callout tone="green" title="Pricing updated">
          {notice}
        </Callout>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-slate-500">
          Last updated{" "}
          {data.settings.updated_at ? formatDateTime(data.settings.updated_at) : "at seed time"}
        </p>
        <Button variant="outline" size="sm" icon={RefreshCw} onClick={api.reload}>
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader
          title="Quotation rules and annual billing"
          description="The 2% benchmark is indicative only. Quotation totals always require senior approval."
          icon={Percent}
        />
        <CardBody className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Benchmark % of annual turnover" htmlFor="pricing_benchmark">
            <Input
              id="pricing_benchmark"
              inputMode="decimal"
              value={rules.benchmark_percent}
              onChange={(event) => setRules({ ...rules, benchmark_percent: event.target.value })}
            />
          </Field>
          <Field
            label="Annual billing discount %"
            htmlFor="pricing_discount"
            hint="0 means no discount is applied."
          >
            <Input
              id="pricing_discount"
              inputMode="decimal"
              value={rules.annual_discount_percent}
              onChange={(event) =>
                setRules({ ...rules, annual_discount_percent: event.target.value })
              }
            />
          </Field>
          <Field label="Quotation validity (days)" htmlFor="pricing_validity">
            <Input
              id="pricing_validity"
              inputMode="numeric"
              value={rules.quote_validity_days}
              onChange={(event) => setRules({ ...rules, quote_validity_days: event.target.value })}
            />
          </Field>
          <Field label="Tax rate % (disclosed separately)" htmlFor="pricing_tax">
            <Input
              id="pricing_tax"
              inputMode="decimal"
              value={rules.tax_rate_percent}
              onChange={(event) => setRules({ ...rules, tax_rate_percent: event.target.value })}
            />
          </Field>
          <Field label="Tax disclosure" htmlFor="pricing_tax_note" className="sm:col-span-2">
            <Textarea
              id="pricing_tax_note"
              value={rules.tax_note}
              onChange={(event) => setRules({ ...rules, tax_note: event.target.value })}
              className="min-h-[70px] text-xs"
            />
          </Field>
          <Field label="Quotation terms" htmlFor="pricing_terms" className="sm:col-span-2">
            <Textarea
              id="pricing_terms"
              value={rules.terms}
              onChange={(event) => setRules({ ...rules, terms: event.target.value })}
              className="min-h-[70px] text-xs"
            />
          </Field>
          <div className="sm:col-span-2 lg:col-span-4">
            <Button icon={Save} loading={busy === "rules"} onClick={() => void saveRules()}>
              Save rules
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Software subscription prices"
          description="Monthly list prices by annual turnover band. Annual billing uses the configured discount."
          icon={BadgeIndianRupee}
          actions={<Badge tone={discount > 0 ? "green" : "slate"}>{discount > 0 ? `${discount}% annual discount` : "No annual discount"}</Badge>}
        />
        <CardBody className="p-0">
          <TableWrap>
            <THead>
              <TR>
                <TH>Plan</TH>
                <TH>Turnover band (INR)</TH>
                <TH>Monthly</TH>
                <TH>Annual effective</TH>
                <TH>Active</TH>
                <TH className="text-right">Save</TH>
              </TR>
            </THead>
            <TBody>
              {tiers.map((tier) => (
                <TR key={tier.id}>
                  <TD>
                    <Input
                      value={tier.label}
                      onChange={(event) =>
                        setTiers((rows) =>
                          rows.map((row) =>
                            row.id === tier.id ? { ...row, label: event.target.value } : row,
                          ),
                        )
                      }
                      className="text-xs"
                      aria-label="Plan label"
                    />
                  </TD>
                  <TD>
                    <div className="flex items-center gap-1">
                      <Input
                        inputMode="decimal"
                        value={String(tier.turnover_min)}
                        onChange={(event) =>
                          setTiers((rows) =>
                            rows.map((row) =>
                              row.id === tier.id
                                ? { ...row, turnover_min: numberValue(event.target.value) }
                                : row,
                            ),
                          )
                        }
                        className="w-28 text-right text-xs"
                        aria-label="Turnover minimum"
                      />
                      <span className="text-[10px] text-slate-400">to</span>
                      <Input
                        inputMode="decimal"
                        value={tier.turnover_max === null ? "" : String(tier.turnover_max)}
                        onChange={(event) =>
                          setTiers((rows) =>
                            rows.map((row) =>
                              row.id === tier.id
                                ? {
                                    ...row,
                                    turnover_max: event.target.value
                                      ? numberValue(event.target.value)
                                      : null,
                                  }
                                : row,
                            ),
                          )
                        }
                        placeholder="No limit"
                        className="w-28 text-right text-xs"
                        aria-label="Turnover maximum"
                      />
                    </div>
                  </TD>
                  <TD>
                    <Input
                      inputMode="decimal"
                      value={String(tier.monthly_price)}
                      onChange={(event) =>
                        setTiers((rows) =>
                          rows.map((row) =>
                            row.id === tier.id
                              ? { ...row, monthly_price: numberValue(event.target.value) }
                              : row,
                          ),
                        )
                      }
                      className="w-24 text-right text-xs"
                      aria-label="Monthly price"
                    />
                  </TD>
                  <TD className="whitespace-nowrap text-[11.5px] font-semibold text-ink-900">
                    {money(tierAnnual(tier.monthly_price))}
                  </TD>
                  <TD>
                    <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-600">
                      <input
                        type="checkbox"
                        checked={tier.is_active}
                        onChange={(event) =>
                          setTiers((rows) =>
                            rows.map((row) =>
                              row.id === tier.id ? { ...row, is_active: event.target.checked } : row,
                            ),
                          )
                        }
                        className="h-3.5 w-3.5 accent-brand-600"
                      />
                      {tier.is_active ? "Shown" : "Hidden"}
                    </label>
                  </TD>
                  <TD className="text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      icon={Save}
                      loading={busy === `tier-${tier.id}`}
                      onClick={() => void saveTier(tier)}
                    >
                      Save
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </TableWrap>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="ITR filing prices"
          description="ITR is a separate paid service and is never included automatically in an accounting subscription."
          icon={BadgeIndianRupee}
        />
        <CardBody className="p-0">
          <TableWrap>
            <THead>
              <TR>
                <TH>Return</TH>
                <TH>From (INR)</TH>
                <TH>To (INR)</TH>
                <TH>Active</TH>
                <TH className="text-right">Save</TH>
              </TR>
            </THead>
            <TBody>
              {itrPrices.map((row) => (
                <TR key={row.id}>
                  <TD>
                    <Input
                      value={row.label}
                      onChange={(event) =>
                        setItrPrices((rows) =>
                          rows.map((item) =>
                            item.id === row.id ? { ...item, label: event.target.value } : item,
                          ),
                        )
                      }
                      className="text-xs"
                      aria-label="ITR label"
                    />
                    <p className="mt-1 text-[10px] text-slate-400">{row.key}</p>
                  </TD>
                  <TD>
                    <Input
                      inputMode="decimal"
                      value={String(row.price_min)}
                      onChange={(event) =>
                        setItrPrices((rows) =>
                          rows.map((item) =>
                            item.id === row.id
                              ? { ...item, price_min: numberValue(event.target.value) }
                              : item,
                          ),
                        )
                      }
                      className="w-28 text-right text-xs"
                      aria-label="ITR minimum price"
                    />
                  </TD>
                  <TD>
                    <Input
                      inputMode="decimal"
                      value={row.price_max === null ? "" : String(row.price_max)}
                      onChange={(event) =>
                        setItrPrices((rows) =>
                          rows.map((item) =>
                            item.id === row.id
                              ? {
                                  ...item,
                                  price_max: event.target.value
                                    ? numberValue(event.target.value)
                                    : null,
                                }
                              : item,
                          ),
                        )
                      }
                      placeholder="Fixed"
                      className="w-28 text-right text-xs"
                      aria-label="ITR maximum price"
                    />
                  </TD>
                  <TD>
                    <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-600">
                      <input
                        type="checkbox"
                        checked={row.is_active}
                        onChange={(event) =>
                          setItrPrices((rows) =>
                            rows.map((item) =>
                              item.id === row.id ? { ...item, is_active: event.target.checked } : item,
                            ),
                          )
                        }
                        className="h-3.5 w-3.5 accent-brand-600"
                      />
                      {row.is_active ? "Shown" : "Hidden"}
                    </label>
                  </TD>
                  <TD className="text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      icon={Save}
                      loading={busy === `itr-${row.id}`}
                      onClick={() => void saveItr(row)}
                    >
                      Save
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </TableWrap>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Additional charges"
          description="Optional add-ons that a senior accountant can include in a quotation."
          icon={BadgeIndianRupee}
          actions={
            <Button size="sm" icon={Plus} onClick={() => setAddonOpen(true)}>
              New charge
            </Button>
          }
        />
        <CardBody className="p-0">
          {addons.length === 0 ? (
            <EmptyState
              title="No additional charges"
              description="Create an add-on such as a payroll per-employee charge or a one-time cleanup fee."
              icon={BadgeIndianRupee}
            />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>Charge</TH>
                  <TH>Amount (INR)</TH>
                  <TH>Cadence</TH>
                  <TH>Active</TH>
                  <TH className="text-right">Save</TH>
                </TR>
              </THead>
              <TBody>
                {addons.map((addon) => (
                  <TR key={addon.id}>
                    <TD>
                      <Input
                        value={addon.label}
                        onChange={(event) =>
                          setAddons((rows) =>
                            rows.map((row) =>
                              row.id === addon.id ? { ...row, label: event.target.value } : row,
                            ),
                          )
                        }
                        className="text-xs"
                        aria-label="Add-on label"
                      />
                      <p className="mt-1 text-[10px] text-slate-400">{addon.key}</p>
                    </TD>
                    <TD>
                      <Input
                        inputMode="decimal"
                        value={addon.amount === null ? "" : String(addon.amount)}
                        placeholder="Quoted after review"
                        onChange={(event) =>
                          setAddons((rows) =>
                            rows.map((row) =>
                              row.id === addon.id
                                ? {
                                    ...row,
                                    amount: event.target.value
                                      ? numberValue(event.target.value)
                                      : null,
                                  }
                                : row,
                            ),
                          )
                        }
                        className="w-32 text-right text-xs"
                        aria-label="Add-on amount"
                      />
                    </TD>
                    <TD>
                      <Select
                        value={addon.cadence}
                        onChange={(event) =>
                          setAddons((rows) =>
                            rows.map((row) =>
                              row.id === addon.id
                                ? { ...row, cadence: event.target.value as "annual" | "one_time" }
                                : row,
                            ),
                          )
                        }
                        className="w-32 text-xs"
                        aria-label="Add-on cadence"
                      >
                        <option value="annual">Annual</option>
                        <option value="one_time">One time</option>
                      </Select>
                    </TD>
                    <TD>
                      <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-600">
                        <input
                          type="checkbox"
                          checked={addon.is_active}
                          onChange={(event) =>
                            setAddons((rows) =>
                              rows.map((row) =>
                                row.id === addon.id
                                  ? { ...row, is_active: event.target.checked }
                                  : row,
                              ),
                            )
                          }
                          className="h-3.5 w-3.5 accent-brand-600"
                        />
                        {addon.is_active ? "Shown" : "Hidden"}
                      </label>
                    </TD>
                    <TD className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        icon={Save}
                        loading={busy === `addon-${addon.id}`}
                        onClick={() => void saveAddon(addon)}
                      >
                        Save
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Price history"
          description="Every price field change is retained with the developer, timestamp and note."
          icon={History}
          actions={<Badge tone="slate">{data.history.length} entries</Badge>}
        />
        <CardBody className="p-0">
          {data.history.length === 0 ? (
            <EmptyState title="No price changes yet" description="Saved pricing changes appear here." icon={History} />
          ) : (
            <TableWrap>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Entity</TH>
                  <TH>Field</TH>
                  <TH>Change</TH>
                  <TH>Note</TH>
                </TR>
              </THead>
              <TBody>
                {data.history.map((row) => (
                  <TR key={row.id}>
                    <TD className="whitespace-nowrap text-[11px] text-slate-500">
                      {row.changed_at ? formatDateTime(row.changed_at) : "—"}
                    </TD>
                    <TD>
                      <Badge tone="slate">{row.entity_type}</Badge>
                      <p className="mt-1 text-[10px] text-slate-400">{row.entity_key}</p>
                    </TD>
                    <TD className="text-[11px] text-slate-600">{row.field}</TD>
                    <TD className="text-[11px] text-slate-600">
                      <span className="text-slate-400">{row.old_value ?? "—"}</span>
                      <span className="mx-1">→</span>
                      <span className="font-semibold text-ink-900">{row.new_value ?? "—"}</span>
                    </TD>
                    <TD className="text-[10.5px] text-slate-500">{row.note || "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </TableWrap>
          )}
        </CardBody>
      </Card>

      <Modal
        open={addonOpen}
        onClose={() => setAddonOpen(false)}
        title="New additional charge"
        description="A price of zero or blank means the charge is quoted after review."
        footer={
          <>
            <Button variant="outline" onClick={() => setAddonOpen(false)} disabled={busy === "addon-create"}>
              Cancel
            </Button>
            <Button icon={Plus} loading={busy === "addon-create"} onClick={() => void createAddon()}>
              Create charge
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {addonError && (
            <Callout tone="red" title="Could not create the charge">
              {addonError}
            </Callout>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Key" htmlFor="addon_key" required hint="Lowercase letters, numbers and underscores.">
              <Input
                id="addon_key"
                value={addonForm.key}
                onChange={(event) =>
                  setAddonForm({ ...addonForm, key: event.target.value.toLowerCase() })
                }
                placeholder="payroll_per_employee"
              />
            </Field>
            <Field label="Label" htmlFor="addon_label" required>
              <Input
                id="addon_label"
                value={addonForm.label}
                onChange={(event) => setAddonForm({ ...addonForm, label: event.target.value })}
                placeholder="Payroll per employee"
              />
            </Field>
          </div>
          <Field label="Description" htmlFor="addon_description">
            <Input
              id="addon_description"
              value={addonForm.description}
              onChange={(event) => setAddonForm({ ...addonForm, description: event.target.value })}
              placeholder="What this charge covers"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Amount (INR)" htmlFor="addon_amount" hint="Leave blank to quote after review.">
              <Input
                id="addon_amount"
                inputMode="decimal"
                value={addonForm.amount}
                onChange={(event) => setAddonForm({ ...addonForm, amount: event.target.value })}
              />
            </Field>
            <Field label="Cadence" htmlFor="addon_cadence">
              <Select
                id="addon_cadence"
                value={addonForm.cadence}
                onChange={(event) =>
                  setAddonForm({
                    ...addonForm,
                    cadence: event.target.value as "annual" | "one_time",
                  })
                }
              >
                <option value="annual">Annual</option>
                <option value="one_time">One time</option>
              </Select>
            </Field>
          </div>
          <label className="flex items-center gap-2 text-[11.5px] text-slate-600">
            <input
              type="checkbox"
              checked={addonForm.is_active}
              onChange={(event) => setAddonForm({ ...addonForm, is_active: event.target.checked })}
              className="h-4 w-4 accent-brand-600"
            />
            Available to senior accountants
          </label>
        </div>
      </Modal>
    </div>
  );
}
