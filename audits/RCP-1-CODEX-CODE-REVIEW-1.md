# RCP-1 — Codex code review 1 (verbatim)

- **Reviewer:** Codex CLI (`codex exec --sandbox read-only`), model `gpt-6-astra`
- **Session:** `01a1d6ad-962e-7ea2-aa05-c08e188f10ba`, 88,345 tokens
- **Reviewed:** the working tree on `ticket/RCP-1-build` over `origin/main` 92f71d6, 13 Nov 2026
- **Verdict:** CHANGES REQUESTED (3 blockers, 9 should-fix). Each one is answered in review 2's prompt and the PR.

---

1. **BLOCKER — Retry bypasses entitlement and existing-number checks.**  
   `backend/services/receptionist_numbers.py:532, 615, 643`  
   After an unsuccessful purchase, suspend the business—or assign it a number through the existing admin endpoint—then retry. Retry can buy a number and overwrite the business’s current assignment without calling `_check_spendable`. I reproduced a suspended business reaching `live` with a new purchase using an in-memory database and fake Twilio.  
   **Fix:** Revalidate DECISION 3 entitlement, feature access, current assignment and regulatory approval immediately before every possible purchase, including retries. Serialize assignment changes for that business and refuse unexpected replacement. Add retry-specific regression tests.

2. **BLOCKER — Claim tokens fence database writes, but do not fence purchases.**  
   `backend/services/receptionist_numbers.py:599–628`; `backend/tests/test_receptionist_numbers.py:506`  
   `_complete` never checks that its token still owns the request before calling Twilio. A worker paused after claiming can resume after another attempt resets the request and Mike declines it, then purchase anyway. `_save_bought` rejects the stale token only **after spending**, leaving an unrecorded purchase. I reproduced that outcome: purchase followed by 409 on a declined request. The stale-worker test exercises only `_save_bought`, so it misses this failure.  
   **Fix:** Serialize purchase execution with takeover-safe ownership across the external operation; verify token and state before spending. Elapsed time alone must not authorize replacement of a potentially executing purchase. Test a paused worker resuming after takeover and decline.

3. **BLOCKER — Concurrent approvals can understate the running-cost total.**  
   `backend/services/receptionist_numbers.py:668–670`; `backend/services/running_costs.py:122`  
   Two businesses complete concurrently. Each transaction sees its own newly live request but not the other’s uncommitted request, and calculates an incomplete sum. `set_item` subsequently serializes the writes, but the second writer still writes its previously calculated, incomplete total.  
   **Fix:** Acquire the shared transaction lock **before** calculating the total, then calculate and write under that lock. Add a PostgreSQL test with two different businesses completing concurrently and assert the exact combined cost.

4. **SHOULD-FIX — Costs start at “live”, rather than purchase, and are not attributed to businesses.**  
   `backend/services/receptionist_numbers.py:627, 651, 661–670`  
   A purchased number with a broken webhook incurs charges while `bought`, but contributes nothing to the ledger. If bought in November and repaired in December, November’s cost is never recorded. The single platform-wide line also does not provide the business attribution required by R6.  
   **Fix:** Persist acquisition time and per-business recurring cost when purchase is confirmed or adopted. Include all unreleased purchased numbers, regardless of configuration status, and reconcile the appropriate billing months. Test month rollover and indefinitely failed configuration.

5. **SHOULD-FIX — The recorded price and £5 ceiling are based on an unverified input.**  
   `backend/services/receptionist_numbers.py:480–489`; `frontend/client/src/components/AdminNumberRequests.tsx:154`  
   Leaving the optional cost blank records £1 regardless of Twilio’s actual price. Entering a value below £5 also passes even if the actual recurring charge exceeds the agreed ceiling. This makes both cost reporting and the spending limit unreliable.  
   **Fix:** Require a verified price and currency conversion policy before confirmation, display that price in the dialog, and enforce the ceiling against it. Remove the silent £1 fallback.

6. **SHOULD-FIX — UK search is unanchored, and “local” is not enforced at purchase.**  
   `backend/services/receptionist_numbers.py:153–155, 476, 500–517`  
   `contains="44161"` can match those digits elsewhere in a number. Only ten results are fetched before prefix filtering, so the UI can report no availability despite matching Manchester numbers existing. Twilio documents `+` as the beginning anchor. Also, approval accepts any number matching the broad UK regex, without requiring geographic type, requested area, or membership in the prepared selection. Twilio’s Local resource can include national numbers.  
   **Fix:** Use an anchored `+44…` search, explicitly restrict geographic numbers, and bind approval to a validated prepared candidate. Add tests for misleading substring matches and non-geographic candidates. [Twilio search syntax](https://www.twilio.com/docs/phone-numbers/api/availablephonenumberlocal-resource), [number-type caveat](https://www.twilio.com/docs/phone-numbers/api/availablephonenumber-resource).

7. **SHOULD-FIX — Onboarding’s race still returns 500 instead of the required 409.**  
   `backend/onboarding_api.py:453, 472–489`  
   Two onboarding transactions can both pass `number_taken`; the unique index rejects the second write with an uncaught `IntegrityError`. The index protects routing, but the endpoint fails R1’s explicit error-handling requirement.  
   **Fix:** Catch the relevant uniqueness violation, roll back the transaction, and return a clear 409. Test concurrent onboarding assignments against PostgreSQL.

8. **SHOULD-FIX — R7’s release-review list is absent, and its test does not test R7.**  
   `backend/services/receptionist_numbers.py:406–411`; `backend/tests/test_receptionist_numbers.py:567`; `frontend/client/src/components/AdminNumberRequests.tsx:216–217`  
   When a live business stops paying or loses the feature, nothing identifies its number for release review. Live requests remain in the hidden closed section. The test merely searches source text for deletion/release operations; it passes while the required list is entirely absent.  
   **Fix:** Add an admin release-review view derived from current entitlement and owned-number records. Test suspension and feature removal appearing there, with no automatic release.

9. **SHOULD-FIX — Retry can spend without a confirmation dialog.**  
   `frontend/client/src/components/AdminNumberRequests.tsx:102, 165`; `backend/services/receptionist_numbers.py:615–618`  
   After a timeout **before** purchase, clicking “Retry (never buys twice)” can make the first purchase immediately. The retry UI neither confirms spending nor displays the stored candidate and cost.  
   **Fix:** Distinguish reconciliation-only retry from an action allowed to purchase. Any retry that may spend should show the stored number, verified cost and explicit confirmation.

10. **SHOULD-FIX — The agreed £50 Stripe payment has been deferred without implementing the agreed flow.**  
    `docs/BACKLOG.md:27`; `backend/services/receptionist_numbers.py:343`; `frontend/client/src/components/AdminNumberRequests.tsx:121`  
    Selecting paid setup records a fee and shows “£50 to collect”, but no payment is collected or checked before fulfilment. The ticket explicitly specifies charging through Stripe; moving it to RCP-1b does not satisfy that acceptance.  
    **Fix:** Implement the agreed payment flow with idempotent payment tracking, or obtain and record an explicit scope amendment before treating RCP-1 as complete.

11. **SHOULD-FIX — Owners receive neither the promised completion notification nor live status updates.**  
    `backend/services/receptionist_numbers.py:657–658`; `frontend/client/src/components/ReceptionistNumberRequest.tsx:139–152`  
    Completion only logs and returns to the admin. An owner already viewing the request remains on the old state until remounting the component; there is no polling, completion email or notification dispatch.  
    **Fix:** Add an idempotent completion notification and refresh pending status while the panel is open. Test successful completion and notification retries.

12. **SHOULD-FIX — The specified test-credential acceptance flow cannot pass this validation.**  
    `backend/services/receptionist_numbers.py:49, 500–502`; `docs/RCP-1-TICKET.md:81`  
    The agreed staging test uses `+15005550006`, but approval rejects it as non-UK before reaching Twilio. The fake-client tests do not establish that acceptance flow.  
    **Fix:** Define and implement an isolated staging/test adapter compatible with the documented test-credential capabilities, or explicitly revise the acceptance procedure. Keep production validation strict.

The webhook fetch → correction → second fetch sequence correctly gates assignment on URL and method. I also inspected the installed **Twilio 9.11.0** signatures: the specified list/create arguments and bundle fetch chain exist; `twilio-approved` is a documented status. [Twilio bundle documentation](https://www.twilio.com/docs/phone-numbers/regulatory/api/bundles).

The blanket “all 4xx except 429 mean definitely nothing bought” classification remains insufficiently justified. I did **not** establish a documented IncomingPhoneNumbers 4xx that proves a completed purchase, so I am not presenting that as a confirmed failure. Before approval, use documented rejection codes rather than treating every possible 4xx as permission to reset purchase state; preserve ambiguous outcomes for reconciliation.

Review was read-only. The two targeted reproductions used SQLite memory databases, fake Twilio and stubbed entitlement/cost dependencies. I did not run `check.sh` or the PostgreSQL suite: those write files or database state, contrary to this review’s constraints. No files were modified, committed or pushed.

VERDICT: CHANGES REQUESTED