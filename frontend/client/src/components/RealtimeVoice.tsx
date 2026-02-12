import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  Box,
  IconButton,
  Typography,
  Button,
  Fade,
} from '@mui/material';
import {
  Mic as MicIcon,
  CallEnd as CallEndIcon,
} from '@mui/icons-material';
import { supabase } from '@/lib/supabase';
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
  
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const audioQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingRef = useRef(false);

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
        
      case 'response.audio_transcript.delta':
        setCurrentTranscript(prev => prev + (data.delta || ''));
        break;
        
      case 'response.audio_transcript.done':
        const assistantText = data.transcript;
        setCurrentTranscript('');
        onTranscript?.(assistantText, false);
        setStatus('Listening...');
        break;
        
      case 'response.audio.delta':
        setStatus('Aria is speaking...');
        // Decode base64 audio and queue for playback
        const audioData = Uint8Array.from(atob(data.delta), c => c.charCodeAt(0));
        audioQueueRef.current.push(audioData.buffer);
        playNextAudio();
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
    try {
      setStatus('Connecting...');
      
      // Get access token
      const token = await getAccessToken();
      
      // Create WebSocket connection
      const wsUrl = config.apiBaseUrl.replace('https://', 'wss://').replace('http://', 'ws://');
      const ws = new WebSocket(`${wsUrl}/v1/realtime/voice`);
      wsRef.current = ws;
      
      ws.onopen = () => {
        // Send auth message
        ws.send(JSON.stringify({ type: 'auth', token }));
      };
      
      ws.onmessage = handleMessage;
      
      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setStatus('Connection error');
        setIsConnected(false);
      };
      
      ws.onclose = () => {
        setIsConnected(false);
        setStatus('Disconnected');
        stopAudioCapture();
      };
      
      // Wait for ready message then start audio
      const onReadyHandler = async (event: MessageEvent) => {
        const data = JSON.parse(event.data);
        if (data.type === 'ready') {
          ws.removeEventListener('message', onReadyHandler);
          setIsConnected(true);
          await startAudioCapture();
        }
      };
      ws.addEventListener('message', onReadyHandler);
      
    } catch (error) {
      console.error('Failed to start session:', error);
      setStatus('Failed to connect');
    }
  }, [handleMessage]);

  // Start capturing audio from microphone
  const startAudioCapture = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: 24000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        } 
      });
      mediaStreamRef.current = stream;
      
      const audioContext = new AudioContext({ sampleRate: 24000 });
      audioContextRef.current = audioContext;
      
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      
      processor.onaudioprocess = (e) => {
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
    return () => {
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
    if (isSpeaking) return 'rgba(139, 92, 246, 0.8)'; // Purple when speaking
    if (isListening) return 'rgba(34, 197, 94, 0.8)'; // Green when listening
    return 'rgba(99, 102, 241, 0.6)'; // Indigo when idle/connected
  };

  const getStatusColor = () => {
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
          ? (isSpeaking ? 'Aria is speaking...' : isListening ? 'Listening...' : 'Ready')
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
      
      {/* Main action button */}
      {!isConnected ? (
        <IconButton
          onClick={startSession}
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
            transition: 'all 0.3s ease'
          }}
        >
          <MicIcon sx={{ fontSize: 36 }} />
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
