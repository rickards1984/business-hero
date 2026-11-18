# STAB-1: the app runs out of database connections and freezes

**Tier:** RED: authentication on every request. **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

## What happened (Mike, 18 Nov 2026)

The app was "temperamental". It crashed a couple of times, and then the dashboard took about 4 minutes to load, for both MSC and New Body.

The Railway logs at 16:00:52 UTC:

`sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00`

It was raised in:
- `auth.get_user_business_context` → `is_platform_admin_user`;
- `assistant_chat.get_business_for_user` → `is_platform_admin` (`engine.connect()`).

Just before it, Mike had approved 5 outreach emails (15:56–15:58). Each approval kept its connection for about 90 seconds while Gmail was called.

## Cause

1. **Two connections per request.** The auth dependencies hold the request session's connection and then call `get_business_for_user`. That function opens a **second** connection (`engine.connect()`) for each of up to three queries. The dashboard fires about 10 requests at once, which means about 20 connections against a pool of 15.
2. **The database work runs on the event loop.** Every auth dependency is `async def` but calls the database synchronously. When the pool is empty, the 30-second wait for a connection blocks the loop, so **every** request stalls, not only the one waiting. That stall is the "crash" and the 4-minute load.
3. **The pool is the SQLAlchemy default:** 5 + 10, with a 30-second wait. Production connects directly (port 5432, no pooler), and that connection allows about 60.

## Fix

- **F1. One connection.**
  - `assistant_chat.is_platform_admin`, `get_business_by_id` and `get_business_for_user` take an optional `session` and run on it.
  - Every auth dependency passes its session.
  - Callers that pass none are unchanged.
- **F2. Off the event loop.** The database part of each dependency below runs in `run_in_threadpool`:
  - `get_user_business_context`
  - `get_current_user_business`
  - `get_current_user_and_business`
  - `get_user_auth_context`
  - `get_platform_admin_context`
  - `require_feature`
  - `get_current_business` (API key)

  The token check (`verify_supabase_token`) stays async: it is already non-blocking `httpx`.
- **F2b. Endpoints that do their own lookup** (Codex code review 1, finding 1):
  - `/v1/me`, the first request of every page, now uses the request's own connection and runs off the loop;
  - chat and TTS (`_assert_ai_access`) do the same;
  - Aria chat's own lookups in `process_chat_message` (`is_platform_admin`, `resolve_conversation` and `get_business_for_user`) now run in `asyncio.to_thread`.

  The realtime voice path already ran its lookup in a thread.
- **F2c. Aria's OpenAI call** (Codex code review 2, finding 4).
  - **What was wrong:** `process_chat_message` called the synchronous OpenAI client on the event loop, for both the tool rounds and the final reply. While Aria answered, often for tens of seconds, every request in the app waited.
  - **The fix:**
    - The call now runs in `asyncio.to_thread`, through `_complete`. That function enters `profit_guard.attributed` inside the thread, so the cost is still charged to the business as `chat`.
    - The chat's database helpers also run in threads: `create_conversation`, `load_conversation_history`, `save_message` (both calls) and `get_user_display_name`.
- **F3. Pool size.** `db.pool_options()` sets 10 + 10, with a 10-second wait, `pre_ping` and recycling every 1800 seconds.
  - `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` and `DB_POOL_TIMEOUT` tune it without a release.
  - An unparseable or out-of-range value falls back to the default.
  - A size plus overflow above `POOL_BUDGET`, which is **30 per process**, also falls back to the default (review 1, finding 3).
  - Production runs one uvicorn process. A test fails if the Procfile or `railway.json` gains `--workers`, because each process has its own pool.
  - Supabase allows about 60 connections on Micro, in both direct and session mode.

**Behaviour is unchanged:**
- membership checks;
- the platform-admin exemption;
- DECISION 3's `enforce_access`;
- the error codes (403, 404, 400).

## Out of scope (follow-ups)

- **STAB-2:** the approval endpoint holds its connection across the Gmail calls, for about 90 seconds per approval. Releasing the connection across the provider call touches the send fencing (RED, outreach), so it is a separate ticket.
- **Caching the Supabase token check.** Each request calls `auth/v1/user`. A cache would let a revoked token keep working for the cache's lifetime, so it needs its own decision.
- **Polling frequency** on the dashboard.

## Acceptance

- [x] Each auth dependency, `/v1/me` and the AI gate hold at most one connection at a time (`test_stab1_connections.py`, real `QueuePool` checkout counting).
  - Every test starts from a session that already holds its connection (review 1, finding 2).
  - Nine mutations, each removing one fix, are each caught.
- [x] A slow database does not stall the event loop in any of the seven dependencies: a heartbeat test, mutation-checked.
- [x] A non-member is still refused (403).
- [x] Pool defaults and overrides are tested.
- [x] `./check.sh` passes.
- [ ] Codex review preserved in `audits/`.
