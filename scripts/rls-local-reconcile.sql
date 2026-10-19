-- OUT-3: disposable LOCAL replay only; never apply to staging/production.
-- Column evidence: audits/live-schema-public.txt lines 342–354 (to_emails
-- is text[], as in backend/migrations/007_email_accounts_messages.sql).
-- 006 wins CREATE IF NOT EXISTS during historical replay, leaving its old
-- SMTP shape. Reconcile columns without recreating the table or guessing live
-- constraints: preserve the replay's existing policies, grants and keys.
-- Claude must independently review/replay this correction before 037 approval.
BEGIN;
LOCK TABLE public.email_outbox IN ACCESS EXCLUSIVE MODE;
DO $local_reconcile$
BEGIN
  IF EXISTS (SELECT 1 FROM public.email_outbox) THEN
    RAISE EXCEPTION 'Local outbox reconciliation requires an empty replay table';
  END IF;
END;
$local_reconcile$;

ALTER TABLE public.email_outbox RENAME COLUMN body TO body_preview;
ALTER TABLE public.email_outbox RENAME COLUMN error_message TO error;
ALTER TABLE public.email_outbox RENAME COLUMN to_email TO to_emails;
ALTER TABLE public.email_outbox
  ALTER COLUMN to_emails TYPE text[] USING ARRAY[to_emails],
  ALTER COLUMN status DROP DEFAULT,
  ADD COLUMN email_account_id uuid NOT NULL,
  ADD COLUMN provider_message_id text;
COMMIT;
