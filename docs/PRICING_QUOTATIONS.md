# Pricing & Quotation Management

Additive module on top of the existing FINOVEXA accounting stack. It does not replace the
Business Manager, GST & Billing, tax, market-research or employee features.

## 1. Default prices (database-configured)

All values live in the database and are editable from **Developer console → Pricing**
(`/developer`). Seeded defaults:

### Software subscription (FINOVEXA AI / Business Manager)

| Annual turnover (INR) | Monthly | Annual (no discount) |
| --- | --- | --- |
| Up to ₹8 lakh | ₹300 | ₹3,600 |
| Above ₹8 lakh–₹15 lakh | ₹500 | ₹6,000 |
| Above ₹15 lakh–₹30 lakh | ₹800 | ₹9,600 |
| Above ₹30 lakh–₹50 lakh | ₹1,500 | ₹18,000 |
| Above ₹50 lakh–₹1 crore | ₹2,500 | ₹30,000 |
| Above ₹1 crore | ₹4,000 | ₹48,000 |

Annual billing exists as an option, but no discount is applied unless the developer sets
`annual_discount_percent` above `0`. The public pricing page and estimator read the same
configured value and never invent a discount.

### ITR filing (separate paid service)

| Return | Price |
| --- | --- |
| Basic ITR-1 | ₹999 |
| Standard ITR-2 / ITR-4 | ₹1,999 |
| Business ITR-3 | ₹3,999 |
| Complex business ITR | ₹5,000 – ₹12,000+, subject to quotation |

ITR is never included automatically with an accounting engagement or a software
subscription. The client must select `itr_filing` in a quotation request.

### Accounting quotation rules

- Indicative benchmark: **2% of annual turnover**, calculated server-side. It is displayed
  as an indicative benchmark only and is never a final or accepted fee.
- Final fees are set line by line by a senior accountant, who must approve before sending.
- Default validity: 15 days; default tax disclosure: 18% GST shown separately.
- Additional charges (for example payroll per employee or one-time cleanup) are add-on
  records; a blank amount means “quoted after review”.

## 2. Calculation rules

Server-side (`backend/app/services/pricing.py`, `backend/app/routers/accounting.py`):

- `subtotal_annual` = sum of annual line items + one-time line items.
- Discount is `none`, an approved `percent`, or an approved `amount` capped at subtotal.
- `total_annual` = subtotal − discount.
- `monthly_equivalent` = total annual ÷ 12.
- Amount per billing period = total annual ÷ 12 (monthly), ÷ 4 (quarterly), ÷ 1 (annual),
  ÷ 1 (one time).
- The client never sends totals; it sends line items, discount inputs, frequency, validity
  and terms. The server recalculates and stores the totals.
- Quotation totals are independent of the software annual discount. Taxes are disclosed,
  not folded into the fee.

Status is computed server-side:

```
draft → approved → sent → accepted | declined
draft/approved → rejected
sent + valid_until < today → expired (virtual state)
```

Editing an approved quotation via `PATCH` clears approval and returns it to `draft`.
Sending requires `approved`. Rejection requires a note. A customer decision is accepted only
when the quotation is `sent` and not expired.

## 3. Permissions

| Action | Developer | Senior | Junior | Customer |
| --- | --- | --- | --- | --- |
| Edit software/ITR/add-on/rules prices | Yes | No | No | No |
| View price history / audit | Yes | No | No | No |
| View quotation workspace | No | Yes | No | No |
| Create/edit/approve/send/reject quotation | No | Yes | No (403) | No |
| View request details | No | Yes | No | Own email / linked client only |
| Request a quotation | No | No | No | Yes |
| View quotation | No | Yes | No | Sent/accepted/declined only, own only |
| Download quotation PDF | No | Yes | No | Sent/accepted/declined/expired, own only |
| Accept/decline | No | Record decision on behalf | No | Own sent quotation only |

Every customer call resolves the customer from the JWT; a quotation must belong to an
enquiry addressed to that email or to the customer's linked client. A stranger receives
403, unapproved drafts are invisible (403 on PDF), and junior accountant sessions receive
403 on the workspace, PDF and approval endpoints.

## 4. API

Public (no auth):

- `GET /api/accounting/public/pricing` — software tiers, ITR, add-ons, rules, disclosures.
- `GET /api/accounting/public/quotation-estimate?annual_turnover=...` — indicative benchmark.
- `POST /api/accounting/public/enquiries` — website quotation request.

Senior:

- `GET /api/accounting/senior/quotation-workspace?status=&search=`
- `POST/PATCH /api/accounting/senior/quotations[/{id}]`
- `POST /api/accounting/senior/quotations/{id}/approve | send | reject | decision`
- `GET /api/accounting/senior/quotations/{id}/pdf`

Customer:

- `GET/POST /api/accounting/customer/quotation-requests`
- `GET /api/accounting/customer/quotations`
- `GET /api/accounting/customer/quotations/{id}/pdf`
- `POST /api/accounting/customer/quotations/{id}/decision`

Developer:

- `GET /api/developer/pricing`
- `PUT /api/developer/pricing/rules`
- `PUT /api/developer/pricing/software/{tier_id}`
- `PUT /api/developer/pricing/itr/{price_id}`
- `POST/PATCH /api/developer/pricing/addons[/{id}]`
- `GET /api/developer/pricing/history`

## 5. PDF

`backend/app/services/quotation_pdf.py` (reportlab) renders the quotation number, client
details, scope lines with amounts, subtotal, approved discount, final annual fee, monthly
equivalent, payment frequency, validity, terms, tax disclosure and the approving senior
accountant. It is watermarked as a quotation, not a tax invoice. The senior workspace and
the customer portal both download the same generated PDF through authenticated endpoints.

## 6. UI surfaces

- **`/pricing`** — monthly/annual toggle, six tier cards, comparison table, clear annual
  discount state, accounting quotation calculator (business details, turnover, services,
  payroll/inventory, GST, bank accounts, FY), ITR cards, disclosures and “Request a
  Quotation”.
- **`/accountant/quotations`** — senior-only workspace: request queue with benchmark,
  searchable quotation list, editable line items, add service/add-on/custom charge,
  discount, payment frequency, validity, terms, live totals preview, save draft, approve,
  send, reject, record customer decision, PDF.
- **`/accountant/enquiries`** — pipeline view; requests link into the workspace. Legacy
  quotation creation now produces a draft that still requires approval and sending.
- **`/client`** — request a quotation, track request status, view only approved/sent
  quotations, download PDFs, accept/decline sent quotations with the explicit statement
  that acceptance charges nothing.
- **`/developer` → Pricing** — rules, software tiers, ITR prices, add-ons, price history;
  each save writes history and a `developer.*` audit event.

## 7. Business rules enforced in code

- Software subscription and accounting fees are separate; a quotation does not bundle the
  subscription price.
- ITR is not automatically included.
- Accounting is never advertised as free.
- Final accounting fees always require senior approval.
- Prices are configurable without source edits.
- Taxes/additional charges are disclosed; totals are recalculated server-side.
- Accepting a quotation creates no payment or charge. Payments remain a separate process.
- No regulated filing is automatic; reports remain working papers unless an authorised
  professional files them through the proper channel.

## 8. Tests

Backend suite (219 passed) includes `backend/tests/test_pricing_quotations.py`:

- exact configured software and ITR prices, annual discount state, disclosures;
- tier boundaries and indicative benchmark;
- discount types, payment frequency math, junior 403;
- full lifecycle: draft → approve → send → customer PDF → accept, with payment count
  unchanged;
- customer request visible only after sending, stranger 403;
- expired quotation rejected for decisions;
- rejection requires a note and blocks sending;
- developer price changes propagate to the public page and estimator, with history pairs
  and audit actions.

The existing accounting flow test was rewritten to assert the draft/approval/send sequence
and that juniors cannot create quotations.

## 9. Verification

- `tsc --noEmit`: clean.
- Vite production build: success (`index-douxmW4Y.js`).
- Frontend Vitest: 66 passed (12 files).
- Backend `pytest`: 219 passed.
- Browser walkthrough:
  - public `/pricing`: exact six monthly prices, annual table with no invented discount,
    ITR prices, calculator and disclosures;
  - senior `/accountant/quotations`: draft from a request, 2% benchmark spread, save,
    approve, send, read-only sent state, PDF download (4 KB, valid `%PDF-1.4`, correct
    scope and totals);
  - customer `/client`: request a quotation (indicative ₹4,00,000 on ₹2 crore turnover,
    marked “not a final fee”), view the approved quotation, PDF download, accept, and no
    charge message.
- Permission checks with real tokens: customer gets 403 on the senior workspace, another
  client's PDF and an unsent quotation PDF; junior gets 403 on the workspace, approval and
  PDF endpoints.
- Developer pricing verified against a real developer session: six configured tier prices,
  2% benchmark, 0% annual discount, 15-day validity, 18% GST, ITR 999/1,999/3,999/5,000–
  12,000, role isolation (401 unauthenticated, 403 senior), and a no-op tier update
  returning 200 without changing the price. The Pricing tab itself was typechecked and
  production-built but not browser-driven, to avoid entering developer credentials into
  the browser.
- Existing demo databases are repaired on boot: the seeded Coastal quotation gains its
  line items/approval totals and the Meridian customer receives the seeded sent quotation,
  so the approval rule is consistent without reseeding the whole database.
- Not deployed. The local build is served by the backend at `127.0.0.1:8000`; a Render
  redeploy would reset the free SQLite database and was not requested.
