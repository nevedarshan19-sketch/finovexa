import type { Invoice } from "../lib/types";
import { formatDate, moneyExact } from "../lib/utils";

function stateLabel(name?: string | null, code?: string | null): string {
  if (name && code) return `${name} (${code})`;
  return name || code || "—";
}

function amountOrDash(value: number | undefined): string {
  return value ? moneyExact(value, "INR") : "—";
}

export function printInvoiceDocument(elementId = "invoice-document"): void {
  const source = document.getElementById(elementId);
  if (!source) return;
  const iframe = document.createElement("iframe");
  iframe.setAttribute("aria-hidden", "true");
  iframe.style.position = "fixed";
  iframe.style.right = "0";
  iframe.style.bottom = "0";
  iframe.style.width = "0";
  iframe.style.height = "0";
  iframe.style.border = "0";
  document.body.appendChild(iframe);
  const doc = iframe.contentDocument;
  if (!doc) {
    iframe.remove();
    return;
  }
  const styles = Array.from(document.querySelectorAll('style, link[rel="stylesheet"]'))
    .map((node) => node.outerHTML)
    .join("");
  doc.open();
  doc.write(
    `<!doctype html><html><head><meta charset="utf-8" />${styles}` +
      `<style>@page{size:A4;margin:10mm}html,body{margin:0;padding:0;background:#fff}` +
      `.invoice-document{width:100%!important;max-width:none!important;min-height:0!important;` +
      `box-shadow:none!important;border:0!important}</style></head><body>${source.innerHTML}</body></html>`,
  );
  doc.close();
  iframe.onload = () => {
    window.setTimeout(() => {
      iframe.contentWindow?.focus();
      iframe.contentWindow?.print();
      window.setTimeout(() => iframe.remove(), 1500);
    }, 250);
  };
}

export function InvoiceDocument({
  invoice,
  id = "invoice-document",
  logoUrl,
}: {
  invoice: Invoice;
  id?: string;
  logoUrl?: string | null;
}) {
  const supplier = invoice.supplier;
  const customer = invoice.customer;
  const currency = invoice.currency || "INR";
  const isTaxInvoice = Boolean(supplier?.gstin);
  const supplyType =
    invoice.supply_type === "inter_state"
      ? "Inter-state (IGST)"
      : invoice.supply_type === "intra_state"
        ? "Intra-state (CGST + SGST)"
        : "Not verified";
  const items = invoice.items ?? [];
  const otherCharges = invoice.other_charges ?? 0;
  const rounding = invoice.rounding_adjustment ?? 0;
  const discount = invoice.discount ?? 0;
  const taxable = invoice.taxable_value ?? invoice.subtotal;
  const cgst = invoice.cgst ?? 0;
  const sgst = invoice.sgst ?? 0;
  const igst = invoice.igst ?? 0;

  return (
    <article
      id={id}
      className="invoice-document mx-auto w-full max-w-[210mm] bg-white p-8 text-[11px] leading-relaxed text-slate-900 shadow-xl sm:p-10"
    >
      <header className="flex flex-wrap items-start justify-between gap-6 border-b-2 border-slate-900 pb-5">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            {logoUrl && (
              <img
                src={logoUrl}
                alt="Business logo"
                className="h-12 w-12 rounded object-contain"
              />
            )}
            <div>
              <h1 className="text-[20px] font-bold leading-tight tracking-tight">
                {supplier?.name || "Your business"}
              </h1>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                {isTaxInvoice ? "GST registered supplier" : "Supplier"}
              </p>
            </div>
          </div>
          {supplier?.address && (
            <p className="mt-3 whitespace-pre-line text-[10.5px] text-slate-600">
              {supplier.address}
            </p>
          )}
          <div className="mt-2 space-y-0.5 text-[10.5px] text-slate-600">
            <p>
              <span className="font-semibold text-slate-800">GSTIN:</span>{" "}
              {supplier?.gstin || "Not provided"}
            </p>
            <p>
              <span className="font-semibold text-slate-800">State:</span>{" "}
              {stateLabel(supplier?.state, supplier?.state_code)}
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-[18px] font-bold uppercase tracking-[0.14em] text-slate-900">
            {isTaxInvoice ? "Tax Invoice" : "Invoice"}
          </p>
          <p className="mt-1 font-mono text-[13px] font-semibold text-slate-700">
            {invoice.number}
          </p>
          <dl className="mt-3 grid grid-cols-[auto_auto] gap-x-3 gap-y-1 text-[10.5px]">
            <dt className="text-slate-500">Invoice date</dt>
            <dd className="font-medium text-slate-800">{formatDate(invoice.issue_date)}</dd>
            <dt className="text-slate-500">Due date</dt>
            <dd className="font-medium text-slate-800">{formatDate(invoice.due_date)}</dd>
            <dt className="text-slate-500">Place of supply</dt>
            <dd className="font-medium text-slate-800">
              {stateLabel(invoice.place_of_supply?.state, invoice.place_of_supply?.state_code)}
            </dd>
            <dt className="text-slate-500">Tax type</dt>
            <dd className="font-medium text-slate-800">{supplyType}</dd>
          </dl>
        </div>
      </header>

      <section className="grid gap-6 border-b border-slate-200 py-5 sm:grid-cols-2">
        <div>
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Bill to
          </p>
          <p className="mt-2 text-[13px] font-semibold text-slate-900">{customer.name}</p>
          {customer.company && <p className="text-[10.5px] text-slate-600">{customer.company}</p>}
          {customer.billing_address && (
            <p className="mt-1 whitespace-pre-line text-[10.5px] text-slate-600">
              {customer.billing_address}
            </p>
          )}
          <p className="mt-1 text-[10.5px] text-slate-600">{customer.email}</p>
          {customer.phone && (
            <p className="text-[10.5px] text-slate-600">Mobile: {customer.phone}</p>
          )}
          <div className="mt-2 space-y-0.5 text-[10.5px] text-slate-600">
            <p>
              <span className="font-semibold text-slate-800">GSTIN:</span>{" "}
              {customer.gstin || "Not provided"}
            </p>
            <p>
              <span className="font-semibold text-slate-800">State:</span>{" "}
              {stateLabel(customer.state, customer.state_code)}
            </p>
          </div>
        </div>
        <div className="sm:text-right">
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Payment status
          </p>
          <p className="mt-2 text-[13px] font-semibold capitalize text-slate-900">
            {invoice.status.replace(/_/g, " ")}
          </p>
          <div className="mt-2 space-y-0.5 text-[10.5px] text-slate-600">
            <p>
              <span className="font-semibold text-slate-800">Amount paid:</span>{" "}
              {moneyExact(invoice.paid, currency)}
            </p>
            <p>
              <span className="font-semibold text-slate-800">Balance due:</span>{" "}
              {moneyExact(invoice.outstanding, currency)}
            </p>
            <p>
              <span className="font-semibold text-slate-800">Pricing:</span>{" "}
              {invoice.pricing_mode === "inclusive"
                ? "Inclusive of GST"
                : "GST added on line value"}
            </p>
          </div>
        </div>
      </section>

      <section className="py-5">
        <table className="w-full border-collapse text-[10px]">
          <thead>
            <tr className="border-b border-slate-300 text-left text-[9px] uppercase tracking-wide text-slate-500">
              <th className="py-2 pr-2 font-semibold">#</th>
              <th className="py-2 pr-2 font-semibold">Description</th>
              <th className="py-2 pr-2 font-semibold">HSN / SAC</th>
              <th className="py-2 pr-2 text-right font-semibold">Qty</th>
              <th className="py-2 pr-2 text-right font-semibold">Rate</th>
              <th className="py-2 pr-2 text-right font-semibold">Discount</th>
              <th className="py-2 pr-2 text-right font-semibold">Taxable</th>
              <th className="py-2 pr-2 text-right font-semibold">GST</th>
              <th className="py-2 text-right font-semibold">Amount</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={item.id ?? index} className="border-b border-slate-100 align-top">
                <td className="py-2 pr-2 text-slate-500">{index + 1}</td>
                <td className="py-2 pr-2">
                  <p className="font-medium text-slate-900">{item.name || item.description}</p>
                  {item.description && item.description !== item.name && (
                    <p className="text-[9.5px] text-slate-500">{item.description}</p>
                  )}
                  <p className="text-[9px] text-slate-400">
                    {item.item_type === "services" ? "Service" : "Goods"} · {item.unit || "pcs"}
                  </p>
                </td>
                <td className="py-2 pr-2 font-mono text-[9.5px] text-slate-600">
                  {item.hsn_sac || "—"}
                </td>
                <td className="py-2 pr-2 text-right text-slate-700">{Number(item.quantity)}</td>
                <td className="py-2 pr-2 text-right text-slate-700">
                  {moneyExact(item.unit_price, currency)}
                </td>
                <td className="py-2 pr-2 text-right text-slate-700">
                  {amountOrDash(item.discount)}
                </td>
                <td className="py-2 pr-2 text-right text-slate-700">
                  {moneyExact(item.taxable_value ?? item.line_total, currency)}
                </td>
                <td className="py-2 pr-2 text-right text-slate-700">
                  <p>{Number(item.gst_rate ?? 0).toFixed(2)}%</p>
                  <p className="text-[9px] text-slate-500">
                    {moneyExact(item.gst_amount ?? 0, currency)}
                  </p>
                </td>
                <td className="py-2 text-right font-semibold text-slate-900">
                  {moneyExact(item.final_amount ?? item.line_total, currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="flex flex-wrap justify-end gap-8 border-t border-slate-200 pt-4">
        <div className="min-w-[220px] flex-1">
          {invoice.notes && (
            <div className="mb-3">
              <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">
                Notes
              </p>
              <p className="mt-1 whitespace-pre-line text-[10px] text-slate-600">{invoice.notes}</p>
            </div>
          )}
          {invoice.terms && (
            <div>
              <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">
                Terms &amp; conditions
              </p>
              <p className="mt-1 whitespace-pre-line text-[10px] text-slate-600">{invoice.terms}</p>
            </div>
          )}
        </div>
        <dl className="w-full max-w-[300px] space-y-1.5 text-[10.5px]">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-slate-500">Subtotal</dt>
            <dd className="text-slate-800">{moneyExact(invoice.subtotal, currency)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-slate-500">Discounts</dt>
            <dd className="text-slate-800">-{moneyExact(discount, currency)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-slate-500">Taxable value</dt>
            <dd className="text-slate-800">{moneyExact(taxable, currency)}</dd>
          </div>
          {invoice.supply_type === "inter_state" ? (
            <div className="flex items-center justify-between gap-4">
              <dt className="text-slate-500">IGST</dt>
              <dd className="text-slate-800">{moneyExact(igst, currency)}</dd>
            </div>
          ) : invoice.supply_type === "intra_state" ? (
            <>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-slate-500">CGST</dt>
                <dd className="text-slate-800">{moneyExact(cgst, currency)}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-slate-500">SGST</dt>
                <dd className="text-slate-800">{moneyExact(sgst, currency)}</dd>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-between gap-4">
              <dt className="text-slate-500">GST (classification not verified)</dt>
              <dd className="text-slate-800">
                {moneyExact(invoice.tax ?? cgst + sgst + igst, currency)}
              </dd>
            </div>
          )}
          {otherCharges > 0 && (
            <div className="flex items-center justify-between gap-4">
              <dt className="text-slate-500">Other charges</dt>
              <dd className="text-slate-800">{moneyExact(otherCharges, currency)}</dd>
            </div>
          )}
          {rounding !== 0 && (
            <div className="flex items-center justify-between gap-4">
              <dt className="text-slate-500">Rounding</dt>
              <dd className="text-slate-800">{moneyExact(rounding, currency)}</dd>
            </div>
          )}
          <div className="flex items-center justify-between gap-4 border-t border-slate-300 pt-1.5 text-[13px] font-bold text-slate-900">
            <dt>Total</dt>
            <dd>{moneyExact(invoice.total, currency)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-slate-500">Amount paid</dt>
            <dd className="text-slate-800">{moneyExact(invoice.paid, currency)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 border-t border-slate-200 pt-1.5 font-semibold text-slate-900">
            <dt>Outstanding balance</dt>
            <dd>{moneyExact(invoice.outstanding, currency)}</dd>
          </div>
        </dl>
      </section>

      <footer className="mt-6 border-t border-slate-200 pt-3 text-[9px] text-slate-500">
        <p>
          GST rates, HSN/SAC classification and place-of-supply treatment must be verified by the
          supplier for each supply. This document reflects the values saved when the invoice was
          issued and does not by itself establish tax registration or compliance.
        </p>
        <p className="mt-1">
          {supplier?.name || "Supplier"} · {invoice.number} · Generated by FINOVEXA AI
        </p>
      </footer>
    </article>
  );
}
