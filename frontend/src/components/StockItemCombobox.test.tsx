import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { StockItemCombobox, type StockItem } from "./StockItemCombobox";

vi.mock("../lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);

const stock: StockItem[] = [
  {
    id: 1,
    sku: "CH-ERG",
    name: "Ergo Pro Task Chair",
    unit: "pcs",
    unit_price: 18500,
    quantity_on_hand: 34,
    low_stock: false,
  },
  {
    id: 2,
    sku: "DK-LFT",
    name: "LiftDesk Pro",
    unit: "pcs",
    unit_price: 34000,
    quantity_on_hand: 0,
    low_stock: false,
  },
];

function renderCombobox(value: string, overrides: Partial<Parameters<typeof StockItemCombobox>[0]> = {}) {
  const onValueChange = vi.fn();
  const onPick = vi.fn();
  const onExactMatch = vi.fn();
  render(
    <StockItemCombobox
      value={value}
      onValueChange={onValueChange}
      onPick={onPick}
      onExactMatch={onExactMatch}
      ariaLabel="Item 1 description"
      currency="INR"
      {...overrides}
    />,
  );
  return { onValueChange, onPick, onExactMatch };
}

describe("StockItemCombobox", () => {
  afterEach(() => {
    apiMock.mockReset();
  });

  it("suggests matching stock items with price and quantity", async () => {
    apiMock.mockResolvedValue({ items: stock });
    renderCombobox("ch");

    fireEvent.focus(screen.getByRole("combobox"));

    expect(await screen.findByText("Ergo Pro Task Chair")).toBeInTheDocument();
    expect(apiMock).toHaveBeenCalledWith(
      "/employee/products?q=ch&limit=6",
      expect.objectContaining({ signal: expect.anything() }),
    );
    expect(screen.getByText(/CH-ERG/)).toBeInTheDocument();
    expect(screen.getByText("34 in stock")).toBeInTheDocument();
    expect(screen.getByText("Out of stock")).toBeInTheDocument();
  });

  it("fills the picked item details when a suggestion is chosen", async () => {
    apiMock.mockResolvedValue({ items: stock });
    const { onPick } = renderCombobox("ch");

    fireEvent.focus(screen.getByRole("combobox"));
    fireEvent.mouseDown(await screen.findByText("Ergo Pro Task Chair"));

    expect(onPick).toHaveBeenCalledWith(stock[0]);
  });

  it("selects a suggestion with the keyboard", async () => {
    apiMock.mockResolvedValue({ items: stock });
    const { onPick } = renderCombobox("ch");
    const input = screen.getByRole("combobox");

    fireEvent.focus(input);
    await screen.findByText("Ergo Pro Task Chair");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onPick).toHaveBeenCalledWith(stock[1]);
  });

  it("reports an exact typed name so the price can fill automatically", async () => {
    apiMock.mockResolvedValue({ items: stock });
    const { onExactMatch } = renderCombobox("ergo pro task chair");

    fireEvent.focus(screen.getByRole("combobox"));

    await waitFor(() => expect(onExactMatch).toHaveBeenCalledWith(stock[0]));
  });

  it("does not query the catalogue for a single character", async () => {
    apiMock.mockResolvedValue({ items: stock });
    renderCombobox("e");

    fireEvent.focus(screen.getByRole("combobox"));

    expect(apiMock).not.toHaveBeenCalled();
  });
});
