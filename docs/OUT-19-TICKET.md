# OUT-19 — Outreach that always pays its way: costs, prices, top-ups, boosts and AI failover

**Tier:** RED. It covers billing (Stripe), sending limits and AI spend.
**Decided by Mike, 25 Oct 2026.** Every feature must cover all its AI and sending costs with a net profit on top: never "a money losing monster". Builds on OUT-18 (per-brand research, setup, sending and monthly allowance).

## Decisions

1. **"20 a day" means 20 emails per inbox (A).**
   - Research finds only as many new contacts as the brand's inbox can email, about 8 a day once follow-ups run, instead of a fixed 20.
   - No paid research is wasted on contacts that can't be emailed.
2. **Replies are never held back by the cold-email cap.**
   - Answering someone who wrote back is conversation, not cold outreach. Replies don't count toward the brand's 20 a day.
   - They are bounded only by a per-inbox safety ceiling (warm-up cap + 20, at most 70 a day).
   - When replies near that ceiling, Aria offers three choices, in a few clicks:
     1. **Boost** the inbox (if it qualifies, see 5);
     2. **Add a warmed second inbox** for the brand;
     3. **"I'll reply myself"**: Aria briefs the owner (who, what they asked, the suggested answer and the facts behind it) to send from their own email.
3. **Prices:**
   - the first brand is included in Business (£269);
   - each extra brand is **£79/month**;
   - the add-on on Pro is **£99/month** for its first brand.

   Mike monitors real costs during his own month as a customer, and prices are adjusted from that evidence.
4. **Top-ups through Stripe, in a few clicks.**
   - One-off payments: Checkout with the saved card, no new card entry.
   - Each is priced at cost × 3 or more.
   - Each raises only its own share of the AI cost ceiling, so the margin stays locked in.
5. **Boost.**
   - An inbox that has sent 20 a day for 4–6 weeks with clean results may step up to 30, then 40, then 50 a day. Each step is held about 2 weeks; it drops back a step automatically if results worsen.
   - "Clean results" means:
     - bounces under 2%;
     - no complaints;
     - unsubscribes under about 1%;
     - SPF/DKIM/DMARC passing daily;
     - healthy replies.
   - **50 a day per inbox is the ceiling.**
   - More volume comes from a properly warmed additional inbox, each with its own limits. Rotating inboxes to evade limits is never allowed (OUT-2).
   - The boost screen says reputation is judged from our own evidence. Business Hero can't see Google's or Microsoft's internal score.
6. **AI provider failover.**
   - Every outreach AI call goes through one routing layer with an ordered list of providers and models: research, drafting, reply classification, suggested answers and summaries.
   - If the primary fails, the next one in the list is used. Example order: OpenAI → xAI Grok → Anthropic Claude, each at a comparable capability. Failure means an outage, rate limit, exhausted credit or repeated errors.
   - The order is a setting, not code: no deploy is needed.
   - Each provider has its own prices for the cost reservation, so the spend caps hold whichever one runs.
   - Research uses each provider's own web-search tool. A provider without one that matches our verification rules is skipped for research.
   - The admin panel shows which provider served each call and any failover.

## What gets built

### A — Cost ledger (first: it measures everything else)
- Every outreach AI call records its cost. This includes calls whose output is then refused, and calls that fail or time out.
  - A call with unknown usage is recorded at a conservative estimate and counted as estimated, never as free.
- The cost is kept per UK month for each business × purpose × brand × provider/model, with:
  - calls, estimated calls, input and output tokens, tool calls and pence;
  - in `usage_meters`, so no migration.
- Monthly aggregates at that grain are the audit record; individual calls are not stored one by one.
- Prices:
  - There is one price table for research reservations, settlement and drafts. AI_PRICES_JSON overrides it, and a configuration with any invalid entry is ignored as a whole.
  - A model with no price is refused before any spend.
  - The default prices must be checked against the providers' current pages.
- The admin panel shows each business and brand for this month and last: projected outreach revenue, AI cost and incremental outreach margin.
  - Revenue is projected from the current plan and the brands existing that month; invoices come with part F.
  - A Business plan's included brand has £0 outreach revenue.
- **A platform-wide monthly AI spend alarm and kill switch, set by Mike** (AI_MONTHLY_ALARM_PENCE / AI_MONTHLY_KILL_PENCE).
  - Ledger writes are serialised platform-wide (the ledger lock comes after any business lock, followed only by meter-row writes), so the alarm is raised once, after commit; a rolled-back transaction's alarm is discarded.
  - The kill switch checks RECORDED spend before each call. A call already running when the limit is reached completes and is recorded, so the limit can be exceeded by at most the calls in flight.

### B — Hidden cost ceiling per brand
- Each brand's AI spend is capped at a share of what it pays: 25–30%, e.g. £79 → about £20/month.
- When it is reached, research stops until next month or a top-up. Drafting replies continues within a small reserve, so conversations are never stranded.
- This replaces today's owner-set £20+ research budget as the hard ceiling. The owner's budget (C) can only lower it.

**Decided (Mike, 27 Oct 2026: "Go with the recommendations. We can always review this when live"):**
- **The allowance is 25% of what the brand pays:**
  - the Pro add-on, £99 → **£24.75** a month;
  - an extra brand, £79 → **£19.75**;
  - a Business plan's included brand → a fixed **£20**.

  A top-up (F) adds a third of its price to that brand's allowance for that month.
- **All of a brand's AI spend counts:** research, Aria's drafting and reply sorting, from the OUT-19 cost ledger. Research reservations in flight count too.
- **At the allowance:**
  - research makes no further paid search until next month or a top-up, and says so with the top-up option;
  - Aria's drafting carries on within a small reserve (`DRAFT_RESERVE_PENCE`, £3), then asks the owner to top up or write it themselves;
  - **reply sorting never stops:** an unsubscribe must always be understood. Its cost is still recorded.
- **The owner's research budget can only lower the allowance,** never raise it.
- **The owner sees how much of the allowance is used, as a percentage, not the figure.** Mike sees the figures in the admin economics panel.

### C — The owner's monthly budget
- A single £ figure for add-on brands and top-ups. Aria suggests a realistic amount from the brands, inboxes and warm-up stages. Nothing is charged beyond it.

**Decided (Mike, 27 Oct 2026):**
- **The budget** is one £ figure a month for what outreach may charge beyond the plan: paid brands and top-ups.
- **Aria's suggestion:** each paid brand's price plus room for one £25 top-up per brand.
- **Only the active owner sets it,** and never below what is already committed (the paid brands).
- **Every future charge** (an extra brand, a top-up: part F) must pass `can_charge`. With no budget set, nothing beyond what's already committed is charged until the owner chooses one; Aria's suggestion is one tap.

**Tests first:** `backend/tests/test_outreach_allowance.py`, 16 tests, strict xfail until Mike approves. **Mike approved them on 27 Oct 2026**, with one condition: "as long as we are always looking at a net profit for all transactions". PROFIT-1, below, is proposed to cover the rest of the platform.

**Codex review 1 (`audits/OUT-19-BC-CODEX-REVIEW-1.md`, 1 × P1):**
- **Drafts are held before Aria starts.** A draft's likely cost (`OUTREACH_DRAFT_HOLD_PENCE`, 50p) is held under the business lock before Aria starts, so drafts and research running at once all see it. It is released when the real cost is recorded; a failed recording leaves it counted (fail closed).
- **Legacy research spend counts.** Spend on the business-wide research meter from before OUT-18 counts against every brand.
- **Meter names are matched literally,** with `_` escaped.
- **No top-up offers yet.** Messages no longer offer top-ups before part F exists.
- **Reply sorting is tested behaviourally** above the allowance.
- **Still for part F:** combining `can_charge` with a durable charge reservation under one lock. Today it is a predicate only.

**Codex review 2 (`audits/OUT-19-BC-CODEX-REVIEW-2.md`, P1 not closed) → fixed:**
- **The hold is the true worst case.** For Aria's real drafters, a draft's hold is `ai_router.chat_bound_pence`: the whole provider chain's worst case for that request (every provider tried, every character a token, the full output, at the highest rate), as `json_chat` charges a failed attempt. So what a draft records stays within its hold, and overlapping drafts stay within the allowance plus the £3 reserve. The exception is a provider billing more than the text it was sent plus framing; that is logged and stated below as a residual risk.
- **The instructions are bounded.** Aria's instructions are tested to fit `SYSTEM_PROMPT_MAX_CHARS`.
- **Unknown failures stay held.** A draft that fails without reporting its usage keeps its hold (it may have been billed).
- **The tests discriminate.** They use deliberately expensive prices, so a fixed hold fails them. Reply sorting above the allowance is shown to still record its cost.

**Codex review 3 (`audits/OUT-19-BC-CODEX-REVIEW-3.md`, the third cycle, P1 still open on two narrower points) → fixed. A further review is Mike's call:**
- **Only a successful draft releases its hold.** A draft that fails keeps its whole hold beside whatever it recorded: an attempt interrupted after dispatch may have been billed.
- **The bound covers message framing.** It adds `PROVIDER_OVERHEAD_TOKENS` for the tokens a provider counts beyond the text. A draft that ever records more than its hold is logged as an error.
- **The request is frozen** before its hold is worked out, so the bound and the call see the same context.
- **Residual risk:** a provider billing far more input tokens than the text it was sent. That's not seen in practice; the allowance still stops all further spend once it's reached.

**Codex review 4 (`audits/OUT-19-BC-CODEX-REVIEW-4.md`, authorised by Mike).** The P1 is closed; Codex accepts the residual risk, since the allowance is a quarter of the price. It does not on its own prove "always a net profit" for the whole platform; PROFIT-1 covers that. Two P2s are fixed:
- **A refusal releases its hold.** Every provider reported its failure and each attempt was recorded, or none was dispatched (all down), so the accounting is complete. An outage's retries never use up the brand's month.
- **The framing-margin test now sits at the boundary:** one provider, the longest instructions, the full output. It fails without the margin.

### D — Research sized to sending capacity (decision 1)
Built on branch `ticket/OUT-19-D-research-capacity`; tests in `backend/tests/test_outreach_research_capacity.py`.

- **Room per search.** Before each paid search, and again under the lock before anything is stored, research works out how many new contacts the brand can email for the first time today:
  - **what can be sent today** = the smallest of:
    - the brand's 20 (or the owner's lower cap);
    - each campaign's cap;
    - each campaign mailbox's warm-up limit, the same number the send path enforces (`metering.mailbox_daily_cap`, asserted equal inside `reserve_outreach_usage`). An inbox shared by two brands is counted once.
  - **minus what is already spoken for:**
    - sends made or held today;
    - follow-ups due by the end of today;
    - contacts waiting for their first email (enrolled and not sent, or found today and not enrolled).
  - Never above 20 and never below 0. Once follow-ups run, this settles at about a third of the inbox's limit.
- **No room, no search.** A brand with no ready campaign on a healthy inbox, or a full inbox, makes no paid search, and the summary says why.
- **The brief** asks for some spare (up to twice the room, at most 5 extra), since verification turns some candidates away. Only the room is kept, and the "at least N named decision-makers" requirement scales with it.
- **Codex review 1 (`audits/OUT-19-D-CODEX-REVIEW-1.md`, 5 × P1) → redesigned.**
  - Each contact kept takes a place in a campaign **for its audience**, enrolled in the same locked transaction that stores it, so retries, other audiences and other brands always see the places already taken.
  - Today's use is counted whatever the campaign's state now. An email already being sent counts once, as a send.
  - The room is checked under the same lock as the spend reservation.
  - Only one paid search runs per business at a time; a second run waits and pays nothing. The claim expires after 10 minutes if a run dies.
  - Manual enrolment reads the same pilot setting.
- **Codex review 2 (`audits/OUT-19-D-CODEX-REVIEW-2.md`, 2 × P1).**
  - A contact is kept only with a campaign place; one that cannot join is not collected.
  - Contacts held for review use today's room, counted from the database, so later attempts and runs see them.
  - The search claim runs on the real clock. Its owner renews it before each paid search and before storing; a run that lost it stops and never takes it back.
  - Whatever fails, the claim is released.
- **Codex review 3 (`audits/OUT-19-D-CODEX-REVIEW-3.md`, 1 × P1).** Contacts held for review, from every brand, now use the inbox of a ready campaign for their audience, so a brand sharing that inbox sees them too. Its regression test is `test_reviews_use_a_shared_inbox_for_every_brand_on_it`. Three cycles are done, so a further review is Mike's call.
- **Codex review 4 (`audits/OUT-19-D-CODEX-REVIEW-4.md`, Mike authorised it beyond three cycles, 1 × P1).**
  - A contact held for review also takes its campaign's place, both the campaign's daily cap and its pilot places, each counted once.
  - Test setup now runs on a clock an hour before the pinned research time, instead of the real one. A real clock past the pinned time had made audience approvals read as out of date.
- **Codex review 5 (`audits/OUT-19-D-CODEX-REVIEW-5.md`, no P1s, 1 × P2).** The research run in tests now also uses the pinned clock (`run_clock()`), so the suites pass at any real time of day. They were checked with the clock faked to 00:59, 06:00, 07:45 and 23:30 UTC.
- **Pilot limit (OUT-10 decision E).** It stays at 5 active contacts per campaign for the first week of the restart, so research also keeps no more than can join a campaign. `OUTREACH_PILOT_ENROLMENTS` raises it without a deploy; `0` lifts it, leaving the inbox's capacity to decide. Before lifting it, index `prepare`'s scan of open cards (OUT-8 ticket, note 2).

### E — Replies outside the cold cap, with the over-ceiling choices (decision 2)
Built on branch `ticket/OUT-19-E-replies-outside-cap`, stacked on D. Tests are in `backend/tests/test_outreach_replies_ceiling.py`.

- **Sending (`metering.reserve_outreach_usage`).**
  - A reply (a `bespoke` message) skips every cold limit: the campaign's cap, the brand's 20, the monthly allowance and the inbox's warm-up limit.
  - Replies count only against the inbox's safety ceiling, `reply_ceiling(cap)` = the warm-up limit + 20, never above 70. The ceiling also binds cold emails, so an inbox never sends more than it in a day.
  - Cold limits are counted from the usage events without replies. An email whose kind is unknown counts as cold.
- **Research (D).** Replies never reduce the room for new contacts.
- **The owner's three choices.**
  - `GET /v1/outreach/inboxes/headroom` lists each campaign inbox's room today. The inbox is flagged near the ceiling at 5 or fewer left.
  - The banner on the home page and the Outreach replies page offers:
    1. **I'll reply myself.** Each reply card shows **Aria's briefing** (`GET /v1/outreach/replies/{id}/brief`, owner only): who wrote, what they asked, her suggested answer and the approved facts behind it, with copy buttons. "I'll handle this" then stops her following up.
    2. **Add a second inbox**, through setup.
    3. **Boost this inbox**, shown but disabled until part G exists.
- **Codex review 1 (`audits/OUT-19-E-CODEX-REVIEW-1.md`, 2 × P1).**
  - The briefing offers Aria's suggested answer only if it still rests on today's approved facts for the matched campaign's brand; otherwise it says why.
  - Both new reads pass the canonical outreach feature gate. The briefing is reply history, so it survives a downgrade like other reply reads; headroom needs full access.
  - Past the contact's retention date, the briefing withholds their details and message.
  - Headroom says when an inbox can't send today, because it isn't passing its checks or today's check hasn't run.
  - Tests now isolate the inbox's warm-up limit, and cover kinds that are unknown (NULL) or unrecognised, and held and unknown outcomes.
  - The wording no longer promises every reply gets answered. Boost is labelled "coming later", a missing suggestion gives its real reason, and fact sources are shown.
- **Codex review 2 (`audits/OUT-19-E-CODEX-REVIEW-2.md`, no P1s, 1 × P2).**
  - The retention notice now says the details are withheld from the briefing, not that they're deleted.
  - Backlog done: headroom ignores a health check dated in the future, as the send path does, and new tests show neither the briefing nor headroom reaches another business.

### F — Stripe: extra brands as subscription items, top-ups and boosts as one-off payments (decisions 3–4)
- Entitlement checks follow the existing webhook rules (BH-006).

**Decided (Mike, 29 Oct 2026: "Go with recommendations ... they also protect expenditure vs income"):**
1. **A new paid brand is charged straight away.** It's added to the customer's existing Stripe subscription as an item, pro-rata for the rest of the month (`proration_behavior=always_invoice`), then billed with the plan each month.
2. **It goes live only once Stripe confirms the payment.**
   - `payment_behavior=pending_if_incomplete`: the subscription changes only when the invoice is paid, and the webhook then shows the new quantity.
   - Until then the brand can be set up, but research and cold sending are off. Replies are never stopped.
3. **Top-ups (£10, £25 or £50) are paid on Stripe's own payment page** (Checkout). *Changed by Mike on 30 Oct 2026, after Codex review 2: previously "two taps on the saved card".*
   - Every charge passes the owner's budget (C), **reserved under the business lock** before Stripe is called, so two top-ups at once can't pass the budget.
   - The top-up is credited only when Stripe says the page was paid, once (keyed on the page). The reservation is released only when Stripe says the page expired (60 minutes) or its payment failed.
4. **Removing a paid brand stops billing at the end of the month already paid.** The quantity is reduced with no proration, and the brand stays live until the period ends. No refund.

**Also decided:**
- **Grandfathering.** Brands that exist when F goes live stay live with no billing change; this includes Mike's own.
- **Free-month switch.** An admin flag, `outreach_brands_free`, keeps every brand of a business live without billing, for the free-month businesses.

**Mike sets these in Stripe and Railway:**
- two recurring monthly prices in GBP: "Extra brand £79/month" (`STRIPE_PRICE_EXTRA_BRAND`) and "Outreach add-on £99/month" (`STRIPE_PRICE_OUTREACH_ADDON`). Each paid brand gets its own price, made from the same product and amount; if the configured price isn't exactly that amount, monthly, in pounds, nothing is charged;
- the webhook events `checkout.session.completed`, `checkout.session.expired`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `customer.subscription.updated` and `invoice.paid`.

**Tests first:** `backend/tests/test_outreach_billing.py`, strict xfail until Mike approves. **Mike approved them on 29 Oct 2026.**

**As built:**
- **Module and endpoints.** `services/outreach_billing.py`, with these routes:
  - `GET /v1/outreach/setup/billing`;
  - `POST` and `DELETE /v1/outreach/setup/brands/{id}/billing`;
  - `POST /v1/outreach/setup/topups`, rate limited.
- **The webhook** hands every event to `outreach_billing.webhook`, inside its retry boundary: a failure returns 503 and Stripe retries. A business with no outreach billing is untouched.
- **Billing switches on only once both Stripe price IDs are set.** Until then a new brand changes nothing.
- **The gates:**
  - research (`run`) and cold sending (`reserve_outreach_usage`, inside `if not reply`) refuse a brand awaiting payment;
  - the budget's committed total counts brands that are charged or pending, plus top-ups reserved but not yet confirmed.
- **Two separate flags,** both known metadata keys in `auth`:
  - `outreach_brands_free`: every brand of the business is live with no brand billing. It does **not** change the profit guard's income;
  - `complimentary`: the profit guard counts the business as £0 income (it pays nothing). MSC and New Body, free permanently with every feature, need both.
- **Screens.** On each brand's research card:
  - "Add for £79/month" (or £99);
  - "Waiting for Stripe…";
  - the £10, £25 and £50 top-ups, each paid on Stripe's page;
  - "Stop paying for this brand", with a confirmation.


**Codex review 1 (`audits/OUT-19-F-CODEX-REVIEW-1.md`, 7 × P1, 5 × P2) → reworked around two principles:**
- **Durable operations.** Every brand change and top-up has an identity saved before Stripe is called and reused as Stripe's idempotency key. An outcome Stripe didn't confirm (a timeout, a 5xx) is kept as `uncertain` and checked later, never assumed to have failed. A retry reuses the identity, so it can't charge twice.
- **Stripe is the truth.** `reconcile()` fetches the subscription as Stripe has it now; an event's own copy, which may be old, is never trusted. It runs on every subscription or invoice event and every 15 minutes (`scheduled_check`, alongside the profit check).
- **The findings, one by one:**
  1. Webhooks for businesses without outreach: the lock is the `business_settings` row, and the billing call is inside the webhook's 503 boundary.
  2. Uncertain outcomes are kept and checked, as above.
  3. Each top-up is keyed by its own reservation (in Stripe's metadata), so a payment releases only its own.
  4. 3-D Secure: the off-session attempt is cancelled, and the hosted page keeps the reservation until it is paid or `checkout.session.expired` arrives.
  5. Races: one subscription operation at a time per business (a claim), no change while Stripe has an unpaid update waiting, and quantities set to an absolute number (the brands being paid for), never +1/−1.
  6. Stale events: see "Stripe is the truth".
  7. A top-up is credited only when the payment is the business's own Stripe customer, in pounds, one of the three sizes, for one of its brands; once, by a durable per-payment row.
  - P2s: a stopped brand stops counting in the budget once its paid month ends; an addition whose invoice was never paid goes back to "awaiting payment" after an hour, with a note; billing needs both prices; Stripe returns the owner to the settings tab; the flag mismatch (above).
- **Screens:** the billing card checks every 10 seconds while a payment is being confirmed, and shows why a payment didn't go through.
- **The webhook's order.** Outreach billing runs first, before the handler writes the business row. The owner's billing actions lock `business_settings` and then `businesses`, so the webhook takes them in the same order and holds no row lock while it asks Stripe. Today's raw-SQL reads don't autoflush the business write, so the old order didn't actually deadlock; the new order makes that safe by construction.
- **Tests:**
  - `test_outreach_billing.py` has 53 tests on a stateful fake Stripe. Eight mutations, one per fix, are each caught.
  - `test_outreach_billing_pg.py` runs through the real webhook endpoint on PostgreSQL: an ordinary customer's event is accepted without asking Stripe; a brand goes live; Stripe being down gives a 503 with nothing kept; a top-up is credited once; and the lock order holds while the owner holds the lock.
  - Fixed in passing: that test and PROFIT-1's race test both polled `pg_stat_activity` inside one transaction, which is one snapshot, so they failed now and then when run together. They now take a fresh snapshot each poll: 12 of 12 clean, against 2 failures in 8 before.
- **Backlog (Codex):** revenue reporting from real Stripe amounts (PROFIT-2).

**Codex review 2 (`audits/OUT-19-F-CODEX-REVIEW-2.md`, 6 × P1, 2 × P2) → simplified, by Mike's decision (30 Oct 2026):**
- **One brand, one line.** Each paid brand gets its own Stripe price, made for it (same product and amount as the configured price, idempotent on the addition's id), and its own subscription line. Brands never share a quantity: no brand can take another's paid place, and removing one can't touch another (P1 2).
- **Top-ups on Stripe's page only.** There is no off-session charge and no cancel-then-fallback (P1 5).
  - The page is created under the reservation's key, with every parameter taken from the stored purchase, so re-sending it is the same request. Stripe returns the page it made, if it made one.
  - The reservation stays until Stripe says the page was paid (credited) or expired (released).
  - A creation Stripe never confirmed is re-sent for 30 minutes. It is released only after 4 days, past Stripe's 3 days of webhook retries.
- **One payment check (P1 6).** `_settle_page` is used by both the webhook and the scheduled check. It credits only against a purchase this business reserved, matching:
  - its reservation and page;
  - the business's Stripe customer;
  - the brand;
  - pounds, and the exact amount.
  A paid page with no reservation credits nothing. A mismatch keeps the reservation and logs it for review.
- **Answers applied only if nothing moved (P1 1).** `reconcile` asks Stripe with no lock held, then applies the answer only to records unchanged since they were read (a fingerprint per brand and per purchase).
- **Removal (P1 3 and P1 4).**
  - It asks Stripe for the paid period's end before recording anything; if Stripe can't be reached, nothing changes.
  - It refuses while Stripe holds an unpaid update.
  - An unconfirmed removal is re-sent by the scheduled check as the identical request.
- **Identical requests (P2).** Every key is stored with its exact parameters: the brand's price id, the item id, and the page's stored purchase. The scheduled settle with an hourly key is gone. The fake Stripe now enforces Stripe's rule: the same key with different parameters is refused.
- **Screens (P2):**
  - the billing card refreshes after every answer, including failures;
  - it checks every 10 seconds while a brand payment is pending or being checked, or while a top-up is waiting;
  - it shows each waiting top-up.
- **The flags:** a behavioural income test covers `complimentary` versus `outreach_brands_free` (`test_profit_guard.py`).
- **Tests:**
  - `test_outreach_billing.py`: 68 tests. Ten mutations, one per fix, are each caught.
  - `test_outreach_billing_pg.py`: a paid page through the real webhook endpoint, delivered twice, is credited once.

**Codex review 3 (`audits/OUT-19-F-CODEX-REVIEW-3.md`, 3 × P1, 3 × P2) → fixed in a 4th cycle, authorised by Mike (30 Oct 2026):**
1. **A retry never forgets an addition that may have been charged.** On a retry of an unconfirmed addition, any failure, even a definite refusal of the retry's own read, keeps the first attempt's identity and price. The scheduled check settles it from Stripe's current state.
2. **No change can slip between a removal's read and its deletion.**
   - A removal claims the subscription operation before reading Stripe.
   - An unconfirmed removal is finished by `resend_removals`, run by the scheduled check in its own session. It also claims first, reads Stripe fresh, and never acts while Stripe holds an unpaid update.
   - The webhook no longer sends brand changes to Stripe (and, after review 4, no payment pages either).
3. **Renewal.** If the line renewed into a new paid period before an unconfirmed removal finished, the brand stays live to the end of that period: it was paid for.
- **P2s:**
  - Top-up pages expire 60 minutes after reservation, so a re-send within 30 minutes still meets Stripe's 30-minutes-from-creation rule. The fake now enforces that rule.
  - Pages are card-only, so payments settle at once. `checkout.session.async_payment_failed` releases the reservation as a backstop.
  - An unconfirmed removal is marked as being checked; the screen says so and polls until Stripe confirms.
- **Tests:** `test_outreach_billing.py` has 74 tests. Seven new mutations, one per fix, are each caught.
- **Mike adds the webhook event** `checkout.session.async_payment_failed`.

**Codex review 4 (`audits/OUT-19-F-CODEX-REVIEW-4.md`, 2 × P1, 2 × P2) → fixed. A 5th review is Mike's call.**
1. **Nothing is taken away while a subscription operation is in progress.** While a claim is held, `reconcile` neither abandons a pending addition nor pauses an active brand: Stripe's answer may predate the request that operation is making. This prevents a retry in flight being cleared and the brand charged twice.
2. **A renewal is honoured even while another payment is pending.** The paid period's end is extended first; only the deletion waits.
- **P2s:**
  - Setting up the Stripe client happens inside each claim's cleanup, so a configuration error never leaves the subscription claimed.
  - Only the scheduled check re-sends an unconfirmed page creation (`reconcile(recover=True)`); the webhook only reads from Stripe.
- **Tests:** `test_outreach_billing.py` has 80 tests. Four new mutations, plus the original ordering of the renewal bug, are each caught.

**Codex review 5 (`audits/OUT-19-F-CODEX-REVIEW-5.md`, no P1, 1 × P2) → fixed.**
- **Every addition attempt, first or retry, gets a new number in the brand's fingerprint.** A check whose answer from Stripe predates a retry can never clear it, even when the retry's own answer was lost and left the record otherwise unchanged. The mutation is caught.
- **Also added (Codex's test-quality notes):**
  - an active brand isn't paused by a check while a change is in progress;
  - the renewal test asserts the exact renewed end.
- **Backlog (Codex):**
  - keep an audit record for unknown pages discarded after four days (needs three failures at once);
  - operations that outlive the ten-minute claim;
  - browser coverage of the billing states;
  - revenue reporting from real Stripe amounts (PROFIT-2).
- **Test-mode check before launch (Codex's suggestion):** in Stripe test mode, add a brand, buy one top-up and stop billing. Confirm one credit, and access until the paid end.

### G — Boost eligibility and steps (decision 5)

### H — AI routing and failover (decision 6)

Built in `services/ai_router.py`. Research and Aria's setup drafts go through it.

**Settings (Railway):**
- `AI_PROVIDER_ORDER`: default `openai,xai,anthropic`.
- `AI_MODELS_JSON`: per purpose. Defaults (Mike, 25 Oct 2026, from the providers' pricing pages):
  - research and drafts: **gpt-6.1-sol** ($2/$10 per M: near-top capability at about GPT-4.1's price), then **grok-4.7**, then claude-sonnet-4-5 (price still an estimate). Grok 4.7 ($2/$6, doubling above 200k tokens) is xAI's most capable model. Mike chose it over the cheaper Grok 4.20 after an earlier Grok failed at research on his own platform. `scripts/compare-research-ai.py` puts both through our verification on a real brief;
  - reply sorting: **gpt-6-luna** ($0.10/$0.50), then grok-4.20-0309-non-reasoning. Every reading is recorded in the ledger (chase replies and outreach replies);
  - at most 4 web searches per call.
- `ARIA_DRAFT_MODEL` and `ARIA_RESEARCH_MODEL` still choose OpenAI's model.
- `AI_FAILOVER_COOLDOWN_SECONDS`: default 300.
- Keys: `OPENAI_API_KEY`, `XAI_API_KEY`, `ANTHROPIC_API_KEY`.

**Which provider is used:**
- A provider is used only with its key set and its model priced.
- A provider error hands over to the next, and the failed provider is skipped for the cooldown.
- An invalid answer is not retried elsewhere, so no second provider is charged.

**Costs:**
- Every attempt is recorded in the ledger; a failed attempt at its conservative maximum, marked estimated.
- **Option B (Mike, 25 Oct 2026).**
  - Each search attempt reserves a realistic amount: `RESEARCH_SEARCH_RESERVE_PENCE`, default 75p, several times a typical search's 15–30p. One reserve is taken per provider the search might try, including those cooling down.
  - The theoretical maximum of an agentic search is not reserved: each search can trigger another pass over a million-token context, so reserving it would make a £20 budget unusable.
  - An overrun is recorded, and the brand stops at its next reservation once its budget is used, so a budget can be exceeded by at most one search.
  - Only a cost beyond the theoretical maximum (a bug or a price change) pauses the brand.
  - Failed attempts without reported usage are recorded at the reserve, marked estimated.

**How each provider is reached:**
- Grok through the OpenAI library pointed at `https://api.x.ai/v1`.
- Claude through the Messages API directly, with its web-search tool for research.
- Both need checking with real keys once Mike adds them (a smoke test per provider).

## Order

1. **A** (ledger), then **H** (routing). The ledger makes every later number real; routing protects Mike from a single provider failing.
2. Then **D** and **E**, which are about deliverability and user experience.
3. Then **B, C, F and G**: money. Each gets its own tests, Codex review and click test.
4. Any migration gets a runbook run by Mike.

## Not in OUT-19

- Changing the published plan prices (£69/£129/£269).
- Outreach as a standalone product without Business Hero.
