# Tally Historical Data Import & Export — Implementation Report

Additive module on the existing FINOVEXA accountant portal. No existing accounting,
authentication, payroll, GST, pricing or market-research feature was rebuilt or replaced.

**Migration is file-based only.** FINOVEXA never connects to a Tally installation and never
stores Tally, bank or payment passwords. There is no direct Tally synchronisation claim
anywhere in the UI or API.

---

## 1. What was built

| Area | Implementation |
| --- | --- |
| Workspace | `frontend/src/pages/accounting/TallyMigrationPage.tsx` — six tabs: Import wizard, Historical reports, Opening balances, Approvals, History, Mapping templates |
| Import service | `backend/app/services/tally_migration.py` — parsing, mapping, normalisation, validation, duplicate detection, posting, rollback, opening balances |
| Report service | `backend/app/services/tally_history.py` — trial balance, P&L, balance sheet, sales/purchase/expense history, outstanding, GST working summary, monthly and FY comparison |
| API | `backend/app/routers/tally_migration.py` — 20 endpoints under `/api/accounting/tally-migration` |
| Reverse export | Existing Tally Integration module (`/api/accounting/tally/exports`) with version-specific Excel, CSV, Tally XML and JSON output |
| Tests | `backend/tests/test_tally_migration.py`, `backend/tests/test_tally_export.py` |

### Data model (created additively at startup)

| Table | Purpose |
| --- | --- |
| `accounting_tally_migrations` | Import/export batch header: client, FY, period, import type, format, file name and size, SHA-256, counts, status, prepared/approved users, retention date |
| `accounting_tally_migration_rows` | Parsed source rows with per-row status, problems, JSON data and voucher lines |
| `accounting_tally_mapping_templates` | Reusable per-client/per-format column mappings |
| `accounting_historical_ledgers` | Imported ledger masters, isolated per client and FY |
| `accounting_historical_vouchers` | Approved imported vouchers, isolated from the live `accounting_vouchers` ledger |
| `accounting_historical_voucher_lines` | Debit/credit lines for each historical voucher |
| `accounting_opening_balances` | Approved opening balance batches with effective date and totals |
| `accounting_opening_balance_lines` | Ledger, party, stock quantity/value opening lines |

No existing table is dropped, truncated or rewritten. `Base.metadata.create_all()` plus the
existing additive `ensure_schema_upgrades()` create the new tables on next boot.

---

## 2. Supported formats and Tally versions

| Tally version | Excel `.xlsx` | Excel `.xls` | CSV | Tally XML | JSON |
| --- | --- | --- | --- | --- | --- |
| TallyPrime 5.0 | Yes | Yes | Yes | Yes | Yes |
| TallyPrime 4.1 | Yes | Yes | Yes | Yes | Yes |
| TallyPrime 3.0 | Yes | Yes | Yes | Yes | Yes |
| TallyPrime 2.0 | Yes | Yes | Yes | Yes | No |
| Tally ERP 9 | Yes | Yes | Yes | Yes | No |

JSON is deliberately restricted to TallyPrime 3.0 and later. The UI and API both enforce the
matrix from `TALLY_VERSION_FORMATS`; an unsupported combination is rejected rather than
silently accepted.

Other limits:

- Upload size: 10 MB per file (`ACCOUNTING_MAX_UPLOAD_MB`).
- Records per import: 20,000 (`MAX_IMPORT_RECORDS`).
- Signature checks: OOXML (`PK`), legacy XLS (OLE2), XML (`<`), JSON (`{`/`[`).
- Import types: ledger masters, groups, stock item masters, sales, purchase, payment,
  receipt, journal, debit/credit notes, historical balances, complete historical data and
  opening balances.

### Column mapping

28 FINOVEXA fields can be mapped from any source heading, including voucher type/number/date,
party and GSTIN, ledger and group, debit/credit/amount/Dr-Cr indicator, taxable value, GST
rate, CGST/SGST/IGST, narration, invoice reference, stock item, quantity, unit, rate,
HSN/SAC, SKU, opening balance, parent group, financial year and record type.

- Headings are matched case-insensitively with spaces/underscores normalised.
- Unmapped fields remain empty; mapped financial values are never inferred or rounded.
- Mappings can be saved as reusable templates per client, format and import type.

---

## 3. Workflow and roles

```
Upload → Parse & preview → Map columns → Validate & stage (Validated)
      → Submit for approval (Pending Approval)
      → Senior decision → Approve & post (Imported / Partially Imported)
                       → Reject with reason (Rejected)
      → Senior rollback (Rolled Back)
```

| Role | Allowed |
| --- | --- |
| Junior accountant | Upload, map, validate, correct the source file, submit batches, view permitted clients |
| Senior accountant | Everything a junior can do, plus approve/reject, post history, roll back, enter manual opening balances |
| Client | No access to migration batches |
| Other staff | Scoped by existing `ensure_client_access` / `staff_client_filter`; cross-client IDs return 403/404 |

Only a senior decision writes historical vouchers. Approval writes to historical tables only;
the live FINOVEXA ledger (`accounting_vouchers`) is untouched, and the Reports page labels it
separately as "Newly recorded FINOVEXA transactions (not included in imported history)".

---

## 4. Validation (before anything is posted)

Every batch is validated without altering any financial value:

- Duplicate vouchers: SHA-256 fingerprint of `client + voucher type + number + date + total`.
  Duplicates are skipped and reported, never overwritten.
- Missing ledgers: created under `Suspense Account` for review, listed explicitly.
- Invalid or missing dates, missing voucher numbers, incomplete records.
- Debit/credit totals per voucher and across the batch, with the difference shown.
- Financial-year consistency: every voucher date must fall in the selected FY.
- Unmatched parties against imported/live ledger masters.
- GST rate and GSTIN format checks.
- Opening balance debit/credit equality and inventory value totals.

Results expose detected / valid / warning / error / duplicate counts, per-check statuses,
per-row problems, mapped Dr/Cr/difference totals, missing ledgers and unmatched parties.
Errors block submission; warnings do not. The error report is downloadable as CSV at any time,
including after approval or rollback.

**Nothing is silently discarded:** invalid rows stay in the batch with their problem codes,
duplicates remain visible, and posted values are exactly the values supplied by the file.

---

## 5. Historical reports

Computed only from approved imports (and approved opening balances where relevant):

- Prior-year profit & loss and balance sheet.
- Trial balance with opening, movement and closing Dr/Cr; difference shown.
- Sales, purchase, expense, credit-note and debit-note history with monthly breakdown.
- Customer and supplier outstanding from closing debtor/creditor balances.
- Ledger-wise drill-down with source vouchers.
- GST working summary (output tax, input tax, credit/debit notes, net payable).
- Monthly revenue, purchases, expenses and profit.
- Multi-year comparison (vouchers, revenue, expenses, net profit, GST).

Monthly figures use the taxable value when present (falling back to the gross voucher amount),
so monthly revenue agrees with the P&L. GST amounts are read from mapped GST columns, or
inferred from separate CGST/SGST/IGST ledger lines commonly present in Tally exports.

---

## 6. Opening balances and double-count protection

Opening balances can be entered manually by a senior or imported as a validated batch:

- Selected opening date and financial year.
- Ledger lines, customer/supplier outstanding, and stock quantity/value.
- Batch must balance Dr = Cr and inventory totals are validated.
- Senior approval is required before posting.

Guards prevent duplicate activity:

- Manual opening entry is rejected if posted historical vouchers already exist for that FY.
- A full-history or historical-balances import is rejected if an approved opening balance
  already exists for that FY.
- A second opening balance for the same client/FY is rejected; nothing is overwritten.
- The UI explains each conflict instead of auto-resolving it.

---

## 7. Reverse export (Tally-compatible)

Implemented in the existing Tally Integration workspace:

- Ledger masters, vouchers (sales, purchase, payment, receipt, journal) and stock masters.
- Formats: Excel `.xlsx`, CSV, Tally-compatible XML and JSON (JSON on TallyPrime 3.0+ only).
- Version templates follow the same `TALLY_VERSION_FORMATS` matrix.
- Exports require senior approval before download; each export stores validation snapshot,
  file hash, approver and Tally import status.
- Files are for manual import into Tally. FINOVEXA does not push data into Tally.

---

## 8. Audit trail and retention

- Every preview, stage, submit, approve, reject, rollback, error-report download, source
  download, mapping change, opening balance approval and export decision writes to the
  practice audit trail with user, client, entity, ID and metadata.
- History tab shows client, FY, file name/format, import date, prepared by, approved by,
  row counts and status for every batch, plus export history.
- Original source files are retained on disk with SHA-256 for
  `ACCOUNTING_TALLY_RETENTION_DAYS` (default 2555 days / 7 years) and can be re-downloaded by
  authorised staff.
- Every upload stores the source SHA-256, so the exact file behind each batch can be verified
  and re-downloaded.

---

## 9. API surface

Base: `/api/accounting/tally-migration` (JWT required; client access enforced per call).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/catalog` | Formats, versions, import types, mapping fields, limits |
| POST | `/preview` | Parse a data-URL file; return headers, sample, suggested mapping |
| GET/POST | `/mappings` | List / create mapping templates |
| PATCH/DELETE | `/mappings/{id}` | Update / delete a template |
| POST/GET | `/batches` | Upload+validate / list batches |
| GET | `/batches/{id}` | Batch detail with rows and validation |
| POST | `/batches/{id}/revalidate` | Re-run validation after a source correction |
| POST | `/batches/{id}/submit` | Submit for senior approval |
| POST | `/batches/{id}/decision` | Approve (post) or reject with reason — senior only |
| POST | `/batches/{id}/rollback` | Remove only rows created by this batch — senior only |
| GET | `/batches/{id}/error-report` | Download validation CSV |
| GET | `/batches/{id}/source` | Download the retained original file |
| GET/POST | `/opening-balances` | List / senior manual opening balance |
| GET | `/years` | Available historical years for a client |
| GET | `/reports` | Full historical report bundle |
| GET | `/reports/ledger` | Ledger drill-down |
| GET | `/reports/compare` | Multi-FY comparison |

Reverse export endpoints remain under `/api/accounting/tally/exports`.

---

## 10. Tests completed

### Automated (all passing)

- **Backend full suite:** `231 passed` (`backend/.venv/bin/python -m pytest -q`, ~190 s).
- **Tally migration suite:** `11 passed`.
  - Catalog, preview and suggested mapping.
  - Sales import → approval → historical vouchers with taxable 10,000, CGST 900, SGST 900.
  - Live ledger untouched; GST output 1,800; net payable 1,800; monthly revenue 10,000.
  - Unbalanced and out-of-year rows block submission.
  - Opening-balance import, Dr/Cr balance check and double-count guards.
  - Client isolation (customer role denied).
  - Mapping template create/update/delete round trip.
  - XML sign conversion, JSON row parsing, XLSX import.
  - Seeded historical reports and multi-year comparison.
- **Tally export suite:** `9 passed` — statuses, senior approval before download, CSV bundle
  content, Tally XML, JSON and version rules, duplicate/GSTIN/GST-mismatch validation,
  stock masters, client isolation, linked-business export, rejection and import-status guard.
- **Frontend:** `tsc --noEmit` clean; Vitest `66 passed` across 12 files; Vite production
  build succeeded (`TallyMigrationPage-Cz6Ai5Me.js`, 55.79 kB).

### Manual browser verification (senior account, local dev)

- Historical reports, ledger drill-down, opening balances, seeded history list and batch detail.
- Full CSV wizard: upload → preview → 28-field mapping → validate/stage → submit →
  review modal → approve & post.
- Post-import reports: P&L, balanced balance sheet and trial balance, outstanding, GST summary,
  monthly table and FY comparison for DN Ventures.
- Rollback from History: confirmation dialog, status `rolled_back`, imported count 0, and
  reports returned to zero — live vouchers unaffected.
- Mapping template create (9 fields, DN Ventures / CSV / Sales) and delete.
- Re-import of a GST-bearing CSV after fixes: Output CGST 900 / SGST 900, net payable 1,800,
  monthly revenue 10,000 matching P&L.

### Issues found and fixed during testing

1. **GST summary read ₹0 for exports that book tax as separate ledger lines.** Added
   `_infer_gst_from_lines()` so CGST/SGST/IGST ledger lines populate the voucher's GST fields
   when no GST amount columns are mapped. Covered by backend assertions.
2. **Monthly revenue was gross of GST (₹11,800) while P&L revenue was taxable (₹10,000).**
   Monthly figures now use taxable value when present, falling back to the gross amount.
3. **Batch validation UI crashed when an old batch lacked optional arrays.** Validation fields
   are optional in TypeScript and every collection is defaulted in the component.
4. **Format labels rendered as "Xml"/"xlsx".** Added explicit labels: CSV, Tally XML,
   Excel (.xlsx), Excel (.xls), JSON.

Both demo imports used the DN Ventures demo company and were rolled back; no client data was
modified.

---

## 11. Known limitations

- **File-based only.** No Tally ODBC/XML gateway, no scheduled sync, no automatic push into
  Tally; exports are for manual Tally import.
- **JSON is TallyPrime 3.0+ only.** Tally ERP 9 and TallyPrime 2.0 receive Excel/CSV/XML.
- **XML shape coverage.** Standard Tally `<ENVELOPE>/<TALLYMESSAGE>` voucher and master exports
  are supported; heavily customised TDL output may need column remapping or conversion to CSV.
- **Duplicate fingerprint is conservative.** Same company + type + number + date + total is a
  duplicate. A corrected voucher reissued with a different total is treated as a new record;
  originals are never overwritten, so staff must roll back the batch to replace it.
- **20,000 rows / 10 MB per import.** Larger histories must be split by year or type.
- **GST summary is a working paper,** not a GSTR-1/GSTR-3B filing; filing remains a separate
  reviewed process.
- **Balance-sheet classification depends on ledger groups.** Unknown or missing groups fall to
  `Suspense Account` and are surfaced for review.
- **Single currency.** Multi-currency Tally exports are treated as INR values exactly as
  supplied; no FX conversion is performed.
- **Historical data stays separate from live data.** Cross-ledger merging is intentionally not
  automatic; reporting shows imported and live activity side by side.
- **SQLite demo database.** Suitable for hackathon evaluation, not concurrent production use.
- **No Tally or bank credentials are stored,** by design.

---

## 12. Demo notes

- Accounts: `senior@finovexa.ai / Senior1234!`, `junior@finovexa.ai / Junior1234!`.
- Demo clients: DN Ventures Pvt. Ltd, Meridian Traders, Sunrise Interiors.
- A sample sales CSV with separate GST ledger lines can be used to demonstrate tax inference.
- Re-deploying the free hosted instance resets its SQLite database, including imported
  migration history; export or re-import after a reset.
