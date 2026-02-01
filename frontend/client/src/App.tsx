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
import BillingSettings from '@/pages/BillingSettings';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1976d2',
      light: '#e3f2fd',
    },
    secondary: {
      main: '#9c27b0',
    },
    background: {
      default: '#f5f7fa',
      paper: '#ffffff',
    },
  },
  shape: {
    borderRadius: 12,
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    h5: {
      fontWeight: 600,
    },
    h6: {
      fontWeight: 600,
    },
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
          borderRadius: 8,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06)',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06)',
          border: '1px solid rgba(0,0,0,0.05)',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 500,
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
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
