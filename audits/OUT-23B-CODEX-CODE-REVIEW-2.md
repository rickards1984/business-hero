# OUT-23 Part B (Hunter.io) — Codex code review 2 (targeted, verbatim)

Commit reviewed: f54bf5c (fixes for review 1).

---

1. **HIGH — Spending can still disappear across an account refresh.** [outreach_hunter.py:508](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_hunter.py:508)  
   A request reserved before `account_fetched_at`, but charged after the snapshot, counts while reserved and disappears once settled: its `created_at` precedes the cutoff. Another run can refresh the account while this request is in flight. The unchanged snapshot balance then admits another spend. An in-memory SQL reproduction confirmed the deduction changes from 1 to 0. **Fix:** reconcile snapshots against request completion and explicitly retain overlapping charges; prevent older concurrent refreshes from replacing newer snapshots. Add an interleaved reservation/refresh/settlement regression test.

2. **HIGH — The network deadline remains unenforced during blocking reads.** [outreach_research.py:1629](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_research.py:1629)  
   The timeout is calculated once; the deadline is checked only after a chunk arrives. A read begun near the deadline can therefore block for the original timeout. An isolated reproduction returned after **0.916 seconds against a 0.600-second deadline**. Publication reads retain the same problem. Additionally, forced account refreshes use a fresh 15-second timeout without the run’s remaining budget. **Fix:** enforce cancellation at the absolute deadline throughout requests and reads, and pass that deadline into forced refreshes. Test elapsed time, including a stalled final read and refresh near budget exhaustion.

Original findings **1, 2, 6 and 7 appear fixed**. Finding **4’s refresh signalling and transaction placement are fixed**, subject to the issues above. The connect endpoint’s session use is sequential: dependencies finish before the awaited threadpool service runs; I found no concurrent session use.

The MX mutant is equivalent under the five-second start gate. The 2,000-byte mutant is equivalent for the oversized-key/no-echo assertion, **not universally**: valid-key JSON padded with whitespace beyond 2,000 bytes distinguishes it.

Read-only; nothing modified, committed or pushed. Inspected the diff and tests; ran isolated in-memory reproductions. Did not run `check.sh` or database suites.

VERDICT: CHANGES REQUESTED