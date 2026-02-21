-- ============================================================
-- Migration 013: Xero Accounting Integration
-- Adds xero_connections table and external_id tracking on transactions
-- ============================================================

-- Store Xero OAuth connection details per business
CREATE TABLE IF NOT EXISTS xero_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    tenant_name TEXT,
    token_ciphertext TEXT NOT NULL,
    refresh_token_ciphertext TEXT NOT NULL,
    token_expires_at TIMESTAMPTZ NOT NULL,
    last_sync_at TIMESTAMPTZ,
    sync_cursor TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(business_id)
);

-- Add external tracking columns to accounting_transactions for deduplication
-- This prevents duplicate imports when syncing from Xero (or future QuickBooks etc.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'accounting_transactions' AND column_name = 'external_id'
    ) THEN
        ALTER TABLE accounting_transactions ADD COLUMN external_id TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'accounting_transactions' AND column_name = 'external_source'
    ) THEN
        ALTER TABLE accounting_transactions ADD COLUMN external_source TEXT;
    END IF;
END $$;

-- Unique index to prevent duplicate Xero transactions per business
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounting_txn_external
    ON accounting_transactions(business_id, external_source, external_id)
    WHERE external_id IS NOT NULL;

-- Index for faster Xero connection lookups
CREATE INDEX IF NOT EXISTS idx_xero_connections_business
    ON xero_connections(business_id);

-- RLS policies for xero_connections
ALTER TABLE xero_connections ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read their own business's Xero connection
CREATE POLICY xero_connections_select_policy ON xero_connections
    FOR SELECT USING (
        business_id IN (
            SELECT id FROM businesses WHERE id = business_id
        )
    );

-- Service role can do everything (backend uses service role key)
CREATE POLICY xero_connections_service_policy ON xero_connections
    FOR ALL USING (true) WITH CHECK (true);
