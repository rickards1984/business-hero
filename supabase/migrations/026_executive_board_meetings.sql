-- ============================================================================
-- Migration 026: Executive Board Meetings Feature
-- Tier-gated at the API layer (pro / business / beta). Starter and paused blocked.
-- ============================================================================

-- Per-business settings for the executive meeting feature
CREATE TABLE IF NOT EXISTS executive_meeting_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    -- Schedule
    enabled BOOLEAN DEFAULT TRUE,
    frequency TEXT NOT NULL DEFAULT 'weekly' CHECK (frequency IN ('weekly', 'monthly')),
    day_of_week INTEGER DEFAULT 1 CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Sun, 1=Mon
    day_of_month INTEGER DEFAULT 1 CHECK (day_of_month BETWEEN 1 AND 28),
    meeting_time TIME DEFAULT '09:00',
    timezone TEXT DEFAULT 'Europe/London',

    -- Meeting configuration
    focus_areas JSONB DEFAULT '["financial", "operations", "team", "growth"]'::jsonb,
    -- Possible values: financial, operations, team, growth, marketing, customer_satisfaction, compliance

    custom_agenda_items JSONB DEFAULT '[]'::jsonb,
    -- User-defined recurring agenda items they always want covered

    -- Attendees (advanced tiers only — for v1, we just store names; no auth required)
    attendees JSONB DEFAULT '[]'::jsonb,
    -- Format: [{"name": "Sarah", "role": "Operations Manager", "email": "..."}, ...]

    -- AI behaviour preferences
    directness_level TEXT DEFAULT 'balanced'
        CHECK (directness_level IN ('gentle', 'balanced', 'direct', 'brutally_honest')),
    include_disclaimers BOOLEAN DEFAULT TRUE,

    -- Tracking
    last_meeting_at TIMESTAMP WITH TIME ZONE,
    next_meeting_at TIMESTAMP WITH TIME ZONE,
    total_meetings_completed INTEGER DEFAULT 0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(business_id)
);

CREATE INDEX IF NOT EXISTS idx_exec_meeting_settings_business
    ON executive_meeting_settings(business_id);
CREATE INDEX IF NOT EXISTS idx_exec_meeting_settings_next
    ON executive_meeting_settings(next_meeting_at) WHERE enabled = TRUE;


-- Individual meeting records
CREATE TABLE IF NOT EXISTS executive_meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    -- Status lifecycle
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'prep_ready', 'in_progress', 'completed', 'cancelled', 'failed')),

    -- Timing
    scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL,
    prep_started_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_minutes INTEGER,

    -- Pre-meeting data (gathered ~30 mins before meeting)
    prep_data JSONB DEFAULT '{}'::jsonb,
    -- Contains: financial summary, ops summary, KPIs, period-over-period comparisons,
    -- last meeting recap, outstanding action items, goal progress, flagged concerns

    -- Generated agenda
    agenda JSONB DEFAULT '[]'::jsonb,
    -- Format: [{"section": "Financial Review", "talking_points": [...], "data_refs": [...]}, ...]

    -- Meeting outputs
    summary TEXT,
    key_takeaways JSONB DEFAULT '[]'::jsonb,
    sentiment TEXT CHECK (sentiment IN ('positive', 'neutral', 'concerning', 'critical')),

    -- AI model used (for tracking/cost analysis)
    ai_model TEXT,
    total_tokens_used INTEGER DEFAULT 0,

    -- Owner notes (added during/after meeting)
    owner_notes TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exec_meetings_business ON executive_meetings(business_id);
CREATE INDEX IF NOT EXISTS idx_exec_meetings_status ON executive_meetings(status);
CREATE INDEX IF NOT EXISTS idx_exec_meetings_scheduled ON executive_meetings(scheduled_for);


-- The conversation log for each meeting (every message, both sides)
CREATE TABLE IF NOT EXISTS executive_meeting_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES executive_meetings(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    role TEXT NOT NULL CHECK (role IN ('aria', 'owner', 'system', 'attendee')),
    speaker_name TEXT,

    content TEXT NOT NULL,
    agenda_section TEXT,

    -- Aria-only fields
    referenced_data JSONB DEFAULT '{}'::jsonb,
    suggested_actions JSONB DEFAULT '[]'::jsonb,

    -- Tracking
    tokens_used INTEGER DEFAULT 0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exec_meeting_messages_meeting
    ON executive_meeting_messages(meeting_id, created_at);
CREATE INDEX IF NOT EXISTS idx_exec_meeting_messages_business
    ON executive_meeting_messages(business_id);


-- Action items committed to during meetings — these carry forward
CREATE TABLE IF NOT EXISTS executive_meeting_action_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES executive_meetings(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    title TEXT NOT NULL,
    description TEXT,

    -- Assignment
    assignee_name TEXT,
    assignee_email TEXT,

    -- Status tracking
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'completed', 'blocked', 'deferred', 'cancelled')),
    priority TEXT DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'urgent')),

    -- Dates
    due_date DATE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Context
    rationale TEXT,
    success_criteria TEXT,

    -- Carry-forward tracking
    times_reviewed INTEGER DEFAULT 0,
    last_reviewed_at TIMESTAMP WITH TIME ZONE,

    -- Owner notes
    notes TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exec_action_items_meeting
    ON executive_meeting_action_items(meeting_id);
CREATE INDEX IF NOT EXISTS idx_exec_action_items_business
    ON executive_meeting_action_items(business_id);
CREATE INDEX IF NOT EXISTS idx_exec_action_items_status
    ON executive_meeting_action_items(business_id, status);


-- Longer-term goals set during meetings
CREATE TABLE IF NOT EXISTS executive_meeting_goals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    set_in_meeting_id UUID REFERENCES executive_meetings(id) ON DELETE SET NULL,

    title TEXT NOT NULL,
    description TEXT,

    horizon TEXT NOT NULL CHECK (horizon IN ('short_term', 'medium_term', 'long_term')),
    -- short_term: < 1 month, medium_term: 1-3 months, long_term: 3+ months

    category TEXT,

    -- Measurement
    kpi_name TEXT,
    kpi_target_value NUMERIC,
    kpi_current_value NUMERIC,
    kpi_unit TEXT,

    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'achieved', 'missed', 'cancelled', 'on_hold')),

    target_date DATE,
    achieved_at TIMESTAMP WITH TIME ZONE,

    -- Progress tracking: [{"date": "...", "value": 1000, "note": "..."}, ...]
    progress_history JSONB DEFAULT '[]'::jsonb,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exec_goals_business ON executive_meeting_goals(business_id);
CREATE INDEX IF NOT EXISTS idx_exec_goals_status
    ON executive_meeting_goals(business_id, status);


-- Key decisions made during meetings (for audit/recall)
CREATE TABLE IF NOT EXISTS executive_meeting_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES executive_meetings(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

    decision TEXT NOT NULL,
    context TEXT,
    rationale TEXT,
    aria_recommendation TEXT,
    owner_chose_differently BOOLEAN DEFAULT FALSE,

    -- Outcome tracking (filled in later meetings)
    outcome_status TEXT CHECK (outcome_status IN ('pending', 'positive', 'neutral', 'negative', 'mixed')),
    outcome_notes TEXT,
    outcome_reviewed_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exec_decisions_meeting ON executive_meeting_decisions(meeting_id);
CREATE INDEX IF NOT EXISTS idx_exec_decisions_business ON executive_meeting_decisions(business_id);


-- ============================================================================
-- Updated-at triggers (uses existing public.update_updated_at_column())
-- ============================================================================

DROP TRIGGER IF EXISTS update_executive_meeting_settings_updated_at
    ON executive_meeting_settings;
CREATE TRIGGER update_executive_meeting_settings_updated_at
    BEFORE UPDATE ON executive_meeting_settings
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_executive_meetings_updated_at
    ON executive_meetings;
CREATE TRIGGER update_executive_meetings_updated_at
    BEFORE UPDATE ON executive_meetings
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_executive_meeting_action_items_updated_at
    ON executive_meeting_action_items;
CREATE TRIGGER update_executive_meeting_action_items_updated_at
    BEFORE UPDATE ON executive_meeting_action_items
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_executive_meeting_goals_updated_at
    ON executive_meeting_goals;
CREATE TRIGGER update_executive_meeting_goals_updated_at
    BEFORE UPDATE ON executive_meeting_goals
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
