import TasksPanel from '@/components/TasksPanel';
import { useMe } from '@/hooks/useMe';

export default function DashboardPage() {
  const { data: me } = useMe();
  if (!me?.id) return null;
  return <TasksPanel businessId={me.id} />;
}
