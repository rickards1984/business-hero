# 031 — PROD RUNBOOK

**Migration:** `backend/migrations/031_money_engine.sql`
**Target:** Business Hero prod — Supabase project **`oxblcmwhuwtobdhsfgyi`**
**Rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`), applied →
rolled back → re-applied, 18 Aug 2026. All sections and all rollbacks.

---

## Before you start

You are tired. That is expected and it is fine. This runbook is written so
you do not have to think — read the step, paste the SQL, compare against
**EXPECT**, and only continue if it matches.

Three rules:

1. **One step at a time.** Never paste two steps at once.
2. **EXPECT must match exactly.** If it does not, go to that step's
   **STOP IF** and follow it. Do not improvise, do not "just try the next
   one", do not fix it yourself at 1am.
3. **If it does not match EXPECT — STOP.** Paste the output to Claude
   Code and say "prod 031 step N mismatch". Do not continue and do not
   improvise. The rollback for every step is in `031_money_engine.sql`
   under `ROLLBACK <n>`.

**Steps 0 to 4 are read-only. Nothing changes until STEP 5.**

**Confirm the project selector says `oxblcmwhuwtobdhsfgyi` before every
paste.** Two Supabase projects exist on this account. The staging one is
`gzcrsrqmygublveuzqyg`. Getting this wrong is the worst outcome available
tonight.

**Elapsed time:** about 20 minutes if nothing goes wrong.
**Downtime:** none expected. STEP 6 briefly rewrites a 15-row table.

---

## STEP 0 — Prod before-snapshot (READ-ONLY)

This is what a rollback would be diffed against. **Do not skip it.**

```sql
SELECT 'COLUMN' AS kind,
       table_name || ' | ' || column_name AS obj,
       data_type || ' ' || coalesce(numeric_precision || ',' || numeric_scale, '-')
         || ' null=' || is_nullable || ' def=' || coalesce(column_default, '-') AS detail
  FROM information_schema.columns
 WHERE table_schema='public'
   AND table_name IN ('quote_line_items','invoices','businesses','quote_settings')
UNION ALL
SELECT 'CONSTRAINT', conrelid::regclass::text || ' | ' || conname,
       pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE connamespace='public'::regnamespace
   AND conrelid::regclass::text IN
       ('quote_line_items','invoices','businesses','quote_settings')
UNION ALL
SELECT 'INDEX', tablename || ' | ' || indexname, indexdef
  FROM pg_indexes
 WHERE schemaname='public'
   AND tablename IN ('quote_line_items','invoices','businesses','quote_settings')
UNION ALL
SELECT 'POLICY', tablename || ' | ' || policyname || ' | ' || cmd,
       coalesce(qual,'~') || ' ||WC|| ' || coalesce(with_check,'~')
  FROM pg_policies
 WHERE schemaname='public'
   AND tablename IN ('quote_line_items','invoices','businesses','quote_settings')
UNION ALL
SELECT 'GRANT', table_name || ' | ' || grantee, privilege_type
  FROM information_schema.role_table_grants
 WHERE table_schema='public'
   AND table_name IN ('quote_line_items','invoices','businesses','quote_settings')
   AND grantee IN ('anon','authenticated','service_role')
UNION ALL
SELECT 'DATA', 'quote_line_items | ' || id::text, unit_cost::text
  FROM public.quote_line_items
UNION ALL
SELECT 'DATA', 'invoices | ' || invoice_number,
       'src=' || source || ' ext=' || coalesce(external_source,'-') || ' amt=' || amount::text
  FROM public.invoices
ORDER BY 1, 2, 3;
```

**DO THIS:** click Export → CSV. Save it. Name it `031-prod-before.csv`.

**EXPECT:** roughly 200–280 rows, including a `DATA` row for each of the
15 quote line items and each of the 5 invoices.

**STOP IF:** you get zero rows, or no `DATA` rows at all — you are in the
wrong project. Go to STEP 1 and come back.

---

## STEP 1 — Confirm you are on the right database

```sql
SELECT current_database(),
       current_setting('cluster_name', true) AS cluster,
       (SELECT count(*) FROM public.invoices)          AS invoices,
       (SELECT count(*) FROM public.quote_line_items)  AS quote_lines,
       (SELECT count(*) FROM public.businesses)        AS businesses;
```

**EXPECT:** `invoices = 5`, `quote_lines = 15`, `businesses = 6`.

**STOP IF:** any count differs. Those are the prod numbers as of
18 Aug 2026. If they have moved a little, that is normal drift — new
quotes get written. If `invoices` is 0 or `businesses` is 3, **you are on
staging**. Close the tab, reopen prod, start again.

---

## STEP 2 — Pre-flight: nothing blocks the unique index

```sql
SELECT business_id, invoice_number, count(*)
  FROM public.invoices
 WHERE external_source IS NULL
 GROUP BY 1, 2
HAVING count(*) > 1;
```

**EXPECT:** `0 rows`.

**STOP IF:** any row comes back. Duplicate app-generated invoice numbers
exist and STEP 13 will fail. Do not delete anything to make it pass —
stop here and work out where the duplicate came from first.

---

## STEP 3 — Pre-flight: every business with app-generated invoices has a settings row

```sql
SELECT i.business_id, count(*) AS app_generated_invoices
  FROM public.invoices i
 WHERE i.source = 'quote' AND i.external_source IS NULL
   AND NOT EXISTS (SELECT 1 FROM public.quote_settings qs
                    WHERE qs.business_id = i.business_id)
 GROUP BY 1;
```

**EXPECT:** `0 rows`.

**STOP IF:** any row comes back. That business would get counter = 1 in
STEP 12 and immediately reissue an invoice number a customer has already
seen. Create its `quote_settings` row first, then come back.

---

## STEP 4 — Pre-flight: no unit_cost exceeds numeric(14,4)

This guards the widening in STEP 6.

```sql
SELECT id, unit_cost
  FROM public.quote_line_items
 WHERE abs(unit_cost) > 9999999999.9999;
```

**EXPECT:** `0 rows`.

**STOP IF:** any row comes back. A price would be truncated by the type
change and a customer's quote would silently change value. Do not widen.
Work out how a value that large got into the column first.

Two things worth knowing so this reads as the formality it should be:

- `unit_cost` is `numeric(12,2)` today, whose ceiling is
  9,999,999,999.99. The new `numeric(14,4)` ceiling is
  9,999,999,999.9999 — strictly larger. So this query is *structurally*
  unable to return a row. A non-zero result means the column is not the
  type this runbook assumes, which is exactly why you run it.
- `invoice_line_items` is deliberately not in this query. It does not
  exist yet — STEP 7 creates it, empty, already at `numeric(14,4)`. There
  is nothing in it to overflow.

Confirm the type assumption while you are here:

```sql
SELECT table_name, numeric_precision, numeric_scale
  FROM information_schema.columns
 WHERE table_schema='public' AND column_name='unit_cost'
 ORDER BY table_name;
```

**EXPECT:** one row — `quote_line_items | 12 | 2`.

**STOP IF:** it is not `12 | 2`, or a second row appears for
`invoice_line_items`. Either this migration has been partly applied
already, or the schema is not what this runbook was written against.
Stop and re-read the state before changing anything.

---

## STEP 5 — Section 1: quote_line_items gains its discount and tax columns

```sql
ALTER TABLE public.quote_line_items
  ADD COLUMN IF NOT EXISTS discount_amount      numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS discount_type        text          NOT NULL DEFAULT 'fixed',
  ADD COLUMN IF NOT EXISTS apportioned_discount numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS taxable              numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tax_rate             numeric(5,2)  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tax_amount           numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tax_treatment        text          NOT NULL DEFAULT 'standard';

ALTER TABLE public.quote_line_items
  ADD CONSTRAINT quote_line_items_discount_type_chk
  CHECK (discount_type IN ('fixed','percentage'));
```

Then check:

```sql
SELECT count(*) AS rows,
       count(*) FILTER (WHERE discount_amount <> 0
                          OR apportioned_discount <> 0
                          OR tax_amount <> 0) AS non_zero,
       count(*) FILTER (WHERE discount_type = 'fixed'
                         AND tax_treatment = 'standard') AS defaults_ok
  FROM public.quote_line_items;
```

**EXPECT:** `rows = 15`, `non_zero = 0`, `defaults_ok = 15`.

**STOP IF:** `non_zero` is anything but 0. The new columns must start
empty. Run `ROLLBACK 1` from the migration file.

---

## STEP 6 — Section 2: widen unit_cost to numeric(14,4)

This rewrites the table. 15 rows, so it is instant.

First, take the comparison snapshot:

```sql
CREATE TABLE IF NOT EXISTS public._031_unit_cost_before AS
  SELECT id, unit_cost FROM public.quote_line_items;
```

Then the change:

```sql
ALTER TABLE public.quote_line_items
  ALTER COLUMN unit_cost TYPE numeric(14,4);
```

Then the check that matters most in this entire runbook:

```sql
SELECT (SELECT count(*) FROM public._031_unit_cost_before) AS before_rows,
       count(*) AS matched,
       count(*) FILTER (WHERE b.unit_cost <> a.unit_cost) AS changed
  FROM public._031_unit_cost_before b
  JOIN public.quote_line_items a USING (id);
```

**EXPECT:** `before_rows = 15`, `matched = 15`, `changed = 0`.

**STOP IF:** `changed` is anything but 0, **or** `matched` is less than
`before_rows`. A customer's price has moved. Run `ROLLBACK 2`
immediately, then this to confirm you are whole again:

```sql
SELECT count(*) FILTER (WHERE b.unit_cost <> a.unit_cost) AS still_changed
  FROM public._031_unit_cost_before b JOIN public.quote_line_items a USING (id);
```

**Leave `_031_unit_cost_before` in place until STEP 15.**

---

## STEP 7 — Section 3: create invoice_line_items

```sql
CREATE TABLE IF NOT EXISTS public.invoice_line_items (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id           uuid NOT NULL
                           REFERENCES public.invoices(id) ON DELETE CASCADE,
    category             text          NOT NULL DEFAULT 'general',
    description          text          NOT NULL,
    quantity             numeric(12,3) NOT NULL DEFAULT 1,
    unit                 text                   DEFAULT 'each',
    unit_cost            numeric(14,4) NOT NULL DEFAULT 0,
    line_total           numeric(12,2) NOT NULL DEFAULT 0,
    markup_percentage    numeric(5,2)           DEFAULT 0,
    markup_amount        numeric(12,2)          DEFAULT 0,
    discount_amount      numeric(12,2) NOT NULL DEFAULT 0,
    discount_type        text          NOT NULL DEFAULT 'fixed',
    apportioned_discount numeric(12,2) NOT NULL DEFAULT 0,
    taxable              numeric(12,2) NOT NULL DEFAULT 0,
    tax_rate             numeric(5,2)  NOT NULL DEFAULT 0,
    tax_amount           numeric(12,2) NOT NULL DEFAULT 0,
    tax_treatment        text          NOT NULL DEFAULT 'standard',
    sort_order           integer                DEFAULT 0,
    group_name           text,
    created_at           timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT invoice_line_items_discount_type_chk
      CHECK (discount_type IN ('fixed','percentage'))
);
```

Then check:

```sql
SELECT (SELECT count(*) FROM information_schema.columns
         WHERE table_schema='public' AND table_name='invoice_line_items') AS columns,
       (SELECT numeric_precision || ',' || numeric_scale
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='invoice_line_items'
           AND column_name='unit_cost') AS unit_cost_type;
```

**EXPECT:** `columns = 20`, `unit_cost_type = 14,4`.

**STOP IF:** the column count is not 20, or the FK failed to create.
Run `ROLLBACK 3` (`DROP TABLE public.invoice_line_items;`) and stop.

---

## STEP 8 — Section 4: index, RLS, policy and grants

**Paste this whole block in one go. Do not stop part-way, do not run it
line by line, and do not walk away in the middle of it.**

The table you created in STEP 7 exists right now with the default
privileges Postgres attaches to every new table in `public` — which means
`anon`, the public key shipped in the browser bundle, can currently write
to it. RLS is off too. This step closes both. Until it finishes, an
invoice-lines table is sitting there publicly writable.

It is wrapped in a transaction so it is all-or-nothing. If any line fails,
nothing is applied and you are back where you started.

```sql
BEGIN;

CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice
  ON public.invoice_line_items USING btree (invoice_id, sort_order);

ALTER TABLE public.invoice_line_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS invoice_line_items_member_access ON public.invoice_line_items;
CREATE POLICY invoice_line_items_member_access
  ON public.invoice_line_items
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.invoices i
     WHERE i.id = invoice_line_items.invoice_id
       AND (public.is_business_member(auth.uid(), i.business_id)
            OR public.is_platform_admin(auth.uid()))));

REVOKE ALL ON public.invoice_line_items FROM anon;
REVOKE ALL ON public.invoice_line_items FROM authenticated;
GRANT SELECT ON public.invoice_line_items TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.invoice_line_items TO service_role;

COMMIT;
```

Two things in there look wrong and are not:

- **No `WITH CHECK` on the policy.** Correct — Postgres rejects one on a
  `FOR SELECT` policy. There is no new row to check.
- **The `service_role` grant looks redundant**, since STEP 7 already gave
  it those privileges implicitly. It is there so this step is safe to
  re-run. Without it, anyone who undoes this step and redoes it leaves
  `service_role` with no access to the table at all.

Then check — one query, covering both halves:

```sql
SELECT (SELECT relrowsecurity FROM pg_class
         WHERE oid='public.invoice_line_items'::regclass) AS rls_enabled,
       (SELECT cmd FROM pg_policies
         WHERE schemaname='public' AND tablename='invoice_line_items') AS policy_cmd,
       (SELECT count(*) FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='invoice_line_items'
           AND grantee='anon') AS anon_privileges,
       (SELECT string_agg(privilege_type, ',' ORDER BY privilege_type)
          FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='invoice_line_items'
           AND grantee='authenticated') AS authenticated_privileges,
       (SELECT count(*) FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='invoice_line_items'
           AND grantee='service_role') AS service_role_privileges;
```

**EXPECT, all five on one row:**

| column | value |
|---|---|
| `rls_enabled` | `true` |
| `policy_cmd` | `SELECT` |
| `anon_privileges` | `0` |
| `authenticated_privileges` | `SELECT` |
| `service_role_privileges` | `7` |

**STOP IF any of the following:**

- `rls_enabled` is false, **or** `anon_privileges` is anything but 0 —
  the table is publicly reachable. Re-run the whole block above. If it is
  still wrong, run `ROLLBACK 3` (`DROP TABLE public.invoice_line_items;`)
  and stop. **Do not leave it and go to bed.**
- `policy_cmd` is `ALL` rather than `SELECT` — an old policy survived the
  `DROP POLICY`. Re-run the block.
- `authenticated_privileges` shows anything beyond `SELECT` — re-run the
  block.
- `service_role_privileges` is 0 — the backend cannot reach the table.
  Re-run the block; the `GRANT ... TO service_role` line fixes it.

---

## STEP 9 — Section 5: invoices gains subtotal, tax_amount, related_invoice_id

```sql
ALTER TABLE public.invoices
  ADD COLUMN IF NOT EXISTS subtotal           numeric(12,2),
  ADD COLUMN IF NOT EXISTS tax_amount         numeric(12,2),
  ADD COLUMN IF NOT EXISTS related_invoice_id uuid;

UPDATE public.invoices
   SET subtotal   = COALESCE(subtotal, amount),
       tax_amount = COALESCE(tax_amount, 0)
 WHERE subtotal IS NULL OR tax_amount IS NULL;

ALTER TABLE public.invoices
  ADD CONSTRAINT invoices_related_invoice_id_fkey
  FOREIGN KEY (related_invoice_id)
  REFERENCES public.invoices(id) ON DELETE SET NULL;
```

Then check:

```sql
SELECT count(*) AS invoices,
       count(*) FILTER (WHERE subtotal + tax_amount <> amount) AS broken,
       count(*) FILTER (WHERE related_invoice_id IS NOT NULL) AS pointing
  FROM public.invoices;
```

**EXPECT:** `invoices = 5`, `broken = 0`, `pointing = 0`.

**STOP IF:** `broken` is not 0. Run `ROLLBACK 5`. `amount` is what every
other part of the system reads — it must keep adding up.

---

## STEP 10 — Section 6: businesses gains region and tax registration

```sql
ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS region         text    NOT NULL DEFAULT 'UK',
  ADD COLUMN IF NOT EXISTS tax_registered boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS tax_number     text;

ALTER TABLE public.businesses
  ADD CONSTRAINT businesses_region_chk CHECK (region IN ('UK','US'));
```

Then check:

```sql
SELECT count(*) AS businesses,
       count(*) FILTER (WHERE region = 'UK')    AS uk,
       count(*) FILTER (WHERE tax_registered)   AS registered
  FROM public.businesses;
```

**EXPECT:** all three numbers equal, and equal to the business count from
STEP 1 (6).

**STOP IF:** `uk` is less than `businesses`. Every existing business must
default to UK — anything else changes behaviour for a live customer.
Run `ROLLBACK 6`.

---

## STEP 11 — Section 7: add the invoice counter

```sql
ALTER TABLE public.quote_settings
  ADD COLUMN IF NOT EXISTS next_invoice_number integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS invoice_prefix      text    NOT NULL DEFAULT 'INV-';
```

Then check:

```sql
SELECT column_name, column_default
  FROM information_schema.columns
 WHERE table_schema='public' AND table_name='quote_settings'
   AND column_name IN ('next_invoice_number','invoice_prefix')
 ORDER BY column_name;
```

**EXPECT:** `invoice_prefix` default `'INV-'::text`,
`next_invoice_number` default `1`.

**STOP IF:** either column is missing. Run `ROLLBACK 7`.

---

## STEP 12 — Section 8: seed the counter

This reads app-generated invoices only. It deliberately ignores the
legacy `INV-100x` CSV rows and anything from Xero.

```sql
UPDATE public.quote_settings qs
   SET next_invoice_number = COALESCE((
         SELECT max((regexp_replace(i.invoice_number, '\D', '', 'g'))::bigint)
           FROM public.invoices i
          WHERE i.business_id = qs.business_id
            AND i.source = 'quote'
            AND i.external_source IS NULL
            AND i.invoice_number ~ '[0-9]'
       ), 0) + 1;
```

Then check:

```sql
SELECT b.name, qs.next_invoice_number, qs.invoice_prefix
  FROM public.quote_settings qs
  JOIN public.businesses b ON b.id = qs.business_id
 ORDER BY b.name;
```

**EXPECT:** `Multi Skilled Contractors LTD | 2 | INV-`.
In prod, MSC is the only business with a `quote_settings` row, so expect
exactly one row back.

Then the safety check:

```sql
SELECT count(*) AS seeded_from_legacy
  FROM public.quote_settings WHERE next_invoice_number > 1000;
```

**EXPECT:** `0`.

**STOP IF:** `seeded_from_legacy` is not 0, or MSC is not exactly 2. The
seed has picked up the legacy CSV series. Run `ROLLBACK 7` (dropping the
columns is cleaner than resetting them) and re-check STEP 3.

---

## STEP 13 — Section 9: the partial unique index

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_business_number_app
  ON public.invoices (business_id, invoice_number)
  WHERE external_source IS NULL;
```

Then check:

```sql
SELECT indexdef FROM pg_indexes
 WHERE schemaname='public' AND indexname='uq_invoices_business_number_app';
```

**EXPECT:** the definition ends with `WHERE (external_source IS NULL)`.

**STOP IF:** the `WHERE` clause is missing. A full unique index will
abort the next Xero sync. Run `ROLLBACK 9` and re-run this step with the
`WHERE` clause.

---

## STEP 14 — Prove the index behaves

Both of these are safe: they roll themselves back.

**13a — a Xero-style duplicate must be ALLOWED:**

```sql
BEGIN;
INSERT INTO public.invoices
  (business_id, invoice_number, customer_name, due_date, amount,
   source, external_source, external_id)
SELECT business_id, invoice_number, 'sync probe', current_date, 1.00,
       'xero', 'xero', 'probe-031'
  FROM public.invoices WHERE external_source IS NULL LIMIT 1;
ROLLBACK;
```

**EXPECT:** `INSERT 0 1`, then `ROLLBACK`. No error.

**13b — an app-generated duplicate must be REJECTED:**

```sql
BEGIN;
INSERT INTO public.invoices
  (business_id, invoice_number, customer_name, due_date, amount, source)
SELECT business_id, invoice_number, 'dupe probe', current_date, 1.00, 'quote'
  FROM public.invoices WHERE external_source IS NULL LIMIT 1;
ROLLBACK;
```

**EXPECT:** `ERROR: duplicate key value violates unique constraint
"uq_invoices_business_number_app"`. **The error is the pass.** Then
`ROLLBACK`.

**STOP IF:** 13a errors, or 13b succeeds. The index is the wrong shape.
Run `ROLLBACK 9` and go back to STEP 13.

---

## STEP 15 — Clean up

```sql
DROP TABLE IF EXISTS public._031_unit_cost_before;
```

**EXPECT:** `DROP TABLE`.

Only do this once STEP 6 passed. It is the only evidence of the
pre-widening prices.

---

## STEP 16 — Final state check

```sql
SELECT 'qli.unit_cost' AS check,
       (SELECT numeric_precision || ',' || numeric_scale
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='quote_line_items'
           AND column_name='unit_cost') AS value
UNION ALL SELECT 'ili.unit_cost',
       (SELECT numeric_precision || ',' || numeric_scale
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='invoice_line_items'
           AND column_name='unit_cost')
UNION ALL SELECT 'ili RLS',
       (SELECT relrowsecurity::text FROM pg_class
         WHERE oid='public.invoice_line_items'::regclass)
UNION ALL SELECT 'ili anon privileges',
       (SELECT count(*)::text FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='invoice_line_items'
           AND grantee='anon')
UNION ALL SELECT 'invoices invariant broken',
       (SELECT count(*) FILTER (WHERE subtotal + tax_amount <> amount)::text
          FROM public.invoices)
UNION ALL SELECT 'MSC counter',
       (SELECT qs.next_invoice_number::text FROM public.quote_settings qs
          JOIN public.businesses b ON b.id = qs.business_id
         WHERE b.name = 'Multi Skilled Contractors LTD')
ORDER BY 1;
```

**EXPECT:**

| check | value |
|---|---|
| ili RLS | `true` |
| ili anon privileges | `0` |
| ili.unit_cost | `14,4` |
| invoices invariant broken | `0` |
| MSC counter | `2` |
| qli.unit_cost | `14,4` |

**STOP IF:** any row differs. Note which, and do not deploy the
application code until it is resolved.

---

## STEP 17 — Browser smoke test

Log in as a **normal customer**, not a platform admin.

1. Quotes list loads
2. Open an existing quote — totals are unchanged from before tonight
3. Create a quote and download the PDF
4. Convert a quote to an invoice — **note the number it issues**
5. Finance → Invoices shows the new invoice
6. Open one of the three legacy CSV invoices — it renders, no blank screen
7. Trigger a Xero sync — it completes without error

**EXPECT:** step 4 issues **INV-0002** for Multi Skilled Contractors.

**STOP IF:** step 4 issues `INV-0001` (the counter did not seed — the
customer now has two invoices with the same number), step 6 is blank
(historical invoices with no line items are not handled), or step 7
errors (the unique index is aborting the sync).

Steps 4, 6 and 7 are the ones this migration could plausibly break.

---

## If you need to undo everything

Run the `ROLLBACK` blocks in `031_money_engine.sql` in **reverse order**:
9, 8, 7, 6, 5, 4, 3, 2, 1. That exact sequence was executed on staging and
returned the database to its pre-031 state with no residue.

One caveat on `ROLLBACK 2`: it is lossless only while no 4-decimal price
has been saved. Check first — expect 0:

```sql
SELECT count(*) FROM public.quote_line_items
 WHERE unit_cost <> round(unit_cost, 2);
```

If that is not 0, rolling back **will silently round real prices**. Stop
and get help instead.

---

## STEP 18 — Record it

```
cd ~/Documents/business-hero-2 && mv ~/Downloads/031-prod-before.csv audits/
```

Then have Claude Code append to `audits/FINDINGS.md`: date applied, which
steps, the STEP 17 final-state values, smoke test results, and anything
skipped or that did not match EXPECT.

Prod and the migration file are now in step. Next: Sonnet implements
against the 172 failing tests in `backend/tests/` until they pass — the
money engine itself. Nothing ships to customers until those are green and
you have walked a quote through to a paid invoice yourself.
