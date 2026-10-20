# 036 — STAGING REHEARSAL RECORD

**Migration:** `backend/migrations/036_chase_replies.sql`
**Target rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`)
**Date:** 19 Oct 2026, by Claude Code
**Prod (`oxblcmwhuwtobdhsfgyi`) was not touched.** The script
(`scripts/rehearse-036-staging.py`) refuses any URL that does not contain the
staging ref or that contains the prod ref. It reads only `STAGING_DB_URL`, and
it never prints it.

## Finding on the first attempt, and the change it caused

The first draft gave `email_message_id` a foreign key to `email_messages(id)`.
On staging, SECTION 1 failed with:

> `there is no unique constraint matching given keys for referenced table "email_messages"`

Because the section is one transaction, nothing changed: a re-check showed
`chase_replies` absent. Staging's `email_messages` and `email_accounts` have
**no primary key, unique constraint or index at all**, while `invoices` and
`aria_actions` do. The repository's migration 007 defines primary keys on
both tables, so staging has drifted from it. Production's constraints on
these tables were never captured, by BH-001 or by the schema dump.

So 036 no longer has that foreign key. `email_message_id` is a plain uuid.
It wasn't needed:
- every read and write is scoped by `business_id`;
- a deleted email must not take its reply, and the pause, with it.

The local Postgres replay and its test (`test_chase_replies_rls.py`) were
updated to match. **This is reported to Codex for 037**, which adds keys on
these tables, and recorded for the staging-drift backlog.

## What was rehearsed (second attempt)

1. **Before-state:** the table is absent.
2. **SECTION 1 is applied.** I checked the columns, RLS flags, policy, grants, constraints, indexes and row count.
3. **The CHECKs and grants actually refuse what they should.** Each case ran inside a rolled-back transaction:
   - an unknown category is refused;
   - an unknown status is refused;
   - an `invoice_ids` that isn't a list is refused;
   - `authenticated` cannot INSERT or UPDATE;
   - a valid row inserts.
4. **Idempotency:** SECTION 1 applied again leaves the snapshot unchanged.
5. **ROLLBACK 1** is run, and the table is gone (the same as the before-state).
6. **SECTION 1 is re-applied and left applied**, so staging models production after 036.

## Result, verbatim from the run

```
- before: chase_replies exists: False
- SECTION 1 applied: ok
- columns (12 expected): 12: [('business_id', 'uuid', 'NO'), ('category', 'text', 'NO'), ('created_at', 'timestamp with time zone', 'NO'), ('customer_email', 'text', 'NO'), ('email_message_id', 'uuid', 'YES'), ('id', 'uuid', 'NO'), ('invoice_ids', 'jsonb', 'NO'), ('resolved_at', 'timestamp with time zone', 'YES'), ('resolved_by', 'uuid', 'YES'), ('status', 'text', 'NO'), ('summary', 'text', 'YES'), ('updated_at', 'timestamp with time zone', 'NO')]
- RLS (enabled, forced): [(True, False)]
- policies: [('chase_replies_member_read', 'SELECT', 'PERMISSIVE', '{authenticated}', True, False)]
- grants: [('authenticated', 'SELECT'), ('service_role', 'DELETE'), ('service_role', 'INSERT'), ('service_role', 'REFERENCES'), ('service_role', 'SELECT'), ('service_role', 'TRIGGER'), ('service_role', 'TRUNCATE'), ('service_role', 'UPDATE')]
- anon has nothing: True
- authenticated has SELECT only: True
- constraints: ['chase_replies_business_id_fkey', 'chase_replies_category_chk', 'chase_replies_invoice_ids_chk', 'chase_replies_pkey', 'chase_replies_status_chk']
- indexes: ['chase_replies_biz_message_uq', 'chase_replies_pkey', 'idx_chase_replies_biz_status']
- rows (0 expected): 0
- CHECK category rejects refund_them: failed as required (23514 chase_replies_category_chk)
- CHECK status rejects deleted: failed as required (23514 chase_replies_status_chk)
- CHECK invoice_ids must be a list: failed as required (23514 chase_replies_invoice_ids_chk)
- authenticated role cannot INSERT: failed as required (42501 permission denied for table chase_replies)
- authenticated role cannot UPDATE: failed as required (42501 permission denied for table chase_replies)
- a valid row inserts (rolled back): True
- SECTION 1 applied again (idempotent), snapshot unchanged: True
- ROLLBACK 1 run; table gone (== before): True
- SECTION 1 re-applied and LEFT APPLIED (staging models prod-after-036): True
```

## Also run

- **Local Supabase Postgres replay** (`scripts/rls-local.sh up`, with 034–036): `test_chase_replies_rls.py` and `test_tenant_isolation_rls_path.py` gave **49 passed**, and the reviewed policy count is 88.
- **The AUTO-2 code's Postgres paths against that replay:** jsonb `->>`, the `ON CONFLICT … RETURNING` insert, the `FOR UPDATE` resolve and the expanding `IN` lists. Each worked end to end:
  - the reply was found from `Harper <pay@harper.example>`;
  - it was linked to its invoice by number;
  - a second scan found nothing new;
  - Stop blocked exactly that invoice.
