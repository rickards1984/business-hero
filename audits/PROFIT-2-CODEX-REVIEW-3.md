Reviewed `59e17d8..cf31673` on `ticket/PROFIT-2-costs-income`, under **North Star P8**.

**P1:** None found.

**P2:** None found. Review-2’s rollback defect is fixed in [_claim()](/Users/michaelrickards/dev/bh2-PROFIT-2/backend/services/stripe_income.py:88): SQLite inserts within the caller’s transaction; PostgreSQL retains its savepoint and catches duplicate-claim errors outside it. No new PostgreSQL defect identified by inspection.

The SQLite regression passes: rollback removes the claim and cash; retry records once. The PostgreSQL regression checks successful retry after rollback and a single cash total.

**Backlog / coverage:**

- Strengthen both rollback tests to assert recurring amount and timestamp are absent immediately after rollback. Add explicit duplicate replay to the PostgreSQL rollback test.
- Frontend slow/failed-load tests remain outstanding.
- Refunds, credit notes and multiple subscriptions per business remain acknowledged limitations.

**Verification:** 89 PROFIT-1/2 tests passed using an in-memory SQLite adaptation; targeted Ruff passed. `RLS_LOCAL_DATABASE_URL` was unavailable, so PostgreSQL rollback and concurrency tests were **not run**. Browser testing and `check.sh full` were not run; the latter writes files and conflicts with this read-only review.

Manual confirmation: Admin → Running costs → switch months under network throttling; old rows should disappear, and failed loads must never report “Saved.”

No files modified, committed or pushed. Pre-existing untracked `data.db` left untouched.

**Verdict: APPROVE.**