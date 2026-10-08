-- =====================================================================
-- 034 — INVOICE CUSTOMER ADDRESS AND SUPPLY DATE
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
-- Ticket: BH-010 (RC1 P0-5). Decision: BH-009 design note, decision 1
-- (Mike, 8 Oct 2026).
--
-- STATUS: DRAFT — NOT REHEARSED, NOT APPLIED. RED: Mike runs it, from a
-- runbook (audits/034-PROD-RUNBOOK.md, written at Stage 2), after the
-- staging rehearsal with a proven rollback.
--
-- WHY THIS EXISTS
-- GOV.UK: every invoice, VAT or not, must show the customer's name and
-- address and the date of supply. HMRC VAT Notice 700 §16.3: a full VAT
-- invoice must show the customer's address and the tax point when it
-- differs from the invoice date. `invoices` stores neither
-- (audits/live-schema-public.txt). Quotes store the address
-- (quotes.customer_address) but a quote can change after invoicing, and
-- manual, CSV and Xero invoices have no quote at all.
--
-- WHAT IT DOES
-- Two nullable columns. No backfill: existing invoices keep NULL, and the
-- PDF falls back to the linked quote's address where one exists (BH-009).
-- A snapshot of the address taken at invoicing time is the point — it must
-- not change when the quote is edited later.
--
-- RLS AND GRANTS
-- Adding a column changes neither. `invoices` already has RLS on with
-- membership policies (audits/BH-001-FINDINGS.md). Table-level grants
-- cover new columns automatically; if `invoices` ever moves to column-level
-- grants (as `businesses` did in 033/030b), these columns must be named.
-- STEP 0 of the runbook checks which applies.
--
-- ORDERING
-- Apply BEFORE the BH-010 code deploys: that code writes these columns,
-- and backend/tests/test_schema_conformance.py will refuse it until
-- audits/live-schema-public.txt (regenerated after this runs, 033 STEP 24b
-- method) contains them.
-- =====================================================================


-- ---------------------------------------------------------------------
-- SECTION 1 — add the columns
-- ---------------------------------------------------------------------
BEGIN;

ALTER TABLE public.invoices
    ADD COLUMN IF NOT EXISTS customer_address text,
    ADD COLUMN IF NOT EXISTS supply_date date;

COMMENT ON COLUMN public.invoices.customer_address IS
    'Customer address as it stood when the invoice was issued. A snapshot: never updated from the quote afterwards. BH-010.';
COMMENT ON COLUMN public.invoices.supply_date IS
    'Date of supply (tax point) when it differs from the invoice date; NULL means the invoice date. BH-010.';

COMMIT;


-- ---------------------------------------------------------------------
-- VERIFY SECTION 1 — EXPECT exactly two rows:
--   customer_address | text | YES
--   supply_date      | date | YES
-- STOP IF: fewer than two rows, a different type, or is_nullable = NO.
-- ---------------------------------------------------------------------
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name = 'invoices'
   AND column_name IN ('customer_address', 'supply_date')
 ORDER BY column_name;


-- ---------------------------------------------------------------------
-- ROLLBACK 1 — run ONLY to undo SECTION 1. Drops any data written to the
-- two columns; before BH-010's code deploys there is none.
-- ---------------------------------------------------------------------
-- BEGIN;
-- ALTER TABLE public.invoices
--     DROP COLUMN IF EXISTS customer_address,
--     DROP COLUMN IF EXISTS supply_date;
-- COMMIT;
