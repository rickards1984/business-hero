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
  Snackbar,
  Checkbox,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
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

export default function BusinessDashboard() {
  const navigate = useNavigate();
  const { user, signOut, loading: authLoading } = useAuth();
  const { data: businessProfile, isLoading: profileLoading } = useMe();
  
  const [tabValue, setTabValue] = useState(0);
  const [membership, setMembership] = useState<BusinessMember | null>(null);
  const [business, setBusiness] = useState<Business | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [calls, setCalls] = useState<Call[]>([]);
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
  const [bulkPreviewOpen, setBulkPreviewOpen] = useState(false);
  const [bulkPreview, setBulkPreview] = useState<{ invoice_id: string; subject: string; body: string; status: string; error_message?: string }[]>([]);

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
      const { data: memberData, error: memberError } = await supabase
        .from('business_members')
        .select('*, businesses(*)')
        .eq('user_id', user?.id)
        .single();

      if (memberError) {
        if (memberError.code === 'PGRST116') {
          setError('You are not assigned to any business. Please contact an administrator.');
        } else {
          throw memberError;
        }
        setLoading(false);
        return;
      }

      setMembership(memberData);
      setBusiness(memberData.businesses);

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

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  // Invoice functions
  const fetchInvoices = async () => {
    if (!business) return;
    setInvoicesLoading(true);
    try {
      const response = await apiRequest('GET', `/v1/invoices?status=unpaid&overdue=true`);
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
      const response = await apiRequest('POST', `/v1/invoices/${selectedInvoice.id}/chase-draft`);
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
        chase_stage: invoiceStage - 1,
        dry_run: dryRunSend,
      });
      const data = await response.json();
      if (dryRunSend) {
        setChaseDraft({ subject: data.subject, body: data.body, chase_stage: data.chase_stage });
        setSuccessMessage('Preview generated (dry run)');
        return;
      }
      await fetchInvoices();
      setSuccessMessage('Chase email sent');
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
        chase_stage: 0,
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
        chase_stage: 0,
        dry_run: false,
      });
      const data = await response.json();
      setBulkPreview(data.results || []);
      await fetchInvoices();
      setSuccessMessage(`Bulk send complete: ${data.sent} sent, ${data.failed} failed`);
      setSelectedInvoiceIds([]);
      setBulkPreviewOpen(false);
    } catch (err: any) {
      setError(err.message || 'Failed to send bulk emails');
    }
  };

  // Fetch invoices when invoices tab is selected
  useEffect(() => {
    if (tabValue === 2 && business) {
      fetchInvoices();
    }
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
            <Paper sx={{ p: 3, mb: 3 }} elevation={1}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h5">
                  Business Profile
                </Typography>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={<SettingsIcon />}
                    onClick={() => navigate('/app/settings/email')}
                  >
                    Email Settings
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={<OutboxIcon />}
                    onClick={() => navigate('/app/email/outbox')}
                  >
                    Email Outbox
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => navigate('/app/help')}
                  >
                    Help / Support
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={<LinkIcon />}
                    onClick={() => navigate('/app/settings/awaz')}
                  >
                    Awaz Settings
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => navigate('/app/settings/branding')}
                  >
                    Branding Settings
                  </Button>
                </Box>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                {logoUrl ? (
                  <img
                    src={logoUrl}
                    alt={businessProfile?.name || business?.name || 'Business Logo'}
                    style={{
                      height: '64px',
                      width: 'auto',
                      maxWidth: '200px',
                      objectFit: 'contain',
                    }}
                  />
                ) : businessProfile?.name || business?.name ? (
                  <Avatar
                    sx={{
                      width: 64,
                      height: 64,
                      bgcolor: 'primary.main',
                      fontSize: '1.5rem',
                    }}
                  >
                    {getBusinessInitials(businessProfile?.name || business?.name || '')}
                  </Avatar>
                ) : (
                  <BusinessIcon sx={{ fontSize: 64, color: 'text.disabled' }} />
                )}
                <Box>
                  <Typography variant="h6" data-testid="text-business-name">
                    {businessProfile?.name || business.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Business Logo
                  </Typography>
                </Box>
              </Box>
              <Grid container spacing={3}>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Business Name
                  </Typography>
                  <Typography variant="body1" fontWeight="medium">
                    {businessProfile?.name || business.name}
                  </Typography>
                </Grid>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Timezone
                  </Typography>
                  <Chip
                    icon={<AccessTimeIcon />}
                    label={business.timezone}
                    size="small"
                    variant="outlined"
                  />
                </Grid>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Your Role
                  </Typography>
                  <Chip
                    label={membership?.role || 'Member'}
                    size="small"
                    color="primary"
                  />
                </Grid>
              </Grid>
            </Paper>

            <Paper sx={{ p: 3 }} elevation={1}>
              <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 0 }}>
                <Tabs value={tabValue} onChange={(_, v) => setTabValue(v)}>
                  <Tab
                    icon={<TaskIcon />}
                    iconPosition="start"
                    label={`Tasks (${tasks.length})`}
                    data-testid="tab-tasks"
                  />
                  <Tab
                    icon={<PhoneIcon />}
                    iconPosition="start"
                    label={`Calls (${calls.length})`}
                    data-testid="tab-calls"
                  />
                  <Tab
                    icon={<ReceiptIcon />}
                    iconPosition="start"
                    label={`Invoices (${invoices.length})`}
                    data-testid="tab-invoices"
                  />
                </Tabs>
              </Box>

              <TabPanel value={tabValue} index={0}>
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
                  <Button
                    variant="contained"
                    startIcon={<AddIcon />}
                    onClick={() => setTaskDialogOpen(true)}
                    data-testid="button-create-task"
                  >
                    Create Task
                  </Button>
                </Box>

                {tasks.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <TaskIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                    <Typography color="text.secondary">No tasks yet</Typography>
                  </Box>
                ) : (
                  <Grid container spacing={2}>
                    {tasks.map((task) => (
                      <Grid size={{ xs: 12, sm: 6, md: 4 }} key={task.id}>
                        <Card
                          variant="outlined"
                          sx={{
                            opacity: task.status === 'completed' ? 0.7 : 1,
                          }}
                          data-testid={`card-task-${task.id}`}
                        >
                          <CardContent>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1, gap: 1 }}>
                              <Typography variant="subtitle1" fontWeight="medium" sx={{ flexGrow: 1 }}>
                                {task.title}
                              </Typography>
                              <Chip
                                label={task.status}
                                size="small"
                                color={task.status === 'completed' ? 'success' : 'warning'}
                              />
                            </Box>
                            {task.description && (
                              <Typography variant="body2" color="text.secondary">
                                {task.description}
                              </Typography>
                            )}
                            <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 1 }}>
                              {new Date(task.created_at).toLocaleString()}
                            </Typography>
                          </CardContent>
                          {task.status !== 'completed' && (
                            <CardActions>
                              <Button
                                size="small"
                                startIcon={<CheckCircleIcon />}
                                onClick={() => handleCompleteTask(task.id)}
                                data-testid={`button-complete-task-${task.id}`}
                              >
                                Complete
                              </Button>
                            </CardActions>
                          )}
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                )}
              </TabPanel>

              <TabPanel value={tabValue} index={1}>
                {calls.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <PhoneIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                    <Typography color="text.secondary">No calls recorded</Typography>
                  </Box>
                ) : (
                  <Grid container spacing={2}>
                    {calls.map((call) => (
                      <Grid size={{ xs: 12, sm: 6, md: 4 }} key={call.id}>
                        <Card variant="outlined" data-testid={`card-call-${call.id}`}>
                          <CardContent>
                            <Typography variant="subtitle1" fontWeight="medium">
                              {call.caller_name}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {call.phone_number}
                            </Typography>
                            {call.notes && (
                              <Typography variant="body2" sx={{ mt: 1 }}>
                                {call.notes}
                              </Typography>
                            )}
                            <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 1 }}>
                              {new Date(call.created_at).toLocaleString()}
                            </Typography>
                          </CardContent>
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                )}
              </TabPanel>

              <TabPanel value={tabValue} index={2}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <Card variant="outlined" sx={{ p: 2, minWidth: 150 }}>
                      <Typography variant="caption" color="text.secondary">Overdue</Typography>
                      <Typography variant="h5" color="error">
                        {invoices.filter(inv => new Date(inv.due_date) < new Date() && inv.status !== 'paid').length}
                      </Typography>
                    </Card>
                    <Card variant="outlined" sx={{ p: 2, minWidth: 150 }}>
                      <Typography variant="caption" color="text.secondary">Due in 7 days</Typography>
                      <Typography variant="h5" color="warning.main">
                        {invoices.filter(inv => {
                          const dueDate = new Date(inv.due_date);
                          const today = new Date();
                          const daysDiff = Math.ceil((dueDate.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
                          return daysDiff >= 0 && daysDiff <= 7 && inv.status !== 'paid';
                        }).length}
                      </Typography>
                    </Card>
                    <Card variant="outlined" sx={{ p: 2, minWidth: 150 }}>
                      <Typography variant="caption" color="text.secondary">Unpaid Total</Typography>
                      <Typography variant="h5">
                        {invoices
                          .filter(inv => inv.status !== 'paid')
                          .reduce((sum, inv) => sum + inv.amount, 0)
                          .toLocaleString('en-GB', { style: 'currency', currency: 'GBP' })}
                      </Typography>
                    </Card>
                  </Box>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button
                      variant="outlined"
                      startIcon={<SendIcon />}
                      disabled={selectedInvoiceIds.length === 0}
                      onClick={handleBulkPreview}
                    >
                      Send stage 1
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
                        {invoices.map((invoice) => (
                          <TableRow
                            key={invoice.id}
                            hover
                            onClick={() => handleInvoiceClick(invoice)}
                            sx={{ cursor: 'pointer' }}
                          >
                            <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                              <Checkbox
                                checked={selectedInvoiceIds.includes(invoice.id)}
                                onChange={() => toggleInvoiceSelection(invoice.id)}
                              />
                            </TableCell>
                            <TableCell>{invoice.invoice_number}</TableCell>
                            <TableCell>{invoice.customer_name}</TableCell>
                            <TableCell>{new Date(invoice.due_date).toLocaleDateString()}</TableCell>
                            <TableCell align="right">
                              {invoice.amount.toLocaleString('en-GB', { style: 'currency', currency: invoice.currency || 'GBP' })}
                            </TableCell>
                            <TableCell>
                              <Chip
                                label={invoice.status}
                                size="small"
                                color={invoice.status === 'paid' ? 'success' : invoice.status === 'overdue' ? 'error' : 'warning'}
                              />
                            </TableCell>
                            <TableCell>{invoice.chase_stage}</TableCell>
                          </TableRow>
                        ))}
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
        {selectedInvoice && (
          <Box sx={{ p: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Typography variant="h6">Invoice Details</Typography>
              <IconButton onClick={() => setInvoiceDrawerOpen(false)}>
                <CloseIcon />
              </IconButton>
            </Box>
            
            <Divider sx={{ mb: 2 }} />
            
            <List>
              <ListItem>
                <ListItemText primary="Invoice Number" secondary={selectedInvoice.invoice_number} />
              </ListItem>
              <ListItem>
                <ListItemText primary="Customer" secondary={selectedInvoice.customer_name} />
              </ListItem>
              {selectedInvoice.customer_email && (
                <ListItem>
                  <ListItemText primary="Email" secondary={selectedInvoice.customer_email} />
                </ListItem>
              )}
              <ListItem>
                <ListItemText primary="Due Date" secondary={new Date(selectedInvoice.due_date).toLocaleDateString()} />
              </ListItem>
              <ListItem>
                <ListItemText 
                  primary="Amount" 
                  secondary={selectedInvoice.amount.toLocaleString('en-GB', { style: 'currency', currency: selectedInvoice.currency || 'GBP' })} 
                />
              </ListItem>
              <ListItem>
                <ListItemText primary="Status" secondary={selectedInvoice.status} />
              </ListItem>
              <ListItem>
                <ListItemText primary="Chase Stage" secondary={selectedInvoice.chase_stage} />
              </ListItem>
              {selectedInvoice.last_chased_at && (
                <ListItem>
                  <ListItemText 
                    primary="Last Chased" 
                    secondary={new Date(selectedInvoice.last_chased_at).toLocaleString()} 
                  />
                </ListItem>
              )}
            </List>

            <Divider sx={{ my: 2 }} />

            <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
              <FormControl size="small" fullWidth>
                <InputLabel id="invoice-stage-label">Stage</InputLabel>
                <Select
                  labelId="invoice-stage-label"
                  label="Stage"
                  value={invoiceStage}
                  onChange={(e) => setInvoiceStage(Number(e.target.value))}
                >
                  <MenuItem value={1}>Stage 1</MenuItem>
                  <MenuItem value={2}>Stage 2</MenuItem>
                  <MenuItem value={3}>Stage 3</MenuItem>
                  <MenuItem value={4}>Stage 4</MenuItem>
                </Select>
              </FormControl>
              <FormControlLabel
                control={
                  <Switch
                    checked={dryRunSend}
                    onChange={(e) => setDryRunSend(e.target.checked)}
                  />
                }
                label="Dry run"
              />
            </Box>

            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Button
                variant="outlined"
                startIcon={<PreviewIcon />}
                onClick={handleGetChaseDraft}
                fullWidth
              >
                Preview chase email
              </Button>
              
              <Button
                variant="contained"
                startIcon={<EmailIcon />}
                onClick={handleSendChaseEmail}
                fullWidth
              >
                Send chase email
              </Button>

              <Button
                variant="outlined"
                startIcon={<CheckCircleOutlineIcon />}
                onClick={handleMarkChased}
                fullWidth
              >
                Mark Chased
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
        )}
      </Drawer>

      {/* Bulk Send Preview Dialog */}
      <Dialog open={bulkPreviewOpen} onClose={() => setBulkPreviewOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Review bulk send (Stage 1)</DialogTitle>
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

      {import.meta.env.DEV && <DebugPanel />}
    </Box>
  );
}
