/**
 * Meeting history list.
 *
 * Most recent first. Filter by status. Expand for full summary + takeaways
 * + transcript link.
 */
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import {
  ExecutiveMeeting,
  MeetingStatus,
  Sentiment,
  formatUKDateTime,
} from '@/lib/executiveMeetingsApi';

interface MeetingListProps {
  meetings: ExecutiveMeeting[];
  loading: boolean;
  error: string | null;
}

type Filter = 'all' | 'completed' | 'scheduled' | 'in_progress';

function sentimentColour(s?: Sentiment | null): 'success' | 'default' | 'warning' | 'error' {
  switch (s) {
    case 'positive':  return 'success';
    case 'neutral':   return 'default';
    case 'concerning': return 'warning';
    case 'critical':  return 'error';
    default:          return 'default';
  }
}

function statusLabel(s: MeetingStatus): string {
  switch (s) {
    case 'completed':   return 'Completed';
    case 'in_progress': return 'In progress';
    case 'scheduled':   return 'Scheduled';
    case 'prep_ready':  return 'Ready';
    case 'cancelled':   return 'Cancelled';
    case 'failed':      return 'Failed';
    default:            return s;
  }
}

function statusColour(s: MeetingStatus): 'default' | 'primary' | 'success' | 'warning' | 'error' {
  switch (s) {
    case 'completed':   return 'success';
    case 'in_progress': return 'primary';
    case 'prep_ready':  return 'primary';
    case 'failed':      return 'error';
    case 'cancelled':   return 'warning';
    default:            return 'default';
  }
}

export default function MeetingList({ meetings, loading, error }: MeetingListProps) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>('all');

  const filtered = useMemo(() => {
    if (filter === 'all') return meetings;
    if (filter === 'completed') return meetings.filter((m) => m.status === 'completed');
    if (filter === 'scheduled')
      return meetings.filter((m) => ['scheduled', 'prep_ready'].includes(m.status));
    if (filter === 'in_progress') return meetings.filter((m) => m.status === 'in_progress');
    return meetings;
  }, [meetings, filter]);

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
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="completed">Completed</ToggleButton>
          <ToggleButton value="scheduled">Scheduled</ToggleButton>
          <ToggleButton value="in_progress">In progress</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="caption" color="text.secondary">
          {filtered.length} {filtered.length === 1 ? 'meeting' : 'meetings'}
        </Typography>
      </Stack>

      {filtered.length === 0 ? (
        <Card>
          <CardContent>
            <Typography variant="body2" color="text.secondary">
              No meetings yet. Your first meeting will be a great starting point for
              setting up rhythms and goals.
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <Stack spacing={1.5}>
          {filtered.map((m) => (
            <Accordion key={m.id} disableGutters elevation={0}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  spacing={1.5}
                  alignItems={{ sm: 'center' }}
                  sx={{ width: '100%', pr: 2 }}
                >
                  <Typography variant="body2" sx={{ fontWeight: 600, minWidth: 220 }}>
                    {formatUKDateTime(m.scheduled_for)}
                  </Typography>
                  <Chip
                    label={statusLabel(m.status)}
                    size="small"
                    color={statusColour(m.status)}
                    variant="outlined"
                  />
                  {m.sentiment && (
                    <Chip
                      label={m.sentiment}
                      size="small"
                      color={sentimentColour(m.sentiment)}
                      sx={{ textTransform: 'capitalize' }}
                    />
                  )}
                  {m.duration_minutes ? (
                    <Typography variant="caption" color="text.secondary">
                      {m.duration_minutes} min
                    </Typography>
                  ) : null}
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{
                      flex: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {m.summary || '—'}
                  </Typography>
                </Stack>
              </AccordionSummary>
              <AccordionDetails>
                <Stack spacing={2}>
                  {m.summary ? (
                    <Box>
                      <Typography variant="h6" sx={{ mb: 0.5 }}>Summary</Typography>
                      <Typography variant="body2">{m.summary}</Typography>
                    </Box>
                  ) : null}

                  <Stack
                    direction="row"
                    spacing={1.5}
                    alignItems="center"
                    flexWrap="wrap"
                    useFlexGap
                  >
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<OpenInNewIcon fontSize="small" />}
                      onClick={() => navigate(`/app/board-meeting/meeting/${m.id}`)}
                    >
                      {m.status === 'completed' ? 'View summary' :
                        m.status === 'in_progress' ? 'Resume meeting' :
                        m.status === 'prep_ready' ? 'Start meeting' :
                        'Open meeting'}
                    </Button>
                    {m.total_tokens_used ? (
                      <Typography variant="caption" color="text.secondary">
                        {m.total_tokens_used.toLocaleString('en-GB')} tokens
                      </Typography>
                    ) : null}
                  </Stack>
                </Stack>
              </AccordionDetails>
            </Accordion>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
