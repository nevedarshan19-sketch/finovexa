# Old Render data capture — retired

This procedure was written when the plan was to migrate the existing old-service
business records into FINOVEXA. That migration is no longer required.

Decision (2026-11-03): FINOVEXA production starts with a **fresh database**. The old
SQLite data, uploads and demo records are not imported. Do not upgrade the Render plan,
open a Shell or copy the old database for migration purposes.

What still matters:

- The old Render service stays live and untouched until the new FINOVEXA deployment
  passes its go-live checklist.
- The new service uses Neon Postgres and `FILE_STORAGE=database`; see
  [`FREE_STACK.md`](FREE_STACK.md).
- If old records are ever needed for reference, they remain in the old service's
  database; no capture is scheduled.

If the old service is decommissioned later, export its SQLite file first only for
archive purposes. That is a separate, explicit decision and is not part of go-live.
