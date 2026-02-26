import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Box,
  Container,
  Typography,
  Card,
  CardContent,
  Button,
  Tabs,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  IconButton,
  TextField,
  InputAdornment,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  Alert,
  Stepper,
  Step,
  StepLabel,
  Grid,
  Divider,
  LinearProgress,
  Tooltip,
  Menu,
  ListItemIcon,
  ListItemText,
  Checkbox,
  Snackbar,
} from '@mui/material';
import {
  ArrowBack as ArrowBackIcon,
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  AccountBalance as AccountBalanceIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
  Upload as UploadIcon,
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  MoreVert as MoreVertIcon,
  CheckCircle as CheckCircleIcon,
  Category as CategoryIcon,
  Receipt as ReceiptIcon,
  FilterList as FilterListIcon,
  FileDownload as FileDownloadIcon,
  Refresh as RefreshIcon,
  Close as CloseIcon,
  Link as LinkIcon,
  Sync as SyncIcon,
  CheckCircleOutline as CheckCircleOutlineIcon,
  LinkOff as LinkOffIcon,
} from '@mui/icons-material';
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
  LineChart,
  Line,
  ReferenceLine,
} from 'recharts';
import { useNavigate } from 'react-router-dom';
import { apiRequest } from '@/lib/queryClient';
import { config } from '@/config/env';
import { supabase } from '@/lib/supabase';

// ============== Types ==============

interface Category {
  id: string;
  name: string;
  type: 'income' | 'expense';
  color: string;
  is_default: boolean;
}

interface Transaction {
  id: string;
  transaction_date: string;
  description: string;
  amount: number;
  type: 'income' | 'expense';
  reference?: string;
  payee_payer?: string;
  account?: string;
  notes?: string;
  is_reconciled: boolean;
  category?: {
    id: string;
    name: string;
    color: string;
  };
}

interface Summary {
  period: {
    start_date: string;
    end_date: string;
    label: string;
  };
  totals: {
    income: number;
    expense: number;
    net: number;
    transaction_count: number;
  };
  categories: {
    income: { name: string; color: string; total: number; count: number }[];
    expense: { name: string; color: string; total: number; count: number }[];
  };
  trend: { month: string; income: number; expense: number }[];
}

interface ColumnMapping {
  date_column?: string;
  description_column?: string;
  amount_column?: string;
  type_column?: string;
  income_column?: string;
  expense_column?: string;
  reference_column?: string;
  payee_column?: string;
}

// ============== Main Component ==============

const Accounting: React.FC = () => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState(0);
  const [loading, setLoading] = useState(true);
  
  // Data
  const [summary, setSummary] = useState<Summary | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [totalTransactions, setTotalTransactions] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [perPage, setPerPage] = useState(50);

  // Filters
  const [period, setPeriod] = useState<'month' | 'quarter' | 'year' | 'all'>('month');
  const [transactionType, setTransactionType] = useState<'all' | 'income' | 'expense'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  
  // Dialogs
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [addTransactionOpen, setAddTransactionOpen] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportPeriodStart, setExportPeriodStart] = useState('');
  const [exportPeriodEnd, setExportPeriodEnd] = useState('');

  // AI Insights
  const [aiInsights, setAiInsights] = useState<{
    loading: boolean;
    data: any | null;
    error: string | null;
  }>({ loading: false, data: null, error: null });
  const [showInsights, setShowInsights] = useState(false);

  // ─── Xero Integration State ────────────────────────────────
  const [xeroStatus, setXeroStatus] = useState<{
    connected: boolean;
    tenant_name?: string;
    last_sync_at?: string;
    connected_at?: string;
  } | null>(null);
  const [xeroSyncing, setXeroSyncing] = useState(false);
  const [xeroSyncResult, setXeroSyncResult] = useState<{
    new_transactions: number;
    updated_transactions: number;
    synced_at: string;
  } | null>(null);
  const [xeroLoading, setXeroLoading] = useState(true);
  const [snackbar, setSnackbar] = useState<{
    open: boolean;
    message: string;
    severity: 'success' | 'error' | 'info';
  }>({ open: false, message: '', severity: 'info' });
  const [financialSummary, setFinancialSummary] = useState<{
    bank_accounts: Array<{ name: string; balance: number; account_id?: string }>;
    total_bank_balance: number | null;
    profit_and_loss: {
      income: number | null;
      expenses: number | null;
      net_profit: number | null;
      period_start: string | null;
      period_end: string | null;
    };
    invoices: {
      overdue_count: number;
      overdue_amount: number;
      due_count: number;
      due_amount: number;
      total_outstanding: number;
    };
    xero_connected: boolean;
  } | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // ============== Data Fetching ==============

  const fetchSummary = useCallback(async () => {
    try {
      const response = await apiRequest('GET', `/v1/accounting/summary?period=${period}`);
      if (response.ok) {
        const data = await response.json();
        setSummary(data);
      }
    } catch (error) {
      console.error('Failed to fetch summary:', error);
    }
  }, [period]);

  const fetchTransactions = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (transactionType !== 'all') params.append('type', transactionType);
      if (searchQuery) params.append('search', searchQuery);
      if (selectedCategory) params.append('category_id', selectedCategory);
      params.append('limit', String(perPage));
      params.append('page', String(currentPage));

      const response = await apiRequest('GET', `/v1/accounting/transactions?${params.toString()}`);
      if (response.ok) {
        const data = await response.json();
        setTransactions(data.transactions);
        setTotalTransactions(data.total);
        setTotalPages(data.total_pages || 1);
      }
    } catch (error) {
      console.error('Failed to fetch transactions:', error);
    }
  }, [transactionType, searchQuery, selectedCategory, currentPage, perPage]);

  const fetchCategories = useCallback(async () => {
    try {
      const response = await apiRequest('GET', '/v1/accounting/categories');
      if (response.ok) {
        const data = await response.json();
        setCategories(data.categories);
      }
    } catch (error) {
      console.error('Failed to fetch categories:', error);
    }
  }, []);

  const fetchAiInsights = async () => {
    setAiInsights({ loading: true, data: null, error: null });
    setShowInsights(true);
    
    try {
      const session = await supabase.auth.getSession();
      const response = await fetch(
        `${config.apiBaseUrl}/v1/accounting/ai-insights?period=${period}`,
        {
          headers: {
            'Authorization': `Bearer ${session.data.session?.access_token}`
          }
        }
      );
      
      if (response.ok) {
        const data = await response.json();
        setAiInsights({ loading: false, data, error: null });
      } else {
        setAiInsights({ loading: false, data: null, error: 'Failed to generate insights' });
      }
    } catch (error) {
      setAiInsights({ loading: false, data: null, error: 'Failed to connect to AI service' });
    }
  };

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchSummary(), fetchTransactions(), fetchCategories()]);
      setLoading(false);
    };
    loadData();
  }, []);

  // Refresh when period changes
  useEffect(() => {
    fetchSummary();
  }, [period]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [transactionType, searchQuery, selectedCategory]);

  // Refresh transactions when filters or page change
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchTransactions();
    }, 300);
    return () => clearTimeout(timer);
  }, [transactionType, searchQuery, selectedCategory, currentPage, perPage]);

  // ─── Xero: Check connection status on mount ────────────────
  useEffect(() => {
    const checkXeroStatus = async () => {
      try {
        setXeroLoading(true);
        const response = await apiRequest('GET', '/v1/accounting/xero/status');
        if (response.ok) {
          const data = await response.json();
          setXeroStatus(data);
        }
      } catch (error) {
        console.error('Failed to check Xero status:', error);
      } finally {
        setXeroLoading(false);
      }
    };
    checkXeroStatus();
  }, []);

  // ─── Xero: Check for OAuth redirect result on mount ────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const xeroResult = params.get('xero');
    const orgName = params.get('org');
    
    if (xeroResult === 'connected') {
      setSnackbar({
        open: true,
        message: orgName 
          ? `Successfully connected to ${orgName}. Syncing transactions...`
          : 'Successfully connected to Xero. Syncing transactions...',
        severity: 'success',
      });
      // Clean up URL params
      window.history.replaceState({}, '', window.location.pathname);
      // Update status
      setXeroStatus({ connected: true, tenant_name: orgName || 'Xero' });
    } else if (xeroResult === 'error') {
      const reason = params.get('reason') || 'unknown';
      setSnackbar({
        open: true,
        message: `Could not connect to Xero (${reason}). Please try again.`,
        severity: 'error',
      });
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  // ─── Xero: Auto-sync when connected ────────────────────────
  useEffect(() => {
    if (!xeroStatus?.connected || xeroSyncing || xeroLoading) return;

    const autoSync = async () => {
      try {
        setXeroSyncing(true);
        const response = await apiRequest('POST', '/v1/accounting/xero/sync');
        if (response.ok) {
          const result = await response.json();
          setXeroSyncResult(result);
          
          // Update last sync time in status
          setXeroStatus(prev => prev ? {
            ...prev,
            last_sync_at: result.synced_at,
          } : prev);

          // Refresh financial summary after sync
          fetchFinancialSummary();

          // Only show notification and refresh if there are actually new/updated transactions
          if (result.new_transactions > 0 || result.updated_transactions > 0) {
            setSnackbar({
              open: true,
              message: `Xero sync complete: ${result.new_transactions} new, ${result.updated_transactions} updated transactions.`,
              severity: 'success',
            });
            // Refresh the transactions list
            fetchTransactions();
            fetchSummary();
          }
        } else if (response.status === 401) {
          // Token expired — user needs to reconnect
          setXeroStatus({ connected: false });
          setSnackbar({
            open: true,
            message: 'Xero connection expired. Please reconnect your Xero account.',
            severity: 'error',
          });
        }
      } catch (error) {
        console.error('Xero auto-sync failed:', error);
      } finally {
        setXeroSyncing(false);
      }
    };

    autoSync();
  }, [xeroStatus?.connected, xeroLoading]);

  // ─── Fetch financial summary (runs on mount) ────────────────
  const fetchFinancialSummary = useCallback(async () => {
    try {
      setSummaryLoading(true);
      const response = await apiRequest('GET', '/v1/accounting/xero/financial-summary');
      if (response.ok) {
        const data = await response.json();
        setFinancialSummary(data);
      }
    } catch (error) {
      console.error('Failed to fetch financial summary:', error);
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFinancialSummary();
  }, [fetchFinancialSummary]);

  // ============== Handlers ==============

  const handleDeleteTransaction = async (id: string) => {
    if (!confirm('Are you sure you want to delete this transaction?')) return;
    
    try {
      const response = await apiRequest('DELETE', `/v1/accounting/transactions/${id}`);
      if (response.ok) {
        fetchTransactions();
        fetchSummary();
      }
    } catch (error) {
      console.error('Failed to delete transaction:', error);
    }
  };

  const handleImportComplete = () => {
    setUploadDialogOpen(false);
    setCurrentPage(1);
    fetchTransactions();
    fetchSummary();
  };

  // ─── Xero Handlers ─────────────────────────────────────────

  const connectXero = async () => {
    try {
      const response = await apiRequest('GET', '/v1/oauth/xero');
      if (response.ok) {
        const data = await response.json();
        // Redirect user to Xero's OAuth login page
        window.location.href = data.url;
      } else {
        setSnackbar({
          open: true,
          message: 'Failed to start Xero connection. Please try again.',
          severity: 'error',
        });
      }
    } catch (error) {
      console.error('Failed to start Xero OAuth:', error);
      setSnackbar({
        open: true,
        message: 'Failed to connect to Xero. Please try again.',
        severity: 'error',
      });
    }
  };

  const syncXeroNow = async () => {
    if (xeroSyncing) return;
    try {
      setXeroSyncing(true);
      const response = await apiRequest('POST', '/v1/accounting/xero/sync');
      if (response.ok) {
        const result = await response.json();
        setXeroSyncResult(result);
        
        // Update last sync time in status
        setXeroStatus(prev => prev ? {
          ...prev,
          last_sync_at: result.synced_at,
        } : prev);

        // Refresh financial summary after sync
        fetchFinancialSummary();

        setSnackbar({
          open: true,
          message: result.new_transactions > 0 || result.updated_transactions > 0
            ? `Xero sync complete: ${result.new_transactions} new, ${result.updated_transactions} updated transactions.`
            : 'Everything is up to date with Xero.',
          severity: 'success',
        });

        // Refresh transactions list if there were changes
        if (result.new_transactions > 0 || result.updated_transactions > 0) {
          fetchTransactions();
          fetchSummary();
        }
      } else {
        const errorData = await response.json().catch(() => ({}));
        setSnackbar({
          open: true,
          message: errorData.detail || 'Failed to sync with Xero. Please try again.',
          severity: 'error',
        });
      }
    } catch (error) {
      console.error('Xero manual sync failed:', error);
      setSnackbar({
        open: true,
        message: 'Failed to sync with Xero. Please try again.',
        severity: 'error',
      });
    } finally {
      setXeroSyncing(false);
    }
  };

  const disconnectXero = async () => {
    if (!confirm('Disconnect Xero? Previously synced transactions will be preserved.')) return;
    try {
      const response = await apiRequest('POST', '/v1/accounting/xero/disconnect');
      if (response.ok) {
        setXeroStatus({ connected: false });
        setXeroSyncResult(null);
        setSnackbar({
          open: true,
          message: 'Xero disconnected. Your previously synced transactions are preserved.',
          severity: 'info',
        });
      }
    } catch (error) {
      console.error('Failed to disconnect Xero:', error);
    }
  };

  // ─── Export Accountant Pack ─────────────────────────────────
  const handleExportAccountantPack = async () => {
    try {
      setExportLoading(true);
      const params = new URLSearchParams();
      if (exportPeriodStart) params.append('period_start', exportPeriodStart);
      if (exportPeriodEnd) params.append('period_end', exportPeriodEnd);

      const session = await supabase.auth.getSession();
      const response = await fetch(
        `${config.apiBaseUrl}/v1/accounting/export/accountant-pack?${params.toString()}`,
        {
          headers: {
            Authorization: `Bearer ${session.data.session?.access_token}`,
          },
        }
      );

      if (!response.ok) throw new Error('Failed to generate accountant pack');

      const contentDisposition = response.headers.get('Content-Disposition');
      let filename = 'accountant-pack.xlsx';
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="(.+)"/);
        if (match) filename = match[1];
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();

      setShowExportModal(false);
      setSnackbar({ open: true, message: 'Accountant pack downloaded!', severity: 'success' });
    } catch (error) {
      console.error('Export failed:', error);
      setSnackbar({ open: true, message: 'Failed to generate accountant pack. Please try again.', severity: 'error' });
    } finally {
      setExportLoading(false);
    }
  };

  // ─── Helper Functions ──────────────────────────────────────
  const formatCurrency = (amount: number | null, showSign: boolean = false): string => {
    if (amount === null || amount === undefined) return '—';
    const prefix = showSign && amount > 0 ? '+' : '';
    return `${prefix}£${Math.abs(amount).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  // ============== Render ==============

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ bgcolor: 'grey.50', minHeight: '100vh' }}>
      {/* Header */}
      <Box sx={{ bgcolor: 'white', borderBottom: 1, borderColor: 'divider', py: 2, px: 3 }}>
        <Container maxWidth="xl">
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <IconButton onClick={() => navigate('/dashboard')}>
              <ArrowBackIcon />
            </IconButton>
            <Box sx={{ flex: 1 }}>
              <Typography variant="h5" fontWeight={600}>
                Accounting
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Track income, expenses, and financial insights
              </Typography>
            </Box>
            <Button
              variant="outlined"
              startIcon={<FileDownloadIcon />}
              onClick={() => setShowExportModal(true)}
              sx={{ mr: 1 }}
            >
              Export Accountant Pack
            </Button>
            <Button
              variant="outlined"
              startIcon={<UploadIcon />}
              onClick={() => setUploadDialogOpen(true)}
              sx={{ mr: 1 }}
            >
              Import Spreadsheet
            </Button>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setAddTransactionOpen(true)}
            >
              Add Transaction
            </Button>
          </Box>
        </Container>
      </Box>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        {/* Period Filter */}
        <Box sx={{ mb: 3, display: 'flex', gap: 1 }}>
          {(['month', 'quarter', 'year', 'all'] as const).map((p) => (
            <Chip
              key={p}
              label={p === 'month' ? 'This Month' : p === 'quarter' ? 'This Quarter' : p === 'year' ? 'This Year' : 'All Time'}
              onClick={() => setPeriod(p)}
              color={period === p ? 'primary' : 'default'}
              variant={period === p ? 'filled' : 'outlined'}
            />
          ))}
        </Box>

        {/* ─── Xero Connection Banner ─────────────────────────────── */}
        {!xeroLoading && (
          <>
            {xeroStatus?.connected ? (
              // CONNECTED STATE — green status bar
              <Paper
                elevation={0}
                sx={{
                  mb: 3,
                  p: 2,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  bgcolor: 'success.50',
                  border: '1px solid',
                  borderColor: 'success.200',
                  borderRadius: 2,
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '50%',
                      bgcolor: 'success.100',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <CheckCircleOutlineIcon sx={{ color: 'success.main' }} />
                  </Box>
                  <Box>
                    <Typography variant="body1" fontWeight={600} color="success.dark">
                      Connected to {xeroStatus.tenant_name || 'Xero'}
                    </Typography>
                    <Typography variant="body2" color="success.main">
                      {xeroSyncing 
                        ? 'Syncing transactions...' 
                        : xeroStatus.last_sync_at 
                          ? `Last synced: ${new Date(xeroStatus.last_sync_at).toLocaleString()}`
                          : 'Not yet synced'
                      }
                      {xeroSyncResult && !xeroSyncing && xeroSyncResult.new_transactions > 0 && (
                        <Box component="span" sx={{ ml: 1, fontWeight: 600 }}>
                          · {xeroSyncResult.new_transactions} new transactions
                        </Box>
                      )}
                    </Typography>
                  </Box>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={syncXeroNow}
                    disabled={xeroSyncing}
                    startIcon={xeroSyncing ? <CircularProgress size={16} /> : <SyncIcon />}
                    sx={{
                      borderColor: 'success.main',
                      color: 'success.dark',
                      '&:hover': {
                        borderColor: 'success.dark',
                        bgcolor: 'success.50',
                      },
                    }}
                  >
                    {xeroSyncing ? 'Syncing...' : 'Sync Now'}
                  </Button>
                  <Button
                    size="small"
                    onClick={disconnectXero}
                    startIcon={<LinkOffIcon />}
                    sx={{ color: 'text.secondary', '&:hover': { color: 'error.main' } }}
                  >
                    Disconnect
                  </Button>
                </Box>
              </Paper>
            ) : (
              // NOT CONNECTED STATE — blue prompt to connect
              <Paper
                elevation={0}
                sx={{
                  mb: 3,
                  p: 2,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  bgcolor: 'primary.50',
                  border: '1px solid',
                  borderColor: 'primary.200',
                  borderRadius: 2,
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '50%',
                      bgcolor: 'primary.100',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <LinkIcon sx={{ color: 'primary.main' }} />
                  </Box>
                  <Box>
                    <Typography variant="body1" fontWeight={600} color="primary.dark">
                      Connect your accounting software
                    </Typography>
                    <Typography variant="body2" color="primary.main">
                      Link Xero to automatically sync your bank transactions — no more manual uploads
                    </Typography>
                  </Box>
                </Box>
                <Button
                  variant="contained"
                  onClick={connectXero}
                  startIcon={<LinkIcon />}
                  sx={{
                    bgcolor: 'primary.main',
                    '&:hover': { bgcolor: 'primary.dark' },
                  }}
                >
                  Connect Xero
                </Button>
              </Paper>
            )}
          </>
        )}

        {/* ─── Financial Summary Header (from Xero + Invoices) ─── */}
        {financialSummary && (xeroStatus?.connected || financialSummary.invoices.total_outstanding > 0) && (
          <Grid container spacing={2} sx={{ mb: 3 }}>
            {/* Bank Balance Card */}
            <Grid item xs={12} sm={6} lg={3}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary" fontWeight={500}>
                      Bank Balance
                    </Typography>
                    <AccountBalanceIcon sx={{ color: 'primary.main', fontSize: 20 }} />
                  </Box>
                  {summaryLoading ? (
                    <Box sx={{ height: 32, width: 100, bgcolor: 'grey.200', borderRadius: 1, animation: 'pulse 1.5s infinite' }} />
                  ) : financialSummary.total_bank_balance !== null ? (
                    <>
                      <Typography 
                        variant="h5" 
                        fontWeight={700}
                        color={financialSummary.total_bank_balance >= 0 ? 'text.primary' : 'error.main'}
                      >
                        {formatCurrency(financialSummary.total_bank_balance)}
                      </Typography>
                      {financialSummary.bank_accounts.length > 1 && (
                        <Typography variant="caption" color="text.secondary">
                          {financialSummary.bank_accounts.length} accounts
                        </Typography>
                      )}
                      {financialSummary.bank_accounts.length === 1 && (
                        <Typography variant="caption" color="text.secondary">
                          {financialSummary.bank_accounts[0].name}
                        </Typography>
                      )}
                    </>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      Connect Xero to see balance
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>

            {/* Monthly P&L Card */}
            <Grid item xs={12} sm={6} lg={3}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary" fontWeight={500}>
                      Monthly P&L
                    </Typography>
                    <TrendingUpIcon sx={{ color: 'success.main', fontSize: 20 }} />
                  </Box>
                  {summaryLoading ? (
                    <Box sx={{ height: 32, width: 100, bgcolor: 'grey.200', borderRadius: 1, animation: 'pulse 1.5s infinite' }} />
                  ) : financialSummary.profit_and_loss.net_profit !== null ? (
                    <>
                      <Typography 
                        variant="h5" 
                        fontWeight={700}
                        color={financialSummary.profit_and_loss.net_profit >= 0 ? 'success.main' : 'error.main'}
                      >
                        {formatCurrency(financialSummary.profit_and_loss.net_profit, true)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatCurrency(financialSummary.profit_and_loss.income)} in · {formatCurrency(financialSummary.profit_and_loss.expenses)} out
                      </Typography>
                    </>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      Connect Xero to see P&L
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>

            {/* Cash Flow Card */}
            <Grid item xs={12} sm={6} lg={3}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary" fontWeight={500}>
                      Cash Flow
                    </Typography>
                    <RefreshIcon sx={{ color: 'secondary.main', fontSize: 20 }} />
                  </Box>
                  {summaryLoading ? (
                    <Box sx={{ height: 48, width: '100%', bgcolor: 'grey.200', borderRadius: 1, animation: 'pulse 1.5s infinite' }} />
                  ) : financialSummary.profit_and_loss.income !== null ? (
                    <Box sx={{ mt: 1 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="body2" color="success.main">Money in</Typography>
                        <Typography variant="body2" fontWeight={600} color="success.main">
                          {formatCurrency(financialSummary.profit_and_loss.income)}
                        </Typography>
                      </Box>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Typography variant="body2" color="error.main">Money out</Typography>
                        <Typography variant="body2" fontWeight={600} color="error.main">
                          {formatCurrency(financialSummary.profit_and_loss.expenses)}
                        </Typography>
                      </Box>
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                        This month
                      </Typography>
                    </Box>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      Connect Xero to see cash flow
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>

            {/* Outstanding Invoices Card — clickable, navigates to Invoices tab */}
            <Grid item xs={12} sm={6} lg={3}>
              <Card
                sx={{
                  height: '100%',
                  cursor: 'pointer',
                  transition: 'box-shadow 0.2s, border-color 0.2s',
                  '&:hover': { boxShadow: 4, borderColor: 'primary.light' },
                }}
                onClick={() => navigate('/app?tab=invoices')}
              >
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary" fontWeight={500}>
                      Invoices Due
                    </Typography>
                    <ReceiptIcon sx={{ color: 'warning.main', fontSize: 20 }} />
                  </Box>
                  {summaryLoading ? (
                    <Box sx={{ height: 32, width: 100, bgcolor: 'grey.200', borderRadius: 1, animation: 'pulse 1.5s infinite' }} />
                  ) : (
                    <>
                      <Typography variant="h5" fontWeight={700} color="text.primary">
                        {formatCurrency(financialSummary.invoices.total_outstanding)}
                      </Typography>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
                        {financialSummary.invoices.overdue_count > 0 && (
                          <Chip 
                            label={`${financialSummary.invoices.overdue_count} overdue`} 
                            size="small" 
                            color="error" 
                            variant="outlined"
                            sx={{ height: 20, fontSize: '0.7rem' }}
                          />
                        )}
                        {financialSummary.invoices.due_count > 0 && (
                          <Chip 
                            label={`${financialSummary.invoices.due_count} due`} 
                            size="small" 
                            color="warning" 
                            variant="outlined"
                            sx={{ height: 20, fontSize: '0.7rem' }}
                          />
                        )}
                        {financialSummary.invoices.total_outstanding === 0 && (
                          <Typography variant="caption" color="success.main">All paid up!</Typography>
                        )}
                      </Box>
                      <Typography variant="caption" color="primary.main" sx={{ mt: 1, display: 'block' }}>
                        View invoices →
                      </Typography>
                    </>
                  )}
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        )}

        {/* Summary Cards */}
        <Grid container spacing={3} sx={{ mb: 3 }}>
          <Grid item xs={12} md={4}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <TrendingUpIcon color="success" />
                  <Typography variant="subtitle2" color="text.secondary">
                    Total Income
                  </Typography>
                </Box>
                <Typography variant="h4" color="success.main" fontWeight={600}>
                  £{summary?.totals.income.toLocaleString('en-GB', { minimumFractionDigits: 2 }) || '0.00'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <TrendingDownIcon color="error" />
                  <Typography variant="subtitle2" color="text.secondary">
                    Total Expenses
                  </Typography>
                </Box>
                <Typography variant="h4" color="error.main" fontWeight={600}>
                  £{summary?.totals.expense.toLocaleString('en-GB', { minimumFractionDigits: 2 }) || '0.00'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <AccountBalanceIcon color="primary" />
                  <Typography variant="subtitle2" color="text.secondary">
                    Net Profit/Loss
                  </Typography>
                </Box>
                <Typography 
                  variant="h4" 
                  fontWeight={600}
                  color={(summary?.totals.net || 0) >= 0 ? 'success.main' : 'error.main'}
                >
                  {(summary?.totals.net || 0) >= 0 ? '+' : ''}
                  £{summary?.totals.net?.toLocaleString('en-GB', { minimumFractionDigits: 2 }) || '0.00'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* Tabs */}
        <Tabs value={activeTab} onChange={(_, v) => setActiveTab(v)} sx={{ mb: 3 }}>
          <Tab label="Overview" />
          <Tab label={`Transactions (${totalTransactions})`} />
          <Tab label="Categories" />
        </Tabs>

        {/* Tab Content */}
        {activeTab === 0 && (
          <>
            {/* AI Insights Button */}
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
              <Button
                variant="contained"
                onClick={fetchAiInsights}
                disabled={aiInsights.loading}
                startIcon={
                  aiInsights.loading ? (
                    <CircularProgress size={20} color="inherit" />
                  ) : (
                    <Box
                      component="img"
                      src="/aria-avatar.png"
                      sx={{ width: 24, height: 24, borderRadius: '50%' }}
                    />
                  )
                }
                sx={{
                  background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                  textTransform: 'none',
                  px: 3,
                  py: 1,
                  '&:hover': {
                    background: 'linear-gradient(135deg, #5558e3 0%, #7c4fe0 100%)',
                  }
                }}
              >
                {aiInsights.loading ? 'Analyzing...' : 'Get AI Insights from Aria'}
              </Button>
            </Box>

            {/* AI Insights Panel */}
            {showInsights && (
              <Paper 
                elevation={0} 
                sx={{ 
                  p: 3, 
                  mb: 3, 
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 2,
                  background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.05) 100%)'
                }}
              >
                {aiInsights.loading && (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <CircularProgress size={24} />
                    <Typography>Aria is analyzing your finances...</Typography>
                  </Box>
                )}
                
                {aiInsights.error && (
                  <Alert severity="error" onClose={() => setShowInsights(false)}>
                    {aiInsights.error}
                  </Alert>
                )}
                
                {aiInsights.data && (
                  <Box>
                    {/* Header with Aria */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                      <Box
                        component="img"
                        src="/aria-avatar.png"
                        sx={{ width: 48, height: 48, borderRadius: '50%', border: '2px solid #6366f1' }}
                      />
                      <Box>
                        <Typography variant="h6" fontWeight={600}>Aria's Financial Insights</Typography>
                        <Typography variant="body2" color="text.secondary">
                          Analysis for {summary?.period?.label || period}
                        </Typography>
                      </Box>
                      <IconButton 
                        onClick={() => setShowInsights(false)} 
                        sx={{ ml: 'auto' }}
                        size="small"
                      >
                        <CloseIcon />
                      </IconButton>
                    </Box>
                    
                    {/* Summary Paragraph with Personality */}
                    <Paper sx={{ p: 2, mb: 3, bgcolor: 'background.default' }}>
                      <Typography variant="body1" sx={{ lineHeight: 1.8 }}>
                        {aiInsights.data.summary}
                      </Typography>
                    </Paper>
                    
                    {/* Structured Sections */}
                    <Grid container spacing={2}>
                      {/* Financial Overview */}
                      <Grid item xs={12} md={6}>
                        <Paper sx={{ p: 2, height: '100%' }}>
                          <Typography variant="subtitle1" fontWeight={600} gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            📊 Financial Overview
                          </Typography>
                          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            {aiInsights.data.overview?.map((item: string, i: number) => (
                              <Typography key={i} variant="body2">• {item}</Typography>
                            ))}
                          </Box>
                        </Paper>
                      </Grid>
                      
                      {/* Spending Analysis */}
                      <Grid item xs={12} md={6}>
                        <Paper sx={{ p: 2, height: '100%' }}>
                          <Typography variant="subtitle1" fontWeight={600} gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            💸 Spending Analysis
                          </Typography>
                          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            {aiInsights.data.spending?.map((item: string, i: number) => (
                              <Typography key={i} variant="body2">• {item}</Typography>
                            ))}
                          </Box>
                        </Paper>
                      </Grid>
                      
                      {/* Suggestions */}
                      <Grid item xs={12} md={6}>
                        <Paper sx={{ p: 2, height: '100%', borderLeft: '3px solid #10B981' }}>
                          <Typography variant="subtitle1" fontWeight={600} gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            💡 Suggestions
                          </Typography>
                          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            {aiInsights.data.suggestions?.map((item: string, i: number) => (
                              <Typography key={i} variant="body2">• {item}</Typography>
                            ))}
                          </Box>
                        </Paper>
                      </Grid>
                      
                      {/* Data Quality */}
                      <Grid item xs={12} md={6}>
                        <Paper sx={{ p: 2, height: '100%', borderLeft: '3px solid #F59E0B' }}>
                          <Typography variant="subtitle1" fontWeight={600} gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            ⚠️ Data Quality
                          </Typography>
                          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            {aiInsights.data.dataQuality?.map((item: string, i: number) => (
                              <Typography key={i} variant="body2">• {item}</Typography>
                            ))}
                          </Box>
                        </Paper>
                      </Grid>
                    </Grid>
                  </Box>
                )}
              </Paper>
            )}

            <OverviewTab summary={summary} />
          </>
        )}
        
        {activeTab === 1 && (
          <TransactionsTab
            transactions={transactions}
            categories={categories}
            transactionType={transactionType}
            setTransactionType={setTransactionType}
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            selectedCategory={selectedCategory}
            setSelectedCategory={setSelectedCategory}
            onDelete={handleDeleteTransaction}
            onRefresh={fetchTransactions}
            currentPage={currentPage}
            totalPages={totalPages}
            totalTransactions={totalTransactions}
            perPage={perPage}
            setCurrentPage={setCurrentPage}
            setPerPage={setPerPage}
          />
        )}
        
        {activeTab === 2 && (
          <CategoriesTab
            categories={categories}
            onRefresh={fetchCategories}
          />
        )}
      </Container>

      {/* Upload Dialog */}
      <UploadDialog
        open={uploadDialogOpen}
        onClose={() => setUploadDialogOpen(false)}
        onComplete={handleImportComplete}
      />

      {/* Add Transaction Dialog */}
      <AddTransactionDialog
        open={addTransactionOpen}
        onClose={() => setAddTransactionOpen(false)}
        categories={categories}
        onSuccess={() => {
          setAddTransactionOpen(false);
          fetchTransactions();
          fetchSummary();
        }}
      />

      {/* Export Accountant Pack Dialog */}
      <Dialog
        open={showExportModal}
        onClose={() => setShowExportModal(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Export Accountant Pack</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Generate a comprehensive Excel workbook with transactions, P&L, Balance Sheet, and more. Ready to send to your accountant.
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
            <TextField
              label="Period Start"
              type="date"
              value={exportPeriodStart}
              onChange={(e) => setExportPeriodStart(e.target.value)}
              InputLabelProps={{ shrink: true }}
              helperText="Defaults to 6 April (UK tax year start)"
              fullWidth
            />
            <TextField
              label="Period End"
              type="date"
              value={exportPeriodEnd}
              onChange={(e) => setExportPeriodEnd(e.target.value)}
              InputLabelProps={{ shrink: true }}
              helperText="Defaults to today's date"
              fullWidth
            />
          </Box>
          {xeroStatus?.connected ? (
            <Paper
              elevation={0}
              sx={{
                mt: 2, p: 1.5, display: 'flex', alignItems: 'center', gap: 1.5,
                bgcolor: 'success.50', border: '1px solid', borderColor: 'success.200', borderRadius: 1,
              }}
            >
              <CheckCircleOutlineIcon sx={{ color: 'success.main', fontSize: 20 }} />
              <Typography variant="body2" color="success.dark">
                Xero connected — includes P&L, Balance Sheet, Trial Balance, Aged Reports
              </Typography>
            </Paper>
          ) : (
            <Paper
              elevation={0}
              sx={{
                mt: 2, p: 1.5, display: 'flex', alignItems: 'center', gap: 1.5,
                bgcolor: 'warning.50', border: '1px solid', borderColor: 'warning.200', borderRadius: 1,
              }}
            >
              <LinkIcon sx={{ color: 'warning.main', fontSize: 20 }} />
              <Typography variant="body2" color="warning.dark">
                Connect Xero for full reports (P&L, Balance Sheet, etc.)
              </Typography>
            </Paper>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setShowExportModal(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleExportAccountantPack}
            disabled={exportLoading}
            startIcon={exportLoading ? <CircularProgress size={16} /> : <FileDownloadIcon />}
          >
            {exportLoading ? 'Generating...' : 'Download Accountant Pack'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar for notifications */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

// ============== Overview Tab ==============

const OverviewTab: React.FC<{ summary: Summary | null }> = ({ summary }) => {
  if (!summary) return null;

  const COLORS = ['#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#6366F1', '#14B8A6'];

  return (
    <Grid container spacing={3}>
      {/* Row 1: Bar Chart + Line Chart (side by side) */}
      
      {/* Income vs Expenses Trend Bar Chart */}
      <Grid item xs={12} md={6}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Income vs Expenses Trend
          </Typography>
          {summary.trend.length > 0 ? (
            <Box sx={{ height: 400 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={summary.trend} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
                  <XAxis 
                    dataKey="month" 
                    tick={{ fontSize: 12 }}
                    axisLine={{ stroke: '#e0e0e0' }}
                    tickFormatter={(value) => {
                      const [year, month] = value.split('-');
                      return new Date(parseInt(year), parseInt(month) - 1).toLocaleDateString('en-GB', { month: 'short' });
                    }}
                  />
                  <YAxis 
                    tick={{ fontSize: 12 }}
                    axisLine={{ stroke: '#e0e0e0' }}
                    tickFormatter={(value) => `£${value.toLocaleString()}`}
                  />
                  <RechartsTooltip 
                    formatter={(value: number) => `£${value.toLocaleString()}`}
                    contentStyle={{ borderRadius: 8 }}
                  />
                  <Legend />
                  <Bar dataKey="income" name="Income" fill="#10B981" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expense" name="Expenses" fill="#EF4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Box>
          ) : (
            <Box sx={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography color="text.secondary">No trend data available</Typography>
            </Box>
          )}
        </Paper>
      </Grid>

      {/* Net Profit/Loss Trend Line Chart */}
      <Grid item xs={12} md={6}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Net Profit/Loss Trend
          </Typography>
          {summary.trend.length > 0 ? (
            <Box sx={{ height: 400 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={summary.trend.map(item => ({
                    ...item,
                    net: item.income - item.expense
                  }))}
                  margin={{ top: 10, right: 30, left: 10, bottom: 10 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
                  <XAxis 
                    dataKey="month" 
                    tick={{ fontSize: 12 }}
                    axisLine={{ stroke: '#e0e0e0' }}
                    tickFormatter={(value) => {
                      const [year, month] = value.split('-');
                      return new Date(parseInt(year), parseInt(month) - 1).toLocaleDateString('en-GB', { month: 'short' });
                    }}
                  />
                  <YAxis 
                    tick={{ fontSize: 12 }}
                    axisLine={{ stroke: '#e0e0e0' }}
                    tickFormatter={(value) => `£${value.toLocaleString()}`}
                  />
                  <RechartsTooltip 
                    formatter={(value: number) => [`£${value.toLocaleString()}`, 'Net']}
                    contentStyle={{ borderRadius: 8 }}
                  />
                  <ReferenceLine y={0} stroke="#666" strokeDasharray="3 3" />
                  <Line 
                    type="monotone" 
                    dataKey="net" 
                    stroke="#6366f1" 
                    strokeWidth={3}
                    dot={{ fill: '#6366f1', strokeWidth: 2, r: 5 }}
                    activeDot={{ r: 8, fill: '#8b5cf6' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Box>
          ) : (
            <Box sx={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography color="text.secondary">No trend data available</Typography>
            </Box>
          )}
        </Paper>
      </Grid>

      {/* Row 2: Pie Charts with side legends */}
      
      {/* Income by Category */}
      <Grid item xs={12} md={6}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Income by Category
          </Typography>
          {summary.categories.income.length > 0 ? (
            <Box sx={{ height: 400, display: 'flex', alignItems: 'center' }}>
              <ResponsiveContainer width="60%" height="100%">
                <PieChart>
                  <Pie
                    data={summary.categories.income}
                    dataKey="total"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={90}
                    paddingAngle={2}
                    label={false}
                  >
                    {summary.categories.income.map((entry, index) => (
                      <Cell key={entry.name} fill={entry.color || COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <RechartsTooltip 
                    formatter={(value: number) => `£${value.toLocaleString()}`}
                    contentStyle={{ borderRadius: 8 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <Box sx={{ width: '40%', maxHeight: 380, overflowY: 'auto', pl: 2 }}>
                {summary.categories.income.slice(0, 10).map((entry, index) => (
                  <Box key={entry.name} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Box sx={{ 
                      width: 12, 
                      height: 12, 
                      borderRadius: '50%', 
                      bgcolor: entry.color || COLORS[index % COLORS.length],
                      flexShrink: 0
                    }} />
                    <Typography variant="body2" noWrap sx={{ flex: 1 }}>
                      {entry.name}
                    </Typography>
                    <Typography variant="body2" fontWeight={600} color="success.main" sx={{ flexShrink: 0 }}>
                      £{entry.total.toLocaleString()}
                    </Typography>
                  </Box>
                ))}
              </Box>
            </Box>
          ) : (
            <Box sx={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography color="text.secondary">No income data</Typography>
            </Box>
          )}
        </Paper>
      </Grid>

      {/* Expenses by Category */}
      <Grid item xs={12} md={6}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Expenses by Category
          </Typography>
          {summary.categories.expense.length > 0 ? (
            <Box sx={{ height: 400, display: 'flex', alignItems: 'center' }}>
              <ResponsiveContainer width="60%" height="100%">
                <PieChart>
                  <Pie
                    data={summary.categories.expense}
                    dataKey="total"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={90}
                    paddingAngle={2}
                    label={false}
                  >
                    {summary.categories.expense.map((entry, index) => (
                      <Cell key={entry.name} fill={entry.color || COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <RechartsTooltip 
                    formatter={(value: number) => `£${value.toLocaleString()}`}
                    contentStyle={{ borderRadius: 8 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <Box sx={{ width: '40%', maxHeight: 380, overflowY: 'auto', pl: 2 }}>
                {summary.categories.expense.slice(0, 10).map((entry, index) => (
                  <Box key={entry.name} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Box sx={{ 
                      width: 12, 
                      height: 12, 
                      borderRadius: '50%', 
                      bgcolor: entry.color || COLORS[index % COLORS.length],
                      flexShrink: 0
                    }} />
                    <Typography variant="body2" noWrap sx={{ flex: 1 }}>
                      {entry.name}
                    </Typography>
                    <Typography variant="body2" fontWeight={600} color="error.main" sx={{ flexShrink: 0 }}>
                      £{entry.total.toLocaleString()}
                    </Typography>
                  </Box>
                ))}
              </Box>
            </Box>
          ) : (
            <Box sx={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography color="text.secondary">No expense data</Typography>
            </Box>
          )}
        </Paper>
      </Grid>
    </Grid>
  );
};

// ============== Transactions Tab ==============

interface TransactionsTabProps {
  transactions: Transaction[];
  categories: Category[];
  transactionType: 'all' | 'income' | 'expense';
  setTransactionType: (type: 'all' | 'income' | 'expense') => void;
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  selectedCategory: string;
  setSelectedCategory: (id: string) => void;
  onDelete: (id: string) => void;
  onRefresh: () => void;
  currentPage: number;
  totalPages: number;
  totalTransactions: number;
  perPage: number;
  setCurrentPage: (page: number | ((p: number) => number)) => void;
  setPerPage: (size: number) => void;
}

const TransactionsTab: React.FC<TransactionsTabProps> = ({
  transactions,
  categories,
  transactionType,
  setTransactionType,
  searchQuery,
  setSearchQuery,
  selectedCategory,
  setSelectedCategory,
  onDelete,
  onRefresh,
  currentPage,
  totalPages,
  totalTransactions,
  perPage,
  setCurrentPage,
  setPerPage,
}) => {
  const [selectedTransactions, setSelectedTransactions] = useState<string[]>([]);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTransaction, setEditingTransaction] = useState<Transaction & { category_id?: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSaveTransaction = async () => {
    if (!editingTransaction) return;
    
    setSaving(true);
    try {
      const session = await supabase.auth.getSession();
      const response = await fetch(
        `${config.apiBaseUrl}/v1/accounting/transactions/${editingTransaction.id}`,
        {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${session.data.session?.access_token}`
          },
          body: JSON.stringify({
            category_id: editingTransaction.category_id || null,
            description: editingTransaction.description || '',
            payee_payer: editingTransaction.payee_payer || ''
          })
        }
      );
      
      if (response.ok) {
        setEditModalOpen(false);
        setEditingTransaction(null);
        onRefresh();
      } else {
        const error = await response.json();
        alert(`Failed to update: ${error.detail || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Update transaction error:', error);
      alert('Failed to update transaction. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleBulkDelete = async () => {
    if (!window.confirm(`Are you sure you want to delete ${selectedTransactions.length} transaction${selectedTransactions.length > 1 ? 's' : ''}? This cannot be undone.`)) {
      return;
    }
    
    try {
      const session = await supabase.auth.getSession();
      const response = await fetch(`${config.apiBaseUrl}/v1/accounting/transactions/bulk-delete`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session.data.session?.access_token}`
        },
        body: JSON.stringify({ transaction_ids: selectedTransactions })
      });
      
      if (response.ok) {
        const data = await response.json();
        alert(`Successfully deleted ${data.deleted_count} transactions`);
        setSelectedTransactions([]);
        onRefresh();
      } else {
        const error = await response.json();
        alert(`Failed to delete: ${error.detail || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Bulk delete error:', error);
      alert('Failed to delete transactions. Please try again.');
    }
  };

  return (
    <Box>
      {/* Filters */}
      <Card sx={{ mb: 3, p: 2 }}>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
          <TextField
            placeholder="Search transactions..."
            size="small"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            sx={{ minWidth: 250 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon color="action" />
                </InputAdornment>
              ),
              endAdornment: searchQuery && (
                <InputAdornment position="end">
                  <IconButton size="small" onClick={() => setSearchQuery('')}>
                    <ClearIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ),
            }}
          />

          <Box sx={{ display: 'flex', gap: 1 }}>
            {(['all', 'income', 'expense'] as const).map((type) => (
              <Chip
                key={type}
                label={type.charAt(0).toUpperCase() + type.slice(1)}
                onClick={() => setTransactionType(type)}
                color={transactionType === type ? (type === 'income' ? 'success' : type === 'expense' ? 'error' : 'primary') : 'default'}
                variant={transactionType === type ? 'filled' : 'outlined'}
              />
            ))}
          </Box>

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Category</InputLabel>
            <Select
              value={selectedCategory}
              label="Category"
              onChange={(e) => setSelectedCategory(e.target.value)}
            >
              <MenuItem value="">All Categories</MenuItem>
              {categories.map((cat) => (
                <MenuItem key={cat.id} value={cat.id}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: cat.color }} />
                    {cat.name}
                  </Box>
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Box sx={{ ml: 'auto' }}>
            <IconButton onClick={onRefresh}>
              <RefreshIcon />
            </IconButton>
          </Box>
        </Box>
      </Card>

      {/* Bulk Actions Toolbar */}
      {selectedTransactions.length > 0 && (
        <Box sx={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: 2, 
          p: 2, 
          bgcolor: 'action.selected',
          borderRadius: 1,
          mb: 2
        }}>
          <Typography variant="body2" fontWeight={600}>
            {selectedTransactions.length} transaction{selectedTransactions.length > 1 ? 's' : ''} selected
          </Typography>
          
          <Button
            size="small"
            color="error"
            variant="outlined"
            startIcon={<DeleteIcon />}
            onClick={handleBulkDelete}
          >
            Delete Selected
          </Button>
          
          <Button
            size="small"
            variant="text"
            onClick={() => setSelectedTransactions([])}
          >
            Clear Selection
          </Button>
        </Box>
      )}

      {/* Transactions Table */}
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  indeterminate={selectedTransactions.length > 0 && selectedTransactions.length < transactions.length}
                  checked={transactions.length > 0 && selectedTransactions.length === transactions.length}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedTransactions(transactions.map(t => t.id));
                    } else {
                      setSelectedTransactions([]);
                    }
                  }}
                />
              </TableCell>
              <TableCell>Date</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>Category</TableCell>
              <TableCell>Payee/Payer</TableCell>
              <TableCell align="right">Amount</TableCell>
              <TableCell align="center">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">
                    {searchQuery || selectedCategory ? 'No transactions match your filters' : 'No transactions yet'}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              transactions.map((transaction) => (
                <TableRow
                  key={transaction.id}
                  hover
                  selected={selectedTransactions.includes(transaction.id)}
                  sx={{ cursor: 'pointer' }}
                  onClick={() => {
                    setEditingTransaction({
                      ...transaction,
                      category_id: transaction.category?.id || ''
                    });
                    setEditModalOpen(true);
                  }}
                >
                  <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selectedTransactions.includes(transaction.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedTransactions(prev => [...prev, transaction.id]);
                        } else {
                          setSelectedTransactions(prev => prev.filter(id => id !== transaction.id));
                        }
                      }}
                    />
                  </TableCell>
                  <TableCell>
                    {new Date(transaction.transaction_date).toLocaleDateString('en-GB', {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric'
                    })}
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>
                      {transaction.description}
                    </Typography>
                    {transaction.reference && (
                      <Typography variant="caption" color="text.secondary">
                        Ref: {transaction.reference}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    {transaction.category ? (
                      <Chip
                        size="small"
                        label={transaction.category.name}
                        sx={{
                          bgcolor: `${transaction.category.color}20`,
                          color: transaction.category.color,
                          fontWeight: 500
                        }}
                      />
                    ) : (
                      <Typography variant="caption" color="text.secondary">
                        Uncategorized
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    {transaction.payee_payer || '—'}
                  </TableCell>
                  <TableCell align="right">
                    <Typography
                      fontWeight={600}
                      color={transaction.type === 'income' ? 'success.main' : 'error.main'}
                    >
                      {transaction.type === 'income' ? '+' : '-'}
                      £{Math.abs(transaction.amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                    </Typography>
                  </TableCell>
                  <TableCell align="center" onClick={(e) => e.stopPropagation()}>
                    <IconButton size="small" onClick={() => onDelete(transaction.id)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* ─── Pagination Controls ──────────────────────────── */}
      {totalPages > 0 && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            mt: 2,
            pt: 2,
            borderTop: 1,
            borderColor: 'divider',
            flexWrap: 'wrap',
            gap: 1,
          }}
        >
          <Typography variant="body2" color="text.secondary">
            Showing {Math.min((currentPage - 1) * perPage + 1, totalTransactions)}–{Math.min(currentPage * perPage, totalTransactions)} of {totalTransactions.toLocaleString()} transactions
          </Typography>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Button size="small" disabled={currentPage === 1} onClick={() => setCurrentPage(1)} sx={{ minWidth: 36 }}>
              ««
            </Button>
            <Button size="small" disabled={currentPage === 1} onClick={() => setCurrentPage((p: number) => Math.max(1, p - 1))} sx={{ minWidth: 36 }}>
              «
            </Button>
            {(() => {
              const pages: number[] = [];
              let start = Math.max(1, currentPage - 2);
              const end = Math.min(totalPages, start + 4);
              if (end - start < 4) start = Math.max(1, end - 4);
              for (let i = start; i <= end; i++) pages.push(i);
              return pages.map((p) => (
                <Button
                  key={p}
                  size="small"
                  variant={p === currentPage ? 'contained' : 'text'}
                  onClick={() => setCurrentPage(p)}
                  sx={{ minWidth: 36 }}
                >
                  {p}
                </Button>
              ));
            })()}
            <Button size="small" disabled={currentPage === totalPages} onClick={() => setCurrentPage((p: number) => Math.min(totalPages, p + 1))} sx={{ minWidth: 36 }}>
              »
            </Button>
            <Button size="small" disabled={currentPage === totalPages} onClick={() => setCurrentPage(totalPages)} sx={{ minWidth: 36 }}>
              »»
            </Button>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body2" color="text.secondary">Per page:</Typography>
            <Select
              size="small"
              value={perPage}
              onChange={(e) => {
                setPerPage(Number(e.target.value));
                setCurrentPage(1);
              }}
              sx={{ minWidth: 70, height: 32 }}
            >
              <MenuItem value={25}>25</MenuItem>
              <MenuItem value={50}>50</MenuItem>
              <MenuItem value={100}>100</MenuItem>
              <MenuItem value={200}>200</MenuItem>
            </Select>
          </Box>
        </Box>
      )}

      {/* Edit Transaction Modal */}
      <Dialog 
        open={editModalOpen} 
        onClose={() => {
          setEditModalOpen(false);
          setEditingTransaction(null);
        }} 
        maxWidth="sm" 
        fullWidth
      >
        <DialogTitle>Edit Transaction</DialogTitle>
        <DialogContent>
          {editingTransaction && (
            <Box sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 3 }}>
              {/* Show transaction date and amount as read-only info */}
              <Box sx={{ display: 'flex', gap: 2, color: 'text.secondary' }}>
                <Typography variant="body2">
                  Date: {new Date(editingTransaction.transaction_date).toLocaleDateString()}
                </Typography>
                <Typography variant="body2">
                  Amount: £{Math.abs(editingTransaction.amount).toFixed(2)}
                </Typography>
                <Typography variant="body2">
                  Type: {editingTransaction.type}
                </Typography>
              </Box>
              
              <TextField
                label="Description"
                fullWidth
                multiline
                rows={2}
                value={editingTransaction.description || ''}
                onChange={(e) => setEditingTransaction({
                  ...editingTransaction,
                  description: e.target.value
                })}
              />
              
              <FormControl fullWidth>
                <InputLabel>Category</InputLabel>
                <Select
                  value={editingTransaction.category_id || ''}
                  label="Category"
                  onChange={(e) => setEditingTransaction({
                    ...editingTransaction,
                    category_id: e.target.value
                  })}
                >
                  <MenuItem value="">
                    <em>Uncategorized</em>
                  </MenuItem>
                  {categories.map((cat) => (
                    <MenuItem key={cat.id} value={cat.id}>{cat.name}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              
              <TextField
                label="Payee / Payer"
                fullWidth
                value={editingTransaction.payee_payer || ''}
                onChange={(e) => setEditingTransaction({
                  ...editingTransaction,
                  payee_payer: e.target.value
                })}
                helperText="Who paid you or who you paid"
              />
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button 
            onClick={() => {
              setEditModalOpen(false);
              setEditingTransaction(null);
            }}
          >
            Cancel
          </Button>
          <Button 
            variant="contained" 
            onClick={handleSaveTransaction}
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

// ============== Categories Tab ==============

const CategoriesTab: React.FC<{ categories: Category[]; onRefresh: () => void }> = ({
  categories,
  onRefresh,
}) => {
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [newCategory, setNewCategory] = useState({ name: '', type: 'expense' as const, color: '#6B7280' });
  const [saving, setSaving] = useState(false);

  const incomeCategories = categories.filter((c) => c.type === 'income');
  const expenseCategories = categories.filter((c) => c.type === 'expense');

  const handleAddCategory = async () => {
    if (!newCategory.name.trim()) return;
    
    setSaving(true);
    try {
      const response = await apiRequest('POST', '/v1/accounting/categories', newCategory);
      if (response.ok) {
        setAddDialogOpen(false);
        setNewCategory({ name: '', type: 'expense', color: '#6B7280' });
        onRefresh();
      }
    } catch (error) {
      console.error('Failed to create category:', error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'flex-end' }}>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setAddDialogOpen(true)}
        >
          Add Category
        </Button>
      </Box>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <TrendingUpIcon color="success" />
                <Typography variant="h6">Income Categories</Typography>
              </Box>
              {incomeCategories.map((cat) => (
                <Box
                  key={cat.id}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    py: 1.5,
                    borderBottom: 1,
                    borderColor: 'divider',
                    '&:last-child': { borderBottom: 0 }
                  }}
                >
                  <Box sx={{ width: 16, height: 16, borderRadius: '4px', bgcolor: cat.color, mr: 2 }} />
                  <Typography sx={{ flex: 1 }}>{cat.name}</Typography>
                  {cat.is_default && (
                    <Chip label="Default" size="small" variant="outlined" />
                  )}
                </Box>
              ))}
              {incomeCategories.length === 0 && (
                <Typography color="text.secondary">No income categories</Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <TrendingDownIcon color="error" />
                <Typography variant="h6">Expense Categories</Typography>
              </Box>
              {expenseCategories.map((cat) => (
                <Box
                  key={cat.id}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    py: 1.5,
                    borderBottom: 1,
                    borderColor: 'divider',
                    '&:last-child': { borderBottom: 0 }
                  }}
                >
                  <Box sx={{ width: 16, height: 16, borderRadius: '4px', bgcolor: cat.color, mr: 2 }} />
                  <Typography sx={{ flex: 1 }}>{cat.name}</Typography>
                  {cat.is_default && (
                    <Chip label="Default" size="small" variant="outlined" />
                  )}
                </Box>
              ))}
              {expenseCategories.length === 0 && (
                <Typography color="text.secondary">No expense categories</Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Add Category Dialog */}
      <Dialog open={addDialogOpen} onClose={() => setAddDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Add Category</DialogTitle>
        <DialogContent>
          <Box sx={{ pt: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Category Name"
              fullWidth
              value={newCategory.name}
              onChange={(e) => setNewCategory({ ...newCategory, name: e.target.value })}
            />
            <FormControl fullWidth>
              <InputLabel>Type</InputLabel>
              <Select
                value={newCategory.type}
                label="Type"
                onChange={(e) => setNewCategory({ ...newCategory, type: e.target.value as 'income' | 'expense' })}
              >
                <MenuItem value="income">Income</MenuItem>
                <MenuItem value="expense">Expense</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label="Color"
              type="color"
              fullWidth
              value={newCategory.color}
              onChange={(e) => setNewCategory({ ...newCategory, color: e.target.value })}
              InputProps={{
                inputProps: { style: { height: 40 } }
              }}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleAddCategory} variant="contained" disabled={saving || !newCategory.name.trim()}>
            {saving ? <CircularProgress size={20} /> : 'Add Category'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

// ============== Upload Dialog ==============

const UploadDialog: React.FC<{
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
}> = ({ open, onClose, onComplete }) => {
  const [activeStep, setActiveStep] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Analysis results
  const [headers, setHeaders] = useState<string[]>([]);
  const [sampleRows, setSampleRows] = useState<string[][]>([]);
  const [rowCount, setRowCount] = useState(0);
  const [mapping, setMapping] = useState<ColumnMapping>({});
  
  // Import results
  const [importResult, setImportResult] = useState<{ success_count: number; error_count: number; errors: string[] } | null>(null);

  const steps = ['Upload File', 'Map Columns', 'Import'];

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;

    setFile(selectedFile);
    setError(null);
    setAnalyzing(true);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const response = await fetch(`${config.apiBaseUrl}/v1/accounting/upload/analyze`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });
      
      if (response.ok) {
        const data = await response.json();
        setHeaders(data.headers);
        setSampleRows(data.sample_rows);
        setRowCount(data.row_count);
        setMapping(data.suggested_mapping || {});
        setActiveStep(1);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to analyze file');
      }
    } catch (err) {
      setError('Failed to upload file');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleImport = async () => {
    if (!file) return;

    setImporting(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('mapping', JSON.stringify(mapping));

      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const response = await fetch(`${config.apiBaseUrl}/v1/accounting/upload/import`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });
      
      if (response.ok) {
        const data = await response.json();
        setImportResult(data);
        setActiveStep(2);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to import file');
      }
    } catch (err) {
      setError('Failed to import file');
    } finally {
      setImporting(false);
    }
  };

  const handleClose = () => {
    setActiveStep(0);
    setFile(null);
    setHeaders([]);
    setSampleRows([]);
    setMapping({});
    setImportResult(null);
    setError(null);
    onClose();
  };

  const handleFinish = () => {
    handleClose();
    onComplete();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Import Spreadsheet</DialogTitle>
      <DialogContent>
        <Stepper activeStep={activeStep} sx={{ mb: 3 }}>
          {steps.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {/* Step 0: Upload */}
        {activeStep === 0 && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <input
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
              id="spreadsheet-upload"
            />
            <label htmlFor="spreadsheet-upload">
              <Button
                variant="outlined"
                component="span"
                size="large"
                startIcon={analyzing ? <CircularProgress size={20} /> : <UploadIcon />}
                disabled={analyzing}
              >
                {analyzing ? 'Analyzing...' : 'Select CSV or Excel File'}
              </Button>
            </label>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              Supported formats: CSV, XLSX, XLS
            </Typography>
          </Box>
        )}

        {/* Step 1: Map Columns */}
        {activeStep === 1 && (
          <Box>
            <Alert severity="info" sx={{ mb: 2 }}>
              We detected {rowCount} rows. Please verify the column mapping below.
            </Alert>

            <Grid container spacing={2} sx={{ mb: 3 }}>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth size="small">
                  <InputLabel>Date Column *</InputLabel>
                  <Select
                    value={mapping.date_column || ''}
                    label="Date Column *"
                    onChange={(e) => setMapping({ ...mapping, date_column: e.target.value })}
                  >
                    <MenuItem value="">Select column</MenuItem>
                    {headers.map((h) => (
                      <MenuItem key={h} value={h}>{h}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth size="small">
                  <InputLabel>Description Column *</InputLabel>
                  <Select
                    value={mapping.description_column || ''}
                    label="Description Column *"
                    onChange={(e) => setMapping({ ...mapping, description_column: e.target.value })}
                  >
                    <MenuItem value="">Select column</MenuItem>
                    {headers.map((h) => (
                      <MenuItem key={h} value={h}>{h}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth size="small">
                  <InputLabel>Amount Column</InputLabel>
                  <Select
                    value={mapping.amount_column || ''}
                    label="Amount Column"
                    onChange={(e) => setMapping({ ...mapping, amount_column: e.target.value })}
                  >
                    <MenuItem value="">Select column</MenuItem>
                    {headers.map((h) => (
                      <MenuItem key={h} value={h}>{h}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth size="small">
                  <InputLabel>Income Column (Credit)</InputLabel>
                  <Select
                    value={mapping.income_column || ''}
                    label="Income Column (Credit)"
                    onChange={(e) => setMapping({ ...mapping, income_column: e.target.value })}
                  >
                    <MenuItem value="">Not used</MenuItem>
                    {headers.map((h) => (
                      <MenuItem key={h} value={h}>{h}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth size="small">
                  <InputLabel>Expense Column (Debit)</InputLabel>
                  <Select
                    value={mapping.expense_column || ''}
                    label="Expense Column (Debit)"
                    onChange={(e) => setMapping({ ...mapping, expense_column: e.target.value })}
                  >
                    <MenuItem value="">Not used</MenuItem>
                    {headers.map((h) => (
                      <MenuItem key={h} value={h}>{h}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControl fullWidth size="small">
                  <InputLabel>Reference Column</InputLabel>
                  <Select
                    value={mapping.reference_column || ''}
                    label="Reference Column"
                    onChange={(e) => setMapping({ ...mapping, reference_column: e.target.value })}
                  >
                    <MenuItem value="">Not used</MenuItem>
                    {headers.map((h) => (
                      <MenuItem key={h} value={h}>{h}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>

            {/* Preview Table */}
            <Typography variant="subtitle2" gutterBottom>
              Preview (first 5 rows)
            </Typography>
            <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 200 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    {headers.map((h) => (
                      <TableCell key={h} sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>
                        {h}
                      </TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {sampleRows.map((row, i) => (
                    <TableRow key={i}>
                      {row.map((cell, j) => (
                        <TableCell key={j}>{cell}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}

        {/* Step 2: Results */}
        {activeStep === 2 && importResult && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <CheckCircleIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
            <Typography variant="h6" gutterBottom>
              Import Complete
            </Typography>
            <Typography color="text.secondary" gutterBottom>
              Successfully imported {importResult.success_count} transactions
            </Typography>
            {importResult.error_count > 0 && (
              <Alert severity="warning" sx={{ mt: 2, textAlign: 'left' }}>
                {importResult.error_count} rows had errors and were skipped.
                {importResult.errors.length > 0 && (
                  <Box sx={{ mt: 1, fontSize: '0.875rem' }}>
                    {importResult.errors.slice(0, 5).map((err, i) => (
                      <div key={i}>{err}</div>
                    ))}
                  </Box>
                )}
              </Alert>
            )}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>
          {activeStep === 2 ? 'Close' : 'Cancel'}
        </Button>
        {activeStep === 1 && (
          <Button
            variant="contained"
            onClick={handleImport}
            disabled={importing || !mapping.date_column || !mapping.description_column || (!mapping.amount_column && !mapping.income_column)}
          >
            {importing ? <CircularProgress size={20} /> : 'Import'}
          </Button>
        )}
        {activeStep === 2 && (
          <Button variant="contained" onClick={handleFinish}>
            Done
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

// ============== Add Transaction Dialog ==============

const AddTransactionDialog: React.FC<{
  open: boolean;
  onClose: () => void;
  categories: Category[];
  onSuccess: () => void;
}> = ({ open, onClose, categories, onSuccess }) => {
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    transaction_date: new Date().toISOString().split('T')[0],
    description: '',
    amount: '',
    type: 'expense' as 'income' | 'expense',
    category_id: '',
    payee_payer: '',
    reference: '',
    notes: '',
  });

  const handleSubmit = async () => {
    if (!form.description || !form.amount) return;

    setSaving(true);
    try {
      const response = await apiRequest('POST', '/v1/accounting/transactions', {
        ...form,
        amount: parseFloat(form.amount),
        category_id: form.category_id || null,
      });

      if (response.ok) {
        setForm({
          transaction_date: new Date().toISOString().split('T')[0],
          description: '',
          amount: '',
          type: 'expense',
          category_id: '',
          payee_payer: '',
          reference: '',
          notes: '',
        });
        onSuccess();
      }
    } catch (error) {
      console.error('Failed to create transaction:', error);
    } finally {
      setSaving(false);
    }
  };

  const filteredCategories = categories.filter((c) => c.type === form.type);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add Transaction</DialogTitle>
      <DialogContent>
        <Box sx={{ pt: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Chip
              label="Expense"
              onClick={() => setForm({ ...form, type: 'expense', category_id: '' })}
              color={form.type === 'expense' ? 'error' : 'default'}
              variant={form.type === 'expense' ? 'filled' : 'outlined'}
            />
            <Chip
              label="Income"
              onClick={() => setForm({ ...form, type: 'income', category_id: '' })}
              color={form.type === 'income' ? 'success' : 'default'}
              variant={form.type === 'income' ? 'filled' : 'outlined'}
            />
          </Box>

          <TextField
            label="Date"
            type="date"
            fullWidth
            value={form.transaction_date}
            onChange={(e) => setForm({ ...form, transaction_date: e.target.value })}
            InputLabelProps={{ shrink: true }}
          />

          <TextField
            label="Description"
            fullWidth
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            required
          />

          <TextField
            label="Amount"
            type="number"
            fullWidth
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            InputProps={{
              startAdornment: <InputAdornment position="start">£</InputAdornment>,
            }}
            required
          />

          <FormControl fullWidth>
            <InputLabel>Category</InputLabel>
            <Select
              value={form.category_id}
              label="Category"
              onChange={(e) => setForm({ ...form, category_id: e.target.value })}
            >
              <MenuItem value="">No category</MenuItem>
              {filteredCategories.map((cat) => (
                <MenuItem key={cat.id} value={cat.id}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: cat.color }} />
                    {cat.name}
                  </Box>
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            label="Payee/Payer"
            fullWidth
            value={form.payee_payer}
            onChange={(e) => setForm({ ...form, payee_payer: e.target.value })}
          />

          <TextField
            label="Reference"
            fullWidth
            value={form.reference}
            onChange={(e) => setForm({ ...form, reference: e.target.value })}
            placeholder="Invoice number, receipt, etc."
          />

          <TextField
            label="Notes"
            fullWidth
            multiline
            rows={2}
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={saving || !form.description || !form.amount}
        >
          {saving ? <CircularProgress size={20} /> : 'Add Transaction'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default Accounting;
