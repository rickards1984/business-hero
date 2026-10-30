**REQUEST CHANGES — OUT-19 F, review 1, commit `87eaff1`.** These findings serve North Star **P8: Trust over cleverness**.

**P1 — must fix**

1. **Ordinary subscription webhooks fail for businesses without outreach setup.**  
   [main.py:1234](/Users/michaelrickards/dev/bh2-OUT-19F/backend/main.py:1234) calls `apply_subscription` unconditionally. Its `_lock` requires an `outreach_settings` row, even when there are no outreach billing records. Reproduced: `ActionRefused(404, "Outreach record unavailable")`. This prevents the existing subscription changes and event receipt from committing. The call also sits outside the explicit 503 handler. Skip outreach reconciliation when inapplicable; include applicable processing in the rollback/retry boundary.

2. **Uncertain Stripe outcomes are treated as definite failures, allowing duplicate charges.**  
   [outreach_billing.py:253](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:253), [line 418](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:418).  
   Stripe can accept a payment or subscription modification before the response times out. The code then releases/reverts its reservation and says “nothing was charged.” Retrying generates a new idempotency key and can charge again. For brands, the exception handler can even revert a brand already activated by its webhook. Persist the operation identity, retain uncertain reservations, and reconcile/retry using that identity.

3. **One successful top-up releases two reservations.**  
   [outreach_billing.py:454](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:454).  
   After releasing the matching PaymentIntent, the unconditional fallback also removes the oldest same-brand/same-amount reservation. Reproduced with two £25 top-ups: confirming one reduced outstanding reservations from £50 to **£0**, although £25 remained payable. Bind each payment to one reservation and release exactly that reservation.

4. **The 3-D Secure fallback loses its budget protection while Checkout remains payable.**  
   [outreach_billing.py:406](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:406), [line 442](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:442).  
   The reservation is associated with the original failed intent, while Checkout creates another intent. The original intent’s failure webhook releases the reservation. Reproduced: Checkout remains payable with **zero held budget**, allowing another purchase to consume the same budget. Track the whole purchase across both intents and Checkout; release only when no associated payment remains payable. Likewise, elapsed 24 hours alone does not prove an unresolved payment cannot succeed.

5. **Subscription mutations and quantity allocation race with each other and with webhooks.**  
   [outreach_billing.py:241](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:241), [line 275](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:275), [line 334](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:334).  
   Concurrent operations retrieve the same quantity and independently write `quantity ± 1`; distinct idempotency keys do not serialize them. Removal also records `ending` only after Stripe responds. Reproduced: removing the older of two paid brands, with its webhook arriving before the response, leaves the removed brand live but **disables the remaining paid brand**. Persist removal intent before dispatch and serialize/reconcile subscription operations. Existing `pending_update` must also be handled: later updates can replace the previous pending invoice. [Stripe documentation](https://docs.stripe.com/billing/subscriptions/pending-updates).

6. **Outreach entitlement reconciliation accepts stale subscription quantities.**  
   [outreach_billing.py:315](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:315).  
   Unlike the existing tier logic, this function receives no event freshness information. An older, distinct event showing a lower quantity can disable a paid brand; an older higher quantity can activate a currently unpaid pending brand. Event-ID deduplication does not prevent this. Reconcile against authoritative current subscription state or enforce a suitable ordering strategy.

7. **Top-up crediting trusts metadata without binding it to the paying customer or purchase.**  
   [outreach_billing.py:428](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:428).  
   Checking that the brand belongs to the metadata business is insufficient. A signed Stripe event with valid local IDs is credited without checking `customer`, currency, expected amount, or a recorded purchase. Reproduced acceptance of an entirely unreserved intent. This is not a demonstrated webhook-signature bypass, but it permits incorrect cross-business credit attribution. Validate the payment against the server-created purchase and its Stripe customer.

**P2**

- **Stopped brands consume budget indefinitely.** [line 119](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:119) excludes only `awaiting_payment`; expired `ending` records remain committed in every future month. Use the paid period and actual billing state.
- **Failed/expired brand additions have no recovery path.** A declined pending update remains `pending`; adding again requires `awaiting_payment`, and removal requires `active`. The UI keeps saying “Waiting for Stripe.” Handle authentication, failure and expiration explicitly.
- **The two-price activation gate is incomplete.** [line 167](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:167) checks only the current brand’s price. Setting either price alone partially enables billing, contrary to section F.
- **Checkout returns to an unimplemented section.** [outreach_setup_api.py:262](/Users/michaelrickards/dev/bh2-OUT-19F/backend/outreach_setup_api.py:262) returns to `/app/outreach/research`; `OutreachPage` renders research under `/app/outreach/settings`. The returned page has no matching section content.
- **Free-month income handling differs from the ticket’s “As built” claim.** [profit_guard.py:99](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/profit_guard.py:99) recognizes only `complimentary`, not `outreach_brands_free`. Align the implementation and documented meaning; currently the latter alone still contributes plan income.

**Backlog**

- Poll or otherwise refresh pending billing states; `staleTime` alone does not poll.
- Replace the bounded 500-payment dedupe list with durable purchase/payment records before volume makes truncation relevant.
- Make projected outreach revenue reporting reflect the new billing states.

**Checks and test quality**

The Stripe **15.6.1** item shapes (`id`, `quantity`, `deleted`), `CardError` access and `idempotency_key` request-option usage are valid. [Item schema](https://raw.githubusercontent.com/stripe/stripe-python/v15.6.1/stripe/params/_subscription_modify_params.py), [errors](https://raw.githubusercontent.com/stripe/stripe-python/v15.6.1/stripe/_error.py), [request options](https://raw.githubusercontent.com/stripe/stripe-python/v15.6.1/stripe/_request_options.py).

Owner checks, tenant-scoped brand lookup, reservation-before-dispatch, grandfathering, and the placement of the cold-send gate outside replies are present. Existing BH-006 tier-write rules remain textually unchanged, and the new writes share the final transaction; finding 1 nevertheless breaks that transaction for ordinary customers.

I ran **25 existing non-parameterized database tests successfully**, using the existing fixture adapted in memory, plus the failure reproductions above. The source-string assertions for webhook wiring and reply gating do not establish behavior; the PostgreSQL tests do not exercise concurrency. The P1 scenarios need behavioral regressions, including real webhook transaction tests.

No files were modified, committed or pushed. `check.sh` was not run because it writes compiled files; no PostgreSQL, browser or live Stripe verification was performed.

**Verdict: REQUEST CHANGES.**