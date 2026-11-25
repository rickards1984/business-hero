# 046 — Codex code review 1 (verbatim)

Model gpt-6-astra, read-only sandbox, 25 Nov 2026.

---

REQUEST CHANGES

1. **Medium — blocking: PostgreSQL tests are omitted from the harness’s default test command.** `scripts/rls-local.sh:308` selects `test_*rls*.py`, which excludes `test_inbox_reply_examples_pg.py`. Ordinary `check.sh` skips these tests unless `RLS_LOCAL_DATABASE_URL` is exported; running `rls-local.sh up` does not export it into the caller’s shell. **Failure scenario:** the harness and normal checks report green without exercising any 046 assertions. Include this suite in the harness command and record its executed result.

2. **High — blocking: the new database tests lack 045’s loopback-only guard.** `backend/tests/test_inbox_reply_examples_pg.py:7–13` accepts any database URL, whereas `test_ai_models_pg.py` rejects non-loopback hosts. **Failure scenario:** a mistakenly configured production URL causes tests to insert businesses and execute deletes against production. Transaction rollback does not make this read-only or authorised. Restore the guard before opening a connection.

3. **Medium — blocking: constraint tests can pass for unrelated database errors.** `backend/tests/test_inbox_reply_examples_pg.py:35–43` catches every exception, including fixture insertion failures, and treats it as successful rejection for invalid cases. **Failure scenario:** a connection failure during an invalid-case insert passes without proving its CHECK exists. Catch the expected integrity exception around only the target insert and assert the CHECK violation. Also cover `sent_body`, subject/excerpt boundaries, invalid FKs and email deletion; currently only business deletion is exercised.

4. **Medium — non-blocking for the empty migration; required before feature activation: retention and deletion promises are not implemented here.** `backend/migrations/046_inbox_reply_examples.sql:20` uses `ON DELETE SET NULL`; `audits/046-PROD-RUNBOOK.md:8` promises deletion controls and a 20-example cap. **Failure scenario:** deleting an email leaves its copied subject, excerpt and reply bodies available indefinitely if no newer examples replace them. Document this explicitly, define the retention/erasure behaviour, and make its implementation and tests a feature-release prerequisite. Business deletion correctly cascades.

5. **Low — non-blocking: the email FK does not enforce tenant agreement.** `backend/migrations/046_inbox_reply_examples.sql:18–20` independently validates the business and email IDs. **Failure scenario:** an elevated backend writer associates business A’s example with business B’s email; both FKs accept it. Require a tenant-scoped source lookup and a cross-business rejection test in ARIA-1b, or enforce the relationship structurally.

Otherwise, the fresh-install SQL is sound by inspection: transactional creation, local 5-second lock and 60-second statement timeouts, bounded text CHECKs, appropriate recent-example index, RLS with no policies, and explicit revocation from `PUBLIC`, `anon`, `authenticated` and `service_role`, matching 045. Identical reruns are safe, although `IF NOT EXISTS` does not validate schema drift.

The runbook’s **C + 10** is exact, and both census queries use the same `zz_%` exclusion as 045 and the snapshot convention. Rollback is clearly restricted to staging rehearsal unless separately instructed for production. The snapshot confirms UUID parent columns, but does not prove live PK/FK constraints.

Review was static and read-only; no tests or SQL were executed, and no files were changed.