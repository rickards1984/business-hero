# 034 — STAGING REHEARSAL RECORD

**Migration:** `backend/migrations/034_invoice_customer_address.sql`
**Target rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`)
**Date:** 9 Oct 2026, by Claude Code
**Prod (`oxblcmwhuwtobdhsfgyi`) was not touched.** The script
(`scripts/rehearse-034-staging.py`) refuses any URL that does not contain the
staging ref or that contains the prod ref, reads only `STAGING_DB_URL` from
`.env.staging`, and never prints it.

## What was rehearsed

Before-snapshot of `public.invoices` (columns, table grants, column grants,
policies, RLS flags, row count) → SECTION 1 → VERIFY → idempotency
(SECTION 1 again) → ROLLBACK 1 → compared against the before-snapshot →
SECTION 1 re-applied and **left applied**, so staging models prod-after-034.

## Result, verbatim from the run

```
- before: invoices columns: 30
- before: has customer_address/supply_date: []
- before: RLS (enabled, forced): [(True, False)]
- before: policies: ['business_members_delete_invoices', 'business_members_insert_invoices', 'business_members_read_invoices', 'business_members_update_invoices', 'platform_admins_full_access_invoices']
- before: table grants to anon/authenticated: [anon and authenticated each hold DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE]
- before: column-level grant pattern (grantee, privilege) count: 240
- SECTION 1 applied: ok
- VERIFY after section 1: [('customer_address', 'text', 'YES'), ('supply_date', 'date', 'YES')]
- new columns: [('customer_address', 'text', 'YES', None), ('supply_date', 'date', 'YES', None)]
- policies unchanged: True
- RLS unchanged: True
- row count unchanged: True
- client column privileges on new columns (inherited from table grants): anon and authenticated each INSERT, REFERENCES, SELECT, UPDATE on both columns
- SECTION 1 applied again (idempotent): ok
- VERIFY after re-apply: [('customer_address', 'text', 'YES'), ('supply_date', 'date', 'YES')]
- ROLLBACK 1 run: ok
- after rollback == before-snapshot (columns, grants, column grants, policies, RLS, rows): True
- SECTION 1 re-applied and LEFT APPLIED (staging now models prod-after-034): ok
- final VERIFY: [('customer_address', 'text', 'YES'), ('supply_date', 'date', 'YES')]
```

## What the rehearsal established

1. **`invoices` uses table-level grants**, so the new columns inherit the
   client roles' privileges automatically — no column naming needed. Row
   access stays governed by the five existing membership policies, unchanged.
2. **Those table grants include `TRUNCATE` and `DELETE` for `anon`** on
   staging. That is BH-001 §6's known finding (TRUNCATE to anon on 46 tables),
   not something 034 introduces or changes; it stays in the security queue.
3. **The rollback is exact**: every captured property returned to the
   before-snapshot.

## Not established

Staging is not proven structurally equal to production for `invoices`
beyond what was captured (AGENTS.md §3.9). For an additive nullable column
this does not affect the result; the runbook's STEP 0 captures production's
own before-state.
