1. **P1 — Memory mutations do not require the owner.** [executive_meeting_api.py:316](/Users/michaelrickards/dev/bh2-BM-4/backend/executive_meeting_api.py:316)  
   `get_user_business_context` checks active membership, not owner role. A staff member can confirm proposals, add confirmed memories, or edit existing confirmed text through these endpoints. That text then enters the business’s prompts without owner consent. Enforce active-owner authority on mutations; add HTTP tests for non-owner rejection.

2. **P2 — Deduplication confirms a group the owner never submitted.** [aria_memory.py:108](/Users/michaelrickards/dev/bh2-BM-4/backend/services/aria_memory.py:108)  
   Deduplication compares only `about` and `meaning`. If a proposal contains those fields plus a group, an owner adding the same note with no group—or a different group—confirms the proposal’s original group. Reproduced: adding without a group returned the proposal’s `"Unapproved group"`. Confirm the submitted content, including its group, rather than silently promoting different content.

3. **P2 — Memory-read failure rolls back meeting startup.** [executive_meeting_orchestrator.py:1180](/Users/michaelrickards/dev/bh2-BM-4/backend/services/executive_meeting_orchestrator.py:1180)  
   `start_meeting()` updates status to `in_progress` before calling `_memory_block`, without committing. On a memory-read failure, this helper rolls back that status change. Startup subsequently saves the opening and returns successfully, but the meeting remains `prep_ready`, so subsequent turns are refused. Reproduced that the fallback discards pending writes. Isolate the optional read using a separate transaction/session or savepoint, and test startup under read failure.

4. **P2 — Group lists can destroy the detailed ledger response.** [meeting_ledger.py:318](/Users/michaelrickards/dev/bh2-BM-4/backend/services/meeting_ledger.py:318)  
   The new group lists are absent from `_TRIM_PATHS`. With 100 populated groups across twelve months in both directions, these lists alone exceed both output budgets. `fit()` exhausts its other lists, then returns headline numbers and an error, losing groups, monthly detail and coverage. Reproduced a 50,444-character grouped payload reducing to totals plus error. Add bounded trimming for groups and a twelve-month regression test.

5. **P2 — The confirmed-memory limit is bypassable.** [aria_memory.py:109](/Users/michaelrickards/dev/bh2-BM-4/backend/services/aria_memory.py:109), [aria_memory.py:152](/Users/michaelrickards/dev/bh2-BM-4/backend/services/aria_memory.py:152)  
   Promoting a duplicate through `add()` bypasses the limit entirely. Separately, `confirm()` counts before acquiring the write lock: two confirmations at 99 can both pass and produce 101. The duplicate bypass is reproducible sequentially and can grow the prompt beyond the intended bound. Check capacity inside the locked mutation on every promotion path, while allowing idempotent confirmation.

6. **P2 — A positive threshold can save as zero and break ledger lookups.** [aria_memory.py:186](/Users/michaelrickards/dev/bh2-BM-4/backend/services/aria_memory.py:186)  
   Validation precedes whole-pound rounding. Saving £0.10 succeeds but persists `0.0`; subsequent `ledger_summary` calls reject the stored threshold and return an error instead of the ledger. Reproduced both results. Validate the rounded value or preserve pennies, and cover fractional and non-finite inputs.

**Verification:** 885 tests passed across memory, ledger, board-meeting voice and plan enforcement. The cases above are not pinned by those tests. Full `check.sh` was not run because it writes compilation artifacts; the review remained read-only. BM-3b was excluded.

**Verdict: CHANGES.**