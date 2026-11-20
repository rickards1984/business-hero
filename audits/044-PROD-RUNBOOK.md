# 044 — PRODUCTION RUNBOOK: let edited outreach wording reach people mid-campaign (Mike's steps)

**For:** Mike. **Ticket:** OUT-28a fix (`docs/OUT-28-TICKET.md`). **Migration:** `backend/migrations/044_outreach_wording_moves.sql`.

**Why.** On 19 Nov, saving New Body's edited emails failed with:

`ForeignKeyViolation … outreach_messages_business_id_campaign_id_sequence_version_fkey`

A rule from 037 tied every email record to its contact's *current* wording version. So a contact with any email history, even New Body's two failed sends of 11 Nov, could never move to new wording. The save was all-or-nothing, so **nothing changed**: your query showed everything still on wording v2.

**What 044 does:**
- **Removes that one rule.** No row is touched.
- **Corrects a related automatic step** (`outreach_bind_message_version`). It used to reset an email's wording version to its contact's current one on *every* update. After an edit, that would have broken later updates of old emails, such as settling an outcome, matching a reply, or deleting a contact's data at their deadline. Now an email keeps the version it was sent with. This was found by Codex in review 1.
- Every email record still names its contact, and still has to match the **exact wording it was sent with**. That second rule (`…_fkey1`) stays.
- The sending code still checks that the contact, campaign and wording all match before every send.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`), 20 Nov 2026:
- the harness was **built from scratch** with 044 (it is now part of `scripts/rls-local.sh up`), and all 372 PostgreSQL tests pass on it;
- STEP 0 found the rule;
- applied it, and STEP 2 matched;
- ran it again: "already applied", nothing changed;
- rolled it back with the block below, then applied it again.

The PostgreSQL tests in `backend/tests/test_outreach_edit_any_time_pg.py`:
- failed **with the production error** before 044;
- pass after it, for a contact with an accepted email (as MSC's) and one with a failed email (as New Body's);
- also show that an email record still can't change the wording it was sent with;
- after a failed send, an edit, and the contact's deadline, the contact's data is erased cleanly;
- after a failed send and an edit, the contact's next email goes out with the new wording;
- with the old automatic step put back, 5 of them fail.

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
SELECT c.conname,
       c.confrelid::regclass AS points_at,
       ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n, i)
             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n ORDER BY k.i) AS columns,
       ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(n, i)
             JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n ORDER BY k.i) AS refers_to
FROM pg_constraint c
WHERE c.conrelid = 'public.outreach_messages'::regclass AND c.contype = 'f'
  AND c.confrelid IN ('public.outreach_enrolments'::regclass, 'public.outreach_sequence_steps'::regclass)
UNION ALL
SELECT 'trigger: ' || CASE WHEN position('044' in f.prosrc) > 0 THEN 'new' ELSE 'old' END
         || CASE WHEN t.tgenabled = 'D' THEN ', DISABLED' ELSE ', enabled' END,
       NULL, NULL, NULL
FROM pg_trigger t JOIN pg_proc f ON f.oid = t.tgfoid JOIN pg_namespace n ON n.oid = f.pronamespace
WHERE t.tgrelid = 'public.outreach_messages'::regclass AND t.tgname = 'outreach_message_version'
  AND n.nspname = 'public'
ORDER BY 1;
```

**EXPECT:** these rows, in any order. Check both column lists.
- **Pointing at `outreach_enrolments`:**
  - `{business_id,enrolment_id}`, refers to `{business_id,id}`;
  - `{business_id,campaign_id,prospect_id,enrolment_id}`, refers to `{business_id,campaign_id,prospect_id,id}`;
  - **`{business_id,campaign_id,sequence_version,enrolment_id}`, refers to `{business_id,campaign_id,sequence_version,id}`**: the rule 044 removes.
- **Pointing at `outreach_sequence_steps`:** three rows, including `{business_id,campaign_id,sequence_version,step_id}` referring to `{business_id,campaign_id,sequence_version,id}`.
- **One last row:** `trigger: old, enabled`.

**STOP IF:** the `sequence_version, enrolment_id` row is missing, any `refers_to` differs from the above, or the trigger row is missing or says `DISABLED`. Send me the output.

---

## STEP 1 — Apply (one transaction)

1. Open **`backend/migrations/044_outreach_wording_moves.sql`**.
2. Select all of it (about 115 lines) and copy it.
3. Paste it into the SQL editor and run it **once**.

**EXPECT:**
- *Success. No rows returned.*
- Supabase may also show the notice `044: dropped outreach_messages_business_id_campaign_id_sequence_version_fkey`.

**STOP IF:** any error, including any `044:` error or `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

Run the STEP 0 query again.

**EXPECT:** the same rows, except:
- the **`{business_id,campaign_id,sequence_version,enrolment_id}`** row is **gone**;
- the last row now reads **`trigger: new, enabled`**.

All the other rows, including the step key `{business_id,campaign_id,sequence_version,step_id}`, are still there.

**STOP IF:** any other row changed, or the last row isn't `trigger: new, enabled`.

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

**EXPECT:** `COMMIT`. STEP 0 then shows the `sequence_version, enrolment_id` row again. The trigger stays `new, enabled`: it is safe under either version of the rule.

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
