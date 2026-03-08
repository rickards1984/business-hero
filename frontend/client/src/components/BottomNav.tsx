import { Box, Typography, Badge } from '@mui/material';
import {
  Task as TaskIcon,
  Phone as PhoneIcon,
  Email as EmailIcon,
  SmartToy as SmartToyIcon,
} from '@mui/icons-material';

interface BottomNavProps {
  activeTab: number;
  onTabChange: (tab: number) => void;
  counts?: {
    tasks?: number;
    calls?: number;
    emails?: number;
  };
}

const NAV_ITEMS = [
  { tab: 0, label: 'Tasks', Icon: TaskIcon, countKey: 'tasks' as const },
  { tab: 1, label: 'Calls', Icon: PhoneIcon, countKey: 'calls' as const },
  { tab: 3, label: 'Emails', Icon: EmailIcon, countKey: 'emails' as const },
  { tab: 4, label: 'AI Recept.', Icon: SmartToyIcon, countKey: undefined },
];

export default function BottomNav({ activeTab, onTabChange, counts }: BottomNavProps) {
  return (
    <Box
      component="nav"
      sx={{
        display: { xs: 'flex', md: 'none' },
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: 64,
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        bgcolor: 'white',
        borderTop: '1px solid var(--color-neutral-100)',
        boxShadow: '0 -4px 12px rgba(0,0,0,0.05)',
        zIndex: 20,
        alignItems: 'center',
        justifyContent: 'space-around',
      }}
    >
      {NAV_ITEMS.map(({ tab, label, Icon, countKey }) => {
        const isActive = activeTab === tab;
        const count = countKey && counts ? counts[countKey] : undefined;
        return (
          <Box
            key={tab}
            component="button"
            onClick={() => onTabChange(tab)}
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '2px',
              p: '4px 12px',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              position: 'relative',
              color: isActive ? 'var(--color-primary-600)' : 'var(--color-neutral-400)',
              transition: 'color 150ms cubic-bezier(0.4,0,0.2,1)',
              '&::before': isActive
                ? {
                    content: '""',
                    position: 'absolute',
                    top: -1,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: 20,
                    height: 3,
                    borderRadius: '0 0 3px 3px',
                    bgcolor: 'var(--color-primary-600)',
                  }
                : {},
            }}
          >
            <Badge
              badgeContent={count && count > 0 ? (count > 99 ? '99+' : count) : undefined}
              color="error"
              sx={{
                '& .MuiBadge-badge': {
                  fontSize: 9,
                  height: 16,
                  minWidth: 16,
                  padding: '0 4px',
                },
              }}
            >
              <Icon sx={{ fontSize: 22 }} />
            </Badge>
            <Typography
              sx={{
                fontSize: '10px',
                fontWeight: isActive ? 600 : 500,
                lineHeight: 1,
                color: 'inherit',
              }}
            >
              {label}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
}
