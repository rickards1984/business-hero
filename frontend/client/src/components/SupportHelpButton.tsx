import { useState, useEffect, useCallback } from 'react';
import { apiRequest } from '@/lib/queryClient';

interface SupportHelpButtonProps {
  onClick: () => void;
}

export default function SupportHelpButton({ onClick }: SupportHelpButtonProps) {
  const [unreadCount, setUnreadCount] = useState(0);

  const checkUnread = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/support/conversations');
      const convos = await res.json();
      const count = (convos as any[]).filter(
        (c) =>
          ['awaiting_reply', 'in_progress'].includes(c.status) &&
          c.last_admin_reply_at &&
          (!c.last_message_at || new Date(c.last_admin_reply_at) > new Date(c.last_message_at))
      ).length;
      setUnreadCount(count);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    checkUnread();
    const interval = setInterval(checkUnread, 60_000);
    return () => clearInterval(interval);
  }, [checkUnread]);

  return (
    <button className="support-help-btn" onClick={onClick} title="Help & Support">
      ?
      {unreadCount > 0 && (
        <span className="support-help-btn__badge">{unreadCount > 9 ? '9+' : unreadCount}</span>
      )}
    </button>
  );
}
