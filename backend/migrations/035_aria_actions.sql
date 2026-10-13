-- =====================================================================
-- 035 — ARIA ACTIONS (proposals the owner approves with a tap)
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
-- Ticket: NS-B10. Decision 1 of Mike's NS-B10 decisions (13 Oct 2026):
-- a new table, migration 035, runbook as for 034.
--
-- STATUS: DRAFT — NOT REHEARSED, NOT APPLIED. RED: Mike runs it from
-- audits/035-PROD-RUNBOOK.md after the staging rehearsal proves the
-- rollback.
--
-- WHY THIS EXISTS
-- Aria drafts an email, an invoice chase, a calendar booking or a task;
-- the owner approves it with one tap; the server then does EXACTLY what
-- was stored, once (ADR 0001 D9, D11, D15; North Star P4). The stored row
-- is the approval boundary: what was shown is what is sent.
-- email_drafts cannot hold it (it requires an inbound email_message_id
-- and holds email only); whatsapp_pending_actions executes before marking
-- itself executed and never checks expiry (gap analysis §B6).
--
-- DESIGN NOTES
-- * status is the once-only guarantee. Approval is a single
--     UPDATE ... SET status='executing' WHERE status='proposed'
--       AND expires_at > now() RETURNING payload
--   committed BEFORE anything is sent. Two taps: one row comes back.
--   An action interrupted mid-send stays 'executing' and is never
--   retried (Mike's decision 4, at most once).
-- * payload is jsonb: the exact recipient, subject, body, sign-off,
--   invoice id and chase stage, event time, or task — per action_type.
-- * action_type and status are CHECKed: unlike a meter name, adding an
--   action type is a deliberate product decision, and an unknown status
--   would silently fall out of every query that decides what may run.
-- * ON DELETE CASCADE on business_id, as usage_meters: an action is
--   meaningless without its business.
-- * proposed_by / approved_by are the auth user ids, not FKs to
--   auth.users: the audit trail must survive a user being removed.
--
-- RLS AND GRANTS (the 033 usage_meters pattern, AGENTS.md §3.3)
-- RLS on; one permissive SELECT policy for members and platform admins.
-- anon gets NOTHING, authenticated gets SELECT only — the default ACL
-- would otherwise make this table writable from any browser, which here
-- means anyone could mark their own proposal 'proposed' again. The
-- backend writes as its elevated role.
--
-- ORDERING
-- Apply BEFORE the NS-B10 code deploys; regenerate
-- audits/live-schema-public.txt afterwards (033 STEP 24b method) so
-- test_schema_conformance.py admits the code that writes these columns.
-- =====================================================================


-- ---------------------------------------------------------------------
-- SECTION 1 — the table, its indexes, RLS, policy and grants
-- ---------------------------------------------------------------------
BEGIN;

CREATE TABLE IF NOT EXISTS public.aria_actions (
  id           uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid         NOT NULL
                            REFERENCES public.businesses(id) ON DELETE CASCADE,
  proposed_by  uuid,
  action_type  text         NOT NULL,
  payload      jsonb        NOT NULL,
  status       text         NOT NULL DEFAULT 'proposed',
  approved_by  uuid,
  approved_at  timestamptz,
  executed_at  timestamptz,
  expires_at   timestamptz  NOT NULL,
  result       jsonb,
  error        text,
  created_at   timestamptz  NOT NULL DEFAULT now(),
  updated_at   timestamptz  NOT NULL DEFAULT now()
);

ALTER TABLE public.aria_actions
  DROP CONSTRAINT IF EXISTS aria_actions_type_chk;
ALTER TABLE public.aria_actions
  ADD CONSTRAINT aria_actions_type_chk
  CHECK (action_type IN ('send_email', 'send_invoice_chase',
                         'create_calendar_event', 'create_task'));

ALTER TABLE public.aria_actions
  DROP CONSTRAINT IF EXISTS aria_actions_status_chk;
ALTER TABLE public.aria_actions
  ADD CONSTRAINT aria_actions_status_chk
  CHECK (status IN ('proposed', 'executing', 'done', 'failed',
                    'dismissed', 'expired'));

-- "This business's open cards, newest first" and the approve claim.
CREATE INDEX IF NOT EXISTS idx_aria_actions_biz_status_created
  ON public.aria_actions USING btree (business_id, status, created_at DESC);

ALTER TABLE public.aria_actions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS aria_actions_member_read ON public.aria_actions;
CREATE POLICY aria_actions_member_read
  ON public.aria_actions
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), aria_actions.business_id)
         OR public.is_platform_admin(auth.uid()));

REVOKE ALL ON public.aria_actions FROM anon;
REVOKE ALL ON public.aria_actions FROM authenticated;
GRANT SELECT ON public.aria_actions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.aria_actions TO service_role;

COMMIT;


-- ---------------------------------------------------------------------
-- VERIFY 1a — expect 14 columns:
--   action_type text NO | approved_at timestamptz YES | approved_by uuid YES
--   | business_id uuid NO | created_at timestamptz NO | error text YES
--   | executed_at timestamptz YES | expires_at timestamptz NO | id uuid NO
--   | payload jsonb NO | proposed_by uuid YES | result jsonb YES
--   | status text NO | updated_at timestamptz NO
-- ---------------------------------------------------------------------
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'aria_actions'
 ORDER BY column_name;

-- VERIFY 1b — expect rls_enabled = true:
--   SELECT relrowsecurity AS rls_enabled FROM pg_class
--    WHERE oid = 'public.aria_actions'::regclass;
--
-- VERIFY 1c — expect exactly ONE row:
--   aria_actions_member_read | SELECT | PERMISSIVE | {authenticated}
--   | has_using=true | has_check=false
--   SELECT policyname, cmd, permissive, roles::text,
--          qual IS NOT NULL AS has_using, with_check IS NOT NULL AS has_check
--     FROM pg_policies
--    WHERE schemaname = 'public' AND tablename = 'aria_actions';
--
-- VERIFY 1d — THE ONE THAT MATTERS. Expect authenticated | SELECT, then
-- service_role's 7 privileges. anon MUST NOT APPEAR:
--   SELECT grantee, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE table_schema = 'public' AND table_name = 'aria_actions'
--      AND grantee IN ('anon', 'authenticated', 'service_role')
--    ORDER BY grantee, privilege_type;
--
-- VERIFY 1e — the CHECKs bite. Each INSERT must FAIL; wrapped, never commits:
--   BEGIN;
--     INSERT INTO public.aria_actions (business_id, action_type, payload, expires_at)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1), 'delete_task', '{}', now());
--   ROLLBACK;
--   BEGIN;
--     INSERT INTO public.aria_actions (business_id, action_type, payload, status, expires_at)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1), 'create_task', '{}', 'sent', now());
--   ROLLBACK;
--
-- VERIFY 1f — the claim returns ONE row, then none. Wrapped, never commits:
--   BEGIN;
--     INSERT INTO public.aria_actions (id, business_id, action_type, payload, expires_at)
--     VALUES ('00000000-0000-4000-8000-000000000035',
--             (SELECT id FROM public.businesses LIMIT 1), 'create_task',
--             '{"title":"rehearsal"}', now() + interval '1 hour');
--     UPDATE public.aria_actions SET status = 'executing'
--      WHERE id = '00000000-0000-4000-8000-000000000035'
--        AND status = 'proposed' AND expires_at > now() RETURNING id;   -- 1 row
--     UPDATE public.aria_actions SET status = 'executing'
--      WHERE id = '00000000-0000-4000-8000-000000000035'
--        AND status = 'proposed' AND expires_at > now() RETURNING id;   -- 0 rows
--   ROLLBACK;
--
-- VERIFY 1g — the table is empty. Expect 0:
--   SELECT count(*) FROM public.aria_actions;


-- ---------------------------------------------------------------------
-- ROLLBACK 1 — run ONLY to undo SECTION 1. Drops the table, its policy,
-- index and grants. After NS-B10 deploys, rows are the audit trail of
-- what Aria sent on approval: capture them first
-- (SELECT * FROM public.aria_actions ORDER BY created_at;).
-- ---------------------------------------------------------------------
-- BEGIN;
-- DROP TABLE IF EXISTS public.aria_actions;
-- COMMIT;
