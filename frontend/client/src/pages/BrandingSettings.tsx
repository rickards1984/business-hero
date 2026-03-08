import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  Button,
  Alert,
  CircularProgress,
  Container,
  IconButton,
  TextField,
  Chip,
} from '@mui/material';
import { ArrowBack, CloudUpload, Delete, CheckCircle, Palette } from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, resolveLogoSrc, type Business } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';
import { useQueryClient } from '@tanstack/react-query';

const BRAND_COLOUR_PRESETS = [
  { id: 'blue', label: 'Blue', value: '#3B82F6', hover: '#2563EB' },
  { id: 'indigo', label: 'Indigo', value: '#6366F1', hover: '#4F46E5' },
  { id: 'purple', label: 'Purple', value: '#8B5CF6', hover: '#7C3AED' },
  { id: 'teal', label: 'Teal', value: '#14B8A6', hover: '#0D9488' },
  { id: 'emerald', label: 'Green', value: '#10B981', hover: '#059669' },
  { id: 'amber', label: 'Amber', value: '#F59E0B', hover: '#D97706' },
  { id: 'rose', label: 'Rose', value: '#F43F5E', hover: '#E11D48' },
  { id: 'slate', label: 'Slate', value: '#475569', hover: '#334155' },
] as const;

function hexToHSL(hex: string): { h: number; s: number; l: number } {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
    }
  }
  return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
}

export function applyBrandColor(hex: string | null | undefined) {
  if (!hex) return;
  const hsl = hexToHSL(hex);
  const root = document.documentElement;
  root.style.setProperty('--color-primary-500', hex);
  const darkerL = Math.max(hsl.l - 10, 10);
  root.style.setProperty('--color-primary-600', `hsl(${hsl.h}, ${hsl.s}%, ${darkerL}%)`);
  const lighterL = Math.min(hsl.l + 35, 96);
  root.style.setProperty('--color-primary-50', `hsl(${hsl.h}, ${hsl.s}%, ${lighterL}%)`);
  const lightL = Math.min(hsl.l + 25, 92);
  root.style.setProperty('--color-primary-100', `hsl(${hsl.h}, ${hsl.s}%, ${lightL}%)`);
  const midL = Math.min(hsl.l + 10, 80);
  root.style.setProperty('--color-primary-300', `hsl(${hsl.h}, ${hsl.s}%, ${midL}%)`);
  root.style.setProperty('--color-primary-400', `hsl(${hsl.h}, ${hsl.s}%, ${Math.max(hsl.l - 5, 15)}%)`);
  root.style.setProperty('--color-primary-700', `hsl(${hsl.h}, ${hsl.s}%, ${Math.max(hsl.l - 20, 10)}%)`);
}

export function resetBrandColor() {
  const root = document.documentElement;
  const props = ['--color-primary-50', '--color-primary-100', '--color-primary-300', '--color-primary-400', '--color-primary-500', '--color-primary-600', '--color-primary-700'];
  props.forEach(p => root.style.removeProperty(p));
}

export default function BrandingSettings() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const queryClient = useQueryClient();
  const [business, setBusiness] = useState<Business | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [selectedColor, setSelectedColor] = useState<string>('#3B82F6');
  const [customHex, setCustomHex] = useState('');
  const [savingColor, setSavingColor] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [user, authLoading, navigate]);

  useEffect(() => {
    if (user) {
      fetchBusiness();
    }
  }, [user]);

  const fetchBusiness = async () => {
    setLoading(true);
    setError('');

    try {
      // Get business membership
      const { data: memberRows, error: memberError } = await supabase
        .from('business_members')
        .select('business_id, role')
        .eq('user_id', user?.id);

      if (memberError) throw memberError;
      const memberData =
        memberRows?.find(row => row.role === 'owner') ??
        memberRows?.[0] ??
        null;
      if (!memberData) {
        const { data: adminData, error: adminError } = await supabase
          .from('platform_admins')
          .select('user_id')
          .eq('user_id', user?.id)
          .maybeSingle();
        if (adminError) throw adminError;
        if (adminData) {
          setError('No business assigned');
        } else {
          setError('No business assigned');
        }
        setBusiness(null);
        setLoading(false);
        return;
      }

      const { data: businessData, error: businessError } = await supabase
        .from('businesses')
        .select('*')
        .eq('id', memberData.business_id)
        .single();
      if (businessError) throw businessError;
      setBusiness(businessData);

      if (businessData.logo_url) {
        const resolvedUrl = resolveLogoSrc(businessData.logo_url);
        setPreviewUrl(resolvedUrl);
      }

      const savedColor = businessData.feature_flags?.brand_color;
      if (savedColor) {
        setSelectedColor(savedColor);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch business data');
    } finally {
      setLoading(false);
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !business) return;

    // Validate file type
    const validTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/svg+xml', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      setError('Invalid file type. Please upload PNG, JPEG, SVG, or WebP image.');
      return;
    }

    // Validate file size (5MB max)
    if (file.size > 5 * 1024 * 1024) {
      setError('File size must be less than 5MB.');
      return;
    }

    setUploading(true);
    setError('');
    setSuccess('');

    try {
      // Get file extension
      const ext = file.name.split('.').pop()?.toLowerCase() || 'png';
      const timestamp = Date.now();
      const logoPath = `${business.id}/logo_${timestamp}.${ext}`;

      // Upload to Supabase Storage
      const { data: uploadData, error: uploadError } = await supabase.storage
        .from('logos')
        .upload(logoPath, file, {
          cacheControl: '3600',
          upsert: false,
        });

      if (uploadError) throw uploadError;

      // Get public URL
      const { data: urlData } = supabase.storage.from('logos').getPublicUrl(logoPath);
      const publicUrl = urlData.publicUrl;

      // Update business logo_url via backend API
      const response = await apiRequest('PUT', `/v1/business/logo`, {
        logo_url: logoPath, // Store the path, not the full URL
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to update logo');
      }

      setSuccess('Logo uploaded successfully!');
      setPreviewUrl(publicUrl);
      
      // Update local business state
      setBusiness({ ...business, logo_url: logoPath });

      // Clear file input
      e.target.value = '';
    } catch (err: any) {
      setError(err.message || 'Failed to upload logo');
      console.error('Upload error:', err);
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteLogo = async () => {
    if (!business?.logo_url || !confirm('Are you sure you want to delete the logo?')) {
      return;
    }

    setUploading(true);
    setError('');
    setSuccess('');

    try {
      // Delete from storage
      const { error: deleteError } = await supabase.storage
        .from('logos')
        .remove([business.logo_url]);

      if (deleteError) throw deleteError;

      // Update business logo_url to null
      const response = await apiRequest('PUT', `/v1/business/logo`, {
        logo_url: null,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to remove logo');
      }

      setSuccess('Logo removed successfully!');
      setPreviewUrl(null);
      setBusiness({ ...business, logo_url: null });
    } catch (err: any) {
      setError(err.message || 'Failed to delete logo');
      console.error('Delete error:', err);
    } finally {
      setUploading(false);
    }
  };

  const handleColorSelect = useCallback((hex: string) => {
    setSelectedColor(hex);
    setCustomHex('');
    applyBrandColor(hex);
  }, []);

  const handleCustomHex = useCallback((value: string) => {
    setCustomHex(value);
    if (/^#[0-9A-Fa-f]{6}$/.test(value)) {
      setSelectedColor(value);
      applyBrandColor(value);
    }
  }, []);

  const handleSaveColor = async () => {
    setSavingColor(true);
    setError('');
    try {
      const resp = await apiRequest('PUT', '/v1/business/brand-color', { brand_color: selectedColor });
      if (!resp.ok) throw new Error('Failed to save brand colour');
      setSuccess('Brand colour saved!');
      queryClient.invalidateQueries({ queryKey: ['v1', 'me'] });
    } catch (err: any) {
      setError(err.message || 'Failed to save');
    } finally {
      setSavingColor(false);
    }
  };

  const handleResetColor = async () => {
    resetBrandColor();
    setSelectedColor('#3B82F6');
    setCustomHex('');
    setSavingColor(true);
    try {
      await apiRequest('PUT', '/v1/business/brand-color', { brand_color: null });
      setSuccess('Brand colour reset to default.');
      queryClient.invalidateQueries({ queryKey: ['v1', 'me'] });
    } catch { /* silent */ } finally {
      setSavingColor(false);
    }
  };

  if (loading || authLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ mb: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
        <IconButton onClick={() => navigate('/app')}>
          <ArrowBack />
        </IconButton>
        <Typography variant="h4" component="h1">
          Branding Settings
        </Typography>
      </Box>

      <Paper sx={{ p: 4 }}>
        <Typography variant="h6" gutterBottom>
          Business Logo
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Upload a logo for your business. Supported formats: PNG, JPEG, SVG, WebP (max 5MB)
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {success && (
          <Alert severity="success" sx={{ mb: 2 }}>
            {success}
          </Alert>
        )}

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'center' }}>
          {/* Logo Preview */}
          <Box
            sx={{
              width: 200,
              height: 200,
              border: '2px dashed',
              borderColor: 'grey.300',
              borderRadius: 2,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: 'grey.50',
              position: 'relative',
            }}
          >
            {previewUrl ? (
              <>
                <img
                  src={previewUrl}
                  alt="Business Logo"
                  style={{
                    maxWidth: '100%',
                    maxHeight: '100%',
                    objectFit: 'contain',
                  }}
                />
                {business?.logo_url && (
                  <IconButton
                    onClick={handleDeleteLogo}
                    disabled={uploading}
                    sx={{
                      position: 'absolute',
                      top: 8,
                      right: 8,
                      bgcolor: 'error.main',
                      color: 'white',
                      '&:hover': { bgcolor: 'error.dark' },
                    }}
                  >
                    <Delete />
                  </IconButton>
                )}
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">
                No logo uploaded
              </Typography>
            )}
          </Box>

          {/* Upload Button */}
          <Box>
            <input
              accept="image/png,image/jpeg,image/jpg,image/svg+xml,image/webp"
              style={{ display: 'none' }}
              id="logo-upload-input"
              type="file"
              onChange={handleFileSelect}
              disabled={uploading}
            />
            <label htmlFor="logo-upload-input">
              <Button
                variant="contained"
                component="span"
                startIcon={<CloudUpload />}
                disabled={uploading}
                sx={{ minWidth: 200 }}
              >
                {uploading ? <CircularProgress size={24} /> : 'Upload Logo'}
              </Button>
            </label>
          </Box>
        </Box>
      </Paper>

      {/* Brand Colour Section */}
      <Paper sx={{ p: 4, mt: 3, border: '1px solid var(--color-neutral-100)', borderRadius: '12px' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Palette sx={{ color: 'var(--color-primary-500)', fontSize: 22 }} />
          <Typography sx={{ fontSize: '1.125rem', fontWeight: 700 }}>
            Brand & Appearance
          </Typography>
        </Box>
        <Typography sx={{ fontSize: '0.8125rem', color: 'var(--color-neutral-500)', mb: 3 }}>
          Choose your brand colour. This will customise buttons, highlights, and accents throughout the app.
        </Typography>

        {/* Colour swatches */}
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 3, alignItems: 'center' }}>
          {BRAND_COLOUR_PRESETS.map(preset => (
            <Box key={preset.id} sx={{ textAlign: 'center' }}>
              <Box
                onClick={() => handleColorSelect(preset.value)}
                sx={{
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  bgcolor: preset.value,
                  cursor: 'pointer',
                  border: selectedColor === preset.value ? '3px solid var(--color-neutral-900)' : '3px solid transparent',
                  boxShadow: selectedColor === preset.value ? '0 0 0 2px white, 0 0 0 4px var(--color-neutral-900)' : 'var(--shadow-xs)',
                  transition: 'all 150ms ease',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  '&:hover': { transform: 'scale(1.1)', boxShadow: 'var(--shadow-sm)' },
                }}
              >
                {selectedColor === preset.value && <CheckCircle sx={{ color: 'white', fontSize: 20 }} />}
              </Box>
              <Typography sx={{ fontSize: '0.625rem', color: 'var(--color-neutral-500)', mt: 0.5 }}>
                {preset.label}
              </Typography>
            </Box>
          ))}

          {/* Custom hex */}
          <Box sx={{ ml: 1 }}>
            <TextField
              size="small"
              label="Custom"
              placeholder="#FF5733"
              value={customHex}
              onChange={e => handleCustomHex(e.target.value)}
              sx={{ width: 120, '& .MuiInputBase-root': { fontSize: '0.8125rem' } }}
            />
          </Box>
        </Box>

        {/* Preview */}
        <Box sx={{ mb: 3, p: 3, borderRadius: '10px', border: '1px solid var(--color-neutral-100)', bgcolor: 'var(--color-neutral-50)' }}>
          <Typography sx={{ fontSize: '0.6875rem', fontWeight: 600, color: 'var(--color-neutral-500)', textTransform: 'uppercase', letterSpacing: '0.05em', mb: 2 }}>
            Preview
          </Typography>
          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
            <Button
              variant="contained"
              size="small"
              sx={{ bgcolor: selectedColor, textTransform: 'none', '&:hover': { bgcolor: selectedColor, filter: 'brightness(0.9)' } }}
            >
              Primary Button
            </Button>
            <Chip
              label="Active Tab"
              size="small"
              sx={{ bgcolor: selectedColor, color: 'white', fontWeight: 600 }}
            />
            <Chip
              label="Badge"
              size="small"
              variant="outlined"
              sx={{ borderColor: selectedColor, color: selectedColor }}
            />
            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: selectedColor }} />
            <Typography sx={{ fontSize: '0.8125rem', fontWeight: 600, color: selectedColor }}>Active link</Typography>
          </Box>
        </Box>

        <Box sx={{ display: 'flex', gap: 2 }}>
          <Button
            variant="contained"
            onClick={handleSaveColor}
            disabled={savingColor}
            sx={{
              textTransform: 'none',
              fontWeight: 600,
              px: 4,
              bgcolor: 'var(--color-primary-500)',
              '&:hover': { bgcolor: 'var(--color-primary-600)' },
            }}
          >
            {savingColor ? <CircularProgress size={20} color="inherit" /> : 'Save'}
          </Button>
          <Button
            variant="outlined"
            onClick={handleResetColor}
            disabled={savingColor}
            sx={{ textTransform: 'none', fontWeight: 500, borderColor: 'var(--color-neutral-300)', color: 'var(--color-neutral-600)' }}
          >
            Reset to Blue
          </Button>
        </Box>
      </Paper>
    </Container>
  );
}

