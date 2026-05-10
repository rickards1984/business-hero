import { useMemo } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider as MuiThemeProvider, createTheme, CssBaseline } from '@mui/material';
import { ThemeProvider as NextThemeProvider, useTheme } from 'next-themes';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './lib/queryClient';
import { AuthProvider } from '@/contexts/AuthContext';
import Login from '@/pages/Login';
import AdminDashboard from '@/pages/AdminDashboard';
import AdminBusinessDetail from '@/pages/AdminBusinessDetail';
import ConfirmEmail from '@/pages/ConfirmEmail';
import BrandingSettings from '@/pages/BrandingSettings';
import EmailSettings from '@/pages/EmailSettings';
import EmailOutbox from '@/pages/EmailOutbox';
import Inbox from '@/pages/Inbox';
import Briefings from '@/pages/Briefings';
import AwazSettings from '@/pages/AwazSettings';
import AssistantChat from '@/pages/AssistantChat';
import HelpSupport from '@/pages/HelpSupport';
import AdminSupport from '@/pages/AdminSupport';
import AdminSupportDashboard from '@/pages/AdminSupportDashboard';
import AdminOnboarding from '@/pages/AdminOnboarding';
import AdminOnboardingWizard from '@/pages/AdminOnboardingWizard';
import BillingSettings from '@/pages/BillingSettings';
import Accounting from '@/pages/Accounting';
import AppShell from '@/components/AppShell';
import DashboardPage from '@/pages/DashboardPage';
import CommsPage from '@/pages/CommsPage';
import FinancePage from '@/pages/FinancePage';
import AIHubPage from '@/pages/AIHubPage';
import QuotesPage from '@/pages/QuotesPage';
import BoardMeeting from '@/pages/BoardMeeting';
import MeetingDetailView from '@/components/board-meeting/MeetingDetailView';

const SHARED_TYPOGRAPHY = {
  fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  button: { fontWeight: 600, fontSize: '0.8125rem' },
};

const SHARED_COMPONENTS = {
  MuiButton: {
    styleOverrides: {
      root: {
        textTransform: 'none' as const,
        fontWeight: 600,
        borderRadius: 8,
        fontSize: '0.8125rem',
      },
    },
  },
  MuiChip: {
    styleOverrides: {
      root: { fontWeight: 500 },
    },
  },
  MuiAlert: {
    styleOverrides: {
      root: { borderRadius: 12 },
    },
  },
  MuiLinearProgress: {
    styleOverrides: {
      root: { borderRadius: 9999, height: 6 },
    },
  },
  MuiBackdrop: {
    styleOverrides: {
      root: { backdropFilter: 'blur(4px)' },
    },
  },
};

const lightMuiTheme = createTheme({
  palette: {
    mode: 'light',
    primary:    { main: '#2563EB', light: '#DBEAFE', dark: '#1D4ED8' },
    secondary:  { main: '#8B5CF6', light: '#EDE9FE', dark: '#7C3AED' },
    success:    { main: '#22C55E', light: '#F0FDF4', dark: '#16A34A' },
    warning:    { main: '#F59E0B', light: '#FFFBEB', dark: '#D97706' },
    error:      { main: '#EF4444', light: '#FEF2F2', dark: '#DC2626' },
    background: { default: '#FCFCFD', paper: '#FFFFFF' },
    text:       { primary: '#111827', secondary: '#6B7280' },
    divider: '#E5E7EB',
  },
  shape: { borderRadius: 12 },
  typography: {
    ...SHARED_TYPOGRAPHY,
    h1: { fontWeight: 700, fontSize: '1.5rem', lineHeight: 1.25, color: '#111827' },
    h2: { fontWeight: 700, fontSize: '1.25rem', lineHeight: 1.25, color: '#111827' },
    h3: { fontWeight: 600, fontSize: '1.0625rem', lineHeight: 1.25, color: '#111827' },
    h4: { fontWeight: 600, fontSize: '0.9375rem', lineHeight: 1.25, color: '#1F2937' },
    h5: { fontWeight: 600, fontSize: '0.875rem', lineHeight: 1.25, color: '#1F2937' },
    h6: { fontWeight: 600, fontSize: '0.8125rem', lineHeight: 1.25, color: '#1F2937' },
    body1: { fontSize: '0.875rem', lineHeight: 1.5, color: '#374151' },
    body2: { fontSize: '0.8125rem', lineHeight: 1.5, color: '#6B7280' },
    caption: { fontSize: '0.75rem', lineHeight: 1.5, color: '#9CA3AF' },
  },
  components: {
    ...SHARED_COMPONENTS,
    MuiCssBaseline: {
      styleOverrides: { body: { backgroundColor: '#FCFCFD' } },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          border: '1px solid #F3F4F6',
          boxShadow: '0 1px 3px 0 rgba(0,0,0,0.06), 0 1px 2px -1px rgba(0,0,0,0.06)',
        },
        elevation0: { boxShadow: 'none', border: 'none' },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          border: '1px solid #F3F4F6',
          boxShadow: '0 1px 3px 0 rgba(0,0,0,0.06), 0 1px 2px -1px rgba(0,0,0,0.06)',
          transition: 'box-shadow 200ms, transform 200ms',
          '&:hover': { boxShadow: '0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.05)' },
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none' as const,
          fontWeight: 500,
          fontSize: '0.8125rem',
          '&.Mui-selected': { fontWeight: 600 },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: 'linear-gradient(135deg, var(--color-primary-700) 0%, var(--color-primary-600) 100%)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.12)',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: { borderRadius: 16, boxShadow: '0 20px 25px -5px rgba(0,0,0,0.08), 0 8px 10px -6px rgba(0,0,0,0.04)' },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: 8,
            '&.Mui-focused': { boxShadow: '0 0 0 3px rgba(219,234,254,1)' },
          },
        },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase',
            letterSpacing: '0.05em', color: '#6B7280', borderBottomColor: '#E5E7EB',
          },
        },
      },
    },
    MuiTableBody: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': { fontSize: '0.8125rem', color: '#374151', borderBottomColor: '#F3F4F6' },
          '& .MuiTableRow-root:hover .MuiTableCell-root': { backgroundColor: '#F9FAFB' },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: { paper: { borderRight: '1px solid #F3F4F6' } },
    },
  },
});

const darkMuiTheme = createTheme({
  palette: {
    mode: 'dark',
    primary:    { main: '#7c5cfc', light: '#a78bfa', dark: '#5a3fd4' },
    secondary:  { main: '#2dd48c', light: '#6ee7b7', dark: '#059669' },
    success:    { main: '#2dd48c', light: '#065f46', dark: '#10b981' },
    warning:    { main: '#fbbf24', light: '#78350f', dark: '#f59e0b' },
    error:      { main: '#f87171', light: '#7f1d1d', dark: '#ef4444' },
    background: { default: '#0d0f13', paper: 'rgba(255,255,255,0.04)' },
    text:       { primary: '#e8e6e1', secondary: 'rgba(232,230,225,0.5)' },
    divider: 'rgba(255,255,255,0.08)',
  },
  shape: { borderRadius: 12 },
  typography: {
    ...SHARED_TYPOGRAPHY,
  },
  components: {
    ...SHARED_COMPONENTS,
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: '#0d0f13',
          color: '#e8e6e1',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(255,255,255,0.04)',
          border: '0.5px solid rgba(255,255,255,0.08)',
          backdropFilter: 'blur(20px)',
          color: '#e8e6e1',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(255,255,255,0.04)',
          border: '0.5px solid rgba(255,255,255,0.08)',
          backdropFilter: 'blur(20px)',
          color: '#e8e6e1',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: 'rgba(13,15,19,0.8)',
          backdropFilter: 'blur(20px)',
          borderBottom: '0.5px solid rgba(255,255,255,0.08)',
          boxShadow: 'none',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 500,
          color: '#e8e6e1',
          borderColor: 'rgba(255,255,255,0.15)',
        },
        outlined: {
          borderColor: 'rgba(255,255,255,0.15)',
          color: '#e8e6e1',
          '&:hover': { backgroundColor: 'rgba(255,255,255,0.08)' },
        },
        filled: {
          backgroundColor: 'rgba(255,255,255,0.08)',
          color: '#e8e6e1',
          '&:hover': { backgroundColor: 'rgba(255,255,255,0.12)' },
        },
        colorPrimary: {
          backgroundColor: 'rgba(124,92,252,0.15)',
          color: '#a78bfa',
        },
        colorSuccess: {
          backgroundColor: 'rgba(45,212,140,0.15)',
          color: '#2dd48c',
        },
        colorWarning: {
          backgroundColor: 'rgba(251,191,36,0.15)',
          color: '#fbbf24',
        },
        colorError: {
          backgroundColor: 'rgba(248,113,113,0.15)',
          color: '#f87171',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none' as const,
          fontWeight: 600,
          borderRadius: 8,
        },
        contained: {
          '&:hover': { color: '#ffffff' },
        },
        outlined: {
          borderColor: 'rgba(255,255,255,0.15)',
          color: '#e8e6e1',
          '&:hover': {
            borderColor: 'rgba(255,255,255,0.3)',
            backgroundColor: 'rgba(255,255,255,0.06)',
            color: '#e8e6e1',
          },
        },
        text: {
          color: '#e8e6e1',
          '&:hover': {
            backgroundColor: 'rgba(255,255,255,0.06)',
            color: '#e8e6e1',
          },
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          color: 'rgba(232,230,225,0.6)',
          '&:hover': {
            backgroundColor: 'rgba(255,255,255,0.08)',
            color: '#e8e6e1',
          },
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none' as const,
          fontWeight: 500,
          color: 'rgba(232,230,225,0.5)',
          '&.Mui-selected': { color: '#a78bfa' },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: { backgroundColor: '#7c5cfc' },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          backgroundColor: '#1a1c22',
          border: '0.5px solid rgba(255,255,255,0.1)',
          backdropFilter: 'blur(20px)',
        },
      },
    },
    MuiDialogContentText: {
      styleOverrides: {
        root: { color: 'rgba(232,230,225,0.7)' },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            '& fieldset': { borderColor: 'rgba(255,255,255,0.12)' },
            '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.2)' },
          },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          color: '#e8e6e1',
          '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.12)' },
          '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.25)' },
          '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: '#7c5cfc' },
        },
        input: {
          color: '#e8e6e1',
          '&::placeholder': { color: 'rgba(232,230,225,0.35)', opacity: 1 },
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          color: 'rgba(232,230,225,0.5)',
          '&.Mui-focused': { color: '#a78bfa' },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: { color: '#e8e6e1' },
        icon: { color: 'rgba(232,230,225,0.5)' },
      },
    },
    MuiMenuItem: {
      styleOverrides: {
        root: {
          color: '#e8e6e1',
          '&:hover': { backgroundColor: 'rgba(255,255,255,0.06)' },
          '&.Mui-selected': {
            backgroundColor: 'rgba(124,92,252,0.12)',
            color: '#a78bfa',
            '&:hover': { backgroundColor: 'rgba(124,92,252,0.18)' },
          },
        },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            backgroundColor: 'rgba(255,255,255,0.04)',
            borderBottom: '0.5px solid rgba(255,255,255,0.08)',
            color: 'rgba(232,230,225,0.6)',
            fontWeight: 600,
            fontSize: '12px',
            textTransform: 'uppercase' as const,
            letterSpacing: '0.5px',
          },
        },
      },
    },
    MuiTableBody: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            borderBottom: '0.5px solid rgba(255,255,255,0.06)',
            color: '#e8e6e1',
          },
          '& .MuiTableRow-root:hover': { backgroundColor: 'rgba(255,255,255,0.04)' },
          '& .MuiTableRow-root:hover .MuiTableCell-root': { color: '#e8e6e1' },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { color: '#e8e6e1' },
      },
    },
    MuiCheckbox: {
      styleOverrides: {
        root: {
          color: 'rgba(255,255,255,0.3)',
          '&.Mui-checked': { color: '#7c5cfc' },
        },
      },
    },
    MuiSwitch: {
      styleOverrides: {
        root: {
          '& .MuiSwitch-track': { backgroundColor: 'rgba(255,255,255,0.2)' },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#0d0f13',
          borderRight: '0.5px solid rgba(255,255,255,0.08)',
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { border: '0.5px solid rgba(255,255,255,0.08)' },
        standardSuccess: { backgroundColor: 'rgba(45,212,140,0.1)', color: '#2dd48c' },
        standardWarning: { backgroundColor: 'rgba(251,191,36,0.1)', color: '#fbbf24' },
        standardError: { backgroundColor: 'rgba(248,113,113,0.1)', color: '#f87171' },
        standardInfo: { backgroundColor: 'rgba(96,165,250,0.1)', color: '#60a5fa' },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: '#1a1c22',
          color: '#e8e6e1',
          border: '0.5px solid rgba(255,255,255,0.1)',
          fontSize: '12px',
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: { borderColor: 'rgba(255,255,255,0.08)' },
      },
    },
    MuiFab: {
      styleOverrides: {
        root: {
          backgroundColor: '#7c5cfc',
          color: '#ffffff',
          '&:hover': { backgroundColor: '#5a3fd4' },
        },
      },
    },
    MuiSnackbarContent: {
      styleOverrides: {
        root: {
          backgroundColor: '#1a1c22',
          color: '#e8e6e1',
          border: '0.5px solid rgba(255,255,255,0.1)',
        },
      },
    },
    MuiTypography: {
      styleOverrides: {
        root: { color: 'inherit' },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: 'rgba(255,255,255,0.06)' },
      },
    },
  },
});

function MuiThemeWrapper({ children }: { children: React.ReactNode }) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  const muiTheme = useMemo(() => (isDark ? darkMuiTheme : lightMuiTheme), [isDark]);

  return (
    <MuiThemeProvider theme={muiTheme}>
      <CssBaseline />
      {children}
    </MuiThemeProvider>
  );
}

function App() {
  return (
    <NextThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
      <QueryClientProvider client={queryClient}>
        <MuiThemeWrapper>
          <AuthProvider>
            <BrowserRouter>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/admin" element={<AdminDashboard />} />
                <Route path="/admin/businesses/:id" element={<AdminBusinessDetail />} />
                <Route path="/admin/support" element={<AdminSupportDashboard />} />
                <Route path="/admin/support-legacy" element={<AdminSupport />} />
                <Route path="/admin/onboarding" element={<AdminOnboarding />} />
                <Route path="/admin/onboarding/new" element={<AdminOnboardingWizard />} />
                <Route path="/admin/onboarding/:businessId" element={<AdminOnboardingWizard />} />
                <Route path="/app" element={<AppShell />}>
                  <Route index element={<Navigate to="/app/dashboard" replace />} />
                  <Route path="dashboard" element={<DashboardPage />} />
                  <Route path="comms" element={<CommsPage />} />
                  <Route path="finance" element={<FinancePage />} />
                  <Route path="quotes" element={<QuotesPage />} />
                  <Route path="ai" element={<AIHubPage />} />
                  <Route path="settings/branding" element={<BrandingSettings />} />
                  <Route path="settings/billing" element={<BillingSettings />} />
                  <Route path="settings/email" element={<EmailSettings />} />
                  <Route path="settings/awaz" element={<AwazSettings />} />
                  <Route path="assistant/chat" element={<AssistantChat />} />
                  <Route path="help" element={<HelpSupport />} />
                  <Route path="inbox" element={<Inbox />} />
                  <Route path="briefings" element={<Briefings />} />
                  <Route path="email/outbox" element={<EmailOutbox />} />
                  <Route path="accounting" element={<Accounting />} />
                  <Route path="board-meeting" element={<BoardMeeting />} />
                  <Route path="board-meeting/meeting/:meetingId" element={<MeetingDetailView />} />
                </Route>
                <Route path="/dashboard" element={<Navigate to="/app/dashboard" replace />} />
                <Route path="/settings/email" element={<Navigate to="/app/settings/email" replace />} />
                <Route path="/inbox" element={<Navigate to="/app/inbox" replace />} />
                <Route path="/briefings" element={<Navigate to="/app/briefings" replace />} />
                <Route path="/confirm" element={<ConfirmEmail />} />
                <Route path="/" element={<Navigate to="/login" replace />} />
                <Route path="*" element={<Navigate to="/login" replace />} />
              </Routes>
            </BrowserRouter>
          </AuthProvider>
        </MuiThemeWrapper>
      </QueryClientProvider>
    </NextThemeProvider>
  );
}

export default App;
