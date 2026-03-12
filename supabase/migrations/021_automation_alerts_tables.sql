-- ============================================================
-- Migration 021: Automation Rules, Alert Settings, Pending Action Status
-- Two-way WhatsApp interaction, real-time alerts, automation engine
-- ============================================================

-- 1. Add alert preference columns to whatsapp_configs
ALTER TABLE whatsapp_configs ADD COLUMN IF NOT EXISTS real_time_alerts_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE whatsapp_configs ADD COLUMN IF NOT EXISTS alert_invoice_overdue_days INTEGER DEFAULT 7;
ALTER TABLE whatsapp_configs ADD COLUMN IF NOT EXISTS alert_bank_balance_threshold NUMERIC(14,2);
ALTER TABLE whatsapp_configs ADD COLUMN IF NOT EXISTS alert_urgent_emails BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE whatsapp_configs ADD COLUMN IF NOT EXISTS alert_receptionist_transfers BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE whatsapp_configs ADD COLUMN IF NOT EXISTS alert_payment_received_threshold NUMERIC(14,2) DEFAULT 100;

-- 2. Add status and executed_at to whatsapp_pending_actions
ALTER TABLE whatsapp_pending_actions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE whatsapp_pending_actions ADD COLUMN IF NOT EXISTS executed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_whatsapp_pending_actions_status ON whatsapp_pending_actions(business_id, status) WHERE status = 'pending';

-- 3. Automation rule templates (seed data for default rules)
CREATE TABLE IF NOT EXISTS automation_rule_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    trigger_type TEXT NOT NULL,
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_type TEXT NOT NULL,
    action_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    requires_approval BOOLEAN NOT NULL DEFAULT true,
    is_default BOOLEAN NOT NULL DEFAULT false,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_automation_rule_templates_default ON automation_rule_templates(is_default) WHERE is_default = true;

-- 4. Automation rules (per-business instances)
CREATE TABLE IF NOT EXISTS automation_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    trigger_type TEXT NOT NULL,
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_type TEXT NOT NULL,
    action_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    requires_approval BOOLEAN NOT NULL DEFAULT true,
    is_active BOOLEAN NOT NULL DEFAULT false,
    last_triggered_at TIMESTAMPTZ,
    total_executions INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_automation_rules_business ON automation_rules(business_id);
CREATE INDEX IF NOT EXISTS idx_automation_rules_active ON automation_rules(business_id, is_active) WHERE is_active = true;

-- 5. Automation executions (audit log)
CREATE TABLE IF NOT EXISTS automation_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID NOT NULL REFERENCES automation_rules(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    trigger_data JSONB,
    action_result JSONB,
    executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_automation_executions_business ON automation_executions(business_id);
CREATE INDEX IF NOT EXISTS idx_automation_executions_rule ON automation_executions(rule_id);

-- 6. Seed default automation templates
INSERT INTO automation_rule_templates (name, description, trigger_type, conditions, action_type, action_config, requires_approval, is_default, sort_order)
VALUES
    ('Chase overdue invoices', 'Send chase email when invoices are overdue by 7 days', 'invoice_overdue', '{"days_overdue": 7, "min_amount": 0}'::jsonb, 'send_chase_email', '{"stage": 1}'::jsonb, true, true, 1),
    ('Email action required', 'Alert when unread emails need action', 'email_action_required', '{}'::jsonb, 'send_whatsapp_alert', '{"template": "urgent_email"}'::jsonb, true, true, 2)
ON CONFLICT DO NOTHING;
