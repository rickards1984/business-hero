import { useState, useEffect } from 'react';
import {
  Box, Typography, Switch, TextField, Button,
  IconButton, CircularProgress, Snackbar, Alert,
} from '@mui/material';
import { Add as AddIcon, Delete as DeleteIcon } from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';

interface DayConfig {
  day: string;
  start: string;
  end: string;
  enabled: boolean;
}

interface AppointmentType {
  name: string;
  duration_minutes: number;
  description: string;
}

interface BookingSettings {
  enabled: boolean;
  business_hours: DayConfig[];
  appointment_types: AppointmentType[];
  buffer_minutes: number;
  max_advance_days: number;
  min_notice_hours: number;
  confirmation_message: string;
}

export default function BookingSettingsPanel() {
  const [settings, setSettings] = useState<BookingSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false, message: '', severity: 'success'
  });

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await apiRequest('GET', '/v1/booking/settings');
        const data = await res.json();
        setSettings(data);
      } catch (err) {
        console.error('Failed to fetch booking settings:', err);
        setSnackbar({ open: true, message: 'Failed to load booking settings', severity: 'error' });
      } finally {
        setLoading(false);
      }
    };
    fetchSettings();
  }, []);

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      await apiRequest('PUT', '/v1/booking/settings', settings);
      setSnackbar({ open: true, message: 'Booking settings saved', severity: 'success' });
    } catch (err) {
      console.error('Failed to save booking settings:', err);
      setSnackbar({ open: true, message: 'Failed to save settings', severity: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const updateDayConfig = (dayIndex: number, field: keyof DayConfig, value: string | boolean) => {
    if (!settings) return;
    const updated = [...settings.business_hours];
    updated[dayIndex] = { ...updated[dayIndex], [field]: value };
    setSettings({ ...settings, business_hours: updated });
  };

  const addAppointmentType = () => {
    if (!settings) return;
    setSettings({
      ...settings,
      appointment_types: [
        ...settings.appointment_types,
        { name: '', duration_minutes: 60, description: '' },
      ],
    });
  };

  const removeAppointmentType = (index: number) => {
    if (!settings) return;
    const updated = settings.appointment_types.filter((_, i) => i !== index);
    setSettings({ ...settings, appointment_types: updated });
  };

  const updateAppointmentType = (index: number, field: keyof AppointmentType, value: string | number) => {
    if (!settings) return;
    const updated = [...settings.appointment_types];
    updated[index] = { ...updated[index], [field]: value };
    setSettings({ ...settings, appointment_types: updated });
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <CircularProgress size={24} sx={{ color: '#7c5cfc' }} />
      </div>
    );
  }

  if (!settings) return null;

  return (
    <div>
      {/* Enable toggle */}
      <div className="glass-card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'hsl(var(--foreground))' }}>
              Appointment booking
            </div>
            <div style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))', marginTop: 4 }}>
              Allow your AI receptionist to check availability and book appointments on your Google Calendar
            </div>
          </div>
          <Switch
            checked={settings.enabled}
            onChange={(e) => setSettings({ ...settings, enabled: e.target.checked })}
            sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#7c5cfc' }, '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { backgroundColor: '#7c5cfc' } }}
          />
        </div>
      </div>

      {settings.enabled && (
        <>
          {/* Business Hours */}
          <div className="glass-card" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 12 }}>
              Business hours
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {settings.business_hours.map((day, index) => (
                <div key={day.day} style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '8px 0',
                  borderBottom: index < 6 ? '0.5px solid var(--glass-border)' : 'none',
                }}>
                  <div style={{ width: 100, fontSize: 13, fontWeight: 500, color: 'hsl(var(--foreground))', textTransform: 'capitalize' }}>
                    {day.day}
                  </div>
                  <Switch
                    size="small"
                    checked={day.enabled}
                    onChange={(e) => updateDayConfig(index, 'enabled', e.target.checked)}
                    sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#7c5cfc' }, '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { backgroundColor: '#7c5cfc' } }}
                  />
                  {day.enabled ? (
                    <>
                      <TextField
                        type="time"
                        size="small"
                        value={day.start}
                        onChange={(e) => updateDayConfig(index, 'start', e.target.value)}
                        sx={{ width: 120 }}
                        InputLabelProps={{ shrink: true }}
                      />
                      <span style={{ color: 'hsl(var(--muted-foreground))', fontSize: 13 }}>to</span>
                      <TextField
                        type="time"
                        size="small"
                        value={day.end}
                        onChange={(e) => updateDayConfig(index, 'end', e.target.value)}
                        sx={{ width: 120 }}
                        InputLabelProps={{ shrink: true }}
                      />
                    </>
                  ) : (
                    <span style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))' }}>Closed</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Appointment Types */}
          <div className="glass-card" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))' }}>
                Appointment types
              </div>
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={addAppointmentType}
                sx={{ color: '#a78bfa', textTransform: 'none', fontSize: 12 }}
              >
                Add type
              </Button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {settings.appointment_types.map((apt, index) => (
                <div key={index} style={{
                  display: 'flex', gap: 8, alignItems: 'flex-start',
                  padding: 12,
                  background: 'var(--glass-bg)',
                  border: '0.5px solid var(--glass-border)',
                  borderRadius: 8,
                }}>
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <TextField
                      size="small"
                      placeholder="Name (e.g., Consultation)"
                      value={apt.name}
                      onChange={(e) => updateAppointmentType(index, 'name', e.target.value)}
                      fullWidth
                    />
                    <div style={{ display: 'flex', gap: 8 }}>
                      <TextField
                        size="small"
                        type="number"
                        label="Duration (mins)"
                        value={apt.duration_minutes}
                        onChange={(e) => updateAppointmentType(index, 'duration_minutes', parseInt(e.target.value) || 30)}
                        sx={{ width: 130 }}
                        InputLabelProps={{ shrink: true }}
                      />
                      <TextField
                        size="small"
                        placeholder="Description (optional)"
                        value={apt.description}
                        onChange={(e) => updateAppointmentType(index, 'description', e.target.value)}
                        fullWidth
                      />
                    </div>
                  </div>
                  <IconButton size="small" onClick={() => removeAppointmentType(index)} sx={{ color: 'rgba(248,113,113,0.7)' }}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </div>
              ))}
            </div>
          </div>

          {/* Booking Rules */}
          <div className="glass-card" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 12 }}>
              Booking rules
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <TextField
                  size="small"
                  type="number"
                  value={settings.buffer_minutes}
                  onChange={(e) => setSettings({ ...settings, buffer_minutes: parseInt(e.target.value) || 0 })}
                  sx={{ width: 80 }}
                />
                <span style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))' }}>
                  minutes buffer between appointments
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <TextField
                  size="small"
                  type="number"
                  value={settings.max_advance_days}
                  onChange={(e) => setSettings({ ...settings, max_advance_days: parseInt(e.target.value) || 1 })}
                  sx={{ width: 80 }}
                />
                <span style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))' }}>
                  days in advance maximum
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <TextField
                  size="small"
                  type="number"
                  value={settings.min_notice_hours}
                  onChange={(e) => setSettings({ ...settings, min_notice_hours: parseInt(e.target.value) || 1 })}
                  sx={{ width: 80 }}
                />
                <span style={{ fontSize: 13, color: 'hsl(var(--muted-foreground))' }}>
                  hours minimum notice required
                </span>
              </div>
            </div>
          </div>

          {/* Confirmation Message */}
          <div className="glass-card" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'hsl(var(--foreground))', marginBottom: 4 }}>
              Confirmation message
            </div>
            <div style={{ fontSize: 12, color: 'hsl(var(--muted-foreground))', marginBottom: 8 }}>
              This message is read to the caller after their appointment is booked
            </div>
            <TextField
              multiline
              rows={3}
              fullWidth
              value={settings.confirmation_message}
              onChange={(e) => setSettings({ ...settings, confirmation_message: e.target.value })}
              placeholder="Your appointment has been booked. You will receive a calendar invite shortly."
            />
          </div>
        </>
      )}

      {/* Save button */}
      <Button
        variant="contained"
        onClick={handleSave}
        disabled={saving}
        fullWidth
        sx={{
          backgroundColor: '#7c5cfc',
          color: '#fff',
          textTransform: 'none',
          fontWeight: 600,
          borderRadius: 2,
          py: 1.2,
          '&:hover': { backgroundColor: '#5a3fd4' },
          '&:disabled': { backgroundColor: 'rgba(124,92,252,0.3)', color: 'rgba(255,255,255,0.5)' },
        }}
      >
        {saving ? <CircularProgress size={20} sx={{ color: '#fff' }} /> : 'Save booking settings'}
      </Button>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
      >
        <Alert severity={snackbar.severity} onClose={() => setSnackbar({ ...snackbar, open: false })}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </div>
  );
}
