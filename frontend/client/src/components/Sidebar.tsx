import { useState } from 'react';
import { Typography, IconButton, Tooltip } from '@mui/material';
import {
  GridViewOutlined,
  ChatOutlined,
  AccountBalanceWalletOutlined,
  AutoAwesomeOutlined,
  Logout as LogoutIcon,
  Settings as SettingsIcon,
  HelpOutline as HelpOutlineIcon,
} from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import ThemeToggle from '@/components/ThemeToggle';
import { resolveLogoSrc } from '@/lib/supabase';

interface SidebarProps {
  activeSection: string;
  onNavigate: (section: string) => void;
  businessName: string;
  businessLogo?: string | null;
  userEmail: string;
  onSignOut: () => void;
  onHelpClick?: () => void;
}

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', Icon: GridViewOutlined },
  { key: 'comms',     label: 'Comms',     Icon: ChatOutlined },
  { key: 'finance',   label: 'Finance',   Icon: AccountBalanceWalletOutlined },
  { key: 'ai',        label: 'AI Hub',    Icon: AutoAwesomeOutlined },
];

const SETTINGS_ITEMS = [
  { label: 'Branding',      path: '/app/settings/branding' },
  { label: 'Billing',       path: '/app/settings/billing' },
  { label: 'Email',         path: '/app/settings/email' },
  { label: 'Voice (Awaz)',  path: '/app/settings/awaz' },
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
  onHelpClick,
}: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const logoUrl = resolveLogoSrc(businessLogo);
  const [settingsOpen, setSettingsOpen] = useState(
    location.pathname.startsWith('/app/settings')
  );

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

      <div className="sidebar-settings-divider" />

      {/* Help & Support */}
      <button
        className="sidebar-nav-item"
        onClick={onHelpClick}
      >
        <HelpOutlineIcon sx={{ fontSize: 20 }} />
        <span>Help & Support</span>
      </button>

      {/* Settings accordion */}
      <div>
        <button
          className={`sidebar-nav-item ${settingsOpen ? 'active' : ''}`}
          onClick={() => setSettingsOpen(!settingsOpen)}
        >
          <SettingsIcon sx={{ fontSize: 20 }} />
          <span style={{ flex: 1 }}>Settings</span>
          <span style={{
            fontSize: 10,
            transition: 'transform 200ms',
            transform: settingsOpen ? 'rotate(90deg)' : 'rotate(0deg)',
            opacity: 0.5,
          }}>
            ▸
          </span>
        </button>

        {settingsOpen && (
          <div className="sidebar-settings-submenu">
            {SETTINGS_ITEMS.map((item) => {
              const isActive = location.pathname === item.path;
              return (
                <button
                  key={item.path}
                  className={`sidebar-settings-item ${isActive ? 'active' : ''}`}
                  onClick={() => navigate(item.path)}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="sidebar-settings-divider" />

      {/* Bottom section */}
      <div className="sidebar-footer">
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
