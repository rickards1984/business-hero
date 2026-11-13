# RCP-1 — Codex code review 3 (verbatim)

- **Reviewer:** Codex CLI (`codex exec --sandbox read-only`), model `gpt-6-astra`
- **Session:** `01a1d6d8-ca32-78f0-8ca0-95c0aaf7d63e`, 71,083 tokens
- **Reviewed:** the working tree on `ticket/RCP-1-build` after the review-2 fixes, 13 Nov 2026
- **Verdict:** CHANGES REQUESTED (0 blockers, 3 should-fix). This was the last permitted cycle, so it was escalated to Mike (AGENTS.md). Findings 1 and 2 were fixed with tests (each mutation-checked). Finding 3 (the £50 payment) was decided by Mike on 13 Nov 2026: deferred to the price catalogue, paid by BACS, Stripe or similar later. See the PR.

---

1. **SHOULD-FIX — Backfill uses UTC months against a UK-calendar ledger.**  
   [backend/services/receptionist_numbers.py:886](/Users/michaelrickards/dev/bh2-RCP1/backend/services/receptionist_numbers.py:886), also line 913.  
   Reproduced a purchase at `2027-06-30 23:30 UTC`—1 July in Britain. RCP-1 recorded 98p in June; July’s already-materialised ledger contained no receptionist cost. `running_costs` uses `metering.period_for()`, which uses Europe/London. The mismatch also defeats the 24-month clamp: at that instant, backfill starting June 2025 raises 422. Because `_save_bought` commits after recording costs, that refusal prevents adoption from being persisted.  
   **Fix:** Derive periods, retention limits and month-end cutoffs consistently in Europe/London. Add BST month-boundary tests, including an already-materialised current month and the oldest permitted backfill month.

2. **SHOULD-FIX — A conflicting assignment does not produce the claimed release-review flag.**  
   [backend/services/receptionist_numbers.py:509](/Users/michaelrickards/dev/bh2-RCP1/backend/services/receptionist_numbers.py:509).  
   After timeout-after-purchase, manually assigning another number and retrying correctly preserves the purchased number as `bought`, records its cost and refuses replacement. However, I reproduced `review=None`: `_review()` checks only entitlement. The request remains visible with an assignment error, but does not identify the unused, billable number for release review as claimed. The new parameterised test asserts the flag only for suspension.  
   **Fix:** Flag owned numbers whose business has a different assigned number, and assert this in the `another_number` case. Keep release manual.

3. **SHOULD-FIX — Review-1 finding 10 remains pending a scope decision.**  
   [docs/RCP-1-TICKET.md:75](/Users/michaelrickards/dev/bh2-RCP1/docs/RCP-1-TICKET.md:75).  
   The £50 Stripe payment is still deferred, explicitly **“Pending Mike’s OK.”** Recording the proposed amendment does not establish its approval; paid setup can still be fulfilled without collecting payment. This is an unresolved acceptance requirement, not a new implementation defect.  
   **Fix:** Mike must explicitly approve and record the RCP-1b deferral, or the agreed payment flow must be implemented.

The six review-2 responses check out as follows:

- **1:** Conditional assignment is present and the regression passes. PostgreSQL concurrency was not exercised here; the PostgreSQL suite still lacks the requested final-assignment interleaving test.
- **2:** Price-rise refusal resets to `requested`; recovery through Check and Buy passes.
- **3:** Adoption precedes eligibility checks and persists ownership/cost. Release-review coverage is incomplete as above.
- **4:** Twilio’s acquisition date and multi-month backfill are implemented; the calendar mismatch above remains.
- **5:** All four external-I/O workflows use `run_in_threadpool`; responsiveness tests pass. The session also sees sequential use during dependency/admin checks, so “one worker thread only, start to finish” is inaccurate, but I found no concurrent-session-use defect.
- **6:** Aria’s tool uses caller-context business identity and owner-filtered output; cross-tenant tests pass.

**Verification:** 86 SQLite tests passed with databases redirected to memory, readiness cache isolated between tests, and file-writing caches disabled. Additional in-memory reproductions confirmed findings 1–2. PostgreSQL tests, mutation checks and `check.sh` were not run. No files were modified, committed or pushed.

As this is the final permitted review cycle, these findings should now be escalated to Mike.

VERDICT: CHANGES REQUESTED