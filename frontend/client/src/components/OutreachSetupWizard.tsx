// OUT-15 — the owner's outreach setup wizard, and changing the sending
// mailbox. Every step saves on the server, so the owner can leave and come
// back. Aria's drafts are suggestions: nothing takes effect until the owner
// approves it, and nothing here sends an email.
import { createContext, useContext, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Box, Button, Checkbox, Chip, FormControlLabel, MenuItem, Paper, Stack, Step, StepContent,
  StepLabel, Stepper, TextField, Typography,
} from '@mui/material';
import { apiRequest } from '@/lib/queryClient';
import { outreachError } from '@/hooks/useOutreachData';

type StepState = 'done' | 'todo' | 'blocked';
export interface SetupStatus { steps: Record<string, StepState>; next: string | null; complete: boolean; started: boolean }
interface Account { id: string; email_address: string; display_name?: string | null; provider: string }
interface Health { status: 'pass' | 'fail'; advice: string[]; evidence: Record<string, unknown>; enabled?: boolean; hold?: string | null }

const STEPS: { key: string; label: string; optional?: boolean }[] = [
  { key: 'brand', label: 'Your brands' },
  { key: 'mailboxes', label: 'Sending mailboxes' },
  { key: 'audience', label: "Who you'll contact, and why" },
  { key: 'privacy', label: 'Privacy notice' },
  { key: 'knowledge', label: 'Facts Aria may use', optional: true },
  { key: 'limits', label: 'Daily limits' },
  { key: 'campaign', label: 'Your first campaign' },
];

const setupPath = (path: string) => `/v1/outreach/setup/${path}`;

// Every cached list is keyed by business, so switching business never shows
// another business's choices (Codex OUT-15 review 1).
const BusinessKey = createContext('');
const useBusinessKey = () => useContext(BusinessKey);

export function useSetupStatus(businessId: string) {
  return useQuery<SetupStatus>({
    queryKey: ['outreach-setup', businessId],
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

function useCall(businessId: string) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function call<T = any>(method: string, path: string, body?: unknown): Promise<T | null> {
    setBusy(true); setError('');
    try {
      const result = await (await apiRequest(method, setupPath(path), body)).json();
      client.invalidateQueries({ queryKey: ['outreach-setup', businessId] });
      client.invalidateQueries({ queryKey: ['outreach', businessId] });
      return result as T;
    } catch (e) {
      const text = e instanceof Error ? e.message : '';
      // The server explains a refusal in plain words; show it.
      setError(/^\d{3}:\s*/.test(text) ? text.replace(/^\d{3}:\s*/, '').replace(/^\{"detail":"?|"?\}$/g, '') : outreachError(e));
      return null;
    } finally { setBusy(false); }
  }
  return { call, busy, error };
}

export default function OutreachSetupWizard({ businessId }: { businessId: string }) {
  const status = useSetupStatus(businessId);
  const accounts = useAccounts(businessId);
  const api = useCall(businessId);
  const [active, setActive] = useState<string | null>(null);
  const [brandId, setBrandId] = useState('');
  const [complianceId, setComplianceId] = useState('');
  const steps = status.data?.steps || {};
  const current = active || status.data?.next || 'brand';
  const started = status.data && Object.values(steps).some(s => s === 'done');

  if (status.isLoading) return <Typography>Loading setup…</Typography>;
  if (status.isError) return <Alert severity="warning">{outreachError(status.error)}</Alert>;

  return (
    <BusinessKey.Provider value={businessId}>
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack spacing={2}>
        <Typography variant="h5">Set up outreach</Typography>
        <Typography color="text.secondary">
          A few steps, saved as you go. Aria drafts the wording; you approve everything. Nothing is sent
          until you approve each email.
        </Typography>
        {api.error && <Alert severity="error">{api.error}</Alert>}
        {!started && (
          <Button variant="contained" disabled={api.busy} onClick={() => api.call('POST', 'begin')}>
            Start setting up outreach
          </Button>
        )}
        <Stepper orientation="vertical" nonLinear activeStep={STEPS.findIndex(s => s.key === current)}>
          {STEPS.map(step => (
            <Step key={step.key} completed={steps[step.key] === 'done'}>
              <StepLabel
                optional={step.optional ? <Typography variant="caption">Optional, can be done later</Typography> : undefined}
                onClick={() => setActive(step.key)} sx={{ cursor: 'pointer' }}
              >
                {step.label}
              </StepLabel>
              <StepContent>
                {step.key === 'brand' && <BrandStep api={api} accounts={accounts.data || []} onSaved={setBrandId} />}
                {step.key === 'mailboxes' && <MailboxStep api={api} accounts={accounts.data || []} />}
                {step.key === 'audience' && <AudienceStep api={api} brandId={brandId} setBrandId={setBrandId} onApproved={setComplianceId} />}
                {step.key === 'privacy' && <PrivacyStep api={api} brandId={brandId} setBrandId={setBrandId} />}
                {step.key === 'knowledge' && <KnowledgeStep brandId={brandId} />}
                {step.key === 'limits' && <LimitsStep />}
                {step.key === 'campaign' && (
                  <CampaignStep api={api} accounts={accounts.data || []} brandId={brandId}
                    setBrandId={setBrandId} complianceId={complianceId} setComplianceId={setComplianceId} />
                )}
              </StepContent>
            </Step>
          ))}
        </Stepper>
        <Box>
          <Button variant="contained" size="large" disabled={api.busy || !status.data?.complete}
            onClick={() => api.call('POST', 'finish')}>
            Start outreach
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {status.data?.complete
              ? 'Starting sends nothing. Aria prepares emails; you approve each one.'
              : 'Finish the steps above first.'}
          </Typography>
        </Box>
      </Stack>
    </Paper>
    </BusinessKey.Provider>
  );
}

type Api = ReturnType<typeof useCall>;

function BrandStep({ api, accounts, onSaved }: { api: Api; accounts: Account[]; onSaved: (id: string) => void }) {
  const [name, setName] = useState('');
  const [sender, setSender] = useState('');
  const [mailbox, setMailbox] = useState('');
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2">Add each brand you contact people as, e.g. "New Body Gym" or "FitFutures".</Typography>
      <TextField label="Brand name" value={name} onChange={e => setName(e.target.value)} />
      <TextField label="Sender identity (shown in every footer)" helperText='e.g. "New Body Gym Ltd"'
        value={sender} onChange={e => setSender(e.target.value)} />
      <TextField select label="Usual sending mailbox (optional)" value={mailbox} onChange={e => setMailbox(e.target.value)}>
        <MenuItem value="">Choose later</MenuItem>
        {accounts.map(a => <MenuItem key={a.id} value={a.id}>{a.email_address}{a.display_name ? ` · ${a.display_name}` : ''}</MenuItem>)}
      </TextField>
      <Button variant="outlined" disabled={api.busy || !name || !sender} onClick={async () => {
        const out = await api.call<{ id: string }>('POST', 'brands', { name, sender_identity: sender, ...(mailbox ? { default_mailbox_id: mailbox } : {}) });
        if (out) { onSaved(out.id); setName(''); setSender(''); setMailbox(''); }
      }}>Save brand</Button>
    </Stack>
  );
}

function MailboxStep({ api, accounts }: { api: Api; accounts: Account[] }) {
  const [results, setResults] = useState<Record<string, Health>>({});
  async function addAndCheck(id: string) {
    // No cap on a check: a new mailbox starts at 5 and an existing limit is kept.
    if (!(await api.call('POST', 'mailboxes', { mailbox_id: id }))) return;
    const health = await api.call<Health>('POST', `mailboxes/${id}/check`);
    if (health) setResults(r => ({ ...r, [id]: health }));
  }
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
              {health?.advice?.map(line => <Alert key={line} severity="info" sx={{ overflowWrap: 'anywhere' }}>{line}</Alert>)}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}

function BrandPicker({ brandId, setBrandId }: { brandId: string; setBrandId: (id: string) => void }) {
  const businessId = useBusinessKey();
  const brands = useQuery<{ items?: { id: string; name: string }[] }>({
    queryKey: ['outreach', businessId, 'setup-brands'], queryFn: async () => (await apiRequest('GET', '/v1/outreach/brands')).json(), retry: false,
  });
  return (
    <TextField select label="Brand" value={brandId} onChange={e => setBrandId(e.target.value)}>
      {(brands.data?.items || []).map(b => <MenuItem key={b.id} value={b.id}>{b.name}</MenuItem>)}
    </TextField>
  );
}

function AudienceStep({ api, brandId, setBrandId, onApproved }: { api: Api; brandId: string; setBrandId: (id: string) => void; onApproved: (id: string) => void }) {
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
    <Stack spacing={1.5}>
      <BrandPicker brandId={brandId} setBrandId={setBrandId} />
      <TextField label="Who do you want to reach?" multiline minRows={2} value={description}
        helperText="In your own words, e.g. independent gyms and PT studios that could host a trainee"
        onChange={e => setDescription(e.target.value)} />
      <TextField label="Sectors (comma separated)" value={segments} onChange={e => setSegments(e.target.value)} />
      <TextField label="Areas (comma separated)" value={regions} onChange={e => setRegions(e.target.value)} />
      <Button variant="outlined" disabled={api.busy || !brandId || !description} onClick={async () => {
        const out = await api.call<Record<string, string>>('POST', 'audience/draft', { brand_id: brandId, description, segments: list(segments), regions: list(regions) });
        if (out) setDraft(out);
      }}>Ask Aria to draft the justification</Button>
      {draft && (
        <Stack spacing={1.5}>
          <Alert severity="info">Aria's draft. Edit anything, then approve. This is your record of why contacting these people is fair (UK GDPR legitimate interests).</Alert>
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
            if (out) { onApproved(out.id); setDraft(null); }
          }}>Approve</Button>
        </Stack>
      )}
    </Stack>
  );
}

function PrivacyStep({ api, brandId, setBrandId }: { api: Api; brandId: string; setBrandId: (id: string) => void }) {
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2">Every outreach email links to a short privacy notice. Aria drafts it; you check and approve it; Business Hero publishes it.</Typography>
      <BrandPicker brandId={brandId} setBrandId={setBrandId} />
      <Button variant="outlined" disabled={api.busy || !brandId} onClick={async () => {
        const out = await api.call<{ text: string }>('POST', `brands/${brandId}/privacy/draft`);
        if (out) setText(out.text);
      }}>Ask Aria to draft the notice</Button>
      <TextField label="Privacy notice" multiline minRows={8} value={text} onChange={e => setText(e.target.value)} />
      <Button variant="contained" disabled={api.busy || !brandId || !text.trim()} onClick={async () => {
        const out = await api.call<{ url: string }>('POST', `brands/${brandId}/privacy/approve`, { text });
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
        Up to 20 new emails a day across the business, and never more than each mailbox's warm-up allows. Emails go
        on weekdays, 9am to 5pm UK. Copying yourself in is off unless you turn it on.
      </Typography>
      <Button component={Link} to="/app/outreach/settings" variant="text" sx={{ alignSelf: 'flex-start' }}>Change limits</Button>
    </Stack>
  );
}

function CampaignStep({ api, accounts, brandId, setBrandId, complianceId, setComplianceId }: {
  api: Api; accounts: Account[]; brandId: string; setBrandId: (id: string) => void; complianceId: string; setComplianceId: (id: string) => void;
}) {
  const [name, setName] = useState('');
  const [mailbox, setMailbox] = useState('');
  const [createdNow, setCreated] = useState('');
  // After a reload, carry on with a drafted campaign whose emails aren't approved yet.
  const drafts = useQuery<{ items?: { id: string; status: string }[] }>({
    queryKey: ['outreach', useBusinessKey(), 'setup-campaigns'],
    queryFn: async () => (await apiRequest('GET', '/v1/outreach/campaigns?limit=50')).json(), retry: false,
  });
  // Saving wording pauses a campaign, so a paused one is also still in setup.
  const created = createdNow || (drafts.data?.items || []).find(c => c.status === 'draft' || c.status === 'paused')?.id || '';
  const compliance = useQuery<{ items?: { id: string; brand_id: string; version: number; decision: string; reviewed_at?: string }[] }>({
    queryKey: ['outreach', useBusinessKey(), 'setup-compliance'], queryFn: async () => (await apiRequest('GET', '/v1/outreach/compliance?limit=50')).json(), retry: false,
  });
  const audiences = (compliance.data?.items || []).filter(a => a.decision === 'approved')
    .map(a => ({ ...a, summary: `Approved audience v${a.version}${a.reviewed_at ? `, ${a.reviewed_at.slice(0, 10)}` : ''}` }));
  return (
    <Stack spacing={1.5}>
      <BrandPicker brandId={brandId} setBrandId={setBrandId} />
      <TextField label="Campaign name" value={name} onChange={e => setName(e.target.value)} />
      <TextField select label="Send from" value={mailbox} onChange={e => setMailbox(e.target.value)}
        helperText="Chosen explicitly. Changing your general email default never changes this.">
        {accounts.map(a => <MenuItem key={a.id} value={a.id}>{a.email_address}</MenuItem>)}
      </TextField>
      {audiences.length > 0 ? (
        <TextField select label="Approved audience" value={complianceId} onChange={e => setComplianceId(e.target.value)}>
          {audiences.filter(a => !brandId || a.brand_id === brandId).map(a => <MenuItem key={a.id} value={a.id}>{a.summary || a.id}</MenuItem>)}
        </TextField>
      ) : !complianceId && <Alert severity="info">Approve who you'll contact first.</Alert>}
      <Button variant="contained" disabled={api.busy || !name || !brandId || !mailbox || !complianceId} onClick={async () => {
        const out = await api.call<{ id: string }>('POST', 'campaign', { name, brand_id: brandId, mailbox_id: mailbox, compliance_id: complianceId, daily_cap: 5 });
        if (out) setCreated(out.id);
      }}>Ask Aria to draft the three emails</Button>
      {created && <CampaignTemplates campaignId={created} />}
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
              <TextField label="Subject" value={value.subject} onChange={e => setEdits({ ...edits, [step.ordinal]: { ...value, subject: e.target.value } })} />
              <TextField label="Email" multiline minRows={4} value={value.body} onChange={e => setEdits({ ...edits, [step.ordinal]: { ...value, body: e.target.value } })} />
            </Stack>
          </Paper>
        );
      })}
      {error && <Alert severity="error">{error}</Alert>}
      <Stack direction="row" spacing={1} flexWrap="wrap">
        <Button variant="outlined" disabled={busy || !changed} onClick={async () => {
          const body = { version: campaign.data!.item!.version, steps: steps.map(s => ({ ordinal: s.ordinal, delay_business_days: s.delay_business_days, ...(edits[s.ordinal] || { subject: s.subject, body: s.body }) })) };
          if (await send('PUT', `/v1/outreach/campaigns/${campaignId}/sequence`, body)) setEdits({});
        }}>Save wording</Button>
        <Button variant="contained" disabled={busy || changed || approved} onClick={() =>
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

interface ResearchStatus { enabled: boolean; monthly_cap_pence: number; spent_pence: number; lessons: string[]; last_run?: string | null; summary?: string | null }

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
  const client = useQueryClient();
  const api = useCall(businessId);
  const [budget, setBudget] = useState<string>('');
  const [notes, setNotes] = useState<string | null>(null);
  const data = research.data;
  async function save(path: string, body: unknown) {
    if (await api.call('POST', path, body)) client.invalidateQueries({ queryKey: ['outreach-research', businessId] });
  }
  if (!data) return null;
  const pounds = (p: number) => `£${(p / 100).toFixed(2)}`;
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="h6">Research</Typography>
        <Typography variant="body2">
          Each weekday morning Aria looks for up to 20 new contacts per business, at least 10 of them named
          decision-makers, and checks every one before it's kept: the email is on their website, the domain receives
          mail, the company is registered at Companies House, and they haven't been contacted or opted out.
        </Typography>
        {data.summary && <Alert severity="info" icon={false}><strong>Latest:</strong> {data.summary}</Alert>}
        <FormControlLabel control={<Checkbox checked={data.enabled} disabled={api.busy}
          onChange={(_, v) => save('research', { enabled: v })} />} label="Aria researches new contacts each weekday" />
        <Typography variant="body2">This month: {pounds(data.spent_pence)} of {pounds(data.monthly_cap_pence)}. Research pauses when the budget is reached.</Typography>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <TextField size="small" type="number" label="Monthly budget (£)" value={budget}
            placeholder={(data.monthly_cap_pence / 100).toFixed(0)} onChange={e => setBudget(e.target.value)} />
          <Button variant="outlined" disabled={api.busy || budget === '' || Number(budget) < 0}
            onClick={() => save('research', { monthly_cap_pence: Math.round(Number(budget) * 100) })}>Save budget</Button>
        </Stack>
        <Typography variant="subtitle2">What Aria has learned</Typography>
        <Typography variant="body2" color="text.secondary">
          Aria learns from your own results: which sectors, areas and roles reply. Add your own notes too, one per line.
        </Typography>
        <TextField multiline minRows={3} value={notes ?? data.lessons.join('\n')} onChange={e => setNotes(e.target.value)}
          placeholder="e.g. Independent studios reply far more than chains." />
        <Button variant="outlined" disabled={api.busy || notes === null} sx={{ alignSelf: 'flex-start' }}
          onClick={async () => { await save('research/lessons', { lessons: (notes || '').split('\n').map(s => s.trim()).filter(Boolean) }); setNotes(null); }}>
          Save notes
        </Button>
        {api.error && <Alert severity="error">{api.error}</Alert>}
      </Stack>
    </Paper>
  );
}

// ------------------------------------------------- OUT-11: auto-approve ---

interface AutopilotState { enabled: boolean; valid: boolean; reason?: string | null; manual_accepted: number; needed: number; granted_at?: string | null }

export function AutopilotSwitch({ businessId, campaign }: { businessId: string; campaign: { id: string; version: number; sequence_version: number } }) {
  const client = useQueryClient();
  const api = useCall(businessId);
  const [confirming, setConfirming] = useState(false);
  const state = useQuery<Record<string, AutopilotState>>({
    queryKey: ['outreach-autopilot', businessId],
    queryFn: async () => (await apiRequest('GET', setupPath('autopilot'))).json(), retry: false,
  });
  const s = state.data?.[campaign.id];
  if (!s) return null;
  const refresh = () => client.invalidateQueries({ queryKey: ['outreach-autopilot', businessId] });
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Typography variant="h6">Automatic sending</Typography>
          <Chip size="small" color={s.enabled && s.valid ? 'success' : 'default'}
            label={s.enabled && s.valid ? 'On' : s.enabled ? 'Paused' : 'Off'} />
        </Stack>
        {s.needed > 0 ? (
          <Typography variant="body2">
            Approve this campaign's first emails yourself to build trust: {s.manual_accepted} of 5 done, {s.needed} to go.
            Then you can let Aria send them for you.
          </Typography>
        ) : s.enabled ? (
          <>
            <Typography variant="body2">
              Aria sends this campaign's approved emails for you: one at a time, spread through the day, weekdays 9–5,
              within your limits. Answers to replies still wait for you.
            </Typography>
            {!s.valid && s.reason && <Alert severity="warning">{s.reason}</Alert>}
            <Button variant="outlined" color="warning" disabled={api.busy} sx={{ alignSelf: 'flex-start' }}
              onClick={async () => { await api.call('DELETE', `autopilot/${campaign.id}`); refresh(); }}>
              Turn off automatic sending
            </Button>
          </>
        ) : confirming ? (
          <>
            <Alert severity="info">
              Aria will send this campaign's emails without asking each time: only the wording you approved, from this
              campaign's mailbox, within its caps and warm-up, weekdays 9–5. Every opt-out, reply check and pause still
              applies. Changing the wording or sender turns it off until you switch it on again.
            </Alert>
            <Stack direction="row" spacing={1}>
              <Button variant="contained" disabled={api.busy} onClick={async () => {
                if (await api.call('POST', `autopilot/${campaign.id}`, { version: campaign.version, sequence_version: campaign.sequence_version })) {
                  setConfirming(false); refresh();
                }
              }}>Yes, let Aria send them</Button>
              <Button onClick={() => setConfirming(false)}>Cancel</Button>
            </Stack>
          </>
        ) : (
          <Button variant="contained" sx={{ alignSelf: 'flex-start' }} onClick={() => setConfirming(true)}>
            Let Aria send this campaign's emails automatically
          </Button>
        )}
        {api.error && <Alert severity="error">{api.error}</Alert>}
      </Stack>
    </Paper>
  );
}
