# 040 — PRODUCTION RUNBOOK: outreach card lookup index (Mike's steps)

**For:** Mike. **Ticket:** OUT-24. **Migration:** `backend/migrations/040_outreach_card_lookup.sql`.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`), which replays every migration and matches production's policies.
- The index was created with the exact definition STEP 2 expects.
- The PostgreSQL tests in `backend/tests/test_outreach_send_rls.py` pass against it, including two cards asked for at the same moment making exactly one.

**Staging first (AGENTS.md §7):**
1. Run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again there.
2. Only then repeat STEPS 0–2 on production.
3. Send me the staging outputs and I'll record them in `audits/040-STAGING-REHEARSAL.md`.

**What it does:**
- adds one index to `aria_actions`, so an outreach email's card is found by its contact rather than by reading every open card;
- changes no data, table, policy or permission.

**Why:** it is the last step before the limit of **5 contacts per campaign** can be lifted (STEP 3). With an inbox at 5 a day, that limit fills a campaign on day one, and nothing new is emailed until those sequences finish.

**Risk:** RED, as all production SQL is. Low in practice: an index only. It waits at most 5 seconds for its lock and stops at 60 seconds. It takes about 5 minutes.

**When:** any time. The index does nothing harmful before the OUT-24 code is live. **STEP 3 waits** until the OUT-24 PR is merged and deployed and STEPS 0–2 are done on production.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start, confirm the project selector reads:**
- for the staging rehearsal, **staging (`gzcrsrqmygublveuzqyg`)**;
- for the production run, **business-hero (`oxblcmwhuwtobdhsfgyi`)**.

---

## STEP 0 — Read-only check

```sql
SELECT current_database(),
       to_regclass('public.idx_aria_actions_outreach_enrolment') AS index_before,
       (SELECT count(*) FROM public.aria_actions WHERE action_type = 'send_outreach') AS outreach_cards,
       (SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'aria_actions') AS indexes_before;
```

**EXPECT:**
- `postgres`;
- `index_before` **NULL**;
- `outreach_cards` is any number (note it);
- `indexes_before` is a number (call it I).

**STOP IF:** `index_before` isn't NULL.

---

## STEP 1 — Create the index (one transaction)

Open **`backend/migrations/040_outreach_card_lookup.sql`**, select all and copy it (about 15 lines). Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.*

**STOP IF:** any error, including `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error; a lock timeout only means try again in a quiet minute.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT indexdef,
       (SELECT indisvalid FROM pg_index WHERE indexrelid = 'public.idx_aria_actions_outreach_enrolment'::regclass) AS valid,
       (SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'aria_actions') AS indexes_after
FROM pg_indexes WHERE indexname = 'idx_aria_actions_outreach_enrolment';
```

**EXPECT:** one row:
- `indexdef` reads exactly:
  `CREATE INDEX idx_aria_actions_outreach_enrolment ON public.aria_actions USING btree (business_id, ((payload ->> 'enrolment_id'::text))) WHERE (action_type = 'send_outreach'::text)`
- `valid` = **true**;
- `indexes_after` = I + 1.

**STOP IF:** no row, `valid` false, or a different definition.

---

## ROLLBACK (staging rehearsal only, or if told to)

Run this as one block. Like STEP 1, it waits at most 5 seconds for its lock, so other work can queue behind it for no more than those 5 seconds (Codex OUT-24 reviews 1 and 2).

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DROP INDEX IF EXISTS public.idx_aria_actions_outreach_enrolment;
COMMIT;
SELECT to_regclass('public.idx_aria_actions_outreach_enrolment') AS gone;
```

**EXPECT:** `gone` **NULL**. Nothing else depends on the index; the code works without it, only more slowly.

**If it says `canceling statement due to lock timeout`:** nothing changed, and the index is still there. Check with `SELECT to_regclass('public.idx_aria_actions_outreach_enrolment');`, which should return the name. Run the block again in a quiet minute.

---

## STEP 3 — Lift the limit of 5 (Railway, after production STEPS 0–2 and the OUT-24 deploy)

In Railway → the backend service → **Variables**, add:

```
OUTREACH_PILOT_ENROLMENTS = 0
```

Railway redeploys by itself.

**`0` means no pilot limit:** each campaign then takes as many contacts as its inbox's warm-up allows (5 a day at first, then 10, then 20). Every email still waits for your tap, unless you have switched on Aria sending by herself.

**To put a limit back:** set the variable to a number, for example `20`. Removing the variable returns it to 5.

**EXPECT** (Codex OUT-24 review 1, finding 4: the limit was on the **total** in a campaign, not each day's intake):
- Each morning's research still keeps at most what the inbox can email that day: 5 a day at first, less any follow-ups due and contacts still waiting for their first email.
- What changes is the **total**. Within a few days the campaign shows **more than 5 active contacts**, where before it stopped at 5 until sequences finished.
- **Before:** day 1 adds 5, and days 2 onwards add 0.
- **After:** day 1 adds 5, and following days keep adding while the inbox has room.
