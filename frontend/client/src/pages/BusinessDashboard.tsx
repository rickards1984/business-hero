import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  Button,
  Container,
  Paper,
  Grid,
  Card,
  CardContent,
  CardActions,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  TextField,
  CircularProgress,
  Alert,
  IconButton,
  Tabs,
  Tab,
  Divider,
  Avatar,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Drawer,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Snackbar,
  Checkbox,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
  Menu,
  Tooltip,
  InputAdornment,
} from '@mui/material';
import {
  Business as BusinessIcon,
  Task as TaskIcon,
  Phone as PhoneIcon,
  Add as AddIcon,
  CheckCircle as CheckCircleIcon,
  Logout as LogoutIcon,
  AccessTime as AccessTimeIcon,
  Receipt as ReceiptIcon,
  Archive as ArchiveIcon,
  Warning as WarningIcon,
  Gavel as GavelIcon,
  CloudUpload as CloudUploadIcon,
  Email as EmailIcon,
  CheckCircleOutline as CheckCircleOutlineIcon,
  Close as CloseIcon,
  Settings as SettingsIcon,
  Outbox as OutboxIcon,
  Send as SendIcon,
  Preview as PreviewIcon,
  Link as LinkIcon,
  SmartToy as SmartToyIcon,
  Payment as PaymentIcon,
  Palette as PaletteIcon,
  Help as HelpIcon,
  Edit as EditIcon,
  Undo as UndoIcon,
  Cancel as CancelIcon,
  Delete as DeleteIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, type Business, type Task, type Call, type BusinessMember, resolveLogoSrc } from '@/lib/supabase';
import { useMe } from '@/hooks/useMe';
import { apiRequest } from '@/lib/queryClient';
import { config } from '@/config/env';
import DebugPanel from '@/components/DebugPanel';

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
  return (
    <div role="tabpanel" hidden={value !== index} {...other}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  );
}

// Chase stage definitions
interface ChaseStage {
  stage: number;
  label: string;
  description: string;
  color: 'default' | 'primary' | 'warning' | 'error';
}

const CHASE_STAGES: ChaseStage[] = [
  { stage: 1, label: 'Stage 1', description: 'Friendly Reminder', color: 'primary' },
  { stage: 2, label: 'Stage 2', description: 'Second Notice', color: 'primary' },
  { stage: 3, label: 'Stage 3', description: 'Final Warning', color: 'warning' },
  { stage: 4, label: 'Stage 4', description: 'Legal Action Notice', color: 'error' },
];

// Helper component to display chase stage as a chip
const ChaseStageChip: React.FC<{ stage: number }> = ({ stage }) => {
  if (!stage || stage === 0) {
    return <Chip label="Not chased" size="small" variant="outlined" />;
  }
  
  const stageInfo = CHASE_STAGES.find(s => s.stage === stage);
  if (!stageInfo) {
    return <Chip label={`Stage ${stage}`} size="small" />;
  }
  
  return (
    <Chip 
      label={`${stageInfo.label}: ${stageInfo.description}`}
      size="small"
      color={stageInfo.color}
      icon={stage >= 4 ? <GavelIcon /> : stage >= 3 ? <WarningIcon /> : undefined}
    />
  );
};

export default function BusinessDashboard() {
  const navigate = useNavigate();
  const { user, signOut, loading: authLoading } = useAuth();
  const { data: businessProfile, isLoading: profileLoading } = useMe();
  
  const [tabValue, setTabValue] = useState(0);
  const [membership, setMembership] = useState<BusinessMember | null>(null);
  const [business, setBusiness] = useState<Business | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [calls, setCalls] = useState<Call[]>([]);
  const [callFilter, setCallFilter] = useState<'all' | 'new' | 'archived'>('new');
  const [taskFilter, setTaskFilter] = useState<'open' | 'completed' | 'all'>('open');
  const [settingsAnchor, setSettingsAnchor] = useState<null | HTMLElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  const logoUrl = resolveLogoSrc(businessProfile?.logo_url);

  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [savingTask, setSavingTask] = useState(false);

  // Invoice state
  interface Invoice {
    id: string;
    invoice_number: string;
    customer_name: string;
    customer_email: string | null;
    issue_date: string | null;
    due_date: string;
    amount: number;
    currency: string;
    status: string;
    paid_date: string | null;
    paid_amount: number | null;
    paid_at: string | null;
    archived: boolean;
    last_chased_at: string | null;
    chase_stage: number;
    source: string;
    source_ref: string | null;
  }
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [invoicesLoading, setInvoicesLoading] = useState(false);
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null);
  const [invoiceDrawerOpen, setInvoiceDrawerOpen] = useState(false);
  const [chaseDraft, setChaseDraft] = useState<{ subject: string; body: string; chase_stage: number } | null>(null);
  const [csvUploading, setCsvUploading] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');
  const [selectedInvoiceIds, setSelectedInvoiceIds] = useState<string[]>([]);
  const [invoiceStage, setInvoiceStage] = useState(1);
  const [dryRunSend, setDryRunSend] = useState(false);
  const [bulkChaseStage, setBulkChaseStage] = useState(1);
  const [bulkPreviewOpen, setBulkPreviewOpen] = useState(false);
  const [bulkPreview, setBulkPreview] = useState<{ invoice_id: string; subject: string; body: string; status: string; stage_description?: string; error_message?: string }[]>([]);
  
  // Invoice filtering state
  const [invoiceSearch, setInvoiceSearch] = useState('');
  const [invoiceStatusFilter, setInvoiceStatusFilter] = useState('');
  const [showArchivedInvoices, setShowArchivedInvoices] = useState(false);
  const [invoiceSortBy, setInvoiceSortBy] = useState('due_date');
  const [invoiceSortOrder, setInvoiceSortOrder] = useState<'asc' | 'desc'>('asc');
  const [invoiceActionLoading, setInvoiceActionLoading] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{ open: boolean; action: 'delete' | 'cancel' | null; invoiceId: string | null }>({ open: false, action: null, invoiceId: null });

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

  const fetchUserBusiness = async () => {
    setLoading(true);
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
        .select('*')
        .eq('id', memberData.business_id)
        .single();
      if (businessError) throw businessError;
      setBusiness(businessData);

      await Promise.all([
        fetchTasks(memberData.business_id),
        fetchCalls(memberData.business_id),
      ]);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch business data');
    } finally {
      setLoading(false);
    }
  };

  const fetchTasks = async (businessId: string) => {
    const { data, error } = await supabase
      .from('tasks')
      .select('*')
      .eq('business_id', businessId)
      .order('created_at', { ascending: false });

    if (error) throw error;
    setTasks(data || []);
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

  const handleCreateTask = async () => {
    if (!taskTitle.trim() || !business) return;

    setSavingTask(true);
    setError('');

    try {
      const { error: insertError } = await supabase
        .from('tasks')
        .insert({
          business_id: business.id,
          title: taskTitle.trim(),
          description: taskDescription.trim(),
          status: 'pending',
        });

      if (insertError) throw insertError;

      setTaskDialogOpen(false);
      setTaskTitle('');
      setTaskDescription('');
      await fetchTasks(business.id);
    } catch (err: any) {
      setError(err.message || 'Failed to create task');
    } finally {
      setSavingTask(false);
    }
  };

  const handleCompleteTask = async (taskId: string) => {
    if (!business) return;

    try {
      const { error: updateError } = await supabase
        .from('tasks')
        .update({ status: 'completed' })
        .eq('id', taskId);

      if (updateError) throw updateError;
      await fetchTasks(business.id);
    } catch (err: any) {
      setError(err.message || 'Failed to complete task');
    }
  };

  // Helper function to format relative time
  const formatRelativeTime = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
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

  // Filter calls based on callFilter
  const filteredCalls = calls.filter(call => {
    if (callFilter === 'archived') return call.archived;
    if (callFilter === 'new') return !call.archived;
    return true; // 'all'
  });

  // Filter tasks based on taskFilter
  const filteredTasks = tasks.filter(task => {
    if (taskFilter === 'open') return task.status !== 'completed';
    if (taskFilter === 'completed') return task.status === 'completed';
    return true; // 'all'
  });

  // Task counts for badges
  const openTaskCount = tasks.filter(t => t.status !== 'completed').length;
  const overdueInvoiceCount = invoices.filter(inv => new Date(inv.due_date) < new Date() && inv.status !== 'paid').length;
  const newCallCount = calls.filter(c => !c.archived).length;

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  // Invoice functions
  const fetchInvoices = async () => {
    if (!business) return;
    setInvoicesLoading(true);
    try {
      const params = new URLSearchParams();
      if (invoiceSearch) params.append('search', invoiceSearch);
      if (invoiceStatusFilter) params.append('status', invoiceStatusFilter);
      params.append('archived', showArchivedInvoices.toString());
      params.append('sort_by', invoiceSortBy);
      params.append('sort_order', invoiceSortOrder);
      
      const response = await apiRequest('GET', `/v1/invoices?${params.toString()}`);
      const data = await response.json();
      setInvoices(data.invoices || []);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch invoices');
    } finally {
      setInvoicesLoading(false);
    }
  };

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !business) return;

    setCsvUploading(true);
    setError('');
    setSuccessMessage('');

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${config.apiBaseUrl}/v1/invoices/import/csv`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${(await supabase.auth.getSession()).data.session?.access_token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to import CSV');
      }

      const result = await response.json();
      setSuccessMessage(`Successfully imported ${result.imported} invoices, updated ${result.updated} invoices`);
      
      // Refetch invoices
      await fetchInvoices();
      
      // Clear file input
      e.target.value = '';
    } catch (err: any) {
      setError(err.message || 'Failed to upload CSV');
    } finally {
      setCsvUploading(false);
    }
  };

  const handleInvoiceClick = (invoice: Invoice) => {
    setSelectedInvoice(invoice);
    setInvoiceDrawerOpen(true);
    setChaseDraft(null);
    setInvoiceStage(Math.min((invoice.chase_stage || 0) + 1, 4));
  };

  const handleGetChaseDraft = async () => {
    if (!selectedInvoice) return;
    try {
      const response = await apiRequest('POST', `/v1/invoices/${selectedInvoice.id}/chase-draft?stage=${invoiceStage}`);
      const data = await response.json();
      setChaseDraft(data);
    } catch (err: any) {
      setError(err.message || 'Failed to get chase draft');
    }
  };

  const handleSendChaseEmail = async () => {
    if (!selectedInvoice) return;
    try {
      const response = await apiRequest('POST', `/v1/invoices/${selectedInvoice.id}/send-chase`, {
        chase_stage: invoiceStage,  // Now uses 1-4 directly
        dry_run: dryRunSend,
      });
      const data = await response.json();
      if (dryRunSend) {
        setChaseDraft({ subject: data.subject, body: data.body, chase_stage: data.chase_stage });
        setSuccessMessage('Preview generated (dry run)');
        return;
      }
      await fetchInvoices();
      const stageInfo = CHASE_STAGES.find(s => s.stage === invoiceStage);
      setSuccessMessage(`${stageInfo?.description || 'Chase email'} sent successfully`);
    } catch (err: any) {
      setError(err.message || 'Failed to send chase email');
    }
  };

  const handleMarkChased = async () => {
    if (!selectedInvoice) return;
    try {
      const response = await apiRequest('POST', `/v1/invoices/${selectedInvoice.id}/mark-chased`);
      const data = await response.json();
      setSelectedInvoice(data);
      await fetchInvoices();
      setSuccessMessage('Invoice marked as chased');
    } catch (err: any) {
      setError(err.message || 'Failed to mark invoice as chased');
    }
  };

  const toggleInvoiceSelection = (invoiceId: string) => {
    setSelectedInvoiceIds((prev) =>
      prev.includes(invoiceId) ? prev.filter((id) => id !== invoiceId) : [...prev, invoiceId]
    );
  };

  const toggleSelectAllInvoices = () => {
    if (selectedInvoiceIds.length === invoices.length) {
      setSelectedInvoiceIds([]);
    } else {
      setSelectedInvoiceIds(invoices.map((inv) => inv.id));
    }
  };

  const handleBulkPreview = async () => {
    if (selectedInvoiceIds.length === 0) {
      setError('Select at least one invoice');
      return;
    }
    try {
      const response = await apiRequest('POST', `/v1/invoices/send-chase/bulk`, {
        invoice_ids: selectedInvoiceIds,
        chase_stage: bulkChaseStage,  // Use selected stage
        dry_run: true,
      });
      const data = await response.json();
      setBulkPreview(data.results || []);
      setBulkPreviewOpen(true);
    } catch (err: any) {
      setError(err.message || 'Failed to preview bulk send');
    }
  };

  const handleBulkSend = async () => {
    if (selectedInvoiceIds.length === 0) return;
    try {
      const response = await apiRequest('POST', `/v1/invoices/send-chase/bulk`, {
        invoice_ids: selectedInvoiceIds,
        chase_stage: bulkChaseStage,  // Use selected stage
        dry_run: false,
      });
      const data = await response.json();
      setBulkPreview(data.results || []);
      await fetchInvoices();
      const stageInfo = CHASE_STAGES.find(s => s.stage === bulkChaseStage);
      setSuccessMessage(`Bulk ${stageInfo?.description || 'chase'} complete: ${data.sent} sent, ${data.failed} failed`);
      setSelectedInvoiceIds([]);
      setBulkPreviewOpen(false);
    } catch (err: any) {
      setError(err.message || 'Failed to send bulk emails');
    }
  };

  // Invoice action handlers
  const handleMarkAsPaid = async (invoiceId: string) => {
    setInvoiceActionLoading('paid');
    try {
      const response = await apiRequest('PATCH', `/v1/invoices/${invoiceId}/status?status=paid`);
      if (response.ok) {
        await fetchInvoices();
        setSuccessMessage('Invoice marked as paid');
        setInvoiceDrawerOpen(false);
        setSelectedInvoice(null);
      } else {
        const data = await response.json();
        setError(data.detail || 'Failed to mark as paid');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to mark as paid');
    } finally {
      setInvoiceActionLoading(null);
    }
  };

  const handleMarkAsUnpaid = async (invoiceId: string) => {
    setInvoiceActionLoading('unpaid');
    try {
      const response = await apiRequest('PATCH', `/v1/invoices/${invoiceId}/status?status=unpaid`);
      if (response.ok) {
        await fetchInvoices();
        setSuccessMessage('Invoice marked as unpaid');
        // Update selected invoice
        const data = await response.json();
        if (selectedInvoice && selectedInvoice.id === invoiceId) {
          setSelectedInvoice({ ...selectedInvoice, status: 'unpaid', paid_amount: null, paid_at: null });
        }
      } else {
        const data = await response.json();
        setError(data.detail || 'Failed to mark as unpaid');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to mark as unpaid');
    } finally {
      setInvoiceActionLoading(null);
    }
  };

  const handleCancelInvoice = async (invoiceId: string) => {
    setInvoiceActionLoading('cancel');
    try {
      const response = await apiRequest('PATCH', `/v1/invoices/${invoiceId}/status?status=cancelled`);
      if (response.ok) {
        await fetchInvoices();
        setSuccessMessage('Invoice cancelled');
        setInvoiceDrawerOpen(false);
        setSelectedInvoice(null);
      } else {
        const data = await response.json();
        setError(data.detail || 'Failed to cancel invoice');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to cancel invoice');
    } finally {
      setInvoiceActionLoading(null);
      setConfirmDialog({ open: false, action: null, invoiceId: null });
    }
  };

  const handleArchiveInvoice = async (invoiceId: string) => {
    setInvoiceActionLoading('archive');
    try {
      const response = await apiRequest('PATCH', `/v1/invoices/${invoiceId}/archive`);
      if (response.ok) {
        await fetchInvoices();
        const data = await response.json();
        setSuccessMessage(data.archived ? 'Invoice archived' : 'Invoice unarchived');
        setInvoiceDrawerOpen(false);
        setSelectedInvoice(null);
      } else {
        const data = await response.json();
        setError(data.detail || 'Failed to archive invoice');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to archive invoice');
    } finally {
      setInvoiceActionLoading(null);
    }
  };

  const handleDeleteInvoice = async (invoiceId: string) => {
    setInvoiceActionLoading('delete');
    try {
      const response = await apiRequest('DELETE', `/v1/invoices/${invoiceId}`);
      if (response.ok) {
        await fetchInvoices();
        setSuccessMessage('Invoice deleted');
        setInvoiceDrawerOpen(false);
        setSelectedInvoice(null);
      } else {
        const data = await response.json();
        setError(data.detail || 'Failed to delete invoice');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to delete invoice');
    } finally {
      setInvoiceActionLoading(null);
      setConfirmDialog({ open: false, action: null, invoiceId: null });
    }
  };

  // Fetch invoices when invoices tab is selected or filters change
  useEffect(() => {
    if (tabValue === 2 && business) {
      fetchInvoices();
    }
  }, [tabValue, business, invoiceStatusFilter, showArchivedInvoices, invoiceSortBy, invoiceSortOrder]);

  // Debounced search for invoices
  useEffect(() => {
    if (tabValue === 2 && business) {
      const timer = setTimeout(() => {
        fetchInvoices();
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [invoiceSearch]);

  if (authLoading || loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'grey.100' }}>
      <AppBar position="static">
        <Toolbar sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          {/* Logo/Avatar - Fixed size */}
          <Box sx={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
            {logoUrl ? (
              <img
                src={logoUrl}
                alt={businessProfile?.name || 'Business Logo'}
                style={{
                  width: '40px',
                  height: '40px',
                  objectFit: 'contain',
                  display: 'block',
                }}
              />
            ) : businessProfile?.name ? (
              <Avatar
                sx={{
                  width: 40,
                  height: 40,
                  bgcolor: 'primary.main',
                  fontSize: '0.875rem',
                }}
              >
                {getBusinessInitials(businessProfile.name)}
              </Avatar>
            ) : (
              <BusinessIcon sx={{ fontSize: 40 }} />
            )}
          </Box>
          
          {/* Business Name - Flexible with text overflow */}
          <Box
            sx={{
              flex: 1,
              minWidth: 0,
              overflow: 'hidden',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Typography
              variant="h6"
              sx={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {businessProfile?.name || business?.name || 'Business Dashboard'}
            </Typography>
          </Box>
          
          {/* Right side - User email and logout */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
            <Button
              variant="outlined"
              size="small"
              startIcon={<SmartToyIcon />}
              onClick={() => navigate('/app/assistant/chat')}
              sx={{ color: 'inherit', borderColor: 'rgba(255,255,255,0.4)' }}
            >
              AI Admin
            </Button>
            <Typography
              variant="body2"
              sx={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                maxWidth: { xs: '120px', sm: '200px', md: 'none' },
              }}
            >
              {user?.email}
            </Typography>
            <IconButton color="inherit" onClick={handleSignOut} data-testid="button-signout">
              <LogoutIcon />
            </IconButton>
          </Box>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 4 }}>
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
            <Card sx={{ mb: 3, p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
                {/* Left: Logo and business info */}
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  {logoUrl ? (
                    <Avatar 
                      src={logoUrl} 
                      alt={businessProfile?.name || business?.name || 'Business'}
                      sx={{ width: 48, height: 48, borderRadius: 1 }}
                      variant="rounded"
                    />
                  ) : (
                    <Avatar sx={{ width: 48, height: 48, borderRadius: 1, bgcolor: 'primary.main' }} variant="rounded">
                      {getBusinessInitials(businessProfile?.name || business?.name || 'B')}
                    </Avatar>
                  )}
                  <Box>
                    <Typography variant="h6" fontWeight={600} data-testid="text-business-name">
                      {businessProfile?.name || business.name}
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <Chip 
                        icon={<AccessTimeIcon />} 
                        label={business.timezone || 'Europe/London'} 
                        size="small" 
                        variant="outlined"
                      />
                      <Chip 
                        label={membership?.role || 'owner'} 
                        size="small" 
                        color="primary"
                      />
                    </Box>
                  </Box>
                </Box>
                
                {/* Right: Settings dropdown */}
                <Box>
                  <Button
                    variant="outlined"
                    onClick={(e) => setSettingsAnchor(e.currentTarget)}
                    endIcon={<SettingsIcon />}
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
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/email/outbox'); }}>
                      <ListItemIcon><OutboxIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Email Outbox</ListItemText>
                    </MenuItem>
                    <Divider />
                    <MenuItem onClick={() => { setSettingsAnchor(null); navigate('/app/help'); }}>
                      <ListItemIcon><HelpIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>Help & Support</ListItemText>
                    </MenuItem>
                  </Menu>
                </Box>
              </Box>
            </Card>

            <Paper sx={{ p: 3 }} elevation={1}>
              <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 0 }}>
                <Tabs 
                  value={tabValue} 
                  onChange={(_, v) => setTabValue(v)}
                  sx={{ 
                    '& .MuiTab-root': {
                      minHeight: 56,
                      textTransform: 'none',
                      fontWeight: 500,
                    }
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
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        Invoices
                        <Chip 
                          label={overdueInvoiceCount > 0 ? `${overdueInvoiceCount} overdue` : invoices.length} 
                          size="small" 
                          color={overdueInvoiceCount > 0 ? 'error' : 'default'}
                          sx={{ minWidth: 24, height: 22 }}
                        />
                      </Box>
                    }
                    data-testid="tab-invoices"
                  />
                </Tabs>
              </Box>

              <TabPanel value={tabValue} index={0}>
                {/* Header with filter chips and create button */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, flexWrap: 'wrap', gap: 2 }}>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Chip 
                      label={`Open (${tasks.filter(t => t.status !== 'completed').length})`}
                      onClick={() => setTaskFilter('open')}
                      color={taskFilter === 'open' ? 'primary' : 'default'}
                      variant={taskFilter === 'open' ? 'filled' : 'outlined'}
                    />
                    <Chip 
                      label={`Completed (${tasks.filter(t => t.status === 'completed').length})`}
                      onClick={() => setTaskFilter('completed')}
                      color={taskFilter === 'completed' ? 'primary' : 'default'}
                      variant={taskFilter === 'completed' ? 'filled' : 'outlined'}
                    />
                    <Chip 
                      label={`All (${tasks.length})`}
                      onClick={() => setTaskFilter('all')}
                      color={taskFilter === 'all' ? 'primary' : 'default'}
                      variant={taskFilter === 'all' ? 'filled' : 'outlined'}
                    />
                  </Box>
                  <Button
                    variant="contained"
                    startIcon={<AddIcon />}
                    onClick={() => setTaskDialogOpen(true)}
                    data-testid="button-create-task"
                  >
                    Create Task
                  </Button>
                </Box>

                {filteredTasks.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <TaskIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                    <Typography color="text.secondary">
                      {taskFilter === 'completed' ? 'No completed tasks' : taskFilter === 'open' ? 'No open tasks' : 'No tasks yet'}
                    </Typography>
                  </Box>
                ) : (
                  <Box>
                    {filteredTasks.map((task) => {
                      const isOverdue = task.due_at && new Date(task.due_at) < new Date() && task.status !== 'completed';
                      return (
                        <Card 
                          key={task.id}
                          data-testid={`card-task-${task.id}`}
                          sx={{ 
                            p: 2, 
                            mb: 2,
                            borderLeft: 4,
                            borderLeftColor: isOverdue ? 'error.main' : task.status === 'completed' ? 'success.main' : 'primary.main',
                            opacity: task.status === 'completed' ? 0.7 : 1,
                            '&:hover': { boxShadow: 2 },
                            transition: 'box-shadow 0.2s'
                          }}
                        >
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                            <Box sx={{ flex: 1 }}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, flexWrap: 'wrap' }}>
                                <Typography 
                                  variant="subtitle1" 
                                  fontWeight={600} 
                                  sx={{
                                    textDecoration: task.status === 'completed' ? 'line-through' : 'none'
                                  }}
                                >
                                  {task.title}
                                </Typography>
                                <Chip 
                                  label={task.status} 
                                  size="small"
                                  color={task.status === 'completed' ? 'success' : 'primary'}
                                  variant="outlined"
                                />
                              </Box>
                              
                              {task.description && (
                                <Typography 
                                  variant="body2" 
                                  color="text.secondary" 
                                  sx={{ 
                                    mb: 1,
                                    display: '-webkit-box',
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: 'vertical',
                                    overflow: 'hidden'
                                  }}
                                >
                                  {task.description}
                                </Typography>
                              )}
                              
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
                                {task.due_at && (
                                  <Typography variant="caption" color={isOverdue ? 'error.main' : 'text.secondary'}>
                                    {isOverdue ? '⚠️ Overdue: ' : 'Due: '}
                                    {new Date(task.due_at).toLocaleDateString('en-GB', { 
                                      day: 'numeric', 
                                      month: 'short',
                                      hour: '2-digit',
                                      minute: '2-digit'
                                    })}
                                  </Typography>
                                )}
                                {task.source && (
                                  <Chip label={task.source} size="small" variant="outlined" />
                                )}
                                <Typography variant="caption" color="text.disabled">
                                  Created: {new Date(task.created_at).toLocaleDateString('en-GB')}
                                </Typography>
                              </Box>
                            </Box>
                            
                            {/* Action buttons */}
                            <Box sx={{ display: 'flex', gap: 0.5, ml: 1 }}>
                              {task.status !== 'completed' && (
                                <Tooltip title="Mark complete">
                                  <IconButton 
                                    size="small" 
                                    onClick={() => handleCompleteTask(task.id)} 
                                    color="success"
                                    data-testid={`button-complete-task-${task.id}`}
                                  >
                                    <CheckCircleIcon fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                              )}
                            </Box>
                          </Box>
                        </Card>
                      );
                    })}
                  </Box>
                )}
              </TabPanel>

              <TabPanel value={tabValue} index={1}>
                {/* Filter chips */}
                <Box sx={{ display: 'flex', gap: 1, mb: 3 }}>
                  <Chip 
                    label={`New (${calls.filter(c => !c.archived).length})`}
                    onClick={() => setCallFilter('new')}
                    color={callFilter === 'new' ? 'primary' : 'default'}
                    variant={callFilter === 'new' ? 'filled' : 'outlined'}
                  />
                  <Chip 
                    label={`All (${calls.length})`}
                    onClick={() => setCallFilter('all')}
                    color={callFilter === 'all' ? 'primary' : 'default'}
                    variant={callFilter === 'all' ? 'filled' : 'outlined'}
                  />
                  <Chip 
                    label={`Archived (${calls.filter(c => c.archived).length})`}
                    onClick={() => setCallFilter('archived')}
                    color={callFilter === 'archived' ? 'primary' : 'default'}
                    variant={callFilter === 'archived' ? 'filled' : 'outlined'}
                  />
                </Box>

                {filteredCalls.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <PhoneIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                    <Typography color="text.secondary">
                      {callFilter === 'archived' ? 'No archived calls' : callFilter === 'new' ? 'No new calls' : 'No calls recorded'}
                    </Typography>
                  </Box>
                ) : (
                  <Grid container spacing={2}>
                    {filteredCalls.map((call) => (
                      <Grid size={{ xs: 12, sm: 6, md: 4 }} key={call.id}>
                        <Card 
                          variant="outlined" 
                          data-testid={`card-call-${call.id}`}
                          sx={{ 
                            position: 'relative',
                            '&:hover': { boxShadow: 3 },
                            transition: 'box-shadow 0.2s',
                            opacity: call.archived ? 0.7 : 1,
                          }}
                        >
                          {/* Archive button */}
                          <IconButton
                            size="small"
                            onClick={() => handleArchiveCall(call.id)}
                            sx={{ 
                              position: 'absolute', 
                              top: 8, 
                              right: 8,
                              opacity: 0.5,
                              '&:hover': { opacity: 1, backgroundColor: 'action.hover' }
                            }}
                            title={call.archived ? 'Unarchive call' : 'Archive call'}
                          >
                            <ArchiveIcon fontSize="small" />
                          </IconButton>

                          <CardContent sx={{ pr: 5 }}>
                            {/* Caller info */}
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                              <PhoneIcon color="primary" fontSize="small" />
                              <Typography variant="subtitle1" fontWeight={600}>
                                {call.caller_name || 'Unknown Caller'}
                              </Typography>
                            </Box>
                            
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                              {call.caller_number || call.phone_number || 'No number'}
                            </Typography>
                            
                            <Typography variant="caption" color="text.secondary">
                              {formatRelativeTime(call.created_at)}
                            </Typography>
                            
                            {/* Summary */}
                            {(call.summary || call.notes) && (
                              <Typography 
                                variant="body2" 
                                sx={{ 
                                  mt: 1.5, 
                                  color: 'text.secondary',
                                  display: '-webkit-box',
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical',
                                  overflow: 'hidden'
                                }}
                              >
                                {call.summary || call.notes}
                              </Typography>
                            )}
                            
                            {/* Intent badge */}
                            {call.intent && (
                              <Chip 
                                label={call.intent} 
                                size="small" 
                                sx={{ mt: 1.5 }}
                                color="primary"
                                variant="outlined"
                              />
                            )}

                            {/* Archived badge */}
                            {call.archived && (
                              <Chip 
                                label="Archived" 
                                size="small" 
                                sx={{ mt: 1.5, ml: call.intent ? 1 : 0 }}
                                color="default"
                                variant="outlined"
                              />
                            )}
                          </CardContent>
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                )}
              </TabPanel>

              <TabPanel value={tabValue} index={2}>
                {/* Summary Cards */}
                <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                  <Card variant="outlined" sx={{ p: 2, minWidth: 130 }}>
                    <Typography variant="caption" color="text.secondary">Overdue</Typography>
                    <Typography variant="h5" color="error">
                      {invoices.filter(inv => new Date(inv.due_date) < new Date() && inv.status !== 'paid' && !inv.archived).length}
                    </Typography>
                  </Card>
                  <Card variant="outlined" sx={{ p: 2, minWidth: 130 }}>
                    <Typography variant="caption" color="text.secondary">Due in 7 days</Typography>
                    <Typography variant="h5" color="warning.main">
                      {invoices.filter(inv => {
                        if (inv.status === 'paid' || inv.archived) return false;
                        const dueDate = new Date(inv.due_date);
                        const today = new Date();
                        const daysDiff = Math.ceil((dueDate.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
                        return daysDiff >= 0 && daysDiff <= 7;
                      }).length}
                    </Typography>
                  </Card>
                  <Card variant="outlined" sx={{ p: 2, minWidth: 130 }}>
                    <Typography variant="caption" color="text.secondary">Unpaid Total</Typography>
                    <Typography variant="h5">
                      {invoices
                        .filter(inv => inv.status !== 'paid' && !inv.archived)
                        .reduce((sum, inv) => sum + inv.amount, 0)
                        .toLocaleString('en-GB', { style: 'currency', currency: 'GBP' })}
                    </Typography>
                  </Card>
                </Box>

                {/* Search and Filter Toolbar */}
                <Box sx={{ mb: 3 }}>
                  {/* Search Bar */}
                  <TextField
                    placeholder="Search by customer name, invoice number, or email..."
                    value={invoiceSearch}
                    onChange={(e) => setInvoiceSearch(e.target.value)}
                    size="small"
                    fullWidth
                    sx={{ mb: 2 }}
                    InputProps={{
                      startAdornment: (
                        <InputAdornment position="start">
                          <SearchIcon color="action" />
                        </InputAdornment>
                      ),
                      endAdornment: invoiceSearch && (
                        <InputAdornment position="end">
                          <IconButton size="small" onClick={() => setInvoiceSearch('')}>
                            <ClearIcon fontSize="small" />
                          </IconButton>
                        </InputAdornment>
                      ),
                    }}
                  />

                  {/* Filters Row */}
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
                    {/* Status Filter Chips */}
                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                      {['all', 'unpaid', 'paid', 'partially_paid', 'cancelled'].map((status) => (
                        <Chip
                          key={status}
                          label={status === 'all' ? 'All' : status.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                          onClick={() => setInvoiceStatusFilter(status === 'all' ? '' : status)}
                          color={invoiceStatusFilter === status || (status === 'all' && !invoiceStatusFilter) ? 'primary' : 'default'}
                          variant={invoiceStatusFilter === status || (status === 'all' && !invoiceStatusFilter) ? 'filled' : 'outlined'}
                          size="small"
                        />
                      ))}
                    </Box>

                    {/* Show Archived Toggle */}
                    <FormControlLabel
                      control={
                        <Switch
                          size="small"
                          checked={showArchivedInvoices}
                          onChange={(e) => setShowArchivedInvoices(e.target.checked)}
                        />
                      }
                      label="Show archived"
                      sx={{ ml: 'auto' }}
                    />

                    {/* Sort Dropdown */}
                    <FormControl size="small" sx={{ minWidth: 140 }}>
                      <InputLabel>Sort by</InputLabel>
                      <Select
                        value={invoiceSortBy}
                        label="Sort by"
                        onChange={(e) => setInvoiceSortBy(e.target.value)}
                      >
                        <MenuItem value="due_date">Due Date</MenuItem>
                        <MenuItem value="amount">Amount</MenuItem>
                        <MenuItem value="customer_name">Customer Name</MenuItem>
                        <MenuItem value="created_at">Date Created</MenuItem>
                        <MenuItem value="status">Status</MenuItem>
                      </Select>
                    </FormControl>

                    {/* Sort Order Toggle */}
                    <IconButton
                      onClick={() => setInvoiceSortOrder(invoiceSortOrder === 'asc' ? 'desc' : 'asc')}
                      title={invoiceSortOrder === 'asc' ? 'Ascending' : 'Descending'}
                      size="small"
                    >
                      {invoiceSortOrder === 'asc' ? <ArrowUpwardIcon /> : <ArrowDownwardIcon />}
                    </IconButton>
                  </Box>
                </Box>

                {/* Bulk Actions Bar */}
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, alignItems: 'center', mb: 2 }}>
                  <FormControl size="small" sx={{ minWidth: 180 }}>
                    <InputLabel>Chase Stage</InputLabel>
                    <Select
                      value={bulkChaseStage}
                      label="Chase Stage"
                      onChange={(e) => setBulkChaseStage(Number(e.target.value))}
                    >
                      {CHASE_STAGES.map((stage) => (
                        <MenuItem key={stage.stage} value={stage.stage}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            {stage.stage >= 4 && <GavelIcon fontSize="small" color="error" />}
                            {stage.stage === 3 && <WarningIcon fontSize="small" color="warning" />}
                            <span>{stage.label}: {stage.description}</span>
                          </Box>
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <Button
                    variant="outlined"
                    startIcon={<SendIcon />}
                    disabled={selectedInvoiceIds.length === 0}
                    onClick={handleBulkPreview}
                    color={bulkChaseStage >= 3 ? 'warning' : 'primary'}
                  >
                    Preview ({selectedInvoiceIds.length})
                  </Button>
                  <input
                    accept=".csv"
                    style={{ display: 'none' }}
                    id="csv-upload-input"
                    type="file"
                    onChange={handleCsvUpload}
                    disabled={csvUploading}
                  />
                  <label htmlFor="csv-upload-input">
                    <Button
                      variant="contained"
                      component="span"
                      startIcon={csvUploading ? <CircularProgress size={20} /> : <CloudUploadIcon />}
                      disabled={csvUploading}
                    >
                      {csvUploading ? 'Uploading...' : 'Upload CSV'}
                    </Button>
                  </label>
                </Box>

                {invoicesLoading ? (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                    <CircularProgress />
                  </Box>
                ) : invoices.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <ReceiptIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                    <Typography color="text.secondary">No invoices found</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      Upload a CSV file to import invoices
                    </Typography>
                  </Box>
                ) : (
                  <TableContainer>
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableCell padding="checkbox">
                            <Checkbox
                              indeterminate={selectedInvoiceIds.length > 0 && selectedInvoiceIds.length < invoices.length}
                              checked={invoices.length > 0 && selectedInvoiceIds.length === invoices.length}
                              onChange={toggleSelectAllInvoices}
                            />
                          </TableCell>
                          <TableCell>Invoice #</TableCell>
                          <TableCell>Customer</TableCell>
                          <TableCell>Due Date</TableCell>
                          <TableCell align="right">Amount</TableCell>
                          <TableCell>Status</TableCell>
                          <TableCell>Chase Stage</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {invoices.map((invoice) => {
                          const isOverdue = invoice.due_date && new Date(invoice.due_date) < new Date() && invoice.status === 'unpaid';
                          return (
                          <TableRow
                            key={invoice.id}
                            hover
                            onClick={() => handleInvoiceClick(invoice)}
                            sx={{ 
                              cursor: 'pointer',
                              opacity: invoice.archived ? 0.6 : 1,
                              backgroundColor: invoice.status === 'paid' ? 'rgba(46, 125, 50, 0.04)' : 'inherit'
                            }}
                          >
                            <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                              <Checkbox
                                checked={selectedInvoiceIds.includes(invoice.id)}
                                onChange={() => toggleInvoiceSelection(invoice.id)}
                              />
                            </TableCell>
                            <TableCell>
                              <Typography fontWeight={500}>{invoice.invoice_number}</Typography>
                              {invoice.archived && (
                                <Chip label="Archived" size="small" sx={{ ml: 1 }} variant="outlined" />
                              )}
                            </TableCell>
                            <TableCell>
                              <Typography>{invoice.customer_name}</Typography>
                              {invoice.customer_email && (
                                <Typography variant="caption" color="text.secondary">
                                  {invoice.customer_email}
                                </Typography>
                              )}
                            </TableCell>
                            <TableCell>
                              <Typography color={isOverdue ? 'error.main' : 'text.primary'}>
                                {new Date(invoice.due_date).toLocaleDateString('en-GB')}
                              </Typography>
                            </TableCell>
                            <TableCell align="right">
                              <Typography fontWeight={600}>
                                {invoice.amount.toLocaleString('en-GB', { style: 'currency', currency: invoice.currency || 'GBP' })}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Chip
                                label={invoice.status || 'unpaid'}
                                size="small"
                                color={
                                  invoice.status === 'paid' ? 'success' : 
                                  invoice.status === 'cancelled' ? 'default' :
                                  isOverdue ? 'error' : 'warning'
                                }
                              />
                            </TableCell>
                            <TableCell>
                              <ChaseStageChip stage={invoice.chase_stage} />
                            </TableCell>
                          </TableRow>
                        );})}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </TabPanel>
            </Paper>
          </>
        )}
      </Container>

      {/* Invoice Detail Drawer */}
      <Drawer
        anchor="right"
        open={invoiceDrawerOpen}
        onClose={() => {
          setInvoiceDrawerOpen(false);
          setSelectedInvoice(null);
          setChaseDraft(null);
        }}
        PaperProps={{ sx: { width: { xs: '100%', sm: 500 } } }}
      >
        {selectedInvoice && (() => {
          const isOverdue = selectedInvoice.due_date && new Date(selectedInvoice.due_date) < new Date() && selectedInvoice.status === 'unpaid';
          const isPaid = selectedInvoice.status === 'paid';
          const isCancelled = selectedInvoice.status === 'cancelled';
          
          return (
          <Box sx={{ p: 3 }}>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Typography variant="h6" fontWeight={600}>
                Invoice {selectedInvoice.invoice_number}
              </Typography>
              <IconButton onClick={() => setInvoiceDrawerOpen(false)}>
                <CloseIcon />
              </IconButton>
            </Box>

            {/* Status Badge */}
            <Box sx={{ mb: 3 }}>
              <Chip
                label={selectedInvoice.status?.toUpperCase() || 'UNPAID'}
                color={
                  isPaid ? 'success' :
                  isCancelled ? 'default' :
                  isOverdue ? 'error' : 'warning'
                }
                sx={{ fontWeight: 600 }}
              />
              {isOverdue && !isPaid && !isCancelled && (
                <Typography variant="caption" color="error" sx={{ ml: 1 }}>
                  Overdue
                </Typography>
              )}
              {selectedInvoice.archived && (
                <Chip label="Archived" size="small" sx={{ ml: 1 }} variant="outlined" />
              )}
            </Box>

            {/* Customer Info */}
            <Box sx={{ mb: 3 }}>
              <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                Customer
              </Typography>
              <Typography variant="body1" fontWeight={500}>
                {selectedInvoice.customer_name}
              </Typography>
              {selectedInvoice.customer_email && (
                <Typography variant="body2" color="text.secondary">
                  {selectedInvoice.customer_email}
                </Typography>
              )}
            </Box>

            {/* Amount */}
            <Box sx={{ mb: 3 }}>
              <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                Amount
              </Typography>
              <Typography variant="h4" fontWeight={600} color={isPaid ? 'success.main' : 'text.primary'}>
                {selectedInvoice.amount.toLocaleString('en-GB', { style: 'currency', currency: selectedInvoice.currency || 'GBP' })}
              </Typography>
              {selectedInvoice.paid_amount && selectedInvoice.paid_amount < selectedInvoice.amount && (
                <Typography variant="body2" color="success.main">
                  {selectedInvoice.paid_amount.toLocaleString('en-GB', { style: 'currency', currency: selectedInvoice.currency || 'GBP' })} paid
                </Typography>
              )}
            </Box>

            {/* Due Date */}
            <Box sx={{ mb: 3 }}>
              <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                Due Date
              </Typography>
              <Typography variant="body1" color={isOverdue ? 'error.main' : 'text.primary'}>
                {new Date(selectedInvoice.due_date).toLocaleDateString('en-GB', {
                  day: 'numeric',
                  month: 'long',
                  year: 'numeric'
                })}
              </Typography>
            </Box>

            {/* Paid Date (if paid) */}
            {isPaid && selectedInvoice.paid_at && (
              <Box sx={{ mb: 3 }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Paid On
                </Typography>
                <Typography variant="body1" color="success.main">
                  {new Date(selectedInvoice.paid_at).toLocaleDateString('en-GB', {
                    day: 'numeric',
                    month: 'long',
                    year: 'numeric'
                  })}
                </Typography>
              </Box>
            )}

            {/* Chase Stage */}
            {!isPaid && !isCancelled && selectedInvoice.chase_stage > 0 && (
              <Box sx={{ mb: 3 }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Chase Status
                </Typography>
                <Chip
                  label={`Stage ${selectedInvoice.chase_stage}`}
                  size="small"
                  color={selectedInvoice.chase_stage >= 3 ? 'warning' : 'primary'}
                />
                {selectedInvoice.last_chased_at && (
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    Last chased: {new Date(selectedInvoice.last_chased_at).toLocaleDateString('en-GB')}
                  </Typography>
                )}
              </Box>
            )}

            <Divider sx={{ my: 3 }} />

            {/* Primary Action: Mark as Paid / Mark as Unpaid */}
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {!isPaid && !isCancelled && (
                <Button
                  variant="contained"
                  color="success"
                  size="large"
                  fullWidth
                  startIcon={invoiceActionLoading === 'paid' ? <CircularProgress size={20} color="inherit" /> : <CheckCircleIcon />}
                  onClick={() => handleMarkAsPaid(selectedInvoice.id)}
                  disabled={invoiceActionLoading !== null}
                >
                  Mark as Paid
                </Button>
              )}

              {isPaid && (
                <Button
                  variant="outlined"
                  color="warning"
                  fullWidth
                  startIcon={invoiceActionLoading === 'unpaid' ? <CircularProgress size={20} /> : <UndoIcon />}
                  onClick={() => handleMarkAsUnpaid(selectedInvoice.id)}
                  disabled={invoiceActionLoading !== null}
                >
                  Mark as Unpaid
                </Button>
              )}

              {/* Chase Email Section (only for unpaid) */}
              {!isPaid && !isCancelled && (
                <>
                  <Divider sx={{ my: 1 }} />
                  <Typography variant="subtitle2" color="text.secondary">Send Chase Email</Typography>
                  
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                    <FormControl size="small" sx={{ flex: 1, minWidth: 180 }}>
                      <InputLabel id="invoice-stage-label">Chase Stage</InputLabel>
                      <Select
                        labelId="invoice-stage-label"
                        label="Chase Stage"
                        value={invoiceStage}
                        onChange={(e) => setInvoiceStage(Number(e.target.value))}
                      >
                        {CHASE_STAGES.map((stage) => (
                          <MenuItem key={stage.stage} value={stage.stage}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              {stage.stage >= 4 && <GavelIcon fontSize="small" color="error" />}
                              {stage.stage === 3 && <WarningIcon fontSize="small" color="warning" />}
                              <span>{stage.label}: {stage.description}</span>
                            </Box>
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={dryRunSend}
                          onChange={(e) => setDryRunSend(e.target.checked)}
                          size="small"
                        />
                      }
                      label="Dry run"
                    />
                  </Box>
                  
                  {invoiceStage >= 3 && (
                    <Alert severity={invoiceStage >= 4 ? 'error' : 'warning'} sx={{ py: 0.5 }}>
                      {invoiceStage >= 4 
                        ? 'This will send a formal legal action notice.'
                        : 'This will send a final warning before potential legal action.'
                      }
                    </Alert>
                  )}

                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button
                      variant="outlined"
                      startIcon={<PreviewIcon />}
                      onClick={handleGetChaseDraft}
                      sx={{ flex: 1 }}
                    >
                      Preview
                    </Button>
                    <Button
                      variant="contained"
                      startIcon={<SendIcon />}
                      onClick={handleSendChaseEmail}
                      sx={{ flex: 1 }}
                    >
                      Send
                    </Button>
                  </Box>
                </>
              )}

              {/* Secondary Actions */}
              <Divider sx={{ my: 1 }} />
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button
                  variant="outlined"
                  color="inherit"
                  fullWidth
                  startIcon={invoiceActionLoading === 'archive' ? <CircularProgress size={20} /> : <ArchiveIcon />}
                  onClick={() => handleArchiveInvoice(selectedInvoice.id)}
                  disabled={invoiceActionLoading !== null}
                >
                  {selectedInvoice.archived ? 'Unarchive' : 'Archive'}
                </Button>

                {!isCancelled && !isPaid && (
                  <Button
                    variant="outlined"
                    color="warning"
                    fullWidth
                    startIcon={<CancelIcon />}
                    onClick={() => setConfirmDialog({ open: true, action: 'cancel', invoiceId: selectedInvoice.id })}
                    disabled={invoiceActionLoading !== null}
                  >
                    Cancel
                  </Button>
                )}
              </Box>

              {/* Delete (danger zone) */}
              <Button
                variant="text"
                color="error"
                size="small"
                startIcon={<DeleteIcon />}
                onClick={() => setConfirmDialog({ open: true, action: 'delete', invoiceId: selectedInvoice.id })}
                disabled={invoiceActionLoading !== null}
                sx={{ mt: 2 }}
              >
                Delete Invoice
              </Button>
            </Box>

            {chaseDraft && (
              <Box sx={{ mt: 3, p: 2, bgcolor: 'grey.100', borderRadius: 1 }}>
                <Typography variant="subtitle2" gutterBottom>Email Draft:</Typography>
                <Typography variant="body2" fontWeight="bold" gutterBottom>{chaseDraft.subject}</Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{chaseDraft.body}</Typography>
              </Box>
            )}
          </Box>
        );})()}
      </Drawer>

      {/* Bulk Send Preview Dialog */}
      <Dialog open={bulkPreviewOpen} onClose={() => setBulkPreviewOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          Review bulk send - {CHASE_STAGES.find(s => s.stage === bulkChaseStage)?.description || `Stage ${bulkChaseStage}`}
          {bulkChaseStage >= 3 && (
            <Chip 
              label={bulkChaseStage >= 4 ? 'Legal Action' : 'Final Warning'} 
              color={bulkChaseStage >= 4 ? 'error' : 'warning'} 
              size="small" 
              sx={{ ml: 1 }}
            />
          )}
        </DialogTitle>
        <DialogContent>
          {bulkPreview.length === 0 ? (
            <Typography color="text.secondary">No preview available.</Typography>
          ) : (
            <List>
              {bulkPreview.map((preview) => (
                <ListItem key={preview.invoice_id} alignItems="flex-start">
                  <ListItemText
                    primary={`Invoice ${preview.invoice_id}`}
                    secondary={
                      <>
                        <Typography variant="body2" fontWeight="bold">{preview.subject}</Typography>
                        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                          {preview.body}
                        </Typography>
                        {preview.error_message && (
                          <Typography variant="caption" color="error">{preview.error_message}</Typography>
                        )}
                      </>
                    }
                  />
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkPreviewOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            startIcon={<SendIcon />}
            onClick={handleBulkSend}
            disabled={bulkPreview.length === 0}
          >
            Send now
          </Button>
        </DialogActions>
      </Dialog>

      {/* Success Snackbar */}
      <Snackbar
        open={!!successMessage}
        autoHideDuration={6000}
        onClose={() => setSuccessMessage('')}
        message={successMessage}
      />

      <Dialog open={taskDialogOpen} onClose={() => setTaskDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Task</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Task Title"
            fullWidth
            variant="outlined"
            value={taskTitle}
            onChange={(e) => setTaskTitle(e.target.value)}
            sx={{ mb: 2, mt: 1 }}
            data-testid="input-task-title"
          />
          <TextField
            margin="dense"
            label="Description (optional)"
            fullWidth
            multiline
            rows={3}
            variant="outlined"
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            data-testid="input-task-description"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTaskDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateTask}
            variant="contained"
            disabled={savingTask || !taskTitle.trim()}
            data-testid="button-save-task"
          >
            {savingTask ? <CircularProgress size={20} /> : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Invoice Delete/Cancel Confirmation Dialog */}
      <Dialog
        open={confirmDialog.open}
        onClose={() => setConfirmDialog({ open: false, action: null, invoiceId: null })}
      >
        <DialogTitle>
          {confirmDialog.action === 'delete' ? 'Delete Invoice?' : 'Cancel Invoice?'}
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            {confirmDialog.action === 'delete'
              ? 'This will permanently delete this invoice. This action cannot be undone.'
              : 'This will mark the invoice as cancelled. You can still view it in the cancelled filter.'}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDialog({ open: false, action: null, invoiceId: null })}>
            Go Back
          </Button>
          <Button
            onClick={() => {
              if (confirmDialog.invoiceId) {
                if (confirmDialog.action === 'delete') {
                  handleDeleteInvoice(confirmDialog.invoiceId);
                } else if (confirmDialog.action === 'cancel') {
                  handleCancelInvoice(confirmDialog.invoiceId);
                }
              }
            }}
            color="error"
            variant="contained"
            disabled={invoiceActionLoading !== null}
          >
            {invoiceActionLoading ? <CircularProgress size={20} /> : confirmDialog.action === 'delete' ? 'Delete' : 'Cancel Invoice'}
          </Button>
        </DialogActions>
      </Dialog>

      {import.meta.env.DEV && <DebugPanel />}
    </Box>
  );
}
