import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InvoiceDocument } from "./InvoiceDocument";
import type { Invoice } from "../lib/types";

function invoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 1,
    number: "INV-GST-1",
    customer: {
      id: 2,
      name: "GST Buyer",
      email: "buyer@example.com",
      company: null,
      gstin: "27AAAAA0000A1Z5",
      billing_address: "12 Buyer Street\nMumbai",
      state: "Maharashtra",
      state_code: "27",
    },
    issue_date: "2026-10-20",
    due_date: "2026-11-04",
    currency: "INR",
    status: "issued",
    base_status: "issued",
    subtotal: 2000,
    tax: 360,
    total: 2360,
    paid: 0,
    outstanding: 2360,
    aging_days: 0,
    aging_bucket: "current",
    notes: null,
    items: [
      {
        description: "Ergonomic chair",
        name: "Ergonomic chair",
        hsn_sac: "9401",
        quantity: 2,
        unit_price: 1000,
        line_total: 2000,
        taxable_value: 2000,
        gst_rate: 18,
        gst_amount: 360,
        final_amount: 2360,
      },
    ],
    payments: [],
    created_by: null,
    pricing_mode: "exclusive",
    supply_type: "intra_state",
    supplier: {
      name: "Northstar Supply",
      gstin: "27BBBBB0000B1Z5",
      address: "Unit 4, Mumbai",
      state: "Maharashtra",
      state_code: "27",
    },
    place_of_supply: { state: "Maharashtra", state_code: "27" },
    supply_verified: true,
    discount: 0,
    taxable_value: 2000,
    cgst: 180,
    sgst: 180,
    igst: 0,
    other_charges: 0,
    rounding_adjustment: 0,
    terms: null,
    ...overrides,
  };
}

describe("InvoiceDocument tax presentation", () => {
  it("shows CGST and SGST for a verified intra-state invoice", () => {
    render(<InvoiceDocument invoice={invoice()} />);
    expect(screen.getByText("CGST")).toBeInTheDocument();
    expect(screen.getByText("SGST")).toBeInTheDocument();
    expect(screen.queryByText("IGST")).not.toBeInTheDocument();
    expect(screen.getByText("Intra-state (CGST + SGST)")).toBeInTheDocument();
    expect(screen.getByText("Tax Invoice")).toBeInTheDocument();
  });

  it("shows IGST for a verified inter-state invoice", () => {
    render(
      <InvoiceDocument
        invoice={invoice({
          supply_type: "inter_state",
          cgst: 0,
          sgst: 0,
          igst: 360,
          place_of_supply: { state: "Karnataka", state_code: "29" },
        })}
      />,
    );
    expect(screen.getByText("IGST")).toBeInTheDocument();
    expect(screen.queryByText("CGST")).not.toBeInTheDocument();
    expect(screen.queryByText("SGST")).not.toBeInTheDocument();
  });

  it("never invents a split when the classification is unverified", () => {
    render(
      <InvoiceDocument
        invoice={invoice({
          supply_type: "unverified",
          supply_verified: false,
          cgst: 0,
          sgst: 0,
          igst: 0,
          supplier: {
            name: "Northstar Supply",
            gstin: null,
            address: null,
            state: null,
            state_code: null,
          },
          place_of_supply: { state: null, state_code: null },
        })}
      />,
    );
    expect(screen.getByText("Not verified")).toBeInTheDocument();
    expect(screen.queryByText("CGST")).not.toBeInTheDocument();
    expect(screen.queryByText("SGST")).not.toBeInTheDocument();
    expect(screen.queryByText("IGST")).not.toBeInTheDocument();
    const row = screen.getByText("GST (classification not verified)").closest("div");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("₹360.00")).toBeInTheDocument();
    expect(screen.getByText("Invoice")).toBeInTheDocument();
  });
});
