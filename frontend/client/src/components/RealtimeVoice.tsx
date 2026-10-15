import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  Box,
  IconButton,
  Typography,
  Button,
  Fade,
  CircularProgress,
} from '@mui/material';
import {
  Mic as MicIcon,
  MicOff as MicOffIcon,
  CallEnd as CallEndIcon,
  VolumeUp as VolumeUpIcon,
  VolumeOff as VolumeOffIcon,
} from '@mui/icons-material';
import { supabase } from '@/lib/supabase';
import ApprovalCard, { Proposal } from '@/components/ApprovalCard';
import { config } from '@/config/env';

interface RealtimeVoiceProps {
  onTranscript?: (text: string, isUser: boolean) => void;
  onClose?: () => void;
}

export const RealtimeVoice: React.FC<RealtimeVoiceProps> = ({ onTranscript, onClose }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [status, setStatus] = useState<string>('Tap to connect');
  const [currentTranscript, setCurrentTranscript] = useState('');
  const [isMuted, setIsMuted] = useState(false);
  const [quietMode, setQuietMode] = useState(false);
  // NS-V1 (D18): drafts Aria prepares while speaking, shown for a tap.
  const [proposals, setProposals] = useState<Proposal[]>([]);
  
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const audioQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingRef = useRef(false);
  const isMutedRef = useRef(false);
  // Why the session ended, kept so the normal close doesn't overwrite it.
  const endReasonRef = useRef<string | null>(null);
  // NS-V2: start-up feedback. The tap is acknowledged at once, repeat taps
  // are ignored, and the microphone is readied WHILE the server prepares.
  const [connecting, setConnecting] = useState(false);
  const progressTimersRef = useRef<number[]>([]);
  const micPromiseRef = useRef<Promise<MediaStream> | null>(null);
  // Set on unmount: a start-up still in flight stops instead of opening a
  // socket for a page that is gone (Codex NS-V2 review).
  const unmountedRef = useRef(false);

  const clearProgress = () => {
    progressTimersRef.current.forEach((t) => window.clearTimeout(t));
    progressTimersRef.current = [];
  };

  const releaseEarlyMic = () => {
    // A microphone readied for a session that never started is released.
    micPromiseRef.current?.then((stream) => {
      if (mediaStreamRef.current !== stream) stream.getTracks().forEach((t) => t.stop());
    }).catch(() => undefined);
    micPromiseRef.current = null;
  };

  // Keep muted ref in sync with state
  useEffect(() => {
    isMutedRef.current = isMuted;
  }, [isMuted]);

  // Convert Float32 to Int16 PCM
  const floatTo16BitPCM = (float32Array: Float32Array): ArrayBuffer => {
    const buffer = new ArrayBuffer(float32Array.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buffer;
  };

  // Play audio from queue
  const playNextAudio = useCallback(async () => {
    if (isPlayingRef.current || audioQueueRef.current.length === 0) return;
    
    isPlayingRef.current = true;
    setIsSpeaking(true);
    
    const audioData = audioQueueRef.current.shift()!;
    const audioContext = audioContextRef.current || new AudioContext({ sampleRate: 24000 });
    audioContextRef.current = audioContext;
    
    try {
      // Convert PCM16 to Float32
      const int16Array = new Int16Array(audioData);
      const float32Array = new Float32Array(int16Array.length);
      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768;
      }
      
      const audioBuffer = audioContext.createBuffer(1, float32Array.length, 24000);
      audioBuffer.getChannelData(0).set(float32Array);
      
      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioContext.destination);
      
      source.onended = () => {
        isPlayingRef.current = false;
        if (audioQueueRef.current.length > 0) {
          playNextAudio();
        } else {
          setIsSpeaking(false);
        }
      };
      
      source.start();
    } catch (e) {
      console.error('Audio playback error:', e);
      isPlayingRef.current = false;
      setIsSpeaking(false);
    }
  }, []);

  // Handle WebSocket messages
  const handleMessage = useCallback((event: MessageEvent) => {
    const data = JSON.parse(event.data);
    
    switch (data.type) {
      case 'ready':
        setStatus('Listening...');
        break;
        
      case 'input_audio_buffer.speech_started':
        setIsListening(true);
        setStatus('Listening...');
        break;
        
      case 'input_audio_buffer.speech_stopped':
        setIsListening(false);
        setStatus('Processing...');
        break;
        
      case 'conversation.item.input_audio_transcription.completed':
        const userText = data.transcript;
        setCurrentTranscript('');
        onTranscript?.(userText, true);
        break;
        
      // OpenAI's GA Realtime event names (NS-V1); the beta names are gone.
      case 'response.output_audio_transcript.delta':
        setCurrentTranscript(prev => prev + (data.delta || ''));
        break;
        
      case 'response.output_audio_transcript.done':
        const assistantText = data.transcript;
        setCurrentTranscript('');
        onTranscript?.(assistantText, false);
        setStatus('Listening...');
        break;
        
      case 'response.output_audio.delta':
        setStatus('Aria is speaking...');
        // Decode base64 audio and queue for playback
        const audioData = Uint8Array.from(atob(data.delta), c => c.charCodeAt(0));
        audioQueueRef.current.push(audioData.buffer);
        playNextAudio();
        break;
        
      case 'proposal':
        // A card to approve with a tap; a spoken "yes" never approves.
        setProposals(prev => [...prev, data.proposal]);
        break;

      case 'session_limit':
        {
          const reason: string = data.message || 'That voice chat reached its time limit.';
          endReasonRef.current = reason;
          setStatus(reason);
        }
        break;

      case 'error':
        console.error('Realtime API error:', data);
        setStatus(`Error: ${data.message || 'Unknown error'}`);
        break;
    }
  }, [onTranscript, playNextAudio]);

  // Get access token from Supabase
  const getAccessToken = async (): Promise<string> => {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      throw new Error('Not authenticated');
    }
    return session.access_token;
  };

  // Start the realtime session
  const startSession = useCallback(async () => {
    if (connecting || (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN)) {
      return;  // already connecting or connected: ignore repeat taps
    }
    endReasonRef.current = null;  // a new chat starts with no end reason
    setConnecting(true);
    setStatus('Connecting to Aria…');
    clearProgress();
    progressTimersRef.current = [
      window.setTimeout(() => setStatus('Checking your account…'), 2500),
      window.setTimeout(() => setStatus('Almost ready…'), 6000),
    ];
    try {
      // Ready the microphone and the audio engine now, in parallel with the
      // server, and inside the tap (Safari only allows audio started by one).
      // Inside the try: a failure here releases everything (Codex review).
      micPromiseRef.current = navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 24000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      micPromiseRef.current.catch(() => undefined);
      if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
        audioContextRef.current = new AudioContext({ sampleRate: 24000 });
      }
      
      // Get access token
      const token = await getAccessToken();
      if (unmountedRef.current) {
        releaseEarlyMic();
        return;  // the page was left while starting: open nothing
      }
      
      // Create WebSocket connection
      const wsUrl = config.apiBaseUrl.replace('https://', 'wss://').replace('http://', 'ws://');
      const ws = new WebSocket(`${wsUrl}/v1/realtime/voice`);
      wsRef.current = ws;
      
      ws.onopen = () => {
        // Send auth message with quiet mode preference
        ws.send(JSON.stringify({ type: 'auth', token, quietMode }));
      };
      
      ws.onmessage = handleMessage;
      
      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setStatus('Connection error');
        setIsConnected(false);
      };
      
      ws.onclose = (event) => {
        setConnecting(false);
        clearProgress();
        releaseEarlyMic();
        setIsConnected(false);
        // 4010 = voice switched off server-side (NS-A2); say why, not just "Disconnected".
        // 4003 = refused before connecting (plan, voice minutes used up, or
        // usage couldn't be checked); the server's reason says which.
        setStatus(endReasonRef.current ? endReasonRef.current : event.code === 4010
          ? 'Voice chat is being upgraded. Please type to Aria instead.'
          : event.code === 4003 && event.reason
            ? `${event.reason}. You can still type to Aria.`
            : 'Disconnected');
        stopAudioCapture();
      };
      
      // Wait for ready message then start audio
      const onReadyHandler = async (event: MessageEvent) => {
        const data = JSON.parse(event.data);
        if (data.type === 'ready') {
          ws.removeEventListener('message', onReadyHandler);
          clearProgress();
          setConnecting(false);
          setIsConnected(true);
          await startAudioCapture();
        }
      };
      ws.addEventListener('message', onReadyHandler);
      
    } catch (error) {
      console.error('Failed to start session:', error);
      clearProgress();
      releaseEarlyMic();
      setConnecting(false);
      setStatus('Failed to connect');
    }
  }, [handleMessage, connecting, quietMode]);

  // Start capturing audio from microphone
  const startAudioCapture = async () => {
    try {
      // Readied at the tap (NS-V2); fall back to asking now if not.
      const stream = await (micPromiseRef.current ?? navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 24000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      }));
      micPromiseRef.current = null;
      mediaStreamRef.current = stream;

      const audioContext = audioContextRef.current && audioContextRef.current.state !== 'closed'
        ? audioContextRef.current
        : new AudioContext({ sampleRate: 24000 });
      audioContextRef.current = audioContext;
      if (audioContext.state === 'suspended') await audioContext.resume();
      
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      
      processor.onaudioprocess = (e) => {
        // Don't send audio if muted
        if (isMutedRef.current) return;
        
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0);
          const pcmData = floatTo16BitPCM(inputData);
          wsRef.current.send(pcmData);
        }
      };
      
      source.connect(processor);
      processor.connect(audioContext.destination);
      
      setStatus('Listening...');
      
    } catch (error) {
      console.error('Microphone access error:', error);
      setStatus('Microphone access denied');
    }
  };

  // Stop audio capture
  const stopAudioCapture = () => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
  };

  // End the session
  const endSession = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    stopAudioCapture();
    setIsConnected(false);
    setStatus('Tap to connect');
    onClose?.();
  }, [onClose]);

  // Cleanup on unmount
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      clearProgress();
      releaseEarlyMic();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      stopAudioCapture();
    };
  }, []);

  // Determine avatar glow color based on state
  const getGlowColor = () => {
    if (!isConnected) return 'rgba(99, 102, 241, 0.3)';
    if (isMuted) return 'rgba(239, 68, 68, 0.6)'; // Red when muted
    if (isSpeaking) return 'rgba(139, 92, 246, 0.8)'; // Purple when speaking
    if (isListening) return 'rgba(34, 197, 94, 0.8)'; // Green when listening
    return 'rgba(99, 102, 241, 0.6)'; // Indigo when idle/connected
  };

  const getStatusColor = () => {
    if (isMuted) return '#ef4444';
    if (isSpeaking) return '#8b5cf6';
    if (isListening) return '#22c55e';
    return '#6366f1';
  };

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 3,
        py: 4,
      }}
    >
      {/* Aria's Avatar - Large and prominent */}
      <Box sx={{ position: 'relative' }}>
        <Box 
          sx={{ 
            width: 180, 
            height: 180, 
            borderRadius: '50%', 
            overflow: 'hidden',
            boxShadow: `0 0 ${isConnected ? '60px' : '30px'} ${getGlowColor()}`,
            border: `4px solid ${getGlowColor()}`,
            transition: 'all 0.5s ease',
            animation: (isConnected && (isListening || isSpeaking)) ? 'pulse 2s ease-in-out infinite' : 'gentlePulse 3s ease-in-out infinite',
            '@keyframes pulse': {
              '0%, 100%': { 
                boxShadow: `0 0 40px ${getGlowColor()}`,
                transform: 'scale(1)'
              },
              '50%': { 
                boxShadow: `0 0 80px ${getGlowColor()}`,
                transform: 'scale(1.03)'
              },
            },
            '@keyframes gentlePulse': {
              '0%, 100%': { 
                boxShadow: `0 0 30px rgba(99, 102, 241, 0.3)`,
              },
              '50%': { 
                boxShadow: `0 0 50px rgba(99, 102, 241, 0.5)`,
              },
            }
          }}
        >
          <img 
            src="/aria-avatar.png" 
            alt="Aria" 
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        </Box>
        
        {/* Connection status indicator */}
        {isConnected && (
          <Box
            sx={{
              position: 'absolute',
              bottom: 10,
              right: 10,
              width: 24,
              height: 24,
              borderRadius: '50%',
              bgcolor: isListening ? '#22c55e' : isSpeaking ? '#8b5cf6' : '#6366f1',
              border: '3px solid white',
              animation: 'statusPulse 1.5s ease-in-out infinite',
              '@keyframes statusPulse': {
                '0%, 100%': { transform: 'scale(1)' },
                '50%': { transform: 'scale(1.2)' },
              }
            }}
          />
        )}
      </Box>
      
      {/* Status text */}
      <Typography 
        variant="h6" 
        sx={{ 
          fontWeight: 600,
          color: getStatusColor(),
          transition: 'color 0.3s ease'
        }}
      >
        {isConnected 
          ? (isMuted ? 'Muted' : isSpeaking ? 'Aria is speaking...' : isListening ? 'Listening...' : 'Ready')
          : 'Aria'
        }
      </Typography>
      
      {/* Current transcript while speaking */}
      <Fade in={!!currentTranscript}>
        <Typography 
          variant="body1" 
          color="text.secondary"
          sx={{ 
            textAlign: 'center', 
            fontStyle: 'italic',
            maxWidth: 400,
            px: 2,
            minHeight: 24
          }}
        >
          {currentTranscript}
        </Typography>
      </Fade>

      {proposals.length > 0 && (
        <Box sx={{ width: '100%', maxWidth: 560, display: 'flex', flexDirection: 'column', gap: 1.5, px: 2 }}>
          {proposals.map((p) => <ApprovalCard key={p.id} proposal={p} />)}
        </Box>
      )}
      
      {/* Main action button */}
      {!isConnected ? (
        <IconButton
          onClick={startSession}
          disabled={connecting}
          aria-label={connecting ? 'Connecting to Aria' : 'Start talking to Aria'}
          sx={{
            width: 80,
            height: 80,
            background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
            color: 'white',
            boxShadow: '0 8px 32px rgba(99, 102, 241, 0.4)',
            '&:hover': {
              background: 'linear-gradient(135deg, #5558e3 0%, #7c4fe0 100%)',
              boxShadow: '0 12px 40px rgba(99, 102, 241, 0.5)',
              transform: 'scale(1.05)',
            },
            '&.Mui-disabled': {
              background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
              color: 'white',
              opacity: 0.9,
            },
            transition: 'all 0.3s ease'
          }}
        >
          {connecting
            ? <CircularProgress size={36} sx={{ color: 'white' }} />
            : <MicIcon sx={{ fontSize: 36 }} />}
        </IconButton>
      ) : (
        <Button
          variant="contained"
          onClick={endSession}
          startIcon={<CallEndIcon />}
          sx={{
            px: 4,
            py: 1.5,
            borderRadius: '50px',
            bgcolor: '#ef4444',
            textTransform: 'none',
            fontWeight: 600,
            '&:hover': {
              bgcolor: '#dc2626',
            }
          }}
        >
          End conversation
        </Button>
      )}
      
      {/* Controls when connected */}
      {isConnected && (
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', mt: 2 }}>
          {/* Mute/Unmute Button */}
          <IconButton
            onClick={() => setIsMuted(!isMuted)}
            sx={{
              width: 56,
              height: 56,
              bgcolor: isMuted ? 'error.main' : 'rgba(99, 102, 241, 0.1)',
              color: isMuted ? 'white' : 'primary.main',
              border: '2px solid',
              borderColor: isMuted ? 'error.main' : 'primary.main',
              '&:hover': {
                bgcolor: isMuted ? 'error.dark' : 'rgba(99, 102, 241, 0.2)',
              },
              transition: 'all 0.2s ease'
            }}
          >
            {isMuted ? <MicOffIcon /> : <MicIcon />}
          </IconButton>
          
          {/* Quiet Mode Toggle */}
          <Box 
            onClick={() => {
              const newQuietMode = !quietMode;
              setQuietMode(newQuietMode);
              // Send quiet mode update to backend
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'config', quietMode: newQuietMode }));
              }
            }}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 2,
              py: 1,
              borderRadius: '20px',
              bgcolor: quietMode ? 'rgba(34, 197, 94, 0.1)' : 'rgba(0, 0, 0, 0.05)',
              border: '1px solid',
              borderColor: quietMode ? 'success.main' : 'divider',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              '&:hover': {
                bgcolor: quietMode ? 'rgba(34, 197, 94, 0.2)' : 'rgba(0, 0, 0, 0.1)',
              }
            }}
          >
            {quietMode ? <VolumeOffIcon fontSize="small" color="success" /> : <VolumeUpIcon fontSize="small" />}
            <Typography variant="body2" fontWeight={500}>
              {quietMode ? 'Quiet Mode' : 'Normal Mode'}
            </Typography>
          </Box>
        </Box>
      )}

      {/* Mute indicator text */}
      {isConnected && isMuted && (
        <Typography variant="caption" color="error" sx={{ mt: 1 }}>
          Microphone muted - Aria can't hear you
        </Typography>
      )}
      
      {/* Instructions when not connected */}
      {!isConnected && (
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', maxWidth: 300 }}>
          Tap the microphone to start talking with Aria. She'll respond naturally when you pause.
        </Typography>
      )}
      
      {/* Status indicator when connected */}
      {isConnected && (
        <Typography variant="caption" color="text.secondary">
          {status}
        </Typography>
      )}
    </Box>
  );
};

export default RealtimeVoice;
