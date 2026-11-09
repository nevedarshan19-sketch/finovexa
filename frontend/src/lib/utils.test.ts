import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clamp,
  cn,
  compactMoney,
  countdown,
  formatDate,
  formatDateShort,
  formatDateTime,
  initials,
  money,
  moneyExact,
  number,
  pct,
  plainPct,
  pluralize,
  timeAgo,
  titleCase,
} from "./utils";

afterEach(() => {
  vi.useRealTimers();
});

describe("cn", () => {
  it("merges conflicting tailwind classes", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-sm", false && "hidden", "font-semibold")).toBe("text-sm font-semibold");
  });
});

describe("money formatting", () => {
  it("formats INR without decimals by default", () => {
    expect(money(123456.78)).toBe("₹1,23,457");
    expect(money("2500")).toBe("₹2,500");
  });

  it("formats exact amounts with two decimals", () => {
    expect(moneyExact(123456.7)).toBe("₹1,23,456.70");
    expect(moneyExact("0")).toBe("₹0.00");
  });

  it("supports compact notation and other currencies", () => {
    expect(compactMoney(1234567)).toContain("₹");
    expect(money(10, "USD")).toContain("$");
  });

  it("returns a dash for missing or invalid values", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(money("")).toBe("—");
    expect(money("not-a-number")).toBe("—");
    expect(compactMoney(Number.NaN)).toBe("—");
  });

  it("formats plain numbers with digit control", () => {
    expect(number(1234567.89)).toBe("12,34,568");
    expect(number(42.5, 1)).toBe("42.5");
    expect(number(null)).toBe("—");
  });
});

describe("percentage formatting", () => {
  it("adds a sign for signed percentages", () => {
    expect(pct(12.34)).toBe("+12.3%");
    expect(pct(-5)).toBe("-5.0%");
    expect(pct(0)).toBe("0.0%");
    expect(pct(null)).toBe("—");
  });

  it("formats unsigned percentages", () => {
    expect(plainPct(45.67)).toBe("45.7%");
    expect(plainPct("7.5", 0)).toBe("8%");
  });
});

describe("dates", () => {
  it("formats ISO dates and datetimes", () => {
    expect(formatDate("2026-10-24")).toBe("24 Oct 2026");
    expect(formatDateShort("2026-10-24")).toBe("24 Oct");
    expect(formatDateTime("2026-10-24T14:05:00Z")).toContain("24 Oct 2026");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not-a-date")).toBe("—");
  });

  it("describes relative time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-24T12:00:00Z"));
    expect(timeAgo("2026-10-24T11:59:30Z")).toBe("just now");
    expect(timeAgo("2026-10-24T11:55:00Z")).toBe("5m ago");
    expect(timeAgo("2026-10-24T09:00:00Z")).toBe("3h ago");
    expect(timeAgo("2026-10-21T12:00:00Z")).toBe("3d ago");
    expect(timeAgo("2026-08-01T12:00:00Z")).toBe("01 Aug 2026");
  });

  it("counts down to a deadline", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-24T12:00:00Z"));
    expect(countdown("2026-10-24T12:30:00Z")).toBe("30m left");
    expect(countdown("2026-10-24T15:10:00Z")).toBe("3h 10m left");
    expect(countdown("2026-10-26T15:00:00Z")).toBe("2d 3h left");
    expect(countdown("2026-10-24T11:00:00Z")).toBe("expired");
    expect(countdown(null)).toBe("—");
  });
});

describe("string helpers", () => {
  it("builds initials", () => {
    expect(initials("Asha Rao")).toBe("AR");
    expect(initials("  asha   rao  ")).toBe("AR");
    expect(initials("Asha")).toBe("A");
  });

  it("title-cases status keys", () => {
    expect(titleCase("partially_paid")).toBe("Partially Paid");
    expect(titleCase("demo-webhook")).toBe("Demo Webhook");
  });

  it("pluralizes", () => {
    expect(pluralize(1, "invoice")).toBe("invoice");
    expect(pluralize(2, "invoice")).toBe("invoices");
    expect(pluralize(0, "entry", "entries")).toBe("entries");
  });

  it("clamps to bounds", () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-1, 0, 10)).toBe(0);
    expect(clamp(99, 0, 10)).toBe(10);
  });
});
