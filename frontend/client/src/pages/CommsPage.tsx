import { useState } from 'react';
import CallsPanel from '@/components/CallsPanel';
import EmailsTab from '@/components/EmailsTab';
import { useMe } from '@/hooks/useMe';

export default function CommsPage() {
  const { data: me } = useMe();
  const [subTab, setSubTab] = useState<'calls' | 'emails'>('calls');
  if (!me?.id) return null;

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button
          onClick={() => setSubTab('calls')}
          className={`glass-panel sub-tab-btn ${subTab === 'calls' ? 'active-sub-tab' : ''}`}
        >
          Calls
        </button>
        <button
          onClick={() => setSubTab('emails')}
          className={`glass-panel sub-tab-btn ${subTab === 'emails' ? 'active-sub-tab' : ''}`}
        >
          Emails
        </button>
      </div>

      {subTab === 'calls' && <CallsPanel businessId={me.id} />}
      {subTab === 'emails' && <EmailsTab businessId={me.id} />}
    </div>
  );
}
