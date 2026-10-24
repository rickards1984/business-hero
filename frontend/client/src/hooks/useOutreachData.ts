import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiRequest } from '@/lib/queryClient';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/AuthContext';

export type OutreachRecord = Record<string, any>;
export interface OutreachResult { item?: OutreachRecord | null; items?: OutreachRecord[]; total?: number; data_quality?: string; message?: string; totals?: Record<string, number>; sources?: Record<string, string>; as_of?: string }
const LIVE = { staleTime: 30000, refetchOnMount: 'always' as const, refetchOnWindowFocus: true, retry: false };
export function useOutreachData(businessId: string | undefined, path: string, enabled = true) {
  return useQuery<OutreachResult>({ queryKey: ['outreach', businessId, path], enabled: !!businessId && enabled,
    queryFn: async () => (await apiRequest('GET', `/v1/outreach/${path}`)).json(), ...LIVE });
}
export function useOutreachSummary(businessId?: string) { return useOutreachData(businessId, 'summary'); }
export function useOutreachOwner(businessId?: string) {
  const { user } = useAuth();
  return useQuery({ queryKey: ['outreach-owner', businessId, user?.id], enabled: !!businessId && !!user,
    queryFn: async () => {
      const { data, error } = await supabase.from('business_members').select('role,is_active').eq('business_id', businessId!).eq('user_id', user!.id);
      if (error) throw error;
      return data?.some(m => m.role === 'owner' && m.is_active === true) ?? false;
    }, ...LIVE });
}
export function useRefreshOutreach(businessId: string) {
  const client = useQueryClient();
  return () => { client.invalidateQueries({ queryKey: ['outreach', businessId] }); client.invalidateQueries({ queryKey: ['aria-actions', businessId] }); };
}
export function outreachError(error: unknown) {
  const text = error instanceof Error ? error.message : '';
  if (text.startsWith('403:')) return 'Access denied. These controls require the active business owner and the relevant account access.';
  if (text.startsWith('404:')) return 'This record is unavailable in the current business.';
  if (text.startsWith('409:')) return 'The record changed or this action is blocked. Reload and review the current state before continuing.';
  if (text.startsWith('422:')) return 'Check the entered values. This request was not accepted.';
  return 'Unavailable. Refresh to check the saved state before trying again.';
}
