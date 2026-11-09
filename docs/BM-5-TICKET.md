# BM-5 — Spoken Aria goes silent after look-ups; typed meetings fail on gpt-5.5

**Found:** Mike's Railway logs, 8 Nov 2026, 17:33–17:44 (board meeting 68c07dd6).

## Fault 1: silence after the first spoken reply

The owner spoke; Aria asked for two `remember`s in one reply (17:35:37). Each
answer sent its own `response.create` while that reply was still running.
OpenAI refused one: `conversation_already_has_active_response` (17:35:40). The
model called `remember` a third time and the conversation went silent.
Nothing in the logs says why the second spoken turn got no reply: a reply's
own `response.done` status was never logged.

**Fix (`backend/realtime_voice.py`).**
- After look-ups, Aria is asked to go on once, after the reply that asked for
  them has finished AND every look-up is answered.
- A look-up that raises is still answered, so the model never waits for it.
- A reply that ends `failed` or `incomplete` is logged with its details. A
  failed one tells the owner on screen to say it again.
- The harmless active-response refusal is no longer shown as "Error".
- A one-line `[Voice summary]` is logged at close: replies, failed, owner
  turns, look-ups.

## Fault 2: every typed meeting turn failed

`EXECUTIVE_MEETING_AI_MODEL=gpt-5.5`. BM-3 offers the ledger tools; gpt-5.5
refuses tools with `reasoning_effort` in Chat Completions ("set
reasoning_effort to 'none'"). Aria's honest fallback ("your message is saved,
try again") was the result. The summary and extraction calls carry no tools,
so they worked, which is why ending the meeting worked.

**Fix (`executive_meeting_orchestrator._gpt_chat_completion`).**
- With tools, gpt-5.x (x ≥ 1) is asked with `reasoning_effort: "none"`.
- Any other model that refuses is retried once with `none` and remembered.
- The final no-tools round keeps `low`. Other failures are not retried.

## Not credits

OpenAI fell only $2; both faults are 400/refusals, not quota errors.

## Tests

- `test_board_meeting_voice.py`: BM-5 section, 7 tests.
- `test_board_meeting_ai.py`: BM-5 section, 7 tests.
- Every fix was mutation-checked: removing it fails a test.

## Codex review 1 — CHANGES REQUESTED (5 findings), all fixed

1. **Interruptions.**
   - Aria is never asked to go on while the owner is talking, or while any
     reply is running.
   - Her request carries an `event_id`. If OpenAI refuses it, she still owes
     the answers and goes on after the other reply.
   - If the owner stops and no reply follows, she still goes on (1.5 s).
   - Ordinary voice now runs look-ups beside the stream too, so the owner
     cutting in is seen.
   - The tests use `_RealtimeLike`: one reply at a time, and an overlapping
     request is refused, as OpenAI does.
2. **Finishing grace at the limit** covers look-ups still running and Aria's
   reply with their answers.
3. **Flush** waits (bounded) for that reply and its saved transcript. It is
   not ok while she still owes the answers.
4. **No double charge.** `profit_guard.wrap_create` no longer estimates a cost
   for a 400 (refused as written, never billed). A retried meeting turn is
   recorded once, tested through the real hook.
5. **Tests are not timing-dependent.** Look-ups are held behind explicit
   events and released by the test.

## Codex review 2 — CHANGES REQUESTED (4 findings), all fixed

1. **Any refusal of Aria's go-on** clears the pending request.
   - "Another reply is running" keeps the debt, and she goes on after it.
   - Anything else (e.g. a rate limit) tells the owner to ask again, so
     nothing is left waiting and ending the meeting is not held up.
2. **Her reply with the answers, cancelled before a word of it is heard**,
   leaves them owed. Once any of it has been heard it is not repeated.
3. **The pause after the owner stops** (1.5 s) is enforced inside the one
   place that asks her to go on, whoever calls it.
4. **The post-speech timers** are kept and cancelled with the session.
   Sending to a closing socket is caught. No test was kept for this: the test
   harness ends its event loop with the socket, so a surviving timer cannot be
   observed there (a test written for it passed with the fix removed).

## Codex review 3 — all four review-2 findings resolved; 1 new finding, fixed

A look-up asked for by the provider's own reply to the owner, answered within
the post-speech pause, left nobody to wake Aria when the pause ended. Now,
whenever the pause is the only thing holding her back, a tracked timer wakes
her when it ends. Tested in both modes; the test fails with the timer removed.
