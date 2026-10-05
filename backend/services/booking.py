"""Booking rules and slot maths, in the business's own time zone (NS-R1).

One place decides whether a time can be booked, used by both the phone
receptionist's availability check and its booking, and by Aria's chat
availability tool. Before this, each did its own maths, the booking did
none, and all of it compared Google's UTC busy times against UK clock
times, so during British Summer Time every existing appointment was an
hour out and occupied slots were offered again.

Everything here is pure: no database, no network. Callers fetch the
settings row and Google's free/busy answer, then ask this module.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/London"
SLOT_STEP_MINUTES = 30

# Why a time cannot be booked. Callers turn these into words.
CLOSED = "closed"
OUTSIDE_HOURS = "outside_hours"
TOO_SOON = "too_soon"
TOO_FAR = "too_far"
CLASH = "clash"
IN_THE_PAST = "in_the_past"
INVALID_TIME = "invalid_time"   # a clock time that happens twice or never

_UTC = ZoneInfo("UTC")

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def now(tz: Optional[ZoneInfo] = None) -> datetime:
    """The current time, aware. A function so tests can fix the clock."""
    return datetime.now(tz or ZoneInfo(DEFAULT_TIMEZONE))


@dataclass(frozen=True)
class BookingRules:
    tz: ZoneInfo
    hours: dict  # weekday name -> (open time, close time); open days only
    appointment_types: tuple
    buffer_minutes: int
    min_notice_hours: int
    max_advance_days: int
    calendar_id: str
    confirmation_message: Optional[str]


def _get(settings, key, default=None):
    if isinstance(settings, dict):
        return settings.get(key, default)
    return getattr(settings, key, default)


def _as_list(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    return json.loads(value)


def _hhmm(value: str) -> time:
    h, m = value.split(":")[:2]
    return time(int(h), int(m))


def rules_from_settings(settings, timezone_name: Optional[str]) -> Optional[BookingRules]:
    """The rules, or None when booking is off or not set up. None means no
    booking — never a default calendar and a default hour."""
    if settings is None or not _get(settings, "enabled", False):
        return None
    hours = {}
    for day in _as_list(_get(settings, "business_hours")):
        if day.get("enabled") and day.get("day") in _DAYS:
            hours[day["day"]] = (_hhmm(day["start"]), _hhmm(day["end"]))

    def _int(key, default):
        value = _get(settings, key)
        return default if value is None else int(value)

    try:
        tz = ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except Exception:
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return BookingRules(
        tz=tz,
        hours=hours,
        appointment_types=tuple(_as_list(_get(settings, "appointment_types"))),
        buffer_minutes=_int("buffer_minutes", 0),
        min_notice_hours=_int("min_notice_hours", 0),
        max_advance_days=_int("max_advance_days", 365),
        calendar_id=_get(settings, "calendar_id") or "primary",
        confirmation_message=_get(settings, "confirmation_message"),
    )


def duration_for(rules: BookingRules, appointment_type: Optional[str], default: int = 60) -> int:
    wanted = (appointment_type or "").strip().lower()
    for apt in rules.appointment_types:
        if (apt.get("name") or "").strip().lower() == wanted:
            return int(apt.get("duration_minutes") or default)
    return default


def local_time(day: date, hour: int, minute: int, tz: ZoneInfo) -> Optional[datetime]:
    """An aware local time, or None if that clock time is ambiguous (happens
    twice when the clocks go back) or nonexistent (skipped when they go
    forward). Both passes of an ambiguous time, or a skipped one, give
    different UTC offsets for fold=0 and fold=1 — that is the test."""
    first = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz, fold=0)
    second = first.replace(fold=1)
    if first.utcoffset() != second.utcoffset():
        return None
    return first


def slot_end(start: datetime, minutes: int) -> datetime:
    """`minutes` of real time after `start`. Python's aware arithmetic adds
    wall-clock time within one tzinfo, which is wrong across a clock change."""
    return (start.astimezone(_UTC) + timedelta(minutes=minutes)).astimezone(start.tzinfo)


def opening(rules: BookingRules, day: date):
    """(open, close) as aware datetimes, or None if closed that day."""
    hours = rules.hours.get(_DAYS[day.weekday()])
    if not hours:
        return None
    start, end = hours
    return (datetime.combine(day, start, tzinfo=rules.tz),
            datetime.combine(day, end, tzinfo=rules.tz))


def freebusy_window(rules: BookingRules, day: date):
    """The window to ask Google about, with its real UTC offset, widened by
    the buffer on both sides: an event ending just before opening still
    blocks the first slot (Codex NS-R1 review 1). A whole local day if
    closed, so callers still get a sane request."""
    window = opening(rules, day) or (
        datetime.combine(day, time(0, 0), tzinfo=rules.tz),
        datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=rules.tz))
    lo = slot_end(window[0], -rules.buffer_minutes)
    hi = slot_end(window[1], rules.buffer_minutes)
    return lo.isoformat(), hi.isoformat()


def parse_busy(busy_entries, rules: BookingRules):
    """Google's free/busy entries (UTC, 'Z') as aware (start, end) pairs in
    the business's zone."""
    out = []
    for b in busy_entries or []:
        s = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
        if s.tzinfo is None:  # never trust a naive time to be local
            s, e = s.replace(tzinfo=ZoneInfo("UTC")), e.replace(tzinfo=ZoneInfo("UTC"))
        out.append((s.astimezone(rules.tz), e.astimezone(rules.tz)))
    return out


def check_slot(rules: BookingRules, start: datetime, duration_minutes: int, busy,
               now: datetime) -> Optional[str]:
    """None if `start` can be booked; otherwise the reason it cannot.

    Every comparison is between real instants (UTC). Comparing aware
    datetimes that share one tzinfo compares wall clock, which cannot tell
    the two passes of 01:30 apart on the night the clocks go back."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=rules.tz)
    s = start.astimezone(_UTC)
    e = s + timedelta(minutes=duration_minutes)
    window = opening(rules, start.astimezone(rules.tz).date())
    if window is None:
        return CLOSED
    if s < window[0].astimezone(_UTC) or e > window[1].astimezone(_UTC):
        return OUTSIDE_HOURS
    n = now.astimezone(_UTC)
    if s < n:
        return IN_THE_PAST
    if s < n + timedelta(hours=rules.min_notice_hours):
        return TOO_SOON
    if start.astimezone(rules.tz).date() > (now.astimezone(rules.tz).date()
                                            + timedelta(days=rules.max_advance_days)):
        return TOO_FAR
    pad = timedelta(minutes=rules.buffer_minutes)
    for b_start, b_end in busy:
        if s - pad < b_end.astimezone(_UTC) and e + pad > b_start.astimezone(_UTC):
            return CLASH
    return None


def free_slots(rules: BookingRules, day: date, duration_minutes: int, busy,
               now: datetime, step_minutes: int = SLOT_STEP_MINUTES):
    """Every bookable start time on `day`, as aware datetimes."""
    window = opening(rules, day)
    if window is None:
        return []
    out = []
    # Walk the wall clock, as a person reads a diary; skip clock times that
    # happen twice or never, which cannot be booked unambiguously.
    # Every start before closing is a candidate; whether the appointment
    # fits is check_slot's real-time judgement, not wall-clock maths.
    minute = window[0].hour * 60 + window[0].minute
    close = window[1].hour * 60 + window[1].minute
    while minute < close:
        candidate = local_time(day, minute // 60, minute % 60, rules.tz)
        if candidate is not None and \
                check_slot(rules, candidate, duration_minutes, busy, now) is None:
            out.append(candidate)
        minute += step_minutes
    return out


# One booking at a time per calendar, so "is it free?" and "book it" are a
# single step for Business Hero's own bookings. What it does NOT cover
# (Codex NS-R1 review 1):
#   - a second Railway replica (AGENTS.md §3.7 requires exactly one — the
#     rate limiter and the Xero refresh lock depend on the same rule);
#   - anyone else writing to the calendar between the check and the create:
#     the owner in Google Calendar, another booking tool, a second business
#     sharing the calendar, or the same calendar under another alias;
#   - Google answering free/busy before a just-created event is visible.
# The window for those is the length of one Google round-trip.
_locks: dict = {}


def calendar_lock(business_id: str, calendar_id: str) -> asyncio.Lock:
    # Keyed by event loop too: an asyncio.Lock belongs to the loop it was
    # first used in. Production has one loop; tests create one per run.
    key = (id(asyncio.get_running_loop()), business_id, calendar_id)
    lock = _locks.get(key)
    if lock is None:
        lock = _locks[key] = asyncio.Lock()
    return lock
