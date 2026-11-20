# 045 — PRODUCTION RUNBOOK: the AI model switchboard's choices (Mike's steps)

**For:** Mike. **Ticket:** AI-1 (`docs/AI-1-TICKET.md`). **Migration:** `backend/migrations/045_ai_model_choices.sql`.

**What it does:** adds one empty, backend-only table, `ai_model_choices`.
- It holds the AI model you choose for each of Aria's tasks on the admin page, which comes in AI-1c.
- It records who chose each one and when, and the previous choice (for Revert).
- No browser can read or write it.
- **While it's empty, every task uses exactly the model it used before**, so creating it changes nothing.
- It changes no existing row.

**Rehearsed locally** on the PostgreSQL harness (`scripts/rls-local.sh`, which now replays 040–045), 20 Nov 2026:
- applied it, then applied it again: "already exists", nothing changed;
- row-level security is on, and there are no client grants;
- 5 columns.

`backend/tests/test_ai_models_pg.py` passes against it. It checks that:
- an empty table changes nothing;
- a saved choice is read;
- malformed rows are refused;
- no browser role can reach the table.

**Risk:** RED, as all production SQL is. Low in practice: one new empty table. It waits at most 5 seconds for a lock and stops at 60 seconds. It takes about 3 minutes.

**When:** **before** merging the AI-1a PR. The code works without the table (it logs once and uses the defaults), but the table is where AI-1c will save your choices.

**Staging first (AGENTS.md §7):**
1. Run STEPS 0–2 and the ROLLBACK on **staging (`gzcrsrqmygublveuzqyg`)**, then STEPS 0–2 again.
2. Then run STEPS 0–2 on **production (`business-hero`, `oxblcmwhuwtobdhsfgyi`)**.

**Run each step ONE AT A TIME** in the Supabase SQL editor, and check the EXPECT before moving on. If anything matches STOP IF, stop and send me the output.

---

## STEP 0 — Read-only check

```sql
SELECT to_regclass('public.ai_model_choices') AS choices_before,
       (SELECT count(*) FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `choices_before` is **NULL**;
- note the `columns` figure (C).

**STOP IF:** `choices_before` is not NULL.

---

## STEP 1 — Create (one transaction)

1. Open **`backend/migrations/045_ai_model_choices.sql`**.
2. Select all of it (about 30 lines) and copy it.
3. Paste it into the SQL editor and run it **once**.

**EXPECT:** *Success. No rows returned.*

**STOP IF:** any error, including `canceling statement due to lock timeout`. It is one transaction, so nothing will have changed. Send me the error.

---

## STEP 2 — VERIFY (read-only)

```sql
SELECT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.ai_model_choices'::regclass) AS rls_on,
       (SELECT count(*) FROM information_schema.role_table_grants
          WHERE table_schema = 'public' AND table_name = 'ai_model_choices'
            AND grantee IN ('anon', 'authenticated', 'service_role')) AS client_grants,
       (SELECT count(*) FROM public.ai_model_choices) AS rows,
       (SELECT count(*) FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name NOT LIKE 'zz_%') AS columns;
```

**EXPECT:**
- `rls_on` is **true**;
- `client_grants` is **0**;
- `rows` is **0**;
- `columns` is **C + 5**.

**STOP IF:** any differs.

---

## ROLLBACK (staging rehearsal only, or if told to)

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
DROP TABLE IF EXISTS public.ai_model_choices;
COMMIT;
SELECT to_regclass('public.ai_model_choices') AS gone;
```

**EXPECT:** `gone` is **NULL**.

**On production:** run it only if told to. Once you've made choices on the admin page, dropping the table would make every task go back to its default model.
