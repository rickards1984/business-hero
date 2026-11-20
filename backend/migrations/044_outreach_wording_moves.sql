-- 044 — OUT-28a fix: let a contact part way through a campaign move to new
-- wording when the owner edits it (docs/OUT-28-TICKET.md, E1). Run by Mike
-- from audits/044-PROD-RUNBOOK.md, staging first.
--
-- Production, 19 Nov 2026: saving New Body's edited emails failed with
--   ForeignKeyViolation ... "outreach_messages_business_id_campaign_id_sequence_version_fkey"
-- 037 tied every email record to its contact's CURRENT wording version, so a
-- contact with any email history (even a failed send) could never move to new
-- wording. This drops that one constraint.
--
-- What still holds:
--   * every email record still names its contact (business_id, campaign_id,
--     prospect_id, enrolment_id), and
--   * its own wording: (business_id, campaign_id, sequence_version, step_id)
--     must be a real step of that version (the "..._fkey1" constraint). An
--     email always remembers exactly the wording it was sent with.
--   * The send path still requires contact == campaign == step version at
--     the moment of sending (services/outreach_send.py).
-- Changes no row. Dropped by its definition, not its name, and only if it is
-- exactly the one constraint expected; idempotent.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE
  found text[];
BEGIN
  SELECT array_agg(c.conname ORDER BY c.conname) INTO found
  FROM pg_constraint c
  WHERE c.conrelid = 'public.outreach_messages'::regclass
    AND c.contype = 'f'
    AND c.confrelid = 'public.outreach_enrolments'::regclass
    AND pg_get_constraintdef(c.oid) =
        'FOREIGN KEY (business_id, campaign_id, sequence_version, enrolment_id) '
        'REFERENCES outreach_enrolments(business_id, campaign_id, sequence_version, id)';
  IF found IS NULL THEN
    RAISE NOTICE '044: already applied (no version-pinning constraint found)';
  ELSIF array_length(found, 1) <> 1 THEN
    RAISE EXCEPTION '044: expected one constraint, found %', found;
  ELSE
    EXECUTE format('ALTER TABLE public.outreach_messages DROP CONSTRAINT %I', found[1]);
    RAISE NOTICE '044: dropped %', found[1];
  END IF;
END $$;

COMMIT;
