import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Box,
  Typography,
  Card,
  Chip,
  TextField,
  CircularProgress,
  Button,
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
  Divider,
  Tooltip,
  Collapse,
} from '@mui/material';
import {
  SmartToy as SmartToyIcon,
  Phone as PhoneIcon,
  ChevronRight as ChevronRightIcon,
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Save as SaveIcon,
  CheckCircle as CheckCircleIcon,
  SwapHoriz as SwapHorizIcon,
  MicNone as MicNoneIcon,
  RecordVoiceOver as RecordVoiceOverIcon,
  AccessTime as AccessTimeIcon,
  MenuBook as MenuBookIcon,
} from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';

interface ReceptionistTabProps {
  businessId: string;
  onViewCalls?: () => void;
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
  recommended?: boolean;
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

function formatDuration(seconds: number | null): string {
  if (!seconds) return '\u2014';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function ReceptionistTab({ businessId, onViewCalls }: ReceptionistTabProps) {
  // ---- State ----
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<ReceptionistConfig | null>(null);
  const [configExists, setConfigExists] = useState(true);
  const [stats, setStats] = useState<ReceptionistStats | null>(null);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [kbItems, setKbItems] = useState<KBItem[]>([]);
  const [kbCategories, setKbCategories] = useState<string[]>([]);
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

  // Setup wizard state (Option B — guided setup card)
  const [setupStep, setSetupStep] = useState(0);
  const [setupVoice, setSetupVoice] = useState('shimmer');
  const [setupGreeting, setSetupGreeting] = useState('Hello, thank you for calling {business_name}. How can I help you today?');
  const [setupFaq1, setSetupFaq1] = useState('');
  const [setupFaq2, setSetupFaq2] = useState('');
  const [setupFaq3, setSetupFaq3] = useState('');
  const [setupSaving, setSetupSaving] = useState(false);
  const [setupDismissed, setSetupDismissed] = useState(false);

  // Voice preview
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [previewVoiceId, setPreviewVoiceId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const showSnack = useCallback((message: string, severity: 'success' | 'error') => {
    setSnackbar({ open: true, message, severity });
  }, []);

  const playPreview = useCallback(async (voiceId: string) => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (previewVoiceId === voiceId && previewPlaying) {
      setPreviewPlaying(false);
      setPreviewVoiceId(null);
      return;
    }
    setPreviewPlaying(true);
    setPreviewVoiceId(voiceId);
    try {
      const res = await apiRequest('GET', `/v1/receptionist/voices/${voiceId}/preview`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => { setPreviewPlaying(false); setPreviewVoiceId(null); };
      audio.onerror = () => { setPreviewPlaying(false); setPreviewVoiceId(null); showSnack('Voice preview not available. Please try another voice.', 'error'); };
      await audio.play();
    } catch {
      setPreviewPlaying(false);
      setPreviewVoiceId(null);
      showSnack('Failed to load voice preview.', 'error');
    }
  }, [previewVoiceId, previewPlaying, showSnack]);

  useEffect(() => {
    return () => { if (audioRef.current) audioRef.current.pause(); };
  }, []);

  // ---- Data fetching ----
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

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      await Promise.all([fetchConfig(), fetchStats(), fetchVoices(), fetchKB(), fetchKBCategories()]);
      if (mounted) setLoading(false);
    })();
    return () => { mounted = false; };
  }, [fetchConfig, fetchStats, fetchVoices, fetchKB, fetchKBCategories]);

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

  // ---- Setup wizard: complete ----
  const handleCompleteSetup = async () => {
    setSetupSaving(true);
    try {
      await apiRequest('PUT', '/v1/receptionist/config', {
        voice: setupVoice,
        greeting_message: setupGreeting,
      });

      const faqs = [
        { category: 'hours', title: 'Opening Hours', content: setupFaq1 },
        { category: 'services', title: 'Services Offered', content: setupFaq2 },
        { category: 'pricing', title: 'Pricing Information', content: setupFaq3 },
      ];
      for (const faq of faqs) {
        if (faq.content.trim()) {
          try {
            await apiRequest('POST', '/v1/receptionist/knowledge-base', faq);
          } catch { /* silently skip individual FAQ failures */ }
        }
      }

      showSnack('Your AI receptionist is configured! An admin will assign a phone number to activate it.', 'success');
      await fetchConfig();
      await fetchKB();
    } catch (err: any) {
      showSnack(`Setup failed: ${err.message}`, 'error');
    } finally {
      setSetupSaving(false);
    }
  };

  // ---- Filtered knowledge base items ----
  const filteredKB = useMemo(() => {
    if (kbFilter === 'all') return kbItems;
    return kbItems.filter((item) => item.category === kbFilter);
  }, [kbItems, kbFilter]);

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
        <Typography variant="h6" gutterBottom>AI Receptionist</Typography>
        <Typography color="text.secondary">
          This feature isn't available on your current plan. Contact us to learn more about AI call handling.
        </Typography>
      </Card>
    );
  }

  // ---- Setup wizard card (Option B) ----
  if (!configExists && !setupDismissed) {
    const selectedVoice = voices.find((v) => v.id === setupVoice);
    return (
      <Box>
        <Card sx={{ p: 4, mb: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
              <SmartToyIcon color="primary" />
              <Typography variant="h6" fontWeight={600}>Get Started with Your AI Receptionist</Typography>
            </Box>
            <Button size="small" onClick={() => setSetupDismissed(true)} sx={{ textTransform: 'none', color: 'text.secondary' }}>
              I'll do this later
            </Button>
          </Box>
          <Typography color="text.secondary" sx={{ mb: 3 }}>
            Set up your AI receptionist in 3 easy steps to start answering calls automatically.
          </Typography>

          <Typography variant="subtitle2" color="primary" sx={{ mb: 2 }}>
            Step {setupStep + 1} of 3
          </Typography>

          {setupStep === 0 && (
            <Box>
              <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>1. Choose a Voice</Typography>
              <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'flex-start' }}>
                <FormControl size="small" sx={{ flex: 1 }}>
                  <InputLabel>Voice</InputLabel>
                  <Select value={setupVoice} label="Voice" onChange={(e) => setSetupVoice(e.target.value)}>
                    {voices.length > 0
                      ? voices.map((v) => (
                          <MenuItem key={v.id} value={v.id}>{v.name} — {v.description}{v.recommended ? ' ⭐ Recommended' : ''}</MenuItem>
                        ))
                      : <MenuItem value="shimmer">Shimmer</MenuItem>}
                  </Select>
                </FormControl>
                <button
                  className={`voice-preview-btn${previewPlaying && previewVoiceId === setupVoice ? ' voice-preview-btn--playing' : ''}`}
                  onClick={() => playPreview(setupVoice)}
                  style={{ marginTop: 2 }}
                >
                  {previewPlaying && previewVoiceId === setupVoice ? '■ Stop' : '▶ Preview'}
                </button>
              </Box>
              {selectedVoice && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {selectedVoice.name} — {selectedVoice.description}
                </Typography>
              )}
              <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Button variant="contained" onClick={() => setSetupStep(1)}>Next</Button>
              </Box>
            </Box>
          )}

          {setupStep === 1 && (
            <Box>
              <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>2. Set Your Greeting</Typography>
              <TextField
                multiline
                minRows={2}
                maxRows={4}
                fullWidth
                size="small"
                value={setupGreeting}
                onChange={(e) => setSetupGreeting(e.target.value.slice(0, 200))}
                helperText={`${setupGreeting.length}/200`}
                sx={{ mb: 2 }}
              />
              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Button onClick={() => setSetupStep(0)}>Back</Button>
                <Button variant="contained" onClick={() => setSetupStep(2)}>Next</Button>
              </Box>
            </Box>
          )}

          {setupStep === 2 && (
            <Box>
              <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
                3. Add your top 3 FAQs
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Help your AI receptionist answer caller questions accurately. Leave blank to skip.
              </Typography>

              <Typography variant="body2" fontWeight={500} sx={{ mb: 0.5 }}>What are your opening hours?</Typography>
              <TextField
                size="small"
                fullWidth
                multiline
                minRows={1}
                value={setupFaq1}
                onChange={(e) => setSetupFaq1(e.target.value)}
                placeholder="e.g., Monday to Friday 9am-5pm, Saturday 10am-2pm"
                sx={{ mb: 2 }}
              />

              <Typography variant="body2" fontWeight={500} sx={{ mb: 0.5 }}>What services do you offer?</Typography>
              <TextField
                size="small"
                fullWidth
                multiline
                minRows={1}
                value={setupFaq2}
                onChange={(e) => setSetupFaq2(e.target.value)}
                placeholder="e.g., We offer personal training, group classes, and nutrition plans"
                sx={{ mb: 2 }}
              />

              <Typography variant="body2" fontWeight={500} sx={{ mb: 0.5 }}>What are your prices?</Typography>
              <TextField
                size="small"
                fullWidth
                multiline
                minRows={1}
                value={setupFaq3}
                onChange={(e) => setSetupFaq3(e.target.value)}
                placeholder="e.g., Monthly membership £30, Annual £300, Student £20/month"
                sx={{ mb: 2 }}
              />

              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Button onClick={() => setSetupStep(1)}>Back</Button>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button onClick={() => setSetupDismissed(true)} sx={{ textTransform: 'none' }}>
                    Skip for now
                  </Button>
                  <Button
                    variant="contained"
                    onClick={handleCompleteSetup}
                    disabled={setupSaving}
                    startIcon={setupSaving ? <CircularProgress size={16} color="inherit" /> : undefined}
                  >
                    {setupSaving ? 'Saving...' : 'Complete Setup'}
                  </Button>
                </Box>
              </Box>
            </Box>
          )}
        </Card>

        {/* Snackbar for setup */}
        <Snackbar
          open={snackbar.open}
          autoHideDuration={6000}
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

  // ---- Bare empty state if setup was dismissed ----
  if (!configExists && setupDismissed) {
    return (
      <Box>
        <Card sx={{ p: 4, textAlign: 'center' }}>
          <SmartToyIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
          <Typography variant="h6" gutterBottom>Your AI Receptionist isn't set up yet</Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }}>
            Set up your AI receptionist to automatically answer calls, take messages, and help callers 24/7.
          </Typography>
          <Button variant="contained" onClick={() => { setSetupDismissed(false); setSetupStep(0); }}>
            Get Started
          </Button>
        </Card>
      </Box>
    );
  }

  return (
    <Box>
      {/* ================================================================
          Contextual banners based on config state
          ================================================================ */}
      {configExists && config && !config.twilio_phone_number && (
        <Alert severity="info" sx={{ mb: 2 }} icon={<CheckCircleIcon />}>
          Your AI receptionist is configured and ready to go. A phone number will be assigned shortly — we'll let you know when it's live.
        </Alert>
      )}

      {configExists && config && config.twilio_phone_number && !config.enabled && (
        <Alert
          severity="warning"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={handleToggleEnabled}>
              Turn On
            </Button>
          }
        >
          Your AI receptionist is currently turned off. Switch it on to start answering calls.
        </Alert>
      )}

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
            ) : (
              <Typography variant="body2" color="text.secondary">
                No phone number assigned — contact support
              </Typography>
            )}
            {config && (
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
          {config && (
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
                            {v.name} — {v.description}{v.recommended ? ' ⭐ Recommended' : ''}
                          </MenuItem>
                        ))
                      : <MenuItem value={formVoice}>{formVoice}</MenuItem>}
                  </Select>
                </FormControl>
                <button
                  className={`voice-preview-btn${previewPlaying && previewVoiceId === formVoice ? ' voice-preview-btn--playing' : ''}`}
                  onClick={() => playPreview(formVoice)}
                >
                  {previewPlaying && previewVoiceId === formVoice ? '■ Stop' : '▶ Preview'}
                </button>
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
          SECTION 4: Recent Activity (compact summary + link to Calls tab)
          ================================================================ */}
      <Card sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
          <PhoneIcon color="primary" fontSize="small" />
          <Typography variant="h6" fontWeight={600}>Recent Activity</Typography>
        </Box>

        <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap', mb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Today: <strong>{stats?.today_calls ?? 0} calls</strong>
          </Typography>
          <Typography variant="body2" color="text.secondary">
            This week: <strong>{stats?.this_week_calls ?? 0} calls</strong>
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Handled: <strong>
              {stats && stats.total_receptionist_calls > 0
                ? `${Math.round((stats.handled_calls / stats.total_receptionist_calls) * 100)}%`
                : '\u2014'}
            </strong>
          </Typography>
        </Box>

        {onViewCalls && (
          <Button
            variant="text"
            size="small"
            endIcon={<ChevronRightIcon />}
            onClick={onViewCalls}
            sx={{ textTransform: 'none' }}
          >
            View all calls
          </Button>
        )}
      </Card>

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
