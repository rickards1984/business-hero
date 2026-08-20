-- =====================================================================
-- 032 — NULLABLE PER-LINE TAX
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
--
-- Apply ONE SECTION AT A TIME. Run the VERIFY query after each section
-- before moving on. Every section has a ROLLBACK block.
--
-- WHY THIS EXISTS
-- 031 added tax_rate, tax_amount and tax_treatment to both line-item
-- tables as NOT NULL DEFAULT 0 / 'standard'. That makes "this line has
-- no rate recorded" and "this line is zero-rated" the same value.
--
-- It matters as soon as lines can carry different rates from each other.
-- The rule the money engine needs is: use the line's own rate when it has
-- one, and fall back to the quote header only when it has none. With a
-- NOT NULL DEFAULT 0 there is no "none" — a zero-rated line and an
-- unrecorded line are indistinguishable, so the fallback either ignores
-- genuine zero-rating or ignores genuine absence. Both are wrong, and
-- both are silent: subtotal + tax = total still holds either way.
--
-- This is the same trap as `default_tax_rate` in Item 3, one layer down.
--
-- LIVE EVIDENCE (prod, read-only, 20 Aug 2026):
--   * quote_line_items: 40 rows, created 7 Jul .. 19 Aug. EVERY row holds
--     tax_rate=0.00, tax_amount=0.00, tax_treatment='standard' — i.e. the
--     031 column defaults. Not one row has a rate that was actually
--     recorded, because the money engine code is written but NOT DEPLOYED.
--   * invoice_line_items: 0 rows.
--   * All 40 lines belong to quotes with tax_rate 20.00, across 4 quotes.
--     One quote sits at 0.00 and has no line items, so prod does not
--     exercise the zero-rate path. Staging fixtures do — see the rehearsal.
--   * No orphan lines; no line whose parent quote has a NULL tax_rate.
--
-- ORDERING CONSTRAINT — READ THIS BEFORE APPLYING
-- **032 must be applied BEFORE the money engine code is deployed.**
-- The backfill in SECTION 4 identifies never-recorded rows by the fact
-- that they still hold the exact 031 defaults. Once the new code is live
-- it will write genuine zeros for zero-rated lines, which look identical,
-- and the two become impossible to tell apart. STEP 2 of the runbook
-- checks this and stops if any row has moved off the defaults.
-- =====================================================================


-- =====================================================================
-- SECTION 1 — Snapshot the current per-line tax values
-- =====================================================================
-- WHY: every rollback below restores from this. Without it, rolling back
-- SECTION 4 means guessing what the columns held, and the whole point of
-- this migration is that the pre-state is not reconstructable from the
-- post-state — a NULL could have been a 0 or could have been absent.
--
-- Cheap: 40 rows in prod, 0 in invoice_line_items.

CREATE TABLE IF NOT EXISTS public._032_line_tax_before AS
  SELECT 'quote_line_items'::text AS src, id, tax_rate, tax_amount, tax_treatment
    FROM public.quote_line_items
  UNION ALL
  SELECT 'invoice_line_items'::text, id, tax_rate, tax_amount, tax_treatment
    FROM public.invoice_line_items;

-- VERIFY 1 — the snapshot counts must equal the ACTUAL counts.
-- In prod expect: quote_line_items 40, ACTUAL quote_line_items 40,
-- ACTUAL invoice_line_items 0.
-- NOTE: there will be NO 'invoice_line_items' row from the snapshot side.
-- That table is empty, so GROUP BY has nothing to group. A missing row
-- there is correct, not a failure.
--   SELECT src, count(*) FROM public._032_line_tax_before GROUP BY src
--   UNION ALL SELECT 'ACTUAL quote_line_items', count(*) FROM public.quote_line_items
--   UNION ALL SELECT 'ACTUAL invoice_line_items', count(*) FROM public.invoice_line_items
--   ORDER BY 1;
--   -- the snapshot counts must equal the ACTUAL counts

-- ROLLBACK 1:
--   DROP TABLE IF EXISTS public._032_line_tax_before;


-- =====================================================================
-- SECTION 2 — quote_line_items: allow "no rate recorded"
-- =====================================================================
-- Dropping the DEFAULT is not cosmetic — it is half the point. With
-- DEFAULT 0 in place, an INSERT that omits the column silently records a
-- zero rate, which is a statement about tax rather than an absence of
-- one. After this, omitting the column records NULL: nothing claimed.
--
-- Dropping NOT NULL is the other half: it makes NULL representable at all.
--
-- Nothing is written to these columns by deployed code today, so this
-- changes no live behaviour. It changes what the NEXT deploy is able to
-- express.

ALTER TABLE public.quote_line_items
  ALTER COLUMN tax_rate      DROP NOT NULL,
  ALTER COLUMN tax_rate      DROP DEFAULT,
  ALTER COLUMN tax_amount    DROP NOT NULL,
  ALTER COLUMN tax_amount    DROP DEFAULT,
  ALTER COLUMN tax_treatment DROP NOT NULL,
  ALTER COLUMN tax_treatment DROP DEFAULT;

-- VERIFY 2a — expect all three: is_nullable=YES, column_default NULL:
--   SELECT column_name, is_nullable, coalesce(column_default,'(none)') AS default
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='quote_line_items'
--      AND column_name IN ('tax_rate','tax_amount','tax_treatment')
--    ORDER BY column_name;
--
-- VERIFY 2b — no VALUE changed. Expect 40 | 40 | 0 in prod:
--   SELECT (SELECT count(*) FROM public._032_line_tax_before WHERE src='quote_line_items') AS snapshot,
--          count(*) AS matched,
--          count(*) FILTER (WHERE b.tax_rate IS DISTINCT FROM a.tax_rate
--                              OR b.tax_amount IS DISTINCT FROM a.tax_amount
--                              OR b.tax_treatment IS DISTINCT FROM a.tax_treatment) AS changed
--     FROM public._032_line_tax_before b
--     JOIN public.quote_line_items a USING (id)
--    WHERE b.src = 'quote_line_items';
--
-- VERIFY 2c — an omitted column now records NULL, not 0. Expect one row
-- with all three NULL, then roll back:
--   BEGIN;
--     INSERT INTO public.quote_line_items (quote_id, description)
--     SELECT id, '032 probe' FROM public.quotes LIMIT 1;
--     SELECT tax_rate, tax_amount, tax_treatment
--       FROM public.quote_line_items WHERE description = '032 probe';
--   ROLLBACK;

-- ROLLBACK 2 — restores NOT NULL and the defaults. Any NULL written since
-- SECTION 2 was applied must be filled first, and 0 / 'standard' is the
-- only value that fits the old shape. That is LOSSY: a line that meant
-- "no rate recorded" comes back as "zero-rated" and is indistinguishable
-- from then on. Check what you are about to flatten — expect 0:
--   SELECT count(*) FROM public.quote_line_items
--    WHERE tax_rate IS NULL OR tax_amount IS NULL OR tax_treatment IS NULL;
--
--   UPDATE public.quote_line_items
--      SET tax_rate      = coalesce(tax_rate, 0),
--          tax_amount    = coalesce(tax_amount, 0),
--          tax_treatment = coalesce(tax_treatment, 'standard');
--   ALTER TABLE public.quote_line_items
--     ALTER COLUMN tax_rate      SET DEFAULT 0,
--     ALTER COLUMN tax_rate      SET NOT NULL,
--     ALTER COLUMN tax_amount    SET DEFAULT 0,
--     ALTER COLUMN tax_amount    SET NOT NULL,
--     ALTER COLUMN tax_treatment SET DEFAULT 'standard',
--     ALTER COLUMN tax_treatment SET NOT NULL;


-- =====================================================================
-- SECTION 3 — invoice_line_items: the same change
-- =====================================================================
-- Same reasoning. This table is empty in prod (0 rows), so this is purely
-- a shape change with nothing to migrate — which is exactly why it is
-- cheap to do now and expensive to do once it holds issued invoices.

ALTER TABLE public.invoice_line_items
  ALTER COLUMN tax_rate      DROP NOT NULL,
  ALTER COLUMN tax_rate      DROP DEFAULT,
  ALTER COLUMN tax_amount    DROP NOT NULL,
  ALTER COLUMN tax_amount    DROP DEFAULT,
  ALTER COLUMN tax_treatment DROP NOT NULL,
  ALTER COLUMN tax_treatment DROP DEFAULT;

-- VERIFY 3a — expect all three: is_nullable=YES, column_default NULL:
--   SELECT column_name, is_nullable, coalesce(column_default,'(none)') AS default
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='invoice_line_items'
--      AND column_name IN ('tax_rate','tax_amount','tax_treatment')
--    ORDER BY column_name;
--
-- VERIFY 3b — expect 0 rows, unchanged (the table is empty in prod):
--   SELECT count(*) FROM public.invoice_line_items;

-- ROLLBACK 3 — same lossy caveat as ROLLBACK 2. Check first, expect 0:
--   SELECT count(*) FROM public.invoice_line_items
--    WHERE tax_rate IS NULL OR tax_amount IS NULL OR tax_treatment IS NULL;
--
--   UPDATE public.invoice_line_items
--      SET tax_rate      = coalesce(tax_rate, 0),
--          tax_amount    = coalesce(tax_amount, 0),
--          tax_treatment = coalesce(tax_treatment, 'standard');
--   ALTER TABLE public.invoice_line_items
--     ALTER COLUMN tax_rate      SET DEFAULT 0,
--     ALTER COLUMN tax_rate      SET NOT NULL,
--     ALTER COLUMN tax_amount    SET DEFAULT 0,
--     ALTER COLUMN tax_amount    SET NOT NULL,
--     ALTER COLUMN tax_treatment SET DEFAULT 'standard',
--     ALTER COLUMN tax_treatment SET NOT NULL;


-- =====================================================================
-- SECTION 4 — Backfill the rate from the quote header
-- =====================================================================
-- WHAT: every quote line that still holds the 031 defaults gets its
-- parent quote's tax_rate recorded against it, and has its two DERIVED
-- columns set to NULL.
--
-- WHY tax_rate is backfilled: the header rate is a fact about the quote
-- and it is exactly the rate that applied to every one of its lines. All
-- 40 rows in prod belong to quotes at 20.00, so all 40 become 20.00 — a
-- recorded rate. After this, the code's fallback to the quote header can
-- be deleted rather than carried forever, which is the whole point.
--
-- WHY a quote at 0.00 is backfilled to 0.00 and NOT left NULL: that is
-- the distinction this migration creates. 0.00 recorded means "this line
-- is zero-rated and we know it". NULL means "nobody ever said". A quote
-- raised by a business that is not tax-registered is genuinely
-- zero-rated, and it must read that way.
--
-- WHY tax_amount and tax_treatment are set to NULL rather than computed:
--   * tax_amount is DERIVED. Computing it here would mean doing per-line
--     money arithmetic inside a migration, and the result would not match
--     the quote header — quotes.tax_amount was produced by the old float
--     code on the whole discounted subtotal, not per line under D2. That
--     would create a header/line disagreement on historical quotes that
--     nobody asked for. NULL says "not recorded", the calculator derives
--     it from the rate, and no stale figure is invented.
--   * tax_treatment 'standard' was a column default, not an observation.
--     Recording it as fact would assert something about VAT treatment
--     that nobody entered.
--
-- WHY a NULL header propagates as a NULL line rate: if the quote itself
-- never recorded a rate, neither did its lines, and saying so is the
-- honest answer. Leaving those lines at the defaulted 0 would assert
-- zero-rating that nobody entered — the exact confusion this migration
-- removes, reintroduced through the back door. Prod has no such line
-- today (every quote with line items carries a rate), but staging
-- fixtures cover it and the predicate handles it.
--
-- The predicate is the 031 default triple. That only identifies
-- never-recorded rows while the money engine is undeployed — see the
-- ordering constraint in the header, and STEP 2 of the runbook.

UPDATE public.quote_line_items l
   SET tax_rate      = q.tax_rate,
       tax_amount    = NULL,
       tax_treatment = NULL
  FROM public.quotes q
 WHERE q.id = l.quote_id
   AND l.tax_rate = 0
   AND l.tax_amount = 0
   AND l.tax_treatment = 'standard';

-- VERIFY 4a — every backfilled line carries its quote's rate, including
-- NULL where the header has none. Expect 0 rows. IS DISTINCT FROM is
-- deliberate: `NULL <> NULL` is NULL, not false, and would hide a
-- mismatch on exactly the rows this section is about.
--   SELECT l.id, l.tax_rate AS line_rate, q.tax_rate AS quote_rate
--     FROM public.quote_line_items l
--     JOIN public.quotes q ON q.id = l.quote_id
--     JOIN public._032_line_tax_before b ON b.id = l.id AND b.src = 'quote_line_items'
--    WHERE b.tax_rate = 0 AND b.tax_amount = 0 AND b.tax_treatment = 'standard'
--      AND l.tax_rate IS DISTINCT FROM q.tax_rate;
--
-- VERIFY 4b — in prod, expect 40 lines at 20.00 and none left at a
-- defaulted zero:
--   SELECT coalesce(tax_rate::text,'NULL') AS rate, count(*)
--     FROM public.quote_line_items GROUP BY 1 ORDER BY 1;
--
-- VERIFY 4c — the derived columns are now NULL, not a stale zero.
-- Expect backfilled = 40, and both NULL counts = 40 in prod:
--   SELECT count(*) AS backfilled,
--          count(*) FILTER (WHERE tax_amount IS NULL)    AS amount_null,
--          count(*) FILTER (WHERE tax_treatment IS NULL) AS treatment_null
--     FROM public.quote_line_items
--    WHERE tax_rate IS NOT NULL;
--
-- VERIFY 4d — THE POINT OF THE MIGRATION. A recorded zero and an absent
-- rate are now different things. Expect the counts to be reported
-- separately rather than collapsed:
--   SELECT count(*) FILTER (WHERE tax_rate IS NULL)   AS no_rate_recorded,
--          count(*) FILTER (WHERE tax_rate = 0)       AS recorded_zero_rated,
--          count(*) FILTER (WHERE tax_rate > 0)       AS recorded_positive
--     FROM public.quote_line_items;
--   -- prod: 0 | 0 | 40   (no quote at 0.00 has line items today)
--
-- VERIFY 4e — nothing outside the predicate moved. Expect 0:
--   SELECT count(*) FROM public._032_line_tax_before b
--     JOIN public.quote_line_items a USING (id)
--    WHERE b.src = 'quote_line_items'
--      AND NOT (b.tax_rate = 0 AND b.tax_amount = 0 AND b.tax_treatment = 'standard')
--      AND (a.tax_rate IS DISTINCT FROM b.tax_rate
--        OR a.tax_amount IS DISTINCT FROM b.tax_amount
--        OR a.tax_treatment IS DISTINCT FROM b.tax_treatment);

-- ROLLBACK 4 restores every value from the snapshot. Exact, because the
-- snapshot holds the pre-state and it cannot be reconstructed otherwise —
-- a NULL in the live table could have been a 0 or could have been absent.
--
-- AFTER rolling back, confirm with this — expect 0:
--   SELECT count(*) FROM public._032_line_tax_before b
--     JOIN public.quote_line_items a USING (id)
--    WHERE b.src='quote_line_items'
--      AND (a.tax_rate IS DISTINCT FROM b.tax_rate
--        OR a.tax_amount IS DISTINCT FROM b.tax_amount
--        OR a.tax_treatment IS DISTINCT FROM b.tax_treatment);
--
-- ROLLBACK 4:
--   UPDATE public.quote_line_items a
--      SET tax_rate      = b.tax_rate,
--          tax_amount    = b.tax_amount,
--          tax_treatment = b.tax_treatment
--     FROM public._032_line_tax_before b
--    WHERE b.id = a.id AND b.src = 'quote_line_items';


-- =====================================================================
-- SECTION 5 — Drop the snapshot
-- =====================================================================
-- ONLY once every VERIFY above has passed. It is the only record of what
-- the columns held before this migration, and after SECTION 4 that state
-- is not recoverable from the live table.

-- DROP TABLE IF EXISTS public._032_line_tax_before;

-- VERIFY 5 — expect 0:
--   SELECT count(*) FROM pg_tables
--    WHERE schemaname='public' AND tablename='_032_line_tax_before';

-- ROLLBACK 5: none. Once dropped it is gone — which is why it is a
-- separate, deliberate, last step rather than part of SECTION 4.


-- =====================================================================
-- WHAT THIS MIGRATION DOES NOT DO
--   * It does not change any code. The money engine still recomputes
--     per-line tax from the quote header — see audits/FINDINGS.md,
--     "Conversion recomputes per-line tax from the quote-level rate".
--     Making the columns nullable is step 2 of the four-step rule
--     recorded there; steps 1, 3 and 4 remain open.
--   * It does not add a CHECK that a NULL rate implies a NULL amount.
--     The calculator owns that invariant.
--   * It touches no invoice data. invoice_line_items is empty.
--
-- POST-APPLY SMOKE TEST — in the browser, as a normal customer:
--   1. Quotes list loads
--   2. Open an existing quote — totals unchanged from before today
--   3. Create a quote and download the PDF
--   4. Convert a quote to an invoice
-- None of these read the per-line tax columns yet, so all four should be
-- indistinguishable from before. If any of them changes, something reads
-- a column this migration made nullable and was not expected to.
-- =====================================================================
