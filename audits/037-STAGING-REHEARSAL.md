# 037 — STAGING REHEARSAL RECORD

**Migration:** `backend/migrations/037_outreach_core.sql` (OUT-3)
**Target rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`)
**Date:** 20 Oct 2026, by Claude Code
**Prod (`oxblcmwhuwtobdhsfgyi`) was not touched.** `scripts/rehearse-037-staging.py` refuses any URL that isn't staging, and it never prints the URL. It also refuses to start unless staging is free of 037 objects, so every run begins from the true before-state.

## How it was run, the way Mike will run it

1. **Seed:** synthetic legacy rows from the runbook's STEP 2 fixture: three chase actions (proposed; executing with no approver; done and owner-approved), an outbox row and a settings sentinel. Their complete JSON was captured.
2. **Section 1:** six statements, each executed separately (concurrent indexes, autocommit).
3. **Section 2:** one transaction, the exact text of `audits/037-STEP-3-section2.sql`; the script asserts the file matches.
4. **Checks**, then Section 3 (the audit) and Section 4 (the default index; no `BLOCKS` row on staging).
5. **Re-paste** Sections 1–2. **Roll back** using the runbook's STEP 9 blocks. **Re-apply**, and leave applied.
6. **Remove** the synthetic rows.

## Fixes found by rehearsing

- **The runbook's fixture** omitted `business_settings.created_at` and `updated_at`, which are NOT NULL with no default in production's schema (`audits/live-schema-public.txt`). It failed as one transaction, with nothing written, and the fixture was corrected.
- **The Section 3 gate was narrowed** (Claude's review). It now blocks Section 4 only for a business with two or more default mailboxes, the only case that makes the at-most-one index fail. A business with mailboxes but no default is reported as `info`. Businesses with no mailbox aren't listed.
- **Two script bugs, both mine, both in the harness:** a statement splitter that picked up a comment, and a runbook-section lookup confused by the new plain-language STEP 2. Each run that hit them was discarded. The script now locates sections exactly, asserts the fixture seeded five rows, and refuses a non-clean start. Staging was rolled back with the runbook's own rollback before the authoritative run below.

## Result of the authoritative run, verbatim

```
- before: {'outreach_tables': 0, 'policies': 88, 'out3_constraints': 0, 'out3_indexes': 0, 'type_check': "CHECK ((action_type = ANY (ARRAY['send_email'::text, 'send_invoice_chase'::text, 'create_calendar_event'::text, 'create_task'::text])))", 'functions': 0}
- fixture: legacy rows captured: 5
- first apply: Section 1 (6 statements, one by one) and Section 2 applied: ok
- after: {'outreach_tables': 17, 'policies': 94, 'out3_constraints': 6, 'out3_indexes': 6, 'type_check': "CHECK ((action_type = ANY (ARRAY['send_email'::text, 'send_invoice_chase'::text, 'create_calendar_event'::text, 'create_task'::text, 'send_outreach'::text, 'reply_outreach'::text])))", 'functions': 2}
- 17 outreach tables: True
- RLS on all 17: True
- anon has nothing on outreach tables: True
- authenticated: SELECT only, on 6 tables: (6, {'SELECT'})
- action types now include outreach: True
- legacy rows unchanged by 037: True
- Section 3 audit (rows, BLOCKS rows): (0, 0)
- Section 4 default index: [(True,)]
- re-paste: Section 1 (6 statements, one by one) and Section 2 applied: ok
- re-paste leaves the snapshot unchanged: True
- rollback returns the exact before-state: True
- legacy rows unchanged by the rollback: True
- re-apply: Section 1 (6 statements, one by one) and Section 2 applied: ok
- re-applied and LEFT APPLIED (staging models prod-after-037): True
- legacy rows unchanged after re-apply: True
- synthetic rows removed: True
```

The policy count goes from 88 to **94**: 036's and 035's policies plus the six from 037. In production that's STEP 0's number + 6.

## Also checked

- Mike's STEP 0 and STEP 4 queries, run on staging with 037 applied, return exactly the runbook's EXPECT values: 17 / 17 / 0 / 6 / `SELECT` / true.
- On the local Supabase replay, the OUT-3 suites pass, with 233 passed (Stage B review).
