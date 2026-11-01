# ACC-1b: Xero's rate limit never sinks a sync

**Tier:** RED (the ledger). **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

## Why (1 Nov 2026, after ACC-1 deployed)

Mike reported "Sync didn't work". His Railway log ran from 19:53 to 20:23 and showed only the *old* deployment.
- Every sync in it failed with the pre-ACC-1 slowapi `request` error.
- The 20:23 shutdown was Railway replacing that deployment after PR #72 merged at 20:21. It wasn't a timeout.

Checking the new code for what could still fail on the first run found one real risk:
- **Xero allows 60 API calls a minute per organisation.**
- The first ACC-1 sync is a full re-read: every page of bank transactions, every page of payments, then the paid invoices 50 at a time. For a business with years of history, that is well over 60 calls in a burst.
- A 429 raised out of `run()` and lost the whole run. Nothing was written and the marker held, so every retry was another full re-read, refused at the same point. The sync could never finish.

## Fix

- `services/xero_sync._xero(call, …)` wraps every Xero call the sync makes:
  - bank transactions and payments (through `_all`);
  - invoices by id;
  - the chart (accounts and trial balance);
  - the invoice stream and contact emails.
- On a 429 it waits 61 seconds, then tries again, up to 5 tries.
  - Some provider methods raise `XeroRateLimitError`; others raise httpx's `HTTPStatusError` with status 429. Both are recognised.
  - A limit that outlasts that (Xero's daily cap of 5,000 calls) still stops the run, with the rate-limit error. Nothing is half-written, and the marker holds.
- Other errors are never retried.

**Effect:** the first full sync takes a few minutes longer while it waits out the minute, then finishes. After that, a quiet sync is 2 calls and never comes near the limit.

## Tests (`test_xero_sync.py`, 61)

- A 429 on bank transactions, payments or invoices: one wait, the run completes, and every row is written.
- A 429 from the chart (httpx form): waited out.
- A limit that never lifts:
  - exactly 5 tries and 4 waits, then a rate-limit error;
  - no rows are written and the marker doesn't move.
- A lasting limit on the account refresh (either chart call) stops the run before any write.
- A lasting limit on contact emails stops after the first contact.
- A non-429 error: not retried.
- Mutation testing: removing each of the wrap on paging, the wrap on invoices, the httpx-429 recognition and the retry decision is caught.

## Not in ACC-1b

- Railway allows 15 minutes per HTTP request. The first sync is expected to need a few. If a business's history ever needs more, the sync should move to a background job. That is backlog, not needed for Mike's data.

## Codex review 1 (`audits/ACC-1b-CODEX-REVIEW-1.md`, 1 × P1, 2 × P2) → fixed

- **P1:** once `_xero` had used up its tries, the contact-email lookup swallowed the error and started again on the next contact: 4 minutes per contact, then invoices were written anyway.
- **P2:** the chart lookup swallowed it too, so a lasting limit on `run()`'s account refresh carried on writing.
- **Fix:** a new `rate_limited(exc)` check. Both places re-raise when Xero's limit is still in force; other failures stay tolerated. The error reaches sync-all, which reports "Transaction sync failed" or "Invoice sync failed", and nothing is written.
- **P2 (tests):** the exhaustion tests asserted too little. They now assert exactly five tries, that the marker doesn't move, and the chart (each call) and contact cases. Mutation testing: removing each re-raise is caught.

## Codex review 2 (`audits/ACC-1b-CODEX-REVIEW-2.md`, targeted) → APPROVE

No P1 or P2; all three findings were confirmed fixed.
