import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Container,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
} from '@mui/material';
import { useAuth } from '@/contexts/AuthContext';
import {
  EmailMessageItem,
  EmailDraftResponse,
  fetchEmailMessages,
  runEmailSync,
  generateEmailDraft,
  sendEmailDraft,
} from '@/lib/emailApi';

export default function Inbox() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<EmailMessageItem[]>([]);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftSending, setDraftSending] = useState(false);
  const [draftError, setDraftError] = useState('');
  const [selectedMessage, setSelectedMessage] = useState<EmailMessageItem | null>(null);
  const [draft, setDraft] = useState<EmailDraftResponse | null>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      loadMessages();
    }
  }, [user]);

  const loadMessages = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchEmailMessages({ limit: 100 });
      setMessages(data.messages || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load inbox');
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError('');
    try {
      await runEmailSync();
      await loadMessages();
    } catch (err: any) {
      setError(err.message || 'Failed to sync inbox');
    } finally {
      setSyncing(false);
    }
  };

  const handleGenerateDraft = async (message: EmailMessageItem) => {
    setSelectedMessage(message);
    setDraft(null);
    setDraftError('');
    setDraftLoading(true);
    setDraftOpen(true);
    try {
      const response = await generateEmailDraft({ email_message_id: message.id });
      setDraft(response);
    } catch (err: any) {
      setDraftError(err.message || 'Failed to generate draft');
    } finally {
      setDraftLoading(false);
    }
  };

  const handleSendDraft = async () => {
    if (!draft) {
      return;
    }
    setDraftSending(true);
    setDraftError('');
    try {
      const result = await sendEmailDraft(draft.id);
      if (!result.success) {
        throw new Error(result.message || 'Failed to send draft');
      }
      setDraftOpen(false);
      setDraft(null);
    } catch (err: any) {
      setDraftError(err.message || 'Failed to send draft');
    } finally {
      setDraftSending(false);
    }
  };

  if (loading || authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Paper sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h6">Inbox</Typography>
          <Button variant="contained" onClick={handleSync} disabled={syncing}>
            {syncing ? <CircularProgress size={20} /> : 'Sync inbox'}
          </Button>
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Subject</TableCell>
                <TableCell>From</TableCell>
                <TableCell>Snippet</TableCell>
                <TableCell>Received</TableCell>
                <TableCell>Unread</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {messages.map((message) => (
                <TableRow key={message.id}>
                  <TableCell>{message.subject || '(no subject)'}</TableCell>
                  <TableCell>{message.from_email || '-'}</TableCell>
                  <TableCell>{message.snippet || '-'}</TableCell>
                  <TableCell>{message.received_at ? new Date(message.received_at).toLocaleString() : '-'}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={message.is_unread ? 'Unread' : 'Read'}
                      color={message.is_unread ? 'primary' : 'default'}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Button size="small" variant="outlined" onClick={() => handleGenerateDraft(message)}>
                      Generate reply
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {messages.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">
                    <Typography color="text.secondary">No messages found</Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Dialog open={draftOpen} onClose={() => setDraftOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Draft reply</DialogTitle>
        <DialogContent>
          {draftLoading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
              <CircularProgress />
            </Box>
          )}
          {!draftLoading && draft && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
              <TextField label="To" value={draft.to_emails.join(', ')} fullWidth disabled />
              <TextField label="Subject" value={draft.subject} fullWidth disabled />
              <TextField
                label="Body"
                value={draft.body_text || draft.body_html || ''}
                multiline
                minRows={6}
                fullWidth
                disabled
              />
            </Box>
          )}
          {draftError && <Alert severity="error" sx={{ mt: 2 }}>{draftError}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDraftOpen(false)}>Close</Button>
          <Button variant="contained" onClick={handleSendDraft} disabled={!draft || draftSending}>
            {draftSending ? <CircularProgress size={20} /> : 'Send'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
