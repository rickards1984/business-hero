import InvoicesPanel from '@/components/InvoicesPanel';
import { useMe } from '@/hooks/useMe';

export default function FinancePage() {
  const { data: me } = useMe();
  if (!me?.id) return null;
  return <InvoicesPanel businessId={me.id} />;
}
