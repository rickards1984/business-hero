-- Migration: Add archived column to calls table
-- This enables archiving calls without deleting them

-- Add archived column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'calls'
        AND column_name = 'archived'
    ) THEN
        ALTER TABLE calls ADD COLUMN archived BOOLEAN DEFAULT FALSE NOT NULL;
    END IF;
END $$;

-- Add updated_at column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'calls'
        AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE calls ADD COLUMN updated_at TIMESTAMPTZ;
    END IF;
END $$;

-- Create index for faster filtering by archived status
CREATE INDEX IF NOT EXISTS idx_calls_archived ON calls(archived);

-- Create composite index for business_id + archived filtering
CREATE INDEX IF NOT EXISTS idx_calls_business_archived ON calls(business_id, archived);
