/**
 * Tier upgrade prompt for Starter (and paused) users.
 *
 * Shown when /v1/executive-meetings/access-check returns has_access=false.
 * Tasteful, not aggressive — the feature genuinely helps and the upgrade
 * copy should reflect that.
 */
import { Box, Button, Card, CardContent, Stack, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import GroupsIcon from '@mui/icons-material/Groups';
import InsightsIcon from '@mui/icons-material/Insights';
import AssignmentTurnedInIcon from '@mui/icons-material/AssignmentTurnedIn';

interface UpgradePromptProps {
  currentTier?: string;
  requiredTier?: string | null;
}

export default function UpgradePrompt({ currentTier, requiredTier }: UpgradePromptProps) {
  const navigate = useNavigate();
  const needsTier = (requiredTier || 'Pro').toLowerCase();
  const niceTier = needsTier.charAt(0).toUpperCase() + needsTier.slice(1);

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: { xs: 4, md: 8 } }}>
      <Card sx={{ maxWidth: 720, width: '100%' }}>
        <CardContent sx={{ p: { xs: 3, md: 5 } }}>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h1" sx={{ fontSize: { xs: '1.5rem', md: '1.875rem' }, mb: 1 }}>
                Take your business to the next level
              </Typography>
              <Typography variant="body1" color="text.secondary">
                Weekly or monthly executive board meetings with Aria, your AI strategic advisor.
                Available on the {niceTier} plan and above.
              </Typography>
            </Box>

            <Stack spacing={2.5} sx={{ pt: 1 }}>
              <Stack direction="row" spacing={2} alignItems="flex-start">
                <InsightsIcon sx={{ color: 'primary.main', mt: 0.5 }} />
                <Box>
                  <Typography variant="h6">Strategic review across every part of your business</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Aria pulls in your financials, invoices, calls, emails, tasks and goals
                    before each meeting, so the conversation starts from facts.
                  </Typography>
                </Box>
              </Stack>

              <Stack direction="row" spacing={2} alignItems="flex-start">
                <GroupsIcon sx={{ color: 'primary.main', mt: 0.5 }} />
                <Box>
                  <Typography variant="h6">Honest, direct insights — not a cheerleader</Typography>
                  <Typography variant="body2" color="text.secondary">
                    She'll call out concerns before they become crises, calibrated to your
                    business's actual scale, and push back when warranted.
                  </Typography>
                </Box>
              </Stack>

              <Stack direction="row" spacing={2} alignItems="flex-start">
                <AssignmentTurnedInIcon sx={{ color: 'primary.main', mt: 0.5 }} />
                <Box>
                  <Typography variant="h6">Action items, goals, and accountability built in</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Every commitment is captured automatically. The next meeting reviews
                    what got done, what didn't, and why.
                  </Typography>
                </Box>
              </Stack>
            </Stack>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ pt: 2 }}>
              <Button
                variant="contained"
                size="large"
                onClick={() => navigate('/app/settings/billing')}
              >
                Upgrade to {niceTier}
              </Button>
              <Button
                variant="text"
                size="large"
                href="https://businessherouk.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                Learn more
              </Button>
            </Stack>

            {currentTier && (
              <Typography variant="caption" color="text.secondary">
                Your current plan: {currentTier}
              </Typography>
            )}
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
