# RC1 scope — the contractor edition

**Status: proposed. Not accepted.** Per the engineering brief, no large
implementation stream begins until Codex has independently reviewed this
foundation and Mike has accepted the boundary.

**Baseline:** `docs/CURRENT_STATE.md`, commit `9826f61`, 2026-09-08.

---

## The test every item is measured against

> **Does a UK contractor need this to pay for the product, and can we take
> their money safely?**

Two halves, and both must hold. A feature the customer needs but which lets
us lose money on them is not RC1-ready; nor is a billing mechanism with
nothing worth billing for.

RC1 is **the smallest commercially credible contractor edition**. The broader
platform architecture is preserved — nothing here proposes deleting a module
— but no additional feature delays the release.

---

## The RC1 journey

One journey defines the release. If it works end to end for MSC and ten
design partners, RC1 ships:

```
enquiry → customer → quote (AI or manual) → PDF to customer → acceptance
        → invoice → VAT-correct invoice PDF → payment recorded
        → accounting sync
```

Wrapped by: **a plan the customer pays for, enforced server-side, with
metered costs capped.**

Everything in P0 is on that line or is what makes it safe to charge for.

---

## P0 — prevents safe launch or completion of the core journey

### Money path

**P0-1 · Server-side entitlement enforcement**
`require_feature` gates exactly one endpoint (email). Realtime voice, Aria
chat, quoting, WhatsApp and accounting sync are authenticated but ungated.
**Board meetings are the exception and were wrongly listed here as ungated**
(review 001 finding 7): `backend/executive_meeting_api.py:51` calls
`require_tier_feature(...)`, a *second* server-side mechanism. That makes
this item's real problem clearer — not "one gate exists" but "three
mechanisms exist and only one is canonical". Paid AI spend is currently gated by hiding
buttons. Includes folding `services/tier_gating.py` and
`_require_receptionist_flag` into the single mechanism — three gates is how
they drift, and `tier_gating.py` still documents the removed `paused` tier.
*Blocks: every pricing decision.*

**P0-2 · Metering and hard caps**
`usage_meters` exists in the database and no code touches it. Without it the
120/350-minute allowances are decorative and a single customer can run £400
of voice through a £129 plan. Needs: minutes accrued at call end from actual
duration, the 20-minute per-call cap, allowance block with mid-call grace,
customer-set spend cap, and usage visible **before** the limit.
*Depends on P0-1.*

**P0-3 · Revoke the `businesses` UPDATE grant (`030b` Release 2)**
Owners can still set their own `plan_tier` and `feature_flags` from the
browser. Release 1 shipped and is confirmed working, which was the stated
precondition. RED: migration, staging rehearsal, proven rollback.
*Without this, P0-1 is bypassable by the customer.*

**P0-4 · Invoice PDF**
There is no invoice PDF at all. `quote_pdf.py` has no sibling. A UK VAT
invoice must legally show the VAT charged, so a contractor cannot issue a
compliant invoice from this product today. The money engine already computes
everything it needs.

**P0-5 · Manual invoice creation**
No `POST /v1/invoices`; the UI offers CSV upload only. A contractor who did
not quote through the product cannot invoice through it. Staged plan already
written in `audits/TIER1-CORE-FIXES.md` §3b.

**P0-6 · Stripe: subscription status drives access**
No `subscription_status` → access resolver exists. `past_due` must keep full
access with a banner; `unpaid`/`canceled` must go read-only (view, PDF and
CSV export still permitted — VAT records are a six-year statutory
obligation). The webhook currently conflates this with `is_active`.

**P0-7 · Stripe reconciliation**
Webhooks stopped for two months in 2026 and nothing surfaced it. A scheduled
comparison of Stripe subscriptions against `businesses`, alerting on
divergence. Small, and it protects every other billing item here.

Acceptance criteria added after review 001 finding 4 — both defects were
reproduced against the extracted handler, so these are known bugs, not
hypotheticals:

- [ ] `customer.subscription.deleted` no longer assigns a plan tier from the
      price the event happens to carry. `backend/main.py:990` currently
      handles created/updated/deleted identically, so a deletion carrying an
      old Pro price *upgrades* the business to `pro`
- [ ] The tier is written only when the price actually changes, per
      DECISION 3
- [ ] Event de-duplication is **atomic with** the business mutation. The
      `StripeEvent` row is written at `backend/main.py:1025`, after the
      commit at `:1022`; replaying the same event applies the write twice
- [ ] A replay test: deliver an identical event twice, assert one write

### Security and safety

**P0-8 · Establish live RLS, policy and grant state**
Currently **unknown**. The July audit listed ~30 tables with RLS off; three
migrations have landed since; the schema dump carries no policy data. One
query answers it. Until it is answered, no honest statement about tenant
isolation is possible — and any remediation is P0 the moment the answer is
bad.

**P0-9 · Tenant-isolation test**
Two businesses, the anon key, asserting one cannot read or write the other's
rows — on both the RLS path and the backend `WHERE business_id` path. The
July audit asked for this; it does not exist. It is the single highest-value
missing test.

**P0-9a · Fix the confirmed accounting cross-tenant leak** *(new — review
001 finding 5, reproduced locally against extracted code)*
`backend/accounting.py:200` joins categories on `t.category_id = c.id` with
the tenant filter applied **only to the transaction**, and
`backend/accounting.py:300` accepts a caller-supplied `category_id` without
checking that the category belongs to the caller's business. A transaction
referencing another business's category returns that business's category
name and colour. This is an **isolation** defect, not an entitlement one:
adding `require_feature` does not touch it, and the backend connects as an
elevated role that **bypasses RLS**, so the database will not catch it
either. Validate category ownership on create, update and bulk-update, scope
the join by `business_id`, and land the two-business regression test with
P0-9. Production exploitability is unverified — it needs authorised
inspection of live constraints.

**P0-10 · Complete 033 STEP 21**
Remove the stopgap `receptionist: true` from MSC and New Body once STEP 20d
passes against the deployed backend. Small, but it is an open RED item and
the entitlement model is not clean until it lands.

---

## P1 — materially damages the first customers' experience

**P1-1 · Multi-provider model routing**
Five models across eight modules; only `QUOTE_AI_MODEL` is changeable without
a deploy. `PRICING-MODEL.md` measures a 20× cost difference decided by a
config value, and Control Tower still runs `gpt-5.4` — two generations old
*and* more expensive than the current alternative. One configurable routing
layer.

*Why P1 and not P0:* it changes margin, not whether the product works or
whether we can charge safely. It becomes P0 the moment volume is real, and
it is cheap enough that it may well land inside the P0 window anyway.

**P1-2 · Dark mode invoice table contrast**
`design-system.css:456` vs `:2337`. Unreadable financial data in dark mode
and an accessibility flag at review. One CSS change, global across every MUI
table.

**P1-3 · Dashboard money truncation**
`£1,299.99` renders as `£1,299`. The correct formatter already exists
elsewhere in the same codebase.

**P1-4 · Chase-send error visibility**
Failure renders behind the open drawer; success floats above it. The user
reliably sees "sent" and reliably misses "failed" — on an action that
contacts a customer about money.

**P1-5 · Playwright smoke tests for the golden journeys**
There are no frontend tests and no end-to-end tests. Playwright over the
golden journeys, in dependency order — not full coverage, the minimum
critical layer:

1. Lead → quote → acceptance → invoice → payment (the RC1 journey)
2. Tenant and role separation — one business cannot reach another's records
3. Failure handling — AI, telephony, email or payment failure must not
   corrupt data or silently duplicate an outbound action

Journeys 4 and 5 from the engineering brief (incoming call → CRM update;
B2B prospect → outreach) and the contractor compliance journey are out of
RC1 and out of this item.

> **Until these exist, Mike is the browser test.**
>
> This is not a figure of speech and it is not temporary goodwill — it is
> the only browser coverage the project has. Therefore: **every UI-touching
> PR must state what Mike needs to click**, with the specific path, the
> expected result, and what failure would look like. A PR that touches the
> frontend and does not carry that section is not ready for review.
>
> The rule is enforced in `docs/DEVELOPMENT_WORKFLOW.md` §7 and
> `docs/DEFINITION_OF_DONE.md`. Each Playwright journey that lands retires
> a corresponding block of manual clicking, and the PR that adds it should
> say which.

**P1-6 · Daily pulse discards its AI output**
Pays for an OpenAI call on every run and throws the result away. Either use
it or delete the call.

**P1-7 · Quote button disambiguation**
"New Quote" goes to AI, "Create Quote" goes to manual, neither says so.
Naming only.

**P1-8 · Region rollout for contractors**
45 hardcoded `£` remain and `assistant_chat.py` hardcodes 20% VAT. The
resolver exists and is tested; it is not wired into the PDFs. A
non-VAT-registered sole trader — common among contractors — must never see
VAT applied.

---

## P2 — useful, deferred

- Audit logging (becomes P0 for the compliance module, not for RC1)
- MFA
- Local JWT verification instead of a remote round-trip per request
- Gmail N+1 batch fetch
- `accounting.py` `float` → `Decimal`
- Idempotency keys on `create_quote`, chase-send, WhatsApp actions
- Consolidating the seven independent total calculations
- Mixed per-line VAT rates (needs the nullable-column migration first)
- Credit notes (seam exists: `related_invoice_id`)
- Per-seat enforcement — seats are priced but never counted
- CRM as a first-class module
- Dependency vulnerability scanning in CI
- `backend/main.py` decomposition
- Two migration directories reconciled into one ordering
- Dead code removal (`docs/CURRENT_STATE.md` §9)

---

## Explicitly out of RC1

| Out | Why |
|---|---|
| **Compliance & site operations module** | Mike's explicit instruction. Marketed as "coming soon". `audits/COMPLIANCE-MODULE-BRIEF.md` |
| CHAS/CAS/SSIP evidence workflows | Part of the compliance module |
| Job / project management | Not on the money journey |
| Staff / contractor management | Not on the money journey |
| Mobile / site PWA for operatives | Part of the compliance module |
| B2B prospecting / Control Tower **in RC1** | Sold separately at £149/mo; not in this repository; economics change at multi-tenant |
| US region rollout | Seam built and tested. UK contractors are the wedge |
| Europe | Deliberate, per the money engine spec |
| Automated US sales tax lookup | Permanently out until funded |
| Hunter/Apollo customer-facing data supply | Redistribution terms unanswered |
| Per-line mixed VAT | P2; needs a migration |

---

## Review 001 boundary challenges — **for Mike's decision, not yet applied**

Codex challenged the boundary below (`audits/foundation-review-001-codex-report.md`
§6). These are recorded, not actioned: the RC1 boundary is Mike's acceptance
gate, so nothing here has been moved. Each needs a yes or no.

1. **P1-8 contains P0 tax behaviour.** "An invoice PDF from a non-registered
   business shows no VAT line at all" is a release criterion in *this
   document* (§What "RC1 ready" means), but the work sits in P1-8. Either
   move that slice into the P0 money path or drop the release criterion.
2. **Subscription-status access should be defined alongside P0-1**, not after
   P0-2. As sequenced, the same access decisions get implemented twice — once
   for plan gating, once for status.
3. **P0-3 must precede any claim that enforcement is effective**, since the
   `businesses` UPDATE grant lets a customer edit their own entitlement
   fields.
4. **Accounting-sync direction is undefined.** The RC1 journey ends in
   "accounting sync", but the inspected code imports provider data; no
   invoice-push implementation was found. Decide the direction before
   treating the journey as covered.
5. **Receptionist metering broadens "the smallest contractor edition".**
   Keep it in RC1 only as an explicit decision that receptionist service
   ships in RC1.

---

## Sequencing

The dependency order is not the priority order. This is the order.

```
P0-8  live RLS state          ─┐  answer first: it may create new P0 items
P0-9  tenant isolation test    │  and it is one query
                               │
P0-1  entitlement enforcement ─┼─► P0-2  metering ──► P0-6  status → access
P0-3  revoke the grant        ─┘                       │
                                                       ▼
P0-4  invoice PDF ──► P0-5  manual invoices      P0-7  reconciliation
P0-10 STEP 21 (independent, unblocks on deploy verification)
```

P0-8 goes first because its answer can change the scope of everything else.
P0-4 and P0-5 are independent of the entitlement chain and can run in
parallel with a second agent.

---

## What "RC1 ready" means

Every P0 item complete under `docs/DEFINITION_OF_DONE.md`, plus:

- [ ] The RC1 journey completes end to end for a **new** business, driven by
      Mike, in production
- [ ] A Starter business is refused voice, board meetings and outreach **at
      the API**, verified with curl and not by the absence of a button
- [ ] A receptionist allowance is exhausted in a test account and the block
      fires
- [ ] An invoice PDF from a VAT-registered business shows correct VAT; one
      from a non-registered business shows no VAT line at all
- [ ] A `past_due` business keeps working; an `unpaid` one is read-only and
      can still export
- [ ] Tenant isolation is proven by test on both DB paths
- [ ] Live RLS state is documented in `docs/PERMISSIONS_AND_TENANCY.md`
- [ ] No P0 item is "apparently complete but unverified"
