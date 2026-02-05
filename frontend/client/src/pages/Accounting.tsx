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
  
  // Filters
  const [period, setPeriod] = useState<'month' | 'quarter' | 'year' | 'all'>('month');
  const [transactionType, setTransactionType] = useState<'all' | 'income' | 'expense'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  
  // Dialogs
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [addTransactionOpen, setAddTransactionOpen] = useState(false);

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
      params.append('limit', '100');
      
      const response = await apiRequest('GET', `/v1/accounting/transactions?${params.toString()}`);
      if (response.ok) {
        const data = await response.json();
        setTransactions(data.transactions);
        setTotalTransactions(data.total);
      }
    } catch (error) {
      console.error('Failed to fetch transactions:', error);
    }
  }, [transactionType, searchQuery, selectedCategory]);

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

  // Refresh transactions when filters change
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchTransactions();
    }, 300);
    return () => clearTimeout(timer);
  }, [transactionType, searchQuery, selectedCategory]);

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
    fetchTransactions();
    fetchSummary();
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
          <OverviewTab summary={summary} />
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
    </Box>
  );
};

// ============== Overview Tab ==============

const OverviewTab: React.FC<{ summary: Summary | null }> = ({ summary }) => {
  if (!summary) return null;

  const COLORS = ['#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899', '#6366F1', '#14B8A6'];

  return (
    <Grid container spacing={3}>
      {/* Trend Chart */}
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Income vs Expenses Trend
            </Typography>
            {summary.trend.length > 0 ? (
              <Box sx={{ height: 300 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={summary.trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="month" 
                      tickFormatter={(value) => {
                        const [year, month] = value.split('-');
                        return new Date(parseInt(year), parseInt(month) - 1).toLocaleDateString('en-GB', { month: 'short' });
                      }}
                    />
                    <YAxis tickFormatter={(value) => `£${value.toLocaleString()}`} />
                    <RechartsTooltip 
                      formatter={(value: number) => `£${value.toLocaleString('en-GB', { minimumFractionDigits: 2 })}`}
                    />
                    <Legend />
                    <Bar dataKey="income" name="Income" fill="#10B981" />
                    <Bar dataKey="expense" name="Expenses" fill="#EF4444" />
                  </BarChart>
                </ResponsiveContainer>
              </Box>
            ) : (
              <Box sx={{ py: 4, textAlign: 'center' }}>
                <Typography color="text.secondary">No trend data available yet</Typography>
              </Box>
            )}
          </CardContent>
        </Card>
      </Grid>

      {/* Income Breakdown */}
      <Grid item xs={12} md={6}>
        <Card sx={{ height: '100%' }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Income by Category
            </Typography>
            {summary.categories.income.length > 0 ? (
              <Box sx={{ height: 250 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={summary.categories.income}
                      dataKey="total"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                    >
                      {summary.categories.income.map((entry, index) => (
                        <Cell key={entry.name} fill={entry.color || COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <RechartsTooltip formatter={(value: number) => `£${value.toLocaleString('en-GB', { minimumFractionDigits: 2 })}`} />
                  </PieChart>
                </ResponsiveContainer>
              </Box>
            ) : (
              <Box sx={{ py: 4, textAlign: 'center' }}>
                <Typography color="text.secondary">No income data yet</Typography>
              </Box>
            )}
          </CardContent>
        </Card>
      </Grid>

      {/* Expense Breakdown */}
      <Grid item xs={12} md={6}>
        <Card sx={{ height: '100%' }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Expenses by Category
            </Typography>
            {summary.categories.expense.length > 0 ? (
              <Box sx={{ height: 250 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={summary.categories.expense}
                      dataKey="total"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                    >
                      {summary.categories.expense.map((entry, index) => (
                        <Cell key={entry.name} fill={entry.color || COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <RechartsTooltip formatter={(value: number) => `£${value.toLocaleString('en-GB', { minimumFractionDigits: 2 })}`} />
                  </PieChart>
                </ResponsiveContainer>
              </Box>
            ) : (
              <Box sx={{ py: 4, textAlign: 'center' }}>
                <Typography color="text.secondary">No expense data yet</Typography>
              </Box>
            )}
          </CardContent>
        </Card>
      </Grid>

      {/* Top Categories Lists */}
      <Grid item xs={12} md={6}>
        <Card>
          <CardContent>
            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Top Income Sources
            </Typography>
            {summary.categories.income.slice(0, 5).map((cat) => (
              <Box key={cat.name} sx={{ display: 'flex', alignItems: 'center', py: 1 }}>
                <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: cat.color, mr: 2 }} />
                <Typography sx={{ flex: 1 }}>{cat.name}</Typography>
                <Typography fontWeight={600} color="success.main">
                  £{cat.total.toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                </Typography>
              </Box>
            ))}
            {summary.categories.income.length === 0 && (
              <Typography color="text.secondary" sx={{ py: 2 }}>No income recorded</Typography>
            )}
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} md={6}>
        <Card>
          <CardContent>
            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Top Expenses
            </Typography>
            {summary.categories.expense.slice(0, 5).map((cat) => (
              <Box key={cat.name} sx={{ display: 'flex', alignItems: 'center', py: 1 }}>
                <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: cat.color, mr: 2 }} />
                <Typography sx={{ flex: 1 }}>{cat.name}</Typography>
                <Typography fontWeight={600} color="error.main">
                  £{cat.total.toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                </Typography>
              </Box>
            ))}
            {summary.categories.expense.length === 0 && (
              <Typography color="text.secondary" sx={{ py: 2 }}>No expenses recorded</Typography>
            )}
          </CardContent>
        </Card>
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
}) => {
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

      {/* Transactions Table */}
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
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
                <TableCell colSpan={6} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">
                    {searchQuery || selectedCategory ? 'No transactions match your filters' : 'No transactions yet'}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              transactions.map((transaction) => (
                <TableRow key={transaction.id} hover>
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
                  <TableCell align="center">
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
