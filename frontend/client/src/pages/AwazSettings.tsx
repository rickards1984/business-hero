import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  Paper,
  Snackbar,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';

interface AwazIntegration {
  webhook_url: string;
  connected: boolean;
  last_received_at: string | null;
  last_error?: string | null;
  receptionist_name?: string | null;
  phone_number?: string | null;
}

export default function AwazSettings() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [copySuccess, setCopySuccess] = useState('');
  const [integration, setIntegration] = useState<AwazIntegration | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const [rotateOpen, setRotateOpen] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [authLoading, user, navigate]);

  useEffect(() => {
    if (user) {
      loadIntegration();
    }
  }, [user]);

  const loadIntegration = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiRequest('GET', '/v1/integrations/awaz');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to load Awaz integration');
      }
      const data: AwazIntegration = await response.json();
      setIntegration(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load Awaz integration');
    } finally {
      setLoading(false);
    }
  };

  const formatTimestamp = (value: string | null | undefined) => {
    if (!value) return 'Never';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  };

  const handleCopy = async () => {
    if (!integration?.webhook_url) return;
    try {
      await navigator.clipboard.writeText(integration.webhook_url);
      setCopySuccess('Webhook URL copied');
    } catch (err: any) {
      setError(err.message || 'Failed to copy webhook URL');
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setError('');
    try {
      const response = await apiRequest('POST', '/v1/integrations/awaz/test');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Test failed');
      }
      setSuccessMessage('Test call created');
      loadIntegration();
    } catch (err: any) {
      setError(err.message || 'Failed to test integration');
    } finally {
      setTesting(false);
    }
  };

  const handleRotate = async () => {
    setRotating(true);
    setError('');
    try {
      const response = await apiRequest('POST', '/v1/integrations/awaz/rotate-secret');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to rotate key');
      }
      const data = await response.json();
      setIntegration((prev) => (prev ? { ...prev, webhook_url: data.webhook_url } : prev));
      setSuccessMessage('Webhook key rotated');
      setRotateOpen(false);
    } catch (err: any) {
      setError(err.message || 'Failed to rotate key');
    } finally {
      setRotating(false);
    }
  };

  if (loading || authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <Typography>Loading...</Typography>
      </Box>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Button
          variant="outlined"
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/app')}
          fullWidth={{ xs: true, sm: false }}
        >
          Back to Dashboard
        </Button>
      </Box>
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>Awaz Settings</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Configure the Awaz webhook to log calls and create follow-up tasks automatically.
        </Typography>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {integration && (
          <>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
              <Chip
                label={integration.connected ? 'Connected' : 'Not connected'}
                color={integration.connected ? 'success' : 'default'}
              />
              <Typography variant="body2" color="text.secondary">
                Last received: {formatTimestamp(integration.last_received_at)}
              </Typography>
            </Box>

            {integration.last_error && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                Last error: {integration.last_error}
              </Alert>
            )}

            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
              <TextField
                fullWidth
                label="Webhook URL"
                value={integration.webhook_url || ''}
                InputProps={{ readOnly: true }}
              />
              <Tooltip title="Copy">
                <IconButton onClick={handleCopy} aria-label="Copy webhook URL">
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>

            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
              <Button variant="outlined" onClick={handleTest} disabled={testing}>
                {testing ? 'Testing...' : 'Test connection'}
              </Button>
              <Button variant="outlined" color="warning" onClick={() => setRotateOpen(true)}>
                Rotate key
              </Button>
              <Button variant="text" onClick={() => setShowSetup((prev) => !prev)}>
                {showSetup ? 'Hide setup instructions' : 'Setup instructions'}
              </Button>
            </Box>

            <Collapse in={showSetup}>
              <Box sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                <Typography variant="subtitle2" gutterBottom>Setup instructions</Typography>
                <Typography variant="body2" color="text.secondary">
                  1. In Awaz, open your AI receptionist configuration.
                  <br />
                  2. Go to Webhooks / Integrations.
                  <br />
                  3. Paste the webhook URL from above.
                  <br />
                  4. Choose the event type “Call completed”.
                  <br />
                  5. Save the configuration in Awaz.
                  <br />
                  6. Run a test call and then click “Test connection” here.
                </Typography>
              </Box>
            </Collapse>
          </>
        )}
      </Paper>

      <Snackbar
        open={!!successMessage}
        autoHideDuration={4000}
        onClose={() => setSuccessMessage('')}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setSuccessMessage('')} severity="success">
          {successMessage}
        </Alert>
      </Snackbar>

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

      <Dialog open={rotateOpen} onClose={() => setRotateOpen(false)}>
        <DialogTitle>Rotate webhook key?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Rotating the webhook key will invalidate the current URL. Update Awaz with the new URL after rotation.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRotateOpen(false)}>Cancel</Button>
          <Button onClick={handleRotate} color="warning" disabled={rotating}>
            {rotating ? 'Rotating...' : 'Rotate key'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
