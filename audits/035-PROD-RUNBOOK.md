# 035 — PRODUCTION RUNBOOK: aria_actions (Aria's approval cards)

**For:** Mike. **Ticket:** NS-B10. **Migration:** `backend/migrations/035_aria_actions.sql`.

**Rehearsed:** `audits/035-STAGING-REHEARSAL.md` (13 Oct 2026). On staging it
was applied, verified, rolled back to the before-state, and re-applied.

**Risk:** RED, as all production SQL is. Low in practice:
- one new, empty table;
- nothing existing is changed;
- the public (anon) role gets no access, and signed-in users can only read
  their own business's rows.

Takes about 10 minutes.

**Run every step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT
before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start:** the NS-B10 code is NOT deployed yet and must not be.
This migration goes first; the code follows once STEP 4 is done.

---

## STEP 0 — Confirm the project, and capture the before-state (READ-ONLY)

In the project selector, confirm it reads **business-hero (`oxblcmwhuwtobdhsfgyi`)**, not staging. Then:

```sql
SELECT current_database(),
       (SELECT count(*) FROM public.businesses)       AS businesses,
       (SELECT count(*) FROM public.business_members) AS members,
       to_regclass('public.aria_actions') IS NOT NULL  AS already_there,
       (SELECT count(*) FROM pg_proc
         WHERE proname IN ('is_business_member', 'is_platform_admin')
           AND pronamespace = 'public'::regnamespace)   AS policy_functions;
```

**EXPECT:**
- `postgres`;
- businesses **8** and members **5** (as at 034), or more if you've added any since;
- `already_there` = **false**;
- `policy_functions` = **2**.

**STOP IF:**
- members is 0 (that is staging);
- `already_there` is true;
- `policy_functions` is not 2 (the read policy depends on both functions).

Send me the row either way. It is the before-snapshot.

---

## STEP 1 — Apply SECTION 1

Paste **only** SECTION 1 from the migration file, from its first `BEGIN;` to
its `COMMIT;`. It covers the table, two CHECKs, one index, RLS, one read
policy and the grants.

**EXPECT:** "Success. No rows returned."

**STOP IF:** any error. Nothing will have changed, because it is one
transaction. Send me the error.

---

## STEP 2 — VERIFY (READ-ONLY)

```sql
SELECT
  (SELECT count(*) FROM information_schema.columns
    WHERE table_schema='public' AND table_name='aria_actions')              AS columns,
  (SELECT relrowsecurity FROM pg_class
    WHERE oid='public.aria_actions'::regclass)                              AS rls_on,
  (SELECT count(*) FROM pg_policies
    WHERE schemaname='public' AND tablename='aria_actions')                 AS policies,
  (SELECT count(*) FROM information_schema.role_table_grants
    WHERE table_schema='public' AND table_name='aria_actions'
      AND grantee='anon')                                                   AS anon_privileges,
  (SELECT string_agg(privilege_type, ',' ORDER BY privilege_type)
     FROM information_schema.role_table_grants
    WHERE table_schema='public' AND table_name='aria_actions'
      AND grantee='authenticated')                                          AS authenticated_privileges,
  (SELECT count(*) FROM public.aria_actions)                                AS rows;
```

**EXPECT:** `columns` **14**, `rls_on` **true**, `policies` **1**,
`anon_privileges` **0**, `authenticated_privileges` **SELECT**, `rows` **0**.

**STOP IF:** anything differs, and above all if `anon_privileges` is not 0 or
`authenticated_privileges` is anything other than `SELECT`. In that case run
STEP 5 and send me the output.

---

## STEP 3 — The once-only check (wrapped, never commits)

```sql
BEGIN;
  INSERT INTO public.aria_actions (id, business_id, action_type, payload, expires_at)
  VALUES ('00000000-0000-4000-8000-000000000035',
          (SELECT id FROM public.businesses LIMIT 1), 'create_task',
          '{"title":"runbook check"}', now() + interval '1 hour');
  UPDATE public.aria_actions SET status = 'executing'
   WHERE id = '00000000-0000-4000-8000-000000000035'
     AND status = 'proposed' AND expires_at > now();
  UPDATE public.aria_actions SET status = 'executing'
   WHERE id = '00000000-0000-4000-8000-000000000035'
     AND status = 'proposed' AND expires_at > now();
ROLLBACK;
```

**EXPECT:** it runs without error. The editor shows only the last statement's
result (the ROLLBACK). This proves the shape works in production; staging
proved the 1-then-0 row counts.

Then re-run STEP 2's query: `rows` must still be **0**.

---

## STEP 4 — Regenerate the schema dump (READ-ONLY)

This is what lets the NS-B10 code pass its safety check.

1. Confirm the project selector still reads `oxblcmwhuwtobdhsfgyi`.
2. **Set the SQL editor's row limit to "No limit"**, then run the whole of
   `scripts/dump-live-schema.sql`.
3. **Download → CSV**, and drag the file into the repo folder as you did for 034.

It should hold about **832 rows**: the previous 818 plus the 14 new columns.
If it holds 100, the limit was on.

---

## STEP 5 — ROLLBACK (only if STEP 2 failed)

```sql
BEGIN;
DROP TABLE IF EXISTS public.aria_actions;
COMMIT;
```

Then re-run STEP 0's query: `already_there` should be **false**. On staging
this restored the before-state exactly.

---

## Afterwards

Send me STEP 0's row and STEP 2's row, and drag in the CSV. I will then:
1. regenerate `audits/live-schema-public.txt`;
2. record the run here;
3. finish the NS-B10 code against it for review.
