# 039 — PRODUCTION RUNBOOK: platform meters (Mike's steps)

**For:** Mike. **Ticket:** PROFIT-1. **Migration:** `backend/migrations/039_platform_meters.sql`.

**Rehearsed locally:** applied to the local PostgreSQL harness, a replay of every migration that matches production's policies (`scripts/rls-local.sh`). The PostgreSQL tests in `backend/tests/test_profit_guard_pg.py` pass against it. They cover:
- row-level security on with no policies, and no client role able to read it;
- bad rows refused: a bad month, an empty meter name, a negative value;
- the rollback, rehearsed inside a transaction that is undone;
- the accounting and alerts themselves.

**Staging first (AGENTS.md §7):** run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again there. Only then repeat STEPS 0–2 on production. Send me the three staging outputs and I'll record them in `audits/039-STAGING-REHEARSAL.md`.

**What it does:**
- creates one empty table, `platform_meters`. It holds AI costs that no business owns, plus the profit guard's "alert already sent this month" markers;
- only the backend can use it: every client role has its access removed, and row-level security is on;
- nothing existing changes.

**Why:** `usage_meters.business_id` must be a real business, so platform-level costs can't go there.

**Risk:** RED, as all production SQL is. Low in practice: it only adds an empty table. It takes about 5 minutes.

**When:** **before** merging the PROFIT-1 PR. If PROFIT-1 runs without the table, it is still safe, but it can't mark or send its alerts and logs an error saying so.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start, confirm the project selector reads:**
- for the staging rehearsal, **staging (`gzcrsrqmygublveuzqyg`)**;
- for the production run, **business-hero (`oxblcmwhuwtobdhsfgyi`)**.

Each step below is run in whichever one you're on.

---

## STEP 0 — Read-only check

```sql
SELECT current_database(),
       to_regclass('public.platform_meters') AS platform_meters_before,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public') AS columns;
```

**EXPECT:** `postgres`; `platform_meters_before` **NULL**. Note `policies` and `columns` (call them P and C); STEP 2 compares against them.

**STOP IF:** `platform_meters_before` isn't NULL.

---

## STEP 1 — Create the table (one transaction)

Open **`backend/migrations/039_platform_meters.sql`**, then select all and copy it (about 20 lines). Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.* **STOP IF:** any error. Because it's one transaction, nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT to_regclass('public.platform_meters') AS platform_meters,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='platform_meters') AS meter_columns,
       (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.platform_meters'::regclass) AS rls_on,
       (SELECT count(*) FROM pg_policies WHERE tablename = 'platform_meters') AS meter_policies,
       (SELECT count(*) FROM information_schema.role_table_grants
         WHERE table_name = 'platform_meters' AND grantee IN ('anon', 'authenticated', 'service_role')) AS client_grants,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public') AS columns,
       (SELECT string_agg(pg_get_constraintdef(oid), ' | ' ORDER BY conname)
          FROM pg_constraint WHERE conrelid = 'public.platform_meters'::regclass) AS constraints;
```

**EXPECT:**
- `platform_meters` = `platform_meters`;
- `meter_columns` **4** (`period` must be a real month; `value` can't be negative);
- `rls_on` **true**;
- `meter_policies` **0**;
- `client_grants` **0**;
- `policies` = **P** (unchanged);
- `columns` = **C + 4**;
- `constraints` contains all four of these, exactly as PostgreSQL prints them (checked against the local replay):
  - `CHECK (((length(meter) >= 1) AND (length(meter) <= 200)))`;
  - `CHECK ((period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'::text))`;
  - `CHECK ((value >= (0)::numeric))`;
  - `PRIMARY KEY (period, meter)`.

**STOP IF:** anything differs. Send me the row; see ROLLBACK below.

---

## ROLLBACK (only if STEP 2 failed, or I ask; on staging, as part of the rehearsal)

Before PROFIT-1 is deployed the table is empty, so dropping it loses nothing. **After deployment it holds this month's platform costs and alert markers;** dropping it then loses them, so ask me first.

```sql
DROP TABLE IF EXISTS public.platform_meters;
```

**EXPECT:** *Success.* Then re-run STEP 0: `platform_meters_before` is NULL again, and `columns` is back to C.

---

## After it's applied
1. Merge the PROFIT-1 PR and let Railway deploy.
2. Set the Railway variables in the PR description: the trial budget, fixed costs and the alert mailbox.
3. Open **Admin → Running costs against income**. It should show this month's costs and income, with no error.
