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

### C — The owner's monthly budget
- A single £ figure for add-on brands and top-ups. Aria suggests a realistic amount from the brands, inboxes and warm-up stages. Nothing is charged beyond it.

### D — Research sized to sending capacity (decision 1)

### E — Replies outside the cold cap, with the over-ceiling choices (decision 2)

### F — Stripe: extra brands as subscription items, top-ups and boosts as one-off payments (decisions 3–4)
- Entitlement checks follow the existing webhook rules (BH-006).

### G — Boost eligibility and steps (decision 5)

### H — AI routing and failover (decision 6)

Built in `services/ai_router.py`. Research and Aria's setup drafts go through it.

**Settings (Railway):**
- `AI_PROVIDER_ORDER`: default `openai,xai,anthropic`.
- `AI_MODELS_JSON`: per purpose. Defaults (Mike, 25 Oct 2026, from the providers' pricing pages):
  - research and drafts: **gpt-6.1-sol** ($2/$10 per M: near-top capability at about GPT-4.1's price), then **grok-4.7**, then claude-sonnet-4-5 (price still an estimate). Grok 4.7 ($2/$6, doubling above 200k tokens) is xAI's most capable model. Mike chose it over the cheaper Grok 4.20 after an earlier Grok failed at research on his own platform. `scripts/compare-research-models.py` puts both through our verification on a real brief;
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
