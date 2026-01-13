-- Migration: Create RLS policies for business_settings, integrations, oauth_tokens
-- Date: 2024-12-XX
-- Description: Row Level Security policies consistent with business_members logic

-- Enable RLS on all tables
ALTER TABLE business_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;

-- Helper function to check if user is platform admin
CREATE OR REPLACE FUNCTION is_platform_admin(user_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM platform_admins WHERE platform_admins.user_id = is_platform_admin.user_id
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Helper function to check if user is active business member
CREATE OR REPLACE FUNCTION is_business_member(user_id UUID, business_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM business_members 
        WHERE business_members.user_id = is_business_member.user_id
          AND business_members.business_id = is_business_member.business_id
          AND business_members.is_active = true
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- BUSINESS_SETTINGS RLS POLICIES
-- ============================================================================

-- Platform admins: full access (SELECT, INSERT, UPDATE, DELETE)
CREATE POLICY "platform_admins_full_access_business_settings"
    ON business_settings
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

-- Business members: read and update only for their business
CREATE POLICY "business_members_read_business_settings"
    ON business_settings
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_update_business_settings"
    ON business_settings
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

-- Allow business members to insert settings for their business (first-time setup)
CREATE POLICY "business_members_insert_business_settings"
    ON business_settings
    FOR INSERT
    TO authenticated
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

-- ============================================================================
-- INTEGRATIONS RLS POLICIES
-- ============================================================================

-- Platform admins: full access (SELECT, INSERT, UPDATE, DELETE)
CREATE POLICY "platform_admins_full_access_integrations"
    ON integrations
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

-- Business members: read and update only for their business
CREATE POLICY "business_members_read_integrations"
    ON integrations
    FOR SELECT
    TO authenticated
    USING (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

CREATE POLICY "business_members_update_integrations"
    ON integrations
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

-- Allow business members to insert integrations for their business
CREATE POLICY "business_members_insert_integrations"
    ON integrations
    FOR INSERT
    TO authenticated
    WITH CHECK (
        is_business_member(auth.uid(), business_id)
        OR is_platform_admin(auth.uid())
    );

-- ============================================================================
-- OAUTH_TOKENS RLS POLICIES
-- ============================================================================

-- Platform admins: full access (SELECT, INSERT, UPDATE, DELETE)
CREATE POLICY "platform_admins_full_access_oauth_tokens"
    ON oauth_tokens
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

-- Service role (backend): full access - no policy needed, service role bypasses RLS
-- Note: Service role access is handled at the application level, not via RLS
-- Frontend clients (authenticated role) have NO access to oauth_tokens

-- Deny all access to authenticated users (except platform admins above)
-- This ensures only platform admins and service role can access tokens
CREATE POLICY "deny_authenticated_oauth_tokens"
    ON oauth_tokens
    FOR ALL
    TO authenticated
    USING (false)
    WITH CHECK (false);


