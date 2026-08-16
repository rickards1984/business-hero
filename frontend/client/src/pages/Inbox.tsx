import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Container,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Button,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  IconButton,
  Tabs,
  Tab,
  Snackbar,
  Tooltip,
} from '@mui/material';
import {
  Sync as SyncIcon,
  AutoAwesome as AnalyzeIcon,
  Reply as ReplyIcon,
  AttachFile as AttachmentIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import {
  EmailMessageItem,
  EmailDraftResponse,
  fetchEmailMessages,
  runEmailSync,
  generateDraftOptions,
  sendEmailDraft,
  analyzeEmails,
} from '@/lib/emailApi';

const CATEGORIES = [
  { key: '', label: 'All' },
  { key: 'action_required', label: 'Action Required' },
  { key: 'awaiting_reply', label: 'Awaiting Reply' },
  { key: 'fyi', label: 'FYI' },
  { key: 'finance', label: 'Finance' },
  { key: 'marketing', label: 'Marketing' },
  { key: 'scheduling', label: 'Scheduling' },
  { key: 'spam', label: 'Spam' },
];

const PRIORITY_COLORS: Record<number, string> = {
  5: '#ef4444',
  4: '#f97316',
  3: '#3b82f6',
  2: '#9ca3af',
  1: '#d1d5db',
};

const TONES = [
  { key: 'professional', label: 'Professional' },
  { key: 'friendly', label: 'Friendly' },
  { key: 'brief', label: 'Brief' },
];

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function Inbox() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [messages, setMessages] = useState<EmailMessageItem[]>([]);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [sortBy, setSortBy] = useState<'received_at' | 'ai_priority'>('received_at');

  // Draft dialog state
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftSending, setDraftSending] = useState(false);
  const [draftError, setDraftError] = useState('');
  const [selectedMessage, setSelectedMessage] = useState<EmailMessageItem | null>(null);
  const [draftOptions, setDraftOptions] = useState<EmailDraftResponse[]>([]);
  const [selectedTone, setSelectedTone] = useState(0);
  const [editedBody, setEditedBody] = useState('');

  useEffect(() => {
    if (!authLoading && !user) navigate('/login');
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) loadMessages();
  }, [user]);

  const loadMessages = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchEmailMessages({ limit: 150, sortBy });
      setMessages(data.messages || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load inbox');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user && !loading) loadMessages();
  }, [sortBy]);

  const handleSync = async () => {
    setSyncing(true);
    setError('');
    try {
      const result = await runEmailSync();
      await loadMessages();
      if (result.message_count > 0) {
        setSuccessMsg(`Synced ${result.message_count} messages (auto-analyzed)`);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to sync inbox');
    } finally {
      setSyncing(false);
    }
  };

  const handleAnalyzeAll = async () => {
    setAnalyzing(true);
    setError('');
    try {
      const unanalyzed = messages.filter((m) => !m.ai_category).map((m) => m.id);
      if (unanalyzed.length === 0) {
        setSuccessMsg('All emails are already analyzed');
        setAnalyzing(false);
        return;
      }
      const result = await analyzeEmails(unanalyzed);
      setSuccessMsg(`Analyzed ${result.analyzed_count} emails`);
      await loadMessages();
    } catch (err: any) {
      setError(err.message || 'Failed to analyze emails');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleReply = async (message: EmailMessageItem) => {
    setSelectedMessage(message);
    setDraftOptions([]);
    setDraftError('');
    setDraftLoading(true);
    setDraftOpen(true);
    setSelectedTone(0);
    setEditedBody('');
    try {
      const response = await generateDraftOptions({ email_message_id: message.id });
      setDraftOptions(response.drafts);
      if (response.drafts.length > 0) {
        setEditedBody(response.drafts[0].body_text || '');
      }
    } catch (err: any) {
      setDraftError(err.message || 'Failed to generate drafts');
    } finally {
      setDraftLoading(false);
    }
  };

  const handleToneChange = (index: number) => {
    setSelectedTone(index);
    if (draftOptions[index]) {
      setEditedBody(draftOptions[index].body_text || '');
    }
  };

  const handleSendDraft = async () => {
    const draft = draftOptions[selectedTone];
    if (!draft) return;
    setDraftSending(true);
    setDraftError('');
    try {
      const result = await sendEmailDraft(draft.id);
      if (!result.success) throw new Error(result.message || 'Failed to send');
      setDraftOpen(false);
      setSuccessMsg('Reply sent successfully');
    } catch (err: any) {
      setDraftError(err.message || 'Failed to send');
    } finally {
      setDraftSending(false);
    }
  };

  const filteredMessages = useMemo(() => {
    if (!categoryFilter) return messages;
    return messages.filter((m) => m.ai_category === categoryFilter);
  }, [messages, categoryFilter]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { '': messages.length };
    for (const m of messages) {
      const cat = m.ai_category || '';
      if (cat) counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [messages]);

  if (authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Paper sx={{ p: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h5" fontWeight={700}>Inbox</Typography>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              startIcon={syncing ? <CircularProgress size={16} /> : <SyncIcon />}
              onClick={handleSync}
              disabled={syncing}
              size="small"
            >
              Sync
            </Button>
            <Button
              variant="outlined"
              startIcon={analyzing ? <CircularProgress size={16} /> : <AnalyzeIcon />}
              onClick={handleAnalyzeAll}
              disabled={analyzing}
              size="small"
            >
              Analyze All
            </Button>
          </Box>
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {/* Category Tabs */}
        <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
          <Tabs
            value={CATEGORIES.findIndex((c) => c.key === categoryFilter)}
            onChange={(_, idx) => setCategoryFilter(CATEGORIES[idx]?.key || '')}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ '& .MuiTab-root': { textTransform: 'none', minHeight: 40, py: 0.5 } }}
          >
            {CATEGORIES.map((cat) => (
              <Tab
                key={cat.key}
                label={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    {cat.label}
                    {(categoryCounts[cat.key] || 0) > 0 && (
                      <Chip label={categoryCounts[cat.key] || 0} size="small" sx={{ height: 18, fontSize: '0.7rem' }} />
                    )}
                  </Box>
                }
              />
            ))}
          </Tabs>
        </Box>

        {/* Sort controls */}
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <Chip
            label="By Date"
            variant={sortBy === 'received_at' ? 'filled' : 'outlined'}
            color={sortBy === 'received_at' ? 'primary' : 'default'}
            onClick={() => setSortBy('received_at')}
            size="small"
          />
          <Chip
            label="By Priority"
            variant={sortBy === 'ai_priority' ? 'filled' : 'outlined'}
            color={sortBy === 'ai_priority' ? 'primary' : 'default'}
            onClick={() => setSortBy('ai_priority')}
            size="small"
          />
        </Box>

        {/* Message List */}
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
            <CircularProgress />
          </Box>
        ) : filteredMessages.length === 0 ? (
          <Box sx={{ textAlign: 'center', py: 6 }}>
            <Typography color="text.secondary">No messages found</Typography>
          </Box>
        ) : (
          <Box>
            {filteredMessages.map((message) => (
              <Box
                key={message.id}
                sx={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 1.5,
                  py: 1.5,
                  px: 1,
                  borderBottom: '1px solid',
                  borderColor: 'divider',
                  bgcolor: message.is_unread ? 'action.hover' : 'transparent',
                  '&:hover': { bgcolor: 'action.selected' },
                  transition: 'background-color 0.15s',
                }}
              >
                {/* Priority dot */}
                <Tooltip title={message.ai_priority ? `Priority ${message.ai_priority}` : 'Not analyzed'}>
                  <Box
                    sx={{
                      width: 10,
                      height: 10,
                      borderRadius: '50%',
                      bgcolor: message.ai_priority ? PRIORITY_COLORS[message.ai_priority] || '#d1d5db' : '#e5e7eb',
                      mt: 0.8,
                      flexShrink: 0,
                    }}
                  />
                </Tooltip>

                {/* Main content */}
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.25 }}>
                    <Typography variant="body2" fontWeight={message.is_unread ? 700 : 500} noWrap>
                      {message.from_name || message.from_email || 'Unknown'}
                    </Typography>
                    {message.has_attachments && (
                      <AttachmentIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
                    )}
                    {message.ai_suggested_action && (
                      <Chip
                        label={message.ai_suggested_action}
                        size="small"
                        sx={{ height: 18, fontSize: '0.65rem' }}
                        color={
                          message.ai_suggested_action.toLowerCase().includes('reply') ? 'warning'
                            : message.ai_suggested_action.toLowerCase().includes('archive') ? 'default'
                            : 'info'
                        }
                        variant="outlined"
                      />
                    )}
                  </Box>
                  <Typography variant="body2" fontWeight={message.is_unread ? 600 : 400} noWrap>
                    {message.subject || '(no subject)'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
                    {message.ai_summary || message.snippet || ''}
                  </Typography>
                </Box>

                {/* Right side: time + actions */}
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 0.5, flexShrink: 0 }}>
                  <Typography variant="caption" color="text.secondary" noWrap>
                    {timeAgo(message.received_at)}
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 0.5 }}>
                    <Tooltip title="Reply">
                      <IconButton size="small" onClick={() => handleReply(message)}>
                        <ReplyIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                </Box>
              </Box>
            ))}
          </Box>
        )}
      </Paper>

      {/* Multi-Tone Reply Dialog */}
      <Dialog open={draftOpen} onClose={() => setDraftOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>
          Reply to: {selectedMessage?.from_email || 'Unknown'}
        </DialogTitle>
        <DialogContent>
          {draftLoading && (
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 4, gap: 1 }}>
              <CircularProgress />
              <Typography variant="body2" color="text.secondary">Generating 3 draft options...</Typography>
            </Box>
          )}
          {!draftLoading && draftOptions.length > 0 && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
              {/* Tone selector */}
              <Box sx={{ display: 'flex', gap: 1 }}>
                {TONES.map((tone, idx) => (
                  <Chip
                    key={tone.key}
                    label={tone.label}
                    variant={selectedTone === idx ? 'filled' : 'outlined'}
                    color={selectedTone === idx ? 'primary' : 'default'}
                    onClick={() => handleToneChange(idx)}
                    disabled={idx >= draftOptions.length}
                  />
                ))}
              </Box>

              <TextField
                label="Subject"
                value={draftOptions[selectedTone]?.subject || ''}
                fullWidth
                size="small"
                InputProps={{ readOnly: true }}
              />
              <TextField
                label="Body"
                value={editedBody}
                onChange={(e) => setEditedBody(e.target.value)}
                multiline
                minRows={8}
                maxRows={16}
                fullWidth
              />
            </Box>
          )}
          {!draftLoading && draftOptions.length === 0 && !draftError && (
            <Typography color="text.secondary" sx={{ py: 2 }}>No drafts generated.</Typography>
          )}
          {draftError && <Alert severity="error" sx={{ mt: 2 }}>{draftError}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDraftOpen(false)}>Close</Button>
          <Button
            variant="contained"
            onClick={handleSendDraft}
            disabled={!draftOptions.length || draftSending}
          >
            {draftSending ? <CircularProgress size={20} /> : 'Send'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={!!successMsg}
        autoHideDuration={4000}
        onClose={() => setSuccessMsg('')}
        message={successMsg}
      />
    </Container>
  );
}
