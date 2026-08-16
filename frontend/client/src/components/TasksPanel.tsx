import { useState, useEffect, useMemo, useImperativeHandle, forwardRef } from 'react';
import {
  Box,
  Typography,
  Button,
  Card,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  CircularProgress,
  Alert,
  IconButton,
  Snackbar,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Tooltip,
} from '@mui/material';
import {
  Task as TaskIcon,
  Add as AddIcon,
  CheckCircle as CheckCircleIcon,
} from '@mui/icons-material';
import { supabase, type Task } from '@/lib/supabase';
import {
  TASK_CATEGORIES, TASK_PRIORITIES,
  getCategoryColor, getCategoryLabel,
  isOverdue as isTaskOverdue, isToday as isDateToday, formatDueDate,
} from '@/lib/taskConstants';

export interface TasksPanelHandle {
  openCreateDialog: () => void;
}

interface TasksPanelProps {
  businessId: string;
  onTaskCountChange?: (count: number) => void;
}

const TasksPanel = forwardRef<TasksPanelHandle, TasksPanelProps>(function TasksPanel({ businessId, onTaskCountChange }, ref) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskFilter, setTaskFilter] = useState<'open' | 'completed' | 'all'>('open');
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [taskDueAt, setTaskDueAt] = useState('');
  const [taskCategory, setTaskCategory] = useState('general');
  const [taskPriority, setTaskPriority] = useState('medium');
  const [savingTask, setSavingTask] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [priorityFilter, setPriorityFilter] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState('created_at');
  const [successMessage, setSuccessMessage] = useState('');
  const [error, setError] = useState('');

  useImperativeHandle(ref, () => ({
    openCreateDialog: () => setTaskDialogOpen(true),
  }));

  useEffect(() => {
    fetchTasks(businessId);
  }, [businessId]);

  const fetchTasks = async (bizId: string) => {
    const { data, error } = await supabase
      .from('tasks')
      .select('*')
      .eq('business_id', bizId)
      .is('deleted_at', null)
      .order('created_at', { ascending: false });

    if (error) throw error;
    setTasks(data || []);
  };

  const handleCreateTask = async () => {
    if (!taskTitle.trim()) return;

    setSavingTask(true);
    setError('');

    try {
      const { error: insertError } = await supabase
        .from('tasks')
        .insert({
          business_id: businessId,
          title: taskTitle.trim(),
          description: taskDescription.trim() || null,
          status: 'open',
          due_at: taskDueAt ? new Date(taskDueAt).toISOString() : null,
          category: taskCategory,
          priority: taskPriority,
        });

      if (insertError) throw insertError;

      setTaskDialogOpen(false);
      setTaskTitle('');
      setTaskDescription('');
      setTaskDueAt('');
      setTaskCategory('general');
      setTaskPriority('medium');
      setSuccessMessage('Task created');
      await fetchTasks(businessId);
    } catch (err: any) {
      setError(err.message || 'Failed to create task');
    } finally {
      setSavingTask(false);
    }
  };

  const handleCompleteTask = async (taskId: string) => {
    try {
      const { error: updateError } = await supabase
        .from('tasks')
        .update({ status: 'completed' })
        .eq('id', taskId);

      if (updateError) throw updateError;
      await fetchTasks(businessId);
    } catch (err: any) {
      setError(err.message || 'Failed to complete task');
    }
  };

  const cycleTaskStatus = async (taskId: string, currentStatus: string) => {
    const nextStatus =
      currentStatus === 'open' ? 'pending' :
      currentStatus === 'pending' ? 'completed' :
      'open';
    try {
      const { error: updateError } = await supabase
        .from('tasks')
        .update({ status: nextStatus, updated_at: new Date().toISOString() })
        .eq('id', taskId);
      if (updateError) throw updateError;
      await fetchTasks(businessId);
    } catch (err: any) {
      setError(err.message || 'Failed to update task status');
    }
  };

  // Filter & sort tasks
  const filteredTasks = useMemo(() => {
    let result = tasks.filter(t => !t.deleted_at);

    if (taskFilter === 'open') result = result.filter(t => t.status !== 'completed');
    else if (taskFilter === 'completed') result = result.filter(t => t.status === 'completed');

    if (categoryFilter) result = result.filter(t => (t.category || 'general') === categoryFilter);
    if (priorityFilter) result = result.filter(t => (t.priority || 'medium') === priorityFilter);

    const priorityOrder: Record<string, number> = { high: 0, medium: 1, low: 2 };
    result.sort((a, b) => {
      if (sortBy === 'due_at') {
        if (!a.due_at && !b.due_at) return 0;
        if (!a.due_at) return 1;
        if (!b.due_at) return -1;
        return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
      }
      if (sortBy === 'priority') {
        return (priorityOrder[a.priority] ?? 1) - (priorityOrder[b.priority] ?? 1);
      }
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });

    return result;
  }, [tasks, taskFilter, categoryFilter, priorityFilter, sortBy]);

  const overdueTasks = tasks.filter(t => t.due_at && new Date(t.due_at) < new Date() && t.status !== 'completed').length;
  const dueTodayTasks = tasks.filter(t => t.due_at && isDateToday(new Date(t.due_at)) && t.status !== 'completed').length;
  const pendingTasks = tasks.filter(t => t.status === 'pending').length;
  const openTaskCount = tasks.filter(t => t.status !== 'completed').length;

  useEffect(() => {
    onTaskCountChange?.(openTaskCount);
  }, [openTaskCount, onTaskCountChange]);

  return (
    <>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {/* Summary cards */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="error.main">{overdueTasks}</Typography>
          <Typography variant="caption" color="text.secondary">Overdue</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="warning.main">{dueTodayTasks}</Typography>
          <Typography variant="caption" color="text.secondary">Due Today</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700} color="info.main">{pendingTasks}</Typography>
          <Typography variant="caption" color="text.secondary">Pending</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2, textAlign: 'center' }}>
          <Typography variant="h5" fontWeight={700}>{openTaskCount}</Typography>
          <Typography variant="caption" color="text.secondary">Total Open</Typography>
        </Card>
      </Box>

      {/* Status filter + create button */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 2 }}>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Chip
            label={`Open (${tasks.filter(t => t.status !== 'completed').length})`}
            onClick={() => setTaskFilter('open')}
            color={taskFilter === 'open' ? 'primary' : 'default'}
            variant={taskFilter === 'open' ? 'filled' : 'outlined'}
          />
          <Chip
            label={`Completed (${tasks.filter(t => t.status === 'completed').length})`}
            onClick={() => setTaskFilter('completed')}
            color={taskFilter === 'completed' ? 'primary' : 'default'}
            variant={taskFilter === 'completed' ? 'filled' : 'outlined'}
          />
          <Chip
            label={`All (${tasks.length})`}
            onClick={() => setTaskFilter('all')}
            color={taskFilter === 'all' ? 'primary' : 'default'}
            variant={taskFilter === 'all' ? 'filled' : 'outlined'}
          />
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setTaskDialogOpen(true)}
          data-testid="button-create-task"
        >
          Create Task
        </Button>
      </Box>

      {/* Category filter chips */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
        <Chip
          label="All Categories"
          size="small"
          onClick={() => setCategoryFilter(null)}
          color={!categoryFilter ? 'primary' : 'default'}
          variant={!categoryFilter ? 'filled' : 'outlined'}
        />
        {TASK_CATEGORIES.map(cat => (
          <Chip
            key={cat.id}
            label={cat.label}
            size="small"
            onClick={() => setCategoryFilter(cat.id)}
            sx={{
              bgcolor: categoryFilter === cat.id ? cat.color : undefined,
              color: categoryFilter === cat.id ? '#fff' : undefined,
              borderColor: categoryFilter === cat.id ? cat.color : undefined,
              '&:hover': { opacity: 0.85 },
            }}
            variant={categoryFilter === cat.id ? 'filled' : 'outlined'}
          />
        ))}
      </Box>

      {/* Priority filter + sort */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="caption" color="text.secondary">Priority:</Typography>
          {[{ id: null, label: 'All' }, ...TASK_PRIORITIES].map(p => (
            <Chip
              key={p.id ?? 'all'}
              label={p.label}
              size="small"
              onClick={() => setPriorityFilter(p.id)}
              variant={(p.id === null && !priorityFilter) || priorityFilter === p.id ? 'filled' : 'outlined'}
              color={(p.id === null && !priorityFilter) || priorityFilter === p.id ? 'primary' : 'default'}
              sx={{ height: 24, fontSize: '0.7rem' }}
            />
          ))}
        </Box>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Sort by</InputLabel>
          <Select value={sortBy} label="Sort by" onChange={e => setSortBy(e.target.value)}>
            <MenuItem value="created_at">Newest First</MenuItem>
            <MenuItem value="due_at">Due Date</MenuItem>
            <MenuItem value="priority">Priority</MenuItem>
          </Select>
        </FormControl>
      </Box>

      {filteredTasks.length === 0 ? (
        <Box sx={{ textAlign: 'center', py: 4 }}>
          <TaskIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
          <Typography color="text.secondary">
            {taskFilter === 'completed' ? 'No completed tasks' : taskFilter === 'open' ? 'No open tasks' : 'No tasks yet'}
          </Typography>
        </Box>
      ) : (
        <Box>
          {filteredTasks.map((task) => {
            const overdue = task.due_at && isTaskOverdue(task.due_at, task.status);
            const dueToday = task.due_at && isDateToday(new Date(task.due_at)) && task.status !== 'completed';
            const catColor = getCategoryColor(task.category || 'general');
            return (
              <Card
                key={task.id}
                data-testid={`card-task-${task.id}`}
                sx={{
                  p: 2,
                  mb: 2,
                  borderLeft: 4,
                  borderLeftColor: catColor,
                  opacity: task.status === 'completed' ? 0.7 : 1,
                  '&:hover': { boxShadow: 2 },
                  transition: 'box-shadow 0.2s',
                }}
              >
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Box sx={{ flex: 1 }}>
                    {/* Title row */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, flexWrap: 'wrap' }}>
                      <Typography
                        variant="subtitle1"
                        fontWeight={600}
                        sx={{ textDecoration: task.status === 'completed' ? 'line-through' : 'none' }}
                      >
                        {task.title}
                      </Typography>
                      <Chip
                        label={getCategoryLabel(task.category || 'general')}
                        size="small"
                        sx={{ bgcolor: catColor, color: '#fff', height: 20, fontSize: '0.65rem' }}
                      />
                      <Chip
                        label={`${(TASK_PRIORITIES.find(p => p.id === task.priority) || TASK_PRIORITIES[1]).icon} ${(task.priority || 'medium').charAt(0).toUpperCase() + (task.priority || 'medium').slice(1)}`}
                        size="small"
                        variant="outlined"
                        sx={{
                          height: 20,
                          fontSize: '0.65rem',
                          borderColor: task.priority === 'high' ? '#EF4444' : task.priority === 'low' ? '#10B981' : '#F59E0B',
                          color: task.priority === 'high' ? '#EF4444' : task.priority === 'low' ? '#10B981' : '#F59E0B',
                        }}
                      />
                    </Box>

                    {/* Description preview */}
                    {task.description && (
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{
                          mb: 1,
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {task.description}
                      </Typography>
                    )}

                    {/* Meta row */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
                      {task.due_at && (
                        <Typography
                          variant="caption"
                          fontWeight={overdue || dueToday ? 600 : 400}
                          color={overdue ? 'error.main' : dueToday ? 'warning.main' : 'text.secondary'}
                        >
                          {overdue ? `⚠️ Overdue: ${formatDueDate(task.due_at)}` : dueToday ? '📅 Due today' : formatDueDate(task.due_at)}
                        </Typography>
                      )}
                      {task.source === 'email' && (
                        <Chip label="From email" size="small" variant="outlined" color="info" sx={{ height: 20, fontSize: '0.65rem' }} />
                      )}
                      {task.source === 'call' && (
                        <Chip label="From call" size="small" variant="outlined" color="success" sx={{ height: 20, fontSize: '0.65rem' }} />
                      )}
                      {task.source === 'manual' && (
                        <Chip label="Manual" size="small" variant="outlined" sx={{ height: 20, fontSize: '0.65rem' }} />
                      )}
                      <Typography variant="caption" color="text.disabled">
                        {new Date(task.created_at).toLocaleDateString('en-GB')}
                      </Typography>
                    </Box>
                  </Box>

                  {/* Action buttons */}
                  <Box sx={{ display: 'flex', gap: 0.5, ml: 1, alignItems: 'center' }}>
                    <Tooltip title={`Status: ${task.status} — click to cycle`}>
                      <Chip
                        label={
                          task.status === 'completed' ? '✅ Done' :
                          task.status === 'pending' ? '⏳ Pending' :
                          '⬜ Open'
                        }
                        size="small"
                        onClick={() => cycleTaskStatus(task.id, task.status)}
                        sx={{
                          cursor: 'pointer',
                          fontWeight: 500,
                          bgcolor:
                            task.status === 'completed' ? '#dcfce7' :
                            task.status === 'pending' ? '#fef3c7' :
                            '#f3f4f6',
                          color:
                            task.status === 'completed' ? '#15803d' :
                            task.status === 'pending' ? '#92400e' :
                            '#4b5563',
                        }}
                      />
                    </Tooltip>
                    {task.status !== 'completed' && (
                      <Tooltip title="Mark complete">
                        <IconButton
                          size="small"
                          onClick={() => handleCompleteTask(task.id)}
                          color="success"
                          data-testid={`button-complete-task-${task.id}`}
                        >
                          <CheckCircleIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </Box>
                </Box>
              </Card>
            );
          })}
        </Box>
      )}

      {/* Create Task Dialog */}
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

          <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
            Category
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
            {TASK_CATEGORIES.map(cat => (
              <Chip
                key={cat.id}
                label={cat.label}
                size="small"
                onClick={() => setTaskCategory(cat.id)}
                sx={{
                  bgcolor: taskCategory === cat.id ? cat.color : undefined,
                  color: taskCategory === cat.id ? '#fff' : undefined,
                  borderColor: taskCategory === cat.id ? cat.color : undefined,
                  '&:hover': { opacity: 0.85 },
                }}
                variant={taskCategory === cat.id ? 'filled' : 'outlined'}
              />
            ))}
          </Box>

          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <FormControl size="small" sx={{ flex: 1 }}>
              <InputLabel>Priority</InputLabel>
              <Select
                value={taskPriority}
                label="Priority"
                onChange={(e) => setTaskPriority(e.target.value)}
              >
                {TASK_PRIORITIES.map(p => (
                  <MenuItem key={p.id} value={p.id}>{p.icon} {p.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Due Date (optional)"
              type="datetime-local"
              size="small"
              sx={{ flex: 1 }}
              value={taskDueAt}
              onChange={(e) => setTaskDueAt(e.target.value)}
              InputLabelProps={{ shrink: true }}
              data-testid="input-task-due-date"
            />
          </Box>

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

      {/* Success Snackbar */}
      <Snackbar
        open={!!successMessage}
        autoHideDuration={6000}
        onClose={() => setSuccessMessage('')}
        message={successMessage}
      />
    </>
  );
});

export default TasksPanel;
