import { useEffect, useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, FormControlLabel, MenuItem, Stack, Switch,
  TextField, Typography,
} from '@mui/material';
import { apiRequest } from '@/lib/queryClient';

/**
 * AUTO-1 — what Aria may do on her own (North Star P4: autonomy is earned one
 * action type at a time). Off until the owner switches it on. The server
 * clamps every value; this page only shows and edits them.
 */

interface ChaseSettings {
  enabled: boolean;
  first_after_days: number;
  every_days: number;
  max_auto_stage: number;
  start_hour: number;
  end_hour: number;
  weekdays_only: boolean;
  customer_gap_days: number;
  daily_cap: number;
  paused_customers: string[];
}

const hour = (h: number) => `${String(h).padStart(2, '0')}:00`;

export default function AriaAutomationsSettings() {
  const [s, setS] = useState<ChaseSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);
  const [pauseEmail, setPauseEmail] = useState('');

  useEffect(() => {
    apiRequest('GET', '/v1/automations/invoice-chasing')
      .then(r => r.json()).then(setS)
      .catch(() => setMessage({ kind: 'error', text: 'Your automation settings could not be loaded.' }));
  }, []);

  const save = async (changes: Partial<ChaseSettings>) => {
    setSaving(true);
    setMessage(null);
    try {
      const r = await apiRequest('PUT', '/v1/automations/invoice-chasing', changes);
      setS(await r.json());
      setMessage({ kind: 'success', text: 'Saved.' });
    } catch {
      setMessage({ kind: 'error', text: 'That could not be saved. Please try again.' });
    } finally {
      setSaving(false);
    }
  };

  if (!s) {
    return message ? <Alert severity="error">{message.text}</Alert> : null;
  }

  const num = (key: keyof ChaseSettings, label: string, min: number, max: number, help: string) => (
    <TextField type="number" size="small" label={label} value={s[key] as number}
      inputProps={{ min, max }} helperText={help} sx={{ width: 220 }}
      onChange={e => setS({ ...s, [key]: Number(e.target.value) })} />
  );

  return (
    <Box sx={{ maxWidth: 760, mx: 'auto' }}>
      <Typography variant="h1" sx={{ mb: 1 }}>What Aria can do on her own</Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Aria normally drafts and waits for your tap. Here you can let her handle routine jobs
        herself, within the rules you set. Everything she does is listed on your home page, and
        you can switch it off at any time.
      </Typography>
      {message && <Alert severity={message.kind} sx={{ mb: 2 }}>{message.text}</Alert>}

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 2, flexWrap: 'wrap' }}>
              <Box>
                <Typography variant="h3">Chase overdue invoices</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 520 }}>
                  Aria sends your chase templates from your email, signed as your AI assistant,
                  when an invoice is overdue. The final stage is always sent to you as a card to
                  approve.
                </Typography>
              </Box>
              <FormControlLabel
                control={<Switch checked={s.enabled} disabled={saving}
                  onChange={e => save({ enabled: e.target.checked })} />}
                label={s.enabled ? 'On' : 'Off'} />
            </Box>

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
              {num('first_after_days', 'First chase after (days overdue)', 1, 90, 'Stage 1')}
              {num('every_days', 'Then every (days)', 3, 60, 'Until the last automatic stage')}
              <TextField select size="small" label="Last stage sent automatically" value={s.max_auto_stage}
                sx={{ width: 220 }} helperText="Later stages come to you as cards"
                onChange={e => setS({ ...s, max_auto_stage: Number(e.target.value) })}>
                {[1, 2, 3].map(n => <MenuItem key={n} value={n}>Stage {n}</MenuItem>)}
              </TextField>
              {num('customer_gap_days', 'At most one chase per customer every (days)', 1, 30, 'Across all their invoices')}
              {num('daily_cap', 'Most chases in one day', 1, 50, 'A safety limit')}
            </Box>

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center' }}>
              <TextField select size="small" label="From" value={s.start_hour} sx={{ width: 120 }}
                onChange={e => setS({ ...s, start_hour: Number(e.target.value) })}>
                {Array.from({ length: 24 }, (_, h) => <MenuItem key={h} value={h}>{hour(h)}</MenuItem>)}
              </TextField>
              <TextField select size="small" label="Until" value={s.end_hour} sx={{ width: 120 }}
                onChange={e => setS({ ...s, end_hour: Number(e.target.value) })}>
                {Array.from({ length: 24 }, (_, h) => h + 1).map(h => <MenuItem key={h} value={h}>{hour(h % 24)}</MenuItem>)}
              </TextField>
              <FormControlLabel
                control={<Switch checked={s.weekdays_only} onChange={e => setS({ ...s, weekdays_only: e.target.checked })} />}
                label="Weekdays only (UK time)" />
            </Box>

            <Box>
              <Typography variant="h5" sx={{ mb: 1 }}>Never chase these customers</Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 1 }}>
                {s.paused_customers.length === 0
                  ? <Typography variant="body2" color="text.secondary">No one is paused.</Typography>
                  : s.paused_customers.map(email => (
                    <Chip key={email} label={email}
                      onDelete={() => setS({ ...s, paused_customers: s.paused_customers.filter(p => p !== email) })} />
                  ))}
              </Box>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <TextField size="small" label="Customer email" value={pauseEmail}
                  onChange={e => setPauseEmail(e.target.value)} sx={{ width: 280 }} />
                <Button variant="outlined" disabled={!pauseEmail.includes('@')}
                  onClick={() => {
                    setS({ ...s, paused_customers: [...s.paused_customers, pauseEmail.trim().toLowerCase()] });
                    setPauseEmail('');
                  }}>Add</Button>
              </Box>
            </Box>

            <Box>
              <Button variant="contained" disabled={saving}
                onClick={() => save({ ...s })}>Save rules</Button>
            </Box>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
