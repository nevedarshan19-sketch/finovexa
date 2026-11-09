# Live vs simulated

FINOVEXA never presents simulated output as live. Every data source carries a mode label, and the UI displays it next to the value.

## Modes

| Label | Meaning |
| --- | --- |
| **LIVE** | Fetched from a configured external provider within its freshness window. |
| **LIVE ORDER** | A real order submitted to Upstox from an owner-approved request. Shown with a red LIVE badge; real money moves. |
| **DELAYED** | Real data from a live provider that publishes it with a lag. Genuine market values, but not exchange-grade realtime and not an execution price. |
| **SANDBOX** | A real provider API in its sandbox environment. No real money moves. |
| **SIMULATED** | Produced by the local simulator for workflow demonstration. No external system was contacted. |
| **STALE** | Previously live data older than its freshness window. |
| **DEMO** | Seeded sample record. Never represented as live. |
| **EMPLOYEE-RECORDED · UNVERIFIED** | Self-reported cash or PayPal receipt entered by staff. It affects the owner's ledger immediately but was not verified by any provider. |
| **UNAVAILABLE** | No verified value exists. Nothing is invented. |

## Capability matrix

| Capability | Out of the box | When configured | Can it change money or external state? |
| --- | --- | --- | --- |
| AI chat | Rules-based deterministic analyst (`mode: rules`) calls read-only tools. | OpenAI-compatible LLM (`mode: llm`) with the same tool allowlist and Pydantic validation. | No. Tools are read-only; approvals are separate. |
| AI tools | 10 read-only tools scoped to the signed-in business. | Same. | No. |
| Reminder execution | Approval executes a **simulated dispatch**; audit records `reminder.simulated_dispatch`. | No email transport exists in this build. | No email is sent. |
| PayPal checkout | `POST /api/paypal/simulate` records a clearly labelled simulated capture. | Sandbox orders and capture via PayPal REST. | Sandbox only; no real money. |
| PayPal webhooks | HMAC demo signature (`X-FINOVEXA-Demo-Signature`) required; unsigned → 401. | PayPal signature verification via `PAYPAL_WEBHOOK_ID`. | Only updates the local ledger after verification. |
| Pending/failed payments | Recorded for reconciliation; never counted as cash. | Same. | No. |
| Employee portal entries | Staff record invoices, paid sales and purchases into the owner's ledger. Payments are stamped `employee_recorded` and shown as **unverified**. | Same. | Updates the local ledger only. A recorded PayPal receipt is not a PayPal API capture or a verified webhook. |
| GST & Billing | Real backend calculation with `Decimal` precision, configurable rates and stored per-line tax snapshots. Invoices lacking a place of supply are stored as **GST not split**, not guessed. | Same; PayPal uses sandbox capture when configured. | Updates the local ledger. The A4 PDF is generated locally. No e-invoicing/IRN or GSTR filing is performed. |
| Tax Center — GST | Real arithmetic on your own invoices and purchase bills: CGST/SGST/IGST split, output GST, input-credit ledger and estimated net GST. No AI decides a number; no paid API is called. | Same. | Read-only over the local ledger plus the input-credit rows you record. Nothing is filed and no tax is paid. |
| Tax Center — income tax | Deterministic slabs, rebate, surcharge and cess read from versioned rule sets stored in the database, labelled with the financial year, assessment year and rule version. | Same. | **Estimate only.** Not a filing. A saved estimate needs an accountant's name and ICAI membership number before it is marked approved, and approval is a record, not a return. |
| Broker orders (simulated, default) | Approve → `simulated_pending`, then `simulated_filled` / `simulated_cancelled` locally. Stock and NIFTY option buys and sells are supported. A stock fill updates the **simulated practice portfolio** (weighted average cost on buys, capped reduction on sells). | Unchanged. | No external order. Simulated sells do not check holdings, margin or settlement; option orders use 75 units per lot. |
| Broker orders (live, opt-in) | Off. `UPSTOX_LIVE_TRADING_ENABLED=false`. | With the flag on, a token, a live quote/chain, an INR profile and `execution_mode: "live"` on the approval, approving sends a real Upstox order. | **Yes — real money.** Default-off; every order needs explicit owner approval. Status sync and cancellation hit Upstox. |
| Indian market panel (NIFTY 50, Bank NIFTY, SENSEX) | Keyless Yahoo Finance quotes and candles for the three indices and all 50 constituents, always labelled **DELAYED** with source and IST timestamps. No signup, key or account. | Same provider; when `UPSTOX_ACCESS_TOKEN` is set the separate trade desk prefers **LIVE** Upstox quotes, while this panel keeps saying which source it used. | Read-only. No order can be placed from the panel; provider failures show **UNAVAILABLE** and a last-good snapshot is marked **STALE**, never relabelled live. |
| Upstox market data | Seeded DEMO quotes and candles for all 50 NIFTY constituents plus a DEMO NIFTY option chain. | Read-only quotes (one batch call for the 50-stock desk), historical candles and a live option chain if a token is configured. | Read-only; live order routing is a separate, explicit opt-in. |
| Indian market simulator | Synthetic 50-stock NSE-style session with technical analytics, breadth, sectors and movers, refreshed every 5 seconds from a deterministic engine. Always labelled **SIMULATED**. | Unchanged — this panel is intentionally independent of provider quotes. | No external feed is contacted and no order can be placed from it. |
| Metals (gold/silver) | DEMO quotes marked `data_mode: demo`. | Provider quotes with source and timestamp. | No. |
| News | Seeded DEMO headlines from a demo newsroom. | NewsAPI headlines with source, URL, timestamp and dedupe. | No. News is untrusted data, never instructions. |
| Forecasts | Deterministic probability-weighted projection. | Same (LLM can explain, not compute). | No. |
| Research signals | Model-generated rules signal with methodology, risks and data-quality note. | Same. | No. |
| Quick stock ideas | Four plain-language ideas from the rules-based signals, refreshed hourly and labelled **model-generated · not investment advice**. A toast names a new idea set once. | Same. | No. It never creates or approves an order. |
| Practice investment portfolio | Seeded demo holdings valued with **DELAYED** NSE prices and labelled **SIMULATED HOLDINGS**; simulated fills approved in the trade desk update quantity and average cost. | Same provider. It never mirrors a real Upstox/demat account. | No real money and no broker position change; brokerage, taxes, corporate actions and settlement are ignored. |
| Analyst ratings | Empty list with an explicit "not fabricated" note. | Same. | No. |
| Market/price display | All values labelled DEMO. | LIVE only within freshness window, otherwise STALE. | No. |

## Enable an integration

1. Copy `backend/.env.example` to `backend/.env`.
2. Fill the relevant variables (never commit them).
3. Restart the API.
4. Open **Settings → Integrations** and run **Check connection**.
5. Confirm the mode chip changes (for example DEMO → LIVE or SANDBOX).

| Integration | Variables | Fallback |
| --- | --- | --- |
| LLM | `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | Deterministic analyst |
| PayPal | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE_URL`, `PAYPAL_WEBHOOK_ID` | Simulated capture |
| Upstox | `UPSTOX_ACCESS_TOKEN` (OAuth token created outside the browser) | DEMO quotes |
| Upstox live orders | Above plus `UPSTOX_LIVE_TRADING_ENABLED=true`, `UPSTOX_ORDER_BASE_URL`, and `UPSTOX_ORDER_PROXY_URL` pointing at a registered static-IP egress | Simulated orders; live execution unavailable |
| Indian market quotes | No credentials. Optional `YAHOO_FINANCE_BASE_URL` and `INDIA_MARKET_CACHE_SECONDS` tune the host and cache TTL. | UNAVAILABLE with an explanatory note; no price is fabricated |
| Metals | `METALS_API_KEY` | DEMO gold/silver |
| News | `NEWS_API_KEY` | DEMO headlines |

## Live trading guardrails

- Off by default (`UPSTOX_LIVE_TRADING_ENABLED=false`).
- Requires a configured Upstox token, a live quote or live option chain, and an INR business profile.
- Never triggered by AI output, a news headline or a signal label; a human must create and approve the exact order.
- Every live order carries a `BP-{approval}-{payload-hash}` tag. On timeout, the backend checks the Upstox order book before marking the approval failed, so a retry cannot silently duplicate an order.
- Market orders request Upstox automatic market protection (`market_protection: -1`) so a fill is not accepted at an unbounded price.
- Upstox requires order traffic from a registered static IP. Use `UPSTOX_ORDER_PROXY_URL` when the app host does not have one.
- Live status is synced or cancelled explicitly from the UI; the simulator endpoints reject live orders.

## Deliberately not implemented

- Automatic or algorithmic live trading without per-order human approval.
- Real email or SMS delivery.
- Card collection or storage.
- Automatic financial actions from AI output or a signal label.
- Automatic payment capture without verified provider evidence.
