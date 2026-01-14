import { useQuery } from '@tanstack/react-query';
import { getQueryFn } from '@/lib/queryClient';

export interface BusinessProfile {
  id: string;
  name: string;
  timezone: string;
  logo_url: string | null;
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
