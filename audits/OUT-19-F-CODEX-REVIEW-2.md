**REQUEST CHANGES — OUT-19 F, review 2, `c98aa49`.** North Star **P8**. The rework improves webhook handling and test coverage, but payment and entitlement defects remain.

**P1 — must fix**

1. **A fetched subscription can become stale before reconciliation acquires its lock.**  
   [outreach_billing.py:475](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:475) fetches Stripe, then locks and reloads local state. A concurrent addition can finish between those steps. Reproduced: the addition was paid and activated; the earlier reconciliation then changed it to `awaiting_payment`, while Stripe still had quantity **1**. The operation claim does not guard `_apply_brands`. Fetching current state alone does not solve ordering. Add a regression covering this interleaving and prevent applying a snapshot across an intervening operation.

2. **An uncertain removal lets another brand become live without a new payment.**  
   [outreach_billing.py:408](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:408), [allocation:515](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:515).  
   Reproduced: remove paid brand A, lose the modification before Stripe applies it, then add B. A is locally `ending`, so B’s desired quantity equals Stripe’s existing quantity. Addition makes **zero modification calls**; reconciliation activates B using A’s paid slot. Both brands remain live. Unsettled removals must retain ownership of their Stripe quantity until resolved.

3. **A failed removal fetch can leave a brand live forever after billing stops.**  
   [outreach_billing.py:397](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:397).  
   Removal persists `ending, ends_at=None` before retrieving Stripe. If retrieval fails, reconciliation subsequently removes the subscription item but never repairs `ends_at`. Reproduced: Stripe quantity **0**, brand still live **100 days later**. `brand_live` and budget accounting both treat that missing end date as indefinite. Recovery must establish the paid-period boundary.

4. **Removal does not refuse an existing `pending_update`.**  
   [outreach_billing.py:404](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:404).  
   Addition checks this; removal does not. Reproduced a removal dispatching `Subscription.modify` while another update was pending. The ticket’s “no change while Stripe has an unpaid update” guarantee is therefore false. Add the refusal and a removal-specific behavioural regression, preserving the original pending payment. [Stripe pending-update documentation](https://docs.stripe.com/billing/subscriptions/pending-updates).

5. **The 3-D Secure recovery still permits lost reservations and overlapping payable attempts.**  
   [outreach_billing.py:593](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:593), [recovery:621](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:621).
   - Cancellation errors are logged, but Checkout is created anyway. Reproduced a Checkout URL returned after cancellation failed. Cancellation must be confirmed before creating another payable attempt.
   - If Checkout creation succeeds but its response is lost, only `uncertain` is stored. Reproduced an **open Checkout session with its £25 reservation removed** by reconciliation.
   - Empty PaymentIntent search results are treated as proof that nothing exists. They cannot establish that an unknown Checkout session is absent; search also has indexing delay.
   
   Persist the purchase’s transition to Checkout, recover creation with the same key, and retain its reservation until every associated attempt is conclusively settled. Stripe explicitly cautions against relying on search for strict consistency. [Search](https://docs.stripe.com/api/payment_intents/search), [cancellation](https://docs.stripe.com/api/payment_intents/cancel).

6. **Payment binding remains incomplete, and reconciliation bypasses it entirely.**  
   [outreach_billing.py:681](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:681), [reconciliation credit:489](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:489).  
   The webhook fabricates a purchase when no reservation exists and never compares the payment amount with the reserved amount. Reproduced an unreserved **£50 credit**. Reconciliation calls `_credit` directly without validating customer, currency, amount or metadata brand: a **USD 50 payment from another customer** satisfied a £10 reservation in my reproduction. Use one validation path backed by a retained purchase record for both webhook and recovery.

**P2**

- **Idempotency keys do not identify immutable requests consistently.**  
  [Addition:333](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:333) recomputes parameters when retrying an existing operation. [Settlement:503](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:503) uses one business/hour key for potentially different quantity changes, then changes that key next hour for an uncertain retry. Different requests can collide; one uncertain request can acquire multiple identities. Persist the exact request and its operation key. The fake does not enforce Stripe’s parameter equality or cached-response behaviour. [Stripe idempotency rules](https://docs.stripe.com/api/idempotent_requests).

- **Polling misses uncertain additions and top-ups.**  
  [BrandBilling:997](/Users/michaelrickards/dev/bh2-OUT-19F/frontend/client/src/components/OutreachSetupWizard.tsx:997) polls only when cached brand data already contains `pending`. A 502 addition does not invalidate that cache, so it can continue showing “Add” while the server holds an uncertain payment. Top-ups expose no pending status to trigger polling. Refresh after uncertain responses and track outstanding purchases. The new failure note itself is correctly rendered.

**Review-1 closure**

| Review-1 finding | Review-2 assessment |
|---|---|
| P1.1 Ordinary-customer webhook failure | Fixed in code; behavioural service and PostgreSQL endpoint regressions exist. |
| P1.2 Uncertain outcomes | Partial. Immediate reservations survive, but Checkout recovery and request identity remain defective. |
| P1.3 One payment releases two reservations | Fixed; `test_one_confirmed_top_up_releases_only_its_own_reservation` covers it. |
| P1.4 3-D Secure reservation loss | Partial; happy-path regression passes, failure paths above remain. |
| P1.5 Subscription races | Partial; early removal intent and claims help, but findings 1–4 remain. |
| P1.6 Stale subscription quantities | Sequential old-event test passes; concurrent stale-fetch reproduction still fails. |
| P1.7 Payment binding | Not fixed completely; missing-purchase, reserved-amount and recovery-path cases remain. |
| P2 Stopped-brand budget | Fixed for known end dates, with regression; unknown end dates remain defective. |
| P2 Failed/expired addition recovery | Fixed for expired pending updates; regression checks that an existing `pending_update` prevents premature reset. |
| P2 Two-price activation gate | Fixed, with parameterized regression. |
| P2 Checkout return route | Corrected to `/app/outreach/settings`; test checks source text, not browser behaviour. |
| P2 Free-month income claim | Documentation now distinguishes `outreach_brands_free` from `complimentary`; no behavioural regression establishes the two-flag income contract. |

**Other checks and backlog**

- `main.py` invokes billing **after event-ID deduplication, before BH-006 business writes, inside a rollback/503 boundary**. Existing BH-006 rules are textually unchanged; **54 webhook-correctness tests passed**, with outreach billing stubbed.
- `_committed` passes `moment` through correctly. The scheduler hook preserves CRLF. `scheduled_check` selects settings containing the billing key, uses separate sessions per business, and catches selection/reconciliation failures.
- Installed Stripe SDK is **15.6.1**. The search query syntax, `PaymentIntent.cancel`, Checkout retrieval, `pending_update` shape and `idempotency_key` request option are valid. The problems are lifecycle and consistency handling, not method signatures. [Search syntax](https://docs.stripe.com/search).
- Durable per-PaymentIntent usage-meter deduplication replaces the bounded list. It does not replace purchase validation.
- Revenue reporting from actual billing states remains backlog. Add browser coverage for pending-payment transitions.

**Verification:** All **53 billing test cases passed** when invoked with their SQLite fixture adapted in memory; the additional reproductions above expose missing coverage. FakeStripe does not model idempotency, cancellation state or delayed search visibility. The PostgreSQL suite includes real endpoint tests, but its top-up dedupe test calls the service directly.

`RLS_LOCAL_DATABASE_URL` was unavailable, so PostgreSQL tests were not run. `check.sh` was not run because it writes compiled files. No browser or live Stripe testing was performed. No files were modified, committed or pushed; the pre-existing untracked `data.db` was left untouched.

**Verdict: REQUEST CHANGES.**