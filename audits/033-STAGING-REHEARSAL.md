# 033 — STAGING REHEARSAL RECORD

**Migration:** `backend/migrations/033_entitlement.sql`
**Target rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`)
**Date:** 25 Aug 2026
**Prod (`oxblcmwhuwtobdhsfgyi`) was not touched.** No prod credentials are
present in this repo — `.env.staging` holds `STAGING_DB_URL` and nothing else.

Before-snapshot: `audits/033-staging-before.txt`

---

## What was rehearsed

Sections 1–5 applied one at a time, each VERIFY run, each ROLLBACK executed,
then all five re-applied forward, then every section run twice more to prove
idempotency. Result of every step below.

| Step | Result |
|---|---|
| SECTION 1 apply — plan_tier CHECK | PASS |
| VERIFY 1a — constraint reads `('starter','pro','business','beta')` | PASS |
| VERIFY 1b — 0 stored rows violate it | PASS |
| VERIFY 1c — `paused` rejected | PASS (CheckViolation) |
| VERIFY 1c2 — `elite` rejected | PASS (CheckViolation) |
| VERIFY 1d — `business` accepted | PASS |
| SECTION 2 apply — `enterprise` → `business` | PASS (UPDATE 1) |
| VERIFY 2a — 0 `enterprise` rows | PASS |
| VERIFY 2b — features/limits/price/sort_order unchanged | PASS |
| VERIFY 2c — no non-canonical plan ids | PASS |
| VERIFY 2d — row count unchanged (3) | PASS |
| VERIFY 2e — exactly one `business` row | PASS |
| SECTION 3 apply — `usage_meters` | PASS |
| VERIFY 3a — 7 columns, `value numeric(14,4)` | PASS |
| VERIFY 3b — RLS enabled | PASS |
| VERIFY 3c — one PERMISSIVE SELECT policy, `has_check=false` | PASS |
| VERIFY 3d/3e — **anon holds zero privileges** | PASS |
| VERIFY 3f — authenticated cannot write | PASS |
| VERIFY 3g — 3 indexes | PASS |
| VERIFY 3h — period `2026-13` rejected | PASS |
| VERIFY 3h — period `2026-8` (unpadded) rejected | PASS |
| VERIFY 3h — negative value rejected | PASS |
| VERIFY 3h — whitespace-only meter rejected | PASS |
| VERIFY 3h — duplicate (business, meter, period) rejected | PASS |
| VERIFY 3i — atomic increment 1.5 + 2.0 = 3.5000 | PASS |
| extra — distinct meters and periods do not collide | PASS (4 rows) |
| extra — `ON DELETE CASCADE` removes meters with the business | PASS |
| VERIFY 3j — table empty after apply | PASS |
| SECTION 4 apply — the two DECISION 2 columns | PASS |
| VERIFY 4a — types/nullability/defaults | PASS |
| VERIFY 4b — all businesses opted out, no cap | PASS |
| VERIFY 4c — `businesses_spend_cap_chk` convalidated=true | PASS |
| VERIFY 4d — metering ON with no cap rejected | PASS |
| VERIFY 4e — metering ON with cap 100 accepted | PASS |
| VERIFY 4f — cap 0 rejected | PASS |
| VERIFY 4f2 — negative cap rejected | PASS |
| VERIFY 4g — cap NULLed while metering ON rejected | PASS |
| VERIFY 4h — cap set while metering OFF allowed | PASS |
| SECTION 5 apply — grant narrowing | PASS |
| VERIFY 5a — authenticated UPDATE on 26 columns | PASS |
| VERIFY 5b — **0 UPDATE on the two new columns** | PASS |
| VERIFY 5c — relacl `authenticated=ardDxtm` | PASS |
| VERIFY 5d — SELECT/INSERT still table-level (28) | PASS *(see M4)* |
| VERIFY 5e — `SET ROLE authenticated` cap write → permission denied | PASS |
| VERIFY 5e2 — metering flip → permission denied | PASS |
| VERIFY 5f — allowed column still writable (reaches RLS) | PASS |
| VERIFY 5g — new columns still readable | PASS |
| SECTION 6 pre-flights 6a/6b (boolean + hex guards) | PASS (0 rows) |
| SECTION 6 apply — brand_color + five renames | PASS |
| VERIFY 6a — `brand_color` key gone from all flags | PASS |
| VERIFY 6b — New Body `#475569` overwrote column; MSC unchanged | PASS |
| VERIFY 6c — no rename source key survives | PASS |
| VERIFY 6d — no merge turned a true into a false | PASS (0 rows) |
| SECTION 7 apply — R4 strip | PASS |
| **VERIFY 7b, canonical defaults — regressions** | **PASS (0 rows)** |
| **VERIFY 7b, deployed defaults — regressions** | **8 ROWS. See D1.** |
| VERIFY 7c — surviving non-canonical keys | `voice`, `industry` on both |
| ROLLBACK 7 and 6 — exact copy-back from backup | PASS (0 rows differ) |
| Backup survives 4 re-pastes of sections 6/7 | PASS *(after D3 fix)* |
| ROLLBACK 5 → 4 → 3 → 2 → 1, in reverse order | ALL PASS |
| Post-rollback diff vs before-snapshot | **IDENTICAL** |
| Re-apply 1 → 5 forward | ALL PASS |
| Idempotency: every section run twice more | ALL PASS *(after M5 fix)* |
| Final diff vs before-snapshot | only 033's own additions |

`./check.sh` — green. 273 passed, 104 subtests.

### The one rollback that destroys data

ROLLBACK 3 is `DROP TABLE usage_meters`. On staging the table was empty, so
the rollback was lossless and provable. **In prod, after the application
starts writing meters, that data is billing evidence.** The section carries a
capture query to run first. This is the only irreversible rollback in the file.

### Rehearsal fixtures

Staging holds 3 fixture businesses, all `starter`, all `feature_flags = '{}'`,
and `plan_definitions` was **empty**. Sections 1 and 2 would have been vacuous.
Fixtures were seeded to mimic prod's recorded shape — two businesses on `pro`,
and `plan_definitions` rows `starter`/`pro`/`enterprise` — then removed after
the rehearsal. Staging's data is back to its before-snapshot values; only the
033 schema changes remain.

**So the DDL is proven. The prod data path is proven only against a fixture
built from the spec's description of prod, not against prod itself.**

---

## Mismatches found — reported, not worked around

### M1 — `businesses.brand_color` already exists. PART B needs a backfill, not an ADD COLUMN.

The column has existed since the 028 baseline: `text null=YES def='#3B82F6'`.
The spec's acceptance criterion reads "`brand_color` **moves out** of
`feature_flags` to its own column on `businesses`" as though the column must be
created.

This changes the work. The destination is not empty — it holds a non-null
default. `PUT /v1/business/brand-color` (`backend/main.py:1352`) writes **only**
the `feature_flags` key and never the column, so the column most likely holds
`#3B82F6` for everyone while the flag holds the real choice. The backfill is
therefore a reconciliation of two values that may disagree, and which one wins
is a decision. **Needs the prod values to settle.**

### M2 — `industry` is a live, non-boolean flag key the canonical vocabulary omits

`feature_flags.industry` is read at `backend/quoting_api.py:1151` to build the
AI quoting system prompt, and written at `AdminBusinessDetail.tsx:835` and
`AdminOnboardingWizard.tsx:408`. PART B's canonical list does not contain it.

PART B says "unknown keys are ignored rather than treated as features", which
is right for entitlement. But **ignoring a key and deleting it are not the same
operation**, and a consolidation that drops unknown keys would take the industry
off both businesses and silently downgrade every AI quote to the `general`
fallback. Nothing would error. Nobody would notice for weeks.

`brand_color` and `industry` are both non-boolean, both load-bearing, and the
spec accounts for only one of them.

### M3 — SETTLED 25 Aug 2026: `025` has NOT run on prod

Confirmed by Michael against prod: `plan_definitions` still holds `enterprise`.
SECTION 2 does real work. The original finding is kept below for the record.

#### (original finding)


`supabase/migrations/025_rename_elite_to_business.sql` renames `elite` →
`business` on `businesses.plan_tier`, widens the CHECK to include `business`,
deletes the `enterprise`/`elite` `plan_definitions` rows and inserts
`starter`/`pro`/`business` with **distinct** feature sets (business carries
`premium_support: true` — which is PART A's "its features must then differ
from pro", listed as unmet).

**025 has not been applied to staging**: staging's CHECK still reads
`('starter','pro','elite','beta','paused')` and `plan_definitions` has no
`setup_fee_gbp` column, which 025 adds. The spec agrees with staging, not 025.

If 025 ran on prod, SECTION 2 is a no-op there and SECTION 1 reduces to
removing `paused`. The file is safe either way — every VERIFY still passes —
but the answer decides whether prod's top tier already has distinct features
or still has two byte-identical ones. **PRE-FLIGHT 2a settles it in one query.**

### M4 — `plan_definitions` has no primary key on staging

`supabase/migrations/017` declares `id TEXT PRIMARY KEY`. Staging's copy has
**no primary key, no unique index, and no constraints at all**, so 017 was not
the statement that created it, and `ON CONFLICT (id)` is impossible there.
Nothing but SECTION 2's `NOT EXISTS` guard prevents two `business` rows, and
`onboarding_api.py:187` does `SELECT * FROM plan_definitions WHERE id = :plan_id`
expecting one. PRE-FLIGHT 2b checks prod. **Not fixed here** — adding a unique
index could fail on prod if duplicates already exist, and that is its own
decision.

### M5 — two of my own written EXPECTs were wrong; both corrected against the DB

- VERIFY 5c: I wrote `authenticated=arDxtm`. Actual is `ardDxtm` — I had
  dropped the lowercase `d` (DELETE) as well as the `w`. File corrected.
- VERIFY 5d: I wrote "expect 26, 26, 0" for SELECT/INSERT/DELETE. Actual is
  **28** for SELECT and INSERT, because those remain **table-level** grants and
  a table-level grant covers columns added later. Only UPDATE was converted to
  a column list. File corrected, with the consequence spelled out: an owner can
  still SELECT both new columns (wanted — PART E requires usage be visible) and
  can still name them in an INSERT of a new business row (the same
  business-creation hole 030b addresses at `AdminDashboard.tsx:380`; not made
  worse here, not fixed here).

Also fixed during rehearsal:
- Sections 3 and 4 were **not idempotent** — Postgres has no
  `ADD CONSTRAINT IF NOT EXISTS`, so re-pasting a section errored. Both now
  `DROP CONSTRAINT IF EXISTS` first. Proven by running every section three times.
- `monthly_spend_cap_gbp` had a redundant `DEFAULT NULL`, which records
  `NULL::numeric` in the catalog and made VERIFY 4a's expected value look wrong.
  Removed.
- SECTION 2 renamed the id but left `name = 'Enterprise'`, recreating the
  internal/external split PART A exists to end. It now sets `name = 'Business'`
  **only when the name is still the bare default**, so bespoke copy is preserved
  and reported rather than clobbered.

---

## Not applied, and why

**SECTION 6 — PART B flag consolidation and the `brand_color` backfill — is
not written.** PART C requires the removal list be reviewed first, and that
list cannot be produced from staging: 3 fixture businesses, `feature_flags`
empty, `plan_definitions` empty. It needs the prod values. The two read-only
queries that unblock it are at the foot of the migration file.

**DECISION 4's `billing_exempt` is absent** — not requested, and the spec makes
it conditional on 030b, which has not shipped to the database.

**030b's grant narrowing has NOT been applied to the database.** Verified:
`authenticated` still holds table-level `arwdDxtm` on `businesses`, with
`plan_tier`, `is_active`, `feature_flags`, `api_key` and `subscription_status`
all browser-writable. Commit `b325b50` shipped 030b's backend endpoints; the
grant half is still open. SECTION 5 narrows exactly two columns and leaves the
rest of that hole exactly as it is.

---

# SECTION 6 / 7 — flag consolidation rehearsal

**Re-run 25 Aug 2026 against the EXACT prod values**, supplied from the live
query. The earlier run used reconstructed fixtures; this one does not. Six
businesses seeded to match prod row for row: 2 × `pro`, 4 × `starter`.

Rules R1–R5 as ruled, plus `voice → aria_voice` as a sixth rename and
`industry` left untouched.

## Result — every business ends at `{}`

| | before | after |
|---|---|---|
| **MSC** (`pro`) | 11 keys, `brand_color` flag `#3B82F6` | `{}` |
| **New Body** (`pro`) | 7 keys, flag `#475569` vs column `#3B82F6` | `{}` |
| **Test 1–4** (`starter`) | `{"receptionist": false}` | `{}` |

`brand_color` column after: MSC `#3B82F6` (unchanged), New Body **`#475569`**
(flag won, as ruled), test businesses `#3B82F6`.

**MSC reaches `{}`.** The earlier D4 finding — that it could not — was an
artifact of the reconstructed fixture, which invented `voice` and `industry`
keys that do not exist in prod. **D4 is withdrawn.** Your original expectation
was right.

The four starter businesses also clear: `receptionist: false` equals starter's
canonical default of `false`, so R4 removes it. That is six businesses with an
empty `feature_flags` — PART C's "empty is the normal state", reached exactly.

### Step by step

| Step | Result |
|---|---|
| PRE-FLIGHT 6a — all rename keys boolean | PASS (0 rows) |
| PRE-FLIGHT 6b — all brand_color values valid hex | PASS (0 rows) |
| PRE-FLIGHT 6c — disagreement: New Body only | as expected |
| SECTION 6 apply | PASS |
| VERIFY 6.0b — backup holds pre-rename keys | PASS (11) |
| VERIFY 6a — `brand_color` key gone | PASS |
| VERIFY 6b — New Body `#475569` written to column | PASS |
| VERIFY 6c — no rename source survives | PASS |
| VERIFY 6d — no merge turned a true into a false | PASS (0 rows) |
| SECTION 7 apply | PASS (UPDATE 6) |
| **VERIFY 7b — canonical defaults** | **PASS (0 regressions)** |
| **VERIFY 7b — deployed defaults** | **12 regressions. See D1.** |
| VERIFY 7c — surviving non-canonical keys | **none** |
| VERIFY 7d — final state | all six at `{}` |
| ROLLBACK 7/6 — copy-back | PASS (0 rows differ, 11 keys restored) |
| Re-apply forward | PASS |
| Idempotency — 6 and 7 twice more | PASS (UPDATE 0), backup intact |

### Merges exercised by the real data

- **MSC** carried `accounting` AND `accounting_enabled`, both `true` → merged
  to `accounting: true`. Also `calendar` AND `calendar_booking_enabled`, both
  `true` → merged to `calendar_booking: true`. Two sources into one target,
  no conflict, as ruled.
- **New Body** carried only the `_enabled` forms → straight renames.
- `voice → aria_voice` is a **no-op on current prod data** — neither business
  has a `voice` key. It is in the pair list for durability: the key is read at
  `AdminBusinessDetail.tsx` and could be written by hand at any time.

## D1 — CONFIRMED and worse than estimated: 12 features, not 8

Applying SECTION 7 against the currently deployed `_plan_feature_defaults`
(`pro = {"email": True}`) costs, measured:

- **MSC (7)** — `accounting`, `aria_chat`, `aria_voice`, `calendar_booking`,
  `quoting`, `receptionist`, `whatsapp`
- **New Body (5)** — `accounting`, `calendar_booking`, `quoting`,
  `receptionist`, `whatsapp`

Against the canonical defaults: **zero**.

The gate stands: SECTION 7 must land in the same deploy as the canonical
constant in **both** `backend/auth.py:249` and `backend/main.py:2346`, or
after it. VERIFY 7b in its deployed form must return 0 rows first.

## D2 — RESOLVED: the admin catalog is now canonical

`FEATURE_TOGGLE_LIST` and `INDUSTRY_PRESETS` rewritten to the canonical
vocabulary, and two write paths fixed that would have undone SECTION 7 on the
first save:

- The **industry preset handler** wrote every catalog key explicitly
  (`updatedFlags[f.key] = presets.includes(f.key)`) — putting plan defaults
  into `feature_flags` and pinning an explicit `false` on everything the preset
  omitted. It now writes only what differs from the plan default.
- The **toggle switch** fell back to a hardcoded per-feature `defaultEnabled`
  that had nothing to do with what the customer bought. It now resolves through
  the plan, and setting a value that matches the plan default **removes** the
  key rather than storing it.

New module `frontend/client/src/lib/entitlements.ts` holds the canonical
feature list, the plan-defaults table, the PART C resolution rule and a
`setFeatureFlag` helper. `AdminBusinessDetail`, `AdminDashboard` and `AppShell`
all import from it. It must stay in step with the backend constant and the
migration's `plan_defaults` CTE — noted in the file.

### The three keys that gate nothing

`ai_receptionist_enabled`, `email_management_enabled`, `invoice_chasing_enabled`.

Every reference to all three was inside `AdminBusinessDetail.tsx` itself — its
own `FEATURE_TOGGLE_LIST` entry plus the `INDUSTRY_PRESETS` rows. **No backend
check, no other component, no gate anywhere.** They were write-only: the admin
panel wrote them to `feature_flags` and nothing ever read them back.

Two of the three were duplicates under a different name — `ai_receptionist_enabled`
is `receptionist`, `email_management_enabled` is `email`, both of which *are*
read. `invoice_chasing_enabled` maps to canonical `invoicing`. All three are
gone from the catalog; none exists in prod data, so no migration is needed for
them.

## D3 — the backup table was clobbering itself (found and fixed earlier)

`DROP TABLE IF EXISTS` + `CREATE TABLE AS` meant re-pasting SECTION 6
re-snapshotted the backup from the already-migrated state, silently destroying
the rollback while the transforms correctly reported `UPDATE 0`. Now
`CREATE TABLE IF NOT EXISTS` plus VERIFY 6.0b. Re-proven on this run: backup
held 11 pre-rename keys after two extra re-pastes of both sections.

## D4 — WITHDRAWN

See the top of this section. `voice` and `industry` do not exist in prod.

## D5 — NEW: SECTION 6 broke brand_color end to end, in the backend

Not caught until the frontend pass. `GET /v1/me` returned
`flags.get("brand_color")` and `PUT /v1/business/brand-color` wrote the flag —
**neither touched the column**. So SECTION 6 would have made `/v1/me` return
`brand_color: null` for every business, and the next save from the branding UI
would have written the key straight back into `feature_flags`.

`businesses.brand_color` was also **not mapped on the SQLModel `Business`
class** at all, despite existing in the database since the 028 baseline — which
is why the code had been using the flags dict.

Fixed: `brand_color` added to the model (a field on an existing table, not a
new table — `create_all()` adds tables, never columns), `/v1/me` reads the
column, and the endpoint writes the column. `flag_modified` is no longer needed
there and its now-unused import was removed.

## Fixture provenance

Exact prod values, supplied 25 Aug 2026:

- **MSC** (`pro`, column `#3B82F6`): `email`, `calendar`, `aria_chat`,
  `accounting`, `aria_voice`, `receptionist`, `quoting_enabled`,
  `whatsapp_enabled`, `accounting_enabled`, `calendar_booking_enabled` all
  `true`, plus `brand_color: "#3B82F6"`
- **New Body** (`pro`, column `#3B82F6`): `email`, `receptionist`,
  `quoting_enabled`, `whatsapp_enabled`, `accounting_enabled`,
  `calendar_booking_enabled` all `true`, plus `brand_color: "#475569"`
- **Test 1–4** (`starter`, column `#3B82F6`): `{"receptionist": false}`

Staging was returned to its before-snapshot data afterwards; only 033's schema
changes remain. Diff against `033-staging-before.txt`: zero unexplained lines.
