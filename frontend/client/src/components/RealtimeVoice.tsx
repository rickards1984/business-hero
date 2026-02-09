import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  Box,
  IconButton,
  Typography,
  Paper,
  Fade,
} from '@mui/material';
import {
  Mic as MicIcon,
  Stop as StopIcon,
  VolumeUp as VolumeUpIcon,
} from '@mui/icons-material';
import { supabase } from '@/lib/supabase';
import { config } from '@/config/env';

interface RealtimeVoiceProps {
  onTranscript?: (text: string, isUser: boolean) => void;
}

export const RealtimeVoice: React.FC<RealtimeVoiceProps> = ({ onTranscript }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [status, setStatus] = useState<string>('Click to start conversation');
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
        setStatus('Ready - start speaking');
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
        setStatus('Ready - start speaking');
        break;
        
      case 'response.audio.delta':
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
      
      setStatus('Ready - start speaking');
      
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
    setStatus('Click to start conversation');
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      endSession();
    };
  }, [endSession]);

  return (
    <Paper
      elevation={3}
      sx={{
        p: 4,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 3,
        maxWidth: 400,
        mx: 'auto',
        borderRadius: 4,
      }}
    >
      <Typography variant="h6" color="text.secondary">
        AI Admin Voice
      </Typography>
      
      {/* Main action button */}
      <Box sx={{ position: 'relative' }}>
        <IconButton
          onClick={isConnected ? endSession : startSession}
          sx={{
            width: 100,
            height: 100,
            bgcolor: isConnected 
              ? (isListening ? 'success.main' : isSpeaking ? 'info.main' : 'primary.main')
              : 'grey.300',
            color: 'white',
            '&:hover': {
              bgcolor: isConnected 
                ? (isListening ? 'success.dark' : isSpeaking ? 'info.dark' : 'primary.dark')
                : 'grey.400',
            },
            transition: 'all 0.3s ease',
          }}
        >
          {!isConnected ? (
            <MicIcon sx={{ fontSize: 48 }} />
          ) : isListening ? (
            <MicIcon sx={{ fontSize: 48 }} />
          ) : isSpeaking ? (
            <VolumeUpIcon sx={{ fontSize: 48 }} />
          ) : (
            <StopIcon sx={{ fontSize: 48 }} />
          )}
        </IconButton>
        
        {/* Pulsing animation when active */}
        {isConnected && (isListening || isSpeaking) && (
          <Box
            sx={{
              position: 'absolute',
              top: -10,
              left: -10,
              right: -10,
              bottom: -10,
              borderRadius: '50%',
              border: 3,
              borderColor: isListening ? 'success.main' : 'info.main',
              animation: 'pulse 1.5s ease-in-out infinite',
              '@keyframes pulse': {
                '0%': { transform: 'scale(1)', opacity: 1 },
                '50%': { transform: 'scale(1.1)', opacity: 0.5 },
                '100%': { transform: 'scale(1)', opacity: 1 },
              },
            }}
          />
        )}
      </Box>
      
      {/* Status text */}
      <Typography 
        variant="body1" 
        color="text.secondary"
        sx={{ textAlign: 'center', minHeight: 24 }}
      >
        {status}
      </Typography>
      
      {/* Current transcript */}
      <Fade in={!!currentTranscript}>
        <Typography 
          variant="body2" 
          color="text.secondary"
          sx={{ 
            textAlign: 'center', 
            fontStyle: 'italic',
            maxWidth: '100%',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {currentTranscript}
        </Typography>
      </Fade>
      
      {/* Instructions */}
      {!isConnected && (
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center' }}>
          Click the microphone to start a voice conversation with your AI Admin.
          Speak naturally - I'll respond when you pause.
        </Typography>
      )}
    </Paper>
  );
};

export default RealtimeVoice;
