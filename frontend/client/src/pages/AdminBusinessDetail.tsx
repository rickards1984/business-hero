import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Divider,
  Paper,
  Tab,
  Tabs,
  TextField,
  Typography,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import Switch from '@mui/material/Switch';
import { supabase, type Business, type BusinessMember } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';
import AdminReceptionistSection from '@/components/AdminReceptionistSection';
import AdminWhatsAppSection from '@/components/AdminWhatsAppSection';

const FEATURE_TOGGLE_LIST = [
  { key: 'quoting_enabled', label: 'Quoting & Quantity Surveying', description: 'AI-powered quotes, quantity surveying, PDF generation, quote-to-invoice', icon: '📋', defaultEnabled: false },
  { key: 'calendar_booking_enabled', label: 'Calendar Booking', description: 'AI receptionist can check availability and book appointments', icon: '📅', defaultEnabled: false },
  { key: 'whatsapp_enabled', label: 'WhatsApp CEO Briefing', description: 'Daily pulse, weekly briefing, and real-time alerts via WhatsApp', icon: '💬', defaultEnabled: false },
  { key: 'ai_receptionist_enabled', label: 'AI Receptionist', description: 'AI-powered phone receptionist with call handling', icon: '🤖', defaultEnabled: true },
  { key: 'email_management_enabled', label: 'Email Management', description: 'Gmail sync, AI categorisation, and email management', icon: '📧', defaultEnabled: true },
  { key: 'invoice_chasing_enabled', label: 'Invoice Chasing', description: 'Automated invoice reminders and chase management', icon: '📄', defaultEnabled: true },
  { key: 'accounting_enabled', label: 'Accounting Integration', description: 'Connect to Xero, FreeAgent, or QuickBooks', icon: '💷', defaultEnabled: false },
];

const INDUSTRY_PRESETS: Record<string, string[]> = {
  general: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled'],
  construction: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'quoting_enabled', 'calendar_booking_enabled', 'accounting_enabled'],
  plumbing: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'quoting_enabled', 'calendar_booking_enabled'],
  electrical: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'quoting_enabled', 'calendar_booking_enabled'],
  fitness: ['email_management_enabled', 'ai_receptionist_enabled', 'calendar_booking_enabled', 'whatsapp_enabled'],
  cleaning: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'quoting_enabled'],
  landscaping: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'quoting_enabled'],
  consulting: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'calendar_booking_enabled', 'accounting_enabled'],
  automotive: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'quoting_enabled'],
  property: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled', 'accounting_enabled'],
  other: ['email_management_enabled', 'ai_receptionist_enabled', 'invoice_chasing_enabled'],
};

interface AwazIntegration {
  webhook_url: string;
  connected: boolean;
  last_received_at: string | null;
  last_error?: string | null;
  receptionist_name?: string | null;
  phone_number?: string | null;
}

interface EmailAccount {
  id: string;
  email_address: string;
  provider: string;
  is_default: boolean;
  created_at: string;
}

interface SyncState {
  email_account_id: string;
  last_synced_at: string | null;
  last_error: string | null;
}

interface SupportTicket {
  id: string;
  title: string;
  message: string;
  severity: string;
  status: string;
  created_at: string;
  admin_notes?: string | null;
}

interface BusinessHealth {
  business: {
    id: string;
    name: string;
    plan_tier: string | null;
    is_active: boolean;
    subscription_status: string | null;
    current_period_end: string | null;
    feature_flags: Record<string, any>;
    limits_json: Record<string, any>;
  };
  awaz: { connected: boolean; last_webhook_at: string | null };
  email: { connected: boolean; default_email: string | null; last_sync_at: string | null };
  calendar: { connected: boolean; last_sync_at: string | null };
  activity: { last_call_at: string | null; last_task_at: string | null };
  support: { open_ticket_count: number };
}

type TabKey = 'overview' | 'members' | 'integrations' | 'activity' | 'support';

const PLAN_TIERS = ['starter', 'pro', 'elite', 'beta', 'paused'];
const ROLES = ['owner', 'admin', 'member'];
const SUPPORT_PRIORITIES = ['low', 'normal', 'high', 'urgent'];

export default function AdminBusinessDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<TabKey>('overview');
  const [business, setBusiness] = useState<Business | null>(null);
  const [planTier, setPlanTier] = useState('starter');
  const [isActive, setIsActive] = useState(true);
  const [trialEndsAt, setTrialEndsAt] = useState('');
  const [featureFlagsText, setFeatureFlagsText] = useState('{}');
  const [limitsText, setLimitsText] = useState('{}');

  const [members, setMembers] = useState<BusinessMember[]>([]);
  const [memberDialogOpen, setMemberDialogOpen] = useState(false);
  const [memberEmail, setMemberEmail] = useState('');
  const [memberRole, setMemberRole] = useState('member');
  const [savingMember, setSavingMember] = useState(false);

  const [awaz, setAwaz] = useState<AwazIntegration | null>(null);
  const [emailAccounts, setEmailAccounts] = useState<EmailAccount[]>([]);
  const [emailSyncState, setEmailSyncState] = useState<SyncState | null>(null);
  const [calendarSyncState, setCalendarSyncState] = useState<SyncState | null>(null);

  const [recentCalls, setRecentCalls] = useState<any[]>([]);
  const [recentTasks, setRecentTasks] = useState<any[]>([]);
  const [openTasksCount, setOpenTasksCount] = useState(0);
  const [callsLast7Days, setCallsLast7Days] = useState(0);

  const [supportTickets, setSupportTickets] = useState<SupportTicket[]>([]);
  const [supportLoading, setSupportLoading] = useState(false);
  const [supportSaving, setSupportSaving] = useState(false);
  const [supportTitle, setSupportTitle] = useState('');
  const [supportMessage, setSupportMessage] = useState('');
  const [supportSeverity, setSupportSeverity] = useState('normal');
  const [selectedTicket, setSelectedTicket] = useState<SupportTicket | null>(null);
  const [ticketStatus, setTicketStatus] = useState('open');
  const [ticketSeverity, setTicketSeverity] = useState('normal');
  const [ticketNotes, setTicketNotes] = useState('');

  const [health, setHealth] = useState<BusinessHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  const [accountingConnection, setAccountingConnection] = useState<{
    connected: boolean;
    provider?: string;
    tenant_name?: string;
    last_sync_at?: string | null;
  } | null>(null);

  useEffect(() => {
    if (id) {
      loadBusiness();
    }
  }, [id]);

  useEffect(() => {
    if (tab === 'support' && id) {
      loadSupportTickets();
    }
  }, [tab, id]);

  const loadBusiness = async () => {
    setLoading(true);
    setError('');
    try {
      const { data, error: fetchError } = await supabase
        .from('businesses')
        .select('*')
        .eq('id', id)
        .single();
      if (fetchError) throw fetchError;
      setBusiness(data);
      setPlanTier(data.plan_tier || 'starter');
      setIsActive(data.is_active ?? true);
      setTrialEndsAt(data.trial_ends_at ? data.trial_ends_at.slice(0, 16) : '');
      setFeatureFlagsText(JSON.stringify(data.feature_flags || {}, null, 2));
      setLimitsText(JSON.stringify(data.limits || {}, null, 2));

      await Promise.all([
        loadMembers(),
        loadAwaz(),
        loadEmailAccounts(),
        loadActivity(),
        loadHealth(),
        loadAccountingConnection(),
      ]);
    } catch (err: any) {
      setError(err.message || 'Failed to load business');
    } finally {
      setLoading(false);
    }
  };

  const loadMembers = async () => {
    const { data, error: memberError } = await supabase
      .from('business_members')
      .select('*')
      .eq('business_id', id)
      .order('created_at', { ascending: false });
    if (memberError) throw memberError;
    setMembers(data || []);
  };

  const loadAwaz = async () => {
    const response = await apiRequest('GET', `/v1/integrations/awaz?business_id=${id}`);
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Failed to load Awaz integration');
    }
    const data: AwazIntegration = await response.json();
    setAwaz(data);
  };

  const loadAccountingConnection = async () => {
    try {
      const response = await apiRequest('GET', `/v1/accounting/connection/status?business_id=${id}`);
      if (response.ok) {
        const data = await response.json();
        setAccountingConnection({
          connected: !!data.connected,
          provider: data.provider,
          tenant_name: data.tenant_name,
          last_sync_at: data.last_sync_at,
        });
      } else {
        setAccountingConnection({ connected: false });
      }
    } catch {
      setAccountingConnection({ connected: false });
    }
  };

  const handleAccountingDisconnect = async () => {
    if (!confirm("Disconnect this business's accounting software? Synced data will be preserved.")) return;
    try {
      const resp = await apiRequest('POST', `/v1/accounting/disconnect?business_id=${id}`);
      if (resp.ok) {
        setAccountingConnection({ connected: false });
      }
    } catch {
      try {
        await apiRequest('POST', `/v1/accounting/xero/disconnect?business_id=${id}`);
        setAccountingConnection({ connected: false });
      } catch { /* ignore */ }
    }
    loadAccountingConnection();
  };

  const loadEmailAccounts = async () => {
    const { data, error: emailError } = await supabase
      .from('email_accounts')
      .select('id,email_address,provider,is_default,created_at')
      .eq('business_id', id);
    if (emailError) throw emailError;
    const accounts = (data || []) as EmailAccount[];
    setEmailAccounts(accounts);

    if (accounts.length) {
      const ids = accounts.map((a) => a.id);
      const { data: syncData } = await supabase
        .from('email_sync_state')
        .select('email_account_id,last_synced_at,last_error')
        .in('email_account_id', ids)
        .order('last_synced_at', { ascending: false })
        .limit(1);
      if (syncData && syncData.length) {
        setEmailSyncState(syncData[0] as SyncState);
      }

      const { data: calData } = await supabase
        .from('calendar_sync_state')
        .select('email_account_id,last_synced_at,last_error')
        .in('email_account_id', ids)
        .order('last_synced_at', { ascending: false })
        .limit(1);
      if (calData && calData.length) {
        setCalendarSyncState(calData[0] as SyncState);
      }
    }
  };

  const loadActivity = async () => {
    const { data: callsData } = await supabase
      .from('calls')
      .select('id,caller_name,caller_number,summary,created_at')
      .eq('business_id', id)
      .order('created_at', { ascending: false })
      .limit(10);
    setRecentCalls(callsData || []);

    const { data: tasksData } = await supabase
      .from('tasks')
      .select('id,title,status,created_at')
      .eq('business_id', id)
      .is('deleted_at', null)
      .order('created_at', { ascending: false })
      .limit(10);
    setRecentTasks(tasksData || []);

    const { count: openCount } = await supabase
      .from('tasks')
      .select('*', { count: 'exact', head: true })
      .eq('business_id', id)
      .eq('status', 'open')
      .is('deleted_at', null);
    setOpenTasksCount(openCount || 0);

    const since = new Date();
    since.setDate(since.getDate() - 7);
    const { count: callCount } = await supabase
      .from('calls')
      .select('*', { count: 'exact', head: true })
      .eq('business_id', id)
      .gte('created_at', since.toISOString());
    setCallsLast7Days(callCount || 0);
  };

  const loadHealth = async () => {
    setHealthLoading(true);
    try {
      const response = await apiRequest('GET', `/v1/admin/businesses/${id}/health`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to load health');
      }
      const data: BusinessHealth = await response.json();
      setHealth(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load health');
    } finally {
      setHealthLoading(false);
    }
  };

  const loadSupportTickets = async () => {
    setSupportLoading(true);
    setError('');
    try {
      const response = await apiRequest(
        'GET',
        `/v1/admin/support-tickets?business_id=${id}&limit=10`,
      );
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to load support tickets');
      }
      const data = await response.json();
      setSupportTickets(data || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load support tickets');
    } finally {
      setSupportLoading(false);
    }
  };

  const handleCreateSupportTicket = async () => {
    if (!supportTitle.trim() || !supportMessage.trim()) return;
    setSupportSaving(true);
    setError('');
    try {
      const response = await apiRequest('POST', '/v1/admin/support-tickets', {
        business_id: id,
        title: supportTitle.trim(),
        message: supportMessage.trim(),
        severity: supportSeverity,
        category: 'general',
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to create support ticket');
      }
      setSupportTitle('');
      setSupportMessage('');
      setSupportSeverity('normal');
      await loadSupportTickets();
    } catch (err: any) {
      setError(err.message || 'Failed to create support ticket');
    } finally {
      setSupportSaving(false);
    }
  };

  const handleOpenTicketEdit = (ticket: SupportTicket) => {
    setSelectedTicket(ticket);
    setTicketStatus(ticket.status);
    setTicketSeverity(ticket.severity);
    setTicketNotes(ticket.admin_notes || '');
  };

  const handleUpdateTicket = async () => {
    if (!selectedTicket) return;
    setSupportSaving(true);
    setError('');
    try {
      const response = await apiRequest('PATCH', `/v1/admin/support-tickets/${selectedTicket.id}`, {
        status: ticketStatus,
        severity: ticketSeverity,
        admin_notes: ticketNotes,
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to update ticket');
      }
      setSelectedTicket(null);
      await loadSupportTickets();
    } catch (err: any) {
      setError(err.message || 'Failed to update ticket');
    } finally {
      setSupportSaving(false);
    }
  };

  const handleSaveOverview = async () => {
    if (!business) return;
    setSaving(true);
    setError('');
    try {
      let featureFlags = {};
      let limits = {};
      try {
        featureFlags = JSON.parse(featureFlagsText || '{}');
        limits = JSON.parse(limitsText || '{}');
      } catch {
        throw new Error('Feature flags or limits JSON is invalid');
      }

      const payload: Record<string, any> = {
        plan_tier: planTier,
        is_active: isActive,
        trial_ends_at: trialEndsAt ? new Date(trialEndsAt).toISOString() : null,
        feature_flags: featureFlags,
        limits: limits,
      };

      const { error: updateError } = await supabase
        .from('businesses')
        .update(payload)
        .eq('id', business.id);
      if (updateError) throw updateError;
      await loadBusiness();
    } catch (err: any) {
      setError(err.message || 'Failed to save business');
    } finally {
      setSaving(false);
    }
  };

  const handleAddMember = async () => {
    if (!memberEmail.trim()) return;
    setSavingMember(true);
    setError('');
    try {
      const { error: insertError } = await supabase
        .from('business_members')
        .insert({
          business_id: id,
          invited_email: memberEmail.trim().toLowerCase(),
          role: memberRole,
          is_active: true,
        });
      if (insertError) throw insertError;
      setMemberDialogOpen(false);
      setMemberEmail('');
      setMemberRole('member');
      await loadMembers();
    } catch (err: any) {
      setError(err.message || 'Failed to add member');
    } finally {
      setSavingMember(false);
    }
  };

  const handleRotateAwaz = async () => {
    try {
      const response = await apiRequest('POST', `/v1/integrations/awaz/rotate-secret?business_id=${id}`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to rotate key');
      }
      const data = await response.json();
      setAwaz((prev) => (prev ? { ...prev, webhook_url: data.webhook_url } : prev));
    } catch (err: any) {
      setError(err.message || 'Failed to rotate key');
    }
  };

  const handleTestAwaz = async () => {
    try {
      const response = await apiRequest('POST', `/v1/admin/businesses/${id}/awaz/test`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to test integration');
      }
      await loadAwaz();
      await loadActivity();
      await loadHealth();
    } catch (err: any) {
      setError(err.message || 'Failed to test integration');
    }
  };

  const handleEmailSync = async () => {
    try {
      const response = await apiRequest('POST', `/v1/admin/businesses/${id}/email/sync`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to sync email');
      }
      await loadEmailAccounts();
      await loadHealth();
    } catch (err: any) {
      setError(err.message || 'Failed to sync email');
    }
  };

  const handleCalendarSync = async () => {
    try {
      const response = await apiRequest('POST', `/v1/admin/businesses/${id}/calendar/sync`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to sync calendar');
      }
      await loadHealth();
    } catch (err: any) {
      setError(err.message || 'Failed to sync calendar');
    }
  };

  const handleToggleActive = async () => {
    if (!business) return;
    setError('');
    try {
      const { error: updateError } = await supabase
        .from('businesses')
        .update({ is_active: !business.is_active })
        .eq('id', business.id);
      if (updateError) throw updateError;
      await loadBusiness();
    } catch (err: any) {
      setError(err.message || 'Failed to update status');
    }
  };

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      setError('Failed to copy');
    }
  };

  const defaultEmail = useMemo(
    () => emailAccounts.find((account) => account.is_default),
    [emailAccounts],
  );

  const lastActivityAt = useMemo(() => {
    const dates = [
      recentCalls[0]?.created_at,
      recentTasks[0]?.created_at,
    ].filter(Boolean);
    if (!dates.length) return null;
    return dates.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];
  }, [recentCalls, recentTasks]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'grey.100' }}>
      <AppBar position="static">
        <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1 }}>
          <Button
            color="inherit"
            startIcon={<ArrowBackIcon />}
            onClick={() => navigate('/admin')}
          >
            Back to Admin Businesses
          </Button>
          <Typography variant="h6" sx={{ ml: 2 }}>
            {business?.name || 'Business'}
          </Typography>
        </Box>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Paper sx={{ mb: 3 }}>
          <Tabs value={tab} onChange={(_, value) => setTab(value)}>
            <Tab label="Overview" value="overview" />
            <Tab label="Members" value="members" />
            <Tab label="Integrations" value="integrations" />
            <Tab label="Activity" value="activity" />
            <Tab label="Support" value="support" />
          </Tabs>
        </Paper>

        {tab === 'overview' && (
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>Health</Typography>
            {healthLoading ? (
              <Typography color="text.secondary">Loading health...</Typography>
            ) : health ? (
              <Box sx={{ display: 'grid', gap: 2 }}>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                  <Chip label={`Plan: ${health.business.plan_tier || 'starter'}`} />
                  <Chip label={`Subscription: ${health.business.subscription_status || 'none'}`} />
                  <Chip
                    label={health.business.is_active ? 'Active' : 'Paused'}
                    color={health.business.is_active ? 'success' : 'default'}
                  />
                  <Typography variant="body2" color="text.secondary">
                    Period end: {health.business.current_period_end ? new Date(health.business.current_period_end).toLocaleString() : '—'}
                  </Typography>
                  <Button variant="outlined" size="small" onClick={handleToggleActive}>
                    {health.business.is_active ? 'Pause' : 'Activate'}
                  </Button>
                </Box>

                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                  <Chip label={`Email: ${health.business.feature_flags?.email ? 'On' : 'Off'}`} size="small" />
                  <Chip label={`Calendar: ${health.business.feature_flags?.calendar ? 'On' : 'Off'}`} size="small" />
                  <Chip label={`Voice: ${health.business.feature_flags?.voice ? 'On' : 'Off'}`} size="small" />
                  <Chip label={`Receptionist: ${health.business.feature_flags?.receptionist ? 'On' : 'Off'}`} size="small" />
                </Box>

                <Divider />

                <Box sx={{ display: 'grid', gap: 1 }}>
                  <Typography variant="subtitle1">Integrations</Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                    <Chip label={`Awaz: ${health.awaz.connected ? 'Connected' : 'Not connected'}`} />
                    <Typography variant="body2" color="text.secondary">
                      Last webhook: {health.awaz.last_webhook_at || 'Never'}
                    </Typography>
                    <Button variant="outlined" size="small" onClick={handleRotateAwaz}>Rotate key</Button>
                    <Button variant="outlined" size="small" onClick={handleTestAwaz}>Test webhook</Button>
                  </Box>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                    <Chip label={`Email: ${health.email.connected ? 'Connected' : 'Not connected'}`} />
                    <Typography variant="body2" color="text.secondary">
                      Default: {health.email.default_email || 'None'}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Last sync: {health.email.last_sync_at || 'Never'}
                    </Typography>
                    <Button variant="outlined" size="small" onClick={handleEmailSync}>Force inbox sync</Button>
                  </Box>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                    <Chip label={`Calendar: ${health.calendar.connected ? 'Connected' : 'Not connected'}`} />
                    <Typography variant="body2" color="text.secondary">
                      Last sync: {health.calendar.last_sync_at || 'Never'}
                    </Typography>
                    <Button variant="outlined" size="small" onClick={handleCalendarSync}>Force calendar sync</Button>
                  </Box>
                  {id && (
                    <Box sx={{ display: 'grid', gap: 2 }}>
                      <AdminReceptionistSection
                        businessId={id}
                        featureFlags={health.business.feature_flags}
                        onFeatureFlagChange={() => { loadBusiness(); loadHealth(); }}
                      />
                      <AdminWhatsAppSection businessId={id} />
                    </Box>
                  )}
                </Box>

                <Divider />

                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                  <Typography variant="body2" color="text.secondary">
                    Last call: {health.activity.last_call_at ? new Date(health.activity.last_call_at).toLocaleString() : '—'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Last task: {health.activity.last_task_at ? new Date(health.activity.last_task_at).toLocaleString() : '—'}
                  </Typography>
                  <Chip label={`Open tickets: ${health.support.open_ticket_count}`} size="small" />
                </Box>
              </Box>
            ) : (
              <Typography color="text.secondary">No health data available.</Typography>
            )}

            <Divider sx={{ my: 3 }} />

            <Typography variant="subtitle1" sx={{ mb: 1 }}>
              Impersonation info
            </Typography>
            <Box sx={{ display: 'grid', gap: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body2">Business ID: {business?.id}</Typography>
                {business?.id && (
                  <Button size="small" onClick={() => handleCopy(business.id)}>Copy</Button>
                )}
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body2">Plan: {planTier}</Typography>
                <Button size="small" onClick={() => handleCopy(planTier)}>Copy</Button>
              </Box>
              <Typography variant="body2">Feature flags: {featureFlagsText}</Typography>
              <Typography variant="body2">Limits: {limitsText}</Typography>
            </Box>

            <Divider sx={{ my: 3 }} />
            <Typography variant="h6" gutterBottom>Business Profile</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              ID: {business?.id}
            </Typography>
            <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
              <FormControl fullWidth>
                <InputLabel>Plan tier</InputLabel>
                <Select
                  value={planTier}
                  label="Plan tier"
                  onChange={(event) => setPlanTier(event.target.value)}
                >
                  {PLAN_TIERS.map((tier) => (
                    <MenuItem key={tier} value={tier}>
                      {tier}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth>
                <InputLabel>Active</InputLabel>
                <Select
                  value={isActive ? 'true' : 'false'}
                  label="Active"
                  onChange={(event) => setIsActive(event.target.value === 'true')}
                >
                  <MenuItem value="true">Active</MenuItem>
                  <MenuItem value="false">Paused</MenuItem>
                </Select>
              </FormControl>
              <TextField
                label="Trial ends at"
                type="datetime-local"
                value={trialEndsAt}
                onChange={(event) => setTrialEndsAt(event.target.value)}
                InputLabelProps={{ shrink: true }}
                fullWidth
              />
              <TextField
                label="Timezone"
                value={business?.timezone || ''}
                fullWidth
                disabled
              />
            </Box>

            <Divider sx={{ my: 3 }} />

            <Typography variant="subtitle1" sx={{ mb: 1 }}>
              Onboarding checklist
            </Typography>
            <Box sx={{ display: 'grid', gap: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Chip label={awaz?.connected ? 'Yes' : 'No'} color={awaz?.connected ? 'success' : 'default'} />
                <Typography variant="body2">Awaz configured</Typography>
                <Typography variant="caption" color="text.secondary">
                  Last received: {awaz?.last_received_at || 'Never'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Chip label={emailAccounts.length ? 'Yes' : 'No'} color={emailAccounts.length ? 'success' : 'default'} />
                <Typography variant="body2">Email connected</Typography>
                <Typography variant="caption" color="text.secondary">
                  Accounts: {emailAccounts.length} • Last sync: {emailSyncState?.last_synced_at || 'Never'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Chip label={calendarSyncState ? 'Yes' : 'No'} color={calendarSyncState ? 'success' : 'default'} />
                <Typography variant="body2">Calendar connected</Typography>
                <Typography variant="caption" color="text.secondary">
                  Last sync: {calendarSyncState?.last_synced_at || 'Never'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Chip label={lastActivityAt ? 'Yes' : 'No'} color={lastActivityAt ? 'success' : 'default'} />
                <Typography variant="body2">Recent activity</Typography>
                <Typography variant="caption" color="text.secondary">
                  {lastActivityAt ? new Date(lastActivityAt).toLocaleString() : 'None'}
                </Typography>
              </Box>
            </Box>

            <Divider sx={{ my: 3 }} />
            <Typography variant="h6" gutterBottom>Feature Configuration</Typography>

            <FormControl fullWidth size="small" sx={{ mb: 2 }}>
              <InputLabel>Industry</InputLabel>
              <Select
                value={business?.feature_flags?.industry || 'general'}
                label="Industry"
                onChange={(e) => {
                  const industry = e.target.value as string;
                  const presets = INDUSTRY_PRESETS[industry] || [];
                  const updatedFlags: Record<string, any> = { ...(business?.feature_flags || {}), industry };
                  FEATURE_TOGGLE_LIST.forEach(f => {
                    updatedFlags[f.key] = presets.includes(f.key);
                  });
                  setBusiness((prev: any) => prev ? { ...prev, feature_flags: updatedFlags } : prev);
                  setFeatureFlagsText(JSON.stringify(updatedFlags, null, 2));
                }}
              >
                <MenuItem value="general">General</MenuItem>
                <MenuItem value="construction">Construction &amp; Building</MenuItem>
                <MenuItem value="plumbing">Plumbing &amp; Heating</MenuItem>
                <MenuItem value="electrical">Electrical</MenuItem>
                <MenuItem value="landscaping">Landscaping &amp; Gardening</MenuItem>
                <MenuItem value="cleaning">Cleaning Services</MenuItem>
                <MenuItem value="fitness">Fitness &amp; Wellness</MenuItem>
                <MenuItem value="automotive">Automotive</MenuItem>
                <MenuItem value="property">Property Management</MenuItem>
                <MenuItem value="consulting">Consulting &amp; Professional Services</MenuItem>
                <MenuItem value="other">Other</MenuItem>
              </Select>
            </FormControl>

            {FEATURE_TOGGLE_LIST.map((feature) => (
              <Box key={feature.key} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
                <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, flex: 1 }}>
                  <Typography sx={{ fontSize: 20, lineHeight: 1 }}>{feature.icon}</Typography>
                  <Box>
                    <Typography variant="body2" fontWeight={500}>{feature.label}</Typography>
                    <Typography variant="caption" color="text.secondary">{feature.description}</Typography>
                  </Box>
                </Box>
                <Switch
                  checked={business?.feature_flags?.[feature.key] ?? feature.defaultEnabled}
                  onChange={(e) => {
                    const updatedFlags = { ...(business?.feature_flags || {}), [feature.key]: e.target.checked };
                    setBusiness((prev: any) => prev ? { ...prev, feature_flags: updatedFlags } : prev);
                    setFeatureFlagsText(JSON.stringify(updatedFlags, null, 2));
                  }}
                />
              </Box>
            ))}

            <Divider sx={{ my: 3 }} />

            <Typography variant="subtitle1" sx={{ mb: 1 }}>
              Feature flags (JSON)
            </Typography>
            <TextField
              multiline
              minRows={4}
              fullWidth
              value={featureFlagsText}
              onChange={(event) => setFeatureFlagsText(event.target.value)}
            />

            <Typography variant="subtitle1" sx={{ mt: 3, mb: 1 }}>
              Limits (JSON)
            </Typography>
            <TextField
              multiline
              minRows={4}
              fullWidth
              value={limitsText}
              onChange={(event) => setLimitsText(event.target.value)}
            />

            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 3 }}>
              <Button variant="contained" onClick={handleSaveOverview} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </Button>
            </Box>
          </Paper>
        )}

        {tab === 'members' && (
          <Paper sx={{ p: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="h6">Members</Typography>
              <Button variant="contained" onClick={() => setMemberDialogOpen(true)}>
                Add member
              </Button>
            </Box>
            {members.length === 0 ? (
              <Typography color="text.secondary">No members yet.</Typography>
            ) : (
              members.map((member) => (
                <Box key={member.id} sx={{ display: 'flex', justifyContent: 'space-between', py: 1 }}>
                  <Box>
                    <Typography>{member.invited_email}</Typography>
                    <Typography variant="caption" color="text.secondary">{member.role}</Typography>
                  </Box>
                  <Chip label={member.is_active ? 'Active' : 'Inactive'} size="small" />
                </Box>
              ))
            )}
          </Paper>
        )}

        {tab === 'integrations' && (
          <Box sx={{ display: 'grid', gap: 2 }}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Awaz</Typography>
              {awaz ? (
                <>
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
                    <Chip label={awaz.connected ? 'Connected' : 'Not connected'} color={awaz.connected ? 'success' : 'default'} />
                    <Typography variant="body2" color="text.secondary">
                      Last received: {awaz.last_received_at || 'Never'}
                    </Typography>
                  </Box>
                  {awaz.last_error && (
                    <Alert severity="warning" sx={{ mb: 2 }}>
                      Last error: {awaz.last_error}
                    </Alert>
                  )}
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Receptionist: {awaz.receptionist_name || 'Not set'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Phone number: {awaz.phone_number || 'Not set'}
                  </Typography>
                  <TextField label="Webhook URL" value={awaz.webhook_url} fullWidth InputProps={{ readOnly: true }} />
                  <Box sx={{ display: 'flex', gap: 2, mt: 2 }}>
                    <Button variant="outlined" onClick={handleTestAwaz}>Test connection</Button>
                    <Button variant="outlined" color="warning" onClick={handleRotateAwaz}>Rotate key</Button>
                  </Box>
                </>
              ) : (
                <Typography color="text.secondary">No Awaz integration data.</Typography>
              )}
            </Paper>

            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Email</Typography>
              <Typography variant="body2" color="text.secondary">
                Accounts: {emailAccounts.length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Default: {defaultEmail?.email_address || 'None'}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Last sync: {emailSyncState?.last_synced_at || 'Never'}
              </Typography>
            </Paper>

            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Calendar</Typography>
              <Typography variant="body2" color="text.secondary">
                Last sync: {calendarSyncState?.last_synced_at || 'Never'}
              </Typography>
              {calendarSyncState?.last_error && (
                <Typography variant="body2" color="error">
                  Error: {calendarSyncState.last_error}
                </Typography>
              )}
            </Paper>

            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Accounting</Typography>
              {accountingConnection?.connected ? (
                <>
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
                    <Chip
                      label={accountingConnection.provider === 'freeagent' ? 'FreeAgent' : accountingConnection.provider === 'quickbooks' ? 'QuickBooks' : 'Xero'}
                      color="success"
                      size="small"
                    />
                  </Box>
                  <Typography variant="body2" color="text.secondary">
                    Organisation: {accountingConnection.tenant_name || 'Unknown'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                    Last synced: {accountingConnection.last_sync_at ? new Date(accountingConnection.last_sync_at).toLocaleString() : 'Never'}
                  </Typography>
                  <Button variant="outlined" color="warning" size="small" sx={{ mt: 2 }} onClick={handleAccountingDisconnect}>
                    Disconnect
                  </Button>
                </>
              ) : (
                <>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    The business owner needs to connect their accounting software from their dashboard. Available providers:
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mb: 2 }}>
                    <Typography variant="body2">Xero — configured and ready</Typography>
                    <Typography variant="body2">FreeAgent — configured and ready</Typography>
                    <Typography variant="body2">QuickBooks — configured and ready</Typography>
                  </Box>
                  <Chip label="Pending owner action" size="small" color="warning" />
                </>
              )}
            </Paper>
          </Box>
        )}

        {tab === 'activity' && (
          <Box sx={{ display: 'grid', gap: 2 }}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Quick stats</Typography>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <Chip label={`Open tasks: ${openTasksCount}`} />
                <Chip label={`Calls last 7 days: ${callsLast7Days}`} />
              </Box>
            </Paper>

            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Recent calls</Typography>
              {recentCalls.length === 0 ? (
                <Typography color="text.secondary">No recent calls.</Typography>
              ) : (
                recentCalls.map((call) => (
                  <Box key={call.id} sx={{ py: 1 }}>
                    <Typography variant="body2">
                      {call.caller_name || call.caller_number || 'Unknown'} — {call.summary || 'No summary'}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(call.created_at).toLocaleString()}
                    </Typography>
                  </Box>
                ))
              )}
            </Paper>

            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Recent tasks</Typography>
              {recentTasks.length === 0 ? (
                <Typography color="text.secondary">No recent tasks.</Typography>
              ) : (
                recentTasks.map((task) => (
                  <Box key={task.id} sx={{ py: 1 }}>
                    <Typography variant="body2">{task.title}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {task.status} • {new Date(task.created_at).toLocaleString()}
                    </Typography>
                  </Box>
                ))
              )}
            </Paper>
          </Box>
        )}

        {tab === 'support' && (
          <Box sx={{ display: 'grid', gap: 2 }}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Quick create ticket</Typography>
              <Box sx={{ display: 'grid', gap: 2 }}>
                <TextField
                  label="Subject"
                  value={supportTitle}
                  onChange={(event) => setSupportTitle(event.target.value)}
                />
                <TextField
                  label="Description"
                  value={supportMessage}
                  onChange={(event) => setSupportMessage(event.target.value)}
                  multiline
                  minRows={3}
                />
                <FormControl fullWidth>
                  <InputLabel>Priority</InputLabel>
                  <Select
                    value={supportSeverity}
                    label="Priority"
                    onChange={(event) => setSupportSeverity(event.target.value)}
                  >
                    {SUPPORT_PRIORITIES.map((priority) => (
                      <MenuItem key={priority} value={priority}>
                        {priority}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <Button
                    variant="contained"
                    onClick={handleCreateSupportTicket}
                    disabled={supportSaving || !supportTitle.trim() || !supportMessage.trim()}
                  >
                    {supportSaving ? 'Creating...' : 'Create ticket'}
                  </Button>
                </Box>
              </Box>
            </Paper>

            <Paper sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6">Recent tickets</Typography>
                <Button variant="outlined" onClick={() => navigate(`/admin/support?business_id=${id}`)}>
                  View all tickets
                </Button>
              </Box>
              {supportLoading ? (
                <Typography color="text.secondary">Loading...</Typography>
              ) : supportTickets.length === 0 ? (
                <Typography color="text.secondary">No tickets yet.</Typography>
              ) : (
                supportTickets.map((ticket) => (
                  <Box key={ticket.id} sx={{ borderBottom: '1px solid', borderColor: 'divider', py: 1.5 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Typography variant="subtitle1">{ticket.title}</Typography>
                      <Box sx={{ display: 'flex', gap: 1 }}>
                        <Chip label={ticket.status} size="small" />
                        <Chip label={ticket.severity} size="small" color={ticket.severity === 'urgent' ? 'error' : 'default'} />
                      </Box>
                    </Box>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(ticket.created_at).toLocaleString()}
                    </Typography>
                    <Box sx={{ mt: 1 }}>
                      <Button size="small" variant="outlined" onClick={() => handleOpenTicketEdit(ticket)}>
                        Edit ticket
                      </Button>
                    </Box>
                  </Box>
                ))
              )}
            </Paper>
          </Box>
        )}
      </Container>

      <Dialog open={memberDialogOpen} onClose={() => setMemberDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add member</DialogTitle>
        <DialogContent>
          <TextField
            label="User Email"
            type="email"
            fullWidth
            value={memberEmail}
            onChange={(event) => setMemberEmail(event.target.value)}
            sx={{ mt: 1, mb: 2 }}
          />
          <FormControl fullWidth>
            <InputLabel>Role</InputLabel>
            <Select
              value={memberRole}
              label="Role"
              onChange={(event) => setMemberRole(event.target.value)}
            >
              {ROLES.map((role) => (
                <MenuItem key={role} value={role}>
                  {role}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMemberDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleAddMember} disabled={savingMember || !memberEmail.trim()}>
            {savingMember ? 'Adding...' : 'Add member'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!selectedTicket} onClose={() => setSelectedTicket(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit support ticket</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {selectedTicket?.title}
          </Typography>
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>Status</InputLabel>
            <Select value={ticketStatus} label="Status" onChange={(e) => setTicketStatus(e.target.value)}>
              {['open', 'in_progress', 'resolved', 'closed'].map((status) => (
                <MenuItem key={status} value={status}>
                  {status}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>Priority</InputLabel>
            <Select value={ticketSeverity} label="Priority" onChange={(e) => setTicketSeverity(e.target.value)}>
              {SUPPORT_PRIORITIES.map((priority) => (
                <MenuItem key={priority} value={priority}>
                  {priority}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Admin note"
            value={ticketNotes}
            onChange={(e) => setTicketNotes(e.target.value)}
            multiline
            minRows={3}
            fullWidth
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelectedTicket(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleUpdateTicket} disabled={supportSaving}>
            {supportSaving ? 'Saving...' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
