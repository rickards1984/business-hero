import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
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

export default function DashboardPage() {
  const { data: me } = useMe();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [showTasks, setShowTasks] = useState(false);
  const [ownerName, setOwnerName] = useState<string>('');
  const businessId = me?.id;

  useEffect(() => {
    if (!businessId) return;
    apiRequest('GET', '/v1/whatsapp/config')
      .then(r => r.json())
      .then(c => { if (c?.owner_name) setOwnerName(c.owner_name); })
      .catch(() => {});
  }, [businessId]);

  // Each query runs INDEPENDENTLY and IN PARALLEL — each card renders as its data arrives
  const { data: callsData, isLoading: callsLoading } = useQuery({
    queryKey: ['dashboard-calls', businessId],
    queryFn: async () => {
      const { data: calls } = await supabase
        .from('calls')
        .select('started_at, created_at, source, outcome')
        .eq('business_id', businessId!)
        .order('created_at', { ascending: false })
        .limit(500);
      if (!calls) return { callsToday: 0, callsThisWeek: 0, aiResolutionRate: 0 };
      const now = new Date();
      const todayStr = now.toISOString().slice(0, 10);
      const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      const callsToday = calls.filter(c => (c.started_at || c.created_at)?.slice(0, 10) === todayStr).length;
      const callsThisWeek = calls.filter(c => new Date(c.started_at || c.created_at) >= weekAgo).length;
      const receptionist = calls.filter(c => c.source === 'receptionist');
      const aiHandled = receptionist.filter(c => c.outcome === 'handled').length;
      return {
        callsToday,
        callsThisWeek,
        aiResolutionRate: receptionist.length > 0 ? Math.round((aiHandled / receptionist.length) * 100) : 0,
      };
    },
    enabled: !!businessId,
    staleTime: 3 * 60 * 1000,
  });

  const { data: emailsData, isLoading: emailsLoading } = useQuery({
    queryKey: ['dashboard-emails', businessId],
    queryFn: async () => {
      const res = await apiRequest('GET', '/v1/email/messages?limit=200');
      const data = await res.json();
      const emails = Array.isArray(data) ? data : (data.messages || []);
      const todayDate = new Date().toDateString();
      return {
        emailsToday: emails.filter((e: any) => e.received_at && new Date(e.received_at).toDateString() === todayDate).length,
        emailsActionRequired: emails.filter((e: any) => e.ai_category === 'Action Required').length,
      };
    },
    enabled: !!businessId,
    staleTime: 3 * 60 * 1000,
  });

  const { data: invoicesData, isLoading: invoicesLoading } = useQuery({
    queryKey: ['dashboard-invoices', businessId],
    queryFn: async () => {
      const res = await apiRequest('GET', '/v1/invoices');
      const data = await res.json();
      const invoices = Array.isArray(data) ? data : (data.invoices || []);
      const unpaid = invoices.filter((i: any) => ['unpaid', 'authorised', 'sent'].includes(i.status) && !i.archived);
      const today = new Date().toISOString().slice(0, 10);
      return {
        unpaidCount: unpaid.length,
        unpaidAmount: unpaid.reduce((sum: number, i: any) => sum + (parseFloat(i.amount_due) || parseFloat(i.amount) || 0), 0),
        overdueCount: unpaid.filter((i: any) => i.due_date && i.due_date < today).length,
      };
    },
    enabled: !!businessId,
    staleTime: 5 * 60 * 1000,
  });

  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: ['dashboard-tasks', businessId],
    queryFn: async () => {
      const { data: tasks } = await supabase
        .from('tasks')
        .select('status, priority')
        .eq('business_id', businessId!)
        .is('deleted_at', null);
      if (!tasks) return { openTasks: 0, highPriorityTasks: 0 };
      const open = tasks.filter(t => t.status !== 'completed');
      return {
        openTasks: open.length,
        highPriorityTasks: open.filter(t => t.priority === 'high').length,
      };
    },
    enabled: !!businessId,
    staleTime: 3 * 60 * 1000,
  });

  // Background email sync — fire and forget, NEVER blocks UI
  useEffect(() => {
    if (businessId) {
      runEmailSync().catch(() => {});
    }
  }, [businessId]);

  if (!businessId) return null;

  const displayName = ownerName || me?.name?.split(' ')[0] || 'there';

  return (
    <div>
      {/* Greeting — renders immediately, no data dependency */}
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

      {/* KPI Cards — each renders independently */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(4, 1fr)',
        gap: 12,
        marginBottom: 24,
      }}>
        <div className="kpi-card" style={{ cursor: 'pointer' }} onClick={() => navigate('/app/comms?tab=calls')}>
          <div className="kpi-label">Calls today</div>
          {callsLoading ? (
            <><div className="skeleton" style={{ height: 28, width: '50%', marginBottom: 6 }} /><div className="skeleton" style={{ height: 14, width: '70%' }} /></>
          ) : (
            <><div className="kpi-value">{callsData?.callsToday ?? 0}</div><div className="kpi-sub neutral">{callsData?.callsThisWeek ?? 0} this week</div></>
          )}
        </div>

        <div className="kpi-card" style={{ cursor: 'pointer' }} onClick={() => navigate('/app/comms?tab=emails')}>
          <div className="kpi-label">Emails today</div>
          {emailsLoading ? (
            <><div className="skeleton" style={{ height: 28, width: '50%', marginBottom: 6 }} /><div className="skeleton" style={{ height: 14, width: '70%' }} /></>
          ) : (
            <><div className="kpi-value">{emailsData?.emailsToday ?? 0}</div>
            <div className={`kpi-sub ${(emailsData?.emailsActionRequired ?? 0) > 0 ? 'warning' : 'neutral'}`}>
              {(emailsData?.emailsActionRequired ?? 0) > 0 ? `${emailsData?.emailsActionRequired} need action` : 'No action required'}
            </div></>
          )}
        </div>

        <div className="kpi-card" style={{ cursor: 'pointer' }} onClick={() => navigate('/app/finance?tab=invoices')}>
          <div className="kpi-label">Invoices</div>
          {invoicesLoading ? (
            <><div className="skeleton" style={{ height: 28, width: '60%', marginBottom: 6 }} /><div className="skeleton" style={{ height: 14, width: '70%' }} /></>
          ) : (
            <><div className="kpi-value">£{(invoicesData?.unpaidAmount ?? 0).toLocaleString('en-GB', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</div>
            <div className={`kpi-sub ${(invoicesData?.overdueCount ?? 0) > 0 ? 'warning' : 'neutral'}`}>
              {invoicesData?.unpaidCount ?? 0} unpaid{(invoicesData?.overdueCount ?? 0) > 0 ? `, ${invoicesData?.overdueCount} overdue` : ''}
            </div></>
          )}
        </div>

        <div className="kpi-card" style={{ cursor: 'pointer' }} onClick={() => navigate('/app/ai?tab=aria')}>
          <div className="kpi-label">AI receptionist</div>
          {callsLoading ? (
            <><div className="skeleton" style={{ height: 28, width: '40%', marginBottom: 6 }} /><div className="skeleton" style={{ height: 14, width: '60%' }} /></>
          ) : (
            <><div className="kpi-value">{callsData?.aiResolutionRate ?? 0}%</div><div className="kpi-sub accent">resolution rate</div></>
          )}
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
          {!tasksLoading && tasksData ? (
            <div>
              <div style={{
                display: 'flex',
                gap: 16,
                marginBottom: tasksData.openTasks > 0 ? 12 : 0,
                fontSize: 13,
                color: 'hsl(var(--muted-foreground))',
              }}>
                <span>
                  <strong style={{ color: 'hsl(var(--foreground))', fontWeight: 600 }}>
                    {tasksData.openTasks}
                  </strong> open
                </span>
                {tasksData.highPriorityTasks > 0 && (
                  <span>
                    <strong style={{ color: '#f87171', fontWeight: 600 }}>
                      {tasksData.highPriorityTasks}
                    </strong> high priority
                  </span>
                )}
              </div>
              {tasksData.openTasks === 0 && (
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
            <div style={{ padding: '12px 0' }}>
              <div className="skeleton" style={{ height: 14, width: '40%', marginBottom: 8 }} />
              <div className="skeleton" style={{ height: 14, width: '60%' }} />
            </div>
          )}
        </div>
      </div>

      {/* Full tasks panel (toggleable) */}
      {showTasks && (
        <div style={{ marginTop: 12 }}>
          <TasksPanel businessId={me!.id} />
        </div>
      )}
    </div>
  );
}
