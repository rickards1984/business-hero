**PROFIT-1 review 4 — `8b96974`, North Star P8.**

**P1:** None found remaining.

**P2 — required corrections**

1. **Cancelled quote requests escape accounting.**  
   [assistant_chat.py:209](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/assistant_chat.py:209) catches `Exception`, which excludes `asyncio.CancelledError`. My mocked transport reproduced cancellation after entering the HTTP request: cancellation propagated, but **zero costs were recorded**. The provider may already have processed the request. Record an estimated failure and re-raise cancellation, as the SDK wrapper does. Add a regression asserting both outcomes.

2. **The preview regression does not test behaviour.**  
   [test_profit_guard.py:608](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/tests/test_profit_guard.py:608) only counts permission-check strings. Disabling both gates with `if False and …` still satisfies it. Add behavioural tests for both endpoints asserting **503 and zero provider calls** on an uncached request at the kill. My independent probes confirm the current implementation works; this is a regression-coverage gap.

**Review 3 closure and other checks**

- **Chat quote drafting:** gating and normal accounting fixed. The existing regression fails with the previous implementation restored in memory. Success, HTTP 500, malformed JSON and timeout probes each recorded once; HTTP 400 recorded nothing. Cancellation remains the exception above.
- **Receptionist previews:** both return 503 with zero provider calls. Restoring either old implementation produces 200 and one provider call. Cached audio can still play without spending.
- **Call summaries:** correctly non-essential; the regression detects the old exemption. At the kill, `_create_call_record` successfully committed the call and follow-up task with `summary=None`.
- **Plan-enforcement harness:** sound. `permits()` performs database I/O, so treating it as a boundary is appropriate. Denied cases require 403 before that boundary. Removing either preview’s entitlement check caused its denial regression to fail.
- **PostgreSQL race:** the revised test observes database blocking and requires successful completion. The interleaving now exercises advisory-lock waiting—or marker-row waiting without the lock. I did **not** independently execute PostgreSQL tests or reproduce the reported three mutation failures under this read-only instruction.
- **Runbook:** environment selectors and actual CHECK-definition verification are corrected; staging apply → rollback → reapply is explicit. Mike’s pending rehearsal is **not a code defect**.
- **Backend inventory:** no additional production OpenAI path found that is non-essential and both ungated and unrecorded. The known `research_compare` exception remains below.

**Backlog**

- Gate and persist costs for the billed `research_compare` admin script.
- Per-business paid-top-up profitability and alert-delivery visibility.
- Ensure the race test releases its writer transaction and joins its worker even when the blocking assertion fails.

**Verification:** 45 profit-guard tests passed using an in-memory fixture; 676 plan-enforcement tests passed; changed Python files pass Ruff. Additional mocked-provider and in-memory mutation probes supplied the evidence above. No `check.sh`, migrations or database-writing PostgreSQL tests were run. No files were modified, committed or pushed.

Mike’s behaviour check after correction: activate the kill in a test environment, try uncached voice previews and chat quote drafting, and confirm completed calls still save without summaries.

**Verdict: REQUEST CHANGES.**