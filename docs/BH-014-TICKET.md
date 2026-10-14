# BH-014 — Stripe reconciliation (RC1 P0-7)

**Tier:** RED (Stripe, plan enforcement). **Builder:** Codex. **Reviewer:** Claude.
**Tests first, reviewed by Mike before implementation.** Mike asked for this
on 14 Oct 2026 ("let's get codex to complete Stripe reconciliation").

## Why

Stripe webhooks stopped for two months in 2026 and nothing surfaced it
(RC1_SCOPE P0-7). Every billing rule in this app (`subscription_status` →
access, `plan_tier` → features, metering) trusts the webhook. A silent
webhook means a customer who cancelled keeps full access, or a paying
customer gets locked out, and nobody knows.

P0-7's four webhook defects (deletion assigning a tier, tier written without
a price change, non-atomic de-duplication, replay) were fixed in BH-006. Read
`audits/BH-006*` and the `stripe_webhook` handler in `backend/main.py`
before designing. What is left is the **safety net**: a scheduled comparison
of Stripe against `businesses`, which alerts when they disagree.

## What to build

A reconciliation job:

1. **For every business with a `stripe_subscription_id` or
   `stripe_customer_id`,** fetch the subscription from Stripe. Use the
   official `stripe` library already used by the webhook, with the existing
   key configuration.
2. **Compare it with what `businesses` holds:**
   - `subscription_status`;
   - the plan the subscription's price resolves to, compared with
     `plan_tier`, using the SAME price→plan resolver the webhook uses (never a
     second copy);
   - `current_period_end`.
3. **Also detect:**
   - **Webhook silence:** active Stripe subscriptions exist, but no
     `stripe_events` row has arrived for longer than a threshold;
   - **Orphans:** a business points at a subscription Stripe does not know,
     or a live Stripe subscription whose metadata or customer maps to no
     business.
4. **Report and alert:**
   - one structured result per run (counts plus each divergence);
   - an alert when anything diverges.
5. **Run it from the existing scheduler** (`services/briefing_scheduler.py`):
   - off the event loop (`asyncio.to_thread`, as metering does);
   - rate-limit friendly;
   - one Stripe failure never stops the scheduler or the other checks.

## Decisions to propose (Mike decides; give your recommendation for each)

- **D1 — Report only, or auto-correct?**
  - *Recommended:* report only in RC1. A human (Mike) corrects it, and
    corrections go through the existing webhook logic or an admin action.
  - If you recommend auto-correcting any field, say exactly which, and why
    it cannot make things worse.
- **D2 — The alert channel.**
  - There is no system mailer: email in this app goes through a business's
    own connected mailbox (see `services/metering_notify.py`).
  - Propose something that works today. Options include a platform-admin
    WhatsApp alert, an admin-dashboard banner, a log line at ERROR, or a
    combination.
  - Say what is actually deliverable.
- **D3 — Frequency and the silence threshold.**
  - *Suggested:* daily, with the silence threshold at 48 hours.
  - Justify both against how often Stripe actually sends events for a small
    customer base.
- **D4 — Visibility.**
  - Should the last run's result appear in the admin dashboard
    (platform admins only)?
  - If yes, is it a read-only endpoint, and where is the result stored?
  - **Any new table or column is a migration: RED, and needs a runbook.**
    Prefer a design that needs none, unless you can show it is needed.

## Stage 1 — this run: tests first and the design note, then STOP

- Write `docs/BH-014-DESIGN.md` with D1–D4 and your recommendations.
- Write the failing tests: strict xfail on the module's absence, as
  `backend/tests/test_metering.py` and `test_aria_actions.py` did. Fake Stripe
  at its library boundary; nothing touches a real Stripe account, staging or
  production.
- Cover:
  - every divergence kind;
  - "all in agreement" (no alert);
  - webhook silence;
  - a Stripe API failure on one business (the others are still checked; the
    failure is reported);
  - tenant correctness (business A's subscription never compared against
    business B);
  - the scheduler isolation.
- `./check.sh full` green with the new tests xfailed.
- Do **not** implement. Mike reviews the tests and D1–D4 first.

## Rules

- Read AGENTS.md first. It governs.
- Your sandbox writes only inside this worktree: **do not git commit or
  push.** Claude reviews the diff, checks scope, and commits it as
  "Built by Codex".
- Use `.venv/bin/python` (system python3 is 3.9).
- No production SQL and no network.
- Do not modify `stripe_webhook`'s behaviour. If you find a defect in it,
  report it; don't fix it here.
