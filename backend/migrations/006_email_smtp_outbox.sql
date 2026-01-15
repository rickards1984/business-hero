-- Migration: Create email_connections and email_outbox tables for SMTP email sending
-- Date: 2024-12-XX
-- Description: SMTP configuration and email outbox for invoice chasing emails

-- Email Connections Table (1 row per business)
CREATE TABLE IF NOT EXISTS email_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'smtp',
    smtp_host TEXT NOT NULL,
    smtp_port INTEGER NOT NULL,
    smtp_username TEXT NOT NULL,
    smtp_password_encrypted TEXT NOT NULL,
    from_email TEXT NOT NULL,
    from_name TEXT,
    use_tls BOOLEAN NOT NULL DEFAULT true,
    use_ssl BOOLEAN NOT NULL DEFAULT false,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(business_id)
);

CREATE INDEX IF NOT EXISTS idx_email_connections_business_id ON email_connections(business_id);
CREATE INDEX IF NOT EXISTS idx_email_connections_enabled ON email_connections(is_enabled) WHERE is_enabled = true;

-- Email Outbox Table (tracks email sends)
CREATE TABLE IF NOT EXISTS email_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    chase_stage INTEGER,
    status TEXT NOT NULL DEFAULT 'queued',
    error_message TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for email_outbox
CREATE INDEX IF NOT EXISTS idx_email_outbox_business_created ON email_outbox(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_outbox_invoice_id ON email_outbox(invoice_id);
CREATE INDEX IF NOT EXISTS idx_email_outbox_status ON email_outbox(status);
CREATE INDEX IF NOT EXISTS idx_email_outbox_business_id ON email_outbox(business_id);

-- Trigger for updated_at timestamp on email_connections
-- Note: update_updated_at_column() function is already created in migration 001
CREATE TRIGGER update_email_connections_updated_at BEFORE UPDATE ON email_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Enable RLS
ALTER TABLE email_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_outbox ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- EMAIL_CONNECTIONS RLS POLICIES
-- ============================================================================
-- Note: Helper functions is_platform_admin() and is_business_member() are 
-- already created in migration 002

-- Platform admins: full access (SELECT, INSERT, UPDATE, DELETE)
CREATE POLICY "platform_admins_full_access_email_connections"
    ON email_connections
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

-- Business members: read and write only for their business
CREATE POLICY "business_members_read_email_connections"
    ON email_connections
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_insert_email_connections"
    ON email_connections
    FOR INSERT
    TO authenticated
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_update_email_connections"
    ON email_connections
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

CREATE POLICY "business_members_delete_email_connections"
    ON email_connections
    FOR DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

-- ============================================================================
-- EMAIL_OUTBOX RLS POLICIES
-- ============================================================================

-- Platform admins: full access (SELECT, INSERT, UPDATE, DELETE)
CREATE POLICY "platform_admins_full_access_email_outbox"
    ON email_outbox
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

-- Business members: read and write only for their business
CREATE POLICY "business_members_read_email_outbox"
    ON email_outbox
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_insert_email_outbox"
    ON email_outbox
    FOR INSERT
    TO authenticated
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_update_email_outbox"
    ON email_outbox
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

CREATE POLICY "business_members_delete_email_outbox"
    ON email_outbox
    FOR DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );
