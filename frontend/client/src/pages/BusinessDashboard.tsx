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
  Grid,
  Card,
  CardContent,
  CardActions,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  CircularProgress,
  Alert,
  IconButton,
  Tabs,
  Tab,
  Divider,
  Avatar,
} from '@mui/material';
import {
  Business as BusinessIcon,
  Task as TaskIcon,
  Phone as PhoneIcon,
  Add as AddIcon,
  CheckCircle as CheckCircleIcon,
  Logout as LogoutIcon,
  AccessTime as AccessTimeIcon,
} from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, type Business, type Task, type Call, type BusinessMember, resolveLogoSrc } from '@/lib/supabase';
import { useMe } from '@/hooks/useMe';
import DebugPanel from '@/components/DebugPanel';

/**
 * Get business initials from name
 */
function getBusinessInitials(name: string): string {
  return name
    .split(' ')
    .map(word => word[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div role="tabpanel" hidden={value !== index} {...other}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  );
}

export default function BusinessDashboard() {
  const navigate = useNavigate();
  const { user, signOut, loading: authLoading } = useAuth();
  const { data: businessProfile, isLoading: profileLoading } = useMe();
  
  const [tabValue, setTabValue] = useState(0);
  const [membership, setMembership] = useState<BusinessMember | null>(null);
  const [business, setBusiness] = useState<Business | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  const logoUrl = resolveLogoSrc(businessProfile?.logo_url);

  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [savingTask, setSavingTask] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      fetchUserBusiness();
    }
  }, [user]);

  const fetchUserBusiness = async () => {
    setLoading(true);
    setError('');

    try {
      const { data: memberData, error: memberError } = await supabase
        .from('business_members')
        .select('*, businesses(*)')
        .eq('user_id', user?.id)
        .single();

      if (memberError) {
        if (memberError.code === 'PGRST116') {
          setError('You are not assigned to any business. Please contact an administrator.');
        } else {
          throw memberError;
        }
        setLoading(false);
        return;
      }

      setMembership(memberData);
      setBusiness(memberData.businesses);

      await Promise.all([
        fetchTasks(memberData.business_id),
        fetchCalls(memberData.business_id),
      ]);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch business data');
    } finally {
      setLoading(false);
    }
  };

  const fetchTasks = async (businessId: string) => {
    const { data, error } = await supabase
      .from('tasks')
      .select('*')
      .eq('business_id', businessId)
      .order('created_at', { ascending: false });

    if (error) throw error;
    setTasks(data || []);
  };

  const fetchCalls = async (businessId: string) => {
    const { data, error } = await supabase
      .from('calls')
      .select('*')
      .eq('business_id', businessId)
      .order('created_at', { ascending: false });

    if (error) throw error;
    setCalls(data || []);
  };

  const handleCreateTask = async () => {
    if (!taskTitle.trim() || !business) return;

    setSavingTask(true);
    setError('');

    try {
      const { error: insertError } = await supabase
        .from('tasks')
        .insert({
          business_id: business.id,
          title: taskTitle.trim(),
          description: taskDescription.trim(),
          status: 'pending',
        });

      if (insertError) throw insertError;

      setTaskDialogOpen(false);
      setTaskTitle('');
      setTaskDescription('');
      await fetchTasks(business.id);
    } catch (err: any) {
      setError(err.message || 'Failed to create task');
    } finally {
      setSavingTask(false);
    }
  };

  const handleCompleteTask = async (taskId: string) => {
    if (!business) return;

    try {
      const { error: updateError } = await supabase
        .from('tasks')
        .update({ status: 'completed' })
        .eq('id', taskId);

      if (updateError) throw updateError;
      await fetchTasks(business.id);
    } catch (err: any) {
      setError(err.message || 'Failed to complete task');
    }
  };

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  if (authLoading || loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'grey.100' }}>
      <AppBar position="static">
        <Toolbar sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          {/* Logo/Avatar - Fixed size */}
          <Box sx={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
            {logoUrl ? (
              <img
                src={logoUrl}
                alt={businessProfile?.name || 'Business Logo'}
                style={{
                  width: '40px',
                  height: '40px',
                  objectFit: 'contain',
                  display: 'block',
                }}
              />
            ) : businessProfile?.name ? (
              <Avatar
                sx={{
                  width: 40,
                  height: 40,
                  bgcolor: 'primary.main',
                  fontSize: '0.875rem',
                }}
              >
                {getBusinessInitials(businessProfile.name)}
              </Avatar>
            ) : (
              <BusinessIcon sx={{ fontSize: 40 }} />
            )}
          </Box>
          
          {/* Business Name - Flexible with text overflow */}
          <Box
            sx={{
              flex: 1,
              minWidth: 0,
              overflow: 'hidden',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Typography
              variant="h6"
              sx={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {businessProfile?.name || business?.name || 'Business Dashboard'}
            </Typography>
          </Box>
          
          {/* Right side - User email and logout */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
            <Typography
              variant="body2"
              sx={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                maxWidth: { xs: '120px', sm: '200px', md: 'none' },
              }}
            >
              {user?.email}
            </Typography>
            <IconButton color="inherit" onClick={handleSignOut} data-testid="button-signout">
              <LogoutIcon />
            </IconButton>
          </Box>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 4 }}>
        {error && (
          <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')} data-testid="alert-error">
            {error}
          </Alert>
        )}

        {!business ? (
          <Paper sx={{ p: 4, textAlign: 'center' }}>
            <Typography variant="h6" color="text.secondary">
              No business assigned
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Please contact an administrator to be assigned to a business.
            </Typography>
          </Paper>
        ) : (
          <>
            <Paper sx={{ p: 3, mb: 3 }} elevation={1}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h5">
                  Business Profile
                </Typography>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => navigate('/app/settings/branding')}
                >
                  Branding Settings
                </Button>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                {logoUrl ? (
                  <img
                    src={logoUrl}
                    alt={businessProfile?.name || business?.name || 'Business Logo'}
                    style={{
                      height: '64px',
                      width: 'auto',
                      maxWidth: '200px',
                      objectFit: 'contain',
                    }}
                  />
                ) : businessProfile?.name || business?.name ? (
                  <Avatar
                    sx={{
                      width: 64,
                      height: 64,
                      bgcolor: 'primary.main',
                      fontSize: '1.5rem',
                    }}
                  >
                    {getBusinessInitials(businessProfile?.name || business?.name || '')}
                  </Avatar>
                ) : (
                  <BusinessIcon sx={{ fontSize: 64, color: 'text.disabled' }} />
                )}
                <Box>
                  <Typography variant="h6" data-testid="text-business-name">
                    {businessProfile?.name || business.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Business Logo
                  </Typography>
                </Box>
              </Box>
              <Grid container spacing={3}>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Business Name
                  </Typography>
                  <Typography variant="body1" fontWeight="medium">
                    {businessProfile?.name || business.name}
                  </Typography>
                </Grid>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Timezone
                  </Typography>
                  <Chip
                    icon={<AccessTimeIcon />}
                    label={business.timezone}
                    size="small"
                    variant="outlined"
                  />
                </Grid>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Your Role
                  </Typography>
                  <Chip
                    label={membership?.role || 'Member'}
                    size="small"
                    color="primary"
                  />
                </Grid>
              </Grid>
            </Paper>

            <Paper sx={{ p: 3 }} elevation={1}>
              <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 0 }}>
                <Tabs value={tabValue} onChange={(_, v) => setTabValue(v)}>
                  <Tab
                    icon={<TaskIcon />}
                    iconPosition="start"
                    label={`Tasks (${tasks.length})`}
                    data-testid="tab-tasks"
                  />
                  <Tab
                    icon={<PhoneIcon />}
                    iconPosition="start"
                    label={`Calls (${calls.length})`}
                    data-testid="tab-calls"
                  />
                </Tabs>
              </Box>

              <TabPanel value={tabValue} index={0}>
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
                  <Button
                    variant="contained"
                    startIcon={<AddIcon />}
                    onClick={() => setTaskDialogOpen(true)}
                    data-testid="button-create-task"
                  >
                    Create Task
                  </Button>
                </Box>

                {tasks.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <TaskIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                    <Typography color="text.secondary">No tasks yet</Typography>
                  </Box>
                ) : (
                  <Grid container spacing={2}>
                    {tasks.map((task) => (
                      <Grid size={{ xs: 12, sm: 6, md: 4 }} key={task.id}>
                        <Card
                          variant="outlined"
                          sx={{
                            opacity: task.status === 'completed' ? 0.7 : 1,
                          }}
                          data-testid={`card-task-${task.id}`}
                        >
                          <CardContent>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1, gap: 1 }}>
                              <Typography variant="subtitle1" fontWeight="medium" sx={{ flexGrow: 1 }}>
                                {task.title}
                              </Typography>
                              <Chip
                                label={task.status}
                                size="small"
                                color={task.status === 'completed' ? 'success' : 'warning'}
                              />
                            </Box>
                            {task.description && (
                              <Typography variant="body2" color="text.secondary">
                                {task.description}
                              </Typography>
                            )}
                            <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 1 }}>
                              {new Date(task.created_at).toLocaleString()}
                            </Typography>
                          </CardContent>
                          {task.status !== 'completed' && (
                            <CardActions>
                              <Button
                                size="small"
                                startIcon={<CheckCircleIcon />}
                                onClick={() => handleCompleteTask(task.id)}
                                data-testid={`button-complete-task-${task.id}`}
                              >
                                Complete
                              </Button>
                            </CardActions>
                          )}
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                )}
              </TabPanel>

              <TabPanel value={tabValue} index={1}>
                {calls.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <PhoneIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                    <Typography color="text.secondary">No calls recorded</Typography>
                  </Box>
                ) : (
                  <Grid container spacing={2}>
                    {calls.map((call) => (
                      <Grid size={{ xs: 12, sm: 6, md: 4 }} key={call.id}>
                        <Card variant="outlined" data-testid={`card-call-${call.id}`}>
                          <CardContent>
                            <Typography variant="subtitle1" fontWeight="medium">
                              {call.caller_name}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {call.phone_number}
                            </Typography>
                            {call.notes && (
                              <Typography variant="body2" sx={{ mt: 1 }}>
                                {call.notes}
                              </Typography>
                            )}
                            <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 1 }}>
                              {new Date(call.created_at).toLocaleString()}
                            </Typography>
                          </CardContent>
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                )}
              </TabPanel>
            </Paper>
          </>
        )}
      </Container>

      <Dialog open={taskDialogOpen} onClose={() => setTaskDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Task</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Task Title"
            fullWidth
            variant="outlined"
            value={taskTitle}
            onChange={(e) => setTaskTitle(e.target.value)}
            sx={{ mb: 2, mt: 1 }}
            data-testid="input-task-title"
          />
          <TextField
            margin="dense"
            label="Description (optional)"
            fullWidth
            multiline
            rows={3}
            variant="outlined"
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            data-testid="input-task-description"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTaskDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleCreateTask}
            variant="contained"
            disabled={savingTask || !taskTitle.trim()}
            data-testid="button-save-task"
          >
            {savingTask ? <CircularProgress size={20} /> : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      <DebugPanel />
    </Box>
  );
}
