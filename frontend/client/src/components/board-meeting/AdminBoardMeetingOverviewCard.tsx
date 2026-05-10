/**
 * Admin: small overview card for the Executive Board Meeting feature.
 *
 * Drops into AdminDashboard.tsx alongside the existing admin tiles.
 * Pulls /v1/executive-meetings/admin/overview and renders a compact summary.
 */
import { useEffect, useState } from 'react';
import { Box, Card, CardContent, CircularProgress, Stack, Typography } from '@mui/material';
import {
  AdminMeetingOverviewRow,
  adminMeetingsOverview,
} from '@/lib/executiveMeetingsApi';

export default function AdminBoardMeetingOverviewCard() {
  const [rows, setRows] = useState<AdminMeetingOverviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await adminMeetingsOverview();
        if (!cancelled) setRows(data);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const enabledCount = rows.filter((r) => r.enabled).length;
  const totalMeetings = rows.reduce(
    (acc, r) => acc + (r.total_meetings_completed || 0),
    0,
  );

  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h3">Executive Board Meeting</Typography>
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
              <CircularProgress size={20} />
            </Box>
          ) : error ? (
            <Typography variant="body2" color="error">
              {error}
            </Typography>
          ) : (
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={3}
              divider={<Box sx={{ width: 1, bgcolor: 'divider' }} />}
            >
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Businesses with schedule
                </Typography>
                <Typography variant="h2">{enabledCount}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Total meetings completed
                </Typography>
                <Typography variant="h2">{totalMeetings.toLocaleString('en-GB')}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Total businesses tracked
                </Typography>
                <Typography variant="h2">{rows.length}</Typography>
              </Box>
            </Stack>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
