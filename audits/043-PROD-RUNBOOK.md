# 043 — PRODUCTION RUNBOOK: receptionist number requests (Mike's steps)

**For:** Mike. **Ticket:** RCP-1 (`docs/RCP-1-TICKET.md`). **Migration:** `backend/migrations/043_receptionist_number_requests.sql`.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`), 13 Nov 2026:
- STEP 0 found no duplicate numbers;
- applied it, and STEP 2 matched: both indexes present, row-level security on, no client access, columns +34;
- rolled it back with the block below, then applied it twice (the second run changes nothing).

The PostgreSQL tests in `backend/tests/test_receptionist_numbers_pg.py` pass against it. They cover:
- both unique indexes;
- the full request → approve → live flow;
- two approves racing, which buy one number;
- two purchases at once, which record the exact combined monthly cost;
- onboarding's own write of a taken number, which is a 409.

**Staging first (AGENTS.md §7):**
1. Run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again there.
2. Only then repeat STEPS 0–2 on production.
3. Send me the staging outputs and I'll record them in `audits/043-STAGING-REHEARSAL.md`.

**What it does:**
- **One number, one business.** It adds a unique index on `receptionist_configs.twilio_phone_number`. Until now, nothing stopped the same number being given to two businesses, and its calls would then go to whichever one the database found first.
- **Adds one empty, backend-only table, `receptionist_number_requests`.** It holds each owner's request:
  - the business's legal name and address, for the UK regulator;
  - the number once bought;
  - the claim that stops a second purchase.
- **Changes no existing row.**

**Risk:** RED, as all production SQL is. Low in practice: one new empty table and one index on a small table. It waits at most 5 seconds for a lock and stops at 120 seconds. It takes about 5 minutes.

**When:** **before** merging the RCP-1 PR. Without the table, the owner's page says requests "aren't switched on yet", and your admin card shows the same.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start, confirm the project selector reads:**
- for the staging rehearsal, **staging (`gzcrsrqmygublveuzqyg`)**;
- for the production run, **business-hero (`oxblcmwhuwtobdhsfgyi`)**.

---

## STEP 0 — Read-only check

```sql
SELECT current_database(),
       to_regclass('public.receptionist_number_requests') AS requests_before,
       (SELECT count(*) FROM (SELECT twilio_phone_number FROM public.receptionist_configs
          WHERE twilio_phone_number IS NOT NULL GROUP BY 1 HAVING count(*) > 1) d) AS duplicate_numbers,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `postgres`;
- `requests_before` **NULL**;
- `duplicate_numbers` **0**;
- note `policies` (P) and `columns` (C).

**STOP IF:**
- `requests_before` is not NULL; or
- `duplicate_numbers` is more than 0. In that case, send me the output. The index can't be created until each number has one owner, and I'll give you a read-only query listing them.

---

## STEP 1 — Create (one transaction)

Open **`backend/migrations/043_receptionist_number_requests.sql`**, select all and copy it (about 65 lines). Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.*

**STOP IF:** any error, including `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT (SELECT count(*) FROM pg_indexes WHERE indexname IN
          ('uq_receptionist_configs_twilio_phone_number', 'uq_receptionist_number_requests_open')) AS indexes,
       (SELECT relrowsecurity FROM pg_class WHERE relname = 'receptionist_number_requests') AS requests_rls,
       (SELECT count(*) FROM information_schema.role_table_grants
          WHERE table_name = 'receptionist_number_requests'
            AND grantee IN ('anon', 'authenticated', 'service_role')) AS client_grants,
       (SELECT count(*) FROM public.receptionist_number_requests) AS rows,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public') AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `indexes` = **2**;
- `requests_rls` **true**;
- `client_grants` **0**;
- `rows` **0**;
- `policies` = P, unchanged (no policy: backend only, as 041 and 042);
- `columns` = C + **34** (measured on the local harness).

**STOP IF:** any differs.

---

## ROLLBACK (staging rehearsal only, or if told to)

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DROP TABLE IF EXISTS public.receptionist_number_requests;
DROP INDEX IF EXISTS public.uq_receptionist_configs_twilio_phone_number;
COMMIT;
SELECT to_regclass('public.receptionist_number_requests') AS requests_gone,
       to_regclass('public.uq_receptionist_configs_twilio_phone_number') AS index_gone;
```

**EXPECT:** both **NULL**.

**This is for the staging rehearsal. Don't run it on production.** Once the RCP-1 code is live, the table is the only record of which Twilio number was bought for which request. Dropping it would lose that record, while you'd still be paying for the numbers.

**If it times out on a lock:** nothing changed. Run it again in a quiet minute.

---

## After merging: MSC's number

1. In Business Hero, as MSC: **AI hub → Receptionist → Phone number**. Choose *keep my existing number* or *a new local number*, fill in MSC's legal name and address, then click **Request my number**.
2. In Twilio: **Phone Numbers → Regulatory Compliance**. Create an **address** and a **bundle** for MSC (UK, local, business) with the same details. Twilio checks the bundle; this can take a few working days.
3. In Business Hero admin, the **Receptionist number requests** card (on the dashboard): paste the bundle and address SIDs, then click **Check**.
   - If the bundle is approved, local numbers in the area appear, with Twilio's monthly price.
   - If not, the request shows *Waiting for UK approval*. Click **Check** again later.
4. Choose a number, then click **Buy and set up**, and confirm. The card goes to *Live*.
5. As MSC, switch the receptionist on, and ring the number to test it. If you chose to keep MSC's existing number, the page shows the forwarding steps for MSC's provider.

**Railway:**
- `PUBLIC_BASE_URL` must be the API's https address. It already is: the call signature check uses it.
- `RECEPTIONIST_GBP_PER_USD` (optional) converts Twilio's price if your Twilio account is billed in dollars. Without it, the default is 0.85: deliberately a little high, so a cost is never under-recorded. If the account is billed in pounds, nothing is converted.

**The monthly cost** of each number comes from Twilio's own price list. It's recorded as one running-costs line, "Receptionist numbers", from the month the number is bought. Each request also records its business and price. If you already enter a "Twilio" bill by hand, it will include these numbers, so remove them from that figure to avoid counting them twice.
