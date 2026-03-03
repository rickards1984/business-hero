-- AI Receptionist configuration per business
CREATE TABLE IF NOT EXISTS receptionist_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL UNIQUE REFERENCES businesses(id),
    enabled BOOLEAN NOT NULL DEFAULT false,
    twilio_phone_number TEXT,
    twilio_phone_sid TEXT,
    voice TEXT NOT NULL DEFAULT 'shimmer',
    language TEXT NOT NULL DEFAULT 'en-GB',
    personality_prompt TEXT,
    greeting_message TEXT NOT NULL DEFAULT 'Hello, thank you for calling. How can I help you today?',
    tone TEXT NOT NULL DEFAULT 'professional',
    humor_enabled BOOLEAN NOT NULL DEFAULT false,
    speaking_speed TEXT NOT NULL DEFAULT 'normal',
    business_hours JSONB NOT NULL DEFAULT '{}',
    timezone TEXT NOT NULL DEFAULT 'Europe/London',
    after_hours_message TEXT,
    after_hours_action TEXT NOT NULL DEFAULT 'message',
    transfer_enabled BOOLEAN NOT NULL DEFAULT true,
    transfer_number TEXT,
    transfer_trigger_phrases TEXT,
    max_call_duration_seconds INTEGER NOT NULL DEFAULT 300,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Knowledge base items for the AI receptionist
CREATE TABLE IF NOT EXISTS knowledge_base_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id),
    category TEXT NOT NULL DEFAULT 'general',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kb_items_business ON knowledge_base_items (business_id);
CREATE INDEX IF NOT EXISTS idx_kb_items_category ON knowledge_base_items (business_id, category);

-- New columns on calls table for receptionist calls
ALTER TABLE calls ADD COLUMN IF NOT EXISTS duration_seconds INTEGER;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS recording_url TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS outcome TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS receptionist_config_id UUID REFERENCES receptionist_configs(id);

-- Add receptionist feature flag (default false) to all businesses
UPDATE businesses
SET feature_flags = feature_flags || '{"receptionist": false}'::jsonb
WHERE NOT (feature_flags ? 'receptionist');
