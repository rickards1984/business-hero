import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Paper,
  TextField,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import MicIcon from '@mui/icons-material/Mic';
import EmailIcon from '@mui/icons-material/Email';
import TaskIcon from '@mui/icons-material/Task';
import PhoneIcon from '@mui/icons-material/Phone';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import ReceiptIcon from '@mui/icons-material/Receipt';
import SendIcon from '@mui/icons-material/Send';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';
import RealtimeVoice from '@/components/RealtimeVoice';

type ChatRole = 'user' | 'assistant';

interface ChatMessage {
  role: ChatRole;
  content: string;
}

const QUICK_ACTIONS = [
  { icon: <EmailIcon fontSize="small" />, label: "Check emails", action: "Give me a summary of my emails today" },
  { icon: <CalendarTodayIcon fontSize="small" />, label: "Today's schedule", action: "What's on my calendar today?" },
  { icon: <TaskIcon fontSize="small" />, label: "Review tasks", action: "What tasks should I focus on today?" },
  { icon: <PhoneIcon fontSize="small" />, label: "Recent calls", action: "Summarise my recent calls" },
  { icon: <ReceiptIcon fontSize="small" />, label: "Invoices", action: "Please review my invoices and give me a summary of what's outstanding, any that are overdue, and recent payments received." },
  { icon: <AccountBalanceIcon fontSize="small" />, label: "Financials", action: "Please provide a detailed summary of my business financials including income, expenses, profit/loss, and spending breakdown by category." },
];

interface AssistantChatProps {
  embedded?: boolean;
}

export default function AssistantChat({ embedded = false }: AssistantChatProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user, loading: authLoading } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [realtimeMode, setRealtimeMode] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [authLoading, user, navigate]);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-send prompt from URL query param (e.g. from "Ask Aria" button)
  const promptHandled = useRef(false);
  useEffect(() => {
    if (promptHandled.current || authLoading || !user) return;
    const prompt = searchParams.get('prompt');
    if (prompt) {
      promptHandled.current = true;
      setSearchParams({}, { replace: true });
      setTimeout(() => handleSendMessage(prompt), 300);
    }
  }, [authLoading, user]);

  const handleSendMessage = async (messageText: string) => {
    const message = messageText.trim();
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

  const handleSend = () => {
    handleSendMessage(input);
  };

  const handleQuickAction = (text: string) => {
    handleSendMessage(text);
  };

  if (authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box
      sx={{
        minHeight: embedded ? 'auto' : '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: embedded ? 'transparent' : 'linear-gradient(180deg, hsl(var(--background)) 0%, rgba(139,92,246,0.04) 30%, hsl(var(--background)) 100%)',
      }}
    >
      <Container maxWidth="md" sx={{ py: embedded ? 0 : 3, flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          {!embedded && (
            <Button
              variant="text"
              startIcon={<ArrowBackIcon />}
              onClick={() => navigate('/app')}
              sx={{ color: 'hsl(var(--muted-foreground))', fontWeight: 500, fontSize: '0.8125rem' }}
            >
              Back
            </Button>
          )}
          {(messages.length > 0 || realtimeMode) && (
            <Button
              variant="text"
              onClick={() => {
                setMessages([]);
                setConversationId(null);
                setRealtimeMode(false);
              }}
              sx={{ color: 'hsl(var(--muted-foreground))', fontWeight: 500, fontSize: '0.8125rem' }}
            >
              New conversation
            </Button>
          )}
        </Box>

        {/* Main Content */}
        {realtimeMode ? (
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '70vh' }}>
            <RealtimeVoice
              onTranscript={(text, isUser) => {
                setMessages(prev => [...prev, { role: isUser ? 'user' : 'assistant', content: text }]);
              }}
              onClose={() => setRealtimeMode(false)}
            />
            {messages.length > 0 && (
              <Paper sx={{ mt: 4, p: 2, maxHeight: 200, overflow: 'auto', width: '100%', maxWidth: 500, bgcolor: 'var(--glass-bg)', border: '1px solid var(--glass-border)' }}>
                <Typography variant="caption" sx={{ mb: 1, display: 'block', color: 'hsl(var(--muted-foreground))' }}>Transcript</Typography>
                {messages.slice(-6).map((msg, i) => (
                  <Typography key={i} variant="body2" sx={{ mb: 0.5, color: msg.role === 'user' ? '#a78bfa' : 'hsl(var(--foreground))', fontStyle: msg.role === 'user' ? 'italic' : 'normal' }}>
                    {msg.role === 'user' ? 'You: ' : 'Aria: '}{msg.content.slice(0, 100)}{msg.content.length > 100 ? '...' : ''}
                  </Typography>
                ))}
              </Paper>
            )}
          </Box>
        ) : messages.length === 0 ? (
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', textAlign: 'center', px: 3 }}>
            {/* Aria Avatar with breathing ring */}
            <Box sx={{ position: 'relative', width: 120, height: 120, mb: 4 }}>
              <Box
                sx={{
                  position: 'absolute',
                  inset: -6,
                  borderRadius: '50%',
                  border: '2px solid var(--color-aria-300)',
                  animation: 'avatarBreathing 4s ease-in-out infinite',
                  '@keyframes avatarBreathing': {
                    '0%, 100%': { transform: 'scale(1)', borderColor: 'var(--color-aria-300)', boxShadow: '0 0 0 0 rgba(139,92,246,0)' },
                    '50%': { transform: 'scale(1.03)', borderColor: 'var(--color-aria-400)', boxShadow: '0 0 20px 5px rgba(139,92,246,0.1)' },
                  },
                }}
              />
              <img
                src="/aria-avatar.png"
                alt="Aria"
                style={{ width: 120, height: 120, borderRadius: '50%', objectFit: 'cover', boxShadow: '0 8px 30px rgba(139,92,246,0.2)', position: 'relative' }}
              />
            </Box>

            <Typography
              sx={{
                fontSize: '1.5rem',
                fontWeight: 800,
                mb: 1,
                background: 'linear-gradient(135deg, var(--color-aria-600) 0%, var(--color-aria-400) 100%)',
                backgroundClip: 'text',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}
            >
              Meet Aria
            </Typography>

            <Typography sx={{ fontSize: '0.875rem', color: 'hsl(var(--muted-foreground))', mb: 5, maxWidth: 360 }}>
              Your AI business assistant. I can help with emails, tasks, calls, invoices, and finances.
            </Typography>

            <Button
              variant="contained"
              size="large"
              onClick={() => setRealtimeMode(true)}
              startIcon={<MicIcon />}
              sx={{
                px: 5,
                py: 1.5,
                borderRadius: '9999px',
                fontSize: '0.9375rem',
                fontWeight: 600,
                background: 'linear-gradient(135deg, var(--color-aria-500) 0%, var(--color-aria-600) 100%)',
                boxShadow: '0 4px 20px rgba(139,92,246,0.35)',
                textTransform: 'none',
                height: 52,
                mb: 2,
                '&:hover': {
                  background: 'linear-gradient(135deg, var(--color-aria-600) 0%, #6D28D9 100%)',
                  boxShadow: '0 8px 30px rgba(139,92,246,0.45)',
                  transform: 'translateY(-2px)',
                },
                transition: 'all 200ms cubic-bezier(0.4,0,0.2,1)',
              }}
            >
              Talk to Aria
            </Button>

            <Typography sx={{ fontSize: '0.8125rem', color: 'rgba(232, 230, 225, 0.4)', mb: 4 }}>
              or type a message below
            </Typography>

            {/* Quick action chips */}
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, justifyContent: 'center', maxWidth: 500 }}>
              {QUICK_ACTIONS.map((action) => (
                <Chip
                  key={action.label}
                  icon={action.icon}
                  label={action.label}
                  onClick={() => handleQuickAction(action.action)}
                  clickable
                  sx={{
                    px: 1.5,
                    py: 2.5,
                    borderRadius: '9999px',
                    border: '1px solid var(--glass-border)',
                    bgcolor: 'var(--glass-bg)',
                    color: 'hsl(var(--foreground))',
                    fontSize: '0.8125rem',
                    fontWeight: 500,
                    boxShadow: 'var(--shadow-xs)',
                    transition: 'all 150ms cubic-bezier(0.4,0,0.2,1)',
                    '& .MuiChip-icon': { color: 'inherit' },
                    '&:hover': {
                      borderColor: 'var(--color-aria-300)',
                      bgcolor: 'rgba(255,255,255,0.1)',
                      color: '#a78bfa',
                      boxShadow: 'var(--shadow-sm)',
                      transform: 'translateY(-1px)',
                    },
                  }}
                />
              ))}
            </Box>
          </Box>
        ) : (
          /* Chat Messages View */
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, pb: 2, mb: 2, borderBottom: '1px solid var(--glass-border)' }}>
              {QUICK_ACTIONS.map((action) => (
                <Chip
                  key={action.label}
                  icon={action.icon}
                  label={action.label}
                  onClick={() => handleQuickAction(action.action)}
                  variant="outlined"
                  size="small"
                  sx={{
                    cursor: 'pointer',
                    borderColor: 'var(--glass-border)',
                    color: 'hsl(var(--foreground))',
                    '& .MuiChip-icon': { color: 'inherit' },
                    '&:hover': { borderColor: 'rgba(124,92,252,0.4)', bgcolor: 'rgba(124,92,252,0.08)' },
                  }}
                />
              ))}
              <Box sx={{ flex: 1 }} />
              <Button
                variant="outlined"
                size="small"
                startIcon={<MicIcon />}
                onClick={() => setRealtimeMode(true)}
                sx={{
                  borderRadius: '9999px',
                  borderColor: 'rgba(124,92,252,0.25)',
                  color: '#a78bfa',
                  '&:hover': { borderColor: 'rgba(124,92,252,0.5)', bgcolor: 'rgba(124,92,252,0.08)' },
                }}
              >
                Voice
              </Button>
            </Box>

            {/* Messages */}
            <Box sx={{ flex: 1, mb: 2, overflow: 'auto', maxHeight: '55vh', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {messages.map((message, idx) => (
                <Box
                  key={`${message.role}-${idx}`}
                  sx={{
                    alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start',
                    bgcolor: message.role === 'user' ? '#7C3AED' : 'var(--glass-bg)',
                    color: message.role === 'user' ? 'white' : 'hsl(var(--foreground))',
                    px: 2.5,
                    py: 1.5,
                    borderRadius: message.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                    maxWidth: '80%',
                    boxShadow: message.role === 'user' ? 'var(--shadow-md)' : 'var(--shadow-xs)',
                    border: message.role === 'assistant' ? '1px solid var(--glass-border)' : 'none',
                    fontSize: '0.875rem',
                    lineHeight: 1.625,
                    animation: 'messageAppear 200ms ease-out',
                    '@keyframes messageAppear': {
                      from: { opacity: 0, transform: 'translateY(8px)' },
                      to: { opacity: 1, transform: 'translateY(0)' },
                    },
                  }}
                >
                  {message.role === 'assistant' ? (
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  ) : (
                    <Typography variant="body2" sx={{ color: 'inherit' }}>{message.content}</Typography>
                  )}
                </Box>
              ))}
              {loading && (
                <Box sx={{ alignSelf: 'flex-start', p: 2 }}>
                  <CircularProgress size={20} sx={{ color: 'var(--color-aria-500)' }} />
                </Box>
              )}
              <div ref={messagesEndRef} />
            </Box>
          </Box>
        )}

        {/* Error display */}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        {/* Input area */}
        {!realtimeMode && (
          <Box
            sx={{
              position: 'sticky',
              bottom: 0,
              pt: 2,
              pb: 2,
              mt: 'auto',
              background: 'linear-gradient(180deg, transparent 0%, hsl(var(--background)) 30%)',
            }}
          >
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                maxWidth: 700,
                mx: 'auto',
                p: '8px 8px 8px 20px',
                bgcolor: 'var(--glass-bg)',
                border: '1px solid var(--glass-border)',
                borderRadius: '9999px',
                boxShadow: 'var(--shadow-md)',
                transition: 'all 150ms cubic-bezier(0.4,0,0.2,1)',
                '&:focus-within': {
                  borderColor: 'var(--color-aria-400)',
                  boxShadow: '0 0 0 3px rgba(139,92,246,0.1), var(--shadow-md)',
                },
              }}
            >
              <TextField
                inputRef={inputRef}
                fullWidth
                placeholder="Ask Aria anything..."
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
                variant="standard"
                InputProps={{ disableUnderline: true }}
                sx={{
                  '& .MuiInputBase-root': { fontSize: '0.875rem', color: 'hsl(var(--foreground))' },
                  '& .MuiInputBase-input::placeholder': { color: 'rgba(232,230,225,0.4)', opacity: 1 },
                }}
              />
              <Button
                variant="contained"
                onClick={handleSend}
                disabled={loading || !input.trim()}
                sx={{
                  minWidth: 'auto',
                  width: 40,
                  height: 40,
                  borderRadius: '50%',
                  flexShrink: 0,
                  background: 'var(--color-aria-500)',
                  boxShadow: 'none',
                  '&:hover': { background: 'var(--color-aria-600)', transform: 'scale(1.05)' },
                  '&.Mui-disabled': { background: 'rgba(255,255,255,0.08)' },
                  transition: 'all 150ms cubic-bezier(0.4,0,0.2,1)',
                }}
              >
                {loading ? <CircularProgress size={18} color="inherit" /> : <SendIcon sx={{ fontSize: 18 }} />}
              </Button>
            </Box>
          </Box>
        )}
      </Container>
    </Box>
  );
}
