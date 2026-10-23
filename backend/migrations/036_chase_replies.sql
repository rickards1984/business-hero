-- =====================================================================
-- 036 — CHASE REPLIES (replies to invoice chases, awaiting the owner)
-- =====================================================================
-- Project: business-hero (prod ref oxblcmwhuwtobdhsfgyi)
-- Rehearse on: business-hero-staging (gzcrsrqmygublveuzqyg) FIRST.
-- Ticket: AUTO-2 (docs/AUTO-2-TICKET.md). Mike, 19 Oct 2026: flag the
-- owner on any reply to a chase; when a customer says they've paid, show
-- it and close chasing.
--
-- STATUS: DRAFT — NOT REHEARSED, NOT APPLIED. RED: Mike runs it from
-- audits/036-PROD-RUNBOOK.md.
--
-- WHY THIS EXISTS
-- A reply from a chased customer pauses automatic chasing of that
-- customer until the owner decides: resume, or stop that invoice for good.
-- The row is that decision's durable state. It must outlive a restart,
-- and the autopilot reads it before every chase.
--
-- DESIGN NOTES
-- * One row per business per inbound message:
--   UNIQUE (business_id, email_message_id). A message scanned twice is
--   flagged once.
-- * email_message_id is a plain uuid, NOT a foreign key. The rehearsal
--   found that staging's email_messages has no primary key or unique index
--   (19 Oct 2026), and production's constraints were never captured, so a
--   foreign key here could fail on production. It is also not needed: the
--   backend reads messages and replies scoped by business_id, and a deleted
--   email must not take its reply (and the pause) with it — the reply
--   simply stays.
-- * invoice_ids is jsonb (a list of invoice ids). It is not a foreign key,
--   because a reply can be about several invoices. The backend resolves
--   the ids in this business only.
-- * status and category are CHECKed. An unknown status would fall out of
--   the query that decides who may be chased.
-- * resolved_by is the auth user id, not an FK, as in 035: the audit
--   trail survives a user's removal.
-- * ON DELETE CASCADE on business_id, as for aria_actions.
--
-- RLS AND GRANTS (the 035 pattern, AGENTS.md §3.3)
-- RLS is on, with one permissive SELECT policy for members and platform
-- admins. anon gets NOTHING; authenticated gets SELECT only. Otherwise a
-- browser could reopen or close its own pause. The backend writes as its
-- elevated role.
--
-- ORDERING
-- Apply BEFORE the AUTO-2 code deploys, then regenerate
-- audits/live-schema-public.txt (the 033 STEP 24b method) so that
-- test_schema_conformance.py admits the code that writes these columns.
-- Migration 037 (OUT-3) comes after this one.
-- =====================================================================


-- ---------------------------------------------------------------------
-- SECTION 1 — the table, its indexes, RLS, policy and grants
-- ---------------------------------------------------------------------
BEGIN;

CREATE TABLE IF NOT EXISTS public.chase_replies (
  id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid         NOT NULL
                                REFERENCES public.businesses(id) ON DELETE CASCADE,
  email_message_id uuid,
  customer_email   text         NOT NULL,
  invoice_ids      jsonb        NOT NULL DEFAULT '[]'::jsonb,
  category         text         NOT NULL,
  summary          text,
  status           text         NOT NULL DEFAULT 'open',
  resolved_by      uuid,
  resolved_at      timestamptz,
  created_at       timestamptz  NOT NULL DEFAULT now(),
  updated_at       timestamptz  NOT NULL DEFAULT now()
);

ALTER TABLE public.chase_replies
  DROP CONSTRAINT IF EXISTS chase_replies_status_chk;
ALTER TABLE public.chase_replies
  ADD CONSTRAINT chase_replies_status_chk
  CHECK (status IN ('open', 'resumed', 'stopped'));

ALTER TABLE public.chase_replies
  DROP CONSTRAINT IF EXISTS chase_replies_category_chk;
ALTER TABLE public.chase_replies
  ADD CONSTRAINT chase_replies_category_chk
  CHECK (category IN ('paid', 'promise', 'dispute', 'question', 'other', 'unknown'));

ALTER TABLE public.chase_replies
  DROP CONSTRAINT IF EXISTS chase_replies_invoice_ids_chk;
ALTER TABLE public.chase_replies
  ADD CONSTRAINT chase_replies_invoice_ids_chk
  CHECK (jsonb_typeof(invoice_ids) = 'array');

-- One reply per business per message (a scan twice flags it once).
CREATE UNIQUE INDEX IF NOT EXISTS chase_replies_biz_message_uq
  ON public.chase_replies USING btree (business_id, email_message_id);

-- "This business's replies awaiting the owner" and the autopilot's check.
CREATE INDEX IF NOT EXISTS idx_chase_replies_biz_status
  ON public.chase_replies USING btree (business_id, status, created_at DESC);

ALTER TABLE public.chase_replies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS chase_replies_member_read ON public.chase_replies;
CREATE POLICY chase_replies_member_read
  ON public.chase_replies
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), chase_replies.business_id)
         OR public.is_platform_admin(auth.uid()));

REVOKE ALL ON public.chase_replies FROM anon;
REVOKE ALL ON public.chase_replies FROM authenticated;
GRANT SELECT ON public.chase_replies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.chase_replies TO service_role;

COMMIT;


-- ---------------------------------------------------------------------
-- VERIFY 1a — expect 12 columns:
--   business_id uuid NO | category text NO | created_at timestamptz NO
--   | customer_email text NO | email_message_id uuid YES | id uuid NO
--   | invoice_ids jsonb NO | resolved_at timestamptz YES
--   | resolved_by uuid YES | status text NO | summary text YES
--   | updated_at timestamptz NO
-- ---------------------------------------------------------------------
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'chase_replies'
 ORDER BY column_name;

-- VERIFY 1b — expect rls_enabled = true:
--   SELECT relrowsecurity AS rls_enabled FROM pg_class
--    WHERE oid = 'public.chase_replies'::regclass;
--
-- VERIFY 1c — expect exactly ONE row:
--   chase_replies_member_read | SELECT | PERMISSIVE | {authenticated}
--   | has_using=true | has_check=false
--   SELECT policyname, cmd, permissive, roles::text,
--          qual IS NOT NULL AS has_using, with_check IS NOT NULL AS has_check
--     FROM pg_policies
--    WHERE schemaname = 'public' AND tablename = 'chase_replies';
--
-- VERIFY 1d — THE ONE THAT MATTERS. Expect authenticated | SELECT, then
-- service_role's 7 privileges. anon MUST NOT APPEAR:
--   SELECT grantee, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE table_schema = 'public' AND table_name = 'chase_replies'
--      AND grantee IN ('anon', 'authenticated', 'service_role')
--    ORDER BY grantee, privilege_type;
--
-- VERIFY 1e — the CHECKs bite. Each INSERT must FAIL; wrapped, never commits:
--   BEGIN;
--     INSERT INTO public.chase_replies (business_id, customer_email, category)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1), 'x@example.invalid', 'refund_them');
--   ROLLBACK;
--   BEGIN;
--     INSERT INTO public.chase_replies (business_id, customer_email, category, status)
--     VALUES ((SELECT id FROM public.businesses LIMIT 1), 'x@example.invalid', 'other', 'deleted');
--   ROLLBACK;
--
-- VERIFY 1f — the table is empty. Expect 0:
--   SELECT count(*) FROM public.chase_replies;


-- ---------------------------------------------------------------------
-- ROLLBACK 1 — run ONLY to undo SECTION 1. This drops the table, its
-- policy, indexes and grants. Once AUTO-2 has deployed, the rows are the
-- owner's pauses and decisions, so capture them first:
--   SELECT * FROM public.chase_replies ORDER BY created_at;
-- Dropping the table while AUTO-2 is deployed stops chasing everywhere:
-- the autopilot cannot read the pauses, so it errors rather than chases.
-- ---------------------------------------------------------------------
-- BEGIN;
-- DROP TABLE IF EXISTS public.chase_replies;
-- COMMIT;
