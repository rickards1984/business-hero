## TICKET OUT-4

**Outcome** Owners and Aria can read the current business's outreach records through the same bounded, redacted, feature-gated projections, without researching, proposing or sending anything.

**Current evidence** `docs/OUT-1-DESIGN.md` §11 assigns OUT-4 scoped reads, two-tenant/grounding tests and no migration. `docs/OUT-2-CONTRACTS.md` §5 and F01/F18 require tenant predicates and safe backend projections; its final AUTO agreement and Claude review defer knowledge to OUT-7, imports to OUT-5 and integrations/provider usage to OUT-10. `backend/migrations/037_outreach_core.sql` creates the 17 core tables, including backend-only messages/settings/mailboxes/sequence steps, but no knowledge table. `backend/assistant_tools.py:33` registers `TOOL_DEFINITIONS`; `:564` dispatches with a separately supplied business ID. Neither contains outreach reads in this checkout. `backend/auth.py:515` already names outreach, `:540` grants Business, `:714` refuses read-only outreach, and `:771` defines `require_feature`. `backend/onboarding_api.py:220` explicitly rejects `plan_definitions.features` as an entitlement source. `backend/tests/test_home_summary.py:test_every_invoice_counts_not_just_the_first_fifty` supplies the seeded-total precedent. These are checkout facts, not a live schema audit.

**Scope** Stage A only: this packet and `backend/tests/test_outreach_read.py`. Propose the fourteen GET routes/tool pairs below and executable acceptance tests. Stage B, after review/approval, implements one read module and registers its router/tools; the exact proposed module seam is below. No implementation in Stage A.

**Non-goals** No write endpoints, models/create_all registration, migration, RLS/grant/auth policy changes, billing changes, model client, research/provider call, import, approval, scheduler, sync, outbound message, UI, commit or push. No network or `~/.openclaw` access. No new direct model client: Claude confirmed no shared router; reads need no model at all. No claim to implement the entire OUT-2 future read catalogue against absent tables.

**Dependencies** OUT-3/037 contract and its separately approved production runbook; Mike reports staging rehearsal and pending production application, not verified here. OUT-2 owner agreement and independent review bind this work. OUT-12 owns additional commercial entitlement paths; it does not block tests/current Business reads, but blocks selling add-on/standalone access. OUT-7 owns actual knowledge storage/read expansion. OUT-5/10/6/11/13 own the explicit deferred projections below. Stage B needs Claude's independent review and Mike's approval of this AMBER plan; any auth/entitlement/schema deviation gets separate RED approval.

**Affected systems** Backend HTTP routes, Aria read tools and tests; no frontend, DB schema or third-party changes.

**Security & data risk** AMBER scoped read integration; security and tenant-isolation prerequisites P9 apply. Reuse existing auth policy without changing it. Plan enforcement/product lifecycle changes are RED and split into OUT-12. SQLite does not prove Postgres RLS, grants or constraints; OUT-3's independent Postgres evidence remains required.

**Acceptance criteria**

1. Exactly the fourteen route/tool pairs below. Every route resolves business from `get_user_business_context`; every tool uses the trusted dispatcher business argument, never a model argument. Scope every SQL query, subquery and join by that business. Reject extra arguments (including `business_id`) with 422. No cross-tenant lookup followed by filtering in Python.
2. Missing/foreign prospect, campaign or mailbox IDs return identical 404 not-found responses; nested collection reads verify their parent before counting children. Every API/tool has A/B positive controls and access-denial tests. IDs that are only returned citations do not become lookup capabilities.
3. HTTP uses `require_feature('outreach')` with `retained_history=False`; shared projection execution also calls canonical `assert_feature_access` on the current business. Tools enforce outreach independently of the outer Aria chat/voice gate. No cached grant or boolean supplied by the model. Business with ordinary full access succeeds; Starter/Pro without an exception, explicit denial, unpaid/canceled and suspended accounts fail 403. `past_due` remains full. No platform-admin cross-tenant endpoint or tenant-gate exemption is introduced.
4. Exact allowlists below, no whole-row serialization; no ciphertext, access/refresh tokens, API keys, suppression/token digests, authority snapshots, raw provider payloads, recipient arrays or message bodies. Unknown health/eligibility remains unknown/blocked, never inferred from a high score. Nothing sends, calls a model, creates an action or writes to any table.
5. Collections default `limit=20, offset=0`; integer limit 1–50, offset 0–10000; reject out-of-range values (do not silently clamp). Stable `created_at DESC, id ASC` order, except sequence `ordinal ASC, id ASC`; current sequence version only. `total` counts all tenant/filter-matching rows before pagination. No unbounded child arrays. Default and requested pagination have the same semantics in API/tools.
6. Grounding counts actual seeded rows (including more than one page), isolates tenants, distinguishes unknown/imported/live accepted outcomes and excludes machine/bounce/self replies from human replies. P2/P8: no revenue, confirmed-meeting claim or inferred won status. Empty collections have zero totals and a message containing “none”; absent settings produce `item=null`, not invented configured defaults. Knowledge returns a truthful deferred empty state.
7. Responses carry data quality and source record IDs; summary source paths resolve through the same gate and tenant context. Expired evidence does not expose its excerpt/fact value; expired prospect retention hides personal/company contact fields. OUT-13 still owns erasure/retention enforcement across storage, backups and other consumers. This read-time minimization is not proof of deletion.
8. Tests strict-xfail only on the precise absence of `backend/outreach_read.py`. Once it exists, imports, assertions, missing registration and dependency errors fail normally; passing tests XPASS strictly until the Stage B builder removes the marker. Nothing is skipped on a broad ImportError.

**Required tests** `backend/tests/test_outreach_read.py`: every surface via real FastAPI router and existing Aria dispatcher; both tenant directions; guessed/nonexistent IDs; real canonical feature resolver with synthetic business objects; DECISION 3 status matrix; allowlist/secret sentinels; SQL-count grounding and >50 rows; empty/deferred knowledge; pagination; mailbox filter; tool registration/schema; SELECT-only/no-dispatch; expiry/text bounds and current sequence version. Every test docstring identifies its rule. The requested `backend/tests/test_auto_chase.py` does not exist on this branch; use the available `test_aria_actions.py` GateSession/SQLite and precise missing-module precedent. No tests are copied from another worktree.

**Verification** Stage A: `PYTHONDONTWRITEBYTECODE=1 ./check.sh`, targeted `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_outreach_read.py -q`, `git diff --check`. Stage B must pass these tests without xfail and run `./check.sh full` before any later authorised feature-branch push. No push in this assignment.

**Likely files** Stage A exactly this file and the test file. Stage B proposed `backend/outreach_read.py`, registration in `backend/assistant_tools.py` and `backend/main.py`, and these tests; sequence main.py ownership with Claude before editing that shared file. No SQLModel tables.

**Builder** Codex.

**Reviewer** Claude Code, independent of builder; Mike reviews product/access choices and approves Stage B, not implementation correctness.

**Branch** `ticket/OUT-4-outreach-read`, isolated worktree `/Users/michaelrickards/dev/bh2-OUT-4`, based on OUT-3. Initial working tree clean.

**Budget band** L (1–2 days) for complete OUT-4; Stage A is packet/tests only.

**Max repair cycles** 3, then escalate.

**Completion evidence** Final `PYTHONDONTWRITEBYTECODE=1 ./check.sh` exited 0: TypeScript, Python syntax, Ruff and pytest passed; eslint skipped because no lint script exists. Pytest: **1,844 passed, 234 skipped, 505 xfailed**, 220 subtests passed, 1,629 warnings, 32.71 seconds. All 505 OUT-4 cases xfail on the precise missing module, not implemented behaviour. The final run includes the strengthened same-tenant second-mailbox filter fixture. A local AST/schema check confirmed all fourteen route/tool pairs match this packet, every SQLite outreach column exists in 037, and every test has a rule docstring. Whitespace and `git diff --check` passed. The suite created an empty untracked `data.db` absent from the initial tree; it was removed after verification. Only the two authorised files remain changed. No network, implementation, migration, commit or push; no live/Postgres verification claimed.

**Status** in review — Stage A; no Stage B implementation authorised by this packet.

**North Star** P1 tool access, P2/P8 grounded or silent, P9 sealed business; Tool layer and Evals pillars, Phase 1 read capability supporting the Phase 3 outreach department. P7 is preserved: zero new model clients. No new stored data.

### Exact HTTP/tool contract

Prefix every path with `/v1/outreach/`; all HTTP methods are **GET**. Tool arguments match path/query inputs. Business/user/authority/provider credentials are never inputs. `P` means optional `limit=20, offset=0` with the bounds above. UUID path inputs are required. API errors use HTTP 404/403/422 with safe `detail`; dispatcher errors are `{status_code: 404|403|422, error: <safe message>}` and no data. Both unknown and foreign IDs say `Not found`, without echoing IDs.

A collection response is `{items, total, limit, offset, data_quality, message}`. A detail/settings response is `{item, data_quality, message}`. `data_quality` is `available`, `none`, `stale` or `not_available`; messages are deterministic, not model-generated. Every item has **exactly** the keys shown (nullable values remain null). Every string exposed is capped at 1000 characters; only evidence excerpt/fact_value use a 2000-character cap. No HTML rendering or interpretation of evidence as instructions. Dates are UTC ISO strings. All other columns are redacted, including those not specifically named below.

| GET path | Aria tool | Inputs beyond context | Exact item fields | OUT-3 tables read |
| --- | --- | --- | --- | --- |
| `brands` | `list_outreach_brands` | P | id, name, privacy_url, sender_identity, version | outreach_brands |
| `prospects` | `list_outreach_prospects` | P | id, company, name, role, domain, stage, eligibility, subscriber_type, fit_score, confidence, evidence_checked_at | outreach_prospects |
| `prospects/{prospect_id}` | `get_outreach_prospect` | prospect_id | Same prospect fields | outreach_prospects |
| `prospects/{prospect_id}/evidence` | `get_outreach_evidence` | prospect_id, P | id, prospect_id, source_type, source_url, excerpt, fact_type, fact_value, confidence, fetched_at, expires_at | outreach_prospects (parent), outreach_evidence |
| `prospects/{prospect_id}/timeline` | `get_outreach_prospect_timeline` | prospect_id, P | id, prospect_id, campaign_id, mailbox_id, kind, origin, direction, state, accepted_at, created_at | outreach_prospects (parent), outreach_messages |
| `campaigns` | `list_outreach_campaigns` | P | id, brand_id, mailbox_id, name, sequence_version, version, status, timezone, daily_cap | outreach_campaigns |
| `campaigns/{campaign_id}` | `get_outreach_campaign` | campaign_id | Same campaign fields | outreach_campaigns |
| `campaigns/{campaign_id}/sequence` | `get_outreach_sequence` | campaign_id, P | id, campaign_id, sequence_version, ordinal, delay_business_days, approved_at | outreach_campaigns (parent/current version), outreach_sequence_steps |
| `replies` | `list_outreach_replies` | P; optional mailbox_id UUID | id, prospect_id, mailbox_id, category, confidence, resolution, received_at | outreach_replies; existing email_accounts for mailbox ownership only |
| `mailboxes` | `list_outreach_mailboxes` | P | id, mailbox_id, enabled, daily_cap, warmup_stage, sending_days, health_status, health_checked_at | outreach_mailboxes |
| `compliance` | `get_outreach_compliance_status` | P | id, brand_id, version, decision, reviewed_at, review_due_at | outreach_compliance |
| `settings` | `get_outreach_settings_and_permissions` | none | id, pause_all, timezone, business_daily_cap, owner_cc_default, retention_policy_version | outreach_settings |
| `summary` | `outreach_summary` | none | See aggregate schema below | outreach_prospects, outreach_campaigns, outreach_messages, outreach_replies |
| `knowledge` | `get_outreach_knowledge` | P | No items yet | None: knowledge table explicitly deferred to OUT-7 |

Settings additionally returns `permissions={status:"not_available", message:"None available: outreach permission projection awaits OUT-6/OUT-11."}`. It must not infer standing permission from pause_all, sequence approval, or an invoice-chase grant. Its name reserves the agreed future settings/permissions surface; it exposes no automation JSON now.

Knowledge always returns `items=[]`, `total=0`, requested pagination, `data_quality="not_available"`, and `message="None available: approved outreach knowledge awaits OUT-7."` No migration, queries against a nonexistent knowledge table, fallback to receptionist knowledge, or treating message/template text as approved facts. This explicitly resolves the OUT-1 label “knowledge” against Claude's later binding split. OUT-7 extends this contract with its own approved tests/schema.

Redaction includes: prospect email/email_key/number/lawful_basis/owner IDs/why_now; evidence provider_record_id, verification_subject_email_key, raw_verdict, flags and internal versions; campaign target_rules/hashes and first_batch_review_id; sequence template_text/hash/allowed_variables/approver; message To/CC, subject/body, provider/thread/RFC identifiers, payload/hash/version, authority/action/outbox/job references; reply suggested_body, knowledge_refs, inbound/matched-message IDs and owner; mailbox health_evidence, reviewer and pause_reason; compliance narratives/sources/hash/reviewer; settings owner_cc_address. Do not select email credentials for an ownership test. Suppression/token tables are never queried by this contract. Fixtures plant sensitive sentinels in these omitted columns so projecting a whole row cannot pass.

### Grounded aggregate, source links and limits

`summary` returns `{totals, sources, data_quality, message}`. `totals` has exactly these integer keys, across **all current-business rows**, without page/date/cohort filtering in this initial contract:

| Key | Exact database meaning | Source path |
| --- | --- | --- |
| prospects | count outreach_prospects | prospects |
| campaigns | count outreach_campaigns | campaigns |
| accepted_live | messages with origin=live, direction=outbound, state=accepted | prospects list → prospect timeline |
| unknown_live | messages with origin=live, direction=outbound, state=unknown | prospects list → prospect timeline |
| imported_messages | messages with origin=import, regardless of state | prospects list → prospect timeline |
| human_replies | replies with category interested/question/not_now/unsubscribe/objection/wrong_person/referral | replies |
| stage_meeting | prospects whose stored stage=meeting | prospects |
| stage_won | prospects whose stored stage=won | prospects |

`sources` maps each total key to an existing `/v1/outreach/...` list path in that table (messages use `/v1/outreach/prospects`, then the returned ID's timeline). Source links are navigational evidence, not a complete inline dump of all contributing records. Detail IDs and parent IDs are scoped and usable only behind the same gate. No unbounded ID citation array. A/B seeds use identical provider/thread identifiers, so neither can authorize a join across tenants.

These are recorded-stage counts, **not confirmed meetings/wins or won revenue**: 037 has no confirmed-outcome provenance. No conversion/reply rates, denominators or estimated spend. Live accepted means provider acceptance, not delivery. The summary deliberately does not call imported historical sends current billable sends. Date/cohort/mailbox aggregate filters, Needs you deduplication and confirmed outcomes remain OUT-8/owning data tickets with F18 expansion tests; no unsupported argument is silently ignored. Counter reservation/race tests in F11 belong to OUT-6, not this read-only stage.

Use a fixed UTC clock seam for expiry tests. At `expires_at <= now`, evidence excerpt/fact_value become null and data_quality is stale; retain safe source/timestamp metadata. At prospect `retention_due_at <= now`, company/name/role/domain become null. This is conservative read minimization, not a new retention duration or an erasure worker. Never refresh expiry because a record was read.

### Feature gate and separate RED commercial ticket

Existing policy is already sufficient for the **Business-included** route:

- `auth.PLAN_FEATURE_DEFAULTS` is the canonical plan grant matrix: outreach false for Starter/Pro, true for Business/beta. `feature_flags` stores deliberate boolean exceptions, not copied plan defaults; explicit false wins.
- `auth.require_feature('outreach')` wraps `assert_feature_access`. It currently has a platform-admin bypass; OUT-4's shared projection gate still applies business access/entitlement, so both customer APIs and tools refuse when the business is denied. This tightens only this new surface and does not rewrite global auth or give platform admins foreign tenant selectors. Claude should review that combination before implementation.
- `resolve_access_level` implements DECISION 3: active/trialing/past_due full; unpaid/canceled read-only; is_active=false otherwise suspended. Outreach is explicitly in READ_ONLY_REFUSED_FEATURES. Do not use `retained_history=True` to sidestep this. The outer Aria chat route also needs aria_chat: an outreach flag alone is not permission to use every Aria channel.
- `plan_definitions` supplies catalogue/limits; its editable `features` JSON is deliberately not an entitlement authority (`onboarding_api.py:215–225`). Updating only that table cannot implement the paid offers.

**Separate ticket: OUT-12 — outreach commercial entitlement and Stripe (RED), already allocated by OUT-1 §11.** Outcome: Business includes outreach; lower tiers can purchase an add-on; a standalone outreach-only product has just its required capabilities. Preserve these settled product decisions. Acceptance proposal: one authoritative resolver combines canonical base plan with a verified paid product grant, honors explicit admin denial and DECISION 3, and revokes only the purchased capability at cancellation. Do not promote standalone customers to Business or grant accounting/invoicing/general email to make dependencies work. Narrow mailbox connection/sync and outreach-only Aria access must be audited through every API/tool/channel and tested. An admin panel must grant/revoke add-on and standalone products and show mailbox state, per Claude's review. Paid grant state/provenance, Stripe IDs/webhooks, reconcile/downgrade, founder exemption and 200/500 shared allowances need independent tests and review. `usage_meters` remains the single monthly authority; outreach usage events/daily aggregates do not become a second allowance counter. Prices follow OUT-9 economics; no price is invented here.

OUT-12 decides the exact persistent grant/bundle representation, canonical tier/constraint implications and required migrations in its own packet/runbook. It owns any `plan_definitions` changes and cross-stack resolver updates. A manual boolean exception is an existing admin grant, **not proof of a paid add-on**. OUT-4 must not add a new tier, write feature flags, register Stripe products or migrate anything. Dependency: OUT-2, OUT-6/9 measured economics; budget L; reviewer other agent; Mike approves each RED action. OUT-4's tests intentionally cover current canonical access, not a made-up paid product schema.

OUT-1/2 also say retained history survives entitlement loss, while today's outreach gate refuses it. This is an explicit **OUT-12 policy reconciliation question**, not authority for OUT-4 to weaken DECISION 3. Existing stored rows/suppressions are not deleted or mutated by refusal. Inbound objection ingestion is a separate worker contract; these interactive reads do not enable/disable it.

### Deferred read catalogue and executable seam

The following are not implemented or advertised as available by OUT-4: imports/reports (OUT-5 tables), approved knowledge (OUT-7), provider quota/credentials/research (OUT-10), suppression status (needs OUT-6's trusted tenant-keyed matching boundary; no digest comparison is invented), permission/authority summaries (OUT-6/11 fresh shared AUTO settings semantics), usage (OUT-6 generic meter/reservation contract; no event-summed monthly allowance), enrolment/batch-review/dispatch operational projections (OUT-6/8). All must ship scoped tools when their owning features activate. OUT-4 does not read `outreach_enrolments`, `outreach_batch_reviews`, `outreach_suppressions`, `outreach_unsubscribe_tokens`, `outreach_dispatch_jobs`, `outreach_daily_usage` or `outreach_usage_events`. No hidden access to their rows is justified by the general OUT-2 catalogue. No F12–F14 provider correctness claim; those move with deferred OUT-10 as OUT-2 permits.

Proposed Stage B module: `backend/outreach_read.py`, exporting `router`, `engine`, `now()` (aware UTC) and `_load_business(session, business_id)` (delegating to auth). The module shares projections between API and dispatcher. Test seams mirror existing routes; they are not a new entitlement engine. Register every listed name and a strict schema (`additionalProperties:false`) in `assistant_tools.TOOL_DEFINITIONS`, and dispatch through `execute_tool(name, arguments, trusted_business_id)`. HTTP uses `db.get_session`; the tool boundary loads the business using its configured engine and calls the same canonical feature assertion. Error serialization is explicit; no raw exception/SQL/provider detail reaches Aria.

Tests override authenticated context and Business loading only, plus SQLite/clock seams. They **do not override** `require_feature` or `assert_feature_access`. Local GateSession follows the existing action tests because the Business model is PostgreSQL-shaped. Projected fields and dangerous omitted fields use actual 037 spellings; JSONB/UUID/timestamps are SQLite text surrogates. No claim about FK, RLS, concurrent snapshots or Postgres execution plans follows from these tests. There are no requests to external services.

### Review questions and owner behaviour check

- **Claude:** review the exact surface/allowlists, deferred catalogue and knowledge placeholder against the binding OUT-2 split; confirm the proposed registration seam and lack of AUTO collisions. Confirm read-time retention minimization and the canonical gate at both boundaries, including platform-admin behaviour. The unavailable AUTO test file is a checkout fact, not a reason to import unreviewed work.
- **Mike:** approve Stage B's bounded read scope after Claude's review. Retained outreach history after cancellation needs an explicit OUT-12 decision against DECISION 3; add-on/standalone inclusion is already settled, and prices stay OUT-12 after economics.
- **Click check now:** open this packet and the test file. There is no new app behaviour to click in Stage A. After implementation/UI integration, switch business A/B, inspect prospect/campaign history and empty knowledge, then compare Aria's counts to visible records. `check.sh` cannot prove those future screens, live migration state or external behaviour; Stage A green with xfails is a test scaffold, not a working feature.
