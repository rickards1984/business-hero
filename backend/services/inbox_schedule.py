"""ARIA-1a — when Aria checks for new mail (docs/ARIA-PROACTIVE-TICKETS.md, ARIA-1 §1).

Every 15 minutes, weekdays 07:00–19:00 UK time: a quick check that fetches
**new** mail only and sorts it. Every 2 hours in the same window, the full
sync runs as before, which also refreshes read and unread state. Outside the
window, nothing runs; the first check of the morning picks up the night's mail.

Pure functions, so the scheduler and the Comms page's "next check" agree.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
QUICK_EVERY = timedelta(minutes=15)
FULL_EVERY = timedelta(hours=2)
FIRST_HOUR, LAST_HOUR = 7, 19          # 07:00 to 19:00 inclusive of the 19:00 check
DESCRIPTION = "every 15 minutes, weekdays 7am to 7pm"


def in_window(now: datetime) -> bool:
    local = now.astimezone(LONDON)
    if local.weekday() >= 5:
        return False
    return FIRST_HOUR <= local.hour < LAST_HOUR or (local.hour == LAST_HOUR and local.minute == 0)


def quick_due(now: datetime, last: Optional[datetime]) -> bool:
    return in_window(now) and (last is None or now - last >= QUICK_EVERY - timedelta(seconds=30))


def full_due(now: datetime, last: Optional[datetime]) -> bool:
    return in_window(now) and (last is None or now - last >= FULL_EVERY)


def due(now: datetime, last_full: Optional[datetime], last_quick: Optional[datetime]) -> Optional[str]:
    """What the scheduler should run now: "full", "quick" or None. A full
    sync, when due, takes the place of that quarter-hour's quick check."""
    if full_due(now, last_full):
        return "full"
    if quick_due(now, last_quick):
        return "quick"
    return None


def _next_opening(after: datetime) -> datetime:
    """The first 07:00 UK on a weekday after `after` (UTC)."""
    local = after.astimezone(LONDON)
    day = local.date() if local.hour < FIRST_HOUR else local.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, FIRST_HOUR, 0, tzinfo=LONDON).astimezone(timezone.utc)


def next_check(now: datetime, last: Optional[datetime] = None) -> datetime:
    """When the next quick check will run (UTC): never a time outside the
    window, where none runs (Codex ARIA-1a review 1, finding 7: Friday 18:55
    said 19:05)."""
    at = max((last + QUICK_EVERY) if last else now, now)
    if in_window(at):
        return at.astimezone(timezone.utc)
    return _next_opening(at)
