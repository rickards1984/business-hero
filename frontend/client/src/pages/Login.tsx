import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Paper,
  TextField,
  Button,
  Typography,
  Alert,
  CircularProgress,
  Container,
  Tabs,
  Tab,
} from '@mui/material';
import { Business as BusinessIcon } from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase } from '@/lib/supabase';

export default function Login() {
  const navigate = useNavigate();
  const { signIn, checkAdminStatus } = useAuth();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const { error: signInError } = await signIn(email, password);
      
      if (signInError) {
        if (signInError.message.toLowerCase().includes('email not confirmed')) {
          setError('Please check your email and click the confirmation link before logging in.');
        } else {
          setError(signInError.message);
        }
        setLoading(false);
        return;
      }

      const isAdmin = await checkAdminStatus();
      
      if (isAdmin) {
        navigate('/admin');
      } else {
        navigate('/app');
      }
    } catch (err: any) {
      setError(err?.message || 'An unexpected error occurred');
      console.error('Login error:', err);
      setLoading(false);
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      setLoading(false);
      return;
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      setLoading(false);
      return;
    }

    try {
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: email.trim(),
        password,
      });

      if (signUpError) {
        setError(signUpError.message);
        setLoading(false);
        return;
      }

      setSuccess('Account created successfully! Please check your email to confirm your account, then log in.');
      
      setMode('login');
      setPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      setError(err?.message || 'An unexpected error occurred');
      console.error('Signup error:', err);
    } finally {
      setLoading(false);
    }
  };

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
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
              mb: 3,
            }}
          >
            <img
              src="/business-hero-logo.svg"
              alt="Business Hero"
              style={{ height: '60px', width: 'auto' }}
            />
          </Box>

          <Tabs
            value={mode}
            onChange={(_, v) => {
              setMode(v);
              setError('');
              setSuccess('');
            }}
            sx={{ mb: 3, width: '100%' }}
            centered
          >
            <Tab label="Sign In" value="login" data-testid="tab-login" />
            <Tab label="Sign Up" value="signup" data-testid="tab-signup" />
          </Tabs>

          {error && (
            <Alert severity="error" sx={{ width: '100%', mb: 2 }} data-testid="alert-error">
              {error}
            </Alert>
          )}

          {success && (
            <Alert severity="success" sx={{ width: '100%', mb: 2 }} data-testid="alert-success">
              {success}
            </Alert>
          )}

          {mode === 'login' ? (
            <Box component="form" onSubmit={handleLogin} sx={{ width: '100%' }}>
              <TextField
                fullWidth
                label="Email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                margin="normal"
                required
                autoComplete="email"
                autoFocus
                variant="outlined"
                data-testid="input-email"
              />
              <TextField
                fullWidth
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                margin="normal"
                required
                autoComplete="current-password"
                variant="outlined"
                data-testid="input-password"
              />
              <Button
                type="submit"
                fullWidth
                variant="contained"
                size="large"
                disabled={loading}
                sx={{ mt: 3, mb: 2 }}
                data-testid="button-login"
              >
                {loading ? <CircularProgress size={24} color="inherit" /> : 'Sign In'}
              </Button>
            </Box>
          ) : (
            <Box component="form" onSubmit={handleSignup} sx={{ width: '100%' }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                You must be invited by an administrator before you can sign up.
              </Typography>
              <TextField
                fullWidth
                label="Email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                margin="normal"
                required
                autoComplete="email"
                autoFocus
                variant="outlined"
                data-testid="input-signup-email"
              />
              <TextField
                fullWidth
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                margin="normal"
                required
                autoComplete="new-password"
                variant="outlined"
                helperText="At least 6 characters"
                data-testid="input-signup-password"
              />
              <TextField
                fullWidth
                label="Confirm Password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                margin="normal"
                required
                autoComplete="new-password"
                variant="outlined"
                data-testid="input-signup-confirm"
              />
              <Button
                type="submit"
                fullWidth
                variant="contained"
                size="large"
                disabled={loading}
                sx={{ mt: 3, mb: 2 }}
                data-testid="button-signup"
              >
                {loading ? <CircularProgress size={24} color="inherit" /> : 'Create Account'}
              </Button>
            </Box>
          )}
        </Paper>
      </Container>
    </Box>
  );
}
