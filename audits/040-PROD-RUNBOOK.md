# 040 — PRODUCTION RUNBOOK: single-use OAuth sign-in states (Mike's steps)

**For:** Mike. **Ticket:** TRADE-0 §3. **Migration:** `backend/migrations/040_oauth_states.sql`.

**Rehearsed locally:** applied to the local PostgreSQL harness, a replay of every migration that matches production's policies (`scripts/rls-local.sh`, which now includes 040). The PostgreSQL tests in `backend/tests/test_oauth_state_pg.py` pass against it. They cover:
- no client role (anon, authenticated) can read or write the table;
- the constraints refuse a bad provider, a bad hash and an expiry before creation;
- a state for a business that doesn't exist is refused;
- two callbacks racing on one state: exactly one wins.

**Staging first (AGENTS.md §7):** run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again there. Only then run STEPS 0–2 on production. Send me the staging outputs and I'll record them in `audits/040-STAGING-REHEARSAL.md`.

**What it does:**
- creates one empty table, `oauth_states`;
- each time you start connecting Xero, FreeAgent, QuickBooks, Google or Microsoft, Business Hero stores a one-time token (only its fingerprint, never the token itself), tied to you, your business, the provider and the purpose;
- when the provider sends you back, the token is used once, must not have expired (10 minutes), and you must *still* own the business. Only then are any credentials saved;
- only the backend can use the table: every client role has its access removed, and row-level security is on;
- nothing existing changes.

**Why:** before this, the accounting providers' link carried the encrypted business id with no expiry and no person, and the email link could be reused within ten minutes. Neither checked that the person who started the connection still owned the business.

**Risk:** RED, as all production SQL is. Low in practice: it only adds an empty table. It takes about 5 minutes.

**When: BEFORE the TRADE-0 PR is merged and deployed.** Once TRADE-0 is live, connecting or reconnecting Xero or email needs this table. If the table were missing, starting a connection would fail with an error. Nothing would be harmed, but you couldn't connect until it's added.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start, confirm the project selector reads:**
- for the staging rehearsal, **staging (`gzcrsrqmygublveuzqyg`)**;
- for the production run, **business-hero (`oxblcmwhuwtobdhsfgyi`)**.

---

## STEP 0 — Read-only check

```sql
SELECT current_database(),
       to_regclass('public.oauth_states') AS oauth_states_before,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public') AS columns;
```

**EXPECT:** `postgres`; `oauth_states_before` **NULL**. Note `policies` and `columns` (call them P and C).

**STOP IF:** `oauth_states_before` isn't NULL.

---

## STEP 1 — Create the table (one transaction)

Open **`backend/migrations/040_oauth_states.sql`**, then select all and copy it (about 25 lines). Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.* **STOP IF:** any error. Because it's one transaction, nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT to_regclass('public.oauth_states') AS oauth_states,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='oauth_states') AS state_columns,
       (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.oauth_states'::regclass) AS rls_on,
       (SELECT count(*) FROM pg_policies WHERE tablename = 'oauth_states') AS state_policies,
       (SELECT count(*) FROM information_schema.role_table_grants
         WHERE table_name = 'oauth_states' AND grantee IN ('anon', 'authenticated', 'service_role')) AS client_grants,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public') AS columns,
       (SELECT string_agg(pg_get_constraintdef(oid), ' | ' ORDER BY conname)
          FROM pg_constraint WHERE conrelid = 'public.oauth_states'::regclass) AS constraints;
```

**EXPECT:**
- `oauth_states` = `oauth_states`;
- `state_columns` **9**;
- `rls_on` **true**;
- `state_policies` **0**;
- `client_grants` **0**;
- `policies` = **P** (unchanged);
- `columns` = **C + 9**;
- `constraints` contains all seven of these, exactly as PostgreSQL prints them (checked against the local replay):
  - `FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE`;
  - `CHECK ((expires_at > created_at))`;
  - `CHECK (((length(operation) >= 1) AND (length(operation) <= 60)))`;
  - `PRIMARY KEY (id)`;
  - `CHECK ((provider = ANY (ARRAY['google'::text, 'microsoft'::text, 'xero'::text, 'freeagent'::text, 'quickbooks'::text])))`;
  - `CHECK ((token_hash ~ '^[0-9a-f]{64}$'::text))`;
  - `UNIQUE (token_hash)`.

**STOP IF:** anything differs. Send me the row; see ROLLBACK below.

---

## ROLLBACK (only if STEP 2 failed, or I ask; on staging, as part of the rehearsal)

Before TRADE-0 is deployed the table is empty. After deployment it only holds in-progress connection attempts (each expires in 10 minutes), so dropping it loses nothing important. **Once TRADE-0 is deployed, though, connecting Xero or email needs the table, so don't drop it on production without asking me.**

```sql
DROP TABLE IF EXISTS public.oauth_states;
```

**EXPECT:** *Success.* Then re-run STEP 0: `oauth_states_before` is NULL again, and `columns` is back to C.

---

## After it's applied
1. Tell me, and I'll record the run and update the schema record.
2. Then merge the TRADE-0 PR (once its review is done) and let Railway deploy.
3. Check: Accounting → reconnect Xero (or Settings → Email → connect) works as before.
