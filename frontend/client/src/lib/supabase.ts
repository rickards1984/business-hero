import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || '';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

if (!supabaseUrl || !supabaseAnonKey) {
  console.error('Missing Supabase environment variables:', {
    hasUrl: !!supabaseUrl,
    hasKey: !!supabaseAnonKey
  });
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export interface Business {
  id: string;
  name: string;
  timezone: string;
  api_key: string;
  created_at: string;
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
  description: string;
  status: 'pending' | 'completed';
  created_at: string;
}

export interface Call {
  id: string;
  business_id: string;
  caller_name: string;
  phone_number: string;
  notes: string;
  created_at: string;
}

export interface PlatformAdmin {
  id: string;
  user_id: string;
  created_at: string;
}
