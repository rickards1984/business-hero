# 032 — PROD RUNBOOK

**Migration:** `backend/migrations/032_nullable_line_tax.sql`
**Target:** Business Hero prod — Supabase project **`oxblcmwhuwtobdhsfgyi`**
**Rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`), applied →
rolled back → re-applied, 20 Aug 2026. All sections, all rollbacks. The
full rollback restored the before-snapshot byte-identically.

---

## How to use this

Work top to bottom. Do not skip. Do not batch.

For every step: paste the SQL, read the result, compare to **EXPECT**.
If it doesn't match EXPECT — **STOP**. Paste the output to Claude Code and
say "prod 032 step N mismatch". Do not continue and do not improvise.

**Confirm the project selector says `oxblcmwhuwtobdhsfgyi` before every
paste.** The staging project is `gzcrsrqmygublveuzqyg`.

**Steps 0 to 2 are read-only. Nothing changes until STEP 3.**

**Elapsed time:** about 10 minutes. **Downtime:** none. No table is
rewritten; 40 rows are updated in STEP 6.

### The one thing that makes this urgent

**032 must be applied BEFORE the money engine code is deployed.**

The backfill in STEP 6 finds never-recorded rows by the fact that they
still hold the exact 031 defaults (`0, 0, 'standard'`). Once the new code
is live it writes genuine zeros for zero-rated lines, which look identical
— and the two become impossible to tell apart, permanently. STEP 2 checks
for this and stops you.

---

## STEP 0 — Prod before-snapshot (READ-ONLY)

This is what a rollback would be diffed against. **Do not skip it.** After
STEP 6 the pre-state is not recoverable from the live table: a NULL could
have been a 0 or could have been absent, and only this tells you which.

```sql
SELECT 'COLUMN' AS kind,
       table_name || ' | ' || column_name AS obj,
       'null=' || is_nullable || ' def=' || coalesce(column_default,'-') AS detail
  FROM information_schema.columns
 WHERE table_schema='public'
   AND table_name IN ('quote_line_items','invoice_line_items')
   AND column_name IN ('tax_rate','tax_amount','tax_treatment')
UNION ALL
SELECT 'LINE', l.id::text,
       'rate=' || coalesce(l.tax_rate::text,'NULL')
       || ' amt=' || coalesce(l.tax_amount::text,'NULL')
       || ' treat=' || coalesce(l.tax_treatment,'NULL')
       || ' quote_rate=' || coalesce(q.tax_rate::text,'NULL')
  FROM public.quote_line_items l
  JOIN public.quotes q ON q.id = l.quote_id
ORDER BY 1, 2;
```

**DO THIS:** click Export → CSV. Save it. Name it `032-prod-before.csv`.

**EXPECT:** 6 `COLUMN` rows (all `null=NO`, `def=0` or `def='standard'`)
and 40 `LINE` rows — 46 total.

**STOP IF:** you get zero rows, or no `LINE` rows — wrong project.
If the `LINE` count is not 40 it is not automatically wrong (quotes get
written every day), but note the real number and use it in place of 40
everywhere below.

---

## STEP 1 — Confirm the shape you are about to change

```sql
SELECT table_name, column_name, is_nullable, coalesce(column_default,'(none)') AS "default"
  FROM information_schema.columns
 WHERE table_schema='public'
   AND table_name IN ('quote_line_items','invoice_line_items')
   AND column_name IN ('tax_rate','tax_amount','tax_treatment')
 ORDER BY table_name, column_name;
```

**EXPECT:** 6 rows, every one `is_nullable = NO`, defaults `0`, `0`,
`'standard'::text` on each table.

**STOP IF:** any row already reads `YES` — 032 has been partly applied.
Do not re-run it blindly; work out how far it got first.

---

## STEP 2 — Pre-flight: has the money engine deployed?

This is the step that protects the whole migration.

```sql
SELECT (SELECT count(*) FROM public.quote_line_items
         WHERE NOT (tax_rate = 0 AND tax_amount = 0 AND tax_treatment = 'standard')) AS qli_non_default,
       (SELECT count(*) FROM public.invoice_line_items
         WHERE NOT (tax_rate = 0 AND tax_amount = 0 AND tax_treatment = 'standard')) AS ili_non_default;
```

**EXPECT:** `0` and `0`.

**STOP IF:** either is non-zero. Something has written a real per-line
rate, which means either the money engine is deployed or a row was edited
by hand. From that point the 031 defaults no longer identify
never-recorded rows, and the STEP 6 backfill would overwrite genuine
zero-rated lines with the quote header's rate. **Stop and get the
predicate re-derived before going any further.**

---

## STEP 3 — Section 1: take the snapshot

```sql
CREATE TABLE IF NOT EXISTS public._032_line_tax_before AS
  SELECT 'quote_line_items'::text AS src, id, tax_rate, tax_amount, tax_treatment
    FROM public.quote_line_items
  UNION ALL
  SELECT 'invoice_line_items'::text, id, tax_rate, tax_amount, tax_treatment
    FROM public.invoice_line_items;
```

Then check:

```sql
SELECT src, count(*) FROM public._032_line_tax_before GROUP BY src
UNION ALL SELECT 'ACTUAL quote_line_items', count(*) FROM public.quote_line_items
UNION ALL SELECT 'ACTUAL invoice_line_items', count(*) FROM public.invoice_line_items
ORDER BY 1;
```

**EXPECT:** three rows —
`ACTUAL invoice_line_items | 0`,
`ACTUAL quote_line_items | 40`,
`quote_line_items | 40`.

**There will be NO `invoice_line_items` row from the snapshot side.**
That table is empty so `GROUP BY` has nothing to group. A missing row
there is correct, not a failure.

**STOP IF:** the snapshot count does not equal the ACTUAL count. Run
`ROLLBACK 1` (`DROP TABLE public._032_line_tax_before;`) and start again.

---

## STEP 4 — Section 2: make quote_line_items nullable

```sql
ALTER TABLE public.quote_line_items
  ALTER COLUMN tax_rate      DROP NOT NULL,
  ALTER COLUMN tax_rate      DROP DEFAULT,
  ALTER COLUMN tax_amount    DROP NOT NULL,
  ALTER COLUMN tax_amount    DROP DEFAULT,
  ALTER COLUMN tax_treatment DROP NOT NULL,
  ALTER COLUMN tax_treatment DROP DEFAULT;
```

Then check no VALUE moved:

```sql
SELECT (SELECT count(*) FROM public._032_line_tax_before WHERE src='quote_line_items') AS snapshot,
       count(*) AS matched,
       count(*) FILTER (WHERE b.tax_rate IS DISTINCT FROM a.tax_rate
                           OR b.tax_amount IS DISTINCT FROM a.tax_amount
                           OR b.tax_treatment IS DISTINCT FROM a.tax_treatment) AS changed
  FROM public._032_line_tax_before b
  JOIN public.quote_line_items a USING (id)
 WHERE b.src = 'quote_line_items';
```

**EXPECT:** `snapshot = 40`, `matched = 40`, `changed = 0`.

**STOP IF:** `changed` is anything but 0. Run `ROLLBACK 2`.

---

## STEP 5 — Section 3: make invoice_line_items nullable

```sql
ALTER TABLE public.invoice_line_items
  ALTER COLUMN tax_rate      DROP NOT NULL,
  ALTER COLUMN tax_rate      DROP DEFAULT,
  ALTER COLUMN tax_amount    DROP NOT NULL,
  ALTER COLUMN tax_amount    DROP DEFAULT,
  ALTER COLUMN tax_treatment DROP NOT NULL,
  ALTER COLUMN tax_treatment DROP DEFAULT;
```

Then check all six columns across both tables:

```sql
SELECT table_name, column_name, is_nullable, coalesce(column_default,'(none)') AS "default"
  FROM information_schema.columns
 WHERE table_schema='public'
   AND table_name IN ('quote_line_items','invoice_line_items')
   AND column_name IN ('tax_rate','tax_amount','tax_treatment')
 ORDER BY table_name, column_name;
```

**EXPECT:** 6 rows, every one `is_nullable = YES` and `default = (none)`.

**STOP IF:** any still reads `NO`, or still shows a default. Re-run the
`ALTER` for the table that did not take.

---

## STEP 6 — Section 4: backfill the rate from the quote header

This is the only step that changes data. 40 rows.

```sql
UPDATE public.quote_line_items l
   SET tax_rate      = q.tax_rate,
       tax_amount    = NULL,
       tax_treatment = NULL
  FROM public.quotes q
 WHERE q.id = l.quote_id
   AND l.tax_rate = 0
   AND l.tax_amount = 0
   AND l.tax_treatment = 'standard';
```

Then check every backfilled line matches its header:

```sql
SELECT l.id, l.tax_rate AS line_rate, q.tax_rate AS quote_rate
  FROM public.quote_line_items l
  JOIN public.quotes q ON q.id = l.quote_id
  JOIN public._032_line_tax_before b ON b.id = l.id AND b.src = 'quote_line_items'
 WHERE b.tax_rate = 0 AND b.tax_amount = 0 AND b.tax_treatment = 'standard'
   AND l.tax_rate IS DISTINCT FROM q.tax_rate;
```

**EXPECT:** `0 rows`.

Then the check this migration exists for:

```sql
SELECT count(*) FILTER (WHERE tax_rate IS NULL) AS no_rate_recorded,
       count(*) FILTER (WHERE tax_rate = 0)     AS recorded_zero_rated,
       count(*) FILTER (WHERE tax_rate > 0)     AS recorded_positive
  FROM public.quote_line_items;
```

**EXPECT in prod:** `0 | 0 | 40`.

Every line belongs to a quote at 20%, so all 40 land in
`recorded_positive`. `no_rate_recorded` is 0 because every quote with
line items has a header rate, and `recorded_zero_rated` is 0 because the
one quote at 0.00 has no lines. **Those two columns being 0 is the
expected prod result, not a sign the backfill did nothing** — the 40 in
the third column is the evidence it worked.

(Staging, which has fixtures for the cases prod lacks, returns
`1 | 2 | 7` — proving a recorded zero and an absent rate are now
genuinely different things.)

**STOP IF:** the first query returns any row, or the three counts do not
sum to your STEP 0 line count. Run `ROLLBACK 4`, then re-run its verify
to confirm you are whole.

---

## STEP 7 — Confirm the derived columns were not left stale

```sql
SELECT count(*) AS with_a_rate,
       count(*) FILTER (WHERE tax_amount IS NULL)    AS amount_null,
       count(*) FILTER (WHERE tax_treatment IS NULL) AS treatment_null
  FROM public.quote_line_items
 WHERE tax_rate IS NOT NULL;
```

**EXPECT:** `40 | 40 | 40`.

`tax_amount` and `tax_treatment` are deliberately NULL, not computed.
They are derived values, and inventing them here would put a figure on
historical quotes that disagrees with their own header — `quotes.tax_amount`
was produced by the old float code across the whole discounted subtotal,
not per line. NULL means "not recorded"; the calculator derives it.

**STOP IF:** either NULL count is below `with_a_rate` — some rows kept a
stale zero. Run `ROLLBACK 4` and stop.

---

## STEP 8 — Section 5: drop the snapshot

**Only once every EXPECT above has matched.** This is the only record of
the pre-state and it is not reconstructable afterwards.

```sql
DROP TABLE IF EXISTS public._032_line_tax_before;
```

**EXPECT:** `DROP TABLE`.

---

## STEP 9 — Final state check

```sql
SELECT 'qli tax_rate nullable' AS check,
       (SELECT is_nullable FROM information_schema.columns
         WHERE table_schema='public' AND table_name='quote_line_items'
           AND column_name='tax_rate') AS value
UNION ALL SELECT 'ili tax_rate nullable',
       (SELECT is_nullable FROM information_schema.columns
         WHERE table_schema='public' AND table_name='invoice_line_items'
           AND column_name='tax_rate')
UNION ALL SELECT 'defaults remaining on the six columns',
       (SELECT count(*)::text FROM information_schema.columns
         WHERE table_schema='public'
           AND table_name IN ('quote_line_items','invoice_line_items')
           AND column_name IN ('tax_rate','tax_amount','tax_treatment')
           AND column_default IS NOT NULL)
UNION ALL SELECT 'lines still at a defaulted zero',
       (SELECT count(*)::text FROM public.quote_line_items
         WHERE tax_rate = 0 AND tax_amount = 0 AND tax_treatment = 'standard')
UNION ALL SELECT 'snapshot table',
       (SELECT count(*)::text FROM pg_tables
         WHERE schemaname='public' AND tablename='_032_line_tax_before')
ORDER BY 1;
```

**EXPECT:**

| check | value |
|---|---|
| defaults remaining on the six columns | `0` |
| ili tax_rate nullable | `YES` |
| lines still at a defaulted zero | `0` |
| qli tax_rate nullable | `YES` |
| snapshot table | `0` |

**STOP IF:** any row differs.

---

## STEP 10 — Browser smoke test

Log in as a **normal customer**, not a platform admin.

1. Quotes list loads
2. Open an existing quote — totals identical to before today
3. Create a quote and download the PDF
4. Convert a quote to an invoice

**EXPECT:** all four behave exactly as they did before you started.

No deployed code reads these three columns yet, so this migration should
be completely invisible in the UI. **STOP IF anything changed** — that
means something reads a column this migration made nullable, and a NULL
is reaching code that expected a number.

---

## STEP 11 — Record it

```
cd ~/Documents/business-hero-2 && mv ~/Downloads/032-prod-before.csv audits/
```

Then have Claude Code append to `audits/FINDINGS.md`: date applied, the
STEP 6 and STEP 9 values, smoke test results, and anything that did not
match EXPECT.

032 is step 2 of the four-step rule recorded in FINDINGS.md under
"Conversion recomputes per-line tax from the quote-level rate". Steps 1, 3
and 4 are still open — the code still recomputes from the header, the
fallback is still unconditional, and there is still no test for a quote
carrying two different per-line rates. **Deploying the money engine is now
unblocked; changing the conversion rule is not yet done.**

---

## If you need to undo everything

Run the `ROLLBACK` blocks in `032_nullable_line_tax.sql` in **reverse
order**: 4, 3, 2, 1. That exact sequence was executed on staging and
returned the database to its pre-032 state byte-identically.

Two caveats, both real:

**ROLLBACK 4 needs the snapshot.** If you have already run STEP 8, the
pre-state is gone and the backfill cannot be undone exactly. That is why
STEP 8 is separate and last.

**ROLLBACK 2 and 3 are lossy if any NULL has been written since.**
Restoring `NOT NULL` means filling NULLs, and `0` / `'standard'` is the
only value that fits — so a line meaning "no rate recorded" comes back as
"zero-rated" and is indistinguishable from then on. Check what you would
flatten first — expect 0:

```sql
SELECT (SELECT count(*) FROM public.quote_line_items
         WHERE tax_rate IS NULL OR tax_amount IS NULL OR tax_treatment IS NULL) AS qli_nulls,
       (SELECT count(*) FROM public.invoice_line_items
         WHERE tax_rate IS NULL OR tax_amount IS NULL OR tax_treatment IS NULL) AS ili_nulls;
```

If that is not 0 and 0, rolling back destroys the distinction this
migration created. Stop and get help instead.
