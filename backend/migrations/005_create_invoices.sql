-- Migration: Create invoices table for invoice chasing
-- Date: 2024-12-XX
-- Description: Invoice tracking and chasing functionality with RLS

-- Invoices Table
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_email TEXT,
    issue_date DATE,
    due_date DATE NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'GBP',
    status TEXT NOT NULL DEFAULT 'unpaid',
    paid_date DATE,
    last_chased_at TIMESTAMPTZ,
    chase_stage INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'csv',
    source_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_invoices_business_due_date ON invoices(business_id, due_date);
CREATE INDEX IF NOT EXISTS idx_invoices_business_status ON invoices(business_id, status);
CREATE INDEX IF NOT EXISTS idx_invoices_business_id ON invoices(business_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date);

-- Trigger for updated_at timestamp
-- Note: update_updated_at_column() function is already created in migration 001
CREATE TRIGGER update_invoices_updated_at BEFORE UPDATE ON invoices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Enable RLS
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- INVOICES RLS POLICIES
-- ============================================================================
-- Note: Helper functions is_platform_admin() and is_business_member() are 
-- already created in migration 002

-- Platform admins: full access (SELECT, INSERT, UPDATE, DELETE)
CREATE POLICY "platform_admins_full_access_invoices"
    ON invoices
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

-- Business members: read and write only for their business
CREATE POLICY "business_members_read_invoices"
    ON invoices
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_insert_invoices"
    ON invoices
    FOR INSERT
    TO authenticated
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_update_invoices"
    ON invoices
    FOR UPDATE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    )
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_delete_invoices"
    ON invoices
    FOR DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );
