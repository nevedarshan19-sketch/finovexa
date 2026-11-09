# FINOVEXA production provisioning

Status 2026-11-03: the zero-cost path in [`FREE_STACK.md`](FREE_STACK.md) is the
approved direction. This file no longer describes the primary plan.

## Current plan

1. Neon Free Postgres — no card, 1 GB, 100 CU-hours/month.
2. Render Free web service from `render.yaml` — no persistent disk, 750 hours/month.
3. `FILE_STORAGE=database` so uploads live in Postgres.
4. Initial owner/senior/junior accounts from `INITIAL_*` env vars; no demo data.
5. New service first; the old Render deployment stays live until the go-live checklist
   passes.

Follow `FREE_STACK.md`. Do not create paid resources or add a payment method.

## Superseded: GCP e2-micro path

An earlier draft planned an always-on GCP e2-micro VM with a 30 GB disk and a GCS backup
bucket. It was blocked at step 0 because the Google account has no accepted Cloud Terms
of Service and no billing account, and Google requires a card even for Always Free
resources. That conflicts with the no-card requirement, so the path is deferred
indefinitely.

If it is ever reconsidered, the trade-offs are:

- Always-on, no cold starts; usable with SQLite plus the existing systemd backup scripts.
- Requires a card and a careful budget/guardrail setup; budgets are alerts, not caps.
- More operational work (VM patching, Caddy, disk, backups) than the render + Neon stack.

Nothing from that draft should be executed without a new explicit approval.
