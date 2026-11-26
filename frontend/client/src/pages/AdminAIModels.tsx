import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert, Box, Button, Chip, CircularProgress, Container, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, MenuItem, Paper, Stack, TextField, Tooltip, Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { apiRequest } from '@/lib/queryClient';
import { errorDetail } from '@/components/ReceptionistNumberRequest';

// AI-1c (docs/AI-1-TICKET.md M2): Mike chooses each of Aria's tasks' models.
// Every change records who and when and can be reverted; "Test this model"
// runs the task's test set side by side with what it uses now and saves nothing.

interface Pair { provider: string; model: string }
interface Option extends Pair { usable: boolean; reason: string | null; price_in_pence: number | null; price_out_pence: number | null; retires_on: string | null }
interface TaskRow {
  task: string; label: string; kind: string; openai_only: boolean;
  default: Pair[]; choice: Pair[] | null; previous: Pair[] | null; changed_by: string | null; changed_at: string | null;
  effective: Pair[]; max_chain: number; spent_pence: number | null; recorded_as: string[]; shared_with: string[];
  testable: boolean; options: Option[];
  retiring: (Pair & { retires_on: string })[];
}
interface Overview { period: string; tasks: TaskRow[]; providers: Record<string, boolean> }
interface CaseResult { name: string; passed: boolean; why: string; answer: string; seconds: number; pence: number }
interface Run { model: string; cases: number; passed: number; pence: number; results: CaseResult[] }

const NAMES: Record<string, string> = { openai: 'OpenAI', anthropic: 'Anthropic (Claude)', xai: 'xAI (Grok)' };
const key = (p: Pair) => `${p.provider}/${p.model}`;
const pounds = (pence: number) => `£${(pence / 100).toFixed(2)}`;
const perMillion = (o: Option) => (o.price_in_pence == null ? 'priced by the minute'
  : `${pounds(o.price_in_pence)} in · ${pounds(o.price_out_pence || 0)} out per million tokens`);
const FIRST = ['chat', 'chat_complex'];
// HK-3: when OpenAI stops serving a model.
const stops = (iso: string) => `Stops working ${new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`;

function ModelChips({ chain }: { chain: Pair[] }) {
  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
      {chain.map((p, i) => (
        <Chip key={key(p)} size="small" color={i === 0 ? 'primary' : 'default'} variant={i === 0 ? 'filled' : 'outlined'}
          label={`${i === 0 ? '' : 'then '}${key(p)}`} />
      ))}
    </Stack>
  );
}

export default function AdminAIModels() {
  const navigate = useNavigate();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editing, setEditing] = useState<TaskRow | null>(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try { setData(await (await apiRequest('GET', '/v1/admin/ai/models')).json()); setError(''); }
    catch (e) { setError(errorDetail(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function act(task: string, path: 'revert' | 'reset', done: string) {
    setBusy(task); setError(''); setNotice('');
    try { await apiRequest('POST', `/v1/admin/ai/models/${task}/${path}`, {}); setNotice(done); await load(); }
    catch (e) { setError(errorDetail(e)); } finally { setBusy(''); }
  }

  if (!data) {
    return <Container sx={{ py: 4 }}>{error ? <Alert severity="error">{error}</Alert> : <CircularProgress />}</Container>;
  }
  const rows = [...data.tasks].sort((a, b) => (FIRST.indexOf(a.task) === -1 ? 99 : FIRST.indexOf(a.task))
    - (FIRST.indexOf(b.task) === -1 ? 99 : FIRST.indexOf(b.task)));

  return (
    <Container maxWidth="lg" sx={{ py: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <IconButton aria-label="Back to admin" onClick={() => navigate('/admin')}><ArrowBackIcon /></IconButton>
        <Typography variant="h1">Aria's AI models</Typography>
      </Stack>
      <Typography variant="body1" sx={{ mb: 2 }}>
        Choose which model does each of Aria's jobs, and what she falls back to if it's unavailable. A change takes
        effect straight away; Revert undoes it. Test a model first: it's tried on a fixed set of questions next to what's used now.
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        {Object.entries(data.providers).map(([p, set]) => (
          <Chip key={p} size="small" color={set ? 'success' : 'default'} variant={set ? 'filled' : 'outlined'}
            label={`${NAMES[p] || p}: ${set ? 'key set' : 'no key'}`} />
        ))}
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}

      <Stack spacing={1.5}>
        {rows.map((row) => (
          <Paper key={row.task} variant="outlined" sx={{ p: 2, borderRadius: 3 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ md: 'center' }}>
              <Stack spacing={0.75} sx={{ minWidth: 0 }}>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                  <Typography sx={{ fontWeight: 700, color: 'text.primary' }}>{row.label}</Typography>
                  {row.choice ? <Chip size="small" label="your choice" /> : <Chip size="small" variant="outlined" label="default" />}
                  {row.retiring.map((r) => (
                    <Chip key={key(r)} size="small" color="warning" label={`${r.model}: ${stops(r.retires_on)}. Change it`} />
                  ))}
                  {row.openai_only && <Chip size="small" variant="outlined" label="OpenAI only" />}
                </Stack>
                <ModelChips chain={row.effective} />
                <Typography variant="body2">
                  {row.spent_pence == null ? 'Not costed separately'
                    : `This month: ${pounds(row.spent_pence)}${row.shared_with.length ? ` (shared with ${row.shared_with.join(', ')})` : ''}`}
                  {row.changed_at ? ` · changed ${new Date(row.changed_at).toLocaleString('en-GB')}` : ''}
                </Typography>
              </Stack>
              <Stack direction="row" spacing={1} flexShrink={0}>
                {row.choice && (
                  <Button size="small" disabled={busy === row.task}
                    onClick={() => act(row.task, 'revert', `${row.label}: reverted.`)}>Revert</Button>
                )}
                {row.choice && (
                  <Button size="small" disabled={busy === row.task}
                    onClick={() => act(row.task, 'reset', `${row.label}: back to the default.`)}>Use default</Button>
                )}
                <Button size="small" variant="outlined" onClick={() => setEditing(row)}>Change</Button>
              </Stack>
            </Stack>
          </Paper>
        ))}
      </Stack>
      {editing && (
        <ChangeDialog row={editing} onClose={() => setEditing(null)}
          onSaved={async (msg) => { setEditing(null); setNotice(msg); await load(); }} />
      )}
    </Container>
  );
}

function ChangeDialog({ row, onClose, onSaved }: { row: TaskRow; onClose: () => void; onSaved: (msg: string) => void }) {
  const usable = row.options.filter((o) => o.usable);
  const [chain, setChain] = useState<Pair[]>(row.effective.filter((p) => usable.some((o) => key(o) === key(p))));
  const [saving, setSaving] = useState(false), [error, setError] = useState('');
  const [testing, setTesting] = useState(false), [result, setResult] = useState<{ candidate: Run; current: Run } | null>(null);
  const set = (i: number, value: string) => {
    const [provider, ...rest] = value.split('/');
    setChain(chain.map((p, n) => (n === i ? { provider, model: rest.join('/') } : p)));
    setResult(null);
  };
  const remove = (i: number) => setChain(chain.filter((_, n) => n !== i));
  const add = () => {
    const next = usable.find((o) => !chain.some((p) => key(p) === key(o)));
    if (next) setChain([...chain, { provider: next.provider, model: next.model }]);
  };
  const duplicate = new Set(chain.map(key)).size !== chain.length;

  async function save() {
    setSaving(true); setError('');
    try {
      await apiRequest('PUT', `/v1/admin/ai/models/${row.task}`, { chain });
      onSaved(`${row.label}: now uses ${key(chain[0])}${chain.length > 1 ? `, then ${chain.slice(1).map(key).join(', then ')}` : ''}.`);
    } catch (e) { setError(errorDetail(e)); } finally { setSaving(false); }
  }

  async function test() {
    setTesting(true); setError(''); setResult(null);
    try { setResult(await (await apiRequest('POST', `/v1/admin/ai/models/${row.task}/test`, chain[0])).json()); }
    catch (e) { setError(errorDetail(e)); } finally { setTesting(false); }
  }

  return (
    <Dialog open onClose={() => !saving && !testing && onClose()} fullWidth maxWidth="md">
      <DialogTitle>{row.label}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2">
            {row.max_chain > 1
              ? "The first model answers; if it's unavailable, the next one does."
              : 'This job still calls OpenAI directly, so it uses one OpenAI model with no fallback for now.'}
            {' '}Default: {row.default.map(key).join(', then ')}.
          </Typography>
          {chain.map((p, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField select fullWidth size="small" label={i === 0 ? 'Uses' : `Then (fallback ${i})`} value={key(p)}
                onChange={(e) => set(i, e.target.value)}>
                {usable.map((o) => (
                  <MenuItem key={key(o)} value={key(o)}>
                    <Stack>
                      <span>{NAMES[o.provider] || o.provider}: {o.model}{o.retires_on ? ` (${stops(o.retires_on)})` : ''}</span>
                      <Typography variant="caption">{perMillion(o)}</Typography>
                    </Stack>
                  </MenuItem>
                ))}
              </TextField>
              {chain.length > 1 && (
                <Tooltip title="Remove"><IconButton aria-label={`Remove ${key(p)}`} onClick={() => remove(i)}><DeleteOutlineIcon /></IconButton></Tooltip>
              )}
            </Stack>
          ))}
          <Box>
            {row.max_chain > 1 && (
              <Button size="small" onClick={add} disabled={chain.length >= row.max_chain || usable.length <= chain.length}>
                + Add a fallback
              </Button>
            )}
          </Box>
          {row.options.some((o) => !o.usable) && (
            <Typography variant="caption">
              Not available: {row.options.filter((o) => !o.usable).map((o) => `${key(o)} (${o.reason})`).join('; ')}
            </Typography>
          )}
          {duplicate && <Alert severity="warning">The same model is listed twice.</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
          {testing && <Stack direction="row" spacing={1} alignItems="center"><CircularProgress size={18} /><Typography variant="body2">Trying both models on the test questions…</Typography></Stack>}
          {result && (
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
              {[['Trying', result.candidate], ['Used now', result.current]].map(([title, run]) => {
                const r = run as Run;
                return (
                  <Paper key={r.model + String(title)} variant="outlined" sx={{ p: 1.5, flex: 1, borderRadius: 2 }}>
                    <Typography sx={{ fontWeight: 700, color: 'text.primary' }}>{String(title)}: {r.model}</Typography>
                    <Typography variant="body2">Passed {r.passed} of {r.cases} · cost {pounds(r.pence)}</Typography>
                    {r.results.map((c) => (
                      <Tooltip key={c.name} title={c.answer ? `Answer: ${c.answer}` : ''} placement="top-start">
                        <Typography variant="body2" sx={{ mt: 0.5 }}>
                          {c.passed ? '✓' : '✗'} {c.name} ({c.seconds}s){c.passed ? '' : `: ${c.why}`}
                        </Typography>
                      </Tooltip>
                    ))}
                  </Paper>
                );
              })}
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving || testing}>Cancel</Button>
        <Tooltip title={row.testable ? '' : 'This job has no test questions yet'}>
          <span>
            <Button onClick={test} disabled={!row.testable || testing || saving || !chain.length}>Test this model</Button>
          </span>
        </Tooltip>
        <Button variant="contained" onClick={save} disabled={saving || testing || !chain.length || duplicate}>
          {saving ? <CircularProgress size={18} color="inherit" /> : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
