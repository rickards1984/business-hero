import { useState } from 'react';
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
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
  action_type: 'send_email' | 'send_invoice_chase' | 'create_calendar_event' | 'create_task';
  status: string;
  preview: Record<string, any>;
  expires_at: string;
  error?: string | null;
}

const KIND: Record<Proposal['action_type'], { label: string; colour: string; approve: string; done: string }> = {
  send_email: { label: 'Email', colour: '#1F5FBF', approve: 'Approve and send', done: 'Sent from your mailbox' },
  send_invoice_chase: { label: 'Invoice chase', colour: '#B4232C', approve: 'Approve and send', done: 'Chase sent from your mailbox' },
  create_calendar_event: { label: 'Booking', colour: '#11734B', approve: 'Approve booking', done: 'Booked' },
  create_task: { label: 'Task', colour: '#8A5300', approve: 'Add task', done: 'Task added' },
};

const EDITABLE: Record<Proposal['action_type'], string[]> = {
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

export default function ApprovalCard({ proposal }: { proposal: Proposal }) {
  const [card, setCard] = useState<Proposal>(proposal);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, any>>({});
  const kind = KIND[card.action_type];
  const p = card.preview || {};
  const open = card.status === 'proposed';

  const act = async (method: 'POST' | 'PATCH', path: string, body?: unknown) => {
    setBusy(true);
    setMessage('');
    try {
      const r = await apiRequest(method, `/v1/aria/actions/${card.id}${path}`, body);
      setCard(await r.json());
      setEditing(false);
    } catch (err) {
      const status = err instanceof Error ? Number((err.message.match(/^(\d{3}):/) || [])[1]) : NaN;
      if (path === '/approve' && !(status >= 400 && status < 500)) {
        // No answer, or a server error: it may or may not have gone. Never invite a second tap.
        setUncertain(true);
      } else {
        setMessage(detail(err, 'That did not work. Please try again.'));
      }
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    setDraft(Object.fromEntries(EDITABLE[card.action_type].map((k) => [k, p[k] ?? ''])));
    setEditing(true);
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, maxWidth: 560, alignSelf: 'flex-start', width: '100%' }}>
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
            {card.action_type === 'create_calendar_event' && (
              <>
                <Typography variant="subtitle2">{p.title}</Typography>
                <Typography variant="body2">{whenText(p)} · {p.duration_minutes} minutes</Typography>
                <Typography variant="body2" color="text.secondary">
                  Calendar: {p.calendar_id === 'primary' ? 'main calendar' : p.calendar_id}
                  {p.attendee_email ? ` · invitation to ${p.attendee_email}` : ''}
                </Typography>
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
            We couldn't confirm whether this went through. Check your Sent folder or calendar before asking Aria again.
          </Alert>
        )}

        {open && !uncertain && (
          editing ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" disabled={busy} onClick={() => act('PATCH', '', draft)}>Save changes</Button>
              <Button disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
            </Stack>
          ) : (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" disabled={busy} onClick={() => act('POST', '/approve')}>{kind.approve}</Button>
              <Button variant="outlined" disabled={busy} onClick={startEdit}>Edit</Button>
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
        {card.status === 'executing' && (
          <Alert severity="warning">
            We can't confirm this finished. Check your Sent folder or calendar before trying again.
          </Alert>
        )}
        {card.status === 'dismissed' && <Typography variant="body2" color="text.secondary">Dismissed.</Typography>}
        {card.status === 'expired' && <Typography variant="body2" color="text.secondary">Expired. Ask Aria again.</Typography>}
      </Stack>
    </Paper>
  );
}
