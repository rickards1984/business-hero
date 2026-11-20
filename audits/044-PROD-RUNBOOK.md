# 044 — PRODUCTION RUNBOOK: let edited outreach wording reach people mid-campaign (Mike's steps)

**For:** Mike. **Ticket:** OUT-28a fix (`docs/OUT-28-TICKET.md`). **Migration:** `backend/migrations/044_outreach_wording_moves.sql`.

**Why.** On 19 Nov, saving New Body's edited emails failed with:

`ForeignKeyViolation … outreach_messages_business_id_campaign_id_sequence_version_fkey`

A rule from 037 tied every email record to its contact's *current* wording version. So a contact with any email history, even New Body's two failed sends of 11 Nov, could never move to new wording. The save was all-or-nothing, so **nothing changed**: your query showed everything still on wording v2.

**What 044 does:**
- **Removes that one rule.** Nothing else changes, and no row is touched.
- Every email record still names its contact, and still has to match the **exact wording it was sent with**. That second rule (`…_fkey1`) stays.
- The sending code still checks that the contact, campaign and wording all match before every send.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`), 20 Nov 2026:
- STEP 0 found the rule;
- applied it, and STEP 2 matched;
- ran it again: "already applied", nothing changed;
- rolled it back with the block below, then applied it again.

The PostgreSQL tests in `backend/tests/test_outreach_edit_any_time_pg.py`:
- failed **with the production error** before 044;
- pass after it, for a contact with an accepted email (as MSC's) and one with a failed email (as New Body's);
- also show that an email record still can't change the wording it was sent with.

**Risk:** RED, as all production SQL is. Low in practice: it drops one constraint and touches no data. It waits at most 5 seconds for a lock and stops at 60 seconds. It takes about 3 minutes.

**When:** **before** merging this PR. The new code doesn't need 044 to deploy, but saving edits only works once 044 is in.

**Staging first (AGENTS.md §7):**
1. On **staging (`gzcrsrqmygublveuzqyg`)**, run STEPS 0–2, then the ROLLBACK, then STEPS 0–2 again.
2. Then run STEPS 0–2 on **production (`business-hero`, `oxblcmwhuwtobdhsfgyi`)**.
3. Send me the staging outputs.

**Run each step ONE AT A TIME** in the Supabase SQL editor, and check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

---

## STEP 0 — Read-only check

```sql
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.outreach_messages'::regclass
  AND contype = 'f'
  AND pg_get_constraintdef(oid) LIKE '%sequence_version%'
ORDER BY conname;
```

**EXPECT:** two rows.
- `outreach_messages_business_id_campaign_id_sequence_version_fkey`, whose definition mentions **`outreach_enrolments`**;
- `outreach_messages_business_id_campaign_id_sequence_versio_fkey1`, whose definition mentions **`outreach_sequence_steps`**.

**STOP IF:** anything else. Send me the output.

---

## STEP 1 — Apply (one transaction)

1. Open **`backend/migrations/044_outreach_wording_moves.sql`**.
2. Select all of it (about 45 lines) and copy it.
3. Paste it into the SQL editor and run it **once**.

**EXPECT:**
- *Success. No rows returned.*
- Supabase may also show the notice `044: dropped outreach_messages_business_id_campaign_id_sequence_version_fkey`.

**STOP IF:** any error, including `expected one constraint` or `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

Run the STEP 0 query again.

**EXPECT:** **one** row, `…_sequence_versio_fkey1`, whose definition mentions `outreach_sequence_steps`.

**STOP IF:** zero rows, or the `outreach_enrolments` one is still there.

---

## ROLLBACK (staging rehearsal only)

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
ALTER TABLE public.outreach_messages
  ADD CONSTRAINT outreach_messages_business_id_campaign_id_sequence_version_fkey
  FOREIGN KEY (business_id, campaign_id, sequence_version, enrolment_id)
  REFERENCES public.outreach_enrolments (business_id, campaign_id, sequence_version, id);
COMMIT;
```

**EXPECT:** `COMMIT`. STEP 0 then shows two rows again.

**This is for the staging rehearsal. Don't run it on production.**
- Once anyone has edited wording on production, their earlier emails sit on an older version than their contact. Re-adding the rule would then fail, and that failure is the right outcome.
- If it times out on a lock, nothing changed. Run it again in a quiet minute.

---

## After merging: New Body

1. Go to **Outreach → Emails** and select New Body's campaign.
2. Press **Edit** on each email and delete "[Your Name]".
3. Press **Save and use from now on**.

**EXPECT:**
- *"Saved. 5 people already in this campaign will get the new wording from their next email."*
- Approval cards then appear straight away, on weekdays between 07:00 and 18:59 UK time.

If anything is refused now, the screen shows the real reason instead of "Unavailable".
