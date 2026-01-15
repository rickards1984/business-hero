import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  TextField,
  Switch,
  FormControlLabel,
  Button,
  CircularProgress,
  Alert,
  Container,
  Snackbar,
} from '@mui/material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';

interface EmailConnection {
  id: string;
  provider: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  from_email: string;
  from_name: string | null;
  use_tls: boolean;
  use_ssl: boolean;
  is_enabled: boolean;
}

export default function EmailSettings() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [hasAccess, setHasAccess] = useState(false);

  // Form state
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [fromEmail, setFromEmail] = useState('');
  const [fromName, setFromName] = useState('');
  const [useTls, setUseTls] = useState(true);
  const [useSsl, setUseSsl] = useState(false);
  const [isEnabled, setIsEnabled] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      loadSettings();
    }
  }, [user]);

  const loadSettings = async () => {
    setLoading(true);
    setError('');

    try {
      const { data: memberData } = await supabase
        .from('business_members')
        .select('role')
        .eq('user_id', user?.id)
        .eq('is_active', true)
        .single();

      const role = memberData?.role;
      const allowed = ['owner', 'manager', 'admin'].includes(role);
      setHasAccess(allowed);

      if (!allowed) {
        setLoading(false);
        return;
      }

      const response = await apiRequest('GET', '/v1/email/connection');
      const data: EmailConnection = await response.json();
      setSmtpHost(data.smtp_host);
      setSmtpPort(data.smtp_port);
      setSmtpUsername(data.smtp_username);
      setFromEmail(data.from_email);
      setFromName(data.from_name || '');
      setUseTls(data.use_tls);
      setUseSsl(data.use_ssl);
      setIsEnabled(data.is_enabled);
    } catch (err: any) {
      if (err.message?.includes('404')) {
        // No existing connection, that's ok
        setHasAccess(true);
      } else {
        setError(err.message || 'Failed to load email settings');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSuccessMessage('');

    try {
      const payload = {
        provider: 'smtp',
        smtp_host: smtpHost,
        smtp_port: smtpPort,
        smtp_username: smtpUsername,
        smtp_password: smtpPassword,
        from_email: fromEmail,
        from_name: fromName || null,
        use_tls: useTls,
        use_ssl: useSsl,
        is_enabled: isEnabled,
      };

      const response = await apiRequest('PUT', '/v1/email/connection', payload);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to save settings');
      }

      setSuccessMessage('Email settings saved');
      setSmtpPassword('');
    } catch (err: any) {
      setError(err.message || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setError('');
    setSuccessMessage('');

    try {
      const response = await apiRequest('POST', '/v1/email/test');
      const data = await response.json();
      if (!response.ok || data.success === false) {
        throw new Error(data.message || 'Test email failed');
      }
      setSuccessMessage('Test email sent');
    } catch (err: any) {
      setError(err.message || 'Failed to send test email');
    } finally {
      setTesting(false);
    }
  };

  if (loading || authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!hasAccess) {
    return (
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>Email Settings</Typography>
          <Alert severity="info">You do not have permission to view or edit email settings.</Alert>
        </Paper>
      </Container>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>Email Settings</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Configure your SMTP settings for sending invoice chase emails.
        </Typography>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField label="SMTP Host" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} />
          <TextField
            label="SMTP Port"
            type="number"
            value={smtpPort}
            onChange={(e) => setSmtpPort(Number(e.target.value))}
          />
          <TextField label="SMTP Username" value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)} />
          <TextField
            label="SMTP Password"
            type="password"
            value={smtpPassword}
            onChange={(e) => setSmtpPassword(e.target.value)}
            helperText="Enter a new password to update"
          />
          <TextField label="From Email" value={fromEmail} onChange={(e) => setFromEmail(e.target.value)} />
          <TextField label="From Name" value={fromName} onChange={(e) => setFromName(e.target.value)} />

          <FormControlLabel
            control={<Switch checked={useTls} onChange={(e) => setUseTls(e.target.checked)} />}
            label="Use TLS"
          />
          <FormControlLabel
            control={<Switch checked={useSsl} onChange={(e) => setUseSsl(e.target.checked)} />}
            label="Use SSL"
          />
          <FormControlLabel
            control={<Switch checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />}
            label="Enabled"
          />

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button variant="contained" onClick={handleSave} disabled={saving}>
              {saving ? <CircularProgress size={20} /> : 'Save'}
            </Button>
            <Button variant="outlined" onClick={handleTest} disabled={testing}>
              {testing ? <CircularProgress size={20} /> : 'Send Test Email'}
            </Button>
          </Box>
        </Box>
      </Paper>

      <Snackbar
        open={!!successMessage}
        autoHideDuration={6000}
        onClose={() => setSuccessMessage('')}
        message={successMessage}
      />
    </Container>
  );
}
