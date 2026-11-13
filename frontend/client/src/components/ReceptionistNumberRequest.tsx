import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Collapse,
  FormControlLabel,
  Link,
  Radio,
  RadioGroup,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
} from '@mui/material';
import { Phone as PhoneIcon } from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';

// RCP-1 (docs/RCP-1-TICKET.md): the owner asks for a number type and area,
// never a number. Mike approves the purchase; this panel shows the progress.

interface ForwardingGuide {
  provider: string;
  kind: string;
  help_url: string;
  steps: string[];
}

interface NumberRequest {
  id: string;
  state: 'requested' | 'waiting_bundle' | 'buying' | 'bought' | 'live' | 'declined' | 'cancelled';
  mode: 'new_local' | 'keep_existing';
  area_code: string | null;
  existing_number: string | null;
  setup: 'self' | 'done_for_you';
  setup_fee_pence: number;
  phone_number: string | null;
  decline_reason: string | null;
  created_at: string;
}

interface NumberStatus {
  ready: boolean;
  phone_number: string | null;
  in_plan: boolean;
  setup_fee_pence: number;
  forwarding: ForwardingGuide[];
  request: NumberRequest | null;
}

interface Props {
  onLive: () => void;
}

const OPEN = ['requested', 'waiting_bundle', 'buying', 'bought'];
const STAGES = ['Requested', 'UK approval', 'Setting up', 'Live'];

function stageOf(state: NumberRequest['state']): number {
  if (state === 'requested') return 0;
  if (state === 'waiting_bundle') return 1;
  if (state === 'buying' || state === 'bought') return 2;
  return 3;
}

export function errorDetail(err: any): string {
  const message = String(err?.message || err || 'Something went wrong');
  const json = message.indexOf('{');
  if (json >= 0) {
    try {
      const detail = JSON.parse(message.slice(json)).detail;
      if (typeof detail === 'string') return detail;
    } catch {
      /* fall through */
    }
  }
  return message;
}

function pounds(pence: number): string {
  return `£${(pence / 100).toFixed(pence % 100 ? 2 : 0)}`;
}

export function ForwardingSteps({ guides, number }: { guides: ForwardingGuide[]; number: string | null }) {
  const [open, setOpen] = useState<string | null>(null);
  const shown = number || 'your new number';
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Forward your existing line to the receptionist's number, for all calls or only when you don't answer.
        Choose your provider for the steps. Your provider may charge for forwarded calls; its help page says.
      </Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 1 }}>
        {guides.map((g) => (
          <Chip
            key={g.provider}
            label={g.provider}
            color={open === g.provider ? 'primary' : 'default'}
            onClick={() => setOpen(open === g.provider ? null : g.provider)}
          />
        ))}
      </Box>
      {guides.filter((g) => g.provider === open).map((g) => (
        <Box key={g.provider} sx={{ pl: 1 }}>
          <ol style={{ margin: 0, paddingLeft: 20 }}>
            {g.steps.map((s) => (
              <li key={s}><Typography variant="body2">{s.replace('{number}', shown)}</Typography></li>
            ))}
          </ol>
          <Link href={g.help_url} target="_blank" rel="noopener noreferrer" variant="body2">
            {g.provider} help
          </Link>
        </Box>
      ))}
    </Box>
  );
}

export default function ReceptionistNumberRequest({ onLive }: Props) {
  const [status, setStatus] = useState<NumberStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    mode: 'keep_existing',
    area_code: '',
    existing_number: '',
    legal_name: '',
    address_line1: '',
    address_line2: '',
    city: '',
    postcode: '',
    setup: 'self',
  });

  const load = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/receptionist/number-request');
      const data: NumberStatus = await res.json();
      setStatus(data);
      if (data.phone_number) onLive();
    } catch (err) {
      setError(errorDetail(err));
    } finally {
      setLoading(false);
    }
  }, [onLive]);

  useEffect(() => { load(); }, [load]);

  // While a request is open, check for progress every 30 seconds.
  const pending = !!status?.request && OPEN.includes(status.request.state);
  useEffect(() => {
    if (!pending) return undefined;
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await apiRequest('POST', '/v1/receptionist/number-request', form);
      await load();
    } catch (err) {
      setError(errorDetail(err));
    } finally {
      setSaving(false);
    }
  };

  const cancel = async () => {
    setSaving(true);
    setError(null);
    try {
      await apiRequest('DELETE', '/v1/receptionist/number-request');
      await load();
    } catch (err) {
      setError(errorDetail(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Card sx={{ p: 3, mb: 3 }}><CircularProgress size={20} /></Card>;
  if (!status) return error ? <Alert severity="error" sx={{ mb: 3 }}>{error}</Alert> : null;
  if (!status.ready) {
    return (
      <Alert severity="info" sx={{ mb: 3 }}>
        Phone number requests aren't switched on yet. Please contact support for a number.
      </Alert>
    );
  }

  const req = status.request;
  const open = req && OPEN.includes(req.state);

  if (status.phone_number) {
    return (
      <Card sx={{ p: 3, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={600} gutterBottom>Your receptionist's number</Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <PhoneIcon fontSize="small" color="action" />
          <Typography variant="body1"><strong>{status.phone_number}</strong></Typography>
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Switch the receptionist on above, then ring {status.phone_number} from your own phone to test it.
        </Typography>
        {req?.mode === 'keep_existing' && <ForwardingSteps guides={status.forwarding} number={status.phone_number} />}
      </Card>
    );
  }

  return (
    <Card sx={{ p: 3, mb: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} gutterBottom>Phone number</Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {open && req ? (
        <Box>
          <Stepper activeStep={stageOf(req.state)} alternativeLabel sx={{ mb: 2 }}>
            {STAGES.map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
          </Stepper>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {req.state === 'requested' && "We've got your request and will set your number up shortly."}
            {req.state === 'waiting_bundle' && "UK numbers need the regulator's checks on your business. This can take a few working days; we'll carry on as soon as it's approved."}
            {(req.state === 'buying' || req.state === 'bought') && 'Your number is being set up now.'}
          </Typography>
          {req.setup === 'done_for_you' && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              We'll also set your receptionist up with you
              {req.setup_fee_pence ? ` (${pounds(req.setup_fee_pence)}, one-off)` : ''}.
            </Typography>
          )}
          {req.mode === 'keep_existing' && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Once it's live, we'll show you how to forward {req.existing_number} to it.
            </Typography>
          )}
          {(req.state === 'requested' || req.state === 'waiting_bundle') && (
            <Button size="small" onClick={cancel} disabled={saving}>Cancel request</Button>
          )}
        </Box>
      ) : (
        <Box>
          {req?.state === 'declined' && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Your last request wasn't approved: {req.decline_reason}
            </Alert>
          )}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Your receptionist answers calls on its own phone number. Ask for one here; there's no charge for the
            number itself.
          </Typography>

          <Typography variant="body2" fontWeight={600}>1. How will callers reach you?</Typography>
          <RadioGroup value={form.mode} onChange={set('mode')} sx={{ mb: 1 }}>
            <FormControlLabel value="keep_existing" control={<Radio size="small" />}
              label="Keep my existing number (recommended): forward it to the receptionist" />
            <FormControlLabel value="new_local" control={<Radio size="small" />} label="A new local number" />
          </RadioGroup>
          <Collapse in={form.mode === 'keep_existing'}>
            <TextField fullWidth size="small" label="The number your callers ring now" placeholder="0161 496 0000"
              value={form.existing_number} onChange={set('existing_number')} sx={{ mb: 1 }} />
            <ForwardingSteps guides={status.forwarding} number={null} />
          </Collapse>
          <TextField fullWidth size="small" sx={{ my: 1 }}
            label={form.mode === 'new_local' ? 'Area code you want (optional)' : 'Area code for the new number (optional)'}
            placeholder="0161" value={form.area_code} onChange={set('area_code')} />

          <Typography variant="body2" fontWeight={600} sx={{ mt: 2 }}>2. Your business, for the UK regulator</Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            The regulator (Ofcom) requires every UK number to be registered to a business and address.
          </Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1 }}>
            <TextField size="small" label="Legal business name" value={form.legal_name} onChange={set('legal_name')} />
            <TextField size="small" label="Address line 1" value={form.address_line1} onChange={set('address_line1')} />
            <TextField size="small" label="Address line 2 (optional)" value={form.address_line2} onChange={set('address_line2')} />
            <TextField size="small" label="Town or city" value={form.city} onChange={set('city')} />
            <TextField size="small" label="Postcode" value={form.postcode} onChange={set('postcode')} />
          </Box>

          <Typography variant="body2" fontWeight={600} sx={{ mt: 2 }}>3. Setting the receptionist up</Typography>
          {status.in_plan ? (
            <Typography variant="body2" color="text.secondary">
              Included in your plan: we'll set it up with you. No charge.
            </Typography>
          ) : (
            <RadioGroup value={form.setup} onChange={set('setup')}>
              <FormControlLabel value="self" control={<Radio size="small" />}
                label="I'll set up the greeting and knowledge myself (free)" />
              <FormControlLabel value="done_for_you" control={<Radio size="small" />}
                label={`Set it all up for me (${pounds(status.setup_fee_pence)}, one-off)`} />
            </RadioGroup>
          )}

          <Box sx={{ mt: 2 }}>
            <Button variant="contained" onClick={submit} disabled={saving}>
              {saving ? <CircularProgress size={18} /> : 'Request my number'}
            </Button>
          </Box>
        </Box>
      )}
    </Card>
  );
}
