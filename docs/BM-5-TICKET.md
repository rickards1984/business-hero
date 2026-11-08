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
