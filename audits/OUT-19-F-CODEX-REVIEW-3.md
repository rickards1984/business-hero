**OUT-19 F, review 3 — `a2adfe2`. North Star P8.**

The simplification fixes several earlier defects, but money and entitlement failures remain. This is the final-cycle handoff to Mike.

**P1 — must fix**

1. **A failed retry can discard an already-charged addition and charge again.**  
   [outreach_billing.py:399](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:399)

   Reproduced: Stripe applies the addition, its response is lost, then the retry’s `Subscription.retrieve` returns a rate-limit error. `_definite` treats that error as proof the original addition failed; `keep=False` deletes its price and operation identity. The next addition creates **two billed lines for one brand**. The response also falsely says nothing was charged.

   A definite failure of the retry’s read does not settle the earlier uncertain write. Preserve the original operation until its outcome is established. No existing regression covers this sequence.

2. **Removal’s pending-update refusal still has a race window.**  
   [outreach_billing.py:434](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:434), [reconciliation resend:537](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:537)

   Reproduced: removal retrieves a subscription without a pending update; another brand addition then creates one and releases its claim; removal acquires a fresh claim and dispatches deletion using the stale snapshot. The deletion is sent **while another payment is pending**.

   `_resend_removals` also checks a previously read claim without acquiring one. The fingerprint guard protects subsequent local writes, not these Stripe mutations. Stripe documents that later item updates can discard an existing pending update. [Pending-update rules](https://docs.stripe.com/billing/subscriptions/pending-updates).

   Claim the subscription operation before fetching the state used to authorize its mutation. The current removal regression tests only a pending update that already exists before retrieval.

3. **An uncertain removal can stop a brand after another period has been paid.**  
   [outreach_billing.py:444](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:444), [resend:543](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:543)

   Reproduced with a period boundary: removal fails before reaching Stripe; the item renews into another paid period; reconciliation retrieves the renewed item and deletes it without proration, but retains the **old `ends_at`**. The brand is then stopped despite the renewed payment.

   Recovery must account for renewal while deletion remains unconfirmed. The existing resend test never crosses a renewal boundary.

**P2**

1. **Checkout recreation violates Stripe’s minimum expiry window.**  
   [outreach_billing.py:599](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:599), [recovery:659](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:659)

   Expiry is fixed at reservation time plus 35 minutes; recovery starts after five minutes and continues until minute 30. If the original request never reached Stripe, recreation at minute 10 leaves only 25 minutes and is invalid. Stripe requires at least 30 minutes **from creation**. [Checkout expiry specification](https://docs.stripe.com/api/checkout/sessions/create).

   Reproduced by adding that documented validation to the fake: no page is created, and the reservation remains. The existing recovery test passes because FakeStripe ignores expiry validation. Keep immutable retry parameters while making the recovery window valid.

2. **Failed delayed payments hold budget indefinitely.**  
   [outreach_billing.py:685](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:685), [event routing:703](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:703)

   Checkout does not restrict payment methods, but `checkout.session.async_payment_failed` is ignored. A completed, unpaid session is neither credited nor released; the four-day cleanup excludes purchases with a session ID.

   Reproduced a failed asynchronous payment whose reservation remained after **100 days**. Handle confirmed terminal failure, or explicitly restrict supported methods. [Stripe delayed-payment events](https://docs.stripe.com/payments/existing-customers?platform=web&ui=stripe-hosted).

3. **The UI says “Billing stopped” before Stripe confirms removal.**  
   [OutreachSetupWizard.tsx:1038](/Users/michaelrickards/dev/bh2-OUT-19F/frontend/client/src/components/OutreachSetupWizard.tsx:1038)

   An uncertain removal is stored as `ending` without a checking flag. Refresh therefore displays “Billing stopped” even when the deletion never reached Stripe, and that state alone does not trigger polling. Represent and display unconfirmed removal honestly.

**Review-2 closure**

Regression names below are in [test_outreach_billing.py](/Users/michaelrickards/dev/bh2-OUT-19F/backend/tests/test_outreach_billing.py), except where noted.

| Review-2 finding | Review-3 assessment |
|---|---|
| P1.1 Stale reconciliation overwrites addition | Original reproduction fixed; `test_an_answer_fetched_before_an_addition_finished_is_not_applied_over_it`. Brand fingerprints and purchase comparisons are present. |
| P1.2 Another brand takes an uncertain removal’s paid slot | Fixed by separate prices/items; `test_removing_one_brand_never_hands_its_place_to_another`. |
| P1.3 Failed fetch leaves indefinite entitlement | Original defect fixed by retrieving before recording; `test_a_removal_that_cant_reach_stripe_changes_nothing`. Renewal recovery remains defective, as above. |
| P1.4 Removal ignores pending update | **Partial:** `test_no_removal_while_stripe_holds_an_unpaid_update` covers sequential refusal, not the reproduced race. |
| P1.5 Overlapping payment attempts/lost reservations | Off-session fallback removed. Lost-response recovery has regression coverage, but recreation after a request never arrived fails Stripe’s expiry rule. |
| P1.6 Incomplete payment binding | Fixed for the reported cases; parameterized `test_a_page_that_isnt_this_reservations_is_never_credited` exercises both settlement paths, plus the no-reservation test. |
| P2 Mutable idempotent requests | Stored price/item/purchase parameters and fake parameter-equality checks improve this substantially. **Not fully closed:** the uncertain-retry sequence above discards the identity. |
| P2 Missing refresh/polling | Addition and top-up refresh/polling fixed in source. No behavioural frontend regression; unconfirmed removal remains misleading. |
| Outstanding flag-income regression | Added and passed: `test_only_the_complimentary_flag_takes_a_business_out_of_income`. |

**Other checks and backlog**

- Installed Stripe SDK is **15.6.1**. The requested Price, Subscription and Checkout parameter shapes, Session fields, and `idempotency_key` option are supported. The expiry problem is a lifecycle constraint, not a signature error.
- Reconciliation performs Stripe calls before acquiring its row lock. Settlement validates reservation, page identity when known, business, brand, customer, GBP and exact paid amount; credit deduplication uses durable usage-meter rows under the business lock.
- `main.py` is unchanged since review 2. Outreach processing remains after event-ID deduplication, before business writes, inside the rollback/503 boundary. `outreach_business_id` avoids the plan Checkout branch’s `business_id` lookup.
- The four-day unknown-page release matches the revised ticket, but elapsed webhook retry time is **not proof of nonpayment**. Retaining an audit record and providing late-payment recovery remain advisable.
- Revenue reporting from actual billing states and browser coverage remain backlog. FakeStripe should additionally model expiry validation, pending-update replacement, renewal boundaries and cached error responses.

**Verification:** **170 tests passed** across billing, profit guard and webhook correctness, with file-backed SQLite fixtures adapted **in memory**. Additional in-memory reproductions established the failures above. The BH-006 tests stub outreach processing; PostgreSQL endpoint tests were inspected but not run because `RLS_LOCAL_DATABASE_URL` is unset.

`check.sh` was not run because it writes files. No browser or live Stripe testing was performed. Nothing was modified, committed or pushed; pre-existing untracked `data.db` was untouched.

**Verdict: REQUEST CHANGES.**