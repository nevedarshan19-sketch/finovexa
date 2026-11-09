# Professional Accounting Services + Accountant Portal — Implementation Report

Implemented as an additive module on top of the existing FINOVEXA AI app. No existing
Business Manager, Employee, Market Intelligence, Tax Center, GST & Billing or PayPal feature was
removed or rewritten.

---

## 1. Database and migrations

No destructive migration and no Alembic baseline change. New tables are created by the
existing `Base.metadata.create_all()` on startup, followed by the existing additive
`ensure_schema_upgrades()` in `backend/app/database.py`. That means an existing SQLite or
Postgres database gains the new tables on next boot without losing data.

New tables (all defined in `backend/app/models.py`):

| Table | Purpose |
| --- | --- |
| `accounting_enquiries` | Public pricing-consultation requests (business, GST status, turnover, services, transaction volume) |
| `accounting_quotations` | Senior-prepared custom quotes + customer accept/decline decision |
| `accounting_clients` | Onboarded engagement: GSTIN, PAN last 4, type, turnover, FY, package, assigned accountant, status |
| `accounting_tasks` | Workflow tasks with service type, priority, due date, assignee, review state, review notes |
| `accounting_task_comments` | Task-level comments/attachments trail |
| `accounting_documents` | Uploaded client documents (random disk filename + SHA-256, per-client scope) |
| `accounting_document_requests` | Pending document requests shown in the customer portal |
| `accounting_messages` | Client ↔ practice conversation |
| `accounting_vouchers` | Sales/purchase vouchers with `(client_id, dedupe_hash)` unique constraint |
| `accounting_bank_imports` | Bank statement import batches |
| `accounting_bank_transactions` | Parsed bank rows, suggestion and confirmed match state |
| `accounting_tally_batches` | Legacy Tally import batches with validation results |
| `accounting_tally_exports` | Tally export batches: period, data types, format, file hash, validation snapshot, review decision, import status |
| `accounting_stock_items` | Client stock item masters (SKU, unit, HSN, GST rate, opening qty/rate) used by the stock-master export |
| `accounting_reports` | Monthly summary / GST working paper / financial statement reports and review decisions |
| `accounting_invoices` | Practice fee invoices |
| `accounting_invoice_payments` | Fee invoice payments (recorded manually — no card data) |
| `accounting_notifications` | Per-user portal notifications |

Roles `senior_accountant`, `junior_accountant` and `customer` are stored in the existing
`users.role` column — no schema change needed there.

Additive column upgrade: `ensure_schema_upgrades()` adds `accounting_vouchers.bank_ledger`
and `accounting_clients.business_profile_id` to an existing database
(`backend/app/database.py:225`). No columns are dropped or rewritten, and no stored voucher
figure is recalculated on upgrade. `business_profile_id` links an accounting engagement to
a Business Manager business without merging their ledgers.

## 2. Environment variables

New optional demo-seed variables (defaults are the seeded demo accounts):

```
DEMO_SENIOR_ACCOUNTANT_NAME="Anita Desai"
DEMO_SENIOR_ACCOUNTANT_EMAIL="senior@finovexa.ai"
DEMO_SENIOR_ACCOUNTANT_PASSWORD="Senior1234!"
DEMO_JUNIOR_ACCOUNTANT_NAME="Rahul Mehta"
DEMO_JUNIOR_ACCOUNTANT_EMAIL="junior@finovexa.ai"
DEMO_JUNIOR_ACCOUNTANT_PASSWORD="Junior1234!"
DEMO_CLIENT_NAME="Kabir Rao"
DEMO_CLIENT_EMAIL="client@finovexa.ai"
DEMO_CLIENT_PASSWORD="Client1234!"
```

No new secrets, API keys or credentials are required for the accounting module. Existing
LLM, SMTP/Twilio, PayPal and Upstox variables are untouched. Demo credentials are only
used by the seeder and are never rendered in the UI.

The Tally export centre adds no environment variables. Generated files are written to the
existing local storage directory and downloaded through authenticated backend endpoints.

## 3. Working features

### M1 — Homepage and public services
- Homepage "Professional Accounting Services" section listing all eight services with
  **Explore Services** and **Request a Consultation**.
- `/accounting` public page: service catalogue, engagement process (enquiry → quote →
  onboarding), pricing-enquiry form (business name, contact, business type, turnover
  range, GST status, services, monthly transactions, requirements).
- No prices are displayed or promised; the page states a senior accountant reviews and
  sends a custom quotation.
- Endpoint: `GET /accounting/services`, `POST /accounting/enquiries`.

### M2 — Logins and roles
- `/accountant/login` and `/client/login`, plus backend `/auth/accountant/login`,
  `/auth/customer/login`.
- Roles: senior accountant, junior accountant, customer (client), plus existing
  owner/employee/developer.
- Route guards redirect each role to its own shell; seniors are the only role allowed on
  reports, documents and audit pages (`SeniorOnly` guard at `frontend/src/App.tsx:296`).
  The Tally export centre is available to both accountant roles
  (`frontend/src/App.tsx:459`), with approval controls restricted to seniors.

### M3 — Senior dashboard
- `/accountant`: active clients, new enquiries, pending quotations, unassigned work, WIP,
  awaiting review, approved, deadlines, overdue, junior workload, plus FY/client/task/status
  filters driven by `GET /accounting/senior/overview`.

### M4 — Client management
- `/accountant/clients` (search/sort/filter) and `/accountant/clients/:clientId`.
- Detail page: business details, GSTIN, PAN last four only, business type, turnover,
  financial year, package, assigned accountant, documents, task/work history, invoices and
  payment status, assignment controls, uploads.
- **Business Manager link:** an engagement can be linked to a Business Manager business via
  `accounting_clients.business_profile_id`. The client list shows a "Linked" badge and the
  detail page names the linked business and states that its invoices/expenses are not
  auto-synced into the accounting books. The seeded demo business **DN Ventures Pvt. Ltd**
  is linked this way, assigned to the senior and junior accountants, with six seeded
  vouchers, three stock masters and one GST task so the practice screens and Tally export
  are populated. Existing databases pick this up idempotently on next boot without
  reseeding the other clients.
- Endpoints under `/accounting/senior/clients*`, plus `linked_business` on every client
  payload.

### M5 — Junior workspace
- `/accountant/work`: assigned clients/tasks, sales/purchase voucher entry, bill/invoice
  upload, expense categorisation, CSV/Excel import, reconciliation, report preparation and
  "submit for review".
- Juniors cannot approve reports or final submissions: review/deliver endpoints are
  senior-only and the UI hides those controls.
- Endpoints under `/accounting/junior/*`, `/accounting/vouchers*`, `/accounting/reports`.

### M6 — Assistants (human-verified)
- **Bill reader** (`POST /accounting/bills/extract`): PDF/image text extraction, suggested
  ledger, confidence + "needs review" flags; nothing is saved until the accountant confirms
  and posts the voucher.
- **Bank reconciliation assistant**: suggested matches, unmatched and duplicate flags;
  `POST /accounting/bank/transactions/{id}/match` requires explicit accountant confirmation.
- **GST preparation assistant** (`POST /accounting/gst/prepare`): GSTR-1/3B working papers
  with output tax, ITC, net payable, carry-forward, mismatches. Payload is marked
  `working_paper_only` with a filing note; no official filing is claimed.
- **Financial report assistant**: deterministic monthly summary / financial statement math
  from stored vouchers only. No invented figures and no automatic tax decisions.
- All page copy states these are assistants that require accountant verification.

### M7 — Tally Integration (Excel/CSV export)

- **Tally export centre** at `/accountant/tally` (nav item "Tally Integration", available to
  both accountant roles) with five tabs: Export centre, Approval queue (senior only),
  Export history, Stock masters, Tally import guide.
- **Data types covered:** sales, purchase, payment, receipt and expense vouchers, ledger
  masters and stock item masters. Only posted vouchers inside the chosen client/period are
  exported; a type with no rows is reported, not silently omitted.
- **File generation** (`backend/app/services/tally_export.py`):
  - Excel: one workbook with Instructions, Summary, one worksheet per voucher type,
    Voucher Entries, Ledger Masters, Stock Item Masters and Validation sheets.
  - CSV: a `.zip` containing one CSV per voucher type, `voucher-entries.csv`,
    `ledger-masters.csv`, `stock-item-masters.csv`, `validation-report.csv`, a README plus
    `tally-master-import.xml` and `tally-voucher-import.xml` for TallyPrime's native XML
    import route.
  - Every row carries date, voucher type, voucher number, ledger name, ledger group,
    debit/credit amount, taxable value, GST split, narration and party details. Stored
    figures are copied, never rounded into a different value.
- **Validation before export** (`POST /accounting/tally/exports/validate`, also enforced on
  prepare): mandatory voucher fields, ledger/group mapping, per-voucher and batch-wide
  debit-credit balance, GST recomputed from taxable value/rate and compared with stored
  values, duplicate voucher numbers inside and outside the period, party GSTIN format,
  purchases with GST but no supplier GSTIN, payment/receipt vouchers without a bank/cash
  ledger, and unusual GST slabs. Errors block the export; warnings are shown and recorded.
  Errors report expected vs stored values and the backend never edits accounting figures.
- **Approval workflow:** a prepared batch is written by a junior or senior accountant and
  saved as `pending_approval`; preparing a batch with blocking errors is refused with 422 so
  a broken file never reaches review. A senior approves or rejects with a note (rejection
  requires a note). The review UI disables approval while blocking errors are present.
  Self-approval is allowed but flagged as `self_approved` in the batch details and audit
  trail.
- **Secure download:** `GET /accounting/tally/exports/{id}/download` returns 403 until the
  batch is approved, resolves the client scope server-side and serves the stored file from a
  random disk name. Each download writes an audit entry containing the file SHA-256. Juniors
  only see clients assigned to them.
- **Export history:** client, period, format, record count, prepared by, approved by,
  export date, batch status, import status (`not_imported`, `imported`,
  `partially_imported`, `failed`), and error/warning counts with the full validation
  snapshot per batch.
- **Import status tracking:** `POST /accounting/tally/exports/{id}/import-status` is only
  accepted for approved batches; it records what the accountant observed in TallyPrime.
- **Stock item masters:** per-client SKU/name/unit/HSN/GST rate/opening quantity and rate,
  with a per-client unique SKU and an explicit "business-verified rates only" disclaimer in
  the UI. These masters feed the stock-master worksheet.
- **TallyPrime instructions:** the Guide tab states plainly that this is *not* a live Tally
  connection and that FINOVEXA does not update Tally by itself. It walks through approve →
  download → Import Data → Masters → Vouchers (or the Excel/CSV route with column mapping)
  → reconcile Summary/Validation → record the outcome.
- **Audit trail:** `accounting.tally_export_prepared`, `accounting.tally_export_approved`,
  `accounting.tally_export_rejected`, `accounting.tally_export_downloaded`,
  `accounting.tally_import_status` and `accounting.stock_item_created`/`updated` are written
  to the existing audit log.
- **Legacy batch table:** `accounting_tally_batches` still backs the earlier CSV/Excel
  import validation; the new approval-gated export is stored in `accounting_tally_exports`.

### M8 — Customer portal
- `/client`: engagement status, tasks/progress/deadlines, document uploads and pending
  document requests, approved/delivered reports, fee invoices and payment status,
  conversation with the practice, notifications with mark-read.
- Invoices state that online payment is not enabled in this portal.
- Quotations: the client can request a quotation, track its request status, view only
  quotations approved and sent by a senior accountant, download the PDF and accept or
  decline. Accepting records the decision only and never charges an amount.
- The pricing/quotation catalogue is documented in
  [`docs/PRICING_QUOTATIONS.md`](PRICING_QUOTATIONS.md).
- Endpoints under `/accounting/customer/*` and `/accounting/notifications/*`.

### M9 — Workflow
- Enquiry → quotation → customer acceptance → onboarding → task assignment → junior work →
  senior review → customer delivery.
- Task priority, due dates, comments, attachments, reassignment, status changes, review
  notes and `accounting.*` audit entries are all persisted.
- `/accountant/enquiries`, `/accountant/tasks`, `/accountant/reports`, `/accountant/audit`.

### M10 — Security
- JWT auth with role checks; every customer call resolves the client from the logged-in
  user, never from a request parameter.
- Junior client access is limited to assignments.
- Documents are stored under random names, scoped per client, downloadable only through
  authorised endpoints; SHA-256 dedupe per client.
- PAN is stored/displayed as last four characters only; GSTIN validated server-side.
- Password hashes (PBKDF2) and API keys are never returned or logged.
- Server-side validation and duplicate protection on vouchers and enquiries.
- Tally export files live outside the web root under random names, are scoped to the
  requesting accountant's clients and return 403 until a senior approves the batch.
  Downloads log the SHA-256; stock masters reject duplicate SKUs per client.
- Audit trail covers onboarding, assignment, task review, report review/delivery, document
  review and customer decisions.

### M11 — UI
- Uses the existing FINOVEXA design system (tokens, cards, tables, badges, modals,
  page skeletons, callouts) with a professional practice layout.
- Responsive sidebar/tables and status indicators; existing Business Manager, Market Intelligence,
  Tax Center and GST & Billing pages remain intact.

## 4. Pending integrations (not implemented, not claimed)

| Integration | Status |
| --- | --- |
| Official GSTN / GSTR filing | Not connected. Outputs are working papers only. |
| Live Tally synchronisation | Not implemented. FINOVEXA generates Excel/CSV/XML files that an accountant imports into TallyPrime manually; it never posts into Tally itself. |
| Automated Tally import confirmation | Not implemented. Import status is recorded by the accountant from what TallyPrime reported. |
| Online fee payment collection | Not enabled in the client portal. |
| Email/SMS notifications for accounting events | Not wired; notifications are in-app only. |
| e-Invoice/IRP, DSC signing | Not implemented. |

## 5. Test results

| Check | Result |
| --- | --- |
| Backend `pytest` (all) | 219 passed |
| Backend accounting suite (`tests/test_accounting.py`) | 11 passed |
| Backend pricing/quotation suite (`tests/test_pricing_quotations.py`) | 8 passed |
| Backend Tally export suite (`tests/test_tally_export.py`) | 8 passed |
| Frontend Vitest | 66 passed (12 files) |
| TypeScript `tsc --noEmit` | clean |
| Vite production build | success (`index-douxmW4Y.js`, lazy `AccountantQuotationsPage-Dte9oGoM.js`, `TallyIntegrationPage-CIkp5CRV.js`, `PricingPage-D5RAfPH9.js`) |
| Browser verification — owner demo | Business Manager dashboard intact |
| Browser verification — senior accountant | dashboard, enquiries, clients, tasks, work, quotation workspace (draft → benchmark → approve → send → PDF), Tally export centre, billing, reports, documents, audit |
| Browser verification — junior accountant | restricted nav; Tally page hides the approval queue; only assigned clients; `/accountant/audit` redirects to `/accountant`; quotation workspace, approval and PDF APIs return 403 |
| Browser verification — customer | overview, documents, reports, invoices, quotation request/view/PDF/accept with no-charge notice, messages, notifications; senior and cross-client PDF endpoints return 403 |
| Developer pricing API | real developer session lists the six tier prices, ITR and rules; 401 unauthenticated and 403 for senior; developer Pricing tab typechecked and built |

Tally export coverage includes: balanced-batch validation, blocking errors and warnings,
422 responses carrying the validation report, prepare → pending approval, senior
approval/rejection with notes, download blocked before approval, approved download
(SHA-256 recorded), import-status recording, stock-master create/update/deactivate,
duplicate SKU rejection, cross-client isolation for juniors, and audit entries for prepare,
approve, download and import status. The linked DN Ventures engagement is covered by a
catalog/validation test proving its six seeded vouchers export as a balanced batch.
Frontend tests cover the export builder, 422 error
surfacing (including warnings), approval gating, approval submission, approved-only
downloads and the "not a live Tally connection" guidance copy.

Backend accounting coverage includes service catalogue/enquiry, role boundaries, senior
overview/detail, quotation and onboarding, junior isolation and task review, document
permissions and cross-client isolation, GST working papers, bank reconciliation/Tally,
bill reader + dedupe, fee-payment math with customer portal, and audit trail.

The only browser console message observed is a pre-existing CSP notice about the inline
theme bootstrap script; it is unrelated to this module and does not affect functionality.

## 6. Running locally

```bash
# backend (from backend/)
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend dev (from frontend/)
npm run dev
```

The backend also serves the built frontend from `frontend/dist` when present.

Demo accounts:

| Role | Email | Password |
| --- | --- | --- |
| Senior accountant | `senior@finovexa.ai` | `Senior1234!` |
| Junior accountant | `junior@finovexa.ai` | `Junior1234!` |
| Customer (Meridian Traders) | `client@finovexa.ai` | `Client1234!` |
| Owner (existing demo) | `demo@finovexa.ai` | `Demo1234!` |

## 7. Deployment status

The accounting module is complete in the application and covered by the backend and
frontend test suites. The live Render service still serves an older demo build; it is
left untouched while the clean FINOVEXA production environment is prepared.

The clean deployment uses a fresh managed Postgres database, database-backed file
storage and environment-provisioned owner and accountant accounts. No demo business
records are created. See [`deploy/FREE_STACK.md`](FREE_STACK.md) for the runbook.

## 8. Business Manager integration — Phase 1

Phase 1 adds the shared data foundation and the explicit business↔engagement link.
It does **not** sync transactions or post vouchers yet; those are later phases and
are not claimed as working.

### Schema (additive only)

New tables, created by `Base.metadata.create_all()`:

| Table | Purpose |
| --- | --- |
| `accounting_business_transactions` | Per-client inbox copy of one Business Manager transaction, unique on `(client_id, source_type, source_id)` |
| `accounting_business_transaction_lines` | Line items for an inbox transaction |
| `accounting_entry_drafts` | Proposed double-entry voucher awaiting review, one per inbox transaction |
| `accounting_entry_draft_lines` | Debit/credit lines for a draft |
| `accounting_voucher_lines` | Debit/credit split for a posted voucher created by the integration |
| `accounting_ledger_mappings` | Client-scoped default ledgers by transaction type/category |
| `accounting_integration_runs` | Sync-run audit record |

Additive columns:

* `accounting_clients.integration_status` (`not_linked` by default), `integration_enabled_at`,
  `integration_last_synced_at`, `integration_settings` (JSON).
* `accounting_vouchers.source_transaction_id`, `entry_draft_id`, `source_hash`.

Existing Tally historical tables are untouched. On an existing database, engagements that
already had a `business_profile_id` are marked `linked` once; no transaction, draft or
voucher is created or recalculated by the upgrade.

### APIs

Senior accountant:

* `GET /api/accounting/senior/business-options` — businesses available to link.
* `GET /api/accounting/senior/clients/{id}/integration` — status, counts and last run.
* `POST /api/accounting/senior/clients/{id}/integration/link` — body
  `{"business_profile_id": 3}`.
* `POST /api/accounting/senior/clients/{id}/integration/unlink` — preserves all synced
  rows, drafts and posted vouchers.

Business owner (owner-only, read-only):

* `GET /api/integration/accounting`
* `GET /api/integration/accounting/transactions?status=&limit=&offset=`

Every link change writes an `accounting.integration_linked` or
`accounting.integration_unlinked` audit event. Juniors cannot link or unlink. An owner
can only ever read the engagement attached to their own business profile; no client id is
accepted from the owner routes.

### Encrypted backups

`backend/scripts/backup_db.py` creates AES-256-GCM encrypted SQLite snapshots with a
SHA-256 payload check and `PRAGMA integrity_check` before and after restore:

```bash
cd backend
.venv/bin/python scripts/backup_db.py keygen --key-file backups/backup.key
.venv/bin/python scripts/backup_db.py create --key-file backups/backup.key
.venv/bin/python scripts/backup_db.py verify --key-file backups/backup.key --input backups/finovexa-....db.enc
.venv/bin/python scripts/backup_db.py restore --key-file backups/backup.key \
  --input backups/finovexa-....db.enc --target /tmp/restored.db
```

Store the key outside the repository. The script refuses to overwrite an existing key or
restore target. Postgres deployments should use the provider's encrypted backups.

### Tests

`tests/test_accounting_integration.py` covers seeded link status, owner view, link,
duplicate-link rejection, junior/owner permission boundaries, owner transaction isolation
and preservation of synced rows after unlink. `tests/test_backup_restore.py` covers the
encrypted round trip, wrong key, tampering and overwrite refusal. Full backend suite:
**239 passed**. The additive upgrade was also applied to a copy of the existing demo
database and to the live local demo database with integrity `ok`; invoice and voucher
counts were unchanged.

### Not implemented yet

* Draft generation, ledger suggestion, review/approval and posting.
* Integration counters on the Business Dashboard and the Financial Data Review UI.
* Tally export of newly approved integration vouchers.

## 9. Transaction sync into the review inbox (Phase 2)

The sync copies the linked business's own source records into
`accounting_business_transactions`. It never edits an invoice, payment, expense,
draft or voucher. Only a senior accountant can trigger a sync; juniors and the business
owner can read the resulting inbox.

### Source mapping

| Source | `source_type` | `transaction_type` | Bookable when |
| --- | --- | --- | --- |
| Sales invoice | `invoice` | `sale` | status is not `draft` or `void`, total > 0 |
| Confirmed payment | `payment` | `receipt` | status is `confirmed`, amount ≠ 0 |
| Refund payment (`refund_of_payment_id` set) | `payment` | `refund` | status is `confirmed`, negative amount preserved |
| Expense | `expense` | `expense` | amount > 0 |

Invoice lines are copied with HSN/SAC, quantity, unit, rate, taxable value and GST
components. Payments, refunds and expenses carry no invented GST split: their taxable
value is the transaction amount and GST fields stay zero until an accountant reviews
them. Inventory movements are already represented on invoice lines, so they are not
double-counted as a separate source. Historical Tally imports stay in their own tables
and are never mixed into this inbox.

### Deduplication and change detection

* A unique constraint on `(client_id, source_type, source_id)` makes every sync
  idempotent; a second identical sync creates nothing.
* Each row stores a SHA-256 hash of the bookable source fields. Volatile fields such as
  invoice status, payment reconciliation status and `updated_at` are excluded, so
  marking an invoice paid or reconciling a payment does not invalidate accounting work.
* Source edits that change bookable fields update the inbox row and its lines:
  * before a draft exists, a still-bookable row returns to `pending`;
  * after a draft, pending review, approval or posting, the row becomes
    `needs_attention` with an explanation and the draft/voucher is left untouched;
  * an ignored row keeps its ignored status and receives a review note.
* Draft invoices and non-voided sources are skipped for new rows. An invoice that becomes
  `void` after it was synced is flagged `needs_attention` with an explanation.
* Voided invoices are excluded by default. `include_voided` in the engagement's
  `integration_settings` includes them as `needs_attention` rows only, never bookable.
* Original transaction dates are preserved and the Indian financial year is derived from
  that date (`2024-05-12` → `2024-25`), not from the sync date.

Each run inserts an `accounting_integration_runs` row with discovered, created, updated,
skipped and error counts plus source counts and skip reasons. A failing source record is
isolated in its own savepoint; other records still sync and the run is marked `partial`.
The engagement's `integration_last_synced_at` is updated when the run finishes.

### APIs

Senior accountant:

* `POST /api/accounting/senior/clients/{id}/integration/sync` — runs a sync and returns
  `{"integration": ..., "run": ...}`; writes `accounting.integration_synced`.
* `GET /api/accounting/senior/clients/{id}/integration/transactions` — filters
  `status`, `source_type`, `transaction_type`, `date_from`, `date_to`, `limit`, `offset`.
* `GET /api/accounting/senior/clients/{id}/integration/runs` — recent sync runs.

Junior accountant (read-only, assigned clients only):

* `GET /api/accounting/junior/clients/{id}/integration`
* `GET /api/accounting/junior/clients/{id}/integration/transactions`

Business owner (read-only, own engagement only):

* `GET /api/integration/accounting`
* `GET /api/integration/accounting/transactions` with the same filters; no client id is
  accepted.

Unlinked engagements return `409` from the sync endpoint. Juniors get `403` when they
attempt a sync or open an unassigned client. The owner routes remain read-only and never
expose integration settings.

### Live demo verification

On the local demo database DN Ventures produced 65 discovered sources (22 invoices,
12 payments, 31 expenses), 62 inbox rows and 3 skipped sources (1 void invoice, 1 failed
and 1 pending payment) with zero errors. A second sync created and updated nothing.
Invoice and accounting-voucher counts were unchanged, owner and assigned-junior views
returned the same 62 rows, and SQLite `integrity_check` returned `ok`.

### Tests

`tests/test_accounting_integration_sync.py` covers idempotent sync, dedupe, line and
financial-year preservation, source-change-after-draft protection, void handling, refund
semantics, senior/junior/owner RBAC, owner isolation and audit records. Full backend
suite: **244 passed**.

### Not implemented yet

* Draft generation, ledger suggestion, review/approval and posting of inbox rows.
* Statement/reconciliation views and the Financial Data Review and Business Dashboard UI.
* Tally export of newly approved integration vouchers.
* Detection of sources deleted at the business end, and scheduled/automatic syncs.

## 10. Draft vouchers and ledger suggestions (Phase 3)

Phase 3 turns eligible inbox rows into **balanced draft vouchers** for accountant review.
It never posts: no `AccountingVoucher` is created, no source business record is modified
and no GST rate or amount is recomputed.

### Suggestion logic

`app/services/accounting_drafts.py` builds a suggestion from, in order:

1. the client's active `AccountingLedgerMapping` for the transaction type and category
   (category match is case-insensitive; a blank-category mapping acts as the fallback);
2. the client's own latest vouchers (sales ledger, bank ledger, expense ledger by category);
3. documented defaults (`Sales`, `Accounts Receivable`, `Sundry Creditors`, `Cash`,
   `PayPal Clearing`, `Bank`, category hints such as `Office rent`).

Suggested entries:

| Source | Debit | Credit |
| --- | --- | --- |
| Sale | Party (receivable) at invoice total | Sales ledger at taxable value + `Output GST - CGST/SGST/IGST` copied from the invoice |
| Receipt | Bank/cash at amount received | Party |
| Refund | Party | Bank/cash |
| Expense | Mapped or category-hinted expense ledger | Mapped ledger, else vendor payable |

GST ledgers are suggestions only. Amounts come from the source invoice; the accountant
confirms the ledger names and tax treatment. Any line imbalance is closed with an explicit
`Rounding adjustment` line, and defaults that fall back to a generic ledger add
`warnings` to the suggestion so nothing is silently assumed.

### APIs

| Method | Path | Access |
| --- | --- | --- |
| POST | `/api/accounting/senior/clients/{id}/integration/drafts/generate` | Senior |
| GET | `/api/accounting/senior/clients/{id}/integration/drafts` | Senior |
| GET | `/api/accounting/senior/clients/{id}/integration/drafts/{draft_id}` | Senior |
| PATCH | `/api/accounting/senior/clients/{id}/integration/drafts/{draft_id}` | Senior |
| GET | `/api/accounting/senior/clients/{id}/integration/transactions/{txn_id}/suggestion` | Senior |
| GET/PUT | `/api/accounting/senior/clients/{id}/integration/ledger-mappings` | Senior |
| DELETE | `/api/accounting/senior/clients/{id}/integration/ledger-mappings/{mapping_id}` | Senior |
| GET | `/api/accounting/junior/clients/{id}/integration/drafts` and `/ledger-mappings` | Junior (assigned clients) |

Generation accepts an optional `transaction_ids` list (up to 200) or a `limit` of pending
rows. Explicitly requested rows are still skipped with a readable reason when a draft
already exists or the source is not `pending`. Each row is generated in its own savepoint,
so one bad transaction cannot abort the batch. Drafts are numbered
`DR-S|R|P|E|J-YYYYMM-NNN` per client and month. Generation writes
`accounting.entry_draft_generated` plus a batch audit event; edits write
`accounting.entry_draft_updated`; mapping changes write `accounting.ledger_mapping_saved`
or `accounting.ledger_mapping_removed`.

Editing is allowed only while a draft is in `draft` status. A PATCH may change the voucher
type, date (financial year is recalculated), party, narration and lines. Validation
requires at least two lines, exactly one side per line (debit or credit) and equal debit
and credit totals. Submitting, approving, rejecting and posting belong to Phase 4.

### Live demo verification

DN Ventures had 62 pending inbox rows (21 sales, 10 receipts, 31 expenses). Draft
generation created 62 drafts with zero skips and zero errors:

* all 62 had debit total = credit total, at least two lines and a positive value;
* inbox counts moved from 62 pending to 62 drafted; no `needs_attention` rows;
* accounting vouchers stayed at 6 and no voucher referenced an entry draft;
* invoices (22), payments (12) and expenses (31) were unchanged;
* SQLite `integrity_check` returned `ok`;
* an assigned junior listed all 62 drafts (read-only) while draft generation returned
  `403`, and the business owner got `403` on the senior draft list.

### Tests

`tests/test_accounting_drafts.py` covers sale/receipt/refund/expense suggestions, GST
split from the source, balanced generation, idempotency, no voucher creation, audit
events, mapping overrides and removal, unlinked-client `409`, draft editing validation,
senior/junior/owner RBAC, cross-client `404`, edit-after-submit `409`, and source changes
after a draft (inbox `needs_attention`, draft preserved). Full backend suite:
**249 passed**.

### Not implemented yet

* Trial balance, P&L and balance sheet built from approved integration entries.
* Statement import and reconciliation matching.
* Integration UI in the Business Dashboard and the Accountant Portal review screen.
* Tally export of newly approved integration vouchers.

## 11. Review, approval and posting (Phase 4)

Phase 4 completes the draft lifecycle. A draft now moves through
`draft -> pending_review -> approved -> posted`, with `rejected` available from
review. Only an approved draft can create a posted voucher, and the approved
lines are copied verbatim.

### Lifecycle

| Transition | Endpoint | Rules |
| --- | --- | --- |
| Submit | `POST .../drafts/{id}/submit` | From `draft` or `rejected`; requires balanced lines and a positive total |
| Approve | `POST .../drafts/{id}/approve` | From `pending_review`; optional note; records reviewer and time |
| Reject | `POST .../drafts/{id}/reject` | From `pending_review`; a reason is required (`422` without one) |
| Post | `POST .../drafts/{id}/post` | From `approved`; creates one posted voucher and its lines |
| Re-edit | `PATCH .../drafts/{id}` | Allowed in `draft` and `rejected`; editing a rejected draft returns it to `draft` |

All four actions are senior-only. Juniors keep read-only access to assigned clients
and see the review state plus the posted voucher. The business owner has no access to
these routes. Junior and owner attempts return `403`; another client's draft returns
`404` for a senior and `403` for an unassigned junior.

Self-approval is allowed because the practice has a single senior seat in the demo, but
the approval audit event records `self_approved: true` when the preparer and reviewer are
the same user.

### Stale source protection

`sync` marks an inbox row `needs_attention` when the business source changes after a draft
exists. Approval and posting both compare the draft's generation hash with the current
inbox hash. A mismatch returns `409` until the reviewer retries with
`{"acknowledge_source_change": true}`. Acknowledging re-baselines the draft hash and is
recorded in the approval or posting audit event; draft lines are never silently replaced.

### Posting

`app/services/accounting_posting.py` derives the voucher header from the approved lines:

* `total_amount` equals the draft debit total; line debits and credits are copied exactly;
* GST amounts come from `CGST`, `SGST` and `IGST` ledger lines, and the rate is computed
  from those amounts (never re-derived from a rate);
* a ledger that looks like GST but is not marked CGST/SGST/IGST returns `422` instead of
  being guessed;
* the primary ledger is the sales/expense ledger for trading vouchers and the bank/cash
  ledger for receipts and payments; a detected bank or cash line is stored in
  `bank_ledger`;
* the voucher stores `source="integration"`, `source_transaction_id`, `entry_draft_id`
  and `source_hash`; historical Tally imports never populate these columns;
* the draft becomes `posted`, the inbox row becomes `posted`, and a second post attempt
  returns `409` with the existing voucher number.

Posting writes one audit event, `accounting.entry_draft_posted`, on the voucher with the
draft id, amounts and acknowledgement flag. Submit, approve and reject write
`accounting.entry_draft_submitted`, `accounting.entry_draft_approved` and
`accounting.entry_draft_rejected` on the draft.

Draft reads now include `submitted_at`, `reviewed_at`, `reviewed_by_user_id`,
`review_note` and, once posted, the full `voucher` object with its lines. Draft lists
include `voucher_id` for posted rows.

### Live demo verification

The demo database held 62 drafts. One sale was submitted, approved and posted as voucher
`DR-S-202611-002` (id 13) for INR 86,500; one sale was left approved; one expense was left
pending review; one expense was rejected with a reason and re-edited back to draft. Final
state: 59 draft, 1 pending review, 1 approved, 1 posted; inbox 61 drafted and 1 posted.

The posted voucher balanced at 86,500 on both sides, its header reconciled
(`taxable + GST = total`), client vouchers moved from 6 to 7 with exactly one
`source="integration"` voucher, invoices (22), payments (12) and expenses (31) were
unchanged, a second post returned `409`, the assigned junior could read the posted draft
and voucher, and SQLite `integrity_check` returned `ok`.

### Tests

`tests/test_accounting_posting.py` covers the full sale lifecycle, voucher and line
fidelity, balanced headers, source-record immutability, audit actions, junior read access,
double-post and wrong-state guards, rejection with mandatory reason, re-edit reopening,
source-change acknowledgement at both approval and posting, GST ledger classification
failure and successful CGST posting, and senior/junior/owner/cross-client permissions.
Full backend suite: **254 passed**.

### Not implemented yet

* Trial balance, P&L and balance sheet built from approved and posted integration entries.
* Statement import and reconciliation matching.
* A dedicated draft review screen in the Accountant Portal (drafts are posting through the API; the client workspace shows their status).
* Posting batches and reversal/correction vouchers.
* Notification of the business owner when entries are posted.

## 12. Business data workspace (accountant view)

The accountant client workspace now has a **Business data** tab for engagements linked to a
Business Manager business. It shows the owner's dashboard figures and full transaction
history, read-only, next to the Tally reporting position.

### What it shows

* Six KPI cards for the last 30 days: revenue with invoice count, operating expenses with
  cash received, net profit with margin, receivables outstanding with overdue amount and
  invoices, recorded cash with reserve, and inventory value with low-stock count.
* Business card: GSTIN, city/state, integration status and last sync, source record counts
  (invoices, payments, expenses) and accounting badges (awaiting review, drafts, awaiting
  approval, posted, needs attention).
* Tally card: posted accounting vouchers, integration-sourced vouchers, export batches, last
  export status and date, plus a **Prepare a Tally export** link that opens
  `/accountant/tally?clientId={id}` with that client already selected.
* Transaction history: every sale (invoice), receipt, refund (negative payment) and expense,
  with reference, party, taxable value, GST, total, source status and accounting state
  (`Not synced`, inbox status, `draft · number`, or `Posted · voucher`). Filters cover type,
  text search, and an inclusive `from`/`to` date range; the list paginates 25 rows at a time
  and shows per-type totals and a net total.
* Senior-only **Sync business records** button, which runs the existing sync and reloads.

### Guarantees

* The view reads the owner's live source tables, so records appear before a sync. It never
  writes owner records, vouchers or drafts.
* Accounting state is attached from the integration inbox, entry drafts and posted vouchers;
  a record is only marked posted when an approved draft produced a voucher.
* Only posted vouchers reach Tally, and the Tally export query already includes
  integration-posted vouchers (`accounting_vouchers.status == "posted"`).
* Juniors see the same view for assigned clients only (`ensure_client_access`); owners and
  customers get `403`; an unlinked engagement returns `linked: false` with empty history.

### APIs

| Method | Path | Access |
| --- | --- | --- |
| GET | `/api/accounting/senior/clients/{id}/business/summary?days=1..365` | Senior |
| GET | `/api/accounting/senior/clients/{id}/business/transactions?transaction_type=&search=&date_from=&date_to=&limit=1..200&offset=` | Senior |
| GET | `/api/accounting/junior/clients/{id}/business/summary` | Junior (assigned clients) |
| GET | `/api/accounting/junior/clients/{id}/business/transactions` | Junior (assigned clients) |

### Frontend

`ClientBusinessPanel` is mounted as the **Business data** tab in
`AccountantClientDetailPage.tsx`. Types live in `frontend/src/lib/accountingTypes.ts`. The
Tally page accepts `?clientId=` and validates it against the loaded client list before use.

### Tests

`tests/test_accounting_business_view.py` covers summary/history parity with the owner's own
records, read-only behaviour, filters, search, paging, status transitions after
sync → draft → post, and senior/junior/owner/customer/unlinked permissions.

Verification on 2026-11-02: backend **258 passed**, frontend **66 passed**, TypeScript and
Vite production build succeeded, and the tab was exercised in the browser on DN Ventures
(KPIs, integration badges, 65 history rows, expense filter → 31 rows, Tally link with the
client preselected).

### Not implemented yet

* Trial balance, P&L and balance sheet from posted integration vouchers.
* An inline review/approve screen inside the workspace (posting continues through the
  existing API endpoints).
* Statements, reconciliation matching and owner notifications.

## 13. Payment Connect (Task 002) — direct payment history and reconciliation

Payment Connect is a separate owner and accountant surface for payment-provider history.
It reuses the shared data layer: provider transactions are stored in
`payment_connections`, `payment_transactions`, `payment_sync_runs` and
`payment_reconciliation_events`; accountants import statements into the existing
`accounting_bank_imports` / `accounting_bank_transactions` tables and approved payments
link to accounting drafts and vouchers. No owner invoice, voucher or historical Tally
record is rewritten.

### Routes

| Route | Role | Purpose |
| --- | --- | --- |
| `/payment-connect` | Owner | Business-wide connections, transactions, Google Pay and reconciliation queue |
| `/accountant/payment-connect` | Senior and junior accountant | Client-scoped connections, transactions, statement import, Google Pay and reconciliation queue |

The accountant route is intentionally not senior-only: juniors can read, inspect
candidates and audit events, preview and import statements, and suggest, reject, mark
not applicable or reset. Only a senior accountant can connect/disconnect providers,
run provider syncs, track Google Pay references and approve a match.

### Providers and honest limits

* **PayPal** — official OAuth + `GET /v1/reporting/transactions` (Transaction Search),
  31-day search windows, paginated and capped, external transaction IDs stored, refunds,
  fee, net amount and provider statuses preserved, every run recorded in `payment_sync_runs`.
  Searches only the merchant that owns the backend credentials. Reading another merchant's
  history requires PayPal partner-network approval and is not assumed.
* **Google Pay** — no official public API lists every consumer Google Pay transaction.
  `/google-pay/eligibility` reports that state; `/google-pay/lookup` always returns an honest
  `409` instead of inventing an endpoint. `/google-pay/track` records a merchant-entered
  reference as `manual_entry_not_provider_verified`. No Google password, UPI PIN, OTP, app
  scraping or notification scraping is used.
* **Bank statements** — accountant-only CSV/XLSX/XLS/TXT and machine-readable PDF fallback.
  Rows are previewed and editable before import, parser confidence and issues are shown,
  duplicates are detected and skipped, the original file is stored encrypted, and imported
  rows start `unverified`. Scanned images are rejected rather than OCR'd.

### Reconciliation

Suggestions are deterministic: exact amount/reference matching with date tolerance and
partial-payment support. A suggestion never approves itself. The review modal shows
candidates, the open-invoice picker, match score/reason and the audit event trail.
Approval is senior-only and only for a `completed` transaction; incoming payments need an
invoice, refunds/chargebacks/reversals create a negative payment, and the amount cannot
exceed the invoice's outstanding balance. Linked engagements also receive accounting
drafts; nothing is auto-posted or auto-filed.

### APIs

Owner routes are under `/api/payment-connect` (owner only). Accountant routes are under
`/api/accounting/payment-connect` with a `client_id` query parameter on GET routes or
`client_id` in the body on write routes.

| Method | Path | Access |
| --- | --- | --- |
| GET | `/overview` | Owner or accountant (client scope) |
| GET | `/transactions?date_from=&date_to=&provider=&direction=&status=&reconciliation_status=&outlet_label=&search=&amount_min=&amount_max=&include_duplicates=&limit=&offset=` | Owner or accountant |
| GET | `/transactions/{id}/events`, `/transactions/{id}/candidates` | Owner or accountant |
| POST | `/transactions/{id}/reconcile` | Owner, or senior accountant for `approve`; juniors may suggest/reject/not_applicable/reset |
| POST | `/connections` | Owner or senior accountant |
| POST | `/connections/{id}/disconnect`, `/connections/{id}/sync` | Owner or senior accountant |
| GET | `/connections/{id}/runs` | Owner or accountant |
| GET | `/google-pay/eligibility` | Owner or accountant |
| POST | `/google-pay/lookup` | Owner or accountant (honest 409) |
| POST | `/google-pay/track` | Owner or senior accountant |
| POST | `/bank-statements/preview`, `/bank-statements/import` | Accountant only |
| GET | `/bank-statements?client_id=` | Accountant only |

### Environment

No new secrets. PayPal sync uses the existing backend-only credentials:

```
PAYPAL_ENVIRONMENT=sandbox            # or live
PAYPAL_SANDBOX_CLIENT_ID=
PAYPAL_SANDBOX_CLIENT_SECRET=
PAYPAL_LIVE_CLIENT_ID=
PAYPAL_LIVE_CLIENT_SECRET=
```

The UI never receives or requests these values; it only shows non-secret connection state.
Google Pay needs no credentials because this deployment has no official merchant API
configured, and statements need none.

### Tests

`backend/tests/test_payment_connect.py` — 13 passed: PayPal success, failed/pending,
refund, Google Pay eligibility and honest lookup, unsupported permission handling, CSV
import, duplicate statement skip, PDF uncertainty, invoice matching, partial payments,
cross-business isolation and repeated idempotent sync. Full backend suite **271 passed**;
frontend Vitest **66 passed**; TypeScript and Vite production build clean.

Browser verification on 2026-11-02: senior accountant overview, connect modal (PayPal and
Google Pay variants), Google Pay eligibility with the honest lookup response, CSV statement
preview (4 rows, all valid, editable amounts), unified transaction filters with empty state,
and the owner `/payment-connect` surface.

### Not implemented

* PayPal partner-network onboarding for third-party merchant history.
* Any Google Pay transaction-history or lookup API (not offered publicly).
* OCR of scanned statements or payment screenshots.
* Automatic approval, automatic accounting posting or automatic GST/ITR filing.
