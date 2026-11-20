# OUT-28: outreach you can read at a glance and change at any time

**Tier:** Part A is RED, because it changes what is sent to whom. Part B is AMBER, UI only. **Builder:** Claude. **Reviewer:** Codex. **Tests first** for Part A.

## Why (Mike, 18 Nov 2026)

- "Outreach seems to be finding prospects, but not offering up many emails to approve and send."
- "What does 'rejected' mean?"
- The prospects tab is "lots of cards" showing long IDs.
- The outreach section must be clear to "someone who doesn't build or understand apps and software", and "beautiful", inspired by HubSpot and Pipedrive.
- It "needs to be easier to edit outreach emails at any time … being able to update an outreach email to improve performance at any time is essential."

**Mockup, approved by Mike on 18 Nov ("Yes, build it"):** https://claude.ai/artifact/Xd2v8Ad2MHFZfh6R2wABa9. It covers Home, Prospects and Emails. Replies and Settings follow the same style.

## What we found (production, 18 Nov)

- **New Body sent nothing after 11 Nov.**
  - All 3 of its emails still contain "[Your Name]", so cards are refused (OUT-25).
  - 5 enrolments have been waiting since 6–13 Nov, and they hold the day's room.
  - Nothing told the owner.
- **Editing wording stranded everyone part way through a campaign.** The cause, in the code:
  - enrolments are pinned to `sequence_version`;
  - `outreach_send` requires enrolment == campaign == step version;
  - editing (`outreach_manage.sequence`) created version n+1 and left every enrolment on version n.

  Had Mike edited New Body's or MSC's emails, those 5 and 9 people would never have been emailed again, silently.
- **The editor itself was jargon:** "Save new sequence version", "Approve these displayed templates (v3)", fields dumped as `key: value`.

## Decided by Mike (18 Nov 2026)

- **E1.** After an edit, people already part way through get the **new** wording from their **next** email. Emails already sent never change.
- **E2.** "Save and use from now on" is **one tap**: saving approves the wording the owner has just written. Placeholders are still refused.
- **E3.** If Aria was sending the campaign automatically, she carries on with the new wording.

## Part A: edit any time (this PR, RED)

**A1. `outreach_manage.save_emails`, via `POST /v1/outreach/campaigns/{id}/emails`.** One transaction, by an active owner, with the version checked. It:
- writes the 3 emails as the next sequence version, already approved by that owner (E2);
- keeps the gaps between emails (0 / 5 / 7 working days);
- sets the campaign to `ready`;
- refuses an empty subject or message, a missing email, a placeholder (422) or curly brackets (the API model);
- moves every `pending` or `active` enrolment to the new version, at the same step and due time (E1);
- leaves replied, paused, stopped, completed and suppressed enrolments alone;
- withdraws every waiting (`proposed`) card of the campaign that was made from older wording (status `dismissed`), so a fresh one is made;
- refuses with 409 while one of the campaign's emails is being sent (`executing`): "Try again in a minute";
- if the campaign has an automatic-sending grant **from this same owner**, with the same sender, **and still valid for the campaign as it was** (same campaign and sequence versions: Codex review 1, finding 1), moves the grant to the new campaign and sequence version (E3, `automatic: "on"`). Anyone else's grant is left to lapse, as OUT-11 already does on a change (`automatic: "off"`), and the screen says so.
- **Locks in the send path's order** (`prepare_claim`):
  1. `lock_business` (the settings rows);
  2. the business row and owner membership (`_locked_authority`);
  3. enrolments;
  4. the campaign;
  5. cards last.
- After it commits, the endpoint calls `prepare_due_cards` straight away, so cards appear immediately instead of at the next hourly pass. This is best effort: a failure never undoes the save.

**A2. The wizard's two-step path does the same.** `approve_templates` (save, then approve) now moves people part way through to the approved version and withdraws cards made from older wording, under the same lock order. Re-approving the **same** version keeps waiting cards.

**A3. `outreach_manage.emails`, via `GET /v1/outreach/campaigns/{id}/emails`.** For each email it returns:
- the subject and message;
- the gap before it;
- any placeholder found;
- **results for each wording it has had**: sent (provider-accepted `initial` and `followup` only; Aria's `bespoke` answers to replies never count, per Codex review 1, finding 4), replied (distinct people), interested (`interested` or `referral`), and the date that wording started.

It needs outreach (with retained history) and is scoped to the business.

**A4. The Emails tab (`OutreachEmails.tsx`):**
- the campaigns as cards, with a plain status: Sending, Waiting for your approval, or Not started;
- the 3 emails as readable cards: Email N, when it's sent, subject, a preview, and results now and for earlier wordings;
- **Changes to all three emails build up into one save** (Codex review 1, finding 2): New Body's three "[Your Name]"s are fixed one by one, then saved once. A bar at the bottom lists what still needs fixing, each with a **Fix** button, alongside **Discard changes** and **Save and use from now on**.
- **The save uses the snapshot taken when editing began** (review 1, finding 3): its three emails and its version (`lib/outreachEmailDraft.ts`). If the emails change elsewhere meanwhile, saving is blocked with a plain warning, and the server would refuse it anyway (409).
- **Edit** opens an inline editor:
  - placeholder and curly-bracket warnings as you type (the server's check is final);
  - **Ask Aria to improve it**, which uses the existing redraft endpoint and saves nothing until the owner chooses "Use this version";
  - **Save and use from now on**, after which the screen says how many people get the new wording next and whether automatic sending carried on.
- The old sequence editor is removed from campaign settings, which now points to the Emails tab.
- Tabs get plain names: Home, Prospects, Emails, Replies, Opt-outs, Settings. The paths are unchanged.

## Part A fix: migration 044 (20 Nov, RED)

**Production, 19 Nov.** Mike's first save on New Body returned 500. The error was:

`ForeignKeyViolation outreach_messages_business_id_campaign_id_sequence_version_fkey`

- **The cause:** 037 tied every email record to its contact's current wording version, so a contact with any email history (New Body's 2 failed sends, MSC's sent emails) could not move.
- **Why the tests missed it:** the SQLite suite enforces no foreign keys, and the PostgreSQL test contact had no email history before the save.
- **What changed:**
  - **Migration 044** (`audits/044-PROD-RUNBOOK.md`) drops that one constraint. An email record still names its contact and still must match the exact wording it was sent with (`…_fkey1`).
  - **New PostgreSQL tests** use real send-path history (accepted and failed). They failed with the production error before 044 and pass after it.
  - The screen shows the server's plain-words reason for any refusal (`lib/outreachErrors.ts`).
- **Codex fix review 1 requested changes**, and all of them were made:
  - **Finding 1, the trigger.** 037's `outreach_bind_message_version` reset a message's version to its contact's current one on every update. After a move, any update of an old message (outcome settling, reply matching, erasure) would have hit the step key. 044 now binds only on insert, or when the message is re-pointed to another contact.
  - **New PostgreSQL tests, run on a fresh harness:**
    - failed send → edit → deadline erasure works;
    - old messages can still be updated and keep version 1;
    - the next email after a failed send and an edit sends the new wording;
    - 5 of these fail with the old trigger.
  - **Finding 2, matching.** Constraints are matched by their columns (`conkey`/`confkey`), not by printed text. An unexpected version key, or a missing contact or step key, stops the migration.
  - **Finding 3, wording.** A 5xx now says "We couldn't confirm the result" rather than "nothing was saved".
  - **Finding 4, the harness.** `scripts/rls-local.sh up` now replays 040–044.
- **Codex fix review 2:** findings 1, 3 and 4 were confirmed resolved. It requested changes for:
  - **finding 2:** the kept keys are now checked on both sides (`confkey` too);
  - **finding 5:** the binding trigger must be attached and enabled for INSERT and UPDATE, or the migration stops. This is mutation-checked: a disabled trigger is refused.
  - The runbook query shows the referenced columns and the trigger's live state.

## Part B: the redesign (next PR, AMBER)

Built to the mockup:
- **Home:**
  - a "Needs you" call to action ("5 emails are ready: Review and send");
  - **why nothing is sending, in plain words**: placeholder, paused, mailbox health, no ready campaign, warm-up cap reached, outside sending hours;
  - 4 numbers;
  - the pipeline;
  - Aria's research as "looked at N, added N, passed over N", with reason counts;
  - warm-up progress showing when the cap rises.
- **Prospects:**
  - a summary strip;
  - filter chips by stage, and search;
  - a compact paginated table: company, contact, where they are, what's next;
  - a side drawer: why Aria picked them, the email timeline, and outcome buttons;
  - **no IDs**.
- **Replies and Settings** in the same style, with opt-outs folded into Settings.
- "Rejected" is renamed "passed over" everywhere, and check that "today's quota is full" candidates are banked rather than discarded.

## Acceptance

### Part A

- [x] `test_outreach_edit_any_time.py`: 48 tests on SQLite, with the real send path.
  - After a save, the person's next email is sent **with the new wording**. Before this ticket, the same test could never send.
  - Old cards are withdrawn.
  - Stopped people, other campaigns and other businesses are untouched.
  - Sent emails are unchanged.
  - Placeholders, staff, out-of-date pages and malformed bodies are refused, and nothing changes.
  - The grant carries for the same owner only.
  - Per-wording results count only accepted emails.
  - The wizard path moves people too.
- [x] 14 mutations, each removing one rule, are each caught. Review 1 added 2 more (a lapsed grant, bespoke counting), and both are caught.
- [x] `test_outreach_email_draft.py`: the editor's draft logic, bundled with esbuild and run under Node.
  - New Body's three placeholders are fixed in one save.
  - The snapshot version is the one saved.
  - Out-of-date drafts are detected.
  - 4 mutations, all caught.
- [x] `test_outreach_edit_any_time_pg.py`: 2 tests on the local PostgreSQL harness.
  - A save on Postgres: native jsonb, and the next email sent with the new wording.
  - A save racing an approval at the shared lock: never stuck, never stale wording.
    - In every run (6 of 6) the approval won and the save was refused with "sending right now".
    - The deadlock the lock reorder guards against was **not** reproduced: the test passed with the old order too. The reorder is argued from `prepare_claim`'s order, not proven by this test.
- [x] `./check.sh full` is green, and the production build passes.
- [x] Codex review 1 preserved (`audits/OUT-28-CODEX-CODE-REVIEW-1.md`): it requested changes, and all 4 findings were acted on.
- [x] Codex review 2 (`audits/OUT-28-CODEX-CODE-REVIEW-2.md`): findings 1–4 confirmed resolved. It requested changes for:
  - **finding 5:** the Node test's temporary entry file. It is now created exclusively, under a unique name, and only that file is removed;
  - **its note on finding 4:** a test now sends Aria's answer through the real reply path, and the per-email results are unchanged. The test is mutation-checked.
- [x] Codex review 3 (`audits/OUT-28-CODEX-CODE-REVIEW-3.md`): APPROVE.
- [ ] Mike: edit one email on MSC or New Body, and see "N people will get the new wording from their next email".

### Part B

- [ ] Home, Prospects, Replies and Settings match the mockup and work at phone width.
- [ ] No database IDs anywhere on the outreach screens.
