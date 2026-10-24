# 038 — PRODUCTION RUNBOOK: outreach replies (Mike's steps)

**For:** Mike. **Ticket:** OUT-7. **Migration:** `backend/migrations/038_outreach_replies.sql`.

**Rehearsed:** `audits/038-STAGING-REHEARSAL.md` (24 Oct 2026). On staging, which started at production's recorded state of 94 policies and 1,105 columns, it was applied, checked, re-pasted with no change, rolled back to the exact before-state, and re-applied.

**What it does:**
- creates two empty tables: approved business facts for Aria's answers, and the one-answer-per-prospect reservation;
- adds one extra lookup key on outreach replies;
- nothing is switched on or sent.

**Risk:** RED, as all production SQL is. Low in practice: it only adds things, and no existing table's data changes. Takes about 10 minutes.

**Run each step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start:** confirm the project selector reads **business-hero (`oxblcmwhuwtobdhsfgyi`)**.

---

## STEP 0 — Read-only checks

```sql
SELECT current_database(),
       to_regclass('public.outreach_knowledge')   AS knowledge_before,
       to_regclass('public.outreach_reply_slots') AS slots_before,
       to_regprocedure('public.is_business_member(uuid,uuid)') IS NOT NULL AS membership_helper,
       (SELECT count(*) FROM (SELECT business_id, prospect_id, mailbox_id, id FROM public.outreach_replies
          GROUP BY 1,2,3,4 HAVING count(*) > 1) d)  AS dup_reply_identity,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'public')                        AS policies,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public')      AS columns;
```

**EXPECT:**
- `postgres`;
- `knowledge_before` and `slots_before` both **NULL**;
- `membership_helper` **true**;
- `dup_reply_identity` **0**;
- `policies` **94** and `columns` **1111**. That count includes the 033 rollback table `zz_033_flags_backup` (6 columns), which the schema dump leaves out; the dump itself is 1,105.

**STOP IF:** either `_before` value isn't NULL, `membership_helper` is false, or `dup_reply_identity` isn't 0. If `policies`/`columns` differ, stop and send me the row: something changed since 037.

---

## STEP 1 — One extra key (run on its own)

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS outreach_replies_out7_identity_key
  ON public.outreach_replies (business_id, prospect_id, mailbox_id, id);
```

**EXPECT:** *Success. No rows returned.* **STOP IF:** any error.

---

## STEP 2 — The two tables (one transaction)

Open **`audits/038-STEP-3-section2.sql`**, then select all and copy it (about 155 lines). Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.* **STOP IF:** any error. Because it's one transaction, nothing will have changed. Send me the error.

---

## STEP 3 — VERIFY (READ-ONLY)

```sql
SELECT (SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'outreach\_%') AS outreach_tables,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='outreach_knowledge')   AS knowledge_columns,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='outreach_reply_slots') AS slot_columns,
       (SELECT count(*) FROM pg_class WHERE relname IN ('outreach_knowledge','outreach_reply_slots') AND relrowsecurity)    AS rls_on,
       (SELECT count(*) FROM pg_policies WHERE schemaname='public')                                                        AS policies,
       (SELECT count(*) FROM pg_policies WHERE tablename='outreach_reply_slots')                                           AS slot_policies,
       (SELECT count(*) FROM information_schema.role_table_grants WHERE grantee='anon'
          AND table_name IN ('outreach_knowledge','outreach_reply_slots'))                                                 AS anon_privileges,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema='public')                                       AS columns;
```

**EXPECT:** `outreach_tables` **19**; `knowledge_columns` **14**; `slot_columns` **18**; `rls_on` **2**; `policies` **95**; `slot_policies` **0**; `anon_privileges` **0**; `columns` **1143** (1,111 + 32, including the 033 rollback table).

**STOP IF:** anything differs. Send me the row; see ROLLBACK below.

---

## STEP 4 — Regenerate the schema dump (READ-ONLY)

As before: row limit **No limit**, run `scripts/dump-live-schema.sql`, **Download → CSV**, and drag it into the repo folder. Expect **1,137 rows**.

---

## ROLLBACK — only if STEP 3 failed

Send me the output first. The rollback is the technical reference's STEP 6. It refuses to run if either table holds any data. I'll tell you exactly which block to paste.

## Afterwards

Send me STEP 0's row and STEP 3's row, and drag in the CSV. I'll regenerate the schema record, record the run here, and the OUT-7 pull request can then go to you.

## RESULT — run by Mike in production, 24 October 2026

- **STEP 0:** `postgres`; both `_before` values NULL; `membership_helper` true; `dup_reply_identity` 0; `policies` **94**; `columns` **1111**. Mike stopped, as the runbook said to: the draft expected 1,105. Mike then ran a check, which found `zz_033_flags_backup` with **6** columns, the 033 rollback table that the schema dump excludes. A full dump (1,105 rows) matched `audits/live-schema-public.txt` line for line, so nothing in production had drifted; only the runbook's counting method was off. The runbook's counts are now corrected.
- **STEPs 1–3:** all passed (`policies` 95; `columns` 1,143).
- **STEP 4:** the schema dump has **1,137 rows**. Against the record, it adds exactly the 32 columns of `outreach_knowledge` (14) and `outreach_reply_slots` (18); nothing is removed or changed. `audits/live-schema-public.txt` was regenerated from it.
- **Rollback:** not needed.

---
---

# Technical reference (Codex, OUT-7 Stage A)

Codex's full runbook follows, unchanged. Mike's steps above are what to run. As for 037, Codex's production row archives are replaced by the staging rehearsal: 038 creates new empty tables and touches no existing rows.

# 038 — DRAFT PRODUCTION RUNBOOK: outreach replies (Mike's steps)

**DRAFT FOR REVIEW — NOT AUTHORISED TO RUN.** Ticket OUT-7 Stage A, 23 October 2026. Migration `backend/migrations/038_outreach_replies.sql`. No rehearsal or remote execution is claimed. Serves P2/P4/P5/P9, tenant isolation and correctness.

**For Mike:** this would add two empty tables for approved business facts and the one-answer reservation. It would not turn on replying, send email, populate data, change invoice chasing or install application models. Read these steps now; do not paste SQL until independent review, staging rehearsal and your separate approval for each production action.

Follow 037's shape: concurrent parent index separately, transactional table/security creation, verify, independent replay, guarded rollback. Run one step at a time. Save each result. On any STOP condition, leave application activation off and send the output to the reviewer; do not guess or remove a check.

## STEP 0 — Preflight (READ-ONLY; future separately authorised execution)

Confirm selector: staging rehearsal **gzcrsrqmygublveuzqyg**; production **business-hero / oxblcmwhuwtobdhsfgyi**. The query below does not establish project identity by itself. Confirm 035/036/037 live catalogue, owner role, migration queue and no other schema migration in flight. Record exact SQL revision/hash. Obtain approval before touching either remote environment.

```sql
SELECT current_database(), current_user,
       to_regprocedure('public.is_business_member(uuid,uuid)') IS NOT NULL AS membership_helper,
       to_regclass('public.outreach_knowledge') AS knowledge_before,
       to_regclass('public.outreach_reply_slots') AS slots_before,
       (SELECT count(*) FROM pg_policies WHERE schemaname='public') AS policies_before,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema='public') AS columns_before;
SELECT c.relname,c.relrowsecurity,con.conname,con.contype,con.convalidated,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_constraint con ON con.conrelid=c.oid
WHERE n.nspname='public' AND c.relname IN
 ('businesses','outreach_brands','outreach_prospects','outreach_replies',
  'outreach_messages','email_accounts','aria_actions')
ORDER BY c.relname,con.conname;
SELECT i.indisvalid,i.indisready,i.indisunique,pg_get_indexdef(i.indexrelid)
FROM pg_index i WHERE i.indexrelid=to_regclass('public.outreach_replies_out7_identity_key');
SELECT count(*) AS duplicate_reply_identity FROM (
 SELECT business_id,prospect_id,mailbox_id,id FROM public.outreach_replies
 GROUP BY business_id,prospect_id,mailbox_id,id HAVING count(*)>1
) d;
SELECT count(*) AS null_reply_identity FROM public.outreach_replies
 WHERE business_id IS NULL OR prospect_id IS NULL OR mailbox_id IS NULL OR id IS NULL;
```

**EXPECT:** database postgres, authorised migration role, helper true, both new tables absent on first apply, duplicates/nulls zero. Parent primary keys and all 037 composite UNIQUE/FK definitions present and validated. In particular messages needs `(business_id,prospect_id,mailbox_id,id)` and `(business_id,action_id,id)`; replies needs its existing tenant key before the new identity key. Pre-existing 038 index is either absent or exactly the valid/ready unique definition above. **STOP IF:** missing keys, invalid constraints/index, partial new schema, wrong project, duplicates/nulls or unexplained drift. Staging's historical missing keys are not repaired by this migration. Never count a migration file as live evidence.

Record measured policy/column counts. Reviewed local baseline is 94 policies; last recorded post-037 production census was 94 policies / 1,105 public columns. These are historical, not assumed live state.

## STEP 1 — Before snapshots and preservation gate (READ-ONLY)

Archive complete definitions, grants (including column/default/inherited privileges), indexes, triggers and policies for all touched parents and existing outreach tables. Save full legacy chase/actions/settings/outbox rows as structured JSON in approved audit storage, not logs containing real PII. On synthetic rehearsal, seed representative `send_invoice_chase` actions (proposed/executing/done, including NULL approver), chase_replies and settings before applying 038; use 037's STEP 2 fixture shape plus a synthetic chase reply. Save and compare complete logical JSON by ID before/after/re-paste/rollback/reapply.

```sql
SELECT tablename,policyname,cmd,roles::text,qual,with_check
FROM pg_policies WHERE schemaname='public' ORDER BY tablename,policyname;
SELECT table_name,grantee,privilege_type FROM information_schema.role_table_grants
WHERE table_schema='public' ORDER BY table_name,grantee,privilege_type;
SELECT table_name,column_name,grantee,privilege_type FROM information_schema.column_privileges
WHERE table_schema='public' ORDER BY table_name,column_name,grantee,privilege_type;
SELECT c.relname, i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid)
FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
WHERE c.relnamespace='public'::regnamespace AND c.relname LIKE 'outreach_%'
ORDER BY c.relname,i.indexrelid;
```

**EXPECT:** reviewed snapshot, structurally equivalent staging parents, no unexplained privileges. New tables absent first time. Do not seed production. **STOP IF:** preservation cannot be established. No cleanup or default-mailbox change is part of 038.

## STEP 2 — Section 1: one extra parent key (autocommit)

When separately approved, paste only Section 1's single `CREATE UNIQUE INDEX CONCURRENTLY` statement. Run outside BEGIN/COMMIT. Concurrent building permits ongoing writes but may wait; key attachment in STEP 3 still takes a brief lock.

```sql
SELECT i.indisvalid,i.indisready,i.indisunique,pg_get_indexdef(i.indexrelid)
FROM pg_index i WHERE i.indexrelid=to_regclass('public.outreach_replies_out7_identity_key');
```

**EXPECT:** one valid/ready unique index on `(business_id, prospect_id, mailbox_id, id)` with no predicate. **STOP IF:** any error or wrong definition. An interrupted build may leave an invalid index; `IF NOT EXISTS` is not repair. Archive it, verify unattached ownership and obtain separate approval to drop only that failed index concurrently before retrying. Never drop a constraint-owned or pre-existing index to clear an error.

## STEP 3 — Section 2: create both tables and secure them atomically

Paste **only Section 2, BEGIN through COMMIT**, after approval. It attaches the parent key, creates 14-column knowledge and 18-column slots, all composite FKs/checks/indexes, one invoker knowledge-freeze trigger, RLS, one member-read policy and minimum grants. It revokes table and column defaults and aborts on inherited client access or service TRUNCATE. No data write or existing-column alteration occurs.

**EXPECT:** success. Five-second lock timeout bounds key attachment; on failure explicitly ROLLBACK the session and investigate. No partial Section 2 should commit. Section 1's index may remain. Re-paste is supported only after checking existing definitions; `CREATE IF NOT EXISTS` does not repair schema drift. No unreviewed grants or replacement policy may be carried through silently.

## STEP 4 — After checks (READ-ONLY)

```sql
SELECT c.relname,c.relrowsecurity,
       has_table_privilege('service_role',c.oid,'TRUNCATE') AS service_truncate
FROM pg_class c WHERE c.oid IN
 (to_regclass('public.outreach_knowledge'),to_regclass('public.outreach_reply_slots'));
SELECT table_name,count(*) AS columns
FROM information_schema.columns WHERE table_schema='public'
 AND table_name IN ('outreach_knowledge','outreach_reply_slots') GROUP BY table_name;
SELECT tablename,policyname,cmd,roles::text,qual,with_check FROM pg_policies
WHERE schemaname='public' AND tablename IN ('outreach_knowledge','outreach_reply_slots');
SELECT (SELECT count(*) FROM pg_policies WHERE schemaname='public') AS policies_after,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema='public') AS columns_after;
SELECT 'outreach_knowledge' AS table_name,count(*) AS rows FROM public.outreach_knowledge
UNION ALL SELECT 'outreach_reply_slots',count(*) FROM public.outreach_reply_slots;
```

**EXPECT exactly:** two RLS-on tables, service_truncate false; knowledge **14**, slots **18**, both empty on first apply. Exactly **one new policy**, knowledge member SELECT `{authenticated}`, USING `is_business_member(auth.uid(), business_id)`, NULL WITH CHECK. No slot policy, no admin OR. **Policy delta +1; column delta +32**, no removed/changed existing columns. Baseline 94 → **95** policies; historical 1,105 → **1,137** columns only if STEP 0 confirms that baseline. Outreach alone 17 → **19** tables / 261 → **293** columns / 6 → **7** policies. Re-paste delta zero. Legitimate intervening migrations need separate reconciliation, not count fudging.

Check effective table and column grants, not just ACL display:

```sql
WITH checks AS (
 SELECT t.tbl,r.role_name,p.privilege,
 CASE WHEN p.privilege IN ('SELECT','INSERT','UPDATE','REFERENCES')
 THEN has_any_column_privilege(r.role_name,'public.'||t.tbl,p.privilege)
 ELSE has_table_privilege(r.role_name,'public.'||t.tbl,p.privilege) END AS actual,
 ((r.role_name='authenticated' AND p.privilege='SELECT' AND t.tbl='outreach_knowledge')
  OR (r.role_name='service_role' AND p.privilege<>'TRUNCATE')) AS expected
 FROM (VALUES ('outreach_knowledge'),('outreach_reply_slots')) t(tbl)
 CROSS JOIN (VALUES ('anon'),('authenticated'),('service_role')) r(role_name)
 CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('REFERENCES'),('DELETE'),('TRIGGER'),('TRUNCATE')) p(privilege)
) SELECT * FROM checks WHERE actual IS DISTINCT FROM expected;
SELECT c.relname,con.conname,con.convalidated,pg_get_constraintdef(con.oid)
FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
WHERE c.oid IN ('public.outreach_knowledge'::regclass,'public.outreach_reply_slots'::regclass)
ORDER BY c.relname,con.conname;
SELECT p.proname,p.prosecdef,p.proconfig FROM pg_proc p
WHERE p.oid='public.outreach_freeze_knowledge()'::regprocedure;
```

**EXPECT:** zero grant mismatches; every FK/check valid and matches draft; trigger function `prosecdef=false`, pinned `search_path=pg_catalog, public`. Re-run complete index/catalogue checks and compare every legacy snapshot exactly. Parse schema export as CSV, never grep numeric column lines. **STOP IF:** any discrepancy or populated table at first activation gate. Do not register models or enable data population yet.

## STEP 5 — Independent replay, security and preservation evidence

On disposable loopback only, reviewer uses installed local image (no network needed):

```bash
scripts/rls-local.sh up
RLS_LOCAL_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54329/postgres PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_outreach_replies_schema_rls.py -v
scripts/rls-local.sh test
```

`up` resets the named container and can pull a missing image: do not run it in this no-network Stage A. Independently verify image exists and obtain any reset authority before use. Preserve historical replay-error manifest unchanged.

The full isolation suite currently pins 94 policies and its reviewed CSV predates this draft. Reviewer must capture/compare the new `pg_policies` rendering and approve its addition/count **95** before full suite can pass. Do not suppress that test or prune the new policy. No live-policy evidence file is fabricated in Stage A.

Rehearse two pastes, local constraints/RLS/anon+authenticated grants, same-business wrong-mailbox and cross-tenant FKs, concurrent slot uniqueness, immutable approved knowledge, one-approved-topic limit and positive slot lifecycle shapes. Prove lock-timeout rollback, invalid concurrent-index handling, pre-038 synthetic chase/settings preservation and STEP 6 rollback/reapply against the same fixtures. Archive exact SQL revision, outputs and independent verdict. Stage B additionally needs native-Postgres service races: pause vs claim, slot/card uniqueness, lost-CAS rollback, stale classification and owner demotion during search. SQLite does not prove these.

## STEP 6 — Rollback (separate RED approval, never automatic)

Before rollback stop activation and snapshot both tables plus action/job history and the before catalogues. If either table contains rows, any reply action exists or later features depend on 038, **STOP**. Use approved data-preserving forward repair; never delete facts, reply history or a consumed slot to make rollback pass. No CASCADE.

For confirmed unused migration only, after separate approval:

```sql
BEGIN;
SET LOCAL lock_timeout='5s';
LOCK TABLE public.aria_actions IN ACCESS EXCLUSIVE MODE;
LOCK TABLE public.outreach_knowledge,public.outreach_reply_slots IN ACCESS EXCLUSIVE MODE;
DO $rollback$
BEGIN
 IF EXISTS (SELECT 1 FROM public.outreach_knowledge)
 OR EXISTS (SELECT 1 FROM public.outreach_reply_slots)
 OR EXISTS (SELECT 1 FROM public.aria_actions WHERE action_type='reply_outreach') THEN
   RAISE EXCEPTION 'History exists; rollback forbidden';
 END IF;
END;
$rollback$;
DROP TABLE public.outreach_reply_slots;
DROP TABLE public.outreach_knowledge;
DROP FUNCTION public.outreach_freeze_knowledge();
COMMIT;
```

**EXPECT:** two tables/function/policy gone; columns -32, policies -1, originals unchanged. Parent key can safely remain. To restore exact before-state, **only if STEP 0 proves absent before and no later dependency**, separately approve:

```sql
BEGIN;
SET LOCAL lock_timeout='5s';
ALTER TABLE public.outreach_replies DROP CONSTRAINT IF EXISTS outreach_replies_out7_identity_key;
COMMIT;
```

Constraint removal removes its attached index. If Section 2 never committed, verify index is unattached and separately approve `DROP INDEX CONCURRENTLY IF EXISTS public.outreach_replies_out7_identity_key` outside a transaction instead. No cascade, automatic cleanup, or retry loop. Re-run STEP 0/1 and compare exact before-state. Reapply and rerun tests on rehearsal before seeking production approval.

## Mike's plain checklist

1. Review OUT-7's five decisions and RED tests; approve the draft only when satisfied.
2. Wait for independent local/staging evidence, policy-baseline review, preservation and rollback results.
3. Separately approve production SQL; confirm the project selector yourself.
4. Run one step at a time; expect two empty secured tables, **+1 policy / +32 columns**. Stop on any mismatch.
5. No app button changes in Stage A. Future behaviour testing is reply → stopped sequence → one cited owner-approved card → second-reply handover, after implementation/pilot authority.

## Builder verification

`PYTHONDONTWRITEBYTECODE=1 ./check.sh`: PASS, 4 passed / 0 failed / 1 optional eslint skip; backend 2,743 passed, 291 skipped, 25 xfailed, 220 subtests passed. Targeted OUT-7: 25 strict absent-module xfails and 30 local-Postgres skips. Shell syntax and diff whitespace checks pass. Loopback connection to 127.0.0.1:54329 denied by sandbox (Operation not permitted); no SQL executed. No remote SQL, external network, emails, commit or push. SQL execution, RLS/constraints/concurrency, replay/re-paste/rollback, staging parity, live schema, provider threading and UI remain unverified. Independent draft review checked counts/FK targets and prompted test corrections; it is not database execution evidence.
