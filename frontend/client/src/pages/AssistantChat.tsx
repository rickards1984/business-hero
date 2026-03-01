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

export default function AssistantChat() {
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
    <Container maxWidth="md" sx={{ py: 3, minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Button
          variant="text"
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/app')}
          sx={{ color: 'text.secondary' }}
        >
          Back
        </Button>
        {(messages.length > 0 || realtimeMode) && (
          <Button
            variant="text"
            onClick={() => {
              setMessages([]);
              setConversationId(null);
              setRealtimeMode(false);
            }}
            sx={{ color: 'text.secondary' }}
          >
            New conversation
          </Button>
        )}
      </Box>

      {/* Main Content */}
      {realtimeMode ? (
        /* Realtime Voice Mode - Full screen experience */
        <Box sx={{ 
          flex: 1,
          display: 'flex', 
          flexDirection: 'column', 
          alignItems: 'center', 
          justifyContent: 'center',
          minHeight: '70vh',
        }}>
          <RealtimeVoice 
            onTranscript={(text, isUser) => {
              setMessages(prev => [...prev, {
                role: isUser ? 'user' : 'assistant',
                content: text
              }]);
            }}
            onClose={() => setRealtimeMode(false)}
          />
          
          {/* Transcript below */}
          {messages.length > 0 && (
            <Paper sx={{ 
              mt: 4, 
              p: 2, 
              maxHeight: 200, 
              overflow: 'auto', 
              width: '100%',
              maxWidth: 500,
              bgcolor: 'grey.50'
            }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                Transcript
              </Typography>
              {messages.slice(-6).map((msg, i) => (
                <Typography 
                  key={i} 
                  variant="body2" 
                  sx={{ 
                    mb: 0.5,
                    color: msg.role === 'user' ? 'primary.main' : 'text.primary',
                    fontStyle: msg.role === 'user' ? 'italic' : 'normal'
                  }}
                >
                  {msg.role === 'user' ? 'You: ' : 'Aria: '}{msg.content.slice(0, 100)}{msg.content.length > 100 ? '...' : ''}
                </Typography>
              ))}
            </Paper>
          )}
        </Box>
      ) : messages.length === 0 ? (
        /* Welcome Screen - Sleek and modern */
        <Box sx={{ 
          flex: 1,
          display: 'flex', 
          flexDirection: 'column', 
          alignItems: 'center', 
          justifyContent: 'center',
          minHeight: '60vh',
          textAlign: 'center',
          px: 3
        }}>
          {/* Aria's Avatar with glow effect */}
          <Box sx={{ position: 'relative', mb: 4 }}>
            <Box sx={{ 
              width: 140, 
              height: 140, 
              borderRadius: '50%', 
              overflow: 'hidden',
              boxShadow: '0 0 40px rgba(99, 102, 241, 0.4)',
              border: '3px solid rgba(99, 102, 241, 0.3)',
              animation: 'avatarPulse 3s ease-in-out infinite',
              '@keyframes avatarPulse': {
                '0%, 100%': { 
                  boxShadow: '0 0 40px rgba(99, 102, 241, 0.4)',
                  transform: 'scale(1)'
                },
                '50%': { 
                  boxShadow: '0 0 60px rgba(99, 102, 241, 0.6)',
                  transform: 'scale(1.02)'
                },
              }
            }}>
              <img 
                src="/aria-avatar.png" 
                alt="Aria" 
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />
            </Box>
          </Box>
          
          <Typography variant="h4" fontWeight={700} sx={{ 
            mb: 1,
            background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
            backgroundClip: 'text',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>
            Meet Aria
          </Typography>
          
          <Typography variant="body1" color="text.secondary" sx={{ mb: 4, maxWidth: 400 }}>
            Your AI business assistant. I can help with emails, tasks, calls, invoices, and finances.
          </Typography>
          
          {/* Main CTA - Talk to Aria button */}
          <Button
            variant="contained"
            size="large"
            onClick={() => setRealtimeMode(true)}
            startIcon={<MicIcon />}
            sx={{
              px: 5,
              py: 2,
              borderRadius: '50px',
              fontSize: '1.1rem',
              fontWeight: 600,
              background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
              boxShadow: '0 8px 32px rgba(99, 102, 241, 0.35)',
              textTransform: 'none',
              mb: 3,
              '&:hover': {
                background: 'linear-gradient(135deg, #5558e3 0%, #7c4fe0 100%)',
                boxShadow: '0 12px 40px rgba(99, 102, 241, 0.45)',
                transform: 'translateY(-2px)',
              },
              transition: 'all 0.3s ease'
            }}
          >
            Talk to Aria
          </Button>
          
          <Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>
            or type a message below
          </Typography>
          
          {/* Quick action chips */}
          <Box sx={{ 
            display: 'flex', 
            flexWrap: 'wrap', 
            gap: 1.5, 
            justifyContent: 'center',
            maxWidth: 500
          }}>
            {QUICK_ACTIONS.map((action) => (
              <Chip
                key={action.label}
                icon={action.icon}
                label={action.label}
                onClick={() => handleQuickAction(action.action)}
                clickable
                sx={{
                  px: 1,
                  py: 2.5,
                  borderRadius: '20px',
                  border: '1px solid',
                  borderColor: 'divider',
                  bgcolor: 'background.paper',
                  '&:hover': {
                    bgcolor: 'action.hover',
                    borderColor: 'primary.main',
                  }
                }}
              />
            ))}
          </Box>
        </Box>
      ) : (
        /* Chat Messages View */
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          {/* Quick actions bar */}
          <Box sx={{ 
            display: 'flex', 
            flexWrap: 'wrap', 
            gap: 1, 
            pb: 2,
            mb: 2,
            borderBottom: 1,
            borderColor: 'divider'
          }}>
            {QUICK_ACTIONS.map((action) => (
              <Chip
                key={action.label}
                icon={action.icon}
                label={action.label}
                onClick={() => handleQuickAction(action.action)}
                variant="outlined"
                size="small"
                sx={{ cursor: 'pointer' }}
              />
            ))}
            <Box sx={{ flex: 1 }} />
            <Button
              variant="outlined"
              size="small"
              startIcon={<MicIcon />}
              onClick={() => setRealtimeMode(true)}
              sx={{ borderRadius: '20px' }}
            >
              Voice
            </Button>
          </Box>
          
          {/* Messages */}
          <Paper sx={{ flex: 1, p: 2, mb: 2, overflow: 'auto', maxHeight: '50vh', bgcolor: 'grey.50' }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {messages.map((message, idx) => (
                <Box
                  key={`${message.role}-${idx}`}
                  sx={{
                    alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start',
                    bgcolor: message.role === 'user' ? 'primary.main' : 'white',
                    color: message.role === 'user' ? 'primary.contrastText' : 'text.primary',
                    px: 2.5,
                    py: 1.5,
                    borderRadius: message.role === 'user' ? '20px 20px 4px 20px' : '20px 20px 20px 4px',
                    maxWidth: '85%',
                    boxShadow: 1,
                  }}
                >
                  {message.role === 'assistant' ? (
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  ) : (
                    <Typography variant="body2">{message.content}</Typography>
                  )}
                </Box>
              ))}
              {loading && (
                <Box sx={{ alignSelf: 'flex-start', p: 2 }}>
                  <CircularProgress size={20} />
                </Box>
              )}
              <div ref={messagesEndRef} />
            </Box>
          </Paper>
        </Box>
      )}

      {/* Error display */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {/* Input area - show when not in realtime mode */}
      {!realtimeMode && (
        <Paper sx={{ p: 2, mt: 'auto' }}>
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-end' }}>
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
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: '24px',
                }
              }}
            />
            <Button 
              variant="contained" 
              onClick={handleSend} 
              disabled={loading || !input.trim()}
              sx={{ 
                minWidth: 'auto',
                width: 48,
                height: 48,
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
              }}
            >
              {loading ? <CircularProgress size={20} color="inherit" /> : <SendIcon />}
            </Button>
          </Box>
        </Paper>
      )}
    </Container>
  );
}
