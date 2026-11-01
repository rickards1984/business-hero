Reviewed `e3f5e41` against `b0b8a37`, review 1 and North Star **P8: trust over cleverness**. Nothing modified, committed or pushed.

**P1**

1. **A genuine payment to a newly added bank can be permanently missed.**  
   The daily cache retains only bank IDs. An account absent from that cache is treated as a confirmed non-bank account: its payment is skipped, any existing payment row is archived, and the cursor advances. Refreshing the chart tomorrow does not refetch yesterday’s unchanged payment.

   Reproduced: payment to `new-bank` → zero transactions, `complete=True`, cursor advanced. Failed chart refreshes also reuse the old bank list and mark it fresh.

   Distinguish **unknown account** from **known clearing account**. Refresh unknown IDs; if classification remains unavailable, hold the cursor. [Cache](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:145), [exclusion](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:417).

**P2**

2. **Stale duplicate decisions violate one-to-one matching.**  
   `resolve()` locks, but does not validate the supplied `xero_id` against the current pending pair or existing assignments. Two browser tabs can successively hide different uploads against the same Xero row.

   Reproduced: both uploads archived; `hidden` contains two assignments to one Xero row. Arbitrary or nonexistent Xero IDs are also accepted. Reject stale/invalid pairs under the lock, and validate both sides of the assignment. [Resolution](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:435).

3. **The settings lock does not protect all new settings writers.**  
   `run()` and `resolve()` serialize correctly **when the settings row exists**, but `cached_chart()`, `contact_email()` and `invoices_done()` read and replace the whole document without first locking it. A writer can read old settings, wait behind a duplicate decision or billing update, then overwrite the committed changes.

   There is also an invoice lock-order inversion: a sync with cached emails can lock invoice rows before requesting settings in `invoices_done()`; another sync can lock settings while caching an email, then wait for those invoice rows. That permits a PostgreSQL deadlock. This is a source-level finding, not a reproduced PostgreSQL deadlock.

   Outreach/billing’s settings-first ordering is compatible with the transaction sync; I found no direct inversion with those paths. However, refreshing the chart already locks settings **before network paging**, extending contention substantially. A missing settings row is not locked by `SELECT … FOR UPDATE` either.

   Use a consistent ordering and protect every settings read-modify-write. [Chart write](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:165), [invoice settings writers](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:521).

4. **A temporary contact lookup failure becomes a permanent “no email” result.**  
   The provider returns `None` for HTTP failures; the new cache stores that forever. Reproduced with HTTP 429: two lookups made one HTTP request and retained an empty email, despite the next response being recoverable.

   Distinguish successful empty responses from failures, and retry failed lookups. [Provider](/Users/michaelrickards/dev/bh2-ACC-1/backend/providers/xero.py:161), [cache](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:530).

5. **Durable “last synced” still advances before sync-all completes.**  
   The transaction worker stamps both connection tables before invoice sync starts. If invoices subsequently fail, sync-all correctly returns `complete=False` and no timestamp, but reloading connection status reveals the newly advanced durable timestamp.

   Either make that timestamp explicitly transaction-only everywhere, or stamp overall freshness only after both parts complete. [Worker stamp](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4209), [combined result](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4548).

**Review-1 closure**

| Review-1 finding | Review-2 assessment |
|---|---|
| Clearing settlements | The aggregate £100 sales/£2 fee/£98 receipt regression passes. Known non-bank clearing payments are excluded correctly; account-cache omission remains P1 above. |
| Cross-loop refresh lock | Fixed with a behavioural three-thread regression. Nonblocking polling and `finally` release are sound. The test checks serialization, but not that waiting callers receive the refreshed token. |
| Missing settings row | Fixed; regression requires the missing live-schema fields. Concurrent creation remains uncovered. |
| Rolled-back category cache | Fixed with a behavioural regression. Pending categories and tallies publish after savepoint success; duplicate state is snapshotted/restored correctly. No regression injects failure after duplicate mutation. |
| Pair-based decisions | Ordinary Keep/Hide cases have passing behavioural regressions. Stale decisions remain defective as above. |
| Concurrent state updates | Incomplete. The regression only counts `_lock` calls in source; it does not exercise concurrency. |
| Partial timestamps/messages | Improved, but durable sync-all freshness remains defective. No behavioural orchestration regression. |
| Duplicate panel/totals refresh | Wiring is corrected: sync invalidates the panel; decisions refresh transactions and summary. No behavioural frontend regression. |
| Incremental invoice speed | Helper-level paging/cache regression passes. Actual sync-all request count, archive writes, invoice rollback and incomplete-cursor handling lack behavioural coverage. A quiet page sync now needs **at least three** requests, not the ticket’s claimed two. |

**Bank accounts and remaining checks**

- **Credit cards should count in this ledger’s bank-account scope.** Excluding card purchases while excluding repayments as transfers would lose expenses. Xero’s Accounting API represents `CREDITCARD` and `PAYPAL` as **`BankAccountType` values**, with `Type=BANK`; they are not alternative `Account.Type` values. The current filter therefore includes them when present in the cache. Add realistic fixtures, rather than changing the filter to accept an unsupported top-level type. [Xero’s official schema](https://raw.githubusercontent.com/XeroAPI/Xero-OpenAPI/master/xero_accounting.yaml).
- Ordinary invoice payments with a known bank `AccountID` pass. I found no evidence warranting a claim that standard GET Payments responses routinely require a code-only fallback; an unidentified account should nevertheless remain incomplete, not silently disappear.
- The clearing regression proves **net bank receipts**, not gross revenue and separately reported processor fees. That matches the revised ticket, but its reporting limitation should remain explicit. [Xero clearing workflow](https://developer.xero.com/documentation/guides/how-to-guides/handling-payment-processor-receipts-in-xero/).
- Transaction auth failures return to the server loop for one refresh/retry. Invoice sync can still refresh inside its worker, safely using the new thread-compatible lock. Scheduled transaction sync does **not** refresh-and-retry a refused token; it defers to the next run. The ticket’s “workers never refresh” claim is inaccurate.
- Invoice fetching uses one incremental stream including VOIDED/DELETED, archives those records, isolates SQL writes with savepoints, and uses its own session in sync-all. Mapping remains outside row error handling, so a malformed invoice can abort the run. `invoices_done()` correctly checks paging completion and recorded write failures.

**Backlog / retained limitations**

- `duplicates()` filters archived uploads but still presents archived Xero counterparts; changed/archived Xero rows leave stale bindings and review candidates.
- The partial-result UI still promises “the rest follows on the next sync,” including the non-recovering page ceiling, and omits invoice failure details.
- Successful contact-email results never expire, so later address corrections may remain invisible.
- Scheduled invoice sync still iterates Xero’s response dictionary as though it contained normalized invoice objects. This predates the review-2 diff; the new incremental invoice path only fixes the page action.
- Foreign-currency bank amounts remain a reporting limitation.

**Verification:** all **42 existing cases passed**, executed with a process-only in-memory SQLite fixture adaptation. Additional reproductions confirmed unknown-bank omission, stale double-hide and permanent caching of HTTP 429. `check.sh` was not run because its compilation and fixtures write files. No PostgreSQL concurrency, live Xero or browser verification was performed. The pre-existing untracked `data.db` remains untouched.

After repair, behavioural acceptance should cover a newly added bank, conflicting duplicate choices from two tabs, a recoverable contact lookup failure, and an invoice failure followed by reloading “last synced.”

**Verdict: REQUEST CHANGES.**