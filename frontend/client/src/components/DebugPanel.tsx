import { useEffect, useState } from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  Box,
  Chip,
  Table,
  TableBody,
  TableRow,
  TableCell,
  CircularProgress,
  Alert,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import BugReportIcon from '@mui/icons-material/BugReport';
import { useAuth } from '@/contexts/AuthContext';
import { supabase } from '@/lib/supabase';

interface WhoAmIResult {
  uid: string | null;
  role: string | null;
}

export default function DebugPanel() {
  const { user } = useAuth();
  const [whoami, setWhoami] = useState<WhoAmIResult | null>(null);
  const [whoamiError, setWhoamiError] = useState<string | null>(null);
  const [whoamiLoading, setWhoamiLoading] = useState(true);
  const [memberCount, setMemberCount] = useState<number | null>(null);
  const [memberError, setMemberError] = useState<string | null>(null);
  const [memberLoading, setMemberLoading] = useState(true);

  useEffect(() => {
    async function fetchDebugData() {
      if (!user) {
        setWhoamiLoading(false);
        setMemberLoading(false);
        return;
      }

      setWhoamiLoading(true);
      try {
        const { data, error } = await supabase.rpc('whoami');
        if (error) {
          setWhoamiError(error.message);
        } else {
          setWhoami(data as WhoAmIResult);
        }
      } catch (err) {
        setWhoamiError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setWhoamiLoading(false);
      }

      setMemberLoading(true);
      try {
        const { count, error } = await supabase
          .from('business_members')
          .select('*', { count: 'exact', head: true })
          .eq('user_id', user.id);
        
        if (error) {
          setMemberError(error.message);
        } else {
          setMemberCount(count);
        }
      } catch (err) {
        setMemberError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setMemberLoading(false);
      }
    }

    fetchDebugData();
  }, [user]);

  return (
    <Accordion
      sx={{
        position: 'fixed',
        bottom: 16,
        right: 16,
        width: 400,
        maxWidth: 'calc(100vw - 32px)',
        zIndex: 1000,
        bgcolor: 'background.paper',
        boxShadow: 3,
      }}
      data-testid="debug-panel"
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{ bgcolor: 'grey.100' }}
        data-testid="button-debug-panel-toggle"
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <BugReportIcon color="warning" />
          <Typography variant="subtitle2" fontWeight="bold">
            Debug Panel
          </Typography>
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Table size="small">
          <TableBody>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', width: 140 }}>Session User ID</TableCell>
              <TableCell>
                <Typography
                  variant="body2"
                  sx={{ fontFamily: 'monospace', fontSize: '0.75rem', wordBreak: 'break-all' }}
                  data-testid="text-session-user-id"
                >
                  {user?.id || 'N/A'}
                </Typography>
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>Session Email</TableCell>
              <TableCell>
                <Typography variant="body2" data-testid="text-session-email">
                  {user?.email || 'N/A'}
                </Typography>
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>RPC whoami()</TableCell>
              <TableCell data-testid="text-whoami-result">
                {whoamiLoading ? (
                  <CircularProgress size={16} />
                ) : whoamiError ? (
                  <Alert severity="error" sx={{ py: 0, px: 1 }}>
                    {whoamiError}
                  </Alert>
                ) : whoami ? (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                      uid: {whoami.uid || 'null'}
                    </Typography>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                      role: {whoami.role || 'null'}
                    </Typography>
                  </Box>
                ) : (
                  <Typography variant="body2" color="text.secondary">No data</Typography>
                )}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold' }}>business_members count</TableCell>
              <TableCell data-testid="text-member-count">
                {memberLoading ? (
                  <CircularProgress size={16} />
                ) : memberError ? (
                  <Alert severity="error" sx={{ py: 0, px: 1 }}>
                    {memberError}
                  </Alert>
                ) : (
                  <Chip
                    label={memberCount ?? 0}
                    size="small"
                    color={memberCount && memberCount > 0 ? 'success' : 'default'}
                  />
                )}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </AccordionDetails>
    </Accordion>
  );
}
