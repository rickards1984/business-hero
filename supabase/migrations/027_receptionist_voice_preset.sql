-- ============================================================================
-- Migration 027: add voice_preset_id to receptionist_configs
--
-- Migrates from the legacy single-string `voice` column to the new
-- accent-aware preset system (see backend/services/voice_presets.py).
--
-- The legacy `voice` column is INTENTIONALLY KEPT for backwards compatibility
-- and as a fallback path in receptionist_call_handler.py — we may drop it in
-- a follow-up migration once we are confident no client relies on it.
-- ============================================================================

ALTER TABLE receptionist_configs
    ADD COLUMN IF NOT EXISTS voice_preset_id TEXT;

-- ----------------------------------------------------------------------------
-- Backfill — every existing voice maps to its British-Standard variant by
-- default. UK businesses get an immediate accent upgrade with no config
-- change required. Anyone who prefers a different accent can switch in
-- Settings after the deploy.
-- ----------------------------------------------------------------------------

UPDATE receptionist_configs
SET voice_preset_id = 'shimmer_british'
WHERE voice_preset_id IS NULL AND voice = 'shimmer';

UPDATE receptionist_configs
SET voice_preset_id = 'echo_british'
WHERE voice_preset_id IS NULL AND voice = 'echo';

UPDATE receptionist_configs
SET voice_preset_id = 'alloy_british'
WHERE voice_preset_id IS NULL AND voice = 'alloy';

UPDATE receptionist_configs
SET voice_preset_id = 'ash_british'
WHERE voice_preset_id IS NULL AND voice = 'ash';

UPDATE receptionist_configs
SET voice_preset_id = 'ballad_british'
WHERE voice_preset_id IS NULL AND voice = 'ballad';

UPDATE receptionist_configs
SET voice_preset_id = 'coral_british'
WHERE voice_preset_id IS NULL AND voice = 'coral';

UPDATE receptionist_configs
SET voice_preset_id = 'sage_british'
WHERE voice_preset_id IS NULL AND voice = 'sage';

UPDATE receptionist_configs
SET voice_preset_id = 'verse_british'
WHERE voice_preset_id IS NULL AND voice = 'verse';

-- Any remaining (unknown voice value, NULL voice, etc.) default to the
-- product-wide default. Code-side resolver also guards against null/unknown.
UPDATE receptionist_configs
SET voice_preset_id = 'shimmer_british'
WHERE voice_preset_id IS NULL;

-- Make voice_preset_id the canonical going-forward setting, with a default
-- that matches the resolver default.
ALTER TABLE receptionist_configs
    ALTER COLUMN voice_preset_id SET DEFAULT 'shimmer_british';

CREATE INDEX IF NOT EXISTS idx_receptionist_configs_voice_preset
    ON receptionist_configs (voice_preset_id);
