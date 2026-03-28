import React, { useState, useEffect } from 'react';
import LoadingMessage from '@/components/LoadingMessage';
import {
  Box,
  Typography,
  Button,
  Card,
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
  Divider,
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
  InputAdornment,
} from '@mui/material';
import {
  Receipt as ReceiptIcon,
  Archive as ArchiveIcon,
  Warning as WarningIcon,
  Gavel as GavelIcon,
  CloudUpload as CloudUploadIcon,
  Close as CloseIcon,
  Send as SendIcon,
  Preview as PreviewIcon,
  Undo as UndoIcon,
  Cancel as CancelIcon,
  Delete as DeleteIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
  CheckCircle as CheckCircleIcon,
} from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';
import { supabase } from '@/lib/supabase';
import { config } from '@/config/env';

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

interface InvoicesPanelProps {
  businessId: string;
}

export default function InvoicesPanel({ businessId }: InvoicesPanelProps) {
  const [invoices, setInvoices] = useState<Invoice[]>(() => {
    try {
      const cached = sessionStorage.getItem(`bh_invoices_${businessId}`);
      return cached ? JSON.parse(cached) : [];
    } catch { return []; }
  });
  const [invoicesLoading, setInvoicesLoading] = useState(false);
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null);
  const [invoiceDrawerOpen, setInvoiceDrawerOpen] = useState(false);
  const [chaseDraft, setChaseDraft] = useState<{ subject: string; body: string; chase_stage: number } | null>(null);
  const [csvUploading, setCsvUploading] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');
  const [error, setError] = useState('');
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

  // Invoice functions
  const fetchInvoices = async () => {
    setInvoicesLoading(invoices.length === 0);
    try {
      const params = new URLSearchParams();
      if (invoiceSearch) params.append('search', invoiceSearch);
      if (invoiceStatusFilter) params.append('status', invoiceStatusFilter);
      params.append('archived', showArchivedInvoices.toString());
      params.append('sort_by', invoiceSortBy);
      params.append('sort_order', invoiceSortOrder);
      
      const response = await apiRequest('GET', `/v1/invoices?${params.toString()}`);
      const data = await response.json();
      const result = data.invoices || [];
      setInvoices(result);
      try { sessionStorage.setItem(`bh_invoices_${businessId}`, JSON.stringify(result)); } catch {}
    } catch (err: any) {
      setError(err.message || 'Failed to fetch invoices');
    } finally {
      setInvoicesLoading(false);
    }
  };

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

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
      
      await fetchInvoices();
      
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
        chase_stage: invoiceStage,
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
        chase_stage: bulkChaseStage,
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
        chase_stage: bulkChaseStage,
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

  // Fetch invoices on mount and when filters change
  useEffect(() => {
    fetchInvoices();
  }, [businessId, invoiceStatusFilter, showArchivedInvoices, invoiceSortBy, invoiceSortOrder]);

  // Debounced search for invoices
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchInvoices();
    }, 300);
    return () => clearTimeout(timer);
  }, [invoiceSearch]);

  // Check Xero connection status (invoice sync is handled by Accounting.tsx via sync-all)
  useEffect(() => {
    const checkXero = async () => {
      try {
        const resp = await apiRequest('GET', '/v1/accounting/xero/status');
        if (resp.ok) {
          const data = await resp.json();
          setXeroConnected(data.connected);
        }
      } catch (e) {
        console.error('Xero status check failed:', e);
      }
    };
    checkXero();
  }, [businessId]);

  return (
    <>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

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
            {!xeroInvoiceSyncing && (
              <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                {(() => {
                  const ls = localStorage.getItem('bh_xero_invoice_last_sync');
                  return ls
                    ? `Last: ${new Date(ls).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`
                    : 'Not synced today';
                })()}
              </Typography>
            )}
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

      {invoicesLoading && invoices.length === 0 ? (
        <LoadingMessage
          messages={["Syncing with your accounting software...", "Matching invoices and updating statuses...", "This keeps everything accurate and up to date!"]}
          icon="📄"
        />
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

      {/* Success Snackbar */}
      <Snackbar
        open={!!successMessage}
        autoHideDuration={6000}
        onClose={() => setSuccessMessage('')}
        message={successMessage}
      />
    </>
  );
}
