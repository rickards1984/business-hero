import { useEffect, useState } from 'react';
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import { apiRequest } from '@/lib/queryClient';

// PROFIT-2 (Mike, 31 Oct 2026): income from real Stripe amounts, the
// itemised running costs (carried forward each month, correctable), and six
// months of income, costs and margin. Platform admins only.

interface Detail { recurring_real_pence: number; recurring_estimated_pence: number; estimated_businesses: number;
  topups_pence: number; cash_received_pence: number; total_pence: number }
interface Month { period: string; income_pence: number; costs_pence: number; margin_pence: number }
interface Status { period: string; income_detail: Detail; history: Month[]; fixed_costs_source: string }
interface Bills { period: string; items: { name: string; pence: number }[]; total_pence: number; source: string }

const gbp = (p: number) => `${p < 0 ? '−' : ''}£${(Math.abs(p) / 100).toFixed(2)}`;

export default function AdminRunningCosts() {
  const [status, setStatus] = useState<Status | null>(null);
  const [bills, setBills] = useState<Bills | null>(null);
  const [period, setPeriod] = useState('');
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function load(month?: string) {
    try {
      const s: Status = await (await apiRequest('GET', '/v1/admin/profit')).json();
      setStatus(s);
      const which = month || period || s.period;
      setPeriod(which);
      setBills(await (await apiRequest('GET', `/v1/admin/profit/costs?period=${which}`)).json());
    } catch { setMessage({ ok: false, text: "Running costs couldn't be loaded." }); }
  }
  useEffect(() => { load(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  async function call(method: string, path: string, body?: unknown, done?: string) {
    setBusy(true); setMessage(null);
    try {
      const out = await (await apiRequest(method, path, body)).json();
      await load(period);
      setMessage({ ok: true, text: done || 'Saved.' });
      return out;
    } catch (e) {
      const text = e instanceof Error ? e.message.replace(/^\d{3}:\s*/, '').replace(/^\{"detail":"?|"?\}$/g, '') : '';
      setMessage({ ok: false, text: text || "That couldn't be saved." });
      return null;
    } finally { setBusy(false); }
  }
  async function save(billName: string, pounds: string) {
    const pence = Math.round(Number(pounds) * 100);
    if (!billName.trim() || !Number.isFinite(pence)) { setMessage({ ok: false, text: 'Give the bill a name and an amount in pounds.' }); return; }
    if (await call('PUT', '/v1/admin/profit/costs', { period, name: billName.trim(), pence }, `${billName.trim()} saved for ${period}.`)) {
      setName(''); setAmount('');
    }
  }

  if (!status || !bills) return message ? <Alert severity="warning" sx={{ mb: 3 }}>{message.text}</Alert> : null;
  const d = status.income_detail;
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3, borderRadius: 2, overflowWrap: 'anywhere' }} data-testid="running-costs">
      <Stack spacing={2}>
        <Box>
          <Typography variant="subtitle2">Income this month ({status.period})</Typography>
          <Typography variant="body2">
            Monthly charges: {gbp(d.recurring_real_pence)} from real Stripe invoices
            {d.estimated_businesses > 0 && ` + ${gbp(d.recurring_estimated_pence)} estimated from plan prices for ${d.estimated_businesses} business${d.estimated_businesses === 1 ? '' : 'es'} with no invoice recorded yet`}
            {d.topups_pence > 0 && ` + ${gbp(d.topups_pence)} top-ups`} = {gbp(d.total_pence)}.
          </Typography>
          <Typography variant="body2" color="text.secondary">Cash received so far this month: {gbp(d.cash_received_pence)} (shown only; the alarm uses monthly charges).</Typography>
          <Button size="small" sx={{ mt: 1 }} disabled={busy}
            onClick={() => call('POST', '/v1/admin/profit/refresh-income', undefined, 'Income refreshed from Stripe.')}>Refresh income from Stripe</Button>
        </Box>

        <Box>
          <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
            <Typography variant="subtitle2">Running costs for</Typography>
            <TextField size="small" type="month" value={period} onChange={e => { setPeriod(e.target.value); load(e.target.value); }}
              inputProps={{ max: status.period, 'aria-label': 'Month' }} />
          </Stack>
          {bills.source !== 'list' && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {bills.source === 'railway setting' ? `No bills listed yet: the Railway figure (${gbp(bills.total_pence)}) is used until you add them.` : 'No bills listed yet.'}</Typography>}
          <Stack spacing={0.75} sx={{ mt: 1 }}>
            {bills.source === 'list' && bills.items.map(i => <BillRow key={i.name} name={i.name} pence={i.pence} busy={busy}
              save={v => save(i.name, v)} remove={() => call('DELETE', '/v1/admin/profit/costs', { period, name: i.name }, `${i.name} removed from ${period}.`)} />)}
          </Stack>
          {bills.source === 'list' && <Typography variant="body2" sx={{ mt: 1 }}><strong>Total {gbp(bills.total_pence)}</strong> a month. Each month starts with the previous month's bills; correct any to the actual amount.</Typography>}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 1.5 }}>
            <TextField size="small" label="Bill (e.g. Railway)" value={name} onChange={e => setName(e.target.value)} inputProps={{ maxLength: 60 }} />
            <TextField size="small" label="£ a month" type="number" value={amount} onChange={e => setAmount(e.target.value)} inputProps={{ min: 0, step: '0.01' }} />
            <Button variant="outlined" disabled={busy} onClick={() => save(name, amount)}>Add bill</Button>
          </Stack>
        </Box>

        <Box>
          <Typography variant="subtitle2">The last six months</Typography>
          <Box sx={{ overflowX: 'auto' }}>
            <Box component="table" sx={{ borderCollapse: 'collapse', fontSize: 13, '& td, & th': { py: 0.5, pr: 3, textAlign: 'left', whiteSpace: 'nowrap' } }}>
              <thead><tr><th>Month</th><th>Income</th><th>Costs</th><th>Margin</th></tr></thead>
              <tbody>{status.history.map(m => <tr key={m.period}>
                <td>{m.period}</td><td>{gbp(m.income_pence)}</td><td>{gbp(m.costs_pence)}</td>
                <td style={{ color: m.margin_pence < 0 ? '#B42318' : undefined, fontWeight: m.margin_pence < 0 ? 700 : undefined }}>{gbp(m.margin_pence)}</td>
              </tr>)}</tbody>
            </Box>
          </Box>
          <Typography variant="caption" color="text.secondary">Income here is what came in (no pre-launch trial budget); costs are AI, voice and the bills listed.</Typography>
        </Box>
        {message && <Alert severity={message.ok ? 'success' : 'error'} onClose={() => setMessage(null)}>{message.text}</Alert>}
      </Stack>
    </Paper>
  );
}

function BillRow({ name, pence, busy, save, remove }: { name: string; pence: number; busy: boolean; save: (v: string) => void; remove: () => void }) {
  const [value, setValue] = useState((pence / 100).toFixed(2));
  useEffect(() => setValue((pence / 100).toFixed(2)), [pence]);
  return <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
    <Typography variant="body2" sx={{ minWidth: 140 }}>{name}</Typography>
    <TextField size="small" type="number" value={value} onChange={e => setValue(e.target.value)} inputProps={{ min: 0, step: '0.01', 'aria-label': `${name} £ a month` }} sx={{ width: 120 }} />
    <Button size="small" disabled={busy || value === (pence / 100).toFixed(2)} onClick={() => save(value)}>Save</Button>
    <Button size="small" color="error" disabled={busy} onClick={remove}>Remove</Button>
  </Stack>;
}
