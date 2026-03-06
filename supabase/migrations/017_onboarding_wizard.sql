-- 017: Admin Onboarding Wizard tables + business onboarding columns

-- New columns on businesses for onboarding tracking
ALTER TABLE businesses
  ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS onboarded_by UUID;

-- Plan definitions (seed data below)
CREATE TABLE IF NOT EXISTS plan_definitions (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  description   TEXT,
  monthly_price_gbp NUMERIC(10,2),
  features      JSONB NOT NULL DEFAULT '{}',
  limits        JSONB NOT NULL DEFAULT '{}',
  sort_order    INTEGER NOT NULL DEFAULT 0,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the three plan tiers
INSERT INTO plan_definitions (id, name, description, features, limits, sort_order) VALUES
  ('starter', 'Starter', 'Essential tools to get your business online',
   '{"email": true, "calendar": true, "aria_chat": true, "aria_voice": false, "receptionist": false, "accounting": false}',
   '{"max_emails_per_day": 50, "max_kb_items": 20}',
   1),
  ('pro', 'Pro', 'Everything in Starter plus AI voice, receptionist, and accounting',
   '{"email": true, "calendar": true, "aria_chat": true, "aria_voice": true, "receptionist": true, "accounting": true}',
   '{"max_emails_per_day": 200, "max_kb_items": 100}',
   2),
  ('enterprise', 'Enterprise', 'Full platform access with bespoke features and priority support',
   '{"email": true, "calendar": true, "aria_chat": true, "aria_voice": true, "receptionist": true, "accounting": true}',
   '{"max_emails_per_day": 1000, "max_kb_items": 500}',
   3)
ON CONFLICT (id) DO NOTHING;

-- Onboarding sessions (one per wizard run)
CREATE TABLE IF NOT EXISTS onboarding_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id     UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  started_by      UUID,
  status          TEXT NOT NULL DEFAULT 'in_progress',
  current_step    TEXT NOT NULL DEFAULT 'business_details',
  steps_completed JSONB NOT NULL DEFAULT '{}',
  wizard_data     JSONB NOT NULL DEFAULT '{}',
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at    TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_business
  ON onboarding_sessions (business_id, status);

-- Onboarding checklist (per-business post-onboarding tracker)
CREATE TABLE IF NOT EXISTS onboarding_checklist (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  item_key      TEXT NOT NULL,
  label         TEXT NOT NULL,
  category      TEXT NOT NULL DEFAULT 'setup',
  is_completed  BOOLEAN NOT NULL DEFAULT FALSE,
  completed_at  TIMESTAMPTZ,
  completed_by  TEXT,
  notes         TEXT,
  sort_order    INTEGER NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (business_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_onboarding_checklist_business
  ON onboarding_checklist (business_id);
