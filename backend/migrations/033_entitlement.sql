-- =====================================================================
-- 033 — ENTITLEMENT (plan vocabulary, feature vocabulary, usage meters)
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
--
-- Source: audits/ENTITLEMENT-SPEC.md — PART A (plan vocabulary),
-- PART B (feature vocabulary + brand_color), PART E (usage meters),
-- and DECISION 2's two columns.
--
-- Apply ONE SECTION AT A TIME. Run the VERIFY queries after each section
-- before moving on. Every section has a ROLLBACK block, and every
-- rollback in this file was executed on staging, not merely written.
--
-- ---------------------------------------------------------------------
-- SCOPE — what is and is not in this file
-- ---------------------------------------------------------------------
--   IN:  SECTION 1  plan_tier CHECK -> ('starter','pro','business','beta')
--        SECTION 2  plan_definitions 'enterprise' -> 'business'
--        SECTION 3  usage_meters table + RLS + grants
--        SECTION 4  businesses.metered_usage_enabled,
--                   businesses.monthly_spend_cap_gbp
--        SECTION 5  grant narrowing so SECTION 4's columns are not
--                   writable from the browser  (see WHY SECTION 5 EXISTS)
--        SECTION 6  PART B, SAFE HALF: brand_color to its column, and
--                   the six key renames. Lossless under any defaults.
--        SECTION 7  PART B, DESTRUCTIVE HALF: R4, remove flags that
--                   merely restate the plan default.
--
--   *** SECTIONS 1-6 MAY SHIP TOGETHER. SECTION 7 MAY NOT. ***
--   Section 7 must land in the SAME deploy as the canonical
--   `_plan_feature_defaults`, or after it. Applied ahead of the code it
--   silently removes eight paid features from the two live businesses.
--   Measured on staging, not assumed. See SECTION 6's warning block.
--
--   OUT: DECISION 4's businesses.billing_exempt. The spec makes it
--        conditional on 030b's grant narrowing, which has NOT shipped to
--        the database (verified below). Not requested for this migration
--        and deliberately absent.
--
-- ---------------------------------------------------------------------
-- LIVE EVIDENCE THIS IS BUILT ON (staging gzcrsrqmygublveuzqyg,
-- read-only, 25 Aug 2026 — captured in audits/033-staging-before.txt)
-- ---------------------------------------------------------------------
--   * businesses_plan_tier_check is
--       CHECK (plan_tier = ANY (ARRAY['starter','pro','elite','beta','paused']))
--     exactly as PART A describes.
--
--   * businesses.brand_color ALREADY EXISTS as a column:
--       text null=YES def='#3B82F6'::text
--     It has existed since the 028 baseline. PART B's "brand_color moves
--     out of feature_flags to its own column" therefore needs a BACKFILL
--     and a key removal, NOT an ADD COLUMN. This is in SECTION 6.
--
--   * plan_definitions has NO foreign key pointing at it, and on staging
--     NO CONSTRAINTS AT ALL — no primary key, no unique index on id,
--     despite supabase/migrations/017 declaring `id TEXT PRIMARY KEY`.
--     So 017 was not the statement that created staging's copy. The
--     SECTION 2 rename cannot cascade or orphan anything, but it also
--     cannot rely on a unique index to stop a duplicate id — hence the
--     NOT EXISTS guard and PRE-FLIGHT 2b.
--
--   * businesses grants are TABLE-LEVEL, not column-level:
--       authenticated=arwdDxtm/postgres
--     and pg_attribute.attacl is NULL for all 26 columns. A table-level
--     UPDATE covers every column INCLUDING COLUMNS ADDED LATER. This is
--     the whole reason SECTION 5 exists.
--
--   * Default ACLs on schema public grant arwdDxtm to anon, authenticated
--     and service_role on every new table, so usage_meters comes into
--     existence in SECTION 3 already writable by the public anon key.
--     SECTION 3's REVOKEs are not undoing a GRANT of ours; they are
--     removing privileges Postgres granted implicitly at CREATE TABLE.
--
--   * usage_meters, metered_usage_enabled, monthly_spend_cap_gbp and
--     billing_exempt do not exist. Nothing here collides.
--
--   * M3 IS SETTLED (confirmed against prod, 25 Aug 2026):
--     supabase/migrations/025 has NOT run on prod. plan_definitions
--     still holds 'enterprise'. SECTION 2 does real work.
--
--   * STAGING HAS NO REPRESENTATIVE DATA. 3 fixture businesses, all
--     plan_tier='starter', all feature_flags='{}', 0 plan_definitions
--     rows. Every section was therefore rehearsed against seeded fixture
--     rows (see audits/033-STAGING-REHEARSAL.md); the DDL and the
--     transforms are proven, the prod data path is proven only against
--     fixtures that mimic prod's recorded shape.
-- =====================================================================


-- =====================================================================
-- WHY SECTION 5 EXISTS — read this before applying anything
-- =====================================================================
-- ENTITLEMENT-SPEC PART E requires that metered_usage_enabled and
-- monthly_spend_cap_gbp be "writable ONLY via the backend — a customer
-- raising their own cap through supabase-js would defeat the purpose".
--
-- `authenticated` holds a TABLE-LEVEL UPDATE grant on businesses. Grants
-- are evaluated BEFORE row-level security, and biz_update_if_owner is
-- column-blind — it authorises the row, not the column. So the moment
-- SECTION 4 lands, every business owner can do this from the browser
-- with the anon key that ships in the frontend bundle:
--
--     await supabase.from('businesses')
--       .update({ metered_usage_enabled: true,
--                 monthly_spend_cap_gbp: 999999 })
--       .eq('id', myBusinessId)
--
-- That is the spend cap turning itself off. SECTION 4 without SECTION 5
-- is a worse state than not shipping SECTION 4 at all, because the cap
-- then LOOKS enforced.
--
-- Postgres cannot revoke a subset of a table-level grant. Narrowing it
-- means REVOKE UPDATE on the table, then re-GRANT UPDATE on an explicit
-- column list. SECTION 5 re-grants the 26 columns that hold UPDATE
-- today and withholds only the two new ones, so NO EXISTING CAPABILITY
-- CHANGES. It is deliberately not the full 030b narrowing.
-- =====================================================================


-- =====================================================================
-- SECTION 1 — plan_tier CHECK -> ('starter','pro','business','beta')
-- =====================================================================
-- PART A, DECISION 1. `business` becomes storable; `elite` and `paused`
-- stop being storable.
--
-- `elite` was the only storable top tier, so _plan_feature_defaults'
-- "business" branch was unreachable and _resolve_plan_from_price's
-- "business" return value would have been rejected on write by the CHECK
-- — a live bug waiting for the first top-tier sale.
--
-- `paused` goes because DECISION 3 separates what was bought (plan_tier)
-- from whether it is paid for (subscription_status). Writing 'paused'
-- into plan_tier destroys the record of the purchase.
--
-- PRE-FLIGHT IS MANDATORY. The ALTER below will fail loudly rather than
-- corrupt anything if a row holds a value leaving the vocabulary, but
-- find out BEFORE you hold the lock, not during.

-- PRE-FLIGHT 1 — run this FIRST. It must return 0 rows. If it returns
-- ANY row, STOP: those businesses need a decided destination tier and
-- that decision is not in this file.
--   SELECT id, name, plan_tier FROM public.businesses
--    WHERE plan_tier NOT IN ('starter','pro','business','beta');

ALTER TABLE public.businesses
  DROP CONSTRAINT IF EXISTS businesses_plan_tier_check;

ALTER TABLE public.businesses
  ADD CONSTRAINT businesses_plan_tier_check
  CHECK (plan_tier IN ('starter','pro','business','beta'));

-- VERIFY 1a — expect exactly one row, and the definition must read
--   CHECK ((plan_tier = ANY (ARRAY['starter'::text, 'pro'::text,
--                                  'business'::text, 'beta'::text])))
-- 'elite' and 'paused' must NOT appear:
--   SELECT conname, pg_get_constraintdef(oid)
--     FROM pg_constraint
--    WHERE conrelid='public.businesses'::regclass
--      AND conname='businesses_plan_tier_check';
--
-- VERIFY 1b — every stored row still satisfies it. Expect 0:
--   SELECT count(*) FROM public.businesses
--    WHERE plan_tier NOT IN ('starter','pro','business','beta');
--
-- VERIFY 1c — the constraint actually bites. This must FAIL with
-- "violates check constraint businesses_plan_tier_check". If it
-- SUCCEEDS the constraint is not doing its job — ROLL BACK.
-- It is wrapped so it can never commit:
--   BEGIN;
--     UPDATE public.businesses SET plan_tier='paused'
--      WHERE id = (SELECT id FROM public.businesses LIMIT 1);
--   ROLLBACK;
--
-- VERIFY 1d — 'business' is now storable. This must SUCCEED, then be
-- discarded. Wrapped so it can never commit:
--   BEGIN;
--     UPDATE public.businesses SET plan_tier='business'
--      WHERE id = (SELECT id FROM public.businesses LIMIT 1);
--     SELECT plan_tier FROM public.businesses
--      WHERE id = (SELECT id FROM public.businesses LIMIT 1);
--     -- expect: business
--   ROLLBACK;

-- ROLLBACK 1 — restores the exact pre-033 constraint, including 'elite'
-- and 'paused'. Safe unconditionally: the old vocabulary is a SUPERSET
-- of the new one on every value except 'business', and no row can hold
-- 'business' unless SECTION 1 committed and something wrote it after.
-- If a row DOES hold 'business' by then, this rollback will fail rather
-- than silently drop the constraint — which is correct.
--   ALTER TABLE public.businesses
--     DROP CONSTRAINT IF EXISTS businesses_plan_tier_check;
--   ALTER TABLE public.businesses
--     ADD CONSTRAINT businesses_plan_tier_check
--     CHECK (plan_tier = ANY (ARRAY['starter'::text, 'pro'::text,
--                                   'elite'::text, 'beta'::text,
--                                   'paused'::text]));


-- =====================================================================
-- SECTION 2 — plan_definitions: 'enterprise' -> 'business'
-- =====================================================================
-- PART A: the third vocabulary. plan_definitions.id holds 'enterprise'
-- where businesses.plan_tier will hold 'business'; the two must agree or
-- a top-tier business has no plan definition to read.
--
-- id is text. supabase/migrations/017 declares it `TEXT PRIMARY KEY`,
-- but staging's copy carries NO primary key and no unique index (see the
-- evidence block). Confirm which is true on prod at PRE-FLIGHT 2b before
-- applying: with no unique index, nothing but the guard below prevents
-- two 'business' rows, and onboarding_api.py:187 does
-- `SELECT * FROM plan_definitions WHERE id = :plan_id` expecting one.
--
-- Verified on staging: NO foreign key anywhere references
-- plan_definitions, so this is a plain UPDATE with no cascade to manage
-- and no orphan to create.
--
-- Guarded three ways:
--   * the WHERE clause is exact, so re-running is a no-op (0 rows)
--   * it will not run if a 'business' row already exists — it should
--     leave both rows alone and be reported, rather than merge two plan
--     definitions into one or create a duplicate id
--   * it touches ONLY the id. features, limits, price and sort_order are
--     left exactly as they are. PART A separately requires that the
--     business tier's features differ from pro's — they are byte-
--     identical today — but that is a DATA decision belonging to the
--     application, not a migration guessing at a price list.

-- PRE-FLIGHT 2a — expect at most one 'enterprise' row and NO 'business'
-- row. If a 'business' row already exists, STOP and report — SECTION 2
-- has probably already been done by supabase/migrations/025 (see the
-- SECTION 2 PROD DIVERGENCE note below):
--   SELECT id, name, monthly_price_gbp, features::text
--     FROM public.plan_definitions
--    WHERE id IN ('enterprise','business');
--
-- PRE-FLIGHT 2b — does prod have a unique id at all? Expect one row
-- naming a PRIMARY KEY or UNIQUE on (id). If it returns 0 rows, prod
-- matches staging and plan_definitions has no uniqueness on its id:
--   SELECT conname, pg_get_constraintdef(oid)
--     FROM pg_constraint WHERE conrelid='public.plan_definitions'::regclass
--   UNION ALL
--   SELECT indexname, indexdef FROM pg_indexes
--    WHERE schemaname='public' AND tablename='plan_definitions';
--
-- PRE-FLIGHT 2c — duplicate ids already present? Expect 0 rows:
--   SELECT id, count(*) FROM public.plan_definitions
--    GROUP BY id HAVING count(*) > 1;
--
-- ---------------------------------------------------------------------
-- SECTION 2 PROD DIVERGENCE — RESOLVE BEFORE APPLYING TO PROD
-- ---------------------------------------------------------------------
-- supabase/migrations/025_rename_elite_to_business.sql already performs
-- most of PART A: it renames elite -> business on businesses.plan_tier,
-- widens the CHECK to include 'business', DELETEs the 'enterprise' and
-- 'elite' plan_definitions rows and inserts starter/pro/business with
-- DISTINCT features (business carries premium_support:true, which is
-- PART A's "its features must then differ from pro").
--
-- 025 has NOT been applied to staging: staging's CHECK still reads
-- ('starter','pro','elite','beta','paused') and plan_definitions has no
-- setup_fee_gbp column, which 025 adds. The ENTITLEMENT-SPEC agrees with
-- staging, not with 025.
--
-- If 025 DID run on prod, SECTION 2 is a no-op there (0 rows updated,
-- every VERIFY still passes) and SECTION 1 reduces to removing 'paused'.
-- If it did not, both sections do their full work. Either way this file
-- is safe — but you must KNOW which, because it decides whether prod's
-- plan_definitions already carries the distinct feature sets PART A
-- requires, or still holds two byte-identical ones.
-- ---------------------------------------------------------------------

UPDATE public.plan_definitions
   SET id = 'business',
       -- The display name goes too, but ONLY if it is still the bare
       -- default 'Enterprise'. PART A exists to end a split between the
       -- internal identifier and the customer-facing name; renaming the
       -- id while the admin dropdown still reads "Enterprise" recreates
       -- exactly that split one layer up. The equality guard means any
       -- bespoke marketing copy someone has written into this column is
       -- left untouched and reported by VERIFY 2b instead of clobbered.
       name = CASE WHEN name = 'Enterprise' THEN 'Business' ELSE name END,
       updated_at = now()
 WHERE id = 'enterprise'
   AND NOT EXISTS (SELECT 1 FROM public.plan_definitions WHERE id = 'business');

-- VERIFY 2a — expect 0 rows named 'enterprise':
--   SELECT count(*) FROM public.plan_definitions WHERE id='enterprise';
--
-- VERIFY 2b — expect the row present under its new id with features,
-- limits, price, sort_order and is_active UNCHANGED from PRE-FLIGHT 2a's
-- output. Compare field by field. `name` should now read 'Business'; if
-- it reads anything else, that is bespoke copy the guard preserved —
-- report it, do not edit it here:
--   SELECT id, name, monthly_price_gbp, sort_order, is_active,
--          features::text, limits::text
--     FROM public.plan_definitions WHERE id='business';
--
-- VERIFY 2c — every plan_definitions id is now in the canonical set.
-- Expect 0 rows. Any row returned is a FOURTH vocabulary and must be
-- reported before continuing:
--   SELECT id FROM public.plan_definitions
--    WHERE id NOT IN ('starter','pro','business','beta');
--
-- VERIFY 2d — row count is unchanged from PRE-FLIGHT. A rename must not
-- create or destroy a plan:
--   SELECT count(*) FROM public.plan_definitions;
--
-- VERIFY 2e — exactly ONE row holds id='business'. Expect 1. This is the
-- check that stands in for the missing unique index:
--   SELECT count(*) FROM public.plan_definitions WHERE id='business';

-- ROLLBACK 2 — same guard in the other direction.
--   UPDATE public.plan_definitions
--      SET id = 'enterprise',
--          name = CASE WHEN name = 'Business' THEN 'Enterprise'
--                      ELSE name END,
--          updated_at = now()
--    WHERE id = 'business'
--      AND NOT EXISTS (SELECT 1 FROM public.plan_definitions
--                       WHERE id = 'enterprise');
-- NOTE: updated_at cannot be restored to its pre-migration value; it is
-- a modification timestamp and this WAS a modification. Everything else
-- round-trips exactly.


-- =====================================================================
-- SECTION 3 — usage_meters
-- =====================================================================
-- PART E: business_id, meter, period (YYYY-MM), value, updated_at,
-- unique on (business_id, meter, period).
--
-- DESIGN NOTES, each of which is a decision and not an accident:
--
-- * meter is TEXT with no CHECK constraint. PART E names
--   receptionist_minutes and outreach_prospects, and DECISION 2 requires
--   the meter be "built generically, not voice-specific" so Aria can use
--   it later. A CHECK here would mean a migration every time a meter is
--   added, which is how the meter stops being generic. The canonical
--   meter list belongs in the application, next to the canonical feature
--   list, for the same reason.
--
-- * period is TEXT 'YYYY-MM', not a date. It is a billing period label,
--   compared for equality and never for range. The CHECK enforces the
--   shape so a malformed period cannot silently create a second bucket
--   that no reset will ever clear.
--
-- * value is numeric(14,4), not integer. receptionist_minutes accrues
--   from actual call duration (PART E) and calls do not end on whole
--   minutes. An integer column would round every call and the error
--   would compound across a month, in our favour or the customer's
--   depending on the rounding — both are wrong. 4 decimal places match
--   031's unit_cost.
--
-- * DECISION 2's overage spend gets its OWN meter row rather than a
--   column here, per PART E: "overage spend accrues to its own meter so
--   it can be shown, capped and billed independently of allowance
--   usage". That is a meter name, not a schema change.
--
-- * ON DELETE CASCADE on business_id: usage is meaningless without the
--   business, and leaving orphan meter rows would corrupt any
--   period-wide aggregate.
--
-- * created_at as well as updated_at: PART E asks only for updated_at,
--   but when a meter bucket first opened is a real question when
--   reconciling a disputed bill, and it costs 8 bytes.

CREATE TABLE IF NOT EXISTS public.usage_meters (
  id          uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid           NOT NULL
                             REFERENCES public.businesses(id) ON DELETE CASCADE,
  meter       text           NOT NULL,
  period      text           NOT NULL,
  value       numeric(14,4)  NOT NULL DEFAULT 0,
  created_at  timestamptz    NOT NULL DEFAULT now(),
  updated_at  timestamptz    NOT NULL DEFAULT now()
);

-- Postgres has no ADD CONSTRAINT IF NOT EXISTS, so each ADD is preceded
-- by a DROP IF EXISTS. That makes this section safe to re-paste — which
-- someone will do at 1am after losing their place. The whole section
-- runs as one transaction in the Supabase SQL editor, so the constraint
-- is never actually absent from a committed state.
ALTER TABLE public.usage_meters
  DROP CONSTRAINT IF EXISTS usage_meters_period_chk;
ALTER TABLE public.usage_meters
  ADD CONSTRAINT usage_meters_period_chk
  CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$');

ALTER TABLE public.usage_meters
  DROP CONSTRAINT IF EXISTS usage_meters_meter_nonempty_chk;
ALTER TABLE public.usage_meters
  ADD CONSTRAINT usage_meters_meter_nonempty_chk
  CHECK (length(btrim(meter)) > 0);

ALTER TABLE public.usage_meters
  DROP CONSTRAINT IF EXISTS usage_meters_value_nonneg_chk;
ALTER TABLE public.usage_meters
  ADD CONSTRAINT usage_meters_value_nonneg_chk
  CHECK (value >= 0);

-- The uniqueness PART E requires. This is what makes the increment an
-- atomic INSERT ... ON CONFLICT (business_id, meter, period) DO UPDATE
-- rather than a read-modify-write that loses concurrent calls.
CREATE UNIQUE INDEX IF NOT EXISTS usage_meters_biz_meter_period_uq
  ON public.usage_meters USING btree (business_id, meter, period);

-- Serves "show me this business's current period" — the PART E
-- requirement that usage be visible BEFORE the limit is reached.
CREATE INDEX IF NOT EXISTS idx_usage_meters_biz_period
  ON public.usage_meters USING btree (business_id, period);

ALTER TABLE public.usage_meters ENABLE ROW LEVEL SECURITY;

-- Policy shape copied from 031's invoice_line_items: ONE permissive
-- SELECT policy for authenticated. FOR SELECT and not FOR ALL because
-- the grants below give authenticated SELECT only, and a FOR ALL policy
-- would describe write access that can never be exercised — which is how
-- a table ends up writable years later when someone restores a grant and
-- trusts the policy to be the real boundary.
--
-- Members read their own business's usage. Writes are backend-only: the
-- backend connects as an elevated role and bypasses both RLS and grants.
DROP POLICY IF EXISTS usage_meters_member_read ON public.usage_meters;
CREATE POLICY usage_meters_member_read
  ON public.usage_meters
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), usage_meters.business_id)
         OR public.is_platform_admin(auth.uid()));

-- GRANTS. anon gets NOTHING. authenticated gets SELECT only.
--
-- These REVOKEs are NOT undoing a GRANT of ours — there is none above.
-- pg_default_acl grants arwdDxtm to anon, authenticated and service_role
-- on every table created in schema public, so usage_meters was already
-- fully writable by the public anon key the instant CREATE TABLE ran.
-- Skipping these leaves a table where any browser can zero its own
-- usage counter.
--
-- service_role is granted explicitly rather than left to the default ACL
-- so this section is idempotent: re-running it after ROLLBACK 3 restores
-- the same end state instead of leaving service_role with nothing.
REVOKE ALL ON public.usage_meters FROM anon;
REVOKE ALL ON public.usage_meters FROM authenticated;
GRANT SELECT ON public.usage_meters TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.usage_meters TO service_role;

-- VERIFY 3a — expect 7 columns with these types:
--   business_id uuid NO | created_at timestamptz NO | id uuid NO
--   | meter text NO | period text NO | updated_at timestamptz NO
--   | value numeric 14,4 NO
--   SELECT column_name, data_type, numeric_precision, numeric_scale,
--          is_nullable
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='usage_meters'
--    ORDER BY column_name;
--
-- VERIFY 3b — expect rls_enabled = true:
--   SELECT relrowsecurity AS rls_enabled FROM pg_class
--    WHERE oid='public.usage_meters'::regclass;
--
-- VERIFY 3c — expect exactly ONE row:
--   usage_meters_member_read | SELECT | PERMISSIVE | {authenticated}
--   | has_using=true | has_check=false
-- has_check MUST be false — a SELECT policy has no WITH CHECK:
--   SELECT policyname, cmd, permissive, roles::text,
--          qual IS NOT NULL AS has_using,
--          with_check IS NOT NULL AS has_check
--     FROM pg_policies
--    WHERE schemaname='public' AND tablename='usage_meters';
--
-- VERIFY 3d — THE ONE THAT MATTERS. Expect EXACTLY:
--     authenticated | SELECT
--     service_role  | (its 7 privileges)
-- anon MUST NOT APPEAR AT ALL:
--   SELECT grantee, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='usage_meters'
--      AND grantee IN ('anon','authenticated','service_role')
--    ORDER BY grantee, privilege_type;
--
-- VERIFY 3e — anon has zero privileges. Expect 0:
--   SELECT count(*) FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='usage_meters'
--      AND grantee='anon';
--
-- VERIFY 3f — authenticated cannot write. Expect 0:
--   SELECT count(*) FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='usage_meters'
--      AND grantee='authenticated'
--      AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE');
--
-- VERIFY 3g — expect 3 indexes: usage_meters_pkey,
-- usage_meters_biz_meter_period_uq, idx_usage_meters_biz_period:
--   SELECT indexname FROM pg_indexes
--    WHERE schemaname='public' AND tablename='usage_meters'
--    ORDER BY indexname;
--
-- VERIFY 3h — the constraints actually bite. Each of these must FAIL.
-- All are wrapped so none can commit. Substitute a real business id.
--   -- bad period shape -> usage_meters_period_chk
--   BEGIN;
--     INSERT INTO public.usage_meters (business_id, meter, period, value)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1),
--             'receptionist_minutes', '2026-13', 1);
--   ROLLBACK;
--   -- negative value -> usage_meters_value_nonneg_chk
--   BEGIN;
--     INSERT INTO public.usage_meters (business_id, meter, period, value)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1),
--             'receptionist_minutes', '2026-08', -1);
--   ROLLBACK;
--   -- duplicate triple -> usage_meters_biz_meter_period_uq
--   BEGIN;
--     INSERT INTO public.usage_meters (business_id, meter, period, value)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1),
--             'receptionist_minutes', '2026-08', 1);
--     INSERT INTO public.usage_meters (business_id, meter, period, value)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1),
--             'receptionist_minutes', '2026-08', 2);
--   ROLLBACK;
--
-- VERIFY 3i — the atomic increment works, which is the whole point of
-- the unique index. Must end with value = 3.5. Wrapped, never commits:
--   BEGIN;
--     INSERT INTO public.usage_meters (business_id, meter, period, value)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1),
--             'receptionist_minutes', '2026-08', 1.5)
--     ON CONFLICT (business_id, meter, period)
--     DO UPDATE SET value = usage_meters.value + EXCLUDED.value,
--                   updated_at = now();
--     INSERT INTO public.usage_meters (business_id, meter, period, value)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1),
--             'receptionist_minutes', '2026-08', 2.0)
--     ON CONFLICT (business_id, meter, period)
--     DO UPDATE SET value = usage_meters.value + EXCLUDED.value,
--                   updated_at = now();
--     SELECT value FROM public.usage_meters
--      WHERE meter='receptionist_minutes' AND period='2026-08';
--     -- expect: 3.5000
--   ROLLBACK;
--
-- VERIFY 3j — the table is empty. Expect 0. A migration must not seed
-- usage:
--   SELECT count(*) FROM public.usage_meters;

-- ROLLBACK 3 — drops the table outright. This is the only rollback in
-- this file that DESTROYS DATA, and after the application starts writing
-- meters that data is billing evidence.
--
-- Before running it, capture what you are about to destroy:
--   SELECT * FROM public.usage_meters ORDER BY business_id, meter, period;
--
-- DROP TABLE removes the indexes, the constraints and the policy with
-- it; there is nothing else to undo. The grants die with the table.
--   DROP TABLE IF EXISTS public.usage_meters;


-- =====================================================================
-- SECTION 4 — businesses: metered_usage_enabled, monthly_spend_cap_gbp
-- =====================================================================
-- PART E / DECISION 2.
--
-- metered_usage_enabled: false by default. Metered overage is OPT-IN.
-- DECISION 2 is explicit that the customer chooses to continue past
-- their allowance at 45p/min; defaulting this to true would bill people
-- who never agreed to be billed. NOT NULL so there is no third state —
-- a NULL here would have to be interpreted somewhere, and it would be
-- interpreted differently in two places within a year.
--
-- monthly_spend_cap_gbp: NULLABLE, and NULL is meaningful. It means "no
-- cap has been chosen", which is only reachable while
-- metered_usage_enabled is false. DECISION 2's £100 default applies at
-- the moment metering is ENABLED without an explicit choice — that is an
-- application rule about a user action, not a column default, and a
-- DEFAULT 100 here would silently hand a £100 cap to all businesses
-- including ones that never opted in.
--
-- numeric(10,2): pounds. 10 total digits allows a cap up to
-- 99,999,999.99, which is beyond absurd and costs nothing.
--
-- THE PAIRED CHECK is the one that matters. It makes the unsafe
-- combination unrepresentable: metering ON with no cap is exactly the
-- unbounded bill DECISION 2 exists to prevent, for the customer and for
-- us. Enforcing it in the application only means one missed code path
-- is an uncapped account.
--
-- It is added NOT VALID and then VALIDATED as a separate statement so
-- the table is not scanned under an ACCESS EXCLUSIVE lock. With 6 rows
-- in prod this is theatre; it is written this way because the pattern is
-- what should be copied when the table is not 6 rows.

ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS metered_usage_enabled boolean       NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS monthly_spend_cap_gbp numeric(10,2);

-- DROP IF EXISTS first, for the same reason as SECTION 3: no
-- ADD CONSTRAINT IF NOT EXISTS exists, and this section must survive
-- being pasted twice.
ALTER TABLE public.businesses
  DROP CONSTRAINT IF EXISTS businesses_spend_cap_chk;

ALTER TABLE public.businesses
  ADD CONSTRAINT businesses_spend_cap_chk
  CHECK (
    (metered_usage_enabled = false)
    OR (monthly_spend_cap_gbp IS NOT NULL AND monthly_spend_cap_gbp > 0)
  ) NOT VALID;

ALTER TABLE public.businesses
  VALIDATE CONSTRAINT businesses_spend_cap_chk;

-- VERIFY 4a — expect exactly 2 rows:
--   metered_usage_enabled boolean null=NO def=false
--   monthly_spend_cap_gbp numeric 10,2 null=YES def=(none)
-- `def=(none)` means column_default IS NULL. An explicit `DEFAULT NULL`
-- was deliberately NOT written: it is a no-op that records the string
-- 'NULL::numeric' in the catalog, and a VERIFY that has to explain why
-- its own expected value looks like a mistake is a VERIFY nobody reads.
--   SELECT column_name, data_type, numeric_precision, numeric_scale,
--          is_nullable, coalesce(column_default,'(none)')
--     FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='businesses'
--      AND column_name IN ('metered_usage_enabled','monthly_spend_cap_gbp')
--    ORDER BY column_name;
--
-- VERIFY 4b — every existing business is opted OUT with no cap. Expect
-- one row: total = the full business count, metered = 0, capped = 0:
--   SELECT count(*) AS total,
--          count(*) FILTER (WHERE metered_usage_enabled) AS metered,
--          count(*) FILTER (WHERE monthly_spend_cap_gbp IS NOT NULL) AS capped
--     FROM public.businesses;
--
-- VERIFY 4c — the constraint exists and is VALIDATED (convalidated=true).
-- A NOT VALID constraint is not enforced against existing rows and must
-- not be left in that state:
--   SELECT conname, convalidated, pg_get_constraintdef(oid)
--     FROM pg_constraint
--    WHERE conrelid='public.businesses'::regclass
--      AND conname='businesses_spend_cap_chk';
--
-- VERIFY 4d — metering ON with no cap is REJECTED. This must FAIL with
-- "violates check constraint businesses_spend_cap_chk". Wrapped:
--   BEGIN;
--     UPDATE public.businesses SET metered_usage_enabled = true
--      WHERE id = (SELECT id FROM public.businesses LIMIT 1);
--   ROLLBACK;
--
-- VERIFY 4e — metering ON with a cap is ACCEPTED. Must SUCCEED. Wrapped:
--   BEGIN;
--     UPDATE public.businesses
--        SET metered_usage_enabled = true, monthly_spend_cap_gbp = 100.00
--      WHERE id = (SELECT id FROM public.businesses LIMIT 1);
--   ROLLBACK;
--
-- VERIFY 4f — a zero or negative cap is REJECTED. Must FAIL. Wrapped:
--   BEGIN;
--     UPDATE public.businesses
--        SET metered_usage_enabled = true, monthly_spend_cap_gbp = 0
--      WHERE id = (SELECT id FROM public.businesses LIMIT 1);
--   ROLLBACK;

-- ROLLBACK 4 — drop the constraint FIRST, then the columns. Dropping the
-- columns alone would fail while the constraint depends on them.
--   ALTER TABLE public.businesses
--     DROP CONSTRAINT IF EXISTS businesses_spend_cap_chk;
--   ALTER TABLE public.businesses
--     DROP COLUMN IF EXISTS metered_usage_enabled,
--     DROP COLUMN IF EXISTS monthly_spend_cap_gbp;
-- NOTE: if SECTION 5 has been applied, run ROLLBACK 5 BEFORE this one.
-- ROLLBACK 5 restores the table-level grant and does not name columns,
-- so the order is not strictly forced — but running 5 then 4 keeps the
-- grant state consistent at every intermediate step.


-- =====================================================================
-- SECTION 5 — narrow the businesses UPDATE grant to exclude SECTION 4's
--             columns  (REQUIRED — see WHY SECTION 5 EXISTS, above)
-- =====================================================================
-- Without this, SECTION 4's spend cap is writable from the browser and
-- therefore is not a cap.
--
-- Postgres has no "revoke one column from a table-level grant". The only
-- way is to drop the table-level UPDATE and re-grant column by column.
--
-- The 26 columns re-granted below are EXACTLY the columns `authenticated`
-- holds UPDATE on today (verified: relacl authenticated=arwdDxtm,
-- pg_attribute.attacl NULL on all 26 — a table-level grant covering all
-- columns). Nothing an owner can write today stops being writable. The
-- ONLY change is that metered_usage_enabled and monthly_spend_cap_gbp
-- are absent from the list.
--
-- THIS IS NOT 030b. 030b narrows this grant properly — plan_tier,
-- is_active, feature_flags, api_key and subscription_status have no
-- business being browser-writable either, and they remain so after this
-- section. This section holds the line at "033 does not make things
-- worse". Do not read it as the security fix being done.
--
-- INSERT is deliberately untouched, and it is table-level, so it DOES
-- extend to the two new columns — an INSERT of a business from the
-- browser can still set them (subject to businesses_spend_cap_chk).
-- Verified, not assumed: VERIFY 5d returns 28 for INSERT, not 26.
-- Business creation from the browser is already 030b's problem via
-- AdminDashboard.tsx:380, and narrowing INSERT here would change
-- behaviour beyond "no worse than today". The UPDATE path is the one
-- that matters for an EXISTING customer raising their own cap, and that
-- is what this section closes.
--
-- anon is untouched: it holds rtm (SELECT/TRIGGER/REFERENCES) and no
-- UPDATE, so it has nothing to narrow.
--
-- service_role is untouched: it is the server-side key, never shipped to
-- a browser, and the backend needs to write these columns.

REVOKE UPDATE ON public.businesses FROM authenticated;

GRANT UPDATE (
  id, name, timezone, api_key, created_at, logo_url, plan_tier, is_active,
  trial_ends_at, feature_flags, limits, stripe_customer_id,
  stripe_subscription_id, subscription_status, current_period_end,
  cancel_at_period_end, last_stripe_event_at, onboarding_completed,
  onboarding_completed_at, onboarded_by, brand_color, owner_whatsapp,
  ceo_briefing_enabled, region, tax_registered, tax_number
) ON public.businesses TO authenticated;

-- VERIFY 5a — THE ONE THAT MATTERS. Expect 26, and the two new columns
-- must NOT be in the list:
--   SELECT count(*) AS n_update_cols,
--          string_agg(column_name, ', ' ORDER BY column_name) AS cols
--     FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='businesses'
--      AND grantee='authenticated' AND privilege_type='UPDATE';
--
-- VERIFY 5b — expect 0. This is the criterion the section exists for:
--   SELECT count(*) FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='businesses'
--      AND grantee='authenticated' AND privilege_type='UPDATE'
--      AND column_name IN ('metered_usage_enabled','monthly_spend_cap_gbp');
--
-- VERIFY 5c — the table-level UPDATE is gone, replaced by column grants.
-- authenticated's relacl entry must now read `arDxtm` (no `w`), and
-- pg_attribute.attacl must be NON-NULL for the 26 granted columns and
-- NULL for the two new ones:
--   SELECT unnest(relacl)::text FROM pg_class
--    WHERE oid='public.businesses'::regclass;
--   -- expect authenticated=ardDxtm/postgres
--   -- (arwdDxtm with the lowercase w removed; the lowercase d is DELETE
--   --  and stays, the uppercase D is TRUNCATE)
--   SELECT attname, attacl IS NOT NULL AS has_col_acl
--     FROM pg_attribute
--    WHERE attrelid='public.businesses'::regclass AND attnum>0
--      AND NOT attisdropped
--      AND attname IN ('metered_usage_enabled','monthly_spend_cap_gbp',
--                      'name','plan_tier')
--    ORDER BY attname;
--   -- expect: metered_usage_enabled false | monthly_spend_cap_gbp false
--   --         name true | plan_tier true
--
-- VERIFY 5d — SELECT and INSERT are UNCHANGED and still TABLE-LEVEL.
-- Expect INSERT 28 and SELECT 28, with NO DELETE row at all:
--   SELECT privilege_type, count(*)
--     FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='businesses'
--      AND grantee='authenticated'
--      AND privilege_type IN ('SELECT','INSERT','DELETE')
--    GROUP BY privilege_type ORDER BY privilege_type;
--
-- 28, NOT 26, AND THAT IS CORRECT — READ THIS.
-- SELECT and INSERT remain table-level grants (relacl `a` and `r`), and a
-- table-level grant covers every column including the two added in
-- SECTION 4. Only UPDATE was converted to a column list. So:
--   * authenticated CAN still SELECT metered_usage_enabled and
--     monthly_spend_cap_gbp. That is wanted — PART E requires usage and
--     remaining allowance be visible to the customer before the limit.
--   * authenticated CAN still name both columns in an INSERT of a NEW
--     business row. businesses_spend_cap_chk still applies, so the row
--     cannot be metered without a positive cap — but the cap on a
--     self-created row could be set to anything. That is the SAME
--     business-creation hole 030b addresses at AdminDashboard.tsx:380,
--     it is not made worse here, and it is not fixed here either.
-- Compare against audits/033-staging-before.txt: SELECT and INSERT were
-- 26 before only because there were 26 columns.
--
-- VERIFY 5e — an owner genuinely cannot write the cap. Run AS the
-- authenticated role. This must FAIL with "permission denied for table
-- businesses". Wrapped so it can never commit:
--   BEGIN;
--     SET LOCAL ROLE authenticated;
--     UPDATE public.businesses SET monthly_spend_cap_gbp = 999999;
--   ROLLBACK;
--
-- VERIFY 5e2 — and cannot flip the metering switch either. Must FAIL
-- with "permission denied for table businesses". Wrapped:
--   BEGIN;
--     SET LOCAL ROLE authenticated;
--     UPDATE public.businesses SET metered_usage_enabled = true;
--   ROLLBACK;
--
-- VERIFY 5f — and can still write a column they could write before.
-- Under RLS this returns 0 rows updated rather than a permission error,
-- because biz_update_if_owner filters on auth.uid() which is NULL here.
-- 0 rows is a PASS; "permission denied" is a FAIL. Wrapped:
--   BEGIN;
--     SET LOCAL ROLE authenticated;
--     UPDATE public.businesses SET owner_whatsapp = owner_whatsapp;
--   ROLLBACK;
--
-- VERIFY 5g — and can still READ the new columns, which PART E needs.
-- Must NOT raise "permission denied". 0 rows is a pass here too — RLS
-- filters on auth.uid(), which is NULL outside a request. Wrapped:
--   BEGIN;
--     SET LOCAL ROLE authenticated;
--     SELECT count(*) FROM public.businesses
--      WHERE monthly_spend_cap_gbp IS NULL;
--   ROLLBACK;

-- ROLLBACK 5 — restores the table-level grant exactly as it was.
-- REVOKE UPDATE without a column list removes BOTH the table-level grant
-- and every column-level one, so this returns relacl to authenticated=
-- arwdDxtm and pg_attribute.attacl to NULL on all columns — byte
-- identical to audits/033-staging-before.txt.
--   REVOKE UPDATE ON public.businesses FROM authenticated;
--   GRANT UPDATE ON public.businesses TO authenticated;
--
-- VERIFY ROLLBACK 5 — expect authenticated=arwdDxtm/postgres and 0
-- column-level ACLs:
--   SELECT unnest(relacl)::text FROM pg_class
--    WHERE oid='public.businesses'::regclass;
--   SELECT count(*) FROM pg_attribute
--    WHERE attrelid='public.businesses'::regclass AND attnum>0
--      AND NOT attisdropped AND attacl IS NOT NULL;
--   -- expect 0




-- =====================================================================
-- SECTION 6 — PART B (SAFE HALF): brand_color + the six renames
-- =====================================================================
-- SECTION 6 IS SAFE TO SHIP ON ITS OWN. SECTION 7 IS NOT. They were one
-- section until the rehearsal showed why they must not be — see the
-- deploy-ordering warning below.
--
-- Section 6 renames keys and moves brand_color. Both are lossless: the
-- rename merges by OR so a true can never become a false, and
-- brand_color lands in a column before the key is dropped. Nobody's
-- resolved access changes, under EITHER set of plan defaults.
--
-- SECTION 7 is the destructive one. It edits the dict that is
-- currently the sole thing granting MSC and New Body their paid
-- features: both are on `pro`, whose DEPLOYED default is {"email": true},
-- and everything else they can do today comes from feature_flags.
--
-- Rules, as ruled:
--   R1  Five renames:
--         accounting_enabled       -> accounting
--         calendar_booking_enabled -> calendar_booking
--         calendar                 -> calendar_booking
--         quoting_enabled          -> quoting
--         whatsapp_enabled         -> whatsapp
--         voice                    -> aria_voice
--       Where source and target both exist, MERGE. The merge is a
--       boolean OR, so true wins — a rename must never be able to take
--       access away, and OR is the only merge that guarantees it.
--       Note calendar_booking has TWO sources; OR is associative, so
--       the order they are applied in cannot change the result.
--   R2  brand_color moves to businesses.brand_color. The FLAG WINS
--       unconditionally — it is what the UI reads, so it is the true
--       value. New Body's #475569 overwrites the column's #3B82F6.
--   R3  NEVER delete an unknown key. Only the five sources above are
--       renamed and only brand_color is removed. Everything else stays
--       and is reported by VERIFY 6f.
--   R4  After the renames, remove any flag whose value EQUALS its plan
--       default, so feature_flags holds only deliberate exceptions.
--       *** R4 IS SECTION 7, NOT THIS SECTION. ***
--   R5  VERIFY must prove, per business, that the resolved feature set
--       after is a SUPERSET of the resolved set before. Nobody loses
--       access. This is VERIFY 7b, in SECTION 7.
--
-- ---------------------------------------------------------------------
-- *** STOP. R4 (SECTION 7) IS A DEPLOY-ORDERING TRAP. READ THIS. ***
-- ---------------------------------------------------------------------
-- R4 removes a flag when it "equals its plan default". That phrase has
-- TWO possible answers today, and they disagree completely:
--
--   (a) THE DEFAULTS THE RUNNING CODE USES. `_plan_feature_defaults`
--       (backend/auth.py:249, duplicated at backend/main.py:2346) says
--         pro = {"email": True}
--       and nothing else. Under (a), a flag `receptionist: true` does
--       NOT equal its default (which is absent, so False) and is KEPT.
--       MSC would keep almost every flag it has. MSC does not end at {}.
--
--   (b) THE CANONICAL PART B TABLE, defined in the plan_defaults CTE
--       below. Under (b), pro grants ten features, so accounting,
--       quoting, whatsapp, calendar_booking, receptionist and email all
--       equal their default and are all REMOVED.
--
-- "MSC on pro should end up {}" is only reachable under (b). This
-- section therefore implements (b).
--
-- AND THAT IS SAFE ONLY IF THE CODE SHIPS THE SAME DEFAULTS IN THE SAME
-- DEPLOY. If this migration runs against the CURRENTLY DEPLOYED backend,
-- MSC resolves, the instant it commits:
--
--     accounting        flags: gone    pro default (a): absent -> FALSE
--     receptionist      flags: gone    pro default (a): absent -> FALSE
--     quoting           flags: gone    pro default (a): absent -> FALSE
--     whatsapp          flags: gone    pro default (a): absent -> FALSE
--     calendar_booking  flags: gone    pro default (a): absent -> FALSE
--     email             flags: gone    pro default (a): TRUE   -> ok
--
-- That is both live businesses losing five paid features at once, with
-- no error raised anywhere.
--
-- THIS IS NOT HYPOTHETICAL. It was measured on staging, 25 Aug 2026,
-- against fixtures carrying the eleven prod keys: resolving the
-- post-SECTION-7 state through the DEPLOYED defaults produced EIGHT
-- feature losses across the two businesses —
--   MSC:      accounting, calendar_booking, quoting, receptionist, whatsapp
--   New Body: accounting, calendar_booking, quoting
-- Resolving the same state through the CANONICAL defaults produced zero.
-- The difference is entirely which Python dict is deployed.
--
-- VERIFY 7b exists to catch exactly this and MUST be run before you
-- walk away. Run it in BOTH forms — the file gives both.
--
-- The spec's own "Order of work" puts migration 033 at step 3 and the
-- implementation at step 5. FOLLOWING THAT ORDER CAUSES THIS OUTAGE.
-- Sections 1-6 are safe in that order; SECTION 7 is not. Section 7 must
-- be applied in the SAME deploy that replaces `_plan_feature_defaults`
-- (backend/auth.py:249 AND backend/main.py:2346, both copies) with the
-- canonical table below, or after it. Never before.
-- ---------------------------------------------------------------------
--
-- THE CANONICAL DEFAULTS BELOW MUST MATCH THE PYTHON CONSTANT EXACTLY.
-- They are transcribed from ENTITLEMENT-SPEC PART B's table. `beta` is
-- given `business`'s row, matching both existing copies of
-- `_plan_feature_defaults`, which treat beta as top-tier for testing
-- parity. PART A keeps beta as an operational state, not a sold plan.
--
--     feature            starter  pro  business  beta
--     quoting               T      T      T       T
--     invoicing             T      T      T       T
--     accounting            T      T      T       T
--     email                 T      T      T       T
--     aria_chat             T      T      T       T
--     aria_voice            F      T      T       T
--     whatsapp              F      T      T       T
--     board_meetings        F      T      T       T
--     calendar_booking      F      T      T       T
--     receptionist          F      T      T       T
--     outreach              F      F      T       T


-- PRE-FLIGHT 6a — MANDATORY. Every key involved in a rename must hold a
-- BOOLEAN, or the merge cast fails mid-statement. Expect 0 rows. Any row
-- returned names a business and a key that must be resolved by hand:
--   SELECT b.name, k.key, jsonb_typeof(b.feature_flags -> k.key) AS typ
--     FROM public.businesses b,
--          LATERAL jsonb_object_keys(b.feature_flags) AS k(key)
--    WHERE k.key IN ('accounting_enabled','accounting',
--                    'calendar_booking_enabled','calendar','calendar_booking',
--                    'quoting_enabled','quoting',
--                    'whatsapp_enabled','whatsapp',
--                    'voice','aria_voice')
--      AND jsonb_typeof(b.feature_flags -> k.key) <> 'boolean';
--
-- PRE-FLIGHT 6b — MANDATORY. Every brand_color value must be a string
-- and a valid 6-digit hex, because the key is DELETED after the copy.
-- A value that fails this is destroyed rather than moved. Expect 0 rows:
--   SELECT b.name, b.feature_flags -> 'brand_color' AS flag_value
--     FROM public.businesses b
--    WHERE b.feature_flags ? 'brand_color'
--      AND (jsonb_typeof(b.feature_flags -> 'brand_color') <> 'string'
--           OR b.feature_flags ->> 'brand_color' !~ '^#[0-9A-Fa-f]{6}$');
--
-- PRE-FLIGHT 6c — what the flag/column disagreement actually is. This is
-- the R2 decision made visible. EXPECT: New Body flag #475569 vs column
-- #3B82F6 (flag wins, column is overwritten); MSC agreeing already:
--   SELECT name, brand_color AS column_now,
--          feature_flags ->> 'brand_color' AS flag_now,
--          (brand_color IS DISTINCT FROM feature_flags ->> 'brand_color')
--            AS will_change
--     FROM public.businesses
--    WHERE feature_flags ? 'brand_color'
--    ORDER BY name;
--
-- PRE-FLIGHT 6d — the full before picture. SAVE THIS OUTPUT. It is what
-- VERIFY 7b and ROLLBACK 6/7 are judged against:
--   SELECT name, plan_tier, brand_color, jsonb_pretty(feature_flags)
--     FROM public.businesses ORDER BY name;


-- ---------------------------------------------------------------------
-- 6.0 — Backup table. ROLLBACK 6 restores from this, byte for byte.
-- ---------------------------------------------------------------------
-- The transforms are not individually reversible: R1's OR-merge loses
-- which source a true came from, and R4's removal loses which flags were
-- explicit. Reversing them by inference would be guesswork. A copy of
-- the two columns is exact, costs 6 rows, and is the only honest
-- rollback available.
--
-- CREATE TABLE AS inherits pg_default_acl, so this table would be
-- readable by the public anon key the instant it exists — and it holds
-- every business's entitlement state. The REVOKEs are not optional.

-- CREATE TABLE IF NOT EXISTS, and NO unconditional DROP.
--
-- THIS IS NOT A STYLE CHOICE. The first draft opened with
-- `DROP TABLE IF EXISTS` followed by a plain `CREATE TABLE AS`. The
-- staging rehearsal caught what that does: re-pasting SECTION 6 after it
-- has already run RE-SNAPSHOTS THE BACKUP FROM THE ALREADY-MIGRATED
-- STATE. The transforms correctly report `UPDATE 0` — they are
-- idempotent — so nothing looks wrong, while the only route back to the
-- original feature_flags is silently destroyed. Verified on staging
-- 25 Aug 2026: after two re-runs the backup held the post-migration
-- values and ROLLBACK 6/7 would have "restored" the migration.
--
-- IF NOT EXISTS means a re-paste leaves the original capture intact.
-- To deliberately re-baseline, drop the table by hand first — which is
-- the point: it should take a deliberate act, not a stray paste.

CREATE TABLE IF NOT EXISTS public.zz_033_flags_backup AS
  SELECT id, name, plan_tier, brand_color, feature_flags, now() AS captured_at
    FROM public.businesses;

REVOKE ALL ON public.zz_033_flags_backup FROM anon;
REVOKE ALL ON public.zz_033_flags_backup FROM authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.zz_033_flags_backup TO service_role;

-- VERIFY 6.0 — expect the same row count as businesses, and anon/
-- authenticated absent entirely:
--   SELECT (SELECT count(*) FROM public.zz_033_flags_backup) AS backed_up,
--          (SELECT count(*) FROM public.businesses)          AS businesses;
--   SELECT grantee, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='zz_033_flags_backup'
--      AND grantee IN ('anon','authenticated','service_role')
--    ORDER BY grantee, privilege_type;
--   -- expect service_role only. anon and authenticated MUST NOT APPEAR.
--
-- VERIFY 6.0b — THE BACKUP MUST PREDATE THE TRANSFORMS. It has to still
-- hold the OLD key names, or it is not a rollback. Expect a non-zero
-- count — the source keys SECTION 6 is about to rename away:
--   SELECT count(*) AS old_keys_in_backup
--     FROM public.zz_033_flags_backup z,
--          LATERAL jsonb_object_keys(z.feature_flags) AS k(key)
--    WHERE k.key IN ('accounting_enabled','calendar_booking_enabled',
--                    'calendar','quoting_enabled','whatsapp_enabled','voice',
--                    'brand_color');
--
-- If this returns 0 on a first run, the backup captured nothing useful —
-- STOP. If it returns 0 on a RE-run, the backup was clobbered by an
-- older copy of this file: STOP, and do not run ROLLBACK 6 or 7, because
-- they would write the migrated state back over itself.


-- ---------------------------------------------------------------------
-- 6.1 — R2: brand_color to its column, flag wins
-- ---------------------------------------------------------------------
-- Guarded by the same hex predicate as PRE-FLIGHT 6b, so a malformed
-- value is left in feature_flags rather than silently written to the
-- column. 6.2 then leaves it there too, and VERIFY 6b reports it.

UPDATE public.businesses
   SET brand_color = feature_flags ->> 'brand_color'
 WHERE feature_flags ? 'brand_color'
   AND jsonb_typeof(feature_flags -> 'brand_color') = 'string'
   AND feature_flags ->> 'brand_color' ~ '^#[0-9A-Fa-f]{6}$'
   AND brand_color IS DISTINCT FROM feature_flags ->> 'brand_color';

UPDATE public.businesses
   SET feature_flags = feature_flags - 'brand_color'
 WHERE feature_flags ? 'brand_color'
   AND jsonb_typeof(feature_flags -> 'brand_color') = 'string'
   AND feature_flags ->> 'brand_color' ~ '^#[0-9A-Fa-f]{6}$'
   AND brand_color = feature_flags ->> 'brand_color';

-- VERIFY 6a — the column now holds what the flag held, and the flag is
-- gone. Expect 0 rows still carrying the key:
--   SELECT count(*) AS still_have_flag FROM public.businesses
--    WHERE feature_flags ? 'brand_color';
--
-- VERIFY 6b — expect New Body #475569 and MSC unchanged. Compare against
-- PRE-FLIGHT 6c:
--   SELECT name, brand_color FROM public.businesses ORDER BY name;


-- ---------------------------------------------------------------------
-- 6.2 — R1: the six renames, merging by OR
-- ---------------------------------------------------------------------
-- One statement driven by an explicit pair list rather than six
-- near-identical UPDATEs, so the pair list is the thing under review and
-- there is no sixth statement to get subtly wrong.
--
-- bool_or over the sources, OR'd with the target's own existing value,
-- so a target that is already true can never be turned false and a
-- source that is true always survives. Sources are then removed.

WITH pairs(src, dst) AS (
  VALUES ('accounting_enabled',       'accounting'),
         ('calendar_booking_enabled', 'calendar_booking'),
         ('calendar',                 'calendar_booking'),
         ('quoting_enabled',          'quoting'),
         ('whatsapp_enabled',         'whatsapp'),
         ('voice',                    'aria_voice')
),
merged AS (
  SELECT b.id,
         jsonb_object_agg(p.dst, t.val) AS newkeys
    FROM public.businesses b
    JOIN LATERAL (
      SELECT p2.dst,
             bool_or(coalesce((b.feature_flags ->> p2.src)::boolean, false))
               OR coalesce((b.feature_flags ->> p2.dst)::boolean, false) AS val
        FROM pairs p2
       WHERE b.feature_flags ? p2.src
       GROUP BY p2.dst
    ) t ON true
    JOIN pairs p ON p.dst = t.dst
   GROUP BY b.id
)
UPDATE public.businesses b
   SET feature_flags =
         (b.feature_flags - ARRAY['accounting_enabled',
                                  'calendar_booking_enabled',
                                  'calendar',
                                  'quoting_enabled',
                                  'whatsapp_enabled',
                                  'voice'])
         || m.newkeys
  FROM merged m
 WHERE m.id = b.id;

-- VERIFY 6c — no source key survives anywhere. Expect 0:
--   SELECT count(*) FROM public.businesses b,
--          LATERAL jsonb_object_keys(b.feature_flags) AS k(key)
--    WHERE k.key IN ('accounting_enabled','calendar_booking_enabled',
--                    'calendar','quoting_enabled','whatsapp_enabled','voice');
--
-- VERIFY 6d — the merge never turned a true into a false. Compare the
-- backup against the result, per business, per target key. Expect 0 rows:
--   SELECT b.name, x.dst
--     FROM public.businesses b
--     JOIN public.zz_033_flags_backup z ON z.id = b.id,
--          LATERAL (VALUES ('accounting_enabled','accounting'),
--                          ('calendar_booking_enabled','calendar_booking'),
--                          ('calendar','calendar_booking'),
--                          ('quoting_enabled','quoting'),
--                          ('whatsapp_enabled','whatsapp'),
--                          ('voice','aria_voice')) x(src,dst)
--    WHERE coalesce((z.feature_flags ->> x.src)::boolean, false)
--      AND NOT coalesce((b.feature_flags ->> x.dst)::boolean, false);


--
-- *** VERIFY 6d IS ONLY VALID BEFORE SECTION 7 RUNS. *** Section 7
-- deliberately removes the very keys 6d looks for, so running 6d after
-- section 7 returns a row per removed key — eight of them on the staging
-- rehearsal — every one a false alarm. Run 6d here, at this checkpoint,
-- and never after. A check that cries wolf is worse than no check,
-- especially sharing a file with VERIFY 7b.

-- ROLLBACK 6 — exact restore from the 6.0 backup. Not an inverse
-- transform; a copy-back. The OR-merge loses which source a true came
-- from, so no inverse exists. Safe to run repeatedly.
--   UPDATE public.businesses b
--      SET feature_flags = z.feature_flags,
--          brand_color   = z.brand_color
--     FROM public.zz_033_flags_backup z
--    WHERE z.id = b.id;
--
-- VERIFY ROLLBACK 6 — expect 0 rows differing:
--   SELECT b.name FROM public.businesses b
--     JOIN public.zz_033_flags_backup z ON z.id = b.id
--    WHERE b.feature_flags IS DISTINCT FROM z.feature_flags
--       OR b.brand_color   IS DISTINCT FROM z.brand_color;


-- =====================================================================
-- SECTION 7 — PART B (DESTRUCTIVE HALF): R4, drop flags that merely
--             restate the plan default
-- =====================================================================
-- *** DO NOT APPLY THIS SECTION AHEAD OF THE CODE CHANGE. ***
-- Re-read the deploy-ordering warning at the top of SECTION 6. Measured
-- on staging: applying this section against the currently deployed
-- `_plan_feature_defaults` costs MSC and New Body eight paid features
-- between them, silently.
--
-- The gate, in one line: SECTION 7 may be applied only once
-- `_plan_feature_defaults` in backend/auth.py AND backend/main.py both
-- return the canonical table below. VERIFY 7b run in its DEPLOYED form
-- must return 0 rows before you continue.
--
-- A key is removed ONLY when it is in the canonical vocabulary AND holds
-- a boolean AND that boolean equals the plan default for this business's
-- tier. Everything else stays, which is R3 falling out for free: an
-- unknown key never joins plan_defaults, so it can never be removed.
-- An explicit `false` against a default of `true` is a deliberate DENIAL
-- and is likewise never removed — it does not equal its default.

-- A key is removed ONLY when it is in the canonical vocabulary AND holds
-- a boolean AND that boolean equals the plan default for this business's
-- tier. Everything else stays, which is R3 falling out for free: an
-- unknown key never joins plan_defaults, so it can never be removed.
--
-- Read the deploy-ordering warning at the top of this section before
-- running this statement. It is the one that can take access away.

WITH plan_defaults(plan_tier, feature, enabled) AS (
  VALUES
    ('starter','quoting',true),  ('starter','invoicing',true),
    ('starter','accounting',true),('starter','email',true),
    ('starter','aria_chat',true), ('starter','aria_voice',false),
    ('starter','whatsapp',false), ('starter','board_meetings',false),
    ('starter','calendar_booking',false),('starter','receptionist',false),
    ('starter','outreach',false),

    ('pro','quoting',true),   ('pro','invoicing',true),
    ('pro','accounting',true),('pro','email',true),
    ('pro','aria_chat',true), ('pro','aria_voice',true),
    ('pro','whatsapp',true),  ('pro','board_meetings',true),
    ('pro','calendar_booking',true),('pro','receptionist',true),
    ('pro','outreach',false),

    ('business','quoting',true),   ('business','invoicing',true),
    ('business','accounting',true),('business','email',true),
    ('business','aria_chat',true), ('business','aria_voice',true),
    ('business','whatsapp',true),  ('business','board_meetings',true),
    ('business','calendar_booking',true),('business','receptionist',true),
    ('business','outreach',true),

    ('beta','quoting',true),   ('beta','invoicing',true),
    ('beta','accounting',true),('beta','email',true),
    ('beta','aria_chat',true), ('beta','aria_voice',true),
    ('beta','whatsapp',true),  ('beta','board_meetings',true),
    ('beta','calendar_booking',true),('beta','receptionist',true),
    ('beta','outreach',true)
),
redundant AS (
  SELECT b.id,
         coalesce(array_agg(k.key), ARRAY[]::text[]) AS drop_keys
    FROM public.businesses b
    JOIN LATERAL jsonb_object_keys(b.feature_flags) AS k(key) ON true
    JOIN plan_defaults d
      ON d.plan_tier = b.plan_tier
     AND d.feature   = k.key
   WHERE jsonb_typeof(b.feature_flags -> k.key) = 'boolean'
     AND d.enabled = (b.feature_flags ->> k.key)::boolean
   GROUP BY b.id
)
UPDATE public.businesses b
   SET feature_flags = b.feature_flags - r.drop_keys
  FROM redundant r
 WHERE r.id = b.id
   AND array_length(r.drop_keys, 1) > 0;

-- VERIFY 7b — *** THE ONE THAT MATTERS. R5. ***
-- Per business, per canonical feature: what resolved to enabled BEFORE
-- (from the backup, using the DEPLOYED defaults) and what resolves to
-- enabled NOW (using the CANONICAL defaults). Any feature that was
-- enabled and is no longer enabled is a REGRESSION.
--
-- EXPECT 0 ROWS. If this returns anything, ROLL BACK — a customer has
-- lost access.
--
-- Note the two default tables are deliberately DIFFERENT: `before` uses
-- what the running code actually does today, not what we wish it did.
-- That is the only comparison that means anything.
--
--   WITH canonical(plan_tier, feature, enabled) AS (
--     VALUES ('pro','quoting',true),('pro','invoicing',true),
--            ('pro','accounting',true),('pro','email',true),
--            ('pro','aria_chat',true),('pro','aria_voice',true),
--            ('pro','whatsapp',true),('pro','board_meetings',true),
--            ('pro','calendar_booking',true),('pro','receptionist',true),
--            ('pro','outreach',false),
--            ('starter','quoting',true),('starter','invoicing',true),
--            ('starter','accounting',true),('starter','email',true),
--            ('starter','aria_chat',true),('starter','aria_voice',false),
--            ('starter','whatsapp',false),('starter','board_meetings',false),
--            ('starter','calendar_booking',false),('starter','receptionist',false),
--            ('starter','outreach',false)
--   ),
--   deployed(plan_tier, feature, enabled) AS (
--     -- backend/auth.py:249 verbatim. starter is {}, so it has no rows.
--     VALUES ('pro','email',true)
--   ),
--   renames(src, dst) AS (
--     VALUES ('accounting_enabled','accounting'),
--            ('calendar_booking_enabled','calendar_booking'),
--            ('calendar','calendar_booking'),
--            ('quoting_enabled','quoting'),
--            ('whatsapp_enabled','whatsapp'),
--            ('voice','aria_voice')
--   ),
--   features AS (SELECT DISTINCT feature FROM canonical),
--   before AS (
--     SELECT z.id, z.name, f.feature,
--            coalesce(
--              (SELECT bool_or(coalesce((z.feature_flags ->> x.k)::boolean,false))
--                 FROM (SELECT f.feature AS k
--                       UNION SELECT r.src FROM renames r WHERE r.dst = f.feature) x
--                WHERE z.feature_flags ? x.k),
--              (SELECT d.enabled FROM deployed d
--                WHERE d.plan_tier = z.plan_tier AND d.feature = f.feature),
--              false) AS was_enabled
--       FROM public.zz_033_flags_backup z CROSS JOIN features f
--   ),
--   after AS (
--     SELECT b.id, f.feature,
--            coalesce(
--              CASE WHEN b.feature_flags ? f.feature
--                   THEN (b.feature_flags ->> f.feature)::boolean END,
--              (SELECT c.enabled FROM canonical c
--                WHERE c.plan_tier = b.plan_tier AND c.feature = f.feature),
--              false) AS is_enabled
--       FROM public.businesses b CROSS JOIN features f
--   )
--   SELECT before.name, before.feature, before.was_enabled, after.is_enabled
--     FROM before JOIN after
--       ON after.id = before.id AND after.feature = before.feature
--    WHERE before.was_enabled AND NOT after.is_enabled
--    ORDER BY before.name, before.feature;
--
-- VERIFY 7c — R3. Every key that SURVIVED and is NOT in the canonical
-- vocabulary. These are the deliberate exceptions and the unknowns. This
-- query is not a pass/fail — it is the list you must read and confirm:
--   SELECT b.name, k.key, b.feature_flags -> k.key AS value
--     FROM public.businesses b,
--          LATERAL jsonb_object_keys(b.feature_flags) AS k(key)
--    WHERE k.key NOT IN ('quoting','invoicing','accounting','email',
--                        'aria_chat','aria_voice','whatsapp',
--                        'board_meetings','calendar_booking',
--                        'receptionist','outreach')
--    ORDER BY b.name, k.key;
--
-- VERIFY 7d — the end state, business by business. Compare against
-- PRE-FLIGHT 6d:
--   SELECT name, plan_tier, brand_color, jsonb_pretty(feature_flags)
--     FROM public.businesses ORDER BY name;

-- ROLLBACK 7 — exact restore from the 6.0 backup. Not an inverse
-- transform; a copy-back. Safe to run repeatedly.
--   UPDATE public.businesses b
--      SET feature_flags = z.feature_flags,
--          brand_color   = z.brand_color
--     FROM public.zz_033_flags_backup z
--    WHERE z.id = b.id;
--
-- VERIFY ROLLBACK 7 — expect 0 rows differing:
--   SELECT b.name FROM public.businesses b
--     JOIN public.zz_033_flags_backup z ON z.id = b.id
--    WHERE b.feature_flags IS DISTINCT FROM z.feature_flags
--       OR b.brand_color   IS DISTINCT FROM z.brand_color;
--
-- The backup table is DELIBERATELY LEFT IN PLACE after a successful
-- apply. Drop it only once the change has been confirmed live, and note
-- that dropping it removes the only route back:
--   DROP TABLE IF EXISTS public.zz_033_flags_backup;
