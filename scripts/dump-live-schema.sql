-- Regenerate audits/live-schema-public.txt — the source of truth for
-- backend/tests/test_schema_conformance.py.
--
-- WHY THIS EXISTS: migration files are not evidence of live state (CLAUDE.md
-- "Do not regress" #4), and `create_all()` creates tables but NEVER columns.
-- So a hand-written `text()` query can name a column that has never existed
-- and nothing in the build will say so. This dump is what the guard compares
-- against. It is only as current as the last time it was run.
--
-- RUN IT: Supabase SQL editor, project oxblcmwhuwtobdhsfgyi (CONFIRM THE
-- PROJECT SELECTOR — two projects exist). Read-only; touches no data.
--
-- THEN: replace the `col` lines in audits/live-schema-public.txt with the
-- result, and set the header to `coverage: FULL`. Re-run ./check.sh.
--
-- The output format matches the existing audits/*-staging-before.txt
-- snapshots, so the same parser reads both.

SELECT 'col   '
       || table_name || '.' || column_name
       || ' ' || data_type
       || coalesce('(' || numeric_precision || ',' || numeric_scale || ')', '')
       || coalesce('(' || character_maximum_length || ')', '')
       || ' null=' || is_nullable
       || ' def=' || coalesce(column_default, '-') AS state
  FROM information_schema.columns
 WHERE table_schema = 'public'
   -- The 033 rollback table is scaffolding, not schema. Excluding it keeps a
   -- dump taken mid-migration identical to one taken after STEP 26.
   AND table_name NOT LIKE 'zz\_%'
 ORDER BY table_name, column_name;
