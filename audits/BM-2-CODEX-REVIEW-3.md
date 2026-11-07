1. **P2 — Executor-queued turns can still be lost at teardown.** [backend/realtime_voice.py:1361](/Users/michaelrickards/dev/bh2-BM-2/backend/realtime_voice.py:1361). If the executor is busy, the writer has removed a turn from `turns`, but `_save_turns` has not started and `in_flight` remains zero. Cancelling the writer cancels that pending submission; teardown sees no leftovers, unsaved turns or active saves and skips recovery. An in-memory probe reproduced the lost turn. Track ownership before executor submission and preserve cancelled pending items.

2. **P2 — `FINAL_SAVE_SECONDS` does not bound recovery.** [backend/realtime_voice.py:1029](/Users/michaelrickards/dev/bh2-BM-2/backend/realtime_voice.py:1029). The initial batch runs before the deadline starts, and subsequent batches execute blocking saves without a deadline. A slow or hung database can retain executor workers indefinitely and delay executor shutdown, although socket cleanup remains bounded. A scaled probe took 90 ms with a 20 ms limit.

Review 2’s billing and flush-result fixes are addressed; ordinary Aria billing remains unchanged. Recovery remains incomplete.

Verification: **102 targeted tests passed**; both findings reproduced using repository functions in memory. Full `check.sh` and browser checks were not run. No files changed, commits or pushes.

**Verdict: CHANGES.**