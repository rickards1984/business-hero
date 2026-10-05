# NS-R1 — Codex reviews

## Review 1

| | |
|---|---|
| Reviewed commits | `26821e8` (tests) + `c8b82f0` (fix), `ticket/NS-R1-safe-phone-booking` |
| Session id | `01a10e4e-570d-7df1-95e1-17911c979751` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 39,614` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES**

Reviewed both commits against local `origin/main`. The permitted tests pass: **71 passed, 1 warning**. No edits, pushes or network use. This review serves P4, P8 and the correctness prerequisite.

Findings, most severe first:

1. **[P1] Calendar lookup failures can become permission to book.**  
   [assistant_tools.py:1811](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/assistant_tools.py:1811)  
   `fetch_busy_periods` checks the HTTP status but ignores calendar-level `errors`. A successful HTTP response containing `calendars[id].errors`, or missing the requested calendar/busy field, becomes `{"busy": []}`. The receptionist consequently offers slots and attempts creation without having established availability. Require an explicit, valid busy list for the requested calendar and refuse on calendar-level errors. Tests replace this entire function, so they cannot catch this.

2. **[P1] DST comparisons can miss an actual overlap; nonexistent times are accepted.**  
   [booking.py:138](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/services/booking.py:138), [booking.py:147](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/services/booking.py:147), [receptionist_call_handler.py:402](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/receptionist_call_handler.py:402)  
   Busy intervals are converted to the same `ZoneInfo` object used for candidate slots. Python then compares their wall times, ignoring the distinction between repeated hours.

   On **25 October 2026**, an existing event `00:45Z–01:15Z` becomes `01:45 BST–01:15 GMT`. A proposed `01:30 BST–02:30 GMT` overlaps it, but `start < b_end` evaluates false and the clash is missed.

   Simply attaching `tzinfo` also accepts a nonexistent spring `01:30`. Stripping the timezone before creation loses any repeated-hour disambiguation. Compare instants in UTC, validate local times, and define an ambiguity policy. Duration and minimum-notice arithmetic also need transition tests.

   Date correction: the UK spring transition in 2027 is **28 March**, not 29 March.

3. **[P2] The free/busy window cannot enforce buffers at opening and closing.**  
   [booking.py:120](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/services/booking.py:120)  
   Only opening-to-closing is queried, although clash checking includes a buffer. With opening at 09:30 and a 15-minute buffer, an external event ending at 09:25 can be excluded from the response, allowing a 09:30 booking. The equivalent problem exists after closing, including adjacent-day events. Expand the query window by the buffer.

   [FakeGoogle.busy:189](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/tests/test_receptionist_booking.py:189) ignores both query bounds and returns every event, concealing this defect.

4. **[P2] Chat does not pass the business timezone to the corrected helper.**  
   [assistant_chat.py:62](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/assistant_chat.py:62)  
   `_execute_tool_async` receives the business timezone but omits it when calling `check_calendar_availability`. Non-London businesses therefore still get London availability. Pass `timezone=timezone` and test through the dispatcher, rather than calling the helper directly.

The remaining checks:

- **Lock coverage:** The lock is held across the free/busy request, validation and awaited creation. No await in that sequence escapes it. Check and create use the same `rules.calendar_id`.
- **Limits of double-booking protection:** It only serialises this receptionist path for the same business/calendar string/event loop. External calendar writers can insert between check and create. Other processes, replicas, calendar aliases and different businesses sharing a calendar do not share that lock. Immediate visibility of a successful insertion in subsequent free/busy responses is also assumed. The second-replica limitation is documented at [booking.py:180](/Users/michaelrickards/dev/bh2-NS-R1-review/backend/services/booking.py:180); the broader limitations are not. “One replica” is insufficient to guarantee no double bookings.
- **Ordinary timezone handling:** BST/GMT offsets are now correct. The actual receptionist config **does contain** `receptionist_configs.timezone`: `build_receptionist_system_prompt` returns `_config_to_dict(cfg)`, which includes it. Missing or invalid values fall back to London. Creation consistently receives naive local times plus `timeZone`, with the DST caveat above.
- **Rules:** On ordinary days, opening and closing boundaries are inclusive, exact minimum notice is allowed, the maximum advance date is inclusive, and an exact buffer gap is allowed. Availability and booking share these checks. Slots advance in 30-minute increments from opening. Existing busy intervals spanning midnight/all-day intervals are handled if returned as timestamp ranges. Overnight opening schedules and new appointments crossing midnight are unsupported.
- **Booking switched off:** Missing/disabled settings refuse before creation. There is a timing caveat: settings are loaded **before** waiting for the lock, so disabling booking while a request waits does not revoke that request’s cached permission.
- **Caller-number privacy:** The number is stored in the event description, which is passed to an attendee-bearing event with `sendUpdates=all`. It is therefore not private verification metadata: the supplied attendee and calendar users able to read descriptions can receive it. Prefer private event metadata if its purpose is future caller verification.
- **Chat behaviour:** Past slots are now removed and returned ISO timestamps include offsets. Chat still truncates opening minutes, defaults to 09:00–17:00 on closed days, and omits booking notice/buffer rules. Those dispatcher behaviours predate this change; chat availability must not be represented as receptionist-bookable availability.

The tests provide meaningful ordinary-day guard coverage, including a concurrency test that should fail without the lock. They do **not** establish that every guard is independently protected: for example, the “past slot” case also violates minimum notice. Missing coverage includes real HTTP response parsing, DST transitions, window-sensitive buffers, all-day/midnight intervals, non-London dispatcher wiring, and calendar identity on the free/busy request.

I did not run `check.sh` or make live calls. After repair, the behavioural smoke test is two simultaneous receptionist callers requesting the same induction, plus an appointment entered directly into the target calendar; only one caller should receive confirmation for an occupied slot.
---

### Response to review 1 — Claude Code, 6 October 2026

Every finding taken, tests first (17 new tests, 15 failing before the fix).

| Finding | Action |
|---|---|
| 1 · A 200 with calendar-level `errors`, or a missing calendar/busy list, became an empty diary | `fetch_busy_periods` now requires a valid busy list for the requested calendar and returns an error otherwise. Tested by parsing real response bodies (four bad shapes, one good), not by replacing the function |
| 2 · DST: wall-clock comparison misses overlaps; nonexistent times accepted; duration and notice arithmetic | `check_slot` compares UTC instants throughout; `slot_end` adds real time; `local_time` rejects 01:30 on 25 Oct 2026 (happens twice) and 28 Mar 2027 (never happens) — at booking, and they are never offered. Policy: such times are refused, not guessed. Corrected spring date noted |
| 3 · Free/busy window ignores the buffer | Window widened by the buffer both sides; the fake Google now honours query bounds, and an event ending 09:25 blocks a 09:30 booking with a 15-minute buffer |
| 4 · Chat ignores the business timezone | Chat passes `timezone`, and with booking set up it now offers exactly the receptionist's availability (`assistant_tools.booking_availability`, shared), tested through the real dispatcher for a New York business |
| Settings read before the lock | Re-read inside the lock; refused if switched off or moved to another calendar meanwhile. Tested with a queued caller |
| Caller number visible to attendee | The attendee is the caller themselves, and the business needs it to ring back, so it stays in the description. It is ALSO stored in Google's private extended properties for Phase 2 verification |
| Lock limits not fully documented | `calendar_lock`'s comment now lists them: second replica, other writers to the calendar, aliases, other businesses sharing it, free/busy visibility lag |
| "Past" not independently guarded | `in_the_past` is its own check, tested with no notice period |
| Not addressed | Overnight opening and appointments crossing midnight: unsupported, as before; not a gym or contractor pattern for RC1 |

Mutation-checked: ignoring calendar errors, wall-clock overlap, and no buffer widening each fail their tests. `./check.sh full`: 756 passed.
