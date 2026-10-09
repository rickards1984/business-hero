# BH-011 — Stage 1 entitlement design

Status: tests/design for Mike's review; **not implementation approval**.
Builder: Codex. Reviewer: Claude Code. Branch: `ticket/BH-011-plan-enforcement`.
Stage 2 waits for BH-010 to merge because both tickets touch `quoting_api.py`.
No runtime source, schema, plan defaults, frontend, billing or production changes.

## North Star §8

This serves the **security and correctness prerequisites**, RC1 P0-1, and P9's
business boundary. It adds no stored/fetched product data, no Aria figures,
and no model-provider client. Existing tenant predicates must remain intact.
No Aria read tool or grounding test is needed for tests/documentation alone.

## Evidence and proposed mechanism

The route inventory is taken from the six imported routers, including their
`admin_router` objects. There are **78 routes**, not just the ticket's 69:
quoting 15; WhatsApp 7 customer/webhook + 2 admin; accounting 13; booking 3;
receptionist 14 customer/public + 7 admin; board meetings 17 including admin.
`test_inventory_covers_every_registered_route` compares that discovery with
an explicit endpoint inventory. New, removed or duplicate handlers require a
policy update; they do not silently inherit expected-failure coverage.

Use `auth.require_feature` for ordinary HTTP dependencies, or
`auth.assert_feature_access` after a trusted business lookup when a JWT
context is inappropriate. Preserve `enforce_access` for method-sensitive
read-only enforcement. Feature access is the plan default plus deliberate
boolean exceptions, subject to subscription status. Do not copy the plan
matrix or use tier ordering to decide whole-feature access.

* `active`, `trialing`, `past_due`: full access to granted features.
* `unpaid`, `canceled`: only the permitted reads/exports below; no AI, writes
  or outbound sends. GET is not sufficient evidence that an endpoint is safe.
* Explicit false overrides a granting plan; explicit true grants a feature
  absent from that plan. Neither overrides a read-only subscription for AI.
* Starter already includes quoting/accounting/email/invoicing. Tests use
  explicit false for features granted by every plan, and real Starter
  defaults for paid features missing from Starter.
* Missing business fails closed (the existing canonical helper returns 404).
  An unknown feature must return 403 even if a same-named metadata flag is
  truthy. The latter is an existing canonical-helper gap, recorded as xfail.

## Per-route mapping

The following is the proposed Stage 2 contract encoded in the tests.
“Allow read” means pass the gate, still subject to feature entitlement and
ownership; it does not promise a record exists. Every other ordinary route
returns 403 when its feature is disabled, before any domain database read,
write or provider operation. Compound mappings require **both** features.

| Method | Route | Feature / EXCEPTION | Read-only behaviour |
|---|---|---|---|
| GET | `/v1/quotes` | quoting | Allow read |
| GET | `/v1/quotes/{quote_id}` | quoting | Allow read |
| POST | `/v1/quotes` | quoting | 403 |
| PUT | `/v1/quotes/{quote_id}` | quoting | 403 |
| DELETE | `/v1/quotes/{quote_id}` | quoting | 403 |
| POST | `/v1/quotes/{quote_id}/send` | quoting | 403 |
| POST | `/v1/quotes/{quote_id}/accept` | quoting | 403 |
| POST | `/v1/quotes/{quote_id}/decline` | quoting | 403 |
| POST | `/v1/quotes/{quote_id}/convert-to-invoice` | quoting + invoicing | 403 |
| POST | `/v1/quotes/{quote_id}/generate-pdf` | quoting; EXCEPTION E — quote export POST | Allow PDF export, no record mutation |
| POST | `/v1/quotes/{quote_id}/send-email` | quoting + email | 403 |
| POST | `/v1/quotes/{quote_id}/send-whatsapp` | quoting + whatsapp | 403 |
| GET | `/v1/quotes/settings/config` | quoting | Allow read |
| PUT | `/v1/quotes/settings/config` | quoting | 403 |
| POST | `/v1/quotes/ai/generate` | quoting | 403 |
| GET | `/v1/whatsapp/config` | whatsapp | 403 |
| PUT | `/v1/whatsapp/config` | whatsapp | 403 |
| POST | `/v1/whatsapp/send-daily-pulse` | whatsapp | 403 |
| POST | `/v1/whatsapp/send-weekly-briefing` | whatsapp | 403 |
| POST | `/v1/whatsapp/send-task-reminder` | whatsapp | 403 |
| GET | `/v1/whatsapp/messages` | whatsapp | 403 |
| POST | `/v1/whatsapp/webhook` | EXCEPTION D — signed webhook → whatsapp | 403 after signature + tenant resolution; no writes/reply |
| GET | `/v1/admin/whatsapp/overview` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| PUT | `/v1/admin/whatsapp/{business_id}/config` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| GET | `/v1/accounting/categories` | accounting | Allow read |
| POST | `/v1/accounting/categories` | accounting | 403 |
| GET | `/v1/accounting/transactions` | accounting | Allow read |
| POST | `/v1/accounting/transactions` | accounting | 403 |
| PATCH | `/v1/accounting/transactions/{transaction_id}` | accounting | 403 |
| DELETE | `/v1/accounting/transactions/{transaction_id}` | accounting | 403 |
| POST | `/v1/accounting/transactions/bulk-delete` | accounting | 403 |
| POST | `/v1/accounting/transactions/bulk-update-category` | accounting | 403 |
| POST | `/v1/accounting/upload/analyze` | accounting | 403 |
| POST | `/v1/accounting/upload/import` | accounting | 403 |
| GET | `/v1/accounting/summary` | accounting | Allow read |
| GET | `/v1/accounting/ai-insights` | accounting | 403 |
| GET | `/v1/accounting/imports` | accounting | Allow read |
| GET | `/v1/booking/calendars` | calendar_booking | 403 |
| GET | `/v1/booking/settings` | calendar_booking | 403 |
| PUT | `/v1/booking/settings` | calendar_booking | 403 |
| GET | `/v1/receptionist/config` | receptionist | 403 |
| PUT | `/v1/receptionist/config` | receptionist | 403 |
| PATCH | `/v1/receptionist/config/toggle` | receptionist | 403 |
| GET | `/v1/receptionist/knowledge-base/categories` | EXCEPTION B — static catalogue | 200; public constants only |
| GET | `/v1/receptionist/knowledge-base` | receptionist | 403 |
| POST | `/v1/receptionist/knowledge-base` | receptionist | 403 |
| PUT | `/v1/receptionist/knowledge-base/{item_id}` | receptionist | 403 |
| DELETE | `/v1/receptionist/knowledge-base/{item_id}` | receptionist | 403 |
| GET | `/v1/receptionist/voices` | EXCEPTION B — static catalogue | 200; public constants only |
| GET | `/v1/receptionist/voices/{voice_id}/preview` | receptionist | 403 |
| GET | `/v1/receptionist/voice-presets` | EXCEPTION B — static catalogue | 200; public constants only |
| POST | `/v1/receptionist/voice-preview` | receptionist | 403 |
| GET | `/v1/receptionist/calls` | receptionist | 403 |
| GET | `/v1/receptionist/stats` | receptionist | 403 |
| GET | `/v1/admin/receptionist/overview` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| PUT | `/v1/admin/receptionist/{business_id}/feature-flag` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| GET | `/v1/admin/receptionist/{business_id}/config` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| PUT | `/v1/admin/receptionist/{business_id}/config` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| PUT | `/v1/admin/receptionist/{business_id}/phone-number` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| GET | `/v1/admin/receptionist/{business_id}/knowledge-base` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| POST | `/v1/admin/receptionist/{business_id}/knowledge-base` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| GET | `/v1/executive-meetings/settings` | board_meetings | 403 |
| PUT | `/v1/executive-meetings/settings` | board_meetings | 403 |
| GET | `/v1/executive-meetings/access-check` | EXCEPTION C — entitlement metadata | 200; has_access/has_advanced false |
| GET | `/v1/executive-meetings/meetings` | board_meetings | 403 |
| GET | `/v1/executive-meetings/action-items` | board_meetings | 403 |
| PUT | `/v1/executive-meetings/action-items/{item_id}` | board_meetings | 403 |
| GET | `/v1/executive-meetings/goals` | board_meetings | 403 |
| PUT | `/v1/executive-meetings/goals/{goal_id}` | board_meetings | 403 |
| GET | `/v1/executive-meetings/admin/overview` | EXCEPTION A — platform admin | Admin only; ordinary owner 403 |
| POST | `/v1/executive-meetings/prep-now` | board_meetings | 403 |
| POST | `/v1/executive-meetings/start-now` | board_meetings | 403 |
| GET | `/v1/executive-meetings/{meeting_id}/prep-data` | board_meetings | 403 |
| POST | `/v1/executive-meetings/{meeting_id}/start` | board_meetings | 403 |
| POST | `/v1/executive-meetings/{meeting_id}/message` | board_meetings | 403 |
| POST | `/v1/executive-meetings/{meeting_id}/end` | board_meetings | 403 |
| GET | `/v1/executive-meetings/{meeting_id}/messages` | board_meetings | 403 |
| POST | `/v1/executive-meetings/{meeting_id}/extract-actions` | board_meetings | 403 |

## Every exception and its reason

**EXCEPTION A — ten admin routes.** The two WhatsApp admin routes, seven
receptionist admin routes and board-meeting `/admin/overview` manage/support
customer accounts. They require platform-admin authority, not the admin's
own customer subscription. An ordinary owner is refused even if their plan
has the feature. Do not place a customer-plan gate around the admin routers.
Tests verify that the registered routes retain the platform-admin dependency;
they substitute its decision and do not re-test JWT/admin-table authentication.

**EXCEPTION B — three public static catalogues.** Receptionist
`GET /knowledge-base/categories`, `/voices`, `/voice-presets` return constants,
not customer data or generated audio. Preserve public 200 responses, including
for callers without a feature. Both actual preview routes are paid
`receptionist` operations and require a gate **before cache lookup**, even when
the audio is cached. They are not `aria_voice` chat sessions.

**EXCEPTION C — board-meeting `GET /access-check`.** Keep the existing 200
metadata response for denied businesses so the UI can explain access. Resolve
`has_access` through canonical `board_meetings` access, including flags and
subscription status; never advertise advanced access when basic access is
false. Preserve response shape and the existing business/beta advanced-setting
restriction, rather than inventing `executive_board_meeting_advanced` as a new
canonical feature. This reports capability; it performs no meeting work.

**EXCEPTION D — `POST /v1/whatsapp/webhook`.** This is an exception to JWT
business-context authentication, **not** a blanket feature exemption. Verify
Twilio's signature, resolve the business from its configured sender mapping,
load that business, then assert `whatsapp` before inbound logging, pending-action
lookup/execution, marking an action executed, or sending even a courtesy reply.
A valid signature does not establish paid entitlement. Tests use real locally
computed Twilio signatures and a synthetic sender mapping. Proposed denial is
403; put the assertion outside the current broad `except Exception` that turns
all failures into 200, or preserve/re-raise HTTPException explicitly. Unknown
sender can retain its current empty 200 without action. See the open question
below about provider acknowledgements. Phone receptionist Twilio callbacks
live outside these six files; no phone-webhook exemption is silently added here.

**EXCEPTION E — quote PDF POST.** `POST /v1/quotes/{quote_id}/generate-pdf`
is a read-only export despite its verb. Keep the exact method/path exception
in `enforce_access`; require `quoting`, but do not introduce a blanket POST
block that removes statutory record access. `GET` quote list/detail/settings
and accounting categories/transactions/summary/import history remain reads
under `READ_ONLY_PERMITTED_FEATURES`. Accounting AI insights is **not** a safe
read: `GET /v1/accounting/ai-insights` needs a read-only refusal in addition to
its `accounting` gate, which by itself permits read-only accounts.

There are **no OAuth callbacks, invoice PDF routes, CSV export routes or
accounting-sync routes in these six routers**. Do not invent exceptions for
nonexistent routes. DECISION 3's quote/invoice CSV/PDF export permission and
accounting-export exclusion still bind their separate owners. Existing OAuth
callback completion exceptions in `auth` remain outside BH-011 Stage 1.

**Compound feature mappings (not exemptions):** quote-to-invoice also requires
`invoicing`; quote email also requires `email`; quote WhatsApp also requires
`whatsapp`. Without these a business could bypass a deliberately disabled
channel via quoting. These are proposals for Mike's review, not changes to
which tier buys which feature.

## Receptionist stopgap: MSC and New Body

`docs/CURRENT_STATE.md` §8 records a manual `receptionist: true` on both
businesses and says 033 STEP 21 is blocked pending deployed verification.
This is repository evidence, **not a fresh observation of production**.
The current `_require_receptionist_flag` already calls `_is_feature_enabled`;
it no longer reads the raw flag with a false default. That explains why the
Step 20d reader fix and removal of the second gate are different tasks.

For an active/trialing/past_due Pro or Business account, folding into the
canonical gate preserves access both with `receptionist: true` and with `{}`.
The tests exercise both forms, including the toggle route. Explicit false
still denies. Stage 1 removes no flags and performs no STEP 21 SQL.

There IS an intended difference for subscription-restricted accounts: the old
helper only resolves the feature; the canonical helper also checks status and
suspension. Read-only customers lose receptionist settings/history/stats GETs;
mutations are already refused by shared context enforcement. They also cannot
use voice previews. Thus it is incorrect to promise no change for the two
founders without knowing their effective access state. This run did not query
it. Turning off/releasing live phone service for unpaid accounts remains a
separate operational concern; this ticket does not prove the phone webhook or
number-release path is protected. Founder billing exceptions do not imply an
entitlement bypass.

## Test approach and limits

`backend/tests/test_plan_enforcement.py` sends requests through each original
FastAPI endpoint and its dependency graph, mounted one route at a time. It
replaces identity/session resolution with synthetic objects and explicitly
runs the real `enforce_access`. The canonical feature checks and legacy gates
are not mocked. Rate limiting is disabled only inside the fixture.

No application lifespan or `main` import is used. A pre-import environment
guard rejects non-SQLite database URLs, following the tenant-isolation test.
Database connections and network connections are blocked. Session/provider
stubs raise an uncaught `BaseException` sentinel at the first domain I/O
boundary; domain operations never execute. A successful denial must be 403
with no boundary attempted. Allowed tests require 2xx or reaching that boundary;
401, 400, 404, 422 and 500 are fixture/test failures, never evidence of passage.
This demonstrates **gate passage**, not successful storage, PDF rendering,
provider response or complete business operation. It is not an end-to-end,
RLS, authentication, cross-tenant or live-provider test.

Expected failures catch only `GateContractMissing` or `LegacyGatePresent`,
with `strict=True`. Unexpected fixture errors cannot become xfails; once an
assertion passes its marker must be removed in Stage 2. Existing receptionist
feature denials, Starter board-meeting denials, read-only mutation refusals,
admin exclusions, public catalogues, and entitled requests run as normal tests.
The inventory test itself is never xfailed. The AST checks require removal of
legacy gate calls across backend runtime code and canonical names at the six
routers' gate calls. These are supporting checks, not substitutes for requests.

Limits to carry into Stage 2 review:

* Individual route mounting does not test `main` registration/order or
  middleware. Existing authentication and tenant tests remain necessary.
* The no-effects proof stops at the first domain I/O boundary; allowed requests
  do not run entire route bodies. The test does not audit every background job,
  service call site, phone webhook or provider in the whole backend. PART D's
  global expensive-call-site audit is broader than this six-router ticket.
* `/access-check` tests cover flags and read-only false responses; preserving
  advanced setting filtering needs focused implementation-stage tests when
  replacing `get_business_tier`. Do not silently alter `_ADVANCED_TIERS`.
* Downgrade history access (PART C) and whether a customer with an explicitly
  disabled `quoting` flag must still export past quotes need a product decision.
  The proposed table preserves the current canonical helper's flag semantics.

## Open questions for Mike before Stage 2

1. Approve the three compound mappings (invoicing/email/WhatsApp from quoting)?
   The proposed tests require both source and destination features.
2. PART C says higher-tier data stays visible after downgrade, while the current
   canonical gate denies the whole feature, including history. Should active
   downgraded accounts retain board-meeting/WhatsApp/receptionist history, and
   should an explicit quoting denial ever block retained quote exports? The
   proposal currently follows the canonical gate; a retention exception needs
   explicit route definitions rather than a generic GET bypass.
3. For a valid signed WhatsApp webhook whose business is denied, retain the
   ticket's strict 403 contract (encoded here), or acknowledge with empty 200
   and no actions/writes/replies to suppress Twilio retries? Both must enforce
   the same no-effects rule; the response is a provider-facing product choice.

## Verification and behaviour review

Run with `/Users/michaelrickards/dev/business-hero-2/.venv/bin/python`:

```bash
.venv/bin/python -m pytest backend/tests/test_plan_enforcement.py -q
./check.sh
```

The worktree's existing `.venv` points to that interpreter. Frontend dependencies
were absent, so an ignored local `node_modules` symlink reuses the existing
installation; npm runs offline. No dependency installation is necessary.
Completion counts/output are recorded in `BH-011-TICKET.md`.

Mike has no changed screen to click in Stage 1: review the plain-English test
contract and questions above. After separately approved implementation, the
behaviour smoke test is to open Quotes/Accounting on Starter (available), try
WhatsApp/Booking/Board Meeting on Starter (refused at API), then repeat on a
granted plan. For unpaid/canceled, open/download an existing quote (available)
and try edits, sends, previews and accounting AI insights (refused). A browser
smoke test cannot replace the API tests. No production smoke test was run here.
