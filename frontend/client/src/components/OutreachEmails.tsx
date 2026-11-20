import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack,
  TextField, Typography,
} from '@mui/material';
import { apiRequest } from '@/lib/queryClient';
import { outreachError, useOutreachData, useRefreshOutreach } from '@/hooks/useOutreachData';
import { changed, Draft, DraftEmail, edit, payload, Problem, problems, stale, startDraft } from '@/lib/outreachEmailDraft';
import { useShellMobile } from '@/hooks/useShellMobile';

// OUT-28a (Mike, 18 Nov 2026): edit an outreach email at any time, in plain
// words. "Save and use from now on" saves AND approves (Mike's decision); the
// server moves everyone part way through to the new wording, withdraws cards
// built on the old one, and still refuses placeholders such as [Your Name].

export interface EmailResult { wording: number; current: boolean; sent: number; replied: number; interested: number; since: string | null }
export interface CampaignEmail { ordinal: number; delay_business_days: number; subject: string; body: string; placeholder: string | null; approved: boolean; results: EmailResult[] }
export interface CampaignEmails { id: string; name: string; status: string; version: number; sequence_version: number; emails: CampaignEmail[] }
interface Campaign { id: string; name: string; status: string; brand_id: string }

const WHEN = ['Sent first', '5 working days later', '7 more working days later'];

export function campaignLabel(status: string): { text: string; tone: 'success' | 'warning' | 'default' } {
  if (status === 'ready' || status === 'running') return { text: 'Sending', tone: 'success' };
  if (status === 'paused') return { text: 'Waiting for your approval', tone: 'warning' };
  if (status === 'draft') return { text: 'Not started', tone: 'default' };
  return { text: status.replace(/_/g, ' '), tone: 'default' };
}

const percent = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)}%` : '–');
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '');

export function resultsLine(r: EmailResult): string {
  return `Sent ${r.sent} · ${r.replied} replied (${percent(r.replied, r.sent)}) · ${r.interested} interested`;
}

export default function OutreachEmails({ businessId, owner, onSettings }: { businessId: string; owner: boolean; onSettings: (id: string) => void }) {
  const campaigns = useOutreachData(businessId, 'campaigns?limit=50');
  const brands = useOutreachData(businessId, 'brands?limit=50');
  const items = (campaigns.data?.items || []) as Campaign[];
  const [selected, setSelected] = useState('');
  useEffect(() => { if (!selected && items.length) setSelected(items[0].id); }, [items, selected]);
  if (campaigns.isLoading) return <Typography>Loading your emails…</Typography>;
  if (campaigns.isError) return <Alert severity="warning">{outreachError(campaigns.error)} <Button onClick={() => campaigns.refetch()}>Try again</Button></Alert>;
  if (!items.length) return <Paper variant="outlined" sx={{ p: 3 }}><Typography>No campaigns yet. Finish setting up outreach on the Home tab and Aria will draft your first three emails.</Typography></Paper>;
  const brandName = (id: string) => brands.data?.items?.find(b => b.id === id)?.name || '';
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'flex-start' }}>
      <Stack component="nav" aria-label="Campaigns" spacing={1.25} sx={{ flex: '1 1 240px', maxWidth: { md: 300 }, minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 700 }}>Who you're emailing</Typography>
        {items.map(c => {
          const label = campaignLabel(c.status);
          const active = c.id === selected;
          return (
            <Paper key={c.id} component="button" type="button" onClick={() => setSelected(c.id)} variant="outlined"
              aria-current={active ? 'true' : undefined}
              sx={{ p: 2, textAlign: 'left', cursor: 'pointer', font: 'inherit', borderWidth: active ? 2 : 1,
                borderColor: active ? 'primary.main' : 'divider', bgcolor: 'background.paper', borderRadius: 3 }}>
              <Stack spacing={0.5}>
                <Typography sx={{ fontWeight: 700, color: 'text.primary' }}>{c.name}</Typography>
                {brandName(c.brand_id) && <Typography variant="body2">{brandName(c.brand_id)}</Typography>}
                <Box><Chip size="small" color={label.tone} label={label.text} /></Box>
              </Stack>
            </Paper>
          );
        })}
      </Stack>
      <Box sx={{ flex: '999 1 520px', minWidth: 0 }}>
        {selected && <CampaignEmailsPanel key={selected} businessId={businessId} campaignId={selected} owner={owner} onSettings={() => onSettings(selected)} />}
      </Box>
    </Box>
  );
}

function CampaignEmailsPanel({ businessId, campaignId, owner, onSettings }: { businessId: string; campaignId: string; owner: boolean; onSettings: () => void }) {
  const q = useOutreachData(businessId, `campaigns/${campaignId}/emails`);
  const data = q.data as unknown as CampaignEmails | undefined;
  const refresh = useRefreshOutreach(businessId);
  const client = useQueryClient();
  // The snapshot is taken when editing begins and never follows a background
  // refresh: what is saved is what the owner started from (review 1, finding 3).
  const [draft, setDraft] = useState<Draft | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [notice, setNotice] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  if (q.isLoading) return <Typography>Loading the emails…</Typography>;
  if (q.isError || !data) return <Alert severity="warning">{outreachError(q.error)} <Button onClick={() => q.refetch()}>Try again</Button></Alert>;
  const fixes = data.emails.filter(e => e.placeholder);
  const issues = draft ? problems(draft) : [];
  const outOfDate = !!draft && stale(draft, data.version);
  const begin = (ordinal: number) => {
    setNotice(''); setError('');
    if (!draft) setDraft(startDraft(data));
    setOpen(ordinal);
  };
  const discard = () => { setDraft(null); setOpen(null); setError(''); };

  async function save() {
    if (!draft) return;
    setBusy(true); setError('');
    try {
      const out = await (await apiRequest('POST', `/v1/outreach/campaigns/${campaignId}/emails`, payload(draft))).json();
      setDraft(null); setOpen(null);
      refresh();
      client.invalidateQueries({ queryKey: ['outreach-dashboard', businessId] });
      // The new cards are made just after the save, in the background: look
      // again shortly so they appear without waiting for the 5-minute refresh.
      for (const wait of [4000, 12000, 30000]) {
        window.setTimeout(() => {
          client.invalidateQueries({ queryKey: ['aria-actions', businessId] });
          client.invalidateQueries({ queryKey: ['outreach-dashboard', businessId] });
        }, wait);
      }
      const people = out.moved === 1 ? '1 person' : `${out.moved} people`;
      setNotice(
        (out.moved ? `Saved. ${people} already in this campaign will get the new wording from their next email; Aria is preparing any that are due now, so their cards appear in a moment.` : 'Saved. Everyone you email from now on gets the new wording.')
        + (out.automatic === 'off' ? ' Automatic sending for this campaign is off: switch it back on in Campaign settings if you want Aria to carry on by herself.' : '')
        + (out.automatic === 'on' ? ' Aria carries on sending it for you.' : ''));
    } catch (e) { setError(outreachError(e)); } finally { setBusy(false); }
  }

  return (
    <Stack spacing={1.75}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between" alignItems={{ sm: 'baseline' }}>
        <Typography variant="h2">Your 3 emails</Typography>
        <Typography variant="body2">Change any of them whenever you like. Each one stops if the person replies.</Typography>
      </Stack>
      {fixes.length > 0 && !draft && (
        <Alert severity="warning">
          {fixes.length === 1 ? `Email ${fixes[0].ordinal + 1} still says` : `${fixes.length} emails still say`} “{fixes[0].placeholder}”.
          Nothing is sent from this campaign until it's replaced. Press Edit on {fixes.length === 1 ? 'it' : 'each one'}, delete it
          (your name and sign-off are added for you), then save once at the end.
        </Alert>
      )}
      {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
      {data.emails.map(email => {
        const current = draft?.emails.find(e => e.ordinal === email.ordinal);
        return open === email.ordinal && draft && current
          ? <EmailEditor key={email.ordinal} campaignId={campaignId} draft={draft} email={email} value={current} busy={busy}
              onChange={change => setDraft(edit(draft, email.ordinal, change))} onDone={() => setOpen(null)} />
          : <EmailCard key={email.ordinal} email={email} owner={owner} busy={busy}
              pending={!!draft && changed(draft, email.ordinal)} problem={issues.find(i => i.ordinal === email.ordinal)}
              shown={current} onEdit={() => begin(email.ordinal)} />;
      })}
      {draft && (
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, position: 'sticky', bottom: 'calc(12px + env(safe-area-inset-bottom, 0px))', bgcolor: 'background.paper', boxShadow: 3 }}>
          <Stack spacing={1.25}>
            {outOfDate && <Alert severity="warning">These emails were changed somewhere else since you started. Discard your changes to see the latest wording, then edit again.</Alert>}
            {issues.map(i => (
              <Alert key={i.ordinal} severity="warning" action={<Button color="inherit" size="small" onClick={() => setOpen(i.ordinal)}>Fix</Button>}>
                Email {i.ordinal + 1} {i.kind === 'placeholder' ? `still says “${i.text}”` : i.kind === 'curly' ? "has curly brackets { }, which can't be sent" : i.text}.
              </Alert>
            ))}
            {error && <Alert severity="error">{error}</Alert>}
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between" alignItems={{ sm: 'center' }}>
              <Typography variant="body2">
                {changed(draft) ? `${draft.emails.filter(e => changed(draft, e.ordinal)).length} of 3 emails changed, not saved yet.` : 'No changes yet.'}
                {' '}People already waiting get the new wording from their next email. Emails already sent don't change.
              </Typography>
              <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
                <Button onClick={discard} disabled={busy}>Discard changes</Button>
                <Button variant="contained" onClick={save} disabled={busy || outOfDate || issues.length > 0 || !changed(draft)}>
                  {busy ? <CircularProgress size={18} color="inherit" /> : 'Save and use from now on'}
                </Button>
              </Stack>
            </Stack>
          </Stack>
        </Paper>
      )}
      <Stack direction="row" justifyContent="flex-end">
        <Button onClick={onSettings}>Campaign settings: name, sender, daily limit, automatic sending</Button>
      </Stack>
    </Stack>
  );
}

function EmailCard({ email, owner, busy, pending, problem, shown, onEdit }: { email: CampaignEmail; owner: boolean; busy: boolean; pending: boolean; problem?: Problem; shown?: DraftEmail; onEdit: () => void }) {
  const current = email.results.find(r => r.current);
  const earlier = email.results.filter(r => !r.current);
  const subject = shown?.subject ?? email.subject, body = shown?.body ?? email.body;
  const preview = body.split('\n').map(l => l.trim()).filter(Boolean).slice(0, 2).join(' ');
  const flag = problem ? (problem.kind === 'placeholder' ? `Says “${problem.text}”` : problem.kind === 'curly' ? 'Has { }' : 'Incomplete')
    : (!shown && email.placeholder ? `Says “${email.placeholder}”` : null);
  return (
    <Paper variant="outlined" component="article" aria-label={`Email ${email.ordinal + 1}`} sx={{ p: { xs: 2, sm: 2.5 }, borderRadius: 4, borderColor: pending ? 'primary.main' : 'divider' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ sm: 'center' }}>
        <Stack spacing={0.75} sx={{ minWidth: 0 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip size="small" color="primary" label={`Email ${email.ordinal + 1}`} />
            <Typography variant="body2">{WHEN[email.ordinal]}</Typography>
            {pending && <Chip size="small" color="primary" variant="outlined" label="Changed, not saved yet" />}
            {flag && <Chip size="small" color="warning" variant="outlined" label={flag} />}
          </Stack>
          <Typography sx={{ fontWeight: 700, color: 'text.primary' }}>{subject}</Typography>
          <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{preview}</Typography>
          <Typography variant="body2" sx={{ color: 'text.primary', fontWeight: 600 }}>
            {current ? resultsLine(current) : 'Not sent with this wording yet'}
          </Typography>
          {earlier.map(r => (
            <Typography key={r.wording} variant="body2">Earlier wording{r.since ? ` (from ${day(r.since)})` : ''}: {resultsLine(r)}</Typography>
          ))}
        </Stack>
        {owner && <Button variant="outlined" onClick={onEdit} disabled={busy} sx={{ flexShrink: 0 }}>Edit</Button>}
      </Stack>
    </Paper>
  );
}

function EmailEditor({ campaignId, draft, email, value, busy, onChange, onDone }: { campaignId: string; draft: Draft; email: CampaignEmail; value: DraftEmail; busy: boolean; onChange: (change: { subject?: string; body?: string }) => void; onDone: () => void }) {
  const mobile = useShellMobile();
  const [asking, setAsking] = useState(false), [notes, setNotes] = useState(''), [thinking, setThinking] = useState(false);
  const [suggestion, setSuggestion] = useState<{ subject: string; body: string } | null>(null), [error, setError] = useState('');
  const problem = problems(draft).find(p => p.ordinal === email.ordinal);

  async function askAria() {
    setThinking(true); setError(''); setSuggestion(null);
    try {
      const current = draft.emails.map(e => ({ subject: e.subject, body: e.body }));
      const out = await (await apiRequest('POST', `/v1/outreach/setup/campaigns/${campaignId}/redraft`,
        { notes: `Only improve email ${email.ordinal + 1}; keep the others as they are. ${notes}`.trim(), current })).json();
      setSuggestion(out.emails?.[email.ordinal] || null);
    } catch (e) { setError(outreachError(e)); } finally { setThinking(false); }
  }

  return (
    <Paper variant="outlined" component="article" aria-label={`Email ${email.ordinal + 1}, being edited`} sx={{ p: { xs: 2, sm: 3 }, borderRadius: 4, borderWidth: 2, borderColor: 'primary.main' }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} alignItems="center"><Chip size="small" color="primary" label={`Email ${email.ordinal + 1}`} /><Typography variant="body2">{WHEN[email.ordinal]}</Typography></Stack>
        <TextField label="Subject" value={value.subject} onChange={e => onChange({ subject: e.target.value })} disabled={busy} fullWidth />
        <TextField label="Message" value={value.body} onChange={e => onChange({ body: e.target.value })} disabled={busy} fullWidth multiline minRows={8}
          helperText="Write it exactly as it should arrive. Your name and sign-off are added at the bottom for you." />
        {problem?.kind === 'placeholder' && <Alert severity="warning">“{problem.text}” needs replacing with the real words. If it's your name or sign-off, just delete it.</Alert>}
        {problem?.kind === 'curly' && <Alert severity="warning">Emails are sent exactly as written, so curly brackets {'{ }'} can't be used. Write the words out instead.</Alert>}
        {error && <Alert severity="error">{error}</Alert>}
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent="flex-end">
          <Button variant="outlined" onClick={() => setAsking(true)} disabled={busy}>Ask Aria to improve it</Button>
          <Button variant="contained" onClick={onDone} disabled={busy}>Done with this email</Button>
        </Stack>
      </Stack>
      <Dialog open={asking} onClose={() => !thinking && setAsking(false)} fullScreen={mobile} fullWidth maxWidth="sm">
        <DialogTitle>Ask Aria to improve email {email.ordinal + 1}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2">Tell Aria what you'd like: shorter, warmer, more direct, something to mention. Nothing is saved until you use her version and press Save.</Typography>
            <TextField multiline minRows={2} value={notes} onChange={e => setNotes(e.target.value)} disabled={thinking}
              placeholder="e.g. Make it shorter and mention our free trial week." />
            {thinking && <Stack direction="row" spacing={1} alignItems="center"><CircularProgress size={18} /><Typography variant="body2">Aria is rewriting it…</Typography></Stack>}
            {suggestion && (
              <Paper variant="outlined" sx={{ p: 2, bgcolor: 'action.hover' }}>
                <Typography sx={{ fontWeight: 700, color: 'text.primary' }}>{suggestion.subject}</Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 1, color: 'text.primary' }}>{suggestion.body}</Typography>
              </Paper>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAsking(false)} disabled={thinking}>Close</Button>
          <Button variant="outlined" onClick={askAria} disabled={thinking}>{suggestion ? 'Try again' : 'Ask Aria'}</Button>
          {suggestion && <Button variant="contained" onClick={() => { onChange({ subject: suggestion.subject, body: suggestion.body }); setAsking(false); setSuggestion(null); }}>Use this version</Button>}
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
