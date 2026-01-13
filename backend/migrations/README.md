# Database Migrations

This directory contains SQL migrations for the Business Hero database.

## Migration Files

1. **001_create_business_settings_integrations.sql** - Creates the three new tables:
   - `business_settings` - 1 row per business for general settings
   - `integrations` - 1 row per business per integration type
   - `oauth_tokens` - Encrypted OAuth token storage (backend-only)

2. **002_create_rls_policies.sql** - Creates Row Level Security (RLS) policies:
   - Platform admins: Full access to all tables
   - Business members: Read/update access to their business's data only
   - OAuth tokens: Platform admins and service role only (no frontend access)

## Applying Migrations

### Option 1: Supabase Dashboard (Recommended)

1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor**
3. Copy and paste the contents of `001_create_business_settings_integrations.sql`
4. Click **Run** to execute
5. Repeat for `002_create_rls_policies.sql`

### Option 2: psql Command Line

```bash
# Connect to your Supabase database
psql "postgresql://postgres:[YOUR-PASSWORD]@[YOUR-PROJECT-REF].supabase.co:5432/postgres"

# Run migrations
\i backend/migrations/001_create_business_settings_integrations.sql
\i backend/migrations/002_create_rls_policies.sql
```

### Option 3: Supabase CLI

```bash
# If you have Supabase CLI installed
supabase db push
```

## Verification

After applying migrations, verify the tables exist:

```sql
-- Check tables exist
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name IN ('business_settings', 'integrations', 'oauth_tokens');

-- Check RLS is enabled
SELECT tablename, rowsecurity 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND tablename IN ('business_settings', 'integrations', 'oauth_tokens');

-- Check policies exist
SELECT schemaname, tablename, policyname 
FROM pg_policies 
WHERE tablename IN ('business_settings', 'integrations', 'oauth_tokens');
```

## RLS Policy Summary

### business_settings
- **Platform admins**: Full access (SELECT, INSERT, UPDATE, DELETE)
- **Business members**: SELECT and UPDATE for their business only

### integrations
- **Platform admins**: Full access (SELECT, INSERT, UPDATE, DELETE)
- **Business members**: SELECT, INSERT, UPDATE for their business only

### oauth_tokens
- **Platform admins**: Full access (SELECT, INSERT, UPDATE, DELETE)
- **Service role**: Full access (bypasses RLS)
- **Business members**: NO ACCESS (denied by policy)

## Notes

- The `oauth_tokens` table stores encrypted tokens and should NEVER be accessed directly from the frontend
- All tables use `ON DELETE CASCADE` - deleting a business will delete all related settings, integrations, and tokens
- The `updated_at` timestamp is automatically maintained by database triggers

## Storage Bucket Setup

### Creating the Logos Bucket

1. Go to Supabase Dashboard → Storage
2. Click "New bucket"
3. Name: `logos`
4. Public: **false** (private bucket)
5. File size limit: 5MB
6. Allowed MIME types: `image/png, image/jpeg, image/jpg, image/svg+xml, image/webp`

### Applying Storage RLS Policies

After creating the bucket, run `004_storage_rls_policies.sql` in the SQL Editor to apply RLS policies for logo uploads and access.

