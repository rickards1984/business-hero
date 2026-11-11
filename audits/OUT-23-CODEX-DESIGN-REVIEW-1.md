# OUT-23 Part A — Codex DESIGN review 1 (verbatim)

Reviewed docs/OUT-23-TICKET.md (design only, no code) on 084d3d8.

Read-only review completed against North Star P8/P9: trust, correctness and tenant isolation. No files modified, committed or pushed. Tests and `check.sh` were not run; these are design findings grounded in the current implementation.

1. **P1 — The expiry definition contradicts the promised deletion of unsent contacts.**  
   **Where:** [A1, A5 and A9](docs/OUT-23-TICKET.md); `outreach_research._store`, `outreach_manage.qualified`.

   A contact drained on day 24 gets an enrolment and approval card. If the owner never approves it, it is permanently outside A5—even after day 28 or its notice deadline. `_store` gives it **365-day retention**. Its prospect, evidence, enrolment and card payload remain. A9 explicitly defers this case, although decision 1 promises deletion of contacts still unsent at day 28.

   **Change:** Make expiry depend on whether notice/first contact was actually provided, not whether an enrolment exists. Include cancellation and deletion/redaction of dependent cards, tokens, evidence and enrolments, with explicit handling of claimed/unknown messages. Make the relevant OUT-13 retention work a prerequisite rather than assuming `_unstore`, designed for an uncommitted insertion, is a complete erasure operation.

2. **P1 — Weekday-only expiry cannot deliver “day 28 exactly”.**  
   **Where:** A4–A5; `run_due` scheduling pattern.

   A prospect captured Friday afternoon reaches day 28 after Friday’s 06:00 drain. It survives until Monday morning—over 30 days after collection. A crash after a separately committed day-claim could also defer cleanup. Copying `run_due`’s `pause_all = false` selection would leave paused businesses uncleared indefinitely.

   **Change:** Separate expiry from research and campaign draining. Run it every day, independently of research, outreach pause, entitlement and mailbox readiness. Define a realistic cleanup interval, enforce expiry immediately in read/enrol/send paths, and make cleanup retryable after failure. Commit its completion marker with the cleanup, not before it.

3. **P1 — The notice guarantee is stronger than the existing send checks support.**  
   **Where:** Decision 1; `outreach_research.NOTICE_WITHIN`; `outreach_send.prepare_claim` and `dispatch`.

   `NOTICE_WITHIN` is 30 days, whereas the legal deadline is one calendar month; these differ around February. Separately, claim checks notice and retention, but `dispatch` does not recheck either. A claim immediately before expiry followed by a lock/process delay can reach transport after expiry. The five-day admission margin does not prevent an owner approving an old card near its deadline.

   **Change:** Define the calendar-month notice deadline and the earlier operational retention cutoff explicitly. Recheck both at the final pre-transport decision using a fresh clock. Test claim-before/deadline-after interleavings. Also remove the assertion that deletion alone means Article 14 was “always met”: ICO guidance requires timely privacy information, subject to applicable exceptions; deletion is not evidence that notice was supplied. See the [ICO guidance](https://ico.org.uk/media/for-organisations/guide-to-the-general-data-protection-regulation-gdpr-1-1.pdf).

4. **P1 — Brand-wide bank room reopens OUT-19 D’s unrelated-audience finding.**  
   **Where:** A2–A3; `capacity(..., audience_hash)`, `_take_place`; OUT-19 D review 1, finding 2.

   A brand has a healthy campaign for audience A and an approved research audience B with no matching campaign. The proposed brand target is positive. Research B can therefore spend and fill the entire bank, although the drain correctly refuses to place those contacts in A. Previously, audience-specific capacity prevented this.

   `_take_place` also returns `None` for both **no free place** and **failed qualification**. Treating either outcome as permission to bank a contact revives the qualification-refusal problem from OUT-19 D review 2.

   **Change:** Require a viable matching brand/audience destination before spending and again before persistence. Distinguish temporary lack of capacity from qualification failure. Retain explicitly classified review records only under a defined review policy.

5. **P1 — The bank formula does not allocate shared-inbox capacity across brands.**  
   **Where:** A2 and A6; `metering._cold_limits`; OUT-19 D reviews 1 and 3.

   Two brands sharing one five-email inbox can each calculate `daily_cap = 5` and target 25 contacts: 50 contacts against approximately 25 first-email places over 15 weekdays at the assumed steady-state rate. With more brands, the overstatement grows. Counting the mailbox once *within each brand* does not allocate it once across brands.

   The campaign summation is also ambiguous: two campaigns capped at three on one five-capacity mailbox should contribute five, not six or three.

   **Change:** Specify shared-mailbox allocation across brands and audiences. Within a mailbox, aggregate campaign capacity then bound it by mailbox capacity; apply brand limits as an additional constraint. Preserve accounting for competing campaigns regardless of their current status.

6. **P1 — `capacity()["places"]` is not a globally bounded allocation.**  
   **Where:** A4; `outreach_research.capacity`, especially the final `room` calculation.

   With two 20-capacity inboxes and a brand cap of 20, `places` can contain 20 places for each campaign while `room` is only 20. A drain following “each ready campaign place” can enrol 40 contacts. Existing research avoids this through its separate `left = room["room"]` counter.

   **Change:** Give draining an explicit remaining brand/mailbox/campaign budget and decrement it atomically for every enrolment. Separate send-placement capacity from the daily research quota: draining existing contacts must not be limited by how many contacts research collected today. Test multiple inboxes, shared brands, paused campaigns’ existing usage and reserved/unknown sends.

7. **P1 — The exclusion list has an incorrect privacy premise and incomplete race semantics.**  
   **Where:** A5; `_held`, `_verify`, `_run`’s final persistence checks.

   A domain identifying a sole trader can be personal data. This matters particularly because banked `review` records include organisations whose corporate status could not be established. The blanket statement “a company domain alone is not personal data” is unsafe; [ICO guidance explicitly distinguishes sole-trader data](https://ico.org.uk/media/for-organisations/training/4022200/module-2-definitions.pdf).

   There is also a concrete race: research verifies a candidate, expiry deletes the existing prospect and records its domain, then research reacquires the lock. Today’s `_held` sees only remaining prospects. Unless the final persistence check reads the exclusion list, the deleted person can immediately return. Prompt exclusions alone cannot enforce this. After 90 days, automatic recollection is permitted again by the proposed policy.

   **Change:** Define a tenant-wide, normalized exclusion check at verification **and under the store lock**, for eligible and review candidates. Document purpose, retention, pruning and subject-rights handling; tenant-keyed digests reduce exposure but are not anonymous data. Keep permanent opt-out suppression distinct from temporary expiry exclusion, and explicitly decide whether repeated 90-day recollection is acceptable.

8. **P1 — The new drain does not specify enough authority or transaction boundaries.**  
   **Where:** A4; `_still_allowed`, `qualified`, `run_due`, `outreach_manage.start`.

   `qualified()` checks the prospect and audience; it does **not** check business entitlement, setup completion, brand payment, global pause or campaign readiness. Research currently supplies other checks around it. A drain independent of research must replace those checks deliberately, otherwise it can enrol contacts for a paused or unavailable business.

   A business lock is sufficient only if candidate selection, rechecking “no enrolment/message”, capacity allocation and insertion happen within that lock. A committed day-claim alone does not protect later work. `prepare_due_cards` performs rollbacks and proposal commits, so it cannot sit inside the promised single transaction.

   **Change:** Specify separate phases: retryable expiry; locked, fully revalidated drain; post-commit card preparation. Preserve global pause while allowing the research toggle to be off. Define ordering so the existing bank drains before new research takes today’s places. Add PostgreSQL interleaving tests against manual enrolment, approval, suppression, unsubscribe and expiry.

9. **P2 — The pilot optimization leaves the scheduled quadratic scan and a duplicate-card race.**  
   **Where:** A8; `outreach_research._prepare_cards`; `outreach_autopilot._due_enrolment`; `aria_actions.propose`.

   Narrowing `outreach_manage.prepare` is correct, but the new drain calls `_prepare_cards`, which loads **all open outreach cards once per prospect**. It checks for an existing card, rolls back, and later proposes without a shared deduplication lock. Concurrent manual preparation or the other scheduled preparation pass can both observe no card and insert one. The proposed non-unique index does not prevent that.

   **Change:** Reuse one indexed, business-locked “find or create current card” operation across manual and scheduled preparation. Preserve the full-set semantics where callers genuinely need all enrolment IDs, or replace those queries with appropriate joins/`NOT EXISTS`; do not globally narrow `send.rows`. Test concurrent preparation and query growth before lifting the pilot.

10. **P2 — “Three weeks” and “healthy capacity” need qualification.**  
    **Where:** A2, A3 and A7; `mailbox_daily_cap`, `reserve_outreach_usage`.

    `5 × daily_cap` is a reasonable **steady-state heuristic**, assuming three delivered sequence emails per prospect. At startup, a five-email inbox can consume 25 first contacts in five sending days before follow-ups dominate. Replies and early exits change that ratio. Review-only contacts cannot drain at all, yet currently count toward the same target.

    Furthermore, `mailbox_daily_cap` deliberately omits same-day health freshness. Sending additionally checks fresh health, payment, monthly allowance and the total mailbox ceiling including replies. Research runs from 06:00; health checks start from 07:00.

    **Change:** Label the target as an estimated steady-state buffer, distinguish review-held from sendable stock, and expose blockers. Do not equate nominal warm-up capacity with permission to send today. If freshness becomes an admission condition, move draining after health checks or allow retries; a once-daily 06:00 refusal must not strand the bank.

11. **P2 — “The spend cap still binds” contradicts the approved OUT-19 Option B exception.**  
    **Where:** A3 and its tests; [OUT-19 decision H](docs/OUT-19-TICKET.md), `_run`, `outreach_allowance.may_research`.

    Raising collection to 40 does not itself bypass reservations: the existing owner budget and brand allowance include research holds, and searches remain serialized per business. However, OUT-19 explicitly permits an actual search cost to exceed its realistic reservation, records the overrun, and stops at the next reservation. OUT-23’s unconditional cap language and test requirement imply a stricter guarantee.

    **Change:** Preserve and name that approved exception. Test allowance exhaustion, concurrent drafting holds, provider failover, uncertain charges, and budget reduction during research. Keep the research maximum separate from provider attempt/token/tool limits; filling a larger bank must not silently expand those limits.

The **proposed expression index itself is appropriate** for the stated tenant-scoped lookup, provided the query retains the literal `action_type='send_outreach'`, open-status filter and matching extraction expression. PostgreSQL can use that partial predicate; a small table may legitimately favour a sequential scan, so test representative cardinality rather than requiring index selection unconditionally. [PostgreSQL documentation](https://www.postgresql.org/docs/17/indexes-partial.html). SQLite supports `->>` from 3.38, but SQLite tests cannot prove row-lock behaviour. [SQLite documentation](https://www.sqlite.org/json1.html). Add bounded lock/statement timeouts to the migration runbook: a small table does not guarantee a short wait behind another transaction.

Removing banked contacts from **today’s send usage** is conceptually sound. The blocking issue is replacing the safeguards established by OUT-19 D with explicit bank allocation, qualification, concurrency and expiry guarantees—not retaining the old accounting unchanged.

VERDICT: CHANGES REQUESTED