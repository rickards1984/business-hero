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
