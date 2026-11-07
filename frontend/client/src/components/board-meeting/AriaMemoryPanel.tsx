/**
 * BM-4: what Aria remembers about the business.
 *
 * The owner's own notes: what payers, references, categories and patterns
 * mean, with optional groups that shape the meeting ledger. Aria suggests
 * them in meetings; nothing is used until confirmed here or on the meeting
 * card. Also the business's "large one-off income" threshold.
 */
import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  IconButton,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import CheckIcon from '@mui/icons-material/Check';
import {
  AriaMemory,
  AriaMemoryEntry,
  addAriaMemory,
  confirmAriaMemory,
  deleteAriaMemory,
  getAriaMemory,
  setOneOffFrom,
  updateAriaMemory,
} from '@/lib/executiveMeetingsApi';

type Draft = { about: string; meaning: string; group: string };
const EMPTY: Draft = { about: '', meaning: '', group: '' };

export default function AriaMemoryPanel() {
  const [memory, setMemory] = useState<AriaMemory | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Draft>(EMPTY);
  const [threshold, setThreshold] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => getAriaMemory()
    .then((m) => { setMemory(m); setThreshold(m.one_off_from ? String(m.one_off_from) : ''); })
    .catch((e) => setError((e as Error).message || 'Could not load what Aria remembers'));
  useEffect(() => { load(); }, []);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message || 'That could not be saved');
    } finally {
      setBusy(false);
    }
  };

  const entries = memory?.entries || [];
  const proposed = entries.filter((e) => e.status === 'proposed');
  const confirmed = entries.filter((e) => e.status === 'confirmed');

  const row = (e: AriaMemoryEntry) => (
    editing === e.id ? (
      <Stack key={e.id} spacing={1} sx={{ py: 1 }}>
        <TextField size="small" label="About" value={editDraft.about} inputProps={{ maxLength: 80 }}
          onChange={(ev) => setEditDraft({ ...editDraft, about: ev.target.value })} />
        <TextField size="small" label="What it means" value={editDraft.meaning} inputProps={{ maxLength: 300 }}
          multiline onChange={(ev) => setEditDraft({ ...editDraft, meaning: ev.target.value })} />
        <TextField size="small" label="Group (optional)" value={editDraft.group} inputProps={{ maxLength: 60 }}
          onChange={(ev) => setEditDraft({ ...editDraft, group: ev.target.value })} />
        <Stack direction="row" spacing={1}>
          <Button size="small" variant="contained" disabled={busy || !editDraft.about.trim() || !editDraft.meaning.trim()}
            onClick={() => run(async () => {
              await updateAriaMemory(e.id, {
                about: editDraft.about, meaning: editDraft.meaning,
                ...(editDraft.group.trim() ? { group: editDraft.group } : { clear_group: true }),
              });
              setEditing(null);
            })}>Save</Button>
          <Button size="small" onClick={() => setEditing(null)}>Cancel</Button>
        </Stack>
      </Stack>
    ) : (
      <Stack key={e.id} direction="row" spacing={1} alignItems="flex-start" sx={{ py: 1 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>{e.about}</Typography>
          <Typography variant="body2" color="text.secondary">{e.meaning}</Typography>
          {e.group && <Chip size="small" label={e.group} sx={{ mt: 0.5 }} />}
        </Box>
        {e.status === 'proposed' && (
          <IconButton size="small" aria-label="Remember" title="Remember" disabled={busy}
            onClick={() => run(() => confirmAriaMemory(e.id))}><CheckIcon fontSize="small" /></IconButton>
        )}
        <IconButton size="small" aria-label="Edit" title="Edit" disabled={busy}
          onClick={() => { setEditing(e.id); setEditDraft({ about: e.about, meaning: e.meaning, group: e.group || '' }); }}>
          <EditOutlinedIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" aria-label="Delete" title="Delete" disabled={busy}
          onClick={() => run(() => deleteAriaMemory(e.id))}><DeleteOutlineIcon fontSize="small" /></IconButton>
      </Stack>
    )
  );

  return (
    <Card>
      <CardContent>
        <Typography variant="h3">What Aria remembers</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
          Your own notes about the business: what payers, references and categories mean. Aria uses them
          in every board meeting and in chat. She suggests new ones in meetings; nothing is used until you
          confirm it. A group (e.g. "Memberships", "MOT work") also lets her show your income and spending
          in your own groups.
        </Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

        {proposed.length > 0 && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="h6">Waiting for you</Typography>
            {proposed.map(row)}
          </Box>
        )}

        <Typography variant="h6">Remembered</Typography>
        {confirmed.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>Nothing yet.</Typography>
        ) : confirmed.map(row)}

        <Stack spacing={1} sx={{ mt: 2 }}>
          <Typography variant="h6">Add a note</Typography>
          <TextField size="small" label="About (as it appears in the books)" value={draft.about}
            inputProps={{ maxLength: 80 }} onChange={(e) => setDraft({ ...draft, about: e.target.value })} />
          <TextField size="small" label="What it means" value={draft.meaning} multiline
            inputProps={{ maxLength: 300 }} onChange={(e) => setDraft({ ...draft, meaning: e.target.value })} />
          <TextField size="small" label="Group (optional)" value={draft.group}
            inputProps={{ maxLength: 60 }} onChange={(e) => setDraft({ ...draft, group: e.target.value })} />
          <Box>
            <Button variant="outlined" disabled={busy || !draft.about.trim() || !draft.meaning.trim()}
              onClick={() => run(async () => {
                await addAriaMemory({ about: draft.about, meaning: draft.meaning, group: draft.group.trim() || null });
                setDraft(EMPTY);
              })}>Add</Button>
          </Box>
        </Stack>

        <Stack spacing={1} sx={{ mt: 3 }}>
          <Typography variant="h6">Large one-off payments</Typography>
          <Typography variant="body2" color="text.secondary">
            Aria lists one-off receipts from this amount (£500 if left empty). A builder might choose £5,000.
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <TextField size="small" label="From £" value={threshold} type="number"
              inputProps={{ min: 1 }} onChange={(e) => setThreshold(e.target.value)} sx={{ maxWidth: 180 }} />
            <Button variant="outlined" disabled={busy}
              onClick={() => run(() => setOneOffFrom(threshold.trim() ? Number(threshold) : null))}>Save</Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
