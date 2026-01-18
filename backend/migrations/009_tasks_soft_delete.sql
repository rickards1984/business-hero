-- Migration: Add soft delete support for tasks
-- Date: 2026-01-17

ALTER TABLE IF EXISTS public.tasks
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_business_deleted_at
    ON public.tasks (business_id, deleted_at);
