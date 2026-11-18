import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack,
  TextField, Typography,
} from '@mui/material';
import { apiRequest } from '@/lib/queryClient';
import { outreachError, useOutreachData, useRefreshOutreach } from '@/hooks/useOutreachData';
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
// A first warning while typing. The server's check is the one that counts.
const PLACEHOLDER = /\[[^\]\n]{1,40}\]|\{\{?[^}\n]{0,40}\}\}?|<[A-Z][A-Z _]{1,30}>/;
const CURLY = /[{}]/;

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
  const [editing, setEditing] = useState<number | null>(null);
  const [notice, setNotice] = useState('');
  if (q.isLoading) return <Typography>Loading the emails…</Typography>;
  if (q.isError || !data) return <Alert severity="warning">{outreachError(q.error)} <Button onClick={() => q.refetch()}>Try again</Button></Alert>;
  const fixes = data.emails.filter(e => e.placeholder);
  return (
    <Stack spacing={1.75}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between" alignItems={{ sm: 'baseline' }}>
        <Typography variant="h2">Your 3 emails</Typography>
        <Typography variant="body2">Change any of them whenever you like. Each one stops if the person replies.</Typography>
      </Stack>
      {fixes.length > 0 && (
        <Alert severity="warning">
          {fixes.length === 1 ? `Email ${fixes[0].ordinal + 1} still says` : `${fixes.length} emails still say`} “{fixes[0].placeholder}”.
          Nothing is sent from this campaign until it's replaced. Open the email, delete it (your name and sign-off are added for you), then save.
        </Alert>
      )}
      {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
      {data.emails.map(email => editing === email.ordinal
        ? <EmailEditor key={email.ordinal} businessId={businessId} campaign={data} email={email}
            onCancel={() => setEditing(null)} onSaved={(message) => { setEditing(null); setNotice(message); }} />
        : <EmailCard key={email.ordinal} email={email} owner={owner} busy={editing !== null} onEdit={() => { setNotice(''); setEditing(email.ordinal); }} />)}
      <Stack direction="row" justifyContent="flex-end">
        <Button onClick={onSettings}>Campaign settings: name, sender, daily limit, automatic sending</Button>
      </Stack>
    </Stack>
  );
}

function EmailCard({ email, owner, busy, onEdit }: { email: CampaignEmail; owner: boolean; busy: boolean; onEdit: () => void }) {
  const current = email.results.find(r => r.current);
  const earlier = email.results.filter(r => !r.current);
  const preview = email.body.split('\n').map(l => l.trim()).filter(Boolean).slice(0, 2).join(' ');
  return (
    <Paper variant="outlined" component="article" aria-label={`Email ${email.ordinal + 1}`} sx={{ p: { xs: 2, sm: 2.5 }, borderRadius: 4 }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ sm: 'center' }}>
        <Stack spacing={0.75} sx={{ minWidth: 0 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip size="small" color="primary" label={`Email ${email.ordinal + 1}`} />
            <Typography variant="body2">{WHEN[email.ordinal]}</Typography>
            {email.placeholder && <Chip size="small" color="warning" variant="outlined" label={`Says “${email.placeholder}”`} />}
          </Stack>
          <Typography sx={{ fontWeight: 700, color: 'text.primary' }}>{email.subject}</Typography>
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

function EmailEditor({ businessId, campaign, email, onCancel, onSaved }: { businessId: string; campaign: CampaignEmails; email: CampaignEmail; onCancel: () => void; onSaved: (message: string) => void }) {
  const refresh = useRefreshOutreach(businessId);
  const client = useQueryClient();
  const mobile = useShellMobile();
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [asking, setAsking] = useState(false), [notes, setNotes] = useState(''), [thinking, setThinking] = useState(false);
  const [suggestion, setSuggestion] = useState<{ subject: string; body: string } | null>(null);
  const found = (subject + '\n' + body).match(PLACEHOLDER)?.[0];
  const curly = CURLY.test(subject + body) && !found;
  const blank = !subject.trim() || !body.trim();
  const unchanged = subject === email.subject && body === email.body;
  const others = campaign.emails.map(e => e.ordinal === email.ordinal ? { ordinal: e.ordinal, subject, body } : { ordinal: e.ordinal, subject: e.subject, body: e.body });

  async function save() {
    setBusy(true); setError('');
    try {
      const out = await (await apiRequest('POST', `/v1/outreach/campaigns/${campaign.id}/emails`, { version: campaign.version, emails: others })).json();
      refresh();
      client.invalidateQueries({ queryKey: ['outreach-dashboard', businessId] });
      const people = out.moved === 1 ? '1 person' : `${out.moved} people`;
      onSaved(
        (out.moved ? `Saved. ${people} already in this campaign will get the new wording from their next email.` : 'Saved. Everyone you email from now on gets the new wording.')
        + (out.automatic === 'off' ? ' Automatic sending was switched on by someone else, so it is now off for this campaign: switch it back on in Campaign settings.' : '')
        + (out.automatic === 'on' ? ' Aria carries on sending it for you.' : ''));
    } catch (e) { setError(outreachError(e)); } finally { setBusy(false); }
  }

  async function askAria() {
    setThinking(true); setError(''); setSuggestion(null);
    try {
      const current = campaign.emails.map(e => e.ordinal === email.ordinal ? { subject, body } : { subject: e.subject, body: e.body });
      const out = await (await apiRequest('POST', `/v1/outreach/setup/campaigns/${campaign.id}/redraft`,
        { notes: `Only improve email ${email.ordinal + 1}; keep the others as they are. ${notes}`.trim(), current })).json();
      setSuggestion(out.emails?.[email.ordinal] || null);
    } catch (e) { setError(outreachError(e)); } finally { setThinking(false); }
  }

  return (
    <Paper variant="outlined" component="article" aria-label={`Email ${email.ordinal + 1}, being edited`} sx={{ p: { xs: 2, sm: 3 }, borderRadius: 4, borderWidth: 2, borderColor: 'primary.main' }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
          <Stack direction="row" spacing={1} alignItems="center"><Chip size="small" color="primary" label={`Email ${email.ordinal + 1}`} /><Typography variant="body2">{WHEN[email.ordinal]}</Typography></Stack>
        </Stack>
        <TextField label="Subject" value={subject} onChange={e => setSubject(e.target.value.replace(/\n/g, ' '))} disabled={busy} fullWidth />
        <TextField label="Message" value={body} onChange={e => setBody(e.target.value)} disabled={busy} fullWidth multiline minRows={8}
          helperText="Write it exactly as it should arrive. Your name and sign-off are added at the bottom for you." />
        {found && <Alert severity="warning">“{found}” needs replacing with the real words. If it's your name or sign-off, just delete it.</Alert>}
        {curly && <Alert severity="warning">Emails are sent exactly as written, so curly brackets {'{ }'} can't be used. Write the words out instead.</Alert>}
        {error && <Alert severity="error">{error}</Alert>}
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} justifyContent="space-between" alignItems={{ md: 'center' }}>
          <Typography variant="body2" sx={{ maxWidth: 440 }}>People already waiting get the new wording from their next email. Emails already sent don't change.</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button variant="outlined" onClick={() => setAsking(true)} disabled={busy}>Ask Aria to improve it</Button>
            <Button onClick={onCancel} disabled={busy}>Cancel</Button>
            <Button variant="contained" onClick={save} disabled={busy || blank || !!found || curly || unchanged}>
              {busy ? <CircularProgress size={18} color="inherit" /> : 'Save and use from now on'}
            </Button>
          </Stack>
        </Stack>
      </Stack>
      <Dialog open={asking} onClose={() => !thinking && setAsking(false)} fullScreen={mobile} fullWidth maxWidth="sm">
        <DialogTitle>Ask Aria to improve email {email.ordinal + 1}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2">Tell Aria what you'd like: shorter, warmer, more direct, something to mention. Nothing is saved until you choose to use her version and save it.</Typography>
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
          {suggestion && <Button variant="contained" onClick={() => { setSubject(suggestion.subject); setBody(suggestion.body); setAsking(false); setSuggestion(null); }}>Use this version</Button>}
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
