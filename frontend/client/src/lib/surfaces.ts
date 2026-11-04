import type { Theme } from '@mui/material/styles';

// UI-2: soft panel backgrounds that follow light and dark mode. `grey.50` and
// `grey.100` are near-white in both MUI themes, so panels using them stayed
// white in dark mode with barely readable text (Mike, 3 Nov 2026). Light mode
// keeps exactly the colour it had.
export const softSurface = (t: Theme) => (t.palette.mode === 'dark' ? 'rgba(255, 255, 255, 0.04)' : t.palette.grey[50]);
export const softSurfaceStrong = (t: Theme) => (t.palette.mode === 'dark' ? 'rgba(255, 255, 255, 0.07)' : t.palette.grey[100]);
