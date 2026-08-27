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

**Applied to prod:** migration `030a` (pre-billing security) and `031`
(money engine schema). Both rehearsed on staging first. Runbooks in
`audits/030a-PROD-RUNBOOK.md` and `audits/031-PROD-RUNBOOK.md`.

`031` added: `invoice_line_items`, `unit_cost` widened to `numeric(14,4)` on
both line-item tables, per-line discount/apportionment/tax columns,
`invoices.subtotal` / `tax_amount` / `related_invoice_id`,
`businesses.region` / `tax_registered` / `tax_number`,
`quote_settings.next_invoice_number` / `invoice_prefix`, and the partial
unique index `UNIQUE (business_id, invoice_number) WHERE external_source IS
NULL`. MSC's counter is seeded to 2.

**Now:** ENTITLEMENT-SPEC PART C — plan is the source of truth. DONE,
`./check.sh full` green, 326 tests passing (53 new in
`backend/tests/test_entitlement_defaults.py`).

The sweep found FIVE plan->feature tables in three vocabularies. Two were
Python (`auth.py` and `main.py`, the same non-canonical dict twice, inventing
`calendar`/`voice` and giving `starter` nothing). Now ONE, in
`auth.PLAN_FEATURE_DEFAULTS`, canonical. The test PARSES the two copies that
cannot be deduplicated — `entitlements.ts` and 033 SECTION 7's CTE — and
compares, so drift fails the build.

`auth.strip_plan_defaults()` is the write-path rule: drop a key only when it
is canonical AND boolean AND equals the tier default. Applied at all three
creation paths — onboarding business_details (feature_flags now OMITTED from
the INSERT; the column default '{}' applies), onboarding plan_features,
`admin_business_api.create_business` — and at the Stripe webhook, which
replaced `_merge_feature_flags` (deleted; it wrote defaults in by
construction, and against the canonical table would have written eleven).

`AdminOnboardingWizard.tsx` now holds exceptions, not a copy of the plan:
canonical keys, `planDefaults()`/`setFeatureFlag`, matching
`AdminBusinessDetail.tsx`. `plan_definitions` still prices plans; it no
longer decides entitlement.

**THIS UNBLOCKS 033 SECTION 7** — and SECTION 7 must now RUN. Two reasons.
(1) Its ordering rule is satisfied only once this deploys. (2) The strip
cannot tell a stale merged default from a goodwill grant, so a business
carrying legacy flags keeps them through a downgrade; SECTION 7 strips
against the CURRENT tier while both live businesses are still `pro`,
reducing them to `{}` and making later downgrades work.

**Deliberately out of scope, still open:** `limits` untouched on every path
(nothing reads it for enforcement). `AdminDashboard.tsx`'s `FEATURE_PRESETS`
still holds a fourth vocabulary (`ai_briefings`, `premium_support`) — now
harmless, because the server strips what it submits, but it is a stale table.
`plan_definitions` remains runtime-editable via
`PUT /v1/admin/onboarding/plans`.

**Then:** manual invoices → invoice PDF and branding (there is no invoice
PDF at all today; `quote_pdf.py` has no sibling, and invoices have no
preview or edit UI) → Stripe with server-side enforcement → the frontend
batch: 108 hardcoded `£`, `assistant_chat.py`'s hardcoded 20% VAT, and
wiring the region resolver into the PDFs.

**Deliberately still open** (recorded in the spec's out-of-scope list):
the seven independent total calculations are not yet consolidated, the
`float` → `Decimal` conversion covers new and touched code only, and
`markup_percentage` is stored but never totalled.
