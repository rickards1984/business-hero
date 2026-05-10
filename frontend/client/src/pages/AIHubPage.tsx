import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import AssistantChat from '@/pages/AssistantChat';
import ReceptionistTab from '@/components/ReceptionistTab';
import CeoBriefingTab from '@/components/CeoBriefingTab';
import BookingSettingsPanel from '@/components/BookingSettingsPanel';
import BoardMeeting from '@/pages/BoardMeeting';
import { useMe } from '@/hooks/useMe';

type SubTab = 'board-meeting' | 'aria' | 'receptionist' | 'briefing' | 'booking';

const VALID_SUB_TABS: SubTab[] = [
  'board-meeting',
  'aria',
  'receptionist',
  'briefing',
  'booking',
];

export default function AIHubPage() {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Default to Board Meeting — it's the most strategic AI Hub feature.
  const [subTab, setSubTab] = useState<SubTab>('board-meeting');

  useEffect(() => {
    const tab = searchParams.get('tab') as SubTab | null;
    if (tab && VALID_SUB_TABS.includes(tab)) {
      setSubTab(tab);
    }
  }, [searchParams]);

  if (!me?.id) return null;

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {/* Board Meeting — strategic flagship, listed first, with subtle
            primary-coloured emphasis when active. */}
        <button
          onClick={() => setSubTab('board-meeting')}
          className={`glass-panel sub-tab-btn ${subTab === 'board-meeting' ? 'active-sub-tab' : ''}`}
          style={{
            borderColor:
              subTab === 'board-meeting'
                ? 'hsl(var(--primary))'
                : undefined,
            boxShadow:
              subTab === 'board-meeting'
                ? '0 0 0 1px hsl(var(--primary) / 0.35)'
                : undefined,
          }}
        >
          Board Meeting
        </button>
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

      {subTab === 'board-meeting' && <BoardMeeting embedded />}
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
