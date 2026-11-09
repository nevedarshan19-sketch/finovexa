import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, post } from "../../lib/api";
import type {
  GstCalculation,
  IncomeTaxComparison,
  IncomeTaxResult,
  IncomeTaxRules,
  TaxGstOptions,
  TaxRuleSet,
} from "../../lib/taxTypes";
import { GstCalculator } from "./GstCalculator";
import { IncomeTaxPanel } from "./IncomeTaxPanel";

vi.mock("../../lib/api", () => ({
  api: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  getErrorMessage: (error: unknown) =>
    error instanceof Error ? error.message : "Request failed",
}));

vi.mock("../../context/ToastContext", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

const apiMock = vi.mocked(api);
const postMock = vi.mocked(post);

afterEach(() => {
  apiMock.mockReset();
  postMock.mockReset();
});

const options: TaxGstOptions = {
  states: [
    { code: "27", name: "Maharashtra" },
    { code: "29", name: "Karnataka" },
  ],
  supplier_state: { name: "Maharashtra", code: "27" },
  gst_rates: [
    { rate: 0, label: "Nil", active: true },
    { rate: 18, label: "18%", active: true },
  ],
  hsn: [],
  hsn_coverage: { invoice_lines: 0, lines_without_hsn: 0, verified_codes: 0 },
  note: "Rates come from your GST settings.",
};

const calculation: GstCalculation = {
  supply_type: "intra_state",
  supplier_state: "Maharashtra",
  supplier_state_code: "27",
  place_of_supply_state: "Maharashtra",
  place_of_supply_state_code: "27",
  lines: [
    {
      quantity: 10,
      unit_price: 100,
      gross_amount: 1000,
      discount: 0,
      taxable_value: 1000,
      gst_rate: 18,
      gst_amount: 180,
      cgst_amount: 90,
      sgst_amount: 90,
      igst_amount: 0,
      final_amount: 1180,
      pricing_mode: "exclusive",
    },
  ],
  totals: {
    subtotal: 1000,
    discount: 0,
    taxable_value: 1000,
    cgst_amount: 90,
    sgst_amount: 90,
    igst_amount: 0,
    tax_amount: 180,
    other_charges: 0,
    rounding_adjustment: 0,
    total_amount: 1180,
  },
  currency: "INR",
  status: "calculated",
  note: "Calculated only, nothing was saved.",
};

describe("GstCalculator", () => {
  it("posts the lines and shows the CGST/SGST split", async () => {
    postMock.mockResolvedValue(calculation);
    render(<GstCalculator options={options} />);

    fireEvent.change(screen.getByLabelText("Line 1 quantity"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Line 1 unit price"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: /calculate gst/i }));

    await screen.findByText("Intra-state · CGST + SGST");
    expect(postMock).toHaveBeenCalledWith(
      "/tax/gst/calculate",
      expect.objectContaining({
        place_of_supply_state_code: "27",
        lines: [expect.objectContaining({ quantity: "10", unit_price: "100", gst_rate: "18" })],
      }),
    );
    expect(screen.getByText("Calculated only · not saved")).toBeInTheDocument();
  });

  it("shows the validation message returned by the API", async () => {
    postMock.mockRejectedValue(new Error("Pick the place of supply state before calculating GST."));
    render(<GstCalculator options={options} />);

    fireEvent.click(screen.getByRole("button", { name: /calculate gst/i }));

    expect(await screen.findByText("Could not calculate")).toBeInTheDocument();
    expect(
      screen.getByText("Pick the place of supply state before calculating GST."),
    ).toBeInTheDocument();
  });

  it("adds and removes lines", () => {
    render(<GstCalculator options={options} />);
    fireEvent.click(screen.getByRole("button", { name: /add line/i }));
    expect(screen.getByLabelText("Line 2 quantity")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /remove line 2/i }));
    expect(screen.queryByLabelText("Line 2 quantity")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove line 1/i })).toBeDisabled();
  });
});

function ruleSet(regime: "new" | "old"): TaxRuleSet {
  return {
    id: regime === "new" ? 2 : 1,
    financial_year: "2025-26",
    assessment_year: "2026-27",
    regime,
    regime_label: regime === "new" ? "New regime" : "Old regime",
    version: "FA2025",
    status: "published",
    effective_from: "2025-04-01",
    effective_to: "2026-03-31",
    source_note: "Published Finance Act slabs.",
    slabs:
      regime === "new"
        ? [
            { from: 0, to: 400000, rate: 0 },
            { from: 400000, to: null, rate: 30 },
          ]
        : [
            { from: 0, to: 250000, rate: 0 },
            { from: 250000, to: null, rate: 30 },
          ],
    surcharge_bands: [{ income_above: 5000000, rate: 10 }],
    rebate: { income_limit: 1200000, max_rebate: 60000, marginal_relief: true, note: null },
    constants: [{ code: "cess_percent", value: 4, description: "Cess" }],
    deductions: [],
    capital_gains: [],
  };
}

const rulesPayload: IncomeTaxRules = {
  financial_years: ["2025-26"],
  financial_year: "2025-26",
  assessment_year: "2026-27",
  rule_sets: [ruleSet("new"), ruleSet("old")],
  disclaimer: "Estimate only. Confirm every figure with a chartered accountant before filing.",
  current_financial_year: "2025-26",
  today: "2026-11-01",
};

function result(regime: "new" | "old", liability: number): IncomeTaxResult {
  return {
    financial_year: "2025-26",
    assessment_year: "2026-27",
    regime,
    regime_label: regime === "new" ? "New regime" : "Old regime",
    rule_set_id: regime === "new" ? 2 : 1,
    rule_version: "FA2025",
    rule_source_note: "Published Finance Act slabs.",
    currency: "INR",
    status: "estimate",
    income: {
      salary: {
        gross_salary: 1500000,
        basic_salary: 600000,
        hra_received: 0,
        hra_exemption: 0,
        standard_deduction: 75000,
        professional_tax: 0,
        net_salary: 1425000,
      },
      business: { basis: "Net profit from books", net_profit: 0, gross_receipts: 0, income: 0 },
      other_income: 0,
      capital_gains: { equity_stcg: 0, equity_ltcg: 0, other_ltcg: 0, other_stcg: 0 },
      gross_total_income: 1425000,
    },
    deductions: { items: [], total: 0 },
    total_income: 1425000,
    tax: {
      slab_income: 1425000,
      slabs: [{ from: 0, to: null, rate: 30, taxable: 1425000, tax: liability / 1.04 }],
      slab_tax: liability / 1.04,
      rebate_87a: 0,
      rebate_marginal_relief: 0,
      capital_gains: [],
      capital_gains_tax: 0,
      tax_before_surcharge: liability / 1.04,
      surcharge_rate: 0,
      surcharge: 0,
      surcharge_marginal_relief: 0,
      cess_rate: 4,
      cess: liability - liability / 1.04,
      total_liability: liability,
      rounding_adjustment: 0,
    },
    effective_rate_pct: 6.84,
    monthly_estimate: liability / 12,
    notes: ["Total income rounded to the nearest 10 for display."],
    disclaimer: rulesPayload.disclaimer,
  };
}

const comparison: IncomeTaxComparison = {
  financial_year: "2025-26",
  assessment_year: "2026-27",
  regimes: { new: result("new", 97500), old: result("old", 257400) },
  recommended_regime: "new",
  savings: 159900,
  disclaimer: rulesPayload.disclaimer,
};

function mockIncomeEndpoints() {
  apiMock.mockImplementation((path: string) => {
    if (path.startsWith("/tax/income/rules")) return Promise.resolve(rulesPayload);
    if (path.startsWith("/tax/income/estimates")) return Promise.resolve({ items: [] });
    return Promise.resolve({});
  });
}

describe("IncomeTaxPanel", () => {
  it("compares both regimes and marks the recommended one", async () => {
    mockIncomeEndpoints();
    postMock.mockResolvedValue(comparison);
    render(<IncomeTaxPanel />);

    await screen.findByText(/AY 2026-27/);
    fireEvent.change(screen.getByLabelText("Gross salary"), { target: { value: "1500000" } });
    fireEvent.click(screen.getByRole("button", { name: /compare both regimes/i }));

    await screen.findByText(/gives the lower estimate/);
    expect(postMock).toHaveBeenCalledWith(
      "/tax/income/compare",
      expect.objectContaining({
        financial_year: "2025-26",
        inputs: expect.objectContaining({
          salary: expect.objectContaining({ gross_salary: "1500000" }),
        }),
      }),
    );
    expect(screen.getByText("recommended")).toBeInTheDocument();
    expect(screen.getAllByText("Rule version FA2025").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Estimated liability").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Estimate only/).length).toBeGreaterThan(0);
  });

  it("saves the recommended estimate as a draft", async () => {
    mockIncomeEndpoints();
    postMock.mockResolvedValueOnce(comparison).mockResolvedValueOnce({ id: 7, status: "draft" });
    render(<IncomeTaxPanel />);

    await screen.findByText(/AY 2026-27/);
    fireEvent.click(screen.getByRole("button", { name: /compare both regimes/i }));
    await screen.findByRole("button", { name: /save as draft/i });
    fireEvent.click(screen.getByRole("button", { name: /save as draft/i }));

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/tax/income/estimates",
        expect.objectContaining({ financial_year: "2025-26" }),
      ),
    );
    expect(postMock.mock.calls[1][1]).not.toHaveProperty("regime");
  });

  it("surfaces a validation error from the engine", async () => {
    mockIncomeEndpoints();
    postMock.mockRejectedValue(new Error("Total income cannot be negative."));
    render(<IncomeTaxPanel />);

    await screen.findByText(/AY 2026-27/);
    fireEvent.click(screen.getByRole("button", { name: /compare both regimes/i }));

    expect(await screen.findByText("Could not estimate")).toBeInTheDocument();
    expect(screen.getByText("Total income cannot be negative.")).toBeInTheDocument();
  });
});
