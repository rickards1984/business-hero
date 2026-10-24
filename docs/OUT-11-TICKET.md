# OUT-11 — Auto-approve outreach: Aria sends a campaign's emails once the owner trusts it

**Tier:** RED: automatic customer contact, a standing permission, and changes to the OUT-6 claim. **Builder:** Claude (Mike, 24 Oct 2026). **Reviewer:** Codex. **Tests first, approved by Mike before code.**
**Decision:** Mike, 24 Oct 2026: "Automated outreach needs to come in ASAP … a toggle at the user's end to auto-approve such outreach and stop having to one-tap approve everything when they feel comfortable."

## Behaviour (what Mike will see)
1. **A switch per campaign: "Let Aria send this campaign's emails automatically".** Only the active owner can turn it on. Before it switches on, the owner sees exactly what it allows:
   - this campaign's approved wording only;
   - from its chosen mailbox;
   - within its caps and the warm-up;
   - weekdays 9–5 UK.

   The owner confirms once. The grant is recorded: who, when, and the exact campaign and wording versions.
2. **It unlocks only after the owner has approved the campaign's first 5 emails by hand,** and the provider has accepted them (decision A). Before that, the switch explains how many are still to go.
3. **While it's on,** Aria prepares due emails and sends them **one at a time, spread through the day**: at least 6 minutes apart, plus a random 0–6 minutes (decision C). This is a natural pace, and it never bunches at 9am. Every rule that applies to a tapped email still applies at the moment of sending:
   - the reply check, suppression and opt-outs;
   - pause-all;
   - mailbox health and warm-up;
   - the daily and monthly caps;
   - the sending window.
4. **It switches off by itself** when:
   - the owner turns it off;
   - the campaign's wording or sender changes (decision D: the grant is tied to versions, and the owner re-grants after reviewing the new wording);
   - outreach is paused;
   - the business loses outreach;
   - the owner leaves.

   Each check is read fresh at the moment of sending, so switching off takes effect before the next email, never after it.
5. **Answers to replies are never sent automatically** (decision B). Aria's drafted answers always wait for the owner's tap.
6. **The owner always sees what went:** the home page shows "Aria sent N emails on your behalf today", each card shows *Sent automatically*, and the audit trail records the grant behind each one. Pause-all stops everything at once.

## Contract
- `services/outreach_autopilot.py`:
  - `grant(session, business, user, campaign_id, {"version", "sequence_version"}) -> {"campaign_id", "granted_at"}`: owner-only; requires 5 accepted, owner-approved sends in this campaign; stored in `business_settings.settings["outreach_autopilot"][campaign_id] = {granted_by, granted_at, campaign_version, sequence_version, mailbox_id}`.
  - `revoke(session, business, user, campaign_id)`: owner-only.
  - `status(session, business) -> {campaign_id: {"enabled", "manual_accepted", "needed", "granted_by", "granted_at", "valid", "reason"}}`.
  - `send_next(session, business, campaign_id, *, moment, rng=random.random) -> {"sent": action_id|None, "waiting": reason|None}`: prepares at most one due card and approves it as the standing permission.
  - `run_due(session, *, moment)`: called from the hourly pass, and repeatedly through the window, by the scheduler tick.
  - `valid_grant(session, business, campaign_id, campaign) -> grant | None`: read fresh, and checks versions, mailbox, owner still active and entitlement.
- `aria_actions`:
  - `propose(..., "send_outreach", ..., automation="outreach_autopilot")` is allowed **only** with a valid grant for that card's campaign.
  - `approve(session, business, action_id, None, version)` for a `send_outreach` card carrying that marker re-reads the grant **under lock** and refuses if it's no longer valid.
  - `reply_outreach` never accepts automation.
- `outreach_send.prepare_claim` accepts `automation == "outreach_autopilot"` only with a validated `authority_snapshot` (the grant). It still requires every OUT-6 check, with no exceptions.
- Home: `recent_automated` also lists automatic outreach sends.

## Decisions for Mike (each with a recommendation)
- **A. Earn trust first:** auto-approve unlocks after the first **5** emails of a campaign were approved by hand and accepted. *Recommended* (matches OUT-9).
- **B. Answers to replies stay manual.** *Recommended:* a reply is a conversation, and the owner should see it.
- **C. Pace:** at least 6 minutes between automatic sends from the business, plus up to 6 minutes at random. *Recommended:* it looks human and protects the mailbox.
- **D. Wording change switches it off** until the owner re-grants. *Recommended.*
- **E. Visibility:** a home-page line plus "Sent automatically" on each card. A daily WhatsApp digest can come with the weekly briefing work. *Recommended.*

## Files
- New: `backend/services/outreach_autopilot.py`, `backend/tests/test_outreach_autopilot.py`.
- Edited: `services/aria_actions.py`, `services/outreach_send.py` (Codex's file, a reviewed change), `services/automations.py` (scheduling), `services/home_summary.py`, the outreach API, and `OutreachPage` (the switch per campaign).

No migration.

## Not in this ticket
- Automatic answers to replies.
- Raising the 5-enrolment pilot limit (after OUT-9).
- Any send without the OUT-16 adapters.

## Tests
`backend/tests/test_outreach_autopilot.py`, strictly xfailed until `services.outreach_autopilot` exists. They use the OUT-6 harness (fake provider, no network) and the real `aria_actions` path.

## Mike's approval — 24 October 2026
**Approved:** the tests and decisions A–E, all as recommended ("absolutely approved").

## Build — 24 October 2026 (Claude)
- **Service:** `services/outreach_autopilot.py`: grant, revoke, status, `valid_grant` (read fresh, and under lock inside the claim), `send_next` (pace, window, pause, due enrolment, propose with the marker, approve with no user), `run_due`.
- **`aria_actions`:** `propose` accepts `automation="outreach_autopilot"` for `send_outreach` only with a valid grant. `_approve_outreach` takes the automatic path only for a `send_outreach` card carrying that marker and `user_id=None`; it re-reads the grant after `prepare_claim` (business settings locked) and claims with `approved_by NULL`. Replies can never take it.
- **`outreach_send.prepare_claim`** (Codex's file; a reviewed change): accepts the marker only with a validated `authority`, never for a reply. Every OUT-6 check is unchanged. The authority snapshot records `automation`, `granted_by`, `granted_at`, version and search time. `_settle` now sets `executed_at` on finished cards.
- **Scheduler:** `briefing_scheduler._run_outreach_autopilot_if_due` runs every 2 minutes, off the loop, never two at once. It was edited byte-for-byte, so the CRLF file kept its line endings: +35 lines only.
- **Home:** `recent_automated` lists automatic outreach sends, and the home line says so.
- **Routes:** `GET/POST/DELETE /v1/outreach/setup/autopilot[/{campaign_id}]`.
- **UI:** `AutopilotSwitch` on each campaign shows progress to 5, a confirmation of exactly what it allows, and the off switch.
- **Verification:**
  - `test_outreach_autopilot.py` has **21 passed**;
  - all OUT-6/7/8/10/15, AUTO and home suites give **601 passed**;
  - `./check.sh full` is green, with tsc;
  - Postgres: an automatic send with the grant recorded passes alongside the existing OUT race and isolation suites.
