"""Pure, timezone-aware wording for the receptionist's human-facing text."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_HOURS = ('twelve', 'one', 'two', 'three', 'four', 'five', 'six',
          'seven', 'eight', 'nine', 'ten', 'eleven')


def spoken_time(value: datetime, timezone: str) -> str:
    local = value.astimezone(ZoneInfo(str(timezone)))
    hour, minute = local.hour, local.minute
    if minute == 0:
        if hour == 0:
            return 'midnight'
        if hour == 12:
            return 'midday'
        return f"{hour % 12 or 12}{'am' if hour < 12 else 'pm'}"
    if minute == 15:
        return f'quarter past {_HOURS[hour % 12]}'
    if minute == 30:
        return f'half past {_HOURS[hour % 12]}'
    if minute == 45:
        return f'quarter to {_HOURS[(hour + 1) % 12]}'
    return f"{hour % 12 or 12}:{minute:02d}{'am' if hour < 12 else 'pm'}"


def spoken_date(value: date, timezone: str, *, now: datetime, full: bool = False) -> str:
    """Use full=True for a date anchor with weekday and year, never a relative date."""
    tz = ZoneInfo(str(timezone))
    today = now.astimezone(tz).date()
    day = value.astimezone(tz).date() if isinstance(value, datetime) else value
    if not full and day == today:
        return 'today'
    if not full and day == today + timedelta(days=1):
        return 'tomorrow'
    suffix = 'th' if 11 <= day.day % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day.day % 10, 'th')
    year = f' {day.year}' if full or day.year != today.year else ''
    return f"{day.strftime('%A')} the {day.day}{suffix} of {day.strftime('%B')}{year}"
