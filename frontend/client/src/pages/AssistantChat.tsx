import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  FormControlLabel,
  Paper,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import MicIcon from '@mui/icons-material/Mic';
import MicOffIcon from '@mui/icons-material/MicOff';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';

type ChatRole = 'user' | 'assistant';

interface ChatMessage {
  role: ChatRole;
  content: string;
}

const QUICK_ACTIONS = [
  "Summarise today’s calls",
  'List open tasks I should do next',
  'Create a follow-up message for the last caller',
];

export default function AssistantChat() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<any>(null);
  const lastSpokenIndexRef = useRef<number>(-1);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [authLoading, user, navigate]);

  useEffect(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceSupported(false);
      return;
    }
    setVoiceSupported(true);
    const recognition = new SpeechRecognition();
    recognition.lang = 'en-GB';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event: any) => {
      const transcript = event.results?.[0]?.[0]?.transcript;
      if (transcript) {
        setInput(transcript);
        inputRef.current?.focus();
      }
    };
    recognition.onerror = (event: any) => {
      setError(event?.error || 'Voice input error');
      setListening(false);
    };
    recognition.onend = () => {
      setListening(false);
    };
    recognitionRef.current = recognition;
    return () => {
      recognition.stop?.();
    };
  }, []);

  useEffect(() => {
    if (!speakReplies) {
      window.speechSynthesis?.cancel();
      setSpeaking(false);
    }
  }, [speakReplies]);

  useEffect(() => {
    if (!speakReplies) return;
    if (!messages.length) return;
    const lastIndex = messages.length - 1;
    if (lastSpokenIndexRef.current === lastIndex) return;
    const lastMessage = messages[lastIndex];
    if (lastMessage.role !== 'assistant' || !lastMessage.content) {
      lastSpokenIndexRef.current = lastIndex;
      return;
    }
    lastSpokenIndexRef.current = lastIndex;
    if (!window.speechSynthesis) {
      setError('Speech synthesis not supported');
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(lastMessage.content);
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  }, [messages, speakReplies]);

  const handleSend = async () => {
    const message = input.trim();
    if (!message || loading) return;

    setError('');
    setLoading(true);
    setMessages((prev) => [...prev, { role: 'user', content: message }]);
    setInput('');

    try {
      const payload: Record<string, any> = { message };
      if (conversationId) payload.conversation_id = conversationId;
      const response = await apiRequest('POST', '/v1/assistant/chat', payload);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to send message');
      }
      const data = await response.json();
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply || '' }]);
      if (data.conversation_id) {
        setConversationId(data.conversation_id);
      }
    } catch (err: any) {
      setError(err.message || 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickAction = (text: string) => {
    setInput(text);
    inputRef.current?.focus();
  };

  const handleMicToggle = () => {
    if (!voiceSupported || !recognitionRef.current) return;
    if (listening) {
      recognitionRef.current.stop();
      setListening(false);
    } else {
      setError('');
      recognitionRef.current.start();
      setListening(true);
    }
  };

  const handleStopSpeaking = () => {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  };

  if (authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Button
          variant="outlined"
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/app')}
          fullWidth={{ xs: true, sm: false }}
        >
          Back to Dashboard
        </Button>
      </Box>
      <Paper sx={{ p: 3, mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <SmartToyIcon color="primary" />
          <Typography variant="h6">AI Admin Chat</Typography>
        </Box>
        <Typography variant="body2" color="text.secondary">
          Ask the assistant to summarise calls, list tasks, or draft follow-ups.
        </Typography>
      </Paper>

      <Paper sx={{ p: 3, mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Quick actions
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {QUICK_ACTIONS.map((action) => (
            <Button key={action} variant="outlined" size="small" onClick={() => handleQuickAction(action)}>
              {action}
            </Button>
          ))}
        </Box>
      </Paper>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <FormControlLabel
            control={
              <Switch
                checked={speakReplies}
                onChange={(event) => setSpeakReplies(event.target.checked)}
              />
            }
            label="Speak replies"
          />
          {speaking && (
            <Button variant="outlined" size="small" onClick={handleStopSpeaking}>
              Stop speaking
            </Button>
          )}
          {listening && (
            <Typography variant="body2" color="primary">
              Listening...
            </Typography>
          )}
        </Box>
      </Paper>

      <Paper sx={{ p: 3, mb: 2, minHeight: 320 }}>
        {messages.length === 0 ? (
          <Typography color="text.secondary">Start a conversation to see responses here.</Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {messages.map((message, idx) => (
              <Box
                key={`${message.role}-${idx}`}
                sx={{
                  alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start',
                  bgcolor: message.role === 'user' ? 'primary.main' : 'grey.100',
                  color: message.role === 'user' ? 'primary.contrastText' : 'text.primary',
                  px: 2,
                  py: 1.5,
                  borderRadius: 2,
                  maxWidth: '85%',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {message.role === 'assistant' ? (
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                ) : (
                  <Typography variant="body2">{message.content}</Typography>
                )}
              </Box>
            ))}
          </Box>
        )}
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', gap: 2 }}>
          <TextField
            inputRef={inputRef}
            fullWidth
            placeholder="Ask your AI admin..."
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                handleSend();
              }
            }}
            multiline
            minRows={1}
            maxRows={4}
            disabled={loading}
          />
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Tooltip title={voiceSupported ? '' : 'Voice not supported in this browser'}>
              <span>
                <Button
                  variant="outlined"
                  onClick={handleMicToggle}
                  disabled={!voiceSupported}
                  startIcon={listening ? <MicOffIcon /> : <MicIcon />}
                >
                  {listening ? 'Stop' : 'Mic'}
                </Button>
              </span>
            </Tooltip>
            <Button variant="contained" onClick={handleSend} disabled={loading || !input.trim()}>
              {loading ? <CircularProgress size={20} color="inherit" /> : 'Send'}
            </Button>
          </Box>
        </Box>
        {!voiceSupported && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            Voice not supported in this browser.
          </Typography>
        )}
      </Paper>
    </Container>
  );
}
