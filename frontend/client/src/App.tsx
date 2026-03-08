import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './lib/queryClient';
import { AuthProvider } from '@/contexts/AuthContext';
import Login from '@/pages/Login';
import AdminDashboard from '@/pages/AdminDashboard';
import AdminBusinessDetail from '@/pages/AdminBusinessDetail';
import BusinessDashboard from '@/pages/BusinessDashboard';
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
import AdminOnboarding from '@/pages/AdminOnboarding';
import AdminOnboardingWizard from '@/pages/AdminOnboardingWizard';
import BillingSettings from '@/pages/BillingSettings';
import Accounting from '@/pages/Accounting';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#2563EB',
      light: '#DBEAFE',
      dark: '#1D4ED8',
    },
    secondary: {
      main: '#8B5CF6',
      light: '#EDE9FE',
      dark: '#7C3AED',
    },
    success: {
      main: '#22C55E',
      light: '#F0FDF4',
      dark: '#16A34A',
    },
    warning: {
      main: '#F59E0B',
      light: '#FFFBEB',
      dark: '#D97706',
    },
    error: {
      main: '#EF4444',
      light: '#FEF2F2',
      dark: '#DC2626',
    },
    background: {
      default: '#FCFCFD',
      paper: '#FFFFFF',
    },
    text: {
      primary: '#111827',
      secondary: '#6B7280',
    },
    divider: '#E5E7EB',
  },
  shape: {
    borderRadius: 12,
  },
  typography: {
    fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    h1: { fontWeight: 700, fontSize: '1.5rem', lineHeight: 1.25, color: '#111827' },
    h2: { fontWeight: 700, fontSize: '1.25rem', lineHeight: 1.25, color: '#111827' },
    h3: { fontWeight: 600, fontSize: '1.0625rem', lineHeight: 1.25, color: '#111827' },
    h4: { fontWeight: 600, fontSize: '0.9375rem', lineHeight: 1.25, color: '#1F2937' },
    h5: { fontWeight: 600, fontSize: '0.875rem', lineHeight: 1.25, color: '#1F2937' },
    h6: { fontWeight: 600, fontSize: '0.8125rem', lineHeight: 1.25, color: '#1F2937' },
    body1: { fontSize: '0.875rem', lineHeight: 1.5, color: '#374151' },
    body2: { fontSize: '0.8125rem', lineHeight: 1.5, color: '#6B7280' },
    caption: { fontSize: '0.75rem', lineHeight: 1.5, color: '#9CA3AF' },
    button: { fontWeight: 600, fontSize: '0.8125rem' },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: '#FCFCFD',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 600,
          borderRadius: 8,
          fontSize: '0.8125rem',
          transition: 'all 150ms cubic-bezier(0.4, 0, 0.2, 1)',
        },
        containedPrimary: {
          boxShadow: '0 4px 14px 0 rgba(37, 99, 235, 0.25)',
          '&:hover': {
            boxShadow: '0 6px 20px 0 rgba(37, 99, 235, 0.35)',
            transform: 'translateY(-1px)',
          },
          '&:active': {
            transform: 'translateY(0)',
            boxShadow: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
          },
        },
        outlined: {
          boxShadow: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
          borderColor: '#E5E7EB',
          '&:hover': {
            boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.06), 0 1px 2px -1px rgba(0, 0, 0, 0.06)',
            borderColor: '#D1D5DB',
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          border: '1px solid #F3F4F6',
          boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.06), 0 1px 2px -1px rgba(0, 0, 0, 0.06)',
        },
        elevation0: {
          boxShadow: 'none',
          border: 'none',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          border: '1px solid #F3F4F6',
          boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.06), 0 1px 2px -1px rgba(0, 0, 0, 0.06)',
          transition: 'box-shadow 200ms cubic-bezier(0.4, 0, 0.2, 1), transform 200ms cubic-bezier(0.4, 0, 0.2, 1)',
          '&:hover': {
            boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.05)',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 600,
          fontSize: '0.75rem',
          letterSpacing: '0.01em',
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
          fontSize: '0.8125rem',
          letterSpacing: 0,
          transition: 'color 150ms cubic-bezier(0.4, 0, 0.2, 1)',
          '&.Mui-selected': {
            fontWeight: 600,
          },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: 'linear-gradient(135deg, #1D4ED8 0%, #2563EB 100%)',
          boxShadow: '0 1px 3px rgba(0, 0, 0, 0.12)',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: 16,
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.04)',
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: 8,
            transition: 'box-shadow 150ms cubic-bezier(0.4, 0, 0.2, 1), border-color 150ms cubic-bezier(0.4, 0, 0.2, 1)',
            '&.Mui-focused': {
              boxShadow: '0 0 0 3px rgba(219, 234, 254, 1)',
            },
          },
        },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            color: '#6B7280',
            borderBottomColor: '#E5E7EB',
          },
        },
      },
    },
    MuiTableBody: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            fontSize: '0.8125rem',
            color: '#374151',
            borderBottomColor: '#F3F4F6',
          },
          '& .MuiTableRow-root:hover .MuiTableCell-root': {
            backgroundColor: '#F9FAFB',
          },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 12,
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: {
          borderRadius: 9999,
          height: 6,
        },
      },
    },
    MuiBackdrop: {
      styleOverrides: {
        root: {
          backdropFilter: 'blur(4px)',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          borderRight: '1px solid #F3F4F6',
        },
      },
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/admin" element={<AdminDashboard />} />
              <Route path="/admin/businesses/:id" element={<AdminBusinessDetail />} />
              <Route path="/admin/support" element={<AdminSupport />} />
              <Route path="/admin/onboarding" element={<AdminOnboarding />} />
              <Route path="/admin/onboarding/new" element={<AdminOnboardingWizard />} />
              <Route path="/admin/onboarding/:businessId" element={<AdminOnboardingWizard />} />
              <Route path="/app" element={<BusinessDashboard />} />
              <Route path="/app/settings/branding" element={<BrandingSettings />} />
              <Route path="/app/settings/billing" element={<BillingSettings />} />
              <Route path="/app/settings/email" element={<EmailSettings />} />
              <Route path="/app/settings/awaz" element={<AwazSettings />} />
              <Route path="/app/assistant/chat" element={<AssistantChat />} />
              <Route path="/app/help" element={<HelpSupport />} />
              <Route path="/app/inbox" element={<Inbox />} />
              <Route path="/app/briefings" element={<Briefings />} />
              <Route path="/app/email/outbox" element={<EmailOutbox />} />
              <Route path="/app/accounting" element={<Accounting />} />
              <Route path="/dashboard" element={<Navigate to="/app" replace />} />
              <Route path="/settings/email" element={<Navigate to="/app/settings/email" replace />} />
              <Route path="/inbox" element={<Navigate to="/app/inbox" replace />} />
              <Route path="/briefings" element={<Navigate to="/app/briefings" replace />} />
              <Route path="/confirm" element={<ConfirmEmail />} />
              <Route path="/" element={<Navigate to="/login" replace />} />
              <Route path="*" element={<Navigate to="/login" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
