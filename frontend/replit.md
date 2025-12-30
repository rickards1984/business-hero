# Business Hero Frontend

A React-based business management dashboard using Supabase for authentication and data.

## Overview

This application provides:
- Login authentication via Supabase
- Admin dashboard for platform administrators to manage businesses and members
- Business dashboard for users to view their business profile, tasks, and calls

## Architecture

### Frontend-Only with Supabase Backend
- **Frontend**: React + TypeScript + Vite
- **UI**: Material UI (MUI)
- **Database/Auth**: Supabase (with Row Level Security)
- **Routing**: React Router DOM

The application connects directly to Supabase from the frontend using the anonymous key. All data access is secured via Supabase Row Level Security (RLS) policies.

## Key Files

- `client/src/App.tsx` - Main app with routing setup
- `client/src/lib/supabase.ts` - Supabase client and TypeScript interfaces
- `client/src/contexts/AuthContext.tsx` - Authentication context provider
- `client/src/pages/Login.tsx` - Login page
- `client/src/pages/AdminDashboard.tsx` - Admin dashboard
- `client/src/pages/BusinessDashboard.tsx` - Business user dashboard

## Environment Variables

Required (stored as Replit secrets):
- `VITE_SUPABASE_URL` - Supabase project URL
- `VITE_SUPABASE_ANON_KEY` - Supabase anonymous key

## Database Tables (in Supabase)

- `platform_admins` - Users with admin privileges
- `businesses` - Business entities
- `business_members` - User-business assignments with roles
- `tasks` - Business tasks
- `calls` - Call records

## Running the App

```bash
npm run dev
```

Runs on port 5000.

## User Flow

1. User logs in at `/login` (with Sign In / Sign Up tabs)
2. New users must be invited first (admin adds their email to a business)
3. User signs up → receives confirmation email → clicks link → `/confirm` page
4. After login, system checks `platform_admins` table
5. If user is admin → redirect to `/admin`
6. If not admin → redirect to `/app` (business dashboard)
7. On first login, user is automatically linked to their invited business

## Pre-Publish Checklist

- [ ] Add permanent URLs to Supabase Authentication → URL Configuration:
  - Site URL: `https://your-app.vercel.app` (or `.replit.app`)
  - Redirect URLs: `https://your-app.vercel.app/confirm`
- [ ] Verify RLS policies are correctly configured
- [ ] Test full signup/login flow with production URL
