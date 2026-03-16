import { useState } from 'react';
import InvoicesPanel from '@/components/InvoicesPanel';
import Accounting from '@/pages/Accounting';
import { useMe } from '@/hooks/useMe';

export default function FinancePage() {
  const { data: me } = useMe();
  const [subTab, setSubTab] = useState<'invoices' | 'accounting'>('invoices');
  if (!me?.id) return null;

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button
          onClick={() => setSubTab('invoices')}
          className={`glass-panel sub-tab-btn ${subTab === 'invoices' ? 'active-sub-tab' : ''}`}
        >
          Invoices
        </button>
        <button
          onClick={() => setSubTab('accounting')}
          className={`glass-panel sub-tab-btn ${subTab === 'accounting' ? 'active-sub-tab' : ''}`}
        >
          Accounting
        </button>
      </div>

      {subTab === 'invoices' && <InvoicesPanel businessId={me.id} />}
      {subTab === 'accounting' && <Accounting embedded />}
    </div>
  );
}
