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
