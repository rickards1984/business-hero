import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Paper,
  Toolbar,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import AddIcon from '@mui/icons-material/Add';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';

interface OnboardingStatus {
  business_id: string;
  business_name: string;
  plan_tier: string;
  is_active: boolean;
  onboarding_completed: boolean;
  checklist_progress: number;
  checklist_completed: number;
  checklist_total: number;
}

export default function AdminOnboarding() {
  const navigate = useNavigate();
  const { user, isAdmin, loading: authLoading, adminLoading } = useAuth();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statuses, setStatuses] = useState<OnboardingStatus[]>([]);
  const [abandonDialogOpen, setAbandonDialogOpen] = useState(false);
  const [abandonTarget, setAbandonTarget] = useState<OnboardingStatus | null>(null);

  useEffect(() => {
    if (!authLoading && !user) navigate('/login');
    else if (!authLoading && !adminLoading && !isAdmin) navigate('/app');
  }, [user, isAdmin, authLoading, adminLoading, navigate]);

  useEffect(() => {
    if (user && isAdmin) fetchData();
  }, [user, isAdmin]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await apiRequest('GET', '/v1/admin/onboarding/status');
      setStatuses(await res.json());
    } catch (err: any) {
      setError(err.message || 'Failed to load onboarding data');
    } finally {
      setLoading(false);
    }
  };

  const inProgress = useMemo(
    () => statuses.filter((s) => !s.onboarding_completed && s.checklist_total > 0 && s.checklist_progress < 100),
    [statuses],
  );

  const completed = useMemo(
    () => statuses.filter((s) => s.onboarding_completed),
    [statuses],
  );

  const stats = useMemo(() => {
    const total = statuses.filter((s) => s.checklist_total > 0).length;
    const done = completed.length;
    const rate = total > 0 ? Math.round((done / total) * 100) : 0;
    return { inProgress: inProgress.length, completed: done, rate };
  }, [statuses, inProgress, completed]);

  const handleAbandon = async () => {
    if (!abandonTarget) return;
    try {
      await apiRequest(
        'PUT',
        `/v1/admin/onboarding/session/${abandonTarget.business_id}/step?step_name=review_activate`,
        { activate_now: false, send_welcome_email: false, admin_notes: 'Abandoned by admin' },
      );
      setAbandonDialogOpen(false);
      setAbandonTarget(null);
      fetchData();
    } catch (err: any) {
      setError(err.message || 'Failed to abandon session');
    }
  };

  if (authLoading || adminLoading || loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static" elevation={1}>
        <Toolbar>
          <Button color="inherit" startIcon={<ArrowBackIcon />} onClick={() => navigate('/admin')} sx={{ mr: 2 }}>
            Back
          </Button>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>Onboarding</Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => navigate('/admin/onboarding/new')} sx={{ bgcolor: 'white', color: 'primary.main', '&:hover': { bgcolor: 'grey.100' } }}>
            Start New Onboarding
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        {error && <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')}>{error}</Alert>}

        {/* Resume banner for in-progress sessions */}
        {inProgress.length > 0 && (
          <Alert
            severity="warning"
            icon={<WarningAmberIcon />}
            action={
              <Button
                color="inherit"
                size="small"
                variant="outlined"
                startIcon={<PlayArrowIcon />}
                onClick={() => navigate(`/admin/onboarding/${inProgress[0].business_id}`)}
              >
                Resume Onboarding
              </Button>
            }
            sx={{ mb: 3 }}
          >
            <Typography variant="subtitle2">You have an onboarding in progress</Typography>
            <Typography variant="body2">
              {inProgress[0].business_name} — {inProgress[0].checklist_completed}/{inProgress[0].checklist_total} checklist items completed
            </Typography>
          </Alert>
        )}

        {/* Stats cards */}
        <Box sx={{ display: 'flex', gap: 2, mb: 4, flexWrap: 'wrap' }}>
          <Card sx={{ flex: 1, minWidth: 160 }}>
            <CardContent sx={{ textAlign: 'center' }}>
              <Typography variant="h4" color="warning.main">{stats.inProgress}</Typography>
              <Typography variant="body2" color="text.secondary">In Progress</Typography>
            </CardContent>
          </Card>
          <Card sx={{ flex: 1, minWidth: 160 }}>
            <CardContent sx={{ textAlign: 'center' }}>
              <Typography variant="h4" color="success.main">{stats.completed}</Typography>
              <Typography variant="body2" color="text.secondary">Completed</Typography>
            </CardContent>
          </Card>
          <Card sx={{ flex: 1, minWidth: 160 }}>
            <CardContent sx={{ textAlign: 'center' }}>
              <Typography variant="h4">{stats.rate}%</Typography>
              <Typography variant="body2" color="text.secondary">Completion Rate</Typography>
            </CardContent>
          </Card>
        </Box>

        {/* In Progress */}
        <Typography variant="h6" gutterBottom>In Progress</Typography>
        {inProgress.length === 0 ? (
          <Paper sx={{ p: 3, mb: 4, textAlign: 'center' }}>
            <Typography color="text.secondary">No onboarding sessions in progress</Typography>
          </Paper>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mb: 4 }}>
            {inProgress.map((s) => (
              <Card key={s.business_id} variant="outlined">
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
                    <Box>
                      <Typography variant="subtitle1" fontWeight="bold">{s.business_name}</Typography>
                      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5 }}>
                        <Chip label={s.plan_tier} size="small" variant="outlined" />
                        <Typography variant="caption" color="text.secondary">
                          {s.checklist_completed}/{s.checklist_total} checklist items
                        </Typography>
                      </Box>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        variant="contained"
                        size="small"
                        startIcon={<PlayArrowIcon />}
                        onClick={() => navigate(`/admin/onboarding/${s.business_id}`)}
                      >
                        Resume
                      </Button>
                      <Button
                        variant="outlined"
                        size="small"
                        color="warning"
                        onClick={() => { setAbandonTarget(s); setAbandonDialogOpen(true); }}
                      >
                        Abandon
                      </Button>
                    </Box>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={s.checklist_progress}
                    sx={{ mt: 2, height: 6, borderRadius: 3 }}
                  />
                </CardContent>
              </Card>
            ))}
          </Box>
        )}

        {/* Completed */}
        <Typography variant="h6" gutterBottom>Recently Completed</Typography>
        {completed.length === 0 ? (
          <Paper sx={{ p: 3, textAlign: 'center' }}>
            <Typography color="text.secondary">No completed onboardings yet</Typography>
          </Paper>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {completed.map((s) => (
              <Card key={s.business_id} variant="outlined">
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
                    <Box>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="subtitle1" fontWeight="bold">{s.business_name}</Typography>
                        <Chip label="Completed" size="small" color="success" />
                      </Box>
                      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5 }}>
                        <Chip label={s.plan_tier} size="small" variant="outlined" />
                        <Typography variant="caption" color="text.secondary">
                          Checklist: {s.checklist_completed}/{s.checklist_total} items done
                        </Typography>
                      </Box>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        variant="outlined"
                        size="small"
                        startIcon={<OpenInNewIcon />}
                        onClick={() => navigate(`/admin/businesses/${s.business_id}`)}
                      >
                        Manage
                      </Button>
                    </Box>
                  </Box>
                </CardContent>
              </Card>
            ))}
          </Box>
        )}

        {/* Abandon confirmation */}
        <Dialog open={abandonDialogOpen} onClose={() => setAbandonDialogOpen(false)} maxWidth="xs" fullWidth>
          <DialogTitle>Abandon Onboarding?</DialogTitle>
          <DialogContent>
            <Typography variant="body2" color="text.secondary">
              This will mark the onboarding for <strong>{abandonTarget?.business_name}</strong> as completed without activation. You can still manage the business from the admin dashboard.
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setAbandonDialogOpen(false)}>Cancel</Button>
            <Button variant="contained" color="warning" onClick={handleAbandon}>Abandon</Button>
          </DialogActions>
        </Dialog>
      </Container>
    </Box>
  );
}
