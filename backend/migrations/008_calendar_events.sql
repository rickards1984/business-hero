-- Migration: Add calendar events cache and sync state
-- Date: 2026-01-15
-- Description: Calendar events cache tied to email_accounts with RLS

-- ============================================================================
-- CALENDAR_EVENTS (cached)
-- ============================================================================
CREATE TABLE calendar_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    email_account_id UUID NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    provider_event_id TEXT NOT NULL,
    subject TEXT,
    description TEXT,
    location TEXT,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    is_all_day BOOLEAN NOT NULL DEFAULT false,
    organizer_email TEXT,
    attendees JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT,
    show_as TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (email_account_id, provider_event_id)
);

CREATE INDEX idx_calendar_events_business_start ON calendar_events(business_id, start_at);
CREATE INDEX idx_calendar_events_account_start ON calendar_events(email_account_id, start_at);

-- ============================================================================
-- CALENDAR_SYNC_STATE
-- ============================================================================
CREATE TABLE calendar_sync_state (
    email_account_id UUID PRIMARY KEY REFERENCES email_accounts(id) ON DELETE CASCADE,
    cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- UPDATED_AT TRIGGERS
-- ============================================================================
CREATE TRIGGER update_calendar_events_updated_at BEFORE UPDATE ON calendar_events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_calendar_sync_state_updated_at BEFORE UPDATE ON calendar_sync_state
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- ENABLE RLS
-- ============================================================================
ALTER TABLE calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_sync_state ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- RLS POLICIES: CALENDAR_EVENTS
-- ============================================================================
CREATE POLICY "platform_admins_full_access_calendar_events"
    ON calendar_events
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_calendar_events"
    ON calendar_events
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_write_calendar_events"
    ON calendar_events
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
-- RLS POLICIES: CALENDAR_SYNC_STATE
-- ============================================================================
CREATE POLICY "platform_admins_full_access_calendar_sync_state"
    ON calendar_sync_state
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

CREATE POLICY "business_members_read_calendar_sync_state"
    ON calendar_sync_state
    FOR SELECT
    TO authenticated
    USING (
        is_platform_admin(auth.uid())
        OR EXISTS (
            SELECT 1
            FROM email_accounts ea
            WHERE ea.id = calendar_sync_state.email_account_id
              AND is_business_member(auth.uid(), ea.business_id)
        )
    );

CREATE POLICY "business_members_write_calendar_sync_state"
    ON calendar_sync_state
    FOR INSERT, UPDATE, DELETE
    TO authenticated
    USING (
        is_platform_admin(auth.uid())
        OR EXISTS (
            SELECT 1
            FROM email_accounts ea
            WHERE ea.id = calendar_sync_state.email_account_id
              AND is_business_member(auth.uid(), ea.business_id)
        )
    )
    WITH CHECK (
        is_platform_admin(auth.uid())
        OR EXISTS (
            SELECT 1
            FROM email_accounts ea
            WHERE ea.id = calendar_sync_state.email_account_id
              AND is_business_member(auth.uid(), ea.business_id)
        )
    );
