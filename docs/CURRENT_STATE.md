# Current state — evidence-based baseline

**Compiled:** 2026-09-08, branch `foundation/rc1-baseline`, from commit
`9826f61`.
**Method:** repository inspection plus `./check.sh full`. Everything below is
either observed in the tree, observed in a verification run, or explicitly
marked unknown.

This document **consolidates** `audits/`; it does not repeat it. Where an
audit document already holds the detail, this links rather than duplicates.

## Status vocabulary

| Status | Means |
|---|---|
| **complete and verified** | Built, and a test or a recorded prod check proves it |
| **apparently complete but unverified** | Code exists and looks finished; nothing proves it works |
| **partial** | Some acceptance criteria met, others provably not |
| **broken** | Evidence it fails |
| **placeholder** | A stub, mock or inert control |
| **absent** | Does not exist |
| **unknown** | Not determinable without access this session did not have |

**Most of the frontend is "apparently complete but unverified."** There are
zero frontend tests and zero end-to-end tests. That is the single largest
epistemic gap in this document.

---

## 1 · Baseline verification — exact results

`./check.sh full`, 2026-09-08, clean tree:

```
FRONTEND
  PASS  tsc --noEmit
  SKIP  eslint  (no lint script in package.json)
BACKEND
  PASS  python syntax (py_compile)
  PASS  ruff
  PASS  pytest      382 passed, 19 warnings, 104 subtests passed in 2.10s
PREFLIGHT
  PASS  TRAP 1 requirements.txt sync
  PASS  TRAP 2 trailing newline
  PASS  TRAP 3 repo location
  PASS  TRAP 4 create_all() RLS drift warning
  PASS  TRAP 5 secret scan
  5 passed   0 failed   1 skipped   — Green.
```

**What green does and does not mean.** It means the frontend typechecks, the
backend compiles and lints, 382 backend tests pass, and five deploy traps
pass. It does **not** mean any user journey works. No test in this repository
drives a browser, and no test asserts that a business cannot read another
business's data.

`tsc --noEmit` passing is new. `audits/TIER1-CORE-FIXES.md` recorded 43
pre-existing errors in July; that backlog has been cleared.

### Test inventory

19 test files, all backend, 382 tests. Concentration by area:

| Area | Tests | Files |
|---|---|---|
| Entitlement (vocabulary + readers) | 85 | `test_entitlement_defaults`, `test_entitlement_reads` |
| Admin business surface | 71 | `test_admin_business_api`, `test_admin_surface_hygiene` |
| Money engine | 145 | numbering, totals, discounts, tax, decimal, conversion, region, parse |
| Infrastructure guards | 31 | `test_schema_conformance`, `test_error_cors`, `test_route_resolution` |
| Legacy | 9 | `test_feature_gating`, `test_awaz_webhook_auth`, `test_microsoft_graph_mapping` |

**Frontend tests: absent. End-to-end tests: absent. Tenant-isolation tests:
absent.**

### CI

`.github/workflows/ci.yml` — **complete and verified**. Runs on push to
`main` and on every PR, as a single job: install both toolchains, then
`./check.sh full`. It is the same command the pre-push hook runs, so the
local gate and the remote gate are one gate rather than two that can
disagree.

Rewritten 8 Sep 2026. It previously ran its own approximation of the gate —
`tsc`, `pytest`, `ruff` and `preflight` as separate steps, with `ruff` on
`continue-on-error: true`. That made lint blocking locally and non-blocking
remotely, which is the disagreement Codex's orientation found. Two pins hold
it together: `ruff` and `pytest` are pinned in CI to the working tree's
versions (an unpinned install lets a new lint rule red CI while local stays
green), and a guard step fails the build if `check.sh` *skipped* ruff or
pytest rather than running them — a skip is not a failure inside
`check.sh`, so a broken install would otherwise report green having
verified nothing.

Gap: no dependency vulnerability scanning (`pip-audit`, `npm audit`) —
outstanding since the July audit. Also, the pre-push hook is enabled per
clone (`git config core.hooksPath .githooks`); a fresh clone that skips that
step has no local gate, and CI on the PR is the only thing standing.

---

## 2 · Stack and deployment

- **Backend** FastAPI on Railway. Nixpacks, `uvicorn main:app`, healthcheck
  `/health` (120s timeout), restart on failure, max 3 retries. Root
  `main.py` is a shim; the real app is `backend/main.py`.
- **Frontend** React/TS + MUI on Vercel.
- **Database** Supabase Postgres `oxblcmwhuwtobdhsfgyi`. Staging is a second
  project, `gzcrsrqmygublveuzqyg`.
- **Replica count must stay 1** — rate limiting and the Xero refresh lock are
  in-process.

### Size

| | Files | Lines |
|---|---|---|
| Backend Python | — | ~41,300 |
| Frontend TS/TSX | 124 | ~33,800 |
| `backend/main.py` alone | 1 | 5,295 |
| Routes | — | ~209 |

`backend/main.py` at 5,295 lines is the largest single risk to parallel
agent work: it holds billing, invoices, business settings, OAuth, admin and
debug endpoints. See `AGENTS.md` §7.

---

## 3 · Database and migrations — **partial**

**Two migration directories with no single ordering:**
`backend/migrations/` (16 files) and `supabase/migrations/` (21 files).
Neither is authoritative. `supabase/migrations/028_baseline_live_state.sql`
is a captured baseline rather than a forward migration.

`create_all()` runs at every boot. It creates tables (RLS off, default
grants) and **never** columns.

### Applied to production

| Migration | Status | Evidence |
|---|---|---|
| `030a` pre-billing security | **complete and verified** | `audits/030a-PROD-RUNBOOK.md`, rehearsed |
| `031` money engine schema | **complete and verified** | `audits/031-PROD-RUNBOOK.md`, rehearsed |
| `033` entitlement, **through Section 7** | **complete and verified** | Mike confirmed post-strip flag state; schema dump shows `usage_meters` (7 cols) and both Section 4 columns present |
| `033` STEP 21 — remove stopgap flags | **absent** | Blocked; see §8 |
| `030b` Release 2 — the revoke | **absent** | See §5 |

### Schema truth

`audits/live-schema-public.txt` — full prod dump, 2026-09-03, **816 columns
across 59 tables**, guarded by `backend/tests/test_schema_conformance.py`
(`coverage: FULL`, `UNGUARDED_BUDGET = 0`, all 39 written tables checked).

**Gap:** the dump is columns only. It carries **no RLS, policy, grant or
index information**, so those cannot be verified from the repository. See
§5.

### Known schema debt (from `audits/`, not re-verified this session)

- Staging lacked every PK/FK/UNIQUE/CHECK until repaired for 031. Any
  rehearsal depending on a constraint proved nothing before that.
- Per-line tax columns are `NOT NULL DEFAULT 0`, so "no rate recorded" and
  "zero-rated" are indistinguishable. Blocks mixed per-line VAT.
- `paid_amount` vs `amount_paid` duplicate columns.

---

## 4 · Authentication, authorisation, tenancy

### Authentication — **apparently complete but unverified**

Supabase JWT, `Authorization: Bearer`. `supabase_auth.py` verifies by calling
Supabase `/auth/v1/user` **on every request** — a remote round-trip per call,
with no local algorithm/audience/issuer check. Flagged as SEC-09/PERF-05 in
July; still present.

**MFA: absent.** Nothing in the tree implements or enforces it.

Second scheme: `MASTER_ADMIN_KEY`, compared with `!=` rather than
`hmac.compare_digest` (SEC-13). `030b` PART C required confirming no external
consumer holds it before retirement — **that human check is still open.**

### Tenant isolation — **partial, and the weakest verified area**

Two paths with opposite behaviour:

- **Backend** connects as an elevated role and **bypasses RLS**. Isolation is
  application-layer `WHERE business_id = :bid`. The July audit found this
  consistently applied at the API layer and `business_id` derived from the
  JWT, never trusted from the client.
- **Frontend** uses supabase-js with the anon key and **is subject to RLS**.

**No automated test asserts tenant isolation on either path.** The July audit
recommended "a two-business integration test using the anon key"; it does not
exist. This is the highest-value missing test in the repository.

### RLS coverage — **unknown**

The July audit listed ~30 tables with RLS off. Migrations since then
(`030a`, `031`, `033`) enabled RLS on some. **The current live state cannot
be determined from this repository** — the schema dump has no policy data and
migration files are not evidence (`AGENTS.md` §3.4).

Resolving this needs one query against prod. It is the first thing RC1
security work should establish.

### Audit logging — **absent**

No append-only audit trail of who changed what. `stripe_events` is the
closest thing and is webhook-specific.

---

## 5 · Entitlement and billing

This is where the largest gap between documented intent and shipped code
sits, and it is the reason RC1's P0 list looks the way it does.

### Vocabulary (spec PART A / B) — **complete and verified**

One canonical tier set (`starter`, `pro`, `business`, `beta`), one canonical
feature table in `auth.PLAN_FEATURE_DEFAULTS`, `paused` removed from the plan
vocabulary and from all backend write paths. 85 tests, including tests that
**parse** the copies that cannot be deduplicated (`entitlements.ts`, 033's
CTE) so drift fails the build.

### Write paths (spec PART C) — **complete and verified**

`auth.strip_plan_defaults()` applied at all four creation/update paths. Plan
defaults are never written into `feature_flags`.

### Read paths — **complete and verified**

Five readers plus `BrandingSettings.tsx` now resolve rather than reading
`feature_flags` raw, guarded by a test that parses every source file for
bypassing reads.

> ⚠ **Naming collision — read this before trusting any status claim.**
> `CLAUDE.md` has been calling the reader work "PART D". The spec's **PART D
> is a different thing entirely: server-side enforcement.** A fresh session
> reading "PART D done" would reasonably conclude enforcement had shipped. It
> has not. The reader work is real and is complete; it is not PART D.

### Server-side enforcement (spec PART D) — **partial, and it is the RC1 blocker**

Verified this session:

```
require_feature call sites in backend/ (excluding tests and the definition):
  backend/app/email/router.py:64   dependencies=[Depends(require_feature("email"))]
```

**One endpoint. Email.** Unchanged from the position `audits/PRICING-MODEL.md`
§6 and `audits/ENTITLEMENT-SPEC.md` recorded in August.

Ungated paid surfaces, each confirmed to have authentication but no
entitlement check:

| Surface | File | Gate |
|---|---|---|
| Realtime voice (most expensive endpoint in the product) | `realtime_voice.py` | none |
| Aria chat | `assistant_chat.py` | none |
| Quoting incl. AI generation | `quoting_api.py` | none |
| WhatsApp send | `whatsapp_briefing_api.py` | none |
| Accounting sync | `accounting.py` | none |
| Receptionist settings | `receptionist_api.py` | `_require_receptionist_flag`, hand-rolled |
| Board meetings | `executive_meeting_api.py` | `require_tier_feature`, a **second** gate |

**A second gating mechanism is still live.** `services/tier_gating.py`
provides `require_tier_feature`, used at 7 sites in
`executive_meeting_api.py`. Its own docstring documents `paused` as a plan
tier — a fifth vocabulary, surviving the migration that removed `paused`
everywhere else. The spec's PART B required folding it into the single
mechanism.

**Consequence:** paid AI spend is gated client-side. The frontend hides
buttons; that is presentation, not enforcement.

### Metering (spec PART E) — **absent**

The `usage_meters` table exists in prod (7 columns) and
`businesses.metered_usage_enabled` / `monthly_spend_cap_gbp` exist. **No
backend code references any of them** — the only occurrences in `backend/`
are two comments. Nothing increments a meter; nothing enforces an allowance
or a spend cap.

Direct consequence: every receptionist minute allowance in
`audits/PRICING-MODEL.md` is decorative, and the pricing model's own warning
applies — "one customer discovers the receptionist and runs £400 of calls
through a £129 plan before anyone notices."

### Stripe — **partial**

Present: `POST /v1/billing/checkout-session`, `GET /v1/billing/status`,
`POST /v1/billing/portal`, `POST /v1/billing/webhook` with signature
verification.

Present and correct: the webhook writes `plan_tier` only when the price
changes, not on payment events — DECISION 3's most important criterion.

Missing:
- **No `subscription_status` → access-level resolver.** DECISION 3 requires
  `past_due` = full access with a banner, `unpaid`/`canceled` = read-only.
  No such resolver exists in `auth.py`.
- The webhook still sets `business.is_active = status in ("active",
  "trialing")`, which is exactly the `is_active` / `subscription_status`
  conflation DECISION 3 set out to separate.
- **No reconciliation between Stripe and `businesses`.** Webhooks silently
  stopped for two months in 2026 (dead Replit URL, 21 June → 20 August) and
  nothing surfaced it. Nothing has been added that would surface it now.
- `billing_exempt` column: **absent**.
- Founder accounts on real subscriptions with a 100% coupon: **absent**.

### The `businesses` UPDATE grant — **partial**

`030b` Release 1 shipped: four admin endpoints, server-side `api_key`
generation, narrowed reads. **Release 2 — the revoke — has not been applied.**
Until it is, `authenticated` retains table-wide UPDATE on `businesses` behind
a column-blind policy, so an owner can still set their own `plan_tier` and
`feature_flags` from the browser.

This is the paywall hole. It is documented, understood, and open.

---

## 6 · Modules

| Module | Status | Notes |
|---|---|---|
| Quoting + AI generation | **apparently complete but unverified** | Backend well tested; no UI test. Two buttons with the same apparent intent go to different modes (`audits/FINDINGS.md` UI-5) |
| Quote PDF | **apparently complete but unverified** | `services/quote_pdf.py` |
| **Invoice PDF** | **absent** | `quote_pdf.py` has no sibling. A UK VAT invoice cannot be produced |
| **Manual invoice creation** | **absent** | No `POST /v1/invoices`; UI offers CSV upload only. Confirmed end to end |
| Invoice numbering | **complete and verified** | Atomic counter, partial unique index, 31 tests |
| Money maths (Decimal, per-line tax, discounts) | **complete and verified** | 145 tests |
| CSV invoice import | **apparently complete but unverified** | `parse_amount` fixed and tested; the import path itself has no test |
| Accounting sync (Xero/QBO/FreeAgent) | **apparently complete but unverified** | Xero most developed. `accounting.py` still does money math in `float` |
| Email summarisation | **apparently complete but unverified** | "Analyse All" is now implemented — `EmailsTab.tsx:289` calls `analyzeEmails`. `audits/FINDINGS.md` UI-7 is **fixed** |
| AI receptionist (Twilio + OpenAI) | **apparently complete but unverified** | Signature validation and stream tokens shipped. **Ungated and unmetered** |
| Aria chat / voice | **apparently complete but unverified** | Ungated |
| WhatsApp briefings | **apparently complete but unverified** | Ungated |
| Board meetings | **apparently complete but unverified** | Gated by the second mechanism |
| Automation rules | **apparently complete but unverified** | |
| Onboarding wizard | **apparently complete but unverified** | Step-skip loop fixed during the reader work |
| Admin surface | **complete and verified** | 71 tests; two 500s fixed 2026-09-03 |
| CRM / customer management | **partial** | No dedicated module; customer data lives on quotes and invoices |
| Job / project management | **absent** | |
| B2B prospecting (Control Tower) | **absent from this repo** | Separate repository, `~/control-tower` (confirmed 8 Sep 2026). Runs on Mike's ChatGPT OAuth quota per `PRICING-MODEL.md` §4; economics change at multi-tenant. `outreach` remains a real canonical feature key here, reserved for the future integration |
| Staff / contractor management | **absent** | |
| Compliance & site operations | **absent** | Deliberate. `audits/COMPLIANCE-MODULE-BRIEF.md`, post-launch |
| Mobile / site workflows | **absent** | |

### Daily pulse — **broken**

`services/briefing_scheduler.py:553` makes a real OpenAI call and discards
the result; a hardcoded summary is sent instead. Every run pays for output
nobody reads. The weekly sibling does it correctly.

### Dark mode invoice table — **broken**

`design-system.css:456` paints a light background on the **cell**;
`:2337` paints the row for dark mode. The cell wins, so light text lands on a
near-white background. **Confirmed still present this session at both
lines.** Unreadable financial data, and an accessibility flag at review.

---

## 7 · Integrations and failure modes

| Integration | Auth | Verified failure handling |
|---|---|---|
| OpenAI | API key | Clients hardened `timeout=30, max_retries=1` at 11 sites |
| Twilio voice | Signature validation + HMAC stream tokens, 5-min TTL | Kill switch `TWILIO_SIGNATURE_VALIDATION=off` |
| Twilio WhatsApp | Signature validation | |
| Stripe | Webhook signature | **No reconciliation** — see §5 |
| Xero | OAuth | Refresh lock is in-process only; breaks at 2+ replicas |
| QuickBooks / FreeAgent | OAuth | Less developed than Xero |
| Google / Microsoft email | OAuth | Gmail per-message fetch is N+1 (PERF-01) |
| Supabase | Service role + anon | JWT verified remotely per request |

**Idempotency: partial.** Quote conversion is blocked by a status gate and
Stripe events are de-duplicated. `create_quote`, chase-send and the WhatsApp
action path have no idempotency key, so a retry can duplicate a customer-
facing send.

Secrets: environment variables only, 48 distinct. `.env*` is gitignored;
only `.env.example` files are tracked. TRAP 5 scans staged files for key
patterns. **No secret rotation policy exists.**

---

## 8 · Outstanding production action

**033 STEP 21 — RED, blocked.** MSC and New Body carry a manual
`receptionist: true`, added as a stopgap when the raw reader 403'd after the
Section 7 strip and locked the owner out of the only switch that stops the
receptionist answering. The reader is fixed but **not yet verified in prod**.
STEP 21 is gated on STEP 20d passing against the deployed backend
(commit `9826f61`, pushed 2026-09-03).

---

## 9 · Dead, duplicated and abandoned code

Evidence-backed only.

| Item | Evidence |
|---|---|
| `get_or_create_smtp_account` | Defined `app/email/service.py:288`, called nowhere |
| `services/tier_gating.py` | Second gate; spec required folding it in |
| `light_text` in `quote_pdf.py:49` | Defined, never applied |
| `nova` voice | Supported by OpenAI, missing from `AVAILABLE_VOICES` |
| `DEFAULT_PRESET_ID` | Imported, then duplicated as a hand-typed literal |
| `AdminDashboard.tsx` `FEATURE_PRESETS` | Fourth feature vocabulary; harmless (server strips) but stale |
| `CLAUDE.md.bak-preharness-…`, `COMMIT_MSG.tmp`, `current_live_schema.sql`, `live_state/` | Untracked working files at repo root |
| 4 local + 7 remote stale branches | e.g. `security-rls-session-1`, `copilot/*` |

---

## 10 · Risks by severity

**Critical**
1. Paid surfaces have no server-side entitlement check (§5).
2. No metering — an allowance cannot be enforced, so voice spend is unbounded (§5).
3. `businesses` UPDATE grant still open to owners (§5).
4. RLS coverage on ~30 tables is **unknown** (§4).

**High**

5. No tenant-isolation test on either DB path.
6. No Stripe reconciliation; a silent webhook outage already ran two months.
7. No invoice PDF — a UK VAT invoice cannot be produced (§6).
8. No frontend or end-to-end test of any kind.
9. No audit logging.
10. No backup/restore test, no documented rollback beyond migration runbooks.

**Medium**

11. `accounting.py` money math in `float`.
12. Remote JWT verification per request.
13. Gmail N+1 sync.
14. No dependency vulnerability scanning.
15. UK GDPR: no data export or deletion path (`docs/SECURITY.md` stub).
16. MFA absent.

---

## 11 · What this document could not determine

- **Live RLS, policy and grant state.** Needs one query against prod. The
  single highest-value unknown.
- Railway environment: replica count, which variables are actually set.
- ~~Whether any external consumer holds `MASTER_ADMIN_KEY`~~ — **answered
  8 Sep 2026: no consumer.** Mike grepped Control Tower and `.openclaw`;
  nothing holds it. This clears the one human check that was blocking
  `030B-SPEC.md` PART C. **Action: delete `MASTER_ADMIN_KEY` from the
  Railway environment**, and remove `verify_master_key` with it — it is a
  shared static secret compared with `!=` rather than
  `hmac.compare_digest` (SEC-13), on an admin surface that has already
  settled on `get_platform_admin_context`.
- Whether the 14-char `sk_` API key generator is still reachable
  (`030B-SPEC.md` scope note 4).
- Dependency CVE status.
- ~~Whether Control Tower shares this codebase~~ — **answered 8 Sep 2026:
  it does not.** Separate repository at `~/control-tower`.
- Real behaviour of every "apparently complete but unverified" module.
