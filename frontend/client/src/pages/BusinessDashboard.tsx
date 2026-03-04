import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
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
  Fab,
  Zoom,
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
  ChevronRight as ChevronRightIcon,
  AccountBalance as AccountBalanceIcon,
  MailOutline as MailOutlineIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, type Business, type Task, type Call, type BusinessMember, resolveLogoSrc } from '@/lib/supabase';
import { useMe } from '@/hooks/useMe';
import { apiRequest } from '@/lib/queryClient';
import { config } from '@/config/env';
import DebugPanel from '@/components/DebugPanel';
import EmailsTab from '@/components/EmailsTab';
import ReceptionistTab from '@/components/ReceptionistTab';
import { fetchEmailMessages } from '@/lib/emailApi';
import {
  TASK_CATEGORIES, TASK_PRIORITIES,
  getCategoryColor, getCategoryLabel,
  isOverdue as isTaskOverdue, isToday as isDateToday, formatDueDate,
} from '@/lib/taskConstants';

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
  const [searchParams, setSearchParams] = useSearchParams();
  const { user, signOut, loading: authLoading } = useAuth();
  const { data: businessProfile, isLoading: profileLoading } = useMe();
  
  const [tabValue, setTabValue] = useState(() => {
    const tab = searchParams.get('tab');
    if (tab === 'receptionist') return 4;
    if (tab === 'emails') return 3;
    if (tab === 'invoices') return 2;
    if (tab === 'calls') return 1;
    return 0;
  });
  const [membership, setMembership] = useState<BusinessMember | null>(null);
  const [business, setBusiness] = useState<Business | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [calls, setCalls] = useState<Call[]>([]);
  const [callFilter, setCallFilter] = useState<'all' | 'new' | 'archived'>('new');
  const [callSearch, setCallSearch] = useState('');
  const [callDateFilter, setCallDateFilter] = useState<'all' | 'today' | 'week' | 'month'>('all');
  const [showArchivedCalls, setShowArchivedCalls] = useState(false);
  const [selectedCall, setSelectedCall] = useState<Call | null>(null);
  const [callPanelOpen, setCallPanelOpen] = useState(false);
  const [taskFilter, setTaskFilter] = useState<'open' | 'completed' | 'all'>('open');
  const [settingsAnchor, setSettingsAnchor] = useState<null | HTMLElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  const logoUrl = resolveLogoSrc(businessProfile?.logo_url);

  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [taskDueAt, setTaskDueAt] = useState('');
  const [taskCategory, setTaskCategory] = useState('general');
  const [taskPriority, setTaskPriority] = useState('medium');
  const [savingTask, setSavingTask] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [priorityFilter, setPriorityFilter] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState('created_at');

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
    external_source: string | null;
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
  
  // Xero invoice sync state
  const [xeroInvoiceSyncing, setXeroInvoiceSyncing] = useState(false);
  const [xeroConnected, setXeroConnected] = useState(false);

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
      .is('deleted_at', null)
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
          description: taskDescription.trim() || null,
          status: 'open',
          due_at: taskDueAt ? new Date(taskDueAt).toISOString() : null,
          category: taskCategory,
          priority: taskPriority,
        });

      if (insertError) throw insertError;

      setTaskDialogOpen(false);
      setTaskTitle('');
      setTaskDescription('');
      setTaskDueAt('');
      setTaskCategory('general');
      setTaskPriority('medium');
      setSuccessMessage('Task created');
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

  const cycleTaskStatus = async (taskId: string, currentStatus: string) => {
    if (!business) return;
    const nextStatus =
      currentStatus === 'open' ? 'pending' :
      currentStatus === 'pending' ? 'completed' :
      'open';
    try {
      const { error: updateError } = await supabase
        .from('tasks')
        .update({ status: nextStatus, updated_at: new Date().toISOString() })
        .eq('id', taskId);
      if (updateError) throw updateError;
      await fetchTasks(business.id);
    } catch (err: any) {
      setError(err.message || 'Failed to update task status');
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

  // Filter calls based on filters
  const filteredCalls = useMemo(() => {
    let result = calls;
    
    // Filter by archived status
    if (!showArchivedCalls) {
      result = result.filter(c => !c.archived);
    }
    
    // Filter by search
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
    
    // Filter by date
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
  }, [calls, callSearch, callDateFilter, showArchivedCalls]);
  
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
    
    const todaysCalls = calls.filter(c => !c.archived && new Date(c.created_at) >= startOfToday);
    const newCalls = calls.filter(c => !c.archived);
    
    return {
      today: todaysCalls.length,
      total: newCalls.length,
    };
  }, [calls]);
  
  // Helper function to calculate call duration
  const calculateDuration = (start: string, end: string): string => {
    const startDate = new Date(start);
    const endDate = new Date(end);
    const diffMs = endDate.getTime() - startDate.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffSecs = Math.floor((diffMs % 60000) / 1000);
    
    if (diffMins > 0) {
      return `${diffMins}m ${diffSecs}s`;
    }
    return `${diffSecs}s`;
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

  // Filter & sort tasks
  const filteredTasks = useMemo(() => {
    let result = tasks.filter(t => !t.deleted_at);

    if (taskFilter === 'open') result = result.filter(t => t.status !== 'completed');
    else if (taskFilter === 'completed') result = result.filter(t => t.status === 'completed');

    if (categoryFilter) result = result.filter(t => (t.category || 'general') === categoryFilter);
    if (priorityFilter) result = result.filter(t => (t.priority || 'medium') === priorityFilter);

    const priorityOrder: Record<string, number> = { high: 0, medium: 1, low: 2 };
    result.sort((a, b) => {
      if (sortBy === 'due_at') {
        if (!a.due_at && !b.due_at) return 0;
        if (!a.due_at) return 1;
        if (!b.due_at) return -1;
        return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
      }
      if (sortBy === 'priority') {
        return (priorityOrder[a.priority] ?? 1) - (priorityOrder[b.priority] ?? 1);
      }
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });

    return result;
  }, [tasks, taskFilter, categoryFilter, priorityFilter, sortBy]);

  const overdueTasks = tasks.filter(t => t.due_at && new Date(t.due_at) < new Date() && t.status !== 'completed').length;
  const dueTodayTasks = tasks.filter(t => t.due_at && isDateToday(new Date(t.due_at)) && t.status !== 'completed').length;
  const pendingTasks = tasks.filter(t => t.status === 'pending').length;
  const openTaskCount = tasks.filter(t => t.status !== 'completed').length;
  const overdueInvoiceCount = invoices.filter(inv => new Date(inv.due_date) < new Date() && inv.status !== 'paid').length;
  const newCallCount = calls.filter(c => !c.archived).length;
  const [unreadEmailCount, setUnreadEmailCount] = useState(0);

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

  // Xero invoice sync
  const syncXeroInvoices = async () => {
    try {
      setXeroInvoiceSyncing(true);
      const resp = await apiRequest('POST', '/v1/invoices/xero/sync');
      if (resp.ok) {
        const data = await resp.json();
        if (data.synced > 0) {
          setSuccessMessage(`Synced ${data.synced} invoices from Xero`);
        }
        await fetchInvoices();
      }
    } catch (e) {
      console.error('Invoice sync failed:', e);
    } finally {
      setXeroInvoiceSyncing(false);
    }
  };

  // Check Xero status and auto-sync invoices when invoices tab is first opened
  useEffect(() => {
    if (tabValue !== 2 || !business) return;
    const checkXero = async () => {
      try {
        const resp = await apiRequest('GET', '/v1/accounting/xero/status');
        if (resp.ok) {
          const data = await resp.json();
          setXeroConnected(data.connected);
          if (data.connected) {
            syncXeroInvoices();
          }
        }
      } catch (e) {
        console.error('Xero status check failed:', e);
      }
    };
    checkXero();
  }, [tabValue, business]);

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
              startIcon={<AccountBalanceIcon />}
              onClick={() => navigate('/app/accounting')}
              sx={{ color: 'inherit', borderColor: 'rgba(255,255,255,0.4)' }}
            >
              Accounting
            </Button>
            <Button
              variant="outlined"
              size="small"
              onClick={() => navigate('/app/assistant/chat')}
              sx={{ 
                color: 'inherit', 
                borderColor: 'rgba(255,255,255,0.4)',
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                textTransform: 'none'
              }}
            >
              <Box
                sx={{
                  width: 24,
                  height: 24,
                  borderRadius: '50%',
                  overflow: 'hidden',
                  border: '2px solid rgba(255,255,255,0.3)'
                }}
              >
                <img 
                  src="/aria-avatar.png" 
                  alt="Aria" 
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
              </Box>
              <span>Aria</span>
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
                    <MenuItem onClick={() => { setSettingsAnchor(null); setTabValue(4); }}>
                      <ListItemIcon><SmartToyIcon fontSize="small" /></ListItemIcon>
                      <ListItemText>AI Receptionist</ListItemText>
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
                </Tabs>
              </Box>

              <TabPanel value={tabValue} index={0}>
                {/* Summary cards */}
                <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                  <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
                    <Typography variant="h5" fontWeight={700} color="error.main">{overdueTasks}</Typography>
                    <Typography variant="caption" color="text.secondary">Overdue</Typography>
                  </Card>
                  <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
                    <Typography variant="h5" fontWeight={700} color="warning.main">{dueTodayTasks}</Typography>
                    <Typography variant="caption" color="text.secondary">Due Today</Typography>
                  </Card>
                  <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
                    <Typography variant="h5" fontWeight={700} color="info.main">{pendingTasks}</Typography>
                    <Typography variant="caption" color="text.secondary">Pending</Typography>
                  </Card>
                  <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
                    <Typography variant="h5" fontWeight={700}>{openTaskCount}</Typography>
                    <Typography variant="caption" color="text.secondary">Total Open</Typography>
                  </Card>
                </Box>

                {/* Status filter + create button */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 2 }}>
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

                {/* Category filter chips */}
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
                  <Chip
                    label="All Categories"
                    size="small"
                    onClick={() => setCategoryFilter(null)}
                    color={!categoryFilter ? 'primary' : 'default'}
                    variant={!categoryFilter ? 'filled' : 'outlined'}
                  />
                  {TASK_CATEGORIES.map(cat => (
                    <Chip
                      key={cat.id}
                      label={cat.label}
                      size="small"
                      onClick={() => setCategoryFilter(cat.id)}
                      sx={{
                        bgcolor: categoryFilter === cat.id ? cat.color : undefined,
                        color: categoryFilter === cat.id ? '#fff' : undefined,
                        borderColor: categoryFilter === cat.id ? cat.color : undefined,
                        '&:hover': { opacity: 0.85 },
                      }}
                      variant={categoryFilter === cat.id ? 'filled' : 'outlined'}
                    />
                  ))}
                </Box>

                {/* Priority filter + sort */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="caption" color="text.secondary">Priority:</Typography>
                    {[{ id: null, label: 'All' }, ...TASK_PRIORITIES].map(p => (
                      <Chip
                        key={p.id ?? 'all'}
                        label={p.label}
                        size="small"
                        onClick={() => setPriorityFilter(p.id)}
                        variant={(p.id === null && !priorityFilter) || priorityFilter === p.id ? 'filled' : 'outlined'}
                        color={(p.id === null && !priorityFilter) || priorityFilter === p.id ? 'primary' : 'default'}
                        sx={{ height: 24, fontSize: '0.7rem' }}
                      />
                    ))}
                  </Box>
                  <FormControl size="small" sx={{ minWidth: 140 }}>
                    <InputLabel>Sort by</InputLabel>
                    <Select value={sortBy} label="Sort by" onChange={e => setSortBy(e.target.value)}>
                      <MenuItem value="created_at">Newest First</MenuItem>
                      <MenuItem value="due_at">Due Date</MenuItem>
                      <MenuItem value="priority">Priority</MenuItem>
                    </Select>
                  </FormControl>
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
                      const overdue = task.due_at && isTaskOverdue(task.due_at, task.status);
                      const dueToday = task.due_at && isDateToday(new Date(task.due_at)) && task.status !== 'completed';
                      const catColor = getCategoryColor(task.category || 'general');
                      return (
                        <Card
                          key={task.id}
                          data-testid={`card-task-${task.id}`}
                          sx={{
                            p: 2,
                            mb: 2,
                            borderLeft: 4,
                            borderLeftColor: catColor,
                            opacity: task.status === 'completed' ? 0.7 : 1,
                            '&:hover': { boxShadow: 2 },
                            transition: 'box-shadow 0.2s',
                          }}
                        >
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                            <Box sx={{ flex: 1 }}>
                              {/* Title row */}
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, flexWrap: 'wrap' }}>
                                <Typography
                                  variant="subtitle1"
                                  fontWeight={600}
                                  sx={{ textDecoration: task.status === 'completed' ? 'line-through' : 'none' }}
                                >
                                  {task.title}
                                </Typography>
                                <Chip
                                  label={getCategoryLabel(task.category || 'general')}
                                  size="small"
                                  sx={{ bgcolor: catColor, color: '#fff', height: 20, fontSize: '0.65rem' }}
                                />
                                <Chip
                                  label={`${(TASK_PRIORITIES.find(p => p.id === task.priority) || TASK_PRIORITIES[1]).icon} ${(task.priority || 'medium').charAt(0).toUpperCase() + (task.priority || 'medium').slice(1)}`}
                                  size="small"
                                  variant="outlined"
                                  sx={{
                                    height: 20,
                                    fontSize: '0.65rem',
                                    borderColor: task.priority === 'high' ? '#EF4444' : task.priority === 'low' ? '#10B981' : '#F59E0B',
                                    color: task.priority === 'high' ? '#EF4444' : task.priority === 'low' ? '#10B981' : '#F59E0B',
                                  }}
                                />
                              </Box>

                              {/* Description preview */}
                              {task.description && (
                                <Typography
                                  variant="body2"
                                  color="text.secondary"
                                  sx={{
                                    mb: 1,
                                    display: '-webkit-box',
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: 'vertical',
                                    overflow: 'hidden',
                                  }}
                                >
                                  {task.description}
                                </Typography>
                              )}

                              {/* Meta row */}
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
                                {task.due_at && (
                                  <Typography
                                    variant="caption"
                                    fontWeight={overdue || dueToday ? 600 : 400}
                                    color={overdue ? 'error.main' : dueToday ? 'warning.main' : 'text.secondary'}
                                  >
                                    {overdue ? `⚠️ Overdue: ${formatDueDate(task.due_at)}` : dueToday ? '📅 Due today' : formatDueDate(task.due_at)}
                                  </Typography>
                                )}
                                {task.source === 'email' && (
                                  <Chip label="From email" size="small" variant="outlined" color="info" sx={{ height: 20, fontSize: '0.65rem' }} />
                                )}
                                {task.source === 'call' && (
                                  <Chip label="From call" size="small" variant="outlined" color="success" sx={{ height: 20, fontSize: '0.65rem' }} />
                                )}
                                {task.source === 'manual' && (
                                  <Chip label="Manual" size="small" variant="outlined" sx={{ height: 20, fontSize: '0.65rem' }} />
                                )}
                                <Typography variant="caption" color="text.disabled">
                                  {new Date(task.created_at).toLocaleDateString('en-GB')}
                                </Typography>
                              </Box>
                            </Box>

                            {/* Action buttons */}
                            <Box sx={{ display: 'flex', gap: 0.5, ml: 1, alignItems: 'center' }}>
                              <Tooltip title={`Status: ${task.status} — click to cycle`}>
                                <Chip
                                  label={
                                    task.status === 'completed' ? '✅ Done' :
                                    task.status === 'pending' ? '⏳ Pending' :
                                    '⬜ Open'
                                  }
                                  size="small"
                                  onClick={() => cycleTaskStatus(task.id, task.status)}
                                  sx={{
                                    cursor: 'pointer',
                                    fontWeight: 500,
                                    bgcolor:
                                      task.status === 'completed' ? '#dcfce7' :
                                      task.status === 'pending' ? '#fef3c7' :
                                      '#f3f4f6',
                                    color:
                                      task.status === 'completed' ? '#15803d' :
                                      task.status === 'pending' ? '#92400e' :
                                      '#4b5563',
                                  }}
                                />
                              </Tooltip>
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
                {/* Stats Cards */}
                <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
                  <Card sx={{ flex: 1, p: 2 }}>
                    <Typography variant="caption" color="text.secondary">Today's Calls</Typography>
                    <Typography variant="h4" color="primary.main">{callStats.today}</Typography>
                  </Card>
                  <Card sx={{ flex: 1, p: 2 }}>
                    <Typography variant="caption" color="text.secondary">Total Active</Typography>
                    <Typography variant="h4">{callStats.total}</Typography>
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
                              {/* Icon */}
                              <Box sx={{ 
                                width: 40, 
                                height: 40, 
                                borderRadius: '50%', 
                                bgcolor: 'primary.light',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexShrink: 0
                              }}>
                                <PhoneIcon color="primary" fontSize="small" />
                              </Box>
                              
                              {/* Main Content */}
                              <Box sx={{ flex: 1, minWidth: 0 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                  <Typography variant="subtitle1" fontWeight={600} noWrap>
                                    {call.caller_name || 'Unknown Caller'}
                                  </Typography>
                                  {call.archived && (
                                    <Chip label="Archived" size="small" />
                                  )}
                                </Box>
                                <Typography variant="body2" color="text.secondary" noWrap>
                                  {call.caller_number || call.phone_number || 'No number'}
                                  {(call.summary || call.notes) && ` • ${(call.summary || call.notes || '').substring(0, 50)}...`}
                                </Typography>
                              </Box>
                              
                              {/* Right side: Time and Intent */}
                              <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                                <Typography variant="caption" color="text.secondary">
                                  {new Date(call.created_at).toLocaleTimeString('en-GB', { 
                                    hour: '2-digit', 
                                    minute: '2-digit' 
                                  })}
                                </Typography>
                                {call.intent && (
                                  <Box>
                                    <Chip label={call.intent} size="small" variant="outlined" />
                                  </Box>
                                )}
                              </Box>
                              
                              {/* Arrow */}
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
                            <PhoneIcon color="primary" />
                            <Typography variant="h6" fontWeight={600}>
                              Call Details
                            </Typography>
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
                          {selectedCall.started_at && selectedCall.ended_at && (
                            <Typography variant="caption" color="text.secondary">
                              Duration: {calculateDuration(selectedCall.started_at, selectedCall.ended_at)}
                            </Typography>
                          )}
                        </Box>

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
                            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                              Transcript
                            </Typography>
                            <Card sx={{ p: 2, bgcolor: 'grey.50', maxHeight: 300, overflow: 'auto' }}>
                              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                                {selectedCall.transcript}
                              </Typography>
                            </Card>
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
                              setTaskDialogOpen(true);
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
                {/* Xero sync indicator */}
                {xeroConnected && (
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      mb: 2,
                      px: 2,
                      py: 1,
                      bgcolor: 'grey.50',
                      borderRadius: 2,
                    }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main' }} />
                      <Typography variant="body2" color="text.secondary">
                        Synced with Xero
                      </Typography>
                      {xeroInvoiceSyncing && <CircularProgress size={14} sx={{ ml: 0.5 }} />}
                    </Box>
                    <Button
                      size="small"
                      onClick={syncXeroInvoices}
                      disabled={xeroInvoiceSyncing}
                    >
                      Sync now
                    </Button>
                  </Box>
                )}

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
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                <Typography fontWeight={500}>{invoice.invoice_number}</Typography>
                                {invoice.external_source === 'xero' && (
                                  <Chip label="Xero" size="small" sx={{ height: 18, fontSize: '0.65rem', bgcolor: 'rgba(25, 118, 210, 0.08)', color: 'primary.main' }} />
                                )}
                                {invoice.archived && (
                                  <Chip label="Archived" size="small" sx={{ ml: 0.5 }} variant="outlined" />
                                )}
                              </Box>
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

              <TabPanel value={tabValue} index={3}>
                {business && <EmailsTab businessId={business.id} />}
              </TabPanel>

              <TabPanel value={tabValue} index={4}>
                {business && <ReceptionistTab businessId={business.id} />}
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

          <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
            Category
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
            {TASK_CATEGORIES.map(cat => (
              <Chip
                key={cat.id}
                label={cat.label}
                size="small"
                onClick={() => setTaskCategory(cat.id)}
                sx={{
                  bgcolor: taskCategory === cat.id ? cat.color : undefined,
                  color: taskCategory === cat.id ? '#fff' : undefined,
                  borderColor: taskCategory === cat.id ? cat.color : undefined,
                  '&:hover': { opacity: 0.85 },
                }}
                variant={taskCategory === cat.id ? 'filled' : 'outlined'}
              />
            ))}
          </Box>

          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <FormControl size="small" sx={{ flex: 1 }}>
              <InputLabel>Priority</InputLabel>
              <Select
                value={taskPriority}
                label="Priority"
                onChange={(e) => setTaskPriority(e.target.value)}
              >
                {TASK_PRIORITIES.map(p => (
                  <MenuItem key={p.id} value={p.id}>{p.icon} {p.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Due Date (optional)"
              type="datetime-local"
              size="small"
              sx={{ flex: 1 }}
              value={taskDueAt}
              onChange={(e) => setTaskDueAt(e.target.value)}
              InputLabelProps={{ shrink: true }}
              data-testid="input-task-due-date"
            />
          </Box>

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

      {/* Floating Aria Button */}
      <Tooltip title="Talk to Aria" placement="left" TransitionComponent={Zoom}>
        <Fab
          color="primary"
          aria-label="Talk to Aria"
          onClick={() => navigate('/app/assistant/chat')}
          sx={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            width: 64,
            height: 64,
            boxShadow: '0 4px 20px rgba(99, 102, 241, 0.4)',
            background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
            border: '3px solid white',
            overflow: 'hidden',
            transition: 'all 0.3s ease',
            animation: 'pulse-aria 2s infinite',
            '&:hover': {
              transform: 'scale(1.1)',
              boxShadow: '0 6px 30px rgba(99, 102, 241, 0.6)',
            },
            '@keyframes pulse-aria': {
              '0%, 100%': { boxShadow: '0 4px 20px rgba(99, 102, 241, 0.4)' },
              '50%': { boxShadow: '0 4px 30px rgba(99, 102, 241, 0.7)' },
            }
          }}
        >
          <img 
            src="/aria-avatar.png" 
            alt="Aria" 
            style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }}
          />
        </Fab>
      </Tooltip>
    </Box>
  );
}
