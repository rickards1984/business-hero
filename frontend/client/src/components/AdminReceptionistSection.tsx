import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box,
  Typography,
  Chip,
  Button,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Switch,
  FormControlLabel,
  Divider,
  Card,
  Alert,
  Snackbar,
  IconButton,
  Drawer,
} from '@mui/material';
import {
  SmartToy as SmartToyIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Add as AddIcon,
  Close as CloseIcon,
  Save as SaveIcon,
  ChevronRight as ChevronRightIcon,
} from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';
import { isFeatureEnabled } from '@/lib/entitlements';

interface AdminReceptionistSectionProps {
  businessId: string;
  // Both, always. ENTITLEMENT-SPEC PART C makes `plan_tier` the source of
  // truth and `featureFlags` the exceptions to it; neither answers on its own.
  planTier?: string | null;
  featureFlags?: Record<string, any>;
  onFeatureFlagChange?: () => void;
}

interface ReceptionistConfig {
  id: string;
  business_id: string;
  enabled: boolean;
  twilio_phone_number: string | null;
  twilio_phone_sid: string | null;
  voice: string;
  voice_preset_id: string | null;
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

interface KBItem {
  id: string;
  category: string;
  title: string;
  content: string;
  is_active: boolean;
}

interface ReceptionistCall {
  id: string;
  caller_number: string;
  caller_name: string | null;
  duration_seconds: number | null;
  summary: string | null;
  outcome: string | null;
  transcript: string | null;
  intent: string | null;
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

const OUTCOME_COLORS: Record<string, 'success' | 'primary' | 'warning' | 'error' | 'default'> = {
  handled: 'success',
  transferred: 'primary',
  voicemail: 'warning',
  missed: 'error',
  error: 'error',
};

function formatDuration(s: number | null): string {
  if (!s) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

export default function AdminReceptionistSection({ businessId, planTier, featureFlags, onFeatureFlagChange }: AdminReceptionistSectionProps) {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<ReceptionistConfig | null>(null);
  const [kbItems, setKbItems] = useState<KBItem[]>([]);
  const [calls, setCalls] = useState<ReceptionistCall[]>([]);
  const [, setVoices] = useState<{ id: string; name: string; description: string }[]>([]);
  const [presets, setPresets] = useState<Array<{
    id: string;
    label: string;
    description?: string;
    base_voice: string;
    accent_group: string;
    verified?: boolean;
    recommended?: boolean;
  }>>([]);
  const [kbCategories, setKbCategories] = useState<string[]>([]);

  const [phoneDialogOpen, setPhoneDialogOpen] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState('');
  const [phoneSid, setPhoneSid] = useState('');
  const [phoneSaving, setPhoneSaving] = useState(false);

  const [configDialogOpen, setConfigDialogOpen] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [formVoice, setFormVoice] = useState('shimmer');
  const [formTone, setFormTone] = useState('professional');
  const [formSpeed, setFormSpeed] = useState('normal');
  const [formHumor, setFormHumor] = useState(false);
  const [formPersonality, setFormPersonality] = useState('');
  const [formGreeting, setFormGreeting] = useState('Hello, thank you for calling. How can I help you today?');
  const [formHours, setFormHours] = useState<Record<string, { enabled: boolean; open: string; close: string }>>(DEFAULT_HOURS);
  const [formAfterHoursAction, setFormAfterHoursAction] = useState('message');
  const [formAfterHoursMsg, setFormAfterHoursMsg] = useState('');
  const [formTransferEnabled, setFormTransferEnabled] = useState(true);
  const [formTransferNumber, setFormTransferNumber] = useState('');
  const [formTransferPhrases, setFormTransferPhrases] = useState('');

  const [callsDialogOpen, setCallsDialogOpen] = useState(false);
  const [selectedCall, setSelectedCall] = useState<ReceptionistCall | null>(null);
  const [callDrawerOpen, setCallDrawerOpen] = useState(false);

  const [kbDialogOpen, setKbDialogOpen] = useState(false);
  const [kbEditItem, setKbEditItem] = useState<KBItem | null>(null);
  const [kbModalOpen, setKbModalOpen] = useState(false);
  const [kbFormCategory, setKbFormCategory] = useState('general');
  const [kbFormTitle, setKbFormTitle] = useState('');
  const [kbFormContent, setKbFormContent] = useState('');
  const [kbFormActive, setKbFormActive] = useState(true);
  const [kbSaving, setKbSaving] = useState(false);

  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({ open: false, message: '', severity: 'success' });
  const [togglingFlag, setTogglingFlag] = useState(false);

  // PART D. Reading the flag raw showed "Enable Feature" for a pro business
  // that already had it, and pressing that button wrote the plan default
  // back into the column — the repair path recreating the fault.
  const receptionistEnabled = isFeatureEnabled(planTier, featureFlags, 'receptionist');

  const showSnack = useCallback((message: string, severity: 'success' | 'error') => {
    setSnackbar({ open: true, message, severity });
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await apiRequest('GET', `/v1/admin/receptionist/${businessId}/config`);
      setConfig(await res.json());
    } catch {
      setConfig(null);
    }
  }, [businessId]);

  const fetchKB = useCallback(async () => {
    try {
      const res = await apiRequest('GET', `/v1/admin/receptionist/${businessId}/knowledge-base`);
      setKbItems(await res.json());
    } catch { /* ignore */ }
  }, [businessId]);

  const fetchCalls = useCallback(async () => {
    try {
      const res = await apiRequest('GET', `/v1/receptionist/calls?period=all&limit=20`);
      setCalls(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchVoices = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/voices');
      setVoices(await res.json());
    } catch { /* non-critical */ }
    try {
      const r = await apiRequest('GET', '/v1/receptionist/voice-presets');
      const data = await r.json();
      if (Array.isArray(data)) setPresets(data);
    } catch { /* ignore */ }
  }, []);

  const fetchKBCategories = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/knowledge-base/categories');
      const data = await res.json();
      setKbCategories(Array.isArray(data) ? data.map((c: any) => c.id || c.key || c) : []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      await Promise.all([fetchConfig(), fetchKB(), fetchVoices(), fetchKBCategories()]);
      if (mounted) setLoading(false);
    })();
    return () => { mounted = false; };
  }, [fetchConfig, fetchKB, fetchVoices, fetchKBCategories]);

  // ---- Feature flag toggle ----
  const handleToggleFeatureFlag = async () => {
    setTogglingFlag(true);
    try {
      await apiRequest('PUT', `/v1/admin/receptionist/${businessId}/feature-flag`, { enabled: !receptionistEnabled });
      showSnack(receptionistEnabled ? 'Feature disabled' : 'Feature enabled', 'success');
      onFeatureFlagChange?.();
    } catch (err: any) {
      showSnack(`Failed: ${err.message}`, 'error');
    } finally {
      setTogglingFlag(false);
    }
  };

  // ---- Phone number ----
  const openPhoneDialog = () => {
    setPhoneNumber(config?.twilio_phone_number || '');
    setPhoneSid(config?.twilio_phone_sid || '');
    setPhoneDialogOpen(true);
  };

  const handleSavePhone = async () => {
    setPhoneSaving(true);
    try {
      await apiRequest('PUT', `/v1/admin/receptionist/${businessId}/phone-number`, {
        twilio_phone_number: phoneNumber,
        twilio_phone_sid: phoneSid || null,
      });
      setPhoneDialogOpen(false);
      showSnack('Phone number assigned', 'success');
      await fetchConfig();
    } catch (err: any) {
      showSnack(`Failed: ${err.message}`, 'error');
    } finally {
      setPhoneSaving(false);
    }
  };

  // ---- Config edit ----
  const openConfigDialog = () => {
    if (config) {
      // Prefer voice_preset_id (canonical). Fall back to legacy voice column
      // mapped to its British-Standard variant to mirror migration 027.
      const presetFromConfig =
        (config.voice_preset_id && String(config.voice_preset_id)) ||
        (config.voice ? `${config.voice}_british` : 'shimmer_british');
      setFormVoice(presetFromConfig);
      setFormTone(config.tone || 'professional');
      setFormSpeed(config.speaking_speed || 'normal');
      setFormHumor(config.humor_enabled || false);
      setFormPersonality(config.personality_prompt || '');
      setFormGreeting(config.greeting_message || 'Hello, thank you for calling. How can I help you today?');
      setFormHours(config.business_hours && Object.keys(config.business_hours).length > 0 ? config.business_hours : DEFAULT_HOURS);
      setFormAfterHoursAction(config.after_hours_action || 'message');
      setFormAfterHoursMsg(config.after_hours_message || '');
      setFormTransferEnabled(config.transfer_enabled ?? true);
      setFormTransferNumber(config.transfer_number || '');
      setFormTransferPhrases(config.transfer_trigger_phrases || '');
    }
    setConfigDialogOpen(true);
  };

  const handleSaveConfig = async () => {
    setConfigSaving(true);
    try {
      const presetMeta = presets.find((p) => p.id === formVoice);
      const baseVoice = presetMeta?.base_voice || formVoice.split('_')[0] || 'shimmer';
      await apiRequest('PUT', `/v1/admin/receptionist/${businessId}/config`, {
        voice: baseVoice,
        voice_preset_id: formVoice,
        tone: formTone,
        speaking_speed: formSpeed,
        humor_enabled: formHumor,
        personality_prompt: formPersonality || null,
        greeting_message: formGreeting,
        business_hours: formHours,
        after_hours_action: formAfterHoursAction,
        after_hours_message: formAfterHoursMsg || null,
        transfer_enabled: formTransferEnabled,
        transfer_number: formTransferNumber || null,
        transfer_trigger_phrases: formTransferPhrases || null,
      });
      setConfigDialogOpen(false);
      showSnack('Configuration saved', 'success');
      await fetchConfig();
    } catch (err: any) {
      showSnack(`Failed: ${err.message}`, 'error');
    } finally {
      setConfigSaving(false);
    }
  };

  // ---- View Calls ----
  const openCallsDialog = async () => {
    setCallsDialogOpen(true);
    await fetchCalls();
  };

  // ---- Knowledge Base CRUD ----
  const openKBDialog = () => { setKbDialogOpen(true); };

  const openKBAdd = () => {
    setKbEditItem(null);
    setKbFormCategory('general');
    setKbFormTitle('');
    setKbFormContent('');
    setKbFormActive(true);
    setKbModalOpen(true);
  };

  const openKBEdit = (item: KBItem) => {
    setKbEditItem(item);
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
      if (kbEditItem) {
        await apiRequest('PUT', `/v1/receptionist/knowledge-base/${kbEditItem.id}`, payload);
      } else {
        await apiRequest('POST', `/v1/admin/receptionist/${businessId}/knowledge-base`, payload);
      }
      setKbModalOpen(false);
      showSnack(kbEditItem ? 'Item updated' : 'Item added', 'success');
      await fetchKB();
    } catch (err: any) {
      showSnack(`Failed: ${err.message}`, 'error');
    } finally {
      setKbSaving(false);
    }
  };

  const handleKBDelete = async (id: string) => {
    try {
      await apiRequest('DELETE', `/v1/receptionist/knowledge-base/${id}`);
      showSnack('Item deleted', 'success');
      await fetchKB();
    } catch (err: any) {
      showSnack(`Failed: ${err.message}`, 'error');
    }
  };

  // ---- Status label ----
  const statusLabel = useMemo(() => {
    if (!receptionistEnabled) return { label: 'Not set up', color: 'default' as const };
    if (config?.enabled) return { label: 'Active', color: 'success' as const };
    if (config) return { label: 'Configured', color: 'warning' as const };
    return { label: 'Not set up', color: 'default' as const };
  }, [receptionistEnabled, config]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1 }}>
        <CircularProgress size={16} />
        <Typography variant="body2" color="text.secondary">Loading receptionist...</Typography>
      </Box>
    );
  }

  return (
    <>
      {/* Integration row — matching Awaz/Email/Calendar pattern */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center' }}>
        <Chip label={`Receptionist: ${statusLabel.label}`} color={statusLabel.color} />
        <Typography variant="body2" color="text.secondary">
          Phone: {config?.twilio_phone_number || 'No number assigned'}
        </Typography>
        {config && (
          <>
            <Typography variant="body2" color="text.secondary">
              Voice: {config.voice} | Tone: {config.tone}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              KB: {kbItems.length} items
            </Typography>
          </>
        )}
      </Box>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
        <Button
          variant="outlined"
          size="small"
          onClick={handleToggleFeatureFlag}
          disabled={togglingFlag}
          color={receptionistEnabled ? 'warning' : 'primary'}
        >
          {togglingFlag ? 'Updating...' : receptionistEnabled ? 'Disable Feature' : 'Enable Feature'}
        </Button>
        <Button variant="outlined" size="small" onClick={openPhoneDialog}>
          Assign Phone
        </Button>
        <Button variant="outlined" size="small" onClick={openConfigDialog}>
          Edit Config
        </Button>
        <Button variant="outlined" size="small" onClick={openCallsDialog}>
          View Calls
        </Button>
        <Button variant="outlined" size="small" onClick={openKBDialog}>
          Knowledge Base
        </Button>
      </Box>

      {/* ========== Phone Number Dialog ========== */}
      <Dialog open={phoneDialogOpen} onClose={() => setPhoneDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Assign Phone Number</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
          <Typography variant="body2" color="text.secondary">
            Enter the Twilio phone number purchased for this business.
          </Typography>
          <TextField
            label="Twilio Phone Number"
            size="small"
            fullWidth
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            placeholder="+44 1234 567890"
          />
          <TextField
            label="Twilio Phone SID (optional)"
            size="small"
            fullWidth
            value={phoneSid}
            onChange={(e) => setPhoneSid(e.target.value)}
            placeholder="PN..."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPhoneDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSavePhone}
            disabled={phoneSaving || !phoneNumber.trim()}
            startIcon={phoneSaving ? <CircularProgress size={16} color="inherit" /> : undefined}
          >
            {phoneSaving ? 'Saving...' : 'Assign Number'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ========== Config Edit Dialog ========== */}
      <Dialog open={configDialogOpen} onClose={() => setConfigDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Receptionist Configuration</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Voice</InputLabel>
            <Select value={formVoice} label="Voice" onChange={(e) => setFormVoice(e.target.value)}>
              {presets.length > 0
                ? (() => {
                    // Grouped by accent_group with subheaders.
                    const order = ['British', 'British RP', 'American'];
                    const groups = new Map<string, typeof presets>();
                    for (const p of presets) {
                      const g = p.accent_group || 'Other';
                      if (!groups.has(g)) groups.set(g, [] as any);
                      groups.get(g)!.push(p as any);
                    }
                    const ordered = [
                      ...order.filter((g) => groups.has(g)),
                      ...Array.from(groups.keys()).filter((g) => !order.includes(g)),
                    ];
                    const items: React.ReactNode[] = [];
                    for (const g of ordered) {
                      items.push(
                        <MenuItem key={`__g_${g}`} disabled sx={{ opacity: 1, fontWeight: 700 }}>
                          {g}
                        </MenuItem>,
                      );
                      for (const p of groups.get(g)!) {
                        const tag: string[] = [];
                        if (p.recommended) tag.push('Recommended');
                        if (p.verified === false) tag.push('Experimental');
                        const suffix = tag.length ? `  \u2014 ${tag.join(' \u00b7 ')}` : '';
                        items.push(
                          <MenuItem key={p.id} value={p.id}>
                            {p.label}{suffix}
                          </MenuItem>,
                        );
                      }
                    }
                    return items;
                  })()
                : <MenuItem value={formVoice}>{formVoice}</MenuItem>}
            </Select>
          </FormControl>

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>Tone</Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
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
          </Box>

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>Speed</Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
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
          </Box>

          <FormControlLabel
            control={<Switch checked={formHumor} onChange={(e) => setFormHumor(e.target.checked)} size="small" />}
            label="Allow light humour"
          />

          <TextField
            label="Personality instructions"
            multiline
            minRows={2}
            fullWidth
            size="small"
            value={formPersonality}
            onChange={(e) => setFormPersonality(e.target.value.slice(0, 500))}
            helperText={`${formPersonality.length}/500`}
          />

          <TextField
            label="Greeting message"
            multiline
            minRows={2}
            fullWidth
            size="small"
            value={formGreeting}
            onChange={(e) => setFormGreeting(e.target.value.slice(0, 200))}
            helperText={`${formGreeting.length}/200`}
          />

          <Divider />
          <Typography variant="subtitle2">Business Hours</Typography>
          {DAYS.map((day) => {
            const h = formHours[day] || { enabled: false, open: '09:00', close: '17:00' };
            return (
              <Box key={day} sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
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
                  label={<Typography variant="body2" sx={{ width: 80, textTransform: 'capitalize' }}>{day}</Typography>}
                  sx={{ mr: 0, width: 140 }}
                />
                {h.enabled ? (
                  <>
                    <input
                      type="time"
                      value={h.open}
                      onChange={(e) => setFormHours((prev) => ({ ...prev, [day]: { ...prev[day], open: e.target.value } }))}
                      style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}
                    />
                    <Typography variant="body2">to</Typography>
                    <input
                      type="time"
                      value={h.close}
                      onChange={(e) => setFormHours((prev) => ({ ...prev, [day]: { ...prev[day], close: e.target.value } }))}
                      style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}
                    />
                  </>
                ) : (
                  <Typography variant="body2" color="text.disabled">Closed</Typography>
                )}
              </Box>
            );
          })}

          <Divider />
          <Typography variant="subtitle2">After Hours</Typography>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {['message', 'voicemail', 'transfer'].map((opt) => (
              <Chip
                key={opt}
                label={opt.charAt(0).toUpperCase() + opt.slice(1)}
                onClick={() => setFormAfterHoursAction(opt)}
                color={formAfterHoursAction === opt ? 'primary' : 'default'}
                variant={formAfterHoursAction === opt ? 'filled' : 'outlined'}
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
            value={formAfterHoursMsg}
            onChange={(e) => setFormAfterHoursMsg(e.target.value)}
          />

          <Divider />
          <Typography variant="subtitle2">Call Transfer</Typography>
          <FormControlLabel
            control={<Switch checked={formTransferEnabled} onChange={(e) => setFormTransferEnabled(e.target.checked)} size="small" />}
            label="Enable call transfer"
          />
          {formTransferEnabled && (
            <>
              <TextField label="Transfer number" size="small" fullWidth value={formTransferNumber} onChange={(e) => setFormTransferNumber(e.target.value)} />
              <TextField label="Transfer triggers (comma separated)" size="small" fullWidth value={formTransferPhrases} onChange={(e) => setFormTransferPhrases(e.target.value)} />
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfigDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSaveConfig}
            disabled={configSaving}
            startIcon={configSaving ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
          >
            {configSaving ? 'Saving...' : 'Save Configuration'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ========== View Calls Dialog ========== */}
      <Dialog open={callsDialogOpen} onClose={() => setCallsDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Receptionist Calls</DialogTitle>
        <DialogContent>
          {calls.length === 0 ? (
            <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
              No receptionist calls yet.
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {calls.map((call) => (
                <Card
                  key={call.id}
                  sx={{
                    p: 2,
                    cursor: 'pointer',
                    '&:hover': { boxShadow: 2, bgcolor: 'action.hover' },
                    display: 'flex',
                    alignItems: 'center',
                    gap: 2,
                  }}
                  onClick={() => { setSelectedCall(call); setCallDrawerOpen(true); }}
                >
                  <Box sx={{ width: 36, height: 36, borderRadius: '50%', bgcolor: 'primary.light', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <SmartToyIcon color="primary" fontSize="small" />
                  </Box>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="subtitle2" fontWeight={600} noWrap>
                      {call.caller_name || 'Unknown Caller'}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" noWrap>
                      {call.caller_number || 'No number'}
                      {call.summary && ` · ${call.summary.substring(0, 50)}...`}
                    </Typography>
                  </Box>
                  <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(call.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit' })}{' '}
                      {new Date(call.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                    </Typography>
                    {call.duration_seconds != null && (
                      <Typography variant="caption" display="block" color="text.secondary">
                        {formatDuration(call.duration_seconds)}
                      </Typography>
                    )}
                    {call.outcome && (
                      <Chip label={call.outcome} size="small" color={OUTCOME_COLORS[call.outcome] || 'default'} variant="outlined" />
                    )}
                  </Box>
                  <ChevronRightIcon color="action" />
                </Card>
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCallsDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Call Detail Drawer */}
      <Drawer anchor="right" open={callDrawerOpen} onClose={() => { setCallDrawerOpen(false); setSelectedCall(null); }}>
        <Box sx={{ width: { xs: '100vw', sm: 420 }, p: 3 }}>
          {selectedCall && (
            <>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6" fontWeight={600}>Call Details</Typography>
                <IconButton onClick={() => { setCallDrawerOpen(false); setSelectedCall(null); }}><CloseIcon /></IconButton>
              </Box>
              <Card sx={{ p: 2, mb: 2, bgcolor: 'primary.light' }}>
                <Typography variant="subtitle2" color="text.secondary">Caller</Typography>
                <Typography variant="h6" fontWeight={600}>{selectedCall.caller_name || 'Unknown Caller'}</Typography>
                {selectedCall.caller_number && <Typography variant="body2">{selectedCall.caller_number}</Typography>}
              </Card>
              <Typography variant="body2" color="text.secondary">
                {new Date(selectedCall.created_at).toLocaleString('en-GB')}
                {selectedCall.duration_seconds != null && ` · Duration: ${formatDuration(selectedCall.duration_seconds)}`}
              </Typography>
              {selectedCall.outcome && (
                <Box sx={{ mt: 1 }}><Chip label={selectedCall.outcome} size="small" color={OUTCOME_COLORS[selectedCall.outcome] || 'default'} /></Box>
              )}
              {selectedCall.intent && (
                <Box sx={{ mt: 1 }}><Chip label={selectedCall.intent} size="small" variant="outlined" /></Box>
              )}
              {selectedCall.summary && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary">Summary</Typography>
                  <Card sx={{ p: 2, bgcolor: 'grey.50', mt: 0.5 }}><Typography variant="body2">{selectedCall.summary}</Typography></Card>
                </Box>
              )}
              {selectedCall.transcript && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary">Transcript</Typography>
                  <Card sx={{ p: 2, bgcolor: 'grey.50', maxHeight: 300, overflow: 'auto', mt: 0.5 }}>
                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{selectedCall.transcript}</Typography>
                  </Card>
                </Box>
              )}
            </>
          )}
        </Box>
      </Drawer>

      {/* ========== Knowledge Base Dialog ========== */}
      <Dialog open={kbDialogOpen} onClose={() => setKbDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            Knowledge Base ({kbItems.length} items)
            <Button size="small" startIcon={<AddIcon />} onClick={openKBAdd}>Add Item</Button>
          </Box>
        </DialogTitle>
        <DialogContent>
          {kbItems.length === 0 ? (
            <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>No knowledge base items.</Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {kbItems.map((item) => (
                <Box key={item.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.5, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Chip label={item.category} size="small" variant="outlined" sx={{ minWidth: 70, textTransform: 'capitalize' }} />
                  <Typography variant="body2" sx={{ flex: 1 }} noWrap>{item.title}</Typography>
                  <IconButton size="small" onClick={() => openKBEdit(item)}><EditIcon fontSize="small" /></IconButton>
                  <IconButton size="small" color="error" onClick={() => handleKBDelete(item.id)}><DeleteIcon fontSize="small" /></IconButton>
                </Box>
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setKbDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* KB Add/Edit Modal */}
      <Dialog open={kbModalOpen} onClose={() => setKbModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{kbEditItem ? 'Edit Item' : 'Add Item'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Category</InputLabel>
            <Select value={kbFormCategory} label="Category" onChange={(e) => setKbFormCategory(e.target.value)}>
              {(kbCategories.length > 0 ? kbCategories : ['general', 'services', 'pricing', 'hours', 'faqs', 'policies', 'location']).map((c) => (
                <MenuItem key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField label="Title" size="small" fullWidth value={kbFormTitle} onChange={(e) => setKbFormTitle(e.target.value)} />
          <TextField label="Content" size="small" fullWidth multiline minRows={4} value={kbFormContent} onChange={(e) => setKbFormContent(e.target.value)} />
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
          >
            {kbSaving ? 'Saving...' : 'Save Item'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
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
    </>
  );
}

/**
 * Compact status chip for the businesses table.
 * Uses the receptionist overview data.
 */
export function ReceptionistStatusChip({ overview }: { overview?: { enabled: boolean; config_exists: boolean } }) {
  if (!overview || !overview.config_exists) {
    return <Chip label="Not set up" size="small" />;
  }
  if (overview.enabled) {
    return <Chip label="Active" size="small" color="success" />;
  }
  return <Chip label="Configured" size="small" color="warning" />;
}
