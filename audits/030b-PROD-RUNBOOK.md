# 030b RELEASE 2 — PROD RUNBOOK

**Migration:** `backend/migrations/030b_release2_revoke.sql`
**Target:** Business Hero prod — Supabase project **`oxblcmwhuwtobdhsfgyi`**
**Spec:** `audits/030B-SPEC.md` PART E. Closes RC1 **P0-3**, the paywall hole.
**Rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`), 18 Sep 2026.
Section 1 applied → verified → rolled back → verified restored → re-applied
→ applied twice more for idempotency. Section 2 the same. Record:
`audits/030b-STAGING-REHEARSAL.md`. Before-snapshot:
`audits/030b-staging-before.txt`.

**What this does, in one sentence:** `authenticated` loses INSERT and UPDATE
on `businesses` and the now-unreachable `biz_update_if_owner` policy is
dropped, so an owner can no longer set their own `plan_tier`,
`feature_flags`, `is_active`, `limits` or `subscription_status` from the
browser with the anon key.

**What it does not touch:** SELECT (retained — the four frontend reads of
`businesses` keep working), `anon` (already SELECT + TRIGGER since 030a),
the backend (connects as the table owner; owner privilege is not a grant),
`business_members`, any data.

---

## Before you start

Read the step, paste the SQL, compare against **EXPECT**, continue only if
it matches. The rules from 033 apply unchanged:

1. **One step at a time, and one QUERY at a time.** The Supabase SQL editor
   renders only the LAST statement's grid; a failed statement poisons the
   rest of its transaction. Where a step lists several queries, run each
   alone. Wrapped `BEGIN … ROLLBACK` blocks that EXPECT an error must be
   run alone.
2. **EXPECT must match.** If not, go to **STOP IF**. Do not improvise.
3. **On a mismatch, stop and report it.** Paste the output to Claude Code
   and say "prod 030b step N mismatch". `ROLLBACK 1` and `ROLLBACK 2` in
   the migration file were both executed on staging.

**Confirm the project selector reads `oxblcmwhuwtobdhsfgyi` before every
paste.** Staging is `gzcrsrqmygublveuzqyg`.

**STEPS 0–4 ARE READ-ONLY. Nothing changes until STEP 5.**

**Gate:** 030b Release 1 must be confirmed live in prod — the admin plan
editor, the two active toggles and business creation all working through
`/v1/admin/businesses/*` — before STEP 5. `docs/CURRENT_STATE.md` §8 records
Release 1 as shipped; STEP 3 checks that no browser path still writes the
table. If STEP 3 fails, Release 2 is not ready regardless of what the docs
say.

**Elapsed time:** about 15 minutes. **Downtime:** none. STEP 5 takes a brief
lock on a 6-row table.

---

## STEP 0 — Prod before-snapshot (READ-ONLY)

Three queries, one at a time. **Save every output** into
`audits/030b-prod-before.txt` — it is the rollback's reference and the
evidence for BH-001 Q4/Q6 at the same time.

```sql
-- 0a: table-level grants on businesses
SELECT grantee, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
  FROM information_schema.role_table_grants
 WHERE table_schema='public' AND table_name='businesses'
 GROUP BY grantee ORDER BY grantee;

-- 0b: COLUMN-level grants on businesses to the client roles
SELECT grantee, privilege_type, count(*) AS columns,
       string_agg(column_name, ', ' ORDER BY column_name) AS cols
  FROM information_schema.column_privileges
 WHERE table_schema='public' AND table_name='businesses'
   AND grantee IN ('anon','authenticated')
 GROUP BY 1, 2 ORDER BY 1, 2;

-- 0c: every policy on businesses, with expressions
SELECT polname, polcmd, polpermissive,
       pg_get_expr(polqual, polrelid)      AS using_expr,
       pg_get_expr(polwithcheck, polrelid) AS check_expr
  FROM pg_policy WHERE polrelid='public.businesses'::regclass ORDER BY 1;
```

**EXPECT** (this is the state 033 left and staging carries):

- **0a:** `anon` → `SELECT, TRIGGER`. `authenticated` →
  `DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE` — **no UPDATE at
  table level**. `postgres` and `service_role` → all seven.
- **0b:** `authenticated | UPDATE | 26` with the 26-column list from 033
  SECTION 5 (`api_key … trial_ends_at`; `metered_usage_enabled` and
  `monthly_spend_cap_gbp` absent). `authenticated | INSERT | 28`,
  `authenticated | REFERENCES | 28`, `authenticated | SELECT | 28`,
  `anon | SELECT | 28` — 28 because table-level grants are reported per
  column. Staging returned exactly these five rows on 18 Sep 2026.
- **0c:** exactly three rows: `Platform admins can manage all businesses`
  (`*`), `biz_select_if_member` (`r`), `biz_update_if_owner` (`w`) with
  both `using_expr` and `check_expr` reading
  `EXISTS (SELECT 1 FROM business_members bm WHERE bm.business_id =
  businesses.id AND bm.user_id = auth.uid() AND bm.role = 'owner' AND
  bm.is_active = true)`.

**STOP IF:**
- **0a shows `authenticated` with table-level UPDATE.** 033 SECTION 5 did
  not land as recorded. This runbook still works — `REVOKE UPDATE` removes
  table-level and column-level alike — but the rollback in the migration
  file restores the 26-column list, **not** the table-level grant, so the
  rollback would be wrong. Stop and report; the rollback needs rewriting
  before continuing.
- **0b shows more than 26 UPDATE columns**, or lists
  `metered_usage_enabled` / `monthly_spend_cap_gbp`. Same reason.
- **0c does not show exactly those three policies.** Something has been
  changed in the dashboard since 030a. Report before continuing; the
  runbook drops one policy by name and must not be run against an
  unknown set.

---

## STEP 1 — Confirm you are on the right database

```sql
SELECT current_database(), (SELECT count(*) FROM public.businesses) AS businesses,
       (SELECT count(*) FROM public.business_members) AS members;
```

**EXPECT:** `postgres`, a business count in the single digits that matches
the admin dashboard, and a non-zero member count. Staging has **3 and 0**;
if you see 3 and 0, you are on staging.

**STOP IF:** the numbers are staging's, or the business count is not what
the admin dashboard shows.

---

## STEP 2 — Pre-flight: the backend is not `authenticated`

The backend must keep writing `businesses` after the revoke. It does so as
the table owner. Prove the owner is not a client role:

```sql
SELECT tableowner FROM pg_tables
 WHERE schemaname='public' AND tablename='businesses';
```

**EXPECT:** `postgres`.

**STOP IF:** anything else. The Railway `SUPABASE_DATABASE_URL` connects as
`postgres`; if the table is owned by another role the revoke could reach
the backend's write path.

---

## STEP 3 — Pre-flight: nothing on the client path still writes the table

This is the Release 1 gate, checked from the repository, not from memory.
Run in a terminal on `main`:

```bash
grep -rn -B4 "\.\(insert\|update\|upsert\|delete\)(" frontend/client/src \
  --include='*.tsx' --include='*.ts' | grep "from('businesses')"
```

**EXPECT:** no output. (18 Sep 2026: the only supabase-js writes are to
`business_members`, `support_tickets` and `tasks`; all four
`from('businesses')` calls are `.select()`.)

**STOP IF:** any line. A browser write to `businesses` survives; Release 2
would break it with `permission denied` inside a `catch`. That is Release 1
work, not this runbook.

---

## STEP 4 — Pre-flight: prove the hole exists before closing it

Wrapped, harmless, and the reason this runbook exists. **Run alone.**

```sql
BEGIN;
  SET LOCAL ROLE authenticated;
  UPDATE public.businesses SET plan_tier = plan_tier;
ROLLBACK;
```

**EXPECT:** `UPDATE 0`. **No error.** Zero rows because `auth.uid()` is
NULL in the SQL editor so `biz_update_if_owner` matches nothing — but the
statement was *permitted*, which is the point. With a real owner's JWT it
would be `UPDATE 1`.

**STOP IF:** `permission denied for table businesses`. The grant is already
gone. Either Release 2 has already been applied (check
`audits/030b-PROD-*` and the git log) or something else revoked it. Do not
continue — the rollback would then GRANT something that was deliberately
removed.

---

## STEP 5 — SECTION 1: the revoke and the drop

**This is the change.** One paste, two statements, one transaction.

```sql
REVOKE INSERT, UPDATE ON public.businesses FROM authenticated;
DROP POLICY IF EXISTS biz_update_if_owner ON public.businesses;
```

**EXPECT:** `Success. No rows returned.`

**STOP IF:** any error. Nothing has changed if the REVOKE errored (it is
the first statement). If the DROP POLICY errored after a successful
REVOKE, the grant is gone and the policy remains — that is safe (the
policy is unreachable) but not the intended end state. Run VERIFY in
STEP 6, then `ROLLBACK 1` if anything is off.

---

## STEP 6 — VERIFY SECTION 1. Three queries, one at a time.

```sql
-- 1a: table-level
SELECT grantee, string_agg(privilege_type, ', ' ORDER BY privilege_type)
  FROM information_schema.role_table_grants
 WHERE table_schema='public' AND table_name='businesses'
   AND grantee IN ('anon','authenticated')
 GROUP BY grantee ORDER BY grantee;

-- 1b: column-level — THE ONE THAT MATTERS
SELECT privilege_type, count(*)
  FROM information_schema.column_privileges
 WHERE table_schema='public' AND table_name='businesses'
   AND grantee='authenticated' AND privilege_type IN ('UPDATE','INSERT')
 GROUP BY 1;

-- 1c: policies
SELECT polname, polcmd FROM pg_policy
 WHERE polrelid='public.businesses'::regclass ORDER BY 1;
```

**EXPECT:**

| query | value |
|---|---|
| 1a `anon` | `SELECT, TRIGGER` |
| 1a `authenticated` | `DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE` |
| 1b | **`0 rows`** — no UPDATE column, no INSERT column |
| 1c | exactly `Platform admins can manage all businesses` / `*` and `biz_select_if_member` / `r` |

**STOP IF:** 1b returns any row — the column grants survived and the hole
is open. Or 1a still lists INSERT or UPDATE. Or 1c still lists
`biz_update_if_owner`, or lists fewer than two policies (the SELECT policy
must survive or every customer loses their business row on the next page
load). Run `ROLLBACK 1` from the migration file, as one paste, then re-run
this step and confirm STEP 0's numbers are back (UPDATE 26, INSERT 28,
three policies).

---

## STEP 7 — Prove it as the role. Each block ALONE. **The errors are the pass.**

```sql
-- 1d-1: must FAIL
BEGIN;
  SET LOCAL ROLE authenticated;
  UPDATE public.businesses SET plan_tier = 'business';
ROLLBACK;

-- 1d-2: must FAIL
BEGIN;
  SET LOCAL ROLE authenticated;
  UPDATE public.businesses SET feature_flags = '{}'::jsonb;
ROLLBACK;

-- 1d-3: must FAIL
BEGIN;
  SET LOCAL ROLE authenticated;
  INSERT INTO public.businesses (name, api_key) VALUES ('x', 'x');
ROLLBACK;

-- 1d-4: must NOT fail. 0 is the pass.
BEGIN;
  SET LOCAL ROLE authenticated;
  SELECT count(*) FROM public.businesses;
ROLLBACK;
```

**EXPECT:** 1d-1, 1d-2, 1d-3 each error `permission denied for table
businesses`. 1d-4 returns `0` with no error — SELECT retained, zero rows
because `auth.uid()` is NULL here.

**STOP IF:** any of 1d-1..3 succeeds (even `UPDATE 0` — that means
*permitted*), or 1d-4 raises `permission denied` (you have removed SELECT;
`ROLLBACK 1` does not restore SELECT because it never removed it — run
`GRANT SELECT ON public.businesses TO authenticated;` and report).

---

## STEP 8 — SECTION 2 (OPTIONAL): DELETE, TRUNCATE, REFERENCES

**Decide before pasting.** The instruction for Release 2 named INSERT and
UPDATE. The spec's VERIFY (`030B-SPEC.md` PART E) says `authenticated`
holds **SELECT and TRIGGER only**, which is this section too. No client
path uses any of the three: no DELETE policy exists for members, TRUNCATE
is not subject to RLS and not exposed by PostgREST, REFERENCES is DDL.
Rehearsed on staging with its own rollback. **Skipping it is a valid
choice; it leaves the spec's VERIFY unmet and nothing else.**

```sql
REVOKE DELETE, TRUNCATE, REFERENCES ON public.businesses FROM authenticated;
```

**EXPECT:** `Success. No rows returned.` Then re-run 1a from STEP 6:
`authenticated` → `SELECT, TRIGGER`.

**STOP IF:** 1a shows anything else for `authenticated`. `ROLLBACK 2`:
`GRANT DELETE, TRUNCATE, REFERENCES ON public.businesses TO authenticated;`

---

## STEP 9 — Browser smoke test (Mike, in the product)

Not SQL. The four pages that read `businesses` through supabase-js:

1. **Business dashboard** loads and shows the business name — `BusinessDashboard.tsx` select.
2. **Billing settings** shows the plan and status — `BillingSettings.tsx` select.
3. **Branding settings** loads, and **saving a brand colour works** — the
   read is supabase-js, the write is `PUT /v1/business/brand-color`.
4. **Admin → business detail** loads, and **changing a plan tier through
   the admin editor works** — `AdminBusinessDetail.tsx` select, write via
   `/v1/admin/businesses/*` (Release 1).
5. **Admin → create a business** works (`admin_business_api.py`).
6. **Onboarding wizard** completes a step that writes the business
   (`onboarding_api.py`, backend).

**EXPECT:** all six work. **STOP IF:** any shows a permission error. 1–2
failing means SELECT was lost (STEP 7 1d-4 should have caught it). 3–6
failing means a write path still goes through the anon key — `ROLLBACK 1`,
and that path is Release 1 work.

---

## STEP 10 — Remove the xfail markers, and record it

In `backend/tests/test_tenant_isolation_rls_path.py`, the four
`test_an_owner_cannot_raise_their_own_entitlement` cases are
`xfail(strict=True)` with reason "030b Release 2 not yet applied". After
this runbook has run **in prod**, a local rehearsal
(`scripts/rls-local.sh up`, apply SECTION 1, `scripts/rls-local.sh test`)
makes them XPASS, and strict turns that into a failure — so the marker
comes off in the same commit that records this runbook as applied. That
commit also:

- adds `audits/030b-prod-before.txt` (STEP 0 output) and
  `audits/030b-prod-after.txt` (STEP 6 output);
- updates `docs/CURRENT_STATE.md` §5 (`030b` Release 2 → applied, with
  the date) and §8 ("This is the paywall hole … open" → closed, with the
  evidence);
- notes in the 030b spec's PART E checklist which of Section 2 was
  applied.

---

## If you need to undo everything

`ROLLBACK 2` (if Section 2 was applied) then `ROLLBACK 1`, each as one
paste from the migration file. Both were executed on staging in that
order and STEP 0's numbers came back exactly. Then re-run STEP 0 and
compare.
