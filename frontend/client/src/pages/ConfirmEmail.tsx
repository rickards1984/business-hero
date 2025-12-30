import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Button,
  Container,
} from '@mui/material';
import { CheckCircle as CheckCircleIcon, Error as ErrorIcon, Business as BusinessIcon } from '@mui/icons-material';
import { supabase } from '@/lib/supabase';

export default function ConfirmEmail() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');

  useEffect(() => {
    const handleEmailConfirmation = async () => {
      try {
        const tokenHash = searchParams.get('token_hash');
        const type = searchParams.get('type');

        if (tokenHash && type === 'email') {
          const { error } = await supabase.auth.verifyOtp({
            token_hash: tokenHash,
            type: 'email',
          });

          if (error) {
            setStatus('error');
            setMessage(error.message);
            return;
          }

          setStatus('success');
          setMessage('Your email has been confirmed successfully! You can now log in.');
          return;
        }

        const accessToken = searchParams.get('access_token');
        const refreshToken = searchParams.get('refresh_token');

        if (accessToken && refreshToken) {
          const { error } = await supabase.auth.setSession({
            access_token: accessToken,
            refresh_token: refreshToken,
          });

          if (error) {
            setStatus('error');
            setMessage(error.message);
            return;
          }

          setStatus('success');
          setMessage('Your email has been confirmed successfully! You can now log in.');
          return;
        }

        const { data: { session } } = await supabase.auth.getSession();
        if (session) {
          setStatus('success');
          setMessage('Your email is already confirmed. Redirecting...');
          setTimeout(() => navigate('/app'), 2000);
          return;
        }

        setStatus('error');
        setMessage('Invalid or expired confirmation link. Please try signing up again.');
      } catch (err: any) {
        setStatus('error');
        setMessage(err?.message || 'An unexpected error occurred');
      }
    };

    handleEmailConfirmation();
  }, [searchParams, navigate]);

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'grey.100',
      }}
    >
      <Container maxWidth="sm">
        <Paper
          elevation={3}
          sx={{
            p: 4,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            maxWidth: 400,
            mx: 'auto',
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              mb: 3,
            }}
          >
            <BusinessIcon sx={{ fontSize: 40, color: 'primary.main' }} />
            <Typography variant="h4" component="h1" fontWeight="bold">
              Business Hero
            </Typography>
          </Box>

          {status === 'loading' && (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <CircularProgress size={48} sx={{ mb: 2 }} />
              <Typography variant="h6">Confirming your email...</Typography>
              <Typography variant="body2" color="text.secondary">
                Please wait while we verify your account.
              </Typography>
            </Box>
          )}

          {status === 'success' && (
            <Box sx={{ textAlign: 'center', py: 2 }}>
              <CheckCircleIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
              <Typography variant="h6" gutterBottom>
                Email Confirmed!
              </Typography>
              <Alert severity="success" sx={{ mb: 3 }} data-testid="alert-success">
                {message}
              </Alert>
              <Button
                variant="contained"
                size="large"
                onClick={() => navigate('/login')}
                data-testid="button-go-to-login"
              >
                Go to Login
              </Button>
            </Box>
          )}

          {status === 'error' && (
            <Box sx={{ textAlign: 'center', py: 2 }}>
              <ErrorIcon sx={{ fontSize: 64, color: 'error.main', mb: 2 }} />
              <Typography variant="h6" gutterBottom>
                Confirmation Failed
              </Typography>
              <Alert severity="error" sx={{ mb: 3 }} data-testid="alert-error">
                {message}
              </Alert>
              <Button
                variant="contained"
                size="large"
                onClick={() => navigate('/login')}
                data-testid="button-go-to-login"
              >
                Back to Login
              </Button>
            </Box>
          )}
        </Paper>
      </Container>
    </Box>
  );
}
