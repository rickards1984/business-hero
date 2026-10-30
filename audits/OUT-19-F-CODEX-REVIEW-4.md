**OUT-19 F review 4 — `9d8ba40`, North Star P8.** Two P1 defects and two P2 issues remain.

**P1 — must fix**

1. **Reconciliation can discard an addition while its retry is executing, causing a second charge.**  
   [outreach_billing.py:608](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:608)

   Reproduced this interleaving:
   - An uncertain addition is more than one hour old.
   - Its retry claims the subscription and retrieves Stripe.
   - Before the retry’s modification reaches Stripe, reconciliation sees no item or pending update and clears the addition’s identity.
   - The retry successfully adds the billed item, but its local update no longer matches.
   - The brand remains `awaiting_payment`, despite being charged. Clicking Add creates a second billed item.

   The fingerprint check does not protect an operation still in progress; `_apply_brands` ignores its held claim. Prevent reconciliation from abandoning an in-flight addition and add this interleaving as a regression.

2. **A pending update prevents renewal recovery, stopping an already-paid brand.**  
   [outreach_billing.py:514](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:514)

   Reproduced: an uncertain removal survives into another paid period; another addition has a pending payment. `resend_removals` returns before updating `ends_at`. The brand becomes non-live at its old boundary despite the renewed payment.

   Refuse the Stripe deletion while payment is pending, but still reconcile the existing brand’s paid entitlement. Review-3 P1.3 is only partially fixed.

**P2**

1. **Stripe-client initialization errors leave subscription claims held.**  
   [Removal:448](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:448), [resend:511](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:511)

   Both commit their claim before calling `_stripe()` outside the protected exception/finally block. Reproduced a configuration exception leaving `op` populated in both paths. Addition has the same placement. Subsequent operations are blocked until the ten-minute lease expires. Include client initialization in claim cleanup.

2. **Webhook reconciliation still writes to Stripe.**  
   [outreach_billing.py:702](/Users/michaelrickards/dev/bh2-OUT-19F/backend/services/outreach_billing.py:702)

   `webhook → reconcile → _ask_about_pages → _create_page` still creates Checkout sessions. Reproduced a subscription webhook creating a previously unconfirmed top-up page. Subscription-removal writes were separated successfully, but the ticket’s “webhook no longer sends anything to Stripe” requirement is not met. Move page recreation into scheduled recovery too.

**Review-3 closure**

Regression names below are in [test_outreach_billing.py](/Users/michaelrickards/dev/bh2-OUT-19F/backend/tests/test_outreach_billing.py:849).

| Review-3 finding | Assessment |
|---|---|
| P1.1 Failed retry discards charged addition | Original sequence fixed; `test_a_failed_retry_never_forgets_an_addition_that_may_have_been_charged` passes. The separate reconciliation race above remains. |
| P1.2 Removal uses stale pre-claim read | Fixed for the reported race; `test_no_other_change_can_slip_between_a_removals_read_and_its_deletion` passes. Scheduled recovery also claims before its fresh read. |
| P1.3 Renewal loses paid entitlement | **Partial**; `test_a_removal_finished_after_a_renewal_keeps_the_brand_for_the_month_paid` passes, but omits a simultaneous pending update. |
| P2.1 Checkout expiry window | Fixed for the reported recovery window; the expiry-enforcing fake and `test_a_page_re_sent_ten_minutes_on_still_meets_stripes_expiry_rule` exercise recreation at minute 29. |
| P2.2 Failed delayed payments retain budget | Fixed; card-only creation is asserted, and `test_a_failed_delayed_payment_releases_its_reservation` passes. Failure release uses the shared purchase/customer/page binding checks. |
| P2.3 Unconfirmed-removal copy | Fixed in source; backend regression asserts `checking=True`, and the UI polls and says it is asking Stripe to stop billing. **No behavioural browser regression.** |

The definite-removal refusal restores `active` and clears removal fields. Scheduled reconciliation and removal recovery use separate sessions. Recovery’s `finally` releases claims for exceptions occurring **inside** its protected block.

`payment_method_types=["card"]` is valid in **stripe-python 15.6.1**. Its Checkout schema explicitly supports that parameter and value. [Versioned SDK source](https://raw.githubusercontent.com/stripe/stripe-python/v15.6.1/stripe/params/checkout/_session_create_params.py)

**Backlog and test quality**

- The new tests meaningfully exercise stored state, Stripe calls and entitlement. They miss the interleavings and initialization failures reproduced above.
- Add browser coverage for uncertain removal, polling and confirmed removal.
- Retain late-payment recovery/auditability for unknown pages discarded after four days; elapsed webhook retry time does not establish nonpayment.
- Revenue reporting from actual billing states remains backlog.

**Verification:** 176 targeted billing, profit-guard and webhook-correctness tests passed with SQLite fixtures adapted **in memory**, plus the additional reproductions above. BH-006 tests stub outreach processing; PostgreSQL integration tests were not run because `RLS_LOCAL_DATABASE_URL` is unset.

`check.sh` was not run because it writes files. No browser or live Stripe verification occurred. For behavioural confirmation after fixes, exercise an uncertain removal in Stripe test mode and verify Outreach settings continues showing “asking Stripe” until confirmation.

Nothing was modified, committed or pushed; pre-existing untracked `data.db` was untouched.

**Verdict: REQUEST CHANGES.**