/**
 * Meeting detail router.
 *
 * For a given :meetingId, looks up the meeting and renders the right view:
 *   - prep_ready → PrepView (then transitions to MeetingChat on Begin)
 *   - in_progress → MeetingChat
 *   - completed → MeetingSummary
 *   - scheduled / failed / cancelled → a small status card
 */
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Container,
  Stack,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import {
  ActionItem,
  ExecutiveMeeting,
  Goal,
  MeetingMessage,
  PrepData,
  formatUKDateTime,
  getMeetingMessages,
  getMeetingPrepData,
  listActionItems,
  listGoals,
  listMeetings,
} from '@/lib/executiveMeetingsApi';
import PrepView from '@/components/board-meeting/PrepView';
import MeetingChat from '@/components/board-meeting/MeetingChat';
import MeetingSummary from '@/components/board-meeting/MeetingSummary';

export default function MeetingDetailView() {
  const { meetingId } = useParams<{ meetingId: string }>();
  const navigate = useNavigate();
  const [meeting, setMeeting] = useState<ExecutiveMeeting | null>(null);
  const [prepData, setPrepData] = useState<PrepData | null>(null);
  const [messages, setMessages] = useState<MeetingMessage[]>([]);
  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [beginning, setBeginning] = useState(false);
  const [forceChat, setForceChat] = useState(false);

  const fetchMeeting = async () => {
    if (!meetingId) return;
    setError(null);

    // 1. Always fetch the latest meeting row (status, summary, prep_data, etc)
    const prep = await getMeetingPrepData(meetingId);
    setPrepData(prep.prep_data);

    // 2. Fetch the matching meeting record from the listing (cheaper than a dedicated
    //    /v1/executive-meetings/{id} endpoint which doesn't exist yet).
    const list = await listMeetings(50);
    const found = list.find((m) => m.id === meetingId);
    if (!found) {
      throw new Error('Meeting not found');
    }
    // Merge in the freshly-fetched prep_data
    setMeeting({ ...found, prep_data: prep.prep_data });

    // 3. Messages, action items, goals
    const [msgs, actions, gs] = await Promise.all([
      getMeetingMessages(meetingId).catch(() => []),
      listActionItems().catch(() => []),
      listGoals().catch(() => []),
    ]);
    setMessages(msgs);
    setActionItems(actions);
    setGoals(gs);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        await fetchMeeting();
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to load meeting');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId]);

  const handleBegin = async () => {
    if (!meeting) return;
    setBeginning(true);
    // Begin = transition to in_progress and render chat. The chat itself
    // will call /start to elicit Aria's opening message.
    setMeeting({ ...meeting, status: 'in_progress' });
    setForceChat(true);
    setBeginning(false);
  };

  const handleEnded = async () => {
    // Refetch the meeting (status will be 'completed' + summary populated)
    try {
      await fetchMeeting();
    } catch (e) {
      setError((e as Error).message || 'Failed to refresh after ending');
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (error || !meeting) {
    return (
      <Container maxWidth="lg" sx={{ py: 3 }}>
        <Alert severity="error">{error || 'Meeting not found'}</Alert>
        <Box sx={{ mt: 2 }}>
          <Button
            startIcon={<ArrowBackIcon />}
            onClick={() => navigate('/app/board-meeting')}
          >
            Back to board meeting
          </Button>
        </Box>
      </Container>
    );
  }

  const renderHeader = () => (
    <Stack
      direction="row"
      spacing={1.5}
      alignItems="center"
      sx={{ mb: 2 }}
    >
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/app/board-meeting')}
        size="small"
        variant="text"
      >
        Back
      </Button>
    </Stack>
  );

  // Route by status
  if (meeting.status === 'prep_ready' && !forceChat) {
    return (
      <Container maxWidth="lg" sx={{ py: { xs: 2, md: 3 } }}>
        {renderHeader()}
        <PrepView
          meeting={meeting}
          prepData={prepData}
          onBegin={handleBegin}
          beginning={beginning}
        />
      </Container>
    );
  }

  if (meeting.status === 'in_progress' || forceChat) {
    return (
      <Container maxWidth="lg" sx={{ py: { xs: 2, md: 3 } }}>
        {renderHeader()}
        <MeetingChat
          meeting={meeting}
          initialMessages={messages}
          onEnded={handleEnded}
        />
      </Container>
    );
  }

  if (meeting.status === 'completed') {
    return (
      <Container maxWidth="lg" sx={{ py: { xs: 2, md: 3 } }}>
        {renderHeader()}
        <MeetingSummary
          meeting={meeting}
          messages={messages}
          actionItems={actionItems}
          goals={goals}
        />
      </Container>
    );
  }

  // scheduled / failed / cancelled
  return (
    <Container maxWidth="lg" sx={{ py: { xs: 2, md: 3 } }}>
      {renderHeader()}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Chip
              label={meeting.status.replace('_', ' ')}
              size="small"
              sx={{ alignSelf: 'flex-start', textTransform: 'capitalize' }}
            />
            <Typography variant="h2">
              {formatUKDateTime(meeting.scheduled_for)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {meeting.status === 'scheduled'
                ? 'Aria is preparing for this meeting. Check back closer to the scheduled time.'
                : meeting.status === 'failed'
                ? 'This meeting failed to prep. Try starting an ad-hoc meeting instead.'
                : 'This meeting has been cancelled.'}
            </Typography>
          </Stack>
        </CardContent>
      </Card>
    </Container>
  );
}
