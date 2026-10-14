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

## Stage 1 completion — Codex, 14 October 2026

Design: `docs/BH-014-DESIGN.md`; proposed decisions D1–D4 await Mike.
Tests: `backend/tests/test_stripe_reconciliation.py`, 17 test functions / 24
cases, strict xfail exclusively on the reconciliation module's absence.
`.venv/bin/python -m pytest backend/tests/test_stripe_reconciliation.py -q`:
24 xfailed. `./check.sh full`: exit 0; 5 passed, 0 failed, 1 skipped
(optional eslint); pytest 1733 passed, 33 skipped, 24 xfailed, 220 subtests
passed, 1243 warnings; all five preflight traps passed.
Status: Stage 1 ready for Claude/Mike review; implementation not started.
No product click test exists at this stage. Changes left uncommitted and
unpushed as instructed.

## Stage 2 completion — Codex, 14 October 2026

**Status:** ready for Claude review; uncommitted and unpushed.
**Authority:** Mike approved D1/D3 and the log + admin-banner alternative in
`BH-014-DESIGN.md`; Claude approved correcting the single Stage 1 fixture
statement to install a real fail-closed SDK default HTTP client. The xfail
marker is removed; all Stage 1 test assertions remain unchanged.
**North Star:** correctness/stability prerequisites, P8 and P9.

Implemented read-only reconciliation, daily scheduler worker, process-local
last-attempt snapshot, admin-gated GET and MUI dashboard banner. No migration,
webhook behaviour change, billing correction, production action or deployment.
Implementation decisions and manual behaviour checks are recorded at the end
of `BH-014-DESIGN.md`. Internal read-only review found no blocking defect;
Claude remains the designated independent reviewer.

Verification using this worktree's `.venv`:
- Targeted reconciliation suites: **37 passed**, 65 warnings, no xfails.
- `./check.sh full`: exit 0; **5 passed, 0 failed, 1 skipped** (optional eslint).
- Full pytest: **1770 passed, 33 skipped, 220 subtests passed**, 1305 warnings.
- All five preflight traps passed; frontend typecheck, py_compile and Ruff passed.
- `git -c core.whitespace=cr-at-eol diff --check`: clean (scheduler retains
  its existing CRLF convention).

New Stage 2 tests in `backend/tests/test_stripe_reconciliation_admin.py`:
- `test_normal_business_user_cannot_read_last_run`
- `test_admin_sees_not_run_since_restart`
- `test_last_result_has_age_completeness_and_each_divergence`
- `test_incomplete_or_errored_result_is_never_healthy` (two cases)
- `test_clean_result_becomes_stale_and_snapshot_is_defensive`
- `test_scheduler_session_failure_replaces_previous_green`
- `test_unplanned_sdk_request_is_refused`
- `test_requests_use_configured_key_and_bounded_retries`
- `test_partial_inventory_keeps_findings_and_reports_failure`
- `test_customer_ambiguity_never_compares_arbitrary_subscription`
- `test_logging_failure_preserves_last_attempt`
- `test_anonymous_user_cannot_read_last_run`

Mike's click check: open the platform-admin dashboard and inspect the Stripe
reconciliation banner above Businesses, including narrow-screen and dark-mode
layout. Check restart, incomplete, divergence and age displays against the
run result. Automated checks do not verify rendered appearance or real Stripe
behaviour; neither was exercised in this offline task.

## Claude review fixes — Codex, 14 October 2026

Authority: Mike requested the P2 scheduler isolation and P3 business-name fixes.
North Star: correctness and stability prerequisites. Scope remains Stage 2.

- P2: retained background reconciliation task; running tasks skip due ticks
  without advancing the daily timestamp. Existing daily due-check is unchanged.
- P3: business names come from the existing businesses query and accompany
  findings/errors; the banner shows the name with ID fallback. Unmapped or
  run-wide findings have no business name. No Stripe customer reads added.
- Tests first: six new regression cases failed before implementation.
- Added `test_slow_stripe_run_does_not_delay_next_scheduler_job`,
  `test_due_tick_skips_running_stripe_reconciliation`,
  `test_findings_carry_database_business_name` (three cases), and
  `test_business_errors_carry_database_business_name`.
- Existing scheduler tests now wait explicitly for the background task;
  business fixtures include the name column.
- Targeted suites: 43 passed. `./check.sh full`: exit 0, 5 passed,
  0 failed, 1 optional eslint skip. Full pytest: 1776 passed, 33 skipped,
  220 subtests passed. All five preflight traps passed.
- Manual click check: platform-admin dashboard → Stripe reconciliation banner;
  confirm named businesses display their name, missing names fall back to ID,
  and narrow-screen/dark-mode appearance remains readable. Rendered appearance
  and real Stripe behaviour were not exercised by automated checks.

Uncommitted and unpushed; ready for Claude's re-review.
