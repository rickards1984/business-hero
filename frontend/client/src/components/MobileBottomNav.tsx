import {
  GridViewOutlined,
  ChatOutlined,
  AccountBalanceWalletOutlined,
  AutoAwesomeOutlined,
} from '@mui/icons-material';

interface MobileBottomNavProps {
  activeSection: string;
  onNavigate: (section: string) => void;
}

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', Icon: GridViewOutlined },
  { key: 'comms',     label: 'Comms',     Icon: ChatOutlined },
  { key: 'finance',   label: 'Finance',   Icon: AccountBalanceWalletOutlined },
  { key: 'ai',        label: 'AI Hub',    Icon: AutoAwesomeOutlined },
];

export default function MobileBottomNav({ activeSection, onNavigate }: MobileBottomNavProps) {
  return (
    <nav className="mobile-bottom-nav">
      {NAV_ITEMS.map(({ key, label, Icon }) => {
        const isActive = activeSection === key;
        return (
          <button
            key={key}
            className={`mobile-bottom-nav-item ${isActive ? 'active' : ''}`}
            onClick={() => onNavigate(key)}
          >
            <Icon sx={{ fontSize: 22 }} />
            <span>{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
