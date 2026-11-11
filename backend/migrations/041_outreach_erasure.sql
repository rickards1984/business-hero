-- 041 — OUT-13 core: erase a never-contacted contact at its deadline. Run by
-- Mike from audits/041-PROD-RUNBOOK.md, staging first.
-- Adds two indexes for the hourly work list and two backend-only tables: the
-- 90-day re-collection guard (tenant-keyed digests, never addresses) and the
-- owner-visible list of contacts whose erasure is blocked and why.
-- Changes no existing row.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE INDEX IF NOT EXISTS idx_outreach_prospects_uncontacted_captured
  ON public.outreach_prospects (captured_at, business_id, id)
  WHERE notice_provided_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_outreach_prospects_uncontacted_notice
  ON public.outreach_prospects (notice_due_at, business_id, id)
  WHERE notice_provided_at IS NULL;

CREATE TABLE IF NOT EXISTS public.outreach_recently_erased (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  key_type text NOT NULL CHECK (key_type IN ('email', 'domain')),
  key_digest text NOT NULL CHECK (length(key_digest) BETWEEN 16 AND 128),
  digest_version integer NOT NULL DEFAULT 1 CHECK (digest_version > 0),
  until timestamptz NOT NULL,
  UNIQUE (business_id, key_type, key_digest)
);

CREATE INDEX IF NOT EXISTS idx_outreach_recently_erased_until
  ON public.outreach_recently_erased (until);

REVOKE ALL ON public.outreach_recently_erased FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_recently_erased ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_erasure_exceptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  prospect_id uuid NOT NULL,
  reason text NOT NULL CHECK (reason IN ('may_have_sent', 'contacted', 'cross_reference', 'orphaned_card', 'error')),
  first_seen_at timestamptz NOT NULL,
  last_checked_at timestamptz NOT NULL,
  UNIQUE (business_id, prospect_id)
);

CREATE INDEX IF NOT EXISTS idx_outreach_erasure_exceptions_checked
  ON public.outreach_erasure_exceptions (last_checked_at);

REVOKE ALL ON public.outreach_erasure_exceptions FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_erasure_exceptions ENABLE ROW LEVEL SECURITY;

COMMIT;
