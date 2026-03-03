export const TASK_CATEGORIES = [
  { id: 'email_followup', label: 'Email Follow-up', color: '#3B82F6' },
  { id: 'lead_contact', label: 'Lead to Contact', color: '#10B981' },
  { id: 'meeting_book', label: 'Meeting to Book', color: '#8B5CF6' },
  { id: 'phone_call', label: 'Phone Call', color: '#F59E0B' },
  { id: 'invoice_payment', label: 'Invoice / Payment', color: '#EF4444' },
  { id: 'proposal_quote', label: 'Proposal / Quote', color: '#EC4899' },
  { id: 'review_approve', label: 'Review / Approve', color: '#06B6D4' },
  { id: 'general', label: 'General To-Do', color: '#6B7280' },
] as const;

export const TASK_PRIORITIES = [
  { id: 'high', label: 'High', color: '#EF4444', icon: '🔴' },
  { id: 'medium', label: 'Medium', color: '#F59E0B', icon: '🟡' },
  { id: 'low', label: 'Low', color: '#10B981', icon: '🟢' },
] as const;

export const getCategoryColor = (categoryId: string): string =>
  TASK_CATEGORIES.find(c => c.id === categoryId)?.color || '#6B7280';

export const getCategoryLabel = (categoryId: string): string =>
  TASK_CATEGORIES.find(c => c.id === categoryId)?.label || 'General';

export const getPriorityColor = (priorityId: string): string =>
  TASK_PRIORITIES.find(p => p.id === priorityId)?.color || '#F59E0B';

export const isOverdue = (dueAt: string, status: string): boolean =>
  new Date(dueAt) < new Date() && status !== 'completed';

export const isToday = (date: Date): boolean =>
  date.toDateString() === new Date().toDateString();

export const formatDueDate = (dateString: string): string => {
  const date = new Date(dateString);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === tomorrow.toDateString()) return 'Tomorrow';

  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: date.getFullYear() !== today.getFullYear() ? 'numeric' : undefined,
  });
};
