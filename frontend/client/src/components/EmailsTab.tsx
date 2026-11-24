import { useState, useEffect, useCallback, useRef } from 'react';
import LoadingMessage from '@/components/LoadingMessage';
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
  AutoAwesome as AutoAwesomeIcon,
  ChatBubbleOutline as ChatBubbleOutlineIcon,
  AttachFile as AttachFileIcon,
  MailOutline as MailOutlineIcon,
  PlaylistAdd as PlaylistAddIcon,
} from '@mui/icons-material';
import {
  fetchEmailMessages,
  analyzeEmails,
  fetchSortingStatus,
  type SortingStatus,
  type EmailMessageItem,
} from '@/lib/emailApi';
import { apiRequest } from '@/lib/queryClient';
import { supabase } from '@/lib/supabase';
import { TASK_CATEGORIES, TASK_PRIORITIES } from '@/lib/taskConstants';
import { CATEGORY_BORDER, CATEGORY_CHIP, INBOX_CATEGORIES, categoryLabel, isImportant } from '@/lib/inboxCategories';

// ARIA-1a: Mike's categories, plus All and Important (the one rule).
const CATEGORIES = [
  { key: 'all', label: 'All' },
  { key: 'important', label: 'Important' },
  ...INBOX_CATEGORIES,
];

const TIME_RANGES = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'This Week' },
  { key: 'month', label: 'This Month' },
  { key: 'all', label: 'All Time' },
];

// Cache-first sync: while a background sync is in flight, re-read the
// DB-backed list a few times so new mail appears without blocking the page.
const POLL_INTERVAL_MS = 6000;
const MAX_POLL_ATTEMPTS = 5;

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

// The same periods as the server's counts (GET /v1/email/sorting): today is
// the UK day, a week is 7 days, a month 30 (Codex ARIA-1a review 2, finding 5).
const UK_DAY = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit' });
function filterByTimeRange(email: EmailMessageItem, range: string): boolean {
  if (range === 'all') return true;
  if (!email.received_at) return false;            // the counts leave these out too
  const received = new Date(email.received_at);
  const now = new Date();
  if (range === 'today') return UK_DAY.format(received) === UK_DAY.format(now);
  const days = range === 'week' ? 7 : 30;
  return now.getTime() - received.getTime() <= days * 24 * 60 * 60 * 1000;
}

interface EmailsTabProps {
  businessId: string;
}

export default function EmailsTab({ businessId }: EmailsTabProps) {
  const navigate = useNavigate();
  const [emails, setEmails] = useState<EmailMessageItem[]>(() => {
    try {
      const cached = sessionStorage.getItem(`bh_emails_${businessId}`);
      return cached ? JSON.parse(cached) : [];
    } catch { return []; }
  });
  const [loading, setLoading] = useState(() => {
    try { return !sessionStorage.getItem(`bh_emails_${businessId}`); } catch { return true; }
  });
  const hasDataRef = useRef(emails.length > 0);
  const [analyzing, setAnalyzing] = useState(false);
  const [sorting, setSorting] = useState<SortingStatus | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [timeRange, setTimeRange] = useState('today');
  const [searchQuery, setSearchQuery] = useState('');
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({ open: false, message: '', severity: 'info' });
  const [hasEmailAccount, setHasEmailAccount] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncPeriod, setSyncPeriod] = useState<'today' | 'week' | 'month' | 'all'>('today');

  // Cache-first sync lifecycle (refs — no re-render, safe to read in timers)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollAttemptsRef = useRef(0);
  const isMountedRef = useRef(true);
  const ensureFiredRef = useRef(false);
  const emailsCountRef = useRef(emails.length);

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

  const requestRef = useRef(0);
  const loadEmails = useCallback(async (): Promise<number> => {
    const request = ++requestRef.current;     // only the latest request may set the list
    try {
      if (!hasDataRef.current) setLoading(true);
      const params: { limit?: number; category?: string; sortBy?: string; unreadOnly?: boolean } = {
        limit: 50,
        sortBy: 'date',
        unreadOnly,
      };
      if (categoryFilter !== 'all') {
        params.category = categoryFilter;
      }
      const data = await fetchEmailMessages(params);
      const result = data.messages || [];
      if (request !== requestRef.current) return result.length;   // a newer view was asked for
      setEmails(result);
      hasDataRef.current = true;
      setHasEmailAccount(true);
      try { sessionStorage.setItem(`bh_emails_${businessId}`, JSON.stringify(result)); } catch {}
      return result.length;
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes('No email account') || message.includes('404') || message.includes('email feature')) {
        setHasEmailAccount(false);
      }
      setEmails([]);
      return 0;
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, unreadOnly, businessId]);

  // Keep a ref of the current email count so timers can read it without
  // re-subscribing on every change.
  useEffect(() => {
    emailsCountRef.current = emails.length;
  }, [emails]);

  useEffect(() => {
    loadEmails();
  }, [loadEmails]);
  // Timers call the latest loadEmails, never one from an earlier view (review 2, finding 5).
  const loadEmailsRef = useRef(loadEmails);
  useEffect(() => { loadEmailsRef.current = loadEmails; }, [loadEmails]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    pollAttemptsRef.current = 0;
  }, []);

  // Poll the DB-backed list while a background sync is in flight. Stops when
  // new mail appears, max attempts are reached, or the tab unmounts.
  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return; // already polling — don't stack intervals
    pollAttemptsRef.current = 0;
    let lastCount = emailsCountRef.current;
    pollTimerRef.current = setInterval(async () => {
      pollAttemptsRef.current += 1;
      const count = await loadEmailsRef.current();
      if (count > lastCount || pollAttemptsRef.current >= MAX_POLL_ATTEMPTS) {
        stopPolling();
        if (isMountedRef.current) setIsSyncing(false);
      } else {
        lastCount = Math.max(lastCount, count);
      }
    }, POLL_INTERVAL_MS);
  }, [stopPolling]);

  // Non-blocking sync trigger: ask the server to sync only if stale/empty.
  // Never blocks render; on failure we just keep showing the cached emails.
  const triggerEnsure = useCallback(async (opts?: { showToast?: boolean }) => {
    try {
      const res = await apiRequest('POST', '/v1/email/sync/ensure');
      const data = await res.json().catch(() => ({}));
      if (data?.scheduled) {
        // 'syncing' (stale) or 'empty' (initial setup) — background sync queued.
        setIsSyncing(true);
        startPolling();
        if (opts?.showToast) {
          setSnackbar({ open: true, message: 'Checking for new mail…', severity: 'info' });
        }
      } else {
        // 'fresh' (cache current) or no account connected — nothing scheduled.
        setIsSyncing(false);
        if (opts?.showToast) {
          loadEmails();
          setSnackbar({ open: true, message: 'Your inbox is up to date', severity: 'success' });
        }
      }
    } catch (e) {
      // Network/other failure — keep the cached emails on screen, no error spew.
      console.warn('[EmailsTab] sync ensure failed:', e);
      setIsSyncing(false);
      if (opts?.showToast) {
        setSnackbar({ open: true, message: 'Could not check for new mail', severity: 'error' });
      }
    }
  }, [startPolling, loadEmails]);

  const handleSyncWithPeriod = useCallback((period: 'today' | 'week' | 'month' | 'all' = 'today') => {
    setSyncPeriod(period);
    setTimeRange(period);
    triggerEnsure({ showToast: true });
  }, [triggerEnsure]);

  // On mount: cached emails are already shown (from sessionStorage + loadEmails).
  // Fire one non-blocking /sync/ensure to refresh in the background if stale.
  useEffect(() => {
    if (!businessId || ensureFiredRef.current) return;
    ensureFiredRef.current = true;
    triggerEnsure();
  }, [businessId, triggerEnsure]);

  // Track mount state and clean up any polling timer on unmount (no leaks).
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      stopPolling();
    };
  }, [stopPolling]);

  // The counts come from the server for the page's time range, never from the
  // (filtered, 50 at most) list on screen (Codex ARIA-1a review 1, finding 5),
  // and refresh each minute so "next check" never sits in the past.
  const lastSortedRef = useRef<string | null>(null);
  const loadSorting = useCallback(async () => {
    try {
      const next = await fetchSortingStatus(timeRange);
      setSorting(next);
      // Sorting has moved on since the list was loaded: reload it, so a count
      // never sits beside a list that doesn't show those emails yet.
      if (lastSortedRef.current !== null && next.last_sorted_at !== lastSortedRef.current) loadEmailsRef.current();
      lastSortedRef.current = next.last_sorted_at;
    } catch { /* the line just stays as it was */ }
  }, [timeRange]);
  useEffect(() => {
    loadSorting();
    const timer = setInterval(loadSorting, 60000);
    return () => clearInterval(timer);
  }, [loadSorting]);
  const showCategory = (key: string, unread = false) => { setCategoryFilter(key); setUnreadOnly(unread); };

  // ARIA-1a: "Sort now" runs the same pass as the 15-minute check and says
  // what it did. "Analyze All" found nothing (the background had sorted it)
  // and looked as if it did nothing.
  const handleSortNow = async () => {
    setAnalyzing(true);
    try {
      const result = await analyzeEmails();
      const sorted = result.sorted_count ?? 0;
      const free = result.skipped_count ?? 0;
      if (result.busy) {
        setSnackbar({ open: true, severity: 'info', message: 'Aria is sorting your mail right now. It will be ready in a moment.' });
      } else if (result.failed) {
        setSnackbar({ open: true, severity: 'error',
          message: `Aria couldn't sort ${result.waiting_count || 'some'} email${result.waiting_count === 1 ? '' : 's'} just now. She'll try again at the next check.` });
      } else if (sorted + free === 0) {
        setSnackbar({ open: true, severity: 'info', message: 'Nothing new to sort: everything is sorted.' });
      } else {
        const parts = [`Sorted ${sorted + free} new email${sorted + free === 1 ? '' : 's'}`];
        if (free) parts.push(`${free} newsletter${free === 1 ? '' : 's'}, promotion${free === 1 ? '' : 's'} or automated message${free === 1 ? '' : 's'} at no cost`);
        setSnackbar({ open: true, severity: 'success', message: parts.join(', including ') + '.' });
      }
      await Promise.all([loadEmails(), loadSorting()]);
    } catch {
      setSnackbar({ open: true, message: "Couldn't reach Aria to sort just now. Try again in a moment.", severity: 'error' });
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
      priority: isImportant(email.ai_category, email.ai_priority) ? 'high' : 'medium',
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
    // The chosen view, applied here too, so a late response can't show another one.
    .filter(e => !unreadOnly || e.is_unread)
    .filter(e => categoryFilter === 'all'
      || (categoryFilter === 'important' ? isImportant(e.ai_category, e.ai_priority) : e.ai_category === categoryFilter))
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

  const counts: Record<string, number> = sorting
    ? {
      all: sorting.total,
      unread: sorting.unread,
      important: sorting.important,
      needsYou: sorting.important_unread,
      ...Object.fromEntries(sorting.categories.map(c => [c.key, c.count])),
    }
    : {
      all: filteredEmails.length,
      unread: filteredEmails.filter(e => e.is_unread).length,
      important: filteredEmails.filter(e => isImportant(e.ai_category, e.ai_priority)).length,
      needsYou: filteredEmails.filter(e => e.is_unread && isImportant(e.ai_category, e.ai_priority)).length,
      ...Object.fromEntries(INBOX_CATEGORIES.map(c => [c.key, filteredEmails.filter(e => e.ai_category === c.key).length])),
    };
  const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : null);
  const nextCheck = sorting?.next_check_at ? new Date(sorting.next_check_at) : null;
  const nextCheckText = nextCheck
    ? (nextCheck.toDateString() === new Date().toDateString() ? when(sorting!.next_check_at)
      : nextCheck.toLocaleString('en-GB', { weekday: 'long', hour: '2-digit', minute: '2-digit' }))
    : null;

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
      {/* Header row: Aria's sorting, said plainly (ARIA-1a) */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 2 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h6" fontWeight={600}>Inbox</Typography>
          <Typography variant="body2" color="text.secondary" data-testid="sorting-status">
            Aria sorts new mail {sorting?.schedule ?? 'every 15 minutes, weekdays 7am to 7pm'}
            {sorting?.last_sorted_at ? ` · last sorted ${when(sorting.last_sorted_at)}` : ''}
            {nextCheckText ? ` · next check ${nextCheckText}` : ''}
            {sorting && sorting.waiting > 0 ? ` · ${sorting.waiting} waiting` : ''}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="outlined"
          startIcon={analyzing ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
          onClick={handleSortNow}
          disabled={analyzing}
        >
          {analyzing ? 'Sorting…' : 'Sort now'}
        </Button>
      </Box>

      {/* Sync period selector */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 12,
        flexWrap: 'wrap',
      }}>
        <span style={{
          fontSize: 12,
          color: 'hsl(var(--muted-foreground))',
          marginRight: 4,
        }}>
          Sync period:
        </span>
        {([
          { key: 'today', label: 'Today', description: null },
          { key: 'week', label: 'Past week', description: 'May take a moment' },
          { key: 'month', label: 'Past month', description: 'Takes longer' },
          { key: 'all', label: 'All time', description: 'May take several minutes' },
        ] as const).map((option) => (
          <button
            key={option.key}
            onClick={() => handleSyncWithPeriod(option.key)}
            disabled={isSyncing}
            title={option.description || undefined}
            style={{
              padding: '4px 12px',
              cursor: isSyncing ? 'not-allowed' : 'pointer',
              fontSize: 12,
              fontWeight: 500,
              background: syncPeriod === option.key
                ? 'rgba(124, 92, 252, 0.12)'
                : 'var(--glass-bg)',
              border: syncPeriod === option.key
                ? '0.5px solid rgba(124, 92, 252, 0.2)'
                : '0.5px solid var(--glass-border)',
              borderRadius: 6,
              color: syncPeriod === option.key
                ? '#a78bfa'
                : 'hsl(var(--foreground))',
              opacity: isSyncing ? 0.5 : 1,
              transition: 'all 200ms',
            }}
          >
            {option.key === syncPeriod && isSyncing ? 'Syncing...' : option.label}
          </button>
        ))}
      </div>

      {/* Summary stat cards: tap one to filter */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Card
          onClick={() => showCategory('important', true)}
          sx={{ flex: '1 1 150px', p: 2, textAlign: 'center', cursor: 'pointer', border: '1px solid var(--color-neutral-100)', boxShadow: 'var(--shadow-xs)' }}
        >
          <Typography sx={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--color-danger-500)' }}>
            {counts.needsYou}
          </Typography>
          <Typography sx={{ fontSize: '0.6875rem', fontWeight: 500, color: 'var(--color-neutral-500)', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
            Needs you
          </Typography>
        </Card>
        <Card
          onClick={() => showCategory('new_enquiry')}
          sx={{ flex: '1 1 150px', p: 2, textAlign: 'center', cursor: 'pointer', border: '1px solid var(--color-neutral-100)', boxShadow: 'var(--shadow-xs)' }}
        >
          <Typography sx={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--color-primary-500)' }}>
            {counts.new_enquiry}
          </Typography>
          <Typography sx={{ fontSize: '0.6875rem', fontWeight: 500, color: 'var(--color-neutral-500)', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
            New enquiries
          </Typography>
        </Card>
        <Card
          onClick={() => showCategory('all', true)}
          sx={{ flex: '1 1 150px', p: 2, textAlign: 'center', cursor: 'pointer', border: '1px solid var(--color-neutral-100)', boxShadow: 'var(--shadow-xs)' }}
        >
          <Typography sx={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--color-neutral-700)' }}>
            {counts.unread}
          </Typography>
          <Typography sx={{ fontSize: '0.6875rem', fontWeight: 500, color: 'var(--color-neutral-500)', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
            Unread
          </Typography>
        </Card>
      </Box>

      {/* Category filter chips */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {CATEGORIES.map(cat => (
          <Chip
            key={cat.key}
            label={`${cat.label} (${counts[cat.key] || 0})`}
            onClick={() => showCategory(cat.key)}
            color={categoryFilter === cat.key ? 'primary' : 'default'}
            variant={categoryFilter === cat.key ? 'filled' : 'outlined'}
          />
        ))}
        {unreadOnly && (
          <Chip label="Unread only" color="primary" onDelete={() => setUnreadOnly(false)} />
        )}
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
            onClick={() => setTimeRange(tr.key as typeof timeRange)}
            color={timeRange === tr.key ? 'primary' : 'default'}
            variant={timeRange === tr.key ? 'filled' : 'outlined'}
          />
        ))}
      </Box>

      {/* Syncing indicator */}
      {isSyncing && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '12px 16px',
          marginBottom: 12,
          borderRadius: 8,
          background: 'rgba(124, 92, 252, 0.08)',
          border: '0.5px solid rgba(124, 92, 252, 0.15)',
          fontSize: 13,
          color: '#a78bfa',
        }}>
          <CircularProgress size={16} sx={{ color: '#a78bfa' }} />
          {emails.length === 0
            ? 'Setting up your inbox\u2026'
            : 'Checking for new mail\u2026'}
        </div>
      )}

      {/* Email list */}
      {loading && emails.length === 0 ? (
        <LoadingMessage
          messages={["Fetching your latest emails...", "Organising and categorising everything...", "Identifying what needs your attention...", "Nearly done — this saves you hours of inbox time!"]}
          icon="📧"
        />
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
            const borderColor = CATEGORY_BORDER[category] || '#9e9e9e';
            const chipColor = CATEGORY_CHIP[category] || 'default';

            return (
              <Card
                key={email.id}
                sx={{
                  p: 2,
                  mb: 1.5,
                  borderLeft: 4,
                  borderLeftColor: borderColor,
                  opacity: email.is_unread ? 1 : 0.8,
                  cursor: 'pointer',
                  transition: 'all 150ms cubic-bezier(0.4,0,0.2,1)',
                  '&:hover': {
                    boxShadow: 'var(--shadow-md)',
                    bgcolor: 'var(--color-neutral-50)',
                    transform: 'translateY(-1px)',
                    '& .email-actions': { opacity: 1 },
                  },
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
                          label={categoryLabel(email.ai_category)}
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
                  <Box className="email-actions" sx={{ ml: 1, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 0.5, opacity: { xs: 1, md: 0 }, transition: 'opacity 150ms ease' }}>
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
