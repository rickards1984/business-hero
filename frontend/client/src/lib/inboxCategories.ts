// ARIA-1a: Mike's inbox categories, the same as services/inbox_sorting.py.
// The server returns every message's category in these keys (an older
// "finance" reads as "money"), so the page needs no mapping of its own.

export type InboxCategory =
  | 'money' | 'new_enquiry' | 'customer' | 'complaint' | 'supplier' | 'scheduling' | 'fyi' | 'junk';

export const INBOX_CATEGORIES: { key: InboxCategory; label: string }[] = [
  { key: 'money', label: 'Money' },
  { key: 'new_enquiry', label: 'New enquiry' },
  { key: 'customer', label: 'Customer' },
  { key: 'complaint', label: 'Complaint' },
  { key: 'supplier', label: 'Supplier' },
  { key: 'scheduling', label: 'Scheduling' },
  { key: 'fyi', label: 'FYI' },
  { key: 'junk', label: 'Junk' },
];

const IMPORTANT = new Set<string>(['money', 'new_enquiry', 'customer', 'complaint']);
export const IMPORTANT_PRIORITY = 4;

/** The one rule, as on the server: Money, New enquiry, Customer or Complaint, or priority 4+ (never Junk). */
export function isImportant(category?: string | null, priority?: number | null): boolean {
  if (!category) return false;
  return IMPORTANT.has(category) || ((priority ?? 0) >= IMPORTANT_PRIORITY && category !== 'junk');
}

export function categoryLabel(category?: string | null): string {
  return INBOX_CATEGORIES.find((c) => c.key === category)?.label ?? 'Not sorted yet';
}

// Left border and chip colour per category.
export const CATEGORY_BORDER: Record<string, string> = {
  money: '#2e7d32',
  new_enquiry: '#7c5cfc',
  customer: '#1976d2',
  complaint: '#d32f2f',
  supplier: '#ed6c02',
  scheduling: '#0288d1',
  fyi: '#9e9e9e',
  junk: '#bdbdbd',
};

export const CATEGORY_CHIP: Record<string, 'error' | 'warning' | 'info' | 'default' | 'primary' | 'success' | 'secondary'> = {
  money: 'success',
  new_enquiry: 'secondary',
  customer: 'primary',
  complaint: 'error',
  supplier: 'warning',
  scheduling: 'info',
  fyi: 'default',
  junk: 'default',
};
