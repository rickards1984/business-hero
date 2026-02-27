-- Add AI analysis columns to email_messages for categorisation and priority scoring
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS ai_category TEXT;
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS ai_priority INTEGER;
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS ai_summary TEXT;
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS ai_suggested_action TEXT;
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS ai_analyzed_at TIMESTAMPTZ;
