# AI-1b — Codex code review 4 (verbatim)

Model gpt-6-astra, read-only sandbox, 21 Nov 2026. The extra cycle Mike approved.

---

APPROVE

1. **Resolved — previous HIGH blocker:** [backend/services/ai_chat.py:199](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:199). Spend is now read under the reservation lock. In the reported scenario, A cannot release its reservation between B’s spend read and admission decision. B therefore counts either A’s recorded cost or its reservation, preventing the demonstrated overspend.

2. **Resolved — previous MEDIUM blocker:** [backend/services/ai_chat.py:211](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:211). Unrecorded costs are indexed by business and UK month. November’s retained 500p no longer blocks December. The rollover regression test passes.

3. **Optional hardening — LOW — global lock contention:** [backend/services/ai_chat.py:199](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:199). A slow database read now delays every business’s admission and settlement. Enough waiting requests could occupy the shared worker pool and delay unrelated work. No lock-order deadlock was found: recording closes its database session before settlement acquires this lock. Calls use `asyncio.to_thread`, so there is no direct event-loop blocking. Consider per-business locks and bounded database waits.

4. **Optional hardening — LOW — rollover timestamps:** [backend/services/ai_chat.py:222](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:222). A recording attempt that starts before midnight but fails and settles afterward assigns its unrecorded cost to the next month. Admission also samples the month separately for recorded and unrecorded spend. Capture and consistently pass the accounting timestamp; add a test crossing midnight during these operations. This does not reproduce the previous persistent rollover blockage.

5. **Resolved — previous optional LOW routing finding:** [backend/services/ai_chat.py:87](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:87). The reported polite new-job phrases now select ordinary chat. No blocking regression found in the detector extension.

Verification: **82 tests passed** in `test_ai_chat.py`, using in-memory SQLite to respect the read-only sandbox. `check.sh`, PostgreSQL concurrency and live-provider tests were not run. No files modified, commits or pushes.