Reviewed `612329f` against `origin/main` and both approved tickets, under **North Star P8**. **REQUEST CHANGES**.

**P1**

1. **Current Stripe invoices bypass subscription-based attribution.** [stripe_income.py:96](/Users/michaelrickards/dev/bh2-PROFIT-2/backend/services/stripe_income.py:96) reads only `invoice.subscription`. Stripe 15.6.1 uses `parent.subscription_details.subscription`; Stripe documents that [field relocation](https://docs.stripe.com/changelog/basil/2025-03-31/adds-new-parent-field-to-invoicing-objects).

   Reproduced with a real SDK object: an invoice for business B’s subscription was assigned to business A because they shared a customer. B retained its estimated plan income. This can distort the platform-wide kill threshold and per-business economics. Read the current field with legacy fallback, and reject ambiguous customer matches rather than selecting the first business.

**P2**

2. **History fabricates past income and changes it retrospectively.** [profit_guard.py:193](/Users/michaelrickards/dev/bh2-PROFIT-2/backend/services/profit_guard.py:193) applies today’s active businesses and plan estimates to previous months. Reproduction: two businesses with only October invoice evidence produced £258 income for May; cancelling them changed May to £0. The UI then calls this “what came in”. Historical income needs period-appropriate evidence, and estimates must remain explicitly identified.

3. **Invoice deduplication is not atomic.** [stripe_income.py:99](/Users/michaelrickards/dev/bh2-PROFIT-2/backend/services/stripe_income.py:99) checks the marker before updating cash. Concurrent refresh/webhook transactions can both pass that check. If monthly cash already exists, the second transaction waits on its update, then increments cash and the now-existing marker again. Sequential replay tests miss this. Atomically claim the invoice before incrementing cash. This affects displayed cash, rather than doubling recurring income.

4. **Concurrent first edits can overwrite running costs.** [running_costs.py:90](/Users/michaelrickards/dev/bh2-PROFIT-2/backend/services/running_costs.py:90) does not serialize materialisation. Two requests can read the previous month’s list; the later copy can overwrite the first request’s corrected bill. Other interleavings produce uniqueness errors. Serialize materialisation and mutation together, with a PostgreSQL concurrency regression test.

5. **Changing months leaves editable bills from the previous month.** [AdminRunningCosts.tsx:26](/Users/michaelrickards/dev/bh2-PROFIT-2/frontend/client/src/components/AdminRunningCosts.tsx:26) changes `period` before loading its bills, without disabling edits. Saving or removing an old displayed row during that interval writes to the newly selected month. Failed loads leave this mismatch indefinitely. Bind actions to the loaded bills’ period and disable editing during transitions. Also, `load()` swallows errors that `call()` subsequently replaces with a success message.

6. **“Cash received” excludes paid top-ups.** [profit_guard.py:97](/Users/michaelrickards/dev/bh2-PROFIT-2/backend/services/profit_guard.py:97) sums invoice cash only. Existing top-ups use payment-mode Checkout without invoice creation, so their receipts never reach this figure. Include those receipts without double-counting, or label the figure specifically as invoice receipts.

**Backlog / approved-policy limitations**

- Refunds and credit notes are not reconciled; refresh skips already-recorded invoices. Define how reversals affect displayed cash and recurring income before claiming net retained receipts.
- `subscription_cycle`/`subscription_create` alone do not prove a full monthly charge: invoices can contain prorations or other adjustments. The implementation follows the approved predicate, but its “never overstated” claim is too strong. [Stripe’s proration documentation](https://docs.stripe.com/billing/subscriptions/prorations) describes these cases.
- Plan changes retain the last full invoice until another qualifies, as approved. Cancelled/inactive businesses are excluded correctly; multiple subscriptions on one customer can still overwrite one business’s recurring amount.
- £0 invoices remain genuine zero values. Trialing businesses are excluded, and the trial-budget floor is preserved. That floor remains effective while configured, including after launch.
- Hot-path overhead: measured **10 queries** inside `profit_guard.allowed()` with a cost list, versus five previously after table-detection caching. The extra five comprise recurring/cash reads and three fixed-cost queries. Consolidate duplicate source queries and avoid fetching cash for the guard.
- Blank amount inputs become zero; API integer coercion also weakens the service’s boolean rejection. Tighten input validation and refresh-error logging.

Tax handling is correct for ordinary fully paid invoices: `total_taxes[].amount`, legacy `tax` and `total_tax_amounts` are supported; discounts are already reflected in `amount_paid`. Refresh uses valid [15.6.1 list parameters](https://raw.githubusercontent.com/stripe/stripe-python/v15.6.1/stripe/params/_invoice_list_params.py) and makes no Stripe writes. The webhook call is inside the 503 boundary, before business writes; BH-006 logic is unchanged. Every admin route has the platform-admin dependency. Carry-forward reads do not write, and missing-table fallback worked.

**Verification:** 32 PROFIT-2 tests and 48 PROFIT-1 tests passed using an in-process, memory-only SQLite adaptation. Targeted Ruff passed. PostgreSQL tests, browser behaviour and `check.sh full` were not run. Current tests miss modern invoice attribution and concurrency; webhook/admin checks are largely source inspection.

No files modified, committed or pushed. The pre-existing untracked `data.db` was left untouched. **Verdict: REQUEST CHANGES.**