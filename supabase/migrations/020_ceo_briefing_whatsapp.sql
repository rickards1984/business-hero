-- ============================================================
-- Migration 020: CEO Briefing & WhatsApp Automation Tables
-- WhatsApp messaging, briefing snapshots, pending actions
-- ============================================================

-- 1. WhatsApp configs (per-business)
CREATE TABLE IF NOT EXISTS whatsapp_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
    phone_number TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    timezone TEXT NOT NULL DEFAULT 'Europe/London',
    owner_name TEXT,
    daily_pulse_enabled BOOLEAN NOT NULL DEFAULT false,
    daily_pulse_time TEXT NOT NULL DEFAULT '07:30',
    weekly_briefing_enabled BOOLEAN NOT NULL DEFAULT false,
    weekly_briefing_day TEXT NOT NULL DEFAULT 'monday',
    weekly_briefing_time TEXT NOT NULL DEFAULT '08:00',
    preferred_detail_level TEXT NOT NULL DEFAULT 'standard',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_configs_business ON whatsapp_configs(business_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_configs_enabled ON whatsapp_configs(enabled) WHERE enabled = true;

-- 2. WhatsApp messages audit log
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    direction TEXT NOT NULL DEFAULT 'outbound',
    message_type TEXT NOT NULL DEFAULT 'notification',
    phone_number TEXT NOT NULL,
    content TEXT,
    twilio_message_sid TEXT,
    twilio_status TEXT,
    related_entity_type TEXT,
    related_entity_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_business ON whatsapp_messages(business_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_created ON whatsapp_messages(created_at DESC);

-- 3. Briefing snapshots (historical metrics for trend comparison)
CREATE TABLE IF NOT EXISTS briefing_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    snapshot_type TEXT NOT NULL DEFAULT 'daily',
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    revenue NUMERIC(14,2) DEFAULT 0,
    expenses NUMERIC(14,2) DEFAULT 0,
    net_profit NUMERIC(14,2) DEFAULT 0,
    calls_total INTEGER DEFAULT 0,
    calls_handled_by_ai INTEGER DEFAULT 0,
    emails_received INTEGER DEFAULT 0,
    emails_action_required INTEGER DEFAULT 0,
    tasks_created INTEGER DEFAULT 0,
    tasks_completed INTEGER DEFAULT 0,
    invoices_overdue_count INTEGER DEFAULT 0,
    invoices_overdue_amount NUMERIC(14,2) DEFAULT 0,
    ai_summary TEXT,
    ai_observations JSONB,
    ai_suggestions JSONB,
    full_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_briefing_snapshots_business ON briefing_snapshots(business_id);
CREATE INDEX IF NOT EXISTS idx_briefing_snapshots_period ON briefing_snapshots(business_id, period_start, period_end);

-- 4. Pending actions for two-way WhatsApp interaction
CREATE TABLE IF NOT EXISTS whatsapp_pending_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    source_message_id UUID REFERENCES whatsapp_messages(id) ON DELETE SET NULL,
    action_number INTEGER NOT NULL,
    action_label TEXT,
    action_type TEXT,
    action_config JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_pending_actions_business ON whatsapp_pending_actions(business_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_pending_actions_source ON whatsapp_pending_actions(source_message_id);
