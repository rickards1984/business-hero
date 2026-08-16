# Business Hero — Working Agreement

Live SaaS. Real customers imminent. Read this before acting.

---

## The verification loop — this is the core change

**Do not ask Michael to check your code.** He is the product owner and tester,
not a code reviewer. Prove your own work instead.

For every change:

1. Make the change.
2. Run `./check.sh`.
3. If it fails, fix and re-run. Iterate until green. Do not report a failure
   you have not attempted to fix.
4. Report: what changed, `check.sh` result, and **what Michael should click to
   confirm the behaviour is right**.

That last line is his job. He tests behaviour against real-world business
knowledge. You test correctness. Do not swap the two around.

If `check.sh` cannot verify a change (e.g. visual layout), say so explicitly
and describe the manual test. Never imply verification you did not perform.

---

## Autonomy tiers

### GREEN — proceed without asking, report when green
UI fixes, styling, empty states, loading skeletons, copy, component refactors,
adding tests, logging, non-behavioural cleanup.

Rule: a mistake here is visible immediately and costs nothing. Just go.

### AMBER — plan first, one approval, then run to completion
New endpoints, schema-additive migrations, PDF generation, feature work,
integration wiring.

Rule: propose the plan with acceptance criteria. Once approved, execute the
whole plan without stopping between steps. Report at the end with results.

### RED — never autonomous, always explicit approval per action
- Money: quoting maths, invoice numbering, VAT, Stripe, plan enforcement
- Security: RLS, grants, policies, auth, `businesses`/`business_members`
- `git push`, or any command that deploys
- Any SQL against production
- Deleting data or dropping anything

Rule: **tests first.** Write the failing test that encodes correct behaviour.
Michael reviews *the test*, not the implementation. Then code until green.

A rounding error on VAT is invisible until it is on eighty invoices. That is
why this tier exists.

---

## Do not regress — each of these was a real, costly incident

1. **Railway installs from ROOT `requirements.txt`**, not `backend/`. Adding a
   dep to only the backend file crashes the deploy. Bit us twice (`slowapi`,
   `reportlab`). `./scripts/preflight.sh` now checks this — run it before push.
2. **Repo must stay outside Dropbox/CloudStorage** (`.git/index.lock` errors).
   It lives at `~/Documents/business-hero-2`. Do not move it.
3. **`create_all()` runs at every boot.** A new SQLModel class silently creates
   a live table with **RLS OFF and default grants**. Any new model = a possibly
   exposed table. Confirm RLS + policies before deploying.
4. **Migration files are NOT evidence of live state.** They have drifted from
   prod before. Verify against `pg_class` / `pg_policies` on the live DB.
5. **Two Supabase projects exist.** Business Hero is `oxblcmwhuwtobdhsfgyi`.
   Confirm the project selector before any SQL.
6. **GPT-5 models reject `temperature`/`max_tokens`.** Use
   `max_completion_tokens` and omit temperature.
7. **Railway replica count must be 1.** Rate limiting and the Xero refresh lock
   are in-process and break silently at 2+.
8. **`anon`/`authenticated` hold broad table grants**, so RLS is the only gate
   on the client path. An RLS-off table is publicly reachable.

---

## Architecture facts

- Frontend: React/TS on Vercel — `frontend/client/src/`
- Backend: FastAPI on Railway — `backend/`
- DB: Supabase Postgres, project `oxblcmwhuwtobdhsfgyi`
- Deploy: push to `main` → Railway + Vercel auto-deploy. **Michael pushes.**
- **Two DB paths, opposite RLS behaviour:** the backend connects as an elevated
  role and **bypasses RLS** (tenant isolation is application-layer
  `WHERE business_id = …`); the frontend uses supabase-js with the public anon
  key and **is subject to RLS**. Never reason about one as if it were the other.
- Admin and customer are the **same Postgres role** (`authenticated`). Grants
  are evaluated before RLS, so a column grant given to admin is given to
  customers too. Admin-only writes belong on the backend.

---

## Claims discipline

Any commercial claim in product copy, marketing or outreach must be defensible
if challenged. Keep "won" and "pipeline" clearly distinguished. Anonymise third
parties unless permission is on file.

---

## Current task

> Keep this section current. It is the first thing a fresh session reads.

**Now:** migration `030` — pre-billing security batch. Blocks Stripe.
- Pin `business_id`, `role`, `user_id` in the `business_members.users_link_self`
  WITH CHECK (currently only constrains email → cross-tenant pivot)
- Add `is_active` to `is_business_member()` (deactivation currently revokes
  nothing across 55 tables)
- Revoke write grants on `businesses` / `business_members` / `stripe_events`
  from `anon`; move the four admin `businesses` writes to backend endpoints
- Lock `businesses.api_key` to owner
- Tighten `stripe_events` to service-role

**Then:** money engine (Decimal, per-line VAT built jurisdiction-pluggable from
the start, collision-safe invoice numbering) → manual invoices → branding and
invoice PDF → Stripe with server-side enforcement → UI batch → final walkthrough.
