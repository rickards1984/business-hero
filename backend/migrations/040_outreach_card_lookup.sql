-- 040 — OUT-24: find an outreach email's card by its enrolment. Run by Mike
-- from audits/040-PROD-RUNBOOK.md, staging first.
-- Before the pilot limit of 5 contacts per campaign is lifted (OUT-10
-- decision E; OUT-8 note 2), each card lookup must be indexed rather than a
-- scan of every open card. The expression and predicate are exactly
-- outreach_send.OPEN_CARD_WHERE's. Adds one index; changes no data.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE INDEX IF NOT EXISTS idx_aria_actions_outreach_enrolment
  ON public.aria_actions (business_id, ((payload->>'enrolment_id')))
  WHERE action_type = 'send_outreach';

COMMIT;
