# 046 — Codex code review 2 (verbatim)

Model gpt-6-astra, read-only sandbox, 25 Nov 2026.

---

REQUEST CHANGES

1. **Medium — blocking; finding 3 partially fixed.** `backend/tests/test_inbox_reply_examples_pg.py:48` now catches only `IntegrityError` around the target insert, but line 72 checks only the table name. An unrelated NOT NULL, FK or UNIQUE violation on that table still passes. Assert CHECK SQLSTATE `23514` and the expected constraint name for each case. The requested sent-body, subject/excerpt, invalid-FK and email-deletion coverage was added.

2. **Medium — non-blocking for the empty migration; finding 4 partially fixed.** `backend/migrations/046_inbox_reply_examples.sql:21` now cascades email deletion, with a regression test at `backend/tests/test_inbox_reply_examples_pg.py:94`. However, `audits/046-PROD-RUNBOOK.md:8` still promises owner deletion controls and a 20-example cap without explicitly making their implementation **and tests** prerequisites for feature activation. The “all made” statement at line 13 overstates closure.

3. **Medium — resolved, non-blocking; finding 1 fixed.** `scripts/rls-local.sh:309` includes both PostgreSQL suite patterns. `audits/046-PROD-RUNBOOK.md:23` records 394 passing tests, including 046’s 17 cases.

4. **High — resolved, non-blocking; finding 2 fixed.** `backend/tests/test_inbox_reply_examples_pg.py:11` rejects non-loopback hosts before opening a connection, matching 045’s guard.

5. **Low — non-blocking; finding 5’s deferral is acceptable for this empty migration.** `audits/046-PROD-RUNBOOK.md:19` assigns tenant agreement to ARIA-1b. Before activation, that code must perform a tenant-scoped source lookup and pass a cross-business rejection test. This review does not establish that those exist.

6. **Informational — non-blocking; runbook EXPECT values remain exact.** `audits/046-PROD-RUNBOOK.md:47` and `:81` correctly specify initial NULL, RLS true, zero client grants/rows, one recent index and **C + 10**, using matching census filters. Lines 32, 92 and 104 restrict routine rollback to staging; production rollback requires separate instruction.

Static, read-only review of `git diff HEAD~1`. No tests or SQL executed; no files modified, committed or pushed.