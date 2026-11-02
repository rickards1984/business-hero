# ACC-2 Codex review 2

Model gpt-6-astra · session 01a19d26-7396-75c1-9474-2f9ba37f5929 · 116,386 tokens · verdict **CHANGES REQUIRED**

## Prompt

```
You are the independent reviewer (read-only) for ticket ACC-2, branch ticket/ACC-2-accountancy-pack in this worktree. Review `git diff origin/main...HEAD`. Your previous review is audits/ACC-2-CODEX-REVIEW-1.md (6 P1, 6 P2); the builder's response is the "Codex review 1" section of docs/ACC-2-TICKET.md.

1. For each review-1 finding, confirm it is fixed in code AND proven by a test that would fail on the old behaviour (backend/tests/test_accountancy_pack.py). Say which, if any, are not.
2. Then look for new defects the fixes introduced, especially: the aged-balance invoice set (open AUTHORISED dated by the end + invoices touched by Payments dated after the end + allocations dated after the end, fetched by id) — can any invoice outstanding at the end still be missed or double counted (batch payments? prepayment/overpayment refunds? credit notes allocated before the end to invoices still open)? Allocation-date deduction vs invoice arrays; currency filtering; invoiced_sales for T1; the AI plain-line guard (can a number, amount or claim still get through?); the worker-thread endpoint (token refresh with its own session, PeriodError → 400, error handling); and Xero API semantics of the parameters sent (where syntax, Statuses, Payments where Date>…, IDs batches).

Output: APPROVE or CHANGES REQUIRED; P1/P2 findings with file:line and a concrete failure; backlog notes. Do not edit files, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED**

Reviewed `git diff origin/main...HEAD`. The remaining issues concern grounded figures and trustworthy output: North Star P2/P8.

1. **P1 — The AI guard still permits invented amounts and financial claims.**  
   [accountancy_pack.py:539](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:539)

   Executable probes confirmed that all these pass `plain_line_ok` and can reach the workbook:

   - “All your spending is tax deductible.”
   - “Claim a dozen pounds in relief.”
   - “You qualify for tax relief.”
   - “Claim ½ of your costs.”

   Preserving the deterministic explanation prevents replacement, but the adjacent AI column can still contradict it. Review-1 finding 1 remains open. Use approved wording or constrained selection; extending the blacklist cannot establish the promised guarantee.

2. **P1 — A non-GBP base currency is displayed and compared against tax thresholds as pounds.**  
   [accountancy_pack.py:644](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:644), [accountancy_pack.py:868](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:868)

   Confirmed with `BaseCurrency="USD"` and USD 100,000 of invoices: aged balances use a pound number format, and T1 states **“£100,000.00, 111% of the £90,000.00 VAT registration threshold.”** No conversion occurred.

   The GBP/USD mixing fix works for GBP-base organisations, but arbitrary base currencies are accepted downstream. Either explicitly restrict unsupported currencies or carry currency through presentation and suppress tax comparisons without a grounded GBP amount.

3. **P2 — The wording timeout does not bound the export’s wait.**  
   [accountancy_pack.py:602](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:602), [main.py:5139](/Users/michaelrickards/dev/bh2-ACC-2/backend/main.py:5139)

   `wait_for` cancels the await on `to_thread`; it cannot stop the synchronous router call. The enclosing `asyncio.run()` then waits for its default executor during shutdown.

   A probe with a **0.01-second timeout** and **0.3-second router sleep** returned only after approximately **0.41 seconds**, despite dropping the wording. A slow provider therefore still delays the download. The existing timeout test uses cancellable `asyncio.sleep`, so it misses the production behavior.

4. **P2 — Failed token refresh retains the expired provider and loses the fallback reason.**  
   [main.py:5124](/Users/michaelrickards/dev/bh2-ACC-2/backend/main.py:5124)

   `_refresh_xero_token_and_retry` catches failures and returns `(None, None)`. This caller nevertheless constructs `XeroProvider` with the original token.

   An isolated execution of the endpoint confirmed that `build` receives **the expired token and `xero_error=None`**. Subsequent report calls fail; because `provider` remains non-null, the ledger P&L fallback is not built. Organisation failure can also select the wrong default financial year. Handle unsuccessful refresh explicitly and test this endpoint path.

5. **P2 — Several review-1 fixes lack the requested regression proof.**  
   [test_accountancy_pack.py:151](/Users/michaelrickards/dev/bh2-ACC-2/backend/tests/test_accountancy_pack.py:151), [test_accountancy_pack.py:337](/Users/michaelrickards/dev/bh2-ACC-2/backend/tests/test_accountancy_pack.py:337)

   The paid-after-end test describes a payment entered before year-end, but supplies no modification timestamp, and `FakeXero` still ignores `modified_since`. Reintroducing the old `PAID`/modified-since discovery can therefore retrieve that fixture and pass.

   There are also no endpoint tests proving worker-thread execution, session ownership, refresh behavior or `PeriodError → 400`, and no tests supplying prepayment/overpayment fixtures. These omissions matter for the stated “all fixed and proven” claim.

Review-1 disposition follows. Test references below are in [test_accountancy_pack.py](/Users/michaelrickards/dev/bh2-ACC-2/backend/tests/test_accountancy_pack.py).

| Review-1 finding | Code and regression evidence |
|---|---|
| **1. AI amounts/advice** | **Not closed.** Tests at 648/652 protect selected examples and immutable rule text, but the probes above still pass. |
| **2. Paid-invoice discovery** | **Code corrected; old-behavior regression unproven.** Payment/allocation dates replace modification dates. Test at 337 cannot model the original omission. |
| **3. T1 cash substitution** | **Fixed for the reported cash-versus-invoice defect.** Test at 538 distinguishes £100k invoiced from £65k cash including a loan, and checks credit-note deduction. The text now identifies the figure as an invoiced-sales proxy, with taxable-turnover qualifications. |
| **4. Historical mileage** | **Fixed and covered.** Test at 589 checks pre-change, post-change and spanning periods. |
| **5. Mixed currencies** | **Partially fixed.** Tests at 366/380 reject foreign invoices from GBP totals. Non-GBP base behavior remains wrong, as above. |
| **6. Invoice rounding** | **Fixed and covered.** Tests at 380/394 check the adjustment and workbook totals. |
| **7. Weak verification** | **Partially fixed.** Comparative parameters, 150-invoice paging, exact balance difference, ledger reconciliation and summer/winter time now have assertions. Modification-time, realistic allocation/refund and endpoint gaps remain. |
| **8. No-Xero comparatives** | **Fixed and covered.** Test at 404 checks prior-year £77 expense beside current figures and the Summary period. |
| **9. Reversed resolved periods** | **Code fixed; service regression covered at 259.** The endpoint’s HTTP 400 mapping is present but untested. |
| **10. Event-loop database work** | **Code moved into the worker-owned session. No regression test proves it.** |
| **11. Router bypass** | **Fixed and covered.** Tests at 697/716 exercise router use, cost attribution and profit-guard refusal. |
| **12. Naive sync timestamps** | **Fixed and covered.** Test at 492 checks UTC-to-BST crossing into the following day. |

For the aged-balance logic, I found **no additional confirmed omission or double count in the normal documented invoice/payment/allocation paths**:

- Invoice IDs are deduplicated across open invoices and later settlement discovery.
- With the allocation map supplied, invoice credit/prepayment/overpayment arrays are not also deducted. A focused probe of a £300 still-open invoice with a £100 pre-end credit returned **£200**, once.
- Focused prepayment and overpayment probes each returned **£200** for £300 invoices with £100 allocated before the end and £200 afterward.
- Batch payments expose individual payment records with invoice references; they do not require adding the batch total. Refunds referencing credit/prepayment/overpayment documents do not themselves settle another invoice. [Xero Payments documentation](https://developer.xero.com/documentation/api/accounting/payments)

The invoice `where` expressions, comma-separated `Statuses`, `Payments where Date>DateTime(...)`, and paged invoice-ID batches are consistent with the documented interfaces. Fifty requested IDs fit within the default 100-record page. [Xero Invoices documentation](https://developer.xero.com/documentation/api/accounting/invoices)

Backlog notes:

- `CreditNotes` is sent `Statuses=AUTHORISED,PAID`, but that parameter is not documented for this resource; its supported filtering uses `where`. The fake incorrectly treats it as supported. Replace it with documented filtering and add a provider-level request test. I did not establish whether production rejects or ignores the extra parameter. [Xero OpenAPI contract](https://github.com/XeroAPI/Xero-OpenAPI/blob/master/xero_accounting.yaml)
- Add explicit batch-payment, refund, overlapping-stream and multiple-ID-batch fixtures.
- Reconcile ticket documentation: A4 still says net + VAT = gross, while the implemented reconciliation correctly includes rounding.

**Verification:** all **83 ticket tests passed**, using runtime-only substitutions for in-memory SQLite and workbook temporary storage to respect the read-only environment. Additional focused probes produced the results above. `check.sh` was not run; this is not a full-green claim. No files were edited, committed or pushed; the worktree remains clean.