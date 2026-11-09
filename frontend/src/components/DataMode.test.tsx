import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ConfidenceBadge,
  DataModeBadge,
  DataModeLegend,
  RiskBadge,
  StatusBadge,
} from "./DataMode";

describe("DataModeBadge", () => {
  it("labels demo data and explains what demo means", () => {
    render(<DataModeBadge mode="demo" />);
    const badge = screen.getByText("DEMO");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", expect.stringContaining("Seeded demonstration"));
  });

  it("normalises case and falls back to unavailable", () => {
    const { rerender } = render(<DataModeBadge mode="LIVE" showDot={false} />);
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    rerender(<DataModeBadge mode={null} />);
    expect(screen.getByText("UNAVAILABLE")).toBeInTheDocument();
  });

  it("does not silently relabel an unknown mode", () => {
    render(<DataModeBadge mode="mystery" />);
    expect(screen.getByText("MYSTERY")).toBeInTheDocument();
  });

  it("accepts a custom label", () => {
    render(<DataModeBadge mode="simulated" label="SIM" />);
    expect(screen.getByText("SIM")).toBeInTheDocument();
  });
});

describe("DataModeLegend", () => {
  it("renders every mode with its meaning", () => {
    render(
      <DataModeLegend
        modes={[
          { mode: "live", meaning: "Fresh external data." },
          { mode: "demo", meaning: "Seeded sample data." },
        ]}
      />,
    );
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("DEMO")).toBeInTheDocument();
    expect(screen.getByText("Seeded sample data.")).toBeInTheDocument();
  });
});

describe("StatusBadge", () => {
  it("title-cases snake_case statuses", () => {
    render(<StatusBadge status="simulated_filled" />);
    expect(screen.getByText("Simulated Filled")).toBeInTheDocument();
  });

  it("supports an explicit label", () => {
    render(<StatusBadge status="overdue" label="Past due" />);
    expect(screen.getByText("Past due")).toBeInTheDocument();
  });
});

describe("ConfidenceBadge", () => {
  it("renders confidence wording", () => {
    const { rerender } = render(<ConfidenceBadge confidence="high" />);
    expect(screen.getByText("High confidence")).toBeInTheDocument();
    rerender(<ConfidenceBadge confidence="medium" />);
    expect(screen.getByText("Medium confidence")).toBeInTheDocument();
    rerender(<ConfidenceBadge confidence="low" />);
    expect(screen.getByText("Low confidence")).toBeInTheDocument();
  });
});

describe("RiskBadge", () => {
  it("renders risk wording", () => {
    render(<RiskBadge risk="high" />);
    expect(screen.getByText("High risk")).toBeInTheDocument();
  });
});
