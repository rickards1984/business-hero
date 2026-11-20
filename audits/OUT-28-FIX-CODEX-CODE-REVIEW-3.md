# OUT-28a fix (044) — Codex code review 3 (verbatim)

Commit 9b8d52a. Model gpt-6-astra, read-only sandbox, 20 Nov 2026.

---

REQUEST CHANGES

1. **Resolved — review 2 finding 2 (previous P2).** [044_outreach_wording_moves.sql:69](/Users/michaelrickards/dev/bh2-OUT28fix/backend/migrations/044_outreach_wording_moves.sql:69) now checks ordered `conkey` **and** `confkey` for both retained keys. The runbook exposes referenced columns. The reported failure scenario—correct source columns referencing incorrectly ordered target columns—is now rejected.

2. **Partially resolved — review 2 finding 5 (P3).** [044_outreach_wording_moves.sql:94](/Users/michaelrickards/dev/bh2-OUT28fix/backend/migrations/044_outreach_wording_moves.sql:94) accepts `tgenabled = 'R'`; [044-PROD-RUNBOOK.md:59](/Users/michaelrickards/dev/bh2-OUT28fix/audits/044-PROD-RUNBOOK.md:59) labels it “enabled.” **Failure scenario:** a replica-only trigger passes migration and verification but never binds versions during ordinary application writes. Require `tgenabled IN ('O', 'A')` and expose the actual mode. [PostgreSQL documents these firing modes](https://www.postgresql.org/docs/17/catalog-pg-trigger.html). The attachment/function checks are correct, and **INSERT=4, UPDATE=16 are correct** per [PostgreSQL’s definitions](https://github.com/postgres/postgres/blob/master/src/include/catalog/pg_trigger.h).

3. **New guard gap — P3.** [044_outreach_wording_moves.sql:95](/Users/michaelrickards/dev/bh2-OUT28fix/backend/migrations/044_outreach_wording_moves.sql:95) checks events but not `BEFORE ROW`. **Failure scenario:** a drifted `AFTER INSERT OR UPDATE` trigger passes, yet assignments to `NEW.sequence_version` cannot change the stored row. Check the BEFORE (`2`) and ROW (`1`) bits too.

No other new defects or regressions found in the diff. Read-only review; no files changed, tests or `check.sh` run.