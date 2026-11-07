1. **P2 — Flush can still report success with a look-up running.** [backend/realtime_voice.py:1158](/Users/michaelrickards/dev/bh2-BM-3/backend/realtime_voice.py:1158) uses `tools_done` from the initial task snapshot. A look-up arriving during the transcription wait or turn drain is missed. An in-memory reproduction returned `{"type":"flushed","ok":true}` while that look-up was still running. Recheck pending tasks before acknowledging success and add coverage for this arrival timing.

The original reader-blocking issue is fixed. No additional regression identified in concurrent socket sends, teardown, ordinary Aria voice, or BM-2 handling.

Verification: **99 existing tests passed**; the additional race reproduction failed. Full `check.sh` not run. No files changed.

**Verdict: CHANGES.**