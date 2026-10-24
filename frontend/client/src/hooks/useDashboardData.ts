import { useOutreachData, useOutreachSummary } from '@/hooks/useOutreachData';
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/queryClient';
import { supabase } from '@/lib/supabase';
import type { Usage } from '@/components/ReceptionistUsage';
import type { Proposal } from '@/components/ApprovalCard';
import type { ChaseReply } from '@/components/ReplyCard';

/**
 * NS-B7 — the Aria home's figures, shared by the hero (briefing) and the page
 * (tiles), so each is fetched once (react-query de-duplicates by key). Every
 * figure comes from the business's own data (North Star P2): nothing here is
 * estimated, and a query that fails is reported as unavailable, never zero.
 */

export interface HomeSummary {
  as_of: string;
  invoices: { outstanding_total: number; outstanding_count: number; overdue_total: number; overdue_count: number };
  emails: { action_required: number; window_days: number };
  synced: { email: string | null; accounting: string | null };
  automated?: Array<{ kind: string; invoice_number?: string; invoice_count?: number; customer_name?: string; stage?: number; sent_at?: string }>;
  replies?: ChaseReply[];  // AUTO-2: replies to chases awaiting the owner
}

export interface HomeTask {
  id: string; title: string; priority?: string | null; due_at?: string | null; source?: string | null;
}

// The home is a live view (Codex NS-B7 review 1, finding 4): the app's
// defaults never refetch, so these refresh on mount, on returning to the
// tab, and every minute.
const LIVE = {
  staleTime: 30 * 1000,
  refetchOnMount: 'always' as const,
  refetchOnWindowFocus: true,
  refetchInterval: 60 * 1000,
};

export function useDashboardData(businessId?: string) {
  const enabled = !!businessId;

  const calls = useQuery({
    queryKey: ['dashboard-calls', businessId],
    queryFn: async () => {
      const { data: rows, error } = await supabase
        .from('calls')
        .select('started_at, created_at, source, outcome')
        .eq('business_id', businessId!)
        .order('created_at', { ascending: false })
        .limit(500);
      if (error || !rows) throw error || new Error('No calls');
      const now = new Date();
      const todayStr = now.toISOString().slice(0, 10);
      const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      const receptionist = rows.filter(c => c.source === 'receptionist');
      const aiHandled = receptionist.filter(c => c.outcome === 'handled').length;
      return {
        callsToday: rows.filter(c => (c.started_at || c.created_at)?.slice(0, 10) === todayStr).length,
        callsThisWeek: rows.filter(c => new Date(c.started_at || c.created_at) >= weekAgo).length,
        aiResolutionRate: receptionist.length > 0 ? Math.round((aiHandled / receptionist.length) * 100) : 0,
      };
    },
    enabled,
    ...LIVE,
  });

  // Invoices and emails are computed on the server over EVERY row, with the
  // time each source last synced (Codex NS-B7 review 1, findings 1, 2, 5, 6).
  // The same receivables feed Aria's invoice summary.
  const summary = useQuery({
    queryKey: ['home-summary', businessId],
    queryFn: async (): Promise<HomeSummary> => (await apiRequest('GET', '/v1/home/summary')).json(),
    enabled,
    ...LIVE,
  });

  const tasks = useQuery({
    queryKey: ['dashboard-tasks', businessId],
    queryFn: async () => {
      const { data: rows, error } = await supabase
        .from('tasks')
        .select('id, title, status, priority, due_at, source')
        .eq('business_id', businessId!)
        .is('deleted_at', null);
      if (error || !rows) throw error || new Error('No tasks');
      const open = rows.filter(t => t.status !== 'completed' && t.status !== 'done');
      const rank = (p?: string | null) => (p === 'high' ? 0 : p === 'medium' ? 1 : 2);
      const upcoming = [...open].sort((a, b) =>
        rank(a.priority) - rank(b.priority)
        || (a.due_at ?? '9999').localeCompare(b.due_at ?? '9999')).slice(0, 6) as HomeTask[];
      return {
        openTasks: open.length,
        highPriorityTasks: open.filter(t => t.priority === 'high').length,
        upcoming,
      };
    },
    enabled,
    ...LIVE,
  });

  const usage = useQuery({
    queryKey: ['dashboard-usage', businessId],
    queryFn: async (): Promise<Usage> => (await apiRequest('GET', '/v1/usage')).json(),
    enabled,
    ...LIVE,
  });

  const actions = useQuery({
    queryKey: ['aria-actions', businessId],
    queryFn: async (): Promise<Proposal[]> => {
      const data = await (await apiRequest('GET', '/v1/aria/actions')).json();
      return data.actions || [];
    },
    enabled,
    ...LIVE,
  });

  const outreach = useOutreachSummary(businessId);
  const outreachPending = useOutreachData(businessId, 'replies?resolution=pending&limit=20&offset=0');
  const outreachHandedOver = useOutreachData(businessId, 'replies?resolution=handed_over&limit=20&offset=0');
  return { calls, summary, tasks, usage, actions, outreach, outreachPending, outreachHandedOver };
}

type Dashboard = ReturnType<typeof useDashboardData>;

const money = (n: number) => `£${n.toLocaleString('en-GB', { maximumFractionDigits: 0 })}`;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * Aria's opening lines, built only from figures that loaded. A figure that
 * is still loading or failed is left out rather than guessed (P2, P8).
 */
export function briefingLines(d: Dashboard): string[] {
  const lines: string[] = [];
  const cards = d.actions.data?.length ?? 0;
  if (cards > 0) {
    lines.push(`${plural(cards, 'draft is', 'drafts are')} waiting for your approval below.`);
  }
  const inv = d.summary.data?.invoices;
  if (inv && inv.overdue_count > 0) {
    lines.push(`${plural(inv.overdue_count, 'invoice is', 'invoices are')} overdue, ${money(inv.overdue_total)} still owed on them.`);
  } else if (inv && inv.outstanding_count > 0) {
    lines.push(`${money(inv.outstanding_total)} is still owed across ${plural(inv.outstanding_count, 'invoice', 'invoices')}, none overdue.`);
  }
  const auto = d.summary.data?.automated ?? [];
  if (auto.length > 0) {
    // AUTO-3: one email can cover several invoices; count the invoices.
    const chased = auto.reduce((n, a) => n + (a.invoice_count ?? 1), 0);
    lines.push(`In the last week I chased ${plural(chased, 'invoice', 'invoices')} for you on autopilot.`);
  }
  const replies = d.summary.data?.replies ?? [];
  // Codex AUTO-2 review 1: count the customers, not their emails.
  const repliedCustomers = new Set(replies.map(r => r.customer_email)).size;
  if (replies.length === 1) {
    const r = replies[0];
    const what = r.category === 'paid' ? 'says they have paid' : 'replied about';
    const which = r.invoice_numbers.length ? r.invoice_numbers.join(', ') : 'an invoice';
    lines.push(`${r.customer_email} ${what} ${which}. I've paused chasing them until you decide, below.`);
  } else if (replies.length > 1) {
    lines.push(repliedCustomers === 1
      ? `${replies[0].customer_email} has replied ${replies.length} times to chases. I've paused chasing them until you decide, below.`
      : `${plural(repliedCustomers, 'customer has', 'customers have')} replied to chases. I've paused chasing them until you decide, below.`);
  }
  const em = d.summary.data?.emails;
  if (em && em.action_required > 0) {
    lines.push(`${plural(em.action_required, 'email needs', 'emails need')} action, from the last ${em.window_days} days.`);
  }
  const tasks = d.tasks.data;
  if (tasks && tasks.highPriorityTasks > 0) {
    lines.push(`${plural(tasks.highPriorityTasks, 'high-priority task is', 'high-priority tasks are')} open.`);
  }
  const calls = d.calls.data;
  if (calls && calls.callsToday > 0) {
    lines.push(`${plural(calls.callsToday, 'call', 'calls')} came in today.`);
  }
  return lines;
}

/** Sources that failed to load, named, so the hero never implies all is well
 *  when it could not check (Codex NS-B7 review 1, finding 3). */
export function unavailable(d: Dashboard): string[] {
  const named: Array<[boolean, string]> = [
    [d.actions.isError, 'your drafts'], [d.summary.isError, 'invoices and email'],
    [d.tasks.isError, 'tasks'], [d.calls.isError, 'calls'],
  ];
  return named.filter(([failed]) => failed).map(([, name]) => name);
}

/** "2 min ago", "3 hours ago", "yesterday" — for a sync timestamp. */
export function ago(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null;
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}
