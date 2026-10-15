import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/queryClient';
import { supabase } from '@/lib/supabase';
import type { Usage } from '@/components/ReceptionistUsage';
import type { Proposal } from '@/components/ApprovalCard';

/**
 * NS-B7 — the Aria home's figures, shared by the hero (briefing) and the page
 * (tiles), so each is fetched once (react-query de-duplicates by key). Every
 * figure comes from the business's own data (North Star P2): nothing here is
 * estimated, and a query that fails reports `undefined`, never zero.
 */
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
    staleTime: 3 * 60 * 1000,
  });

  const emails = useQuery({
    queryKey: ['dashboard-emails', businessId],
    queryFn: async () => {
      const res = await apiRequest('GET', '/v1/email/messages?limit=200');
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data.messages || []);
      const todayDate = new Date().toDateString();
      return {
        emailsToday: list.filter((e: any) => e.received_at && new Date(e.received_at).toDateString() === todayDate).length,
        emailsActionRequired: list.filter((e: any) => e.ai_category === 'Action Required').length,
      };
    },
    enabled,
    staleTime: 3 * 60 * 1000,
  });

  const invoices = useQuery({
    queryKey: ['dashboard-invoices', businessId],
    queryFn: async () => {
      const res = await apiRequest('GET', '/v1/invoices');
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data.invoices || []);
      const unpaid = list.filter((i: any) => ['unpaid', 'authorised', 'sent'].includes(i.status) && !i.archived);
      const today = new Date().toISOString().slice(0, 10);
      const overdue = unpaid.filter((i: any) => i.due_date && i.due_date < today);
      const owed = (rows: any[]) => rows.reduce((sum: number, i: any) =>
        sum + (parseFloat(i.amount_due) || parseFloat(i.amount) || 0), 0);
      return {
        unpaidCount: unpaid.length,
        unpaidAmount: owed(unpaid),
        overdueCount: overdue.length,
        overdueAmount: owed(overdue),
      };
    },
    enabled,
    staleTime: 5 * 60 * 1000,
  });

  const tasks = useQuery({
    queryKey: ['dashboard-tasks', businessId],
    queryFn: async () => {
      const { data: rows, error } = await supabase
        .from('tasks')
        .select('status, priority')
        .eq('business_id', businessId!)
        .is('deleted_at', null);
      if (error || !rows) throw error || new Error('No tasks');
      const open = rows.filter(t => t.status !== 'completed' && t.status !== 'done');
      return { openTasks: open.length, highPriorityTasks: open.filter(t => t.priority === 'high').length };
    },
    enabled,
    staleTime: 3 * 60 * 1000,
  });

  const usage = useQuery({
    queryKey: ['dashboard-usage', businessId],
    queryFn: async (): Promise<Usage> => (await apiRequest('GET', '/v1/usage')).json(),
    enabled,
    staleTime: 3 * 60 * 1000,
  });

  const actions = useQuery({
    queryKey: ['aria-actions', businessId],
    queryFn: async (): Promise<Proposal[]> => {
      const data = await (await apiRequest('GET', '/v1/aria/actions')).json();
      return data.actions || [];
    },
    enabled,
    staleTime: 60 * 1000,
  });

  return { calls, emails, invoices, tasks, usage, actions };
}

const money = (n: number) => `£${n.toLocaleString('en-GB', { maximumFractionDigits: 0 })}`;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * Aria's opening lines, built only from figures that loaded. A figure that
 * is still loading or failed is left out rather than guessed (P2, P8).
 */
export function briefingLines(d: ReturnType<typeof useDashboardData>): string[] {
  const lines: string[] = [];
  const cards = d.actions.data?.length ?? 0;
  if (cards > 0) {
    lines.push(`${plural(cards, 'draft is', 'drafts are')} waiting for your approval below.`);
  }
  const inv = d.invoices.data;
  if (inv && inv.overdueCount > 0) {
    lines.push(`${plural(inv.overdueCount, 'invoice is', 'invoices are')} overdue, ${money(inv.overdueAmount)} in total.`);
  } else if (inv && inv.unpaidCount > 0) {
    lines.push(`${money(inv.unpaidAmount)} is outstanding across ${plural(inv.unpaidCount, 'invoice', 'invoices')}, none overdue.`);
  }
  const em = d.emails.data;
  if (em && em.emailsActionRequired > 0) {
    lines.push(`${plural(em.emailsActionRequired, 'email needs', 'emails need')} a reply.`);
  }
  const calls = d.calls.data;
  if (calls && calls.callsToday > 0) {
    lines.push(`${plural(calls.callsToday, 'call', 'calls')} came in today.`);
  }
  return lines;
}
