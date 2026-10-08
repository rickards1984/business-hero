# 0001 — North Star: RC1 decisions, approved sending, fresh data, Aria's identity

**Status:** accepted (decisions); the conditions marked *recommended* are
awaiting Mike's confirmation
**Date:** 2026-09-28
**Decider:** Mike

## Context

`docs/NORTH_STAR.md` was adopted on 28 September 2026. `docs/RC1_SCOPE_PROPOSAL.md`
§E put seven decisions to Mike; `docs/ARIA_GAP_ANALYSIS.md` is the evidence.
Mike accepted all seven recommendations and added three decisions of his own
(D8–D10). The gap analysis and proposal are still under Codex review
(`docs/reviews/REVIEW_REQUEST_aria-gap-analysis.md`); a review finding that
changes the evidence reopens the decision it rests on.

## Decision

### D1–D7 — accepted as recommended in `RC1_SCOPE_PROPOSAL.md` §E

- **D1** Aria stops acting outside the app on her own decision. `send_email`,
  `send_invoice_chase` and `create_calendar_event` stop executing directly
  (`assistant_tools.py:1391`, `:2431`, `:1904`). **D9 amends this:** they
  become draft-and-approve, not draft-only. *After Codex review 1:* refusal is
  enforced at the server's execution boundaries in chat and voice, not by
  removing tools from the advertised lists, and it also covers the two task
  writes. **D11, decided by Mike 28 Sep 2026:** `delete_task` is refused;
  `create_task` goes through the same tap-to-approve card as D9.
- **D13, decided by Mike 28 Sep 2026:** revision 2's larger estimates are
  accepted. The Aria-centred home (proposal B7) is worth the extra time to
  him and is not a casual drop.
- **D2** If Aria voice is broken in production, it is turned off for RC1 and
  repaired (Realtime GA migration) after P0-2 metering. *After Codex review
  1:* "off" means refused server-side before the provider connection opens,
  not a hidden button.
- **D3** Phase 1 items A1, A2 and B1–B8 of the proposal may enter RC1, with
  the entry test: no migration, no new provider call site, never ahead of the
  security sequence.
- **D4** The home briefing is deterministic — built from data, no model call.
- **D5** P9's "enforced by RLS" to be amended to "enforced by business
  scoping, tested per tool, and by RLS on the client path". *`NORTH_STAR.md`
  is Mike's document; the wording change is his to make.*
- **D6** The router allows OpenAI only until the provider/legal question
  (North Star open question 5) is settled.
- **D7** The remaining isolation work is the BH-001 §6 findings (anon-readable
  views, `TRUNCATE` to `anon`, inactive members reading `calls`/`tasks`), not
  "RLS batches 4–5", which BH-001 found already applied.

### D8 — Opening the app always refreshes the business's data

When the owner opens Business Hero, every connected source — email,
accounting, calendar — is brought up to date, so neither the owner nor Aria
works from stale figures. Serves P2.

*Recommended conditions:*
- **Never blocks the app opening.** The pattern already exists for email:
  `POST /v1/email/sync/ensure` (`app/email/router.py:917`) is cache-first,
  schedules a background sync only when stale, and returns instantly. Extend
  it to accounting and calendar. `POST /v1/accounting/sync-all`
  (`main.py:4646`) currently runs synchronously on the request and must not be
  what login waits on.
- **Says how fresh it is.** Every figure shows "updated N minutes ago"; if a
  sync fails the page and Aria say so (the `data_quality` pattern). "Always
  current" cannot be guaranteed when Xero or Google is down; "never silently
  stale" can.
- Calls need no sync — the receptionist writes them as they happen.

### D9 — Aria may send a drafted email once the owner approves it, signed with her name

Aria drafts; the owner approves; the owner may then tell Aria to send it, and
she sends it signed with her name. This applies to email replies and invoice
chases. It brings Phase 2's "approval cards for the first write actions"
forward into RC1. Serves P4.

*Recommended conditions — these are what make it safe:*
- **Approval is enforced in code, not in the prompt.** The draft is stored
  (`email_drafts` already exists in production with `status`, `subject`,
  `body_text`, `to_emails` — no migration expected, grants and RLS to be
  checked). The send endpoint sends only a draft whose status is `approved`,
  and sends exactly the approved text. Any edit after approval returns it to
  draft.
- **The approval is a tap, not a sentence.** "Send it" to Aria brings up the
  final draft with a Send button; the tap is the approval. A model
  interpreting "yes" — or voice mishearing one — is not an approval.
- **Each draft sends once.** The draft id is the idempotency key; chase-send
  has none today (`CURRENT_STATE.md` §7).
- **The sign-off says she is an AI assistant — decided by Mike, 28 Sep 2026
  (proposal D12).** It should sound confident in what she can do and make
  clear that she passes everything on to the owner. It is a template —
  `{assistant_name}`, `{owner_name}`, `{business_name}` — so the D10 name
  flows in. Every line in it must be something the product actually does
  (P8, `AGENTS.md` §9). "Your reply reaches the owner" is true because Aria
  sends from the owner's own connected mailbox. Promises the product does not
  keep yet — reply tracking, response times, "24/7" — stay out. The final
  wording is Mike's choice from the drafts in the B10 ticket.
- Every send is recorded in `email_outbox` (it exists) against the draft and
  the approving user.

### D10 — Owners can rename Aria, choose her voice, and pick an avatar; Aria is the default

Answers North Star open question 2. In settings and as an optional onboarding
step, an owner can change her name, choose her voice with a preview (as the
receptionist voice can be previewed today), and choose one of 2–3 avatar
images. Doing nothing leaves Aria, her default voice and default avatar.

*Recommended conditions:*
- Stored in `business_settings.settings` (JSONB, exists) — no migration.
- One persona first: the name is injected in one place (proposal B4), not
  into three separate prompts, or a rename reaches chat but not the board
  meeting.
- Voice choice reuses the receptionist's presets and preview
  (`services/voice_presets.py`, `receptionist_api.py:612`). Aria's voice is a
  single global setting today (`ARIA_REALTIME_VOICE`, `realtime_voice.py:19`),
  so per-business voice is new, and it matters only once voice works (D2).
- Avatars are bundled, licensed images; no uploads in RC1 (no storage,
  moderation or cross-tenant file-path risk). Illustrated rather than
  photographs of real people, so none implies a real employee.
- Onboarding step is skippable with "Keep Aria" as the default action.
- **The phone receptionist keeps its own identity in RC1 — decided by Mike,
  28 Sep 2026 (proposal D14).** It does not take Aria's name. An option to
  rename the AI receptionist is to be added once there are users asking for
  it. That is post-RC1 and logged in `docs/BACKLOG.md`.

### D15–D17 — calendar booking and removal (Mike, 5 Oct 2026)

- **D15 — Aria books calendar events on approval.** Calendar booking joins
  NS-B10's tap-to-approve card alongside email replies, invoice chases and
  tasks. The booking code exists (`assistant_tools.create_calendar_event`);
  NS-A1 put it behind a refusal, and NS-B10 puts the approval in front of it.
- **D16 — Removing or cancelling events is Phase 2.** No code can delete or
  cancel an event today. Cancelling can notify every attendee and is hard to
  undo, so it is built as its own approval-gated work after booking works.
- **D17 — The phone receptionist books for callers; this is RC1.** Example:
  a caller rings New Body's AI receptionist and books an induction. Booking
  for callers is the business's own public booking service, switched on by
  the owner in booking settings. That setting IS the standing permission P4
  allows, so the receptionist books without asking the owner each time.
  This is unlike Aria acting for the owner, which waits for a tap.
  The receptionist already books (`receptionist_call_handler.py:378`), but
  code review on 5 Oct 2026 found four gaps, now ticket **NS-R1** (RC1):
  1. it books even when booking is switched off — with no enabled settings
     it falls through to a default one-hour slot on the owner's primary
     calendar (`:392-422`);
  2. nothing checks the slot is still free at the moment of booking, so two
     callers, or a skipped availability check, can double-book;
  3. business hours, minimum notice and maximum advance are enforced only
     by the availability check, not by the booking;
  4. the caller's phone number is not stored on the booking.
  Production behaviour is UNVERIFIED until a test call.
  **Caller cancellation and rescheduling by phone is Phase 2, with D16.** It
  needs the caller verified first (their number must match the booking's),
  or anyone could cancel someone else's induction by naming a time — which is
  why NS-R1 stores the caller's number now.

### D18 — approving by voice (Mike, 6 Oct 2026)

For RC1 an approval is a **tap**, as D9 says, even in voice: Aria reads the
draft aloud and the owner taps once. Spoken approval ("confirm send", after
Aria reads it back, recorded in the audit trail) is **Phase 3**, introduced
per action type like the standing permissions. Built for site, not the
desk (§5) argues for it eventually; a misheard "yes" emailing a customer
about money argues against it now.

### D17 addendum — the double-booking cause (6 Oct 2026)

Writing NS-R1's tests found the main cause of double booking, beyond the
four gaps above: availability sent Google UK clock times labelled UTC and
compared Google's UTC answers against UK clock times, so during British
Summer Time every existing appointment was an hour out and an occupied
slot was offered again. Aria's chat availability tool had the same bug.
Fixed in NS-R1 (`backend/services/booking.py`).

## Consequences

- RC1 gains its first Aria write path (D9). It is safer than today — where
  Aria sends with no approval at all — but it is new money-adjacent customer
  contact, so its tests are written first and reviewed by Mike.
- D8 increases calls to Xero, Google and Microsoft on every app open;
  staleness thresholds and the existing `LIMIT_SYNC` rate limit bound it.
- D10 makes "Aria" a default rather than a fixed identity. Marketing still
  leads with Aria (North Star §7).

## Alternatives

- **Draft-only, no sending (the original D1).** Rejected by Mike: the owner
  should be able to have Aria send once approved.
- **Blocking sync at login.** Rejected: a slow Xero call would make the app
  feel broken, which is worse than a clearly labelled cached figure.
- **Free-text avatar upload.** Deferred: storage and moderation for a feature
  most owners will skip.
