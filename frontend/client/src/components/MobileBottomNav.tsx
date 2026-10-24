import {
  GridViewOutlined,
  ChatOutlined,
  AccountBalanceWalletOutlined,
  RequestQuoteOutlined,
  AutoAwesomeOutlined,
  CampaignOutlined,
} from '@mui/icons-material';

interface MobileBottomNavProps {
  activeSection: string;
  onNavigate: (section: string) => void;
  showQuotes?: boolean;
  showOutreach?: boolean;
  outreachNew?: boolean;
}

const BASE_NAV_ITEMS = [
  { key: 'dashboard', label: 'Home',    Icon: GridViewOutlined },
  { key: 'comms',     label: 'Comms',   Icon: ChatOutlined },
  { key: 'outreach',  label: 'Outreach', Icon: CampaignOutlined, feature: 'outreach' as const },
  { key: 'finance',   label: 'Finance', Icon: AccountBalanceWalletOutlined },
  { key: 'quotes',    label: 'Quotes',  Icon: RequestQuoteOutlined, feature: 'quotes' as const },
  { key: 'ai',        label: 'AI',      Icon: AutoAwesomeOutlined },
];

export default function MobileBottomNav({ activeSection, onNavigate, showQuotes = true, showOutreach = false, outreachNew = false }: MobileBottomNavProps) {
  const navItems = BASE_NAV_ITEMS.filter(item => !item.feature
    || (item.feature === 'quotes' && showQuotes) || (item.feature === 'outreach' && showOutreach));
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
            <span className="mobile-bottom-nav-icon">
              <Icon sx={{ fontSize: 22 }} />
              {key === 'outreach' && outreachNew && <span className="mobile-bottom-nav-dot" aria-label="New" />}
            </span>
            <span>{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
