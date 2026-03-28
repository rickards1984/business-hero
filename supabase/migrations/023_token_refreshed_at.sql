-- Track when the OAuth token was last refreshed to prevent concurrent
-- refresh race conditions (single-use refresh tokens).
ALTER TABLE xero_connections
ADD COLUMN IF NOT EXISTS token_refreshed_at TIMESTAMPTZ;

ALTER TABLE accounting_connections
ADD COLUMN IF NOT EXISTS token_refreshed_at TIMESTAMPTZ;
