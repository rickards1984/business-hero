# 046 — PRODUCTION RUNBOOK: how you write your replies (Mike's steps)

**For:** Mike. **Ticket:** ARIA-1b (`docs/ARIA-PROACTIVE-TICKETS.md`, ARIA-1 §4). **Migration:** `backend/migrations/046_inbox_reply_examples.sql`.

**What it does:** adds one empty, backend-only table, `inbox_reply_examples`.
- Each time you **send** one of Aria's drafted replies, ARIA-1b stores the draft she wrote and the reply you actually sent, edited or not, with the category of the email it answered.
- The few most recent are shown to her as examples of how you write.
- Nothing is stored for a draft you didn't send. You'll be able to see and delete them, and the backend keeps at most 20 per category.
- Deleting a business, or the email a reply answered, deletes those rows too, copied text included.
- No browser can read or write it.
- **While it's empty, nothing changes**, and it changes no existing row.

**Codex review 1** (`audits/046-CODEX-CODE-REVIEW-1.md`) asked for changes, all made:
- the harness's `test` command now runs every PostgreSQL suite, 045's and 046's included;
- the 046 test refuses any database that isn't on this machine;
- each rule is checked against its own database error;
- the email link now **deletes** an example when its email is deleted, where before it kept the copied text.

The fifth point, that an example's email must belong to the same business, is checked in ARIA-1b's code: the database can't enforce it without changing `email_messages`.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`, which now replays 040–046), 25 Nov 2026:
- created by `up`: row-level security on, no client grants, 10 columns, 0 rows;
- `scripts/rls-local.sh test`: 394 passed, including `test_inbox_reply_examples_pg.py` (17), which covers each rule, its limits, unknown business or email, and deleting the business or the email;
- applied again: nothing changed;
- ROLLBACK, then applied again: back as before.

**Risk:** RED, as all production SQL is. Low in practice: one new empty table and its index. It waits at most 5 seconds for a lock and stops at 60 seconds. It takes about 3 minutes.

**When:** any time **before** the ARIA-1b feature PR is merged. That PR uses the table when you send a drafted reply.

**Staging first (AGENTS.md §7):**
1. Run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again.
2. Then run STEPS 0–2 on **production (`business-hero`, `oxblcmwhuwtobdhsfgyi`)**.

**Run each step ONE AT A TIME** in the Supabase SQL editor, and check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

---

## STEP 0 — Read-only check

```sql
SELECT to_regclass('public.inbox_reply_examples') AS examples_before,
       (SELECT count(*) FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `examples_before` is **NULL**;
- note the `columns` figure (C).

**STOP IF:** `examples_before` is not NULL.

---

## STEP 1 — Create (one transaction)

1. Open **`backend/migrations/046_inbox_reply_examples.sql`**.
2. Select all of it (about 35 lines) and copy it.
3. Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.*

**STOP IF:** any error, including `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.inbox_reply_examples'::regclass) AS rls_on,
       (SELECT count(*) FROM information_schema.role_table_grants
          WHERE table_schema = 'public' AND table_name = 'inbox_reply_examples'
            AND grantee IN ('anon', 'authenticated', 'service_role')) AS client_grants,
       (SELECT count(*) FROM public.inbox_reply_examples) AS rows,
       (SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'
          AND indexname = 'inbox_reply_examples_recent') AS recent_index,
       (SELECT count(*) FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `rls_on` is **true**;
- `client_grants` is **0**;
- `rows` is **0**;
- `recent_index` is **1**;
- `columns` is **C + 10**.

**STOP IF:** any differs.

---

## ROLLBACK (staging rehearsal only, or if told to)

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
DROP TABLE IF EXISTS public.inbox_reply_examples;
COMMIT;
SELECT to_regclass('public.inbox_reply_examples') AS gone;
```

**EXPECT:** `gone` is **NULL**.

**On production:** run it only if told to. Once you've sent drafted replies, dropping the table would make Aria forget how you write.
