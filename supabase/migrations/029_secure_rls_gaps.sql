-- ============================================================================
-- 029_secure_rls_gaps.sql
-- SECURITY REMEDIATION - closes the 19 RLS-off tables found on 2026-07-05.
-- Standalone migration — do NOT run 028 against production. 028 is a documentation
-- baseline only; 029 has no dependency on it (the helper functions it uses already
-- exist live). Fully idempotent — safe to re-run.
--
-- Context: every table below has GRANT ALL to anon + authenticated and RLS
-- disabled, so anyone holding the public anon key could read AND write all
-- rows cross-tenant via PostgREST. The backend is unaffected by this change:
-- it connects as the table owner (SQLAlchemy) / service_role (REST), both of
-- which bypass RLS. The frontend touches NONE of these tables directly
-- (verified by grep of supabase.from() usage on 2026-07-05).
--
-- Tables touched (19):
--   Business-scoped, member-access policies (13):
--     business_settings, integrations, briefing_snapshots,
--     automation_rules, automation_executions,
--     onboarding_sessions, onboarding_checklist,
--     executive_meetings, executive_meeting_settings,
--     executive_meeting_messages, executive_meeting_decisions,
--     executive_meeting_action_items, executive_meeting_goals
--   Personal data, self-scoped policies (1):
--     profiles
--   Catalog: public/authenticated read, platform-admin write (4):
--     accounting_providers, plan_definitions, support_articles,
--     automation_rule_templates
--   Dropped entirely (1):
--     email_sync_state_backup (orphan manual backup, referenced nowhere)
--
-- Deliberately NOT in scope (separate later migrations):
--   * consolidation of duplicate policies on businesses/tasks/calls
--   * tightening oauth_tokens / *_connections member access to service-only
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Business-scoped tables (13) - same member-access pattern already live on
--    quotes, whatsapp_*, receptionist_configs, etc. Members of the owning
--    business (or platform admins) get full access; everyone else: nothing.
--    All 13 tables carry business_id uuid NOT NULL directly - no join needed.
-- ----------------------------------------------------------------------------

ALTER TABLE public.business_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS business_settings_member_access ON public.business_settings;
CREATE POLICY business_settings_member_access ON public.business_settings
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.integrations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS integrations_member_access ON public.integrations;
CREATE POLICY integrations_member_access ON public.integrations
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.briefing_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS briefing_snapshots_member_access ON public.briefing_snapshots;
CREATE POLICY briefing_snapshots_member_access ON public.briefing_snapshots
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.automation_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS automation_rules_member_access ON public.automation_rules;
CREATE POLICY automation_rules_member_access ON public.automation_rules
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.automation_executions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS automation_executions_member_access ON public.automation_executions;
CREATE POLICY automation_executions_member_access ON public.automation_executions
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.onboarding_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS onboarding_sessions_member_access ON public.onboarding_sessions;
CREATE POLICY onboarding_sessions_member_access ON public.onboarding_sessions
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.onboarding_checklist ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS onboarding_checklist_member_access ON public.onboarding_checklist;
CREATE POLICY onboarding_checklist_member_access ON public.onboarding_checklist
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.executive_meetings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS executive_meetings_member_access ON public.executive_meetings;
CREATE POLICY executive_meetings_member_access ON public.executive_meetings
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.executive_meeting_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS executive_meeting_settings_member_access ON public.executive_meeting_settings;
CREATE POLICY executive_meeting_settings_member_access ON public.executive_meeting_settings
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.executive_meeting_messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS executive_meeting_messages_member_access ON public.executive_meeting_messages;
CREATE POLICY executive_meeting_messages_member_access ON public.executive_meeting_messages
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.executive_meeting_decisions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS executive_meeting_decisions_member_access ON public.executive_meeting_decisions;
CREATE POLICY executive_meeting_decisions_member_access ON public.executive_meeting_decisions
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.executive_meeting_action_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS executive_meeting_action_items_member_access ON public.executive_meeting_action_items;
CREATE POLICY executive_meeting_action_items_member_access ON public.executive_meeting_action_items
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

ALTER TABLE public.executive_meeting_goals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS executive_meeting_goals_member_access ON public.executive_meeting_goals;
CREATE POLICY executive_meeting_goals_member_access ON public.executive_meeting_goals
    FOR ALL TO authenticated
    USING (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()));

-- ----------------------------------------------------------------------------
-- 2. profiles - personal data keyed to auth.users(id). Self-access only:
--    a user can see and edit their own profile; platform admins see all.
--    No user-facing DELETE (rows cascade-delete with the auth.users record).
--    NOTE: profiles is now strictly self-visible. If a future feature needs the
--    frontend to read teammates' names directly from Supabase, add one policy
--    allowing business co-members to SELECT each other's profiles.
-- ----------------------------------------------------------------------------

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profiles_select_own ON public.profiles;
CREATE POLICY profiles_select_own ON public.profiles
    FOR SELECT TO authenticated
    USING (id = auth.uid());

DROP POLICY IF EXISTS profiles_insert_own ON public.profiles;
CREATE POLICY profiles_insert_own ON public.profiles
    FOR INSERT TO authenticated
    WITH CHECK (id = auth.uid());

DROP POLICY IF EXISTS profiles_update_own ON public.profiles;
CREATE POLICY profiles_update_own ON public.profiles
    FOR UPDATE TO authenticated
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());

DROP POLICY IF EXISTS profiles_admin_all ON public.profiles;
CREATE POLICY profiles_admin_all ON public.profiles
    FOR ALL TO authenticated
    USING (public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_platform_admin(auth.uid()));

-- ----------------------------------------------------------------------------
-- 3. Catalog tables (4) - reads stay open (that is by design), but writes
--    become platform-admin / service-role only. Before this, ANYONE with the
--    anon key could rewrite e.g. accounting_providers.oauth_auth_url
--    (phishing vector) or plan_definitions pricing.
--    service_role bypasses RLS, so backend writes keep working.
-- ----------------------------------------------------------------------------

-- accounting_providers: provider catalog incl. OAuth URLs. Anyone may read.
ALTER TABLE public.accounting_providers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS accounting_providers_public_read ON public.accounting_providers;
CREATE POLICY accounting_providers_public_read ON public.accounting_providers
    FOR SELECT TO anon, authenticated
    USING (true);
DROP POLICY IF EXISTS accounting_providers_admin_write ON public.accounting_providers;
CREATE POLICY accounting_providers_admin_write ON public.accounting_providers
    FOR ALL TO authenticated
    USING (public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_platform_admin(auth.uid()));

-- plan_definitions: pricing/limits catalog. Anyone may read.
ALTER TABLE public.plan_definitions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS plan_definitions_public_read ON public.plan_definitions;
CREATE POLICY plan_definitions_public_read ON public.plan_definitions
    FOR SELECT TO anon, authenticated
    USING (true);
DROP POLICY IF EXISTS plan_definitions_admin_write ON public.plan_definitions;
CREATE POLICY plan_definitions_admin_write ON public.plan_definitions
    FOR ALL TO authenticated
    USING (public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_platform_admin(auth.uid()));

-- support_articles: help centre. anon sees published only; logged-in users
-- see published; platform admins also see unpublished drafts.
ALTER TABLE public.support_articles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS support_articles_public_read ON public.support_articles;
CREATE POLICY support_articles_public_read ON public.support_articles
    FOR SELECT TO anon
    USING (is_published = true);
DROP POLICY IF EXISTS support_articles_member_read ON public.support_articles;
CREATE POLICY support_articles_member_read ON public.support_articles
    FOR SELECT TO authenticated
    USING (is_published = true OR public.is_platform_admin(auth.uid()));
DROP POLICY IF EXISTS support_articles_admin_write ON public.support_articles;
CREATE POLICY support_articles_admin_write ON public.support_articles
    FOR ALL TO authenticated
    USING (public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_platform_admin(auth.uid()));

-- automation_rule_templates: in-app template catalog - no anon read needed,
-- any logged-in user may read; writes admin/service only.
ALTER TABLE public.automation_rule_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS automation_rule_templates_member_read ON public.automation_rule_templates;
CREATE POLICY automation_rule_templates_member_read ON public.automation_rule_templates
    FOR SELECT TO authenticated
    USING (true);
DROP POLICY IF EXISTS automation_rule_templates_admin_write ON public.automation_rule_templates;
CREATE POLICY automation_rule_templates_admin_write ON public.automation_rule_templates
    FOR ALL TO authenticated
    USING (public.is_platform_admin(auth.uid()))
    WITH CHECK (public.is_platform_admin(auth.uid()));

-- ----------------------------------------------------------------------------
-- 4. Drop the orphan backup table. Manual copy of the old email_sync_state
--    made during the singular->plural rename; no PK, no business scoping,
--    referenced nowhere in backend or frontend code, anon-writable until now.
-- ----------------------------------------------------------------------------

DROP TABLE IF EXISTS public.email_sync_state_backup;
