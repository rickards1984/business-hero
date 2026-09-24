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
| `is_active = false` AND `subscription_status` IN (`active`,`trialing`,`past_due`) | **Locked out wrongly.** The old webhook did this. A paying customer cannot use the product. | **Repaired** |
| `is_active = false` AND `subscription_status` IN (`unpaid`,`canceled`) | Correctly read-only. The resolver returns READ-ONLY for these regardless of `is_active`, so they already behave correctly. | Left alone |
| `is_active = false` AND `subscription_status` IS NULL | Ambiguous, and most likely a genuine admin suspension (no Stripe subscription ever existed). | **Left alone — you decide, per row** |

**STOP IF** the first group contains a business you know an admin suspended
on purpose. The repair would un-suspend it. Tell me which and it comes out
of the `WHERE` clause by id.

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

**Note:** zero is a perfectly good answer. It means no customer has yet hit
a payment blip, and the fix is preventative. It does **not** mean STEP 4 is
unnecessary — the next `past_due` event would have caused it.

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
and `is_active = true`: every paid feature keeps working, and
`GET /v1/billing/status` returns `payment_warning: true` with
`access_level: "full"`.

For `unpaid` or `canceled`: `access_level: "read_only"`, every GET still
works, every POST/PUT/PATCH/DELETE is refused with a 403 saying so — except
`POST /v1/quotes/{id}/generate-pdf` and the two `/v1/billing/*` paths, which
must keep working. **The customer must be able to pay their way out.**

---

## STEP 4 — The repair. AFTER the deploy, not before.

**Gate: the deploy must be live.** Confirm Railway has finished and
`GET /v1/billing/status` returns the new fields (`access_level`,
`payment_warning`, `read_only`). Run this before the deploy and the old code
rewrites `is_active` from the next Stripe event, undoing it.

This clears the `is_active = false` that the old webhook wrote for
businesses whose subscription is in good standing. It touches **only** the
first group from STEP 0.

```sql
-- Wrapped deliberately. Read the count, then COMMIT or ROLLBACK by hand.
BEGIN;

UPDATE public.businesses
   SET is_active = true
 WHERE is_active = false
   AND subscription_status IN ('active', 'trialing', 'past_due');

-- EXPECT: the exact count STEP 1 reported. If it differs, ROLLBACK.
SELECT id, name, plan_tier, subscription_status, is_active
  FROM public.businesses
 WHERE subscription_status IN ('active', 'trialing', 'past_due')
 ORDER BY name;

-- Only if the count matches STEP 1 and the rows are the ones you expect:
COMMIT;
```

**EXPECT:** `UPDATE <n>` where `n` is exactly STEP 1's count, and every
listed row now `is_active = true`.

**STOP IF** the count differs from STEP 1 — something changed between the
two reads, which means an event landed mid-runbook. `ROLLBACK`, re-run
STEP 1, and start this step again.

**STOP IF** any row in the list is a business an admin suspended on purpose.
`ROLLBACK` and tell me; the statement gets an `AND id NOT IN (...)`.

**ROLLBACK 4** (after COMMIT — from STEP 0's saved output, per id):

```sql
UPDATE public.businesses SET is_active = false WHERE id IN (
  -- the ids from STEP 0's first group, and ONLY those
);
```

This is why STEP 0's output must be saved before STEP 4 runs: it is the
only record of which rows were false.

---

## STEP 5 — Smoke test (Mike, in the product)

1. A business in good standing: the receptionist, Aria and email all work.
2. `GET /v1/billing/status` returns `access_level: "full"` and
   `payment_warning: false`.
3. **The one that was broken:** if any business is `past_due`, confirm its
   paid features work and the banner state is `payment_warning: true`.
4. Admin → set a test business's `subscription_status` to `canceled`
   (admin UI, not SQL). Confirm: quotes and invoices still **view**; the
   PDF export still works; creating a quote is refused with a message
   naming Billing; Aria and email are refused. Then set it back to
   `active` and confirm everything returns **without re-entering the plan**
   — that is DECISION 3's payoff, and it works because `plan_tier` was
   never overwritten.
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
- **The concurrent-delivery case**, if STEP 2 found no UNIQUE constraint.
