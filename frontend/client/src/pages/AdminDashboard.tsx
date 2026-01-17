import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  Button,
  Container,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  IconButton,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Divider,
  CircularProgress,
  Alert,
  useTheme,
  useMediaQuery,
} from '@mui/material';
import {
  Menu as MenuIcon,
  Dashboard as DashboardIcon,
  Business as BusinessIcon,
  People as PeopleIcon,
  Add as AddIcon,
  Logout as LogoutIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, type Business, type BusinessMember } from '@/lib/supabase';
import DebugPanel from '@/components/DebugPanel';

const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Europe/London',
  'Europe/Paris',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
];

const ROLES = ['owner', 'admin', 'member'];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user, signOut, isAdmin, loading: authLoading, adminLoading } = useAuth();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'businesses' | 'members'>('businesses');
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [members, setMembers] = useState<(BusinessMember & { business_name?: string })[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [businessDialogOpen, setBusinessDialogOpen] = useState(false);
  const [businessName, setBusinessName] = useState('');
  const [businessTimezone, setBusinessTimezone] = useState('America/New_York');
  const [savingBusiness, setSavingBusiness] = useState(false);

  const [memberDialogOpen, setMemberDialogOpen] = useState(false);
  const [memberEmail, setMemberEmail] = useState('');
  const [memberBusinessId, setMemberBusinessId] = useState('');
  const [memberRole, setMemberRole] = useState('member');
  const [savingMember, setSavingMember] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    } else if (!authLoading && !adminLoading && !isAdmin) {
      navigate('/app');
    }
  }, [user, isAdmin, authLoading, adminLoading, navigate]);

  useEffect(() => {
    if (user && isAdmin) {
      fetchData();
    }
  }, [user, isAdmin]);

  const fetchData = async () => {
    setLoading(true);
    setError('');
    
    try {
      const { data: businessData, error: businessError } = await supabase
        .from('businesses')
        .select('*')
        .order('created_at', { ascending: false });

      if (businessError) throw businessError;
      setBusinesses(businessData || []);

      const { data: memberData, error: memberError } = await supabase
        .from('business_members')
        .select('*, businesses(name)')
        .order('created_at', { ascending: false });

      if (memberError) throw memberError;
      
      const formattedMembers = (memberData || []).map((m: any) => ({
        ...m,
        business_name: m.businesses?.name,
      }));
      setMembers(formattedMembers);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  };

  const generateApiKey = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let key = 'bh_';
    for (let i = 0; i < 32; i++) {
      key += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return key;
  };

  const handleCreateBusiness = async () => {
    if (!businessName.trim()) return;
    
    setSavingBusiness(true);
    setError('');

    try {
      const { error: insertError } = await supabase
        .from('businesses')
        .insert({
          name: businessName.trim(),
          timezone: businessTimezone,
          api_key: generateApiKey(),
        });

      if (insertError) throw insertError;

      setBusinessDialogOpen(false);
      setBusinessName('');
      setBusinessTimezone('America/New_York');
      fetchData();
    } catch (err: any) {
      setError(err.message || 'Failed to create business');
    } finally {
      setSavingBusiness(false);
    }
  };

  const handleCreateMember = async () => {
    if (!memberEmail.trim() || !memberBusinessId) return;
    
    setSavingMember(true);
    setError('');

    try {
      const { error: insertError } = await supabase
        .from('business_members')
        .insert({
          business_id: memberBusinessId,
          invited_email: memberEmail.trim().toLowerCase(),
          role: memberRole,
          is_active: true,
        });

      if (insertError) throw insertError;

      setMemberDialogOpen(false);
      setMemberEmail('');
      setMemberBusinessId('');
      setMemberRole('member');
      fetchData();
    } catch (err: any) {
      setError(err.message || 'Failed to create member');
    } finally {
      setSavingMember(false);
    }
  };

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  const drawerContent = (
    <Box sx={{ width: 240 }}>
      <Toolbar>
        <BusinessIcon sx={{ mr: 1 }} />
        <Typography variant="h6" noWrap>
          Platform Admin
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        <ListItem disablePadding>
          <ListItemButton
            selected={activeTab === 'businesses'}
            onClick={() => {
              setActiveTab('businesses');
              setDrawerOpen(false);
            }}
            data-testid="nav-businesses"
          >
            <ListItemIcon>
              <BusinessIcon />
            </ListItemIcon>
            <ListItemText primary="Businesses" />
          </ListItemButton>
        </ListItem>
        <ListItem disablePadding>
          <ListItemButton
            selected={activeTab === 'members'}
            onClick={() => {
              setActiveTab('members');
              setDrawerOpen(false);
            }}
            data-testid="nav-members"
          >
            <ListItemIcon>
              <PeopleIcon />
            </ListItemIcon>
            <ListItemText primary="Members" />
          </ListItemButton>
        </ListItem>
      </List>
      <Divider />
      <List>
        <ListItem disablePadding>
          <ListItemButton onClick={handleSignOut} data-testid="button-signout">
            <ListItemIcon>
              <LogoutIcon />
            </ListItemIcon>
            <ListItemText primary="Sign Out" />
          </ListItemButton>
        </ListItem>
      </List>
    </Box>
  );

  if (authLoading || adminLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar position="fixed" sx={{ zIndex: theme.zIndex.drawer + 1 }}>
        <Toolbar>
          {isMobile && (
            <IconButton
              color="inherit"
              edge="start"
              onClick={() => setDrawerOpen(!drawerOpen)}
              sx={{ mr: 2 }}
              data-testid="button-menu"
            >
              <MenuIcon />
            </IconButton>
          )}
          <DashboardIcon sx={{ mr: 1 }} />
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>
            Admin Dashboard
          </Typography>
          <Typography variant="body2" sx={{ mr: 2 }}>
            {user?.email}
          </Typography>
        </Toolbar>
      </AppBar>

      {isMobile ? (
        <Drawer
          variant="temporary"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          ModalProps={{ keepMounted: true }}
        >
          {drawerContent}
        </Drawer>
      ) : (
        <Drawer variant="permanent" sx={{ width: 240, flexShrink: 0 }}>
          {drawerContent}
        </Drawer>
      )}

      <Box component="main" sx={{ flexGrow: 1, p: 3, mt: 8, ml: isMobile ? 0 : '240px' }}>
        <Container maxWidth="xl">
          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')} data-testid="alert-error">
              {error}
            </Alert>
          )}

          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, gap: 2, flexWrap: 'wrap' }}>
            <Typography variant="h4" component="h1">
              {activeTab === 'businesses' ? 'Businesses' : 'Business Members'}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={() => setBusinessDialogOpen(true)}
                data-testid="button-create-business"
              >
                Create Business
              </Button>
              <Button
                variant="outlined"
                startIcon={<AddIcon />}
                onClick={() => setMemberDialogOpen(true)}
                data-testid="button-add-member"
              >
                Add Member
              </Button>
            </Box>
          </Box>

          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress />
            </Box>
          ) : activeTab === 'businesses' ? (
            <TableContainer component={Paper} elevation={1}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Name</TableCell>
                    <TableCell>Timezone</TableCell>
                    <TableCell>Created</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {businesses.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={3} align="center" sx={{ py: 4 }}>
                        <Typography color="text.secondary">No businesses yet</Typography>
                      </TableCell>
                    </TableRow>
                  ) : (
                    businesses.map((business) => (
                      <TableRow key={business.id} data-testid={`row-business-${business.id}`}>
                        <TableCell>
                          <Typography fontWeight="medium">{business.name}</Typography>
                        </TableCell>
                        <TableCell>
                          <Chip label={business.timezone} size="small" variant="outlined" />
                        </TableCell>
                        <TableCell>
                          {new Date(business.created_at).toLocaleDateString()}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <TableContainer component={Paper} elevation={1}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Email</TableCell>
                    <TableCell>Business</TableCell>
                    <TableCell>Role</TableCell>
                    <TableCell>Created</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {members.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} align="center" sx={{ py: 4 }}>
                        <Typography color="text.secondary">No members yet</Typography>
                      </TableCell>
                    </TableRow>
                  ) : (
                    members.map((member) => (
                      <TableRow key={member.id} data-testid={`row-member-${member.id}`}>
                        <TableCell>{member.invited_email}</TableCell>
                        <TableCell>{member.business_name || '-'}</TableCell>
                        <TableCell>
                          <Chip
                            label={member.role}
                            size="small"
                            color={member.role === 'owner' ? 'primary' : member.role === 'admin' ? 'secondary' : 'default'}
                          />
                        </TableCell>
                        <TableCell>
                          {new Date(member.created_at).toLocaleDateString()}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Container>
      </Box>

      <Dialog open={businessDialogOpen} onClose={() => setBusinessDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Business</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Business Name"
            fullWidth
            variant="outlined"
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            sx={{ mb: 2, mt: 1 }}
            data-testid="input-business-name"
          />
          <FormControl fullWidth>
            <InputLabel>Timezone</InputLabel>
            <Select
              value={businessTimezone}
              label="Timezone"
              onChange={(e) => setBusinessTimezone(e.target.value)}
              data-testid="select-timezone"
            >
              {TIMEZONES.map((tz) => (
                <MenuItem key={tz} value={tz}>
                  {tz}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBusinessDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateBusiness}
            variant="contained"
            disabled={savingBusiness || !businessName.trim()}
            data-testid="button-save-business"
          >
            {savingBusiness ? <CircularProgress size={20} /> : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={memberDialogOpen} onClose={() => setMemberDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Business Member</DialogTitle>
        <DialogContent>
          <FormControl fullWidth sx={{ mb: 2, mt: 1 }}>
            <InputLabel>Business</InputLabel>
            <Select
              value={memberBusinessId}
              label="Business"
              onChange={(e) => setMemberBusinessId(e.target.value)}
              data-testid="select-business"
            >
              {businesses.map((b) => (
                <MenuItem key={b.id} value={b.id}>
                  {b.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            margin="dense"
            label="User Email"
            type="email"
            fullWidth
            variant="outlined"
            value={memberEmail}
            onChange={(e) => setMemberEmail(e.target.value)}
            sx={{ mb: 2 }}
            data-testid="input-member-email"
          />
          <FormControl fullWidth>
            <InputLabel>Role</InputLabel>
            <Select
              value={memberRole}
              label="Role"
              onChange={(e) => setMemberRole(e.target.value)}
              data-testid="select-role"
            >
              {ROLES.map((role) => (
                <MenuItem key={role} value={role}>
                  {role.charAt(0).toUpperCase() + role.slice(1)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMemberDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateMember}
            variant="contained"
            disabled={savingMember || !memberEmail.trim() || !memberBusinessId}
            data-testid="button-save-member"
          >
            {savingMember ? <CircularProgress size={20} /> : 'Add Member'}
          </Button>
        </DialogActions>
      </Dialog>

      {import.meta.env.DEV && <DebugPanel />}
    </Box>
  );
}
