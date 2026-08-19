# 030a — PROD RUNBOOK

Rehearsed on staging 17 Aug. All 5 sections applied and verified; 3 rollback
bugs found and fixed. Commit `a570ac5`.

## How to use this

Work top to bottom. Do not skip. Do not batch.

For every step: paste the SQL, read the result, compare to **EXPECT**.
If it doesn't match EXPECT — **STOP**. Paste the output to Claude Code and
say "prod 030a step N mismatch". Do not continue and do not improvise.

Steps 0 and 1 are read-only. Nothing changes until Step 2.

---

## STEP 0 — Prod before-snapshot (READ-ONLY)

This is what a rollback would be diffed against. Do not skip it.

```sql
SELECT 'GRANT' AS kind, table_name || ' | ' || grantee AS obj, privilege_type AS detail
  FROM information_schema.role_table_grants
 WHERE table_schema='public'
   AND table_name IN ('businesses','business_members','stripe_events')
   AND grantee IN ('anon','authenticated')
UNION ALL
SELECT 'COLGRANT', table_name || ' | ' || grantee || ' | ' || column_name, privilege_type
  FROM information_schema.column_privileges
 WHERE table_schema='public' AND table_name='business_members'
   AND grantee IN ('anon','authenticated') AND privilege_type='UPDATE'
UNION ALL
SELECT 'POLICY', tablename || ' | ' || policyname || ' | ' || cmd,
       coalesce(qual,'~') || ' ||WC|| ' || coalesce(with_check,'~')
  FROM pg_policies
 WHERE schemaname='public'
   AND tablename IN ('businesses','business_members','stripe_events')
UNION ALL
SELECT 'FUNC', proname, pg_get_functiondef(p.oid)
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND proname IN ('is_business_member','is_platform_admin')
ORDER BY 1,2,3;
```

**DO THIS:** click Export → CSV. Save it. Name it `030a-prod-before.csv`.

**EXPECT:** roughly 40–60 rows. If you get zero rows, you are in the wrong
project — go to Step 1.

---

## STEP 1 — Confirm the project (READ-ONLY)

Three Supabase projects exist across two orgs. This is the single easiest
way to cause damage today.

**DO THIS:** look at the browser address bar. It must contain:

```
oxblcmwhuwtobdhsfgyi
```

- `gzcrsrqmygublveuzqyg` = staging. WRONG for this runbook.
- Anything else = Trackwise or FitFutures. WRONG.

Then confirm with SQL:

```sql
SELECT count(*) AS tables, (SELECT count(*) FROM public.business_members) AS members
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind='r';
```

**EXPECT:** `tables = 55` and `members = 5`.

**STOP IF:** members = 0 → that's staging. Switch projects and redo Step 0.

---

## STEP 2 — Section 1: remove anon write privilege

Nothing before this point changed anything. This is the first write.

```sql
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES
  ON public.businesses       FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES
  ON public.business_members FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES
  ON public.stripe_events    FROM anon;
```

Verify:

```sql
SELECT table_name, privilege_type
  FROM information_schema.role_table_grants
 WHERE table_schema='public' AND grantee='anon'
   AND table_name IN ('businesses','business_members','stripe_events')
 ORDER BY table_name, privilege_type;
```

**EXPECT:** only `SELECT` and `TRIGGER` for each of the three tables.
6 rows total.

**STOP IF:** you see INSERT, UPDATE, DELETE, TRUNCATE or REFERENCES.

---

## STEP 3 — Section 2: close the cross-tenant pivot

```sql
REVOKE UPDATE ON public.business_members FROM authenticated;
GRANT  UPDATE (user_id, accepted_at) ON public.business_members TO authenticated;
```

Verify:

```sql
SELECT column_name FROM information_schema.column_privileges
 WHERE table_schema='public' AND table_name='business_members'
   AND grantee='authenticated' AND privilege_type='UPDATE'
 ORDER BY column_name;
```

**EXPECT:** exactly 2 rows — `accepted_at`, `user_id`.

```sql
SELECT privilege_type FROM information_schema.role_table_grants
 WHERE table_schema='public' AND table_name='business_members'
   AND grantee='authenticated' ORDER BY privilege_type;
```

**EXPECT:** `INSERT` present. `UPDATE` **absent**.

**STOP IF:** INSERT is missing — the admin invite feature depends on it.

---

## STEP 4 — Section 3: make is_active actually revoke access

This is the highest-consequence step. This function gates 45 tables.

```sql
CREATE OR REPLACE FUNCTION public.is_business_member(p_user_id uuid, p_business_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $function$
  select exists (
    select 1
    from public.business_members bm
    where bm.user_id = p_user_id
      and bm.business_id = p_business_id
      and bm.is_active = true
  );
$function$;
```

Verify — all three in one go:

```sql
SELECT
  (SELECT count(*) FROM public.business_members WHERE is_active = false) AS inactive_members,
  public.is_business_member(
    (SELECT user_id     FROM public.business_members
      WHERE user_id IS NOT NULL AND is_active LIMIT 1),
    (SELECT business_id FROM public.business_members
      WHERE user_id IS NOT NULL AND is_active LIMIT 1)
  ) AS real_member_still_works;
```

**EXPECT:** `inactive_members = 0` and `real_member_still_works = true`.

### STOP IF `real_member_still_works` IS NOT true

This means live customers are about to lose access to 45 tables.
Roll back immediately — paste this and nothing else:

```sql
CREATE OR REPLACE FUNCTION public.is_business_member(p_user_id uuid, p_business_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $function$
  select exists (select 1 from public.business_members bm
    where bm.user_id = p_user_id and bm.business_id = p_business_id);
$function$;
```

Then re-run the verify. `real_member_still_works` must return to `true`.
Then stop and report.

---

## STEP 5 — Section 4: stripe_events becomes backend-only

```sql
DROP POLICY IF EXISTS stripe_events_member_access ON public.stripe_events;
REVOKE ALL ON public.stripe_events FROM anon;
REVOKE ALL ON public.stripe_events FROM authenticated;
```

Verify:

```sql
SELECT (SELECT count(*) FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='stripe_events'
           AND grantee IN ('anon','authenticated')) AS leftover_grants,
       (SELECT count(*) FROM pg_policies
         WHERE schemaname='public' AND tablename='stripe_events') AS leftover_policies;
```

**EXPECT:** both `0`.

---

## STEP 6 — Section 5: collapse policy sprawl on businesses

Optional. Skip if you want a smaller blast radius today; Steps 2–5 do not
depend on it.

```sql
DROP POLICY IF EXISTS "Members can select their own businesses"   ON public.businesses;
DROP POLICY IF EXISTS "Members can view their business"           ON public.businesses;
DROP POLICY IF EXISTS "Users can view their businesses"           ON public.businesses;
DROP POLICY IF EXISTS "members can read their businesses"         ON public.businesses;
DROP POLICY IF EXISTS "Platform admins can view all businesses"   ON public.businesses;
DROP POLICY IF EXISTS "Platform admins full access to businesses" ON public.businesses;
```

Verify:

```sql
SELECT policyname, cmd FROM pg_policies
 WHERE schemaname='public' AND tablename='businesses'
 ORDER BY cmd, policyname;
```

**EXPECT:** exactly 3 rows —
`Platform admins can manage all businesses` (ALL),
`biz_select_if_member` (SELECT),
`biz_update_if_owner` (UPDATE).

**STOP IF:** `biz_select_if_member` is missing. Customers cannot read their
own business. Roll back with the CREATE POLICY block in the migration file
and report.

---

## STEP 7 — Browser smoke test (THE REAL TEST)

SQL verifies prove the objects changed. These prove the app still works.
Items 4–6 are the ones 030a could plausibly break.

| # | Test | Pass looks like |
|---|------|-----------------|
| 1 | Business dashboard loads | business name + data render, no white screen |
| 2 | Branding settings loads and saves | save succeeds, reload keeps the change |
| 3 | Billing settings shows the right plan | correct plan tier, no error |
| 4 | **Admin: invite a member** | invite succeeds — this is the INSERT grant |
| 5 | **Accept an invite on a fresh login** | second account links successfully |
| 6 | **Stripe test webhook** | a new `stripe_events` row appears |

For 6:

```sql
SELECT count(*) AS rows, max(created_at) AS newest FROM public.stripe_events;
```

Fire a test event from the Stripe dashboard, re-run, confirm the count rose.

**If 4 or 5 fails:** roll back Step 3 only —

```sql
REVOKE UPDATE (user_id, accepted_at) ON public.business_members FROM authenticated;
GRANT UPDATE ON public.business_members TO authenticated;
```

**If 6 fails:** roll back Step 5 using ROLLBACK 4 in the migration file.

---

## STEP 8 — Record it

```
cd ~/Documents/business-hero-2 && mv ~/Downloads/030a-prod-before.csv audits/
```

Then have Claude Code append to `audits/FINDINGS.md`: date applied, which
sections, verify results, smoke test results, anything skipped.

Prod and the migration file are now in step. Next: 030b — move the four
admin `businesses` writes to backend endpoints, narrow the two `select('*')`
queries, then revoke UPDATE on `businesses` and close the paywall bypass.
