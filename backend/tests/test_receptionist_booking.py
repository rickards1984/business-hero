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
        self.queries = []

    async def busy(self, business_id, calendar_id, time_min, time_max):
        """Like Google: only events overlapping the requested window."""
        await asyncio.sleep(0.01)  # let a concurrent caller interleave
        self.queries.append((calendar_id, time_min, time_max))
        lo, hi = datetime.fromisoformat(time_min), datetime.fromisoformat(time_max)
        return {"busy": [
            {"start": s.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "end": e.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
            for s, e in self.events if s < hi and e > lo]}

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
    holder = {"settings": settings}

    class _Res:
        def fetchone(self):
            current = holder["settings"]
            if current is None or not current.get("enabled"):
                return None
            return types.SimpleNamespace(**current)

    class _Sess:
        def execute(self, *a, **k):
            return _Res()

    @contextlib.contextmanager
    def _ctx():
        yield _Sess()

    import db
    monkeypatch.setattr(db, "get_session_context", _ctx)
    return holder


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


# ------------------------------------------- Codex NS-R1 review 1 additions ---

SUNDAY_ALL_DAY = [{"day": d, "start": "00:00", "end": "23:30", "enabled": True}
                  for d in ("monday", "tuesday", "wednesday", "thursday",
                            "friday", "saturday", "sunday")]
FALL_BACK = date(2026, 10, 25)     # clocks go back: 01:00-02:00 happens twice
SPRING_FORWARD = date(2027, 3, 28)  # clocks go forward: 01:00-02:00 never happens


def test_overlap_is_judged_on_real_instants_not_wall_clock():
    """25 Oct 2026: an event 00:45Z-01:15Z. 01:30 in the SECOND (GMT) pass
    is 01:30Z — clear of it. 01:30 in the FIRST (BST) pass is 00:30Z —
    overlapping it for a 60-minute slot. A wall-clock comparison cannot
    tell them apart."""
    b = booking()
    r = rules(business_hours=SUNDAY_ALL_DAY, min_notice_hours=0)
    busy = b.parse_busy([{"start": "2026-10-25T00:45:00Z", "end": "2026-10-25T01:15:00Z"}], r)
    early = datetime(2026, 10, 24, 12, 0, tzinfo=LONDON)
    gmt_pass = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1)
    bst_pass = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=0)
    assert b.check_slot(r, gmt_pass, 60, busy, now=early) is None
    assert b.check_slot(r, bst_pass, 60, busy, now=early) == "clash"


def test_duration_is_real_time_across_the_clock_change():
    b = booking()
    start = datetime(2026, 10, 25, 0, 30, tzinfo=LONDON)   # BST, 23:30Z
    end = b.slot_end(start, 120)
    assert end.astimezone(UTC) == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)


@pytest.mark.parametrize("day,why", [(FALL_BACK, "happens twice"),
                                     (SPRING_FORWARD, "never happens")])
def test_a_clock_change_time_is_refused_at_booking(monkeypatch, google, now_is, day, why):
    _settings_db(monkeypatch, {**SETTINGS, "business_hours": SUNDAY_ALL_DAY,
                               "max_advance_days": 365})
    now_is(datetime(2026, 10, 1, 8, 0, tzinfo=LONDON))
    result = asyncio.run(book(day=day.isoformat(), time="01:30"))
    assert result["success"] is False, f"01:30 {why} on {day}"
    assert google.created == []


def test_clock_change_times_are_not_offered(monkeypatch):
    b = booking()
    r = rules(business_hours=SUNDAY_ALL_DAY, min_notice_hours=0, max_advance_days=365)
    early = datetime(2026, 10, 1, 8, 0, tzinfo=LONDON)
    for day in (FALL_BACK, SPRING_FORWARD):
        starts = [s.strftime("%H:%M") for s in b.free_slots(r, day, 30, [], now=early)]
        assert "01:00" not in starts and "01:30" not in starts, day


def test_the_free_busy_window_is_widened_by_the_buffer():
    lo, hi = booking().freebusy_window(rules(buffer_minutes=15), BST_DAY)
    assert lo == "2026-10-07T09:15:00+01:00"
    assert hi == "2026-10-07T17:15:00+01:00"


def test_an_event_just_before_opening_still_blocks_the_buffer(monkeypatch, google, now_is):
    """Opening 09:30, buffer 15: an event ending 09:25 must block a 09:30
    booking. Asking Google only about 09:30-17:00 would never see it."""
    _settings_db(monkeypatch, {**SETTINGS, "buffer_minutes": 15})
    google.events.append((at(BST_DAY, "09:00"), at(BST_DAY, "09:25")))
    assert asyncio.run(book(time="09:30"))["success"] is False
    assert google.created == []


def test_a_slot_in_the_past_is_refused_even_with_no_notice_period():
    b = booking()
    assert b.check_slot(rules(min_notice_hours=0), at(BST_DAY, "10:00"), 60, [],
                        now=at(BST_DAY, "15:00")) == "in_the_past"


def test_free_busy_is_asked_about_the_booking_calendar(monkeypatch, google, now_is):
    _settings_db(monkeypatch, SETTINGS)
    asyncio.run(book(time="10:00"))
    assert google.queries and all(q[0] == SETTINGS["calendar_id"] for q in google.queries)


def test_switching_booking_off_stops_a_caller_who_was_waiting(monkeypatch, google, now_is):
    """Settings are re-read inside the lock: a caller queued behind another
    booking must not book once the owner has switched booking off."""
    holder = _settings_db(monkeypatch, SETTINGS)
    original_create = google.create

    async def create_then_switch_off(**kw):
        result = await original_create(**kw)
        holder["settings"] = {**SETTINGS, "enabled": False}
        return result
    monkeypatch.setattr(assistant_tools, "create_calendar_event", create_then_switch_off)

    async def both():
        return await asyncio.gather(book(time="10:00", name="Sam"),
                                    book(time="12:00", name="Alex"))
    results = asyncio.run(both())
    assert [r["success"] for r in results].count(True) == 1
    assert len(google.created) == 1


def test_the_callers_number_is_also_stored_privately(monkeypatch, google, now_is):
    """For Phase 2's caller verification: private event data the attendee
    never receives, not only the description."""
    _settings_db(monkeypatch, SETTINGS)
    asyncio.run(book(time="10:00"))
    assert google.created[0].get("private_properties", {}).get("caller_phone") == CALLER


# --- Google's free/busy response, parsed for real ---

class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _google_answers(monkeypatch, body, status=200):
    monkeypatch.setattr(assistant_tools, "_get_google_calendar_token",
                        lambda engine, bid: ("token", "acct", None))

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp(status, body)
    monkeypatch.setattr(assistant_tools.httpx, "AsyncClient", _Client)


CAL = "inductions@group.calendar.google.com"


@pytest.mark.parametrize("body,why", [
    ({"calendars": {CAL: {"errors": [{"domain": "global", "reason": "notFound"}], "busy": []}}},
     "calendar-level error"),
    ({"calendars": {}}, "calendar missing from the answer"),
    ({"calendars": {CAL: {}}}, "no busy list"),
    ({}, "no calendars at all"),
])
def test_an_unusable_free_busy_answer_is_an_error_not_an_empty_diary(monkeypatch, body, why):
    _google_answers(monkeypatch, body)
    result = asyncio.run(assistant_tools.fetch_busy_periods(
        BIZ, CAL, "2026-10-07T09:30:00+01:00", "2026-10-07T17:00:00+01:00"))
    assert result.get("error"), why


def test_a_valid_free_busy_answer_is_returned(monkeypatch):
    busy = [{"start": "2026-10-07T09:00:00Z", "end": "2026-10-07T10:00:00Z"}]
    _google_answers(monkeypatch, {"calendars": {CAL: {"busy": busy}}})
    result = asyncio.run(assistant_tools.fetch_busy_periods(
        BIZ, CAL, "2026-10-07T09:30:00+01:00", "2026-10-07T17:00:00+01:00"))
    assert result == {"busy": busy}


# --- Aria's chat, through the real dispatcher ---

def test_chat_availability_uses_the_business_timezone_and_booking_rules(
        monkeypatch, google, now_is):
    """Through assistant_chat's dispatcher, for a business NOT in London.
    New York, 7 Oct 2026, is UTC-4: an event 14:00-15:00Z is 10:00-11:00
    local. With booking set up, chat offers what the receptionist would:
    opening at 09:30, so 09:30 is offered and 10:00 is not."""
    import assistant_chat
    _settings_db(monkeypatch, SETTINGS)
    ny = ZoneInfo("America/New_York")
    google.events.append((datetime(2026, 10, 7, 10, 0, tzinfo=ny),
                          datetime(2026, 10, 7, 11, 0, tzinfo=ny)))
    now_is(datetime(2026, 10, 6, 8, 0, tzinfo=ny))
    result = asyncio.run(assistant_chat._execute_tool_async(
        "check_calendar_availability", {"date": "2026-10-07", "duration_minutes": 60},
        BIZ, "America/New_York"))
    starts = [x["start"] for x in result["available_slots"]]
    assert starts[0] == "09:30"
    assert "10:00" not in starts and "11:00" in starts
