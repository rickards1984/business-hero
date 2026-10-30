import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, Tab, Tabs,
  ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import { apiRequest } from '@/lib/queryClient';

// OUT-14 (Mike, 30 Oct 2026): the approved dashboard. Brand switcher, Aria's
// summary, Needs you, the pipeline, results for a period and (owner only)
// spend. Every number comes from GET /v1/outreach/dashboard, the same
// function Aria's get_outreach_dashboard tool reads.

type Period = 'week' | 'month' | 'all';
const STAGES: [string, string][] = [['found', 'Found'], ['ready', 'Ready'], ['contacted', 'Contacted'], ['replied', 'Replied'],
  ['interested', 'Interested'], ['meeting', 'Meeting'], ['won', 'Won'], ['closed', 'Closed']];
const PERIODS: [Period, string][] = [['week', 'This week'], ['month', 'This month'], ['all', 'All time']];

interface Dashboard {
  brand_id: string | null; period: Period; as_of: string; summary: string;
  brands: { id: string; name: string }[];
  pipeline: Record<string, number>;
  results: { contacted: number; emails_sent: number; replied: number; positive: number; reply_rate: number | null;
    positive_rate: number | null; objections: number; bounces: number; meetings: number; wins: number };
  needs_you: { replies_waiting: number; approvals: number; failures: { emails: number; paused_inboxes: number; awaiting_payment: number } };
  definitions: Record<string, string>;
  spend?: { period: string; brands: { brand_id: string; name: string; allowance_pence: number; spent_pence: number; topups_pence: number; billing: string; live: boolean }[];
    budget: { budget_pence: number | null; committed_pence: number } };
}
interface StagePage { stage: string; total: number; items: { id: string; company?: string; name?: string; role?: string; last_activity_at?: string }[] }

const pounds = (p: number) => `£${(p / 100).toFixed(2)}`;
const rate = (r: number | null) => (r === null ? 'unavailable' : `${(r * 100).toFixed(1)}%`);

export default function OutreachDashboard({ businessId, owner }: { businessId: string; owner: boolean }) {
  const navigate = useNavigate();
  const [brand, setBrand] = useState('all');
  const [period, setPeriod] = useState<Period>('week');
  const [stage, setStage] = useState('');
  const query = brand === 'all' ? `period=${period}` : `period=${period}&brand_id=${brand}`;
  const q = useQuery<Dashboard>({ queryKey: ['outreach-dashboard', businessId, brand, period], retry: false, staleTime: 30000,
    queryFn: async () => (await apiRequest('GET', `/v1/outreach/dashboard?${query}`)).json() });
  if (q.isError) return <Alert severity="warning">The dashboard couldn't load just now. Please try again.</Alert>;
  const d = q.data;
  if (!d) return <Typography variant="body2">Loading the dashboard…</Typography>;
  const brandName = brand === 'all' ? '' : d.brands.find(b => b.id === brand)?.name || '';
  const r = d.results, n = d.needs_you;
  const failures = n.failures.emails + n.failures.paused_inboxes + n.failures.awaiting_payment;
  const askAria = () => navigate(`/app/assistant/chat?prompt=${encodeURIComponent(
    `How is outreach going${brandName ? ` for ${brandName}` : ''}? Use the outreach dashboard numbers for ${PERIODS.find(p => p[0] === period)?.[1].toLowerCase()}.`)}`);
  return (
    <Stack spacing={2} sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
      {d.brands.length > 1 && <Tabs value={brand} onChange={(_, v) => setBrand(v)} variant="scrollable" scrollButtons="auto" aria-label="Brands">
        <Tab value="all" label="All brands" />
        {d.brands.map(b => <Tab key={b.id} value={b.id} label={b.name} />)}
      </Tabs>}

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }} justifyContent="space-between">
          <Typography><strong>Aria:</strong> {d.summary}</Typography>
          <Button variant="outlined" sx={{ minHeight: 44, flexShrink: 0 }} onClick={askAria}>Ask Aria</Button>
        </Stack>
        <Typography variant="caption" color="text.secondary">Updated {new Date(d.as_of).toLocaleString('en-GB')}</Typography>
      </Paper>

      <Section title="Needs you">
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <Button component={Link} to="/app/outreach/replies" variant={n.replies_waiting ? 'contained' : 'outlined'} sx={{ minHeight: 44 }}>
            {n.replies_waiting} {n.replies_waiting === 1 ? 'reply' : 'replies'} waiting</Button>
          <Button component={Link} to="/app" variant={n.approvals ? 'contained' : 'outlined'} sx={{ minHeight: 44 }}>
            {n.approvals} {n.approvals === 1 ? 'approval' : 'approvals'}</Button>
          <Chip color={failures ? 'warning' : 'default'} sx={{ alignSelf: 'center' }}
            label={`${failures} ${failures === 1 ? 'problem' : 'problems'}`} />
        </Stack>
        {failures > 0 && <Typography variant="body2" sx={{ mt: 1 }}>
          {[n.failures.emails && `${n.failures.emails} email${n.failures.emails === 1 ? '' : 's'} not confirmed in the last 7 days`,
            n.failures.paused_inboxes && `${n.failures.paused_inboxes} inbox${n.failures.paused_inboxes === 1 ? '' : 'es'} paused`,
            n.failures.awaiting_payment && `${n.failures.awaiting_payment} brand${n.failures.awaiting_payment === 1 ? '' : 's'} waiting for payment`]
            .filter(Boolean).join(' · ')}.</Typography>}
      </Section>

      <Section title="Pipeline" note="Each person is counted once, at the furthest stage they've reached. Choose a stage to see who's there.">
        <Box sx={{ display: 'grid', gap: 1, gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(4, minmax(0, 1fr))', md: 'repeat(8, minmax(0, 1fr))' } }}>
          {STAGES.map(([key, label]) => <Button key={key} variant="outlined" onClick={() => setStage(key)}
            sx={{ flexDirection: 'column', alignItems: 'flex-start', minHeight: 64, textTransform: 'none' }}>
            <Typography variant="h6" component="span">{d.pipeline[key] ?? 0}</Typography>
            <Typography variant="caption" component="span">{label}</Typography>
          </Button>)}
        </Box>
        <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 1 }}>
          Meetings and wins are the ones you've marked. Interest is never counted as a win.</Typography>
      </Section>

      <Section title="Results">
        <ToggleButtonGroup exclusive size="small" value={period} onChange={(_, v) => v && setPeriod(v)} aria-label="Period" sx={{ mb: 1.5, flexWrap: 'wrap' }}>
          {PERIODS.map(([key, label]) => <ToggleButton key={key} value={key}>{label}</ToggleButton>)}
        </ToggleButtonGroup>
        <Box sx={{ display: 'grid', gap: 1, gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(3, minmax(0, 1fr))', md: 'repeat(5, minmax(0, 1fr))' } }}>
          <Metric label="Contacted" value={r.contacted} hint={d.definitions.contacted} />
          <Metric label="Emails sent" value={r.emails_sent} hint={d.definitions.emails_sent} />
          <Metric label="Reply rate" value={rate(r.reply_rate)} hint={`${r.replied} of ${r.contacted} contacted replied themselves`} />
          <Metric label="Positive" value={r.positive} hint={`${d.definitions.positive} (${rate(r.positive_rate)})`} />
          <Metric label="Objections" value={r.objections} />
          <Metric label="Bounces" value={r.bounces} />
          <Metric label="Meetings" value={r.meetings} hint={d.definitions.meetings} />
          <Metric label="Wins" value={r.wins} hint={d.definitions.wins} />
        </Box>
      </Section>

      {d.spend && <Section title="Spend this month" note="Only you see this.">
        <Stack spacing={1}>
          {d.spend.brands.map(b => <Paper key={b.brand_id} variant="outlined" sx={{ p: 1.5 }}>
            <Typography fontWeight={600}>{b.name}{!b.live ? ' · waiting for payment' : ''}</Typography>
            <Typography variant="body2">AI research and drafting: {pounds(b.spent_pence)} of {pounds(b.allowance_pence)}
              {b.topups_pence ? ` (including ${pounds(b.topups_pence)} of top-ups)` : ''}</Typography>
          </Paper>)}
          <Typography variant="body2">Outreach budget: {pounds(d.spend.budget.committed_pence)} committed
            {d.spend.budget.budget_pence !== null ? ` of ${pounds(d.spend.budget.budget_pence)}` : ' (no budget set)'} this month.</Typography>
        </Stack>
      </Section>}

      <StageDialog businessId={businessId} brand={brand} stage={stage} owner={owner} close={() => setStage('')} />
    </Stack>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return <Paper variant="outlined" sx={{ p: 2 }}>
    <Typography variant="subtitle1" fontWeight={700} sx={{ mb: note ? 0.25 : 1 }}>{title}</Typography>
    {note && <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{note}</Typography>}
    {children}
  </Paper>;
}

function Metric({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return <Paper variant="outlined" sx={{ p: 1.5 }} title={hint}>
    <Typography variant="h6">{value}</Typography>
    <Typography variant="caption" component="p">{label}</Typography>
    {hint && <Typography variant="caption" color="text.secondary" component="p">{hint}</Typography>}
  </Paper>;
}

function StageDialog({ businessId, brand, stage, owner, close }: { businessId: string; brand: string; stage: string; owner: boolean; close: () => void }) {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState('');
  const brandParam = brand === 'all' ? '' : `&brand_id=${brand}`;
  const q = useQuery<StagePage>({ queryKey: ['outreach-dashboard-stage', businessId, brand, stage, offset], enabled: !!stage, retry: false,
    queryFn: async () => (await apiRequest('GET', `/v1/outreach/dashboard/stage/${stage}?limit=20&offset=${offset}${brandParam}`)).json() });
  async function mark(id: string, outcome: string | null) {
    setError('');
    try {
      await apiRequest('POST', `/v1/outreach/dashboard/prospects/${id}/outcome`, { outcome });
      client.invalidateQueries({ queryKey: ['outreach-dashboard', businessId] });
      client.invalidateQueries({ queryKey: ['outreach-dashboard-stage', businessId] });
    } catch { setError("That couldn't be saved just now. Please try again."); }
  }
  const label = STAGES.find(s => s[0] === stage)?.[1] || '';
  const marked = ['meeting', 'won', 'closed'].includes(stage);
  return <Dialog open={!!stage} onClose={() => { setOffset(0); close(); }} fullWidth maxWidth="sm">
    <DialogTitle>{label}: {q.data?.total ?? '…'} {q.data?.total === 1 ? 'person' : 'people'}</DialogTitle>
    <DialogContent>
      <Stack spacing={1} sx={{ pt: 1 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {q.data?.items.length === 0 && <Typography variant="body2">Nobody is at this stage.</Typography>}
        {q.data?.items.map(p => <Paper key={p.id} variant="outlined" sx={{ p: 1.5 }}>
          <Typography fontWeight={600}>{p.name || 'Unnamed'}{p.role ? `, ${p.role}` : ''}</Typography>
          <Typography variant="body2">{p.company || ''}{p.last_activity_at ? ` · last activity ${new Date(p.last_activity_at).toLocaleDateString('en-GB')}` : ''}</Typography>
          {owner && <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
            {marked
              ? <Button size="small" onClick={() => mark(p.id, null)}>Undo mark</Button>
              : <>
                  <Button size="small" variant="outlined" onClick={() => mark(p.id, 'meeting')}>Meeting booked</Button>
                  <Button size="small" variant="outlined" onClick={() => mark(p.id, 'won')}>Won</Button>
                  <Button size="small" onClick={() => mark(p.id, 'closed')}>Closed</Button>
                </>}
          </Stack>}
        </Paper>)}
      </Stack>
    </DialogContent>
    <DialogActions>
      <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</Button>
      <Button disabled={!q.data || offset + 20 >= q.data.total} onClick={() => setOffset(offset + 20)}>Next</Button>
      <Button onClick={() => { setOffset(0); close(); }}>Close</Button>
    </DialogActions>
  </Dialog>;
}
