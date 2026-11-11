# 041 — PRODUCTION RUNBOOK: outreach erasure tables (Mike's steps)

**For:** Mike. **Ticket:** OUT-13 core. **Migration:** `backend/migrations/041_outreach_erasure.sql`.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`): applied, rolled back with the block below, and applied again. The PostgreSQL tests in `backend/tests/test_outreach_erasure_pg.py` pass against it. They cover:
- erasure in foreign-key order;
- a contact who was emailed is never erased;
- an uncertain send is kept and listed;
- both new tables have row-level security on and no client access.

**Staging first (AGENTS.md §7):**
1. Run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again there.
2. Only then repeat STEPS 0–2 on production.
3. Send me the staging outputs and I'll record them in `audits/041-STAGING-REHEARSAL.md`.

**What it does:**
- adds two indexes on `outreach_prospects`, for the hourly list of contacts past their deadline;
- adds two empty, backend-only tables:
  - `outreach_recently_erased`: scrambled fingerprints that stop an erased contact being collected again for 90 days;
  - `outreach_erasure_exceptions`: contacts whose erasure is held, with the reason (for example, an email may have been sent);
- **changes no existing row.**

**Why:** a researched contact who is never emailed must not be kept beyond 28 days (UK GDPR Article 14). Today they are kept for 365 days.

**Risk:** RED, as all production SQL is. Low in practice: indexes and empty tables. It waits at most 5 seconds for a lock and stops at 120 seconds. It takes about 5 minutes.

**When:** **before** merging the OUT-13 core PR. Without these tables the hourly erasure pass logs an error and does nothing, and research fails its new check.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start, confirm the project selector reads:**
- for the staging rehearsal, **staging (`gzcrsrqmygublveuzqyg`)**;
- for the production run, **business-hero (`oxblcmwhuwtobdhsfgyi`)**.

---

## STEP 0 — Read-only check

```sql
SELECT current_database(),
       to_regclass('public.outreach_recently_erased') AS guard_before,
       to_regclass('public.outreach_erasure_exceptions') AS exceptions_before,
       to_regclass('public.idx_outreach_prospects_uncontacted_captured') AS index_before,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns,
       (SELECT count(*) FROM public.outreach_prospects WHERE notice_provided_at IS NULL
          AND captured_at <= now() - interval '28 days') AS past_deadline_now;
```

**EXPECT:**
- `postgres`;
- `guard_before`, `exceptions_before` and `index_before` all **NULL**;
- note `policies` (P), `columns` (C) and `past_deadline_now` (D).

D is how many researched contacts are already past 28 days and never emailed. They will be erased within about an hour of the OUT-13 core deploy.

**STOP IF:** any of the three is not NULL.

---

## STEP 1 — Create (one transaction)

Open **`backend/migrations/041_outreach_erasure.sql`**, select all and copy it (about 55 lines). Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.*

**STOP IF:** any error, including `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT (SELECT count(*) FROM pg_indexes WHERE indexname IN
          ('idx_outreach_prospects_uncontacted_captured', 'idx_outreach_prospects_uncontacted_notice',
           'idx_outreach_recently_erased_until', 'idx_outreach_erasure_exceptions_checked')) AS indexes,
       (SELECT relrowsecurity FROM pg_class WHERE relname = 'outreach_recently_erased') AS guard_rls,
       (SELECT relrowsecurity FROM pg_class WHERE relname = 'outreach_erasure_exceptions') AS exceptions_rls,
       (SELECT count(*) FROM information_schema.role_table_grants
          WHERE table_name IN ('outreach_recently_erased', 'outreach_erasure_exceptions')
            AND grantee IN ('anon', 'authenticated', 'service_role')) AS client_grants,
       (SELECT count(*) FROM public.outreach_recently_erased) + (SELECT count(*) FROM public.outreach_erasure_exceptions) AS rows,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `indexes` = **4**;
- `guard_rls` and `exceptions_rls` **true**;
- `client_grants` **0**;
- `rows` **0**;
- `policies` = P, unchanged (no policy: backend only, as 039);
- `columns` = C + **16** (8 in each new table; measured on the local harness).

**STOP IF:** any differs.

---

## ROLLBACK (staging rehearsal only, or if told to)

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DROP TABLE IF EXISTS public.outreach_erasure_exceptions;
DROP TABLE IF EXISTS public.outreach_recently_erased;
DROP INDEX IF EXISTS public.idx_outreach_prospects_uncontacted_notice;
DROP INDEX IF EXISTS public.idx_outreach_prospects_uncontacted_captured;
COMMIT;
SELECT to_regclass('public.outreach_recently_erased') AS guard_gone,
       to_regclass('public.idx_outreach_prospects_uncontacted_captured') AS index_gone;
```

**EXPECT:** both **NULL**.

Only roll back **before** the OUT-13 core code is live. Once it is, the guard rows stop an erased contact being collected again, so dropping the table would lose that.

**If it times out on a lock:** nothing changed. Run it again in a quiet minute.
