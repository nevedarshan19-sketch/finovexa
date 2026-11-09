# FINOVEXA AI

A working, full-stack business operations and financial intelligence app for small businesses. It combines the ledger (invoices, payments, expenses, obligations), cash-flow forecasting, collections, market context, model-generated research signals, and an owner-controlled approval queue with an auditable trail.

The business owner sees the full dashboard. A separate, server-enforced **employee portal** lets staff generate invoices and record paid sales and purchases without exposing owner routes, cash totals, approvals or market data. A third, env-provisioned **developer console** manages owner/employee accounts and reviews auth audit events without access to any business ledger.

A public marketing site (`/home`, `/features`, `/pricing`, `/about`, `/contact`) is available without a session. **Market Intelligence** publishes NIFTY 50 research: every NSE NIFTY 50 constituent is screened on the same documented rules, positive-upside ideas are separated from no-signal and insufficient-data names, and every figure carries its market-data source and timestamp. These recommendations are informational only and are not investment advice.

> Every external capability has an offline demo mode. Anything simulated is labelled **SIMULATED**, **DEMO**, **SANDBOX**, **DELAYED**, **STALE** or **UNAVAILABLE** in the UI. No email is sent, and no money moves unless an owner explicitly approves a live Upstox order after live trading is enabled. Live trading is off by default.

![stack](https://img.shields.io/badge/React-18-149ECA) ![stack](https://img.shields.io/badge/TypeScript-5.7-3178C6) ![stack](https://img.shields.io/badge/FastAPI-0.162-009688) ![stack](https://img.shields.io/badge/SQLite-SQLAlchemy%202-003B57)

## Feature map

| Page | What it does |
| --- | --- |
| Overview | Recorded cash, revenue/expenses, receivables, reserve headroom, alerts, obligations, low stock, deterministic business insights. |
| Business Analytics | Accrual vs cash, margins, revenue trend, expense mix, product/customer performance, inventory. |
| Money Recovery | Aging buckets, priority scoring, duplicate-invoice detection, unmatched payment suggestions, reminder drafts that require approval. |
| Cash Flow | 7/30/90-day probability-weighted forecasts, reserve floor, conservative/base/optimistic scenarios, sensitivity, shortfall date, investable surplus. |
| Market Intelligence | Gold, silver, NIFTY 50, SENSEX and Indian equities with source, timestamp, freshness and data-mode labels; attributed, deduplicated news. |
| Investment Research | A plain-language owner view: a quick idea notification with one-line model reasons, a separate **simulated practice portfolio** valued with delayed NSE prices, and real NSE market data for the NIFTY 50, NIFTY Bank and SENSEX through a keyless provider, shown as **DELAYED** with provider, source timestamp and IST session state (index tiles, breadth, movers, per-stock intraday/daily charts, SMA/RSI and 52-week range); model-generated signals with methodology, risks and disclosures; analyst ratings are never fabricated; a separate, clearly labelled simulated session that analyses all 50 NIFTY constituents (RSI, SMA, VWAP, breadth, sectors, movers); NIFTY option chain plus an all-50-constituent trade desk with owner-approval order tickets. Execution is simulated by default and can be switched to live Upstox when the backend is configured for it. |
| Ask FINOVEXA | Chat over authorized read-only tools with citations, facts vs estimates vs interpretations, uncertainty, deterministic fallback, and prompt-injection defenses. |
| Approval Center | Exact-payload hash, expiry, duplicate protection, approve/reject, simulated reminder dispatch, simulated or live Upstox stock and option buy/sell orders, cash-flow acknowledgements. Live orders are highlighted in red and only send to Upstox after explicit approval. |
| Payment Center | Invoices, PayPal sandbox/live checkout, server-verified captures, owner-confirmed refunds, stored orders, webhook event log, reconciliation history, and date/status/currency filters. Verified net totals separate pending, failed and refunded money. Pending/failed never count as cash. |
| GST & Billing | GST invoice register with backend-authoritative decimal math: per-line HSN/SAC and configurable 0/5/12/18/28% rates, exclusive or inclusive pricing, discounts before tax, CGST+SGST vs IGST from a verified place of supply, A4 print/PDF, and payment status from confirmed records. Invoices without a verified place of supply are stored as **GST not split** rather than guessed. |
| Tax Center | Deterministic, no-AI GST and income-tax engine. GST: multi-line inclusive/exclusive calculator, CGST/SGST/IGST split, invoice-wise and by-rate/by-HSN reports, input-tax-credit ledger (eligible/claimed/blocked), estimated net GST, and a verified HSN/SAC registry. Income tax: salary, business/44AD/44ADA, other income and capital gains, Chapter VI-A deductions, old-vs-new comparison with a recommended regime, 87A rebate and surcharge marginal relief, cess and final estimate — all read from versioned rule sets stored in the database, with the financial year, assessment year and rule version shown on every result. Saved estimates need an accountant's name and ICAI membership number before they are marked approved; approval is a record, never a filing. |
| Activity & Audit | Per-business audit log with filters, before/after detail, protected fields and a note on credential redaction. |
| Settings & Integrations | Business profile (reserve, risk, research interests, reminder tone), PayPal sandbox/production selector with masked hints and connection test, integration modes/health checks, runtime modes, demo reset. |
| Team Entries (owner) | Employee roster, create and pause employee logins, and a live feed of sale, purchase and invoice entries attributed to each employee. |
| Employee Portal (separate login) | Employee day view, invoice generation with line items and tax, sale and purchase entry editor with edit/void rules. Employees cannot open owner routes or owner APIs. |
| Developer Console (separate login) | Env-provisioned platform account. Creates owners/employees, edits their login email and password, pauses accounts, reviews scoped auth/team audit events, reviews contact messages and checks system readiness. No owner ledger, invoices, payments, approvals or market positions. |
| Public site (no login) | Premium dark marketing surface: home, features, pricing, about and contact. The contact form validates server-side, requires consent and uses a honeypot plus per-IP rate limits; it never invents contact details or customer counts. |
| Market Intelligence (public) | Live NIFTY 50 research workspace: all 50 constituents screened on one documented rule set, with latest price, market-data timestamp, provider, target price, upside, horizon, confidence, indicators, risks, methodology and disclaimer. Positive-upside ideas are separated from a "No Positive Upside Signal" list and an explicit insufficient-data bucket; search, sort, horizon and confidence filters are available. |

## Stack

- **Frontend:** React 18, TypeScript 5.7 (strict), Vite 5, Tailwind CSS 3, Recharts, Lucide, React Router 6. Local shadcn-style primitives. Vitest + Testing Library.
- **Backend:** FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, PyJWT, pandas/numpy for deterministic finance. Pytest.
- **AI:** OpenAI-compatible orchestrator with a maximum of 5 tool loops, schema validation, authorized read-only tools, and a no-key deterministic analyst fallback.
- **Integrations:** PayPal (sandbox/simulated), Upstox (live quotes; live order placement off by default), Yahoo Finance (keyless, delayed NSE/BSE quotes — no credentials), Metals.dev (optional), NewsAPI (optional). Credentials, where needed, live only in backend environment variables.

## Quickstart

Prerequisites: Python 3.12+, Node.js 20+ (Node 22 recommended), npm.

### 1. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # optional; defaults work offline
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API: http://127.0.0.1:8000 · Swagger: http://127.0.0.1:8000/api/docs · Health: http://127.0.0.1:8000/api/health

The first start creates `backend/finovexa.db`. With `AUTO_SEED=true` (the development `.env.example` default) it also seeds the demo business and global market demo data; the seed is idempotent and starts clean — ₹0 opening cash, ₹0 reserve and no invoices, payments, expenses or portfolio — while keeping customers, products, GST settings and the employee account. `AUTO_SEED=false` is the production default: the database starts empty except reference market and tax data, and the first login comes from the `DEVELOPER_*` environment variables (with `INITIAL_*` available if you choose startup provisioning instead).

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://127.0.0.1:5173. Vite proxies `/api` to `127.0.0.1:8000`.

If `npm` is not on your shell `PATH` in this environment, prefix commands with `PATH=/Users/darshanyogeshneve/.local/node-v22/bin:$PATH`.

### 3. Demo login (when `AUTO_SEED=true`)

Owner (full dashboard):

```text
URL:      http://127.0.0.1:5173/login
Email:    demo@finovexa.ai
Password: Demo1234!
```

Employee (scoped portal):

```text
URL:      http://127.0.0.1:5173/employee/login
Email:    employee@finovexa.ai
Password: Employee1234!
```

Developer (only when `DEVELOPER_EMAIL` + `DEVELOPER_PASSWORD` are set on the backend):

```text
URL:      http://127.0.0.1:5173/developer/login
Email:    value of DEVELOPER_EMAIL
Password: value of DEVELOPER_PASSWORD
```

There is no default or demo developer account. Set the env vars before startup; the backend seeds or syncs the account. The password must be at least 12 characters and contain a letter and a digit.

Registration also works and creates an isolated, empty business with its own reserve and risk settings.

### 4. Owner, employee and developer access model

- The owner signs in at `/login`; employee and developer accounts are rejected by the owner login endpoint.
- Employees sign in at `/employee/login`; owner and developer accounts are rejected by the employee login endpoint.
- Developers sign in at `/developer/login`; owner and employee accounts are rejected by the developer login endpoint.
- Owner, employee and developer routes each render only for the matching session. Navigating to the wrong side redirects to the correct portal.
- Owner APIs are mounted behind `get_current_owner`; `/api/employee/*` is behind `get_current_employee`; `/api/developer/*` is behind `get_current_developer`. Cross-role calls return **403** even with a valid token.
- The developer can manage owner/employee accounts (create, change login email, reset password, pause) and review auth/team audit events. Developer APIs never expose ledger, invoice, payment, approval, cash or position data, and no API can create a developer or change a role.
- Disabling an owner immediately invalidates their employees' tokens and blocks new employee logins until the owner is re-enabled.
- Employee writes are posted to the owner's ledger under the owner's tenant, so cash, receivables, expenses, Payment Center and the owner dashboard update immediately (dashboard polling, not a websocket push).
- Employee-recorded cash and PayPal receipts are labelled **employee-recorded · unverified**; only provider-verified captures are treated as verified money. Entries with a confirmed payment are locked against employee edits or voiding.
- Employee entry lines that match a catalogue product (picked from the stock combobox, or an exact name/SKU) move that product's stored quantity: purchases add stock, sales and invoices reduce it. Editing or voiding an entry reverses the previous movement. Free-text lines such as rent or marketing never touch stock, and quantities for catalogue products must be whole units.
- Owners create and pause employee logins on the Team page. Paused employees lose access on their next request while their history remains in the ledger.
- Public visitors can read the marketing site and Market Intelligence research. They cannot open owner, employee or developer routes or any business ledger.
- Market recommendations are public research output: every card carries the provider, market-data timestamp and freshness label, and unavailable inputs are shown as unavailable rather than estimated from invented data.
- The developer role is provisioned only from backend environment variables. It cannot be created, promoted or requested through registration, the API or a special URL.

## GST & Billing setup

Open **GST & Billing** in the owner navigation.

1. **GST setup tab** — save the supplier state (and GSTIN when you have a registered number) and review the active GST rates. Rates are configuration data, seeded with 0/5/12/18/28%; the calculation engine reads the configured list and rejects rates that are not active. Changing a rate here does not rewrite invoices already issued.
2. **Product catalogue tab** — each product carries its own default GST rate, HSN/SAC and unit. Selecting a product in the editor prefills a line; overriding the rate on that line never changes the saved product default.
3. **New invoice** — choose the customer, confirm the **place of supply**, and tick the verification checkbox. The backend recalculates every line with `Decimal` arithmetic and rejects inconsistent totals, invalid quantities, discounts above the line value and inactive rates.
4. **Preview / save / issue** — *Preview A4* renders the exact document; *Save draft* keeps it editable; *Issue invoice* stores the tax snapshot. Print and **Download PDF** use that stored snapshot, so later catalogue or rate changes cannot alter an issued invoice.
5. **Payments** — record only verified receipts with a reference. PayPal uses the sandbox when credentials are configured; otherwise the button opens a clearly labelled **simulated** payment dialog. Nothing is marked paid from a client-side success message alone.

GST rules implemented:

- Exclusive: `taxable = qty × unit price − discount`, `GST = taxable × rate ÷ 100`, total = taxable + GST.
- Inclusive: `taxable = amount ÷ (1 + rate ÷ 100)`; GST is the remainder.
- Same supplier and place-of-supply state → CGST + SGST (equal split); different states → IGST. Never both.
- Rounding is applied per line at 2 decimals; the optional rupee rounding adjustment is stored and shown.
- Missing supplier or place-of-supply state → the invoice is stored as `unverified` with **no CGST/SGST/IGST allocation** and the tax kept in the tax total. The register and PDF show *GST not split*. Edit the invoice, choose the place of supply and re-issue to obtain a verified split.

> GST rates, HSN/SAC classification and place-of-supply treatment must be verified by the business for each supply. FINOVEXA does not guess a rate or legal classification, and the app is not e-invoicing or GSTR filing software. Confirm the applicable rate and invoicing rules before issuing a real tax invoice.

Legacy databases are migrated safely: the GST columns are added, tax already recorded is preserved, and older invoices are marked `unverified` instead of receiving a fabricated split.

## Tax Center

Open **Tax Center** in the owner navigation. It has no paid dependency: every figure is plain arithmetic on rows stored in the database, and no AI model decides a tax amount.

**GST module**

1. **Calculator** — any number of lines with quantity, unit price, discount and GST rate; exclusive or inclusive pricing; an optional other-charges amount; rupee rounding. The result shows the taxable value, the CGST/SGST or IGST split, the total and a per-line table. Nothing is saved.
2. **Reports** — invoice-wise output GST for a chosen period, reconciled by rate and by HSN/SAC, with warnings for invoices without a verified supply type and lines without an HSN/SAC code. Periods are capped at about two financial years.
3. **Input credit** — a purchase-bill ledger with supplier GSTIN validation (including the GSTIN check digit), exclusive CGST/SGST vs IGST checks, a tolerance check against rate × taxable value, and eligible/claimed/blocked status. Blocked credit never counts. The ledger is all-time; explicit date filters are available on the API.
4. **HSN / SAC** — a per-business registry the owner confirms: HSN codes of 2/4/6/8 digits or a 6-digit SAC, a default rate, and a "verified" flag. FINOVEXA never invents a classification.

Net GST = output tax on output invoices − available input credit, shown as payable, refundable or nil.

**Income-tax module**

- Rule sets live in `tax_rule_sets` and child tables (`tax_slabs`, `tax_surcharge_bands`, `tax_rebate_rules`, `tax_constants`, `tax_deduction_caps`, `tax_capital_gains_rules`), keyed by financial year, regime and version. The app seeds published Finance Act figures and shows the version, effective dates and source note with every result; changing a rate means adding a rule set, not editing code.
- Inputs cover salary (gross, basic, HRA, rent, professional tax, employer NPS, metro flag), business income (books, 44AD with the digital-receipt split, 44ADA), other income, 111A/112A capital gains and Chapter VI-A deductions.
- Output covers the old-vs-new comparison with the cheaper regime marked recommended, gross and total income, every allowed deduction with its cap and reason, slab-by-slab tax, 87A rebate and marginal relief, surcharge bands with marginal relief, 111A/112A tax, 4% health and education cess, section 288A-style rounding, the effective rate and the final estimate.
- Estimates can be saved as drafts. Marking one **approved** requires the accountant's name and ICAI membership number, and writes `tax_estimate.approved` to the activity log. Approval only records a sign-off — FINOVEXA never files a return or pays tax.

> Every tax figure is an estimate. GST treatment, HSN/SAC classification, slab applicability and every income-tax number must be confirmed by the business and a chartered accountant against the notifications and Finance Act in force for the relevant financial year before any filing.

## Tests

```bash
# Backend: 186 tests
cd backend
.venv/bin/python -m pytest -q

# Frontend: 60 tests
cd frontend
npm test

# Production build + TypeScript check
npm run build
```

Coverage includes auth and tenant isolation, owner/employee/developer role isolation, developer account management and least privilege, owner-disable employee revocation, ledger propagation, invoice/payment math, recovery aging, cash-flow consistency and scenarios, market labelling, research disclosures, approval hash/expiry/idempotency, PayPal webhook verification, AI tool safety and prompt injection, audit redaction, demo reset, the GST suite (0/5/12/18/28 rates, multi-rate invoices, inclusive pricing, discount-before-tax, intra/inter-state splits, rounding, invalid lines and rates, missing place of supply, issue-time snapshots, PDF rendering, partial/full payments and tenant isolation), the NIFTY 50 recommendation screen (all-50 coverage, upside arithmetic, no-signal separation, unavailable-data handling, no strong-buy-from-upside-alone), and the tax engine (37 tests: financial-year bounds and leap years, new and old regime slabs, standard deduction, HRA metro/non-metro, 87A rebate and marginal relief, surcharge marginal relief at 50L/1cr/2cr, 111A/112A and other LTCG, 44AD digital split and 44ADA, regime comparison, GST inclusive/exclusive and intra/inter-state calculator, HSN/SAC CRUD and validation, input-credit checks and ledger, net GST, invoice-wise reports, estimate save/approve/reopen, owner-only isolation and rule-version payloads).

## Production container

The image builds the React app and serves it from FastAPI on a single origin, with a strict Content-Security-Policy and SPA fallback.

```bash
cd /Users/darshanyogeshneve/DHAN
docker build -t finovexa-ai .
docker run --rm -p 8000:8000 \
  -e ENV=production \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  -v finovexa-data:/app/data \
  finovexa-ai
```

Open http://127.0.0.1:8000. For a public deployment:

- **Zero-cost stack (recommended):** Render Free web service + Neon Free Postgres +
  `FILE_STORAGE=database`. Render's filesystem is ephemeral, so Postgres must hold all
  data and uploads. The full runbook, free-tier limits, backup commands and go-live
  checklist are in [`deploy/FREE_STACK.md`](deploy/FREE_STACK.md).
- **Production safety:** `ENV=production`, `AUTO_SEED=false`,
  `DEMO_RESET_ENABLED=false`. Production currently boots with developer-only
  bootstrap: set `DEVELOPER_EMAIL` and `DEVELOPER_PASSWORD` and leave every `INITIAL_*`
  variable unset. The developer signs in at `/developer/login` and creates or repairs
  owner, employee and accountant logins from the console. No demo records are created.
- **Persistent database:** the app accepts `postgres://`, `postgresql://` and
  `postgresql+psycopg://` Neon/Supabase URLs and uses psycopg 3. Keep `SECRET_KEY` and
  `PAYMENT_DOCUMENT_KEY` stable in the host environment so sessions and encrypted
  statement originals survive restarts.
- **Railway:** `railway login`, `railway init`, then `railway up` from this directory.
  Attach a volume at `/app/data` if you deliberately run SQLite.
- External provider keys are optional; the app stays in simulated/demo mode without them.

## Environment variables

All variables are documented with placeholders in [`backend/.env.example`](backend/.env.example). Core settings:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | JWT signing key. Replace for any non-local use. |
| `DATABASE_URL` | SQLAlchemy URL; defaults to `backend/finovexa.db`. Use a managed Postgres URL for public deployments so data survives restarts. |
| `AUTO_SEED` | `true` seeds demo users and business data at startup. Defaults to `false`; production ignores it when `ENV=production`. |
| `DEMO_RESET_ENABLED` | Enables the demo-only reset endpoint. Defaults to `false`. |
| `SEED_DEMO_TRANSACTIONS` | `false` (default) seeds a clean business — customers, products and settings but zero balances and no ledger records. `true` seeds the full demo ledger, expenses and simulated portfolio. |
| `INITIAL_OWNER_*`, `INITIAL_BUSINESS_NAME` | Optional startup provisioning for a first owner and business profile. Off by default in the free-stack production config, which uses developer-only bootstrap. Passwords need ≥12 characters with a letter and a digit. Existing accounts are never modified. |
| `INITIAL_SENIOR_ACCOUNTANT_*`, `INITIAL_JUNIOR_ACCOUNTANT_*` | Optional startup provisioning for first accountant logins. Leave blank to create them from the developer console instead. |
| `FILE_STORAGE` | `local` writes uploads to `ACCOUNTING_UPLOAD_DIR`; `database` keeps them in the `stored_files` table so they survive redeploys on hosts without a disk. |
| `DEMO_EMAIL` / `DEMO_PASSWORD` | Seeded demo owner login. |
| `DEMO_EMPLOYEE_EMAIL` / `DEMO_EMPLOYEE_PASSWORD` | Seeded demo employee login, linked to the demo owner's business. |
| `DEVELOPER_NAME`, `DEVELOPER_EMAIL`, `DEVELOPER_PASSWORD` | Optional developer console account, provisioned only from backend env. Blank → developer portal disabled. Password ≥12 chars with a letter and digit. |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Optional OpenAI-compatible orchestration. Empty → deterministic fallback. |
| `PAYPAL_ENVIRONMENT` | Default `sandbox`. The owner can select sandbox or production in Settings; the app never enables production automatically. |
| `PAYPAL_SANDBOX_CLIENT_ID`, `PAYPAL_SANDBOX_CLIENT_SECRET`, `PAYPAL_SANDBOX_WEBHOOK_ID` | Sandbox REST credentials and webhook ID. Empty → simulated checkout. |
| `PAYPAL_LIVE_CLIENT_ID`, `PAYPAL_LIVE_CLIENT_SECRET`, `PAYPAL_LIVE_WEBHOOK_ID` | Production credentials. Required before production mode can be enabled, and kept separate from sandbox keys. |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE_URL`, `PAYPAL_WEBHOOK_ID` | Legacy single-environment fallback for older deployments. |
| `PAYPAL_DEMO_WEBHOOK_SECRET` | HMAC secret for local demo webhook signatures only. |
| `UPSTOX_ACCESS_TOKEN` | Upstox quotes, historical candles, NIFTY option chain, and broker order placement when live trading is enabled. |
| `UPSTOX_LIVE_TRADING_ENABLED` | Default `false`. Enables the live order path; every order still needs an owner approval, a live quote and an INR business profile. |
| `UPSTOX_ORDER_BASE_URL` / `UPSTOX_ORDER_PROXY_URL` | Upstox order host (default `https://api-hft.upstox.com/v2`) and optional registered static-IP egress proxy. Upstox requires order traffic from a registered static IP. |
| `YAHOO_FINANCE_BASE_URL` | Keyless quote host for the real Indian market panel (default `https://query1.finance.yahoo.com`; the client fails over to `query2`). No key or account is required. |
| `INDIA_MARKET_CACHE_SECONDS` | TTL for the cached NSE overview payload (default `60`). Detail responses cache for 60 s intraday, 300 s daily. |
| `METALS_API_KEY`, `NEWS_API_KEY` | Optional live market data/news. Empty → DEMO data. |

Never commit a real `.env`. The browser never receives keys: `/api/settings/runtime` and `/api/integrations` expose booleans, modes and timestamps only.

## Architecture

```text
backend/
  app/
    main.py              app factory, lifespan seed, CORS, security headers
    config.py            env-backed settings
    models.py            SQLAlchemy models (users, businesses, invoices, payments, approvals, orders, market, audit, chat)
    schemas.py           Pydantic request/response validation
    security.py          JWT auth, PBKDF2 hashing, rate limiting, tenant scoping
    seed.py              rich demo data, demo employee and demo reset
    routers/             auth, profile, dashboard, invoices, cashflow, market, ai, approvals, payments, audit, settings, employee, team, developer, tax
    services/
      finance.py         Decimal-safe ledger math and aging
      payments.py        recording, matching, idempotency
      employee_entries.py employee sale/purchase/invoice writes, edit/void locks and attribution
      recovery.py        priority scoring, duplicates, reminder drafts
      forecasting.py     probability-weighted forecasts, scenarios, sensitivity
      market.py          quote/news caching, freshness, data-mode labels
      research.py        model signals, disclosures, broker status
      india_market.py    NSE/BSE overview and stock detail, caching, stale fallback, indicators
      approvals.py       canonical payload hash, expiry, simulated/live execution, audit
      gst_reports.py     GST calculator, invoice reports, ITC ledger, HSN registry, net GST
      income_tax.py      deterministic slab/surcharge/rebate engine over versioned rule sets
      ai/                orchestrator, read-only tools, rules fallback
      integrations/      PayPal, Upstox, Yahoo Finance, metals, news clients
  tests/                 186 pytest tests
frontend/
  src/
    pages/               owner pages incl. GST & Billing and Tax Center, 3 employee pages, developer console, three role-specific logins
    components/          design system, badges, charts, insight cards, owner/employee/developer shells
    context/             auth and toast providers
    hooks/               API fetch hooks with optional polling
    lib/                 typed API client, types, formatters
```

**Money:** stored and computed as `Numeric(16,2)` / `Decimal` with `ROUND_HALF_UP` on the server. The JSON layer emits numbers (parsed by the UI with `Intl.NumberFormat`). Only confirmed payments count as cash.

**Approvals:** every approval stores a SHA-256 hash of a canonical JSON payload. Approval requires the same hash and `confirm: true`. Expiry windows: reminders 24h, investments 30m, cash-flow interventions 72h. Execution is one-shot; failures are recorded as `failed` with an error, and investment headroom is re-checked at execution. Live Upstox approvals additionally require a unique `BP-{approval}-{hash}` order tag, and timeouts are reconciled against the Upstox order book before an approval is marked failed.

**AI safety:** tools are read-only and server-authorized for the current business. Tool output, news and invoice notes are untrusted data, never instructions. The orchestrator cannot change payment, approval or order state.

## Live vs simulated

| Capability | Default (no keys) | With credentials |
| --- | --- | --- |
| AI chat | Deterministic rules analyst, mode `rules` | OpenAI-compatible LLM over the same read-only tools, mode `llm` |
| PayPal checkout | SIMULATED capture endpoint, no external call | Sandbox or production orders/capture via the REST API with signature-verified webhooks, refunds and stored provider references |
| Reminder dispatch | Simulated dispatch recorded in audit | Still simulated — email transport is intentionally not implemented |
| Broker orders | SIMULATED stock and option buy/sell orders, approve → simulated order | Live Upstox orders available when `UPSTOX_LIVE_TRADING_ENABLED=true`, a token is configured and the quote/chain is live. Every live order still requires an owner approval and a registered static IP. |
| Market quotes/news | DEMO seeded data, explicitly labelled | Attributed provider data with freshness/staleness labels |
| Indian market data (NIFTY 50 / Bank NIFTY / SENSEX) | Real quotes fetched keylessly from Yahoo Finance, always labelled **DELAYED** (provider may lag the exchange by minutes). No key needed. | With `UPSTOX_ACCESS_TOKEN` set the research desk prefers Upstox **LIVE** quotes; the public panel stays DELAYED and says which provider served each value. |
| Upstox quotes | DEMO quotes for all 50 NIFTY constituents and the NIFTY option chain | Authorized read-only quotes (batched for the 50-stock desk) and a live option chain if a token is configured |

Full detail: [`docs/LIVE_VS_SIMULATED.md`](docs/LIVE_VS_SIMULATED.md).

## Security and trust boundaries

- Passwords: PBKDF2-SHA256 (390,000 iterations), never logged or returned.
- JWT bearer auth, per-IP sliding-window rate limits on login/register/chat/reset/webhooks.
- Owner, employee and developer sessions are separated at the router and UI-route level. Each token receives 403 from the other portals' APIs and is redirected away from their pages.
- The developer account exists only when its env vars are configured. No app endpoint can create a developer or promote an existing user, and developer APIs expose no business financial data.
- Every query is scoped by `user_id`; cross-tenant IDs return 404. Employee writes are scoped to the employee's linked owner and attributed on the created invoice, payment or expense.
- Employee-recorded cash/PayPal receipts are marked `employee_recorded` and shown as unverified; they are not claimed as provider captures or webhook-verified payments.
- Security headers: `nosniff`, `DENY` framing, `no-referrer`, restrictive permissions policy, `no-store` for API responses.
- PayPal webhooks require signature verification with the PayPal API when configured. With no provider configured, local demo events require the HMAC header; unsigned events return 401. Client-side success is never treated as payment proof.
- Pending/failed payments never increase recorded cash. Provider event IDs, refund IDs and payment idempotency keys prevent duplicates. Refunds require explicit owner confirmation; AI agents cannot capture or refund.
- PayPal client secrets, access tokens and full webhook IDs stay in the backend environment. Settings responses contain booleans and masked hints only; tokens are cached in memory and never logged.
- No raw card data is collected or stored.
- Live trading is default-off, owner-approval-gated and never triggered by AI output, a news headline or a signal label. The Upstox token is only read by the backend; order payloads are re-hashed and re-checked at execution.
- Audit details exclude credentials, tokens, passwords and card data.
- Demo reset is demo-account-only, requires the exact phrase `RESET DEMO`, and is rate-limited.

## Limitations

- Reminder approval records a **simulated** dispatch; no SMTP/email provider is wired.
- Broker orders are **simulated by default**. The optional live Upstox path requires `UPSTOX_LIVE_TRADING_ENABLED=true`, a configured token, a live quote/chain, an INR business profile and explicit owner approval. Simulated sells do not check holdings, margin or settlement; live orders are validated by Upstox. Live option orders use 75 units per lot, and FINOVEXA performs no margin or position accounting.
- Live Upstox orders must originate from a static IP registered with Upstox. Set `UPSTOX_ORDER_PROXY_URL` to route order traffic through such an egress; quotes and read-only market data do not need it.
- Live order execution is not exercised against the real broker in this repository's tests; the live path is covered with mocked Upstox responses.
- PayPal live mode is not exercised by tests; sandbox is supported and simulation is the default. The integration tests use an in-memory PayPal API fake and never contact PayPal.
- The PayPal environment selector is stored per deployment, so the active environment is shared by the business owner and any staff account. OAuth tokens are cached in memory per API process; a restart simply fetches a new token.
- GST & Billing produces an A4 invoice/PDF and stores the tax snapshot; it is not e-invoicing (no IRN/QR) and does not prepare or file GSTR returns.
- The place of supply is chosen by the owner; the app does not infer it from an address. Legacy invoices without a saved place of supply remain **GST not split** until edited and re-issued.
- Seeded rates (0/5/12/18/28%) are demo configuration, not a statement that a rate applies to a particular good or service. HSN/SAC classification and registration status must be verified by the business.
- Market data uses seeded DEMO data unless provider keys are supplied. Freshness and provenance are always shown.
- The real Indian market panel reads a **free, unofficial** Yahoo Finance endpoint, so quotes are delayed (often 1–15 minutes), may be rate-limited, and are not an exchange feed or an execution price. The panel labels this **DELAYED**, shows the source timestamp, and serves a last-good snapshot marked **STALE** rather than inventing a value; when nothing is available it renders **UNAVAILABLE**.
- Session open/closed state uses the fixed 09:15–15:30 IST Mon–Fri clock and does not detect NSE/BSE trading holidays.
- The practice portfolio is **simulated**: with `SEED_DEMO_TRANSACTIONS=true` it starts from seeded demo holdings (otherwise it starts empty), is valued with delayed provider prices, and is updated only by simulated fills approved in the trade desk. It never mirrors a real demat account, ignores brokerage, taxes, corporate actions and settlement, and its profit/loss is an indicative mark-to-market, not an accounting result.
- Quick stock ideas are a four-item slice of the rules-based signal set, refreshed hourly and labelled **model-generated · not investment advice**. They never create an order or trigger a trade.
- Upstox remains the path for exchange-authoritative quotes and any real order; the public panel never places orders.
- The AI fallback is deterministic and rule-based; it is an analyst assistant, not an investment adviser.
- Employee-recorded cash and PayPal receipts are self-reported by staff. They update the ledger immediately but remain marked unverified until the owner reconciles them; the owner dashboard and team feed refresh on a 10–15 second poll rather than a realtime push.
- SQLite is used for portability, not production concurrency. Migrations are not included; additive column upgrades run at startup for demo databases.
- Demo data/credentials are for local evaluation only.

## Demo scripts

- [`PAYPAL_SETUP.md`](PAYPAL_SETUP.md) — sandbox setup, webhooks, refunds, reconciliation, production checklist and tests.
- [`docs/DEMO_WALKTHROUGH.md`](docs/DEMO_WALKTHROUGH.md) — a 10-minute end-to-end walkthrough and reset.
- [`docs/TALLY_MIGRATION.md`](docs/TALLY_MIGRATION.md) — Tally historical import/export implementation report, formats, workflow and test results.
- [`docs/API.md`](docs/API.md) — endpoint reference and request examples.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — ports, rate limits, resets, test setup.

## Disclaimer

FINOVEXA AI is a demonstration build. It does not provide financial, investment, legal or tax advice. Model signals are illustrative, not analyst ratings or recommendations. Verify all figures against your own records before acting.
