# BH-014 — Stage 1 design for review

14 October 2026. Builder: Codex. Reviewer: Claude. Branch:
`ticket/BH-014-stripe-reconciliation`. **Proposed; D1–D4 require Mike's
review before implementation.** This run adds a design and tests only.
North Star: correctness and stability prerequisites, P8 (honest reporting)
and P9 (tenant isolation). No model calls or new Aria-facing figures.

## Current evidence and scope

- `backend/main.py:999` contains the BH-006 webhook; `:1095` and `:1114`
  use `_resolve_plan_from_price`, defined at `:2801`. `_plan_item` at
  `:2785` selects the known plan item; `_resolve_current_period_end` at
  `:2727` handles item-level periods and legacy subscription-level periods.
  Reconciliation must use those same functions, not a second price map.
- The webhook deliberately preserves purchased tier on cancellation and
  status-only updates. An admin exception can therefore cause a legitimate
  price/tier mismatch. A reconciliation finding is evidence to investigate,
  not authority to overwrite it.
- `backend/models.py:185` defines StripeEvent; its `created_at` is local
  receipt time. Use `MAX(stripe_events.created_at)` for silence, not the
  event payload's creation time or `businesses.last_stripe_event_at`.
- `backend/services/briefing_scheduler.py:57` demonstrates worker-thread
  reconciliation; `:95` contains independently guarded scheduler jobs.
- `backend/app/billing/config.py:26` is the existing key configuration.
  The job must initialise the SDK with this configuration even if no checkout
  request has run since process startup.
- `backend/services/metering_notify.py` uses a tenant's mailbox and optional
  WhatsApp; this is not a platform operations mailer.
- `audits/BH-006-PROD-RUNBOOK.md` documents entitlement preservation,
  the production uniqueness verification requirement and unresolved issues.
  No live state was inspected or inferred from migration files.

Scope after approval: read-only Stripe reconciliation service and scheduler
hook, structured results and operational logging. No billing writes, webhook
behaviour changes, dependencies, schema changes, outbound messages or deploy.
This is RC1 P0-7 work; Stripe implementation remains RED. Stage 1 has explicit
authorisation only for the design and tests.

## D1 — Report only (recommended)

Report discrepancies; never update businesses, Stripe subscriptions or event
rows. Keep admin suspension, feature flags, purchased tier and payment state
untouched. Corrections need a separately authorised existing webhook/admin
path. Status, plan and period comparisons are independent; one business can
produce several findings. Report unknown price/missing or invalid period as
unresolved rather than guessing. Normalize naive DB timestamps as UTC and
compare UTC instants at seconds precision, using the webhook period resolver.

## D2 — Structured ERROR log (recommended for RC1)

Emit one JSON-safe run summary, INFO when fully in agreement, ERROR when any
finding or fetch failure occurs. Include timestamp, completeness, counts,
business/subscription identifiers and field differences; exclude full Stripe
payloads, credentials, contact data and raw exception messages. An ERROR log
is deliverable with current infrastructure, but it does not guarantee Mike
receives a notification. Mike must inspect application logs operationally.
Do not claim an email/WhatsApp delivery path exists for platform alerts.
A proactive platform WhatsApp channel needs an explicitly configured admin
recipient, approved template and outbound authority; defer it. Failure of
logging/alert handling must not terminate other scheduler jobs.

## D3 — Daily run; 48-hour silence warning (recommended, with caveat)

Run on the first eligible scheduler tick after its existing startup sleep,
then at most once per 24 hours. Use UTC elapsed time, not local calendar
midnight. Record attempt time to avoid retrying every minute after failure.
Daily comparison bounds detection delay to roughly a day while keeping API
traffic modest. No assumption that Stripe sends a daily heartbeat: recurring
billing can have long quiet intervals in a small customer base. Thus 48 hours
is a conservative **possible silence warning**, not proof of a dead webhook.
Its expected noise must be reviewed after observing actual event cadence.
No network research or live event inspection was performed in Stage 1.

Warn only if at least one fetched Stripe subscription is `active` and the
latest local receipt is strictly older than 48 hours. Exactly 48 hours is
not overdue. No event rows plus an active subscription also warns. No active
subscriptions means no silence finding. A partial inventory is never a clean
bill of health: report its error and `complete=false`; a confirmed active
subscription can still justify a warning. A recent unrelated event is only
a global liveness signal, not evidence that every tenant is synchronized.

## D4 — Logs only initially; defer dashboard (recommended)

Do not introduce an endpoint, table, column or dashboard banner in RC1's first
iteration. The returned result is transient; the operational log is the run
record, subject to hosting retention (not verified here). This avoids a
misleading process-local “last successful run” after restart and requires no
migration. There is no last-run dashboard display under this recommendation.

If Mike chooses a dashboard instead, propose a separate read-only endpoint
gated by `get_platform_admin_context` (as in `admin_business_api.py:223`),
with an in-memory immutable last-attempt result under the existing single
replica constraint. Show “not run since restart”, age, incompleteness and
errors, never an implicit green. This would add access-control tests and,
under North Star §8, a tenant-scoped Aria read tool exposing only that
business's findings, never the global inventory. Do not implement this
alternative or new storage without revising the reviewed scope.

## Proposed service contract and identity rules

`services.stripe_reconciliation.run(session, *, now, silence_threshold)` is
synchronous. It returns a JSON-safe dict with `complete`, `counts`,
`divergences`, `errors`, and run timestamps. Counts are businesses attempted,
distinct subscriptions fetched, findings and errors; a subscription seen by
both retrieval and inventory is counted once. Each finding carries `kind`,
nullable `business_id`, nullable `subscription_id`, and relevant local/remote
values. Errors carry scope, nullable business ID and a safe code. `alert(result)`
is the operational ERROR logging boundary, called once when findings/errors
exist. Tests replace it with a recorder.

1. Read every business with either Stripe identifier, including inactive
   businesses. Retrieve explicit subscription IDs. For customer-only rows,
   list subscriptions with `status='all'` and paginate. Zero subscriptions
   means `missing_subscription`; multiple viable matches mean
   `identity_conflict`, not an arbitrary first choice.
2. Also paginate the account inventory to find live subscriptions absent
   locally. For this purpose nonterminal statuses (including trialing,
   past_due, unpaid, incomplete and paused) remain relevant; canceled and
   incomplete_expired are terminal. Match subscription ID, customer and
   metadata business ID against local rows. Missing optional metadata alone
   is not an orphan if customer mapping is unique. Conflicting mappings,
   duplicate IDs and ambiguous customers are identity conflicts. A stale
   explicit metadata ID is evidence to report even if the customer maps.
3. Never compare business A's fields to B's subscription. Resolve identity
   before comparing fields; on conflict report and skip that comparison.
   A live subscription with no business mapping is `orphan_subscription`.
   An explicitly requested subscription returning resource_missing is
   `missing_subscription`; authentication, rate limit or transport errors
   are fetch errors, never proof of an orphan.
4. Reuse main's resolver functions at call time (lazy import inside the
   worker avoids importing the application during module initialization).
   Extracting shared helpers could be considered later with BH-006 tests,
   but is not needed for this proposal and is not authorised here.
5. Fetch sequentially, paginate with SDK iterators, bounded request timeouts
   and bounded SDK retries/backoff for transient failures. No unbounded
   retry loop. A per-business failure must not prevent subsequent businesses;
   inventory pagination failure marks completeness false. Scan failures do
   not manufacture missing subscriptions from an incomplete inventory.

The scheduler's proposed `_reconcile_stripe_if_due` opens and closes its DB
session **inside** `asyncio.to_thread`. The loop guards that hook independently
so failures preserve metering, briefings, meeting prep and the next tick.
Rate limits and request timeouts still require implementation-stage boundary
tests; Stage 1 does not establish a production runtime bound.

## Acceptance tests and verification

`backend/tests/test_stripe_reconciliation.py` specifies field divergence,
unknown price/period, agreement/no alert, silence boundaries and empty history,
both orphan directions, customer-only records, API failure continuation,
identity conflicts, incomplete inventory, and scheduler worker/due/isolation
behaviour. Every service invocation snapshots businesses to assert no writes
and checks counts, JSON serialization and alert/no-alert behaviour.

The fixtures use an isolated SQLite database and fake the official Stripe
Subscription library methods. The SDK HTTP request path fails closed. No
staging, production or real Stripe calls. SQLite proves comparison logic,
not PostgreSQL semantics. No frontend behaviour changes: Mike has nothing
new to click in the product for Stage 1; review this decision note and the
named tests before authorising implementation.

Strict xfail permits only the custom exception raised when
`services.stripe_reconciliation` is absent. Once present, import/runtime and
assertion failures are real failures, and passing tests are strict XPASS
failures until the marker is removed. Xfails prove the reviewed contract is
pending, not that reconciliation works. Required commands:
`.venv/bin/python -m pytest backend/tests/test_stripe_reconciliation.py -q`
and `./check.sh full`. Completion counts are recorded below after execution.

Completion evidence (14 October 2026): targeted suite **24 xfailed**;
`./check.sh full` exit 0: **5 passed, 0 failed, 1 skipped** (optional eslint).
Pytest: **1733 passed, 33 skipped, 24 xfailed, 220 subtests passed**, 1243
warnings. All five preflight traps passed. No implementation, commit or push.

## Mike's decisions — 14 October 2026

"I agree on D1 and D3 and your suggestion for D2 and D4, as long as it keeps
it sleek and looking good within the UI."

- **D1 — report only.** Accepted.
- **D3 — daily run, with a 48-hour "possible silence" warning.** Accepted.
- **D2 + D4 — Claude's counter-proposal, accepted.** The alert is BOTH:
  - the structured ERROR log, as designed; AND
  - a **platform-admin dashboard banner** showing the last run.
  The banner shows:
  - the last run's result and its age;
  - "not run since restart" when that is true;
  - an incomplete run;
  - each divergence.
  It is never an implicit green.
  - Storage: an in-memory last result (a single replica; no schema change).
  - The endpoint is read-only and gated by `get_platform_admin_context`.
  - It must look sleek and consistent with the admin UI (Mike).
  - No Aria read tool: this is platform-operations data across tenants, not
    a business's own data. North Star §8 applies to business data.
  - Later: a proactive WhatsApp alert to the platform admin, which needs an
    approved template and a configured recipient. Backlogged.

## Stage 2 implementation decisions — Codex, 14 October 2026

Mike's decisions above supersede the original logs-only recommendation.
The implementation serves correctness/stability and P8/P9. Platform operations
results remain in memory; no business-data storage or Aria tool is added.

- GET `/v1/admin/stripe-reconciliation` uses `get_platform_admin_context`
  and `Cache-Control: no-store`. Reads never start a Stripe scan.
- A completed clean result becomes stale after 24 hours; incomplete results
  and errors always take precedence over healthy. The banner polls every
  minute and labels failed loads as unavailable, retaining explicitly labelled
  last-loaded findings. Findings are visible without opening a disclosure.
- Stripe 15.6.1 resources are converted with `to_dict()` before comparison,
  matching the existing webhook boundary. No webhook behaviour changes.
- Sequential SDK calls carry the configured API key and two network retries.
  The installed SDK default client's bounded 80-second timeout is checked by
  a local construction-only test. This bounds individual request attempts,
  not the duration of an inventory of arbitrary size.
- The Stage 1 fixture installs a fake default HTTP client whose sync/async and
  streaming request methods raise. An unrelated Customer retrieval proves the
  SDK reaches that guard. Apart from this fixture statement and removal of
  the Stage 1 xfail marker, Stage 1 tests are unchanged.
- Scheduler session failures publish an incomplete attempt; logging failures
  cannot prevent dashboard publication. Last results are defensive copies.

Manual behaviour check after a separately authorised deployment: open the
platform-admin dashboard. Check the reconciliation banner above Businesses
in light/dark themes and a narrow viewport. On restart it must say “Not run
since restart”; after a run it must show time/age and all findings. A failed
or partial run must never show success. No browser visual or live Stripe
verification was performed in this offline worktree.
