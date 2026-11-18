# STAB-1 — Codex code review 3 (verbatim)

Commit 689c095. Model gpt-6-astra, read-only sandbox, 18 Nov 2026.

---

APPROVE

1. **Low — test coverage limitation:** `backend/tests/test_stab1_connections.py:365` and `backend/tests/test_profit_guard.py:355`. The heartbeat test meaningfully detects a blocking first OpenAI call and verifies worker attribution. However, its fake client bypasses `wrap_create`; the updated guard checks source strings. **Failure scenario:** broken cost recording, or blocking in later tool rounds/final completion, could pass both tests. Neither proves ledger recording.

2. **No defect found — attribution:** `backend/assistant_chat.py:601`, `backend/services/profit_guard.py:419,498`. `_complete` keeps attribution active through SDK execution and recording. `asyncio.to_thread` copies caller context, including `_accounted` and `ai_costs._collecting`; existing suppression semantics survive. The chat route sets neither suppression context. **Failure scenario checked:** costs becoming unattributed or double-counted because of the thread boundary; no regression found.

3. **No defect found — behaviour and thread safety:** `backend/assistant_chat.py:823–945`. Awaited operations preserve history loading → user save → model/tool rounds → assistant save. Both OpenAI exception paths retain their previous handling. `_execute_tool_async` remains awaited outside chat attribution. The client and messages are request-local, and each worker finishes before subsequent use or mutation. **Failure scenario checked:** concurrent client access, messages changing during serialization, or saving the reply before tools finish; none introduced.

Verification: an isolated execution of the actual attribution context managers and SDK wrapper confirmed inherited context and parent-context restoration. Full pytest/`check.sh` was not run in the read-only sandbox. No files modified.