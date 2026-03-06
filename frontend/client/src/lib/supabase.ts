import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  const missing = [];
  if (!supabaseUrl) missing.push('VITE_SUPABASE_URL');
  if (!supabaseAnonKey) missing.push('VITE_SUPABASE_ANON_KEY');
  throw new Error(
    `Missing required Supabase environment variables: ${missing.join(', ')}. ` +
    `Please set these in your .env file or deployment environment.`
  );
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

/**
 * Resolves a logo URL to a public URL for display.
 * 
 * - Returns null if logoUrl is empty/null/undefined
 * - Returns logoUrl unchanged if it already starts with "http" (full URL)
 * - Otherwise treats logoUrl as a Supabase Storage path in bucket "logos"
 *   and converts it to a public URL
 * 
 * @param logoUrl - The logo URL from the database (can be a storage path or full URL)
 * @returns The resolved public URL or null
 */
export function resolveLogoSrc(logoUrl: string | null | undefined): string | null {
  if (!logoUrl) return null;
  
  // If it's already a full URL (http/https), return as-is
  if (logoUrl.startsWith('http://') || logoUrl.startsWith('https://')) {
    return logoUrl;
  }
  
  // Construct the public URL directly for the logos bucket
  // Format: {supabase_url}/storage/v1/object/public/logos/{path}
  const baseUrl = supabaseUrl || 'https://oxblcmwhuwtobdhsfgyi.supabase.co';
  return `${baseUrl}/storage/v1/object/public/logos/${logoUrl}`;
}

export interface Business {
  id: string;
  name: string;
  timezone: string;
  api_key: string;
  logo_url: string | null;
  created_at: string;
  plan_tier?: string;
  is_active?: boolean;
  trial_ends_at?: string | null;
  feature_flags?: Record<string, any>;
  limits?: Record<string, any>;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
  subscription_status?: string | null;
  current_period_end?: string | null;
  cancel_at_period_end?: boolean;
  last_stripe_event_at?: string | null;
}

export interface BusinessMember {
  id: string;
  business_id: string;
  user_id: string | null;
  role: string;
  is_active: boolean;
  invited_email: string;
  accepted_at: string | null;
  created_at: string;
}

export interface Task {
  id: string;
  business_id: string;
  title: string;
  description: string | null;
  due_at: string | null;
  recurrence: string;
  status: string;
  source: string;
  category: string;
  priority: string;
  source_id: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Call {
  id: string;
  business_id: string;
  caller_name: string;
  caller_number: string;
  phone_number?: string;
  notes?: string;
  summary?: string;
  intent?: string;
  archived?: boolean;
  created_at: string;
  source?: string;
  outcome?: string;
  duration_seconds?: number | null;
  transcript?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  recording_url?: string | null;
}

export interface PlatformAdmin {
  id: string;
  user_id: string;
  created_at: string;
}
