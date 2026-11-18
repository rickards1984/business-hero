# STAB-1 — Codex code review 2 (verbatim)

Commit 279016e. Model gpt-6-astra, read-only sandbox, 18 Nov 2026.

---

APPROVE

1. **Resolved — original severity High.** `backend/main.py:1369,1422,2501` forwards the request session through `/v1/me` and `_assert_ai_access`. Both AI callers await the complete gate in a thread (`2463,2529`). Chat’s three initial lookups are also offloaded (`backend/assistant_chat.py:768,772,796`). The original failure scenario—these lookups blocking the event loop during pool exhaustion—is addressed. Against `origin/main`, error behaviour is preserved: `/v1/me` tolerates two-argument `NO_BUSINESS`, maps other `ValueError`s to **400**; the AI gate maps lookup `ValueError`s to **404**, retaining the admin exemption and feature enforcement.

2. **Resolved — original severity Medium.** `backend/tests/test_stab1_connections.py:86,140` now starts with `SELECT 1`, holding the request connection. Mentally removing forwarding at `backend/dependencies.py:66` makes the standalone lookup acquire a second connection while the first remains checked out: peak becomes **2**, failing both parametrized tests’ `peak == 1` assertion. The previous false-negative scenario is closed.

3. **Resolved — original severity Medium; deployment verification remains limited.** `backend/db.py:48,60` caps the combined pool at **30 per process**. Executed in-memory checks confirmed `30+10`, `40+40`, and `25+6` fall back to `10+10`; `15+15` remains valid. The assertions at `backend/tests/test_stab1_connections.py:348` pass for both launch files. They establish only that those files omit `--workers`; they cannot prove live worker/replica counts. Additional processes would still multiply the budget.

4. **Non-blocking, pre-existing — High under pool exhaustion.** `backend/assistant_chat.py:813,821,824,828` still invokes synchronous database helpers on the event loop, while the chat route retains its request session. A subsequent checkout can therefore still stall other requests. This is unchanged from `origin/main` and outside the three newly offloaded lookups; approval does **not** establish that the entire chat path is stall-free.

No new blocking behaviour regression found. No files modified. Full pytest/`check.sh` was not run; verification comprised source comparison, mental mutation analysis, and executed in-memory pool/configuration checks.