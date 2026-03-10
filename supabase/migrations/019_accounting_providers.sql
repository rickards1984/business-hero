-- ============================================================
-- Migration 019: Multi-Provider Accounting Abstraction
-- Adds accounting_providers reference table and accounting_connections
-- generic connection table.  Migrates existing Xero data across so both
-- tables stay in sync.
-- ============================================================

-- 1. Reference table of supported providers
CREATE TABLE IF NOT EXISTS accounting_providers (
    id          TEXT PRIMARY KEY,           -- 'xero', 'freeagent', 'quickbooks'
    name        TEXT NOT NULL,
    description TEXT,
    logo_url    TEXT,
    is_available BOOLEAN DEFAULT FALSE,
    features    JSONB DEFAULT '[]'::jsonb,
    sort_order  INT DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO accounting_providers (id, name, description, is_available, features, sort_order) VALUES
    ('xero',       'Xero',       'Cloud accounting for small business. Bank feeds, invoicing, payroll and more.', TRUE,
     '["bank_transactions","invoices","contacts","profit_loss","balance_sheet","aged_receivables","aged_payables"]'::jsonb, 1),
    ('freeagent',  'FreeAgent',  'Accounting software for freelancers and micro-businesses. Loved by UK contractors.', FALSE,
     '["bank_transactions","invoices","contacts","profit_loss"]'::jsonb, 2),
    ('quickbooks', 'QuickBooks', 'Intuit QuickBooks — popular worldwide for small and mid-sized businesses.', FALSE,
     '["bank_transactions","invoices","contacts","profit_loss","balance_sheet"]'::jsonb, 3)
ON CONFLICT (id) DO NOTHING;

-- 2. Generic accounting connection table (one active connection per business)
CREATE TABLE IF NOT EXISTS accounting_connections (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id               UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    provider                  TEXT NOT NULL REFERENCES accounting_providers(id),
    tenant_id                 TEXT,
    tenant_name               TEXT,
    token_ciphertext          TEXT NOT NULL,
    refresh_token_ciphertext  TEXT NOT NULL,
    token_expires_at          TIMESTAMPTZ NOT NULL,
    last_sync_at              TIMESTAMPTZ,
    sync_cursor               TEXT,
    is_active                 BOOLEAN DEFAULT TRUE,
    provider_metadata         JSONB DEFAULT '{}'::jsonb,
    created_at                TIMESTAMPTZ DEFAULT NOW(),
    updated_at                TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(business_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_acct_connections_business
    ON accounting_connections(business_id);

CREATE INDEX IF NOT EXISTS idx_acct_connections_provider
    ON accounting_connections(provider);

-- 3. Add provider column to accounting_transactions if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'accounting_transactions' AND column_name = 'provider'
    ) THEN
        ALTER TABLE accounting_transactions ADD COLUMN provider TEXT DEFAULT 'xero';
    END IF;
END $$;

-- 4. Add provider column to invoices if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'invoices' AND column_name = 'provider'
    ) THEN
        ALTER TABLE invoices ADD COLUMN provider TEXT;
    END IF;
END $$;

-- 5. Migrate existing Xero connections into accounting_connections
INSERT INTO accounting_connections (
    business_id, provider, tenant_id, tenant_name,
    token_ciphertext, refresh_token_ciphertext,
    token_expires_at, last_sync_at, sync_cursor,
    is_active, created_at, updated_at
)
SELECT
    business_id, 'xero', tenant_id, tenant_name,
    token_ciphertext, refresh_token_ciphertext,
    token_expires_at, last_sync_at, sync_cursor,
    is_active, created_at, updated_at
FROM xero_connections
ON CONFLICT (business_id, provider) DO NOTHING;

-- 6. RLS
ALTER TABLE accounting_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounting_connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY accounting_providers_read ON accounting_providers
    FOR SELECT USING (true);

CREATE POLICY accounting_connections_service ON accounting_connections
    FOR ALL USING (true) WITH CHECK (true);
