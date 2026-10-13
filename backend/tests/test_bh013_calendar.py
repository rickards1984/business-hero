"""BH-013: offline calendar reads, grounded in tenant-scoped SQLite rows."""
from urllib.parse import unquote

import httpx
import pytest
from sqlalchemy import create_engine, text

import assistant_tools as tools


@pytest.fixture
def calendars(monkeypatch):
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE email_accounts (id TEXT, business_id TEXT, provider TEXT, email_address TEXT, token_ciphertext TEXT, refresh_token_ciphertext TEXT, created_at TEXT)'))
        conn.execute(text('CREATE TABLE booking_settings (business_id TEXT, calendar_id TEXT)'))
        for bid in ('A', 'B'):
            conn.execute(text("INSERT INTO email_accounts VALUES (:bid, :bid, 'google', 'owner@example.com', 'token', NULL, '2026')"), {'bid': bid})
            conn.execute(text('INSERT INTO booking_settings VALUES (:bid, :cal)'), {'bid': bid, 'cal': f'{bid}/bookings'})
    monkeypatch.setattr(tools, '_decrypt_token', lambda token: token)
    calls = []
    bodies = {
        'primary': {'summary': 'Main diary', 'items': [event('later', '2026-10-07T10:00:00Z'), event('same', '2026-10-07')]},
        'A/bookings': {'summary': 'NBG Inductions', 'items': [event('earlier', '2026-10-07T10:30:00+01:00'), event('same', '2026-10-07')]},
        'B/bookings': {'items': [event('private-B', '2026-10-07')]},
    }

    def get(url, **kwargs):
        cal = unquote(url.split('/calendars/')[1].removesuffix('/events'))
        calls.append(cal)
        body = bodies[cal]
        if isinstance(body, Exception):
            raise body
        return httpx.Response(body if isinstance(body, int) else 200, json={} if isinstance(body, int) else body)
    monkeypatch.setattr(tools.httpx, 'get', get)
    yield engine, calls, bodies
    engine.dispose()


def event(eid, start):
    key = 'dateTime' if 'T' in start else 'date'
    return {'id': eid, 'start': {key: start}, 'end': {key: start}}


@pytest.mark.parametrize('primary_summary', ['owner@example.com', 'Main diary'])
def test_calendar_reads_merge_sort_deduplicate_and_label(calendars, primary_summary):
    engine, calls, bodies = calendars
    bodies['primary']['summary'] = primary_summary
    result = tools._list_calendar_events(engine, 'A', {})
    assert calls == ['primary', 'A/bookings']
    assert [e['id'] for e in result['events']] == ['same', 'earlier', 'later']
    assert result['count'] == 3
    assert result['events'][1]['calendar'] == 'NBG Inductions'
    assert result['events'][2]['calendar'] == 'main calendar'


def test_calendar_reads_are_scoped_to_the_business(calendars):
    engine, calls, _ = calendars
    tools._list_calendar_events(engine, 'A', {'calendar_id': 'B/bookings'})
    assert calls == ['primary', 'A/bookings']
    calls.clear()
    result = tools._list_calendar_events(engine, 'B', {})
    assert calls == ['primary', 'B/bookings']
    assert any(e['id'] == 'private-B' for e in result['events'])


@pytest.mark.parametrize('calendar_id', [None, '', 'primary'])
def test_missing_or_primary_booking_calendar_is_only_read_once(calendars, calendar_id):
    engine, calls, _ = calendars
    with engine.begin() as conn:
        conn.execute(text('UPDATE booking_settings SET calendar_id=:cal WHERE business_id=:bid'), {'cal': calendar_id, 'bid': 'A'})
    tools._list_calendar_events(engine, 'A', {})
    assert calls == ['primary']


@pytest.mark.parametrize('failure', [403, 404, httpx.ReadTimeout('offline')])
def test_unreadable_booking_calendar_keeps_primary_and_warns(calendars, failure):
    engine, _, bodies = calendars
    bodies['A/bookings'] = failure
    result = tools._list_calendar_events(engine, 'A', {})
    assert result['count'] == 2
    assert 'booking calendar could not be read' in ' '.join(result['warnings']).lower()
    briefing = tools._get_calendar_briefing(engine, 'A', {})
    assert briefing['warnings']


def test_calendar_labels_fall_back_when_names_are_missing(calendars):
    engine, _, bodies = calendars
    for body in bodies.values():
        body.pop('summary', None)
    result = tools._list_calendar_events(engine, 'A', {})
    assert {e['calendar'] for e in result['events']} == {'main calendar', 'booking calendar'}


def test_no_booking_settings_row_reads_primary_only(calendars):
    engine, calls, _ = calendars
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM booking_settings WHERE business_id=:bid'), {'bid': 'A'})
    result = tools._list_calendar_events(engine, 'A', {})
    assert calls == ['primary']
    assert result['count'] == 2


def test_briefing_includes_the_booking_calendar_with_grounded_counts(calendars):
    engine, calls, _ = calendars
    result = tools._get_calendar_briefing(engine, 'A', {})
    assert calls == ['primary', 'A/bookings', 'primary', 'A/bookings']
    assert result['today']['total'] == 3
    assert result['week']['total_events'] == 3
    events = result['today']['upcoming'] + result['today']['completed']
    assert any(e['id'] == 'earlier' and e['calendar'] == 'NBG Inductions' for e in events)
