import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import AssistantChat from '@/pages/AssistantChat';
import ReceptionistTab from '@/components/ReceptionistTab';
import CeoBriefingTab from '@/components/CeoBriefingTab';
import BookingSettingsPanel from '@/components/BookingSettingsPanel';
import { useMe } from '@/hooks/useMe';

export default function AIHubPage() {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [subTab, setSubTab] = useState<'aria' | 'receptionist' | 'briefing' | 'booking'>('aria');

  useEffect(() => {
    const tab = searchParams.get('tab');
    if (tab === 'aria') setSubTab('aria');
    if (tab === 'receptionist') setSubTab('receptionist');
    if (tab === 'briefing') setSubTab('briefing');
    if (tab === 'booking') setSubTab('booking');
  }, [searchParams]);

  if (!me?.id) return null;

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button
          onClick={() => setSubTab('aria')}
          className={`glass-panel sub-tab-btn ${subTab === 'aria' ? 'active-sub-tab' : ''}`}
        >
          Aria
        </button>
        <button
          onClick={() => setSubTab('receptionist')}
          className={`glass-panel sub-tab-btn ${subTab === 'receptionist' ? 'active-sub-tab' : ''}`}
        >
          Receptionist
        </button>
        <button
          onClick={() => setSubTab('briefing')}
          className={`glass-panel sub-tab-btn ${subTab === 'briefing' ? 'active-sub-tab' : ''}`}
        >
          CEO Briefing
        </button>
        <button
          onClick={() => setSubTab('booking')}
          className={`glass-panel sub-tab-btn ${subTab === 'booking' ? 'active-sub-tab' : ''}`}
        >
          Booking
        </button>
      </div>

      {subTab === 'aria' && <AssistantChat embedded />}
      {subTab === 'receptionist' && (
        <ReceptionistTab
          businessId={me.id}
          onViewCalls={() => navigate('/app/comms?tab=calls')}
        />
      )}
      {subTab === 'briefing' && <CeoBriefingTab />}
      {subTab === 'booking' && <BookingSettingsPanel />}
    </div>
  );
}
