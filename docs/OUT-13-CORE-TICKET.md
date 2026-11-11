# OUT-13 core — erase a never-contacted contact from every outreach record, at the cutoff

**Design approved by Codex: design review 4 (`audits/OUT-13-CORE-CODEX-DESIGN-REVIEW-4.md`), after reviews 1–3.** Read Revision 3.1, then 3, then 2; each supersedes the later sections where they differ.

**Asked for:** Mike, 10 Nov 2026. This is step 2 of his order: OUT-24 → **OUT-13 core** → the OUT-23 prospect bank → Hunter → running low. The bank (OUT-23) deletes contacts still unsent at day 28. Codex's two design reviews of the bank (`audits/OUT-23-CODEX-DESIGN-REVIEW-1.md`, `-2.md`) showed that deleting properly means deleting **everywhere**, which is the "never contacted" slice of OUT-13 (OUT-1 design: retention and erasure, required before launch).

**Also closes a live gap:** today a researched contact whose card is never approved is kept for **365 days** (`retention_due_at`), with no notice ever given.

**Decided by Mike:** an erased company may be found again after **90 days** (a tenant-keyed digest guard until then).

---

## Revision 3.1 (after `audits/OUT-13-CORE-CODEX-DESIGN-REVIEW-3.md`: findings 21, 22 and three qualifications)

**U1. Fairness by separate budgets (finding 21; replaces T5's cooldown rule).**
- **New candidates:** past the deadline and with **no** exception row. They get the pass's main budget (up to 120 s), in keyset order.
  - A new candidate that cannot be erased becomes an exception at once, so it never blocks the next one.
  - New candidates can therefore never be starved by exceptions.
- **Exception re-checks:** a separate, fixed budget of at most **20 per pass**, the least recently checked first, each at most once a day.
- **Tests:**
  - 30 passes' worth of permanently blocked prospects **already recorded as exceptions**, ahead of one new candidate, with the clock advanced past every cooldown: the new one is reached in the first pass.
  - A prefix **not yet classified**, larger than one pass: every pass makes forward progress, each blocked prospect gains its own exception, and cooldown expiry never interrupts that classification (Codex design review 4).

**U2. Only initial sends are reconciled (finding 22).**
- T3 selects only jobs whose card is a sequence email (`action_type = 'send_outreach'`).
- A reply's unstarted claim is left to the reply path's own safeguards (its slot constraints in migration 038). The prospect is contacted anyway, so it is never an erasure candidate.
- **Test:** a committed reply claim whose dispatch never began is untouched by T3.

**U3. Qualifications Codex noted.**
- **T1 holds for every repository-created prospect** (`_store` writes both timestamps from one moment, at 30 days, soon 28), but the schema allows other values. So the deadline is computed in code as `min(notice_due_at, captured_at + 28 days)`, with NULL meaning `captured_at + 28 days`.
- The candidate predicate is `captured_at <= :now - 28 days OR notice_due_at <= :now`, with a partial index for each (`WHERE notice_provided_at IS NULL`).
- **T2:** dispatch's mailbox check after its compare-and-set can raise before settlement. That job then has a marker but no transport. It is conservatively a `may_have_sent` exception (T4), never erased, and listed for the owner. "Never left claimed" is therefore narrowed to "never sent after the deadline".
- **T7:** incoming references checked also include **dispatch jobs** of other prospects naming one of these cards (037's independent job-to-card foreign key).
- **T3:** the fence and the settlement commit in **one** transaction.

## Revision 3 (after `audits/OUT-13-CORE-CODEX-DESIGN-REVIEW-2.md`; it supersedes Revision 2 where they differ)

**Title correction (review 2, item 4):** this erases a never-contacted contact from **every outreach record**. It does not reach Aria's chats or memory (Mike's boundary), Railway logs, backups, or the AI model provider. An owner's chat that fetches outreach data persists in Aria's reply, by that boundary.

### T1. The deadline is simply `captured_at + 28 days` (findings 16, 17)
- Every stored `notice_due_at` is 30 days (old) or 28 days (new). Neither is ever earlier than `captured_at + 28 days`, so the effective deadline is always exactly `captured_at + 28 days`.
- **There is no backfill.** Migration 041 changes no prospect.
- **The code deploy is the switch.** There is no window in which a migrated deadline meets old code.
- During a rolling deploy, an old process can still send under the 30-day rule for the minutes it runs. That is stated, not hidden; no contact is erased by old code.
- **Index:** `(captured_at, business_id, id) WHERE notice_provided_at IS NULL`, matching the work-list's order and predicate exactly (T5).

### T2. Send admission at the deadline (finding 16)
`first_send_allowed` (`notice_provided_at` set, or `now < captured_at + 28 days`) is checked in three places:
1. the claim;
2. card creation (`build_payload(one_card=True)`, before the token);
3. **`dispatch`'s existing under-lock recheck block**, which re-reads the prospect with a fresh clock.

In dispatch, a failure there takes the **existing** `blocked` path. The job's `dispatch_started_at` is set, nothing is handed to the provider, and it is settled `definitely_not_accepted`, "Stopped before transport". Job, message, card and usage all reach their terminal states through `_settle`, as any blocked send does today. A first email can therefore never leave after its deadline, and a blocked one is never left `claimed`.

### T3. A claim that never reached transport: fenced, then settled (finding 14)
**`reconcile_abandoned_claims`**, under the business lock, takes jobs that are:
- `claimed`, with `dispatch_started_at IS NULL`;
- created more than **1 hour** ago (a claim is dispatched within seconds of its commit; the lease column is unused and is not relied on).

**For each such job:**
1. **The fence:** the same compare-and-set the dispatcher uses, `UPDATE outreach_dispatch_jobs SET dispatch_started_at = :at WHERE id = :id AND status = 'claimed' AND dispatch_started_at IS NULL`.
   - If it changes no row, the dispatcher won and nothing more is done.
   - If it changes one, any paused or resumed dispatcher **loses** its own compare-and-set (`require(claimed.rowcount == 1)`) and raises **before** transport.
2. **Then** `_settle(... {'outcome': 'definitely_not_accepted', 'reason': 'Interrupted before sending started'})` sets the terminal job, message (`failed`), card (`failed`) and usage (`released`), exactly as a blocked send does.

**Tests:**
- both lock orderings;
- a dispatcher paused between its prechecks and its compare-and-set resuming after reconciliation: it raises and never calls the provider;
- running reconciliation twice is idempotent.

### T4. Uncertain sends are kept, never decided by the owner (finding 15)
- `dispatch_started_at` set and not settled, or the message `unknown`, means it **may have been sent**. It is **never** made erasable by elapsed time or by an owner's tap.
- The owner sees it as a classified exception (T6) with its age: "Sending may have happened: Business Hero is waiting for confirmation". There is no "It wasn't sent" button.
- The existing reconciliation (provider evidence) is the only thing that resolves it. If the email was sent, the first email carried the notice, so keeping the contact is lawful.

### T5. The work list makes progress across passes (findings 17, 19)
**Table `outreach_erasure_exceptions`** (migration 041; RLS on, no client grants):
- columns `(business_id, prospect_id, reason, first_seen_at, last_checked_at)`, unique per prospect;
- reasons: `may_have_sent`, `contacted`, `cross_reference`, `orphaned_card`, `error`.

**The candidate query:**
- `notice_provided_at IS NULL AND captured_at <= :now - 28 days`, and **not** already an exception last checked in the past 24 hours;
- ordered by `(captured_at, business_id, id)`, returning all three for the keyset, in pages of 100, with a 10-second statement timeout on the page query.

**Each candidate:**
- its own transaction, with `lock_timeout = '5s'` and `statement_timeout = '15s'` per statement;
- a 30-second total budget, checked between steps; when it is exceeded, the transaction rolls back and is recorded as `error`;
- a candidate that cannot be erased is upserted as an exception with its reason, so the next pass passes over it, and it is re-checked daily.

**Fairness:** a permanently blocked prefix never starves the rest. The pass stops at 120 s; the next pass starts from the beginning but skips exceptions checked within 24 hours, so it reaches new candidates.

**Monitoring:**
- **actionable backlog:** candidates past the deadline, not exceptions, and the oldest one's age;
- **exceptions:** counted by reason, separately;
- an actionable oldest above 3 hours is an alert.

**Cleanup:** pruning of `outreach_recently_erased` and of exceptions for prospects that no longer exist runs in bounded `DELETE … LIMIT`-style batches.

### T6. Every blocked erasure is owner-visible (finding 19)
**The outreach dashboard** lists exceptions by reason and age:
- `may_have_sent`: waits for provider confirmation; no owner action.
- `cross_reference`: another contact's message refers to this one. Resolution: an erasure-repair step, under the lock, nulls the other message's `retry_of`/`reply_target_id` **only** when that message is itself never sent (`draft`, `proposed`, `cancelled`, `failed`). Otherwise it stays, as evidence of contact.
- `orphaned_card`: an executing card with no job. It is reported for support; it never decides a send.
- `contacted`: notice given. It is no longer a candidate, and the exception is dropped.
- `error`: retried daily; after 3 days it is escalated in the daily briefing.

### T7. Deletion order (finding 13)
**The full deletion set is found first:**
- the cards (by payload enrolment, **and** by every `action_id` on the prospect's messages and jobs);
- the never-sent messages, their jobs, and their usage events;
- the tokens, enrolments and evidence.

**Then any incoming reference to that set from outside it is checked:**
- a reply slot or message of another prospect naming one of these cards;
- another prospect's message naming one of these messages.

Any such reference makes it a `cross_reference` exception (T6). Nothing is deleted.

**Then, in order:**
1. dispatch jobs are deleted;
2. `outreach_usage_events.message_id` is nulled;
3. the prospect's own messages' `retry_of` and `reply_target_id` are nulled;
4. messages are deleted;
5. **then cards** (no foreign key points at them any longer);
6. tokens, enrolments, evidence, and the prospect;
7. the `outreach_outcomes` entry is removed, in the same transaction, and the guard rows are upserted.

There is one commit. A PostgreSQL test covers a prospect with a failed message referencing its card and job, and a second prospect referencing it.

### T8. Lock without an outreach settings row (finding 18)
`outreach_erasure._lock(session, bid)` locks `business_settings` if it exists, then `outreach_settings` if it exists, in the documented order, **without creating either**. Erasure never provisions settings. Tests cover a business missing each row.

### T9. Remaining items from review 2
- **Chat logging (item 8):** `assistant_chat` stops logging **tool arguments** as well as results (only the tool name and sizes).
- **Read boundary (item 5):** the ticket states plainly that a signed-in member's direct table SELECT is outside the app. It is bounded by physical erasure, except for T6 exceptions, which are kept and listed.
- **Screens (finding 20):**
  - projections carry each contact's `deadline`, and the frontend hides any item whose deadline has passed **by the browser's clock**, before and regardless of a refetch. This covers the contact detail, stage lists, dashboard and home cards, so a stale or failed fetch cannot keep showing it;
  - polling every 5 minutes refreshes the rest;
  - tested with a cutoff crossed during a failed fetch and on an already-open contact detail.
- **Guard (item 12):** `digest_version = 1`; only unexpired rows match (`until > now`); an index on `(until)` serves pruning.
- **Removed:** the Revision 1 tests that redact chats and memory, so they cannot reintroduce it.

## Revision 2 (after `audits/OUT-13-CORE-CODEX-DESIGN-REVIEW-1.md`, 12 findings)

**Mike's decision, 10 Nov 2026:** automatic erasure covers **outreach records only**. Aria's chat history and memory notes are the owner's own business records. They are cleaned on an erasure request (OUT-13's request flow), not by automatic redaction, which Codex showed can miss mentions, corrupt unrelated text, and be undone by a reply in flight. Findings 3, 4 and 9 are answered by this boundary. Finding 8's logging point is fixed anyway (R8).

### R1. Four separate predicates, one module: `outreach_erasure` (finding 1)

**`deadline(p)`**
- `notice_due_at`, never later than `captured_at + 28 days`.
- Migration 041 backfills `notice_due_at = LEAST(notice_due_at, captured_at + 28 days)` for every prospect without `notice_provided_at`. A NULL becomes `captured_at + 28 days`.
- New contacts are stored at 28 days (`NOTICE_WITHIN`).
- After that, the deadline is the column alone, which can be indexed.

**`first_send_allowed(p, moment)`**
- `notice_provided_at IS NULL` ⇒ `moment < deadline(p)`.
- Checked at the **claim**, which replaces today's `notice_due_at` check with the same column now backfilled.
- Checked again **immediately before transport** in `dispatch`, with the prospect re-read and a fresh clock after every lock wait. This applies to a first email even though its own claim and executing card exist.
- **Follow-ups** (`notice_provided_at` set) are exempt. **Retention** is always enforced, separately.

**`erasable(session, bid, prospect_id)`** reads the related tables. It is false if any of these exist for the prospect:
- a message in `accepted`, `imported`, `claimed` or `unknown`;
- an `executing` card;
- any reply or reply slot;
- `notice_provided_at` set;
- an incoming `retry_of` or `reply_target_id` from **another** prospect's message (finding 7).

**`hidden(p, moment)`** = `notice_provided_at IS NULL AND moment >= deadline(p)`. It holds whatever the erasure state.

The words "notice has been given" are dropped (finding 2). The rules only **preserve** a prospect whose contact may have happened, and say so.

### R2. Stuck first sends (finding 2)

**A claim that never reached transport** has its job `claimed` with `dispatch_started_at IS NULL`, and its lease expired more than an hour ago. That is proof nothing was handed to the provider. `reconcile_abandoned_claims` cancels it, under the business lock and with the send path's own settlement:
- the message becomes `cancelled`;
- the usage reservation becomes `released`;
- the card becomes `failed` with "Sending was interrupted before it started".

It is then ordinary and erasable at the deadline.

**A claim that may have reached transport** (`dispatch_started_at` set, or the message `unknown`) is never inferred. It is an **owner-visible exception**:
- the owner sees: "1 email may or may not have been sent: check your Sent folder";
- it has its age, and two taps: "It was sent" (the message becomes `accepted`, notice recorded) or "It wasn't sent" (`failed`);
- it is retained until the owner decides, stated as the one retention exception;
- after 7 days it is escalated in the daily briefing.

### R3. Hidden at the deadline: the whole read boundary (findings 5, 6, 10)

The browser reads outreach **only through the API**. No `supabase.from('outreach_…')` or `from('aria_actions')` exists in `frontend/client/src`. So the API boundary is the boundary. Direct table SELECT by a signed-in member is outside the app and is bounded by physical erasure (R5).

**At `hidden(p)`:**
- **Cards:** `aria_actions.get`, `list_open` and `_view` show a `send_outreach` card whose prospect is hidden as "This contact's deadline passed", with no recipient, body, source or link. It cannot be approved.
- **Prospect and evidence projections:** `outreach_read` and `outreach_dashboard` (pipeline, contact record, stage lists) omit the prospect's personal fields, including the evidence `source_url` and excerpt, whatever the evidence's own `expires_at`.
- **Card creation:** `build_payload`'s `one_card` path, under the business lock and **before the token is made**, refuses with "This contact's first email is past its deadline" (`first_send_allowed`). This covers scheduled preparation, the autopilot and direct proposals; `qualified()` keeps its own message.
- **Open screens:** the outreach dashboard, stage list and home cards refetch every **5 minutes** (`refetchInterval`), and on window focus. A tab left open shows a hidden contact for at most 5 minutes.

### R4. The candidate work list (finding 11)

**Migration 041** (RED; runbook; staging first):
1. backfills `notice_due_at` (R1);
2. adds `CREATE INDEX … ON outreach_prospects (notice_due_at, business_id, id) WHERE notice_provided_at IS NULL`;
3. adds the guard table (R6).

**Each pass:** `SELECT business_id, id FROM outreach_prospects WHERE notice_provided_at IS NULL AND notice_due_at <= :now ORDER BY notice_due_at, id LIMIT 200`, in keyset pages after `(notice_due_at, id)`.
- Each candidate is its own transaction: `SET LOCAL lock_timeout = '5s'`, `statement_timeout = '30s'`.
- A candidate that is not erasable, or fails, is passed over by the keyset, never retried in the same pass, so nothing starves behind it.
- A pass stops after 120 s and resumes next hour.

**Schedule:**
- the hourly pass, every day, for every business, whatever its pause, entitlement or settings row;
- it runs **first** in the automations pass, before any provider-dependent work such as research;
- recovery after downtime is the same query.

**Monitoring:** each pass logs counts, plus the oldest overdue candidate's age in hours, never names. An oldest-overdue above 3 hours is an alert. The bound is a monitored target.

### R5. The erasure transaction, revised (findings 7, 8)

Under `send.lock_business`, re-checking `erasable` under the lock:
1. **Cards:** the prospect's cards, found by payload `enrolment_id`, **and** by every `action_id` on its messages and dispatch jobs, are **deleted outright**, whatever their status.
   - Nothing that is kept references them: reply slots exist only for contacted prospects, and the messages and jobs go in this transaction.
   - This replaces the redacted audit row, which Codex noted is still linkable by ids and timestamps.
2. **Never-sent messages** (`draft`, `proposed`, `cancelled`, `failed`):
   - their dispatch jobs are deleted;
   - `outreach_usage_events.message_id` is nulled; the metering fact stays, unlinked, and a released reservation never counts;
   - self-references *among the prospect's own* messages are nulled first;
   - then the messages are deleted.
3. Unsubscribe tokens with the prospect's `prospect_key_digest`, then enrolments, evidence, and the prospect row.
4. **Settings document** (one fresh locked read, one write, no intermediate commit). The prospect's entry in `outreach_outcomes` (the dashboard's marked outcomes) is removed, and the guard rows are written (R6).
5. **Commit once.** Any error rolls back everything. A test injects a failure after each step.
6. **Suppressions are never deleted.**

**Inventory corrections (finding 8):**
- `assistant_chat` no longer logs tool results (only a tool name and size), so researched contacts never reach Railway logs from chat.
- "Provider copies" means the **mail** provider: none for never-sent mail. The AI model provider receives whatever the owner discusses in chat, under its own terms (the chat boundary above).
- Stored research summaries are sanitised: emails and domains are stripped from the stored `summary` on every research save, and by the first erasure pass for each business. That is in code, under the settings lock, not SQL on JSON.

### R6. The re-collection guard, in its own table (finding 12)
- **Table:** `outreach_recently_erased (business_id, key_type ('email','domain'), key_digest, digest_version, until)`, `UNIQUE (business_id, key_type, key_digest)`, RLS on, no client grants (migration 041).
- **Writing:** on conflict, `until = GREATEST(until, :until)`.
- **Matching:** null or empty email or domain is skipped; values are normalised as `send.suppression_digest` does.
- **Checks:** at verification and under the store lock.
- **Pruning:** `DELETE … WHERE until < now()` on every erasure pass, for all businesses, so idle ones are pruned too.
- **Size:** it is bounded by erasures in 90 days and kept out of the settings document and the send path's hot reads.

## (Revision 1, superseded where Revision 2 differs)

## C1. Words (one definition, used everywhere)

**Contacted.** The prospect has an `outreach_messages` row in `accepted` or `imported`, or any `outreach_replies` or `outreach_reply_slots` row, or `notice_provided_at` set. Notice has been given.

**Unresolved.** A message in `claimed` or `unknown`, or a card in `executing`. A send may have happened. It is never erased; it waits for reconciliation.

**Never contacted.** Neither contacted nor unresolved.

**Cutoff** = `min(notice_due_at, captured_at + 28 days)`, so it also applies to prospects stored before this change, which have `notice_due_at` at 30 days. New contacts get `notice_due_at = captured_at + 28 days` (`NOTICE_WITHIN`).

**Past cutoff** = never contacted and `now >= cutoff`.

## C2. Hidden at the cutoff, before any deletion (OUT-23 design review 2, finding 3)

One function, `outreach_erasure.past_cutoff(prospect, moment)`, is used by every reader and writer:

- **Enrolling and preparing:** `outreach_manage.qualified()` refuses with "This contact's first email is past its deadline". It covers manual enrolment, preparation and the drain.
- **Sending, first email:**
  - the claim refuses, as today (it checks `notice_due_at`);
  - **new:** `dispatch` re-checks, with a fresh clock, immediately before transport, for a first email only. Follow-ups keep the `notice_provided_at` exemption, and retention is always enforced (review 2, finding 4);
  - approving a card past the cutoff is refused, and the card expires.
- **Reading:**
  - `outreach_read`'s projections (Aria's tools) and `outreach_dashboard` (pipeline, contact record, stage lists) omit a past-cutoff prospect's personal fields, as expired retention already does (OUT-4 item 7);
  - the frontend refetches on its usual polling, so no new cache is introduced.

## C3. Erasure: `outreach_erasure.erase_never_contacted(session, bid, prospect_id, moment, reason)`

It runs under the business lock (`send.lock_business`), in **one transaction**. It re-checks "never contacted" under the lock; if contacted or unresolved, it does nothing and returns why.

**Cards:** every `aria_actions` row whose payload names one of the prospect's enrolments, whatever its status (proposed, dismissed, expired, failed, done-but-not-sent):
- `payload` becomes `{"redacted": "OUT-13", "enrolment_id": …}`;
- `result` and `error` are nulled;
- a proposed card becomes `expired`.

The row stays as a bare audit trail: no recipient, no body, no link.

**Unsubscribe tokens:** rows with the prospect's `prospect_key_digest` are deleted. They were only in cards that were never sent.

**Messages that never left** (`draft`, `proposed`, `cancelled`, `failed`), each with its dependencies:
- its `outreach_dispatch_jobs` row is deleted;
- `outreach_usage_events.message_id` is set to NULL. The metering fact is kept, but no longer names the person; a `released` event never counts;
- then the message is deleted. Self-references (`retry_of`, `reply_target_id`) are handled within the prospect's own messages first.

**Then:** enrolments, then evidence, then the prospect row are deleted.

**Suppressions are never deleted.** An opt-out survives erasure (OUT-2 F19).

**The re-collection guard** (C5) is written in the same transaction.

**Aria's memory** (`business_settings.settings.aria_memory`): any entry whose `about` or `meaning` contains the prospect's email address, or their full name together with their company, is deleted. This goes through `aria_memory`'s own locked read-modify-write.

**Aria's chat** (`assistant_messages` for this business): the exact email address, and the full name where the company also appears in the same message, are replaced with `[erased contact]`. This is a best-effort redaction of known identifiers. The ticket says so: free text can mention a person in other ways, and OUT-13's subject-request flow covers what remains.

**Research summary text:** `summary()` already carries counts and reason labels only. Labels are now normalised to a fixed vocabulary, so no domain or address is ever persisted in it.

**Not covered, by design, and documented:**
- Railway logs (retained by Railway; no personal data is logged deliberately, and log lines are reviewed);
- database backups (Supabase point-in-time; OUT-13's backup policy);
- the provider's own copies (none for never-sent mail).

## C4. The schedule: `outreach_erasure.run_due(session, moment)`

- **When:** every hourly automations pass, **every day, weekends included**.
- **For whom:** every business, **whatever** its pause, entitlement or inbox state.
- **What:** for each prospect past its cutoff, `erase_never_contacted`. Each prospect is its own transaction, so one failure never holds the rest. There is no day-claim: the query *is* the work list, so a failed pass is simply retried next hour.
- **Bound:** a contact is erased within about an hour of its cutoff. Until then it is already hidden (C2).
- **Logging:** counts per business only, never names. Skipped (unresolved or contacted) counts are logged, and unresolved ones are shown to the owner as "1 contact waiting for a send to be confirmed".

## C5. The re-collection guard, for 90 days (decided by Mike)

- **What is kept:** `send.suppression_digest(bid, 'email', email)` and `(bid, 'domain', domain)` of each erased contact, with an `until` 90 days ahead. They are stored in the research config, `recently_erased`, and pruned on each research run and each erasure pass.
- **What it is:** pseudonymous, not anonymous, and documented as such. Its purpose is to avoid re-collecting someone just erased.
- **Where it is checked:** in research at verification, and **again under the store lock**, for eligible and review-held candidates alike. This closes the race in which erasure deletes and records while a search for the same company is mid-flight.
- **Separate from opt-outs:** permanent suppression is unchanged.

## C6. Not in OUT-13 core
- Erasure of **contacted** prospects, their messages and replies.
- The subject-access and erasure request flow.
- Engaged-lead retention.
- Backup and provider deletion.

These remain OUT-13 proper, a launch gate.

## Tests first (RED: deletion of personal data)
- **`past_cutoff`:**
  - both cohorts: old 30-day `notice_due_at`, new 28-day;
  - a null `notice_due_at` falls back to capture plus 28 days;
  - a follow-up after day 28 for a contacted prospect is still allowed.
- **Hidden:** read tools and the dashboard omit fields at the cutoff; enrolment, preparation and approval are refused; dispatch refuses a first email whose claim was made before the cutoff.
- **Erasure:**
  - removes the prospect, evidence, enrolments, tokens and never-sent messages, nulls the link on usage events, and redacts every card status;
  - suppressions remain;
  - memory entries go, and chat mentions are redacted;
  - a contacted or unresolved prospect is untouched and reported;
  - the bare audit rows contain no email, name or company (asserted by scanning every column).
- **Schedule:** weekends, a paused business, an unentitled business; a failure on one prospect does not stop the others; it is retried next pass.
- **Guard:** re-collection is blocked at verification and under the store lock (a race test on PostgreSQL), and allowed after 90 days.
- **PostgreSQL:**
  - erasure against concurrent approve, prepare, unsubscribe and research store, with no deadlock (the documented lock order);
  - foreign-key order on a prospect with messages, dispatch jobs and usage events.

---

## Implementation (against Revision 3.1)

| Design | Code |
|---|---|
| Predicates (T1, U3) | `services/outreach_erasure.py`: `deadline` = min(notice_due_at, captured_at + 28 days); `first_send_allowed`; `hidden`; `contacted_ids` (any accepted, imported, claimed or unknown message, or a reply; never hidden or erased, even without a notice date) |
| Send admission (T2) | The claim (`outreach_send.prepare_claim`), card creation (`build_payload(one_card=True)`, before the token), dispatch's under-lock recheck with a fresh clock (the existing blocked path), and `outreach_manage.qualified`. New contacts are stored at 28 days (`NOTICE_WITHIN`). |
| Interrupted claims (T3, U2) | `reconcile_abandoned_claims`: sequence-email jobs only, over 1 hour, `dispatch_started_at IS NULL`; the dispatcher's own compare-and-set as a fence, then `_settle(definitely_not_accepted)`, in one transaction |
| Uncertain sends (T4) | `assess` returns `may_have_sent`; there is no owner override |
| Work list (T5, U1) | `run_due`: prune; reconcile; scrub stored summaries; new candidates in keyset pages (main budget); at most 20 exception re-checks (separate budget); oldest-overdue logged, with a warning above 3 hours. Wired **first** in `automations.run_all_due` (hourly, every day). |
| Owner view (T6) | `exceptions_for`; the dashboard's "Needs you" lists held erasures by reason and age. An unsent cross-reference is repaired (`_repair_references`). |
| Deletion order (T7) | jobs → usage unlinked → own self-references → messages → cards → tokens → enrolments → evidence → prospect → outcome entry → guard; one commit; an error records `error` and rolls everything back |
| Lock (T8) | `_lock` takes existing rows only, never creates settings |
| Logging (T9) | `assistant_chat` logs tool names and sizes only |
| Read boundary (R3) | `aria_actions._shown` (every card view), `outreach_read._withhold_past_deadline` (prospect, evidence including source URL, timeline), `outreach_dashboard.stage_list`; `withhold_at` is sent with each record and card |
| Screens (T9) | `lib/outreachWithhold.ts`, applied in `useOutreachData`'s select, `ApprovalCard` and `StageDialog`; 5-minute `refetchInterval` on the outreach, dashboard and card queries |
| Guard (R6) | `outreach_recently_erased`, checked after verification and again under research's store lock (eligible and review alike) |
| Migration 041 | Two partial indexes and two backend-only tables. Runbook `audits/041-PROD-RUNBOOK.md`, rehearsed (apply, rollback, apply) on the local harness. The schema record gained the 16 columns by hand, as 039's did. |

**Tests:**
- `test_outreach_erasure.py` (26): predicates, erasure, hiding, the guard, scheduling and fairness.
- `test_outreach_send.py`, OUT-13 section (8): the deadline at the card, approval and dispatch; follow-ups; interrupted claims, including a fenced dispatcher.
- `test_outreach_erasure_pg.py` (4): foreign-key order, contacted, uncertain, and backend-only tables.
- Mutation-checked throughout.

**Not testable here:** the frontend has no unit runner. The browser-clock rule is type-checked, and its server half is tested.

## Codex code review 1 — CHANGES REQUESTED (7), all fixed
1. **Contacted imports starved the work list.** A contacted prospect without a notice date is now recorded as a `contacted` exception, never shown to the owner as a problem. The new-candidate query skips it. Test: 25 imported contacts ahead, budget-limited passes with a fake clock; the never-emailed one is erased.
2. **Housekeeping took the candidates' budget.** Prune, reconciliation and summary scrubbing share a separate 30 s budget. The candidates' 120 s starts after it. Scrubbing reads only documents with research config, at most 50 per pass. Test: reconciliation stuck for "10 minutes"; the overdue contact is still erased.
3. **Uncertain sends stayed visible.** `contacted_ids` (what stays visible) now means accepted or imported, or a reply. Claimed or unknown remain protected from erasure (`assess`) but are withheld. Test: a claimed send past the deadline has its card withheld and is not erased.
4. **The browser clock didn't advance.** `useClockTick` (30 s) gives `useOutreachData` a new `select` each tick, so TanStack recomputes from stale data with no refetch (checked against `@tanstack/query-core`'s `QueryObserver`). `ApprovalCard` and `StageDialog` re-render on the same tick.
5. **Timeouts after a rollback.** `_limits` is re-applied before the error record, and before every scheduler query: reconciliation selection, summary scan, re-check selection and backlog age.
6. **Backlog age.** It uses the effective deadline, the earlier of notice due and capture plus 28 days. Test: a day-20 deadline at day 24 is 96 hours.
7. **No escalation.** `escalations` covers errors after 3 days, uncertain sends and cross-references after 7, and orphaned cards after 3. It goes in the outreach summary, and the Aria home's "Needs you" shows a warning with a link. This replaces T6's "daily briefing": the home is the owner's daily screen. Test: thresholds, with `contacted` excluded.

## Codex code review 2 — all 7 earlier findings resolved; 2 new, fixed
1. **Summary scrubbing could stall behind clean documents.** It now selects only documents still holding the one identifying phrase unscrubbed (`no mail server for <domain>`, the only reason that names a domain). Each document cleaned drops out, so every one is reached. Test: 210 clean documents ahead of one legacy summary; the old query fails it.
2. **`contacted` showed as a dashboard warning.** It is now excluded from `erasure_held` too. Tested.

**Codex code review 3** (targeted): both resolved, none new. **APPROVE.**
