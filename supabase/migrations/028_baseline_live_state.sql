-- ============================================================================
-- 028_baseline_live_state.sql
-- DOCUMENTATION BASELINE - captures the LIVE production state as of 2026-07-05
-- (pg_dump 18.4 schema-only dump, see audits/AUDIT-2026-07-04.md for context).
--
-- WHY THIS EXISTS
--   Live DB and migration files had diverged badly ("schema drift"):
--   * 16 tables exist in production that no migration ever created
--     (built via SQLAlchemy create_all() or the Supabase dashboard).
--   * RLS policies were fixed/added directly in the dashboard; the policies
--     in migrations 013/019 (USING(true) etc.) were superseded there and
--     NEVER matched what production runs today.
--   This file records reality so future migrations start from truth.
--
-- SAFETY
--   Fully idempotent. Safe to run against production by accident:
--   * CREATE TABLE IF NOT EXISTS       -> no-op where the table exists
--   * CREATE INDEX IF NOT EXISTS       -> no-op where the index exists
--   * CREATE OR REPLACE FUNCTION       -> re-asserts the identical live body
--   * ENABLE ROW LEVEL SECURITY        -> no-op where already enabled
--   * DROP POLICY IF EXISTS + CREATE   -> recreates the identical live policy
--
-- NOT INCLUDED (deliberately)
--   * email_sync_state_backup - orphan manual backup, dropped in 029; the
--     baseline must not resurrect it.
--   * No consolidation of the duplicate policies on businesses/tasks/calls
--     and no tightening of oauth_tokens - captured AS-IS; cleanup is a
--     separate, later migration.
--
-- NOTE: this is a baseline, not a from-scratch bootstrap. Some FKs reference
-- tables created by the historical backend/migrations/ series (e.g.
-- email_accounts); a brand-new environment needs those first.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Tables that exist ONLY in the live DB (no prior migration / ORM-created)
-- ----------------------------------------------------------------------------

-- --- businesses ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.businesses (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    timezone text DEFAULT 'Europe/London'::text NOT NULL,
    api_key text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    logo_url text,
    plan_tier text DEFAULT 'starter'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    trial_ends_at timestamp with time zone,
    feature_flags jsonb DEFAULT '{}'::jsonb NOT NULL,
    limits jsonb DEFAULT '{}'::jsonb NOT NULL,
    stripe_customer_id text,
    stripe_subscription_id text,
    subscription_status text,
    current_period_end timestamp with time zone,
    cancel_at_period_end boolean DEFAULT false NOT NULL,
    last_stripe_event_at timestamp with time zone,
    onboarding_completed boolean DEFAULT false,
    onboarding_completed_at timestamp with time zone,
    onboarded_by uuid,
    brand_color text DEFAULT '#3B82F6'::text,
    owner_whatsapp text,
    ceo_briefing_enabled boolean DEFAULT false,
    CONSTRAINT businesses_plan_tier_check CHECK ((plan_tier = ANY (ARRAY['starter'::text, 'pro'::text, 'elite'::text, 'beta'::text, 'paused'::text]))),
    CONSTRAINT businesses_api_key_key UNIQUE (api_key),
    CONSTRAINT businesses_pkey PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_businesses_is_active ON public.businesses USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_businesses_logo_url ON public.businesses USING btree (logo_url) WHERE (logo_url IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_businesses_plan_tier ON public.businesses USING btree (plan_tier);
CREATE INDEX IF NOT EXISTS idx_businesses_stripe_customer_id ON public.businesses USING btree (stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_businesses_stripe_subscription_id ON public.businesses USING btree (stripe_subscription_id);

-- --- profiles ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id uuid NOT NULL,
    full_name text,
    display_name text,
    job_title text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT profiles_pkey PRIMARY KEY (id),
    CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE
);

-- --- platform_admins -----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.platform_admins (
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT platform_admins_pkey PRIMARY KEY (user_id),
    CONSTRAINT platform_admins_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);

-- --- business_members ----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.business_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    user_id uuid,
    role text DEFAULT 'owner'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    invited_email text,
    accepted_at timestamp with time zone DEFAULT '2025-12-23 13:13:40.205968+00'::timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT business_members_business_id_user_id_key UNIQUE (business_id, user_id),
    CONSTRAINT business_members_pkey PRIMARY KEY (id),
    CONSTRAINT business_members_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE,
    CONSTRAINT business_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bm_business_id ON public.business_members USING btree (business_id);
CREATE INDEX IF NOT EXISTS idx_bm_user_id ON public.business_members USING btree (user_id);

-- --- tasks ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    title text NOT NULL,
    description text,
    due_at timestamp with time zone,
    recurrence text DEFAULT 'none'::text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    source text DEFAULT 'manual'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    category text DEFAULT 'general'::text,
    priority text DEFAULT 'medium'::text,
    source_id text,
    CONSTRAINT tasks_pkey PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS idx_tasks_business_deleted_at ON public.tasks USING btree (business_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_tasks_business_id ON public.tasks USING btree (business_id);

-- --- calls ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.calls (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    source text DEFAULT 'Awaz'::text NOT NULL,
    caller_number text,
    caller_name text,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    transcript text,
    summary text,
    intent text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    archived boolean DEFAULT false,
    updated_at timestamp with time zone DEFAULT now(),
    duration_seconds integer,
    recording_url text,
    outcome text DEFAULT 'handled'::text,
    receptionist_config_id uuid,
    CONSTRAINT calls_pkey PRIMARY KEY (id),
    CONSTRAINT calls_receptionist_config_id_fkey FOREIGN KEY (receptionist_config_id) REFERENCES public.receptionist_configs(id)
);
CREATE INDEX IF NOT EXISTS idx_calls_archived ON public.calls USING btree (archived);
CREATE INDEX IF NOT EXISTS idx_calls_business_archived ON public.calls USING btree (business_id, archived);
CREATE INDEX IF NOT EXISTS idx_calls_business_id ON public.calls USING btree (business_id);
CREATE INDEX IF NOT EXISTS idx_calls_outcome ON public.calls USING btree (outcome);
CREATE INDEX IF NOT EXISTS idx_calls_source ON public.calls USING btree (source);
DROP TRIGGER IF EXISTS tr_check_filters ON public.calls;
CREATE TRIGGER tr_check_filters BEFORE INSERT OR UPDATE ON realtime.subscription FOR EACH ROW EXECUTE FUNCTION realtime.subscription_check_filters(); -- -- Name: buckets enforce_bucket_name_length_trigger; Type: TRIGGER; Schema: storage; Owner: - -- CREATE TRIGGER enforce_bucket_name_length_trigger BEFORE INSERT OR UPDATE OF name ON storage.buckets FOR EACH ROW EXECUTE FUNCTION storage.enforce_bucket_name_length(); -- -- Name: buckets protect_buckets_delete; Type: TRIGGER; Schema: storage; Owner: - -- CREATE TRIGGER protect_buckets_delete BEFORE DELETE ON storage.buckets FOR EACH STATEMENT EXECUTE FUNCTION storage.protect_delete(); -- -- Name: objects protect_objects_delete; Type: TRIGGER; Schema: storage; Owner: - -- CREATE TRIGGER protect_objects_delete BEFORE DELETE ON storage.objects FOR EACH STATEMENT EXECUTE FUNCTION storage.protect_delete(); -- -- Name: objects update_objects_updated_at; Type: TRIGGER; Schema: storage; Owner: - -- CREATE TRIGGER update_objects_updated_at BEFORE UPDATE ON storage.objects FOR EACH ROW EXECUTE FUNCTION storage.update_updated_at_column(); -- -- Name: identities identities_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.identities ADD CONSTRAINT identities_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: mfa_amr_claims mfa_amr_claims_session_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.mfa_amr_claims ADD CONSTRAINT mfa_amr_claims_session_id_fkey FOREIGN KEY (session_id) REFERENCES auth.sessions(id) ON DELETE CASCADE; -- -- Name: mfa_challenges mfa_challenges_auth_factor_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.mfa_challenges ADD CONSTRAINT mfa_challenges_auth_factor_id_fkey FOREIGN KEY (factor_id) REFERENCES auth.mfa_factors(id) ON DELETE CASCADE; -- -- Name: mfa_factors mfa_factors_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.mfa_factors ADD CONSTRAINT mfa_factors_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: oauth_authorizations oauth_authorizations_client_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.oauth_authorizations ADD CONSTRAINT oauth_authorizations_client_id_fkey FOREIGN KEY (client_id) REFERENCES auth.oauth_clients(id) ON DELETE CASCADE; -- -- Name: oauth_authorizations oauth_authorizations_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.oauth_authorizations ADD CONSTRAINT oauth_authorizations_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: oauth_consents oauth_consents_client_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.oauth_consents ADD CONSTRAINT oauth_consents_client_id_fkey FOREIGN KEY (client_id) REFERENCES auth.oauth_clients(id) ON DELETE CASCADE; -- -- Name: oauth_consents oauth_consents_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.oauth_consents ADD CONSTRAINT oauth_consents_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: one_time_tokens one_time_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.one_time_tokens ADD CONSTRAINT one_time_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: refresh_tokens refresh_tokens_session_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.refresh_tokens ADD CONSTRAINT refresh_tokens_session_id_fkey FOREIGN KEY (session_id) REFERENCES auth.sessions(id) ON DELETE CASCADE; -- -- Name: saml_providers saml_providers_sso_provider_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.saml_providers ADD CONSTRAINT saml_providers_sso_provider_id_fkey FOREIGN KEY (sso_provider_id) REFERENCES auth.sso_providers(id) ON DELETE CASCADE; -- -- Name: saml_relay_states saml_relay_states_flow_state_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.saml_relay_states ADD CONSTRAINT saml_relay_states_flow_state_id_fkey FOREIGN KEY (flow_state_id) REFERENCES auth.flow_state(id) ON DELETE CASCADE; -- -- Name: saml_relay_states saml_relay_states_sso_provider_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.saml_relay_states ADD CONSTRAINT saml_relay_states_sso_provider_id_fkey FOREIGN KEY (sso_provider_id) REFERENCES auth.sso_providers(id) ON DELETE CASCADE; -- -- Name: sessions sessions_oauth_client_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.sessions ADD CONSTRAINT sessions_oauth_client_id_fkey FOREIGN KEY (oauth_client_id) REFERENCES auth.oauth_clients(id) ON DELETE CASCADE; -- -- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.sessions ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: sso_domains sso_domains_sso_provider_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.sso_domains ADD CONSTRAINT sso_domains_sso_provider_id_fkey FOREIGN KEY (sso_provider_id) REFERENCES auth.sso_providers(id) ON DELETE CASCADE; -- -- Name: webauthn_challenges webauthn_challenges_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.webauthn_challenges ADD CONSTRAINT webauthn_challenges_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: webauthn_credentials webauthn_credentials_user_id_fkey; Type: FK CONSTRAINT; Schema: auth; Owner: - -- ALTER TABLE ONLY auth.webauthn_credentials ADD CONSTRAINT webauthn_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: accounting_categories accounting_categories_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.accounting_categories ADD CONSTRAINT accounting_categories_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: accounting_connections accounting_connections_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.accounting_connections ADD CONSTRAINT accounting_connections_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: accounting_imports accounting_imports_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.accounting_imports ADD CONSTRAINT accounting_imports_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: accounting_transactions accounting_transactions_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.accounting_transactions ADD CONSTRAINT accounting_transactions_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: accounting_transactions accounting_transactions_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.accounting_transactions ADD CONSTRAINT accounting_transactions_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.accounting_categories(id) ON DELETE SET NULL; -- -- Name: accounting_transactions accounting_transactions_import_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.accounting_transactions ADD CONSTRAINT accounting_transactions_import_id_fkey FOREIGN KEY (import_id) REFERENCES public.accounting_imports(id) ON DELETE SET NULL; -- -- Name: assistant_conversations assistant_conversations_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.assistant_conversations ADD CONSTRAINT assistant_conversations_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: assistant_conversations assistant_conversations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.assistant_conversations ADD CONSTRAINT assistant_conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: assistant_messages assistant_messages_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.assistant_messages ADD CONSTRAINT assistant_messages_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: assistant_messages assistant_messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.assistant_messages ADD CONSTRAINT assistant_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.assistant_conversations(id) ON DELETE CASCADE; -- -- Name: assistant_messages assistant_messages_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.assistant_messages ADD CONSTRAINT assistant_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: automation_executions automation_executions_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.automation_executions ADD CONSTRAINT automation_executions_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: automation_executions automation_executions_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.automation_executions ADD CONSTRAINT automation_executions_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.automation_rules(id) ON DELETE CASCADE; -- -- Name: automation_rules automation_rules_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.automation_rules ADD CONSTRAINT automation_rules_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: booking_settings booking_settings_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.booking_settings ADD CONSTRAINT booking_settings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: briefing_snapshots briefing_snapshots_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.briefing_snapshots ADD CONSTRAINT briefing_snapshots_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: business_members business_members_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.business_members ADD CONSTRAINT business_members_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: business_members business_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.business_members ADD CONSTRAINT business_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: business_settings business_settings_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.business_settings ADD CONSTRAINT business_settings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id); -- -- Name: calendar_events calendar_events_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.calendar_events ADD CONSTRAINT calendar_events_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: calendar_events calendar_events_email_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.calendar_events ADD CONSTRAINT calendar_events_email_account_id_fkey FOREIGN KEY (email_account_id) REFERENCES public.email_accounts(id) ON DELETE CASCADE; -- -- Name: calendar_sync_state calendar_sync_state_email_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.calendar_sync_state ADD CONSTRAINT calendar_sync_state_email_account_id_fkey FOREIGN KEY (email_account_id) REFERENCES public.email_accounts(id) ON DELETE CASCADE; -- -- Name: calls calls_receptionist_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.calls ADD CONSTRAINT calls_receptionist_config_id_fkey FOREIGN KEY (receptionist_config_id) REFERENCES public.receptionist_configs(id); -- -- Name: email_accounts email_accounts_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_accounts ADD CONSTRAINT email_accounts_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: email_accounts email_accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_accounts ADD CONSTRAINT email_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: email_briefings email_briefings_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_briefings ADD CONSTRAINT email_briefings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: email_briefings email_briefings_email_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_briefings ADD CONSTRAINT email_briefings_email_account_id_fkey FOREIGN KEY (email_account_id) REFERENCES public.email_accounts(id) ON DELETE SET NULL; -- -- Name: email_briefings email_briefings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_briefings ADD CONSTRAINT email_briefings_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: email_connections email_connections_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_connections ADD CONSTRAINT email_connections_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id); -- -- Name: email_drafts email_drafts_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_drafts ADD CONSTRAINT email_drafts_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: email_drafts email_drafts_email_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_drafts ADD CONSTRAINT email_drafts_email_message_id_fkey FOREIGN KEY (email_message_id) REFERENCES public.email_messages(id) ON DELETE CASCADE; -- -- Name: email_messages email_messages_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_messages ADD CONSTRAINT email_messages_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: email_messages email_messages_email_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_messages ADD CONSTRAINT email_messages_email_account_id_fkey FOREIGN KEY (email_account_id) REFERENCES public.email_accounts(id) ON DELETE CASCADE; -- -- Name: email_outbox email_outbox_business_id_fkey1; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_outbox ADD CONSTRAINT email_outbox_business_id_fkey1 FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: email_outbox email_outbox_email_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_outbox ADD CONSTRAINT email_outbox_email_account_id_fkey FOREIGN KEY (email_account_id) REFERENCES public.email_accounts(id) ON DELETE CASCADE; -- -- Name: email_outbox email_outbox_invoice_id_fkey1; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_outbox ADD CONSTRAINT email_outbox_invoice_id_fkey1 FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE SET NULL; -- -- Name: email_sync_states email_sync_states_email_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.email_sync_states ADD CONSTRAINT email_sync_states_email_account_id_fkey FOREIGN KEY (email_account_id) REFERENCES public.email_accounts(id); -- -- Name: executive_meeting_action_items executive_meeting_action_items_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_action_items ADD CONSTRAINT executive_meeting_action_items_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: executive_meeting_action_items executive_meeting_action_items_meeting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_action_items ADD CONSTRAINT executive_meeting_action_items_meeting_id_fkey FOREIGN KEY (meeting_id) REFERENCES public.executive_meetings(id) ON DELETE CASCADE; -- -- Name: executive_meeting_decisions executive_meeting_decisions_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_decisions ADD CONSTRAINT executive_meeting_decisions_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: executive_meeting_decisions executive_meeting_decisions_meeting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_decisions ADD CONSTRAINT executive_meeting_decisions_meeting_id_fkey FOREIGN KEY (meeting_id) REFERENCES public.executive_meetings(id) ON DELETE CASCADE; -- -- Name: executive_meeting_goals executive_meeting_goals_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_goals ADD CONSTRAINT executive_meeting_goals_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: executive_meeting_goals executive_meeting_goals_set_in_meeting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_goals ADD CONSTRAINT executive_meeting_goals_set_in_meeting_id_fkey FOREIGN KEY (set_in_meeting_id) REFERENCES public.executive_meetings(id) ON DELETE SET NULL; -- -- Name: executive_meeting_messages executive_meeting_messages_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_messages ADD CONSTRAINT executive_meeting_messages_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: executive_meeting_messages executive_meeting_messages_meeting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_messages ADD CONSTRAINT executive_meeting_messages_meeting_id_fkey FOREIGN KEY (meeting_id) REFERENCES public.executive_meetings(id) ON DELETE CASCADE; -- -- Name: executive_meeting_settings executive_meeting_settings_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meeting_settings ADD CONSTRAINT executive_meeting_settings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: executive_meetings executive_meetings_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.executive_meetings ADD CONSTRAINT executive_meetings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: financial_summary_cache financial_summary_cache_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.financial_summary_cache ADD CONSTRAINT financial_summary_cache_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id); -- -- Name: integrations integrations_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.integrations ADD CONSTRAINT integrations_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id); -- -- Name: invoices invoices_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.invoices ADD CONSTRAINT invoices_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: knowledge_base_items knowledge_base_items_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.knowledge_base_items ADD CONSTRAINT knowledge_base_items_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: oauth_tokens oauth_tokens_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.oauth_tokens ADD CONSTRAINT oauth_tokens_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id); -- -- Name: onboarding_checklist onboarding_checklist_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.onboarding_checklist ADD CONSTRAINT onboarding_checklist_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: onboarding_sessions onboarding_sessions_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.onboarding_sessions ADD CONSTRAINT onboarding_sessions_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: platform_admins platform_admins_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.platform_admins ADD CONSTRAINT platform_admins_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: profiles profiles_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.profiles ADD CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: quote_line_items quote_line_items_quote_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.quote_line_items ADD CONSTRAINT quote_line_items_quote_id_fkey FOREIGN KEY (quote_id) REFERENCES public.quotes(id) ON DELETE CASCADE; -- -- Name: quote_settings quote_settings_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.quote_settings ADD CONSTRAINT quote_settings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: quotes quotes_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.quotes ADD CONSTRAINT quotes_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: receptionist_configs receptionist_configs_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.receptionist_configs ADD CONSTRAINT receptionist_configs_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: stripe_events stripe_events_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.stripe_events ADD CONSTRAINT stripe_events_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE SET NULL; -- -- Name: support_conversations support_conversations_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.support_conversations ADD CONSTRAINT support_conversations_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: support_messages support_messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.support_messages ADD CONSTRAINT support_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.support_conversations(id) ON DELETE CASCADE; -- -- Name: support_tickets support_tickets_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.support_tickets ADD CONSTRAINT support_tickets_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: support_tickets support_tickets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.support_tickets ADD CONSTRAINT support_tickets_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE; -- -- Name: whatsapp_configs whatsapp_configs_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.whatsapp_configs ADD CONSTRAINT whatsapp_configs_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: whatsapp_messages whatsapp_messages_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.whatsapp_messages ADD CONSTRAINT whatsapp_messages_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: whatsapp_pending_actions whatsapp_pending_actions_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.whatsapp_pending_actions ADD CONSTRAINT whatsapp_pending_actions_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE; -- -- Name: whatsapp_pending_actions whatsapp_pending_actions_source_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.whatsapp_pending_actions ADD CONSTRAINT whatsapp_pending_actions_source_message_id_fkey FOREIGN KEY (source_message_id) REFERENCES public.whatsapp_messages(id); -- -- Name: xero_connections xero_connections_business_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: - -- ALTER TABLE ONLY public.xero_connections ADD CONSTRAINT xero_connections_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id); -- -- Name: objects objects_bucketId_fkey; Type: FK CONSTRAINT; Schema: storage; Owner: - -- ALTER TABLE ONLY storage.objects ADD CONSTRAINT "objects_bucketId_fkey" FOREIGN KEY (bucket_id) REFERENCES storage.buckets(id); -- -- Name: s3_multipart_uploads s3_multipart_uploads_bucket_id_fkey; Type: FK CONSTRAINT; Schema: storage; Owner: - -- ALTER TABLE ONLY storage.s3_multipart_uploads ADD CONSTRAINT s3_multipart_uploads_bucket_id_fkey FOREIGN KEY (bucket_id) REFERENCES storage.buckets(id); -- -- Name: s3_multipart_uploads_parts s3_multipart_uploads_parts_bucket_id_fkey; Type: FK CONSTRAINT; Schema: storage; Owner: - -- ALTER TABLE ONLY storage.s3_multipart_uploads_parts ADD CONSTRAINT s3_multipart_uploads_parts_bucket_id_fkey FOREIGN KEY (bucket_id) REFERENCES storage.buckets(id); -- -- Name: s3_multipart_uploads_parts s3_multipart_uploads_parts_upload_id_fkey; Type: FK CONSTRAINT; Schema: storage; Owner: - -- ALTER TABLE ONLY storage.s3_multipart_uploads_parts ADD CONSTRAINT s3_multipart_uploads_parts_upload_id_fkey FOREIGN KEY (upload_id) REFERENCES storage.s3_multipart_uploads(id) ON DELETE CASCADE; -- -- Name: vector_indexes vector_indexes_bucket_id_fkey; Type: FK CONSTRAINT; Schema: storage; Owner: - -- ALTER TABLE ONLY storage.vector_indexes ADD CONSTRAINT vector_indexes_bucket_id_fkey FOREIGN KEY (bucket_id) REFERENCES storage.buckets_vectors(id); -- -- Name: audit_log_entries; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.audit_log_entries ENABLE ROW LEVEL SECURITY; -- -- Name: flow_state; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.flow_state ENABLE ROW LEVEL SECURITY; -- -- Name: identities; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.identities ENABLE ROW LEVEL SECURITY; -- -- Name: instances; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.instances ENABLE ROW LEVEL SECURITY; -- -- Name: mfa_amr_claims; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.mfa_amr_claims ENABLE ROW LEVEL SECURITY; -- -- Name: mfa_challenges; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.mfa_challenges ENABLE ROW LEVEL SECURITY; -- -- Name: mfa_factors; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.mfa_factors ENABLE ROW LEVEL SECURITY; -- -- Name: one_time_tokens; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.one_time_tokens ENABLE ROW LEVEL SECURITY; -- -- Name: refresh_tokens; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.refresh_tokens ENABLE ROW LEVEL SECURITY; -- -- Name: saml_providers; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.saml_providers ENABLE ROW LEVEL SECURITY; -- -- Name: saml_relay_states; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.saml_relay_states ENABLE ROW LEVEL SECURITY; -- -- Name: schema_migrations; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.schema_migrations ENABLE ROW LEVEL SECURITY; -- -- Name: sessions; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.sessions ENABLE ROW LEVEL SECURITY; -- -- Name: sso_domains; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.sso_domains ENABLE ROW LEVEL SECURITY; -- -- Name: sso_providers; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.sso_providers ENABLE ROW LEVEL SECURITY; -- -- Name: users; Type: ROW SECURITY; Schema: auth; Owner: - -- ALTER TABLE auth.users ENABLE ROW LEVEL SECURITY; -- -- Name: calls Members can select calls for their businesses; Type: POLICY; Schema: public; Owner: - -- CREATE POLICY "Members can select calls for their businesses" ON public.calls FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1 FROM public.business_members bm WHERE ((bm.business_id = calls.business_id) AND (bm.user_id = auth.uid())))));

-- --- email_sync_states ---------------------------------------------------
CREATE TABLE IF NOT EXISTS public.email_sync_states (
    id uuid NOT NULL,
    email_account_id uuid NOT NULL,
    last_sync_token character varying,
    last_history_id character varying,
    last_synced_at timestamp without time zone,
    sync_status character varying DEFAULT 'idle'::character varying NOT NULL,
    error_message character varying,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    cursor jsonb DEFAULT '{}'::jsonb,
    last_error text,
    CONSTRAINT email_sync_states_pkey PRIMARY KEY (id),
    CONSTRAINT email_sync_states_email_account_id_fkey FOREIGN KEY (email_account_id) REFERENCES public.email_accounts(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_email_sync_states_email_account_id ON public.email_sync_states USING btree (email_account_id);

-- --- quotes --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.quotes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    quote_number text NOT NULL,
    reference text,
    customer_name text NOT NULL,
    customer_email text,
    customer_phone text,
    customer_address text,
    job_title text NOT NULL,
    job_description text,
    job_location text,
    subtotal numeric(12,2) DEFAULT 0 NOT NULL,
    tax_rate numeric(5,2) DEFAULT 20.00,
    tax_amount numeric(12,2) DEFAULT 0,
    discount_amount numeric(12,2) DEFAULT 0,
    discount_type text DEFAULT 'fixed'::text,
    total numeric(12,2) DEFAULT 0 NOT NULL,
    currency text DEFAULT 'GBP'::text,
    markup_percentage numeric(5,2) DEFAULT 0,
    profit_margin numeric(12,2) DEFAULT 0,
    status text DEFAULT 'draft'::text NOT NULL,
    issue_date date,
    valid_until date,
    accepted_at timestamp with time zone,
    declined_at timestamp with time zone,
    terms text,
    notes text,
    customer_notes text,
    ai_generated boolean DEFAULT false,
    ai_prompt text,
    ai_model text,
    invoice_id uuid,
    pdf_url text,
    sent_at timestamp with time zone,
    sent_via text,
    viewed_at timestamp with time zone,
    project_reference text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    CONSTRAINT quotes_business_id_quote_number_key UNIQUE (business_id, quote_number),
    CONSTRAINT quotes_pkey PRIMARY KEY (id),
    CONSTRAINT quotes_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_quotes_business_created ON public.quotes USING btree (business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quotes_business_status ON public.quotes USING btree (business_id, status);
CREATE INDEX IF NOT EXISTS idx_quotes_project ON public.quotes USING btree (business_id, project_reference) WHERE (project_reference IS NOT NULL);

-- --- quote_settings ------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.quote_settings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    next_quote_number integer DEFAULT 1,
    quote_prefix text DEFAULT 'QTE-'::text,
    default_terms text DEFAULT 'This quote is valid for 30 days from the date of issue. Payment terms: 50% deposit on acceptance, balance on completion.'::text,
    default_valid_days integer DEFAULT 30,
    default_tax_rate numeric(5,2) DEFAULT 20.00,
    include_tax boolean DEFAULT true,
    default_markup numeric(5,2) DEFAULT 0,
    company_name text,
    company_address text,
    company_phone text,
    company_email text,
    company_logo_url text,
    company_registration text,
    vat_number text,
    industry text DEFAULT 'general'::text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    labour_rates jsonb DEFAULT '[]'::jsonb,
    CONSTRAINT quote_settings_business_id_key UNIQUE (business_id),
    CONSTRAINT quote_settings_pkey PRIMARY KEY (id),
    CONSTRAINT quote_settings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE
);

-- --- quote_line_items ----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.quote_line_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    quote_id uuid NOT NULL,
    category text DEFAULT 'general'::text NOT NULL,
    description text NOT NULL,
    quantity numeric(12,3) DEFAULT 1 NOT NULL,
    unit text DEFAULT 'each'::text,
    unit_cost numeric(12,2) DEFAULT 0 NOT NULL,
    line_total numeric(12,2) DEFAULT 0 NOT NULL,
    markup_percentage numeric(5,2) DEFAULT 0,
    markup_amount numeric(12,2) DEFAULT 0,
    sort_order integer DEFAULT 0,
    group_name text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT quote_line_items_pkey PRIMARY KEY (id),
    CONSTRAINT quote_line_items_quote_id_fkey FOREIGN KEY (quote_id) REFERENCES public.quotes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_quote_items_quote ON public.quote_line_items USING btree (quote_id, sort_order);

-- --- accounting_categories -----------------------------------------------
CREATE TABLE IF NOT EXISTS public.accounting_categories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    type character varying(20) NOT NULL,
    color character varying(7) DEFAULT '#6B7280'::character varying,
    icon character varying(50),
    is_default boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT accounting_categories_type_check CHECK (((type)::text = ANY ((ARRAY['income'::character varying, 'expense'::character varying])::text[]))),
    CONSTRAINT accounting_categories_business_id_name_type_key UNIQUE (business_id, name, type),
    CONSTRAINT accounting_categories_pkey PRIMARY KEY (id),
    CONSTRAINT accounting_categories_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_categories_business ON public.accounting_categories USING btree (business_id);

-- --- accounting_imports --------------------------------------------------
CREATE TABLE IF NOT EXISTS public.accounting_imports (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    filename character varying(255) NOT NULL,
    original_filename character varying(255),
    row_count integer DEFAULT 0,
    success_count integer DEFAULT 0,
    error_count integer DEFAULT 0,
    status character varying(20) DEFAULT 'pending'::character varying,
    error_message text,
    column_mapping jsonb,
    created_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    CONSTRAINT accounting_imports_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT accounting_imports_pkey PRIMARY KEY (id),
    CONSTRAINT accounting_imports_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_imports_business ON public.accounting_imports USING btree (business_id);

-- --- accounting_transactions ---------------------------------------------
CREATE TABLE IF NOT EXISTS public.accounting_transactions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    import_id uuid,
    category_id uuid,
    transaction_date date NOT NULL,
    description text NOT NULL,
    amount numeric(12,2) NOT NULL,
    type character varying(20) NOT NULL,
    reference character varying(100),
    payee_payer character varying(255),
    account character varying(100),
    notes text,
    is_reconciled boolean DEFAULT false,
    is_archived boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    external_id text,
    external_source text,
    provider text DEFAULT 'xero'::text,
    CONSTRAINT accounting_transactions_type_check CHECK (((type)::text = ANY ((ARRAY['income'::character varying, 'expense'::character varying])::text[]))),
    CONSTRAINT accounting_transactions_pkey PRIMARY KEY (id),
    CONSTRAINT accounting_transactions_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE,
    CONSTRAINT accounting_transactions_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.accounting_categories(id) ON DELETE SET NULL,
    CONSTRAINT accounting_transactions_import_id_fkey FOREIGN KEY (import_id) REFERENCES public.accounting_imports(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounting_txn_external ON public.accounting_transactions USING btree (business_id, external_source, external_id) WHERE (external_id IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_transactions_business_category ON public.accounting_transactions USING btree (business_id, category_id);
CREATE INDEX IF NOT EXISTS idx_transactions_business_date ON public.accounting_transactions USING btree (business_id, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_business_type ON public.accounting_transactions USING btree (business_id, type);
CREATE INDEX IF NOT EXISTS idx_transactions_import ON public.accounting_transactions USING btree (import_id);

-- --- assistant_conversations ---------------------------------------------
CREATE TABLE IF NOT EXISTS public.assistant_conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    business_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT assistant_conversations_pkey PRIMARY KEY (id),
    CONSTRAINT assistant_conversations_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE,
    CONSTRAINT assistant_conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);

-- --- assistant_messages --------------------------------------------------
CREATE TABLE IF NOT EXISTS public.assistant_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid NOT NULL,
    business_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT assistant_messages_role_check CHECK ((role = ANY (ARRAY['system'::text, 'user'::text, 'assistant'::text]))),
    CONSTRAINT assistant_messages_pkey PRIMARY KEY (id),
    CONSTRAINT assistant_messages_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE,
    CONSTRAINT assistant_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.assistant_conversations(id) ON DELETE CASCADE,
    CONSTRAINT assistant_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);

-- --- booking_settings ----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.booking_settings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    business_id uuid NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    business_hours jsonb DEFAULT '[]'::jsonb NOT NULL,
    appointment_types jsonb DEFAULT '[]'::jsonb NOT NULL,
    buffer_minutes integer DEFAULT 15 NOT NULL,
    max_advance_days integer DEFAULT 30 NOT NULL,
    min_notice_hours integer DEFAULT 2 NOT NULL,
    confirmation_message text DEFAULT 'Your appointment has been booked. You will receive a calendar invite shortly.'::text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    calendar_id text DEFAULT 'primary'::text,
    CONSTRAINT booking_settings_business_id_key UNIQUE (business_id),
    CONSTRAINT booking_settings_pkey PRIMARY KEY (id),
    CONSTRAINT booking_settings_business_id_fkey FOREIGN KEY (business_id) REFERENCES public.businesses(id) ON DELETE CASCADE
);

-- ----------------------------------------------------------------------------
-- 2. Helper functions used by RLS policies (live definitions, verbatim)
--    NB: is_business_member does NOT check business_members.is_active -
--    captured as-is; any tightening is a separate decision.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.is_business_member(p_user_id uuid, p_business_id uuid) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  select exists (
    select 1
    from public.business_members bm
    where bm.user_id = p_user_id
      and bm.business_id = p_business_id
  );
$$;

CREATE OR REPLACE FUNCTION public.is_platform_admin(p_user_id uuid) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
  select exists (
    select 1
    from public.platform_admins pa
    where pa.user_id = p_user_id
  );
$$;

CREATE OR REPLACE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
begin
  new.updated_at = now();
  return new;
end;
$$;

CREATE OR REPLACE FUNCTION public.setup_default_accounting_categories(p_business_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Default income categories
    INSERT INTO accounting_categories (business_id, name, type, color, is_default) VALUES
        (p_business_id, 'Sales', 'income', '#10B981', true),
        (p_business_id, 'Services', 'income', '#3B82F6', true),
        (p_business_id, 'Memberships', 'income', '#8B5CF6', true),
        (p_business_id, 'Other Income', 'income', '#6B7280', true)
    ON CONFLICT (business_id, name, type) DO NOTHING;
    
    -- Default expense categories
    INSERT INTO accounting_categories (business_id, name, type, color, is_default) VALUES
        (p_business_id, 'Rent', 'expense', '#EF4444', true),
        (p_business_id, 'Utilities', 'expense', '#F59E0B', true),
        (p_business_id, 'Salaries', 'expense', '#EC4899', true),
        (p_business_id, 'Equipment', 'expense', '#6366F1', true),
        (p_business_id, 'Marketing', 'expense', '#14B8A6', true),
        (p_business_id, 'Insurance', 'expense', '#F97316', true),
        (p_business_id, 'Supplies', 'expense', '#84CC16', true),
        (p_business_id, 'Professional Fees', 'expense', '#A855F7', true),
        (p_business_id, 'Travel', 'expense', '#06B6D4', true),
        (p_business_id, 'Other Expense', 'expense', '#6B7280', true)
    ON CONFLICT (business_id, name, type) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION public.whoami() RETURNS json
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
  SELECT json_build_object(
    'uid', auth.uid()::text,
    'role', auth.role()
  );
$$;

-- ----------------------------------------------------------------------------
-- 3. RLS enablement - the 37 tables with RLS ON in production today
-- ----------------------------------------------------------------------------

ALTER TABLE public.accounting_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounting_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounting_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounting_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assistant_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.booking_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calendar_sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_briefings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_sync_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.financial_summary_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_base_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_admins ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quote_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quote_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.receptionist_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stripe_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.support_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.support_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.support_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.whatsapp_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.whatsapp_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.whatsapp_pending_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.xero_connections ENABLE ROW LEVEL SECURITY;

-- ----------------------------------------------------------------------------
-- 4. Live RLS policies, verbatim (66 policies)
--    Includes the 9 overlapping policies on businesses and the duplicate
--    SELECT policies on tasks/calls - real production state, kept AS-IS.
-- ----------------------------------------------------------------------------

-- --- calls ---------------------------------------------------------------
DROP POLICY IF EXISTS "Members can select calls for their businesses" ON public.calls;
CREATE POLICY "Members can select calls for their businesses" ON public.calls FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = calls.business_id) AND (bm.user_id = auth.uid())))));

-- --- tasks ---------------------------------------------------------------
DROP POLICY IF EXISTS "Members can select tasks for their businesses" ON public.tasks;
CREATE POLICY "Members can select tasks for their businesses" ON public.tasks FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = tasks.business_id) AND (bm.user_id = auth.uid())))));

-- --- businesses ----------------------------------------------------------
DROP POLICY IF EXISTS "Members can select their own businesses" ON public.businesses;
CREATE POLICY "Members can select their own businesses" ON public.businesses FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid())))));

DROP POLICY IF EXISTS "Members can view their business" ON public.businesses;
CREATE POLICY "Members can view their business" ON public.businesses FOR SELECT TO authenticated USING ((id IN ( SELECT business_members.business_id
   FROM public.business_members
  WHERE (business_members.user_id = auth.uid()))));

DROP POLICY IF EXISTS "Platform admins can manage all businesses" ON public.businesses;
CREATE POLICY "Platform admins can manage all businesses" ON public.businesses TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.platform_admins
  WHERE (platform_admins.user_id = auth.uid()))));

DROP POLICY IF EXISTS "Platform admins can view all businesses" ON public.businesses;
CREATE POLICY "Platform admins can view all businesses" ON public.businesses FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.platform_admins
  WHERE (platform_admins.user_id = auth.uid()))));

DROP POLICY IF EXISTS "Platform admins full access to businesses" ON public.businesses;
CREATE POLICY "Platform admins full access to businesses" ON public.businesses TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.platform_admins
  WHERE (platform_admins.user_id = auth.uid()))));

DROP POLICY IF EXISTS "Users can view their businesses" ON public.businesses;
CREATE POLICY "Users can view their businesses" ON public.businesses FOR SELECT TO authenticated USING ((id IN ( SELECT business_members.business_id
   FROM public.business_members
  WHERE (business_members.user_id = auth.uid()))));

-- --- accounting_categories -----------------------------------------------
DROP POLICY IF EXISTS accounting_categories_member_access ON public.accounting_categories;
CREATE POLICY accounting_categories_member_access ON public.accounting_categories TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- accounting_connections ----------------------------------------------
DROP POLICY IF EXISTS accounting_connections_member_access ON public.accounting_connections;
CREATE POLICY accounting_connections_member_access ON public.accounting_connections TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- accounting_imports --------------------------------------------------
DROP POLICY IF EXISTS accounting_imports_member_access ON public.accounting_imports;
CREATE POLICY accounting_imports_member_access ON public.accounting_imports TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- accounting_transactions ---------------------------------------------
DROP POLICY IF EXISTS accounting_transactions_member_access ON public.accounting_transactions;
CREATE POLICY accounting_transactions_member_access ON public.accounting_transactions TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- business_members ----------------------------------------------------
DROP POLICY IF EXISTS admins_full_access ON public.business_members;
CREATE POLICY admins_full_access ON public.business_members TO authenticated USING ((auth.uid() IN ( SELECT platform_admins.user_id
   FROM public.platform_admins))) WITH CHECK ((auth.uid() IN ( SELECT platform_admins.user_id
   FROM public.platform_admins)));

-- --- assistant_conversations ---------------------------------------------
DROP POLICY IF EXISTS assistant_conversations_member_access ON public.assistant_conversations;
CREATE POLICY assistant_conversations_member_access ON public.assistant_conversations TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- assistant_messages --------------------------------------------------
DROP POLICY IF EXISTS assistant_messages_member_access ON public.assistant_messages;
CREATE POLICY assistant_messages_member_access ON public.assistant_messages TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- businesses ----------------------------------------------------------
DROP POLICY IF EXISTS biz_select_if_member ON public.businesses;
CREATE POLICY biz_select_if_member ON public.businesses FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))));

DROP POLICY IF EXISTS biz_update_if_owner ON public.businesses;
CREATE POLICY biz_update_if_owner ON public.businesses FOR UPDATE TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.role = 'owner'::text) AND (bm.is_active = true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.role = 'owner'::text) AND (bm.is_active = true)))));

-- --- booking_settings ----------------------------------------------------
DROP POLICY IF EXISTS booking_settings_member_access ON public.booking_settings;
CREATE POLICY booking_settings_member_access ON public.booking_settings TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- invoices ------------------------------------------------------------
DROP POLICY IF EXISTS business_members_delete_invoices ON public.invoices;
CREATE POLICY business_members_delete_invoices ON public.invoices FOR DELETE TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

DROP POLICY IF EXISTS business_members_insert_invoices ON public.invoices;
CREATE POLICY business_members_insert_invoices ON public.invoices FOR INSERT TO authenticated WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- support_tickets -----------------------------------------------------
DROP POLICY IF EXISTS business_members_insert_support_tickets ON public.support_tickets;
CREATE POLICY business_members_insert_support_tickets ON public.support_tickets FOR INSERT TO authenticated WITH CHECK ((public.is_business_member(auth.uid(), business_id) AND (user_id = auth.uid())));

-- --- calendar_events -----------------------------------------------------
DROP POLICY IF EXISTS business_members_read_calendar_events ON public.calendar_events;
CREATE POLICY business_members_read_calendar_events ON public.calendar_events FOR SELECT TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- calendar_sync_state -------------------------------------------------
DROP POLICY IF EXISTS business_members_read_calendar_sync_state ON public.calendar_sync_state;
CREATE POLICY business_members_read_calendar_sync_state ON public.calendar_sync_state FOR SELECT TO authenticated USING ((public.is_platform_admin(auth.uid()) OR (EXISTS ( SELECT 1
   FROM public.email_accounts ea
  WHERE ((ea.id = calendar_sync_state.email_account_id) AND public.is_business_member(auth.uid(), ea.business_id))))));

-- --- email_accounts ------------------------------------------------------
DROP POLICY IF EXISTS business_members_read_email_accounts ON public.email_accounts;
CREATE POLICY business_members_read_email_accounts ON public.email_accounts FOR SELECT TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- email_briefings -----------------------------------------------------
DROP POLICY IF EXISTS business_members_read_email_briefings ON public.email_briefings;
CREATE POLICY business_members_read_email_briefings ON public.email_briefings FOR SELECT TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- email_drafts --------------------------------------------------------
DROP POLICY IF EXISTS business_members_read_email_drafts ON public.email_drafts;
CREATE POLICY business_members_read_email_drafts ON public.email_drafts FOR SELECT TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- email_messages ------------------------------------------------------
DROP POLICY IF EXISTS business_members_read_email_messages ON public.email_messages;
CREATE POLICY business_members_read_email_messages ON public.email_messages FOR SELECT TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- email_outbox --------------------------------------------------------
DROP POLICY IF EXISTS business_members_read_email_outbox_v2 ON public.email_outbox;
CREATE POLICY business_members_read_email_outbox_v2 ON public.email_outbox FOR SELECT TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- invoices ------------------------------------------------------------
DROP POLICY IF EXISTS business_members_read_invoices ON public.invoices;
CREATE POLICY business_members_read_invoices ON public.invoices FOR SELECT TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- support_tickets -----------------------------------------------------
DROP POLICY IF EXISTS business_members_select_support_tickets ON public.support_tickets;
CREATE POLICY business_members_select_support_tickets ON public.support_tickets FOR SELECT TO authenticated USING (public.is_business_member(auth.uid(), business_id));

-- --- invoices ------------------------------------------------------------
DROP POLICY IF EXISTS business_members_update_invoices ON public.invoices;
CREATE POLICY business_members_update_invoices ON public.invoices FOR UPDATE TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- support_tickets -----------------------------------------------------
DROP POLICY IF EXISTS business_members_update_support_tickets ON public.support_tickets;
CREATE POLICY business_members_update_support_tickets ON public.support_tickets FOR UPDATE TO authenticated USING ((public.is_business_member(auth.uid(), business_id) AND (user_id = auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) AND (user_id = auth.uid()) AND (status = 'closed'::text)));

-- --- calls ---------------------------------------------------------------
DROP POLICY IF EXISTS calls_select_if_member ON public.calls;
CREATE POLICY calls_select_if_member ON public.calls FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = calls.business_id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))));

-- --- email_connections ---------------------------------------------------
DROP POLICY IF EXISTS email_connections_member_access ON public.email_connections;
CREATE POLICY email_connections_member_access ON public.email_connections TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- email_sync_states ---------------------------------------------------
DROP POLICY IF EXISTS email_sync_states_member_access ON public.email_sync_states;
CREATE POLICY email_sync_states_member_access ON public.email_sync_states TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.email_accounts ea
  WHERE ((ea.id = email_sync_states.email_account_id) AND (public.is_business_member(auth.uid(), ea.business_id) OR public.is_platform_admin(auth.uid())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM public.email_accounts ea
  WHERE ((ea.id = email_sync_states.email_account_id) AND (public.is_business_member(auth.uid(), ea.business_id) OR public.is_platform_admin(auth.uid()))))));

-- --- financial_summary_cache ---------------------------------------------
DROP POLICY IF EXISTS financial_summary_cache_member_access ON public.financial_summary_cache;
CREATE POLICY financial_summary_cache_member_access ON public.financial_summary_cache TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- knowledge_base_items ------------------------------------------------
DROP POLICY IF EXISTS knowledge_base_items_member_access ON public.knowledge_base_items;
CREATE POLICY knowledge_base_items_member_access ON public.knowledge_base_items TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- businesses ----------------------------------------------------------
DROP POLICY IF EXISTS "members can read their businesses" ON public.businesses;
CREATE POLICY "members can read their businesses" ON public.businesses FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))));

-- --- oauth_tokens --------------------------------------------------------
DROP POLICY IF EXISTS oauth_tokens_member_access ON public.oauth_tokens;
CREATE POLICY oauth_tokens_member_access ON public.oauth_tokens TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- calendar_events -----------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_calendar_events ON public.calendar_events;
CREATE POLICY platform_admins_full_access_calendar_events ON public.calendar_events TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- calendar_sync_state -------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_calendar_sync_state ON public.calendar_sync_state;
CREATE POLICY platform_admins_full_access_calendar_sync_state ON public.calendar_sync_state TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- email_accounts ------------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_email_accounts ON public.email_accounts;
CREATE POLICY platform_admins_full_access_email_accounts ON public.email_accounts TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- email_briefings -----------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_email_briefings ON public.email_briefings;
CREATE POLICY platform_admins_full_access_email_briefings ON public.email_briefings TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- email_drafts --------------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_email_drafts ON public.email_drafts;
CREATE POLICY platform_admins_full_access_email_drafts ON public.email_drafts TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- email_messages ------------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_email_messages ON public.email_messages;
CREATE POLICY platform_admins_full_access_email_messages ON public.email_messages TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- email_outbox --------------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_email_outbox_v2 ON public.email_outbox;
CREATE POLICY platform_admins_full_access_email_outbox_v2 ON public.email_outbox TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- invoices ------------------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_invoices ON public.invoices;
CREATE POLICY platform_admins_full_access_invoices ON public.invoices TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- support_tickets -----------------------------------------------------
DROP POLICY IF EXISTS platform_admins_full_access_support_tickets ON public.support_tickets;
CREATE POLICY platform_admins_full_access_support_tickets ON public.support_tickets TO authenticated USING (public.is_platform_admin(auth.uid())) WITH CHECK (public.is_platform_admin(auth.uid()));

-- --- platform_admins -----------------------------------------------------
DROP POLICY IF EXISTS platform_admins_read_own ON public.platform_admins;
CREATE POLICY platform_admins_read_own ON public.platform_admins FOR SELECT TO authenticated USING ((user_id = auth.uid()));

-- --- quote_line_items ----------------------------------------------------
DROP POLICY IF EXISTS quote_line_items_member_access ON public.quote_line_items;
CREATE POLICY quote_line_items_member_access ON public.quote_line_items TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.quotes q
  WHERE ((q.id = quote_line_items.quote_id) AND (public.is_business_member(auth.uid(), q.business_id) OR public.is_platform_admin(auth.uid())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM public.quotes q
  WHERE ((q.id = quote_line_items.quote_id) AND (public.is_business_member(auth.uid(), q.business_id) OR public.is_platform_admin(auth.uid()))))));

-- --- quote_settings ------------------------------------------------------
DROP POLICY IF EXISTS quote_settings_member_access ON public.quote_settings;
CREATE POLICY quote_settings_member_access ON public.quote_settings TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- quotes --------------------------------------------------------------
DROP POLICY IF EXISTS quotes_member_access ON public.quotes;
CREATE POLICY quotes_member_access ON public.quotes TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- receptionist_configs ------------------------------------------------
DROP POLICY IF EXISTS receptionist_configs_member_access ON public.receptionist_configs;
CREATE POLICY receptionist_configs_member_access ON public.receptionist_configs TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- stripe_events -------------------------------------------------------
DROP POLICY IF EXISTS stripe_events_member_access ON public.stripe_events;
CREATE POLICY stripe_events_member_access ON public.stripe_events TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- support_conversations -----------------------------------------------
DROP POLICY IF EXISTS support_conversations_member_access ON public.support_conversations;
CREATE POLICY support_conversations_member_access ON public.support_conversations TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- support_messages ----------------------------------------------------
DROP POLICY IF EXISTS support_messages_member_access ON public.support_messages;
CREATE POLICY support_messages_member_access ON public.support_messages TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.support_conversations sc
  WHERE ((sc.id = support_messages.conversation_id) AND (public.is_business_member(auth.uid(), sc.business_id) OR public.is_platform_admin(auth.uid())))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM public.support_conversations sc
  WHERE ((sc.id = support_messages.conversation_id) AND (public.is_business_member(auth.uid(), sc.business_id) OR public.is_platform_admin(auth.uid()))))));

-- --- tasks ---------------------------------------------------------------
DROP POLICY IF EXISTS tasks_delete_if_owner ON public.tasks;
CREATE POLICY tasks_delete_if_owner ON public.tasks FOR DELETE TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = tasks.business_id) AND (bm.user_id = auth.uid()) AND (bm.role = 'owner'::text) AND (bm.is_active = true)))));

DROP POLICY IF EXISTS tasks_insert_if_member ON public.tasks;
CREATE POLICY tasks_insert_if_member ON public.tasks FOR INSERT TO authenticated WITH CHECK ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = tasks.business_id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))));

DROP POLICY IF EXISTS tasks_select_if_member ON public.tasks;
CREATE POLICY tasks_select_if_member ON public.tasks FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = tasks.business_id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))));

DROP POLICY IF EXISTS tasks_update_if_member ON public.tasks;
CREATE POLICY tasks_update_if_member ON public.tasks FOR UPDATE TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = tasks.business_id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM public.business_members bm
  WHERE ((bm.business_id = tasks.business_id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))));

-- --- business_members ----------------------------------------------------
DROP POLICY IF EXISTS users_link_self ON public.business_members;
CREATE POLICY users_link_self ON public.business_members FOR UPDATE TO authenticated USING (((invited_email = auth.email()) AND (user_id IS NULL))) WITH CHECK ((invited_email = auth.email()));

DROP POLICY IF EXISTS users_view_own ON public.business_members;
CREATE POLICY users_view_own ON public.business_members FOR SELECT TO authenticated USING (((user_id = auth.uid()) OR (invited_email = auth.email())));

-- --- whatsapp_configs ----------------------------------------------------
DROP POLICY IF EXISTS whatsapp_configs_member_access ON public.whatsapp_configs;
CREATE POLICY whatsapp_configs_member_access ON public.whatsapp_configs TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- whatsapp_messages ---------------------------------------------------
DROP POLICY IF EXISTS whatsapp_messages_member_access ON public.whatsapp_messages;
CREATE POLICY whatsapp_messages_member_access ON public.whatsapp_messages TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- whatsapp_pending_actions --------------------------------------------
DROP POLICY IF EXISTS whatsapp_pending_actions_member_access ON public.whatsapp_pending_actions;
CREATE POLICY whatsapp_pending_actions_member_access ON public.whatsapp_pending_actions TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

-- --- xero_connections ----------------------------------------------------
DROP POLICY IF EXISTS xero_connections_member_access ON public.xero_connections;
CREATE POLICY xero_connections_member_access ON public.xero_connections TO authenticated USING ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid()))) WITH CHECK ((public.is_business_member(auth.uid(), business_id) OR public.is_platform_admin(auth.uid())));

