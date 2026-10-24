## TICKET OUT-7

**Outcome** Every outreach reply stops the sequence, gives the owner a grounded proposed answer where appropriate, and hands the conversation over without duplicate answers.

**Current evidence** `docs/OUT-3-TICKET.md:73` explicitly leaves knowledge and reply slots to OUT-7. `backend/migrations/037_outreach_core.sql:425` creates replies but neither missing table. `backend/services/chase_replies.py:118` stores mailbox search results; `:145` searches then scans invoice replies. `backend/services/outreach_send.py:195` searches before claim and `:232` rechecks the database under locks. `backend/services/aria_actions.py:493` enforces active owner membership, but `ACTION_TYPES` currently registers only `send_outreach`, not `reply_outreach`. OUT-1 §6 and OUT-2 §3/§6 F17 set the one-answer and handover rules.

**Scope** Full OUT-7, with no schema deferred: Part A is RED migration 038; Part B is shared inbound integration, pause-on-reply, classification, one-answer cards, owner handover, mailbox health events and scoped knowledge/slot read projections. This delivery is **Stage A only: ticket, executable tests, draft migration, draft runbook, local replay registration**.

**Non-goals** No service/model/API/frontend implementation in Stage A, no application data writes, production or staging SQL, provider/model calls, emails, network, commit, push or deploy. No OpenClaw/control-tower reads. No independent inbox cursor, scheduler, model client, monthly allowance or approval engine. No invoice-chase behaviour change, real imports, automatic reply approval, speculative contact enrichment, retention activation or mailbox fallback. Existing OUT-6 transport and caps remain binding.

**Dependencies** OUT-1 approved design; OUT-2 shared contracts; 035/036/037; OUT-6 reviewed send and owner hook. AUTO owner agrees the shared storage-to-scan boundary before implementation. OUT-4 projections/grounding ship with new data before population. Router-backed classification/drafting is an activation gate; no new direct provider client. OUT-13 retention and OUT-9 pilot gates remain. Migration queue and structural staging parity must be reconfirmed before any remote action.

**Affected systems** Backend tests and future services/API/tools, PostgreSQL, shared inbox and action interfaces; future UI consumes existing card/Needs you surfaces.

**Security & data risk** Part A RED (schema/RLS/grants). Part B AMBER feature work with RED owner authority, suppression and claim races. Mike's 23 October 2026 **Option 2** authorises full schema design now and these draft/test artifacts; it does not authorise applying SQL, implementing services or sending. Each remote action remains separately approved.

**Acceptance criteria** The behaviour below and every test pass after implementation. Stage A has green `./check.sh`, behaviour cases strictly xfail only for absent `services.outreach_replies`, and local PostgreSQL cases skip only when URL is absent. Missing tables fail when a URL is supplied. No existing service diff. No hidden deferred schema.

**Required tests** `backend/tests/test_outreach_replies_schema_rls.py` and `backend/tests/test_outreach_replies.py`, plus existing OUT-6/AUTO regressions. PostgreSQL claim/pause/slot races and real action-boundary tests are completion gates in Part B, not established by SQLite. Grounding compares projected knowledge IDs, versions and slot state to scoped database rows.

**Verification** `PYTHONDONTWRITEBYTECODE=1 ./check.sh`; `bash -n scripts/rls-local.sh`; `git diff --check`. If loopback is reachable, run targeted schema tests against a rehearsed 038 harness. Independent reviewer replays 038 twice, rollback/reapply and existing RLS suite, with policy-baseline review below. `./check.sh full` before any future push, which is not authorised here.

**Likely files** Stage A: this ticket, the two tests above, `backend/migrations/038_outreach_replies.sql`, `audits/038-PROD-RUNBOOK.md`, `scripts/rls-local.sh`. Part B exact integration surfaces below.

**Builder** Codex. **Reviewer** independent agent for draft/test review; Claude Code must review shared AUTO interfaces and RED completion before implementation approval. **Branch** `ticket/OUT-7-outreach-replies`, worktree `bh2-OUT-7`. **Budget band** L full OUT-7; Stage A bounded to artifacts. **Max repair cycles** 3. **Status** in review; implementation not authorised. **Completion evidence** recorded below.

**North Star** P2 grounded facts, P4 owner decides, P5 visible structured knowledge, P8 honest refusal, P9 sealed businesses; Tool layer and Actions & permissions pillars, Phase 3. Security/isolation and correctness prerequisites.

### Part A — RED schema, migration 038 (draft)

Same shape as 037: one concurrent parent index outside a transaction; attach it and create both tables, indexes, invoker trigger, RLS and grants in one transaction with a five-second lock timeout. No existing columns or action/status constraints change. No ORM class can reach boot-time `create_all()` ahead of this migration.

| Table | Exact columns, in SQL order | Invariants |
| --- | --- | --- |
| `outreach_knowledge` (14) | id, business_id, created_at, updated_at, brand_id, topic, answer, source_reference, version, status, approved_by, approved_at, review_due_at, retired_at | Tenant-bound brand; unique business/brand/topic/version; positive version; draft/approved/retired; approval actor/date paired and required when approved; review after approval; retirement timestamp iff retired. Bounded nonblank topic/answer/source. At most one approved version per topic. Approved content, source, identity, approval and review dates immutable; retirement permitted, resurrection forbidden. New facts/reviews use new versions. |
| `outreach_reply_slots` (18) | id, business_id, created_at, updated_at, prospect_id, reply_id, mailbox_id, action_id, message_id, state, generation, reserved_at, dispatched_at, settled_at, released_at, release_reason, outcome_evidence, payload_hash | One permanent row per business/prospect across brands, campaigns and mailboxes. Unique reply and action within business. Reply composite FK binds tenant/prospect/mailbox; message composite FKs also bind action. All parents tenant-bound. Positive generation; reserved/accepted/unknown/released; dispatch requires message/hash/date; accepted requires settlement; release requires reason/time/nonempty bounded object evidence. |

Both have UUID primary keys, non-null business FK, UTC timestamps and `UNIQUE(business_id,id)`. Actor UUIDs are audit attribution, as in 037, not permissions; service checks current active owner membership. The slot's action type, immutable payload, factual citations and lifecycle transitions are service checks, not claimed as SQL CHECK guarantees. JSON knowledge refs on replies/actions are validated against same-business/same-brand immutable fact versions at proposal and claim; they never grant authority.

The new parent key is `outreach_replies_out7_identity_key(business_id,prospect_id,mailbox_id,id)`. Existing 037 message/action/brand/prospect/mailbox composite keys are reused. No cascading deletes or identity rewrites. New indexes: knowledge review queue, partial unique approved topic, slot state/update queue; unique constraints also supply their indexes.

Default table and column grants are revoked from PUBLIC/anon/authenticated/service_role. RLS enabled before commit. Knowledge permits **authenticated member SELECT only**, using exactly `is_business_member(auth.uid(),business_id)`; no admin bypass. Slots are backend-only, no policies/client privileges. Service gets SELECT/INSERT/UPDATE/DELETE/REFERENCES/TRIGGER, never TRUNCATE. Effective inherited client or service TRUNCATE privileges abort the transaction.

**Exact deltas:** +2 tables, +32 columns (14 + 18), +1 policy. On current checked-in RLS baseline 94: **95**. The recorded post-037 production column census 1,105 would become **1,137** if no intervening changes; live baseline must be measured, never inferred. Outreach subtotal 17 → 19 tables, 261 → 293 columns; policies 6 → 7. Re-paste adds zero further objects/columns/policies.

`test_tenant_isolation_rls_path.py` pins 94 and the reviewed policy CSV lacks this draft policy. Do not weaken that independent baseline or label a SQL-derived policy as live evidence. The targeted 038 suite asserts the exact new policy; full harness isolation suite will intentionally require Claude's reviewed catalogue addition/count 95 before Stage B acceptance. Local replay/pruning recognises 038; historical replay indices/error allowances remain unchanged.

### Part B — behaviour Mike can approve

1. **Stop first.** When a genuine reply is stored, stop all pending/active sequences for that prospect in this business before asking a model what it means. Dismiss unclaimed sequence cards and cancel pending jobs. The owner sees the original reply and mailbox beside its label. No label can resume a sequence. Classification failure still leaves it stopped and in Needs you.
2. **Use the actual mailbox.** Read AUTO-2's stored messages and complete `search_from` results. Match business + mailbox + provider thread, exact participants and available RFC references. A repeated thread ID in another mailbox is not the same thread; subject alone proves nothing. Uncertain same-sender matches pause all possible outreach enrolments for owner review and create no answer card. Self-mail is ignored; out-of-office pauses without treating it as buying interest. Disconnection, partial search and missing bodies fail closed. Never change invoice chasing's match or resolution rules.
3. **Close the local race.** Search outside locks, store through AUTO-2, then recheck database replies inside OUT-6's claim transaction. A reply stored between search and claim blocks the next step even before classification. Storage/pause and claims share the business/settings lock order. Remote mail arriving after final search may still race provider acceptance; show search and dispatch timestamps, never promise recall.
4. **Honour objections.** Unsubscribe/objection immediately writes the same tenant address suppression as OUT-6 and cancels unclaimed work across campaigns/mailboxes. It requires no owner approval, plan entitlement or model success for an explicit opt-out. No marketing acknowledgement is sent. Domain-wide requests go to owner scope review; do not silently suppress other tenants or invoice debt communications. Hard bounce suppresses the recipient; complaint pauses only its mailbox; three distinct hard bounces among its latest 50 accepted sends pauses that mailbox. Repeated/stale events never double-count or reopen it.
5. **One grounded answer.** For a question, use only this campaign brand's current approved knowledge where approval is not in the future and `now < review_due_at`. Show pinned fact IDs/versions/sources with the card. Missing, contradictory, retired, expired or unsubstantiated facts mean handover. Reject invented citations or factual additions; untrusted inbound text cannot request tools or permissions. Clear interest may include an approved booking link; an unrelated question never gets a generic booking link instead of an answer. AI identity/sign-off stays explicit; owner CC is opt-in and shown exactly.
6. **One card and one send.** Reserve the permanent prospect slot and create its proposed `reply_outreach` card in one transaction; two sync workers return the same existing card, even across campaigns/mailboxes. This is a proposal reservation, not usage or send authority. Claim checks the same slot/action/generation and reserves usage atomically with the shared action CAS. The active owner must approve the exact version, as in OUT-6, including membership recheck under lock. Staff, inactive owners, platform admins without ownership, other-tenant owners and NULL-user automation cannot approve. No chat/model or standing-permission shortcut.
7. **Keep uncertain sends held.** Accepted consumes the slot; unknown keeps it held, without retry or lease-expiry release. Confirmed non-acceptance can release only with recorded evidence and an owner-reviewed replacement card; reuse the same prospect slot with incremented generation, preserve old action/message/job/evidence audit. Never reuse a prior dispatch operation. Dismissing an unsent card leaves handover, not automatic re-proposal. A second question in any thread/mailbox hands to the owner.
8. **Hand over visibly.** Unknown/low-confidence, missing facts, second question, not-now, wrong-person or referral creates/updates Needs you with original reply, safe reason and owner assignment; mark reply handed_over and takeover time. Owner takeover stops drafts and pending sends. Referral is a suggestion for a new unapproved contact, never permission to email. No automatic restart. A stale scan/classifier result cannot overwrite takeover, suppression, resolution, newer classification or an accepted/unknown slot. Use scoped compare-and-swap against the captured reply version/timestamp and re-read under locks.
9. **Keep Aria grounded.** Ship tenant-scoped knowledge and redacted answer-slot state projections with grounding tests in this ticket, coordinated with OUT-4. No raw token/digest or sensitive transport payload in tool results. An entitlement downgrade does not disable inbound safety/history/suppression.

### Proposed exact service contracts (absent today)

`services.outreach_replies.scan(session, business, *, classify, moment) -> list[reply_id]`: consume already-stored scoped inbox rows idempotently. Commit reply capture + pause/cancellation before invoking `classify(bounded_reply_context)`. Classification returns `{category, confidence, classification_version}`; update with CAS only if the captured state is still current. No provider search inside this method or while holding locks. It owns its transactions and must receive a session without unrelated pending writes.

`propose_answer(session, business, *, reply_id, draft, moment) -> card | {status: 'handed_over'}`: load scoped reply and current brand knowledge, invoke `draft({reply, knowledge})` outside locks, then recheck facts/reply/owner-takeover and create the slot plus card atomically. Each knowledge entry includes id/version/answer/source_reference. Drafter returns `{body, knowledge_refs: [{id,version}]}`; unsupported refs or claims refuse. Card uses existing `{id, version, preview}` and `reply_outreach`; preview pins recipient/mailbox/thread/reply, slot ID/generation, body, sign-off/footer, knowledge refs, CC, expiry and payload hash. No knowledge means no drafter call. Same reply retries return existing card; a different reply with occupied slot hands over.

`handover(session, business, *, reply_id, user_id, moment) -> reply view`: authenticated active owner only for manual handover; scoped lookup, lock, terminal update and unclaimed-card cancellation. Internal classification handover uses a separate trusted service path, never a forged owner ID.

`aria_actions.approve` keeps its public signature. Register `reply_outreach` server-side and apply the existing `_is_active_owner` rule before search and again in claim. Reply-specific preparation reuses OUT-6 usage/mailbox/entitlement/footer/dispatch gates but permits the *matched reply* and stopped enrolment (sequence claim must still reject them). Any newer reply, takeover, invalid fact or suppression blocks. No generic `_execute`/email bookkeeping. Slot, message, job, usage and action claim roll back together on lost CAS. Allowed service transitions are reserved → accepted/unknown/released, unknown → accepted on recorded acceptance evidence, unknown → released only after independently recorded definite non-acceptance, and released → reserved only with owner review and generation +1. Accepted is terminal and can never release. Every release archives the previous binding and evidence on the immutable old action/result before a replacement can use the row; schema evidence shape alone is not proof of non-acceptance. Settlement updates slot and existing ledger atomically; reconciliation never calls transport again.

Shared lock order follows OUT-6: business settings → outreach settings → entitlement/meter/day/mailbox → prospect/enrolments → campaign/brand/knowledge/reply/slot → action → membership (existing hook order). All readers/writers, including suppression, knowledge approval/retirement and owner takeover, must agree the order before implementation. No network/model call inside a locked transaction. Captured timestamps support CAS, not untrusted provider-watermark authority. Existing AUTO sync state remains its single owner.

### Exact Part B file ownership

- New `backend/services/outreach_replies.py`: scan/match/pause/classify/propose/handover and health observations.
- `backend/services/outreach_send.py`: shared inbound database recheck and typed reply claim/dispatch/settlement integration; preserve initial/follow-up semantics.
- `backend/services/aria_actions.py`: Claude-coordinated reply action registration/build/edit/owner hook; common signature and invoice path unchanged.
- `backend/services/chase_replies.py`: coordinate extraction/reuse of `_store` notification boundary only; no changes to chase matching, categories, invoice paid state or decisions. Existing `_store` commits; no call from an OUT-7 locked transaction.
- `backend/app/email/service.py`, `backend/app/email/router.py`, and `backend/services/background_sync.py`: shared storage completion → OUT-7 scan, scoped owner knowledge/handover handlers, no second poller/cursor. Inspect caller chain before patching; do not assume a generic inbound service exists (none at `services/inbound_sync.py`).
- `backend/outreach_read.py` (knowledge placeholder at line 200), `backend/assistant_tools.py` (existing outreach tool registry at line 525), and `backend/tests/test_outreach_read.py`: implement the existing scoped knowledge projection and redacted slot summary, with database grounding tests; no second registry.
- Tests above plus existing AUTO/OUT-6 suites and new scoped tool/API tests. Frontend cards/Needs you presentation remains OUT-8; full OUT-7 supplies its data/contracts, no separate UI rewrite.

### Decisions for Mike (recommendations; no response needed to finish Stage A)

1. **Proposal hold:** reserve the durable slot at card creation, then validate/reserve send usage at approval. **Recommend yes**: fulfils the requested one-card rule under concurrent syncs; this tightens OUT-1's approval-only slot language without authorising a send.
2. **Knowledge review interval:** require an explicit date on each approved version. **Recommend 90 days as the suggested UI default**, shorter for prices/availability, no automatic extension; expired facts stop answers. No default expiry is silently stored by 038.
3. **Confidence and ambiguity:** **recommend handover below 90/100**, missing body, conflicting facts or uncertain threading; pause all possible same-business enrolments. A classifier cannot weaken a clear opt-out. Threshold is proposed, not provider-calibrated evidence.
4. **Release and replacement:** **recommend owner-reviewed replacement only after definite non-acceptance**, reusing the same slot with a new generation and immutable old audit. Unresolved unknown never releases; independently proven non-acceptance may release after owner review. Dismissal hands over. No timeout reset or new-campaign reset.
5. **Handover destination:** **recommend assigned active prospect owner, otherwise the business's active owner queue**, with no external notification in this ticket. If no active owner exists, keep Needs you unassigned and blocked. No real email/SMS side effect.

### Completion evidence / limits

`PYTHONDONTWRITEBYTECODE=1 ./check.sh` passed: 4 checks passed, 0 failed, optional eslint skipped (no script); backend **2,743 passed, 291 skipped, 25 xfailed, 220 subtests passed**. Targeted OUT-7: **25 xfailed / 30 PostgreSQL cases skipped**. Strict xfail catches only the absent implementation module; schema scaffold setup executes before that check. `bash -n scripts/rls-local.sh` and `git diff --check` passed. An explicit connection attempt to 127.0.0.1:54329 was denied with **Operation not permitted**; no SQL ran. Therefore no PostgreSQL parsing, constraints, RLS, replay/re-paste/rollback or concurrency proof is claimed. No service implementation, network beyond that permitted loopback attempt, remote database, commit or push.

Independent draft review checked SQL/FK targets, counts, fixture validity and runbook limits. Repairs added valid slot-state tests, one-approved-version checks, genuine owner memberships, successful owner path, post-proposal knowledge invalidation and older-scan suppression preservation. Expiry advances only 31 seconds past a near-term review date so normal card expiry cannot mask missing knowledge validation. The PostgreSQL race now uses different replies/actions/mailboxes for the same prospect, isolating the business/prospect unique key. Runtime service lifecycle/CAS evidence, Claude's shared-interface approval and independent PostgreSQL rehearsal remain open; Stage A xfails prove neither behaviour nor sending. No app behaviour exists to click in Stage A. Mike should open this ticket and the behavioural tests to approve the five choices and RED boundaries. Future authorised behaviour check: view a campaign reply → verify sequence stopped → inspect fact citations and exact mailbox on one card → owner approves → second reply appears in Needs you; test opt-out and switch business. `check.sh` cannot prove that UI, real provider threading or live schema state.

### Claude's review of Stage A (schema) — 23 October 2026
- **Local Postgres:** rebuilt with 035–038 replayed. The 038 schema suite and the 037, AUTO-2 and tenant-isolation suites give **280 passed**.
- **Re-paste:** 038 applied twice more leaves policies, columns and outreach tables unchanged (95, 1,101 local and 19). It is idempotent.
- **Policy baseline:** Claude verified `outreach_knowledge_member_read` (member-only SELECT, the same rendering as 037's six) and added it to `audits/BH-003-rls-policies-post-july.csv`; the count goes from 94 to **95**. `outreach_reply_slots` has no policy (backend only), as designed.
- **Still to do before 038 goes to production:** the staging rehearsal (037 style), and Mike's runbook run (`audits/038-PROD-RUNBOOK.md`).

## Mike's approval — 24 October 2026
- **Approved:** the tests, all five decisions as recommended, and the one-answer-per-prospect rule (one Aria-drafted answer per prospect; every later question goes to the owner).
- **Build split** (as for OUT-6):
  - **Codex:** `outreach_replies.py`, the `outreach_send.py` integration, the storage-completion → scan wiring in `app/email/*` and `background_sync.py`, and the `outreach_read.py`/`assistant_tools.py` projections.
  - **Claude:** the `reply_outreach` registration and owner hook in `aria_actions.py`, and any `chase_replies._store` boundary change. Codex does not edit those two files.
- **Order to production:** Codex builds → Claude reviews → 038 is rehearsed on staging → Mike runs 038 on production → only then is OUT-7 merged.

## Stage B builder handoff — 24 October 2026

**Builder:** Codex, in `ticket/OUT-7-outreach-replies`. **Reviewer:** Claude.
Serves P2/P4/P5/P8/P9, Tool layer and Actions & permissions. Mike's approval
above is the implementation authority. Migration 038, `aria_actions.py` and
`chase_replies.py` are untouched. No network, provider/model call, real send,
SQL against an external database, commit or push was performed. The pre-existing
untracked `data.db` is untouched. This is not activation or deployment approval.

### Implemented behaviour

- `outreach_replies.scan` consumes existing tenant-scoped inbox storage. Matching
  uses exact sender, accepted outbound history, mailbox and provider thread;
  available recipient/RFC evidence must also agree. Subject is never identity.
  Ambiguity pauses every candidate prospect's sequences and hands over. Self-mail
  is ignored. Stop/cancellation and explicit opt-out suppression commit before
  classification; no callback runs with locks held. Classification errors,
  missing bodies, disconnected mailboxes, unknown/low-confidence, OOO, not-now,
  wrong-person and referrals become assigned `handed_over` reply records.
  Existing resolved/dismissed replies, suppression and takeover are not reopened.
- `propose_answer` rechecks capture state and immutable current brand facts after
  drafting, then creates the card and permanent prospect slot atomically. Retries
  return the existing proposed card; later replies hand over. Proposal does not
  reserve sending allowance. No facts means no draft callback. The deterministic
  grounding rule accepts only the referenced facts' exact answers joined with
  blank lines; invented citations, extra claims and changed/expired facts refuse.
  This deliberately conservative extractive draft policy is not a claim that a
  model can establish semantic answer relevance. Router activation/evaluation
  remains a gate, including relevance and approved booking-link selection.
- Typed reply claims reuse OUT-6 entitlement, compliance, exact mailbox, footer,
  opt-in CC, current window, warm-up and shared allowance/cap gates. They allow
  exactly the matched inbound and stopped (`replied`) enrolment, and do not impose
  sequence-follow-up delay on an answer. Other stored inbound blocks even before
  scanning/classification. A reply never advances/restarts a sequence. The
  message has kind `bespoke` and links its matched outbound via `reply_target_id`.
- Dispatch adds a database recheck for suppression, pause/takeover, mailbox health,
  inbound and reply facts before fencing transport. This also addresses OUT-6's
  suppression-between-claim-and-dispatch backlog. The SQL sender filter replaces
  its whole-inbox Python filter. The remote arrival window after final search/
  database recheck still exists. UK bank holidays and unapproved-card token
  revocation remain OUT-6 backlog.
- Slot, message/job, action, outbox and shared metering settle in one transaction.
  Accepted is terminal; unknown holds the slot and allowance with no resend.
  Definite non-acceptance releases allowance, but holds the answer slot until
  explicit owner review. `reconcile` verifies outside locks without transport;
  repeated terminal evidence is idempotent and contradictory terminal evidence
  refuses. `release_slot` archives the entire old slot binding/evidence on the old
  action result. `replace_answer` requires active owner review, a released slot,
  still-current facts and no later reply/takeover; it reuses the original draft,
  increments generation and issues a new card/operation/RFC ID. No automatic
  redraft, timeout reset or retry is exposed.
- `observe_health` accepts a **trusted, authenticated provider-adapter observation**,
  not a model classification or public request body. It binds the stored event
  to an accepted message's provider ID and mailbox. Hard bounces suppress that
  tenant recipient; complaints pause only the attributed mailbox; three distinct
  hard-bounced messages among its latest 50 accepted sends pause it. Repeated
  stored events do not double-count and old events never reopen a mailbox.
  Live provider health ingestion/authentication is still an adapter gate.
- `outreach_storage_completed(session, business)` in `app/email/service.py` is
  called after committed storage in `_run_inbox_sync`, `sync_email_inbox` and
  `_sync_email_for_business`. No poller or cursor was added. No plan gate disables
  safety scanning. The default has **no model callback** and hands over safely;
  missing rollout schema/scan errors are logged as unavailable, not empty inbox.
  Approval independently checks stored inbound even if that notification fails.
- `POST /v1/outreach/replies/{reply_id}/handover` and
  `POST /v1/outreach/knowledge` use authenticated context and active-owner checks,
  including membership recheck under lock. Handover remains available after a
  plan downgrade. Knowledge writes require outreach access and an explicit
  future review date; approval retires the previous version of the topic and
  creates a new immutable version. No 90-day default is silently stored.
- Existing Aria/API read registration now supplies knowledge (IDs, versions,
  answer/source, status and review dates) and `list_outreach_reply_slots`
  (`GET /v1/outreach/reply-slots`). Slots expose state/generation/timestamps and
  related record IDs, never payload hashes, transport evidence, token or digest.
  Reply reads include original inbound/matched-message and assigned-owner IDs.
  These history reads use the existing retained-history gate: downgrade does not
  hide them; explicit feature denial and suspension still apply. Grounding tests
  compare scoped stored values, including stale knowledge and slot state.

### Exact Claude integration contract

`outreach_replies.propose_answer(session, business, *, reply_id, draft, moment)`
returns `{id, status, preview, version}` or `{status: 'handed_over', ...}`. It owns
its transactions and creates **both** the `reply_outreach` action and slot; do not
call generic `propose` afterwards or create another card. `draft(context)` is a
trusted server-configured router callback receiving bounded untrusted reply text
and scoped knowledge, and returns `{body, knowledge_refs: [{id, version}]}`.
`scan(session, business, *, classify=None, moment=None)` owns its transactions;
`classify(context)` returns `{category, confidence, classification_version}` and
cannot grant authority. Neither callback is accepted from a request/model tool.
The production storage notification currently invokes neither model nor drafter.

Register `reply_outreach` in the server action types/features, **not** chat/voice
or standing-permission types. Refuse NULL owner, staff, inactive/foreign owner,
platform-admin-without-ownership and automation markers before searching. Keep
the public `aria_actions.approve` signature unchanged. Use the existing active
owner check both before search and under membership lock after action preparation.
Do not build a reply with the generic task/email builder. A stored reply preview
has `action_kind='reply_outreach'`; this is checked against its actual action row,
permanent slot/action/generation and deterministic operation key.

```python
# Scoped stored proposed card, authenticated active owner, exact version and
# expiry already validated; end preliminary read transaction first.
outreach_send.search_reply_before_claim(
    session, business, action_id=action_id, payload=payload)
# Same session; provider search and AUTO-2 storage have finished outside locks.
outreach_send.prepare_reply_claim(
    session, business, action_id=action_id, payload=payload,
    user_id=user_id, version=version, moment=outreach_send.now())
# Recheck active owner WITH membership lock, then existing scoped, exact-payload
# proposed -> executing CAS. Any exception/lost CAS: rollback EVERYTHING and
# remove session.info['outreach_dispatch'][action_id]. Otherwise commit once.
result = outreach_send.dispatch_reply(
    session, business, action_id=action_id, payload=payload)
# No generic _execute, _bookkeep_email, meter increment or finalisation.
# Return the persisted card view, as OUT-6 does.
```

Preparation performs no commit/rollback/provider call; slot message binding and
usage reservation participate in the action CAS transaction. Dispatch requires
no active transaction after claim commit and consumes the same-session one-use
permit. It returns `status`/`outcome`/`search_at`/`dispatch_at` and owns settlement.
Crash/restart cannot recover a permit or resend. Preserve all preview bindings,
including pinned knowledge and exact footer/CC. Do not allow arbitrary reply
body editing: current deterministic claim validation only permits the exact
cited approved answers. Dismissal never releases/re-proposes the slot. The next
proposal attempt hands over; the permanent row remains held.

Transport uses the existing `send_outreach` envelope plus, **only for replies**,
`reply_provider_message_id` naming the inbound provider message. Preserve its
mailbox/thread and RFC headers when available. The adapter must implement genuine
provider reply semantics (particularly Graph's original-message reply path) and
fail closed if it cannot; no fallback to generic `send_email`. No such production
adapter is added by this work.

**Claude-owned `_store` change needed:** keep `_store(session, business,
account_id, messages)`'s signature and commit ownership. Store available
`to_emails`, `cc_emails` and `raw_headers` alongside the existing body/thread
fields; retain provider `Message-ID`, `In-Reply-To`, `References` verbatim within
the existing bounded stored representation. After its storage commit, call
`app.email.service.outreach_storage_completed(session, business)` once, including
when the search returned no new rows. Do not call it before commit or from a
locked claim. The notification catches/logs its own scan errors. Do not alter
invoice matching/categories/resolution. This single change also covers OUT-6/7
preflight `search_before_claim`, which already calls `_store`; no duplicate
notification was added around it here. Inbound already stored between search
and claim is checked independently of this future notification.

**Other public service boundaries for adapter/UI work:**

```python
handover(session, business, *, reply_id, user_id, moment)
save_knowledge(session, business, *, brand_id, topic, answer, source_reference,
               review_due_at, user_id, moment)
observe_health(session, business, *, inbound_email_id, message_id, kind,
               evidence, moment)  # kind: hard_bounce | complaint
reconcile(session, business, *, action_id, verify, moment)
release_slot(session, business, *, slot_id, user_id, moment)
replace_answer(session, business, *, slot_id, user_id, moment)
```

`verify(query)` is a trusted read-only adapter callback, never a user assertion;
query contains original operation/mailbox/provider/RFC IDs. Its result must
include terminal `outcome`, matching `operation_key`/`mailbox_id`/`provider` and
an independent `verification_reference`. Health evidence must include matching
provider message ID/mailbox/provider and `authenticated=True` set only by a
verified adapter. These are internal contracts, not new public webhooks.
All mutation writers take the existing business/settings locks first. SQLite's
local writer lock tests idempotency but is not PostgreSQL locking evidence.

### Remaining strict xfails

Exactly eight cases have reason **`awaits Claude's aria_actions hook`**:

- `test_answer_card_uses_real_owner_only_approval_boundary`: five identities.
- `test_active_owner_can_approve_one_answer_through_real_hook`: one case.
- `test_knowledge_changed_after_proposal_refuses_claim`: retire/expire, two cases.

Their original assertions remain. Only missing `reply_outreach` registration
raises `MissingSharedHook`; imports, fixture setup, service proposal and all
other failures are real failures. Once Claude registers the action, passing
cases are strict XPASS until he removes their marks. Separate direct service/CAS
tests exercise claim, dispatch, settlement, rollback and knowledge/race checks
now; they do **not** claim to prove the absent owner hook.

### PostgreSQL verification Claude must run

No loopback connection was attempted in Stage B: this sandbox cannot reach it.
Against the already authorised **local synthetic** 035–038 harness, run with
`RLS_LOCAL_DATABASE_URL` set to that loopback harness (never a remote URL):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  backend/tests/test_outreach_replies_schema_rls.py \
  backend/tests/test_outreach_schema_rls.py \
  backend/tests/test_outreach_send_rls.py \
  backend/tests/test_tenant_isolation_rls_path.py
```

Add/run genuine two-session **service-path** tests, beyond the existing unique-key
schema race: simultaneous scans/proposals for one prospect across two mailboxes;
reply storage/pause versus sequence claim; owner takeover/suppression versus
reply claim and dispatch; fact retirement/expiry versus drafting and claim;
last monthly/business/mailbox/campaign slot with sequence and reply competing;
lost action CAS/hook exception rolling back slot message binding, messages/jobs,
events and every meter; duplicate approvals and stale slot generation; owner
membership demotion during search; unknown -> acceptance/non-acceptance twice;
owner-reviewed release/replacement preserving old audit; crash after claim,
after fence and after provider acceptance, including settlement failure and no
resend; original UK month/day and DST settlement. Observe actual blocked locks,
not sleeps, and fail races on worker exceptions/timeouts/missing outcomes.

Verify native UUID/JSONB/text[]/timestamptz binding, 037 composite FKs/triggers,
038 immutable knowledge and slot constraints, service grants and member-only
knowledge SELECT with no slot browser access. Re-paste/rollback/reapply and the
95-policy baseline remain required. Extend teardown to remove reply slots and
knowledge before their parents if sharing the OUT-6 synthetic tenants. Rerun
AUTO regressions after `_store` changes and API-chain ownership tests after the
hook. Gmail/Graph wire fixtures, authenticated health-event parsing, router
relevance evals, UI and live delivery are **not** established by SQLite tests.

**Mike's eventual behaviour check:** after Claude's hook, adapter/router gates,
038 rollout and pilot approval, open a campaign reply; confirm the sequence is
stopped, the original mailbox/message and fact citations are shown on one card;
approve once as owner, then verify the next question goes to Needs you. An
opt-out must suppress without an acknowledgement; switching business must hide
all these records. No new frontend or real-send check was performed here.

### Stage B verification result and scope blocker

**Status: implementation handed off, acceptance blocked; `./check.sh` is not green.**
Final `PYTHONDONTWRITEBYTECODE=1 ./check.sh` exited 1: frontend TypeScript, Python
compilation and Ruff passed; optional eslint skipped. Backend: **2,827 passed,
291 skipped, 8 xfailed, 220 subtests passed; 2 failed**. The only failures are:

- `LiveSchemaConformance.test_full_coverage_leaves_nothing_unguarded`
- `LiveSchemaConformance.test_unguarded_table_count_only_ratchets_down`

Both correctly identify `outreach_reply_slots` as absent from the **live** schema
dump. This is expected before 038 deployment under Mike's approved rollout order;
it is not evidence that 038 is wrong. The earlier read-router assertion was
repaired to assert GET-only methods for the enumerated read surfaces while
retaining its SELECT-only SQL check; the new owner writes are separately tested.
Final targeted OUT-7 service suite: **46 passed, 8 xfailed**. `git diff --check`
passed. All original Stage A assertions remain, with only the absent-module
expectation replaced by the eight explicit Claude-hook expectations above.

The live dump, conformance guard and migration have **not** been changed, and
SQL has not been disguised to evade the scanner. The conformance test is outside
Mike's assigned file list. Codex requested permission for one additional test-file
change: validate the two reviewed pending 038 tables against a byte-digest-pinned
migration contract, explicitly separate from live evidence, with the live dump
still authoritative for every observed table and the unguarded budget still zero.
A concrete unapplied patch was prepared at `/tmp/OUT-7-schema-guard-proposal.patch`;
its standalone test copy passed **12 tests**. That is a proposed repair, not a
passing repository gate or deployment evidence. Apply/review it only after the
scope extension is authorised, then rerun `./check.sh`. Updating the live dump
requires a separately authorised real census after deployment, never invented
columns from migration text. No change to Claude-owned files is needed to resolve
this particular guard conflict.
