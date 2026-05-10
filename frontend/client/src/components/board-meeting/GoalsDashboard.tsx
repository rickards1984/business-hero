/**
 * Goals dashboard.
 *
 * Grid of goal cards with KPI progress bars, target dates, and quick status
 * transitions.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Snackbar,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import {
  Goal,
  GoalStatus,
  daysRemaining,
  formatUKDate,
  listGoals,
  updateGoal,
} from '@/lib/executiveMeetingsApi';

type Filter = 'all' | 'active' | 'achieved' | 'missed' | 'on_hold';

const HORIZON_LABEL: Record<string, string> = {
  short_term: 'Short-term',
  medium_term: 'Medium-term',
  long_term: 'Long-term',
};

const HORIZON_COLOUR: Record<string, 'default' | 'info' | 'primary'> = {
  short_term: 'default',
  medium_term: 'info',
  long_term: 'primary',
};

function statusColour(s: GoalStatus): 'default' | 'success' | 'warning' | 'error' | 'info' {
  switch (s) {
    case 'achieved': return 'success';
    case 'active':   return 'info';
    case 'missed':   return 'error';
    case 'on_hold':  return 'warning';
    case 'cancelled': return 'default';
    default:         return 'default';
  }
}

export default function GoalsDashboard() {
  const navigate = useNavigate();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [detail, setDetail] = useState<Goal | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await listGoals();
        if (!cancelled) setGoals(data);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to load goals');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const visible = useMemo(() => {
    if (filter === 'all') return goals;
    return goals.filter((g) => g.status === filter);
  }, [goals, filter]);

  const optimisticUpdate = async (id: string, updates: Partial<Goal>) => {
    setGoals((prev) => prev.map((g) => (g.id === id ? { ...g, ...updates } : g)));
    setSavingId(id);
    try {
      const saved = await updateGoal(id, updates);
      setGoals((prev) => prev.map((g) => (g.id === id ? { ...g, ...saved } : g)));
      setToast({ type: 'success', message: 'Goal updated' });
    } catch {
      try {
        const data = await listGoals();
        setGoals(data);
      } catch {}
      setToast({ type: 'error', message: 'Update failed' });
    } finally {
      setSavingId(null);
    }
  };

  const kpiProgress = (g: Goal): number | null => {
    if (!g.kpi_target_value || g.kpi_target_value <= 0) return null;
    if (g.kpi_current_value === null || g.kpi_current_value === undefined) return null;
    return Math.max(0, Math.min(100, (g.kpi_current_value / g.kpi_target_value) * 100));
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }
  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
        <ToggleButtonGroup
          value={filter}
          exclusive
          size="small"
          onChange={(_, v: Filter | null) => v && setFilter(v)}
          sx={{ flexWrap: 'wrap' }}
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="active">Active</ToggleButton>
          <ToggleButton value="achieved">Achieved</ToggleButton>
          <ToggleButton value="missed">Missed</ToggleButton>
          <ToggleButton value="on_hold">On hold</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="caption" color="text.secondary">
          {visible.length} {visible.length === 1 ? 'goal' : 'goals'}
        </Typography>
      </Stack>

      {visible.length === 0 ? (
        <Card>
          <CardContent>
            <Typography variant="body2" color="text.secondary">
              No goals{filter === 'all' ? ' set yet — your next board meeting is the place to set them' : ' match this filter'}.
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' },
            gap: 2,
          }}
        >
          {visible.map((g) => {
            const progress = kpiProgress(g);
            const days = daysRemaining(g.target_date);
            const overdue = days !== null && days < 0 && g.status === 'active';
            return (
              <Card key={g.id}>
                <CardContent>
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1} alignItems="flex-start" justifyContent="space-between">
                      <Typography variant="h5" sx={{ flex: 1, mr: 1 }}>{g.title}</Typography>
                      <Chip
                        label={g.status.replace('_', ' ')}
                        size="small"
                        color={statusColour(g.status)}
                        sx={{ textTransform: 'capitalize' }}
                      />
                    </Stack>

                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      <Chip
                        label={HORIZON_LABEL[g.horizon] || g.horizon}
                        size="small"
                        color={HORIZON_COLOUR[g.horizon] || 'default'}
                        variant="outlined"
                      />
                      {g.category && (
                        <Chip
                          label={g.category}
                          size="small"
                          variant="outlined"
                          sx={{ textTransform: 'capitalize' }}
                        />
                      )}
                    </Stack>

                    {progress !== null && g.kpi_name && (
                      <Box>
                        <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ mb: 0.5 }}>
                          <Typography variant="caption" color="text.secondary">
                            {g.kpi_name}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {g.kpi_current_value}{g.kpi_unit ? ` ${g.kpi_unit}` : ''}
                            {' / '}
                            {g.kpi_target_value}{g.kpi_unit ? ` ${g.kpi_unit}` : ''}
                          </Typography>
                        </Stack>
                        <LinearProgress
                          variant="determinate"
                          value={progress}
                          color={progress >= 100 ? 'success' : 'primary'}
                        />
                      </Box>
                    )}

                    {g.target_date && (
                      <Typography
                        variant="caption"
                        sx={{ color: overdue ? 'error.main' : 'text.secondary' }}
                      >
                        Target: {formatUKDate(g.target_date)}
                        {days !== null && (
                          <> · {overdue ? `${Math.abs(days)}d overdue` : `${days}d remaining`}</>
                        )}
                      </Typography>
                    )}

                    <Stack direction="row" spacing={1} sx={{ pt: 1 }}>
                      <Button size="small" variant="outlined" onClick={() => setDetail(g)}>
                        Details
                      </Button>
                      {g.set_in_meeting_id && (
                        <Button
                          size="small"
                          variant="text"
                          startIcon={<OpenInNewIcon fontSize="small" />}
                          onClick={() => navigate(`/app/board-meeting/meeting/${g.set_in_meeting_id}`)}
                        >
                          Set in meeting
                        </Button>
                      )}
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>
            );
          })}
        </Box>
      )}

      <Dialog open={!!detail} onClose={() => setDetail(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{detail?.title}</DialogTitle>
        <DialogContent dividers>
          {detail && (
            <Stack spacing={2}>
              {detail.description && (
                <Box>
                  <Typography variant="caption" color="text.secondary">Description</Typography>
                  <Typography variant="body2">{detail.description}</Typography>
                </Box>
              )}
              <Stack direction="row" spacing={1.5} flexWrap="wrap">
                <Chip
                  label={HORIZON_LABEL[detail.horizon] || detail.horizon}
                  size="small"
                  variant="outlined"
                />
                {detail.category && (
                  <Chip label={detail.category} size="small" variant="outlined" sx={{ textTransform: 'capitalize' }} />
                )}
              </Stack>
              {detail.kpi_name && (
                <Box>
                  <Typography variant="caption" color="text.secondary">KPI</Typography>
                  <Typography variant="body2">
                    {detail.kpi_name}: {detail.kpi_current_value ?? '—'}
                    {' / '}
                    {detail.kpi_target_value ?? '—'}
                    {detail.kpi_unit ? ` ${detail.kpi_unit}` : ''}
                  </Typography>
                </Box>
              )}
              {detail.progress_history && detail.progress_history.length > 0 && (
                <Box>
                  <Typography variant="caption" color="text.secondary">Progress history</Typography>
                  <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                    {detail.progress_history.map((p, i) => (
                      <Typography key={i} variant="body2" color="text.secondary">
                        {formatUKDate(p.date)} — {p.value}{detail.kpi_unit ? ` ${detail.kpi_unit}` : ''}
                        {p.note ? ` · ${p.note}` : ''}
                      </Typography>
                    ))}
                  </Stack>
                </Box>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          {detail && detail.status === 'active' && (
            <>
              <Button
                onClick={() => {
                  optimisticUpdate(detail.id, { status: 'on_hold' });
                  setDetail(null);
                }}
                disabled={savingId === detail.id}
              >
                Pause
              </Button>
              <Button
                onClick={() => {
                  optimisticUpdate(detail.id, { status: 'missed' });
                  setDetail(null);
                }}
                color="error"
                disabled={savingId === detail.id}
              >
                Mark missed
              </Button>
              <Button
                onClick={() => {
                  optimisticUpdate(detail.id, { status: 'achieved' });
                  setDetail(null);
                }}
                variant="contained"
                color="success"
                disabled={savingId === detail.id}
              >
                Mark achieved
              </Button>
            </>
          )}
          <Button onClick={() => setDetail(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={!!toast}
        autoHideDuration={3000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast ? (
          <Alert severity={toast.type} onClose={() => setToast(null)}>
            {toast.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Stack>
  );
}
