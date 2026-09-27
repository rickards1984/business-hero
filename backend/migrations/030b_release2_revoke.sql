-- =====================================================================
-- 030b RELEASE 2 — THE REVOKE
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
-- Spec: audits/030B-SPEC.md PART E. Runbook: audits/030b-PROD-RUNBOOK.md.
--
-- Apply ONE SECTION AT A TIME. Run the VERIFY after each section before
-- moving on. Every section has a ROLLBACK block, and every ROLLBACK has
-- been executed on staging, not merely written.
--
-- WHAT THIS CLOSES
--   RC1 P0-3, the paywall hole. `authenticated` holds UPDATE on
--   `businesses` — since 033 as a COLUMN LIST of 26 columns rather than
--   table-level, and that list still contains plan_tier, is_active,
--   feature_flags, limits and subscription_status. `biz_update_if_owner`
--   authorises the ROW for an owner. Grants are evaluated before RLS. So
--   an owner can, today, from the browser with the anon key:
--
--     await supabase.from('businesses')
--       .update({ plan_tier: 'business', feature_flags: {...} })
--       .eq('id', myBusinessId)
--
--   backend/tests/test_tenant_isolation_rls_path.py (PR #9, branch
--   ticket/BH-003-tenant-isolation-harness — not on main at the time of
--   writing) encodes exactly that as four xfail(strict) tests; this
--   migration is what makes them pass.
--
-- EVIDENCE THIS IS BUILT ON (gathered 18 Sep 2026)
--   * Frontend supabase-js writes: business_members (3 sites),
--     support_tickets (2), tasks (4). ZERO to businesses. All four
--     `from('businesses')` calls are `.select()`. (grep, frontend/client/src)
--   * Every customer-side business save (logo, brand colour, billing)
--     goes through apiRequest to the backend.
--   * onboarding_api.py writes businesses by raw SQL through the backend's
--     SQLAlchemy session — the elevated postgres connection, the table
--     OWNER. Owner privilege is not a grant and cannot be revoked here.
--   * admin_business_api.py (030b Release 1) owns admin writes and
--     creation. Release 1 is live: docs/CURRENT_STATE.md §8.
--   * Staging, read-only, 18 Sep: authenticated holds
--     DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE at table
--     level and UPDATE on 26 columns; anon holds SELECT, TRIGGER;
--     three policies on businesses. Matches the migration-defined state.
--
-- WHY THE POLICY IS DROPPED IN THE SAME SECTION (spec PART E, RULED)
--   With the grant gone the policy is unreachable. Left in place it reads
--   as protection and enforces nothing; the next person to restore an
--   UPDATE grant would find an owner-scoped policy and reasonably
--   conclude the table was still protected. After this, the protection
--   lives in exactly one place: the absence of the grant.
--
-- POSTGRES BEHAVIOUR THIS RELIES ON
--   `REVOKE UPDATE ON table FROM role` also revokes every column-level
--   UPDATE that role holds on the table (REVOKE docs: "when revoking
--   privileges on a table, the corresponding column privileges (if any)
--   are automatically revoked on each column of the table, as well").
--   VERIFY 1b checks column_privileges directly rather than trusting it.
--
-- SECTION 2 IS SEPARATE, OPTIONAL, AND NOT TO BE APPLIED WITHOUT MIKE'S
--   EXPLICIT APPROVAL OF THAT STEP. Mike's instruction named INSERT
--   and UPDATE. The spec's own VERIFY expects authenticated to hold
--   SELECT and TRIGGER ONLY, which also means DELETE, TRUNCATE and
--   REFERENCES go. No client path uses any of them (no DELETE policy
--   exists for members; TRUNCATE is not subject to RLS and not exposed
--   by PostgREST; REFERENCES is DDL). Section 2 is the difference between
--   the instruction and the spec, kept apart so it can be skipped.
-- =====================================================================


-- =====================================================================
-- SECTION 1 — Revoke INSERT and UPDATE from authenticated; drop the policy
-- =====================================================================

REVOKE INSERT, UPDATE ON public.businesses FROM authenticated;

DROP POLICY IF EXISTS biz_update_if_owner ON public.businesses;

-- VERIFY 1a — table-level grants. Expect for authenticated:
--   DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE   (no INSERT, no UPDATE)
--   and for anon: SELECT, TRIGGER (unchanged from 030a)
--   SELECT grantee, string_agg(privilege_type, ', ' ORDER BY privilege_type)
--     FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='businesses'
--      AND grantee IN ('anon','authenticated')
--    GROUP BY grantee ORDER BY grantee;

-- VERIFY 1b — COLUMN-level UPDATE and INSERT. Expect 0 and 0. This is the
-- one that matters: Q6-style table-grant views cannot see column grants.
--   SELECT privilege_type, count(*)
--     FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='businesses'
--      AND grantee='authenticated' AND privilege_type IN ('UPDATE','INSERT')
--    GROUP BY 1;

-- VERIFY 1c — the policy is gone; the other two remain. Expect exactly:
--   Platform admins can manage all businesses | *
--   biz_select_if_member                      | r
--   SELECT polname, polcmd FROM pg_policy
--    WHERE polrelid='public.businesses'::regclass ORDER BY 1;

-- VERIFY 1d — as the role itself. Each block ALONE. The errors are the pass.
--   BEGIN; SET LOCAL ROLE authenticated;
--     UPDATE public.businesses SET plan_tier = 'business';
--   ROLLBACK;
--     -> ERROR: permission denied for table businesses
--   BEGIN; SET LOCAL ROLE authenticated;
--     INSERT INTO public.businesses (name, api_key) VALUES ('x','x');
--   ROLLBACK;
--     -> ERROR: permission denied for table businesses
--   BEGIN; SET LOCAL ROLE authenticated;
--     SELECT count(*) FROM public.businesses;
--   ROLLBACK;
--     -> 0 (no error: SELECT is retained; 0 because auth.uid() is NULL)

-- ROLLBACK 1 — restores the exact pre-state: the 26-column UPDATE list
-- from 033 SECTION 5, table-level INSERT, and the policy verbatim from
-- 028 line 597. Run as ONE paste.
--   GRANT INSERT ON public.businesses TO authenticated;
--   GRANT UPDATE (
--     id, name, timezone, api_key, created_at, logo_url, plan_tier, is_active,
--     trial_ends_at, feature_flags, limits, stripe_customer_id,
--     stripe_subscription_id, subscription_status, current_period_end,
--     cancel_at_period_end, last_stripe_event_at, onboarding_completed,
--     onboarding_completed_at, onboarded_by, brand_color, owner_whatsapp,
--     ceo_briefing_enabled, region, tax_registered, tax_number
--   ) ON public.businesses TO authenticated;
--   CREATE POLICY biz_update_if_owner ON public.businesses FOR UPDATE
--     TO authenticated
--     USING ((EXISTS ( SELECT 1 FROM public.business_members bm
--              WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid())
--                AND (bm.role = 'owner'::text) AND (bm.is_active = true)))))
--     WITH CHECK ((EXISTS ( SELECT 1 FROM public.business_members bm
--              WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid())
--                AND (bm.role = 'owner'::text) AND (bm.is_active = true)))));
-- VERIFY ROLLBACK 1: VERIFY 1b returns UPDATE 26, INSERT 28 (28 = every
-- column, because table-level INSERT is reported per column); VERIFY 1c
-- lists three policies.


-- =====================================================================
-- SECTION 2 — OPTIONAL: DELETE, TRUNCATE, REFERENCES (spec's "SELECT and
--             TRIGGER only"). Skip if Mike rules INSERT+UPDATE is the scope.
-- =====================================================================

REVOKE DELETE, TRUNCATE, REFERENCES ON public.businesses FROM authenticated;

-- VERIFY 2 — expect authenticated: SELECT, TRIGGER. anon: SELECT, TRIGGER.
--   (same query as VERIFY 1a)

-- ROLLBACK 2:
--   GRANT DELETE, TRUNCATE, REFERENCES ON public.businesses TO authenticated;
