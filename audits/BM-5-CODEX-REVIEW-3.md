# BM-5 — Codex review 3 (verbatim, targeted)

Reviewed `git diff HEAD~1..HEAD` at 59154ab.

Review-2 findings:

1. **Resolved:** Other continuation refusals clear `asked` and tell the owner to ask again.
2. **Resolved:** Cancellation before audio restores the answer obligation.
3. **Resolved for the reported scenario:** All continuation callers respect the post-speech deadline. However, this introduces the defect below.
4. **Resolved:** Timers are retained and cancelled during teardown; send failures are caught. No regression test covers teardown.

New finding:

1. **Medium — [backend/realtime_voice.py:1272](/Users/michaelrickards/dev/bh2-BM-5/backend/realtime_voice.py:1272): fast lookups can leave Aria silent.** When the owner stops speaking with no tool answer owed yet, `quiet_until` is set but no timer is scheduled. If the subsequent automatic response requests a lookup and both finish within 1.5 seconds, continuation is blocked by that deadline. Nothing retries when it expires. An in-memory endpoint replay reproduced this: tool output delivered, zero continuation requests afterward. **Fix:** whenever the deadline blocks an otherwise-ready continuation, schedule a tracked wake-up for the remaining delay. Add coverage where speech stops *before* the tool request.

Verification: all four new tests passed; the additional replay reproduced the defect. No files modified; `check.sh` was not run.

VERDICT: CHANGES REQUESTED