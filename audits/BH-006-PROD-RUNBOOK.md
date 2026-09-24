# BH-006 — PROD RUNBOOK

**Deploy:** the merge of BH-006's implementation branch is the deploy
(`AGENTS.md` §4). **This runbook is what must happen around it.**
**Target:** Business Hero prod — Supabase project **`oxblcmwhuwtobdhsfgyi`**.
**Why it exists:** two things the code cannot do for itself. One is a data
repair the fix makes necessary; the other is a constraint the fix's
correctness depends on and which is **not verified in production**.

Both are **RED** (`AGENTS.md` §2: any SQL against production). Mike runs
them. No agent connects.

---

## Before you start

The rules from `033-PROD-RUNBOOK.md` apply unchanged: one step at a time,
one query at a time (the Supabase editor renders only the last statement's
grid), EXPECT must match, and on a mismatch stop and report rather than
improvise.

**Confirm the project selector reads `oxblcmwhuwtobdhsfgyi` before every
paste.** Staging is `gzcrsrqmygublveuzqyg`.

**STEPS 0–3 ARE READ-ONLY. Nothing changes until STEP 4.**

**Ordering:** STEPS 0–3 can be run before the merge. **STEP 4 (the repair)
must run AFTER the deploy**, because the old code would immediately rewrite
`is_active` from the Stripe status and undo it.

---

## STEP 0 — Who is affected, and how badly (READ-ONLY)

The fix stops the webhook writing `is_active`. Rows it already wrote are
ambiguous: `is_active = false` could mean "the old webhook saw a failed
payment" or "an admin switched this business off deliberately", and no
column distinguishes them. `auth.resolve_access_level` keeps admin
suspension **absolute**, so those businesses stay suspended until repaired.

```sql
SELECT id, name, plan_tier, subscription_status, is_active,
       trial_ends_at, current_period_end, last_stripe_event_at
  FROM public.businesses
 ORDER BY is_active, subscription_status NULLS FIRST, name;
```

**EXPECT:** a handful of rows (single digits). **Save this output** into
`audits/BH-006-prod-before.txt` — it is the repair's reference and the
rollback's.

**How to read it.** Three groups matter:

| Group | Meaning | STEP 4 |
|---|---|---|
| `is_active = false` AND `subscription_status` IN (`active`,`trialing`,`past_due`) | **CANDIDATES for repair.** The old webhook wrote this for any non-active status, so most are wrongly locked out — but an admin suspension of a paying customer looks IDENTICAL, and no column distinguishes them. | **You name the ids** |
| `is_active = false` AND `subscription_status` IN (`unpaid`,`canceled`) | Read-only today, correctly — the resolver returns READ-ONLY for these regardless of `is_active`. **But the stale `false` is still there**, so if they pay and Stripe sends `active`, they land in row 1's state and stay suspended. | **Repaired too — see STEP 4b** |
| `is_active = false` AND `subscription_status` IS NULL | No Stripe subscription ever existed, so the old webhook never touched it. Almost certainly a genuine admin suspension. | Left alone |

**This is a judgement, not a query.** Codex's review corrected an earlier
version of this table that called every row in group 1 "locked out wrongly":

- Admin intent is **indistinguishable** from the webhook's writes. Only you
  know which businesses an admin switched off deliberately.
- A row with a **future `trial_ends_at`** may not have been locked out at all.

**So STEP 4 repairs an EXPLICIT LIST OF IDS that you have read and approved**,
not everything the predicate matches. Go through group 1 row by row. For each,
decide: was this business switched off on purpose? If in doubt, leave it out —
a wrongly-omitted row is a customer who calls support and gets fixed in a
minute; a wrongly-included one is a suspension you have silently reversed.

---

## STEP 1 — Is anyone in the failure this fixes right now? (READ-ONLY)

```sql
SELECT count(*) AS locked_out_wrongly
  FROM public.businesses
 WHERE is_active = false
   AND subscription_status IN ('active', 'trialing', 'past_due');
```

**EXPECT:** whatever STEP 0's first group counted. **If it is more than 0,
those customers are locked out of paid features right now** — that is the
live failure BH-006 defect 5 describes, and STEP 4 is what ends it.

**Note:** zero is a perfectly good answer, but it does **not** mean no
customer has ever hit a payment blip — only that none is in that state right
now. A business that went `past_due` and then paid would have had `is_active`
set back to true by the same old webhook, leaving no trace here. What zero
means is that there is nothing to repair in group 1 today.

---

## STEP 2 — THE CONSTRAINT THE DE-DUPLICATION DEPENDS ON (READ-ONLY)

**This is the most important read in this runbook.**

Defect 2's fix looks up `stripe_events.event_id` before applying an event.
Under concurrent delivery of the same event, two requests can both read
"not seen" — and what makes that safe is a **UNIQUE constraint** on
`event_id`: the loser of the race fails its commit and rolls back, having
applied nothing. Without the constraint, both apply, and the bug the fix
exists to close reappears under load.

`supabase/migrations/010_stripe_billing.sql:17` declares
`event_id text UNIQUE NOT NULL` — but **migration files are not evidence of
live state** (`AGENTS.md` §3.4), and `create_all()` would have created this
table from `models.py`, where `StripeEvent.event_id` is
`Field(index=True)` — **indexed, not unique**. So which one prod has depends
on which created the table, and nothing in the repository records that.
`audits/live-schema-public.txt` lists columns only. **Staging has no
constraints or indexes on this table at all.**

```sql
SELECT conname, pg_get_constraintdef(oid) AS definition
  FROM pg_constraint WHERE conrelid = 'public.stripe_events'::regclass
UNION ALL
SELECT indexname, indexdef FROM pg_indexes
 WHERE schemaname = 'public' AND tablename = 'stripe_events'
 ORDER BY 1;
```

**EXPECT:** a `UNIQUE (event_id)` constraint — most likely
`stripe_events_event_id_key` — plus the `id` primary key.

**IF THE UNIQUE IS PRESENT:** nothing to do. Record it in
`audits/BH-006-prod-before.txt` and go to STEP 3.

**IF THE UNIQUE IS ABSENT:** the de-duplication is best-effort until it is
added, and adding it is a **separate RED migration** — not a line in this
runbook. It needs its own before-snapshot and a duplicate check first,
because `ADD CONSTRAINT ... UNIQUE` **fails outright if duplicate
`event_id` rows already exist**, and given the two-month redelivery window
in 2026 they plausibly do:

```sql
-- Run this too, and report both outputs. It decides what that migration
-- has to do first.
SELECT event_id, count(*) AS copies
  FROM public.stripe_events
 GROUP BY event_id HAVING count(*) > 1
 ORDER BY copies DESC, event_id
 LIMIT 50;
```

**Report both. Do not add the constraint from here.** The fix is still a
strict improvement without it — it de-duplicates every sequential
redelivery, which is what Stripe actually does — but the concurrent case
stays open and must not be described as closed.

---

## STEP 3 — What the deploy will change for a past_due customer (READ-ONLY)

Nothing to run. Read it, so the smoke test in STEP 5 has a prediction to
check.

After the deploy, for a business with `subscription_status = 'past_due'`
and `is_active = true`: every paid feature keeps working, `GET /v1/me`
returns `payment_warning: true` with `access_level: "full"`, and **a warning
banner appears at the top of the app** (`SubscriptionBanner.tsx`, rendered in
`AppShell`).

For `unpaid` or `canceled`: `access_level: "read_only"`, a read-only banner,
and every POST/PUT/PATCH/DELETE refused with a 403 — **except**
`POST /v1/quotes/{id}/generate-pdf` and `POST /v1/billing/{checkout-session,
portal}`. The customer must be able to pay their way out.

**What "every write refused" does and does not mean.** Enforcement sits in
the three shared context dependencies, in the feature gate, and in the four
paths that authenticate themselves (assistant chat, TTS, realtime voice, the
inbound receptionist call). Codex enumerated the gaps in the first
implementation and they are closed. What is NOT claimed: that no endpoint
anywhere escapes it. Specifically still reachable for a read-only business:
OAuth *callbacks* (deliberate — a connection already begun can finish; using
it is refused), and provider callbacks that arrive with a valid provider
signature. Those are recorded in `NOT_PINNED` rather than asserted closed.

---

## STEP 4 — The repair. AFTER the deploy, not before.

**Gate: the deploy must be live.** Confirm Railway has finished and
`GET /v1/billing/status` returns the new fields (`access_level`,
`payment_warning`, `read_only`). Run this before the deploy and the old code
rewrites `is_active` from the next Stripe event, undoing it.

This clears the `is_active = false` that the old webhook wrote for
businesses whose subscription is in good standing. It touches **only** the
first group from STEP 0.

**Paste 4a FIRST, on its own.** It records exactly what is about to change,
which is what makes the rollback exact. Codex's review found the earlier
version of this step supplied one `BEGIN … COMMIT` block while telling you to
inspect before committing — pasted as given, it committed before you looked.

```sql
-- 4a: capture the before-state of the ids YOU approved in STEP 0.
--     Replace the id list. Nothing else in this runbook touches these rows.
CREATE TABLE IF NOT EXISTS public.zz_bh006_is_active_before AS
SELECT id, name, plan_tier, subscription_status, is_active, trial_ends_at,
       now() AS captured_at
  FROM public.businesses
 WHERE id IN (
   -- '00000000-0000-0000-0000-000000000000',   <- your approved ids, one per line
 );

SELECT count(*) AS rows_captured, count(*) FILTER (WHERE is_active) AS already_true
  FROM public.zz_bh006_is_active_before;
```

**EXPECT:** `rows_captured` equals the number of ids you listed, and
`already_true` is **0**. If `already_true` is not 0 you have included a row
that is not suspended — remove it and re-run 4a after
`DROP TABLE public.zz_bh006_is_active_before;`.

**Then 4b, on its own.** It repairs exactly the captured rows, and it covers
group 2 as well as group 1 — Codex's point: leaving the stale `false` on an
`unpaid`/`canceled` row means that when the customer pays and Stripe sends
`active`, the resolver sees `is_active = false` and suspends them. That breaks
"pay to restore", which is the promise DECISION 3 turns on.

```sql
-- 4b: the repair. Bounded by the captured table, so it cannot touch a row
--     you did not approve, whatever has changed since.
UPDATE public.businesses b
   SET is_active = true
  FROM public.zz_bh006_is_active_before z
 WHERE b.id = z.id
   AND b.is_active = false;
```

**EXPECT:** `UPDATE <n>` where `n` = `rows_captured` from 4a.

**STOP IF** `n` is smaller than `rows_captured`: a row changed between 4a and
4b, which means a Stripe event or an admin landed mid-runbook. Nothing is
broken — the repair is bounded — but find out which row and why before
continuing.

**Then 4c, to verify:**

```sql
SELECT z.id, z.name, z.subscription_status,
       z.is_active AS was, b.is_active AS now
  FROM public.zz_bh006_is_active_before z
  JOIN public.businesses b ON b.id = z.id
 ORDER BY z.name;
```

**EXPECT:** every row `was = false, now = true`. This compares **row by row**,
not by count — an earlier version compared counts only, and equal counts do not
prove the same rows were repaired.

**ROLLBACK 4** — exact, from the captured table, and it restores only rows
that are still in the state 4b left them:

```sql
UPDATE public.businesses b
   SET is_active = z.is_active
  FROM public.zz_bh006_is_active_before z
 WHERE b.id = z.id
   AND b.is_active = true;      -- do not stamp over a later deliberate change
```

Then `DROP TABLE public.zz_bh006_is_active_before;` once you are satisfied —
**not before**, it is the only record of the pre-state. (The `zz_` prefix keeps
it out of `scripts/dump-live-schema.sql`, which filters `zz\_%`, so it will not
appear in the schema guard.)

---

## STEP 5 — Smoke test (Mike, in the product)

1. A business in good standing: the receptionist, Aria and email all work.
2. `GET /v1/billing/status` returns `access_level: "full"` and
   `payment_warning: false`.
3. **The one that was broken:** if any business is `past_due`, confirm its
   paid features work and the banner state is `payment_warning: true`.
4. **Read-only, end to end.** The admin UI **cannot** set
   `subscription_status` — `admin_business_api.py:49` excludes it from the
   writable fields, so an earlier version of this step was unperformable
   (Codex found it). Two ways to do it for real, in order of preference:

   **(a) Through Stripe, on a test business** — the honest test, because it
   exercises the webhook too. In the Stripe dashboard, cancel that business's
   test subscription. Wait for `customer.subscription.deleted`, then confirm
   in the product:
   - quotes and invoices still **view**; the quote **PDF export still works**;
   - the **banner** appears saying the account is read-only;
   - creating or editing a quote is refused, with a message naming Billing;
   - Aria chat, Aria voice and email are refused;
   - `GET /v1/me` returns `access_level: "read_only"`.
   Then resubscribe and confirm **everything returns without re-entering the
   plan** — DECISION 3's payoff, and it works because `plan_tier` was never
   overwritten. Confirm `plan_tier` is still what it was throughout.

   **(b) By SQL on a test business, if (a) is not practical:**
   ```sql
   -- A TEST business only. Note the id first.
   UPDATE public.businesses SET subscription_status = 'canceled' WHERE id = '<test-id>';
   -- ... run the checks above ...
   UPDATE public.businesses SET subscription_status = 'active'   WHERE id = '<test-id>';
   ```
   This skips the webhook, so it tests the resolver and the enforcement but
   not the handler. Say which you did when you report.
5. Stripe dashboard → send a test `customer.subscription.updated`. Confirm a
   new `stripe_events` row appears. **Send the same event again** (Stripe
   lets you resend): confirm **no second row**, and that nothing about the
   business changed.

**STOP IF** step 5 produces a second row for the same `event_id` — the
de-duplication is not working, and that is the defect that cost money.

---

## STEP 6 — Record it

- `audits/BH-006-prod-before.txt` (STEPS 0 and 2 output) and
  `audits/BH-006-prod-after.txt` (STEP 4's list).
- `docs/CURRENT_STATE.md`: the webhook's four defects and the missing
  resolver move from open to fixed, **with the date and this runbook's
  result** — and the `stripe_events` UNIQUE constraint's actual state
  recorded either way.
- If STEP 2 found the constraint missing, raise the ticket for it.

---

## Still open after this runbook

- **Twilio number release on cancellation.** DECISION 3 says the number
  releases when a business goes read-only. It does not, and by instruction
  it is a separate ticket. **A cancelled business keeps its number and its
  monthly cost until that ticket lands** — the one read-only consequence
  that costs real money every month if forgotten.
- **CSV export of quotes and invoices, and PDF export of invoices.**
  DECISION 3 promises a read-only customer can export both as PDF and CSV.
  Searched 24 Sep 2026: the only CSV endpoint on either resource is
  `POST /v1/invoices/import/csv`, an import, and only quotes have a PDF
  endpoint. The resolver permits routes that do not exist. Invoices are the
  records with the six-year HMRC retention obligation, so this is the more
  consequential half. Recorded in `MISSING_EXPORT_SURFACE` in
  `backend/tests/test_readonly_resolver.py`.
- **The concurrent-delivery case**, if STEP 2 found no UNIQUE constraint. Even
  WITH it, two concurrent deliveries are safe only for the subscription
  branch; `checkout.session.completed` is now inside the same transaction, so
  it is covered too, but neither is proven under real concurrency by any test
  here — that needs a real database and is in `NOT_PINNED`.
- **OAuth and provider callbacks** for a read-only business (see STEP 3).
- **A frontend end-to-end test of the banner.** It is rendered and typechecked;
  nothing automated asserts it appears, because this repository has no frontend
  test harness (`docs/TESTING.md`). STEP 5 is the manual check.
