-- Add external tracking columns to invoices table for Xero sync
-- These allow deduplication when syncing invoices from Xero

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invoices' AND column_name = 'external_id') THEN
        ALTER TABLE invoices ADD COLUMN external_id TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invoices' AND column_name = 'external_source') THEN
        ALTER TABLE invoices ADD COLUMN external_source TEXT DEFAULT NULL;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invoices' AND column_name = 'amount_due') THEN
        ALTER TABLE invoices ADD COLUMN amount_due NUMERIC(12,2) DEFAULT NULL;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invoices' AND column_name = 'amount_paid') THEN
        ALTER TABLE invoices ADD COLUMN amount_paid NUMERIC(12,2) DEFAULT 0;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invoices' AND column_name = 'invoice_type') THEN
        ALTER TABLE invoices ADD COLUMN invoice_type TEXT DEFAULT 'ACCREC';
    END IF;
END $$;

-- Unique index for deduplication: one row per (business, source, external_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_external_unique
ON invoices (business_id, external_source, external_id)
WHERE external_id IS NOT NULL;
