import { useTheme } from 'next-themes';
import { IconButton, Tooltip } from '@mui/material';
import { DarkMode, LightMode } from '@mui/icons-material';

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <Tooltip title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
      <IconButton
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        sx={{ color: 'text.secondary' }}
        size="small"
      >
        {theme === 'dark' ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
      </IconButton>
    </Tooltip>
  );
}
