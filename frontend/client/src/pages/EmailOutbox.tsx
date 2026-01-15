import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Container,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';

interface OutboxEmail {
  id: string;
  invoice_id: string | null;
  to_email: string;
  subject: string;
  status: string;
  chase_stage: number | null;
  created_at: string;
  sent_at: string | null;
}

export default function EmailOutbox() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('sent');
  const [emails, setEmails] = useState<OutboxEmail[]>([]);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      fetchOutbox();
    }
  }, [user, statusFilter]);

  const fetchOutbox = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiRequest('GET', `/v1/email/outbox?status=${statusFilter}`);
      const data = await response.json();
      setEmails(data.emails || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load outbox');
    } finally {
      setLoading(false);
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
          <Typography variant="h6">Email Outbox</Typography>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Status</InputLabel>
            <Select
              label="Status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <MenuItem value="sent">Sent</MenuItem>
              <MenuItem value="failed">Failed</MenuItem>
              <MenuItem value="queued">Queued</MenuItem>
            </Select>
          </FormControl>
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Date</TableCell>
                <TableCell>To</TableCell>
                <TableCell>Subject</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Invoice Ref</TableCell>
                <TableCell>Stage</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {emails.map((email) => (
                <TableRow key={email.id}>
                  <TableCell>{new Date(email.created_at).toLocaleString()}</TableCell>
                  <TableCell>{email.to_email}</TableCell>
                  <TableCell>{email.subject}</TableCell>
                  <TableCell>{email.status}</TableCell>
                  <TableCell>{email.invoice_id || '-'}</TableCell>
                  <TableCell>{email.chase_stage ?? '-'}</TableCell>
                </TableRow>
              ))}
              {emails.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">
                    <Typography color="text.secondary">No emails found</Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Container>
  );
}
