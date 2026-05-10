/**
 * Post-meeting summary view.
 *
 * Shown when a meeting is `completed`. Displays Aria's summary,
 * key takeaways, sentiment, action items committed, goals set,
 * next meeting time, and a button to view the full transcript.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Stack,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import {
  ActionItem,
  ExecutiveMeeting,
  Goal,
  MeetingMessage,
  Sentiment,
  formatUKDateTime,
} from '@/lib/executiveMeetingsApi';

interface MeetingSummaryProps {
  meeting: ExecutiveMeeting;
  messages: MeetingMessage[];
  actionItems: ActionItem[];
  goals: Goal[];
}

function sentimentChip(s?: Sentiment | null) {
  if (!s) return null;
  const colour: 'success' | 'default' | 'warning' | 'error' =
    s === 'positive' ? 'success' :
    s === 'critical' ? 'error' :
    s === 'concerning' ? 'warning' : 'default';
  return (
    <Chip
      label={s}
      color={colour}
      size="small"
      sx={{ textTransform: 'capitalize' }}
    />
  );
}

export default function MeetingSummary({
  meeting,
  messages,
  actionItems,
  goals,
}: MeetingSummaryProps) {
  const navigate = useNavigate();
  const [transcriptOpen, setTranscriptOpen] = useState(false);

  // Filter action items + goals to those from this meeting
  const meetingActions = actionItems.filter((a) => a.meeting_id === meeting.id);
  const meetingGoals = goals.filter((g) => g.set_in_meeting_id === meeting.id);

  const keyTakeaways: string[] = Array.isArray((meeting as any).key_takeaways)
    ? (meeting as any).key_takeaways
    : [];

  return (
    <Box>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h1" sx={{ fontSize: { xs: '1.5rem', md: '1.875rem' }, mb: 0.5 }}>
            Meeting complete
          </Typography>
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
            <Typography variant="body2" color="text.secondary">
              {formatUKDateTime(meeting.scheduled_for)}
            </Typography>
            {meeting.duration_minutes ? (
              <Chip
                label={`${meeting.duration_minutes} min`}
                size="small"
                variant="outlined"
              />
            ) : null}
            {sentimentChip(meeting.sentiment)}
          </Stack>
        </Box>

        {meeting.summary && (
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ mb: 1 }}>Summary</Typography>
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                {meeting.summary}
              </Typography>
            </CardContent>
          </Card>
        )}

        {keyTakeaways.length > 0 && (
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ mb: 1.5 }}>Key takeaways</Typography>
              <Stack component="ul" spacing={1} sx={{ pl: 2.5, m: 0 }}>
                {keyTakeaways.map((t, i) => (
                  <li key={i}>
                    <Typography variant="body2">{t}</Typography>
                  </li>
                ))}
              </Stack>
            </CardContent>
          </Card>
        )}

        {meetingActions.length > 0 && (
          <Card>
            <CardContent>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ mb: 1.5 }}
              >
                <Typography variant="h3">
                  Action items committed ({meetingActions.length})
                </Typography>
                <Button
                  size="small"
                  variant="text"
                  onClick={() => navigate('/app/board-meeting?tab=actions')}
                >
                  View all
                </Button>
              </Stack>
              <Stack spacing={1}>
                {meetingActions.map((a) => (
                  <Stack
                    key={a.id}
                    direction="row"
                    spacing={1}
                    alignItems="center"
                    sx={{
                      px: 1.5,
                      py: 1,
                      border: '1px solid',
                      borderColor: 'divider',
                      borderRadius: 1,
                    }}
                  >
                    <Box sx={{ flex: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {a.title}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {[a.assignee_name, a.due_date].filter(Boolean).join(' · ') || 'No due date'}
                      </Typography>
                    </Box>
                    <Chip
                      label={a.priority}
                      size="small"
                      variant="outlined"
                      sx={{ textTransform: 'capitalize' }}
                    />
                  </Stack>
                ))}
              </Stack>
            </CardContent>
          </Card>
        )}

        {meetingGoals.length > 0 && (
          <Card>
            <CardContent>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ mb: 1.5 }}
              >
                <Typography variant="h3">
                  Goals set ({meetingGoals.length})
                </Typography>
                <Button
                  size="small"
                  variant="text"
                  onClick={() => navigate('/app/board-meeting?tab=goals')}
                >
                  View all
                </Button>
              </Stack>
              <Stack spacing={1}>
                {meetingGoals.map((g) => (
                  <Stack
                    key={g.id}
                    direction="row"
                    spacing={1}
                    alignItems="center"
                    sx={{
                      px: 1.5,
                      py: 1,
                      border: '1px solid',
                      borderColor: 'divider',
                      borderRadius: 1,
                    }}
                  >
                    <Box sx={{ flex: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>{g.title}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {g.horizon.replace('_', ' ')} · target {g.target_date || 'TBD'}
                      </Typography>
                    </Box>
                  </Stack>
                ))}
              </Stack>
            </CardContent>
          </Card>
        )}

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1.5}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
        >
          <Button variant="outlined" onClick={() => setTranscriptOpen(true)}>
            View transcript
          </Button>
          <Stack direction="row" spacing={1.5} alignItems="center">
            {meeting.total_tokens_used ? (
              <Typography variant="caption" color="text.secondary">
                {meeting.total_tokens_used.toLocaleString('en-GB')} tokens
              </Typography>
            ) : null}
            <Button
              variant="contained"
              onClick={() => navigate('/app/board-meeting')}
            >
              Done
            </Button>
          </Stack>
        </Stack>
      </Stack>

      {/* Transcript dialog */}
      <Dialog
        open={transcriptOpen}
        onClose={() => setTranscriptOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Stack direction="row" alignItems="center" justifyContent="space-between">
            <span>Transcript</span>
            <IconButton size="small" onClick={() => setTranscriptOpen(false)} aria-label="Close">
              <CloseIcon fontSize="small" />
            </IconButton>
          </Stack>
        </DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            {messages.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                Transcript unavailable.
              </Typography>
            )}
            {messages.map((m) => (
              <Box key={m.id}>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                  {m.role === 'aria' ? 'Aria' : m.role === 'owner' ? 'You' : m.role}
                </Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                  {m.content}
                </Typography>
                <Divider sx={{ mt: 1.5 }} />
              </Box>
            ))}
          </Stack>
        </DialogContent>
      </Dialog>
    </Box>
  );
}
