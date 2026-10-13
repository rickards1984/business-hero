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
