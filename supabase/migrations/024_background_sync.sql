-- Background sync infrastructure: Gmail History API tracking + financial summary cache

-- 1. Add historyId tracking for Gmail incremental sync
ALTER TABLE email_sync_state ADD COLUMN IF NOT EXISTS last_history_id TEXT;
ALTER TABLE email_sync_state ADD COLUMN IF NOT EXISTS last_background_sync_at TIMESTAMPTZ;

-- 2. Financial summary cache table
CREATE TABLE IF NOT EXISTS financial_summary_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id),
    provider TEXT NOT NULL DEFAULT 'xero',
    bank_summary JSONB,
    profit_and_loss JSONB,
    cash_flow JSONB,
    invoices_summary JSONB,
    cached_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start DATE,
    period_end DATE,
    UNIQUE(business_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_financial_summary_cache_business
ON financial_summary_cache(business_id, provider);
