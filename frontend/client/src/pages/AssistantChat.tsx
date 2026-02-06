import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  FormControlLabel,
  Paper,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { keyframes } from '@mui/system';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import MicIcon from '@mui/icons-material/Mic';
import MicOffIcon from '@mui/icons-material/MicOff';
import EmailIcon from '@mui/icons-material/Email';
import TaskIcon from '@mui/icons-material/Task';
import PhoneIcon from '@mui/icons-material/Phone';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import { Card } from '@mui/material';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';

type ChatRole = 'user' | 'assistant';

interface ChatMessage {
  role: ChatRole;
  content: string;
}

const QUICK_ACTIONS = [
  { icon: <EmailIcon />, label: "Check my emails", shortLabel: "Emails", action: "Give me a summary of my emails today" },
  { icon: <CalendarTodayIcon />, label: "Today's schedule", shortLabel: "Schedule", action: "What's on my calendar today?" },
  { icon: <TaskIcon />, label: "Review tasks", shortLabel: "Tasks", action: "What tasks should I focus on today?" },
  { icon: <PhoneIcon />, label: "Recent calls", shortLabel: "Calls", action: "Summarise my recent calls" },
  { icon: <AccountBalanceIcon />, label: "Summarise financials", shortLabel: "Financials", action: "Please provide a detailed summary of my business financials. Include: 1) Total income and gross revenue, 2) Total expenses and net profit/loss, 3) Breakdown of expenses by category showing where most money is being spent, 4) Flag any uncategorized transactions that need attention, 5) Suggestions for potential cost savings to improve profitability. After the summary, please offer to go into more detail on any specific area I'm interested in." },
];

const pulseAnimation = keyframes`
  0% { box-shadow: 0 0 0 0 rgba(244, 67, 54, 0.7); }
  70% { box-shadow: 0 0 0 10px rgba(244, 67, 54, 0); }
  100% { box-shadow: 0 0 0 0 rgba(244, 67, 54, 0); }
`;

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
  const [usePremiumVoice, setUsePremiumVoice] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<any>(null);
  const lastSpokenIndexRef = useRef<number>(-1);
  const pendingVoiceMessageRef = useRef<string | null>(null);
  const speakRepliesRef = useRef(speakReplies);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Keep speakRepliesRef in sync
  useEffect(() => {
    speakRepliesRef.current = speakReplies;
  }, [speakReplies]);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [authLoading, user, navigate]);

  // Load voices on mount (Chrome needs this)
  useEffect(() => {
    if (window.speechSynthesis) {
      window.speechSynthesis.getVoices();
      window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.getVoices();
      };
    }
  }, []);

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
        if (speakRepliesRef.current) {
          // In voice mode, auto-send after recognition
          pendingVoiceMessageRef.current = transcript;
          setInput(transcript);
        } else {
          setInput(transcript);
          inputRef.current?.focus();
        }
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

  // Handle pending voice message (auto-send after speech recognition)
  useEffect(() => {
    if (pendingVoiceMessageRef.current && !loading && !listening) {
      const message = pendingVoiceMessageRef.current;
      pendingVoiceMessageRef.current = null;
      // Small delay to ensure UI updates
      setTimeout(() => {
        handleSendMessage(message);
      }, 100);
    }
  }, [listening, loading]);

  useEffect(() => {
    if (!speakReplies) {
      window.speechSynthesis?.cancel();
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setSpeaking(false);
    }
  }, [speakReplies]);

  // Speak with OpenAI TTS (premium voice)
  const speakWithOpenAI = async (text: string) => {
    try {
      setSpeaking(true);
      
      const response = await apiRequest('POST', '/v1/tts', {
        text: text,
        voice: 'nova'  // Natural female voice
      });
      
      if (!response.ok) {
        throw new Error('TTS request failed');
      }
      
      const data = await response.json();
      const audioData = data.audio;
      
      // Create audio element and play
      const audio = new Audio(`data:audio/mp3;base64,${audioData}`);
      audioRef.current = audio;
      
      audio.onended = () => {
        setSpeaking(false);
        audioRef.current = null;
        // Auto-listen after speaking if in voice mode
        if (speakRepliesRef.current && recognitionRef.current) {
          setTimeout(() => {
            try {
              recognitionRef.current.start();
              setListening(true);
            } catch (e) {
              // Ignore if already listening
            }
          }, 500);
        }
      };
      
      audio.onerror = () => {
        setSpeaking(false);
        audioRef.current = null;
        // Fallback to browser TTS
        speakWithBrowser(text);
      };
      
      await audio.play();
      
    } catch (error) {
      console.error('OpenAI TTS error:', error);
      setSpeaking(false);
      // Fallback to browser TTS
      speakWithBrowser(text);
    }
  };

  // Speak with browser TTS (fallback)
  const speakWithBrowser = (text: string) => {
    if (!window.speechSynthesis) {
      setSpeaking(false);
      return;
    }
    
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-GB';
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    
    const voices = window.speechSynthesis.getVoices();
    const preferredVoices = [
      'Google UK English Female',
      'Google UK English Male', 
      'Microsoft Libby Online (Natural)',
      'Microsoft Ryan Online (Natural)',
      'Samantha',
      'Daniel',
    ];
    
    let selectedVoice = null;
    for (const preferred of preferredVoices) {
      selectedVoice = voices.find(v => v.name.includes(preferred));
      if (selectedVoice) break;
    }
    
    if (!selectedVoice) {
      selectedVoice = voices.find(v => v.lang === 'en-GB') || 
                      voices.find(v => v.lang.startsWith('en'));
    }
    
    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }
    
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => {
      setSpeaking(false);
      if (speakRepliesRef.current && recognitionRef.current) {
        setTimeout(() => {
          try {
            recognitionRef.current.start();
            setListening(true);
          } catch (e) {}
        }, 500);
      }
    };
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  };

  // Speak new assistant messages
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
    
    // Use OpenAI TTS for premium voice, otherwise browser TTS
    if (usePremiumVoice) {
      speakWithOpenAI(lastMessage.content);
    } else {
      speakWithBrowser(lastMessage.content);
    }
  }, [messages, speakReplies, usePremiumVoice]);

  const handleSendMessage = async (messageText: string) => {
    const message = messageText.trim();
    if (!message || loading) return;

    setError('');
    setLoading(true);
    setMessages((prev) => [...prev, { role: 'user', content: message }]);
    setInput('');

    // Immediate voice feedback while processing
    if (speakReplies && window.speechSynthesis) {
      const lowerMessage = message.toLowerCase();
      let acknowledgment = "One moment...";
      
      if (lowerMessage.includes('email') || lowerMessage.includes('inbox')) {
        acknowledgment = "Let me check your emails...";
      } else if (lowerMessage.includes('calendar') || lowerMessage.includes('schedule') || lowerMessage.includes('meeting')) {
        acknowledgment = "Let me look at your calendar...";
      } else if (lowerMessage.includes('call') || lowerMessage.includes('calls')) {
        acknowledgment = "Let me pull up your calls...";
      } else if (lowerMessage.includes('task') || lowerMessage.includes('tasks') || lowerMessage.includes('to do') || lowerMessage.includes('todo')) {
        acknowledgment = "Let me check your tasks...";
      } else if (lowerMessage.includes('invoice') || lowerMessage.includes('payment')) {
        acknowledgment = "Let me look at your invoices...";
      } else if (lowerMessage.includes('brief') || lowerMessage.includes('summary') || lowerMessage.includes('today') || lowerMessage.includes('morning')) {
        acknowledgment = "Let me pull together your briefing...";
      } else if (lowerMessage.includes('send') && lowerMessage.includes('email')) {
        acknowledgment = "I'll draft that email for you...";
      }
      
      // Speak acknowledgment immediately
      const ack = new SpeechSynthesisUtterance(acknowledgment);
      ack.lang = 'en-GB';
      ack.rate = 1.1; // Slightly faster for acknowledgment
      
      // Use the same voice selection logic
      const voices = window.speechSynthesis.getVoices();
      const preferredVoices = ['Google UK English Female', 'Google UK English Male', 'Microsoft Libby', 'Microsoft Ryan', 'Samantha', 'Daniel'];
      let selectedVoice = null;
      for (const preferred of preferredVoices) {
        selectedVoice = voices.find(v => v.name.includes(preferred));
        if (selectedVoice) break;
      }
      if (!selectedVoice) {
        selectedVoice = voices.find(v => v.lang === 'en-GB') || voices.find(v => v.lang.startsWith('en'));
      }
      if (selectedVoice) {
        ack.voice = selectedVoice;
      }
      
      window.speechSynthesis.speak(ack);
    }

    try {
      const payload: Record<string, any> = { 
        message,
        voice_mode: speakReplies,
      };
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
      // Speak error in voice mode
      if (speakReplies && window.speechSynthesis) {
        const errorUtterance = new SpeechSynthesisUtterance("Sorry, I had trouble with that. Please try again.");
        errorUtterance.lang = 'en-GB';
        window.speechSynthesis.speak(errorUtterance);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSend = () => {
    handleSendMessage(input);
  };

  const handleQuickAction = (text: string) => {
    setInput(text);
    // Auto-send the quick action
    handleSendMessage(text);
  };

  const handleMicToggle = () => {
    if (!voiceSupported || !recognitionRef.current) return;
    
    // If AI is speaking, stop it first (allows interruption)
    if (speaking) {
      window.speechSynthesis?.cancel();
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setSpeaking(false);
    }
    
    if (listening) {
      recognitionRef.current.stop();
      setListening(false);
    } else {
      setError('');
      try {
        recognitionRef.current.start();
        setListening(true);
      } catch (e) {
        // Ignore if already started
      }
    }
  };

  const handleStopSpeaking = () => {
    window.speechSynthesis?.cancel();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
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
          sx={{ width: { xs: '100%', sm: 'auto' } }}
        >
          Back to Dashboard
        </Button>
      </Box>
      {/* Voice controls */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <FormControlLabel
            control={
              <Switch
                checked={speakReplies}
                onChange={(event) => setSpeakReplies(event.target.checked)}
              />
            }
            label="Voice conversation mode"
          />
          {speakReplies && (
            <FormControlLabel
              control={
                <Switch
                  checked={usePremiumVoice}
                  onChange={(event) => setUsePremiumVoice(event.target.checked)}
                  size="small"
                />
              }
              label={<Typography variant="body2">Premium voice</Typography>}
            />
          )}
          <Typography variant="caption" color="text.secondary">
            {speakReplies 
              ? (usePremiumVoice ? 'Using OpenAI natural voice' : 'Using browser voice') 
              : 'Text-only mode'}
          </Typography>
          {speaking && (
            <Button variant="outlined" size="small" onClick={handleStopSpeaking}>
              Stop speaking
            </Button>
          )}
        </Box>
      </Paper>

      <Paper sx={{ p: 3, mb: 2, minHeight: 400 }}>
        {messages.length === 0 ? (
          /* Modern empty state */
          <Box sx={{ 
            display: 'flex', 
            flexDirection: 'column', 
            alignItems: 'center', 
            justifyContent: 'center',
            height: '100%',
            minHeight: 350,
            textAlign: 'center',
            py: 4
          }}>
            {/* Animated AI icon */}
            <Box sx={{ 
              width: 80, 
              height: 80, 
              borderRadius: '50%', 
              bgcolor: 'primary.light',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              mb: 3,
              animation: 'pulse 2s infinite',
              '@keyframes pulse': {
                '0%': { boxShadow: '0 0 0 0 rgba(25, 118, 210, 0.4)' },
                '70%': { boxShadow: '0 0 0 15px rgba(25, 118, 210, 0)' },
                '100%': { boxShadow: '0 0 0 0 rgba(25, 118, 210, 0)' },
              }
            }}>
              <SmartToyIcon sx={{ fontSize: 40, color: 'primary.main' }} />
            </Box>
            
            <Typography variant="h5" fontWeight={600} gutterBottom>
              Hi! I'm your AI Admin
            </Typography>
            <Typography variant="body1" color="text.secondary" sx={{ mb: 4, maxWidth: 400 }}>
              I can help you manage emails, tasks, calls, and invoices. Try asking me something or use a quick action below.
            </Typography>
            
            {/* Quick action cards */}
            <Box sx={{ 
              display: 'grid', 
              gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' }, 
              gap: 2,
              maxWidth: 500,
              width: '100%'
            }}>
              {QUICK_ACTIONS.map((action, index) => (
                <Card 
                  key={index}
                  sx={{ 
                    p: 2, 
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    '&:hover': { 
                      transform: 'translateY(-2px)',
                      boxShadow: 3,
                      borderColor: 'primary.main'
                    },
                    border: '1px solid',
                    borderColor: 'divider'
                  }}
                  onClick={() => handleQuickAction(action.action)}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                    <Box sx={{ color: 'primary.main' }}>{action.icon}</Box>
                    <Typography variant="body2" fontWeight={500}>
                      {action.label}
                    </Typography>
                  </Box>
                </Card>
              ))}
            </Box>
            
            {/* Voice mode hint */}
            <Box sx={{ mt: 4, display: 'flex', alignItems: 'center', gap: 1, color: 'text.secondary' }}>
              <MicIcon fontSize="small" />
              <Typography variant="caption">
                Toggle voice mode above for hands-free conversation
              </Typography>
            </Box>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {/* Compact quick actions - always visible when conversation started */}
            <Box sx={{ 
              display: 'flex', 
              flexWrap: 'wrap', 
              gap: 1, 
              pb: 2,
              borderBottom: 1,
              borderColor: 'divider'
            }}>
              {QUICK_ACTIONS.map((action, index) => (
                <Chip
                  key={index}
                  icon={action.icon}
                  label={action.shortLabel}
                  onClick={() => handleQuickAction(action.action)}
                  variant="outlined"
                  color="primary"
                  size="small"
                  sx={{ cursor: 'pointer' }}
                />
              ))}
            </Box>
            
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
            <Tooltip title={voiceSupported ? (listening ? 'Stop listening' : (speaking ? 'Interrupt and speak' : 'Start voice input')) : 'Voice not supported in this browser'}>
              <span>
                <Button
                  variant={listening ? "contained" : "outlined"}
                  color={listening ? "error" : "primary"}
                  onClick={handleMicToggle}
                  disabled={!voiceSupported || loading}
                  startIcon={listening ? <MicOffIcon /> : <MicIcon />}
                  sx={listening ? { animation: `${pulseAnimation} 1.5s infinite` } : {}}
                >
                  {listening ? 'Listening...' : 'Mic'}
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
