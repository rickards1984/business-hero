# Entitlement & Metering — Spec

RED tier. Tests written and reviewed before implementation, same discipline as
the money engine.

**Why this exists:** `require_feature` currently gates exactly one endpoint in
the whole backend — email. Quoting, Aria chat, WhatsApp, TTS, accounting sync
and the realtime voice handler have no server-side check. The frontend hides
buttons, which is presentation, not enforcement. Combined with owners being
able to write their own `plan_tier` and `feature_flags` via supabase-js, paid
AI spend is currently gated client-side.

Nothing in `audits/PRICING-MODEL.md` is enforceable until this is built.

**All four decisions are RESOLVED** (20 Aug 2026) — DECISION 1 in PART A,
DECISIONS 2, 3 and 4 in PART E. One open sub-question remains under DECISION 4
(which allowance the founder accounts should exercise). Otherwise nothing in
this spec is blocked on an answer; it is blocked on being built.

---

## PART A — One vocabulary

### The problem
Three incompatible plan vocabularies exist:

| Source | Values |
|---|---|
| `_plan_feature_defaults` (×2) | starter, pro, **business**, beta, paused |
| `plan_definitions` table | starter, pro, **enterprise** |
| `businesses_plan_tier_check` | starter, pro, **elite**, beta, paused |

Only `elite` is storable, so the top-tier branch of `_plan_feature_defaults`
is **unreachable** — no row can hold `plan_tier = 'business'`. And
`_resolve_plan_from_price` returns `"business"`, so a top-tier Stripe webhook
would fail the CHECK constraint on write. That is a live bug waiting for the
first top-tier sale.

`_plan_feature_defaults` is also **defined twice** — `auth.py:249` and
`main.py:2355` — with different lookup behaviour. `auth.py` lowercases and
defaults to `{}`; `main.py` does neither. So `"Pro"` resolves to
`{"email": True}` in one and `{}` in the other.

### DECISION 1 — RESOLVED: the top tier is `business`

**`business`** is the canonical identifier. It matches the customer-facing
name and most of the existing code. `elite` would have needed no migration but
would have left internal and external names permanently different, which is
its own trap and the sort that outlives everyone who remembers why.

**The canonical set is `starter`, `pro`, `business`, `beta`.**
`paused` is **removed** — see DECISION 3. `beta` stays as an operational state
for testing parity.

Migration work:

- CHECK constraint altered from
  `('starter','pro','elite','beta','paused')` to
  `('starter','pro','business','beta')`
- `plan_definitions.enterprise` renamed to `business`

**No data migration is needed for either.** Verified against prod 20 Aug 2026:
the only stored values are `pro` (2 businesses) and `starter` (4). No row
holds `elite`, `beta` or `paused`, so the constraint can be tightened and
`paused` dropped without touching a single row.

There is also a **fourth vocabulary** to remove while doing this —
`backend/main.py:836` maps two more names inbound:

```python
plan_tier = payload.plan_tier.lower()
if plan_tier in ("premium", "elite"):
    plan_tier = "business"
```

So `premium` and `elite` are both accepted from the client and silently
rewritten. That mapping becomes dead once the vocabulary is single, and
leaving it in place would quietly re-admit the names this decision removes.

### Acceptance criteria
- [ ] One canonical set: `starter`, `pro`, `business`, plus the operational
      state `beta`. **`paused` does not appear anywhere** — not in the CHECK,
      not in `_plan_feature_defaults`, not in the admin UI
- [ ] `_plan_feature_defaults` exists in **exactly one place**; `main.py`
      imports it rather than defining its own copy (`auth.py:249` and
      `main.py:2355` today, with different lookup behaviour)
- [ ] Lookup lowercases input and defaults to `starter` behaviour
- [ ] `plan_definitions` row `enterprise` renamed to `business`; its features
      must then differ from `pro`, or the tier is not a tier — they are
      byte-identical today
- [ ] CHECK constraint altered to `('starter','pro','business','beta')`
- [ ] `_resolve_plan_from_price` returns only storable values, and raises
      loudly on an unrecognised price rather than silently leaving the old
      tier in place. It returns `"business"` today, which the current CHECK
      would reject — a live bug waiting for the first top-tier sale
- [ ] The `("premium", "elite")` rewrite at `main.py:836` is removed, and an
      unrecognised `plan_tier` from the client is a 400 rather than a silent
      remap
- [ ] Frontend `PLAN_TIERS` (`AdminBusinessDetail.tsx:112`) and the tier
      dropdown (`AdminDashboard.tsx:648`) match the canonical set exactly
- [ ] A test asserts the CHECK constraint and the Python vocabulary agree —
      so they cannot drift again
- [ ] A test asserts every `plan_definitions.id` is in the canonical set

---

## PART B — One feature vocabulary

### The problem
Eleven distinct keys live in prod `feature_flags`, with near-duplicates
(`accounting` / `accounting_enabled`, `calendar` / `calendar_booking_enabled`)
and one that isn't a feature at all: `brand_color` holds a colour string, and
`bool("#3B82F6")` is `True`, so it reads as an enabled feature.

### Canonical features

| Key | Starter | Pro | Business |
|---|---|---|---|
| `quoting` | ✓ | ✓ | ✓ |
| `invoicing` | ✓ | ✓ | ✓ |
| `accounting` | ✓ | ✓ | ✓ |
| `email` | ✓ | ✓ | ✓ |
| `aria_chat` | ✓ | ✓ | ✓ |
| `aria_voice` | — | ✓ | ✓ |
| `whatsapp` | — | ✓ | ✓ |
| `board_meetings` | — | ✓ | ✓ |
| `calendar_booking` | — | ✓ | ✓ |
| `receptionist` | — | ✓ | ✓ |
| `outreach` | — | — | ✓ |

Starter includes `aria_chat` **text only** because email summarisation only
exists inside Aria — without it a Starter customer is paying for an email
client they could have free. `aria_voice` is separate because that is where
the cost is.

### Acceptance criteria
- [ ] One canonical list, defined once, used by backend and frontend
- [ ] `brand_color` **moves out** of `feature_flags` to its own column on
      `businesses`; existing values migrated, not dropped
- [ ] Duplicate keys consolidated: `accounting_enabled` → `accounting`,
      `calendar_booking_enabled` → `calendar_booking`,
      `quoting_enabled` → `quoting`, `whatsapp_enabled` → `whatsapp`
- [ ] Migration backfills both live businesses to the canonical names with no
      loss of currently-granted access
- [ ] Unknown keys are ignored rather than treated as features
- [ ] `services/tier_gating.py` is folded into the single mechanism — two
      gates with different logic is how they drift

---

## PART C — Plan is the source of truth

### The problem
`_is_feature_enabled` checks `feature_flags` first and returns immediately, so
`plan_tier` is only a fallback for keys absent from the flags. Worse,
`_merge_feature_flags` does `{**defaults, **existing}` — existing wins — and
**writes plan defaults into `feature_flags`**. Once a feature lands there, no
plan change removes it.

Live consequence: both businesses are on `pro`, which grants only
`{"email": True}` by default, yet carry up to eleven flags including
`receptionist` and `accounting`. Plan tier is close to decorative.

### The rule
```
enabled(feature) =
    feature_flags[feature]              if feature in feature_flags
    else plan_defaults[plan_tier].get(feature, False)
```

The difference from today is not the lookup — it is that **plan defaults are
never written into `feature_flags`.** That dict holds only deliberate
per-business exceptions set by a platform admin: a beta tester, a goodwill
grant, a feature disabled for one customer. Everything else comes from the
plan, live, at read time.

### Acceptance criteria
- [ ] `_merge_feature_flags` no longer writes plan defaults into
      `feature_flags`; the Stripe webhook sets `plan_tier` only
- [ ] A downgrade genuinely removes access — a `business` customer dropping
      to `pro` loses `outreach` immediately
- [ ] An explicit `false` in `feature_flags` denies even when the plan grants
- [ ] An explicit `true` grants even when the plan does not (the beta case)
- [ ] Migration cleans both live businesses: flags matching their plan
      defaults are removed, genuine exceptions retained. **List what will be
      removed for Michael's review before running it**
- [ ] `feature_flags` is writable only by a platform admin, only via the
      backend (this is 030b)

### Data on downgrade — decided
Data created under a higher tier stays **visible, read-only, indefinitely**.
No timer, no expiry job, no retention rules. It is the customer's data, it is
the least code, and the upgrade incentive is new functionality rather than old
records.

---

## PART D — Enforce it server-side

### Acceptance criteria
- [ ] `require_feature` on **every** paid surface. Currently gated: email
      only. Must add: quoting (`quoting_api`), Aria chat (`assistant_chat`),
      WhatsApp send, TTS preview, accounting sync, board meetings, calendar
      booking, and **the realtime voice handler** — the most expensive
      endpoint in the product and currently ungated
- [ ] The receptionist's hand-rolled `_require_receptionist_flag` is replaced
      by the standard gate
- [ ] Every gate **fails closed** — an unknown feature or missing business
      denies, never grants
- [ ] Frontend hiding stays, but is understood as cosmetic; a test calls each
      protected endpoint directly on a Starter plan and asserts 403
- [ ] A test enumerates every LLM/voice/Twilio call site and asserts each sits
      behind a gate, so a new expensive endpoint cannot ship ungated

---

## PART E — Metering

Without this, the voice allowances in the pricing model are decorative.

### Acceptance criteria
- [ ] `usage_meters` table: business_id, meter, period (YYYY-MM), value,
      updated_at, unique on (business_id, meter, period)
- [ ] Meters: `receptionist_minutes`, `outreach_prospects`
- [ ] `businesses` gains `metered_usage_enabled` (default false) and
      `monthly_spend_cap_gbp` (nullable, default £100 when metering is
      enabled without an explicit choice)
- [ ] Both are writable **only** via the backend — a customer raising their
      own cap through supabase-js would defeat the purpose (see 030b)
- [ ] Overage spend accrues to its own meter so it can be shown, capped and
      billed independently of allowance usage
- [ ] Voice minutes accrue at call end from actual duration, not estimated
- [ ] Allowance per plan: Pro 120, Business 350, Starter 0
- [ ] Usage visible to the customer **before** they hit the limit — a billing
      surprise is worse than a block
- [ ] A test proves the meter increments and the block fires at the limit

### DECISION 2 — RESOLVED: metered overage with a customer-set budget cap

Modelled on how LLM providers handle this: use your allowance, then either
wait for the monthly reset or opt in to metered usage with a ceiling **you**
set. Predictable for the customer, bounded for us.

- [ ] **Per-call hard cap of 20 minutes**, regardless of allowance. The
      receptionist answers basic questions and books appointments — a call
      running longer than that has gone wrong, and an AI talking to a
      voicemail loop can burn a day's budget unnoticed
- [ ] When the allowance is exhausted **mid-call, the call completes** — up to
      the 20-minute cap. Never cut a caller off mid-sentence
- [ ] **After** that call ends, new calls are blocked and the owner is
      notified immediately
- [ ] Notification carries a one-click **"enable metered usage"** toggle:
      £0.45/min until the monthly reset
- [ ] With metered usage on, the customer sets a **maximum monthly spend**.
      Reaching it blocks new calls and notifies again — no unbounded bill,
      for them or for us
- [ ] Default cap when they enable metering without choosing one: **£100**
- [ ] Usage and remaining allowance visible in-app **before** the limit is
      reached, not only at the point of failure
- [ ] Everything resets at the billing period boundary
- [ ] The same mechanism applies to **Aria** once text volume justifies
      metering it — build the meter generically, not voice-specific

Tests must cover: allowance exhausted mid-call completes; the next call is
blocked; enabling metering unblocks; the spend cap blocks again; the 20-minute
cap fires independently of allowance; the reset clears both.

### DECISION 3 — RESOLVED: `paused` is removed; status drives access

`paused` is **deleted from the plan vocabulary**. It conflated two things that
must stay apart: *what the customer bought* and *whether they have paid*.

The damage was concrete. Writing `paused` into `plan_tier` on a failed payment
**overwrites the record of what the customer purchased**. Once overwritten,
restoring them after they pay is guesswork — nothing left in the row says
whether they were on Pro or Business. A payment blip would permanently lose
the sale.

**The separation:**

| Column | Meaning | Changed by a payment event? |
|---|---|---|
| `plan_tier` | what was purchased | **Never** |
| `subscription_status` | whether it is paid for | Yes — this is Stripe's field |

`plan_tier` records the purchase and is only ever changed by an actual plan
change — an upgrade, a downgrade, or an admin acting deliberately.
`subscription_status` drives access.

**Access by status:**

| `subscription_status` | Access |
|---|---|
| `active`, `trialing` | Full access to everything `plan_tier` includes |
| `past_due` | **Full access**, with a warning banner. Stripe is still retrying — the customer has usually not done anything wrong, and a card that expired on Tuesday should not take the receptionist off the phones on Wednesday |
| `unpaid`, `canceled` | **Read-only** |

**Read-only means, precisely:**

*Can:*
- Log in
- View quotes, invoices and accounting history
- Export PDFs and CSV

*Cannot:*
- Create or edit anything
- Use any AI feature
- Send anything outbound
- Keep a Twilio number — **the number releases**

### Why read-only rather than lockout

Three reasons, and the third is the one that settles it.

**Legal retention.** UK businesses must keep VAT records for **six years**
(HMRC, VAT Notice 700/21). A customer who stops paying still has a statutory
obligation to produce those records, and their invoices are in here.

**Data portability.** GDPR Article 20 gives them the right to receive their
personal data in a structured, commonly used, machine-readable format. A
lockout that hides the export button obstructs a right they hold regardless of
their payment state.

**There is no cost argument.** Read-only makes **no LLM calls, no voice
minutes, no outbound sends** — the entire COGS of a read-only account is
database storage. So a lockout saves nothing measurable, and costs a
reputation: the story of a company that held a small business's VAT records
hostage over a failed card is the kind that gets told. Releasing the Twilio
number is the one real recurring cost, and that is why it is the one thing
that goes.

### Acceptance criteria

- [ ] **`plan_tier` is never written by a Stripe payment event.** The webhook
      may write it only when the subscription's *price* changes — a genuine
      plan change — and never in response to `invoice.payment_failed`,
      `customer.subscription.deleted`, or a status transition
- [ ] `subscription_status` is written from Stripe's value verbatim, not
      derived or normalised into a local vocabulary
- [ ] A single resolver maps `subscription_status` → access level, in one
      place, alongside the plan resolver from PART A
- [ ] `past_due` grants the **same** entitlements as `active`, and sets a
      user-visible warning state — a banner, not a silent flag
- [ ] `unpaid` and `canceled` resolve to read-only
- [ ] Read-only permits: login, viewing quotes/invoices/accounting history,
      PDF export, CSV export
- [ ] Read-only refuses: every create and edit path, every AI feature, every
      outbound send — enforced **server-side**, per PART D. Hiding the buttons
      is not enforcement
- [ ] Twilio number release is triggered on entry to read-only, and is
      idempotent — a repeated webhook must not attempt a second release
- [ ] Number release is **logged with the number and the timestamp**, because
      it is not reversible and the customer will ask
- [ ] Returning to `active` restores full access **from the unchanged
      `plan_tier`**, with no manual re-entry of what they had bought
- [ ] `paused` appears nowhere: not in the CHECK constraint, not in
      `_plan_feature_defaults`, not in `PLAN_TIERS`
      (`AdminBusinessDetail.tsx:112`), not in the admin dropdown
      (`AdminDashboard.tsx:648`)
- [ ] `is_active` and `subscription_status` have documented, non-overlapping
      meanings. `is_active` is the admin's manual switch; `subscription_status`
      is Stripe's. Today `require_feature` reads only `is_active`
      (`auth.py:~270`) and the webhook writes it from the Stripe status, which
      is precisely the conflation this decision removes

### Tests

**The one that matters most:**

- [ ] **A payment failure does not alter `plan_tier`.** Given a business on
      `plan_tier='business'`, deliver `invoice.payment_failed` and then a
      `customer.subscription.updated` carrying `status='past_due'`, and assert
      `plan_tier` is still `'business'`. Repeat for `unpaid` and for
      `customer.subscription.deleted` with `status='canceled'`. In every case
      `plan_tier` is unchanged and only `subscription_status` moves

Also:

- [ ] `past_due` resolves to the same entitlement set as `active` for the same
      `plan_tier`
- [ ] `unpaid` and `canceled` resolve to read-only
- [ ] A read-only business is refused on a create path, an edit path, an AI
      path and an outbound-send path — four separate assertions, server-side
- [ ] A read-only business **succeeds** on quote view, invoice view, PDF
      export and CSV export
- [ ] Restoring `status='active'` restores the full entitlement set for the
      original `plan_tier`, with no other column touched
- [ ] Twilio release runs once for repeated `unpaid` events (idempotency)
- [ ] No code path anywhere writes the literal `'paused'` to `plan_tier`


### DECISION 4 — RESOLVED: founder accounts pay zero, through the real billing path

MSC and New Body must not be charged, and must not bypass billing either.

**Approach: a Stripe 100% forever coupon on both**, with `plan_tier = 'business'`
and a genuine active subscription. The whole billing path runs — checkout,
webhook, `subscription_status`, renewal, entitlement resolution — and the
amount charged is zero.

**No `founder` or `internal` plan tier.** That would add a fifth entry to a
vocabulary this spec exists to reduce to four (PART A), and worse, it would
create a code path that only founder accounts ever take — which is the
definition of an untested one. The accounts that matter most for catching
regressions would be the accounts running code nobody else runs.

**New column: `businesses.billing_exempt`** — boolean, default `false`.
Usage still meters exactly as it does for a paying customer; metered overage
never charges. Writable **only via the backend**.

The coupon and the column do different jobs and both are needed. The coupon
zeroes the *subscription*; `billing_exempt` zeroes *metered overage*, which is
charged separately (PART E, DECISION 2) and would otherwise bill a founder
account at £0.45/min the moment it passed its allowance.

### Why not simply exempt them from billing

**Because bypassing billing means the founder stops dogfooding the billing
path — and that path has already failed silently for two months.**

Stripe webhooks stopped arriving after **21 June 2026**. The last
`customer.subscription.updated` in `stripe_events` is dated 21 June, and
`businesses.last_stripe_event_at` agrees to within four seconds, so nothing
was processed after that date. The cause was a **webhook pointing at a dead
Replit URL**. It went unnoticed until 20 August because there is no
reconciliation between Stripe and `businesses` — no poll, no startup check,
nothing that would ever have surfaced it (see `audits/FINDINGS.md`, Stripe
evidence pass).

An exempt founder account would not have caught it either. An account on the
real path, renewing monthly at zero, is the cheapest possible monitor for
exactly this class of failure — a renewal that does not arrive is visible in
a place someone looks.

**Second reason: allowance calibration.** Founder usage is currently the only
source of real data on whether the 120-minute (Pro) and 350-minute (Business)
receptionist allowances are set correctly. Those numbers are assumptions until
somebody's actual month is measured against them, and a founder account that
does not meter produces no such measurement.

**⚠ Open sub-question — which allowance gets tested?** Putting both founder
accounts on `business` means founder usage only ever exercises the **350**
allowance. The 120-minute Pro allowance — the one on the tier most customers
will buy — would remain uncalibrated. There are two founder accounts, so the
obvious answer is **one on `business` and one on `pro`**, which exercises both
allowances and both overage thresholds. Not decided here; flagging it because
the calibration rationale above is otherwise only half-served.

### Acceptance criteria

- [ ] Both founder businesses carry a real Stripe subscription with a **100%
      forever coupon** — not a trial, not a manually-set status. `checkout`,
      the webhook, and `subscription_status` all behave as for a paying
      customer
- [ ] `plan_tier = 'business'` on the exempt accounts, set through the normal
      plan path, not by direct edit
- [ ] **No `founder` or `internal` value exists** in the plan vocabulary — the
      canonical set stays `starter`, `pro`, `business`, `beta` (PART A)
- [ ] New column `businesses.billing_exempt boolean NOT NULL DEFAULT false`
- [ ] A `billing_exempt` business **meters usage identically** to a paying
      one — same counters, same increments, same period reset. Metering is not
      conditional on billing
- [ ] Metered overage is **suppressed but recorded**: the usage row is written
      with the minutes and the amount that *would* have been charged, plus the
      reason it was not. Suppressed revenue must be queryable — "what would
      founder usage have cost" is a real question with a real answer
- [ ] **The allowance block still fires.** Reaching the limit blocks new calls
      and notifies, exactly as for a paying customer, so the limit is genuinely
      tested rather than quietly infinite. `billing_exempt` waives the
      *charge*, never the *cap*
- [ ] Enabling metered usage on an exempt account still requires the explicit
      opt-in and still respects the customer-set spend cap (DECISION 2) — the
      cap is measured against the suppressed amount
- [ ] `billing_exempt` is writable **only** through a backend endpoint
      requiring platform-admin auth. No frontend write path exists
- [ ] **A column-level grant prevents client writes.** This is the criterion
      most likely to be missed: `authenticated` currently holds table-wide
      `UPDATE` on `businesses` (26 column grants), and `biz_update_if_owner` is
      column-blind — so `billing_exempt` would be writable from the browser by
      any owner the moment the column exists. Adding it **before** the grant is
      narrowed hands every owner a switch that turns off their own overage
      billing. This depends on the `030b` work and must not ship ahead of it

### Tests

- [ ] **`billing_exempt` cannot be set from the client.** Attempt the write as
      an authenticated owner via the anon key and assert it is refused at the
      grant layer — not merely absent from the UI. Assert the stored value is
      unchanged afterwards
- [ ] An exempt business and a paying business on the same tier produce
      **identical usage counters** for identical activity
- [ ] Overage on an exempt business records the suppressed amount and charges
      nothing; overage on a paying business charges
- [ ] The allowance block fires on an exempt business at the same threshold as
      a paying one
- [ ] `billing_exempt` defaults to `false` on a newly created business
- [ ] Suppressed overage is retrievable in aggregate for a period

---

## Out of scope

- Per-seat enforcement — seats are priced but not yet counted. Needs its own
  pass once `business_members` is the source of truth
- Stripe wiring — separate spec; depends on this one
- Outreach metering beyond a daily prospect count

---

## Order of work

1. ~~Michael answers Decisions 1–4~~ — **done, 20 Aug 2026**. One open
   sub-question under DECISION 4: which allowance the founder accounts
   exercise (both on `business`, or one on each)
2. **`030b` first** — narrow the `businesses` UPDATE grant. DECISION 4's
   `billing_exempt` column must not exist before this, or every owner gets a
   browser switch that disables their own overage billing
3. Migration `033` — CHECK constraint to
   `('starter','pro','business','beta')`, `plan_definitions.enterprise` →
   `business`, `brand_color` column, `billing_exempt` column, `usage_meters`,
   flag key consolidation. No data migration needed for the tier changes
   (prod holds only `pro` and `starter`). Rehearsed on staging, rollback
   proven
4. Tests written. **Michael reviews the tests**
5. Implementation until green
6. `033` to prod via runbook
7. Smoke test: a Starter business is denied voice, quoting and outreach at the
   API, not just in the UI
8. Founder accounts moved onto real subscriptions with the 100% coupon, and
   the next monthly renewal confirmed to arrive — the dead-webhook monitor
   from DECISION 4 only works once it has run at least once
