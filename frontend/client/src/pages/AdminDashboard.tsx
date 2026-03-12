import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  Button,
  Container,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  IconButton,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Divider,
  CircularProgress,
  Alert,
  useTheme,
  useMediaQuery,
} from '@mui/material';
import {
  Menu as MenuIcon,
  Dashboard as DashboardIcon,
  Business as BusinessIcon,
  People as PeopleIcon,
  Add as AddIcon,
  Logout as LogoutIcon,
  RocketLaunch as RocketLaunchIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, type BusinessMember } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';
import DebugPanel from '@/components/DebugPanel';
import { ReceptionistStatusChip } from '@/components/AdminReceptionistSection';
import { fetchAdminWhatsAppOverview } from '@/lib/whatsappApi';

const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Europe/London',
  'Europe/Paris',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
];

const ROLES = ['owner', 'admin', 'member'];
const PLAN_TIERS = ['starter', 'pro', 'elite', 'beta'];
const SUBSCRIPTION_STATUSES = ['active', 'past_due', 'canceled'];

interface BusinessSummary {
  id: string;
  name: string;
  timezone: string;
  plan_tier: string | null;
  is_active: boolean | null;
  subscription_status: string | null;
  awaz_connected: boolean;
  email_connected: boolean;
  calendar_connected: boolean;
  open_ticket_count: number;
  last_activity_at: string | null;
  last_awaz_webhook_at: string | null;
  last_email_sync_at: string | null;
  last_calendar_sync_at: string | null;
}
const FEATURE_PRESETS: Record<string, { feature_flags: Record<string, any>; limits: Record<string, any> }> = {
  starter: { feature_flags: { ai_briefings: false }, limits: { users: 3, tasks: 200 } },
  pro: { feature_flags: { ai_briefings: true }, limits: { users: 10, tasks: 1000 } },
  elite: { feature_flags: { ai_briefings: true, premium_support: true }, limits: { users: 50, tasks: 5000 } },
};

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user, signOut, isAdmin, loading: authLoading, adminLoading } = useAuth();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'businesses' | 'members'>('businesses');
  const [businesses, setBusinesses] = useState<BusinessSummary[]>([]);
  const [members, setMembers] = useState<(BusinessMember & { business_name?: string })[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [businessDialogOpen, setBusinessDialogOpen] = useState(false);
  const [businessName, setBusinessName] = useState('');
  const [businessTimezone, setBusinessTimezone] = useState('America/New_York');
  const [savingBusiness, setSavingBusiness] = useState(false);
  const [businessPlanTier, setBusinessPlanTier] = useState('starter');
  const [businessIsActive, setBusinessIsActive] = useState(true);
  const [businessTrialEndsAt, setBusinessTrialEndsAt] = useState('');
  const [featurePreset, setFeaturePreset] = useState('starter');
  const [featureFlags, setFeatureFlags] = useState<Record<string, any>>(FEATURE_PRESETS.starter.feature_flags);
  const [limits, setLimits] = useState<Record<string, any>>(FEATURE_PRESETS.starter.limits);

  const [memberDialogOpen, setMemberDialogOpen] = useState(false);
  const [memberEmail, setMemberEmail] = useState('');
  const [memberBusinessId, setMemberBusinessId] = useState('');
  const [memberRole, setMemberRole] = useState('member');
  const [savingMember, setSavingMember] = useState(false);

  const [searchTerm, setSearchTerm] = useState('');
  const [filterPlan, setFilterPlan] = useState('all');
  const [filterActive, setFilterActive] = useState('all');
  const [filterSubscription, setFilterSubscription] = useState('all');
  const [filterAwaz, setFilterAwaz] = useState('all');
  const [filterEmail, setFilterEmail] = useState('all');
  const [filterCalendar, setFilterCalendar] = useState('all');
  const [filterReceptionist, setFilterReceptionist] = useState('all');
  const [receptionistOverview, setReceptionistOverview] = useState<Record<string, { enabled: boolean; config_exists: boolean }>>({});
  const [whatsappOverview, setWhatsappOverview] = useState<Record<string, { configured: boolean; enabled: boolean }>>({});
  const [onboardingStatus, setOnboardingStatus] = useState<Record<string, { onboarding_completed: boolean; checklist_progress: number; checklist_total: number }>>({});
  const [accountingConnections, setAccountingConnections] = useState<Record<string, { provider: string; tenant_name?: string; is_active: boolean; last_sync_at?: string | null }>>({});
  const [toggleDialogOpen, setToggleDialogOpen] = useState(false);
  const [toggleTarget, setToggleTarget] = useState<BusinessSummary | null>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    } else if (!authLoading && !adminLoading && !isAdmin) {
      navigate('/app');
    }
  }, [user, isAdmin, authLoading, adminLoading, navigate]);

  useEffect(() => {
    if (user && isAdmin) {
      fetchData();
    }
  }, [user, isAdmin]);

  const fetchData = async () => {
    setLoading(true);
    setError('');
    
    try {
      const response = await apiRequest('GET', '/v1/admin/businesses/summary');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to fetch businesses');
      }
      const businessData = await response.json();
      setBusinesses(businessData || []);

      const { data: memberData, error: memberError } = await supabase
        .from('business_members')
        .select('*, businesses(name)')
        .order('created_at', { ascending: false });

      if (memberError) throw memberError;
      
      const formattedMembers = (memberData || []).map((m: any) => ({
        ...m,
        business_name: m.businesses?.name,
      }));
      setMembers(formattedMembers);

      // Fetch receptionist overview (non-blocking — don't fail the whole page)
      try {
        const recRes = await apiRequest('GET', '/v1/admin/receptionist/overview');
        const recData: any[] = await recRes.json();
        const recMap: Record<string, { enabled: boolean; config_exists: boolean }> = {};
        for (const item of recData) {
          recMap[item.business_id] = { enabled: !!item.enabled, config_exists: !!item.config_exists };
        }
        setReceptionistOverview(recMap);
      } catch { /* receptionist overview is optional */ }

      try {
        const obRes = await apiRequest('GET', '/v1/admin/onboarding/status');
        const obData: any[] = await obRes.json();
        const obMap: Record<string, { onboarding_completed: boolean; checklist_progress: number; checklist_total: number }> = {};
        for (const item of obData) {
          obMap[item.business_id] = { onboarding_completed: !!item.onboarding_completed, checklist_progress: item.checklist_progress || 0, checklist_total: item.checklist_total || 0 };
        }
        setOnboardingStatus(obMap);
      } catch { /* onboarding status is optional */ }

      try {
        const acctRes = await apiRequest('GET', '/v1/admin/accounting/overview');
        const acctData: any[] = await acctRes.json();
        const acctMap: Record<string, { provider: string; tenant_name?: string; is_active: boolean; last_sync_at?: string | null }> = {};
        for (const conn of acctData) {
          acctMap[conn.business_id] = { provider: conn.provider, tenant_name: conn.tenant_name, is_active: !!conn.is_active, last_sync_at: conn.last_sync_at };
        }
        setAccountingConnections(acctMap);
      } catch { /* accounting overview is optional */ }

      try {
        const waRes = await fetchAdminWhatsAppOverview();
        const waMap: Record<string, { configured: boolean; enabled: boolean }> = {};
        for (const item of waRes) {
          waMap[item.business_id] = { configured: true, enabled: !!item.enabled };
        }
        setWhatsappOverview(waMap);
      } catch { /* WhatsApp overview is optional */ }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  };

  const memberEmailMap = useMemo(() => {
    const map: Record<string, string[]> = {};
    members.forEach((member) => {
      if (!member.business_id || !member.invited_email) return;
      if (!map[member.business_id]) {
        map[member.business_id] = [];
      }
      map[member.business_id].push(member.invited_email.toLowerCase());
    });
    return map;
  }, [members]);

  const filteredBusinesses = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return businesses.filter((biz) => {
      if (term) {
        const nameMatch = biz.name.toLowerCase().includes(term);
        const memberMatch = (memberEmailMap[biz.id] || []).some((email) => email.includes(term));
        if (!nameMatch && !memberMatch) return false;
      }
      if (filterPlan !== 'all' && (biz.plan_tier || 'starter') !== filterPlan) return false;
      if (filterActive !== 'all') {
        const activeValue = filterActive === 'active';
        if (Boolean(biz.is_active) !== activeValue) return false;
      }
      if (filterSubscription !== 'all' && (biz.subscription_status || 'none') !== filterSubscription) return false;
      if (filterAwaz !== 'all') {
        const awazValue = filterAwaz === 'connected';
        if (Boolean(biz.awaz_connected) !== awazValue) return false;
      }
      if (filterEmail !== 'all') {
        const emailValue = filterEmail === 'connected';
        if (Boolean(biz.email_connected) !== emailValue) return false;
      }
      if (filterCalendar !== 'all') {
        const calValue = filterCalendar === 'connected';
        if (Boolean(biz.calendar_connected) !== calValue) return false;
      }
      if (filterReceptionist !== 'all') {
        const rec = receptionistOverview[biz.id];
        if (filterReceptionist === 'active' && !(rec?.enabled)) return false;
        if (filterReceptionist === 'configured' && !(rec?.config_exists && !rec?.enabled)) return false;
        if (filterReceptionist === 'not_set_up' && rec?.config_exists) return false;
      }
      return true;
    });
  }, [
    businesses,
    searchTerm,
    filterPlan,
    filterActive,
    filterSubscription,
    filterAwaz,
    filterEmail,
    filterCalendar,
    filterReceptionist,
    receptionistOverview,
    memberEmailMap,
  ]);

  const handleCopyBusinessId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
    } catch {
      setError('Failed to copy business ID');
    }
  };

  const confirmToggleActive = (business: BusinessSummary) => {
    setToggleTarget(business);
    setToggleDialogOpen(true);
  };

  const handleToggleActive = async () => {
    if (!toggleTarget) return;
    setError('');
    try {
      const { error: updateError } = await supabase
        .from('businesses')
        .update({ is_active: !toggleTarget.is_active })
        .eq('id', toggleTarget.id);
      if (updateError) throw updateError;
      setToggleDialogOpen(false);
      setToggleTarget(null);
      fetchData();
    } catch (err: any) {
      setError(err.message || 'Failed to update business');
    }
  };

  const generateApiKey = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let key = 'bh_';
    for (let i = 0; i < 32; i++) {
      key += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return key;
  };

  const handleFeaturePresetChange = (preset: string) => {
    setFeaturePreset(preset);
    const values = FEATURE_PRESETS[preset];
    if (values) {
      setFeatureFlags(values.feature_flags);
      setLimits(values.limits);
    }
  };

  const handleCreateBusiness = async () => {
    if (!businessName.trim()) return;
    
    setSavingBusiness(true);
    setError('');

    try {
      const { error: insertError } = await supabase
        .from('businesses')
        .insert({
          name: businessName.trim(),
          timezone: businessTimezone,
          api_key: generateApiKey(),
          plan_tier: businessPlanTier,
          is_active: businessIsActive,
          trial_ends_at: businessTrialEndsAt ? new Date(businessTrialEndsAt).toISOString() : null,
          feature_flags: featureFlags,
          limits,
        });

      if (insertError) throw insertError;

      setBusinessDialogOpen(false);
      setBusinessName('');
      setBusinessTimezone('America/New_York');
      setBusinessPlanTier('starter');
      setBusinessIsActive(true);
      setBusinessTrialEndsAt('');
      handleFeaturePresetChange('starter');
      fetchData();
    } catch (err: any) {
      setError(err.message || 'Failed to create business');
    } finally {
      setSavingBusiness(false);
    }
  };

  const handleCreateMember = async () => {
    if (!memberEmail.trim() || !memberBusinessId) return;
    
    setSavingMember(true);
    setError('');

    try {
      const { error: insertError } = await supabase
        .from('business_members')
        .insert({
          business_id: memberBusinessId,
          invited_email: memberEmail.trim().toLowerCase(),
          role: memberRole,
          is_active: true,
        });

      if (insertError) throw insertError;

      setMemberDialogOpen(false);
      setMemberEmail('');
      setMemberBusinessId('');
      setMemberRole('member');
      fetchData();
    } catch (err: any) {
      setError(err.message || 'Failed to create member');
    } finally {
      setSavingMember(false);
    }
  };

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  const drawerContent = (
    <Box sx={{ width: 240 }}>
      <Toolbar>
        <BusinessIcon sx={{ mr: 1 }} />
        <Typography variant="h6" noWrap>
          Platform Admin
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        <ListItem disablePadding>
          <ListItemButton
            selected={activeTab === 'businesses'}
            onClick={() => {
              setActiveTab('businesses');
              setDrawerOpen(false);
            }}
            data-testid="nav-businesses"
          >
            <ListItemIcon>
              <BusinessIcon />
            </ListItemIcon>
            <ListItemText primary="Businesses" />
          </ListItemButton>
        </ListItem>
        <ListItem disablePadding>
          <ListItemButton
            selected={activeTab === 'members'}
            onClick={() => {
              setActiveTab('members');
              setDrawerOpen(false);
            }}
            data-testid="nav-members"
          >
            <ListItemIcon>
              <PeopleIcon />
            </ListItemIcon>
            <ListItemText primary="Members" />
          </ListItemButton>
        </ListItem>
        <ListItem disablePadding>
          <ListItemButton
            onClick={() => {
              navigate('/admin/onboarding');
              setDrawerOpen(false);
            }}
            data-testid="nav-onboarding"
          >
            <ListItemIcon>
              <RocketLaunchIcon />
            </ListItemIcon>
            <ListItemText primary="Onboarding" />
          </ListItemButton>
        </ListItem>
        <ListItem disablePadding>
          <ListItemButton
            onClick={() => {
              navigate('/admin/support');
              setDrawerOpen(false);
            }}
            data-testid="nav-support"
          >
            <ListItemIcon>
              <DashboardIcon />
            </ListItemIcon>
            <ListItemText primary="Support" />
          </ListItemButton>
        </ListItem>
      </List>
      <Divider />
      <List>
        <ListItem disablePadding>
          <ListItemButton onClick={handleSignOut} data-testid="button-signout">
            <ListItemIcon>
              <LogoutIcon />
            </ListItemIcon>
            <ListItemText primary="Sign Out" />
          </ListItemButton>
        </ListItem>
      </List>
    </Box>
  );

  if (authLoading || adminLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', width: '100%', overflow: 'hidden' }}>
      <AppBar position="fixed" sx={{ zIndex: theme.zIndex.drawer + 1 }}>
        <Toolbar>
          {isMobile && (
            <IconButton
              color="inherit"
              edge="start"
              onClick={() => setDrawerOpen(!drawerOpen)}
              sx={{ mr: 2 }}
              data-testid="button-menu"
            >
              <MenuIcon />
            </IconButton>
          )}
          <DashboardIcon sx={{ mr: 1 }} />
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>
            Admin Dashboard
          </Typography>
          <Typography variant="body2" sx={{ mr: 2 }}>
            {user?.email}
          </Typography>
        </Toolbar>
      </AppBar>

      {isMobile ? (
        <Drawer
          variant="temporary"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          ModalProps={{ keepMounted: true }}
        >
          {drawerContent}
        </Drawer>
      ) : (
        <Drawer variant="permanent" sx={{ width: 240, flexShrink: 0 }}>
          {drawerContent}
        </Drawer>
      )}

      <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: 3, mt: 8, ml: isMobile ? 0 : '240px', overflowX: 'auto' }}>
        <Container maxWidth="xl" sx={{ px: { xs: 1, sm: 2, md: 3 } }}>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')} data-testid="alert-error">
              {error}
            </Alert>
          )}

          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, gap: 2, flexWrap: 'wrap' }}>
            <Typography variant="h4" component="h1">
              {activeTab === 'businesses' ? 'Businesses' : 'Business Members'}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="contained"
                startIcon={<RocketLaunchIcon />}
                onClick={() => navigate('/admin/onboarding/new')}
                data-testid="button-onboard-business"
              >
                Onboard Business
              </Button>
              <Button
                variant="outlined"
                startIcon={<AddIcon />}
                onClick={() => setBusinessDialogOpen(true)}
                data-testid="button-create-business"
              >
                Quick Create
              </Button>
              <Button
                variant="outlined"
                startIcon={<AddIcon />}
                onClick={() => setMemberDialogOpen(true)}
                data-testid="button-add-member"
              >
                Add Member
              </Button>
            </Box>
          </Box>

          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress />
            </Box>
          ) : activeTab === 'businesses' ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Paper sx={{ p: 2, overflow: 'hidden' }}>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
                  <TextField
                    label="Search businesses"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    sx={{ minWidth: 180, flex: '1 1 180px' }}
                    size="small"
                  />
                  <FormControl size="small" sx={{ minWidth: 110 }}>
                    <InputLabel>Plan</InputLabel>
                    <Select value={filterPlan} label="Plan" onChange={(e) => setFilterPlan(e.target.value)}>
                      <MenuItem value="all">All</MenuItem>
                      {PLAN_TIERS.map((tier) => (
                        <MenuItem key={tier} value={tier}>
                          {tier}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 110 }}>
                    <InputLabel>Status</InputLabel>
                    <Select value={filterActive} label="Status" onChange={(e) => setFilterActive(e.target.value)}>
                      <MenuItem value="all">All</MenuItem>
                      <MenuItem value="active">Active</MenuItem>
                      <MenuItem value="paused">Paused</MenuItem>
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 130 }}>
                    <InputLabel>Subscription</InputLabel>
                    <Select
                      value={filterSubscription}
                      label="Subscription"
                      onChange={(e) => setFilterSubscription(e.target.value)}
                    >
                      <MenuItem value="all">All</MenuItem>
                      {SUBSCRIPTION_STATUSES.map((status) => (
                        <MenuItem key={status} value={status}>
                          {status}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 110 }}>
                    <InputLabel>Awaz</InputLabel>
                    <Select value={filterAwaz} label="Awaz" onChange={(e) => setFilterAwaz(e.target.value)}>
                      <MenuItem value="all">All</MenuItem>
                      <MenuItem value="connected">Connected</MenuItem>
                      <MenuItem value="not_connected">Not connected</MenuItem>
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 110 }}>
                    <InputLabel>Email</InputLabel>
                    <Select value={filterEmail} label="Email" onChange={(e) => setFilterEmail(e.target.value)}>
                      <MenuItem value="all">All</MenuItem>
                      <MenuItem value="connected">Connected</MenuItem>
                      <MenuItem value="not_connected">Not connected</MenuItem>
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 120 }}>
                    <InputLabel>Calendar</InputLabel>
                    <Select
                      value={filterCalendar}
                      label="Calendar"
                      onChange={(e) => setFilterCalendar(e.target.value)}
                    >
                      <MenuItem value="all">All</MenuItem>
                      <MenuItem value="connected">Connected</MenuItem>
                      <MenuItem value="not_connected">Not connected</MenuItem>
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 130 }}>
                    <InputLabel>Receptionist</InputLabel>
                    <Select
                      value={filterReceptionist}
                      label="Receptionist"
                      onChange={(e) => setFilterReceptionist(e.target.value)}
                    >
                      <MenuItem value="all">All</MenuItem>
                      <MenuItem value="active">Active</MenuItem>
                      <MenuItem value="configured">Configured</MenuItem>
                      <MenuItem value="not_set_up">Not set up</MenuItem>
                    </Select>
                  </FormControl>
                </Box>
              </Paper>

              <TableContainer component={Paper} elevation={1} sx={{ overflowX: 'auto' }}>
                <Table size="small" sx={{ minWidth: 1100 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>Name</TableCell>
                      <TableCell>Plan</TableCell>
                      <TableCell>Sub</TableCell>
                      <TableCell>Awaz</TableCell>
                      <TableCell>Email</TableCell>
                      <TableCell>Calendar</TableCell>
                      <TableCell>Accounting</TableCell>
                      <TableCell>Recept.</TableCell>
                      <TableCell>Briefing</TableCell>
                      <TableCell>Onboard.</TableCell>
                      <TableCell>Tickets</TableCell>
                      <TableCell>Last activity</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {filteredBusinesses.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={13} align="center" sx={{ py: 4 }}>
                          <Typography color="text.secondary">No businesses found</Typography>
                        </TableCell>
                      </TableRow>
                    ) : (
                      filteredBusinesses.map((business) => (
                        <TableRow key={business.id} data-testid={`row-business-${business.id}`}>
                          <TableCell>
                            <Typography fontWeight="medium">{business.name}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              {business.id}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Chip label={business.plan_tier || 'starter'} size="small" variant="outlined" />
                          </TableCell>
                          <TableCell>
                            <Chip
                              label={business.subscription_status || 'none'}
                              size="small"
                              color={business.subscription_status === 'active' ? 'success' : 'default'}
                            />
                          </TableCell>
                          <TableCell>
                            <Chip
                              label={business.awaz_connected ? 'Connected' : 'Not connected'}
                              size="small"
                              color={business.awaz_connected ? 'success' : 'default'}
                            />
                          </TableCell>
                          <TableCell>
                            <Chip
                              label={business.email_connected ? 'Connected' : 'Not connected'}
                              size="small"
                              color={business.email_connected ? 'success' : 'default'}
                            />
                          </TableCell>
                          <TableCell>
                            <Chip
                              label={business.calendar_connected ? 'Connected' : 'Not connected'}
                              size="small"
                              color={business.calendar_connected ? 'success' : 'default'}
                            />
                          </TableCell>
                          <TableCell>
                            {(() => {
                              const acct = accountingConnections[business.id];
                              const label = acct?.is_active
                                ? acct.provider === 'freeagent'
                                  ? 'FreeAgent'
                                  : acct.provider === 'quickbooks'
                                    ? 'QuickBooks'
                                    : acct.provider === 'xero'
                                      ? 'Xero'
                                      : 'Connected'
                                : 'Not connected';
                              return (
                                <Chip
                                  label={label}
                                  size="small"
                                  color={acct?.is_active ? 'success' : 'default'}
                                />
                              );
                            })()}
                          </TableCell>
                          <TableCell>
                            <ReceptionistStatusChip overview={receptionistOverview[business.id]} />
                          </TableCell>
                          <TableCell>
                            {(() => {
                              const wa = whatsappOverview[business.id];
                              if (wa?.configured) {
                                return <Chip label={wa.enabled ? '📱 Active' : '📱 Disabled'} size="small" color={wa.enabled ? 'success' : 'default'} />;
                              }
                              return <Typography variant="body2" color="text.secondary">Not configured</Typography>;
                            })()}
                          </TableCell>
                          <TableCell>
                            {(() => {
                              const ob = onboardingStatus[business.id];
                              if (!ob || ob.checklist_total === 0) return <Chip label="Not onboarded" size="small" />;
                              if (ob.onboarding_completed) return <Chip label="Complete" size="small" color="success" />;
                              return <Chip label={`${ob.checklist_progress}%`} size="small" color="warning" />;
                            })()}
                          </TableCell>
                          <TableCell>{business.open_ticket_count}</TableCell>
                          <TableCell>
                            {business.last_activity_at
                              ? new Date(business.last_activity_at).toLocaleString()
                              : '—'}
                          </TableCell>
                          <TableCell align="right">
                            <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, flexWrap: 'wrap' }}>
                              <Button
                                variant="outlined"
                                size="small"
                                onClick={() => navigate(`/admin/businesses/${business.id}`)}
                              >
                                Manage
                              </Button>
                              <Button
                                variant="outlined"
                                size="small"
                                onClick={() => handleCopyBusinessId(business.id)}
                              >
                                Copy ID
                              </Button>
                              <Button
                                variant="outlined"
                                size="small"
                                color={business.is_active === false ? 'success' : 'warning'}
                                onClick={() => confirmToggleActive(business)}
                              >
                                {business.is_active === false ? 'Activate' : 'Pause'}
                              </Button>
                            </Box>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          ) : (
            <TableContainer component={Paper} elevation={1}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Email</TableCell>
                    <TableCell>Business</TableCell>
                    <TableCell>Role</TableCell>
                    <TableCell>Created</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {members.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} align="center" sx={{ py: 4 }}>
                        <Typography color="text.secondary">No members yet</Typography>
                      </TableCell>
                    </TableRow>
                  ) : (
                    members.map((member) => (
                      <TableRow key={member.id} data-testid={`row-member-${member.id}`}>
                        <TableCell>{member.invited_email}</TableCell>
                        <TableCell>{member.business_name || '-'}</TableCell>
                        <TableCell>
                          <Chip
                            label={member.role}
                            size="small"
                            color={member.role === 'owner' ? 'primary' : member.role === 'admin' ? 'secondary' : 'default'}
                          />
                        </TableCell>
                        <TableCell>
                          {new Date(member.created_at).toLocaleDateString()}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Container>
      </Box>

      <Dialog open={businessDialogOpen} onClose={() => setBusinessDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Business</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Business Name"
            fullWidth
            variant="outlined"
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            sx={{ mb: 2, mt: 1 }}
            data-testid="input-business-name"
          />
          <FormControl fullWidth>
            <InputLabel>Timezone</InputLabel>
            <Select
              value={businessTimezone}
              label="Timezone"
              onChange={(e) => setBusinessTimezone(e.target.value)}
              data-testid="select-timezone"
            >
              {TIMEZONES.map((tz) => (
                <MenuItem key={tz} value={tz}>
                  {tz}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth sx={{ mt: 2 }}>
            <InputLabel>Plan tier</InputLabel>
            <Select
              value={businessPlanTier}
              label="Plan tier"
              onChange={(e) => setBusinessPlanTier(e.target.value)}
            >
              {PLAN_TIERS.map((tier) => (
                <MenuItem key={tier} value={tier}>
                  {tier}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth sx={{ mt: 2 }}>
            <InputLabel>Active</InputLabel>
            <Select
              value={businessIsActive ? 'true' : 'false'}
              label="Active"
              onChange={(e) => setBusinessIsActive(e.target.value === 'true')}
            >
              <MenuItem value="true">Active</MenuItem>
              <MenuItem value="false">Paused</MenuItem>
            </Select>
          </FormControl>
          <TextField
            label="Trial ends at"
            type="datetime-local"
            fullWidth
            value={businessTrialEndsAt}
            onChange={(e) => setBusinessTrialEndsAt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ mt: 2 }}
          />
          <FormControl fullWidth sx={{ mt: 2 }}>
            <InputLabel>Feature preset</InputLabel>
            <Select
              value={featurePreset}
              label="Feature preset"
              onChange={(e) => handleFeaturePresetChange(e.target.value)}
            >
              {Object.keys(FEATURE_PRESETS).map((preset) => (
                <MenuItem key={preset} value={preset}>
                  {preset.charAt(0).toUpperCase() + preset.slice(1)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Preset applies feature flags and limits for the new business.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBusinessDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateBusiness}
            variant="contained"
            disabled={savingBusiness || !businessName.trim()}
            data-testid="button-save-business"
          >
            {savingBusiness ? <CircularProgress size={20} /> : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={toggleDialogOpen} onClose={() => setToggleDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Confirm status change</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary">
            {toggleTarget?.is_active === false
              ? `Activate ${toggleTarget?.name}?`
              : `Pause ${toggleTarget?.name}?`}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setToggleDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" color="warning" onClick={handleToggleActive}>
            Confirm
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={memberDialogOpen} onClose={() => setMemberDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Business Member</DialogTitle>
        <DialogContent>
          <FormControl fullWidth sx={{ mb: 2, mt: 1 }}>
            <InputLabel>Business</InputLabel>
            <Select
              value={memberBusinessId}
              label="Business"
              onChange={(e) => setMemberBusinessId(e.target.value)}
              data-testid="select-business"
            >
              {businesses.map((b) => (
                <MenuItem key={b.id} value={b.id}>
                  {b.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            margin="dense"
            label="User Email"
            type="email"
            fullWidth
            variant="outlined"
            value={memberEmail}
            onChange={(e) => setMemberEmail(e.target.value)}
            sx={{ mb: 2 }}
            data-testid="input-member-email"
          />
          <FormControl fullWidth>
            <InputLabel>Role</InputLabel>
            <Select
              value={memberRole}
              label="Role"
              onChange={(e) => setMemberRole(e.target.value)}
              data-testid="select-role"
            >
              {ROLES.map((role) => (
                <MenuItem key={role} value={role}>
                  {role.charAt(0).toUpperCase() + role.slice(1)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMemberDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateMember}
            variant="contained"
            disabled={savingMember || !memberEmail.trim() || !memberBusinessId}
            data-testid="button-save-member"
          >
            {savingMember ? <CircularProgress size={20} /> : 'Add Member'}
          </Button>
        </DialogActions>
      </Dialog>

      {import.meta.env.DEV && <DebugPanel />}
    </Box>
  );
}
