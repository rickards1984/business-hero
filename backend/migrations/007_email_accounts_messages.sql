-- Migration: Add email account, outbox, message cache, sync state, briefings, drafts
-- Date: 2026-01-15
-- Description: Email account management, audit logging, and sync cache with RLS

-- ============================================================================
-- EMAIL_ACCOUNTS
-- ============================================================================
CREATE TABLE email_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('google', 'microsoft', 'smtp', 'imap')),
    email_address TEXT NOT NULL,
    display_name TEXT,
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_default BOOLEAN NOT NULL DEFAULT false,
    token_ciphertext TEXT,
    refresh_token_ciphertext TEXT,
    token_expires_at TIMESTAMPTZ,
    smtp_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (business_id, email_address, provider)
);

-- ============================================================================
-- EMAIL_OUTBOX (audit log)
-- ============================================================================
CREATE TABLE email_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    email_account_id UUID NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
    chase_stage INTEGER,
    to_emails TEXT[] NOT NULL,
    subject TEXT NOT NULL,
    body_preview TEXT NOT NULL,
    provider_message_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'sent', 'failed')),
    error TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_email_outbox_business_id ON email_outbox(business_id);
CREATE INDEX idx_email_outbox_email_account_id ON email_outbox(email_account_id);
CREATE INDEX idx_email_outbox_invoice_id ON email_outbox(invoice_id);
CREATE INDEX idx_email_outbox_created_at_desc ON email_outbox(created_at DESC);

-- ============================================================================
-- EMAIL_MESSAGES (local cache)
-- ============================================================================
CREATE TABLE email_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    email_account_id UUID NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    provider_message_id TEXT NOT NULL,
    provider_thread_id TEXT,
    folder TEXT NOT NULL DEFAULT 'INBOX',
    from_email TEXT,
    from_name TEXT,
    to_emails TEXT[],
    cc_emails TEXT[],
    subject TEXT,
    snippet TEXT,
    received_at TIMESTAMPTZ,
    is_unread BOOLEAN NOT NULL DEFAULT true,
    has_attachments BOOLEAN NOT NULL DEFAULT false,
    labels TEXT[],
    body_text TEXT,
    body_html TEXT,
    raw_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (email_account_id, provider_message_id)
);

CREATE INDEX idx_email_messages_business_received_desc ON email_messages(business_id, received_at DESC);
CREATE INDEX idx_email_messages_account_received_desc ON email_messages(email_account_id, received_at DESC);
CREATE INDEX idx_email_messages_business_unread ON email_messages(business_id, is_unread);

-- ============================================================================
-- EMAIL_SYNC_STATE
-- ============================================================================
CREATE TABLE email_sync_state (
    email_account_id UUID PRIMARY KEY REFERENCES email_accounts(id) ON DELETE CASCADE,
    cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- EMAIL_BRIEFINGS
-- ============================================================================
CREATE TABLE email_briefings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    email_account_id UUID REFERENCES email_accounts(id) ON DELETE SET NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    briefing_markdown TEXT NOT NULL,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_email_briefings_business_created_desc ON email_briefings(business_id, created_at DESC);
CREATE INDEX idx_email_briefings_user_created_desc ON email_briefings(user_id, created_at DESC);

-- ============================================================================
-- EMAIL_DRAFTS
-- ============================================================================
CREATE TABLE email_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    email_message_id UUID NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
    to_emails TEXT[] NOT NULL,
    subject TEXT NOT NULL,
    body_text TEXT,
    body_html TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'sent', 'discarded')),
    provider_message_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- UPDATED_AT TRIGGERS
-- ============================================================================
CREATE TRIGGER update_email_accounts_updated_at BEFORE UPDATE ON email_accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_email_messages_updated_at BEFORE UPDATE ON email_messages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_email_sync_state_updated_at BEFORE UPDATE ON email_sync_state
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_email_drafts_updated_at BEFORE UPDATE ON email_drafts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- ENABLE RLS
-- ============================================================================
ALTER TABLE email_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_briefings ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_drafts ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- RLS POLICIES: EMAIL_ACCOUNTS
-- ============================================================================
CREATE POLICY "platform_admins_full_access_email_accounts"
    ON email_accounts
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_email_accounts"
    ON email_accounts
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_write_email_accounts"
    ON email_accounts
    FOR INSERT, UPDATE, DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    )
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

-- ============================================================================
-- RLS POLICIES: EMAIL_OUTBOX
-- ============================================================================
CREATE POLICY "platform_admins_full_access_email_outbox_v2"
    ON email_outbox
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_email_outbox_v2"
    ON email_outbox
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_write_email_outbox_v2"
    ON email_outbox
    FOR INSERT, UPDATE, DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    )
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

-- ============================================================================
-- RLS POLICIES: EMAIL_MESSAGES
-- ============================================================================
CREATE POLICY "platform_admins_full_access_email_messages"
    ON email_messages
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_email_messages"
    ON email_messages
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_write_email_messages"
    ON email_messages
    FOR INSERT, UPDATE, DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    )
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

-- ============================================================================
-- RLS POLICIES: EMAIL_SYNC_STATE
-- ============================================================================
CREATE POLICY "platform_admins_full_access_email_sync_state"
    ON email_sync_state
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_email_sync_state"
    ON email_sync_state
    FOR SELECT
    TO authenticated
    USING (
        is_platform_admin(auth.uid())
        OR EXISTS (
            SELECT 1
            FROM email_accounts ea
            WHERE ea.id = email_sync_state.email_account_id
              AND is_business_member(auth.uid(), ea.business_id)
        )
    );

CREATE POLICY "business_members_write_email_sync_state"
    ON email_sync_state
    FOR INSERT, UPDATE, DELETE
    TO authenticated
    USING (
        is_platform_admin(auth.uid())
        OR EXISTS (
            SELECT 1
            FROM email_accounts ea
            WHERE ea.id = email_sync_state.email_account_id
              AND is_business_member(auth.uid(), ea.business_id)
        )
    )
    WITH CHECK (
        is_platform_admin(auth.uid())
        OR EXISTS (
            SELECT 1
            FROM email_accounts ea
            WHERE ea.id = email_sync_state.email_account_id
              AND is_business_member(auth.uid(), ea.business_id)
        )
    );

-- ============================================================================
-- RLS POLICIES: EMAIL_BRIEFINGS
-- ============================================================================
CREATE POLICY "platform_admins_full_access_email_briefings"
    ON email_briefings
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_email_briefings"
    ON email_briefings
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_write_email_briefings"
    ON email_briefings
    FOR INSERT, UPDATE, DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    )
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

-- ============================================================================
-- RLS POLICIES: EMAIL_DRAFTS
-- ============================================================================
CREATE POLICY "platform_admins_full_access_email_drafts"
    ON email_drafts
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_email_drafts"
    ON email_drafts
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_write_email_drafts"
    ON email_drafts
    FOR INSERT, UPDATE, DELETE
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    )
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );
