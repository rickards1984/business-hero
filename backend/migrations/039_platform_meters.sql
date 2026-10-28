-- 039 — PROFIT-1: platform-level meters. Run by Mike from audits/039-PROD-RUNBOOK.md.
-- usage_meters.business_id is a UUID tied to a business, so costs no business
-- owns (an AI call with no business) and the profit guard's once-a-month alert
-- markers need their own table. Backend only: no client role may read or write.
-- Adds one empty table; changes no existing data.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.platform_meters (
  period text NOT NULL CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  meter text NOT NULL CHECK (length(meter) BETWEEN 1 AND 200),
  value numeric(14,4) NOT NULL DEFAULT 0 CHECK (value >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (period, meter)
);

REVOKE ALL ON public.platform_meters FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.platform_meters ENABLE ROW LEVEL SECURITY;

COMMIT;
