// OUT-15 — the owner's outreach setup wizard, and changing the sending
// mailbox. Every step saves on the server, so the owner can leave and come
// back. Aria's drafts are suggestions: nothing takes effect until the owner
// approves it, and nothing here sends an email.
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox, Chip, CircularProgress,
  FormControlLabel, MenuItem, Paper, Stack, Step, StepContent, StepLabel, Stepper, TextField, Typography,
} from '@mui/material';
import { ExpandMore } from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';
import { outreachError } from '@/hooks/useOutreachData';

type StepState = 'done' | 'todo' | 'blocked';
export interface BrandAudience { id: string; description: string; approved: boolean; campaign: null | { id: string; name: string; mailbox_id: string; approved: boolean; other_inbox: boolean; ready: boolean } }
export interface BrandProfile { offer?: string; audience?: string; proof?: string; tone?: string; ask?: string; website?: string }
export interface BrandSetup { id: string; name: string; sender_identity: string; profile?: BrandProfile; mailbox_id: string | null; mailbox_address: string | null; mailbox_ok: boolean; privacy: boolean; audiences: BrandAudience[]; ready: boolean }
export interface SetupStatus { steps: Record<string, StepState>; next: string | null; complete: boolean; started: boolean; brands?: BrandSetup[] }
interface Account { id: string; email_address: string; display_name?: string | null; provider: string }
interface GuideRecord { what: 'spf' | 'dkim' | 'dmarc'; type: string; host: string; action: string; current?: string | string[] | null; value?: string | null; why: string; steps?: string[]; help_url?: string }
interface Guide { domain: string; mail_provider: string; records: GuideRecord[]; email_to_helper: { subject: string; body: string };
  dns_host: { key: string; name: string | null; help_url: string | null; domain_connect: { supported: boolean; available: boolean } } }
interface Health { status: 'pass' | 'fail'; advice: string[]; evidence: Record<string, unknown>; enabled?: boolean; hold?: string | null; guide?: Guide }

export const STEPS: { key: string; label: string; optional?: boolean }[] = [
  { key: 'brand', label: 'What you do outreach for' },
  { key: 'mailboxes', label: 'Sending inbox' },
  { key: 'audience', label: "Who it contacts, and why" },
  { key: 'privacy', label: 'Privacy notice' },
  { key: 'knowledge', label: 'Facts Aria may use', optional: true },
  { key: 'limits', label: 'Daily limits' },
  { key: 'campaign', label: 'The emails for each audience' },
];

const setupPath = (path: string) => `/v1/outreach/setup/${path}`;

// Every cached list is keyed by business, so switching business never shows
// another business's choices (Codex OUT-15 review 1).
const BusinessKey = createContext('');
const useBusinessKey = () => useContext(BusinessKey);

export function useSetupStatus(businessId: string, enabled = true) {
  return useQuery<SetupStatus>({
    queryKey: ['outreach-setup', businessId], enabled: !!businessId && enabled,
    queryFn: async () => (await apiRequest('GET', setupPath('status'))).json(),
    staleTime: 10000, retry: false,
  });
}

function useAccounts(businessId: string) {
  return useQuery<Account[]>({
    queryKey: ['email-accounts', businessId],
    queryFn: async () => {
      const data = await (await apiRequest('GET', '/v1/email/accounts')).json();
      return Array.isArray(data) ? data : (data.accounts || data.items || []);
    },
    retry: false,
  });
}

// OUT-20 (Mike's click test): say what is happening while a step saves or
// Aria writes, so a few seconds' wait never looks like nothing happened.
function doingLabel(method: string, path: string): string {
  if (path === 'begin') return 'Getting outreach ready…';
  if (path.startsWith('brands') && path.includes('/privacy/draft')) return 'Aria is drafting your privacy notice…';
  if (path.includes('/privacy/approve')) return 'Publishing your privacy notice…';
  if (path.startsWith('brands')) return 'Saving your brand…';
  if (path.endsWith('/check')) return "Checking your domain's email settings — this takes a few seconds…";
  if (path.startsWith('mailboxes')) return 'Adding the mailbox…';
  if (path === 'audience/draft') return 'Aria is drafting why contacting them is fair — about 10 seconds…';
  if (path.startsWith('audience')) return 'Saving your approval…';
  if (path === 'campaign') return 'Aria is writing your three emails — usually 10–20 seconds…';
  if (path.endsWith('/redraft')) return 'Aria is rewriting the emails with your notes…';
  if (path === 'finish') return 'Starting outreach…';
  return method === 'GET' ? 'Loading…' : 'Saving…';
}

function useCall(businessId: string) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [doing, setDoing] = useState('');
  const [error, setError] = useState('');
  async function call<T = any>(method: string, path: string, body?: unknown): Promise<T | null> {
    setBusy(true); setError(''); setDoing(doingLabel(method, path));
    try {
      const result = await (await apiRequest(method, setupPath(path), body)).json();
      // Refresh only what the change affects (refreshing every outreach view made each step slower).
      client.invalidateQueries({ queryKey: ['outreach-setup', businessId] });
      if (/^(campaign|campaigns\/|mailboxes|finish)/.test(path)) client.invalidateQueries({ queryKey: ['outreach', businessId] });
      return result as T;
    } catch (e) {
      const text = e instanceof Error ? e.message : '';
      // The server explains a refusal in plain words; show it.
      setError(/^\d{3}:\s*/.test(text) ? text.replace(/^\d{3}:\s*/, '').replace(/^\{"detail":"?|"?\}$/g, '') : outreachError(e));
      return null;
    } finally { setBusy(false); setDoing(''); }
  }
  return { call, busy, error, doing };
}

const MAGIC = ['Making a little magic…', 'Nearly there…', 'Still working on it…'];

export function Working({ label }: { label: string }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!label) { setTick(0); return; }
    const t = window.setInterval(() => setTick(n => n + 1), 5000);
    return () => window.clearInterval(t);
  }, [label]);
  if (!label) return null;
  return (
    <Stack direction="row" spacing={1.5} alignItems="center" role="status" aria-live="polite"
      sx={{ p: 1.25, borderRadius: 2, bgcolor: 'action.hover' }}>
      <CircularProgress size={18} />
      <Typography variant="body2">{label}{tick > 0 ? ` ${MAGIC[(tick - 1) % MAGIC.length]}` : ''}</Typography>
    </Stack>
  );
}

function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button size="small" variant="outlined" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); window.setTimeout(() => setDone(false), 2000); } catch { /* copy by hand */ }
    }}>{done ? 'Copied ✓' : label}</Button>
  );
}

// OUT-18: outreach is set up per brand, product or service — its own inbox,
// its own audiences, one email sequence per audience. Setup is finished when
// one brand is ready; another is set up by repeating the steps.
const REQUIRED_STEPS = STEPS.filter(s => !s.optional).map(s => s.key);

function brandSteps(brand: BrandSetup | undefined, knowledge: StepState | undefined): Record<string, StepState> {
  return {
    brand: brand ? 'done' : 'todo',
    mailboxes: brand?.mailbox_ok ? 'done' : 'todo',
    audience: brand?.audiences.some(a => a.approved) ? 'done' : (brand ? 'todo' : 'blocked'),
    privacy: brand?.privacy ? 'done' : 'todo',
    knowledge: knowledge || 'todo',
    limits: 'done',
    campaign: brand?.audiences.some(a => a.approved && a.campaign?.ready) ? 'done' : 'todo',
  };
}

export default function OutreachSetupWizard({ businessId, adding = false, onClose }: {
  businessId: string; adding?: boolean; onClose?: () => void;
}) {
  const status = useSetupStatus(businessId);
  const accounts = useAccounts(businessId);
  const api = useCall(businessId);
  const [active, setActive] = useState<string | null>(adding ? 'brand' : null);
  const [brandId, setBrandId] = useState('');
  const [newBrand, setNewBrand] = useState(adding);
  // A ready brand shows its summary unless the owner opens one of its steps
  // (Codex OUT-18 part B review 1: finishing the steps must reach the summary).
  const [revisiting, setRevisiting] = useState(false);
  const brands = status.data?.brands || [];
  const brand = brandId ? brands.find(b => b.id === brandId)
    : newBrand ? undefined : (brands.find(b => !b.ready) || brands[0]);
  const steps = brandSteps(brand, status.data?.steps?.knowledge);
  const begun = !!status.data && (brands.length > 0 || Object.values(status.data.steps || {}).some(x => x === 'done'));
  const current = active || REQUIRED_STEPS.find(k => steps[k] !== 'done') || 'campaign';
  const choose = (id: string) => { setBrandId(id); setNewBrand(false); setActive(null); setRevisiting(false); };
  const another = () => { setBrandId(''); setNewBrand(true); setActive('brand'); setRevisiting(false); };
  const showReady = !!brand?.ready && !revisiting;

  if (status.isLoading) return <Typography>Loading setup…</Typography>;
  if (status.isError) return <Alert severity="warning">{outreachError(status.error)}</Alert>;

  return (
    <BusinessKey.Provider value={businessId}>
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
          <Typography variant="h5">{brand ? `Set up outreach for ${brand.name}` : 'Set up outreach'}</Typography>
          {onClose && <Button onClick={onClose}>Close</Button>}
        </Stack>
        <Typography color="text.secondary">
          Each brand, product or service you promote gets its own inbox, its own audiences and its own emails.
          Steps save as you go. Aria drafts the wording; you edit and approve everything. Nothing is sent until you
          approve it.
        </Typography>
        <Working label={api.doing} />
        {api.error && (current !== 'brand' || showReady) && <Alert severity="error">{api.error}</Alert>}
        {!begun && (
          <Button variant="contained" disabled={api.busy} onClick={() => api.call('POST', 'begin')}>
            Start setting up outreach
          </Button>
        )}
        {brands.length > 1 && (
          <TextField select label="Setting up" value={brand?.id || ''} onChange={e => choose(e.target.value)}>
            {brands.map(b => <MenuItem key={b.id} value={b.id}>{b.name}{b.ready ? ' · ready' : ' · in progress'}</MenuItem>)}
          </TextField>
        )}
        {showReady && brand ? (
          <BrandReady brand={brand} started={!!status.data?.started} busy={api.busy}
            onAnother={another} onStart={() => api.call('POST', 'finish')} onClose={onClose}
            onReview={() => { setActive('mailboxes'); setRevisiting(true); }} />
        ) : (
          <Stepper orientation="vertical" nonLinear activeStep={STEPS.findIndex(s => s.key === current)}>
            {STEPS.map(step => (
              <Step key={step.key} completed={steps[step.key] === 'done'}>
                <StepLabel
                  optional={step.optional ? <Typography variant="caption">Optional, can be done later</Typography> : undefined}
                  onClick={() => { setActive(step.key); if (brand?.ready) setRevisiting(true); }} sx={{ cursor: 'pointer' }}
                >
                  {step.label}
                </StepLabel>
                <StepContent>
                  {step.key === 'brand' && <BrandsStep api={api} brands={brands} current={brand}
                    onSaved={choose} onNext={() => setActive('mailboxes')} onChoose={choose} />}
                  {step.key === 'mailboxes' && <><MailboxStep api={api} accounts={accounts.data || []} />
                    {brand && <BrandInbox api={api} brand={brand} accounts={accounts.data || []} />}</>}
                  {step.key === 'audience' && (brand ? <AudiencesStep key={brand.id} api={api} brand={brand} /> : <NeedBrand />)}
                  {step.key === 'privacy' && (brand ? <PrivacyStep key={brand.id} api={api} brand={brand} /> : <NeedBrand />)}
                  {step.key === 'knowledge' && <KnowledgeStep brandId={brand?.id || ''} />}
                  {step.key === 'limits' && <LimitsStep />}
                  {step.key === 'campaign' && (brand ? <EmailsStep key={brand.id} api={api} brand={brand} /> : <NeedBrand />)}
                </StepContent>
              </Step>
            ))}
          </Stepper>
        )}
        {brand?.ready && revisiting && <Button sx={{ alignSelf: 'flex-start' }} onClick={() => setRevisiting(false)}>Back to {brand.name}'s summary</Button>}
        {status.data?.complete && !status.data.started && !showReady && (
          <Box>
            <Button variant="contained" size="large" disabled={api.busy} onClick={() => api.call('POST', 'finish')}>
              Start outreach
            </Button>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Starting sends nothing. Aria prepares emails; you approve each one.
            </Typography>
          </Box>
        )}
      </Stack>
    </Paper>
    </BusinessKey.Provider>
  );
}

type Api = ReturnType<typeof useCall>;

function NeedBrand() {
  return <Alert severity="info">Add what you do outreach for first.</Alert>;
}

function BrandReady({ brand, started, busy, onAnother, onStart, onClose, onReview }: {
  brand: BrandSetup; started: boolean; busy: boolean; onAnother: () => void; onStart: () => void; onClose?: () => void;
  onReview: () => void;
}) {
  const audiences = brand.audiences.filter(a => a.approved && a.campaign?.ready);
  return (
    <Alert severity="success" icon={false} sx={{ '& .MuiAlert-message': { width: '100%' } }}>
      <Stack spacing={1.5}>
        <Typography variant="h6">{brand.name} is ready.</Typography>
        <Typography variant="body2">
          Aria will look for {audiences.map(a => a.description.toLowerCase()).join('; ') || 'your audiences'} and
          draft {audiences.length === 1 ? `the "${audiences[0].campaign!.name}" emails` : 'the right emails for each'}
          {brand.mailbox_address ? `, sent from ${brand.mailbox_address}` : ''}. You approve every email before it goes.
        </Typography>
        <Typography variant="body2">
          <strong>Have another business, service or product to promote?</strong> Set it up the same way: it gets its
          own inbox, its own audiences and its own emails.
        </Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button variant="outlined" onClick={onAnother}>+ Set up another</Button>
          <Button onClick={onReview}>Review or change {brand.name}'s setup</Button>
          {!started && <Button variant="contained" disabled={busy} onClick={onStart}>Start outreach</Button>}
          {started && onClose && <Button variant="contained" onClick={onClose}>Done</Button>}
        </Stack>
      </Stack>
    </Alert>
  );
}

function BrandsStep({ api, brands, current, onSaved, onNext, onChoose }: {
  api: Api; brands: BrandSetup[]; current?: BrandSetup; onSaved: (id: string) => void; onNext: () => void;
  onChoose: (id: string) => void;
}) {
  const blank = { name: '', sender: '', profile: {} as BrandProfile };
  const [rows, setRows] = useState([blank]);
  const [editing, setEditing] = useState('');
  // Mike's click test (25 Oct 2026): saving gave no sign it had worked, and the
  // step moved on by itself. Now it says what was saved and stays here, so
  // another brand can be added; "Next" moves on when the owner is ready.
  const [saved, setSaved] = useState<string[]>([]);
  const filled = rows.filter(r => r.name.trim() && r.sender.trim());
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2">
        Add each brand, product or service you want to win customers for: for example "New Body Gym", or
        "FitFutures". Most businesses need just one.
      </Typography>
      <Alert severity="info" icon={false}>
        <strong>The more Aria knows, the better your emails.</strong> Aria writes your outreach from these details:
        what you offer, who it's for, why people choose you, how you like to sound and what you'd like them to do.
        A few honest, specific sentences make the difference between an email that gets a reply and one that
        reads like spam. You can change these at any time.
      </Alert>
      {brands.length > 0 && (
        <Stack spacing={1}>
          {brands.map(b => (
            <Paper key={b.id} variant="outlined" sx={{ p: 1.5, borderColor: current?.id === b.id ? 'primary.main' : undefined }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography sx={{ fontWeight: 600 }}>{b.name}</Typography>
                <Chip size="small" color={b.ready ? 'success' : 'default'} label={b.ready ? 'Ready' : 'In progress'} />
                {b.mailbox_address && <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>{b.mailbox_address}</Typography>}
                {current?.id !== b.id && <Button size="small" onClick={() => onChoose(b.id)}>Set up</Button>}
                <Button size="small" onClick={() => setEditing(editing === b.id ? '' : b.id)}>
                  {editing === b.id ? 'Close' : 'Edit details'}
                </Button>
              </Stack>
              {!b.profile?.offer && editing !== b.id &&
                <Typography variant="caption" color="text.secondary">Add what you offer and who it's for, so Aria can write better emails.</Typography>}
              {editing === b.id && <BrandEditor api={api} brand={b} onDone={() => setEditing('')} />}
            </Paper>
          ))}
        </Stack>
      )}
      {rows.map((row, i) => (
        <Paper key={i} variant="outlined" sx={{ p: 1.5 }}>
          <Stack spacing={1}>
            <TextField label="Brand, product or service" value={row.name}
              onChange={e => setRows(rows.map((r, j) => j === i ? { ...r, name: e.target.value } : r))} />
            <TextField label="Who it's sent by (shown in every email footer)" helperText='e.g. "New Body Gym Ltd"'
              value={row.sender} onChange={e => setRows(rows.map((r, j) => j === i ? { ...r, sender: e.target.value } : r))} />
            <ProfileFields value={row.profile} onChange={profile => setRows(rows.map((r, j) => j === i ? { ...r, profile } : r))} />
            {rows.length > 1 && <Button size="small" sx={{ alignSelf: 'flex-start' }}
              onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</Button>}
          </Stack>
        </Paper>
      ))}
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Button variant="text" onClick={() => setRows([...rows, blank])}>+ Add another brand, product or service</Button>
        <Button variant="contained" disabled={api.busy || filled.length === 0} onClick={async () => {
          let first = '';
          const names: string[] = [];
          setSaved([]);
          for (const r of filled) {
            const out = await api.call<{ id: string }>('POST', 'brands', { name: r.name.trim(), sender_identity: r.sender.trim(), profile: r.profile });
            if (!out) {
              setSaved(names);
              setRows(rows.filter(x => !names.includes(x.name.trim())));   // keep what didn't save, to try again
              return;
            }
            names.push(r.name.trim());
            first = first || out.id;
          }
          setSaved(names);
          setRows([blank]);
          if (first) onSaved(first);
        }}>{api.busy ? 'Saving…' : 'Save'}</Button>
        {brands.length > 0 && <Button variant="outlined" onClick={onNext}>Next: sending inbox</Button>}
      </Stack>
      {saved.length > 0 && <Alert severity="success">Saved: {saved.join(', ')}. Add another below, or go on to the sending inbox.</Alert>}
      {api.error && <Alert severity="error">Not saved: {api.error}</Alert>}
    </Stack>
  );
}

const PROFILE_LABELS: [keyof BrandProfile, string, string][] = [
  ['offer', 'What you offer', 'e.g. Free 12-week Level 3 fitness interns who support your members and staff'],
  ['audience', "Who it's for", 'e.g. Independent gyms and health clubs in Essex and Kent'],
  ['proof', 'Why people choose you', 'e.g. 120 interns placed since 2019; Ofsted-rated training provider'],
  ['tone', 'How you like to sound', 'e.g. Friendly, direct, no jargon'],
  ['ask', "What you'd like them to do", 'e.g. A 15-minute call this week'],
  ['website', 'Website (optional)', 'e.g. https://newbodyhf.co.uk/fitfutures'],
];

function ProfileFields({ value, onChange }: { value: BrandProfile; onChange: (v: BrandProfile) => void }) {
  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2">Tell Aria about it (recommended)</Typography>
      {PROFILE_LABELS.map(([key, label, hint]) => (
        <TextField key={key} label={label} placeholder={hint} value={value[key] || ''} multiline={key !== 'website'}
          minRows={key === 'offer' || key === 'proof' ? 2 : 1}
          onChange={e => onChange({ ...value, [key]: e.target.value })} />
      ))}
    </Stack>
  );
}

function BrandEditor({ api, brand, onDone }: { api: Api; brand: BrandSetup; onDone: () => void }) {
  const [name, setName] = useState(brand.name);
  const [sender, setSender] = useState(brand.sender_identity);
  const [profile, setProfile] = useState<BrandProfile>(brand.profile || {});
  return (
    <Stack spacing={1} sx={{ mt: 1.5 }}>
      <TextField label="Brand, product or service" value={name} onChange={e => setName(e.target.value)} />
      <TextField label="Who it's sent by (shown in every email footer)" value={sender} onChange={e => setSender(e.target.value)} />
      <ProfileFields value={profile} onChange={setProfile} />
      <Button variant="contained" sx={{ alignSelf: 'flex-start' }} disabled={api.busy || !name.trim() || !sender.trim()}
        onClick={async () => {
          if (await api.call('PATCH', `brands/${brand.id}`, { name: name.trim(), sender_identity: sender.trim(), profile })) onDone();
        }}>Save changes</Button>
    </Stack>
  );
}

function BrandInbox({ api, brand, accounts }: { api: Api; brand: BrandSetup; accounts: Account[] }) {
  return (
    <Stack spacing={1} sx={{ mt: 2 }} key={brand.id}>
      <TextField select label={`Send ${brand.name} emails from`} value={brand.mailbox_id || ''}
        helperText={brand.mailbox_id && !brand.mailbox_ok ? 'Check this mailbox above before it can send.' :
          'Each brand sends from its own inbox. Your general email default never changes this.'}
        onChange={e => api.call('POST', 'brands', { name: brand.name, sender_identity: brand.sender_identity, default_mailbox_id: e.target.value })}>
        {accounts.map(a => <MenuItem key={a.id} value={a.id}>{a.email_address}</MenuItem>)}
      </TextField>
    </Stack>
  );
}

function MailboxStep({ api, accounts }: { api: Api; accounts: Account[] }) {
  const businessId = useBusinessKey();
  const client = useQueryClient();
  const [results, setResults] = useState<Record<string, Health>>({});
  async function addAndCheck(id: string) {
    // No cap on a check: a new mailbox starts at 5 and an existing limit is kept.
    if (!(await api.call('POST', 'mailboxes', { mailbox_id: id }))) return;
    const health = await api.call<Health>('POST', `mailboxes/${id}/check`);
    if (health) setResults(r => ({ ...r, [id]: health }));
  }
  // OUT-20: while a mailbox needs attention and this page is open, check it
  // again every few minutes, so nobody has to keep pressing "Check again".
  const failing = Object.entries(results).filter(([, h]) => h.status !== 'pass').map(([id]) => id);
  const rounds = useRef(0);
  const running = useRef(false);
  useEffect(() => {
    if (!failing.length) { rounds.current = 0; return; }
    let live = true;
    const t = window.setInterval(async () => {
      if (rounds.current >= 20) return window.clearInterval(t);
      if (running.current) return;                       // never overlap a slow round
      running.current = true; rounds.current += 1;
      try {
        for (const id of failing) {
          if (!live) return;
          try {
            const health = await (await apiRequest('POST', setupPath(`mailboxes/${id}/check`))).json();
            if (!live) return;
            setResults(r => ({ ...r, [id]: health }));
            if (health?.status === 'pass') {                // readiness and mailbox lists change with it
              client.invalidateQueries({ queryKey: ['outreach-setup', businessId] });
              client.invalidateQueries({ queryKey: ['outreach', businessId] });
            }
          } catch { /* the next round tries again */ }
        }
      } finally { running.current = false; }
    }, 180000);
    return () => { live = false; window.clearInterval(t); };
  }, [failing.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2">
        Tick the mailboxes that may send outreach. Each is checked automatically so your emails don't land in spam.
        New mailboxes start at 5 emails a day, rising to 10, then 20, as they build a sending history.
      </Typography>
      <Button component={Link} to="/app/settings/email" variant="text" sx={{ alignSelf: 'flex-start' }}>
        Connect another mailbox
      </Button>
      {accounts.length === 0 && <Alert severity="info">No mailboxes connected yet.</Alert>}
      {accounts.map(a => {
        const health = results[a.id];
        return (
          <Paper key={a.id} variant="outlined" sx={{ p: 1.5 }}>
            <Stack spacing={1}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Typography sx={{ overflowWrap: 'anywhere' }}>{a.email_address}</Typography>
                {a.display_name && <Chip size="small" label={a.display_name} />}
                {health && <Chip size="small" color={health.status === 'pass' && !health.hold ? 'success' : 'warning'}
                  label={health.hold ? 'On hold' : health.status === 'pass' ? 'Ready' : 'Needs attention'} />}
              </Stack>
              <Button size="small" variant="outlined" disabled={api.busy} onClick={() => addAndCheck(a.id)}>
                {health ? 'Check again' : 'Use for outreach and check'}
              </Button>
              {health?.hold && <Alert severity="warning" sx={{ overflowWrap: 'anywhere' }}>Its records are fine, but this mailbox is on hold: {health.hold}. A passing check never lifts a hold.</Alert>}
              {health && health.status !== 'pass' && (health.guide
                ? <DnsHelp guide={health.guide} />
                : health.advice?.map(line => <Alert key={line} severity="info" sx={{ overflowWrap: 'anywhere' }}>{line}</Alert>))}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}

// OUT-20 (Mike): a failed check explained plainly, with a choice of ways to fix it.
function DnsHelp({ guide }: { guide: Guide }) {
  const host = guide.dns_host;
  const where = host.name ? `at ${host.name}` : 'wherever your domain is managed';
  const [asked, setAsked] = useState('');
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState('');
  return (
    <Stack spacing={1}>
      <Alert severity="warning" icon={false}>
        <strong>Your emails aren't yet proven to come from you</strong>, so more of them may land in spam. Your
        everyday email keeps working. To fix it, {guide.records.length === 1 ? 'one setting needs' : `${guide.records.length} settings need`} adding
        to {guide.domain} {where}. It usually takes about 10 minutes, and we'll keep checking for you.
      </Alert>
      <Accordion disableGutters>
        <AccordionSummary expandIcon={<ExpandMore />}><Typography sx={{ fontWeight: 600 }}>I'll do it myself</Typography></AccordionSummary>
        <AccordionDetails>
          <Stack spacing={1.5}>
            <Typography variant="body2">
              {host.name ? <>Your domain's settings (DNS) are managed at <strong>{host.name}</strong>. Log in there, open
                {' '}{guide.domain}, then its DNS settings.</> : <>Log in where your domain's settings (DNS) are managed — often
                where you bought the domain, or your web designer's account.</>}
              {host.help_url && <> <a href={host.help_url} target="_blank" rel="noreferrer">Their guide</a>.</>}
            </Typography>
            {guide.records.map((r, i) => (
              <Paper key={r.what} variant="outlined" sx={{ p: 1.5 }}>
                <Stack spacing={0.75}>
                  <Typography variant="subtitle2">
                    {i + 1}. {r.what === 'spf' ? 'Sender check (SPF)' : r.what === 'dkim' ? 'Email signature (DKIM)' : 'Email policy (DMARC)'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">{r.why}</Typography>
                  {r.steps && <Box component="ol" sx={{ m: 0, pl: 2.5 }}>{r.steps.map(step => <li key={step}><Typography variant="body2">{step}</Typography></li>)}</Box>}
                  {r.help_url && <Typography variant="body2"><a href={r.help_url} target="_blank" rel="noreferrer">{guide.mail_provider}'s guide</a></Typography>}
                  {r.value && <>
                    <Typography variant="body2">
                      {r.action === 'edit' ? 'Edit the existing' : 'Add a'} <strong>{r.type}</strong> record · name/host <code>{r.host}</code>
                      {r.action === 'edit' ? ', so it reads:' : ' · value:'}
                    </Typography>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Box component="code" sx={{ p: 0.75, bgcolor: 'action.hover', borderRadius: 1, overflowWrap: 'anywhere' }}>{r.value}</Box>
                      <CopyButton text={r.value} />
                    </Stack>
                    {r.action === 'edit' && typeof r.current === 'string' && <Typography variant="caption" color="text.secondary">It currently reads: {r.current}</Typography>}
                  </>}
                </Stack>
              </Paper>
            ))}
          </Stack>
        </AccordionDetails>
      </Accordion>
      <Accordion disableGutters>
        <AccordionSummary expandIcon={<ExpandMore />}><Typography sx={{ fontWeight: 600 }}>Send this to my web person or IT</Typography></AccordionSummary>
        <AccordionDetails>
          <Stack spacing={1}>
            <Typography variant="body2">Copy this email and send it to whoever looks after your website or domain.</Typography>
            <Typography variant="body2"><strong>Subject:</strong> {guide.email_to_helper.subject}</Typography>
            <Box component="pre" sx={{ m: 0, p: 1.25, bgcolor: 'action.hover', borderRadius: 1, whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 14 }}>
              {guide.email_to_helper.body}
            </Box>
            <Stack direction="row" spacing={1}>
              <CopyButton text={guide.email_to_helper.body} label="Copy the email" />
              <CopyButton text={guide.email_to_helper.subject} label="Copy the subject" />
            </Stack>
          </Stack>
        </AccordionDetails>
      </Accordion>
      {/* "Connect my domain now" (Domain Connect) appears here once a provider has accepted our template. */}
      <Accordion disableGutters>
        <AccordionSummary expandIcon={<ExpandMore />}><Typography sx={{ fontWeight: 600 }}>Set it up for me (paid)</Typography></AccordionSummary>
        <AccordionDetails>
          <Stack spacing={1}>
            <Typography variant="body2">
              Our team can make these changes with you for a one-off fee. We'll confirm the price before doing anything.
            </Typography>
            {asked ? <Alert severity="success">{asked}</Alert> : (
              <Button variant="outlined" sx={{ alignSelf: 'flex-start' }} disabled={asking} onClick={async () => {
                setAsking(true); setAskError('');
                try {
                  const chat = await (await apiRequest('POST', '/v1/support/chat', {
                    content: `Please help me set up email authentication (SPF/DKIM/DMARC) for ${guide.domain} so outreach can send. `
                      + `DNS is managed ${where}. I'd like the paid set-up service.` })).json();
                  if (!chat?.conversation_id) throw new Error('no conversation');
                  if (!chat.escalated) await apiRequest('POST', '/v1/support/escalate', { conversation_id: chat.conversation_id });
                  setAsked("Thanks. Our team will be in touch with the price, usually within one working day. You'll see the conversation in Help & Support.");
                } catch { setAskError("We couldn't send that just now. Please try again, or use Help & Support."); }
                finally { setAsking(false); }
              }}>{asking ? 'Sending…' : 'Ask our team'}</Button>
            )}
            {askError && <Alert severity="error">{askError}</Alert>}
          </Stack>
        </AccordionDetails>
      </Accordion>
      <Typography variant="caption" color="text.secondary">
        We'll check again automatically every few minutes while this page is open, and every morning anyway.
      </Typography>
    </Stack>
  );
}

function AudiencesStep({ api, brand }: { api: Api; brand: BrandSetup }) {
  const [adding, setAdding] = useState(brand.audiences.length === 0);
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2">
        Add each type of organisation {brand.name} contacts. Each gets its own email: for example schools get a PE
        provision email, charities a collaboration email.
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Be specific: "independent gyms and health clubs in Kent and Essex" works far better than "gyms". Aria uses
        this to find the right organisations and to write to them in their terms.
      </Typography>
      {brand.audiences.map(a => (
        <Paper key={a.id} variant="outlined" sx={{ p: 1.5 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography sx={{ overflowWrap: 'anywhere' }}>{a.description}</Typography>
            <Chip size="small" color={a.approved ? 'success' : 'default'} label={a.approved ? 'Approved' : 'Draft'} />
          </Stack>
        </Paper>
      ))}
      {adding ? <AudienceForm api={api} brand={brand} onApproved={() => setAdding(false)} />
        : <Button variant="outlined" sx={{ alignSelf: 'flex-start' }} onClick={() => setAdding(true)}>+ Add another type of organisation</Button>}
    </Stack>
  );
}

function AudienceForm({ api, brand, onApproved }: { api: Api; brand: BrandSetup; onApproved: () => void }) {
  const [description, setDescription] = useState('');
  const [segments, setSegments] = useState('');
  const [regions, setRegions] = useState('');
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  // Decision A: 12 months by default; the owner may choose a different date.
  const [reviewDate, setReviewDate] = useState(() => {
    const d = new Date(); d.setFullYear(d.getFullYear() + 1); return d.toISOString().slice(0, 10);
  });
  const list = (s: string) => s.split(',').map(x => x.trim()).filter(Boolean);
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Stack spacing={1.5}>
        <TextField label="Who should it contact?" multiline minRows={2} value={description}
          helperText="In your own words, e.g. secondary schools that need PE support"
          onChange={e => setDescription(e.target.value)} />
        <TextField label="Sectors (comma separated)" value={segments} onChange={e => setSegments(e.target.value)} />
        <TextField label="Areas (comma separated)" value={regions} onChange={e => setRegions(e.target.value)} />
        <Button variant="outlined" disabled={api.busy || !description} onClick={async () => {
          const out = await api.call<Record<string, string>>('POST', 'audience/draft', { brand_id: brand.id, description, segments: list(segments), regions: list(regions) });
          if (out) setDraft(out);
        }}>Ask Aria to draft the justification</Button>
        {draft && (
          <Stack spacing={1.5}>
            <Alert severity="info">Aria's draft. Edit anything, then approve. This is your record of why contacting these organisations is fair (UK GDPR legitimate interests).</Alert>
            {(['purpose', 'necessity', 'balancing_test', 'safeguards'] as const).map(k => (
              <TextField key={k} label={k.replace('_', ' ')} multiline minRows={2} value={draft[k] || ''}
                onChange={e => setDraft({ ...draft, [k]: e.target.value })} />
            ))}
            <TextField type="date" label="Review this again by" InputLabelProps={{ shrink: true }} value={reviewDate}
              onChange={e => setReviewDate(e.target.value)} helperText="12 months by default; choose sooner if you prefer" />
            <Button variant="contained" disabled={api.busy || !reviewDate} onClick={async () => {
              const { purpose, necessity, balancing_test, safeguards } = draft;
              const out = await api.call<{ id: string }>('POST', `audience/${draft.id}/approve`,
                { purpose, necessity, balancing_test, safeguards, review_due_at: `${reviewDate}T23:59:59Z` });
              if (out) { setDraft(null); setDescription(''); setSegments(''); setRegions(''); onApproved(); }
            }}>Approve</Button>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

function PrivacyStep({ api, brand }: { api: Api; brand: BrandSetup }) {
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2">Every {brand.name} email links to a short privacy notice. Aria drafts it; you check and approve it; Business Hero publishes it.</Typography>
      {brand.privacy && !text && <Alert severity="success">{brand.name}'s notice is published. You can replace it below.</Alert>}
      <Button variant="outlined" disabled={api.busy} onClick={async () => {
        const out = await api.call<{ text: string }>('POST', `brands/${brand.id}/privacy/draft`);
        if (out) setText(out.text);
      }}>Ask Aria to draft the notice</Button>
      <TextField label="Privacy notice" multiline minRows={8} value={text} onChange={e => setText(e.target.value)} />
      <Button variant="contained" disabled={api.busy || !text.trim()} onClick={async () => {
        const out = await api.call<{ url: string }>('POST', `brands/${brand.id}/privacy/approve`, { text });
        if (out) setUrl(out.url);
      }}>Approve and publish</Button>
      {url && <Alert severity="success" sx={{ overflowWrap: 'anywhere' }}>Published at {url}</Alert>}
    </Stack>
  );
}

function KnowledgeStep(_: { brandId: string }) {
  return (
    <Stack spacing={1}>
      <Typography variant="body2">
        Facts Aria may quote when someone replies with a question: prices, availability, what you offer. Each has a
        review date; when it passes, Aria stops using it. You can add these now or later.
      </Typography>
      <Button component={Link} to="/app/outreach/settings" variant="outlined" sx={{ alignSelf: 'flex-start' }}>
        Add facts in Outreach settings
      </Button>
    </Stack>
  );
}

function LimitsStep() {
  return (
    <Stack spacing={1}>
      <Typography variant="body2">
        Up to 20 new emails a day for each brand, and never more than each mailbox's warm-up allows (5, then 10, then
        20 a day as it builds a sending history). Emails go on weekdays, 9am to 5pm UK. Copying yourself in is off
        unless you turn it on.
      </Typography>
      <Button component={Link} to="/app/outreach/settings" variant="text" sx={{ alignSelf: 'flex-start' }}>Change limits</Button>
    </Stack>
  );
}

function EmailsStep({ api, brand }: { api: Api; brand: BrandSetup }) {
  const approved = brand.audiences.filter(a => a.approved);
  const [open, setOpen] = useState<string>('');
  if (approved.length === 0) return <Alert severity="info">Approve who {brand.name} contacts first.</Alert>;
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2">
        Aria drafts three emails for each type of organisation: a first email and two follow-ups. Edit anything, then
        approve. Approving sends nothing.
      </Typography>
      {!brand.mailbox_id && <Alert severity="info">Choose {brand.name}'s sending inbox first.</Alert>}
      {!brand.profile?.offer && <Alert severity="info" icon={false}>
        Tip: Aria writes much better emails when she knows what {brand.name} offers and who it's for. Add those under
        <strong> What you do outreach for → Edit details</strong>, then draft or redraft.
      </Alert>}
      {approved.map(a => (
        <Paper key={a.id} variant="outlined" sx={{ p: 1.5 }}>
          <Stack spacing={1}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{a.description}</Typography>
              {a.campaign && <Chip size="small" color={a.campaign.ready ? 'success' : a.campaign.other_inbox ? 'warning' : 'default'}
                label={a.campaign.ready ? 'Emails approved' : a.campaign.other_inbox ? 'On another inbox' : !a.campaign.approved ? 'Waiting for your approval' : 'Inbox needs its check'} />}
            </Stack>
            {!a.campaign ? (
              <Button variant="contained" sx={{ alignSelf: 'flex-start' }} disabled={api.busy || !brand.mailbox_id}
                onClick={() => api.call('POST', 'campaign', { name: a.description.slice(0, 120), brand_id: brand.id,
                  mailbox_id: brand.mailbox_id, compliance_id: a.id, daily_cap: 5 })}>
                Ask Aria to draft the emails
              </Button>
            ) : a.campaign.other_inbox ? (
              <Stack spacing={1}>
                <Typography variant="body2">
                  These emails send from a different inbox to {brand.name}'s{brand.mailbox_address ? ` (${brand.mailbox_address})` : ''}.
                  Copy them across: same wording, which you approve once more.
                </Typography>
                <Button variant="contained" sx={{ alignSelf: 'flex-start' }} disabled={api.busy || !brand.mailbox_id}
                  onClick={() => api.call('POST', `campaigns/${a.campaign!.id}/copy`, { mailbox_id: brand.mailbox_id })}>
                  Copy the emails to {brand.name}'s inbox
                </Button>
              </Stack>
            ) : a.campaign.ready && open !== a.id ? (
              <Button size="small" sx={{ alignSelf: 'flex-start' }} onClick={() => setOpen(a.id)}>Read or edit the emails</Button>
            ) : <CampaignTemplates campaignId={a.campaign.id} />}
          </Stack>
        </Paper>
      ))}
    </Stack>
  );
}

// ------------------------------------------------ change sending mailbox ---

export function ChangeSendingMailbox({ businessId }: { businessId: string }) {
  const accounts = useAccounts(businessId);
  const api = useCall(businessId);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [reason, setReason] = useState('');
  const [retire, setRetire] = useState(false);
  const [result, setResult] = useState<{ switched: string[]; kept_on_old: string[]; paused_enrolments: number; dismissed_cards: string[] } | null>(null);
  const list = accounts.data || [];
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="h6">Change sending mailbox</Typography>
        <Typography variant="body2">
          Rebrand, new name or a mailbox losing its reputation: move your brands and unsent campaigns to another mailbox in
          one step. The new mailbox must pass its check first. The old inbox stays connected, so replies are still read.
        </Typography>
        <TextField select label="From" value={from} onChange={e => setFrom(e.target.value)}>
          {list.map(a => <MenuItem key={a.id} value={a.id}>{a.email_address}</MenuItem>)}
        </TextField>
        <TextField select label="To" value={to} onChange={e => setTo(e.target.value)}>
          {list.filter(a => a.id !== from).map(a => <MenuItem key={a.id} value={a.id}>{a.email_address}</MenuItem>)}
        </TextField>
        <TextField label="Reason" value={reason} onChange={e => setReason(e.target.value)} helperText="e.g. Rebrand, or Reputation dropped" />
        <FormControlLabel control={<Checkbox checked={retire} onChange={(_, v) => setRetire(v)} />}
          label="Retire the old mailbox now (stops it sending; anyone part-way through is paused and listed for you)" />
        {api.error && <Alert severity="error">{api.error}</Alert>}
        <Button variant="contained" disabled={api.busy || !from || !to || !reason.trim()} onClick={async () => {
          const out = await api.call<typeof result>('POST', 'mailboxes/replace', { old_mailbox_id: from, new_mailbox_id: to, reason, retire_old: retire });
          if (out) setResult(out);
        }}>Change mailbox</Button>
        {result && (
          <Alert severity="success">
            Moved {result.switched.length} campaign(s). {result.dismissed_cards.length} waiting email(s) will be prepared again from the new mailbox.
            {result.kept_on_old.length > 0 && ` ${result.kept_on_old.length} campaign(s) already part-way through stay on the old mailbox so their threads continue${retire ? `; ${result.paused_enrolments} prospect(s) paused` : ''}. You can copy them to the new mailbox from Campaigns.`}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}


// The three emails, read, edited and approved without leaving the wizard
// (Codex OUT-15 review 1: setup could not be finished in the app).
function CampaignTemplates({ campaignId }: { campaignId: string }) {
  const businessId = useBusinessKey();
  const client = useQueryClient();
  const campaign = useQuery<{ item?: { version: number; sequence_version: number } }>({
    queryKey: ['outreach', businessId, `campaigns/${campaignId}`],
    queryFn: async () => (await apiRequest('GET', `/v1/outreach/campaigns/${campaignId}`)).json(), retry: false,
  });
  const sequence = useQuery<{ items?: { ordinal: number; delay_business_days: number; subject: string; body: string; approved_at?: string | null }[] }>({
    queryKey: ['outreach', businessId, `campaigns/${campaignId}/sequence`],
    queryFn: async () => (await apiRequest('GET', `/v1/outreach/campaigns/${campaignId}/sequence`)).json(), retry: false,
  });
  const [edits, setEdits] = useState<Record<number, { subject: string; body: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // OUT-20 (Mike): work on the wording WITH Aria — notes in, a redraft out,
  // nothing saved until the owner saves and approves it.
  const [notes, setNotes] = useState('');
  const [rewriting, setRewriting] = useState(false);
  const [rewritten, setRewritten] = useState(false);
  const steps = [...(sequence.data?.items || [])].sort((a, b) => a.ordinal - b.ordinal);
  const approved = steps.length === 3 && steps.every(s => s.approved_at);
  const changed = Object.keys(edits).length > 0;
  const refresh = () => { client.invalidateQueries({ queryKey: ['outreach', businessId] }); client.invalidateQueries({ queryKey: ['outreach-setup', businessId] }); };
  async function send(method: string, path: string, body: unknown) {
    setBusy(true); setError('');
    try { await (await apiRequest(method, path, body)).json(); refresh(); return true; }
    catch (e) { setError(outreachError(e)); return false; } finally { setBusy(false); }
  }
  if (!campaign.data?.item || steps.length !== 3) return <Typography>Loading the drafted emails…</Typography>;
  const labels = ['First email', 'Follow-up after 5 working days', 'Final email after 7 more'];
  return (
    <Stack spacing={1.5}>
      <Alert severity={approved ? 'success' : 'info'}>
        {approved ? 'Approved. These three emails are ready.' : "Aria's drafts. Edit anything, save, then approve. Approving sends nothing."}
      </Alert>
      {steps.map(step => {
        const value = edits[step.ordinal] || { subject: step.subject, body: step.body };
        return (
          <Paper key={step.ordinal} variant="outlined" sx={{ p: 1.5 }}>
            <Stack spacing={1}>
              <Typography variant="subtitle2">{labels[step.ordinal]}</Typography>
              <TextField label="Subject" value={value.subject} disabled={rewriting} onChange={e => setEdits({ ...edits, [step.ordinal]: { ...value, subject: e.target.value } })} />
              <TextField label="Email" multiline minRows={4} value={value.body} disabled={rewriting} onChange={e => setEdits({ ...edits, [step.ordinal]: { ...value, body: e.target.value } })} />
            </Stack>
          </Paper>
        );
      })}
      <Paper variant="outlined" sx={{ p: 1.5, bgcolor: 'action.hover' }}>
        <Stack spacing={1}>
          <Typography variant="subtitle2">Work on these with Aria</Typography>
          <Typography variant="body2" color="text.secondary">
            Tell Aria what to change: something to mention, a different angle, shorter, warmer, more direct. She
            rewrites all three emails; you review them here before anything is saved. Go back and forth as often as
            you like.
          </Typography>
          <TextField multiline minRows={2} value={notes} onChange={e => setNotes(e.target.value)}
            placeholder="e.g. Mention our free trial week. Gyms care about member retention, not staffing. Make the first email shorter." />
          <Stack direction="row" spacing={1} alignItems="center">
            <Button variant="contained" disabled={busy || rewriting || !notes.trim()} onClick={async () => {
              setRewriting(true); setError(''); setRewritten(false);
              try {
                const current = steps.map(st => edits[st.ordinal] || { subject: st.subject, body: st.body });
                const out = await (await apiRequest('POST', setupPath(`campaigns/${campaignId}/redraft`), { notes, current })).json();
                const next: Record<number, { subject: string; body: string }> = {};
                steps.forEach((st, i) => { next[st.ordinal] = out.emails[i]; });
                setEdits(next); setRewritten(true);
              } catch (e) { setError(outreachError(e)); } finally { setRewriting(false); }
            }}>Redraft with my notes</Button>
          </Stack>
          {rewriting && <Working label="Aria is rewriting the emails with your notes… (editing is paused until she's done)" />}
          {rewritten && <Alert severity="success">Aria's new version is above. Edit anything, then Save wording and approve.</Alert>}
        </Stack>
      </Paper>
      {busy && <Working label="Saving your emails…" />}
      {error && <Alert severity="error">{error}</Alert>}
      <Stack direction="row" spacing={1} flexWrap="wrap">
        <Button variant="outlined" disabled={busy || rewriting || !changed} onClick={async () => {
          const body = { version: campaign.data!.item!.version, steps: steps.map(s => ({ ordinal: s.ordinal, delay_business_days: s.delay_business_days, ...(edits[s.ordinal] || { subject: s.subject, body: s.body }) })) };
          if (await send('PUT', `/v1/outreach/campaigns/${campaignId}/sequence`, body)) setEdits({});
        }}>Save wording</Button>
        <Button variant="contained" disabled={busy || rewriting || changed || approved} onClick={() =>
          send('POST', `/v1/outreach/campaigns/${campaignId}/approve-templates`, { version: campaign.data!.item!.version, sequence_version: campaign.data!.item!.sequence_version })
        }>Approve these templates</Button>
      </Stack>
    </Stack>
  );
}

// ------------------------- after setup: mailboxes and campaign copy (review 3) ---

// Mailbox registration and "Check again" stay available once outreach has
// started, so a paused mailbox can be rechecked and a replacement prepared.
export function OutreachMailboxes({ businessId }: { businessId: string }) {
  const accounts = useAccounts(businessId);
  const api = useCall(businessId);
  return (
    <BusinessKey.Provider value={businessId}>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={1.5}>
          <Typography variant="h6">Sending mailboxes</Typography>
          <Working label={api.doing} />
          {api.error && <Alert severity="error">{api.error}</Alert>}
          <MailboxStep api={api} accounts={accounts.data || []} />
        </Stack>
      </Paper>
    </BusinessKey.Provider>
  );
}

export function CopyCampaign({ businessId, campaignId }: { businessId: string; campaignId: string }) {
  const accounts = useAccounts(businessId);
  const api = useCall(businessId);
  const [mailbox, setMailbox] = useState('');
  const [done, setDone] = useState('');
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="subtitle1" fontWeight={600}>Copy to another mailbox</Typography>
        <Typography variant="body2">Same audience and wording, sent from a different mailbox. You'll approve the wording once more.</Typography>
        <TextField select label="Send from" value={mailbox} onChange={e => setMailbox(e.target.value)}>
          {(accounts.data || []).map(a => <MenuItem key={a.id} value={a.id}>{a.email_address}</MenuItem>)}
        </TextField>
        <Button variant="outlined" sx={{ alignSelf: 'flex-start' }} disabled={api.busy || !mailbox} onClick={async () => {
          const out = await api.call<{ id: string }>('POST', `campaigns/${campaignId}/copy`, { mailbox_id: mailbox });
          if (out) setDone(out.id);
        }}>Copy campaign</Button>
        {done && <Alert severity="success">Copied. Open it from Campaigns to approve its wording.</Alert>}
        {api.error && <Alert severity="error">{api.error}</Alert>}
      </Stack>
    </Paper>
  );
}

// ---------------------------------------------------- OUT-10: research ---

interface BrandResearch { brand_id: string; name: string; enabled: boolean; monthly_cap_pence: number; spent_pence: number; paused_reason?: string | null; lessons: string[] }
interface ResearchStatus { brands: BrandResearch[]; enabled: boolean; daily_target_per_brand: number; min_cap_pence: number; last_run?: string | null; summary?: string | null }

export function useResearchStatus(businessId: string) {
  return useQuery<ResearchStatus>({
    queryKey: ['outreach-research', businessId],
    queryFn: async () => (await apiRequest('GET', setupPath('research'))).json(),
    staleTime: 30000, retry: false,
  });
}

export function ResearchSummary({ businessId }: { businessId: string }) {
  const research = useResearchStatus(businessId);
  if (!research.data?.summary) return null;
  return <Alert severity="info" icon={false}><strong>Aria:</strong> {research.data.summary}</Alert>;
}

export function ResearchPanel({ businessId }: { businessId: string }) {
  const research = useResearchStatus(businessId);
  const data = research.data;
  if (!data) return null;
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="h6">Research</Typography>
        <Typography variant="body2">
          Each weekday morning Aria looks for up to {data.daily_target_per_brand} new contacts for each brand, at least
          10 of them named decision-makers, and checks every one before it's kept: the email is on their website, the
          domain receives mail, the company is registered at Companies House, and they haven't been contacted or opted out.
        </Typography>
        {data.summary && <Alert severity="info" icon={false}><strong>Latest:</strong> {data.summary}</Alert>}
        {data.brands.length === 0 && <Typography variant="body2">Add a brand in setup to start research.</Typography>}
        {data.brands.map(b => <BrandResearchCard key={b.brand_id} businessId={businessId} brand={b} minCap={data.min_cap_pence} />)}
      </Stack>
    </Paper>
  );
}

function BrandResearchCard({ businessId, brand, minCap }: { businessId: string; brand: BrandResearch; minCap: number }) {
  const client = useQueryClient();
  const api = useCall(businessId);
  const [budget, setBudget] = useState('');
  const [notes, setNotes] = useState<string | null>(null);
  const pounds = (p: number) => `£${(p / 100).toFixed(2)}`;
  const min = minCap / 100;
  async function save(path: string, body: Record<string, unknown>) {
    const ok = await api.call('POST', path, { brand_id: brand.brand_id, ...body });
    if (ok) client.invalidateQueries({ queryKey: ['outreach-research', businessId] });
    return ok;
  }
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.25}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{brand.name}</Typography>
        {brand.paused_reason && <Alert severity="warning">Paused: {brand.paused_reason}</Alert>}
        <FormControlLabel control={<Checkbox checked={brand.enabled} disabled={api.busy}
          onChange={(_, v) => save('research', { enabled: v })} />} label={`Aria researches new contacts for ${brand.name} each weekday`} />
        <Typography variant="body2">This month: {pounds(brand.spent_pence)} of {pounds(brand.monthly_cap_pence)}. Research for {brand.name} pauses when its budget is reached.</Typography>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField size="small" type="number" label="Monthly budget (£)" value={budget} inputProps={{ min }}
            placeholder={(brand.monthly_cap_pence / 100).toFixed(0)} onChange={e => setBudget(e.target.value)}
            helperText={`At least £${min.toFixed(0)}`} />
          <Button variant="outlined" disabled={api.busy || budget === '' || Number(budget) < min || Number(budget) > 1000}
            onClick={async () => { if (await save('research', { monthly_cap_pence: Math.round(Number(budget) * 100) })) setBudget(''); }}>Save budget</Button>
        </Stack>
        <Typography variant="subtitle2">What Aria has learned for {brand.name}</Typography>
        <Typography variant="body2" color="text.secondary">
          Aria learns from this brand's own results: which sectors, areas and roles reply. Add your own notes too, one per line.
        </Typography>
        <TextField multiline minRows={3} value={notes ?? brand.lessons.join('\n')} onChange={e => setNotes(e.target.value)}
          placeholder="e.g. Independent studios reply far more than chains." />
        <Button variant="outlined" disabled={api.busy || notes === null} sx={{ alignSelf: 'flex-start' }}
          onClick={async () => { if (await save('research/lessons', { lessons: (notes || '').split('\n').map(s => s.trim()).filter(Boolean) })) setNotes(null); }}>
          Save notes
        </Button>
        {api.error && <Alert severity="error">{api.error}</Alert>}
      </Stack>
    </Paper>
  );
}
