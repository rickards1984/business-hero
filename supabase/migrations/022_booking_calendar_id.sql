-- Add calendar_id column to booking_settings so businesses can choose
-- which Google Calendar the AI receptionist books into.
ALTER TABLE booking_settings
ADD COLUMN IF NOT EXISTS calendar_id TEXT DEFAULT 'primary';
