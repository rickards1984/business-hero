# AI-1d — Codex code review 1 (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

REQUEST CHANGES

1. **High — blocking: failover bypasses a newly closed kill switch.** [backend/services/ai_text.py:70](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:70) checks `permits()` only before entering the chain. If recording the first failed or empty answer crosses the spending threshold, subsequent providers still receive requests. `profit_guard.accounted()` suppresses the SDK’s `_refuse_if_paused()` check, so it cannot intervene. Reproduced with the first adapter closing the guard: the second adapter was called while permission was false. Recheck before each attempt; test a guard transition during failover, not only a job starting paused.

2. **Medium — blocking: fence extraction corrupts valid JSON containing backticks.** [backend/services/ai_text.py:123](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:123) searches anywhere in the response, including inside JSON string values. A valid reply object whose `body_text` contains `` ```json {"enabled": true}``` `` gets replaced by the escaped inner fragment. Single-draft generation then saves that fragment as the reply; classification and three-draft parsing can fall back unnecessarily. Preserve already-valid JSON before attempting wrapper extraction. Existing tests cover external fences, but no fences inside JSON values.

3. **Medium — blocking: support evaluations certify invented policies and incorrectly attributed prices.** [backend/services/ai_eval.py:253](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:253). Both these answers reproducibly pass:
   - Refund policy: “Yes, cancellations receive a full refund. The team will process it.”
   - Pro price: “Pro costs £269 a month; Business costs £129. [CATEGORY: billing] [CONFIDENCE: 0.9]”

   Mentioning “team” does not establish uncertainty or a handoff, and membership in the set of plan prices does not establish the correct plan–price relationship. Add adversarial checks for unsupported affirmative policies and swapped prices.

4. **Medium — blocking: briefing evaluations accept incorrect figures and unusable action structures.** [backend/services/ai_eval.py:301](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:301) accepts `{"action_options":[1,2,3]}` without any briefing or action objects. [backend/services/ai_eval.py:311](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:311) accepts “Revenue fell 20% to £4,200 from £3,500.” Both were reproduced. Validate required action fields and the direction and attribution of the revenue change. The current tests reject missing JSON and changed amounts, but do not cover these false passes.

5. **Medium — blocking: daily-pulse evaluations use five times the production output allowance.** [backend/services/ai_eval.py:340](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:340) gives every briefing case 2,000 tokens; production daily pulses request 400. A candidate can therefore pass evaluation with an answer that production truncates. `complete()` returns the truncation flag, but the pulse caller ignores it. Give cases their actual site limits and use those limits in admission costing. The £3 cap calculation is internally consistent with the current evaluation requests; the mismatch is between evaluation and production.

6. **Medium — non-blocking, inherited accounting gap: SDK retries are not recorded individually.** [backend/services/ai_chat.py:317](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_chat.py:317) enables one internal SDK retry, while `ai_text` records only the adapter’s final outcome. If a first request is processed but its response times out, then the retry succeeds, only the successful response’s usage is recorded. Two timeouts receive only one request’s maximum estimate. The previous sites also used SDK retries, so this is not a newly introduced regression, but the ticket’s “each attempt” accounting claim is stronger than the implementation. A mocked SDK transport test should cover timeout → success and timeout → timeout.

7. **Medium — non-blocking: the timeout is per attempt, not a job deadline.** [backend/services/ai_text.py:85](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:85) gives every adapter the full 30 seconds. OpenAI/xAI can each retry, adding another timeout and backoff; Claude ignores the `retries` argument. Three different providers timing out can therefore consume roughly 150 seconds plus backoff, rather than 90 seconds. Consider a total deadline with remaining-time limits. Tests currently verify the passed timeout value, not elapsed chain behaviour.

8. **Low — non-blocking: the chat grading follow-up still accepts a total assigned to one customer.** [backend/services/ai_eval.py:136](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:136) permits the total whenever a clause contains “total”. “Harbour owes £1,250 in total. Northgate owes £500.” reproducibly passes. The new regression example omits that qualifying word, leaving the original class of false pass unresolved.

Normal-path attribution and SDK-hook suppression appear consistent: no duplicate recording or changed business/purpose attribution found. The moved task declarations reach the shared chain; quotes and meetings remain restricted. The email workers read already-loaded scalar attributes, and callers await them before further session work; I found no demonstrated concurrent ORM-session access. Context propagation is covered.

Validation: **109 tests passed; 84 setup errors required temporary files unavailable in this read-only environment.** In-memory reproductions confirmed the findings above. `check.sh` was not run because it writes compilation artifacts. No files were modified, committed or pushed.