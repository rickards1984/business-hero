**REQUEST CHANGES — PROFIT-1 review 1, commit `a5321b8`.** This does not yet reliably enforce the approved guard or provide trustworthy cost figures under North Star P8.

**P1 — blocking**

1. **Platform costs and alert markers cannot use the documented PostgreSQL schema.**  
   [`profit_guard.py:197`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:197) queries/inserts `business_id = "platform"`, but the [recorded schema](/Users/michaelrickards/dev/bh2-PROFIT-1/audits/live-schema-public.txt:1089) declares UUID; the migration also declares a business foreign key. Consequently, unattributed calls—including briefings and meetings—fail recording, and threshold checks fail before creating alert markers. The savepoint protects the preceding business cost write, but no email follows. Use a storage design compatible with the actual schema and tenant boundaries.

2. **The async chat SDK hook records the coroutine, not its response.**  
   [`wrap_create:296`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:296) relies on `inspect.iscoroutinefunction`. In the installed SDK, `AsyncCompletions.create` returns **False**, while its unwrapped function returns **True**. It therefore takes the synchronous wrapper and records before awaiting the response. Reproducing that decorator shape recorded `0.000001p` instead of actual tokens—rounded to zero by PostgreSQL’s `numeric(14,4)`. Async briefings, meetings and support are affected. Test the actual SDK entry point with mocked transport.

3. **Non-essential AI remains ungated, and quoting remains unrecorded.**  
   The hook only records; it never checks permission. Existing calls in [email drafting](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/app/email/service.py:562), [assistant email drafting](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/assistant_tools.py:2881), [support](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/support_api.py:663) and [call summaries](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/openai_utils.py:28) continue beyond the threshold. [Quote generation](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/quoting_api.py:1250) uses direct HTTP, bypassing both recording and gating. Explicitly gate non-essential operations while preserving owner chat, live calls and reply sorting.

4. **Voice overage is missing from platform and business costs.**  
   [`costs:87`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:87) counts only included-minute meters. [Meter allocation](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/metering.py:398) puts excess minutes into separate receptionist and Aria overage meters. Reproduction: **100 overage minutes reported 0p instead of 1,600p**. Include both overage meters in `costs` and `_losing`. Standalone [TTS](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/main.py:2510) also has no cost recording or minute accrual in this path.

5. **Briefings and meetings bypass the absolute kill.**  
   [`permits:243`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:243) calls `profit_guard.allowed`, bypassing `ai_costs.allowed`. Reproduction with the absolute limit exceeded: `ai_costs.allowed(..., purpose="briefing") == False`, but `permits("briefing") == True`. This particularly breaks the documented pre-launch protection when neither subscription income nor trial budget exists.

6. **Research can be recorded twice once platform recording is repaired.**  
   Suppression at [`_record_response:266`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:266) only covers `ai_costs.collect()`. [Research calls](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/outreach_research.py:793) run outside that context and subsequently record their returned costs explicitly. The SDK hook adds another charge. xAI searches also use this SDK, but the hook labels them OpenAI and applies its unknown-model rate. This can falsely trip the switch. Suppression must cover all explicitly accounted router paths.

**P2 — required corrections**

- **Missing usage and failed requests are effectively free.** [`_record_response:271`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:271) substitutes zero tokens and a sub-storage-precision minimum. Exceptions from the underlying SDK bypass recording entirely, including potentially billable timeouts. Use conservative estimates when usage is unavailable; retain the guarantee that accounting failure does not break the customer’s response.

- **Connection-savepoint rollback does not discard queued alerts.** [`check_after_record:213`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:213) mutates `session.info`, but connection-level rollback does not invoke the session rollback hooks. I reproduced a unique violation on the second marker: the ledger cost survived, the first marker rolled back, yet its email fired on outer commit. Normal ledger writers are serialized by the advisory lock, so this is not an ordinary concurrent-writer race. Nevertheless, failed savepoint work must restore its pending-alert state.

- **Voice/fixed-cost threshold crossings do not trigger email independently.** `check_after_record` is only called after AI recording. Voice can cross the threshold, or fixed costs can put a new month above it, without any notification until another recorded AI call occurs. That call may already be prevented by the guard. Add a committed-cost or scheduled threshold check.

- **Business attribution is incomplete and can escape function boundaries.** [`label:231`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:231) never resets its context; directly awaited functions share the caller’s context. Briefings and meetings omit the business ID entirely, and nested drafting can inherit `"chat"`. Use scoped attribution at operation boundaries and verify concurrent async tasks and threadpool execution.

**Backlog**

- Refresh the ProfitPanel while open; it currently fetches once and can keep showing an outdated healthy state.
- Include paid top-ups in per-business profitability, and expose alert-delivery failure rather than treating configured addresses as evidence of delivery.
- Make the financial limitation explicit: monthly recurring revenue, a trial allowance and exemptions for essential activity do **not** guarantee net profit on every transaction. Full fixed costs can legitimately exhaust the trial allowance on day one.

**What checked out:** active subscription filtering and plan-price summation match the ticket; trial budget is a fallback, not additive income. AI totals exclude breakdown rows, avoiding that source of double counting. Both existing `ai_costs.allowed` callers now supply appropriate purposes; omitted purpose is non-essential, guard-read failures hold non-essential work, and that function checks the absolute limit first. Briefings fall back and meetings suppress model calls at the percentage kill. Owner chat remains available. The admin endpoint uses the real platform-admin dependency, and `send_alert` catches delivery exceptions.

**Verification:** 21 existing test functions passed with an in-memory replacement for their disk fixture; additional read-only probes reproduced the failures above. The tests use SQLite with TEXT business IDs, omit actual async SDK behavior, and override admin authentication rather than testing denial.

No files were modified, committed or pushed. I did **not** run `check.sh` because it writes artifacts, or execute PostgreSQL tests under this read-only authorization. PostgreSQL UUID/FK, advisory-lock concurrency, savepoint failure and outer commit/rollback tests remain required before approval.

After correction, Mike’s behaviour check should be: cross the thresholds in a test environment, open **Admin Dashboard**, confirm one email per threshold, verify non-essential generation pauses, and confirm owner chat and live calls continue.