import { apiRequest } from '@/lib/queryClient';

export interface EmailMessageItem {
  id: string;
  business_id: string;
  email_account_id: string;
  provider_message_id: string;
  provider_thread_id?: string | null;
  folder: string;
  from_email?: string | null;
  from_name?: string | null;
  to_emails?: string[] | null;
  cc_emails?: string[] | null;
  subject?: string | null;
  snippet?: string | null;
  received_at?: string | null;
  is_unread: boolean;
  has_attachments: boolean;
  labels?: string[] | null;
  ai_category?: string | null;
  ai_priority?: number | null;
  ai_summary?: string | null;
  ai_suggested_action?: string | null;
  created_at: string;
  updated_at: string;
}

export interface EmailMessageListResponse {
  messages: EmailMessageItem[];
  total: number;
}

export interface EmailSyncRunResponse {
  email_account_id: string;
  synced: boolean;
  message_count: number;
  cursor: Record<string, unknown>;
}

export interface EmailBriefingItem {
  id: string;
  business_id: string;
  user_id: string;
  email_account_id?: string | null;
  period_start: string;
  period_end: string;
  briefing_markdown: string;
  created_at: string;
}

export interface EmailBriefingListResponse {
  briefings: EmailBriefingItem[];
  total: number;
}

export interface EmailDraftResponse {
  id: string;
  business_id: string;
  email_message_id: string;
  to_emails: string[];
  subject: string;
  body_text?: string | null;
  body_html?: string | null;
  status: string;
  provider_message_id?: string | null;
  tone?: string | null;
  created_at: string;
  updated_at: string;
}

export interface EmailDraftSendResponse {
  success: boolean;
  message: string;
  outbox_id?: string | null;
  provider_message_id?: string | null;
  status?: string | null;
}

export interface EmailAnalysis {
  message_id: string;
  category: string;
  priority: number;
  summary: string;
  suggested_action?: string | null;
}

export interface EmailAnalyzeResponse {
  analyses: EmailAnalysis[];
  analyzed_count: number;
}

export interface EmailDraftOptionsResponse {
  drafts: EmailDraftResponse[];
  message_id: string;
}

export async function fetchEmailMessages(params?: {
  emailAccountId?: string;
  limit?: number;
  category?: string;
  priorityMin?: number;
  sortBy?: string;
}): Promise<EmailMessageListResponse> {
  const search = new URLSearchParams();
  if (params?.emailAccountId) search.set('email_account_id', params.emailAccountId);
  if (params?.limit) search.set('limit', String(params.limit));
  if (params?.category) search.set('category', params.category);
  if (params?.priorityMin) search.set('priority_min', String(params.priorityMin));
  if (params?.sortBy) search.set('sort_by', params.sortBy);
  const query = search.toString();
  const response = await apiRequest('GET', `/v1/email/messages${query ? `?${query}` : ''}`);
  return response.json();
}

export async function runEmailSync(): Promise<EmailSyncRunResponse> {
  const response = await apiRequest('POST', '/v1/email/sync/run');
  return response.json();
}

export async function fetchEmailBriefings(params?: {
  limit?: number;
}): Promise<EmailBriefingListResponse> {
  const search = new URLSearchParams();
  if (params?.limit) search.set('limit', String(params.limit));
  const query = search.toString();
  const response = await apiRequest('GET', `/v1/email/briefings${query ? `?${query}` : ''}`);
  return response.json();
}

export async function generateEmailBriefing(payload?: {
  hours?: number;
  email_account_id?: string;
}): Promise<EmailBriefingItem> {
  const response = await apiRequest('POST', '/v1/email/briefings/generate', payload || {});
  return response.json();
}

export async function generateEmailDraft(payload: {
  email_message_id: string;
  to_emails?: string[];
}): Promise<EmailDraftResponse> {
  const response = await apiRequest('POST', '/v1/email/drafts/generate', payload);
  return response.json();
}

export async function generateDraftOptions(payload: {
  email_message_id: string;
  to_emails?: string[];
}): Promise<EmailDraftOptionsResponse> {
  const response = await apiRequest('POST', '/v1/email/drafts/generate-options', payload);
  return response.json();
}

export async function sendEmailDraft(id: string): Promise<EmailDraftSendResponse> {
  const response = await apiRequest('POST', `/v1/email/drafts/${id}/send`);
  return response.json();
}

export async function analyzeEmails(messageIds?: string[]): Promise<EmailAnalyzeResponse> {
  const response = await apiRequest('POST', '/v1/email/analyze', {
    message_ids: messageIds || [],
  });
  return response.json();
}
