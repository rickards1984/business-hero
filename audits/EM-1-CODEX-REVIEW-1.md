# EM-1 — Codex review 1 (verbatim)

Findings: none.

- Root cause is correct: all four runtime creators omit `sync_status`; the previous model supplied `None`, bypassing production’s database default. No runtime SQL or Supabase REST writes of this field, or dependencies on `None`, were found.
- `create_all()` now generates `sync_status NOT NULL` with a Python-side `"idle"` default, **not a server default**. Raw inserts omitting it would fail on newly generated tables, but no affected repository paths exist. SQLite fixtures define their own tables; SQLite’s existing JSONB incompatibility is unchanged.
- `email_account_id` is the only production NOT NULL field without a model default; all four creators supply it. IDs and timestamps have factories.
- The three focused tests passed with bytecode, pytest caching, and temporary-file capture disabled. Full `check.sh` was not run because it writes files.

VERDICT: APPROVE