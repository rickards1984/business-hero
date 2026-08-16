import { useState, useEffect, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Box, Button, TextField, IconButton, Chip, Drawer, Divider, Dialog,
  DialogTitle, DialogContent, DialogActions, Tabs, Tab,
  Select, MenuItem, FormControl, InputLabel, Switch, FormControlLabel,
  Snackbar, Alert,
} from '@mui/material';
import {
  Add as AddIcon, Search as SearchIcon, Clear as ClearIcon,
  Edit as EditIcon, Delete as DeleteIcon, ContentCopy as DuplicateIcon,
  AutoAwesome as AIIcon,
  Close as CloseIcon, ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon,
  Send as SendIcon, PictureAsPdf as PdfIcon, Visibility as PreviewIcon,
  WhatsApp as WhatsAppIcon, Email as EmailIcon, Download as DownloadIcon,
} from '@mui/icons-material';
import { useMe } from '@/hooks/useMe';
import { apiRequest } from '@/lib/queryClient';
import LoadingMessage from '@/components/LoadingMessage';

interface LineItem {
  id?: string;
  category: string;
  description: string;
  quantity: number;
  unit: string;
  unit_cost: number;
  line_total: number;
  markup_percentage: number;
  markup_amount: number;
  sort_order: number;
  group_name: string;
}

interface Quote {
  id: string;
  quote_number: string;
  reference?: string;
  customer_name: string;
  customer_email?: string;
  customer_phone?: string;
  customer_address?: string;
  job_title: string;
  job_description?: string;
  job_location?: string;
  subtotal: number;
  tax_rate: number;
  tax_amount: number;
  discount_amount: number;
  discount_type: string;
  total: number;
  currency: string;
  markup_percentage: number;
  status: string;
  issue_date?: string;
  valid_until?: string;
  accepted_at?: string;
  declined_at?: string;
  terms?: string;
  notes?: string;
  customer_notes?: string;
  ai_generated: boolean;
  ai_prompt?: string;
  invoice_id?: string;
  sent_via?: string;
  created_at: string;
  updated_at: string;
  line_items?: LineItem[];
  project_reference?: string;
}

interface LabourRate {
  role: string;
  daily_rate: number;
}

interface QuoteSettings {
  quote_prefix: string;
  next_quote_number: number;
  default_terms: string;
  default_valid_days: number;
  default_tax_rate: number;
  include_tax: boolean;
  default_markup: number;
  company_name?: string;
  company_address?: string;
  company_phone?: string;
  company_email?: string;
  company_logo_url?: string;
  company_registration?: string;
  vat_number?: string;
  industry: string;
  labour_rates?: LabourRate[];
}

const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  draft:    { bg: 'rgba(255,255,255,0.08)', color: 'hsl(var(--muted-foreground))' },
  sent:     { bg: 'rgba(96,165,250,0.12)',  color: '#60a5fa' },
  viewed:   { bg: 'rgba(167,139,250,0.12)', color: '#a78bfa' },
  accepted: { bg: 'rgba(45,212,140,0.12)',  color: '#2dd48c' },
  declined: { bg: 'rgba(248,113,113,0.12)', color: '#f87171' },
  expired:  { bg: 'rgba(251,191,36,0.12)',  color: '#fbbf24' },
  invoiced: { bg: 'rgba(45,212,196,0.12)',  color: '#2dd4c4' },
};

const UNIT_OPTIONS = ['each', 'hours', 'days', 'sqm', 'lm', 'kg', 'cubic_m', 'litres', 'tonnes'];
// TODO(day2-vat): wire category picker — needed for CIS labour/materials split.
// const CATEGORY_OPTIONS = ['labour', 'materials', 'equipment', 'subcontractor', 'other'];
const INDUSTRY_OPTIONS = ['general', 'construction', 'plumbing', 'electrical', 'landscaping', 'cleaning', 'fitness', 'other'];

// apiRequest throws "<status>: <json body>" — extract the backend's
// human-readable `detail` field, or return null if there isn't one.
function apiErrorDetail(err: any): string | null {
  const raw: string = err?.message || '';
  const jsonStart = raw.indexOf('{');
  if (jsonStart !== -1) {
    try {
      const detail = JSON.parse(raw.slice(jsonStart))?.detail;
      if (typeof detail === 'string' && detail) return detail;
    } catch {}
  }
  return null;
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_COLORS[status] || STATUS_COLORS.draft;
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: 12,
      fontSize: 11,
      fontWeight: 600,
      textTransform: 'capitalize',
      background: style.bg,
      color: style.color,
    }}>
      {status}
    </span>
  );
}

export default function QuotesPage() {
  const { data: me } = useMe();
  const [searchParams] = useSearchParams();
  const businessId = me?.id;

  const [view, setView] = useState<'list' | 'create' | 'edit' | 'detail' | 'settings'>(
    (searchParams.get('view') as any) || 'list'
  );
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [, setStatusCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [groupByProject, setGroupByProject] = useState(false);

  const [selectedQuote, setSelectedQuote] = useState<Quote | null>(null);
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);

  // Create/Edit form state
  const [formMode, setFormMode] = useState<'ai' | 'manual'>('ai');
  const [aiDescription, setAiDescription] = useState('');
  const [aiGenerating, setAiGenerating] = useState(false);
  const [formData, setFormData] = useState({
    customer_name: '', customer_email: '', customer_phone: '', customer_address: '',
    job_title: '', job_description: '', job_location: '', project_reference: '',
    tax_rate: 20, discount_amount: 0, discount_type: 'fixed',
    terms: '', notes: '', customer_notes: '',
  });
  const [lineItems, setLineItems] = useState<LineItem[]>([]);
  const [editingQuoteId, setEditingQuoteId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Settings state
  const [settings, setSettings] = useState<QuoteSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);

  // Send dialog state
  const [sendDialogOpen, setSendDialogOpen] = useState(false);
  const [sendTab, setSendTab] = useState(0);
  const [sendEmail, setSendEmail] = useState('');
  const [sendSubject, setSendSubject] = useState('');
  const [sendMessage, setSendMessage] = useState('');
  const [sendPhone, setSendPhone] = useState('');
  const [sending, setSending] = useState(false);

  // Collapsed groups in line items
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // File upload state
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [uploadPreviews, setUploadPreviews] = useState<string[]>([]);

  // Snackbar
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({ open: false, message: '', severity: 'info' });

  const fetchQuotes = useCallback(async () => {
    if (!businessId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.append('status', statusFilter);
      if (search) params.append('search', search);
      params.append('limit', '100');
      const res = await apiRequest('GET', `/v1/quotes?${params.toString()}`);
      const data = await res.json();
      setQuotes(data.quotes || []);
      setStatusCounts(data.status_counts || {});
    } catch { setQuotes([]); }
    finally { setLoading(false); }
  }, [businessId, statusFilter, search]);

  useEffect(() => { fetchQuotes(); }, [fetchQuotes]);

  const fetchSettings = useCallback(async () => {
    setSettingsLoading(true);
    try {
      const res = await apiRequest('GET', '/v1/quotes/settings/config');
      setSettings(await res.json());
    } catch {}
    finally { setSettingsLoading(false); }
  }, []);

  useEffect(() => { if (view === 'settings') fetchSettings(); }, [view, fetchSettings]);

  // KPIs
  const kpis = useMemo(() => {
    const now = new Date();
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const thisMonth = quotes.filter(q => new Date(q.created_at) >= monthStart);
    const quotedThisMonth = thisMonth.reduce((sum, q) => sum + q.total, 0);
    const totalSentOrBeyond = quotes.filter(q => ['sent', 'accepted', 'declined', 'invoiced'].includes(q.status)).length;
    const accepted = quotes.filter(q => ['accepted', 'invoiced'].includes(q.status)).length;
    const acceptanceRate = totalSentOrBeyond > 0 ? Math.round((accepted / totalSentOrBeyond) * 100) : 0;
    const avgValue = quotes.length > 0 ? quotes.reduce((sum, q) => sum + q.total, 0) / quotes.length : 0;
    const outstanding = quotes.filter(q => ['sent', 'draft'].includes(q.status)).length;
    return { quotedThisMonth, acceptanceRate, avgValue, outstanding };
  }, [quotes]);

  // Grouped quotes by project
  const groupedByProject = useMemo(() => {
    if (!groupByProject) return null;
    const groups: Record<string, Quote[]> = { '(No project)': [] };
    quotes.forEach(q => {
      const key = q.project_reference || '(No project)';
      if (!groups[key]) groups[key] = [];
      groups[key].push(q);
    });
    return groups;
  }, [quotes, groupByProject]);

  // Filtered quotes for list
  const filteredQuotes = useMemo(() => {
    let filtered = quotes;
    if (search) {
      const s = search.toLowerCase();
      filtered = filtered.filter(q =>
        q.customer_name.toLowerCase().includes(s) ||
        q.job_title.toLowerCase().includes(s) ||
        q.quote_number.toLowerCase().includes(s)
      );
    }
    return filtered;
  }, [quotes, search]);

  const handleFileUpload = (files: File[]) => {
    const validFiles = files.filter(f =>
      f.type.startsWith('image/') || f.type === 'application/pdf'
    );
    setUploadedFiles(prev => [...prev, ...validFiles]);
    validFiles.forEach(file => {
      if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = (e) => {
          setUploadPreviews(prev => [...prev, e.target?.result as string]);
        };
        reader.readAsDataURL(file);
      } else {
        setUploadPreviews(prev => [...prev, '']);
      }
    });
  };

  const removeFile = (index: number) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index));
    setUploadPreviews(prev => prev.filter((_, i) => i !== index));
  };

  const handleGenerateAI = async () => {
    if (!aiDescription.trim()) return;
    setAiGenerating(true);
    try {
      const requestBody: any = { description: aiDescription };

      if (uploadedFiles.length > 0) {
        const imageData: string[] = [];
        for (const file of uploadedFiles) {
          if (file.type.startsWith('image/')) {
            const base64 = await new Promise<string>((resolve) => {
              const reader = new FileReader();
              reader.onload = (e) => resolve(e.target?.result as string);
              reader.readAsDataURL(file);
            });
            imageData.push(base64);
          }
        }
        if (imageData.length > 0) {
          requestBody.images = imageData;
        }
      }

      const res = await apiRequest('POST', '/v1/quotes/ai/generate', requestBody);
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || 'AI generation failed');
      }
      const data = await res.json();

      setFormData(prev => ({
        ...prev,
        job_title: data.job_title || prev.job_title || '',
        job_description: aiDescription,
        notes: data.notes || '',
      }));
      const items: LineItem[] = (data.line_items || []).map((item: any, i: number) => ({
        category: item.category || 'other',
        description: item.description || '',
        quantity: item.quantity || 1,
        unit: item.unit || 'each',
        unit_cost: item.unit_cost || 0,
        line_total: item.line_total || (item.quantity * item.unit_cost) || 0,
        markup_percentage: 0,
        markup_amount: 0,
        sort_order: i,
        group_name: item.group_name || 'General',
      }));
      setLineItems(items);
      setFormMode('manual');
      setSnackbar({ open: true, message: `AI generated ${items.length} line items — review and edit below`, severity: 'success' });
    } catch (err: any) {
      console.error('AI generation failed:', err);
      const detail = apiErrorDetail(err);
      setSnackbar({
        open: true,
        message: detail
          ? `Quote generation failed: ${detail}. Please try again.`
          : 'AI quote generation failed. Please try again, or simplify the description.',
        severity: 'error',
      });
    } finally { setAiGenerating(false); }
  };

  const handleSaveQuote = async () => {
    if (!formData.customer_name || !formData.job_title) {
      alert('Customer name and job title are required.');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...formData,
        line_items: lineItems.map((item, i) => ({ ...item, sort_order: i })),
        ai_generated: lineItems.some(() => formMode === 'ai'),
        ai_prompt: aiDescription || undefined,
      };
      if (editingQuoteId) {
        await apiRequest('PUT', `/v1/quotes/${editingQuoteId}`, payload);
      } else {
        await apiRequest('POST', '/v1/quotes', payload);
      }
      resetForm();
      setView('list');
      fetchQuotes();
    } catch {
      alert('Failed to save quote.');
    } finally { setSaving(false); }
  };

  const handleDeleteQuote = async (quoteId: string) => {
    if (!confirm('Delete this quote?')) return;
    try {
      await apiRequest('DELETE', `/v1/quotes/${quoteId}`);
      fetchQuotes();
      setDetailDrawerOpen(false);
    } catch {}
  };

  const handleStatusAction = async (quoteId: string, action: string, data?: any) => {
    try {
      const res = await apiRequest('POST', `/v1/quotes/${quoteId}/${action}`, data || {});
      const result = await res.json().catch(() => ({}));
      const successMessages: Record<string, string> = {
        'accept': 'Quote marked as accepted',
        'decline': 'Quote marked as declined',
        'convert-to-invoice': result.invoice_number
          ? `Invoice ${result.invoice_number} created — see Finance → Invoices`
          : 'Invoice created — see Finance → Invoices',
      };
      setSnackbar({ open: true, message: successMessages[action] || 'Done', severity: 'success' });
      fetchQuotes();
      if (selectedQuote?.id === quoteId) {
        const refreshed = await apiRequest('GET', `/v1/quotes/${quoteId}`);
        setSelectedQuote(await refreshed.json());
      }
    } catch (err: any) {
      console.error(`Quote action '${action}' failed:`, err);
      const detail = apiErrorDetail(err);
      setSnackbar({
        open: true,
        message: detail ? `Action failed: ${detail}` : 'Action failed. Please try again.',
        severity: 'error',
      });
    }
  };

  const openDetail = async (quoteId: string) => {
    try {
      const res = await apiRequest('GET', `/v1/quotes/${quoteId}`);
      setSelectedQuote(await res.json());
      setDetailDrawerOpen(true);
    } catch {}
  };

  const openEdit = async (quoteId: string) => {
    try {
      const res = await apiRequest('GET', `/v1/quotes/${quoteId}`);
      const q: Quote = await res.json();
      setEditingQuoteId(q.id);
      setFormData({
        customer_name: q.customer_name, customer_email: q.customer_email || '',
        customer_phone: q.customer_phone || '', customer_address: q.customer_address || '',
        job_title: q.job_title, job_description: q.job_description || '',
        job_location: q.job_location || '', project_reference: q.project_reference || '',
        tax_rate: q.tax_rate, discount_amount: q.discount_amount,
        discount_type: q.discount_type, terms: q.terms || '',
        notes: q.notes || '', customer_notes: q.customer_notes || '',
      });
      setLineItems(q.line_items || []);
      setFormMode('manual');
      setView('edit');
      setDetailDrawerOpen(false);
    } catch {}
  };

  const handleDuplicate = async (quoteId: string) => {
    try {
      const res = await apiRequest('GET', `/v1/quotes/${quoteId}`);
      const q: Quote = await res.json();
      setEditingQuoteId(null);
      setFormData({
        customer_name: q.customer_name, customer_email: q.customer_email || '',
        customer_phone: q.customer_phone || '', customer_address: q.customer_address || '',
        job_title: q.job_title + ' (copy)', job_description: q.job_description || '',
        job_location: q.job_location || '', project_reference: q.project_reference || '',
        tax_rate: q.tax_rate, discount_amount: q.discount_amount,
        discount_type: q.discount_type, terms: q.terms || '',
        notes: q.notes || '', customer_notes: q.customer_notes || '',
      });
      setLineItems((q.line_items || []).map(i => ({ ...i, id: undefined })));
      setFormMode('manual');
      setView('create');
      setDetailDrawerOpen(false);
    } catch {}
  };

  const resetForm = () => {
    setFormData({
      customer_name: '', customer_email: '', customer_phone: '', customer_address: '',
      job_title: '', job_description: '', job_location: '', project_reference: '',
      tax_rate: 20, discount_amount: 0, discount_type: 'fixed',
      terms: '', notes: '', customer_notes: '',
    });
    setLineItems([]);
    setEditingQuoteId(null);
    setAiDescription('');
    setFormMode('ai');
    setUploadedFiles([]);
    setUploadPreviews([]);
  };

  const addLineItem = (groupName: string = 'General') => {
    setLineItems(prev => [...prev, {
      category: 'other', description: '', quantity: 1, unit: 'each',
      unit_cost: 0, line_total: 0, markup_percentage: 0, markup_amount: 0,
      sort_order: prev.length, group_name: groupName,
    }]);
  };

  const updateLineItem = (index: number, field: string, value: any) => {
    setLineItems(prev => prev.map((item, i) => {
      if (i !== index) return item;
      const updated = { ...item, [field]: value };
      updated.line_total = updated.quantity * updated.unit_cost;
      updated.markup_amount = updated.line_total * (updated.markup_percentage / 100);
      return updated;
    }));
  };

  const removeLineItem = (index: number) => {
    setLineItems(prev => prev.filter((_, i) => i !== index));
  };

  const subtotal = lineItems.reduce((sum, i) => sum + i.line_total, 0);
  const discountApplied = formData.discount_type === 'percentage'
    ? subtotal * (formData.discount_amount / 100)
    : formData.discount_amount;
  const taxable = subtotal - discountApplied;
  const taxAmount = taxable * (formData.tax_rate / 100);
  const total = taxable + taxAmount;

  const lineItemGroups = useMemo(() => {
    const groups: Record<string, { items: LineItem[]; indices: number[] }> = {};
    lineItems.forEach((item, i) => {
      const g = item.group_name || 'General';
      if (!groups[g]) groups[g] = { items: [], indices: [] };
      groups[g].items.push(item);
      groups[g].indices.push(i);
    });
    return groups;
  }, [lineItems]);

  const handleSaveSettings = async () => {
    if (!settings) return;
    setSettingsSaving(true);
    try {
      await apiRequest('PUT', '/v1/quotes/settings/config', settings);
    } catch {}
    finally { setSettingsSaving(false); }
  };

  const handleDownloadPDF = async (quoteId: string, quoteNumber: string) => {
    try {
      const res = await apiRequest('POST', `/v1/quotes/${quoteId}/generate-pdf`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${quoteNumber}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('PDF download failed. Please try again.');
    }
  };

  const handlePreviewPDF = async (quoteId: string) => {
    try {
      const res = await apiRequest('POST', `/v1/quotes/${quoteId}/generate-pdf`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    } catch {
      alert('PDF preview failed. Please try again.');
    }
  };

  const openSendDialog = (quote: Quote) => {
    setSendEmail(quote.customer_email || '');
    setSendPhone(quote.customer_phone || '');
    setSendSubject(`Quote ${quote.quote_number}`);
    setSendMessage(
      `Dear ${quote.customer_name || 'Customer'},\n\n` +
      `Please find attached our quote ${quote.quote_number} for ${quote.job_title || 'the requested work'}.\n\n` +
      `Total: £${quote.total.toLocaleString('en-GB', { minimumFractionDigits: 2 })} (inc. VAT)\n\n` +
      (quote.valid_until ? `This quote is valid until ${quote.valid_until}.\n\n` : '') +
      `If you have any questions or would like to proceed, please don't hesitate to get in touch.\n\nKind regards`
    );
    setSendTab(0);
    setSendDialogOpen(true);
  };

  const handleSendEmail = async () => {
    if (!selectedQuote || !sendEmail) return;
    setSending(true);
    try {
      await apiRequest('POST', `/v1/quotes/${selectedQuote.id}/send-email`, {
        email: sendEmail,
        subject: sendSubject,
        message: sendMessage,
      });
      setSendDialogOpen(false);
      fetchQuotes();
      const res = await apiRequest('GET', `/v1/quotes/${selectedQuote.id}`);
      setSelectedQuote(await res.json());
    } catch {
      alert('Failed to send email. Make sure Gmail is connected in Email Settings.');
    } finally { setSending(false); }
  };

  const handleSendWhatsApp = async () => {
    if (!selectedQuote || !sendPhone) return;
    setSending(true);
    try {
      await apiRequest('POST', `/v1/quotes/${selectedQuote.id}/send-whatsapp`, {
        phone: sendPhone,
      });
      setSendDialogOpen(false);
      fetchQuotes();
      const res = await apiRequest('GET', `/v1/quotes/${selectedQuote.id}`);
      setSelectedQuote(await res.json());
    } catch {
      alert('Failed to send WhatsApp message.');
    } finally { setSending(false); }
  };

  // ─── RENDER ──────────────────────────────────────────────

  if (!businessId) return null;

  // Settings view
  if (view === 'settings') {
    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, color: 'hsl(var(--foreground))', margin: 0 }}>Quote Settings</h2>
          <Button size="small" onClick={() => setView('list')} sx={{ color: 'hsl(var(--muted-foreground))' }}>← Back to Quotes</Button>
        </div>
        {settingsLoading || !settings ? (
          <LoadingMessage messages={["Loading your quote settings..."]} icon="⚙️" />
        ) : (
          <div className="glass-card" style={{ padding: 20 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
              <TextField label="Quote Prefix" size="small" value={settings.quote_prefix} onChange={e => setSettings({ ...settings, quote_prefix: e.target.value })} />
              <TextField label="Default Validity (days)" size="small" type="number" value={settings.default_valid_days} onChange={e => setSettings({ ...settings, default_valid_days: parseInt(e.target.value) || 30 })} />
              <TextField label="Default Tax Rate (%)" size="small" type="number" value={settings.default_tax_rate} onChange={e => setSettings({ ...settings, default_tax_rate: parseFloat(e.target.value) || 0 })} />
              <TextField label="Default Markup (%)" size="small" type="number" value={settings.default_markup} onChange={e => setSettings({ ...settings, default_markup: parseFloat(e.target.value) || 0 })} />
            </div>
            <TextField label="Default Terms & Conditions" size="small" fullWidth multiline minRows={3} value={settings.default_terms || ''} onChange={e => setSettings({ ...settings, default_terms: e.target.value })} sx={{ mb: 2 }} />
            <Divider sx={{ my: 2, borderColor: 'rgba(255,255,255,0.06)' }} />
            <h3 style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 12 }}>Company Details (for quotes)</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
              <TextField label="Company Name" size="small" value={settings.company_name || ''} onChange={e => setSettings({ ...settings, company_name: e.target.value })} />
              <TextField label="Company Phone" size="small" value={settings.company_phone || ''} onChange={e => setSettings({ ...settings, company_phone: e.target.value })} />
              <TextField label="Company Email" size="small" value={settings.company_email || ''} onChange={e => setSettings({ ...settings, company_email: e.target.value })} />
              <TextField label="Registration Number" size="small" value={settings.company_registration || ''} onChange={e => setSettings({ ...settings, company_registration: e.target.value })} />
              <TextField label="VAT Number" size="small" value={settings.vat_number || ''} onChange={e => setSettings({ ...settings, vat_number: e.target.value })} />
              <FormControl size="small">
                <InputLabel>Industry</InputLabel>
                <Select value={settings.industry} label="Industry" onChange={e => setSettings({ ...settings, industry: e.target.value })}>
                  {INDUSTRY_OPTIONS.map(i => <MenuItem key={i} value={i} sx={{ textTransform: 'capitalize' }}>{i}</MenuItem>)}
                </Select>
              </FormControl>
            </div>
            <TextField label="Company Address" size="small" fullWidth multiline minRows={2} value={settings.company_address || ''} onChange={e => setSettings({ ...settings, company_address: e.target.value })} sx={{ mb: 2 }} />
            <Divider sx={{ my: 2, borderColor: 'rgba(255,255,255,0.06)' }} />
            <h3 style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 4 }}>Your Labour Rates</h3>
            <p style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))', marginBottom: 12 }}>
              Set your standard rates. AI will use these instead of industry averages when generating quotes.
            </p>
            {(settings.labour_rates && settings.labour_rates.length > 0 ? settings.labour_rates : [
              { role: 'Labourer', daily_rate: 150 },
              { role: 'Skilled Tradesperson', daily_rate: 280 },
              { role: 'Electrician', daily_rate: 320 },
              { role: 'Plumber', daily_rate: 300 },
              { role: 'Painter/Decorator', daily_rate: 220 },
            ]).map((rate: LabourRate, index: number) => (
              <div key={index} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <TextField
                  size="small" value={rate.role} placeholder="Role" sx={{ flex: 1 }}
                  onChange={(e) => {
                    const updated = [...(settings.labour_rates && settings.labour_rates.length > 0 ? settings.labour_rates : [
                      { role: 'Labourer', daily_rate: 150 }, { role: 'Skilled Tradesperson', daily_rate: 280 },
                      { role: 'Electrician', daily_rate: 320 }, { role: 'Plumber', daily_rate: 300 },
                      { role: 'Painter/Decorator', daily_rate: 220 },
                    ])];
                    updated[index] = { ...updated[index], role: e.target.value };
                    setSettings({ ...settings, labour_rates: updated });
                  }}
                />
                <TextField
                  size="small" type="number" value={rate.daily_rate} label="£/day" sx={{ width: 100 }}
                  InputLabelProps={{ shrink: true }}
                  onChange={(e) => {
                    const updated = [...(settings.labour_rates && settings.labour_rates.length > 0 ? settings.labour_rates : [
                      { role: 'Labourer', daily_rate: 150 }, { role: 'Skilled Tradesperson', daily_rate: 280 },
                      { role: 'Electrician', daily_rate: 320 }, { role: 'Plumber', daily_rate: 300 },
                      { role: 'Painter/Decorator', daily_rate: 220 },
                    ])];
                    updated[index] = { ...updated[index], daily_rate: parseFloat(e.target.value) || 0 };
                    setSettings({ ...settings, labour_rates: updated });
                  }}
                />
                <IconButton size="small" onClick={() => {
                  const current = settings.labour_rates && settings.labour_rates.length > 0 ? settings.labour_rates : [
                    { role: 'Labourer', daily_rate: 150 }, { role: 'Skilled Tradesperson', daily_rate: 280 },
                    { role: 'Electrician', daily_rate: 320 }, { role: 'Plumber', daily_rate: 300 },
                    { role: 'Painter/Decorator', daily_rate: 220 },
                  ];
                  setSettings({ ...settings, labour_rates: current.filter((_: any, i: number) => i !== index) });
                }} sx={{ color: 'rgba(248,113,113,0.7)' }}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </div>
            ))}
            <Button size="small" startIcon={<AddIcon />} onClick={() => {
              const current = settings.labour_rates && settings.labour_rates.length > 0 ? settings.labour_rates : [
                { role: 'Labourer', daily_rate: 150 }, { role: 'Skilled Tradesperson', daily_rate: 280 },
                { role: 'Electrician', daily_rate: 320 }, { role: 'Plumber', daily_rate: 300 },
                { role: 'Painter/Decorator', daily_rate: 220 },
              ];
              setSettings({ ...settings, labour_rates: [...current, { role: '', daily_rate: 0 }] });
            }} sx={{ color: '#a78bfa', textTransform: 'none', mb: 2 }}>
              Add rate
            </Button>
            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button variant="contained" onClick={handleSaveSettings} disabled={settingsSaving} sx={{ background: '#7c5cfc', '&:hover': { background: '#6a4de0' } }}>
                {settingsSaving ? 'Saving...' : 'Save Settings'}
              </Button>
            </Box>
          </div>
        )}
      </div>
    );
  }

  // Create / Edit view
  if (view === 'create' || view === 'edit') {
    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, color: 'hsl(var(--foreground))', margin: 0 }}>
            {editingQuoteId ? 'Edit Quote' : 'Create Quote'}
          </h2>
          <Button size="small" onClick={() => { resetForm(); setView('list'); }} sx={{ color: 'hsl(var(--muted-foreground))' }}>← Back</Button>
        </div>

        {/* AI Generation — only for new quotes */}
        {!editingQuoteId && formMode === 'ai' && lineItems.length === 0 && (
          <>
            <div className="glass-card" style={{ padding: 20, marginBottom: 16 }}>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 8 }}>
                ✨ AI-Assisted Quote
              </h3>
              <p style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))', marginBottom: 12 }}>
                Describe the job and optionally upload site photos — AI will generate an itemised quote with UK trade pricing.
              </p>
              <TextField
                fullWidth multiline minRows={4} size="small"
                placeholder={'e.g., "Kitchen extension, 4m x 3m single storey, brick build, flat roof,\nnew window, relocate radiator, 2 new sockets, plastering and painting"'}
                value={aiDescription}
                onChange={e => setAiDescription(e.target.value)}
                disabled={aiGenerating}
                sx={{ mb: 2 }}
              />
            </div>

            {/* Photo & Drawing Upload */}
            <div className="glass-card" style={{ padding: 20, marginBottom: 16 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 4 }}>
                📸 Photos & Drawings
              </div>
              <div style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))', marginBottom: 12 }}>
                Upload site photos, drawings, plans, or specifications. AI will analyse these alongside your description to generate a more accurate quote.
              </div>
              <div
                onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = '#7c5cfc'; }}
                onDragLeave={(e) => { e.currentTarget.style.borderColor = 'var(--glass-border)'; }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.currentTarget.style.borderColor = 'var(--glass-border)';
                  handleFileUpload(Array.from(e.dataTransfer.files));
                }}
                onClick={() => document.getElementById('quote-file-upload')?.click()}
                style={{
                  border: '2px dashed var(--glass-border)',
                  borderRadius: 12,
                  padding: '24px 16px',
                  textAlign: 'center',
                  cursor: 'pointer',
                  transition: 'all 200ms',
                  background: 'var(--glass-bg)',
                }}
              >
                <input
                  id="quote-file-upload"
                  type="file"
                  multiple
                  accept="image/*,.pdf,.dwg,.dxf"
                  style={{ display: 'none' }}
                  onChange={(e) => { handleFileUpload(Array.from(e.target.files || [])); e.target.value = ''; }}
                />
                <div style={{ fontSize: 28, marginBottom: 8 }}>📷</div>
                <div style={{ fontSize: 13, fontWeight: 500, color: 'hsl(var(--foreground))' }}>
                  Drop photos, drawings, or plans here
                </div>
                <div style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))', marginTop: 4 }}>
                  or click to browse — JPG, PNG, PDF supported
                </div>
              </div>
              {uploadedFiles.length > 0 && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
                  {uploadedFiles.map((file, index) => (
                    <div key={index} style={{
                      position: 'relative', width: 80, height: 80, borderRadius: 8,
                      overflow: 'hidden', border: '0.5px solid var(--glass-border)',
                    }}>
                      {file.type.startsWith('image/') ? (
                        <img src={uploadPreviews[index]} alt={file.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      ) : (
                        <div style={{
                          width: '100%', height: '100%', display: 'flex', flexDirection: 'column',
                          alignItems: 'center', justifyContent: 'center', background: 'var(--glass-bg)',
                          fontSize: 10, color: 'hsl(var(--muted-foreground))', padding: 4, textAlign: 'center',
                        }}>
                          📄
                          <span style={{ marginTop: 2, wordBreak: 'break-all' }}>{file.name.slice(0, 15)}</span>
                        </div>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); removeFile(index); }}
                        style={{
                          position: 'absolute', top: 2, right: 2, width: 18, height: 18, borderRadius: '50%',
                          background: 'rgba(0,0,0,0.6)', color: '#fff', border: 'none', cursor: 'pointer',
                          fontSize: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* AI Generate Button */}
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              padding: '20px 16px', marginBottom: 16, borderRadius: 12,
              background: 'rgba(124, 92, 252, 0.06)', border: '0.5px solid rgba(124, 92, 252, 0.15)',
            }}>
              {!aiGenerating ? (
                <>
                  <div style={{ fontSize: 14, fontWeight: 500, color: 'hsl(var(--foreground))', marginBottom: 4, textAlign: 'center' }}>
                    Ready to generate your quote?
                  </div>
                  <div style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))', marginBottom: 12, textAlign: 'center' }}>
                    AI will analyse your job description{uploadedFiles.length > 0 ? ` and ${uploadedFiles.length} uploaded file${uploadedFiles.length > 1 ? 's' : ''}` : ''} to create an itemised quote with UK trade rates
                  </div>
                  <Button
                    variant="contained" onClick={handleGenerateAI} disabled={!aiDescription.trim()}
                    startIcon={<span>✨</span>}
                    sx={{
                      backgroundColor: '#7c5cfc', color: '#fff', textTransform: 'none',
                      fontWeight: 600, px: 4, py: 1.2, borderRadius: 2, fontSize: 14,
                      '&:hover': { backgroundColor: '#5a3fd4' },
                      '&:disabled': { backgroundColor: 'rgba(124,92,252,0.3)', color: 'rgba(255,255,255,0.5)' },
                    }}
                  >
                    Generate Quote with AI
                  </Button>
                  {!aiDescription.trim() && (
                    <div style={{ fontSize: 11, color: 'hsl(var(--muted-foreground))', marginTop: 8 }}>
                      Add a job description above to enable AI generation
                    </div>
                  )}
                  <Button size="small" onClick={() => setFormMode('manual')} sx={{ mt: 1.5, color: 'hsl(var(--muted-foreground))', textTransform: 'none', fontSize: 12 }}>
                    or enter items manually
                  </Button>
                </>
              ) : (
                <LoadingMessage
                  messages={[
                    "Analysing the job requirements...",
                    uploadedFiles.length > 0 ? "Studying your photos and drawings..." : "Breaking down the scope of work...",
                    "Calculating material quantities...",
                    "Pricing up each trade at current UK rates...",
                    "Building your itemised quote...",
                    "Nearly done — just reviewing the numbers!",
                  ]}
                  icon="🔨" rotateInterval={3000}
                />
              )}
            </div>
          </>
        )}

        {/* Manual Form — always shown in edit mode or after AI generates */}
        {(formMode === 'manual' || lineItems.length > 0 || editingQuoteId) && (
          <>
            {/* Customer & Job Details */}
            <div className="glass-card" style={{ padding: 20, marginBottom: 16 }}>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 12 }}>Customer & Job</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
                <TextField label="Customer Name *" size="small" value={formData.customer_name} onChange={e => setFormData({ ...formData, customer_name: e.target.value })} />
                <TextField label="Customer Email" size="small" value={formData.customer_email} onChange={e => setFormData({ ...formData, customer_email: e.target.value })} />
                <TextField label="Customer Phone" size="small" value={formData.customer_phone} onChange={e => setFormData({ ...formData, customer_phone: e.target.value })} />
                <TextField label="Job Location" size="small" value={formData.job_location} onChange={e => setFormData({ ...formData, job_location: e.target.value })} />
              </div>
              <TextField label="Job Title *" size="small" fullWidth value={formData.job_title} onChange={e => setFormData({ ...formData, job_title: e.target.value })} sx={{ mb: 1.5 }} />
              <TextField label="Job Description" size="small" fullWidth multiline minRows={2} value={formData.job_description} onChange={e => setFormData({ ...formData, job_description: e.target.value })} sx={{ mb: 1.5 }} />
              <TextField label="Project Reference (optional)" size="small" fullWidth value={formData.project_reference} onChange={e => setFormData({ ...formData, project_reference: e.target.value })} placeholder="e.g., 42 Oak Lane Garage Conversion" />
            </div>

            {/* Line Items */}
            <div className="glass-card" style={{ padding: 20, marginBottom: 16 }}>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 12 }}>Line Items</h3>
              {Object.entries(lineItemGroups).map(([groupName, { items, indices }]) => {
                const groupTotal = items.reduce((sum, i) => sum + i.line_total, 0);
                const isCollapsed = collapsedGroups.has(groupName);
                return (
                  <div key={groupName} style={{ marginBottom: 16 }}>
                    <div onClick={() => {
                      setCollapsedGroups(prev => {
                        const next = new Set(prev);
                        isCollapsed ? next.delete(groupName) : next.add(groupName);
                        return next;
                      });
                    }} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        {isCollapsed ? <ExpandMoreIcon sx={{ fontSize: 18 }} /> : <ExpandLessIcon sx={{ fontSize: 18 }} />}
                        <span style={{ fontSize: 13, fontWeight: 600, color: 'hsl(var(--foreground))' }}>{groupName}</span>
                      </div>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#2dd48c' }}>£{groupTotal.toLocaleString('en-GB', { minimumFractionDigits: 2 })}</span>
                    </div>
                    {!isCollapsed && (
                      <div>
                        {items.map((item, localIdx) => {
                          const globalIdx = indices[localIdx];
                          return (
                            <div key={globalIdx} style={{ display: 'grid', gridTemplateColumns: '2fr 80px 80px 90px 90px 36px', gap: 8, padding: '8px 0', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                              <TextField size="small" placeholder="Description" value={item.description} onChange={e => updateLineItem(globalIdx, 'description', e.target.value)} />
                              <TextField size="small" type="number" placeholder="Qty" value={item.quantity} onChange={e => updateLineItem(globalIdx, 'quantity', parseFloat(e.target.value) || 0)} inputProps={{ step: 'any' }} />
                              <Select size="small" value={item.unit} onChange={e => updateLineItem(globalIdx, 'unit', e.target.value)}>
                                {UNIT_OPTIONS.map(u => <MenuItem key={u} value={u}>{u}</MenuItem>)}
                              </Select>
                              <TextField size="small" type="number" placeholder="Cost" value={item.unit_cost} onChange={e => updateLineItem(globalIdx, 'unit_cost', parseFloat(e.target.value) || 0)} InputProps={{ startAdornment: <span style={{ color: 'hsl(var(--muted-foreground))', marginRight: 2 }}>£</span> }} />
                              <span style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))', textAlign: 'right' }}>£{item.line_total.toFixed(2)}</span>
                              <IconButton size="small" onClick={() => removeLineItem(globalIdx)} sx={{ color: '#f87171' }}><DeleteIcon sx={{ fontSize: 16 }} /></IconButton>
                            </div>
                          );
                        })}
                        <Button size="small" startIcon={<AddIcon />} onClick={() => addLineItem(groupName)} sx={{ mt: 1, color: '#7c5cfc', fontSize: 12 }}>Add item</Button>
                      </div>
                    )}
                  </div>
                );
              })}
              {lineItems.length === 0 && (
                <div style={{ textAlign: 'center', padding: '20px 0', color: 'hsl(var(--muted-foreground))', fontSize: 13 }}>
                  No line items yet.
                  <br />
                  <Button size="small" startIcon={<AddIcon />} onClick={() => addLineItem()} sx={{ mt: 1, color: '#7c5cfc' }}>Add first item</Button>
                </div>
              )}
            </div>

            {/* Totals & Terms */}
            <div className="glass-card" style={{ padding: 20, marginBottom: 16 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
                <TextField label="Tax Rate (%)" size="small" type="number" value={formData.tax_rate} onChange={e => setFormData({ ...formData, tax_rate: parseFloat(e.target.value) || 0 })} />
                <TextField label="Discount" size="small" type="number" value={formData.discount_amount} onChange={e => setFormData({ ...formData, discount_amount: parseFloat(e.target.value) || 0 })} />
                <FormControl size="small"><InputLabel>Discount Type</InputLabel><Select value={formData.discount_type} label="Discount Type" onChange={e => setFormData({ ...formData, discount_type: e.target.value })}><MenuItem value="fixed">Fixed (£)</MenuItem><MenuItem value="percentage">Percentage (%)</MenuItem></Select></FormControl>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, fontSize: 13, color: 'hsl(var(--muted-foreground))' }}>
                <div>Subtotal: <strong style={{ color: 'hsl(var(--foreground))' }}>£{subtotal.toFixed(2)}</strong></div>
                {discountApplied > 0 && <div>Discount: <span style={{ color: '#f87171' }}>-£{discountApplied.toFixed(2)}</span></div>}
                <div>VAT ({formData.tax_rate}%): £{taxAmount.toFixed(2)}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#2dd48c' }}>Total: £{total.toFixed(2)}</div>
              </div>
              <Divider sx={{ my: 2, borderColor: 'rgba(255,255,255,0.06)' }} />
              <TextField label="Terms & Conditions" size="small" fullWidth multiline minRows={2} value={formData.terms} onChange={e => setFormData({ ...formData, terms: e.target.value })} sx={{ mb: 1.5 }} />
              <TextField label="Notes to Customer" size="small" fullWidth multiline minRows={2} value={formData.customer_notes} onChange={e => setFormData({ ...formData, customer_notes: e.target.value })} sx={{ mb: 1.5 }} />
              <TextField label="Internal Notes" size="small" fullWidth multiline minRows={2} value={formData.notes} onChange={e => setFormData({ ...formData, notes: e.target.value })} />
            </div>

            {/* Save Actions */}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Button variant="outlined" onClick={() => { resetForm(); setView('list'); }} sx={{ borderColor: 'rgba(255,255,255,0.12)', color: 'hsl(var(--foreground))' }}>Cancel</Button>
              <Button variant="contained" onClick={handleSaveQuote} disabled={saving} sx={{ background: '#7c5cfc', '&:hover': { background: '#6a4de0' } }}>
                {saving ? 'Saving...' : 'Save as Draft'}
              </Button>
            </div>
          </>
        )}
      </div>
    );
  }

  // ─── LIST VIEW ───────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, color: 'hsl(var(--foreground))', margin: 0 }}>Quotes</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button size="small" onClick={() => setView('settings')} sx={{ color: 'hsl(var(--muted-foreground))' }}>Settings</Button>
          <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={() => { resetForm(); setView('create'); }} sx={{ background: '#7c5cfc', '&:hover': { background: '#6a4de0' } }}>
            New Quote
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        <div className="kpi-card"><div className="kpi-label">Quoted this month</div><div className="kpi-value">£{kpis.quotedThisMonth.toLocaleString('en-GB', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</div></div>
        <div className="kpi-card"><div className="kpi-label">Acceptance rate</div><div className="kpi-value">{kpis.acceptanceRate}%</div></div>
        <div className="kpi-card"><div className="kpi-label">Avg quote value</div><div className="kpi-value">£{kpis.avgValue.toLocaleString('en-GB', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</div></div>
        <div className="kpi-card"><div className="kpi-label">Outstanding</div><div className="kpi-value">{kpis.outstanding} quotes</div></div>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        {['', 'draft', 'sent', 'accepted', 'declined', 'invoiced'].map(s => (
          <Chip key={s || 'all'} label={s || 'All'} size="small"
            onClick={() => setStatusFilter(s)}
            sx={{
              textTransform: 'capitalize',
              background: statusFilter === s ? '#7c5cfc' : 'rgba(255,255,255,0.06)',
              color: statusFilter === s ? '#fff' : 'hsl(var(--foreground))',
              fontWeight: 500, fontSize: 12, cursor: 'pointer',
              '&:hover': { background: statusFilter === s ? '#6a4de0' : 'rgba(255,255,255,0.1)' },
            }}
          />
        ))}
        <div style={{ flex: 1 }} />
        <TextField size="small" placeholder="Search quotes..." value={search} onChange={e => setSearch(e.target.value)}
          InputProps={{ startAdornment: <SearchIcon sx={{ fontSize: 18, mr: 0.5, color: 'hsl(var(--muted-foreground))' }} />, endAdornment: search ? <IconButton size="small" onClick={() => setSearch('')}><ClearIcon sx={{ fontSize: 16 }} /></IconButton> : null }}
          sx={{ width: 220 }}
        />
        <FormControlLabel control={<Switch size="small" checked={groupByProject} onChange={e => setGroupByProject(e.target.checked)} />} label={<span style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))' }}>Group by project</span>} />
      </div>

      {/* Quote List */}
      {loading ? (
        <LoadingMessage messages={["Loading your quotes..."]} icon="📋" />
      ) : filteredQuotes.length === 0 ? (
        <div className="glass-card" style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📝</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 4 }}>No quotes yet</div>
          <div style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))', marginBottom: 16 }}>Create your first quote manually or describe a job and let AI price it up for you.</div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
            <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={() => { resetForm(); setFormMode('manual'); setView('create'); }} sx={{ background: '#7c5cfc', '&:hover': { background: '#6a4de0' } }}>Create Quote</Button>
            <Button size="small" variant="outlined" startIcon={<AIIcon />} onClick={() => { resetForm(); setView('create'); }} sx={{ borderColor: '#7c5cfc', color: '#7c5cfc' }}>AI Quote</Button>
          </div>
        </div>
      ) : groupByProject && groupedByProject ? (
        Object.entries(groupedByProject).map(([project, projectQuotes]) => (
          <div key={project} style={{ marginBottom: 20 }}>
            {project !== '(No project)' && (
              <div style={{ fontSize: 13, fontWeight: 600, color: '#7c5cfc', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                📁 {project}
                <span style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))', fontWeight: 400 }}>
                  — £{projectQuotes.reduce((s, q) => s + q.total, 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })} total
                </span>
              </div>
            )}
            {projectQuotes.map(q => <QuoteRow key={q.id} quote={q} onView={openDetail} onEdit={openEdit} onDuplicate={handleDuplicate} onDelete={handleDeleteQuote} />)}
          </div>
        ))
      ) : (
        filteredQuotes.map(q => <QuoteRow key={q.id} quote={q} onView={openDetail} onEdit={openEdit} onDuplicate={handleDuplicate} onDelete={handleDeleteQuote} />)
      )}

      {/* Detail Drawer */}
      <Drawer anchor="right" open={detailDrawerOpen} onClose={() => setDetailDrawerOpen(false)} PaperProps={{ sx: { width: { xs: '100%', sm: 480 }, background: 'var(--glass-bg)', backdropFilter: 'blur(20px)', color: 'hsl(var(--foreground))' } }}>
        {selectedQuote && (
          <Box sx={{ p: 3 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700 }}>{selectedQuote.quote_number}</div>
                <StatusBadge status={selectedQuote.status} />
              </div>
              <IconButton onClick={() => setDetailDrawerOpen(false)}><CloseIcon /></IconButton>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{selectedQuote.job_title}</div>
            <div style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))', marginBottom: 12 }}>{selectedQuote.customer_name}</div>
            {selectedQuote.project_reference && (
              <div style={{ fontSize: 12, color: '#7c5cfc', marginBottom: 12 }}>📁 Project: {selectedQuote.project_reference}</div>
            )}

            {/* Line items by group */}
            {selectedQuote.line_items && selectedQuote.line_items.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                {Object.entries(
                  selectedQuote.line_items.reduce((acc: Record<string, LineItem[]>, item) => {
                    const g = item.group_name || 'General';
                    if (!acc[g]) acc[g] = [];
                    acc[g].push(item);
                    return acc;
                  }, {})
                ).map(([group, items]) => (
                  <div key={group} style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontWeight: 600, padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                      <span>{group}</span>
                      <span style={{ color: '#2dd48c' }}>£{items.reduce((s, i) => s + i.line_total, 0).toFixed(2)}</span>
                    </div>
                    {items.map((item, i) => (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '4px 0 4px 12px', color: 'hsl(var(--muted-foreground))' }}>
                        <span>{item.description}</span>
                        <span>{item.quantity} {item.unit} × £{item.unit_cost.toFixed(2)} = £{item.line_total.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {/* Totals */}
            <div style={{ textAlign: 'right', fontSize: 13, color: 'hsl(var(--muted-foreground))', marginBottom: 16 }}>
              <div>Subtotal: £{selectedQuote.subtotal.toFixed(2)}</div>
              <div>VAT ({selectedQuote.tax_rate}%): £{selectedQuote.tax_amount.toFixed(2)}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#2dd48c' }}>Total: £{selectedQuote.total.toFixed(2)}</div>
            </div>

            {/* PDF Actions */}
            <Divider sx={{ my: 2, borderColor: 'rgba(255,255,255,0.06)' }} />
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <Button size="small" variant="outlined" onClick={() => handlePreviewPDF(selectedQuote.id)} startIcon={<PreviewIcon />} sx={{ borderColor: 'rgba(255,255,255,0.12)', color: 'hsl(var(--foreground))' }}>Preview PDF</Button>
              <Button size="small" variant="outlined" onClick={() => handleDownloadPDF(selectedQuote.id, selectedQuote.quote_number)} startIcon={<DownloadIcon />} sx={{ borderColor: 'rgba(255,255,255,0.12)', color: 'hsl(var(--foreground))' }}>Download PDF</Button>
            </div>

            {/* Status Actions */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {selectedQuote.status === 'draft' && (
                <>
                  <Button size="small" variant="contained" onClick={() => openEdit(selectedQuote.id)} startIcon={<EditIcon />} sx={{ background: 'rgba(255,255,255,0.08)' }}>Edit</Button>
                  <Button size="small" variant="contained" onClick={() => openSendDialog(selectedQuote)} startIcon={<SendIcon />} sx={{ background: '#7c5cfc', '&:hover': { background: '#6a4de0' } }}>Send Quote</Button>
                  <Button size="small" variant="contained" onClick={() => handleStatusAction(selectedQuote.id, 'convert-to-invoice')} sx={{ background: 'rgba(45,212,196,0.15)', color: '#2dd4c4' }}>Convert to Invoice</Button>
                  <Button size="small" color="error" onClick={() => handleDeleteQuote(selectedQuote.id)} startIcon={<DeleteIcon />}>Delete</Button>
                </>
              )}
              {selectedQuote.status === 'sent' && (
                <>
                  <Button size="small" variant="contained" onClick={() => handleStatusAction(selectedQuote.id, 'accept')} sx={{ background: 'rgba(45,212,140,0.15)', color: '#2dd48c' }}>Mark Accepted</Button>
                  <Button size="small" variant="contained" onClick={() => handleStatusAction(selectedQuote.id, 'decline')} sx={{ background: 'rgba(248,113,113,0.15)', color: '#f87171' }}>Mark Declined</Button>
                  <Button size="small" onClick={() => openEdit(selectedQuote.id)} startIcon={<EditIcon />}>Edit</Button>
                  <Button size="small" onClick={() => openSendDialog(selectedQuote)} startIcon={<SendIcon />}>Resend</Button>
                  <Button size="small" variant="contained" onClick={() => handleStatusAction(selectedQuote.id, 'convert-to-invoice')} sx={{ background: 'rgba(45,212,196,0.15)', color: '#2dd4c4' }}>Convert to Invoice</Button>
                </>
              )}
              {selectedQuote.status === 'accepted' && (
                <>
                  <Button size="small" variant="contained" onClick={() => handleStatusAction(selectedQuote.id, 'convert-to-invoice')} sx={{ background: 'rgba(45,212,196,0.15)', color: '#2dd4c4' }}>Convert to Invoice</Button>
                  <Button size="small" onClick={() => openEdit(selectedQuote.id)} startIcon={<EditIcon />}>Edit</Button>
                </>
              )}
              {selectedQuote.status === 'declined' && (
                <Button size="small" variant="contained" onClick={() => handleDuplicate(selectedQuote.id)} startIcon={<DuplicateIcon />} sx={{ background: 'rgba(255,255,255,0.08)' }}>Duplicate as New</Button>
              )}
            </div>
          </Box>
        )}
      </Drawer>

      {/* Send Quote Dialog */}
      <Dialog open={sendDialogOpen} onClose={() => setSendDialogOpen(false)} maxWidth="sm" fullWidth
        PaperProps={{ sx: { background: 'var(--glass-bg, #1a1c22)', backdropFilter: 'blur(20px)', color: 'hsl(var(--foreground))', border: '1px solid rgba(255,255,255,0.08)' } }}>
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', pb: 0 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>Send Quote</span>
          <IconButton size="small" onClick={() => setSendDialogOpen(false)}><CloseIcon /></IconButton>
        </DialogTitle>
        <DialogContent>
          <Tabs value={sendTab} onChange={(_, v) => setSendTab(v)} sx={{ mb: 2, '& .MuiTab-root': { color: 'hsl(var(--muted-foreground))', minHeight: 40 }, '& .Mui-selected': { color: '#7c5cfc' }, '& .MuiTabs-indicator': { backgroundColor: '#7c5cfc' } }}>
            <Tab icon={<EmailIcon sx={{ fontSize: 18 }} />} iconPosition="start" label="Email" sx={{ textTransform: 'none', fontSize: 13 }} />
            <Tab icon={<WhatsAppIcon sx={{ fontSize: 18 }} />} iconPosition="start" label="WhatsApp" sx={{ textTransform: 'none', fontSize: 13 }} />
          </Tabs>

          {sending ? (
            <LoadingMessage messages={["Generating your professional PDF and sending it now...", "Almost there — just a moment..."]} icon="📨" rotateInterval={3000} />
          ) : sendTab === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <TextField label="Customer Email" size="small" fullWidth value={sendEmail} onChange={e => setSendEmail(e.target.value)} />
              <TextField label="Subject" size="small" fullWidth value={sendSubject} onChange={e => setSendSubject(e.target.value)} />
              <TextField label="Message" size="small" fullWidth multiline minRows={6} value={sendMessage} onChange={e => setSendMessage(e.target.value)} />
              <div style={{ fontSize: 11, color: 'hsl(var(--muted-foreground))' }}>
                <PdfIcon sx={{ fontSize: 14, verticalAlign: 'middle', mr: 0.5 }} />
                A professional PDF quote will be attached automatically.
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <TextField label="Customer Phone" size="small" fullWidth value={sendPhone} onChange={e => setSendPhone(e.target.value)} placeholder="+447..." />
              <div className="glass-card" style={{ padding: 12, fontSize: 12, color: 'hsl(var(--muted-foreground))', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                {selectedQuote && (
                  <>
                    📋 <strong>Quote {selectedQuote.quote_number}</strong>{'\n'}
                    {'\n'}
                    <strong>{selectedQuote.job_title}</strong>{'\n'}
                    {'\n'}
                    💷 <strong>Total: £{selectedQuote.total.toLocaleString('en-GB', { minimumFractionDigits: 2 })}</strong> (inc. VAT){'\n'}
                    {selectedQuote.valid_until && <>{'\n'}Valid until: {selectedQuote.valid_until}{'\n'}</>}
                    {'\n'}
                    <em>This is a text summary — PDFs cannot be sent via WhatsApp.</em>
                  </>
                )}
              </div>
            </div>
          )}
        </DialogContent>
        {!sending && (
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button onClick={() => setSendDialogOpen(false)} sx={{ color: 'hsl(var(--muted-foreground))' }}>Cancel</Button>
            {sendTab === 0 ? (
              <Button variant="contained" onClick={handleSendEmail} disabled={!sendEmail} startIcon={<EmailIcon />} sx={{ background: '#7c5cfc', '&:hover': { background: '#6a4de0' } }}>Send Email</Button>
            ) : (
              <Button variant="contained" onClick={handleSendWhatsApp} disabled={!sendPhone} startIcon={<WhatsAppIcon />} sx={{ background: '#25d366', '&:hover': { background: '#1da851' } }}>Send WhatsApp</Button>
            )}
          </DialogActions>
        )}
      </Dialog>

      {/* Snackbar */}
      <Snackbar open={snackbar.open} autoHideDuration={5000} onClose={() => setSnackbar(prev => ({ ...prev, open: false }))} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        <Alert onClose={() => setSnackbar(prev => ({ ...prev, open: false }))} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </div>
  );
}

function QuoteRow({ quote, onView, onEdit, onDuplicate, onDelete }: {
  quote: Quote;
  onView: (id: string) => void;
  onEdit: (id: string) => void;
  onDuplicate: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="glass-card" style={{ padding: '12px 16px', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }} onClick={() => onView(quote.id)}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'hsl(var(--muted-foreground))' }}>{quote.quote_number}</span>
          <StatusBadge status={quote.status} />
          {quote.project_reference && (
            <span style={{ fontSize: 11, color: '#7c5cfc', background: 'rgba(124,92,252,0.1)', padding: '1px 6px', borderRadius: 8 }}>{quote.project_reference}</span>
          )}
        </div>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{quote.job_title}</div>
        <div style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))' }}>{quote.customer_name}</div>
      </div>
      <div style={{ textAlign: 'right', flexShrink: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#2dd48c' }}>£{quote.total.toLocaleString('en-GB', { minimumFractionDigits: 2 })}</div>
        <div style={{ fontSize: 11, color: 'hsl(var(--muted-foreground))' }}>{new Date(quote.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</div>
      </div>
      <div style={{ display: 'flex', gap: 2 }} onClick={e => e.stopPropagation()}>
        <IconButton size="small" onClick={() => onEdit(quote.id)} sx={{ color: 'hsl(var(--muted-foreground))' }}><EditIcon sx={{ fontSize: 16 }} /></IconButton>
        <IconButton size="small" onClick={() => onDuplicate(quote.id)} sx={{ color: 'hsl(var(--muted-foreground))' }}><DuplicateIcon sx={{ fontSize: 16 }} /></IconButton>
        <IconButton size="small" onClick={() => onDelete(quote.id)} sx={{ color: '#f87171' }}><DeleteIcon sx={{ fontSize: 16 }} /></IconButton>
      </div>
    </div>
  );
}
