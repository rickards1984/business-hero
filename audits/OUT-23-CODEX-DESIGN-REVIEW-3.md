# OUT-23 bank — Codex DESIGN review 3 (verbatim)

Reviewed docs/OUT-23-TICKET.md revision 3 (design only).

Read-only review against North Star P8/P9 and correctness. Nothing modified, committed or pushed. Tests and `check.sh` were not run.

Revision 3 resolves the privacy dependencies, but **B4 is not yet a send-admissible allocation**, and the transition to bank-only research leaves scheduling gaps.

| Review 2 finding | Resolved? | Assessment |
|---|---|---|
| 1. Never-contacted prospects retained indefinitely | Yes | OUT-13 owns erasure of definitively unsent records and classified exceptions for uncertain sends. |
| 2. Personal-data copies survive | Yes, within the approved boundary | OUT-13 handles outreach records, tokens, outcomes and summaries. Chats and memory remain outside that boundary by Mike’s decision. |
| 3. Cutoff missing from reads/manual enrolment | Yes | OUT-13 supplies read withholding, browser-clock handling and `qualified()` enforcement. |
| 4. Old 30-day deadlines/follow-up regression | Yes | The effective deadline includes capture plus 28 days; notice already provided exempts follow-ups. |
| 5. Drain budget differs from send admission | Partly | The additional limits are correct, but their composition and existing `capacity()` behaviour remain problematic. Findings 1–2 below. |
| 6. Research takes places before the bank | Yes, for the original issue | Bank-only research removes that competition. Its replacement scheduling still needs finding 3 addressed. |
| 7. Duplicate cards/autopilot authority | Yes | OUT-24 guards actual creation under the business lock. Autopilot selection remains selection-only; `_prepare_cards` skips valid grants. |
| 8. Qualification eliminates review-held collection | Partly | B5 establishes an exception, but its claimed existing quota and promotion workflow do not match the code. Finding 6. |

1. **P1 — B4 cannot reuse the current `capacity()` allocation unchanged.**

   **Where:** B4; [outreach_research.capacity](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_research.py:689), particularly its unplaced-contact accounting and final `room`.

   **Scenario:** At 06:00 research banks 25 contacts for a five-email inbox. `capacity()` counts contacts captured today without enrolments against inbox, campaign and pilot places. At 07:00 it therefore reports no places, although the send path would admit five emails. Its aggregate `room` also remains bounded by the old research collection quota.

   Separately, `places` greedily assigns inbox capacity to campaigns before checking whether each campaign has drainable stock. A campaign with no qualifying bank candidates can consume the provisional allocation and leave another campaign on the same inbox with zero.

   **Change:** Explicitly separate research quotas, nominal bank sizing and drain capacity. Remove banked/review-held stock from send-use accounting; preserve actual usage, queued commitments and pilot limits. Allocate places to qualifying candidates, returning unused provisional allocations. Test same-day banking followed by draining, and an empty/ineligible campaign ahead of a stocked campaign sharing its inbox.

2. **P1 — Taking the minimum of B4’s bounds does not account for existing commitments consistently.**

   **Where:** B4 budget items 1–4; [reply_headroom](/Users/michaelrickards/dev/bh2-BANK/backend/services/metering.py:738), [_cold_limits](/Users/michaelrickards/dev/bh2-BANK/backend/services/metering.py:838).

   **Scenario:** A 20-cold-email inbox has a total ceiling of 40. Replies have used 39 places, and one existing step-0 contact is waiting. Cold capacity still has 19 places, while `reply_headroom()["left"]` is one. B4 admits another contact, although the existing waiter already needs that last total-mailbox place. On another hourly pass, the same headroom remains until a send reserves it.

   Similarly, with one monthly place remaining and one due follow-up, B4’s monthly calculation subtracts step-0 waiting but not that follow-up. Daily capacity can still be positive, so it enrols a first contact whose send is refused once the follow-up consumes the monthly allowance.

   **Change:** Build one consistent commitment ledger. Subtract existing unsent work from **every applicable bound**, including total-mailbox headroom and monthly allowance; exclude commitments already represented by reserved/unknown usage so they count once. Decrement those same balances for each new enrolment. Add combined-limit and repeated-hour tests, not only B7’s “every bound binds alone” cases.

   These are scheduling allocations, not send reservations: subsequent replies or authority changes can still legitimately make a later send refuse.

3. **P1 — Card preparation must run independently of finding banked contacts or making new enrolments.**

   **Where:** B4’s business selection and post-commit preparation; [prepare_due_cards](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_research.py:1250), [research.run_due](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_research.py:1307), [automations.run_all_due](/Users/michaelrickards/dev/bh2-BANK/backend/services/automations.py:606).

   **Scenario:** Research is switched off. The drain enrols the last banked contacts and commits, then the process fails before creating their cards. The business now has no banked contacts, so B4 never selects it again; research’s scheduler also skips it. Those first emails receive no cards. Even without a crash, later manual follow-ups have the same problem once the bank is empty.

   Autopilot campaigns do not need ordinary cards: their separate scheduler selects due enrolments and creates automatic proposals. That existing behaviour should remain.

   **Change:** Run retryable due-card preparation for businesses with due active enrolments, independently of bank stock, new placements and the research toggle. Keep it outside the drain transaction and retain valid-grant skipping. Test commit-before-preparation failure, an empty bank, research disabled, later follow-ups, and autopilot grants being revoked.

4. **P2 — B2 does not fully define allocation after brand limits bind.**

   **Where:** B2; [capacity’s brand calculation](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_research.py:745), [_cold_limits](/Users/michaelrickards/dev/bh2-BANK/backend/services/metering.py:858).

   **Scenario:** Two campaigns share a 20-place inbox. Equal allocation gives ten each, but one brand has already consumed its aggregate allocation on another inbox. Clipping that brand afterward leaves unused capacity unless allocation is repeated across the affected inboxes. Another brand could bank and send into those places.

   B2 also names the brand’s “20 (or boosted)” cap without explicitly retaining the owner’s lower `business_daily_cap`, which the send path enforces.

   **Change:** Specify deterministic allocation under campaign, mailbox **and brand** constraints, including redistribution after a brand binds and integer remainder handling. Use the send path’s lower-cap/boost policy. Test multiple inboxes, a shared inbox, a lower owner cap and brand-bound redistribution.

   The estimated steady-state wording is otherwise honest: five times daily capacity is approximately three weeks only under the stated one-third-first-email assumption.

5. **P2 — Contacts inside the five-day exclusion window can block replacement stock despite being undrainable.**

   **Where:** B1, B2, B4 and B6.

   **Scenario:** An inbox’s target is 25. Its bank contains 25 eligible contacts with four days remaining. B4 skips every one, but B2 still counts all 25 against `bank_room`. Research buys no replacements, and the inbox sends nothing until erasure frees the bank—even though fresh contacts could be collected and sent.

   **Change:** Distinguish held stock from drainable stock. Define how near-deadline contacts affect replenishment and show the distinction in status, without changing OUT-13’s erasure policy. Test a bank entirely inside the exclusion window.

   A brand-new contact has 28 days remaining and therefore passes the margin immediately. B7 should explicitly test that the rule is **five days remaining**, not a five-day wait after collection.

6. **P2 — B5 promises an existing review quota and promotion workflow that the repository does not provide.**

   **Where:** B3/B5/B7; [research’s review-storage loop](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_research.py:1172), [_store](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_research.py:881), [qualified](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_manage.py:160).

   **Scenario:** `MAX_GATEKEEPERS` limits contact type, not review-held records. Named review-held contacts can currently reach 20; [the existing test explicitly expects that](/Users/michaelrickards/dev/bh2-BANK/backend/tests/test_outreach_research_brands.py:358). There is no separate existing ten-review quota.

   I also found no owner operation that promotes a review-held prospect into qualified, verified stock. The outcome operation changes stage, not eligibility or verification. Review storage deliberately leaves corporate status, lawful basis and valid verification evidence absent. Changing eligibility alone would not make sending possible.

   **Change:** Define the new review-specific counter explicitly and exempt this storage path from B3’s universal qualification rule. Either specify the authorised review/reverification operation, including its evidence requirements, or remove the claim that an existing workflow promotes these contacts and state that promotion is deferred. Test actual promotion through the intended operation, not a direct eligibility update.

7. **P2 — B4’s lock contract needs an explicit entry sequence; `start()` rolls back.**

   **Where:** B4’s “under the business lock” authority checks; [outreach_manage.start](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_manage.py:13).

   **Scenario:** An implementation locks and selects candidates, then calls `start()` as B4 instructs. `start()` performs `session.rollback()` before reacquiring locks. Any preceding selection or capacity calculation has lost its protection and must not be reused. It also requires an active owner identity, which the scheduled drain has not specified.

   **Change:** Define scheduler authority acquisition before candidate selection: resolve the owner and complete `start()`/`growth()`, or extract an appropriate shared authority helper. Then re-read pause, payment, campaign state, candidates and balances under the final uninterrupted lock through commit. Keep `plan()`, card preparation and other rollback-owning helpers outside that phase.

B7 should also explicitly replace the superseded immediate-enrolment/card assertions in `test_outreach_research.py` and the PostgreSQL research test with research → drain → preparation tests. Preserve manual enrolment: B4’s “only path into a campaign” should mean the only **automatic research-placement** path, unless removing the existing owner control is an intended product change.

VERDICT: CHANGES REQUESTED