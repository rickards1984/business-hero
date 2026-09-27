import { useQuery } from '@tanstack/react-query';
import { getQueryFn } from '@/lib/queryClient';

export interface BusinessProfile {
  id: string;
  name: string;
  timezone: string;
  logo_url: string | null;
  brand_color?: string | null;
  plan_tier?: string | null;
  feature_flags?: Record<string, any>;
  /**
   * ENTITLEMENT-SPEC DECISION 3. `subscription_status` is Stripe's value,
   * stored verbatim; `access_level` is what the SERVER resolves from it and
   * enforces (`auth.resolve_access_level`), so the UI renders the same answer
   * the API will act on rather than deriving access a second time.
   *   past_due         -> access_level 'full',      payment_warning true
   *   unpaid, canceled -> access_level 'read_only',  read_only true
   */
  subscription_status?: string | null;
  access_level?: 'full' | 'read_only' | 'suspended' | null;
  payment_warning?: boolean;
  read_only?: boolean;
}

/**
 * Hook to fetch current business profile from GET /v1/me
 * Caches the result with a staleTime of 5 minutes
 */
export function useMe() {
  return useQuery<BusinessProfile>({
    queryKey: ['v1', 'me'],
    queryFn: getQueryFn<BusinessProfile>({ on401: 'throw' }),
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: false,
  });
}
