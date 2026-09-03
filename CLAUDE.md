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

**Applied to prod:** migrations `030a` (pre-billing security), `031`
(money engine schema) and `033` (entitlement) **through SECTION 7**. All
rehearsed on staging first. Runbooks in `audits/030a-PROD-RUNBOOK.md`,
`audits/031-PROD-RUNBOOK.md` and `audits/033-PROD-RUNBOOK.md`.

The 2026-09-03 schema dump confirms 033's schema half: `usage_meters` exists
with all seven columns, and `businesses` carries both SECTION 4 columns
(`metered_usage_enabled`, `monthly_spend_cap_gbp`).

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

**PART D — the READ side. DONE, `./check.sh` green, 358 tests (26 new in
`backend/tests/test_entitlement_reads.py`).**

PART C fixed every write path and touched no reader. `feature_flags` had
been doing two jobs — recording exceptions AND being the readable state of
the world — and PART C took the second away, so every reader still asking
it raw read a column that is, correctly, empty. `_is_feature_enabled` reads
a stripped `pro` business as entitled; `flags.get("receptionist", False)`
reads the same row as denied.

Five sites, now resolving: `_require_receptionist_flag` (nine settings
endpoints — NOT the phone line, which gates on
`receptionist_configs.enabled` and never checks entitlement, so a broken
gate meant the receptionist answering while its owner was locked out of the
only switch that stops it); onboarding's step-skip loop (the priority — it
does not error, it marks the step COMPLETE, and `accounting` is true on
every tier so it hit every business); the admin overview; the admin email
chip; and `PUT /admin/receptionist/{id}/feature-flag`, now the fourth write
path that strips — it closed a loop where the admin UI's "Enable Feature"
button re-pinned the default SECTION 7 had just removed.

Plus `BrandingSettings.tsx`, same species from SECTION 6: the column and
the save endpoint moved, the read did not, so saved brand colours never
loaded back.

The guard that did not exist: the new test parses every backend and
frontend source file for canonical-feature reads that bypass the resolver,
resolving alias chains to a fixpoint, with a self-test so a regex matching
nothing cannot pass as green. The vocabulary test protects what the table
says; this protects how it is asked.

**THIS UNBLOCKED 033 SECTION 7, WHICH HAS NOW RUN.** The strip cannot tell
a stale merged default from a goodwill grant, so a business carrying legacy
flags would keep them through a downgrade; SECTION 7 stripped against the
CURRENT tier while both live businesses were still `pro`, which is what makes
later downgrades work.

**Post-SECTION-7 state, verified against the expected output at the time:**
MSC and New Body are both `{}`, the four test businesses are `{}`, and
Business Hero retains only `quoting: false`, `calendar_booking: false`,
`industry`, and the two retired wizard keys.

**THE ONE OUTSTANDING 033 ITEM, and it is RED: STEP 21.** MSC and New Body
carry a manual `receptionist: true`, added as a stopgap when the raw reader
in `receptionist_api.py` 403'd after the strip — the owner was locked out of
the only switch that stops the receptionist answering. Removing it is
`033-PROD-RUNBOOK.md` STEP 21.

That reader is fixed (PART D) **but not yet verified in prod**, and the fix
is in the same undeployed batch as the two bugs below. STEP 21 is gated on
STEP 20d — the fourth gate check, which asks whether the DEPLOYED backend
resolves entitlement rather than reading it raw, and names the commit. Do
not run STEP 21 until 20d passes against prod.

**Deliberately out of scope, still open:** `limits` untouched on every path
(nothing reads it for enforcement). `AdminDashboard.tsx`'s `FEATURE_PRESETS`
still holds a fourth vocabulary (`ai_briefings`, `premium_support`) — now
harmless, because the server strips what it submits, but it is a stale table.
`plan_definitions` remains runtime-editable via
`PUT /v1/admin/onboarding/plans`.

**Two prod bugs found and fixed while reading the admin path, both
undeployed. `./check.sh full` green, 382 tests (24 new).**

(1) `admin_business_api` wrote `businesses.updated_at` on BOTH the overview
save and the admin activate/pause endpoint. There is no such column — not in
`models.py`, not in the 028 baseline, not in any observed dump. Both endpoints
had returned 500 on every request since 030b Release 1 (`b325b50`, 20 Aug).
Nothing read the column, so the write is simply gone rather than the column
added: `create_all()` creates tables but never columns, so adding it means a
migration plus a trigger, and `onboarding_api` writes this table without
setting it — half-applied audit metadata is worse than none.

New guard `backend/tests/test_schema_conformance.py` parses every
`UPDATE`/`INSERT` in the backend and checks each written column against
`audits/live-schema-public.txt`. **That file is now the FULL prod dump of
2026-09-03 — 816 columns, 59 tables, `coverage: FULL`, `UNGUARDED_BUDGET = 0`
— so all 39 written tables are guarded and nothing is exempt.** It found no
phantom writes beyond the two `updated_at` ones. Regenerating after every
migration is 033-PROD-RUNBOOK **STEP 24b**.

Building that file with `grep` is a trap and STEP 24b now says so: the
Supabase CSV export quotes every field containing a comma, so `grep "^col "`
silently drops all 111 `numeric(p,s)` / `character varying(n)` rows and the
result reads convincingly like a half-applied migration. Parse it as CSV. The
guard does not fail quietly on a bad dump — fed the truncated version it
reported 106 phantom writes.

(2) Those 500s reached the browser as `Failed to fetch`. Starlette routes
`Exception`/500 to `ServerErrorMiddleware`, which sits ABOVE all user
middleware including CORS, so unhandled 500s carried no
`Access-Control-Allow-Origin` and Chrome discarded them — status and body
both unreachable. Every unhandled server error in this app has looked like a
network failure. Fixed with `main.CORSSafeErrorMiddleware`, added BEFORE
`CORSMiddleware` so CORS wraps it; `backend/tests/test_error_cors.py` asserts
the ordering as well as the behaviour, verified to fail when reverted.
**4xx were never affected** — they go through `ExceptionMiddleware`, below
CORS — so any 400 seen on these endpoints is a separate, still-undiagnosed
issue.

**Then:** manual invoices → invoice PDF and branding (there is no invoice
PDF at all today; `quote_pdf.py` has no sibling, and invoices have no
preview or edit UI) → Stripe with server-side enforcement → the frontend
batch: 108 hardcoded `£`, `assistant_chat.py`'s hardcoded 20% VAT, and
wiring the region resolver into the PDFs.

**Post-launch:** Compliance & Site Operations module — brief, decisions and
open questions in `audits/COMPLIANCE-MODULE-BRIEF.md`. Not started; marketed
as "coming soon" at launch.

**Deliberately still open** (recorded in the spec's out-of-scope list):
the seven independent total calculations are not yet consolidated, the
`float` → `Decimal` conversion covers new and touched code only, and
`markup_percentage` is stored but never totalled.
