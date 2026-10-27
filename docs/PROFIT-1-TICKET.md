# PROFIT-1 — Never spend more running Business Hero than comes in

**Tier:** RED (money: a platform-wide kill switch). **Builder:** Claude. **Reviewer:** Codex. **Tests first.**
**Decision:** Mike, 27 Oct 2026, approving OUT-19 B + C: "as long as we are always looking at a net profit for all transactions, from subscriptions to ad-hoc top-ups, with the alarm and 'kill switch' ensuring we don't lose money, as in, spend more on running Business Hero than the money coming in." He agreed the proposal below the same day, with these defaults: alarm at 40% of the month's income, kill switch at 80%, an email plus an admin banner.

## Why
Today the cost ledger (OUT-19 A) and its alarm and kill switch see **outreach AI only**:
- Aria chat, briefings, executive meetings, quoting, email drafting, support and call summaries all call OpenAI unrecorded.
- Voice is metered in minutes, not pounds.
- The alarm only writes to the server log.

## What gets built

1. **Every AI call is recorded,** platform-wide. A single hook on the OpenAI SDK records each text call's cost in the ledger: the business when known, otherwise a platform row, and its purpose. Calls already recorded by `ai_router` (outreach) are not counted twice.
   - A model without a price is recorded at a conservative default and marked estimated, never as free.
   - Realtime voice is costed per minute instead (2).
2. **Voice in pounds.** Receptionist and Aria voice minutes, from the existing meters, × `VOICE_COST_PENCE_PER_MINUTE`.
   - The default is **16p**: the pricing model's planning rate of $0.20 a minute, with Twilio folded in (audits/PRICING-MODEL.md §2).
3. **Fixed costs.** Hosting and services (Railway, Vercel, Supabase and others) are set by Mike as one monthly figure, `PLATFORM_FIXED_COSTS_PENCE`, counted in full from the 1st.
4. **Income, as monthly recurring revenue.** The plan price of every business whose subscription is `active`: Starter £69, Pro £129, Business £269.
   - Plus paid top-ups this month, once part F exists. Projected brand charges are not counted until part F bills them.
   - Recurring revenue, not payments received so far this month: a customer billed on the 28th must not make the 2nd look like a loss.
   - **Before launch**, when there are no paying customers, `PROFIT_TRIAL_BUDGET_PENCE` stands in for income. With neither, only the existing absolute `AI_MONTHLY_KILL_PENCE` applies, and the admin panel says so.
5. **The guard.** It compares this month's running costs (1 + 2 + 3) with income (4):
   - **Alarm at 40%:** an email to Mike, plus a red banner in the admin panel. Sent once per month per threshold, after the transaction commits.
   - **Kill switch at 80%: non-essential AI pauses,** with a plain message: outreach research, Aria's drafting, briefings and executive meetings.
   - It **never** stops live receptionist calls, reply sorting, unsubscribes or the owner's own chat. Those would harm customers. The pause lifts on the 1st, or when income rises or Mike raises the thresholds.
   - Both thresholds are set by `PROFIT_ALARM_PERCENT` / `PROFIT_KILL_PERCENT`, with no deploy.
6. **Per business:** the admin economics panel flags any business whose costs this month exceed what it pays.
7. **Alarm delivery:** the email is sent from the mailbox Mike names (`PROFIT_ALERT_FROM_ACCOUNT`, a connected email account id) to `PROFIT_ALERT_TO`. With neither set, the banner alone shows it, and the admin panel says email alerts aren't set up.

## Decisions for Mike (defaults proposed)
- **Voice cost:** 16p a minute.
- **Fixed costs:** the monthly total of the hosting and service bills, in pence.
- **Trial budget:** the stand-in income figure for the pre-launch month with three trial businesses. Proposed: **£100**.
- **Alert mailbox:** which connected mailbox sends the alarm (proposed: New Body's), and to which address.

## Not in PROFIT-1
- Changing plan prices: the pre-launch pricing review is a separate task.
- Stripe billing for outreach brands and top-ups (OUT-19 F).

## Codex review 1 (`audits/PROFIT-1-CODEX-REVIEW-1.md`, 6 × P1) → fixed
1. **Migration 039, `platform_meters`.** Costs no business owns, and the once-a-month alert markers, live in this new backend-only table: client access is removed and row-level security is on. `usage_meters` is never given a fake business id. **Mike runs `audits/039-PROD-RUNBOOK.md` before merging.** Until then the guard is safe, but it can't mark or send alerts, and it logs that.
2. **The SDK hook works on async calls.** It handles a `create` that returns an awaitable (the async client). The tests drive the real OpenAI SDK with a mocked transport, and wrapping is idempotent.
3. **Non-essential features are gated, not only recorded:**
   - email drafting and the inbox briefing fall back to their plain versions. They're gated at the SDK hook itself: the email router labels each call (`attributed(..., "draft" / "briefing")`), and the hook refuses a non-essential labelled call before it reaches the provider (`Paused`). The drafting code already falls back on any AI failure;
   - quote drafting is paused with a message. Its direct HTTP call is now recorded too, with images estimated at ~1,105 tokens each;
   - inbox sorting is recorded but never stopped.
   - Text-to-speech is recorded per character, as voice: essential.
4. **Voice overage minutes count.**
5. **`permits()` is `ai_costs.allowed`:** the absolute limit and the guard. **Essential work bypasses both** (the older absolute limit used to stop reply sorting too).
6. **Router and research calls are marked `accounted()`,** so the hook never records them a second time.
- **Also fixed:**
  - A call without reported usage is charged at its request's maximum; a call that raised is recorded at that maximum, as estimated (it may have been billed).
  - A failed savepoint drops the alerts it queued.
  - A scheduled check every 15 minutes notices voice or fixed costs crossing a threshold.
  - Attribution is scoped to each call, with business ids for chat, briefings, meetings, drafting and quotes.
  - The admin panel refreshes every minute.
- **Limits, stated plainly:**
  - Income is monthly recurring revenue, or the trial budget before launch. Essential work is exempt from the kill switch.
  - So the guard pauses non-essential AI once costs reach a set share of income. Essential spending (live calls, reply sorting, unsubscribes, owner chat) can continue past it. It does not prove a profit on every single transaction.
  - Full fixed costs can use up a small trial budget on day one: set the trial budget above them.

## Codex review 2 (`audits/PROFIT-1-CODEX-REVIEW-2.md`, 1 × P1) → fixed (cycle 3 is next, the last)
- **Every named AI feature is labelled.** Assistant email drafting is `draft` and support drafting is `support_draft`, both non-essential and refused at the SDK at the kill switch; their code falls back to a message. Receptionist call summaries are `receptionist`: essential and never refused.
- **The scheduled check takes the ledger's advisory lock,** so it and a cost being recorded never both send one threshold's alert. A deterministic PostgreSQL test fails without the lock.
- **Estimates count every billable part of a request:** messages, tools, instructions and response format. With no output limit set, they use the model's own maximum output (128,000 when unknown).
- **Migration 039 is constrained.** `period` must be a real month and `value` can't be negative. Tests on PostgreSQL show the table is backend-only and that its constraints and rollback work.
- **The runbook adds a staging rehearsal** before production. Mike runs it.

## Codex review 3 (`audits/PROFIT-1-CODEX-REVIEW-3.md`, the third cycle, 2 × P1) → fixed. A further review is Mike's call.
- **Quote drafting in Aria's chat is gated and recorded.** It is a direct HTTP call; tested behaviourally.
- **Receptionist voice previews are paused** at the kill switch. Live calls are unaffected.
- **Call summaries are non-essential (`call_summary`).** A summary of a call that has already ended is skipped at the kill switch, returning its existing `None`. The live call is what's essential.
- **A customer's support chat is labelled `chat`:** essential and recorded.
- **The race test is synchronised on PostgreSQL itself.** It waits until the scheduled check is blocked behind the writer (`pg_blocking_pids`) and asserts the check completed. It fails three times out of three without the lock.
- **The runbook names the project for each environment** and checks the actual constraint definitions, not only a column count. The staging rehearsal is Mike's step; its evidence is recorded after.
- **Backlog:**
  - `research_compare` is an admin script whose billed searches aren't persisted;
  - per-business top-ups (part F);
  - alert-delivery visibility.
