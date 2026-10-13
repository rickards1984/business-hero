# 035 — STAGING REHEARSAL RECORD

**Migration:** `backend/migrations/035_aria_actions.sql`
**Target rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`)
**Date:** 13 Oct 2026, by Claude Code
**Prod (`oxblcmwhuwtobdhsfgyi`) was not touched.** The script
(`scripts/rehearse-035-staging.py`) refuses any URL that does not contain the
staging ref or that contains the prod ref, reads only `STAGING_DB_URL` from
`.env.staging`, and never prints it.

## What was rehearsed

1. Before-state: the table is absent.
2. SECTION 1 is applied, then the result is checked:
   - columns, RLS flags, the policy and the grants;
   - constraints and indexes;
   - the row count.
3. The CHECKs and grants actually bite, each tested inside a rolled-back
   transaction:
   - an unknown `action_type` is refused;
   - an unknown `status` is refused;
   - the `authenticated` role cannot INSERT or UPDATE.
4. **The once-only claim:** the approve UPDATE returns one row and then none,
   and it returns none for an expired row.
5. Idempotency: SECTION 1 is applied again and the snapshot is unchanged.
6. ROLLBACK 1 is run, and the table is gone (the same as the before-state).
7. SECTION 1 is re-applied and **left applied**, so staging models
   prod-after-035.

## Result, verbatim from the run

```
- before: aria_actions exists: False
- SECTION 1 applied: ok
- columns (14 expected): 14: [('action_type', 'text', 'NO'), ('approved_at', 'timestamp with time zone', 'YES'), ('approved_by', 'uuid', 'YES'), ('business_id', 'uuid', 'NO'), ('created_at', 'timestamp with time zone', 'NO'), ('error', 'text', 'YES'), ('executed_at', 'timestamp with time zone', 'YES'), ('expires_at', 'timestamp with time zone', 'NO'), ('id', 'uuid', 'NO'), ('payload', 'jsonb', 'NO'), ('proposed_by', 'uuid', 'YES'), ('result', 'jsonb', 'YES'), ('status', 'text', 'NO'), ('updated_at', 'timestamp with time zone', 'NO')]
- RLS (enabled, forced): [(True, False)]
- policies: [('aria_actions_member_read', 'SELECT', 'PERMISSIVE', '{authenticated}', True, False)]
- grants: [('authenticated', 'SELECT'), ('service_role', 'DELETE'), ('service_role', 'INSERT'), ('service_role', 'REFERENCES'), ('service_role', 'SELECT'), ('service_role', 'TRIGGER'), ('service_role', 'TRUNCATE'), ('service_role', 'UPDATE')]
- anon has nothing: True
- authenticated has SELECT only: True
- constraints: ['aria_actions_business_id_fkey', 'aria_actions_pkey', 'aria_actions_status_chk', 'aria_actions_type_chk']
- indexes: ['aria_actions_pkey', 'idx_aria_actions_biz_status_created']
- rows (0 expected): 0
- CHECK action_type rejects delete_task: failed as required (23514 aria_actions_type_chk)
- CHECK status rejects 'sent': failed as required (23514 aria_actions_status_chk)
- authenticated role cannot INSERT: failed as required (42501 permission denied for table aria_actions)
- authenticated role cannot UPDATE: failed as required (42501 permission denied for table aria_actions)
- claim: first returns 1 row, second 0: (1, 0)
- claim on an expired row returns 0: 0
- SECTION 1 applied again (idempotent), snapshot unchanged: True
- ROLLBACK 1 run; table gone (== before): True
- SECTION 1 re-applied and LEFT APPLIED (staging models prod-after-035): True
```

Every property matched the migration's VERIFY expectations.
