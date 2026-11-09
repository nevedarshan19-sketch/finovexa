import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadFile, get, post } from "../../lib/api";
import type {
  AccountingClient,
  TallyExportBatch,
  TallyExportCatalog,
  TallyValidationReport,
} from "../../lib/accountingTypes";
import { TallyIntegrationPage } from "./TallyIntegrationPage";

vi.mock("../../lib/api", () => {
  class MockApiError extends Error {
    status: number;
    payload: unknown;
    constructor(message: string, status = 400, payload?: unknown) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload;
    }
  }
  return {
    ApiError: MockApiError,
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    downloadFile: vi.fn(),
    getErrorMessage: (error: unknown) =>
      error instanceof Error ? error.message : "Request failed",
  };
});

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, full_name: "Riya Senior", email: "riya@finovexa.ai", role: "senior_accountant" },
    isSeniorAccountant: true,
  }),
}));

const getMock = vi.mocked(get);
const postMock = vi.mocked(post);
const downloadMock = vi.mocked(downloadFile);

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  downloadMock.mockReset();
});

const client: AccountingClient = {
  id: 7,
  code: "MER-001",
  business_name: "Meridian Interiors",
  contact_name: "Asha Rao",
  email: "asha@meridian.example",
  phone: null,
  business_type: "private_limited",
  turnover_range: "1_5_crore",
  gst_status: "regular",
  gstin: "27ABCDE1234F1Z5",
  pan_last4: "1Z5",
  financial_year: "2025-26",
  service_package: "gst_accounting",
  status: "active",
  customer_user_id: null,
  business_profile_id: null,
  linked_business: null,
  senior_accountant_user_id: 1,
  assigned_junior_user_id: 2,
  senior_name: "Riya Senior",
  junior_name: "Kunal Junior",
  onboarded_at: null,
  notes: null,
  created_at: "2026-04-01T09:00:00",
};

const catalog: TallyExportCatalog = {
  client_id: 7,
  client_name: client.business_name,
  client_gstin: client.gstin,
  types: [
    { key: "sales", label: "Sales Vouchers", record_count: 3, kind: "vouchers" },
    { key: "purchase", label: "Purchase Vouchers", record_count: 2, kind: "vouchers" },
    { key: "payment", label: "Payment Vouchers", record_count: 1, kind: "vouchers" },
    { key: "receipt", label: "Receipt Vouchers", record_count: 1, kind: "vouchers" },
    { key: "expense", label: "Expense Entries", record_count: 1, kind: "vouchers" },
    { key: "ledger_masters", label: "Ledger Masters", record_count: null, kind: "masters" },
    { key: "stock_masters", label: "Stock Item Masters", record_count: 3, kind: "masters" },
  ],
  stock_item_count: 3,
  formats: [
    { key: "xlsx", label: "Excel workbook (.xlsx)" },
    { key: "csv_zip", label: "CSV bundle + Tally XML (.zip)" },
    { key: "xml", label: "Tally XML (.xml)" },
    { key: "json", label: "Structured JSON (.json, TallyPrime 3.0+)" },
  ],
  tally_versions: [
    { key: "TallyPrime 5.0", formats: ["xlsx", "csv", "xml", "json"] },
    { key: "TallyPrime 4.1", formats: ["xlsx", "csv", "xml", "json"] },
    { key: "TallyPrime 3.0", formats: ["xlsx", "csv", "xml", "json"] },
    { key: "TallyPrime 2.0", formats: ["xlsx", "csv", "xml"] },
    { key: "Tally ERP 9", formats: ["xlsx", "csv", "xml"] },
  ],
  import_statuses: [{ key: "not_imported", label: "Not imported" }],
  note: "Files are generated for manual import into TallyPrime.",
};

const okReport: TallyValidationReport = {
  ok: true,
  client_id: 7,
  client_name: client.business_name,
  client_gstin: client.gstin,
  export_types: ["sales", "purchase"],
  period: { from: "2026-04-01", to: "2026-04-30" },
  summary: {
    voucher_count: 8,
    entry_count: 25,
    ledger_count: 14,
    stock_item_count: 3,
    debit_total: "413320.00",
    credit_total: "413320.00",
    balanced: true,
    by_type: [
      {
        export_type: "sales",
        label: "Sales Vouchers",
        voucher_count: 3,
        taxable_value: "271400.00",
        cgst: "13410.00",
        sgst: "13410.00",
        igst: "0.00",
        total: "298220.00",
        debit_total: "298220.00",
        credit_total: "298220.00",
      },
    ],
  },
  checks: [
    { key: "debit_credit", label: "Debit and credit balance", status: "passed", detail: "Both sides total 4,13,320.00." },
  ],
  errors: [],
  warnings: [],
  error_count: 0,
  warning_count: 0,
  checked_at: "2026-11-01T10:00:00",
  note: "Validation only reports issues; no figure was changed.",
};

const failingReport: TallyValidationReport = {
  ...okReport,
  ok: false,
  summary: { ...okReport.summary, balanced: false, credit_total: "413310.00" },
  checks: [
    { key: "debit_credit", label: "Debit and credit balance", status: "failed", detail: "Debit and credit differ by 10.00." },
  ],
  errors: [
    {
      severity: "error",
      code: "VOUCHER_UNBALANCED",
      message: "The debit and credit lines of this voucher do not balance.",
      voucher_type: "sale",
      voucher_number: "MT-1042",
      voucher_date: "2026-04-12",
      stored: "0.10",
    },
  ],
  warnings: [
    {
      severity: "warning",
      code: "PARTY_GSTIN_MISSING",
      message: "No GSTIN recorded for this party.",
      voucher_number: "MT-1043",
    },
  ],
  error_count: 1,
  warning_count: 1,
};

const approvedBatch: TallyExportBatch = {
  id: 12,
  client_id: 7,
  client_name: client.business_name,
  export_types: ["sales", "purchase"],
  type_labels: ["Sales Vouchers", "Purchase Vouchers"],
  file_format: "xlsx",
  tally_version: "TallyPrime 4.1",
  period_from: "2026-04-01",
  period_to: "2026-04-30",
  filename: "meridian-interiors-tally-2026-04-01-to-2026-04-30-batch-12.xlsx",
  file_sha256: "a".repeat(64),
  file_size: 20480,
  row_count: 41,
  voucher_count: 8,
  master_count: 14,
  error_count: 0,
  warning_count: 0,
  status: "approved",
  prepared_by_user_id: 2,
  prepared_by: "Kunal Junior",
  approved_by_user_id: 1,
  approved_by: "Riya Senior",
  approved_at: "2026-11-01T09:30:00",
  approval_note: null,
  import_status: "not_imported",
  import_note: null,
  created_at: "2026-11-01T09:00:00",
  details: {},
  download_url: "/api/accounting/tally/exports/12/download",
  validation: okReport,
};

const pendingBatch: TallyExportBatch = {
  ...approvedBatch,
  id: 13,
  status: "pending_approval",
  approved_by_user_id: null,
  approved_by: null,
  approved_at: null,
  download_url: null,
  filename: "meridian-interiors-tally-batch-13.xlsx",
};

const pendingList = { items: [pendingBatch], pending_approval_count: 1 };
const historyList = { items: [approvedBatch], pending_approval_count: 1 };

function mockGets() {
  getMock.mockImplementation(async (path: string) => {
    if (path === "/accounting/senior/clients") return { items: [client] };
    if (path.startsWith("/accounting/tally/catalog")) return catalog;
    if (path.startsWith("/accounting/tally/exports?status=pending_approval")) return pendingList;
    if (path.startsWith("/accounting/tally/exports?")) return historyList;
    if (path === "/accounting/tally/exports/13") return pendingBatch;
    if (path === "/accounting/tally/exports/12") return approvedBatch;
    if (path.startsWith("/accounting/tally/stock-items")) return { items: [] };
    throw new Error(`Unexpected GET ${path}`);
  });
}

describe("TallyIntegrationPage", () => {
  it("renders the export builder with catalog counts and validates a balanced batch", async () => {
    mockGets();
    postMock.mockResolvedValue(okReport);

    render(<TallyIntegrationPage />);

    expect(await screen.findByText(/Meridian Interiors/)).toBeInTheDocument();
    expect(await screen.findByText("3 voucher(s) in all periods")).toBeInTheDocument();
    expect(screen.getByText("Ledger masters built from recorded vouchers")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Validate" }));

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const [path, payload] = postMock.mock.calls[0];
    expect(path).toBe("/accounting/tally/exports/validate");
    expect(payload).toMatchObject({
      client_id: 7,
      export_types: [
        "sales",
        "purchase",
        "payment",
        "receipt",
        "expense",
        "ledger_masters",
        "stock_masters",
      ],
      file_format: "xlsx",
      tally_version: "TallyPrime 4.1",
    });

    expect(await screen.findByText("Validation passed")).toBeInTheDocument();
    expect(screen.getByText("Debit and credit balance")).toBeInTheDocument();
    expect(screen.getByText(/Both sides total/)).toBeInTheDocument();
  });

  it("surfaces backend validation errors and blocked prepare attempts", async () => {
    mockGets();
    const { ApiError } = await import("../../lib/api");
    postMock.mockRejectedValue(
      new ApiError("Export blocked", 422, {
        detail: {
          message: "The export was not prepared because validation found errors. No figure was changed.",
          validation: failingReport,
        },
      }),
    );

    render(<TallyIntegrationPage />);
    await screen.findByText(/Meridian Interiors/);

    fireEvent.click(screen.getByRole("button", { name: /prepare batch/i }));

    expect(
      await screen.findByText(/validation found errors\. No figure was changed/),
    ).toBeInTheDocument();
    expect(screen.getByText("Validation failed — fix the errors before export")).toBeInTheDocument();
    expect(screen.getByText("VOUCHER_UNBALANCED")).toBeInTheDocument();
    expect(screen.getByText("The debit and credit lines of this voucher do not balance.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /show warnings/i }));
    expect(screen.getByText("PARTY_GSTIN_MISSING")).toBeInTheDocument();
  });

  it("opens the approval queue and blocks approving a failed batch", async () => {
    getMock.mockImplementation(async (path: string) => {
      if (path === "/accounting/senior/clients") return { items: [client] };
      if (path.startsWith("/accounting/tally/catalog")) return catalog;
      if (path.startsWith("/accounting/tally/exports?status=pending_approval"))
        return { items: [{ ...pendingBatch, validation: failingReport }], pending_approval_count: 1 };
      if (path.startsWith("/accounting/tally/exports?")) return historyList;
      if (path === "/accounting/tally/exports/13")
        return { ...pendingBatch, validation: failingReport };
      throw new Error(`Unexpected GET ${path}`);
    });

    render(<TallyIntegrationPage />);
    await screen.findByText(/Meridian Interiors/);

    fireEvent.click(screen.getByRole("tab", { name: /approval queue/i }));
    expect(await screen.findByText("Kunal Junior")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /review/i }));
    expect(await screen.findByText("Review batch #13")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve export/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject batch/i })).toBeDisabled();
  });

  it("approves a validated pending batch with a note", async () => {
    getMock.mockImplementation(async (path: string) => {
      if (path === "/accounting/senior/clients") return { items: [client] };
      if (path.startsWith("/accounting/tally/catalog")) return catalog;
      if (path.startsWith("/accounting/tally/exports?status=pending_approval"))
        return { items: [pendingBatch], pending_approval_count: 1 };
      if (path.startsWith("/accounting/tally/exports?")) return historyList;
      if (path === "/accounting/tally/exports/13") return pendingBatch;
      throw new Error(`Unexpected GET ${path}`);
    });
    postMock.mockResolvedValue({ ...pendingBatch, status: "approved" });

    render(<TallyIntegrationPage />);
    await screen.findByText(/Meridian Interiors/);
    fireEvent.click(screen.getByRole("tab", { name: /approval queue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /review/i }));
    await screen.findByText("Review batch #13");

    fireEvent.change(screen.getByLabelText(/decision note/i), {
      target: { value: "Checked the GST split and bank ledgers." },
    });
    fireEvent.click(screen.getByRole("button", { name: /approve export/i }));

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock).toHaveBeenCalledWith("/accounting/tally/exports/13/decision", {
      decision: "approve",
      note: "Checked the GST split and bank ledgers.",
    });
  });

  it("downloads only approved batches from the history", async () => {
    mockGets();
    downloadMock.mockResolvedValue(undefined);

    render(<TallyIntegrationPage />);
    await screen.findByText(/Meridian Interiors/);
    fireEvent.click(screen.getByRole("tab", { name: /export history/i }));

    expect(await screen.findByText("Kunal Junior")).toBeInTheDocument();
    expect(screen.getByText("Riya Senior")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /download/i }));

    await waitFor(() =>
      expect(downloadMock).toHaveBeenCalledWith(
        "/accounting/tally/exports/12/download",
        approvedBatch.filename,
      ),
    );
  });

  it("shows the manual TallyPrime import guide with an explicit no-sync disclaimer", async () => {
    mockGets();
    render(<TallyIntegrationPage />);
    await screen.findByText(/Meridian Interiors/);

    fireEvent.click(screen.getByRole("tab", { name: /tally import guide/i }));

    expect(screen.getByText("Not a live Tally connection")).toBeInTheDocument();
    expect(screen.getByText(/does not update Tally by itself/i)).toBeInTheDocument();
    expect(screen.getByText(/Import masters first/i)).toBeInTheDocument();
    expect(screen.getByText(/Record the outcome/i)).toBeInTheDocument();
  });
});