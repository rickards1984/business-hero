# AI-1c — Codex code review 3 (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

APPROVE

No blocking defect found in the review-2 fixes. Numbering follows review 2; remaining issues are follow-up hardening.

1. **Fixed — informational, non-blocking: saved chains now match task limits.** [ai_models.py:289](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_models.py:289). The former scenario—support displaying a fallback it never uses—is covered by the new saved-chain regression test. Additional in-memory probes confirmed ordered truncation for **all 21 tasks**, including `voice_preview` retaining three choices. The call-site tests provide partial integration evidence: they inspect source and call `chat_request()`, rather than execute the actual endpoints.

2. **Fixed for the reported race and continued spending — low residual risk, non-blocking.** [ai_eval.py:175](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:175), [ai_eval.py:203](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:203). Both concurrent admission tests pass, including the stale-copy reproduction. `_window` protects the entire list update; `_running` acquisition is non-blocking, so there is no lock-order deadlock. The caller’s `finally` releases the slot; an additional exception probe confirmed this.

   The mid-run test proves later calls stop when `permits()` becomes false, but stubs recording and the guard. It does **not** prove a real ledger-driven transition. Remaining scenario: a call admitted just below the spending threshold can cross it because there is no reservation. This is bounded overshoot, not the previously reported unbounded admission problem.

3. **Partially fixed — medium, non-blocking: timeout arithmetic is correct, but 150 seconds is not a strict elapsed-time guarantee.** [ai_eval.py:201](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:201). Boundary probes passed: under three seconds skips; exactly three starts; values above 25 cap at 25. However, remaining time is calculated **before** the guard query. Reproduced: five seconds remain, the guard consumes four seconds, then the adapter receives a five-second timeout, permitting completion four seconds beyond the deadline.

   The new test proves timeout arguments, not wall-clock completion. Also, [test_ai_model_admin.py:394](/Users/michaelrickards/dev/bh2-AI1c/backend/tests/test_ai_model_admin.py:394) sets a 0.4-second deadline, so `MIN_CALL_SECONDS = 3` now makes the older slow-call test skip **every** call. It still proves release, but no longer proves stopping after executing slow cases.

4. **Reported examples and crash fixed; grading remains partial — medium, non-blocking.** [ai_eval.py:58](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:58), [ai_eval.py:100](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:100). Passing tests cover missing/non-object arguments, invented money beside a lookup, both reported swapped-balance examples, and four honest answers. `[]` and `null` now fail without crashing.

   Additional probes reproduced:

   - **False failure:** “Harbour and Northgate owe £750 and £500 respectively; £1,250 total.” Splitting at “and” associates £750 with Northgate.
   - **False pass:** “£1,250 total; Harbour £500 / Northgate £750.” Clauses containing both customers bypass attribution.
   - **False pass:** “£1,250 total; Harbour owes £1,250; Northgate owes £500.” The total is allowed against either customer.

   These affect evaluation reliability under P2/P8; they do not change the configured model or execute customer actions.

5. **Fixed — informational, non-blocking: ledger mappings match the inspected attributions.** [ai_models.py:76](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_models.py:76), [ai_models.py:101](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_models.py:101). `reply_draft → draft`, `email_briefing → briefing`, and `wording → accountancy_pack` now agree with their recording sites. The former missing-spend/shared-label scenarios are addressed. Tests verify tuples and source strings; they provide partial proof rather than executing those workflows through recording and overview aggregation.

**Verification:** 76 admin tests passed with the file-backed SQLite fixture replaced **in memory** to respect the read-only sandbox. Additional probes covered all task limits, deadline boundaries, grading examples and exception-path slot release. No full `check.sh`, PostgreSQL or browser verification was performed. No files modified, committed or pushed.