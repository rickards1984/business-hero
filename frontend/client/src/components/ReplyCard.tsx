import { useState } from 'react';
import { Alert, Box, Button, Paper, Stack, Typography } from '@mui/material';
import { apiRequest } from '@/lib/queryClient';

/**
 * AUTO-2 — a customer replied to a chase. Aria has paused automatic chasing
 * of that customer until the owner decides. "Stop chasing" ends automatic
 * chasing of the invoice(s) the reply is about; it never marks anything paid
 * (record the payment in your accounts software, or with Mark as paid).
 */

export interface ChaseReply {
  id: string;
  customer_email: string;
  invoice_ids: string[];
  invoice_numbers: string[];
  category: 'paid' | 'promise' | 'dispute' | 'question' | 'other' | 'unknown';
  summary: string | null;
  status: string;
  created_at: string | null;
}

const SAYS: Record<ChaseReply['category'], string> = {
  paid: 'says they have paid',
  promise: 'promises to pay',
  dispute: 'disputes it',
  question: 'has a question',
  other: 'replied',
  unknown: "replied (I couldn't read it)",
};

function about(r: ChaseReply) {
  const n = r.invoice_numbers;
  return n.length === 0 ? 'your invoice' : n.length === 1 ? n[0] : `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}`;
}

export default function ReplyCard({ reply, onChanged }: { reply: ChaseReply; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: 'resume' | 'stop') => {
    setBusy(true);
    setError(null);
    try {
      await apiRequest('POST', `/v1/automations/replies/${reply.id}/resolve`, { decision });
      setDone(decision === 'stop'
        ? `I won't chase ${about(reply)} again. Record the payment in your accounts when it arrives.`
        : 'Chasing resumes under your usual rules.');
      onChanged();
    } catch {
      setError('That could not be saved. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, maxWidth: 560, alignSelf: 'flex-start', width: '100%' }}>
      <Stack spacing={1.25}>
        <Typography variant="caption" sx={{ fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase', color: '#B4232C' }}>
          Reply to a chase · chasing paused
        </Typography>
        <Typography variant="body1">
          <strong>{reply.customer_email}</strong> {SAYS[reply.category] ?? 'replied'} about {about(reply)}.
        </Typography>
        {reply.summary && (
          <Box sx={{ bgcolor: 'action.hover', borderRadius: 2, p: 1.5 }}>
            <Typography variant="body2">{reply.summary}</Typography>
          </Box>
        )}
        <Typography variant="body2" color="text.secondary">
          I've paused chasing them until you decide. Their email is in your inbox.
        </Typography>
        {error && <Alert severity="error">{error}</Alert>}
        {done ? (
          <Alert severity="success">{done}</Alert>
        ) : (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button variant="contained" disabled={busy} onClick={() => decide('stop')}>
              Stop chasing {reply.invoice_numbers.length > 1 ? 'these invoices' : 'this invoice'}
            </Button>
            <Button variant="outlined" disabled={busy} onClick={() => decide('resume')}>Resume chasing</Button>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
