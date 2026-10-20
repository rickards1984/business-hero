# 037 — PRODUCTION RUNBOOK: outreach core (Mike's steps)

**For:** Mike. **Ticket:** OUT-3. **Migration:** `backend/migrations/037_outreach_core.sql`.

**Rehearsed:** `audits/037-STAGING-REHEARSAL.md` (20 Oct 2026). On staging it was applied, verified, re-pasted, rolled back to the exact before-state, and re-applied. Existing invoice-chase records came through unchanged.

**What it does:**
- creates the 17 outreach tables, all empty;
- adds six extra lookup keys to existing email and action tables;
- allows two new action types, for outreach;
- nothing is switched on or sent.

**Risk:** RED, as all production SQL is. Moderate in practice: it is bigger than 036, but it only adds things.

Takes about 20 minutes.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start:** confirm the project selector reads **business-hero (`oxblcmwhuwtobdhsfgyi`)**. 036 is already live (20 Oct).

---

## STEP 0 — Read-only checks

```sql
SELECT current_database(),
       (SELECT count(*) FROM pg_tables
         WHERE schemaname = 'public' AND tablename LIKE 'outreach\_%')       AS outreach_tables,
       to_regprocedure('public.is_business_member(uuid,uuid)') IS NOT NULL AS membership_helper,
       (SELECT count(*) FROM (SELECT id FROM public.email_accounts GROUP BY id HAVING count(*) > 1) d) AS dup_accounts,
       (SELECT count(*) FROM (SELECT id FROM public.email_messages GROUP BY id HAVING count(*) > 1) d) AS dup_messages,
       (SELECT count(*) FROM (SELECT id FROM public.email_outbox  GROUP BY id HAVING count(*) > 1) d) AS dup_outbox,
       (SELECT count(*) FROM (SELECT id FROM public.aria_actions  GROUP BY id HAVING count(*) > 1) d) AS dup_actions,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public')          AS policies;
```

**EXPECT:**
- `postgres`;
- `outreach_tables` **0**;
- `membership_helper` **true**;
- all four `dup_` values **0**;
- `policies` noted. It should rise by **6** after STEP 3.

**STOP IF:** `outreach_tables` isn't 0, `membership_helper` is false, or any `dup_` value isn't 0.

You already sent the key check (036 STEP 0, 20 Oct): all four tables have their primary keys.

---

## STEP 1 — The default-mailbox check (READ-ONLY)

```sql
SELECT b.id AS business_id,
       count(e.id) AS account_count,
       count(e.id) FILTER (WHERE e.is_default IS TRUE) AS default_count,
       coalesce(array_agg(e.id ORDER BY e.id)
                FILTER (WHERE e.is_default IS TRUE), '{}'::uuid[]) AS default_account_ids,
       CASE WHEN count(e.id) FILTER (WHERE e.is_default IS TRUE) > 1 THEN 'BLOCKS'
            ELSE 'info' END AS gate
FROM public.businesses AS b
JOIN public.email_accounts AS e ON e.business_id = b.id
GROUP BY b.id
HAVING count(e.id) FILTER (WHERE e.is_default IS TRUE) <> 1
ORDER BY gate, b.id;
```

**EXPECT:** **no rows**, or only rows with `gate` = `info`. An `info` row is a business with mailboxes but none marked default. It's fine for this step, and Aria won't chase for that business until a default is chosen.

**STOP IF:** any row says **`BLOCKS`**: a business with two or more default mailboxes. Send me the rows. You'll choose which mailbox stays default, as a separate step. Carry on with STEPs 2–4 either way, but skip STEP 5 until it's resolved.

---

## STEP 2 — Six extra keys on existing tables (six separate runs)

Run each statement **on its own**: paste it, run it, wait for success, then do the next. These build without locking the tables, which is why they can't run together. Each should say *Success. No rows returned*.

**Run 1:**

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_accounts_out3_business_id_key
  ON public.email_accounts (business_id, id);
```

**Run 2:**

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS aria_actions_out3_business_id_key
  ON public.aria_actions (business_id, id);
```

**Run 3:**

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_outbox_out3_business_id_key
  ON public.email_outbox (business_id, id);
```

**Run 4:**

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_messages_out3_business_id_key
  ON public.email_messages (business_id, id);
```

**Run 5:**

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_outbox_out3_mailbox_id_key
  ON public.email_outbox (business_id, email_account_id, id);
```

**Run 6:**

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_messages_out3_mailbox_id_key
  ON public.email_messages (business_id, email_account_id, id);
```

**STOP IF:** any of them errors. Don't retry it. Send me the error, because a failed build can leave a half-made index that I need to look at.

---

## STEP 3 — The outreach tables (one transaction)

Open **`audits/037-STEP-3-section2.sql`**, then select all and copy it. It's long, about 760 lines. Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.*

**STOP IF:** any error. Because it's one transaction, nothing will have changed. Send me the error.

---

## STEP 4 — VERIFY (READ-ONLY)

```sql
SELECT
  (SELECT count(*) FROM pg_tables
    WHERE schemaname = 'public' AND tablename LIKE 'outreach\_%')                       AS tables,
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname LIKE 'outreach\_%' AND c.relkind = 'r'
      AND c.relrowsecurity)                                                              AS rls_on,
  (SELECT count(*) FROM information_schema.role_table_grants
    WHERE table_schema = 'public' AND table_name LIKE 'outreach\_%' AND grantee = 'anon') AS anon_privileges,
  (SELECT count(DISTINCT table_name) FROM information_schema.role_table_grants
    WHERE table_schema = 'public' AND table_name LIKE 'outreach\_%'
      AND grantee = 'authenticated')                                                     AS readable_tables,
  (SELECT string_agg(DISTINCT privilege_type, ',') FROM information_schema.role_table_grants
    WHERE table_schema = 'public' AND table_name LIKE 'outreach\_%'
      AND grantee = 'authenticated')                                                     AS signed_in_privileges,
  (SELECT pg_get_constraintdef(oid) LIKE '%send_outreach%' FROM pg_constraint
    WHERE conname = 'aria_actions_type_chk')                                             AS outreach_actions_allowed,
  (SELECT count(*) FROM pg_policies WHERE schemaname = 'public')                         AS policies;
```

**EXPECT:**
- `tables` **17**;
- `rls_on` **17**;
- `anon_privileges` **0**;
- `readable_tables` **6**;
- `signed_in_privileges` **SELECT**;
- `outreach_actions_allowed` **true**;
- `policies` = STEP 0's number **+ 6**.

**STOP IF:** anything differs, and above all if `anon_privileges` isn't 0 or `signed_in_privileges` is anything other than `SELECT`. In that case run ROLLBACK below and send me both outputs.

---

## STEP 5 — One default mailbox per business (only if STEP 1 had no `BLOCKS` row)

Run this on its own:

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_accounts_one_default_idx
  ON public.email_accounts (business_id) WHERE is_default IS TRUE;
```

**EXPECT:** *Success. No rows returned.*

---

## STEP 6 — Regenerate the schema dump (READ-ONLY)

As for 036: row limit **No limit**, run `scripts/dump-live-schema.sql`, **Download → CSV**, and drag it into the repo folder. Expect about **1,105 rows**: the previous 844 plus the 261 new outreach columns.

---

## ROLLBACK — only if STEP 4 failed

This is tested on staging. It refuses to run if any outreach table has rows. Paste it as one run:

```sql
BEGIN;
SET LOCAL lock_timeout='5s';
DO $rollback$
DECLARE t text; populated boolean;
BEGIN
  LOCK TABLE public.aria_actions IN ACCESS EXCLUSIVE MODE;
  IF EXISTS (SELECT 1 FROM public.aria_actions
             WHERE action_type IN ('send_outreach','reply_outreach')) THEN
    RAISE EXCEPTION 'Outreach action history exists; rollback forbidden';
  END IF;
  FOR t IN SELECT unnest(ARRAY[
    'outreach_brands','outreach_settings','outreach_mailboxes','outreach_prospects',
    'outreach_evidence','outreach_compliance','outreach_campaigns',
    'outreach_batch_reviews','outreach_sequence_steps','outreach_enrolments',
    'outreach_messages','outreach_replies','outreach_suppressions',
    'outreach_unsubscribe_tokens','outreach_dispatch_jobs','outreach_daily_usage',
    'outreach_usage_events']) LOOP
    EXECUTE format('LOCK TABLE public.%I IN ACCESS EXCLUSIVE MODE',t);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I)',t) INTO populated;
    IF populated THEN RAISE EXCEPTION 'Table % has history; rollback forbidden',t; END IF;
  END LOOP;
END;
$rollback$;
ALTER TABLE public.outreach_campaigns DROP CONSTRAINT IF EXISTS outreach_campaigns_first_review_fk;
DROP TABLE IF EXISTS public.outreach_usage_events;
DROP TABLE IF EXISTS public.outreach_daily_usage;
DROP TABLE IF EXISTS public.outreach_dispatch_jobs;
DROP TABLE IF EXISTS public.outreach_replies;
DROP TABLE IF EXISTS public.outreach_messages;
DROP TABLE IF EXISTS public.outreach_enrolments;
DROP TABLE IF EXISTS public.outreach_sequence_steps;
DROP TABLE IF EXISTS public.outreach_batch_reviews;
DROP TABLE IF EXISTS public.outreach_campaigns;
DROP TABLE IF EXISTS public.outreach_evidence;
DROP TABLE IF EXISTS public.outreach_prospects;
DROP TABLE IF EXISTS public.outreach_compliance;
DROP TABLE IF EXISTS public.outreach_brands;
DROP TABLE IF EXISTS public.outreach_mailboxes;
DROP TABLE IF EXISTS public.outreach_settings;
DROP TABLE IF EXISTS public.outreach_suppressions;
DROP TABLE IF EXISTS public.outreach_unsubscribe_tokens;
DROP FUNCTION IF EXISTS public.outreach_bind_message_version();
DROP FUNCTION IF EXISTS public.outreach_freeze_approved_step();
ALTER TABLE public.aria_actions DROP CONSTRAINT IF EXISTS aria_actions_type_chk;
ALTER TABLE public.aria_actions ADD CONSTRAINT aria_actions_type_chk
  CHECK (action_type IN ('send_email','send_invoice_chase','create_calendar_event','create_task'));
COMMIT;
```

The six keys from STEP 2 can safely stay. Send me STEP 0's and STEP 4's output either way.

---

## Afterwards

Send me STEP 0's row and STEP 4's row, and drag in the CSV. I'll then regenerate the schema record, record the run here, and open the OUT-3 pull request.

---
---

# Technical reference (Codex, OUT-3 Stage B)

Codex's full runbook follows, unchanged except for the fixture fix noted in the rehearsal record. Mike's steps above are what to run. The extra captures Codex specified (full JSON row archives of `aria_actions`, `email_outbox`, `business_settings` and `usage_meters` in production) are replaced by the staging rehearsal's synthetic legacy rows, which were compared byte for byte through apply, rollback and re-apply. This is Claude's review decision: 037 doesn't modify existing rows, the comparison is exact on staging, and archiving production's live payloads would copy customer data out of the database for no added safety.

# 037 — PRODUCTION RUNBOOK: outreach core

**For:** Mike. **Ticket:** OUT-3 Stage B. **Migration:** `backend/migrations/037_outreach_core.sql`.
**North Star:** P4/P9, Actions & permissions; security, isolation and correctness.
**Status:** DRAFT, NOT REHEARSED, NOT APPLIED. Stage A tests approved 19 October
2026. This document is not production authority. Claude must independently
review and replay; Mike separately authorises each production action.

Run numbered steps individually in the Supabase SQL editor. Never paste the
whole migration: Section 1 and Section 4 use concurrent indexes and must run
outside transactions, **one CREATE statement per execution**. Section 2 is one
transaction, including creation, RLS and grant narrowing. Do not deploy models,
populate outreach or enable sends: OUT-4 tools and later activation gates remain.
No monthly allowance counter is introduced; `usage_meters` remains authoritative.

## STEP 0 — Confirm project identity FIRST (READ-ONLY)

Check the dashboard selector **and URL**: production is
`oxblcmwhuwtobdhsfgyi`; rehearsal is `gzcrsrqmygublveuzqyg`. Record the reference,
time and operator. Both databases can be named `postgres`; database name and
row counts are not project identity. For Claude's local replay, require loopback
`127.0.0.1:54329` instead. No production action until staging parity, migration,
rollback and reapplication have been independently proved.

```sql
SELECT current_database(), current_user, version(),
       to_regprocedure('public.is_business_member(uuid,uuid)') AS membership_helper;
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (table_name IN ('businesses','business_members','business_settings',
                     'email_accounts','email_messages','email_outbox','aria_actions')
       OR table_name LIKE 'outreach\_%' ESCAPE '\')
ORDER BY table_name, ordinal_position;
SELECT c.relname, c.relrowsecurity, c.relacl
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND (c.relname IN ('email_accounts','email_messages','email_outbox','aria_actions')
       OR c.relname LIKE 'outreach\_%' ESCAPE '\')
ORDER BY c.relname;
SELECT conrelid::regclass AS relation, conname, contype, convalidated,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
ORDER BY conrelid::regclass::text, conname;
SELECT t.relname AS table_name, i.relname AS index_name,
       x.indisvalid, x.indisready, pg_get_indexdef(i.oid) AS definition
FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
JOIN pg_class t ON t.oid = x.indrelid
WHERE t.relnamespace = 'public'::regnamespace
ORDER BY t.relname, i.relname;
SELECT tablename, policyname, cmd, roles::text, qual, with_check
FROM pg_policies WHERE schemaname = 'public' ORDER BY tablename, policyname;
```

Claude's 036 staging rehearsal on **19 October 2026** found **no primary key,
unique constraint or index** on staging `email_accounts` and `email_messages`;
`invoices` and `aria_actions` did have keys. Production keys for the two email
tables were never captured. Do not infer production constraints from staging
or from the column dump. Run and archive these additional **read-only production**
checks before any 037 DDL. The LEFT JOIN emits a row even when a table has no
primary/unique constraint.

```sql
WITH parents(table_name) AS (
  VALUES ('email_accounts'), ('email_messages'), ('email_outbox'), ('aria_actions')
)
SELECT p.table_name, c.conname, c.contype, c.convalidated,
       pg_get_constraintdef(c.oid) AS definition
FROM parents p
LEFT JOIN pg_constraint c
  ON c.conrelid = to_regclass('public.' || p.table_name)
 AND c.contype IN ('p','u')
ORDER BY p.table_name, c.contype, c.conname;

-- One result per new (business_id,id) key. Count both globally repeated IDs
-- and repeated composite keys; neither count may be nonzero.
WITH parent_rows AS (
  SELECT 'email_accounts' AS table_name, business_id, id FROM public.email_accounts
  UNION ALL
  SELECT 'email_messages', business_id, id FROM public.email_messages
  UNION ALL
  SELECT 'email_outbox', business_id, id FROM public.email_outbox
  UNION ALL
  SELECT 'aria_actions', business_id, id FROM public.aria_actions
), parents(table_name) AS (
  VALUES ('email_accounts'), ('email_messages'), ('email_outbox'), ('aria_actions')
), duplicate_ids AS (
  SELECT table_name, id FROM parent_rows GROUP BY table_name, id HAVING count(*) > 1
), duplicate_keys AS (
  SELECT table_name, business_id, id FROM parent_rows
  GROUP BY table_name, business_id, id HAVING count(*) > 1
)
SELECT p.table_name,
       (SELECT count(*) FROM duplicate_ids d
        WHERE d.table_name=p.table_name) AS duplicate_id_groups,
       (SELECT count(*) FROM duplicate_keys d
        WHERE d.table_name=p.table_name) AS duplicate_business_id_id_groups,
       (SELECT count(*) FROM parent_rows r
        WHERE r.table_name=p.table_name AND r.business_id IS NULL) AS null_business_ids,
       (SELECT count(*) FROM parent_rows r
        WHERE r.table_name=p.table_name AND r.id IS NULL) AS null_ids
FROM parents p ORDER BY p.table_name;
```

**EXPECT:** a primary key on `id` for each parent; all four counts **0** for
each table (including empty tables). **If any primary key is missing: STOP and
send Claude the complete output.** The new composite unique keys would still
work without a primary key, but Claude must review that fact and the actual
production constraints before 037 proceeds. Nonzero duplicates/nulls or an
unexpected key definition also mean STOP; do not clean data or invent a primary
key as part of this migration. Reconcile staging parity through separate review.

**EXPECT:** membership helper exists; four existing parent tables have UUID
`id` and non-null UUID `business_id`; both mail tables have UUID
`email_account_id`. `email_outbox` must support `to_emails`, `body_preview`,
`status`, `chase_stage` as the approved test fixture requires. `aria_actions`
has the four legacy action types and existing six statuses. First application
has none of the 17 outreach tables. Archive all results as the before-catalogue.

**STOP IF:** missing/different columns, unvalidated constraints, incompatible
indexes, unexpected tables/policies or differing staging/prod PK/FK/UNIQUE/CHECK
structure. Migration history is not proof of parity. The local harness applies `scripts/rls-local-reconcile.sql` after historical
replay and before 034–037 to match the outbox columns in
`audits/live-schema-public.txt:342–354`. Claude must review and replay that
correction; it is local-only and is not evidence of production constraints.
037 does not add guessed columns or hide the failure.
A re-paste requires comparison against the approved post-catalogue first;
`IF NOT EXISTS` does not repair an incompatible existing object.

## STEP 1 — Capture legacy data and default audit (READ-ONLY)

Archive the complete JSON values below in restricted audit storage, not a public
PR. Capture under a consistent snapshot. Repeat this exact query after Section 2
and after rehearsal rollback. It includes executing actions, NULL approvers,
payloads, settings, outbox rows and meter state, not just counts.

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT 'aria_actions' AS relation, id::text AS row_id, to_jsonb(a) AS row_value
  FROM public.aria_actions a
UNION ALL
SELECT 'email_outbox', id::text, to_jsonb(o) FROM public.email_outbox o
UNION ALL
SELECT 'business_settings', id::text, to_jsonb(s) FROM public.business_settings s
UNION ALL
SELECT 'usage_meters', id::text, to_jsonb(m) FROM public.usage_meters m
ORDER BY relation, row_id;
COMMIT;
```

Also run **Section 3** of 037 now: the read-only default-account audit includes
businesses with no accounts. Save its entire result. Zero rows means every
business currently has exactly one default. UUID ordering is display only.

**When non-zero:** stop the default-index path. Mike chooses exact account IDs
for ambiguous businesses. Zero-account/zero-default businesses need Mike's
explicit disposition; do not invent an account or select the newest. Any
cleanup UPDATE is a separate RED action, with before/after evidence and its own
approval; this runbook performs none. A business may remain disconnected and
blocked, but under this Stage B instruction that means **Section 4 stays
blocked** until Mike explicitly revises the gate or the audit is zero. No
implicit exception for an archived business. Other schema sections can proceed
under their own approval, but do not mark migration complete without the index.

**EXPECT:** archived snapshots and audit. On production, legitimate concurrent
chasing can change these rows: coordinate a separately approved quiescent
window for exact comparison, or stop and investigate every delta. Never claim
byte-for-byte preservation from counts or from the post-migration coexistence test.

## STEP 2 — Rehearse with synthetic legacy rows BEFORE 037 (Claude)

Mandatory before production approval. Use isolated local Postgres or separately
authorised staging, never insert these fixtures in production. No workers or
provider calls may run. Confirm the fixed IDs below are absent before seeding.
Run this before Section 1/2, then capture STEP 1.

```sql
BEGIN;
INSERT INTO auth.users (id,email,aud,role)
VALUES ('00000000-0000-4000-8000-000000037001',
        'out3-rehearsal@example.invalid','authenticated','authenticated');
INSERT INTO public.businesses (id,name,api_key,plan_tier)
VALUES ('00000000-0000-4000-8000-000000037002','OUT3 preservation rehearsal',
        'out3-synthetic-037-never-production','starter');
INSERT INTO public.business_members (id,business_id,user_id,role,is_active)
VALUES ('00000000-0000-4000-8000-000000037003',
        '00000000-0000-4000-8000-000000037002',
        '00000000-0000-4000-8000-000000037001','owner',true);
INSERT INTO public.email_accounts
  (id,business_id,user_id,provider,email_address,is_default)
VALUES ('00000000-0000-4000-8000-000000037004',
        '00000000-0000-4000-8000-000000037002',
        '00000000-0000-4000-8000-000000037001','google',
        'out3-sender@example.invalid',true);
INSERT INTO public.business_settings (id,business_id,settings,created_at,updated_at)
VALUES ('00000000-0000-4000-8000-000000037005',
        '00000000-0000-4000-8000-000000037002',
        '{"automations":{"invoice_chase":{"enabled":false,"revision":7}},"out3_preservation":"sentinel"}',
        '2026-10-19 10:00:00', '2026-10-19 10:00:00');
INSERT INTO public.aria_actions
  (id,business_id,action_type,payload,status,approved_by,approved_at,expires_at)
SELECT ('00000000-0000-4000-8000-00000003701' || n)::uuid,
       '00000000-0000-4000-8000-000000037002'::uuid, 'send_invoice_chase',
       jsonb_build_object('invoice_id','synthetic','stage',n,'version',1,
                          'automation','invoice_chase','nested',jsonb_build_array(1,NULL,'keep')),
       status,
       CASE WHEN n = 2 THEN '00000000-0000-4000-8000-000000037001'::uuid END,
       CASE WHEN n = 2 THEN '2026-10-19 10:00:00+00'::timestamptz END,
       '2026-11-19 10:00:00+00'::timestamptz
FROM (VALUES (0,'proposed'),(1,'executing'),(2,'done')) AS fixture(n,status);
INSERT INTO public.email_outbox
  (id,business_id,email_account_id,to_emails,subject,body_preview,status,chase_stage)
VALUES ('00000000-0000-4000-8000-000000037020',
        '00000000-0000-4000-8000-000000037002',
        '00000000-0000-4000-8000-000000037004',
        ARRAY['out3-recipient@example.invalid'],'Synthetic chase',
        'Preserve this audit row','sent',1);
COMMIT;
```

**EXPECT:** three chase actions including executing/NULL approver, owner-approved
done row, nested JSON/nulls, settings sentinel and outbox row. Save complete
before values. Execute all sections and rollback/reapply using the same fixtures;
compare canonical JSON by `(relation,row_id)` for exact logical equality. Keep
pre-existing synthetic tenants' default-account decisions explicit as well.
The seed is deliberately not re-paste safe: duplicate UUIDs must stop a repeat.
Fixture cleanup belongs to the disposable rehearsal environment, not prod SQL.

## STEP 3 — Section 1: build six existing-table indexes concurrently

Paste each of the six `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS`
statements from **Section 1**, one at a time, outside BEGIN/COMMIT. Four are
`(business_id,id)`; two bind `(business_id,email_account_id,id)` on the mail
tables. Builds allow writes to continue, though they can wait for old transactions.

**EXPECT:** each succeeds. Re-run STEP 0's index query: six named `_out3_` indexes,
all `indisvalid=true`, `indisready=true`, unique, exact columns/order, no predicate.
**STOP IF:** invalid or wrong-definition index. `IF NOT EXISTS` alone would skip
an invalid index. An interrupted concurrent build leaves earlier successful
indexes in place; it does not roll back the whole file. After independent review
and separate production approval, remove only the failed **unattached** 037
index with `DROP INDEX CONCURRENTLY IF EXISTS public.<exact_failed_index>` as
one execution, then retry that CREATE. Never drop a constraint-owned index or
any pre-existing index. Archive its definition first. No automatic retry loop.

## STEP 4 — Section 2: attach keys and create outreach atomically

Paste **only Section 2**, from BEGIN through COMMIT. This attaches the six unique
constraints to the already-built indexes, extends only the action-type CHECK,
and creates the 17 tables, compound FKs, checks, indexes, two invoker trigger
functions, RLS, six member-only read policies and grants. No blanket admin policy.
Client/PUBLIC defaults are revoked before reads are granted; column-level grants
are revoked too. Unexpected inherited privileges abort the transaction.
`service_role` receives SELECT/INSERT/UPDATE/DELETE/REFERENCES/TRIGGER; default
TRUNCATE is revoked, unlike 035's broader service grant.

**EXPECT:** success; no row mutation. A 5-second lock timeout bounds the brief
locks required to attach constraints/change the action CHECK. Index building is
concurrent; attachment is not lock-free. **STOP IF:** any error; ROLLBACK the
failed session, retain Section 1 indexes and investigate. Do not silently increase
timeouts or remove a constraint. Nothing in Section 2 should partially commit.

Implementation details for Claude's review: pilot timezones are pinned to
Europe/London. Existing contract enums are retained; previously implicit enums
are explicit: prospect stage `new/research/ready/contacted/replied/qualified/meeting/won/closed`,
reply resolution `pending/handed_over/resolved/dismissed`, job status
`pending/claimed/completed/failed/unknown/cancelled`. Reply category snake-case
spellings follow OUT-1 §6 plus unknown/bounce/complaint/self. Confirm these names
before services consume them. JSON objects/arrays are bounded to 16 KiB, evidence
excerpt/value to 4,000 characters and flags to 4 KiB. Adapter allowlists and safe
content projection remain service responsibilities. Owner CC ownership is also
validated by the future service, never authorised by the stored address alone.

The internal message `sequence_version` is derived from its enrolment by an
invoker trigger, then enforced against both enrolment and step composite keys;
callers cannot forge a mismatched version. Daily `scope_mailbox_id` is generated
only for mailbox scopes, allowing an actual composite account FK. Approved
sequence versions reject edits; create a new version. Campaign mailbox FKs use
NO ACTION, preventing mailbox changes while reviews/messages reference it,
including before dispatch. No cascade silently rewrites historical identity.
Settings, counters, batch counts and JSON authority snapshots never grant send
permission. Fresh shared authority and atomic generic metering are OUT-6 work.

## STEP 5 — After checks (READ-ONLY)

```sql
SELECT c.relname, c.relrowsecurity,
       has_table_privilege('service_role',c.oid,'TRUNCATE') AS service_truncate
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r'
  AND c.relname LIKE 'outreach\_%' ESCAPE '\'
ORDER BY c.relname;
SELECT tablename, policyname, cmd, roles::text, qual, with_check
FROM pg_policies
WHERE schemaname='public' AND tablename LIKE 'outreach\_%' ESCAPE '\'
ORDER BY tablename, policyname;
SELECT count(*) AS total_public_policies FROM pg_policies WHERE schemaname='public';
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid='public.aria_actions'::regclass
ORDER BY conname;
```

**EXPECT:** exactly these 17 RLS-on tables, all `service_truncate=false`:
brands, settings, mailboxes, prospects, evidence, compliance, campaigns,
batch_reviews, sequence_steps, enrolments, messages, replies, suppressions,
unsubscribe_tokens, dispatch_jobs, daily_usage, usage_events (all `outreach_`).
Exactly six policies: `outreach_<table>_member_read` for brands, campaigns,
prospects, evidence, compliance, replies; SELECT, `{authenticated}`, USING
`is_business_member(auth.uid(), business_id)`, NULL WITH CHECK. No admin OR.
Expected policy count is **93** on the reviewed replay baseline (87 + 6).
If AUTO-2 or another migration legitimately adds policies, reconcile separately;
never remove or ignore an unexpected policy to make the pinned test pass.
Action types are all four originals plus send_outreach/reply_outreach; statuses
remain exactly proposed/executing/done/failed/dismissed/expired.

Check effective grants, including inherited and column privileges:

```sql
WITH tables AS (
  SELECT c.oid,c.relname FROM pg_class c
  WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
    AND c.relname LIKE 'outreach\_%' ESCAPE '\'
), checks AS (
  SELECT t.relname,r.role_name,p.privilege,
    CASE WHEN p.privilege IN ('SELECT','INSERT','UPDATE','REFERENCES')
      THEN has_any_column_privilege(r.role_name,t.oid,p.privilege)
      ELSE has_table_privilege(r.role_name,t.oid,p.privilege) END AS actual,
    (r.role_name='authenticated' AND p.privilege='SELECT' AND t.relname IN
      ('outreach_brands','outreach_campaigns','outreach_prospects',
       'outreach_evidence','outreach_compliance','outreach_replies')) AS expected
  FROM tables t CROSS JOIN (VALUES ('anon'),('authenticated')) r(role_name)
  CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('REFERENCES'),
                     ('DELETE'),('TRUNCATE'),('TRIGGER')) p(privilege)
)
SELECT * FROM checks WHERE actual IS DISTINCT FROM expected;
SELECT table_name,grantee,privilege_type
FROM information_schema.role_table_grants
WHERE table_schema='public' AND table_name LIKE 'outreach\_%' ESCAPE '\'
  AND grantee IN ('anon','authenticated','service_role')
ORDER BY table_name,grantee,privilege_type;
```

**EXPECT:** zero rows from mismatch query; exactly six service privileges per
table and SELECT only on the six readable tables for authenticated. No anon.
Repeat STEP 0's complete constraint/index/policy catalogue and STEP 1's data
snapshot; compare legacy rows exactly. All constraints valid, all indexes valid.
**STOP IF:** any discrepancy. Keep application population disabled; do not deploy.

## STEP 6 — Section 3 again: default-index gate (READ-ONLY)

Run **Section 3's exact audit** again immediately before creating the default
index, even if STEP 1 was clear. Archive results and Mike's account-ID decisions.
**EXPECT: ZERO problem businesses.** Any non-zero result blocks STEP 7, including
zero defaults. Use STEP 1's resolution procedure. There is no recency cleanup.

## STEP 7 — Section 4: default index, separately authorised

Only after STEP 6 returns zero rows, run **Section 4's single CREATE UNIQUE INDEX
CONCURRENTLY** as its own SQL-editor execution, outside any transaction.

```sql
SELECT i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid)
FROM pg_index i
WHERE i.indexrelid=to_regclass('public.email_accounts_one_default_idx');
```

**EXPECT:** one valid, ready UNIQUE index on `(business_id)` with predicate
`is_default IS TRUE`. Repeat Section 3 audit after creation: zero rows still
required for sign-off. Concurrent account changes can race the audit; the unique
build rejects duplicates, but cannot enforce at least one. Any audit change or
failed build stops sign-off; investigate, do not pick an account. The at-most-one
index permits later zero defaults; general sends must fail closed in that case.
AUTO owns atomic set-default and sender fixes; this migration does not enable them.

## STEP 8 — Independent replay, preservation and handoff

Claude runs outside this builder sandbox:

```bash
scripts/rls-local.sh up
scripts/rls-local.sh test
RLS_LOCAL_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54329/postgres PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_outreach_schema_rls.py -v
```

**EXPECT:** all Stage A cases pass without changing their meaning; the exact
policy suite passes at 93. Confirm the six offline-derived CSV expressions
against actual `pg_policies`; correct renderings only, never policy semantics.
Replay from baseline, re-paste and rollback/reapply must all succeed. The normal
replay applies 037 automatically; the separate STEP 2 preservation rehearsal
must deliberately pause before 037 and capture before-values, then execute 037.
A post-replay seed alone does not prove migration preservation.

In addition, exercise both trigger functions (matching-version success,
wrong-version step rejection, parent version mutation rejection, approved-step
edit rejection), campaign mailbox mutation after a synthetic accepted message,
and daily scope parent updates/deletes. Rehearse concurrent index interruption
and bounded lock timeout. Test effective anon/member A/member B privileges and
composite FKs as the elevated backend, including nullable-field bypass attempts.
Verify no inherited service TRUNCATE and no unexpected policies on a re-paste.
These are required Postgres evidence, not results claimed by `check.sh`.

Archive outputs, exact SQL revision, pre/post/rollback snapshots and independent
verdict. New tables should be empty at initial deployment. Do not import PII,
register ORM models or launch sends. Mike's behaviour check: there is nothing
new to click in the app; review the runbook evidence and default-account choices.

## STEP 9 — Rollback (separate RED approval; never automatic)

Before rollback, stop rollout and confirm no outreach feature has been enabled.
Capture complete rows from all 17 new tables, plus STEP 0/1 snapshots. If any
new table has rows, any outreach action exists, or another feature depends on
these objects, **STOP**: preserve audit/suppression data and prepare an approved
forward repair or data-preserving rollback. Never drop populated history or
suppression records. Do not use CASCADE. A failed Section 2 needs only ROLLBACK;
Section 1 indexes can remain harmlessly until separately removed.

For a completed but unused migration, with confirmed empty new tables and no
`send_outreach`/`reply_outreach` actions, paste this transaction. It rechecks
emptiness under exclusive locks, then drops only the new objects. This is a
bounded pre-activation rollback, not a general retention operation.

```sql
BEGIN;
SET LOCAL lock_timeout='5s';
DO $rollback$
DECLARE t text; populated boolean;
BEGIN
  LOCK TABLE public.aria_actions IN ACCESS EXCLUSIVE MODE;
  IF EXISTS (SELECT 1 FROM public.aria_actions
             WHERE action_type IN ('send_outreach','reply_outreach')) THEN
    RAISE EXCEPTION 'Outreach action history exists; rollback forbidden';
  END IF;
  FOR t IN SELECT unnest(ARRAY[
    'outreach_brands','outreach_settings','outreach_mailboxes','outreach_prospects',
    'outreach_evidence','outreach_compliance','outreach_campaigns',
    'outreach_batch_reviews','outreach_sequence_steps','outreach_enrolments',
    'outreach_messages','outreach_replies','outreach_suppressions',
    'outreach_unsubscribe_tokens','outreach_dispatch_jobs','outreach_daily_usage',
    'outreach_usage_events']) LOOP
    EXECUTE format('LOCK TABLE public.%I IN ACCESS EXCLUSIVE MODE',t);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I)',t) INTO populated;
    IF populated THEN RAISE EXCEPTION 'Table % has history; rollback forbidden',t; END IF;
  END LOOP;
END;
$rollback$;
ALTER TABLE public.outreach_campaigns DROP CONSTRAINT IF EXISTS outreach_campaigns_first_review_fk;
DROP TABLE IF EXISTS public.outreach_usage_events;
DROP TABLE IF EXISTS public.outreach_daily_usage;
DROP TABLE IF EXISTS public.outreach_dispatch_jobs;
DROP TABLE IF EXISTS public.outreach_replies;
DROP TABLE IF EXISTS public.outreach_messages;
DROP TABLE IF EXISTS public.outreach_enrolments;
DROP TABLE IF EXISTS public.outreach_sequence_steps;
DROP TABLE IF EXISTS public.outreach_batch_reviews;
DROP TABLE IF EXISTS public.outreach_campaigns;
DROP TABLE IF EXISTS public.outreach_evidence;
DROP TABLE IF EXISTS public.outreach_prospects;
DROP TABLE IF EXISTS public.outreach_compliance;
DROP TABLE IF EXISTS public.outreach_brands;
DROP TABLE IF EXISTS public.outreach_mailboxes;
DROP TABLE IF EXISTS public.outreach_settings;
DROP TABLE IF EXISTS public.outreach_suppressions;
DROP TABLE IF EXISTS public.outreach_unsubscribe_tokens;
DROP FUNCTION IF EXISTS public.outreach_bind_message_version();
DROP FUNCTION IF EXISTS public.outreach_freeze_approved_step();
ALTER TABLE public.aria_actions DROP CONSTRAINT IF EXISTS aria_actions_type_chk;
ALTER TABLE public.aria_actions ADD CONSTRAINT aria_actions_type_chk
  CHECK (action_type IN ('send_email','send_invoice_chase','create_calendar_event','create_task'));
COMMIT;
```

**EXPECT:** all 17 new tables/functions gone; original action-type/status checks,
legacy rows, settings, grants and policies match before-state. If BEFORE had
additional action types, stop and use the reviewed exact original constraint
instead; never erase another migration's work. Removing 037 policies returns
the replay baseline to 87; do not change the approved test to hide that rollback.

The six existing-table keys are additive and can safely remain. To return to the
exact before-state, **only if STEP 0 proves each was absent**, and no later
migration depends on it, separately authorise this transaction (no CASCADE):

```sql
BEGIN;
SET LOCAL lock_timeout='5s';
ALTER TABLE public.email_messages DROP CONSTRAINT IF EXISTS email_messages_out3_mailbox_id_key;
ALTER TABLE public.email_outbox DROP CONSTRAINT IF EXISTS email_outbox_out3_mailbox_id_key;
ALTER TABLE public.email_messages DROP CONSTRAINT IF EXISTS email_messages_out3_business_id_key;
ALTER TABLE public.email_outbox DROP CONSTRAINT IF EXISTS email_outbox_out3_business_id_key;
ALTER TABLE public.aria_actions DROP CONSTRAINT IF EXISTS aria_actions_out3_business_id_key;
ALTER TABLE public.email_accounts DROP CONSTRAINT IF EXISTS email_accounts_out3_business_id_key;
COMMIT;
```

Dropping attached constraints also removes their indexes. If Section 2 never
committed, those indexes are unattached: remove each remaining 037 index with
its own `DROP INDEX CONCURRENTLY IF EXISTS public.<exact_037_index_name>`
execution after verifying ownership and before-state. No transaction wrapper.
If the default index was absent before and its removal is separately approved:

```sql
DROP INDEX CONCURRENTLY IF EXISTS public.email_accounts_one_default_idx;
```

Removing the index does not undo Mike's separately approved default cleanup;
that action requires its own recorded reversal. Repeat STEP 0 and STEP 1,
compare exact catalogues and legacy JSON, reapply on rehearsal and rerun all
Postgres tests. Archive evidence before asking Mike to approve production.

## Builder verification — 19 October 2026

`PYTHONDONTWRITEBYTECODE=1 ./check.sh` passed: TypeScript, Python compilation,
Ruff and pytest; 1,844 passed, 234 skipped, 220 subtests passed. Eslint is skipped
because the frontend has no lint script. Postgres-only suites skip without
`RLS_LOCAL_DATABASE_URL`; this is **not** constraint, grant, trigger or migration
execution evidence. No Postgres, network, commit, push or production access.

Offline structure checks confirmed exactly 17 tables, every Stage A fixture
column, composite-FK target unique keys, six matching SQL/CSV policies and seven
concurrent indexes (six parents plus default account). `git diff --check` passed.
Stage A tests were not changed; no test/contract conflicts were identified.
Only the policy-count assertion/comment changes from 87 to 93. The policy CSV
is explicitly derived from SQL, not represented as a live catalogue capture.

Claude must verify Postgres parsing/execution, effective grants/RLS, exact
`pg_policies` renderings, all Stage A cases, added trigger/version bindings,
re-paste safety, index interruption/locks, the pre-037 legacy snapshot comparison,
and rollback/reapply. Verify the local outbox reconciliation against dump lines 342–354. Confirm the explicit enum vocabulary before service integration.


### OUT-3 Stage B — repair cycle 1 (19 October 2026)

Added the local-only outbox column reconciliation before 034–037, with an
empty-table guard and fail-fast transaction. Historical replay indices and the
expected-errors manifest are unchanged; 037 is unchanged. Added STEP 0 production
PK/UNIQUE inspection, duplicate ID/composite-key and null-business checks, with
mandatory STOP and Claude review if a primary key is absent.

`PYTHONDONTWRITEBYTECODE=1 ./check.sh`: **PASS** (4 passed, 0 failed,
1 optional eslint skip; pytest 1,844 passed, 234 skipped, 220 subtests passed).
`bash -n scripts/rls-local.sh` and `git diff --check`: **PASS**.
Docker image inspection was denied access to the local Docker socket, so this
builder could not execute PostgreSQL replay or verify the reconciled catalogue.
Claude must rerun STEP 8 and compare the outbox columns/types/nullability/defaults
to dump lines 342–354 before accepting this repair. No network, commit, push or
production action. Mike: no app behaviour changed and nothing new to click.
