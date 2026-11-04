-- 040: TRADE-0 §3, server-side OAuth state. Run by Mike from audits/040-PROD-RUNBOOK.md.
-- One row per connection attempt: a single-use, expiring token bound to the
-- person who started it, the business, the provider and the operation. The
-- callback consumes it atomically and rechecks the person's CURRENT owner
-- authority before any credential is saved. Backend only: no client role may
-- read or write. Adds one empty table; changes no existing data.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.oauth_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  user_id uuid NOT NULL,
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('google', 'microsoft', 'xero', 'freeagent', 'quickbooks')),
  operation text NOT NULL CHECK (length(operation) BETWEEN 1 AND 60),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS oauth_states_expires_at_idx ON public.oauth_states (expires_at);

REVOKE ALL ON public.oauth_states FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.oauth_states ENABLE ROW LEVEL SECURITY;

COMMIT;
