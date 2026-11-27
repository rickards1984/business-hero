# 046 — Codex code review 3, narrow and final (verbatim)

Model gpt-6-astra, read-only sandbox, 25 Nov 2026.

---

APPROVE

1. **Informational — resolved, non-blocking.** `backend/tests/test_inbox_reply_examples_pg.py:56` now asserts both SQLSTATE and exact constraint name. Each CHECK case supplies `23514` and its expected constraint; FK cases likewise assert `23503` and specific constraints. Review 2’s blocking finding is fixed.

2. **Informational — resolved, non-blocking.** `audits/046-PROD-RUNBOOK.md:19` explicitly requires implementation **and tests** for owner viewing/deletion, the 20-per-category cap, and tenant-scoped source lookup with cross-business rejection before ARIA-1b uses the table. Line 13 also corrects the closure overstatement.

Static review of `git diff HEAD~1`; no tests or SQL executed. No files modified, committed or pushed.