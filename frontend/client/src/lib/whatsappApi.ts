/**
 * WhatsApp CEO Briefing and Automation API helpers.
 */

import { apiRequest } from '@/lib/queryClient';

export interface WhatsAppConfig {
  configured: boolean;
  id?: string;
  business_id?: string;
  phone_number?: string;
  enabled?: boolean;
  timezone?: string;
  owner_name?: string;
  daily_pulse_enabled?: boolean;
  daily_pulse_time?: string;
  weekly_briefing_enabled?: boolean;
  weekly_briefing_day?: string;
  weekly_briefing_time?: string;
  preferred_detail_level?: string;
  real_time_alerts_enabled?: boolean;
  alert_receptionist_transfers?: boolean;
  alert_payment_received_threshold?: number;
  alert_urgent_emails?: boolean;
  alert_bank_balance_threshold?: number;
  alert_invoice_overdue_days?: number;
  task_reminder_enabled?: boolean;
  task_reminder_frequency?: string;
  task_reminder_time?: string;
  created_at?: string;
  updated_at?: string;
}

export interface WhatsAppMessage {
  id: string;
  direction: string;
  message_type: string;
  phone_number: string;
  content: string | null;
  twilio_message_sid: string | null;
  twilio_status: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  created_at: string | null;
}

export interface AutomationRule {
  id: string;
  business_id: string;
  name: string;
  description: string;
  trigger_type: string;
  conditions: Record<string, any>;
  action_type: string;
  action_config: Record<string, any>;
  requires_approval: boolean;
  is_active: boolean;
  last_triggered_at: string | null;
  total_executions: number;
  created_at: string;
  updated_at: string;
}

export async function fetchWhatsAppConfig(): Promise<WhatsAppConfig> {
  const res = await apiRequest('GET', '/v1/whatsapp/config');
  return res.json();
}

export async function saveWhatsAppConfig(config: Partial<WhatsAppConfig>): Promise<WhatsAppConfig> {
  const res = await apiRequest('PUT', '/v1/whatsapp/config', config);
  return res.json();
}

export async function sendTestBriefing(): Promise<{ sent: boolean; message_sid?: string }> {
  const res = await apiRequest('POST', '/v1/whatsapp/send-weekly-briefing');
  return res.json();
}

export async function sendTestPulse(): Promise<{ sent: boolean; message_sid?: string }> {
  const res = await apiRequest('POST', '/v1/whatsapp/send-daily-pulse');
  return res.json();
}

export async function sendTestTaskReminder(): Promise<{ status: string }> {
  const res = await apiRequest('POST', '/v1/whatsapp/send-task-reminder');
  return res.json();
}

export async function fetchWhatsAppMessages(limit = 20): Promise<WhatsAppMessage[]> {
  const res = await apiRequest('GET', `/v1/whatsapp/messages?limit=${limit}`);
  return res.json();
}

export async function fetchAutomationRules(): Promise<AutomationRule[]> {
  const res = await apiRequest('GET', '/v1/automation/rules');
  return res.json();
}

export async function provisionDefaultRules(): Promise<{ status: string; count: number }> {
  const res = await apiRequest('POST', '/v1/automation/provision-defaults');
  return res.json();
}

export async function updateAutomationRule(
  ruleId: string,
  updates: Partial<AutomationRule>
): Promise<AutomationRule> {
  const res = await apiRequest('PUT', `/v1/automation/rules/${ruleId}`, updates);
  return res.json();
}

// Admin APIs
export async function fetchAdminWhatsAppOverview(): Promise<any[]> {
  const res = await apiRequest('GET', '/v1/admin/whatsapp/overview');
  return res.json();
}

export async function updateAdminWhatsAppConfig(
  businessId: string,
  config: Partial<WhatsAppConfig>
): Promise<WhatsAppConfig> {
  const res = await apiRequest('PUT', `/v1/admin/whatsapp/${businessId}/config`, config);
  return res.json();
}
