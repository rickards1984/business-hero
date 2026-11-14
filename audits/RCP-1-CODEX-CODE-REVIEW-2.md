# RCP-1 — Codex code review 2 (verbatim)

- **Reviewer:** Codex CLI (`codex exec --sandbox read-only`), model `gpt-6-astra`
- **Session:** `01a1d6b9-a5e0-73e3-bd29-b93031bdee1c`, 87,555 tokens
- **Reviewed:** the working tree on `ticket/RCP-1-build` after the review-1 fixes, 13 Nov 2026
- **Verdict:** CHANGES REQUESTED (1 blocker, 5 should-fix). Each one is answered in review 3's prompt and the PR.

---

1. **BLOCKER — Final assignment can still overwrite a number assigned concurrently.**  
   `backend/services/receptionist_numbers.py:805` checks the current assignment, then `:371` updates it unconditionally. An admin/onboarding assignment committed between those operations is overwritten. The request-row fence does not protect `receptionist_configs`. A controlled in-memory interleaving reproduced the replacement and a resulting `live` request.  
   **Fix:** Serialize assignment changes using a shared business-level lock across all assignment paths, or use an atomic conditional assignment that refuses replacement. Add a PostgreSQL test pausing completion between its check and write. The existing “given in the meantime” test assigns **before Retry**, so misses this race.

2. **SHOULD-FIX — A price increase permanently strands the request in `buying`.**  
   `backend/services/receptionist_numbers.py:740–744` refuses the increased price but calls `_note` without resetting the state. Check (`:567`), Decline (`:668`) and Cancel (`:478`) reject `buying`; Retry repeats the same price refusal. I reproduced the instruction “run Check again” followed by Check returning “This request is buying.”  
   **Fix:** Provide a fenced reconciliation/recovery transition. Once no outstanding purchase remains possible, return to a state where Check can refresh the price and require confirmation again. Extend the price-rise test through successful recovery.

3. **SHOULD-FIX — Changed eligibility prevents reconciliation of an already purchased number.**  
   `backend/services/receptionist_numbers.py:732–748` performs spending checks **before** `find_tagged`. After a timeout following purchase, suspension, another assigned number, a rejected bundle or an increased price can prevent adoption indefinitely. I reproduced suspension leaving one number held by fake Twilio, state `buying`, no recorded cost and no release-review flag. Retry made no Twilio reconciliation call.  
   **Fix:** Under the fence, reconcile existing tagged purchases first and persist their ownership/cost regardless of current purchase eligibility. Apply spending checks before a **new** purchase and entitlement checks before assignment. Test timeout-after-purchase combined with each changed prerequisite.

4. **SHOULD-FIX — Adoption in a later month loses the original month’s cost.**  
   `backend/services/receptionist_numbers.py:718–724` sets `bought_at` to the retry time; `:865` records only that month. A November purchase that times out and is adopted in December is recorded as a December acquisition. I reproduced an empty November ledger and a December-only 98p entry. This leaves review-1 finding 4 partially unresolved.  
   **Fix:** Preserve or recover the actual acquisition timestamp and reconcile affected billing periods without including later acquisitions in earlier totals. Add a month-boundary adoption test.

5. **SHOULD-FIX — Twilio operations block the server’s event loop.**  
   `backend/receptionist_api.py:1323`, `:1338` and `:1353` directly call synchronous services from `async def` endpoints. Those services perform multiple synchronous Twilio requests with 30-second timeouts. The configured single-worker server also handles receptionist audio streams, so Check/Approve/Retry can stall active calls. A synthetic 250ms provider delay delayed a concurrent 10ms heartbeat to 255ms.  
   **Fix:** Run the synchronous workflow in FastAPI’s thread pool, with session ownership kept within that execution context. Add a responsiveness test with a blocked fake provider.

6. **SHOULD-FIX — New request data has no tenant-scoped Aria read tool.**  
   `backend/services/receptionist_numbers.py:403` stores request/provisioning data, but the existing tool at `backend/assistant_tools.py:3090` exposes only usage. Aria cannot answer whether the owner’s requested number is ready or why setup is pending. This conflicts with `AGENTS.md` North Star rule 3.  
   **Fix:** Add a tenant-scoped read tool exposing owner-safe request status and the assigned number, with cross-tenant isolation tests.

The other claimed changes are present: purchase fencing, locking before the cost total, candidate/area restrictions, onboarding’s uniqueness-error translation, release-review flags for recorded owned numbers, Retry confirmation, email dispatch and polling. I found no intervening commit in the successful `_fence` → `_save_bought` path, or a demonstrated deadlock cycle involving the running-costs lock. The £50 deferral and revised acceptance procedure are documented as described.

**Verification:** All 75 service tests passed with their SQLite databases redirected to memory and file-writing caches disabled. Additional in-memory reproductions exposed the failures above. I inspected but did not run the PostgreSQL suite or independently verify its mutation-test claim. `check.sh` was not run because it writes files. No files were modified, committed or pushed.

VERDICT: CHANGES REQUESTED