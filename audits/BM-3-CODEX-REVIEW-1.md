1. **P2 — Tool results are silently cut mid-JSON.** `backend/services/executive_meeting_orchestrator.py:535` slices results at 30,000 characters. A synthetic 12-month ledger with 20 counterparties and ordinary 275-character descriptions produced 34,587 characters; truncation removed remaining receipts and the allowance advisory. Return valid, explicitly truncated JSON with preserved totals and coverage. No test covers oversized results.

2. **P2 — Preparing a meeting blocks the event loop.** `backend/services/executive_meeting_prep.py:120` synchronously queries and aggregates the ledger. Both async `/start-now` and `/prep-now` handlers call this directly. A busy business’s ledger or slow database therefore stalls other requests and voice processing on that worker. Move preparation into a worker with its own session; the current tests don’t check responsiveness.

3. **P2 — Recurring receipts crowd out “one-off” income.** `backend/services/meeting_ledger.py:154` selects every income transaction ≥£500, then keeps the newest 40. Forty recent recurring Ashbourne/GoCardless receipts can hide an earlier £1,625 course payment, without indicating omissions. The tool description nevertheless calls these “large one-off income.” Distinguish recurring payments or label this accurately and expose truncation. The existing test never exceeds 40 qualifying receipts.

4. **P2 — Typed ledger lookups have no timeout.** `backend/services/executive_meeting_orchestrator.py:1151` awaits the worker indefinitely. A stalled database lookup leaves the owner’s message saved but the response pending; bounded model rounds do not bound tool execution. Add a lookup deadline and recoverable tool error, with a slow-tool regression test.

5. **P3 — Every search fails on leap day.** `backend/services/meeting_ledger.py:213` replaces the year directly. On 29 February 2028, constructing 29 February 2026 raises `ValueError`; reproduced through `run_tool`, which returns an error for otherwise valid searches. Clamp the anniversary to a valid date and test it.

Verification: **104 tests passed** across ledger, spoken-meeting and BM-1 AI suites. Full `check.sh` was not run in this read-only review.

**Verdict: CHANGES.**