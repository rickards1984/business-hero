# OUT-28a fix (044) — Codex code review 4 (verbatim)

Commit 925802e. Model gpt-6-astra, read-only sandbox, 20 Nov 2026.

---

APPROVE

1. **Resolved — review 3 finding 2 (P3).** `backend/migrations/044_outreach_wording_moves.sql:96` now accepts only `O`/`A`. The failure scenario—a replica-only trigger passing verification but not binding ordinary writes—is rejected. `audits/044-PROD-RUNBOOK.md:59` reports `R`/`D` as `NOT FIRING`, triggering STOP. This matches [PostgreSQL’s firing modes](https://www.postgresql.org/docs/17/catalog-pg-trigger.html).

2. **Resolved — review 3 finding 3 (P3).** `backend/migrations/044_outreach_wording_moves.sql:97` requires ROW=1, BEFORE=2, INSERT=4 and UPDATE=16, matching [PostgreSQL’s definitions](https://raw.githubusercontent.com/postgres/postgres/REL_17_STABLE/src/include/catalog/pg_trigger.h). The failure scenario—an AFTER or statement-level trigger passing while failing to bind the stored row—is now rejected. `audits/044-PROD-RUNBOOK.md:60` applies the same checks.

3. **Optional hardening only — P3.** `audits/044-PROD-RUNBOOK.md:59` labels both accepted modes `enabled`, rather than displaying their actual values. An unintended switch from `O` to `A` would therefore be invisible in this output, although both satisfy ordinary-write requirements. Displaying the accepted mode would improve diagnostics; this does not block approval.

No new blocking defects or regressions found in the latest diff. Read-only review; no files modified, tests or `check.sh` run.