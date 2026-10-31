# PROFIT-2 — Real income and a running-costs tracker

**Tier:** RED: it changes what the profit guard's alarm (40%) and kill switch (80%) compare. **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

**Why:** PROFIT-1 counts income as each active business's *list* price (£69 / £129 / £269). Mike's £1.50 test subscription showed as £129 (28 Oct 2026). Fixed costs are one figure in Railway. Codex's backlog on PROFIT-1 and OUT-19 F asked for revenue from real Stripe amounts.

**Decided by Mike, 31 Oct 2026:**
1. **Income is real monthly amounts.** Each business counts its monthly charge as Stripe actually billed it on its last full monthly invoice, after discounts and before VAT.
   - A business with no invoice recorded yet counts its plan price, marked *estimated*.
   - Top-ups count as paid (as today).
   - Cash received so far this month is shown alongside, but doesn't drive the alarm. A customer billed on the 28th can't make the 2nd look like a loss.
   - **"Refresh from Stripe"** reads each business's paid invoices, so existing subscriptions are counted at once.
2. **Running costs are an itemised monthly list.** Mike adds each bill (Railway, Vercel, Supabase, Twilio, domains and so on) with its monthly amount.
   - The list carries forward each month, and a month can be corrected to the actual bill.
   - A 6-month history shows income, costs and margin.
   - `PLATFORM_FIXED_COSTS_PENCE` stays as the fallback while no list exists.

## Income (`services/stripe_income.py`)

**Recorded from the Stripe webhook's `invoice.paid`,** in the webhook's transaction and inside its 503 retry boundary. It runs before the handler writes the business row, as outreach billing does.
- **Which business:** the business is found by the invoice's subscription, else its customer. An invoice for no known business changes nothing.
- **Only once per invoice:** a durable `stripe_invoice:<id>` row per business (`usage_meters`). A redelivery, or the same invoice reached by a refresh, never counts twice.
- **Pounds only:** an invoice in another currency is logged and ignored.
- **Net amount:** `amount_paid` less its tax (VAT), never below 0.
- **Cash:** every paid invoice adds its net amount to the business's `stripe_paid_pence` for the UK month it was paid.
- **Recurring:** a full monthly invoice (`billing_reason` = `subscription_cycle` or `subscription_create`) sets the business's `stripe_recurring_pence` for that month. The latest paid one wins. A proration (for example a brand added mid-month) is cash, not recurring, so recurring is never overstated.

**Recurring income for a month:**
- **Which businesses:** every active, non-complimentary business.
- **Its amount:** its latest recorded recurring amount up to that month; otherwise its plan price, counted as estimated.
- **Plus:** top-ups paid that month.
- **The pre-launch trial budget stays a floor**, as in PROFIT-1.

The "costs more than it pays" list uses the same real amount.

**Refresh from Stripe** (platform admin only):
- For each business with a Stripe customer, it reads its paid invoices (the latest 24) and records each one through the same function.
- It is safe to run any number of times, and it never writes to Stripe.

## Running costs (`services/running_costs.py`)

**Storage:** items are stored per month in `platform_meters` as `fixed_cost:<name>` = pence, so no migration is needed. A `fixed_costs_set` marker means the month has been edited.
- **A month with no edits** shows the items of the latest earlier month that has them (carried forward), without writing anything. The profit guard reads costs on every AI call, so the read path never writes.
- **The first edit in a month** copies the carried-forward items into that month, then applies the change.
- **Fixed costs for a month:** the sum of its items. If no month up to then has any, `PLATFORM_FIXED_COSTS_PENCE` is used.
- **Names:** 1–60 characters, trimmed, letters, digits and `. - & ( ) /` and spaces.
- **Amounts:** whole pence, 0 to 10,000,000.
- **Which months:** only the current month and earlier can be edited, back to 24 months.

## Admin panel (platform admins only)

- **Running costs against income (extended):**
  - income split into real and estimated recurring, top-ups, and cash received;
  - costs (AI, voice, the fixed items);
  - the alarm and kill state as before.
- **Running costs:** the month's items, to add, change or remove, and "Refresh income from Stripe".
- **History:** the last 6 months' income, costs and margin.

## Endpoints

- `GET /v1/admin/profit`, extended with `income_detail` and `history`.
- `GET /v1/admin/profit/costs?period=`, `PUT /v1/admin/profit/costs` with `{period, name, pence}`, and `DELETE /v1/admin/profit/costs` with `{period, name}`.
- `POST /v1/admin/profit/refresh-income`.

**Tests first:** `backend/tests/test_profit_income_costs.py`.
