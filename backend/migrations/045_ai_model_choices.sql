-- 045 — AI-1: the model switchboard's saved choices (docs/AI-1-TICKET.md, M6).
-- Run by Mike from audits/045-PROD-RUNBOOK.md, staging first.
--
-- One row per AI task that Mike has chosen a model for on the admin page:
-- the ordered list of {provider, model} to try, who changed it and when, and
-- the previous list (for Revert). Platform-wide, backend only: no browser
-- role can read or write it. With no rows every task uses the model its code
-- used before AI-1 (services/ai_models.py), so creating it changes nothing.
-- Changes no existing row.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS public.ai_model_choices (
  task text PRIMARY KEY CHECK (task ~ '^[a-z][a-z0-9_]{0,39}$'),
  chain jsonb NOT NULL CHECK (jsonb_typeof(chain) = 'array'
                              AND jsonb_array_length(chain) BETWEEN 1 AND 6
                              AND octet_length(chain::text) <= 4096),
  changed_by uuid,
  changed_at timestamptz NOT NULL DEFAULT now(),
  previous jsonb CHECK (previous IS NULL OR (jsonb_typeof(previous) = 'array'
                                             AND octet_length(previous::text) <= 4096))
);

REVOKE ALL ON public.ai_model_choices FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.ai_model_choices ENABLE ROW LEVEL SECURITY;

COMMIT;
