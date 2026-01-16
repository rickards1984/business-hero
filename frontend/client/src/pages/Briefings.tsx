import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Container,
  Paper,
  Typography,
  CircularProgress,
  Alert,
  Button,
  Divider,
} from '@mui/material';
import { useAuth } from '@/contexts/AuthContext';
import { fetchEmailBriefings, generateEmailBriefing, EmailBriefingItem } from '@/lib/emailApi';

export default function Briefings() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [briefings, setBriefings] = useState<EmailBriefingItem[]>([]);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      loadBriefings();
    }
  }, [user]);

  const loadBriefings = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchEmailBriefings({ limit: 20 });
      setBriefings(data.briefings || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load briefings');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setError('');
    try {
      await generateEmailBriefing({ hours: 24 });
      await loadBriefings();
    } catch (err: any) {
      setError(err.message || 'Failed to generate briefing');
    } finally {
      setGenerating(false);
    }
  };

  if (loading || authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Paper sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h6">Email Briefings</Typography>
          <Button variant="contained" onClick={handleGenerate} disabled={generating}>
            {generating ? <CircularProgress size={20} /> : 'Generate now'}
          </Button>
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {briefings.map((briefing, index) => (
          <Box key={briefing.id} sx={{ mb: 3 }}>
            <Typography variant="subtitle2" color="text.secondary">
              {new Date(briefing.created_at).toLocaleString()}
            </Typography>
            <Typography
              component="div"
              sx={{ whiteSpace: 'pre-wrap', mt: 1 }}
            >
              {briefing.briefing_markdown}
            </Typography>
            {index < briefings.length - 1 && <Divider sx={{ mt: 3 }} />}
          </Box>
        ))}

        {briefings.length === 0 && (
          <Typography color="text.secondary">No briefings yet.</Typography>
        )}
      </Paper>
    </Container>
  );
}
