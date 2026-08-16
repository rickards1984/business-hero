/**
 * Action Items dashboard.
 *
 * Filterable, sortable list of action items extracted from meetings.
 * Inline status updates with optimistic UI.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import {
  ActionItem,
  ActionItemStatus,
  Priority,
  daysRemaining,
  formatUKDate,
  listActionItems,
  updateActionItem,
} from '@/lib/executiveMeetingsApi';

type Filter = 'all' | 'open' | 'in_progress' | 'completed' | 'blocked' | 'overdue';

const PRIORITY_COLOUR: Record<Priority, 'default' | 'info' | 'warning' | 'error'> = {
  low: 'default',
  medium: 'info',
  high: 'warning',
  urgent: 'error',
};

const STATUS_OPTIONS: Array<{ value: ActionItemStatus; label: string }> = [
  { value: 'open',         label: 'Open' },
  { value: 'in_progress',  label: 'In progress' },
  { value: 'blocked',      label: 'Blocked' },
  { value: 'deferred',     label: 'Deferred' },
  { value: 'completed',    label: 'Completed' },
  { value: 'cancelled',    label: 'Cancelled' },
];

export default function ActionItemsDashboard() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>('all');
  const [items, setItems] = useState<ActionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailItem, setDetailItem] = useState<ActionItem | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await listActionItems();
        if (!cancelled) setItems(data);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to load action items');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const visible = useMemo(() => {
    let list = items;
    if (filter === 'overdue') {
      list = items.filter((i) => {
        const d = daysRemaining(i.due_date || null);
        return i.status === 'open' || i.status === 'in_progress'
          ? d !== null && d < 0
          : false;
      });
    } else if (filter !== 'all') {
      list = items.filter((i) => i.status === filter);
    }
    // Smart sort: overdue first (red), then due-soon, then priority desc, then created desc
    return [...list].sort((a, b) => {
      const aDays = daysRemaining(a.due_date || null);
      const bDays = daysRemaining(b.due_date || null);
      const aOver = aDays !== null && aDays < 0;
      const bOver = bDays !== null && bDays < 0;
      if (aOver && !bOver) return -1;
      if (!aOver && bOver) return 1;
      const order: Record<Priority, number> = { urgent: 0, high: 1, medium: 2, low: 3 };
      const pa = order[a.priority] ?? 4;
      const pb = order[b.priority] ?? 4;
      if (pa !== pb) return pa - pb;
      return (b.created_at || '').localeCompare(a.created_at || '');
    });
  }, [items, filter]);

  const optimisticUpdate = async (id: string, updates: Partial<ActionItem>) => {
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...updates } : i)));
    setSavingId(id);
    try {
      const saved = await updateActionItem(id, updates);
      setItems((prev) =>
        prev.map((i) => (i.id === id ? { ...i, ...saved } : i)),
      );
      setToast({ type: 'success', message: 'Action item updated' });
    } catch (e) {
      // Revert on error: refetch
      try {
        const data = await listActionItems();
        setItems(data);
      } catch {}
      setToast({ type: 'error', message: 'Update failed' });
    } finally {
      setSavingId(null);
    }
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
          <ToggleButton value="open">Open</ToggleButton>
          <ToggleButton value="in_progress">In progress</ToggleButton>
          <ToggleButton value="completed">Completed</ToggleButton>
          <ToggleButton value="blocked">Blocked</ToggleButton>
          <ToggleButton value="overdue">Overdue</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="caption" color="text.secondary">
          {visible.length} {visible.length === 1 ? 'item' : 'items'}
        </Typography>
      </Stack>

      {visible.length === 0 ? (
        <Card>
          <CardContent>
            <Typography variant="body2" color="text.secondary">
              No action items{filter === 'all' ? ' yet' : ' for this filter'}.
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <Stack spacing={1}>
          {visible.map((item) => {
            const days = daysRemaining(item.due_date || null);
            const overdue = days !== null && days < 0 &&
              (item.status === 'open' || item.status === 'in_progress');
            const isDone = item.status === 'completed';
            return (
              <Card key={item.id} sx={{ opacity: isDone ? 0.65 : 1 }}>
                <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Stack direction="row" spacing={1.5} alignItems="flex-start">
                    <Checkbox
                      checked={isDone}
                      disabled={savingId === item.id}
                      onChange={(e) =>
                        optimisticUpdate(item.id, {
                          status: e.target.checked ? 'completed' : 'open',
                        })
                      }
                      sx={{ p: 0.5, mt: 0.25 }}
                    />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Typography
                          variant="body1"
                          sx={{
                            fontWeight: 600,
                            textDecoration: isDone ? 'line-through' : 'none',
                          }}
                        >
                          {item.title}
                        </Typography>
                        <Chip
                          label={item.priority}
                          size="small"
                          color={PRIORITY_COLOUR[item.priority]}
                          variant="outlined"
                          sx={{ textTransform: 'capitalize' }}
                        />
                      </Stack>

                      <Stack
                        direction="row"
                        spacing={1.5}
                        alignItems="center"
                        flexWrap="wrap"
                        sx={{ mt: 0.5 }}
                      >
                        {item.assignee_name && (
                          <Typography variant="caption" color="text.secondary">
                            {item.assignee_name}
                          </Typography>
                        )}
                        {item.due_date && (
                          <Typography
                            variant="caption"
                            sx={{ color: overdue ? 'error.main' : 'text.secondary' }}
                          >
                            {formatUKDate(item.due_date)}
                            {days !== null && (
                              <> · {overdue ? `${Math.abs(days)}d overdue` : `${days}d remaining`}</>
                            )}
                          </Typography>
                        )}
                        {item.meeting_id && (
                          <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{
                              cursor: 'pointer',
                              '&:hover': { textDecoration: 'underline' },
                            }}
                            onClick={() => navigate(`/app/board-meeting/meeting/${item.meeting_id}`)}
                          >
                            <OpenInNewIcon sx={{ fontSize: 12, mr: 0.25, verticalAlign: 'middle' }} />
                            View meeting
                          </Typography>
                        )}
                      </Stack>
                    </Box>

                    <FormControl size="small" sx={{ minWidth: 140 }}>
                      <Select
                        value={item.status}
                        onChange={(e) =>
                          optimisticUpdate(item.id, { status: e.target.value as ActionItemStatus })
                        }
                        disabled={savingId === item.id}
                      >
                        {STATUS_OPTIONS.map((s) => (
                          <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>

                    <IconButton
                      size="small"
                      onClick={() => setDetailItem(item)}
                      aria-label="Open detail"
                    >
                      <OpenInNewIcon fontSize="small" />
                    </IconButton>
                  </Stack>
                </CardContent>
              </Card>
            );
          })}
        </Stack>
      )}

      {/* Detail dialog */}
      <Dialog
        open={!!detailItem}
        onClose={() => setDetailItem(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{detailItem?.title}</DialogTitle>
        <DialogContent dividers>
          {detailItem && (
            <Stack spacing={2}>
              {detailItem.description && (
                <Box>
                  <Typography variant="caption" color="text.secondary">Description</Typography>
                  <Typography variant="body2">{detailItem.description}</Typography>
                </Box>
              )}
              {detailItem.rationale && (
                <Box>
                  <Typography variant="caption" color="text.secondary">Why this was agreed</Typography>
                  <Typography variant="body2">{detailItem.rationale}</Typography>
                </Box>
              )}
              {detailItem.success_criteria && (
                <Box>
                  <Typography variant="caption" color="text.secondary">Success criteria</Typography>
                  <Typography variant="body2">{detailItem.success_criteria}</Typography>
                </Box>
              )}
              <TextField
                label="Notes"
                multiline
                minRows={3}
                defaultValue={detailItem.notes || ''}
                onBlur={(e) => {
                  if (e.target.value !== (detailItem.notes || '')) {
                    optimisticUpdate(detailItem.id, { notes: e.target.value });
                  }
                }}
              />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <button
            onClick={() => setDetailItem(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '8px 16px' }}
          >
            <Typography variant="body2" color="primary">Close</Typography>
          </button>
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
