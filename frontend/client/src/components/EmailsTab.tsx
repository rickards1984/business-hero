import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Typography,
  Card,
  Chip,
  TextField,
  CircularProgress,
  Button,
  InputAdornment,
  Tooltip,
  IconButton,
  Snackbar,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import {
  Search as SearchIcon,
  Sync as SyncIcon,
  AutoAwesome as AutoAwesomeIcon,
  ChatBubbleOutline as ChatBubbleOutlineIcon,
  AttachFile as AttachFileIcon,
  MailOutline as MailOutlineIcon,
  PlaylistAdd as PlaylistAddIcon,
} from '@mui/icons-material';
import {
  fetchEmailMessages,
  runEmailSync,
  analyzeEmails,
  type EmailMessageItem,
} from '@/lib/emailApi';
import { supabase } from '@/lib/supabase';
import { TASK_CATEGORIES, TASK_PRIORITIES, getCategoryColor } from '@/lib/taskConstants';

const CATEGORIES = [
  { key: 'all', label: 'All' },
  { key: 'action_required', label: 'Action Required' },
  { key: 'awaiting_reply', label: 'Awaiting Reply' },
  { key: 'fyi', label: 'FYI' },
  { key: 'finance', label: 'Finance' },
  { key: 'newsletter', label: 'Newsletters' },
];

const TIME_RANGES = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'This Week' },
  { key: 'month', label: 'This Month' },
  { key: 'all', label: 'All Time' },
];

const PRIORITY_BORDERS: Record<string, string> = {
  action_required: '#d32f2f',
  awaiting_reply: '#ed6c02',
  fyi: '#1976d2',
  finance: '#1976d2',
  scheduling: '#1976d2',
  newsletter: '#9e9e9e',
  marketing: '#9e9e9e',
  spam: '#9e9e9e',
};

const CATEGORY_COLORS: Record<string, 'error' | 'warning' | 'info' | 'default' | 'primary' | 'success'> = {
  action_required: 'error',
  awaiting_reply: 'warning',
  fyi: 'info',
  finance: 'primary',
  scheduling: 'info',
  newsletter: 'default',
  marketing: 'default',
  spam: 'default',
};

function formatCategoryLabel(cat: string): string {
  return cat.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function formatTimestamp(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function filterByTimeRange(email: EmailMessageItem, range: string): boolean {
  if (range === 'all') return true;
  if (!email.received_at) return true;
  const received = new Date(email.received_at);
  const now = new Date();
  if (range === 'today') {
    return received.toDateString() === now.toDateString();
  }
  if (range === 'week') {
    const weekAgo = new Date(now);
    weekAgo.setDate(weekAgo.getDate() - 7);
    return received >= weekAgo;
  }
  if (range === 'month') {
    const monthAgo = new Date(now);
    monthAgo.setMonth(monthAgo.getMonth() - 1);
    return received >= monthAgo;
  }
  return true;
}

interface EmailsTabProps {
  businessId: string;
}

export default function EmailsTab({ businessId }: EmailsTabProps) {
  const navigate = useNavigate();
  const [emails, setEmails] = useState<EmailMessageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [timeRange, setTimeRange] = useState('week');
  const [searchQuery, setSearchQuery] = useState('');
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({ open: false, message: '', severity: 'info' });
  const [hasEmailAccount, setHasEmailAccount] = useState(true);

  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskSaving, setTaskSaving] = useState(false);
  const [taskForm, setTaskForm] = useState({
    title: '',
    category: 'email_followup',
    priority: 'medium',
    due_at: '',
    description: '',
    source: 'email',
    source_id: '',
  });

  const loadEmails = useCallback(async () => {
    try {
      setLoading(true);
      const params: { limit?: number; category?: string; sortBy?: string } = {
        limit: 50,
        sortBy: 'date',
      };
      if (categoryFilter !== 'all') {
        params.category = categoryFilter;
      }
      const data = await fetchEmailMessages(params);
      setEmails(data.messages || []);
      setHasEmailAccount(true);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes('No email account') || message.includes('404') || message.includes('email feature')) {
        setHasEmailAccount(false);
      }
      setEmails([]);
    } finally {
      setLoading(false);
    }
  }, [categoryFilter]);

  useEffect(() => {
    loadEmails();
  }, [loadEmails]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const result = await runEmailSync();
      setSnackbar({ open: true, message: `Synced ${result.message_count} emails`, severity: 'success' });
      await loadEmails();
    } catch {
      setSnackbar({ open: true, message: 'Sync failed — check email connection', severity: 'error' });
    } finally {
      setSyncing(false);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const unanalyzed = emails.filter(e => !e.ai_category).map(e => e.id);
      if (unanalyzed.length === 0) {
        setSnackbar({ open: true, message: 'All emails already analyzed', severity: 'info' });
        setAnalyzing(false);
        return;
      }
      const result = await analyzeEmails(unanalyzed.slice(0, 30));
      setSnackbar({ open: true, message: `Analyzed ${result.analyzed_count} emails`, severity: 'success' });
      await loadEmails();
    } catch {
      setSnackbar({ open: true, message: 'Analysis failed', severity: 'error' });
    } finally {
      setAnalyzing(false);
    }
  };

  const handleAskAria = (email: EmailMessageItem) => {
    const sender = email.from_name || email.from_email || 'unknown sender';
    const subject = email.subject || 'no subject';
    const prompt = `Check the email from ${sender} about "${subject}" and help me respond`;
    navigate(`/app/assistant/chat?prompt=${encodeURIComponent(prompt)}`);
  };

  const openCreateTaskFromEmail = (email: EmailMessageItem) => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    setTaskForm({
      title: `Follow up: ${email.subject || '(no subject)'}`,
      category: 'email_followup',
      priority: email.ai_category === 'action_required' ? 'high' : 'medium',
      due_at: tomorrow.toISOString().slice(0, 16),
      description: `Email from ${email.from_name || email.from_email || 'Unknown'}\nSubject: ${email.subject || ''}\n\n${email.ai_summary || ''}`,
      source: 'email',
      source_id: email.id,
    });
    setTaskDialogOpen(true);
  };

  const handleCreateTask = async () => {
    if (!taskForm.title.trim()) return;
    setTaskSaving(true);
    try {
      const { error: insertError } = await supabase.from('tasks').insert({
        business_id: businessId,
        title: taskForm.title.trim(),
        description: taskForm.description.trim() || null,
        category: taskForm.category,
        priority: taskForm.priority,
        due_at: taskForm.due_at ? new Date(taskForm.due_at).toISOString() : null,
        source: taskForm.source,
        source_id: taskForm.source_id || null,
        status: 'open',
      });
      if (insertError) throw insertError;
      setSnackbar({ open: true, message: `Task "${taskForm.title}" created`, severity: 'success' });
      setTaskDialogOpen(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create task';
      setSnackbar({ open: true, message: msg, severity: 'error' });
    } finally {
      setTaskSaving(false);
    }
  };

  const filteredEmails = emails
    .filter(e => filterByTimeRange(e, timeRange))
    .filter(e => {
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        (e.from_name || '').toLowerCase().includes(q) ||
        (e.from_email || '').toLowerCase().includes(q) ||
        (e.subject || '').toLowerCase().includes(q) ||
        (e.ai_summary || '').toLowerCase().includes(q) ||
        (e.snippet || '').toLowerCase().includes(q)
      );
    });

  const counts = {
    total: filteredEmails.length,
    unread: filteredEmails.filter(e => e.is_unread).length,
    action_required: filteredEmails.filter(e => e.ai_category === 'action_required').length,
    awaiting_reply: filteredEmails.filter(e => e.ai_category === 'awaiting_reply').length,
    fyi: filteredEmails.filter(e => e.ai_category === 'fyi').length,
    finance: filteredEmails.filter(e => e.ai_category === 'finance').length,
    newsletter: filteredEmails.filter(e => e.ai_category === 'newsletter' || e.ai_category === 'marketing').length,
  };

  if (!hasEmailAccount) {
    return (
      <Box sx={{ textAlign: 'center', py: 8 }}>
        <MailOutlineIcon sx={{ fontSize: 64, color: 'text.disabled', mb: 2 }} />
        <Typography variant="h6" color="text.secondary" gutterBottom>
          Connect your email to get started
        </Typography>
        <Typography variant="body2" color="text.disabled" sx={{ mb: 3 }}>
          Your AI-categorized inbox will appear here.
        </Typography>
        <Button
          variant="contained"
          onClick={() => navigate('/app/settings/email')}
        >
          Connect Email →
        </Button>
      </Box>
    );
  }

  return (
    <Box>
      {/* Header row: Sync + Analyze */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, flexWrap: 'wrap', gap: 2 }}>
        <Typography variant="h6" fontWeight={600}>
          Inbox
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            size="small"
            variant="outlined"
            startIcon={syncing ? <CircularProgress size={16} /> : <SyncIcon />}
            onClick={handleSync}
            disabled={syncing}
          >
            {syncing ? 'Syncing...' : 'Sync'}
          </Button>
          <Button
            size="small"
            variant="outlined"
            startIcon={analyzing ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
            onClick={handleAnalyze}
            disabled={analyzing}
          >
            {analyzing ? 'Analyzing...' : 'Analyze All'}
          </Button>
        </Box>
      </Box>

      {/* Summary stat cards */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Card sx={{ flex: '1 1 150px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="error.main">
            {counts.action_required}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Action Required
          </Typography>
        </Card>
        <Card sx={{ flex: '1 1 150px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="warning.main">
            {counts.awaiting_reply}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Awaiting Reply
          </Typography>
        </Card>
        <Card sx={{ flex: '1 1 150px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="primary.main">
            {counts.unread}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Unread
          </Typography>
        </Card>
      </Box>

      {/* Category filter chips */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {CATEGORIES.map(cat => (
          <Chip
            key={cat.key}
            label={`${cat.label} (${cat.key === 'all' ? counts.total : (counts as Record<string, number>)[cat.key] || 0})`}
            onClick={() => setCategoryFilter(cat.key)}
            color={categoryFilter === cat.key ? 'primary' : 'default'}
            variant={categoryFilter === cat.key ? 'filled' : 'outlined'}
          />
        ))}
      </Box>

      {/* Search bar */}
      <TextField
        size="small"
        fullWidth
        placeholder="Search by sender, subject, or summary..."
        value={searchQuery}
        onChange={e => setSearchQuery(e.target.value)}
        sx={{ mb: 2 }}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon color="action" />
            </InputAdornment>
          ),
        }}
      />

      {/* Time range chips */}
      <Box sx={{ display: 'flex', gap: 1, mb: 3 }}>
        {TIME_RANGES.map(tr => (
          <Chip
            key={tr.key}
            label={tr.label}
            size="small"
            onClick={() => setTimeRange(tr.key)}
            color={timeRange === tr.key ? 'primary' : 'default'}
            variant={timeRange === tr.key ? 'filled' : 'outlined'}
          />
        ))}
      </Box>

      {/* Email list */}
      {loading ? (
        <Box sx={{ textAlign: 'center', py: 6 }}>
          <CircularProgress />
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            Loading emails...
          </Typography>
        </Box>
      ) : filteredEmails.length === 0 ? (
        <Box sx={{ textAlign: 'center', py: 6 }}>
          <MailOutlineIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
          <Typography variant="body1" color="text.secondary">
            {searchQuery ? 'No emails match your search' : 'No emails in this view'}
          </Typography>
        </Box>
      ) : (
        <Box>
          {filteredEmails.map(email => {
            const category = email.ai_category || 'fyi';
            const borderColor = PRIORITY_BORDERS[category] || '#9e9e9e';
            const chipColor = CATEGORY_COLORS[category] || 'default';

            return (
              <Card
                key={email.id}
                sx={{
                  p: 2,
                  mb: 2,
                  borderLeft: 4,
                  borderLeftColor: borderColor,
                  opacity: email.is_unread ? 1 : 0.85,
                  '&:hover': { boxShadow: 2 },
                  transition: 'box-shadow 0.2s',
                }}
              >
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    {/* Line 1: Sender + timestamp */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      <Box
                        sx={{
                          width: 8,
                          height: 8,
                          borderRadius: '50%',
                          bgcolor: borderColor,
                          flexShrink: 0,
                        }}
                      />
                      <Typography
                        variant="subtitle2"
                        fontWeight={email.is_unread ? 700 : 500}
                        noWrap
                        sx={{ flex: 1 }}
                      >
                        {email.from_name || email.from_email || 'Unknown'}
                      </Typography>
                      {email.has_attachments && (
                        <AttachFileIcon sx={{ fontSize: 16, color: 'text.disabled' }} />
                      )}
                      <Typography variant="caption" color="text.disabled" sx={{ flexShrink: 0 }}>
                        {formatTimestamp(email.received_at)}
                      </Typography>
                    </Box>

                    {/* Line 2: Subject + category badge */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      <Typography
                        variant="body2"
                        fontWeight={email.is_unread ? 600 : 400}
                        noWrap
                        sx={{ flex: 1 }}
                      >
                        {email.subject || '(no subject)'}
                      </Typography>
                      {email.ai_category && (
                        <Chip
                          label={formatCategoryLabel(email.ai_category)}
                          size="small"
                          color={chipColor}
                          variant="outlined"
                          sx={{ height: 20, fontSize: '0.7rem' }}
                        />
                      )}
                    </Box>

                    {/* Line 3: AI summary or snippet */}
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      noWrap
                      sx={{
                        display: '-webkit-box',
                        WebkitLineClamp: 1,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                        mb: 0.5,
                      }}
                    >
                      {email.ai_summary || email.snippet || ''}
                    </Typography>
                  </Box>

                  {/* Action buttons */}
                  <Box sx={{ ml: 1, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Tooltip title="Create a follow-up task">
                      <Button
                        size="small"
                        variant="text"
                        startIcon={<PlaylistAddIcon sx={{ fontSize: 16 }} />}
                        onClick={() => openCreateTaskFromEmail(email)}
                        sx={{
                          textTransform: 'none',
                          fontSize: '0.75rem',
                          color: 'text.secondary',
                          '&:hover': { color: 'primary.main' },
                        }}
                      >
                        Create Task
                      </Button>
                    </Tooltip>
                    <Tooltip title="Ask Aria about this email">
                      <Button
                        size="small"
                        variant="text"
                        startIcon={<ChatBubbleOutlineIcon sx={{ fontSize: 16 }} />}
                        onClick={() => handleAskAria(email)}
                        sx={{
                          textTransform: 'none',
                          fontSize: '0.75rem',
                          color: 'text.secondary',
                          '&:hover': { color: 'primary.main' },
                        }}
                      >
                        Ask Aria
                      </Button>
                    </Tooltip>
                  </Box>
                </Box>
              </Card>
            );
          })}
        </Box>
      )}

      {/* Create Task from Email Dialog */}
      <Dialog open={taskDialogOpen} onClose={() => setTaskDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Task from Email</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Task Title"
            fullWidth
            variant="outlined"
            value={taskForm.title}
            onChange={e => setTaskForm(prev => ({ ...prev, title: e.target.value }))}
            sx={{ mb: 2, mt: 1 }}
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
                onClick={() => setTaskForm(prev => ({ ...prev, category: cat.id }))}
                sx={{
                  bgcolor: taskForm.category === cat.id ? cat.color : undefined,
                  color: taskForm.category === cat.id ? '#fff' : undefined,
                  borderColor: taskForm.category === cat.id ? cat.color : undefined,
                  '&:hover': { opacity: 0.85 },
                }}
                variant={taskForm.category === cat.id ? 'filled' : 'outlined'}
              />
            ))}
          </Box>

          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <FormControl size="small" sx={{ flex: 1 }}>
              <InputLabel>Priority</InputLabel>
              <Select
                value={taskForm.priority}
                label="Priority"
                onChange={e => setTaskForm(prev => ({ ...prev, priority: e.target.value }))}
              >
                {TASK_PRIORITIES.map(p => (
                  <MenuItem key={p.id} value={p.id}>{p.icon} {p.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Due Date"
              type="datetime-local"
              size="small"
              sx={{ flex: 1 }}
              value={taskForm.due_at}
              onChange={e => setTaskForm(prev => ({ ...prev, due_at: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
          </Box>

          <TextField
            label="Notes"
            fullWidth
            multiline
            rows={3}
            variant="outlined"
            value={taskForm.description}
            onChange={e => setTaskForm(prev => ({ ...prev, description: e.target.value }))}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTaskDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateTask}
            variant="contained"
            disabled={taskSaving || !taskForm.title.trim()}
          >
            {taskSaving ? <CircularProgress size={20} /> : 'Create Task'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar(s => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar(s => ({ ...s, open: false }))}
          severity={snackbar.severity}
          variant="filled"
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
