/**
 * Board Meeting — Overview tab content.
 *
 * The default landing tab. Shows next-meeting card, last-meeting recap,
 * open action items snapshot, and active goals snapshot.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
  Typography,
} from '@mui/material';
import EventOutlinedIcon from '@mui/icons-material/EventOutlined';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import {
  ActionItem,
  ExecutiveMeeting,
  ExecutiveMeetingSettings,
  Goal,
  daysRemaining,
  formatUKDateTime,
  startNow,
} from '@/lib/executiveMeetingsApi';

interface OverviewProps {
  settings: ExecutiveMeetingSettings | null;
  meetings: ExecutiveMeeting[];
  actionItems: ActionItem[];
  goals: Goal[];
  onChangeTab: (tab: string) => void;
}

export default function BoardMeetingOverview({
  settings,
  meetings,
  actionItems,
  goals,
  onChangeTab,
}: OverviewProps) {
  const navigate = useNavigate();
  const [startingAdHoc, setStartingAdHoc] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upcoming = meetings.find(
    (m) => m.status === 'prep_ready' || m.status === 'in_progress' || m.status === 'scheduled',
  );
  const lastCompleted = meetings.find((m) => m.status === 'completed');

  const openActions = actionItems.filter(
    (a) => a.status === 'open' || a.status === 'in_progress',
  );
  const activeGoals = goals.filter((g) => g.status === 'active');

  const settingsAreDefault = settings?.is_default === true;

  const startAdHoc = async () => {
    setStartingAdHoc(true);
    setError(null);
    try {
      const result = await startNow();
      navigate(`/app/board-meeting/meeting/${result.meeting_id}`);
    } catch (e) {
      setError((e as Error).message || 'Failed to start meeting');
      setStartingAdHoc(false);
    }
  };

  const renderNextMeetingCard = () => {
    if (upcoming) {
      const ctaLabel =
        upcoming.status === 'in_progress' ? 'Resume meeting' :
        upcoming.status === 'prep_ready'  ? 'Start meeting' :
        'Open meeting';
      return (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <EventOutlinedIcon sx={{ color: 'primary.main' }} />
                <Typography variant="caption" color="text.secondary">
                  {upcoming.status === 'in_progress' ? 'Meeting in progress' :
                    upcoming.status === 'prep_ready'  ? 'Meeting ready' :
                    'Next meeting'}
                </Typography>
              </Stack>
              <Typography variant="h2">
                {formatUKDateTime(upcoming.scheduled_for)}
              </Typography>
              <Stack direction="row" spacing={1}>
                <Button
                  variant="contained"
                  size="large"
                  startIcon={<PlayArrowIcon />}
                  onClick={() => navigate(`/app/board-meeting/meeting/${upcoming.id}`)}
                >
                  {ctaLabel}
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      );
    }

    return (
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction="row" spacing={1.5} alignItems="center">
              <AccessTimeIcon sx={{ color: 'text.secondary' }} />
              <Typography variant="caption" color="text.secondary">No meetings scheduled</Typography>
            </Stack>
            <Typography variant="h2">
              {settings?.enabled && settings?.next_meeting_at
                ? formatUKDateTime(settings.next_meeting_at)
                : 'Set up your meeting schedule'}
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <Button
                variant="contained"
                startIcon={<PlayArrowIcon />}
                onClick={startAdHoc}
                disabled={startingAdHoc}
              >
                {startingAdHoc ? 'Starting…' : 'Start ad-hoc meeting'}
              </Button>
              {settingsAreDefault && (
                <Button variant="outlined" onClick={() => onChangeTab('settings')}>
                  Set up schedule
                </Button>
              )}
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    );
  };

  return (
    <Stack spacing={3}>
      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {renderNextMeetingCard()}

      {lastCompleted && (
        <Card>
          <CardContent>
            <Stack spacing={1.5}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h3">Last meeting</Typography>
                <Button
                  size="small"
                  variant="text"
                  onClick={() =>
                    navigate(`/app/board-meeting/meeting/${lastCompleted.id}`)
                  }
                >
                  Full summary
                </Button>
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {formatUKDateTime(lastCompleted.scheduled_for)}
              </Typography>
              {lastCompleted.summary ? (
                <Typography variant="body2">{lastCompleted.summary}</Typography>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No summary available.
                </Typography>
              )}
            </Stack>
          </CardContent>
        </Card>
      )}

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' },
          gap: 2,
        }}
      >
        <Card>
          <CardContent>
            <Stack spacing={1.5}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h3">Open action items</Typography>
                <Button size="small" variant="text" onClick={() => onChangeTab('actions')}>
                  View all
                </Button>
              </Stack>
              <Typography variant="h1">{openActions.length}</Typography>
              {openActions.slice(0, 3).map((a) => {
                const days = daysRemaining(a.due_date || null);
                const overdue = days !== null && days < 0;
                return (
                  <Stack
                    key={a.id}
                    direction="row"
                    spacing={1}
                    alignItems="center"
                    sx={{ py: 0.5 }}
                  >
                    <Box sx={{ flex: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {a.title}
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ color: overdue ? 'error.main' : 'text.secondary' }}
                      >
                        {a.due_date
                          ? (overdue
                              ? `${Math.abs(days || 0)}d overdue`
                              : `${days}d remaining`)
                          : 'No due date'}
                      </Typography>
                    </Box>
                    <Chip
                      label={a.priority}
                      size="small"
                      variant="outlined"
                      sx={{ textTransform: 'capitalize' }}
                    />
                  </Stack>
                );
              })}
              {openActions.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  Nothing outstanding. Well done.
                </Typography>
              )}
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Stack spacing={1.5}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h3">Active goals</Typography>
                <Button size="small" variant="text" onClick={() => onChangeTab('goals')}>
                  View all
                </Button>
              </Stack>
              <Typography variant="h1">{activeGoals.length}</Typography>
              {activeGoals.slice(0, 3).map((g) => (
                <Box key={g.id} sx={{ py: 0.5 }}>
                  <Typography variant="body2" sx={{ fontWeight: 500 }}>{g.title}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {g.horizon.replace('_', ' ')}
                    {g.target_date ? ` · target ${g.target_date}` : ''}
                  </Typography>
                </Box>
              ))}
              {activeGoals.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  No active goals. Your next meeting is the place to set them.
                </Typography>
              )}
            </Stack>
          </CardContent>
        </Card>
      </Box>
    </Stack>
  );
}
