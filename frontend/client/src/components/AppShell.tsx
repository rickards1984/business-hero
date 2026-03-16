import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { IconButton } from '@mui/material';
import { Settings as SettingsIcon } from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { useMe } from '@/hooks/useMe';
import { useIsMobile } from '@/hooks/use-mobile';
import { resolveLogoSrc } from '@/lib/supabase';
import Sidebar from './Sidebar';
import MobileBottomNav from './MobileBottomNav';
import SupportHelpButton from './SupportHelpButton';
import SupportPanel from './SupportPanel';
import ThemeToggle from '@/components/ThemeToggle';

type Section = 'dashboard' | 'comms' | 'finance' | 'ai';

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, signOut, loading: authLoading } = useAuth();
  const { data: me } = useMe();
  const isMobile = useIsMobile();
  const [supportPanelOpen, setSupportPanelOpen] = useState(false);

  const activeSection: Section = useMemo(() => {
    const path = location.pathname;
    if (path.startsWith('/app/comms')) return 'comms';
    if (path.startsWith('/app/finance')) return 'finance';
    if (path.startsWith('/app/ai')) return 'ai';
    return 'dashboard';
  }, [location.pathname]);

  useEffect(() => {
    if (!authLoading && !user) navigate('/login');
  }, [user, authLoading, navigate]);

  if (!user) return null;

  const handleNavigate = (section: string) => navigate(`/app/${section}`);

  return (
    <div className="app-shell">
      {!isMobile && (
        <Sidebar
          activeSection={activeSection}
          onNavigate={handleNavigate}
          businessName={me?.name || ''}
          businessLogo={me?.logo_url}
          userEmail={user.email || ''}
          onSignOut={signOut}
          onHelpClick={() => setSupportPanelOpen(true)}
        />
      )}

      <main className="app-content">
        {isMobile && (
          <div className="mobile-header">
            <div className="mobile-header-brand">
              {me?.logo_url && (
                <img
                  src={resolveLogoSrc(me.logo_url) || ''}
                  alt=""
                  style={{ width: 28, height: 28, borderRadius: 6, objectFit: 'cover' }}
                />
              )}
              <span>{me?.name || 'Business Hero'}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <ThemeToggle />
              <IconButton
                onClick={() => navigate('/app/settings/branding')}
                size="small"
                sx={{ color: 'text.secondary' }}
              >
                <SettingsIcon fontSize="small" />
              </IconButton>
            </div>
          </div>
        )}
        <Outlet />
      </main>

      {isMobile && (
        <MobileBottomNav
          activeSection={activeSection}
          onNavigate={handleNavigate}
        />
      )}

      {isMobile && <SupportHelpButton onClick={() => setSupportPanelOpen(true)} />}
      <SupportPanel open={supportPanelOpen} onClose={() => setSupportPanelOpen(false)} />
    </div>
  );
}
