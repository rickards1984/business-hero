import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box,
  Typography,
  Card,
  Chip,
  TextField,
  CircularProgress,
  Button,
  InputAdornment,
  IconButton,
  Snackbar,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Switch,
  FormControlLabel,
  Drawer,
  Divider,
  Tooltip,
  Collapse,
} from '@mui/material';
import {
  SmartToy as SmartToyIcon,
  Phone as PhoneIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
  Close as CloseIcon,
  ChevronRight as ChevronRightIcon,
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Save as SaveIcon,
  CheckCircle as CheckCircleIcon,
  Cancel as CancelIcon,
  SwapHoriz as SwapHorizIcon,
  MicNone as MicNoneIcon,
  RecordVoiceOver as RecordVoiceOverIcon,
  AccessTime as AccessTimeIcon,
  MenuBook as MenuBookIcon,
} from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';

interface ReceptionistTabProps {
  businessId: string;
}

interface ReceptionistConfig {
  id: string;
  business_id: string;
  enabled: boolean;
  twilio_phone_number: string | null;
  voice: string;
  language: string;
  personality_prompt: string | null;
  greeting_message: string;
  tone: string;
  humor_enabled: boolean;
  speaking_speed: string;
  business_hours: Record<string, { enabled: boolean; open: string; close: string }>;
  timezone: string;
  after_hours_message: string | null;
  after_hours_action: string;
  transfer_enabled: boolean;
  transfer_number: string | null;
  transfer_trigger_phrases: string | null;
  max_call_duration_seconds: number;
}

interface ReceptionistStats {
  total_receptionist_calls: number;
  today_calls: number;
  this_week_calls: number;
  handled_calls: number;
  transferred_calls: number;
  voicemail_calls: number;
  missed_calls: number;
  avg_duration_seconds: number;
}

interface VoiceOption {
  id: string;
  name: string;
  description: string;
  accent?: string;
  gender?: string;
}

interface KBItem {
  id: string;
  business_id: string;
  category: string;
  title: string;
  content: string;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

interface ReceptionistCall {
  id: string;
  business_id: string;
  caller_number: string;
  caller_name: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  transcript: string | null;
  summary: string | null;
  intent: string | null;
  outcome: string | null;
  recording_url: string | null;
  created_at: string;
}

const DEFAULT_HOURS: Record<string, { enabled: boolean; open: string; close: string }> = {
  monday: { enabled: true, open: '09:00', close: '17:00' },
  tuesday: { enabled: true, open: '09:00', close: '17:00' },
  wednesday: { enabled: true, open: '09:00', close: '17:00' },
  thursday: { enabled: true, open: '09:00', close: '17:00' },
  friday: { enabled: true, open: '09:00', close: '17:00' },
  saturday: { enabled: false, open: '10:00', close: '14:00' },
  sunday: { enabled: false, open: '10:00', close: '14:00' },
};

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

const OUTCOME_STYLES: Record<string, { color: 'success' | 'primary' | 'warning' | 'error' | 'default'; icon: string }> = {
  handled: { color: 'success', icon: '✅' },
  transferred: { color: 'primary', icon: '🔄' },
  voicemail: { color: 'warning', icon: '📩' },
  missed: { color: 'error', icon: '❌' },
  error: { color: 'error', icon: '⚠️' },
};

function formatDuration(seconds: number | null): string {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function groupCallsByDate(calls: ReceptionistCall[]): Record<string, ReceptionistCall[]> {
  const groups: Record<string, ReceptionistCall[]> = {};
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  for (const call of calls) {
    const d = new Date(call.created_at);
    d.setHours(0, 0, 0, 0);
    let label: string;
    if (d.getTime() === today.getTime()) label = 'Today';
    else if (d.getTime() === yesterday.getTime()) label = 'Yesterday';
    else label = d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
    if (!groups[label]) groups[label] = [];
    groups[label].push(call);
  }
  return groups;
}

export default function ReceptionistTab({ businessId }: ReceptionistTabProps) {
  // ---- State ----
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<ReceptionistConfig | null>(null);
  const [configExists, setConfigExists] = useState(true);
  const [stats, setStats] = useState<ReceptionistStats | null>(null);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [kbItems, setKbItems] = useState<KBItem[]>([]);
  const [kbCategories, setKbCategories] = useState<string[]>([]);
  const [calls, setCalls] = useState<ReceptionistCall[]>([]);
  const [featureEnabled, setFeatureEnabled] = useState(true);

  // Form state (mirrors config for editing)
  const [formVoice, setFormVoice] = useState('shimmer');
  const [formTone, setFormTone] = useState('professional');
  const [formSpeed, setFormSpeed] = useState('normal');
  const [formHumor, setFormHumor] = useState(false);
  const [formPersonality, setFormPersonality] = useState('');
  const [formGreeting, setFormGreeting] = useState('Hello, thank you for calling. How can I help you today?');
  const [formHours, setFormHours] = useState<Record<string, { enabled: boolean; open: string; close: string }>>(DEFAULT_HOURS);
  const [formAfterHoursAction, setFormAfterHoursAction] = useState('message');
  const [formAfterHoursMessage, setFormAfterHoursMessage] = useState('');
  const [formTransferEnabled, setFormTransferEnabled] = useState(true);
  const [formTransferNumber, setFormTransferNumber] = useState('');
  const [formTransferPhrases, setFormTransferPhrases] = useState('speak to a person, real human, manager, complaint');

  // UI state
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({ open: false, message: '', severity: 'success' });
  const [callFilter, setCallFilter] = useState<'today' | 'week' | 'month' | 'all'>('all');
  const [callSearch, setCallSearch] = useState('');
  const [selectedCall, setSelectedCall] = useState<ReceptionistCall | null>(null);
  const [callDrawerOpen, setCallDrawerOpen] = useState(false);
  const [kbFilter, setKbFilter] = useState('all');
  const [kbModalOpen, setKbModalOpen] = useState(false);
  const [kbEditing, setKbEditing] = useState<KBItem | null>(null);
  const [kbFormCategory, setKbFormCategory] = useState('general');
  const [kbFormTitle, setKbFormTitle] = useState('');
  const [kbFormContent, setKbFormContent] = useState('');
  const [kbFormActive, setKbFormActive] = useState(true);
  const [kbSaving, setKbSaving] = useState(false);
  const [kbDeleteConfirm, setKbDeleteConfirm] = useState<string | null>(null);
  const [configExpanded, setConfigExpanded] = useState(true);

  // ---- Data fetching ----
  const showSnack = useCallback((message: string, severity: 'success' | 'error') => {
    setSnackbar({ open: true, message, severity });
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/config');
      const data = await res.json();
      setConfig(data);
      setConfigExists(true);
      // Sync form state
      setFormVoice(data.voice || 'shimmer');
      setFormTone(data.tone || 'professional');
      setFormSpeed(data.speaking_speed || 'normal');
      setFormHumor(data.humor_enabled || false);
      setFormPersonality(data.personality_prompt || '');
      setFormGreeting(data.greeting_message || 'Hello, thank you for calling. How can I help you today?');
      setFormHours(data.business_hours && Object.keys(data.business_hours).length > 0 ? data.business_hours : DEFAULT_HOURS);
      setFormAfterHoursAction(data.after_hours_action || 'message');
      setFormAfterHoursMessage(data.after_hours_message || '');
      setFormTransferEnabled(data.transfer_enabled ?? true);
      setFormTransferNumber(data.transfer_number || '');
      setFormTransferPhrases(data.transfer_trigger_phrases || 'speak to a person, real human, manager, complaint');
    } catch (err: any) {
      if (err.message?.includes('403')) {
        setFeatureEnabled(false);
      } else if (err.message?.includes('404')) {
        setConfigExists(false);
      } else {
        console.error('Failed to fetch receptionist config:', err);
      }
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/stats');
      setStats(await res.json());
    } catch { /* stats may fail if feature not enabled */ }
  }, []);

  const fetchVoices = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/voices');
      setVoices(await res.json());
    } catch { /* non-critical */ }
  }, []);

  const fetchKB = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/knowledge-base');
      setKbItems(await res.json());
    } catch { /* may fail if feature not enabled */ }
  }, []);

  const fetchKBCategories = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/knowledge-base/categories');
      const data = await res.json();
      setKbCategories(Array.isArray(data) ? data.map((c: any) => c.id || c.key || c) : []);
    } catch { /* non-critical */ }
  }, []);

  const fetchCalls = useCallback(async () => {
    try {
      const res = await apiRequest('GET', `/v1/receptionist/calls?period=${callFilter}&limit=50`);
      setCalls(await res.json());
    } catch { /* may fail if feature not enabled */ }
  }, [callFilter]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      await Promise.all([fetchConfig(), fetchStats(), fetchVoices(), fetchKB(), fetchKBCategories(), fetchCalls()]);
      if (mounted) setLoading(false);
    })();
    return () => { mounted = false; };
  }, [fetchConfig, fetchStats, fetchVoices, fetchKB, fetchKBCategories, fetchCalls]);

  useEffect(() => { fetchCalls(); }, [callFilter, fetchCalls]);

  // ---- Toggle enabled ----
  const handleToggleEnabled = async () => {
    if (!config) return;
    try {
      const res = await apiRequest('PATCH', '/v1/receptionist/config/toggle');
      const data = await res.json();
      setConfig((prev) => prev ? { ...prev, enabled: data.enabled } : prev);
      showSnack(data.enabled ? 'Receptionist enabled' : 'Receptionist disabled', 'success');
    } catch (err: any) {
      showSnack(`Failed to toggle: ${err.message}`, 'error');
    }
  };

  // ---- Save config ----
  const handleSaveConfig = async () => {
    setSaving(true);
    try {
      const payload = {
        voice: formVoice,
        tone: formTone,
        speaking_speed: formSpeed,
        humor_enabled: formHumor,
        personality_prompt: formPersonality || null,
        greeting_message: formGreeting,
        business_hours: formHours,
        after_hours_action: formAfterHoursAction,
        after_hours_message: formAfterHoursMessage || null,
        transfer_enabled: formTransferEnabled,
        transfer_number: formTransferNumber || null,
        transfer_trigger_phrases: formTransferPhrases || null,
      };
      const res = await apiRequest('PUT', '/v1/receptionist/config', payload);
      const data = await res.json();
      setConfig(data);
      setConfigExists(true);
      showSnack('Configuration saved', 'success');
    } catch (err: any) {
      showSnack(`Failed to save: ${err.message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  // ---- Knowledge Base CRUD ----
  const openKBAdd = () => {
    setKbEditing(null);
    setKbFormCategory('general');
    setKbFormTitle('');
    setKbFormContent('');
    setKbFormActive(true);
    setKbModalOpen(true);
  };

  const openKBEdit = (item: KBItem) => {
    setKbEditing(item);
    setKbFormCategory(item.category);
    setKbFormTitle(item.title);
    setKbFormContent(item.content);
    setKbFormActive(item.is_active);
    setKbModalOpen(true);
  };

  const handleKBSave = async () => {
    if (!kbFormTitle.trim() || !kbFormContent.trim()) return;
    setKbSaving(true);
    try {
      const payload = { category: kbFormCategory, title: kbFormTitle, content: kbFormContent, is_active: kbFormActive };
      if (kbEditing) {
        await apiRequest('PUT', `/v1/receptionist/knowledge-base/${kbEditing.id}`, payload);
      } else {
        await apiRequest('POST', '/v1/receptionist/knowledge-base', payload);
      }
      setKbModalOpen(false);
      showSnack(kbEditing ? 'Item updated' : 'Item added', 'success');
      await fetchKB();
    } catch (err: any) {
      showSnack(`Failed to save: ${err.message}`, 'error');
    } finally {
      setKbSaving(false);
    }
  };

  const handleKBDelete = async (id: string) => {
    try {
      await apiRequest('DELETE', `/v1/receptionist/knowledge-base/${id}`);
      setKbDeleteConfirm(null);
      showSnack('Item deleted', 'success');
      await fetchKB();
    } catch (err: any) {
      showSnack(`Failed to delete: ${err.message}`, 'error');
    }
  };

  // ---- Filtered knowledge base items ----
  const filteredKB = useMemo(() => {
    if (kbFilter === 'all') return kbItems;
    return kbItems.filter((item) => item.category === kbFilter);
  }, [kbItems, kbFilter]);

  // ---- Filtered + grouped calls ----
  const filteredCalls = useMemo(() => {
    if (!callSearch.trim()) return calls;
    const q = callSearch.toLowerCase();
    return calls.filter(
      (c) =>
        (c.caller_name || '').toLowerCase().includes(q) ||
        (c.caller_number || '').includes(q) ||
        (c.summary || '').toLowerCase().includes(q),
    );
  }, [calls, callSearch]);

  const groupedCalls = useMemo(() => groupCallsByDate(filteredCalls), [filteredCalls]);

  // ---- Unique KB categories for filter tabs ----
  const usedKBCategories = useMemo(() => {
    const cats = new Set(kbItems.map((i) => i.category));
    return Array.from(cats);
  }, [kbItems]);

  // ---- Render ----

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!featureEnabled) {
    return (
      <Card sx={{ p: 4, textAlign: 'center' }}>
        <SmartToyIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
        <Typography variant="h6" gutterBottom>AI Receptionist is not available</Typography>
        <Typography color="text.secondary">
          This feature hasn't been enabled for your business yet. Contact support to get started.
        </Typography>
      </Card>
    );
  }

  return (
    <Box>
      {/* ================================================================
          SECTION 1: Status & Quick Stats
          ================================================================ */}
      <Card sx={{ p: 3, mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 2 }}>
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <SmartToyIcon color="primary" />
              <Typography variant="h6" fontWeight={600}>AI Receptionist</Typography>
            </Box>
            {config?.twilio_phone_number ? (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <PhoneIcon fontSize="small" color="action" />
                <Typography variant="body1">{config.twilio_phone_number}</Typography>
                <Chip
                  label={config.enabled ? 'Active' : 'Inactive'}
                  size="small"
                  color={config.enabled ? 'success' : 'default'}
                />
              </Box>
            ) : configExists ? (
              <Typography variant="body2" color="text.secondary">
                No phone number assigned — contact support
              </Typography>
            ) : null}
            {configExists && config && (
              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <Typography variant="body2" color="text.secondary">
                  Voice: <strong>{config.voice}</strong>
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Tone: <strong>{config.tone}</strong>
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Language: <strong>{(config.language || 'en-GB').toUpperCase()}</strong>
                </Typography>
              </Box>
            )}
          </Box>
          {configExists && config ? (
            <FormControlLabel
              control={
                <Switch
                  checked={config.enabled}
                  onChange={handleToggleEnabled}
                  color="primary"
                />
              }
              label={config.enabled ? 'ON' : 'OFF'}
              labelPlacement="start"
              sx={{ mr: 0 }}
            />
          ) : (
            <Button variant="contained" onClick={() => { setConfigExpanded(true); handleSaveConfig(); }}>
              Get Started
            </Button>
          )}
        </Box>
      </Card>

      {/* Stat cards */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="primary.main">{stats?.today_calls ?? 0}</Typography>
          <Typography variant="caption" color="text.secondary">Today's Calls</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700}>{stats?.this_week_calls ?? 0}</Typography>
          <Typography variant="caption" color="text.secondary">This Week</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="success.main">
            {stats && stats.total_receptionist_calls > 0
              ? `${Math.round((stats.handled_calls / stats.total_receptionist_calls) * 100)}%`
              : '—'}
          </Typography>
          <Typography variant="caption" color="text.secondary">Handled</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700}>{formatDuration(stats?.avg_duration_seconds ?? null)}</Typography>
          <Typography variant="caption" color="text.secondary">Avg Duration</Typography>
        </Card>
      </Box>

      {/* ================================================================
          SECTION 2: Configuration Panel
          ================================================================ */}
      <Card sx={{ mb: 3 }}>
        <Box
          sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', p: 2, cursor: 'pointer' }}
          onClick={() => setConfigExpanded(!configExpanded)}
        >
          <Typography variant="h6" fontWeight={600}>Configuration</Typography>
          {configExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
        </Box>
        <Collapse in={configExpanded}>
          <Box sx={{ px: 3, pb: 3 }}>

            {/* 2A: Voice & Personality */}
            <Card variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <RecordVoiceOverIcon color="primary" fontSize="small" />
                <Typography variant="subtitle1" fontWeight={600}>Voice & Personality</Typography>
              </Box>

              <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
                <FormControl size="small" sx={{ minWidth: 200 }}>
                  <InputLabel>Voice</InputLabel>
                  <Select value={formVoice} label="Voice" onChange={(e) => setFormVoice(e.target.value)}>
                    {voices.length > 0
                      ? voices.map((v) => (
                          <MenuItem key={v.id} value={v.id}>
                            {v.name} — {v.description}
                          </MenuItem>
                        ))
                      : <MenuItem value={formVoice}>{formVoice}</MenuItem>}
                  </Select>
                </FormControl>
                <Tooltip title="Preview coming soon">
                  <span>
                    <Button variant="outlined" size="small" disabled startIcon={<MicNoneIcon />}>
                      Preview
                    </Button>
                  </span>
                </Tooltip>
              </Box>

              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Tone</Typography>
              <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                {['professional', 'friendly', 'casual'].map((t) => (
                  <Chip
                    key={t}
                    label={t.charAt(0).toUpperCase() + t.slice(1)}
                    onClick={() => setFormTone(t)}
                    color={formTone === t ? 'primary' : 'default'}
                    variant={formTone === t ? 'filled' : 'outlined'}
                    size="small"
                  />
                ))}
              </Box>

              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Speed</Typography>
              <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                {['slow', 'normal', 'fast'].map((s) => (
                  <Chip
                    key={s}
                    label={s.charAt(0).toUpperCase() + s.slice(1)}
                    onClick={() => setFormSpeed(s)}
                    color={formSpeed === s ? 'primary' : 'default'}
                    variant={formSpeed === s ? 'filled' : 'outlined'}
                    size="small"
                  />
                ))}
              </Box>

              <FormControlLabel
                control={<Switch checked={formHumor} onChange={(e) => setFormHumor(e.target.checked)} size="small" />}
                label="Allow light humour"
                sx={{ mb: 2 }}
              />

              <TextField
                label="Custom personality instructions (optional)"
                multiline
                minRows={2}
                maxRows={4}
                fullWidth
                size="small"
                value={formPersonality}
                onChange={(e) => setFormPersonality(e.target.value.slice(0, 500))}
                placeholder='e.g., "Always mention that we offer a free trial. Be enthusiastic about our new yoga classes."'
                helperText={`${formPersonality.length}/500`}
              />
            </Card>

            {/* 2B: Greeting Message */}
            <Card variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <Typography fontSize="1.2rem">👋</Typography>
                <Typography variant="subtitle1" fontWeight={600}>Greeting Message</Typography>
              </Box>
              <TextField
                label="What the receptionist says when answering"
                multiline
                minRows={2}
                maxRows={3}
                fullWidth
                size="small"
                value={formGreeting}
                onChange={(e) => setFormGreeting(e.target.value.slice(0, 200))}
                helperText={`${formGreeting.length}/200 · Variables: {business_name}, {time_of_day}`}
              />
            </Card>

            {/* 2C: Business Hours */}
            <Card variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <AccessTimeIcon color="primary" fontSize="small" />
                <Typography variant="subtitle1" fontWeight={600}>Business Hours</Typography>
              </Box>
              {DAYS.map((day) => {
                const h = formHours[day] || { enabled: false, open: '09:00', close: '17:00' };
                return (
                  <Box key={day} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
                    <FormControlLabel
                      control={
                        <Switch
                          size="small"
                          checked={h.enabled}
                          onChange={(e) =>
                            setFormHours((prev) => ({ ...prev, [day]: { ...prev[day], enabled: e.target.checked } }))
                          }
                        />
                      }
                      label={
                        <Typography variant="body2" sx={{ width: 90, textTransform: 'capitalize' }}>
                          {day}
                        </Typography>
                      }
                      sx={{ mr: 0, width: 160 }}
                    />
                    {h.enabled ? (
                      <>
                        <input
                          type="time"
                          value={h.open}
                          onChange={(e) =>
                            setFormHours((prev) => ({ ...prev, [day]: { ...prev[day], open: e.target.value } }))
                          }
                          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}
                        />
                        <Typography variant="body2" color="text.secondary">to</Typography>
                        <input
                          type="time"
                          value={h.close}
                          onChange={(e) =>
                            setFormHours((prev) => ({ ...prev, [day]: { ...prev[day], close: e.target.value } }))
                          }
                          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}
                        />
                      </>
                    ) : (
                      <Typography variant="body2" color="text.disabled">Closed</Typography>
                    )}
                  </Box>
                );
              })}

              <Divider sx={{ my: 2 }} />

              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>After-hours behaviour</Typography>
              <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                {[
                  { value: 'message', label: 'Play message' },
                  { value: 'voicemail', label: 'Take voicemail' },
                  { value: 'transfer', label: 'Transfer to number' },
                ].map((opt) => (
                  <Chip
                    key={opt.value}
                    label={opt.label}
                    onClick={() => setFormAfterHoursAction(opt.value)}
                    color={formAfterHoursAction === opt.value ? 'primary' : 'default'}
                    variant={formAfterHoursAction === opt.value ? 'filled' : 'outlined'}
                    size="small"
                  />
                ))}
              </Box>
              <TextField
                label="After-hours message"
                multiline
                minRows={2}
                fullWidth
                size="small"
                value={formAfterHoursMessage}
                onChange={(e) => setFormAfterHoursMessage(e.target.value)}
                placeholder="We're currently closed. Our hours are Mon-Fri 9-5."
              />
            </Card>

            {/* 2D: Call Transfer */}
            <Card variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <SwapHorizIcon color="primary" fontSize="small" />
                <Typography variant="subtitle1" fontWeight={600}>Call Transfer</Typography>
              </Box>
              <FormControlLabel
                control={<Switch checked={formTransferEnabled} onChange={(e) => setFormTransferEnabled(e.target.checked)} size="small" />}
                label="Enable call transfer"
                sx={{ mb: 1 }}
              />
              {formTransferEnabled && (
                <>
                  <TextField
                    label="Transfer number"
                    size="small"
                    fullWidth
                    value={formTransferNumber}
                    onChange={(e) => setFormTransferNumber(e.target.value)}
                    placeholder="+44 1234 567890"
                    sx={{ mb: 2 }}
                  />
                  <TextField
                    label="Transfer triggers (comma separated)"
                    size="small"
                    fullWidth
                    multiline
                    minRows={1}
                    value={formTransferPhrases}
                    onChange={(e) => setFormTransferPhrases(e.target.value)}
                    placeholder="speak to a person, real human, manager, complaint"
                  />
                </>
              )}
            </Card>

            {/* Save button */}
            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button
                variant="contained"
                startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <SaveIcon />}
                onClick={handleSaveConfig}
                disabled={saving}
              >
                {saving ? 'Saving...' : 'Save Configuration'}
              </Button>
            </Box>
          </Box>
        </Collapse>
      </Card>

      {/* ================================================================
          SECTION 3: Knowledge Base Manager
          ================================================================ */}
      <Card sx={{ mb: 3, p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <MenuBookIcon color="primary" fontSize="small" />
            <Typography variant="h6" fontWeight={600}>Knowledge Base</Typography>
          </Box>
          <Button variant="outlined" size="small" startIcon={<AddIcon />} onClick={openKBAdd}>
            Add Item
          </Button>
        </Box>

        {/* Category filter tabs */}
        <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
          <Chip
            label="All"
            onClick={() => setKbFilter('all')}
            color={kbFilter === 'all' ? 'primary' : 'default'}
            variant={kbFilter === 'all' ? 'filled' : 'outlined'}
            size="small"
          />
          {usedKBCategories.map((cat) => (
            <Chip
              key={cat}
              label={cat.charAt(0).toUpperCase() + cat.slice(1).replace(/_/g, ' ')}
              onClick={() => setKbFilter(cat)}
              color={kbFilter === cat ? 'primary' : 'default'}
              variant={kbFilter === cat ? 'filled' : 'outlined'}
              size="small"
            />
          ))}
        </Box>

        {/* Item list */}
        {filteredKB.length === 0 ? (
          <Card variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
            <MenuBookIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
            <Typography color="text.secondary">
              No knowledge base items yet. Add your business information so the AI receptionist can answer caller questions accurately.
            </Typography>
          </Card>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {filteredKB.map((item) => (
              <Card key={item.id} variant="outlined" sx={{ p: 2, opacity: item.is_active ? 1 : 0.5 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      <Chip
                        label={item.category.charAt(0).toUpperCase() + item.category.slice(1).replace(/_/g, ' ')}
                        size="small"
                        variant="outlined"
                        color="primary"
                      />
                      {!item.is_active && <Chip label="Inactive" size="small" color="default" />}
                    </Box>
                    <Typography variant="subtitle2" fontWeight={600}>{item.title}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                      {item.content.length > 200 ? item.content.slice(0, 200) + '...' : item.content}
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', gap: 0.5, ml: 1, flexShrink: 0 }}>
                    <IconButton size="small" onClick={() => openKBEdit(item)}><EditIcon fontSize="small" /></IconButton>
                    <IconButton size="small" onClick={() => setKbDeleteConfirm(item.id)} color="error"><DeleteIcon fontSize="small" /></IconButton>
                  </Box>
                </Box>
              </Card>
            ))}
          </Box>
        )}
      </Card>

      {/* KB Add/Edit Modal */}
      <Dialog open={kbModalOpen} onClose={() => setKbModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{kbEditing ? 'Edit Knowledge Base Item' : 'Add Knowledge Base Item'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Category</InputLabel>
            <Select value={kbFormCategory} label="Category" onChange={(e) => setKbFormCategory(e.target.value)}>
              {(kbCategories.length > 0 ? kbCategories : ['general', 'services', 'pricing', 'hours', 'faqs', 'policies', 'location']).map((c) => (
                <MenuItem key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1).replace(/_/g, ' ')}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Title"
            size="small"
            fullWidth
            value={kbFormTitle}
            onChange={(e) => setKbFormTitle(e.target.value)}
            placeholder="e.g., Gym Membership Options"
          />
          <TextField
            label="Content"
            size="small"
            fullWidth
            multiline
            minRows={4}
            value={kbFormContent}
            onChange={(e) => setKbFormContent(e.target.value)}
            placeholder="Write the information your AI receptionist should know about this topic..."
          />
          <FormControlLabel
            control={<Switch checked={kbFormActive} onChange={(e) => setKbFormActive(e.target.checked)} size="small" />}
            label="Active"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setKbModalOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleKBSave}
            disabled={kbSaving || !kbFormTitle.trim() || !kbFormContent.trim()}
            startIcon={kbSaving ? <CircularProgress size={16} color="inherit" /> : undefined}
          >
            {kbSaving ? 'Saving...' : 'Save Item'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* KB Delete Confirmation */}
      <Dialog open={!!kbDeleteConfirm} onClose={() => setKbDeleteConfirm(null)}>
        <DialogTitle>Delete Item</DialogTitle>
        <DialogContent>
          <Typography>Are you sure you want to delete this knowledge base item? This cannot be undone.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setKbDeleteConfirm(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={() => kbDeleteConfirm && handleKBDelete(kbDeleteConfirm)}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      {/* ================================================================
          SECTION 4: Recent Receptionist Calls
          ================================================================ */}
      <Card sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
          <PhoneIcon color="primary" fontSize="small" />
          <Typography variant="h6" fontWeight={600}>Recent Receptionist Calls</Typography>
        </Box>

        {/* Time filter chips */}
        <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
          {[
            { value: 'today' as const, label: 'Today' },
            { value: 'week' as const, label: 'This Week' },
            { value: 'month' as const, label: 'This Month' },
            { value: 'all' as const, label: 'All Time' },
          ].map((f) => (
            <Chip
              key={f.value}
              label={f.label}
              onClick={() => setCallFilter(f.value)}
              color={callFilter === f.value ? 'primary' : 'default'}
              variant={callFilter === f.value ? 'filled' : 'outlined'}
              size="small"
            />
          ))}
        </Box>

        {/* Search */}
        <TextField
          placeholder="Search by caller name, number, or summary..."
          value={callSearch}
          onChange={(e) => setCallSearch(e.target.value)}
          size="small"
          fullWidth
          sx={{ mb: 2 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start"><SearchIcon color="action" /></InputAdornment>
            ),
            endAdornment: callSearch && (
              <InputAdornment position="end">
                <IconButton size="small" onClick={() => setCallSearch('')}><ClearIcon fontSize="small" /></IconButton>
              </InputAdornment>
            ),
          }}
        />

        {/* Call list */}
        {filteredCalls.length === 0 ? (
          <Card variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
            <SmartToyIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
            <Typography color="text.secondary">
              {callSearch || callFilter !== 'all'
                ? 'No calls match your filters'
                : 'No receptionist calls yet. Once your AI receptionist is active and receiving calls, they\'ll appear here with full transcripts.'}
            </Typography>
          </Card>
        ) : (
          <Box>
            {Object.entries(groupedCalls).map(([date, dateCalls]) => (
              <Box key={date} sx={{ mb: 3 }}>
                <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, ml: 1 }}>
                  {date} ({dateCalls.length} {dateCalls.length === 1 ? 'call' : 'calls'})
                </Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {dateCalls.map((call) => (
                    <Card
                      key={call.id}
                      sx={{
                        p: 2,
                        cursor: 'pointer',
                        '&:hover': { boxShadow: 2, bgcolor: 'action.hover' },
                        transition: 'all 0.2s',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 2,
                      }}
                      onClick={() => { setSelectedCall(call); setCallDrawerOpen(true); }}
                    >
                      {/* AI Icon */}
                      <Box
                        sx={{
                          width: 40,
                          height: 40,
                          borderRadius: '50%',
                          bgcolor: 'primary.light',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexShrink: 0,
                        }}
                      >
                        <SmartToyIcon color="primary" fontSize="small" />
                      </Box>

                      {/* Main content */}
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="subtitle1" fontWeight={600} noWrap>
                          {call.caller_name || 'Unknown Caller'}
                        </Typography>
                        <Typography variant="body2" color="text.secondary" noWrap>
                          {call.caller_number || 'No number'}
                          {call.summary && ` · ${call.summary.substring(0, 60)}...`}
                        </Typography>
                      </Box>

                      {/* Right side */}
                      <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                        <Typography variant="caption" color="text.secondary">
                          {new Date(call.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                        </Typography>
                        {call.outcome && (
                          <Box>
                            <Chip
                              label={`${OUTCOME_STYLES[call.outcome]?.icon || ''} ${call.outcome}`}
                              size="small"
                              color={OUTCOME_STYLES[call.outcome]?.color || 'default'}
                              variant="outlined"
                            />
                          </Box>
                        )}
                      </Box>

                      <ChevronRightIcon color="action" />
                    </Card>
                  ))}
                </Box>
              </Box>
            ))}
          </Box>
        )}
      </Card>

      {/* ================================================================
          Call Detail Drawer
          ================================================================ */}
      <Drawer anchor="right" open={callDrawerOpen} onClose={() => { setCallDrawerOpen(false); setSelectedCall(null); }}>
        <Box sx={{ width: { xs: '100vw', sm: 450 }, p: 3 }}>
          {selectedCall && (
            <>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <SmartToyIcon color="primary" />
                  <Typography variant="h6" fontWeight={600}>Call Details</Typography>
                </Box>
                <IconButton onClick={() => { setCallDrawerOpen(false); setSelectedCall(null); }}>
                  <CloseIcon />
                </IconButton>
              </Box>

              {/* Caller info */}
              <Card sx={{ p: 2, mb: 3, bgcolor: 'primary.light' }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>Caller</Typography>
                <Typography variant="h5" fontWeight={600}>{selectedCall.caller_name || 'Unknown Caller'}</Typography>
                {selectedCall.caller_number && (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
                    <PhoneIcon fontSize="small" color="action" />
                    <Typography variant="body1">{selectedCall.caller_number}</Typography>
                  </Box>
                )}
              </Card>

              {/* Date & Duration */}
              <Box sx={{ mb: 3 }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>Date & Time</Typography>
                <Typography variant="body1">
                  {new Date(selectedCall.created_at).toLocaleDateString('en-GB', {
                    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
                  })}{' '}
                  at{' '}
                  {new Date(selectedCall.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                </Typography>
                {selectedCall.duration_seconds != null && (
                  <Typography variant="caption" color="text.secondary">
                    Duration: {formatDuration(selectedCall.duration_seconds)}
                  </Typography>
                )}
              </Box>

              {/* Outcome */}
              {selectedCall.outcome && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Outcome</Typography>
                  <Chip
                    label={`${OUTCOME_STYLES[selectedCall.outcome]?.icon || ''} ${selectedCall.outcome}`}
                    color={OUTCOME_STYLES[selectedCall.outcome]?.color || 'default'}
                    variant="outlined"
                  />
                </Box>
              )}

              {/* Intent */}
              {selectedCall.intent && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Intent</Typography>
                  <Chip label={selectedCall.intent} color="primary" variant="outlined" />
                </Box>
              )}

              {/* Summary */}
              {selectedCall.summary && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Summary</Typography>
                  <Card sx={{ p: 2, bgcolor: 'grey.50' }}>
                    <Typography variant="body2">{selectedCall.summary}</Typography>
                  </Card>
                </Box>
              )}

              {/* Transcript */}
              {selectedCall.transcript && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Transcript</Typography>
                  <Card sx={{ p: 2, bgcolor: 'grey.50', maxHeight: 300, overflow: 'auto' }}>
                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                      {selectedCall.transcript}
                    </Typography>
                  </Card>
                </Box>
              )}

              {/* No details fallback */}
              {!selectedCall.summary && !selectedCall.transcript && !selectedCall.intent && (
                <Card sx={{ p: 3, textAlign: 'center', bgcolor: 'grey.50', mb: 3 }}>
                  <Typography color="text.secondary">No additional details available for this call.</Typography>
                </Card>
              )}
            </>
          )}
        </Box>
      </Drawer>

      {/* ================================================================
          Snackbar
          ================================================================ */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={snackbar.severity} onClose={() => setSnackbar((s) => ({ ...s, open: false }))}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
