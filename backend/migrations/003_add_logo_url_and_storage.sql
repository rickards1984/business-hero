-- Migration: Add logo_url to businesses table and create logos storage bucket
-- Date: 2024-12-XX
-- Description: Support per-business logo branding

-- Add logo_url column to businesses table
ALTER TABLE businesses 
ADD COLUMN IF NOT EXISTS logo_url TEXT;

CREATE INDEX IF NOT EXISTS idx_businesses_logo_url ON businesses(logo_url) WHERE logo_url IS NOT NULL;

-- Create storage bucket for logos (run this in Supabase Dashboard SQL Editor)
-- Note: Storage buckets must be created via Supabase Storage API or Dashboard
-- This SQL will be executed via Supabase Storage API or manually in Dashboard

-- The bucket will be created with:
-- - Name: 'logos'
-- - Public: false (private bucket)
-- - File size limit: 5MB
-- - Allowed MIME types: image/png, image/jpeg, image/jpg, image/svg+xml, image/webp

-- RLS policies for storage bucket will be added in the next migration


