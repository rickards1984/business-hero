# ACC-2 Codex review 3

Model gpt-6-astra · session 01a19d44-c48b-76f1-8760-e938bff5d082 · 63,118 tokens · verdict **CHANGES REQUIRED**

## Prompt

```
Read-only review 3 (the last cycle) of ticket ACC-2, branch ticket/ACC-2-accountancy-pack in this worktree. Review `git diff HEAD~1..HEAD` (the review-2 fixes) in the context of the whole ticket (`git diff origin/main...HEAD`). Your review 2 is audits/ACC-2-CODEX-REVIEW-2.md; the builder's response is the "Codex review 2" section of docs/ACC-2-TICKET.md.

Note: for finding 1 (AI line), Mike, the owner, made a product decision on 2 Nov 2026 to keep the AI line, labelled as AI-written and possibly imprecise, with a stronger filter, accepting the residual risk documented in the ticket. Do not re-raise that decision itself; do check the label, the filter and that the rule text/figures can never be changed.

Confirm each other review-2 finding is fixed and proven by a test that fails on the old behaviour (non-GBP base; daemon-thread timeout; unrenewed token / unreadable organisation fallback via accountancy_pack.connect and the endpoint; If-Modified-Since-aware fake, prepayment/overpayment, ID batches, endpoint thread + 400; CreditNotes `where`). Look for any new defect these changes introduced (e.g. thread safety of the future settle, the session used by connect then build, currency format, fallback when provider is dropped mid-build).

Output: APPROVE or CHANGES REQUIRED; P1/P2 with file:line and a concrete failure; backlog notes. Do not edit, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED**

1. **P1 — The new fallback path can still present foreign invoices as pounds.**  
   [accountancy_pack.py:778](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:778), [accountancy_pack.py:921](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:921)

   When Organisation fails, the provider is dropped and currency defaults to GBP. The fallback invoice query ignores the stored `invoices.currency`.

   **Reproduced:** a stored USD 120 invoice, with Organisation unavailable, produces **“Currency: GBP”** and gross **120 with `£#,##0.00` formatting**. No conversion occurred. Failed renewal reaches the same fallback. Preserve each invoice’s currency or exclude unsupported currencies with an explicit explanation.

2. **P2 — Endpoint fallback regression proof remains incomplete.**  
   [test_accountancy_pack.py:874](/Users/michaelrickards/dev/bh2-ACC-2/backend/tests/test_accountancy_pack.py:874)

   The endpoint test replaces both `connect` and `build`. It proves off-main-thread invocation and exception-to-400 mapping, but not real fallback, reason propagation, or session ownership across connection and workbook construction.

   **Confirmed surviving mutation:** changing the endpoint to pass `xero_error=None` leaves **all 98 tests green**, despite losing the renewal-failure explanation. Add endpoint tests using real `connect` and `build`, faking only external dependencies, for failed renewal and unreadable Organisation; assert workbook contents, failure reason and worker-owned session use.

Review-2 disposition:

| Item | Result |
|---|---|
| AI decision | Accepted. Stronger filter, explicit “AI-written, may be imprecise” label, and immutable rule text/figures are implemented and tested. Production sends only titles to the model. |
| Non-GBP base | Working-provider path fixed and tested; disabling GBP-only tax gating fails the test. **Fallback remains defective above.** |
| Daemon-thread timeout | Fixed. The blocking-router test fails against the previous implementation, taking approximately 0.61 seconds. Future settlement runs on the event loop, checks completion there, and tolerates a closed loop; no confirmed settlement race. |
| Unrenewed token | `connect` rejects it. Restoring expired-token use fails the regression test. Endpoint integration proof remains incomplete. |
| Unreadable Organisation | Service fallback and reason are tested; the previous implementation fails that test. Endpoint integration proof remains incomplete. |
| If-Modified-Since fake | Fixed. Restoring PAID/modified-since discovery makes the £1,200 historical-debt test fail. |
| Prepayment/overpayment | Covered. Independently omitting either allocation stream fails the test. |
| ID batches | Covered. Increasing the batch size beyond fifty fails the 60-invoice test. |
| Endpoint thread + 400 | Covered at wrapper level, subject to finding 2. |
| CreditNotes `where` | Fixed; the fake rejects the old `Statuses` parameter. The replacement uses [Xero’s documented status filtering](https://developer.xero.com/documentation/api/accounting/creditnotes/). |

Backlog notes:

- Add a provider-level request assertion for CreditNotes filtering.
- Add explicit batch-payment/refund and overlapping-stream fixtures.
- Reconcile the ticket’s older “As built” and AI descriptions with the final implementation.
- Bound concurrent lingering wording threads if provider stalls become operationally significant.

**Verification:** 98 tests passed using runtime-only in-memory SQLite and workbook storage substitutions. Additional probes and mutations produced the results above. `check.sh` was not run; this is not a full-green claim. No files edited, committed or pushed; worktree remains clean.