import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  Button,
  Alert,
  CircularProgress,
  Container,
  Avatar,
  IconButton,
} from '@mui/material';
import { ArrowBack, CloudUpload, Delete } from '@mui/icons-material';
import { useAuth } from '@/contexts/AuthContext';
import { supabase, resolveLogoSrc, type Business } from '@/lib/supabase';
import { apiRequest } from '@/lib/queryClient';
import { config } from '@/config/env';

export default function BrandingSettings() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [business, setBusiness] = useState<Business | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

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
      const { data: memberData, error: memberError } = await supabase
        .from('business_members')
        .select('*, businesses(*)')
        .eq('user_id', user?.id)
        .single();

      if (memberError) throw memberError;

      const businessData = memberData.businesses as Business;
      setBusiness(businessData);

      // Load preview if logo exists
      if (businessData.logo_url) {
        const resolvedUrl = resolveLogoSrc(businessData.logo_url);
        setPreviewUrl(resolvedUrl);
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
    </Container>
  );
}

