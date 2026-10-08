# BH-009 — Stage 1 invoice PDF design for review

Status: proposed contract, tests written first; no implementation or migration.
Builder: Codex. Reviewer: Claude Code. Mike reviews the money behaviour before
Stage 2. Serves RC1 P0-4, North Star P8 correctness and P9 tenant isolation.

## North Star §8

This is a correctness prerequisite over existing invoices. Stage 1 stores or
fetches no new application data, introduces no Aria numbers and makes no model
calls. Stage 2 should render existing records; any later address/tax-point
snapshot migration needs its own approval and assessment of Aria read access.
Security work retains its place in the release sequence.

## Proposed reusable contract

New `backend/invoice_pdf_api.py` router, with
`GET /v1/invoices/{invoice_id}/pdf`, registered in `main.py` in Stage 2 only.
Use `get_user_business_context`, `get_session`, and the real
`require_feature("invoicing")` dependency. Return an attachment with
`application/pdf`; foreign and missing invoice IDs return the same 404 JSON
and no PDF bytes. Never allocate a number, update an invoice, send email,
fetch logos over the network, or call Xero to download a stored record.

New `backend/services/invoice_pdf.py` exposes the async function
`generate_invoice_pdf(invoice, line_items, business, settings) -> bytes`.
The renderer receives a normalized, already tenant-scoped document. Proposed
normalized fields include `invoice.customer_address`, `tax_point`, and
`discount_amount`: these are NOT claims that these columns exist in invoices.
Stage 1 renderer fixtures deliberately supply complete data to express what
the future document must display. Missing-source decisions below remain open.

P0-5 should store canonical invoice amounts and lines, then use this same
reader/renderer. Share the `invoicing` feature gate and tax treatment semantics;
creation is a mutation and must deny read-only businesses, while PDF download
must allow them. `auth.py:700` explicitly includes invoicing in read-only
permitted features; `auth.py:732` and `:756` implement the actual gate.
The HTTP tests exercise that real gate with active, unpaid, canceled,
feature-disabled, and administratively inactive businesses. Authentication
itself is overridden with a synthetic identity, not claimed verified.

## Repository evidence and data sources

| Data | Evidence and proposed source |
| --- | --- |
| Invoice ownership, number, customer name | `backend/models.py:225`; `audits/live-schema-public.txt:484` onward. Select invoice by BOTH id and authenticated business_id first. |
| Header totals | Schema snapshot `:511`–`:512` and `:484`: subtotal, tax_amount, amount. `backend/quoting_api.py:663` writes these; amount is gross, not outstanding balance. Use raw numeric reads/Decimal normalization; the ORM at `backend/models.py:247` annotates money as float and omits subtotal/tax_amount. |
| Line amounts, rates, discounts | Schema snapshot `:464`–`:483`; conversion `backend/quoting_api.py:694` copies line_total, discounts, taxable, tax_rate, tax_amount and tax_treatment. Lines have no business_id: read them only through the invoice whose ownership was established. |
| Supplier identity and address | `quote_settings.company_name/company_address`, schema snapshot `:593` onward; existing PDF loader `backend/quoting_api.py:754`. Fallback business name is read at `:764`. Address may be absent. |
| VAT registration | businesses.tax_registered/tax_number, schema snapshot `:212`–`:213`; old quote_settings.vat_number also exists. Proposed canonical number is businesses.tax_number; resolving conflicting or missing legacy values needs a decision. Never print either when unregistered. |
| Region/currency | `backend/services/region.py:35` defines currency codes; `:79` resolves profiles. It currently provides NO currency symbol helper. Stage 2 should add/reuse a region-owned symbol mapping, not scatter pound literals. Tests cover GBP and USD; invoice currency versus current business region precedence needs agreement. |
| Dates | invoice_date and issue_date are nullable, schema snapshot `:498` and `:501`; created_at is not an explicit tax point. Quote conversion at `backend/quoting_api.py:663` writes neither invoice date field. Do not silently call due_date the issue date. |
| Customer address via quote | `quotes.customer_address` at snapshot `:623`; conversion writes source='quote', source_ref=quote_number (`backend/quoting_api.py:669`, `:685`) and updates quotes.invoice_id (`:724`). Prefer a same-business quotes.invoice_id link; any source_ref fallback must also filter business_id, source type, and reject ambiguity. |
| related_invoice_id | `backend/migrations/031_money_engine.sql:396` documents this as the credit-note-to-invoice pointer. It is NOT a quote relationship. Migration text is design evidence, not evidence of live schema state. |
| Existing PDF | `backend/services/quote_pdf.py:12` provides the ReportLab structure; `backend/quoting_api.py:790` serves it. Do not copy its float conversions, hard-coded £, or VAT-number visibility rules. No quote-PDF edits in BH-009. |

The schema dump is repository evidence only. No live database was queried.

## Money and document behaviour proposed for Mike's review

Use stored header and line amounts as the authority for issued documents.
No independent invoice total calculation. `services/money.py:24` provides
ROUND_HALF_UP `q2`; `:29` is the normalization boundary and `:163` contains
the calculator. Rendering does not need to rerun the calculator, which takes
one invoice-wide rate and would lose mixed stored rates. Preserve each line's
stored rate and tax treatment; a zero is not a missing value. Line tax labels
do not determine taxability.

Present stored totals to the penny and show discounts. A normalized discount
can be assembled from stored line discounts and apportioned discounts, taking
care that percentage discount_amount is an input percentage, not money.
There is no invoice header discount column. For imported headers with no lines,
do not infer a discount or reconstruct lines from the totals.

Tests deliberately supply header totals inconsistent with the line calculation:
the PDF must retain the stored subtotal/tax_amount/amount rather than silently
reprice the invoice. Whether to show a discrepancy warning is open below.
Decimal fixtures include a value that forbids float conversion and a 2.6750
unit price that must display as 2.68, not 2.67.

Registered documents display supplier/customer identities and addresses,
registration and invoice numbers, issue date, differing tax point, item
quantity/description/unit net price/rate/amount, net total, discount, total VAT,
and total payable. Nonregistered documents omit all generated VAT terminology,
rates and registration numbers, even if stale settings still contain them.
Stored zero rates remain zero. Imported CSV/Xero invoices without lines render
header totals and explicitly say "No itemised lines". This means a structurally
valid PDF, NOT a claim that it qualifies as a full VAT invoice.

## Open questions — decisions before implementation claims completeness

1. **Customer-address gap:** invoices have no address snapshot. Quote-backed
   invoices can reach a same-tenant quote address, but that value can change
   or disappear. Manual/CSV/Xero rows need not have a quote at all. A complete,
   historically reliable full VAT invoice for every invoice cannot be promised
   from this schema. Decide whether to authorize a separate RED snapshot
   migration with P0-5, and how to treat existing rows. Do not guess an address
   by customer name or use another tenant's quote.
2. **Issue date and tax point:** no dedicated tax-point column was found;
   conversion omits issue_date/invoice_date. What is the approved source and
   precedence, and how are historical nulls handled? A created_at fallback
   would be an explicit product/accounting decision, not established evidence.
3. **Supplier details and history:** which record wins if business tax_number
   differs from quote_settings.vat_number? What happens when supplier address
   or number is absent, or registration status changes after issue? The ticket
   currently gates presentation on the business's current tax_registered flag;
   this does not preserve historical registration facts.
4. **Incomplete imports:** the ticket requires downloads without lines, but
   full VAT invoice fields may be unavailable. Agree explicit incomplete-record
   wording and whether the VAT title must be withheld. Do not describe such
   PDFs as lawful full VAT invoices without confirming the applicable rules.
5. **Currency:** should a historical invoice's explicit currency override a
   later business region change? Recommended: yes. Agree supported currencies
   and how unknown codes display. Stage 1 tests cover matching GBP/UK and
   USD/US only. UK VAT accounting in a foreign currency remains unverified.
6. **Inconsistent data:** stored headers win in these tests. Decide whether
   missing totals or discrepancies should visibly flag incomplete data, or
   refuse generation. Nonregistered records with nonzero stored tax create a
   conflict between preserving totals and suppressing tax; the tests exercise
   stale rates/numbers with zero header tax, not that unresolved conflict.
7. **Discounts:** confirm display of line versus invoice discounts and their
   relationship to the stored gross-before-discount subtotal. Header-only
   imports cannot recover an unstored discount. Do not invent one.
8. **HMRC verification is outstanding:** no network was used. Every legal field
   requirement in the ticket's summary of VAT Notice 700 §16 is unverified in
   this run: title, supplier/customer identity/address, registration number,
   numbering, issue date/tax point, line details/rates, net/VAT/gross totals and
   discount presentation. Also unverified: simplified/modified invoices,
   no-line imported records, rate-group totals, zero/exempt/reverse-charge
   wording, foreign-currency VAT, and the precise retention duty. Mike should
   check the notice before approving a compliance claim. These tests express
   the supplied acceptance criteria, not independent legal advice or proof.

## Verification boundaries and review steps

`backend/tests/test_invoice_pdf.py` uses only an explicitly created in-memory
SQLite database with two fixed tenant UUIDs and distinct private data. Matching
quote numbers across tenants expose unscoped address lookups. The runtime guard
rejects non-SQLite environment URLs before app import, and each test blocks
network connections and disk/default database connections. SQLite does not
prove PostgreSQL types, numeric behaviour, constraints, grants or RLS.

The HTTP app mounts the proposed router independently: it does not prove the
future one-line registration in main.py, JWT verification or middleware.
The real entitlement resolver runs; only its ORM Business lookup and the
platform-admin check are substituted. Invoice/line/quote SQL is real SQLite.

Without a PDF text-extraction package installed, tests observe ReportLab's
actual text-formatting calls while producing real PDF bytes. An unmarked
harness test verifies text/currency capture; another verifies both seeded
tenants. This does not prove readable visual layout, pagination, clipping,
font embedding, or successful text extraction by an external PDF reader.
No dependency was installed. Stage 2 should add visual inspection of long and
multi-page invoices and missing-data cases. Mike's later click test is Invoices
→ select invoice → Download PDF, then open it and compare to the stored record;
there is no new button or application behaviour to click in Stage 1.

Each new-behaviour test carries the exact strict xfail reason requested in the
ticket, restricted to MissingInvoicePDF for an absent target module. Other
failures remain failures. Once implementation exists, remove the markers:
strict XPASS is intentional. The missing module means the tests are a reviewable
future contract; deeper assertions have not yet been exercised against an
implementation. No implementation completeness is claimed by an xfail count.

## Reviewer addendum — HMRC checked online (Claude Code, 6 Oct 2026)

Codex had no network. I fetched HMRC VAT Notice 700 §16 and GOV.UK's
"Invoices: what they must include" on 6 Oct 2026. **Caveat:** my fetch tool
returns a model-summarised extraction, not raw page text, so treat the list
below as strong evidence to confirm, not verbatim law. Mike (or an
accountant) should confirm against https://www.gov.uk/guidance/vat-guide-notice-700
before any compliance claim is made in copy.

**Full VAT invoice (§16.3), as returned:** unique sequential invoice
number; invoice date; date of supply (tax point) if different; supplier
name, address and VAT registration number; customer name and address;
description sufficient to identify the goods/services; quantity or extent;
unit price and total excluding VAT; VAT rate per description; amount of VAT
chargeable. The extraction also listed "the customer's VAT number if VAT
registered", which I could not corroborate and believe applies only to
specific cases (e.g. reverse charge). **Unconfirmed; do not build it in
RC1 without confirmation.**

**Less detailed VAT invoice (§16.6.1), as returned:** for a supply of
£250 or less including VAT: supplier name and address, date of supply,
description, total payable including VAT, VAT rate. **No customer name or
address required.** This matters to open question 1.

**Unregistered:** "You must not issue a VAT invoice unless you are
registered for VAT." Confirms the unregistered tests.

**Foreign currency (§7.6):** VAT on an invoice in another currency must
also be shown in sterling at an approved rate. Stage 1 tests use USD only
for an unregistered business, which is right. A VAT-registered business
invoicing in a non-GBP currency is NOT handled: in RC1 (UK only) the PDF
should refuse it with a clear message rather than issue an incomplete VAT
invoice.

**Every invoice, VAT or not (GOV.UK):** unique number; supplier name,
address and contact details; customer name and address; description;
supply date; invoice date; amounts; VAT if applicable; total owed. So the
customer-address gap (open question 1) affects non-VAT invoices too, and
the supply-date gap (open question 2) is a general requirement as well.

## Decisions — Mike, 8 October 2026

Mike reviewed the Stage 1 tests and approved them, and agreed every
recommendation put to him (Claude Code's summary of the eight open
questions). These now bind Stage 2:

| # | Question | Decision |
|---|---|---|
| 1 | Customer address | A RED migration adds `invoices.customer_address` and `invoices.supply_date`, delivered **with P0-5** (manual invoices), not in BH-009. Until then Stage 2 reads the address from the same-business quote linked by `quotes.invoice_id` only; it never guesses |
| 2 | Invoice date | Quote conversion records the invoice date from now on (P0-5 owns that write). For existing rows: `issue_date`, else `invoice_date`, else the date of `created_at`, labelled "Invoice date". A tax point is shown only when stored and different |
| 3 | VAT number | `businesses.tax_number` wins; `quote_settings.vat_number` only when it is empty. (Flagging a mismatch in Settings is follow-up UI, not BH-009) |
| 4 | Imported CSV/Xero invoices | Titled **"Invoice copy"**, never "VAT invoice", with "Originally issued from Xero" (or "Imported from CSV") and "No itemised lines" when there are none |
| 5 | Currency | The invoice's own currency wins over the business region. A VAT-registered business with a non-GBP invoice is **refused** in RC1 (HMRC requires VAT shown in sterling too) |
| 6 | Unregistered business, VAT stored on the invoice | **Refused** with a clear message telling the owner to check their VAT settings. Never rendered either way |
| 7 | Discounts | Shown as their own line in the totals |
| 8 | HMRC | Mike has the reviewer addendum above; confirmation against Notice 700 §16 rests with him |

### Behaviour while the address column does not exist (Stage 2 interim)

A VAT-registered invoice over £250 with no customer address cannot be a
complete full VAT invoice (§16.3); at £250 or under, the less detailed
form needs none (§16.6.1). Stage 2 renders what exists and **never
invents an address**, and the API reports what is missing in a response
header, `X-Invoice-Missing-Fields` (e.g. `customer_address`), so the app
can warn the owner before they send it. The PDF itself carries no warning
text. This is an interim rule until P0-5's migration, and it is Claude
Code's call within Mike's decisions, flagged to him.
