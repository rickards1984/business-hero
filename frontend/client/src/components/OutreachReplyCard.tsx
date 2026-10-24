import { useState } from 'react';
import { Alert, Button, Paper, Stack, Typography } from '@mui/material';
import { apiRequest } from '@/lib/queryClient';
import { OutreachRecord, outreachError, useOutreachData, useOutreachOwner, useRefreshOutreach } from '@/hooks/useOutreachData';
export default function OutreachReplyCard({ businessId, reply }: { businessId: string; reply: OutreachRecord }) {
  const detail = useOutreachData(businessId, `replies/${reply.id}`);
  const owner = useOutreachOwner(businessId);
  const refresh = useRefreshOutreach(businessId);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const item = detail.data?.item;
  const original = item?.original_status === 'available' || item?.body_text != null ? item : null;
  async function act(action: string) {
    setBusy(true); setError('');
    try { await apiRequest('POST', `/v1/outreach/replies/${reply.id}/${action}`, {}); refresh(); }
    catch (e) { setError(outreachError(e)); } finally { setBusy(false); }
  }
  return <Paper variant="outlined" sx={{ p: 2, overflowWrap: 'anywhere' }}><Stack spacing={1}>
    <Typography variant="subtitle1">Outreach reply · {reply.category || 'Unknown classification'}</Typography>
    <Typography variant="body2">Confidence: {reply.confidence ?? 'unknown'} · {reply.resolution} · Received {reply.received_at}</Typography>
    <Typography variant="body2">Mailbox: {reply.mailbox_id} · Assigned owner: {reply.owner_id || 'Unassigned'}</Typography>
    <Typography variant="body2">Handling this reply does not restart a sequence or release an answer slot.</Typography>
    {item?.enrolments?.map((e: OutreachRecord) => <Typography key={e.id} variant="body2">Campaign {e.campaign_id}: {e.state} · {e.stop_reason || 'No stored stop reason'}{e.takeover_at ? ` · Taken over ${e.takeover_at}` : ''}</Typography>)}
    {detail.isLoading ? <Typography>Loading original message…</Typography> : detail.isError ? <Alert severity="warning">Original message unavailable.</Alert> : original ? <>
      <Typography>From: {original.from_email || 'Unavailable'}</Typography><Typography>{original.subject || 'No stored subject'}</Typography>
      <Typography sx={{ whiteSpace: 'pre-wrap' }}>{original.body_text ?? 'Original content unavailable.'}</Typography>
    </> : <Alert severity="info">Original content unavailable.</Alert>}
    {error && <Alert severity="error">{error}</Alert>}
    {reply.resolution !== 'resolved' && reply.resolution !== 'dismissed' && <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
      <Button sx={{ minHeight: 44 }} disabled={!owner.data || busy} onClick={() => act('handover')}>I'll handle this</Button>
      <Button sx={{ minHeight: 44 }} disabled={!owner.data || busy} onClick={() => act('resolve')}>Mark handled</Button>
    </Stack>}
  </Stack></Paper>;
}
