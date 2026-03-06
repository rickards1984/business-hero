import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Container,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Select,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Toolbar,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CelebrationIcon from '@mui/icons-material/Celebration';
import { useAuth } from '@/contexts/AuthContext';
import { apiRequest } from '@/lib/queryClient';

const TIMEZONES = [
  'Europe/London',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Europe/Paris',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
];

const ALL_FEATURE_KEYS = [
  { key: 'email', label: 'Email Integration' },
  { key: 'calendar', label: 'Calendar Sync' },
  { key: 'aria_chat', label: 'AI Assistant (Chat)' },
  { key: 'aria_voice', label: 'AI Assistant (Voice)' },
  { key: 'receptionist', label: 'AI Receptionist' },
  { key: 'accounting', label: 'Accounting (Xero)' },
];

interface PlanDef {
  id: string;
  name: string;
  description: string | null;
  monthly_price_gbp: number | null;
  features: Record<string, boolean>;
  limits: Record<string, any>;
  sort_order: number;
}

interface VoiceOption {
  id: string;
  name: string;
  description: string;
  gender: string;
  accent: string;
}

interface ChecklistItem {
  id: string;
  item_key: string;
  label: string;
  category: string;
  is_completed: boolean;
  notes: string | null;
}

interface WizardSession {
  id: string;
  business_id: string;
  status: string;
  current_step: string;
  steps_completed: Record<string, boolean>;
  wizard_data: Record<string, any>;
}

const STEP_ORDER = [
  'business_details',
  'owner_account',
  'plan_features',
  'email_setup',
  'receptionist_setup',
  'calendar_setup',
  'accounting_setup',
  'review_activate',
];

const STEP_LABELS = [
  'Business',
  'Owner',
  'Features',
  'Email',
  'Receptionist',
  'Calendar',
  'Accounting',
  'Review',
];

const TONE_OPTIONS = ['professional', 'friendly', 'casual'];
const LANGUAGE_OPTIONS = [
  { value: 'en-GB', label: 'English (UK)' },
  { value: 'en-US', label: 'English (US)' },
  { value: 'en-AU', label: 'English (AU)' },
];

export default function AdminOnboardingWizard() {
  const navigate = useNavigate();
  const { businessId: resumeBusinessId } = useParams<{ businessId?: string }>();
  const { user, isAdmin, loading: authLoading, adminLoading } = useAuth();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [completed, setCompleted] = useState(false);

  const [plans, setPlans] = useState<PlanDef[]>([]);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [checklist, setChecklist] = useState<ChecklistItem[]>([]);

  const [session, setSession] = useState<WizardSession | null>(null);
  const [businessId, setBusinessId] = useState<string | null>(resumeBusinessId || null);
  const [currentStepIdx, setCurrentStepIdx] = useState(0);

  // Step 1
  const [bizName, setBizName] = useState('');
  const [bizTimezone, setBizTimezone] = useState('Europe/London');
  const [bizPlan, setBizPlan] = useState('starter');

  // Step 2
  const [ownerEmail, setOwnerEmail] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [sendInvite, setSendInvite] = useState(true);

  // Step 3
  const [featureFlags, setFeatureFlags] = useState<Record<string, boolean>>({});
  const [planFeatureDefaults, setPlanFeatureDefaults] = useState<Record<string, boolean>>({});

  // Step 4
  const [emailNotes, setEmailNotes] = useState('');

  // Step 5
  const [recPhone, setRecPhone] = useState('');
  const [recVoice, setRecVoice] = useState('shimmer');
  const [recTone, setRecTone] = useState('professional');
  const [recLanguage, setRecLanguage] = useState('en-GB');
  const [recGreeting, setRecGreeting] = useState('');
  const [recKbHours, setRecKbHours] = useState('');
  const [recKbServices, setRecKbServices] = useState('');
  const [recKbPricing, setRecKbPricing] = useState('');
  const [recKbLocation, setRecKbLocation] = useState('');

  // Step 6
  const [calNotes, setCalNotes] = useState('');

  // Step 7
  const [accNotes, setAccNotes] = useState('');

  // Step 8
  const [activateNow, setActivateNow] = useState(true);
  const [sendWelcome, setSendWelcome] = useState(true);
  const [adminNotes, setAdminNotes] = useState('');

  const selectedPlan = useMemo(() => plans.find((p) => p.id === bizPlan), [plans, bizPlan]);

  const skippedSteps = useMemo(() => {
    const skip: Record<string, boolean> = {};
    if (!featureFlags.receptionist) skip.receptionist_setup = true;
    if (!featureFlags.accounting) skip.accounting_setup = true;
    return skip;
  }, [featureFlags]);

  const visibleStepIndices = useMemo(() => {
    return STEP_ORDER.map((_, i) => i).filter((i) => !skippedSteps[STEP_ORDER[i]]);
  }, [skippedSteps]);

  useEffect(() => {
    if (!authLoading && !user) navigate('/login');
    else if (!authLoading && !adminLoading && !isAdmin) navigate('/app');
  }, [user, isAdmin, authLoading, adminLoading, navigate]);

  useEffect(() => {
    if (user && isAdmin) loadInitialData();
  }, [user, isAdmin]);

  const loadInitialData = async () => {
    setLoading(true);
    try {
      const [planRes, voiceRes] = await Promise.all([
        apiRequest('GET', '/v1/admin/onboarding/plans'),
        apiRequest('GET', '/v1/receptionist/voices'),
      ]);
      const planData: PlanDef[] = await planRes.json();
      const voiceData: VoiceOption[] = await voiceRes.json();
      setPlans(planData);
      setVoices(voiceData);

      const defaultPlan = planData.find((p) => p.id === 'starter');
      if (defaultPlan) {
        setFeatureFlags({ ...defaultPlan.features });
        setPlanFeatureDefaults({ ...defaultPlan.features });
      }

      if (resumeBusinessId) {
        await resumeSession(resumeBusinessId);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  const resumeSession = async (bId: string) => {
    try {
      const res = await apiRequest('GET', `/v1/admin/onboarding/session/${bId}`);
      const data: WizardSession = await res.json();
      setSession(data);
      setBusinessId(bId);

      const wd = data.wizard_data || {};
      if (wd.business_details) {
        setBizName(wd.business_details.name || '');
        setBizTimezone(wd.business_details.timezone || 'Europe/London');
        setBizPlan(wd.business_details.plan_tier || 'starter');
      }
      if (wd.owner_account) {
        setOwnerEmail(wd.owner_account.owner_email || '');
        setOwnerName(wd.owner_account.owner_name || '');
        setSendInvite(wd.owner_account.send_invite ?? true);
      }
      if (wd.plan_features) {
        setFeatureFlags(wd.plan_features.feature_flags || {});
      }
      if (wd.email_setup) {
        setEmailNotes(wd.email_setup.notes || '');
      }
      if (wd.receptionist_setup) {
        const rs = wd.receptionist_setup;
        setRecPhone(rs.twilio_phone_number || '');
        setRecVoice(rs.voice || 'shimmer');
        setRecTone(rs.tone || 'professional');
        setRecLanguage(rs.language || 'en-GB');
        setRecGreeting(rs.greeting_message || '');
      }
      if (wd.calendar_setup) {
        setCalNotes(wd.calendar_setup.notes || '');
      }
      if (wd.accounting_setup) {
        setAccNotes(wd.accounting_setup.notes || '');
      }
      if (wd.review_activate) {
        setActivateNow(wd.review_activate.activate_now ?? true);
        setSendWelcome(wd.review_activate.send_welcome_email ?? true);
        setAdminNotes(wd.review_activate.admin_notes || '');
      }

      const stepIdx = STEP_ORDER.indexOf(data.current_step);
      if (stepIdx >= 0) setCurrentStepIdx(stepIdx);
    } catch {
      setError('No active onboarding session found for this business.');
    }
  };

  const fetchChecklist = useCallback(async (bId: string) => {
    try {
      const res = await apiRequest('GET', `/v1/admin/onboarding/checklist/${bId}`);
      setChecklist(await res.json());
    } catch {}
  }, []);

  const handleNext = async () => {
    setError('');
    setSaving(true);

    try {
      const stepName = STEP_ORDER[currentStepIdx];

      if (stepName === 'business_details' && !businessId) {
        const res = await apiRequest('POST', '/v1/admin/onboarding/start', {
          name: bizName.trim(),
          timezone: bizTimezone,
          plan_tier: bizPlan,
        });
        const data = await res.json();
        setBusinessId(data.business.id);
        setSession(data.session);

        const plan = plans.find((p) => p.id === bizPlan);
        if (plan) {
          setFeatureFlags({ ...plan.features });
          setPlanFeatureDefaults({ ...plan.features });
        }

        setRecGreeting(`Hello, thank you for calling ${bizName.trim()}. How can I help you today?`);
        advanceToNext(currentStepIdx);
        return;
      }

      if (!businessId) throw new Error('No business ID — please start from step 1');

      let stepData: any = {};

      switch (stepName) {
        case 'owner_account':
          stepData = { owner_email: ownerEmail, owner_name: ownerName, send_invite: sendInvite };
          break;
        case 'plan_features':
          stepData = { feature_flags: featureFlags };
          break;
        case 'email_setup':
          stepData = { status: 'pending', notes: emailNotes || null };
          break;
        case 'receptionist_setup':
          stepData = {
            skip: false,
            twilio_phone_number: recPhone.replace(/\s/g, '').trim() || null,
            voice: recVoice,
            greeting_message: recGreeting,
            tone: recTone,
            language: recLanguage,
            knowledge_base_items: [
              { category: 'hours', title: 'Opening Hours', content: recKbHours },
              { category: 'services', title: 'Services Offered', content: recKbServices },
              { category: 'pricing', title: 'Pricing Information', content: recKbPricing },
              { category: 'location', title: 'Location & Parking', content: recKbLocation },
            ].filter((item) => item.content.trim()),
          };
          break;
        case 'calendar_setup':
          stepData = { status: 'pending', notes: calNotes || null };
          break;
        case 'accounting_setup':
          stepData = { status: 'pending', notes: accNotes || null };
          break;
        case 'review_activate':
          stepData = { activate_now: activateNow, send_welcome_email: sendWelcome, admin_notes: adminNotes || null };
          break;
      }

      const res = await apiRequest(
        'PUT',
        `/v1/admin/onboarding/session/${businessId}/step?step_name=${stepName}`,
        stepData,
      );
      const result = await res.json();

      if (result.status === 'completed') {
        setCompleted(true);
        return;
      }

      if (result.steps_completed) {
        setSession((prev) => prev ? { ...prev, steps_completed: result.steps_completed, current_step: result.next_step } : prev);
      }

      const nextIdx = STEP_ORDER.indexOf(result.next_step);
      if (nextIdx >= 0) {
        setCurrentStepIdx(nextIdx);
        if (result.next_step === 'review_activate') {
          fetchChecklist(businessId);
        }
      } else {
        advanceToNext(currentStepIdx);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to save step');
    } finally {
      setSaving(false);
    }
  };

  const handleSkipStep = async () => {
    setError('');
    setSaving(true);
    try {
      const stepName = STEP_ORDER[currentStepIdx];
      if (!businessId) return;

      const stepData: any = { status: 'skip' };
      if (stepName === 'receptionist_setup') {
        Object.assign(stepData, { skip: true });
      }
      if (stepName === 'email_setup') stepData.notes = emailNotes || null;
      if (stepName === 'calendar_setup') stepData.notes = calNotes || null;
      if (stepName === 'accounting_setup') stepData.notes = accNotes || null;

      const res = await apiRequest(
        'PUT',
        `/v1/admin/onboarding/session/${businessId}/step?step_name=${stepName}`,
        stepData,
      );
      const result = await res.json();

      if (result.status === 'completed') {
        setCompleted(true);
        return;
      }

      const nextIdx = STEP_ORDER.indexOf(result.next_step);
      if (nextIdx >= 0) {
        setCurrentStepIdx(nextIdx);
        if (result.next_step === 'review_activate') fetchChecklist(businessId!);
      } else {
        advanceToNext(currentStepIdx);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to skip step');
    } finally {
      setSaving(false);
    }
  };

  const advanceToNext = (fromIdx: number) => {
    let next = fromIdx + 1;
    while (next < STEP_ORDER.length && skippedSteps[STEP_ORDER[next]]) next++;
    if (next < STEP_ORDER.length) {
      setCurrentStepIdx(next);
      if (STEP_ORDER[next] === 'review_activate' && businessId) fetchChecklist(businessId);
    }
  };

  const handleBack = () => {
    let prev = currentStepIdx - 1;
    while (prev >= 0 && skippedSteps[STEP_ORDER[prev]]) prev--;
    if (prev >= 0) setCurrentStepIdx(prev);
  };

  const canProceed = useMemo(() => {
    const stepName = STEP_ORDER[currentStepIdx];
    switch (stepName) {
      case 'business_details': return bizName.trim().length > 0;
      case 'owner_account': return ownerEmail.trim().length > 0;
      case 'plan_features': return true;
      case 'email_setup': return true;
      case 'receptionist_setup': return recGreeting.trim().length > 0;
      case 'calendar_setup': return true;
      case 'accounting_setup': return true;
      case 'review_activate': return true;
      default: return true;
    }
  }, [currentStepIdx, bizName, ownerEmail, recGreeting]);

  // Completed screen
  if (completed) {
    return (
      <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Card sx={{ maxWidth: 520, textAlign: 'center', p: 4 }}>
          <CelebrationIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
          <Typography variant="h5" gutterBottom>Onboarding Complete!</Typography>
          <Typography color="text.secondary" sx={{ mb: 3 }}>
            The business has been {activateNow ? 'activated and is ready to go' : 'created (not yet activated)'}.
          </Typography>
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
            {businessId && (
              <Button variant="contained" onClick={() => navigate(`/admin/businesses/${businessId}`)}>
                View Business
              </Button>
            )}
            <Button variant="outlined" onClick={() => navigate('/admin/onboarding')}>
              All Onboardings
            </Button>
            <Button variant="outlined" onClick={() => navigate('/admin')}>
              Dashboard
            </Button>
          </Box>
        </Card>
      </Box>
    );
  }

  if (authLoading || adminLoading || loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  const stepName = STEP_ORDER[currentStepIdx];

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static" elevation={1}>
        <Toolbar>
          <Button color="inherit" startIcon={<ArrowBackIcon />} onClick={() => navigate('/admin')} sx={{ mr: 2 }}>
            Back
          </Button>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Onboarding Wizard {bizName ? `— ${bizName}` : ''}
          </Typography>
        </Toolbar>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 4 }}>
        {error && <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError('')}>{error}</Alert>}

        <Paper sx={{ p: 3, mb: 3 }}>
          <Stepper activeStep={visibleStepIndices.indexOf(currentStepIdx)} alternativeLabel>
            {STEP_ORDER.map((s, idx) => {
              const isSkipped = skippedSteps[s];
              const isDone = session?.steps_completed?.[s];
              return (
                <Step key={s} completed={!!isDone && !isSkipped}>
                  <StepLabel
                    optional={isSkipped ? <Typography variant="caption" color="text.disabled">Skipped</Typography> : undefined}
                    sx={isSkipped ? { '& .MuiStepLabel-label': { textDecoration: 'line-through', color: 'text.disabled' } } : undefined}
                  >
                    {STEP_LABELS[idx]}
                  </StepLabel>
                </Step>
              );
            })}
          </Stepper>
        </Paper>

        <Paper sx={{ p: 4, mb: 3 }}>
          {/* STEP 1: Business Details */}
          {stepName === 'business_details' && (
            <Box>
              <Typography variant="h6" gutterBottom>Business Details</Typography>
              <TextField
                autoFocus
                label="Business Name"
                fullWidth
                required
                value={bizName}
                onChange={(e) => setBizName(e.target.value)}
                sx={{ mb: 3 }}
              />
              <FormControl fullWidth sx={{ mb: 3 }}>
                <InputLabel>Timezone</InputLabel>
                <Select value={bizTimezone} label="Timezone" onChange={(e) => setBizTimezone(e.target.value)}>
                  {TIMEZONES.map((tz) => <MenuItem key={tz} value={tz}>{tz}</MenuItem>)}
                </Select>
              </FormControl>

              <Typography variant="subtitle1" gutterBottom>Select a Plan</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {plans.map((plan) => (
                  <Card
                    key={plan.id}
                    variant="outlined"
                    sx={{
                      cursor: 'pointer',
                      borderColor: bizPlan === plan.id ? 'primary.main' : 'divider',
                      borderWidth: bizPlan === plan.id ? 2 : 1,
                      bgcolor: bizPlan === plan.id ? 'primary.light' : 'background.paper',
                    }}
                    onClick={() => {
                      setBizPlan(plan.id);
                      setFeatureFlags({ ...plan.features });
                      setPlanFeatureDefaults({ ...plan.features });
                    }}
                  >
                    <CardContent>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Radio checked={bizPlan === plan.id} />
                          <Typography variant="subtitle1" fontWeight="bold">{plan.name}</Typography>
                          {plan.id === 'pro' && <Chip label="Popular" size="small" color="primary" />}
                        </Box>
                        {plan.monthly_price_gbp != null && (
                          <Typography variant="subtitle1" fontWeight="bold">£{plan.monthly_price_gbp}/mo</Typography>
                        )}
                      </Box>
                      <Typography variant="body2" color="text.secondary" sx={{ ml: 5, mb: 1 }}>{plan.description}</Typography>
                      <Box sx={{ ml: 5, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                        {ALL_FEATURE_KEYS.map((f) => (
                          <Chip
                            key={f.key}
                            label={f.label}
                            size="small"
                            variant="outlined"
                            color={plan.features[f.key] ? 'success' : 'default'}
                            sx={!plan.features[f.key] ? { textDecoration: 'line-through', opacity: 0.5 } : undefined}
                          />
                        ))}
                      </Box>
                    </CardContent>
                  </Card>
                ))}
              </Box>
            </Box>
          )}

          {/* STEP 2: Owner Account */}
          {stepName === 'owner_account' && (
            <Box>
              <Typography variant="h6" gutterBottom>Business Owner Account</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                This person will be the primary user for this business.
              </Typography>
              <TextField
                autoFocus
                label="Owner Name"
                fullWidth
                value={ownerName}
                onChange={(e) => setOwnerName(e.target.value)}
                sx={{ mb: 2 }}
              />
              <TextField
                label="Owner Email"
                type="email"
                fullWidth
                required
                value={ownerEmail}
                onChange={(e) => setOwnerEmail(e.target.value)}
                sx={{ mb: 2 }}
              />
              <FormControlLabel
                control={<Checkbox checked={sendInvite} onChange={(e) => setSendInvite(e.target.checked)} />}
                label="Send welcome email with login instructions"
              />
              <Alert severity="info" sx={{ mt: 2 }}>
                The owner will receive an email to set their password and log in. They'll need to connect their own email and calendar integrations via OAuth.
              </Alert>
            </Box>
          )}

          {/* STEP 3: Plan & Features */}
          {stepName === 'plan_features' && (
            <Box>
              <Typography variant="h6" gutterBottom>Features &amp; Permissions</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                Based on the <strong>{selectedPlan?.name || bizPlan}</strong> plan. You can override individual features below.
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {ALL_FEATURE_KEYS.map((f) => {
                  const planDefault = planFeatureDefaults[f.key] ?? false;
                  const isOverridden = featureFlags[f.key] !== planDefault;
                  return (
                    <Box
                      key={f.key}
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        p: 1.5,
                        borderRadius: 1,
                        border: '1px solid',
                        borderColor: isOverridden ? 'warning.main' : 'divider',
                        bgcolor: isOverridden ? 'rgba(255,152,0,0.04)' : 'background.paper',
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <FormControlLabel
                          control={
                            <Checkbox
                              checked={!!featureFlags[f.key]}
                              onChange={(e) => setFeatureFlags((prev) => ({ ...prev, [f.key]: e.target.checked }))}
                            />
                          }
                          label={f.label}
                        />
                        {isOverridden && <Chip label="Override" size="small" color="warning" />}
                      </Box>
                      <Typography variant="caption" color="text.secondary">
                        {planDefault ? 'Included in plan' : `Not in ${selectedPlan?.name || 'plan'}`}
                      </Typography>
                    </Box>
                  );
                })}
              </Box>
              {Object.entries(featureFlags).some(([k, v]) => v && !planFeatureDefaults[k]) && (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  You've enabled features not included in the {selectedPlan?.name} plan. These are custom overrides.
                </Alert>
              )}
            </Box>
          )}

          {/* STEP 4: Email Setup */}
          {stepName === 'email_setup' && (
            <Box>
              <Typography variant="h6" gutterBottom>Email Integration</Typography>
              <Alert severity="info" sx={{ mb: 3 }}>
                Email requires the business owner to connect their Google or Microsoft account via OAuth. This can't be done on their behalf.
              </Alert>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
                <Typography variant="body2">Status:</Typography>
                <Chip label="Pending owner action" size="small" color="warning" />
              </Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                The business owner will be prompted to connect their email when they first log in.
              </Typography>
              <TextField
                label="Admin notes (optional)"
                fullWidth
                multiline
                rows={2}
                value={emailNotes}
                onChange={(e) => setEmailNotes(e.target.value)}
                placeholder="e.g., Owner uses Gmail, enquiries@business.co.uk"
              />
            </Box>
          )}

          {/* STEP 5: AI Receptionist */}
          {stepName === 'receptionist_setup' && (
            <Box>
              <Typography variant="h6" gutterBottom>AI Receptionist Setup</Typography>

              <TextField
                label="Twilio Phone Number"
                fullWidth
                value={recPhone}
                onChange={(e) => setRecPhone(e.target.value)}
                placeholder="+44..."
                helperText="Enter the Twilio number purchased for this business. Leave blank to assign later."
                sx={{ mb: 3 }}
              />

              <Divider sx={{ my: 2 }} />

              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
                <FormControl sx={{ minWidth: 200, flex: 1 }}>
                  <InputLabel>Voice</InputLabel>
                  <Select value={recVoice} label="Voice" onChange={(e) => setRecVoice(e.target.value)}>
                    {voices.map((v) => (
                      <MenuItem key={v.id} value={v.id}>{v.name} — {v.description}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl sx={{ minWidth: 180 }}>
                  <InputLabel>Language</InputLabel>
                  <Select value={recLanguage} label="Language" onChange={(e) => setRecLanguage(e.target.value)}>
                    {LANGUAGE_OPTIONS.map((l) => <MenuItem key={l.value} value={l.value}>{l.label}</MenuItem>)}
                  </Select>
                </FormControl>
              </Box>

              <Typography variant="subtitle2" sx={{ mb: 1 }}>Tone</Typography>
              <RadioGroup row value={recTone} onChange={(e) => setRecTone(e.target.value)} sx={{ mb: 3 }}>
                {TONE_OPTIONS.map((t) => (
                  <FormControlLabel key={t} value={t} control={<Radio />} label={t.charAt(0).toUpperCase() + t.slice(1)} />
                ))}
              </RadioGroup>

              <Divider sx={{ my: 2 }} />

              <TextField
                label="Greeting Message"
                fullWidth
                required
                multiline
                rows={2}
                value={recGreeting}
                onChange={(e) => setRecGreeting(e.target.value)}
                helperText={`${recGreeting.length}/200 characters`}
                inputProps={{ maxLength: 200 }}
                sx={{ mb: 3 }}
              />

              <Divider sx={{ my: 2 }} />

              <Typography variant="subtitle2" gutterBottom>Quick Knowledge Base</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Help the AI answer common questions. The business owner can add more later.
              </Typography>
              <TextField label="Opening Hours" fullWidth multiline rows={2} value={recKbHours} onChange={(e) => setRecKbHours(e.target.value)} sx={{ mb: 2 }} />
              <TextField label="Services Offered" fullWidth multiline rows={2} value={recKbServices} onChange={(e) => setRecKbServices(e.target.value)} sx={{ mb: 2 }} />
              <TextField label="Pricing Information" fullWidth multiline rows={2} value={recKbPricing} onChange={(e) => setRecKbPricing(e.target.value)} sx={{ mb: 2 }} />
              <TextField label="Location & Parking" fullWidth multiline rows={2} value={recKbLocation} onChange={(e) => setRecKbLocation(e.target.value)} />
            </Box>
          )}

          {/* STEP 6: Calendar */}
          {stepName === 'calendar_setup' && (
            <Box>
              <Typography variant="h6" gutterBottom>Calendar Integration</Typography>
              <Alert severity="info" sx={{ mb: 3 }}>
                Calendar requires the business owner to connect via OAuth.
              </Alert>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
                <Typography variant="body2">Status:</Typography>
                <Chip label="Pending owner action" size="small" color="warning" />
              </Box>
              <TextField
                label="Admin notes (optional)"
                fullWidth
                multiline
                rows={2}
                value={calNotes}
                onChange={(e) => setCalNotes(e.target.value)}
              />
            </Box>
          )}

          {/* STEP 7: Accounting */}
          {stepName === 'accounting_setup' && (
            <Box>
              <Typography variant="h6" gutterBottom>Accounting (Xero) Integration</Typography>
              <Alert severity="info" sx={{ mb: 3 }}>
                Xero requires the business owner to connect via OAuth.
              </Alert>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
                <Typography variant="body2">Status:</Typography>
                <Chip label="Pending owner action" size="small" color="warning" />
              </Box>
              <TextField
                label="Admin notes (optional)"
                fullWidth
                multiline
                rows={2}
                value={accNotes}
                onChange={(e) => setAccNotes(e.target.value)}
              />
            </Box>
          )}

          {/* STEP 8: Review & Activate */}
          {stepName === 'review_activate' && (
            <Box>
              <Typography variant="h6" gutterBottom>Review &amp; Activate</Typography>

              <Card variant="outlined" sx={{ mb: 3 }}>
                <CardContent>
                  <Typography variant="subtitle2" color="text.secondary">Business</Typography>
                  <Typography variant="body1" fontWeight="bold">{bizName}</Typography>
                  <Box sx={{ display: 'flex', gap: 2, mt: 1, flexWrap: 'wrap' }}>
                    <Typography variant="body2">Plan: <strong>{selectedPlan?.name || bizPlan}</strong></Typography>
                    <Typography variant="body2">Timezone: <strong>{bizTimezone}</strong></Typography>
                  </Box>
                  {ownerEmail && (
                    <Typography variant="body2" sx={{ mt: 1 }}>Owner: <strong>{ownerName ? `${ownerName} (${ownerEmail})` : ownerEmail}</strong></Typography>
                  )}
                </CardContent>
              </Card>

              <Typography variant="subtitle2" gutterBottom>Features Enabled</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mb: 3 }}>
                {ALL_FEATURE_KEYS.map((f) => {
                  const enabled = featureFlags[f.key];
                  let statusLabel = 'Ready';
                  let statusColor: 'success' | 'warning' | 'default' = 'success';
                  if (['email', 'calendar', 'accounting'].includes(f.key) && enabled) {
                    statusLabel = 'Pending owner OAuth';
                    statusColor = 'warning';
                  }
                  if (f.key === 'receptionist' && enabled) {
                    statusLabel = recPhone ? `Configured (${recVoice}, ${recPhone})` : 'Configured (no phone yet)';
                  }
                  return (
                    <Box key={f.key} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.5 }}>
                      {enabled ? (
                        <CheckCircleIcon fontSize="small" color="success" />
                      ) : (
                        <Typography color="text.disabled" sx={{ width: 20, textAlign: 'center' }}>—</Typography>
                      )}
                      <Typography variant="body2" sx={!enabled ? { color: 'text.disabled', textDecoration: 'line-through' } : undefined}>
                        {f.label}
                      </Typography>
                      {enabled && <Chip label={statusLabel} size="small" color={statusColor} variant="outlined" />}
                    </Box>
                  );
                })}
              </Box>

              <Divider sx={{ my: 2 }} />

              <Typography variant="subtitle2" gutterBottom>Onboarding Checklist</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mb: 3 }}>
                {checklist.map((item) => (
                  <Box key={item.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.5 }}>
                    {item.is_completed ? (
                      <CheckCircleIcon fontSize="small" color="success" />
                    ) : (
                      <Typography color="text.disabled" sx={{ width: 20, textAlign: 'center' }}>○</Typography>
                    )}
                    <Typography variant="body2">{item.label}</Typography>
                    {item.notes && (
                      <Typography variant="caption" color="text.secondary">({item.notes})</Typography>
                    )}
                  </Box>
                ))}
              </Box>

              <Divider sx={{ my: 2 }} />

              <FormControlLabel
                control={<Checkbox checked={activateNow} onChange={(e) => setActivateNow(e.target.checked)} />}
                label={
                  <Box>
                    <Typography variant="body2">Activate business now</Typography>
                    <Typography variant="caption" color="text.secondary">Sets business to active and enables configured integrations</Typography>
                  </Box>
                }
                sx={{ mb: 1 }}
              />
              <FormControlLabel
                control={<Checkbox checked={sendWelcome} onChange={(e) => setSendWelcome(e.target.checked)} />}
                label="Send welcome email to business owner"
                sx={{ mb: 2, display: 'block' }}
              />
              <TextField
                label="Admin notes (optional)"
                fullWidth
                multiline
                rows={2}
                value={adminNotes}
                onChange={(e) => setAdminNotes(e.target.value)}
              />
            </Box>
          )}
        </Paper>

        {/* Navigation buttons */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Button
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={handleBack}
            disabled={currentStepIdx === 0 || saving}
          >
            Back
          </Button>

          <Box sx={{ display: 'flex', gap: 1 }}>
            {['email_setup', 'calendar_setup', 'accounting_setup'].includes(stepName) && (
              <Button variant="text" onClick={handleSkipStep} disabled={saving}>
                Skip this step
              </Button>
            )}
            <Button
              variant="contained"
              onClick={handleNext}
              disabled={!canProceed || saving}
            >
              {saving ? (
                <CircularProgress size={20} color="inherit" />
              ) : stepName === 'review_activate' ? (
                'Complete Onboarding'
              ) : (
                'Next Step'
              )}
            </Button>
          </Box>
        </Box>
      </Container>
    </Box>
  );
}
