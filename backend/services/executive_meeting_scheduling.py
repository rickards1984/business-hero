"""
Shared scheduling helpers for the Executive Board Meeting feature.

Used by:
- The scheduler tick (briefing_scheduler._check_and_prep_executive_meetings)
- Future Prompt 3 code that recomputes next_meeting_at after a meeting completes
- The Prompt 2 prep service when computing period boundaries

This is a SHARED module deliberately separated from executive_meeting_api.py
so we don't have to modify Prompt 1's code. The scheduling logic mirrors
Prompt 1's private _calculate_next_meeting_time helper but is exposed for reuse.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional, Dict, Any

import pytz


DEFAULT_TIMEZONE = "Europe/London"


def _resolve_tz(tz_name: Optional[str]) -> "pytz.BaseTzInfo":
    """Resolve a tz name to a pytz tzinfo, falling back to DEFAULT_TIMEZONE."""
    try:
        return pytz.timezone(tz_name or DEFAULT_TIMEZONE)
    except Exception:
        return pytz.timezone(DEFAULT_TIMEZONE)


def _parse_meeting_time(time_str: Optional[str]) -> time:
    """Parse a 'HH:MM' string into a time(); falls back to 09:00 on error."""
    try:
        parts = str(time_str or "09:00").split(":")
        hour, minute = int(parts[0]), int(parts[1])
        return time(hour, minute)
    except Exception:
        return time(9, 0)


def compute_next_meeting_time(settings: Dict[str, Any]) -> Optional[datetime]:
    """
    Given a settings row (or a dict-like with the same fields), compute the
    next meeting datetime as a tz-aware datetime in the business's local
    timezone.

    Returns None when:
    - settings is missing or `enabled` is False
    - the schedule cannot be parsed

    NOTE: Returns LOCAL time (with tzinfo). Callers that store this in the DB
    typically convert to UTC via .astimezone(pytz.UTC) — the existing
    Prompt 1 endpoint stores the local-time-with-tzinfo .isoformat() value,
    which Postgres TIMESTAMPTZ handles correctly.
    """
    if not settings or not settings.get("enabled", False):
        return None

    tz = _resolve_tz(settings.get("timezone"))
    now = datetime.now(tz)
    meeting_time = _parse_meeting_time(settings.get("meeting_time"))

    frequency = settings.get("frequency", "weekly")

    if frequency == "weekly":
        # SQL day_of_week: 0=Sun..6=Sat   Python weekday(): 0=Mon..6=Sun
        target_dow = int(settings.get("day_of_week", 1))
        target_weekday = (target_dow - 1) % 7 if target_dow > 0 else 6

        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0:
            today_meeting = tz.localize(datetime.combine(now.date(), meeting_time))
            if today_meeting > now:
                return today_meeting
            days_ahead = 7

        next_date = now.date() + timedelta(days=days_ahead)
        return tz.localize(datetime.combine(next_date, meeting_time))

    if frequency == "monthly":
        target_day = max(1, min(28, int(settings.get("day_of_month", 1))))

        try:
            this_month = now.replace(
                day=target_day,
                hour=meeting_time.hour,
                minute=meeting_time.minute,
                second=0,
                microsecond=0,
            )
            if this_month > now:
                return this_month
        except Exception:
            pass

        if now.month == 12:
            return now.replace(
                year=now.year + 1,
                month=1,
                day=target_day,
                hour=meeting_time.hour,
                minute=meeting_time.minute,
                second=0,
                microsecond=0,
            )
        return now.replace(
            month=now.month + 1,
            day=target_day,
            hour=meeting_time.hour,
            minute=meeting_time.minute,
            second=0,
            microsecond=0,
        )

    return None


# ----------------------------------------------------------------------------
# Period boundaries (for prep data — current vs. previous comparison windows)
# ----------------------------------------------------------------------------

def compute_period_boundaries(
    scheduled_for: datetime,
    frequency: str,
    timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute current and previous period boundaries anchored to the meeting's
    scheduled_for, in the business's local timezone.

    Conventions
    -----------
    - "weekly":  current  = previous 7 days ending the day before the meeting
                 previous = the 7 days before that
    - "monthly": current  = the previous full calendar month
                 previous = the calendar month before that

    All boundary times are tz-aware, anchored to local-midnight (start) and
    local-23:59:59.999999 (end), then returned as UTC ISO strings for
    JSON serialisation. The raw tz-aware datetimes are returned alongside
    so loaders can use them in DB queries.

    Returns
    -------
    {
        "type": "weekly" | "monthly",
        "timezone": "Europe/London",
        "comparison_label": "week-over-week" | "month-over-month",
        "current_start": <datetime, tz-aware>,
        "current_end":   <datetime, tz-aware>,
        "previous_start": <datetime, tz-aware>,
        "previous_end":   <datetime, tz-aware>,
        "current_start_iso":  ISO str (UTC),
        "current_end_iso":    ISO str (UTC),
        "previous_start_iso": ISO str (UTC),
        "previous_end_iso":   ISO str (UTC),
    }
    """
    tz = _resolve_tz(timezone_name)

    # Localise scheduled_for if it isn't already
    if scheduled_for.tzinfo is None:
        scheduled_for = pytz.UTC.localize(scheduled_for)
    scheduled_local = scheduled_for.astimezone(tz)
    scheduled_date_local = scheduled_local.date()

    if frequency == "monthly":
        # Previous full calendar month relative to the meeting date
        first_of_meeting_month = scheduled_date_local.replace(day=1)
        last_of_prev_month = first_of_meeting_month - timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        # Month before that
        last_of_two_back = first_of_prev_month - timedelta(days=1)
        first_of_two_back = last_of_two_back.replace(day=1)

        current_start_d = first_of_prev_month
        current_end_d = last_of_prev_month
        previous_start_d = first_of_two_back
        previous_end_d = last_of_two_back
        comparison_label = "month-over-month"
        period_type = "monthly"
    else:
        # Default to weekly
        current_end_d = scheduled_date_local - timedelta(days=1)
        current_start_d = current_end_d - timedelta(days=6)
        previous_end_d = current_start_d - timedelta(days=1)
        previous_start_d = previous_end_d - timedelta(days=6)
        comparison_label = "week-over-week"
        period_type = "weekly"

    def _localise_start(d: date) -> datetime:
        return tz.localize(datetime.combine(d, time(0, 0, 0)))

    def _localise_end(d: date) -> datetime:
        return tz.localize(datetime.combine(d, time(23, 59, 59, 999999)))

    current_start = _localise_start(current_start_d)
    current_end = _localise_end(current_end_d)
    previous_start = _localise_start(previous_start_d)
    previous_end = _localise_end(previous_end_d)

    return {
        "type": period_type,
        "timezone": tz.zone,
        "comparison_label": comparison_label,
        "current_start": current_start,
        "current_end": current_end,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "current_start_iso": current_start.astimezone(pytz.UTC).isoformat(),
        "current_end_iso": current_end.astimezone(pytz.UTC).isoformat(),
        "previous_start_iso": previous_start.astimezone(pytz.UTC).isoformat(),
        "previous_end_iso": previous_end.astimezone(pytz.UTC).isoformat(),
    }
