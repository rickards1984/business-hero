# BM-5 — Codex review 1 (verbatim)

Prompt: as preserved in the session scratchpad; reviewed `git diff origin/main...HEAD` at 2b31b28.

1. **High — [backend/realtime_voice.py:1244](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1244): interruptions can still lose or duplicate a continuation.**  
   `responding` reflects received events, while `owed` is cleared before OpenAI accepts `response.create`. In ordinary mode, an inline lookup can block event consumption while the owner interrupts and OpenAI starts another response. Processing the queued old `response.done` then sends a continuation against that already-active response. Its refusal is suppressed, and `owed` is never restored. Alternatively, cancellation while the owner is still speaking immediately restarts Aria before their new turn is committed. Automatic interruption and response creation are part of [Realtime VAD behavior](https://developers.openai.com/api/docs/guides/realtime-vad).

   **Fix:** track requesting response IDs, owner speech state, and continuation requests awaiting acceptance. Reconcile refusals instead of discarding the obligation. Test both modes with a stateful upstream that actually rejects overlapping responses. The cancellation test at line 944 merely counts outgoing requests; it cannot prove one was accepted.

2. **Medium — [backend/realtime_voice.py:1298](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1298): the deferred continuation falls outside finishing grace.**  
   After the tool-requesting response ends, `responding` becomes false while background lookups remain outstanding. If the allowance expires then, `_end_at_cap` at line 1100 sees no response or audio playback and immediately closes the session, cancelling the tools. The same gap exists after sending the continuation but before receiving `response.created`. Aria’s final answer is cut off despite the available grace period.

   **Fix:** include outstanding tools, owed continuations, and requests awaiting acceptance in the bounded finishing condition. Add deterministic allowance-expiry tests for both gaps.

3. **Medium — [backend/realtime_voice.py:1262](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1262): flush can acknowledge completion before a deferred answer exists.**  
   When all tools finish before the requesting response ends, their tasks leave `pending_tools`, but `tool_turn["owed"]` remains true. The flush check at line 1181 ignores that state and can return `ok: true` after its fixed delay. Ending the meeting then closes the socket before the continuation or its transcript is saved.

   **Fix:** make flush wait, within its deadline, for the relevant response/tool/continuation chain and transcript persistence. Return `ok: false` when that chain remains unfinished. Cover delayed `response.done` and delayed continuation creation.

4. **Medium — [backend/services/executive_meeting_orchestrator.py:533](/Users/michaelrickards/dev/bh2-BM-5/backend/services/executive_meeting_orchestrator.py:533): the recoverable refusal is recorded as estimated spend before retrying.**  
   The installed `profit_guard.wrap_create` records every exception through `_record_failure`, estimating the full request’s input and maximum output. Thus the known parameter-validation 400 records estimated spend, then the successful retry records actual spend. Near the guard limit, that artificial first charge can also block the retry. Both attempts have correct business attribution, and returned tokens count successful responses, but spend accounting differs.

   **Fix:** distinguish definitive, unbilled validation refusals from ambiguous failures in the accounting hook. Test the retry through that hook, asserting attribution, recorded cost, and cumulative tokens; the current fake bypasses it.

5. **Low — [backend/tests/test_board_meeting_voice.py:936](/Users/michaelrickards/dev/bh2-BM-5/backend/tests/test_board_meeting_voice.py:936): the answer-ordering test is timing-dependent.**  
   After observing `k1`, the test sleeps and assumes the 0.6-second `k2` lookup remains unfinished. A scheduling pause can let `k2` finish first, failing correct code. Other negative assertions likewise rely on sleeps rather than confirmed event processing.

   **Fix:** hold each lookup behind an explicit synchronization barrier, confirm the relevant upstream event was processed, assert no continuation, then release the final lookup.

The 14 selected tests passed. No files were modified; the full verification suite was not run.

VERDICT: CHANGES REQUESTED