import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
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
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  Tooltip,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import GoogleIcon from '@mui/icons-material/Google';
import EmailIcon from '@mui/icons-material/Email';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { useAuth } from '@/contexts/AuthContext';
import { supabase } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';
import { config } from '@/config/env';

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

interface ConnectedAccount {
  provider: string;
  email_address: string;
  capabilities: Record<string, any>;
}

interface AwazIntegration {
  webhook_url: string;
  connected: boolean;
  last_received_at: string | null;
  last_error?: string | null;
  receptionist_name?: string | null;
  phone_number?: string | null;
}

interface OAuthAccount {
  id: string;
  provider: string;
  email_address: string;
  display_name?: string;
  created_at: string;
}

export default function EmailSettings() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [hasAccess, setHasAccess] = useState(false);
  const [, setAccounts] = useState<ConnectedAccount[]>([]);
  const [awazIntegration, setAwazIntegration] = useState<AwazIntegration | null>(null);
  const [awazLoading, setAwazLoading] = useState(false);
  const [awazError, setAwazError] = useState('');
  const [copySuccess, setCopySuccess] = useState('');
  const [showAwazSetup, setShowAwazSetup] = useState(false);
  const [rotateOpen, setRotateOpen] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [testingAwaz, setTestingAwaz] = useState(false);
  const [oauthAccounts, setOauthAccounts] = useState<OAuthAccount[]>([]);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [accountToDisconnect, setAccountToDisconnect] = useState<OAuthAccount | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

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

  // Check for success param on mount
  useEffect(() => {
    const success = searchParams.get('success');
    if (success === '1') {
      setSuccessMessage('Email account connected successfully!');
      // Remove the param from URL
      searchParams.delete('success');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      loadSettings();
      loadAwazIntegration();
      fetchOAuthAccounts();
    }
  }, [user]);

  const loadSettings = async () => {
    setLoading(true);
    setError('');

    try {
      const { data: memberRows, error: memberError } = await supabase
        .from('business_members')
        .select('business_id, role')
        .eq('user_id', user?.id)
        .eq('is_active', true);

      if (memberError) throw memberError;
      const memberData =
        memberRows?.find(row => row.role === 'owner') ??
        memberRows?.[0] ??
        null;
      if (!memberData) {
        const { error: adminError } = await supabase
          .from('platform_admins')
          .select('user_id')
          .eq('user_id', user?.id)
          .maybeSingle();
        if (adminError) throw adminError;
        setHasAccess(false);
        setError('No business assigned');
        setLoading(false);
        return;
      }

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

      if (data.from_email) {
        setAccounts([
          {
            provider: 'smtp',
            email_address: data.from_email,
            capabilities: { send: true },
          },
        ]);
      }
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

  const loadAwazIntegration = async () => {
    setAwazLoading(true);
    setAwazError('');
    try {
      const response = await apiRequest('GET', '/v1/integrations/awaz');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to load Awaz integration');
      }
      const data: AwazIntegration = await response.json();
      setAwazIntegration(data);
    } catch (err: any) {
      setAwazError(err.message || 'Failed to load Awaz integration');
    } finally {
      setAwazLoading(false);
    }
  };

  const fetchOAuthAccounts = async () => {
    try {
      const response = await apiRequest('GET', '/v1/email/accounts');
      if (response.ok) {
        const data = await response.json();
        setOauthAccounts(data.accounts || data || []);
      }
    } catch (error) {
      console.error('Failed to fetch OAuth accounts:', error);
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

  const startOAuth = async (provider: 'google' | 'microsoft') => {
    const { data } = await supabase.auth.getSession();
    const accessToken = data.session?.access_token;
    if (!accessToken) {
      setError('You must be logged in to connect an email account.');
      return;
    }
    try {
      const response = await fetch(
        `${config.apiBaseUrl}/v1/oauth/${provider}/start?mode=read_full`,
        {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      if (!response.ok) {
        const bodyText = await response.text();
        console.error(`OAuth start failed (${response.status})`, bodyText);
        setError(bodyText || 'Failed to start OAuth');
        return;
      }
      const payload = await response.json();
      if (!payload?.url) {
        setError('Failed to start OAuth');
        return;
      }
      window.location.assign(payload.url);
    } catch (err: any) {
      setError(err.message || 'Failed to start OAuth');
    }
  };

  const handleDisconnectClick = (account: OAuthAccount) => {
    setAccountToDisconnect(account);
    setDisconnectOpen(true);
  };

  const handleDisconnect = async () => {
    if (!accountToDisconnect) return;
    
    setDisconnecting(true);
    try {
      const response = await apiRequest('DELETE', `/v1/email/accounts/${accountToDisconnect.id}`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to disconnect account');
      }
      setSuccessMessage('Email account disconnected');
      setDisconnectOpen(false);
      setAccountToDisconnect(null);
      // Refresh the accounts list
      fetchOAuthAccounts();
    } catch (err: any) {
      setError(err.message || 'Failed to disconnect account');
    } finally {
      setDisconnecting(false);
    }
  };

  const formatTimestamp = (value: string | null | undefined) => {
    if (!value) return 'Never';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  };

  const handleCopyWebhook = async () => {
    if (!awazIntegration?.webhook_url) return;
    try {
      await navigator.clipboard.writeText(awazIntegration.webhook_url);
      setCopySuccess('Webhook URL copied');
    } catch (err: any) {
      setAwazError(err.message || 'Failed to copy webhook URL');
    }
  };

  const handleAwazTest = async () => {
    setTestingAwaz(true);
    setAwazError('');
    try {
      const response = await apiRequest('POST', '/v1/integrations/awaz/test');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Test failed');
      }
      setSuccessMessage('Awaz test call created');
      loadAwazIntegration();
    } catch (err: any) {
      setAwazError(err.message || 'Failed to test Awaz integration');
    } finally {
      setTestingAwaz(false);
    }
  };

  const handleRotateSecret = async () => {
    setRotating(true);
    setAwazError('');
    try {
      const response = await apiRequest('POST', '/v1/integrations/awaz/rotate-secret');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to rotate key');
      }
      const data = await response.json();
      setAwazIntegration((prev) => (prev ? { ...prev, webhook_url: data.webhook_url } : null));
      setSuccessMessage('Webhook key rotated');
      setRotateOpen(false);
    } catch (err: any) {
      setAwazError(err.message || 'Failed to rotate key');
    } finally {
      setRotating(false);
    }
  };

  // Check if provider is already connected
  const hasGoogle = oauthAccounts.some(a => a.provider === 'google');
  const hasMicrosoft = oauthAccounts.some(a => a.provider === 'microsoft');

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
          {error ? (
            <Alert severity="warning">{error}</Alert>
          ) : (
            <Alert severity="info">You do not have permission to view or edit email settings.</Alert>
          )}
        </Paper>
      </Container>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/app')}
          variant="text"
        >
          Back to Dashboard
        </Button>
        <Typography variant="h5" component="h1">Email Settings</Typography>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {/* Section 1: Connected Accounts */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>Connected Accounts</Typography>
        
        {oauthAccounts.length === 0 ? (
          <Box sx={{ py: 2 }}>
            <Typography color="text.secondary">
              No email accounts connected yet. Connect your Google or Microsoft account below.
            </Typography>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {oauthAccounts.map((account) => (
              <Box
                key={account.id}
                sx={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center', 
                  p: 2, 
                  bgcolor: 'background.default',
                  borderRadius: 1,
                  border: '1px solid',
                  borderColor: 'divider'
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  {account.provider === 'google' ? (
                    <GoogleIcon sx={{ color: '#DB4437', fontSize: 32 }} />
                  ) : (
                    <EmailIcon sx={{ color: '#0078D4', fontSize: 32 }} />
                  )}
                  <Box>
                    <Typography variant="body1" fontWeight="medium">
                      {account.email_address}
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Chip 
                        size="small" 
                        label={account.provider === 'google' ? 'Google' : 'Microsoft'}
                        color={account.provider === 'google' ? 'error' : 'primary'}
                        variant="outlined"
                      />
                      <Chip 
                        size="small" 
                        icon={<CheckCircleIcon />}
                        label="Connected"
                        color="success"
                        variant="outlined"
                      />
                    </Box>
                  </Box>
                </Box>
                <Button 
                  size="small" 
                  color="error" 
                  variant="outlined"
                  onClick={() => handleDisconnectClick(account)}
                >
                  Disconnect
                </Button>
              </Box>
            ))}
          </Box>
        )}
      </Paper>

      {/* Section 2: Connect New Account */}
      {(!hasGoogle || !hasMicrosoft) && (
        <Paper sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>Connect New Account</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Connect your email account to enable inbox sync, email briefings, and draft replies.
          </Typography>

          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            {!hasGoogle && (
              <Button 
                variant="outlined" 
                startIcon={<GoogleIcon />}
                onClick={() => startOAuth('google')}
                sx={{ 
                  borderColor: '#DB4437', 
                  color: '#DB4437',
                  '&:hover': { borderColor: '#C53929', bgcolor: 'rgba(219, 68, 55, 0.04)' }
                }}
              >
                Connect Google
              </Button>
            )}
            {!hasMicrosoft && (
              <Button 
                variant="outlined" 
                startIcon={<EmailIcon />}
                onClick={() => startOAuth('microsoft')}
                sx={{ 
                  borderColor: '#0078D4', 
                  color: '#0078D4',
                  '&:hover': { borderColor: '#006CBE', bgcolor: 'rgba(0, 120, 212, 0.04)' }
                }}
              >
                Connect Microsoft
              </Button>
            )}
          </Box>
        </Paper>
      )}

      {/* Section 3: Awaz Integration */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>Awaz Integration</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Connect Awaz calls to automatically log calls and create follow-up tasks.
        </Typography>

        {awazError && <Alert severity="error" sx={{ mb: 2 }}>{awazError}</Alert>}
        {awazLoading && <CircularProgress size={20} />}

        {awazIntegration && (
          <>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
              <Chip
                label={awazIntegration.connected ? 'Connected' : 'Not connected'}
                color={awazIntegration.connected ? 'success' : 'default'}
              />
              <Typography variant="body2" color="text.secondary">
                Last received: {formatTimestamp(awazIntegration.last_received_at)}
              </Typography>
            </Box>

            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
              <TextField
                fullWidth
                label="Webhook URL"
                value={awazIntegration.webhook_url || ''}
                InputProps={{ readOnly: true }}
                size="small"
              />
              <Tooltip title="Copy">
                <IconButton onClick={handleCopyWebhook} aria-label="Copy webhook URL">
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>

            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
              <Button variant="outlined" onClick={handleAwazTest} disabled={testingAwaz} size="small">
                {testingAwaz ? 'Testing...' : 'Test connection'}
              </Button>
              <Button variant="outlined" color="warning" onClick={() => setRotateOpen(true)} size="small">
                Rotate key
              </Button>
              <Button variant="text" onClick={() => setShowAwazSetup((prev) => !prev)} size="small">
                {showAwazSetup ? 'Hide setup instructions' : 'Setup instructions'}
              </Button>
            </Box>

            <Collapse in={showAwazSetup}>
              <Box sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                <Typography variant="subtitle2" gutterBottom>Setup instructions</Typography>
                <Typography variant="body2" color="text.secondary">
                  1. In Awaz, open your AI receptionist settings.
                  <br />
                  2. Find the "Webhooks" or "Integrations" section.
                  <br />
                  3. Paste the webhook URL shown above.
                  <br />
                  4. Set the webhook to trigger on call end.
                  <br />
                  5. Save and run a test call to verify connectivity.
                  <br />
                  6. Use "Test connection" here to confirm it logs a call.
                </Typography>
              </Box>
            </Collapse>
          </>
        )}
      </Paper>

      {/* Section 4: SMTP Settings (Collapsible) */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>SMTP Settings (Advanced)</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Configure SMTP for sending emails directly. Most users should use Google or Microsoft connection above.
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField label="SMTP Host" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} size="small" />
          <TextField
            label="SMTP Port"
            type="number"
            value={smtpPort}
            onChange={(e) => setSmtpPort(Number(e.target.value))}
            size="small"
          />
          <TextField label="SMTP Username" value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)} size="small" />
          <TextField
            label="SMTP Password"
            type="password"
            value={smtpPassword}
            onChange={(e) => setSmtpPassword(e.target.value)}
            helperText="Enter a new password to update"
            size="small"
          />
          <TextField label="From Email" value={fromEmail} onChange={(e) => setFromEmail(e.target.value)} size="small" />
          <TextField label="From Name" value={fromName} onChange={(e) => setFromName(e.target.value)} size="small" />

          <FormControlLabel
            control={<Switch checked={useTls} onChange={(e) => setUseTls(e.target.checked)} size="small" />}
            label="Use TLS"
          />
          <FormControlLabel
            control={<Switch checked={useSsl} onChange={(e) => setUseSsl(e.target.checked)} size="small" />}
            label="Use SSL"
          />
          <FormControlLabel
            control={<Switch checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} size="small" />}
            label="Enabled"
          />

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button variant="contained" onClick={handleSave} disabled={saving} size="small">
              {saving ? <CircularProgress size={20} /> : 'Save SMTP Settings'}
            </Button>
            <Button variant="outlined" onClick={handleTest} disabled={testing} size="small">
              {testing ? <CircularProgress size={20} /> : 'Send Test Email'}
            </Button>
          </Box>
        </Box>
      </Paper>

      {/* Success Snackbar */}
      <Snackbar
        open={!!successMessage}
        autoHideDuration={6000}
        onClose={() => setSuccessMessage('')}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setSuccessMessage('')} severity="success" sx={{ width: '100%' }}>
          {successMessage}
        </Alert>
      </Snackbar>

      {/* Copy Success Snackbar */}
      <Snackbar
        open={!!copySuccess}
        autoHideDuration={3000}
        onClose={() => setCopySuccess('')}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setCopySuccess('')} severity="success">
          {copySuccess}
        </Alert>
      </Snackbar>

      {/* Rotate Key Confirmation Dialog */}
      <Dialog open={rotateOpen} onClose={() => setRotateOpen(false)}>
        <DialogTitle>Rotate webhook key?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Rotating the webhook key will invalidate the current URL. Update Awaz with the new URL after rotation.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRotateOpen(false)}>Cancel</Button>
          <Button onClick={handleRotateSecret} color="warning" disabled={rotating}>
            {rotating ? 'Rotating...' : 'Rotate key'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Disconnect Confirmation Dialog */}
      <Dialog open={disconnectOpen} onClose={() => setDisconnectOpen(false)}>
        <DialogTitle>Disconnect email account?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to disconnect <strong>{accountToDisconnect?.email_address}</strong>?
            <br /><br />
            This will remove access to your email for briefings and drafts. You can reconnect at any time.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDisconnectOpen(false)}>Cancel</Button>
          <Button onClick={handleDisconnect} color="error" disabled={disconnecting}>
            {disconnecting ? 'Disconnecting...' : 'Disconnect'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
