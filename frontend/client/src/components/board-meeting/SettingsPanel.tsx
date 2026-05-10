/**
 * Executive Board Meeting — Settings Panel
 *
 * Configures cadence, focus areas, attendees, and Aria's directness level.
 * Advanced fields (attendees, extended focus areas) are gated for
 * business/beta tiers — pro sees them disabled with a hint.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  FormControlLabel,
  FormGroup,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import {
  ExecutiveMeetingSettings,
  Attendee,
  DirectnessLevel,
  Frequency,
  formatUKDateTime,
  getSettings,
  updateSettings,
} from '@/lib/executiveMeetingsApi';

const DAYS_OF_WEEK = [
  { value: 0, label: 'Sunday' },
  { value: 1, label: 'Monday' },
  { value: 2, label: 'Tuesday' },
  { value: 3, label: 'Wednesday' },
  { value: 4, label: 'Thursday' },
  { value: 5, label: 'Friday' },
  { value: 6, label: 'Saturday' },
];

const TIMEZONES = [
  'Europe/London',
  'Europe/Dublin',
  'Europe/Paris',
  'Europe/Berlin',
  'America/New_York',
  'America/Los_Angeles',
  'Australia/Sydney',
  'UTC',
];

const STANDARD_FOCUS_AREAS = [
  { value: 'financial', label: 'Financial' },
  { value: 'operations', label: 'Operations' },
  { value: 'team', label: 'Team' },
  { value: 'growth', label: 'Growth' },
] as const;

const ADVANCED_FOCUS_AREAS = [
  { value: 'marketing', label: 'Marketing' },
  { value: 'customer_satisfaction', label: 'Customer Satisfaction' },
  { value: 'compliance', label: 'Compliance' },
] as const;

const DIRECTNESS_OPTIONS: Array<{ value: DirectnessLevel; label: string }> = [
  { value: 'gentle', label: 'Gentle' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'direct', label: 'Direct' },
  { value: 'brutally_honest', label: 'Brutally Honest' },
];

const MAX_CUSTOM_AGENDA_ITEMS = 5;

interface SettingsPanelProps {
  hasAdvanced: boolean; // business or beta tier
}

const DEFAULT_SETTINGS: ExecutiveMeetingSettings = {
  enabled: false,
  frequency: 'weekly',
  day_of_week: 1,
  day_of_month: 1,
  meeting_time: '09:00',
  timezone: 'Europe/London',
  focus_areas: ['financial', 'operations', 'team', 'growth'],
  custom_agenda_items: [],
  attendees: [],
  directness_level: 'balanced',
  include_disclaimers: true,
};

export default function SettingsPanel({ hasAdvanced }: SettingsPanelProps) {
  const [settings, setSettings] = useState<ExecutiveMeetingSettings>(DEFAULT_SETTINGS);
  const [original, setOriginal] = useState<ExecutiveMeetingSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [newAgendaItem, setNewAgendaItem] = useState('');
  const [newAttendee, setNewAttendee] = useState<Attendee>({ name: '', role: '', email: '' });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getSettings();
        if (cancelled) return;
        const normalised: ExecutiveMeetingSettings = {
          ...DEFAULT_SETTINGS,
          ...s,
          focus_areas: Array.isArray(s.focus_areas) && s.focus_areas.length
            ? s.focus_areas
            : DEFAULT_SETTINGS.focus_areas,
          custom_agenda_items: Array.isArray(s.custom_agenda_items)
            ? s.custom_agenda_items
            : [],
          attendees: Array.isArray(s.attendees) ? s.attendees : [],
          meeting_time: (s.meeting_time || '09:00').slice(0, 5),
        };
        setSettings(normalised);
        setOriginal(normalised);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to load settings');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const isDirty = useMemo(() => {
    return JSON.stringify(settings) !== JSON.stringify(original);
  }, [settings, original]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateSettings(settings);
      const normalised: ExecutiveMeetingSettings = {
        ...DEFAULT_SETTINGS,
        ...updated,
        focus_areas: Array.isArray(updated.focus_areas) ? updated.focus_areas : [],
        custom_agenda_items: Array.isArray(updated.custom_agenda_items)
          ? updated.custom_agenda_items
          : [],
        attendees: Array.isArray(updated.attendees) ? updated.attendees : [],
        meeting_time: (updated.meeting_time || '09:00').slice(0, 5),
      };
      setSettings(normalised);
      setOriginal(normalised);
      setToast({ type: 'success', message: 'Settings saved' });
    } catch (e) {
      setError((e as Error).message || 'Failed to save settings');
      setToast({ type: 'error', message: 'Save failed' });
    } finally {
      setSaving(false);
    }
  };

  const toggleFocusArea = (value: string) => {
    setSettings((prev) => {
      const has = prev.focus_areas.includes(value);
      return {
        ...prev,
        focus_areas: has
          ? prev.focus_areas.filter((f) => f !== value)
          : [...prev.focus_areas, value],
      };
    });
  };

  const addCustomAgendaItem = () => {
    const trimmed = newAgendaItem.trim();
    if (!trimmed) return;
    if (settings.custom_agenda_items.length >= MAX_CUSTOM_AGENDA_ITEMS) return;
    setSettings((prev) => ({
      ...prev,
      custom_agenda_items: [...prev.custom_agenda_items, trimmed],
    }));
    setNewAgendaItem('');
  };

  const removeCustomAgendaItem = (idx: number) => {
    setSettings((prev) => ({
      ...prev,
      custom_agenda_items: prev.custom_agenda_items.filter((_, i) => i !== idx),
    }));
  };

  const addAttendee = () => {
    const name = newAttendee.name.trim();
    if (!name) return;
    setSettings((prev) => ({
      ...prev,
      attendees: [
        ...prev.attendees,
        {
          name,
          role: newAttendee.role?.trim() || undefined,
          email: newAttendee.email?.trim() || undefined,
        },
      ],
    }));
    setNewAttendee({ name: '', role: '', email: '' });
  };

  const removeAttendee = (idx: number) => {
    setSettings((prev) => ({
      ...prev,
      attendees: prev.attendees.filter((_, i) => i !== idx),
    }));
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  return (
    <Stack spacing={3}>
      {error && <Alert severity="error">{error}</Alert>}

      <Card>
        <CardContent>
          <Stack spacing={3}>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={2}
              justifyContent="space-between"
              alignItems={{ xs: 'flex-start', sm: 'center' }}
            >
              <Box>
                <Typography variant="h3">Meeting schedule</Typography>
                <Typography variant="body2" color="text.secondary">
                  Choose how often you want to meet with Aria.
                </Typography>
              </Box>
              <FormControlLabel
                control={
                  <Switch
                    checked={settings.enabled}
                    onChange={(e) => setSettings({ ...settings, enabled: e.target.checked })}
                  />
                }
                label={settings.enabled ? 'Enabled' : 'Disabled'}
              />
            </Stack>

            <Divider />

            <FormControl>
              <Typography variant="h6" sx={{ mb: 1 }}>Frequency</Typography>
              <ToggleButtonGroup
                value={settings.frequency}
                exclusive
                onChange={(_, v: Frequency | null) => v && setSettings({ ...settings, frequency: v })}
                size="small"
              >
                <ToggleButton value="weekly">Weekly</ToggleButton>
                <ToggleButton value="monthly">Monthly</ToggleButton>
              </ToggleButtonGroup>
            </FormControl>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              {settings.frequency === 'weekly' ? (
                <FormControl sx={{ minWidth: 200 }} size="small">
                  <InputLabel id="dow-label">Day of week</InputLabel>
                  <Select
                    labelId="dow-label"
                    label="Day of week"
                    value={settings.day_of_week}
                    onChange={(e) =>
                      setSettings({ ...settings, day_of_week: Number(e.target.value) })
                    }
                  >
                    {DAYS_OF_WEEK.map((d) => (
                      <MenuItem key={d.value} value={d.value}>{d.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              ) : (
                <FormControl sx={{ minWidth: 200 }} size="small">
                  <InputLabel id="dom-label">Day of month</InputLabel>
                  <Select
                    labelId="dom-label"
                    label="Day of month"
                    value={settings.day_of_month}
                    onChange={(e) =>
                      setSettings({ ...settings, day_of_month: Number(e.target.value) })
                    }
                  >
                    {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                      <MenuItem key={d} value={d}>{d}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}

              <TextField
                size="small"
                label="Meeting time"
                type="time"
                value={settings.meeting_time}
                onChange={(e) =>
                  setSettings({ ...settings, meeting_time: e.target.value })
                }
                InputLabelProps={{ shrink: true }}
                sx={{ minWidth: 160 }}
              />

              <FormControl sx={{ minWidth: 220 }} size="small">
                <InputLabel id="tz-label">Timezone</InputLabel>
                <Select
                  labelId="tz-label"
                  label="Timezone"
                  value={settings.timezone}
                  onChange={(e) => setSettings({ ...settings, timezone: e.target.value })}
                >
                  {TIMEZONES.map((tz) => (
                    <MenuItem key={tz} value={tz}>{tz}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h3">Focus areas</Typography>
              <Typography variant="body2" color="text.secondary">
                Aria will give these topics more weight during the meeting.
              </Typography>
            </Box>

            <FormGroup>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {STANDARD_FOCUS_AREAS.map((fa) => (
                  <FormControlLabel
                    key={fa.value}
                    control={
                      <Checkbox
                        checked={settings.focus_areas.includes(fa.value)}
                        onChange={() => toggleFocusArea(fa.value)}
                      />
                    }
                    label={fa.label}
                  />
                ))}
              </Stack>

              <Box sx={{ mt: 2 }}>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                  Advanced focus areas {hasAdvanced ? '' : '— available on the Business plan'}
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {ADVANCED_FOCUS_AREAS.map((fa) => (
                    <FormControlLabel
                      key={fa.value}
                      control={
                        <Checkbox
                          checked={settings.focus_areas.includes(fa.value)}
                          onChange={() => toggleFocusArea(fa.value)}
                          disabled={!hasAdvanced}
                        />
                      }
                      label={fa.label}
                      sx={{ opacity: hasAdvanced ? 1 : 0.55 }}
                    />
                  ))}
                </Stack>
              </Box>
            </FormGroup>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Box>
              <Typography variant="h3">Custom agenda items</Typography>
              <Typography variant="body2" color="text.secondary">
                Add up to {MAX_CUSTOM_AGENDA_ITEMS} recurring items you want covered every meeting.
              </Typography>
            </Box>

            <Stack spacing={1}>
              {settings.custom_agenda_items.map((item, idx) => (
                <Stack
                  key={idx}
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  sx={{
                    px: 1.5,
                    py: 1,
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                  }}
                >
                  <Typography variant="body2" sx={{ flex: 1 }}>{item}</Typography>
                  <IconButton
                    size="small"
                    onClick={() => removeCustomAgendaItem(idx)}
                    aria-label="Remove agenda item"
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Stack>
              ))}
            </Stack>

            {settings.custom_agenda_items.length < MAX_CUSTOM_AGENDA_ITEMS && (
              <Stack direction="row" spacing={1}>
                <TextField
                  fullWidth
                  size="small"
                  placeholder="e.g. Review hiring pipeline"
                  value={newAgendaItem}
                  onChange={(e) => setNewAgendaItem(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addCustomAgendaItem();
                    }
                  }}
                />
                <Button
                  variant="outlined"
                  startIcon={<AddIcon />}
                  onClick={addCustomAgendaItem}
                  disabled={!newAgendaItem.trim()}
                >
                  Add
                </Button>
              </Stack>
            )}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Box>
              <Typography variant="h3">Attendees</Typography>
              <Typography variant="body2" color="text.secondary">
                {hasAdvanced
                  ? 'Add people who attend this meeting. They will be referenced by name in the agenda.'
                  : 'Multiple attendees are available on the Business plan. Pro tier meetings are owner-only.'}
              </Typography>
            </Box>

            {hasAdvanced && (
              <>
                <Stack spacing={1}>
                  {settings.attendees.map((a, idx) => (
                    <Stack
                      key={idx}
                      direction="row"
                      spacing={1}
                      alignItems="center"
                      sx={{
                        px: 1.5,
                        py: 1,
                        border: '1px solid',
                        borderColor: 'divider',
                        borderRadius: 1,
                      }}
                    >
                      <Box sx={{ flex: 1 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{a.name}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {[a.role, a.email].filter(Boolean).join(' · ') || 'No role or email'}
                        </Typography>
                      </Box>
                      <IconButton
                        size="small"
                        onClick={() => removeAttendee(idx)}
                        aria-label="Remove attendee"
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Stack>
                  ))}
                </Stack>

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                  <TextField
                    size="small"
                    label="Name"
                    value={newAttendee.name}
                    onChange={(e) => setNewAttendee({ ...newAttendee, name: e.target.value })}
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    size="small"
                    label="Role (optional)"
                    value={newAttendee.role}
                    onChange={(e) => setNewAttendee({ ...newAttendee, role: e.target.value })}
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    size="small"
                    label="Email (optional)"
                    value={newAttendee.email}
                    onChange={(e) => setNewAttendee({ ...newAttendee, email: e.target.value })}
                    sx={{ flex: 1 }}
                  />
                  <Button
                    variant="outlined"
                    startIcon={<AddIcon />}
                    onClick={addAttendee}
                    disabled={!newAttendee.name.trim()}
                  >
                    Add
                  </Button>
                </Stack>
              </>
            )}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h3">Aria's tone</Typography>
              <Typography variant="body2" color="text.secondary">
                How directly Aria should give you feedback. Calibrated to your preference.
              </Typography>
            </Box>

            <ToggleButtonGroup
              value={settings.directness_level}
              exclusive
              size="small"
              onChange={(_, v: DirectnessLevel | null) =>
                v && setSettings({ ...settings, directness_level: v })
              }
              sx={{ flexWrap: 'wrap' }}
            >
              {DIRECTNESS_OPTIONS.map((opt) => (
                <ToggleButton key={opt.value} value={opt.value}>
                  {opt.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>

            <FormControlLabel
              control={
                <Switch
                  checked={settings.include_disclaimers}
                  onChange={(e) =>
                    setSettings({ ...settings, include_disclaimers: e.target.checked })
                  }
                />
              }
              label="Include professional disclaimers on legal / tax / financial topics"
            />
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={2}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', sm: 'center' }}
          >
            <Box>
              {settings.enabled && settings.next_meeting_at ? (
                <>
                  <Typography variant="body2" color="text.secondary">Next meeting</Typography>
                  <Typography variant="h6">
                    {formatUKDateTime(settings.next_meeting_at)}
                  </Typography>
                </>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {settings.enabled
                    ? 'Save your settings to see the next meeting time.'
                    : 'Enable the schedule to see your next meeting.'}
                </Typography>
              )}
            </Box>
            <Stack direction="row" spacing={1}>
              {isDirty && (
                <Chip label="Unsaved changes" size="small" color="warning" variant="outlined" />
              )}
              <Button
                variant="contained"
                onClick={handleSave}
                disabled={!isDirty || saving}
              >
                {saving ? 'Saving…' : 'Save settings'}
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Snackbar
        open={!!toast}
        autoHideDuration={3500}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast ? (
          <Alert severity={toast.type} onClose={() => setToast(null)}>
            {toast.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Stack>
  );
}
