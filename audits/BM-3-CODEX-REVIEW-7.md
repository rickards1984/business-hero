1. **P2 resolved — backend/realtime_voice.py:1161.** Flush rechecks `pending_tools` when constructing the reply, covering look-ups started during either wait. No regression found within scope.

104 targeted tests passed. The new regression test fails when the recheck is removed in memory. Full `check.sh` not run; no files changed, committed or pushed.

**Verdict: APPROVE.**