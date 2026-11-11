# OUT-23 Part B (Hunter.io) — Codex design review 2 (verbatim)

Commit reviewed: 29b3283 (design revision 2).

---

Read-only review completed. Nothing modified, committed or pushed; tests not run. Review serves correctness, security and tenant isolation.

1. **P1 — R2.5: Disconnect/reconnect can reuse a generation.**  
   A run starts with generation 1; disconnect deletes the row; reconnect creates generation 1 again. The old run passes the equality check and can store old results. A connect request awaiting `/account` can also finish after disconnect and recreate the connection. **Fix:** use a durable connection epoch that survives deletion, or a unique incarnation token with conditional writes. Apply it to connect completion, account refresh, error-state updates and storage. Test both races.

2. **P1 — R2.4/R2.5/R2.11: The reservation sweep cannot operate on the proposed storage.**  
   `usage_meters` stores monthly aggregates, not individual reservation identities, ages or settlement states. One crashed reservation and one fresh reservation share a row; the sweep cannot distinguish them or safely handle a late settlement. Migration 042 only adds the account table. **Fix:** specify a minimal reservation ledger, or charge conservatively immediately and remove the sweep. Define idempotent settlement, original-period accounting across month boundaries, inclusion of outstanding reservations in caps, and treatment of late responses. Include the resulting storage in migration 042 and the persistence allowlist.

3. **P1 — R2.4/R2.6: Reservation units conflate provider quotas with the brand cap.**  
   Reserving `0.5` in a `verification` pool under-reserves a separate-pool verification, which costs one verification request. The brand’s equivalent-credit cap can still count that as 0.5, but these are distinct quantities. **Fix:** define native pool reservations and explicit conversion to brand-cap credits. Infer the expected pool before calling, including when error headers are absent; validate settlement headers against it. Hunter documents these different units in its [API reference](https://hunter.io/api-documentation/v2#account).

4. **P1 — R2.4/R2.5/R2.12: The new writers have no complete lock protocol.**  
   Only reservation creation explicitly takes the business lock. Settlement, sweeping, connect/disconnect and cache/error updates have no specified ordering. A sweep locking a meter before the business can deadlock against research; a helper invoking `outreach_setup._authority` after taking locks silently rolls them back. **Fix:** specify one order beginning with `business_settings → outreach_settings`, then a consistent position for provider accounts, reservations and meters. Require every writer to follow it, prohibit rollback-owning helpers inside the critical section, and keep network calls outside transactions.

5. **P1 — R2.4: The 120-second budget does not bound claim inactivity.**  
   “Hunter time” excludes publication fetches, corporate checks and ordinary web verification. Existing `fetch_page` allows multiple redirects and uses per-operation timeouts, so the run can exceed the 15-minute claim despite consuming little Hunter time. A takeover can then repeat paid work; an in-memory domain set cannot coordinate old and new owners. **Fix:** define a monotonic wall-clock deadline covering all enrichment work, constrain each operation to the remaining budget, and explicitly renew/check ownership before storage. Define takeover handling for outstanding reservations and test slow publication fetches, not just slow Hunter calls.

6. **P1 — R2.2: Verifier-path date validation remains unspecified.**  
   Path (b) accepts the top-level status and flags without requiring a valid, non-future, sufficiently recent `data.verification.date` or matching nested status. The later instruction to store “the verifier’s date” does not establish acceptance criteria. A contradictory response can therefore pass acquisition and fail the real send check—or create incorrectly extended evidence. **Fix:** explicitly validate the nested verification object, date, status and expiry before accepting the person, preserving `verification_subject_email_key`. Hunter documents that verification can be cached or absent in its [Verifier contract](https://hunter.io/api-documentation/v2#email-verifier). Existing `prepare_claim` accepts Hunter evidence without a source-type change when those fields are correctly populated.

7. **P1 — R2.7: Latest verification is still not immutable acquisition provenance.**  
   Selecting `email_verification ORDER BY fetched_at DESC, id DESC` fixes ties but lets a later web verification replace Hunter attribution and its publication URL. It can also bypass R2.8 if Hunter origin is inferred from that selected row. **Fix:** identify an immutable acquisition record independently of subsequent validity evidence, or require later verification records to preserve the original acquisition fields. Test Hunter acquisition followed by web re-verification.

8. **P1 — R2.8: The existing audience flow cannot persist the proposed source approval.**  
   `draft_audience` inserts `sources=[]` and omits sources from the drafting context; `approve_audience` never updates sources. Reusing that flow leaves every re-approved audience ineligible. It also retains earlier approved versions, so “current approved assessment” needs a precise selection rule. **Fix:** specify validated source input, inclusion in the assessment drafting context, persisted approved sources, and which compliance version acquisition and first-send checks use. Preserve the audience-hash/campaign relationship explicitly.

9. **P1 — R2.7/R2.8: First-send notice enforcement conflicts with unconditional claimed-job dispatch.**  
   R2.7 says claimed jobs dispatch unchanged; R2.8 requires refusal after a notice mismatch. A notice can change after `prepare_claim` commits but before `dispatch`, whose existing final checks do not inspect the notice. **Fix:** distinguish immutable payloads from permission to dispatch. Check the current notice binding under the business lock at claim and again at the final dispatch gate for never-contacted Hunter prospects. Refuse through the existing blocked-dispatch path without rewriting the payload. Test a notice change between claim and dispatch.

VERDICT: CHANGES REQUESTED