import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { useMe } from '@/hooks/useMe';
import { useIsMobile } from '@/hooks/use-mobile';
import Sidebar from './Sidebar';
import MobileBottomNav from './MobileBottomNav';
import SupportHelpButton from './SupportHelpButton';
import SupportPanel from './SupportPanel';

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
        />
      )}

      <main className="app-content">
        <Outlet />
      </main>

      {isMobile && (
        <MobileBottomNav
          activeSection={activeSection}
          onNavigate={handleNavigate}
        />
      )}

      <SupportHelpButton onClick={() => setSupportPanelOpen(true)} />
      <SupportPanel open={supportPanelOpen} onClose={() => setSupportPanelOpen(false)} />
    </div>
  );
}
