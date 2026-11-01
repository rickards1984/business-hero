# ACC-1 — Xero sync that brings in everything, once

**Tier:** RED (money: the ledger every report and the accountancy pack read). **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

## Why (Mike, 31 Oct – 1 Nov 2026)

Transactions in Business Hero stop at 4 July 2026, though Xero has everything reconciled to yesterday. Mike reconciled mostly by Match / auto-reconcile against his own earlier entries, plus some Create.

The code shows several faults, any of which can lose data, and together they explain what Mike sees:
1. **Only Xero "bank transactions" are fetched.** A line reconciled by matching an invoice or bill is a Xero *payment*, and is never fetched.
2. **A silent cap of 10 pages (1,000 transactions).**
3. **Transfers are counted as expenses.** Xero's `SPEND-TRANSFER` and `RECEIVE-TRANSFER` are treated as "not RECEIVE", so both legs of a transfer between Mike's own accounts become expenses. `RECEIVE-OVERPAYMENT` and `RECEIVE-PREPAYMENT` are booked as expenses for the same reason.
4. **The "last synced" marker always advances,** even after the 1,000 cap or after the sync stopped at 10 errors. Whatever was missed is never fetched again.
5. **One bad row can fail the rest.** All rows share one database transaction, so a single failure (for example a reference longer than 100 characters) poisons every row after it.
6. **Xero changes don't all arrive.**
   - A date changed in Xero isn't updated.
   - A transaction deleted or voided in Xero stays in Business Hero.
   - The marker is set *after* fetching, so changes made in Xero during a sync are missed.
7. **"Sync all" reports success even when the transaction sync failed.** The page only speaks when something is new, so a failure looks like "nothing new".
8. **The sync blocks the server.** The endpoints are `async` but do blocking database work, so while a sync runs (it starts automatically when the page opens), every other request waits. That includes the connection check, which is why the page showed "Based on uploaded data" for minutes.
9. **Nothing shows where a transaction came from** (Xero, upload or typed in), and Xero copies of uploaded transactions would double-count.

## Decided by Mike (1 Nov 2026)

1. **Order:** ACC-1 (this ticket), then ACC-2 (the accountancy pack, checked figure by figure), then the small housekeeping, then Mike's daily use.
2. **Duplicates: Xero wins, and the upload is hidden.**
   - A match is the same direction, the same amount to the penny, and dates within 3 days.
   - With exactly one matching upload, the upload is archived: hidden from the books, never deleted, and restorable.
   - With two or more possible uploads, nothing is hidden; they go on a "check these" list for Mike.
3. **Xero payments count** as Xero records them. Money in from customer invoices and money out on bills appear as income and expense on the date paid, with the invoice or bill as reference and its category.
   - **Transfers between Mike's own accounts are never income or expense.** They're left out of the books here, because storing them needs a database change (the type column allows only income and expense). Profit and loss is unaffected.

## What gets built

**`services/xero_sync.py`, testable with a fake Xero:**
- **Paging:** each list (bank transactions, payments) is read page by page until a short page.
  - A safety ceiling of 500 pages, if hit, stops the run *incomplete*. It is never silent.
- **Bank transactions:**
  - `RECEIVE`, `RECEIVE-OVERPAYMENT`, `RECEIVE-PREPAYMENT` → income.
  - `SPEND`, `SPEND-OVERPAYMENT`, `SPEND-PREPAYMENT` → expense.
  - `*-TRANSFER` → not a transaction. Any row stored for it earlier is archived, which repairs fault 3.
  - `DELETED` or `VOIDED` → the stored row is archived. If it reappears, it is restored.
- **Payments:** external id `payment:<PaymentID>`. Amount is `BankAmount` (the bank account's currency), else `Amount`.
  - **Money in:** `ACCRECPAYMENT` (a customer pays an invoice), `APCREDITPAYMENT` (a supplier refunds a credit note), `APOVERPAYMENTPAYMENT` and `APPREPAYMENTPAYMENT` (a supplier refunds an overpayment or prepayment).
  - **Money out:** `ACCPAYPAYMENT` (Mike pays a bill), `ARCREDITPAYMENT`, `AROVERPAYMENTPAYMENT`, `ARPREPAYMENTPAYMENT` (refunds to customers).
  - **Description:** the contact, then "invoice/bill <number>".
  - **Reference:** the invoice number.
  - **Category:** the invoice's largest line's account, through the chart lookup. Invoices are fetched by id, 50 at a time.
  - An unknown payment type is skipped and logged. A `DELETED` payment is archived.
- **Each row is written in its own savepoint.** One bad row is reported and the rest are kept.
  - Text is cut to the column sizes (reference 100, payee 255).
  - The date, amount, type, description, reference and payee follow Xero. A category the owner set is kept if Xero has none.
- **The marker:**
  - The next cursor is the moment the run *started*, less 5 minutes.
  - It advances only when the run was complete: every page read and no row failed. Otherwise it stays, and the next run fetches the same window again; writes are idempotent.
  - The first run after this ships is a **full** re-sync (a version flag), which brings in everything since Mike started and repairs past faults.
- **Duplicates (decision 2):**
  - Candidates are only *uploaded* rows (`import_id` set, no external id, not archived) of the same business.
  - An upload is matched once at most.
  - A pair Mike restores ("keep both") is remembered and never hidden again.
  - The pairings and the review list are kept in the business settings document.

**Endpoints:**
- **`POST /v1/accounting/xero/sync`** keeps its token handling. The work runs in a worker thread, so the server stays free. It returns:
  - `new`, `updated`, `archived`, `duplicates_hidden`, `needs_review`;
  - `errors` (the first 5);
  - `complete`.
- **`POST /v1/accounting/sync-all`** reports each part's real outcome. `success` is false if the transaction sync failed.
- **`GET /v1/accounting/duplicates`:** the review list, plus the uploads hidden as duplicates.
- **`POST /v1/accounting/duplicates/resolve`**, with `{upload_id, action: "hide" | "keep"}`:
  - **hide** archives the upload;
  - **keep** restores it and remembers the pair as not a duplicate.
- **`GET /v1/accounting/transactions`:** each row gains `source`, one of `xero`, `xero_payment`, `upload` or `manual`.

**Screen (Accounting):**
- While the connection is being checked, the page says "Checking connection…", never "Based on uploaded data".
- Every sync result is shown, including "up to date", a partial run and a failure.
- Each transaction shows its source.
- A "Possible duplicates" panel lets Mike review, hide or keep.

## Not in ACC-1

- Storing transfers (needs the type column widened).
- The accountancy pack (ACC-2).
- FreeAgent and QuickBooks, which are unchanged.

**Tests first:** `backend/tests/test_xero_sync.py`.

**Mike approved the rules and tests on 1 Nov 2026,** and added a requirement: after the first full sync it must be fast, with no needless calls to Xero or OpenAI.

## Root cause found while building

**From 6 July 2026, no sync from the page ever ran.** That day's security work (commit `a84796f`) added a rate limit to the Xero sync endpoints. `POST /v1/accounting/sync-all`, which the page uses, called those decorated functions without a `request`. slowapi refuses that before any work is done, and sync-all swallowed the error and reported success. Mike's transactions stop on **4 July**.
- `sync-all` now calls the undecorated functions, passing the request. sync-all is itself rate-limited, so each click counts once.
- A regression proves the decorated call fails without a request, and that sync-all no longer makes it.

**A second, scheduled path** (`services/background_sync.py`) treated Xero's records as objects of another type, so every Xero row failed silently. It also did its database work on the server's event loop. For Xero it now goes through the same `xero_sync.run`, in a worker thread.

## As built

- **`services/xero_sync.py`:** `run`, `resolve`, `duplicates`, `source_of`, `cached_accounts` and `accounts_from_trial_balance`.
- **Provider (`providers/xero.py`):** `get_payments` and `get_invoices_by_ids`, both read only.
- **`main.py`:**
  - `sync_xero_transactions` keeps its token handling and runs `_xero_sync_work` in a worker thread, with its own session and event loop.
  - `sync-all` reports `success` from each part's real result, and its invoice sync is also off the event loop.
- **`accounting.py`:** the list returns `source`; `GET /duplicates` and `POST /duplicates/resolve`.
- **Screen (`Accounting.tsx`):**
  - "Checking connection…" while the connection is checked;
  - honest sync messages: done, partly done, didn't finish, duplicates hidden or to check;
  - each row's source;
  - the "Possible duplicates" panel: Review, Hide, Keep, Restore.
- **Speed:** after the first full run, a sync with nothing new makes **two** Xero requests. The chart of accounts is read at most once a day. The page reads only Business Hero's own data, and the profit and loss figures use the existing 8-hour cache.
- **Tests:** `test_xero_sync.py` has 32 tests. Ten mutations, one per fix including the root cause, are each caught.
- **Two test fixtures** for the existing accounting isolation tests gain the live columns, and the expected rows gain `source`.

**After deploy:** the first sync, from the page or the next scheduled run, re-reads everything from Xero. Expect a few minutes; it runs in the background.

## Codex review 1 (`audits/ACC-1-CODEX-REVIEW-1.md`, 1 × P1, 8 × P2) → fixed

Codex confirmed the root cause and the fix, and all eight payment-type directions against Xero's documentation.

**P1. The books are cash in and out of BANK accounts only.**
- With a card processor, invoice payments go to a *clearing* account, and the bank receipt that settles it (net of fees) is the cash. Counting both doubled the income.
- A payment counts only when its account is a Xero `BANK` account. The bank accounts are read with the chart of accounts, at most once a day.
- A payment into any other account is skipped, and any row stored for it earlier is archived. If the bank accounts can't be read, no payment is recorded and the run is incomplete, so the marker holds.

**P2 fixes:**
1. **Token refresh is serialised across event loops and threads.** The shared lock is now a threading lock, awaited politely.
   - The transaction worker reports a refused token; the server's loop refreshes and retries once.
   - The scheduled job hands its provider, already refreshed on the server's loop, to the worker, and defers a refused token to its next run.
   - The invoice sync may still refresh inside its worker, which the thread-safe lock now permits.
2. **A business with no settings row gets one** with `id`, `created_at` and `updated_at`, as the live table requires.
3. **A failed row can't poison the next.** Categories created inside a row's savepoint are published to the cache only if it succeeds. Tallies and duplicate changes are applied only on success, and restored on rollback.
4. **Duplicate decisions are per pair.** A "keep" is remembered for that upload and that Xero row only; the upload can still match another Xero row. Keeping one candidate leaves the others for review. Hiding one settles that Xero row and frees its other candidates. The review list leaves out anything no longer a visible upload.
5. **One writer per business:** a sync's write phase and every decision lock the settings row first.
6. **"Last synced" moves only on a complete sync,** on screen and in the scheduled job. `success` means it ran; `complete` means nothing was missed. A partial sync now says so.
7. **The duplicates panel reloads after every sync,** and a decision refreshes the totals too.
8. **Speed: the page's invoice sync is incremental.**
   - One paged stream of invoices changed since the last complete sync: open, paid, voided and deleted together, with no silent 20-page cap.
   - Each customer's email is asked of Xero once, ever.
   - Each invoice is written in its own savepoint.
   - **New: an invoice voided or deleted in Xero is archived here,** so it's never chased.
- **Also:**
  - the invoice worker in sync-all has its own session;
  - `IDs` requests carry `page=1`, so Xero returns line items;
  - the run's ceiling message is honest.
- **Tests:** 42. Eight more mutations, one per fix, are each caught. The per-business lock is checked from the source.

## Codex review 2 (`audits/ACC-1-CODEX-REVIEW-2.md`, 1 × P1, 4 × P2) → fixed

**P1. An account Business Hero doesn't recognise is never assumed not to be a bank.**
- Accounts are cached by kind: bank (including credit cards and PayPal, which Xero types as BANK) and other.
- A payment to an account in neither list makes the run read Xero's accounts again, before any writing.
- If it's still unknown, the payment isn't recorded: the run is incomplete, so the marker holds and it is tried again.
- A chart refresh that partly failed is never marked fresh.

**P2 fixes:**
1. **Duplicate decisions are checked under the lock.**
   - The Xero row must exist.
   - "Hide" needs the pair to be pending and that Xero row not already matched.
   - "Keep" needs the pair to be pending or currently hidden.
   - A decision from a stale screen gets 409.
2. **Every settings write locks first** (`_update_doc`): the chart, contact emails, cursors and duplicates.
   - A missing settings row is created, then locked.
   - Settings are always locked before invoice or transaction rows, the order outreach and billing use too.
   - Missing contact emails are looked up before the invoice writes begin.
   - The chart is written and committed before the run's paging, so no settings lock is held across network calls.
3. **A failed contact lookup is never remembered as "no email";** it is asked again. A confirmed empty answer is kept.
4. **"Last synced" has one meaning everywhere: the transactions (the ledger) fully synced.** That is what the worker stamps, and what sync-all returns. An invoice failure is reported separately on screen: "Transactions synced, but invoices didn't…".
- **Also:**
  - a malformed invoice is reported and skipped, never ending the run;
  - review groups whose Xero row is archived are left out;
  - the partial-sync message quotes the real reason.
- **Tests:** 48. The new mutations are caught, apart from the one-to-one guard, which is redundant behind the pending-pair check; the stale-tab regression covers the scenario.
- **Backlog:**
  - the scheduled invoice sync still uses the old path (it writes nothing for Xero, so does no harm);
  - cached contact emails never expire;
  - foreign-currency bank amounts;
  - net settlements mean processor fees aren't shown separately;
  - concurrency is checked by tests that inspect the code, not by a PostgreSQL race test.

## Codex review 3 (`audits/ACC-1-CODEX-REVIEW-3.md`, 0 × P1, 3 × P2) → fixed

**P2 fixes:**
1. **Creating a missing settings row never overwrites one.**
   - `_lock` inserts the row only if it is absent (`INSERT … SELECT … WHERE NOT EXISTS`), then locks it and reads it.
   - It never updates, so another writer's committed settings can't be replaced with `{}`.
   - The race regression fails on the old code.
2. **A failed contact-email lookup holds the invoice cursor.**
   - `lookup_emails` returns `(found, failed)`, and any failure makes the invoice run incomplete.
   - The marker stays put, so the next sync fetches that invoice again and asks for the email again.
3. **"Hide" against an archived Xero transaction gets 409.**
   - A voided Xero row can't swallow an upload from a stale screen.
   - "Keep", which restores a hidden upload, still works.

**Lower-severity items, also fixed:**
- Connection stamps are written `xero_connections` first, then `accounting_connections`: the order token refresh uses, so the two can't deadlock.
- sync-all's `synced_at` is the transaction run's own timestamp, and the Accounting page says "Transactions last synced".
- The generic settings PUT now preserves the `xero_*` keys and `accounting_duplicates`, as it already did for automations and outreach.

**Tests:** 52 in `test_xero_sync.py`. `./check.sh full` is green (4045 passed).

**Backlog, unchanged:**
- the scheduled invoice sync's old path;
- cached emails never expire;
- foreign-currency amounts;
- net settlements;
- no PostgreSQL race test.

## Codex review 4 (`audits/ACC-1-CODEX-REVIEW-4.md`, quick targeted) → APPROVE

No P1 or P2. It confirmed all three review-3 fixes, the smaller items, and that sync-all can no longer hit the slowapi `request` error that production still logs on main.
