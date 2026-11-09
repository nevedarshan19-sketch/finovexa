# Troubleshooting

## Start here

```bash
curl -s http://127.0.0.1:8000/api/health
```

Expected: `status: "ok"`, PayPal `"simulated"` without keys, LLM `"deterministic_fallback"`, `live_trading_enabled: false`, and `developer_console` set to `configured` or `disabled`.

If the API does not answer, check the process and log:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
tail -n 80 /tmp/finovexa-api.log   # if started with the suggested log redirect
```

## Ports are already in use

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

Stop the stale process, then restart. If you change the API port, update the Vite proxy target in `frontend/vite.config.ts` and `FRONTEND_URL`/`CORS_ORIGINS` in `backend/.env`.

## `npm` or `node` not found

In this workspace Node is installed outside the default shell `PATH`:

```bash
export PATH=/Users/darshanyogeshneve/.local/node-v22/bin:$PATH
node --version
npm --version
```

## The UI loads but API calls fail

1. Confirm the backend runs on `127.0.0.1:8000`.
2. Confirm the frontend runs on `127.0.0.1:5173` (the default CORS origin).
3. Check the browser Network tab for the failing request and status.
4. `401` usually means the token expired or the backend database was recreated. Sign out and sign in again.
5. A `404` for a record usually means it belongs to another business — tenant isolation is working as intended.

## Demo reset fails

| Symptom | Cause | Fix |
| --- | --- | --- |
| `400 Type "RESET DEMO" to confirm` | Wrong confirmation phrase | Send exactly `{"confirm": "RESET DEMO"}`. |
| `403 Demo reset is restricted to the seeded demo account` | You are signed into a registered account | Use `demo@finovexa.ai`. |
| `403 Demo reset is disabled` | `DEMO_RESET_ENABLED=false` | Enable it in `backend/.env` and restart. |
| `429` | Limit is 3 resets per 5 minutes | Wait for the window to pass. |
| Reset succeeds but UI looks stale | Cached client data | Reload the page; sign in again if needed. |

## Developer console login fails

The developer account exists only when the backend env is configured. Check `/api/health`:

```bash
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
```

| Symptom | Cause | Fix |
| --- | --- | --- |
| `developer_console: "disabled"` | `DEVELOPER_EMAIL` or `DEVELOPER_PASSWORD` is empty | Set both in `backend/.env` (or the Render dashboard) and restart. |
| Startup log: `refusing to seed developer` | Password is shorter than 12 characters or lacks a letter/digit | Use a stronger password and restart. |
| Startup log: email belongs to a non-developer | `DEVELOPER_EMAIL` matches an existing owner/employee | Use a unique email or remove the conflicting account first. |
| `403 Developer console access required` | Signed in with an owner or employee token | Sign out and use `/developer/login`. |
| `401` on the developer page | Token expired or the developer account was disabled | Sign in again; the account is re-enabled by seeding on startup if it is the configured developer. |

The developer password is hashed in the database and never returned by any API. Reset it by changing `DEVELOPER_PASSWORD` in the backend env and restarting — startup re-syncs the configured developer's password hash. Never put the password in the frontend or source control.

The developer console can also change any owner/employee login email or password. An email must be unique across all accounts; changing it immediately changes the sign-in ID, while existing JWT sessions stay valid until they expire. Use **Disable** if a session must be cut off immediately.

## `429 Too Many Requests`

Limits are per IP and per scope. Common ones: login 10/min, register 5/min, AI chat 20/min, demo reset 3/5min. Wait for the window to expire. Automated tests clear the in-process limiter between tests.

## PayPal shows SIMULATED and capture returns 409

Expected without credentials. The simulated path is `POST /api/paypal/simulate`. To use sandbox:

1. Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE_URL` (sandbox URL) and `PAYPAL_WEBHOOK_ID`.
2. Restart the backend.
3. Use the normal order/capture endpoints.

Never use live PayPal credentials for a demo.

## Webhook returns 401

The raw body signature did not verify.

- Configured PayPal: confirm the webhook ID and that PayPal's verification headers are forwarded unchanged.
- Unconfigured demo: send `X-FINOVEXA-Demo-Signature: sha256=<hex>` computed with HMAC-SHA256 over the exact raw bytes using `PAYPAL_DEMO_WEBHOOK_SECRET`.
- Do not re-serialize the JSON between signing and sending.

## AI answers say `mode: "rules"`

No usable LLM key is configured, or the provider failed and the orchestrator fell back deterministically. This is intentional and safe. Set `LLM_PROVIDER`, `LLM_API_KEY` and `LLM_MODEL`, restart, then check Settings → Integrations.

## Market data says DEMO

No metals/news/Upstox credentials are configured. DEMO values are seeded sample data and are never presented as live. Configure the provider and restart; check the mode chips and freshness timestamps.

## Investment order cannot execute

- Approval payload hash must match exactly.
- Approval expires after 30 minutes.
- Buy headroom is re-checked at execution; a request that exceeds it is marked `failed` with an explanation.
- A duplicate order for the same approval is blocked.

Open a new approval after changing the business reserve or the requested quantity.

## Live Upstox order is rejected

Live execution requires `UPSTOX_LIVE_TRADING_ENABLED=true`, a valid `UPSTOX_ACCESS_TOKEN`, an INR business profile, a live quote or live option chain, and an instrument token. The ticket also has to be created with execution mode **Live**.

- `401` from Upstox usually means the access token expired. Generate a fresh token and restart the backend.
- `429` means the Upstox rate limit was hit; wait and retry.
- A static-IP error means the request did not come from an IP registered with Upstox. Set `UPSTOX_ORDER_PROXY_URL` to an HTTPS egress proxy that exits from the registered IP, then retry.
- A timeout does **not** prove the order failed. The backend checks the Upstox order book for the `BP-{approval}-{hash}` tag before marking the approval failed.
- If an order was submitted, use **Refresh broker status** in the Approval Center. Use the simulated fill/cancel endpoints only for simulated orders; they reject live orders.

## Test failures

Run tests from each project directory:

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm test
```

- Backend tests create an isolated temporary SQLite database and override credentials. Do not point them at `finovexa.db`.
- If pytest cannot import `conftest`, confirm you are in `backend/` and `requirements-dev.txt` is installed.
- Frontend tests need `npm install` first.
- If `npm test` cannot find `src/test/setup.ts`, confirm the file exists and re-run.

## Database is locked (SQLite)

SQLite allows one writer. Stop duplicate backend processes (including `--reload` children), then retry. For a completely fresh local database:

```bash
# Destructive: deletes local demo data. Stop the backend first.
cd backend
rm finovexa.db
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The startup seed recreates the demo business and market data.

## TypeScript build errors

```bash
cd frontend
npx tsc --noEmit
npm run build
```

The build is strict. Missing imports or mismatched API types surface here before Vite bundles.

## Where to look next

- Swagger: `http://127.0.0.1:8000/api/docs`
- API examples: [`API.md`](API.md)
- Live vs simulated matrix: [`LIVE_VS_SIMULATED.md`](LIVE_VS_SIMULATED.md)
- Demo script: [`DEMO_WALKTHROUGH.md`](DEMO_WALKTHROUGH.md)
