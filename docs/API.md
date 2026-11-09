# API reference

Base URL: `http://127.0.0.1:8000/api`

Interactive schema: `/api/docs` (Swagger UI) and `/api/openapi.json`.

## Conventions

- **Auth:** send `Authorization: Bearer <jwt>` for every endpoint except `/health`, `/auth/register`, `/auth/login`, `/auth/employee/login`, `/auth/developer/login` and the PayPal webhook.
- **Roles:** owner tokens access the business APIs. Employee tokens are limited to `/employee/*`; developer tokens are limited to `/developer/*` with no business financial data. Each role receives `403` from the other roles' APIs.
- **Tenant scope:** every record is scoped to the authenticated user's business. Foreign IDs return `404`, not `403`.
- **Content type:** JSON. The PayPal webhook reads the raw request body.
- **Money:** the server computes with `Decimal` and stores `Numeric(16,2)`. JSON responses deliver numbers; format them for display client-side.
- **Dates:** ISO 8601. Seed/demo timestamps are UTC.
- **Errors:** `{"detail": "..."}` or FastAPI's `422` validation array.
- **Caching:** API responses send `Cache-Control: no-store`.
- **Rate limits:** per IP, sliding window. Key limits: login 10/min, register 5/min, AI chat 20/min, approval execution 20/min, payment simulation 20/min, integration check 15/min, demo reset 3/5min, business analysis 6/min.

### Status codes

| Code | Use |
| --- | --- |
| `200` | Success |
| `201` | Created (register, invoice, approval, snapshot) |
| `400` | Invalid business operation (wrong confirmation, overpayment, bad dates) |
| `401` | Missing/invalid JWT; failed webhook signature |
| `403` | Wrong role for the endpoint, owner-only demo action denied, or owner/employee account used with the developer login |
| `404` | Missing or foreign resource |
| `409` | Conflict: duplicate invoice, changed approval payload, expired/executed approval, provider not configured |
| `422` | Schema validation |
| `429` | Rate limit |
| `502` | Provider request failed |

## Endpoint map

### Auth

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/register` | Create business + owner. Body: `email`, `password`, `full_name`, `business_name`, `currency`. |
| `POST` | `/auth/login` | Owner login. Returns JWT, user and profile. Employee and developer accounts receive `403`. |
| `POST` | `/auth/employee/login` | Employee login. Returns the same session shape plus the linked business. Owner and developer accounts receive `403`. |
| `POST` | `/auth/developer/login` | Developer login. Only `developer` accounts may sign in; returns the same session shape. Rate limited to 10/min. |
| `GET` | `/auth/me` | Current user + profile. |
| `POST` | `/auth/logout` | Stateless logout acknowledgement. |

### Employee portal (employee role only)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/employee/overview` | Employee's own day summary: entry counts, paid sales, purchases, open invoices, recent entries. |
| `GET` | `/employee/entries?entry_type=all&status=all` | The signed-in employee's sale, purchase and invoice entries with line items, payment attribution, lock state and `editable`/`voidable` flags. |
| `GET` | `/employee/entries/{id}` | One of the employee's own entries. |
| `GET` | `/employee/products?q=chair&limit=8` | Stock catalogue lookup for the entry form: matches the owning business's item name or SKU and returns `name`, `sku`, `unit`, `unit_price`, `quantity_on_hand` and `low_stock`. Unit cost stays hidden from employees. |
| `POST` | `/employee/entries` | Create an invoice, paid sale or purchase. Body: `entry_type`, `counterparty`, `description`, `amount` and/or `items`, `payment_method`, `entry_date`, optional `due_date`, `tax_rate`, `notes`. Each item is `{description, quantity, unit_price}`; sales and purchases accept several items per bill and derive the total from quantity × unit price. Purchase line items are stored on the entry and mirrored in the expense note. |
| `PATCH` | `/employee/entries/{id}` | Edit an entry. Entries with a confirmed payment accept notes only. |
| `POST` | `/employee/entries/{id}/void` | Void an entry. Purchases delete the linked expense; invoices are marked `void` and outstanding drops to zero. Paid entries return `409`. |

Entry writes post to the linked owner's tenant: a purchase creates an expense, a sale creates a paid invoice plus a confirmed `employee_recorded` payment, and an invoice creates a receivable without moving cash.

### Developer console (developer role only)

The developer account is provisioned only from `DEVELOPER_EMAIL` / `DEVELOPER_PASSWORD` at startup. No endpoint creates a developer or changes roles.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/developer/overview` | Environment, account counts, auth events in 24h, feature readiness and security metadata. No secrets or financial data. |
| `GET` | `/developer/accounts?role=all\|owner\|employee` | Owner/employee accounts with business, owner email and status. Developers are never listed. |
| `POST` | `/developer/accounts` | Create an owner or employee. Body: `role`, `email`, `password`, `full_name`; owners need `business_name` (+ optional `currency`), employees need `owner_id`. |
| `PATCH` | `/developer/accounts/{id}` | Change `email`, `password`, `full_name` or `is_active` for an owner/employee. Emails must be unique; developer accounts return `404`. |
| `GET` | `/developer/security-log?limit=50` | Scoped `auth.*`, `developer.*` and `team.*` audit events. No ledger entries. |
| `GET` | `/developer/contact-messages?limit=50` | Public contact-form submissions for review. No automatic email is sent. |

Disabling an owner also blocks their employees' existing tokens and new employee logins until the owner is re-enabled.

### Public site (no session)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/public/contact` | Body: `name`, `email`, optional `organisation`/`phone`, `category` (`general`/`support`/`partnership`/`developer`), `subject`, `message`, `consent`, honeypot `website`. Rate-limited per IP. |
| `GET` | `/accounting/public/pricing` | Configured accounting service pricing and availability. No checkout or subscription payment exists. |
| `GET` | `/market/nifty50/recommendations` | Public NIFTY 50 screen. Query: `q`, `sort` (`upside`/`confidence`/`name`), `horizon`, `confidence`, `min_upside`, `limit`. Returns all 50 constituents split into `qualifying`, `no_positive_upside` and `insufficient_data`, plus methodology, data provenance and disclaimer. |

### Team (owner role only)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/team/employees` | Employee roster with status and entry counts, plus the employee portal path. Never returns passwords. |
| `POST` | `/team/employees` | Create an employee account linked to the owner. Body: `full_name`, `email`, `password`. |
| `PATCH` | `/team/employees/{id}` | Pause or restore employee access. Paused sessions fail on their next request. |
| `GET` | `/team/entries?entry_type=all&status=all` | Owner feed of all employee entries with employee attribution and summary totals. |

### Profile and catalog

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` / `PUT` | `/profile` | Business name, currency, timezone, reporting period, reserve, opening balance, risk tolerance, research interests, reminder tone. |
| `GET` | `/customers` | Customer list for the business. |
| `GET` | `/products` | Catalog with stock, reorder level and low-stock flag. |

### Dashboard and analytics

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/dashboard?days=30` | KPIs, receivables/aging, cash, obligations, inventory, alerts, deterministic insights. |
| `GET` | `/analytics?days=90` | Trend, margins, expense mix, product/customer performance. |
| `GET` | `/agents/business-manager/monitor` | Agent monitor snapshot. |
| `POST` | `/agents/business-manager/analyze?days=90` | Recompute deterministic business insights. |

### Invoices, payments and recovery

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/invoices?q=&status=all&limit=100` | Search/filter invoices. Status display includes `overdue`; `base_status` is the ledger status. |
| `GET` | `/invoices/{id}` | Invoice detail with line items, payments and reminders. |
| `POST` | `/invoices` | Create an invoice. Totals are computed server-side. |
| `POST` | `/invoices/{id}/payments` | Record a manual payment; rejects overpayment. |
| `GET` | `/recovery/summary?days=30` | Aging, overdue/current totals, pending totals, priority invoices. |
| `GET` | `/recovery/duplicates` | Possible duplicate invoices. |
| `GET` | `/recovery/priorities?limit=10` | Ranked collection priorities with reasons. |
| `GET` | `/recovery/unmatched` | Confirmed but unreconciled payments with suggested matches. |
| `GET` | `/recovery/reminder-schedule?window_days=7` | Deadline ladder. Each open invoice gets a stage from its due date: `due_in_7`, `due_today`, `overdue_1_7`, `overdue_8_14`, `overdue_15_plus`. Returns per-stage counts/amounts, whether that stage was already reminded, contact readiness and `share` text with `whatsapp_url` / `mailto_url` / `sms_uri`. Nothing is dispatched. |
| `POST` | `/recovery/reminder-draft/{invoice_id}` | Draft only. Body: optional `tone`, `instructions`, `channel`, `stage`. A stage without a tone picks the stage's tone. Never sends. |
| `GET` | `/payments?status=all` | Payment ledger. |
| `POST` | `/payments/{payment_id}/match` | Reconcile an unmatched payment. Body: `invoice_id`, `confirm: true`. |

### GST & Billing (owner-only)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/billing/overview` | Invoice counts (total, drafts, open, overdue), invoiced/outstanding/received totals and GST charged on issued invoices (not a net GST liability). |
| `GET` / `PUT` | `/billing/settings` | Supplier billing identity, state code, GSTIN and configurable GST rates. GSTIN is checksum-validated. |
| `GET` / `POST` | `/billing/gst-rates` | List or add a configurable GST rate. Inactive rates are rejected by the calculation engine. |
| `GET` / `POST` | `/billing/products` | Product/service catalogue with default GST rate, HSN/SAC and unit. |
| `PUT` | `/billing/products/{product_id}` | Update a product default (does not rewrite issued invoices). |
| `GET` / `POST` | `/billing/customers` | Customers with optional GSTIN, billing address and state code. |
| `GET` | `/billing/next-number` | Next available invoice number. |
| `POST` | `/billing/calculate` | Stateless preview calculation. Requires line items, `pricing_mode`, `place_of_supply_state_code` and `confirm_supply_details: true`. Returns per-line taxable/GST and the CGST/SGST or IGST split. Rejects inactive rates, invalid quantities and excessive discounts. |
| `GET` | `/billing/invoices?q=&status=all` | GST invoice register with display status, aging and payment state. |
| `POST` | `/billing/invoices` | Create a draft or issue an invoice. Totals are recomputed and validated server-side; the tax snapshot is stored per line. |
| `GET` / `PUT` | `/billing/invoices/{id}` | Read or update an invoice. The backend recalculates and re-stores the tax snapshot on save; void invoices are immutable and a revised total cannot fall below payments already recorded. |
| `POST` | `/billing/invoices/{id}/void` | Void an invoice; outstanding drops to zero. |
| `GET` | `/billing/invoices/{id}/pdf` | A4 PDF. Titled **TAX INVOICE** only when a supplier GSTIN exists; **INVOICE** otherwise. |

Payments for GST invoices use the existing `POST /invoices/{invoice_id}/payments` endpoint (overpayment rejected); PayPal simulation and capture use the Payment Center endpoints above.

### Tax Center (owner-only)

Every result carries the financial year and, for income tax, the rule-set version and effective dates. No endpoint calls an AI model.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/tax/overview` | Combined dashboard: current-quarter output GST, available input credit, net GST direction, saved-estimate count, verification warnings and the disclaimer. |
| `GET` | `/tax/gst/options` | GST rates, state codes, supplier state and the cached HSN/SAC registry for the calculator. |
| `POST` | `/tax/gst/calculate` | Stateless multi-line GST calculation. Body: `lines[]` (`quantity`, `unit_price`, `gst_rate`, `discount`, optional `hsn_code`), `place_of_supply_state_code`, `price_basis` (`exclusive`/`inclusive`), optional `other_charges`, `round_to_rupee`. Returns per-line taxable/GST, the CGST/SGST or IGST split and totals. |
| `GET` | `/tax/gst/report?date_from=&date_to=` | Invoice-wise output GST for a period (default 90 days, capped near two financial years), with by-rate and by-HSN summaries and warnings for unverified supply types and missing HSN codes. |
| `GET` | `/tax/gst/net?date_from=&date_to=` | Output GST − available input credit for the period, as payable, refundable or nil. |
| `GET` | `/tax/gst/itc?date_from=&date_to=` | Input-credit ledger with per-status summary and available credit. Omit dates for the full ledger. |
| `POST` | `/tax/gst/itc` | Record a purchase bill. Validates GSTIN check digit, rejects CGST+SGST mixed with IGST, requires the tax to match rate × taxable within ₹1, rejects claims above the bill and future invoice dates. |
| `PATCH` | `/tax/gst/itc/{entry_id}?status=` | Move an entry between `eligible`, `claimed` and `blocked`; blocking zeroes the eligible amount. |
| `DELETE` | `/tax/gst/itc/{entry_id}` | Remove a ledger entry (204). |
| `GET` / `POST` | `/tax/gst/hsn` | Owner-confirmed HSN/SAC registry. `POST` body: `code`, `kind` (`hsn`/`sac`), `description`, `default_rate`, optional `note`, `verified`. HSN must be 2/4/6/8 digits; SAC exactly 6. |
| `PUT` / `DELETE` | `/tax/gst/hsn/{hsn_id}` | Update or delete a registry row. Duplicate codes return `409`. |
| `GET` | `/tax/income/rules?financial_year=2026-27` | Available financial years plus each regime's version, effective dates, source note, slabs, surcharge bands, rebate rule, constants, deduction caps and capital-gains rates. Unknown years return `400`. |
| `POST` | `/tax/income/calculate` | Body: `financial_year`, `regime` (`new`/`old`), `inputs` (`salary`, `business`, `capital_gains`, `deductions`). Returns income, deductions with caps and reasons, slab rows, rebate, surcharge, cess, rounding and the final estimate. |
| `POST` | `/tax/income/compare` | Same body shape; computes both regimes, marks the recommended one and returns the saving. |
| `GET` / `POST` | `/tax/income/estimates` | List saved estimates, or save one. Saving without a regime stores the recommended regime; the full inputs and computed result are stored as JSON. |
| `GET` | `/tax/income/estimates/{estimate_id}` | One saved estimate with its inputs and result. |
| `POST` | `/tax/income/estimates/{estimate_id}/approve` | Record an accountant's sign-off. Body: `approved_by_name`, `membership_number` (ICAI), optional `note`. Already-approved estimates return `409`. Writes `tax_estimate.approved` to the audit log. |
| `POST` | `/tax/income/estimates/{estimate_id}/reopen` | Return an approved estimate to draft. |

Mutations on input credit, HSN/SAC and estimates write `itc.*`, `hsn.*` and `tax_estimate.*` audit events. Approval records a sign-off only — no endpoint files a return or moves money.

### Cash flow

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/cashflow/forecast?horizon=30&scenario=base` | Daily projection, reserve floor, shortfall, investable surplus. Horizon 7–90. |
| `GET` | `/cashflow/overview?horizon=30` | All three scenarios, sensitivity and obligations. |
| `GET` / `POST` | `/cashflow/forecasts` | List/save a projection snapshot. |

### Market and research

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/market/overview` | Metals, indices and equities grouped with mode/source/freshness. |
| `GET` | `/market/simulator` | Simulated Indian market session over all 50 NIFTY constituents: per-stock RSI, SMA, VWAP, momentum, volume, support/resistance, score, breadth, sectors, movers and index history. Labelled `data_mode: simulated`; not exchange data. |
| `GET` | `/market/simulator/{symbol}` | Simulated candles and full technical analysis for one NIFTY 50 symbol. Unknown symbol → 404. |
| `GET` | `/market/india/overview` | Real (provider-delayed) NSE data: NIFTY 50, NIFTY Bank and SENSEX tiles with sparklines, all 50 constituent quotes, breadth summary, 52-week range, session state and provider metadata. `data_mode: "delayed"`; each quote carries `source` and `price_as_of`. |
| `GET` | `/market/india/stocks/{symbol}?range=1d` | Real candles and indicators for one NIFTY 50 constituent. `range` is one of `1d`, `5d`, `1mo`, `3mo`, `1y`. Returns candles, SMA 20/50, RSI(14), 52-week range and position, plus disclosures. Unknown symbol → 404, bad range → 422, provider failure → 503 while claiming no substitute price, provider rate limit → 429. |
| `GET` | `/market/instruments/{symbol}` | Latest quote. Unknown symbol → 404. |
| `GET` | `/market/instruments/{symbol}/history?days=90` | Candles (10–365 days). |
| `GET` | `/market/news?instrument=TCS&limit=20` | Attributed, deduplicated headlines. |
| `GET` | `/research` | Model signals, quotes, disclosures, empty analyst ratings, cash constraints and broker mode. |
| `GET` | `/research/stock-tokens` | Public Upstox instrument keys for all 50 NIFTY constituents with coverage notes. |
| `GET` | `/research/nifty50` | Trade desk for all 50 constituents: quote, data mode, tradability and signal availability. Live Upstox quotes are fetched in one batch when a token is configured. |
| `GET` | `/research/option-chain?expiry=&strikes=` | NIFTY option chain with expiries, ATM marker, OI/IV analytics and a 75-unit lot size. Demo model, or live Upstox chain when configured. |
| `GET` | `/research/portfolio` | Simulated practice portfolio: per-holding quantity, average cost, delayed price, value, profit/loss, day move and sector weight, plus totals, sector allocation and disclosures. `is_simulated: true`; `data_mode` is `delayed`, `live`, `demo` or `unavailable`. Never mirrors a real broker account. |
| `GET` | `/research/recommendations` | Four quick model ideas: label (`Strong setup`/`Worth a look`/`Neutral`/`Weak`/`High risk`), score, one-line reason, delayed quote and an hourly `signature`. Label is model-generated, not investment advice; no order is created. |

### AI

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/ai/chat` | Body: `{"question": "..."}`. Returns answer, facts, estimates, interpretations, uncertainty, citations, follow-ups, mode. |
| `GET` | `/ai/history?limit=40` | Current user's persisted chat. |
| `GET` | `/ai/tools` | Read-only tool specs plus policy. |

### Approvals and orders

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/approvals?status=pending&limit=50` | List approvals; expiry is refreshed before returning. |
| `GET` | `/approvals/{id}` | Full payload, hash, result and linked order. |
| `POST` | `/approvals/{id}/approve` | Body: `confirm: true`, exact `payload_hash`, optional note. |
| `POST` | `/approvals/{id}/reject` | Body: optional `reason`. |
| `POST` | `/approvals/reminders` | Create reminder approval. Body: `invoice_id`, `body`, `recipient` (must match the customer), optional `channel` (`email`/`sms`) and `stage` (ladder stage recorded with the dispatch). |
| `POST` | `/approvals/investments` | Create stock order approval. Body: `symbol`, `side: buy\|sell`, `quantity`, `order_type`, optional `limit_price`, `execution_mode: simulated\|live` (default `simulated`). |
| `POST` | `/approvals/options` | Create NIFTY option order approval. Body: `expiry`, `strike`, `option_type: call\|put`, `side: buy\|sell`, `lots`, `order_type`, optional `limit_price`, `execution_mode: simulated\|live`. Priced from the current chain at 75 units per lot. |
| `POST` | `/approvals/cashflow` | Record a cash-flow action-plan acknowledgement. |
| `GET` | `/orders` | Broker orders with `execution_mode`, `simulated`, broker status fields, plus `broker_mode` and live-readiness flags. |
| `POST` | `/orders/{id}/sync` | Refresh a live order from Upstox and map its status (`live_open`, `live_filled`, `live_rejected`, …). Simulated orders → 409. |
| `POST` | `/orders/{id}/cancel-request` | Simulated order → local `cancel_requested`. Live order → sends a real Upstox cancellation when the order is cancellable. Body: `confirm: true`. |
| `POST` | `/orders/{id}/simulate-fill` | Mark a simulated order filled. Body: `confirm: true`. Live orders → 409. |
| `POST` | `/orders/{id}/simulate-cancel` | Mark a simulated order cancelled. Body: `confirm: true`. Live orders → 409. |

### Payments (PayPal)

Every route below is owner-only. Employees and developers receive `403`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/payments/overview?days=30&start=&end=&status=&currency=` | Provider mode, statistics, orders, captures/refunds/events, reconciliation summary, daily series and open invoices. `days` > 30 or `start`/`end` switches to a custom window. |
| `GET` | `/paypal/settings` | Non-secret runtime state: selected `environment`, `enabled`, whether sandbox/live credentials and webhook ID are present (masked hints only), and the webhook endpoint. Never returns a Client Secret or token. |
| `PUT` | `/paypal/settings` | Body: `environment: sandbox\|live`, `enabled`, optional `confirm_live: true`. Enabling live without `confirm_live` → `400`; live credentials missing from the backend environment → `409`. Disabling leaves recorded history untouched. |
| `POST` | `/paypal/settings/test` | OAuth token check against the environment's API host. Returns `ok`, `unauthorized`, `unconfigured` or `error` without echoing credentials. Rate limited. |
| `POST` | `/paypal/orders` | Body: `{"invoice_id": 1}`. Creates a PayPal order for the invoice's verified outstanding amount in the invoice currency, stores `provider_order_id`, and marks the invoice `pending_payment`. A recent open checkout for the same amount is reused instead of duplicated. Unknown/foreign invoice → `404`; draft, void or zero-outstanding → `409`; provider failure → `502`. Return/cancel URLs are configured server-side. |
| `GET` | `/paypal/orders` | Local order history with provider status and captured amount. |
| `GET` | `/paypal/orders/{identifier}` | Local order by numeric ID or `provider_order_id`. Returns stored state plus a live provider refresh when configured; `UNAVAILABLE` when not configured. |
| `POST` | `/paypal/orders/{identifier}/cancel` | Cancel a local order still awaiting payment and release the invoice hold. Captured orders → `409`. |
| `POST` | `/paypal/orders/{identifier}/capture` | Capture an approved order server-side, then re-read the provider status before recording. Response flags `duplicate: true` for a replayed capture and `mismatch: true` when amount/currency differs (invoice stays open, payment is recorded as unreconciled). Cash is credited only after a verified `COMPLETED` capture. |
| `POST` | `/paypal/simulate` | Labelled simulated capture for unconfigured deployments. Idempotent per invoice/amount; never calls PayPal. |
| `POST` | `/paypal/payments/{payment_id}/refund` | Owner-confirmed refund. Body: `{"amount": 500, "reason": "...", "confirm": true}`; `amount` is optional (defaults to the full refundable balance) and may not exceed captured minus prior refunds. Records a provider refund ID, reduces net cash, and leaves an audit trail. Missing `confirm` / over-refund / already-refunded → `409`/`400`; provider rejection → `502`. |
| `GET` | `/paypal/refunds` | Refund records with provider reference, amount, status and reason. |
| `GET` | `/paypal/events` | Webhook/event log for the business: event type, verification result, idempotency outcome and linked invoice/payment. |
| `GET` | `/paypal/reconciliation` | Deterministic reconciliation: matched, unmatched, mismatched and duplicate counts plus the unreconciled payment list. |
| `POST` | `/paypal/webhook` | Raw-body webhook. Unauthenticated but signature-verified (PayPal verification API, or the demo HMAC when unconfigured). Event IDs are deduplicated; unsupported/out-of-order events are logged without changing cash. Invalid signature → `401`. |

### Payment Connect

Owner routes use `/payment-connect`; accountant routes use `/accounting/payment-connect`
and take `client_id` as a query parameter (GET) or body field (writes). Every route is
scoped to the signed-in owner or to a business assigned to the accountant. No route accepts
provider credentials from the browser.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/payment-connect/overview` | Connections, transaction/duplicate/incoming/outgoing summary, reconciliation counts, recent syncs, last success and capability notes. |
| `GET` | `/payment-connect/transactions?date_from=&date_to=&provider=&direction=&status=&reconciliation_status=&outlet_label=&search=&amount_min=&amount_max=&include_duplicates=&limit=1..500&offset=` | Unified provider and statement history. Provider references are returned unchanged. |
| `GET` | `/payment-connect/transactions/{id}/events` | Reconciliation audit events for one transaction. |
| `GET` | `/payment-connect/transactions/{id}/candidates` | Deterministic invoice match suggestions with score and reason. |
| `POST` | `/payment-connect/transactions/{id}/reconcile` | Body: `{action: approve\|reject\|not_applicable\|reset\|suggest, invoice_id?, note?}`. Approval is senior-only for accountants, requires a completed transaction, an invoice for incoming payments and an amount within the outstanding balance. Refunds create a negative payment. |
| `POST` | `/payment-connect/connections` | Body: `{provider: paypal\|google_pay, environment, label?, outlet_label?, merchant_id?, consent: true, note?}`. Consent is mandatory; bank statements cannot be connected here. |
| `POST` | `/payment-connect/connections/{id}/disconnect` | Revokes the connection and preserves imported history. |
| `POST` | `/payment-connect/connections/{id}/sync` | PayPal only. Body: `{start_date?, end_date?, days?, trigger?}`; windows are capped at 31 days. Idempotent per external transaction ID. |
| `GET` | `/payment-connect/connections/{id}/runs` | Sync history with fetched/created/duplicate/skipped counts and errors. |
| `GET` | `/payment-connect/google-pay/eligibility` | Reports that no public Google Pay transaction-history or detail API exists and what is supported. |
| `POST` | `/payment-connect/google-pay/lookup` | Always `409` with an honest explanation; no placeholder data is returned. |
| `POST` | `/payment-connect/google-pay/track` | Body: `{merchant_id, google_transaction_id, amount, currency, occurred_on, status, description?, upi_reference?, outlet_label?}`. Records a merchant-entered reference as not verified through Google. Duplicate references return the existing row. |
| `POST` | `/accounting/payment-connect/bank-statements/preview` | Accountant only. Body: `{client_id, filename, data_url, account_label?}`. Returns parsed rows with confidence, issues, duplicate flags and editable values. Nothing is stored. |
| `POST` | `/accounting/payment-connect/bank-statements/import` | Accountant only. Same body plus `corrections[]`. Stores the encrypted original, skips duplicates and marks rows unverified. |
| `GET` | `/accounting/payment-connect/bank-statements?client_id=` | Import history for the client. |

### Audit, integrations and settings

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/audit-log?limit=100&action=&entity_type=&start=&end=` | Audit trail for the business. |
| `GET` | `/audit-log/actions` | Distinct action/entity pairs for filters. |
| `GET` | `/integrations` | Provider modes, configuration booleans, setup hints, mode legend. |
| `POST` | `/integrations/check` | Body: `{"provider": "paypal"|"upstox"|"metals"|"news"|"llm"}`. Records an audit event. |
| `GET` | `/settings/runtime` | Environment, feature modes, security summary. Never returns keys. |
| `POST` | `/demo/reset` | Demo account only. Body: `{"confirm": "RESET DEMO"}`. |

## Examples

### Login

```bash
TOKEN=$(curl -s http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@finovexa.ai","password":"Demo1234!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

### Employee login and a paid sale

```bash
EMP_TOKEN=$(curl -s http://127.0.0.1:8000/api/auth/employee/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"employee@finovexa.ai","password":"Employee1234!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s -X POST http://127.0.0.1:8000/api/employee/entries \
  -H "Authorization: Bearer $EMP_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "entry_type": "sale",
    "counterparty": "Bluewave Interiors",
    "description": "Website maintenance retainer",
    "amount": 18000,
    "payment_method": "paypal",
    "entry_date": "2026-10-24",
    "tax_rate": 0
  }'
```

The sale appears in the owner's Payment Center as **employee-recorded · unverified** and increases recorded cash immediately. The owner dashboard and team feed refresh on their next poll (10–15 seconds).

### Employee sale/purchase lines and catalogue stock

Send `items` instead of `amount` to bill several products. Each line takes `description`, `quantity`, `unit_price` and optional `product_id`:

```bash
curl -s -X POST http://127.0.0.1:8000/api/employee/entries \
  -H "Authorization: Bearer $EMP_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "entry_type": "purchase",
    "counterparty": "Ergo Wholesale",
    "description": "Ergo Pro Task Chair",
    "entry_date": "2026-11-01",
    "items": [{"description": "Ergo Pro Task Chair", "quantity": 2, "unit_price": 18500, "product_id": 3}]
  }'
```

A line linked to a catalogue product (explicit `product_id`, or an exact case-insensitive name/SKU match in the owner's catalogue) updates that product's stored `quantity_on_hand`: purchases add, sales and invoices subtract. Editing an entry reverses the old movement before applying the new one, and voiding reverses it entirely. Lines with no catalogue match (rent, marketing) leave stock untouched. Quantities for catalogue products must be whole units or the request returns **400**.

### Ask a grounded question

```bash
curl -s http://127.0.0.1:8000/api/ai/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which overdue invoice should I prioritise?"}'
```

The response contains `answer.citations` referencing the read-only tools used, plus `verified_facts`, `estimates`, `interpretations`, `uncertainty` and `followups`.

### Approve exactly what was reviewed

```bash
# 1. Fetch the pending approval and its current hash.
curl -s "http://127.0.0.1:8000/api/approvals?status=pending" \
  -H "Authorization: Bearer $TOKEN"

# 2. Send the same hash. The server recomputes it from the canonical payload.
curl -s -X POST "http://127.0.0.1:8000/api/approvals/1/approve" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"confirm":true,"payload_hash":"<64-char-hash-from-step-1>"}'
```

A stale hash returns `409` and leaves the request pending. Expired or already executed requests return `409`. Reminder execution is a simulated dispatch. Investment execution creates a simulated order unless the approval payload says `execution_mode: "live"`.

### Live Upstox execution

Live execution is denied with `409` unless all of the following are true:

1. `UPSTOX_LIVE_TRADING_ENABLED=true` and `UPSTOX_ACCESS_TOKEN` is set on the backend.
2. The business profile currency is `INR`.
3. The quote (or option chain) has `data_mode: "live"`.
4. The instrument has an Upstox token (stocks: catalogue key; options: leg `instrument_key`).
5. The approval payload contains `execution_mode: "live"` and is approved with its exact hash.

A live approval returns an order with `broker: "upstox"`, `simulated: false`, `execution_mode: "live"`, an Upstox `broker_order_id` and an idempotency `order_tag` of `BP-{approval_id}-{payload_hash[:10]}`. Upstox rejects orders that do not originate from a registered static IP; set `UPSTOX_ORDER_PROXY_URL` to route order calls through one. Statuses are refreshed via `/orders/{id}/sync`.

### Simulated PayPal capture

```bash
curl -s -X POST http://127.0.0.1:8000/api/paypal/simulate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"invoice_id":1}'
```

The response is labelled `mode: "simulated"` / `simulation: true`. Repeating it returns the same recorded payment rather than double-counting.

### Demo webhook signature

When PayPal is not configured, local demo events require an HMAC-SHA256 header:

```python
import hashlib, hmac

signature = "sha256=" + hmac.new(
    b"demo-paypal-webhook-secret",          # PAYPAL_DEMO_WEBHOOK_SECRET
    raw_body,
    hashlib.sha256,
).hexdigest()

# POST raw_body to /api/paypal/webhook with:
# X-FINOVEXA-Demo-Signature: <signature>
```

Unsigned/invalid events return `401`. Duplicate event IDs return `duplicate: true` without extra cash.

### Reset demo data

```bash
curl -s -X POST http://127.0.0.1:8000/api/demo/reset \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"confirm":"RESET DEMO"}'
```

Only the seeded demo account may reset (other accounts receive `403`), and the exact phrase is required. Reset restores the configured seed: with `SEED_DEMO_TRANSACTIONS=false` (default) the business returns to a clean slate with customers, products and settings but zero balances and no ledger records; set it to `true` for the full demo ledger.
