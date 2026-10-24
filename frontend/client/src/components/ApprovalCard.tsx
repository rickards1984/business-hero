import { useEffect, useState } from 'react';
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import { useMe } from '@/hooks/useMe';
import { useOutreachOwner } from '@/hooks/useOutreachData';
import OutreachReplyCard from '@/components/OutreachReplyCard';
import { apiRequest } from '@/lib/queryClient';

/**
 * NS-B10 — one of Aria's drafts, awaiting the owner's tap.
 *
 * The card shows exactly what the server stored; Approve sends exactly that,
 * once (services/aria_actions.py). Nothing here decides what is sent: the
 * preview comes from the server and every action goes back to it. Built to
 * be reused on the Aria home (NS-B7).
 */

export interface Proposal {
  id: string;
  action_type: 'send_email' | 'send_invoice_chase' | 'create_calendar_event' | 'create_task' | 'send_outreach' | 'reply_outreach';
  status: string;
  preview: Record<string, any>;
  version: string;
  expires_at: string;
  error?: string | null;
}

const KIND: Record<Proposal['action_type'], { label: string; colour: string; approve: string; done: string }> = {
  send_outreach: { label: 'Outreach email', colour: '#1F5FBF', approve: 'Approve and send', done: 'Provider accepted (delivery not confirmed)' },
  reply_outreach: { label: 'Outreach reply', colour: '#1F5FBF', approve: 'Approve and send reply', done: 'Provider accepted (delivery not confirmed)' },
  send_email: { label: 'Email', colour: '#1F5FBF', approve: 'Approve and send', done: 'Sent from your mailbox' },
  send_invoice_chase: { label: 'Invoice chase', colour: '#B4232C', approve: 'Approve and send', done: 'Chase sent from your mailbox' },
  create_calendar_event: { label: 'Booking', colour: '#11734B', approve: 'Approve booking', done: 'Booked' },
  create_task: { label: 'Task', colour: '#8A5300', approve: 'Add task', done: 'Task added' },
};

const EDITABLE: Record<Proposal['action_type'], string[]> = {
  send_outreach: [], reply_outreach: [],
  send_email: ['to', 'subject', 'body'],
  send_invoice_chase: ['subject', 'body'],
  create_calendar_event: ['title', 'date', 'start_time', 'duration_minutes'],
  create_task: ['title', 'description', 'due_at'],
};

const FIELD_LABEL: Record<string, string> = {
  to: 'To', subject: 'Subject', body: 'Message', title: 'Title', date: 'Date (YYYY-MM-DD)',
  start_time: 'Start (HH:MM)', duration_minutes: 'Minutes', description: 'Notes', due_at: 'Due (YYYY-MM-DD)',
};

function detail(err: unknown, fallback: string): string {
  const raw = (err instanceof Error ? err.message : '').replace(/^\d{3}:\s*/, '');
  try {
    const d = JSON.parse(raw).detail;
    if (typeof d === 'string') return d;
  } catch {
    // not JSON
  }
  return fallback;
}

function whenText(p: Record<string, any>): string {
  if (!p.start) return '';
  const start = new Date(p.start);
  return start.toLocaleString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', hour: 'numeric', minute: '2-digit',
    timeZone: p.timezone || 'Europe/London',
  });
}

export default function ApprovalCard({ proposal, onChanged }: { proposal: Proposal; onChanged?: (card: Proposal) => void }) {
  const { data: me } = useMe();
  const owner = useOutreachOwner(me?.id);
  const [card, setCard] = useState<Proposal>(proposal);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, any>>({});
  useEffect(() => { setCard(proposal); }, [proposal]);
  const outreach = card.action_type === 'send_outreach' || card.action_type === 'reply_outreach';
  const kind = KIND[card.action_type];
  const p = card.preview || {};
  const expired = new Date(card.expires_at).getTime() <= Date.now();
  const open = card.status === 'proposed' && !expired;

  // The server is the authority. After a conflict or a lost reply, re-read
  // the card rather than keep showing a live Approve button (Codex review 1).
  const reconcile = async () => {
    try {
      const r = await apiRequest('GET', `/v1/aria/actions/${card.id}`);
      const fresh: Proposal = await r.json();
      setCard(fresh);
      onChanged?.(fresh);
    } catch {
      // The authoritative state is unknown: switch the controls off rather
      // than fall back to a stale `proposed` (Codex review 2, finding 2).
      setUncertain(true);
    }
  };

  const act = async (method: 'POST' | 'PATCH', path: string, body?: unknown) => {
    setBusy(true);
    setMessage('');
    try {
      const r = await apiRequest(method, `/v1/aria/actions/${card.id}${path}`, body);
      const updated: Proposal = await r.json();
      setCard(updated);
      setEditing(false);
      onChanged?.(updated);  // the card's NEW state, e.g. for the home's draft count
    } catch (err) {
      const status = err instanceof Error ? Number((err.message.match(/^(\d{3}):/) || [])[1]) : NaN;
      const definite = status >= 400 && status < 500;
      if (!definite) {
        // No answer, or a server error: it may or may not have happened.
        // Never invite a second tap; show what the server now says.
        setUncertain(true);
        setEditing(false);
      } else {
        setMessage(detail(err, 'That did not work. Please try again.'));
      }
      await reconcile();
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    setDraft(Object.fromEntries(EDITABLE[card.action_type].map((k) => [k, p[k] ?? ''])));
    setEditing(true);
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, maxWidth: 560, alignSelf: 'flex-start', width: '100%', overflowWrap: 'anywhere' }}>
      <Stack spacing={1.25}>
        <Typography variant="caption" sx={{ fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase', color: kind.colour }}>
          {kind.label} · needs your approval
        </Typography>

        {editing ? (
          <Stack spacing={1}>
            {EDITABLE[card.action_type].map((k) => (
              <TextField key={k} size="small" label={FIELD_LABEL[k] || k} value={draft[k] ?? ''}
                multiline={k === 'body' || k === 'description'} minRows={k === 'body' ? 5 : 1}
                onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
            ))}
            {p.sign_off && (
              <Typography variant="body2" sx={{ whiteSpace: 'pre-line', color: 'text.secondary' }}>{p.sign_off}</Typography>
            )}
          </Stack>
        ) : (
          <Box>
            {(card.action_type === 'send_email' || card.action_type === 'send_invoice_chase') && (
              <>
                <Typography variant="body2"><strong>To:</strong> {p.to}</Typography>
                <Typography variant="body2" sx={{ mb: 1 }}><strong>Subject:</strong> {p.subject}</Typography>
                <Box sx={{ bgcolor: 'action.hover', borderRadius: 2, p: 1.5 }}>
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>{p.body}</Typography>
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-line', mt: 1.5, color: 'text.secondary' }}>{p.sign_off}</Typography>
                </Box>
              </>
            )}
            {outreach && <Stack spacing={1}>
              <Typography>From: {p.from_email} · Mailbox: {p.mailbox_id} · {p.provider}</Typography>
              <Typography>To: {p.to}</Typography><Typography>CC: {Array.isArray(p.cc) && p.cc.length ? p.cc.join(', ') : 'Off'}</Typography>
              <Typography>Subject: {p.subject}</Typography>
              <Typography sx={{ whiteSpace: 'pre-wrap' }}>{p.body}</Typography>
              <Typography sx={{ whiteSpace: 'pre-wrap' }}>{p.sign_off}</Typography>
              <Typography sx={{ whiteSpace: 'pre-wrap' }}>{p.footer}</Typography>
              <Typography variant="caption">Campaign {p.campaign_id} · campaign v{p.campaign_version} · sequence v{p.sequence_version} · step {p.ordinal} · template {p.template_hash}</Typography>
              <Typography variant="caption">Window: {p.sending_window} · Expires: {card.expires_at}</Typography>
              {card.action_type === 'reply_outreach' && <>
                {me?.id && p.reply_id && <OutreachReplyCard businessId={me.id} reply={{ id: p.reply_id, mailbox_id: p.mailbox_id, resolution: 'resolved' }} />}
                {(p.knowledge || []).map((fact: Record<string, any>) => <Box key={fact.id}>
                  <Typography>{fact.topic} · version {fact.version} · review due {fact.review_due_at}</Typography>
                  <Typography sx={{ whiteSpace: 'pre-wrap' }}>{fact.answer}</Typography><Typography>Source: {fact.source_reference}</Typography>
                </Box>)}
              </>}
            </Stack>}
            {card.action_type === 'create_calendar_event'  && (
              <>
                <Typography variant="subtitle2">{p.title}</Typography>
                <Typography variant="body2">{whenText(p)} · {p.duration_minutes} minutes</Typography>
                <Typography variant="body2" color="text.secondary">
                  Calendar: {p.calendar_id === 'primary' ? 'main calendar' : p.calendar_id}
                </Typography>
                {p.attendee_email && (
                  <Typography variant="body2">Google will email an invitation to <strong>{p.attendee_email}</strong>.</Typography>
                )}
                {p.description && (
                  <Box sx={{ bgcolor: 'action.hover', borderRadius: 2, p: 1.5, mt: 1 }}>
                    <Typography variant="caption" color="text.secondary">
                      {p.attendee_email ? 'Included in the invitation' : 'Event notes'}
                    </Typography>
                    <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>{p.description}</Typography>
                  </Box>
                )}
              </>
            )}
            {card.action_type === 'create_task' && (
              <>
                <Typography variant="subtitle2">{p.title}</Typography>
                {p.description && <Typography variant="body2">{p.description}</Typography>}
                {p.due_at && <Typography variant="body2" color="text.secondary">Due {p.due_at}</Typography>}
              </>
            )}
          </Box>
        )}

        {message && <Alert severity="warning">{message}</Alert>}
        {uncertain && (
          <Alert severity="warning">
            We couldn't confirm the outcome. Refresh to load the authoritative state. Do not prepare or send a replacement while the outcome is unknown.
          </Alert>
        )}

        {open && !uncertain && (!outreach || owner.data) && (
          editing ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" disabled={busy} onClick={() => act('PATCH', '', draft)}>Save changes</Button>
              <Button disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
            </Stack>
          ) : (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" disabled={busy}
                onClick={() => act('POST', '/approve', { version: card.version })}>{kind.approve}</Button>
              <Button variant="outlined" disabled={busy} onClick={startEdit} sx={{ display: outreach ? 'none' : undefined }}>Edit</Button>
              <Button disabled={busy} onClick={() => act('POST', '/dismiss')}>Not now</Button>
            </Stack>
          )
        )}

        {card.status === 'done' && (
          <Typography variant="body2" sx={{ color: 'success.main', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <CheckIcon fontSize="small" /> {kind.done}
          </Typography>
        )}
        {card.status === 'failed' && (
          <Alert severity="error">Not done: {card.error || 'it failed'}. Nothing will be retried automatically.</Alert>
        )}
        {card.status === 'executing' && !uncertain && (
          <Alert severity="warning">
            Outcome unknown. No retry is available; await authoritative reconciliation.
          </Alert>
        )}
        {card.status === 'dismissed' && <Typography variant="body2" color="text.secondary">Dismissed.</Typography>}
        {(card.status === 'expired' || (card.status === 'proposed' && expired)) && (
          <Typography variant="body2" color="text.secondary">Expired. Ask Aria again.</Typography>
        )}
      </Stack>
    </Paper>
  );
}
