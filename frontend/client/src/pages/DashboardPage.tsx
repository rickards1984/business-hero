import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMe } from '@/hooks/useMe';
import { useIsMobile } from '@/hooks/use-mobile';
import { apiRequest } from '@/lib/queryClient';
import { supabase } from '@/lib/supabase';
import { runEmailSync } from '@/lib/emailApi';
import TasksPanel from '@/components/TasksPanel';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

function formatDate(): string {
  return new Date().toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

interface DashboardStats {
  callsToday: number;
  callsThisWeek: number;
  emailsToday: number;
  emailsActionRequired: number;
  unpaidInvoices: number;
  unpaidAmount: number;
  overdueInvoices: number;
  aiResolutionRate: number;
  openTasks: number;
  highPriorityTasks: number;
}

export default function DashboardPage() {
  const { data: me } = useMe();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [showTasks, setShowTasks] = useState(false);
  const [ownerName, setOwnerName] = useState<string>('');

  useEffect(() => {
    const fetchOwnerName = async () => {
      try {
        const res = await apiRequest('GET', '/v1/whatsapp/config');
        const config = await res.json();
        if (config?.owner_name) setOwnerName(config.owner_name);
      } catch {}
    };
    fetchOwnerName();
  }, []);

  useEffect(() => {
    if (!me?.id) return;

    const fetchStats = async () => {
      try {
        let callsToday = 0;
        let callsThisWeek = 0;
        let aiHandled = 0;
        let totalReceptionist = 0;
        try {
          const { data: calls } = await supabase
            .from('calls')
            .select('started_at, created_at, source, outcome')
            .eq('business_id', me.id)
            .order('created_at', { ascending: false })
            .limit(500);
          if (calls) {
            const now = new Date();
            const todayStr = now.toISOString().slice(0, 10);
            const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
            callsToday = calls.filter(c =>
              (c.started_at || c.created_at)?.slice(0, 10) === todayStr
            ).length;
            callsThisWeek = calls.filter(c =>
              new Date(c.started_at || c.created_at) >= weekAgo
            ).length;
            const receptionist = calls.filter(c => c.source === 'receptionist');
            totalReceptionist = receptionist.length;
            aiHandled = receptionist.filter(c => c.outcome === 'handled').length;
          }
        } catch {}

        let emailsToday = 0;
        let emailsAction = 0;
        try {
          const emailsRes = await apiRequest('GET', '/v1/email/messages?limit=200');
          const emailsData = await emailsRes.json();
          const allEmails = Array.isArray(emailsData) ? emailsData : (emailsData.messages || []);
          const todayDate = new Date().toDateString();
          emailsToday = allEmails.filter((e: any) => e.received_at && new Date(e.received_at).toDateString() === todayDate).length;
          emailsAction = allEmails.filter((e: any) => e.ai_category === 'Action Required').length;
        } catch {}

        let unpaidCount = 0;
        let unpaidAmount = 0;
        let overdueCount = 0;
        try {
          const invRes = await apiRequest('GET', '/v1/invoices');
          const invData = await invRes.json();
          const invoices = Array.isArray(invData) ? invData : (invData.invoices || []);
          const unpaid = invoices.filter((i: any) =>
            ['unpaid', 'authorised', 'sent'].includes(i.status) && !i.archived
          );
          unpaidCount = unpaid.length;
          unpaidAmount = unpaid.reduce((sum: number, i: any) =>
            sum + (parseFloat(i.amount_due) || parseFloat(i.amount) || 0), 0
          );
          const today = new Date().toISOString().slice(0, 10);
          overdueCount = unpaid.filter((i: any) => i.due_date && i.due_date < today).length;
        } catch {}

        let openTasks = 0;
        let highPriority = 0;
        try {
          const { data: tasks } = await supabase
            .from('tasks')
            .select('status, priority')
            .eq('business_id', me.id)
            .is('deleted_at', null);
          if (tasks) {
            const open = tasks.filter(t => t.status !== 'completed');
            openTasks = open.length;
            highPriority = open.filter(t => t.priority === 'high').length;
          }
        } catch {}

        setStats({
          callsToday,
          callsThisWeek,
          emailsToday,
          emailsActionRequired: emailsAction,
          unpaidInvoices: unpaidCount,
          unpaidAmount,
          overdueInvoices: overdueCount,
          aiResolutionRate: totalReceptionist > 0
            ? Math.round((aiHandled / totalReceptionist) * 100)
            : 0,
          openTasks,
          highPriorityTasks: highPriority,
        });
      } catch (err) {
        console.error('Dashboard stats error:', err);
      } finally {
        setLoading(false);
      }

      // Background email sync — refresh counts after sync
      try {
        await runEmailSync();
        const freshRes = await apiRequest('GET', '/v1/email/messages?limit=200');
        const freshData = await freshRes.json();
        const fresh = Array.isArray(freshData) ? freshData : (freshData.messages || []);
        const todayStr = new Date().toDateString();
        const freshToday = fresh.filter((e: any) => e.received_at && new Date(e.received_at).toDateString() === todayStr).length;
        const freshAction = fresh.filter((e: any) => e.ai_category === 'Action Required').length;
        setStats(prev => prev ? { ...prev, emailsToday: freshToday, emailsActionRequired: freshAction } : prev);
      } catch {}
    };

    fetchStats();
  }, [me?.id]);

  if (!me?.id) return null;

  const displayName = ownerName || me.name?.split(' ')[0] || 'there';

  return (
    <div>
      {/* Greeting header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{
          fontSize: 22,
          fontWeight: 600,
          letterSpacing: '-0.3px',
          color: 'hsl(var(--foreground))',
          margin: 0,
        }}>
          {getGreeting()}, {displayName}
        </h1>
        <p style={{
          fontSize: 13,
          color: 'hsl(var(--muted-foreground))',
          marginTop: 4,
        }}>
          {formatDate()}
        </p>
      </div>

      {/* KPI Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(4, 1fr)',
        gap: 12,
        marginBottom: 24,
      }}>
        <div
          className="kpi-card"
          style={{ cursor: 'pointer' }}
          onClick={() => navigate('/app/comms?tab=calls')}
        >
          <div className="kpi-label">Calls today</div>
          <div className="kpi-value">{loading ? '—' : stats?.callsToday ?? 0}</div>
          <div className="kpi-sub neutral">
            {loading ? '' : `${stats?.callsThisWeek ?? 0} this week`}
          </div>
        </div>

        <div
          className="kpi-card"
          style={{ cursor: 'pointer' }}
          onClick={() => navigate('/app/comms?tab=emails')}
        >
          <div className="kpi-label">Emails today</div>
          <div className="kpi-value">{loading ? '—' : stats?.emailsToday ?? 0}</div>
          <div className={`kpi-sub ${(stats?.emailsActionRequired ?? 0) > 0 ? 'warning' : 'neutral'}`}>
            {loading ? '' : (stats?.emailsActionRequired ?? 0) > 0
              ? `${stats?.emailsActionRequired} need action`
              : 'No action required'
            }
          </div>
        </div>

        <div
          className="kpi-card"
          style={{ cursor: 'pointer' }}
          onClick={() => navigate('/app/finance?tab=invoices')}
        >
          <div className="kpi-label">Invoices</div>
          <div className="kpi-value">
            {loading ? '—' : `£${(stats?.unpaidAmount ?? 0).toLocaleString('en-GB', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          </div>
          <div className={`kpi-sub ${(stats?.overdueInvoices ?? 0) > 0 ? 'warning' : 'neutral'}`}>
            {loading ? '' : `${stats?.unpaidInvoices ?? 0} unpaid${(stats?.overdueInvoices ?? 0) > 0 ? `, ${stats?.overdueInvoices} overdue` : ''}`}
          </div>
        </div>

        <div
          className="kpi-card"
          style={{ cursor: 'pointer' }}
          onClick={() => navigate('/app/ai?tab=aria')}
        >
          <div className="kpi-label">AI receptionist</div>
          <div className="kpi-value">{loading ? '—' : `${stats?.aiResolutionRate ?? 0}%`}</div>
          <div className="kpi-sub accent">resolution rate</div>
        </div>
      </div>

      {/* Two column layout: Quick Actions + Tasks */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
        gap: 12,
        marginBottom: 24,
      }}>
        {/* Quick Actions */}
        <div className="glass-card">
          <div className="section-header">
            <span>Quick actions</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {[
              { label: 'Check emails', icon: '📧', path: '/app/comms?tab=emails' },
              { label: 'Review invoices', icon: '📄', path: '/app/finance?tab=invoices' },
              { label: 'Talk to Aria', icon: '🤖', path: '/app/ai?tab=aria' },
              { label: 'View calls', icon: '📞', path: '/app/comms?tab=calls' },
            ].map((item) => (
              <div
                key={item.label}
                className="quick-action-row"
                onClick={() => navigate(item.path)}
              >
                <span style={{ fontSize: 16 }}>{item.icon}</span>
                {item.label}
                <span style={{ marginLeft: 'auto', opacity: 0.3, fontSize: 12 }}>→</span>
              </div>
            ))}
          </div>
        </div>

        {/* Tasks Summary */}
        <div className="glass-card">
          <div className="section-header">
            <span>Tasks</span>
            <span className="section-link" onClick={() => setShowTasks(!showTasks)}>
              {showTasks ? 'Hide full list' : 'View all'}
            </span>
          </div>
          {stats && !loading ? (
            <div>
              <div style={{
                display: 'flex',
                gap: 16,
                marginBottom: stats.openTasks > 0 ? 12 : 0,
                fontSize: 13,
                color: 'hsl(var(--muted-foreground))',
              }}>
                <span>
                  <strong style={{ color: 'hsl(var(--foreground))', fontWeight: 600 }}>
                    {stats.openTasks}
                  </strong> open
                </span>
                {stats.highPriorityTasks > 0 && (
                  <span>
                    <strong style={{ color: '#f87171', fontWeight: 600 }}>
                      {stats.highPriorityTasks}
                    </strong> high priority
                  </span>
                )}
              </div>
              {stats.openTasks === 0 && (
                <div style={{
                  fontSize: 13,
                  color: 'hsl(var(--muted-foreground))',
                  textAlign: 'center',
                  padding: '20px 0',
                }}>
                  All caught up — no open tasks
                </div>
              )}
            </div>
          ) : (
            <div style={{
              fontSize: 13,
              color: 'hsl(var(--muted-foreground))',
              textAlign: 'center',
              padding: '20px 0',
            }}>
              Loading...
            </div>
          )}
        </div>
      </div>

      {/* Full tasks panel (toggleable) */}
      {showTasks && (
        <div style={{ marginTop: 12 }}>
          <TasksPanel businessId={me.id} />
        </div>
      )}
    </div>
  );
}
