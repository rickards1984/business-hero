**OUT-19 F, review 5 — `ddb7fdb`. North Star P8.**

**P1:** None identified at that severity.

**P2 — a completed retry can still lose its payment identity**

[Reconciliation](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:574) checks the current claim and a fingerprint that does not record intervening retry attempts.

Reproduced in memory:

1. An uncertain addition reaches the stale threshold.
2. Reconciliation fetches Stripe before the addition exists.
3. A concurrent retry successfully adds the billed line, but its response is lost.
4. The exception handler releases its claim and sets `uncertain=True`—which was already true. The fingerprint therefore remains unchanged.
5. Reconciliation applies its earlier answer and clears the operation and price.
6. Clicking Add again creates a second billed line.

Observed: **`awaiting_payment` with one billed line; two billed lines after the next Add.** Stripe’s idempotency protection cannot connect the new operation key to the discarded one. [Stripe idempotency documentation](https://docs.stripe.com/api/idempotent_requests)

This is narrower than review-4’s P1: it requires two transport failures and a particular interleaving. Nevertheless, it is a reproduced money defect in the supported retry path, without requiring lease expiry, database corruption or prolonged webhook failure. **P2, requiring correction.** Persist an attempt revision that changes when a retry starts, and reject reconciliation snapshots spanning that revision.

**Review-4 closure**

| Finding | Assessment |
|---|---|
| P1.1 Reconciliation abandons an in-flight retry | **Original sequence fixed; broader issue partially open**, as above. `test_a_check_never_abandons_an_addition_whose_retry_is_in_flight` passes. |
| P1.2 Pending update blocks renewal recovery | **Fixed.** Renewal extends `ends_at` before skipping deletion. `test_a_renewal_is_honoured_even_while_another_payment_is_pending` checks continued entitlement and no deletion. |
| P2.1 Client initialization leaves claims held | **Fixed for add, remove and scheduled recovery**, with behavioural regressions. Recovery initialization is inside `try/finally`; add/remove failures reach cleanup. |
| P2.2 Webhook creates payment pages | **Fixed.** Recovery defaults off; `scheduled_check` enables it. `test_the_webhook_never_creates_a_payment_page` checks both webhook non-creation and subsequent recovery. |

**Whole-module assessment and backlog**

- I found no additional demonstrated path to duplicate top-up credit, credit an unreserved/unpaid purchase, or release a reservation while its normal payment page remains payable. Shared settlement validates purchase identity, customer, brand, currency and amount.
- The changed removal recovery preserves renewed entitlement while another payment is pending and releases its claim through `finally`.
- BH-006 processing remains after event deduplication, before business writes, within the rollback/503 boundary.
- **Backlog:** retain an audit/recovery record for unknown pages discarded after four days. Losing a paid top-up this way requires creation-response loss, unsuccessful recovery and exhausted webhook delivery; that is a compound operational failure, not an ordinary-path blocker.
- **Backlog:** operations surviving the ten-minute lease, browser coverage for uncertain billing transitions, and revenue reporting from actual billing states.

**Test quality and verification**

The new regressions meaningfully check persisted state, entitlement and Stripe calls. The retry test covers reconciliation **while the claim remains held**, but misses reconciliation applying **after a lost-response retry releases it**. Add that regression and direct coverage for preserving an active brand under a held claim. The renewal test would also benefit from asserting the exact renewed expiry.

**182 targeted billing, profit-guard and webhook-correctness tests passed**, with SQLite fixtures adapted in memory for read-only execution. BH-006 unit tests stub outreach processing. PostgreSQL integration tests were inspected but not run: `RLS_LOCAL_DATABASE_URL` is unset.

`check.sh` was not run because it writes files. No browser or live Stripe verification occurred. For behavioural confirmation, use Stripe test mode to add a brand, buy one top-up and stop billing; confirm one credit and access through the paid expiry.

Nothing was modified, committed or pushed. Pre-existing untracked `data.db` was untouched.

**Verdict: REQUEST CHANGES.**