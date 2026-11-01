Reviewed `e64fc44`, including `git diff e3f5e41 HEAD`, against North Star **P8**. Nothing modified, committed or pushed.

**P1: none found.** The unknown-bank omission is fixed.

**P2 — changes required**

1. **Creating a missing settings row can erase another writer’s committed settings.**  
   `_lock()` checks for absence, then calls `_save(..., {})`. But `_save` performs an **UPDATE before INSERT**. If another writer creates and commits the row between those statements, the update replaces its settings with `{}`; no integrity exception occurs.

   A deterministic interleaving reproduced the entire document becoming empty. This needs concurrent first creation, not several independent failures. Use insert-if-absent without updating an existing row, then lock and read it. [xero_sync.py:75](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:75)

2. **Failed contact-email lookups still need not be retried by subsequent syncs.**  
   The checked provider correctly raises on failure, and the cache no longer stores that failure. However, the invoice run still reports complete and advances its cursor. An older, unchanged invoice then disappears from subsequent fetches, so its contact is never requested again.

   Reproduced through the actual invoice endpoint with simulated provider/SQL responses: first run received HTTP 429, saved a null email and returned complete; second run fetched zero invoices and made **no second contact request**. Persist pending retries and update affected invoices, or hold the invoice cursor when required lookups fail. The existing regression only calls the helper repeatedly. [main.py:4324](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4324), [main.py:4437](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4437)

3. **A stale duplicate screen can hide an upload against an archived Xero transaction.**  
   `resolve()` checks that the Xero row exists, but not that it remains active. Archiving the Xero row leaves its pending pair stored; hiding that group from `duplicates()` does not invalidate a previously loaded screen.

   Reproduced: create an ambiguous match → sync its Xero counterpart as VOIDED → submit the old Hide decision → upload becomes archived successfully. Reject Hide against archived counterparts under the lock; retain the ability to restore previously hidden uploads. [xero_sync.py:504](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/xero_sync.py:504)

**Review-2 closure**

| Finding | Assessment |
|---|---|
| Unknown accounts | Fixed, with behavioural regressions for a new bank and unresolved account. Refresh precedes writes; unresolved payments hold the cursor. Partial refresh does not advance cache freshness. |
| Stale duplicate decisions | Double-hide and nonexistent-ID cases fixed and tested. Archived-counterpart case remains above. |
| Settings serialization | Existing-row writers now lock correctly. Invoice sync locks settings before invoice writes, fixing the reported inversion. Missing-row race remains above. |
| Email failures | Provider/cache fix verified, including mocked HTTP 429. End-to-end retry remains defective. |
| Last synced | Changed to transaction-only semantics. The regression checks source text, not behaviour; remaining presentation discrepancies are below. |

`_update_doc` is **not literally used by every writer**: `run()` and `resolve()` still call `_save` directly, but both already hold the settings lock. That is not itself a defect.

**Backlog / lower-severity concerns**

- **Connection-table lock inversion:** scheduled sync stamps `accounting_connections` then `xero_connections`; token refresh writes them in reverse order. Concurrent stamping and refresh can deadlock. This is source-level evidence, not a reproduced PostgreSQL deadlock or demonstrated ledger loss. Standardize the order. [background_sync.py:608](/Users/michaelrickards/dev/bh2-ACC-1/backend/services/background_sync.py:608), [xero_oauth.py:177](/Users/michaelrickards/dev/bh2-ACC-1/backend/providers/xero_oauth.py:177)
- **Last synced remains imprecise:** sync-all returns the time after invoice processing, while durable storage records transaction-run start. Reloading can therefore change the displayed time. Return the transaction result’s timestamp and label it “Transactions last synced”; the UI and Aria context currently say only “Last synced.” [main.py:4565](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:4565)
- The generic settings PUT preserves automation/outreach fields but not ACC-1’s server-owned state. A replacement document can discard cursors and duplicate decisions. I found no frontend caller, so this is API hardening rather than a demonstrated normal-screen failure. [main.py:1492](/Users/michaelrickards/dev/bh2-ACC-1/backend/main.py:1492)
- Retained limitations: scheduled invoice sync’s old path, permanently cached successful emails, foreign-currency amounts, and net settlements without separate processor fees.

**Verification:** all **48 existing cases passed**, using a process-only in-memory SQLite fixture adaptation. Additional reproductions established the three P2 findings above. No PostgreSQL concurrency, live Xero or browser verification was performed. `check.sh` was not run because it writes files; the pre-existing untracked `data.db` remains untouched.

After repair, Mike’s behavioural checks are: recover an invoice email after a temporary lookup failure, reject a stale Hide after the Xero row is voided, and confirm the transaction timestamp stays consistent after reload.

**Verdict: REQUEST CHANGES.**