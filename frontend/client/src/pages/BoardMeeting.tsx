/**
 * Executive Board Meeting — Main Hub Page.
 *
 * Tab strip with: Overview (default), Settings, History, Goals, Action Items.
 * Tier-gated: starter/paused see UpgradePrompt; pro/business/beta see the hub.
 */
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Container,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import {
  AccessCheck,
  ActionItem,
  ExecutiveMeeting,
  ExecutiveMeetingSettings,
  Goal,
  checkAccess,
  formatUKDateTime,
  getSettings,
  listActionItems,
  listGoals,
  listMeetings,
} from '@/lib/executiveMeetingsApi';
import BoardMeetingOverview from '@/components/board-meeting/BoardMeetingOverview';
import SettingsPanel from '@/components/board-meeting/SettingsPanel';
import MeetingList from '@/components/board-meeting/MeetingList';
import GoalsDashboard from '@/components/board-meeting/GoalsDashboard';
import ActionItemsDashboard from '@/components/board-meeting/ActionItemsDashboard';
import UpgradePrompt from '@/components/board-meeting/UpgradePrompt';

type TabKey = 'overview' | 'settings' | 'history' | 'goals' | 'actions';

const VALID_TABS: TabKey[] = ['overview', 'settings', 'history', 'goals', 'actions'];

interface BoardMeetingProps {
  /** If true, hides outer Container padding because this page is embedded
   * inside another tab (e.g. AI Hub). Defaults to false (standalone). */
  embedded?: boolean;
}

export default function BoardMeeting({ embedded = false }: BoardMeetingProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  const initialTab = (searchParams.get('tab') as TabKey) || 'overview';
  const [tab, setTab] = useState<TabKey>(
    VALID_TABS.includes(initialTab) ? initialTab : 'overview',
  );

  const [access, setAccess] = useState<AccessCheck | null>(null);
  const [settings, setSettings] = useState<ExecutiveMeetingSettings | null>(null);
  const [meetings, setMeetings] = useState<ExecutiveMeeting[]>([]);
  const [actionItems, setActionItems] = useState<ActionItem[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [meetingsLoading, setMeetingsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const changeTab = (next: TabKey) => {
    setTab(next);
    const params = new URLSearchParams(searchParams);
    if (next === 'overview') {
      params.delete('tab');
    } else {
      params.set('tab', next);
    }
    setSearchParams(params, { replace: true });
  };

  // Sync from URL when search params change externally
  useEffect(() => {
    const urlTab = (searchParams.get('tab') as TabKey) || 'overview';
    if (VALID_TABS.includes(urlTab) && urlTab !== tab) {
      setTab(urlTab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Access check first
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const acc = await checkAccess();
        if (!cancelled) setAccess(acc);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || 'Failed to check access');
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Load data in parallel once access is confirmed
  useEffect(() => {
    if (!access?.has_access) return;
    let cancelled = false;
    setLoading(true);

    Promise.all([
      getSettings().catch(() => null),
      listMeetings(20).catch(() => []),
      listActionItems().catch(() => []),
      listGoals().catch(() => []),
    ]).then(([s, m, a, g]) => {
      if (cancelled) return;
      setSettings(s);
      setMeetings(m || []);
      setActionItems(a || []);
      setGoals(g || []);
      setLoading(false);
      setMeetingsLoading(false);
    });
    return () => { cancelled = true; };
  }, [access?.has_access]);

  // ----- Access check fallback states -----
  if (!access && !error) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }
  if (error) {
    return (
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Alert severity="error">{error}</Alert>
      </Container>
    );
  }
  if (access && !access.has_access) {
    return (
      <Container maxWidth="lg" sx={{ py: embedded ? 0 : 3 }}>
        <UpgradePrompt
          currentTier={access.current_tier}
          requiredTier={access.required_tier}
        />
      </Container>
    );
  }

  // ----- Main hub -----
  const statusBadge = (() => {
    const inProgress = meetings.find((m) => m.status === 'in_progress');
    const ready = meetings.find((m) => m.status === 'prep_ready');
    if (inProgress) {
      return <Chip label="Meeting in progress" color="primary" size="small" />;
    }
    if (ready) {
      return <Chip label="Meeting ready" color="success" size="small" />;
    }
    if (settings?.enabled && settings.next_meeting_at) {
      return (
        <Chip
          label={`Next: ${formatUKDateTime(settings.next_meeting_at)}`}
          variant="outlined"
          size="small"
        />
      );
    }
    return null;
  })();

  const content = (
    <Stack spacing={3}>
      <Box>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1.5}
          alignItems={{ sm: 'center' }}
          justifyContent="space-between"
        >
          <Box>
            <Typography variant="h1" sx={{ fontSize: { xs: '1.5rem', md: '1.875rem' } }}>
              Executive Board Meeting
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Your strategic review, on the schedule that works for you.
            </Typography>
          </Box>
          {statusBadge}
        </Stack>
      </Box>

      <Tabs
        value={tab}
        onChange={(_, v: TabKey) => changeTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Tab value="overview" label="Overview" />
        <Tab value="settings" label="Settings" />
        <Tab value="history"  label="History" />
        <Tab value="goals"    label="Goals" />
        <Tab value="actions"  label="Action items" />
      </Tabs>

      {loading && tab === 'overview' ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <Box>
          {tab === 'overview' && (
            <BoardMeetingOverview
              settings={settings}
              meetings={meetings}
              actionItems={actionItems}
              goals={goals}
              onChangeTab={(t) => changeTab(t as TabKey)}
            />
          )}
          {tab === 'settings' && (
            <SettingsPanel hasAdvanced={access?.has_advanced || false} />
          )}
          {tab === 'history' && (
            <MeetingList
              meetings={meetings}
              loading={meetingsLoading}
              error={null}
            />
          )}
          {tab === 'goals' && <GoalsDashboard />}
          {tab === 'actions' && <ActionItemsDashboard />}
        </Box>
      )}
    </Stack>
  );

  if (embedded) {
    return <Box>{content}</Box>;
  }

  return (
    <Container maxWidth="lg" sx={{ py: { xs: 2, md: 3 } }}>
      {content}
    </Container>
  );
}
