## TICKET BH-010 — manual invoice creation, with the address and supply date (RC1 P0-5)

**Outcome**  An owner creates an invoice in Business Hero without a quote,
and every invoice records the customer's address and the date of supply,
so a lawful invoice (and with BH-009, its PDF) can always be produced.

**Current evidence**  No `POST /v1/invoices` exists; Finance → Invoices
offers CSV upload only (`docs/CURRENT_STATE.md` §6; `audits/TIER1-CORE-FIXES.md`
§3b, confirmed end to end). `invoices` has no customer address or supply
date column (`audits/live-schema-public.txt`); GOV.UK requires both on every
invoice and HMRC VAT Notice 700 §16.3 on every full VAT invoice (BH-009
design note, reviewer addendum). Quote conversion writes neither
`invoice_date` nor `issue_date` (`backend/quoting_api.py:663`).

**Serves**  RC1 P0-5 (the core money journey). Decisions: BH-009 design
note, decisions 1 and 2 (Mike, 8 Oct 2026).

**Scope — Stage 1 (this commit): tests, migration draft. No implementation.**
- `backend/tests/test_manual_invoice.py` — the contract, strict xfail.
- `backend/migrations/034_invoice_customer_address.sql` — two nullable
  columns, VERIFY and ROLLBACK. **Draft: not rehearsed, not applied.**

**Stage 2, after Mike approves the tests**
1. `backend/invoices_api.py`, `POST /v1/invoices`, registered in `main.py`
   (one line). Totals by `services.money.calculate_totals`; rate by
   `quoting_api._quote_tax_context`; number by
   `services.invoice_numbering.allocate`; money via `to_decimal` only.
   Portable SQL (`CURRENT_TIMESTAMP`, not `now()`).
2. Quote conversion: snapshot `quotes.customer_address` into
   `invoices.customer_address`; record `invoice_date` (decision 2).
3. BH-009's PDF reads `invoices.customer_address` / `supply_date` first,
   falling back to the quote (after BH-009 merges — it owns those files).
4. Finance → Invoices: a **New invoice** button and form (customer, address,
   dates, lines), errors shown inside the dialog (`TIER1-CORE-FIXES.md` §3b
   notes the page-level alert sits behind the modal).
5. **The migration, RED:** staging rehearsal with a before-snapshot and a
   proven rollback, then `audits/034-PROD-RUNBOOK.md` with EXPECT/STOP IF at
   every step, which Mike runs. Then regenerate
   `audits/live-schema-public.txt` (033 STEP 24b method, parsed as CSV).

**Ordering constraint**  Code that writes the new columns cannot merge until
034 is live in production and the schema dump is regenerated —
`test_schema_conformance.py` refuses it otherwise. Stage 2 therefore ships
the migration first (Mike runs it), then the code.

**Non-goals**  Editing an issued invoice; credit notes (seam:
`related_invoice_id`); idempotency keys (RC1 P2 — the form disables its
button while submitting); client-chosen invoice numbers (refused: HMRC needs
a unique sequence); per-line VAT rates different from the business rate
(needs 032, P2); emailing the invoice.

**Security & data risk**  RED — money, a migration, and a new write path.
Tenant: `business_id` only from the authenticated context; a two-business
test proves the body cannot redirect it. Access: read-only and suspended
businesses refused (DECISION 3), `invoicing` feature required.

**Required tests**  `backend/tests/test_manual_invoice.py` (28 pending + 1
guard), `test_schema_conformance.py` green after the dump regenerates.

**Verification**  `./check.sh full`; the staging rehearsal record; Mike's
production run of the runbook.

**Builder** Claude Code  **Reviewer** Codex  **Branch** `ticket/BH-010-manual-invoices`
**Budget band** L  **Max repair cycles** 3
**Status** in progress — Stage 1 awaiting Mike's review of the tests
