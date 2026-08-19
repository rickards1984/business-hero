# Money Engine — Batch 1 Spec (v2)

Supersedes v1. All three decisions resolved. Region and locale seams added.

**Markets: UK and USA.** Europe deferred until a customer asks and pays —
it is fragmented per country, more regulated than the UK, and moving to
mandatory e-invoicing.

**Tax is calculated, never looked up.** Business Hero does not determine
taxability. In the UK a business sets its VAT rate; in the US the contractor
enters the rate they know applies. US construction sales tax depends on
jurisdiction, labour type, contract structure, residential vs commercial, and
repair vs capital improvement — automating that is a product in itself
(Avalara, TaxJar) and is explicitly out of scope, permanently, until it is a
funded decision. **No marketing copy may claim tax compliance or automation.**

All RED tier. Tests written and reviewed BEFORE implementation.
Use **Opus** in Claude Code for the tests and migration `031`; drop to
**Sonnet** for implementation once the tests exist.

---

## RESOLVED DECISIONS

**D1 — duplicates:** none exist in prod, constraint applies cleanly. Existing
invoice numbers are never rewritten. Provider-synced numbers are preserved
exactly as issued; the app never renumbers them.

**D2 — rounding:** per-line tax, `ROUND_HALF_UP` to 2dp, then summed.
Money totals 2dp everywhere. **Unit prices 4dp** (see Item 2 — schema change).

**D3 — zero rate:** if a business is not tax-registered, omit tax lines
entirely from PDFs and totals. Never print "VAT 0.00" — it implies
registration. Seller tax number prints only when set.

**D4 — the float boundary:** money arriving over the JSON API is converted
with `Decimal(str(x))`, **never** `Decimal(x)`. `Decimal(0.1)` is
0.1000000000000000055511151231257827, and `Decimal(2.675)` quantises to 2.67
rather than 2.68 — the binary approximation is already wrong before any
arithmetic happens. One conversion helper at the boundary; the calculator
itself accepts Decimal only and rejects floats rather than coercing them,
so a float that reaches it is a bug that gets found instead of hidden.

**D5 — discount order:** exactly one order, applied everywhere:

    line_total  ->  line discount  ->  quote discount apportioned pro-rata
                    by line net    ->  per-line tax on the discounted net

Both the line-level and quote-level discount may be `fixed` or `percentage`,
in any combination. A percentage quote discount is taken on the net **after**
line discounts, not on the gross subtotal. Apportionment shares are rounded
HALF_UP to 2dp and the remainder — of either sign — is applied to the largest
line by net, ties broken by lowest `sort_order`. The invariant that makes this
safe: **the sum of the line taxables equals the quote taxable exactly**, on
every quote, including discounts that do not divide evenly.

---

## ITEM 1 — Invoice numbering

### What
Unique sequential app-generated numbers per business, that can never collide
with numbers imported from Xero, QuickBooks, Sage or FreeAgent.

### Why it matters
HMRC and IRS both require unique sequential numbering. Today it is
`COUNT(*) + 1` over a table that also holds synced invoices, with no live
constraint. Xero's default format (`INV-0001`) is character-identical to the
app's generator. New Body already holds a Xero `INV-0001`; the next
app-generated number for that business would be `INV-0005`, and Xero's series
will reach `INV-0005` on its own in time.

### Acceptance criteria
- [ ] Atomic counter per business — `UPDATE … SET next_invoice_number =
      next_invoice_number + 1 … RETURNING …` in the same transaction as the
      insert. Never `COUNT(*)`
- [ ] Counter seeds from **app-generated rows only** (`source = 'quote'`):
      MSC → 2, every other business → 1. Legacy `INV-100x` CSV rows and the
      Xero row are ignored
- [ ] **Partial** unique index: `UNIQUE (business_id, invoice_number)
      WHERE external_source IS NULL`. A synced invoice can never violate it,
      so a provider sync can never abort on a numbering conflict
- [ ] Per-business `invoice_prefix`, default `INV-`, configurable
- [ ] On connecting an accounting provider, detect the provider's numbering
      format; if it matches the business's prefix, warn the user and offer to
      change the prefix. **Warn, never auto-change** — an invoice series is the
      customer's own record
- [ ] Synced invoice numbers are stored verbatim and never regenerated
- [ ] Two invoices created simultaneously get different numbers — proven by a
      concurrency test
- [ ] Deleting or archiving an invoice does not cause reuse
- [ ] Insert retries with the next number on a collision rather than 500ing
- [ ] Businesses with no settings row get one created on demand
- [ ] Zero-padding handles >9999 without breaking format

### How I will test it
Create three, delete the middle one, create a fourth.
Expect INV-0001, INV-0002, INV-0004 — never a second INV-0003.

---

## ITEM 2 — Invoice line items, tax split, and 4dp unit prices

### What
Invoices carry their own line items and tax breakdown, copied from the quote
at conversion. Unit prices gain 2 more decimal places.

### Why it matters
`invoice_line_items` does not exist — an invoice is one flat `amount`, and
`convert_to_invoice` discards the lines and the tax split. A UK VAT invoice
must legally show the VAT charged; yours structurally cannot.

**The 4dp change is time-critical.** `unit_cost` is `numeric(12,2)`, so
47.5 m² at £3.3333/m² rounds to £3.33 and the line is 15p out before you
start. Trades price per metre, per m², per tonne. Xero supports 4dp unit
prices. Changing this with 5 invoices in the table is trivial; changing it
with 5,000 is not.

### Acceptance criteria
- [ ] New table `invoice_line_items` mirroring `quote_line_items`, plus
      `tax_rate` and `tax_amount` per line
- [ ] `quote_line_items.unit_cost` and `invoice_line_items.unit_cost` are
      `numeric(12,4)`. Money totals stay `numeric(12,2)`
- [ ] Existing `unit_cost` values are preserved exactly by the widening
- [ ] Invoices gain `subtotal` and `tax_amount`
- [ ] **`invoices.amount` keeps its current meaning — the gross total.**
      Xero sync, briefings and accounting all read it; nothing that reads it
      today changes behaviour
- [ ] `convert_to_invoice` copies every line, the subtotal, tax and total
- [ ] Stored `subtotal` equals the sum of stored `line_total` values exactly —
      no second, differently-derived subtotal anywhere
- [ ] `subtotal + tax_amount = amount` exactly, on every invoice
- [ ] Tax rate stored **per line**, even though every line shares a rate today
- [ ] `quote_line_items` and `invoice_line_items` carry `discount_amount` and
      `discount_type`, plus the derived `apportioned_discount` and `taxable`
- [ ] The D5 order is implemented once, in the calculator, and used by quotes,
      invoices and PDFs alike
- [ ] Sum of line taxables equals the quote taxable **exactly**, including
      uneven apportionment (e.g. £10 across three equal lines)
- [ ] Sum of apportioned discounts equals the quote discount exactly
- [ ] Each line carries a `tax_treatment` text label (UK: `standard`,
      `reduced`, `zero`, `exempt`, `reverse_charge`; US: `taxable`, `exempt`).
      Stored and displayed only — **it drives no calculation**
- [ ] RLS enabled on the new table with the standard `is_business_member`
      policy. `create_all()` creates tables with RLS OFF
- [ ] **Existing invoices with no line items still render everywhere they
      render today** — no blank screens on historical data
- [ ] All new arithmetic uses `Decimal`, never `float`

### How I will test it
Convert a 3-line quote at 20%. The PDF shows each line, net total, tax amount
and gross — and the gross equals the quote total to the penny.

---

## ITEM 3 — Tax registration and the business's own rate

### What
Honour `default_tax_rate`, and let a business declare whether it is
tax-registered at all.

### Why it matters
The setting is stored, editable, and never read — backend and frontend both
hardcode 20. A non-VAT-registered business setting its rate to 0 still gets
20% on every quote. Charging VAT when not registered is illegal, and the
product would be walking customers into it.

### Acceptance criteria
- [ ] Business-level `tax_registered` boolean and `tax_number`
- [ ] When `tax_registered` is false: no tax on quotes or invoices, no tax
      lines on PDFs, no tax column in the UI
- [ ] New quotes seed `tax_rate` from `quote_settings.default_tax_rate`
- [ ] Hardcoded `20` removed from all four sites in `quoting_api.py`
- [ ] **A stored rate of 0 stays 0.** `rate or 20` turns 0 into 20 in both
      Python and JavaScript — use explicit `is None` / `=== undefined`.
      This is the single most likely way to implement this wrongly
- [ ] Frontend form initialises from the setting, not a literal
- [ ] Changing the default does not alter existing quotes
- [ ] US mode: tax rate is editable per line, entered manually, no default
      beyond the business setting

---

## ITEM 4 — Fix `parse_amount`

### What
`backend/main.py:2143` is a two-line stub returning `None` for every input.
CSV invoice import rejects every row and always has.

### Acceptance criteria
- [ ] Returns `Decimal`, not float
- [ ] Handles `1234.56`, `£1,234.56`, `$1,234.56`, `1,234.56`, `-50.00`, `50`
- [ ] Strips `£ $ €` and thousands separators
- [ ] Returns `None` for empty, whitespace or unparseable input — never `0.0`.
      A silent zero on a money import is worse than a rejection
- [ ] Unit tests cover every case including the failures

---

## ITEM 5 — Region and locale foundation (the seams, not the rollout)

### What
Record the region once, and put a single resolver in place that everything
else can read from later.

### Why it matters
Retrofitting this after launch means touching every money and date display in
the product. Adding the seam now costs hours; adding it later costs a rewrite.
**This item builds the plumbing, not the full rollout** — the 108 hardcoded
`£` in the frontend are Wednesday's job.

### Acceptance criteria
- [ ] `businesses.region` — `UK` or `US`, asked during onboarding and during
      admin-created signup, editable afterwards
- [ ] Derived defaults per region, in ONE place, not scattered:

      | | UK | US |
      |---|---|---|
      | currency | GBP | USD |
      | locale | en-GB | en-US |
      | date format | DD/MM/YYYY | MM/DD/YYYY |
      | tax label | VAT | Sales Tax |
      | default rate | 20 | 0 (manual) |
      | quote noun | Quote | Estimate |

- [ ] A terminology module — one map, no scattered ternaries:
      `Quote → Estimate`, `VAT → Sales Tax`, `VAT Number → Tax ID`,
      `Labour → Labor`, `Postcode → ZIP Code`, `Organisation → Organization`,
      `Cheque → Check`, `Turnover → Revenue`, `inc. VAT → incl. tax`,
      `Sole trader → Sole proprietor`
- [ ] Quote and invoice PDFs read currency and date format from the resolver,
      not from literals
- [ ] Existing businesses default to `UK` — no behaviour change for MSC or
      New Body
- [ ] The resolver is unit-tested for both regions

### ⚠ Note on "Estimate"
In US trades, `Quote` is an **Estimate**. Getting this wrong marks the product
as foreign on first screen. Worth getting right even in a v1.

---

## Out of scope — deliberately, with eyes open

- Automated US sales tax jurisdiction lookup. **Permanently out** until funded
- Europe as a region
- Full `float` → `Decimal` conversion across all 40+ sites. New and touched
  code uses Decimal; the rest waits
- Consolidating the seven independent total calculations
- The 108 hardcoded `£` in the frontend — Wednesday
- `assistant_chat.py` hardcoding 20% VAT — Wednesday
- CIS labour/materials split — **enabled** by the per-line `category` and
  `tax_treatment` columns added here, but not built
- **Credit notes.** Deferred, but seamed now. `invoices.invoice_type` already
  exists and already carries `ACCREC`, so the type discriminator is in place;
  **031 adds a nullable `related_invoice_id`** so a future credit note can
  point at the invoice it credits without a second migration against a table
  that by then holds real customer data. Nothing reads it yet
- `markup_percentage` stored but never totalled
- `paid_amount` vs `amount_paid` duplicate columns
- Editing a quote after conversion to an invoice

---

## Order of work

1. Opus: write the tests. **Michael reviews the tests.** No implementation
2. Opus: migration `031` — new table, 4dp widening, region, tax_registered,
   counter, partial unique index, line discount columns, nullable
   `related_invoice_id`. Rehearse on staging, prove the rollback
3. Sonnet: implement until tests pass
4. Apply `031` to prod via a step-by-step runbook
5. Smoke test: create quote → convert → PDF shows a correct tax invoice
6. Repeat the smoke test with a US-region business and `tax_registered = false`
