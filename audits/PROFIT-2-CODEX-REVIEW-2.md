Reviewed `612329f..59e17d8` on `ticket/PROFIT-2-costs-income`, against **North Star P8**.

**P1:** None found.

**P2 — SQLite rollback permanently loses invoice income.**  
In [_claim()](/Users/michaelrickards/dev/bh2-PROFIT-2/backend/services/stripe_income.py:98), SQLite’s current transaction configuration allows the savepoint to start before a real outer transaction. Releasing it commits the claim independently.

Reproduced using the actual service and in-memory SQLite:

```text
record_invoice → True
session.rollback()
remaining rows → stripe_invoice:in_rollback = 1
retry record_invoice → False
cash → 0
```

A subsequent webhook/refresh failure can therefore roll back cash and recurring income while leaving the invoice permanently marked as recorded. Ensure the claim participates in the outer transaction on SQLite. Add a behavioural regression asserting that rollback removes **both claim and income**, and retry records everything once. This is a SQLite defect; I am not claiming PostgreSQL has this failure.

Review-1 findings:

| Finding | Review 2 |
|---|---|
| Current Stripe attribution | Fixed: modern parent subscription, legacy fallback and ambiguous-customer rejection. Behavioural regressions pass. |
| Fabricated historical income | Fixed: history uses each month’s invoice receipts and top-ups, independent of current subscription status. Cancellation regression passes. |
| Non-atomic invoice deduplication | PostgreSQL approach is sound: unique insert arbitrates competing claims; catching the error outside the nested transaction preserves the outer transaction. Race regression exists but was not run. SQLite rollback defect remains above. |
| Concurrent running-cost edits | PostgreSQL transaction advisory lock covers materialisation **and** mutation, remaining held until commit/rollback. Race regression exists but was not run. |
| Wrong-month frontend writes | Fixed by inspection: rows are cleared during switching, writes use `bills.period`, and reload failures no longer become success messages. **No behavioural frontend regression was added.** |
| Cash omitting top-ups | Fixed; behavioural regression passes. The guard’s income path also skips cash, with a passing regression. |

I additionally forced a duplicate-insert failure on SQLite: the savepoint rollback left an existing outer write usable and committable. The defect is the **successful claim surviving outer rollback**, not duplicate-error recovery.

**Backlog / coverage**

- Add frontend tests for delayed month loads, failed loads, and successful writes followed by failed reloads.
- Refunds/credit notes and multiple subscriptions per business remain acknowledged limitations.
- Full-cycle invoices may contain adjustments; the withdrawn “never overstated” claim correctly reflects that limitation.

**Verification:** 88 PROFIT-1/2 tests passed using an in-process, memory-only SQLite adaptation. Targeted Ruff and frontend TypeScript checks passed. `RLS_LOCAL_DATABASE_URL` was unavailable, so neither PostgreSQL race test ran. Browser behaviour and `check.sh full` were not run; the latter writes files and conflicts with this read-only review.

Manual confirmation: Admin → Running costs → switch months under network throttling; confirm old rows disappear and failed loads never report “Saved.”

No files modified, committed or pushed. Pre-existing untracked `data.db` remains untouched.

**Verdict: REQUEST CHANGES.**