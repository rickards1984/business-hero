import { Alert, AlertTitle, Button, Stack, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { OutreachRecord, useOutreachData } from '@/hooks/useOutreachData';

// OUT-19 E (Mike's decision 2): replies never wait on the cold-email limits,
// but each inbox has a daily safety ceiling. When replies get close to it,
// the owner gets three choices, in a click or two.
export default function ReplyCeilingBanner({ businessId }: { businessId: string }) {
  const q = useOutreachData(businessId, 'inboxes/headroom');
  const navigate = useNavigate();
  const near: OutreachRecord[] = (q.data as OutreachRecord | undefined)?.near_ceiling || [];
  if (!near.length) return null;
  return <Alert severity="warning" sx={{ overflowWrap: 'anywhere' }}>
    <AlertTitle>Replies are close to today's limit</AlertTitle>
    {near.map(b => <Typography key={b.mailbox_id} variant="body2">
      {b.email || 'An outreach inbox'} can send {b.left} more email{b.left === 1 ? '' : 's'} today
      {b.pending_replies ? ` · ${b.pending_replies} repl${b.pending_replies === 1 ? 'y' : 'ies'} waiting` : ''}.
    </Typography>)}
    <Typography variant="body2" sx={{ mt: 1 }}>Replies are never held back by the cold-email limits, but each inbox can only send so many emails a day. Choose how to handle the rest:</Typography>
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1, '& .MuiButton-root': { minHeight: 44 } }}>
      <Button variant="contained" onClick={() => navigate('/app/outreach/replies')}>I'll reply myself</Button>
      <Button variant="outlined" onClick={() => navigate('/app/outreach')}>Add a second inbox</Button>
      <Button variant="outlined" disabled>Boost this inbox (coming later)</Button>
    </Stack>
    <Typography variant="caption" component="p" sx={{ mt: 1 }}>
      "I'll reply myself": each reply shows Aria's briefing — who wrote, what they asked, her suggested answer and the facts behind it — to send from your own email.
      A second inbox needs warming up before it sends. Boosting an inbox isn't available yet.
    </Typography>
  </Alert>;
}
