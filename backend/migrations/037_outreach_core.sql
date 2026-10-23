-- 037 — OUT-3 outreach core. DRAFT: not replayed or applied to any database.
-- North Star P4/P9: approval boundary, tenant isolation and correctness.
-- Mike approved Stage A tests 19 Oct 2026. Claude independently reviews/replays.
-- Apply sections individually using audits/037-PROD-RUNBOOK.md. Do NOT paste
-- the whole file into the SQL editor: concurrent indexes require autocommit.
-- No data writes, permission grants, model registration or sending enabled.
-- OUT-4 must supply scoped read tools before application population/exposure.

-- SECTION 1 — EXISTING PARENT INDEXES: OUTSIDE ANY TRANSACTION.
-- Run EACH CREATE as a separate SQL-editor execution. IF NOT EXISTS is safe
-- only after checking the existing index is valid and has this definition.
-- A failed concurrent build can leave an INVALID index; see the runbook.

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_accounts_out3_business_id_key
  ON public.email_accounts (business_id, id);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS aria_actions_out3_business_id_key
  ON public.aria_actions (business_id, id);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_outbox_out3_business_id_key
  ON public.email_outbox (business_id, id);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_messages_out3_business_id_key
  ON public.email_messages (business_id, id);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_outbox_out3_mailbox_id_key
  ON public.email_outbox (business_id, email_account_id, id);

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_messages_out3_mailbox_id_key
  ON public.email_messages (business_id, email_account_id, id);


-- SECTION 2 — ATTACH PARENT KEYS, CREATE CORE, CHECKS, RLS AND GRANTS.
BEGIN;
SET LOCAL lock_timeout = '5s';
-- Attaching needs a brief table lock; timeout rolls this entire section back.
-- Do not drop attached keys on re-paste: existing child FKs depend on them.

DO $attach$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.email_accounts'::regclass AND conname = 'email_accounts_out3_business_id_key') THEN
    ALTER TABLE public.email_accounts ADD CONSTRAINT email_accounts_out3_business_id_key UNIQUE USING INDEX email_accounts_out3_business_id_key;
  END IF;
END;
$attach$;

DO $attach$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.aria_actions'::regclass AND conname = 'aria_actions_out3_business_id_key') THEN
    ALTER TABLE public.aria_actions ADD CONSTRAINT aria_actions_out3_business_id_key UNIQUE USING INDEX aria_actions_out3_business_id_key;
  END IF;
END;
$attach$;

DO $attach$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.email_outbox'::regclass AND conname = 'email_outbox_out3_business_id_key') THEN
    ALTER TABLE public.email_outbox ADD CONSTRAINT email_outbox_out3_business_id_key UNIQUE USING INDEX email_outbox_out3_business_id_key;
  END IF;
END;
$attach$;

DO $attach$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.email_messages'::regclass AND conname = 'email_messages_out3_business_id_key') THEN
    ALTER TABLE public.email_messages ADD CONSTRAINT email_messages_out3_business_id_key UNIQUE USING INDEX email_messages_out3_business_id_key;
  END IF;
END;
$attach$;

DO $attach$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.email_outbox'::regclass AND conname = 'email_outbox_out3_mailbox_id_key') THEN
    ALTER TABLE public.email_outbox ADD CONSTRAINT email_outbox_out3_mailbox_id_key UNIQUE USING INDEX email_outbox_out3_mailbox_id_key;
  END IF;
END;
$attach$;

DO $attach$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.email_messages'::regclass AND conname = 'email_messages_out3_mailbox_id_key') THEN
    ALTER TABLE public.email_messages ADD CONSTRAINT email_messages_out3_mailbox_id_key UNIQUE USING INDEX email_messages_out3_mailbox_id_key;
  END IF;
END;
$attach$;

ALTER TABLE public.aria_actions DROP CONSTRAINT IF EXISTS aria_actions_type_chk;
ALTER TABLE public.aria_actions ADD CONSTRAINT aria_actions_type_chk
  CHECK (action_type IN ('send_email', 'send_invoice_chase', 'create_calendar_event',
                        'create_task', 'send_outreach', 'reply_outreach'));
-- Existing status CHECK, payloads, approvers and settings are untouched.

CREATE TABLE IF NOT EXISTS public.outreach_brands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  name text NOT NULL,
  default_mailbox_id uuid,
  privacy_url text NOT NULL,
  sender_identity text NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  UNIQUE (business_id, id),
  UNIQUE (business_id, name),
  FOREIGN KEY (business_id, default_mailbox_id) REFERENCES public.email_accounts (business_id, id)
);

REVOKE ALL ON public.outreach_brands FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_brands ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_settings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  pause_all boolean NOT NULL DEFAULT true,
  timezone text NOT NULL DEFAULT 'Europe/London' CHECK (timezone = 'Europe/London'),
  business_daily_cap integer NOT NULL DEFAULT 20 CHECK (business_daily_cap BETWEEN 1 AND 20),
  owner_cc_default boolean NOT NULL DEFAULT false,
  owner_cc_address text,
  retention_policy_version integer NOT NULL CHECK (retention_policy_version > 0),
  UNIQUE (business_id, id),
  UNIQUE (business_id),
  CHECK (NOT owner_cc_default OR owner_cc_address IS NOT NULL)
);

REVOKE ALL ON public.outreach_settings FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_settings ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_mailboxes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  mailbox_id uuid NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  pause_reason text,
  daily_cap integer NOT NULL CHECK (daily_cap BETWEEN 1 AND 20),
  warmup_stage integer NOT NULL CHECK (warmup_stage IN (5,10,20)),
  sending_days integer NOT NULL DEFAULT 0 CHECK (sending_days >= 0),
  health_status text NOT NULL DEFAULT 'unknown' CHECK (health_status IN ('unknown', 'pass', 'fail', 'stale')),
  health_checked_at timestamptz,
  health_evidence jsonb NOT NULL CHECK (jsonb_typeof(health_evidence) = 'object' AND octet_length(health_evidence::text) <= 16384),
  health_reviewed_by uuid,
  health_reviewed_at timestamptz,
  UNIQUE (business_id, id),
  UNIQUE (business_id, mailbox_id),
  FOREIGN KEY (business_id, mailbox_id) REFERENCES public.email_accounts (business_id, id)
);

REVOKE ALL ON public.outreach_mailboxes FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_mailboxes ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_compliance (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  brand_id uuid NOT NULL,
  audience_hash text NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  purpose text NOT NULL,
  necessity text NOT NULL,
  balancing_test text NOT NULL,
  safeguards text NOT NULL,
  sources jsonb NOT NULL CHECK (jsonb_typeof(sources) = 'array' AND octet_length(sources::text) <= 16384),
  decision text NOT NULL DEFAULT 'draft' CHECK (decision IN ('draft', 'approved', 'rejected')),
  reviewer uuid,
  reviewed_at timestamptz,
  review_due_at timestamptz NOT NULL,
  UNIQUE (business_id, id),
  UNIQUE (business_id, brand_id, audience_hash, version),
  FOREIGN KEY (business_id, brand_id) REFERENCES public.outreach_brands (business_id, id),
  CHECK (decision <> 'approved' OR (reviewer IS NOT NULL AND reviewed_at IS NOT NULL))
);

REVOKE ALL ON public.outreach_compliance FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_compliance ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_prospects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  company text,
  name text,
  role text,
  domain text,
  number text,
  email text,
  email_key text,
  subscriber_type text NOT NULL DEFAULT 'unknown' CHECK (subscriber_type IN ('corporate', 'individual', 'unknown')),
  eligibility text NOT NULL DEFAULT 'blocked' CHECK (eligibility IN ('blocked', 'review', 'eligible')),
  lawful_basis text,
  lia_id uuid,
  stage text NOT NULL DEFAULT 'new' CHECK (stage IN ('new', 'research', 'ready', 'contacted', 'replied', 'qualified', 'meeting', 'won', 'closed')),
  fit_score numeric CHECK (fit_score BETWEEN 0 AND 100),
  confidence numeric CHECK (confidence BETWEEN 0 AND 100),
  why_now text,
  evidence_checked_at timestamptz,
  captured_at timestamptz NOT NULL,
  first_contact_at timestamptz,
  last_contact_at timestamptz,
  notice_due_at timestamptz,
  notice_provided_at timestamptz,
  retention_due_at timestamptz NOT NULL,
  owner_user_id uuid,
  UNIQUE (business_id, id),
  CHECK ((email IS NULL) = (email_key IS NULL)),
  FOREIGN KEY (business_id, lia_id) REFERENCES public.outreach_compliance (business_id, id)
);

REVOKE ALL ON public.outreach_prospects FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_prospects ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  prospect_id uuid NOT NULL,
  source_type text NOT NULL,
  operation text NOT NULL,
  source_url text,
  excerpt text CHECK (length(excerpt) <= 4000),
  fact_type text NOT NULL,
  fact_value text NOT NULL CHECK (length(fact_value) <= 4000),
  provider_record_id text,
  confidence numeric CHECK (confidence BETWEEN 0 AND 100),
  scale text,
  verification_status text,
  verification_subject_email_key text,
  raw_verdict text CHECK (length(raw_verdict) <= 256),
  flags jsonb CHECK (jsonb_typeof(flags) = 'array' AND octet_length(flags::text) <= 4096),
  fetched_at timestamptz NOT NULL,
  verified_at timestamptz,
  expires_at timestamptz NOT NULL,
  adapter_version text,
  model_config_version text,
  UNIQUE (business_id, id),
  FOREIGN KEY (business_id, prospect_id) REFERENCES public.outreach_prospects (business_id, id),
  CHECK (verification_status IS NULL OR verification_subject_email_key IS NOT NULL)
);

REVOKE ALL ON public.outreach_evidence FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_evidence ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  brand_id uuid NOT NULL,
  mailbox_id uuid NOT NULL,
  name text NOT NULL,
  target_rules jsonb NOT NULL CHECK (jsonb_typeof(target_rules) = 'object' AND octet_length(target_rules::text) <= 16384),
  target_hash text NOT NULL,
  sequence_version integer NOT NULL CHECK (sequence_version > 0),
  version integer NOT NULL CHECK (version > 0),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ready', 'running', 'paused', 'completed')),
  timezone text NOT NULL CHECK (timezone = 'Europe/London'),
  daily_cap integer NOT NULL CHECK (daily_cap BETWEEN 1 AND 20),
  first_batch_review_id uuid,
  UNIQUE (business_id, id),
  FOREIGN KEY (business_id, brand_id) REFERENCES public.outreach_brands (business_id, id),
  FOREIGN KEY (business_id, mailbox_id) REFERENCES public.email_accounts (business_id, id),
  UNIQUE (business_id, mailbox_id, id)
);

REVOKE ALL ON public.outreach_campaigns FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_campaigns ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_batch_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  campaign_id uuid NOT NULL,
  campaign_version integer NOT NULL CHECK (campaign_version > 0),
  mailbox_id uuid NOT NULL,
  target_hash text NOT NULL,
  template_set_hash text NOT NULL,
  eligible_count integer NOT NULL CHECK (eligible_count BETWEEN 0 AND 5),
  reviewed_count integer NOT NULL DEFAULT 0 CHECK (reviewed_count BETWEEN 0 AND 5),
  reviewed_by uuid,
  reviewed_at timestamptz,
  UNIQUE (business_id, id),
  UNIQUE (business_id, campaign_id, campaign_version),
  UNIQUE (business_id, campaign_id, mailbox_id, id),
  CHECK (reviewed_count <= eligible_count),
  FOREIGN KEY (business_id, mailbox_id, campaign_id) REFERENCES public.outreach_campaigns (business_id, mailbox_id, id)
);

REVOKE ALL ON public.outreach_batch_reviews FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_batch_reviews ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.outreach_campaigns DROP CONSTRAINT IF EXISTS outreach_campaigns_first_review_fk;
ALTER TABLE public.outreach_campaigns ADD CONSTRAINT outreach_campaigns_first_review_fk
  FOREIGN KEY (business_id, id, mailbox_id, first_batch_review_id)
  REFERENCES public.outreach_batch_reviews (business_id, campaign_id, mailbox_id, id);

CREATE TABLE IF NOT EXISTS public.outreach_sequence_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  campaign_id uuid NOT NULL,
  sequence_version integer NOT NULL CHECK (sequence_version > 0),
  ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 2),
  delay_business_days integer NOT NULL,
  template_text text NOT NULL,
  template_hash text NOT NULL,
  allowed_variables jsonb NOT NULL CHECK (jsonb_typeof(allowed_variables) = 'array' AND octet_length(allowed_variables::text) <= 16384),
  approved_by uuid,
  approved_at timestamptz,
  UNIQUE (business_id, id),
  UNIQUE (business_id, campaign_id, sequence_version, ordinal),
  UNIQUE (business_id, campaign_id, id),
  UNIQUE (business_id, campaign_id, sequence_version, id),
  FOREIGN KEY (business_id, campaign_id) REFERENCES public.outreach_campaigns (business_id, id),
  CHECK ((ordinal = 0 AND delay_business_days = 0) OR (ordinal = 1 AND delay_business_days = 5) OR (ordinal = 2 AND delay_business_days = 7))
);

REVOKE ALL ON public.outreach_sequence_steps FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_sequence_steps ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_enrolments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  prospect_id uuid NOT NULL,
  campaign_id uuid NOT NULL,
  sequence_version integer NOT NULL CHECK (sequence_version > 0),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'active', 'paused', 'replied', 'completed', 'suppressed')),
  next_step integer CHECK (next_step BETWEEN 0 AND 2),
  next_due_at timestamptz,
  stop_reason text,
  takeover_at timestamptz,
  UNIQUE (business_id, id),
  UNIQUE (business_id, campaign_id, prospect_id),
  UNIQUE (business_id, campaign_id, prospect_id, id),
  UNIQUE (business_id, campaign_id, sequence_version, id),
  FOREIGN KEY (business_id, prospect_id) REFERENCES public.outreach_prospects (business_id, id),
  FOREIGN KEY (business_id, campaign_id) REFERENCES public.outreach_campaigns (business_id, id)
);

REVOKE ALL ON public.outreach_enrolments FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_enrolments ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  prospect_id uuid NOT NULL,
  campaign_id uuid,
  enrolment_id uuid,
  step_id uuid,
  sequence_version integer, -- internal binding, derived from enrolment by trigger
  mailbox_id uuid,
  batch_review_id uuid,
  action_id uuid,
  outbox_id uuid,
  kind text NOT NULL CHECK (kind IN ('initial', 'followup', 'bespoke', 'imported')),
  origin text NOT NULL CHECK (origin IN ('live', 'import')),
  direction text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
  to_emails text[] NOT NULL,
  cc_emails text[] NOT NULL,
  subject text NOT NULL,
  body text NOT NULL,
  payload_hash text NOT NULL,
  payload_version integer NOT NULL CHECK (payload_version > 0),
  state text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft', 'proposed', 'claimed', 'accepted', 'failed', 'unknown', 'cancelled', 'imported')),
  provider text,
  provider_message_id text,
  provider_thread_id text,
  rfc_message_id text,
  reply_target_id uuid,
  accepted_at timestamptz,
  idempotency_key text NOT NULL,
  retry_of uuid,
  authority_snapshot jsonb NOT NULL CHECK (jsonb_typeof(authority_snapshot) = 'object' AND octet_length(authority_snapshot::text) <= 16384),
  UNIQUE (business_id, id),
  UNIQUE (business_id, idempotency_key),
  UNIQUE (business_id, mailbox_id, id),
  UNIQUE (business_id, prospect_id, mailbox_id, id),
  UNIQUE (business_id, enrolment_id, step_id, id),
  UNIQUE (business_id, action_id, id),
  FOREIGN KEY (business_id, prospect_id) REFERENCES public.outreach_prospects (business_id, id),
  FOREIGN KEY (business_id, campaign_id) REFERENCES public.outreach_campaigns (business_id, id),
  FOREIGN KEY (business_id, enrolment_id) REFERENCES public.outreach_enrolments (business_id, id),
  FOREIGN KEY (business_id, step_id) REFERENCES public.outreach_sequence_steps (business_id, id),
  FOREIGN KEY (business_id, mailbox_id) REFERENCES public.email_accounts (business_id, id),
  FOREIGN KEY (business_id, action_id) REFERENCES public.aria_actions (business_id, id),
  FOREIGN KEY (business_id, outbox_id) REFERENCES public.email_outbox (business_id, id),
  FOREIGN KEY (business_id, batch_review_id) REFERENCES public.outreach_batch_reviews (business_id, id),
  FOREIGN KEY (business_id, retry_of) REFERENCES public.outreach_messages (business_id, id),
  FOREIGN KEY (business_id, reply_target_id) REFERENCES public.outreach_messages (business_id, id),
  FOREIGN KEY (business_id, mailbox_id, campaign_id) REFERENCES public.outreach_campaigns (business_id, mailbox_id, id),
  FOREIGN KEY (business_id, campaign_id, prospect_id, enrolment_id) REFERENCES public.outreach_enrolments (business_id, campaign_id, prospect_id, id),
  FOREIGN KEY (business_id, campaign_id, step_id) REFERENCES public.outreach_sequence_steps (business_id, campaign_id, id),
  FOREIGN KEY (business_id, campaign_id, mailbox_id, batch_review_id) REFERENCES public.outreach_batch_reviews (business_id, campaign_id, mailbox_id, id),
  FOREIGN KEY (business_id, mailbox_id, outbox_id) REFERENCES public.email_outbox (business_id, email_account_id, id),
  CHECK (origin <> 'live' OR direction <> 'outbound' OR state NOT IN ('claimed','accepted','unknown') OR (mailbox_id IS NOT NULL AND action_id IS NOT NULL)),
  FOREIGN KEY (business_id, campaign_id, sequence_version, enrolment_id)
    REFERENCES public.outreach_enrolments (business_id, campaign_id, sequence_version, id),
  FOREIGN KEY (business_id, campaign_id, sequence_version, step_id)
    REFERENCES public.outreach_sequence_steps (business_id, campaign_id, sequence_version, id),
  CHECK ((enrolment_id IS NULL) = (sequence_version IS NULL)),
  CHECK (enrolment_id IS NULL OR campaign_id IS NOT NULL),
  CHECK (step_id IS NULL OR (enrolment_id IS NOT NULL AND campaign_id IS NOT NULL)),
  CHECK (batch_review_id IS NULL OR (campaign_id IS NOT NULL AND mailbox_id IS NOT NULL)),
  CHECK (outbox_id IS NULL OR mailbox_id IS NOT NULL)
);

REVOKE ALL ON public.outreach_messages FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_messages ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_replies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  prospect_id uuid NOT NULL,
  mailbox_id uuid NOT NULL,
  inbound_email_id uuid NOT NULL,
  matched_message_id uuid,
  category text CHECK (category IN ('interested', 'question', 'not_now', 'unsubscribe', 'objection', 'out_of_office', 'wrong_person', 'referral', 'unknown', 'bounce', 'complaint', 'self')),
  confidence numeric CHECK (confidence BETWEEN 0 AND 100),
  classification_version integer CHECK (classification_version > 0),
  knowledge_refs jsonb NOT NULL CHECK (jsonb_typeof(knowledge_refs) = 'array' AND octet_length(knowledge_refs::text) <= 16384),
  suggested_body text,
  owner_id uuid,
  resolution text NOT NULL DEFAULT 'pending' CHECK (resolution IN ('pending', 'handed_over', 'resolved', 'dismissed')),
  received_at timestamptz NOT NULL,
  UNIQUE (business_id, id),
  UNIQUE (business_id, inbound_email_id),
  FOREIGN KEY (business_id, prospect_id) REFERENCES public.outreach_prospects (business_id, id),
  FOREIGN KEY (business_id, mailbox_id) REFERENCES public.email_accounts (business_id, id),
  FOREIGN KEY (business_id, mailbox_id, inbound_email_id) REFERENCES public.email_messages (business_id, email_account_id, id),
  FOREIGN KEY (business_id, prospect_id, mailbox_id, matched_message_id) REFERENCES public.outreach_messages (business_id, prospect_id, mailbox_id, id)
);

REVOKE ALL ON public.outreach_replies FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_replies ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_suppressions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  key_type text NOT NULL CHECK (key_type IN ('email', 'domain')),
  key_digest text NOT NULL,
  digest_version integer NOT NULL CHECK (digest_version > 0),
  reason text NOT NULL,
  source_ref text,
  suppressed_at timestamptz NOT NULL,
  review_at timestamptz,
  UNIQUE (business_id, id),
  UNIQUE (business_id, key_type, digest_version, key_digest)
);

REVOKE ALL ON public.outreach_suppressions FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_suppressions ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_unsubscribe_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  token_digest text NOT NULL UNIQUE,
  prospect_key_digest text NOT NULL,
  digest_version integer NOT NULL CHECK (digest_version > 0),
  issued_at timestamptz NOT NULL,
  revoked_at timestamptz,
  UNIQUE (business_id, id)
);

REVOKE ALL ON public.outreach_unsubscribe_tokens FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_unsubscribe_tokens ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_dispatch_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  message_id uuid NOT NULL,
  enrolment_id uuid,
  step_id uuid,
  logical_key text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'completed', 'failed', 'unknown', 'cancelled')),
  due_at timestamptz NOT NULL,
  lease_owner text,
  lease_until timestamptz,
  action_id uuid,
  dispatch_started_at timestamptz,
  UNIQUE (business_id, id),
  UNIQUE (business_id, logical_key),
  UNIQUE (business_id, message_id),
  FOREIGN KEY (business_id, message_id) REFERENCES public.outreach_messages (business_id, id),
  FOREIGN KEY (business_id, enrolment_id) REFERENCES public.outreach_enrolments (business_id, id),
  FOREIGN KEY (business_id, step_id) REFERENCES public.outreach_sequence_steps (business_id, id),
  FOREIGN KEY (business_id, action_id) REFERENCES public.aria_actions (business_id, id),
  FOREIGN KEY (business_id, action_id, message_id) REFERENCES public.outreach_messages (business_id, action_id, id),
  FOREIGN KEY (business_id, enrolment_id, step_id, message_id) REFERENCES public.outreach_messages (business_id, enrolment_id, step_id, id),
  CHECK ((enrolment_id IS NULL) = (step_id IS NULL))
);

REVOKE ALL ON public.outreach_dispatch_jobs FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_dispatch_jobs ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_daily_usage (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  scope_type text NOT NULL CHECK (scope_type IN ('business', 'mailbox')),
  scope_id uuid NOT NULL,
  local_date date NOT NULL,
  reserved integer NOT NULL DEFAULT 0 CHECK (reserved >= 0),
  accepted integer NOT NULL DEFAULT 0 CHECK (accepted >= 0),
  unknown integer NOT NULL DEFAULT 0 CHECK (unknown >= 0),
  scope_mailbox_id uuid GENERATED ALWAYS AS (CASE WHEN scope_type = 'mailbox' THEN scope_id END) STORED,
  UNIQUE (business_id, id),
  UNIQUE (business_id, scope_type, scope_id, local_date),
  CHECK (scope_type <> 'business' OR scope_id = business_id),
  FOREIGN KEY (business_id, scope_mailbox_id) REFERENCES public.email_accounts (business_id, id)
);

REVOKE ALL ON public.outreach_daily_usage FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_daily_usage ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_usage_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  operation_key text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('outreach_prospects_researched', 'outreach_emails_sent')),
  quantity integer NOT NULL CHECK (quantity >= 0),
  state text NOT NULL CHECK (state IN ('reserved', 'committed', 'released', 'unknown')),
  period_start timestamptz NOT NULL,
  period_end timestamptz NOT NULL,
  mailbox_id uuid,
  local_send_date date,
  message_id uuid,
  cost numeric(18,6) CHECK (cost >= 0),
  currency text,
  UNIQUE (business_id, id),
  UNIQUE (business_id, operation_key, kind),
  CHECK (period_end > period_start),
  FOREIGN KEY (business_id, mailbox_id) REFERENCES public.email_accounts (business_id, id),
  FOREIGN KEY (business_id, message_id) REFERENCES public.outreach_messages (business_id, id),
  FOREIGN KEY (business_id, mailbox_id, message_id) REFERENCES public.outreach_messages (business_id, mailbox_id, id)
);

REVOKE ALL ON public.outreach_usage_events FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_usage_events ENABLE ROW LEVEL SECURITY;

CREATE UNIQUE INDEX IF NOT EXISTS outreach_prospects_email_key_idx
  ON public.outreach_prospects (business_id, email_key) WHERE email_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS outreach_enrolments_live_prospect_idx
  ON public.outreach_enrolments (business_id, prospect_id) WHERE state IN ('pending','active');

CREATE UNIQUE INDEX IF NOT EXISTS outreach_messages_action_idx
  ON public.outreach_messages (business_id, action_id) WHERE action_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS outreach_messages_provider_idx
  ON public.outreach_messages (business_id, mailbox_id, provider_message_id) WHERE provider_message_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS outreach_dispatch_jobs_live_step_idx
  ON public.outreach_dispatch_jobs (business_id, enrolment_id, step_id) WHERE enrolment_id IS NOT NULL AND step_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS outreach_mailboxes_health_idx
  ON public.outreach_mailboxes (business_id, health_status);

CREATE INDEX IF NOT EXISTS outreach_campaigns_status_idx
  ON public.outreach_campaigns (business_id, status);

CREATE INDEX IF NOT EXISTS outreach_prospects_stage_idx
  ON public.outreach_prospects (business_id, stage);

CREATE INDEX IF NOT EXISTS outreach_prospects_retention_idx
  ON public.outreach_prospects (business_id, retention_due_at);

CREATE INDEX IF NOT EXISTS outreach_evidence_prospect_idx
  ON public.outreach_evidence (business_id, prospect_id, fetched_at);

CREATE INDEX IF NOT EXISTS outreach_evidence_expiry_idx
  ON public.outreach_evidence (business_id, expires_at);

CREATE INDEX IF NOT EXISTS outreach_enrolments_due_idx
  ON public.outreach_enrolments (business_id, state, next_due_at);

CREATE INDEX IF NOT EXISTS outreach_messages_thread_idx
  ON public.outreach_messages (business_id, mailbox_id, provider_thread_id);

CREATE INDEX IF NOT EXISTS outreach_messages_prospect_idx
  ON public.outreach_messages (business_id, prospect_id, created_at);

CREATE INDEX IF NOT EXISTS outreach_replies_resolution_idx
  ON public.outreach_replies (business_id, mailbox_id, resolution, received_at);

CREATE INDEX IF NOT EXISTS outreach_dispatch_jobs_due_idx
  ON public.outreach_dispatch_jobs (business_id, status, due_at);

CREATE INDEX IF NOT EXISTS outreach_usage_events_period_idx
  ON public.outreach_usage_events (business_id, period_start, state);

CREATE INDEX IF NOT EXISTS outreach_usage_events_mailbox_idx
  ON public.outreach_usage_events (business_id, mailbox_id, local_send_date);


-- Internal version binding avoids an unenforced enrolment/step version pair.
-- Invoker rights: this grants no read/write authority to browser callers.
CREATE OR REPLACE FUNCTION public.outreach_bind_message_version()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF NEW.enrolment_id IS NULL THEN
    NEW.sequence_version := NULL;
  ELSE
    SELECT e.sequence_version INTO NEW.sequence_version
      FROM public.outreach_enrolments e
      WHERE e.business_id = NEW.business_id AND e.id = NEW.enrolment_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Enrolment not in business' USING ERRCODE = '23503';
    END IF;
  END IF;
  RETURN NEW;
END;
$fn$;
REVOKE ALL ON FUNCTION public.outreach_bind_message_version() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS outreach_message_version ON public.outreach_messages;
CREATE TRIGGER outreach_message_version BEFORE INSERT OR UPDATE ON public.outreach_messages
  FOR EACH ROW EXECUTE FUNCTION public.outreach_bind_message_version();

-- Referencing message/review FKs already prevent changing a campaign mailbox
-- while history exists (including drafts); there is no ON UPDATE CASCADE.
-- An approved sequence version is immutable: create a new version to edit it.
CREATE OR REPLACE FUNCTION public.outreach_freeze_approved_step()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF (OLD.approved_at IS NOT NULL OR OLD.approved_by IS NOT NULL)
     AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
    RAISE EXCEPTION 'Approved sequence version is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$fn$;
REVOKE ALL ON FUNCTION public.outreach_freeze_approved_step() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS outreach_approved_step_immutable ON public.outreach_sequence_steps;
CREATE TRIGGER outreach_approved_step_immutable BEFORE UPDATE ON public.outreach_sequence_steps
  FOR EACH ROW EXECUTE FUNCTION public.outreach_freeze_approved_step();

-- Re-paste also clears column-level client grants (table REVOKE alone does not).
-- Effective inherited grants are checked below: abort rather than alter shared roles.
DO $columns$
DECLARE t text; c text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['outreach_brands', 'outreach_settings', 'outreach_mailboxes', 'outreach_compliance', 'outreach_prospects', 'outreach_evidence', 'outreach_campaigns', 'outreach_batch_reviews', 'outreach_sequence_steps', 'outreach_enrolments', 'outreach_messages', 'outreach_replies', 'outreach_suppressions', 'outreach_unsubscribe_tokens', 'outreach_dispatch_jobs', 'outreach_daily_usage', 'outreach_usage_events']) LOOP
    SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO c
      FROM pg_attribute WHERE attrelid = ('public.' || t)::regclass
        AND attnum > 0 AND NOT attisdropped;
    EXECUTE format('REVOKE SELECT (%s), INSERT (%s), UPDATE (%s), REFERENCES (%s) ON public.%I FROM PUBLIC, anon, authenticated', c,c,c,c,t);
  END LOOP;
END;
$columns$;

DROP POLICY IF EXISTS outreach_brands_member_read ON public.outreach_brands;
CREATE POLICY outreach_brands_member_read ON public.outreach_brands
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), business_id));
GRANT SELECT ON public.outreach_brands TO authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_brands TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_settings TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_mailboxes TO service_role;

DROP POLICY IF EXISTS outreach_compliance_member_read ON public.outreach_compliance;
CREATE POLICY outreach_compliance_member_read ON public.outreach_compliance
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), business_id));
GRANT SELECT ON public.outreach_compliance TO authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_compliance TO service_role;

DROP POLICY IF EXISTS outreach_prospects_member_read ON public.outreach_prospects;
CREATE POLICY outreach_prospects_member_read ON public.outreach_prospects
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), business_id));
GRANT SELECT ON public.outreach_prospects TO authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_prospects TO service_role;

DROP POLICY IF EXISTS outreach_evidence_member_read ON public.outreach_evidence;
CREATE POLICY outreach_evidence_member_read ON public.outreach_evidence
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), business_id));
GRANT SELECT ON public.outreach_evidence TO authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_evidence TO service_role;

DROP POLICY IF EXISTS outreach_campaigns_member_read ON public.outreach_campaigns;
CREATE POLICY outreach_campaigns_member_read ON public.outreach_campaigns
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), business_id));
GRANT SELECT ON public.outreach_campaigns TO authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_campaigns TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_batch_reviews TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_sequence_steps TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_enrolments TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_messages TO service_role;

DROP POLICY IF EXISTS outreach_replies_member_read ON public.outreach_replies;
CREATE POLICY outreach_replies_member_read ON public.outreach_replies
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), business_id));
GRANT SELECT ON public.outreach_replies TO authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_replies TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_suppressions TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_unsubscribe_tokens TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_dispatch_jobs TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_daily_usage TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_usage_events TO service_role;


-- Abort on inherited client access; never weaken the deployment's shared roles.
DO $grants$
DECLARE t text; r text; p text; allowed boolean; actual boolean;
BEGIN
  FOR t IN SELECT unnest(ARRAY['outreach_brands', 'outreach_settings', 'outreach_mailboxes', 'outreach_compliance', 'outreach_prospects', 'outreach_evidence', 'outreach_campaigns', 'outreach_batch_reviews', 'outreach_sequence_steps', 'outreach_enrolments', 'outreach_messages', 'outreach_replies', 'outreach_suppressions', 'outreach_unsubscribe_tokens', 'outreach_dispatch_jobs', 'outreach_daily_usage', 'outreach_usage_events']) LOOP
    IF has_table_privilege('service_role', 'public.' || t, 'TRUNCATE') THEN
      RAISE EXCEPTION 'Unexpected effective service TRUNCATE grant on %', t;
    END IF;
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
      FOREACH p IN ARRAY ARRAY['SELECT','INSERT','UPDATE','REFERENCES','DELETE','TRUNCATE','TRIGGER'] LOOP
        allowed := r = 'authenticated' AND p = 'SELECT' AND t = ANY (ARRAY[
          'outreach_brands','outreach_campaigns','outreach_prospects',
          'outreach_evidence','outreach_compliance','outreach_replies']);
        IF p IN ('SELECT','INSERT','UPDATE','REFERENCES') THEN
          actual := has_any_column_privilege(r, 'public.' || t, p);
        ELSE
          actual := has_table_privilege(r, 'public.' || t, p);
        END IF;
        IF actual IS DISTINCT FROM allowed THEN
          RAISE EXCEPTION 'Unexpected effective grant: % % %', r,t,p;
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
END;
$grants$;
COMMIT;

-- SECTION 3 — READ-ONLY DEFAULT-ACCOUNT AUDIT. Archive the whole result.
-- No recency selection, no automated cleanup, no newest-account fallback.
-- gate = 'BLOCKS': two or more defaults. The Section 4 index would fail;
--   Mike chooses which account stays default, as a separate approved step.
-- gate = 'info': connected mailboxes but none marked default. Not a blocker
--   (the index allows at most one); AUTO-2 already stands down for such a
--   business ("no_default_mailbox") until the owner picks one.
-- Businesses with no mailbox at all are not listed: nothing to decide.
-- (Gate narrowed by Claude's review, 20 Oct 2026: the index enforces AT MOST
-- one default, so only two-or-more can make it fail.)
SELECT b.id AS business_id,
       count(e.id) AS account_count,
       count(e.id) FILTER (WHERE e.is_default IS TRUE) AS default_count,
       coalesce(array_agg(e.id ORDER BY e.id)
                FILTER (WHERE e.is_default IS TRUE), '{}'::uuid[]) AS default_account_ids,
       CASE WHEN count(e.id) FILTER (WHERE e.is_default IS TRUE) > 1 THEN 'BLOCKS'
            ELSE 'info' END AS gate
FROM public.businesses AS b
JOIN public.email_accounts AS e ON e.business_id = b.id
GROUP BY b.id
HAVING count(e.id) FILTER (WHERE e.is_default IS TRUE) <> 1
ORDER BY gate, b.id;

-- SECTION 4 — DEFAULT INDEX: SEPARATE APPROVAL/GATE, OUTSIDE TRANSACTION.
-- Run ONLY when SECTION 3 returns no row with gate = 'BLOCKS'.
-- Never invent or select a default account to clear the gate.
-- The index enforces AT MOST one, not exactly one. Later zero defaults fail closed.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS email_accounts_one_default_idx
  ON public.email_accounts (business_id) WHERE is_default IS TRUE;
