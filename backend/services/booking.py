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


def opening(rules: BookingRules, day: date):
    """(open, close) as aware datetimes, or None if closed that day."""
    hours = rules.hours.get(_DAYS[day.weekday()])
    if not hours:
        return None
    start, end = hours
    return (datetime.combine(day, start, tzinfo=rules.tz),
            datetime.combine(day, end, tzinfo=rules.tz))


def freebusy_window(rules: BookingRules, day: date):
    """The window to ask Google about, with its real UTC offset. A whole
    local day if closed, so callers still get a sane request."""
    window = opening(rules, day) or (
        datetime.combine(day, time(0, 0), tzinfo=rules.tz),
        datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=rules.tz))
    return window[0].isoformat(), window[1].isoformat()


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
    """None if `start` can be booked; otherwise the reason it cannot."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=rules.tz)
    end = start + timedelta(minutes=duration_minutes)
    window = opening(rules, start.astimezone(rules.tz).date())
    if window is None:
        return CLOSED
    if start < window[0] or end > window[1]:
        return OUTSIDE_HOURS
    if start < now + timedelta(hours=rules.min_notice_hours):
        return TOO_SOON
    if start.astimezone(rules.tz).date() > (now.astimezone(rules.tz).date()
                                            + timedelta(days=rules.max_advance_days)):
        return TOO_FAR
    pad = timedelta(minutes=rules.buffer_minutes)
    for b_start, b_end in busy:
        if start - pad < b_end and end + pad > b_start:
            return CLASH
    return None


def free_slots(rules: BookingRules, day: date, duration_minutes: int, busy,
               now: datetime, step_minutes: int = SLOT_STEP_MINUTES):
    """Every bookable start time on `day`, as aware datetimes."""
    window = opening(rules, day)
    if window is None:
        return []
    out = []
    cursor = window[0]
    while cursor + timedelta(minutes=duration_minutes) <= window[1]:
        if check_slot(rules, cursor, duration_minutes, busy, now) is None:
            out.append(cursor)
        cursor += timedelta(minutes=step_minutes)
    return out


# One booking at a time per calendar, so "is it free?" and "book it" are a
# single step. In-process: correct because Railway runs exactly one replica
# (AGENTS.md §3.7 — the same constraint the rate limiter and the Xero refresh
# lock already depend on). A second replica would reopen double booking.
_locks: dict = {}


def calendar_lock(business_id: str, calendar_id: str) -> asyncio.Lock:
    # Keyed by event loop too: an asyncio.Lock belongs to the loop it was
    # first used in. Production has one loop; tests create one per run.
    key = (id(asyncio.get_running_loop()), business_id, calendar_id)
    lock = _locks.get(key)
    if lock is None:
        lock = _locks[key] = asyncio.Lock()
    return lock
