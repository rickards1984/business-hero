Reviewed `ticket/ACC-1-xero-sync` at `b0b8a37`, against `origin/main`, the approved ticket and North Star **P8**. Nothing modified, committed or pushed.

**P1 — must fix**

1. **Clearing-account settlements double-count income.**  
   Xero explicitly documents applying invoice Payments to a clearing account, then reconciling the settlement using a Receive Money transaction. ACC-1 imports both as income, under different external IDs; its dedupe only considers uploads. I reproduced **£100 becoming £200 income**.

   This needs account-aware treatment and a regression covering aggregated settlements and fees—not matching Xero records merely by amount/date. [Xero’s documented workflow](https://developer.xero.com/documentation/guides/how-to-guides/handling-payment-processor-receipts-in-xero/), [mapping code](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:161).

**P2 — changes required**

2. **Token refresh now crosses event loops, but its lock cannot.**  
   Worker calls to `asyncio.run` reach the same process-global `asyncio.Lock` used by requests and other workers. Under contention, this can fail or leave waiters unwoken. I reproduced “bound to a different event loop” using the existing lock. Use coordination that works across threads, or keep refresh on one owning event loop. [Worker refresh](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4201), [shared lock](/Users/michaelrickards/dev/bh2-ACC-1/backend/providers/token_refresh_lock.py:23), [Python’s documented restriction](https://docs.python.org/3.11/library/asyncio-sync.html).

3. **Creating a missing settings row fails against the recorded live schema.**  
   `_save` inserts only `business_id` and `settings`. The schema evidence requires `id`, `created_at` and `updated_at`, with no database defaults; the model’s Python defaults do not apply to raw SQL. I reproduced the NOT NULL failure. This prevents sync completion for businesses without settings. [Insert](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:53), [schema evidence](/Users/michaelrickards/dev/bh2-ACC-1/audits/live-schema-public.txt:201).

4. **A failed row can still poison later rows through the category cache.**  
   `_category` caches a newly inserted category ID inside the row’s savepoint. If the transaction insert subsequently fails, rollback removes the category but leaves its ID cached. Following valid rows using that category fail their foreign key. I reproduced this failure chain. Publish cache entries and success counters only after successful savepoint completion, or restore them on rollback. [Category creation](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:195), [row processing](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:312).

5. **Duplicate resolution loses unresolved choices and does not remember pairs.**  
   With one Xero row and two candidate uploads, choosing **Keep** for one removes the entire review group. The other candidate remains counted but disappears from review. I reproduced that transition. Also, `kept` stores upload IDs globally: keeping an upload against Xero row A excludes it from matching a genuinely duplicate Xero row B. That differs from the approved *pair* rule. Resolution should identify the pair, preserve outstanding candidates and enforce one-to-one assignments across overlapping groups. [Dedupe](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:255), [resolution](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:352).

6. **Concurrent syncs and duplicate decisions can overwrite each other’s state.**  
   The run holds its duplicate document in memory while processing rows, then replaces the stored document without locking or conflict detection. A concurrent Keep/Restore can be lost; overlapping syncs can lose pairing history despite committed archive changes. Re-reading the outer settings document does not refresh the already-held `dups`. Serialize these operations per business or use transactional conflict protection. [State write](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:306).

7. **Incomplete runs still acquire misleading “last synced” timestamps.**  
   The scheduled caller ignores `complete=False` and subsequently updates `accounting_connections.last_sync_at` unconditionally. The frontend likewise adopts `synced_at` for HTTP-200 failure results. The durable service cursor stays safe, but the displayed freshness becomes false. Additionally, `syncMessage` checks `success=False` before `complete=False`, making the intended partial-result message unreachable for actual partial service responses. [Scheduled stamp](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/background_sync.py:471), [frontend handling](/Users/michaelrickards/dev/bh2-ACC-1/frontend/client/src/pages/Accounting.tsx:94).

8. **The duplicate panel does not refresh after sync.**  
   It fetches on mount and after its own decisions, but receives no sync invalidation. Newly discovered duplicates can remain invisible while the Transactions tab stays open. Hide/Restore refreshes the transaction list only, leaving summary figures stale. Refresh both the duplicate list and affected totals after these operations. [Panel](/Users/michaelrickards/dev/bh2-ACC-1/frontend/client/src/pages/Accounting.tsx:1912), [callback](/Users/michaelrickards/dev/bh2-ACC-1/frontend/client/src/pages/Accounting.tsx:1527).

9. **The two-call speed requirement is not met by the page’s sync path.**  
   A quiet transaction-service run makes two calls with a fresh chart cache. But sync-all subsequently re-fetches outstanding and paid invoices, plus potentially contact emails, every time. Thus the actual page action remains dependent on the full invoice history. The speed test bypasses this orchestration. Make that path incremental/cached and test its request count. [Invoice fetches](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4285), [sync-all invocation](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4496).

**Other checks and backlog**

- **Root cause: supported; fix correct.** Commit `a84796f` added the decorators and required `request`. Installed slowapi **0.1.10** rejects the old invocation and exposes `__wrapped__` through `functools.wraps`. Passing `request` to the undecorated functions is correct. Sync-all retains **10/minute per user/IP**, and direct endpoints remain limited. This establishes the broken page path, rather than independently proving historical production activity.
- **Paging/cursor:** both streams page correctly; 500 full pages return incomplete without advancing the version/cursor. Start time minus five minutes is correctly used. However, “the next sync carries on” is inaccurate at the ceiling: it restarts the same window and hits the same ceiling. Report that limit honestly.
- **Mappings:** the six receive/spend types and transfer exclusion match the approved rules. All eight PaymentType directions match Xero’s documented semantics, including supplier refunds as money in and customer refunds as money out. [Xero types](https://developer.xero.com/documentation/api/accounting/types/).
- **Overlap:** ordinary invoice payments, prepayment/overpayment allocations and batch membership are not grounds to discard matching amounts. Refunds are distinct cash movements; batch Payments should be counted individually without adding the batch total. The confirmed overlap defect is the clearing-account workflow above. [Payments documentation](https://developer.xero.com/documentation/api/accounting/payments).
- **Amounts:** `BankAmount`, including zero, takes precedence correctly; `Amount` is the fallback. This follows the approved rule. Foreign-currency bank accounts remain a limitation: bank currency is not necessarily the GBP currency displayed by this ledger.
- **Categories:** IDs are deduplicated and batched at 50 correctly. **Unverified provider contract:** the request supplies `IDs` without `page`; Xero documents paging as a way to obtain collection line details. Add `page=1` or establish the bulk-ID response contract with a realistic provider test. The fake always returns line items. [Provider request](/Users/michaelrickards/dev/bh2-ACC-1/backend/providers/xero.py:116), [Xero invoices](https://developer.xero.com/documentation/api/accounting/invoices).
- **Archive/update:** deletion, voiding, restoration, date updates and category preservation are implemented. Dedupe runs on updated rows during full re-sync. Existing hidden/review bindings bypass rematching; stale review candidates need explicit handling.
- **Sessions:** transaction workers own their sessions correctly. Invoice sync borrows the request session sequentially, so ordinary execution does not concurrently use it; cancellation can nevertheless leave the worker running while request cleanup closes it. Give that worker its own session too. Initial token refresh still performs blocking work on the server loop.
- **Endpoints/UI:** duplicate queries and mutations are tenant-scoped; feature gates precede service work and the plan inventory includes both routes. Source indexing/labels and the initial checking label look correct. No additional direct page-load Xero fetch was introduced.
- **Separate PR #71:** the clock-pinning changes are separate from the ACC-1 findings.

**Verification:** all **32 tests passed** with a process-only adaptation replacing the file-backed SQLite fixture with an in-memory database. Additional reproductions exposed the defects above. The existing suite lacks real schema constraints, rollback-after-category-creation coverage, clearing settlements, concurrent execution and behavioral orchestration tests; several wiring tests only inspect source strings.

I did not run `check.sh full`: it writes compiled files and uses filesystem-backed tests, contrary to this read-only review. No live Xero or production database verification was performed.

After fixes, the behavioral checks are: sync a clearing settlement once, keep one of multiple duplicate candidates while retaining the others for review, see the panel/totals refresh immediately, and confirm a partial sync leaves the last-success timestamp unchanged.

**Verdict: REQUEST CHANGES.**