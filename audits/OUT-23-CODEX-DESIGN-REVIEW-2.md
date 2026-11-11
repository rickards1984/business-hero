# OUT-23 Part A — Codex DESIGN review 2 (verbatim)

Reviewed docs/OUT-23-TICKET.md revision 2 (design only).

Read-only review completed against North Star P8/P9 and correctness. Nothing modified, committed or pushed. Tests were not run; this is a design review against repository code and migrations, not verified production schema.

Revision 2’s disposition of the original 11 findings:

| Original finding | Resolved? | Assessment |
|---|---|---|
| 1. Unsent enrolled contacts escape expiry | **Partly** | Included now, but A5 still indefinitely excludes several unsent cases and leaves copies behind. |
| 2. Weekday-only expiry | **Partly** | Daily, pause-independent cleanup and transactional completion are correct. Immediate read/enrol enforcement and a defensible cleanup bound remain missing. |
| 3. Notice deadline and dispatch race | **Partly** | New-contact cutoff and fresh dispatch check address the main issues. Existing prospects remain outside 28 days; follow-up semantics need preserving. |
| 4. Unrelated audiences and qualification refusal | **Yes, for eligible banking** | Matching audience required before spend/store; qualification failure is distinguished from no capacity. Review-held handling now conflicts with this rule. |
| 5. Shared-inbox allocation | **Yes, at design level** | Allocation once per inbox, campaign bounds and aggregate brand bound answer the double-counting finding. |
| 6. Unbounded drain allocation | **Partly** | Explicit decrementing budgets fix the original overflow. They still omit send-admission constraints. |
| 7. Exclusion privacy and store race | **Yes, technically** | Pseudonymous digests and locked rechecking address it. The 90-day recollection decision remains explicitly unapproved. |
| 8. Drain authority and transactions | **Partly** | Separate locked drain and post-commit preparation are correct. Entitlement and scheduling details below remain. |
| 9. Card scans and duplicate race | **Partly** | Indexed locked creation is the right approach; its integration with autopilot and `NOT EXISTS` is incomplete. |
| 10. Buffer estimate and health readiness | **Partly** | Estimate wording, separate review stock and hourly retries help. Monthly allowance and total mailbox ceiling remain absent. |
| 11. Spend-cap exception | **Yes** | A3 explicitly preserves OUT-19 H and unchanged provider limits. |

Remaining and newly introduced findings:

1. **P1 — A5 explicitly retains never-contacted prospects indefinitely.**  
   **Where:** [A5](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:101), [dispatch settlement](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_send.py:468).

   **Scenario:** Transport definitively refuses a first email, or the new deadline check stops it before transport. Settlement creates a `failed` message. A5 then keeps the prospect “for OUT-13” on every pass. Likewise, a `draft` or `proposed` message does not prove sending is in progress and need never change state. These contacts remain past day 28.

   **Change:** Include definitively unsent messages and their dependencies in Part A erasure, or make that OUT-13 work a prerequisite. Distinguish temporary execution uncertainty from confirmed non-delivery. Preserve unresolved-send safety, but define reconciliation and an explicit exception policy; retries alone cannot justify “one hourly pass plus one retry.”

2. **P1 — Successful A5 deletion still leaves personal-data copies.**  
   **Where:** [A5’s transaction](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:106), [card dismissal](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/aria_actions.py:947), [assistant message storage](/Users/michaelrickards/dev/bh2-OUT-23/backend/assistant_chat.py:630), [structured memory](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/aria_memory.py:1).

   **Scenario:** The owner dismisses a prospect’s card without sending. A5 deletes the prospect but redacts only **open** cards; the dismissed card retains the recipient, source URL, body and unsubscribe link. A conversation about that prospect can also persist in `assistant_messages`, and owner-confirmed facts can persist in `business_settings.settings.aria_memory`.

   **Change:** Inventory and erase/redact all prospect-linked card statuses and applicable payload/result/error fields, assistant messages and structured memory. Define how copies are identified and how concurrent writers are prevented from restoring them after erasure.

   **FK assessment:** For a genuinely message-free prospect, enrolments → evidence → prospect is valid. Tokens have no prospect FK and need explicit digest-based deletion; cards have no enrolment FK and therefore survive automatically. Expanding erasure to failed messages requires dependency handling for dispatch jobs, usage events, message self-references and, where present, replies/reply slots under 037/038. Do not simply remove A5’s skips and reuse its current deletion order.

   Research summaries are normally aggregate, so they should not be indiscriminately deleted; nevertheless, `summary()` incorporates rejection reasons, and `_verify()` can include a domain in those reasons. Define sanitisation for that persisted text too.

3. **P1 — The cutoff is not enforced on reads or manual enrolment.**  
   **Where:** [A6](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:121), [qualification](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_manage.py:162), [read projection](/Users/michaelrickards/dev/bh2-OUT-23/backend/outreach_read.py:153), [dashboard stage list](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_dashboard.py:328).

   **Scenario:** Cleanup is delayed or repeatedly fails. The prospect’s notice cutoff passes, but its retention deadline remains 365 days away. Manual enrolment still passes `qualified()`, and read tools/dashboard still expose its details. A6 only adds approval/dispatch checks.

   **Change:** Use one effective never-contacted cutoff in read, enrolment, card preparation and send paths. Withhold details immediately at that cutoff, independently of physical cleanup.

   The outreach dashboard is built from live rows, but the frontend caches dashboard, stage-list and action responses under separate query keys. Specify expiry-aware refresh/removal for these views. I found no dedicated persisted outreach briefing cache in the inspected paths; assistant conversation storage is a confirmed persistent copy and must be handled.

4. **P1 — A6 preserves the old 30-day window and risks stopping legitimate follow-ups.**  
   **Where:** [A6](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:122), [research storage](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_research.py:879), [claim checks](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_send.py:321).

   **Scenario:** A prospect collected before rollout keeps `captured_at + 30 days`, so it can receive its first email on day 29 or remain stored until day 30. Conversely, an unconditional dispatch check against `notice_due_at` would stop an already-contacted prospect’s valid follow-up after day 28. The current claim correctly exempts notice already provided.

   **Change:** Define the effective cutoff for existing never-contacted prospects—normally the earlier of the stored deadline and capture plus 28 days—and handle null deadlines explicitly. Preserve the `notice_provided_at` exception for subsequent messages while always enforcing retention. Test both rollout cohorts and follow-ups crossing day 28.

5. **P1 — A4’s allocation is not yet a send-admissible budget.**  
   **Where:** [A2/A4](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:50), [reservation](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/metering.py:782), [cold limits](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/metering.py:855).

   **Scenario:** An inbox has cold capacity remaining but replies have exhausted its provider-bound total ceiling. Alternatively, a brand has exhausted its monthly cold allowance. A4 can still enrol contacts and create cards that sending refuses. Research can continue buying replacement stock against nominal capacity with no currently usable sending allowance.

   **Change:** Bound drain placement by fresh health, remaining monthly brand allowance and remaining total mailbox ceiling, including replies, alongside the proposed cold campaign/inbox/brand budgets. Count each reservation once. Distinguish the nominal bank-sizing estimate from today’s admission budget and expose these blockers.

   Also specify the full growth-entitlement check: `outreach_manage.start()` uses `retained_history=True`; existing mutating growth paths additionally call `growth()`. Copying `start` alone does not authorise new enrolments.

6. **P2 — The stated drain-before-research order does not hold at 06:00.**  
   **Where:** [A4 scheduling](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:76), [research scheduler](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_research.py:1296), [automation ordering](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/automations.py:606).

   **Scenario:** Research still runs once daily from 06:00; drain starts at 07:00. A3 immediately enrols newly researched contacts into free places before older banked contacts receive their first opportunity. Alternatively, if freshness gates research, its committed daily marker can consume the day before health checks run.

   **Change:** Move scheduled research behind the first eligible health/drain pass, with retryable readiness refusal, and make immediate research placement respect existing-bank priority. Merely placing the drain call before research inside the hourly function does not resolve the differing start times.

7. **P1 — A8 does not preserve autopilot authority across selection and card creation.**  
   **Where:** [A8](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:133), [autopilot selection/send](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_autopilot.py:210), [proposal creation](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/aria_actions.py:430).

   **Scenario:** `_due_enrolment()` currently selects without creating a card. `send_next()` subsequently rolls back, commits a pacing reservation, then calls `propose(..., automation=MARKER)`. Making selection call a generic find-or-create operation can create a manual card that blocks automatic sending, or leave the later unconditional proposal creating a second card. A concurrent manual preparation can also win after the `NOT EXISTS` scan.

   **Change:** Treat `NOT EXISTS` as candidate filtering only. Perform the authoritative recheck and creation under one business lock through commit, at the actual proposal point. Explicitly distinguish manual and automatic authority; autopilot must stand down when a manual card wins, and must not leave ordinary approval cards during candidate selection. Cover this interleaving in PostgreSQL tests.

   Separately, filtering manual `prepare()` entirely through `NOT EXISTS` removes its existing `result['existing']` behaviour. Preserve that response with an indexed join or separate set query.

8. **P2 — A3’s universal qualification rule eliminates review-held collection.**  
   **Where:** [A1/A3](/Users/michaelrickards/dev/bh2-OUT-23/docs/OUT-23-TICKET.md:48), [qualification](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_manage.py:162), [review storage](/Users/michaelrickards/dev/bh2-OUT-23/backend/services/outreach_research.py:1171).

   **Scenario:** A verified address whose corporate status is unresolved is deliberately stored as `eligibility='review'`, `subscriber_type='unknown'`, without a lawful basis. It necessarily fails `qualified()`. A3 says every failed qualification is rejected, contradicting A1’s continued review-held collection.

   **Change:** Specify separate eligible and review-held admission rules. Preserve the existing review workflow without allowing review-held contacts to enrol or send, and state its independent daily and retention bounds.

VERDICT: CHANGES REQUESTED