# BM-5 — Codex review 2 (verbatim)

Reviewed `git diff HEAD~1..HEAD` and the branch at 5ada4ff.

1. **Medium — [backend/realtime_voice.py:1376](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1376): other continuation refusals leave `asked` stuck.**  
   If `response.create` receives an event-ID-matched error other than `conversation_already_has_active_response`, the handler leaves `asked` populated and `owed=False`. Without another response, continuation cannot retry, `_tools_busy()` remains true, and every flush times out unsuccessfully. An in-memory replay reproduced this with `rate_limit_exceeded`.  
   **Fix:** reconcile every error matching an outstanding request: clear `asked`, then either restore the obligation with bounded retry/backoff or explicitly terminate it with an actionable error. Add a regression test for refusal without a subsequent `response.created`.

2. **Medium — [backend/realtime_voice.py:1334](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1334): cancelling an accepted continuation silently loses the answer obligation.**  
   Once the continuation starts, `owed` is already false. If an owner noise interrupts it before any answer is delivered, `response.done(cancelled)` clears `continuing`. When speech stops without a replacement response, no fallback is scheduled because `owed` remains false. Aria stays silent, and flush can report success despite the missing answer. The in-memory replay reproduced this state. Existing interruption tests interrupt the *tool-requesting* response, not the accepted continuation.  
   **Fix:** track the continuation’s response identity and retain or restore its obligation when cancelled before delivering an answer. Test cancellation after acceptance, followed by speech ending without a replacement response.

3. **Medium — [backend/realtime_voice.py:1267](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1267): the post-speech waiting period can be bypassed.**  
   After `speech_stopped`, a timer is scheduled, but a lookup finishing during that interval calls `_continue_after_tools()` immediately. With `owner_speaking=False` and no received `response.created`, it sends a continuation before the intended 1.5-second wait expires, racing the automatic response. The fixture’s `owner_speaks()` immediately queues the automatic response, so it does not exercise this gap.  
   **Fix:** enforce a shared post-speech deadline inside `_continue_after_tools()`, regardless of which caller invokes it. Test a held lookup released after speech stops but before the automatic response is announced.

4. **Low — [backend/realtime_voice.py:1355](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1355): delayed continuation tasks survive socket teardown.**  
   `_continue_soon` tasks are neither retained nor cancelled. Disconnecting during their sleep can leave a task waking with an outstanding obligation and sending on the closed upstream socket, producing an unhandled task exception. This is bounded-lived cleanup noise, rather than an indefinite task leak.  
   **Fix:** retain and cancel/await these tasks during teardown, and guard continuation against a closing session. Test disconnect while the fallback timer is pending.

The normal grace and flush gaps from review 1 are addressed. Held lookup gates improve ordering tests, but delayed acceptance and the cases above remain uncovered.

The accounting hook currently wraps **chat, Responses, and audio speech**, not embeddings, images, or Realtime. Both new accounting tests passed using an in-memory SQLite substitution. The known validation-refusal fix works; [OpenAI’s error documentation](https://developers.openai.com/api/docs/guides/error-codes) does not establish a universal billing guarantee for every HTTP 400.

Verification: 30 selected tests passed; three fixture setups were blocked by read-only temporary storage. The two new accounting tests then passed in memory. No files modified; `check.sh` was not run.

VERDICT: CHANGES REQUESTED