/**
 * Active meeting chat — the boardroom interface.
 *
 * Owner and Aria converse turn by turn. Aria writes plain paragraphs
 * (no markdown). Token usage shown discreetly. Soft-cap warning banner
 * at 80% of soft cap. End-Meeting button opens a confirmation dialog.
 *
 * BM-2: Talk / Type. Talking uses the board-meeting voice minutes (shown,
 * with a warning at 80%); when they run out the meeting carries on typed.
 * Spoken turns are saved by the server and appear here as they're heard.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Avatar,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  Snackbar,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import KeyboardIcon from '@mui/icons-material/Keyboard';
import MicIcon from '@mui/icons-material/Mic';
import { RealtimeVoice, RealtimeVoiceHandle } from '@/components/RealtimeVoice';
import SendIcon from '@mui/icons-material/Send';
import StopCircleOutlinedIcon from '@mui/icons-material/StopCircleOutlined';
import {
  AriaMemoryEntry,
  BoardVoiceUsage,
  confirmAriaMemory,
  deleteAriaMemory,
  getAriaMemory,
  EndMeetingResponse,
  ExecutiveMeeting,
  MeetingMessage,
  endMeeting,
  getBoardVoiceUsage,
  formatUKDateTime,
  sendMessage,
  startMeeting,
} from '@/lib/executiveMeetingsApi';
import { useMe } from '@/hooks/useMe';

const HARD_CAP_TOKENS = 100_000;
const SOFT_CAP_TOKENS = 50_000;

interface MeetingChatProps {
  meeting: ExecutiveMeeting;
  initialMessages?: MeetingMessage[];
  onEnded: (result: EndMeetingResponse) => void;
}

interface DisplayMessage {
  id: string;
  role: 'aria' | 'owner';
  content: string;
  tokens_used?: number;
  pending?: boolean;
}

export default function MeetingChat({ meeting, initialMessages, onEnded }: MeetingChatProps) {
  const { data: me } = useMe();
  const [messages, setMessages] = useState<DisplayMessage[]>(() =>
    (initialMessages || [])
      .filter((m) => m.role === 'aria' || m.role === 'owner')
      .map((m) => ({
        id: m.id,
        role: m.role as 'aria' | 'owner',
        content: m.content || '',
        tokens_used: m.tokens_used,
      })),
  );
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [endDialogOpen, setEndDialogOpen] = useState(false);
  const [softCapWarning, setSoftCapWarning] = useState(false);
  const [tokensTotal, setTokensTotal] = useState<number>(meeting.total_tokens_used || 0);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const openingTriggered = useRef(false);
  const [mode, setMode] = useState<'type' | 'talk'>('type');
  const [voiceUsage, setVoiceUsage] = useState<BoardVoiceUsage | null>(null);
  const [liveVoice, setLiveVoice] = useState<{ secondsLeft: number; warn: boolean } | null>(null);
  const [savingVoice, setSavingVoice] = useState(false);
  const voiceRef = useRef<RealtimeVoiceHandle>(null);
  const handleVoiceMinutes = useCallback((secondsLeft: number, warn: boolean) => {
    setLiveVoice({ secondsLeft, warn });
  }, []);

  const refreshVoiceUsage = useCallback(() => {
    getBoardVoiceUsage().then(setVoiceUsage).catch(() => setVoiceUsage(null));
  }, []);
  useEffect(() => { refreshVoiceUsage(); }, [refreshVoiceUsage]);

  // A spoken turn, as heard. The server has already saved it to the meeting.
  // BM-4: Aria's suggestions to remember, shown as cards to confirm.
  const [suggestions, setSuggestions] = useState<AriaMemoryEntry[]>([]);
  const refreshSuggestions = useCallback(() => {
    getAriaMemory()
      .then((m) => setSuggestions(m.entries.filter((e) => e.status === 'proposed')))
      .catch(() => undefined);   // the meeting goes on without them
  }, []);
  useEffect(() => { refreshSuggestions(); }, [refreshSuggestions]);
  const answerSuggestion = async (entry: AriaMemoryEntry, remember: boolean) => {
    setSuggestions((prev) => prev.filter((e) => e.id !== entry.id));
    try {
      if (remember) {
        await confirmAriaMemory(entry.id);
        setToast(`Aria will remember: ${entry.about}`);
      } else {
        await deleteAriaMemory(entry.id);
      }
    } catch (e) {
      setError((e as Error).message || 'That could not be saved');
      refreshSuggestions();
    }
  };

  const handleSpoken = useCallback((text: string, isUser: boolean) => {
    const content = (text || '').trim();
    if (!content) return;
    if (!isUser) refreshSuggestions();   // she may have just suggested something
    setMessages((prev) => [...prev, {
      id: `${isUser ? 'owner' : 'aria'}-voice-${Date.now()}-${prev.length}`,
      role: isUser ? 'owner' : 'aria',
      content,
    }]);
  }, [refreshSuggestions]);

  const handleVoiceEnded = useCallback((reason: string | null) => {
    setLiveVoice(null);
    refreshVoiceUsage();
    if (reason) {
      // e.g. the month's board-meeting voice minutes are used up: carry on typed.
      setMode('type');
      setToast(reason);
    }
  }, [refreshVoiceUsage]);

  const canTalk = !!voiceUsage?.voice_available;

  // Generate opening on mount if no messages yet and meeting is in_progress
  useEffect(() => {
    if (openingTriggered.current) return;
    if (messages.length > 0) return;
    if (meeting.status !== 'in_progress') return;
    openingTriggered.current = true;

    (async () => {
      setStarting(true);
      try {
        const result = await startMeeting(meeting.id);
        setMessages([
          {
            id: `aria-opening-${Date.now()}`,
            role: 'aria',
            content: result.opening_message,
            tokens_used: result.tokens_used,
          },
        ]);
        setTokensTotal((t) => t + (result.tokens_used || 0));
      } catch (e) {
        setError((e as Error).message || 'Failed to start meeting');
      } finally {
        setStarting(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meeting.id, meeting.status]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, sending]);

  const hardCapReached = tokensTotal >= HARD_CAP_TOKENS;
  const softCapReached = tokensTotal >= SOFT_CAP_TOKENS;

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending || hardCapReached) return;

    const ownerMsg: DisplayMessage = {
      id: `owner-${Date.now()}`,
      role: 'owner',
      content: text,
    };
    const pendingId = `aria-pending-${Date.now()}`;
    setMessages((prev) => [...prev, ownerMsg, {
      id: pendingId,
      role: 'aria',
      content: '',
      pending: true,
    }]);
    setInput('');
    setSending(true);
    setError(null);

    try {
      const result = await sendMessage(meeting.id, text);
      refreshSuggestions();
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
              id: `aria-${Date.now()}`,
              role: 'aria' as const,
              content: result.content,
              tokens_used: result.tokens_used,
            }
            : m,
        ),
      );
      setTokensTotal((t) => t + (result.tokens_used || 0));
      if (result.soft_cap_warning) setSoftCapWarning(true);
    } catch (e) {
      // Remove the pending Aria stub but keep the owner message (the user can retry)
      setMessages((prev) => prev.filter((m) => m.id !== pendingId));
      // Restore the owner's typed text so they can retry without retyping
      setInput(text);
      // Remove the locally-rendered owner message too (we'll send fresh on retry)
      setMessages((prev) => prev.filter((m) => m.id !== ownerMsg.id));
      setError((e as Error).message || 'Failed to send message. Try again.');
    } finally {
      setSending(false);
    }
  };

  const handleEnd = async () => {
    setEnding(true);
    setError(null);
    try {
      if (mode === 'talk') {
        // BM-2: what was said is saved BEFORE the meeting is summarised, and
        // the voice session (and its billing) ends first.
        setSavingVoice(true);
        const saved = (await voiceRef.current?.flushAndStop()) ?? true;
        setSavingVoice(false);
        if (!saved) {
          // Never summarise without part of what was said.
          setEndDialogOpen(false);
          setError("The last part of the conversation couldn't be saved yet, so the meeting is still open. "
            + 'Please try ending it again in a moment.');
          setEnding(false);
          return;
        }
        setMode('type');
      }
      const result = await endMeeting(meeting.id);
      setEndDialogOpen(false);
      setToast('Meeting ended.');
      onEnded(result);
    } catch (e) {
      // Close the dialog so the reason is visible, not hidden behind it.
      setEndDialogOpen(false);
      setError((e as Error).message || 'Failed to end meeting');
      setEnding(false);
    }
  };

  const ownerName = me?.name || 'You';

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: '70vh' }}>
      {/* Top bar */}
      <Stack
        direction="row"
        spacing={2}
        alignItems="center"
        justifyContent="space-between"
        sx={{ pb: 2, borderBottom: '1px solid', borderColor: 'divider', flexWrap: 'wrap', gap: 1 }}
      >
        <Box>
          <Typography variant="h3">{me?.name || 'Board meeting'}</Typography>
          <Typography variant="caption" color="text.secondary">
            {formatUKDateTime(meeting.scheduled_for)} · {tokensTotal.toLocaleString('en-GB')} / {HARD_CAP_TOKENS.toLocaleString('en-GB')} tokens
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center">
          <ToggleButtonGroup
            size="small"
            exclusive
            value={mode}
            onChange={(_, value) => value && setMode(value)}
            aria-label="Talk or type"
            disabled={ending || starting}
          >
            <ToggleButton value="type" aria-label="Type">
              <KeyboardIcon fontSize="small" sx={{ mr: 0.5 }} /> Type
            </ToggleButton>
            <ToggleButton value="talk" aria-label="Talk" disabled={!canTalk}>
              <MicIcon fontSize="small" sx={{ mr: 0.5 }} /> Talk
            </ToggleButton>
          </ToggleButtonGroup>
          <Button
            variant="outlined"
            color="error"
            startIcon={<StopCircleOutlinedIcon />}
            onClick={() => setEndDialogOpen(true)}
            disabled={ending}
          >
            End meeting
          </Button>
        </Stack>
      </Stack>

      {/* Voice minutes (BM-2) */}
      {mode === 'talk' && liveVoice ? (
        <Alert severity={liveVoice.warn ? 'warning' : 'info'} sx={{ mt: 2 }}>
          {`${Math.floor(liveVoice.secondsLeft / 60)} voice minute${Math.floor(liveVoice.secondsLeft / 60) === 1 ? '' : 's'} left this month.`}
          {liveVoice.warn ? ' Running low: when they run out, the meeting carries on by typing.' : ''}
        </Alert>
      ) : voiceUsage && (mode === 'talk' || voiceUsage.warn || !canTalk) && (
        <Alert severity={!canTalk ? 'info' : voiceUsage.warn ? 'warning' : 'info'} sx={{ mt: 2 }}>
          {!canTalk
            ? (voiceUsage.allowance_minutes > 0
              ? "This month's board-meeting voice minutes are used up, so this meeting is typed."
              : 'Voice meetings are not available on this plan, so this meeting is typed.')
            : `${voiceUsage.minutes_available_now} voice minute${voiceUsage.minutes_available_now === 1 ? '' : 's'} available this month`
              + (voiceUsage.warn
                ? ` (${Math.round(voiceUsage.used_minutes)} of ${voiceUsage.allowance_minutes} used).`
                  + (voiceUsage.extra_minutes_on ? ' Extra minutes are on, at £0.45 a minute.' : ' Typing is always available.')
                : '.')}
        </Alert>
      )}

      {/* Warnings */}
      {(softCapWarning || softCapReached) && !hardCapReached && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          Approaching the token limit. Aria will start wrapping up soon.
        </Alert>
      )}
      {hardCapReached && (
        <Alert severity="error" sx={{ mt: 2 }}>
          Token limit reached. Please end this meeting to capture commitments;
          you can start a new meeting afterwards.
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mt: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Message thread */}
      <Box
        sx={{
          flex: 1,
          overflowY: 'auto',
          py: 3,
          px: { xs: 0, md: 1 },
        }}
      >
        {messages.length === 0 && starting && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
            <Stack alignItems="center" spacing={1}>
              <CircularProgress size={28} />
              <Typography variant="body2" color="text.secondary">
                Aria is opening the meeting…
              </Typography>
            </Stack>
          </Box>
        )}

        <Stack spacing={3}>
          {messages.map((m) => (
            <Stack
              key={m.id}
              direction={m.role === 'aria' ? 'row' : 'row-reverse'}
              spacing={1.5}
              alignItems="flex-start"
              sx={{ maxWidth: '100%' }}
            >
              <Avatar
                sx={{
                  width: 32,
                  height: 32,
                  fontSize: 13,
                  bgcolor: m.role === 'aria' ? 'var(--color-aria-500, #8B5CF6)' : 'primary.main',
                }}
              >
                {m.role === 'aria' ? 'A' : (ownerName.charAt(0).toUpperCase() || 'Y')}
              </Avatar>
              <Box sx={{ maxWidth: '85%' }}>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                  {m.role === 'aria' ? 'Aria' : 'You'}
                </Typography>
                <Box
                  sx={{
                    px: 2,
                    py: 1.5,
                    borderRadius: 2,
                    backgroundColor: m.role === 'aria'
                      ? 'var(--surface-secondary)'
                      : 'rgba(124, 92, 252, 0.10)',
                    border: '1px solid',
                    borderColor: 'divider',
                  }}
                >
                  {m.pending ? (
                    <Stack direction="row" spacing={1} alignItems="center">
                      <CircularProgress size={14} />
                      <Typography variant="body2" color="text.secondary">
                        Aria is thinking…
                      </Typography>
                    </Stack>
                  ) : (
                    <Typography
                      variant="body1"
                      sx={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        lineHeight: 1.6,
                      }}
                    >
                      {m.content}
                    </Typography>
                  )}
                </Box>
              </Box>
            </Stack>
          ))}
        </Stack>
        <div ref={messagesEndRef} />
      </Box>

      {/* Aria's suggestions to remember (BM-4) */}
      {suggestions.map((entry) => (
        <Alert
          key={entry.id}
          severity="info"
          sx={{ mb: 1 }}
          action={(
            <Stack direction="row" spacing={1}>
              <Button size="small" variant="contained" onClick={() => answerSuggestion(entry, true)}>Remember</Button>
              <Button size="small" onClick={() => answerSuggestion(entry, false)}>Not now</Button>
            </Stack>
          )}
        >
          Aria suggests remembering: <strong>{entry.about}</strong> — {entry.meaning}
          {entry.group ? ` (group: ${entry.group})` : ''}
        </Alert>
      ))}

      {/* Input */}
      <Box
        sx={{
          borderTop: '1px solid',
          borderColor: 'divider',
          pt: 2,
        }}
      >
        {mode === 'talk' && canTalk && !hardCapReached ? (
          <RealtimeVoice
            ref={voiceRef}
            meetingId={meeting.id}
            onTranscript={handleSpoken}
            onSessionEnd={handleVoiceEnded}
            onVoiceMinutes={handleVoiceMinutes}
          />
        ) : (
        <Stack direction="row" spacing={1} alignItems="flex-end">
          <TextField
            fullWidth
            multiline
            minRows={1}
            maxRows={6}
            placeholder={
              hardCapReached
                ? 'Token limit reached — end the meeting to continue.'
                : 'Your message — Enter to send, Shift+Enter for a new line'
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={sending || starting || hardCapReached || ending}
          />
          <IconButton
            color="primary"
            onClick={handleSend}
            disabled={!input.trim() || sending || starting || hardCapReached || ending}
            sx={{ p: 1.25 }}
            aria-label="Send"
          >
            <SendIcon />
          </IconButton>
        </Stack>
        )}
      </Box>

      {/* End meeting confirmation */}
      <Dialog open={endDialogOpen} onClose={() => !ending && setEndDialogOpen(false)}>
        <DialogTitle>End this meeting?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Aria will summarise what was discussed and capture any action items.
            This may take up to 30 seconds.
            {savingVoice ? ' Saving what was said first…' : ''}
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setEndDialogOpen(false)} disabled={ending}>
            Continue meeting
          </Button>
          <Button
            variant="contained"
            color="primary"
            onClick={handleEnd}
            disabled={ending}
          >
            {ending ? 'Ending…' : 'End meeting'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={!!toast}
        autoHideDuration={3000}
        onClose={() => setToast(null)}
        message={toast || ''}
      />
    </Box>
  );
}
