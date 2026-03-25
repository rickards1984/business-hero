/**
 * CEO Briefing Tab — WhatsApp configuration, schedule, alerts, and automations.
 * Uses existing design system (MUI, Plus Jakarta Sans).
 */

import { useState, useEffect, useCallback } from 'react';
import LoadingMessage from '@/components/LoadingMessage';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  TextField,
  FormControlLabel,
  Checkbox,
  Switch,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  CircularProgress,
  Snackbar,
  Alert,
  Chip,
  Divider,
} from '@mui/material';
import PhoneInput from './PhoneInput';
import {
  fetchWhatsAppConfig,
  saveWhatsAppConfig,
  sendTestBriefing,
  sendTestPulse,
  sendTestTaskReminder,
  fetchWhatsAppMessages,
  fetchAutomationRules,
  provisionDefaultRules,
  updateAutomationRule,
  type WhatsAppConfig,
  type WhatsAppMessage,
  type AutomationRule,
} from '@/lib/whatsappApi';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
const DETAIL_LEVELS = [
  { value: 'brief', label: 'Brief' },
  { value: 'standard', label: 'Standard' },
  { value: 'detailed', label: 'Detailed' },
];

function TestButton({
  label,
  onSend,
}: {
  label: string;
  onSend: () => Promise<void>;
}) {
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');

  const handleClick = async () => {
    setState('sending');
    try {
      await onSend();
      setState('sent');
      setTimeout(() => setState('idle'), 3000);
    } catch {
      setState('error');
      setTimeout(() => setState('idle'), 3000);
    }
  };

  return (
    <Button
      variant="outlined"
      size="small"
      onClick={handleClick}
      disabled={state === 'sending'}
      sx={{ opacity: state === 'sending' ? 0.7 : 1 }}
    >
      {state === 'idle' && `📤 ${label}`}
      {state === 'sending' && '⏳ Sending...'}
      {state === 'sent' && '✅ Sent!'}
      {state === 'error' && '❌ Failed'}
    </Button>
  );
}

function formatMessageTime(createdAt: string): string {
  try {
    const d = new Date(createdAt);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
    if (diffDays === 0) {
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    }
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return d.toLocaleDateString('en-GB', { weekday: 'short' });
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  } catch {
    return '';
  }
}

function messageTypeIcon(type: string): string {
  if (type === 'weekly_briefing') return '📊';
  if (type === 'daily_pulse') return '🌅';
  if (type === 'task_reminder') return '📝';
  if (type === 'alert') return '⚡';
  return '💬';
}

function messageTypeLabel(type: string): string {
  if (type === 'weekly_briefing') return 'Weekly Briefing';
  if (type === 'daily_pulse') return 'Daily Pulse';
  if (type === 'task_reminder') return 'Task Reminder';
  if (type === 'alert') return 'Alert';
  return type.replace(/_/g, ' ');
}

export default function CeoBriefingTab() {
  const [config, setConfig] = useState<WhatsAppConfig | null>(null);
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
    open: false,
    message: '',
    severity: 'success',
  });
  const [messages, setMessages] = useState<WhatsAppMessage[]>([]);
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [rulesLoaded, setRulesLoaded] = useState(false);

  // Form state (mirrors config for editing)
  const [phoneNumber, setPhoneNumber] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [dailyPulseEnabled, setDailyPulseEnabled] = useState(false);
  const [dailyPulseTime, setDailyPulseTime] = useState('07:30');
  const [weeklyBriefingEnabled, setWeeklyBriefingEnabled] = useState(false);
  const [weeklyBriefingDay, setWeeklyBriefingDay] = useState('monday');
  const [weeklyBriefingTime, setWeeklyBriefingTime] = useState('08:00');
  const [preferredDetailLevel, setPreferredDetailLevel] = useState('standard');
  const [taskReminderEnabled, setTaskReminderEnabled] = useState(false);
  const [taskReminderFrequency, setTaskReminderFrequency] = useState('daily');
  const [taskReminderTime, setTaskReminderTime] = useState('08:00');
  const [realTimeAlertsEnabled, setRealTimeAlertsEnabled] = useState(false);
  const [alertTransfers, setAlertTransfers] = useState(true);
  const [alertPayments, setAlertPayments] = useState(true);
  const [alertPaymentsThreshold, setAlertPaymentsThreshold] = useState(100);
  const [alertUrgentEmails, setAlertUrgentEmails] = useState(true);
  const [alertLowBalance, setAlertLowBalance] = useState(false);
  const [alertLowBalanceThreshold, setAlertLowBalanceThreshold] = useState(500);
  const [alertKbGaps, setAlertKbGaps] = useState(true);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchWhatsAppConfig();
      if (data && data.configured && data.phone_number) {
        setConfig(data);
        setConfigured(true);
        setPhoneNumber(data.phone_number);
        setOwnerName(data.owner_name || '');
        setDailyPulseEnabled(data.daily_pulse_enabled ?? false);
        setDailyPulseTime(data.daily_pulse_time || '07:30');
        setWeeklyBriefingEnabled(data.weekly_briefing_enabled ?? false);
        setWeeklyBriefingDay(data.weekly_briefing_day || 'monday');
        setWeeklyBriefingTime(data.weekly_briefing_time || '08:00');
        setPreferredDetailLevel(data.preferred_detail_level || 'standard');
        setTaskReminderEnabled(data.task_reminder_enabled ?? false);
        setTaskReminderFrequency(data.task_reminder_frequency || 'daily');
        setTaskReminderTime(data.task_reminder_time || '08:00');
        setRealTimeAlertsEnabled((data as any).real_time_alerts_enabled ?? false);
        setAlertTransfers((data as any).alert_receptionist_transfers ?? true);
        setAlertPayments((data as any).alert_payment_received ?? true);
        setAlertPaymentsThreshold((data as any).alert_payment_received_threshold ?? 100);
        setAlertUrgentEmails((data as any).alert_urgent_emails ?? true);
        setAlertLowBalance((data as any).alert_bank_balance ?? false);
        setAlertLowBalanceThreshold((data as any).alert_bank_balance_threshold ?? 500);
        setAlertKbGaps((data as any).alert_kb_gaps ?? true);

        const msgData = await fetchWhatsAppMessages(20);
        setMessages(msgData || []);
      } else {
        setConfigured(false);
      }
    } catch (err: any) {
      setToast({ open: true, message: err.message || 'Failed to load config', severity: 'error' });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRules = useCallback(async () => {
    try {
      const data = await fetchAutomationRules();
      setRules(data || []);
      setRulesLoaded(true);
    } catch {
      setRules([]);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    if (configured && !rulesLoaded) {
      loadRules();
    }
  }, [configured, rulesLoaded, loadRules]);

  const handleActivate = async () => {
    if (!phoneNumber.trim()) {
      setToast({ open: true, message: 'Please enter your WhatsApp number', severity: 'error' });
      return;
    }
    setSaving(true);
    try {
      await saveWhatsAppConfig({
        phone_number: phoneNumber.replace(/\s/g, ''),
        owner_name: ownerName.trim() || undefined,
        enabled: true,
        daily_pulse_enabled: true,
        daily_pulse_time: '07:30',
        weekly_briefing_enabled: true,
        weekly_briefing_day: 'monday',
        weekly_briefing_time: '08:00',
        real_time_alerts_enabled: true,
      });
      setToast({ open: true, message: 'CEO Briefing activated!', severity: 'success' });
      await loadConfig();
      await provisionDefaultRules();
      await loadRules();
    } catch (err: any) {
      setToast({ open: true, message: err.message || 'Failed to activate', severity: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveWhatsAppConfig({
        phone_number: phoneNumber.replace(/\s/g, ''),
        owner_name: ownerName.trim() || undefined,
        enabled: true,
        daily_pulse_enabled: dailyPulseEnabled,
        daily_pulse_time: dailyPulseTime,
        weekly_briefing_enabled: weeklyBriefingEnabled,
        weekly_briefing_day: weeklyBriefingDay,
        weekly_briefing_time: weeklyBriefingTime,
        preferred_detail_level: preferredDetailLevel,
        task_reminder_enabled: taskReminderEnabled,
        task_reminder_frequency: taskReminderFrequency,
        task_reminder_time: taskReminderTime,
        real_time_alerts_enabled: realTimeAlertsEnabled,
        alert_receptionist_transfers: alertTransfers,
        alert_payment_received_threshold: alertPayments ? alertPaymentsThreshold : undefined,
        alert_urgent_emails: alertUrgentEmails,
        alert_bank_balance_threshold: alertLowBalance ? alertLowBalanceThreshold : undefined,
      });
      setToast({ open: true, message: 'Preferences saved!', severity: 'success' });
      await loadConfig();
    } catch (err: any) {
      setToast({ open: true, message: err.message || 'Failed to save', severity: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const handleToggleRule = async (ruleId: string, isActive: boolean) => {
    try {
      await updateAutomationRule(ruleId, { is_active: isActive });
      await loadRules();
    } catch {
      setToast({ open: true, message: 'Failed to update automation', severity: 'error' });
    }
  };

  if (loading) {
    return (
      <LoadingMessage
        messages={[
          "Loading your briefing preferences...",
          "Checking WhatsApp configuration...",
        ]}
        icon="📋"
      />
    );
  }

  // First-time setup
  if (!configured) {
    return (
      <Box sx={{ maxWidth: 600, mx: 'auto', my: 4 }}>
        <Card sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 3, p: 4 }}>
          <Box textAlign="center" mb={3}>
            <Typography sx={{ fontSize: 48, mb: 1 }}>🤖📊</Typography>
            <Typography variant="h6" fontWeight={700}>
              Your AI Business Intelligence
            </Typography>
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3, textAlign: 'center' }}>
            Get strategic briefings delivered to your WhatsApp:
          </Typography>
          <Box sx={{ textAlign: 'left', mb: 3 }}>
            {[
              '📊 Weekly CEO Briefing — strategic analysis every Monday',
              '🌅 Daily Morning Pulse — overnight summary at 7:30am',
              '⚡ Real-Time Alerts — instant notifications for urgent events',
              '🤖 Smart Automations — auto-chase invoices, create tasks',
            ].map((line, i) => (
              <Typography key={i} variant="body2" color="text.secondary" sx={{ mb: 1.5, display: 'flex', gap: 1 }}>
                {line}
              </Typography>
            ))}
          </Box>
          <Box sx={{ mb: 2 }}>
            <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
              Your WhatsApp Number
            </Typography>
            <PhoneInput value={phoneNumber} onChange={setPhoneNumber} />
          </Box>
          <Box sx={{ mb: 3 }}>
            <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
              Your Name (for personalised greetings)
            </Typography>
            <TextField
              fullWidth
              size="small"
              value={ownerName}
              onChange={(e) => setOwnerName(e.target.value)}
              placeholder="Michael"
            />
          </Box>
          <Button
            variant="contained"
            fullWidth
            onClick={handleActivate}
            disabled={saving}
            sx={{ py: 1.5 }}
          >
            {saving ? <CircularProgress size={24} /> : 'Activate CEO Briefing'}
          </Button>
        </Card>
        <Snackbar
          open={toast.open}
          autoHideDuration={4000}
          onClose={() => setToast((t) => ({ ...t, open: false }))}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert severity={toast.severity}>{toast.message}</Alert>
        </Snackbar>
      </Box>
    );
  }

  // Configured view
  const statsMessages = messages.length;
  const statsWeekly = messages.filter((m) => m.message_type === 'weekly_briefing').length;
  const statsDaily = messages.filter((m) => m.message_type === 'daily_pulse').length;
  const statsAutomations = rules.filter((r) => r.is_active).length;

  return (
    <Box>
      {/* Connection card */}
      <Card sx={{ mb: 3, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
        <CardContent>
          <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={2}>
            <Box>
              <Typography variant="subtitle1" fontWeight={600}>
                WhatsApp Connection
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Your number: {config?.phone_number} · Status: ✅ Active
              </Typography>
            </Box>
            <Chip label="Connected" color="success" size="small" />
          </Box>
        </CardContent>
      </Card>

      {/* Stats */}
      <Box display="flex" gap={2} mb={3} flexWrap="wrap">
        <Card sx={{ flex: '1 1 120px', minWidth: 100, textAlign: 'center', py: 2 }}>
          <Typography variant="h5" fontWeight={700}>{statsMessages}</Typography>
          <Typography variant="caption" color="text.secondary">Messages Sent</Typography>
        </Card>
        <Card sx={{ flex: '1 1 120px', minWidth: 100, textAlign: 'center', py: 2 }}>
          <Typography variant="h5" fontWeight={700}>{statsWeekly}</Typography>
          <Typography variant="caption" color="text.secondary">Weekly Briefings</Typography>
        </Card>
        <Card sx={{ flex: '1 1 120px', minWidth: 100, textAlign: 'center', py: 2 }}>
          <Typography variant="h5" fontWeight={700}>{statsDaily}</Typography>
          <Typography variant="caption" color="text.secondary">Daily Pulses</Typography>
        </Card>
        <Card sx={{ flex: '1 1 120px', minWidth: 100, textAlign: 'center', py: 2 }}>
          <Typography variant="h5" fontWeight={700}>{statsAutomations}</Typography>
          <Typography variant="caption" color="text.secondary">Automations</Typography>
        </Card>
      </Box>

      <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Schedule & Preferences
      </Typography>
      <Card sx={{ mb: 3, border: '1px solid', borderColor: 'divider', overflow: 'hidden' }}>
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
          <Typography variant="subtitle2" fontWeight={600}>📊 Weekly CEO Briefing</Typography>
          <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
            <FormControlLabel
              control={<Switch checked={weeklyBriefingEnabled} onChange={(e) => setWeeklyBriefingEnabled(e.target.checked)} />}
              label="Enabled"
            />
            <FormControl size="small" sx={{ minWidth: 100 }}>
              <InputLabel>Day</InputLabel>
              <Select value={weeklyBriefingDay} label="Day" onChange={(e) => setWeeklyBriefingDay(e.target.value)}>
                {DAYS.map((d) => (
                  <MenuItem key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField size="small" type="time" value={weeklyBriefingTime} onChange={(e) => setWeeklyBriefingTime(e.target.value)} sx={{ width: 100 }} />
            <FormControl size="small" sx={{ minWidth: 100 }}>
              <InputLabel>Detail</InputLabel>
              <Select value={preferredDetailLevel} label="Detail" onChange={(e) => setPreferredDetailLevel(e.target.value)}>
                {DETAIL_LEVELS.map((d) => (
                  <MenuItem key={d.value} value={d.value}>{d.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TestButton label="Send Test Briefing" onSend={sendTestBriefing} />
          </Box>
        </Box>
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
          <Typography variant="subtitle2" fontWeight={600}>🌅 Daily Morning Pulse</Typography>
          <Box display="flex" alignItems="center" gap={2}>
            <FormControlLabel
              control={<Switch checked={dailyPulseEnabled} onChange={(e) => setDailyPulseEnabled(e.target.checked)} />}
              label="Enabled"
            />
            <TextField size="small" type="time" value={dailyPulseTime} onChange={(e) => setDailyPulseTime(e.target.value)} sx={{ width: 100 }} />
            <TestButton label="Send Test Pulse" onSend={sendTestPulse} />
          </Box>
        </Box>
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography sx={{ fontSize: 18 }}>📝</Typography>
            <Box>
              <Typography variant="subtitle2" fontWeight={600}>Task Reminders</Typography>
              <Typography variant="caption" color="text.secondary">Get reminded of open and overdue tasks</Typography>
            </Box>
          </Box>
          <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
            <FormControlLabel
              control={<Switch checked={taskReminderEnabled} onChange={(e) => setTaskReminderEnabled(e.target.checked)} />}
              label="Enabled"
            />
            {taskReminderEnabled && (
              <>
                <FormControl size="small" sx={{ minWidth: 120 }}>
                  <InputLabel>Frequency</InputLabel>
                  <Select value={taskReminderFrequency} label="Frequency" onChange={(e) => setTaskReminderFrequency(e.target.value)}>
                    <MenuItem value="daily">Daily</MenuItem>
                    <MenuItem value="weekly">Weekly (Mon)</MenuItem>
                  </Select>
                </FormControl>
                <TextField size="small" type="time" value={taskReminderTime} onChange={(e) => setTaskReminderTime(e.target.value)} sx={{ width: 100 }} InputLabelProps={{ shrink: true }} />
                <TestButton label="Send Test" onSend={sendTestTaskReminder} />
              </>
            )}
          </Box>
        </Box>
        <Box sx={{ p: 2 }}>
          <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>⚡ Real-Time Alerts</Typography>
          <FormControlLabel
            control={<Switch checked={realTimeAlertsEnabled} onChange={(e) => setRealTimeAlertsEnabled(e.target.checked)} />}
            label="Enable alerts"
          />
          <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.5, ml: 2 }}>
            <FormControlLabel control={<Checkbox checked={alertTransfers} onChange={(e) => setAlertTransfers(e.target.checked)} />} label="Call transfers from receptionist" />
            <FormControlLabel
              control={<Checkbox checked={alertPayments} onChange={(e) => setAlertPayments(e.target.checked)} />}
              label={
                <Box component="span" display="flex" alignItems="center" gap={1}>
                  Payments received over £
                  <TextField size="small" type="number" value={alertPaymentsThreshold} onChange={(e) => setAlertPaymentsThreshold(Number(e.target.value) || 100)} sx={{ width: 70 }} />
                </Box>
              }
            />
            <FormControlLabel control={<Checkbox checked={alertUrgentEmails} onChange={(e) => setAlertUrgentEmails(e.target.checked)} />} label="Urgent emails" />
            <FormControlLabel
              control={<Checkbox checked={alertLowBalance} onChange={(e) => setAlertLowBalance(e.target.checked)} />}
              label={
                <Box component="span" display="flex" alignItems="center" gap={1}>
                  Bank balance below £
                  <TextField size="small" type="number" value={alertLowBalanceThreshold} onChange={(e) => setAlertLowBalanceThreshold(Number(e.target.value) || 500)} sx={{ width: 70 }} />
                </Box>
              }
            />
            <FormControlLabel control={<Checkbox checked={alertKbGaps} onChange={(e) => setAlertKbGaps(e.target.checked)} />} label="Knowledge base gaps detected" />
          </Box>
        </Box>
      </Card>

      <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Automations
      </Typography>
      <Card sx={{ mb: 3, border: '1px solid', borderColor: 'divider', overflow: 'hidden' }}>
        {rules.map((rule) => (
          <Box
            key={rule.id}
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              p: 2,
              borderBottom: 1,
              borderColor: 'divider',
              '&:last-child': { borderBottom: 0 },
              '&:hover': { bgcolor: 'action.hover' },
            }}
          >
            <Box flex={1}>
              <Typography variant="subtitle2" fontWeight={600}>{rule.name}</Typography>
              <Typography variant="caption" color="text.secondary">{rule.description || ''}</Typography>
            </Box>
            <Switch
              checked={rule.is_active}
              onChange={(e) => handleToggleRule(rule.id, e.target.checked)}
            />
          </Box>
        ))}
        {rules.length === 0 && rulesLoaded && (
          <Box p={2} textAlign="center">
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              No automation rules yet.
            </Typography>
            <Button size="small" variant="outlined" onClick={async () => { await provisionDefaultRules(); await loadRules(); }}>Provision default rules</Button>
          </Box>
        )}
      </Card>

      <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Recent Messages
      </Typography>
      <Card sx={{ mb: 3, border: '1px solid', borderColor: 'divider', overflow: 'hidden' }}>
        {messages.slice(0, 5).map((m) => (
          <Box
            key={m.id}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              p: 1.5,
              borderBottom: 1,
              borderColor: 'divider',
              '&:last-child': { borderBottom: 0 },
            }}
          >
            <Typography sx={{ fontSize: 18 }}>{messageTypeIcon(m.message_type)}</Typography>
            <Box flex={1}>
              <Typography variant="body2" fontWeight={500}>{messageTypeLabel(m.message_type)}</Typography>
              <Typography variant="caption" color="text.secondary">{formatMessageTime(m.created_at)}</Typography>
            </Box>
            <Chip size="small" label={m.twilio_status || 'Delivered'} color="success" variant="outlined" />
          </Box>
        ))}
        {messages.length === 0 && (
          <Box p={3} textAlign="center" color="text.secondary">
            <Typography variant="body2">No messages yet</Typography>
          </Box>
        )}
      </Card>

      <Button variant="contained" onClick={handleSave} disabled={saving}>
        {saving ? <CircularProgress size={20} /> : 'Save Preferences'}
      </Button>

      <Snackbar
        open={toast.open}
        autoHideDuration={4000}
        onClose={() => setToast((t) => ({ ...t, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={toast.severity}>{toast.message}</Alert>
      </Snackbar>
    </Box>
  );
}
