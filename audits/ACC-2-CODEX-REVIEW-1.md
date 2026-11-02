# ACC-2 Codex review 1

Model gpt-6-astra · session 01a19d17-01b8-7a33-ae22-97e6844812f5 · 93,452 tokens · verdict **CHANGES REQUIRED**

## Prompt

```
You are the independent reviewer (read-only) for ticket ACC-2 in this worktree, branch ticket/ACC-2-accountancy-pack, uncommitted diff vs origin/main (`git diff`, plus untracked backend/services/accountancy_pack.py, backend/tests/test_accountancy_pack.py, docs/ACC-2-TICKET.md). Tier RED: an accountancy pack (Excel) handed to a business's accountant, with tax points.

Read docs/ACC-2-TICKET.md (rules A1–A9, T1–T8, W, speed; Mike approved them) and review the implementation against it. Focus on correctness of money and dates:
- default/prior periods (Xero FinancialYearEndDay/Month, leap years, "last completed" year);
- Xero report parsing (no label/header ever becomes money; comparative columns);
- aged debtors/creditors AS AT the period end (payments/credits dated after the end; voided; the three invoice streams and their Xero `where`/Statuses/If-Modified-Since semantics — is any invoice outstanding at the end missed or double counted?);
- invoices in period (net+VAT=gross), ledger P&L and cash summary (Decimal exactness, archived rows, transfers), loose ends (sync date compared in UK time);
- tax rules vs the UK figures in THRESHOLDS (checked on GOV.UK 2 Nov 2026), rule conditions, and that every point is framed for discussion with an accountant, never advice;
- AI wording guard: can any invented number or new claim survive `word_points`? Is cost metered (profit_guard.attributed, permits) and is the pack never blocked by AI?
- endpoint in backend/main.py: worker thread + own session + asyncio.run, token refresh, errors, tenant scoping of every query (business_id), no blocking on the event loop;
- tests: do they prove the rules (look for assertions that would pass on wrong code)?

Output: verdict APPROVE or CHANGES REQUIRED; P1 (wrong figures / data leak / crash) and P2 findings, each with file:line and a concrete failure scenario; then backlog notes. Do not edit files, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED**

Reviewed the diff against `origin/main` and the three untracked ticket files. The blockers concern grounded figures and trustworthy output: North Star P2/P8.

**P1 — wrong figures or unsupported financial claims**

1. **The AI guard accepts invented amounts and advice.** [accountancy_pack.py:470](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:470)  
   Confirmed by executable probes: “Claim £999k immediately”, “Claim nine thousand pounds in tax relief”, and “You are guaranteed a £125.50 tax refund” all survive for T7 with £125.50 uncategorised spending. The guard checks recognised numeric tokens, not their meaning, units, claims, accountant framing or sentence count. W is not enforced. Use constrained wording that cannot change the approved claims; retain deterministic text when that cannot be guaranteed.

2. **The paid-invoice filter silently misses debt outstanding at year end.** [accountancy_pack.py:643](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:643)  
   Example: a £1,200 invoice has an April payment entered on 30 March, with no subsequent modification. At 31 March it remains outstanding economically, but today it is `PAID`; neither `AUTHORISED` nor `PAID` modified since 31 March retrieves it. Even if the sales stream retrieves it, line 688 excludes that stream from ageing. Older sales and purchase bills remain missed regardless. The ticket acknowledges this limitation, but A3 contains no exception. Xero’s modification filter selects modification timestamps, not payment dates. [Xero invoice API](https://developer.xero.com/documentation/api/accounting/invoices)

3. **T1 substitutes cash receipts for taxable turnover.** [accountancy_pack.py:608](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:608)  
   £100,000 of taxable invoices with £60,000 collected produces no warning. Conversely, £60,000 sales receipts plus a £40,000 loan recorded as income produces a compulsory-registration discussion based on £100,000. There is no taxable-supply classification or exclusion of financing/exempt receipts. The £90,000 threshold is correct; the business figure compared against it is not. [GOV.UK turnover definition](https://www.gov.uk/register-for-vat)

4. **Historical packs receive the wrong mileage rate.** [accountancy_pack.py:385](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:385)  
   The default March-2026 year-end pack quotes 55p for that period’s vehicle expenditure, without an effective-date qualification. The checked publication confirms 55p starts **6 April 2026**, replacing 45p. Select rates by the relevant dates or explicitly distinguish a prospective discussion from the period’s treatment. [GOV.UK mileage change](https://www.gov.uk/government/publications/increase-to-approved-mileage-allowance-payments-amaps-and-self-employed-simplified-mileage-rates/increasing-mileage-rates)

5. **Foreign-currency invoices become pound-denominated totals.** [accountancy_pack.py:258](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:258), [accountancy_pack.py:542](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:542)  
   A USD 1,000 invoice and GBP 1,000 invoice are added and displayed as £2,000. `CurrencyCode` is neither checked nor displayed. Excluding multicurrency revaluation from scope does not justify combining currencies: reject/omit unsupported balances with an explicit reason, or segregate them. Xero returns invoice amounts in the invoice currency. [Xero invoice API](https://developer.xero.com/documentation/api/accounting/invoices)

6. **A4 does not handle valid invoice rounding adjustments.** [accountancy_pack.py:267](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:267)  
   A valid invoice with subtotal £100, VAT £20, rounding £0.01 and total £120.01 is exported without its adjustment; net + VAT does not equal gross. Xero explicitly supports this case. Represent the reconciliation transparently rather than silently altering Xero’s figures. [Xero rounding rules](https://developer.xero.com/documentation/api/accounting/invoices)

**P2 — requirements and verification gaps**

7. **The tests cannot prove stream completeness or comparative requests.** [test_accountancy_pack.py:112](/Users/michaelrickards/dev/bh2-ACC-2/backend/tests/test_accountancy_pack.py:112)  
   `FakeXero` ignores `where`, `statuses` and `modified_since`; report fakes also ignore requested dates/comparatives. Removing a filter or comparative parameter can leave tests green. Add filter-aware fixtures, multiple pages, genuinely omitted paid invoices, and realistic prepayment/overpayment allocation payloads. Other weak assertions:
   - A6 checks that a warning exists, not its £1,000 difference.
   - A7 counts transaction rows rather than reconciling their amounts.
   - The UK-time test runs in November and checks only the date.
   - W explicitly accepts replacement text without accountant framing.

8. **The no-Xero pack promises comparatives but supplies none.** [accountancy_pack.py:672](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:672)  
   Only current-period ledger data is rendered, while Summary states a comparative period. A business with last-year transactions receives no prior figures. Build the prior ledger column or explicitly report its absence.

9. **Partial date overrides can create reversed periods.** [main.py:5101](/Users/michaelrickards/dev/bh2-ACC-2/backend/main.py:5101), [accountancy_pack.py:602](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:602)  
   With March year end, supplying only `period_start=2026-04-01` defaults the end to `2026-03-31`. Validation runs before defaults, so the pack proceeds with an invalid interval. Validate the resolved pair.

10. **Database work still blocks the request event loop.** [main.py:5105](/Users/michaelrickards/dev/bh2-ACC-2/backend/main.py:5105)  
    Connection lookup, refresh persistence and `session.commit()` precede `to_thread`. A slow database query or lock blocks other requests. Workbook construction correctly uses a worker-owned session and `asyncio.run`; move the remaining export-specific synchronous database work into that worker.

11. **The new model call bypasses the existing router.** [accountancy_pack.py:485](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:485)  
    `AsyncOpenAI` is instantiated directly despite the existing `services.ai_router` and North Star rule 5. Attribution and the installed profit-guard hook do provide a metering path; this is not an unmetered-call finding. Route the call through the approved layer while retaining the fallback and overall timeout.

12. **Naive sync timestamps are reinterpreted as London time.** [accountancy_pack.py:739](/Users/michaelrickards/dev/bh2-ACC-2/backend/services/accountancy_pack.py:739)  
    `_parse_moment` correctly treats naive timestamps as UTC, then this branch overrides that interpretation. A naive `2026-06-30 23:30` represents 1 July in London, but becomes 30 June, generating an incorrect sync warning. Preserve UTC interpretation before conversion.

**Backlog notes**

- Preserve the connection-failure reason when falling back; currently a failed connection can be described as no connection.
- Qualify T8 with the annual-event aggregation/all-staff conditions and trivial-benefit exclusions. The monetary thresholds checked are consistent with GOV.UK, but eligibility needs more than price alone. [Events](https://www.gov.uk/expenses-benefits-social-functions-parties/whats-exempt), [trivial benefits](https://www.gov.uk/expenses-and-benefits-trivial-benefits)
- Add endpoint, metering and cancellation tests. Synchronous profit-guard database work means `wait_for(15)` alone does not prove a hard 15-second wording budget.
- I found no cross-tenant query in the new pack reads. Archive filtering, Decimal aggregation, first-column/header preservation and invoice-ID deduplication are present. ACC-1 excludes Xero transfers upstream.

**Verification:** 45 selected tests passed. The 14 workbook tests could not be completed: even with in-memory SQLite, openpyxl requires temporary-file writes prohibited by this read-only environment. `check.sh` was not run; no full-green claim. No files were edited, committed or pushed.