-- 044 — OUT-28a fix: let a contact part way through a campaign move to new
-- wording when the owner edits it (docs/OUT-28-TICKET.md, E1). Run by Mike
-- from audits/044-PROD-RUNBOOK.md, staging first.
--
-- Production, 19 Nov 2026: saving New Body's edited emails failed with
--   ForeignKeyViolation ... "outreach_messages_business_id_campaign_id_sequence_version_fkey"
-- 037 tied every email record to its contact's CURRENT wording version, in
-- two places:
--   1. a foreign key (business_id, campaign_id, sequence_version, enrolment_id)
--      -> outreach_enrolments, so a contact with any email history (even a
--      failed send) could never move to new wording; and
--   2. the trigger outreach_bind_message_version, which on EVERY update of an
--      email record reset its version to the contact's current one, so after
--      a move any later update of an old email (settling an outcome, matching
--      a reply, erasure clearing references) would be refused by the step key
--      (Codex OUT-28 fix review 1, finding 1).
-- This drops (1) and makes (2) bind the version only when an email record is
-- created or re-pointed to another contact; otherwise it keeps the version it
-- has, so an email always remembers the wording it was sent with.
--
-- What still holds:
--   * every email record names its contact (business_id, campaign_id,
--     prospect_id, enrolment_id) — checked below, the migration refuses
--     without it;
--   * its own wording: (business_id, campaign_id, sequence_version, step_id)
--     must be a real step of that version (the step key) — checked below;
--   * on insert, its version is the contact's version (the trigger);
--   * the send path requires contact == campaign == step version when it
--     sends (services/outreach_send.py).
-- Changes no row. Constraints are found by their exact columns, not by name or
-- printed text (Codex review 1, finding 2). Idempotent.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE
  messages oid := 'public.outreach_messages'::regclass;
  enrolments oid := 'public.outreach_enrolments'::regclass;
  steps oid := 'public.outreach_sequence_steps'::regclass;
  pinned text[];
  kept int;
  identity int;
BEGIN
  -- The key to drop: messages(business_id, campaign_id, sequence_version, enrolment_id)
  --   -> enrolments(business_id, campaign_id, sequence_version, id), in that order.
  SELECT array_agg(c.conname ORDER BY c.conname) INTO pinned
  FROM pg_constraint c
  WHERE c.conrelid = messages AND c.confrelid = enrolments AND c.contype = 'f'
    AND ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n, i)
              JOIN pg_attribute a ON a.attrelid = messages AND a.attnum = k.n ORDER BY k.i)
        = ARRAY['business_id', 'campaign_id', 'sequence_version', 'enrolment_id']
    AND ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n, i)
              JOIN pg_attribute a ON a.attrelid = enrolments AND a.attnum = k.n ORDER BY k.i)
        = ARRAY['business_id', 'campaign_id', 'sequence_version', 'id'];

  -- Any OTHER key from messages to enrolments that involves sequence_version is
  -- unexpected: stop rather than report "already applied" (finding 2).
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    WHERE c.conrelid = messages AND c.confrelid = enrolments AND c.contype = 'f'
      AND (SELECT attnum FROM pg_attribute WHERE attrelid = messages AND attname = 'sequence_version') = ANY (c.conkey)
      AND c.conname <> ALL (coalesce(pinned, ARRAY[]::text[]))) THEN
    RAISE EXCEPTION '044: an unexpected version key from outreach_messages to outreach_enrolments exists';
  END IF;

  -- What must remain: the contact key and the step key, by their columns on
  -- BOTH sides (Codex fix review 2, finding 2).
  SELECT count(*) INTO identity FROM pg_constraint c
  WHERE c.conrelid = messages AND c.confrelid = enrolments AND c.contype = 'f'
    AND ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n, i)
              JOIN pg_attribute a ON a.attrelid = messages AND a.attnum = k.n ORDER BY k.i)
        = ARRAY['business_id', 'campaign_id', 'prospect_id', 'enrolment_id']
    AND ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n, i)
              JOIN pg_attribute a ON a.attrelid = enrolments AND a.attnum = k.n ORDER BY k.i)
        = ARRAY['business_id', 'campaign_id', 'prospect_id', 'id'];
  SELECT count(*) INTO kept FROM pg_constraint c
  WHERE c.conrelid = messages AND c.confrelid = steps AND c.contype = 'f'
    AND ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n, i)
              JOIN pg_attribute a ON a.attrelid = messages AND a.attnum = k.n ORDER BY k.i)
        = ARRAY['business_id', 'campaign_id', 'sequence_version', 'step_id']
    AND ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n, i)
              JOIN pg_attribute a ON a.attrelid = steps AND a.attnum = k.n ORDER BY k.i)
        = ARRAY['business_id', 'campaign_id', 'sequence_version', 'id'];
  IF identity <> 1 OR kept <> 1 THEN
    RAISE EXCEPTION '044: expected the contact key and the step key to exist (found %, %)', identity, kept;
  END IF;
  -- The trigger that binds a new email's version must be attached, fire in
  -- normal operation ('O' origin or 'A' always; not 'D' disabled or 'R'
  -- replica-only), and be BEFORE ROW for INSERT and UPDATE: tgtype bits
  -- ROW 1, BEFORE 2, INSERT 4, UPDATE 16 (Codex fix reviews 2 and 3).
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger t JOIN pg_proc f ON f.oid = t.tgfoid
    JOIN pg_namespace n ON n.oid = f.pronamespace
    WHERE t.tgrelid = messages AND t.tgname = 'outreach_message_version' AND NOT t.tgisinternal
      AND t.tgenabled IN ('O', 'A') AND n.nspname = 'public' AND f.proname = 'outreach_bind_message_version'
      AND (t.tgtype & 1) <> 0 AND (t.tgtype & 2) <> 0 AND (t.tgtype & 4) <> 0 AND (t.tgtype & 16) <> 0) THEN
    RAISE EXCEPTION '044: trigger outreach_message_version is missing, not firing normally, or not BEFORE ROW INSERT/UPDATE';
  END IF;

  IF pinned IS NULL THEN
    RAISE NOTICE '044: version-pinning key already gone';
  ELSIF array_length(pinned, 1) <> 1 THEN
    RAISE EXCEPTION '044: expected one version-pinning key, found %', pinned;
  ELSE
    EXECUTE format('ALTER TABLE public.outreach_messages DROP CONSTRAINT %I', pinned[1]);
    RAISE NOTICE '044: dropped %', pinned[1];
  END IF;
END $$;

-- Bind the version when an email record is created or re-pointed to another
-- contact; otherwise keep it (an email never changes the wording it was sent
-- with). A caller still cannot set the version itself.
CREATE OR REPLACE FUNCTION public.outreach_bind_message_version()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.enrolment_id IS NOT DISTINCT FROM OLD.enrolment_id THEN
    NEW.sequence_version := OLD.sequence_version;   -- 044: history keeps its wording
    RETURN NEW;
  END IF;
  IF NEW.enrolment_id IS NULL THEN
    NEW.sequence_version := NULL;
  ELSE
    SELECT e.sequence_version INTO NEW.sequence_version
      FROM public.outreach_enrolments e
      WHERE e.business_id = NEW.business_id AND e.id = NEW.enrolment_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Enrolment not in business' USING ERRCODE = '23503';
    END IF;
  END IF;
  RETURN NEW;
END;
$fn$;
REVOKE ALL ON FUNCTION public.outreach_bind_message_version() FROM PUBLIC, anon, authenticated;

COMMIT;
