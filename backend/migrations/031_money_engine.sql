-- =====================================================================
-- 031 — MONEY ENGINE (batch 1)
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
--
-- Apply ONE SECTION AT A TIME. Run the VERIFY query after each section
-- before moving on. Every section has a ROLLBACK block.
--
-- LIVE EVIDENCE THIS IS BUILT ON (prod, read-only, 18 Aug 2026):
--   * quote_line_items has NO business_id. Its RLS policy is a SINGLE
--     PERMISSIVE ALL policy (quote_line_items_member_access) that joins
--     through quotes. It does NOT follow the per-command pattern used by
--     invoices/businesses. invoice_line_items mirrors THIS shape.
--   * quote_line_items grants: anon, authenticated, service_role and
--     postgres each hold DELETE, INSERT, REFERENCES, SELECT, TRIGGER,
--     TRUNCATE, UPDATE — including anon, the public key shipped in the
--     frontend bundle. invoice_line_items deliberately does NOT copy
--     that: SECTION 4 gives anon nothing and authenticated SELECT only.
--     quote_line_items' own exposure is untouched here and remains open.
--   * Default ACLs on schema public already grant arwdDxtm to anon,
--     authenticated and service_role, so ANY new table inherits that set
--     on creation. Section 4 states the grants explicitly anyway, so the
--     privilege surface is auditable in this file rather than implied.
--   * No view or materialized view depends on quote_line_items,
--     invoices, businesses or quote_settings, so the SECTION 2 type
--     change cannot fail on a dependent view.
--   * quote_line_items: 15 rows, unit_cost between 3.50 and 295.00.
--   * invoices: 5 rows, 0 duplicate (business_id, invoice_number).
--     Section 9's unique index applies cleanly.
--   * Only ONE invoice in prod was ever app-generated: MSC's INV-0001
--     (source='quote'). Everything else is legacy CSV or Xero.
--   * businesses has no region/tax_registered/tax_number and no currency
--     column. quote_settings has no invoice counter. invoices has no
--     subtotal/tax_amount/related_invoice_id. Nothing here collides.
--
-- All three open questions from the first draft are now RESOLVED — see
-- the block immediately below. There is no optional section: the grants
-- in SECTION 4 are the final ones.
-- =====================================================================


-- =====================================================================
-- RESOLVED — the three notes from the first draft
-- ---------------------------------------------------------------------
-- N1  discount_percentage is GONE. Both line-item tables carry
--     discount_amount + discount_type ('fixed' | 'percentage'), matching
--     backend/tests/test_discounts.py. One value, one discriminator, no
--     way to express two contradictory discounts on one line.
--
-- N2  unit_cost is numeric(14,4), NOT numeric(12,4). 14 total digits
--     keeps all 10 integer digits the old numeric(12,2) allowed AND adds
--     the 4 decimals. This is a true widening — no ceiling is lowered.
--     (numeric(12,4) would have cut the maximum unit price from
--     9,999,999,999.99 to 99,999,999.9999.)
--
-- N3  quote_line_items now gets tax_rate, tax_amount and tax_treatment
--     too, so a quote line and an invoice line carry the same shape and
--     conversion is a straight copy rather than a recomputation.
-- =====================================================================


-- =====================================================================
-- SECTION 1 — quote_line_items: discount, apportionment and tax columns
-- =====================================================================
-- WHY: spec D5 puts the discount order in one place —
--   line_total -> line discount -> quote discount apportioned pro-rata
--   by line net -> per-line tax on the discounted net
-- The apportioned share and the resulting taxable are stored per line so
-- the invoice can be reproduced exactly as it was issued, rather than
-- recomputed years later by whatever the calculator says then.
--
-- All columns default to a zero that means "no discount", so every one
-- of the 15 existing rows is unchanged in meaning.

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

-- VERIFY 1a — expect exactly 7 rows:
--   apportioned_discount 12,2 | discount_amount 12,2 | discount_type text
--   | tax_amount 12,2 | tax_rate 5,2 | tax_treatment text | taxable 12,2
--   SELECT column_name, data_type, numeric_precision, numeric_scale
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='quote_line_items'
--      AND column_name IN ('discount_amount','discount_type',
--                          'apportioned_discount','taxable',
--                          'tax_rate','tax_amount','tax_treatment')
--    ORDER BY column_name;
--
-- VERIFY 1b — expect 15 rows and 0 non-zero (nothing changed):
--   SELECT count(*) AS rows,
--          count(*) FILTER (WHERE discount_amount <> 0
--                             OR apportioned_discount <> 0
--                             OR tax_amount <> 0) AS non_zero
--     FROM public.quote_line_items;
--
-- VERIFY 1c — expect 15 rows, all 'fixed' and all 'standard':
--   SELECT discount_type, tax_treatment, count(*)
--     FROM public.quote_line_items GROUP BY 1,2;
--
-- VERIFY 1d — discount_percentage must NOT exist. Expect 0:
--   SELECT count(*) FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='quote_line_items'
--      AND column_name='discount_percentage';

-- ROLLBACK 1:
--   ALTER TABLE public.quote_line_items
--     DROP CONSTRAINT IF EXISTS quote_line_items_discount_type_chk;
--   ALTER TABLE public.quote_line_items
--     DROP COLUMN IF EXISTS discount_amount,
--     DROP COLUMN IF EXISTS discount_type,
--     DROP COLUMN IF EXISTS apportioned_discount,
--     DROP COLUMN IF EXISTS taxable,
--     DROP COLUMN IF EXISTS tax_rate,
--     DROP COLUMN IF EXISTS tax_amount,
--     DROP COLUMN IF EXISTS tax_treatment;


-- =====================================================================
-- SECTION 2 — Widen quote_line_items.unit_cost to numeric(14,4)
-- =====================================================================
-- WHY: 47.5 m2 at 3.3333/m2 is 158.3317. At numeric(12,2) the unit price
-- is stored as 3.33 and the line is 15p short before any rounding rule
-- applies. Trades price per metre, per m2, per tonne.
--
-- Postgres rewrites the table for this change. 15 rows. Values are
-- preserved exactly — 3.50 becomes 3.5000, which is the same number.
--
-- numeric(14,4) is a TRUE widening. Precision is total digits, so the old
-- numeric(12,2) held 10 integer digits + 2 decimals; 14,4 holds the same
-- 10 integer digits + 4 decimals. The ceiling (9,999,999,999.99) does not
-- move. Nothing can fail to fit, which is why VERIFY 2a expects 0 on a
-- ceiling that has not changed.

-- VERIFY 2a — PRE-FLIGHT, expect 0. The old and new ceilings are the
-- same, so this is a formality — but run it, because a non-zero here
-- means something is very wrong with the data:
--   SELECT count(*) AS would_not_fit
--     FROM public.quote_line_items WHERE abs(unit_cost) >= 10000000000;

-- Snapshot for the after-comparison (drop it once VERIFY 2c passes):
CREATE TABLE IF NOT EXISTS public._031_unit_cost_before AS
  SELECT id, unit_cost FROM public.quote_line_items;

ALTER TABLE public.quote_line_items
  ALTER COLUMN unit_cost TYPE numeric(14,4);

-- VERIFY 2b — expect numeric | 14 | 4:
--   SELECT data_type, numeric_precision, numeric_scale
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='quote_line_items'
--      AND column_name='unit_cost';
--
-- VERIFY 2c — THE ONE THAT MATTERS. Expect 15 | 15 | 0:
--   every row still present, every value numerically identical.
--   SELECT (SELECT count(*) FROM public._031_unit_cost_before) AS before_rows,
--          count(*) AS matched,
--          count(*) FILTER (WHERE b.unit_cost <> a.unit_cost) AS changed
--     FROM public._031_unit_cost_before b
--     JOIN public.quote_line_items a USING (id);
--
-- VERIFY 2d — line_total must NOT have moved (money stays 2dp):
--   SELECT data_type, numeric_precision, numeric_scale
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='quote_line_items'
--      AND column_name='line_total';
--   -- expect numeric | 12 | 2
--
-- Once 2c passes:
--   DROP TABLE public._031_unit_cost_before;

-- ROLLBACK 2:
--   -- WARNING: this is only lossless while no 4dp value has been written.
--   -- Check first — expect 0:
--   --   SELECT count(*) FROM public.quote_line_items
--   --    WHERE unit_cost <> round(unit_cost, 2);
--   -- If that is non-zero, rolling back SILENTLY ROUNDS those rows and
--   -- the quotes they belong to no longer reproduce their own totals.
--   ALTER TABLE public.quote_line_items
--     ALTER COLUMN unit_cost TYPE numeric(12,2);
--   DROP TABLE IF EXISTS public._031_unit_cost_before;


-- =====================================================================
-- SECTION 3 — Create invoice_line_items
-- =====================================================================
-- WHY: an invoice is currently one flat `amount`. convert_to_invoice
-- copies quote.total and discards every line and the whole tax split. A
-- UK VAT invoice must show the VAT charged; today's structurally cannot.
--
-- Mirrors quote_line_items column-for-column, plus the per-line tax
-- split and the same discount/apportionment columns. unit_cost is
-- numeric(14,4) from birth. Money columns are numeric(12,2).
--
-- tax_treatment is a LABEL. It is stored and displayed and drives no
-- calculation — see backend/tests/test_money_totals.py.

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

-- VERIFY 3a — expect 20 columns, and unit_cost numeric(14,4):
--   SELECT count(*) AS columns FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='invoice_line_items';
--   SELECT column_name, data_type, numeric_precision, numeric_scale
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='invoice_line_items'
--      AND column_name IN ('unit_cost','line_total','tax_amount','taxable')
--    ORDER BY column_name;
--   -- expect line_total/tax_amount/taxable = 12,2 and unit_cost = 14,4
--
-- VERIFY 3d — discount_percentage must NOT exist. Expect 0:
--   SELECT count(*) FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='invoice_line_items'
--      AND column_name='discount_percentage';
--
-- VERIFY 3b — the FK must cascade from invoices:
--   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conrelid='public.invoice_line_items'::regclass AND contype='f';
--   -- expect FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
--
-- VERIFY 3c — expect 0 rows. Nothing backfills historical invoices;
-- the three legacy CSV invoices and the Xero one keep no lines, and the
-- app must still render them (see test_money_totals.TestEmptyLineItems):
--   SELECT count(*) FROM public.invoice_line_items;

-- ROLLBACK 3:
--   DROP TABLE IF EXISTS public.invoice_line_items;


-- =====================================================================
-- SECTION 4 — invoice_line_items: index, RLS, policy, grants
-- =====================================================================
-- CRITICAL: create_all() at boot creates tables with RLS OFF and default
-- grants. This section is what stops invoice_line_items being a publicly
-- reachable table. anon and authenticated hold broad grants by default
-- (see the header), so RLS is the only gate on the client path.
--
-- The policy keeps quote_line_items_member_access's SHAPE — one
-- PERMISSIVE policy for `authenticated`, joining through the parent to
-- reach business_id — but is FOR SELECT, not FOR ALL. It is NOT the
-- per-command pattern used on invoices; that pattern was checked against
-- live state and deliberately not copied.
--
-- WHY FOR SELECT: the grants below give `authenticated` SELECT only, so
-- a FOR ALL policy would describe write access that can never be
-- exercised. Saying ALL and meaning SELECT is how a table ends up
-- writable years later when someone restores a grant and trusts the
-- policy to be the real boundary. The policy now states the intent.
--
-- A FOR SELECT policy carries USING only — Postgres rejects WITH CHECK
-- on SELECT, because there is no new row to check. The predicate is
-- unchanged from the FOR ALL version.

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

-- GRANTS — deliberately TIGHTER than quote_line_items.
--
-- anon gets NOTHING. authenticated gets SELECT and nothing else.
--
-- THIS IS NOT A GRANT-THEN-REVOKE. There is no GRANT above to undo. The
-- default privileges on schema public (pg_default_acl) grant arwdDxtm to
-- anon, authenticated and service_role on EVERY table created here, so
-- invoice_line_items came into existence in SECTION 3 already writable by
-- the public anon key. These REVOKEs remove privileges POSTGRES granted
-- implicitly at CREATE TABLE. Skipping them leaves the table wide open.
--
-- Why read-only for authenticated: invoice lines are the record of what a
-- customer was charged. They are written by the backend, which connects
-- as an elevated role and bypasses both RLS and these grants. No frontend
-- code writes them. A browser session has no business editing an issued
-- invoice's lines, and grants are checked BEFORE policies — so this holds
-- even if the policy above is later loosened by mistake.
--
-- service_role keeps full access: it is the server-side key, never shipped
-- to a browser, and it matches quote_line_items. Its grant is written out
-- explicitly rather than left to the default ACL, so this section is
-- idempotent — re-running it after ROLLBACK 4 restores the same end state
-- instead of leaving service_role with nothing.
REVOKE ALL ON public.invoice_line_items FROM anon;
REVOKE ALL ON public.invoice_line_items FROM authenticated;
GRANT SELECT ON public.invoice_line_items TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.invoice_line_items TO service_role;

-- VERIFY 4a — expect rls_enabled = true:
--   SELECT relrowsecurity AS rls_enabled FROM pg_class
--    WHERE oid='public.invoice_line_items'::regclass;
--
-- VERIFY 4b — expect exactly ONE row:
--   invoice_line_items_member_access | SELECT | PERMISSIVE |
--   {authenticated} | has_using=true | has_check=FALSE
-- has_check MUST be false — a SELECT policy has no WITH CHECK:
--   SELECT policyname, cmd, permissive, roles::text,
--          qual IS NOT NULL AS has_using,
--          with_check IS NOT NULL AS has_check
--     FROM pg_policies
--    WHERE schemaname='public' AND tablename='invoice_line_items';
--
-- VERIFY 4c — THE ONE THAT MATTERS. Expect EXACTLY these rows and no
-- others:
--     authenticated | SELECT
--     service_role  | (its 7 privileges)
-- anon MUST NOT APPEAR AT ALL.
--   SELECT grantee, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='invoice_line_items'
--      AND grantee IN ('anon','authenticated','service_role')
--    ORDER BY grantee, privilege_type;
--
-- VERIFY 4c2 — anon has zero privileges. Expect 0:
--   SELECT count(*) FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='invoice_line_items'
--      AND grantee='anon';
--
-- VERIFY 4c3 — authenticated cannot write. Expect 0:
--   SELECT count(*) FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='invoice_line_items'
--      AND grantee='authenticated'
--      AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE');
--
-- VERIFY 4d — the index exists:
--   SELECT indexname FROM pg_indexes WHERE schemaname='public'
--     AND tablename='invoice_line_items';
--   -- expect invoice_line_items_pkey and idx_invoice_items_invoice

-- ROLLBACK 4 — restores the state the table had at the END of SECTION 3,
-- which is the default-ACL grant set. Do NOT simply revoke: Section 3
-- inherited those privileges from pg_default_acl, so revoking without
-- re-granting leaves service_role unable to reach the table and the
-- backend's service key silently broken.
--   REVOKE ALL ON public.invoice_line_items FROM anon, authenticated, service_role;
--   GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
--     ON public.invoice_line_items TO anon, authenticated, service_role;
--   DROP POLICY IF EXISTS invoice_line_items_member_access ON public.invoice_line_items;
--   ALTER TABLE public.invoice_line_items DISABLE ROW LEVEL SECURITY;
--   DROP INDEX IF EXISTS public.idx_invoice_items_invoice;


-- =====================================================================
-- SECTION 5 — invoices: subtotal, tax_amount, related_invoice_id
-- =====================================================================
-- WHY subtotal/tax_amount: an invoice must show net, tax and gross.
--
-- WHY `amount` IS NOT TOUCHED: it is the GROSS total and stays the gross
-- total. Xero sync, the CEO briefing, accounting summaries and the
-- chase emails all read it. The invariant the tests enforce is
--   subtotal + tax_amount = amount
-- so nothing that reads `amount` today changes behaviour.
--
-- WHY related_invoice_id: the credit-note seam. invoices.invoice_type
-- already exists and already carries 'ACCREC', so the discriminator is
-- in place. This adds the pointer so a future credit note can reference
-- the invoice it credits without a second migration against a table
-- that by then holds real customer money. NOTHING READS IT YET.
--
-- Backfill: existing rows get subtotal = amount and tax_amount = 0. That
-- keeps subtotal + tax_amount = amount true on all 5 existing rows. It
-- does NOT assert those invoices were zero-rated — three are legacy CSV
-- imports with no tax data and one is a Xero record whose split lives in
-- Xero. It asserts only that we do not know a split, and the invariant
-- must still hold.

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

-- VERIFY 5a — expect 3 rows, all numeric/uuid, all nullable:
--   SELECT column_name, data_type, is_nullable
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='invoices'
--      AND column_name IN ('subtotal','tax_amount','related_invoice_id')
--    ORDER BY column_name;
--
-- VERIFY 5b — THE INVARIANT. Expect 5 | 0:
--   SELECT count(*) AS invoices,
--          count(*) FILTER (WHERE subtotal + tax_amount <> amount) AS broken
--     FROM public.invoices;
--
-- VERIFY 5c — `amount` must be untouched. Expect 5 rows, unchanged
-- values (compare against the before-snapshot taken in the runbook):
--   SELECT invoice_number, amount FROM public.invoices ORDER BY invoice_number;
--
-- VERIFY 5d — the self-FK exists and is ON DELETE SET NULL:
--   SELECT pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conname='invoices_related_invoice_id_fkey';
--
-- VERIFY 5e — nothing points anywhere yet. Expect 0:
--   SELECT count(*) FROM public.invoices WHERE related_invoice_id IS NOT NULL;

-- ROLLBACK 5:
--   ALTER TABLE public.invoices
--     DROP CONSTRAINT IF EXISTS invoices_related_invoice_id_fkey;
--   ALTER TABLE public.invoices
--     DROP COLUMN IF EXISTS subtotal,
--     DROP COLUMN IF EXISTS tax_amount,
--     DROP COLUMN IF EXISTS related_invoice_id;


-- =====================================================================
-- SECTION 6 — businesses: region, tax_registered, tax_number
-- =====================================================================
-- WHY: the region resolver needs somewhere to read from, and
-- tax_registered is the difference between a legal invoice and an
-- illegal one. A business that is not VAT-registered must not charge
-- VAT; today the product would make it do so on every quote.
--
-- Defaults are chosen so NOTHING changes for the two live businesses:
-- region 'UK' and tax_registered true is exactly what the code assumes
-- today. This adds the switch; it does not flip it.

ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS region         text    NOT NULL DEFAULT 'UK',
  ADD COLUMN IF NOT EXISTS tax_registered boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS tax_number     text;

ALTER TABLE public.businesses
  ADD CONSTRAINT businesses_region_chk CHECK (region IN ('UK','US'));

-- VERIFY 6a — expect region text NOT NULL default 'UK',
-- tax_registered boolean NOT NULL default true, tax_number text NULL:
--   SELECT column_name, data_type, is_nullable, column_default
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='businesses'
--      AND column_name IN ('region','tax_registered','tax_number')
--    ORDER BY column_name;
--
-- VERIFY 6b — every existing business defaults to UK and registered.
-- Expect 6 | 6 | 6 | 0 (6 businesses in prod, 4 of them test rows):
--   SELECT count(*) AS businesses,
--          count(*) FILTER (WHERE region='UK')        AS uk,
--          count(*) FILTER (WHERE tax_registered)     AS registered,
--          count(*) FILTER (WHERE tax_number IS NOT NULL) AS with_number
--     FROM public.businesses;
--
-- VERIFY 6c — the CHECK rejects anything else:
--   -- expect ERROR: new row violates check constraint
--   -- (run inside a transaction and ROLL BACK)
--   BEGIN;
--     UPDATE public.businesses SET region='FR'
--      WHERE id=(SELECT id FROM public.businesses LIMIT 1);
--   ROLLBACK;

-- ROLLBACK 6:
--   ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_region_chk;
--   ALTER TABLE public.businesses
--     DROP COLUMN IF EXISTS region,
--     DROP COLUMN IF EXISTS tax_registered,
--     DROP COLUMN IF EXISTS tax_number;


-- =====================================================================
-- SECTION 7 — quote_settings: the invoice counter
-- =====================================================================
-- WHY: invoice numbering is COUNT(*) + 1 over a table that also holds
-- Xero-synced invoices, with no unique constraint. This is the column
-- the atomic counter increments:
--   UPDATE quote_settings SET next_invoice_number = next_invoice_number + 1
--    WHERE business_id = :bid
--   RETURNING next_invoice_number - 1, invoice_prefix;
--
-- SEMANTICS: next_invoice_number holds the NEXT number to ISSUE, exactly
-- like the next_quote_number column beside it, which works correctly
-- today (MSC: 3 quotes, max QTE-0003, next_quote_number = 4).
--
-- quote_settings is the right home: it already has UNIQUE (business_id)
-- and already carries the quote counter and prefix.

ALTER TABLE public.quote_settings
  ADD COLUMN IF NOT EXISTS next_invoice_number integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS invoice_prefix      text    NOT NULL DEFAULT 'INV-';

-- VERIFY 7 — expect next_invoice_number integer default 1,
-- invoice_prefix text default 'INV-':
--   SELECT column_name, data_type, is_nullable, column_default
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='quote_settings'
--      AND column_name IN ('next_invoice_number','invoice_prefix')
--    ORDER BY column_name;

-- ROLLBACK 7:
--   ALTER TABLE public.quote_settings
--     DROP COLUMN IF EXISTS next_invoice_number,
--     DROP COLUMN IF EXISTS invoice_prefix;


-- =====================================================================
-- SECTION 8 — Seed the counter from app-generated rows ONLY
-- =====================================================================
-- WHY source='quote' AND external_source IS NULL: those are the only
-- rows this application ever numbered. Seeding from max(invoice_number)
-- across all rows would set New Body's counter to 1004 off three legacy
-- CSV invoices it did not issue, and would let Xero's independent
-- INV-000n series steer the app's counter.
--
-- Expected outcome in prod:
--   Multi Skilled Contractors LTD -> 2   (holds INV-0001, source='quote')
--   every other business          -> 1   (no app-generated invoices)
--
-- RUN VERIFY 8a BEFORE APPLYING. It catches the one case this seed
-- cannot cover: a business that HAS app-generated invoices but NO
-- quote_settings row. Such a business would keep the column default of
-- 1 and immediately reissue a number it has already used. Prod returns
-- zero rows today — New Body has no settings row, but its only
-- non-CSV invoice came from Xero, so it has nothing to preserve.

-- VERIFY 8a — PRE-FLIGHT, expect 0 rows. If not, STOP and create the
-- missing quote_settings rows before seeding:
--   SELECT i.business_id, count(*) AS app_generated_invoices
--     FROM public.invoices i
--    WHERE i.source='quote' AND i.external_source IS NULL
--      AND NOT EXISTS (SELECT 1 FROM public.quote_settings qs
--                       WHERE qs.business_id = i.business_id)
--    GROUP BY 1;

UPDATE public.quote_settings qs
   SET next_invoice_number = COALESCE((
         SELECT max((regexp_replace(i.invoice_number, '\D', '', 'g'))::bigint)
           FROM public.invoices i
          WHERE i.business_id = qs.business_id
            AND i.source = 'quote'
            AND i.external_source IS NULL
            AND i.invoice_number ~ '[0-9]'
       ), 0) + 1;

-- VERIFY 8b — expect MSC = 2. In prod MSC is the only business with a
-- quote_settings row, so expect exactly one row:
--   SELECT b.name, qs.next_invoice_number, qs.invoice_prefix
--     FROM public.quote_settings qs
--     JOIN public.businesses b ON b.id = qs.business_id
--    ORDER BY b.name;
--
-- VERIFY 8c — the seed must have IGNORED the legacy and Xero rows.
-- Expect 0 rows: no counter is above the app-generated maximum + 1.
--   SELECT b.name, qs.next_invoice_number, x.app_max
--     FROM public.quote_settings qs
--     JOIN public.businesses b ON b.id = qs.business_id
--     LEFT JOIN LATERAL (
--       SELECT COALESCE(max((regexp_replace(i.invoice_number,'\D','','g'))::bigint),0) AS app_max
--         FROM public.invoices i
--        WHERE i.business_id = qs.business_id AND i.source='quote'
--          AND i.external_source IS NULL AND i.invoice_number ~ '[0-9]'
--     ) x ON true
--    WHERE qs.next_invoice_number <> x.app_max + 1;
--
-- VERIFY 8d — proof the legacy rows were not used. New Body holds
-- INV-1001..1003; nothing may be seeded to 1004:
--   SELECT count(*) AS seeded_from_legacy
--     FROM public.quote_settings WHERE next_invoice_number > 1000;
--   -- expect 0

-- BEFORE ROLLING BACK SECTION 8, READ THIS:
-- Resetting the counter is safe ONLY while the app has not yet issued an
-- invoice through it. After that, resetting reissues numbers that have
-- already gone to customers. Rolling back Section 7 instead drops the
-- column outright and is cleaner.
-- Check first — expect 0:
--   SELECT count(*) FROM public.invoices
--    WHERE source='quote' AND external_source IS NULL
--      AND created_at > '<the moment 031 was applied>';
--
-- ROLLBACK 8:
--   UPDATE public.quote_settings SET next_invoice_number = 1;


-- =====================================================================
-- SECTION 9 — Partial unique index on app-generated invoice numbers
-- =====================================================================
-- WHY PARTIAL: a full UNIQUE (business_id, invoice_number) would make a
-- provider sync ABORT the moment Xero issued a number the app had also
-- used. The sync upserts ON CONFLICT (business_id, external_source,
-- external_id) — a violation on a different index is unhandled and
-- rolls back the whole sync transaction.
--
-- Restricting the index to external_source IS NULL means synced rows can
-- never violate it, while app-generated numbers stay unique per business.
-- New Body already holds a Xero INV-0001; the app is free to issue its
-- own INV-0001 for that business, which is correct — they are two
-- different series in two different systems.
--
-- RUN VERIFY 9a BEFORE APPLYING.

-- VERIFY 9a — PRE-FLIGHT, expect 0 rows (confirmed on prod 18 Aug 2026):
--   SELECT business_id, invoice_number, count(*)
--     FROM public.invoices WHERE external_source IS NULL
--    GROUP BY 1,2 HAVING count(*) > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_business_number_app
  ON public.invoices (business_id, invoice_number)
  WHERE external_source IS NULL;

-- VERIFY 9b — expect the index, WITH the WHERE clause present:
--   SELECT indexdef FROM pg_indexes
--    WHERE schemaname='public' AND indexname='uq_invoices_business_number_app';
--   -- must end: WHERE (external_source IS NULL)
--
-- VERIFY 9c — a synced duplicate must still be allowed. Expect the
-- INSERT to SUCCEED, then roll back:
--   BEGIN;
--     INSERT INTO public.invoices
--       (business_id, invoice_number, customer_name, due_date, amount,
--        source, external_source, external_id)
--     SELECT business_id, invoice_number, 'RLS probe', current_date, 1.00,
--            'xero', 'xero', 'probe-031'
--       FROM public.invoices WHERE external_source IS NULL LIMIT 1;
--   ROLLBACK;
--
-- VERIFY 9d — an app-generated duplicate must be REJECTED. Expect
-- ERROR: duplicate key value violates unique constraint, then roll back:
--   BEGIN;
--     INSERT INTO public.invoices
--       (business_id, invoice_number, customer_name, due_date, amount, source)
--     SELECT business_id, invoice_number, 'dupe probe', current_date, 1.00, 'quote'
--       FROM public.invoices WHERE external_source IS NULL LIMIT 1;
--   ROLLBACK;

-- ROLLBACK 9:
--   DROP INDEX IF EXISTS public.uq_invoices_business_number_app;


-- =====================================================================
-- POST-APPLY SMOKE TEST — in the browser, as a normal customer:
--   1. Quotes list loads                      (SELECT quotes + line items)
--   2. Open an existing quote, totals correct (unit_cost after widening)
--   3. Create a quote, download the PDF       (INSERT quote_line_items)
--   4. Convert a quote to an invoice          (counter + invoice_line_items)
--   5. Finance -> Invoices shows the new one  (SELECT invoices)
--   6. The three legacy CSV invoices still open with no blank screen
--      (invoices with zero line items)
--   7. Trigger a Xero sync, confirm it completes (partial unique index)
--   8. An invoice's line items RENDER for a customer (authenticated
--      SELECT, FOR SELECT policy) but nothing in the UI can edit them —
--      writes go through the backend only, which bypasses both layers
-- Items 4, 6, 7 and 8 are the ones this migration could plausibly break.
-- =====================================================================
