# AI-1b — Codex code review 2 (verbatim)

Model gpt-6-astra, read-only sandbox, 21 Nov 2026.

---

REQUEST CHANGES

**Blocking defects**

2. **PARTIALLY RESOLVED — HIGH: business budget exists, but overspend is not bounded.** [ai_chat.py:130](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:130), [ai_chat.py:356](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:356). The query correctly scopes spend to the business, month and `chat_complex` meters; plan budgets and distinct refusal messages are implemented. All five budget tests passed using in-memory SQLite.

   Failure scenario: several requests read 499p against Starter’s 500p budget, then all proceed. Checks neither reserve funds nor account for in-flight requests. Failover also starts another paid attempt without rechecking.

   **Maximum excess:**
   - With reliable recording and sequential turns, overshoot is limited to **one admitted round’s entire provider chain**, not one provider call.
   - A turn has at most **six rounds**—five tool rounds plus finalisation—but each rechecks, so it cannot keep using complex rounds after recorded spend reaches the budget.
   - With **N concurrently admitted rounds**, excess can approach their combined chain costs.
   - At the repository’s default GPT-5 tariff, 32,768 output tokens cost **25.788p per attempt, plus input**. Twenty concurrent attempts can therefore add **515.768p plus input**, starting just below the limit. The 20/minute limit is per user, not a business concurrency cap.
   - There is **no fixed application-enforced maximum excess**. Input size, provider configuration and concurrency vary; additionally, `_record()` swallows write failures ([ai_chat.py:164](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:164)), allowing subsequent checks to read stale spend.

   **Recommendation:** reserve atomically per business/month before each provider attempt, then reconcile usage. A small, explicitly bounded overshoot could be acceptable; this implementation does not establish one.

4. **PARTIALLY RESOLVED — MEDIUM: final-answer truncation remains silent.** [assistant_chat.py:944](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:944). Truncated tool calls are now rejected before execution, and ordinary text replies receive a warning. However, finalisation ignores `reply.truncated`. Reproduced five tool rounds followed by a `length` response: the saved reply was simply “First half only”, without warning. Apply the same handling to finalisation.

9. **NEW — MEDIUM: empty replies can falsely report completed actions.** [assistant_chat.py:944](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:944). The new empty-response retry reaches the existing success fallback even when nothing happened. Reproduced “send the invoice” followed by two empty responses: **“I've completed the requested actions.”**, with zero tools executed. Return an honest inability-to-answer message unless completion is established by tool results. This conflicts with P8.

**Resolved original findings**

1. **RESOLVED — original HIGH: escalation bypass.** [assistant_chat.py:850](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:850). Initial selection, escalation and finalisation all call `task_for()`. A refusal keeps subsequent rounds on everyday chat. The previously failing escalation scenario passes; my six-round reproduction recorded six budget checks.

3. **RESOLVED — original HIGH: request rejection trips the shared breaker.** [ai_chat.py:227](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:227), [ai_chat.py:362](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:362). Both adapters classify 400/404/413/422 as `Rejected`; these attempts neither record invented spending nor trip the breaker. Request-error regression tests pass.

5. **RESOLVED — original MEDIUM: unbounded output and incomplete estimates.** [ai_chat.py:219](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:219), [ai_chat.py:319](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:319). OpenAI now receives an explicit limit; GPT-5’s actual limit and failure estimate both use 32,768. Serialized tool-call arguments enter the input estimate, and missing output usage triggers estimation instead of exact zero.

6. **RESOLVED — original MEDIUM: empty history poisons Anthropic requests.** [ai_chat.py:271](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:271), [assistant_chat.py:890](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:890). Empty assistant history entries are omitted and empty replies are retried. Both regression tests pass. The separate false-success regression is finding 9 above.

7. **RESOLVED — original MEDIUM: mandatory OpenAI key.** [assistant_chat.py:823](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:823). Availability uses the resolved chat chain. The Anthropic-only credential test passes.

**Optional hardening**

8. **PARTIALLY RESOLVED — LOW remaining; original MEDIUM: routing context.** [ai_chat.py:72](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:72). All original examples now pass. However, only the immediately preceding user message supplies context, and every short message is treated as a follow-up. Reproduced:
   - Profit question → “What about last month?” → “And the month before?” selects everyday chat on the third question.
   - Profit question → “Change my account name” selects complex chat despite the topic change.

   Improve contextual follow-up detection; these heuristic limitations need not block the safety fixes.

Verification: **62 pytest passes; five filesystem-dependent setup errors**, then **five successful in-memory reruns**. Additional mocked reproductions confirmed findings 4, 8 and 9. No files modified, commits or pushes. `check.sh` and live-provider tests were not run.