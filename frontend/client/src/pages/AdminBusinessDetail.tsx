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
import { supabase, type Business, type BusinessMember } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';

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

type TabKey = 'overview' | 'members' | 'integrations' | 'activity';

const PLAN_TIERS = ['starter', 'pro', 'elite', 'beta', 'paused'];
const ROLES = ['owner', 'admin', 'member'];

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

  useEffect(() => {
    if (id) {
      loadBusiness();
    }
  }, [id]);

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
      const response = await apiRequest('POST', `/v1/integrations/awaz/test?business_id=${id}`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to test integration');
      }
      await loadAwaz();
      await loadActivity();
    } catch (err: any) {
      setError(err.message || 'Failed to test integration');
    }
  };

  const defaultEmail = useMemo(
    () => emailAccounts.find((account) => account.is_default),
    [emailAccounts],
  );

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
            Back to Admin
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
          </Tabs>
        </Paper>

        {tab === 'overview' && (
          <Paper sx={{ p: 3 }}>
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
    </Box>
  );
}
