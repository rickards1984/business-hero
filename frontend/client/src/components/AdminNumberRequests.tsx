import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import { apiRequest } from '@/lib/queryClient';
import { errorDetail } from '@/components/ReceptionistNumberRequest';

// RCP-1: Mike's side of a receptionist number request. "Check" saves the
// regulatory bundle and lists numbers (spends nothing); "Buy and set up" is
// the only action that spends, and it asks first.

interface AdminRequest {
  id: string;
  business_id: string;
  business_name: string;
  state: string;
  version: number;
  mode: string;
  area_code: string | null;
  existing_number: string | null;
  legal_name: string;
  address_line1: string;
  address_line2: string | null;
  city: string;
  postcode: string;
  setup: string;
  in_plan: boolean;
  setup_fee_pence: number;
  bundle_sid: string | null;
  address_sid: string | null;
  phone_number: string | null;
  chosen_number: string | null;
  candidates: string[];
  monthly_pence: number | null;
  last_error: string | null;
  owner_told_at: string | null;
  review: string | null;
  created_at: string;
}

const STATE_LABEL: Record<string, string> = {
  requested: 'Requested', waiting_bundle: 'Waiting for UK approval', buying: 'Buying',
  bought: 'Bought, not set up', live: 'Live', declined: 'Declined', cancelled: 'Cancelled',
};

function RequestCard({ r, onChange }: { r: AdminRequest; onChange: () => void }) {
  const [bundle, setBundle] = useState(r.bundle_sid || '');
  const [address, setAddress] = useState(r.address_sid || '');
  const [numbers, setNumbers] = useState<string[]>(r.candidates || []);
  const [chosen, setChosen] = useState(r.candidates?.[0] || '');
  const [monthly, setMonthly] = useState<number | null>(r.monthly_pence);
  const [bundleStatus, setBundleStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(r.last_error);
  const [confirm, setConfirm] = useState(false);
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState('');

  const call = async (path: string, body: object) => {
    setBusy(true);
    setError(null);
    try {
      const res = await apiRequest('POST', `/v1/admin/receptionist/number-requests/${r.id}/${path}`, body);
      return await res.json();
    } catch (err) {
      setError(errorDetail(err));
      onChange();
      return null;
    } finally {
      setBusy(false);
    }
  };

  const check = async () => {
    const out = await call('prepare', { bundle_sid: bundle.trim(), address_sid: address.trim(), version: r.version });
    if (out) {
      setBundleStatus(out.bundle_status);
      setNumbers(out.numbers);
      setChosen(out.numbers[0] || '');
      setMonthly(out.monthly_pence);
      onChange();
    }
  };

  const buy = async () => {
    setConfirm(false);
    if (await call('approve', { phone_number: chosen, version: r.version })) onChange();
  };

  const retry = async () => {
    setConfirmRetry(false);
    if (await call('retry', { version: r.version })) onChange();
  };

  const notify = async () => { if (await call('notify', {})) onChange(); };

  const decline = async () => {
    setDeclining(false);
    if (await call('decline', { reason, version: r.version })) onChange();
  };

  const open = ['requested', 'waiting_bundle'].includes(r.state);
  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1, mb: 1 }}>
        <Typography fontWeight={600}>{r.business_name}</Typography>
        <Chip size="small" label={STATE_LABEL[r.state] || r.state}
          color={r.state === 'live' ? 'success' : r.state === 'bought' || r.state === 'buying' ? 'warning' : 'default'} />
      </Box>
      <Typography variant="body2">
        {r.mode === 'keep_existing' ? `Keep ${r.existing_number}, forwarded` : 'New local number'}
        {r.area_code ? ` · area ${r.area_code}` : ''}
        {' · '}{r.in_plan ? 'In plan' : 'Add-on'}
        {r.setup === 'done_for_you' ? ` · set it up for them${r.setup_fee_pence ? ` (£${r.setup_fee_pence / 100} to collect)` : ''}` : ''}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {r.legal_name}, {r.address_line1}{r.address_line2 ? `, ${r.address_line2}` : ''}, {r.city} {r.postcode}
      </Typography>
      {r.phone_number && <Typography variant="body2">Number: <strong>{r.phone_number}</strong></Typography>}
      {r.review && <Alert severity="warning" sx={{ my: 1 }}>{r.review}</Alert>}
      {error && <Alert severity="error" sx={{ my: 1 }}>{error}</Alert>}
      {r.state === 'live' && !r.owner_told_at && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
          <Typography variant="body2" color="text.secondary">The owner hasn't been emailed (no connected mailbox?).</Typography>
          <Button size="small" onClick={notify} disabled={busy}>Email them again</Button>
        </Box>
      )}

      {open && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Create the regulatory bundle and address in Twilio (Phone Numbers → Regulatory Compliance) with the
            details above, then paste their SIDs. Checking spends nothing.
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <TextField size="small" label="Bundle SID (BU…)" value={bundle} onChange={(e) => setBundle(e.target.value)} sx={{ flex: '1 1 220px' }} />
            <TextField size="small" label="Address SID (AD…)" value={address} onChange={(e) => setAddress(e.target.value)} sx={{ flex: '1 1 220px' }} />
            <Button variant="outlined" onClick={check} disabled={busy || !bundle || !address}>Check</Button>
          </Box>
          {bundleStatus && bundleStatus !== 'twilio-approved' && (
            <Alert severity="info">Bundle is {bundleStatus}. Check again once Twilio approves it.</Alert>
          )}
          {bundleStatus === 'twilio-approved' && numbers.length === 0 && (
            <Alert severity="warning">No numbers available in that area. Ask the owner for a nearby area code.</Alert>
          )}
          {numbers.length > 0 && (
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel>Number</InputLabel>
                <Select label="Number" value={chosen} onChange={(e) => setChosen(String(e.target.value))}>
                  {numbers.map((n) => <MenuItem key={n} value={n}>{n}</MenuItem>)}
                </Select>
              </FormControl>
              {monthly !== null && (
                <Typography variant="body2" color="text.secondary">Twilio: about £{(monthly / 100).toFixed(2)} a month</Typography>
              )}
              <Button variant="contained" onClick={() => setConfirm(true)} disabled={busy || !chosen}>Buy and set up</Button>
            </Box>
          )}
          <Box>
            <Button size="small" color="inherit" onClick={() => setDeclining(true)} disabled={busy}>Decline</Button>
          </Box>
        </Box>
      )}
      {r.state === 'bought' && (
        <Button sx={{ mt: 1 }} variant="outlined" onClick={retry} disabled={busy}>Finish setting it up</Button>
      )}
      {r.state === 'buying' && (
        <Button sx={{ mt: 1 }} variant="outlined" onClick={() => setConfirmRetry(true)} disabled={busy}>
          Retry (never buys twice)
        </Button>
      )}
      {busy && <CircularProgress size={18} sx={{ ml: 1 }} />}

      <Dialog open={confirm} onClose={() => setConfirm(false)}>
        <DialogTitle>Buy {chosen}?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            This buys the number on your Twilio account for {r.business_name}
            {monthly !== null ? `, at about £${(monthly / 100).toFixed(2)} a month (Twilio's price)` : ''}. It points the
            number's calls at Business Hero, checks it, and assigns it. Twilio bills it monthly until you release it
            in Twilio.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirm(false)}>Cancel</Button>
          <Button variant="contained" onClick={buy}>Buy and set up</Button>
        </DialogActions>
      </Dialog>
      <Dialog open={confirmRetry} onClose={() => setConfirmRetry(false)}>
        <DialogTitle>Retry buying {r.chosen_number}?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            The last attempt didn't finish. Retry first looks for a number Twilio already bought for this request and
            uses it. If there isn't one, it buys {r.chosen_number} for {r.business_name}
            {r.monthly_pence ? ` (about £${(r.monthly_pence / 100).toFixed(2)} a month)` : ''}.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmRetry(false)}>Cancel</Button>
          <Button variant="contained" onClick={retry}>Retry</Button>
        </DialogActions>
      </Dialog>
      <Dialog open={declining} onClose={() => setDeclining(false)} fullWidth>
        <DialogTitle>Decline this request</DialogTitle>
        <DialogContent>
          <TextField fullWidth multiline minRows={2} sx={{ mt: 1 }} label="Reason (the owner sees this)"
            value={reason} onChange={(e) => setReason(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeclining(false)}>Cancel</Button>
          <Button variant="contained" onClick={decline} disabled={!reason.trim()}>Decline</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default function AdminNumberRequests() {
  const [requests, setRequests] = useState<AdminRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/admin/receptionist/number-requests');
      setRequests((await res.json()).requests);
      setError(null);
    } catch (err) {
      setError(errorDetail(err));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <Alert severity="info">Receptionist number requests: {error}</Alert>;
  if (!requests) return null;
  const open = requests.filter((r) => ['requested', 'waiting_bundle', 'buying', 'bought'].includes(r.state) || r.review);
  const closed = requests.filter((r) => !open.includes(r));
  if (!requests.length) return null;
  return (
    <Card sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle1" fontWeight={600}>Receptionist number requests ({open.length} to look at)</Typography>
        {closed.length > 0 && (
          <Button size="small" onClick={() => setShowClosed(!showClosed)}>
            {showClosed ? 'Hide closed' : `Show closed (${closed.length})`}
          </Button>
        )}
      </Box>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {(showClosed ? requests : open).map((r) => <RequestCard key={r.id} r={r} onChange={load} />)}
      </Box>
    </Card>
  );
}
