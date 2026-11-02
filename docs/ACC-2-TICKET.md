# ACC-2: an accountancy pack an accountant can trust

**Tier:** RED (money: figures handed to an accountant, and tax points). **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

## Why (Mike, 1–2 Nov 2026)

The pack must be "of the highest standards possible as a first draft to give to an accountant": accurate, complete, and with legal tax-saving points. The aim is efficient bookkeeping and lower accountancy fees.

## What the current pack gets wrong (`GET /v1/accounting/export/accountant-pack`, main.py)

1. **The Summary's "Net Profit/Loss" is bank money in minus money out.** It is gross of VAT, and it counts loan repayments, asset purchases and drawings as costs. It sits beside Xero's real P&L with nothing explaining the difference.
2. **Aged Receivables and Payables call Xero's `AgedReceivablesByContact` without a contact,** which the report requires. The call fails and the tab is quietly dropped. Even if it worked, it would show *today's* position, not the position at year end.
3. **A failed Xero report quietly drops its tab,** yet the Summary still says "Reports included: P&L, Balance Sheet, Trial Balance, Aged…".
4. **The Invoices tab lists every invoice ever,** not those in the period, and gives gross amounts only.
5. **The default period is the 6 April tax year.** A limited company's accounts run to its own year end.
6. **Missing:**
   - comparatives (last year);
   - a list of loose ends (uncategorised and unreconciled lines, possible duplicates, an incomplete sync);
   - tax points.
7. **Speed:**
   - five Xero reports are fetched one after another;
   - the database work blocks the server;
   - the "Generated" time is the server's UTC time, not UK time.
8. **The report writer turns any number-like text into £ currency,** for example an account code in a cell of its own.

## Decided by Mike (2 Nov 2026)

1. **The default period is the business's own financial year from Xero** (Organisation `FinancialYearEndDay` and `FinancialYearEndMonth`): the last *completed* year. If there is none, it falls back to 6 April–5 April. Any dates can still be chosen.
2. **The P&L and balance sheet show last year alongside this year.**
3. **Tax points are rules from the business's own figures, with AI wording.**
4. **Businesses without Xero get a P&L built from Business Hero's own transactions.** It is labelled as cash basis and unaudited, and has no balance sheet.

## The pack (Excel, one workbook)

| Tab | Contents | Source |
|---|---|---|
| **Summary** | Business name; legal type (company or sole trader, from Xero); period; generated time (UK time); what is in the pack and what isn't, with the reason; headline figures from the P&L; the loose-ends count | built |
| **Profit & Loss** | This period and the prior period, side by side | Xero `ProfitAndLoss`, `periods=1&timeframe=YEAR` (with Xero); otherwise built from the ledger by category |
| **Balance Sheet** | At period end and a year earlier | Xero `BalanceSheet`, `periods=1&timeframe=YEAR`; omitted without Xero, with the reason |
| **Trial Balance** | At period end | Xero |
| **Aged Debtors / Aged Creditors** | Outstanding **at period end**, by contact, in buckets: current, 1–30, 31–60, 61–90 and 90+ days | built from Xero invoices (ACCREC / ACCPAY): the total less payments and credits dated on or before the period end |
| **Invoices** | Sales invoices *issued in the period*: number, customer, issue date, due date, net, VAT, gross, status today, outstanding today | Business Hero `invoices` (synced from Xero) |
| **Transactions** | Every ledger line in the period, with source (Xero, Xero payment, upload, manual) and category | Business Hero |
| **Cash Summary** | Money in and out by category, **clearly labelled "cash movements, not profit"**, with a note on why it differs from the P&L (VAT, timing, capital items, transfers) | built |
| **Loose Ends** | Each with count, value and what to do:<ul><li>uncategorised lines;</li><li>unreconciled lines;</li><li>possible duplicates waiting for review;</li><li>last complete sync earlier than the period end, or incomplete;</li><li>a balance sheet that doesn't balance</li></ul> | built |
| **Points to Discuss** | The tax points (below) | rules plus AI wording |

## Accuracy rules (each one tested)

- **A1.** Every figure on a Xero-sourced tab is Xero's number. Text is never turned into a number unless Xero marks the cell as a value: a value cell in a data row or summary row, not a heading or code.
- **A2.** Every total on a built tab equals the sum of its lines, to the penny, using `Decimal`, never `float`.
- **A3.** Aged balances at the period end: for each invoice dated on or before the end, outstanding = total − payments − credits allocated − overpayments allocated, *each dated on or before the end*. Voided and deleted invoices are excluded. Invoices fully paid by the end are excluded. Buckets are by due date, relative to the period end.
- **A4.** The Invoices tab holds exactly the sales invoices whose issue date falls in the period, and net + VAT + rounding = gross on every row. Xero's rounding is shown, never hidden.
- **A5.** The Summary lists a tab as included only if it was built. A missing tab is listed with its reason, never silently.
- **A6.** The balance-sheet check: total assets − total liabilities = total equity. If not, it goes on Loose Ends, and the pack is still produced.
- **A7.** The ledger P&L (without Xero): income and expense by category, transfers excluded, labelled "cash basis — unaudited". Totals tie to the Transactions tab exactly.
- **A8.** Periods: the default is the last completed financial year, from Xero's year-end day and month (for example, year end 31 March, generated 2 Nov 2026 → 1 Apr 2025–31 Mar 2026). The prior period is the same length, a year earlier. Leap years are handled.
- **A9.** The sync check: if Business Hero's last complete Xero transaction sync is earlier than the period end, Loose Ends says so, with the date.

## Tax points (rules; each shows the figures that triggered it)

Every point is framed **"Points to discuss with your accountant"**, with the figures behind it, never an instruction. UK thresholds are **checked against GOV.UK when built** and held in one dated table in the code.

| # | Fires when | Says (in substance) |
|---|---|---|
| T1 | Not VAT-registered, and taxable turnover over the last 12 months ≥ 80% of the VAT threshold | how close turnover is; registration becomes compulsory at the threshold |
| T2 | Single purchases ≥ £500 in equipment, computer, tools or vehicle categories | these may qualify for capital allowances (AIA or full expensing) rather than being treated as ordinary costs; check the treatment |
| T3 | A company with no employer pension contributions in the period | employer pension contributions are normally deductible for corporation tax |
| T4 | A sole trader with no use-of-home cost | simplified expenses or the actual-cost method for working from home |
| T5 | Fuel or vehicle spend, but no mileage claims | mileage allowance versus actual costs |
| T6 | Company profit within 10% of a corporation-tax band edge (small profits limit or main rate limit) | marginal relief, and how the timing of planned spending affects the band |
| T7 | Uncategorised spending > £0 | uncategorised spending may hide allowable expenses; categorise it before the accounts are filed |
| T8 | Staff entertainment spend present (company) | the annual-event exemption per head, and trivial benefits |

- **Rules decide whether a point appears and what its figures are.** AI never decides either.
- **The AI only rewords the explanation.** It gets the rule's text and figures, and returns at most 3 plain-English sentences. Any number in its text that isn't one of the rule's figures causes the AI text to be discarded and the rule's own text used instead. The same fallback applies if the AI fails or times out. The pack never waits more than 15 s for wording.
- **One AI call per pack** covers all points. Its cost goes to the AI cost ledger (`ai_costs.record`, purpose `accountancy_pack`), so it is covered by plan pricing (profit rule).
- Both the business's legal type (company or sole trader) and VAT registration come from Xero's Organisation record. **Without Xero, only the points that don't need them appear.**

## Speed

- Xero calls run **concurrently**: at most 5 at once, Xero's limit. Each goes through `xero_sync._xero` (rate-limit waits).
- Database work runs in a worker thread.
- Typical pack: about 6 Xero calls, plus invoice pages for the aged tabs, plus 1 AI call. The goal is under 20 seconds for Mike's data.
- Nothing is fetched until the button is pressed.

## Not in ACC-2

- PDF output.
- Filing.
- Corporation tax or self-assessment calculations.
- Multi-currency revaluation.
- A balance sheet without Xero.

## Tests first: `backend/tests/test_accountancy_pack.py`

- A fake Xero carries the organisation, P&L, balance sheet, trial balance and invoices with payments.
- The workbook is read back with openpyxl, and each rule (A1–A9, T1–T8, the AI rules) has at least one test.
- Mutation testing is done per rule.

## As built

> **Where the reviews below differ, they describe the final code.** In particular, the AI never rewords a point's explanation. It may add a separate, labelled "In plain words" line (review 1, and Mike's decision in review 2), and invoices for the aged tabs come from payment and allocation dates, not "modified since" (review 1).

- **`services/accountancy_pack.py`:**
  - `build()` makes the workbook, and the endpoint is a thin wrapper that runs it in a worker thread.
  - Pure helpers, each tested:
    - `default_period`, `prior_period`;
    - `report_rows`, `find_value`, `balance_difference`;
    - `aged`, `period_invoices`;
    - `ledger_pnl`, `facts_from`, `tax_points`, `word_points`;
    - `loose_ends`.
  - `THRESHOLDS` holds the UK figures, checked against GOV.UK on 2 Nov 2026, with the sources listed. **Mileage is now 55p** (from 6 April 2026), not 45p.
- **Provider (`providers/xero.py`), read only:**
  - the P&L and balance sheet take `periods` and `timeframe`;
  - `get_invoice_list(where, statuses, modified_since, page)` is new.
- **Endpoint (`GET /v1/accounting/export/accountant-pack`):**
  - same route and query, with invalid dates rejected (400);
  - the token refresh is kept;
  - it returns the correct `.xlsx` media type;
  - if Xero fails, the pack is still produced from Business Hero's own data, and the Summary says what's missing.
- **The old main.py report writer is removed,** and with it the Aged calls that always failed.
- **The Accounting page's export dialog** describes the new pack and its default period.
- **Xero invoices for the aged tabs come from three filtered streams,** fetched concurrently:
  - open now and dated by the end;
  - paid now but changed since the end (so paid after it);
  - sales issued in the period.
  Each is paged.
- **Tests:** `test_accountancy_pack.py` has 59. Mutation testing covered 21 mutants across the accuracy rules, the tax rules, the AI guard, concurrency and rate-limit routing. All are caught, after three tests were tightened: bucket edges, a leap-year month end, and an AI answer that arrives too late.

## Codex review 1 (`audits/ACC-2-CODEX-REVIEW-1.md`, 6 × P1, 6 × P2) → fixed

**P1**
1. **AI could insert invented amounts or claims** ("Claim £999k immediately", "guaranteed refund").
   - The rule's text and figures are now **never** replaced.
   - The AI may add one line in a separate column, "In plain words (AI)", labelled as AI-written. The line is dropped if it has any digit, currency or percent sign, number word, or claim word (guarantee, refund, must, will save, avoid…), or more than 3 sentences.
   - Only the point titles go to the model, never the figures.
2. **Aged balances missed debts that were paid after the year end** but entered earlier. "Modified since" is gone. The aged set is now:
   - every invoice open now and dated by the end;
   - every invoice touched by a payment **dated** after the end (Xero `Payments where Date>end`);
   - every invoice touched by a credit-note, prepayment or overpayment allocation **dated** after the end.
   Those invoices are fetched by id. Credits are deducted by their allocation dates, and deleted payments and voided credits never reduce a debt.
3. **The VAT test (T1) used cash received.** It now uses sales invoiced before VAT, less sales credit notes, over the 12 months to the period end. The text says the legal test is taxable turnover over any rolling 12 months. Without Xero (VAT status unknown), T1 doesn't fire.
4. **Mileage used the current rate for every period.** The rate now comes from a dated table: 45p until 5 April 2026, 55p from 6 April 2026. A period spanning the change shows both.
5. **Currencies were added together.** Only the base currency (Xero `BaseCurrency`) is aged or totalled. Other currencies are listed under Loose Ends, never added in.
6. **Xero rounding:** a Rounding column means net + VAT + rounding = gross on every invoice row, and the Invoices tab has totals.

**P2**
7. **The fake Xero now honours what the pack sends:** statuses, `where` dates and types, and pages of 100.
   - Tests assert the comparative parameters, 150 invoices across two pages, the paid-after-the-end and credit-after-the-end scenarios, the £1,000 balance-sheet difference, ledger totals tied by amount, and UK time in summer and winter.
8. **The no-Xero P&L has last year beside this year.** The Summary only claims comparatives when there is a P&L.
9. **A resolved period that runs backwards** (only a start given, after the default end) raises `PeriodError`, which the endpoint returns as 400.
10. **Every database step of the export** (connection lookup, token refresh, the pack) runs on the worker thread with its own session.
11. **The wording call goes through `ai_router.json_chat`** (purpose `wording`, failover, priced models), with its cost saved as `accountancy_pack`, and is gated by the profit guard.
12. **Naive sync timestamps are read as UTC,** then shown in UK time.

**Backlog notes, also done:**
- A failed Xero connection's reason is carried into the Summary.
- T8 states the conditions: an annual event open to all staff, a combined per-head limit; and for trivial benefits, not cash, not a reward, not contractual.

**Tests:** 83. Mutation testing covered 21 mutants in round 1 and 26 in round 2, all caught.

## Codex review 2 (`audits/ACC-2-CODEX-REVIEW-2.md`, 2 × P1, 3 × P2)

**P1**
1. **The AI line could still overstate** ("All your spending is tax deductible", "You qualify for tax relief"). A word filter cannot guarantee it never will. **Mike decided on 2 Nov 2026 to keep the AI line,** having been offered pre-written lines or no line instead. So:
   - the column is headed "In plain words (AI-written, may be imprecise)";
   - the tab note says the Explanation and Figures are what count;
   - the filter now also blocks fractions and the words Codex found (deductible, allowable, qualify, eligible, relief, exempt, claim, dozen, all, every…).

   **Accepted residual risk:** an overstated line that avoids every blocked word can still appear. The rule's text and figures beside it are never affected.
2. **A non-GBP base currency was shown as pounds and tested against UK limits.**
   - The workbook's money format follows the base currency, and the Summary states it.
   - No tax points are raised unless the base is GBP; the tab says why.

**P2**
3. **The wording timeout didn't bound the wait,** because the synchronous router call held `asyncio.run` at shutdown. The call now runs on a daemon thread, so a timeout really ends the wait (its cost is still saved). Tested with a blocking call.
4. **A token that couldn't be renewed was still used.**
   - `accountancy_pack.connect()` returns no provider and a reason, and the pack falls back to Business Hero's data and says why.
   - An organisation that can't be read does the same.
   - Tested: fresh, renewed, renewal failed, no connection.
5. **Proof gaps, now covered:**
   - the fake Xero honours If-Modified-Since, and the paid-after-the-end fixture was last modified *before* the end, so the old approach fails it;
   - prepayment and overpayment allocations;
   - two batches of invoice ids;
   - an endpoint test shows the connection and pack run off the main thread, and a backwards period returns 400.

**Backlog note, also done:** credit notes are filtered with the documented `where` (`Status=="AUTHORISED" OR Status=="PAID"`), not `Statuses`. The fake now rejects `Statuses` for credit records.

**Tests:** 98. Mutation testing on the review-2 fixes: all 6 caught.

## Codex review 3 (`audits/ACC-2-CODEX-REVIEW-3.md`, 1 × P1, 1 × P2) → fixed

Cycle 3 of 3. Every review-2 item was confirmed fixed and proven.

1. **P1: the fallback path could show foreign invoices as pounds.** When Xero can't be used (sign-in not renewed, or the organisation unreadable):
   - the currency is "not confirmed";
   - amounts are shown as recorded, with no currency symbol;
   - no tax points are raised, and the tab says why;
   - stored invoices in another currency (the `invoices.currency` column) are left out and listed under Loose Ends.
2. **P2: there was no endpoint proof of the fallback.** A new test drives the real `connect` and `build` through the endpoint, faking only Xero's sign-in and the database. A token that can't be renewed produces a workbook built from Business Hero's data, with the reason on the Summary. The request's session is passed as `None`, so using it would fail.

**Mutation testing:** passing `xero_error=None` in the endpoint, dropping the fallback currency filter, and treating an unconfirmed currency as confirmed are all caught.

**Tests:** 100.

**Backlog (Codex):**
- a provider-level request assertion for credit-note filtering;
- batch-payment, refund and overlapping-stream fixtures;
- a cap on lingering wording threads if a provider stalls often.

**Known limits:**
- The tax-point categories match by keyword on category names (for example "Computer Equipment"). A business with unusual category names gets fewer points, never wrong figures.

## Codex review 4 (`audits/ACC-2-CODEX-REVIEW-4.md`, quick targeted) → APPROVE

No P1 or P2. Both review-3 fixes were confirmed and proven. A business with no Xero connection still gets pounds and tax points.
