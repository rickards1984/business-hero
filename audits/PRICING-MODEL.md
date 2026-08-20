# Business Hero + Control Tower — Pricing Model

Working document. Figures verified August 2026; provider prices move, so
re-check before committing to public pricing.

All costs USD where quoted from providers, converted at ~£1 = $1.27.

---

## 1 · Tier structure — Business Hero

| | Starter | Pro | Business |
|---|---|---|---|
| **Base / month** | £69 | £129 | £269 |
| Users included | 1 | 3 | 6 |
| Extra seats | — | £25 | £25 |
| Quoting / estimating (AI) | ✓ | ✓ | ✓ |
| Invoicing + chasing | ✓ | ✓ | ✓ |
| Accounting sync (Xero/QBO/FreeAgent) | ✓ | ✓ | ✓ |
| Email summaries + categorisation | ✓ | ✓ | ✓ |
| **Aria chat (text only)** | ✓ | ✓ | ✓ |
| Aria voice | — | ✓ | ✓ |
| WhatsApp briefings | — | ✓ | ✓ |
| AI board meetings | — | ✓ | ✓ |
| Calendar booking | — | ✓ | ✓ |
| **AI receptionist** | — | 120 min | 350 min |
| **Control Tower outreach** | — | — | ✓ |

Voice overage **£0.45/min**. Control Tower standalone **£149/month** (§4).

### Why these numbers

A three-person trades business buying the parts separately today pays roughly
£226–266/month: Tradify at £37/user (£111), a standalone AI receptionist
(£80–120), Xero (£35). None of that includes outreach.

Pro at £129 saves them ~£100/month and consolidates to one login. That is a
defensible pitch. £79 would have been a third of the alternative — which reads
as low value rather than good value, and raising prices later on existing
customers is far harder than discounting now.

### Why Starter includes Aria chat

**Email summarisation only exists inside Aria.** The Emails section of the app
displays messages competently but does nothing an ordinary email client
doesn't. A Starter tier without Aria would be charging £69 for a free email
client plus quoting — not a tier, a disappointment.

Aria splits cleanly along the cost line: **text is pennies, voice is the
expensive one.** So Starter gets text Aria, and `aria_voice` stays
Pro-and-above. That is why Starter is £69 rather than £49 — it now does
something worth paying for.

Related, and on the UI list: the **"Analyse All" button in Emails does
nothing.** It is currently the only discoverable route to the feature Starter
is being sold on. Fixing it is a conversion issue, not a cosmetic one.

---

## 2 · Unit economics — what each feature actually costs

### The cost hierarchy

**voice ≫ outreach ≫ everything else combined.**

Everything below follows from that. Meter the first two; bundle the rest.

### Voice — the one that can bankrupt the model

OpenAI Realtime (`gpt-realtime-2`) bills $32/M audio input, $64/M output.
Audio is duration-encoded: ~600 tokens per minute of user speech, ~1,200 per
minute of assistant speech.

| Basis | Cost/min | Source |
|---|---|---|
| Bare audio only | ~$0.096 | token arithmetic |
| OpenAI "typical" | $0.30 | includes mid-turn text reasoning |
| Measured, uncached | $0.18–0.46 | production instrumentation |
| Measured, cached | $0.05–0.10 | 80%+ cache hit rate |

**Plan at $0.20/min. Do not plan at $0.096.** The text reasoning pass, not the
audio, is where most of the money goes.

What that means per customer:

```
20 calls/day × 4 min × 22 days = 1,760 min/month
1,760 × $0.20 = $352/month  ≈ £277
```

**A £129 plan with an unmetered receptionist loses money on every active
user, and loses most on the best customers.** This is why essentially every
AI receptionist in the market meters minutes — plans run $25–899 with
overages of $0.65–11 per call. The flat-rate "unlimited" players are
loss-leading or serving very low volume.

Allowance costs at $0.20/min:
- Pro, 120 min → $24/month ≈ **£19**
- Business, 350 min → $70/month ≈ **£55**

**The biggest margin lever in the product:** cached audio input is $0.40 vs
$32 — a 98.75% discount — and 80%+ hit rates are achievable if the system
prompt and tool definitions stay **byte-stable** between turns. That is a 3–4×
swing in unit cost decided entirely by how `receptionist_call_handler.py` is
written. Treat prompt stability as a margin feature, not a tidiness one.

Also: `gpt-realtime-2-mini` is ~60% cheaper across all rates. Worth testing
whether call quality holds for receptionist work — a routine "take a message
and book a slot" call may not need the flagship.

### Text AI — nearly free, if routed correctly

Email categorisation at 100 emails/day ≈ 4.5M input tokens/month:

| Model | Rate | Monthly |
|---|---|---|
| GPT-5.6 Luna | $0.20 / $1.20 | ~$1 |
| GPT-5.6 Sol | $5 / $30 | ~$22 |

**Same feature, 20× cost difference, decided by a config value.**

The codebase currently calls **five different models** across eight modules —
`gpt-4o-mini`, `gpt-4o`, `gpt-5`, `gpt-5.4`, and one env-configurable. Only
`QUOTE_AI_MODEL` can be changed without a deploy. Routing every call through
one configurable layer, with cheap models on high-volume work, is worth more
than any pricing decision in this document.

AI quoting (vision + generation) is ~15k tokens per quote. At 20 quotes/month
it is under £1 whatever model runs it.

### Twilio

Per-message and per-minute carrier costs, small but real, and they scale with
the same usage voice does. Fold into the voice allowance rather than tracking
separately.

### Estimated COGS per customer

| | Starter | Pro | Business |
|---|---|---|---|
| Text AI (incl. Aria chat) | £4 | £6 | £8 |
| Voice allowance | — | £19 | £55 |
| Outreach | — | — | £30 |
| Infra share | £3 | £4 | £6 |
| **Total** | **£7** | **£29** | **£99** |
| **Price** | £69 | £129 | £269 |
| **Gross margin** | **90%** | **78%** | **63%** |

Business is thinnest because it carries both cost centres. That is the honest
signal that voice and outreach must never both be unmetered.

---

## 3 · Data providers — Apollo and Hunter

| | Apollo | Hunter |
|---|---|---|
| Model | **per seat** | **per account, credits** |
| Entry | $49/user/mo (annual) | $34/mo — 2K credits |
| Mid | $79/user/mo — 6,000 credits/user/mo | $104/mo — 10K credits |
| Top | $119/user/mo (min 3 seats) | $209/mo — 25K credits |
| Monthly billing | +25–30% | ~30% cheaper annually |
| Team seats | charged per seat | **unlimited, shared pool** |
| Credit cost | 1/email, 8/phone | 1/email found, 0.5/verify |

Hunter also sells bulk packs — 1,000 search credits $50, 1,000 verification
credits $11 — and charges $10/month per extra sending account.

### What this means for a multi-tenant product

**Hunter's structure fits reselling; Apollo's does not.** Hunter is one
account, one shared credit pool, unlimited team members — you buy credits and
allocate them across customers. Apollo charges per seat, so a seat per
customer would be $79/month each and the economics collapse immediately.

Cost per outreach customer via Hunter at Growth rates:

```
30 prospects/day × 22 days = 660 credits/month
660 × ~$0.0104 = ~$7/month  ≈ £5.50
```

Very manageable. Data is not the expensive part of outreach — the LLM is.

### How Hunter should actually be used — batch top-up, not per-day supply

**The binding constraint is deliverability, not supply.** Sending above
roughly 30–50 emails a day from one address damages its reputation, and a
burned sending domain costs far more than any data subscription. Holding
10,000 contacts changes nothing if only 660 can be sent.

So Hunter is a **periodic batch top-up**, not a live lookup: one call weekly
or monthly, pulling a batch that is queued and released across the sending
window, alongside the existing research agent. It fills gaps and guarantees a
loaded queue — it does not replace the research agent or raise the ceiling.

Practical consequence: buy the **smallest tier that covers actual sends**.
Starter at $34/month is likely sufficient for a long time. Buying Growth or
Scale to sit on unusable inventory is the mistake here.

### Scope: Michael's account only, for now

Hunter goes in for Michael's own use first — it improves his own contact
quality immediately and defers the redistribution question entirely. Offer it
to customers only when one asks, and get Hunter's written answer on reselling
before that happens.

**The higher-value move is model quality, not more contacts.** Control Tower
agents still run `gpt-5.4` — two generations old and *more expensive* than
GPT-5.6 Terra. Better research at lower cost. When sends are capped at 30/day,
quality of contact beats volume every time.

### Hunter scope, restated so it is not misread later

Hunter is a **periodic batch top-up for Michael's account only** — not
per-customer supply, and not a live per-lookup integration. Deliverability
caps sends at **30–50/day regardless of how many contacts are held**, so the
size of the contact pool is not the constraint and buying a larger tier buys
inventory that cannot be sent. Revisit only if a customer asks, and only after
Hunter answer in writing on redistribution.

### Model routing — the open action

| Agent role | Today | Move to | Why |
|---|---|---|---|
| Research | `gpt-5.4` | **GPT-5.6** — and trial **Grok 4.6** | see below |
| Drafting | `gpt-5.4` | **GPT-5.6** | better output, lower cost |
| Orchestration / tool use | `gpt-5.4` | **GPT-5.6** | keep Grok out of this path |

`gpt-5.4` is two generations old **and more expensive** than GPT-5.6 Terra, so
upgrading research and drafting is cheaper and better at the same time — an
unusually easy call.

**Grok 4.6 is worth testing for research specifically.** It is turn-efficient
and cheap, which suits research where the work is read-heavy and the output is
a summary. Its weakness is terminal and tool use, which is exactly what
orchestration depends on — so **keep it off orchestration** and off anything
that drives the sending pipeline. Test it on research alone, compare against
GPT-5.6 on the same prospects, and adopt only if quality holds.

Sequencing note: this is a config change, not a build, and it lowers the
£20–40 LLM line in §4's COGS. Worth doing before that line becomes a real
bill — see the multi-tenant warning at the end of §4.

### ⚠ Risk to verify before building on Apollo

Contact-data providers typically **prohibit redistribution** of their data to
third parties. Pulling Apollo records under one seat and surfacing them to
paying customers may breach their terms regardless of the technical
arrangement. **Check Apollo's ToS and, if there is any doubt, ask them
directly about a reseller or OEM arrangement before building the integration.**
Discovering this after launch would mean removing a shipped feature.

Hunter's per-account-unlimited-seats model suggests more tolerance here, but
the same question applies and deserves the same explicit answer.

---

## 4 · Control Tower standalone — £149/month

Includes: AI prospect research, drafting, sending, follow-up, reply
classification, warm-lead CRM, health panel. Fair-use cap of 30 prospects/day
per business, matching the current engine's own limits.

### Comparison

| | Price | What it does |
|---|---|---|
| Hunter Starter | $34/mo | email finding only |
| Instantly / Smartlead | $30–97/mo | sequencing, no research |
| Apollo Professional | $79/user/mo | data + sequencing, per seat |
| **Control Tower** | **£149/mo** | research + drafting + sending + reply triage + CRM |

The category norm is a data tool plus a sequencer plus a human writing the
copy. Control Tower replaces all three. £149 sits above the sequencers and
roughly level with Apollo for a two-seat team, while doing materially more.

### COGS

| | Monthly |
|---|---|
| Hunter credits (660) | £5.50 |
| LLM research + drafting | £20–40 |
| Sending infra | £5 |
| **Total** | **£30–50** |
| **Gross margin** | **~70%** |

### ⚠ The economics change at multi-tenant

Control Tower currently runs on Michael's **ChatGPT OAuth quota** — free at
the point of use. Every customer added moves that to API billing. The £20–40
LLM line above does not exist today and will appear the moment a second
tenant does. Budget for it before pricing, not after.

---

## 5 · Structural rules

1. **Meter anything whose marginal cost scales with use** — voice minutes,
   outreach prospects.
2. **Bundle anything whose cost is effectively fixed** — quoting, invoicing,
   email, briefings, accounting.
3. **Never ship a metered feature without a hard cap enforced server-side.**
   The failure mode is not gradual: one customer discovers the receptionist
   and runs £400 of calls through a £129 plan before anyone notices. A billing
   problem already went unobserved here for two months.
4. **Route models through one configurable layer.** A 20× cost difference
   should never require a deploy to change.
5. **Price on value against the alternative stack, not on cost-plus.** The
   comparison is £226–266 of separate tools, not the £27 it costs to serve.

---

## 6 · What must be built before any of this is real

Current state, verified in code: `require_feature` gates **exactly one
endpoint** in the entire backend — email. Quoting, Aria chat, WhatsApp, TTS,
accounting sync and **the realtime voice handler** have no server-side
entitlement check at all. The frontend hides buttons; that is presentation,
not enforcement.

Combined with owners being able to write their own `plan_tier` and
`feature_flags` through supabase-js, **paid AI spend is currently gated
client-side.**

Also blocking:

- `_plan_feature_defaults` is defined **twice** (`auth.py:249`,
  `main.py:2355`) with different lookup behaviour — `"Pro"` resolves
  differently in each
- Three incompatible plan vocabularies: Python says `business`,
  `plan_definitions` says `enterprise`, the CHECK constraint says `elite`.
  Only `elite` is storable, so the top-tier branch is **unreachable**
- `_resolve_plan_from_price` returns `"business"`, which the CHECK constraint
  rejects — a top-tier Stripe webhook would fail the write
- `_merge_feature_flags` does `{**defaults, **existing}` — existing wins — so
  **a downgrade can never remove access**
- `brand_color` (a colour string) shares the namespace with entitlement flags;
  `bool("#3B82F6")` is `True`
- No usage metering exists for voice minutes or outreach volume

None of the pricing above is enforceable until the gate exists.
