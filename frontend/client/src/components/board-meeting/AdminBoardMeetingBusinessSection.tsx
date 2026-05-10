/**
 * Admin: per-business Executive Board Meeting section.
 *
 * Drops into AdminBusinessDetail.tsx. Read-only summary of a business's
 * meeting status, plus a link into their meeting history.
 */
import { useEffect, useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from '@mui/material';
import {
  AdminMeetingOverviewRow,
  adminMeetingsOverview,
  formatUKDateTime,
} from '@/lib/executiveMeetingsApi';

interface AdminBoardMeetingBusinessSectionProps {
  businessId: string;
}

export default function AdminBoardMeetingBusinessSection({
  businessId,
}: AdminBoardMeetingBusinessSectionProps) {
  const [row, setRow] = useState<AdminMeetingOverviewRow | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const all = await adminMeetingsOverview();
        const match = all.find((r) => r.business_id === businessId);
        if (!cancelled) setRow(match || null);
      } catch {
        // Silent fail — admin pages tolerate missing sections
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [businessId]);

  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h3">Executive Board Meeting</Typography>
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
              <CircularProgress size={20} />
            </Box>
          ) : !row ? (
            <Typography variant="body2" color="text.secondary">
              No meeting settings on file for this business.
            </Typography>
          ) : (
            <Stack spacing={1.5}>
              <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
                <Chip
                  label={row.enabled ? 'Enabled' : 'Disabled'}
                  color={row.enabled ? 'success' : 'default'}
                  size="small"
                />
                {row.frequency && (
                  <Chip
                    label={row.frequency}
                    variant="outlined"
                    size="small"
                    sx={{ textTransform: 'capitalize' }}
                  />
                )}
                {row.plan_tier && (
                  <Chip
                    label={`Tier: ${row.plan_tier}`}
                    variant="outlined"
                    size="small"
                  />
                )}
              </Stack>
              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                spacing={2}
              >
                <Box>
                  <Typography variant="caption" color="text.secondary">Next meeting</Typography>
                  <Typography variant="body2">
                    {row.next_meeting_at ? formatUKDateTime(row.next_meeting_at) : '—'}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Last meeting</Typography>
                  <Typography variant="body2">
                    {row.last_meeting_at ? formatUKDateTime(row.last_meeting_at) : 'Never'}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Total completed</Typography>
                  <Typography variant="body2">
                    {row.total_meetings_completed ?? 0}
                  </Typography>
                </Box>
              </Stack>
            </Stack>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
