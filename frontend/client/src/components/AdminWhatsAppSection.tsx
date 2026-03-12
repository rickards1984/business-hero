/**
 * Admin WhatsApp Section — CEO Briefing config for a business (admin view).
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  Chip,
  CircularProgress,
  Snackbar,
  Alert,
  TextField,
} from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import SendIcon from '@mui/icons-material/Send';
import {
  fetchAdminWhatsAppOverview,
  updateAdminWhatsAppConfig,
  sendTestBriefing,
  sendTestPulse,
  type WhatsAppConfig,
} from '@/lib/whatsappApi';
import PhoneInput from './PhoneInput';

interface AdminWhatsAppSectionProps {
  businessId: string;
}

export default function AdminWhatsAppSection({ businessId }: AdminWhatsAppSectionProps) {
  const [config, setConfig] = useState<WhatsAppConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sendingTest, setSendingTest] = useState<'briefing' | 'pulse' | null>(null);
  const [editing, setEditing] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [toast, setToast] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({ open: false, message: '', severity: 'success' });

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const overview = await fetchAdminWhatsAppOverview();
      const item = overview.find((o: any) => o.business_id === businessId);
      if (item) {
        setConfig({
          configured: true,
          phone_number: item.phone_number,
          owner_name: item.owner_name || '',
          enabled: item.enabled,
          daily_pulse_enabled: item.daily_pulse_enabled,
          weekly_briefing_enabled: item.weekly_briefing_enabled,
        });
        setPhoneNumber(item.phone_number || '');
        setOwnerName(item.owner_name || '');
      } else {
        setConfig({ configured: false });
      }
    } catch {
      setConfig({ configured: false });
    } finally {
      setLoading(false);
    }
  }, [businessId]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateAdminWhatsAppConfig(businessId, {
        phone_number: phoneNumber.replace(/\s/g, ''),
        owner_name: ownerName.trim() || undefined,
        enabled: true,
      });
      setToast({ open: true, message: 'WhatsApp config saved', severity: 'success' });
      setEditing(false);
      await loadConfig();
    } catch (err: any) {
      setToast({ open: true, message: err.message || 'Failed to save', severity: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const handleSendTestBriefing = async () => {
    setSendingTest('briefing');
    try {
      const result = await sendTestBriefing();
      setToast({ open: true, message: result.sent ? 'Weekly briefing sent!' : 'Failed to send', severity: result.sent ? 'success' : 'error' });
    } catch {
      setToast({ open: true, message: 'Failed to send test briefing', severity: 'error' });
    } finally {
      setSendingTest(null);
    }
  };

  const handleSendTestPulse = async () => {
    setSendingTest('pulse');
    try {
      const result = await sendTestPulse();
      setToast({ open: true, message: result.sent ? 'Daily pulse sent!' : 'Failed to send', severity: result.sent ? 'success' : 'error' });
    } catch {
      setToast({ open: true, message: 'Failed to send test pulse', severity: 'error' });
    } finally {
      setSendingTest(null);
    }
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" py={2}>
        <CircularProgress size={24} />
      </Box>
    );
  }

  if (!config?.configured && !editing) {
    return (
      <Card sx={{ border: 1, borderColor: 'divider', borderRadius: 2, mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={600} gutterBottom>
            📱 CEO Briefing
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Not configured. The business owner can set this up from their dashboard.
          </Typography>
          <Button variant="outlined" size="small" startIcon={<EditIcon />} onClick={() => setEditing(true)}>
            Configure now
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card sx={{ border: 1, borderColor: 'divider', borderRadius: 2, mb: 2 }}>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
          📱 CEO Briefing
        </Typography>

        {editing ? (
          <Box sx={{ mt: 2 }}>
            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>Phone</Typography>
              <PhoneInput value={phoneNumber} onChange={setPhoneNumber} />
            </Box>
            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>Owner name</Typography>
              <TextField
                fullWidth
                size="small"
                value={ownerName}
                onChange={(e) => setOwnerName(e.target.value)}
                placeholder="Michael"
              />
            </Box>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button variant="contained" size="small" onClick={handleSave} disabled={saving}>
                {saving ? <CircularProgress size={18} /> : 'Save'}
              </Button>
              <Button variant="outlined" size="small" onClick={() => setEditing(false)}>Cancel</Button>
            </Box>
          </Box>
        ) : (
          <>
            <Typography variant="body2">Phone: {config?.phone_number || '—'}</Typography>
            <Typography variant="body2">Owner: {config?.owner_name || '—'}</Typography>
            <Typography variant="body2">
              Status: <Chip label={config?.enabled ? 'Active' : 'Disabled'} size="small" color={config?.enabled ? 'success' : 'default'} />
            </Typography>
            <Typography variant="body2">
              Weekly Briefing: {config?.weekly_briefing_enabled ? '✅' : '❌'} · Daily Pulse: {config?.daily_pulse_enabled ? '✅' : '❌'} · Real-Time Alerts: ✅
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, mt: 2, flexWrap: 'wrap' }}>
              <Button variant="outlined" size="small" startIcon={<EditIcon />} onClick={() => setEditing(true)}>
                Edit Config
              </Button>
              <Button
                variant="outlined"
                size="small"
                startIcon={<SendIcon />}
                onClick={handleSendTestBriefing}
                disabled={!!sendingTest}
              >
                {sendingTest === 'briefing' ? 'Sending...' : 'Send Test Briefing'}
              </Button>
              <Button
                variant="outlined"
                size="small"
                onClick={handleSendTestPulse}
                disabled={!!sendingTest}
              >
                {sendingTest === 'pulse' ? 'Sending...' : 'Send Test Pulse'}
              </Button>
            </Box>
          </>
        )}
      </CardContent>
      <Snackbar open={toast.open} autoHideDuration={4000} onClose={() => setToast((t) => ({ ...t, open: false }))} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        <Alert severity={toast.severity}>{toast.message}</Alert>
      </Snackbar>
    </Card>
  );
}
