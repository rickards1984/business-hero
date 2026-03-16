import React, { useState, useEffect, useMemo } from 'react';
import {
  Box,
  Typography,
  Card,
  Chip,
  TextField,
  IconButton,
  Drawer,
  Divider,
  FormControlLabel,
  Switch,
  Tooltip,
  InputAdornment,
  Button,
} from '@mui/material';
import {
  Task as TaskIcon,
  Phone as PhoneIcon,
  Archive as ArchiveIcon,
  SmartToy as SmartToyIcon,
  Close as CloseIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
  ChevronRight as ChevronRightIcon,
} from '@mui/icons-material';
import { supabase, type Call } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';

interface CallsPanelProps {
  businessId: string;
  onCreateTaskFromCall?: () => void;
}

export default function CallsPanel({ businessId, onCreateTaskFromCall }: CallsPanelProps) {
  const [calls, setCalls] = useState<Call[]>([]);
  const [callSearch, setCallSearch] = useState('');
  const [callDateFilter, setCallDateFilter] = useState<'all' | 'today' | 'week' | 'month'>('all');
  const [callSourceFilter, setCallSourceFilter] = useState<'all' | 'receptionist' | 'Awaz'>('all');
  const [showArchivedCalls, setShowArchivedCalls] = useState(false);
  const [selectedCall, setSelectedCall] = useState<Call | null>(null);
  const [callPanelOpen, setCallPanelOpen] = useState(false);

  const fetchCalls = async (bizId: string) => {
    const { data, error } = await supabase
      .from('calls')
      .select('*')
      .eq('business_id', bizId)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('Failed to fetch calls:', error);
      return;
    }
    setCalls(data || []);
  };

  useEffect(() => {
    if (businessId) {
      fetchCalls(businessId);
    }
  }, [businessId]);

  const formatRelativeTime = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  };

  const handleArchiveCall = async (callId: string) => {
    try {
      const response = await apiRequest('PATCH', `/v1/calls/${callId}/archive`, {});
      if (response.ok) {
        const data = await response.json();
        setCalls(prev => prev.map(c =>
          c.id === callId ? { ...c, archived: data.archived } : c
        ));
      } else {
        console.error('Failed to archive call');
      }
    } catch (error) {
      console.error('Failed to archive call:', error);
    }
  };

  const filteredCalls = useMemo(() => {
    let result = calls;

    if (!showArchivedCalls) {
      result = result.filter(c => !c.archived);
    }

    if (callSourceFilter !== 'all') {
      result = result.filter(c => c.source === callSourceFilter);
    }

    if (callSearch) {
      const searchLower = callSearch.toLowerCase();
      result = result.filter(c =>
        (c.caller_name?.toLowerCase() || '').includes(searchLower) ||
        (c.caller_number?.toLowerCase() || '').includes(searchLower) ||
        (c.phone_number?.toLowerCase() || '').includes(searchLower) ||
        (c.summary?.toLowerCase() || '').includes(searchLower) ||
        (c.intent?.toLowerCase() || '').includes(searchLower)
      );
    }

    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfWeek = new Date(startOfToday);
    startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay());
    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);

    if (callDateFilter === 'today') {
      result = result.filter(c => new Date(c.created_at) >= startOfToday);
    } else if (callDateFilter === 'week') {
      result = result.filter(c => new Date(c.created_at) >= startOfWeek);
    } else if (callDateFilter === 'month') {
      result = result.filter(c => new Date(c.created_at) >= startOfMonth);
    }

    return result;
  }, [calls, callSearch, callDateFilter, callSourceFilter, showArchivedCalls]);

  const groupedCalls = useMemo(() => {
    const groups: { [key: string]: Call[] } = {};

    filteredCalls.forEach(call => {
      const date = new Date(call.created_at);
      const today = new Date();
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);

      let key: string;
      if (date.toDateString() === today.toDateString()) {
        key = 'Today';
      } else if (date.toDateString() === yesterday.toDateString()) {
        key = 'Yesterday';
      } else {
        key = date.toLocaleDateString('en-GB', {
          weekday: 'long',
          day: 'numeric',
          month: 'long'
        });
      }

      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(call);
    });

    return groups;
  }, [filteredCalls]);

  const callStats = useMemo(() => {
    const today = new Date();
    const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());

    const activeCalls = calls.filter(c => !c.archived);
    const todaysCalls = activeCalls.filter(c => new Date(c.created_at) >= startOfToday);
    const receptionistCount = activeCalls.filter(c => c.source === 'receptionist').length;
    const awazCount = activeCalls.filter(c => c.source !== 'receptionist').length;

    return {
      today: todaysCalls.length,
      total: activeCalls.length,
      receptionist: receptionistCount,
      awaz: awazCount,
    };
  }, [calls]);

  const calculateDuration = (start: string, end: string): string => {
    const startDate = new Date(start);
    const endDate = new Date(end);
    const diffMs = endDate.getTime() - startDate.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffSecs = Math.floor((diffMs % 60000) / 1000);
    if (diffMins > 0) return `${diffMins}m ${diffSecs}s`;
    return `${diffSecs}s`;
  };

  const formatDurationSec = (seconds: number | null | undefined): string => {
    if (!seconds) return '';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const OUTCOME_BADGE: Record<string, { color: 'success' | 'primary' | 'warning' | 'error' | 'default'; icon: string }> = {
    handled: { color: 'success', icon: '\u2705' },
    transferred: { color: 'primary', icon: '\uD83D\uDD04' },
    voicemail: { color: 'warning', icon: '\uD83D\uDCE9' },
    missed: { color: 'error', icon: '\u274C' },
    error: { color: 'error', icon: '\u26A0\uFE0F' },
  };

  const formatCallDateTime = (dateString: string) => {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-GB', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const handleCallClick = (call: Call) => {
    setSelectedCall(call);
    setCallPanelOpen(true);
  };

  return (
    <>
      {/* Stats Cards */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Card sx={{ flex: '1 1 140px', p: 2 }}>
          <Typography variant="caption" color="text.secondary">Today's Calls</Typography>
          <Typography variant="h4" color="primary.main">{callStats.today}</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2 }}>
          <Typography variant="caption" color="text.secondary">Total Active</Typography>
          <Typography variant="h4">{callStats.total}</Typography>
        </Card>
        <Card sx={{ flex: '1 1 140px', p: 2 }}>
          <Typography variant="caption" color="text.secondary">Source</Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 0.5 }}>
            <Tooltip title="AI Receptionist">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <SmartToyIcon fontSize="small" color="primary" />
                <Typography variant="h6" fontWeight={600}>{callStats.receptionist}</Typography>
              </Box>
            </Tooltip>
            <Tooltip title="Awaz">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <PhoneIcon fontSize="small" color="action" />
                <Typography variant="h6" fontWeight={600}>{callStats.awaz}</Typography>
              </Box>
            </Tooltip>
          </Box>
        </Card>
      </Box>

      {/* Search and Filter Toolbar */}
      <Box sx={{ mb: 3 }}>
        {/* Search Bar */}
        <TextField
          placeholder="Search by caller name, number, or summary..."
          value={callSearch}
          onChange={(e) => setCallSearch(e.target.value)}
          size="small"
          fullWidth
          sx={{ mb: 2 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon color="action" />
              </InputAdornment>
            ),
            endAdornment: callSearch && (
              <InputAdornment position="end">
                <IconButton size="small" onClick={() => setCallSearch('')}>
                  <ClearIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ),
          }}
        />

        {/* Filters Row */}
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Date Filter Chips */}
          <Box sx={{ display: 'flex', gap: 1 }}>
            {[
              { value: 'today', label: 'Today' },
              { value: 'week', label: 'This Week' },
              { value: 'month', label: 'This Month' },
              { value: 'all', label: 'All Time' },
            ].map((filter) => (
              <Chip
                key={filter.value}
                label={filter.label}
                onClick={() => setCallDateFilter(filter.value as 'all' | 'today' | 'week' | 'month')}
                color={callDateFilter === filter.value ? 'primary' : 'default'}
                variant={callDateFilter === filter.value ? 'filled' : 'outlined'}
                size="small"
              />
            ))}
          </Box>

          {/* Source Filter Chips */}
          <Box sx={{ display: 'flex', gap: 1 }}>
            {([
              { value: 'all', label: 'All Calls' },
              { value: 'receptionist', label: 'AI Receptionist' },
              { value: 'Awaz', label: 'Awaz' },
            ] as const).map((f) => (
              <Chip
                key={f.value}
                label={f.label}
                icon={f.value === 'receptionist' ? <SmartToyIcon /> : undefined}
                onClick={() => setCallSourceFilter(f.value)}
                color={callSourceFilter === f.value ? 'secondary' : 'default'}
                variant={callSourceFilter === f.value ? 'filled' : 'outlined'}
                size="small"
              />
            ))}
          </Box>

          {/* Show Archived Toggle */}
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={showArchivedCalls}
                onChange={(e) => setShowArchivedCalls(e.target.checked)}
              />
            }
            label="Show archived"
            sx={{ ml: 'auto' }}
          />
        </Box>
      </Box>

      {/* Calls List */}
      {filteredCalls.length === 0 ? (
        <Card sx={{ p: 4, textAlign: 'center' }}>
          <PhoneIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />
          <Typography color="text.secondary">
            {callSearch || callDateFilter !== 'all' ? 'No calls match your filters' : 'No calls yet'}
          </Typography>
        </Card>
      ) : (
        <Box>
          {Object.entries(groupedCalls).map(([date, dateCalls]) => (
            <Box key={date} sx={{ mb: 3 }}>
              {/* Date Header */}
              <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, ml: 1 }}>
                {date} ({dateCalls.length} {dateCalls.length === 1 ? 'call' : 'calls'})
              </Typography>

              {/* Calls for this date */}
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {dateCalls.map((call) => (
                  <Card
                    key={call.id}
                    data-testid={`card-call-${call.id}`}
                    sx={{
                      p: 2,
                      cursor: 'pointer',
                      opacity: call.archived ? 0.6 : 1,
                      '&:hover': { boxShadow: 2, bgcolor: 'action.hover' },
                      transition: 'all 0.2s',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 2,
                    }}
                    onClick={() => handleCallClick(call)}
                  >
                    {/* Icon — different for AI Receptionist vs Awaz */}
                    <Box sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '50%',
                      bgcolor: call.source === 'receptionist' ? 'secondary.light' : 'primary.light',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      {call.source === 'receptionist'
                        ? <SmartToyIcon color="secondary" fontSize="small" />
                        : <PhoneIcon color="primary" fontSize="small" />}
                    </Box>

                    {/* Main Content */}
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="subtitle1" fontWeight={600} noWrap>
                          {call.caller_name || 'Unknown Caller'}
                        </Typography>
                        {call.source === 'receptionist' && (
                          <Chip label="AI" size="small" color="secondary" sx={{ height: 20, fontSize: '0.7rem' }} />
                        )}
                        {call.archived && (
                          <Chip label="Archived" size="small" />
                        )}
                      </Box>
                      <Typography variant="body2" color="text.secondary" noWrap>
                        {call.caller_number || call.phone_number || 'No number'}
                        {(call.summary || call.notes) && ` \u00B7 ${(call.summary || call.notes || '').substring(0, 50)}...`}
                      </Typography>
                    </Box>

                    {/* Right side */}
                    <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                      <Typography variant="caption" color="text.secondary">
                        {new Date(call.created_at).toLocaleTimeString('en-GB', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                        {call.duration_seconds ? ` \u00B7 ${formatDurationSec(call.duration_seconds)}` : ''}
                      </Typography>
                      <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end', mt: 0.5 }}>
                        {call.source === 'receptionist' && call.outcome && OUTCOME_BADGE[call.outcome] && (
                          <Chip
                            label={`${OUTCOME_BADGE[call.outcome].icon} ${call.outcome}`}
                            size="small"
                            color={OUTCOME_BADGE[call.outcome].color}
                            variant="outlined"
                            sx={{ height: 22, fontSize: '0.7rem' }}
                          />
                        )}
                        {call.intent && call.source !== 'receptionist' && (
                          <Chip label={call.intent} size="small" variant="outlined" sx={{ height: 22, fontSize: '0.7rem' }} />
                        )}
                      </Box>
                    </Box>

                    <ChevronRightIcon color="action" />
                  </Card>
                ))}
              </Box>
            </Box>
          ))}
        </Box>
      )}

      {/* Call Detail Panel */}
      <Drawer anchor="right" open={callPanelOpen} onClose={() => { setCallPanelOpen(false); setSelectedCall(null); }}
        PaperProps={{ sx: { bgcolor: 'var(--surface-primary, #0d0f13)', backgroundImage: 'none' } }}
      >
        <Box sx={{ width: 450, p: 3 }}>
          {selectedCall && (
            <>
              {/* Header */}
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  {selectedCall.source === 'receptionist'
                    ? <SmartToyIcon color="secondary" />
                    : <PhoneIcon color="primary" />}
                  <Typography variant="h6" fontWeight={600}>
                    Call Details
                  </Typography>
                  {selectedCall.source === 'receptionist' && (
                    <Chip label="AI Receptionist" size="small" color="secondary" />
                  )}
                </Box>
                <IconButton onClick={() => { setCallPanelOpen(false); setSelectedCall(null); }}>
                  <CloseIcon />
                </IconButton>
              </Box>

              {/* Caller Info */}
              <Card sx={{ p: 2, mb: 3, bgcolor: 'rgba(255, 255, 255, 0.04)', border: '0.5px solid rgba(255, 255, 255, 0.08)' }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Caller
                </Typography>
                <Typography variant="h5" fontWeight={600}>
                  {selectedCall.caller_name || 'Unknown Caller'}
                </Typography>
                {(selectedCall.caller_number || selectedCall.phone_number) && (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
                    <PhoneIcon fontSize="small" color="action" />
                    <Typography variant="body1">{selectedCall.caller_number || selectedCall.phone_number}</Typography>
                  </Box>
                )}
              </Card>

              {/* Date/Time */}
              <Box sx={{ mb: 3 }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Date & Time
                </Typography>
                <Typography variant="body1">
                  {formatCallDateTime(selectedCall.created_at)}
                </Typography>
                {selectedCall.duration_seconds ? (
                  <Typography variant="caption" color="text.secondary">
                    Duration: {formatDurationSec(selectedCall.duration_seconds)}
                  </Typography>
                ) : selectedCall.started_at && selectedCall.ended_at ? (
                  <Typography variant="caption" color="text.secondary">
                    Duration: {calculateDuration(selectedCall.started_at, selectedCall.ended_at)}
                  </Typography>
                ) : null}
              </Box>

              {/* Outcome (receptionist) */}
              {selectedCall.source === 'receptionist' && selectedCall.outcome && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Outcome
                  </Typography>
                  <Chip
                    label={`${OUTCOME_BADGE[selectedCall.outcome]?.icon || ''} ${selectedCall.outcome}`}
                    color={OUTCOME_BADGE[selectedCall.outcome]?.color || 'default'}
                    variant="outlined"
                  />
                </Box>
              )}

              {/* Intent Badge */}
              {selectedCall.intent && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Intent
                  </Typography>
                  <Chip
                    label={selectedCall.intent}
                    color="primary"
                    variant="outlined"
                  />
                </Box>
              )}

              {/* Summary */}
              {(selectedCall.summary || selectedCall.notes) && (
                <Box sx={{ mb: 3 }}>
                  <Typography sx={{ fontSize: '0.75rem', fontWeight: 600, color: 'rgba(232, 230, 225, 0.6)', textTransform: 'uppercase', letterSpacing: '0.05em', mb: 1 }}>
                    Summary
                  </Typography>
                  <Card sx={{ p: 2, bgcolor: 'rgba(255, 255, 255, 0.04)', border: '0.5px solid rgba(255, 255, 255, 0.08)' }}>
                    <Typography variant="body2" sx={{ color: '#e8e6e1' }}>
                      {selectedCall.summary || selectedCall.notes}
                    </Typography>
                  </Card>
                </Box>
              )}

              {/* Transcript */}
              {selectedCall.transcript && (
                <Box sx={{ mb: 3 }}>
                  <Typography sx={{ fontSize: '0.75rem', fontWeight: 600, color: 'rgba(232, 230, 225, 0.6)', textTransform: 'uppercase', letterSpacing: '0.05em', mb: 1.5 }}>
                    Transcript
                  </Typography>
                  <Box sx={{ maxHeight: 400, overflow: 'auto', px: 0.5 }}>
                    {selectedCall.source === 'receptionist' ? (
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        {selectedCall.transcript.split('\n').filter(Boolean).map((line: string, idx: number) => {
                          const isCaller = line.startsWith('Caller:');
                          const text = line.replace(/^(Caller|Receptionist):\s*/, '');
                          return (
                            <Box key={idx} sx={{ display: 'flex', justifyContent: isCaller ? 'flex-start' : 'flex-end' }}>
                              <Box
                                className={`transcript-bubble ${isCaller ? 'transcript-bubble--caller' : 'transcript-bubble--receptionist'}`}
                                sx={{ maxWidth: '85%', px: 2, py: 1 }}
                              >
                                <Typography sx={{ fontSize: '0.625rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', mb: '2px', color: isCaller ? 'rgba(232, 230, 225, 0.5)' : '#a78bfa' }}>
                                  {isCaller ? 'Caller' : 'Receptionist'}
                                </Typography>
                                <Typography sx={{ fontSize: '0.8125rem', lineHeight: 1.625, color: '#e8e6e1' }}>{text}</Typography>
                              </Box>
                            </Box>
                          );
                        })}
                      </Box>
                    ) : (
                      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', color: '#e8e6e1' }}>
                        {selectedCall.transcript}
                      </Typography>
                    )}
                  </Box>
                </Box>
              )}

              {/* No details message */}
              {!selectedCall.summary && !selectedCall.notes && !selectedCall.transcript && !selectedCall.intent && (
                <Card sx={{ p: 3, textAlign: 'center', bgcolor: 'rgba(255, 255, 255, 0.04)', border: '0.5px solid rgba(255, 255, 255, 0.08)', mb: 3 }}>
                  <Typography color="text.secondary">
                    No additional details available for this call.
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Call details will appear here when captured by the AI receptionist.
                  </Typography>
                </Card>
              )}

              <Divider sx={{ my: 3 }} />

              {/* Actions */}
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {/* Create Task from Call */}
                {onCreateTaskFromCall && (
                  <Button
                    variant="outlined"
                    startIcon={<TaskIcon />}
                    fullWidth
                    onClick={() => {
                      onCreateTaskFromCall();
                      setCallPanelOpen(false);
                    }}
                  >
                    Create Task from Call
                  </Button>
                )}

                {/* Archive */}
                <Button
                  variant="outlined"
                  startIcon={<ArchiveIcon />}
                  onClick={() => {
                    handleArchiveCall(selectedCall.id);
                    setCallPanelOpen(false);
                    setSelectedCall(null);
                  }}
                  fullWidth
                  sx={{
                    bgcolor: 'var(--glass-bg)',
                    border: '0.5px solid var(--glass-border)',
                    color: 'hsl(var(--foreground))',
                    '&:hover': { bgcolor: 'rgba(255,255,255,0.08)' },
                  }}
                >
                  {selectedCall.archived ? 'Unarchive' : 'Archive Call'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Drawer>
    </>
  );
}
