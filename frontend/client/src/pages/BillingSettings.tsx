import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Container,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { supabase } from '@/lib/supabase';
import { useMe } from '@/hooks/useMe';
import { apiRequest } from '@/lib/queryClient';

const PLAN_OPTIONS = ['starter', 'pro', 'premium'];

export default function BillingSettings() {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [planTier, setPlanTier] = useState('starter');
  const [subscriptionStatus, setSubscriptionStatus] = useState<string | null>(null);
  const [currentPeriodEnd, setCurrentPeriodEnd] = useState<string | null>(null);
  const [isActive, setIsActive] = useState<boolean | null>(null);
  const [trialEndsAt, setTrialEndsAt] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (me?.business?.id) {
      loadBilling();
    }
  }, [me?.business?.id]);

  const loadBilling = async () => {
    setLoading(true);
    setError('');
    try {
      const { data, error: fetchError } = await supabase
        .from('businesses')
        .select('plan_tier,subscription_status,current_period_end,is_active,trial_ends_at')
        .eq('id', me?.business?.id)
        .single();
      if (fetchError) throw fetchError;
      setPlanTier(data?.plan_tier || 'starter');
      setSubscriptionStatus(data?.subscription_status || null);
      setCurrentPeriodEnd(data?.current_period_end || null);
      setIsActive(data?.is_active ?? null);
      setTrialEndsAt(data?.trial_ends_at || null);
    } catch (err: any) {
      setError(err.message || 'Failed to load billing');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckout = async () => {
    setSubmitting(true);
    setError('');
    try {
      const response = await apiRequest('POST', '/v1/billing/checkout-session', {
        plan_tier: planTier,
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to start checkout');
      }
      const data = await response.json();
      window.location.assign(data.url);
    } catch (err: any) {
      setError(err.message || 'Failed to start checkout');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePortal = async () => {
    setSubmitting(true);
    setError('');
    try {
      const response = await apiRequest('POST', '/v1/billing/portal');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to open billing portal');
      }
      const data = await response.json();
      window.location.assign(data.url);
    } catch (err: any) {
      setError(err.message || 'Failed to open billing portal');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Button variant="outlined" startIcon={<ArrowBackIcon />} onClick={() => navigate('/app')}>
          Back to Dashboard
        </Button>
      </Box>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>Billing</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Manage your subscription and plan features.
        </Typography>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {loading ? (
          <Typography color="text.secondary">Loading...</Typography>
        ) : (
          <>
            <Box sx={{ display: 'grid', gap: 1, mb: 2 }}>
              <Typography variant="body2">Plan: {planTier}</Typography>
              <Typography variant="body2">Status: {subscriptionStatus || 'Not subscribed'}</Typography>
              <Typography variant="body2">
                Current period end: {currentPeriodEnd ? new Date(currentPeriodEnd).toLocaleString() : '—'}
              </Typography>
              <Typography variant="body2">Active: {isActive === null ? '—' : isActive ? 'Yes' : 'No'}</Typography>
              <Typography variant="body2">
                Trial ends: {trialEndsAt ? new Date(trialEndsAt).toLocaleString() : '—'}
              </Typography>
            </Box>

            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>Plan</InputLabel>
              <Select value={planTier} label="Plan" onChange={(e) => setPlanTier(e.target.value)}>
                {PLAN_OPTIONS.map((plan) => (
                  <MenuItem key={plan} value={plan}>{plan}</MenuItem>
                ))}
              </Select>
            </FormControl>

            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
              <Button variant="contained" onClick={handleCheckout} disabled={submitting}>
                Upgrade / Downgrade
              </Button>
              <Button variant="outlined" onClick={handlePortal} disabled={submitting}>
                Manage Billing
              </Button>
            </Box>
          </>
        )}
      </Paper>
    </Container>
  );
}
