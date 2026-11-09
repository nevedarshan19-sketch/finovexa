# PayPal integration — setup and operations

FINOVEXA AI uses the official PayPal REST APIs for checkout, capture verification, refunds and webhooks.
Nothing is marked paid from a browser redirect. Cash changes only after the backend verifies a capture or a
signed webhook.

- Sandbox is the default and the only environment used for development.
- Production is never enabled automatically. It requires its own credentials and an explicit owner
  confirmation in **Settings → PayPal**.
- AI agents can explain and recommend actions, but they never capture, refund or move money.

## 1. What is implemented

| Area | Behaviour |
| --- | --- |
| Checkout | `POST /api/paypal/orders` creates a PayPal order for an issued GST invoice and stores the provider order ID. |
| Payment | The customer approves in PayPal, then the owner selects **Verify & capture**. The backend captures server-side and re-checks status, amount, currency and invoice reference. |
| Invoice state | `draft → issued → pending_payment → paid` (or `partially_paid`, `overdue`, `void`). A checkout hold is released on cancel or denial. |
| Webhooks | PayPal signature verification API when credentials and a webhook ID are present. Invalid signatures return 401. Events are deduplicated by PayPal event ID. |
| Refunds | Owner-only, confirmation required, partial refunds supported, recorded as negative payments with the PayPal refund reference. |
| Reconciliation | Deterministic matching: amount/currency and invoice reference first, then customer/sender name suggestions. Unmatched or mismatched captures never change an invoice until the owner confirms a match. |
| Dashboard | Verified totals, pending, failed, refunded, net, unmatched/mismatch, payment series and recent transactions — all from stored records. |
| Settings | Sandbox/production selector, enable toggle, masked client/webhook hints, connection test, webhook endpoint and event log. |
| Audit | Every order, capture, refund, settings change and webhook outcome is written to the audit trail. Secrets and tokens are never logged. |

## 2. Credentials

Secrets live **only** in backend environment variables (or the deployment secret store). The browser
receives booleans, the active environment and masked hints such as `••••AB12`.

```env
PAYPAL_ENVIRONMENT=sandbox
PAYPAL_SANDBOX_CLIENT_ID=
PAYPAL_SANDBOX_CLIENT_SECRET=
PAYPAL_SANDBOX_WEBHOOK_ID=
PAYPAL_LIVE_CLIENT_ID=
PAYPAL_LIVE_CLIENT_SECRET=
PAYPAL_LIVE_WEBHOOK_ID=
PAYPAL_DEMO_WEBHOOK_SECRET=replace-with-a-local-demo-only-secret
```

- Keep both sandbox and production pairs separate. Never reuse sandbox keys in production.
- `PAYPAL_BASE_URL` / `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` / `PAYPAL_WEBHOOK_ID` are legacy fallbacks for
  older deployments. Prefer the scoped names above.
- Do not commit a real `.env`. `.env.example` contains placeholders only.
- Access tokens are cached in memory per `(environment, client_id)` and are never written to the database or logs.

## 3. Sandbox setup (developer.paypal.com)

1. Create a PayPal Developer account and open **Apps & Credentials → Sandbox**.
2. Create a sandbox app and copy its **Client ID** and **Secret** into `PAYPAL_SANDBOX_CLIENT_ID` and
   `PAYPAL_SANDBOX_CLIENT_SECRET`.
3. Under **Sandbox → Accounts**, use a Personal (buyer) sandbox account to approve checkouts. Use the
   Business account that owns the app for captures.
4. Add a webhook:
   - URL: `https://YOUR_BACKEND_HOST/api/paypal/webhook`
   - Events: `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.DENIED`,
     `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED`
   - Copy the **Webhook ID** into `PAYPAL_SANDBOX_WEBHOOK_ID`.
5. Restart the backend, sign in as the owner, and open **Settings → PayPal**. Confirm the environment is
   `Sandbox`, the masked client ID is shown, and **Test connection** succeeds.

If credentials are empty, the Payment Center stays in **SIMULATED** mode: the button records a clearly
labelled demo payment and calls no PayPal API. Simulated records are never presented as real captures.

## 4. Sandbox walkthrough

1. Issue a GST invoice (GST & Billing). Note the final amount including tax.
2. Open **Payments → Outstanding invoices → PayPal checkout**.
3. Select **Create PayPal order** and open the approval link.
4. Pay with the sandbox buyer account.
5. Return to FINOVEXA and select **Verify & capture**.
6. Confirm:
   - The invoice moves to **Paid** only after the capture is verified.
   - The transaction shows `paypal`, `confirmed`, `matched`.
   - A reconciliation record exists and the dashboard totals increased by the net amount.
7. Deliver the same webhook event twice (PayPal **Webhooks → Resend**). The second delivery is reported as a
   duplicate and creates no second payment.
8. Cancel an uncaptured checkout. The invoice returns from `pending_payment` to `issued`/`overdue`.
9. Capture a wrong amount or currency. It is stored as `mismatch`, the invoice is not marked paid, and the
   reconciliation panel asks for owner review.
10. Refund all or part of a capture from the transaction row. The invoice balance reopens and a negative
    payment plus refund reference are stored.

## 5. API summary

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/payments/overview` | Filters (`days`, `start`, `end`, `status`, `currency`), stats, payments, orders, refunds, events, reconciliation, series. |
| GET/PUT | `/api/paypal/settings` | Read masked runtime settings / select environment and enabled state (owner only). |
| POST | `/api/paypal/settings/test` | OAuth connection test (owner only). |
| POST | `/api/paypal/orders` | Create or reuse an open checkout order for an invoice. |
| GET | `/api/paypal/orders[/{id}]` | Stored orders / remote status when configured. |
| POST | `/api/paypal/orders/{id}/cancel` | Cancel an uncaptured checkout and release the invoice hold. |
| POST | `/api/paypal/orders/{id}/capture` | Verify and capture; idempotent per capture ID. |
| POST | `/api/paypal/payments/{id}/refund` | Owner-confirmed refund (full or partial). |
| GET | `/api/paypal/refunds` | Refund history for the business. |
| GET | `/api/paypal/events` | Webhook event log, scoped to the business. |
| GET | `/api/paypal/reconciliation` | Matched/unmatched/mismatched captures and reconciliation history. |
| POST | `/api/paypal/webhook` | Public, signature-verified, idempotent webhook endpoint. |
| POST | `/api/paypal/simulate` | Labelled simulated capture when PayPal is not configured. |

All business endpoints require an owner JWT except the webhook. Employee accounts receive 403.

## 6. Webhook security and idempotency

- Verification uses PayPal's `/v1/notifications/verify-webhook-signature` with the configured webhook ID.
- When PayPal is not configured, local demo events require `X-FINOVEXA-Demo-Signature` (HMAC-SHA256 with
  `PAYPAL_DEMO_WEBHOOK_SECRET`). Unsigned events are rejected with 401.
- Every delivered event ID is stored in `payment_events` with a unique constraint.
- Delayed refunds that arrive before their capture are stored as `deferred` and applied when the capture lands.
- Repeated, out-of-order and unsupported events never create duplicate cash movements.

## 7. Data stored

- `paypal_orders` — checkout records, amount, currency, approve URL, capture status.
- `paypal_refunds` — refund references, amounts, reasons, mode and status.
- `payments` — confirmed captures, pending/failed attempts and negative refund entries, with
  `reconciliation_status`, `reconciled_at` and `refund_of_payment_id`.
- `payment_events` — verified webhook log, verification mode, linked user/invoice/payment and outcome.
- `reconciliation_records` — deterministic matching and refund history.
- `provider_settings` — non-secret runtime selection (environment, enabled, updated by).

Indexes and unique constraints cover provider order IDs, capture references, refund IDs, event IDs and
payment idempotency keys. Migrations are additive and run at startup.

## 8. Moving from sandbox to production

Do this only after the sandbox workflow and reconciliation have been validated.

1. Create a **Live** PayPal app and copy its live client ID and secret.
2. Add a live webhook with the production URL and the same event set; copy its webhook ID.
3. Set `PAYPAL_LIVE_CLIENT_ID`, `PAYPAL_LIVE_CLIENT_SECRET` and `PAYPAL_LIVE_WEBHOOK_ID` in the backend
   deployment. Redeploy/restart so the environment is loaded.
4. In **Settings → PayPal**, choose **Production**, tick the real-money confirmation, and save.
5. Run **Test connection**; confirm `mode = LIVE` and webhook verification is active.
6. Capture a small real payment and refund it to confirm both directions before normal use.

The app does not switch itself to production. It refuses production mode when live credentials are absent.
Do not keep sandbox and live webhooks pointed at the same environment selection.

## 9. Business restrictions

PayPal is only for legitimate business payments on GST invoices. It must not be used for investment money,
shares, ownership transfers, stock trades or securities subscriptions. Market Intelligence is an
informational research surface only.

## 10. Troubleshooting

| Symptom | Check |
| --- | --- |
| `PayPal is not configured` on capture | Credentials for the selected environment are missing; restart after setting them. |
| `PayPal authentication failed` | Client ID/secret mismatch or the account is not enabled for that environment. |
| Webhook returns 401 | Webhook ID missing/incorrect, or the signature does not match the raw body. |
| Invoice stays `pending_payment` | The order was not captured; cancel it or resend the checkout. |
| Capture stored as `mismatch` | Amount, currency or invoice reference differs. Review it in Money Recovery. |
| Refund rejected | The capture was already fully refunded, or the payment is not a confirmed PayPal capture. |
| Dashboard totals unchanged | Only confirmed captures count; pending and failed attempts never affect cash. |

## 11. Tests

`backend/tests/test_paypal_integration.py` covers masked settings and production gating, order creation and
invoice holds, verified capture and duplicate prevention, cancel release, owner-confirmed refunds and refund
limits, mismatch webhooks, refund webhooks and duplicate events, failed captures, owner scoping and
cross-business denial, and overview filters/statistics. PayPal HTTP calls are served by an in-memory fake
so no network request or real money is involved. Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_paypal_integration.py -q
.venv/bin/python -m pytest -q
```
