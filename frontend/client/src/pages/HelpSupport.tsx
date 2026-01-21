import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useAuth } from '@/contexts/AuthContext';
import { supabase } from '@/lib/supabase';
import { useMe } from '@/hooks/useMe';

const CATEGORIES = ['general', 'billing', 'technical', 'account'];
const SEVERITIES = ['low', 'normal', 'high', 'urgent'];

interface SupportTicket {
  id: string;
  title: string;
  category: string;
  severity: string;
  status: string;
  message: string;
  created_at: string;
  user_id: string;
}

export default function HelpSupport() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, loading: authLoading } = useAuth();
  const { data: me } = useMe();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [lastApiError, setLastApiError] = useState('');
  const [tickets, setTickets] = useState<SupportTicket[]>([]);

  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('general');
  const [severity, setSeverity] = useState('normal');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [authLoading, user, navigate]);

  useEffect(() => {
    if (me && !me.id) {
      setError('No business assigned');
      setLoading(false);
      return;
    }
    if (me?.id) {
      loadTickets();
    }
  }, [me?.id]);

  const loadTickets = async () => {
    if (!me?.id) {
      setError('No business assigned');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const { data, error: fetchError } = await supabase
        .from('support_tickets')
        .select('*')
        .eq('business_id', me.id)
        .order('created_at', { ascending: false });
      if (fetchError) throw fetchError;
      setTickets((data || []) as SupportTicket[]);
    } catch (err: any) {
      setError(err.message || 'Failed to load tickets');
      setLastApiError(err.message || 'Failed to load tickets');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!me?.id || !user) return;
    if (!title.trim() || !message.trim()) {
      setError('Title and message are required');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const context = {
        route: location.pathname,
        user_agent: navigator.userAgent,
        timestamp: new Date().toISOString(),
        last_api_error: lastApiError || null,
      };

      const { error: insertError } = await supabase.from('support_tickets').insert({
        business_id: me.id,
        user_id: user.id,
        title: title.trim(),
        category,
        severity,
        message: message.trim(),
        page_url: window.location.href,
        context,
      });
      if (insertError) throw insertError;
      setTitle('');
      setCategory('general');
      setSeverity('normal');
      setMessage('');
      loadTickets();
    } catch (err: any) {
      setError(err.message || 'Failed to submit ticket');
      setLastApiError(err.message || 'Failed to submit ticket');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCloseTicket = async (ticketId: string) => {
    setError('');
    try {
      const { error: updateError } = await supabase
        .from('support_tickets')
        .update({ status: 'closed' })
        .eq('id', ticketId);
      if (updateError) throw updateError;
      loadTickets();
    } catch (err: any) {
      setError(err.message || 'Failed to close ticket');
      setLastApiError(err.message || 'Failed to close ticket');
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Button variant="outlined" startIcon={<ArrowBackIcon />} onClick={() => navigate('/app')}>
          Back to Dashboard
        </Button>
      </Box>

      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>Help / Support</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Submit a support request and track responses.
        </Typography>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <FormControl fullWidth>
            <InputLabel>Category</InputLabel>
            <Select value={category} label="Category" onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <MenuItem key={c} value={c}>{c}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth>
            <InputLabel>Severity</InputLabel>
            <Select value={severity} label="Severity" onChange={(e) => setSeverity(e.target.value)}>
              {SEVERITIES.map((s) => (
                <MenuItem key={s} value={s}>{s}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Message"
            multiline
            minRows={4}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button variant="contained" onClick={handleSubmit} disabled={submitting}>
              {submitting ? 'Submitting...' : 'Submit ticket'}
            </Button>
          </Box>
        </Box>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>Your tickets</Typography>
        {loading ? (
          <Typography color="text.secondary">Loading...</Typography>
        ) : tickets.length === 0 ? (
          <Typography color="text.secondary">No tickets yet.</Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {tickets.map((ticket) => (
              <Box key={ticket.id} sx={{ borderBottom: '1px solid', borderColor: 'divider', pb: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2 }}>
                  <Box>
                    <Typography variant="subtitle1">{ticket.title}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(ticket.created_at).toLocaleString()}
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Chip label={ticket.status} size="small" />
                    <Chip label={ticket.severity} size="small" color={ticket.severity === 'urgent' ? 'error' : 'default'} />
                  </Box>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  {ticket.message}
                </Typography>
                {ticket.status !== 'closed' && ticket.user_id === user?.id && (
                  <Box sx={{ mt: 1 }}>
                    <Button size="small" variant="outlined" onClick={() => handleCloseTicket(ticket.id)}>
                      Close ticket
                    </Button>
                  </Box>
                )}
              </Box>
            ))}
          </Box>
        )}
      </Paper>
    </Container>
  );
}
