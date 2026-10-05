"""NS-R1 — the phone receptionist books safely.

A caller rings New Body's AI receptionist and books an induction (ADR 0001
D17, Mike, 5 Oct 2026). The receptionist already books
(`receptionist_call_handler.py`, `book_appointment`), but review found:

1. It books even when booking is switched off — with no enabled settings it
   fell through to a default hour on the owner's primary calendar.
2. Nothing re-checks the slot at the moment of booking, so two callers, or a
   skipped availability check, double-book.
3. Opening hours, minimum notice, maximum advance and buffers were not
   enforced by the booking — and not even by the availability check, which
   also read opening hours to the hour only (09:30 became 09:00).
4. The caller's phone number was not stored on the booking.
5. **Found while writing these tests, and the main cause of double booking:**
   the availability check sent Google UK clock times labelled as UTC, then
   compared Google's UTC answers against UK clock times. During British
   Summer Time every existing appointment is an hour out, so an occupied
   10:00 is offered again. This also affected Aria's chat availability tool.

Everything here is synthetic and offline: Google is replaced by a fake that
records what would be created and answers free/busy from those records.
"""

import asyncio
import contextlib
import os
import types
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_configured = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
if _configured and not _configured.startswith("sqlite"):
    raise RuntimeError("test_receptionist_booking.py must never run against Postgres.")

import pytest  # noqa: E402

import assistant_tools  # noqa: E402
import receptionist_call_handler as rch  # noqa: E402

LONDON = ZoneInfo("Europe/London")
UTC = ZoneInfo("UTC")
BIZ = "11111111-1111-1111-1111-111111111111"
CALLER = "+447700900123"

BST_DAY = date(2026, 10, 7)   # Wednesday, British Summer Time (UTC+1)
GMT_DAY = date(2026, 11, 4)   # Wednesday, GMT (UTC+0)

HOURS = [
    {"day": d, "start": "09:30", "end": "17:00", "enabled": True}
    for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
] + [{"day": "saturday", "start": "10:00", "end": "14:00", "enabled": False},
     {"day": "sunday", "start": "10:00", "end": "14:00", "enabled": False}]

SETTINGS = {
    "enabled": True,
    "calendar_id": "inductions@group.calendar.google.com",
    "business_hours": HOURS,
    "appointment_types": [{"name": "Induction", "duration_minutes": 60},
                          {"name": "PT taster", "duration_minutes": 30}],
    "buffer_minutes": 0,
    "max_advance_days": 30,
    "min_notice_hours": 2,
    "confirmation_message": "You'll get a text to confirm.",
}


def booking():
    """Imported per test, so a missing module fails each test, not collection."""
    from services import booking as _booking
    return _booking


def at(day, hhmm, tz=LONDON):
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=tz)


def rules(**overrides):
    return booking().rules_from_settings({**SETTINGS, **overrides}, "Europe/London")


def utc_busy(day, start, end):
    """A Google free/busy entry, which Google returns in UTC ('Z')."""
    s = at(day, start).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    e = at(day, end).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"start": s, "end": e}


EARLY_MORNING = lambda day: at(day - timedelta(days=1), "08:00")  # noqa: E731


# ------------------------------------------------- the rules, in UK time ---

def test_busy_times_are_read_in_uk_time_during_bst():
    """An induction 10:00-11:00 BST is 09:00-10:00 UTC at Google. The 10:00
    slot must be busy; the old code freed it and blocked 09:00 instead."""
    b = booking()
    busy = b.parse_busy([utc_busy(BST_DAY, "10:00", "11:00")], rules())
    starts = [s.strftime("%H:%M") for s in
              b.free_slots(rules(), BST_DAY, 60, busy, now=EARLY_MORNING(BST_DAY))]
    assert "10:00" not in starts and "10:30" not in starts
    assert "11:00" in starts and "09:30" not in starts  # 09:30-10:30 overlaps


def test_busy_times_are_read_in_uk_time_in_winter_too():
    b = booking()
    busy = b.parse_busy([utc_busy(GMT_DAY, "10:00", "11:00")], rules())
    starts = [s.strftime("%H:%M") for s in
              b.free_slots(rules(), GMT_DAY, 60, busy, now=EARLY_MORNING(GMT_DAY))]
    assert "10:00" not in starts and "11:00" in starts


def test_the_free_busy_window_is_sent_to_google_with_its_real_offset():
    lo, hi = booking().freebusy_window(rules(), BST_DAY)
    assert lo == "2026-10-07T09:30:00+01:00"
    assert hi == "2026-10-07T17:00:00+01:00"


def test_opening_hours_are_read_to_the_minute():
    starts = booking().free_slots(rules(), BST_DAY, 60, [], now=EARLY_MORNING(BST_DAY))
    assert starts[0].strftime("%H:%M") == "09:30"
    assert starts[-1].strftime("%H:%M") == "16:00"  # 16:00-17:00 is the last that fits


def test_a_closed_day_has_no_slots_and_refuses_a_booking():
    b = booking()
    saturday = date(2026, 10, 10)
    assert b.free_slots(rules(), saturday, 60, [], now=EARLY_MORNING(saturday)) == []
    assert b.check_slot(rules(), at(saturday, "11:00"), 60, [],
                        now=EARLY_MORNING(saturday)) == "closed"


def test_minimum_notice_is_enforced():
    b = booking()
    now = at(BST_DAY, "10:00")
    assert b.check_slot(rules(), at(BST_DAY, "11:00"), 60, [], now=now) == "too_soon"
    assert b.check_slot(rules(), at(BST_DAY, "12:00"), 60, [], now=now) is None
    starts = [s.strftime("%H:%M") for s in b.free_slots(rules(), BST_DAY, 60, [], now=now)]
    assert "11:30" not in starts and "12:00" in starts


def test_maximum_advance_is_enforced():
    b = booking()
    now = at(BST_DAY, "08:00")
    far = BST_DAY + timedelta(days=35)   # a Wednesday: open, but beyond 30 days
    assert far.weekday() == 2
    assert b.check_slot(rules(), at(far, "10:00"), 60, [], now=now) == "too_far"


def test_a_slot_running_past_closing_is_refused():
    assert booking().check_slot(rules(), at(BST_DAY, "16:30"), 60, [],
                                now=EARLY_MORNING(BST_DAY)) == "outside_hours"


def test_a_slot_in_the_past_is_refused():
    assert booking().check_slot(rules(), at(BST_DAY, "10:00"), 60, [],
                                now=at(BST_DAY, "15:00")) in ("too_soon", "in_the_past")


def test_the_buffer_keeps_appointments_apart():
    b = booking()
    r = rules(buffer_minutes=15)
    busy = b.parse_busy([utc_busy(BST_DAY, "10:00", "11:00")], r)
    assert b.check_slot(r, at(BST_DAY, "11:00"), 60, busy, now=EARLY_MORNING(BST_DAY)) == "clash"
    assert b.check_slot(r, at(BST_DAY, "11:15"), 60, busy, now=EARLY_MORNING(BST_DAY)) is None


def test_the_appointment_type_sets_the_length():
    assert booking().duration_for(rules(), "induction") == 60
    assert booking().duration_for(rules(), "PT taster") == 30


def test_disabled_or_missing_settings_mean_no_booking():
    b = booking()
    assert b.rules_from_settings({**SETTINGS, "enabled": False}, "Europe/London") is None
    assert b.rules_from_settings(None, "Europe/London") is None


# ------------------------------------- the receptionist, against a fake Google ---

class FakeGoogle:
    """Answers free/busy from the events it has been asked to create."""

    def __init__(self, existing=()):
        self.events = list(existing)   # (start_aware, end_aware)
        self.created = []

    async def busy(self, business_id, calendar_id, time_min, time_max):
        await asyncio.sleep(0.01)  # let a concurrent caller interleave
        return {"busy": [
            {"start": s.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "end": e.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
            for s, e in self.events]}

    async def create(self, **kw):
        await asyncio.sleep(0.01)
        start = datetime.fromisoformat(kw["start_time"])
        end = datetime.fromisoformat(kw["end_time"])
        if start.tzinfo is None:
            tz = ZoneInfo(kw.get("timezone") or "Europe/London")
            start, end = start.replace(tzinfo=tz), end.replace(tzinfo=tz)
        self.events.append((start, end))
        self.created.append(kw)
        return {"success": True, "event_id": f"evt-{len(self.created)}"}


@pytest.fixture
def google(monkeypatch):
    g = FakeGoogle()
    monkeypatch.setattr(assistant_tools, "fetch_busy_periods", g.busy, raising=False)
    monkeypatch.setattr(assistant_tools, "create_calendar_event", g.create)
    return g


def _settings_db(monkeypatch, settings):
    row = None if settings is None else types.SimpleNamespace(**settings)

    class _Res:
        def fetchone(self):
            return row if (row is not None and row.enabled) else None

    class _Sess:
        def execute(self, *a, **k):
            return _Res()

    @contextlib.contextmanager
    def _ctx():
        yield _Sess()

    import db
    monkeypatch.setattr(db, "get_session_context", _ctx)


@pytest.fixture
def now_is(monkeypatch):
    def _set(dt):
        monkeypatch.setattr(booking(), "now", lambda tz=None: dt)
    _set(EARLY_MORNING(BST_DAY))
    return _set


def book(day="2026-10-07", time="10:00", name="Sam Carter", kind="Induction"):
    return rch.handle_receptionist_function_call(
        function_name="book_appointment",
        arguments={"date": day, "time": time, "caller_name": name,
                   "appointment_type": kind},
        business_id=BIZ, caller_number=CALLER,
        config={"timezone": "Europe/London"},
    )


def test_booking_is_refused_when_booking_is_switched_off(monkeypatch, google, now_is):
    _settings_db(monkeypatch, {**SETTINGS, "enabled": False})
    result = asyncio.run(book())
    assert result["success"] is False
    assert google.created == [], "booked with booking switched off"


def test_booking_is_refused_when_no_settings_exist(monkeypatch, google, now_is):
    _settings_db(monkeypatch, None)
    assert asyncio.run(book())["success"] is False
    assert google.created == []


def test_a_slot_taken_since_it_was_offered_is_refused(monkeypatch, google, now_is):
    _settings_db(monkeypatch, SETTINGS)
    google.events.append((at(BST_DAY, "10:00"), at(BST_DAY, "11:00")))
    result = asyncio.run(book(time="10:00"))
    assert result["success"] is False
    assert google.created == []


@pytest.mark.parametrize("time,why", [("16:30", "past closing"), ("07:00", "before opening")])
def test_a_booking_outside_opening_hours_is_refused(monkeypatch, google, now_is, time, why):
    _settings_db(monkeypatch, SETTINGS)
    assert asyncio.run(book(time=time))["success"] is False, why
    assert google.created == []


def test_a_booking_inside_the_notice_period_is_refused(monkeypatch, google, now_is):
    _settings_db(monkeypatch, SETTINGS)
    now_is(at(BST_DAY, "10:00"))
    assert asyncio.run(book(time="11:00"))["success"] is False
    assert google.created == []


def test_a_good_booking_is_made_once_in_uk_time_with_the_callers_number(
        monkeypatch, google, now_is):
    _settings_db(monkeypatch, SETTINGS)
    result = asyncio.run(book(time="10:00"))
    assert result["success"] is True
    assert len(google.created) == 1
    made = google.created[0]
    assert made["calendar_id"] == SETTINGS["calendar_id"]
    assert made.get("timezone") == "Europe/London"
    start = datetime.fromisoformat(made["start_time"])
    end = datetime.fromisoformat(made["end_time"])
    assert (start.hour, start.minute) == (10, 0) and end - start == timedelta(minutes=60)
    assert CALLER in made["description"], "the caller's number must be on the booking"
    assert "Induction" in made["title"] and "Sam Carter" in made["title"]


def test_two_callers_cannot_take_the_same_slot(monkeypatch, google, now_is):
    """Both check, both see it free, both book — unless the check and the
    booking are one step. Exactly one must succeed."""
    _settings_db(monkeypatch, SETTINGS)

    async def both():
        return await asyncio.gather(book(time="10:00", name="Sam"),
                                    book(time="10:00", name="Alex"))
    results = asyncio.run(both())
    assert sorted(r["success"] for r in results) == [False, True]
    assert len(google.created) == 1


def test_availability_offered_to_a_caller_is_in_uk_time(monkeypatch, google, now_is):
    _settings_db(monkeypatch, SETTINGS)
    google.events.append((at(BST_DAY, "10:00"), at(BST_DAY, "11:00")))
    result = asyncio.run(rch.handle_receptionist_function_call(
        function_name="check_availability",
        arguments={"date": "2026-10-07", "appointment_type": "Induction"},
        business_id=BIZ, caller_number=CALLER, config={"timezone": "Europe/London"},
    ))
    assert result["success"] is True
    assert "10:00" not in result["message"]
    assert "11:00" in result["message"]


# --------------------------------------------- Aria's chat availability tool ---

def test_arias_chat_availability_is_in_uk_time_too(monkeypatch, google, now_is):
    google.events.append((at(BST_DAY, "10:00"), at(BST_DAY, "11:00")))
    result = asyncio.run(assistant_tools.check_calendar_availability(
        business_id=BIZ, date="2026-10-07", duration_minutes=60,
        start_hour=9, end_hour=17, calendar_id="primary"))
    starts = [s["start"] for s in result["available_slots"]]
    assert "10:00" not in starts and "10:30" not in starts
    assert "09:00" in starts and "11:00" in starts
