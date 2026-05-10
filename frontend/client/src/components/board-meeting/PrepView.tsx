/**
 * Pre-meeting prep view.
 *
 * Brief transition screen shown after the user clicks "Start Meeting" on a
 * prep_ready meeting. Surfaces data-source status, flagged-concern counts,
 * and any carry-forward action items, then hands off to MeetingChat via
 * the "Begin Meeting" button.
 */
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Stack,
  Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import CancelOutlinedIcon from '@mui/icons-material/CancelOutlined';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';
import { ExecutiveMeeting, formatUKDateTime, PrepData } from '@/lib/executiveMeetingsApi';

interface PrepViewProps {
  meeting: ExecutiveMeeting;
  prepData: PrepData | null | undefined;
  onBegin: () => void;
  beginning: boolean;
}

const DATA_SOURCE_LABELS: Array<{ key: string; label: string }> = [
  { key: 'financials',  label: 'Financials' },
  { key: 'invoices',    label: 'Invoices' },
  { key: 'calls',       label: 'Calls' },
  { key: 'emails',      label: 'Emails' },
  { key: 'tasks',       label: 'Tasks' },
  { key: 'calendar',    label: 'Calendar' },
  { key: 'quotes',      label: 'Quotes' },
];

function getSectionAvailability(prepData: PrepData | null | undefined, key: string): boolean {
  if (!prepData) return false;
  if (key === 'financials') return Boolean(prepData.financials?.available);
  if (key === 'invoices')   return Boolean(prepData.invoices?.available);
  if (key === 'calls')      return Boolean(prepData.operations?.calls?.available);
  if (key === 'emails')     return Boolean(prepData.operations?.emails?.available);
  if (key === 'tasks')      return Boolean(prepData.operations?.tasks?.available);
  if (key === 'calendar')   return Boolean(prepData.operations?.calendar?.available);
  if (key === 'quotes')     return Boolean(prepData.operations?.quotes?.available);
  return false;
}

export default function PrepView({ meeting, prepData, onBegin, beginning }: PrepViewProps) {
  const period = prepData?.period;
  const concerns = prepData?.flagged_concerns || [];
  const lastMeeting = prepData?.last_meeting;
  const carryForwardOpen = lastMeeting?.actions_still_open?.length || 0;
  const completeness = prepData?.data_quality?.completeness_score;

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: { xs: 2, md: 4 } }}>
      <Stack spacing={3} sx={{ maxWidth: 720, width: '100%' }}>
        <Box>
          <Typography variant="h1" sx={{ fontSize: { xs: '1.5rem', md: '1.875rem' }, mb: 0.5 }}>
            Aria has prepared for your meeting
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Scheduled for {formatUKDateTime(meeting.scheduled_for)}
          </Typography>
        </Box>

        {period && (
          <Card>
            <CardContent>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                Period under review ({period.comparison_label || 'period-over-period'})
              </Typography>
              <Typography variant="h6">
                {formatUKDateTime(period.current_start || '').replace(',.+$/', '')} – {formatUKDateTime(period.current_end || '')}
              </Typography>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Box>
                <Typography variant="h3" sx={{ mb: 0.5 }}>Data sources</Typography>
                <Typography variant="body2" color="text.secondary">
                  Aria will only reason from sources marked available. Gaps are acknowledged honestly during the meeting.
                </Typography>
              </Box>

              <Stack spacing={1}>
                {DATA_SOURCE_LABELS.map(({ key, label }) => {
                  const available = getSectionAvailability(prepData, key);
                  return (
                    <Stack
                      key={key}
                      direction="row"
                      spacing={1.5}
                      alignItems="center"
                      sx={{
                        px: 1.5,
                        py: 1,
                        border: '1px solid',
                        borderColor: 'divider',
                        borderRadius: 1,
                      }}
                    >
                      {available ? (
                        <CheckCircleOutlineIcon sx={{ color: 'success.main', fontSize: 18 }} />
                      ) : (
                        <CancelOutlinedIcon sx={{ color: 'text.disabled', fontSize: 18 }} />
                      )}
                      <Typography variant="body2" sx={{ flex: 1 }}>{label}</Typography>
                      <Typography
                        variant="caption"
                        color={available ? 'success.main' : 'text.disabled'}
                      >
                        {available ? 'Available' : 'Not available'}
                      </Typography>
                    </Stack>
                  );
                })}
              </Stack>

              {completeness !== undefined && (
                <Typography variant="caption" color="text.secondary">
                  Data completeness: {Math.round((completeness || 0) * 100)}%
                </Typography>
              )}
            </Stack>
          </CardContent>
        </Card>

        {(concerns.length > 0 || carryForwardOpen > 0) && (
          <Card>
            <CardContent>
              <Stack spacing={1.5}>
                {concerns.length > 0 && (
                  <Stack direction="row" spacing={1.5} alignItems="center">
                    <WarningAmberOutlinedIcon sx={{ color: 'warning.main' }} />
                    <Box sx={{ flex: 1 }}>
                      <Typography variant="body2">
                        <strong>{concerns.length}</strong> {concerns.length === 1 ? 'flagged concern' : 'flagged concerns'} to discuss
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Aria will walk through these proportionately during the meeting.
                      </Typography>
                    </Box>
                    <Chip
                      label={`${concerns.length}`}
                      size="small"
                      color="warning"
                      variant="outlined"
                    />
                  </Stack>
                )}

                {carryForwardOpen > 0 && (
                  <>
                    {concerns.length > 0 && <Divider />}
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <CheckCircleOutlineIcon sx={{ color: 'primary.main' }} />
                      <Box sx={{ flex: 1 }}>
                        <Typography variant="body2">
                          <strong>{carryForwardOpen}</strong> action {carryForwardOpen === 1 ? 'item' : 'items'} from last meeting
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          We'll review status on each before moving forward.
                        </Typography>
                      </Box>
                    </Stack>
                  </>
                )}
              </Stack>
            </CardContent>
          </Card>
        )}

        {!prepData && (
          <Alert severity="warning">
            Prep data is unavailable for this meeting. Aria will work from limited context.
          </Alert>
        )}

        <Stack direction="row" justifyContent="flex-end" spacing={1.5}>
          <Button
            variant="contained"
            size="large"
            onClick={onBegin}
            disabled={beginning}
          >
            {beginning ? 'Beginning…' : 'Begin meeting'}
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
}
