import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  TextField,
  Button,
  Typography,
  Alert,
  CircularProgress,
  Link,
} from '@mui/material';
import {
  CheckCircleOutline as CheckIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase } from '@/lib/supabase';

const FEATURES = [
  'AI-powered business management',
  'Smart email & call handling',
  'Automated invoicing & accounting',
  '24/7 AI receptionist',
];

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
      const { error: signUpError } = await supabase.auth.signUp({
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
        display: 'flex',
        minHeight: '100vh',
        flexDirection: { xs: 'column', md: 'row' },
      }}
    >
      {/* Brand Panel */}
      <Box
        sx={{
          width: { xs: '100%', md: '45%' },
          background: 'linear-gradient(135deg, #1E40AF 0%, #1E3A8A 50%, #0F172A 100%)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          p: { xs: 4, md: 6 },
          position: 'relative',
          overflow: 'hidden',
          minHeight: { xs: 'auto', md: '100vh' },
          '&::before': {
            content: '""',
            position: 'absolute',
            inset: 0,
            backgroundImage:
              'radial-gradient(circle at 25% 25%, rgba(255,255,255,0.03) 0%, transparent 50%), radial-gradient(circle at 75% 75%, rgba(255,255,255,0.05) 0%, transparent 50%)',
            pointerEvents: 'none',
          },
          '&::after': {
            content: '""',
            position: 'absolute',
            width: 300,
            height: 300,
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%)',
            top: -50,
            right: -100,
            animation: 'floatBlob 15s ease-in-out infinite alternate',
          },
          '@keyframes floatBlob': {
            '0%': { transform: 'translate(0,0) scale(1)' },
            '100%': { transform: 'translate(-30px,40px) scale(1.1)' },
          },
        }}
      >
        <Box sx={{ position: 'relative', zIndex: 1, textAlign: 'center', maxWidth: 360 }}>
          <img
            src="/business-hero-logo.svg"
            alt="Business Hero"
            style={{ maxWidth: 200, width: '100%', height: 'auto', marginBottom: 24, filter: 'brightness(0) invert(1)' }}
          />
          <Typography
            sx={{
              color: 'white',
              fontWeight: 800,
              fontSize: { xs: '1.125rem', md: '1.25rem' },
              letterSpacing: '0.08em',
              mb: 3,
            }}
          >
            YOUR TIME. UNLOCKED.
          </Typography>
          <Box sx={{ display: { xs: 'none', md: 'block' } }}>
            {FEATURES.map((f) => (
              <Box key={f} sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1.5, justifyContent: 'flex-start' }}>
                <CheckIcon sx={{ color: 'rgba(255,255,255,0.6)', fontSize: 18 }} />
                <Typography sx={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.8125rem' }}>{f}</Typography>
              </Box>
            ))}
          </Box>
          <Typography
            sx={{
              color: 'rgba(255,255,255,0.35)',
              fontSize: '0.75rem',
              mt: { xs: 0, md: 6 },
              display: { xs: 'none', md: 'block' },
            }}
          >
            &copy; {new Date().getFullYear()} Business Hero
          </Typography>
        </Box>
      </Box>

      {/* Form Panel — force light-mode input styles on the white background
         since the global theme may be dark */}
      <Box
        sx={{
          width: { xs: '100%', md: '55%' },
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          p: { xs: 3, sm: 4, md: 6 },
          bgcolor: '#ffffff',
          color: '#111827',
          flex: { xs: 1, md: 'none' },
          '& .MuiOutlinedInput-root': {
            color: '#1e293b !important',
            backgroundColor: '#ffffff !important',
            borderRadius: '8px',
            '& fieldset': { borderColor: '#6b7280 !important', borderWidth: '1.5px' },
            '&:hover fieldset': { borderColor: '#374151 !important' },
            '&.Mui-focused fieldset': { borderColor: '#7c3aed !important', borderWidth: '2px' },
            '&.Mui-focused': { backgroundColor: '#ffffff !important' },
          },
          '& .MuiOutlinedInput-input': {
            color: '#1e293b !important',
            WebkitTextFillColor: '#1e293b !important',
            '&::placeholder': { color: '#94a3b8', opacity: 1 },
            '&:-webkit-autofill': {
              WebkitBoxShadow: '0 0 0 100px rgba(255, 255, 255, 0.95) inset !important',
              WebkitTextFillColor: '#1e293b !important',
            },
          },
          '& .MuiInputLabel-root': {
            color: '#374151 !important',
            fontWeight: 500,
            '&.Mui-focused': { color: '#7c3aed !important' },
          },
          '& .MuiFormHelperText-root': {
            color: '#64748b',
          },
        }}
      >
        <Box sx={{ width: '100%', maxWidth: 400 }}>
          <Typography
            sx={{
              fontSize: '1.5rem',
              fontWeight: 700,
              color: '#111827 !important',
              mb: 0.5,
            }}
          >
            {mode === 'login' ? 'Sign In' : 'Create Account'}
          </Typography>
          <Typography
            sx={{
              fontSize: '0.8125rem',
              color: '#334155 !important',
              mb: 4,
            }}
          >
            {mode === 'login'
              ? 'Welcome back. Manage your business effortlessly.'
              : 'You must be invited by an administrator before you can sign up.'}
          </Typography>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }} data-testid="alert-error">
              {error}
            </Alert>
          )}
          {success && (
            <Alert severity="success" sx={{ mb: 2 }} data-testid="alert-success">
              {success}
            </Alert>
          )}

          {mode === 'login' ? (
            <Box component="form" onSubmit={handleLogin}>
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
                disabled={loading}
                sx={{
                  mt: 3,
                  mb: 2,
                  height: 48,
                  fontSize: '0.875rem',
                  fontWeight: 600,
                }}
                data-testid="button-login"
              >
                {loading ? <CircularProgress size={24} color="inherit" /> : 'Sign In'}
              </Button>
              <Box sx={{ textAlign: 'center' }}>
                <Typography variant="body2" sx={{ color: '#334155 !important' }}>
                  Don&apos;t have an account?{' '}
                  <Link
                    component="button"
                    type="button"
                    onClick={() => { setMode('signup'); setError(''); setSuccess(''); }}
                    sx={{ fontWeight: 600, cursor: 'pointer', color: '#7c3aed !important' }}
                    data-testid="tab-signup"
                  >
                    Sign Up
                  </Link>
                </Typography>
              </Box>
            </Box>
          ) : (
            <Box component="form" onSubmit={handleSignup}>
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
                disabled={loading}
                sx={{
                  mt: 3,
                  mb: 2,
                  height: 48,
                  fontSize: '0.875rem',
                  fontWeight: 600,
                }}
                data-testid="button-signup"
              >
                {loading ? <CircularProgress size={24} color="inherit" /> : 'Create Account'}
              </Button>
              <Box sx={{ textAlign: 'center' }}>
                <Typography variant="body2" sx={{ color: '#334155 !important' }}>
                  Already have an account?{' '}
                  <Link
                    component="button"
                    type="button"
                    onClick={() => { setMode('login'); setError(''); setSuccess(''); }}
                    sx={{ fontWeight: 600, cursor: 'pointer', color: '#7c3aed !important' }}
                    data-testid="tab-login"
                  >
                    Sign In
                  </Link>
                </Typography>
              </Box>
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
}
