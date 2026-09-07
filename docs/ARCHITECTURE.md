# Architecture — STUB

**Status: stub.** Verified architecture facts are in `AGENTS.md` §4 and
`docs/CURRENT_STATE.md` §2. This file is the placeholder for a proper
component and data-flow document.

Summary, so this page is not empty:

- React/TS on Vercel → FastAPI on Railway → Supabase Postgres
- **Two DB paths with opposite RLS behaviour** — the backend bypasses RLS and
  isolates tenants in application code; the frontend is subject to RLS. This
  is the single most important architectural fact in the system
- `create_all()` at boot creates tables but never columns
- Railway replica count must stay 1 (in-process rate limiter and Xero lock)

**Known structural debt** (`docs/CURRENT_STATE.md`): `backend/main.py` is
5,295 lines and holds billing, invoices, settings, OAuth, admin and debug
routes; two migration directories exist with no single ordering.

**To write properly when:** someone needs it to make a decision. A diagram
nobody uses is boilerplate, and the brief explicitly warns against that.
