import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Checkbox,
  Container,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Ticket {
  id: string;
  business_id: string;
  business_name?: string;
  user_id?: string;
  status: string;
  priority: string;
  category?: string;
  subject?: string;
  ai_resolved: boolean;
  ai_confidence?: number;
  escalated_at?: string;
  escalation_reason?: string;
  assigned_to?: string;
  admin_notes?: string;
  resolved_at?: string;
  closed_at?: string;
  last_message_at?: string;
  last_admin_reply_at?: string;
  created_at: string;
  updated_at: string;
  messages?: Message[];
  businesses?: { name: string };
}

interface Message {
  id: string;
  conversation_id: string;
  sender_type: 'user' | 'ai' | 'admin';
  sender_id?: string;
  sender_name?: string;
  content: string;
  is_internal: boolean;
  created_at: string;
}

interface Article {
  id: string;
  title: string;
  content: string;
  summary?: string;
  category: string;
  tags?: string[];
  is_published: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

interface Stats {
  open_tickets: number;
  awaiting_admin: number;
  in_progress: number;
  awaiting_reply: number;
  resolved_total: number;
  ai_resolved_total: number;
  created_today: number;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const STATUS_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'escalated', label: 'Escalated' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'awaiting_reply', label: 'Awaiting Reply' },
  { key: 'ai_chat', label: 'AI Chat' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'closed', label: 'Closed' },
];

const PRIORITY_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'urgent', label: 'Urgent' },
  { key: 'high', label: 'High' },
  { key: 'normal', label: 'Normal' },
  { key: 'low', label: 'Low' },
];

const ARTICLE_CATEGORIES = [
  'getting-started',
  'email',
  'receptionist',
  'invoicing',
  'accounting',
  'aria',
  'billing',
  'troubleshooting',
  'general',
];

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  ai_chat:        { label: 'AI Chat',        cls: 'bh-badge bh-badge--info' },
  escalated:      { label: 'Escalated',      cls: 'bh-badge bh-badge--warning' },
  in_progress:    { label: 'In Progress',    cls: 'bh-badge bh-badge--info' },
  awaiting_reply: { label: 'Awaiting Reply', cls: 'bh-badge bh-badge--neutral' },
  resolved:       { label: 'Resolved',       cls: 'bh-badge bh-badge--success' },
  closed:         { label: 'Closed',         cls: 'bh-badge bh-badge--neutral' },
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function bizName(t: Ticket): string {
  if (t.business_name) return t.business_name;
  if (t.businesses?.name) return t.businesses.name;
  return t.business_id?.slice(0, 8) ?? 'Unknown';
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function AdminSupportDashboard() {
  const navigate = useNavigate();
  const { user, isAdmin, loading: authLoading, adminLoading } = useAuth();

  /* ---------- Auth guard ---------- */
  useEffect(() => {
    if (!authLoading && !user) navigate('/login');
    else if (!authLoading && !adminLoading && !isAdmin) navigate('/app');
  }, [user, isAdmin, authLoading, adminLoading, navigate]);

  /* ---------- State ---------- */
  const [stats, setStats] = useState<Stats | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [articles, setArticles] = useState<Article[]>([]);

  const [statusFilter, setStatusFilter] = useState('all');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [loadingTickets, setLoadingTickets] = useState(true);

  // Ticket detail
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [detailMessages, setDetailMessages] = useState<Message[]>([]);
  const [replyText, setReplyText] = useState('');
  const [isInternal, setIsInternal] = useState(false);
  const [sendingReply, setSendingReply] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [adminNotes, setAdminNotes] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // KB article editor
  const [articleModalOpen, setArticleModalOpen] = useState(false);
  const [editingArticle, setEditingArticle] = useState<Article | null>(null);
  const [articleForm, setArticleForm] = useState({
    title: '',
    content: '',
    summary: '',
    category: 'general',
    tags: '',
    is_published: true,
  });
  const [savingArticle, setSavingArticle] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  /* ---------- Fetch helpers ---------- */

  const fetchStats = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/admin/support/stats');
      setStats(await res.json());
    } catch { /* silent */ }
  }, []);

  const fetchTickets = useCallback(async () => {
    setLoadingTickets(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.set('status', statusFilter);
      if (priorityFilter !== 'all') params.set('priority', priorityFilter);
      const res = await apiRequest('GET', `/v1/admin/support/tickets?${params}`);
      setTickets(await res.json());
    } catch { /* silent */ }
    setLoadingTickets(false);
  }, [statusFilter, priorityFilter]);

  const fetchArticles = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/admin/support/articles');
      setArticles(await res.json());
    } catch { /* silent */ }
  }, []);

  const fetchTicketDetail = useCallback(async (id: string) => {
    try {
      const res = await apiRequest('GET', `/v1/admin/support/tickets/${id}`);
      const data: Ticket = await res.json();
      setSelectedTicket(data);
      setDetailMessages(data.messages ?? []);
      setAdminNotes(data.admin_notes ?? '');
    } catch { /* silent */ }
  }, []);

  /* ---------- Effects ---------- */

  useEffect(() => {
    if (user && isAdmin) {
      fetchStats();
      fetchArticles();
    }
  }, [user, isAdmin, fetchStats, fetchArticles]);

  useEffect(() => {
    if (user && isAdmin) fetchTickets();
  }, [user, isAdmin, fetchTickets]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [detailMessages]);

  /* ---------- Ticket actions ---------- */

  const openTicketDetail = (t: Ticket) => {
    setReplyText('');
    setIsInternal(false);
    fetchTicketDetail(t.id);
  };

  const closeDetail = () => {
    setSelectedTicket(null);
    setDetailMessages([]);
  };

  const handleUpdateStatus = async (newStatus: string) => {
    if (!selectedTicket) return;
    try {
      await apiRequest('PUT', `/v1/admin/support/tickets/${selectedTicket.id}/status`, {
        status: newStatus,
      });
      setSelectedTicket((prev) => (prev ? { ...prev, status: newStatus } : prev));
      fetchTickets();
      fetchStats();
    } catch { /* silent */ }
  };

  const handleUpdatePriority = async (newPriority: string) => {
    if (!selectedTicket) return;
    try {
      await apiRequest('PUT', `/v1/admin/support/tickets/${selectedTicket.id}/status`, {
        status: selectedTicket.status,
        priority: newPriority,
      });
      setSelectedTicket((prev) => (prev ? { ...prev, priority: newPriority } : prev));
      fetchTickets();
    } catch { /* silent */ }
  };

  const handleSendReply = async () => {
    if (!selectedTicket || !replyText.trim()) return;
    setSendingReply(true);
    try {
      await apiRequest('POST', `/v1/admin/support/tickets/${selectedTicket.id}/reply`, {
        content: replyText.trim(),
        is_internal: isInternal,
      });
      setReplyText('');
      setIsInternal(false);
      await fetchTicketDetail(selectedTicket.id);
      fetchTickets();
    } catch { /* silent */ }
    setSendingReply(false);
  };

  const handleAiDraft = async () => {
    if (!selectedTicket) return;
    setDraftLoading(true);
    try {
      const res = await apiRequest('POST', `/v1/admin/support/tickets/${selectedTicket.id}/ai-draft`);
      const data = await res.json();
      if (data.draft) setReplyText(data.draft);
    } catch { /* silent */ }
    setDraftLoading(false);
  };

  const handleSaveNotes = async () => {
    if (!selectedTicket) return;
    setSavingNotes(true);
    try {
      await apiRequest('PUT', `/v1/admin/support/tickets/${selectedTicket.id}/status`, {
        status: selectedTicket.status,
        admin_notes: adminNotes,
      });
    } catch { /* silent */ }
    setSavingNotes(false);
  };

  const handleMarkResolved = async () => {
    if (!selectedTicket) return;
    await handleUpdateStatus('resolved');
    closeDetail();
  };

  /* ---------- KB actions ---------- */

  const openNewArticle = () => {
    setEditingArticle(null);
    setArticleForm({ title: '', content: '', summary: '', category: 'general', tags: '', is_published: true });
    setArticleModalOpen(true);
  };

  const openEditArticle = (a: Article) => {
    setEditingArticle(a);
    setArticleForm({
      title: a.title,
      content: a.content,
      summary: a.summary ?? '',
      category: a.category,
      tags: (a.tags ?? []).join(', '),
      is_published: a.is_published,
    });
    setArticleModalOpen(true);
  };

  const handleSaveArticle = async () => {
    setSavingArticle(true);
    const tags = articleForm.tags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    const body = {
      title: articleForm.title,
      content: articleForm.content,
      summary: articleForm.summary || null,
      category: articleForm.category,
      tags,
      is_published: articleForm.is_published,
    };
    try {
      if (editingArticle) {
        await apiRequest('PUT', `/v1/admin/support/articles/${editingArticle.id}`, body);
      } else {
        await apiRequest('POST', '/v1/admin/support/articles', body);
      }
      setArticleModalOpen(false);
      fetchArticles();
    } catch { /* silent */ }
    setSavingArticle(false);
  };

  const handleTogglePublish = async (a: Article) => {
    try {
      await apiRequest('PUT', `/v1/admin/support/articles/${a.id}`, {
        is_published: !a.is_published,
      });
      fetchArticles();
    } catch { /* silent */ }
  };

  const handleDeleteArticle = async () => {
    if (!deleteConfirmId) return;
    try {
      await apiRequest('DELETE', `/v1/admin/support/articles/${deleteConfirmId}`);
      setDeleteConfirmId(null);
      fetchArticles();
    } catch { /* silent */ }
  };

  /* ---------- AI resolution rate ---------- */

  const aiRate =
    stats && stats.resolved_total + stats.ai_resolved_total > 0
      ? Math.round((stats.ai_resolved_total / (stats.resolved_total + stats.ai_resolved_total)) * 100)
      : 0;

  /* ---------- Render ---------- */

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
        <Button variant="outlined" startIcon={<ArrowBackIcon />} onClick={() => navigate('/admin')}>
          Back to Admin
        </Button>
        <Typography variant="h5" sx={{ fontWeight: 600 }}>Support Dashboard</Typography>
      </Box>

      {/* Stat cards */}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4, 1fr)' }, gap: 2, mb: 4 }}>
        <div className={`bh-stat-card${(stats?.awaiting_admin ?? 0) > 0 ? ' bh-stat-card--danger' : ''}`}>
          <div className="bh-stat-card__value">{stats?.awaiting_admin ?? '–'}</div>
          <div className="bh-stat-card__label">Awaiting Admin</div>
        </div>
        <div className="bh-stat-card">
          <div className="bh-stat-card__value">{stats?.in_progress ?? '–'}</div>
          <div className="bh-stat-card__label">In Progress</div>
        </div>
        <div className="bh-stat-card bh-stat-card--success">
          <div className="bh-stat-card__value">{aiRate}%</div>
          <div className="bh-stat-card__label">AI Resolution Rate</div>
        </div>
        <div className="bh-stat-card bh-stat-card--primary">
          <div className="bh-stat-card__value">{stats?.open_tickets ?? '–'}</div>
          <div className="bh-stat-card__label">Total Open</div>
        </div>
      </Box>

      {/* Filters */}
      <Box sx={{ mb: 1, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            className={`bh-pill${statusFilter === f.key ? ' bh-pill--active' : ''}`}
            onClick={() => setStatusFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </Box>
      <Box sx={{ mb: 3, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {PRIORITY_FILTERS.map((f) => (
          <button
            key={f.key}
            className={`bh-pill${priorityFilter === f.key ? ' bh-pill--active' : ''}`}
            onClick={() => setPriorityFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </Box>

      {/* Ticket list */}
      <Paper sx={{ border: '1px solid var(--color-neutral-100)', boxShadow: 'var(--shadow-sm)', mb: 5, overflow: 'hidden' }} elevation={0}>
        {loadingTickets ? (
          <Box sx={{ p: 4, textAlign: 'center', color: 'var(--color-neutral-400)' }}>Loading tickets…</Box>
        ) : tickets.length === 0 ? (
          <Box sx={{ p: 4, textAlign: 'center', color: 'var(--color-neutral-400)' }}>No tickets match the current filters.</Box>
        ) : (
          tickets.map((t) => {
            const badge = STATUS_BADGE[t.status] ?? STATUS_BADGE.closed;
            return (
              <div key={t.id} className="support-ticket-card" onClick={() => openTicketDetail(t)}>
                <div className="support-ticket-card__header">
                  <span className={`support-ticket-card__priority support-ticket-card__priority--${t.priority}`} />
                  {t.priority === 'urgent' && (
                    <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--color-danger-500)', textTransform: 'uppercase' }}>
                      Urgent
                    </span>
                  )}
                  {t.priority === 'high' && (
                    <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-warning-600)', textTransform: 'uppercase' }}>
                      High
                    </span>
                  )}
                  <span className="support-ticket-card__subject">
                    {t.subject || 'Support conversation'}
                  </span>
                  <span className={badge.cls}>{badge.label}</span>
                </div>
                <div className="support-ticket-card__meta">
                  <span>{bizName(t)}</span>
                  <span>·</span>
                  {t.category && <><span>{t.category}</span><span>·</span></>}
                  <span>{timeAgo(t.updated_at)}</span>
                  {t.status === 'ai_chat' && <span title="AI handling">🤖 AI handling</span>}
                  {t.ai_resolved && <span title="AI resolved">✅ AI resolved</span>}
                </div>
              </div>
            );
          })
        )}
      </Paper>

      {/* Knowledge Base */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h6" sx={{ fontWeight: 600 }}>
          📚 Knowledge Base ({articles.length} articles)
        </Typography>
        <Button variant="contained" size="small" onClick={openNewArticle}>
          + New Article
        </Button>
      </Box>

      <Paper sx={{ border: '1px solid var(--color-neutral-100)', boxShadow: 'var(--shadow-sm)', overflow: 'hidden' }} elevation={0}>
        {articles.length === 0 ? (
          <Box sx={{ p: 4, textAlign: 'center', color: 'var(--color-neutral-400)' }}>
            No knowledge base articles yet. Create one to help the AI answer support questions.
          </Box>
        ) : (
          articles.map((a) => (
            <div key={a.id} className="admin-support-kb-row">
              <span className="admin-support-kb-row__title">{a.title}</span>
              <span className="admin-support-kb-row__cat">{a.category}</span>
              <span className={a.is_published ? 'bh-badge bh-badge--success' : 'bh-badge bh-badge--neutral'}>
                {a.is_published ? 'Published' : 'Draft'}
              </span>
              <div className="admin-support-kb-row__actions">
                <Button size="small" onClick={() => openEditArticle(a)}>Edit</Button>
                <Button size="small" onClick={() => handleTogglePublish(a)}>
                  {a.is_published ? 'Unpublish' : 'Publish'}
                </Button>
                <Button size="small" color="error" onClick={() => setDeleteConfirmId(a.id)}>Delete</Button>
              </div>
            </div>
          ))
        )}
      </Paper>

      {/* ================================================================ */}
      {/*  TICKET DETAIL PANEL                                             */}
      {/* ================================================================ */}

      {/* Overlay */}
      <div
        className={`support-panel-overlay${selectedTicket ? ' support-panel-overlay--open' : ''}`}
        onClick={closeDetail}
      />

      {/* Panel */}
      <div className={`admin-support-detail-panel${selectedTicket ? ' admin-support-detail-panel--open' : ''}`}>
        {selectedTicket && (
          <>
            {/* Header */}
            <div className="support-panel__header">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0, fontSize: 'var(--text-lg)', fontWeight: 600 }}>
                <button className="support-panel__back" onClick={closeDetail} style={{ marginBottom: 0 }}>← Back</button>
                Ticket Detail
              </h3>
              <button className="support-panel__close" onClick={closeDetail}>✕</button>
            </div>

            {/* Ticket info */}
            <Box sx={{ px: 3, pt: 3, pb: 2, borderBottom: '1px solid var(--color-neutral-100)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 0.5 }}>
                {selectedTicket.subject || 'Support conversation'}
              </Typography>
              <Typography variant="caption" sx={{ color: 'var(--color-neutral-500)', display: 'block', mb: 2 }}>
                {bizName(selectedTicket)}
                {selectedTicket.category && ` · ${selectedTicket.category}`}
                {` · Created ${new Date(selectedTicket.created_at).toLocaleString()}`}
              </Typography>
              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <FormControl size="small" sx={{ minWidth: 140 }}>
                  <InputLabel>Status</InputLabel>
                  <Select
                    value={selectedTicket.status}
                    label="Status"
                    onChange={(e) => handleUpdateStatus(e.target.value)}
                  >
                    {STATUS_FILTERS.filter((f) => f.key !== 'all').map((f) => (
                      <MenuItem key={f.key} value={f.key}>{f.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" sx={{ minWidth: 120 }}>
                  <InputLabel>Priority</InputLabel>
                  <Select
                    value={selectedTicket.priority}
                    label="Priority"
                    onChange={(e) => handleUpdatePriority(e.target.value)}
                  >
                    {PRIORITY_FILTERS.filter((f) => f.key !== 'all').map((f) => (
                      <MenuItem key={f.key} value={f.key}>{f.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Box>
            </Box>

            {/* Conversation */}
            <Box sx={{ flex: 1, overflowY: 'auto', px: 3, py: 2 }}>
              <Typography
                variant="overline"
                sx={{ color: 'var(--color-neutral-400)', fontWeight: 600, fontSize: 'var(--text-xs)', mb: 1, display: 'block' }}
              >
                💬 Conversation
              </Typography>

              <div className="support-messages">
                {detailMessages.map((m) => {
                  if (m.is_internal) {
                    return (
                      <div key={m.id} className="support-msg--internal">
                        {m.content}
                        <div style={{ fontSize: '0.625rem', color: 'var(--color-warning-500)', marginTop: '4px', fontStyle: 'normal' }}>
                          {m.sender_name} · {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    );
                  }

                  const isUser = m.sender_type === 'user';
                  const cls = isUser ? 'support-msg--user' : m.sender_type === 'admin' ? 'support-msg--admin' : 'support-msg--ai';

                  return (
                    <div key={m.id} className={cls}>
                      {!isUser && (
                        <div className="support-msg__sender">
                          {m.sender_type === 'admin' ? '👤' : '🤖'} {m.sender_name || 'Support'}
                          <span style={{ marginLeft: 'auto', fontWeight: 400 }}>
                            {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                      )}
                      {isUser && (
                        <div className="support-msg__sender" style={{ color: 'rgba(255,255,255,0.7)' }}>
                          👤 {m.sender_name || 'User'}
                          <span style={{ marginLeft: 'auto', fontWeight: 400 }}>
                            {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                      )}
                      <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
                    </div>
                  );
                })}
                <div ref={chatEndRef} />
              </div>

              {/* Admin notes */}
              <Box sx={{ mt: 3, pt: 2, borderTop: '1px solid var(--color-neutral-100)' }}>
                <Typography variant="overline" sx={{ color: 'var(--color-neutral-400)', fontWeight: 600, fontSize: 'var(--text-xs)', mb: 1, display: 'block' }}>
                  Admin Notes (internal)
                </Typography>
                <TextField
                  size="small"
                  multiline
                  minRows={2}
                  fullWidth
                  placeholder="Notes not visible to user…"
                  value={adminNotes}
                  onChange={(e) => setAdminNotes(e.target.value)}
                />
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
                  <Button size="small" variant="outlined" onClick={handleSaveNotes} disabled={savingNotes}>
                    {savingNotes ? 'Saving…' : 'Save Notes'}
                  </Button>
                </Box>
              </Box>
            </Box>

            {/* Reply area */}
            <div className="admin-support-reply-area">
              <Box sx={{ mb: 1, display: 'flex', gap: 1 }}>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={handleAiDraft}
                  disabled={draftLoading}
                >
                  {draftLoading ? 'Generating…' : '🤖 Generate AI Draft'}
                </Button>
              </Box>
              <textarea
                placeholder="Type your reply…"
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
              />
              <Box sx={{ mt: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}>
                <FormControlLabel
                  control={<Checkbox size="small" checked={isInternal} onChange={(e) => setIsInternal(e.target.checked)} />}
                  label={<Typography variant="caption">Internal note (not visible to user)</Typography>}
                />
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button variant="contained" size="small" onClick={handleSendReply} disabled={sendingReply || !replyText.trim()}>
                    {sendingReply ? 'Sending…' : 'Send Reply'}
                  </Button>
                  <Button variant="outlined" size="small" color="success" onClick={handleMarkResolved}>
                    Mark Resolved
                  </Button>
                </Box>
              </Box>
            </div>
          </>
        )}
      </div>

      {/* ================================================================ */}
      {/*  ARTICLE EDITOR MODAL                                            */}
      {/* ================================================================ */}

      <Dialog open={articleModalOpen} onClose={() => setArticleModalOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{editingArticle ? 'Edit Article' : 'New Article'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
          <TextField
            label="Title"
            required
            fullWidth
            value={articleForm.title}
            onChange={(e) => setArticleForm({ ...articleForm, title: e.target.value })}
          />
          <FormControl fullWidth>
            <InputLabel>Category</InputLabel>
            <Select
              value={articleForm.category}
              label="Category"
              onChange={(e) => setArticleForm({ ...articleForm, category: e.target.value })}
            >
              {ARTICLE_CATEGORIES.map((c) => (
                <MenuItem key={c} value={c}>{c}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Summary (shown in article list)"
            fullWidth
            value={articleForm.summary}
            onChange={(e) => setArticleForm({ ...articleForm, summary: e.target.value })}
          />
          <TextField
            label="Content"
            required
            fullWidth
            multiline
            minRows={12}
            value={articleForm.content}
            onChange={(e) => setArticleForm({ ...articleForm, content: e.target.value })}
            inputProps={{ style: { minHeight: 300, fontFamily: 'var(--font-sans)' } }}
          />
          <TextField
            label="Tags (comma separated)"
            fullWidth
            value={articleForm.tags}
            onChange={(e) => setArticleForm({ ...articleForm, tags: e.target.value })}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={articleForm.is_published}
                onChange={(e) => setArticleForm({ ...articleForm, is_published: e.target.checked })}
              />
            }
            label="Published"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setArticleModalOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSaveArticle}
            disabled={savingArticle || !articleForm.title.trim() || !articleForm.content.trim()}
          >
            {savingArticle ? 'Saving…' : 'Save Article'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={!!deleteConfirmId} onClose={() => setDeleteConfirmId(null)}>
        <DialogTitle>Delete Article</DialogTitle>
        <DialogContent>
          <Typography>Are you sure you want to delete this article? This action cannot be undone.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmId(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteArticle}>Delete</Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
