import { QueryClient, QueryFunction } from "@tanstack/react-query";
import { config } from "@/config/env";
import { supabase } from "@/lib/supabase";

async function throwIfResNotOk(res: Response) {
  if (!res.ok) {
    const text = (await res.text()) || res.statusText;
    throw new Error(`${res.status}: ${text}`);
  }
}

/**
 * Resolves a URL for backend API calls.
 * If the URL starts with /v1/ or v1/, prepends the API base URL.
 * Otherwise, returns the URL as-is (for relative URLs like /api/...).
 */
function resolveApiUrl(url: string): string {
  if (url.startsWith("/v1/") || url.startsWith("v1/")) {
    // Ensure we have the leading slash for proper URL construction
    const path = url.startsWith("/") ? url : `/${url}`;
    return `${config.apiBaseUrl}${path}`;
  }
  return url;
}

/**
 * Get authorization headers with Supabase access token.
 */
async function getAuthHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  
  try {
    const { data: { session } } = await supabase.auth.getSession();
    if (session?.access_token) {
      headers["Authorization"] = `Bearer ${session.access_token}`;
    }
  } catch (error) {
    console.error("Failed to get Supabase session:", error);
  }
  
  return headers;
}

export async function apiRequest(
  method: string,
  url: string,
  data?: unknown | undefined,
): Promise<Response> {
  const resolvedUrl = resolveApiUrl(url);

  const makeRequest = async () => {
    const authHeaders = await getAuthHeaders();
    const headers: Record<string, string> = { ...authHeaders };
    if (data) {
      headers["Content-Type"] = "application/json";
    }
    return fetch(resolvedUrl, {
      method,
      headers,
      body: data ? JSON.stringify(data) : undefined,
    });
  };

  let res = await makeRequest();

  // If 401, try refreshing the token and retry once
  if (res.status === 401) {
    try {
      const { error } = await supabase.auth.refreshSession();
      if (!error) {
        res = await makeRequest();
      }
    } catch {}
  }

  await throwIfResNotOk(res);
  return res;
}

type UnauthorizedBehavior = "returnNull" | "throw";
export const getQueryFn: <T>(options: {
  on401: UnauthorizedBehavior;
}) => QueryFunction<T> =
  ({ on401: unauthorizedBehavior }) =>
  async ({ queryKey }) => {
    const url = queryKey.join("/") as string;
    const resolvedUrl = resolveApiUrl(url);

    const makeRequest = async () => {
      const authHeaders = await getAuthHeaders();
      return fetch(resolvedUrl, { headers: authHeaders });
    };

    let res = await makeRequest();

    // If 401, try refreshing the token and retry once
    if (res.status === 401) {
      try {
        const { error } = await supabase.auth.refreshSession();
        if (!error) {
          res = await makeRequest();
        }
      } catch {}
    }

    if (unauthorizedBehavior === "returnNull" && res.status === 401) {
      return null;
    }

    await throwIfResNotOk(res);
    return await res.json();
  };

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      queryFn: getQueryFn({ on401: "throw" }),
      staleTime: 5 * 60 * 1000,
      gcTime: 30 * 60 * 1000,
      refetchOnWindowFocus: false,
      refetchOnMount: false,
      refetchInterval: false,
      retry: (failureCount, error: any) => {
        const status = error?.status ?? parseInt(error?.message, 10);
        if (status === 401 || status === 403) return false;
        return failureCount < 1;
      },
    },
    mutations: {
      retry: false,
    },
  },
});
