# QUOTE-1: an estimator that wins work (RED: prices customers act on)

**Asked for by Mike, 22 Nov 2026.** The problem was first recorded on 2 Nov (memory: trade-quotation-estimator).

## Why

Mike has lost two jobs on price after quoting with the most capable models, prompted by hand. One roof quote came out about 80% above a like-for-like quote. The EPDM option came out at **over £260/m²** where, from Mike's memory, **about £130–180/m²** was right.

The models weren't short of intelligence. Nothing checked their answer against what the job typically costs, against trade (rather than retail) material prices, or against the business's own rates. They over-specified, and nobody was there to stop it.

**The rule this ticket enforces:** the AI drafts the quote, and Business Hero's engine checks it. The engine is plain code with the business's own data, never the model marking its own work. **The user decides, line by line.**

## What exists today (checked in code, 22 Nov, origin/main 31fcfd5)

- **The AI call:** `quoting_api.generate_ai_quote` (`POST /v1/quotes/ai/generate`) makes one call that turns a job description and up to 5 photos into grouped line items (category, quantity, unit, unit cost).
  - It calls OpenAI directly over httpx. Its task is `quote`: gpt-5.4, or `QUOTE_AI_MODEL`, and OpenAI only on the admin page.
  - Quote drafting inside Aria's chat (`quote_chat`, gpt-4o) is the same.
- **The prompt pushes prices up:**
  - "Be thorough … include all necessary items a professional would include" invites over-specifying.
  - "Realistic UK material prices from major suppliers" means retail prices.
  - Day-rate ranges are hard-coded (labourer £120–180, skilled £200–350, …).
- **`quote_settings`:**
  - `labour_rates`: a list of role and **daily** rate. There's no hourly rate, and it's used only as prompt text.
  - `default_markup`, `industry` and `default_tax_rate`.
- **Line items:** `markup_percentage` is per line, and the quote editor (`QuotesPage.tsx`) can edit lines.
- **What's missing:**
  - checks against typical rates (£/m² or equivalent);
  - a trade-price basis or a materials markup;
  - supplier prices;
  - warnings;
  - learning from won and lost quotes;
  - any record of other quotes the customer has had.

## What it does

### 1. The most capable models, chosen on the admin page
- `quote` and `quote_chat` move onto `services/ai_text`, like AI-1d. That gives any provider, with fallbacks and costing.
- Mike's suggested defaults: **Claude Opus 5.5 first, GPT-6.1 as fallback**, confirmed at build time against the price table.
- "Test this model" gets an estimating set, built from jobs with known fair prices. Mike's EPDM roof is the first case.

### 2. The business's own rates, used as numbers, not prompt text
- **Labour rates per role, daily and/or hourly.** For example: labourer £x/day or £y/hour; skilled roofer, electrician and so on.
  - Set in Quote settings.
  - The AI picks *which* role and *how long*.
  - **The engine fills in the rate.** The model never prices labour.
- **A materials markup %**, the business's own figure added on top of trade cost, shown as its own figure on the quote. It can be overridden per quote and per line.

### 3. Materials at trade prices, not retail
For each material line, the engine uses the first of these that exists:
1. **The user's own price:** typed on the line, or from their supplier price list. Upload a CSV or the supplier's export; it's remembered per item.
2. **What they paid or quoted before** (learned, see 5).
3. **The AI's researched price**, converted to an estimated trade price.
   - It uses the provider's web search, with the source and date cited.
   - Retail-to-trade is a factor the business sets, with a starting suggestion that is checked at build time and labelled as an assumption.
   - These lines are marked **"estimated: check"**.

The line shows where its price came from, and the user can change any row.

### 4. The engine's checks, before the user sees a total
- **Typical-rate benchmarks:** the job's total, and its main parts, are compared against a typical range per unit. Examples: £/m² for flat roofing by membrane; £/m² for plastering; £ per point for electrics.
  - **Where the ranges come from:**
    - the business's own past won jobs (best);
    - ranges Mike or the business sets;
    - published typical-cost figures, gathered and cited at build time, with their date shown. These are never the model's guess.
  - **Above the range → a warning** on the quote: "EPDM roof at £262/m²: typical £130–180/m² (your past jobs: £150/m²). Check spec and quantities." Below the range also warns, as a possible missed item.
  - No benchmark for a job type: the quote says so, rather than implying it was checked.
- **Spec creep:** a line the job description didn't ask for (an upgrade, an extra, "while we're there" work) is flagged, along with a premium material where a standard one would do. Economical by default.
- **Arithmetic and units:** quantity × unit price is checked; quantities are checked against the measured area or length; units must be consistent (no m² against linear metres); there must be no duplicate lines; and VAT and markup must not be added twice.
- **Other quotes:** at the start the estimator asks: "Has the customer had other quotes? Their total or per-m²?" If given, that becomes a benchmark too.

### 5. Learning from the business's own quotes
- A won quote's per-unit figures feed that business's benchmarks.
- Line edits teach the estimator; for example, if the owner always trims labour on roofing, it starts closer next time.
- A lost-on-price reason, asked when a quote is marked lost, lowers confidence in the ranges that produced it.

### 6. Line by line, the user decides
- Every line can be edited, re-researched, or sent to the AI to double-check, for that line only.
- The quote can't be sent while a warning is unacknowledged. One click acknowledges it, with an optional note.
- Every figure shows its source: your rate, your supplier, your past job, researched with a citation, or an estimate.

## Out of scope for QUOTE-1
These are already recorded separately:
- sending a quote, acceptance, staged invoices per project and chasing (memory: trade-quotation-estimator);
- the trade site portal.

## Cost
- Every AI call is costed under `quote` (the profit rule). Web research costs more per line, so it runs on material lines without a user, supplier or past price, and it's capped per quote.
- Using the most capable models for estimating is worth its cost here: one won job pays for years of it.
- The price per quote goes into the price catalogue at build time.

## Decisions for Mike (when we start)
1. Where the starting benchmark ranges come from: research them now (cited, dated) or have Mike supply the trades he quotes most.
2. The starting retail-to-trade factor, and whether to allow one per supplier.
3. Whether a warning blocks sending until acknowledged (proposed: yes), or only advises.
4. The research cap per quote.

## Definition of done (beyond docs/DEFINITION_OF_DONE.md)
- **The roof case:** an EPDM flat roof at Mike's area returns lines whose £/m² is inside the benchmark, or else shows a warning naming the range. The over-£260/m² outcome can't reach the customer unflagged.
- No labour line is priced by the model; every one uses the business's rate.
- Every material price shows its source.
- Tests run on the engine's checks with fixed data, so they don't depend on a model; there's an eval set for the models. Codex reviews it, as RED.
