-- Migration: Add paid tracking and archived columns to invoices table
-- This enables marking invoices as paid with amount/date and archiving invoices

-- Add paid_amount column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'invoices'
        AND column_name = 'paid_amount'
    ) THEN
        ALTER TABLE invoices ADD COLUMN paid_amount DECIMAL(12,2);
    END IF;
END $$;

-- Add paid_at column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'invoices'
        AND column_name = 'paid_at'
    ) THEN
        ALTER TABLE invoices ADD COLUMN paid_at TIMESTAMPTZ;
    END IF;
END $$;

-- Add archived column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'invoices'
        AND column_name = 'archived'
    ) THEN
        ALTER TABLE invoices ADD COLUMN archived BOOLEAN DEFAULT FALSE NOT NULL;
    END IF;
END $$;

-- Create index for faster filtering by status
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);

-- Create index for faster filtering by archived status
CREATE INDEX IF NOT EXISTS idx_invoices_archived ON invoices(archived);

-- Create composite index for business_id + status + archived filtering
CREATE INDEX IF NOT EXISTS idx_invoices_business_status_archived ON invoices(business_id, status, archived);

-- Update existing invoices to have explicit status if null
UPDATE invoices SET status = 'unpaid' WHERE status IS NULL;

-- Update existing invoices to have archived = false if null
UPDATE invoices SET archived = FALSE WHERE archived IS NULL;
