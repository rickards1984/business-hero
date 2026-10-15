import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { Box, CircularProgress, Typography, useMediaQuery } from '@mui/material';
import { Capacitor } from '@capacitor/core';
import { useAuth } from '@/contexts/AuthContext';
import { useMe } from '@/hooks/useMe';
import { isFeatureEnabled } from '@/lib/entitlements';
import AriaShellHeader from './AriaShellHeader';
import MobileBottomNav from './MobileBottomNav';
import SupportHelpButton from './SupportHelpButton';
import SupportPanel from './SupportPanel';
import SectionErrorBoundary from './SectionErrorBoundary';
import SubscriptionBanner from './SubscriptionBanner';

type Section = 'dashboard' | 'comms' | 'finance' | 'quotes' | 'ai' | '';

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, session, signOut, loading: authLoading } = useAuth();
  const { data: me } = useMe();
  const narrowScreen = useMediaQuery('(max-width: 768px)');
  const isMobile = narrowScreen || Capacitor.isNativePlatform();
  const [supportPanelOpen, setSupportPanelOpen] = useState(false);

  // Canonical key, resolved through the plan. `quoting_enabled` was renamed
  // by migration 033 SECTION 6. Presentation only — PART D's server-side gate
  // is the enforcement; hiding a nav item is not refusing a request.
  const showQuotes = isFeatureEnabled(me?.plan_tier, me?.feature_flags, 'quoting');

  const activeSection: Section = useMemo(() => {
    const path = location.pathname;
    if (['/app/comms', '/app/inbox', '/app/email/outbox'].some(prefix => path.startsWith(prefix))) return 'comms';
    if (['/app/finance', '/app/accounting'].some(prefix => path.startsWith(prefix))) return 'finance';
    if (path.startsWith('/app/quotes')) return 'quotes';
    if (['/app/ai', '/app/board-meeting', '/app/briefings'].some(prefix => path.startsWith(prefix))) return 'ai';
    if (['/app/dashboard', '/app/assistant/chat'].some(prefix => path.startsWith(prefix))) return 'dashboard';
    return '';
  }, [location.pathname]);

  useEffect(() => {
    if (!authLoading && (!user || !session)) navigate('/login');
  }, [user, session, authLoading, navigate]);

  if (authLoading) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: 2 }}>
        <CircularProgress size={32} />
        <Typography variant="body2" color="text.secondary">Loading...</Typography>
      </Box>
    );
  }

  if (!user) return null;

  const handleNavigate = (section: string) => navigate(`/app/${section}`);

  return (
    <div className={`app-shell aria-shell${isMobile ? ' aria-shell-mobile' : ''}`}>
      <AriaShellHeader
        activeSection={activeSection}
        businessName={me?.name || ''}
        brandColor={me?.brand_color}
        isMobile={isMobile}
        showQuotes={showQuotes}
        onSignOut={signOut}
        onHelp={() => setSupportPanelOpen(true)}
      />
      <main className="app-content">
        <SectionErrorBoundary>
          <SubscriptionBanner />
          <Outlet />
        </SectionErrorBoundary>
      </main>

      {isMobile && (
        <MobileBottomNav
          activeSection={activeSection}
          onNavigate={handleNavigate}
          showQuotes={showQuotes}
        />
      )}

      {isMobile && <SupportHelpButton onClick={() => setSupportPanelOpen(true)} />}
      <SupportPanel open={supportPanelOpen} onClose={() => setSupportPanelOpen(false)} />
    </div>
  );
}
