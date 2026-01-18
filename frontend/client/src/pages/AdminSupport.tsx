import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  Drawer,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/AuthContext';

const STATUS_OPTIONS = ['open', 'in_progress', 'resolved', 'closed'];
const SEVERITY_OPTIONS = ['low', 'normal', 'high', 'urgent'];

interface SupportTicket {
  id: string;
  business_id: string;
  user_id: string;
  title: string;
  category: string;
  severity: string;
  status: string;
  message: string;
  page_url?: string | null;
  context?: Record<string, any>;
  admin_notes?: string | null;
  created_at: string;
}

export default function AdminSupport() {
  const navigate = useNavigate();
  const { user, isAdmin, loading: authLoading, adminLoading } = useAuth();
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [selected, setSelected] = useState<SupportTicket | null>(null);
  const [adminNotes, setAdminNotes] = useState('');
  const [statusUpdate, setStatusUpdate] = useState('open');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    } else if (!authLoading && !adminLoading && !isAdmin) {
      navigate('/app');
    }
  }, [user, isAdmin, authLoading, adminLoading, navigate]);

  useEffect(() => {
    if (user && isAdmin) {
      loadTickets();
    }
  }, [user, isAdmin, statusFilter, severityFilter]);

  const loadTickets = async () => {
    setLoading(true);
    setError('');
    try {
      let query = supabase
        .from('support_tickets')
        .select('*')
        .order('created_at', { ascending: false });
      if (statusFilter !== 'all') {
        query = query.eq('status', statusFilter);
      }
      if (severityFilter !== 'all') {
        query = query.eq('severity', severityFilter);
      }
      const { data, error: fetchError } = await query;
      if (fetchError) throw fetchError;
      setTickets((data || []) as SupportTicket[]);
    } catch (err: any) {
      setError(err.message || 'Failed to load tickets');
    } finally {
      setLoading(false);
    }
  };

  const openTicket = (ticket: SupportTicket) => {
    setSelected(ticket);
    setAdminNotes(ticket.admin_notes || '');
    setStatusUpdate(ticket.status);
  };

  const handleSave = async () => {
    if (!selected) return;
    setSaving(true);
    setError('');
    try {
      const { error: updateError } = await supabase
        .from('support_tickets')
        .update({ admin_notes: adminNotes, status: statusUpdate })
        .eq('id', selected.id);
      if (updateError) throw updateError;
      setSelected(null);
      loadTickets();
    } catch (err: any) {
      setError(err.message || 'Failed to update ticket');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, flexWrap: 'wrap', gap: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Button variant="outlined" startIcon={<ArrowBackIcon />} onClick={() => navigate('/admin')}>
            Back to Admin
          </Button>
          <Typography variant="h5">Support Tickets</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 2 }}>
          <FormControl size="small">
            <InputLabel>Status</InputLabel>
            <Select value={statusFilter} label="Status" onChange={(e) => setStatusFilter(e.target.value)}>
              <MenuItem value="all">All</MenuItem>
              {STATUS_OPTIONS.map((status) => (
                <MenuItem key={status} value={status}>
                  {status}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small">
            <InputLabel>Severity</InputLabel>
            <Select value={severityFilter} label="Severity" onChange={(e) => setSeverityFilter(e.target.value)}>
              <MenuItem value="all">All</MenuItem>
              {SEVERITY_OPTIONS.map((severity) => (
                <MenuItem key={severity} value={severity}>
                  {severity}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Paper sx={{ p: 2 }}>
        {loading ? (
          <Typography color="text.secondary">Loading...</Typography>
        ) : tickets.length === 0 ? (
          <Typography color="text.secondary">No tickets found.</Typography>
        ) : (
          tickets.map((ticket) => (
            <Box
              key={ticket.id}
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                py: 1.5,
                borderBottom: '1px solid',
                borderColor: 'divider',
                cursor: 'pointer',
              }}
              onClick={() => openTicket(ticket)}
            >
              <Box>
                <Typography variant="subtitle1">{ticket.title}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {ticket.category} • {new Date(ticket.created_at).toLocaleString()}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Chip label={ticket.status} size="small" />
                <Chip label={ticket.severity} size="small" color={ticket.severity === 'urgent' ? 'error' : 'default'} />
              </Box>
            </Box>
          ))
        )}
      </Paper>

      <Drawer anchor="right" open={!!selected} onClose={() => setSelected(null)}>
        <Box sx={{ width: { xs: 320, sm: 420 }, p: 3 }}>
          {selected && (
            <>
              <Typography variant="h6" gutterBottom>{selected.title}</Typography>
              <Typography variant="body2" color="text.secondary">
                {selected.category} • {new Date(selected.created_at).toLocaleString()}
              </Typography>
              <Typography variant="body2" sx={{ mt: 2 }}>
                {selected.message}
              </Typography>
              {selected.page_url && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
                  Page: {selected.page_url}
                </Typography>
              )}
              <TextField
                label="Admin notes"
                multiline
                minRows={4}
                fullWidth
                value={adminNotes}
                onChange={(e) => setAdminNotes(e.target.value)}
                sx={{ mt: 3 }}
              />
              <FormControl fullWidth sx={{ mt: 2 }}>
                <InputLabel>Status</InputLabel>
                <Select value={statusUpdate} label="Status" onChange={(e) => setStatusUpdate(e.target.value)}>
                  {STATUS_OPTIONS.map((status) => (
                    <MenuItem key={status} value={status}>
                      {status}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 3 }}>
                <Button variant="contained" onClick={handleSave} disabled={saving}>
                  {saving ? 'Saving...' : 'Save'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Drawer>
    </Container>
  );
}
