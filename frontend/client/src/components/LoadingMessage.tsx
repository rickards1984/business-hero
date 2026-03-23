import { useState, useEffect } from 'react';
import { CircularProgress } from '@mui/material';

interface LoadingMessageProps {
  messages: string[];
  rotateInterval?: number;
  icon?: string;
}

export default function LoadingMessage({
  messages,
  rotateInterval = 4000,
  icon = '⏳',
}: LoadingMessageProps) {
  const [messageIndex, setMessageIndex] = useState(0);

  useEffect(() => {
    if (messages.length <= 1) return;
    const interval = setInterval(() => {
      setMessageIndex(prev => (prev + 1) % messages.length);
    }, rotateInterval);
    return () => clearInterval(interval);
  }, [messages.length, rotateInterval]);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '40px 20px',
      textAlign: 'center',
    }}>
      <CircularProgress size={24} sx={{ color: '#7c5cfc', mb: 2 }} />
      <div style={{
        fontSize: 14,
        fontWeight: 500,
        color: 'hsl(var(--foreground))',
        marginBottom: 4,
        transition: 'opacity 300ms',
      }}>
        {icon} {messages[messageIndex]}
      </div>
    </div>
  );
}
