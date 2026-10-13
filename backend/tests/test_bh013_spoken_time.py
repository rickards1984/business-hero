"""BH-013: natural British wording without changing booking instants."""
import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from test_receptionist_booking import SETTINGS, _settings_db, book, rch
from test_receptionist_booking import google as _google, now_is as _now_is

google = _google
now_is = _now_is


@pytest.mark.parametrize('hour,minute,expected', [
    (9, 0, '9am'), (14, 0, '2pm'), (10, 30, 'half past ten'),
    (15, 15, 'quarter past three'), (16, 45, 'quarter to five'),
    (14, 40, '2:40pm'), (12, 0, 'midday'), (0, 0, 'midnight'),
])
def test_spoken_clock_forms(hour, minute, expected):
    from services.spoken_time import spoken_time
    assert spoken_time(datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc), 'Europe/London') == expected


@pytest.mark.parametrize('month,expected', [(7, '11am'), (1, '10am')])
def test_spoken_time_converts_bst_and_gmt(month, expected):
    from services.spoken_time import spoken_time
    assert spoken_time(datetime(2026, month, 7, 10, tzinfo=timezone.utc), 'Europe/London') == expected


@pytest.mark.parametrize('day,suffix', [(1, '1st'), (2, '2nd'), (3, '3rd'), (7, '7th'), (11, '11th'), (12, '12th'), (13, '13th'), (21, '21st'), (22, '22nd'), (23, '23rd'), (31, '31st')])
def test_spoken_date_ordinals(day, suffix):
    from services.spoken_time import spoken_date
    result = spoken_date(date(2026, 10, day), 'Europe/London', now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert f'the {suffix} of October' in result
    assert '2026' not in result


def test_spoken_dates_use_local_today_tomorrow_and_other_year():
    from services.spoken_time import spoken_date
    now = datetime(2026, 7, 6, 23, 30, tzinfo=timezone.utc)
    assert spoken_date(date(2026, 7, 7), 'Europe/London', now=now) == 'today'
    assert spoken_date(date(2026, 7, 8), 'Europe/London', now=now) == 'tomorrow'
    assert spoken_date(date(2027, 10, 7), 'Europe/London', now=now) == 'Thursday the 7th of October 2027'


def test_availability_words_and_machine_values_are_separate(monkeypatch, google, now_is):
    now_is(datetime(2026, 10, 1, 8, tzinfo=timezone.utc))
    _settings_db(monkeypatch, SETTINGS)
    result = asyncio.run(rch.handle_receptionist_function_call('check_availability', {'date': '2026-10-07'}, 'A', '', {'timezone': 'Europe/London'}))
    assert 'Wednesday the 7th of October' in result['message']
    assert 'half past nine' in result['message']
    assert '09:30' not in result['message']
    assert result['slots'][0]['start'] == '2026-10-07T09:30:00+01:00'


def test_confirmation_uses_spoken_words_and_preserves_booking(monkeypatch, google, now_is):
    now_is(datetime(2026, 10, 1, 8, tzinfo=timezone.utc))
    _settings_db(monkeypatch, SETTINGS)
    result = asyncio.run(book(time='14:00'))
    assert 'Wednesday the 7th of October at 2pm' in result['message']
    assert google.created[0]['start_time'] == '2026-10-07T14:00:00+01:00'


@pytest.mark.parametrize('day,closed', [('2026-10-11', True), ('2026-10-07', False)])
def test_closed_and_full_days_use_spoken_dates(monkeypatch, google, now_is, day, closed):
    import assistant_tools
    now_is(datetime(2026, 10, 1, 8, tzinfo=timezone.utc))
    _settings_db(monkeypatch, SETTINGS)
    async def no_slots(*args):
        return {'slots': []}
    monkeypatch.setattr(assistant_tools, 'booking_availability', no_slots)
    result = asyncio.run(rch.handle_receptionist_function_call('check_availability', {'date': day}, 'A', '', {'timezone': 'Europe/London'}))
    assert ('Sunday the 11th of October' if closed else 'Wednesday the 7th of October') in result['message']
    assert day not in result['message']


@pytest.mark.parametrize('instant,expected,iso_date', [
    (datetime(2026, 10, 13, 13, tzinfo=timezone.utc), '2pm on Tuesday the 13th of October 2026', '2026-10-13'),
    (datetime(2026, 1, 21, 14, tzinfo=timezone.utc), '2pm on Wednesday the 21st of January 2026', '2026-01-21'),
    (datetime(2026, 7, 6, 23, tzinfo=timezone.utc), 'midnight on Tuesday the 7th of July 2026', '2026-07-07'),
])
def test_system_prompt_current_time_is_spoken(monkeypatch, instant, expected, iso_date):
    import receptionist_api as api
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)
    monkeypatch.setattr(api, 'datetime', Clock)
    cfg = api.ReceptionistConfig(business_id='A')
    results = iter([SimpleNamespace(first=lambda: cfg), SimpleNamespace(first=lambda: None), SimpleNamespace(all=lambda: [])])
    session = SimpleNamespace(exec=lambda *a: next(results))
    result = asyncio.run(api.build_receptionist_system_prompt('A', session))
    assert f'Current time: {expected}\n' in result['system_prompt']
    assert f'Date for tool arguments only (do not read aloud): {iso_date}' in result['system_prompt']
