CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE IF EXISTS public.businesses
    ADD COLUMN IF NOT EXISTS plan_tier text NOT NULL DEFAULT 'starter'
        CHECK (plan_tier IN ('starter','pro','elite','beta','paused')),
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS trial_ends_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS feature_flags jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS limits jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_businesses_plan_tier ON public.businesses (plan_tier);
CREATE INDEX IF NOT EXISTS idx_businesses_is_active ON public.businesses (is_active);

CREATE TABLE IF NOT EXISTS public.support_tickets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title text NOT NULL,
    category text NOT NULL DEFAULT 'general',
    severity text NOT NULL DEFAULT 'normal' CHECK (severity IN ('low','normal','high','urgent')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','resolved','closed')),
    message text NOT NULL,
    page_url text NULL,
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    admin_notes text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_support_tickets_business_created
    ON public.support_tickets (business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status_created
    ON public.support_tickets (status, created_at DESC);

DROP TRIGGER IF EXISTS update_support_tickets_updated_at ON public.support_tickets;
CREATE TRIGGER update_support_tickets_updated_at
    BEFORE UPDATE ON public.support_tickets
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'businesses'
          AND column_name = 'updated_at'
    ) THEN
        DROP TRIGGER IF EXISTS update_businesses_updated_at ON public.businesses;
        CREATE TRIGGER update_businesses_updated_at
            BEFORE UPDATE ON public.businesses
            FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
    END IF;
END $$;

ALTER TABLE public.support_tickets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "platform_admins_full_access_support_tickets" ON public.support_tickets;
CREATE POLICY "platform_admins_full_access_support_tickets"
    ON public.support_tickets
    FOR ALL
    TO authenticated
    USING (is_platform_admin(auth.uid()))
    WITH CHECK (is_platform_admin(auth.uid()));

DROP POLICY IF EXISTS "business_members_select_support_tickets" ON public.support_tickets;
CREATE POLICY "business_members_select_support_tickets"
    ON public.support_tickets
    FOR SELECT
    TO authenticated
    USING (is_business_member(auth.uid(), business_id));

DROP POLICY IF EXISTS "business_members_insert_support_tickets" ON public.support_tickets;
CREATE POLICY "business_members_insert_support_tickets"
    ON public.support_tickets
    FOR INSERT
    TO authenticated
    WITH CHECK (is_business_member(auth.uid(), business_id) AND user_id = auth.uid());

DROP POLICY IF EXISTS "business_members_update_support_tickets" ON public.support_tickets;
CREATE POLICY "business_members_update_support_tickets"
    ON public.support_tickets
    FOR UPDATE
    TO authenticated
    USING (is_business_member(auth.uid(), business_id) AND user_id = auth.uid())
    WITH CHECK (is_business_member(auth.uid(), business_id) AND user_id = auth.uid() AND status = 'closed');
