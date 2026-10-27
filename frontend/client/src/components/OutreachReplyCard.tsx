import { useState } from 'react';
import { Alert, Button, Paper, Stack, Typography } from '@mui/material';
import { apiRequest } from '@/lib/queryClient';
import { OutreachRecord, outreachError, useOutreachData, useOutreachOwner, useRefreshOutreach } from '@/hooks/useOutreachData';
export default function OutreachReplyCard({ businessId, reply }: { businessId: string; reply: OutreachRecord }) {
  const detail = useOutreachData(businessId, `replies/${reply.id}`);
  const owner = useOutreachOwner(businessId);
  const refresh = useRefreshOutreach(businessId);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [brief, setBrief] = useState<OutreachRecord | null>(null), [copied, setCopied] = useState('');
  async function showBrief() {
    setBusy(true); setError('');
    try { setBrief(await (await apiRequest('GET', `/v1/outreach/replies/${reply.id}/brief`)).json()); }
    catch (e) { setError(outreachError(e)); } finally { setBusy(false); }
  }
  async function copy(label: string, text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(label); window.setTimeout(() => setCopied(''), 2000); } catch { /* copy by hand */ }
  }
  const briefText = brief ? [
    `From: ${[brief.who?.name, brief.who?.role, brief.who?.company].filter(Boolean).join(', ')} <${brief.who?.email || ''}>`,
    `They asked: ${brief.asked?.text || ''}`,
    brief.suggested_answer ? `Suggested answer: ${brief.suggested_answer}` : '',
    ...(brief.facts || []).map((f: OutreachRecord) => `Fact — ${f.topic}: ${f.answer}${f.source ? ` (source: ${f.source})` : ''}`),
  ].filter(Boolean).join('\n\n') : '';
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
    {brief && <Paper variant="outlined" sx={{ p: 1.5, bgcolor: 'action.hover' }}><Stack spacing={1}>
      <Typography variant="subtitle2">Aria's briefing — to answer from your own email</Typography>
      {brief.retained === false && <Alert severity="info">This contact has passed its retention date, so their details and message are withheld from this briefing.</Alert>}
      <Typography variant="body2"><strong>Who:</strong> {[brief.who?.name, brief.who?.role, brief.who?.company].filter(Boolean).join(', ') || 'Unknown'} · {brief.who?.email}</Typography>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}><strong>They asked:</strong> {brief.asked?.text || 'Message unavailable'}</Typography>
      {brief.suggested_answer
        ? <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}><strong>Suggested answer:</strong> {brief.suggested_answer}</Typography>
        : <Typography variant="body2">{brief.no_suggestion_reason || "Aria hasn't suggested an answer for this reply."}</Typography>}
      {(brief.facts || []).length > 0 && <Typography variant="body2" component="div"><strong>Facts you've approved:</strong>
        <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>{brief.facts.map((f: OutreachRecord) => <li key={f.topic}>{f.topic}: {f.answer}{f.source ? <> <Typography component="span" variant="caption" color="text.secondary">(source: {f.source})</Typography></> : null}</li>)}</ul></Typography>}
      <Typography variant="caption">{brief.how}</Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        {brief.suggested_answer && <Button size="small" variant="outlined" onClick={() => copy('answer', brief.suggested_answer)}>{copied === 'answer' ? 'Copied ✓' : 'Copy the answer'}</Button>}
        <Button size="small" variant="outlined" onClick={() => copy('all', briefText)}>{copied === 'all' ? 'Copied ✓' : 'Copy the briefing'}</Button>
      </Stack>
    </Stack></Paper>}
    {error && <Alert severity="error">{error}</Alert>}
    {reply.resolution !== 'resolved' && reply.resolution !== 'dismissed' && <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
      <Button sx={{ minHeight: 44 }} disabled={!owner.data || busy} onClick={showBrief}>Aria's briefing</Button>
      <Button sx={{ minHeight: 44 }} disabled={!owner.data || busy} onClick={() => act('handover')}>I'll handle this</Button>
      <Button sx={{ minHeight: 44 }} disabled={!owner.data || busy} onClick={() => act('resolve')}>Mark handled</Button>
    </Stack>}
  </Stack></Paper>;
}
