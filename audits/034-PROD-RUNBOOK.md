# 034 — PRODUCTION RUNBOOK: invoice customer address and supply date

**For:** Mike. **Ticket:** BH-010 (RC1 P0-5). **Migration:**
`backend/migrations/034_invoice_customer_address.sql`.
**Rehearsed:** `audits/034-STAGING-REHEARSAL.md` (9 Oct 2026) — applied,
verified, rolled back to an exact before-snapshot, re-applied.
**Risk:** RED (all production SQL is). Low in practice: two new optional
columns, no data changed, no backfill, nothing removed. Takes about 10 minutes.

**Run every step ONE AT A TIME in the Supabase SQL editor.** Check the
EXPECT before moving on. If anything matches STOP IF, stop and send me the
output. Nothing here is irreversible except the rollback in STEP 5 (which
only exists to undo STEP 2).

**Before you start:** the BH-010 code is NOT deployed yet and must not be.
This migration goes first; the code follows once STEP 4 is done.

---

## STEP 0 — Confirm the project, and capture the before-state (READ-ONLY)

In the top-left project selector, confirm it reads
**business-hero (`oxblcmwhuwtobdhsfgyi`)**, not staging. Then:

```sql
SELECT current_database(),
       (SELECT count(*) FROM public.businesses)       AS businesses,
       (SELECT count(*) FROM public.business_members) AS members,
       (SELECT count(*) FROM public.invoices)         AS invoices,
       (SELECT count(*) FROM information_schema.columns
         WHERE table_schema='public' AND table_name='invoices') AS invoice_columns,
       (SELECT count(*) FROM information_schema.columns
         WHERE table_schema='public' AND table_name='invoices'
           AND column_name IN ('customer_address','supply_date'))  AS already_there;
```

**EXPECT:** `postgres`; a business count matching the admin dashboard; a
non-zero member count; your real invoice count; `invoice_columns` = **30**;
`already_there` = **0**.

**STOP IF:** members is 0 (that is staging), `already_there` is not 0, or
`invoice_columns` is not 30. Send me the row.

Copy this row into a note — it is the before-snapshot.

---

## STEP 1 — Confirm `invoices` uses table-level grants (READ-ONLY)

```sql
SELECT grantee, privilege_type
  FROM information_schema.role_table_grants
 WHERE table_schema='public' AND table_name='invoices'
   AND grantee IN ('anon','authenticated')
 ORDER BY 1, 2;
```

**EXPECT:** rows for both `anon` and `authenticated`, including `SELECT`,
`INSERT` and `UPDATE` (staging also shows DELETE, REFERENCES, TRIGGER and
TRUNCATE — that is a known security finding, BH-001 §6, handled separately).

**STOP IF:** there are **no** `SELECT`/`INSERT`/`UPDATE` rows for
`authenticated`. That would mean `invoices` uses column-level grants, the new
columns would need naming, and the migration needs a change first.

---

## STEP 2 — Apply SECTION 1

Paste **only** SECTION 1 from the migration file — from `BEGIN;` to
`COMMIT;`:

```sql
BEGIN;

ALTER TABLE public.invoices
    ADD COLUMN IF NOT EXISTS customer_address text,
    ADD COLUMN IF NOT EXISTS supply_date date;

COMMENT ON COLUMN public.invoices.customer_address IS
    'Customer address as it stood when the invoice was issued. A snapshot: never updated from the quote afterwards. BH-010.';
COMMENT ON COLUMN public.invoices.supply_date IS
    'Date of supply (tax point) when it differs from the invoice date; NULL means the invoice date. BH-010.';

COMMIT;
```

**EXPECT:** "Success. No rows returned."

**STOP IF:** any error. Nothing will have changed (it is one transaction);
send me the error.

---

## STEP 3 — VERIFY

```sql
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'invoices'
   AND column_name IN ('customer_address', 'supply_date')
 ORDER BY column_name;

SELECT (SELECT count(*) FROM public.invoices) AS invoices,
       (SELECT count(*) FROM pg_policies
         WHERE schemaname='public' AND tablename='invoices') AS invoice_policies;
```

**EXPECT:** exactly two rows — `customer_address | text | YES` and
`supply_date | date | YES`. The invoice count equals STEP 0's, and
`invoice_policies` = **5**.

**STOP IF:** fewer than two rows, `is_nullable` = NO, the invoice count
changed, or the policy count is not 5. If so, run STEP 5 and send me the output.

Then open the app, go to **Finance → Invoices**, and check the list still
loads. (Nothing reads the new columns yet, so nothing should look different.)

---

## STEP 4 — Regenerate the schema dump (READ-ONLY)

This is what lets the BH-010 code pass its safety check, so it matters.

1. Confirm the project selector still reads `oxblcmwhuwtobdhsfgyi`.
2. **Set the SQL editor's row limit to "No limit"** (the dropdown by the
   Run button). The editor's default limit silently cut BH-001's exports at
   100 rows; this dump has about **818 rows**.
3. Run the whole of `scripts/dump-live-schema.sql`.
4. **Download → CSV.**
5. Tell me the downloaded file's name. I parse it as CSV (never `grep`: 033
   STEP 24b) and check it holds the two new columns and about 818 rows. If it
   holds 100, the limit was on — re-run with "No limit".

---

## STEP 5 — ROLLBACK (only if STEP 3 failed)

```sql
BEGIN;
ALTER TABLE public.invoices
    DROP COLUMN IF EXISTS customer_address,
    DROP COLUMN IF EXISTS supply_date;
COMMIT;
```

Then re-run STEP 0's query: `invoice_columns` should be **30** again and
`already_there` **0**. Rehearsed on staging, where it restored every captured
property exactly.

---

## Afterwards

Send me: STEP 0's row, STEP 3's result, and the CSV file name. I will
regenerate `audits/live-schema-public.txt`, record the run here, and then
the BH-010 code can be reviewed and merged.
