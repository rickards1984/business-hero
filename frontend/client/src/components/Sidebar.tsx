import { Typography, IconButton, Tooltip } from '@mui/material';
import {
  GridViewOutlined,
  ChatOutlined,
  AccountBalanceWalletOutlined,
  AutoAwesomeOutlined,
  Logout as LogoutIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import ThemeToggle from '@/components/ThemeToggle';
import { resolveLogoSrc } from '@/lib/supabase';

interface SidebarProps {
  activeSection: string;
  onNavigate: (section: string) => void;
  businessName: string;
  businessLogo?: string | null;
  userEmail: string;
  onSignOut: () => void;
}

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', Icon: GridViewOutlined },
  { key: 'comms',     label: 'Comms',     Icon: ChatOutlined },
  { key: 'finance',   label: 'Finance',   Icon: AccountBalanceWalletOutlined },
  { key: 'ai',        label: 'AI Hub',    Icon: AutoAwesomeOutlined },
];

function getInitials(name: string): string {
  return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
}

export default function Sidebar({
  activeSection,
  onNavigate,
  businessName,
  businessLogo,
  userEmail,
  onSignOut,
}: SidebarProps) {
  const navigate = useNavigate();
  const logoUrl = resolveLogoSrc(businessLogo);

  return (
    <aside className="sidebar">
      {/* Business branding */}
      <div className="sidebar-brand" onClick={() => onNavigate('dashboard')} style={{ cursor: 'pointer' }}>
        {logoUrl ? (
          <img src={logoUrl} alt={businessName} className="sidebar-brand-logo" />
        ) : (
          <div className="sidebar-brand-fallback">
            {getInitials(businessName || 'BH')}
          </div>
        )}
        <span className="sidebar-brand-name">{businessName || 'Business Hero'}</span>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {NAV_ITEMS.map(({ key, label, Icon }) => {
          const isActive = activeSection === key;
          return (
            <button
              key={key}
              className={`sidebar-nav-item ${isActive ? 'active' : ''}`}
              onClick={() => onNavigate(key)}
            >
              <Icon sx={{ fontSize: 20 }} />
              <span>{label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-spacer" />

      {/* Bottom section */}
      <div className="sidebar-footer">
        <Tooltip title="Settings" placement="right">
          <IconButton
            size="small"
            onClick={() => navigate('/app/settings/branding')}
            sx={{ color: 'rgba(232,230,225,0.5)', '&:hover': { color: '#e8e6e1' } }}
          >
            <SettingsIcon sx={{ fontSize: 18 }} />
          </IconButton>
        </Tooltip>
        <ThemeToggle />
        <div className="sidebar-user">
          <Typography
            sx={{
              fontSize: '11px',
              color: 'rgba(232,230,225,0.4)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: 130,
            }}
          >
            {userEmail}
          </Typography>
        </div>
        <Tooltip title="Sign out" placement="right">
          <IconButton
            size="small"
            onClick={onSignOut}
            sx={{ color: 'rgba(232,230,225,0.4)', '&:hover': { color: '#f87171' } }}
          >
            <LogoutIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      </div>
    </aside>
  );
}
