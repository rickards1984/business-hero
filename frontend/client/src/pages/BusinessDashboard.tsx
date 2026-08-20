import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  Button,
  Container,
  Paper,
  Card,
  Chip,
  TextField,
  CircularProgress,
  Alert,
  IconButton,
  Tabs,
  Tab,
  Divider,
  Avatar,
  Drawer,
  ListItemIcon,
  ListItemText,
  Snackbar,
  FormControlLabel,
  Switch,
  Menu,
  MenuItem,
  Tooltip,
  InputAdornment,
  Fab,
  Zoom,
} from '@mui/material';
import {
  Task as TaskIcon,
  Phone as PhoneIcon,
  Logout as LogoutIcon,
  AccessTime as AccessTimeIcon,
  Receipt as ReceiptIcon,
  Archive as ArchiveIcon,
  Email as EmailIcon,
  Close as CloseIcon,
  Settings as SettingsIcon,
  Outbox as OutboxIcon,
  SmartToy as SmartToyIcon,
  Payment as PaymentIcon,
  Palette as PaletteIcon,
  Help as HelpIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
  ChevronRight as ChevronRightIcon,
  AccountBalance as AccountBalanceIcon,
  MailOutline as MailOutlineIcon,
  Sms as SmsIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, type Business, type Call, type BusinessMember, resolveLogoSrc } from '@/lib/supabase';
import { useMe } from '@/hooks/useMe';
import { apiRequest } from '@/lib/queryClient';
import DebugPanel from '@/components/DebugPanel';
import EmailsTab from '@/components/EmailsTab';
import ReceptionistTab from '@/components/ReceptionistTab';
import CeoBriefingTab from '@/components/CeoBriefingTab';
import TasksPanel, { type TasksPanelHandle } from '@/components/TasksPanel';
import InvoicesPanel from '@/components/InvoicesPanel';
import BottomNav from '@/components/BottomNav';
import { fetchEmailMessages } from '@/lib/emailApi';
import { applyBrandColor } from '@/pages/BrandingSettings';
import SupportPanel from '@/components/SupportPanel';
import SupportHelpButton from '@/components/SupportHelpButton';

/**
 * Get business initials from name
 */
function getBusinessInitials(name: string): string {
  return name
    .split(' ')
    .map(word => word[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  const active = value === index;
  return (
    <div
      role="tabpanel"
      style={{ display: active ? 'block' : 'none' }}
      {...other}
    >
      <Box sx={{ pt: 3 }}>{children}</Box>
    </div>
  );
}

export default function BusinessDashboard() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user, signOut, loading: authLoading } = useAuth();
  const { data: businessProfile } = useMe();

  useEffect(() => {
    if (businessProfile?.brand_color) {
      applyBrandColor(businessProfile.brand_color);
    }
  }, [businessProfile?.brand_color]);
  
  const [tabValue, setTabValue] = useState(() => {
    const tab = searchParams.get('tab');
    if (tab === 'ceo-briefing') return 5;
    if (tab === 'receptionist') return 4;
    if (tab === 'emails') return 3;
    if (tab === 'invoices') return 2;
    if (tab === 'calls') return 1;
    return 0;
  });
  const [membership, setMembership] = useState<BusinessMember | null>(null);
  // Only the columns this page selects — api_key is deliberately absent.
  type DashboardBusiness = Pick<Business, 'id' | 'name' | 'timezone' | 'logo_url'>;
  const [business, setBusiness] = useState<DashboardBusiness | null>(null);
  const [calls, setCalls] = useState<Call[]>([]);
  const [callSearch, setCallSearch] = useState('');
  const [callDateFilter, setCallDateFilter] = useState<'all' | 'today' | 'week' | 'month'>('all');
  const [callSourceFilter, setCallSourceFilter] = useState<'all' | 'receptionist' | 'Awaz'>('all');
  const [showArchivedCalls, setShowArchivedCalls] = useState(false);
  const [selectedCall, setSelectedCall] = useState<Call | null>(null);
  const [callPanelOpen, setCallPanelOpen] = useState(false);
  const [openTaskCount, setOpenTaskCount] = useState(0);
  const [settingsAnchor, setSettingsAnchor] = useState<null | HTMLElement>(null);
  const [supportPanelOpen, setSupportPanelOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const initialLoadDone = useRef(false);
  const tasksPanelRef = useRef<TasksPanelHandle>(null);
  const [mountedTabs, setMountedTabs] = useState<Set<number>>(() => new Set([tabValue]));
  
  const logoUrl = resolveLogoSrc(businessProfile?.logo_url ?? business?.logo_url);

  const [successMessage, setSuccessMessage] = useState('');

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      fetchUserBusiness();
    }
  }, [user]);

  useEffect(() => {
    setMountedTabs(prev => {
      if (prev.has(tabValue)) return prev;
      const next = new Set(prev);
      next.add(tabValue);
      return next;
    });
  }, [tabValue]);

  const fetchUserBusiness = async () => {
    if (!initialLoadDone.current) {
      setLoading(true);
    }
    setError('');

    try {
      const { data: memberRows, error: memberError } = await supabase
        .from('business_members')
        .select('business_id, role')
        .eq('user_id', user?.id);

      if (memberError) throw memberError;
      const memberData =
        memberRows?.find(row => row.role === 'owner') ??
        memberRows?.[0] ??
        null;
      if (!memberData) {
        const { data: adminData, error: adminError } = await supabase
          .from('platform_admins')
          .select('user_id')
          .eq('user_id', user?.id)
          .maybeSingle();
        if (adminError) throw adminError;
        if (adminData) {
          setError('No business assigned');
        } else {
          setError('No business assigned');
        }
        setMembership(null);
        setBusiness(null);
        setLoading(false);
        return;
      }

      setMembership(memberData as BusinessMember);
      const { data: businessData, error: businessError } = await supabase
        .from('businesses')
        .select('id,name,timezone,logo_url')
        .eq('id', memberData.business_id)
        .single();
      if (businessError) throw businessError;
      setBusiness(businessData);

      await fetchCalls(memberData.business_id);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch business data');
    } finally {
      setLoading(false);
      initialLoadDone.current = true;
    }
  };

  const fetchCalls = async (businessId: string) => {
    const { data, error } = await supabase
      .from('calls')
      .select('*')
      .eq('business_id', businessId)
      .order('created_at', { ascending: false });

    if (error) throw error;
    setCalls(data || []);
  };


  // Handler to archive/unarchive a call
  const handleArchiveCall = async (callId: string) => {
    try {
      const response = await apiRequest('PATCH', `/v1/calls/${callId}/archive`, {});
      if (response.ok) {
        const data = await response.json();
        // Update local state to toggle archived status
        setCalls(prev => prev.map(c => 
          c.id === callId ? { ...c, archived: data.archived } : c
        ));
      } else {
        console.error('Failed to archive call');
      }
    } catch (error) {
      console.error('Failed to archive call:', error);
    }
  };

  // Filter calls based on filters
  const filteredCalls = useMemo(() => {
    let result = calls;

    if (!showArchivedCalls) {
      result = result.filter(c => !c.archived);
    }

    if (callSourceFilter !== 'all') {
      result = result.filter(c => c.source === callSourceFilter);
    }

    if (callSearch) {
      const searchLower = callSearch.toLowerCase();
      result = result.filter(c =>
        (c.caller_name?.toLowerCase() || '').includes(searchLower) ||
        (c.caller_number?.toLowerCase() || '').includes(searchLower) ||
        (c.phone_number?.toLowerCase() || '').includes(searchLower) ||
        (c.summary?.toLowerCase() || '').includes(searchLower) ||
        (c.intent?.toLowerCase() || '').includes(searchLower)
      );
    }

    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfWeek = new Date(startOfToday);
    startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay());
    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);

    if (callDateFilter === 'today') {
      result = result.filter(c => new Date(c.created_at) >= startOfToday);
    } else if (callDateFilter === 'week') {
      result = result.filter(c => new Date(c.created_at) >= startOfWeek);
    } else if (callDateFilter === 'month') {
      result = result.filter(c => new Date(c.created_at) >= startOfMonth);
    }

    return result;
  }, [calls, callSearch, callDateFilter, callSourceFilter, showArchivedCalls]);
  
  // Group calls by date for better display
  const groupedCalls = useMemo(() => {
    const groups: { [key: string]: Call[] } = {};
    
    filteredCalls.forEach(call => {
      const date = new Date(call.created_at);
      const today = new Date();
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);
      
      let key: string;
      if (date.toDateString() === today.toDateString()) {
        key = 'Today';
      } else if (date.toDateString() === yesterday.toDateString()) {
        key = 'Yesterday';
      } else {
        key = date.toLocaleDateString('en-GB', { 
          weekday: 'long', 
          day: 'numeric', 
          month: 'long' 
        });
      }
      
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(call);
    });
    
    return groups;
  }, [filteredCalls]);
  
  // Calculate call stats
  const callStats = useMemo(() => {
    const today = new Date();
    const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());

    const activeCalls = calls.filter(c => !c.archived);
    const todaysCalls = activeCalls.filter(c => new Date(c.created_at) >= startOfToday);
    const receptionistCount = activeCalls.filter(c => c.source === 'receptionist').length;
    const awazCount = activeCalls.filter(c => c.source !== 'receptionist').length;

    return {
      today: todaysCalls.length,
      total: activeCalls.length,
      receptionist: receptionistCount,
      awaz: awazCount,
    };
  }, [calls]);
  
  const calculateDuration = (start: string, end: string): string => {
    const startDate = new Date(start);
    const endDate = new Date(end);
    const diffMs = endDate.getTime() - startDate.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffSecs = Math.floor((diffMs % 60000) / 1000);
    if (diffMins > 0) return `${diffMins}m ${diffSecs}s`;
    return `${diffSecs}s`;
  };

  const formatDurationSec = (seconds: number | null | undefined): string => {
    if (!seconds) return '';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const OUTCOME_BADGE: Record<string, { color: 'success' | 'primary' | 'warning' | 'error' | 'default'; icon: string }> = {
    handled: { color: 'success', icon: '\u2705' },
    transferred: { color: 'primary', icon: '\uD83D\uDD04' },
    voicemail: { color: 'warning', icon: '\uD83D\uDCE9' },
    missed: { color: 'error', icon: '\u274C' },
    error: { color: 'error', icon: '\u26A0\uFE0F' },
  };
  
  // Format date time for call detail panel
  const formatCallDateTime = (dateString: string) => {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-GB', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };
  
  // Handle call click to open detail panel
  const handleCallClick = (call: Call) => {
    setSelectedCall(call);
    setCallPanelOpen(true);
  };

  const newCallCount = calls.filter(c => !c.archived).length;
  const [unreadEmailCount, setUnreadEmailCount] = useState(0);

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  // Fetch unread email count for tab badge
  useEffect(() => {
    if (!business) return;
    fetchEmailMessages({ limit: 50 })
      .then(data => {
        const unread = (data.messages || []).filter(m => m.is_unread).length;
        setUnreadEmailCount(unread);
      })
      .catch(() => setUnreadEmailCount(0));
  }, [business]);

  if (authLoading || loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'var(--color-neutral-25)' }}>
      <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
        <Toolbar
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            minHeight: '56px !important',
            height: 56,
            px: { xs: 2, sm: 3 },
          }}
        >
          {/* Logo */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              flexShrink: 0,
              cursor: 'pointer',
            }}
            onClick={() => setTabValue(0)}
          >
            {logoUrl ? (
              <img
                src={logoUrl}
                alt={businessProfile?.name || 'Business Logo'}
                style={{ width: 32, height: 32, objectFit: 'contain', borderRadius: 6 }}
              />
            ) : (
              <Box
                sx={{
                  width: 32,
                  height: 32,
                  borderRadius: '8px',
                  bgcolor: 'rgba(255,255,255,0.15)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  color: 'white',
                }}
              >
                {getBusinessInitials(businessProfile?.name || business?.name || 'BH')}
              </Box>
            )}
            <Typography
              sx={{
                fontWeight: 700,
                fontSize: '0.875rem',
                color: 'white',
                display: { xs: 'none', sm: 'block' },
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                maxWidth: 200,
              }}
            >
              {businessProfile?.name || business?.name || 'Business Hero'}
            </Typography>
          </Box>

          <Box sx={{ flex: 1 }} />

          {/* Nav items */}
          <Box sx={{ display: { xs: 'none', sm: 'flex' }, alignItems: 'center', gap: 0.5 }}>
            <Button
              size="small"
              startIcon={<AccountBalanceIcon sx={{ fontSize: '16px !important' }} />}
              onClick={() => navigate('/app/accounting')}
              sx={{
                color: 'rgba(255,255,255,0.8)',
                fontSize: '0.8125rem',
                fontWeight: 500,
                px: 1.5,
                borderRadius: '8px',
                textTransform: 'none',
                '&:hover': { bgcolor: 'rgba(255,255,255,0.1)', color: 'white' },
              }}
            >
              Accounting
            </Button>
            <Button
              size="small"
              onClick={() => navigate('/app/assistant/chat')}
              sx={{
                color: 'rgba(255,255,255,0.8)',
                fontSize: '0.8125rem',
                fontWeight: 500,
                px: 1.5,
                borderRadius: '8px',
                textTransform: 'none',
                gap: 1,
                '&:hover': { bgcolor: 'rgba(255,255,255,0.1)', color: 'white' },
              }}
            >
              <Box
                sx={{
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  overflow: 'hidden',
                  border: '2px solid rgba(167,139,250,0.6)',
                  flexShrink: 0,
                  animation: 'ariaRing 3s ease-in-out infinite',
                  '@keyframes ariaRing': {
                    '0%, 100%': { borderColor: 'rgba(167,139,250,0.4)' },
                    '50%': { borderColor: 'rgba(167,139,250,0.8)' },
                  },
                }}
              >
                <img
                  src="/aria-avatar.png"
                  alt="Aria"
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
              </Box>
              Aria
            </Button>
          </Box>

          {/* User area */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, ml: 1 }}>
            <Typography
              variant="body2"
              sx={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                maxWidth: { xs: 0, sm: 100, md: 180 },
                color: 'rgba(255,255,255,0.7)',
                fontSize: '0.75rem',
                display: { xs: 'none', sm: 'block' },
              }}
            >
              {user?.email}
            </Typography>
            <IconButton
              size="small"
              onClick={handleSignOut}
              data-testid="button-signout"
              sx={{
                color: 'rgba(255,255,255,0.7)',
                '&:hover': { bgcolor: 'rgba(255,255,255,0.1)', color: 'white' },
              }}
            >
              <LogoutIcon sx={{ fontSize: 20 }} />
            </IconButton>
          </Box>
        </Toolbar>
      </AppBar>
      {/* Toolbar spacer for fixed AppBar */}
      <Box sx={{ height: 56 }} />

      <Container maxWidth="xl" sx={{ py: { xs: 2, sm: 3, md: 4 }, pb: { xs: 12, md: 4 } }}>
        {error && (
          <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')} data-testid="alert-error">
            {error}
          </Alert>
        )}

        {!business ? (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <Typography variant="h6" color="text.secondary">
              No business assigned
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Please contact an administrator to be assigned to a business.
            </Typography>
          </Paper>
        ) : (
          <>
            {/* Compact Business Header */}
            <Card
              sx={{
                mb: 3,
                px: { xs: 2, sm: 2.5 },
                py: 1.5,
                border: '1px solid var(--color-neutral-100)',
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1.5 }}>
                {/* Left: Logo and business info */}
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  {logoUrl ? (
                    <Avatar 
                      src={logoUrl} 
                      alt={businessProfile?.name || business?.name || 'Business'}
                      sx={{
                        width: 44,
                        height: 44,
                        borderRadius: '10px',
                        boxShadow: 'var(--shadow-xs)',
                      }}
                      variant="rounded"
                    />
                  ) : (
                    <Avatar
                      sx={{
                        width: 44,
                        height: 44,
                        borderRadius: '10px',
                        bgcolor: 'primary.main',
                        boxShadow: 'var(--shadow-xs)',
                        fontSize: '0.875rem',
                        fontWeight: 700,
                      }}
                      variant="rounded"
                    >
                      {getBusinessInitials(businessProfile?.name || business?.name || 'B')}
                    </Avatar>
                  )}
                  <Box>
                    <Typography
                      sx={{
                        fontSize: '1.0625rem',
                        fontWeight: 700,
                        color: 'var(--color-neutral-900)',
                        lineHeight: 1.3,
                      }}
                      data-testid="text-business-name"
                    >
                      {businessProfile?.name || business.name}
                    </Typography>
                    <Typography
                      sx={{
                        fontSize: '0.75rem',
                        color: 'var(--color-neutral-500)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 0.5,
                      }}
                    >
                      <AccessTimeIcon sx={{ fontSize: 13 }} />
                      {business.timezone || 'Europe/London'}
                      <span style={{ margin: '0 4px' }}>&middot;</span>
                      {membership?.role || 'Owner'}
                    </Typography>
                  </Box>
                </Box>
                
                {/* Right: Settings dropdown */}
                <Box>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={(e) => setSettingsAnchor(e.currentTarget)}
                    endIcon={<SettingsIcon sx={{ fontSize: '16px !important' }} />}
                    sx={{
                      borderColor: 'var(--color-neutral-200)',
                      color: 'var(--color-neutral-600)',
                      fontWeight: 500,
                      fontSize: '0.8125rem',
                      '&:hover': {
                        borderColor: 'var(--color-neutral-300)',
                        bgcolor: 'var(--color-neutral-50)',
                      },
                    }}
                  >
                    Settings
                  </Button>
                  <Menu
                    anchorEl={settingsAnchor}
                    open={Boolean(settingsAnchor)}
                    onClose={() => setSettingsAnchor(null)}
                    PaperProps={{ sx: { minWidth: 200 } }}
                  >
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/settings/email'); }}>
                      <ListItemIcon><EmailIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Email Settings</ListItemText>
                    </MenuItem>
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/settings/billing'); }}>
                      <ListItemIcon><PaymentIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Billing</ListItemText>
                    </MenuItem>
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/settings/awaz'); }}>
                      <ListItemIcon><PhoneIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Awaz Settings</ListItemText>
                    </MenuItem>
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/settings/branding'); }}>
                      <ListItemIcon><PaletteIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Branding</ListItemText>
                    </MenuItem>
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/accounting'); }}>
                      <ListItemIcon><AccountBalanceIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Accounting</ListItemText>
                    </MenuItem>
                    <MenuItem onClick={() => { setSettingsAnchor(null); setTabValue(4); }}>
                      <ListItemIcon><SmartToyIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>AI Receptionist</ListItemText>
                    </MenuItem>
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/email/outbox'); }}>
                      <ListItemIcon><OutboxIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Email Outbox</ListItemText>
                    </MenuItem>
                    <Divider />
                    <MenuItem onClick={() => { setSettingsAnchor(null); setSupportPanelOpen(true); }}>
                      <ListItemIcon><HelpIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Help & Support</ListItemText>
                    </MenuItem>
                  </Menu>
                </Box>
              </Box>
            </Card>

            <Paper sx={{ p: { xs: 2, sm: 3 }, border: '1px solid var(--color-neutral-100)', boxShadow: 'var(--shadow-sm)' }} elevation={0}>
              <Box
                sx={{
                  borderBottom: 1,
                  borderColor: 'divider',
                  mb: 0,
                  position: 'sticky',
                  top: 56,
                  zIndex: 10,
                  bgcolor: 'white',
                  mx: { xs: -2, sm: -3 },
                  px: { xs: 2, sm: 3 },
                }}
              >
                <Tabs
                  value={tabValue}
                  onChange={(_, v) => setTabValue(v)}
                  variant="scrollable"
                  scrollButtons="auto"
                  allowScrollButtonsMobile
                  sx={{
                    '& .MuiTab-root': {
                      minHeight: 48,
                      textTransform: 'none',
                      fontWeight: 500,
                      fontSize: { xs: '0.75rem', sm: '0.8125rem' },
                      px: { xs: 1.5, sm: 2 },
                    },
                    '& .MuiTabs-scrollButtons': {
                      '&.Mui-disabled': { opacity: 0.3 },
                    },
                  }}
                >
                  <Tab
                    icon={<TaskIcon />}
                    iconPosition="start"
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        Tasks
                        <Chip 
                          label={openTaskCount} 
                          size="small" 
                          color={openTaskCount > 0 ? 'primary' : 'default'}
                          sx={{ minWidth: 24, height: 22 }}
                        />
                      </Box>
                    }
                    data-testid="tab-tasks"
                  />
                  <Tab
                    icon={<PhoneIcon />}
                    iconPosition="start"
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        Calls
                        <Chip 
                          label={newCallCount} 
                          size="small" 
                          color={newCallCount > 0 ? 'primary' : 'default'}
                          sx={{ minWidth: 24, height: 22 }}
                        />
                      </Box>
                    }
                    data-testid="tab-calls"
                  />
                  <Tab
                    icon={<ReceiptIcon />}
                    iconPosition="start"
                    label="Invoices"
                    data-testid="tab-invoices"
                  />
                  <Tab
                    icon={<MailOutlineIcon />}
                    iconPosition="start"
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        Emails
                        <Chip 
                          label={unreadEmailCount} 
                          size="small" 
                          color={unreadEmailCount > 0 ? 'primary' : 'default'}
                          sx={{ minWidth: 24, height: 22 }}
                        />
                      </Box>
                    }
                    data-testid="tab-emails"
                  />
                  <Tab
                    icon={<SmartToyIcon />}
                    iconPosition="start"
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        Receptionist
                      </Box>
                    }
                    data-testid="tab-receptionist"
                  />
                  <Tab
                    icon={<SmsIcon />}
                    iconPosition="start"
                    label="CEO Briefing"
                    data-testid="tab-ceo-briefing"
                  />
                </Tabs>
              </Box>

              <TabPanel value={tabValue} index={0}>
                <TasksPanel ref={tasksPanelRef} businessId={business.id} onTaskCountChange={setOpenTaskCount} />
              </TabPanel>

              <TabPanel value={tabValue} index={1}>
                {/* Stats Cards */}
                <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                  <Card sx={{ flex: '1 1 140px', p: 2 }}>
                    <Typography variant="caption" color="text.secondary">Today's Calls</Typography>
                    <Typography variant="h4" color="primary.main">{callStats.today}</Typography>
                  </Card>
                  <Card sx={{ flex: '1 1 140px', p: 2 }}>
                    <Typography variant="caption" color="text.secondary">Total Active</Typography>
                    <Typography variant="h4">{callStats.total}</Typography>
                  </Card>
                  <Card sx={{ flex: '1 1 140px', p: 2 }}>
                    <Typography variant="caption" color="text.secondary">Source</Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 0.5 }}>
                      <Tooltip title="AI Receptionist">
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <SmartToyIcon fontSize="small" color="primary" />
                          <Typography variant="h6" fontWeight={600}>{callStats.receptionist}</Typography>
                        </Box>
                      </Tooltip>
                      <Tooltip title="Awaz">
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <PhoneIcon fontSize="small" color="action" />
                          <Typography variant="h6" fontWeight={600}>{callStats.awaz}</Typography>
                        </Box>
                      </Tooltip>
                    </Box>
                  </Card>
                </Box>

                {/* Search and Filter Toolbar */}
                <Box sx={{ mb: 3 }}>
                  {/* Search Bar */}
                  <TextField
                    placeholder="Search by caller name, number, or summary..."
                    value={callSearch}
                    onChange={(e) => setCallSearch(e.target.value)}
                    size="small"
                    fullWidth
                    sx={{ mb: 2 }}
                    InputProps={{
                      startAdornment: (
                        <InputAdornment position="start">
                          <SearchIcon color="action" />
                        </InputAdornment>
                      ),
                      endAdornment: callSearch && (
                        <InputAdornment position="end">
                          <IconButton size="small" onClick={() => setCallSearch('')}>
                            <ClearIcon fontSize="small" />
                          </IconButton>
                        </InputAdornment>
                      ),
                    }}
                  />

                  {/* Filters Row */}
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
                    {/* Date Filter Chips */}
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      {[
                        { value: 'today', label: 'Today' },
                        { value: 'week', label: 'This Week' },
                        { value: 'month', label: 'This Month' },
                        { value: 'all', label: 'All Time' },
                      ].map((filter) => (
                        <Chip
                          key={filter.value}
                          label={filter.label}
                          onClick={() => setCallDateFilter(filter.value as 'all' | 'today' | 'week' | 'month')}
                          color={callDateFilter === filter.value ? 'primary' : 'default'}
                          variant={callDateFilter === filter.value ? 'filled' : 'outlined'}
                          size="small"
                        />
                      ))}
                    </Box>

                    {/* Source Filter Chips */}
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      {([
                        { value: 'all', label: 'All Calls' },
                        { value: 'receptionist', label: 'AI Receptionist' },
                        { value: 'Awaz', label: 'Awaz' },
                      ] as const).map((f) => (
                        <Chip
                          key={f.value}
                          label={f.label}
                          icon={f.value === 'receptionist' ? <SmartToyIcon /> : undefined}
                          onClick={() => setCallSourceFilter(f.value)}
                          color={callSourceFilter === f.value ? 'secondary' : 'default'}
                          variant={callSourceFilter === f.value ? 'filled' : 'outlined'}
                          size="small"
                        />
                      ))}
                    </Box>

                    {/* Show Archived Toggle */}
                    <FormControlLabel
                      control={
                        <Switch
                          size="small"
                          checked={showArchivedCalls}
                          onChange={(e) => setShowArchivedCalls(e.target.checked)}
                        />
                      }
                      label="Show archived"
                      sx={{ ml: 'auto' }}
                    />
                  </Box>
                </Box>

                {/* Calls List */}
                {filteredCalls.length === 0 ? (
                  <Card sx={{ p: 4, textAlign: 'center' }}>
                    <PhoneIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
                    <Typography color="text.secondary">
                      {callSearch || callDateFilter !== 'all' ? 'No calls match your filters' : 'No calls yet'}
                    </Typography>
                  </Card>
                ) : (
                  <Box>
                    {Object.entries(groupedCalls).map(([date, dateCalls]) => (
                      <Box key={date} sx={{ mb: 3 }}>
                        {/* Date Header */}
                        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, ml: 1 }}>
                          {date} ({dateCalls.length} {dateCalls.length === 1 ? 'call' : 'calls'})
                        </Typography>
                        
                        {/* Calls for this date */}
                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                          {dateCalls.map((call) => (
                            <Card
                              key={call.id}
                              data-testid={`card-call-${call.id}`}
                              sx={{
                                p: 2,
                                cursor: 'pointer',
                                opacity: call.archived ? 0.6 : 1,
                                '&:hover': { boxShadow: 2, bgcolor: 'action.hover' },
                                transition: 'all 0.2s',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 2,
                              }}
                              onClick={() => handleCallClick(call)}
                            >
                              {/* Icon — different for AI Receptionist vs Awaz */}
                              <Box sx={{
                                width: 40,
                                height: 40,
                                borderRadius: '50%',
                                bgcolor: call.source === 'receptionist' ? 'secondary.light' : 'primary.light',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexShrink: 0,
                              }}>
                                {call.source === 'receptionist'
                                  ? <SmartToyIcon color="secondary" fontSize="small" />
                                  : <PhoneIcon color="primary" fontSize="small" />}
                              </Box>

                              {/* Main Content */}
                              <Box sx={{ flex: 1, minWidth: 0 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                  <Typography variant="subtitle1" fontWeight={600} noWrap>
                                    {call.caller_name || 'Unknown Caller'}
                                  </Typography>
                                  {call.source === 'receptionist' && (
                                    <Chip label="AI" size="small" color="secondary" sx={{ height: 20, fontSize: '0.7rem' }} />
                                  )}
                                  {call.archived && (
                                    <Chip label="Archived" size="small" />
                                  )}
                                </Box>
                                <Typography variant="body2" color="text.secondary" noWrap>
                                  {call.caller_number || call.phone_number || 'No number'}
                                  {(call.summary || call.notes) && ` \u00B7 ${(call.summary || call.notes || '').substring(0, 50)}...`}
                                </Typography>
                              </Box>

                              {/* Right side */}
                              <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                                <Typography variant="caption" color="text.secondary">
                                  {new Date(call.created_at).toLocaleTimeString('en-GB', {
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  })}
                                  {call.duration_seconds ? ` \u00B7 ${formatDurationSec(call.duration_seconds)}` : ''}
                                </Typography>
                                <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end', mt: 0.5 }}>
                                  {call.source === 'receptionist' && call.outcome && OUTCOME_BADGE[call.outcome] && (
                                    <Chip
                                      label={`${OUTCOME_BADGE[call.outcome].icon} ${call.outcome}`}
                                      size="small"
                                      color={OUTCOME_BADGE[call.outcome].color}
                                      variant="outlined"
                                      sx={{ height: 22, fontSize: '0.7rem' }}
                                    />
                                  )}
                                  {call.intent && call.source !== 'receptionist' && (
                                    <Chip label={call.intent} size="small" variant="outlined" sx={{ height: 22, fontSize: '0.7rem' }} />
                                  )}
                                </Box>
                              </Box>

                              <ChevronRightIcon color="action" />
                            </Card>
                          ))}
                        </Box>
                      </Box>
                    ))}
                  </Box>
                )}

                {/* Call Detail Panel */}
                <Drawer anchor="right" open={callPanelOpen} onClose={() => { setCallPanelOpen(false); setSelectedCall(null); }}>
                  <Box sx={{ width: 450, p: 3 }}>
                    {selectedCall && (
                      <>
                        {/* Header */}
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            {selectedCall.source === 'receptionist'
                              ? <SmartToyIcon color="secondary" />
                              : <PhoneIcon color="primary" />}
                            <Typography variant="h6" fontWeight={600}>
                              Call Details
                            </Typography>
                            {selectedCall.source === 'receptionist' && (
                              <Chip label="AI Receptionist" size="small" color="secondary" />
                            )}
                          </Box>
                          <IconButton onClick={() => { setCallPanelOpen(false); setSelectedCall(null); }}>
                            <CloseIcon />
                          </IconButton>
                        </Box>

                        {/* Caller Info */}
                        <Card sx={{ p: 2, mb: 3, bgcolor: 'primary.light' }}>
                          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                            Caller
                          </Typography>
                          <Typography variant="h5" fontWeight={600}>
                            {selectedCall.caller_name || 'Unknown Caller'}
                          </Typography>
                          {(selectedCall.caller_number || selectedCall.phone_number) && (
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
                              <PhoneIcon fontSize="small" color="action" />
                              <Typography variant="body1">{selectedCall.caller_number || selectedCall.phone_number}</Typography>
                            </Box>
                          )}
                        </Card>

                        {/* Date/Time */}
                        <Box sx={{ mb: 3 }}>
                          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                            Date & Time
                          </Typography>
                          <Typography variant="body1">
                            {formatCallDateTime(selectedCall.created_at)}
                          </Typography>
                          {selectedCall.duration_seconds ? (
                            <Typography variant="caption" color="text.secondary">
                              Duration: {formatDurationSec(selectedCall.duration_seconds)}
                            </Typography>
                          ) : selectedCall.started_at && selectedCall.ended_at ? (
                            <Typography variant="caption" color="text.secondary">
                              Duration: {calculateDuration(selectedCall.started_at, selectedCall.ended_at)}
                            </Typography>
                          ) : null}
                        </Box>

                        {/* Outcome (receptionist) */}
                        {selectedCall.source === 'receptionist' && selectedCall.outcome && (
                          <Box sx={{ mb: 3 }}>
                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                              Outcome
                            </Typography>
                            <Chip
                              label={`${OUTCOME_BADGE[selectedCall.outcome]?.icon || ''} ${selectedCall.outcome}`}
                              color={OUTCOME_BADGE[selectedCall.outcome]?.color || 'default'}
                              variant="outlined"
                            />
                          </Box>
                        )}

                        {/* Intent Badge */}
                        {selectedCall.intent && (
                          <Box sx={{ mb: 3 }}>
                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                              Intent
                            </Typography>
                            <Chip
                              label={selectedCall.intent}
                              color="primary"
                              variant="outlined"
                            />
                          </Box>
                        )}

                        {/* Summary */}
                        {(selectedCall.summary || selectedCall.notes) && (
                          <Box sx={{ mb: 3 }}>
                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                              Summary
                            </Typography>
                            <Card sx={{ p: 2, bgcolor: 'grey.50' }}>
                              <Typography variant="body2">
                                {selectedCall.summary || selectedCall.notes}
                              </Typography>
                            </Card>
                          </Box>
                        )}

                        {/* Transcript */}
                        {selectedCall.transcript && (
                          <Box sx={{ mb: 3 }}>
                            <Typography sx={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-neutral-500)', textTransform: 'uppercase', letterSpacing: '0.05em', mb: 1.5 }}>
                              Transcript
                            </Typography>
                            <Box sx={{ maxHeight: 400, overflow: 'auto', px: 0.5 }}>
                              {selectedCall.source === 'receptionist' ? (
                                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                                  {selectedCall.transcript.split('\n').filter(Boolean).map((line: string, idx: number) => {
                                    const isCaller = line.startsWith('Caller:');
                                    const text = line.replace(/^(Caller|Receptionist):\s*/, '');
                                    return (
                                      <Box key={idx} sx={{ display: 'flex', justifyContent: isCaller ? 'flex-start' : 'flex-end' }}>
                                        <Box
                                          className={`transcript-bubble ${isCaller ? 'transcript-bubble--caller' : 'transcript-bubble--receptionist'}`}
                                          sx={{ maxWidth: '85%', px: 2, py: 1 }}
                                        >
                                          <Typography sx={{ fontSize: '0.625rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', mb: '2px', color: isCaller ? 'var(--color-neutral-500)' : 'var(--color-primary-600)' }}>
                                            {isCaller ? 'Caller' : 'Receptionist'}
                                          </Typography>
                                          <Typography sx={{ fontSize: '0.8125rem', lineHeight: 1.625 }}>{text}</Typography>
                                        </Box>
                                      </Box>
                                    );
                                  })}
                                </Box>
                              ) : (
                                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', color: 'var(--color-neutral-700)' }}>
                                  {selectedCall.transcript}
                                </Typography>
                              )}
                            </Box>
                          </Box>
                        )}

                        {/* No details message */}
                        {!selectedCall.summary && !selectedCall.notes && !selectedCall.transcript && !selectedCall.intent && (
                          <Card sx={{ p: 3, textAlign: 'center', bgcolor: 'grey.50', mb: 3 }}>
                            <Typography color="text.secondary">
                              No additional details available for this call.
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              Call details will appear here when captured by the AI receptionist.
                            </Typography>
                          </Card>
                        )}

                        <Divider sx={{ my: 3 }} />

                        {/* Actions */}
                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                          {/* Create Task from Call */}
                          <Button
                            variant="outlined"
                            startIcon={<TaskIcon />}
                            fullWidth
                            onClick={() => {
                              tasksPanelRef.current?.openCreateDialog();
                              setCallPanelOpen(false);
                            }}
                          >
                            Create Task from Call
                          </Button>

                          {/* Archive */}
                          <Button
                            variant="outlined"
                            color={selectedCall.archived ? 'primary' : 'inherit'}
                            startIcon={<ArchiveIcon />}
                            onClick={() => {
                              handleArchiveCall(selectedCall.id);
                              setCallPanelOpen(false);
                              setSelectedCall(null);
                            }}
                            fullWidth
                          >
                            {selectedCall.archived ? 'Unarchive' : 'Archive Call'}
                          </Button>
                        </Box>
                      </>
                    )}
                  </Box>
                </Drawer>
              </TabPanel>

              <TabPanel value={tabValue} index={2}>
                {mountedTabs.has(2) && business && <InvoicesPanel businessId={business.id} />}
              </TabPanel>

              <TabPanel value={tabValue} index={3}>
                {mountedTabs.has(3) && business && <EmailsTab businessId={business.id} />}
              </TabPanel>

              <TabPanel value={tabValue} index={4}>
                {mountedTabs.has(4) && business && <ReceptionistTab businessId={business.id} onViewCalls={() => { setCallSourceFilter('receptionist'); setTabValue(1); }} />}
              </TabPanel>
              <TabPanel value={tabValue} index={5}>
                {mountedTabs.has(5) && business && <CeoBriefingTab />}
              </TabPanel>
            </Paper>
          </>
        )}
      </Container>

      {/* Success Snackbar */}
      <Snackbar
        open={!!successMessage}
        autoHideDuration={6000}
        onClose={() => setSuccessMessage("")}
        message={successMessage}
      />

      {import.meta.env.DEV && <DebugPanel />}

      {/* Floating Aria Button */}
      <Tooltip title="Talk to Aria" placement="left" TransitionComponent={Zoom}>
        <Fab
          color="primary"
          aria-label="Talk to Aria"
          onClick={() => navigate('/app/assistant/chat')}
          sx={{
            position: 'fixed',
            bottom: { xs: `calc(72px + env(safe-area-inset-bottom, 0px))`, md: 24 },
            right: 24,
            width: { xs: 48, md: 56 },
            height: { xs: 48, md: 56 },
            boxShadow: '0 4px 20px rgba(139, 92, 246, 0.3)',
            background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
            border: '3px solid var(--color-aria-400)',
            overflow: 'hidden',
            transition: 'all 200ms cubic-bezier(0.4,0,0.2,1)',
            animation: 'ariaPulse 3s ease-in-out infinite',
            zIndex: 60,
            '&:hover': {
              transform: 'scale(1.08)',
              boxShadow: '0 6px 28px rgba(139, 92, 246, 0.4)',
              borderColor: 'var(--color-aria-500)',
            },
            '@keyframes ariaPulse': {
              '0%, 100%': { boxShadow: '0 4px 20px rgba(139, 92, 246, 0.3)' },
              '50%': { boxShadow: '0 4px 30px rgba(139, 92, 246, 0.5)' },
            },
          }}
        >
          <img
            src="/aria-avatar.png"
            alt="Aria"
            style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }}
          />
        </Fab>
      </Tooltip>

      {/* Floating Support Help Button */}
      <SupportHelpButton onClick={() => setSupportPanelOpen(true)} />

      {/* Support Panel */}
      <SupportPanel open={supportPanelOpen} onClose={() => setSupportPanelOpen(false)} />

      {/* Mobile Bottom Navigation */}
      <BottomNav
        activeTab={tabValue}
        onTabChange={setTabValue}
        counts={{
          tasks: openTaskCount,
          calls: newCallCount,
        }}
      />
    </Box>
  );
}
