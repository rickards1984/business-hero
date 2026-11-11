-- 042 — OUT-23 Part B: the Hunter.io add-on. Run by Mike from
-- audits/042-PROD-RUNBOOK.md, staging first.
-- Two backend-only tables, neither holding personal data:
--   outreach_provider_accounts: one row per business and provider. The key is
--     Fernet-encrypted; the row is never deleted (disconnect leaves a
--     tombstone), so `generation` never repeats (design R3.1, R4.1).
--   outreach_provider_charges: one row per billable call, reserved before the
--     call and settled after it (R3.2, R4.3). No domain, email or person.
-- Changes no existing row.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE TABLE IF NOT EXISTS public.outreach_provider_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  provider text NOT NULL CHECK (provider IN ('hunter')),
  key_ciphertext text,
  key_last4 text CHECK (key_last4 IS NULL OR length(key_last4) <= 4),
  generation integer NOT NULL CHECK (generation > 0),
  status text NOT NULL CHECK (status IN ('connected', 'invalid', 'disconnected')),
  plan text,
  pools jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(pools) = 'object'),
  account_fetched_at timestamptz,
  blocked jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(blocked) = 'object'),
  connected_by uuid,
  connected_at timestamptz,
  CHECK (status <> 'connected' OR key_ciphertext IS NOT NULL),
  UNIQUE (business_id, provider)
);

REVOKE ALL ON public.outreach_provider_accounts FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_provider_accounts ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_provider_charges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  brand_id uuid NOT NULL,
  provider text NOT NULL CHECK (provider IN ('hunter')),
  generation integer NOT NULL CHECK (generation > 0),
  operation text NOT NULL CHECK (operation IN ('search', 'verify')),
  pool text NOT NULL CHECK (pool IN ('credit', 'search', 'verification')),
  reserved_native numeric(10,4) NOT NULL CHECK (reserved_native >= 0),
  brand_credits numeric(10,4) NOT NULL CHECK (brand_credits >= 0),
  used_native numeric(10,4) CHECK (used_native IS NULL OR used_native >= 0),
  pool_actual text CHECK (pool_actual IS NULL OR pool_actual IN ('credit', 'search', 'verification')),
  state text NOT NULL CHECK (state IN ('reserved', 'settled', 'charged')),
  period text NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
  settled_at timestamptz,
  FOREIGN KEY (business_id, brand_id) REFERENCES public.outreach_brands (business_id, id)
);

CREATE INDEX IF NOT EXISTS idx_outreach_provider_charges_brand_period
  ON public.outreach_provider_charges (business_id, brand_id, period);

CREATE INDEX IF NOT EXISTS idx_outreach_provider_charges_reserved
  ON public.outreach_provider_charges (created_at)
  WHERE state = 'reserved';

REVOKE ALL ON public.outreach_provider_charges FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_provider_charges ENABLE ROW LEVEL SECURITY;

COMMIT;
