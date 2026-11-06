1. **Resolved P2 — `backend/realtime_voice.py:1045`.** One locked snapshot includes pending, failed and saving entries, closing the premature-return race.
2. **No new regressions found — `backend/realtime_voice.py:1017–1051`.** Locked claims prevent concurrent double saves; retry sleep prevents busy-looping; the single deadline remains intact, subject to the previously accepted in-flight database-call limitation.

All **4 targeted tests passed**. No files changed; no commit or push.

**Verdict: APPROVE.**