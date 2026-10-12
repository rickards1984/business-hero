import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  FormControlLabel,
  LinearProgress,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { apiRequest } from '@/lib/queryClient';

/**
 * BH-012 — the month's receptionist minutes, visible BEFORE the limit
 * (ENTITLEMENT-SPEC PART E: "a billing surprise is worse than a block").
 *
 * Every figure comes from GET /v1/usage; nothing is calculated here.
 */

export interface Usage {
  period: string;
  allowance_minutes: string;
  used_minutes: string;
  remaining_minutes: string;
  overage_minutes: string;
  overage_spend_gbp: string;
  overage_rate_gbp: string;
  metered_usage_enabled: boolean;
  spend_cap_gbp: string;
  state: 'ok' | 'allowance_exhausted' | 'spend_cap_reached';
}

export function monthLabel(period: string): string {
  const [y, m] = period.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
}

/** Whether a limit is actually stopping calls — a plan with no minutes and
 *  no extra minutes switched on has nothing to warn about. */
export function isBlocking(u: Usage): boolean {
  return u.state !== 'ok' && (Number(u.allowance_minutes) > 0 || u.metered_usage_enabled);
}

function readableError(err: unknown): string {
  const body = (err instanceof Error ? err.message : '').replace(/^\d{3}:\s*/, '');
  try {
    const detail = JSON.parse(body).detail;
    if (typeof detail === 'string') return detail;
  } catch {
    // not JSON
  }
  return 'That could not be saved. Please try again.';
}

export default function ReceptionistUsage() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [cap, setCap] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);

  const load = async () => {
    setLoadFailed(false);
    try {
      const r = await apiRequest('GET', '/v1/usage');
      const u: Usage = await r.json();
      setUsage(u);
      setCap(u.spend_cap_gbp);
    } catch {
      setUsage(null);
      setLoadFailed(true);
    }
  };

  useEffect(() => { load(); }, []);

  // Say so when usage cannot be shown: "no warning" and "could not check"
  // must not look the same (Codex BH-012 review 1).
  if (loadFailed) {
    return (
      <Alert severity="warning" sx={{ mb: 2 }}
        action={<Button color="inherit" size="small" onClick={load}>Retry</Button>}>
        Receptionist usage could not be loaded, so this page cannot show how many minutes are left.
      </Alert>
    );
  }
  if (!usage) return null;

  const allowance = Number(usage.allowance_minutes);
  const used = Number(usage.used_minutes);
  const percent = allowance > 0 ? Math.min(100, (used / allowance) * 100) : 0;

  const save = async (enabled: boolean) => {
    setSaving(true);
    setError('');
    try {
      const r = await apiRequest('PUT', '/v1/usage/metering', {
        enabled,
        monthly_spend_cap_gbp: enabled ? cap : null,
      });
      const u: Usage = await r.json();
      setUsage(u);
      setCap(u.spend_cap_gbp);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={600}>
          Receptionist minutes — {monthLabel(usage.period)}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {usage.used_minutes} of {usage.allowance_minutes} minutes used · {usage.remaining_minutes} left.
          Resets at the start of each month. Calls are limited to 20 minutes each.
        </Typography>
        {allowance > 0 && (
          <LinearProgress variant="determinate" value={percent} sx={{ height: 8, borderRadius: 4, mb: 2 }}
            color={percent >= 100 ? 'error' : percent >= 80 ? 'warning' : 'primary'} />
        )}

        {usage.state === 'allowance_exhausted' && isBlocking(usage) && (
          <Alert severity="error" sx={{ mb: 2 }}>
            This month's minutes are used up, so new calls are not being answered. Switch on extra
            minutes below to keep answering, or wait for the month to reset.
          </Alert>
        )}
        {usage.state === 'spend_cap_reached' && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Your monthly cap for extra minutes (£{usage.spend_cap_gbp}) has been reached, so new calls
            are not being answered. Raise the cap below, or wait for the month to reset.
          </Alert>
        )}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <FormControlLabel
          control={<Switch checked={usage.metered_usage_enabled} disabled={saving}
            onChange={e => save(e.target.checked)} />}
          label={`Extra minutes when the allowance runs out (£${usage.overage_rate_gbp} a minute)`}
        />
        {usage.metered_usage_enabled && (
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mt: 1 }}>
            <TextField size="small" label="Monthly cap (£)" value={cap} inputMode="decimal"
              onChange={e => setCap(e.target.value)} sx={{ width: 160 }} />
            <Button size="small" variant="outlined" disabled={saving} onClick={() => save(true)}>
              Save cap
            </Button>
            <Typography variant="body2" color="text.secondary">
              Extra this month: {usage.overage_minutes} min · £{usage.overage_spend_gbp}
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
