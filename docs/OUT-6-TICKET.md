## TICKET OUT-6 — Stage A: owner-approved outreach sending

**Outcome** An owner can approve exactly one version of one outreach message from the campaign's chosen mailbox, with current eligibility, reply, suppression and capacity checks before anything leaves the app.

**Current evidence** `docs/OUT-1-DESIGN.md` §11 OUT-6 assigns adapters, action binding, limits, unsubscribe and metering. `docs/OUT-2-CONTRACTS.md` §§2–3, F01–F11/F13/F14/F16 and the AUTO owner's agreement establish the boundary; Claude's final review requires `services/metering` / `usage_meters` as the sole monthly allowance source. `backend/services/aria_actions.py:40` omits outreach from `ACTION_TYPES`; `:268` proposes cards, `:389` approves, and its conditional UPDATE commits before `_execute`. There is no outreach reservation hook or `services.outreach_send` module. `backend/services/automations.py` `_reserve`/`_still_holds` demonstrate durable tickets and ownership fencing, but commit reservations separately and allow reclaiming unused chase tickets: neither is an outreach dispatch authority. `backend/services/chase_replies.py` `find_replies` uses whole-mailbox searches; `_store` commits. `backend/providers/base.py` `search_from` promises complete results or an exception. The current send result only carries an optional message ID. `backend/migrations/037_outreach_core.sql` includes outreach action types, campaign/mailbox bindings, messages, dispatch jobs, daily usage, usage events and unsubscribe tokens. OUT-3 owns schema/RLS, OUT-4 scoped reads, OUT-5 paused import history. Mike reports 037 live; this offline task does not independently verify production.

**Scope** Stage A: only this packet and `backend/tests/test_outreach_send.py`. Specify the future `send_outreach` builder, approval-time gates, atomic reservations, once-only dispatch and unsubscribe service; encode synthetic failing tests. All OUT-6 sends require individual owner-approved, version-bound cards, including follow-ups. Stage B implementation is a separate reviewed RED step.

**Non-goals** No implementation, schema changes, production SQL, auth policy edits, real emails, credentials, network, commits or pushes. No access to `~/.openclaw` or `~/control-tower`. No `reply_outreach`, classification/answer slots or reply UI (OUT-7); no outreach screens (OUT-8); no automatic sending, scheduler, standing permission or outreach permission registration (OUT-11). Research/provider enrichment remains OUT-10, pricing/billing OUT-12, retention OUT-13, real pilot OUT-9. Generic default-mailbox fixes and AUTO internals remain Claude's. Existing untracked `data.db` is untouched.

**Dependencies** OUT-2 contracts, OUT-3/037, OUT-4 reads and AUTO-1/2 baseline are present in this branch. Claude must agree to and implement the shared hook below before Stage B integration passes. No production migration is proposed; if implementation needs one, stop for a separately reviewed RED runbook. Real activation still requires OUT-7/8/9/13 and independent legal/provider/domain evidence. Imported unknown-mailbox history stays blocked, consistent with Mike's OUT-5 legacy-inbox decision.

**Affected systems** Stage A documentation/backend tests only. Future backend approval service, metering, email adapters and existing outreach tables; no frontend work here.

**Security & data risk** Stage A synthetic tests/documentation are authorised. Delivery is RED: tenant isolation, authority and plan enforcement plus irreversible external contact. Mike reviews the behavioural contract/tests; Claude independently reviews security and owns shared approval changes. No Stage A result authorises sending.

**Acceptance criteria**

1. `aria_actions.propose(..., 'send_outreach', ...)` builds from tenant-scoped campaign + enrolment + sequence step + prospect, validates the relationships and current sequence version, and stores an immutable preview. It never sends. Approval requires the owner identity supplied by the authenticated boundary and the exact preview hash. Missing/wrong/expired/edited versions fail. NULL user fails even with a forged or enabled automation payload; no manual approval confers authority on another step.
2. Bind the campaign's exact `email_accounts.id`, provider and From identity. Never select the business/brand default or newest account during proposal, execution or bookkeeping. Caller-supplied mailbox/recipient/business overrides fail. Foreign IDs, mismatched enrolment/step, disconnected account and unsupported SMTP refuse without fallback or foreign-data disclosure.
3. Inside the claim transaction re-read entitlement (`outreach`, using the shared auth gate, not product-name or founder-name guesses), pause-all, campaign ready/running state and versions, enrolment due step/takeover, prospect eligibility/corporate subscriber, approved current LIA tied to brand/target, exact-address valid fresh verification, notice/source/privacy and retention. Tenant-wide email/domain suppression applies across every brand/campaign. Imported or unverified address history cannot grant eligibility.
4. Immediately before claim, search the campaign mailbox for mail from the exact normalised prospect address since the last accepted outreach message. Use AUTO-2 provider `search_from`, not inbox message counts or the default inbox. With no predecessor use capture time, and also check already recorded tenant/prospect replies. Any inbound from that prospect blocks regardless of classification, thread or body availability; self mail is excluded by sender identity. Incomplete/failed search fails closed. Do not call `chase_replies.find_replies` or `_store` inside the claim: they commit. Record search time and dispatch time in bounded action result/audit metadata; a reply arriving remotely after the search remains an acknowledged race. OUT-7 owns ongoing ingestion/classification, not this synchronous check.
5. Recheck connected tenant-owned mailbox, enabled state, current aligned health evidence (daily), complaint/pause state and warm-up. Effective mailbox cap is the minimum of warm-up, configured and provider limits: 5 per UK sending day for five accepted sending days, then 10 for five, then 20 only after owner health review. Unknown holds capacity but does not advance warm-up. Business cap is at most 20/day across mailboxes/campaigns; lower owner/campaign limits win. Accepted + reserved + unknown occupy capacity. Reconnect/new campaign/month cannot reset a daily count or promote warm-up.
6. Reserve the business monthly allowance through `services/metering` and `usage_meters`, not an independent outreach monthly total. Default email allowance 500 accepted messages/month; 200 is researched prospects, not emails. No overage. The usage-event ledger identifies/resolves operations; daily usage holds business/mailbox day aggregates. All initial/follow-up/bespoke sends eventually share capacity, although bespoke delivery is OUT-7. Lock shared capacity and contact state, reserve and conditionally claim in one transaction. Losing a claim or failing any hook check rolls back every reservation.
7. Weekdays 09:00 inclusive–17:00 exclusive Europe/London, DST-aware. Follow-ups require accepted predecessor, due step, 5 then 7 business-day delays and at least seven calendar days since the prospect's last contact across campaigns (later bound wins). No catch-up burst. Freeze UK period/date at dispatch reservation; rebook unclaimed work if the period changes; settle dispatched work in its original period, including unknown reconciliation.
8. Logical key derives from tenant + enrolment + sequence version + step, not action UUID or a click. Two cards for that operation cannot send twice. Persist message/job/reservation and action claim before transport. Call the mailbox-bound adapter once. Crash after claim, ambiguous timeout/5xx or persistence failure after possible send holds capacity, marks unknown where possible and never retries, even after lease expiry/restart. A durable claimed-but-unsettled job is conservatively unknown after a crash. Definite rejection releases once but does not reopen the old card. Acceptance counts once even without provider ID; thread-dependent follow-up stays blocked until correlation.
9. Accepted results link `outreach_messages` and `email_outbox` to the actual bound mailbox and action; preserve provider/thread/RFC references. Outbox is a projection, never the authority to send. Generic `_bookkeep_email`'s newest fallback must never run for outreach. Settlement and generic meter increment are one idempotent transaction; bookkeeping failure cannot turn an accepted send into a retryable failure.
10. Exact approved To/CC, subject, body, AI sign-off, sender disclosure, privacy/source notice and opt-out footer reach transport. Only allowlisted unsubscribe headers are permitted; no model-chosen From/credentials/header injection. Opaque random token (at least 256 bits) maps via stored digest to tenant + recipient digest. HTTPS `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, with readable body link. Public GET confirms without mutation; valid POST is idempotent, requires no login/cookie, suppresses that tenant prospect across campaigns and cancels unclaimed work. Forged/revoked tokens cannot mutate any tenant. Token raw value never stored in token table or logged; the approved payload necessarily contains the public link and follows OUT-13 retention.
11. Extend existing tenant-scoped OUT-4 projections for message outcomes and used/reserved/remaining usage when implementation lands, grounded against seeded meters/events. No raw tokens/credentials in tools. Preserve existing AUTO behaviour and tests. No direct model-provider client is required.

**Required tests** This Stage A file exercises real proposal/approval entrypoints with SQLite fixtures and fake providers: valid bound-mailbox send; foreign/injected IDs; fresh approval checks; tenant-wide and other-tenant suppression; reply/failing search; missing/wrong/edited/expired version; NULL-owner forgery; revoked entitlement; daily/monthly caps; DST/window; reentrant double approval; unknown and definite rejection; accepted-without-ID; rollback after reservation; exact headers/token; unsubscribe; predecessor search/thread; cross-campaign spacing; both provider identities; metering delegation and owner warm-up review. The fake transport opens a separate DB connection to assert durable action, reservation and dispatch claim before any send.

The marker is `xfail(strict=True, raises=MissingOutreachSend)`; only `find_spec('services.outreach_send') is None` raises that custom exception. Schema setup runs before the guard. Missing attributes/dependencies, broken imports and assertion failures are real failures once the module exists; successes are strict XPASS until Stage B removes the marker. No blanket ImportError/AttributeError xfail. Socket connections and the generic sender are denied before implementation import.

**Verification** `PYTHONDONTWRITEBYTECODE=1 ./check.sh`; targeted `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_outreach_send.py -q`; `git diff --check`. No push; future authorised push requires `./check.sh full`.

**Likely files** Stage A exactly this packet and `backend/tests/test_outreach_send.py`. Stage B proposed `backend/services/outreach_send.py`, metering extension and provider adapters/tests; Claude alone edits the shared `aria_actions` hook/registration/dispatch path. API/tool wiring and OUT-4 projection extensions need explicit Stage B scope. No models/create_all changes.

**Builder** Codex (outreach); Claude (shared approval hook, separately coordinated).

**Reviewer** Claude Code for outreach; Codex independently reviews Claude's shared hook. Neither is sole approver of their own RED changes. No review has been claimed or message sent on Claude's behalf.

**Branch** `ticket/OUT-6-outreach-send`, isolated `/Users/michaelrickards/dev/bh2-OUT-6`; initial status had only untracked `data.db`.

**Budget band** M Stage A; L complete OUT-6, re-estimate if provider wire work or a migration expands scope.

**Max repair cycles** 3, then escalate.

**Completion evidence** Final `PYTHONDONTWRITEBYTECODE=1 ./check.sh` exited 0: 4 passed, 0 failed, 1 skipped (eslint has no lint script). Backend: 2,617 passed, 251 skipped, 63 xfailed, 220 subtests passed. All 63 new cases xfail only on the precise absent module. TypeScript, Python compilation and Ruff passed. Local whitespace check passed. Only the two authorised files were added; pre-existing untracked `data.db` remains. No network, real email, production access, commit or push. SQLite/expected failures do not verify an implemented send path, PostgreSQL concurrency or provider wire behaviour.

**Status** proposed — Stage A packet/tests ready for review; implementation not authorised by this document.

**North Star** P4 owner-decided actions, P8 trustworthy outcome reporting, P9 tenant isolation, P2 grounded usage; Actions & permissions and Tool layer pillars. Correctness/security prerequisites precede activation.

### Exact shared-hook proposal for Claude

This is a proposal against Claude's OUT-2 agreement, not a claim that a hook exists or that Claude has accepted this signature:

```python
# Implemented by outreach, invoked only by trusted aria_actions registration.
def prepare_claim(session, business, *, action_id: str, payload: dict,
                  user_id: str, version: str, moment: datetime) -> None:
    ...
```

Keep public `approve(session, business, action_id, user_id, version=None)` unchanged. Claude adds server-side action-type registration (no caller-supplied callback), outreach mandatory-version/owner checks, invokes `outreach_send.prepare_claim`, and routes the stored payload to the outreach dispatcher. Resolve the function at call time so failure injection tests can wrap it. Reject automatic outreach even if unrelated invoice-chasing permission is enabled.

Order: validate scoped card/version/expiry; acquire shared business settings/capacity lock, monthly meter row, business day, mailbox/day, prospect/enrolment, then action row in one documented consistent order shared by pause/suppression and future OUT-11. Re-read all gated records under those locks. Hook performs complete bounded provider **read-only search** and all outreach checks, creates one reservation/message/job, and returns None without changing the approved payload. Then the existing conditional proposed→executing UPDATE must still match tenant, payload and expiry; commit once. Any exception or lost conditional UPDATE rolls back the entire transaction. Only after commit may dispatch run. No hook commit/rollback, nested session, provider send or silent payload regeneration. Recheck current time after the search before reserving, so crossing the window/expiry is refused.

The search holds transaction locks for its bounded timeout: intentional fail-closed tradeoff for this manual pilot; no provider send is made under locks. Claude should review lock order/deadlock risk before implementation. Suppression/public POST must use the same tenant/contact ordering. A suppression committed before claim wins; a claim committed first may already be in flight and cannot be recalled.

Outreach proposed seams used by tests:

- `now()`; `get_provider_for_account(account)` (the existing provider factory exposed locally for injection).
- `suppression_digest(business_id, kind, value)` computes the versioned tenant-scoped digest; tests supply synthetic values only.
- Adapter `send_outreach(*, account, operation_key, to_emails, cc_emails, subject, body_text, body_html, rfc_message_id, in_reply_to, references, provider_thread_id, headers)` returns `{outcome, mailbox_id, provider, provider_message_id, provider_thread_id, rfc_message_id, accepted_at, error_code}`. Outcomes are `accepted`, `definitely_not_accepted`, `unknown`; an exception after dispatch is unknown. Production adapters must implement genuine Gmail threading/MIME and Graph reply/draft semantics, not merely rename today's `send_email`.
- `unsubscribe(session, *, token, method)` supplies the public handler's service boundary; token determines tenant, never request tenant input.
- Proposed metering seam `reserve_outreach_usage(session, business, *, operation_key, mailbox_id, prospect_id, message_id, moment)`: owns allowance/cap locking and reservation with no commit. Companion `settle_outreach_usage(session, business, *, operation_key, outcome, evidence)` commits/releases/holds idempotently, also no commit. Exact return types/internal meter reservation representation belong to the metering implementation review, not a second allowance counter.

The synthetic approved `template_text` uses a proposed versioned JSON text envelope `{schema_version: 1, subject, body}`; its hash binds those exact stored bytes. No existing write API is assumed. Stage B must agree this representation with template/UI ownership before accepting drafts.

Builder args are only `campaign_id`, `enrolment_id`, `step_id`. Builder resolves prospect, brand, template and exact mailbox and freezes `campaign_version`, `sequence_version`, template/target hashes, recipient, CC opt-in, provider/From, final copy/sign-off/footer, RFC/thread references, expiry, time window and `idempotency_key`. Plaintext transport joins the preview `body`, `sign_off` and `footer` with two newlines, without regenerating copy. Existing `version_of` hashes the entire stored payload; relevant database edits invalidate it at approval rather than changing the message unseen. Subject/body edits create a fresh version; address/sender/relationship edits require a fresh proposal. First five cards (or all if fewer) are individually approved like every later card: a completed first-batch review is not a prerequisite to approving the first card, and never grants standing authority.

Hook tests assigned to Claude: positive reservation visible before dispatch; reservation-then-refusal rollback; lost conditional claim rollback; mandatory outreach version/NULL-owner rejection; second approval while executing; action-type isolation and unchanged invoice chase/manual task behaviour. This file includes the first two and outreach entrypoint cases. Claude adds common-service regression and PostgreSQL concurrency tests alongside hook implementation; no parallel edit of `aria_actions.py` by Codex.

### Fixture coverage and remaining gates

SQLite extracts 037's column declarations into local tables, with JSON/arrays represented as text and key operation uniqueness added. It deliberately does not simulate RLS, composite foreign keys, triggers or PostgreSQL row locks. Read/write tenant predicates remain observable even when malformed local rows are seeded. A green xfail run means the scaffold is valid and the implementation is absent, **not** that sending works.

Before Stage B completion, add genuine two-session PostgreSQL tests for F07/F09/F11 last-slot races and lost-CAS rollback; duplicate logical cards; crash after claim/acceptance and settlement failure; reconciliation twice; original-period/month rollover; warm-up accepted-day progression and restart; both follow-up delays; token revocation/cross-tenant substitution and cancellation across multiple campaigns; notice/source/health evidence failure; owner authorisation at the API boundary; OUT-4 usage grounding. These are implementation/review gates, not passed Stage A claims.

F08 wire fixtures must inspect Gmail raw MIME/threadId and Graph reply/draft requests, including CC, RFC References, header preservation and accepted 202 without ID. The current Stage A fake verifies the application adapter envelope for both provider names; it does **not** prove those wire formats, DKIM signing, deliverability or live provider behaviour. Exact official provider evidence and authorised signed-message tests remain external gates; no network allowed here. F12/13 enrichment credit semantics remain OUT-10; F17 answer slots OUT-7; F02 standing-permission/revocation suite OUT-11. F16 ongoing bounce/complaint ingestion belongs to OUT-7; OUT-6 refuses an already paused/unhealthy mailbox and owns unsubscribe.

### Review action and questions

Mike: no new app screen to click in Stage A. Open this packet and review the behavioural test cases, especially no automatic sending, campaign mailbox, unknown outcome hold and no-retry rule. Future authorised pilot click path: open one campaign card, verify From/To/copy, approve once, then inspect mailbox-attributed history/usage; queue another card and opt out before approval, which must refuse it. UI and real-send verification are not performed here.

No new product decision is needed to finish Stage A; the defaults are already agreed. Before Stage B, Mike's RED test approval and Claude's exact hook agreement are outstanding. Sender/domain/header evidence, real-send approval and retention activation remain later gates. Do not reopen OUT-5's unknown legacy-mailbox mapping or OUT-11 grant expiry here.

### Claude's agreement on the shared hook — 23 October 2026

**Agreed, with one change.** `prepare_claim(session, business, *, action_id, payload, user_id, version, moment) -> None` is registered server-side for `send_outreach` and called inside `approve`'s transaction, before the conditional claim. It doesn't commit or roll back. Any exception, or a lost claim, rolls back everything. Dispatch only after commit, and the public `approve` signature is unchanged.

**The change: no network call while holding locks.** The provider reply search does **not** run inside the locked transaction. A slow provider would hold the capacity, settings and prospect locks, stalling other approvals and settings saves. Instead:

1. **Before the transaction:** `outreach_send.search_before_claim(...)` runs the complete, bounded `search_from` on the campaign mailbox (failing closed), stores what it found through the AUTO-2 path, and returns the search moment.
2. **Inside the transaction:** `prepare_claim` takes the locks in the documented order, then re-checks from the database only. That includes any reply stored since the search moment, suppression, caps, window and entitlement.
3. **The remaining gap** is a reply that arrives between the search and the provider accepting the send. It's the unavoidable window OUT-2 §3 already accepts, and it's recorded as such.

**Ownership:** Claude implements the hook in `aria_actions` (registration, mandatory version for outreach, refusing a NULL-owner outreach approval), plus its common-service regression and Postgres concurrency tests. Codex reviews them. Codex implements `outreach_send`.

**Test impact:** any Stage A test that expects the search inside `prepare_claim` is re-expressed in Stage B as "search before, then re-check under the lock". The assertions (fail closed, reply blocks the send) stay.

### Mike's approval — 23 October 2026

The Stage A tests are approved, including the change that moves the search outside the locked transaction. Stage B is authorised: Codex builds `outreach_send`; Claude builds the shared hook.

### Stage B builder handoff — 23 October 2026

**Status:** implemented locally for Claude's review; shared-hook integration,
PostgreSQL verification and production adapters remain gates. Mike's approval
above authorises this implementation. No commit, push, network, real send or
production SQL. Only the four permitted files changed; existing `data.db` is
untouched. Serves P4, P8, P9 and P2/correctness.

**Implemented:** `backend/services/outreach_send.py` supplies `build_payload`,
`search_before_claim`, `prepare_claim`, `dispatch`, and `unsubscribe`.
`backend/services/metering.py` adds outreach-only reservation/settlement helpers.
No change to `aria_actions.py`, provider files, schema, API routes or read tools.

**Exact integration contract for Claude:**

```python
payload = outreach_send.build_payload(session, business, args, owner_name=owner_name)
# Persist the payload and card together, then commit, as for other proposals.
# On approval, first validate authenticated owner, scoped proposed card, exact
# version and expiry. Do not regenerate payload or permit automation.
search_at = outreach_send.search_before_claim(
    session, business, action_id=action_id, payload=payload)
# Same Session, new transaction; search_at is audit information, not authority.
outreach_send.prepare_claim(
    session, business, action_id=action_id, payload=payload,
    user_id=user_id, version=version, moment=outreach_send.now())
# Conditional proposed -> executing claim, including tenant/payload/expiry.
# On ANY exception or lost CAS: rollback all reservations. Otherwise commit.
result = outreach_send.dispatch(
    session, business, action_id=action_id, payload=payload)
```

`search_before_claim` ends its preliminary read transaction before provider
I/O. It must not be called with pending application writes. It invokes AUTO-2
`search_from`, requires a complete list, then AUTO-2 `_store` commits the inbox
observations outside the claim transaction. Search errors fail closed. A
same-session receipt binds action ID, exact payload hash, search start and
lower time bound; it expires after two minutes. Claim consumes it and rechecks
stored inbox messages and outreach replies, including those inserted after
search. `prepare_claim` never calls providers, commits, rolls back or opens
another session. It returns None. Dispatch must immediately follow the claim
commit on the same Session **without starting another transaction first**.
It consumes a one-use in-memory permit and durably fences the job before I/O.
A restarted process cannot obtain that permit: unresolved durable claims hold
capacity and are conservatively unknown, never retry candidates.

`dispatch` owns its settlement transaction and returns `status` (done, failed,
executing), `outcome`, `search_at`, and `dispatch_at`. Claude must bypass generic
email dispatch/bookkeeping and generic success/failure finalisation for this
result. Unknown is executing, even after a transport exception or projection
failure. The dispatcher stores action result, message/provider references,
mailbox-attributed outbox and metering together. No provider ID still counts
as acceptance, but cannot support a threaded follow-up. Meter settlement is
idempotent and allows unknown -> terminal reconciliation, in the original UK
month/day; reconciliation must also update message/job/action projections in
its transaction, not call the dispatcher again.

**Lock order:** shared `business_settings` then `outreach_settings`; current
business entitlement row; shared monthly metering advisory/row locks; business
then mailbox daily rows; account/mailbox state; prospect/enrolment;
campaign/step/brand; compliance/evidence; action last. All reads carry tenant
predicates. Settlement takes the shared settings lock before meter/daily and
mailbox state; unsubscribe takes the same settings lock before token/contact
and pending actions. Claude must coordinate pause/settings/suppression writers
on this order. The business-wide lock serialises operation uniqueness and
shared capacity, including absent daily rows; database unique constraints
remain the backstop. No lease expiry releases capacity or authorises replay.

**Meter decisions:** `usage_meters.outreach_emails_sent` is accepted usage;
`outreach_emails_reserved` holds reserved + unknown usage. Their sum may not
exceed 500; no overage or separate monthly aggregate. Events freeze their UK
period and local date, identify one logical operation, and settle exactly
once. Business and mailbox daily aggregates include accepted/reserved/unknown;
campaign cap checks events joined to its messages. Five accepted sending days
promote stage 5 to 10; another five and explicit owner health review are needed
for 20. Unknown never advances warm-up. Lower configured caps continue to win.
Health evidence may include a lower `provider_daily_cap`; otherwise the pilot
ceiling is 20, not a claim about a provider's externally verified quota.

**Configuration/representation:** approved templates use the packet's exact
version-1 JSON text envelope; stored-byte SHA-256 is rechecked. No rendering or
model call is added. Template/UI ownership must use this same representation.
`OUTREACH_SUPPRESSION_SECRET` must be at least 32 characters and shared with
address verification/import writers: v1 HMAC-SHA256 over
`v1:{business_id}:{kind}:{normalised_value}`. Current prospect email_key must
match the exact address; old verification cannot follow an edited address.
Key rotation/multi-version migration is not activated by this change.
`OUTREACH_UNSUBSCRIBE_BASE_URL` must be HTTPS and point to the future public
handler. Neither setting has a production default. Tokens have 256 random
bits; only SHA-256 and recipient binding enter the token table. GET confirms
without mutation; POST derives tenant from the token, checks revocation under
lock, suppresses once and cancels pending cards/jobs for the recipient. Cards use the existing `dismissed`
status (with an unsubscribe reason); pending jobs use `cancelled`. The local
fixture now enforces 035's action status CHECK as well.

Existing Gmail/Graph providers **do not implement `send_outreach`**. Search
preflight refuses adapters without that method before any reservation. The
service uses the packet's adapter envelope; it does not silently call
`send_email`. Production wire adapters, public endpoint wiring, OUT-4 usage
projections, retention activation and live delivery remain outside these four
allowed files. This is not an end-to-end send feature or activation approval.

**Test changes, with assertions preserved:** the former module-absence xfail
is removed. A thin local transaction seam persists a real payload, calls
search, then the real claim, conditional action update/commit and dispatcher;
it never replaces eligibility, reservation, settlement or transport logic.
All existing assertions remain. Search-order cases now exercised through that
seam are:

- `test_reply_search_at_approval_blocks_even_unclassified_reply`
- `test_complete_search_failure_is_not_an_empty_inbox`
- `test_disconnected_campaign_mailbox_never_falls_back`
- `test_followup_searches_since_actual_predecessor_and_preserves_thread`
- `test_claim_hook_reservations_roll_back_if_hook_fails`

The entitlement-revocation case now changes the database record rather than
only mutating the caller's object, proving the fresh database gate. Fixture
recipient digest now uses the real v1 synthetic HMAC, and the fixture includes
business entitlement and AUTO-2 inbox tables. No assertion was weakened.
Added direct tests cover the database-only claim/no commit/no rollback,
reply arriving after search, missing search receipt, all-reservation rollback,
duplicate logical cards, crash/restart refusal, original-month reconciliation
twice, projection failure after acceptance, changed-address verification,
self-mail exclusion, revoked tokens, missing adapters, window crossing, both
follow-up delays, warm-up progression and unclaimed-card cancellation.

**Still strict-xfailed, reason exactly `awaits Claude's aria_actions hook`:**

- `test_version_is_mandatory` (None, empty, wrong-version: 3 cases)
- `test_edited_card_invalidates_old_approval`
- `test_expired_card`
- `test_no_null_owner_even_with_forged_standing_permission`
- `test_double_approval_during_transport_and_after_completion`

These seven cases keep the real `aria_actions` path. Only absent outreach
registration raises `MissingSharedHook`; once registered, implementation or
assertion failures are real failures and passing cases become strict XPASS
until Claude removes the marks. Other cases explicitly test the service seam,
not the absent shared hook.

**Claude's PostgreSQL verification:** run genuine two-session last-slot races
for monthly/business/mailbox/campaign caps; duplicate-card/operation races;
lost action CAS and hook-exception rollback of messages/jobs/events/meters;
concurrent pause/suppression/token revocation versus claim; lock order and
missing-row insertion; native UUID/text-array/JSONB/timestamptz binding and
037 composite FKs/version triggers. Verify midnight/month/DST reservation and
unknown settlement, accepted-day promotion across restarts and multiple
messages on one day, crash after claim/before transport/after acceptance, and
projection/settlement failure without replay. SQLite does not establish these
properties on PostgreSQL. Shared owner/API authorisation and unchanged AUTO
behaviour need Claude's hook regression tests. Provider wire fixtures must
still establish Gmail MIME/threadId and Graph reply/draft/header behaviour.

**Mike's behaviour check:** no new screen or live-send test is available in
this worktree. After hook, adapters and pilot approval, use the previously
specified campaign-card From/To/copy -> approve once -> history/usage path,
and opt out before approving another card. No real email has been sent here.

**Stage B completion evidence:** final `PYTHONDONTWRITEBYTECODE=1 ./check.sh`
exited 0: **4 passed, 0 failed, 1 skipped** (no eslint script). TypeScript,
Python compilation and Ruff passed. Backend: **2,692 passed, 251 skipped,
7 xfailed, 220 subtests passed**. Targeted OUT-6: **75 passed, 7 xfailed**.
The added current-card-hash tests also reject subject CRLF and arbitrary
headers; claim checks the allowlisted unsubscribe headers and stored token
binding. `git diff --check` passed. The only untracked files are the new
permitted service and the pre-existing `data.db`. No integration, PostgreSQL,
provider-wire, visual or live-send verification is claimed by this result.

### Claude's aria_actions hook, and Claude's review of Stage B — 23 October 2026

**Hook (`backend/services/aria_actions.py`)**, as agreed above:
- `send_outreach` is in `ACTION_TYPES`. Chat and voice use the new `CHAT_ACTION_TYPES`, which leaves it out, and `propose_from_chat` refuses it. Only a campaign raises an outreach card, never the model.
- `propose` refuses `automation` or `raised_by` for outreach, and rolls back on a refused build, so no unsubscribe token is left pending.
- `edit` can change only the subject (one line, at most 998 characters) and the body (1–20,000 characters). It never rebuilds, which would mint a new unsubscribe link.
- `approve` routes outreach to `_approve_outreach`:
  - a signed-in owner and the exact version are required;
  - automation markers are refused;
  - order: `search_before_claim` (no transaction); then one transaction with `prepare_claim` and the `proposed → executing` claim; then commit; then `dispatch`;
  - any refusal or lost claim rolls back every reservation and drops the dispatch permit;
  - generic `_execute` and `_bookkeep_email` are never used.
- The seven strict-xfail cases now pass through the real path. Their marks are gone, replaced by a `real_aria_actions` fixture that keeps them on the real path. Eight hook tests were added.

**PostgreSQL (`backend/tests/test_outreach_send_rls.py`).** These run against the local harness with 035, 036 and 037 replayed: real types, foreign keys and triggers, and the real path. All six pass:
- one send with native `text[]`/JSONB, the meters settled and the job completed;
- two taps on one card at once: one send;
- two cards for one recipient at once: one send;
- the last monthly slot (499 + 2 at once): exactly one;
- a lost claim rolls back events, messages, jobs, daily rows and meters;
- unsubscribing before approval stops the card.

Mutation checks, with the code restored afterwards:
- With every lock off, the last-slot race sends two and fails.
- With only the business-wide locks on, it passes.
- Same-card races are held by the claim and the unique keys even without locks.
- Pre-created daily and meter rows stop insert conflicts from masking the race.

Not covered here: DST and month-boundary settlement on Postgres, crash after acceptance, provider wire fixtures. Those stay as gates for the adapter ticket.

**Claude's review of Stage B — APPROVE, no P1.** Backlog (P2):
1. `prepare_claim` loads every inbox message since the last contact into Python to look for a reply. This is correct but grows with the inbox; filter by sender in SQL.
2. The sending window ignores UK bank holidays.
3. An unsubscribe landing between the claim commit and `dispatch` (milliseconds) is not rechecked. `dispatch` could take `lock_business` and recheck suppression before fencing.
4. Unsubscribe tokens from cards that were never approved are never revoked. They still unsubscribe correctly, which is the safe direction.

**Codex hook review 1: REQUEST-CHANGES, one P1 (repair cycle 1).** Any authenticated member could approve. **Fix:** `_is_active_owner`, which requires `business_members.role = 'owner'` and `is_active` for this business. It is checked before the reply search, so nothing is searched for a non-owner. It is checked again inside the claim transaction holding the membership row (`FOR SHARE`), so ownership removed during the search stops the claim. Tests cover staff, an inactive owner, a platform admin (no membership), another business's owner, demotion during the search, and staff on Postgres.

Review backlog, also done:
- the race helper now fails on any crash, hung worker or missing outcome;
- a real second-session dismiss during the claim waits on the row lock and loses with 409.

Still backlog: daily-cap (business/mailbox/campaign) races and pause/suppression races on Postgres.

Review preserved verbatim: `audits/OUT-6-HOOK-CODEX-REVIEW-1.md`. Postgres: 8 pass. Codex's sandbox cannot reach the loopback harness; Claude ran it.
