-- 043 — RCP-1: receptionist phone numbers, requested in the app and set up by
-- Mike's Approve (docs/RCP-1-TICKET.md). Run by Mike from
-- audits/043-PROD-RUNBOOK.md, staging first.
--   1. One number, one business (R1). receptionist_configs.twilio_phone_number
--      had no UNIQUE constraint, so a number given to two businesses would
--      split its calls. STEP 0 of the runbook checks for duplicates first.
--   2. receptionist_number_requests: one row per request, backend only. It
--      holds the business's own legal name and address for the UK regulator,
--      the local numbers Mike's Check listed (approval must pick one), the
--      Twilio number once bought, and the claim that makes a purchase happen
--      at most once (R3).
-- Changes no existing row.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE UNIQUE INDEX IF NOT EXISTS uq_receptionist_configs_twilio_phone_number
  ON public.receptionist_configs (twilio_phone_number)
  WHERE twilio_phone_number IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.receptionist_number_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  requested_by uuid,
  state text NOT NULL CHECK (state IN ('requested', 'waiting_bundle', 'buying', 'bought', 'live', 'declined', 'cancelled')),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  mode text NOT NULL CHECK (mode IN ('new_local', 'keep_existing')),
  area_code text,
  existing_number text,
  legal_name text NOT NULL,
  address_line1 text NOT NULL,
  address_line2 text,
  city text NOT NULL,
  postcode text NOT NULL,
  setup text NOT NULL CHECK (setup IN ('self', 'done_for_you')),
  in_plan boolean NOT NULL,
  setup_fee_pence integer NOT NULL DEFAULT 0 CHECK (setup_fee_pence >= 0),
  bundle_sid text,
  address_sid text,
  candidates text,
  chosen_number text,
  monthly_pence integer CHECK (monthly_pence IS NULL OR monthly_pence BETWEEN 1 AND 500),
  number_sid text,
  phone_number text,
  claim_token text,
  claimed_at timestamptz,
  last_error text,
  decided_by uuid,
  decided_at timestamptz,
  decline_reason text,
  bought_at timestamptz,
  live_at timestamptz,
  owner_told_at timestamptz
);

-- At most one open request per business.
CREATE UNIQUE INDEX IF NOT EXISTS uq_receptionist_number_requests_open
  ON public.receptionist_number_requests (business_id)
  WHERE state IN ('requested', 'waiting_bundle', 'buying', 'bought');

REVOKE ALL ON public.receptionist_number_requests FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.receptionist_number_requests ENABLE ROW LEVEL SECURITY;

COMMIT;
