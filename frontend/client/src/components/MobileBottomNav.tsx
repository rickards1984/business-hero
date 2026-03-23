import {
  GridViewOutlined,
  ChatOutlined,
  AccountBalanceWalletOutlined,
  RequestQuoteOutlined,
  AutoAwesomeOutlined,
} from '@mui/icons-material';

interface MobileBottomNavProps {
  activeSection: string;
  onNavigate: (section: string) => void;
  showQuotes?: boolean;
}

const BASE_NAV_ITEMS = [
  { key: 'dashboard', label: 'Home',    Icon: GridViewOutlined },
  { key: 'comms',     label: 'Comms',   Icon: ChatOutlined },
  { key: 'finance',   label: 'Finance', Icon: AccountBalanceWalletOutlined },
  { key: 'quotes',    label: 'Quotes',  Icon: RequestQuoteOutlined, feature: 'quotes' as const },
  { key: 'ai',        label: 'AI',      Icon: AutoAwesomeOutlined },
];

export default function MobileBottomNav({ activeSection, onNavigate, showQuotes = true }: MobileBottomNavProps) {
  const navItems = BASE_NAV_ITEMS.filter(item => !item.feature || (item.feature === 'quotes' && showQuotes));
  return (
    <nav className="mobile-bottom-nav">
      {navItems.map(({ key, label, Icon }) => {
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
