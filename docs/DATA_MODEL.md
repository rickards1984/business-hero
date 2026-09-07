# Data model — STUB

**Status: stub.** The authoritative data model is the live schema, not a
document.

| Question | Source |
|---|---|
| Every live column, 59 tables, 816 columns | `audits/live-schema-public.txt` |
| How to regenerate it | `scripts/dump-live-schema.sql`, runbook STEP 24b |
| What guards it against drift | `backend/tests/test_schema_conformance.py` |
| ORM models (partial — not every table has one) | `backend/models.py` |
| Money-path schema and why | `audits/MONEY-ENGINE-BATCH1-SPEC-v2.md` |
| Entitlement schema and why | `audits/ENTITLEMENT-SPEC.md` |

**Two warnings that belong on any page describing this data model:**

1. Migration files are not evidence of live state. Verify against the dump or
   the database.
2. The dump is **columns only**. It carries no RLS, policy, grant or index
   information — see `docs/PERMISSIONS_AND_TENANCY.md`.

**Known modelling debt:** per-line tax columns are `NOT NULL DEFAULT 0`, so
"no rate recorded" and "zero-rated" are indistinguishable (blocks mixed VAT);
`paid_amount` and `amount_paid` duplicate each other.
