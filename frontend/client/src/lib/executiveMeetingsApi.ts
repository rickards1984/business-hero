/**
 * Executive Board Meeting API client.
 *
 * Wraps every endpoint from backend/executive_meeting_api.py.
 * Uses the existing `apiRequest` pattern (Supabase JWT auto-injected,
 * 401 retry-on-refresh). Tier checks happen server-side.
 */

import { apiRequest } from '@/lib/queryClient';

// ----------------------------------------------------------------------------
// Types — mirror backend Prompt 1/2/3 shapes
// ----------------------------------------------------------------------------

export type Frequency = 'weekly' | 'monthly';

export type DirectnessLevel = 'gentle' | 'balanced' | 'direct' | 'brutally_honest';

export type MeetingStatus =
  | 'scheduled'
  | 'prep_ready'
  | 'in_progress'
  | 'completed'
  | 'cancelled'
  | 'failed';

export type Sentiment = 'positive' | 'neutral' | 'concerning' | 'critical';

export type Priority = 'low' | 'medium' | 'high' | 'urgent';

export type ActionItemStatus =
  | 'open'
  | 'in_progress'
  | 'completed'
  | 'blocked'
  | 'deferred'
  | 'cancelled';

export type GoalHorizon = 'short_term' | 'medium_term' | 'long_term';

export type GoalStatus = 'active' | 'achieved' | 'missed' | 'cancelled' | 'on_hold';

export interface Attendee {
  name: string;
  role?: string;
  email?: string;
}

export interface ExecutiveMeetingSettings {
  id?: string;
  business_id?: string;
  enabled: boolean;
  frequency: Frequency;
  day_of_week: number;
  day_of_month: number;
  meeting_time: string;
  timezone: string;
  focus_areas: string[];
  custom_agenda_items: string[];
  attendees: Attendee[];
  directness_level: DirectnessLevel;
  include_disclaimers: boolean;
  next_meeting_at?: string | null;
  last_meeting_at?: string | null;
  total_meetings_completed?: number;
  is_default?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ExecutiveMeeting {
  id: string;
  business_id: string;
  status: MeetingStatus;
  scheduled_for: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_minutes?: number | null;
  prep_data?: PrepData | null;
  summary?: string | null;
  sentiment?: Sentiment | null;
  total_tokens_used?: number;
  ai_model?: string | null;
  owner_notes?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface MeetingMessage {
  id: string;
  role: 'aria' | 'owner' | 'system' | 'attendee';
  speaker_name?: string | null;
  content: string;
  agenda_section?: string | null;
  tokens_used?: number;
  created_at: string;
}

export interface ActionItem {
  id: string;
  meeting_id: string;
  business_id: string;
  title: string;
  description?: string | null;
  assignee_name?: string | null;
  assignee_email?: string | null;
  status: ActionItemStatus;
  priority: Priority;
  due_date?: string | null;
  completed_at?: string | null;
  rationale?: string | null;
  success_criteria?: string | null;
  times_reviewed?: number;
  last_reviewed_at?: string | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface Goal {
  id: string;
  business_id?: string;
  set_in_meeting_id?: string | null;
  title: string;
  description?: string | null;
  horizon: GoalHorizon;
  category?: string | null;
  kpi_name?: string | null;
  kpi_target_value?: number | null;
  kpi_current_value?: number | null;
  kpi_unit?: string | null;
  status: GoalStatus;
  target_date?: string | null;
  achieved_at?: string | null;
  progress_history?: Array<{ date: string; value: number; note?: string }>;
  created_at?: string;
  updated_at?: string;
}

export interface AccessCheck {
  has_access: boolean;
  has_advanced: boolean;
  current_tier: string;
  required_tier?: string | null;
  feature_name: string;
}

// PrepData is a deep structure — we keep it flexible. Specific fields the UI
// reads are typed here; the rest is passed through as-is.
export interface PrepData {
  schema_version?: string;
  generated_at?: string;
  generation_duration_ms?: number;
  ai_model?: string;
  business?: {
    id?: string;
    name?: string;
    tier?: string;
    industry?: string | null;
    owner_name?: string | null;
    joined_at?: string | null;
    founded_or_joined_at?: string | null;
  };
  period?: {
    type?: string;
    timezone?: string;
    comparison_label?: string;
    current_start?: string;
    current_end?: string;
    previous_start?: string;
    previous_end?: string;
  };
  financials?: any;
  invoices?: any;
  operations?: any;
  goals?: any;
  action_items?: any;
  last_meeting?: any;
  flagged_concerns?: Array<any>;
  owner_context?: any;
  data_quality?: {
    completeness_score?: number;
    missing_sources?: string[];
    stale_sources?: string[];
    errors_during_prep?: string[];
  };
  [key: string]: any;
}

// ----------------------------------------------------------------------------
// Response shapes
// ----------------------------------------------------------------------------

export interface StartNowResponse {
  meeting_id: string;
  status: string;
  scheduled_for?: string;
  completeness_score?: number | null;
}

export interface StartMeetingResponse {
  meeting_id: string;
  opening_message: string;
  tokens_used: number;
  agenda_section?: string;
}

export interface SendMessageResponse {
  meeting_id: string;
  role: 'aria';
  content: string;
  tokens_used: number;
  soft_cap_warning?: boolean;
}

export interface EndMeetingResponse {
  meeting_id: string;
  summary: string | null;
  key_takeaways: string[];
  sentiment: Sentiment | null;
  action_items_count: number;
  goals_count: number;
  decisions_count: number;
  duration_minutes?: number | null;
  next_meeting_at?: string | null;
  extraction_error?: string | null;
  summary_error?: string | null;
}

// ----------------------------------------------------------------------------
// Endpoints
// ----------------------------------------------------------------------------

const BASE = '/v1/executive-meetings';

export async function checkAccess(): Promise<AccessCheck> {
  const res = await apiRequest('GET', `${BASE}/access-check`);
  return res.json();
}

export async function getSettings(): Promise<ExecutiveMeetingSettings> {
  const res = await apiRequest('GET', `${BASE}/settings`);
  return res.json();
}

export async function updateSettings(
  settings: Partial<ExecutiveMeetingSettings>,
): Promise<ExecutiveMeetingSettings> {
  const res = await apiRequest('PUT', `${BASE}/settings`, settings);
  return res.json();
}

export async function listMeetings(limit = 20): Promise<ExecutiveMeeting[]> {
  const res = await apiRequest('GET', `${BASE}/meetings?limit=${limit}`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function getMeetingMessages(meetingId: string): Promise<MeetingMessage[]> {
  const res = await apiRequest('GET', `${BASE}/${meetingId}/messages`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function getMeetingPrepData(meetingId: string): Promise<{
  meeting_id: string;
  business_id: string;
  status: MeetingStatus;
  scheduled_for: string | null;
  prep_started_at: string | null;
  ai_model: string | null;
  prep_data: PrepData | null;
}> {
  const res = await apiRequest('GET', `${BASE}/${meetingId}/prep-data`);
  return res.json();
}

export async function prepNow(): Promise<PrepData> {
  const res = await apiRequest('POST', `${BASE}/prep-now`);
  return res.json();
}

export async function startNow(): Promise<StartNowResponse> {
  const res = await apiRequest('POST', `${BASE}/start-now`);
  return res.json();
}

export async function startMeeting(meetingId: string): Promise<StartMeetingResponse> {
  const res = await apiRequest('POST', `${BASE}/${meetingId}/start`);
  return res.json();
}

export async function sendMessage(
  meetingId: string,
  content: string,
): Promise<SendMessageResponse> {
  const res = await apiRequest('POST', `${BASE}/${meetingId}/message`, { content });
  return res.json();
}

export async function endMeeting(meetingId: string): Promise<EndMeetingResponse> {
  const res = await apiRequest('POST', `${BASE}/${meetingId}/end`);
  return res.json();
}

export async function listActionItems(status?: string): Promise<ActionItem[]> {
  const url = status
    ? `${BASE}/action-items?status=${encodeURIComponent(status)}`
    : `${BASE}/action-items`;
  const res = await apiRequest('GET', url);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function updateActionItem(
  itemId: string,
  updates: Partial<ActionItem>,
): Promise<ActionItem> {
  const res = await apiRequest('PUT', `${BASE}/action-items/${itemId}`, updates);
  return res.json();
}

export async function listGoals(status?: string): Promise<Goal[]> {
  const url = status
    ? `${BASE}/goals?status=${encodeURIComponent(status)}`
    : `${BASE}/goals`;
  const res = await apiRequest('GET', url);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function updateGoal(
  goalId: string,
  updates: Partial<Goal>,
): Promise<Goal> {
  const res = await apiRequest('PUT', `${BASE}/goals/${goalId}`, updates);
  return res.json();
}

// ----------------------------------------------------------------------------
// Admin-only
// ----------------------------------------------------------------------------

export interface AdminMeetingOverviewRow {
  id: string | null;
  business_id: string | null;
  business_name: string | null;
  plan_tier: string | null;
  enabled: boolean;
  frequency: string | null;
  next_meeting_at: string | null;
  last_meeting_at: string | null;
  total_meetings_completed: number | null;
  updated_at: string | null;
}

export async function adminMeetingsOverview(): Promise<AdminMeetingOverviewRow[]> {
  const res = await apiRequest('GET', `${BASE}/admin/overview`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

// ----------------------------------------------------------------------------
// Small UK-style formatters used throughout the UI
// ----------------------------------------------------------------------------

export function formatGBP(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value as number)) return '—';
  return new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency: 'GBP',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value as number);
}

export function formatUKDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-GB', {
      weekday: 'short',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function formatUKDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

export function daysRemaining(targetIso: string | null | undefined): number | null {
  if (!targetIso) return null;
  try {
    const target = new Date(targetIso);
    const now = new Date();
    const ms = target.getTime() - now.getTime();
    return Math.floor(ms / (1000 * 60 * 60 * 24));
  } catch {
    return null;
  }
}
