-- 046 — ARIA-1b: how the owner writes their replies (docs/ARIA-PROACTIVE-TICKETS.md, ARIA-1 §4).
-- Run by Mike from audits/046-PROD-RUNBOOK.md, staging first.
--
-- One row each time the owner SENDS one of Aria's drafted replies: the draft
-- Aria wrote and the reply the owner actually sent (edited or not), with the
-- category of the email it answered. The few most recent rows are shown to
-- the drafter as examples of the owner's style. Nothing is stored for a
-- draft the owner didn't send. The owner can see and delete them; the
-- backend keeps at most the 20 most recent per business and category. Deleting
-- the business, or the email answered, deletes its rows (copied text included).
-- Backend only: no browser role can read or write it. Empty at creation,
-- so creating it changes nothing. Changes no existing row.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS public.inbox_reply_examples (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  category text NOT NULL CHECK (category IN ('new_enquiry', 'customer', 'complaint')),
  email_message_id uuid REFERENCES public.email_messages(id) ON DELETE CASCADE,   -- the email gone: its copied text goes too
  incoming_subject text CHECK (incoming_subject IS NULL OR char_length(incoming_subject) <= 500),
  incoming_excerpt text CHECK (incoming_excerpt IS NULL OR char_length(incoming_excerpt) <= 2000),
  draft_body text NOT NULL CHECK (char_length(draft_body) BETWEEN 1 AND 10000),
  sent_body text NOT NULL CHECK (char_length(sent_body) BETWEEN 1 AND 10000),
  edited boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS inbox_reply_examples_recent
  ON public.inbox_reply_examples (business_id, category, created_at DESC);

REVOKE ALL ON public.inbox_reply_examples FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.inbox_reply_examples ENABLE ROW LEVEL SECURITY;

COMMIT;
