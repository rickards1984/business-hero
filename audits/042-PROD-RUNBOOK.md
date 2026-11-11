# 042 — PRODUCTION RUNBOOK: Hunter.io add-on tables (Mike's steps)

**For:** Mike. **Ticket:** OUT-23 Part B (Hunter.io). **Migration:** `backend/migrations/042_outreach_provider_accounts.sql`.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`): applied, rolled back with the block below, then applied twice (the second run changes nothing). The PostgreSQL tests in `backend/tests/test_outreach_hunter_pg.py` pass against it. They cover:
- both tables have row-level security on, no policies and no client access;
- connecting, disconnecting and reconnecting;
- the credit ledger;
- the first email's footer;
- every Hunter writer waiting on the business lock.

**Staging first (AGENTS.md §7):**
1. Run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again there.
2. Only then repeat STEPS 0–2 on production.
3. Send me the staging outputs and I'll record them in `audits/042-STAGING-REHEARSAL.md`.

**What it does:**
- adds two empty, backend-only tables, neither holding personal data:
  - `outreach_provider_accounts`: your Hunter connection. The key is stored encrypted, the plan, and the credits left. Disconnecting keeps the row, with the key removed;
  - `outreach_provider_charges`: one row per Hunter call, so credits are reserved before a call and settled after it. No email, domain or person is stored;
- adds two indexes on the charges table;
- **changes no existing row.**

**Why:** the Hunter key must never sit in the business settings that the app reads in many places, and every paid Hunter call must be accounted for exactly.

**Risk:** RED, as all production SQL is. Low in practice: two new empty tables. It waits at most 5 seconds for a lock and stops at 120 seconds. It takes about 5 minutes.

**When:** **before** merging the OUT-23 Part B PR. Without these tables, the Hunter settings page shows an error, and research for a brand with Hunter switched on carries on with web research only.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start, confirm the project selector reads:**
- for the staging rehearsal, **staging (`gzcrsrqmygublveuzqyg`)**;
- for the production run, **business-hero (`oxblcmwhuwtobdhsfgyi`)**.

---

## STEP 0 — Read-only check

```sql
SELECT current_database(),
       to_regclass('public.outreach_provider_accounts') AS accounts_before,
       to_regclass('public.outreach_provider_charges') AS charges_before,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `postgres`;
- `accounts_before` and `charges_before` both **NULL**;
- note `policies` (P) and `columns` (C).

**STOP IF:** either of the two is not NULL.

---

## STEP 1 — Create (one transaction)

Open **`backend/migrations/042_outreach_provider_accounts.sql`**, select all and copy it (about 70 lines). Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.*

**STOP IF:** any error, including `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT (SELECT count(*) FROM pg_indexes WHERE indexname IN
          ('idx_outreach_provider_charges_brand_period', 'idx_outreach_provider_charges_reserved')) AS indexes,
       (SELECT relrowsecurity FROM pg_class WHERE relname = 'outreach_provider_accounts') AS accounts_rls,
       (SELECT relrowsecurity FROM pg_class WHERE relname = 'outreach_provider_charges') AS charges_rls,
       (SELECT count(*) FROM information_schema.role_table_grants
          WHERE table_name IN ('outreach_provider_accounts', 'outreach_provider_charges')
            AND grantee IN ('anon', 'authenticated', 'service_role')) AS client_grants,
       (SELECT count(*) FROM public.outreach_provider_accounts) + (SELECT count(*) FROM public.outreach_provider_charges) AS rows,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `indexes` = **2**;
- `accounts_rls` and `charges_rls` **true**;
- `client_grants` **0**;
- `rows` **0**;
- `policies` = P, unchanged (no policy: backend only, as 041);
- `columns` = C + **31** (15 + 16; measured on the local harness).

**STOP IF:** any differs.

---

## ROLLBACK (staging rehearsal only, or if told to)

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DROP TABLE IF EXISTS public.outreach_provider_charges;
DROP TABLE IF EXISTS public.outreach_provider_accounts;
COMMIT;
SELECT to_regclass('public.outreach_provider_accounts') AS accounts_gone,
       to_regclass('public.outreach_provider_charges') AS charges_gone;
```

**EXPECT:** both **NULL**.

Only roll back **before** the Hunter code is live. Once it is, the charges table is the record of your Hunter credits, and dropping it loses that.

**If it times out on a lock:** nothing changed. Run it again in a quiet minute.

---

## After merging: connect Hunter for MSC

1. Sign up at hunter.io (Starter, £28/month, is enough for one brand) and copy your API key from *API* in Hunter's dashboard.
2. In Business Hero, under **Outreach → Settings → Hunter.io**, paste the key and connect.
3. Approve MSC's audience again with **Hunter.io** ticked as a source. The audience stays the same, so its campaigns carry on.
4. Confirm MSC's privacy notice names Hunter.io (suggested wording is shown), then switch Hunter on for MSC. You can set a monthly credit cap there too.
