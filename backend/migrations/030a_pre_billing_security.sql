-- =====================================================================
-- 030a — PRE-BILLING SECURITY BATCH
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
--
-- Apply ONE SECTION AT A TIME. Run the VERIFY query after each section
-- before moving on. Every section has a ROLLBACK block.
--
-- EVIDENCE THIS IS BUILT ON (gathered 17 Aug 2026, read-only):
--   * business_members: 5 rows, 0 with is_active=false, 2 pending invites
--   * frontend UPDATEs business_members in ONE place (AuthContext.tsx),
--     writing user_id + accepted_at only — never role or business_id
--   * backend NEVER writes business_members (no model, no raw SQL)
--   * business_members INSERT is admin-only (admins_full_access) — the
--     admin invite UI depends on it, so INSERT must NOT be revoked
--   * is_business_member() is referenced by 50 policies on 45 tables
--   * stripe_events is written ONLY by backend stripe_webhook(), which
--     uses a direct Postgres connection and bypasses RLS
--
-- DELIBERATELY NOT IN THIS MIGRATION (see 030b):
--   * REVOKE UPDATE ON businesses FROM authenticated
--       — 4 admin write sites must move to backend endpoints first
--   * businesses.api_key column restriction
--       — BusinessDashboard.tsx and BrandingSettings.tsx use select('*');
--         removing a column grant makes select('*') FAIL OUTRIGHT and
--         would take those pages down. Narrow the queries first.
-- =====================================================================


-- =====================================================================
-- SECTION 1 — Remove all write privilege from anon
-- =====================================================================
-- WHY: anon is the public key shipped in the frontend bundle. It holds
-- INSERT/UPDATE/DELETE/TRUNCATE on all three tables. RLS is currently
-- the only barrier. No policy grants anon anything (every policy is
-- {authenticated}), so anon writes are already blocked — this is
-- defence in depth and costs nothing.

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES
  ON public.businesses       FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES
  ON public.business_members FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES
  ON public.stripe_events    FROM anon;

-- VERIFY 1 — expect only SELECT (and possibly TRIGGER) for anon:
--   SELECT table_name, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND grantee='anon'
--      AND table_name IN ('businesses','business_members','stripe_events')
--    ORDER BY table_name, privilege_type;

-- ROLLBACK 1:
--   GRANT INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES
--     ON public.businesses, public.business_members, public.stripe_events
--     TO anon;


-- =====================================================================
-- SECTION 2 — Close the cross-tenant pivot on business_members
-- =====================================================================
-- THE HOLE: policy users_link_self allows UPDATE where
--   USING      ((invited_email = auth.email()) AND (user_id IS NULL))
--   WITH CHECK  (invited_email = auth.email())
-- WITH CHECK only re-tests the email, so a pending invite can be
-- rewritten to ANY business with role='owner':
--   UPDATE business_members
--      SET business_id='<victim>', role='owner', user_id='<me>'
--    WHERE invited_email='<my email>';
-- That makes the attacker an owner of another tenant.
--
-- WHY NOT FIX THE POLICY: Postgres RLS cannot compare new values to old
-- ones. USING sees the OLD row, WITH CHECK sees the NEW row; neither can
-- see both. "Keep business_id unchanged" is NOT expressible in a policy.
--
-- THE FIX: column-level UPDATE grants. Remove table-wide UPDATE and give
-- back only the two columns AuthContext.tsx actually writes. The pivot
-- becomes impossible at the privilege layer, before RLS is consulted.
-- Grants are checked BEFORE policies, so this holds even if a policy is
-- later loosened by mistake.

REVOKE UPDATE ON public.business_members FROM authenticated;
GRANT  UPDATE (user_id, accepted_at) ON public.business_members TO authenticated;

-- NOTE: this also prevents a PLATFORM ADMIN from changing a member's
-- role from the browser, because admin connects as `authenticated` too.
-- No such feature exists today (frontend has exactly one UPDATE site).
-- When you build "change member role", it belongs on the backend, which
-- bypasses RLS and column grants entirely.

-- VERIFY 2a — expect exactly two rows: user_id, accepted_at
--   SELECT column_name FROM information_schema.column_privileges
--    WHERE table_schema='public' AND table_name='business_members'
--      AND grantee='authenticated' AND privilege_type='UPDATE'
--    ORDER BY column_name;
--
-- VERIFY 2b — INSERT must SURVIVE (admin invite UI depends on it):
--   SELECT privilege_type FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='business_members'
--      AND grantee='authenticated' ORDER BY privilege_type;
--   -- expect INSERT present, UPDATE absent at table level

-- ROLLBACK 2:
--   REVOKE UPDATE (user_id, accepted_at) ON public.business_members FROM authenticated;
--   GRANT UPDATE ON public.business_members TO authenticated;


-- =====================================================================
-- SECTION 3 — Make is_active actually revoke access
-- =====================================================================
-- THE BUG: is_business_member() does not check is_active. It gates 50
-- policies across 45 tables, so deactivating a member revokes NOTHING —
-- they keep full read access to every business-scoped table.
--
-- SAFE TO APPLY: prod currently has 0 rows with is_active=false, so this
-- changes no one's access today. It makes deactivation work from now on.
--
-- Signature, language, volatility and security properties are preserved
-- exactly — only the WHERE clause changes.

CREATE OR REPLACE FUNCTION public.is_business_member(p_user_id uuid, p_business_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $function$
  select exists (
    select 1
    from public.business_members bm
    where bm.user_id = p_user_id
      and bm.business_id = p_business_id
      and bm.is_active = true
  );
$function$;

-- VERIFY 3a — confirm is_active is in the body:
--   SELECT pg_get_functiondef(p.oid) FROM pg_proc p
--     JOIN pg_namespace n ON n.oid=p.pronamespace
--    WHERE n.nspname='public' AND p.proname='is_business_member';
--
-- VERIFY 3b — confirm nobody was locked out (expect 0):
--   SELECT count(*) AS inactive_members
--     FROM public.business_members WHERE is_active = false;
--
-- VERIFY 3c — smoke test with a REAL member (expect true):
--   SELECT public.is_business_member(
--     (SELECT user_id FROM public.business_members
--       WHERE user_id IS NOT NULL AND is_active LIMIT 1),
--     (SELECT business_id FROM public.business_members
--       WHERE user_id IS NOT NULL AND is_active LIMIT 1));

-- ROLLBACK 3:
--   CREATE OR REPLACE FUNCTION public.is_business_member(p_user_id uuid, p_business_id uuid)
--   RETURNS boolean
--   LANGUAGE sql
--   STABLE
--   AS $function$
--     select exists (
--       select 1
--       from public.business_members bm
--       where bm.user_id = p_user_id
--         and bm.business_id = p_business_id
--     );
--   $function$;


-- =====================================================================
-- SECTION 4 — stripe_events becomes backend-only
-- =====================================================================
-- WHY: stripe_events is the webhook idempotency ledger. A member can
-- currently insert or delete rows in it. Deleting lets a processed
-- webhook be replayed; inserting a forged event_id makes a real Stripe
-- webhook look already-handled and be silently skipped — e.g. a
-- subscription cancellation that never takes effect.
--
-- SAFE: written only by backend stripe_webhook(), which uses a direct
-- Postgres connection (elevated role, bypasses RLS and these grants).
-- Frontend has zero references to this table.

DROP POLICY IF EXISTS stripe_events_member_access ON public.stripe_events;

REVOKE ALL ON public.stripe_events FROM anon;
REVOKE ALL ON public.stripe_events FROM authenticated;

-- VERIFY 4a — expect ZERO rows:
--   SELECT grantee, privilege_type FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='stripe_events'
--      AND grantee IN ('anon','authenticated');
--
-- VERIFY 4b — expect no member-access policy left:
--   SELECT policyname, cmd FROM pg_policies
--    WHERE schemaname='public' AND tablename='stripe_events';
--
-- VERIFY 4c — CRITICAL, backend must still write. After applying,
-- trigger a Stripe test webhook and confirm a new row appears:
--   SELECT count(*), max(created_at) FROM public.stripe_events;

-- ROLLBACK 4:
--   GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
--     ON public.stripe_events TO anon, authenticated;
--   CREATE POLICY stripe_events_member_access ON public.stripe_events
--     AS PERMISSIVE FOR ALL TO authenticated
--     USING (is_business_member(auth.uid(), business_id) OR is_platform_admin(auth.uid()))
--     WITH CHECK (is_business_member(auth.uid(), business_id) OR is_platform_admin(auth.uid()));


-- =====================================================================
-- SECTION 5 — Collapse policy sprawl on businesses
-- =====================================================================
-- WHY: businesses has 7 SELECT policies and 2 IDENTICAL admin ALL
-- policies. Permissive policies OR together, so more policies only ever
-- WIDEN access, and three of the seven ignore is_active — meaning the
-- is_active checks in the other two are currently pointless.
--
-- Keeping: biz_select_if_member (the strictest — checks is_active),
--          one admin ALL policy, biz_update_if_owner (untouched here).
-- SAFE: 0 inactive members, so no one loses access.
-- Sections 1–4 do not depend on this. Skip it if you want a smaller
-- blast radius today.

DROP POLICY IF EXISTS "Members can select their own businesses" ON public.businesses;
DROP POLICY IF EXISTS "Members can view their business"        ON public.businesses;
DROP POLICY IF EXISTS "Users can view their businesses"        ON public.businesses;
DROP POLICY IF EXISTS "members can read their businesses"      ON public.businesses;
DROP POLICY IF EXISTS "Platform admins can view all businesses" ON public.businesses;
DROP POLICY IF EXISTS "Platform admins full access to businesses" ON public.businesses;

-- VERIFY 5 — expect exactly 3: "Platform admins can manage all
-- businesses" (ALL), biz_select_if_member (SELECT), biz_update_if_owner (UPDATE)
--   SELECT policyname, cmd FROM pg_policies
--    WHERE schemaname='public' AND tablename='businesses'
--    ORDER BY cmd, policyname;

-- ROLLBACK 5: only the admin duplicate is worth restoring; the four
-- member SELECT policies were strictly weaker than biz_select_if_member.
-- NOTE: no WITH CHECK here — the original had none (ALL policies with
-- only USING implicitly reuse it for the write-check at runtime; adding
-- an explicit WITH CHECK is behaviourally identical but would not match
-- the original definition, which recorded with_check = null).
--   CREATE POLICY "Platform admins full access to businesses"
--     ON public.businesses AS PERMISSIVE FOR ALL TO authenticated
--     USING (EXISTS (SELECT 1 FROM platform_admins WHERE platform_admins.user_id = auth.uid()));


-- =====================================================================
-- POST-APPLY SMOKE TEST — do this in the browser, logged in as a
-- normal customer (NOT a platform admin):
--   1. Business dashboard loads                      (SELECT businesses)
--   2. Branding settings loads and saves             (backend write path)
--   3. Billing settings shows the right plan         (SELECT businesses)
--   4. Admin: invite a member to a business          (INSERT business_members)
--   5. Accept an invite on a fresh login             (UPDATE user_id/accepted_at)
--   6. Stripe test webhook lands a stripe_events row (backend write)
-- Items 4, 5 and 6 are the ones this migration could plausibly break.
-- =====================================================================
