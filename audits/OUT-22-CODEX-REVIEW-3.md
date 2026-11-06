# OUT-22 — Codex review 3, targeted (preserved verbatim)

APPROVE — both prior findings are resolved. No new findings in the targeted review.

- P1: existing rows return before the advisory lock; missing-row creators still lock and recheck.
- P2: all three helpers ensure the row exists before locking and reading.
- In-memory SQLite checks passed for all three helpers, including `lock_business`.
- The PostgreSQL race test still removes UNIQUE and runs six concurrent creators.

PostgreSQL tests and `check.sh` were inspected, not run under the read-only constraint. No files modified, committed, or pushed.