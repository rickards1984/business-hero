import { useState, type CSSProperties } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Divider, IconButton, Menu, MenuItem, Tooltip } from '@mui/material';
import { HelpOutline, SettingsOutlined } from '@mui/icons-material';
import ThemeToggle from './ThemeToggle';
import AriaHero from './AriaHero';
import { resolveLogoSrc } from '@/lib/supabase';
import './AriaShellHeader.css';

interface Props {
  activeSection: string;
  businessName: string;
  brandColor?: string | null;
  businessLogo?: string | null;
  isMobile: boolean;
  showQuotes: boolean;
  onHelp: () => void;
  onSignOut: () => void;
}

const departments = [
  ['dashboard', 'Aria'], ['comms', 'Comms'], ['finance', 'Finance'],
  ['quotes', 'Quotes'], ['ai', 'AI Hub'],
];
const settings = [
  ['Branding', '/app/settings/branding'], ['Billing', '/app/settings/billing'],
  ['Email', '/app/settings/email'], ['Voice (Awaz)', '/app/settings/awaz'],
  ['Aria automations', '/app/settings/aria'],
];

function luminance(hex: string) {
  const rgb = hex.slice(1).match(/../g)!.map(value => {
    const channel = parseInt(value, 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
}

export default function AriaShellHeader({ activeSection, businessName, brandColor, businessLogo, isMobile, showQuotes, onHelp, onSignOut }: Props) {
  const { pathname } = useLocation();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const logoSrc = resolveLogoSrc(businessLogo);
  const [logoFailed, setLogoFailed] = useState(false);
  const primary = brandColor && /^#[0-9a-f]{6}$/i.test(brandColor) ? brandColor : '#8E7CFF';
  const light = luminance(primary);
  // Keep the underline visibly distinct from the band and pale/white labels.
  const underline = light > 0.75 || (light + 0.05) / (luminance('#0B0C12') + 0.05) < 3 ? '#8E7CFF' : primary;
  const style = { '--shell-primary': primary, '--shell-primary-text': light > 0.179 ? '#0B0C12' : '#FFFFFF', '--shell-underline': underline } as CSSProperties;
  const avatar = (
    <Link to="/app/assistant/chat" className="aria-shell-ask" aria-label="Ask Aria">
      <img src="/aria-avatar-160.webp" srcSet="/aria-avatar-160.webp 160w, /aria-avatar-320.webp 320w, /aria-avatar-640.jpg 640w" sizes="40px" width={40} height={40} alt="" className="aria-shell-avatar" />
      {!isMobile && <span>Ask Aria</span>}
    </Link>
  );

  return (
    <header className={`aria-shell-header${isMobile ? ' aria-shell-header-mobile' : ''}`} style={style}>
      <div className="aria-shell-inner">
        <div className="aria-shell-top">
          <Link to="/app/dashboard" className="aria-shell-brand" aria-label="Business Hero home">
            <span className="aria-shell-mark">B</span>
            {!isMobile && <span className="aria-shell-wordmark">Business Hero</span>}
            {logoSrc && !logoFailed && (
              // The owner's own logo (Settings → Branding), on a light tile so a
              // dark logo still shows on the dark band.
              <span className="aria-shell-logo">
                <img src={logoSrc} alt="" onError={() => setLogoFailed(true)} />
              </span>
            )}
            <span className="aria-shell-business" title={businessName}>{businessName || 'Business Hero'}</span>
          </Link>
          <div className="aria-shell-actions">
            {isMobile ? avatar : <>
              <Link className="aria-shell-board" to="/app/board-meeting">Hold a board meeting</Link>
              <Tooltip title="Help & Support"><IconButton aria-label="Help & Support" onClick={onHelp}><HelpOutline fontSize="small" /></IconButton></Tooltip>
              <ThemeToggle />
            </>}
            <Tooltip title="Settings">
              <IconButton id="aria-shell-settings" aria-label="Settings" aria-haspopup="menu" aria-controls={anchor ? 'aria-shell-settings-menu' : undefined} aria-expanded={!!anchor} onClick={event => setAnchor(event.currentTarget)}><SettingsOutlined fontSize="small" /></IconButton>
            </Tooltip>
          </div>
        </div>
        {!isMobile && <>
          {pathname.replace(/\/$/, '') === '/app/dashboard' ? (
            <AriaHero variant="band" />
          ) : <div className="aria-shell-compact">{avatar}</div>}
          <nav className="aria-shell-nav" aria-label="Departments">
            {departments.filter(([key]) => key !== 'quotes' || showQuotes).map(([key, label]) => (
              <Link key={key} to={`/app/${key}`} aria-current={activeSection === key ? 'page' : undefined}>{label}</Link>
            ))}
          </nav>
        </>}
      </div>
      <Menu id="aria-shell-settings-menu" anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)} MenuListProps={{ 'aria-labelledby': 'aria-shell-settings' }}>
        {settings.map(([label, path]) => <MenuItem key={path} component={Link} to={path} selected={pathname === path} onClick={() => setAnchor(null)}>{label}</MenuItem>)}
        {isMobile && <MenuItem component={Link} to="/app/board-meeting" onClick={() => setAnchor(null)}>Hold a board meeting</MenuItem>}
        {isMobile && <MenuItem onClick={() => { setAnchor(null); onHelp(); }}>Help & Support</MenuItem>}
        {isMobile && <li className="aria-shell-theme-option"><span>Theme</span><ThemeToggle /></li>}
        <Divider />
        <MenuItem onClick={() => { setAnchor(null); onSignOut(); }}>Sign out</MenuItem>
      </Menu>
    </header>
  );
}
