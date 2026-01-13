-- Migration: RLS policies for logos storage bucket
-- Date: 2024-12-XX
-- Description: Row Level Security for logo uploads and access

-- Note: These policies are for Supabase Storage, not regular tables
-- They use storage.objects and storage.buckets

-- Policy: Allow business members to upload logos for their business
-- Path format: {business_id}/logo.{ext}
CREATE POLICY "business_members_upload_logo"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
    bucket_id = 'logos' AND
    (
        -- Check if user is a member of the business (business_id is in the path)
        EXISTS (
            SELECT 1 FROM business_members bm
            WHERE bm.user_id = auth.uid()
              AND bm.is_active = true
              AND (storage.objects.name)::text LIKE (bm.business_id::text || '/%')
        )
        OR
        -- Platform admins can upload to any business
        EXISTS (
            SELECT 1 FROM platform_admins pa
            WHERE pa.user_id = auth.uid()
        )
    )
);

-- Policy: Allow business members to read logos for their business
CREATE POLICY "business_members_read_logo"
ON storage.objects
FOR SELECT
TO authenticated
USING (
    bucket_id = 'logos' AND
    (
        -- Check if user is a member of the business
        EXISTS (
            SELECT 1 FROM business_members bm
            WHERE bm.user_id = auth.uid()
              AND bm.is_active = true
              AND (storage.objects.name)::text LIKE (bm.business_id::text || '/%')
        )
        OR
        -- Platform admins can read any logo
        EXISTS (
            SELECT 1 FROM platform_admins pa
            WHERE pa.user_id = auth.uid()
        )
    )
);

-- Policy: Allow business members to update/delete logos for their business
CREATE POLICY "business_members_update_logo"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
    bucket_id = 'logos' AND
    (
        EXISTS (
            SELECT 1 FROM business_members bm
            WHERE bm.user_id = auth.uid()
              AND bm.is_active = true
              AND (storage.objects.name)::text LIKE (bm.business_id::text || '/%')
        )
        OR
        EXISTS (
            SELECT 1 FROM platform_admins pa
            WHERE pa.user_id = auth.uid()
        )
    )
)
WITH CHECK (
    bucket_id = 'logos' AND
    (
        EXISTS (
            SELECT 1 FROM business_members bm
            WHERE bm.user_id = auth.uid()
              AND bm.is_active = true
              AND (storage.objects.name)::text LIKE (bm.business_id::text || '/%')
        )
        OR
        EXISTS (
            SELECT 1 FROM platform_admins pa
            WHERE pa.user_id = auth.uid()
        )
    )
);

CREATE POLICY "business_members_delete_logo"
ON storage.objects
FOR DELETE
TO authenticated
USING (
    bucket_id = 'logos' AND
    (
        EXISTS (
            SELECT 1 FROM business_members bm
            WHERE bm.user_id = auth.uid()
              AND bm.is_active = true
              AND (storage.objects.name)::text LIKE (bm.business_id::text || '/%')
        )
        OR
        EXISTS (
            SELECT 1 FROM platform_admins pa
            WHERE pa.user_id = auth.uid()
        )
    )
);


