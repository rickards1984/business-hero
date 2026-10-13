# BH-013 — Aria sees the booking calendar; the receptionist speaks times and dates naturally

**Tier:** AMBER (feature work; read-only for Aria; wording for the receptionist).
Plan approved by Mike, 13 Oct 2026 ("Yes please. Let's get this done.").
**Builder:** Codex. **Reviewer:** Claude.
**Source:** `docs/BACKLOG.md` rows "Aria sees every business calendar" and
"Receptionist speaks more naturally" (Mike's test calls, 9 Oct 2026).

## Part 1 — Aria sees the booking calendar

New Body's receptionist books inductions into its "NBG Inductions" calendar
(`booking_settings.calendar_id`). Aria's calendar tools read only `primary`,
so she could not see them.

Acceptance:
1. Aria's calendar READ tools (`assistant_tools._list_calendar_events`,
   `_get_calendar_briefing`, and any other read of the owner's events) read
   `primary` AND the business's own booking calendar when one is set and
   differs from primary. Events are merged, ordered by start, de-duplicated
   by event id, and each says which calendar it is on (the calendar's name
   where known, else "booking calendar" / "main calendar").
2. Only THIS business's booking calendar: the calendar id comes from this
   business's `booking_settings` row, scoped by `business_id`. A test proves
   business A never reads business B's booking calendar id.
3. If the booking calendar cannot be read (deleted, permission revoked), the
   primary events are still returned and the answer says the booking calendar
   could not be read. It never fails the whole tool.
4. No write paths change. Calendar WRITES stay refused for Aria (NS-A1,
   `PROHIBITED_ACTIONS`); `test_aria_no_unapproved_actions.py` stays green
   untouched.

## Part 2 — the receptionist speaks naturally

Times reach the voice model as `%H:%M` (it reads "fourteen hundred") and
dates as ISO. Change what the CALL HANDLER passes to the model, not the
booking logic:

1. Times are spoken in 12-hour form: "9am", "2pm", "half past ten",
   "quarter past three", "quarter to five", otherwise "2:40pm". Noon is
   "midday"; midnight is "midnight".
2. Dates: "Wednesday the 7th of October" (ordinal; no year unless it is not
   this year); "today" / "tomorrow" where true, in the business's timezone.
3. One pure, tested formatter module (e.g. `backend/services/spoken_time.py`)
   used by the availability, closed-day and confirmation messages in
   `receptionist_call_handler.py`, and by the "Current time" line in the
   receptionist system prompt (`receptionist_api.py`).
4. `services/booking.py` is NOT changed: it compares instants in UTC, rejects
   clock-change times, and holds a per-calendar lock (NS-R1). Every existing
   booking test stays green untouched, with ONE exception (Codex, build 1,
   13 Oct: the ticket contradicted itself): in
   `test_receptionist_booking.py::test_availability_offered_to_a_caller_is_in_uk_time`
   the two wording assertions `"10:00" not in` / `"11:00" in` the spoken
   message become `"10am" not in` / `"11am" in`. Its fixture, its busy
   period and its meaning (the occupied 10am BST slot is not offered; 11am
   is) stay exactly as they are. No other existing test changes. Machine-readable values the model
   passes BACK to the booking tool (ISO start times) are unchanged — only the
   human-facing words change. If the model needs both, give both
   (e.g. `"2pm (14:00)"` is NOT acceptable to speak; pass the spoken text and
   the ISO value as separate fields).
5. Summer/winter: formatting happens in the business's timezone (Europe/London
   for New Body); a test covers a BST and a GMT date.

## Process

- Tests first, as their own commit, then the implementation.
- `./check.sh full` green before every push. Use `.venv/bin/python` from
  `/Users/michaelrickards/dev/business-hero-2/.venv` (system python3 is 3.9).
- Push the ticket branch only. Never push or merge `main`.
- Do not touch production, migrations, `services/booking.py`, metering,
  entitlement, or Stripe.
- Finish with a short report: what changed, test counts, anything you were
  unsure of.

## Builder completion — Codex, 13 Oct 2026

**North Star:** P2 (grounded calendar reads), P3 (natural British wording),
P9 (business-scoped booking calendar lookup); Phase 1 tool layer.
**Status:** Built; awaiting Claude's independent review. Changes left in the
working tree, without committing or pushing, per Mike's worktree instruction.

Tests were written and run before implementation: the first focused run had
33 failures and 3 passes. Added coverage subsequently includes a missing
booking-settings row and grounding the merged briefing counts. New coverage
comprises 38 parameterised cases across `test_bh013_calendar.py` and
`test_bh013_spoken_time.py`. Only the two explicitly authorised wording
assertions changed in `test_receptionist_booking.py`.

Implementation decisions:
- Google event-list `summary` supplies each calendar's display name, with
  the ticket's fallback labels when absent. Duplicate event IDs retain the
  primary calendar's copy. Offset-aware start times are ordered by instant;
  all-day dates sort at midnight UTC.
- Read the configured booking calendar even if receptionist booking is
  disabled: disabling new bookings does not hide existing events from Aria.
- Keep the existing six spoken availability choices, adding separate ISO
  start values for those choices. Keep today's ISO date separately labelled
  for tool arguments in the system prompt, since spoken "today" alone loses
  the model's date anchor. No booking calculation or write path changed.

Manual behaviour check after review/deployment: open Aria and ask for upcoming
appointments and a calendar briefing; check that an induction on the booking
calendar appears with its calendar name. In an authorised receptionist test
call, ask for availability and confirm a booking; listen for natural dates
and times. `check.sh` verifies the offline inputs and outputs, not live Google
permissions or the voice model's pronunciation. No live calls or external
writes were performed during this build.

**Completion evidence:** `./check.sh full` using this worktree's `.venv`:
1,663 passed, 33 skipped, 854 warnings, 220 subtests passed (pytest, 14.02s).
Gate summary: 5 passed, 0 failed, 1 skipped (optional eslint: no lint script).
TypeScript, Python compilation, Ruff and all five preflight traps passed.
`git diff --check` passed. `test_aria_no_unapproved_actions.py` and all booking
logic tests are included in that full run; the former is untouched.

## Claude review corrections — Codex, 13 Oct 2026

Addressed the two requested findings only (North Star P2/P3):
- The prompt's current time includes the full local weekday, ordinal day,
  month and year, using the shared formatter's explicit full-date mode.
  The separate ISO date for tool arguments remains unchanged.
- Primary calendar events always use "main calendar", even when Google returns
  the owner's email or another summary. Booking calendars retain their summary
  with "booking calendar" as the fallback. This supersedes the primary-summary
  naming decision recorded above.

Tests first: extended `test_system_prompt_current_time_is_spoken` to three
cases (BST, GMT and local midnight), and
`test_calendar_reads_merge_sort_deduplicate_and_label` to two primary summaries
(email and display name). Before fixing: 5 failed, 36 passed. After fixing:
41 passed. Existing booking-calendar name and fallback coverage remains green.

Verification: `./check.sh full` exited 0: 1,666 passed, 33 skipped,
860 warnings, 220 subtests passed. Gate summary: 5 passed, 0 failed,
1 optional eslint skip; all five preflight traps passed.
No commit, push or live external actions performed. For a post-deployment
behaviour check, open Aria and ask which calendar an appointment is on;
primary events should say "main calendar". In an authorised receptionist test
call, ask about "next Tuesday" or "the 20th". Offline checks verify the prompt
context, not the live voice model's interpretation.
