# OUT-23 Part B (Hunter.io) — Codex code review 1 (verbatim)

Commit reviewed: ac78ecc.

---

1. **HIGH — Validation errors can echo the Hunter key.** [backend/outreach_setup_api.py:235](/Users/michaelrickards/dev/bh2-HUNTER/backend/outreach_setup_api.py:235)  
   `HunterKey` uses ordinary Pydantic validation. An oversized string or wrong-type value fails before the sanitised service checks; FastAPI’s default 422 response includes the submitted `input`. I reproduced this using the repository’s model and installed exception handler with a synthetic secret. **Fix:** sanitise validation errors for this endpoint, including malformed bodies and extra fields. Add HTTP-level tests asserting no submitted secret appears in responses.

2. **HIGH — Verifier polling bypasses reservations and permission checks.** [backend/services/outreach_hunter.py:722](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_hunter.py:722)  
   Each 202 triggers another HTTP request without renewing the claim, checking disconnect/pause, or reserving credits. Earlier responses’ credit headers are discarded. A synthetic execution confirmed three requests, one gate, one reservation and settlement using only the final response. The existing polling test explicitly expects that single charge despite its fake returning charge headers on every response. **Fix:** gate, reserve and settle each request, including polls; test mid-poll disconnect and cumulative charges.

3. **HIGH — Settled spending disappears from the cached pool-balance check.** [backend/services/outreach_hunter.py:498](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_hunter.py:498)  
   `reserve` subtracts only outstanding reservations from cached availability. Settlement removes a reservation from that calculation without reducing cached availability. With one credit available, a one-credit search settles and another search is admitted against the same cached credit. This continues until refresh or a provider refusal. **Fix:** account for consumption since the account snapshot, with generation-safe reconciliation that avoids double counting after refresh. Test sequential settled calls as well as concurrent reservations.

4. **MEDIUM — Unit mismatches never trigger the required account refresh.** [backend/services/outreach_hunter.py:531](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_hunter.py:531)  
   Settlement correctly converts the reported unit and takes the larger credit amount, but only logs the mismatch. Neither settlement nor its caller refreshes `/account`. Subsequent reservations therefore continue using the account model that has just proved inconsistent. The missing/past-reset 429 path likewise omits its specified refresh. **Fix:** propagate the refresh requirement and refresh outside the transaction, conditional on the connection generation; test the resulting account state and next reservation.

5. **HIGH — The enrichment deadline does not bound running network operations.** [backend/services/outreach_research.py:892](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_research.py:892), [backend/services/outreach_hunter.py:84](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_hunter.py:84)  
   `_bounded` checks time only before MX and Companies House calls; Companies House can then perform several requests with independent ten-second timeouts. Hunter’s HTTPX timeout is an inactivity timeout, not a total deadline, and its response is fully buffered. A slowly streaming response can exceed 180 seconds substantially. Publication reads also retain their original per-read timeout as the deadline approaches. **Fix:** enforce the remaining monotonic budget throughout DNS, requests and body reads. The current slow-site test only checks call count—it does not prove execution stops at the deadline.

6. **HIGH — Paid-work limits reset between attempts, and the search-count bound is absent.** [backend/services/outreach_research.py:911](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_research.py:911), [backend/services/outreach_research.py:1245](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_research.py:1245)  
   Every `_enrich` invocation creates a new 60-call/180-second budget and fresh domain set. `_run` can invoke it three times. Failed domains can therefore be charged repeatedly, and one run can exceed the approved limits. There is also no `2 × room` search limit: one remaining place can permit many unsuccessful searches. **Fix:** maintain budget, attempted domains and search allowance across the entire run. Add multi-attempt tests with repeated and unsuccessful leads.

7. **MEDIUM — Gatekeeper quota filtering happens after paid verification.** [backend/services/outreach_hunter.py:760](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_hunter.py:760), [backend/services/outreach_research.py:930](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_research.py:930)  
   Candidate filtering checks suppression and erasure but never the gatekeeper quota. When today’s 20 gatekeeper places are full, Hunter can fetch and verify another gatekeeper, return it as the first usable person, then discard it at storage. This spends avoidable credits and can prevent consideration of another usable candidate. **Fix:** filter by contact type and remaining gatekeeper allowance before publication fetches and verification, including pending contacts; retain the store-time recheck.

Read-only review; nothing modified, committed or pushed. Ran two isolated, in-memory reproductions. Did not run `check.sh` or database suites because they write files or database state. Serves security, correctness and tenant isolation.

VERDICT: CHANGES REQUESTED